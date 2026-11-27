#!/usr/bin/env python3
"""Check a finished turn once before it reaches the owner.

A step of the turn-end event (tools/dispatch.py). It looks at the last assistant message and the
tool calls of the turn, and evaluates cheap deterministic signals. No model is called.

Each signal runs in one of two modes set in the instance config (`deliver.block`, `deliver.observe`).
An observed signal is only recorded, so its hit rate can be judged before it is trusted. A blocking
signal stops the turn once: the reason names only the signals that fired and quotes the owner's
request, so the agent rereads its own output as the recipient. A second Stop call in the same turn
passes and records whether the answer changed, the check's own effect measure (the dispatcher's
turns.block_once would hold back a repeated block anyway). With no signal in the config the hook
returns before it reads the transcript, so it checks and records nothing.

Signals:
  unopened  a reading document written this turn is delivered without being reopened
  reader    a long report at the end of a long working turn (off unless configured)

`deliver.send_tools` lists the tool names that count as delivering a file to the owner. Shell-style
wildcards are allowed, so a document connector can be listed once.

Signals that judge wording alone (asking the owner to do something, claiming that a check passed)
are deliberately absent: wording cannot tell whether such a sentence is legitimate. The decision
record KIT-DR-022 holds the measurements behind this choice.

Commands: hook (the payload on stdin), check --message FILE [--request FILE] [--transcript FILE]
(manual), stats.

No hook line is pasted for it; it checks nothing until the signals are named in the instance
config, for example "deliver": {"observe": ["unopened"]}.
"""
import datetime
import fnmatch
import hashlib
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import hook_input
import paths as P

# Messages this module prints in more than one place, or too long to read inline.
# The reply the block asks for when nothing needs fixing.
UNCHANGED = "checked: unchanged"
HEAD = (
    "[pre-delivery check] Look once more before this reaches the owner. Fix only what applies "
    "below. If nothing needs fixing, write only \"{unchanged}\"."
)
READER = (
    "- This is a long report after long work. Reread it as the recipient. (1) Is the answer to "
    "what the owner asked within the first two sentences? (2) Do names, abbreviations, or "
    "numbers you coined while working appear without explanation? (3) Is there content the "
    "owner did not ask for that does not change the answer? If you fix anything, write the "
    "whole report again."
)
UNOPENED = (
    "- You delivered what you wrote this turn without reopening it: {files}. Read each from "
    "start to end yourself, and say in one line what you fixed."
)

LOG = P.deliver_log()
ALL_SIGNALS = ("unopened", "reader")
EDIT_TOOLS = ("Write", "Edit", "NotebookEdit")
SEND_TOOLS = ("SendUserFile", "Artifact")
READING_EXT = (".md", ".html", ".htm", ".txt", ".pdf", ".docx", ".pptx")
# A document shorter than this is cheap to check in the message itself.
MIN_DOCUMENT_CHARS = 1500
FENCE = re.compile(r"```.*?```", re.S)
# User-role rows that the runtime injects rather than the owner types. Modelled on recall.py
# _SYS_INJECT; kept local so the Stop hook does not import the recall tool.
# A slash command row (<command-name>) is typed by the owner, so it is not listed: it opens a turn.
INJECTED = re.compile(r"^\s*(<(system-reminder|task-notification|local-command)\b"
                      r"|\[Request interrupted)", re.I)
# The reply the block asks for when nothing needs fixing, compared without quotes and a final period.
UNCHANGED_STRIP = " \t\r\n\"'`“”‘’.。"


def modes(config=None):
    """Return (blocking signals, observed signals) of the instance config's optional `deliver`
    block; a broken config means defaults. Blocking wins when a signal is listed twice."""
    config = C.deliver() if config is None else config
    block = config.get("block", ())
    observe = config.get("observe", ())
    block = tuple(s for s in ALL_SIGNALS if isinstance(block, (list, tuple)) and s in block)
    observe = tuple(s for s in ALL_SIGNALS
                    if isinstance(observe, (list, tuple)) and s in observe and s not in block)
    return block, observe


