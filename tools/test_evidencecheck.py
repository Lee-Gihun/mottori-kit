#!/usr/bin/env python3
"""Regression tests for the public evidencecheck CLI."""

import contextlib
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


@contextlib.contextmanager
def _refresh_fixture():
    from unittest import mock
    import gate as G

    tmp, tree = _fixture()
    try:
        shutil.copy2(ROOT / "tools/testlib.py", tree / "tools/testlib.py")
        marker = "`test:tools/test_probe.py::test_probe`"
        _write(tree / "system/kit-decisions.md", "### DR-001 fixture\nEvidence: " + marker + ".\n")
        _write(tree / "CHANGELOG.md", "## v0\n\n### [Note] fixture\nEvidence: " + marker + ".\n")
        _write(tree / "system/enforcement-matrix.md",
               "| Contract | Status | Evidence |\n|---|---|---|\n| fixture | ENFORCED | " + marker + " |\n")
        log = tree / "runs.log"
        log.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {
                "MOTTORI_TEST_LOG": str(log), "MOTTORI_TEST_RUN_ID": "caller-run"}):
            os.environ.pop("MOTTORI_TEST_EVIDENCE_ACTIVE", None)
            yield G, tree, log
    finally:
        tmp.cleanup()


def _probe(body):
    return ("import os, pathlib\nfrom testlib import run_test\n"
            "def test_probe():\n"
            "    with pathlib.Path('attempts.txt').open('a') as out:\n"
            "        out.write(os.environ['MOTTORI_TEST_RUN_ID'] + '\\n')\n"
            + body + "\nrun_test(test_probe, __file__)\n")


def test_refresh_reruns_inherited_evidence_with_new_ids():
    """Inherited invocation records cannot replace a completed current suite."""
    with _refresh_fixture() as (G, tree, log):
        historical = _run_line("tools/test_probe.py::test_probe", run_id="caller-run")
        log.write_text(historical, encoding="utf-8")
        _write(tree / "tools/test_probe.py", _probe("    assert True"))
        for caller in ("caller-run", "caller-run", "another-caller"):
            os.environ["MOTTORI_TEST_RUN_ID"] = caller
            path, ok = G._refresh_test_evidence(str(tree))
            assert ok and path == str(log), (path, ok)
        attempts = (tree / "attempts.txt").read_text().splitlines()
        assert len(attempts) == len(set(attempts)) == 3, attempts
        assert all(run.startswith("gate-") for run in attempts), attempts
        assert log.read_text().startswith(historical), "preserve inherited execution history"
        # A nested evidence fixture uses its outer attempt, without starting another suite.
        os.environ["MOTTORI_TEST_EVIDENCE_ACTIVE"] = "1"
        run_id = os.environ["MOTTORI_TEST_RUN_ID"]
        assert G._refresh_test_evidence(str(tree)) == (str(log), True)
        assert os.environ["MOTTORI_TEST_RUN_ID"] == run_id
        assert (tree / "attempts.txt").read_text().splitlines() == attempts
        from unittest import mock
        os.environ.pop("MOTTORI_TEST_EVIDENCE_ACTIVE")
        os.environ.pop("MOTTORI_TEST_LOG")
        with mock.patch.object(G, "_ephem", return_value=str(log)):
            assert G._refresh_test_evidence(str(tree)) == (str(log), True)
        assert len(log.read_text().splitlines()) == 5, "default logs must preserve history too"


def test_refresh_retries_after_later_test_failure():
    with _refresh_fixture() as (G, tree, log):
        source = _probe("    assert True") + (
            "def test_later():\n    raise AssertionError('later failure')\n"
            "run_test(test_later, __file__)\n")
        _write(tree / "tools/test_probe.py", source)
        for _ in range(2):
            os.environ["MOTTORI_TEST_RUN_ID"] = "caller-run"
            assert G._refresh_test_evidence(str(tree)) == (str(log), False)
        attempts = (tree / "attempts.txt").read_text().splitlines()
        assert len(attempts) == len(set(attempts)) == 2, attempts
        assert len(log.read_text().splitlines()) == 4, "retain both failed suite histories"


def test_refresh_rechecks_imports_and_rejects_old_test_coverage():
    import evidencecheck as EC

    with _refresh_fixture() as (G, tree, log):
        _write(tree / "tools/fixture_dependency.py", "READY = True\n")
        _write(tree / "tools/test_probe.py", _probe(
            "    from fixture_dependency import READY\n    assert READY"))
        assert G._refresh_test_evidence(str(tree)) == (str(log), True)
        first_id = os.environ["MOTTORI_TEST_RUN_ID"]
        _write(tree / "tools/fixture_dependency.py", "READY = False\n")
        os.environ["MOTTORI_TEST_RUN_ID"] = first_id
        assert G._refresh_test_evidence(str(tree)) == (str(log), False)
        # The cited function still exists but no longer runs in this source version.
        _write(tree / "tools/test_probe.py", "from testlib import run_test\n"
               "def test_probe():\n    pass\n"
               "def test_other():\n    pass\nrun_test(test_other, __file__)\n")
        os.environ["MOTTORI_TEST_RUN_ID"] = first_id
        assert G._refresh_test_evidence(str(tree)) == (str(log), True)
        issues, _reviews, _markers = EC.check(str(tree), str(tree), str(log))
        assert any("not-run|" in issue[0] and "::test_probe" in issue[0] for issue in issues), issues
        assert os.environ["MOTTORI_TEST_RUN_ID"] != first_id


