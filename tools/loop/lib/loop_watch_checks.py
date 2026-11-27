#!/usr/bin/env python3
"""What the loop's health check checks: each check reads the loop's files, schedules or login and returns problems.

A problem is (key, message). A check that finds a failure the loop can repair itself registers the
command that repairs it in heal_cmds under the problem's key. Cycle state is read through the
loop_state module the caller passes (ls); with none, only the beats' state files are checked. A
cycle with no outcome record is not finished; zero adoption alone is not a failure; a cycle closed
before outcome records existed raises nothing; a cycle stopped at loop.token_ceiling is one problem of
its own with no repair, since only the owner can raise the ceiling. Every function takes the instance root and the day it
judges by, so nothing here holds a root of its own."""
import datetime
import fcntl
import glob
import json
import os
import re
import subprocess
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
from loop_stores import LOOPS, PAPERS_BASE, PAPERS_HOME  # noqa: E402
import loop_config  # noqa: E402
import loop_platform  # noqa: E402
import loop_settings  # noqa: E402
import loop_sources  # noqa: E402
import loop_worker  # noqa: E402
from loop_common import load_json  # noqa: E402

MAX_AGE = 8
STATUS_COMMAND = "python3 tools/loop/loops.py status"
EXTRA_TIMEOUT = 60
LOOKBACK = 35
DAILY_MAX_AGE = 2


def age(today, d):
    """Days from the ISO date d to today, or None when d is not a date."""
    try:
        return (today - datetime.date.fromisoformat(d)).days
    except Exception:  # noqa: BLE001
        return None


def _exists(root, p, min_bytes=1):
    fp = os.path.join(root, p)
    return os.path.isfile(fp) and os.path.getsize(fp) >= min_bytes


