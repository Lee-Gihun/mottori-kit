#!/usr/bin/env python3
"""Take a folder of existing material into the workspace as it is.

Usage:
  python3 tools/adopt.py FOLDER           Adopt the folder: record, report, write the inventory
  python3 tools/adopt.py FOLDER --dry     Print the same report and write nothing
  python3 tools/adopt.py FOLDER --again   Adopt it again as it is now, with links broken since
  python3 tools/adopt.py                  List the adopted folders

FOLDER is inside this workspace: move or copy your documents in first, whole. A code repository
stays where it is and is added to the session instead (--add-dir in each runtime). The tool
moves, renames and edits nothing. It does three things:

  1. Records the links that are already broken in the folder's Markdown. The turn-end check then
     stops a turn only for a link the turn broke, not for one the folder came in with. A second
     run drops the links that have been fixed and records no link broken since the first, so
     running it again does not silence a turn's own breakage; --again is the owner's way to
     accept the folder as it is now.
  2. Names what needs a person's eye: instruction files inside the folder, which a runtime reads
     when it works there, and Git repositories inside it.
  3. Writes an inventory page under the private state folder, so an agent can propose tracks
     from one page instead of reading the folder.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import adopted  # noqa: E402
import paths as P  # noqa: E402
import safeio  # noqa: E402

# Folders the kit or its state owns, whose documents are already checked or never checked, and
# folders never walked into.
OWN, SKIP = P.KIT_OWNED, P.NEVER_WALKED
# Files and folders a runtime reads as instructions when it works in the folder that holds them.
INSTRUCTIONS = {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".cursorrules",
                ".claude", ".codex", ".agents", ".cursor"}
# The inventory is one page an agent reads whole, so each list is cut and says what it left out.
MAX_CHILDREN = 40
MAX_DOCUMENTS = 150
HEADING_CHARS = 80

REFUSE_OUTSIDE = (
    "adopt: {path} is not inside this workspace ({root}). Move or copy the folder into projects/ "
    "first, whole, for example: mv {path} {root}/projects/"
)
REFUSE_REPOSITORY = (
    "adopt: {path} is a Git repository outside this workspace. Leave it where it is: its paths, "
    "its tooling and its remote stay as they are. Open the agent here and add the repository to "
    "the session, for example: claude --add-dir {path}"
)
REFUSE_OWN = "adopt: {rel} belongs to the kit or to its state; adopt a folder of your own material."
REFUSE_ROOT = "adopt: name a folder of your own material inside the workspace, not the workspace itself."
REFUSE_MISSING = "adopt: no such folder: {path}"


def _rel_folder(argument, root):
    """Return FOLDER as a path relative to the workspace root, or exit with the reason."""
    path = os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(argument)))
    real_root = os.path.realpath(root)
    if not os.path.isdir(path):
        sys.exit(REFUSE_MISSING.format(path=argument))
    if path == real_root:
        sys.exit(REFUSE_ROOT)
    if not path.startswith(real_root + os.sep):
        refusal = REFUSE_REPOSITORY if os.path.exists(os.path.join(path, ".git")) else REFUSE_OUTSIDE
        sys.exit(refusal.format(path=argument.rstrip("/"), root=root))
    rel = os.path.relpath(path, real_root).replace(os.sep, "/")
    if rel.split("/")[0] in OWN:
        sys.exit(REFUSE_OWN.format(rel=rel))
    return rel


def _first_heading(path):
    """Return the first Markdown heading of a file, or "" when it has none or cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as source:
            for _ in range(40):
                line = source.readline()
                if not line:
                    break
                if line.startswith("#"):
                    return line.lstrip("#").strip()[:HEADING_CHARS]
    except OSError:
        pass
    return ""


