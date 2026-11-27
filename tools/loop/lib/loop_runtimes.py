#!/usr/bin/env python3
"""Which runtimes a loop stage tries, in order, and whether a finished worker run ended because its
runtime could not be called.

A caller walks order(stage): the stage's order from the instance configuration's
loop.runtime_orders (tools/loop/lib/loop_config.py names its engine default), with the reviewer's rule
applied here. It runs the first runtime and moves on to the next only when
unavailable(run) names a reason. A worker that ran and answered badly ends the walk.

Usage:
  python3 tools/loop/lib/loop_runtimes.py order STAGE [--built-by RUNTIME]
      prints a JSON list of {"runtime": NAME, "own_family": BOOL}
  python3 tools/loop/lib/loop_runtimes.py unavailable RUN_DIR
      prints {"unavailable": REASON or null}; exits 0 when there is a reason, else 1"""
import argparse
import json
import os
import shutil
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402


def order(stage, built_by=None, root=None):
    """The runtimes to try for stage, each marked as the builder's own family or not.

    The reviewer of a built change tries the other families in the stage's order, the builder's last."""
    if stage not in loop_config.STAGES:
        raise ValueError(f"unknown stage: {stage}")
    orders = loop_config.value("runtime_orders", root)
    runtimes = list(orders.get(stage, orders["default"]))
    if stage == "review":
        if not built_by:
            raise ValueError("the review stage needs built_by")
        runtimes = [r for r in runtimes if r != built_by] + [built_by]
    return [{"runtime": r, "own_family": r == built_by} for r in runtimes]


def installed(root=None):
    """The runtimes of the configured orders whose program (the one the worker tool starts,
    config.WORKER_PROGRAMS) is on this machine's PATH, in order of first use."""
    from config import WORKER_PROGRAMS  # Imported here, as loop_config imports the runtimes' names here.
    orders = loop_config.value("runtime_orders", root)
    names = dict.fromkeys(r for stage in orders.values() for r in stage)
    return [r for r in names if shutil.which(WORKER_PROGRAMS[r])]


def unavailable(run):
    """The reason fresh_worker.py recorded that the run's runtime could not be called, or None.

    run is a run folder or its meta.json as a dict. A missing or unreadable record is None: only a
    recorded reason moves a caller on to the next runtime."""
    meta = run
    if not isinstance(run, dict):
        try:
            with open(os.path.join(run, "meta.json"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            return None
    reason = meta.get("unavailable") if isinstance(meta, dict) else None
    return reason if isinstance(reason, str) and reason else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    o = sub.add_parser("order")
    o.add_argument("stage", choices=sorted(loop_config.STAGES))
    o.add_argument("--built-by")
    u = sub.add_parser("unavailable")
    u.add_argument("run")
    args = ap.parse_args(argv)
    if args.command == "order":
        try:
            print(json.dumps(order(args.stage, args.built_by)))
        except ValueError as e:
            ap.error(str(e))
        return 0
    reason = unavailable(args.run)
    print(json.dumps({"unavailable": reason}))
    return 0 if reason else 1


if __name__ == "__main__":
    sys.exit(main())
