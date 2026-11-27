#!/usr/bin/env python3
"""Audit an assistant's memory index for lines that outlive the status they state.

Claude Code keeps a folder of memory files beside the session transcripts, with MEMORY.md as its
index. The folder is not state, but now.py check is the one measure the turn-end gate runs, so it
calls audit() with its own findings. Links are same-folder Markdown links: any file name case, an
optional #section anchor. Importing this module reads no file."""
import datetime
import hashlib
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C  # noqa: E402

CHECK_MEMORY_ROT = (
    "[rot candidate] {name}: project memory not updated for {age}d. Update it, or replace the "
    "changing part with a pointer to state/NOW.md"
)

_MEMORY_LINK = r"\]\(([^)#/\s]+\.md)(?:#[^)]*)?\)"
MEMORY_INDEX = "MEMORY.md"
# A file named *-index.md that the index links to is a sub-index; its links count as indexed.
SUB_INDEX_SUFFIX = "-index.md"
# A memory file whose front matter says it records project status, and the page it should point to.
PROJECT_MEMORY_MARK = "type: project"


def audit(memory_dir, add):
    """Report volatile index lines, index and file mismatches, and stale project memories.

    add(gated, ident, text) receives each finding. The words that mark a status that goes stale
    (a wait, a scheduled item) are the instance's own regular expressions in
    checks.volatile_index_words, none by default; a match is advisory, so ordinary words never
    block the turn-end gate."""
    index = os.path.join(memory_dir, MEMORY_INDEX)
    _volatile_index_lines(index, add)
    if os.path.exists(index):
        _index_mismatches(memory_dir, index, add)
    _stale_project_memories(memory_dir, add)


def _volatile_index_lines(index, add):
    words = C.check_config("volatile_index_words", [])
    words = [w for w in words if isinstance(w, str) and w] if isinstance(words, list) else []
    try:
        volatile = re.compile("|".join(words)) if words else None
    except re.error as e:
        add(False, "volatile-words-invalid",
            f"checks.volatile_index_words in {C.CONFIG_NAME} is not a valid pattern: {e}")
        return
    if not (volatile and os.path.exists(index)):
        return
    # A stray byte in a hand-edited memory file must not crash the turn-end gate.
    for i, line in enumerate(open(index, encoding="utf-8", errors="replace"), 1):
        if line.startswith("- ") and volatile.search(line):
            # The id names the linked file, not the line number, so moving the line keeps it.
            m = re.search(_MEMORY_LINK, line)
            key = m.group(1) if m else hashlib.sha1(line.strip().encode()).hexdigest()[:8]
            add(False, f"index-volatile:{key}",
                f"[volatile index] {MEMORY_INDEX}:{i} {line.strip()[:80]}")


def _index_mismatches(memory_dir, index, add):
    text = open(index, encoding="utf-8", errors="replace").read()
    files = {f for f in os.listdir(memory_dir) if f.endswith(".md") and f != MEMORY_INDEX}
    linked = set(re.findall(_MEMORY_LINK, text))
    # Links of one level of sub-indexes count as indexed; via names the sub-index of each.
    via = {}
    for sub in [x for x in linked if x.endswith(SUB_INDEX_SUFFIX) and x in files]:
        try:
            sub_text = open(os.path.join(memory_dir, sub), encoding="utf-8").read()
        except Exception as e:
            add(False, f"subindex-unreadable:{sub}", f"[sub-index unreadable] {sub}: {e}")
            continue
        for x in re.findall(_MEMORY_LINK, sub_text):
            if x not in linked:
                via.setdefault(x, sub)
    linked |= set(via)
    # The link pattern also sees links back to the index itself, which are not entries.
    linked.discard(MEMORY_INDEX)
    for f in sorted(files - linked):
        add(False, f"index-missing:{f}", f"[index missing] {f}: the file exists but no index line points to it")
    for f in sorted(linked - files):
        add(False, f"index-ghost:{f}",
            f"[ghost index] {f}: {via.get(f, MEMORY_INDEX)} has a line but the file does not exist")


def _stale_project_memories(memory_dir, add):
    """Project memories older than memory_rot_days that do not point to the state page."""
    for f in sorted(os.listdir(memory_dir)) if os.path.isdir(memory_dir) else []:
        path = os.path.join(memory_dir, f)
        if not f.endswith(".md") or f == MEMORY_INDEX:
            continue
        try:
            body = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if PROJECT_MEMORY_MARK not in body[:400]:
            continue
        age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days
        if age > C.threshold("memory_rot_days") and "state/NOW.md" not in body:
            add(False, f"memory-rot:{f}", CHECK_MEMORY_ROT.format(name=f, age=age))
