#!/usr/bin/env python3
"""The way into the improvement loop: options.py allows a source to send, loops.py runs, schedules and
unschedules a source, `off loop` takes everything back, and on a platform other than macOS every step
but status refuses with one sentence.

Every case runs in a scratch copy of tools/ with its own configuration and HOME. launchctl is a
stand-in that keeps its loaded labels in a file, so nothing is scheduled on this machine, and no
model program is started."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

from testlib import add_loop_source, copy_tools, macos_only

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/loops.py",
    "tools/loop/lib/loop_jobs.py",
    "tools/loop/lib/loop_platform.py",
    "tools/loop/lib/loop_sending.py",
    "tools/loop/lib/loop_macos_schedule.py",
    "tools/options.py",
)
CONFIG = {"schema_version": 4, "instance": {"name": "fixture"},
          "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None, "legacy_public_tracks": []},
          "egress": {"model_send": {"deny_prefixes": ["_private/"], "allow_prefixes": []}}}
LAUNCHCTL = """#!/usr/bin/python3
import os, sys
state = os.path.join(os.environ["HOME"], "loaded.txt")
labels = set(open(state).read().split()) if os.path.exists(state) else set()
open(os.path.join(os.environ["HOME"], "launchctl.log"), "a").write(" ".join(sys.argv[1:]) + "\\n")
cmd = sys.argv[1]
if cmd == "list":
    print("PID\\tStatus\\tLabel")
    for label in sorted(labels):
        print(f"-\\t0\\t{label}")
elif cmd == "print":
    sys.exit(0 if sys.argv[2].rsplit("/", 1)[-1] in labels else 113)
elif cmd == "bootstrap":
    labels.add(os.path.basename(sys.argv[3])[:-len(".plist")])
elif cmd == "bootout":
    label = sys.argv[2].rsplit("/", 1)[-1]
    if label not in labels:
        sys.exit(3)
    labels.discard(label)
