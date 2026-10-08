#!/usr/bin/env python3
"""recall.py, memlib transcript discovery, and Codex root-thread regressions."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = os.path.dirname(os.path.abspath(__file__))
RECALL = os.path.join(HERE, "recall.py")
ROOT_THREAD = os.path.join(HERE, "codex_root_thread.py")


def fixture():
    base = tempfile.mkdtemp(prefix="recall-fixture-")
    root = os.path.join(base, "instance with.dot_한글")
    home = os.path.join(base, "home")
    os.makedirs(root)
    os.makedirs(os.path.join(home, ".codex", "sessions"))
    return base, root, home


def env(root, home):
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
        code = ("import sys; sys.path.insert(0, %r); import memlib; "
                "print(memlib.mangle_project_key(%r)); print(memlib.TRANSCRIPTS)" %
                (HERE, root))
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
            write_rollout(home, f"session-{i:02d}", root, [("user", f"turn {i}")])
        result = run(RECALL, root, home, "sessions")
        rows = [line for line in result.stdout.splitlines() if line.startswith("[codex ")]
        assert result.returncode == 0, result.stderr
        assert len(rows) == 40
        assert "(40/45개 최신순 표시" in result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_codex_root_thread_uses_authored_turn_count():
    base, root, home = fixture()
    try:
        write_rollout(home, "root", root, [
            ("user", "first authored"),
            ("user", "[Claude Code가 delegated prompt"),
            ("user", "<environment_context>injected</environment_context>"),
            ("user", "second authored"),
        ], session_id="owner-root")
        write_rollout(home, "competitor", root, [("user", "one authored")],
                      session_id="competitor")
        write_rollout(home, "agent", root,
                      [("user", f"agent {i}") for i in range(8)], subagent=True,
                      session_id="agent")
        result = run(ROOT_THREAD, root, home)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "owner-root"
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
    os.makedirs(os.path.join(root, "system"), exist_ok=True)
    with open(os.path.join(root, "system", "memory-config.json"), "w") as f:
        json.dump({"schema_version": 4, "instance": {
            "name": "fixture", "context": "personal", "root_aliases": [alias]},
            "journal_visibility": {"legacy_cutoff": None, "legacy_public_tracks": []}}, f)


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
        ])
        rows = json_find(root, home, "형식카나리", "--role", "user")
        assert {r["message_id"] for r in rows} == {"native", "legacy"}, rows
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
        ])
        write_claude(home, root, "owner", [owner_row(
            '<environment_context>자동문맥</environment_context>\n봉투카나리 Claude 질문')])
        rows = json_find(root, home, "봉투카나리", "--role", "user")
        assert len(rows) == 3, rows
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
        write_claude(home, root, "owner", [shared])
        write_claude(home, alias, "owner", [shared, owner_row("별칭카나리 old-only", "old")])
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
        write_claude(home, root, "owner", [injected, ordinary])
        rows = json_find(root, home, "META-CANARY", "--role", "user", "--max", "1")
        assert [r["message_id"] for r in rows] == ["human"], rows
        diagnostic = json_find(root, home, "META-CANARY", "--include-system")
        assert {r["message_id"]: r["origin"] for r in diagnostic} == {"human":"user", "hook":"system"}
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


def test_garden_and_sync_wrappers_share_authority_and_scope():
    base, root, home = fixture()
    try:
        path = write_rollout(home, "owner", root, [
            ("user", "수집카나리 actual"), ("user", "# AGENTS.md instructions\n수집카나리 system")])
        archive_copy(home, path)
        os.unlink(path)
        write_rollout(home, "foreign", root + "-foreign", [("user", "수집카나리 foreign")])
        write_rollout(home, "agent", root, [("user", "수집카나리 agent")], subagent=True)
        # Length is not provenance. Redaction/output budgets belong to the output policy.
        write_claude(home, root, "owner", [owner_row("수집카나리 " + "긴질문" * 1600)])
        code = ("import sys,json,datetime;sys.path.insert(0,%r);import garden_lanes as g;"
                "since=datetime.datetime(2026,9,1,tzinfo=g.KST);"
                "print(json.dumps({'codex':[r[1] for r in g.codex_msgs(since)],"
                "'claude':[len(r[1]) for r in g.claude_msgs(since)]},ensure_ascii=False))") % HERE
        result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env(root, home),
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        got = json.loads(result.stdout)
        assert got["codex"] == ["수집카나리 actual"] and got["claude"][0] > 4000, got
    finally:
        shutil.rmtree(base, ignore_errors=True)



def test_eval_matches_record_id_not_same_minute():
    import eval_recall
    assert not eval_recall._retrieved_id('[{"record_id":"different","timestamp":"2026-10-08T10:01"}]', "wanted")
    assert eval_recall._retrieved_id('[{"record_id":"wanted"}]', "wanted")
    assert not eval_recall._retrieved_id("not json", "wanted")



def test_display_time_preserves_source_timezone():
    import recall
    assert recall._local_time("2026-10-08T12:00:00Z") == recall._local_time("2026-10-08T21:00:00+09:00")
    assert recall._local_time("2026-10-08T12:00:00") == recall._local_time("2026-10-08T12:00:00Z")
    assert recall._local_time("unknown") == "unknown"


TESTS = [
    test_display_time_preserves_source_timezone,
    test_transcript_directory_mangling,
    test_other_cwd_rollout_is_excluded_by_default,
    test_authored_only_excludes_agents_and_system_injection,
    test_sessions_default_is_40,
    test_codex_root_thread_uses_authored_turn_count,
    test_claude_text_and_legacy_content_blocks,
    test_summary_cannot_occupy_user_score_slot,
    test_codex_injection_cannot_occupy_user_score_slot,
    test_ambient_envelope_keeps_actual_request,
    test_archive_uses_same_cwd_and_subagent_boundary,
    test_active_archive_dedup_keeps_distinct_repeated_turns,
    test_native_ids_dedup_copied_claude_alias_and_keep_old_only_turn,
    test_agent_handbacks_are_not_owner_authority,
    test_claude_meta_transport_is_not_owner_but_quoted_feedback_survives,
    test_locator_and_context_point_to_original_record,
    test_eval_matches_record_id_not_same_minute,
]


# garden/sync are optional instance adapters and are not exported with the generic kit.
if os.path.isfile(os.path.join(HERE, "garden_lanes.py")):
    TESTS.append(test_garden_and_sync_wrappers_share_authority_and_scope)

def main():
    failed = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"recall: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
