#!/usr/bin/env python3
"""recall.py, recall_literal.py, transcripts.py and paths transcript discovery regressions."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path.insert(0, os.path.join(TOOLS, "dev"))
RECALL = os.path.join(HERE, "recall.py")


def fixture():
    base = tempfile.mkdtemp(prefix="recall-fixture-")
    root = os.path.join(base, "instance with.dot_한글")
    home = os.path.join(base, "home")
    os.makedirs(root)
    os.makedirs(os.path.join(home, ".codex", "sessions"))
    return base, root, home


def env(root, home):
    # Assertions below read Korean output; English output is covered by its own test.
    return dict(os.environ, MOTTORI_INSTANCE=root, HOME=home)


def run(script, root, home, *args):
    return subprocess.run([sys.executable, script, *args], cwd=root,
                          env=env(root, home), capture_output=True, text=True)


def write_rollout(home, name, cwd, messages, *, subagent=False, session_id=None):
    path = os.path.join(home, ".codex", "sessions", name + ".jsonl")
    payload = {"cwd": cwd, "id": session_id or name}
    if subagent:
        payload.update({"thread_source": "subagent", "parent_thread_id": "parent"})
    rows = [{"type": "session_meta", "payload": payload}]
    for i, (role, text) in enumerate(messages):
        rows.append({
            "timestamp": f"2026-09-17T00:{i:02d}:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": role,
                "content": [{
                    "type": "input_text" if role == "user" else "output_text",
                    "text": text,
                }],
            },
        })
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def test_transcript_directory_mangling():
    base, root, home = fixture()
    try:
        code = ("import sys; sys.path.insert(0, %r); import paths; "
                "print(paths.mangle_project_key(%r)); print(paths.transcripts())" %
                (os.path.join(HERE, "lib"), root))
        result = subprocess.run([sys.executable, "-c", code], env=env(root, home),
                                capture_output=True, text=True)
        expected = "".join(ch if ch.isascii() and (ch.isalnum() or ch == "-") else "-"
                           for ch in root)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert lines == [expected, os.path.join(home, ".claude", "projects", expected)]
        assert " " not in expected and "." not in expected and "_" not in expected
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_other_cwd_rollout_is_excluded_by_default():
    base, root, home = fixture()
    try:
        write_rollout(home, "own", root, [("user", "INSTANCE-BOUNDARY-CANARY own")])
        write_rollout(home, "other", root + "-other",
                      [("user", "INSTANCE-BOUNDARY-CANARY other")])
        result = run(RECALL, root, home, "find", "INSTANCE-BOUNDARY-CANARY",
                     "--source", "codex", "--order", "oldest")
        assert result.returncode == 0, result.stderr
        assert "own" in result.stdout and "other" not in result.stdout

        opened = run(RECALL, root, home, "find", "INSTANCE-BOUNDARY-CANARY",
                     "--source", "codex", "--order", "oldest", "--all-instances")
        assert "own" in opened.stdout and "other" in opened.stdout

        # A list-valued cwd, or a first line that is not session_meta naming this folder, is
        # skipped and counted; neither stops the search nor lends the session this folder.
        listed = write_rollout(home, "listed", root, [("user", "INSTANCE-BOUNDARY-CANARY listed")])
        joined = write_rollout(home, "joined", root + "-other",
                               [("user", "INSTANCE-BOUNDARY-CANARY joined")])
        for path, first in ((listed, {"type": "session_meta", "payload": {"cwd": [root]}}),
                            (joined, {"type": "turn_context", "payload": {"cwd": root}})):
            with open(path, encoding="utf-8") as f:
                rows = f.readlines()
            with open(path, "w", encoding="utf-8") as f:
                f.writelines([json.dumps(first) + "\n"] + rows[(path == listed):])
        result = run(RECALL, root, home, "find", "INSTANCE-BOUNDARY-CANARY", "--source", "codex")
        assert result.returncode == 0, result.stderr
        assert "own" in result.stdout and "listed" not in result.stdout, result.stdout
        assert "joined" not in result.stdout and "Records skipped as malformed" in result.stdout, result.stdout
        assert "): 2." in result.stdout, result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_authored_only_excludes_agents_and_system_injection():
    base, root, home = fixture()
    try:
        write_rollout(home, "owner", root, [
            ("user", "AUTHORED-CANARY owner words"),
            ("assistant", "AUTHORED-CANARY assistant words"),
            ("user", "# AGENTS.md instructions\nAUTHORED-CANARY injected words"),
        ])
        write_rollout(home, "agent", root,
                      [("user", "AUTHORED-CANARY copied agent words")], subagent=True)
        result = run(RECALL, root, home, "find", "AUTHORED-CANARY", "--source", "codex",
                     "--order", "oldest", "--max", "10")
        assert result.returncode == 0, result.stderr
        assert "owner words" in result.stdout and "assistant words" in result.stdout
        assert "injected words" not in result.stdout and "copied agent words" not in result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_sessions_default_is_40():
    base, root, home = fixture()
    try:
        for i in range(45):
            path = write_rollout(home, f"session-{i:02d}", root, [("user", f"turn {i}")])
            os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))
        result = run(RECALL, root, home, "sessions")
        rows = [line for line in result.stdout.splitlines() if line.startswith("[codex ")]
        assert result.returncode == 0, result.stderr
        assert len(rows) == 40
        # The newest are listed: the last written is in, the first written is out.
        assert "session-44" in result.stdout and "session-00" not in result.stdout
        assert "(40/45 shown, newest first" in result.stdout, result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def write_claude(home, root, name, rows):
    key = "".join(c if c.isascii() and (c.isalnum() or c == "-") else "-" for c in root)
    folder = os.path.join(home, ".claude", "projects", key)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def owner_row(text, ident="owner", *, summary=False, stamp="2026-09-17T00:00:00Z"):
    return {"type": "user", "uuid": ident, "sessionId": "fixture-owner",
            "timestamp": stamp, "isCompactSummary": summary,
            "message": {"content": text}}


def json_find(root, home, pattern, *args):
    result = run(RECALL, root, home, "find", pattern, "--json", "--around", "0", *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def archive_copy(home, path):
    folder = os.path.join(home, ".codex", "archived_sessions")
    os.makedirs(folder, exist_ok=True)
    return shutil.copy2(path, os.path.join(folder, os.path.basename(path)))


def write_alias_config(root, alias):
    os.makedirs(os.path.join(root, "instance"), exist_ok=True)
    with open(os.path.join(root, "instance", "config.json"), "w") as f:
        json.dump({"schema_version": 4, "instance": {
            "name": "fixture", "root_aliases": [alias]},
            "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                                   "legacy_public_tracks": []}}, f)


def test_claude_text_and_legacy_content_blocks():
    base, root, home = fixture()
    try:
        write_claude(home, root, "owner", [
            None, ["not a message"],
            owner_row([{"type": "text", "text": "형식카나리 native"}], "native"),
            owner_row([{"type": "text", "content": "형식카나리 legacy"}], "legacy"),
            owner_row([{"type": "tool_result", "content": "형식카나리 tool"}], "tool"),
            owner_row([{"type": "tool_result", "content": "tool output"},
                       {"type": "text", "text": "형식카나리 mixed tool transport"}], "mixed"),
            # Wrongly typed nested fields skip their own record, not the whole search.
            {"type": "user", "message": "형식카나리 not an object"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": 5}]}},
            {**owner_row("형식카나리 session list"), "sessionId": ["s"]},
            {**owner_row("형식카나리 number stamp"), "timestamp": 5},
            {**owner_row("형식카나리 session number", "number"), "sessionId": 5},
            {**owner_row("형식카나리 session zero", "zero"), "sessionId": 0},
        ])
        path = write_rollout(home, "codex", root, [("user", "형식카나리 codex")])
        with open(path, "a", encoding="utf-8") as f:
            for payload in ("형식카나리 payload", {"type": "message", "role": "user", "content": 5},
                            {"type": "message", "role": "user",
                             "content": [{"type": "input_text", "text": 5}]}):
                f.write(json.dumps({"type": "response_item", "payload": payload}) + "\n")
            f.write(json.dumps({"type": "response_item", "message": "x", "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "형식카나리 field"}]}}) + "\n")
        result = run(RECALL, root, home, "find", "형식카나리", "--json", "--around", "0",
                     "--role", "user")
        rows = json.loads(result.stdout)
        assert sorted(r["text"] for r in rows) == [
            "형식카나리 codex", "형식카나리 field", "형식카나리 legacy", "형식카나리 native",
            "형식카나리 session number", "형식카나리 session zero"], rows
        assert [r["session_id"] for r in rows if r["message_id"] == "number"] == ["5"], rows
        # A zero id reads as no id, as before ids were type checked, so the row keeps the
        # session read before it.
        assert [r["session_id"] for r in rows if r["message_id"] == "zero"] == ["5"], rows
        # null, a list row, the list session id and the number timestamp.
        assert "Records skipped as malformed" in result.stderr and "): 4." in result.stderr, result.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_summary_cannot_occupy_user_score_slot():
    base, root, home = fixture()
    try:
        write_claude(home, root, "owner", [
            owner_row("요약카나리 actual", "actual"),
            owner_row("요약카나리 " * 30, "summary", summary=True),
        ])
        rows = json_find(root, home, "요약카나리", "--role", "user", "--max", "1")
        assert len(rows) == 1 and rows[0]["message_id"] == "actual", rows
        diagnostic = json_find(root, home, "요약카나리", "--include-system", "--max", "1")
        assert diagnostic[0]["origin"] == "summary", diagnostic
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_codex_injection_cannot_occupy_user_score_slot():
    base, root, home = fixture()
    try:
        write_rollout(home, "owner", root, [
            ("user", "주입카나리 actual"),
            ("user", "# AGENTS.md instructions\n" + "주입카나리 " * 30),
        ])
        rows = json_find(root, home, "주입카나리", "--role", "user", "--max", "1")
        assert len(rows) == 1 and rows[0]["text"] == "주입카나리 actual", rows
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_ambient_envelope_keeps_actual_request():
    base, root, home = fixture()
    try:
        request = '<in-app-browser-context source="ambient-ui-state">자동문맥</in-app-browser-context>'
        write_rollout(home, "owner", root, [
            ("user", request + "\n\n## My request:\n봉투카나리 실제 질문"),
            ("user", request),
            ("user", "<custom>봉투카나리 사용자가 쓴 XML</custom>"),
            # Codex can put its instructions or internal context before the typed text.
            ("user", "<user_instructions>\n자동문맥\n</user_instructions>\n봉투카나리 지침 뒤 질문"),
            ("user", "<codex_internal_context>자동문맥</codex_internal_context>\n봉투카나리 문맥 뒤"),
            ("user", "<user_instructions>자동문맥 봉투카나리</user_instructions>"),
        ])
        write_claude(home, root, "owner", [owner_row(
            '<environment_context>자동문맥</environment_context>\n봉투카나리 Claude 질문')])
        rows = json_find(root, home, "봉투카나리", "--role", "user")
        assert len(rows) == 5, rows
        assert all("자동문맥" not in r["text"] for r in rows), rows
        assert any(r["text"].startswith("<custom>") for r in rows), rows
        assert json_find(root, home, "자동문맥", "--role", "user") == []
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_archive_uses_same_cwd_and_subagent_boundary():
    base, root, home = fixture()
    try:
        for name, cwd, sub in [("own", root, False), ("other", root + "-other", False),
                               ("unknown", None, False), ("agent", root, True)]:
            path = write_rollout(home, name, cwd, [("user", "보관카나리 " + name)], subagent=sub)
            archive_copy(home, path)
            os.unlink(path)
        rows = json_find(root, home, "보관카나리", "--role", "user")
        assert [r["text"] for r in rows] == ["보관카나리 own"], rows
        assert "/archived_sessions/" in rows[0]["path"]
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_active_archive_dedup_keeps_distinct_repeated_turns():
    base, root, home = fixture()
    try:
        path = write_rollout(home, "owner", root,
                             [("user", "반복카나리 ㅇㅇ"), ("user", "반복카나리 ㅇㅇ")])
        archive_copy(home, path)
        rows = json_find(root, home, "반복카나리", "--role", "user")
        assert len(rows) == 2 and len({r["record_id"] for r in rows}) == 2, rows
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_native_ids_dedup_copied_claude_alias_and_keep_old_only_turn():
    base, root, home = fixture()
    try:
        alias = os.path.join(base, "previous_name")
        write_alias_config(root, alias)
        shared = owner_row("별칭카나리 copied", "shared")
        # The copy's stamp differs, so only the native uuid can merge the two.
        copy = owner_row("별칭카나리 copied", "shared", stamp="2026-09-18T00:00:00Z")
        write_claude(home, root, "owner", [shared])
        write_claude(home, alias, "owner", [copy, owner_row("별칭카나리 old-only", "old")])
        rows = json_find(root, home, "별칭카나리", "--role", "user")
        assert {r["message_id"] for r in rows} == {"shared", "old"} and len(rows) == 2, rows
        path = write_rollout(home, "old-cwd", alias, [("user", "옛경로카나리")])
        archive_copy(home, path)
        os.unlink(path)
        assert len(json_find(root, home, "옛경로카나리", "--role", "user")) == 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_agent_handbacks_are_not_owner_authority():
    base, root, home = fixture()
    try:
        write_claude(home, root, "owner", [
            owner_row("권위카나리 actual", "actual"),
            owner_row("Another Claude session sent a message:\n권위카나리 report", "report"),
            owner_row(f"Base directory for this skill: {root}\n권위카나리 skill", "skill"),
        ])
        rows = json_find(root, home, "권위카나리", "--role", "user")
        assert [r["message_id"] for r in rows] == ["actual"], rows
        diagnostic = json_find(root, home, "권위카나리", "--include-agents", "--include-system")
        assert {r["origin"] for r in diagnostic} == {"user", "agent", "system"}, diagnostic
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_claude_meta_transport_is_not_owner_but_quoted_feedback_survives():
    base, root, home = fixture()
    try:
        injected = owner_row("Stop hook feedback: META-CANARY " * 8, "hook")
        injected["isMeta"] = True
        ordinary = owner_row("Stop hook feedback: META-CANARY is the text I am asking about", "human")
        ordinary["isMeta"] = False
        # A message typed while the assistant works is stored once, as a queued_command
        # attachment; its origin says whether a person typed it.
        def queued(ident, kind, prompt):
            origin = {"kind": kind} if kind else None
            return {"type": "attachment", "uuid": ident, "sessionId": "fixture-owner",
                    "timestamp": "2026-09-17T00:01:00Z",
                    "attachment": {"type": "queued_command", "prompt": prompt, "origin": origin}}
        typed = queued("typed", "human", "META-CANARY typed mid-turn")
        parts = queued("parts", "human", [{"type": "text", "text": "META-CANARY in parts"}])
        legacy = queued("legacy", None, "META-CANARY before origins were written")
        notice = queued("notice", "task-notification", "META-CANARY task finished")
        peer = queued("peer", "peer", "META-CANARY from another session")
        resumed = owner_row("META-CANARY continue automatically", "resumed")
        resumed["origin"] = {"kind": "auto-continuation"}
        # The same instant and text again, as a forked session copies it: one message.
        copy = dict(typed, uuid="typed-copy", sessionId="fork")
        write_claude(home, root, "owner", [injected, ordinary, typed, parts, legacy, notice, peer,
                                           resumed, copy])
        rows = json_find(root, home, "META-CANARY", "--role", "user", "--max", "9")
        assert sorted(r["message_id"] for r in rows) == ["human", "legacy", "parts", "typed"], rows
        diagnostic = json_find(root, home, "META-CANARY", "--include-system", "--include-agents",
                               "--max", "9")
        assert {r["message_id"]: r["origin"] for r in diagnostic} == {
            "human": "user", "hook": "system", "typed": "user", "parts": "user",
            "legacy": "user", "notice": "system", "peer": "agent", "resumed": "system"}, diagnostic
    finally:
        shutil.rmtree(base, ignore_errors=True)


def slash_command(args):
    """A slash-command row's content in the shape Claude Code writes it."""
    return ("<command-name>/goal</command-name>\n            <command-message>goal</command-message>"
            f"\n            <command-args>{args}</command-args>")


