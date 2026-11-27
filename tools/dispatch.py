#!/usr/bin/env python3
"""Run the kit's steps for one runtime hook event: dispatch.py EVENT RUNTIME < payload.

tools/hook.sh starts this once per event (sh tools/hook.sh event EVENT RUNTIME). The runtime's
adapter turns the payload on stdin into one Event that every step receives. An event's steps
(steps(), each with a plain id) run in a fixed order, each in its own thread with a time budget.
A step that raises, exits nonzero or overruns leaves one timestamped line on stderr, which the
launcher sends to state/.hook-errors.log, and the other steps still run; a step that is not
required and overruns is marked so that the session start does not announce it. What the steps
print is merged (context joined, block reasons joined) and written in one write at the end, so the
launcher never sees half an answer. When a required step gives nothing, the exit status is
REQUIRED_FAILED and the launcher answers with its fallback (for session start: run the state
command by hand). The turn record (tools/lib/turns.py) decides which block reasons a turn end sends:
a finding blocks once per turn.
"""
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
from collections import namedtuple

# Messages this module prints in more than one place, or too long to read inline.
HELD = "[kit] Still open from the last turn, which was not stopped for it twice: {reason}"

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]

# What a step receives, whatever the runtime. paths is None when the runtime did not say which
# files an edit touched; continuing is the runtime's own hint that a turn-end check already
# stopped this turn; turn is the runtime's turn id, or None where it has none.
Event = namedtuple("Event", "runtime name session cwd prompt paths continuing turn raw")

REQUIRED_FAILED = 3
OVERRAN = "timed out after {budget}s"
TIME_FORMAT = "[now: %Y-%m-%d %H:%M %Z (%a)]"


def _text(source, key):
    """Return source[key] when it is a non-empty string, else None."""
    value = source.get(key)
    return value if isinstance(value, str) and value else None


def claude_in(name, payload):
    tool_input = payload.get("tool_input")
    path = (_text(tool_input, "file_path") or _text(tool_input, "notebook_path")
            if isinstance(tool_input, dict) else None)
    return Event("claude", name, _text(payload, "session_id"), _text(payload, "cwd"),
                 _text(payload, "prompt"), [path] if path else None,
                 payload.get("stop_hook_active") is True, _text(payload, "prompt_id"), payload)


def claude_out(name, context, block):
    """Return Claude Code's answer as a JSON object, or None for the empty answer."""
    if name == "Stop":
        return {"decision": "block", "reason": "\n\n".join(block)} if block else None
    if name in ("SessionStart", "UserPromptSubmit") and context:
        return {"hookSpecificOutput": {"hookEventName": name,
                                       "additionalContext": "\n".join(context)}}
    return None


# Codex sends Claude Code's field names; an apply_patch edit names its files only in the patch
# headers, relative to the session's folder (system/dev/runtime-capture.md).
PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", re.M)


def codex_in(name, payload):
    event = claude_in(name, payload)
    tool_input = payload.get("tool_input")
    patch = tool_input.get("command") if isinstance(tool_input, dict) else None
    found = PATCH_PATH.findall(patch) if isinstance(patch, str) else []
    turn = payload.get("turn_id")
    return event._replace(runtime="codex",
                          paths=[os.path.join(event.cwd or "", p.strip())
                                 for p in found if p.strip()] or None,
                          turn=turn if isinstance(turn, str) and turn else None)


# Codex reads Claude Code's answer shape: the capture's context and block reached the model.
codex_out = claude_out

AGY_EDIT_TOOLS = ("write_file", "edit_file", "write_to_file", "replace_file_content",
                  "multi_replace_file_content")


