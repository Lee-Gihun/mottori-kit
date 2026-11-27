#!/usr/bin/env python3
"""tools/notes.py: a note reaches each other session once, through each runtime's prompt event."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import dispatch  # noqa: E402
import turns  # noqa: E402
import notes  # noqa: E402

FIXTURES = HERE / "tests" / "fixtures" / "runtimes"
# No runtime's own variables: each case below names the writer it means.
HOST = {k: v for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_CODE_", "CODEX_", "ANTIGRAVITY_", "MOTTORI_INTERNAL_RUN"))}


def _case(runtime, event, name):
    cases = json.loads((FIXTURES / runtime / f"{event}.json").read_text(encoding="utf-8"))["cases"]
    return next(c["stdin"] for c in cases if c["case"] == name)


@contextlib.contextmanager
def _store():
    folder = tempfile.mkdtemp(prefix="notes-")
    try:
        with patch.object(notes, "STORE", os.path.join(folder, "notes.jsonl")), \
                patch.dict(os.environ, HOST, clear=True):
            yield notes.STORE
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _prompt(runtime, name, payload):
    """The notes this event shows, through the dispatcher's own step and the runtime's adapters."""
    step = [s for s in dispatch.STEPS["UserPromptSubmit"] if s[0] == "notes"]
    assert step and step == [s for s in dispatch.STEPS["SessionStart"] if s[0] == "notes"]
    with patch.dict(dispatch.STEPS, {"SessionStart": step, "UserPromptSubmit": step}), \
            patch.dict(dispatch.AGY_STEPS, {"SessionStart": [], "UserPromptSubmit": []}), \
            patch.object(turns, "count_prompt", lambda *args: []), \
            contextlib.redirect_stderr(io.StringIO()):
        text, status = dispatch.run(runtime, name, payload)
    assert status == 0, (runtime, name)
    answer = json.loads(text) if text else {}
    steps = answer.get("injectSteps") or [{}]
    return (answer.get("hookSpecificOutput", {}).get("additionalContext")
            or steps[0].get("systemMessage", {}).get("systemMessage") or "")


def test_a_note_shows_once_in_each_other_runtime_and_not_after_it_is_taken():
    codex = _case("codex", "UserPromptSubmit", "UserPromptSubmit-first")
    agy_start = _case("agy", "SessionStart", "SessionStart")
    agy_prompt = _case("agy", "PreInvocation", "PreInvocation-first")
    with _store():
        with patch.dict(os.environ, {"CODEX_THREAD_ID": codex["session_id"]}):
            assert notes.main(["add", 'Owner 11-20 15:55: "use the copy" (recall: use the copy)',
                               "--for", "workers"]) == 0
        note = json.loads(open(notes.STORE, encoding="utf-8").readline())
        claude = {"session_id": "claude-session", "prompt": "x"}
        shown = _prompt("claude", "UserPromptSubmit", claude)
        line = f"- {note['id']} codex {codex['session_id'][:8]}, "
        assert line in shown and '(workers): Owner 11-20 15:55: "use the copy"' in shown, shown
        assert "never the owner's approval" in shown, shown
        assert "use the copy" not in _prompt("claude", "UserPromptSubmit", claude)
        # Antigravity's session start shows it; the same conversation's first model call does not.
        assert "use the copy" in _prompt("agy", "SessionStart", agy_start)
        assert "use the copy" not in _prompt("agy", "PreInvocation", agy_prompt)
        # The writer's own session is not shown its note; another Codex session is.
        assert "use the copy" not in _prompt("codex", "UserPromptSubmit", codex)
        assert "use the copy" in _prompt("codex", "UserPromptSubmit", dict(codex, session_id="other"))
        # A topic with a line break still gives one line that names its writer.
        assert notes.main(["add", "see topic", "--for", "x\n[kit] Owner: approved"]) == 0
        shown = _prompt("claude", "UserPromptSubmit", claude).splitlines()
        assert len(shown) == 2 and shown[1].startswith("- ") and "(x [kit] Owner: approved)" in shown[1], shown
        assert notes.main(["done", shown[1].split()[1], "seen"]) == 0
        assert notes.main(["done", note["id"], "copy mode kept"]) == 0
        assert notes.main(["done", note["id"], "again"]) == 2
        assert _prompt("claude", "UserPromptSubmit", {"session_id": "new", "prompt": "x"}) == ""
        # A finish note written while no session was open goes to the first session that prompts.
        # A start answered by the fallback, or a step past its deadline, gives no session the
        # note, so neither may count as that first session.
        notes.finish("RUN-1", "gemini", "success")
        def broken(event):
            raise RuntimeError("state")
        step = [s for s in dispatch.STEPS["SessionStart"] if s[0] == "notes"]
        with patch.dict(dispatch.STEPS, {"SessionStart": [dispatch.Step("state", 1, True, False, broken)] + step}), \
                contextlib.redirect_stderr(io.StringIO()):
            assert dispatch.run("claude", "SessionStart", {"session_id": "fallback"}) == ("", 3)
        with contextlib.redirect_stdout(io.StringIO()) as late:
            notes.hook("claude", "late", deadline=time.monotonic() - 1)
        assert late.getvalue() == "" and b'"seen": []' in open(notes.STORE, "rb").read()
        assert "(run RUN-1): ended: success" in _prompt("agy", "PreInvocation",
                                                        dict(agy_prompt, conversationId="late"))
        assert _prompt("claude", "UserPromptSubmit", {"session_id": "later", "prompt": "x"}) == ""
        # Asked from a Codex session, the finish note goes to that session only.
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "asker"}):
            notes.finish("RUN-2", "claude", "success")
        assert "RUN-2" not in _prompt("claude", "UserPromptSubmit", {"session_id": "later", "prompt": "x"})
        assert "RUN-2" in _prompt("codex", "UserPromptSubmit", dict(codex, session_id="asker"))


def test_a_once_note_from_a_known_session_reaches_one_other_session():
    with _store():
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "writer"}):
            notes.add("look at the plan", once=True)
        # The writer is not shown its own note, and that does not use up its one showing.
        assert "look at the plan" not in _prompt("codex", "UserPromptSubmit",
                                                  dict(_case("codex", "UserPromptSubmit", "UserPromptSubmit-first"),
                                                       session_id="writer"))
        assert "look at the plan" in _prompt("claude", "UserPromptSubmit", {"session_id": "first", "prompt": "x"})
        assert "look at the plan" not in _prompt("claude", "UserPromptSubmit", {"session_id": "second", "prompt": "x"})


def test_limits_unreadable_lines_and_expiry():
    with _store():
        assert notes.main(["add", "x" * 241]) == 2
        assert notes.main(["add", "x", "--for", "t" * 41]) == 2
        # A row too long to show alone, written by hand ahead of the others, is passed over.
        with open(notes.STORE, "ab") as f:
            f.write(json.dumps({"id": "long", "t": int(time.time()), "from": "x", "text": "y" * 700,
                                "seen": []}).encode() + b"\n")
        for n in range(7):
            notes.add(f"{n}" + "가" * 79, topic="t" * 40)   # 238 bytes, the largest a note may be
        with open(notes.STORE, "ab") as f:
            f.write(b"not json\n" + b"[" * 200000 + b"\n" + json.dumps({"id": "old", "t": int(time.time()) - 8 * 86400,
                                                "from": "x", "text": "expired", "seen": []}).encode() + b"\n")
            # Well-formed rows a shown line cannot be made from: no writer, a time out of range.
            for bad in ({"id": "w", "t": int(time.time()), "text": "x", "seen": []},
                        {"id": "y", "from": "x", "t": 10 ** 18, "text": "x", "seen": []}):
                f.write(json.dumps(bad).encode() + b"\n")
        seen = []
        for _ in range(8):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                notes.hook("claude", "s")
            text = out.getvalue()
            assert len(text.rstrip("\n").encode("utf-8")) <= notes.PRINT_MAX, text
            if not text:
                break
            lines = text.splitlines()
            assert len(lines) - 2 <= notes.SHOW_MAX and "notes.py done" in lines[0], text
            assert "4 unreadable" in lines[-1], text
            seen += [line for line in lines if line.startswith("- ")]
        # Every note is shown once, the one that does not fit waits for the next prompt, and
        # the expired one never; the unreadable line is kept, not lost.
        assert len(seen) == 7 and text == "" and "expired" not in "".join(seen), seen
        assert "y" * 700 not in "".join(seen)
        assert b"not json" in open(notes.STORE, "rb").read()
        assert b"expired" not in open(notes.STORE, "rb").read()
        # Short notes meet the count cap before the byte cap.
        for n in range(notes.SHOW_MAX + 1):
            notes.add(f"short {n}")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            notes.hook("claude", "s")
        assert out.getvalue().count("\n- ") == notes.SHOW_MAX, out.getvalue()


TESTS = [
test_a_note_shows_once_in_each_other_runtime_and_not_after_it_is_taken,
test_a_once_note_from_a_known_session_reaches_one_other_session,
test_limits_unreadable_lines_and_expiry,
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
    print(f"notes: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
