#!/usr/bin/env python3
"""Search episodic transcript records for targeted recall.

  recall.py find PATTERN [--source all|claude|codex|dumps] [--role user|assistant]
      [--since YYYY-MM-DD] [--around 2] [--max 8] [--thinking]
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


def _source_files(names, all_instances=False):
    """Yield configured source files. Codex storage is machine-wide, so filter it by instance identity unless all-instances access was explicitly requested. Claude sources are already project-scoped."""
    out, seen = [], set()
    for name, kind, base, pat in M.EPISODIC_SOURCES:
        if names and name not in names:
            continue
        bases = [base]
        # Only expand the configured instance transcript family, never an unrelated custom source.
        if kind == "claude-jsonl" and os.path.realpath(base) == os.path.realpath(M.TRANSCRIPTS):
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
            if identity not in seen:
                seen.add(identity)
                out.append((name, kind, f))
    return out


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


_AGENT_TRANSPORT = re.compile(
    r"^\s*(?:Another Claude session sent a message:|\[Claude Code가|FRESH_WORKER\b"
    r"|Claude다[.。]|너는 (?:Codex|코덱스|Claude)다[.。])", re.I)
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
    for source, kind, path in _source_files(sources, all_instances):
        if paths is not None and path not in paths:
            continue
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
                # Do not merge repeated short owner replies just because the text is equal.
                # Native IDs survive active/archive moves and Claude root-alias copies.
                if native_id:
                    identity = (source, kind, os.path.realpath(path) if kind == "text" else session_id,
                                str(native_id))
                else:
                    identity = (source, kind, session_id, stamp, role, text)
                record_id = hashlib.sha256(
                    json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
                if record_id in seen:
                    continue
                seen.add(record_id)
                yield {"source": source, "kind": kind, "path": os.path.abspath(path),
                       "line": line_number, "session_id": session_id,
                       "message_id": native_id, "record_id": record_id,
                       "timestamp": stamp, "role": role, "origin": origin, "text": text}


def _eligible(message, role=None, since=None):
    stamp = message["timestamp"]
    return ((role is None or message["role"] == role)
            and not (since and stamp and stamp[:10] < since))


def _match_stamps(pattern, sources, all_instances, thinking,
                  include_agents, include_system, role, since):
    """Compatibility helper; shares precisely the same eligibility as find."""
    rx, branches = re.compile(pattern, re.I), _branches(pattern)
    return [(_score(m["text"], branches, rx), m["timestamp"][:16])
            for m in iter_messages(sources, all_instances=all_instances, thinking=thinking,
                                   include_agents=include_agents, include_system=include_system)
            if _eligible(m, role, since) and rx.search(m["text"])]


def find(pattern, role=None, since=None, around=2, max_hits=8, thinking=False, sources=None,
         include_agents=False, include_system=False, all_instances=False,
         order="recent", json_output=False):
    """Select top-N eligible records in one pass; output their exact source locators.

    Keep at most N candidates plus a bounded context ring. Scoring, display, and
    consumer corpora all see the shared reader's eligibility and deduplication.
    """
    if max_hits < 1 or around < 0:
        raise ValueError("max_hits must be positive and around must be nonnegative")
    rx, branches = re.compile(pattern, re.I), _branches(pattern)
    best, ring, pending = [], collections.deque(maxlen=around), []
    previous_path = None
    for ordinal, message in enumerate(iter_messages(
            sources, all_instances=all_instances, thinking=thinking,
            include_agents=include_agents, include_system=include_system)):
        if message["path"] != previous_path:
            ring.clear()
            pending = []
            previous_path = message["path"]
        for candidate in pending:
            candidate["after"].append(message)
        pending = [c for c in pending if len(c["after"]) < around]
        text = message["text"]
        if _eligible(message, role, since) and rx.search(text):
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
    for hit, message in enumerate(selected, 1):
        origin = message["origin"]
        label = {"system": " [주입]", "summary": " [요약본]", "agent": " [agent]"}.get(origin, "")
        print(f"■ 매치 {hit} · [{message['source']}] {message['path']}:{message['line']}"
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
        print(f"매치 없음: /{pattern}/ — 소스 범위·파서·출처 필터·질의 표현을 확인할 것. "
              "원문의 부재를 뜻하지 않는다.")
    return 0


def sessions(max_sessions=40):
    files = _source_files(None)
    files.sort(key=lambda row: os.path.getmtime(row[2]), reverse=True)
    total = len(files)
    shown = files if max_sessions is None else files[:max_sessions]
    for sname, kind, fp in shown:
        sz = os.path.getsize(fp) / 1048576
        print(f"[{sname:6s}] {os.path.basename(fp)[:52]:54s} {sz:8.1f} MB")
    if len(shown) < total:
        print(f"({len(shown)}/{total}개 최신순 표시 · 전량은 `recall.py sessions --all`)")
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("find")
    f.add_argument("pattern")
    f.add_argument("--role", choices=["user", "assistant"])
    f.add_argument("--since")
    f.add_argument("--around", type=int, default=2)
    f.add_argument("--max", type=int, default=8, dest="max_hits")
    f.add_argument("--thinking", action="store_true")
    f.add_argument("--json", action="store_true", dest="json_output",
                   help="원문 위치·native ID·record ID를 포함한 구조화 결과")
    f.add_argument("--source", default=None, help="all(기본)|claude|codex|dumps, 콤마 목록 가능")
    f.add_argument("--include-agents", action="store_true",
                   help="서브에이전트 rollout과 알려진 에이전트 전달문도 검색")
    f.add_argument("--include-system", action="store_true",
                   help="시스템 주입 레코드도 표시 (플러그인 목록·AGENTS 전문·커맨드 래퍼 등)")
    f.add_argument("--order", choices=["score","recent","oldest"], default="score",
                   help="score=매치품질(기본) · recent=최신순 · oldest=파일순(이전 동작)")
    f.add_argument("--all-instances", action="store_true",
                   help="다른 인스턴스의 Codex 세션까지 검색 (기본은 이 인스턴스만 — DR-025)")
    s = sub.add_parser("sessions")
    s.add_argument("--max", type=int, default=40, dest="max_sessions")
    s.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.cmd == "find":
        srcs = None if (a.source in (None, "all")) else set(a.source.split(","))
        return find(a.pattern, a.role, a.since, a.around, a.max_hits, a.thinking, srcs,
                    include_agents=a.include_agents, include_system=a.include_system,
                    all_instances=a.all_instances, order=a.order, json_output=a.json_output)
    if a.cmd == "sessions":
        if a.max_sessions < 1 and not a.all:
            s.error("--max는 1 이상이어야 한다")
        return sessions(None if a.all else a.max_sessions)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
