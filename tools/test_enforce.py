#!/usr/bin/env python3
"""Test fail-closed gate controls and Git egress boundaries."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, text=True, capture_output=True,
    )


def _repo(context: str = "personal") -> Path:
    root = Path(tempfile.mkdtemp(prefix="enforce-fixture-"))
    (root / "tools").mkdir()
    for name in ("enforce.py", "i18n.py"):
        shutil.copy2(HERE / name, root / "tools" / name)
    (root / "system").mkdir()
    (root / "system" / "memory-config.json").write_text(json.dumps({
        "schema_version": 4,
        "instance": {"name": "fixture", "context": context, "remote_allowlist": []},
    }), encoding="utf-8")
    (root / "system" / "instance-rules.md").write_text(
        "# instance\n\n국경: fixture only\n", encoding="utf-8"
    )
    (root / ".gitignore").write_text(
        "/state/\n/_private/\n/system/memory-config.json\n/system/instance-rules.md\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("ok\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=fixture", "-c", "user.email=f@example.invalid",
         "commit", "-qm", "initial")
    return root


def _issues(root: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    run = subprocess.run(
        [sys.executable, str(root / "tools" / "enforce.py"), "--issues", *args],
        cwd=root, text=True, capture_output=True,
    )
    lines = run.stdout.splitlines()
    assert lines and lines[-1].startswith("#issues "), (run.stdout, run.stderr)
    return run, [line.split("\t", 1)[0] for line in lines[:-1]]


def test_G03_markdown_symlink_is_blocked() -> None:
    root = _repo()
    try:
        made = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"], cwd=root,
            input="missing.md", text=True, capture_output=True, check=True,
        )
        _git(root, "update-index", "--add", "--cacheinfo", f"120000,{made.stdout.strip()},linked.md")
        run, issues = _issues(root, "--index")
        assert run.returncode == 0 and "index-markdown-symlink:linked.md" in issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_G04_submodule_gitlink_is_blocked() -> None:
    root = _repo()
    try:
        commit = _git(root, "rev-parse", "HEAD").stdout.strip()
        _git(root, "update-index", "--add", "--cacheinfo", f"160000,{commit},vendor/child")
        _, issues = _issues(root, "--index")
        assert "index-submodule:vendor/child" in issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_G02_unicode_markdown_path_is_not_git_quoted() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    previous = gate.M.ROOT
    try:
        path = root / "감사 문서.md"
        path.write_text("[bad](없는-대상.md)\n", encoding="utf-8")
        _git(root, "add", "-f", path.name)
        gate.M.ROOT = str(root)
        assert gate._staged_markdown_paths() == ["README.md", "감사 문서.md"]
    finally:
        gate.M.ROOT = previous
        shutil.rmtree(root, ignore_errors=True)


def test_G10_signed_baseline_rejects_direct_mutation() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = Path(tempfile.mkdtemp(prefix="baseline-signature-"))
    old_baseline, old_key = gate.BASELINE, gate.SIGNING_KEY
    try:
        gate.BASELINE = str(root / "baseline.json")
        key = root / "key"
        key.write_bytes(b"k" * 32)
        gate.SIGNING_KEY = lambda: str(key)
        gate._save_baseline({"linkcheck": {"known"}})
        document = json.loads(Path(gate.BASELINE).read_text(encoding="utf-8"))
        document["issues"]["linkcheck"].append("forged")
        Path(gate.BASELINE).write_text(json.dumps(document), encoding="utf-8")
        _baseline, state = gate._load_baseline()
        assert state == "corrupt"
    finally:
        gate.BASELINE = old_baseline
        gate.SIGNING_KEY = old_key
        shutil.rmtree(root, ignore_errors=True)


def test_G12_sealed_baseline_refuses_staged_recreation() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    old_root, old_root_ok, old_key = gate.M.ROOT, gate._root_ok, gate.SIGNING_KEY
    try:
        (root / "README.md").write_text("broken\n", encoding="utf-8")
        _git(root, "add", "README.md")
        key = root / ".git" / "mottori-gate-key"
        key.write_bytes(b"k" * 32)
        gate.M.ROOT = str(root)
        gate._root_ok = lambda: True
        gate.SIGNING_KEY = lambda: str(key)
        assert gate.cmd_baseline() != 0
    finally:
        gate.M.ROOT = old_root
        gate._root_ok = old_root_ok
        gate.SIGNING_KEY = old_key
        shutil.rmtree(root, ignore_errors=True)


def test_S2_G1_G2_force_add_and_work_tracked_changes_are_blocked() -> None:
    root = _repo("work")
    try:
        (root / "state").mkdir()
        (root / "state" / "NOW.md").write_text("secret\n", encoding="utf-8")
        _git(root, "add", "-f", "state/NOW.md")
        (root / "README.md").write_text("company data\n", encoding="utf-8")
        _git(root, "add", "README.md")
        _, issues = _issues(root, "--index")
        assert "forbidden-index-path:state/NOW.md" in issues
        assert "work-local-change:README.md" in issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tracked_public_state_is_not_forbidden() -> None:
    """Personal instances may track public state; the _private/ tree is always forbidden."""
    root = _repo("personal")
    try:
        (root / ".gitignore").write_text("/_private/\n", encoding="utf-8")
        (root / "state").mkdir()
        (root / "state" / "NOW.md").write_text("# NOW\n", encoding="utf-8")
        (root / "system" / "decisions.md").write_text("# DR\n", encoding="utf-8")
        _git(root, "add", ".gitignore", "state/NOW.md", "system/decisions.md", "system/memory-config.json")
        _git(root, "-c", "user.name=fixture", "-c", "user.email=f@example.invalid",
             "commit", "-qm", "track public instance files")
        (root / "state" / "NOW.md").write_text("# NOW\n\nupdated\n", encoding="utf-8")
        (root / "system" / "decisions.md").write_text("# DR\n\nupdated\n", encoding="utf-8")
        _git(root, "add", "state/NOW.md", "system/decisions.md")
        (root / "_private").mkdir()
        (root / "_private" / "x.md").write_text("secret\n", encoding="utf-8")
        _git(root, "add", "-f", "_private/x.md")
        _, issues = _issues(root, "--index")
        assert "forbidden-index-path:state/NOW.md" not in issues, issues
        assert "forbidden-index-path:system/decisions.md" not in issues, issues
        assert "forbidden-index-path:system/memory-config.json" not in issues, issues
        assert "forbidden-index-path:_private/x.md" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_N3_gitignore_exception_cannot_allow_new_instance_paths() -> None:
    """Changing .gitignore cannot make a path absent from HEAD safe to stage."""
    root = _repo("personal")
    try:
        with (root / ".gitignore").open("a", encoding="utf-8") as ignore:
            ignore.write("\n!/state/leak.bin\n!/system/decisions.md\n")
        (root / "state").mkdir()
        (root / "state" / "leak.bin").write_bytes(b"\x00\x01\x02\x03")
        (root / "system" / "decisions.md").write_text("new instance file\n", encoding="utf-8")
        _git(root, "add", ".gitignore", "system/decisions.md")
        _git(root, "add", "-f", "state/leak.bin")
        _, issues = _issues(root, "--index")
        assert "forbidden-index-path:state/leak.bin" in issues, issues
        assert "forbidden-index-path:system/decisions.md" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_N6_sealed_baseline_requires_explicit_adoption_and_records_it() -> None:
    """A sealed baseline accepts new IDs only from a control-plane approval artifact."""
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    baseline = root / "state" / ".gate-baseline.json"
    baseline.parent.mkdir(exist_ok=True)
    key = root / ".git" / "mottori-gate-key"
    key.write_bytes(b"k" * 32)
    original = {
        "root": gate.M.ROOT,
        "baseline": gate.BASELINE,
        "key": gate.SIGNING_KEY,
        "approval": gate.APPROVAL,
        "root_ok": gate._root_ok,
        "measure": gate.measure,
        "pending": gate.PENDING,
        "lock": gate.LOCK,
    }
    try:
        gate.M.ROOT = str(root)
        gate.BASELINE = str(baseline)
        gate.SIGNING_KEY = lambda: str(key)
        approval = root / ".git" / "mottori-gate-adoption-approval.json"
        gate.APPROVAL = lambda: str(approval)
        gate._root_ok = lambda: True
        gate.PENDING = lambda: str(root / ".git" / "pending")
        gate.LOCK = lambda: str(root / ".git" / "lock")
        gate._save_baseline({"linkcheck": {"known"}})
        gate.measure = lambda **_: {"linkcheck": {"known", "new-n6-a", "new-n6-b"}}

        assert gate.cmd_baseline() != 0
        saved, state = gate._load_baseline()
        assert state == "ok" and saved == {"linkcheck": {"known"}}
        previous_argv = sys.argv
        try:
            sys.argv = ["gate.py", "baseline", "--adopt", "linkcheck:new-n6-a"]
            assert gate.main() == 2, "baseline must not accept adoption authority inline"
        finally:
            sys.argv = previous_argv

        assert gate.cmd_approve_adoption(["linkcheck:new-n6-a"]) != 0
        assert not approval.exists()
        assert gate.cmd_approve_adoption(
            ["linkcheck:new-n6-a", "linkcheck:new-n6-b"]
        ) == 0
        document = json.loads(approval.read_text(encoding="utf-8"))
        assert document["baseline_sha256"] == gate._file_sha256(gate.BASELINE)
        assert document["target_issues_sha256"] == gate._issues_sha256(gate.measure())
        assert document["adoptions"] == [
            {"checker": "linkcheck", "issue_id": "new-n6-a"},
            {"checker": "linkcheck", "issue_id": "new-n6-b"},
        ]

        forged = approval.read_text(encoding="utf-8")
        document["adoptions"][0]["issue_id"] = "forged"
        approval.write_text(json.dumps(document), encoding="utf-8")
        assert gate.cmd_baseline() != 0
        approval.write_text(forged, encoding="utf-8")

        assert gate.cmd_baseline() == 0
        saved, state = gate._load_baseline()
        assert state == "ok" and saved == {"linkcheck": {"known", "new-n6-a", "new-n6-b"}}
        document = json.loads(baseline.read_text(encoding="utf-8"))
        assert document["schema_version"] == 3
        assert document["adoptions"][-1]["checker"] == "linkcheck"
        assert [row["issue_id"] for row in document["adoptions"][-2:]] == ["new-n6-a", "new-n6-b"]
        sealed = baseline.read_text(encoding="utf-8")
        document["adoptions"][-1]["issue_id"] = "forged"
        baseline.write_text(json.dumps(document), encoding="utf-8")
        _saved, state = gate._load_baseline()
        assert state == "corrupt"
        baseline.write_text(sealed, encoding="utf-8")

        gate.measure = lambda **_: {"linkcheck": {"known", "new-n6-a", "new-n6-b", "new-n6-c"}}
        assert gate.cmd_baseline() != 0, "approval must be bound to the previous baseline and target set"

        gate.measure = lambda **_: {"linkcheck": {"known"}}
        assert gate.cmd_baseline() == 0
        document = json.loads(baseline.read_text(encoding="utf-8"))
        assert document["adoptions"][-1]["issue_id"] == "new-n6-b"
    finally:
        gate.M.ROOT = original["root"]
        gate.BASELINE = original["baseline"]
        gate.SIGNING_KEY = original["key"]
        gate.APPROVAL = original["approval"]
        gate._root_ok = original["root_ok"]
        gate.measure = original["measure"]
        gate.PENDING = original["pending"]
        gate.LOCK = original["lock"]
        shutil.rmtree(root, ignore_errors=True)


def test_N6_adoption_approval_lives_in_git_control_plane() -> None:
    """The approval path is derived from the Git control plane, not the worktree."""
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    previous = gate.M.ROOT
    try:
        gate.M.ROOT = str(root)
        assert Path(gate.APPROVAL()).parent == root / ".git"
    finally:
        gate.M.ROOT = previous
        shutil.rmtree(root, ignore_errors=True)


def test_N6_baseline_refuses_when_control_plane_lock_is_unavailable() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    baseline = root / "state" / ".gate-baseline.json"
    baseline.parent.mkdir(exist_ok=True)
    key = root / ".git" / "mottori-gate-key"
    key.write_bytes(b"k" * 32)
    original = (gate.M.ROOT, gate.BASELINE, gate.SIGNING_KEY, gate._root_ok,
                gate.measure, gate.PENDING, gate._lock)

    @contextlib.contextmanager
    def unavailable_lock(timeout=150):
        yield False

    try:
        gate.M.ROOT = str(root)
        gate.BASELINE = str(baseline)
        gate.SIGNING_KEY = lambda: str(key)
        gate._root_ok = lambda: True
        gate.PENDING = lambda: str(root / ".git" / "pending")
        gate._save_baseline({"linkcheck": {"known", "removed"}})
        gate.measure = lambda **_: {"linkcheck": {"known"}}
        gate._lock = unavailable_lock
        assert gate.cmd_baseline() != 0
        saved, state = gate._load_baseline()
        assert state == "ok" and saved == {"linkcheck": {"known", "removed"}}
    finally:
        (gate.M.ROOT, gate.BASELINE, gate.SIGNING_KEY, gate._root_ok,
         gate.measure, gate.PENDING, gate._lock) = original
        shutil.rmtree(root, ignore_errors=True)


def test_N6_first_sealed_baseline_is_the_only_implicit_adoption() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    baseline = root / "state" / ".gate-baseline.json"
    baseline.parent.mkdir(exist_ok=True)
    key = root / ".git" / "mottori-gate-key"
    key.write_bytes(b"k" * 32)
    original = (gate.M.ROOT, gate.BASELINE, gate.SIGNING_KEY, gate._root_ok,
                gate.measure, gate.PENDING, gate.LOCK)
    try:
        gate.M.ROOT = str(root)
        gate.BASELINE = str(baseline)
        gate.SIGNING_KEY = lambda: str(key)
        gate._root_ok = lambda: True
        gate.measure = lambda **_: {"linkcheck": {"first-install-issue"}}
        gate.PENDING = lambda: str(root / ".git" / "pending")
        gate.LOCK = lambda: str(root / ".git" / "lock")
        assert gate.cmd_baseline() == 0
        saved, state = gate._load_baseline()
        assert state == "ok" and saved["linkcheck"] == {"first-install-issue"}
    finally:
        (gate.M.ROOT, gate.BASELINE, gate.SIGNING_KEY, gate._root_ok,
         gate.measure, gate.PENDING, gate.LOCK) = original
        shutil.rmtree(root, ignore_errors=True)


def test_tracked_markdown_symlink_in_head_is_not_reflagged() -> None:
    """A .md symlink already in HEAD is not reflagged, but a newly staged symlink is."""
    root = _repo()
    try:
        made = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"], cwd=root,
            input="missing.md", text=True, capture_output=True, check=True,
        )
        _git(root, "update-index", "--add", "--cacheinfo", f"120000,{made.stdout.strip()},old.md")
        _git(root, "-c", "user.name=fixture", "-c", "user.email=f@example.invalid",
             "commit", "-qm", "legacy symlink")
        (root / "README.md").write_text("changed\n", encoding="utf-8")
        _git(root, "add", "README.md")
        _, issues = _issues(root, "--index")
        assert "index-markdown-symlink:old.md" not in issues, issues
        _git(root, "update-index", "--add", "--cacheinfo", f"120000,{made.stdout.strip()},new.md")
        _, issues = _issues(root, "--index")
        assert "index-markdown-symlink:new.md" in issues, issues
        assert "index-markdown-symlink:old.md" not in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_prepush_allows_presetup_kit_tree_and_blocks_unknown_context() -> None:
    """Allow a pre-setup kit tree explicitly; block other cases that cannot be classified."""
    root = _repo("personal")
    try:
        (root / "system" / "memory-config.json").unlink()
        blocked = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
                                 cwd=root, text=True, capture_output=True,
                                 env=dict(os.environ, MOTTORI_LANG="ko"))
        assert blocked.returncode != 0 and "판정할 수 없다" in blocked.stderr, blocked.stderr
        (root / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (root / "templates").mkdir()
        (root / "templates" / "memory-config.json").write_text("{}", encoding="utf-8")
        allowed = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
                                 cwd=root, text=True, capture_output=True)
        assert allowed.returncode == 0 and "pre-setup kit tree" in allowed.stdout, allowed.stdout + allowed.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_S2_G4_work_push_is_hard_blocked() -> None:
    root = _repo("work")
    try:
        run = subprocess.run(
            [sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
            cwd=root, text=True, capture_output=True,
        )
        assert run.returncode != 0 and "work" in (run.stdout + run.stderr).lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_S2_G5_ready_rejects_missing_context_and_template_rules() -> None:
    root = _repo()
    try:
        (root / "system" / "memory-config.json").write_text(
            json.dumps({"schema_version": 4, "instance": {"name": "fixture"}}),
            encoding="utf-8",
        )
        (root / "system" / "instance-rules.md").write_text("CHANGEME\n", encoding="utf-8")
        run = subprocess.run(
            [sys.executable, str(root / "tools" / "enforce.py"), "ready"],
            cwd=root, text=True, capture_output=True,
        )
        assert run.returncode != 0
        assert "context" in (run.stdout + run.stderr) and "CHANGEME" in (run.stdout + run.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_W09_strict_scope_requires_a_prefix() -> None:
    spec = importlib.util.spec_from_file_location("fresh_worker_enforce_test", HERE / "fresh_worker.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    try:
        module.run("codex", "unused", strict_scope=True)
    except module.InputError as error:
        assert "write-prefix" in str(error)
    else:
        raise AssertionError("--strict-scope without --write-prefix must fail before dispatch")


def test_enforce_messages_follow_language_and_survive_without_catalog() -> None:
    """English output has no Hangul, and a missing i18n.py still yields the English text."""
    root = _repo("personal")
    try:
        (root / "system" / "memory-config.json").unlink()
        enforce = str(root / "tools" / "enforce.py")

        def prepush(lang: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run([sys.executable, enforce, "prepush"], cwd=root, text=True,
                                  capture_output=True, env=dict(os.environ, MOTTORI_LANG=lang))

        english = prepush("en")
        assert english.returncode != 0
        assert "push blocked: cannot determine instance.context" in english.stderr, english.stderr
        assert not re.search("[가-힣]", english.stdout + english.stderr), english.stderr
        hook = subprocess.run([sys.executable, enforce, "hook", "--runtime", "claude",
                               "--event", "SessionStart", "--claimed-root", "/nonexistent"],
                              cwd=root, text=True, capture_output=True, input="{}",
                              env=dict(os.environ, MOTTORI_LANG="en"))
        context = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "_private/state/NOW.md" in context and not re.search("[가-힣]", context), context
        (root / "tools" / "i18n.py").unlink()
        alone = prepush("ko")
        assert alone.returncode != 0
        assert "push blocked: cannot determine instance.context" in alone.stderr, alone.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_enforce_fallback_text_matches_catalog() -> None:
    sys.path.insert(0, str(HERE))
    import enforce
    import i18n
    for key, text in enforce.FALLBACK_TEXT.items():
        assert i18n.STRINGS[key]["en"] == text, key
    spec = importlib.util.spec_from_file_location("fresh_worker_fallback_test", HERE / "fresh_worker.py")
    worker = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker)
    for key, text in worker.FALLBACK_TEXT.items():
        assert i18n.STRINGS[key]["en"] == text, key


def test_worker_refusals_follow_language() -> None:
    """fresh_worker input refusals: Korean under ko, Hangul-free English under en and alone."""
    root = Path(tempfile.mkdtemp(prefix="worker-lang-"))
    try:
        (root / "tools").mkdir()
        for name in ("fresh_worker.py", "memlib.py", "worker_batch.py", "claude_auth.py", "i18n.py"):
            shutil.copy2(HERE / name, root / "tools" / name)
        (root / "empty.md").write_text("", encoding="utf-8")

        def refuse(lang: str) -> str:
            env = dict(os.environ, MOTTORI_LANG=lang)
            env.pop("MOTTORI_INSTANCE", None)
            run = subprocess.run([sys.executable, "tools/fresh_worker.py", "--runtime", "codex",
                                  "--strict-scope", "empty.md"], cwd=root, text=True,
                                 capture_output=True, env=env)
            assert run.returncode == 2, run.stdout + run.stderr
            return run.stderr

        assert "--strict-scope에는" in refuse("ko")
        english = refuse("en")
        assert "--strict-scope needs at least one --write-prefix" in english, english
        assert not re.search("[가-힣]", english), english
        (root / "tools" / "i18n.py").unlink()
        assert "--strict-scope needs at least one --write-prefix" in refuse("ko")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _stop_fixture(root):
    """Point the gate's markers at a scratch directory and stub out measurement."""
    sys.path.insert(0, str(HERE))
    import gate
    saved = {name: getattr(gate, name) for name in (
        "DIRTY", "PENDING", "LOCK", "FINGERPRINT", "BASELINE", "SIGNING_KEY", "_root_ok",
        "_load_baseline", "measure", "_worktree_fingerprint")}
    saved["log"] = gate.M.log_run
    gate.DIRTY = lambda: str(root / "dirty")
    gate.PENDING = lambda: str(root / "pending")
    gate.LOCK = lambda: str(root / "lock")
    gate.FINGERPRINT = lambda: str(root / "fingerprint")
    gate.BASELINE = str(root / "baseline.json")
    gate.SIGNING_KEY = lambda: str(root / "no-key")
    gate._root_ok = lambda: True
    gate._worktree_fingerprint = lambda: "fixture-fingerprint"
    gate.M.log_run = lambda *args, **kwargs: None
    return gate, saved


