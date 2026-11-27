#!/usr/bin/env python3
"""tools/dispatch.py, its turn record tools/lib/turns.py, and the event form of tools/hook.sh: one
process per event, whole answers, a finding blocking once per turn."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch


HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import dispatch  # noqa: E402
import gate  # noqa: E402
import turns  # noqa: E402
from testlib import copy_kit  # noqa: E402

STATE = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "STATE"}}


def _run(name, steps, payload=None, runtime="claude", kit_name=None):
    # The block stamp has its own test below; these calls leave the checkout's stamp alone.
    with patch.dict(dispatch.STEPS, {kit_name or name: steps}), \
            patch.object(turns, "block_once", lambda *args: args[-1]), \
            patch.object(turns, "count_prompt", lambda *args: []), \
            contextlib.redirect_stderr(io.StringIO()) as err:
        text, status = dispatch.run(runtime, name, payload or {})
    return text, status, err.getvalue()


def _step(step_id, budget, required, call):
    return dispatch.Step(step_id, budget, required, False, call)


def _cases(runtime, event):
    path = HERE / "tests" / "fixtures" / "runtimes" / runtime / f"{event}.json"
    return {c["case"]: c["stdin"] for c in json.loads(path.read_text(encoding="utf-8"))["cases"]}


def test_claude_adapter_reads_each_event_shape():
    """Synthetic payloads in the shape Claude Code sends (ids and paths are made up)."""
    common = {"session_id": "sess-1", "cwd": "/work/project", "transcript_path": "/work/t.jsonl"}
    start = dispatch.claude_in("SessionStart", dict(common, hook_event_name="SessionStart",
                                                    source="startup"))
    assert (start.session, start.cwd, start.paths, start.turn, start.continuing) == (
        "sess-1", "/work/project", None, None, False), start
    prompt = dispatch.claude_in("UserPromptSubmit", dict(common, prompt="hello", prompt_id="p-1"))
    assert (prompt.prompt, prompt.turn) == ("hello", "p-1"), prompt
    edit = dispatch.claude_in("PostToolUse", dict(common, prompt_id="p-1", tool_name="Write",
                                                  tool_input={"file_path": "/work/project/a.md"}))
    assert edit.paths == ["/work/project/a.md"], edit
    notebook = dispatch.claude_in("PostToolUse", dict(common, tool_input={"notebook_path": "n.ipynb"}))
    assert notebook.paths == ["n.ipynb"], notebook
    stop = dispatch.claude_in("Stop", dict(common, stop_hook_active=True, prompt_id="p-1",
                                           last_assistant_message="done", background_tasks=[]))
    assert stop.continuing is True and stop.turn == "p-1" and stop.raw["last_assistant_message"] == "done"
    # A string "true" is not the runtime's flag.
    assert dispatch.claude_in("Stop", {"stop_hook_active": "true"}).continuing is False
    assert dispatch.claude_in("Stop", {}).session is None


def test_codex_and_agy_fixtures_pass_through_both_adapters():
    """The captured inputs (system/dev/runtime-capture.md) give the kit's events, and every
    answer is the runtime's own shape."""
    start = _cases("codex", "SessionStart")["SessionStart-startup"]
    event = dispatch.codex_in("SessionStart", start)
    assert (event.runtime, event.name, event.session, event.cwd) == (
        "codex", "SessionStart", start["session_id"], start["cwd"]), event
    prompts = list(_cases("codex", "UserPromptSubmit").values())
    turns = [dispatch.codex_in("UserPromptSubmit", p) for p in prompts]
    assert turns[0].prompt == turns[1].prompt and turns[0].turn != turns[1].turn, turns
    edits = _cases("codex", "PostToolUse")
    paths = {k: dispatch.codex_in("PostToolUse", v).paths for k, v in edits.items()}
    cwd = edits["PostToolUse-apply_patch-add"]["cwd"]
    assert paths["PostToolUse-apply_patch-move"] == [cwd + "/mv-src.txt", cwd + "/moved.txt"], paths
    assert paths["PostToolUse-apply_patch-delete"] == [cwd + "/del.txt"], paths
    assert paths["PostToolUse-Bash"] is None, paths
    blank = dict(edits["PostToolUse-apply_patch-add"],
                 tool_input={"command": "*** Begin Patch\n*** Update File:   \n*** End Patch"})
    assert dispatch.codex_in("PostToolUse", blank).paths is None
    stops = [dispatch.codex_in("Stop", s) for s in _cases("codex", "Stop").values()]
    assert [s.continuing for s in stops] == [False, True, False], stops
    assert stops[0].turn == stops[1].turn != stops[2].turn, stops
    assert dispatch.codex_out("Stop", [], ["fix"]) == {"decision": "block", "reason": "fix"}
    assert dispatch.codex_out("SessionStart", ["S"], [])["hookSpecificOutput"] == {
        "hookEventName": "SessionStart", "additionalContext": "S"}
    assert dispatch.codex_out("PostToolUse", [], []) is None

    agy = {e: _cases("agy", e) for e in ("SessionStart", "PreInvocation", "PostToolUse", "Stop")}
    names = {k: dispatch.agy_in(e, v).name for e, cases in agy.items() for k, v in cases.items()}
    assert names["SessionStart"] == "SessionStart", names
    assert [names[k] for k in ("PreInvocation-first", "PreInvocation-second-prompt",
                               "PreInvocation-after-compact")] == ["UserPromptSubmit"] * 3, names
    assert names["PreInvocation-later"] is names["PreInvocation-after-continue"] is None, names
    # The /compact turn ends by a hook, not by the model: no turn-end check.
    assert names["Stop-compact"] is None and names["Stop-first"] == "Stop", names
    first = dispatch.agy_in("PreInvocation", agy["PreInvocation"]["PreInvocation-first"])
    assert first.prompt and first.session and first.turn is None, first
    edit = dispatch.agy_in("PostToolUse", agy["PostToolUse"]["PostToolUse-edit_file"])
    assert edit.paths == [agy["PostToolUse"]["PostToolUse-edit_file"]["toolCall"]["args"]["Path"]]
    read = dispatch.agy_in("PostToolUse", agy["PostToolUse"]["PostToolUse-read_file"])
    assert read.paths is None, read
    older = dispatch.agy_in("PostToolUse", {"toolCall": {"name": "write_to_file",
                                                         "args": {"TargetFile": "/w/a.md"}}})
    assert older.paths == ["/w/a.md"], older
    assert dispatch.agy_out("Stop", [], ["fix"]) == {"decision": "continue", "reason": "fix"}
    assert dispatch.agy_out("PreInvocation", ["S"], []) == {
        "injectSteps": [{"systemMessage": {"systemMessage": "S"}}]}
    assert dispatch.agy_out("PostToolUse", [], []) == {} == dispatch.agy_out("Stop", [], [])
    # A model call after the first of a prompt runs nothing and still answers {}.
    later = agy["PreInvocation"]["PreInvocation-later"]
    assert _run("PreInvocation", [_step("x", 1, False, lambda e: print("NO"))], later, "agy",
                "UserPromptSubmit")[:2] == ("{}", 0)


