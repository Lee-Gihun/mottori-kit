#!/usr/bin/env python3
"""Test fail-closed gate controls and Git egress boundaries."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from unittest.mock import patch

from testlib import gate_stop_fixture, hook_event


HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent
def _set_root(value: object) -> str | None:
    """Point every tool at the instance root value (None clears it); return the previous one."""
    previous = os.environ.get("MOTTORI_INSTANCE")
    if value is None:
        os.environ.pop("MOTTORI_INSTANCE", None)
    else:
        os.environ["MOTTORI_INSTANCE"] = str(value)
    return previous


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, text=True, capture_output=True,
    )


def _repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="enforce-fixture-"))
    (root / "tools" / "lib").mkdir(parents=True)
    for name in ("enforce.py", "lib/config.py", "lib/paths.py", "lib/safeio.py"):
        shutil.copy2(HERE / name, root / "tools" / name)
    (root / "instance").mkdir()
    (root / "instance" / "config.json").write_text(json.dumps({
        "schema_version": 4,
        "instance": {"name": "fixture"},
    }), encoding="utf-8")
    (root / "instance" / "rules.md").write_text(
        "# instance\n\n국경: fixture only\n", encoding="utf-8"
    )
    (root / ".gitignore").write_text(
        "/state/\n/_private/\n/instance/config.json\n/instance/rules.md\n",
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
    previous = os.environ.get("MOTTORI_INSTANCE")
    try:
        path = root / "감사 문서.md"
        path.write_text("[bad](없는-대상.md)\n", encoding="utf-8")
        _git(root, "add", "-f", path.name)
        _set_root(root)
        assert gate._staged_markdown_paths() == ["README.md", "감사 문서.md"]
    finally:
        _set_root(previous)
        shutil.rmtree(root, ignore_errors=True)


def test_S2_G1_a_forced_state_file_is_blocked_and_an_ordinary_file_is_not() -> None:
    """The check keeps the installation's own files out of a commit. Whether a folder may commit an
    ordinary file is not its business."""
    root = _repo()
    try:
        (root / "state").mkdir()
        (root / "state" / "NOW.md").write_text("secret\n", encoding="utf-8")
        _git(root, "add", "-f", "state/NOW.md")
        (root / "README.md").write_text("an ordinary change\n", encoding="utf-8")
        _git(root, "add", "README.md")
        _, issues = _issues(root, "--index")
        assert "new-instance-path:state/NOW.md" in issues
        assert not [issue for issue in issues if "README.md" in issue], issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tracked_public_state_is_not_forbidden() -> None:
    """Personal instances may track public state; the _private/ tree is always forbidden."""
    root = _repo()
    try:
        (root / ".gitignore").write_text("/_private/\n", encoding="utf-8")
        (root / "state").mkdir()
        (root / "state" / "NOW.md").write_text("# NOW\n", encoding="utf-8")
        (root / "instance" / "decisions.md").write_text("# DR\n", encoding="utf-8")
        _git(root, "add", ".gitignore", "state/NOW.md", "instance/decisions.md", "instance/config.json")
        _commit(root, "track public instance files")
        (root / "_private").mkdir()
        (root / "_private" / "old.md").write_text("old\n", encoding="utf-8")
        _git(root, "add", "-f", "_private/old.md")
        _commit(root, "an old commit that already holds a private file")
        (root / "_private" / "old.md").write_text("old\nchanged\n", encoding="utf-8")
        _git(root, "add", "-f", "_private/old.md")
        (root / "state" / "NOW.md").write_text("# NOW\n\nupdated\n", encoding="utf-8")
        (root / "instance" / "decisions.md").write_text("# DR\n\nupdated\n", encoding="utf-8")
        _git(root, "add", "state/NOW.md", "instance/decisions.md")
        (root / "_private" / "x.md").write_text("secret\n", encoding="utf-8")
        _git(root, "add", "-f", "_private/x.md")
        _, issues = _issues(root, "--index")
        assert "forbidden-index-path:_private/old.md" in issues, issues
        assert "new-instance-path:state/NOW.md" not in issues, issues
        assert "new-instance-path:instance/decisions.md" not in issues, issues
        assert "new-instance-path:instance/config.json" not in issues, issues
        assert "forbidden-index-path:_private/x.md" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _commit(root: Path, message: str) -> None:
    _git(root, "-c", "user.name=fixture", "-c", "user.email=f@example.invalid",
         "commit", "-qm", message)


def test_new_monthly_journal_allowed_when_journals_tracked() -> None:
    """A tracked public journal lets the next month's journal in; other new state stays refused."""
    root = _repo()
    try:
        (root / "state").mkdir()
        (root / "state" / "journal-2026-10.md").write_text("# 10\n", encoding="utf-8")
        _git(root, "add", "-f", "state/journal-2026-10.md")
        _, issues = _issues(root, "--index")
        assert "new-instance-path:state/journal-2026-10.md" in issues, issues
        _git(root, "rm", "-q", "--cached", "state/journal-2026-10.md")
        (root / "state" / "journal-2026-09.md").write_text("# 09\n", encoding="utf-8")
        _git(root, "add", "-f", "state/journal-2026-09.md")
        _commit(root, "track public journal")
        _git(root, "add", "-f", "state/journal-2026-10.md")
        (root / "state" / "other.md").write_text("x\n", encoding="utf-8")
        _git(root, "add", "-f", "state/other.md")
        _, issues = _issues(root, "--index")
        assert not [i for i in issues if i.endswith(":state/journal-2026-10.md")], issues
        assert "new-instance-path:state/other.md" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_private_case_variant_is_forbidden() -> None:
    """On a case-insensitive disk _PRIVATE/ is the same folder as _private/."""
    root = _repo()
    try:
        _git(root, "config", "core.ignorecase", "true")
        (root / "_PRIVATE").mkdir()
        (root / "_PRIVATE" / "s.md").write_text("secret\n", encoding="utf-8")
        _git(root, "add", "-f", "_PRIVATE/s.md")
        _, issues = _issues(root, "--index")
        assert "forbidden-index-path:_PRIVATE/s.md" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_issues_without_index_is_a_usage_error() -> None:
    root = _repo()
    try:
        run = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "--issues"],
                             cwd=root, text=True, capture_output=True)
        assert run.returncode == 2, (run.returncode, run.stdout, run.stderr)
        assert "#issues" not in run.stdout, run.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unmerged_entry_and_non_git_root_fail_closed() -> None:
    root = _repo()
    plain = Path(tempfile.mkdtemp(prefix="enforce-not-git-"))
    try:
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=root, input="x\n",
                              text=True, capture_output=True, check=True).stdout.strip()
        subprocess.run(["git", "update-index", "--index-info"], cwd=root, check=True, text=True,
                       input="".join(f"100644 {blob} {stage}\tconflict.md\n" for stage in (1, 2, 3)))
        _, issues = _issues(root, "--index")
        assert "index-unmerged:conflict.md" in issues, issues
        run = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "--issues", "--index",
                              "--root", str(plain)], cwd=plain, text=True, capture_output=True)
        assert run.returncode == 2 and "#issues" not in run.stdout, (run.stdout, run.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(plain, ignore_errors=True)


def _prepush(root: Path, stdin: str, *remote: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush", *remote],
                          cwd=root, text=True, capture_output=True, input=stdin)


def test_prepush_refuses_pushed_private_commit() -> None:
    """The push hook rechecks the one thing that must not leave: a path under _private/. It does not
    decide which remote a folder may push to."""
    root = _repo()
    zero = "0" * 40
    try:
        (root / "notes.md").write_text("public\n", encoding="utf-8")
        _git(root, "add", "notes.md")
        _commit(root, "clean")
        clean = _git(root, "rev-parse", "HEAD").stdout.strip()
        line = f"refs/heads/main {clean} refs/heads/main {zero}\n"
        good = ("origin", "git@github.com:example/repo.git")
        assert _prepush(root, line, *good).returncode == 0
        assert _prepush(root, line, "origin", "https://github.com/example/repo.git").returncode == 0
        assert _prepush(root, line).returncode == 0
        # A manual run that inherits an open pipe nobody writes must return, not wait on it.
        idle = subprocess.Popen([sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
                                cwd=root, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            assert idle.wait(timeout=20) == 0
        finally:
            idle.kill()
            idle.stdin.close()
        # Ref input that is not UTF-8 or never closes cannot be judged: a refusal, not a hang.
        garbled = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush", *good],
                                 cwd=root, input=b"\xff\n", capture_output=True)
        assert garbled.returncode == 2 and b"Traceback" not in garbled.stderr, garbled.stderr
        sys.path.insert(0, str(root / "tools"))
        import enforce
        read_end, write_end = os.pipe()
        saved = sys.stdin
        try:
            sys.stdin = os.fdopen(read_end)
            try:
                enforce._hook_lines(timeout=0.2)
                raise AssertionError("an open ref pipe was read as complete")
            except enforce.MeasurementError:
                pass
        finally:
            sys.stdin.close()
            sys.stdin = saved
            os.close(write_end)
            sys.path.remove(str(root / "tools"))
        # Any remote is the owner's to choose.
        assert _prepush(root, line, "origin", "https://example.invalid/other/repo.git").returncode == 0
        (root / "_private").mkdir()
        (root / "_private" / "s.md").write_text("secret\n", encoding="utf-8")
        _git(root, "add", "-f", "_private/s.md")
        _commit(root, "skipped the commit hook")
        (root / "_private" / "s.md").unlink()
        _git(root, "add", "-A")
        _commit(root, "removed again")
        tip = _git(root, "rev-parse", "HEAD").stdout.strip()
        run = _prepush(root, f"refs/heads/main {tip} refs/heads/main {zero}\n", *good)
        assert run.returncode == 1 and "_private/s.md" in run.stderr, run.stdout + run.stderr
        # A cached remote-tracking ref is not evidence of what the receiver holds: the same
        # remote name can push to another URL. Only the id Git reports for the receiver counts.
        _git(root, "update-ref", "refs/remotes/other/main", tip)
        run = _prepush(root, f"refs/heads/main {tip} refs/heads/main {zero}\n", "other", good[1])
        assert run.returncode == 1 and "_private/s.md" in run.stderr, run.stdout + run.stderr
        run = _prepush(root, f"refs/heads/main {tip} refs/heads/main {tip}\n", *good)
        assert run.returncode == 0, run.stdout + run.stderr
        deleting = _prepush(root, f"(delete) {zero} refs/heads/old {clean}\n", *good)
        assert deleting.returncode == 0, deleting.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_N3_gitignore_exception_cannot_allow_new_instance_paths() -> None:
    """Changing .gitignore cannot make a path absent from HEAD safe to stage."""
    root = _repo()
    try:
        with (root / ".gitignore").open("a", encoding="utf-8") as ignore:
            ignore.write("\n!/state/leak.bin\n!/instance/decisions.md\n")
        (root / "state").mkdir()
        (root / "state" / "leak.bin").write_bytes(b"\x00\x01\x02\x03")
        (root / "instance" / "decisions.md").write_text("new instance file\n", encoding="utf-8")
        _git(root, "add", ".gitignore", "instance/decisions.md")
        _git(root, "add", "-f", "state/leak.bin")
        _, issues = _issues(root, "--index")
        assert "new-instance-path:state/leak.bin" in issues, issues
        assert "new-instance-path:instance/decisions.md" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_repository_without_head_refuses_force_added_instance_paths() -> None:
    """Before the first commit, a force-added state path is refused and an unignored one is not."""
    root = Path(tempfile.mkdtemp(prefix="enforce-no-head-"))
    try:
        (root / "tools" / "lib").mkdir(parents=True)
        for name in ("enforce.py", "lib/config.py", "lib/paths.py", "lib/safeio.py"):
            shutil.copy2(HERE / name, root / "tools" / name)
        (root / "instance").mkdir()
        (root / ".gitignore").write_text("/state/\n", encoding="utf-8")
        (root / "state").mkdir()
        (root / "state" / "x.md").write_text("local\n", encoding="utf-8")
        (root / "instance" / "decisions.md").write_text("# DR\n", encoding="utf-8")
        _git(root, "init", "-q")
        _git(root, "add", ".gitignore", "instance/decisions.md")
        _git(root, "add", "-f", "state/x.md")
        _, issues = _issues(root, "--index")
        assert "new-instance-path:state/x.md" in issues, issues
        assert "new-instance-path:instance/decisions.md" not in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_N6_baseline_refuses_when_control_plane_lock_is_unavailable() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    baseline = root / "state" / ".gate-baseline.json"
    baseline.parent.mkdir(exist_ok=True)
    previous = os.environ.get("MOTTORI_INSTANCE")
    original = (gate.BASELINE, gate._root_ok, gate.measure, gate.PENDING, gate._lock)

    @contextlib.contextmanager
    def unavailable_lock(timeout=150):
        yield False

    try:
        _set_root(root)
        gate.BASELINE = str(baseline)
        gate._root_ok = lambda: True
        gate.PENDING = lambda: str(root / ".git" / "pending")
        gate._save_baseline({"linkcheck": {"known", "removed"}})
        gate.measure = lambda **_: gate.Measurement({"linkcheck": {"known"}})
        gate._lock = unavailable_lock
        assert gate.cmd_baseline() != 0
        saved, state = gate._load_baseline()
        assert state == "ok" and saved == {"linkcheck": {"known", "removed"}}
    finally:
        _set_root(previous)
        (gate.BASELINE, gate._root_ok, gate.measure, gate.PENDING, gate._lock) = original
        shutil.rmtree(root, ignore_errors=True)


def test_N6_first_sealed_baseline_is_the_only_implicit_adoption() -> None:
    sys.path.insert(0, str(HERE))
    import gate
    root = _repo()
    baseline = root / "state" / ".gate-baseline.json"
    baseline.parent.mkdir(exist_ok=True)
    previous = os.environ.get("MOTTORI_INSTANCE")
    original = (gate.BASELINE, gate._root_ok, gate.measure, gate.PENDING, gate.LOCK)
    try:
        _set_root(root)
        gate.BASELINE = str(baseline)
        gate._root_ok = lambda: True
        gate.measure = lambda **_: gate.Measurement({"linkcheck": {"first-install-issue"}})
        gate.PENDING = lambda: str(root / ".git" / "pending")
        gate.LOCK = lambda: str(root / ".git" / "lock")
        assert gate.cmd_baseline() == 0
        saved, state = gate._load_baseline()
        assert state == "ok" and saved["linkcheck"] == {"first-install-issue"}
    finally:
        _set_root(previous)
        (gate.BASELINE, gate._root_ok, gate.measure, gate.PENDING, gate.LOCK) = original
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
        _commit(root, "legacy symlink")
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


def test_prepush_refuses_a_damaged_instance_and_a_private_path_and_allows_a_kit_tree() -> None:
    """A tree with instance files and no config pushes nothing; a kit tree before setup pushes, and
    its private paths are still refused."""
    root = _repo()
    try:
        (root / "instance" / "config.json").unlink()
        blocked = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
                                 cwd=root, text=True, capture_output=True)
        assert blocked.returncode != 0 and "damaged instance" in blocked.stderr, blocked.stderr
        (root / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (root / "templates").mkdir()
        (root / "templates" / "config.json").write_text("{}", encoding="utf-8")
        # With instance files beside the installer it is a damaged instance: push and commit
        # checks refuse and name the way back.
        damaged = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
                                 cwd=root, text=True, capture_output=True)
        assert damaged.returncode == 1 and "config.json.bak" in damaged.stderr, damaged.stderr
        _, issues = _issues(root, "--index")
        assert "instance-config-missing" in issues, issues
        (root / "instance" / "rules.md").unlink()
        # A journal alone is the state evidence now.py check also counts, so it is still damaged.
        (root / "state").mkdir()
        (root / "state" / "journal-2026-11.md").write_text("", encoding="utf-8")
        journal_only = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush",
                                       "o", "https://example.invalid/x"],
                                      cwd=root, text=True, capture_output=True)
        assert journal_only.returncode == 1 and "journal-2026-11.md" in journal_only.stderr, journal_only.stderr
        shutil.rmtree(root / "state")
        allowed = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
                                 cwd=root, text=True, capture_output=True)
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr
        # Before setup the private-path check still runs on what is pushed.
        (root / "_private").mkdir()
        (root / "_private" / "s.md").write_text("secret\n", encoding="utf-8")
        _git(root, "add", "-f", "_private/s.md")
        _commit(root, "private before setup")
        tip = _git(root, "rev-parse", "HEAD").stdout.strip()
        leaked = _prepush(root, f"refs/heads/main {tip} refs/heads/main {'0' * 40}\n",
                          "origin", "https://example.invalid/repo.git")
        assert leaked.returncode == 1 and "_private/s.md" in leaked.stderr, leaked.stdout + leaked.stderr
        # The refusal names the step that works: a later deleting commit does not help.
        assert "git rm --cached" in leaked.stderr and "does not" in leaked.stderr, leaked.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_enforce_messages_are_english() -> None:
    """A refused push explains itself in English with no Hangul."""
    root = _repo()
    try:
        (root / "instance" / "config.json").unlink()
        english = subprocess.run([sys.executable, str(root / "tools" / "enforce.py"), "prepush"],
                                 cwd=root, text=True, capture_output=True)
        assert english.returncode != 0
        assert "damaged instance" in english.stderr, english.stderr
        assert not re.search("[\uac00-\ud7a3]", english.stdout + english.stderr), english.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_worker_refusals_are_english() -> None:
    """fresh_worker input refusals are English with no Hangul."""
    root = Path(tempfile.mkdtemp(prefix="worker-refusal-"))
    try:
        (root / "tools" / "lib").mkdir(parents=True)
        for name in ("fresh_worker.py", "lib/config.py", "lib/paths.py", "lib/safeio.py",
                     "receipts.py", "claude_auth.py", "lib/worker_sandbox.py"):
            shutil.copy2(HERE / name, root / "tools" / name)
        (root / "empty.md").write_text("", encoding="utf-8")
        env = dict(os.environ)
        env.pop("MOTTORI_INSTANCE", None)
        run = subprocess.run([sys.executable, "tools/fresh_worker.py", "--runtime", "codex",
                              "empty.md"], cwd=root, text=True, capture_output=True, env=env)
        assert run.returncode == 2, run.stdout + run.stderr
        assert "prompt is empty" in run.stderr, run.stderr
        assert not re.search("[\uac00-\ud7a3]", run.stderr), run.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _stop_fixture(root):
    """Point the gate's markers at a scratch directory; _restore undoes it."""
    sys.path.insert(0, str(HERE))
    import gate
    fixture = contextlib.ExitStack()
    fixture.enter_context(gate_stop_fixture(gate, root))
    fixture.enter_context(patch.dict(os.environ, {"MOTTORI_INSTANCE": str(root)}))
    return gate, fixture