def prose(text):
    """Drop fenced code and quoted lines; signals read what the agent says, not what it shows."""
    text = FENCE.sub("", text or "")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def scan_turn(transcript_path):
    """Return (owner request, tool calls, turn key) for the turn after the last owner message.

    A tool call is (name, serialized input). An unreadable or unknown transcript yields an empty
    turn, which leaves only the message-based signals active.
    The turn key names that turn within its transcript: the owner message's position among the
    owner messages, then a digest of its text. A re-entered Stop call of the same turn sees the
    same key; a later turn sees a different position even when its request repeats the text.
    The key is None when the transcript has no owner message.
    """
    request, tools, ordinal = "", [], 0
    try:
        f = open(transcript_path, encoding="utf-8")
    except (OSError, TypeError):
        return request, tools, None
    # Stream the rows: reading a long session's transcript whole costs gigabytes at every turn end.
    with f:
        for raw in f:
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            message = row.get("message") if isinstance(row, dict) else None
            if not isinstance(message, dict):
                continue
            role, content = message.get("role"), message.get("content")
            if role == "user":
                text = _owner_text(row, content)
                if text:
                    request, tools, ordinal = text, [], ordinal + 1
            elif role == "assistant" and isinstance(content, list):
                tools += [(c.get("name", ""), json.dumps(c.get("input", {}), ensure_ascii=False))
                          for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
    return request, tools, (f"{ordinal}:{digest(request)}" if ordinal else None)


def _owner_text(row, content):
    """Return what the owner typed in a user row, or "" for a row that is not an owner message."""
    if row.get("isMeta") or row.get("isCompactSummary"):
        return ""
    # Notices and reminders arrive as user rows; only a human origin is an owner request.
    origin = row.get("origin")
    human = isinstance(origin, dict) and origin.get("kind") == "human"
    if isinstance(origin, dict) and origin.get("kind", "human") != "human":
        return ""
    # Filter injected text per block: the runtime often stores an owner message as a list whose
    # first block is a reminder and whose later block is what the owner typed.
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
            return ""
        blocks = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    else:
        return ""
    owned = [b for b in blocks if b.strip() and not INJECTED.match(b)]
    # A human origin is an owner message whatever its text; keep the raw text to quote.
    if not owned and human:
        owned = [b for b in blocks if b.strip()]
    return "\n".join(owned).strip()


def _send_tools(config):
    """Return the tool-name patterns that count as delivering a file to the owner."""
    names = config.get("send_tools")
    if isinstance(names, (list, tuple)) and all(isinstance(n, str) for n in names):
        return tuple(names)
    return SEND_TOOLS


def _sends(name, patterns):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def edited_paths(tools):
    """Yield (index, path, input) for each call among a turn's tools that wrote or edited a file."""
    for index, (name, raw) in enumerate(tools):
        # scan_turn serialized each input itself, so only its shape needs checking.
        data = json.loads(raw) if name in EDIT_TOOLS else None
        path = (data.get("file_path") or data.get("notebook_path")) if isinstance(data, dict) else None
        if isinstance(path, str) and path:
            yield index, path, data


def _edited_documents(tools):
    """Yield (index, path) for reading documents written or edited in the turn."""
    for index, path, data in edited_paths(tools):
        if not path.lower().endswith(READING_EXT):
            continue
        # Count characters for every tool, so a Korean document is judged the same whether it was
        # written whole or edited: an Edit carries only a fragment, so the file on disk is read.
        if tools[index][0] == "Write":
            size = len(data.get("content", ""))
        else:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    size = len(f.read())
            except (OSError, TypeError):
                size = 0
        if size >= MIN_DOCUMENT_CHARS:
            yield index, path


# A character that could continue a path, so a match must not touch one on either side.
PATH_CHAR = r"[\w.~/-]"


def _path_pattern(path, written):
    """Match the whole path, as written or normalized, or its form relative to the instance root.

    The bare file name is never enough: another folder's file of the same name is not a reread.
    """
    forms = [re.escape(path), re.escape(written)]
    relative = os.path.relpath(path, P.instance_root())
    if relative.split(os.sep)[0] != "..":
        forms.append(r"(?:\./)?" + re.escape(relative))
    return re.compile(rf"(?<!{PATH_CHAR})(?:{'|'.join(forms)})(?!{PATH_CHAR})")


def _strings(value):
    """Yield every string in a decoded tool input, so a newline or tab before a path stays one."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _names_path(raw, pattern):
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    return any(pattern.search(text) for text in _strings(data))


def signal_unopened(message, tools, config):
    send = _send_tools(config)
    last = {}
    for index, path in _edited_documents(tools):
        last[os.path.normpath(path)] = (index, path)
    unopened = []
    for path, (index, written) in last.items():
        base = os.path.basename(path)
        # The whole file name, so data.md does not deliver a.md; a path separator may precede it.
        # Only ASCII word characters are refused after it, because a Korean particle may follow a
        # name directly; a dot then a word character is another file such as name.md.bak.
        named = re.compile(r"(?<![\w.-])" + re.escape(base) + r"(?![A-Za-z0-9_-]|\.\w)")
        later = tools[index + 1:]
        delivered = bool(named.search(message)) or any(_sends(name, send) and named.search(raw)
                                                       for name, raw in later)
        # Any later call that is neither an edit nor a send and names the path counts, because the
        # agent mostly rereads through the shell. Whether that output was read is unknown, and a
        # path the shell builds or escapes (a variable, a glob, a backslash before a space) is not
        # seen, so such a turn still stops once. For a document at the instance root the
        # root-relative path is its file name, so there the name alone counts.
        opened = _path_pattern(path, written)
        reopened = any(not _sends(name, send) and name not in EDIT_TOOLS and _names_path(raw, opened)
                       for name, raw in later)
        if delivered and not reopened:
            unopened.append(base)
    return {"files": sorted(unopened)} if unopened else None


def signal_reader(message, tools, config):
    min_chars = config.get("reader_min_chars", 1200)
    min_tools = config.get("reader_min_tools", 8)
    if len(prose(message)) >= min_chars and len(tools) >= min_tools:
        return {}
    return None


SIGNALS = {"unopened": signal_unopened, "reader": signal_reader}


def evaluate(message, tools, config=None, names=None):
    """Return {signal: detail} for every signal in names (default: blocking and observed) that fires."""
    config = C.deliver() if config is None else config
    if names is None:
        block, observe = modes(config)
        names = block + observe
    fired = {}
    for name in names:
        detail = SIGNALS[name](message or "", tools, config)
        if detail is not None:
            fired[name] = detail
    return fired


def reason(fired, request):
    parts = [HEAD.format(unchanged=UNCHANGED)]
    if "unopened" in fired:
        parts.append(UNOPENED.format(files=", ".join(fired["unopened"]["files"])))
    if "reader" in fired:
        parts.append(READER)
    if request:
        parts.append(f"What the owner asked: \"{request[:600]}\"")
    return "\n".join(parts)


def digest(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def record(row):
    row = dict(row, at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rows():
    rows = []
    try:
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                # One torn line must not hide every other row.
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return [r for r in rows if isinstance(r, dict)]


def _record_followup(session, turn, message):
    """Record once whether the answer changed after this check blocked the same turn.

    This is the check's own effect measure. A re-entered Stop call also happens after another
    Stop hook blocked, or in a turn this check never blocked; those write nothing, and a turn
    that already has its follow-up is not counted again.
    """
    if turn is None:
        return
    rows = [r for r in _rows() if r.get("session") == session and r.get("turn") == turn]
    blocks = [r for r in rows if r.get("event") == "block"]
    if not blocks or any(r.get("event") == "after" for r in rows):
        return
    record({"event": "after", "session": session, "turn": turn,
             "signals": blocks[-1].get("signals", []),
             "changed": _changed(blocks[-1], message), "chars": len(message)})


def _changed(block, message):
    """The reply the block asks for when nothing needs fixing is not a change."""
    unchanged = UNCHANGED.strip(UNCHANGED_STRIP).casefold()
    return block.get("digest") != digest(message) and message.strip(UNCHANGED_STRIP).casefold() != unchanged


def cmd_hook(payload=None):
    """Block once per turn. The check's own failure never blocks: it is advice, not a safety gate."""
    try:
        payload = hook_input.hook_payload() if payload is None else payload
        config = C.deliver()
        block, observe = modes(config)
        # With no signal on there is no block to follow up either, so skip the whole-transcript read.
        if not block and not observe:
            return 0
        message = payload.get("last_assistant_message") or ""
        session = digest(str(payload.get("session_id", "")))[:8]
        request, tools, turn = scan_turn(payload.get("transcript_path"))
        if payload.get("stop_hook_active") is True:
            # The re-entered Stop of a turn: record the follow-up, never block a second time.
            _record_followup(session, turn, message)
            return 0
        fired = evaluate(message, tools, config)
        if not fired:
            return 0
        blocking = {name: detail for name, detail in fired.items() if name in block}
        record({"event": "block" if blocking else "observe", "session": session, "turn": turn,
                 "signals": sorted(blocking) if blocking else sorted(fired),
                 "observed": sorted(set(fired) - set(blocking)),
                 "digest": digest(message), "chars": len(message), "tools": len(tools)})
        if blocking:
            print(json.dumps({"decision": "block", "reason": reason(blocking, request)}, ensure_ascii=False))
        return 0
    except Exception as error:
        _log_error(error)
        return 0


def _log_error(error):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} deliver hook failed: {type(error).__name__}: {error}"
    # tools/hook.sh sends stderr to the hook error log, so the line is written there once.
    print(line, file=sys.stderr)