def _lock_held(root, p):
    """Whether the cycle execution lock is currently held."""
    fp = os.path.join(root, p)
    if not os.path.exists(fp):
        return False
    try:
        fd = os.open(fp, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def apply_problem(root, ls, d):
    """Return (problem, detail) for root-relative cycle d using the supplied loop_state module."""
    st = ls.apply_status(os.path.join(root, d))
    if st in (ls.DONE, ls.CLOSED, ls.CEILING):
        return False, ""
    return True, {None: "no outcome record", ls.FAILED: "outcome failed or unreadable",
                  ls.PENDING: "a change is pending", ls.STALE: "the input changed and needs a new judgment"}[st]


def ceiling_problem(source, root, rd, date, again):
    """The one problem of the cycle at root-relative rd while it is stopped at loop.token_ceiling, or None.
    An added source's health check (its watch hook) uses it too.
    Nothing repairs it but the owner, so it has no repair command; again is the command that continues it."""
    line = loop_worker.ceiling_line(os.path.join(root, rd), root)
    return (f"{source}-token-ceiling-{date}", f"{source} cycle {date} {line}. Nothing is retried. Raise "
            f"loop.token_ceiling in the configuration, then `{again}` continues it") if line else None


def apply_cmd(source):
    """Heal unjudged cycles through one sequential, time-bounded backlog run, not concurrent workers per cycle."""
    return [sys.executable, os.path.join("tools", "loop", "papers_apply.py"), "--backlog", "--source", source]


def watched(source, root, today):
    """Whether the health check looks at source: it has run here before, or its job was scheduled more than
    MAX_AGE days ago. A source never turned on, or scheduled too recently to have run, is not reported."""
    state = os.path.join(root, PAPERS_HOME if source == "papers" else loop_sources.get(source).HOME, "state.json")
    if os.path.exists(state):
        return True
    if not loop_platform.supported():
        return False
    sched = loop_platform.module("schedule")
    label = loop_config.job_label(source, root)
    if not sched.installed(label):
        return False
    since = datetime.date.fromtimestamp(os.path.getmtime(sched.job_file(label)))
    return (today - since).days > MAX_AGE


def check_papers(root, today, ls, heal_cmds):
    if not watched("papers", root, today):
        return []
    out = []
    s = load_json(os.path.join(root, PAPERS_HOME, "state.json"))
    last, d = s.get("last_cycle"), s.get("last_dir", "")
    a = age(today, last) if last else None
    if a is None or a > MAX_AGE:
        out.append(("papers-stale", f"papers cycle last ran {last or 'never'} "
                                    f"({'unknown' if a is None else f'{a} days ago'}). See its schedule: {STATUS_COMMAND}"))
    elif a < 0:
        out.append(("papers-future", f"papers cycle state date is in the future: {last}"))
    valid_dir = bool(last) and d == f"{PAPERS_BASE}/{last}-kit" and os.path.isdir(os.path.join(root, d))
    status = s.get("status")
    # The beat counts a failed apply stage as a cycle failure too. A cycle whose only failed stage is
    # the apply and that needs no more processing (done, or closed before outcome records) is not
    # turned back into a collection repair.
    settled = ls is not None and valid_dir and not ls.needs_processing(os.path.join(root, d))
    terminal_apply_only = settled and status == "failed" and (
        s.get("failed_stages") == ["apply"] or ls.apply_status(os.path.join(root, d)) == ls.CLOSED)
    stopped = ceiling_problem("papers", root, d, last, f"bash tools/loop/papers_cycle.sh --resume {last}") if valid_dir else None
    if stopped:
        out.append(stopped)   # Not failed and not resumed: its missing outputs wait for the owner.
    elif last and a is not None and a >= 0:
        resume = ["bash", os.path.join("tools", "loop", "papers_cycle.sh"), "--resume", last]
        if (status == "failed" and not terminal_apply_only) or (status == "running" and a >= 1 and not _lock_held(root, f"{PAPERS_HOME}/cycle.lock")):
            out.append(("papers-cycle-failed", f"papers cycle {last} status {status}: {s.get('fails', '')[:160]}"))
            heal_cmds["papers-cycle-failed"] = resume
        # A running cycle is judged only by the orphan rule above; its outputs are still being written.
        elif status not in ("noop", "running") and valid_dir and a <= MAX_AGE:
            if not _exists(root, f"{d}/PROPOSALS.md", 200):
                out.append(("papers-no-proposals", f"papers cycle {last}: no PROPOSALS.md ({d})"))
                heal_cmds["papers-no-proposals"] = resume
        elif last and not valid_dir and status not in ("noop", "running"):
            out.append(("papers-bad-state", f"papers state has an unexpected last_dir: {d!r}"))
    if ls is None:
        return out
    for cdir in sorted(glob.glob(os.path.join(root, f"{PAPERS_BASE}/*-kit"))):
        name = os.path.basename(cdir)
        m = re.match(r"(\d{4}-\d{2}-\d{2})-kit$", name)
        cage = age(today, m.group(1)) if m else None
        if cage is None or cage < 0 or cage > LOOKBACK or os.path.islink(cdir):
            continue
        rd = f"{PAPERS_BASE}/{name}"
        stopped = ceiling_problem("papers", root, rd, m.group(1), f"bash tools/loop/papers_cycle.sh --resume {m.group(1)}")
        if stopped:
            out += [stopped] if stopped not in out else []
            continue
        if not _exists(root, f"{rd}/PROPOSALS.md", 200):
            continue
        bad, why = apply_problem(root, ls, rd)
        st = ls.apply_status(cdir)
        if bad and (st is not None or cage >= 1):   # Today's missing outcome may still be on its way.
            key = f"papers-unjudged-{m.group(1)}"
            out.append((key, f"papers cycle {m.group(1)}: judge and apply not finished ({why}). "
                             f"`python3 tools/loop/papers_apply.py {rd}`"))
            heal_cmds[key] = apply_cmd("papers")
    return out


def _daily_run_expected(root, today, last):
    """Whether this check is meant to run every day here: it has completed a daily run before, a
    source is in use, its own job is scheduled, or the settings name who starts it."""
    if last or loop_config.value("health_started_by", root):
        return True
    if any(watched(source, root, today) for source in loop_config.SOURCES):
        return True
    return (loop_platform.supported()
            and loop_platform.module("schedule").installed(loop_config.job_label(loop_config.HEALTH, root)))


def check_daily_heartbeat(root, today):
    """The daily run of this check, when one is expected. An installation that never turned the
    loop on has no daily run to miss."""
    s = load_json(os.path.join(root, LOOPS, "watchdog-daily.json"))
    if not _daily_run_expected(root, today, s.get("last")):
        return []
    a = age(today, s.get("last", "")) if s.get("last") else None
    if a is None or a > DAILY_MAX_AGE:
        by = loop_config.value("health_started_by", root)
        where = f"It is started by {by}" if by else f"See its schedule: {STATUS_COMMAND}"
        return [("watchdog-daily-missing", f"the daily health check last completed {s.get('last') or 'never'}. {where}")]
    return []


def check_settings(root):
    """The loop's settings, while a problem in them stops every cycle."""
    found = loop_settings.problems(root)
    return [("loop-settings", f"the loop is stopped by {len(found)} problem{'' if len(found) == 1 else 's'} in "
                              f"its settings, first: {found[0]}. See: {STATUS_COMMAND}")] if found else []


def check_schedule(root):
    """A job the loop scheduled (its job file is in place) that the scheduler no longer has loaded."""
    if not loop_platform.supported():
        return []
    sched = loop_platform.module("schedule")
    jobs = {job: loop_config.job_label(job, root) for job in loop_config.JOBS}
    jobs = {job: label for job, label in jobs.items() if sched.installed(label)}
    if not jobs:
        return []
    try:
        loaded = sched.loaded_labels()
    except RuntimeError as e:
        return [("launchd-unknown", f"the scheduler could not list its jobs: {e}")]
    return [(f"launchd-{job}", f"the scheduled job {label} is not loaded. Schedule it again: "
                               f"python3 tools/loop/loops.py start {job if job != loop_config.HEALTH else '<source>'}")
            for job, label in jobs.items() if label not in loaded]


def check_extra(root):
    """The problems the installation's own checks (loop.health_extra_checks) print as a JSON list of [key, message]."""
    out = []
    for cmd in loop_config.value("health_extra_checks", root):
        shown = " ".join(cmd)
        try:
            r = subprocess.run(list(cmd), cwd=root, capture_output=True, text=True, timeout=EXTRA_TIMEOUT)
            found = json.loads(r.stdout)
            if not isinstance(found, list) or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p)
                                                      for p in found):
                raise ValueError("not a list of [key, message]")
            out += [(k, m) for k, m in found]
        except Exception as e:  # noqa: BLE001
            out.append(("extra-check-failed", f"`{shown}` did not report its problems: {type(e).__name__}: {e}"[:300]))
    return out


def auth_probe(root):
    """The login probe of the tree at root; it is its own repair."""
    return [sys.executable, os.path.join(root, "tools", "claude_auth.py"), "check"]


def check_auth(root):
    """Report a lost login (claude_auth exit 1) as "auth" for the owner and any other failed probe as "auth-probe".

    A probe can fail for passing reasons (network, a slow CLI), so it is retried like any other repair
    and alerts only when the retries keep failing."""
    try:
        r = subprocess.run(auth_probe(root), capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            return []
        detail = (r.stdout + r.stderr).strip()[-200:]
    except Exception as e:  # noqa: BLE001
        r, detail = None, str(e)
    if r is not None and r.returncode == 1:
        return [("auth", "headless claude is not logged in: " + detail)]
    return [("auth-probe", "the headless claude check failed (not a login problem): " + detail)]
