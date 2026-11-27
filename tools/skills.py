#!/usr/bin/env python3
"""Copy each skill from its one source folder to the folders the runtimes read.

A skill's source is system/skills/<name>/: a SKILL.md and any files beside it. Claude Code reads
.claude/skills/<name>/ and Codex and Antigravity read .agents/skills/<name>/, so each of those holds
a byte-for-byte copy of the source folder. A folder there with no source of the same name is the
owner's own skill and is left alone. Hidden files are not copied.

Usage: python3 tools/skills.py check | write
check prints each copied file that is missing, extra or different, then exits 1; when every copy
matches it prints nothing and exits 0. write makes every copy match and prints each file it wrote
or removed.
"""
import os
import pathlib
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P  # noqa: E402
import safeio  # noqa: E402

SOURCE = P.tracked_name(P.skills)
COPIES = P.SKILL_COPIES
FIX = "python3 tools/skills.py write"


def _files(folder):
    """Map each file under folder, as a path relative to it, to its bytes. Hidden names are skipped."""
    found = {}
    for path in sorted(pathlib.Path(folder).rglob("*")):
        rel = path.relative_to(folder)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        found[rel.as_posix()] = path.read_bytes()
    return found


def sources(root):
    """Map each skill name to its files ({relative path: bytes}); {} when there is no source folder."""
    base = pathlib.Path(root) / SOURCE
    if not base.is_dir():
        return {}
    return {d.name: _files(d) for d in sorted(base.iterdir())
            if d.is_dir() and not d.name.startswith(".")}


def differences(root):
    """List (kind, path) for each copied file that is "missing", "extra" or "different", path
    relative to root, in a stable order."""
    root = pathlib.Path(root)
    found = []
    for name, files in sources(root).items():
        for copy in COPIES:
            folder = root / copy / name
            have = _files(folder) if folder.is_dir() else {}
            for rel in sorted(set(files) | set(have)):
                path = f"{copy}/{name}/{rel}"
                if rel not in have:
                    found.append(("missing", path))
                elif rel not in files:
                    found.append(("extra", path))
                elif have[rel] != files[rel]:
                    found.append(("different", path))
    return found


def write(root):
    """Make every copy match its source; return the (kind, path) pairs that were fixed."""
    root = pathlib.Path(root)
    fixed = differences(root)
    all_sources = sources(root)
    for kind, path in fixed:
        target = root / path
        # Each COPIES entry has two parts, so the third part of path is the skill's name.
        name, rel = path.split("/", 3)[2:]
        if kind == "extra":
            target.unlink()
            # Remove folders the removal left empty, keeping the skill's own folder.
            skill_folder, parent = target.parents[len(pathlib.Path(rel).parts) - 1], target.parent
            while parent != skill_folder and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            continue
        source = root / SOURCE / name / rel
        safeio.atomic_write(str(target), all_sources[name][rel],
                            mode=os.stat(source).st_mode & 0o777)
    return fixed


def main(argv):
    root = P.instance_root()
    if argv in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv == ["write"]:
        for kind, path in write(root):
            print(("removed " if kind == "extra" else "wrote ") + path)
        return 0
    if argv != ["check"]:
        print("usage: python3 tools/skills.py check | write", file=sys.stderr)
        return 2
    found = differences(root)
    for kind, path in found:
        print(f"{kind} {path}")
    if found:
        print(f"-> {FIX}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
