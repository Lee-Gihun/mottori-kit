#!/usr/bin/env python3
"""Search episodic transcript records for targeted recall.

  recall.py find PATTERN [--source all|claude|codex|dumps] [--role user|assistant]
      [--since YYYY-MM-DD] [--around N] [--max 8] [--thinking] [--full]
  recall.py sessions [--max 40 | --all]

memlib.EPISODIC_SOURCES is the source registry. Dump results are for in-session reading only, not quotation in deliverables or commits. Use original utterances for attribution. Keep queries scoped to the current question; record scope and actual coverage for a requested exhaustive review. Summarize relevant evidence instead of flooding context with entire result sets."""
import argparse
import collections
import datetime
import hashlib
import heapq
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M
from i18n import STRINGS, t

# The default find output goes straight into an agent's context, so it is a fixed cost of every
# lookup: a common word used to print about 18KB. Compact output keeps each hit's locator and a
# short excerpt and stops at this many bytes; --full restores the previous unbounded form.
COMPACT_MAX_BYTES = 4000
# About two to three terminal lines of excerpt per hit.
COMPACT_SNIPPET_CHARS = 180
COMPACT_NEARBY_CHARS = 120
# In the capped default form a zero-hit notice repeats the query only up to this many bytes,
# so a pasted paragraph cannot push the notice past COMPACT_MAX_BYTES.
NOTICE_QUERY_MAX_BYTES = 200
# Any other notice line in the capped form is cut at this many bytes.
NOTICE_LINE_MAX_BYTES = 600
FULL_AROUND_DEFAULT = 2


def _local_time(ts):
    """Display the full source timestamp in the machine's local timezone."""
    if not ts:
        return ts
    try:
        value = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone().strftime("%m-%d %H:%M %Z")
    except (ValueError, TypeError):
        return ts


import glob as _glob


_CWD_CACHE = {}


def _codex_cwd(fp):
    """Read the rollout working directory from the first session_meta payload."""
    if fp in _CWD_CACHE:
        return _CWD_CACHE[fp]
    cwd = None
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            d = json.loads(f.readline())
        cwd = (d.get("payload") or {}).get("cwd")
    except Exception:
        pass
    _CWD_CACHE[fp] = cwd
    return cwd


def _same_instance(cwd):
    """Accept only absolute working directories inside this instance or a configured root alias. Unknown identity fails closed unless all-instances access was explicitly requested."""
    if not cwd or not os.path.isabs(cwd):
        return False
    # Configured root aliases preserve retrieval after an instance rename; unrelated roots remain excluded.
    roots = [M.ROOT] + list((getattr(M, "ROOT_ALIASES", None) or []))
    for base in roots:
        try:
            real = os.path.realpath(cwd)
            root = os.path.realpath(base)
            if real == root or os.path.commonpath([real, root]) == root:
                return True
        except ValueError:      # Different filesystem drives may not have a common path.
            continue
    return False


# Claude names a project's transcript folder by replacing every character outside ASCII letters,
# digits and hyphens, so different folders (two Hangul names, "a_b" and "a-b") share one store.
# Each Claude record line carries the working folder it was written in; that field, not the
# store name, decides whether a record belongs to this instance.
_CLAUDE_FILE_CACHE = {}


def _claude_line_cwd(line):
    """Return the top-level working folder of one raw Claude record line, or None.

    Lines without the key are skipped before parsing; a "cwd" nested inside message content
    is not the record's own folder and is ignored.
    """
    if '"cwd"' not in line:
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    value = record.get("cwd") if isinstance(record, dict) else None
    return value if isinstance(value, str) and value else None


def _claude_file_owner(fp):
    """Classify a Claude transcript file as "own", "foreign" or "unverified".

    own: some line names a working folder inside this instance or a declared root alias.
    foreign: lines name working folders, none of them this instance's.
    unverified: no line names a working folder (an older record form); kept, but counted.
    """
    if fp in _CLAUDE_FILE_CACHE:
        return _CLAUDE_FILE_CACHE[fp]
    seen_cwd, owner = False, "unverified"
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            for line in f:
                cwd = _claude_line_cwd(line)
                if cwd is None:
                    continue
                seen_cwd = True
                if _same_instance(cwd):
                    owner = "own"
                    break
    except OSError:
        pass
    if owner != "own" and seen_cwd:
        owner = "foreign"
    _CLAUDE_FILE_CACHE[fp] = owner
    return owner