def test_each_finding_blocks_once_per_turn():
    import paths
    import safeio
    state = tempfile.mkdtemp(prefix="turn-record-")
    findings = []

    def check(n):
        return lambda event: findings[n:n + 1] and findings[n] and print(json.dumps(
            {"decision": "block", "reason": findings[n]}))
    # Two steps, as the gate and the delivery check are: each gives its own finding.
    steps = {"Stop": [_step("gate", 1, False, check(0)), _step("deliver", 1, False, check(1))],
             "UserPromptSubmit": []}

    def turn(runtime, name, payload):
        with patch.object(paths, "marker", lambda name, root=None: os.path.join(state, name)), \
                patch.dict(dispatch.STEPS, steps), \
                patch.dict(dispatch.AGY_STEPS, {e: [] for e in dispatch.AGY_STEPS}), \
                contextlib.redirect_stderr(io.StringIO()):
            text, status = dispatch.run(runtime, name, payload)
        assert status == 0, (runtime, name)
        return json.loads(text) if text else None

    agy_stop = dict(_cases("agy", "Stop")["Stop-first"])
    agy_prompt = dict(_cases("agy", "PreInvocation")["PreInvocation-first"])
    shapes = {
        # Every Stop here is a first Stop (executionNum 0, no stop_hook_active), so the stamp
        # alone is exercised. Claude Code's prompt_id comes on the prompt only, so the turn key
        # must still move with each prompt.
        "agy": (agy_prompt, agy_stop, "PreInvocation", lambda a: a.get("reason")),
        "claude": ({"session_id": "s", "prompt": "same", "prompt_id": "p"}, {"session_id": "s"},
                   "UserPromptSubmit", lambda a: a and a.get("reason")),
    }
    try:
        for runtime, (prompt, stop, prompt_name, reason) in shapes.items():
            del findings[:]
            findings.append("link a.md -> b.md is broken")
            turn(runtime, prompt_name, prompt)
            assert reason(turn(runtime, "Stop", stop)) == findings[0], runtime
            # A second Stop of the same turn with the same finding does not block again ...
            assert not reason(turn(runtime, "Stop", stop)), runtime
            # ... and the same prompt text again is a new turn, which names it once.
            answer = json.dumps(turn(runtime, prompt_name, prompt), ensure_ascii=False)
            assert findings[0] in answer, (runtime, answer)
            assert findings[0] not in json.dumps(turn(runtime, prompt_name, prompt)), runtime
            assert reason(turn(runtime, "Stop", stop)) == findings[0], runtime
            # A new finding in the same turn blocks; a fixed one is cleared.
            findings.append("second finding")
            assert reason(turn(runtime, "Stop", stop)) == "\n\n".join(findings), runtime
            del findings[:]
            assert not reason(turn(runtime, "Stop", stop)), runtime
            turn(runtime, prompt_name, prompt)
            findings.append("link a.md -> b.md is broken")
            assert reason(turn(runtime, "Stop", stop)) == findings[0], runtime
            # Inside one turn a fixed finding is cleared, so it blocks again when it comes back,
            # alone or beside a finding that stayed open.
            del findings[:]
            assert not reason(turn(runtime, "Stop", stop)), runtime
            findings.append("link a.md -> b.md is broken")
            assert reason(turn(runtime, "Stop", stop)) == findings[0], runtime
            findings.append("second finding")
            assert reason(turn(runtime, "Stop", stop)), runtime
            findings[0] = ""
            assert not reason(turn(runtime, "Stop", stop)), runtime
            findings[0] = "link a.md -> b.md is broken"
            assert reason(turn(runtime, "Stop", stop)) == "\n\n".join(findings), runtime
        # Codex has a turn id: the retry of the same turn is held, the next turn blocks again.
        del findings[:]
        findings.append("only finding")
        stops = list(_cases("codex", "Stop").values())
        assert turn("codex", "Stop", stops[0])["reason"] == "only finding"
        assert turn("codex", "Stop", dict(stops[1], stop_hook_active=False)) is None
        assert turn("codex", "Stop", stops[2])["reason"] == "only finding"
        # Without a stamp the runtime's hint alone decides.
        def broken(*args, **kwargs):
            raise OSError("read-only state")
        with patch.object(safeio, "locked", broken):
            assert turn("codex", "Stop", stops[0])["reason"] == "only finding"
            assert turn("codex", "Stop", stops[1]) is None
            # Antigravity's flag is always false; its count of runs after a continuation is not.
            assert turn("agy", "Stop", agy_stop)["reason"] == "only finding"
            assert turn("agy", "Stop", _cases("agy", "Stop")["Stop-continued"]) == {}
    finally:
        shutil.rmtree(state, ignore_errors=True)


def _steps(event, label):
    # By label, so a step added before it does not shift what the test keeps.
    return [step for step in dispatch.STEPS[event] if step[0] == label]