def _restore(gate, saved):
    gate.M.log_run = saved.pop("log")
    for name, value in saved.items():
        setattr(gate, name, value)


def _run_check(gate, payload):
    previous_stdin, previous_stdout = sys.stdin, sys.stdout
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        captured = io.StringIO()
        sys.stdout = captured
        code = gate.cmd_check()
    finally:
        sys.stdin, sys.stdout = previous_stdin, previous_stdout
    return code, captured.getvalue()


def test_H03_H04_stop_hook_active_passes_once_and_keeps_pending() -> None:
    """A reentrant Stop lets the turn end once; the unresolved finding stays pending."""
    root = Path(tempfile.mkdtemp(prefix="stop-active-"))
    gate, saved = _stop_fixture(root)
    try:
        gate._load_baseline = lambda: ({"linkcheck": set(), "now-check": set()}, "ok")
        gate.measure = lambda **_: {"linkcheck": {"new-issue"}, "now-check": set()}
        Path(gate.DIRTY()).write_text("1", encoding="utf-8")
        code, output = _run_check(gate, {"stop_hook_active": True})
        assert code == 0 and output == "", output
        assert "new-issue" in Path(gate.PENDING()).read_text(encoding="utf-8")
        # Only a real boolean counts as reentrant; any other value still blocks.
        code, output = _run_check(gate, {"stop_hook_active": "false"})
        assert code == 0 and json.loads(output)["decision"] == "block", output
        assert Path(gate.PENDING()).exists()
    finally:
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_session_check_keeps_release_checkers_in_baseline() -> None:
    """A session-scope pass compares and tightens only what it measured."""
    root = Path(tempfile.mkdtemp(prefix="session-baseline-"))
    gate, saved = _stop_fixture(root)
    scopes = []
    try:
        gate._save_baseline({"linkcheck": {"known", "fixed"}, "now-check": set(),
                             "evidencecheck": {"release-only"}, "manifest": {"manifest-only"}})

        def session_measure(**kwargs):
            scopes.append(kwargs.get("scope"))
            return {"linkcheck": {"known"}, "now-check": set()}

        gate.measure = session_measure
        Path(gate.DIRTY()).write_text("1", encoding="utf-8")
        code, output = _run_check(gate, {})
        assert code == 0 and output == "", output
        assert scopes == ["session"], scopes
        saved_issues, state = gate._load_baseline()
        assert state == "ok", state
        assert saved_issues == {"linkcheck": {"known"}, "now-check": set(),
                                "evidencecheck": {"release-only"},
                                "manifest": {"manifest-only"}}, saved_issues
        assert not Path(gate.DIRTY()).exists() and not Path(gate.PENDING()).exists()
        assert Path(gate.FINGERPRINT()).read_text(encoding="utf-8") == "fixture-fingerprint"
    finally:
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_session_check_still_detects_a_removed_session_checker() -> None:
    root = Path(tempfile.mkdtemp(prefix="session-removed-"))
    gate, saved = _stop_fixture(root)
    try:
        gate._load_baseline = lambda: ({"linkcheck": set(), "now-check": set(),
                                        "evidencecheck": set()}, "ok")
        gate.measure = lambda **_: {"now-check": set()}
        Path(gate.DIRTY()).write_text("1", encoding="utf-8")
        code, output = _run_check(gate, {})
        reason = json.loads(output)["reason"]
        assert "linkcheck" in reason and "evidencecheck" not in reason, reason
    finally:
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_installed_baseline_measures_session_scope_and_keeps_release_entries() -> None:
    root = _repo()
    gate, saved = _stop_fixture(root / ".git")
    previous_root, previous_scope = gate.M.ROOT, os.environ.pop("MOTTORI_GATE_SCOPE", None)
    scopes = []
    try:
        gate.M.ROOT = str(root)
        gate._save_baseline({"linkcheck": {"old"}, "now-check": set(),
                             "evidencecheck": {"release-only"}})

        def measured(**kwargs):
            scopes.append(kwargs.get("scope"))
            return {"linkcheck": set(), "now-check": set()}

        gate.measure = measured
        assert gate.cmd_baseline() == 0
        assert scopes == ["session"], scopes
        issues, state = gate._load_baseline()
        assert state == "ok" and issues["evidencecheck"] == {"release-only"}, issues
        assert issues["linkcheck"] == set(), issues
    finally:
        gate.M.ROOT = previous_root
        if previous_scope is not None:
            os.environ["MOTTORI_GATE_SCOPE"] = previous_scope
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_release_baseline_still_migrates_a_removed_checker() -> None:
    """Only a session measurement keeps unmeasured entries; release replaces the whole set."""
    root = _repo()
    gate, saved = _stop_fixture(root / ".git")
    previous_root, previous_scope = gate.M.ROOT, os.environ.get("MOTTORI_GATE_SCOPE")
    try:
        gate.M.ROOT = str(root)
        os.environ["MOTTORI_GATE_SCOPE"] = "release"
        gate._save_baseline({"linkcheck": set(), "retired-checker": {"old"}})
        gate.measure = lambda **_: {"linkcheck": set(), "now-check": set(),
                                    "evidencecheck": set(), "manifest": set()}
        assert gate.cmd_baseline() == 0
        issues, state = gate._load_baseline()
        assert state == "ok" and "retired-checker" not in issues, issues
    finally:
        gate.M.ROOT = previous_root
        if previous_scope is None:
            os.environ.pop("MOTTORI_GATE_SCOPE", None)
        else:
            os.environ["MOTTORI_GATE_SCOPE"] = previous_scope
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_resume_reports_pending_reason_without_measuring() -> None:
    root = Path(tempfile.mkdtemp(prefix="resume-pending-"))
    gate, saved = _stop_fixture(root)
    previous_stdout = sys.stdout

    def forbidden(**_):
        raise AssertionError("resume must not measure")

    refresh = gate._refresh_test_evidence
    try:
        gate.measure = forbidden
        gate._refresh_test_evidence = forbidden
        Path(gate.DIRTY()).write_text("1", encoding="utf-8")
        captured = io.StringIO()
        sys.stdout = captured
        assert gate.cmd_resume() == 0
        sys.stdout = previous_stdout
        assert captured.getvalue() == "", "a dirty marker alone is left for the next Stop"
        Path(gate.PENDING()).write_text("linkcheck: README.md -> gone.md", encoding="utf-8")
        captured = io.StringIO()
        sys.stdout = captured
        assert gate.cmd_resume() == 0
        sys.stdout = previous_stdout
        context = json.loads(captured.getvalue())["hookSpecificOutput"]["additionalContext"]
        assert "README.md -> gone.md" in context, context
        assert Path(gate.PENDING()).exists() and Path(gate.DIRTY()).exists()
    finally:
        sys.stdout = previous_stdout
        gate._refresh_test_evidence = refresh
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_fixture_git_setup_ignores_outer_commit_pinning() -> None:
    """A commit hook's GIT_DIR and GIT_INDEX_FILE must not reach the extracted tree's Git."""
    sys.path.insert(0, str(HERE))
    import gate
    outer = _repo()
    tree = Path(tempfile.mkdtemp(prefix="extracted-tree-"))
    pinning = {"GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(outer),
               "GIT_INDEX_FILE": str(outer / ".git" / "index")}
    previous = {key: os.environ.get(key) for key in pinning}
    try:
        (outer / "README.md").write_text("staged change\n", encoding="utf-8")
        _git(outer, "add", "README.md")
        (outer / "untracked.md").write_text("outer untracked\n", encoding="utf-8")
        index_before = (outer / ".git" / "index").read_bytes()
        head_before = _git(outer, "rev-parse", "HEAD").stdout
        (tree / "fixture.md").write_text("extracted\n", encoding="utf-8")
        os.environ.update(pinning)
        try:
            assert gate._ensure_git_tree(str(tree))
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        assert (outer / ".git" / "index").read_bytes() == index_before
        assert _git(outer, "rev-parse", "HEAD").stdout == head_before
        assert (tree / ".git").is_dir()
        listed = _git(tree, "ls-files").stdout.split()
        assert listed == ["fixture.md"], listed
    finally:
        shutil.rmtree(outer, ignore_errors=True)
        shutil.rmtree(tree, ignore_errors=True)