def agy_in(name, payload):
    """Antigravity's events as the kit's. PreInvocation comes before every model call, and only
    the first of a prompt (invocationNum 0) is the per-prompt event. A Stop counts only when the
    model ended the turn without a pending tool call; a compaction or an error is not a turn end.
    It has no turn id, so the dispatcher counts prompts. Its continuationActive stays false, so the
    hint is executionNum, which is 0 at a prompt's first Stop and counts the Stops after a
    continuation (system/dev/runtime-capture.md)."""
    kit = name
    if name == "PreInvocation":
        kit = "UserPromptSubmit" if payload.get("invocationNum") == 0 else None
    elif name == "Stop" and payload.get("terminationReason") != "NO_TOOL_CALL":
        kit = None
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    path = _text(args, "Path") or _text(args, "TargetFile") if call.get("name") in AGY_EDIT_TOOLS else None
    return Event("agy", kit, _text(payload, "conversationId"), _text(payload, "cwd"),
                 _text(payload, "lastUserInput") if kit == "UserPromptSubmit" else None,
                 [path] if path else None,
                 isinstance(payload.get("executionNum"), int) and payload["executionNum"] > 0,
                 None, payload)


def agy_out(name, context, block):
    """Return Antigravity's answer; it reads JSON after every exit 0, so {} is the empty one.
    A block is its continue decision, whose reason reaches the model as a system message."""
    if name == "Stop" and block:
        return {"decision": "continue", "reason": "\n\n".join(block)}
    if name in ("SessionStart", "PreInvocation") and context:
        return {"injectSteps": [{"systemMessage": {"systemMessage": "\n".join(context)}}]}
    return {}


ADAPTERS = {"claude": (claude_in, claude_out), "codex": (codex_in, codex_out),
            "agy": (agy_in, agy_out)}


def _tool(name):
    return __import__(name)


def _payload(event):
    # now.precompact reads the Claude shape; built from the Event so every runtime's adapter feeds it.
    return {"session_id": event.session, "cwd": event.cwd}


def _edited(event):
    # Unknown paths still mark the turn: the turn-end check then measures the whole tree.
    return _tool("gate").record_edit(event.session, event.paths, event.cwd)


def injects_time(commands):
    """True when a hook command runs date itself, not a name that merely contains "date". The
    part after "||" is a hook's error handler, whose date goes to the error log, not the model."""
    return any(re.search(r"(^|[;&|\s(`/])date([\s)`]|$)", c.split("||", 1)[0]) for c in commands)


# Where a runtime keeps the user's own hooks, which it runs beside the project's.
USER_HOOKS = {"claude": "~/.claude/settings.json", "codex": "~/.codex/hooks.json"}


def _time(event):
    # A time hook among the user's own hooks already stamps every prompt in every folder; a
    # second line would only cost context.
    if event.runtime in USER_HOOKS:
        try:
            with open(os.path.expanduser(USER_HOOKS[event.runtime]), encoding="utf-8") as f:
                blocks = json.load(f)["hooks"]["UserPromptSubmit"]
            if injects_time(h.get("command", "") for b in blocks for h in b.get("hooks", [])):
                return 0
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    print(time.strftime(TIME_FORMAT))
    return 0


NOTES_BUDGET = 1


def _notes(event):
    # A note counts as shown only when its line reaches the model. A probe's answer is read by
    # nobody, and a line printed after the step's budget is dropped, so neither may count. The
    # deadline stops 0.2 s early to leave time for saving what was shown.
    if _tool("hook_input").probe():
        return 0
    deadline = time.monotonic() + NOTES_BUDGET - 0.2
    return _tool("notes").hook(event.runtime, event.session, deadline)


def _arming(event):
    # The starting runtime's hooks run, so its own stale verdict goes before the notice names the others.
    hookdiag = _tool("hookdiag")
    hookdiag.clear_stale_verdict(os.path.dirname(HERE), event.runtime)
    print(hookdiag.unarmed_notice(os.path.dirname(HERE), event.runtime))


def _index(event):
    # A probe's session start is nobody's session: it starts no work behind one.
    if _tool("hook_input").probe():
        return 0
    return _tool("recall_store").start_catch_up()


