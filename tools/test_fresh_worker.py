#!/usr/bin/env python3
"""Fixture tests for the bounded fresh-worker interface."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

from testlib import run_test


HERE = Path(__file__).resolve().parent
WORKER = HERE / "fresh_worker.py"


def _script(path, body):
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _fixture_env(root):
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("CLAUDE_", "ANTHROPIC_", "OPENAI_", "CODEX_"))}
    env.update(HOME=str(root / ".fixture-home"), MOTTORI_INSTANCE=str(root),
               CODEX_HOME=str(root / ".fixture-home/.codex"))
    return env


def _run(root, runtime, prompt, binary):
    env = _fixture_env(root)
    env[f"MOTTORI_FRESH_WORKER_{runtime.upper()}_BIN"] = str(binary)
    return subprocess.run(
        [sys.executable, str(WORKER), "--runtime", runtime, str(prompt)],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
    )


def _git_ok(root, *args):
    # An outer Git hook's index path must not select the fixture worktree's index.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True, env=env,
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
    (root / "system" / "memory-config.json").write_text(json.dumps({
        "schema_version": 4,
        "journal_visibility": {"legacy_cutoff": None, "legacy_public_tracks": []},
    }), encoding="utf-8")
    for name in ("instance-rules.md", "decisions.md", "rituals.local.md"):
        (root / "system" / name).write_text(f"instance {name}\n", encoding="utf-8")
    prompt = root / "prompt.md"
    prompt.write_text("work in isolation\n", encoding="utf-8")
    fake = root / "fake codex"
    _script(fake, _CODEX_WRITER)
    return root, prompt, fake


def _run_worktree(root, prompt, binary, mode="head", prefixes=(), strict=False, extra_env=None, materials=()):
    env = dict(_fixture_env(root),
               MOTTORI_FRESH_WORKER_CODEX_BIN=str(binary), **(extra_env or {}))
    argv = [sys.executable, str(WORKER), "--runtime", "codex", f"--worktree={mode}"]
    if strict:
        argv.append("--strict-scope")
    for prefix in prefixes:
        argv += ["--write-prefix", prefix]
    for material in materials:
        argv += ["--read-material", material]
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
        assert "batch" not in meta, "legacy single-run meta must not gain batch bytes"
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
        assert "RESULT_JSON:" in prefix


def test_result_contract_is_structured_and_free_prose_is_inconclusive():
    fw = _fw()
    valid = fw._result_contract(
        'done\nRESULT_JSON: {"verdict":"PASS","summary":"ok","evidence":["x.py:1"],'
        '"unknowns":[]}\n'
    )
    assert valid == {
        "schema_version": 1,
        "valid": True,
        "verdict": "PASS",
        "summary": "ok",
        "evidence": ["x.py:1"],
        "unknowns": [],
        "error": None,
    }
    for malformed in (
        "판정: PASS\n증거: x.py:1\n",
        'RESULT_JSON: {"verdict":"MAYBE","summary":"ok","evidence":["x.py:1"],'
        '"unknowns":[]}\n',
        'RESULT_JSON: {"verdict":"PASS","summary":"ok","evidence":[],"unknowns":[]}\n',
        'RESULT_JSON: {"verdict":"PASS","summary":"ok","evidence":["x.py:1"],'
        '"unknowns":[]}\ntrailing prose\n',
    ):
        contract = fw._result_contract(malformed)
        assert contract["valid"] is False and contract["verdict"] == "INCONCLUSIVE"


def test_fresh_worker_receipt_limit_matches_contract_boundary():
    fw = _fw()
    assert fw.RECEIPT_MAX_BYTES == 4096
    meta = {
        "run": "_private/work/runs/fixture",
        "runtime": "codex",
        "capability": "workspace-write",
        "status": "success",
        "process_exit": 0,
        "wrapper_exit": 0,
        "prompt_sha256": "a" * 64,
        "stream_sha256": "b" * 64,
        "result_sha256": "c" * 64,
        "result_bytes": 20000,
        "egress": {"private_ref_count": 0},
        "scope": {"status": "ok", "changed_count": 0, "violation_count": 0},
    }
    assert len(fw._receipt(meta, "x" * 20000).encode("utf-8")) <= 4096


def _run_prefixed(root, runtime, prompt, binary, prefixes, strict=False):
    env = _fixture_env(root)
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
config = json.loads((root / "system" / "memory-config.json").read_text(encoding="utf-8"))
assert config["schema_version"] == 4
assert config["journal_visibility"] == {"legacy_cutoff": None, "legacy_public_tracks": []}
for name in ("instance-rules.md", "decisions.md", "rituals.local.md"):
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
        for path, digest in meta["worktree"]["instance_sha256"].items():
            assert digest == hashlib.sha256((root / path).read_bytes()).hexdigest()
        assert meta["worktree"]["files"] == []
        assert not (run / "wt").exists()
        assert str(run / "wt") not in _git_ok(root, "worktree", "list", "--porcelain")
        assert (run / "patch.diff").read_bytes() == b""
        assert (run / "untracked.txt").read_text(encoding="utf-8") == ""
    finally:
        shutil.rmtree(root, ignore_errors=True)



def test_worktree_pins_observed_revision_even_when_head_moves():
    root, prompt, fake = _init_worktree_repo()
    fw = _fw()
    old_root, git_require = fw.ROOT, fw._git_require
    run = root / "run"
    run.mkdir()
    base = _git_ok(root, "rev-parse", "HEAD").strip()
    before = (root / "base.txt").read_text()
    def racing_git(args, cwd, input_bytes=None):
        if args[:2] == ["worktree", "add"]:
            (root / "base.txt").write_text("new head\n")
            _git_ok(root, "add", "base.txt")
            _git_ok(root, "commit", "-qm", "concurrent change")
        return git_require(args, cwd, input_bytes)
    try:
        fw.ROOT, fw._git_require = str(root), racing_git
        worktree, meta, copied = fw._prepare_worktree(str(run), "head")
        assert meta["base_rev"] == base
        assert _git_ok(Path(worktree), "rev-parse", "HEAD").strip() == base
        assert (Path(worktree) / "base.txt").read_text() == before
        assert _git_ok(root, "rev-parse", "HEAD").strip() != base
        fw._remove_worktree(worktree)
    finally:
        fw.ROOT, fw._git_require = old_root, git_require
        shutil.rmtree(root, ignore_errors=True)


def test_worktree_ignores_git_env_pinned_by_an_outer_hook():
    # A commit hook exports GIT_INDEX_FILE (relative). Inherited, it made `worktree add` open the outer
    # index and fail. Worker Git commands must use only the current worktree.
    root, prompt, fake = _init_worktree_repo()
    try:
        r = _run_worktree(root, prompt, fake, extra_env={"GIT_INDEX_FILE": ".git/index"})
        assert r.returncode == 0, (r.stdout, r.stderr)
        run = _run_dir(root, r.stdout)
        assert not (run / "wt").exists()
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


def test_worktree_ignored_output_survives_cleanup_with_hash_and_patch():
    root, prompt, fake = _init_worktree_repo()
    try:
        with (root / ".gitignore").open("a") as f:
            f.write("/research/\n")
        material = "research/synthetic-output/input.json"
        (root / material).parent.mkdir(parents=True)
        (root / material).write_text('[604, 770, 305]\n')
        writer = root / "ignored writer"
        _script(writer, r"""
