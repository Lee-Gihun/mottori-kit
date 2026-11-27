#!/usr/bin/env python3
"""Where the improvement loop may change files: the never list and the allowed area, defined here only.

A path the loop changes must be inside the allowed area (the harness), off the never list, and not a
file Git itself reads from the tree (a name that starts with .git). The engine fixes part of the never
list: the private area, the tool-written state folder, Git's own folder, the instance configuration,
which holds the loop's own settings, and the template that configuration is made from. The
installation adds entries in the configuration's loop.never (tools/loop/lib/loop_config.py); nothing
there removes one the engine fixes. The never list and this file's own name are compared in one form
(Unicode NFC, case folded), since the file system may take two spellings for one file. This module is
the definition of these lists, so a change to it is refused too.
Prompts and documents show the lists through render(). A root argument names the instance root;
without it, the tree this file lives in.

  python3 tools/loop/loop_policy.py     prints the two lists
"""
import fnmatch
import os
import subprocess
import sys
import unicodedata

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402
import loop_sources  # noqa: E402
import paths as P  # noqa: E402

ENGINE_NEVER = (P.tracked_name(P.private_area) + "/", P.tracked_name(P.state) + "/", ".git/",
                P.tracked_name(P.config_file), P.tracked_name(P.config_template))
# The harness. An entry ending in "/" is a folder; any other entry is one file.
ALLOWED = ("tools/", "system/", "templates/", "instance/", ".claude/", ".codex/", ".agents/",
           "AGENTS.md", "CLAUDE.md", "setup.sh")
DEFINITION = "tools/loop/loop_policy.py"
# The loop's own tools and their tests. At most one bundle per cycle may change only these. An entry
# with "*" is a file name pattern inside its folder, so every tools/loop/loop_<job>.py and
# tools/loop/lib/loop_<job>.py module and its
# tools/tests/test_loop_<job>.py test count without being listed one by one.
# An added source lists its own files under LOOP_FILES (tools/loop/sources/README.md).
LOOP_TOOLS = ("tools/loop/papers_apply.py", "tools/loop/papers_cycle.sh", "tools/loop/loops.py",
              "tools/loop/loop_*.py", "tools/loop/lib/loop_*.py", "tools/loop/papers/", "tools/loop/sources/",
              "tools/tests/test_papers_apply.py", "tools/tests/test_loop_*.py") + tuple(
    entry for _, entries in loop_sources.each("LOOP_FILES") for entry in entries)


def _within(path, entries):
    return any(path == e or (e.endswith("/") and path.startswith(e))
               or ("*" in e and path.count("/") == e.count("/") and fnmatch.fnmatchcase(path, e)) for e in entries)


def canonical(path):
    """The one form two spellings of a path are compared in: Unicode NFC, case folded."""
    return unicodedata.normalize("NFC", path).casefold()


def _within_canonical(path, entries):
    return _within(canonical(path), tuple(canonical(e) for e in entries))


def never(root=None):
    """The never list: the engine's entries, then this installation's additions."""
    return ENGINE_NEVER + tuple(e for e in loop_config.value("never", root) if e not in ENGINE_NEVER)


def refusal(path, root=None):
    """Why the loop may not change path, or None. path is a normalized path relative to the root."""
    if _within_canonical(path, never(root)):
        return f"on the never list: {path}"
    if canonical(path) == canonical(DEFINITION):
        return f"changes the definition of the never list and the allowed area: {path}"
    if canonical(path.rsplit("/", 1)[-1]).startswith(".git"):
        return f"a file Git itself reads from the tree: {path}"
    if not in_allowed_area(path):
        return f"outside the allowed area: {path}"
    return None


def tracked_alias(paths, root):
    """Why one of paths is another spelling of a tracked path or of another of paths, or None. When
    the tracked paths cannot be listed, that is the reason."""
    try:
        p = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True)
    except OSError as e:
        return f"the tracked paths could not be listed (git ls-files: {e})"
    if p.returncode != 0:
        return f"the tracked paths could not be listed (git ls-files ended {p.returncode})"
    listed = p.stdout
    spelled = {canonical(p): p for p in listed.decode("utf-8", "replace").split("\0") if p}
    seen = {}
    for path in paths:
        tracked = spelled.get(canonical(path))
        if tracked is not None and tracked != path:
            return f"another spelling of the tracked path {tracked}: {path}"
        if seen.setdefault(canonical(path), path) != path:
            return f"two spellings of one path: {seen[canonical(path)]}, {path}"
    return None


def in_allowed_area(path):
    """Whether path (a file, or a folder ending with /) is inside the allowed area."""
    return _within(path, ALLOWED)


def loop_only(files):
    """Whether every file is one of the loop's own tools or their tests."""
    return bool(files) and all(_within(f, LOOP_TOOLS) for f in files)


def _shown(entry):
    return f"`{entry}`"


def render(root=None):
    """The two lists as prompt text."""
    return (f"Never changed: {', '.join(_shown(e) for e in never(root))}, `{DEFINITION}` itself, and any file "
            "whose name starts with `.git`. "
            f"Changed only inside: {', '.join(_shown(e) for e in ALLOWED)}.")


if __name__ == "__main__":
    print(render())
