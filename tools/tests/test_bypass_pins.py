#!/usr/bin/env python3
"""Characterization pins for H1 and G2 gate/hook/worker bypass attacks.

These tests preserve the integrated behavior after W2-7 and W2-19. ``EXPECT_HOLE=True``
is attached to attacks that remain REVIEW or are waiting on a named dependency.

Known limit, not pinned: anyone who can replace .git/hooks/pre-commit disables the commit gate;
nothing on the machine detects it.
"""
import atexit
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch


HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
# Gate pins produce block verdicts. signals.py reads this variable once at import, so set it
# before gate or test_enforce is imported; fixture verdicts must never reach the real log.
os.environ["MOTTORI_SIGNALS_DIR"] = tempfile.mkdtemp(prefix="test-bypass-signals-")
atexit.register(shutil.rmtree, os.environ["MOTTORI_SIGNALS_DIR"], ignore_errors=True)
# Pins that need a kit-only suite record why they did not run, so the summary does not count
# them as passed.
SKIPPED = []


def hole(function):
    function.EXPECT_HOLE = True
    return function


def dependency_hole(reason):
    def decorate(function):
        function.EXPECT_HOLE = True
        function.EXPECT_HOLE_REASON = reason
        return function
    return decorate


def _repo():
    root = Path(tempfile.mkdtemp(prefix="bypass-pin-"))
    (root / "tools" / "lib").mkdir(parents=True)
    for name in ("lib/config.py", "lib/paths.py", "lib/runlog.py", "lib/safeio.py", "linkcheck.py"):
        shutil.copy2(HERE / name, root / "tools" / name)
    (root / "instance").mkdir()
    # The kit stores config in templates/; an installed instance stores it in system/
    # (the same rule used by test_coherence).
    source = next(p for p in (ROOT / "templates" / "config.json",
                              ROOT / "instance" / "config.json") if p.is_file())
    cfg = json.loads(source.read_text(encoding="utf-8"))
    cfg["instance"] = {"name": "pin"}
    cfg["tracks"], cfg["threads"] = [], []
    (root / "instance" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / ".gitignore").write_text("_private/\nstate/\ninstance/config.json\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "pin@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Pin"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init", "--allow-empty"], cwd=root, check=True)
    return root


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _linkcheck(root, *extra):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "tools/linkcheck.py", *extra], cwd=root, env=env,
                          capture_output=True, text=True)