def test_a_partly_fixed_gate_block_does_not_block_again_in_its_turn():
    """The gate names all its open issues in one reason; fixing one of them must not make the
    others a new finding of the same turn."""
    import gate
    import paths
    state = tempfile.mkdtemp(prefix="dispatch-gate-")
    broken = {"a", "b"}

    def issues(cmd, **_):
        return gate.Checked({f"SETUP.md -> missing-{x}.md" for x in broken} if "linkcheck.py" in cmd[1]
                            else set())

    def stop():
        with contextlib.redirect_stderr(io.StringIO()):
            text, status = dispatch.run("claude", "Stop", {"session_id": "s"})
        assert status == 0
        return json.loads(text)["reason"] if text else None
    try:
        with patch.object(paths, "marker", lambda name, root=None: os.path.join(state, name)), \
                patch.multiple(gate, _issues=issues,
                            _root_ok=lambda: True,
                            _load_baseline=lambda: ({"linkcheck": set(), "now-check": set()}, "ok"),
                            _save_baseline=lambda cur: None), \
                patch.object(gate.runlog, "log_run", lambda *a, **k: None), \
                patch.dict(dispatch.STEPS, {"Stop": _steps("Stop", "gate"),
                                            "UserPromptSubmit": _steps("UserPromptSubmit", "resume")}):
            first = stop()
            assert "missing-a.md" in first and "missing-b.md" in first, first
            broken.discard("b")
            assert stop() is None
            # The next prompt names the held reason once, though the gate's own line repeats it.
            with contextlib.redirect_stderr(io.StringIO()):
                text, _ = dispatch.run("claude", "UserPromptSubmit", {"session_id": "s", "prompt": "x"})
            assert text.count("missing-a.md") == 1, text
            broken.add("c")
            assert "missing-c.md" in stop()
    finally:
        shutil.rmtree(state, ignore_errors=True)


def test_state_reaches_each_runtime_and_agy_again_only_when_it_missed_it():
    """Every runtime gets the state at session start. Antigravity sends no SessionStart for a
    continued conversation or after a compaction, so its next prompt gets the state when the
    conversation has not received the current one, and the prompt after that does not."""
    import now
    import paths
    import safeio
    state = tempfile.mkdtemp(prefix="dispatch-restate-")
    transcript = os.path.join(state, "transcript_full.jsonl")
    current, compactions = ["STATE A"], []

    def session_state():
        return current[0]

    def precompact(runtime, payload):
        compactions.append((runtime, payload["session_id"]))

    def answer(runtime, name, payload, build=lambda: current[0]):
        # Background work recorded in this tree's .git (a session running here) must not reach the answer.
        with patch.object(paths, "marker", lambda name, root=None: os.path.join(state, name)), \
                patch.object(paths, "work_snapshots", lambda root=None: os.path.join(state, "work")), \
                patch.multiple(now, session_state=session_state, precompact=precompact,
                               build_context=build), \
                patch.dict(os.environ, {"MOTTORI_INTERNAL_RUN": "1"}), \
                contextlib.redirect_stderr(io.StringIO()):
            text, status = dispatch.run(runtime, name, payload)
        assert status == 0, (runtime, name)
        return text

    def rows(*kinds):
        with open(transcript, "a", encoding="utf-8") as f:
            f.writelines(json.dumps({"type": k, "content": "x"}) + "\n" for k in kinds)
    agy = {e: {k: dict(v, transcriptPath=transcript) for k, v in _cases("agy", e).items()}
           for e in ("SessionStart", "PreInvocation", "Stop")}
    prompt = agy["PreInvocation"]["PreInvocation-second-prompt"]
    try:
        assert "STATE A" in answer("claude", "SessionStart", {"session_id": "c", "source": "startup"})
        for case, start in _cases("codex", "SessionStart").items():
            assert "STATE A" in json.loads(answer("codex", "SessionStart", start))[
                "hookSpecificOutput"]["additionalContext"], case
        rows("USER_INPUT", "PLANNER_RESPONSE")
        start = json.loads(answer("agy", "SessionStart", agy["SessionStart"]["SessionStart"]))
        assert start["injectSteps"][0]["systemMessage"]["systemMessage"] == "STATE A", start
        # The conversation already has this state: its prompt carries the time only.
        assert "STATE" not in answer("agy", "PreInvocation", agy["PreInvocation"]["PreInvocation-first"])
        # Continued later, after another session changed the state: given once, not again.
        current[0] = "STATE B"
        rows("USER_INPUT")
        assert "STATE B" in answer("agy", "PreInvocation", prompt)
        assert "STATE" not in answer("agy", "PreInvocation", prompt)
        assert answer("agy", "PreInvocation", agy["PreInvocation"]["PreInvocation-later"]) == "{}"
        # An ordinary turn end records no compaction; a checkpoint row is one, recorded once and
        # followed by the state even when the state text did not change.
        answer("agy", "Stop", agy["Stop"]["Stop-first"])
        answer("agy", "Stop", agy["Stop"]["Stop-compact"])
        assert compactions == []
        rows("USER_INPUT", "SYSTEM_MESSAGE")
        # A row still being written is read once its line ends, not skipped.
        with open(transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "CHECKPOINT", "content": "x"}))
        assert "STATE" not in answer("agy", "PreInvocation", prompt) and compactions == []
        with open(transcript, "a", encoding="utf-8") as f:
            f.write("\n")
        after = answer("agy", "PreInvocation", agy["PreInvocation"]["PreInvocation-after-compact"])
        assert "STATE B" in after, after
        assert compactions == [("agy", prompt["conversationId"])], compactions
        assert "STATE" not in answer("agy", "PreInvocation", prompt) and len(compactions) == 1
        # A conversation the stamp never saw gets the state, and an old checkpoint is no news.
        other = dict(prompt, conversationId="a9a9a9a9-0000-4000-8000-0000000000ff")
        assert "STATE B" in answer("agy", "PreInvocation", other) and len(compactions) == 1
        # A step abandoned at its budget records its compaction once, and the next prompt
        # gives the state it could not.
        rows("CHECKPOINT")
        answer("agy", "PreInvocation", prompt, build=threading.Event().wait)
        assert "STATE B" in answer("agy", "PreInvocation", prompt) and len(compactions) == 2
        assert "STATE" not in answer("agy", "PreInvocation", prompt) and len(compactions) == 2
        # A step whose stamp write would land after its budget, when nothing it prints is used
        # any more, does not record the state as received.
        current[0] = "STATE B2"
        write = safeio.atomic_write

        def slow_write(path, *args, **kwargs):
            time.sleep(0.3 if "mottori-turn-record" in path else 0)
            return write(path, *args, **kwargs)
        with patch.object(safeio, "atomic_write", slow_write):
            answer("agy", "PreInvocation", prompt, build=lambda: time.sleep(0.85) or current[0])
        time.sleep(0.6)
        assert "STATE B2" in answer("agy", "PreInvocation", prompt)
        # Other runtimes get the state from their own SessionStart, never at a prompt.
        current[0] = "STATE C"
        assert "STATE" not in answer("codex", "UserPromptSubmit", _cases("codex", "UserPromptSubmit")[
            "UserPromptSubmit-first"])

        # Without a readable stamp the state is never repeated at every prompt.
        def broken(*args, **kwargs):
            raise OSError("read-only state")
        with patch.object(safeio, "locked", broken):
            assert "STATE" not in answer("agy", "PreInvocation", prompt)
        # Nor when the stamp can be locked but not read or replaced.
        current[0] = "STATE D"
        stamp = os.path.join(state, "mottori-turn-record")
        os.remove(stamp)
        os.mkdir(stamp)
        for _ in range(3):
            assert "STATE" not in answer("agy", "PreInvocation", prompt)
    finally:
        shutil.rmtree(state, ignore_errors=True)


