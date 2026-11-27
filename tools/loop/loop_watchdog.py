#!/usr/bin/env python3
"""Run the loop's health check: check the loop, repair what it can, then say what needs the owner.

The checks (tools/loop/lib/loop_watch_checks.py) read cycle age, required outputs, application status,
whether each job the loop scheduled is still loaded, the installation's own checks
(loop.health_extra_checks), the daily run's freshness, and optional Claude authentication; stale cycles still receive detailed
checks, and cycle state is read through tools/loop/lib/loop_state.py. Repairs (tools/loop/lib/loop_watch_heal.py)
run first, so the owner hears (tools/loop/lib/loop_watch_say.py) only of what the loop cannot handle itself.
Missing collection artifacts are recovered by resuming the cycle, actionable application backlog
sequentially. An abandoned change is no problem: its cycle's REPORT.md says it. Cycles closed before outcome records existed raise nothing. A lost login (claude_auth exit
1) alerts at once, since only the owner can fix it; a probe that failed for another reason is
retried as a repair. This module binds the run's instance root
and day to those three and keeps the order of a run.

--dry performs no operational writes, healing, triggers, or default auth probe. --help and invalid
arguments exit before operational work. An unexpected failure of the health check writes WATCHDOG-ERROR.md,
notifies, and exits 3; a completed run exits 0 with no problem, 1 with one. It prints the problems
first, then the repairs it started, and nothing when there is no problem."""
import argparse
import datetime
import importlib.util
import json
import os
import sys
import traceback

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_sources  # noqa: E402
import loop_watch_checks as checks  # noqa: E402
import loop_watch_heal as healing  # noqa: E402
import loop_watch_say as say  # noqa: E402
import safeio  # noqa: E402
from loop_stores import LOOPS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TODAY = datetime.date.today()
HEAL_CMDS = {}
DELIVERY_TIMEOUT = 60
_notify = say.notify


def _load_state_reader():
    """tools/loop/lib/loop_state.py of the tree at ROOT, loaded from there so a caller that points ROOT elsewhere reads that tree."""
    spec = importlib.util.spec_from_file_location("loop_state_for_watchdog",
                                                  os.path.join(ROOT, "tools", "loop", "lib", "loop_state.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The checks, repairs and sayings of this run, bound to its root, day and repair commands.
def check_papers(ls=None):
    return checks.check_papers(ROOT, TODAY, ls, HEAL_CMDS)


def check_added(ls=None):
    """The health checks of the sources this installation added (their watch hook)."""
    return [p for _, watch in loop_sources.each("watch") for p in watch(ROOT, TODAY, ls, HEAL_CMDS)]


def check_settings():
    return checks.check_settings(ROOT)


def check_daily_heartbeat():
    return checks.check_daily_heartbeat(ROOT, TODAY)


def check_auth():
    return checks.check_auth(ROOT)


def check_schedule():
    return checks.check_schedule(ROOT)


def check_extra():
    return checks.check_extra(ROOT)


def _heal_command(key):
    """Resolve the recovery command: the fixed auth probe, or one registered by the current checks."""
    return checks.auth_probe(ROOT) if key == "auth-probe" else HEAL_CMDS.get(key)


def heal(problems, mode=None, report=None, unchecked=()):
    return healing.heal(ROOT, TODAY, problems, _heal_command, mode, report, unchecked)


def _voice():
    return say.Voice(ROOT, TODAY, _notify, DELIVERY_TIMEOUT)


def alert(problems, quiet=False, handled=(), blocked=(), unchecked=()):
    return say.alert(_voice(), problems, quiet, handled, blocked, unchecked)


def record_error(text):
    say.record_error(_voice(), text)


def _end_error_episode():
    say.end_error_episode(_voice())


def parser():
    ap = argparse.ArgumentParser(description="Check the improvement loop's outputs. --dry changes no file, login, "
                                             "notification or repair.")
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--no-auth", action="store_true")
    ap.add_argument("--dry", action="store_true")
    return ap


def run(args):
    args = parser().parse_args(args) if isinstance(args, (list, tuple)) else args
    HEAL_CMDS.clear()
    try:
        ls = _load_state_reader()
        pa_err = []
    except Exception as e:  # noqa: BLE001
        ls, pa_err = None, [("apply-parser", f"loop_state.py could not be loaded, so no cycle outcome was checked: "
                                             f"{type(e).__name__}: {e}")]
    problems = pa_err + check_settings() + check_papers(ls) + check_added(ls) + check_schedule() + check_extra()
    if not args.daily:
        problems += check_daily_heartbeat()
    if not args.no_auth and not args.dry:
        problems += check_auth()
    if args.dry:
        for key, message in problems:
            print(f"[{key}] {message}")
        return 1 if problems else 0
    # Repair first, so the owner hears only about what the loop cannot handle itself.
    report = {}
    unchecked = (["auth", "auth-probe"] if args.no_auth else []) + (["watchdog-daily-missing"] if args.daily else [])
    try:
        healed = heal(problems, report=report, unchecked=unchecked)
    except Exception as e:  # noqa: BLE001  A broken repair must not silence the alerts.
        report = {}
        problems.append(("heal-error", f"the repair step raised; some repairs may have started already: "
                                       f"{type(e).__name__}: {e}"))
        healed = []
    errors = alert(problems, handled=report.get("handled", ()), blocked=report.get("blocked", ()),
                   unchecked=unchecked)
    p = os.path.join(ROOT, LOOPS, "WATCHDOG.md")
    extra = ""
    if healed:
        extra += "\n## Repairs\n" + "\n".join(healed) + "\n"
    if errors:
        extra += "\n## Alerts not delivered\n" + "\n".join(f"- {e}" for e in errors) + "\n"
    if extra:
        with open(p, "a", encoding="utf-8") as f:
            f.write(extra)
    if errors:
        record_error("alerts not delivered: " + "; ".join(errors))
    else:
        _end_error_episode()
    if args.daily:
        safeio.atomic_write(os.path.join(ROOT, LOOPS, "watchdog-daily.json"),
                            json.dumps({"last": TODAY.isoformat(), "at": datetime.datetime.now().isoformat(timespec="seconds"),
                                        "problems": len(problems)}))
    for k, m in problems:
        print(f"[{k}] {m}")
    for line in healed:
        print(line)
    return 1 if problems else 0


def main(argv=None):
    args = parser().parse_args(argv)  # Handle help and invalid arguments before any operational call.
    try:
        rc = run(args)
    except Exception:  # noqa: BLE001
        if not args.dry:
            record_error("loop_watchdog.py raised:\n" + traceback.format_exc()[-1500:])
        print(traceback.format_exc(), file=sys.stderr)
        return 3
    return rc


if __name__ == "__main__":
    sys.exit(main())
