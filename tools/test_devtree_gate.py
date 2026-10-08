#!/usr/bin/env python3
"""Regression tests for the unconfigured kit-development-tree gate contract."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


ROOT = Path(__file__).resolve().parent.parent


def fixture_env(root):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    for key in ("MOTTORI_INSTANCE", "CLAUDE_PROJECT_DIR", "MOTTORI_TEST_EVIDENCE_ACTIVE"):
        env.pop(key, None)
    env.update(MOTTORI_LANG="ko", MOTTORI_TEST_LOG=str(root / ".git" / "devtree-runs.log"),
               MOTTORI_TEST_RUN_ID=root.parent.name)
    return env


def run(root, *args, check=False):
    result = subprocess.run(
        [sys.executable, *args], cwd=root, env=fixture_env(root),
        capture_output=True, text=True,
    )
    if check and result.returncode:
        raise AssertionError(
            f"{' '.join(args)} exit={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def fixture_tree():
    """Stage current gate/state tools with a small, independently executed evidence probe."""
    outer = Path(tempfile.mkdtemp(prefix="devtree-gate-"))
    root = outer / "repo"
    root.mkdir()
    paths = ("templates/memory-config.json", *("tools/" + name for name in (
        "gate.py", "enforce.py", "memlib.py", "i18n.py", "now.py", "linkcheck.py",
        "evidencecheck.py", "manifest_build.py", "testlib.py")))
    for rel in paths:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    marker = "`test:tools/test_devtree_probe.py::test_probe`"
    files = {
        ".gitignore": "_private/\nstate/\nsystem/memory-config.json\n",
        "README.md": "# Synthetic gate fixture\n",
        "system/kit-decisions.md": "### DR-001 fixture\nContext: " + marker + ".\n",
        "CHANGELOG.md": "## v0\n\n### [Note] fixture\nEvidence: " + marker + ".\n",
        "system/enforcement-matrix.md": (
            "| Contract | Status | Evidence |\n|---|---|---|\n"
            "| fixture | ENFORCED | " + marker + " |\n"),
        "tools/test_devtree_probe.py": (
            "from pathlib import Path\nfrom testlib import run_test\n"
            "def test_probe():\n"
            "    root = Path(__file__).resolve().parents[1]\n"
            "    assert (root / 'README.md').read_text() == '# Synthetic gate fixture\\n'\n"
            "if __name__ == '__main__':\n    run_test(test_probe, __file__)\n"),
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (root / "state").mkdir()
    env = fixture_env(root)
    for command in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                     "commit", "-qm", "synthetic gate fixture"]):
        subprocess.run(command, cwd=root, env=env, check=True, capture_output=True, text=True)
    return outer, root


def check_output(root, *extra):
    return run(root, str(root / "tools" / "now.py"), "check", "--issues", *extra)


def test_unconfigured_devtree_precommit_is_not_applicable():
    outer, root = fixture_tree()
    try:
        assert not (root / "system" / "memory-config.json").exists()
        assert not (root / "state" / "NOW.md").exists()
        assert not list((root / "state").glob("journal-*.md"))
        assert not (root / "_private" / "state" / "NOW.md").exists()
        assert not list((root / "_private" / "state").glob("journal-*.md"))
        assert not (root / "_private" / "state" / "threads.json").exists()

        for result in (check_output(root), check_output(root, "--portable")):
            assert result.returncode == 0, result.stdout + result.stderr
            assert "~now-not-applicable\t" in result.stdout, result.stdout
            assert "해당없음" in result.stdout, result.stdout
            assert result.stdout.rstrip().endswith("#issues 0"), result.stdout
            assert "now-input-newer" not in result.stdout, result.stdout

        baseline = run(root, str(root / "tools" / "gate.py"), "baseline")
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        precommit = run(root, str(root / "tools" / "gate.py"), "precommit")
        assert precommit.returncode == 0, precommit.stdout + precommit.stderr
        selfcheck = run(root, str(root / "tools" / "gate.py"), "selfcheck")
        assert selfcheck.returncode == 0, selfcheck.stdout + selfcheck.stderr
        assert "selfcheck: PASS" in selfcheck.stdout, selfcheck.stdout
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_partial_install_without_config_fails_closed():
    outer, root = fixture_tree()
    try:
        baseline = run(root, str(root / "tools" / "gate.py"), "baseline")
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr

        state = root / "state"
        state.mkdir(exist_ok=True)
        now_path = state / "NOW.md"
        now_path.write_text("# legacy NOW without content marker\n", encoding="utf-8")
        journal = state / f"journal-{datetime.datetime.now():%Y-%m}.md"
        journal.write_text(
            "# journal\n\n- 2026-09-17T00:00:00+09:00 [system/state] partial install\n",
            encoding="utf-8",
        )

        before = now_path.read_bytes()
        rendered = run(root, str(root / "tools" / "now.py"), "render")
        assert rendered.returncode != 0, rendered.stdout + rendered.stderr
        assert "visibility config" in rendered.stderr, rendered.stderr
        assert now_path.read_bytes() == before

        for result in (check_output(root), check_output(root, "--portable")):
            assert result.returncode == 0, result.stdout + result.stderr
            assert "config-absent\t" in result.stdout, result.stdout
            assert result.stdout.rstrip().endswith("#issues 1"), result.stdout
            assert "now-input-newer" not in result.stdout, result.stdout

        precommit = run(root, str(root / "tools" / "gate.py"), "precommit")
        assert precommit.returncode != 0, precommit.stdout + precommit.stderr
        assert "now-check: config-absent" in precommit.stderr, precommit.stderr
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_private_only_partial_install_without_config_fails_closed():
    residues = (
        ("NOW.md", "# local NOW without config\n"),
        (
            f"journal-{datetime.datetime.now():%Y-%m}.md",
            "# journal\n\n- 2026-09-17T00:00:00+09:00 "
            "[system/state] private partial install\n",
        ),
        ("threads.json", "[]\n"),
    )
    for name, content in residues:
        outer, root = fixture_tree()
        try:
            baseline = run(root, str(root / "tools" / "gate.py"), "baseline")
            assert baseline.returncode == 0, baseline.stdout + baseline.stderr

            private_state = root / "_private" / "state"
            private_state.mkdir(parents=True, exist_ok=True)
            (private_state / name).write_text(content, encoding="utf-8")
            assert not (root / "system" / "memory-config.json").exists()
            assert not (root / "state" / "NOW.md").exists()
            assert not list((root / "state").glob("journal-*.md"))

            for result in (check_output(root), check_output(root, "--portable")):
                assert result.returncode == 0, result.stdout + result.stderr
                assert "config-absent\t" in result.stdout, result.stdout
                assert result.stdout.rstrip().endswith("#issues 1"), result.stdout
                assert "now-input-newer" not in result.stdout, result.stdout

            precommit = run(root, str(root / "tools" / "gate.py"), "precommit")
            assert precommit.returncode != 0, precommit.stdout + precommit.stderr
            assert "now-check: config-absent" in precommit.stderr, precommit.stderr
        finally:
            shutil.rmtree(outer, ignore_errors=True)


def test_selfcheck_warns_with_both_different_issue_sets():
    outer, root = fixture_tree()
    try:
        config = json.loads((root / "templates" / "memory-config.json").read_text(encoding="utf-8"))
        config["instance"].update({"name": "fixture", "context": "personal"})
        config["tracks"] = []
        config_path = root / "system" / "memory-config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        logged = run(
            root,
            str(root / "tools" / "now.py"),
            "log",
            "[system/state] SELFCHECK-SEED",
        )
        assert logged.returncode == 0, logged.stdout + logged.stderr
        private_state = root / "_private" / "state"
        private_state.mkdir(parents=True, exist_ok=True)
        (private_state / f"journal-{datetime.datetime.now():%Y-%m}.md").write_text(
            "- malformed private journal row\n", encoding="utf-8"
        )

        result = run(root, str(root / "tools" / "gate.py"), "selfcheck")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "selfcheck: WARN" in result.stdout, result.stdout
        assert "direct=" in result.stdout and "precommit=" in result.stdout, result.stdout
        assert "now-check:journal-corrupt:" in result.stdout, result.stdout
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_fixture_evidence_is_isolated_and_fail_closed():
    outer, root = fixture_tree()
    try:
        log = root / ".git" / "devtree-runs.log"
        assert not log.exists()
        baseline = run(root, str(root / "tools/gate.py"), "baseline")
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        assert "evidencecheck 0건" in baseline.stdout, baseline.stdout
        records = log.read_text(encoding="utf-8").splitlines()
        assert records and all(line.endswith(" tools/test_devtree_probe.py::test_probe")
                               for line in records), records
        probe = root / "tools/test_devtree_probe.py"
        log.write_text("", encoding="utf-8")
        probe.write_text("raise RuntimeError('synthetic probe failure')\n", encoding="utf-8")
        failed = run(root, str(root / "tools/gate.py"), "baseline")
        assert failed.returncode != 0, failed.stdout + failed.stderr
        assert "test evidence suite failed: tools/test_devtree_probe.py" in failed.stderr, failed.stderr
        assert "synthetic probe failure" in failed.stderr, failed.stderr
        probe.unlink()
        missing = run(root, str(root / "tools/gate.py"), "baseline")
        assert missing.returncode != 0, missing.stdout + missing.stderr
        assert "test evidence suite missing: tools/test_devtree_probe.py" in missing.stderr, missing.stderr
    finally:
        shutil.rmtree(outer, ignore_errors=True)


TESTS = [
    test_fixture_evidence_is_isolated_and_fail_closed,
    test_unconfigured_devtree_precommit_is_not_applicable,
    test_partial_install_without_config_fails_closed,
    test_private_only_partial_install_without_config_fails_closed,
    test_selfcheck_warns_with_both_different_issue_sets,
]


def main():
    failures = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print(f"✓ {test.__name__}")
        except Exception as error:  # noqa: BLE001
            failures.append(test.__name__)
            print(f"✗ {test.__name__}: {type(error).__name__}: {error}")
    print(f"devtree gate: {len(TESTS) - len(failures)}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