# A workspace's engine; its own documents and data stay out of the copy.
WORKSPACE_PARTS = (".gitignore", ".claude", ".codex", ".agents", "AGENTS.md", "CLAUDE.md", "tools",
                   "system", "instance")


@contextlib.contextmanager
def _instance():
    """A fresh instance beside an empty HOME: a kit checkout copied and set up by setup.sh, or,
    where the checkout has no setup.sh (a workspace), its engine and config with a baseline."""
    base = Path(tempfile.mkdtemp(prefix="dispatch-instance-"))
    root, home = base / "inst", base / "home"
    home.mkdir()
    skip = shutil.ignore_patterns(".git", "state", "_private", "__pycache__")
    if (ROOT / "setup.sh").exists():
        # The kit's own files only: an installation's documents and data stay out (KIT-DR-089).
        copy_kit(ROOT, root)
        for old in (root / "instance").glob("config.json*"):
            old.unlink()
        command = ["bash", "setup.sh", "--force", "--name", "fixture"]
    else:
        root.mkdir()
        for part in WORKSPACE_PARTS:
            if (ROOT / part).is_dir():
                shutil.copytree(ROOT / part, root / part, ignore=skip)
            elif (ROOT / part).exists():
                shutil.copy2(ROOT / part, root / part)
        command = [sys.executable, "tools/gate.py", "baseline"]
    # The turn below moves a document Git ignores; an instance's own ignore file need not say so.
    with open(root / ".gitignore", "a", encoding="utf-8") as ignore:
        ignore.write("\n/work/\n")
    (root / "state").mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), MOTTORI_INSTANCE=str(root))
    try:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        done = subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
        yield root.resolve(), env
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _hook(root, env, runtime, event, payload):
    done = subprocess.run(["sh", str(root / "tools" / "hook.sh"), "event", event, runtime],
                          input=json.dumps(payload), cwd=root, env=env, capture_output=True,
                          text=True, timeout=240)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _tree(root):
    """Every file's bytes and modification time, except compiled Python a run may add."""
    out = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__" and not (d == "objects" and folder.endswith(".git"))]
        for name in files:
            path = os.path.join(folder, name)
            out[path] = (os.stat(path).st_mtime_ns, Path(path).read_bytes())
    return out