def _instance_claude_base(kind, base):
    return kind == "claude-jsonl" and os.path.realpath(base) == os.path.realpath(M.TRANSCRIPTS)


def _select_sources(names, all_instances=False):
    """Return ([(name, kind, path, owner_checked)], unverified_claude_file_count).

    Codex storage is machine-wide, so it is filtered by the rollout's working folder. The
    instance's Claude store is filtered by the working folders its records name, because the
    store name alone can be shared with another folder. Both filters are skipped only when
    all-instances access was explicitly requested. owner_checked marks the Claude files whose
    lines iter_messages must still match to this instance session by session.
    """
    out, seen = [], set()
    unverified = 0
    for name, kind, base, pat in M.EPISODIC_SOURCES:
        if names and name not in names:
            continue
        bases = [base]
        instance_claude = _instance_claude_base(kind, base)
        # Only expand the configured instance transcript family, never an unrelated custom source.
        if instance_claude:
            bases += [M.transcript_dir(alias) for alias in M.ROOT_ALIASES]
        fs = []
        for candidate in bases:
            if os.path.isdir(candidate):
                fs.extend(_glob.glob(os.path.join(candidate, pat), recursive=True))
        fs.sort(key=lambda p: (os.path.getmtime(p), p))
        if kind == "codex-jsonl" and not all_instances:
            fs = [f for f in fs if _same_instance(_codex_cwd(f))]
        for f in fs:
            identity = (kind, os.path.realpath(f))
            if identity in seen:
                continue
            seen.add(identity)
            owner = (_claude_file_owner(f) if instance_claude and not all_instances
                     else None)
            if owner == "foreign":
                continue
            if owner == "unverified":
                unverified += 1
            out.append((name, kind, f, owner == "own"))
    return out, unverified


def _source_files(names, all_instances=False):
    """Return the selected source files as (name, kind, path); see _select_sources."""
    return [(name, kind, f) for name, kind, f, _checked in _select_sources(names, all_instances)[0]]


def _missing_claude_store(names):
    """Return this instance's Claude transcript path when it is selected but absent everywhere.

    The caller says so instead of letting an empty result look like a searched-but-empty store.
    """
    if names and "claude" not in names:
        return None
    for name, kind, base, _pat in M.EPISODIC_SOURCES:
        if kind != "claude-jsonl" or (names and name not in names):
            continue
        if os.path.realpath(base) != os.path.realpath(M.TRANSCRIPTS):
            continue
        bases = [base] + [M.transcript_dir(alias) for alias in M.ROOT_ALIASES]
        if not any(os.path.isdir(b) for b in bases):
            return base
    return None


def _compile_query(pattern):
    """Compile a query as a regex, or as literal text when it is not valid regex syntax.

    People type things like C++ or a(b without meaning a regex; failing with a traceback
    hides the search instead of answering it. Returns (regex, branches, error_or_None).
    """
    try:
        return re.compile(pattern, re.I), _branches(pattern), None
    except re.error as exc:
        return re.compile(re.escape(pattern), re.I), [], str(exc)


# A user role does not establish a human utterance. Exclude injected environment, plugin, policy,
# and command wrappers by content patterns. Exclude copied parent histories using session_meta:
# subagent copies duplicate utterances and may replace their timestamps with spawn time.
_SYS_INJECT = re.compile(
    r"^\s*<(recommended_plugins|environment_context|codex_internal_context|app-context|in-app-browser-context"
    r"|system-reminder|command-name|command-message|command-args|local-command"
    r"|user_instructions|task-notification)\b"
    r"|^\s*#\s*AGENTS\.md instructions"
    r"|^\s*You are an agent in a team of agents"
    r"|^\s*Base directory for this skill:"
    r"|^\s*## Page contract — read before your first publish",
    re.I)


def _is_system_injected(text):
    return bool(_SYS_INJECT.search(text or ""))


# Openers of agent hand-off messages. The dispatch prefix is written by the kit in the instance
# language, so both catalog forms are recognised. The escaped Korean alternatives are worker
# prompt openers in Korean transcripts: "Claude-da." ("[This is] Claude.") and
# "neoneun Codex/Kodekseu/Claude-da." ("You are Codex/Claude.").
_DISPATCH_PREFIXES = "|".join(re.escape(form.rstrip())
                              for form in STRINGS["codex_root.dispatch_prefix"].values())