import json, pathlib, sys
sys.stdin.read()
values = json.loads(pathlib.Path('research/synthetic-output/input.json').read_text())
pathlib.Path('research/synthetic-output/totals.json').write_text(json.dumps({'count': len(values), 'total': sum(values)}) + '\n')
pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text('DONE\n')
print(json.dumps({'type': 'turn.completed'}))
""")
        r = _run_worktree(root, prompt, writer, mode="dirty", prefixes=("research/synthetic-output",),
                          strict=True, materials=(material,))
        assert r.returncode == 0, (r.stdout, r.stderr)
        run = _run_dir(root, r.stdout)
        rel = "research/synthetic-output/totals.json"
        expected = b'{"count": 3, "total": 1679}\n'
        assert (run / "untracked" / rel).read_bytes() == expected
        assert not (run / "wt").exists()
        assert not (root / rel).exists()
        meta = json.loads((run / "meta.json").read_text())
        assert meta["worktree"]["capture_status"] == "complete"
        assert "preserved_path" not in meta["worktree"]
        assert meta["worktree"]["ignored_captured"] == [rel]
        assert meta["worktree"]["output_sha256"] == {rel: hashlib.sha256(expected).hexdigest()}
        assert meta["worktree"]["material_integrity"] is True
        assert material not in meta["worktree"]["files"]
        assert not (run / "untracked" / material).exists()
        assert (run / "untracked.txt").read_text() == rel + "\n"
        patch = (run / "patch.diff").read_bytes()
        assert rel.encode() in patch and b'+{"count": 3, "total": 1679}' in patch
        # The existing patch consumer can restore the new output without the removed worktree.
        replay = root / "replay"
        replay.mkdir()
        _git_ok(replay, "init", "-q")
        (replay / ".gitignore").write_bytes(_git_ok(root, "show", "HEAD:.gitignore").encode() + b"\n")
        subprocess.run(["git", "apply", "--binary", str(run / "patch.diff")], cwd=replay, check=True,
                       capture_output=True)
        assert (replay / rel).read_bytes() == expected
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_worktree_unsafe_ignored_outputs_are_not_exported_and_prevent_cleanup():
    root, prompt, fake = _init_worktree_repo()
    outside = Path(tempfile.mkdtemp(prefix="fresh-worker-artifact-outside-"))
    try:
        with (root / ".gitignore").open("a") as f:
            f.write("/research/\n")
        (outside / "source.txt").write_text("synthetic external source\n")
        writer = root / "unsafe ignored writer"
        _script(writer, r"""
