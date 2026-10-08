#!/usr/bin/env python3
"""Run deterministic mutation probes against critical distribution tools.

The default selects four probes; --full runs all eight tools with three mutations each.
Every mutant runs in a temporary copy, leaving the source tree unchanged.
"""
from dataclasses import dataclass
import ast
import re
import os
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class Mutation:
    id: str
    tool: str
    kind: str
    old: str
    new: str
    test: str
    survivor: bool = False


MUTATIONS = (
    Mutation("memlib-compare", "tools/memlib.py", "comparison",
             "row_dt <= LEGACY_CUTOFF", "row_dt > LEGACY_CUTOFF",
             "tools/test_memlib_journal.py"),
    Mutation("memlib-return", "tools/memlib.py", "early-return",
             "def journal_visibility(track, force_private=False):\n",
             "def journal_visibility(track, force_private=False):\n    return \"private\"\n",
             "tools/test_memlib_journal.py"),
    Mutation("memlib-constant", "tools/memlib.py", "constant",
             'len(m.group("body")) > 300', 'len(m.group("body")) > 301',
             "tools/test_memlib_journal.py", True),

    Mutation("now-compare", "tools/now.py", "comparison",
             'tail.read(1) != b"\\n"', 'tail.read(1) == b"\\n"',
             "tools/test_state_runtime.py"),
    Mutation("now-return", "tools/now.py", "early-return",
             'def _assert_runtime_inputs_unchanged(scopes=("public", "private")):\n',
             'def _assert_runtime_inputs_unchanged(scopes=("public", "private")):\n    return\n',
             "tools/test_state_runtime.py"),
    Mutation("now-string", "tools/now.py", "constant",
             'M.parse_journal(visibility="private", physical_visibilities=("public",))',
             'M.parse_journal(visibility="public", physical_visibilities=("public",))',
             "tools/test_state_runtime.py"),

    Mutation("gate-compare", "tools/gate.py", "comparison",
             "declared != len(gated)", "declared == len(gated)",
             "tools/test_hook_runtime.py"),
    Mutation("gate-return", "tools/gate.py", "early-return",
             "def _issues(cmd, cwd=None, instance=None, extra_env=None):\n",
             "def _issues(cmd, cwd=None, instance=None, extra_env=None):\n    return set()\n",
             "tools/test_hook_runtime.py"),
    Mutation("gate-string", "tools/gate.py", "constant",
             'startswith("#issues ")', 'startswith("#issue ")',
             "tools/test_hook_runtime.py"),

    Mutation("linkcheck-compare", "tools/linkcheck.py", "comparison",
             "if TREE != ROOT:", "if TREE == ROOT:",
             "tools/test_install_checks.py", True),
    Mutation("linkcheck-return", "tools/linkcheck.py", "early-return",
             "def check():\n", "def check():\n    check.pending = []\n    return [], 0\n",
             "tools/test_install_checks.py"),
    Mutation("linkcheck-string", "tools/linkcheck.py", "constant",
             '"system/memory-config.json", "system/instance-rules.md",',
             '"system/memory-config.json", "system/instance-rule.md",',
             "tools/test_install_checks.py"),

    Mutation("doctor-compare", "tools/doctor.py", "comparison",
             "< (2, 5):", ">= (2, 5):", "tools/test_install_checks.py"),
    Mutation("doctor-return", "tools/doctor.py", "early-return",
             "def _allowed(url, allowlist):\n",
             "def _allowed(url, allowlist):\n    return True\n",
             "tools/test_install_checks.py", True),
    Mutation("doctor-constant", "tools/doctor.py", "constant",
             "< (2, 5):", "< (2, 6):", "tools/test_install_checks.py"),

    Mutation("fresh-worker-compare", "tools/fresh_worker.py", "comparison",
             "if rel in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep):",
             "if rel not in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep):",
             "tools/test_fresh_worker.py"),
    Mutation("fresh-worker-return", "tools/fresh_worker.py", "early-return",
             "    def link_escapes(path):\n",
             "    def link_escapes(path):\n        return False\n",
             "tools/test_fresh_worker.py"),
    Mutation("fresh-worker-constant", "tools/fresh_worker.py", "constant",
             "WRAPPER_RESULT_MISSING = 3", "WRAPPER_RESULT_MISSING = 2",
             "tools/test_fresh_worker.py"),

    Mutation("install-hooks-compare", "tools/install_hooks.sh", "comparison",
             '[[ "$STATUS" == "current" && "$PUSH_STATUS" == "current" ]]',
             '[[ "$STATUS" != "current" && "$PUSH_STATUS" == "current" ]]',
             "tools/test_install_hooks.py"),
    Mutation("install-hooks-return", "tools/install_hooks.sh", "early-return",
             "classify() {\n", 'classify() {\n  echo "current"\n  return\n',
             "tools/test_install_hooks.py"),
    Mutation("install-hooks-string", "tools/install_hooks.sh", "constant",
             'HOOK="$DIR/pre-commit"', 'HOOK="$DIR/pre-push"',
             "tools/test_install_hooks.py"),

    Mutation("setup-compare", "setup.sh", "comparison",
             '[ "$CONTEXT" != "work" ]', '[ "$CONTEXT" == "work" ]',
             "tools/test_setup_migration.py"),
    Mutation("setup-return", "setup.sh", "early-return",
             'cd "$ROOT"\n', 'cd "$ROOT"\nexit 0\n',
             "tools/test_setup_migration.py"),
    Mutation("setup-constant", "setup.sh", "constant",
             'DEFAULT_CONTEXT="work"', 'DEFAULT_CONTEXT="personal"',
             "tools/test_setup_migration.py", True),
)


