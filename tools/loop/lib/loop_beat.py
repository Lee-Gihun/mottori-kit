#!/usr/bin/env python3
"""Run one beat of the improvement loop: its lock, its log, its workers, its state file and its end.

A beat (tools/loop/lib/loop_papers.py, or the beat of a source an installation added) is a list of stages that call the methods of
Beat in order. A stage that needs a model runs it through tools/loop/lib/loop_worker.py, which walks the
stage's runtimes and reads each run's outcome from the data the worker tool leaves.
The other tools a beat uses (the worker tool, now.py, the applier, the watchdog, triggers.py) are
called as programs from the instance root, so a test can replace each with a stand-in. Every
program a beat starts while it holds the lock inherits the lock's descriptor, so a worker that
outlives its beat keeps the cycle locked until it ends."""
import datetime
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import traceback

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_worker  # noqa: E402
from loop_stores import PAPERS_BASE  # noqa: E402
from loop_common import stop_group  # noqa: E402
from loop_contracts import LENS_HEADING, lens_skill  # noqa: E402
import safeio  # noqa: E402

# Where the worker templates are, and the loop's document a template may name.
PROMPTS = "system/loop/prompts"
# The engine documents a worker reads for the kit's philosophy and decisions, with what to read of each.
ENGINE_DOCS = (("README.md", "its first section"), ("system/specs/kit-decisions.md", ""))
# Placeholders every prompt template may hold; others are the beat's own (see render()).
PROTECTED = "{{PROTECTED}}"
LENS = "{{LENS_HEADING}}"
# Added to the prompt of a stage whose output is one file: every worker runs read-only, and the loop
# writes the file from the answer.
ANSWER_NOTE = ("\nThis run cannot write files. Where this prompt says to write `{}`, give its whole content as "
               "your final answer and nothing else; the loop writes the file from your answer.\n")
# The longest one worker of a beat may run, in seconds; the papers beat may set its own.
WORKER_TIMEOUT = 7200


def nonempty(path):
    """Whether path exists with more than zero bytes (any kind of file)."""
    try:
        return os.stat(path).st_size > 0
    except OSError:
        return False


def wc_bytes(path):
    """The size of path right-aligned in eight columns, the form the beat logs carry."""
    return f"{os.path.getsize(path):8d}"


def shell_status(returncode):
    """A child's exit status as a shell reports it: 128 plus the signal for a killed child."""
    return 128 - returncode if returncode < 0 else returncode


def write_json(path, data, **dump):
    """Replace path with data as JSON (no final newline) through safeio.atomic_write."""
    safeio.atomic_write(path, json.dumps(data, **dump))


def common_values(root="."):
    """The values of the placeholders every template may hold, for the installation at root.

    ENGINE_DOCS and LENS_SKILL name only files this installation has; a missing one is said in the text,
    so the worker writes one line about it and goes on. A beat adds its own placeholders when it renders."""
    docs = [f"`{p}`" + (f" ({what})" if what else "") for p, what in ENGINE_DOCS if os.path.isfile(os.path.join(root, p))]
    return {"ENGINE_DOCS": ", ".join(docs) or "no engine document (this installation has neither "
                                                + " nor ".join(p for p, _ in ENGINE_DOCS) + "; say so in one line)",
            "PAPERS_CYCLES": PAPERS_BASE, "LENS_SKILL": lens_skill(root)}


def render(template, dst, values, extra=None, remove_first=False):
    """Write the prompt template with each {{NAME}} of values filled in; return whether it was written.

    extra(text) may fill the beat's own placeholders after values. {{PROTECTED}} becomes the never
    list and the allowed area as tools/loop/loop_policy.py renders them, and {{LENS_HEADING}} the heading
    of the optional section on what the lenses changed. A failure prints its traceback."""
    try:
        if remove_first and os.path.lexists(dst):
            os.unlink(dst)
        with open(template, encoding="utf-8") as f:
            text = f.read()
        for name, value in {**common_values(), **values}.items():
            text = text.replace("{{" + name + "}}", value)
        if extra:
            text = extra(text)
        if PROTECTED in text:
            import loop_policy
            text = text.replace(PROTECTED, loop_policy.render())
        text = text.replace(LENS, LENS_HEADING)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)
        return True
    except Exception:  # noqa: BLE001  The stage records the failure; the traceback says why.
        traceback.print_exc()
        return False