def _broken_source_pin(filename="README.md"):
    root = _repo()
    try:
        _write(root, filename, "[bad](missing.md)\n")
        subprocess.run(["git", "add", filename], cwd=root, check=True)
        return _linkcheck(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_h1_g01_space_filename_blocked():
    result = _broken_source_pin("space name.md")
    assert result.returncode == 1 and "missing.md" in result.stdout


def test_h1_g02_unicode_filename_blocked_at_commit_boundary():
    import test_enforce
    test_enforce.test_G02_unicode_markdown_path_is_not_git_quoted()


def test_h1_g03_symlink_markdown_source_blocked():
    import test_enforce
    test_enforce.test_G03_markdown_symlink_is_blocked()


def test_h1_g04_submodule_gitlink_blocked():
    import test_enforce
    test_enforce.test_G04_submodule_gitlink_is_blocked()


def test_h1_g05_g06_g07_extracted_index_tree_rejects_broken_link():
    """G05 (commit -a), G06 (git apply) and G07 (direct index blob) all reach precommit, which
    extracts the index with checkout-index; one check of linkcheck on an extracted tree pins the
    shared mechanism."""
    root = _repo()
    tree = Path(tempfile.mkdtemp(prefix="bypass-tree-"))
    try:
        _write(tree, "README.md", "[bad](missing-index.md)\n")
        filelist = tree / "files.txt"
        filelist.write_text("README.md\n", encoding="utf-8")
        result = _linkcheck(root, "--tree", str(tree), "--filelist", str(filelist))
        assert result.returncode == 1 and "missing-index.md" in result.stdout
    finally:
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_h1_g09_precommit_unsets_instance_override():
    text = (HERE / "lib" / "precommit-hook.sh").read_text(encoding="utf-8")
    assert "unset MOTTORI_INSTANCE" in text
    assert text.index("unset MOTTORI_INSTANCE") < text.index('exec python3 "$ROOT/tools/gate.py"')


def test_h1_g11_absent_baseline_blocks():
    """A set-up instance whose baseline is gone blocks: deleting the file must not open the gate.
    A folder that was never set up has no baseline by construction, and a turn there passes."""
    import gate
    from unittest.mock import patch
    measured = gate.Measurement({"linkcheck": set()})
    with patch.object(gate.C, "not_set_up", lambda: False):
        reason, advance = gate._verdict(measured, {}, "absent")
        assert reason == gate.BASELINE_ABSENT and advance is False
    with patch.object(gate.C, "not_set_up", lambda: True):
        assert gate._verdict(measured, {}, "absent") == (None, False)


def _scope_root():
    root = Path(tempfile.mkdtemp(prefix="bypass-scope-"))
    (root / "allowed").mkdir()
    return root


def test_h1_w01_hardlink_alias_blocked():
    import worker_sandbox as sandbox
    root = _scope_root()
    fd, name = tempfile.mkstemp(prefix="bypass-hardlink-")
    os.close(fd)
    outside = Path(name)
    try:
        alias = root / "allowed" / "alias.txt"
        os.link(outside, alias)
        snap = sandbox.snapshot(str(root))
        report = sandbox.scope_report(["allowed"], snap, snap, 0, root=str(root))
        assert report["status"] == "scope_violation" and "hardlink" in str(report["violations"])
    finally:
        outside.unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def test_h1_w02_symlink_escape_blocked():
    import worker_sandbox as sandbox
    root = _scope_root()
    fd, name = tempfile.mkstemp(prefix="bypass-symlink-")
    os.close(fd)
    outside = Path(name)
    try:
        os.symlink(outside, root / "allowed" / "door")
        snap = sandbox.snapshot(str(root))
        report = sandbox.scope_report(["allowed"], snap, snap, 0, root=str(root))
        assert report["status"] == "scope_violation" and "symlink" in str(report["violations"])
    finally:
        outside.unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def test_h1_w03_case_spelling_does_not_escape_scope():
    import worker_sandbox as sandbox
    root = _scope_root()
    try:
        normalized = sandbox.normalize_prefix("ALLOWED", root=str(root))
        assert normalized in {"ALLOWED", "allowed"} and ".." not in normalized
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_h1_w04_parent_prefix_blocked():
    import worker_sandbox as sandbox
    root = _scope_root()
    try:
        try:
            sandbox.normalize_prefix("../escape", root=str(root))
        except sandbox.InputError:
            pass
        else:
            raise AssertionError("parent prefix accepted")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_h1_w07_write_outside_declared_prefix_is_violation():
    """W07: a write outside the declared prefix, from the worker or a concurrent writer, is a
    scope violation."""
    import worker_sandbox as sandbox
    root = _scope_root()
    try:
        before = sandbox.snapshot(str(root))
        _write(root, "README.md", "concurrent")
        after = sandbox.snapshot(str(root))
        report = sandbox.scope_report(["allowed"], before, after, 0, root=str(root))
        assert report["status"] == "scope_violation"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_h1_w08_declared_prefix_violation_is_report_only():
    import test_fresh_worker
    test_fresh_worker.test_scope_violation_is_report_only_without_strict()


def test_h1_h01_missing_gate_command_is_logged():
    """Every gate hook leaves a timestamped line and the stderr in state/.hook-errors.log, and
    still runs and exits 0 when state/ is missing or read-only."""
    hooks = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
    # Each line runs the dispatcher, whose gate step fails: the copy has no gate.py.
    commands = [hook["command"] for event in ("Stop", "PostToolUse", "UserPromptSubmit")
                for block in hooks[event] for hook in block["hooks"]
                if f"event {event} claude" in hook["command"]]
    assert len(commands) == 3, commands
    for command in commands:
        for state in ("writable", "absent", "read-only"):
            project = Path(tempfile.mkdtemp(prefix="bypass-missing-gate-"))
            try:
                (project / "tools").mkdir()
                shutil.copy2(HERE / "hook.sh", project / "tools" / "hook.sh")
                shutil.copy2(HERE / "dispatch.py", project / "tools" / "dispatch.py")
                if state != "absent":
                    (project / "state").mkdir()
                if state == "read-only":
                    (project / "state").chmod(0o555)
                result = subprocess.run(["bash", "-c", command], input="{}",
                                        env=dict(os.environ, CLAUDE_PROJECT_DIR=str(project)),
                                        capture_output=True, text=True)
                assert result.returncode == 0, (command, state, result.stderr)
                if state == "writable":
                    log = (project / "state" / ".hook-errors.log").read_text(encoding="utf-8")
                    assert "No module named 'gate'" in log and "hook failed" in log, (command, log)
                else:
                    # The tool still ran: its own error reaches the inherited stderr.
                    assert "No module named 'gate'" in result.stderr and "hook-errors" not in result.stderr, (
                        command, state, result.stderr)
            finally:
                if (project / "state").exists():
                    (project / "state").chmod(0o755)
                shutil.rmtree(project, ignore_errors=True)


def test_h1_h01b_session_hooks_log_stderr():
    """SessionStart and PreCompact hooks in both runtimes keep stderr in state/.hook-errors.log.

    A crashing reminder hook or state injector must leave a trace instead of being discarded, so
    the owner can learn why reminders or state did not appear. Both tools are replaced by stubs
    that fail: the real reminder hook skips unreadable rows and exits 0, so a corrupt store no
    longer reaches this log.
    """
    for rel in ((".claude", "settings.json"), (".codex", "hooks.json")):
        hooks = json.loads((ROOT.joinpath(*rel)).read_text(encoding="utf-8"))["hooks"]
        commands = [hook["command"] for event in ("SessionStart", "PreCompact")
                    for block in hooks[event] for hook in block["hooks"]]
        # Both runtimes declare one event line each.
        assert len(commands) == 2, (rel, commands)
        for command in commands:
            project = Path(tempfile.mkdtemp(prefix="bypass-session-hook-"))
            try:
                (project / "state").mkdir()
                (project / "tools").mkdir()
                shutil.copy2(HERE / "hook.sh", project / "tools" / "hook.sh")
                shutil.copy2(HERE / "dispatch.py", project / "tools" / "dispatch.py")
                # Each stub also names the instance override it sees: a hook must not inherit one.
                for tool, marker in (("triggers.py", "triggers-hook-crashed"),
                                     ("now.py", "now-injector-crashed")):
                    (project / "tools" / tool).write_text(
                        "import os, sys\n"
                        f"sys.stderr.write('{marker} instance=%s\\n' % os.environ.get('MOTTORI_INSTANCE'))\n"
                        "sys.exit(3)\n", encoding="utf-8")
                subprocess.run(["git", "init", "-q"], cwd=project, check=True)
                env = dict(os.environ, MOTTORI_INSTANCE=str(project / "other-instance"))
                env["CLAUDE_PROJECT_DIR"] = str(project)
                # As in a real session: a doctor probe's flag would skip the reminder step.
                env.pop("MOTTORI_INTERNAL_RUN", None)
                subprocess.run(["bash", "-c", command], input="{}", cwd=project, env=env,
                               capture_output=True, text=True)
                log_path = project / "state" / ".hook-errors.log"
                log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
                start = "event SessionStart" in command
                markers = (["triggers-hook-crashed"] if start or "triggers.py" in command else []) + (
                    ["now-injector-crashed"] if start or "now.py" in command or "event PreCompact" in command
                    else [])
                for marker in markers:
                    assert marker + " instance=None" in log, (rel, command, log)
                # The timestamped line is what doctor and the session notice count.
                import runlog
                assert runlog.hook_error_entries(log) and "hook failed" in log, (rel, command, log)
            finally:
                shutil.rmtree(project, ignore_errors=True)


def test_h1_h02_malformed_stop_payload_blocks_when_dirty():
    import gate
    old_stdin, old_measure, old_load, old_root = sys.stdin, gate.measure, gate._load_baseline, gate._root_ok
    old_dirty, old_pending, old_log = gate.EDITS, gate.PENDING, gate.runlog.log_run
    old_lock = gate.LOCK
    # The real lock lives in the instance git dir; a live Stop hook holding it would stall this
    # test, so the test must never touch it.
    real_lock = gate.LOCK()
    lock_before = os.stat(real_lock).st_mtime_ns if os.path.exists(real_lock) else None
    with tempfile.TemporaryDirectory(prefix="bypass-gate-") as td:
        try:
            gate.EDITS = lambda: os.path.join(td, "dirty")
            gate.PENDING = lambda: os.path.join(td, "pending")
            gate.LOCK = lambda: os.path.join(td, "lock")
            Path(gate.EDITS()).write_text("x", encoding="utf-8")
            gate.measure = lambda **_: gate.Measurement({"linkcheck": {"new"}})
            gate._load_baseline = lambda: ({"linkcheck": set()}, "ok")
            gate._root_ok = lambda: True
            gate.runlog.log_run = lambda *a, **k: None
            sys.stdin = io.StringIO("not-json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), patch.object(sys, "argv", ["gate.py", "check"]):
                assert gate.main() == 0
            assert json.loads(out.getvalue())["decision"] == "block"
            # The catch-all handler also blocks, so only the pending text shows that the block
            # came from the measured new issue and not from a crash on the malformed payload.
            pending = Path(gate.PENDING()).read_text(encoding="utf-8")
            assert gate.SELF_FAILED.format(error_type="JSONDecodeError") not in pending, pending
        finally:
            sys.stdin, gate.measure, gate._load_baseline, gate._root_ok = old_stdin, old_measure, old_load, old_root
            gate.EDITS, gate.PENDING, gate.runlog.log_run = old_dirty, old_pending, old_log
            gate.LOCK = old_lock
    lock_after = os.stat(real_lock).st_mtime_ns if os.path.exists(real_lock) else None
    assert lock_after == lock_before, "test touched the instance gate lock"


def test_h1_h03_h04_stop_hook_active_passes_once_and_keeps_pending():
    """H03 (boolean stop_hook_active passes once) and H04 (string "false" still blocks)."""
    import test_enforce
    test_enforce.test_H03_H04_stop_hook_active_passes_once_and_keeps_pending()


def test_h1_h05_sessionstart_failure_has_json_fallback():
    """With the launcher present and the dispatcher failing, session start gets the fallback."""
    command = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))[
        "hooks"]["SessionStart"][0]["hooks"][0]["command"]
    project = Path(tempfile.mkdtemp(prefix="bypass-no-dispatcher-"))
    try:
        (project / "tools").mkdir()
        shutil.copy2(HERE / "hook.sh", project / "tools" / "hook.sh")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
        result = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True)
    finally:
        shutil.rmtree(project, ignore_errors=True)
    payload = json.loads(result.stdout)
    assert result.returncode == 0 and "unavailable" in payload["hookSpecificOutput"]["additionalContext"]