def _restore(_gate, fixture):
    fixture.close()


def _run_check(gate, payload):
    """Run the Stop event's gate step through the dispatcher; the hook always exits 0."""
    return 0, hook_event("Stop", payload, "gate")


def test_H03_H04_stop_hook_active_passes_once_and_keeps_pending() -> None:
    """A reentrant Stop lets the turn end once; the unresolved finding stays pending."""
    root = Path(tempfile.mkdtemp(prefix="stop-active-"))
    gate, saved = _stop_fixture(root)
    try:
        gate._load_baseline = lambda: ({"linkcheck": set(), "now-check": set()}, "ok")
        gate.measure = lambda **_: gate.Measurement({"linkcheck": {"new-issue"}, "now-check": set()})
        Path(gate.EDITS()).write_text("1", encoding="utf-8")
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


def test_check_drops_retired_checkers_from_an_older_baseline() -> None:
    """A baseline saved while evidencecheck and manifest ran passes a Stop and loses their entries."""
    root = Path(tempfile.mkdtemp(prefix="retired-baseline-"))
    gate, saved = _stop_fixture(root)
    try:
        gate._save_baseline({"linkcheck": {"known", "fixed"}, "now-check": set(),
                             "evidencecheck": {"old-evidence"}, "manifest": {"old-manifest"}})
        gate.measure = lambda **_: gate.Measurement({"linkcheck": {"known"}, "now-check": set()})
        Path(gate.EDITS()).write_text("1", encoding="utf-8")
        code, output = _run_check(gate, {})
        assert code == 0 and output == "", output
        saved_issues, state = gate._load_baseline()
        assert state == "ok", state
        assert saved_issues == {"linkcheck": {"known"}, "now-check": set()}, saved_issues
        assert "evidencecheck" not in Path(gate.BASELINE).read_text(encoding="utf-8")
        assert not Path(gate.EDITS()).exists() and not Path(gate.PENDING()).exists()
    finally:
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_check_still_detects_a_removed_checker() -> None:
    root = Path(tempfile.mkdtemp(prefix="checker-removed-"))
    gate, saved = _stop_fixture(root)
    try:
        gate._save_baseline({"linkcheck": set(), "now-check": set(), "evidencecheck": set()})
        gate.measure = lambda **_: gate.Measurement({"now-check": set()})
        Path(gate.EDITS()).write_text("1", encoding="utf-8")
        code, output = _run_check(gate, {})
        reason = json.loads(output)["reason"]
        assert "linkcheck" in reason and "evidencecheck" not in reason, reason
    finally:
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_baseline_replaces_the_file_with_the_measurement() -> None:
    """`gate.py baseline` is how a checker removed from CHECKS is migrated away on purpose."""
    root = _repo()
    gate, saved = _stop_fixture(root / ".git")
    previous_root = os.environ.get("MOTTORI_INSTANCE")
    try:
        _set_root(root)
        gate._save_baseline({"linkcheck": {"old"}, "now-check": set(), "retired-checker": {"old"},
                             "evidencecheck": {"old-evidence"}})
        gate.measure = lambda **_: gate.Measurement({"linkcheck": set(), "now-check": set()})
        assert gate.cmd_baseline() == 0
        issues, state = gate._load_baseline()
        assert state == "ok" and issues == {"linkcheck": set(), "now-check": set()}, issues
    finally:
        _set_root(previous_root)
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_resume_reports_pending_reason_without_measuring() -> None:
    root = Path(tempfile.mkdtemp(prefix="resume-pending-"))
    gate, saved = _stop_fixture(root)
    previous_stdout = sys.stdout

    def forbidden(**_):
        raise AssertionError("resume must not measure")

    try:
        gate.measure = forbidden
        Path(gate.EDITS()).write_text("1", encoding="utf-8")
        resume = hook_event("UserPromptSubmit", {}, "resume")
        assert resume == "", "a dirty marker alone is left for the next Stop"
        Path(gate.PENDING()).write_text(json.dumps({"": {"reason": "linkcheck: README.md -> gone.md"}}),
                                        encoding="utf-8")
        resume = hook_event("UserPromptSubmit", {}, "resume")
        context = json.loads(resume)["hookSpecificOutput"]["additionalContext"]
        assert "README.md -> gone.md" in context, context
        assert Path(gate.PENDING()).exists() and Path(gate.EDITS()).exists()
    finally:
        sys.stdout = previous_stdout
        _restore(gate, saved)
        shutil.rmtree(root, ignore_errors=True)