# One step of an event. id names it in the error log and for tools that look a step up; budget
# is its time limit in seconds; required means the event's answer is worthless without it;
# skip_on_fallback skips it once a required step has failed, because the launcher then sends its
# own fallback answer and what this step gives would be recorded as received though nobody
# receives it; call runs it.
Step = namedtuple("Step", "id budget required skip_on_fallback call")

STEPS = {
    "SessionStart": [
        Step("state", 15, True, False, lambda e: print(_tool("now").session_state())),
        # The reminder store's lock wait is one second; the rest leaves room for the notes and
        # tasks steps inside the launcher's start limit.
        Step("reminders", 2, False, False, lambda e: _tool("triggers").main(["hook"])),
        Step("notes", NOTES_BUDGET, False, True, _notes),
        Step("arming", 1, False, False, _arming),
        # Before the tasks step, so its line names a catch-up started here. On 10,000 stored
        # messages it took 0.26 s when nothing was behind; its second comes from the tasks step,
        # which has the one second it has at a prompt.
        Step("index", 1, False, False, _index),
        Step("tasks", 1, False, False, lambda e: _tool("tasks").show(e, start=True)),
    ],
    "UserPromptSubmit": [
        Step("time", 1, False, False, _time),
        # It only reads the gate's markers; the seconds it gives up keep the notes and tasks steps
        # inside the launcher's prompt limit.
        Step("resume", 3, False, False, lambda e: _tool("gate").cmd_resume(e.session)),
        Step("notes", NOTES_BUDGET, False, True, _notes),
        Step("tasks", 1, False, False, lambda e: _tool("tasks").show(e)),
    ],
    "PostToolUse": [
        Step("edited", 5, False, False, _edited),
    ],
    "Stop": [
        # First, so a gate that waits on a lock cannot hold back the list of running tasks.
        Step("tasks", 2, False, False, lambda e: _tool("tasks").save(e)),
        # The gate waits up to 150 s for another session's Stop to release its lock.
        Step("gate", 170, False, False,
             lambda e: _tool("gate").cmd_check(e.session, e.continuing)),
        # The delivery check reads Claude Code's transcript; the other runtimes have none yet.
        Step("deliver", 10, False, False,
             lambda e: _tool("deliver").cmd_hook(e.raw) if e.runtime == "claude" else 0),
    ],
    "PreCompact": [
        Step("precompact", 10, False, False,
             lambda e: _tool("now").precompact(e.runtime, _payload(e))),
    ],
}


RESTATE_BUDGET = 1


def _checkpoint(path, seen):
    """Return (whether a compaction row came after byte seen, the byte read up to). Antigravity
    appends a CHECKPOINT row to the transcript when it compacts and sends no event for it
    (system/dev/runtime-capture.md); only whole new lines are read. Without a known offset
    (a conversation never recorded) nothing counts and reading starts at the end."""
    try:
        size = os.path.getsize(path)
    except (OSError, TypeError, ValueError):
        return False, seen
    if not isinstance(seen, int) or not 0 <= seen <= size:
        return False, size
    with open(path, "rb") as f:
        f.seek(seen)
        data = f.read(size - seen)
    data = data[:data.rfind(b"\n") + 1]
    for line in data.splitlines():
        if b"CHECKPOINT" in line:
            try:
                if json.loads(line).get("type") == "CHECKPOINT":
                    return True, seen + len(data)
            except (ValueError, AttributeError):
                pass
    return False, seen + len(data)


