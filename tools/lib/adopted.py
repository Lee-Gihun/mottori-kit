"""The link issues an adopted folder already had when it came into the workspace.

`tools/adopt.py` writes the record and the turn-end check reads it: an issue listed here is not
counted against a turn that edits the file it sits in.
"""
import json
import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P  # noqa: E402


def read(root=None):
    """Return the record as a dict, or an empty one when it is missing or cannot be read."""
    try:
        with open(P.gate_adopted(root), encoding="utf-8") as source:
            raw = json.load(source)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def covers(path, root=None):
    """Whether a path relative to the workspace root lies inside an adopted folder."""
    folders = read(root).get("folders")
    return isinstance(folders, dict) and any(path.startswith(name + "/") for name in folders)


def issue_ids(root=None):
    """Return the adopted link-issue IDs. An unreadable record adopts nothing, so the check then
    blocks on those links again instead of passing them unseen."""
    ids = read(root).get("linkcheck")
    if not isinstance(ids, list):
        return frozenset()
    return frozenset(i for i in ids if isinstance(i, str))


def retire(ids, root=None):
    """Drop issue IDs the turn end saw repaired, so a link broken again later is that turn's issue.

    A record that cannot be read or written is left as it is; the next turn end tries again."""
    data = read(root)
    listed = data.get("linkcheck")
    if not isinstance(listed, list):
        return
    kept = [i for i in listed if i not in set(ids)]
    if len(kept) == len(listed):
        return
    data["linkcheck"] = kept
    try:
        import safeio
        safeio.atomic_write(P.gate_adopted(root), json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        pass
