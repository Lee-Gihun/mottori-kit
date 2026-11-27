#!/usr/bin/env python3
"""The owner's typed messages as a small derived store, and the lists a search of them prints.

recall.py hands every search of the owner's words here (find --role user, a time window, or a
locator of a listed message). The store holds one record per message the transcript reader marks
as typed by the owner, with the tail of the assistant's text just before a short reply; a search
ranks them by the words they share with the query (BM25), lists them by time, or opens one by its
locator, and recall_meaning.py adds an optional list by meaning. The store is a cache under the
private state folder: deleting it is safe, because the next search, or `recall.py index`, builds
it again from the transcripts.

The store keeps no other assistant text and no tool output. One exception: per session it keeps
the last 300 characters of assistant text that no reply has followed yet. That text is never
searched or printed. It is kept because an update reads only what was added, and a short reply
written later needs the text before it.
"""
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import paths as P
import safeio
import recall_meaning as meaning
import transcripts as T

# Messages this module prints in more than one place, or too long to read inline.
RECALL_STORE_CATCH_UP_FAILED = (
    "[tasks] Bringing the search index up to date behind the session failed ({reason}); a search "
    "answers from what is indexed now, and the next session start tries again."
)
CATCH_UP_STOPPED = "it stopped before it finished"
RECALL_STORE_COVERAGE = (
    "Searched: {count} messages the owner typed, {first} to {last} ({sources}); store checked "
    "{updated}; {waiting} file(s) waiting for the next search or `recall.py index`, "
    "{unreadable} unreadable{left}{meaning}."
)
RECALL_STORE_INDEXED = (
    "Indexed {count} owner messages from {files} transcript files in {seconds} s ({path})."
)
RECALL_STORE_NO_LOCATOR = (
    "No stored message at {locator}; a locator comes from a list line (8 characters:line)."
)
RECALL_STORE_RECENT = (
    "The newest message of the session written last was left out: it is the turn that is asking."
)
RECALL_STORE_SHORT_LABEL = (
    "Short replies found through the assistant's text before them (read both before saying they "
    "decided):"
)
RECALL_STORE_SHORT_QUERY = (
    "One or two words find far less: ask in a full sentence and add any of the owner's own words "
    "you remember."
)

STORE = P.recall_store()
# What the catch-up process started at session start did; its lock is held while it runs.
CATCH_UP = P.recall_catch_up
# One line per search of the owner's words (time, query, options, lines shown), never a hit's text:
# the material for measuring how real queries are asked. Deleting it loses nothing else.
QUERY_LOG = P.recall_queries()
# A change of what a record holds or how it is tokenized bumps this, so an old store is rebuilt.
VERSION = 1
# A stored record is a list of these fields, in this order; _unpack names them.
FIELDS = ("line", "timestamp", "epoch", "session", "text", "tail", "n", "nc")
# A reply this short usually means what the assistant's text before it proposed ("yes, do that").
SHORT_REPLY_CHARS = 45
# How much of the assistant's text before a short reply is kept with it.
TAIL_CHARS = 300
# A few long pasted messages hold most of the text; the store keeps a message up to this point,
# which keeps it small and a search fast. Opening a message by its locator reads it whole.
TEXT_CHARS = 2000
# A search reads what the transcripts added for at most this long, newest files first, so a
# message typed a minute ago is in the store and can be listed;
# it embeds what has no vector for at most this long only
# while no catch-up process runs, and it never waits for one. A file with more unread bytes than
# a search can read in that time is left to the catch-up or `recall.py index`.
UPDATE_SECONDS = 3
SEARCH_BYTES = 200 * 1024 * 1024
# Without a store, a history this large is built inline by the first search; a larger one asks
# for `recall.py index` once, because reading it would hold up the search for minutes.
FIRST_BUILD_BYTES = 300 * 1024 * 1024
# Lines of the short-reply list.
SHORT_LINES = 4
# The message of the turn that is asking is in its transcript already and would match itself. A
# message older than this is taken for one of an earlier turn and is listed.
RECENT_MINUTES = 10
# Width of a --before or --near window when --minutes does not say.
WINDOW_MINUTES = 30
# The BM25 constants: term-frequency saturation and length normalization.
K1, B = 1.2, 0.75
# Characters of a message shown on its list line, before a line is cut to fit the budget.
LINE_CHARS = 150
# Beside the list by meaning the word list shows this many lines, or half of --max when that is
# more: the two lists find different things, so both are shown, apart, and both grow for a sweep.
BESIDE_LINES = 4
# Of the short-reply lines, this many come by meaning and the rest by words.
SHORT_BY_MEANING = 2
# Locators the lists print: the last 8 characters of the session id in the file name, and a line.
# The last ones, because time-ordered ids (Codex) share their first characters across sessions
# started in the same minute; the rare locator two files still share opens both.
LOCATOR = re.compile(r"^([0-9a-f]{8}):(\d+)$")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# Scripts written without reliable spaces between words: a run of their letters is not a word, so
# every adjacent pair of their characters is a token, including the pair across a single space, and
# a lone one is a token by itself. Words are runs of letters or digits of every other script, so a
# term written against a following particle, as BM25 with a Korean ending, is the term.
_SPACELESS = ("ᄀ-ᇿ぀-ヿ㄰-㆏㐀-䶿一-鿿"
              "ꥠ-꥿가-힯豈-﫿ｦ-ﾟ")
