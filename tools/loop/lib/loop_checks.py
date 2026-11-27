#!/usr/bin/env python3
"""Checks a candidate of the improvement loop: runs the test files in the sandbox and compares them with
the baseline by test id, measures the always-loaded context against its warning line, and runs the
commit check (tools/gate.py precommit) on the base and on the patched clone.

A root argument names the working tree; without it, the tree this file lives in."""
import glob
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import paths as P  # noqa: E402
from loop_common import (StageError, check_deadline, clip, git, normal_path, remaining, run_group,  # noqa: E402
                         write)
from loop_edits import safe_target, write_nofollow  # noqa: E402
from loop_isolate import Isolate  # noqa: E402
from loop_judging import CONTEXT_BYTES, test_target  # noqa: E402

TEST_TIMEOUT = 900
GATE_TIMEOUT = 900


_PASS_RE = re.compile(r"^\s*(?:✓|PASS\b)\s*(.*)$")
_FAIL_RE = re.compile(r"^\s*(?:✗|FAIL\b|FAILED\b)\s*(.*)$")


# The line tools/tests/testlib.py prints for a test that did not run: "- skipped NAME: needs WHAT".
_SKIP_RE = re.compile(r"^- skipped (\S+): needs (.+)$")
_TIMING_RE = re.compile(r"\s*\(\s*\d+(?:\.\d+)?\s*(?:ms|s|sec|secs|seconds)?\s*\)$")


def _test_id(rest):
    # Test files print prose names ("papers_cycle normal ..."), so the first word is not unique; the
    # name is everything before the failure detail (": reason"), minus a trailing timing.
    name = rest.strip().split(": ", 1)[0].strip().rstrip(":")
    name = _TIMING_RE.sub("", name).strip()
    return name or "(no name)"


def parse_test_output(text):
    passes, fails, seen = [], [], {}
    for line in text.splitlines():
        m = _FAIL_RE.match(line)
        target = fails
        if not m:
            m, target = _PASS_RE.match(line), passes
        if m:
            tid = _test_id(m.group(1))
            # A repeated name still counts: a later copy that disappears must show as missing.
            seen[tid] = seen.get(tid, 0) + 1
            target.append(tid if seen[tid] == 1 else f"{tid} #{seen[tid]}")
    return sorted(set(passes)), sorted(set(fails))


def skipped_tests(text):
    """[name, what it needs] of each test the output says was skipped."""
    return [[m.group(1), m.group(2).strip()] for m in map(_SKIP_RE.match, text.splitlines()) if m]


def summarize_tests(res):
    """The test files that passed, then the number of tests skipped, each reason named once."""
    ok = sum(1 for r in res.values() if r["rc"] == 0)
    skips = [s for r in res.values() for s in r.get("skips", [])]
    needs = "; ".join(dict.fromkeys(need for _, need in skips))
    return f"{ok} of {len(res)} test files passed, {len(skips)} tests skipped" + (f" (needs {needs})" if skips else "")


def failing_output(text, n):
    """At most n characters of a failed test file's output for its correction prompt: the lines that report a
    failure, then as much of the output's end as still fits, in their own lines."""
    lines = text.rstrip("\n").split("\n")
    failed = [ln for ln in lines if _FAIL_RE.match(ln)]
    head = "\n".join(failed)[: n // 2]
    room = n - len(head) - len("\n...\n")
    tail = "\n".join(lines)[-room:] if room > 0 else ""
    return (head + "\n...\n" + tail) if head else "\n".join(lines)[-n:]


def run_tests(iso, paths=None, diagnostic=False, keep_failing=False):
    """Run each test file of the clone (or the given paths) in the sandbox; its results by file name.
    diagnostic keeps every file's output, keep_failing (the candidate's run) that of a file that
    failed, as failing_output() keeps it."""
    out = {}
    for path in sorted(paths if paths is not None else glob.glob(os.path.join(iso.tree, "tools", "tests", "test_*.py"))):
        name = os.path.basename(path)
        check_deadline("verify (tests)")
        rc, text, timed = run_group(iso.command([sys.executable, path]),
                                    remaining(TEST_TIMEOUT), iso.tree, iso.env())
        passes, fails = parse_test_output(text)
        skips = skipped_tests(text)
        # A skipped test prints its pass line too; it did not pass, so it is not one.
        passes = [p for p in passes if p not in {name for name, _ in skips}]
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "(no output)")
        out[name] = {"rc": rc, "timeout": timed, "passes": passes, "fails": fails, "skips": skips,
                     "first": clip(first, 160), "tail": clip(text.strip()[-200:], 160)}
        if diagnostic:
            # Preserve the actual failure cause. A nonzero exit alone may be import/setup
            # failure rather than the behavior-specific regression required by the spec.
            out[name]["output"] = clip(text, 12000)
            out[name]["output_truncated"] = len(text) > 12000
        elif keep_failing and (rc != 0 or fails):
            out[name]["output"] = failing_output(text, 4000)
    return out


