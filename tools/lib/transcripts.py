#!/usr/bin/env python3
"""Read the runtimes' session files of this instance as one stream of messages.

The session files are the ones the configuration's episodic_sources names: Claude Code project
records, Codex rollouts (plain, or compressed as .jsonl.zst and read through the zstd command),
Antigravity transcripts, and plain text files. select_sources picks the files that belong to this instance;
iter_messages reads them and yields one dict per message, marked with who wrote it ("user",
"assistant", "system", "summary", "agent" or "document"), with copies from forked or archived
sessions removed. recall.py, recall_literal.py, recall_store.py and eval_recall.py read
transcripts through this module, as do an instance's own tools that need the owner's words.

The module also holds what those readers print in common: the notices that say what the reader
left out, and the local time and neighbour line of a message, so each sentence is written once.
"""
import collections
import concurrent.futures
import contextlib
import functools
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import paths as P
import receipts as R
import safeio

# Sentences that say what the reader left out; recall.py and recall_store.py print them.
AGY_UNSCOPED = (
    "{count} Antigravity transcript(s) were not searched: the conversation index beside them "
    "does not place them in a folder, and nothing else in them names one. `--source agy "
    "--all-instances` reads them, together with the Antigravity conversations of other folders."
)
NO_TRANSCRIPTS = (
    "No Claude conversation records exist for this folder yet ({path}). Records of other "
    "projects are not searched."
)
MALFORMED_SKIPPED = (
    "Records skipped as malformed (not a JSON object, a wrongly typed session id or timestamp, "
    "a Codex session whose metadata names no usable working folder, or under --since a match "
    "whose time does not parse): {count}."
)
UNVERIFIED_FILES = (
    "{count} Claude record file(s) have no working-folder field, so they were included without "
    "confirming that they belong to this folder."
)
ZST_SKIPPED = (
    "{count} compressed Codex session file(s) (.jsonl.zst) were not searched because the zstd "
    "command is not installed."
)
ZST_UNREADABLE = (
    "{count} compressed Codex session file(s) (.jsonl.zst) could not be read with zstd and "
    "were not searched. They are tried again on the next run."
)

# Codex can store sessions compressed as *.jsonl.zst. Python reads zstd only from 3.14 on, so
# compressed files are streamed through the zstd command and never written out decompressed.
ZST_SUFFIX = ".zst"
# Session metadata of compressed files, keyed by path and checked against size and mtime so a
# rewritten file is read again. Reading the first line costs one zstd process per file, which
# took about 17 seconds for 5,000 sessions; the cache holds no message text and is safe to delete.
# It names the working folder of every Codex session on the machine, other projects included, so
# it belongs in the private state folder, which is never tracked.
CODEX_META_CACHE = P.recall_codex_meta()
# Bumped when the reader records something new about a session, so entries an older reader wrote
# are read again once instead of being trusted for good (archived files never change).
CODEX_META_VERSION = 2
# Spawning zstd is the cost of a cold metadata read, and the processes run independently.
META_READ_WORKERS = 8


# ------------------------------------------------------------------ time stamps


def instant(ts):
    """Return the aware time of a source stamp, or None when it does not parse.

    A stamp without a zone is read as UTC, the zone both runtimes write."""
    if not isinstance(ts, str):
        return None
    return C.parse_timestamp(ts) or C.parse_timestamp(ts + "Z")


def local_time(ts):
    """Display the full source timestamp in the machine's local timezone."""
    value = instant(ts)
    return value.astimezone().strftime("%m-%d %H:%M %Z") if value else ts


def nearby_line(message, excerpt, clock=True):
    """The line that shows a message next to a hit: when, who, and an excerpt of its text.

    Without clock the time is left out and the role is not padded, for the compact form."""
    if not clock:
        return f"    {message['role']} | {excerpt}"
    return f"    {local_time(message['timestamp'])} {message['role']:9s} | {excerpt}"


def mtime(fp):
    """The file's modification time, or 0 when it cannot be read."""
    try:
        return os.path.getmtime(fp)
    except OSError:
        return 0


# ------------------------------------------------------------------ compressed Codex files


_ZSTD_STARTS = {}
_CODEX_META = {}
# Compressed files whose first line zstd could not deliver in this run. They are reported and
# not cached, so a passing failure does not hide a session from later runs.
_UNREADABLE = set()
_DISK_META = None
_DISK_META_DIRTY = False