def survey(root, rel):
    """Walk the folder once and return what the report and the inventory need.

    Symbolic links are neither followed nor counted, so the walk stays inside the folder.
    """
    base = os.path.join(root, rel)
    found = {"files": 0, "bytes": 0, "markdown": [], "instructions": [], "repositories": [],
             "children": {}}
    for folder, names, files in os.walk(base):
        here = os.path.relpath(folder, root).replace(os.sep, "/")
        if ".git" in names or ".git" in files:
            if here != rel:
                found["repositories"].append(here)
        for name in sorted(set(names + files) & INSTRUCTIONS):
            found["instructions"].append(f"{here}/{name}")
        names[:] = sorted(n for n in names if n not in SKIP and n not in INSTRUCTIONS
                          and not os.path.islink(os.path.join(folder, n)))
        inside = os.path.relpath(folder, base).replace(os.sep, "/")
        child = "(files at the top)" if inside == "." else inside.split("/")[0] + "/"
        for name in sorted(files):
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue
            try:
                info = os.stat(path)
            except OSError:
                continue
            found["files"] += 1
            found["bytes"] += info.st_size
            row = found["children"].setdefault(child, [0, 0, 0.0])
            row[0] += 1
            row[1] += info.st_size
            row[2] = max(row[2], info.st_mtime)
            if name.lower().endswith(".md") and name not in INSTRUCTIONS:
                found["markdown"].append((info.st_mtime, f"{here}/{name}"))
    found["markdown"].sort(reverse=True)
    return found


def broken_links(root, documents):
    """Return the link-issue IDs of the documents, measured the way the turn-end check measures
    an edited file, or None with the reason when the checker did not answer."""
    if not documents:
        return set(), None
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as listing:
        listing.write("".join(path + "\n" for path in documents))
    env = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_INTERNAL_RUN="1")
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "linkcheck.py"), "--issues", "--session",
             "--filelist", listing.name],
            cwd=root, env=env, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f"{type(error).__name__}: {error}"
    finally:
        os.remove(listing.name)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines or not lines[-1].startswith("#issues "):
        return None, (result.stderr.strip().splitlines() or ["no issue trailer"])[-1][:200]
    ids = {line.split("\t", 1)[0] for line in lines[:-1]}
    return {i for i in ids if not i.startswith("~")}, None