def context_over(iso, changed):
    """(refusal, loaded): loaded lists the changed files every session loads; refusal names the warning line
    the candidate's fixed context then goes over, with both numbers, or is None. Measured by the tree's
    tools/context_budget.py --json in the sandbox; its list of instruction files says what is always loaded."""
    tool_path = os.path.join(iso.tree, "tools", "context_budget.py")
    if not os.path.isfile(tool_path):
        return None, []
    rc, text, _ = run_group(iso.command([sys.executable, tool_path, "--json"]),
                            remaining(TEST_TIMEOUT), iso.tree, iso.env())
    try:
        report = json.loads([ln for ln in text.splitlines() if ln.startswith("{")][-1])
        items = [*report["items"], dict(report["total"], key="total")]
        loaded = {part["name"] for item in report["items"] if item["key"] == "instructions" for part in item["parts"]}
    except (IndexError, KeyError, TypeError, ValueError):
        return f"the fixed context could not be measured (context_budget.py rc={rc})", []
    touched = sorted(loaded & set(changed))
    over = next((item for item in items if item.get("over")), None) if touched else None
    return (f"fixed context over its warning line: {over['key']} {over['bytes']} bytes > {over['limit']}"
            if over else None), touched


# A failure line that names one of these failed before the test reached what it checks.
_IMPORT_ERROR = re.compile(r"\b(?:ImportError|ModuleNotFoundError|SyntaxError)\b")
_CHECKED_RE = re.compile(r"^\s*Checked:\s*(\S.*)$", re.M)
# The tool a cost check's number comes from; a patch that changes it cannot be measured by it.
CONTEXT_TOOL = "tools/context_budget.py"


def context_bytes(command, cwd, env):
    """The always-loaded context's total bytes as tools/context_budget.py --json prints it, run by
    command (argv to the argv that runs in the sandbox); None when it cannot be read or the run did
    not end 0 in time."""
    rc, text, timed = run_group(command([sys.executable, os.path.join(cwd, CONTEXT_TOOL), "--json"]),
                                remaining(TEST_TIMEOUT), cwd, env)
    if rc != 0 or timed:
        return None
    try:
        total = json.loads([ln for ln in text.splitlines() if ln.startswith("{")][-1])["total"]["bytes"]
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    return total if isinstance(total, int) else None


def patch_lines(patch):
    """{path: [lines added, lines removed]} of a Git patch; a binary change counts as one added line."""
    rows, path, hunk = {}, None, False
    for line in patch.decode("utf-8", "replace").splitlines():
        if line.startswith("diff --git "):
            path, hunk = line.split(" b/", 1)[-1], False
            rows.setdefault(path, [0, 0])
        elif path is None:
            continue
        elif line.startswith("@@"):
            hunk = True
        elif line.startswith("GIT binary patch") or (hunk and line.startswith("+")):
            rows[path][0] += 1
        elif hunk and line.startswith("-"):
            rows[path][1] += 1
    return rows


def checked_statement(answer):
    """The builder's one-sentence statement of what it checked: its last line 'Checked: ...'."""
    found = _CHECKED_RE.findall(answer or "")
    return clip(found[-1].strip(), 300) if found else ""


def _test_result(run, name):
    if not run:
        return "not run"
    if timed_out(run):
        return "timed out"
    if name in run["fails"]:
        lines = [ln for ln in (run.get("output") or "").splitlines() if _FAIL_RE.match(ln) and name in ln]
        return "failed by an import error" if any(_IMPORT_ERROR.search(ln) for ln in lines) else "failed"
    if name in run["passes"]:
        return "passed"
    return "failed by an import or setup error" if without_ids(run) else "not run"


