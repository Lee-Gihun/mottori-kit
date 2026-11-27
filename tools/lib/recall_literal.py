#!/usr/bin/env python3
"""The literal search: the transcript messages that match a pattern, ranked and printed.

The pattern is a regular expression, or its literal text when it is not valid regex syntax. find
reads the messages once through transcripts.py, keeps the best hits with the messages around them
in the same file, and prints them in a compact form capped at COMPACT_MAX_BYTES, in full, or as
JSON, with notices of what was not searched. recall.py calls it for every search that the store of
the owner's words does not answer.
"""
import collections
import heapq
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import transcripts as T

# Messages this module prints in more than one place, or too long to read inline.
MORE = (
    "[{hidden} more of {total} matches not shown. Full output: --full · narrow: --max, --role, "
    "--since, --source]"
)
SCOPE_AGY_UNSCOPED = (
    "; {count} Antigravity transcript(s) not searched because the index does not place them "
    "(`--source agy --all-instances` reads them)"
)
UNSCANNED = (
    "Session files not searched within the {seconds}-second limit: {count}. To search them "
    "all, add --scan-all."
)
ZERO_HITS = (
    "No match for /{pattern}/ in the searched scope: {scope}. This does not mean the original "
    "is absent. Try other words or another form of the word."
)

# The default find output goes straight into an agent's context, so it is a fixed cost of every
# lookup: a common word prints about 18KB in full. Compact output keeps each hit's locator and a
# short excerpt and stops at this many bytes; --full prints every selected hit whole.
COMPACT_MAX_BYTES = 4000
# About two to three terminal lines of excerpt per hit.
COMPACT_SNIPPET_CHARS = 180
COMPACT_NEARBY_CHARS = 120
# In the capped default form a zero-hit notice repeats the query only up to this many bytes,
# so a pasted paragraph cannot push the notice past COMPACT_MAX_BYTES.
NOTICE_QUERY_MAX_BYTES = 200
# Any other notice line in the capped form is cut at this many bytes.
NOTICE_LINE_MAX_BYTES = 600


def _time_rank(ts):
    """Sort key that orders stamps by instant, not by text, and puts unparseable ones first.

    Ranks are sorted highest first, so first here means last in the output. Text order breaks
    across zones: 00:30 at +09:00 on New Year sorts after 16:30Z the evening before."""
    value = T.instant(ts)
    return (1, value.timestamp()) if value else (0, 0.0)


def _local_date(ts):
    """Return the stamp's local calendar date (YYYY-MM-DD), or None when it does not parse.

    --since names the date the listings show, which is local time, not the UTC prefix."""
    value = T.instant(ts)
    return value.astimezone().date().isoformat() if value else None


# ------------------------------------------------------------------ matching


def _compile_query(pattern):
    """Compile a query as a regex, or as literal text when it is not valid regex syntax.

    People type things like C++ or a(b without meaning a regex; failing with a traceback
    hides the search instead of answering it. Returns (regex, branches, error_or_None).
    """
    try:
        return re.compile(pattern, re.I), _branches(pattern), None
    except re.error as exc:
        return re.compile(re.escape(pattern), re.I), [], str(exc)


def _branches(pattern):
    """Split top-level OR branches, returning an empty list when none exist."""
    if "|" not in pattern:
        return []
    depth, parts, cur = 0, [], ""
    for ch in pattern:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    try:
        return [re.compile(x, re.I) for x in parts if x.strip()]
    except re.error:
        return []


def _score(text, branches, rx):
    """Score lexical matches by matched OR branches, then total occurrences.

    The score is not normalized by length: a long discussion can be the message looked for."""
    if not branches:
        return (1, len(rx.findall(text)))
    matched = sum(1 for b in branches if b.search(text))
    total = sum(len(b.findall(text)) for b in branches)
    return (matched, total)