def test_sync_inventory_is_single_source_and_partial_copy_rolls_back() -> None:
    if not (HERE / "sync_engine.sh").is_file():
        print("- sync inventory: not applicable to an installed instance")
        return
    import fresh_worker
    instance = Path(tempfile.mkdtemp(prefix="sync-rollback-"))
    tools = instance / "tools"
    tools.mkdir()
    fake_bin = instance / "bin"
    fake_bin.mkdir()
    before = {}
    try:
        for name in fresh_worker.SYNC_FILES[::2]:
            content = f"old {name}\n"
            (tools / name).write_text(content, encoding="utf-8")
            before[name] = content
        wrapper = fake_bin / "python3"
        wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$#" -eq 4 ] && [ "$1" = "-" ]; then\n'
            '  echo reached > "$SYNC_VERIFY_MARKER"\n'
            "  exit 74\n"
            "fi\n"
            'exec "$REAL_PYTHON" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        marker = fake_bin / "verified"
        env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                   REAL_PYTHON=sys.executable, SYNC_VERIFY_MARKER=str(marker))
        run = subprocess.run(
            ["bash", str(HERE / "sync_engine.sh"), str(instance)], cwd=ROOT,
            text=True, capture_output=True, env=env,
        )
        assert run.returncode != 0, run.stdout
        assert marker.exists(), (run.stdout, run.stderr)
        assert all((tools / name).read_text(encoding="utf-8") == content
                   for name, content in before.items())
        assert all(not (tools / name).exists() for name in fresh_worker.SYNC_FILES if name not in before)
        assert not list(tools.glob(".sync-engine.*"))
        source = (HERE / "sync_engine.sh").read_text(encoding="utf-8")
        assert "SYNC_FILES" in source
        assert "for f in fresh_worker.py" not in source
    finally:
        shutil.rmtree(instance, ignore_errors=True)