def evidence(check, patch, statement, counterfactual, base, cand, cost):
    """What the loop itself found about a bundle's check, from its own runs: holds, before, after, and
    the reason when it does not hold. An unknown check holds (only an observe bundle gets this far with
    one). A cost check always needs cost, the (before, after) context bytes, whatever the patch is. For
    a test check, a patch that adds no line or changes only documents carries the builder's statement
    instead; otherwise the named test is read in the run of the candidate's tests on the unchanged code
    (or, for a test file the patch leaves alone, the baseline) and in the candidate's run."""
    e = {"check": check, "holds": True, "before": None, "after": None}
    if check["kind"] == "unknown":
        return dict(e, by="no check exists")
    lines = patch_lines(patch)
    if check["kind"] == "cost":
        before, after = cost or (None, None)
        e.update(by=CONTEXT_TOOL, before=before, after=after)
        if CONTEXT_TOOL in lines:
            return dict(e, holds=False, reason=f"the patch changes {CONTEXT_TOOL}, the tool that measures its check")
        if before is None or after is None:
            return dict(e, holds=False, reason=f"{CONTEXT_BYTES} could not be measured on the base and the candidate")
        line = check.get("pass")
        e["holds"] = after < before if line is None else after <= line
        return e if e["holds"] else dict(e, reason=f"{CONTEXT_BYTES} {before} -> {after}: " + (
            "not smaller" if line is None else f"over the pass line {line}"))
    if not any(a for a, _ in lines.values()) or all(p.endswith(".md") for p in lines):
        why = "the patch adds no line" if not any(a for a, _ in lines.values()) else "the patch changes only documents"
        e.update(by=why + "; the builder's statement", statement=statement, holds=bool(statement))
        return e if statement else dict(e, reason=f"{why}, and the builder's answer has no 'Checked:' line saying what it checked")
    path, name = test_target(check)
    fname = os.path.basename(path)
    e.update(by="test runs", before=_test_result(counterfactual.get(fname) or base.get(fname), name),
             after=_test_result(cand.get(fname), name))
    e["holds"] = e["before"] == "failed" and e["after"] == "passed"
    if e["before"] != "failed":
        e["reason"] = f"the named test {check['target']} did not fail on the unchanged code ({e['before']})"
    elif not e["holds"]:
        e["reason"] = f"the named test {check['target']} does not pass on the candidate ({e['after']})"
    return e


def evidence_line(e):
    """A person's line for a bundle's evidence; UNKNOWN where the loop has no result."""
    if not e or e["check"]["kind"] == "unknown":
        return "UNKNOWN (no check)" if e else "UNKNOWN"
    if "statement" in e:
        line = f"{e['by']}: {e['statement'] or '-'}"
    elif e["check"]["kind"] == "cost":
        line = f"{CONTEXT_BYTES} {e['before']} -> {e['after']}"
    else:
        line = f"test {e['check']['target']}: {e['before']} on the unchanged code, {e['after']} on the change"
    return line + ("" if e["holds"] else f" (does not hold: {e['reason']})")


def timed_out(res):
    return bool(res.get("timeout") or res["rc"] == 124)


def without_ids(res):
    """A file that ended nonzero without naming a failing test hides every check after the crash."""
    return res["rc"] != 0 and not res["fails"]


def incomparable(res):
    """True when a test file's run cannot be compared with another run by test id."""
    return timed_out(res) or without_ids(res)


def new_failures(base, cand):
    """Compare test IDs. Reject new failures, timeouts, unexplained nonzero exits, missing baseline IDs, and deleted test files."""
    bad = []
    for name, r in cand.items():
        b = base.get(name)
        if timed_out(r):
            bad.append(f"{name}(timeout)")
            continue
        if b is None:
            if r["rc"] != 0 or r["fails"]:
                bad.append(f"{name}(new file rc={r['rc']})")
            continue
        new = sorted(set(r["fails"]) - set(b["fails"]))
        if new:
            bad.append(f"{name}(new failures {', '.join(new[:3])})")
        missing = sorted((set(b["passes"]) | set(b["fails"])) - (set(r["passes"]) | set(r["fails"])))
        if missing:
            bad.append(f"{name}(not run {', '.join(missing[:3])})")
        if b["rc"] == 0 and r["rc"] != 0 and not new:
            bad.append(f"{name}(rc 0→{r['rc']})")
        elif b["rc"] != r["rc"] and r["rc"] != 0:
            bad.append(f"{name}(rc {b['rc']}→{r['rc']})")
        elif without_ids(r):
            # It blocks even when the base crashed the same way: otherwise a candidate could break
            # that file unseen.
            bad.append(f"{name}(crash rc={r['rc']}, no failing id)")
    for name in base:
        if name not in cand:
            bad.append(f"{name}(deleted)")
    return bad


def require_comparable_baseline(ctx, sha, root=None):
    """Stop the cycle before any bundle is built when a test file of the unchanged tree ends without
    results that can be compared by id: new_failures would refuse every candidate for it."""
    base = baseline(ctx, sha, root)
    broken = [name for name in sorted(base) if incomparable(base[name])]
    if broken:
        raise StageError("baseline", "; ".join(
            f"{name} ends rc={base[name]['rc']} without a test id on the unchanged tree: "
            f"{base[name].get('first', base[name].get('tail', ''))}" for name in broken))


def baseline(ctx, sha, root=None):
    """The unchanged tree's test results at sha, run once per run and kept in the apply folder."""
    if sha not in ctx.base_cache:
        with Isolate(sha, root) as iso:
            ctx.base_cache[sha] = run_tests(iso)
        write(os.path.join(ctx.apply_dir, f"tests-baseline-{sha[:12]}.json"),
              json.dumps(ctx.base_cache[sha], ensure_ascii=False, indent=1) + "\n")
    ctx.base_summary = f"{summarize_tests(ctx.base_cache[sha])} (starting commit {sha[:12]})"
    return ctx.base_cache[sha]