def test_slash_command_args_are_the_owners_words():
    """What the owner typed after a slash command is theirs, and is the row's whole text; a
    command typed without words stays a runtime row."""
    import transcripts as T
    base, root, home = fixture()
    try:
        typed = owner_row(slash_command("SLASH-CANARY finish the draft"), "typed")
        bare = owner_row(slash_command(""), "bare")
        write_claude(home, root, "owner", [typed, bare])
        rows = json_find(root, home, "SLASH-CANARY", "--role", "user", "--max", "9")
        assert [(r["message_id"], r["origin"]) for r in rows] == [("typed", "user")], rows
        assert T.text_of_claude(typed) == ("user", "SLASH-CANARY finish the draft")
        assert T._is_system_injected(T.text_of_claude(bare)[1])
        diagnostic = json_find(root, home, "goal", "--include-system", "--max", "9")
        assert {r["message_id"]: r["origin"] for r in diagnostic}.get("bare") == "system", diagnostic
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_locator_and_context_point_to_original_record():
    base, root, home = fixture()
    try:
        path = write_rollout(home, "owner", root, [
            ("assistant", "앞 문맥"), ("user", "위치카나리 실제"), ("assistant", "뒤 문맥")])
        rows = json_find(root, home, "위치카나리", "--role", "user", "--around", "1")
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["path"] == path and row["line"] == 3 and row["session_id"] == "owner", row
        assert row["before"][0]["text"] == "앞 문맥" and row["after"][0]["text"] == "뒤 문맥", row
        assert json_find(root, home, "ABSENT-CA13-PLANTED", "--role", "user") == []
    finally:
        shutil.rmtree(base, ignore_errors=True)


def write_stamped_rollout(home, name, cwd, rows):
    """Write a rollout whose messages carry the given (role, text, timestamp) rows."""
    path = os.path.join(home, ".codex", "sessions", name + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "session_meta", "payload": {"cwd": cwd, "id": name}}) + "\n")
        for role, text, stamp in rows:
            f.write(json.dumps({"timestamp": stamp, "type": "response_item", "payload": {
                "type": "message", "role": role, "content": [{
                    "type": "input_text" if role == "user" else "output_text",
                    "text": text}]}}, ensure_ascii=False) + "\n")
    return path