def _restate(event):
    """Give an Antigravity conversation the state again when it has not received the current one.

    Antigravity starts no SessionStart for a continued conversation or after a compaction, and a
    message it is given stays in the conversation. So at a prompt's first model call the state is
    injected when it differs from what this conversation last received, or when a compaction row
    appeared since. At session start the state step injects it and this step only records what
    was given.

    What the conversation received (a digest of the state, and the transcript offset read) is
    kept in its turn record (turns.update). A compaction is recorded as an event
    first, so its row is in the state given. The state is printed only after the record says it
    was received: a record that cannot be written gives no state, rather than the state at every
    prompt."""
    # Past the step's budget nothing printed reaches the answer, so the state may no longer be
    # recorded as received; the margin leaves room for the write after the check.
    deadline = time.monotonic() + RESTATE_BUDGET - 0.2
    turns, now = _tool("turns"), _tool("now")

    def update(change, fallback):
        return turns.update(event.runtime, event.session, change, fallback)
    entry = update(dict, None)
    if entry is None:
        return 0
    path = event.raw.get("transcriptPath")
    if event.name == "SessionStart":
        compacted, seen = False, _checkpoint(path, 0)[1] if path else None
    else:
        compacted, seen = _checkpoint(path, entry.get("seen"))
    if compacted:
        # The new offset is saved and the received state cleared before the row is written, so
        # a step abandoned at its budget cannot count this compaction again and the next prompt
        # still gives the state.
        if not update(lambda e: e.update(seen=seen, state=None) or True, False):
            return 0
        now.precompact("agy", _payload(event))
    text = now.build_context()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    give = event.name != "SessionStart" and (compacted or digest != entry.get("state"))

    def received(e):
        if time.monotonic() > deadline:
            return False
        e.update(state=digest, seen=seen)
        return True
    if (give or (digest, seen) != (entry.get("state"), entry.get("seen"))) and not update(
            received, False):
        return 0
    if give:
        print(text)
    return 0


# Antigravity's own steps, after the shared ones.
AGY_STEPS = {
    "SessionStart": [Step("restate", RESTATE_BUDGET, False, True, _restate)],
    "UserPromptSubmit": [Step("restate", RESTATE_BUDGET, False, True, _restate)],
}


def steps(event, runtime):
    """Return the Steps one kit event runs for one runtime, in the order they run."""
    return STEPS.get(event, []) + (AGY_STEPS.get(event, []) if runtime == "agy" else [])


# A declared line of the launcher's event form, in any runtime's spelling of the root: groups
# are the kit event and the runtime it runs.
EVENT_LINE = re.compile(r'hook\.sh"?\s+event\s+(\w+)\s+(\w+)')


class _Outputs(io.TextIOBase):
    """Stands in for sys.stdout while steps run: each step thread writes to its own buffer, and
    a step abandoned at its budget writes nowhere, so it cannot reach a later step's answer."""

    def __init__(self):
        self.buffers = {}

    def writable(self):
        return True

    def write(self, text):
        buffer = self.buffers.get(threading.get_ident())
        if buffer is not None:
            buffer.write(text)
        return len(text)


def _call(outputs, step, event, budget):
    """Run one step in a thread; return (printed text, None) or (None, why it failed)."""
    buffer, result = io.StringIO(), {}

    def target():
        outputs.buffers[threading.get_ident()] = buffer
        try:
            result["rc"] = step(event) or 0
        except SystemExit as exit_:
            result["rc"] = exit_.code if isinstance(exit_.code, int) else 1
        except BaseException as error:  # noqa: BLE001 - a broken step must not cost the others
            result["error"] = f"{type(error).__name__}: {error}"

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(budget)
    if thread.is_alive():
        return None, OVERRAN.format(budget=budget)
    if "error" in result:
        return None, result["error"]
    if result.get("rc"):
        # As a runtime does with a failing hook, the output of a nonzero exit is not used.
        return None, f"rc={result['rc']}"
    return buffer.getvalue(), None


def _failure_words(step, failure):
    """The words a failed step's log line starts with: an optional step past its budget is
    logged as overran, which the session start does not announce; any other failure as failed."""
    if step.required or failure != OVERRAN.format(budget=step.budget):
        return "hook failed"
    try:
        return _tool("runlog").HOOK_OVERRAN
    except Exception:  # noqa: BLE001 - the line is still written, announced like any failure
        return "hook failed"