import json, os, pathlib, sys
sys.stdin.read()
base = pathlib.Path('research/output')
for rel in ['ok.json', '.env', 'credentials.json', 'cache/a.bin', '_private/a.txt', 'node_modules/a.js']:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('synthetic\n')
pathlib.Path('research/outside').mkdir()
pathlib.Path('research/outside/other.json').write_text('outside prefix\n')
(base / 'link.txt').symlink_to(os.environ['FAKE_LINK_TARGET'])
os.link(os.environ['FAKE_LINK_TARGET'], base / 'hardlink.txt')
pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1]).write_text('DONE\n')
print(json.dumps({'type': 'turn.completed'}))
""")
        r = _run_worktree(root, prompt, writer, mode="dirty", prefixes=("research/output",), strict=True,
                          extra_env={"FAKE_LINK_TARGET": str(outside / "source.txt")})
        assert r.returncode == 5, (r.stdout, r.stderr)
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text())
        assert meta["status"] == "artifact-capture-incomplete"
        assert meta["scope"]["status"] == "scope_violation"
        assert meta["worktree"]["ignored_captured"] == ["research/output/ok.json"]
        skipped = {row["path"] for row in meta["worktree"]["capture_skipped"]}
        assert skipped == {"research/output/" + name for name in
                           ('.env', 'credentials.json', 'cache/a.bin', '_private/a.txt', 'node_modules/a.js',
                            'link.txt', 'hardlink.txt')}
        exported = sorted(str(p.relative_to(run / "untracked")) for p in (run / "untracked").rglob('*') if p.is_file())
        assert exported == ["research/output/ok.json"]
        patch = (run / "patch.diff").read_text()
        assert all(path not in patch for path in skipped)
        assert "research/outside/other.json" not in patch
        assert (run / "wt/research/output/credentials.json").read_text() == "synthetic\n"
        assert Path(meta["worktree"]["preserved_path"]).is_dir()
        assert str(run / "wt") in _git_ok(root, "worktree", "list", "--porcelain")
        assert (outside / "source.txt").read_text() == "synthetic external source\n"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_worktree_capture_io_failure_preserves_recoverable_output():
    global WORKER
    root, prompt, fake = _init_worktree_repo()
    original_worker = WORKER
    try:
        with (root / ".gitignore").open("a") as f:
            f.write("/research/\n")
        driver = root / "capture-failure.py"
        _script(driver, "import sys\nsys.path.insert(0, " + repr(str(WORKER.parent)) + ")\n" + r"""
import fresh_worker as fw
write = fw._private_write
def fail_copy(path, data):
    if '/untracked/research/output/' in path:
        raise OSError('synthetic capture failure')
    return write(path, data)
fw._private_write = fail_copy
sys.exit(fw.main(sys.argv[1:]))
""")
        WORKER = driver
        r = _run_worktree(root, prompt, fake, mode="dirty", prefixes=("research/output",), strict=True,
                          extra_env={"FAKE_WRITES": "w=research/output/totals.json"})
        assert r.returncode == 5, (r.stdout, r.stderr)
        run = _run_dir(root, r.stdout)
        meta = json.loads((run / "meta.json").read_text())
        assert meta["status"] == "artifact-capture-failed"
        assert meta["worktree"]["capture_error"] == "OSError: synthetic capture failure"
        assert (run / "wt/research/output/totals.json").read_text() == "written\n"
        assert Path(meta["worktree"]["preserved_path"]).is_dir()
        assert str(run / "wt") in _git_ok(root, "worktree", "list", "--porcelain")
    finally:
        WORKER = original_worker
        shutil.rmtree(root, ignore_errors=True)


def test_worktree_incomplete_ignored_listing_preserves_output():
    global WORKER
    original_worker = WORKER
    for listing in [b'research/output/totals.json', b'', b'outside-prefix.json\0']:
        root, prompt, fake = _init_worktree_repo()
        try:
            with (root / ".gitignore").open("a") as f:
                f.write("/research/\n")
            driver = root / "listing-failure.py"
            _script(driver, "import sys, subprocess\nsys.path.insert(0, " + repr(str(original_worker.parent)) + ")\n"
                    + "listing = " + repr(listing) + "\n" + r"""
import fresh_worker as fw
process = fw._git_process
def broken_listing(args, *a, **kw):
    if args[0] == 'check-ignore':
        return subprocess.CompletedProcess(args, 0, stdout=listing, stderr=b'')
    return process(args, *a, **kw)