def test_since_uses_local_date():
    base, root, home = fixture()
    try:
        write_stamped_rollout(home, "owner", root,
                              [("user", "SINCE-CANARY morning", "2026-11-17T23:30:00Z")])
        e = dict(env(root, home), TZ="Asia/Seoul")

        def hits(since):
            r = subprocess.run([sys.executable, RECALL, "find", "SINCE-CANARY", "--json",
                                "--since", since], cwd=root, env=e, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            return json.loads(r.stdout)

        # 23:30 UTC on the 17th is 08:30 on the 18th in Seoul, the date the listing shows.
        assert len(hits("2026-11-18")) == 1
        assert hits("2026-11-19") == []
        # A year-old nanosecond stamp is placed, not kept as unknown; a stamp that does not
        # parse is left out and counted rather than shown as if it were recent.
        write_stamped_rollout(home, "undated", root, [
            ("user", "SINCE-CANARY old", "2025-01-01T00:00:00.123456789Z"),
            ("user", "SINCE-CANARY junk", "not a time")])
        assert [r["text"] for r in hits("2026-11-18")] == ["SINCE-CANARY morning"]
        r = subprocess.run([sys.executable, RECALL, "find", "SINCE-CANARY", "--since",
                            "2026-11-18"], cwd=root, env=e, capture_output=True, text=True)
        assert "morning" in r.stdout and "junk" not in r.stdout, r.stdout
        assert "--since" in r.stdout and "): 1." in r.stdout, r.stdout
        bad = subprocess.run([sys.executable, RECALL, "find", "SINCE-CANARY", "--since",
                              "2026-11-8"], cwd=root, env=e, capture_output=True, text=True)
        assert bad.returncode == 2 and "--since" in bad.stderr, (bad.returncode, bad.stderr)
        assert "Traceback" not in bad.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_role_filter_drops_the_other_role():
    base, root, home = fixture()
    try:
        write_rollout(home, "owner", root, [("user", "ROLE-CANARY owner"),
                                            ("assistant", "ROLE-CANARY assistant")])
        users = json_find(root, home, "ROLE-CANARY", "--role", "user")
        assert [r["text"] for r in users] == ["ROLE-CANARY owner"], users
        helpers = json_find(root, home, "ROLE-CANARY", "--role", "assistant")
        assert [r["text"] for r in helpers] == ["ROLE-CANARY assistant"], helpers
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_dangling_transcript_is_skipped():
    base, root, home = fixture()
    try:
        write_rollout(home, "owner", root, [("user", "DANGLING-CANARY kept")])
        os.symlink(os.path.join(base, "nowhere.jsonl"),
                   os.path.join(home, ".codex", "sessions", "gone.jsonl"))
        found = run(RECALL, root, home, "find", "DANGLING-CANARY")
        assert found.returncode == 0, found.stderr
        assert "DANGLING-CANARY kept" in found.stdout, found.stdout
        listing = run(RECALL, root, home, "sessions")
        assert listing.returncode == 0, listing.stderr
        assert "owner.jsonl" in listing.stdout and "gone.jsonl" not in listing.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_bad_find_arguments_are_usage_errors():
    base, root, home = fixture()
    try:
        write_rollout(home, "owner", root, [("user", "ARG-CANARY words")])
        for args, needle in ((["ARG-CANARY", "--source", "codx"], "codx"),
                             (["ARG-CANARY", "--source", "all,codx"], "codx"),
                             (["", "--source", "codex"], "PATTERN"),
                             (["   "], "PATTERN"),
                             (["ARG-CANARY", "--max", "0"], "--max"),
                             (["ARG-CANARY", "--around", "-1"], "--around"),
                             (["--before", "2026-09-17 10:00", "--minutes", "-1"],
                              "--minutes must be 0 or more")):
            r = run(RECALL, root, home, "find", *args)
            assert r.returncode == 2, (args, r.returncode, r.stdout, r.stderr)
            assert needle in r.stderr and "Traceback" not in r.stderr, (args, r.stderr)
        # The unknown-source message names the configured sources.
        r = run(RECALL, root, home, "find", "ARG-CANARY", "--source", "codx")
        assert "codex" in r.stderr and "claude" in r.stderr, r.stderr
        assert run(RECALL, root, home, "find", "ARG-CANARY", "--source", "all").returncode == 0
        assert run(RECALL, root, home, "find", "ARG-CANARY", "--source", "codex,claude").returncode == 0
        # "all" inside a list still means every source, not only the other names.
        assert "ARG-CANARY words" in run(RECALL, root, home, "find", "ARG-CANARY",
                                         "--source", "claude,all").stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_order_and_context_stay_inside_their_file():
    base, root, home = fixture()
    try:
        older = write_stamped_rollout(home, "older", root, [
            ("user", "ORDER-CANARY early", "2026-09-17T00:00:00Z"),
            ("user", "ORDER-CANARY late", "2026-09-17T05:00:00Z"),
            ("assistant", "PREVIOUS-FILE-TAIL", "2026-09-17T05:01:00Z")])
        newer = write_stamped_rollout(home, "newer", root, [
            ("user", "CONTEXT-CANARY first line", "2026-09-18T00:00:00Z")])
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_700_000_100, 1_700_000_100))
        recent = json_find(root, home, "ORDER-CANARY", "--order", "recent", "--scan-all")
        assert recent[0]["text"] == "ORDER-CANARY late", recent
        oldest = json_find(root, home, "ORDER-CANARY", "--order", "oldest", "--scan-all")
        assert oldest[0]["text"] == "ORDER-CANARY early", oldest
        # Recent order compares instants: the +09:00 New Year stamp is an hour earlier than the
        # UTC one, a nanosecond fraction still parses, and a stamp that does not parse goes last.
        write_stamped_rollout(home, "newyear", root, [
            ("user", "NEWYEAR-CANARY earlier", "2027-01-01T00:30:00+09:00"),
            ("user", "NEWYEAR-CANARY undated", "sometime"),
            ("user", "NEWYEAR-CANARY later", "2026-12-31T16:30:00.123456789Z")])
        recent = json_find(root, home, "NEWYEAR-CANARY", "--order", "recent", "--scan-all")
        assert [r["text"].split()[1] for r in recent] == ["later", "earlier", "undated"], recent
        assert recent[0]["timestamp"] == "2026-12-31T16:30:00.123456789Z", recent
        # Oldest-first reading puts the older file's last line right before this hit.
        rows = json_find(root, home, "CONTEXT-CANARY", "--around", "2", "--scan-all")
        assert len(rows) == 1 and rows[0]["before"] == [], rows
    finally:
        shutil.rmtree(base, ignore_errors=True)



def test_eval_matches_record_id_not_same_minute():
    import eval_recall
    assert not eval_recall._retrieved_id('[{"record_id":"different","timestamp":"2026-10-08T10:01"}]', "wanted")
    assert eval_recall._retrieved_id('[{"record_id":"wanted"}]', "wanted")
    assert not eval_recall._retrieved_id("not json", "wanted")



def mangle(path):
    return "".join(c if c.isascii() and (c.isalnum() or c == "-") else "-" for c in path)


def claude_row(text, ident, stamp="2026-09-17T00:00:00Z"):
    return {"type": "user", "uuid": ident, "sessionId": "fixture", "timestamp": stamp,
            "message": {"content": text}}