class Beat:
    """One run of a beat. Paths are relative to the instance root, which is the working folder."""

    def __init__(self, log_path, worker_timeout=None):
        self.log_path = log_path
        # Workers run in their own session with no input, under this many seconds each.
        self.worker_timeout = worker_timeout or WORKER_TIMEOUT
        self.fails = []
        self.lock_file = None
        self.active = set()
        self.active_lock = threading.Lock()

    # The log and the failures of this run.
    def log(self, message):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")

    def fail(self, stage, reason):
        """Record that stage failed, with reason for people."""
        self.fails.append((stage, reason))
        self.log(f"FAIL: {reason}")

    @property
    def failures(self):
        return "; ".join(reason for _, reason in self.fails)

    @property
    def failed_stages(self):
        """The stages that failed in this run, each once, in order."""
        return list(dict.fromkeys(stage for stage, _ in self.fails))

    # The lock: one run of a beat at a time; a second run skips.
    def take_lock(self, path):
        """Take the beat's lock. False when another run holds the lock."""
        f = open(path, "a")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.lock_file = f
        return True

    def release_lock(self):
        if self.lock_file is not None:
            self.lock_file.close()
            self.lock_file = None

    def _fds(self):
        return (self.lock_file.fileno(),) if self.lock_file is not None else ()

    # Programs.
    def run(self, args, out=None, mode="a"):
        """Run a program; its output goes to the file out (the log when None). Return its status."""
        with open(out or self.log_path, mode, encoding="utf-8") as f:
            p = subprocess.run(args, stdout=f, stderr=subprocess.STDOUT, pass_fds=self._fds())
        return shell_status(p.returncode)

    def tool(self, name, *args):
        """Run python3 tools/<name> with args, its output going to the log. Return its status."""
        return self.run(["python3", os.path.join("tools", name), *args])

    def backlog(self, args):
        """Let the applier take earlier cycles first; its failure is logged, not a failure of this run."""
        rc = self.tool("loop/papers_apply.py", "--backlog", *args)
        if rc:
            self.log(f"backlog apply ended with exit {rc} (the applier's lines above name each cycle)")

    def journal(self, text, failure_line):
        """Add one line to the private journal through now.py."""
        if self.tool("now.py", "log", "--private", f"[system/state] {text}"):
            self.log(failure_line)

    def watchdog(self):
        """Run the watchdog after this run when the instance has one; it ends 0 or 1 when it completed."""
        if os.path.isfile(os.path.join("tools", "loop", "loop_watchdog.py")):
            rc = self.tool("loop/loop_watchdog.py", "--no-auth")
            if rc > 1:
                self.log(f"watchdog FAILED rc={rc}")

    # Workers.
    def walk(self, stage, prompt, receipt, answer_file=None):
        """Run the worker tool on prompt for stage through tools/loop/lib/loop_worker.py; return the run's outcome.

        Every worker runs read-only. A runtime that could not be called is logged and hands the stage
        to the next one. With answer_file, the prompt says that the answer is the file's whole content,
        and the answer of a run that succeeded becomes the file. Each worker's exit status is noted at
        the end of its receipt."""
        def next_runtime(o):
            self.log(f"{stage}: {o['runtime']} cannot be called {json.dumps({'unavailable': o['unavailable']})} "
                     f"({o['run']}), next runtime")
        if answer_file and os.path.isfile(prompt):   # a prompt that failed to render stays missing
            with open(prompt, "a", encoding="utf-8") as f:
                f.write(ANSWER_NOTE.format(answer_file))
        o = loop_worker.run_stage(stage, ["python3", os.path.join("tools", "fresh_worker.py")], prompt, receipt,
                                  self._launch, ".", on_unavailable=next_runtime)
        if o.get("status") == loop_worker.CEILING:
            self.log(f"{stage}: not started: {o['unavailable']}")
        if not o["unavailable"] and answer_file and o["run"]:
            self._take_answer(o, answer_file)
        return o

    def _launch(self, args, receipt):
        """Start one worker with its output in receipt; return (exit status, whether it timed out)."""
        rc, timed = self._bounded(args, receipt)
        with open(receipt, "a", encoding="utf-8") as f:
            f.write(f"exit {rc}\n")
        return rc, timed

    def _take_answer(self, o, dst):
        """The answer of a read-only run that succeeded becomes dst, a new file moved into its place."""
        meta = o["meta"]
        try:
            if meta.get("capability") == "read-only" and meta.get("status") == "success" and meta.get("result_bytes"):
                # A new file moved into place: a link already at dst is replaced, never written through.
                with open(os.path.join(o["run"], "result.txt"), "rb") as f:
                    safeio.atomic_write(dst, f.read(), 0o600)
        except Exception:  # noqa: BLE001  The stage then finds no file and fails on that.
            traceback.print_exc()

    def _bounded(self, args, receipt):
        """Run a worker in its own process group under worker_timeout; return (status, timed out).
        A timeout is noted in the receipt and has status 124."""
        with open(receipt, "w", encoding="utf-8") as out:
            p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                 start_new_session=True, pass_fds=self._fds())
            with self.active_lock:
                self.active.add(p)
            try:
                rc = p.wait(timeout=self.worker_timeout)
            except subprocess.TimeoutExpired:
                stop_group(p)
                os.write(out.fileno(), f"TIMEOUT {float(self.worker_timeout):g}s\n".encode())
                return 124, True
            finally:
                with self.active_lock:
                    self.active.discard(p)
            stop_group(p)   # Whatever the worker left in its group does not outlive it.
            return (rc & 0xFF if rc < 0 else rc), False

    def stop_workers_on_signals(self):
        """A termination of this run stops its bounded workers, which run in sessions of their own."""
        def on_signal(n, _frame):
            with self.active_lock:
                running = list(self.active)
            for p in running:
                stop_group(p)
            sys.exit(128 + n)
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)

    def parallel(self, jobs):
        """Run each (key, function) in its own thread; return {key: result} once all have ended."""
        results, threads = {}, []
        for key, fn in jobs:
            t = threading.Thread(target=lambda k=key, f=fn: results.__setitem__(k, f()), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        return results

    def in_log(self, fn, *args):
        """Run fn with its printed output and any traceback going to the log; return whether it ended well."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            stdout, stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = f
            try:
                fn(*args)
                return True
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                return False
            finally:
                sys.stdout, sys.stderr = stdout, stderr