fw._git_process = broken_listing
sys.exit(fw.main(sys.argv[1:]))
""")
            WORKER = driver
            r = _run_worktree(root, prompt, fake, mode="dirty", prefixes=("research/output",), strict=True,
                              extra_env={"FAKE_WRITES": "w=research/output/totals.json"})
            assert r.returncode == 5, (listing, r.stdout, r.stderr)
            run = _run_dir(root, r.stdout)
            meta = json.loads((run / "meta.json").read_text())
            assert meta["status"] == "artifact-capture-failed"
            expected = "unexpected path" if listing.endswith(b"\0") else "incomplete listing"
            assert expected in meta["worktree"]["capture_error"]
            assert (run / "wt/research/output/totals.json").read_text() == "written\n"
            assert not (run / "untracked").exists()
        finally:
            WORKER = original_worker
            shutil.rmtree(root, ignore_errors=True)


def test_worktree_final_metadata_failure_keeps_durable_artifacts():
    global WORKER
    root, prompt, fake = _init_worktree_repo()
    original_worker = WORKER
    try:
        with (root / ".gitignore").open("a") as f:
            f.write("/research/\n")
        driver = root / "metadata-failure.py"
        _script(driver, "import sys\nsys.path.insert(0, " + repr(str(WORKER.parent)) + ")\n" + r"""
import fresh_worker as fw
write_meta = fw._write_meta
def fail_final_meta(path, meta):
    if meta['status'] != 'running':
        raise OSError('synthetic final metadata failure')
    return write_meta(path, meta)
fw._write_meta = fail_final_meta
sys.exit(fw.main(sys.argv[1:]))
""")
        WORKER = driver
        r = _run_worktree(root, prompt, fake, mode="dirty", prefixes=("research/output",), strict=True,
                          extra_env={"FAKE_WRITES": "w=research/output/totals.json"})
        assert r.returncode != 0 and 'synthetic final metadata failure' in r.stderr
        assert 'status: success' not in r.stdout
        run, = (root / '_private/work/runs').iterdir()
        assert (run / 'untracked/research/output/totals.json').read_text() == 'written\n'
        assert 'research/output/totals.json' in (run / 'patch.diff').read_text()
        assert json.loads((run / 'meta.json').read_text())['status'] == 'running'
        assert not (run / 'wt').exists()
    finally:
        WORKER = original_worker
        shutil.rmtree(root, ignore_errors=True)


def test_sigterm_during_capture_preserves_owned_worktree_and_output():
    global WORKER
    root, prompt, fake = _init_worktree_repo()
    original_worker = WORKER
    try:
        with (root / ".gitignore").open("a") as f:
            f.write("/research/\n")
        driver = root / "capture-term.py"
        _script(driver, "import os, signal, sys\nsys.path.insert(0, " + repr(str(WORKER.parent)) + ")\n" + r"""
from pathlib import Path
import fresh_worker as fw
def interrupt_capture(worktree, *args, **kwargs):
    assert (Path(worktree) / 'research/output/totals.json').read_text() == 'written\n'
    os.kill(os.getpid(), signal.SIGTERM)
    raise AssertionError('SIGTERM did not interrupt capture')
