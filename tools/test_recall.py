#!/usr/bin/env python3
"""recall.py and memlib transcript discovery regressions."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = os.path.dirname(os.path.abspath(__file__))
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
    return dict(os.environ, MOTTORI_INSTANCE=root, HOME=home, MOTTORI_LANG="ko")


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
        code = ("import sys; sys.path.insert(0, %r); import memlib; print(memlib.TRANSCRIPTS)"
                % HERE)
        got = subprocess.run([sys.executable, "-c", code], env=env(root, home),
                             capture_output=True, text=True)
        assert got.stdout.strip() == os.path.join(home, ".claude", "projects", mangle(root)), got
        for lang, notice in (("ko", "이 폴더의 Claude 대화 기록이 아직 없다"),
                             ("en", "No Claude conversation records exist for this folder yet")):
            result = subprocess.run([sys.executable, RECALL, "find", "OTHER-PROJECT"], cwd=root,
                                    env=dict(env(root, home), MOTTORI_LANG=lang),
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            assert "secret words" not in result.stdout, result.stdout
            assert notice in result.stdout, result.stdout
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
        for lang, needles in (
                ("ko", ["찾은 범위에서", "파일 1개", "메시지 2개", "다른 언어"]),
                ("en", ["searched scope", "1 file(s)", "2 message(s)", "other language"])):
            result = subprocess.run([sys.executable, RECALL, "find", "train ticket"], cwd=root,
                                    env=dict(env(root, home), MOTTORI_LANG=lang),
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            for needle in needles:
                assert needle in result.stdout, (needle, result.stdout)
            assert "기록에 없다" not in result.stdout
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
        ])
        texts = sorted(r["text"] for r in json_find(root, home, "옛기록열쇠"))
        assert texts == ["옛기록열쇠 before-confirm", "옛기록열쇠 confirmed",
                         "옛기록열쇠 legacy"], texts
        for lang, needle in (("ko", "작업 폴더 정보가 없어"), ("en", "no working-folder field")):
            e = dict(env(root, home), MOTTORI_LANG=lang)
            zero = subprocess.run([sys.executable, RECALL, "find", "없는낱말"], cwd=root, env=e,
                                  capture_output=True, text=True)
            lines = [line for line in zero.stdout.splitlines() if needle in line]
            assert len(lines) == 1 and "1" in lines[0], zero.stdout
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
        for lang in ("ko", "en"):
            e = dict(env(root, home), MOTTORI_LANG=lang)
            for query in ("가" * 4500, "(" + "나" * 4500):
                result = subprocess.run([sys.executable, RECALL, "find", query], cwd=root, env=e,
                                        capture_output=True, text=True)
                assert result.returncode == 0, result.stderr
                size = len(result.stdout.encode("utf-8"))
                assert size <= 4000, (lang, size)
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
    import recall
    assert inspect.signature(recall.find).parameters["order"].default == "score"


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
        result = run(os.path.join(HERE, "eval_recall.py"), root, home,
                     "--n", "3", "--band", "rare", "--quiet")
        assert result.returncode == 0, result.stdout + result.stderr
        metrics = os.path.join(root, "_private", "state", "metrics-recall.jsonl")
        rec = json.loads(open(metrics, encoding="utf-8").read().splitlines()[-1])
        assert rec["n"] == 3 and rec["hits"] == 3 and rec["rate"] == 1.0, rec
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_eval_recall_without_queries_is_unmeasured_not_zero():
    base, root, home = fixture()
    try:
        eval_corpus(home, root, words=False)
        result = run(os.path.join(HERE, "eval_recall.py"), root, home,
                     "--n", "3", "--band", "rare", "--quiet")
        assert result.returncode != 0, result.stdout
        assert "hit@" not in result.stdout, result.stdout
        assert "unmeasured" in result.stdout or "측정 못 함" in result.stdout, result.stdout
        metrics = os.path.join(root, "_private", "state", "metrics-recall.jsonl")
        rec = json.loads(open(metrics, encoding="utf-8").read().splitlines()[-1])
        assert rec["rate"] is None and rec["status"] == "unmeasured" and rec["n"] == 0, rec
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_display_time_preserves_source_timezone():
    import recall
    assert recall._local_time("2026-10-08T12:00:00Z") == recall._local_time("2026-10-08T21:00:00+09:00")
    assert recall._local_time("2026-10-08T12:00:00") == recall._local_time("2026-10-08T12:00:00Z")
    assert recall._local_time("unknown") == "unknown"


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
        assert result.stdout.count("■ 매치 ") == 30, result.stdout[:400]
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
        english = dict(env(root, home), MOTTORI_LANG="en")
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
    sys.path.insert(0, HERE)
    recall = importlib.import_module("recall")
    for text in ("[Claude Code가 보낸 요청]", "[Claude Code requested a review]",
                 "너는 Codex다.", "Claude다。", "FRESH_WORKER run"):
        assert recall._AGENT_TRANSPORT.search(text), text
    assert not recall._AGENT_TRANSPORT.search("ordinary owner words")


TESTS = [
    test_english_output_has_no_hangul,
    test_agent_dispatch_prefix_is_recognised_in_both_languages,
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