def _copy_repo(destination):
    shutil.copytree(
        ROOT, destination,
        ignore=shutil.ignore_patterns(".git", "state", "_private", "__pycache__", "*.pyc"),
    )
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)


def _apply(root, mutation):
    path = os.path.join(root, mutation.tool)
    text = open(path, encoding="utf-8").read()
    count = text.count(mutation.old)
    if count != 1:
        raise AssertionError(f"{mutation.id}: mutation anchor occurs {count} times")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(mutation.old, mutation.new, 1))


def _run_test(root, test):
    env = dict(os.environ, MOTTORI_INSTANCE=root, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, test], cwd=root, env=env,
        capture_output=True, text=True, timeout=90,
    )


def anchor_issues(root, mutations):
    """Inspect every selected seam before spending time on subprocesses."""
    issues = []
    for mutation in mutations:
        try:
            text = open(os.path.join(root, mutation.tool), encoding="utf-8").read()
            count = text.count(mutation.old)
            if count != 1:
                issues.append(f"{mutation.id}: mutation anchor occurs {count} times")
        except (OSError, UnicodeError) as error:
            issues.append(f"{mutation.id}: cannot read anchor: {error}")
    return issues


def _test_outcome(root, test, result):
    """Separate a completed test failure from a crashed or incomplete measurement."""
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    summaries = re.findall(
        r"^(?:state runtime|hook runtime|install checks|install hooks|setup migration): "
        r"([0-9]+)/([0-9]+) passed$", output, re.M)
    if summaries:
        if len(summaries) != 1:
            return "ERROR", "ambiguous test summary"
        passed, total = map(int, summaries[0])
        failed_line = re.search(r"^(?:✗|FAIL) ", output, re.M)
        exceptions = re.findall(r"^✗ test_[A-Za-z0-9_]+: ([A-Za-z0-9_]+):", output, re.M)
        if any(exception != "AssertionError" for exception in exceptions):
            return "ERROR", "test runner reported a non-assertion exception"
        if total > 0 and passed == total and result.returncode == 0 and not failed_line:
            return "PASS", f"{passed}/{total} passed"
        if 0 <= passed < total and result.returncode == 1 and failed_line:
            return "FAIL", f"{total - passed}/{total} failed"
        return "ERROR", "exit status and test summary disagree"
    if result.returncode == 1 and "Traceback (most recent call last):" in output:
        if re.search(r"^AssertionError(?:[\s:]|$)", output, re.M) and os.path.basename(test) in output:
            return "FAIL", "test assertion failed"
        return "ERROR", "test process crashed without a reported assertion failure"
    if result.returncode != 0:
        return "ERROR", f"test process exited {result.returncode} without a valid failure summary"
    if test == "tools/test_memlib_journal.py":
        matches = re.findall(
            r"^PASS: journal ([0-9]+) generated cases, config ([0-9]+) cases, seed=[0-9]+$",
            output, re.M)
        if len(matches) == 1 and int(matches[0][0]) >= 200 and int(matches[0][1]) > 0:
            return "PASS", "generated journal and config cases completed"
    elif test == "tools/test_fresh_worker.py":
        tree = ast.parse(open(os.path.join(root, test), encoding="utf-8").read())
        expected = next((
            [item.id for item in node.value.elts]
            for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "TESTS" for target in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
            and all(isinstance(item, ast.Name) for item in node.value.elts)
        ), [])
        observed = re.findall(r"^PASS (test_[A-Za-z0-9_]+)$", output, re.M)
        if expected and observed == expected:
            return "PASS", f"{len(expected)} test cases completed"
    return "ERROR", "missing or incomplete success summary"


