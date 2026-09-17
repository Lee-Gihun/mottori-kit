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


def _git_ok(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True,
    ).stdout.strip()


def _init_worktree_repo():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-worktree-"))
    (root / "state").mkdir()
    (root / "system").mkdir()
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    (root / "delete.txt").write_text("delete me\n", encoding="utf-8")
    (root / "state" / ".gitkeep").write_text("", encoding="utf-8")
    (root / ".gitignore").write_text(
        "/_private/\n/system/memory-config.json\n/system/instance-rules.md\n"
        "/system/decisions.md\n/system/rituals.local.md\n/state/*\n!/state/.gitkeep\n",
        encoding="utf-8",
    )
    _git_ok(root, "init", "-q")
    _git_ok(root, "add", ".")
    _git_ok(root, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "-m", "init")
    for name in ("memory-config.json", "instance-rules.md", "decisions.md", "rituals.local.md"):
        (root / "system" / name).write_text(f"instance {name}\n", encoding="utf-8")
    prompt = root / "prompt.md"
    prompt.write_text("work in isolation\n", encoding="utf-8")
    fake = root / "fake codex"
    _script(fake, _CODEX_WRITER)
    return root, prompt, fake


def _run_worktree(root, prompt, binary, mode="head", prefixes=(), strict=False, extra_env=None):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root),
               MOTTORI_FRESH_WORKER_CODEX_BIN=str(binary), **(extra_env or {}))
    argv = [sys.executable, str(WORKER), "--runtime", "codex", f"--worktree={mode}"]
    if strict:
        argv.append("--strict-scope")
    for prefix in prefixes:
        argv += ["--write-prefix", prefix]
    argv.append(str(prompt))
    return subprocess.run(argv, cwd=root, env=env, text=True, capture_output=True)


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


def _fw():
    sys.path.insert(0, str(HERE))
    import fresh_worker
    return fresh_worker


