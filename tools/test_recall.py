#!/usr/bin/env python3
"""recall.py, memlib transcript discovery, and Codex root-thread regressions."""
import json
import os
import shutil
import subprocess
import sys
import tempfile


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


TESTS = [
    test_transcript_directory_mangling,
    test_other_cwd_rollout_is_excluded_by_default,
    test_authored_only_excludes_agents_and_system_injection,
    test_sessions_default_is_40,
    test_codex_root_thread_uses_authored_turn_count,
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