def _first_gate_line(text):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    tagged = [ln for ln in lines if ln.startswith("[gate]")]
    return clip((tagged or lines or ["(no check output)"])[0], 200)


def _prepare_gate_clone(iso, keep, root=None):
    """Make the clone's commit check run the same code as the real hook.

    The installed hook executes tools/gate.py and its helpers from the main working tree and
    compares against the untracked local baseline, while it measures only the index. Copy the
    main tree's uncommitted tools/ files and the baseline into the clone unstaged, so the
    measured index stays base + patch. Paths in ``keep`` (the patch) retain the patched bytes."""
    root = root or ROOT
    listed = git(["diff", "--name-only", "--no-renames", "-z", "HEAD", "--", "tools"], root, check=False)
    untracked = git(["ls-files", "--others", "--exclude-standard", "-z", "--", "tools"], root, check=False)
    for path in (listed.stdout + b"\0" + untracked.stdout).decode("utf-8", "replace").split("\0"):
        src = os.path.join(root, path)
        if not path or path in keep or not normal_path(path) or os.path.islink(src):
            continue
        try:
            fp, st = safe_target(iso.tree, path)
        except ValueError:
            continue
        if not os.path.lexists(src):
            if st is not None:
                os.unlink(fp)   # Deleted in the main tree, so the hook's code does not have it either.
            continue
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(src, "rb") as f:
            write_nofollow(fp, f.read())
    base_file = P.gate_baseline(root)
    if os.path.isfile(base_file) and not os.path.islink(base_file):
        os.makedirs(P.state(iso.tree), exist_ok=True)
        shutil.copyfile(base_file, P.gate_baseline(iso.tree))


def _run_gate(iso):
    """Run `tools/gate.py precommit` inside the sandboxed clone; None when the tree has no gate."""
    gate = os.path.join(iso.tree, "tools", "gate.py")
    if not os.path.isfile(gate):
        return None
    check_deadline("commit check")
    rc, text, timed = run_group(iso.command([sys.executable, gate, "precommit"]),
                                remaining(GATE_TIMEOUT), iso.tree, iso.env())
    # Each clone has its own temporary path; drop it so base and patched output can be compared.
    text = text.replace(iso.tmp, "<clone>")
    return rc, text + (f"\nTIMEOUT {GATE_TIMEOUT}s" if timed else "")


def _gate_lines(text):
    lines = {ln.strip() for ln in (text or "").splitlines() if ln.strip()}
    return {ln for ln in lines if ln.startswith("[gate]")} or lines


def gate_on_base(ctx, sha, root=None):
    """Commit check on the unpatched base, cached per base. A failure here blocks every commit."""
    cache = ctx.__dict__.setdefault("gate_base", {})
    if sha not in cache:
        with Isolate(sha, root) as iso:
            _prepare_gate_clone(iso, (), root)
            cache[sha] = _run_gate(iso)
    return cache[sha]


def gate_env_block(ctx, sha, root=None):
    """Return the first line of the base commit check failure, or None when commits can pass."""
    res = gate_on_base(ctx, sha, root)
    return _first_gate_line(res[1]) if res and res[0] != 0 else None


def gate_candidate(ctx, bid, base_sha, patch_path, changed, root=None):
    """Stage the patch in a clone and run the commit check before review.

    Returns status ok, skipped (no gate in the tree), env (the base fails too with the same lines, so
    the environment blocks commits), or patch (the patched index fails, or fails with a line the base
    does not have), with the first output line."""
    with Isolate(base_sha, root) as iso:
        git(["apply", patch_path], iso.tree)
        git(["add", "-A", "--", *changed], iso.tree)
        _prepare_gate_clone(iso, set(changed), root)
        res = _run_gate(iso)
    if res is None:
        return {"status": "skipped", "line": "tools/gate.py is missing", "summary": "commit check skipped (no gate)"}
    write(os.path.join(ctx.apply_dir, f"{bid}.gate.txt"), f"exit {res[0]}\n{res[1]}")
    if res[0] == 0:
        return {"status": "ok", "line": "", "summary": "commit check passed (clone)"}
    block = gate_env_block(ctx, base_sha, root)
    added = sorted(_gate_lines(res[1]) - _gate_lines(gate_on_base(ctx, base_sha, root)[1])) if block else []
    if block and not added:
        return {"status": "env", "line": block, "summary": f"commit check blocked by the environment: {block}"}
    # A failing base excuses only the failures it already has; a line the patch adds is the patch's.
    line = clip(added[0], 200) if added else _first_gate_line(res[1])
    return {"status": "patch", "line": line, "summary": f"commit check failed (patch): {line}"}
