#!/usr/bin/env python3
"""Exercise worker-cluster upgrades and rollback in disposable instances."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SYNC = HERE / "sync_engine.sh"


def inventory():
    tree = ast.parse((HERE / "fresh_worker.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "SYNC_FILES" for t in n.targets))
    return ast.literal_eval(node.value)


def fixture():
    root = Path(tempfile.mkdtemp(prefix="worker sync instance "))
    (root / "tools").mkdir()
    (root / "system").mkdir()
    config = {"schema_version": 4, "instance": {"name": "fixture", "context": "personal"},
              "tracks": [{"key": "system", "name": "System", "canonical": "README.md"}],
              "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                                     "legacy_public_tracks": []}}
    (root / "system/memory-config.json").write_text(json.dumps(config))
    for name in inventory():
        (root / "tools" / name).write_text(f"# previous {name}\n")
    for name in ("now.py", "doctor.py", "i18n.py"):
        shutil.copy2(HERE / name, root / "tools" / name)
    (root / "tools/memlib.py").write_text("LEGACY_CONTEXT = 'legacy state still available'\n")
    return root


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


def env(root, **extra):
    value = {k: v for k, v in os.environ.items() if not k.upper().startswith(("GIT_", "CLAUDE_", "ANTHROPIC_", "OPENAI_", "CODEX_"))}
    value.update(MOTTORI_INSTANCE=str(root), HOME=str(root / ".fixture-home"),
                 CODEX_HOME=str(root / ".fixture-home/.codex"), PYTHONDONTWRITEBYTECODE="1", **extra)
    return value


def sync(root, kit=ROOT, extra=None):
    return subprocess.run(["bash", str(kit / "tools/sync_engine.sh"), str(root)],
                          cwd=kit, env=env(root, **(extra or {})), capture_output=True,
                          text=True, timeout=60)


def test_old_memlib_upgrades_with_real_state_consumers_and_worker():
    root = fixture()
    foreign = Path(tempfile.mkdtemp(prefix="foreign-git-context-"))
    try:
        subprocess.run(["git", "init", "-q", str(foreign)], check=True)
        before = {name: data for name, data in tree_bytes(root).items()
                  if name not in {"tools/" + item for item in inventory()}}
        result = sync(root, extra={"GIT_DIR": str(foreign / ".git"), "GIT_WORK_TREE": str(foreign)})
        assert result.returncode == 0, (result.stdout, result.stderr)
        after = {name: data for name, data in tree_bytes(root).items()
                 if name not in {"tools/" + item for item in inventory()}}
        assert after == before
        assert (root / "tools/memlib.py").read_bytes() == (HERE / "memlib.py").read_bytes()
        assert (root / "tools/testlib.py").read_bytes() == (HERE / "testlib.py").read_bytes()
        # The instance's non-cluster consumer and localization files remain intact.
        for name in ("now.py", "doctor.py", "i18n.py"):
            assert (root / "tools" / name).read_bytes() == (HERE / name).read_bytes()
        identity = subprocess.run([sys.executable, "-c",
                                   "import json,fresh_worker as f; print(json.dumps(f._engine_identity()))"],
                                  cwd=root / "tools", env=env(root), capture_output=True, text=True)
        assert identity.returncode == 0, identity.stderr
        data = json.loads(identity.stdout)
        expected_rev = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        assert data["kit_rev"] == expected_rev and data["kit_rev_source"] == "embedded"
        assert data["kit_sync"]["matches_copy"] is True
        prompt = root / "prompt.md"
        prompt.write_text("Reply with an optional read declaration.\n")
        runtime = root / "fake codex"
        runtime.write_text("#!/usr/bin/env python3\nimport json,pathlib,sys\n"
                           "args=sys.argv[1:]; sys.stdin.read()\n"
                           "pathlib.Path(args[args.index('--output-last-message')+1]).write_text('READ_SCOPE: prompt.md\\nUNREAD: none\\n')\n"
                           "print(json.dumps({'type':'turn.completed'}))\n")
        runtime.chmod(0o755)
        run = subprocess.run([sys.executable, str(root / "tools/fresh_worker.py"), "--runtime", "codex", str(prompt)],
                             cwd=root, env=env(root, MOTTORI_FRESH_WORKER_CODEX_BIN=str(runtime)),
                             capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, (run.stdout, run.stderr)
        run_rel = next(line[5:] for line in run.stdout.splitlines() if line.startswith("run: "))
        meta = json.loads((root / run_rel / "meta.json").read_text())
        assert meta["read_scope"] == {"declared": "READ_SCOPE: prompt.md", "unread": "UNREAD: none"}
        assert not list((root / "tools").glob(".sync-engine.*"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(foreign, ignore_errors=True)


def test_old_consumer_failure_restores_cluster_and_session_context():
    root = fixture()
    try:
        (root / "tools/now.py").write_text(
            "import json,memlib\n"
            "def hook_context():\n"
            " print(json.dumps({'hookSpecificOutput': {'hookEventName':'SessionStart',"
            "'additionalContext':memlib.LEGACY_CONTEXT}}))\n"
            " return 0\n"
            "if __name__ == '__main__': raise SystemExit(hook_context())\n")
        # Neither configuration nor an old consumer belongs to the copied cluster.
        config = root / "system/memory-config.json"
        document = json.loads(config.read_text())
        for schema in (4, 3):
            document["schema_version"] = schema
            config.write_text(json.dumps(document))
            before = tree_bytes(root)
            result = sync(root)
            expected = "now compatibility" if schema == 4 else "doctor compatibility"
            assert result.returncode != 0 and expected in result.stderr, result.stderr
            assert tree_bytes(root) == before
        hook = subprocess.run([sys.executable, str(root / "tools/now.py"), "hook-context"],
                              cwd=root, env=env(root), capture_output=True, text=True)
        assert hook.returncode == 0, hook.stderr
        assert json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"] == "legacy state still available"
        assert tree_bytes(root) == before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_schema_migration_and_invalid_config_each_rollback():
    for invalid in (False, True):
        root = fixture()
        try:
            config = root / "system/memory-config.json"
            doc = json.loads(config.read_text())
            doc["schema_version"] = 3
            config.write_text("[]" if invalid else json.dumps(doc))
            before = tree_bytes(root)
            result = sync(root)
            assert result.returncode != 0, result.stdout
            expected = "configuration is missing or invalid" if invalid else "doctor compatibility check failed"
            assert expected in result.stderr, result.stderr
            assert tree_bytes(root) == before
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_destination_symlinks_cannot_write_outside_instance():
    for target in ("memlib.py", "tools"):
        root = fixture()
        outside = Path(tempfile.mkdtemp(prefix="sync-outside-"))
        try:
            sentinel = outside / "sentinel"
            sentinel.write_text("untouched\n")
            if target == "tools":
                shutil.rmtree(root / "tools")
                (root / "tools").symlink_to(outside, target_is_directory=True)
            else:
                (root / "tools" / target).unlink()
                (root / "tools" / target).symlink_to(sentinel)
            before = tree_bytes(outside)
            result = sync(root)
            assert result.returncode != 0, result.stdout
            assert tree_bytes(outside) == before
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(outside, ignore_errors=True)


def test_source_symlink_is_rejected_before_import():
    root = fixture()
    kit = Path(tempfile.mkdtemp(prefix="sync-source-copy-"))
    outside = Path(tempfile.mkdtemp(prefix="sync-source-outside-"))
    try:
        (kit / "tools").mkdir()
        for name in (*inventory(), "sync_engine.sh"):
            shutil.copy2(HERE / name, kit / "tools" / name)
        marker = outside / "imported"
        evil = outside / "auth.py"
        evil.write_text(f"open({str(marker)!r}, 'w').write('executed')\n")
        (kit / "tools/claude_auth.py").unlink()
        (kit / "tools/claude_auth.py").symlink_to(evil)
        before = tree_bytes(root)
        result = sync(root, kit=kit)
        assert result.returncode != 0 and "source must be a regular file" in result.stderr, result.stderr
        assert not marker.exists()
        assert tree_bytes(root) == before
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(kit, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


TESTS = (
    test_old_memlib_upgrades_with_real_state_consumers_and_worker,
    test_old_consumer_failure_restores_cluster_and_session_context,
    test_schema_migration_and_invalid_config_each_rollback,
    test_destination_symlinks_cannot_write_outside_instance,
    test_source_symlink_is_rejected_before_import,
)

if __name__ == "__main__":
    for test in TESTS:
        run_test(test, __file__)
        print("PASS", test.__name__)
