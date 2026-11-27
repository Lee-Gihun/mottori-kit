#!/usr/bin/env python3
"""Regression tests of the gate in a kit development tree before setup and in an installed
instance: the same checks judge both, through the commit check and the turn-end hooks."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def fixture_env(root):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    for key in ("MOTTORI_INSTANCE", "CLAUDE_PROJECT_DIR"):
        env.pop(key, None)
    # The fixture commits with git; a developer's global signing or hook settings must not apply.
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
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
    """Commit the current gate and state tools in a tree shaped like a kit before setup."""
    outer = Path(tempfile.mkdtemp(prefix="devtree-gate-"))
    root = outer / "repo"
    root.mkdir()
    paths = ("templates/config.json", *("tools/" + name for name in (
        "gate.py", "enforce.py", "lib/adopted.py", "lib/config.py", "lib/hook_input.py", "lib/journal.py",
        "lib/paths.py", "lib/runlog.py", "lib/safeio.py", "now.py", "lib/memory_index.py", "linkcheck.py",
        "tests/testlib.py")))
    for rel in paths:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    files = {
        ".gitignore": "_private/\nstate/\nnotes/\ninstance/config.json\n",
        "README.md": "# Synthetic gate fixture\n",
        "system/specs/kit-decisions.md": "### DR-001 fixture\nContext: evidence: none\n",
        # setup.sh with templates/ and no instance config marks a kit development tree.
        "setup.sh": "#!/usr/bin/env bash\n",
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


STOP = json.dumps({"session_id": "x", "stop_hook_active": False, "hook_event_name": "Stop"})


def gate_hook(root, command, payload=STOP):
    """Run one gate hook command the way Claude Code does: JSON on stdin."""
    return subprocess.run(
        [sys.executable, str(root / "tools" / "gate.py"), command], cwd=root,
        env=fixture_env(root), input=payload, capture_output=True, text=True,
    )


def block_reason(result):
    """Return the Stop block reason, or None when the hook let the turn end."""
    assert result.returncode == 0, result.stdout + result.stderr
    if not result.stdout.strip():
        return None
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block", result.stdout
    return decision["reason"]


def installed_tree():
    """Turn the fixture into an installed instance: instance config present, state rendered."""
    outer, root = fixture_tree()
    config = json.loads((root / "templates" / "config.json").read_text(encoding="utf-8"))
    config["instance"].update({"name": "fixture"})
    config["tracks"] = []
    (root / "instance").mkdir()
    (root / "instance" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    for args in (("log", "[system/state] installed fixture"), ("render",)):
        run(root, str(root / "tools" / "now.py"), *args, check=True)
    run(root, str(root / "tools" / "gate.py"), "baseline", check=True)
    return outer, root


def test_installed_user_edits_do_not_block_but_broken_links_do():
    outer, root = installed_tree()
    try:
        (root / "notes").mkdir()
        (root / "notes" / "meeting.md").write_text("# 회의 메모\n", encoding="utf-8")
        (root / "system" / "team-notes.md").write_text("# team notes\n", encoding="utf-8")
        with (root / "README.md").open("a", encoding="utf-8") as readme:
            readme.write("\nlocal note\n")
        gate_hook(root, "dirty", json.dumps({"tool_input": {"file_path": str(root / "README.md")}}))
        assert block_reason(gate_hook(root, "check")) is None
        with (root / "README.md").open("a", encoding="utf-8") as readme:
            readme.write("[gone](missing-target.md)\n")
        gate_hook(root, "dirty", "{}")
        reason = block_reason(gate_hook(root, "check"))
        assert reason and "README.md" in reason and "missing-target.md" in reason, reason
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_installed_check_sees_shell_edits_without_marker():
    outer, root = installed_tree()
    try:
        assert block_reason(gate_hook(root, "check")) is None
        readme = root / "README.md"
        readme.write_text("# Synthetic gate fixture\n[gone](first-missing.md)\n", encoding="utf-8")
        reason = block_reason(gate_hook(root, "check"))
        assert reason and "first-missing.md" in reason, reason
        repaired = "# Synthetic gate fixture\nrepaired without any link\n"
        broken = "# Synthetic gate fixture\n[gone](second-missing.md)\n"
        assert len(repaired) == len(broken)
        readme.write_text(repaired, encoding="utf-8")
        assert block_reason(gate_hook(root, "check")) is None
        # README stays " M" in git status and keeps its size; only its mtime reveals the second
        # edit. The explicit bump keeps that true on filesystems with coarse mtime resolution.
        before = readme.stat().st_mtime_ns
        readme.write_text(broken, encoding="utf-8")
        os.utime(readme, ns=(before + 2_000_000_000, before + 2_000_000_000))
        reason = block_reason(gate_hook(root, "check"))
        assert reason and "second-missing.md" in reason, reason
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_dirty_ignores_edits_outside_the_instance_root():
    outer, root = installed_tree()
    try:
        marker = root / ".git" / "mottori-gate-dirty"
        elsewhere = outer / "elsewhere.md"
        gate_hook(root, "dirty", json.dumps({"tool_input": {"file_path": str(elsewhere)}}))
        assert not marker.exists()
        gate_hook(root, "dirty", json.dumps({"tool_input": {"notebook_path": str(elsewhere)}}))
        assert not marker.exists()
        gate_hook(root, "dirty", json.dumps({"tool_input": {"file_path": str(root / "README.md")}}))
        assert marker.exists()
        marker.unlink()
        gate_hook(root, "dirty", "not json")
        assert marker.exists(), "an unreadable payload must still mark the turn"
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_checker_failure_reason_names_the_checker():
    outer, root = installed_tree()
    try:
        (root / "tools" / "linkcheck.py").write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        gate_hook(root, "dirty", "{}")
        reason = block_reason(gate_hook(root, "check"))
        assert reason and "linkcheck" in reason and "exit=7" in reason, reason
        assert len(reason) < 600, reason
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_resume_reports_the_last_block_reason():
    outer, root = installed_tree()
    try:
        (root / "README.md").write_text("[gone](resume-missing.md)\n", encoding="utf-8")
        gate_hook(root, "dirty", "{}")
        assert block_reason(gate_hook(root, "check"))
        resumed = gate_hook(root, "resume", "{}")
        assert resumed.returncode == 0, resumed.stderr
        context = json.loads(resumed.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "resume-missing.md" in context, context
        assert (root / ".git" / "mottori-gate-pending").exists()
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_devtree_commit_refuses_a_broken_link_like_an_installed_one():
    """Before setup the commit check is the one an installed instance runs: a staged broken link
    is refused, and a contributor tool that does not compile is left to the suite."""
    outer, root = fixture_tree()
    try:
        gate = str(root / "tools" / "gate.py")
        run(root, gate, "baseline", check=True)
        (root / "README.md").write_text("# Synthetic gate fixture\n[gone](commit-missing.md)\n",
                                        encoding="utf-8")
        (root / "tools" / "tests" / "test_broken.py").write_text("def (:\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, env=fixture_env(root), check=True)
        refused = run(root, gate, "precommit")
        assert refused.returncode == 1, refused.stdout + refused.stderr
        assert "README.md -> commit-missing.md" in refused.stderr, refused.stderr
        assert "test_broken.py" not in refused.stderr, refused.stderr
        (root / "README.md").write_text("# Synthetic gate fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, env=fixture_env(root), check=True)
        passed = run(root, gate, "precommit")
        assert passed.returncode == 0, passed.stdout + passed.stderr
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def test_fixture_env_ignores_developer_git_config():
    env = fixture_env(Path(tempfile.gettempdir()) / "x" / "repo")
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull and env["GIT_CONFIG_NOSYSTEM"] == "1"


def check_output(root, *extra):
    return run(root, str(root / "tools" / "now.py"), "check", "--issues", *extra)


def test_unconfigured_devtree_precommit_is_not_applicable():
    outer, root = fixture_tree()
    try:
        assert not (root / "instance" / "config.json").exists()
        assert not (root / "state" / "NOW.md").exists()
        assert not list((root / "state").glob("journal-*.md"))
        assert not (root / "_private" / "state" / "NOW.md").exists()
        assert not list((root / "_private" / "state").glob("journal-*.md"))
        assert not (root / "_private" / "state" / "threads.json").exists()

        for result in (check_output(root), check_output(root, "--portable")):
            assert result.returncode == 0, result.stdout + result.stderr
            assert "~now-not-applicable\t" in result.stdout, result.stdout
            assert "not applicable" in result.stdout, result.stdout
            assert result.stdout.rstrip().endswith("#issues 0"), result.stdout
            assert "now-input-newer" not in result.stdout, result.stdout

        baseline = run(root, str(root / "tools" / "gate.py"), "baseline")
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        precommit = run(root, str(root / "tools" / "gate.py"), "precommit")
        assert precommit.returncode == 0, precommit.stdout + precommit.stderr
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

        # A NOW page without config is a damaged instance: the staged-index check refuses first.
        precommit = run(root, str(root / "tools" / "gate.py"), "precommit")
        assert precommit.returncode != 0, precommit.stdout + precommit.stderr
        assert "instance-config-missing" in precommit.stderr, precommit.stderr
        # The commit refusal names the way back, not only the ID.
        assert "config.json.bak" in precommit.stderr, precommit.stderr
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
            assert not (root / "instance" / "config.json").exists()
            assert not (root / "state" / "NOW.md").exists()
            assert not list((root / "state").glob("journal-*.md"))

            for result in (check_output(root), check_output(root, "--portable")):
                assert result.returncode == 0, result.stdout + result.stderr
                assert "config-absent\t" in result.stdout, result.stdout
                assert result.stdout.rstrip().endswith("#issues 1"), result.stdout
                assert "now-input-newer" not in result.stdout, result.stdout

            precommit = run(root, str(root / "tools" / "gate.py"), "precommit")
            assert precommit.returncode != 0, precommit.stdout + precommit.stderr
            # The staged-index check counts the same state files as now.py check, so it refuses first.
            assert "instance-config-missing" in precommit.stderr, precommit.stderr
        finally:
            shutil.rmtree(outer, ignore_errors=True)


TESTS = [
    test_unconfigured_devtree_precommit_is_not_applicable,
    test_partial_install_without_config_fails_closed,
    test_private_only_partial_install_without_config_fails_closed,
    test_installed_user_edits_do_not_block_but_broken_links_do,
    test_installed_check_sees_shell_edits_without_marker,
    test_dirty_ignores_edits_outside_the_instance_root,
    test_checker_failure_reason_names_the_checker,
    test_resume_reports_the_last_block_reason,
    test_devtree_commit_refuses_a_broken_link_like_an_installed_one,
    test_fixture_env_ignores_developer_git_config,
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
