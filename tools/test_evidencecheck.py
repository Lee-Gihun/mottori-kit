#!/usr/bin/env python3
"""evidencecheck 공개 CLI 계약의 회귀 테스트."""

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

from testlib import run_test


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "evidencecheck.py"
RUN_ID = "evidencecheck-fixture"


def _run_line(test_id, run_id=RUN_ID, timestamp_ns=None):
    timestamp_ns = timestamp_ns if timestamp_ns is not None else time.time_ns()
    return f"RAN {run_id} {timestamp_ns} {test_id}\n"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture():
    tmp = tempfile.TemporaryDirectory(prefix="evidencecheck-")
    root = pathlib.Path(tmp.name)
    _write(root / "system" / "kit-decisions.md", """\
### DR-001 fixture (2026-09-17 · active)
결정: fixture.
맥락: measured by `paper:2609.09134`.
""")
    _write(root / "CHANGELOG.md", """\
## v0.6

### `[알아둘 것]` fixture

근거: `experiment:fixture-1`.
""")
    _write(root / "system" / "enforcement-matrix.md", """\
| 계약 | 상태 | 근거 |
|---|---|---|
| fixture | ENFORCED | `test:tools/test_sample.py::test_ok` |
""")
    _write(root / "tools" / "test_sample.py", "def test_ok():\n    pass\n")
    _write(root / "test-runs.log", _run_line("tools/test_sample.py::test_ok"))
    return tmp, root


