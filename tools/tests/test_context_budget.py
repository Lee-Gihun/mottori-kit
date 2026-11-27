#!/usr/bin/env python3
"""Fixture tests for the per-session fixed context measurement CLI."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent.parent
CONTEXT_BUDGET = HERE / "context_budget.py"
# The session start line stands for the state and reminder steps, the prompt line for the time.
SESSION_HOOK = 'sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" event SessionStart claude'
# A line of the launcher's direct form is not the kit's event line, so it is not run.
DIRECT_HOOK = 'sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" triggers.py hook || true'
DATE_HOOK = 'sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" event UserPromptSubmit claude'
AGENTS_TEXT = "가나다abcd\n"            # 3 wide chars + 5 others -> 3 + ceil(5/4) = 5 tokens


def _key(path):
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path))


def _fixture(memory_index=None, thresholds=None):
    base = Path(tempfile.mkdtemp(prefix="context-budget-"))
    root, home = base / "inst", base / "home"
    (root / "instance").mkdir(parents=True)
    (root / "state").mkdir()
    (root / "docs").mkdir()
    (root / ".claude").mkdir()
    home.mkdir()
    (root / "CLAUDE.md").write_text("@AGENTS.md\n@docs/extra.md\n`see @docs/ignored.md`\n"
                                    "```\n@docs/fenced.md\n```\n", encoding="utf-8")
    (root / "CLAUDE.local.md").write_text("local\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(AGENTS_TEXT, encoding="utf-8")
    (root / "docs" / "extra.md").write_text("x" * 100, encoding="utf-8")
    (root / "docs" / "ignored.md").write_text("y" * 5000, encoding="utf-8")
    (root / "docs" / "fenced.md").write_text("f" * 5000, encoding="utf-8")
    (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": SESSION_HOOK}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": DATE_HOOK}]}],
    }}), encoding="utf-8")
    # Inline config: an installed instance has no templates/ folder to copy from.
    config = {
        "schema_version": 4,
        "instance": {"name": "fixture"},
        "tracks": [], "threads": [], "personal_pointer": None,
        "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                               "legacy_public_tracks": []},
        "thresholds": dict(thresholds or {}),
    }
    (root / "instance" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if memory_index is not None:
        memdir = home / ".claude" / "projects" / _key(root) / "memory"
        memdir.mkdir(parents=True)
        (memdir / "MEMORY.md").write_text(memory_index, encoding="utf-8")
    return base, root, home


def _env(root, home):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root), HOME=str(home))
    # Under a probe the reminders hook prints nothing; these tests compare it with the measurement.
    env.pop("MOTTORI_HOOK_CANARY", None)
    env.pop("MOTTORI_INTERNAL_RUN", None)
    return env


def _run(root, home, *args, script=CONTEXT_BUDGET):
    return subprocess.run([sys.executable, str(script), *args], cwd=root,
                          env=_env(root, home), capture_output=True, text=True)


def _json(root, home):
    result = _run(root, home, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _item(report, key):
    return next(row for row in report["items"] if row["key"] == key)


def _tree(*dirs):
    out = {}
    for d in dirs:
        for path in Path(d).rglob("*"):
            info = path.lstat()
            out[str(path)] = (info.st_size, info.st_mtime_ns)
    return out


def test_instruction_files_follow_imports_and_count_tokens():
    base, root, home = _fixture()
    try:
        report = _json(root, home)
        item = _item(report, "instructions")
        # A list, not a set: CLAUDE.md imports AGENTS.md, and AGENTS.md must still be counted once.
        assert sorted(part["name"] for part in item["parts"]) == [
            "AGENTS.md", "CLAUDE.local.md", "CLAUDE.md", "docs/extra.md"], item["parts"]
        names = {part["name"]: part for part in item["parts"]}
        assert names["AGENTS.md"]["bytes"] == len(AGENTS_TEXT.encode("utf-8"))
        assert names["AGENTS.md"]["chars"] == len(AGENTS_TEXT)
        assert names["AGENTS.md"]["tokens"] == 5
        assert names["docs/extra.md"]["tokens"] == 25
        assert item["bytes"] == sum(part["bytes"] for part in item["parts"])
        assert report["total"]["bytes"] == sum(row["bytes"] for row in report["items"])
        assert len(report["top"]) == 3
        assert report["top"][0]["bytes"] >= report["top"][1]["bytes"] >= report["top"][2]["bytes"]
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_state_matches_hook_context_when_snapshots_are_fresh():
    base, root, home = _fixture()
    try:
        rendered = _run(root, home, "render", script=HERE / "now.py")
        assert rendered.returncode == 0, rendered.stderr
        before = _tree(root, home)
        state = _item(_json(root, home), "state")
        assert _tree(root, home) == before
        context = _run(root, home, "context", script=HERE / "now.py")
        assert context.returncode == 0, context.stderr
        assert state["method"] == "exact", state
        assert state["bytes"] == len(context.stdout.encode("utf-8")), state
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_stale_state_is_estimated_without_writing_any_file():
    base, root, home = _fixture(memory_index="- [A](a.md)\n")
    try:
        (root / "state" / "NOW.md").write_text("# NOW\n" + "z" * 300, encoding="utf-8")
        before = _tree(root, home)
        report = _json(root, home)
        table = _run(root, home)
        assert table.returncode == 0, table.stderr
        assert _tree(root, home) == before
        state = _item(report, "state")
        assert state["method"] == "estimate" and state["bytes"] == 306, state
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_session_hook_matches_trigger_hook_output():
    base, root, home = _fixture()
    try:
        added = _run(root, home, "add", "--when", "date:2000-01-01", "--what", "트리거 본문",
                     script=HERE / "triggers.py")
        assert added.returncode == 0, added.stderr
        with open(root / "_private" / "triggers" / "triggers.jsonl", "a") as fh:   # the hook still injects then
            fh.write("{bad\n")
        measured = _item(_json(root, home), "session_hooks")
        hook = _run(root, home, "hook", "--format", "text", script=HERE / "triggers.py")
        assert hook.returncode == 0, hook.stderr
        # print() adds one newline after the injected body.
        assert measured["bytes"] == len(hook.stdout.encode("utf-8")) - 1, (measured, hook.stdout)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_memory_index_absent_is_reported_not_zero_warning():
    base, root, home = _fixture()
    try:
        report = _json(root, home)
        memory = _item(report, "memory_index")
        assert memory["method"] == "absent" and memory["bytes"] == 0 and not memory["over"]
        table = _run(root, home)
        assert "absent" in table.stdout, table.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_thresholds_mark_items_and_hint_subindex():
    base, root, home = _fixture(memory_index="- line\n" * 200,
                                thresholds={"context_memory_index_max_bytes": 1000,
                                            "context_fixed_max_bytes": 1500})
    try:
        report = _json(root, home)
        memory = _item(report, "memory_index")
        assert memory["bytes"] == 1400 and memory["limit"] == 1000 and memory["over"], memory
        assert _item(report, "instructions")["limit"] == 8192
        assert not _item(report, "instructions")["over"]
        assert report["total"]["over"] and report["total"]["limit"] == 1500
        assert set(report["warnings"]) == {"memory_index", "total"}, report["warnings"]
        table = _run(root, home)
        assert table.returncode == 0, table.stderr
        assert "-index.md" in table.stdout, table.stdout
        assert table.stdout.count("OVER") >= 2, table.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_defaults_do_not_warn_on_small_install():
    base, root, home = _fixture(memory_index="- [A](a.md)\n")
    try:
        report = _json(root, home)
        assert report["warnings"] == [], report
        limits = {row["key"]: row["limit"] for row in report["items"]}
        assert limits["instructions"] == 8192 and limits["state"] is None
        assert limits["memory_index"] == 12288 and report["total"]["limit"] == 24576
        prompt = next(row for row in report["items"] if row["key"] == "prompt_hooks")
        assert [part["name"] for part in prompt["parts"]] == ["date"], prompt
        assert prompt["parts"][0]["bytes"] > 20
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_non_ascii_import_paths_are_counted():
    base, root, home = _fixture()
    try:
        (root / "한글지침.md").write_text("가" * 800, encoding="utf-8")
        (root / "docs" / "é-notes.md").write_text("z" * 40, encoding="utf-8")
        (root / "CLAUDE.md").write_text("@AGENTS.md\n@한글지침.md\n@docs/é-notes.md\n@없는파일.md\n",
                                        encoding="utf-8")
        item = _item(_json(root, home), "instructions")
        names = {part["name"]: part for part in item["parts"]}
        assert set(names) == {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "한글지침.md",
                              "docs/é-notes.md"}, names
        assert names["한글지침.md"]["bytes"] == 2400
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_state_at_the_injection_cap_does_not_warn():
    # The injector caps state itself, so state filling up to the cap is normal, not a warning.
    base, root, home = _fixture()
    try:
        (root / "state" / "NOW.md").write_text("# NOW\n" + ("z" * 99 + "\n") * 80, encoding="utf-8")
        report = _json(root, home)
        assert 5400 < _item(report, "state")["bytes"] <= 6000, _item(report, "state")
        assert "state" not in report["warnings"], report["warnings"]
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_hooks_that_are_not_measured_are_counted():
    base, root, home = _fixture()
    try:
        (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": SESSION_HOOK},
                                        {"type": "command", "command": DIRECT_HOOK}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": DATE_HOOK}]}],
        }}), encoding="utf-8")
        report = _json(root, home)
        assert report["unmeasured"] == 1, report.get("unmeasured")
        assert _item(report, "session_hooks")["method"] == "partial", _item(report, "session_hooks")
        assert _item(report, "prompt_hooks")["method"] == "measured"
        assert "partial" in _run(root, home).stdout
        store = root / "_private" / "triggers" / "triggers.jsonl"
        store.parent.mkdir(parents=True)
        store.write_text("{}\n", encoding="utf-8")
        # Unreadable lines are measured now, so only a store that cannot be opened stays unmeasured.
        store.chmod(0)
        try:
            report = _json(root, home)
        finally:
            store.chmod(0o600)
        assert report["unmeasured"] == 2, report.get("unmeasured")
        # A command that is not a string is a hook not measured, never a crash.
        (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": 5},
                                        {"type": "command", "command": None}]}],
        }}), encoding="utf-8")
        assert _json(root, home)["unmeasured"] == 2
        # A hook that is not declared costs zero, even when its source has content.
        (root / "state" / "NOW.md").write_text("# NOW\n" + "z" * 300, encoding="utf-8")
        (root / ".claude" / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
        report = _json(root, home)
        assert _item(report, "state")["bytes"] == 0 and report["unmeasured"] == 0, report
        # A malformed or blank declaration names its file instead of crashing or counting zero.
        for text in ('{"hooks": {"SessionStart": null}}', ""):
            (root / ".claude" / "settings.json").write_text(text, encoding="utf-8")
            report = _json(root, home)
            assert ".claude/settings.json" in " ".join(_item(report, "session_hooks")["notes"]), report
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_measuring_writes_no_arming_verdict():
    """The arming line is measured from doctor's verdicts as they stand. Measuring writes
    nothing, even when the verdict of the runtime it measures for says its hooks do not run."""
    base, root, home = _fixture()
    try:
        verdicts = root / "state" / ".mottori-runtime-arming"
        verdicts.write_text(json.dumps({"claude": {"armed": False, "at": "2026-11-01"},
                                        "codex": {"armed": False, "at": "2026-11-02"}}),
                            encoding="utf-8")
        before = _tree(root, home)
        stored = verdicts.read_bytes()
        report = _json(root, home)
        assert verdicts.read_bytes() == stored and _tree(root, home) == before
        unarmed = [part for part in _item(report, "session_hooks")["parts"]
                   if part["name"] == "hookdiag.py unarmed"]
        assert unarmed and unarmed[0]["bytes"] > 0, report
    finally:
        shutil.rmtree(base, ignore_errors=True)


TESTS = [
    test_instruction_files_follow_imports_and_count_tokens,
    test_state_matches_hook_context_when_snapshots_are_fresh,
    test_stale_state_is_estimated_without_writing_any_file,
    test_session_hook_matches_trigger_hook_output,
    test_memory_index_absent_is_reported_not_zero_warning,
    test_thresholds_mark_items_and_hint_subindex,
    test_defaults_do_not_warn_on_small_install,
    test_non_ascii_import_paths_are_counted,
    test_state_at_the_injection_cap_does_not_warn,
    test_hooks_that_are_not_measured_are_counted,
    test_measuring_writes_no_arming_verdict,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