def _measure_test(root, test):
    try:
        result = _run_test(root, test)
    except subprocess.TimeoutExpired:
        return "ERROR", "test process timed out"
    except OSError as error:
        return "ERROR", f"test process could not start: {error}"
    outcome, detail = _test_outcome(root, test, result)
    if outcome == "ERROR":
        tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
        if tail:
            detail += ": " + " | ".join(tail)
    return outcome, detail


def control_suites(mutations):
    """Establish one unmodified passing control for each selected suite."""
    with tempfile.TemporaryDirectory(prefix="mutation-controls-") as parent:
        root = os.path.join(parent, "repo")
        _copy_repo(root)
        results = []
        for test in sorted({mutation.test for mutation in mutations}):
            outcome, detail = _measure_test(root, test)
            results.append((test, outcome, detail))
            print(f"CONTROL {outcome} {test}: {detail}", flush=True)
        return results


def run_mutation(mutation):
    with tempfile.TemporaryDirectory(prefix=f"mutation-{mutation.id}-") as parent:
        clone = os.path.join(parent, "repo")
        _copy_repo(clone)
        _apply(clone, mutation)
        outcome, detail = _measure_test(clone, mutation.test)
        return {"FAIL": "CAUGHT", "PASS": "SURVIVED", "ERROR": "ERROR"}[outcome], detail


def test_mutation_preflight_reports_all_invalid_anchors():
    with tempfile.TemporaryDirectory(prefix="mutation-anchor-test-") as root:
        path = os.path.join(root, "target.py")
        with open(path, "w", encoding="utf-8") as target:
            target.write("duplicate duplicate unique")
        probes = (
            Mutation("missing", "absent.py", "constant", "x", "y", "test.py"),
            Mutation("duplicate", "target.py", "constant", "duplicate", "y", "test.py"),
            Mutation("gone", "target.py", "constant", "not present", "y", "test.py"),
            Mutation("valid", "target.py", "constant", "unique", "y", "test.py"),
        )
        issues = anchor_issues(root, probes)
        assert len(issues) == 3 and all(any(issue.startswith(name + ":") for issue in issues)
                                      for name in ("missing", "duplicate", "gone")), issues


def test_mutation_classification_rejects_crashes_and_false_success():
    def outcome(rc, stdout="", stderr=""):
        return _test_outcome(ROOT, "tools/test_hook_runtime.py",
                             subprocess.CompletedProcess([], rc, stdout, stderr))[0]
    assert outcome(0, "hook runtime: 3/3 passed\n") == "PASS"
    assert outcome(1, "✗ test_x: AssertionError\nhook runtime: 2/3 passed\n") == "FAIL"
    assert outcome(1, "hook runtime: 3/3 passed\n") == "ERROR"
    assert outcome(1, "✗ test_x: KeyError: missing\nhook runtime: 2/3 passed\n") == "ERROR"
    assert outcome(0) == "ERROR"
    assert outcome(-15) == "ERROR"
    assert outcome(1, stderr="Traceback (most recent call last):\n"
                   "  File tools/test_hook_runtime.py\nSyntaxError: invalid syntax\n") == "ERROR"
    assert outcome(1, stderr="Traceback (most recent call last):\n"
                   "  File tools/test_hook_runtime.py\nAssertionError: expected rejection\n") == "FAIL"
    assert outcome(0, "hook runtime: 3/3 passed\nhook runtime: 3/3 passed\n") == "ERROR"


def main():
    full = "--full" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv[:-1] else None
    selected = MUTATIONS if full else tuple(m for m in MUTATIONS if m.survivor)
    if only is not None:
        selected = tuple(m for m in MUTATIONS if m.id == only)
        if not selected:
            print(f"unknown mutation: {only}")
            return 2
    for test in (test_mutation_preflight_reports_all_invalid_anchors,
                 test_mutation_classification_rejects_crashes_and_false_success):
        run_test(test, __file__)
    issues = anchor_issues(ROOT, selected)
    if issues:
        for issue in issues:
            print("PREFLIGHT ERROR " + issue)
        print(f"mutation: preflight failed; 0 mutants executed, {len(issues)} invalid anchors")
        return 2
    controls = control_suites(selected)
    if any(outcome != "PASS" for _test, outcome, _detail in controls):
        print("mutation: control failed; 0 mutants executed")
        return 2
    caught, errors = 0, 0
    for mutation in selected:
        outcome, detail = run_mutation(mutation)
        caught += int(outcome == "CAUGHT")
        errors += int(outcome == "ERROR")
        print(f"{outcome} {mutation.id} ({mutation.tool}, {mutation.kind}): {detail}", flush=True)
    mode = "single" if only is not None else ("full" if full else "M1-survivor smoke")
    print(f"mutation ({mode}): {caught}/{len(selected)} caught; {errors} errors")
    return 2 if errors else (0 if caught == len(selected) else 1)


if __name__ == "__main__":
    raise SystemExit(run_test(main, __file__))
