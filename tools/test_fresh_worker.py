#!/usr/bin/env python3
"""Fixture tests for the bounded fresh-worker interface (KIT-DR-007)."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
WORKER = HERE / "fresh_worker.py"


def _script(path, body):
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run(root, runtime, prompt, binary):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root))
    env[f"MOTTORI_FRESH_WORKER_{runtime.upper()}_BIN"] = str(binary)
    return subprocess.run(
        [sys.executable, str(WORKER), "--runtime", runtime, str(prompt)],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
    )


def _run_dir(root, receipt):
    line = next(x for x in receipt.splitlines() if x.startswith("run: "))
    return root / line.split(": ", 1)[1]


def test_claude_trace_cap_and_capability():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-claude-"))
    try:
        prompt = root / "review prompt.md"
        prompt.write_text("Review safely.\n", encoding="utf-8")
        fake = root / "fake claude"
        _script(fake, """
import json, sys
args = sys.argv[1:]
body = sys.stdin.read()
print(json.dumps({"type":"system","args":args,"prompt":body}, ensure_ascii=False))
print(json.dumps({"type":"result","result":"검" * 400000}, ensure_ascii=False))
""")
        r = _run(root, "claude", prompt, fake)
        assert r.returncode == 0, r.stderr
        assert len(r.stdout.encode("utf-8")) <= 4096
        assert "capability: read-only" in r.stdout
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["capability"] == "read-only" and meta["status"] == "success"
        assert "--no-session-persistence" in meta["command"]
        assert "--safe-mode" in meta["command"]
        assert "--strict-mcp-config" in meta["command"]
        assert "--disable-slash-commands" in meta["command"]
        assert meta["command"][meta["command"].index("--mcp-config") + 1] == (
            '{"mcpServers":{}}')
        assert "bypassPermissions" not in meta["command"]
        assert meta["command"][meta["command"].index("--tools") + 1:][:3] == [
            "Read", "Glob", "Grep"]
        assert (run / "stream.jsonl").stat().st_size > 1_000_000
        assert (run / "result.txt").stat().st_size > 1_000_000
        assert stat.S_IMODE(run.stat().st_mode) == 0o700
        for child in run.iterdir():
            assert stat.S_IMODE(child.stat().st_mode) == 0o600, child
        r.stdout.encode("utf-8").decode("utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_codex_prompt_is_data_not_shell_and_workspace_capability():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-codex-"))
    try:
        marker = root / "PWNED"
        prompt = root / "명령 $(아님); prompt.md"
        prompt.write_text(f"literal `date`; $(touch {marker}); end\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, """
import json, pathlib, sys
args = sys.argv[1:]
body = sys.stdin.read()
out = pathlib.Path(args[args.index("--output-last-message") + 1])
out.write_text("CODEX_OK\\n" + body[-120:], encoding="utf-8")
print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"ok"}}))
""")
        r = _run(root, "codex", prompt, fake)
        assert r.returncode == 0, r.stderr
        assert not marker.exists(), "prompt content executed in a shell"
        assert "capability: workspace-write" in r.stdout
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["capability"] == "workspace-write"
        assert "--ephemeral" in meta["command"]
        assert "--ignore-user-config" in meta["command"]
        assert 'web_search="disabled"' in meta["command"]
        assert "sandbox_workspace_write.network_access=false" in meta["command"]
        assert "agents.enabled=false" in meta["command"]
        disabled = [meta["command"][i + 1] for i, arg in enumerate(meta["command"][:-1])
                    if arg == "--disable"]
        for feature in ("apps", "hooks", "image_generation", "memories", "multi_agent",
                        "plugins", "tool_suggest"):
            assert feature in disabled
        assert "--sandbox" in meta["command"] and "workspace-write" in meta["command"]
        assert "$(touch" in (run / "prompt.md").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_prompt_boundaries_fail_closed():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-input-"))
    outside = Path(tempfile.mkdtemp(prefix="fresh-worker-outside-"))
    try:
        fake = root / "fake"
        _script(fake, "print('unused')\n")
        empty = root / "empty.md"
        empty.write_text("", encoding="utf-8")
        r = _run(root, "claude", empty, fake)
        assert r.returncode == 2 and "비어" in r.stderr

        external = outside / "outside.md"
        external.write_text("x", encoding="utf-8")
        r = _run(root, "claude", external, fake)
        assert r.returncode == 2 and "workspace 밖" in r.stderr

        actual = root / "actual"
        actual.mkdir()
        (actual / "prompt.md").write_text("x", encoding="utf-8")
        linked = root / "linked"
        linked.symlink_to(actual, target_is_directory=True)
        r = _run(root, "claude", linked / "prompt.md", fake)
        assert r.returncode == 2 and "symlink" in r.stderr

        direct = root / "direct.md"
        direct.write_text("x", encoding="utf-8")
        sym = root / "sym.md"
        sym.symlink_to(direct)
        r = _run(root, "claude", sym, fake)
        assert r.returncode == 2 and "symlink" in r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_missing_result_is_not_success_and_no_runtime_fallback():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-missing-"))
    try:
        prompt = root / "prompt.md"
        prompt.write_text("x", encoding="utf-8")
        fake = root / "fake claude"
        _script(fake, "print('{\"type\":\"system\"}')\n")
        r = _run(root, "claude", prompt, fake)
        assert r.returncode == 3
        assert "status: failed-missing-result" in r.stdout
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["process_exit"] == 0 and meta["wrapper_exit"] == 3
        assert meta["runtime"] == "claude"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_parity_requires_exact_import():
    sys.path.insert(0, str(HERE))
    import doctor
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-parity-"))
    old = doctor.ROOT
    try:
        doctor.ROOT = str(root)
        (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        status, _ = doctor.c_agents_parity()
        assert status == doctor.PASS

        (root / "CLAUDE.md").write_text("rules\n", encoding="utf-8")
        status, _ = doctor.c_agents_parity()
        assert status == doctor.FAIL

        (root / "CLAUDE.md").write_text("different\n", encoding="utf-8")
        status, _ = doctor.c_agents_parity()
        assert status == doctor.FAIL

        (root / "AGENTS.md").unlink()
        status, _ = doctor.c_agents_parity()
        assert status == doctor.FAIL
    finally:
        doctor.ROOT = old
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_claude_trace_cap_and_capability,
    test_codex_prompt_is_data_not_shell_and_workspace_capability,
    test_prompt_boundaries_fail_closed,
    test_missing_result_is_not_success_and_no_runtime_fallback,
    test_parity_requires_exact_import,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