def test_refresh_timeout_late_records_cannot_cover_retry():
    from unittest import mock
    import evidencecheck as EC

    with _refresh_fixture() as (G, tree, log):
        _write(tree / "tools/late_record.py", "import pathlib, time\n"
               "from testlib import run_test\n"
               "deadline = time.monotonic() + 5\n"
               "while not pathlib.Path('release-late').exists() and time.monotonic() < deadline:\n"
               "    time.sleep(0.02)\n"
               "if not pathlib.Path('release-late').exists():\n    raise SystemExit(1)\n"
               "def test_probe():\n    pass\n"
               "run_test(test_probe, pathlib.Path(__file__).with_name('test_probe.py'))\n"
               "pathlib.Path('late.done').write_text('finished')\n")
        _write(tree / "tools/test_probe.py", _probe(
            "    import subprocess, sys, time\n"
            "    subprocess.Popen([sys.executable, 'tools/late_record.py'],\n"
            "                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "    time.sleep(10)"))
        launch = subprocess.run

        def short_timeout(command, **kwargs):
            if command == [sys.executable, "tools/test_probe.py"]:
                kwargs["timeout"] = 1
            return launch(command, **kwargs)

        with mock.patch.object(G.subprocess, "run", side_effect=short_timeout):
            assert G._refresh_test_evidence(str(tree)) == (str(log), False)
        (tree / "release-late").touch()
        deadline = time.monotonic() + 5
        while not (tree / "late.done").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tree / "late.done").exists(), "timed-out descendant did not finish its late record"
        historical = log.read_text()
        assert len(historical.splitlines()) == 2, historical
        _write(tree / "tools/test_probe.py", "from testlib import run_test\n"
               "def test_probe():\n    pass\n"
               "def test_other():\n    pass\nrun_test(test_other, __file__)\n")
        os.environ["MOTTORI_TEST_RUN_ID"] = "caller-run"
        assert G._refresh_test_evidence(str(tree)) == (str(log), True)
        assert log.read_text().startswith(historical), "late execution history must not be erased"
        issues, _reviews, _markers = EC.check(str(tree), str(tree), str(log))
        assert any("not-run|" in issue[0] and "::test_probe" in issue[0] for issue in issues), issues


def test_refresh_reports_timeout_and_launch_error_without_evidence():
    sys.path.insert(0, str(ROOT / "tools"))
    import gate as G
    import contextlib
    import io
    from unittest import mock

    with tempfile.TemporaryDirectory(prefix="evidence-errors-") as temporary:
        tree = pathlib.Path(temporary)
        rel = "tools/test_probe.py"
        _write(tree / rel, "def test_probe():\n    pass\n")
        _write(tree / "CHANGELOG.md", "Evidence: `test:tools/test_probe.py::test_probe`.\n")
        log = tree / "runs.log"
        cases = (
            (subprocess.TimeoutExpired([sys.executable, rel], 120,
                                       output=b"partial output\n", stderr=b"nested detail\n"),
             ("timed out", rel, "120s", "partial output", "nested detail")),
            (OSError("synthetic launch failure"), ("could not run", rel, "OSError", "synthetic launch failure")),
        )
        for error, expected in cases:
            log.write_text("", encoding="utf-8")
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, {
                "MOTTORI_TEST_LOG": str(log), "MOTTORI_TEST_RUN_ID": "unavailable-fixture",
            }):
                os.environ.pop("MOTTORI_TEST_EVIDENCE_ACTIVE", None)
                with mock.patch.object(G, "_ensure_git_tree", return_value=True), \
                        mock.patch.object(G.subprocess, "run", side_effect=error) as launch, \
                        contextlib.redirect_stderr(stderr):
                    path, ok = G._refresh_test_evidence(str(tree))
            assert path == str(log) and ok is False, (path, ok)
            assert log.read_text(encoding="utf-8") == "", "this pre-execution fixture must leave its empty log unchanged"
            assert launch.call_args.kwargs["timeout"] == 120
            assert all(part in stderr.getvalue() for part in expected), stderr.getvalue()