def _zstd():
    return shutil.which("zstd")


def _zstd_starts(zstd):
    """Whether the zstd found on PATH can be started at all, checked once per process.

    A file that is on PATH but cannot run (a broken link or interpreter line) would otherwise
    raise in the middle of the message read, where metadata from the cache never touched it."""
    if zstd not in _ZSTD_STARTS:
        try:
            subprocess.run([zstd, "-V"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10)
            _ZSTD_STARTS[zstd] = True
        except (OSError, subprocess.SubprocessError):
            _ZSTD_STARTS[zstd] = False
    return _ZSTD_STARTS[zstd]


def unreadable_count():
    """How many compressed files zstd could not read in this run; they were not searched."""
    return len(_UNREADABLE)


@contextlib.contextmanager
def _open_lines(fp):
    """Open a transcript for line reading, decompressing a .zst file through zstd on the fly."""
    if not fp.endswith(ZST_SUFFIX):
        with open(fp, encoding="utf-8", errors="replace") as f:
            yield f
        return
    proc = subprocess.Popen([_zstd() or "zstd", "-dcq", "--", fp], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    try:
        yield io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace")
    finally:
        # A reader that stops early leaves zstd blocked on a full pipe; stop it instead of waiting.
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def _zst_first_line(fp):
    """Return the first decompressed line of a .zst file, or None when zstd did not deliver it.

    A complete line came out of a working decompressor, so it is a property of the file even
    when it does not parse. Output that ends before a newline is trusted only when zstd exited
    cleanly; otherwise it may be a passing failure (zstd missing, cut off, or unable to start).
    """
    try:
        proc = subprocess.Popen([_zstd() or "zstd", "-dcq", "--", fp], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except OSError:
        return None
    try:
        line = proc.stdout.readline()
        if line.endswith(b"\n"):
            return line.decode("utf-8", "replace")
        # End of output before a newline: zstd has finished, so its exit status is final.
        return line.decode("utf-8", "replace") if proc.wait() == 0 else None
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()


# ------------------------------------------------------------------ Codex session metadata


def read_codex_meta(fp):
    """Return the parts of the first session_meta line that the reader uses, or an empty dict.

    The session's folder is the cwd of that line, a string that is an absolute path. A first line
    that names a folder any other way gives a dict marked malformed, which a scoped search skips
    and counts. A first line that does not parse gives an empty dict. A compressed file whose
    first line zstd could not deliver gives None, because zstd may fail only this time."""
    try:
        if fp.endswith(ZST_SUFFIX):
            line = _zst_first_line(fp)
            if line is None:
                return None
        else:
            with open(fp, encoding="utf-8", errors="replace") as f:
                line = f.readline()
        first = json.loads(line)
    except (OSError, ValueError):
        return {}
    p = first.get("payload") if isinstance(first, dict) else None
    if not isinstance(p, dict):
        return {}
    if first.get("type") != "session_meta":
        # A turn_context payload names the folder of one turn, not the session's.
        return {"malformed": True} if "cwd" in p else {}
    cwd = p.get("cwd")
    src = p.get("source") if isinstance(p.get("source"), dict) else {}
    meta = {"cwd": cwd, "id": p.get("id"),
            "identity": "subagent" if (p.get("thread_source") == "subagent"
                                       or "subagent" in src) else "user",
            "parent": p.get("parent_thread_id"),
            "boundary": p.get("subagent_history_start_ordinal")}
    if not (isinstance(cwd, str) and os.path.isabs(cwd)):
        meta.update(cwd=None, malformed=True)
    return meta


def _disk_meta():
    global _DISK_META
    if _DISK_META is None:
        try:
            with open(CODEX_META_CACHE, encoding="utf-8") as f:
                data = json.load(f)
            files = data.get("files") if isinstance(data, dict) else None
            _DISK_META = (files if data.get("version") == CODEX_META_VERSION
                          and isinstance(files, dict) else {})
        except (OSError, ValueError):
            _DISK_META = {}
    return _DISK_META


def _stamp(fp):
    try:
        st = os.stat(fp)
        return [st.st_size, st.st_mtime_ns]
    except OSError:
        return None


_realpath = functools.lru_cache(maxsize=None)(os.path.realpath)


def _cached_meta(fp):
    entry = _disk_meta().get(_realpath(fp))
    if isinstance(entry, list) and len(entry) == 2 and entry[0] == _stamp(fp):
        return entry[1]
    return None


def _codex_meta(fp):
    """Session metadata of one Codex rollout, through the memory and disk caches."""
    global _DISK_META_DIRTY
    if fp in _CODEX_META:
        return _CODEX_META[fp]
    meta = None
    if fp.endswith(ZST_SUFFIX):
        meta = _cached_meta(fp)
    if meta is None:
        meta = read_codex_meta(fp)
        if meta is None:
            _UNREADABLE.add(fp)
            meta = {}
        elif fp.endswith(ZST_SUFFIX):
            _disk_meta()[_realpath(fp)] = [_stamp(fp), meta]
            _DISK_META_DIRTY = True
    _CODEX_META[fp] = meta
    return meta


def _prefetch_codex_meta(files):
    """Read the metadata of every uncached compressed file in parallel, then save the cache.

    A cold first run stays short, and every file read in this run is in the cache it saves."""
    todo = [f for f in files if f.endswith(ZST_SUFFIX) and f not in _CODEX_META
            and _cached_meta(f) is None]
    if todo:
        with concurrent.futures.ThreadPoolExecutor(META_READ_WORKERS) as pool:
            list(pool.map(_codex_meta, todo))
    _save_disk_meta()


def _save_disk_meta():
    """Write the metadata cache, dropping entries for files that no longer exist."""
    global _DISK_META_DIRTY
    if not _DISK_META_DIRTY:
        return
    data = {k: v for k, v in _disk_meta().items() if os.path.exists(k)}
    try:
        # ASCII escapes keep a lone surrogate from a malformed session writable.
        safeio.atomic_write(CODEX_META_CACHE, json.dumps(
            {"version": CODEX_META_VERSION, "files": data}, ensure_ascii=True, separators=(",", ":")))
        _DISK_META_DIRTY = False
    except OSError:
        # The cache only saves time; a read-only state folder must not stop a search.
        pass


def session_identity(fp):
    """Return (kind, parent_id, boundary) of a Codex rollout from its session metadata.

    kind is "subagent" for a session the metadata marks as a subagent's, "user" for any other
    session_meta, and "unknown" without one. boundary is the one-based ordinal where a
    subagent's copy of its parent's history ends, or None when the metadata does not give it."""
    meta = _codex_meta(fp)
    return (meta.get("identity", "unknown"), meta.get("parent"), meta.get("boundary"))


# ------------------------------------------------------------------ which files are this instance's


def _same_instance(cwd):
    """True for an absolute working folder inside this instance or one of its root aliases.

    Any other value (a relative path, or a non-string from an older metadata cache) is False."""
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return False
    return _inside_instance(cwd)


# Thousands of sessions share a few folders, and resolving links of each took most of a search.
@functools.lru_cache(maxsize=None)
def _inside_instance(cwd):
    # Root aliases are the instance's earlier folders, so its records survive a rename.
    roots = [P.instance_root()] + C.root_aliases()
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


def file_unverified(fp):
    """True for a Claude file that was selected although no line of it names a working folder."""
    return _CLAUDE_FILE_CACHE.get(fp) == "unverified"


# Antigravity keeps one transcript per conversation under brain/<conversation id>/, and its rows
# name no folder; the conversation index beside brain/ holds each conversation's workspace_uris
# (system/dev/runtime-capture.md). The capture named only that column, so an index row is tied
# to a conversation by any of its values that equals a conversation id. A transcript the index
# does not place is skipped and counted.
_UNSCOPED = set()
_AGY_REQUEST = re.compile(r"<USER_REQUEST>\n?(.*?)\n?</USER_REQUEST>", re.S)


def agy_conversation(fp):
    """The conversation id of an Antigravity transcript: the folder three levels above it."""
    return os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(fp))))