open(state, "w").write("\\n".join(sorted(labels)))
"""


@contextlib.contextmanager
def instance(config=None):
    """Yield (root, env): a scratch instance with the loop's files and a stand-in launchctl."""
    parent = tempfile.mkdtemp(prefix="loop-way-in-")
    try:
        root = os.path.join(parent, "inst")
        copy_tools(ROOT, root)
        add_loop_source(root)
        shutil.copytree(os.path.join(ROOT, "system", "loop", "launchd"), os.path.join(root, "system", "loop", "launchd"))
        os.makedirs(os.path.join(root, "instance"))
        write(root, "instance/config.json", json.dumps(config or CONFIG, indent=2) + "\n")
        home, bindir = os.path.join(parent, "home"), os.path.join(parent, "bin")
        os.makedirs(home)
        os.makedirs(bindir)
        write(bindir, "launchctl", LAUNCHCTL)
        os.chmod(os.path.join(bindir, "launchctl"), 0o755)
        # The cycle scripts are stand-ins that only say they ran; notes is the test's added source.
        write(root, "tools/loop/papers_cycle.sh", "echo papers cycle ran with \"$@\"\n")
        env = {"HOME": home, "PATH": bindir + os.pathsep + "/usr/bin:/bin", "MOTTORI_INSTANCE": root,
               "PYTHONDONTWRITEBYTECODE": "1"}
        yield root, env
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def write(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def config(root):
    with open(os.path.join(root, "instance", "config.json"), encoding="utf-8") as f:
        return json.load(f)


def run(root, env, tool, *args):
    return subprocess.run([sys.executable, os.path.join(root, "tools", *tool.split("/")), *args], cwd=root, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)


def label(root, job):
    """The schedule label the loop gives job in the installation at root (loop_config.job_label)."""
    folder = hashlib.sha1(os.path.realpath(root).encode("utf-8")).hexdigest()[:8]
    return f"local.fixture-{folder}.loop.{job}"


def agents(env):
    folder = os.path.join(env["HOME"], "Library", "LaunchAgents")
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


# On another platform these steps refuse; test_another_platform_refuses covers that.
MACOS = "the loop's sandbox, scheduler and alerts"


def test_status_says_no_source_may_send_before_on_loop():
    with instance() as (root, env):
        r = run(root, env, "options.py")
        assert "] Improvement loop (loop)" in r.stdout, r.stdout
        r = run(root, env, "loop/loops.py", "status")
        assert r.returncode == 0 and r.stdout.startswith("sending: no source allowed"), r.stdout


@macos_only(MACOS)
def test_nothing_runs_before_a_source_may_send():
    with instance() as (root, env):
        r = run(root, env, "options.py")
        assert "[off] Improvement loop" in r.stdout, r.stdout
        for cmd in ("run", "start"):
            r = run(root, env, "loop/loops.py", cmd, "notes")
            assert r.returncode == 1 and r.stdout.strip() == (
                "notes is not allowed to send to a model runtime. To allow it: python3 tools/options.py on loop"), r.stdout
        assert agents(env) == []


@macos_only(MACOS)
def test_on_loop_takes_a_yes_and_allows_only_the_chosen_source():
    with instance() as (root, env):
        before = config(root)
        r = run(root, env, "options.py", "on", "loop")
        assert r.returncode == 1 and "Nothing was changed" in r.stdout and "sources=all yes" in r.stdout, r.stdout
        assert "notes: every file in notes/" in r.stdout and "papers: the search queries" in r.stdout
        assert "The loop needs Claude Code or Codex installed, and neither is" in r.stdout, r.stdout   # none on this PATH
        assert config(root) == before
        r = run(root, env, "options.py", "on", "loop", "sources=notes", "yes")
        assert r.returncode == 0, r.stdout + r.stderr
        allow = config(root)["egress"]["model_send"]["allow_prefixes"]
        assert allow == ["_private/notes/"], allow
        assert config(root).get("loop") is None and agents(env) == []
        r = run(root, env, "loop/loops.py", "run", "papers")
        assert r.returncode == 1 and "papers is not allowed" in r.stdout, r.stdout
        r = run(root, env, "loop/loops.py", "run", "notes")
        assert r.returncode == 0 and "notes cycle ran with --force" in r.stdout, r.stdout + r.stderr
        r = run(root, env, "options.py")
        assert "[notes may send; nothing scheduled] Improvement loop" in r.stdout, r.stdout


@macos_only(MACOS)
def test_start_and_stop_schedule_a_source_with_the_health_check():
    cfg = json.loads(json.dumps(CONFIG))
    cfg["egress"]["model_send"]["allow_prefixes"] = ["_private/notes/", "_private/work/papers/"]
    with instance(cfg) as (root, env):
        r = run(root, env, "loop/loops.py", "start", "notes")
        assert r.returncode == 0 and "notes: scheduled, Sunday 21:00" in r.stdout and "health check: scheduled, daily 06:00" in r.stdout, r.stdout
        assert agents(env) == sorted([label(root, "notes") + ".plist", label(root, "health") + ".plist"]), agents(env)
        with open(os.path.join(env["HOME"], "Library", "LaunchAgents", label(root, "notes") + ".plist"), encoding="utf-8") as f:
            plist = f.read()
        assert "tools/loop/notes_cycle.sh</string>" in plist and "<key>Weekday</key><integer>0</integer>" in plist, plist
        with open(os.path.join(env["HOME"], "Library", "LaunchAgents", label(root, "health") + ".plist"), encoding="utf-8") as f:
            health = f.read()
        # The scheduled health check probes no login, so the check itself starts no model program.
        assert "<string>--daily</string>" in health and "<string>--no-auth</string>" in health, health
        run(root, env, "loop/loops.py", "start", "papers")
        r = run(root, env, "loop/loops.py", "status")
        lines = r.stdout.splitlines()
        assert lines[1:] == ["  notes: reads notes/ only", "notes         Sunday 21:00     scheduled", "  last cycle: none yet",
                             "papers        Wednesday 03:00  scheduled", "  last cycle: none yet",
                             "health check  daily 06:00      scheduled", "  last run: never"], lines
        r = run(root, env, "loop/loops.py", "stop", "notes")
        assert r.returncode == 0 and agents(env) == [label(root, "health") + ".plist", label(root, "papers") + ".plist"], agents(env)
        r = run(root, env, "loop/loops.py", "stop", "papers")
        assert r.returncode == 0 and "health check: unscheduled" in r.stdout and agents(env) == [], r.stdout
    cfg["loop"] = {"health_started_by": "my own daily job", "job_prefix": "org.example"}
    with instance(cfg) as (root, env):
        r = run(root, env, "loop/loops.py", "start", "papers")
        assert agents(env) == ["org.example.papers.plist"] and "started by my own daily job" in r.stdout, r.stdout


@macos_only(MACOS)
def test_on_loop_says_nothing_is_scheduled_only_when_it_read_so():
    cfg = json.loads(json.dumps(CONFIG))
    cfg["egress"]["model_send"]["allow_prefixes"] = ["_private/notes/"]
    with instance(cfg) as (root, env):
        r = run(root, env, "options.py", "on", "loop", "sources=notes", "yes")
        assert r.returncode == 0 and "Nothing is scheduled." in r.stdout, r.stdout
        run(root, env, "loop/loops.py", "start", "notes")
        r = run(root, env, "options.py", "on", "loop", "sources=notes", "yes")
        assert r.returncode == 0 and "Nothing is scheduled." not in r.stdout, r.stdout
        assert "This does not change the schedule." in r.stdout, r.stdout


@macos_only(MACOS)
def test_a_job_that_was_scheduled_and_is_no_longer_loaded_is_a_problem():
    cfg = json.loads(json.dumps(CONFIG))
    cfg["egress"]["model_send"]["allow_prefixes"] = ["_private/notes/"]
    with instance(cfg) as (root, env):
        run(root, env, "loop/loops.py", "start", "notes")
        os.unlink(os.path.join(env["HOME"], "loaded.txt"))
        r = run(root, env, "loop/loop_watchdog.py", "--dry", "--no-auth")
        assert f"[launchd-notes] the scheduled job {label(root, 'notes')} is not loaded" in r.stdout, r.stdout
        assert "[launchd-health]" in r.stdout, r.stdout


def test_off_loop_takes_everything_back():
    cfg = json.loads(json.dumps(CONFIG))
    cfg["egress"]["model_send"]["allow_prefixes"] = ["_private/shared/", "_private/notes/", "_private/work/papers/"]
    cfg["loop"] = {"never": ["notes/"]}
    with instance(cfg) as (root, env):
        r = run(root, env, "options.py", "off", "loop")
        assert r.returncode == 0 and "no source may send" in r.stdout, r.stdout + r.stderr
        after = config(root)
        assert after["egress"]["model_send"]["allow_prefixes"] == ["_private/shared/"], after
        assert after["loop"] == {"never": ["notes/"]} and agents(env) == [], (after, agents(env))
        assert "loop" in after["options"]["declined"]


@macos_only(MACOS)
def test_off_loop_unschedules_what_was_scheduled():
    cfg = json.loads(json.dumps(CONFIG))
    cfg["egress"]["model_send"]["allow_prefixes"] = ["_private/notes/"]
    with instance(cfg) as (root, env):
        run(root, env, "loop/loops.py", "start", "notes")
        assert agents(env), "start scheduled nothing"
        r = run(root, env, "options.py", "off", "loop")
        assert r.returncode == 0 and "unscheduled: notes, health check" in r.stdout and agents(env) == [], r.stdout


def test_another_platform_refuses():
    sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "lib"),
                    os.path.join(ROOT, "tools", "loop"), os.path.join(ROOT, "tools", "loop", "lib")]
    import loop_platform
    import loops
    import options
    with mock.patch.object(sys, "platform", "linux"):
        assert not loop_platform.supported()
        for argv in (["run", "notes"], ["start", "papers"], ["stop", "notes"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = loops.main(argv)
            assert rc == 1 and out.getvalue() == loop_platform.REFUSAL + "\n", (argv, out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = options.BY_NAME["loop"]["turn_on"](["sources=all", "yes"])
        assert rc == 1 and out.getvalue() == loop_platform.REFUSAL + "\n", out.getvalue()
        assert options.BY_NAME["loop"]["label"]({}, "off") == "off; macOS only"
        try:
            loop_platform.module("sandbox")
        except RuntimeError as e:
            assert str(e) == loop_platform.REFUSAL
        else:
            raise AssertionError("a platform module was handed out where the loop does not run")


def test_a_template_names_only_files_the_installation_has():
    sys.path[:0] = [os.path.join(ROOT, "tools", "loop", "lib")]
    import loop_beat
    with instance() as (root, _env):
        values = loop_beat.common_values(root)
        assert values["ENGINE_DOCS"].startswith("no engine document"), values
        write(root, "README.md", "# kit\n")
        values = loop_beat.common_values(root)
        assert values["ENGINE_DOCS"] == "`README.md` (its first section)", values


TESTS = [
    test_a_template_names_only_files_the_installation_has,
    test_status_says_no_source_may_send_before_on_loop,
    test_nothing_runs_before_a_source_may_send,
    test_on_loop_takes_a_yes_and_allows_only_the_chosen_source,
    test_start_and_stop_schedule_a_source_with_the_health_check,
    test_on_loop_says_nothing_is_scheduled_only_when_it_read_so,
    test_a_job_that_was_scheduled_and_is_no_longer_loaded_is_a_problem,
    test_off_loop_takes_everything_back,
    test_off_loop_unschedules_what_was_scheduled,
    test_another_platform_refuses,
]


def main():
    unlisted = sorted(n for n, f in globals().items() if n.startswith("test_") and callable(f) and f not in TESTS)
    for name in unlisted:
        print(f"✗ {name}: not in TESTS")
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"loop_way_in: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
