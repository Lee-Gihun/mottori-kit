#!/usr/bin/env python3
"""Check a finished turn once before it reaches the owner.

Stop hook. Read the hook JSON on stdin, look at the last assistant message and the tool calls of
the turn, and evaluate cheap deterministic signals. No model is called.

Each signal runs in one of two modes set in the instance config (`deliver.block`, `deliver.observe`).
An observed signal is only recorded, so its hit rate can be judged before it is trusted. A blocking
signal stops the turn once: the reason names only the signals that fired and quotes the owner's
request, so the agent rereads its own output as the recipient. A second Stop call in the same turn
always passes. Unless the config says otherwise, `unopened` is observed and nothing blocks.

Signals:
  unopened  a reading document written this turn is delivered without being reopened
  reader    a long report at the end of a long working turn (off unless configured)

`deliver.send_tools` lists the tool names that count as delivering a file to the owner. Shell-style
wildcards are allowed, so a document connector can be listed once.

Signals that judge wording alone (asking the owner to do something, claiming that a check passed)
are deliberately absent: wording cannot tell whether such a sentence is legitimate. The decision
record KIT-DR-020 holds the measurements behind this choice.

Commands: hook (Stop hook), check --message FILE [--request FILE] (manual), stats.
"""
import datetime
import fnmatch
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M
from i18n import t

LOG = os.path.join(M.STATE, ".deliver.jsonl")
ERRORS = os.path.join(M.STATE, ".hook-errors.log")
ALL_SIGNALS = ("unopened", "reader")
DEFAULT_OBSERVE = ("unopened",)
EDIT_TOOLS = ("Write", "Edit", "NotebookEdit")
SEND_TOOLS = ("SendUserFile", "Artifact")
READING_EXT = (".md", ".html", ".htm", ".txt", ".pdf", ".docx", ".pptx")
# A document shorter than this is cheap to check in the message itself.
MIN_DOCUMENT_CHARS = 1500
FENCE = re.compile(r"```.*?```", re.S)


def _config():
    """Return the optional `deliver` block of the instance config; a broken config means defaults."""
    try:
        with open(M.CONFIG_PATH, encoding="utf-8") as f:
            block = json.load(f).get("deliver", {})
        return block if isinstance(block, dict) else {}
    except (OSError, ValueError):
        return {}


def modes(config=None):
    """Return (blocking signals, observed signals). Blocking wins when a signal is listed twice."""
    config = _config() if config is None else config
    block = config.get("block", ())
    observe = config.get("observe", DEFAULT_OBSERVE)
    block = tuple(s for s in ALL_SIGNALS if isinstance(block, (list, tuple)) and s in block)
    observe = tuple(s for s in ALL_SIGNALS
                    if isinstance(observe, (list, tuple)) and s in observe and s not in block)
    return block, observe


def prose(text):
    """Drop fenced code and quoted lines; signals read what the agent says, not what it shows."""
    text = FENCE.sub("", text or "")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def read_turn(transcript_path):
    """Return (owner request, tool calls) for the turn after the last owner message.

    A tool call is (name, serialized input). An unreadable or unknown transcript yields an empty
    turn, which leaves only the message-based signals active.
    """
    request, tools, _turn = scan_turn(transcript_path)
    return request, tools


def scan_turn(transcript_path):
    """Return (owner request, tool calls, turn key) for the turn after the last owner message.

    The turn key names that turn within its transcript: the owner message's position among the
    owner messages, then a digest of its text. A re-entered Stop call of the same turn sees the
    same key; a later turn sees a different position even when its request repeats the text.
    The key is None when the transcript has no owner message.
    """
    request, tools, ordinal = "", [], 0
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, TypeError):
        return request, tools, None
    for raw in lines:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) else None
        if not isinstance(message, dict):
            continue
        role, content = message.get("role"), message.get("content")
        if role == "user":
            if row.get("isMeta"):
                continue
            if isinstance(content, str):
                text, tool_result = content, False
            elif isinstance(content, list):
                tool_result = any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
                text = "\n".join(c.get("text", "") for c in content
                                 if isinstance(c, dict) and c.get("type") == "text")
            else:
                continue
            if tool_result or not text.strip():
                continue
            request, tools, ordinal = text.strip(), [], ordinal + 1
        elif role == "assistant" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tools.append((c.get("name", ""), json.dumps(c.get("input", {}), ensure_ascii=False)))
    return request, tools, (f"{ordinal}:{_digest(request)}" if ordinal else None)


def _send_tools(config):
    """Return the tool-name patterns that count as delivering a file to the owner."""
    names = config.get("send_tools")
    if isinstance(names, (list, tuple)) and all(isinstance(n, str) for n in names):
        return tuple(names)
    return SEND_TOOLS