_AGENT_TRANSPORT = re.compile(
    r"^\s*(?:Another Claude session sent a message:|" + _DISPATCH_PREFIXES + r"|FRESH_WORKER\b"
    r"|Claude\ub2e4[.。]|\ub108\ub294 (?:Codex|\ucf54\ub371\uc2a4|Claude)\ub2e4[.。])", re.I)
_USER_ENVELOPE = re.compile(
    r"^\s*<(in-app-browser-context|environment_context|app-context|recommended_plugins)\b"
    r"[^>]*>.*?</\1>\s*", re.S)


def _unwrap_user(text):
    """Remove known ambient envelopes while retaining a request following them.

    A pure injected block is returned intact so --include-system can inspect it.
    Arbitrary XML written by the user is not discarded.
    """
    original = text
    while True:
        stripped, n = _USER_ENVELOPE.subn("", text, count=1)
        if not n:
            break
        text = stripped
    if text != original:
        text = re.sub(r"^\s*## My request:\s*", "", text)
    return text if text.strip() else original


_META_CACHE = {}


def _file_identity(fp):
    """Return (kind, parent_id, boundary) from session metadata.

    Recognize explicit subagent markers. A paginated history may include a one-based parent-history boundary; legacy records may omit it."""
    if fp in _META_CACHE:
        return _META_CACHE[fp]
    ident = ("unknown", None, None)
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            first = json.loads(f.readline())
        if first.get("type") == "session_meta":
            p = first.get("payload") or {}
            src = p.get("source") if isinstance(p.get("source"), dict) else {}
            is_sub = p.get("thread_source") == "subagent" or "subagent" in src
            ident = ("subagent" if is_sub else "user",
                     p.get("parent_thread_id"),
                     p.get("subagent_history_start_ordinal"))
    except Exception:
        pass
    _META_CACHE[fp] = ident
    return ident