def test_h1_h06_delivery_check_needs_only_its_config():
    """The delivery check is a step of the Stop event, so no hook line has to be pasted for it;
    without a signal in the config it runs cleanly and answers nothing."""
    import dispatch
    import turns
    from unittest.mock import patch
    settings = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "deliver.py" not in settings
    assert "deliver" in [step.id for step in dispatch.steps("Stop", "claude")]
    # Run the Stop event with its delivery step alone: the gate would judge this checkout.
    deliver_step = [step for step in dispatch.STEPS["Stop"] if step[0] == "deliver"]
    # Without the block stamp: a test must not write into this checkout's Git folder.
    with patch.dict(dispatch.STEPS, {"Stop": deliver_step}), \
            patch.object(turns, "block_once", lambda *args: args[-1]), \
            contextlib.redirect_stderr(io.StringIO()) as err:
        assert dispatch.run("claude", "Stop", {"session_id": "s"}) == ("", 0)
    assert not err.getvalue(), err.getvalue()


def _forged_repo():
    root = Path(tempfile.mkdtemp(prefix="bypass-forged-"))
    (root / "tools").mkdir()
    # state/ makes the forged repository look like an installed instance, so a pin cannot pass
    # because a hook treated the folder as not set up.
    (root / "state").mkdir()
    # A forged repository can ship its own launcher, so the pins below copy the real one.
    shutil.copy2(HERE / "hook.sh", root / "tools" / "hook.sh")
    shutil.copy2(HERE / "dispatch.py", root / "tools" / "dispatch.py")
    # Run as a script (the Codex line) or called by the dispatcher (the Claude Code line).
    (root / "tools" / "now.py").write_text(
        "def session_state():\n"
        "    return 'FORGED SESSION STATE'\n"
        "def hook_context():\n"
        '    print(\'{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"FORGED SESSION STATE"}}\')\n'
        "if __name__ == '__main__':\n"
        "    hook_context()\n",
        encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@hole
def test_h1_s01_claude_project_root_currently_trusts_forged_repo():
    root = _forged_repo()
    try:
        command = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))[
            "hooks"]["SessionStart"][0]["hooks"][0]["command"]
        result = subprocess.run(["bash", "-c", command], cwd=root,
                                env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)),
                                capture_output=True, text=True)
        assert "FORGED SESSION STATE" in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