def _sends(name, patterns):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _edited_documents(tools):
    """Yield (index, path) for reading documents written or edited in the turn."""
    for index, (name, raw) in enumerate(tools):
        if name not in EDIT_TOOLS:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        path = data.get("file_path") or data.get("notebook_path") or ""
        if not path.lower().endswith(READING_EXT):
            continue
        # Count characters for every tool, so a Korean document is judged the same whether it was
        # written whole or edited: an Edit carries only a fragment, so the file on disk is read.
        if name == "Write":
            size = len(data.get("content", ""))
        else:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    size = len(f.read())
            except (OSError, TypeError):
                size = 0
        if size >= MIN_DOCUMENT_CHARS:
            yield index, path


def signal_unopened(message, tools, config):
    send = _send_tools(config)
    last = {}
    for index, path in _edited_documents(tools):
        last[path] = index
    unopened = []
    for path, index in last.items():
        base = os.path.basename(path)
        later = tools[index + 1:]
        delivered = base in message or any(_sends(name, send) and base in raw for name, raw in later)
        reopened = any(not _sends(name, send) and name not in EDIT_TOOLS and base in raw for name, raw in later)
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


def evaluate(message, request, tools, config=None, names=None):
    """Return {signal: detail} for every signal in names (default: blocking and observed) that fires."""
    config = _config() if config is None else config
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
    parts = [t("deliver.head")]
    if "unopened" in fired:
        parts.append(t("deliver.unopened", files=", ".join(fired["unopened"]["files"])))
    if "reader" in fired:
        parts.append(t("deliver.reader"))
    if request:
        parts.append(t("deliver.request", request=request[:600]))
    return "\n".join(parts)


def _digest(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _record(row):
    row = dict(row, at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rows():
    try:
        with open(LOG, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []


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
    _record({"event": "after", "session": session, "turn": turn,
             "signals": blocks[-1].get("signals", []),
             "changed": blocks[-1].get("digest") != _digest(message), "chars": len(message)})


def cmd_hook():
    """Block once per turn. The check's own failure never blocks: it is advice, not a safety gate."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        message = payload.get("last_assistant_message") or ""
        session = _digest(str(payload.get("session_id", "")))[:8]
        request, tools, turn = scan_turn(payload.get("transcript_path"))
        if payload.get("stop_hook_active") is True:
            _record_followup(session, turn, message)
            return 0
        config = _config()
        block, _observe = modes(config)
        fired = evaluate(message, request, tools, config)
        if not fired:
            return 0
        blocking = {name: detail for name, detail in fired.items() if name in block}
        _record({"event": "block" if blocking else "observe", "session": session, "turn": turn,
                 "signals": sorted(blocking) if blocking else sorted(fired),
                 "observed": sorted(set(fired) - set(blocking)),
                 "digest": _digest(message), "chars": len(message), "tools": len(tools)})
        if blocking:
            print(json.dumps({"decision": "block", "reason": reason(blocking, request)}, ensure_ascii=False))
        return 0
    except Exception as error:
        line = f"{datetime.datetime.now().isoformat(timespec='seconds')} deliver hook failed: {type(error).__name__}: {error}"
        print(line, file=sys.stderr)
        try:
            os.makedirs(os.path.dirname(ERRORS), exist_ok=True)
            with open(ERRORS, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        return 0


def cmd_check(argv):
    """Evaluate a message file by hand with every signal enabled; print what would fire."""
    def arg(flag):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
    if not arg("--message"):
        print("usage: deliver.py check --message FILE [--request FILE] [--transcript FILE]", file=sys.stderr)
        return 2
    message = open(arg("--message"), encoding="utf-8").read()
    request = open(arg("--request"), encoding="utf-8").read() if arg("--request") else ""
    tools = read_turn(arg("--transcript"))[1] if arg("--transcript") else []
    fired = evaluate(message, request, tools, names=ALL_SIGNALS)
    print(reason(fired, request) if fired else t("deliver.none"))
    return 0


def cmd_stats():
    """Print how often each signal blocked and how often the answer changed afterwards.

    "Changed" means the final answer's text differs from the blocked one; it does not say whether
    the change was an improvement.
    """
    rows = _rows()
    blocks = [r for r in rows if r.get("event") == "block"]
    after = [r for r in rows if r.get("event") == "after"]
    watched = [r for r in rows if r.get("event") in ("observe", "block")]
    print(t("deliver.stats_head", blocks=len(blocks), after=len(after),
            changed=sum(1 for r in after if r.get("changed"))))
    for name in ALL_SIGNALS:
        fired = sum(1 for r in blocks if name in r.get("signals", []))
        changed = sum(1 for r in after if name in r.get("signals", []) and r.get("changed"))
        seen = sum(1 for r in after if name in r.get("signals", []))
        observed = sum(1 for r in watched if name in r.get("observed", [])
                       or (r.get("event") == "observe" and name in r.get("signals", [])))
        print(f"  {name:<9} {t('deliver.stats_row', observed=observed, fired=fired, seen=seen, changed=changed)}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else ""
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