def _text_of_codex(d):
    """Extract (role, text, timestamp) from a Codex response_item message."""
    if d.get("type") != "response_item":
        return None
    p = d.get("payload") or {}
    if p.get("type") != "message" or p.get("role") not in ("user", "assistant"):
        return None
    parts = [b.get("text") or "" for b in (p.get("content") or [])
             if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")]
    text = "\n".join(x for x in parts if x)
    if p["role"] == "user":
        text = _unwrap_user(text)
    return (p["role"], text, (d.get("timestamp") or "")[:16]) if text else None


def _text_of(d, include_thinking=False):
    """Extract searchable user or assistant text, or return None."""
    t = d.get("type")
    if t not in ("user", "assistant"):
        return None
    m = d.get("message") or {}
    c = m.get("content")
    if t == "user":
        if isinstance(c, str):
            return ("user", _unwrap_user(c))
        if isinstance(c, list):  # Exclude tool results from default message retrieval.
            parts = [b.get("text") or b.get("content") for b in c if isinstance(b, dict)
                     and b.get("type") == "text"]
            joined = " ".join(p for p in parts if isinstance(p, str))
            return ("user", _unwrap_user(joined)) if joined else None
        return None
    parts = []
    if isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(b.get("text") or "")
            elif include_thinking and b.get("type") == "thinking":
                parts.append(b.get("thinking") or "")
    return ("assistant", "\n".join(p for p in parts if p)) if parts else None


def _snip(text, rx, width=260):
    m = rx.search(text)
    if not m:
        return text[:width].replace("\n", " ")
    a = max(0, m.start() - width // 2)
    s = text[a:a + width].replace("\n", " ")
    return ("…" if a else "") + s + ("…" if a + width < len(text) else "")


def _score(text, branches, rx):
    """Score lexical matches by matched OR branches, then total occurrences. Do not normalize by length: longer discussions can be useful retrieval targets."""
    if not branches:
        return (1, len(rx.findall(text)))
    matched = sum(1 for b in branches if b.search(text))
    total = sum(len(b.findall(text)) for b in branches)
    return (matched, total)


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


def iter_messages(sources=None, *, all_instances=False, include_agents=False,
                  include_system=False, thinking=False, paths=None):
    """Shared local transcript reader for recall, garden, and channel sync.

    Eligibility and native-message deduplication happen before any consumer ranks
    or counts records. A user-role message is not proof that every quoted claim
    inside it was authored or approved by the owner. Known machine envelopes have
    explicit origins and are excluded by default.
    """
    seen = set()
    for source, kind, path, owner_checked in _select_sources(sources, all_instances)[0]:
        if paths is not None and path not in paths:
            continue
        # For files whose store name may be shared with another folder, a record belongs to this
        # instance when the first working folder its session names is this instance's. A
        # session's lines read before that folder is known wait in held[session]; a session
        # that never names one is dropped. The first folder is the one the session started in,
        # so a session that later moved to another working folder keeps its owner's lines.
        session_owner, held = {}, {}
        file_kind = _file_identity(path)[0] if kind == "codex-jsonl" else "user"
        if file_kind == "subagent" and not include_agents:
            continue
        session_id = os.path.basename(path).removesuffix(".jsonl")
        if kind == "codex-jsonl":
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    meta = json.loads(f.readline()).get("payload") or {}
                session_id = meta.get("id") or session_id
            except (OSError, ValueError, AttributeError):
                pass
        with open(path, encoding="utf-8", errors="replace") as f:
            for line_number, line in enumerate(f, 1):
                native_id, stamp, origin = None, "", None
                if kind == "text":
                    role, text, origin = "document", line.rstrip("\n"), "document"
                    native_id = str(line_number)
                else:
                    try:
                        d = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(d, dict):
                        continue
                    if kind == "codex-jsonl":
                        got = _text_of_codex(d)
                        if not got:
                            continue
                        role, text, _ = got
                        native_id = (d.get("payload") or {}).get("id")
                    else:
                        line_session = d.get("sessionId") or os.path.basename(path).removesuffix(".jsonl")
                        if owner_checked and line_session not in session_owner:
                            cwd = d.get("cwd")
                            if isinstance(cwd, str) and cwd:
                                session_owner[line_session] = _same_instance(cwd)
                        got = _text_of(d, include_thinking=thinking)
                        if not got:
                            continue
                        role, text = got
                        native_id = d.get("uuid")
                        session_id = d.get("sessionId") or session_id
                    stamp = d.get("timestamp") or ""
                    content = (d.get("message") or {}).get("content")
                    tool_transport = (isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content))
                    if d.get("isCompactSummary") or text.startswith(
                            "This session is being continued from a previous conversation"):
                        role, origin = "summary", "summary"
                    elif tool_transport or (kind == "claude-jsonl" and d.get("isMeta") is True):
                        # Claude records hook feedback in user-role messages.
                        # Trust its explicit transport flag, not words that a
                        # person may also quote in an ordinary request.
                        origin = "system"
                    elif role == "user" and _is_system_injected(text):
                        origin = "system"
                    elif role == "user" and _AGENT_TRANSPORT.search(text):
                        origin = "agent"
                    elif file_kind == "subagent":
                        origin = "agent"
                    else:
                        origin = role
                if origin in ("system", "summary") and not include_system:
                    continue
                if origin == "agent" and not include_agents:
                    continue
                if not text:
                    continue
                record = {"source": source, "kind": kind, "path": os.path.abspath(path),
                          "line": line_number, "session_id": session_id,
                          "message_id": native_id, "record_id": None,
                          "timestamp": stamp, "role": role,
                          "origin": origin, "text": text}
                if owner_checked:
                    owned = session_owner.get(line_session)
                    if owned is None:
                        held.setdefault(line_session, []).append(record)
                        continue
                    if not owned:
                        continue
                    ready = held.pop(line_session, []) + [record]
                else:
                    ready = [record]
                for item in ready:
                    if _keep_new(item, seen):
                        yield item


def _keep_new(record, seen):
    """Give a record its stable record_id; return False when that id was already yielded.

    Do not merge repeated short owner replies just because the text is equal. Native IDs survive
    active/archive moves and Claude root-alias copies.
    """
    source, kind, session_id = record["source"], record["kind"], record["session_id"]
    native_id = record["message_id"]
    if native_id:
        identity = (source, kind, os.path.realpath(record["path"]) if kind == "text" else session_id,
                    str(native_id))
    else:
        identity = (source, kind, session_id, record["timestamp"], record["role"], record["text"])
    record_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
    if record_id in seen:
        return False
    seen.add(record_id)
    record["record_id"] = record_id
    return True


def _eligible(message, role=None, since=None):
    stamp = message["timestamp"]
    return ((role is None or message["role"] == role)
            and not (since and stamp and stamp[:10] < since))


def _match_stamps(pattern, sources, all_instances, thinking,
                  include_agents, include_system, role, since):
    """Compatibility helper; shares precisely the same eligibility as find."""
    rx, branches, _error = _compile_query(pattern)
    return [(_score(m["text"], branches, rx), m["timestamp"][:16])
            for m in iter_messages(sources, all_instances=all_instances, thinking=thinking,
                                   include_agents=include_agents, include_system=include_system)
            if _eligible(m, role, since) and rx.search(m["text"])]


def find(pattern, role=None, since=None, around=2, max_hits=8, thinking=False, sources=None,
         include_agents=False, include_system=False, all_instances=False,
         order="score", json_output=False, full=True, capped=False):
    """Select top-N eligible records in one pass; output their exact source locators.

    Keep at most N candidates plus a bounded context ring. Scoring, display, and
    consumer corpora all see the shared reader's eligibility and deduplication.
    full=False prints the compact form, whose hits stop at COMPACT_MAX_BYTES. capped=True
    (the CLI default form) also counts notices and the zero-hit message toward that cap.
    """
    if max_hits < 1 or around < 0:
        raise ValueError("max_hits must be positive and around must be nonnegative")
    capped = capped and not full and not json_output
    rx, branches, regex_error = _compile_query(pattern)
    notices = []
    if regex_error:
        notices.append(t("recall.literal_fallback", error=regex_error))
    missing = _missing_claude_store(sources)
    if missing:
        notices.append(t("recall.no_transcripts", path=missing))
    if capped:
        notices = [_clip_bytes(line, NOTICE_LINE_MAX_BYTES) for line in notices]
    # Notices go to stderr under --json so the structured stdout stays parseable.
    for line in notices:
        print(line, file=sys.stderr if json_output else sys.stdout)
    budget = COMPACT_MAX_BYTES - sum(_nbytes(line) + 1 for line in notices)
    best, ring, pending = [], collections.deque(maxlen=around), []
    previous_path = None
    files_read, messages_read, matched = set(), 0, 0
    for ordinal, message in enumerate(iter_messages(
            sources, all_instances=all_instances, thinking=thinking,
            include_agents=include_agents, include_system=include_system)):
        files_read.add(message["path"])
        messages_read += 1
        if message["path"] != previous_path:
            ring.clear()
            pending = []
            previous_path = message["path"]
        for candidate in pending:
            candidate["after"].append(message)
        pending = [c for c in pending if len(c["after"]) < around]
        text = message["text"]
        if _eligible(message, role, since) and rx.search(text):
            matched += 1
            score, stamp = _score(text, branches, rx), message["timestamp"]
            if order == "score":
                rank = (score, stamp, -ordinal)
            elif order == "recent":
                rank = (stamp, score, -ordinal)
            else:
                rank = (-ordinal,)
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
    selected = [item[2] for item in sorted(best, key=lambda item: item[0], reverse=True)]
    if json_output:
        print(json.dumps(selected, ensure_ascii=False))
        return 0
    if not full and selected:
        _print_compact(selected, rx, matched, budget if capped else COMPACT_MAX_BYTES, capped)
        return 0
    for hit, message in enumerate(selected, 1):
        origin = message["origin"]
        label = _origin_label(origin)
        print(t("recall.hit_header", hit=hit) + f"[{message['source']}] {message['path']}:{message['line']}"
              f" · {_local_time(message['timestamp'])} · {message['role']}{label}")
        print(f"  id:{message['record_id']}")
        for nearby in message["before"]:
            print(f"    {_local_time(nearby['timestamp'])} {nearby['role']:9s} | "
                  + nearby["text"][:200].strip().replace("\n", " "))
        print(f"  ▶ {message['snippet']}")
        for nearby in message["after"]:
            print(f"    {_local_time(nearby['timestamp'])} {nearby['role']:9s} | "
                  + nearby["text"][:200].strip().replace("\n", " "))
        print()
    if not selected:
        # Report what was actually searched: an empty answer is only as wide as its scope.
        files, unverified = _select_sources(sources, all_instances)
        names = sorted({name for name, _k, _b, _p in M.EPISODIC_SOURCES
                        if not sources or name in sources})
        filters = " ".join(f"--{k}={v}" for k, v in (("role", role), ("since", since)) if v)
        scope = t("recall.scope", files=len(files), sources=", ".join(names) or "-",
                  messages=messages_read, filters=f" ({filters})" if filters else "")
        shown_pattern = _clip_bytes(pattern, NOTICE_QUERY_MAX_BYTES) if capped else pattern
        lines = [t("recall.zero_hits", pattern=shown_pattern, scope=scope)]
        if unverified:
            lines.append(t("recall.unverified_files", count=unverified))
        text = "\n".join(lines) + "\n"
        if capped:
            text = _clip_bytes(text, budget)
        sys.stdout.write(text)
    return 0


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
        return t("recall.label_system")
    if origin == "summary":
        return t("recall.label_summary")
    return " [agent]" if origin == "agent" else ""


def _compact_block(hit, message, rx):
    origin = message["origin"]
    label = _origin_label(origin)
    lines = [f"■ {hit} · [{message['source']}] {os.path.basename(message['path'])}:{message['line']}"
             f" · {_local_time(message['timestamp'])} · {message['role']}{label}"]
    for nearby in message["before"]:
        lines.append(f"    {nearby['role']} | "
                     + nearby["text"][:COMPACT_NEARBY_CHARS].strip().replace("\n", " "))
    lines.append(f"  ▶ {_snip(message['text'], rx, COMPACT_SNIPPET_CHARS)}")
    for nearby in message["after"]:
        lines.append(f"    {nearby['role']} | "
                     + nearby["text"][:COMPACT_NEARBY_CHARS].strip().replace("\n", " "))
    return "\n".join(lines) + "\n"


def _print_compact(selected, rx, matched, budget=COMPACT_MAX_BYTES, clip_first=False):
    """Print hits until budget bytes, then one line naming what was left out and how to get it.

    A cut that does not say how to recover the rest leaves the reader guessing; naming the
    narrowing flags lets the next call ask for less instead of more. The first hit is always
    printed; clip_first cuts it to the budget instead of letting it run over.
    """
    trailer_room = len(t("recall.more", hidden=10 ** 6, total=10 ** 6).encode("utf-8")) + 1
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
        print(t("recall.more", hidden=matched - shown, total=matched))


def sessions(max_sessions=40):
    missing = _missing_claude_store(None)
    if missing:
        print(t("recall.no_transcripts", path=missing))
    files, unverified = _select_sources(None)
    files.sort(key=lambda row: os.path.getmtime(row[2]), reverse=True)
    total = len(files)
    shown = files if max_sessions is None else files[:max_sessions]
    for sname, kind, fp, _checked in shown:
        sz = os.path.getsize(fp) / 1048576
        print(f"[{sname:6s}] {os.path.basename(fp)[:52]:54s} {sz:8.1f} MB")
    if len(shown) < total:
        print(t("recall.sessions_more", shown=len(shown), total=total))
    if unverified:
        print(t("recall.unverified_files", count=unverified))
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("find")
    f.add_argument("pattern")
    f.add_argument("--role", choices=["user", "assistant"])
    f.add_argument("--since")
    f.add_argument("--around", type=int, default=None,
                   help=t("recall.help_around", full=FULL_AROUND_DEFAULT))
    f.add_argument("--max", type=int, default=8, dest="max_hits")
    f.add_argument("--thinking", action="store_true")
    f.add_argument("--full", action="store_true",
                   help=t("recall.help_full", max_bytes=COMPACT_MAX_BYTES))
    f.add_argument("--json", action="store_true", dest="json_output",
                   help=t("recall.help_json"))
    f.add_argument("--source", default=None, help=t("recall.help_source"))
    f.add_argument("--include-agents", action="store_true",
                   help=t("recall.help_include_agents"))
    f.add_argument("--include-system", action="store_true",
                   help=t("recall.help_include_system"))
    f.add_argument("--order", choices=["score","recent","oldest"], default="score",
                   help=t("recall.help_order"))
    f.add_argument("--all-instances", action="store_true",
                   help=t("recall.help_all_instances"))
    s = sub.add_parser("sessions")
    s.add_argument("--max", type=int, default=40, dest="max_sessions")
    s.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.cmd == "find":
        srcs = None if (a.source in (None, "all")) else set(a.source.split(","))
        # --json and --full keep the previous default context; compact output shows
        # neighbours only when they are asked for.
        around = a.around if a.around is not None else (
            FULL_AROUND_DEFAULT if (a.full or a.json_output) else 0)
        return find(a.pattern, a.role, a.since, around, a.max_hits, a.thinking, srcs,
                    include_agents=a.include_agents, include_system=a.include_system,
                    all_instances=a.all_instances, order=a.order, json_output=a.json_output,
                    full=a.full, capped=a.around is None)
    if a.cmd == "sessions":
        if a.max_sessions < 1 and not a.all:
            s.error(t("recall.max_too_small"))
        return sessions(None if a.all else a.max_sessions)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