def _size(count):
    for unit in ("bytes", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "bytes" else f"{count:.1f} {unit}"
        count /= 1024


def _day(stamp):
    return datetime.date.fromtimestamp(stamp).isoformat()


def inventory(root, rel, found, issues):
    """Return the inventory page: the folder in the fewest lines that let a reader propose tracks."""
    lines = [f"# Inventory of {rel}/", "",
             f"Written by `python3 tools/adopt.py {rel}` on {datetime.date.today().isoformat()}. "
             "Nothing in the folder was moved, renamed or edited.", "",
             f"{found['files']} files, {_size(found['bytes'])}, {len(found['markdown'])} Markdown "
             f"documents, {len(issues)} {'link' if len(issues) == 1 else 'links'} already broken "
             "(recorded as known).", "",
             "## What is in it", "", "| Part | Files | Size | Newest |", "|---|---|---|---|"]
    children = sorted(found["children"].items(), key=lambda item: -item[1][2])
    for name, (count, size, newest) in children[:MAX_CHILDREN]:
        lines.append(f"| {name} | {count} | {_size(size)} | {_day(newest)} |")
    if len(children) > MAX_CHILDREN:
        lines.append(f"| ({len(children) - MAX_CHILDREN} more parts not listed) | | | |")
    lines += ["", "## Documents, newest first", ""]
    for stamp, path in found["markdown"][:MAX_DOCUMENTS]:
        heading = _first_heading(os.path.join(root, path))
        lines.append(f"- {_day(stamp)} `{path}`" + (f": {heading}" if heading else ""))
    if len(found["markdown"]) > MAX_DOCUMENTS:
        lines.append(f"- ({len(found['markdown']) - MAX_DOCUMENTS} older documents not listed)")
    if not found["markdown"]:
        lines.append("- (none)")
    for title, rows in (("Instruction files inside", found["instructions"]),
                        ("Git repositories inside", found["repositories"])):
        if rows:
            lines += ["", f"## {title}", ""] + [f"- `{row}`" for row in rows]
    return "\n".join(lines) + "\n"


def record(root, rel, found, issues, again):
    """Write the folder's entry in the record of adopted link issues and return the issues left
    unrecorded: on a second run without `again`, the links broken since the first."""
    data = adopted.read(root)
    folders = data.get("folders") if isinstance(data.get("folders"), dict) else {}
    before = adopted.issue_ids(root)
    mine = {i for i in before if i.startswith(rel + "/")}
    accepted = issues if again or rel not in folders else issues & mine
    folders[rel] = {"adopted": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "markdown": len(found["markdown"]), "broken_links": len(accepted)}
    safeio.make_parent(P.gate_adopted(root))
    safeio.atomic_write(P.gate_adopted(root), json.dumps(
        {"schema_version": 1, "folders": folders,
         "linkcheck": sorted((before - mine) | accepted)}, ensure_ascii=False, indent=1) + "\n")
    return issues - accepted


def report(rel, found, issues, page, dry, later=()):
    lines = [f"{rel}/: {found['files']} files, {_size(found['bytes'])}, "
             f"{len(found['markdown'])} Markdown documents"]
    lines.append(f"  links already broken: {len(issues) - len(later)}. " + (
        "They would be recorded as known." if dry else
        "Recorded as known: they will not stop a turn that edits these documents."))
    if later:
        lines.append(f"  links broken since the folder was adopted: {len(later)}. Not recorded. Fix "
                     "them, or accept the folder as it is now with --again:")
        lines += [f"    {row}" for row in sorted(later)[:10]]
        if len(later) > 10:
            lines.append(f"    ({len(later) - 10} more)")
    if found["instructions"]:
        lines.append("  instruction files inside. A runtime reads them when it works in their "
                     "folder, beside this workspace's rules. Move what still applies into "
                     "instance/rules.md and rename the rest:")
        lines += [f"    {row}" for row in found["instructions"]]
    if found["repositories"]:
        lines.append("  Git repositories inside. They keep working, and this workspace's Git "
                     "ignores them:")
        lines += [f"    {row}" for row in found["repositories"]]
    lines.append(f"  inventory: {page}" + (" (not written)" if dry else "") +
                 ". Read it, not the folder, to propose tracks.")
    lines.append("Nothing in the folder was moved, renamed or edited.")
    return "\n".join(lines)


def listing(root):
    folders = adopted.read(root).get("folders")
    if not isinstance(folders, dict) or not folders:
        return "No folder has been adopted. python3 tools/adopt.py FOLDER adopts one."
    rows = [f"{name}/: adopted {entry.get('adopted', '?')}, {entry.get('markdown', '?')} Markdown "
            f"documents, {entry.get('broken_links', '?')} links recorded as already broken"
            for name, entry in sorted(folders.items()) if isinstance(entry, dict)]
    return "\n".join(rows)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in args):
        print(__doc__.strip())
        return 0
    dry, again = "--dry" in args, "--again" in args
    names = [a for a in args if a not in ("--dry", "--again")]
    root = P.instance_root()
    if not names:
        print(listing(root))
        return 0
    if len(names) != 1 or names[0].startswith("-"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    rel = _rel_folder(names[0], root)
    found = survey(root, rel)
    issues, failure = broken_links(root, [path for _, path in found["markdown"]])
    if issues is None:
        print(f"adopt: the link check did not answer ({failure}). Nothing was written.",
              file=sys.stderr)
        return 1
    page = os.path.join(P.private_state(root), "adopt-" + rel.replace("/", "-") + ".md")
    later = set()
    if not dry:
        later = record(root, rel, found, issues, again)
        safeio.make_parent(page)
        safeio.atomic_write(page, inventory(root, rel, found, issues))
    print(report(rel, found, issues, os.path.relpath(page, root), dry, later))
    return 0


if __name__ == "__main__":
    sys.exit(main())