def unscoped_count():
    """How many Antigravity transcripts were left out because the index does not place them."""
    return len(_UNSCOPED)


def _agy_workspaces(brain, ids):
    """Return {conversation id: [workspace folder]} for ids, or {} when the index cannot be read."""
    import sqlite3
    index = os.path.join(os.path.dirname(brain), "conversation_summaries.db")
    out = {}
    try:
        db = sqlite3.connect("file:" + urllib.parse.quote(index) + "?mode=ro", uri=True, timeout=1)
        try:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for (table,) in tables:
                _read_workspace_table(db, table, ids, out)
        finally:
            db.close()
    except sqlite3.Error:
        return {}
    return out


def _read_workspace_table(db, table, ids, out):
    """Add the workspace folders of one index table's rows to out, for the rows naming an id."""
    name = '"' + table.replace('"', '""') + '"'
    columns = [row[1] for row in db.execute(f"PRAGMA table_info({name})")]
    if "workspace_uris" not in columns:
        return
    for row in db.execute(f"SELECT * FROM {name}"):
        record = dict(zip(columns, row))
        try:
            uris = json.loads(record["workspace_uris"] or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(uris, list):
            continue
        folders = [urllib.parse.unquote(u[len("file://"):]) for u in uris
                   if isinstance(u, str) and u.startswith("file://")]
        for value in record.values():
            if isinstance(value, str) and value in ids:
                out.setdefault(value, []).extend(folders)


def _instance_claude_bases(kind, base):
    """[base] plus the root aliases' Claude folders when base is this instance's Claude store,
    else None. Only the instance's own store has aliases, never an unrelated custom source."""
    if kind != "claude-jsonl" or os.path.realpath(base) != os.path.realpath(P.transcripts()):
        return None
    return [base] + [P.transcripts(alias) for alias in C.root_aliases()]


def _candidate_files(kind, base, pat):
    """The files a registry row's glob matches, in its base and, for this instance's Claude
    store, in the stores of its root aliases; a Codex row also matches compressed files."""
    bases = _instance_claude_bases(kind, base) or [base]
    pats = [pat]
    if kind == "codex-jsonl" and pat.endswith(".jsonl"):
        pats.append(pat + ZST_SUFFIX)
    fs = []
    for candidate in bases:
        if os.path.isdir(candidate):
            for one in pats:
                fs.extend(glob.glob(os.path.join(candidate, one), recursive=True))
    return fs


# What select_sources found: rows of (name, kind, path, owner_checked), and the counts of Claude
# files kept without a working folder, of compressed files skipped without zstd, and of Codex
# sessions skipped as malformed.
Selection = collections.namedtuple("Selection", "rows unverified zst_skipped malformed")


def select_sources(names, all_instances=False):
    """Return the Selection of the session files that belong to this instance.

    Codex storage is machine-wide, so it is filtered by the rollout's working folder. The
    instance's Claude store is filtered by the working folders its records name, because the
    store name alone can be shared with another folder. Both filters are skipped only when
    all-instances access was explicitly requested. owner_checked marks the Claude files whose
    lines iter_messages must still match to this instance session by session.
    """
    out, seen = [], set()
    unverified = skipped = malformed = 0
    zstd = _zstd()
    for name, kind, base, pat in C.episodic_sources():
        if names and name not in names:
            continue
        instance_claude = _instance_claude_bases(kind, base) is not None
        fs = _candidate_files(kind, base, pat)
        if not zstd:
            kept = [f for f in fs if not f.endswith(ZST_SUFFIX)]
            skipped += len(fs) - len(kept)
            fs = kept
        elif any(f.endswith(ZST_SUFFIX) for f in fs) and not _zstd_starts(zstd):
            # Reported as unreadable, not as missing: the command exists and may work next run.
            _UNREADABLE.update(f for f in fs if f.endswith(ZST_SUFFIX))
            fs = [f for f in fs if not f.endswith(ZST_SUFFIX)]
        # A dangling link or a file removed since the glob is not a transcript to read.
        fs = [f for f in fs if os.path.isfile(f)]
        fs.sort(key=lambda p: (mtime(p), p))
        if kind == "codex-jsonl":
            _prefetch_codex_meta(fs)
        if kind == "codex-jsonl" and not all_instances:
            malformed += sum(1 for f in fs if _codex_meta(f).get("malformed"))
            # The rollout's working directory comes from its first session_meta payload.
            fs = [f for f in fs if _same_instance(_codex_meta(f).get("cwd"))]
        if kind == "agy-jsonl" and not all_instances:
            spaces = _agy_workspaces(base, {agy_conversation(f) for f in fs})
            _UNSCOPED.update(f for f in fs if agy_conversation(f) not in spaces)
            fs = [f for f in fs if any(_same_instance(p) for p in spaces.get(agy_conversation(f), ()))]
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
    return Selection(out, unverified, skipped, malformed)


def source_files(names, all_instances=False):
    """Return the selected source files as (name, kind, path); see select_sources."""
    return [(name, kind, f) for name, kind, f, _checked in select_sources(names, all_instances).rows]


def missing_claude_store(names):
    """Return this instance's Claude transcript path when it is selected but absent everywhere.

    The caller says so instead of letting an empty result look like a searched-but-empty store.
    """
    if names and "claude" not in names:
        return None
    for name, kind, base, _pat in C.episodic_sources():
        if names and name not in names:
            continue
        bases = _instance_claude_bases(kind, base)
        if bases is not None and not any(os.path.isdir(b) for b in bases):
            return base
    return None


# ------------------------------------------------------------------ the text of one row


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
    r"|^\s*## Page contract — read before your first publish"
    # Claude Code writes this line itself, as a user row, when a person stops a turn.
    r"|^\s*\[Request interrupted by user",
    re.I)