def test_meta_v2_fields_present_end_to_end():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-v2-"))
    try:
        prompt = root / "p.md"
        prompt.write_text("Review.\n", encoding="utf-8")
        fake = root / "fake claude"
        _script(fake, """
import json, sys
body = sys.stdin.read()
print(json.dumps({"type":"assistant","message":{"usage":{"input_tokens":1,"output_tokens":2}}}))
print(json.dumps({"type":"result","result":"읽음: A, B\\n본문\\nUNREAD: 없음\\n",
                  "usage":{"input_tokens":10,"cache_creation_input_tokens":20,"cache_read_input_tokens":30,"output_tokens":5}}, ensure_ascii=False))
""")
        r = _run(root, "claude", prompt, fake)
        assert r.returncode == 0, r.stderr
        assert r.stdout.startswith("FRESH_WORKER v1\n")
        assert len(r.stdout.encode("utf-8")) <= 4096
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        assert meta["schema_version"] == 2
        assert isinstance(meta["harness_sha256"], str) and len(meta["harness_sha256"]) == 64
        assert meta["kit_rev"] is None or len(meta["kit_rev"]) == 40
        assert meta["kit_dirty"] in (True, False, None)
        assert len(meta["engine_sha256"]) == 64 and "agents_sha256" in meta and "repo_rev" in meta
        assert meta["usage"] == {"raw": {"input_tokens": 10, "cache_creation_input_tokens": 20,
                                         "cache_read_input_tokens": 30, "output_tokens": 5},
                                 "input": 60, "output": 5, "total": 65}
        assert meta["read_scope"] == {"declared": "읽음: A, B", "unread": "UNREAD: 없음"}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_harness_hash_stable_when_prompt_changes():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-hash-"))
    try:
        fake = root / "fake claude"
        _script(fake, """
import json, sys
sys.stdin.read()
print(json.dumps({"type":"result","result":"ok"}))
""")
        hashes = []
        for text in ("첫 프롬프트\n", "완전히 다른 두 번째 프롬프트\n"):
            prompt = root / f"p{len(hashes)}.md"
            prompt.write_text(text, encoding="utf-8")
            r = _run(root, "claude", prompt, fake)
            assert r.returncode == 0, r.stderr
            meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
            hashes.append(meta["harness_sha256"])
        assert hashes[0] == hashes[1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_harness_hash_changes_when_capability_changes():
    fw = _fw()
    base = fw._harness_sha256("claude", fw._claude_command())
    assert base != fw._harness_sha256("codex", fw._codex_command("/x/result.txt"), ("/x/result.txt",))
    # run-specific result path must not enter the codex hash
    assert fw._harness_sha256("codex", fw._codex_command("/a/r.txt"), ("/a/r.txt",)) == \
        fw._harness_sha256("codex", fw._codex_command("/b/r.txt"), ("/b/r.txt",))
    old = fw.CAPABILITIES["claude"]
    try:
        fw.CAPABILITIES["claude"] = "read-only-mutated"
        assert fw._harness_sha256("claude", fw._claude_command()) != base
    finally:
        fw.CAPABILITIES["claude"] = old
    assert fw._harness_sha256("claude", fw._claude_command()) == base


def test_usage_parsed_claude_and_codex():
    fw = _fw()
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-usage-"))
    try:
        claude = root / "claude.jsonl"
        claude.write_text(
            '{"type":"assistant","message":{"usage":{"input_tokens":1,"output_tokens":1}}}\n'
            'not json\n'
            '{"result":"x","usage":{"input_tokens":386,"cache_creation_input_tokens":522349,'
            '"cache_read_input_tokens":3396308,"output_tokens":62703},"type":"result"}\n',
            encoding="utf-8")
        assert fw._usage("claude", str(claude)) == {
            "raw": {"input_tokens": 386, "cache_creation_input_tokens": 522349,
                    "cache_read_input_tokens": 3396308, "output_tokens": 62703},
            "input": 3919043, "output": 62703, "total": 3981746}
        codex = root / "codex.jsonl"
        codex.write_text(
            '{"type":"item.completed","usage":{"input_tokens":999}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":5828479,"cached_input_tokens":5546112,'
            '"cache_write_input_tokens":0,"output_tokens":25855,"reasoning_output_tokens":6042}}\n',
            encoding="utf-8")
        u = fw._usage("codex", str(codex))
        assert (u["input"], u["output"], u["total"]) == (5828479, 25855, 5854334)
        # Claude fallback: no result event → last assistant message usage
        fallback = root / "fallback.jsonl"
        fallback.write_text(
            '{"type":"assistant","message":{"usage":{"input_tokens":1,"output_tokens":1}}}\n'
            '{"type":"assistant","message":{"usage":{"input_tokens":2,"cache_read_input_tokens":3,"output_tokens":4}}}\n',
            encoding="utf-8")
        assert fw._usage("claude", str(fallback))["total"] == 9
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_usage_null_when_absent():
    fw = _fw()
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-usage0-"))
    try:
        empty = root / "s.jsonl"
        empty.write_text('{"type":"system"}\n', encoding="utf-8")
        assert fw._usage("claude", str(empty)) == {"raw": None, "input": None, "output": None, "total": None}
        assert fw._usage("codex", str(root / "missing.jsonl"))["raw"] is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_kit_rev_recorded_when_kit_git_present():
    fw = _fw()
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-git-"))
    try:
        tools = root / "tools"
        tools.mkdir()
        (tools / "engine.py").write_text("x = 1\n", encoding="utf-8")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@x")
        for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-q", "-m", "init"]):
            subprocess.run(cmd, cwd=root, env=env, check=True, capture_output=True)
        rev, dirty = fw._kit_identity(str(tools))
        assert isinstance(rev, str) and len(rev) == 40 and dirty is False
        (tools / "engine.py").write_text("x = 2\n", encoding="utf-8")
        assert fw._kit_identity(str(tools)) == (rev, True)
        # dirt outside the engine dir does not count
        (tools / "engine.py").write_text("x = 1\n", encoding="utf-8")
        (root / "journal.md").write_text("noise\n", encoding="utf-8")
        assert fw._kit_identity(str(tools)) == (rev, False)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_kit_rev_null_without_git():
    fw = _fw()
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-nogit-"))
    try:
        assert fw._kit_identity(str(root)) == (None, None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_scope_parsed_and_null():
    fw = _fw()
    assert fw._read_scope("읽음: A, B\n본문\n끝까지 못 읽은 것: 없음\n") == {
        "declared": "읽음: A, B", "unread": "끝까지 못 읽은 것: 없음"}
    assert fw._read_scope("\n읽기 범위: 읽음=x; 안 읽음=y\n본문\n") == {
        "declared": "읽기 범위: 읽음=x; 안 읽음=y", "unread": None}
    assert fw._read_scope("본문만\nNOT FOUND 표기는 무시\n") is None
    assert fw._read_scope("") is None


def test_common_contract_has_source_line():
    fw = _fw()
    for runtime in ("claude", "codex"):
        prefix = fw._effective_prompt(runtime, "")
        assert "names the file path" in prefix
        assert "remaining unknowns" in prefix


def _run_prefixed(root, runtime, prompt, binary, prefixes, strict=False):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root))
    env[f"MOTTORI_FRESH_WORKER_{runtime.upper()}_BIN"] = str(binary)
    argv = [sys.executable, str(WORKER), "--runtime", runtime]
    if strict:
        argv.append("--strict-scope")
    for p in prefixes:
        argv += ["--write-prefix", p]
    argv.append(str(prompt))
    return subprocess.run(argv, cwd=root, env=env, text=True, capture_output=True)