_SPACELESS_CHAR = re.compile("[" + _SPACELESS + "]")
_WORD = re.compile(r"[^\W_" + _SPACELESS + r"]+")
_RUN = re.compile("[" + _SPACELESS + "]+")
_PAIR = re.compile(r"(?=([" + _SPACELESS + r"]) ?([" + _SPACELESS + r"]))")
_WORD_EDGE = r"[^\W_" + _SPACELESS + r"]"


def search_copy(text):
    """The form every comparison uses; the stored text stays as typed."""
    return unicodedata.normalize("NFKC", text).casefold()


def tokens(copy):
    """Words, lone characters of spaceless scripts, and their character pairs."""
    return (_WORD.findall(copy) + [run for run in _RUN.findall(copy) if len(run) == 1]
            + [a + b for a, b in _PAIR.findall(copy)])


def short_id(path):
    """The part of a file name a locator names: the session id's last 8 characters."""
    stem = os.path.basename(path)
    found = _UUID.findall(stem)
    return found[-1][-8:] if found else stem[:8]


def _nbytes(text):
    return len(text.encode("utf-8"))


# ------------------------------------------------------------------ store


def load():
    try:
        with open(STORE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {"version": VERSION, "updated": None, "left": 0, "files": {}}
    return data


def _save(store):
    safeio.atomic_write(STORE, json.dumps(store, ensure_ascii=False, separators=(",", ":")))


def _unpack(path, entry, stored):
    """One stored record of the file at path as a dict, named by FIELDS."""
    return {"path": path, "source": entry["source"], **dict(zip(FIELDS, stored))}


def _transcripts(selection):
    return {path: (name, kind) for name, kind, path, _checked in selection.rows if kind != "text"}


def _stat(path):
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime_ns, st.st_ino
    except OSError:
        return None


def _complete_lines(path, offset, line):
    """Byte offset and line number after the last complete line, reading from offset.

    Read in blocks: one session file can be larger than the memory a search may take."""
    end = offset
    with open(path, "rb") as f:
        f.seek(offset)
        while True:
            block = f.read(1 << 22)
            if not block:
                return end, line
            last = block.rfind(b"\n")
            if last >= 0:
                line += block.count(b"\n")
                end = offset + last + 1
            offset += len(block)


def _tag(path, offset):
    """The bytes just before offset, so a file rewritten in place to a larger size is noticed."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, offset - 256))
            return hashlib.sha1(f.read(min(offset, 256))).hexdigest()[:16]
    except OSError:
        return None


def _changed(entry, st):
    return st is not None and (entry is None or [entry["size"], entry["mtime"]] != list(st[:2]))


def update(store, selection, seconds=UPDATE_SECONDS):
    """Read what was added to the transcripts since the store last saw them; save the store.

    Returns the number of records that left with deleted files in this update. Changed files are
    read newest first, each to its end; with `seconds`, none is started after that time and none
    whose unread part is larger than a search can read in that time, so a search stays short.
    What is left stays waiting for the next use or for `recall.py index`.
    """
    files = _transcripts(selection)
    rows = {row[2]: row for row in selection.rows}
    left = 0
    for path in [p for p in store["files"] if p not in files]:
        left += len(store["files"].pop(path)["records"])
    store["left"] = store.get("left", 0) + left
    changed = [p for p in files if _changed(store["files"].get(p), _stat(p))]
    changed.sort(key=T.mtime, reverse=True)
    deadline = None if seconds is None else time.monotonic() + seconds
    read = 0
    for path in changed:
        if deadline is not None and time.monotonic() > deadline:
            break
        got = _update_file(store["files"].get(path), path, files[path],
                           selection._replace(rows=[rows[path]]), deadline)
        if got is not None:
            store["files"][path], was_read = got
            read += was_read
    if read or left:
        store["updated"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        _save(store)
    return left


def _update_file(entry, path, source, selection, deadline):
    """Return (the file's new entry, whether it was read), or None to leave the entry as it is.

    A file that grew in place is read from where the entry stopped; a compressed, replaced or
    rewritten one is read again from its start. A Codex subagent session is remembered unread,
    with no records, because it never holds the owner's words."""
    name, kind = source
    st = _stat(path)
    if st is None:
        return None
    fresh = {"source": name, "kind": kind, "size": st[0], "mtime": st[1], "ino": st[2],
             "offset": 0, "line": 0, "tails": {}, "records": []}
    if kind == "codex-jsonl" and T.session_identity(path)[0] == "subagent":
        return fresh, False
    if (entry and not path.endswith(T.ZST_SUFFIX) and entry["ino"] == st[2]
            and entry["offset"] <= st[0]
            and entry.get("tag", "") == _tag(path, entry["offset"])):
        fresh.update(offset=entry["offset"], line=entry["line"],
                     tails=dict(entry["tails"]), records=list(entry["records"]))
    if deadline is not None and st[0] - fresh["offset"] > SEARCH_BYTES:
        return None
    resume = None
    if path.endswith(T.ZST_SUFFIX):
        fresh["offset"] = st[0]
    else:
        resume = {path: (fresh["offset"], fresh["line"])}
        try:
            fresh["offset"], fresh["line"] = _complete_lines(path, fresh["offset"],
                                                             fresh["line"])
            fresh["tag"] = _tag(path, fresh["offset"])
        except OSError:
            return None
    _read_file(fresh, path, selection, resume)
    return fresh, True


def _read_file(entry, path, selection, resume):
    """Add one file's new owner messages to its entry, with the tail before a short reply."""
    buffers = {}
    for message in T.iter_messages(None, resume=resume, selection=selection):
        if (resume and message["line"] > entry["line"]):
            continue   # A line still being written; the next update reads it whole.
        session = message["session_id"]
        if session not in buffers:
            buffers[session] = entry["tails"].get(session, "")
        if message["role"] == "assistant" and message["origin"] == "assistant":
            buffers[session] = (buffers[session] + "\n" + message["text"])[-TAIL_CHARS:]
        elif message["role"] == "user" and message["origin"] == "user":
            text = message["text"][:TEXT_CHARS]
            tail = buffers[session].strip() if len(text.strip()) <= SHORT_REPLY_CHARS else None
            buffers[session] = ""
            when = T.instant(message["timestamp"])
            searched = search_copy(text)
            entry["records"].append([   # in the order of FIELDS
                message["line"], message["timestamp"], when.timestamp() if when else None,
                session, text, tail or None, len(tokens(searched)),
                len(tokens(search_copy(tail) + "\n" + searched)) if tail else None])
    entry["tails"].update(buffers)


def refresh(selection, seconds=UPDATE_SECONDS):
    """Load the store and bring it up to date. Returns (store, status), or (None, status) when
    there is no store yet and building it would take far longer than a search."""
    files = _transcripts(selection)
    store = load()
    status = {"left": 0}
    if not store["files"]:
        pending = sum((_stat(p) or (0,))[0] for p in files)
        if pending > FIRST_BUILD_BYTES:
            return None, status
        seconds = None
    try:
        with safeio.locked(STORE + ".lock", timeout=seconds or 600):
            # Another search may have saved while this one waited. The copy read above goes
            # first, so the store is held once.
            store = None
            store = load()
            status["left"] = update(store, selection, seconds)
            # Checked now even when nothing was new, which is what the coverage line must say.
            status["checked"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    except (safeio.StateLockTimeout, OSError):
        pass   # Another search is updating; this one answers from what is saved.
    status["waiting"] = sum(1 for path in files if _changed(store["files"].get(path), _stat(path)))
    status["unreadable"] = selection.zst_skipped + selection.malformed + T.unreadable_count()
    return store, status


def _update_all():
    """Bring the store fully up to date without a time limit; returns (store, records)."""
    selection = T.select_sources(None)
    with safeio.locked(STORE + ".lock", timeout=600):
        store = load()
        update(store, selection, None)
    return store, stored_records(store)


def build():
    """Bring the store and the vectors fully up to date (`recall.py index`)."""
    start = time.monotonic()
    store, records = _update_all()
    print(RECALL_STORE_INDEXED.format(count=len(records), files=len(store["files"]), seconds=round(time.monotonic() - start, 1), path=os.path.relpath(STORE, P.instance_root())))
    code = meaning.update_all(records)
    print(meaning.state(records))
    return code


# ------------------------------------------------------------------ catching up behind a session


def _behind(selection):
    """Whether a transcript changed since the store read it, or a stored message has no vector."""
    store = load()
    files = _transcripts(selection)
    if any(p not in files for p in store["files"]) or any(
            _changed(store["files"].get(p), _stat(p)) for p in files):
        return True
    return meaning.behind(stored_records(store))


def _holds(lock_file):
    """Take the catch-up lock on an open file without waiting; False when a process holds it."""
    import fcntl
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def catch_up_running(root=None):
    """Whether a catch-up process runs now."""
    if not os.path.exists(CATCH_UP(root) + ".lock"):
        return False
    with open(CATCH_UP(root) + ".lock", "a+b") as lock_file:
        return not _holds(lock_file)   # closing the file lets go of a lock taken here


def start_catch_up():
    """Session start: when no catch-up runs, start one detached process that brings the store and
    the vectors up to date if they are behind, and return without waiting for it.

    Whether anything is behind is decided in that process: it reads every session store on the
    machine, which can take longer than the session start may wait. The lock is taken here and
    handed to the process, so a second session start that comes while it runs starts none."""
    if catch_up_running():
        return 0
    safeio.make_parent(CATCH_UP())
    with open(CATCH_UP() + ".lock", "a+b") as lock_file:
        if not _holds(lock_file):
            return 0
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import recall_store; "
                "recall_store.catch_up(int(sys.argv[2]))")
        subprocess.Popen([sys.executable, "-c", code, os.path.dirname(os.path.abspath(__file__)),
                          str(lock_file.fileno())], pass_fds=(lock_file.fileno(),),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    return 0


def catch_up(lock_fd):
    """The detached process: while holding the lock it was handed, bring the store and the
    vectors up to date when they are behind, then record what the index holds. When nothing is
    behind it records nothing, so the last catch-up's outcome stands."""
    # The failure said last is kept, so the same failure is not said again by a later catch-up.
    said = (_catch_up_status() or {}).get("said")
    status = dict({"started": time.time()}, **({"said": said} if said else {}))
    try:
        try:
            if not _behind(T.select_sources(None)):
                return
            safeio.atomic_write(CATCH_UP(), json.dumps(status))
            _store, records = _update_all()
            lines = []
            code = meaning.update_all(records, say=lines.append)
            status.update(messages=len(records), meaning=meaning.indexed(records),
                          failed=lines[-1] if code and lines else None)
        except Exception as exc:  # noqa: BLE001 - said by the work line, not lost with the process
            status["failed"] = f"{type(exc).__name__}: {exc}"
        status["ended"] = time.time()
        safeio.atomic_write(CATCH_UP(), json.dumps(status))
    finally:
        os.close(lock_fd)


def _catch_up_status(root=None):
    try:
        with open(CATCH_UP(root), encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) and isinstance(
        status.get("started"), (int, float)) else None


def catch_up_notice(keep, root=None):
    """(key, line) for a catch-up that failed or stopped before it finished, or None.

    A catch-up that runs or ended well says nothing: the last line of a search says how much is
    indexed. A failure is said once, and a later catch-up that fails the same way says nothing;
    a catch-up that ends well forgets it. The outcome is marked told unless keep (a run whose
    lines nobody reads)."""
    status = _catch_up_status(root)
    if status is None or status.get("told") or catch_up_running(root):
        return None
    if status.get("ended") is None:
        reason = CATCH_UP_STOPPED
    else:
        reason = (status.get("failed") or "").rstrip(".") or None
    if not keep:
        told = dict(status, told=True)
        told.pop("said", None)
        if reason:
            told["said"] = reason
        safeio.atomic_write(CATCH_UP(root), json.dumps(told))
    if reason is None or reason == status.get("said"):
        return None
    return ("index", status["started"], "ended"), RECALL_STORE_CATCH_UP_FAILED.format(reason=reason)


# ------------------------------------------------------------------ ranking


def stored_records(store, sources=None):
    """The stored records of the named sources (all when None), each typed message once, oldest
    first."""
    rows = []
    for path in sorted(store["files"]):
        entry = store["files"][path]
        if sources and entry["source"] not in sources:
            continue
        rows.extend(_unpack(path, entry, stored) for stored in entry["records"])
    # A forked or imported session repeats earlier messages in its own file, sometimes with
    # the time of the copy, so the earliest copy is kept and copies in other files are
    # dropped. A message longer than a short reply is the same one by its text; a short
    # reply only with the same assistant text before it, or at the same instant. In one file
    # a repeat is a resend, which a listing by time must show at its own time.
    rows.sort(key=lambda r: (r["epoch"] is None, r["epoch"] or 0))
    first, records = {}, []
    for r in rows:
        text = r["text"].strip()
        key = (text if len(text) > SHORT_REPLY_CHARS
               else (text, r["tail"]) if r["tail"] else (text, r["timestamp"]))
        if first.setdefault(key, r["path"]) != r["path"]:
            continue
        records.append(r)
    return records


def _pair(token):
    return len(token) == 2 and all(_SPACELESS_CHAR.match(ch) for ch in token)


def _count(token, doc):
    """How often a query token occurs in one search copy, the way tokens() counts it."""
    if _pair(token):
        return doc.count(token) + doc.count(token[0] + " " + token[1])
    edge = "[" + _SPACELESS + "]" if _SPACELESS_CHAR.match(token) else _WORD_EDGE
    return len(re.findall("(?<!" + edge + ")" + re.escape(token) + "(?!" + edge + ")", doc))


def bm25(order, texts, lengths, query_tokens):
    """BM25 scores of the documents texts[i] (search copies) for the query, as {order[i]: score}.

    A substring test per document goes first: it is done in C and rules out most documents, so
    a token common enough to occur a hundred thousand times costs no Python step per occurrence."""
    if not order:
        return {}
    count = len(order)
    avg = sum(lengths) / count or 1.0
    scores = {}
    for token in set(query_tokens):
        if _pair(token):
            spaced = token[0] + " " + token[1]
            found = [i for i, doc in enumerate(texts) if token in doc or spaced in doc]
        else:
            found = [i for i, doc in enumerate(texts) if token in doc]
        tf = {}
        for doc in found:
            f = _count(token, texts[doc])
            if f:
                tf[doc] = f
        if not tf:
            continue
        idf = math.log(1 + (count - len(tf) + 0.5) / (len(tf) + 0.5))
        for doc, f in tf.items():
            norm = f + K1 * (1 - B + B * lengths[doc] / avg)
            scores[order[doc]] = scores.get(order[doc], 0.0) + idf * f * (K1 + 1) / norm
    return scores


# ------------------------------------------------------------------ printing


def _when(epoch):
    if epoch is None:
        return "????-??-?? ??:??"
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


def _flat(text):
    return " ".join(text.split())


def _cut(text, chars, keep_end=False):
    if len(text) <= chars:
        return text
    return ("…" + text[-max(0, chars - 1):]) if keep_end else (text[:max(0, chars - 1)] + "…")


def head(record):
    """What a line starts with: when, which runtime, and the locator that opens the message."""
    return (f"■ {_when(record['epoch'])} [{record['source']}] "
            f"{short_id(record['path'])}:{record['line']}")


def line_of(record, chars, exact=False, short=False, mark="", lead=""):
    """One list line of a record, its text cut to chars; a short reply shows the end of the
    assistant's text before it. mark and lead are what its list adds (a similarity, [both])."""
    mark = (" [exact]" if exact else "") + mark + (f" · {lead}" if lead else "")
    if short:
        reply = _flat(record["text"])
        tail = _cut(_flat(record["tail"] or ""), max(0, chars - len(reply) - 4), keep_end=True)
        return f"{head(record)}{mark} · {tail} → {reply}"
    return f"{head(record)}{mark} · {_cut(_flat(record['text']), chars)}"


def print_block(lines, budget):
    """Print lines within budget bytes; a line past the budget keeps only its head, never dropped.

    lines holds (record, render(chars)) pairs; each line gets an equal share of what is left."""
    used = 0
    for position, (record, render) in enumerate(lines):
        share = (budget - used) // max(1, len(lines) - position)
        chars = LINE_CHARS
        text = render(chars)
        while _nbytes(text) + 1 > share and chars > 0:
            over = _nbytes(text) + 1 - share
            chars = max(0, min(chars, len(text)) - max(1, over // 2))
            text = render(chars) if chars else head(record)
        print(text)
        used += _nbytes(text) + 1
    return used


def coverage(store, records, status, found=None, catching=False):
    """The closing line of a search: what it searched, and with the list by meaning how much of
    it has vectors."""
    stamps = [r["epoch"] for r in records if r["epoch"] is not None]
    by_meaning = ""
    if not found and C.meaning_off_hint():
        # Off says so where people look, with the one command that turns it on (KIT-DR-094).
        by_meaning = "; " + C.meaning_off_hint()
    if found:
        have = meaning.share(found.vectors, records)[0]
        by_meaning = f"; by meaning: {have} of {len(records)}" + (
            ", the rest being indexed behind the session" if catching and have < len(records)
            else "")
    left = status.get("left") or store.get("left", 0)
    updated = status.get("checked") or store.get("updated") or "-"
    sources = sorted({r["source"] for r in records})
    return RECALL_STORE_COVERAGE.format(count=len(records), first=_when(min(stamps))[:10] if stamps else "-", last=_when(max(stamps))[:10] if stamps else "-", sources=", ".join(sources) or "-", updated=updated[:16].replace("T", " "), waiting=status.get("waiting", 0), unreadable=status.get("unreadable", 0), left=f"; {left} left with deleted transcripts" if left else "", meaning=by_meaning)


def log_query(query, options, shown):
    try:
        os.makedirs(os.path.dirname(QUERY_LOG), exist_ok=True)
        with open(QUERY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": datetime.datetime.now().astimezone().isoformat(
                timespec="seconds"), "query": query, "options": options, "shown": shown},
                ensure_ascii=False) + "\n")
    except OSError:
        pass   # The log is material for a later measurement; a search never fails over it.


# ------------------------------------------------------------------ searching


def parse_time(text, end=False):
    """A date or a time; without a zone it is local time. A date alone means its first instant,
    or with end=True the first instant of the next day. Returns an epoch, or None.

    recall.py checks the time arguments with this function, so a time it accepts is a time the
    window below can place."""
    text = text.strip()
    try:
        day = datetime.date.fromisoformat(text)
        moment = datetime.datetime.combine(day + datetime.timedelta(days=1 if end else 0),
                                           datetime.time())
        return moment.astimezone().timestamp()
    except ValueError:
        pass
    value = C.parse_timestamp(text.replace(" ", "T", 1))
    if value is None:
        try:
            value = datetime.datetime.fromisoformat(text.replace("T", " ", 1))
        except ValueError:
            return None
    return (value if value.tzinfo else value.astimezone()).timestamp()


def window(a):
    """The time limits of a search as (low, high, reference) epochs, any of them None."""
    low = parse_time(a.since) if a.since else None
    high = parse_time(a.until, end=True) if a.until else None
    reference = None
    minutes = (a.minutes if a.minutes is not None else WINDOW_MINUTES) * 60
    if a.before:
        reference = parse_time(a.before)
        low = max(low or -math.inf, reference - minutes)
        high = min(high if high is not None else math.inf, reference)
    if a.near:
        reference = parse_time(a.near)
        low = max(low or -math.inf, reference - minutes)
        high = min(high if high is not None else math.inf, reference + minutes)
    return low, high, reference


def _asking(records, now):
    """The index of the message of the turn that is asking, or None.

    The asking session's transcript is being written while it searches, so it is the one
    written last, and its newest message of the last RECENT_MINUTES is the question. What the
    owner typed a moment ago in another session, or earlier in this one, is not left out. A
    search from a session that keeps no transcript leaves out the newest message of another
    recent session instead.
    """
    newest = {}
    for i, record in enumerate(records):
        epoch = record["epoch"]
        if epoch is not None and epoch > now - RECENT_MINUTES * 60:
            held = newest.get(record["path"])
            if held is None or epoch > records[held]["epoch"]:
                newest[record["path"]] = i
    if not newest:
        return None

    def written(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0
    return newest[max(sorted(newest), key=written)]


def _pool(records, low, high, query, now):
    """The indexes of the records a search may list, with the counts of those left out:
    (pool, the asking turn's message, undated under a time limit or a search by time)."""
    recent = undated = 0
    pool = []
    asking = _asking(records, now)
    for i, record in enumerate(records):
        epoch = record["epoch"]
        if i == asking:
            recent += 1
            continue
        if (low is not None or high is not None or not query) and epoch is None:
            # It may as well be years outside the window, and a listing by time cannot place
            # it; said, not kept.
            undated += 1
            continue
        if low is not None and epoch < low:
            continue
        if high is not None and epoch > high:
            continue
        pool.append(i)
    return pool, recent, undated


def find(a, query, sources, budget, full_around):
    """Answer a search of the owner's words from the store and print it within budget bytes.

    full_around is the number of neighbours --full shows when --around does not say. Returns
    an exit code, or None when the store does not exist yet and is too large to build inside
    one search."""
    selection = T.select_sources(None)
    store, status = refresh(selection)
    if store is None:
        return None
    records = stored_records(store, sources)
    low, high, reference = window(a)
    now = time.time()
    pool, recent, undated = _pool(records, low, high, query, now)
    trailer = []
    # A search by time alone embeds nothing; see UPDATE_SECONDS for the rule.
    catching = bool(query) and catch_up_running()
    found = (meaning.prepare(query, records, trailer, 0 if catching else UPDATE_SECONDS)
             if query else None)
    if recent:
        trailer.append(RECALL_STORE_RECENT)
    if undated:
        trailer.append(T.MALFORMED_SKIPPED.format(count=undated))
    trailer.append(coverage(store, records, status, found, catching))
    if query and len(query.split()) <= 2:
        trailer.append(RECALL_STORE_SHORT_QUERY)
    budget -= sum(_nbytes(x) + 1 for x in trailer)
    if query:
        lists = _by_query(a, records, pool, query, found)
    else:
        lists = _by_time(a, records, pool, reference, high, now)
    if a.order in ("oldest", "recent"):
        epoch_of = lambda i: records[i]["epoch"] or 0
        for _label, picked, _render in lists["blocks"]:
            picked.sort(key=epoch_of, reverse=a.order == "recent")
        lists["short"].sort(key=epoch_of, reverse=a.order == "recent")
    _print_lists(a, records, lists, selection.unverified, budget, query, full_around)
    for line in trailer:
        print(line)
    blocks = lists["blocks"]
    shown = {"words": len(blocks[-1][1]), "short": len(lists["short"])}
    if lists["by_meaning"]:
        shown["meaning"] = len(blocks[0][1])
    log_query(query, {k: v for k, v in (("since", a.since), ("until", a.until),
                                        ("near", a.near), ("before", a.before),
                                        ("minutes", a.minutes), ("max", a.max_hits),
                                        ("order", a.order), ("source", a.source),
                                        ("around", a.around), ("full", a.full))
                      if v not in (None, False)}, shown)
    return 0


def _ranked(scores, records):
    """The keys of scores, highest first, the newer of two equal ones first."""
    return sorted(scores, key=lambda i: (-scores[i], -(records[i]["epoch"] or 0)))


def _by_query(a, records, pool, query, found):
    """The lists of a search by words: by meaning and by words beside it when the list by
    meaning has vectors in this range, else by words alone; then the short replies."""
    limit = a.max_hits
    order = "best first" if a.order == "score" else "shown in time order"
    qtokens = tokens(search_copy(query))
    scores = bm25(pool, [search_copy(records[i]["text"]) for i in pool],
                  [records[i]["n"] or 1 for i in pool], qtokens)
    matched = _ranked(scores, records)
    sims = found.messages(records, pool) if found else {}
    if not sims:
        found = None   # Nothing embedded yet in this range: the word list keeps its lines.
    if found:
        by_meaning = _ranked(sims, records)[:limit]
        word_top = set(matched[:limit])
        shown = set(by_meaning)
        beside = [i for i in matched if i not in shown][:max(BESIDE_LINES, limit // 2)]
        listed = shown | set(beside)
        blocks = [(f"The owner's messages by meaning, with similarity ({order}):", by_meaning,
                   lambda r, i: {"lead": f"{sims[i]:.2f}",
                                 "mark": " [both]" if i in word_top else ""}),
                  (f"By words, not listed above ({order}):", beside, lambda r, i: {})]
    else:
        listed = set(matched[:limit])
        blocks = [(f"The owner's messages by words ({order}):", matched[:limit],
                   lambda r, i: {})]
    short, short_sims = _short_replies(records, pool, listed, qtokens, found)
    return {"blocks": blocks, "short": short, "short_sims": short_sims, "matched": matched,
            "hidden": sum(1 for i in matched if i not in listed), "by_meaning": bool(found)}


def _short_replies(records, pool, listed, qtokens, found):
    """The short replies not listed above, ranked by the assistant's text before them and the
    reply together; with the list by meaning the first SHORT_BY_MEANING come by meaning.
    Returns (indexes, {index: similarity shown})."""
    short_pool = [i for i in pool if records[i]["tail"] and i not in listed]
    scores = bm25(short_pool, [search_copy(records[i]["tail"] + "\n" + records[i]["text"])
                               for i in short_pool],
                  [records[i]["nc"] or 1 for i in short_pool], qtokens)
    by_words = _ranked(scores, records)
    sims = {}
    if found:
        replies = found.replies(records, short_pool)
        first = _ranked(replies, records)[:SHORT_BY_MEANING]
        by_words = first + [i for i in by_words if i not in first]
        sims = {i: f"{replies[i]:.2f}" for i in first}   # a weak pick shows it
    return by_words[:SHORT_LINES], sims


def _by_time(a, records, pool, reference, high, now):
    """The list of a search by time alone: what the owner typed, nearest the window's reference first."""
    anchor = (reference if reference is not None
              else high if high not in (None, math.inf) else now)
    matched = sorted(pool, key=lambda i: abs(records[i]["epoch"] - anchor))
    blocks = [("What the owner typed in that time, nearest first:", matched[:a.max_hits],
               lambda r, i: {})]
    return {"blocks": blocks, "short": [], "short_sims": {}, "matched": matched,
            "hidden": len(matched) - len(blocks[0][1]), "by_meaning": False}


def _print_lists(a, records, lists, unverified, budget, query, full_around):
    """Print the lists, their notes and the short replies, sharing budget by line count.

    A list after the first is left out when it is empty; the first always prints its label."""
    blocks, short = lists["blocks"], lists["short"]
    hits = [records[i] for _label, picked, _render in blocks for i in picked]
    notes = ["No message of the owner matched."] if not hits else []
    # Files that never name a working folder were kept without proof that they are this folder's.
    if unverified and (not hits or any(T.file_unverified(r["path"])
                                       for r in hits + [records[i] for i in short])):
        notes.append(T.UNVERIFIED_FILES.format(count=unverified))
    if lists["hidden"] > 0:
        notes.append(f"{lists['hidden']} more of {len(lists['matched'])} matching messages not shown (--max N shows more).")
    short_label = RECALL_STORE_SHORT_LABEL if short else None
    labels = [label for label, picked, _render in blocks if picked or label == blocks[0][0]]
    budget -= sum(_nbytes(x) + 1 for x in [*labels, short_label, *notes] if x)
    lines = sum(len(picked) for _label, picked, _render in blocks) + len(short)
    for label, picked, render in blocks:
        if not picked and label != blocks[0][0]:
            continue
        print(label)
        share = budget * len(picked) // max(1, lines)
        budget -= _print_hits(a, [(records[i], render(records[i], i)) for i in picked], share,
                              query, full_around)
        lines -= len(picked)
    for line in notes:
        print(line)
    if short:
        print(short_label)
        print_block([(records[i], (lambda chars, i=i: line_of(
            records[i], chars, short=True, lead=lists["short_sims"].get(i, ""))))
                     for i in short], budget)


def _exact(record, query):
    squashed = "".join(search_copy(query).split())
    return bool(squashed) and squashed in "".join(search_copy(record["text"]).split())


def _print_hits(a, hits, budget, query, full_around):
    """Print the hits one line each, or in full with neighbours when asked; return bytes used.

    hits holds (record, extra) pairs, extra being what line_of adds to that line."""
    if a.full or a.around:
        for record, _extra in hits:
            show_message(record, a.around if a.around is not None else full_around,
                         full=a.full)
        return 0
    return print_block([(r, (lambda chars, r=r, extra=extra: line_of(
        r, chars, _exact(r, query) if query else False, **extra))) for r, extra in hits], budget)


# ------------------------------------------------------------------ opening a message


def _line_offset(path, line):
    """Byte offset where line number `line` (1-based) starts in a plain transcript."""
    if line <= 1:
        return 0
    seen, offset = 1, 0
    with open(path, "rb") as f:
        while True:
            block = f.read(1 << 20)
            if not block:
                return offset
            start = 0
            while seen < line:
                at = block.find(b"\n", start)
                if at < 0:
                    break
                seen += 1
                start = at + 1
            if seen == line:
                return offset + start
            offset += len(block)


def _split_at(messages, line, around):
    """(up to `around` messages before `line`, the message at it, up to `around` after it)."""
    before, target, after = [], None, []
    for message in messages:
        if message["line"] < line:
            before = (before + [message])[-around:] if around else []
        elif message["line"] == line and target is None:
            target = message
        elif target is not None:
            after.append(message)
            if len(after) >= around:
                break
    return before, target, after


def neighbours(path, line, around):
    """The messages around one line of a transcript, read from that file alone."""
    selection = T.select_sources(None)
    span = max(200, around * 50)
    while True:
        first = max(1, line - span)
        resume = None
        if not path.endswith(T.ZST_SUFFIX):
            resume = {path: (_line_offset(path, first), first - 1)}
        messages = T.iter_messages(None, paths={path}, resume=resume, selection=selection)
        before, target, after = _split_at(messages, line, around)
        if len(before) >= around or first == 1 or resume is None:
            return before, target, after
        span *= 4


def show_message(record, around, full=True):
    """Print a message read from its transcript, with `around` messages on each side."""
    before, target, after = neighbours(os.path.abspath(record["path"]), record["line"], around)
    print(head(record) + f" · {record['path']}:{record['line']}")
    for message in before:
        print(T.nearby_line(message, _cut(_flat(message["text"]), 200)))
    text = (target or {"text": record["text"]})["text"]
    print("  ▶ " + (text if full else _cut(_flat(text), LINE_CHARS)))
    for message in after:
        print(T.nearby_line(message, _cut(_flat(message["text"]), 200)))
    print()


def open_locator(locator, around):
    """Open every stored message the locator names, with `around` messages on each side."""
    found = LOCATOR.match(locator)
    store = load()
    opened = 0
    for path, entry in store["files"].items():
        if short_id(path) != found.group(1):
            continue
        for stored in entry["records"]:
            record = _unpack(path, entry, stored)
            if record["line"] == int(found.group(2)):
                show_message(record, around)
                opened += 1
    if opened:
        return 0
    print(RECALL_STORE_NO_LOCATOR.format(locator=locator))
    return 1