def _is_system_injected(text):
    return bool(_SYS_INJECT.search(text or ""))


# Openers of messages that an agent sent, not the owner: the first line of every worker prompt the
# kit writes, a receipt handed back (FRESH_WORKER), a message from another Claude session, and the
# dispatch prefix, also in the Korean form that transcripts written while the kit spoke Korean
# carry. An instance adds the openers of its own prompts in instance.agent_openers.
_KIT_OPENERS = (R.CONTRACT_HEADER, "Another Claude session sent a message:",
                "[Claude Code requested", "[Claude Code가")
AGENT_TRANSPORT = re.compile(
    r"^\s*(?:" + "|".join(re.escape(opener) for opener in _KIT_OPENERS) + r"|FRESH_WORKER\b)",
    re.I)


@functools.lru_cache(maxsize=None)
def _instance_openers():
    """The instance's own openers as one pattern matched at the start, or None without any."""
    patterns = C.agent_openers()
    if not patterns:
        return None
    return re.compile(r"^\s*(?:" + "|".join(f"(?:{p})" for p in patterns) + ")", re.I)


def _sent_by_agent(text):
    """True for a message that opens with the words of a prompt an agent sent."""
    configured = _instance_openers()
    return bool(AGENT_TRANSPORT.search(text) or (configured and configured.search(text)))