@hole
def test_h1_s02_codex_current_repo_currently_trusts_forged_repo():
    root = _forged_repo()
    try:
        command = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))[
            "hooks"]["SessionStart"][0]["hooks"][0]["command"]
        result = subprocess.run(["bash", "-c", command], cwd=root, capture_output=True, text=True)
        assert "FORGED SESSION STATE" in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


@hole
def test_h1_s03_canary_currently_accepts_arbitrary_context_text():
    source = (HERE / "now.py").read_text(encoding="utf-8")
    assert 'canary = os.environ.get("MOTTORI_HOOK_CANARY")' in source
    assert 'f"HOOK_CANARY:{canary}\\n"' in source


@dependency_hole("open: the planned W2-18 seal for additions to HANGUL_ALLOWED in tools/tests/test_language.py was withdrawn with the approval ledger (KIT-DR-032); no seal is planned")
def test_g2_n1_allowlist_addition_currently_skips_language_check():
    if not (ROOT / "tools" / "tests" / "test_language.py").is_file():
        SKIPPED.append("kit-only suite test_language absent (installed instance)")
        return
    import test_language
    with tempfile.TemporaryDirectory(prefix="g2-n1-language-") as tmp:
        root = Path(tmp)
        _write(root, ".github/workflows/gates.yml", "# 신규 한국어 우회\n")
        matching = [issue for issue in test_language.language_issues(root, frozenset({".github/workflows/gates.yml"}))
                    if ".github/workflows/gates.yml" in issue]
        assert matching == []