def cmd_check(argv):
    """Evaluate a message file by hand with every signal enabled; print what would fire."""
    def arg(flag):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
    if not arg("--message"):
        print("usage: deliver.py check --message FILE [--request FILE] [--transcript FILE]", file=sys.stderr)
        return 2
    message = open(arg("--message"), encoding="utf-8").read()
    request = open(arg("--request"), encoding="utf-8").read() if arg("--request") else ""
    tools = scan_turn(arg("--transcript"))[1] if arg("--transcript") else []
    fired = evaluate(message, tools, names=ALL_SIGNALS)
    print(reason(fired, request) if fired else "no signal fired")
    return 0


def cmd_stats():
    """Print how often each signal blocked and how often the answer changed afterwards.

    "Changed" means the final answer's text differs from the blocked one, except that the reply the
    block asks for when nothing needs fixing ("checked: unchanged") counts
    as unchanged; it does not say whether the change was an improvement.
    """
    rows = _rows()
    blocks = [r for r in rows if r.get("event") == "block"]
    after = [r for r in rows if r.get("event") == "after"]
    watched = [r for r in rows if r.get("event") in ("observe", "block")]
    changed = sum(1 for r in after if r.get("changed"))
    print(f"blocked turns: {len(blocks)}; seen again: {len(after)}; answer changed: {changed}")
    for name in ALL_SIGNALS:
        fired = sum(1 for r in blocks if name in r.get("signals", []))
        changed = sum(1 for r in after if name in r.get("signals", []) and r.get("changed"))
        seen = sum(1 for r in after if name in r.get("signals", []))
        observed = sum(1 for r in watched if name in r.get("observed", [])
                       or (r.get("event") == "observe" and name in r.get("signals", [])))
        print(f"  {name:<9} recorded only {observed} · blocked {fired} · seen again {seen} · changed {changed}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else ""
    if command in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if command == "hook":
        return cmd_hook()
    if command == "check":
        return cmd_check(argv[1:])
    if command == "stats":
        return cmd_stats()
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