_USER_ENVELOPE = re.compile(
    r"^\s*<(in-app-browser-context|environment_context|app-context|recommended_plugins"
    r"|codex_internal_context|user_instructions)\b"
    r"[^>]*>.*?</\1>\s*", re.S)


# Claude Code records a slash command as one user row of three wrappers. The command is the
# runtime's; what the owner typed after it, in command-args, is theirs.
_SLASH_COMMAND = re.compile(
    r"^\s*<command-name>[^<]*</command-name>\s*<command-message>.*?</command-message>"
    r"\s*<command-args>(.*)</command-args>\s*$", re.S)


def _typed_args(text):
    """The text the owner typed after a slash command, or text unchanged for any other row and
    for a command typed without words, which stays an injected row."""
    found = _SLASH_COMMAND.match(text)
    return found.group(1).strip() if found and found.group(1).strip() else text


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


def text_of_agy(d, include_thinking=False):
    """Extract (role, text) from an Antigravity transcript row: the typed request, the model's
    answer, or a system row (a compaction checkpoint or a system message)."""
    kind, content = d.get("type"), d.get("content")
    if kind == "USER_INPUT" and isinstance(content, str):
        found = _AGY_REQUEST.search(content)
        return ("user", found.group(1) if found else content)
    if kind == "PLANNER_RESPONSE":
        parts = [content] + ([d.get("thinking")] if include_thinking else [])
        text = "\n".join(p for p in parts if isinstance(p, str) and p)
        return ("assistant", text) if text else None
    if d.get("source") == "SYSTEM" and isinstance(content, str):
        return ("user", content)
    return None