def test_g2_n3_gitignore_change_cannot_allow_new_instance_path():
    import test_enforce
    test_enforce.test_N3_gitignore_exception_cannot_allow_new_instance_paths()


def test_g2_n5_allow_prefix_cannot_empty_deny_policy():
    import test_egress
    test_egress.test_N5_allow_prefix_must_be_strictly_below_every_overlapping_deny()
    test_egress.test_N5_invalid_overlap_stops_fresh_worker_before_runtime()


TESTS = tuple(value for name, value in sorted(globals().items())
              if name.startswith(("test_h1_", "test_g2_")) and callable(value))


def main():
    failed = []
    skipped = 0
    holes = 0
    for test in TESTS:
        expected_hole = bool(getattr(test, "EXPECT_HOLE", False))
        holes += int(expected_hole)
        try:
            before = len(SKIPPED)
            test()
            if len(SKIPPED) > before:
                skipped += 1
                print(f"SKIP {test.__name__}: not applicable here: {SKIPPED[-1]}")
                continue
            reason = getattr(test, "EXPECT_HOLE_REASON", None)
            suffix = f" reason={reason}" if reason else ""
            print(f"PASS {test.__name__} EXPECT_HOLE={expected_hole}{suffix}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    ran = len(TESTS) - skipped
    print(f"bypass pins: {ran - len(failed)}/{ran} passed, not applicable {skipped}, "
          f"EXPECT_HOLE {holes}")
    assert len(TESTS) == 25, len(TESTS)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