def _run(root, *args):
    env = dict(os.environ, MOTTORI_TEST_LOG=str(root / "test-runs.log"),
               MOTTORI_TEST_RUN_ID=RUN_ID)
    return subprocess.run(
        [sys.executable, str(CHECKER), "--tree", str(root), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_defined_but_not_run_is_issue():
    tmp, root = _fixture()
    try:
        (root / "test-runs.log").write_text("", encoding="utf-8")
        issues = _run(root, "--issues")
        assert "not-run|system/enforcement-matrix.md|test:tools/test_sample.py::test_ok\t" in issues.stdout
        assert issues.stdout.splitlines()[-1] == "#issues 1", issues.stdout
        assert _run(root).returncode == 1
    finally:
        tmp.cleanup()


def test_run_log_allows_test_marker():
    tmp, root = _fixture()
    try:
        result = _run(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "실행 증거 없음" not in result.stdout
    finally:
        tmp.cleanup()


def test_missing_run_log_fails_closed():
    tmp, root = _fixture()
    try:
        (root / "test-runs.log").unlink()
        issues = _run(root, "--issues")
        assert "missing-test-log|system/enforcement-matrix.md|test:tools/test_sample.py::test_ok\t" in issues.stdout
        assert "실행 증거 없음" in issues.stdout
        assert issues.stdout.splitlines()[-1] == "#issues 1", issues.stdout
    finally:
        tmp.cleanup()


def test_stale_run_log_fails_closed():
    tmp, root = _fixture()
    try:
        stale = time.time_ns() - (25 * 60 * 60 * 1_000_000_000)
        (root / "test-runs.log").write_text(
            _run_line("tools/test_sample.py::test_ok", timestamp_ns=stale), encoding="utf-8"
        )
        issues = _run(root, "--issues")
        assert "missing-test-log|system/enforcement-matrix.md|test:tools/test_sample.py::test_ok\t" in issues.stdout
        assert issues.stdout.splitlines()[-1] == "#issues 1", issues.stdout
    finally:
        tmp.cleanup()


def test_fresh_append_does_not_validate_stale_row():
    tmp, root = _fixture()
    try:
        _write(root / "tools" / "test_sample.py", """\
def test_ok():
    pass

def test_new():
    pass
""")
        stale = time.time_ns() - (25 * 60 * 60 * 1_000_000_000)
        (root / "test-runs.log").write_text(
            _run_line("tools/test_sample.py::test_ok", run_id="previous-run", timestamp_ns=stale)
            + _run_line("tools/test_sample.py::test_new"),
            encoding="utf-8",
        )
        issues = _run(root, "--issues")
        assert "not-run|system/enforcement-matrix.md|test:tools/test_sample.py::test_ok\t" in issues.stdout
        assert issues.stdout.splitlines()[-1] == "#issues 1", issues.stdout
    finally:
        tmp.cleanup()


def test_TESTS_omission_mutation_is_caught():
    tmp, root = _fixture()
    try:
        shutil.copy2(ROOT / "tools" / "testlib.py", root / "tools" / "testlib.py")
        _write(root / "tools" / "test_sample.py", """\
from testlib import run_test

def test_ok():
    pass

def test_other():
    pass

TESTS = [test_other]

if __name__ == "__main__":
    for test in TESTS:
        run_test(test, __file__)
""")
        (root / "test-runs.log").write_text("", encoding="utf-8")
        ran = subprocess.run(
            [sys.executable, "tools/test_sample.py"], cwd=root,
            capture_output=True, text=True,
            env=dict(os.environ, MOTTORI_TEST_LOG=str(root / "test-runs.log"),
                     MOTTORI_TEST_RUN_ID=RUN_ID),
        )
        assert ran.returncode == 0, ran.stdout + ran.stderr
        recorded = (root / "test-runs.log").read_text(encoding="utf-8")
        assert re.fullmatch(
            rf"RAN {RUN_ID} [0-9]{{16,20}} tools/test_sample.py::test_other\n", recorded
        ), recorded
        issues = _run(root, "--issues")
        assert "not-run|system/enforcement-matrix.md|test:tools/test_sample.py::test_ok\t" in issues.stdout
    finally:
        tmp.cleanup()


def test_malformed_marker_fails():
    tmp, root = _fixture()
    try:
        with (root / "CHANGELOG.md").open("a", encoding="utf-8") as f:
            f.write("잘못된 표지: `paper:not-an-id`.\n")
        normal = _run(root)
        assert normal.returncode == 1, normal.stdout + normal.stderr
        issues = _run(root, "--issues")
        assert issues.returncode == 0, issues.stdout + issues.stderr
        lines = issues.stdout.splitlines()
        assert lines[-1] == "#issues 1", issues.stdout
        assert lines[0].startswith("syntax|CHANGELOG.md|paper:not-an-id\t"), issues.stdout
    finally:
        tmp.cleanup()


def test_missing_local_id_fails():
    for marker in (
        "run:missing-run",
        "decision:KIT-DR-999",
        "test:tools/test_sample.py::test_missing",
    ):
        tmp, root = _fixture()
        try:
            with (root / "CHANGELOG.md").open("a", encoding="utf-8") as f:
                f.write(f"근거: `{marker}`.\n")
            normal = _run(root)
            assert normal.returncode == 1, normal.stdout + normal.stderr
            issues = _run(root, "--issues")
            assert issues.returncode == 0, issues.stdout + issues.stderr
            assert f"missing-local|CHANGELOG.md|{marker}\t" in issues.stdout, issues.stdout
            assert issues.stdout.splitlines()[-1] == "#issues 1", issues.stdout
        finally:
            tmp.cleanup()


def test_valid_five_marker_types_pass():
    tmp, root = _fixture()
    try:
        (root / "_private" / "work" / "runs" / "run-1").mkdir(parents=True)
        _write(root / "system" / "decisions.md", "### DR-001 fixture\n")
        with (root / "CHANGELOG.md").open("a", encoding="utf-8") as f:
            f.write(
                "추가 근거: `paper:10.1000/fixture`, `run:run-1`, "
                "`decision:KIT-DR-001`, `decision:DR-001`.\n"
            )
        normal = _run(root)
        assert normal.returncode == 0, normal.stdout + normal.stderr
        issues = _run(root, "--issues")
        assert issues.returncode == 0, issues.stdout + issues.stderr
        assert "~review|system/kit-decisions.md|paper:2609.09134\tREVIEW " in issues.stdout
        assert "~review|CHANGELOG.md|experiment:fixture-1\tREVIEW " in issues.stdout
        assert "~review|CHANGELOG.md|paper:10.1000/fixture\tREVIEW " in issues.stdout
        assert issues.stdout.splitlines()[-1] == "#issues 0", issues.stdout
    finally:
        tmp.cleanup()


def test_external_markers_are_review_not_issues():
    tmp, root = _fixture()
    try:
        normal = _run(root)
        assert normal.returncode == 0, normal.stdout + normal.stderr
        assert "REVIEW 외부 존재 미판정" in normal.stdout, normal.stdout
        issues = _run(root, "--issues")
        assert issues.returncode == 0, issues.stdout + issues.stderr
        assert issues.stdout.count("~review|") == 2, issues.stdout
        assert issues.stdout.splitlines()[-1] == "#issues 0", issues.stdout
    finally:
        tmp.cleanup()


def test_required_locations_without_markers_fail():
    tmp, root = _fixture()
    try:
        _write(root / "system" / "kit-decisions.md", """\
### DR-001 fixture (2026-09-17 · active)
결정: fixture.
맥락: 근거 표지가 없다.
""")
        _write(root / "CHANGELOG.md", """\
## v0.6

### `[알아둘 것]` fixture

근거 표지가 없다.
""")
        _write(root / "system" / "enforcement-matrix.md", """\
| 계약 | 상태 | 근거 |
|---|---|---|
| fixture | ENFORCED | 근거 표지가 없다 |
""")
        issues = _run(root, "--issues")
        assert issues.returncode == 0, issues.stdout + issues.stderr
        assert "required|kit-decisions|DR-001\t" in issues.stdout, issues.stdout
        assert "required|CHANGELOG.md|[알아둘 것] fixture\t" in issues.stdout, issues.stdout
        assert "required|enforcement-matrix|fixture\t" in issues.stdout, issues.stdout
        assert issues.stdout.splitlines()[-1] == "#issues 3", issues.stdout
        assert _run(root).returncode == 1
    finally:
        tmp.cleanup()


def test_changelog_evidence_none_is_explicit_pass():
    tmp, root = _fixture()
    try:
        _write(root / "CHANGELOG.md", """\
## v0.6

### `[해야 함]` 근거가 없는 변경

evidence: none
""")
        result = _run(root)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        tmp.cleanup()


def test_legacy_dr_evidence_none_is_explicit_pass():
    tmp, root = _fixture()
    try:
        _write(root / "system" / "kit-decisions.md", """\
### DR-001 fixture (2026-09-17 · active)
결정: fixture.
맥락: 소급할 근거 포인터가 없다.
evidence: none
""")
        result = _run(root)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        tmp.cleanup()


def test_refresh_reuses_fresh_evidence_for_the_same_run():
    """The gate re-runs cited suites only when the inherited log lacks a fresh record of the same run ID
    (2026-09-18: every fixture gate run re-executed all cited suites; CI's regression step went from
    2.5 to 32 minutes and one cell hit the 40-minute limit)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import gate as G
    tmp = tempfile.TemporaryDirectory(prefix="evidence-reuse-")
    keys = ("MOTTORI_TEST_LOG", "MOTTORI_TEST_RUN_ID", "MOTTORI_TEST_EVIDENCE_ACTIVE")
    saved = {key: os.environ.get(key) for key in keys}
    try:
        tree = pathlib.Path(tmp.name) / "tree"
        sentinel = tree / "probe-ran.txt"
        _write(tree / "tools" / "test_probe.py",
               "import pathlib, sys\n"
               "pathlib.Path(sys.argv[0]).resolve().parent.parent.joinpath('probe-ran.txt').write_text('ran')\n")
        _write(tree / "CHANGELOG.md", "## v0\n\nEvidence: `test:tools/test_probe.py::test_probe`.\n")
        log = pathlib.Path(tmp.name) / "runs.log"
        log.write_text(_run_line("tools/test_probe.py::test_probe", run_id="reuse-1"), encoding="utf-8")
        os.environ.pop("MOTTORI_TEST_EVIDENCE_ACTIVE", None)
        os.environ["MOTTORI_TEST_LOG"] = str(log)
        os.environ["MOTTORI_TEST_RUN_ID"] = "reuse-1"
        path, ok = G._refresh_test_evidence(str(tree))
        assert ok and path == str(log), (path, ok)
        assert not sentinel.exists(), "a covered marker must not re-run its suite"
        os.environ["MOTTORI_TEST_RUN_ID"] = "reuse-2"
        path, ok = G._refresh_test_evidence(str(tree))
        assert ok, (path, ok)
        assert sentinel.exists(), "another run ID is not evidence: the suite must run"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tmp.cleanup()


def test_gate_consumes_evidencecheck_issues_end_to_end():
    tmp = tempfile.TemporaryDirectory(prefix="evidence-gate-")
    try:
        repo = pathlib.Path(tmp.name) / "repo"
        repo.mkdir()
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode().split("\0")
        new_engine_files = {
            "system/engine-inventory.txt",
            "system/enforcement-matrix.md",
            "system/evidence-schema.md",
            "system/test-matrix.yaml",
            "tools/evidencecheck.py",
            "tools/enforce.py",
            "tools/i18n.py",
            "tools/test_egress.py",
            "tools/test_enforce.py",
            "tools/test_evidencecheck.py",
            "tools/test_devtree_gate.py",
            "tools/test_instance_shape.py",
            "tools/test_language.py",
            "tools/test_matrix_check.py",
            "tools/testlib.py",
        }
        for rel in sorted(set(path for path in listed if path) | new_engine_files):
            source = ROOT / rel
            if not source.is_file():
                continue
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        env = dict(os.environ)
        env.pop("MOTTORI_INSTANCE", None)
        env.pop("CLAUDE_PROJECT_DIR", None)
        for command in (["git", "init", "-q"], ["git", "add", "-A"]):
            step = subprocess.run(command, cwd=repo, capture_output=True, text=True, env=env)
            assert step.returncode == 0, step.stdout + step.stderr
        if os.environ.get("MOTTORI_TEST_EVIDENCE_ACTIVE") != "1":
            env["MOTTORI_TEST_LOG"] = str(repo / ".git" / "evidence-e2e-runs.log")
            env["MOTTORI_TEST_RUN_ID"] = f"evidence-e2e-{os.getpid()}-{time.time_ns()}"
            env.pop("MOTTORI_TEST_EVIDENCE_ACTIVE", None)
        baseline = subprocess.run(
            [sys.executable, "tools/gate.py", "baseline"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )
        if baseline.returncode != 0:
            diagnostic = subprocess.run(
                [sys.executable, "tools/evidencecheck.py", "--issues"], cwd=repo,
                capture_output=True, text=True, env=env,
            )
            manifest_diagnostic = subprocess.run(
                [sys.executable, "tools/manifest_build.py", "--issues"], cwd=repo,
                capture_output=True, text=True, env=env,
            )
            raise AssertionError(
                baseline.stdout + baseline.stderr + "\n"
                + diagnostic.stdout + diagnostic.stderr + "\n"
                + manifest_diagnostic.stdout + manifest_diagnostic.stderr
            )
        assert "evidencecheck 0건" in baseline.stdout, baseline.stdout
        env["MOTTORI_TEST_EVIDENCE_ACTIVE"] = "1"
        status = subprocess.run(
            [sys.executable, "tools/gate.py", "status"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )
        assert status.returncode == 0, status.stdout + status.stderr
        assert "evidencecheck 0건" in status.stdout, status.stdout
        installed = subprocess.run(
            ["bash", "tools/install_hooks.sh", "--repair"], cwd=repo,
            capture_output=True, text=True, env=env,
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr
        hook = subprocess.run(
            [str(repo / ".git" / "hooks" / "pre-commit")],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )
        if hook.returncode != 0:
            manifest_test = subprocess.run(
                [sys.executable, "tools/test_manifests.py"], cwd=repo,
                capture_output=True, text=True, env=env,
            )
            raise AssertionError(
                hook.stdout + hook.stderr + "\n" + manifest_test.stdout + manifest_test.stderr
            )
    finally:
        tmp.cleanup()


def test_tree_without_any_target_is_not_applicable():
    tmp = tempfile.TemporaryDirectory(prefix="evidencecheck-none-")
    try:
        root = pathlib.Path(tmp.name)
        _write(root / "system" / "decisions.md", "### DR-001 instance decision\n")
        issues = _run(root, "--issues")
        assert issues.returncode == 0, issues.stdout + issues.stderr
        assert "missing-file" not in issues.stdout, issues.stdout
        assert issues.stdout.rstrip().endswith("#issues 0"), issues.stdout
        report = _run(root)
        assert "not applicable" in report.stdout, report.stdout
    finally:
        tmp.cleanup()


def test_tree_with_partial_targets_reports_missing_files():
    tmp = tempfile.TemporaryDirectory(prefix="evidencecheck-partial-")
    try:
        root = pathlib.Path(tmp.name)
        _write(root / "CHANGELOG.md", "## v0.6\n\n### `[알아둘 것]` fixture\n\n근거: `experiment:fixture-1`.\n")
        issues = _run(root, "--issues")
        assert issues.returncode == 0, issues.stdout + issues.stderr
        assert "missing-file|system/kit-decisions.md\t" in issues.stdout, issues.stdout
        assert "missing-file|system/enforcement-matrix.md\t" in issues.stdout, issues.stdout
    finally:
        tmp.cleanup()


TESTS = [
    test_defined_but_not_run_is_issue,
    test_run_log_allows_test_marker,
    test_missing_run_log_fails_closed,
    test_stale_run_log_fails_closed,
    test_fresh_append_does_not_validate_stale_row,
    test_TESTS_omission_mutation_is_caught,
    test_tree_without_any_target_is_not_applicable,
    test_tree_with_partial_targets_reports_missing_files,
    test_malformed_marker_fails,
    test_missing_local_id_fails,
    test_valid_five_marker_types_pass,
    test_external_markers_are_review_not_issues,
    test_required_locations_without_markers_fail,
    test_changelog_evidence_none_is_explicit_pass,
    test_legacy_dr_evidence_none_is_explicit_pass,
    test_refresh_reuses_fresh_evidence_for_the_same_run,
    test_gate_consumes_evidencecheck_issues_end_to_end,
]


if __name__ == "__main__":
    failed = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print("PASS", test.__name__)
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"evidencecheck: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