fw._capture_worktree = interrupt_capture
sys.exit(fw.main(sys.argv[1:]))
""")
        WORKER = driver
        r = _run_worktree(root, prompt, fake, mode="dirty", prefixes=("research/output",), strict=True,
                          extra_env={"FAKE_WRITES": "w=research/output/totals.json"})
        assert r.returncode == 143, (r.returncode, r.stdout, r.stderr)
        assert 'status: success' not in r.stdout
        run, = (root / '_private/work/runs').iterdir()
        assert (run / 'wt/research/output/totals.json').is_file(), 'capture interruption deleted output'
        assert (run / 'wt/research/output/totals.json').read_text() == 'written\n'
        meta = json.loads((run / 'meta.json').read_text())
        assert meta['status'] != 'success'
        assert meta['worktree']['capture_status'] == 'in_progress'
        assert Path(meta['worktree']['preserved_path']).resolve() == (run / 'wt').resolve()
        assert str(run / 'wt') in _git_ok(root, 'worktree', 'list', '--porcelain')
    finally:
        WORKER = original_worker
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
        assert why.get("allowed/cards/escape") == "symlink under write-prefix escapes it"
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


def test_strict_scope_detects_git_and_immediate_parent_writes():
    container = Path(tempfile.mkdtemp(prefix="fresh-worker-protected-"))
    root = container / "workspace"
    root.mkdir()
    parent_name = f"worker-parent-{os.getpid()}.txt"
    parent_path = root.parent / parent_name
    try:
        _git_ok(root, "init", "-q")
        (root / "allowed").mkdir()
        prompt = root / "p.md"
        prompt.write_text("write\n", encoding="utf-8")
        fake = root / "fake codex"
        _script(fake, _CODEX_WRITER)
        os.environ["FAKE_WRITES"] = f"w=.git/worker-attack;w=../{parent_name}"
        try:
            result = _run_prefixed(root, "codex", prompt, fake, ["allowed"], strict=True)
        finally:
            os.environ.pop("FAKE_WRITES", None)
        assert result.returncode == 4, (result.stdout, result.stderr)
        meta = json.loads((_run_dir(root, result.stdout) / "meta.json").read_text(encoding="utf-8"))
        violations = {row["path"] for row in meta["scope"]["violations"]}
        assert ".git/worker-attack" in violations
        assert f"../{parent_name}" in violations
    finally:
        parent_path.unlink(missing_ok=True)
        shutil.rmtree(container, ignore_errors=True)


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


def test_scope_hardlink_alias_outside_workspace_is_violation():
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


def test_missing_nested_prefix_is_created_before_baseline():
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


def test_prefix_case_is_not_rewritten_on_case_sensitive_fs():
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


def test_usage_string_numbers_stay_raw_but_normalize_to_null():
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


def test_engine_sha256_ignores_sync_stamp_lines():
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


def test_scope_preexisting_symlink_under_prefix_is_violation():
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


def test_scope_detects_same_size_change_with_restored_mtime_and_empty_dirs():
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


def test_scope_violation_outranks_runtime_failure():
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
        # Without strict mode, the runtime failure stays primary while the scope report remains recorded.
        with _fake_env(FAKE_WRITES="w=outside2.txt", FAKE_EXIT="7"):
            r2 = _run_prefixed(root, "codex", prompt, fake, ["out"])
        assert r2.returncode == 7 and "status: failed" in r2.stdout
        meta2 = json.loads((_run_dir(root, r2.stdout) / "meta.json").read_text(encoding="utf-8"))
        assert meta2["scope"]["status"] == "scope_violation"
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


def test_read_scope_strips_bom_and_finds_first_marker():
    fw = _fw()
    assert fw._read_scope("\ufeff읽음: A\n본문\n")["declared"] == "읽음: A"
    assert fw._read_scope("\n  읽음: A  \n본문\n")["declared"] == "읽음: A"
    assert fw._read_scope("본문\n읽음: 늦음\n")["declared"] == "읽음: 늦음"


def test_git_timeout_yields_null_identity():
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


def test_engine_identity_prefers_embedded_kit_rev():
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


def _allow_cycle_materials(root):
    path = root / "system/memory-config.json"
    config = json.loads(path.read_text())
    config["egress"] = {"model_send": {"deny_prefixes": ["_private/"], "allow_prefixes": ["_private/work/papers/"]}}
    path.write_text(json.dumps(config))


def test_read_materials_actual_isolate_reproduces_missing_then_delivers_all_inputs():
    root, prompt, _ = _init_worktree_repo()
    try:
        _allow_cycle_materials(root)
        base = "_private/work/papers/2026-10-08-kit/"
        data = {base + path: text for path, text in {
            "PROPOSALS.md": "proposals source", "cards/card.md": "card source",
            "apply/inputs/experiments.md": "experiments source", "apply/item.patch": "patch source",
            "apply/item.tests.txt": "tests source", "apply/item.spec.json": "spec source",
            "apply/attempts/old/impl-item.result.md": "original failed answer",
            "apply/attempts/old/review-item.result.md": "original independent review",
        }.items()}
        for path, body in data.items():
            dest = root / path; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(body)
        prompt.write_text("Read the supplied materials.\n")
        checker = root / "material checker"
        _script(checker, """
import json, pathlib, sys
args = sys.argv[1:]; sys.stdin.read()
expected = """ + repr(data) + """
root = pathlib.Path.cwd()
assert '/wt' in str(root), root
for name, body in expected.items():
    assert (root / name).read_text() == body, name
    assert not (root / name).is_symlink(), name
