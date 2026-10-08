#!/usr/bin/env python3
"""Regression tests for the public evidencecheck CLI."""

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
    """Re-run cited suites only when the inherited log lacks a fresh record for the same run ID."""
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
        kit_tree = (ROOT / "system/engine-inventory.txt").is_file()
        if kit_tree:
            import manifest_build
            # Cited suites require source provenance from a real HEAD.
            # Keep that history and overlay the prospective delivery inventory.
            cloned = subprocess.run(
                ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(repo)],
                capture_output=True, text=True,
            )
            assert cloned.returncode == 0, cloned.stdout + cloned.stderr
            paths = sorted(manifest_build.git_paths())
            previous = subprocess.run(
                ["git", "-C", str(repo), "ls-files", "-z"], check=True, capture_output=True,
            ).stdout
            for raw in previous.split(b"\0"):
                if raw and raw.decode("utf-8") not in paths:
                    (repo / raw.decode("utf-8")).unlink()
        else:
            # An installed instance has unrelated documents and local evidence.
            # Exercise the gate with synthetic evidence, not a copy of that workspace.
            paths = ["tools/" + name for name in (
                "gate.py", "enforce.py", "memlib.py", "i18n.py", "now.py",
                "linkcheck.py", "evidencecheck.py", "manifest_build.py",
                "testlib.py", "install_hooks.sh", "precommit-hook.sh")]
            import json
            _write(repo / ".gitignore", "_private/\nstate/\nsystem/memory-config.json\n")
            _write(repo / "README.md", "# Gate fixture\n")
            _write(repo / "system/memory-config.json", json.dumps({
                "schema_version": 4, "instance": {"name": "fixture", "context": "personal"},
                "tracks": [{"key": "system", "name": "System", "canonical": "README.md"}],
                "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                                       "legacy_public_tracks": []},
            }))
            marker = "`test:tools/test_sample.py::test_ok`"
            _write(repo / "system/kit-decisions.md",
                   "### DR-001 fixture (2026-09-17 · active)\nContext: " + marker + ".\n")
            _write(repo / "CHANGELOG.md", "## v0\n\n### [Note] fixture\nEvidence: " + marker + ".\n")
            _write(repo / "system/enforcement-matrix.md",
                   "| Contract | Status | Evidence |\n|---|---|---|\n| fixture | ENFORCED | "
                   + marker + " |\n")
            _write(repo / "tools/test_sample.py",
                   "from testlib import run_test\n"
                   "def test_ok():\n    assert 1 + 1 == 2\n"
                   "if __name__ == '__main__':\n"
                   "    run_test(test_ok, __file__)\n    print('PASS test_ok')\n")
        for rel in paths:
            source = ROOT / rel
            target = repo / rel
            if not source.is_file():
                if target.is_file():
                    target.unlink()
                continue
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
            detail = hook.stdout + hook.stderr
            if (repo / "tools/test_manifests.py").is_file():
                manifest_test = subprocess.run(
                    [sys.executable, "tools/test_manifests.py"], cwd=repo,
                    capture_output=True, text=True, env=env,
                )
                detail += "\n" + manifest_test.stdout + manifest_test.stderr
            raise AssertionError(detail)
        if not kit_tree:
            matrix = repo / "system/enforcement-matrix.md"
            matrix.write_text(matrix.read_text() + "\n`test:tools/test_sample.py::test_missing`\n")
            staged = subprocess.run(["git", "add", "system/enforcement-matrix.md"],
                                    cwd=repo, capture_output=True, text=True, env=env)
            assert staged.returncode == 0, staged.stderr
            blocked = subprocess.run([str(repo / ".git/hooks/pre-commit")], cwd=repo,
                                     capture_output=True, text=True, env=env)
            assert blocked.returncode != 0, "a missing evidence target passed the installed hook"
            assert "evidencecheck" in blocked.stderr and "test_missing" in blocked.stderr, blocked.stderr
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


def test_english_context_uses_same_evidence_boundary():
    tmp, root = _fixture()
    try:
        path = root / "system/kit-decisions.md"
        for label in ("Context:", "Reason:", "맥락:"):
            path.write_text(f"### DR-001 fixture\nDecision: rule.\n{label} evidence: none\nVerification: separate.\n")
            assert "required|kit-decisions|DR-001" not in _run(root, "--issues").stdout
            path.write_text(f"### DR-001 fixture\n{label} no evidence here.\nVerification: evidence: none\n")
            assert "required|kit-decisions|DR-001" in _run(root, "--issues").stdout
    finally:
        tmp.cleanup()


TESTS = [
    test_english_context_uses_same_evidence_boundary,
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
