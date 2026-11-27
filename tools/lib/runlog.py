#!/usr/bin/env python3
"""Keep the kit's diagnostic logs: the record of explicit checker runs, which doctor reads to tell
whether a check passed at this content, and the hook-failure log that hook.sh appends to.

Journals and user records are never trimmed here. Importing this module reads no file."""
import datetime
import hashlib
import os
import re
import subprocess
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths  # noqa: E402
import safeio  # noqa: E402

LOG_MAX_BYTES = 256 * 1024

# One hook failure is one line that starts with a timestamp; stderr a wrapper appends (a
# traceback) is not. doctor and the SessionStart notice share this so their counts agree.
HOOK_ERROR_ENTRY = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?")


# The words after the timestamp of a step that is not required and ran past its budget. Such a
# line is kept and counted like any failure, but the session start does not announce it.
HOOK_OVERRAN = "hook overran"


def hook_error_entries(text):
    """Return the failure lines of state/.hook-errors.log text, in order."""
    return [line for line in text.splitlines() if HOOK_ERROR_ENTRY.match(line)]


def overran(entry):
    """Whether a failure line records an optional step past its budget, not a failure to announce."""
    found = HOOK_ERROR_ENTRY.match(entry)
    return bool(found) and entry[found.end():].lstrip().startswith(HOOK_OVERRAN)


def trim_log(path, max_bytes=LOG_MAX_BYTES):
    """Keep the newer half of a diagnostic log grown past max_bytes; return the bytes dropped."""
    try:
        size = os.path.getsize(path)
        if size <= max_bytes:
            return 0
        with open(path, "rb") as f:
            f.seek(size - max_bytes // 2)
            tail = f.read()
        # Start on a whole line so the first kept entry is not a fragment. Keep the raw bytes: a
        # decoded copy changes length, and the hook error cursor is a byte offset.
        kept = tail[tail.find(b"\n") + 1:]
        safeio.atomic_write(path, kept)
        return size - len(kept)
    except OSError:
        return 0


def index_hash():
    """Hash the staged Git index identity (not working-tree content), independent of commit identity."""
    try:
        out = subprocess.run(["git", "ls-files", "-s"], capture_output=True, text=True,
                             cwd=paths.instance_root()).stdout
        return hashlib.sha1(out.encode()).hexdigest()[:12] if out else "-"
    except Exception:
        return "-"


def log_run(tool, result="", scope=None, ok=None):
    """Record one explicit checker run: time, tool, content identity, result and ok/ng/-.

    A run under MOTTORI_INTERNAL_RUN is not recorded, so doctor inspecting the evidence cannot
    create it. scope is the checker's own input hash; without one the Git index hash stands in.
    A failure to record never stops the checker."""
    if os.environ.get("MOTTORI_INTERNAL_RUN"):
        return
    try:
        runs = paths.tool_runs()
        os.makedirs(os.path.dirname(runs), exist_ok=True)
        ts = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        # Truncated once here: ran_at_head compares 12 characters.
        head = (scope or index_hash())[:12]
        # One lock over trim and append: a trim replaces the file, and without the lock it could
        # replace a line another session appended a moment earlier. It is not the state lock, so
        # a Stop hook never waits on another session's render and drops its row.
        with safeio.locked(runs + ".lock"):
            trim_log(runs)
            with open(runs, "a", encoding="utf-8") as f:
                f.write(f"{ts}\t{tool}\t{head}\t{result}\t{'ok' if ok else 'ng' if ok is not None else '-'}\n")
    except Exception:
        pass


def rows():
    """The log's rows as [time, tool, content hash, result, ok|ng|-]; several writers append, so
    a stray byte must not crash a reader."""
    if not os.path.exists(paths.tool_runs()):
        return []
    with open(paths.tool_runs(), encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n").split("\t") for line in f]


def last_run(tool):
    """Return the last (timestamp, content hash) of tool, or (None, None) when absent."""
    hit = (None, None)
    for parts in rows():
        if len(parts) >= 3 and parts[1] == tool:
            hit = (parts[0], parts[2])
    return hit


def ran_at_head(tool, head, require_ok=True):
    """Return whether tool ran against this content identity; a failed run counts only when
    require_ok is false, because a failed run is not verification."""
    if not head or head == "-":
        return False
    return any(len(parts) >= 3 and parts[1] == tool and parts[2] == head[:12]
               and (not require_ok or (len(parts) >= 5 and parts[4] == "ok"))
               for parts in rows())