def test_missing_transcript_dir_never_borrows_another_project():
    base, root, home = fixture()
    try:
        # A different project whose folder name merely ends with this instance's basename.
        foreign = os.path.join(home, ".claude", "projects",
                               "-Users-someoneelse-clientwork-" + mangle(os.path.basename(root)))
        os.makedirs(foreign)
        with open(os.path.join(foreign, "s1.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(claude_row("OTHER-PROJECT secret words", "x")) + "\n")
        code = ("import sys; sys.path.insert(0, %r); import paths; print(paths.transcripts())"
                % os.path.join(HERE, "lib"))
        got = subprocess.run([sys.executable, "-c", code], env=env(root, home),
                             capture_output=True, text=True)
        assert got.stdout.strip() == os.path.join(home, ".claude", "projects", mangle(root)), got
        result = run(RECALL, root, home, "find", "OTHER-PROJECT")
        assert result.returncode == 0, result.stderr
        assert "secret words" not in result.stdout, result.stdout
        assert "No Claude conversation records exist for this folder yet" in result.stdout, result.stdout
        rows = json_find(root, home, "OTHER-PROJECT")
        assert rows == [], rows
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_regex_special_characters_fall_back_to_literal_text():
    base, root, home = fixture()
    try:
        write_claude(home, root, "owner", [claude_row("I mostly write C++ these days", "cpp")])
        result = run(RECALL, root, home, "find", "C++")
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr and "C++ these days" in result.stdout, result
        rows = json_find(root, home, "C++")
        assert [r["message_id"] for r in rows] == ["cpp"], rows
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_zero_hits_reports_scope_and_suggests_rewording():
    base, root, home = fixture()
    try:
        write_claude(home, root, "owner", [claude_row("기차표를 예매했다", "a"),
                                           claude_row("두 번째 발화", "b")])
        result = run(RECALL, root, home, "find", "train ticket")
        assert result.returncode == 0, result.stderr
        for needle in ("searched scope", "1 file(s)", "2 message(s)", "another form of the word"):
            assert needle in result.stdout, (needle, result.stdout)
        # A miss is never reported as proof that nothing was said.
        assert "does not mean the original is absent" in result.stdout, result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def cwd_row(text, ident, cwd, session="fixture", stamp="2026-09-17T00:00:00Z"):
    row = claude_row(text, ident, stamp)
    row["sessionId"] = session
    if cwd is not None:
        row["cwd"] = cwd
    return row


def test_claude_records_from_another_folder_with_the_same_store_name_are_excluded():
    """Folder names that encode to one Claude store key must not share their conversations."""
    base, _root, home = fixture()
    try:
        for mine_name, other_name in (("한글", "다른"), ("a_b", "a-b")):
            mine = os.path.join(base, mine_name)
            other = os.path.join(base, other_name)
            os.makedirs(mine, exist_ok=True)
            os.makedirs(other, exist_ok=True)
            assert mangle(mine) == mangle(other), (mine, other)
            write_claude(home, mine, "own-" + mine_name,
                         [cwd_row("공유열쇠 MINE " + mine_name, "m-" + mine_name, mine, "own-s")])
            # The other folder's session lands in the very same store directory.
            write_claude(home, other, "foreign-" + other_name,
                         [cwd_row("공유열쇠 FOREIGN " + other_name, "f-" + other_name, other,
                                  "foreign-s"),
                          claude_row("공유열쇠 FOREIGN-NOCWD " + other_name, "g-" + other_name)])
            rows = json_find(mine, home, "공유열쇠 ")
            texts = sorted(r["text"] for r in rows)
            assert texts == ["공유열쇠 MINE " + mine_name], (mine_name, texts)
            listing = run(RECALL, mine, home, "sessions")
            assert "foreign-" + other_name not in listing.stdout, listing.stdout
            assert "own-" + mine_name in listing.stdout, listing.stdout
            everything = json_find(mine, home, "공유열쇠 FOREIGN ", "--all-instances")
            assert len(everything) == 1, everything
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_claude_records_of_a_declared_previous_root_are_kept():
    base, root, home = fixture()
    try:
        alias = os.path.join(base, "예전_이름")
        stranger = os.path.join(base, "예전-이름")
        write_alias_config(root, alias)
        write_claude(home, alias, "old", [cwd_row("별칭열쇠 OLD", "old", alias, "old-s")])
        write_claude(home, stranger, "stranger",
                     [cwd_row("별칭열쇠 STRANGER", "st", stranger, "st-s")])
        write_claude(home, root, "new", [cwd_row("별칭열쇠 NEW", "new", os.path.join(root, "sub"),
                                                 "new-s")])
        texts = sorted(r["text"] for r in json_find(root, home, "별칭열쇠"))
        assert texts == ["별칭열쇠 NEW", "별칭열쇠 OLD"], texts
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_claude_records_without_working_folder_are_kept_and_counted():
    base, root, home = fixture()
    try:
        # A whole file without any working-folder field is the old record form: keep it.
        write_claude(home, root, "legacy", [claude_row("옛기록열쇠 legacy", "legacy")])
        # Inside a file that names folders, a line without one follows its own session.
        write_claude(home, root, "mixed", [
            claude_row("옛기록열쇠 before-confirm", "early", "2026-09-17T00:00:00Z"),
            cwd_row("옛기록열쇠 confirmed", "conf", root, "fixture", "2026-09-17T00:01:00Z"),
            cwd_row("옛기록열쇠 elsewhere", "else", os.path.join(base, "elsewhere"), "other-s"),
            {**claude_row("옛기록열쇠 orphan", "orphan"), "sessionId": "other-s"},
            # A session that never names its folder is dropped.
            {**claude_row("옛기록열쇠 never-named", "never"), "sessionId": "never-s"},
            # The first folder a session names decides; a later foreign one does not.
            cwd_row("옛기록열쇠 moved-start", "mv1", root, "moved-s"),
            cwd_row("옛기록열쇠 moved-later", "mv2", os.path.join(base, "elsewhere"), "moved-s"),
            # A line without a session id belongs to the session being written.
            {k: v for k, v in claude_row("옛기록열쇠 no-id", "noid").items() if k != "sessionId"},
            # A row that names the folder but carries no text releases what waited for it.
            {**claude_row("옛기록열쇠 held-to-end", "held"), "sessionId": "late-s"},
            {"type": "progress", "sessionId": "late-s", "cwd": root},
        ])
        texts = sorted(r["text"] for r in json_find(root, home, "옛기록열쇠"))
        assert texts == ["옛기록열쇠 before-confirm", "옛기록열쇠 confirmed",
                         "옛기록열쇠 held-to-end", "옛기록열쇠 legacy",
                         "옛기록열쇠 moved-later", "옛기록열쇠 moved-start",
                         "옛기록열쇠 no-id"], texts
        needle, e = "no working-folder field", env(root, home)
        zero = subprocess.run([sys.executable, RECALL, "find", "없는낱말"], cwd=root, env=e,
                              capture_output=True, text=True)
        lines = [line for line in zero.stdout.splitlines() if needle in line]
        assert len(lines) == 1 and "1" in lines[0], zero.stdout
        # Hits may come from that file, so they carry the same warning once.
        found = subprocess.run([sys.executable, RECALL, "find", "옛기록열쇠"], cwd=root,
                               env=e, capture_output=True, text=True)
        lines = [line for line in found.stdout.splitlines() if needle in line]
        assert "legacy" in found.stdout and len(lines) == 1, found.stdout
        # Hits from checked files only are not in doubt; the store path says the same.
        for extra in ((), ("--role", "user")):
            checked = subprocess.run([sys.executable, RECALL, "find", "옛기록열쇠 confirmed",
                                      "--max", "1", *extra], cwd=root, env=e,
                                     capture_output=True, text=True)
            assert "legacy" not in checked.stdout and needle not in checked.stdout, (
                extra, checked.stdout)
        owner = subprocess.run([sys.executable, RECALL, "find", "옛기록열쇠 legacy", "--role",
                                "user", "--max", "1"], cwd=root, env=e, capture_output=True,
                               text=True)
        assert "legacy" in owner.stdout and needle in owner.stdout, owner.stdout
        listing = subprocess.run([sys.executable, RECALL, "sessions"], cwd=root, env=e,
                                 capture_output=True, text=True)
        lines = [line for line in listing.stdout.splitlines() if needle in line]
        assert len(lines) == 1 and "1" in lines[0], listing.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_default_output_stays_under_the_cap_with_a_long_query():
    base, root, home = fixture()
    try:
        write_claude(home, root, "owner", [claude_row("짧은 발화", "a")])
        for query in ("가" * 4500, "(" + "나" * 4500):
            result = run(RECALL, root, home, "find", query)
            assert result.returncode == 0, result.stderr
            size = len(result.stdout.encode("utf-8"))
            assert size <= 4000, size
            assert query[:20] in result.stdout, result.stdout[:200]
        # A matching query of the same length is also printed within the cap.
        long_text = "다" * 4500
        write_claude(home, root, "owner", [claude_row(long_text, "long")])
        result = run(RECALL, root, home, "find", long_text)
        assert result.returncode == 0 and "■ " in result.stdout, result.stdout[:200]
        assert len(result.stdout.encode("utf-8")) <= 4000
        # --full keeps the query as typed.
        result = run(RECALL, root, home, "find", "가" * 4500, "--full")
        assert len(result.stdout.encode("utf-8")) > 4000
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_function_default_order_matches_cli():
    import inspect
    import recall_literal
    assert inspect.signature(recall_literal.find).parameters["order"].default == "score"


def eval_corpus(home, root, count=12, words=True):
    rows = []
    for i in range(count):
        body = (f"marker{i:02d}alpha marker{i:02d}beta " if words else "")
        rows.append(claude_row(body + "가 " * 120, f"m{i}", f"2026-09-17T00:{i:02d}:00Z"))
    write_claude(home, root, "owner", rows)


def test_eval_recall_runs_to_completion():
    base, root, home = fixture()
    try:
        eval_corpus(home, root)
        result = run(os.path.join(HERE, "dev", "eval_recall.py"), root, home,
                     "--n", "3", "--band", "rare", "--quiet")
        assert result.returncode == 0, result.stdout + result.stderr
        metrics = os.path.join(root, "_private", "state", "metrics-recall.jsonl")
        rec = json.loads(open(metrics, encoding="utf-8").read().splitlines()[-1])
        assert rec["n"] == 3 and rec["hits"] == 3 and rec["rate"] == 1.0, rec
        assert rec["path"] == "transcript", rec
        # Tied words are ordered by the word, so the query is the same under any hash seed.
        code = ("import sys; sys.path.insert(0, %r); import eval_recall as e; "
                "print(e._query_for('amber birch cedar denim', dict.fromkeys("
                "['amber', 'birch', 'cedar', 'denim'], 1), band='rare'))") % os.path.join(HERE, "dev")
        queries = {subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True,
                                  text=True, env=dict(env(root, home), PYTHONHASHSEED=str(seed))
                                  ).stdout.strip() for seed in range(1, 7)}
        assert queries == {"amber|birch"}, queries
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_eval_recall_without_queries_is_unmeasured_not_zero():
    base, root, home = fixture()
    try:
        eval_corpus(home, root, words=False)
        result = run(os.path.join(HERE, "dev", "eval_recall.py"), root, home,
                     "--n", "3", "--band", "rare", "--quiet")
        assert result.returncode != 0, result.stdout
        assert "hit@" not in result.stdout, result.stdout
        assert "unmeasured" in result.stdout, result.stdout
        metrics = os.path.join(root, "_private", "state", "metrics-recall.jsonl")
        rec = json.loads(open(metrics, encoding="utf-8").read().splitlines()[-1])
        assert rec["rate"] is None and rec["status"] == "unmeasured" and rec["n"] == 0, rec
    finally:
        shutil.rmtree(base, ignore_errors=True)

def test_eval_recall_search_failure_is_error_not_zero():
    # A crashing search command must not be recorded as a measured 0% hit rate.
    base, root, home = fixture()
    try:
        eval_corpus(home, root)
        tools = os.path.join(base, "tools")
        shutil.copytree(HERE, tools, ignore=shutil.ignore_patterns("__pycache__"))
        stand_in = os.path.join(tools, "recall.py")
        src = open(stand_in, encoding="utf-8").read()
        # Exit before main only when run as a script; importing still works for eval_recall.
        marker = "\nimport argparse\n"
        assert marker in src
        src = src.replace(marker, "\nimport sys as _sys\nif __name__ == \"__main__\":\n    _sys.stderr.write(\"search broke\\n\")\n    _sys.exit(3)\n" + marker[1:], 1)
        with open(stand_in, "w", encoding="utf-8") as f:
            f.write(src)
        result = run(os.path.join(tools, "dev", "eval_recall.py"), root, home,
                     "--n", "3", "--band", "rare", "--quiet")
        assert result.returncode != 0, result.stdout + result.stderr
        assert "search broke" in result.stdout + result.stderr, result.stdout + result.stderr
        metrics = os.path.join(root, "_private", "state", "metrics-recall.jsonl")
        rec = json.loads(open(metrics, encoding="utf-8").read().splitlines()[-1])
        assert rec["status"] == "error" and rec["rate"] is None and rec["errors"] == 3, rec
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_eval_stopwords_are_clean():
    import eval_recall
    assert "will" in eval_recall.STOP
    english = [w for w in eval_recall.STOP if w.isascii()]
    assert english, eval_recall.STOP
    for w in english:
        assert eval_recall.TOKEN.fullmatch(w), w



def test_display_time_preserves_source_timezone():
    import transcripts
    assert transcripts.local_time("2026-10-08T12:00:00Z") == transcripts.local_time("2026-10-08T21:00:00+09:00")
    assert transcripts.local_time("2026-10-08T12:00:00") == transcripts.local_time("2026-10-08T12:00:00Z")
    assert transcripts.local_time("unknown") == "unknown"


def cap_corpus(home, root, count=30):
    """Many long matches, as a common word produces in a real transcript store."""
    rows = []
    for i in range(count):
        body = f"상한카나리 {i:02d} " + "긴 한국어 문장이 이어진다 " * 40
        rows.append(owner_row(body, f"cap{i:02d}", stamp=f"2026-09-17T00:{i:02d}:00Z"))
    write_claude(home, root, "owner", rows)


def test_default_output_is_capped_and_says_how_to_see_more():
    base, root, home = fixture()
    try:
        cap_corpus(home, root)
        result = run(RECALL, root, home, "find", "상한카나리", "--max", "30")
        assert result.returncode == 0, result.stderr
        size = len(result.stdout.encode("utf-8"))
        assert size <= 4096, size
        shown = result.stdout.count("■ ")
        assert 1 <= shown < 30, result.stdout
        last = result.stdout.rstrip("\n").splitlines()[-1]
        assert "--full" in last and str(30 - shown) in last, last
        # The compact form keeps the locator and an excerpt, not neighbouring messages.
        assert "owner.jsonl:" in result.stdout and " | " not in result.stdout, result.stdout
        # With no trailer to print, no room is held back for one: the space left is under one hit.
        write_claude(home, root, "short", [
            owner_row(f"KOALA {i:02d} " + "long sentence goes on " * 11, f"k{i:02d}")
            for i in range(40)])
        result = run(RECALL, root, home, "find", "KOALA", "--max", "20")
        size, shown = len(result.stdout.encode("utf-8")), result.stdout.count("■ ")
        assert 4096 - size < size // shown, (size, shown)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_default_output_reports_matches_beyond_max():
    base, root, home = fixture()
    try:
        cap_corpus(home, root, count=5)
        result = run(RECALL, root, home, "find", "상한카나리", "--max", "2")
        assert result.returncode == 0, result.stderr
        assert result.stdout.count("■ ") == 2, result.stdout
        last = result.stdout.rstrip("\n").splitlines()[-1]
        assert "3" in last and "--full" in last, last
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_full_keeps_previous_output_shape():
    base, root, home = fixture()
    try:
        cap_corpus(home, root)
        result = run(RECALL, root, home, "find", "상한카나리", "--max", "30", "--full")
        assert result.returncode == 0, result.stderr
        assert result.stdout.count("■ hit ") == 30, result.stdout[:400]
        assert len(result.stdout.encode("utf-8")) > 4096
        assert "  id:" in result.stdout and " | " in result.stdout
        assert "--full" not in result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_explicit_around_shows_neighbours_in_compact_output():
    base, root, home = fixture()
    try:
        rows = [owner_row("앞 문맥 메시지", "n0", stamp="2026-09-17T00:00:00Z"),
                owner_row("이웃카나리 본문", "n1", stamp="2026-09-17T00:01:00Z"),
                owner_row("뒤 문맥 메시지", "n2", stamp="2026-09-17T00:02:00Z")]
        write_claude(home, root, "owner", rows)
        plain = run(RECALL, root, home, "find", "이웃카나리")
        assert "앞 문맥" not in plain.stdout, plain.stdout
        result = run(RECALL, root, home, "find", "이웃카나리", "--around", "1")
        assert result.returncode == 0, result.stderr
        assert "앞 문맥" in result.stdout and "뒤 문맥" in result.stdout, result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_english_output_has_no_hangul():
    base, root, home = fixture()
    try:
        for i in range(3):
            write_rollout(home, f"session-{i:02d}", root,
                          [("user", f"english canary {i}"), ("assistant", "english canary reply")])
        english = dict(env(root, home), LANG="ko_KR.UTF-8", LC_ALL="ko_KR.UTF-8")
        outputs = []
        for args in (("sessions", "--max", "1"), ("find", "canary", "--full"), ("find", "canary"),
                     ("find", "absent-word"), ("find", "--help"), ("sessions", "--max", "0")):
            result = subprocess.run([sys.executable, RECALL, *args], cwd=root, env=english,
                                    capture_output=True, text=True)
            outputs.append(result.stdout + result.stderr)
        text = "\n".join(outputs)
        assert "(1/3 shown, newest first" in text, text
        assert "■ hit 1 · " in text and "--max must be 1 or more" in text, text
        assert not re.search("[가-힣]", text.replace(root, "<root>")), text
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_agent_dispatch_prefix_is_recognised_in_both_languages():
    import importlib
    transcripts = importlib.import_module("transcripts")
    receipts = importlib.import_module("receipts")
    for text in ("[Claude Code가 보낸 요청]", "[Claude Code requested a review]",
                 "FRESH_WORKER run", receipts.worker_prompt("read-only", "Review it.")):
        assert transcripts.AGENT_TRANSPORT.search(text), text
    assert not transcripts.AGENT_TRANSPORT.search("ordinary owner words")


def worker_prompt(body):
    """The prompt tools/fresh_worker.py gives a worker, which tools/ask.sh also sends."""
    import receipts
    return receipts.worker_prompt("read-only", body)


def write_config(root, **instance):
    os.makedirs(os.path.join(root, "instance"), exist_ok=True)
    with open(os.path.join(root, "instance", "config.json"), "w") as f:
        json.dump({"schema_version": 4, "instance": {
            "name": "fixture", **instance},
            "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                                   "legacy_public_tracks": []}}, f)


def owner_and_worker_lists(root, home, source):
    """What the literal search and the search of the owner's words list for WORKER-CANARY."""
    literal = run(RECALL, root, home, "find", "WORKER-CANARY", "--source", source, "--full")
    owner = run(RECALL, root, home, "find", "WORKER-CANARY", "--source", source, "--role", "user")
    assert literal.returncode == 0 and owner.returncode == 0, literal.stderr + owner.stderr
    return literal.stdout, owner.stdout


def test_selection_names_its_fields():
    """recall.py and recall_store.py read the selection by these names."""
    base, root, home = fixture()
    try:
        write_rollout(home, "own", root, [("user", "selection words")])
        code = ("import sys; sys.path.insert(0, %r); import transcripts as T; s = T.select_sources(None); "
                "print(s._fields, [r[2].endswith('own.jsonl') for r in s.rows], s.unverified, "
                "s.zst_skipped, s.malformed)") % os.path.join(HERE, "lib")
        result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env(root, home),
                                capture_output=True, text=True)
        assert result.stdout.strip() == ("('rows', 'unverified', 'zst_skipped', 'malformed') "
                                         "[True] 0 0 0"), result.stdout + result.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_claude_worker_prompt_is_not_the_owner():
    """A Claude worker runs with --no-session-persistence (pinned in test_fresh_worker), so it
    writes no record. A record of its prompt in this folder would still not be the owner's."""
    base, root, home = fixture()
    try:
        write_claude(home, root, "owner", [
            dict(owner_row("WORKER-CANARY the owner typed this", "o1"), cwd=root),
            dict(owner_row(worker_prompt("WORKER-CANARY review the plan"), "w1"), cwd=root)])
        literal, owner = owner_and_worker_lists(root, home, "claude")
        for listed in (literal, owner):
            assert "the owner typed this" in listed, listed
            assert "review the plan" not in listed and "bounded worker" not in listed, listed
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_codex_worker_prompt_is_not_the_owner():
    """A Codex worker runs with --ephemeral (pinned in test_fresh_worker), which leaves no
    rollout. A rollout of its prompt in this folder would still not be the owner's."""
    base, root, home = fixture()
    try:
        write_rollout(home, "owner", root, [("user", "WORKER-CANARY the owner typed this")])
        write_rollout(home, "worker", root, [("user", worker_prompt("WORKER-CANARY review the plan")),
                                             ("assistant", "WORKER-CANARY the worker answered")])
        literal, owner = owner_and_worker_lists(root, home, "codex")
        for listed in (literal, owner):
            assert "the owner typed this" in listed, listed
            assert "review the plan" not in listed and "bounded worker" not in listed, listed
        assert "the worker answered" in literal, literal
    finally:
        shutil.rmtree(base, ignore_errors=True)


def write_agy(home, conversations):
    """Antigravity conversations in the captured shape: {id: (workspace folder, request)}."""
    import sqlite3
    import urllib.parse
    brain = os.path.join(home, ".gemini", "antigravity-cli", "brain")
    os.makedirs(brain)
    db = sqlite3.connect(os.path.join(os.path.dirname(brain), "conversation_summaries.db"))
    db.execute("CREATE TABLE summaries (conversation TEXT, title TEXT, workspace_uris TEXT)")
    for conversation, (folder, request) in conversations.items():
        logs = os.path.join(brain, conversation, ".system_generated", "logs")
        os.makedirs(logs)
        row = {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
               "status": "DONE", "created_at": "2026-11-20T19:58:30Z",
               "content": "<USER_REQUEST>\n" + request + "\n</USER_REQUEST>\n"
                          "<ADDITIONAL_METADATA>\nThe current local time is: 2026-11-20."
                          "\n</ADDITIONAL_METADATA>"}
        with open(os.path.join(logs, "transcript.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        db.execute("INSERT INTO summaries VALUES (?, 't', ?)", (conversation, json.dumps(
            ["file://" + urllib.parse.quote(folder)])))
    db.commit()
    db.close()


def test_agy_worker_prompt_is_not_the_owner():
    """Antigravity keeps every conversation, a worker's too. A worker in a copy has the copy as
    its workspace, which is not this folder; one placed in this folder (where instance) or in a
    worktree under it has this folder's workspace, and its prompt's opening words keep it out."""
    base, root, home = fixture()
    try:
        prompt = worker_prompt("WORKER-CANARY review the plan")
        write_agy(home, {
            "owner": (root, "WORKER-CANARY the owner typed this"),
            "copy": (os.path.join(base, "mottori-worker-copy-1"), prompt + " from a copy"),
            "instance": (root, prompt + " in this folder"),
            "worktree": (os.path.join(root, "_private", "work", "runs", "r1", "wt"),
                         prompt + " in a worktree")})
        literal, owner = owner_and_worker_lists(root, home, "agy")
        for listed in (literal, owner):
            assert "the owner typed this" in listed, listed
            assert "review the plan" not in listed and "bounded worker" not in listed, listed
        agents = run(RECALL, root, home, "find", "WORKER-CANARY", "--source", "agy", "--full",
                     "--include-agents").stdout
        assert "in this folder" in agents and "in a worktree" in agents, agents
        assert "from a copy" not in agents, agents
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_configured_opener_keeps_a_worker_prompt_out():
    """An instance's own prompts are known by the openers in instance.agent_openers."""
    base, root, home = fixture()
    try:
        write_rollout(home, "owner", root, [("user", "OPENER-CANARY the owner typed this"),
                                            ("user", "You are the archivist. OPENER-CANARY sort")])
        write_config(root)
        before = run(RECALL, root, home, "find", "OPENER-CANARY", "--source", "codex").stdout
        assert "the owner typed this" in before and "archivist" in before, before
        write_config(root, agent_openers=[r"You are the (?:archivist|scribe)\."])
        after = run(RECALL, root, home, "find", "OPENER-CANARY", "--source", "codex").stdout
        assert "the owner typed this" in after and "archivist" not in after, after
        import config
        try:
            config.validate({"instance": {"agent_openers": ["(unclosed"]}})
            raise AssertionError("a pattern that does not compile was accepted")
        except ValueError as exc:
            assert "agent_openers" in str(exc), exc
    finally:
        shutil.rmtree(base, ignore_errors=True)


# Compressed Codex sessions (*.jsonl.zst) are read through the zstd command. These tests put a
# stand-in zstd on PATH that prints the file unchanged, so they do not need the real binary;
# one test below uses the real binary when it is installed.
FAKE_ZSTD = "#!/bin/sh\nfor arg; do last=$arg; done\nexec cat \"$last\"\n"


def fake_zstd_dir(base):
    folder = os.path.join(base, "fakebin")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "zstd")
    with open(path, "w") as f:
        f.write(FAKE_ZSTD)
    os.chmod(path, 0o755)
    return folder


