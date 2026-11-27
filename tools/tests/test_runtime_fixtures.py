#!/usr/bin/env python3
"""Captured hook inputs and transcripts of Codex and Antigravity, with synthetic ids and paths.

The files under fixtures/runtimes/ are what real sessions sent (system/dev/runtime-capture.md says
which run showed what). This test pins the fields the adapters and readers will rely on, so a
fixture edited by hand cannot drift from the shape the record describes.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "runtimes")
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]

# Any case, with or without dashes: a real id may be written either way.
UUID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.I)
SYNTHETIC_ID = re.compile(r"(?:(?:c0dec0de|a9a9a9a9)-0000-4000-8000-\d{12}|(?:c0dec0de|0{8})0{24})$")
# A server's prefixed id (msg_, resp_, call_, ...): only the synthetic forms may appear.
PREFIXED_ID = re.compile(r"\b[a-z]{2,8}_(?=[0-9A-Za-z]*\d)[0-9A-Za-z]{12,}")
SYNTHETIC_PREFIXED = re.compile(r"(?:msg_c0dec0de|call_0{12})[0-9]*$")
PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", re.M)


def _load(runtime):
    events = {}
    for name in sorted(os.listdir(os.path.join(FIXTURES, runtime))):
        if name.endswith(".json"):
            with open(os.path.join(FIXTURES, runtime, name), encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["runtime"] == runtime and name == data["event"] + ".json", name
            events[data["event"]] = {c["case"]: c for c in data["cases"]}
    return events


def test_captured_inputs_carry_the_fields_adapters_read():
    import transcripts
    for name in ("codex", "agy"):
        for root, _dirs, files in os.walk(os.path.join(FIXTURES, name)):
            for f in files:
                text = open(os.path.join(root, f), encoding="utf-8").read()
                # A capture copied in without its synthetic ids and paths would leak the machine.
                assert not re.search(r"/Users/|/private/|/var/folders/", text), f
                assert all(SYNTHETIC_ID.match(u) for u in UUID.findall(text)), f
                assert set(re.findall(r"/home/[^/\s\"]*", text)) <= {"/home/user"}, f
                assert all(SYNTHETIC_PREFIXED.match(m) for m in PREFIXED_ID.findall(text)), f

    codex = _load("codex")
    assert set(codex) == {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "PreCompact",
                          "PostCompact"}
    for event, cases in codex.items():
        for case in cases.values():
            stdin = case["stdin"]
            assert stdin["hook_event_name"] == event and stdin["session_id"], case["case"]
            # Codex runs a hook in the session's folder, which may be below the repository root.
            assert case["proc_cwd"] == stdin["cwd"], case["case"]
    starts = codex["SessionStart"]
    assert [c["stdin"]["source"] for c in starts.values()] == ["startup", "resume", "compact"]
    assert starts["SessionStart-startup"]["stdin"]["cwd"].endswith("/sub")
    first, repeat = (c["stdin"] for c in codex["UserPromptSubmit"].values())
    assert first["prompt"] == repeat["prompt"] and first["turn_id"] != repeat["turn_id"]
    patches = {k: c["stdin"] for k, c in codex["PostToolUse"].items() if "apply_patch" in k}
    assert {k: PATCH_PATH.findall(s["tool_input"]["command"]) for k, s in patches.items()} == {
        "PostToolUse-apply_patch-add": ["new.txt"],
        "PostToolUse-apply_patch-update": ["upd.txt"],
        "PostToolUse-apply_patch-move": ["mv-src.txt", "moved.txt"],
        "PostToolUse-apply_patch-delete": ["del.txt"],
    }
    assert all(s["tool_name"] == "apply_patch" and s["turn_id"] for s in patches.values())
    stops = [c["stdin"] for c in codex["Stop"].values()]
    assert [s["stop_hook_active"] for s in stops] == [False, True, False]
    assert all(isinstance(s["last_assistant_message"], str) and s["turn_id"] for s in stops)
    assert stops[0]["turn_id"] == stops[1]["turn_id"] != stops[2]["turn_id"]
    assert codex["PreCompact"]["PreCompact-auto"]["stdin"]["trigger"] == "auto"

    transcript = os.path.join(FIXTURES, "codex", "transcript.jsonl")
    meta = transcripts.read_codex_meta(transcript)
    assert meta["cwd"] == starts["SessionStart-startup"]["stdin"]["cwd"] and not meta.get("malformed")
    assert meta["id"] == starts["SessionStart-startup"]["stdin"]["session_id"]
    texts = [transcripts.text_of_codex(json.loads(l)) for l in open(transcript, encoding="utf-8")]
    assert ("user", first["prompt"]) in texts and any(t and t[0] == "assistant" for t in texts)

    agy = _load("agy")
    assert set(agy) == {"SessionStart", "PreInvocation", "PostInvocation", "PostToolUse", "Stop"}
    for event, cases in agy.items():
        for case in cases.values():
            stdin = case["stdin"]
            assert stdin["hookEventName"] == event and stdin["conversationId"], case["case"]
            assert stdin["workspacePaths"] == [stdin["cwd"]], case["case"]
            # Antigravity runs a hook in the folder that holds its hooks file.
            assert case["proc_cwd"] == stdin["cwd"] + "/.agents", case["case"]
            assert stdin["transcriptPath"].endswith("/transcript_full.jsonl"), case["case"]
    pre = {k: (c["stdin"]["invocationNum"], c["stdin"]["initialNumSteps"])
           for k, c in agy["PreInvocation"].items()}
    assert pre["PreInvocation-first"][0] == 0 and pre["PreInvocation-second-prompt"][0] == 0
    assert pre["PreInvocation-after-continue"][0] > 0
    # After a compaction nothing in the hook input says so; only the step count keeps growing.
    assert pre["PreInvocation-after-compact"] == (0, pre["PreInvocation-compact"][1] + 3)
    tools = {c["stdin"]["toolCall"]["name"]: c["stdin"]["toolCall"]["args"]
             for c in agy["PostToolUse"].values()}
    assert {"Path", "Target", "Replacement"} <= set(tools["edit_file"])
    assert all(os.path.isabs(a["Path"]) for n, a in tools.items() if n != "run_command")
    stops = agy["Stop"]
    assert [c["stdin"]["executionNum"] for c in stops.values()] == [0, 1, 0, 0]
    assert not any(c["stdin"]["continuationActive"] for c in stops.values())
    assert stops["Stop-compact"]["stdin"]["terminationReason"] != "NO_TOOL_CALL"
    rows = [json.loads(l) for l in open(os.path.join(FIXTURES, "agy", "transcript.jsonl"),
                                       encoding="utf-8")]
    assert [r["step_index"] for r in rows] == list(range(len(rows)))
    assert [r["type"] for r in rows].count("CHECKPOINT") == 1 and "cwd" not in rows[0]

    # Codex passed about 10 KB of a longer session-start block and dropped its middle without a
    # mark, so the config cannot raise the state block's cap to that size.
    import config
    config.validate({"thresholds": {"now_hook_max_bytes": 6000}})
    try:
        config.validate({"thresholds": {"now_hook_max_bytes": 6001}})
    except ValueError:
        pass
    else:
        raise AssertionError("a state block cap above 6000 bytes was accepted")


TESTS = [test_captured_inputs_carry_the_fields_adapters_read]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"runtime fixtures: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
