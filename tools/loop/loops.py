#!/usr/bin/env python3
"""The improvement loop's commands: show its state, run a source now, schedule or unschedule a source.

  python3 tools/loop/loops.py status                  any problem of the settings, what may send, then each
                                                      job's schedule and each source's last cycle: its
                                                      state, counts, model use and report
  python3 tools/loop/loops.py run SOURCE             run one cycle of the source now; its last line names
                                                      the cycle's report
  python3 tools/loop/loops.py start SOURCE           schedule the source weekly, with the daily health check
  python3 tools/loop/loops.py stop SOURCE            unschedule the source; the last one takes the health check

SOURCE is papers or a source this installation added (tools/loop/sources/README.md).

A source runs or starts only when it may send (python3 tools/options.py on loop). Every command but
status runs on macOS only for now."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import config as C  # noqa: E402
import loop_config  # noqa: E402
import loop_jobs  # noqa: E402
import loop_report  # noqa: E402
import loop_platform  # noqa: E402
import loop_sending  # noqa: E402
import loop_settings  # noqa: E402
import loop_sources  # noqa: E402
import loop_worker  # noqa: E402
from loop_common import load_json  # noqa: E402
from loop_config import HEALTH, SOURCES  # noqa: E402
from loop_stores import LOOPS, PAPERS_BASE, PAPERS_HOME  # noqa: E402

# Where each job's last run is recorded, and under which key.
LAST = {**{name: (f"{m.HOME}/state.json", "last_cycle") for name, m in loop_sources.added().items()},
        "papers": (f"{PAPERS_HOME}/state.json", "last_cycle"), HEALTH: (f"{LOOPS}/watchdog-daily.json", "last")}
JOB_NAMES = {**{name: name for name in SOURCES}, HEALTH: "health check"}


def _job_state(label, scheduled, loaded):
    if not scheduled:
        return "not scheduled"
    if loaded is None:
        return "scheduled"
    return "scheduled" if label in loaded else "scheduled, not loaded: it will not run until `loops.py start` again"


def _schedule(root):
    """{job: its state word} on this platform, or None where the loop schedules nothing."""
    if not loop_platform.supported():
        return None
    jobs = loop_jobs.scheduled(root)
    try:
        loaded = loop_platform.module("schedule").loaded_labels()
    except RuntimeError:
        loaded = None
    return {n: _job_state(loop_config.job_label(n, root), yes, loaded) for n, yes in jobs.items()}


def _last_cycle(name, root):
    """The folder of the source's last cycle, relative to root, as its beat's state names it; or None."""
    last = load_json(os.path.join(root, LAST[name][0])).get("last_cycle")
    if not isinstance(last, str) or not last:
        return None
    return f"{PAPERS_BASE}/{last}-kit" if name == "papers" else f"{loop_sources.get(name).BASE}/{last}"


def _cycle_lines(name, root):
    """The source's last cycle: its state and counts with its model use, then its report."""
    d = _last_cycle(name, root)
    if not d or not os.path.isdir(os.path.join(root, d)):
        return ["  last cycle: none yet"]
    cyc = os.path.join(root, d)
    lines = [f"  last cycle {loop_report.in_words(d, root)}; {loop_worker.spent_line(cyc)}",
             f"  report: {d}/REPORT.md"]
    stopped = loop_worker.ceiling_line(cyc, root)
    return lines + ([f"  {stopped}"] if stopped else [])


def status(root=ROOT):
    """Any problem of the settings first, then what may send, then each job with its schedule and, for a
    source, its last cycle."""
    found = loop_settings.problems(root)
    for line in loop_settings.report_lines(found) if found else ():
        print(line)
    allowed = loop_sending.allowed(C.egress_model_send())
    print("sending: " + (", ".join(allowed) + " allowed" if allowed else "no source allowed (python3 tools/options.py on loop)"))
    for name, note in loop_sources.each("status_note"):
        line = note(root) if name in allowed else None
        if line:
            print(f"  {line}")
    times, by, sched = loop_config.value("schedule", root), loop_config.value("health_started_by", root), _schedule(root)
    if sched is None:
        print(f"schedule: none here ({loop_platform.SHORT})")
    for name in SOURCES + (HEALTH,):
        if name == HEALTH and by:
            state = f"started by {by}"
        else:
            state = (sched or {}).get(name, "not scheduled")
        print(f"{JOB_NAMES[name]:13} {loop_jobs.when_text(times[name]):16} {state}")
        if name in SOURCES:
            for line in _cycle_lines(name, root):
                print(line)
        else:
            print(f"  last run: {load_json(os.path.join(root, LAST[name][0])).get('last') or 'never'}")
    return 0


def _may_send(source):
    if source in loop_sending.allowed(C.egress_model_send()):
        return True
    print(loop_sending.REFUSAL.format(source=source))
    return False


def run(source, root=ROOT):
    if not _may_send(source):
        return 1
    script = loop_jobs.PROGRAMS[source][0][1]
    return subprocess.run(["bash", script, "--force"], cwd=root).returncode


def _said(results, verb):
    times = loop_config.value("schedule", ROOT)
    bad = 0
    for name, err in results:
        if err:
            bad += 1
            print(f"{JOB_NAMES[name]}: not {verb}: {err}")
        elif verb == "scheduled":
            print(f"{JOB_NAMES[name]}: scheduled, {loop_jobs.when_text(times[name])}")
        else:
            print(f"{JOB_NAMES[name]}: unscheduled")
    return 1 if bad else 0


def start(source, root=ROOT):
    if not _may_send(source):
        return 1
    rc = _said(loop_jobs.start(source, root), "scheduled")
    by = loop_config.value("health_started_by", root)
    if by:
        print(f"health check: started by {by}, so the loop schedules none")
    return rc


def stop(source, root=ROOT):
    return _said(loop_jobs.stop(source, root), "unscheduled")


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    cmd = argv[0] if argv else "status"
    if cmd == "status" and len(argv) <= 1:
        return status()
    if cmd not in ("run", "start", "stop"):
        print(__doc__, file=sys.stderr)
        return 2
    if not loop_platform.supported():
        print(loop_platform.REFUSAL)
        return 1
    if len(argv) != 2 or argv[1] not in SOURCES:
        print(f"usage: python3 tools/loop/loops.py {cmd} {'|'.join(SOURCES)}", file=sys.stderr)
        return 2
    return {"run": run, "start": start, "stop": stop}[cmd](argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