def run_path(root, home, path_value, *args, script=RECALL):
    return subprocess.run([sys.executable, script, *args], cwd=root,
                          env=dict(env(root, home), PATH=path_value),
                          capture_output=True, text=True)


def as_fake_zst(path):
    """Rename a plain rollout so it looks compressed to recall; the stand-in zstd cats it."""
    os.replace(path, path + ".zst")
    return path + ".zst"


def all_files(folder):
    return sorted(os.path.join(d, n) for d, _s, names in os.walk(folder) for n in names)


def test_compressed_codex_sessions_are_found_with_the_instance_filter():
    base, root, home = fixture()
    try:
        path = fake_zstd_dir(base) + os.pathsep + os.environ.get("PATH", "")
        as_fake_zst(write_rollout(home, "own", root, [("user", "ZST-CANARY own words")]))
        as_fake_zst(write_rollout(home, "other", root + "-other",
                                  [("user", "ZST-CANARY other words")]))
        as_fake_zst(write_rollout(home, "agent", root, [("user", "ZST-CANARY agent words")],
                                  subagent=True))
        before = all_files(home)
        result = run_path(root, home, path, "find", "ZST-CANARY", "--source", "codex")
        assert result.returncode == 0, result.stderr
        assert "own words" in result.stdout, result.stdout
        assert "other words" not in result.stdout and "agent words" not in result.stdout
        opened = run_path(root, home, path, "find", "ZST-CANARY", "--source", "codex",
                          "--all-instances")
        assert "own words" in opened.stdout and "other words" in opened.stdout
        listed = run_path(root, home, path, "sessions")
        assert "own.jsonl.zst" in listed.stdout and "other.jsonl.zst" not in listed.stdout
        # Sessions are streamed, never written out decompressed.
        assert all_files(home) == before
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_missing_zstd_skips_compressed_sessions_with_one_line():
    base, root, home = fixture()
    try:
        empty = os.path.join(base, "emptybin")
        os.makedirs(empty)
        write_rollout(home, "plain", root, [("user", "NOZSTD-CANARY plain words")])
        as_fake_zst(write_rollout(home, "packed", root, [("user", "NOZSTD-CANARY packed")]))
        result = run_path(root, home, empty, "find", "NOZSTD-CANARY", "--source", "codex")
        assert result.returncode == 0, result.stderr
        assert "plain words" in result.stdout and "packed" not in result.stdout
        lines = [line for line in result.stdout.splitlines() if "zstd" in line]
        assert len(lines) == 1 and lines[0].startswith("1 compressed"), result.stdout
        listed = run_path(root, home, empty, "sessions")
        assert listed.returncode == 0, listed.stderr
        assert sum("zstd" in line for line in listed.stdout.splitlines()) == 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_metadata_cache_holds_no_text_and_follows_a_rewritten_file():
    base, root, home = fixture()
    try:
        path = fake_zstd_dir(base) + os.pathsep + os.environ.get("PATH", "")
        packed = as_fake_zst(write_rollout(home, "moving", root,
                                           [("user", "CACHE-CANARY first")]))
        first = run_path(root, home, path, "find", "CACHE-CANARY", "--source", "codex")
        assert "first" in first.stdout, first.stdout
        # The cache names the working folder of every Codex session on the machine, so it lives
        # in the private state folder, never in the public one.
        cache = os.path.join(root, "_private", "state", ".recall-codex-meta.json")
        assert not os.path.exists(os.path.join(root, "state", ".recall-codex-meta.json"))
        with open(cache, encoding="utf-8") as f:
            cached = f.read()
        assert "CACHE-CANARY" not in cached and "moving" in cached
        # The same path now holds another folder's session: the cached folder must not be reused.
        os.remove(packed)
        as_fake_zst(write_rollout(home, "moving", root + "-elsewhere",
                                  [("user", "CACHE-CANARY rewritten, longer than before")]))
        second = run_path(root, home, path, "find", "CACHE-CANARY", "--source", "codex")
        assert "rewritten" not in second.stdout and "first" not in second.stdout, second.stdout
        os.remove(cache)
        third = run_path(root, home, path, "find", "CACHE-CANARY", "--source", "codex",
                         "--all-instances")
        assert third.returncode == 0 and "rewritten" in third.stdout, third.stdout
        # A single uncached session is saved too, not read again by every later search.
        assert os.path.exists(cache), all_files(os.path.join(root, "_private"))
        # A cache an older reader wrote is read again once, not trusted: here it would place the
        # other folder's session in this instance.
        moved = [p for p in all_files(os.path.join(home, ".codex")) if p.endswith(".zst")][0]
        st = os.stat(moved)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({os.path.realpath(moved): [[st.st_size, st.st_mtime_ns],
                                                 {"cwd": root, "id": "moving"}]}, f)
        fourth = run_path(root, home, path, "find", "CACHE-CANARY", "--source", "codex")
        assert "rewritten" not in fourth.stdout, fourth.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_time_limit_reads_newest_first_and_says_what_was_left():
    base, root, home = fixture()
    try:
        old = write_rollout(home, "old", root, [("user", "LIMIT-CANARY oldest words")])
        middle = write_rollout(home, "middle", root, [("user", "unrelated")])
        new = write_rollout(home, "new", root,
                            [("user", "LIMIT-CANARY newest words " + "x" * 300)] * 40)
        for age, fp in ((300, old), (200, middle), (100, new)):
            os.utime(fp, (1_800_000_000 - age, 1_800_000_000 - age))
        # A zero-second limit reads only the newest file, which is always read.
        code = ("import sys; sys.path.insert(0, %r); import recall; recall.SCAN_SECONDS = 0; "
                "sys.argv = ['recall.py'] + sys.argv[1:]; sys.exit(recall.main())" % HERE)
        result = subprocess.run([sys.executable, "-c", code, "find", "LIMIT-CANARY",
                                 "--source", "codex"], cwd=root, env=env(root, home),
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "newest words" in result.stdout and "oldest words" not in result.stdout
        assert "not searched within the 0-second limit: 2." in result.stdout and "--scan-all" in result.stdout, result.stdout
        assert len(result.stdout.encode("utf-8")) <= 4000
        full = subprocess.run([sys.executable, "-c", code, "find", "LIMIT-CANARY",
                               "--source", "codex", "--scan-all", "--order", "oldest"],
                              cwd=root, env=env(root, home), capture_output=True, text=True)
        assert "oldest words" in full.stdout and "--scan-all" not in full.stdout, full.stdout
        assert full.stdout.index("oldest words") < full.stdout.index("newest words")
        # Oldest order under the same limit opens the oldest file first, not the newest.
        oldest = subprocess.run([sys.executable, "-c", code, "find", "LIMIT-CANARY",
                                 "--source", "codex", "--order", "oldest"],
                                cwd=root, env=env(root, home), capture_output=True, text=True)
        assert "oldest words" in oldest.stdout, oldest.stdout
        assert "newest words" not in oldest.stdout and "limit: 2." in oldest.stdout, oldest.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_failed_zstd_read_is_reported_and_tried_again():
    base, root, home = fixture()
    try:
        broken = os.path.join(base, "brokenbin")
        os.makedirs(broken)
        with open(os.path.join(broken, "zstd"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(broken, "zstd"), 0o755)
        as_fake_zst(write_rollout(home, "flaky", root, [("user", "FLAKY-CANARY words")]))
        failed = run_path(root, home, broken, "find", "FLAKY-CANARY", "--source", "codex")
        assert failed.returncode == 0, failed.stderr
        lines = [line for line in failed.stdout.splitlines() if "zstd" in line]
        assert len(lines) == 1 and lines[0].startswith("1 compressed"), failed.stdout
        listed = run_path(root, home, broken, "sessions")
        assert sum("zstd" in line for line in listed.stdout.splitlines()) == 1, listed.stdout
        # A working zstd later must find the session: the failure was not remembered.
        path = fake_zstd_dir(base) + os.pathsep + os.environ.get("PATH", "")
        again = run_path(root, home, path, "find", "FLAKY-CANARY", "--source", "codex")
        assert "FLAKY-CANARY words" in again.stdout, again.stdout
        assert "zstd" not in again.stdout, again.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_lone_surrogate_in_session_metadata_does_not_crash():
    base, root, home = fixture()
    try:
        path = fake_zstd_dir(base) + os.pathsep + os.environ.get("PATH", "")
        odd = write_rollout(home, "odd", root + "MARK", [("user", "SURROGATE words")],
                            session_id="odd-MARK")
        with open(odd, encoding="utf-8") as f:
            text = f.read()
        # A lone surrogate escape is valid JSON but cannot be encoded as UTF-8 once decoded.
        with open(odd, "w", encoding="utf-8") as f:
            f.write(text.replace("MARK", "\\ud800"))
        as_fake_zst(odd)
        as_fake_zst(write_rollout(home, "own", root, [("user", "SURROGATE own words")]))
        for args in (("find", "SURROGATE", "--source", "codex"), ("sessions",)):
            result = run_path(root, home, path, *args)
            assert result.returncode == 0, result.stderr
        assert "own words" in run_path(root, home, path, "find", "SURROGATE",
                                       "--source", "codex").stdout
        state = os.path.join(root, "_private", "state")
        assert os.listdir(state) == [".recall-codex-meta.json"], os.listdir(state)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_time_limit_counts_only_sessions_it_would_have_read():
    base, root, home = fixture()
    try:
        old = write_rollout(home, "old", root, [("user", "unrelated old words")])
        new = write_rollout(home, "new", root, [("user", "unrelated new words")])
        agents = [write_rollout(home, f"agent{i}", root, [("user", "unrelated agent words")],
                                subagent=True) for i in range(5)]
        for age, fp in [(300, old), (200, new)] + [(100 - i, fp) for i, fp in enumerate(agents)]:
            os.utime(fp, (1_800_000_000 - age, 1_800_000_000 - age))
        code = ("import sys; sys.path.insert(0, %r); import recall; recall.SCAN_SECONDS = 0; "
                "sys.argv = ['recall.py'] + sys.argv[1:]; sys.exit(recall.main())" % HERE)
        result = subprocess.run([sys.executable, "-c", code, "find", "NOWHERE-CANARY",
                                 "--source", "codex"], cwd=root, env=env(root, home),
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        # Subagent sessions are never searched by default, so they are neither read nor left over:
        # the newest user session is read and the one older user session is left.
        assert "1 file(s) from codex" in result.stdout, result.stdout
        assert "limit: 1." in result.stdout, result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_real_zstd_reads_a_compressed_session():
    real = shutil.which("zstd")
    if not real:
        print("  (zstd is not installed; skipped)")
        return
    base, root, home = fixture()
    try:
        plain = write_rollout(home, "real", root, [("user", "REAL-ZST-CANARY packed words")])
        subprocess.run([real, "-q", "--rm", plain, "-o", plain + ".zst"], check=True)
        assert not os.path.exists(plain)
        result = run(RECALL, root, home, "find", "REAL-ZST-CANARY", "--source", "codex")
        assert result.returncode == 0, result.stderr
        assert "packed words" in result.stdout and "real.jsonl.zst" in result.stdout, result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _stub_zstd(base, name, body):
    folder = os.path.join(base, name)
    os.makedirs(folder)
    with open(os.path.join(folder, "zstd"), "w") as f:
        f.write(body)
    os.chmod(os.path.join(folder, "zstd"), 0o755)
    return folder


def test_unstartable_zstd_is_reported_even_across_all_instances():
    base, root, home = fixture()
    try:
        working = fake_zstd_dir(base) + os.pathsep + os.environ.get("PATH", "")
        # On PATH but impossible to start: its interpreter line names no program.
        broken = _stub_zstd(base, "nostart", "#!/nonexistent/interpreter\n")
        write_rollout(home, "plain", root, [("user", "NOSTART-CANARY plain words")])
        as_fake_zst(write_rollout(home, "packed", root + "-other",
                                  [("user", "NOSTART-CANARY packed words")]))
        # Once with no metadata cache, once with the metadata cached by a working zstd: the
        # message read must not reach the broken command either way.
        for warm in (False, True):
            if warm:
                assert "packed words" in run_path(root, home, working, "find", "NOSTART-CANARY",
                                                  "--source", "codex", "--all-instances").stdout
            for args in (("find", "NOSTART-CANARY", "--source", "codex", "--all-instances"),
                         ("find", "NOSTART-CANARY", "--source", "codex", "--all-instances",
                          "--full")):
                result = run_path(root, home, broken, *args)
                assert result.returncode == 0, result.stderr
                assert "plain words" in result.stdout and "packed words" not in result.stdout
                lines = [line for line in result.stdout.splitlines() if "zstd" in line]
                assert len(lines) == 1 and lines[0].startswith("1 compressed"), result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_zero_hit_scope_counts_only_sessions_read_without_a_time_limit():
    base, root, home = fixture()
    try:
        for name in ("one", "two"):
            write_rollout(home, name, root, [("user", "unrelated words")])
        for i in range(5):
            write_rollout(home, f"agent{i}", root, [("user", "unrelated agent words")],
                          subagent=True)
        result = run(RECALL, root, home, "find", "NOWHERE-CANARY", "--source", "codex",
                     "--scan-all")
        assert result.returncode == 0, result.stderr
        # Subagent sessions are not searched by default, so they are not part of the scope.
        assert "2 file(s) from codex" in result.stdout, result.stdout
        agents = run(RECALL, root, home, "find", "NOWHERE-CANARY", "--source", "codex",
                     "--scan-all", "--include-agents")
        assert "7 file(s) from codex" in agents.stdout, agents.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_compressed_file_with_an_unparseable_first_line_is_cached_not_reread():
    base, root, home = fixture()
    try:
        log = os.path.join(base, "zstd-calls.log")
        # Counts each decompression, then prints the file unchanged like the other stand-in.
        counting = _stub_zstd(base, "countbin",
                              "#!/bin/sh\nfor arg; do last=$arg; done\n"
                              "[ \"$1\" = -dcq ] && echo x >> %s\nexec cat \"$last\"\n" % log)
        path = counting + os.pathsep + os.environ.get("PATH", "")
        odd = os.path.join(home, ".codex", "sessions", "odd.jsonl.zst")
        with open(odd, "w", encoding="utf-8") as f:
            f.write("this first line is not JSON\nneither is this\n")
        write_rollout(home, "plain", root, [("user", "PARSE-CANARY words")])
        for _ in range(2):
            if os.path.exists(log):
                os.remove(log)
            result = run_path(root, home, path, "find", "PARSE-CANARY", "--source", "codex")
            assert result.returncode == 0, result.stderr
            assert "PARSE-CANARY words" in result.stdout and "zstd" not in result.stdout
        # zstd delivered the line, so the file is known; the second run decompresses nothing.
        assert not os.path.exists(log), open(log).read()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_hit_from_a_session_whose_id_holds_a_lone_surrogate_is_printed():
    base, root, home = fixture()
    try:
        path = fake_zstd_dir(base) + os.pathsep + os.environ.get("PATH", "")
        for name, packed in (("plainodd", False), ("packedodd", True)):
            odd = write_rollout(home, name, root + "-elsewhere",
                                [("user", "SURROGATE-HIT words MARK " + name)],
                                session_id=name + "-MARK")
            with open(odd, encoding="utf-8") as f:
                text = f.read()
            # The message id and the timestamp of the hit carry one as well. The texts differ: the
            # same text at the same instant in two sessions is one message copied by a fork.
            text = text.replace('"payload": {"type": "message"',
                                '"payload": {"id": "m-MARK", "type": "message"')
            text = text.replace('00:00Z"', '00:00Z-MARK"')
            with open(odd, "w", encoding="utf-8") as f:
                f.write(text.replace("MARK", "\\ud800"))
            if packed:
                as_fake_zst(odd)
        for extra in ((), ("--full",), ("--json",)):
            result = run_path(root, home, path, "find", "SURROGATE-HIT", "--source", "codex",
                              "--all-instances", *extra)
            assert result.returncode == 0, result.stderr
            assert result.stdout.count("SURROGATE-HIT words") >= 2, result.stdout
        # Two messages whose ids differ only in their lone surrogate are two messages.
        pair = write_claude(home, root, "pair", [])
        with open(pair, "w", encoding="utf-8") as f:   # ASCII escapes carry the surrogates.
            for row in (cwd_row("COLL alpha", "u\ud800", root),
                        cwd_row("COLL beta", "u\udc00", root)):
                f.write(json.dumps(row) + "\n")
        rows = json_find(root, home, "COLL")
        assert sorted(r["text"] for r in rows) == ["COLL alpha", "COLL beta"], rows
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_agy_transcripts_are_scoped_by_the_conversation_index():
    """Antigravity rows name no folder; the conversation index's workspace_uris does. The
    captured transcript's shape is read, and a conversation the index does not place is counted."""
    import sqlite3
    import urllib.parse
    base, root, home = fixture()
    try:
        brain = os.path.join(home, ".gemini", "antigravity-cli", "brain")
        captured = os.path.join(HERE, "tests", "fixtures", "runtimes", "agy", "transcript.jsonl")
        for conversation in ("own", "other", "unplaced"):
            logs = os.path.join(brain, conversation, ".system_generated", "logs")
            os.makedirs(logs)
            shutil.copy(captured, os.path.join(logs, "transcript.jsonl"))
        db = sqlite3.connect(os.path.join(home, ".gemini", "antigravity-cli", "conversation_summaries.db"))
        db.execute("CREATE TABLE summaries (conversation TEXT, title TEXT, workspace_uris TEXT)")
        for conversation, folder in (("own", root), ("other", root + "-other")):
            db.execute("INSERT INTO summaries VALUES (?, ?, ?)", (conversation, "t", json.dumps(
                ["file://" + urllib.parse.quote(folder)])))
        # Valid JSON that is not a list places nothing.
        db.execute("INSERT INTO summaries VALUES ('unplaced', 't', '5')")
        db.commit()
        db.close()
        result = run(RECALL, root, home, "find", "SECOND", "--source", "agy", "--full")
        assert result.returncode == 0, result.stderr
        assert "[agy]" in result.stdout and "/own/" in result.stdout, result.stdout
        assert "/other/" not in result.stdout and "/unplaced/" not in result.stdout, result.stdout
        assert "1 Antigravity transcript(s) were not searched" in result.stdout, result.stdout
        # The notice names the one search that reads them.
        assert "`--source agy --all-instances` reads them" in result.stdout, result.stdout
        # The typed request without its wrapper; a system row and the checkpoint stay out.
        user = run(RECALL, root, home, "find", "single word SECOND", "--source", "agy", "--full",
                   "--role", "user")
        assert "Reply with the single word SECOND." in user.stdout, user.stdout
        assert "USER_REQUEST" not in user.stdout, user.stdout
        assert "[agy]" not in run(RECALL, root, home, "find", "Resuming from a compaction",
                                  "--source", "agy").stdout
        assert "[agy]" not in run(RECALL, root, home, "find", "not actually sent by the user",
                                  "--source", "agy").stdout
        # --since reads the row time from created_at (2026-11-20 UTC); these bounds hold in any time zone.
        assert "/own/" in run(RECALL, root, home, "find", "SECOND", "--source", "agy", "--full",
                              "--since", "2026-11-19").stdout
        assert "/own/" not in run(RECALL, root, home, "find", "SECOND", "--source", "agy", "--full",
                                  "--since", "2026-11-22").stdout
        missed = run(RECALL, root, home, "find", "no such words", "--source", "agy")
        assert "Antigravity transcript(s) not searched because the index" in missed.stdout, missed.stdout
        assert "`--source agy --all-instances` reads them" in missed.stdout, missed.stdout
        wide = run(RECALL, root, home, "find", "AFTER", "--source", "agy", "--full", "--all-instances")
        assert all(f"/{c}/" in wide.stdout for c in ("own", "other", "unplaced")), wide.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_word_search_says_the_list_by_meaning_is_off_until_the_owner_says_no():
    """KIT-DR-094: with a config and the list off, the word search names the command that turns it
    on; after the owner's no it stops saying so."""
    base, root, home = fixture()
    try:
        cfg = {"schema_version": 4, "instance": {"name": "t"},
               "journal_visibility": {"public_tracks": None, "legacy_cutoff": None, "legacy_public_tracks": []}}
        os.makedirs(os.path.join(root, "instance"))
        config_path = os.path.join(root, "instance", "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        write_claude(home, root, "owner", [owner_row("the pricing plan moves to Monday")])
        hint = "By meaning: off (python3 tools/options.py on meaning)."
        result = run(RECALL, root, home, "find", "pricing")
        assert result.returncode == 0 and hint in result.stdout, result.stdout + result.stderr
        cfg["options"] = {"declined": ["meaning"]}
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        result = run(RECALL, root, home, "find", "pricing")
        assert result.returncode == 0 and "pricing" in result.stdout and hint not in result.stdout, result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


TESTS = [
    test_the_word_search_says_the_list_by_meaning_is_off_until_the_owner_says_no,
    test_english_output_has_no_hangul,
    test_agent_dispatch_prefix_is_recognised_in_both_languages,
    test_selection_names_its_fields,
    test_claude_worker_prompt_is_not_the_owner,
    test_codex_worker_prompt_is_not_the_owner,
    test_agy_worker_prompt_is_not_the_owner,
    test_configured_opener_keeps_a_worker_prompt_out,
    test_display_time_preserves_source_timezone,
    test_transcript_directory_mangling,
    test_other_cwd_rollout_is_excluded_by_default,
    test_authored_only_excludes_agents_and_system_injection,
    test_sessions_default_is_40,
    test_claude_text_and_legacy_content_blocks,
    test_summary_cannot_occupy_user_score_slot,
    test_codex_injection_cannot_occupy_user_score_slot,
    test_ambient_envelope_keeps_actual_request,
    test_archive_uses_same_cwd_and_subagent_boundary,
    test_active_archive_dedup_keeps_distinct_repeated_turns,
    test_native_ids_dedup_copied_claude_alias_and_keep_old_only_turn,
    test_agent_handbacks_are_not_owner_authority,
    test_claude_meta_transport_is_not_owner_but_quoted_feedback_survives,
    test_slash_command_args_are_the_owners_words,
    test_locator_and_context_point_to_original_record,
    test_eval_matches_record_id_not_same_minute,
    test_missing_transcript_dir_never_borrows_another_project,
    test_regex_special_characters_fall_back_to_literal_text,
    test_zero_hits_reports_scope_and_suggests_rewording,
    test_function_default_order_matches_cli,
    test_eval_recall_runs_to_completion,
    test_eval_recall_without_queries_is_unmeasured_not_zero,
    test_default_output_is_capped_and_says_how_to_see_more,
    test_default_output_reports_matches_beyond_max,
    test_full_keeps_previous_output_shape,
    test_explicit_around_shows_neighbours_in_compact_output,
    test_claude_records_from_another_folder_with_the_same_store_name_are_excluded,
    test_claude_records_of_a_declared_previous_root_are_kept,
    test_claude_records_without_working_folder_are_kept_and_counted,
    test_default_output_stays_under_the_cap_with_a_long_query,
    test_compressed_codex_sessions_are_found_with_the_instance_filter,
    test_missing_zstd_skips_compressed_sessions_with_one_line,
    test_metadata_cache_holds_no_text_and_follows_a_rewritten_file,
    test_time_limit_reads_newest_first_and_says_what_was_left,
    test_failed_zstd_read_is_reported_and_tried_again,
    test_lone_surrogate_in_session_metadata_does_not_crash,
    test_time_limit_counts_only_sessions_it_would_have_read,
    test_real_zstd_reads_a_compressed_session,
    test_unstartable_zstd_is_reported_even_across_all_instances,
    test_zero_hit_scope_counts_only_sessions_read_without_a_time_limit,
    test_compressed_file_with_an_unparseable_first_line_is_cached_not_reread,
    test_hit_from_a_session_whose_id_holds_a_lone_surrogate_is_printed,
    test_agy_transcripts_are_scoped_by_the_conversation_index,
    test_eval_recall_search_failure_is_error_not_zero,
    test_eval_stopwords_are_clean,
    test_since_uses_local_date,
    test_role_filter_drops_the_other_role,
    test_dangling_transcript_is_skipped,
    test_bad_find_arguments_are_usage_errors,
    test_order_and_context_stay_inside_their_file,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"recall: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