_CODEX_WRITER = """
import json, os, pathlib, sys
args = sys.argv[1:]
sys.stdin.read()
root = pathlib.Path(os.getcwd())
for spec in os.environ.get("FAKE_WRITES", "").split(";"):
    if not spec:
        continue
    kind, path = spec.split("=", 1)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == "w":
        target.write_text("written\\n", encoding="utf-8")
    elif kind == "l":
        target.symlink_to(os.environ["FAKE_LINK_TARGET"])
    elif kind == "d":
        target.mkdir(parents=True, exist_ok=True)
    elif kind == "s":  # same size, mtime restored: only ctime can tell
        st = target.stat()
        old_text = target.read_text(encoding="utf-8")
        target.write_text("B" * len(old_text), encoding="utf-8")
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
    elif kind == "r":
        target.unlink()
out = pathlib.Path(args[args.index("--output-last-message") + 1])
out.write_text("읽음: 없음\\nDONE\\nUNREAD: 없음\\n", encoding="utf-8")
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":4}}))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def test_worktree_is_created_with_minimum_instance_state_and_cleaned():
    root, prompt, fake = _init_worktree_repo()
    try:
        checker = root / "fake checker"
        _script(checker, """
import json, os, pathlib, sys
args = sys.argv[1:]
sys.stdin.read()
root = pathlib.Path.cwd()
assert os.environ["MOTTORI_INSTANCE"] == str(root)
for name in ("memory-config.json", "instance-rules.md", "decisions.md", "rituals.local.md"):
    assert (root / "system" / name).read_text(encoding="utf-8") == f"instance {name}\\n"