def test_E1_rec_check_crash_is_doctor_fail() -> None:
    sys.path.insert(0, str(HERE))
    import doctor
    root = Path(tempfile.mkdtemp(prefix="doctor-ledger-"))
    facts = root / "_private" / "ledger" / "facts"
    facts.mkdir(parents=True)
    (facts / "one.md").write_text("fact\n", encoding="utf-8")
    old_root, old_sh = os.environ.get("MOTTORI_INSTANCE"), doctor.sh
    try:
        _set_root(root)

        class Result:
            returncode = 1
            stdout = ""
            stderr = "Traceback: synthetic crash"

        doctor.sh = lambda *args, **kwargs: Result()
        status, detail = doctor.c_ledger()
        assert status == doctor.FAIL and "synthetic crash" in detail

        class Quiet:
            returncode = 1
            stdout = "[check] problems: 0\n"
            stderr = ""

        doctor.sh = lambda *args, **kwargs: Quiet()
        assert doctor.c_ledger()[0] == doctor.FAIL, "a nonzero exit alone must fail"
    finally:
        _set_root(old_root)
        doctor.sh = old_sh
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_reads_tool_trailers_by_exit_code() -> None:
    """doctor takes facts.py's verdict from its exit code, not from its summary line."""
    sys.path.insert(0, str(HERE))
    import doctor
    root = Path(tempfile.mkdtemp(prefix="doctor-forms-"))
    facts = root / "_private" / "ledger" / "facts"
    facts.mkdir(parents=True)
    (facts / "one.md").write_text("fact\n", encoding="utf-8")
    old_root, old_sh = os.environ.get("MOTTORI_INSTANCE"), doctor.sh

    class Result:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout, self.stderr, self.returncode = stdout, "", returncode

    try:
        _set_root(root)
        # The exit code is the verdict whatever the summary line says.
        for out in ("[check] problems: 0\n", ""):
            doctor.sh = lambda *args, out=out, **kwargs: Result(out)
            status, _detail = doctor.c_ledger()
            assert status == doctor.PASS, (out, status)
        doctor.sh = lambda *args, **kwargs: Result("PROBLEM f1: x\n[check] problems: 1\n", 1)
        status, detail = doctor.c_ledger()
        assert status == doctor.FAIL and "f1: x" in detail, (status, detail)
        assert doctor.C.warning_text(("doctor.config_warn_missing", {"path": "/x"})) == "config missing: /x"
        assert doctor.PRECOMPACT_MARKER == "[system/state] compaction occurred"
    finally:
        _set_root(old_root)
        doctor.sh = old_sh
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_doctor_reads_tool_trailers_by_exit_code,
    test_G03_markdown_symlink_is_blocked,
    test_G04_submodule_gitlink_is_blocked,
    test_G02_unicode_markdown_path_is_not_git_quoted,
    test_S2_G1_a_forced_state_file_is_blocked_and_an_ordinary_file_is_not,
    test_enforce_messages_are_english,
    test_worker_refusals_are_english,
    test_H03_H04_stop_hook_active_passes_once_and_keeps_pending,
    test_check_drops_retired_checkers_from_an_older_baseline,
    test_baseline_replaces_the_file_with_the_measurement,
    test_check_still_detects_a_removed_checker,
    test_resume_reports_pending_reason_without_measuring,
    test_E1_rec_check_crash_is_doctor_fail,
    test_tracked_public_state_is_not_forbidden,
    test_N3_gitignore_exception_cannot_allow_new_instance_paths,
    test_repository_without_head_refuses_force_added_instance_paths,
    test_N6_baseline_refuses_when_control_plane_lock_is_unavailable,
    test_N6_first_sealed_baseline_is_the_only_implicit_adoption,
    test_tracked_markdown_symlink_in_head_is_not_reflagged,
    test_prepush_refuses_a_damaged_instance_and_a_private_path_and_allows_a_kit_tree,
    test_new_monthly_journal_allowed_when_journals_tracked,
    test_private_case_variant_is_forbidden,
    test_issues_without_index_is_a_usage_error,
    test_unmerged_entry_and_non_git_root_fail_closed,
    test_prepush_refuses_pushed_private_commit,
]


def main() -> int:
    failed: list[str] = []
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print("FAIL", test.__name__, type(error).__name__, error)
    print(f"enforce tests: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