out = pathlib.Path(args[args.index('--output-last-message') + 1])
out.write_text('RESULT_JSON: {"verdict":"PASS","summary":"all materials read inside isolate","evidence":["material fixture"],"unknowns":[]}')
print(json.dumps({'type':'turn.completed'}))
""")
        missing = _run_worktree(root, prompt, checker)
        assert missing.returncode != 0, "the former missing-input failure was not reproduced"
        missing_run = _run_dir(root, missing.stdout)
        assert "FileNotFoundError" in (missing_run / "stderr.log").read_text()
        present = _run_worktree(root, prompt, checker, materials=list(data))
        assert present.returncode == 0, present.stdout + present.stderr
        run = _run_dir(root, present.stdout)
        meta = json.loads((run / "meta.json").read_text())["worktree"]
        assert meta["material_integrity"] is True
        assert meta["material_sha256"] == {path: hashlib.sha256(body.encode()).hexdigest() for path, body in data.items()}
        assert meta["files"] == [] and (run / "patch.diff").read_bytes() == b""
        assert not (run / "wt").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_material_rejects_denied_directory_symlink_and_source_shadow():
    root, prompt, fake = _init_worktree_repo()
    try:
        _allow_cycle_materials(root)
        private = root / "_private"; private.mkdir()
        (private / "secret.md").write_text("not approved")
        allowed = private / "work/papers/cycle"; allowed.mkdir(parents=True)
        (allowed / "allowed.md").write_text("approved")
        (allowed / "link.md").symlink_to(allowed / "allowed.md")
        for target in ("_private/secret.md", "_private/work/papers/cycle", "_private/work/papers/cycle/link.md", "../outside.md", "base.txt"):
            r = _run_worktree(root, prompt, fake, materials=[target])
            assert r.returncode == 2, (target, r.stdout, r.stderr)
        assert (root / "base.txt").read_text() == "base\n"
        assert not list((root / "_private/work/runs").glob("*/wt"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_material_mutation_overrides_runtime_pass_and_preserves_original():
    root, prompt, _ = _init_worktree_repo()
    try:
        _allow_cycle_materials(root)
        material = "_private/work/papers/cycle/source.md"
        path = root / material; path.parent.mkdir(parents=True); path.write_text("original source")
        worker = root / "material mutation"
        _script(worker, """
import json, pathlib, sys
args = sys.argv[1:]; sys.stdin.read()
p = pathlib.Path(""" + repr(material) + """); p.chmod(0o600); p.write_text('mutated')
out = pathlib.Path(args[args.index('--output-last-message') + 1]); out.write_text('PASS')
print(json.dumps({'type':'turn.completed'}))
""")
        r = _run_worktree(root, prompt, worker, materials=[material])
        assert r.returncode == 4, r.stdout + r.stderr
        meta = json.loads((_run_dir(root, r.stdout) / "meta.json").read_text())
        assert meta["status"] == "read-material-changed" and meta["worktree"]["material_integrity"] is False
        assert meta["worktree"]["material_changes"] == [material]
        assert path.read_text() == "original source"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_material_snapshot_bytes_do_not_follow_later_source_edits():
    root, prompt, _ = _init_worktree_repo()
    fw = _fw(); previous_root = fw.ROOT
    try:
        fw.ROOT = str(root)
        (root / "materials").mkdir(); source = root / "materials/item.md"; source.write_text("before")
        snapshot = fw._snapshot_read_materials(["materials/item.md"])
        source.write_text("after")
        run = root / "read-material-snapshot-run"; run.mkdir()
        wt, meta, _ = fw._prepare_worktree(str(run), "head", snapshot)
        try:
            assert (Path(wt) / "materials/item.md").read_text() == "before"
            assert meta["material_sha256"]["materials/item.md"] == hashlib.sha256(b"before").hexdigest()
        finally:
            fw._remove_worktree(wt)
    finally:
        fw.ROOT = previous_root
        shutil.rmtree(root, ignore_errors=True)


def test_sigterm_reaps_runtime_and_removes_only_owned_worktree_and_materials():
    root, prompt, _ = _init_worktree_repo()
    process = None
    try:
        _allow_cycle_materials(root)
        material = "_private/work/papers/sample.md"
        (root / material).parent.mkdir(parents=True)
        (root / material).write_text("private approved source\n")
        other = root / "_private/other-worktree"
        _git_ok(root, "worktree", "add", "--detach", str(other), "HEAD")
        marker = root / "runtime-pids.json"
        runtime = root / "stubborn runtime"
        _script(runtime, '''import json, os, pathlib, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])
pathlib.Path(os.environ['PID_MARKER']).write_text(json.dumps([os.getpid(), child.pid, str(pathlib.Path.cwd())]))
time.sleep(60)
''')
        process = subprocess.Popen([sys.executable, str(WORKER), "--runtime", "codex", "--worktree=head",
                                    "--read-material", material, str(prompt)], cwd=root,
                                   env=dict(_fixture_env(root), PID_MARKER=str(marker),
                                            MOTTORI_FRESH_WORKER_CODEX_BIN=str(runtime)),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.05)
        assert marker.exists(), ("runtime did not start", process.communicate(timeout=1))
        parent_pid, child_pid, worktree = json.loads(marker.read_text())
        assert (Path(worktree) / material).is_file()
        process.terminate()  # Signal just the dispatcher, not its child process group.
        out, err = process.communicate(timeout=8)
        assert process.returncode == 143, (process.returncode, out, err)
        assert not Path(worktree).exists()
        registered = _git_ok(root, "worktree", "list", "--porcelain")
        assert worktree not in registered and str(other) in registered and other.is_dir()
        assert (root / material).read_text() == "private approved source\n"
        for pid in (parent_pid, child_pid):
            # A just-killed orphan can briefly be a zombie awaiting the system reaper.
            result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
            assert not result.stdout.strip() or result.stdout.strip().startswith("Z"), (pid, result.stdout)
        meta = json.loads((Path(worktree).parent / "meta.json").read_text())
        assert meta["status"] == "interrupted"
    finally:
        if process and process.poll() is None:
            process.kill(); process.wait()
        shutil.rmtree(root, ignore_errors=True)


def test_agents_identity_uses_worker_head_bytes_and_separates_dirty_root():
    root, prompt, runtime = _init_worktree_repo()
    try:
        original = (root / "AGENTS.md").read_bytes()
        (root / "AGENTS.md").write_text("uncommitted root rules\n")
        result = _run_worktree(root, prompt, runtime)
        assert result.returncode == 0, (result.stdout, result.stderr)
        meta = json.loads((_run_dir(root, result.stdout) / "meta.json").read_text())
        assert meta["agents_sha256"] == hashlib.sha256(original).hexdigest()
        assert meta["root_agents_sha256"] == hashlib.sha256((root / "AGENTS.md").read_bytes()).hexdigest()
        assert meta["agents_sha256"] != meta["root_agents_sha256"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_runtime_credentials_are_provider_scoped_end_to_end():
    root = Path(tempfile.mkdtemp(prefix="worker-provider-env-"))
    try:
        home = root / "home"
        token = home / ".config/mottori/claude-oauth-token"
        token.parent.mkdir(parents=True)
        token.write_text("synthetic-saved-claude-token")
        token.chmod(0o600)
        prompt = root / "prompt.md"
        prompt.write_text("Report only environment presence, never credential values.\n")
        runtime = root / "fake runtime"
        _script(runtime, r"""
