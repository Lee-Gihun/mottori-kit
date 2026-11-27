#!/usr/bin/env python3
"""Applies a worker's edit blocks safely: parses the blocks of its final answer and writes them only to
the bundle's files inside a tree, never through a link, and turns them into a patch in a clone. Every
file an edit wrote must be in the patch (Git leaves out a file it ignores), and the patch changes no
file mode: a new file is 0644 and an existing one keeps its mode."""
import os
import re
import stat
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_contracts as C  # noqa: E402
from loop_common import blob_hash, clip, git, normal_path  # noqa: E402


class UnsafeEdit(ValueError):
    """An edit refused for safety (path outside the bundle, link, hardlink, non-normal path).
    The refusal is final for the attempt; other ValueErrors from applying edits are retried."""


_HEADER = re.compile(r"^(" + re.escape(C.EDIT_FILE) + "|" + re.escape(C.EDIT_EDIT) + r") (\S+)\s*$")


def _until(lines, i, marker, what):
    """(lines from i up to the line equal to marker, the index after it); ValueError when it never comes."""
    body = []
    while i < len(lines) and lines[i] != marker:
        body.append(lines[i])
        i += 1
    if i >= len(lines):
        raise ValueError(f"{what}: no {marker}")
    return body, i + 1


def parse_edits(text):
    """Parse the complete file blocks and the edit blocks (search and replace) of text, each ending with C.EDIT_END."""
    edits, lines, i = [], (text or "").split("\n"), 0
    while i < len(lines):
        line = lines[i]
        m = _HEADER.match(line)
        if not m:
            # A malformed header would drop its block and let a partial implementation reach testing.
            if line.startswith(C.EDIT_MARK):
                raise ValueError(f"malformed edit block header: {clip(line, 80)}")
            i += 1
            continue
        header, path = m.groups()
        what = f"{header} {path}"
        i += 1
        if header == C.EDIT_FILE:
            body, i = _until(lines, i, C.EDIT_END, what)
            edits.append(("FILE", path, "\n".join(body) + "\n", None))
            continue
        if i >= len(lines) or lines[i] != C.EDIT_SEARCH:
            raise ValueError(f"{what}: no {C.EDIT_SEARCH}")
        search, i = _until(lines, i + 1, C.EDIT_REPLACE, what)
        repl, i = _until(lines, i, C.EDIT_END, what)
        edits.append(("EDIT", path, "\n".join(search), "\n".join(repl)))
    return edits


def safe_target(tree, path):
    """Before writing, reject symlink components and non-regular or multiply linked targets.
    Require the resolved path inside the tree; return (absolute path, existing stat or None)."""
    if not normal_path(path):
        raise UnsafeEdit(f"not a normalized path: {path}")
    real_tree = os.path.realpath(tree)
    cur = real_tree
    parts = path.split("/")
    for part in parts[:-1]:
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise UnsafeEdit(f"a component of the path is a link or not a folder: {path}")
    fp = os.path.join(real_tree, *parts)
    try:
        st = os.lstat(fp)
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise UnsafeEdit(f"the target is a symbolic link or not a regular file: {path}")
        if st.st_nlink != 1:
            raise UnsafeEdit(f"the target is shared by a hard link: {path}")
    if not os.path.realpath(os.path.dirname(fp)).startswith(real_tree + os.sep) and \
            os.path.realpath(os.path.dirname(fp)) != real_tree:
        raise UnsafeEdit(f"outside the tree: {path}")
    return fp, st


def write_nofollow(fp, data):
    """Write bytes to fp without following a link there; a new file is 0644, an existing one keeps its mode."""
    fd = os.open(fp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def apply_edits(tree, edits, allowed):
    for kind, path, a, b in edits:
        if path not in allowed:
            raise UnsafeEdit(f"edits a file outside the bundle: {path}")
        fp, st = safe_target(tree, path)
        if kind == "FILE":
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            fp, st = safe_target(tree, path)   # Recheck after creation.
            write_nofollow(fp, a.encode("utf-8"))
            continue
        if st is None:
            raise ValueError(f"no file to edit: {path}")
        fd = os.open(fp, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, encoding="utf-8") as f:
            cur = f.read()
        n = cur.count(a) if a else 0
        if n != 1:
            raise ValueError(f"edit {path}: the search text occurs {n} times (it must occur exactly once)")
        write_nofollow(fp, cur.replace(a, b, 1).encode("utf-8"))


def add_new_files(tree):
    """Mark the clone's untracked files as intended to add, so a diff shows them; return them."""
    untracked = git(["ls-files", "--others", "--exclude-standard", "-z"], tree).stdout
    new_files = [p for p in untracked.decode("utf-8", "replace").split("\0") if p]
    if new_files:
        git(["add", "-N", "--", *new_files], tree)
    return new_files


def mode_change(patch):
    """The first path whose file mode the patch bytes change, or None; a new file must be 100644."""
    path = None
    for line in patch.decode("utf-8", "replace").splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1]
        elif line.startswith(("old mode ", "new mode ")) or (line.startswith("new file mode ")
                                                             and line != "new file mode 100644"):
            return path
    return None


def build_candidate(iso, edits, files):
    """Apply edits in the clone and return patch bytes, changed paths, new paths, and expected hashes.
    UnsafeEdit when a written file is not in the patch or the patch changes a file mode."""
    apply_edits(iso.tree, edits, set(files))
    new_files = add_new_files(iso.tree)
    patch = git(["diff", "HEAD", "--binary"], iso.tree).stdout
    changed = [p for p in git(["diff", "HEAD", "--name-only", "-z"], iso.tree).stdout
               .decode("utf-8", "replace").split("\0") if p]
    tracked = set(git(["ls-files", "-z", "--", *{e[1] for e in edits}], iso.tree).stdout.decode("utf-8", "replace")
                  .split("\0"))
    left_out = sorted({path for _, path, _, _ in edits if path not in changed and path not in tracked})
    if left_out:
        raise UnsafeEdit("written by an edit but not in the patch (Git ignores it): " + ", ".join(left_out))
    moved = mode_change(patch)
    if moved:
        raise UnsafeEdit(f"the patch changes a file mode: {moved}")
    expected = {p: blob_hash(iso.tree, p) for p in changed}
    return patch, changed, new_files, expected
