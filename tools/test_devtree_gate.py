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


ROOT = Path(__file__).resolve().parent.parent


def run(root, *args, check=False):
    env = dict(os.environ, MOTTORI_LANG="ko")
    env.pop("MOTTORI_INSTANCE", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    result = subprocess.run(
        [sys.executable, *args], cwd=root, env=env, capture_output=True, text=True
    )
    if check and result.returncode:
        raise AssertionError(
            f"{' '.join(args)} exit={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def clone_current_tree():
    """Clone HEAD, then stage current delivery bytes so the fixture tests this checkout."""
    outer = Path(tempfile.mkdtemp(prefix="devtree-gate-"))
    clone = outer / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    paths = {raw.decode("utf-8") for raw in listed.split(b"\0") if raw}
    # A fresh-install test stages this newly delivered fixture before invoking it, while a
    # worker checkout may not. Include the fixture in both cases so nested direct/index
    # evidence measurements see the same tree.
    paths.add(Path(__file__).relative_to(ROOT).as_posix())
    for rel in sorted(paths):
        source = ROOT / rel
        target = clone / rel
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif target.exists():
            target.unlink()
    subprocess.run(
        ["git", "-C", str(clone), "add", "-A"],
        check=True,
        capture_output=True,
        text=True,
    )
    return outer, clone


def check_output(root, *extra):
    return run(root, str(root / "tools" / "now.py"), "check", "--issues", *extra)


def test_unconfigured_devtree_precommit_is_not_applicable():
    outer, root = clone_current_tree()
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
    outer, root = clone_current_tree()
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
        outer, root = clone_current_tree()
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
    outer, root = clone_current_tree()
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


TESTS = [
    test_unconfigured_devtree_precommit_is_not_applicable,
    test_partial_install_without_config_fails_closed,
    test_private_only_partial_install_without_config_fails_closed,
    test_selfcheck_warns_with_both_different_issue_sets,
]


def main():
    failures = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as error:  # noqa: BLE001
            failures.append(test.__name__)
            print(f"✗ {test.__name__}: {type(error).__name__}: {error}")
    print(f"devtree gate: {len(TESTS) - len(failures)}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
