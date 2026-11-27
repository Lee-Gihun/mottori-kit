#!/usr/bin/env python3
"""What the loop's watchdog re-runs: each repair at most once a day, with backoff, started detached.

Problems whose repair is the same run share a group. Each group's attempt is reserved atomically
by a marker file named for the day, and its attempt count lives in heal-state.json; the next
attempt waits 1, 2, 4, then 7 days, and from the third attempt the group is reported as blocked. A
dispatch that dies at once counts as an attempt and keeps its reservation; a dispatch that cannot
start releases it. A group whose failure is gone loses its count. MOTTORI_WATCHDOG_HEAL=record
records plans without dispatch or markers; off disables recovery."""
import datetime
import json
import os
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import safeio  # noqa: E402
import loop_sources  # noqa: E402
from loop_stores import LOOPS  # noqa: E402
from loop_common import load_json  # noqa: E402
from loop_watch_checks import age  # noqa: E402

# Problems repaired by the same run share a group.
# An added source names its own (tools/loop/sources/README.md).
GROUPS = {"papers-cycle-failed": "papers-cycle", "papers-no-proposals": "papers-cycle",
          **{k: v for _, groups in loop_sources.each("HEAL_GROUPS") for k, v in groups.items()}}
PREFIX_GROUPS = (("papers-unjudged-", "papers-backlog"),) + tuple(
    pair for _, pairs in loop_sources.each("HEAL_PREFIXES") for pair in pairs)


def group_of(key):
    if key in GROUPS:
        return GROUPS[key]
    return next((group for prefix, group in PREFIX_GROUPS if key.startswith(prefix)), key)


def backoff_days(attempts):
    return min(2 ** max(attempts - 1, 0), 7)


def state_path(root):
    return os.path.join(root, LOOPS, "heal-state.json")


def _blocked(report, group, attempts):
    line = f"- [heal-blocked] {group}: repair attempt {attempts} for the same failure. The cause needs a look by hand"
    if report is not None:
        report["blocked"].append((group, line))
    return line


def heal(root, today, problems, command_of, mode=None, report=None, unchecked=()):
    """Reserve and dispatch repairable failures at most once per day; return report lines.

    command_of(key) is the repair command of a problem key, or None. When report is a dict, fill
    report["handled"] with the problem keys the loop is repairing (dispatched, waiting on backoff,
    or already tried today) and report["blocked"] with (group, line) for groups that reached the
    repeated-failure limit. unchecked: groups whose check did not run this time; they keep their
    attempt count."""
    if report is not None:
        report.setdefault("handled", set())
        report.setdefault("blocked", [])
    mode = mode or os.environ.get("MOTTORI_WATCHDOG_HEAL", "run")
    if mode == "off":
        return []
    d = os.path.join(root, LOOPS)
    os.makedirs(d, mode=0o700, exist_ok=True)
    hs = load_json(state_path(root))
    lines, done, groups_now, groups, handled = [], set(), set(), {}, set()
    for key, _ in problems:
        cmd = command_of(key)
        group = groups[key] = group_of(key)
        if cmd is None or group in done:
            continue
        done.add(group)
        groups_now.add(group)
        if mode == "record":
            lines.append(f"- [{key}] recorded only (MOTTORI_WATCHDOG_HEAL=record): {' '.join(cmd)}")
        elif _attempt(root, today, hs, key, group, cmd, lines, report):
            handled.add(group)
    for group in list(hs):
        if group not in groups_now and group not in unchecked:   # Reset attempts after the failure disappears.
            hs.pop(group)
    if mode != "record":
        safeio.atomic_write(state_path(root), json.dumps(hs))
    if report is not None:
        report["handled"].update(k for k, grp in groups.items() if grp in handled)
    return lines


def _attempt(root, today, hs, key, group, cmd, lines, report):
    """Try one group's repair; return whether the loop is handling it (dispatched, backing off or tried today)."""
    g = hs.get(group)
    g = g if isinstance(g, dict) else {}   # A hand-edited or foreign shape counts as no history.
    attempts, last = g.get("attempts", 0), g.get("last")
    attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else 0
    since = age(today, last) if last else None
    if attempts and since is not None and since < backoff_days(attempts):
        lines.append(f"- [{key}] backoff: {attempts} attempts, last {last}, next after {backoff_days(attempts)} days")
        if attempts >= 3:   # Keep the block visible while backoff waits; the trigger id dedups it.
            _blocked(report, group, attempts)
        return True
    d = os.path.join(root, LOOPS)
    marker = os.path.join(d, f"heal-{group}-{today}")
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        lines.append(f"- [{key}] already tried today (marker {os.path.relpath(marker, root)}), skipped")
        return True
    os.write(fd, (" ".join(cmd) + "\n").encode())
    os.close(fd)
    try:
        lines.append(_dispatch(root, d, key, group, cmd))
        hs[group] = {"attempts": attempts + 1, "last": today.isoformat()}
        if attempts + 1 >= 3:
            lines.append(_blocked(report, group, attempts + 1))
        return True
    except Exception as e:  # noqa: BLE001
        try:
            os.unlink(marker)
        except OSError:
            pass
        lines.append(f"- [{key}] the repair could not start (marker removed, it can be tried again): {e}")
        return False


def _dispatch(root, d, key, group, cmd):
    """Start the repair detached; return its report line. An instant death is a failed attempt."""
    logf = open(os.path.join(d, f"heal-{group}.log"), "a")
    logf.write(f"\n=== {datetime.datetime.now():%F %T} {' '.join(cmd)}\n")
    logf.flush()
    p = subprocess.Popen(["nohup", *cmd], cwd=root, stdin=subprocess.DEVNULL, stdout=logf,
                         stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(float(os.environ.get("MOTTORI_WATCHDOG_SPAWN_GRACE", "2")))
    early = p.poll()
    if early is not None and early != 0:
        # It keeps the marker and moves toward heal-blocked.
        return f"- [{key}] the repair died at once (rc={early}); the next attempt follows the backoff: {' '.join(cmd)}"
    return f"- [{key}] started detached, pid {p.pid}: {' '.join(cmd)} (log {LOOPS}/heal-{group}.log)"