def test_a_moved_ignored_document_with_a_broken_link_stops_its_turn_once_in_each_runtime():
    """A turn moves an ignored Markdown file so that its link breaks. Codex's patch names both
    paths; Claude Code and Antigravity have no move tool, so the turn writes the new file and the
    shell removes the old one, and the write names the new path. Each runtime's turn is stopped
    once with the paths in its session's edit entry, not again in that turn, and passes after
    the repair. gate.py manual-check judges the same tree by hand and changes no file."""
    with _instance() as (root, env):
        (root / "work" / "sub").mkdir(parents=True)
        (root / "work" / "b.md").write_text("# B\n", encoding="utf-8")

        def manual():
            before = _tree(root)
            done = subprocess.run([sys.executable, "tools/gate.py", "manual-check"], cwd=root,
                                  env=env, capture_output=True, text=True, timeout=240)
            assert _tree(root) == before, "manual-check changed a file"
            return done.returncode, done.stdout

        def edited(session):
            return json.loads((root / ".git" / "mottori-gate-dirty").read_text())[session]["files"]
        codex_prompt = dict(_cases("codex", "UserPromptSubmit")["UserPromptSubmit-first"], cwd=str(root))
        codex_edit = dict(_cases("codex", "PostToolUse")["PostToolUse-apply_patch-move"], cwd=str(root))
        codex_stop = {k: dict(v, cwd=str(root)) for k, v in _cases("codex", "Stop").items()}
        for stop in codex_stop.values():
            stop["session_id"] = codex_prompt["session_id"] = codex_edit["session_id"]
        # The captured cases come from several conversations; here they are one.
        agy = {e: {k: dict(v, cwd=str(root), conversationId="agy-conversation")
                   for k, v in _cases("agy", e).items()}
               for e in ("PreInvocation", "PostToolUse", "Stop")}

        def patch_of(old, new=None):
            head = f"*** Update File: {old}\n" + (f"*** Move to: {new}\n" if new else "")
            return {"command": "*** Begin Patch\n" + head + "@@\n-x\n+x\n*** End Patch"}

        def agy_write(path):
            case = agy["PostToolUse"]["PostToolUse-write_file"]
            return dict(case, toolCall=dict(case["toolCall"], args={"Path": str(path), "Content": "x"}))
        # Per runtime: (turn start, edit after the move, its session, the paths it names,
        # first Stop, the Stop after the block, repair turn start, repair edit, repair Stop).
        turns = {
            "claude": ({"session_id": "cl", "cwd": str(root), "prompt": "move", "prompt_id": "p1"},
                       {"session_id": "cl", "cwd": str(root), "tool_name": "Write",
                        "tool_input": {"file_path": str(root / "work/sub/claude.md")}},
                       "cl", ["work/sub/claude.md"],
                       {"session_id": "cl", "cwd": str(root)},
                       {"session_id": "cl", "cwd": str(root), "stop_hook_active": True},
                       {"session_id": "cl", "cwd": str(root), "prompt": "fix", "prompt_id": "p2"},
                       {"session_id": "cl", "cwd": str(root), "tool_name": "Edit",
                        "tool_input": {"file_path": str(root / "work/sub/claude.md")}},
                       {"session_id": "cl", "cwd": str(root)}),
            "codex": (codex_prompt,
                      dict(codex_edit, tool_input=patch_of("work/codex.md", "work/sub/codex.md")),
                      codex_edit["session_id"], ["work/codex.md", "work/sub/codex.md"],
                      codex_stop["Stop-before"], codex_stop["Stop-retry"], codex_prompt,
                      dict(codex_edit, tool_input=patch_of("work/sub/codex.md")),
                      codex_stop["Stop-fresh-turn"]),
            "agy": (agy["PreInvocation"]["PreInvocation-first"],
                    agy_write(root / "work/sub/agy.md"),
                    agy["Stop"]["Stop-first"]["conversationId"], ["work/sub/agy.md"],
                    agy["Stop"]["Stop-first"], agy["Stop"]["Stop-continued"],
                    agy["PreInvocation"]["PreInvocation-second-prompt"],
                    agy_write(root / "work/sub/agy.md"), agy["Stop"]["Stop-second-prompt"]),
        }
        prompt_event = {"claude": "UserPromptSubmit", "codex": "UserPromptSubmit",
                        "agy": "PreInvocation"}
        quiet = {"claude": "", "codex": "", "agy": "{}"}
        # The link findings the fixture holds before any turn: none in a kit, a workspace copy's own.
        code, out = manual()
        assert code == 0, out
        held = int(re.match(r"checks run: linkcheck (\d+) ", out).group(1))
        for runtime, (start, edit, session, paths, stop, again, fix_start, fix, fix_stop) in turns.items():
            (root / "work" / f"{runtime}.md").write_text("[b](b.md)\n", encoding="utf-8")
            moved = root / "work" / "sub" / f"{runtime}.md"
            _hook(root, env, runtime, prompt_event[runtime], start)
            os.rename(root / "work" / f"{runtime}.md", moved)
            out = _hook(root, env, runtime, "PostToolUse", edit)
            assert out == quiet[runtime], (runtime, out)
            assert edited(session) == paths, (runtime, edited(session))
            if runtime == "codex":
                # By hand, before the turn end: the same finding, and the edit list stays.
                code, out = manual()
                assert code == 1 and out.startswith(f"checks run: linkcheck {held + 1} ") and \
                    "BLOCK: " in out and "work/sub/codex.md -> b.md" in out, out
            answer = json.loads(_hook(root, env, runtime, "Stop", stop))
            assert answer["decision"] in ("block", "continue") and \
                f"work/sub/{runtime}.md -> b.md" in answer["reason"], (runtime, answer)
            if runtime == "codex":
                # While that session's block stands, a check by hand clears nothing.
                pending = (root / ".git" / "mottori-gate-pending").read_bytes()
                assert manual()[0] == 0
                assert (root / ".git" / "mottori-gate-pending").read_bytes() == pending
            assert _hook(root, env, runtime, "Stop", again) == quiet[runtime], runtime
            _hook(root, env, runtime, prompt_event[runtime], fix_start)
            moved.write_text("[b](../b.md)\n", encoding="utf-8")
            _hook(root, env, runtime, "PostToolUse", fix)
            assert _hook(root, env, runtime, "Stop", fix_stop) == quiet[runtime], runtime
        baseline = root / "state" / ".gate-baseline.json"
        baseline.rename(root / "baseline.json")
        code, out = manual()
        assert code == 2 and "UNCHECKED: " in out, out


_FAKE_CODEX = """import json, os, sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("id") == 1:
        print(json.dumps({"id": 1, "result": {}}), flush=True)
    elif msg.get("id") == 2:
        events = ("sessionStart", "userPromptSubmit", "postToolUse", "stop", "preCompact")
        hooks = [{"eventName": e, "source": "project", "enabled": True, "command": "sh hook",
                  "trustStatus": os.environ.get("FAKE_TRUST_" + e, os.environ["FAKE_TRUST"]),
                  "currentHash": "sha256:x"} for e in events]
        print(json.dumps({"id": 2, "result": {"data": [{"hooks": hooks, "errors": []}]}}), flush=True)
"""
# The shape of Antigravity's /hooks listing in print mode (system/dev/runtime-capture.md).
_FAKE_AGY = """import json, os, sys
assert sys.argv[1:] == ["-p", "/hooks", "--output-format", "json"], sys.argv
actions = [{"event": e, "type": "command", "command": "sh ../tools/hook.sh event %s agy" % e,
            "timeout_seconds": 15} for e in ("SessionStart", "PreInvocation", "PostToolUse", "Stop")]
hook = {"name": "kit", "enabled": True, "source": os.path.join(os.getcwd(), ".agents", "hooks.json"),
        "actions": actions}
print(json.dumps({"status": "SUCCESS", "num_turns": 0, "command": {"name": "hooks", "data": {"hooks": [hook]}}}))
"""