def test_sync_second_destination_copy_failure_rolls_back_first_copy() -> None:
    if not (HERE / "sync_engine.sh").is_file():
        print("- sync publication: not applicable to an installed instance")
        return
    import fresh_worker
    instance = Path(tempfile.mkdtemp(prefix="sync-publish-failure-"))
    fake_bin = Path(tempfile.mkdtemp(prefix="sync-fake-python-"))
    tools = instance / "tools"
    tools.mkdir()
    before = {}
    try:
        for name in fresh_worker.SYNC_FILES[::2]:
            content = f"old {name}\n"
            (tools / name).write_text(content, encoding="utf-8")
            before[name] = content
        wrapper = fake_bin / "python3"
        wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$#" -eq 3 ] && [ "$1" = "-" ]; then\n'
            '  case "$2" in "$SYNC_FAIL_ROOT"/tools/.sync-engine.*/new/*)\n'
            '    n=0; test ! -f "$SYNC_FAIL_COUNT" || n=$(cat "$SYNC_FAIL_COUNT")\n'
            '    n=$((n + 1)); echo "$n" > "$SYNC_FAIL_COUNT"\n'
            '    if [ "$n" -eq 2 ]; then\n'
            '      cmp "$SYNC_SOURCE_FIRST" "$SYNC_DEST_FIRST" && echo replaced > "$SYNC_FIRST_MARKER"\n'
            "      exit 73\n"
            "    fi\n"
            "  esac\n"
            "fi\n"
            'exec "$REAL_PYTHON" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        marker = fake_bin / "first-replaced"
        env = dict(os.environ,
                   PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                   REAL_PYTHON=sys.executable,
                   SYNC_FAIL_ROOT=str(instance.resolve()),
                   SYNC_FAIL_COUNT=str(fake_bin / "count"),
                   SYNC_SOURCE_FIRST=str(HERE / fresh_worker.SYNC_FILES[0]),
                   SYNC_DEST_FIRST=str(tools / fresh_worker.SYNC_FILES[0]),
                   SYNC_FIRST_MARKER=str(marker))
        run = subprocess.run(
            ["bash", str(HERE / "sync_engine.sh"), str(instance)], cwd=ROOT,
            text=True, capture_output=True, env=env,
        )
        assert run.returncode != 0, run.stdout
        assert marker.exists(), (run.stdout, run.stderr)
        assert all((tools / name).read_text(encoding="utf-8") == content
                   for name, content in before.items())
        assert all(not (tools / name).exists() for name in fresh_worker.SYNC_FILES if name not in before)
        assert not list(tools.glob(".sync-engine.*"))
    finally:
        shutil.rmtree(fake_bin, ignore_errors=True)
        shutil.rmtree(instance, ignore_errors=True)


