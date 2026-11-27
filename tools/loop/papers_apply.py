#!/usr/bin/env python3
"""Judge, build, test and review bounded improvements from the loop's cycles, and save each
reviewed patch with its report. Nothing here writes into the working tree, stages or commits.

Usage:
  python3 tools/loop/papers_apply.py CYCLE [--source SOURCE] [--judge-only] [--force]
  python3 tools/loop/papers_apply.py --backlog [--source SOURCE] [--list]

Select at most two bundles, one observation and one behavior change, each with explicit stop conditions. At most one of them may change only the loop's own tools. A bundle names the files it changes; when it names none, the judge is asked once for them, and a bundle still without files is recorded as an idea only. Bind the judgment to input hashes and the worker-observed source identity. Archive stale input generations; a settled specification is not built again.

A bundle is refused for exactly two reasons, both decided from the paths it changes (tools/loop/loop_policy.py): a path on the never list or outside the allowed area, or a change to the module that defines those lists. A bundle that changes an always-loaded rule file is refused when the candidate's fixed context goes over the warning line of tools/context_budget.py.

Each specification has at most two implementation attempts, persisted before dispatch. Source or input changes and --force do not replenish the budget. A correction receives the prior final output, patch, test results, and independent review. Accept edit blocks only from the final response.

Build patches in an isolated clone of a snapshot of the working tree (tracked changes and untracked files Git does not ignore), the tree a saved patch is applied to. Validate paths, reject symlinks, and test in a sandbox with dedicated HOME/TMPDIR and no network. Before the first implementation of a cycle, run the unchanged tree's tests; a test file that times out or ends nonzero without a failing test ID stops the cycle there, since no candidate could be compared on it. The size check and the commit check (`tools/gate.py precommit` on the patch staged in a clone) need no test run and come before the candidate's; a commit check that fails on the unpatched base too is only a note. Compare test IDs against baseline, rerun original tests on the candidate, and provide candidate-tests-on-base diagnostics separately. Require an independent successful PASS on the same patch bytes and source/material identity. Each stage walks its order of runtimes and moves to the next one only when a runtime cannot be called. The reviewer comes from another family than the builder when one can be called, and otherwise is a fresh worker of the builder's family; REPORT.md names the builder's and the reviewer's runtime.

A start checks, as a cycle does, that its source may still send (tools/options.py on loop) and ends with exit 1 before any model call when it may not.

Write the cycle's outcome record whole, then draw the cycle's REPORT.md (tools/loop/lib/loop_report.py). A bundle ends saved, refused, abandoned or pending (tools/loop/lib/loop_outcome.py); the cycle's state is pending, done, failed or token-ceiling (tools/loop/lib/loop_state.py); measured effect remains UNKNOWN. A cycle folder whose APPLY.md has no outcome record beside it, or whose record predates these words, is closed and not processed again. The loop sets no reminder: a run that saves a change the journal has not named yet adds one private journal line, which the next session's state view shows; nothing else is journaled. Worker, test, cycle, and backlog time budgets bound execution; timed-out process groups are terminated."""
import argparse
import datetime
import fcntl
import glob
import os
import re
import stat
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_report  # noqa: E402
import loop_state  # noqa: E402
import loop_worker  # noqa: E402
from loop_bundle import prior_record, run_bundle  # noqa: E402
from loop_common import (StageError, check_deadline, clip, int_env, load_json, normal_path, open_lock,  # noqa: E402
                         rel, set_deadline)
from loop_isolate import cleanup_snapshots  # noqa: E402
from loop_judge import check_input, judgment  # noqa: E402
from loop_judging import JUDGE, input_name, source_snapshot  # noqa: E402
from loop_outcome import is_terminal  # noqa: E402
from loop_prompts import ALLOWED_PRIVATE  # noqa: E402
import loop_sending  # noqa: E402
import loop_settings  # noqa: E402
from loop_run import Ctx  # noqa: E402
from loop_config import SOURCES  # noqa: E402
import loop_sources  # noqa: E402
from loop_stores import PAPERS_BASE  # noqa: E402