def text_of_codex(d):
    """Extract (role, text) from a Codex response_item message."""
    if d.get("type") != "response_item":
        return None
    p = d.get("payload")
    if not isinstance(p, dict) or p.get("type") != "message" or p.get("role") not in (
            "user", "assistant") or not isinstance(p.get("content"), list):
        return None
    parts = [b.get("text") for b in p["content"]
             if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")
             and isinstance(b.get("text"), str)]
    text = "\n".join(x for x in parts if x)
    if p["role"] == "user":
        text = _unwrap_user(text)
    return (p["role"], text) if text else None


def text_of_claude(d, include_thinking=False):
    """Extract (role, text) from a Claude record row: a user or assistant message, or a message
    typed while the assistant was working; None for any other row. Tool results are left out."""
    t = d.get("type")
    attachment = d.get("attachment")
    if (t == "attachment" and isinstance(attachment, dict)
            and attachment.get("type") == "queued_command"):
        # A message typed while the assistant was working is stored only here, never again as a
        # user row; its origin, checked by the caller, says whether a person typed it.
        prompt = attachment.get("prompt")
        if isinstance(prompt, list):
            prompt = " ".join(b.get("text") for b in prompt if isinstance(b, dict)
                              and b.get("type") == "text" and isinstance(b.get("text"), str))
        return ("user", _unwrap_user(prompt)) if isinstance(prompt, str) and prompt else None
    if t not in ("user", "assistant"):
        return None
    m = d.get("message")
    if not isinstance(m, dict):
        return None
    c = m.get("content")
    if t == "user":
        if isinstance(c, str):
            return ("user", _typed_args(_unwrap_user(c)))
        if isinstance(c, list):
            parts = [b.get("text") or b.get("content") for b in c if isinstance(b, dict)
                     and b.get("type") == "text"]
            joined = " ".join(p for p in parts if isinstance(p, str))
            return ("user", _typed_args(_unwrap_user(joined))) if joined else None
        return None
    parts = []
    if isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(b.get("text"))
            elif include_thinking and b.get("type") == "thinking":
                parts.append(b.get("thinking"))
    parts = [p for p in parts if isinstance(p, str)]
    return ("assistant", "\n".join(p for p in parts if p)) if parts else None


def _parse_line(kind, d, thinking):
    """Return (role, text, native message id) of one parsed row, or None for a row without text."""
    if kind == "codex-jsonl":
        got = text_of_codex(d)
        return got and (*got, (d.get("payload") or {}).get("id"))
    if kind == "agy-jsonl":
        got = text_of_agy(d, include_thinking=thinking)
        return got and (*got, str(d.get("step_index")))
    got = text_of_claude(d, include_thinking=thinking)
    return got and (*got, d.get("uuid"))


def _origin_kind(d):
    """Return who a Claude row says produced it ("human", "task-notification", "peer", ...), or
    None for rows written before the runtime recorded it."""
    holder = d.get("attachment") if d.get("type") == "attachment" else d
    origin = holder.get("origin") if isinstance(holder, dict) else None
    kind = origin.get("kind") if isinstance(origin, dict) else None
    return kind if isinstance(kind, str) else None


def _classify(kind, d, role, text, file_kind):
    """Return (role, origin) of a row with text: who wrote it, read from the row's own markers.

    The runtime's own markers come first (a checkpoint, a summary, a recorded origin, a tool
    result, a meta flag); the text's opening words decide only for a row without one."""
    message = d.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    tool_transport = (isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content))
    if kind == "agy-jsonl" and d.get("type") == "CHECKPOINT":
        return "summary", "summary"
    if kind == "agy-jsonl" and d.get("source") == "SYSTEM":
        return role, "system"
    if d.get("isCompactSummary") or text.startswith(
            "This session is being continued from a previous conversation"):
        return "summary", "summary"
    if kind == "claude-jsonl" and _origin_kind(d) not in (None, "human"):
        # The runtime names what wrote the row (a task notification, another session, an
        # automatic continuation); none of them is the owner typing.
        return role, "agent" if _origin_kind(d) == "peer" else "system"
    if tool_transport or (kind == "claude-jsonl" and d.get("isMeta") is True):
        # Claude records hook feedback in user-role messages. Trust its explicit transport
        # flag, not words that a person may also quote in an ordinary request.
        return role, "system"
    if role == "user" and _is_system_injected(text):
        return role, "system"
    if role == "user" and _sent_by_agent(text):
        return role, "agent"
    if file_kind == "subagent":
        return role, "agent"
    return role, role


