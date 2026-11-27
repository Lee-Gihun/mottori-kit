#!/usr/bin/env python3
"""Run deterministic mutation probes against critical distribution tools.

The default selects four probes; --full runs all of them.
Every mutant and every unmodified control runs in a temporary copy of its own, leaving the source
tree unchanged, so they run side by side.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import ast
import re
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Suites that run side by side; each one is a single Python process.
WORKERS = max(1, (os.cpu_count() or 2) - 2)
# Seconds one suite may take in a copy while others run beside it.
SUITE_TIMEOUT = 300


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
    Mutation("journal-compare", "tools/lib/journal.py", "comparison",
             "row_dt <= cutoff", "row_dt > cutoff",
             "tools/tests/test_memlib_journal.py"),
    Mutation("journal-tail-compare", "tools/lib/journal.py", "comparison",
             'tail.read(1) != b"\\n"', 'tail.read(1) == b"\\n"',
             "tools/tests/test_state_runtime.py"),
    Mutation("journal-return", "tools/lib/journal.py", "early-return",
             "def journal_visibility(track, force_private=False):\n",
             "def journal_visibility(track, force_private=False):\n    return \"private\"\n",
             "tools/tests/test_memlib_journal.py"),
    Mutation("journal-constant", "tools/lib/journal.py", "constant",
             "BODY_MAX = 300", "BODY_MAX = 301",
             "tools/tests/test_memlib_journal.py", True),

    Mutation("config-compare", "tools/lib/config.py", "comparison",
             'or ".." in re.split(', 'or ".." not in re.split(',
             "tools/tests/test_memlib_journal.py"),
    Mutation("config-return", "tools/lib/config.py", "early-return",
             "def _workers(data, warn):\n", "def _workers(data, warn):\n    return None\n",
             "tools/tests/test_memlib_journal.py"),
    Mutation("config-constant", "tools/lib/config.py", "constant",
             'TRACK_NAME = r"[a-z0-9가-힣_-]+"', 'TRACK_NAME = r"[a-z가-힣_-]+"',
             "tools/tests/test_memlib_journal.py"),

    Mutation("now-return", "tools/now.py", "early-return",
             'def _assert_config_unchanged():\n',
             'def _assert_config_unchanged():\n    return\n',
             "tools/tests/test_state_runtime.py"),
    Mutation("now-string", "tools/now.py", "constant",
             'J.parse_journal(visibility="private", physical_visibilities=("public",))',
             'J.parse_journal(visibility="public", physical_visibilities=("public",))',
             "tools/tests/test_state_runtime.py"),

    Mutation("gate-compare", "tools/gate.py", "comparison",
             "declared != len(gated)", "declared == len(gated)",
             "tools/tests/test_hook_runtime.py"),
    Mutation("gate-return", "tools/gate.py", "early-return",
             "def _issues(cmd, cwd=None, instance=None, unpin_git=False):\n",
             "def _issues(cmd, cwd=None, instance=None, unpin_git=False):\n    return Checked(set())\n",
             "tools/tests/test_hook_runtime.py"),
    Mutation("gate-string", "tools/gate.py", "constant",
             'startswith("#issues ")', 'startswith("#issue ")',
             "tools/tests/test_hook_runtime.py"),

    Mutation("linkcheck-compare", "tools/linkcheck.py", "comparison",
             "if tree != os.path.abspath(ROOT):", "if tree == os.path.abspath(ROOT):",
             "tools/tests/test_install_checks.py", True),
    Mutation("linkcheck-return", "tools/linkcheck.py", "early-return",
             "def check(tree=ROOT, filelist=None, include_all=False, session=False):\n",
             "def check(tree=ROOT, filelist=None, include_all=False, session=False):\n"
             "    return Result([], 0, [], [], set())\n",
             "tools/tests/test_install_checks.py"),
    Mutation("linkcheck-string", "tools/linkcheck.py", "constant",
             "P.config_file, P.rules, P.rituals,",
             "P.config_file, P.rituals,",
             "tools/tests/test_install_checks.py"),

    Mutation("doctor-compare", "tools/doctor.py", "comparison",
             "< (2, 5):", ">= (2, 5):", "tools/tests/test_install_checks.py"),
    Mutation("doctor-constant", "tools/doctor.py", "constant",
             "< (2, 5):", "< (2, 6):", "tools/tests/test_install_checks.py"),

    Mutation("fresh-worker-compare", "tools/lib/worker_sandbox.py", "comparison",
             "if rel == os.pardir or rel.startswith(os.pardir + os.sep):",
             # Lets a path that climbs out of the workspace through. Negating the whole test made
             # every valid path raise inside fixtures, a crash rather than an assertion failure.
             "if rel == os.pardir or rel.startswith(os.pardir + os.sep + os.sep):",
             "tools/tests/test_fresh_worker.py"),
    Mutation("fresh-worker-return", "tools/lib/worker_sandbox.py", "early-return",
             "    def link_escapes(path):\n",
             "    def link_escapes(path):\n        return False\n",
             "tools/tests/test_fresh_worker.py"),
    Mutation("fresh-worker-constant", "tools/fresh_worker.py", "constant",
             "WRAPPER_RESULT_MISSING = 3", "WRAPPER_RESULT_MISSING = 2",
             "tools/tests/test_fresh_worker.py"),

    Mutation("install-hooks-compare", "tools/install_hooks.sh", "comparison",
             'if ok "$STATUS" && ! ok "$PUSH_STATUS"; then',
             'if ! ok "$STATUS" && ! ok "$PUSH_STATUS"; then',
             "tools/tests/test_install_hooks.py"),
    Mutation("install-hooks-return", "tools/install_hooks.sh", "early-return",
             "restore() {  # restore <hook> <installed 0|1> <backup>\n",
             "restore() {  # restore <hook> <installed 0|1> <backup>\n  return 0\n",
             "tools/tests/test_install_hooks.py"),
    # The status word is checked by assertion; renaming the hook path instead made the
    # suite crash on a missing file, which the classifier rightly refuses to count as caught.
    Mutation("install-hooks-string", "tools/install_hooks.sh", "constant",
             'current|missing) printf \'%s\\t%s\\n\' "$status" "$target" ;;',
             'current|missing) printf \'%s\\t%s\\n\' "absent" "$target" ;;',
             "tools/tests/test_install_hooks.py"),

    Mutation("setup-compare", "setup.sh", "comparison",
             '[ "$FORCE" -eq 0 ]', '[ "$FORCE" -ne 0 ]',
             "tools/tests/test_setup_migration.py"),
    Mutation("setup-return", "setup.sh", "early-return",
             'cd "$ROOT"\n', 'cd "$ROOT"\nexit 0\n',
             "tools/tests/test_setup_migration.py"),
)


def _copy_repo(destination):
    # The kit's own files only: an installation's documents and data, which can be gigabytes, stay
    # out of every mutant's copy (KIT-DR-089).
    from testlib import copy_kit
    copy_kit(ROOT, destination)
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
        capture_output=True, text=True, timeout=SUITE_TIMEOUT,
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
    if test == "tools/tests/test_memlib_journal.py":
        matches = re.findall(
            r"^PASS: journal ([0-9]+) generated cases, config ([0-9]+) cases, seed=[0-9]+$",
            output, re.M)
        if len(matches) == 1 and int(matches[0][0]) >= 200 and int(matches[0][1]) > 0:
            return "PASS", "generated journal and config cases completed"
    elif test == "tools/tests/test_fresh_worker.py":
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


def _measure_copy(mutation, test):
    """Measure test in a fresh copy of the tree, with mutation applied unless it is None."""
    with tempfile.TemporaryDirectory(prefix=f"mutation-{mutation.id if mutation else 'control'}-") as parent:
        root = os.path.join(parent, "repo")
        _copy_repo(root)
        if mutation is not None:
            _apply(root, mutation)
        return _measure_test(root, test)


def measure_all(mutations):
    """Run one unmodified control per selected suite and every mutant, side by side.

    Return (controls, mutants): controls as (test, outcome, detail) in suite order, mutants as
    (mutation, CAUGHT|SURVIVED|ERROR, detail) in the given order.
    """
    tests = sorted({mutation.test for mutation in mutations})
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        control_jobs = [pool.submit(_measure_copy, None, test) for test in tests]
        mutant_jobs = [pool.submit(_measure_copy, mutation, mutation.test) for mutation in mutations]
        controls = [(test, *job.result()) for test, job in zip(tests, control_jobs)]
        mutants = [(mutation, *job.result()) for mutation, job in zip(mutations, mutant_jobs)]
    verdict = {"FAIL": "CAUGHT", "PASS": "SURVIVED", "ERROR": "ERROR"}
    return controls, [(mutation, verdict[outcome], detail) for mutation, outcome, detail in mutants]


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
        return _test_outcome(ROOT, "tools/tests/test_hook_runtime.py",
                             subprocess.CompletedProcess([], rc, stdout, stderr))[0]
    assert outcome(0, "hook runtime: 3/3 passed\n") == "PASS"
    assert outcome(1, "✗ test_x: AssertionError\nhook runtime: 2/3 passed\n") == "FAIL"
    assert outcome(1, "hook runtime: 3/3 passed\n") == "ERROR"
    assert outcome(1, "✗ test_x: KeyError: missing\nhook runtime: 2/3 passed\n") == "ERROR"
    assert outcome(0) == "ERROR"
    assert outcome(-15) == "ERROR"
    assert outcome(1, stderr="Traceback (most recent call last):\n"
                   "  File tools/tests/test_hook_runtime.py\nSyntaxError: invalid syntax\n") == "ERROR"
    assert outcome(1, stderr="Traceback (most recent call last):\n"
                   "  File tools/tests/test_hook_runtime.py\nAssertionError: expected rejection\n") == "FAIL"
    assert outcome(0, "hook runtime: 3/3 passed\nhook runtime: 3/3 passed\n") == "ERROR"


def main():
    full = "--full" in sys.argv
    # A trailing --only without an id would otherwise fall through to the default probe set.
    if sys.argv[-1] == "--only":
        print("usage: test_mutation.py [--full] [--only ID]")
        return 2
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv[:-1] else None
    selected = MUTATIONS if full else tuple(m for m in MUTATIONS if m.survivor)
    if only is not None:
        selected = tuple(m for m in MUTATIONS if m.id == only)
        if not selected:
            print(f"unknown mutation: {only}")
            return 2
    for test in (test_mutation_preflight_reports_all_invalid_anchors,
                 test_mutation_classification_rejects_crashes_and_false_success):
        test()
    issues = anchor_issues(ROOT, selected)
    if issues:
        for issue in issues:
            print("PREFLIGHT ERROR " + issue)
        print(f"mutation: preflight failed; 0 mutants executed, {len(issues)} invalid anchors")
        return 2
    controls, mutants = measure_all(selected)
    for test, outcome, detail in controls:
        print(f"CONTROL {outcome} {test}: {detail}", flush=True)
    if any(outcome != "PASS" for _test, outcome, _detail in controls):
        print("mutation: control failed; mutant results discarded")
        return 2
    caught, errors = 0, 0
    for mutation, outcome, detail in mutants:
        caught += int(outcome == "CAUGHT")
        errors += int(outcome == "ERROR")
        print(f"{outcome} {mutation.id} ({mutation.tool}, {mutation.kind}): {detail}", flush=True)
    mode = "single" if only is not None else ("full" if full else "M1-survivor smoke")
    print(f"mutation ({mode}): {caught}/{len(selected)} caught; {errors} errors")
    return 2 if errors else (0 if caught == len(selected) else 1)


if __name__ == "__main__":
    raise SystemExit(main())