def _snip(text, rx, width=260):
    m = rx.search(text)
    if not m:
        return text[:width].replace("\n", " ")
    a = max(0, m.start() - width // 2)
    s = text[a:a + width].replace("\n", " ")
    return ("…" if a else "") + s + ("…" if a + width < len(text) else "")


def _eligible(message, role=None, since=None):
    """Return True or False, or None for a --since search that cannot place the stamp.

    None is left out like False and counted by the caller: a stamp that cannot be placed may as
    well be years before the date asked for, and keeping it silently filled results with it."""
    if role is not None and message["role"] != role:
        return False
    if not since:
        return True
    day = _local_date(message["timestamp"])
    return None if day is None else day >= since


def _rank(order, score, stamp, position):
    if order == "score":
        return (score, stamp, position)
    if order == "recent":
        return (stamp, score, position)
    return (position,)


def _search(rx, branches, role, since, around, max_hits, order, scan, reading):
    """Read the messages once and keep the max_hits best matches, each with up to `around`
    messages before and after it from the same file.

    Keeps at most max_hits candidates and a ring of `around` messages, so memory does not grow
    with the history. Returns (hits best first, matches counted, messages read)."""
    best, ring, pending = [], collections.deque(maxlen=around), []
    previous_path = None
    # Files may arrive newest first, so the file count orders ties between files as the oldest
    # first reading order does: an older file and an earlier line rank first.
    newest_first = reading["scan_seconds"] is not None and order != "oldest"
    files_seen = messages_read = matched = 0
    for ordinal, message in enumerate(T.iter_messages(
            oldest_first=order == "oldest", scan=scan, **reading)):
        messages_read += 1
        if message["path"] != previous_path:
            ring.clear()
            pending = []
            previous_path = message["path"]
            files_seen += 1
        position = (files_seen if newest_first else -files_seen, -ordinal)
        for candidate in pending:
            candidate["after"].append(message)
        pending = [c for c in pending if len(c["after"]) < around]
        text = message["text"]
        eligible = _eligible(message, role, since)
        if eligible is None and rx.search(text):
            scan["malformed"] = scan.get("malformed", 0) + 1
        elif eligible and rx.search(text):
            matched += 1
            score = _score(text, branches, rx)
            rank = _rank(order, score, _time_rank(message["timestamp"]), position)
            candidate = {**message, "score": score, "snippet": _snip(text, rx),
                         "before": list(ring), "after": []}
            item = (rank, ordinal, candidate)
            kept = len(best) < max_hits or rank > best[0][0]
            if len(best) < max_hits:
                heapq.heappush(best, item)
            elif kept:
                heapq.heapreplace(best, item)
            if kept and around:
                pending.append(candidate)
        ring.append(message)
    hits = [item[2] for item in sorted(best, key=lambda item: item[0], reverse=True)]
    return hits, matched, messages_read


# ------------------------------------------------------------------ the literal search


def find(pattern, role=None, since=None, around=2, max_hits=8, thinking=False, sources=None,
         include_agents=False, include_system=False, all_instances=False,
         order="score", json_output=False, full=True, capped=False, scan_seconds=None):
    """Search the transcripts for a pattern and print the best hits with their exact locators.

    full=False prints the compact form, whose hits stop at COMPACT_MAX_BYTES. capped=True
    (the CLI default form) also counts notices and the zero-hit message toward that cap.
    scan_seconds bounds the search time (newest files first, oldest first for order="oldest");
    None reads every file. Returns the exit code.
    """
    if max_hits < 1 or around < 0:
        raise ValueError("max_hits must be positive and around must be nonnegative")
    capped = capped and not full and not json_output
    rx, branches, regex_error = _compile_query(pattern)
    scan = {"unread": 0}
    reading = {"sources": sources, "all_instances": all_instances, "thinking": thinking,
               "include_agents": include_agents, "include_system": include_system,
               "scan_seconds": scan_seconds}
    selected, matched, messages_read = _search(rx, branches, role, since, around, max_hits,
                                               order, scan, reading)
    # Printed after the search because the one source selection happens inside it; hits are
    # printed after the search as well, so the notices still come first.
    notices = _notices(regex_error, sources, scan, selected)
    if capped:
        notices = [_clip_bytes(line, NOTICE_LINE_MAX_BYTES) for line in notices]
    # Notices go to stderr under --json so the structured stdout stays parseable.
    for line in notices:
        print(line, file=sys.stderr if json_output else sys.stdout)
    budget = COMPACT_MAX_BYTES - sum(_nbytes(line) + 1 for line in notices)
    trailer = _trailer(scan, scan_seconds)
    if trailer:
        # The trailer is printed after the hits, so its room is kept out of the hit budget.
        budget -= _nbytes(trailer) + 1
    if json_output:
        print(json.dumps(selected, ensure_ascii=False))
        if trailer:
            print(trailer, file=sys.stderr)
        return 0
    if not full and selected:
        _print_compact(selected, rx, matched, budget if capped else COMPACT_MAX_BYTES, capped)
    elif selected:
        _print_full(selected)
    else:
        _print_zero_hits(pattern, role, since, sources, scan, messages_read,
                         budget if capped else None)
    if trailer:
        print(trailer)
    return 0


def _notices(regex_error, sources, scan, selected):
    """The lines printed before the hits: what was not searched, or searched without proof."""
    notices = []
    if regex_error:
        notices.append(f"Not a valid regular expression ({regex_error}); searched for the literal text instead.")
    missing = T.missing_claude_store(sources)
    if missing:
        notices.append(T.NO_TRANSCRIPTS.format(path=missing))
    if scan.get("skipped"):
        notices.append(T.ZST_SKIPPED.format(count=scan["skipped"]))
    if T.unreadable_count():
        notices.append(T.ZST_UNREADABLE.format(count=T.unreadable_count()))
    # A miss may be in those files and a hit may come from them; a hit from checked files is not
    # in doubt, and repeating the line on every search would teach the reader to skip it.
    if scan.get("unverified") and (not selected or any(
            T.file_unverified(m["path"]) for m in selected)):
        notices.append(T.UNVERIFIED_FILES.format(count=scan["unverified"]))
    if T.unscoped_count() and selected:
        notices.append(T.AGY_UNSCOPED.format(count=T.unscoped_count()))
    if C.meaning_off_hint():
        # The word search says the list by meaning is off too (KIT-DR-094).
        notices.append(C.meaning_off_hint()[0].upper() + C.meaning_off_hint()[1:] + ".")
    return notices


def _trailer(scan, scan_seconds):
    """The lines printed after the hits (malformed records, files the time limit left), or None."""
    trailer = (UNSCANNED.format(count=scan["unread"], seconds=scan_seconds)
               if scan["unread"] else None)
    if scan.get("malformed"):
        trailer = "\n".join(filter(None, (
            T.MALFORMED_SKIPPED.format(count=scan["malformed"]), trailer)))
    return trailer


def _print_full(selected):
    """Print every hit with its full path, record id and neighbours (--full)."""
    for hit, message in enumerate(selected, 1):
        print(f"■ hit {hit} · " + f"[{message['source']}] {message['path']}:{message['line']}"
              f" · {T.local_time(message['timestamp'])} · {message['role']}"
              f"{_origin_label(message['origin'])}")
        print(f"  id:{message['record_id']}")
        for nearby in message["before"]:
            print(T.nearby_line(nearby, nearby["text"][:200].strip().replace("\n", " ")))
        print(f"  ▶ {message['snippet']}")
        for nearby in message["after"]:
            print(T.nearby_line(nearby, nearby["text"][:200].strip().replace("\n", " ")))
        print()


def _print_zero_hits(pattern, role, since, sources, scan, messages_read, budget):
    """Say that nothing matched and what was actually searched; budget caps it in the capped
    form, None prints it whole.

    An empty answer is only as wide as its scope, and the scope is the files actually read:
    subagent sessions, unreadable files and files the time limit left out are not part of it."""
    names = sorted({name for name, _k, _b, _p in C.episodic_sources()
                    if not sources or name in sources})
    filters = " ".join(f"--{k}={v}" for k, v in (("role", role), ("since", since)) if v)
    scope = "{files} file(s) from {sources}, {messages} message(s) read{filters}".format(files=scan.get("read", 0), sources=", ".join(names) or "-", messages=messages_read, filters=f" ({filters})" if filters else "")
    if T.unscoped_count():
        scope += SCOPE_AGY_UNSCOPED.format(count=T.unscoped_count())
    capped = budget is not None
    shown_pattern = _clip_bytes(pattern, NOTICE_QUERY_MAX_BYTES) if capped else pattern
    text = ZERO_HITS.format(pattern=shown_pattern, scope=scope) + "\n"
    if capped:
        text = _clip_bytes(text, budget)
    sys.stdout.write(text)


def _nbytes(text):
    return len(text.encode("utf-8"))


def _clip_bytes(text, max_bytes):
    """Cut text to max_bytes at a UTF-8 boundary, marking a cut with an ellipsis."""
    if _nbytes(text) <= max_bytes:
        return text
    marker = "…"
    room = max(0, max_bytes - _nbytes(marker) - (1 if text.endswith("\n") else 0))
    clipped = text.encode("utf-8")[:room].decode("utf-8", "ignore") + marker
    return clipped + ("\n" if text.endswith("\n") else "")


def _origin_label(origin):
    if origin == "system":
        return " [injected]"
    if origin == "summary":
        return " [summary]"
    return " [agent]" if origin == "agent" else ""


def _compact_block(hit, message, rx):
    lines = [f"■ {hit} · [{message['source']}] {os.path.basename(message['path'])}:{message['line']}"
             f" · {T.local_time(message['timestamp'])} · {message['role']}"
             f"{_origin_label(message['origin'])}"]
    for nearby in message["before"]:
        lines.append(T.nearby_line(nearby, _compact_excerpt(nearby), clock=False))
    lines.append(f"  ▶ {_snip(message['text'], rx, COMPACT_SNIPPET_CHARS)}")
    for nearby in message["after"]:
        lines.append(T.nearby_line(nearby, _compact_excerpt(nearby), clock=False))
    return "\n".join(lines) + "\n"


def _compact_excerpt(message):
    return message["text"][:COMPACT_NEARBY_CHARS].strip().replace("\n", " ")


def _print_compact(selected, rx, matched, budget=COMPACT_MAX_BYTES, clip_first=False):
    """Print hits until budget bytes, then one line naming what was left out and how to get it.

    A cut that does not say how to recover the rest leaves the reader guessing; naming the
    narrowing flags lets the next call ask for less instead of more. The first hit is always
    printed; clip_first cuts it to the budget instead of letting it run over.
    """
    trailer_room = len(MORE.format(hidden=10 ** 6, total=10 ** 6).encode("utf-8")) + 1
    used, shown = 0, 0
    for hit, message in enumerate(selected, 1):
        block = _compact_block(hit, message, rx)
        if not shown and clip_first:
            block = _clip_bytes(block, budget - trailer_room)
        size = len(block.encode("utf-8"))
        if shown and used + size + trailer_room > budget:
            break
        sys.stdout.write(block)
        used += size
        shown += 1
    if matched > shown:
        print(MORE.format(hidden=matched - shown, total=matched))
