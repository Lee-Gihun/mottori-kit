#!/usr/bin/env python3
"""evidencecheck 공개 CLI 계약의 회귀 테스트."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "evidencecheck.py"


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
    return tmp, root


def _run(root, *args):
    return subprocess.run(
        [sys.executable, str(CHECKER), "--tree", str(root), *args],
        capture_output=True,
        text=True,
    )


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


def test_gate_consumes_evidencecheck_issues_end_to_end():
    tmp = tempfile.TemporaryDirectory(prefix="evidence-gate-")
    try:
        repo = pathlib.Path(tmp.name) / "repo"
        repo.mkdir()
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode().split("\0")
        new_engine_files = {
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
            "tools/test_language.py",
            "tools/test_matrix_check.py",
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
        baseline = subprocess.run(
            [sys.executable, "tools/gate.py", "baseline"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env,
        )
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        assert "evidencecheck 0건" in baseline.stdout, baseline.stdout
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
        assert hook.returncode == 0, hook.stdout + hook.stderr
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
    test_tree_without_any_target_is_not_applicable,
    test_tree_with_partial_targets_reports_missing_files,
    test_malformed_marker_fails,
    test_missing_local_id_fails,
    test_valid_five_marker_types_pass,
    test_external_markers_are_review_not_issues,
    test_required_locations_without_markers_fail,
    test_changelog_evidence_none_is_explicit_pass,
    test_legacy_dr_evidence_none_is_explicit_pass,
    test_gate_consumes_evidencecheck_issues_end_to_end,
]


if __name__ == "__main__":
    failed = []
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"evidencecheck: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