def _claude_line_session(d, session_id):
    """The session a Claude row belongs to, or None when its id has the wrong type.

    A row without an id belongs to the session being written, which is the file's name only
    until a row names another one. A numeric id is read as its text, so it compares and hashes
    like any other id; a zero id counts as no id."""
    line_id = d.get("sessionId")
    if isinstance(line_id, (int, float)) and not isinstance(line_id, bool) and line_id:
        line_id = str(line_id)
    line_session = line_id or session_id
    return line_session if isinstance(line_session, str) else None


# ------------------------------------------------------------------ the message stream


def _count_malformed(scan):
    if scan is not None:
        scan["malformed"] = scan.get("malformed", 0) + 1


def _encodable(value):
    """Replace lone surrogates, which a JSON escape can carry but UTF-8 output cannot encode.

    Record ids are hashed from UTF-8 and hits are printed, so one malformed session would
    otherwise stop the whole search."""
    if not isinstance(value, str):
        return value
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        # An escape, not U+FFFD: two different lone surrogates must stay two different ids.
        return value.encode("utf-8", "backslashreplace").decode("utf-8")


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
    # A forked session copies earlier owner messages into a new file under a new session id; the
    # same text at the same instant was typed once.
    typed = (("typed", record["timestamp"], record["text"])
             if record["origin"] == "user" and record["timestamp"] else None)
    if typed in seen:
        return False
    if typed:
        seen.add(typed)
    seen.add(record_id)
    record["record_id"] = record_id
    return True


def _file_session_id(kind, path):
    """The session id a file's rows belong to until a row names another one."""
    session_id = os.path.basename(path).removesuffix(ZST_SUFFIX).removesuffix(".jsonl")
    if kind == "codex-jsonl":
        session_id = _codex_meta(path).get("id") or session_id
    elif kind == "agy-jsonl":
        session_id = agy_conversation(path)
    return _encodable(session_id)


def _record(source, kind, path, line_number, session_id, native_id, stamp, role, origin, text):
    # Every string the record id hashes or the output prints is made encodable.
    return {"source": source, "kind": kind, "path": os.path.abspath(path),
            "line": line_number, "session_id": _encodable(session_id),
            "message_id": _encodable(native_id), "record_id": None,
            "timestamp": _encodable(stamp), "role": role,
            "origin": origin, "text": _encodable(text)}


def _row_record(row, d, line_number, session_id, flags, scan):
    """The record of one parsed JSON row, or None for a row that is skipped or malformed."""
    source, kind, path, file_kind = row
    got = _parse_line(kind, d, flags["thinking"])
    if not got:
        return None
    role, text, native_id = got
    stamp = d.get("created_at" if kind == "agy-jsonl" else "timestamp") or ""
    if not isinstance(stamp, str):
        _count_malformed(scan)
        return None
    role, origin = _classify(kind, d, role, text, file_kind)
    return _record(source, kind, path, line_number, session_id, native_id, stamp, role, origin,
                   text)


def _file_messages(row, owner_checked, seen, scan, resume, flags):
    """Yield the new eligible records of one file, in line order.

    For files whose store name may be shared with another folder, a record belongs to this
    instance when the first working folder its session names is this instance's. A session's
    lines read before that folder is known wait in held[session]; a session that never names one
    is dropped. The first folder is the one the session started in, so a session that later moved
    to another working folder keeps its owner's lines."""
    source, kind, path, _file_kind = row
    session_owner, held = {}, {}
    session_id = _file_session_id(kind, path)
    start = (resume or {}).get(path)
    with contextlib.ExitStack() as stack:
        try:
            f = stack.enter_context(_open_lines(path))
            if start:
                f.seek(start[0])
        except OSError:
            return  # Removed or made unreadable after it was selected.
        for line_number, line in enumerate(f, start[1] + 1 if start else 1):
            if kind == "text":
                record = _record(source, kind, path, line_number, session_id, str(line_number),
                                 "", "document", "document", line.rstrip("\n"))
            else:
                try:
                    d = json.loads(line)
                except (ValueError, TypeError):
                    d = None
                if not isinstance(d, dict):
                    _count_malformed(scan)
                    continue
                if kind not in ("codex-jsonl", "agy-jsonl"):
                    line_session = _claude_line_session(d, session_id)
                    if line_session is None:
                        _count_malformed(scan)
                        continue
                    session_id = line_session
                    if owner_checked and session_id not in session_owner:
                        yield from _settle_owner(d, session_id, session_owner, held, seen)
                record = _row_record(row, d, line_number, session_id, flags, scan)
                if record is None:
                    continue
            if not _wanted(record, flags):
                continue
            if owner_checked:
                # Keyed by the session id as the file wrote it, as _settle_owner keys it.
                owned = session_owner.get(session_id)
                if owned is None:
                    held.setdefault(session_id, []).append(record)
                    continue
                if not owned:
                    continue
            if _keep_new(record, seen):
                yield record