def test_doctor_names_each_runtime_armed_unapproved_or_absent_and_session_start_says_so_once():
    """Stand-in codex and agy on an otherwise empty PATH. Doctor's row per runtime is a pass when
    armed, and not applicable when the program is absent. Unapproved, it names the exact one-time
    step: as a later step while the runtime has no session in this folder, and as a warning once
    it has one. Only then does a session start of another runtime carry one line from the cached
    verdict."""
    with _instance() as (root, env):
        bin_dir = root.parent / "bin"
        bin_dir.mkdir()
        rows = {}

        def doctor(trust, programs, trusted_folder, used=()):
            for name in ("codex", "agy"):
                path = bin_dir / name
                if path.exists():
                    path.unlink()
                if name in programs:
                    path.write_text(f"#!{sys.executable}\n" + {"codex": _FAKE_CODEX,
                                                                  "agy": _FAKE_AGY}[name])
                    path.chmod(0o755)
            settings = Path(env["HOME"]) / ".gemini" / "antigravity-cli" / "settings.json"
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps({"trustedWorkspaces": [trusted_folder] if trusted_folder else []}))
            code = ("import json, sys; sys.path.insert(0, 'tools'); import doctor; "
                    f"doctor._sessions_here = lambda: {dict.fromkeys(used, 1)!r}; "
                    "print(json.dumps([doctor.c_hook_codex_armed(), doctor.c_hook_agy_armed()]))")
            done = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                                  env=dict(env, PATH=str(bin_dir), FAKE_TRUST=trust),
                                  timeout=60)
            assert done.returncode == 0, done.stderr
            rows["codex"], rows["agy"] = json.loads(done.stdout)

        def notice(runtime):
            payload = {"claude": {"session_id": "s", "source": "startup"},
                       "codex": _cases("codex", "SessionStart")["SessionStart-startup"],
                       "agy": _cases("agy", "SessionStart")["SessionStart"]}[runtime]
            answer = json.loads(_hook(root, dict(env), runtime, "SessionStart", payload))
            text = (answer["injectSteps"][0]["systemMessage"]["systemMessage"] if runtime == "agy"
                    else answer["hookSpecificOutput"]["additionalContext"])
            return [line for line in text.split("\n") if "do not run in this folder" in line]

        doctor("trusted", (), None)
        assert [r[0] for r in rows.values()] == ["SKIP", "SKIP"], rows
        assert notice("claude") == []
        # Installed, unapproved and never used in this folder: a step for later, and no line.
        doctor("untrusted", ("codex", "agy"), None)
        assert [r[0] for r in rows.values()] == ["SKIP", "SKIP"], rows
        assert 'choose "Trust all"' in rows["codex"][1] and notice("claude") == [], rows
        doctor("untrusted", ("codex", "agy"), None, used=("codex", "agy"))
        assert [r[0] for r in rows.values()] == ["WARN", "WARN"], rows
        assert f'start `codex` in {root} once, trust the folder, then choose "Trust all"' in \
            rows["codex"][1], rows
        assert f"start `agy` in {root} once and answer" in rows["agy"][1], rows
        lines = notice("claude")
        assert len(lines) == 1 and "Hooks of agy, codex do not run" in lines[0], lines
        # A codex session's own hooks run, so it names only the other one and its verdict goes.
        assert "Hooks of agy do not run" in notice("codex")[0]
        assert "Hooks of agy do not run" in notice("claude")[0]
        # Print mode lists the hooks of an untrusted folder too; trust above the folder counts.
        doctor("trusted", ("codex", "agy"), str(root.parent))
        assert [r[0] for r in rows.values()] == ["PASS", "PASS"], rows
        assert notice("claude") == [] and notice("agy") == []
        # The rows are in doctor's list; armed means every kit event; Antigravity's wiring needs no
        # compaction hook; the hooks switch is reported.
        code = ("import json, sys; sys.path.insert(0, 'tools'); import doctor; "
                "doctor._sessions_here = lambda: {'codex': 1}; print(json.dumps(["
                "[f.__name__ for _, _, f, _ in doctor.CHECKS], doctor.c_hook_codex_armed(), "
                "doctor.c_hook_wiring_agy(), doctor.c_hook_wiring()]))")
        done = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                              env=dict(env, PATH=str(bin_dir), FAKE_TRUST="trusted", FAKE_TRUST_stop="untrusted",
                                       MOTTORI_DISABLE_HOOKS="1"), timeout=60)
        names, codex, agy, claude = json.loads(done.stdout)
        assert {"c_runtime_transcripts", "c_hook_wiring_agy", "c_hook_agy_armed"} <= set(names), names
        assert codex[0] == "WARN" and "unarmed: Stop" in codex[1], codex
        assert agy[0] == "PASS" and claude[0] == "WARN" and "MOTTORI_DISABLE_HOOKS=1" in claude[1], (agy, claude)
        # The dispatcher has read stdin, so the compaction row takes the session from the parsed input.
        payload = _cases("codex", "PreCompact")["PreCompact-auto"]
        _hook(root, env, "codex", "PreCompact", payload)
        sid = hashlib.sha256(payload["session_id"].encode()).hexdigest()[:8]
        rows = subprocess.run(["grep", "-rh", "(codex · s:", str(root / "state"), str(root / "_private")],
                              capture_output=True, text=True).stdout
        assert f"(codex · s:{sid})" in rows, rows


def test_agy_is_not_started_for_a_user_who_has_never_run_it():
    """Without a login Antigravity opens a browser to sign in. Tests run under an empty HOME, so a
    doctor run there must not start the program: the listing refuses when its data folder is absent."""
    with tempfile.TemporaryDirectory() as tmp:
        marker, stub = Path(tmp) / "started", Path(tmp) / "agy"
        stub.write_text(f"#!{sys.executable}\nopen({str(marker)!r}, 'w').close()\n")
        stub.chmod(0o755)
        code = ("import sys; sys.path.insert(0, 'tools/lib'); import hookdiag\n"
                "try:\n    hookdiag.agy_hooks_list('.', agy_bin=sys.argv[1])\n"
                "except FileNotFoundError as e:\n    print('refused:', e)\n")
        done = subprocess.run([sys.executable, "-c", code, str(stub)], cwd=ROOT, capture_output=True,
                              text=True, env=dict(os.environ, HOME=tmp), timeout=30)
        assert done.stdout.startswith("refused: agy has not been run by this user"), (done.stdout, done.stderr)
        assert not marker.exists()


