#!/usr/bin/env python3
"""Fail-close regression pins for H1 bypasses and S2 Git egress paths."""
from __future__ import annotations

import contextlib
import importlib.util
import io
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
def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, text=True, capture_output=True,
    )


def _repo(context: str = "personal") -> Path:
    root = Path(tempfile.mkdtemp(prefix="enforce-fixture-"))
    (root / "tools").mkdir()
    for name in ("enforce.py",):
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
    """Tracked public state is allowed by the original instance contract; _private/ never is."""
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
        gate.measure = lambda: {"linkcheck": {"known", "new-n6-a", "new-n6-b"}}

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

        gate.measure = lambda: {"linkcheck": {"known", "new-n6-a", "new-n6-b", "new-n6-c"}}
        assert gate.cmd_baseline() != 0, "approval must be bound to the previous baseline and target set"

        gate.measure = lambda: {"linkcheck": {"known"}}
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
        gate.measure = lambda: {"linkcheck": {"known"}}
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
        gate.measure = lambda: {"linkcheck": {"first-install-issue"}}
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
                                 cwd=root, text=True, capture_output=True)
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


def test_H03_H04_stop_hook_active_never_skips_a_pending_gate() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = Path(tempfile.mkdtemp(prefix="stop-active-"))
    original = {
        "DIRTY": gate.DIRTY,
        "PENDING": gate.PENDING,
        "LOCK": gate.LOCK,
        "root_ok": gate._root_ok,
        "load": gate._load_baseline,
        "measure": gate.measure,
        "verdict": gate._verdict,
        "log": gate.M.log_run,
        "stdin": sys.stdin,
        "stdout": sys.stdout,
    }
    try:
        gate.DIRTY = lambda: str(root / "dirty")
        gate.PENDING = lambda: str(root / "pending")
        gate.LOCK = lambda: str(root / "lock")
        gate._root_ok = lambda: True
        gate._load_baseline = lambda: ({"fixture": set()}, "ok")
        gate.measure = lambda: {"fixture": {"new-issue"}}
        gate._verdict = lambda current, baseline, state: ("fixture blocked", False)
        gate.M.log_run = lambda *args, **kwargs: None
        Path(gate.DIRTY()).write_text("1", encoding="utf-8")
        for payload in ({"stop_hook_active": True}, {"stop_hook_active": "false"}):
            Path(gate.DIRTY()).write_text("1", encoding="utf-8")
            sys.stdin = io.StringIO(json.dumps(payload))
            captured = io.StringIO()
            sys.stdout = captured
            assert gate.cmd_check() == 0
            assert json.loads(captured.getvalue())["decision"] == "block"
    finally:
        gate.DIRTY = original["DIRTY"]
        gate.PENDING = original["PENDING"]
        gate.LOCK = original["LOCK"]
        gate._root_ok = original["root_ok"]
        gate._load_baseline = original["load"]
        gate.measure = original["measure"]
        gate._verdict = original["verdict"]
        gate.M.log_run = original["log"]
        sys.stdin = original["stdin"]
        sys.stdout = original["stdout"]
        shutil.rmtree(root, ignore_errors=True)


def test_sync_inventory_is_single_source_and_partial_copy_rolls_back() -> None:
    if not (HERE / "sync_engine.sh").is_file():
        # The stamped kit-to-instance copier exists only in the kit (instance kit_sync NOT_SYNCED).
        print("- sync inventory: not applicable here (no tools/sync_engine.sh: installed instance)")
        return
    instance = Path(tempfile.mkdtemp(prefix="sync-rollback-"))
    tools = instance / "tools"
    tools.mkdir()
    names = ("fresh_worker.py", "test_fresh_worker.py", "ask_codex.sh")
    before = {}
    try:
        for name in names:
            content = f"old {name}\n"
            (tools / name).write_text(content, encoding="utf-8")
            before[name] = content
        (tools / "memlib.py").write_text("raise RuntimeError('verification fail')\n", encoding="utf-8")
        run = subprocess.run(
            ["bash", str(HERE / "sync_engine.sh"), str(instance)], cwd=ROOT,
            text=True, capture_output=True,
        )
        assert run.returncode != 0
        assert all((tools / name).read_text(encoding="utf-8") == content
                   for name, content in before.items())
        source = (HERE / "sync_engine.sh").read_text(encoding="utf-8")
        assert "f.SYNC_FILES" in source
        assert "for f in fresh_worker.py" not in source
    finally:
        shutil.rmtree(instance, ignore_errors=True)


def test_sync_second_destination_copy_failure_rolls_back_first_copy() -> None:
    instance = Path(tempfile.mkdtemp(prefix="sync-copy-failure-"))
    fake_bin = Path(tempfile.mkdtemp(prefix="sync-fake-cp-"))
    tools = instance / "tools"
    tools.mkdir()
    names = ("fresh_worker.py", "test_fresh_worker.py", "worker_batch.py",
             "test_worker_batch.py", "ask_codex.sh")
    before = {}
    try:
        for name in names:
            content = f"old {name}\n"
            (tools / name).write_text(content, encoding="utf-8")
            before[name] = content
        wrapper = fake_bin / "cp"
        wrapper.write_text(
            "#!/bin/sh\n"
            "dest=\nfor arg in \"$@\"; do dest=$arg; done\n"
            "case \"$dest\" in\n"
            "  \"$SYNC_FAIL_ROOT\"/tools/*)\n"
            "    n=0; test ! -f \"$SYNC_FAIL_COUNT\" || n=$(cat \"$SYNC_FAIL_COUNT\")\n"
            "    n=$((n + 1)); echo \"$n\" > \"$SYNC_FAIL_COUNT\"\n"
            "    test \"$n\" -ne 2 || exit 73\n"
            "    ;;\n"
            "esac\n"
            "exec \"$REAL_CP\" \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        env = dict(os.environ,
                   PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                   REAL_CP=shutil.which("cp") or "/bin/cp",
                   SYNC_FAIL_ROOT=str(instance),
                   SYNC_FAIL_COUNT=str(fake_bin / "count"))
        run = subprocess.run(
            ["bash", str(HERE / "sync_engine.sh"), str(instance)], cwd=ROOT,
            text=True, capture_output=True, env=env,
        )
        assert run.returncode != 0
        assert all((tools / name).read_text(encoding="utf-8") == content
                   for name, content in before.items())
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


TESTS = [
    test_G03_markdown_symlink_is_blocked,
    test_G04_submodule_gitlink_is_blocked,
    test_G02_unicode_markdown_path_is_not_git_quoted,
    test_G10_signed_baseline_rejects_direct_mutation,
    test_G12_sealed_baseline_refuses_staged_recreation,
    test_S2_G1_G2_force_add_and_work_tracked_changes_are_blocked,
    test_S2_G4_work_push_is_hard_blocked,
    test_S2_G5_ready_rejects_missing_context_and_template_rules,
    test_W09_strict_scope_requires_a_prefix,
    test_H03_H04_stop_hook_active_never_skips_a_pending_gate,
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