assert [p.name for p in (root / "state").iterdir()] == [".gitkeep"]
assert not (root / "_private").exists()
out = pathlib.Path(args[args.index("--output-last-message") + 1])
out.write_text("DONE\\n", encoding="utf-8")
print(json.dumps({"type":"turn.completed"}))
""")
        r = _run_worktree(root, prompt, checker)
        assert r.returncode == 0, (r.stdout, r.stderr)
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["worktree"]["mode"] == "head"
        assert len(meta["worktree"]["base_rev"]) == 40
        assert meta["worktree"]["files"] == []
        assert not (run / "wt").exists()
        assert str(run / "wt") not in _git_ok(root, "worktree", "list", "--porcelain")
        assert (run / "patch.diff").read_bytes() == b""
        assert (run / "untracked.txt").read_text(encoding="utf-8") == ""
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_worktree_patch_extracts_modified_new_and_deleted_files():
    root, prompt, fake = _init_worktree_repo()
    try:
        r = _run_worktree(
            root, prompt, fake, extra_env={"FAKE_WRITES": "w=base.txt;w=new.txt;r=delete.txt"}
        )
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "patch: 3 files (+2/-2)" in r.stdout
        run = _run_dir(root, r.stdout)
        patch = (run / "patch.diff").read_text(encoding="utf-8")
        assert "diff --git a/base.txt b/base.txt" in patch
        assert "diff --git a/new.txt b/new.txt" in patch
        assert "diff --git a/delete.txt b/delete.txt" in patch
        assert (run / "untracked.txt").read_text(encoding="utf-8") == "new.txt\n"
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["worktree"]["files"] == ["base.txt", "delete.txt", "new.txt"]
        assert len(meta["worktree"]["patch_sha256"]) == 64
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_worktree_scope_uses_isolate_and_original_tree_is_unchanged():
    root, prompt, fake = _init_worktree_repo()
    try:
        original = (root / "base.txt").read_bytes()
        status_before = _git_ok(root, "status", "--porcelain=v1", "--untracked-files=no")
        r = _run_worktree(
            root, prompt, fake, prefixes=("allowed",), strict=True,
            extra_env={"FAKE_WRITES": "w=base.txt;w=allowed/ok.txt"},
        )
        assert r.returncode == 4, (r.stdout, r.stderr)
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["scope"]["prefixes"] == ["allowed"]
        assert {v["path"] for v in meta["scope"]["violations"]} == {"base.txt"}
        assert meta["worktree"]["files"] == ["allowed/ok.txt", "base.txt"]
        assert (root / "base.txt").read_bytes() == original
        assert _git_ok(root, "status", "--porcelain=v1", "--untracked-files=no") == status_before
        assert not (root / "allowed").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_worktree_dirty_mode_applies_original_tracked_diff():
    root, prompt, fake = _init_worktree_repo()
    try:
        (root / "base.txt").write_text("dirty source\n", encoding="utf-8")
        checker = root / "fake dirty checker"
        _script(checker, """
