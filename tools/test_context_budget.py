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

from testlib import run_test


HERE = Path(__file__).resolve().parent
CONTEXT_BUDGET = HERE / "context_budget.py"
SESSION_HOOK = 'python3 "$CLAUDE_PROJECT_DIR/tools/now.py" hook-context'
DATE_HOOK = "date '+[now: %Y-%m-%d %H:%M %Z (%a)]'"
AGENTS_TEXT = "가나다abcd\n"            # 3 wide chars + 5 others -> 3 + ceil(5/4) = 5 tokens


def _key(path):
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path))


def _fixture(memory_index=None, thresholds=None):
    base = Path(tempfile.mkdtemp(prefix="context-budget-"))
    root, home = base / "inst", base / "home"
    (root / "system").mkdir(parents=True)
    (root / "state").mkdir()
    (root / "docs").mkdir()
    (root / ".claude").mkdir()
    home.mkdir()
    (root / "CLAUDE.md").write_text("@AGENTS.md\n@docs/extra.md\n`@docs/ignored.md`\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(AGENTS_TEXT, encoding="utf-8")
    (root / "docs" / "extra.md").write_text("x" * 100, encoding="utf-8")
    (root / "docs" / "ignored.md").write_text("y" * 5000, encoding="utf-8")
    (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": SESSION_HOOK}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": DATE_HOOK}]}],
    }}), encoding="utf-8")
    # Inline config: an installed instance has no templates/ folder to copy from.
    config = {
        "schema_version": 4,
        "instance": {"name": "fixture", "context": "personal", "remote_allowlist": []},
        "tracks": [], "threads": [], "personal_pointer": None,
        "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                               "legacy_public_tracks": []},
        "thresholds": dict(thresholds or {}),
    }
    (root / "system" / "memory-config.json").write_text(json.dumps(config), encoding="utf-8")
    if memory_index is not None:
        memdir = home / ".claude" / "projects" / _key(root) / "memory"
        memdir.mkdir(parents=True)
        (memdir / "MEMORY.md").write_text(memory_index, encoding="utf-8")
    return base, root, home


def _env(root, home):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root), HOME=str(home), MOTTORI_LANG="en")
    env.pop("MOTTORI_HOOK_CANARY", None)
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
        names = {part["name"]: part for part in item["parts"]}
        assert set(names) == {"CLAUDE.md", "AGENTS.md", "docs/extra.md"}, names
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
        assert limits["instructions"] == 8192 and limits["state"] == 5400
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
        assert set(names) == {"CLAUDE.md", "AGENTS.md", "한글지침.md", "docs/é-notes.md"}, names
        assert names["한글지침.md"]["bytes"] == 2400
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_state_warning_line_is_below_the_injection_cap():
    base, root, home = _fixture()
    try:
        limits = {row["key"]: row["limit"] for row in _json(root, home)["items"]}
        config = json.loads((HERE.parent / "templates" / "memory-config.json").read_text(encoding="utf-8")) \
            if (HERE.parent / "templates" / "memory-config.json").is_file() else None
        cap = (config or {}).get("thresholds", {}).get("now_hook_max_bytes", 6000)
        assert limits["state"] < cap, (limits["state"], cap)
        assert limits["state"] == 5400
        if config is not None:
            assert config["thresholds"]["context_state_max_bytes"] == 5400, config["thresholds"]
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
    test_state_warning_line_is_below_the_injection_cap,
]


if __name__ == "__main__":
    for test in TESTS:
        run_test(test, __file__)
        print("PASS", test.__name__)