def test_steps_are_found_by_plain_id():
    """Tools outside the dispatcher look a step up by its id through steps(event, runtime)."""
    ids = {event: [step.id for step in dispatch.steps(event, "claude")] for event in dispatch.STEPS}
    assert ids == {"SessionStart": ["state", "reminders", "notes", "arming", "index", "tasks"],
                   "UserPromptSubmit": ["time", "resume", "notes", "tasks"],
                   "PostToolUse": ["edited"], "Stop": ["tasks", "gate", "deliver"],
                   "PreCompact": ["precompact"]}, ids
    agy = [step.id for step in dispatch.steps("UserPromptSubmit", "agy")]
    assert agy == ids["UserPromptSubmit"] + ["restate"], agy
    assert all(isinstance(step.budget, (int, float)) and step.budget > 0
               for event in dispatch.STEPS for step in dispatch.steps(event, "agy"))
    # Only the steps whose output would be recorded as received are skipped on the fallback.
    assert {step.id for event in dispatch.STEPS for step in dispatch.steps(event, "agy")
            if step.skip_on_fallback} == {"notes", "restate"}


def test_answers_are_merged_in_order():
    def say(text):
        return lambda event: print(text)

    def blocks(reason):
        return lambda event: print(json.dumps({"decision": "block", "reason": reason}))
    text, status, _ = _run("SessionStart", [
        _step("a", 1, True, lambda e: print(json.dumps(STATE))), _step("b", 1, False, say("REMINDER"))])
    assert status == 0 and json.loads(text)["hookSpecificOutput"]["additionalContext"] == "STATE\nREMINDER"
    text, _, _ = _run("Stop", [_step("a", 1, False, blocks("first")), _step("b", 1, False, blocks("second"))])
    assert json.loads(text) == {"decision": "block", "reason": "first\n\nsecond"}, text
    text, _, _ = _run("Stop", [_step("a", 1, False, say(""))])
    assert text == "", text
    # A plain block that ends with its own newline keeps it, so the next block stays a paragraph
    # apart, as the state text did when it came wrapped in JSON.
    text, _, _ = _run("SessionStart", [
        _step("a", 1, True, lambda e: print("STATE\n")), _step("b", 1, False, say("REMINDER"))])
    assert json.loads(text)["hookSpecificOutput"]["additionalContext"] == "STATE\n\nREMINDER", text
    # The delivery check reads Claude Code's transcript and runs for no other runtime.
    import deliver
    deliver_step = [s for s in dispatch.STEPS["Stop"] if s[0] == "deliver"]
    with patch.object(deliver, "cmd_hook", lambda payload: print(json.dumps(
            {"decision": "block", "reason": "reread"}))):
        assert "reread" in _run("Stop", deliver_step)[0]
        assert _run("Stop", deliver_step, runtime="codex")[0] == ""
        agy_stop = {"terminationReason": "NO_TOOL_CALL"}
        assert _run("Stop", deliver_step, agy_stop, runtime="agy")[0] == "{}"
    # A time hook in the user's global settings already stamps the prompt; the step adds none.
    time_step = [dispatch.STEPS["UserPromptSubmit"][0]]
    home = tempfile.mkdtemp(prefix="dispatch-home-")
    try:
        with patch.dict(os.environ, {"HOME": home}):
            assert "[now: " in _run("UserPromptSubmit", time_step)[0]
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "settings.json"), "w", encoding="utf-8") as f:
                json.dump({"hooks": {"UserPromptSubmit": [{"hooks": [
                    {"type": "command", "command": "date '+[now: %H:%M]'"}]}]}}, f)
            assert _run("UserPromptSubmit", time_step)[0] == ""
            # Codex runs the user's own hooks file beside the project's, the same way.
            assert "[now: " in _run("UserPromptSubmit", time_step, runtime="codex")[0]
            os.makedirs(os.path.join(home, ".codex"))
            shutil.copy(os.path.join(home, ".claude", "settings.json"),
                        os.path.join(home, ".codex", "hooks.json"))
            assert _run("UserPromptSubmit", time_step, runtime="codex")[0] == ""
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_a_failing_or_slow_step_does_not_cost_the_state_block():
    def boom(event):
        raise RuntimeError("reminder store broke")

    def slow(event):
        time.sleep(5)

    def nonzero(event):
        print("IGNORED")
        return 2
    state = _step("state", 1, True, lambda e: print(json.dumps(STATE)))
    for label, step in (("raises", boom), ("sleeps", slow), ("exits 2", nonzero)):
        started = time.monotonic()
        text, status, err = _run("SessionStart", [state, _step("reminders", 0.5, False, step)])
        assert time.monotonic() - started < 3, label
        assert status == 0 and json.loads(text)["hookSpecificOutput"]["additionalContext"] == "STATE", (
            label, text)
        words = "hook overran" if label == "sleeps" else "hook failed"
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} " + words
                        + r" \(SessionStart step reminders, ", err), err
    # Without the required state step the dispatcher answers nothing, so the launcher falls back.
    for step in (boom, slow, lambda e: None):
        text, status, _ = _run("SessionStart", [_step("state", 0.5, True, step)])
        assert (text, status) == ("", dispatch.REQUIRED_FAILED), (text, status)


def test_steps_get_one_parsed_payload():
    seen = []
    payload = {"session_id": "s", "tool_input": {"file_path": "x.md"}}
    _run("PostToolUse", [_step("a", 1, False, seen.append), _step("b", 1, False, seen.append)], payload)
    assert len(seen) == 2 and seen[0] is seen[1] and seen[0].paths == ["x.md"], seen


def _project(dispatcher):
    """A project with the real launcher and a stand-in dispatcher."""
    project = Path(tempfile.mkdtemp(prefix="dispatch-launcher-"))
    (project / "tools").mkdir()
    (project / "state").mkdir()
    shutil.copy2(HERE / "hook.sh", project / "tools" / "hook.sh")
    (project / "tools" / "dispatch.py").write_text(dispatcher, encoding="utf-8")
    return project


def _launch(project, event, env=None, runtime="claude"):
    return subprocess.run(["sh", str(project / "tools" / "hook.sh"), "event", event, runtime],
                          input='{"session_id": "s"}', capture_output=True, text=True,
                          env=dict(os.environ, **(env or {})), timeout=60)