import json, pathlib, sys
args = sys.argv[1:]
sys.stdin.read()
root = pathlib.Path.cwd()
assert root.joinpath("base.txt").read_text(encoding="utf-8") == "dirty source\\n"
root.joinpath("worker.txt").write_text("worker\\n", encoding="utf-8")
out = pathlib.Path(args[args.index("--output-last-message") + 1])
out.write_text("DONE\\n", encoding="utf-8")
print(json.dumps({"type":"turn.completed"}))
""")
        r = _run_worktree(root, prompt, checker, mode="dirty")
        assert r.returncode == 0, (r.stdout, r.stderr)
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["worktree"]["mode"] == "dirty"
        assert meta["worktree"]["files"] == ["base.txt", "worker.txt"]
        assert (root / "base.txt").read_text(encoding="utf-8") == "dirty source\n"
        assert not (root / "worker.txt").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scope_violation_detected_outside_prefix_and_symlink_escape():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-scope-"))
    outside = Path(tempfile.mkdtemp(prefix="fresh-worker-scope-out-"))
    try:
        (root / "README.md").write_text("old\n", encoding="utf-8")
        (root / "allowed" / "cards").mkdir(parents=True)
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        (outside / "secret.txt").write_text("s\n", encoding="utf-8")
        os.environ["FAKE_WRITES"] = "w=allowed/cards/ok.md;w=README.md;w=.cache/junk;l=allowed/cards/escape"
        os.environ["FAKE_LINK_TARGET"] = str(outside / "secret.txt")
        try:
            r = _run_prefixed(root, "codex", prompt, fake, ["allowed/cards"], strict=True)
        finally:
            os.environ.pop("FAKE_WRITES", None)
            os.environ.pop("FAKE_LINK_TARGET", None)
        assert r.returncode == 4, (r.returncode, r.stderr)
        assert "status: scope_violation" in r.stdout
        assert "scope: scope_violation (changed" in r.stdout
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        assert meta["scope"]["prefixes"] == ["allowed/cards"]
        changed = set(meta["scope"]["changed"])
        assert {"allowed/cards/ok.md", "README.md", ".cache/junk", "allowed/cards/escape"} <= changed
        assert not any(c.startswith("_private/work/runs/") for c in changed), "run dir must be excluded"
        why = {v["path"]: v["why"] for v in meta["scope"]["violations"]}
        assert why["README.md"] == "outside write-prefix"
        assert why[".cache/junk"] == "outside write-prefix"
        assert why["allowed/cards/escape"] == "symlink under write-prefix escapes it"
        assert "allowed/cards/ok.md" not in why
        assert (root / "README.md").read_text(encoding="utf-8") == "written\n", "no rollback"
        assert meta["usage"]["total"] == 7 and meta["read_scope"]["declared"] == "읽음: 없음"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_scope_ok_within_prefix_and_unchecked_without_prefix():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-scope-ok-"))
    try:
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        os.environ["FAKE_WRITES"] = "w=out/a.md"
        try:
            r = _run_prefixed(root, "codex", prompt, fake, ["out"])
            assert r.returncode == 0, r.stderr
            assert "scope: ok (changed" in r.stdout
            meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
            assert meta["scope"]["status"] == "ok" and meta["scope"]["violations"] == []
            assert "out/a.md" in meta["scope"]["changed"]

            r2 = _run_prefixed(root, "codex", prompt, fake, [])
            assert r2.returncode == 0, r2.stderr
            meta2 = json.loads((_run_dir(root, r2.stdout) / "meta.json").read_text(encoding="utf-8"))
            assert meta2["scope"]["status"] == "unchecked" and "out/a.md" in meta2["scope"]["changed"]
            assert "scope: unchecked (changed" in r2.stdout
        finally:
            os.environ.pop("FAKE_WRITES", None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scope_violation_is_report_only_without_strict():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-scope-lenient-"))
    try:
        (root / "README.md").write_text("old\n", encoding="utf-8")
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        os.environ["FAKE_WRITES"] = "w=out/a.md;w=README.md"
        try:
            r = _run_prefixed(root, "codex", prompt, fake, ["out"])
        finally:
            os.environ.pop("FAKE_WRITES", None)
        assert r.returncode == 0, r.stderr
        assert "status: success" in r.stdout
        assert "scope: scope_violation (changed 3, violations 1)" in r.stdout  # out/, out/a.md, README.md
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        assert meta["status"] == "success" and meta["scope"]["status"] == "scope_violation"
        assert meta["scope"]["violations"] == [{"path": "README.md", "why": "outside write-prefix"}]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_scope_accepts_declaration_variants():
    fw = _fw()
    assert fw._read_scope("읽기 범위 선언: 읽음=A; 안 읽음=B\n본문\n")["declared"] == "읽기 범위 선언: 읽음=A; 안 읽음=B"
    assert fw._read_scope("읽음: A\n")["declared"] == "읽음: A"
    assert fw._read_scope("읽었음 A\n") is None


def test_write_prefix_boundaries_fail_closed():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-prefix-"))
    outside = Path(tempfile.mkdtemp(prefix="fresh-worker-prefix-out-"))
    try:
        prompt = root / "p.md"
        prompt.write_text("x\n", encoding="utf-8")
        fake = root / "fake"
        _script(fake, "print('unused')\n")
        r = _run_prefixed(root, "codex", prompt, fake, [str(outside)])
        assert r.returncode == 2 and "write-prefix" in r.stderr
        r = _run_prefixed(root, "codex", prompt, fake, ["."])
        assert r.returncode == 2 and "루트 전체" in r.stderr
        real = root / "real"
        real.mkdir()
        (root / "linkdir").symlink_to(real, target_is_directory=True)
        r = _run_prefixed(root, "codex", prompt, fake, ["linkdir/sub"])
        assert r.returncode == 2 and "symlink" in r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_scope_hardlink_alias_outside_workspace_is_violation():  # review R8
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-r8-"))
    outside = Path(tempfile.mkdtemp(prefix="fresh-worker-r8-out-"))
    try:
        (root / "allowed").mkdir()
        secret = outside / "secret.txt"
        secret.write_text("original\n", encoding="utf-8")
        os.link(secret, root / "allowed" / "alias.txt")  # exists BEFORE the run
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        with _fake_env(FAKE_WRITES="w=allowed/alias.txt"):
            r = _run_prefixed(root, "codex", prompt, fake, ["allowed"], strict=True)
        assert r.returncode == 4, (r.returncode, r.stderr, r.stdout)
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        why = {v["path"]: v["why"] for v in meta["scope"]["violations"]}
        assert why.get("allowed/alias.txt", "").startswith("hardlink under write-prefix"), why
        assert secret.read_text(encoding="utf-8") == "written\n", "the alias write changed the outside file"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_missing_nested_prefix_is_created_before_baseline():  # review R9
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-r9-"))
    try:
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        with _fake_env(FAKE_WRITES="w=out/sub/a.txt;d=out/sub/empty"):
            r = _run_prefixed(root, "codex", prompt, fake, ["out/sub"], strict=True)
        assert r.returncode == 0, (r.returncode, r.stdout)
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        assert meta["scope"]["status"] == "ok" and meta["scope"]["violations"] == []
        assert "out/sub/a.txt" in meta["scope"]["changed"] and "out/sub/empty" in meta["scope"]["changed"]
        assert "out" not in meta["scope"]["changed"], "prefix creation belongs to the dispatcher"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_prefix_case_is_not_rewritten_on_case_sensitive_fs():  # review R10 (simulated)
    fw = _fw()
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-r10-"))
    try:
        (root / "out").mkdir()
        real_listdir, real_exists, real_samefile = fw.os.listdir, fw.os.path.exists, fw.os.path.samefile
        old_root = fw.ROOT
        fw.ROOT = str(root)
        # simulate a case-sensitive volume: OUT does not resolve to out
        fw.os.path.exists = lambda p: real_exists(p) and not p.endswith("/OUT")
        try:
            assert fw._normalize_prefix("OUT/new") == "OUT/new"
            assert fw._normalize_prefix("out/new") == "out/new"
        finally:
            fw.os.path.exists = real_exists
            fw.ROOT = old_root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_usage_string_numbers_stay_raw_but_normalize_to_null():  # review R7
    fw = _fw()
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-usage-str-"))
    try:
        s = root / "s.jsonl"
        s.write_text('{"type":"turn.completed","usage":{"input_tokens":"12","output_tokens":3}}\n', encoding="utf-8")
        u = fw._usage("codex", str(s))
        assert u["raw"] == {"input_tokens": "12", "output_tokens": 3}
        assert u["input"] is None and u["output"] == 3 and u["total"] is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_engine_sha256_ignores_sync_stamp_lines():  # review R5
    fw = _fw()
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-stamp-"))
    try:
        raw = (HERE / "fresh_worker.py").read_text(encoding="utf-8")
        # start from an unstamped source whether this copy is the kit or a stamped instance copy
        src = "\n".join(line for line in raw.split("\n")
                        if not line.startswith(fw.STAMP_PREFIXES)) + "\n"
        (root / "memlib.py").write_text("x = 1\n", encoding="utf-8")
        (root / "fresh_worker.py").write_text(src, encoding="utf-8")
        plain = fw._engine_sha256(str(root))
        stamped = src.replace("ENGINE_FILES = (", 'KIT_REV_EMBEDDED = "a" * 40\nKIT_SYNC_DIRTY = True\n'
                              'KIT_SYNC_ENGINE_SHA256 = "b" * 64\nKIT_SYNC_SOURCE_SHA256 = "c" * 64\nENGINE_FILES = (', 1)
        assert stamped != src
        (root / "fresh_worker.py").write_text(stamped, encoding="utf-8")
        assert fw._engine_sha256(str(root)) == plain, "stamp lines must not change the engine identity"
        (root / "fresh_worker.py").write_text(stamped + "\n# real change\n", encoding="utf-8")
        assert fw._engine_sha256(str(root)) != plain
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _fake_env(**kv):
    class _Ctx:
        def __enter__(self):
            for k, v in kv.items():
                os.environ[k] = v
        def __exit__(self, *a):
            for k in kv:
                os.environ.pop(k, None)
    return _Ctx()


def test_scope_preexisting_symlink_under_prefix_is_violation():  # review R1
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-r1-"))
    outside = Path(tempfile.mkdtemp(prefix="fresh-worker-r1-out-"))
    try:
        (root / "allowed").mkdir()
        (root / "allowed" / "escape").symlink_to(outside, target_is_directory=True)  # exists BEFORE the run
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        with _fake_env(FAKE_WRITES="w=allowed/escape/written.txt"):
            r = _run_prefixed(root, "codex", prompt, fake, ["allowed"], strict=True)
        assert r.returncode == 4, (r.returncode, r.stderr)
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        why = {v["path"]: v["why"] for v in meta["scope"]["violations"]}
        assert why.get("allowed/escape") == "symlink under write-prefix escapes it", why
        assert (outside / "written.txt").exists(), "the write itself is outside the snapshot"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_scope_detects_same_size_change_with_restored_mtime_and_empty_dirs():  # review R2
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-r2-"))
    try:
        victim = root / "victim.txt"
        victim.write_text("AAAA\n", encoding="utf-8")
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        import time as _t
        _t.sleep(0.01)
        with _fake_env(FAKE_WRITES="s=victim.txt;w=out/a.md;w=newdir/.keep"):
            r = _run_prefixed(root, "codex", prompt, fake, ["out"], strict=True)
        assert r.returncode == 4, (r.returncode, r.stderr)
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        paths = {v["path"] for v in meta["scope"]["violations"]}
        assert "victim.txt" in paths, meta["scope"]
        assert "newdir" in paths and "newdir/.keep" in paths, meta["scope"]
        assert victim.read_text(encoding="utf-8") == "BBBBB", "content changed with same size"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scope_violation_outranks_runtime_failure():  # review R3
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-r3-"))
    try:
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        with _fake_env(FAKE_WRITES="w=outside.txt", FAKE_EXIT="7"):
            r = _run_prefixed(root, "codex", prompt, fake, ["out"], strict=True)
        assert r.returncode == 4, (r.returncode, r.stderr)
        assert "status: scope_violation" in r.stdout and "process_exit: 7" in r.stdout
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        assert meta["process_exit"] == 7 and meta["wrapper_exit"] == 4 and meta["status"] == "scope_violation"
        # without strict the runtime failure is what the status reports, scope stays informative
        with _fake_env(FAKE_WRITES="w=outside2.txt", FAKE_EXIT="7"):
            r2 = _run_prefixed(root, "codex", prompt, fake, ["out"])
        assert r2.returncode == 7 and "status: failed" in r2.stdout and "scope: scope_violation" in r2.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_prefix_spelling_follows_disk_on_case_insensitive_fs():
    root = Path(tempfile.mkdtemp(prefix="fresh-worker-case-"))
    try:
        (root / "out").mkdir()
        if not (root / "OUT").exists():
            print("  note: case-sensitive filesystem, nothing to normalize (skipped body)")
            return
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        with _fake_env(FAKE_WRITES="w=out/ok.txt"):
            r = _run_prefixed(root, "codex", prompt, fake, ["OUT"], strict=True)
        assert r.returncode == 0, (r.returncode, r.stdout)
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text(encoding="utf-8"))
        assert meta["scope"]["prefixes"] == ["out"] and meta["scope"]["status"] == "ok"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_scope_strips_bom_and_uses_first_nonempty_line():  # review R6
    fw = _fw()
    assert fw._read_scope("\ufeff읽음: A\n본문\n")["declared"] == "읽음: A"
    assert fw._read_scope("\n  읽음: A  \n본문\n")["declared"] == "읽음: A"
    assert fw._read_scope("본문\n읽음: 늦음\n") is None


def test_git_timeout_yields_null_identity():  # review R7
    fw = _fw()
    real = fw.subprocess.run
    def boom(*a, **k):
        raise fw.subprocess.TimeoutExpired(cmd="git", timeout=10)
    fw.subprocess.run = boom
    try:
        assert fw._kit_identity(str(HERE)) == (None, None)
        ident = fw._engine_identity(str(HERE), str(HERE.parent))
        assert ident["repo_rev"] is None and ident["kit_dirty"] is None
        assert len(ident["engine_sha256"]) == 64
    finally:
        fw.subprocess.run = real


def test_engine_identity_prefers_embedded_kit_rev():  # review R5
    fw = _fw()
    ident = fw._engine_identity(str(HERE), str(HERE.parent))
    assert set(ident) == {"kit_rev", "kit_rev_source", "kit_dirty", "kit_sync", "repo_rev", "engine_sha256", "agents_sha256"}
    assert set(ident["kit_sync"]) == {"dirty", "engine_sha256", "source_sha256", "matches_copy"}
    assert len(fw._source_manifest_sha256(str(HERE))) == 64
    assert len(ident["engine_sha256"]) == 64
    assert ident["kit_rev_source"] in ("embedded", "git", None)
    old = fw.KIT_REV_EMBEDDED
    try:
        fw.KIT_REV_EMBEDDED = "f" * 40
        stamped = fw._engine_identity(str(HERE), str(HERE.parent))
        assert stamped["kit_rev"] == "f" * 40 and stamped["kit_rev_source"] == "embedded"
        assert stamped["repo_rev"] == ident["repo_rev"], "repo HEAD of the running copy is kept separately"
    finally:
        fw.KIT_REV_EMBEDDED = old


TESTS = [
    test_claude_trace_cap_and_capability,
    test_codex_prompt_is_data_not_shell_and_workspace_capability,
    test_prompt_boundaries_fail_closed,
    test_missing_result_is_not_success_and_no_runtime_fallback,
    test_parity_requires_exact_import,
    test_meta_v2_fields_present_end_to_end,
    test_harness_hash_stable_when_prompt_changes,
    test_harness_hash_changes_when_capability_changes,
    test_usage_parsed_claude_and_codex,
    test_usage_null_when_absent,
    test_kit_rev_recorded_when_kit_git_present,
    test_kit_rev_null_without_git,
    test_read_scope_parsed_and_null,
    test_common_contract_has_source_line,
    test_scope_violation_detected_outside_prefix_and_symlink_escape,
    test_scope_ok_within_prefix_and_unchecked_without_prefix,
    test_scope_violation_is_report_only_without_strict,
    test_read_scope_accepts_declaration_variants,
    test_write_prefix_boundaries_fail_closed,
    test_scope_preexisting_symlink_under_prefix_is_violation,
    test_scope_detects_same_size_change_with_restored_mtime_and_empty_dirs,
    test_scope_violation_outranks_runtime_failure,
    test_prefix_spelling_follows_disk_on_case_insensitive_fs,
    test_read_scope_strips_bom_and_uses_first_nonempty_line,
    test_git_timeout_yields_null_identity,
    test_engine_identity_prefers_embedded_kit_rev,
    test_scope_hardlink_alias_outside_workspace_is_violation,
    test_missing_nested_prefix_is_created_before_baseline,
    test_prefix_case_is_not_rewritten_on_case_sensitive_fs,
    test_usage_string_numbers_stay_raw_but_normalize_to_null,
    test_engine_sha256_ignores_sync_stamp_lines,
    test_worktree_is_created_with_minimum_instance_state_and_cleaned,
    test_worktree_patch_extracts_modified_new_and_deleted_files,
    test_worktree_scope_uses_isolate_and_original_tree_is_unchanged,
    test_worktree_dirty_mode_applies_original_tracked_diff,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