import json, os, pathlib, sys
args = sys.argv[1:]
sys.stdin.read()
provider_keys = sorted(key for key in os.environ if key.startswith(("CLAUDE_", "ANTHROPIC_", "OPENAI_", "CODEX_")))
result = json.dumps({"keys": provider_keys,
                     "saved_token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "synthetic-saved-claude-token",
                     "code_home_kept": os.environ.get("CODEX_HOME", "").endswith("synthetic-codex-home")})
if "--output-last-message" in args:
    pathlib.Path(args[args.index("--output-last-message") + 1]).write_text(result)
    print(json.dumps({"type": "turn.completed"}))
else:
    print(json.dumps({"type": "result", "result": result}))
""")
        common = dict(_fixture_env(root), HOME=str(home),
                      CLAUDE_CODE_OAUTH_TOKEN="synthetic-inherited-claude-token",
                      ANTHROPIC_API_KEY="synthetic-anthropic-key",
                      ANTHROPIC_BASE_URL="https://provider.example.invalid",
                      OPENAI_API_KEY="synthetic-openai-key", CODEX_API_KEY="synthetic-codex-key",
                      CODEX_HOME=str(home / "synthetic-codex-home"))
        for provider in ("codex", "claude"):
            env = dict(common)
            env[f"MOTTORI_FRESH_WORKER_{provider.upper()}_BIN"] = str(runtime)
            if provider == "claude":
                env["CLAUDE_CODE_OAUTH_TOKEN"] = ""
            result = subprocess.run([sys.executable, str(WORKER), "--runtime", provider, str(prompt)],
                                    cwd=root, env=env, capture_output=True, text=True)
            assert result.returncode == 0, (result.returncode, result.stderr)
            run = _run_dir(root, result.stdout)
            observed = json.loads((run / "result.txt").read_text())
            if provider == "codex":
                assert not any(key.startswith(("CLAUDE_", "ANTHROPIC_")) for key in observed["keys"]), observed
                assert "OPENAI_API_KEY" in observed["keys"] and observed["code_home_kept"], observed
                assert observed["saved_token"] is False
            else:
                assert not any(key.startswith(("OPENAI_", "CODEX_")) for key in observed["keys"]), observed
                assert observed["saved_token"] is True and "ANTHROPIC_API_KEY" in observed["keys"], observed
            for artifact in run.iterdir():
                if artifact.is_file():
                    payload = artifact.read_bytes()
                    for secret in (b"synthetic-saved-claude-token", b"synthetic-inherited-claude-token",
                                   b"synthetic-anthropic-key", b"synthetic-openai-key", b"synthetic-codex-key"):
                        assert secret not in payload, artifact.name
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_codex_environment_never_reads_claude_token_and_hash_binds_policy():
    fw = _fw()
    old_env, old_policy = fw._claude_auth.env, fw.ENV_POLICY_VERSION
    try:
        def forbidden(*args, **kwargs):
            raise AssertionError("Codex must not load a saved Claude token")
        fw._claude_auth.env = forbidden
        env = fw._runtime_env("codex", "/synthetic/workspace")
        assert env["MOTTORI_INSTANCE"] == "/synthetic/workspace"
        first = fw._harness_sha256("codex", fw._codex_command("/result"), ("/result",))
        fw.ENV_POLICY_VERSION = old_policy + "-changed"
        assert fw._harness_sha256("codex", fw._codex_command("/result"), ("/result",)) != first
    finally:
        fw._claude_auth.env, fw.ENV_POLICY_VERSION = old_env, old_policy


def test_read_scope_english_markers_anywhere_are_optional_self_reports():
    fw = _fw()
    result = "# Review\nREAD_SCOPE: tools/a.py\nREAD_SCOPE: ignored\nUNREAD: old\nUNREAD: tools/b.py\nRESULT_JSON: {}\n"
    assert fw._read_scope(result) == {"declared": "READ_SCOPE: tools/a.py", "unread": "UNREAD: tools/b.py"}
    assert fw._read_scope("UNREAD: missing\n") == {"declared": None, "unread": "UNREAD: missing"}
    for provider in ("claude", "codex"):
        prefix = fw._effective_prompt(provider, "")
        assert "READ_SCOPE:" in prefix and "UNREAD:" in prefix and "self-reports" in prefix
    valid = fw._result_contract('RESULT_JSON: {"verdict":"PASS","summary":"ok","evidence":["x.py:1"],"unknowns":[]}')
    assert valid["valid"] and fw._read_scope("No declaration.\n") is None


def test_sync_cluster_contains_runtime_and_test_dependencies():
    fw = _fw()
    assert set(fw.ENGINE_FILES) <= set(fw.SYNC_FILES)
    assert "testlib.py" in fw.SYNC_FILES
    assert len(fw.SYNC_FILES) == len(set(fw.SYNC_FILES))


TESTS = [
    test_runtime_credentials_are_provider_scoped_end_to_end,
    test_codex_environment_never_reads_claude_token_and_hash_binds_policy,
    test_read_scope_english_markers_anywhere_are_optional_self_reports,
    test_sync_cluster_contains_runtime_and_test_dependencies,
    test_sigterm_reaps_runtime_and_removes_only_owned_worktree_and_materials,
    test_agents_identity_uses_worker_head_bytes_and_separates_dirty_root,
    test_read_materials_actual_isolate_reproduces_missing_then_delivers_all_inputs,
    test_read_material_rejects_denied_directory_symlink_and_source_shadow,
    test_read_material_mutation_overrides_runtime_pass_and_preserves_original,
    test_read_material_snapshot_bytes_do_not_follow_later_source_edits,

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
    test_result_contract_is_structured_and_free_prose_is_inconclusive,
    test_fresh_worker_receipt_limit_matches_contract_boundary,
    test_scope_violation_detected_outside_prefix_and_symlink_escape,
    test_scope_ok_within_prefix_and_unchecked_without_prefix,
    test_scope_violation_is_report_only_without_strict,
    test_strict_scope_detects_git_and_immediate_parent_writes,
    test_read_scope_accepts_declaration_variants,
    test_write_prefix_boundaries_fail_closed,
    test_scope_preexisting_symlink_under_prefix_is_violation,
    test_scope_detects_same_size_change_with_restored_mtime_and_empty_dirs,
    test_scope_violation_outranks_runtime_failure,
    test_prefix_spelling_follows_disk_on_case_insensitive_fs,
    test_read_scope_strips_bom_and_finds_first_marker,
    test_git_timeout_yields_null_identity,
    test_engine_identity_prefers_embedded_kit_rev,
    test_scope_hardlink_alias_outside_workspace_is_violation,
    test_missing_nested_prefix_is_created_before_baseline,
    test_prefix_case_is_not_rewritten_on_case_sensitive_fs,
    test_usage_string_numbers_stay_raw_but_normalize_to_null,
    test_engine_sha256_ignores_sync_stamp_lines,
    test_worktree_is_created_with_minimum_instance_state_and_cleaned,
    test_worktree_pins_observed_revision_even_when_head_moves,
    test_worktree_ignores_git_env_pinned_by_an_outer_hook,
    test_worktree_patch_extracts_modified_new_and_deleted_files,
    test_worktree_ignored_output_survives_cleanup_with_hash_and_patch,
    test_worktree_unsafe_ignored_outputs_are_not_exported_and_prevent_cleanup,
    test_worktree_capture_io_failure_preserves_recoverable_output,
    test_worktree_incomplete_ignored_listing_preserves_output,
    test_worktree_final_metadata_failure_keeps_durable_artifacts,
    test_sigterm_during_capture_preserves_owned_worktree_and_output,
    test_worktree_scope_uses_isolate_and_original_tree_is_unchanged,
    test_worktree_dirty_mode_applies_original_tracked_diff,
]


if __name__ == "__main__":
    for test in TESTS:
        run_test(test, __file__)
        print("PASS", test.__name__)