def _settle_owner(d, session, session_owner, held, seen):
    """Decide a session's owner from the first row that names its working folder, and yield
    the rows held until then when the session is this instance's.

    They are released here, not with the next eligible row: the row that names the folder may
    carry no text, or the session may end there."""
    cwd = d.get("cwd")
    if not (isinstance(cwd, str) and cwd):
        return
    session_owner[session] = _same_instance(cwd)
    released = held.pop(session, [])
    if session_owner[session]:
        for item in released:
            if _keep_new(item, seen):
                yield item


def _wanted(record, flags):
    """Whether a record is shown under the caller's include flags; empty text never is."""
    if record["origin"] in ("system", "summary") and not flags["include_system"]:
        return False
    if record["origin"] == "agent" and not flags["include_agents"]:
        return False
    return bool(record["text"])


def iter_messages(sources=None, *, all_instances=False, include_agents=False,
                  include_system=False, thinking=False, paths=None, scan_seconds=None,
                  oldest_first=False, scan=None, resume=None, selection=None):
    """Yield the messages of the selected session files, one record dict each.

    Eligibility and native-message deduplication happen before any consumer ranks or counts
    records. A user-role message is not proof that every quoted claim inside it was authored
    or approved by the owner. Known machine envelopes have explicit origins and are excluded
    by default; include_system and include_agents keep them.

    Sources are selected once per call, and scan receives the selection's counts ("unverified",
    "skipped", "malformed"). A row that is not a JSON object, or whose session id or timestamp
    has the wrong type, is skipped and counted in scan["malformed"] as well.

    With scan_seconds, files are read newest first, or oldest first with oldest_first. No file
    is opened once that many seconds have passed after source selection. The first file is
    read even so. scan["unread"] receives the number of files left unread.

    resume maps a plain file to (byte offset, line number) of a line start, so a reader that
    remembers how far it got reads only what was added. selection reuses one select_sources
    result for calls that read one file each.
    """
    seen = set()
    flags = {"thinking": thinking, "include_system": include_system,
             "include_agents": include_agents}
    if selection is None:
        selection = select_sources(sources, all_instances)
    selected = list(selection.rows)
    if scan is not None:
        scan.update(unverified=selection.unverified, skipped=selection.zst_skipped,
                    malformed=scan.get("malformed", 0) + selection.malformed)
    if paths is not None:
        selected = [row for row in selected if row[2] in paths]
    # A compressed file whose first line zstd could not deliver was reported as not searched;
    # reading its messages would fail the same way, or stop the search when zstd cannot start.
    selected = [row for row in selected if row[2] not in _UNREADABLE]
    if not include_agents:
        # Dropped before reading so the unread count below covers only sessions it would read.
        selected = [row for row in selected
                    if row[1] != "codex-jsonl" or session_identity(row[2])[0] != "subagent"]
    deadline = None
    if scan_seconds is not None:
        # Started after selection: a cold metadata read must not use up the time for messages.
        deadline = time.monotonic() + scan_seconds
        selected.sort(key=lambda row: mtime(row[2]), reverse=not oldest_first)
    if scan is not None:
        scan["read"] = 0
    for position, (source, kind, path, owner_checked) in enumerate(selected):
        if deadline is not None and position and time.monotonic() > deadline:
            if scan is not None:
                scan.update(read=position, unread=len(selected) - position)
            return
        if scan is not None:
            scan["read"] = position + 1
        file_kind = session_identity(path)[0] if kind == "codex-jsonl" else "user"
        yield from _file_messages((source, kind, path, file_kind), owner_checked, seen, scan,
                                  resume, flags)
