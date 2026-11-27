#!/usr/bin/env python3
"""Fixture tests for truthful hook diagnostics, pre-commit drift, and canary parsing.

The gate cases exercise tools/gate.py."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]


def test_capability_stages_do_not_collapse():
    import hookdiag
    cfg = {"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "echo ok"}]}],
        "PreCompact": [{"hooks": [{"type": "command", "command": "echo ok"}]}],
    }}
    report = hookdiag.static_report("codex", cfg)
    assert report["SessionStart"]["declared"] is True
    assert report["PreCompact"]["declared"] is True
    assert report["PostToolUse"]["declared"] is False
    assert report["Stop"]["declared"] is False
    assert report["SessionStart"]["fired"] == "unknown"
    assert report["SessionStart"]["effect"] == "unknown"
    assert report["SessionStart"]["command_valid"] is True


def test_gate_unit_rejects_current_only_checker_key():
    """Keep the test name for evidence-marker compatibility.

    New checkers start with an empty baseline; removing a checker blocks validation."""
    import gate
    reason, pull = gate._verdict(gate.Measurement({"linkcheck": set(), "new-checker": set()}), {"linkcheck": set()}, "ok")
    assert reason is None and pull is True, (reason, pull)
    reason, pull = gate._verdict(gate.Measurement({"linkcheck": set(), "new-checker": {"n|1"}}), {"linkcheck": set()}, "ok")
    assert reason is not None and "n|1" in reason and pull is False, (reason, pull)
    reason, pull = gate._verdict(gate.Measurement({"linkcheck": set()}), {"linkcheck": set(), "gone": set()}, "ok")
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
        assert status == doctor.FAIL and "declared but command invalid" in detail, detail
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_owner_lines_beside_the_kit_lines_never_fail_doctor():
    """SETUP invites owners to add their own hook lines. One beside the kit's line, on any event of
    any runtime and wherever it stands, fails none of the rows that read the declarations, even
    when it names an absolute path on the owner's machine."""
    import doctor
    import hookdiag
    root = tempfile.mkdtemp(prefix="hook-doctor-own-")
    saved = doctor.ROOT, doctor._probe_session, doctor._configured
    try:
        os.symlink(os.path.join(saved[0], "tools"), os.path.join(root, "tools"))
        own = [{"type": "command", "command": "echo mine"},
               {"type": "command", "command": "python3 /Users/owner/bin/mine.py || true"}]
        for runtime, parts in hookdiag.HOOK_FILES.items():
            with open(os.path.join(saved[0], *parts), encoding="utf-8") as f:
                cfg = json.load(f)
            tables = [cfg["kit"]] if runtime == "agy" else [cfg["hooks"]]
            for table in tables:
                for event, entries in table.items():
                    if event == "enabled":
                        continue
                    grouped = "hooks" in entries[0]
                    # Before the kit's line in its own group and after it in the same group.
                    entries.insert(0, {"hooks": [own[0]]} if grouped else own[0])
                    (entries[-1]["hooks"] if grouped else entries).append(own[1])
            os.makedirs(os.path.join(root, parts[0]), exist_ok=True)
            with open(os.path.join(root, *parts), "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        doctor.ROOT = root
        doctor._probe_session = lambda command, *a, **k: (
            ("[kit] state/NOW.md _private/state/NOW.md unavailable", None)
            if "doctor-hook-failure-" in a[0] else ("state", None))
        doctor._configured = lambda: True
        rows = {f"wiring {runtime}": doctor._wiring(runtime) for runtime in hookdiag.HOOK_FILES}
        rows.update(success=doctor.c_hook_success(), failure=doctor.c_hook_failure(),
                    codex=doctor.c_hook_codex_run(), time=doctor.c_global_hook(),
                    compact_claude=doctor._simulate_precompact("claude"),
                    compact_codex=doctor._simulate_precompact("codex"))
        failed = {name: row for name, row in rows.items() if row[0] == doctor.FAIL}
        assert not failed, failed
        # The kit's own line is still judged: made absolute, it fails.
        path = os.path.join(root, ".claude", "settings.json")
        with open(path, encoding="utf-8") as f:
            text = f.read().replace("$CLAUDE_PROJECT_DIR", "/Users/owner/kit")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        status, detail = doctor._wiring("claude")
        assert status == doctor.FAIL and "absolute path" in detail and "mine.py" not in detail, detail
    finally:
        doctor.ROOT, doctor._probe_session, doctor._configured = saved
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_accepts_own_session_hook_beside_event_line():
    """SETUP tells owners to put their own hooks beside the kit's event lines."""
    import doctor
    root = tempfile.mkdtemp(prefix="hook-doctor-")
    old_root = doctor.ROOT
    old_probe, old_configured = doctor._probe_session, doctor._configured
    try:
        os.makedirs(os.path.join(root, ".claude"))
        with open(os.path.join(old_root, ".claude", "settings.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        own = {"hooks": [{"type": "command", "command": "echo hello"}]}
        kit_line = cfg["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        path = os.path.join(root, ".claude", "settings.json")
        doctor.ROOT = root
        seen = []
        doctor._probe_session = lambda command, *a, **k: (seen.append(command), (None, "x"))[1]
        doctor._configured = lambda: True
        # SETUP gives no order, so the owner's line may come before the kit's line or after it.
        for groups in ([cfg["hooks"]["SessionStart"][0], own], [own, cfg["hooks"]["SessionStart"][0]]):
            cfg["hooks"]["SessionStart"] = groups
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            status, detail = doctor._wiring("claude")
            assert status != doctor.FAIL, detail
            del seen[:]
            doctor.c_hook_success()
            doctor.c_hook_failure()
            assert seen == [kit_line, kit_line], seen
        # The same holds for PreCompact, whose simulation runs only the kit's line.
        os.symlink(os.path.join(old_root, "tools"), os.path.join(root, "tools"))
        kit_compact = cfg["hooks"]["PreCompact"][0]
        for groups in ([kit_compact, own], [own, kit_compact]):
            cfg["hooks"]["PreCompact"] = groups
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            status, detail = doctor._simulate_precompact("claude")
            assert status == doctor.PASS, detail
        # Two lines and neither the kit's: nothing says which one to run, so the row says so.
        cfg["hooks"]["PreCompact"] = [own, own]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        status, detail = doctor._simulate_precompact("claude")
        assert (status, detail) == (doctor.FAIL, doctor.PRECOMPACT_MULTIPLE.format(
            runtime="claude", count=2)), detail
        # An event line for another event or another runtime does not carry the start contract.
        for wrong in ("event UserPromptSubmit claude", "event SessionStart codex"):
            cfg["hooks"]["SessionStart"] = [{"hooks": [{"type": "command", "timeout": 30,
                "command": kit_line.replace("event SessionStart claude", wrong)}]}]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            status, detail = doctor._wiring("claude")
            assert status == doctor.FAIL and "unavailable" in detail, (wrong, detail)
        # Without the launcher line the hand-written fallback must still carry the contract.
        cfg["hooks"]["SessionStart"] = [own]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        status, detail = doctor._wiring("claude")
        assert status == doctor.FAIL and "unavailable" in detail, detail
    finally:
        doctor.ROOT = old_root
        doctor._probe_session, doctor._configured = old_probe, old_configured
        shutil.rmtree(root, ignore_errors=True)


def test_codex_trust_and_matcher_are_separate_stages():
    import hookdiag
    hooks = [{
        "eventName": "sessionStart", "source": "project", "enabled": True,
        "trustStatus": "modified", "currentHash": "sha256:new", "matcher": None,
        "command": "echo ok",
    }, {
        "eventName": "postToolUse", "source": "project", "enabled": True,
        "trustStatus": "trusted", "currentHash": "sha256:edit", "matcher": "Glob|Grep",
        "command": "echo edited",
    }]
    report = hookdiag.codex_runtime_report(hooks)
    assert report["SessionStart"]["declared"] is True
    assert report["SessionStart"]["armed"] is False
    assert report["SessionStart"]["trust"] == "modified"
    assert report["PostToolUse"]["armed"] is True
    assert report["PostToolUse"]["matcher_reachable"] is False
    assert report["PostToolUse"]["fired"] == "unknown"

    # A disabled hook is not armed even when trusted, and a user-level hook is not the
    # project's SessionStart hook at all.
    trusted = {"eventName": "sessionStart", "enabled": True, "trustStatus": "trusted",
               "currentHash": "sha256:ok", "matcher": None, "command": "echo ok"}
    disabled = hookdiag.codex_runtime_report([dict(trusted, source="project", enabled=False)])
    assert disabled["SessionStart"]["declared"] is True
    assert disabled["SessionStart"]["armed"] is False
    user = hookdiag.codex_runtime_report([dict(trusted, source="user")])
    assert user["SessionStart"]["declared"] is False
    assert user["SessionStart"]["armed"] is False


def _git_env(extra=None):
    """Environment for fixture Git calls that ignores the user's global and system config.

    A global core.hooksPath would otherwise send fixture hooks into the user's real hook folder."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    env.update(extra or {})
    return env


# The installer suite's fixture already isolates Git config and keeps the hook path inside the
# fixture; sharing it keeps one copy of that safety net.
from test_install_hooks import (  # noqa: E402
    fixture as _fixture_repo, hook_path as _hook_path, isolated_env, run as _installer)


def test_installer_check_is_read_only_and_repair_is_exact():
    root = _fixture_repo()
    try:
        hook = _hook_path(root)
        r = _installer(root, "--check")
        assert r.returncode != 0 and "missing" in (r.stdout + r.stderr)
        assert not os.path.exists(hook)

        r = _installer(root, "--repair")
        assert r.returncode == 0, r.stdout + r.stderr
        template = open(os.path.join(root, "tools", "lib", "precommit-hook.sh"), "rb").read()
        assert open(hook, "rb").read() == template
        assert os.stat(hook).st_mode & stat.S_IXUSR
        push_hook = os.path.join(os.path.dirname(hook), "pre-push")
        assert open(push_hook, "rb").read() == template

        before = (hashlib.sha256(open(hook, "rb").read()).hexdigest(),
                  os.stat(hook).st_mode, os.stat(hook).st_mtime_ns)
        r = _installer(root, "--check")
        after = (hashlib.sha256(open(hook, "rb").read()).hexdigest(),
                 os.stat(hook).st_mode, os.stat(hook).st_mtime_ns)
        assert r.returncode == 0 and before == after

        # Git skips a hook without the execute bit, so it must not be reported as installed.
        os.chmod(hook, 0o644)
        r = _installer(root, "--check")
        assert r.returncode != 0 and "owned-drift" in (r.stdout + r.stderr), r.stdout + r.stderr
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

        # A user's own pre-push is kept and named, and the free pre-commit is still installed.
        os.remove(hook)
        push_hook = os.path.join(os.path.dirname(hook), "pre-push")
        foreign_push = b"#!/bin/sh\necho user push hook\n"
        with open(push_hook, "wb") as f:
            f.write(foreign_push)
        r = _installer(root, "--repair")
        assert r.returncode == 2 and "foreign" in r.stderr and "enforce.py prepush" in r.stderr, r.stdout + r.stderr
        assert open(push_hook, "rb").read() == foreign_push
        assert open(hook, "rb").read() == open(os.path.join(root, "tools", "lib", "precommit-hook.sh"), "rb").read()
        # The line the refusal names makes that hook count as installed, and is never rewritten.
        chained = b"#!/bin/sh\n  python3 tools/enforce.py prepush \"$@\" || exit 1\necho user push hook\n"
        with open(push_hook, "wb") as f:
            f.write(chained)
        r = _installer(root, "--check")
        assert r.returncode == 0 and "chained" in r.stdout, r.stdout + r.stderr
        assert _installer(root, "--repair").returncode == 0 and open(push_hook, "rb").read() == chained

        subprocess.run(["git", "config", "core.hooksPath", outside], cwd=root, check=True,
                       env=isolated_env())
        r = _installer(root, "--repair")
        assert r.returncode != 0 and "outside-repo" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(outside, "pre-commit"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_installer_uses_common_hooks_in_linked_worktree():
    root = _fixture_repo()
    git_env = isolated_env()
    linked = tempfile.mkdtemp(prefix="linked-worktree-")
    shutil.rmtree(linked)
    try:
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True, env=git_env)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True, env=git_env)
        subprocess.run(["git", "add", "."], cwd=root, check=True, env=git_env)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True, env=git_env)
        subprocess.run(["git", "worktree", "add", "-q", "-b", "fixture-linked", linked],
                       cwd=root, check=True, env=git_env)

        r = _installer(linked, "--repair")
        assert r.returncode == 0, r.stdout + r.stderr
        # The linked worktree's hook path is the common one in the main checkout.
        assert os.path.isfile(_hook_path(root))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", linked],
                       cwd=root, capture_output=True, env=git_env)
        shutil.rmtree(linked, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_installer_fixtures_ignore_global_hookspath():
    """A global core.hooksPath must not redirect fixture hooks into the user's hook folder."""
    from unittest.mock import patch
    home = tempfile.mkdtemp(prefix="hook-global-home-")
    sentinel_dir = os.path.join(home, "global-hooks")
    os.makedirs(sentinel_dir)
    sentinel = os.path.join(sentinel_dir, "pre-commit")
    with open(sentinel, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\necho sentinel\n")
    with open(os.path.join(home, ".gitconfig"), "w", encoding="utf-8") as f:
        f.write("[core]\n\thooksPath = %s\n" % sentinel_dir)
    hostile = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    hostile["HOME"] = home
    root = None
    try:
        with patch.dict(os.environ, hostile, clear=True):
            root = _fixture_repo()
            hook = _hook_path(root)
            assert os.path.realpath(hook).startswith(os.path.realpath(root) + os.sep), hook
            r = _installer(root, "--repair")
            assert r.returncode == 0, r.stdout + r.stderr
        with open(sentinel, encoding="utf-8") as f:
            assert f.read() == "#!/bin/sh\necho sentinel\n"
        assert os.listdir(sentinel_dir) == ["pre-commit"], os.listdir(sentinel_dir)
    finally:
        if root:
            shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


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
        from unittest.mock import patch
        os.makedirs(os.path.dirname(result_path))
        # A saved file that is not a JSON object is replaced, not a crash; an uninstalled
        # runtime under --all is skipped and nothing is saved for it.
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("[]")
        with patch.object(hook_canary.shutil, "which", lambda name: None if name == "claude" else "/bin/" + name):
            assert hook_canary.main() == 0
        assert set(json.load(open(result_path, encoding="utf-8"))["runtimes"]) == {"codex"}
        with patch.object(hook_canary.shutil, "which", lambda name: "/bin/" + name):
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


def test_hook_canary_rejects_unknown_flag():
    """A mistyped flag must not silently fall back to the paid Codex canary."""
    import hook_canary
    from unittest.mock import patch
    calls = []
    with patch.object(hook_canary, "_codex_canary", lambda token: calls.append("codex") or True), \
            patch.object(hook_canary, "_claude_canary", lambda token: calls.append("claude") or True), \
            patch.object(hook_canary, "_persist_results", lambda rows: calls.append("persist")), \
            patch.object(sys, "argv", ["hook_canary.py", "--claud"]):
        try:
            code = hook_canary.main()
        except SystemExit as exit_:
            code = exit_.code
    assert code not in (0, None), code
    assert calls == [], calls


def test_claude_canary_skips_negative_after_failed_positive():
    """A failed positive run already decides FAIL; the negative model call is wasted cost."""
    import hook_canary
    from unittest.mock import patch
    calls = []

    def fake_run(token, hooks_enabled):
        calls.append(hooks_enabled)
        return subprocess.CompletedProcess([], 1, stdout="", stderr="boom")

    with patch.object(hook_canary, "_run_claude", fake_run):
        assert hook_canary._claude_canary("SYNTHETIC-NONCE") is False
    assert calls == [True], calls
    # Both runtimes get a closed stdin; the Claude model comes from the environment, default haiku.
    seen = []
    with patch.object(hook_canary.shutil, "which", lambda name: "/bin/" + name), \
            patch.object(hook_canary.subprocess, "run", lambda cmd, **kw: seen.append((cmd, kw))), \
            patch.object(hook_canary.claude_auth, "_read_token", return_value=None):
        with patch.dict(os.environ, {"MOTTORI_HOOK_CANARY_CLAUDE_MODEL": ""}):
            hook_canary._run_claude("SYNTHETIC-NONCE", True)
            hook_canary._run("SYNTHETIC-NONCE", True)
        with patch.dict(os.environ, {"MOTTORI_HOOK_CANARY_CLAUDE_MODEL": "sonnet"}):
            hook_canary._run_claude("SYNTHETIC-NONCE", True)
    assert all(kw.get("stdin") is subprocess.DEVNULL for _cmd, kw in seen), seen
    models = [cmd[cmd.index("--model") + 1] for cmd, _kw in seen if "--model" in cmd]
    assert models == ["haiku", "sonnet"], models


def test_staged_python_syntax_checks_unicode_spaces_and_index_bytes():
    """Quoted filenames and clean worktree bytes must not hide broken staged code."""
    import gate
    with tempfile.TemporaryDirectory(prefix="staged-python-") as directory:
        root = os.path.join(directory, "repo")
        extracted = os.path.join(directory, "index")
        os.makedirs(os.path.join(root, "tools"))
        os.makedirs(extracted)
        subprocess.run(["git", "init", "-q", root], check=True)
        subprocess.run(["git", "-C", root, "config", "core.quotePath", "true"], check=True)
        names = ("tools/한글 파일.py", "tools/space name.py")
        for name in names:
            with open(os.path.join(root, name), "w", encoding="utf-8") as source:
                source.write("def broken(:\n")
        subprocess.run(["git", "-C", root, "add", "--", *names], check=True)
        for name in names:
            with open(os.path.join(root, name), "w", encoding="utf-8") as source:
                source.write("value = 1\n")
        subprocess.run(["git", "-C", root, "checkout-index", "-a", "--prefix", extracted + "/"], check=True)
        old_root = os.environ.get("MOTTORI_INSTANCE")
        os.environ["MOTTORI_INSTANCE"] = root
        try:
            errors = gate._staged_tools_compile(extracted)
            assert len(errors) == 2 and all(any(error.startswith(name + ":") for error in errors) for name in names), errors
            for name in names:
                shutil.copy2(os.path.join(root, name), os.path.join(extracted, name))
            assert gate._staged_tools_compile(extracted) == []
            os.remove(os.path.join(extracted, names[0]))
            assert gate._staged_tools_compile(extracted) == [names[0] + ": missing staged file"]
            # A path that does not exist: the extracted tree may sit inside some other checkout.
            os.environ["MOTTORI_INSTANCE"] = os.path.join(directory, "missing")
            try:
                gate._staged_tools_compile(extracted)
            except ValueError:
                pass
            else:
                raise AssertionError("failed Git listing was accepted as an empty source tree")
        finally:
            if old_root is None:
                os.environ.pop("MOTTORI_INSTANCE", None)
            else:
                os.environ["MOTTORI_INSTANCE"] = old_root


def test_precommit_now_check_reads_extracted_index_tree():
    """The index check must catch staged journal/NOW drift even when live NOW is clean."""
    import gate

    root = tempfile.mkdtemp(prefix="staged-now-source-")
    extracted = root + "-extracted"
    try:
        os.makedirs(os.path.join(root, "tools", "lib"))
        os.makedirs(os.path.join(root, "instance"))
        os.makedirs(os.path.join(root, "state"))
        for name in ("now.py", "lib/memory_index.py", "lib/config.py", "enforce.py",
                     "lib/hook_input.py", "lib/journal.py", "lib/paths.py", "lib/runlog.py", "lib/safeio.py"):
            shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
        cfg = {
            "schema_version": 4,
            "instance": {"name": "fixture"},
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
                "journal_stale_days": 2,
                "memory_rot_days": 14,
                "now_max_bytes": 6000,
                "now_hook_max_bytes": 6000,
            },
        }
        with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
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
        clean = gate.measure(tree=extracted, filelist=clean_filelist).ids
        assert clean["now-check"] is not None
        assert not any(issue.startswith("journal-corrupt:")
                       for issue in clean["now-check"]), clean["now-check"]
        assert "now-input-newer" not in clean["now-check"], clean["now-check"]

        # Even with unchanged input bytes, tampering only with staged NOW must mismatch the marker.
        now_path = os.path.join(extracted, "state", "NOW.md")
        clean_now = open(now_path, encoding="utf-8").read()
        with open(now_path, "w", encoding="utf-8") as f:
            f.write(clean_now.replace("# NOW\n", "# NOW TAMPERED\n", 1))
        tampered = gate.measure(tree=extracted, filelist=clean_filelist).ids
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

        measured = gate.measure(tree=extracted, filelist=filelist).ids
        assert measured["now-check"] is not None
        assert "now-input-newer" in measured["now-check"], measured["now-check"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(extracted, ignore_errors=True)


# Fake codex/claude executable: checks the isolation contract, then answers like the model would,
# with the hook's nonce only when hooks run.
_FAKE_RUNTIME = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
root = pathlib.Path.cwd()
if os.environ.get("MOTTORI_INSTANCE") != str(root):
    raise SystemExit(31)
if "exec" in args:
    if any(key.upper().startswith(("CLAUDE_", "ANTHROPIC_")) for key in os.environ):
        raise SystemExit(34)
else:
    if os.environ.get("CLAUDE_PROJECT_DIR") != str(root):
        raise SystemExit(31)
    if any(key.upper().startswith(("OPENAI_", "CODEX_")) for key in os.environ):
        raise SystemExit(35)
if any(key.startswith("GIT_") and key != "GIT_TERMINAL_PROMPT" for key in os.environ):
    raise SystemExit(32)
if os.environ.get("CLAUDE_CODE_PLUGIN_DIRS") or os.environ.get("CLAUDE_CODE_SYNC_PLUGINS"):
    (root / "ambient-executed").write_text("plugin")
if "exec" in args:
    disabled = [args[i+1] for i, value in enumerate(args[:-1]) if value == "--disable"]
    if "--ignore-user-config" in args or "plugins" not in disabled or "apps" not in disabled or "mcp_servers={}" not in args:
        (root / "ambient-executed").write_text("connector")
    enabled = "hooks" not in disabled
else:
    required = ("--strict-mcp-config", "--disable-slash-commands", "--no-chrome")
    if not all(flag in args for flag in required) or args[args.index("--setting-sources")+1] != "project" or json.loads(args[args.index("--mcp-config")+1]) != {"mcpServers": {}} or args[args.index("--tools")+1] != "":
        (root / "ambient-executed").write_text("connector")
    enabled = "--safe-mode" not in args
# A broken runtime that still runs hooks in the hooks-off case.
if os.environ.get("FAKE_RUNTIME_IGNORES_HOOKS_OFF"):
    enabled = True
if os.environ.get("MOTTORI_HOOK_CANARY") in args[-1]:
    raise SystemExit(33)
value = subprocess.check_output([sys.executable, "hook.py"], text=True).strip() if enabled else "ABSENT"
if "exec" in args:
    print(json.dumps({"type":"item.completed", "item":{"type":"agent_message", "text":value}}))
else:
    print(json.dumps({"type":"system", "subtype":"init", "tools":[], "mcp_servers":[], "plugins":[]}))
    print(json.dumps({"type":"result", "is_error":False, "result":value}))
'''


def _write_fake_runtime(runtime):
    runtime.write_text(_FAKE_RUNTIME, encoding="utf-8")
    runtime.chmod(0o755)
    (runtime.parent / "hook.py").write_text(
        'import os\nprint(os.environ["MOTTORI_HOOK_CANARY"])\n', encoding="utf-8")


def test_canary_children_pin_instance_and_block_ambient_tools():
    """Exercise the wrapper contract with a fake runtime and ambient sentinel files."""
    from pathlib import Path
    from unittest.mock import patch
    import hook_canary

    with tempfile.TemporaryDirectory(prefix="hook-canary-isolation-") as temporary:
        root = Path(temporary)
        marker = root / "ambient-executed"
        runtime = root / "runtime"
        _write_fake_runtime(runtime)
        hostile = {
            "MOTTORI_INSTANCE": "/synthetic/unrelated",
            "CLAUDE_PROJECT_DIR": "/synthetic/unrelated",
            "GIT_DIR": "/synthetic/unrelated/.git",
            "GIT_INDEX_FILE": "/synthetic/unrelated/index",
            "CLAUDE_CODE_PLUGIN_DIRS": "/synthetic/ambient-plugin",
            "CLAUDE_CODE_SYNC_PLUGINS": "1",
            "CLAUDE_CODE_SYNC_SESSION_REFS": "1",
            "CLAUDE_CODE_SAFE_MODE": "1",
            "CLAUDE_CODE_OAUTH_TOKEN": "SYNTHETIC-CLAUDE-TOKEN",
            "ANTHROPIC_API_KEY": "SYNTHETIC-PROVIDER-TOKEN",
            "claude_fixture": "SYNTHETIC-LOWERCASE",
            "OPENAI_API_KEY": "SYNTHETIC-OPENAI-TOKEN",
            "CODEX_PROVIDER": "SYNTHETIC-CODEX-PROVIDER",
            "openai_fixture": "SYNTHETIC-LOWERCASE",
        }
        with patch.object(hook_canary, "ROOT", str(root)), \
                patch.object(hook_canary.shutil, "which", return_value=str(runtime)), \
                patch.object(hook_canary.claude_auth, "_read_token", return_value=None), \
                patch.dict(os.environ, hostile):
            for enabled, expected in ((True, "SYNTHETIC-NONCE"), (False, "ABSENT")):
                result = hook_canary._run("SYNTHETIC-NONCE", enabled)
                assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
                assert hook_canary.agent_messages(result.stdout) == ([expected], 0)
                result = hook_canary._run_claude("SYNTHETIC-NONCE", enabled)
                assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
                assert hook_canary.claude_messages(result.stdout) == (expected, 0, True)
            assert os.environ["MOTTORI_INSTANCE"] == hostile["MOTTORI_INSTANCE"]
        assert not marker.exists(), marker.read_text() if marker.exists() else ""


def test_canary_verdict_requires_hooks_off_absence():
    """Each canary passes only when the hooks-off run lacks the nonce."""
    import contextlib
    import io
    from pathlib import Path
    from unittest.mock import patch
    import hook_canary

    armed = {"hooks": [{"eventName": "sessionStart", "source": "project", "enabled": True,
                        "trustStatus": "trusted", "currentHash": "sha256:ok", "matcher": None,
                        "command": "echo ok"}]}
    with tempfile.TemporaryDirectory(prefix="hook-canary-verdict-") as temporary:
        root = Path(temporary)
        runtime = root / "runtime"
        _write_fake_runtime(runtime)
        with patch.object(hook_canary, "ROOT", str(root)), \
                patch.object(hook_canary.shutil, "which", return_value=str(runtime)), \
                patch.object(hook_canary.claude_auth, "_read_token", return_value=None), \
                patch.object(hook_canary.hookdiag, "codex_hooks_list", return_value=armed), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            assert hook_canary._codex_canary("SYNTHETIC-NONCE") is True
            assert hook_canary._claude_canary("SYNTHETIC-NONCE") is True
            with patch.dict(os.environ, {"FAKE_RUNTIME_IGNORES_HOOKS_OFF": "1"}):
                assert hook_canary._codex_canary("SYNTHETIC-NONCE") is False
                assert hook_canary._claude_canary("SYNTHETIC-NONCE") is False


def test_claude_canary_rejects_tools_plugins_and_missing_startup():
    import hook_canary

    init = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "plugins": []}
    result = {"type": "result", "is_error": False, "result": "SYNTHETIC-NONCE"}
    def stream(*events):
        return "\n".join(json.dumps(event) for event in events)

    assert hook_canary.claude_messages(stream(init, result)) == ("SYNTHETIC-NONCE", 0, True)
    padded = dict(result, result="SYNTHETIC-NONCE\n")
    assert hook_canary.claude_messages(stream(init, padded))[0] == "SYNTHETIC-NONCE"
    bundled = [{"name": name, "path": "builtin", "source": name + "@builtin"}
               for name in sorted(hook_canary.CLAUDE_BUILTIN_PLUGINS)]
    assert hook_canary.claude_messages(stream(dict(init, plugins=bundled), result))[2] is True
    for plugins in (None, {}, bundled + bundled, [{"name": []}],
                    [{"name": "unknown", "path": "builtin", "source": "unknown@builtin"}],
                    [dict(bundled[0], path="/configured/plugin")],
                    [dict(bundled[0], source="configured")]):
        assert hook_canary.claude_messages(stream(dict(init, plugins=plugins), result))[2] is False
    assert hook_canary.claude_messages(stream(result))[2] is False
    assert hook_canary.claude_messages(stream(init, init, result))[2] is False
    missing_plugins = {key: value for key, value in init.items() if key != "plugins"}
    assert hook_canary.claude_messages(stream(missing_plugins, result))[2] is False
    for key in ("tools", "mcp_servers", "plugins"):
        unsafe = dict(init, **{key: ["ambient"]})
        assert hook_canary.claude_messages(stream(unsafe, result))[2] is False
    tool = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__external"}]}}
    assert hook_canary.claude_messages(stream(init, tool, result))[1] == 1
    assert hook_canary.claude_messages(stream(init, dict(result, is_error=True)))[0] is None
    assert hook_canary.claude_messages(stream(init, result, dict(result, is_error=True)))[0] is None




def test_runtime_state_ignored():
    """Files hooks rewrite on every run must never show up as untracked in the workspace."""
    root = os.path.dirname(HERE)
    if subprocess.run(["git", "-C", root, "rev-parse", "--is-inside-work-tree"],
                      capture_output=True).returncode:
        return  # check-ignore needs a work tree; an exported copy without .git has nothing to ignore.
    for path in ("state/hook-canary.json", "state/.hook-errors.log", "state/.hook-errors.seen"):
        r = subprocess.run(["git", "-C", root, "check-ignore", "-q", "--no-index", path],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{path} is not git-ignored: {r.returncode} {r.stderr}"


TESTS = [
    test_canary_children_pin_instance_and_block_ambient_tools,
    test_canary_verdict_requires_hooks_off_absence,
    test_claude_canary_rejects_tools_plugins_and_missing_startup,
    test_capability_stages_do_not_collapse,
    test_gate_unit_rejects_current_only_checker_key,
    test_doctor_rejects_declared_hook_with_invalid_command,
    test_owner_lines_beside_the_kit_lines_never_fail_doctor,
    test_doctor_accepts_own_session_hook_beside_event_line,
    test_codex_trust_and_matcher_are_separate_stages,
    test_installer_check_is_read_only_and_repair_is_exact,
    test_installer_refuses_foreign_and_outside_hookspath,
    test_installer_uses_common_hooks_in_linked_worktree,
    test_installer_fixtures_ignore_global_hookspath,
    test_canary_parser_reads_only_agent_messages,
    test_all_canary_persists_runtime_results_without_nonce,
    test_hook_canary_rejects_unknown_flag,
    test_claude_canary_skips_negative_after_failed_positive,
    test_staged_python_syntax_checks_unicode_spaces_and_index_bytes,
    test_precommit_now_check_reads_extracted_index_tree,
    test_runtime_state_ignored,
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