def test_checker_failure_diagnostics_keep_unavailable_verdict():
    sys.path.insert(0, str(ROOT / "tools"))
    import gate as G
    import contextlib
    import io
    from unittest import mock

    command = [sys.executable, "tools/evidencecheck.py", "--issues"]
    cases = (
        (subprocess.TimeoutExpired(command, 120, output=b"partial output", stderr=b"nested detail"),
         ("checker timed out", "evidencecheck.py", "120s", "nested detail")),
        (OSError("synthetic launch failure"), ("checker could not run", "OSError")),
        (subprocess.CompletedProcess(command, 2, "", "synthetic checker failure"),
         ("checker exited nonzero", "exit=2", "synthetic checker failure")),
        (subprocess.CompletedProcess(command, 0, "not a trailer\n", ""),
         ("checker missing final issue trailer", "not a trailer")),
        (subprocess.CompletedProcess(command, 0, "#issues invalid\n", ""),
         ("checker malformed issue trailer",)),
        (subprocess.CompletedProcess(command, 0, "issue\tmessage\n#issues 0\n", ""),
         ("checker issue count mismatch", "declared=0 actual=1")),
    )
    for outcome, expected in cases:
        stderr = io.StringIO()
        options = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with mock.patch.object(G.subprocess, "run", **options) as launch, contextlib.redirect_stderr(stderr):
            issues = G._issues(command)
        assert issues is None, issues
        assert launch.call_args.kwargs["timeout"] == 120
        assert all(part in stderr.getvalue() for part in expected), stderr.getvalue()
    noisy = "discarded-prefix\n" + ("x" * 1000 + "\n") * 20
    stderr = io.StringIO()
    with mock.patch.object(G.subprocess, "run", side_effect=subprocess.TimeoutExpired(
            command, 120, output=noisy, stderr=noisy)), contextlib.redirect_stderr(stderr):
        assert G._issues(command) is None
    assert "discarded-prefix" not in stderr.getvalue()
    assert len(stderr.getvalue()) < 8500, "subprocess diagnostics must remain bounded"


def test_evidence_git_and_log_failures_report_their_source():
    sys.path.insert(0, str(ROOT / "tools"))
    import gate as G
    import contextlib
    import io
    from unittest import mock

    stderr = io.StringIO()
    results = [subprocess.CompletedProcess(["git"], 1, "", "not a repository"),
               subprocess.CompletedProcess(["git"], 2, "", "synthetic git init failure")]
    with mock.patch.object(G.subprocess, "run", side_effect=results), contextlib.redirect_stderr(stderr):
        assert G._ensure_git_tree("/synthetic-tree") is False
    assert "evidence Git setup failed: init: exit=2" in stderr.getvalue(), stderr.getvalue()
    assert "synthetic git init failure" in stderr.getvalue()
    stderr = io.StringIO()
    with mock.patch.object(G.subprocess, "run", side_effect=OSError("synthetic git launch")), \
            contextlib.redirect_stderr(stderr):
        try:
            G._ensure_git_tree("/synthetic-tree")
        except OSError:
            pass
        else:
            raise AssertionError("Git launch errors must still propagate")
    assert "evidence Git probe could not run" in stderr.getvalue(), stderr.getvalue()
    with tempfile.TemporaryDirectory(prefix="evidence-log-error-") as temporary:
        root = pathlib.Path(temporary)
        blocker = root / "not-a-directory"
        blocker.write_text("fixture", encoding="utf-8")
        log = blocker / "runs.log"
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {
                "MOTTORI_TEST_LOG": str(log), "MOTTORI_TEST_RUN_ID": "log-error-fixture"}):
            os.environ.pop("MOTTORI_TEST_EVIDENCE_ACTIVE", None)
            with mock.patch.object(G, "_ensure_git_tree", return_value=True), \
                    contextlib.redirect_stderr(stderr):
                path, ok = G._refresh_test_evidence(str(root))
        assert path == str(log) and ok is False, (path, ok)
        assert "test evidence log unavailable" in stderr.getvalue(), stderr.getvalue()


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
        if env.get("MOTTORI_TEST_EVIDENCE_ACTIVE") != "1":
            records = pathlib.Path(env["MOTTORI_TEST_LOG"]).read_text().splitlines()
            run_ids = {line.split()[1] for line in records if line.startswith("RAN ")}
            assert len(run_ids) == 1, run_ids
            env["MOTTORI_TEST_RUN_ID"] = run_ids.pop()
        # The baseline above ran the real outer suite. Subsequent fixture operations consume
        # that completed attempt while checking staged-document rejection below.
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
    test_refresh_reruns_inherited_evidence_with_new_ids,
    test_refresh_retries_after_later_test_failure,
    test_refresh_rechecks_imports_and_rejects_old_test_coverage,
    test_refresh_timeout_late_records_cannot_cover_retry,
    test_refresh_reports_timeout_and_launch_error_without_evidence,
    test_checker_failure_diagnostics_keep_unavailable_verdict,
    test_evidence_git_and_log_failures_report_their_source,
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