def backlog_dirs(root=None, source="papers"):
    """The cycle folders of a source that still need processing, oldest first."""
    root = root or ROOT
    out = []
    if source == "papers":
        pattern, rx = os.path.join(root, PAPERS_BASE, "*-kit"), r"\d{4}-\d{2}-\d{2}-kit$"
    else:
        pattern, rx = os.path.join(root, loop_sources.get(source).BASE, "*"), loop_sources.get(source).CYCLE_NAME
    unusable = loop_sources.hook(source, "unusable")
    for d in sorted(glob.glob(pattern)):
        if not re.match(rx, os.path.basename(d)) or os.path.islink(d):
            continue
        inp = os.path.join(d, input_name(source))
        if not os.path.isfile(inp) or os.path.getsize(inp) < 200:
            continue
        if unusable and unusable(d):
            continue
        if loop_state.needs_processing(d):
            out.append(os.path.relpath(d, root).replace(os.sep, "/"))
    return out


def cycle_dir_ok(d):
    """Require the cycle under an allowed repository prefix with no symlink path components."""
    if not normal_path(d) or not d.startswith(ALLOWED_PRIVATE):
        return False
    real_root = os.path.realpath(ROOT)
    cur = real_root
    for part in d.split("/"):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            return False
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            return False
    return True


def _skip(d, cyc):
    """The line to print when a cycle needs no run (done, closed, or stopped at its token ceiling while
    it still is), else None."""
    stopped = loop_worker.ceiling_line(cyc, ROOT)
    if stopped:
        return f"skip: {d} {stopped}; raise loop.token_ceiling to continue it"
    st = loop_state.apply_status(cyc)
    if st in (loop_state.DONE, loop_state.CLOSED):
        return f"skip: {d} is {st} (--force runs it again). Report: {d}/REPORT.md"
    return None


def _locked(d, cyc, apply_dir, source, judge_only, force):
    """The cycle under its own lock: the skip check, then the run within its deadline."""
    if not judge_only and not force:
        line = _skip(d, cyc)
        if line:
            print(line)
            return 0
    set_deadline(time.monotonic() + int_env("MOTTORI_APPLY_DEADLINE", 6 * 3600))
    try:
        return _process(d, cyc, apply_dir, source, judge_only)
    finally:
        set_deadline(None)
        cleanup_snapshots()


def process(d, source, judge_only=False, force=False):
    """Run the applier over one cycle folder."""
    if not cycle_dir_ok(d):
        print(f"cycle folder refused (outside the allowed prefixes, a link, or missing): {d}", file=sys.stderr)
        return 2
    cyc = os.path.join(ROOT, d)
    apply_dir = os.path.join(cyc, "apply")
    for sub in ("prompts", "apply"):
        p = os.path.join(cyc, sub)
        if os.path.islink(p):
            print(f"a cycle subfolder is a link: {d}/{sub}", file=sys.stderr)
            return 2
        os.makedirs(p, exist_ok=True)
    fd = open_lock(os.path.join(apply_dir, ".lock"))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = os.pread(fd, 200, 0).decode("utf-8", "replace").strip()
        os.close(fd)
        print(f"running: {d} is held by another run ({holder or 'no holder recorded'})")
        return 0
    try:
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid={os.getpid()} at={datetime.datetime.now():%F %T}\n".encode(), 0)
        return _locked(d, cyc, apply_dir, source, judge_only, force)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _print_judgment(d, bundles, rejected):
    print(f"judge-only: bundles {len(bundles)} · rejected {len(rejected)} · {d}/JUDGE.md")
    for b in bundles:
        print(f"- [{b['kind']}] {b['id']}: {b['title']} -> {', '.join(b['files'])}")
    for x in rejected:
        print(f"- rejected {x['id']} {x.get('title', '')}: {x['reason']}")