def test_launcher_answers_whole_or_falls_back():
    partial = ("import os, sys\n"
               "sys.stdout.write('{\"hookSpecificOutput\": {\"additionalContext\": \"HALF')\n"
               "sys.stdout.flush()\n"
               "os.kill(os.getpid(), 9)\n")
    project = _project(partial)
    try:
        result = _launch(project, "SessionStart")
        assert result.returncode == 0, result
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert context.startswith("[kit]") and "HALF" not in result.stdout, result.stdout
        for marker in ("state/NOW.md", "_private/state/NOW.md", "unavailable"):
            assert marker in context, marker
        log = (project / "state" / ".hook-errors.log").read_text(encoding="utf-8")
        assert "hook failed (event SessionStart claude, rc=137)" in log, log
        # Codex reads the same answer; Antigravity gets its own shape of the same text.
        codex = _launch(project, "SessionStart", runtime="codex")
        assert json.loads(codex.stdout)["hookSpecificOutput"]["additionalContext"] == context
        agy = json.loads(_launch(project, "SessionStart", runtime="agy").stdout)
        assert agy == {"injectSteps": [{"systemMessage": {"systemMessage": context}}]}, agy
        # Other events have no fallback text: the empty answer, which is {} for Antigravity.
        for runtime, empty in (("claude", ""), ("codex", ""), ("agy", "{}\n")):
            result = _launch(project, "Stop", runtime=runtime)
            assert (result.returncode, result.stdout) == (0, empty), result
        # Switched off: the empty answer before Python starts.
        (project / "state" / ".hook-errors.log").unlink()
        for runtime, empty in (("claude", ""), ("agy", "{}\n")):
            result = _launch(project, "SessionStart", {"MOTTORI_DISABLE_HOOKS": "1"}, runtime)
            assert (result.returncode, result.stdout) == (0, empty), result
        assert not (project / "state" / ".hook-errors.log").exists()
    finally:
        shutil.rmtree(project, ignore_errors=True)


def test_launcher_drops_an_overrunning_dispatcher():
    hang = ("import sys, time\n"
            "sys.stdout.write('{\"partial\": ')\n"
            "sys.stdout.flush()\n"
            "time.sleep(120)\n")
    project = _project(hang)
    try:
        started = time.monotonic()
        result = _launch(project, "UserPromptSubmit")
        assert time.monotonic() - started < 20, time.monotonic() - started
        assert (result.returncode, result.stdout) == (0, ""), result
        log = (project / "state" / ".hook-errors.log").read_text(encoding="utf-8")
        assert "hook failed (event UserPromptSubmit claude, rc=137)" in log, log
    finally:
        shutil.rmtree(project, ignore_errors=True)


# The fixed command text of each runtime (system/dev/runtime-capture.md). Codex ties its approval
# to this text, the timeout and the position, so none of them may change.
FIXED = {
    "claude": 'sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" event {} claude',
    "codex": 'sh "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/tools/hook.sh" event {} codex',
    "agy": "sh ../tools/hook.sh event {} agy",
}
AGY_EVENTS = {"SessionStart": "SessionStart", "UserPromptSubmit": "PreInvocation",
              "PostToolUse": "PostToolUse", "Stop": "Stop"}


def _declared(runtime):
    """Return {event: [handler]} of a declaration file, whatever its shape."""
    import hookdiag
    path = {"claude": ".claude/settings.json", "codex": ".codex/hooks.json",
            "agy": ".agents/hooks.json"}[runtime]
    return hookdiag.declared(runtime, json.loads((ROOT / path).read_text(encoding="utf-8")))


def test_declared_lines_and_time_limits_agree():
    """One fixed line per event in each runtime's file, a declared timeout above the launcher's
    limit, and that limit above the sum of the event's step budgets."""
    launcher = (HERE / "hook.sh").read_text(encoding="utf-8")
    limits = dict(re.findall(r"^\s+(\w+|\*)\) limit=(\d+) ;;", launcher, re.M))
    for runtime, fixed in FIXED.items():
        hooks = _declared(runtime)
        names = AGY_EVENTS if runtime == "agy" else {e: e for e in dispatch.STEPS}
        for event, steps in dispatch.STEPS.items():
            name = names.get(event)
            if name is None:
                continue
            lines = [h for h in hooks[name] if "hook.sh" in h["command"] and " event " in h["command"]]
            assert [h["command"] for h in lines] == [fixed.format(name)], (runtime, event, lines)
            limit = int(limits.get(name, limits["*"]))
            assert lines[0]["timeout"] >= limit + 5, (runtime, event, lines[0], limit)
            steps = steps + (dispatch.AGY_STEPS.get(event, []) if runtime == "agy" else [])
            assert limit >= sum(step[1] for step in steps) + 3, (runtime, event, limit)
        # No entry for an event the kit does not use.
        assert set(hooks) - {"PreToolUse"} == set(names.values()), (runtime, set(hooks))
    # Antigravity's edit tools under both generations of names.
    matcher = json.loads((ROOT / ".agents" / "hooks.json").read_text(encoding="utf-8"))[
        "kit"]["PostToolUse"][0]["matcher"]
    for tool in ("write_file", "edit_file", "write_to_file", "replace_file_content",
                 "multi_replace_file_content"):
        assert re.search(matcher, tool), tool
    assert not re.search(matcher, "read_file") and not re.search(matcher, "run_command")


TESTS = [
    test_claude_adapter_reads_each_event_shape,
    test_codex_and_agy_fixtures_pass_through_both_adapters,
    test_each_finding_blocks_once_per_turn,
    test_a_partly_fixed_gate_block_does_not_block_again_in_its_turn,
    test_state_reaches_each_runtime_and_agy_again_only_when_it_missed_it,
    test_a_moved_ignored_document_with_a_broken_link_stops_its_turn_once_in_each_runtime,
    test_doctor_names_each_runtime_armed_unapproved_or_absent_and_session_start_says_so_once,
    test_agy_is_not_started_for_a_user_who_has_never_run_it,
    test_steps_are_found_by_plain_id,
    test_answers_are_merged_in_order,
    test_a_failing_or_slow_step_does_not_cost_the_state_block,
    test_steps_get_one_parsed_payload,
    test_launcher_answers_whole_or_falls_back,
    test_launcher_drops_an_overrunning_dispatcher,
    test_declared_lines_and_time_limits_agree,
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
    print(f"dispatch: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
