#!/usr/bin/env python3
"""Runs a worker for a stage of the improvement loop and reads how each run ended, for the applier and the beats.

run_stage walks the stage's order of runtimes (tools/loop/lib/loop_runtimes.py): it starts the worker tool once
per runtime and moves on only when the run's record says its runtime could not be called. Every start
passes --read-only, so no model program the loop starts may write anywhere, and --run-file, so where the run is and how it ended come from what the worker tool wrote (the run
file, then meta.json, result.txt and result-contract.json in the run's folder). The receipt the worker
tool prints is saved for a person to read; nothing reads it.

The caller supplies how one start is launched, because the two callers bound a worker differently:
the beats keep the cycle's lock open in their workers and stop them on a signal, under the beat's
worker time; the applier runs each worker without Git's pinning variables, under what is left of its
own deadline. A root argument names the working tree; without it, the tree this file lives in.

Every run is also counted in its cycle's folder (TOKENS, read by spent()): the beats and the applier
are separate processes, so the count is a file. A run's tokens are the total its record carries; a run
whose record has none is counted as a run without a count, never as zero. Once a cycle's tokens reach
loop.token_ceiling, run_stage starts no new run and names the stage among those not started; runs
already going in parallel may finish, so the count can pass the ceiling by their size. A cycle that
stopped this way is not a failed one: ceiling_line() says so while it would stop again, and the next
stage that may start (after the owner raised the ceiling) ends the note."""
import fcntl
import json
import os
import shlex
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402
import loop_runtimes  # noqa: E402
from loop_common import (StageError, WorkerUnavailable, clean_env, clip, int_env, load_json, read,  # noqa: E402
                         remaining, run_group, sha256_file, write)

# The status of a start that left no run: the worker tool refused its input or never got that far.
NO_RUN = "no-run"
TIMEOUT = "timeout"
# The worker tool's option that starts every runtime without the right to write; a stage's output is
# the worker's answer, which the loop writes itself.
READ_ONLY = "--read-only"
# The status of a stage that did not start because its cycle reached loop.token_ceiling.
CEILING = "token-ceiling"
# The file in a cycle's folder that counts its model runs and their tokens.
TOKENS = "tokens.json"
EMPTY = {"runs": 0, "tokens": 0, "uncounted": 0, "not_started": [], "ceiling": None}


def run_file(receipt):
    """The file the worker tool names its run in, beside the receipt of the same start."""
    return os.path.splitext(receipt)[0] + ".run.json"


def outcome(receipt, rc=None, timed_out=False, root=None):
    """How the start saved at receipt ended, from the data the worker tool left (never the receipt).

    A dict: rc, timed_out, run (the run's folder or None), status (meta.json's status, TIMEOUT, or
    NO_RUN when no run started), unavailable (why the runtime could not be called, or None), result,
    contract, model, worktree, and detail (a short line for a person, from the record)."""
    root = root or ROOT
    run = load_json(os.path.join(root, run_file(receipt))).get("run_dir")
    run = run if isinstance(run, str) and run else None
    path = os.path.join(root, run) if run else None
    meta = load_json(os.path.join(path, "meta.json")) if path else {}
    status = TIMEOUT if timed_out else (str(meta.get("status") or "unknown") if path else NO_RUN)
    errors = [x for x in (meta.get("runtime_error") or meta.get("stderr_tail") or []) if isinstance(x, str)]
    return {"rc": rc, "timed_out": timed_out, "run": run, "status": status,
            "unavailable": loop_runtimes.unavailable(meta) if path else None,
            "result": read(os.path.join(path, "result.txt")) if path else "",
            "contract": load_json(os.path.join(path, "result-contract.json")) if path else {},
            "meta": meta, "model": meta.get("model"), "worktree": meta.get("worktree"),
            "detail": clip(f"status {status}, exit {rc}" + (f": {errors[0]}" if errors else ""), 200)}


def run_stage(stage, cmd, prompt, receipt, launch, root=None, built_by=None, extra=(), on_unavailable=None):
    """Run stage with the first runtime of its order that can be called; return that run's outcome.

    launch(args, receipt) starts the worker tool once and returns (rc, timed_out). The outcome also
    carries runtime, own (the builder's own family) and skipped (the runtimes before it that could not
    be called). on_unavailable(outcome) hears of each runtime that could not be called. When none
    could, the last outcome is returned with its unavailable reason set."""
    root = root or ROOT
    skipped = []
    cycle = cycle_of(os.path.join(root, receipt))
    for entry in loop_runtimes.order(stage, built_by, root):
        refused = _over_ceiling(cycle, stage, receipt, root)
        if refused:
            return {"rc": None, "timed_out": False, "run": None, "status": CEILING, "unavailable": refused,
                    "result": "", "contract": {}, "meta": {}, "model": None, "worktree": None, "detail": refused,
                    "runtime": entry["runtime"], "own": entry["own_family"], "skipped": list(skipped)}
        if os.path.lexists(os.path.join(root, run_file(receipt))):
            os.unlink(os.path.join(root, run_file(receipt)))   # An earlier start's file must not name this run.
        rc, timed_out = launch([*cmd, "--runtime", entry["runtime"], READ_ONLY, *extra,
                                "--run-file", run_file(receipt), prompt], receipt)
        o = outcome(receipt, rc, timed_out, root)
        o.update(runtime=entry["runtime"], own=entry["own_family"], skipped=list(skipped))
        if o["run"] and not o["unavailable"]:
            _count(cycle, o["meta"])
        if not o["unavailable"]:
            return o
        skipped.append(entry["runtime"])
        if on_unavailable:
            on_unavailable(o)
    return o


