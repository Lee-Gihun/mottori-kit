#!/usr/bin/env python3
"""Fixture tests for truthful hook diagnostics, pre-commit drift, and canary parsing."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def test_capability_roles_do_not_collapse():
    import hookdiag
    cfg = {"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "echo ok"}]}],
        "PreCompact": [{"hooks": [{"type": "command", "command": "echo ok"}]}],
    }}
    report = hookdiag.static_report("codex", cfg)
    assert report["injector"]["declared"] is True
    assert report["side_effect"]["declared"] is True
    assert report["observer"]["declared"] is False
    assert report["enforcer"]["declared"] is False
    assert report["injector"]["fired"] == "unknown"
    assert report["injector"]["effect"] == "unknown"
    assert report["injector"]["command_valid"] is True


def test_gate_unit_rejects_current_only_checker_key():
    """이름은 유지(근거 표지 호환), 계약은 2026-09-18에 바뀌었다: 검사기 추가는 빈 기준선(이슈 0이면 통과·기록),
    검사기 제거는 차단. 옛 계약(추가도 차단)은 검사기 추가 커밋을 교착시켰다."""
    import gate
    reason, pull = gate._verdict({"linkcheck": set(), "new-checker": set()}, {"linkcheck": set()}, "ok")
    assert reason is None and pull is True, (reason, pull)
    reason, pull = gate._verdict({"linkcheck": set(), "new-checker": {"n|1"}}, {"linkcheck": set()}, "ok")
    assert reason is not None and "n|1" in reason and pull is False, (reason, pull)
    reason, pull = gate._verdict({"linkcheck": set()}, {"linkcheck": set(), "gone": set()}, "ok")
    assert reason is not None and "gone" in reason and pull is False, (reason, pull)


def test_doctor_rejects_declared_hook_with_invalid_command():
    import doctor
    root = tempfile.mkdtemp(prefix="hook-doctor-")
    old_root = doctor.ROOT
    try:
        os.makedirs(os.path.join(root, ".claude"))
        cfg = {"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command":
                "echo state/NOW.md _private/state/NOW.md unavailable"}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": ""}]}],
        }}
        with open(os.path.join(root, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        doctor.ROOT = root
        status, detail = doctor._wiring("claude")
        assert status == doctor.FAIL and "command invalid" in detail
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_codex_trust_and_matcher_are_separate_stages():
    import hookdiag
    hooks = [{
        "eventName": "sessionStart", "source": "project", "enabled": True,
        "trustStatus": "modified", "currentHash": "sha256:new", "matcher": None,
        "command": "echo ok",
    }, {
        "eventName": "preToolUse", "source": "project", "enabled": True,
        "trustStatus": "trusted", "currentHash": "sha256:guard", "matcher": "Glob|Grep",
        "command": "echo guard",
    }]
    report = hookdiag.codex_runtime_report(hooks)
    assert report["injector"]["declared"] is True
    assert report["injector"]["armed"] is False
    assert report["injector"]["trust"] == "modified"
    assert report["guard"]["armed"] is True
    assert report["guard"]["matcher_reachable"] is False
    assert report["guard"]["fired"] == "unknown"


def _fixture_repo():
    root = tempfile.mkdtemp(prefix="hook-installer-")
    subprocess.run(["git", "init", "-q", root], check=True)
    os.makedirs(os.path.join(root, "tools"))
    for name in ("install_hooks.sh", "precommit-hook.sh"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    with open(os.path.join(root, "tools", "gate.py"), "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env python3\nraise SystemExit(0)\n")
    return root


def _installer(root, mode, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(["bash", "tools/install_hooks.sh", mode], cwd=root,
                          capture_output=True, text=True, env=env)


def _hook_path(root):
    hooks = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=root,
                           capture_output=True, text=True, check=True).stdout.strip()
    if not os.path.isabs(hooks):
        hooks = os.path.join(root, hooks)
    return os.path.join(os.path.realpath(hooks), "pre-commit")


def test_installer_check_is_read_only_and_repair_is_exact():
    root = _fixture_repo()
    try:
        hook = _hook_path(root)
        r = _installer(root, "--check")
        assert r.returncode != 0 and "missing" in (r.stdout + r.stderr)
        assert not os.path.exists(hook)

        r = _installer(root, "--repair")
        assert r.returncode == 0, r.stdout + r.stderr
        template = open(os.path.join(root, "tools", "precommit-hook.sh"), "rb").read()
        assert open(hook, "rb").read() == template
        assert os.stat(hook).st_mode & stat.S_IXUSR

        before = (hashlib.sha256(open(hook, "rb").read()).hexdigest(),
                  os.stat(hook).st_mode, os.stat(hook).st_mtime_ns)
        r = _installer(root, "--check")
        after = (hashlib.sha256(open(hook, "rb").read()).hexdigest(),
                 os.stat(hook).st_mode, os.stat(hook).st_mtime_ns)
        assert r.returncode == 0 and before == after

        # The canonical hook from immediately before the sentinel was introduced is owned
        # migration material only when it matches the explicit legacy hash.
        legacy = open(hook, encoding="utf-8").read().replace(
            "# MOTTORI_PRECOMMIT_HOOK_V1\n", "")
        with open(hook, "w", encoding="utf-8") as f:
            f.write(legacy)
        legacy_hash = hashlib.sha256(legacy.encode("utf-8")).hexdigest()
        r = _installer(root, "--check", {"MOTTORI_LEGACY_HOOK_HASHES": legacy_hash})
        assert r.returncode != 0 and "owned-drift" in (r.stdout + r.stderr), r.stdout + r.stderr
        r = _installer(root, "--repair", {"MOTTORI_LEGACY_HOOK_HASHES": legacy_hash})
        assert r.returncode == 0 and open(hook, "rb").read() == template
        assert [x for x in os.listdir(os.path.dirname(hook)) if x.startswith("pre-commit.bak.")]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_installer_refuses_foreign_and_outside_hookspath():
    root = _fixture_repo()
    outside = tempfile.mkdtemp(prefix="outside-hooks-")
    try:
        hook = _hook_path(root)
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        with open(hook, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n# docs mention mottori gate, but this hook is foreign\necho foreign\n")
        r = _installer(root, "--repair")
        assert r.returncode != 0 and "foreign" in (r.stdout + r.stderr)
        assert "echo foreign" in open(hook, encoding="utf-8").read()

        subprocess.run(["git", "config", "core.hooksPath", outside], cwd=root, check=True)
        r = _installer(root, "--repair")
        assert r.returncode != 0 and "outside-repo" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(outside, "pre-commit"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_installer_uses_common_hooks_in_linked_worktree():
    root = _fixture_repo()
    linked = tempfile.mkdtemp(prefix="linked-worktree-")
    shutil.rmtree(linked)
    try:
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        subprocess.run(["git", "worktree", "add", "-q", "-b", "fixture-linked", linked],
                       cwd=root, check=True)

        r = _installer(linked, "--repair")
        assert r.returncode == 0, r.stdout + r.stderr
        assert os.path.isfile(_hook_path(linked))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", linked],
                       cwd=root, capture_output=True)
        shutil.rmtree(linked, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_installer_honors_relative_hookspath():
    root = _fixture_repo()
    try:
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True)
        r = _installer(root, "--repair")
        assert r.returncode == 0, r.stdout + r.stderr
        assert os.path.isfile(os.path.join(root, ".githooks", "pre-commit"))
        assert _installer(root, "--check").returncode == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_canary_parser_reads_only_agent_messages():
    import hook_canary
    token = "SECRET-NONCE"
    stream = "\n".join([
        json.dumps({"type": "hook.completed", "payload": {"output": token}}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "output": token}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ABSENT"}}),
    ])
    messages, tool_count = hook_canary.agent_messages(stream)
    assert messages == ["ABSENT"]
    assert tool_count == 1
    assert token not in "\n".join(messages)


def test_all_canary_persists_runtime_results_without_nonce():
    import hook_canary
    root = tempfile.mkdtemp(prefix="hook-canary-result-")
    result_path = os.path.join(root, "state", "hook-canary.json")
    old_path = hook_canary.RESULT_PATH
    old_argv = sys.argv[:]
    old_codex = hook_canary._codex_canary
    old_claude = hook_canary._claude_canary
    old_token_hex = hook_canary.secrets.token_hex
    try:
        hook_canary.RESULT_PATH = result_path
        hook_canary._codex_canary = lambda token: True
        hook_canary._claude_canary = lambda token: False
        hook_canary.secrets.token_hex = lambda size: "SECRET-NONCE"
        sys.argv = ["hook_canary.py", "--all"]
        assert hook_canary.main() == 1
        payload = json.load(open(result_path, encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert set(payload["runtimes"]) == {"codex", "claude"}
        assert payload["runtimes"]["codex"]["status"] == "PASS"
        assert payload["runtimes"]["codex"]["effect"] == "verified"
        assert payload["runtimes"]["claude"]["status"] == "FAIL"
        assert payload["runtimes"]["claude"]["effect"] == "not_verified"
        assert all(row["checked_at"] for row in payload["runtimes"].values())
        assert "SECRET" not in open(result_path, encoding="utf-8").read()
    finally:
        hook_canary.RESULT_PATH = old_path
        hook_canary._codex_canary = old_codex
        hook_canary._claude_canary = old_claude
        hook_canary.secrets.token_hex = old_token_hex
        sys.argv = old_argv
        shutil.rmtree(root, ignore_errors=True)


def test_precommit_now_check_reads_extracted_index_tree():
    """The index check must catch staged journal/NOW drift even when live NOW is clean."""
    import gate

    root = tempfile.mkdtemp(prefix="staged-now-source-")
    extracted = root + "-extracted"
    try:
        os.makedirs(os.path.join(root, "tools"))
        os.makedirs(os.path.join(root, "system"))
        os.makedirs(os.path.join(root, "state"))
        for name in ("now.py", "memlib.py"):
            shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
        cfg = {
            "schema_version": 4,
            "instance": {"name": "fixture", "context": "personal", "remote_allowlist": []},
            "tracks": [],
            "threads": [],
            "personal_pointer": None,
            "journal_visibility": {
                "public_tracks": ["system"],
                "legacy_cutoff": None,
                "legacy_public_tracks": [],
            },
            "journal_types": ["decision", "state", "artifact", "correction", "lesson", "switch", "idea"],
            "thresholds": {
                "now_tail_events": 12,
                "now_recent_decisions": 8,
                "track_stale_days": 7,
                "journal_stale_days": 2,
                "memory_rot_days": 14,
                "now_max_bytes": 6000,
                "now_hook_max_bytes": 6000,
            },
        }
        with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        first = subprocess.run(
            [sys.executable, os.path.join(root, "tools", "now.py"), "log",
             "[system/state] INDEX-BASE"],
            cwd=root, env=env, capture_output=True, text=True)
        assert first.returncode == 0, first.stdout + first.stderr
        # checkout-index cannot preserve an mtime that Git does not store. If a clean tree
        # extracted with identical bytes and a new mtime appears stale, every commit is blocked.
        shutil.copytree(root, extracted, copy_function=shutil.copy)
        local_state = os.path.join(extracted, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        local_journal = os.path.join(
            local_state, "journal-" +
            __import__("datetime").datetime.now().strftime("%Y-%m") + ".md")
        with open(local_journal, "w", encoding="utf-8") as f:
            f.write("- malformed local-only journal row\n")
        live_env = dict(os.environ, MOTTORI_INSTANCE=extracted)
        live = subprocess.run(
            [sys.executable, os.path.join(extracted, "tools", "now.py"),
             "check", "--issues"],
            cwd=extracted, env=live_env, capture_output=True, text=True)
        assert live.returncode == 0, live.stdout + live.stderr
        assert "journal-corrupt:" in live.stdout, live.stdout
        clean_filelist = os.path.join(extracted, ".gate-filelist")
        open(clean_filelist, "w", encoding="utf-8").close()
        clean = gate.measure(tree=extracted, filelist=clean_filelist)
        assert clean["now-check"] is not None
        assert not any(issue.startswith("journal-corrupt:")
                       for issue in clean["now-check"]), clean["now-check"]
        assert "now-input-newer" not in clean["now-check"], clean["now-check"]

        # Even with unchanged input bytes, tampering only with staged NOW must mismatch the marker.
        now_path = os.path.join(extracted, "state", "NOW.md")
        clean_now = open(now_path, encoding="utf-8").read()
        with open(now_path, "w", encoding="utf-8") as f:
            f.write(clean_now.replace("# NOW\n", "# NOW TAMPERED\n", 1))
        tampered = gate.measure(tree=extracted, filelist=clean_filelist)
        assert tampered["now-check"] is not None
        assert "now-input-newer" in tampered["now-check"], tampered["now-check"]
        with open(now_path, "w", encoding="utf-8") as f:
            f.write(clean_now)

        journal = os.path.join(extracted, "state", "journal-" +
                               __import__("datetime").datetime.now().strftime("%Y-%m") + ".md")
        with open(journal, "a", encoding="utf-8") as f:
            f.write("- 2099-01-01T00:00:00+09:00 [system/state] INDEX-ONLY-CHANGE\n")
        filelist = os.path.join(extracted, ".gate-filelist")
        open(filelist, "w", encoding="utf-8").close()

        measured = gate.measure(tree=extracted, filelist=filelist)
        assert measured["now-check"] is not None
        assert "now-input-newer" in measured["now-check"], measured["now-check"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(extracted, ignore_errors=True)


TESTS = [
    test_capability_roles_do_not_collapse,
    test_gate_unit_rejects_current_only_checker_key,
    test_doctor_rejects_declared_hook_with_invalid_command,
    test_codex_trust_and_matcher_are_separate_stages,
    test_installer_check_is_read_only_and_repair_is_exact,
    test_installer_refuses_foreign_and_outside_hookspath,
    test_installer_uses_common_hooks_in_linked_worktree,
    test_installer_honors_relative_hookspath,
    test_canary_parser_reads_only_agent_messages,
    test_all_canary_persists_runtime_results_without_nonce,
    test_precommit_now_check_reads_extracted_index_tree,
]


def run():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as e:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
    print(f"hook runtime: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