def _parse(text):
    """Split a step's printed answer into (context blocks, block reasons). A plain answer loses
    only the newline print adds, so a block that ends with its own newline keeps it."""
    plain = text.lstrip().removesuffix("\n")
    text = text.strip()
    if not text:
        return [], []
    try:
        answer = json.loads(text)
    except ValueError:
        return [plain], []
    if not isinstance(answer, dict):
        return [plain], []
    if answer.get("decision") == "block":
        return [], [str(answer.get("reason") or "")]
    output = answer.get("hookSpecificOutput")
    context = output.get("additionalContext") if isinstance(output, dict) else None
    return ([context] if isinstance(context, str) and context.strip() else []), []


def _turn_record(call, fallback):
    """Return call(turns), or fallback when tools/lib/turns.py cannot be loaded."""
    try:
        turns = _tool("turns")
    except Exception as error:  # noqa: BLE001 - a missing record must not cost the answer
        print(time.strftime("%Y-%m-%dT%H:%M:%S"),
              f"hook failed (turn record, {type(error).__name__}: {error})", file=sys.stderr)
        return fallback
    return call(turns)


def run(runtime, name, payload):
    """Run one event's steps and return (answer text, exit status)."""
    adapt_in, adapt_out = ADAPTERS[runtime]
    event = adapt_in(name, payload if isinstance(payload, dict) else {})
    context, block, status = [], [], 0
    outputs, saved = _Outputs(), sys.stdout
    sys.stdout = outputs
    try:
        for step in steps(event.name, event.runtime):
            if status and step.skip_on_fallback:
                continue
            text, failure = _call(outputs, step.call, event, step.budget)
            if failure:
                print(time.strftime("%Y-%m-%dT%H:%M:%S"),
                      f"{_failure_words(step, failure)} ({event.name} step {step.id}, {failure})",
                      file=sys.stderr)
                text = ""
            more, reasons = _parse(text)
            if step.required and not more:
                status = REQUIRED_FAILED
            context += more
            block += reasons
    finally:
        sys.stdout = saved
    if status:
        return "", status
    if event.name == "Stop":
        block = _turn_record(lambda turns: turns.block_once(
            event.runtime, event.session, event.turn, event.continuing, block),
            [] if event.continuing else block)
    elif event.name == "UserPromptSubmit":
        # The gate's own pending line may already repeat a held reason.
        context += [HELD.format(reason=r)
                    for r in _turn_record(lambda turns: turns.count_prompt(event.runtime, event.session), [])
                    if not any(r in c for c in context)]
    answer = adapt_out(name, context, block)
    return (json.dumps(answer, ensure_ascii=False) if answer is not None else ""), 0


def _read_payload():
    try:
        hook_input = _tool("hook_input")
    except Exception:  # noqa: BLE001 - every step that needs the payload fails and is logged
        return {}
    return hook_input.hook_payload()


HELP = (
    "Run the kit's steps for one runtime hook event; the runtimes start it through tools/hook.sh.\n\n"
    "usage: python3 tools/dispatch.py EVENT RUNTIME < payload\n\n"
    "  EVENT    {events}\n"
    "  RUNTIME  {runtimes}\n"
    "  payload  the runtime's hook event as JSON on stdin"
)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]):
        print(HELP.format(events=", ".join(STEPS), runtimes=", ".join(ADAPTERS)))
        return 0
    if len(argv) != 2 or argv[1] not in ADAPTERS:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    name, runtime = argv
    # The answer goes out through a private copy of stdout; children of a step (git, a tool's own
    # subprocess) get /dev/null, so none can hold the launcher's pipe open or write into it.
    answer_fd = os.dup(1)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.close(null)
    text, status = run(runtime, name, _read_payload())
    data = text.encode("utf-8")
    while data:
        data = data[os.write(answer_fd, data):]
    sys.stderr.flush()
    # A step abandoned at its budget may still run; nothing it does may delay or change the exit.
    os._exit(status)


if __name__ == "__main__":
    sys.exit(main())