def cycle_of(receipt):
    """The cycle folder a receipt belongs to: its own folder, or the cycle above the applier's apply folder."""
    folder = os.path.dirname(os.path.abspath(receipt))
    return os.path.dirname(folder) if os.path.basename(folder) == "apply" else folder


def _counted(cycle, change=None):
    """The cycle's count, after change(count) when given, under a lock (card workers run in parallel)."""
    path = os.path.join(cycle, TOKENS)
    lock = os.open(cycle, os.O_RDONLY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        found = load_json(path)
        count = {k: found.get(k, v) for k, v in EMPTY.items()} if found else json.loads(json.dumps(EMPTY))
        if change:
            change(count)
            write(path, json.dumps(count) + "\n")
        return count
    finally:
        os.close(lock)


def _count(cycle, meta):
    total = (meta.get("usage") or {}).get("total") if isinstance(meta.get("usage"), dict) else None
    counted = isinstance(total, int) and not isinstance(total, bool)

    def add(count):
        count["runs"] += 1
        count["tokens" if counted else "uncounted"] += total if counted else 1
    _counted(cycle, add)


def _over_ceiling(cycle, stage, receipt, root):
    """Why a new run of stage may not start (the cycle reached loop.token_ceiling), noting it; or None,
    which also ends the note of stages an earlier run did not start."""
    ceiling = loop_config.value("token_ceiling", root)
    if not os.path.isdir(cycle):
        return None
    if ceiling is None or _counted(cycle)["tokens"] < ceiling:
        if os.path.isfile(os.path.join(cycle, TOKENS)) and _counted(cycle)["not_started"]:
            _counted(cycle, lambda count: count.update(not_started=[], ceiling=None))
        return None
    def note(count):
        count["not_started"].append(f"{stage} ({os.path.basename(receipt)})")
        count["ceiling"] = ceiling
    _counted(cycle, note)
    return f"the cycle's token ceiling is reached: {_counted(cycle)['tokens']} tokens of {ceiling}"


def spent(cycle):
    """The cycle's count: runs, tokens, uncounted (runs whose record carried no total), not_started and the
    ceiling that stopped them."""
    return _counted(cycle) if os.path.isfile(os.path.join(cycle, TOKENS)) else json.loads(json.dumps(EMPTY))


def ceiling_line(cycle, root=None):
    """One line for a cycle that stopped at loop.token_ceiling and would stop again now; None for any
    other cycle, and once the ceiling is raised above the cycle's count or taken away."""
    count, ceiling = spent(cycle), loop_config.value("token_ceiling", root)
    if not count["not_started"] or ceiling is None or count["tokens"] < ceiling:
        return None
    return (f"stopped at the token ceiling: {count['tokens']} tokens of {ceiling} (loop.token_ceiling); not started: "
            f"{', '.join(dict.fromkeys(count['not_started']))}")


def spent_line(cycle):
    """The cycle's model use in a few words, for its report and for status."""
    c = spent(cycle)
    return (f"{c['runs']} model run{'' if c['runs'] == 1 else 's'}, {c['tokens']} tokens, "
            f"{c['uncounted']} run{'' if c['uncounted'] == 1 else 's'} without a count")


def worker_cmd(root=None):
    raw = os.environ.get("MOTTORI_APPLY_WORKER_CMD")
    if raw:
        return shlex.split(raw)
    return [sys.executable, os.path.join(root or ROOT, "tools", "fresh_worker.py")]


def run_in_order(stage, built_by, prompt_rel, receipt_path, extra=(), read_materials=(), root=None):
    """The applier's run of a stage: the named read materials are hashed before the run and passed to
    the worker tool, and each start is bounded by MOTTORI_APPLY_WORKER_TIMEOUT within the run's
    deadline. The outcome also carries materials_expected; no runtime that can be called, or a cycle at its
    token ceiling, raises WorkerUnavailable."""
    root = root or ROOT
    materials_expected = {path: sha256_file(os.path.join(root, path)) for path in read_materials}
    if any(value is None for value in materials_expected.values()):
        raise StageError("materials", "a named read material is missing")
    material_args = [arg for path in materials_expected for arg in ("--read-material", path)]

    def launch(args, receipt):
        timeout = remaining(int_env("MOTTORI_APPLY_WORKER_TIMEOUT", 5400))
        rc, out, timed = run_group(args, timeout, root, clean_env())
        write(receipt, out + (f"\nTIMEOUT {timeout}s" if timed else "") + f"\nexit {rc}\n")
        return rc, timed

    w = run_stage(stage, worker_cmd(root), prompt_rel, receipt_path, launch, root, built_by,
                  (*extra, *material_args))
    if w["status"] == CEILING:
        raise WorkerUnavailable(stage, w["unavailable"], kind=CEILING)
    if w["unavailable"]:
        raise WorkerUnavailable(stage, "no runtime of the order could be called: "
                                + ", ".join(w["skipped"] + [w["runtime"]]))
    return dict(w, materials_expected=materials_expected)


def reviewer_line(r):
    """The report's words for who reviewed a bundle."""
    rv = r.get("reviewer") or {}
    if not rv:
        return "-"
    line = f"{rv['runtime']} (model {rv.get('model') or 'runtime default'})"
    return line + (", same family as the builder" if rv.get("own") else "")
