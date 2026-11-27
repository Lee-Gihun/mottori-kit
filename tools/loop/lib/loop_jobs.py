#!/usr/bin/env python3
"""The loop's scheduled jobs: each source's weekly run and the daily health check, with their labels,
programs and times, scheduled and removed through the platform's schedule module.

Starting a source schedules the health check with it, unless the configuration says that something
else starts the health check (loop.health_started_by); stopping the last source removes it. A root
argument names the instance root; without it, the tree this file lives in."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402
import loop_platform  # noqa: E402
import loop_sources  # noqa: E402
from loop_config import HEALTH, JOBS, SOURCES  # noqa: E402
from loop_stores import LOOPS, PAPERS_HOME  # noqa: E402

DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
# Each job's program, relative to the root, and the folder of its scheduler log. The health check the
# loop schedules probes no login (--no-auth), so the check itself starts no model program; a repair it
# makes runs a failed cycle again, and that cycle does.
PROGRAMS = {**{name: (list(m.PROGRAM), m.HOME) for name, m in loop_sources.added().items()},
            "papers": (["/bin/bash", "tools/loop/papers_cycle.sh"], PAPERS_HOME),
            HEALTH: (["/usr/bin/env", "python3", "tools/loop/loop_watchdog.py", "--daily", "--no-auth"], LOOPS)}


def when_text(when):
    """A job's time in words: "Sunday 21:00" or "daily 06:00"."""
    day = DAYS[when["weekday"]] if "weekday" in when else "daily"
    return f"{day} {when['hour']:02d}:{when['minute']:02d}"


def job(name, root=None):
    """The job dict the schedule module takes, for job name."""
    root = os.path.realpath(root or ROOT)
    argv, logdir = PROGRAMS[name]
    return {"label": loop_config.job_label(name, root), "root": root,
            "argv": [os.path.join(root, a) if a.startswith("tools/") else a for a in argv],
            "when": loop_config.value("schedule", root)[name], "log": os.path.join(root, logdir, "launchd.log")}


def health_is_ours(root=None):
    """Whether the loop schedules the health check itself."""
    return not loop_config.value("health_started_by", root)


def scheduled(root=None):
    """{job: whether it is scheduled} for the jobs the loop may schedule; {} where the loop does not run."""
    if not loop_platform.supported():
        return {}
    sched = loop_platform.module("schedule")
    return {name: sched.installed(loop_config.job_label(name, root))
            for name in JOBS if name != HEALTH or health_is_ours(root)}


def start(source, root=None):
    """Schedule source and, when it is the loop's own, the health check. Returns [(job, error or None)]."""
    sched = loop_platform.module("schedule")
    names = [source] + ([HEALTH] if health_is_ours(root) else [])
    return [(name, sched.install(job(name, root))) for name in names]


def stop(source, root=None):
    """Remove source's job and, once no source is scheduled, the health check. Returns [(job, error or None)]."""
    sched = loop_platform.module("schedule")
    out = [(source, sched.remove(loop_config.job_label(source, root)))]
    if not any(sched.installed(loop_config.job_label(s, root)) for s in SOURCES):
        health = loop_config.job_label(HEALTH, root)
        if sched.installed(health):
            out.append((HEALTH, sched.remove(health)))
    return out


def stop_all(root=None):
    """Remove every job the loop scheduled. Returns [(job, error or None)] for the jobs that were scheduled."""
    if not loop_platform.supported():
        return []
    sched = loop_platform.module("schedule")
    labels = [(name, loop_config.job_label(name, root)) for name in JOBS]
    return [(name, sched.remove(label)) for name, label in labels if sched.installed(label)]
