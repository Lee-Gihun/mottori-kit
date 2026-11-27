#!/usr/bin/env python3
"""What the loop's health check says: WATCHDOG.md, and to the owner each failure once when it starts and once when it is over.

Every problem goes to WATCHDOG.md. The owner hears only of problems the loop cannot repair itself
and of repairs that keep failing, and only twice per failure episode: when it is first seen (a
session trigger, a private NOW line and one notification) and when it is over (the trigger closed
and a private NOW line). A failure that returns later starts a new episode with a new trigger. The
watchdog's own failure is an episode too. Each function takes a Voice: the instance root, the day,
the notification function and the delivery timeout of this run."""
import collections
import datetime
import json
import os
import re
import subprocess
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import safeio  # noqa: E402
from loop_stores import LOOPS  # noqa: E402
from loop_common import load_json  # noqa: E402
import loop_platform  # noqa: E402

Voice = collections.namedtuple("Voice", "root today notify timeout")
DATED_KEY = re.compile(r"\d{4}-\d{2}-\d{2}")
# The episode key of the watchdog's own failure.
ERROR_KEY = "watchdog-error"


def notify(msg):
    """One notification on this machine through the platform's alert module; raises when it was not shown."""
    err = loop_platform.module("alert").notify("Improvement loop health check", msg)
    if err:
        raise RuntimeError(err)


def _loops(v):
    return os.path.join(v.root, LOOPS)


def _episodes_path(v):
    return os.path.join(_loops(v), "alert-episodes.json")


def _load_episodes(v):
    """{problem key: first day} of the failures already said; a broken file counts as none said."""
    return load_json(_episodes_path(v))


def _save_episodes(v, cur, errors=None):
    # A failed save must not stop delivery.
    try:
        safeio.atomic_write(_episodes_path(v), json.dumps(cur))
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"failure episodes not saved: {type(e).__name__}: {e}")


def trigger_id(key, first):
    """One trigger per failure episode: undated keys carry the episode's first day."""
    return f"loop-{key}" if DATED_KEY.search(key) else f"loop-{key}-{first}"


def _tool(v, name):
    return [sys.executable, os.path.join(v.root, "tools", name)]


def _deliver(v, cmd):
    """Run one delivery command; return an error text or None. A stuck store must not hang the cycle."""
    try:
        r = subprocess.run(cmd, cwd=v.root, capture_output=True, text=True, timeout=v.timeout)
    except subprocess.TimeoutExpired:
        return f"did not finish within {v.timeout} s"
    return None if r.returncode == 0 else (r.stdout + r.stderr).strip()[-120:]


def _close(v, key, first):
    """Close the episode's trigger. Best effort: the owner may have closed it already."""
    _deliver(v, _tool(v, "triggers.py") + ["fire", trigger_id(key, first), "--outcome", "over"])


def _write_report(v, problems):
    """WATCHDOG.md lists the problems; with none there is no file."""
    d = _loops(v)
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = os.path.join(d, "WATCHDOG.md")
    if not problems:
        if os.path.lexists(p):
            os.unlink(p)
        return
    lines = [f"# Loop health check {v.today}", ""] + [f"- [{k}] {m}" for k, m in problems]
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(p, 0o600)


def alert(v, problems, quiet=False, handled=(), blocked=(), unchecked=()):
    """Write every problem to WATCHDOG.md; say only what needs the owner, once per episode; return delivery errors.

    handled: keys the loop is repairing itself, which stay in WATCHDOG.md only.
    blocked: (group, line) for repairs that reached the repeated-failure limit.
    unchecked: keys whose check did not run this time, so their failure episode stays open."""
    _write_report(v, problems)
    send = [(k, m) for k, m in problems if k not in handled]
    send += [(f"heal-blocked-{g}", line.lstrip("- ")) for g, line in blocked]
    if quiet:
        return []
    errors, old, now = [], _load_episodes(v), dict(send)
    keep = set(unchecked) | {ERROR_KEY}
    cur = {k: d for k, d in old.items() if k in now or k in keep}
    new = []
    for k, m in now.items():
        if k in old:
            continue
        err = _deliver(v, _tool(v, "triggers.py") + [
            "add", "--when", f"date:{v.today}", "--tier", "T0", "--id", trigger_id(k, v.today.isoformat()),
            "--source", f"{LOOPS}/WATCHDOG.md", "--what", f"improvement loop failure: {m}"[:280]])
        if err:
            errors.append(f"trigger {k}: {err}")   # Not said, so the next run tries again.
            continue
        cur[k] = v.today.isoformat()
        new.append(k)
    over = [k for k in old if k not in now and k not in keep]
    for k in over:
        if isinstance(old[k], str):
            _close(v, k, old[k])
    _save_episodes(v, cur, errors)
    _say_changes(v, new, over, errors)
    return errors


def _say_changes(v, new, over, errors):
    parts = ([f"new failures {len(new)}: " + " · ".join(new)] if new else []) + \
            ([f"over {len(over)}: " + " · ".join(over)] if over else [])
    if parts:
        err = _deliver(v, _tool(v, "now.py") + ["log", "--private",
                                                ("[system/state] improvement loop watchdog: " + "; ".join(parts))[:290]])
        if err:
            errors.append(f"NOW: {err}")
    if new:
        try:
            v.notify(f"{len(new)} improvement loop problems need a hand. See {LOOPS}/WATCHDOG.md")
        except Exception as e:  # noqa: BLE001
            errors.append(f"notification: {e}")


def record_error(v, text):
    """Record a watchdog or sync failure in a file; say it (trigger and notification) only when its
    episode starts. Never raises."""
    try:
        d = _loops(v)
        os.makedirs(d, mode=0o700, exist_ok=True)
        with open(os.path.join(d, "WATCHDOG-ERROR.md"), "a", encoding="utf-8") as f:
            f.write(f"\n## {datetime.datetime.now():%F %T}\n{text}\n")
        os.chmod(os.path.join(d, "WATCHDOG-ERROR.md"), 0o600)
        episodes = _load_episodes(v)
        if ERROR_KEY in episodes:
            return
        _save_episodes(v, {**episodes, ERROR_KEY: v.today.isoformat()})
    except Exception:  # noqa: BLE001
        pass
    try:
        subprocess.run(_tool(v, "triggers.py") + [
            "add", "--when", f"date:{v.today}", "--tier", "T0", "--id", trigger_id(ERROR_KEY, v.today.isoformat()),
            "--source", f"{LOOPS}/WATCHDOG-ERROR.md",
            "--what", "the improvement loop watchdog itself failed: " + " ".join(text.split())[-200:]],
            cwd=v.root, capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        pass
    try:
        v.notify("the improvement loop watchdog itself failed")
    except Exception:  # noqa: BLE001
        pass


def end_error_episode(v):
    """A run that completed and delivered everything ends the watchdog's own failure episode."""
    episodes = _load_episodes(v)
    if ERROR_KEY not in episodes:
        return
    first = episodes.pop(ERROR_KEY)
    _save_episodes(v, episodes)
    _close(v, ERROR_KEY, first)
    _deliver(v, _tool(v, "now.py") + ["log", "--private", "[system/state] improvement loop watchdog: its own failure is over"])