def test_E1_rec_check_crash_is_doctor_fail() -> None:
    sys.path.insert(0, str(HERE))
    import doctor
    import memlib
    root = Path(tempfile.mkdtemp(prefix="doctor-ledger-"))
    facts = root / "_private" / "ledger" / "facts"
    facts.mkdir(parents=True)
    (facts / "one.md").write_text("fact\n", encoding="utf-8")
    old_root, old_sh = memlib.ROOT, doctor.sh
    try:
        memlib.ROOT = str(root)

        class Result:
            returncode = 1
            stdout = ""
            stderr = "Traceback: synthetic crash"

        doctor.sh = lambda *args, **kwargs: Result()
        status, detail = doctor.c_ledger()
        assert status == doctor.FAIL and "synthetic crash" in detail
    finally:
        memlib.ROOT = old_root
        doctor.sh = old_sh
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_reads_tool_trailers_in_either_language() -> None:
    """doctor parses rec.py and coherence.py summary lines printed under either language."""
    sys.path.insert(0, str(HERE))
    import doctor
    import memlib
    root = Path(tempfile.mkdtemp(prefix="doctor-forms-"))
    facts = root / "_private" / "ledger" / "facts"
    facts.mkdir(parents=True)
    (facts / "one.md").write_text("fact\n", encoding="utf-8")
    old_root, old_sh = memlib.ROOT, doctor.sh

    class Result:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout, self.stderr, self.returncode = stdout, "", returncode

    try:
        memlib.ROOT = str(root)
        for out in ("[check] 문제: 2건\n", "[check] problems: 2\n"):
            doctor.sh = lambda *args, out=out, **kwargs: Result(out)
            status, _detail = doctor.c_ledger()
            assert status == doctor.WARN, (out, status)
        doctor.sh = lambda *args, **kwargs: Result("[check] nothing\n")
        assert doctor.c_ledger()[0] == doctor.FAIL
        for out, expected in (("[coherence] 이슈 3건: a | b\n", doctor.WARN),
                              ("[coherence] 3 issue(s): a | b\n", doctor.WARN),
                              ("[coherence] 이상 없음\n", doctor.PASS),
                              ("[coherence] no issues\n", doctor.PASS),
                              ("garbled\n", doctor.FAIL)):
            doctor.sh = lambda *args, out=out, **kwargs: Result(out, 1 if "3" in out else 0)
            assert doctor.c_coherence()[0] == expected, out
        assert doctor._config_warning("config 없음: /x") in ("config 없음: /x", "config missing: /x")
        markers = set(doctor.STRINGS["doctor.precompact_marker"].values())
        assert markers == {"[system/state] compaction occurred", "[system/state] 컴팩션 발생"}
    finally:
        memlib.ROOT = old_root
        doctor.sh = old_sh
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_doctor_reads_tool_trailers_in_either_language,
    test_G03_markdown_symlink_is_blocked,
    test_G04_submodule_gitlink_is_blocked,
    test_G02_unicode_markdown_path_is_not_git_quoted,
    test_G10_signed_baseline_rejects_direct_mutation,
    test_G12_sealed_baseline_refuses_staged_recreation,
    test_S2_G1_G2_force_add_and_work_tracked_changes_are_blocked,
    test_S2_G4_work_push_is_hard_blocked,
    test_S2_G5_ready_rejects_missing_context_and_template_rules,
    test_W09_strict_scope_requires_a_prefix,
    test_enforce_messages_follow_language_and_survive_without_catalog,
    test_enforce_fallback_text_matches_catalog,
    test_worker_refusals_follow_language,
    test_H03_H04_stop_hook_active_passes_once_and_keeps_pending,
    test_session_check_keeps_release_checkers_in_baseline,
    test_session_check_still_detects_a_removed_session_checker,
    test_installed_baseline_measures_session_scope_and_keeps_release_entries,
    test_release_baseline_still_migrates_a_removed_checker,
    test_resume_reports_pending_reason_without_measuring,
    test_fixture_git_setup_ignores_outer_commit_pinning,
    test_sync_inventory_is_single_source_and_partial_copy_rolls_back,
    test_sync_second_destination_copy_failure_rolls_back_first_copy,
    test_E1_rec_check_crash_is_doctor_fail,
    test_tracked_public_state_is_not_forbidden,
    test_N3_gitignore_exception_cannot_allow_new_instance_paths,
    test_N6_sealed_baseline_requires_explicit_adoption_and_records_it,
    test_N6_adoption_approval_lives_in_git_control_plane,
    test_N6_baseline_refuses_when_control_plane_lock_is_unavailable,
    test_N6_first_sealed_baseline_is_the_only_implicit_adoption,
    test_tracked_markdown_symlink_in_head_is_not_reflagged,
    test_prepush_allows_presetup_kit_tree_and_blocks_unknown_context,
]


def main() -> int:
    failed: list[str] = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print("PASS", test.__name__)
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print("FAIL", test.__name__, type(error).__name__, error)
    print(f"enforce tests: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