def _process(d, cyc, apply_dir, source, judge_only):
    """The order of a cycle: judge (or reuse the judgment), take each unsettled bundle in the judgment's
    order through its path, then save the state, journal saved changes once, write the outcome record and
    draw REPORT.md."""
    ctx = Ctx(d, cyc, apply_dir, source, ROOT)
    ctx.state = load_json(ctx.state_path)
    bundles, rejected, summary = [], [], ""
    stage, inp_sha, failure = JUDGE, "", None
    try:
        ctx.source_identity = source_snapshot(ROOT)
        need, inp_sha = check_input(ctx)
        (bundles, rejected, summary), meta = judgment(ctx, need, inp_sha, judge_only)
        ctx.material_identity = meta.get("material_identity", {})
        if judge_only:
            ctx.save([])
            _print_judgment(d, bundles, rejected)
            return 0
        prev = ctx.state.get("bundles", {})
        for b in bundles:
            prior_record(ctx, b, prev)
        for b in bundles:
            if is_terminal(b.get("_r")):
                continue
            r = b.setdefault("_r", {})
            r["spec"] = b["_spec"]
            stage = f"bundle({b['id']})"
            check_deadline(stage)
            run_bundle(ctx, b, r)
            ctx.save(bundles)
    except StageError as e:
        if e.kind == loop_worker.CEILING:
            ctx.ceiling = True
        else:
            failure = (e.stage, clip(e.reason, 300))
    except Exception as e:  # noqa: BLE001  Surface failure instead of silently continuing.
        failure = (stage, f"{type(e).__name__}: {clip(str(e), 280)}")
    try:
        ctx.save(bundles)
    except OSError as e:
        failure = ("save-state", str(e))
    record = loop_report.outcome_record(ctx, failure, summary, bundles, rejected, inp_sha)
    if judge_only:
        print(record["state"])
        return 1
    loop_report.journal_run(ctx, record)
    loop_report.write_outcome(ctx, record)
    return 1 if record["state"] == loop_state.FAILED else 0


def _not_allowed(source):
    """Whether source may not send to a model runtime now (tools/options.py on loop), said in one line;
    checked at every start, as a cycle checks it, since the allowance may have been taken back since."""
    import config as C  # Imported here: the applier's other uses need only the loop's files.
    if source in loop_sending.allowed(C.egress_model_send()):
        return False
    print(loop_sending.REFUSAL.format(source=source))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?")
    ap.add_argument("--source", choices=SOURCES)
    ap.add_argument("--judge-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="run a finished cycle again; the implementation attempts already spent stay spent")
    ap.add_argument("--backlog", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    found = loop_settings.problems(ROOT)
    if found:
        print(loop_settings.stopped_line(found))
        return 1
    if a.backlog:
        source = a.source or "papers"
        if not a.list and _not_allowed(source):
            return 1
        dirs = backlog_dirs(source=source)
        if a.list or not dirs:
            print("\n".join(dirs) if dirs else f"backlog({source}): none")
            return 0
        rc, end = 0, time.monotonic() + int_env("MOTTORI_APPLY_BACKLOG_BUDGET", 8 * 3600)
        for i, d in enumerate(dirs):
            if time.monotonic() > end:
                print(f"backlog time budget used up: {len(dirs) - i} left for the next run ({', '.join(dirs[i:])})")
                rc |= 1
                break
            print(f"backlog: {d}")
            rc |= process(d, source)
        return rc
    if not a.dir:
        ap.error("a cycle folder is required (or --backlog)")
    d = rel(ROOT, a.dir)
    if d.startswith("..") or not os.path.isdir(os.path.join(ROOT, d)):
        print(f"no such cycle folder, or outside the repository: {a.dir}", file=sys.stderr)
        return 2
    if not d.startswith(ALLOWED_PRIVATE):
        print(f"a cycle folder must be under {ALLOWED_PRIVATE}: {d}", file=sys.stderr)
        return 2
    source = a.source or next((name for name, m in loop_sources.added().items() if d.startswith(m.BASE + "/")),
                              "papers")
    if _not_allowed(source):
        return 1
    return process(d, source, judge_only=a.judge_only, force=a.force)


if __name__ == "__main__":
    sys.exit(main())
