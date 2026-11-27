"""The owner's projects: one folder each under projects/ (KIT-DR-093).

Every folder under projects/ is a project, named after the folder. A project can describe itself in a
block at the top of its README.md, between two `---` lines; every line is optional:

    ---
    name: Website redesign
    area: Work
    status: active            (active, paused, planned or closed)
    canonical: PLAN.md        (the file to open first, relative to the project folder)
    outside:                  (folders that stay where they are, each with a note)
      - ~/code/site: the site's own repository
    private:                  (what Git never takes, kept under _private/)
      - _private/site/: client contracts
    ---

A folder brought in as it is has no block and is still a project. The map in projects/README.md, the
projects section at session start and doctor's projects row are all read from the folders and their
blocks, so nothing else lists projects. Nothing here fails doctor: a project problem is a warning.
"""
import difflib
import os
import re
import sys
import urllib.parse

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P
import safeio

FOLDER = "projects"
STATUSES = ("active", "paused", "planned", "closed")
LISTS = ("outside", "private")
FIELDS = ("name", "area", "status", "canonical") + LISTS
MAP_START = "<!-- projects:start -->"
MAP_END = "<!-- projects:end -->"
# The session-start section shares the view's byte cap with the newest decisions, so it has its own.
CONTEXT_MAX_BYTES = 800
URL = re.compile(r"^[a-z]+://")


def _front(text):
    """(fields, notes, foreign) of a README's block; fields is None when it has none. Keys are read in
    any case, list items at any indent. A field close to one the kit knows (`statuss`) is named in
    notes. A block with a field unlike any of the kit's (`title`, `tags`) is someone else's front
    matter, as in a folder brought in as it is: none of it is read and its field names are returned
    as foreign, so nothing asks for a file the rules say to leave alone to be edited."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip() != "---":
        return None, [], []
    if "---" not in [line.strip() for line in lines[1:]]:
        return None, ["the block at the top of README.md has no closing ---"], []
    fields, notes, foreign, key = {}, [], [], None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key in LISTS:
            fields[key].append(item.group(1).strip())
            continue
        pair = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", line)
        if not pair:
            if line.strip():
                notes.append(f"unreadable line in the block: {line.strip()!r}")
            continue
        key, value = pair.group(1).lower(), pair.group(2).strip()
        if key not in FIELDS:
            if difflib.get_close_matches(key, FIELDS, n=1, cutoff=0.75):
                notes.append(f"unknown field {pair.group(1)!r} (known: {', '.join(FIELDS)})")
            else:
                foreign.append(pair.group(1))
            key = None
            continue
        fields[key] = ([value] if value else []) if key in LISTS else value
    if foreign:
        return None, [], foreign
    return fields, notes, foreign


def _split(entry):
    """'~/My code/app: the repository' -> ('~/My code/app', 'the repository'). The note starts after the
    first colon that a space follows, so a URL keeps its colon and a path may hold spaces."""
    path, _, note = entry.strip().partition(": ")
    return path.strip(), note.strip()


def read():
    """Every folder under projects/, sorted by name, as dicts with paths relative to the workspace.
    `block` says whether its README has a block; `notes` holds what is wrong with it."""
    base = P.projects()
    if not os.path.isdir(base):
        return []
    projects = []
    for key in sorted(os.listdir(base)):
        folder = os.path.join(base, key)
        # A link to a folder elsewhere is not a project folder: that folder is named under outside.
        if key.startswith((".", "_")) or not os.path.isdir(folder) or os.path.islink(folder):
            continue
        rel = f"{FOLDER}/{key}"
        try:
            with open(os.path.join(folder, "README.md"), encoding="utf-8") as f:
                fields, notes, foreign = _front(f.read())
        except (OSError, UnicodeError):
            fields, notes, foreign = None, [], []
        fields = fields or {}
        status = fields.get("status", "").lower() or None
        if status and status not in STATUSES:
            notes.append(f"status {fields['status']!r} is not one of {', '.join(STATUSES)}")
            status = None
        canonical = fields.get("canonical", "")
        # Written from the project folder (PLAN.md) or from the workspace (projects/<name>/PLAN.md).
        canonical = canonical if canonical.startswith(rel + "/") else (f"{rel}/{canonical}" if canonical else None)
        private = [_split(x) for x in fields.get("private", [])]
        notes += [f"private part {path} is not under _private/" for path, _ in private
                  if not path.startswith("_private/")]
        projects.append({"key": key, "folder": rel, "block": bool(fields) or bool(notes),
                         "foreign": foreign, "name": fields.get("name") or key,
                         "area": fields.get("area", ""), "status": status, "canonical": canonical,
                         "outside": [_split(x) for x in fields.get("outside", [])],
                         "private": private, "notes": notes})
    return projects


def links():
    """Folders under projects/ that are symbolic links, which read() leaves out."""
    base = P.projects()
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return [f"{FOLDER}/{n}" for n in names
            if os.path.islink(os.path.join(base, n)) and os.path.isdir(os.path.join(base, n))]


def expand(path):
    """An outside path on this machine (~ expanded); a URL is returned as it is."""
    return path if URL.match(path) else os.path.expanduser(path)


def problems(projects=None):
    """Warnings for doctor, one line each. Each can be normal for a while (a planned project's first
    file not written yet, an outside folder on another machine), so none is a failure."""
    rows = []
    for p in projects if projects is not None else read():
        rows += [f"{p['folder']}: {note}" for note in p["notes"]]
        if p["canonical"] and not os.path.exists(os.path.join(P.instance_root(), p["canonical"])):
            rows.append(f"{p['folder']}: canonical {p['canonical']} does not exist yet")
        for path, _ in p["outside"]:
            if not URL.match(path) and not os.path.exists(expand(path)):
                rows.append(f"{p['folder']}: outside folder {path} is not on this machine")
        for path, _ in p["private"]:
            if path.startswith("_private/") and not os.path.exists(os.path.join(P.instance_root(), path)):
                rows.append(f"{p['folder']}: private part {path} does not exist")
    rows += [f"{link}: a link to a folder elsewhere; leave that folder where it is and name it under outside "
             "in a project's block" for link in links()]
    state = map_state()
    if state == "malformed":
        rows.append(f"{FOLDER}/README.md: the map needs exactly one {MAP_START} line followed by one "
                    f"{MAP_END} line; it is not redrawn until then")
    return rows


def context_rows(max_bytes=CONTEXT_MAX_BYTES):
    """The projects for session start: one line naming the open project folders by status (closed ones
    only counted), then one line per open project with folders outside this one. Lines past
    max_bytes are left out and counted; names and private parts are in the map."""
    found = read()
    groups = {}
    for p in found:
        groups.setdefault(p["status"] or "no status", []).append(p["key"])
    order = [s for s in STATUSES if s != "closed"] + ["no status"]
    head = " · ".join(f"{s} " + ", ".join(groups[s]) for s in order if s in groups)
    closed = len(groups.get("closed", []))
    if closed:
        head += (" · " if head else "") + f"closed {closed} (in {FOLDER}/README.md)"
    first = f"- in {FOLDER}/: {head}" if head else ""
    if len(first.encode("utf-8")) > max_bytes:
        # Many or long names: the line itself is cut, so the cap holds for it too.
        cut = first.encode("utf-8")[:max_bytes - 60].decode("utf-8", "ignore").rsplit(",", 1)[0]
        first = f"{cut} … ({len(found)} in all: {FOLDER}/README.md)"
    rows = [first] if first else []
    rows += [f"- {p['key']} outside: " + ", ".join(path for path, _ in p["outside"])
             for p in found if p["outside"] and p["status"] != "closed"]
    kept, used = [], 0
    for i, row in enumerate(rows):
        cost = len(row.encode("utf-8")) + 1
        if used + cost > max_bytes and kept:
            kept.append(f"- … {len(rows) - i} more line(s): {FOLDER}/README.md")
            break
        kept.append(row)
        used += cost
    return kept


def words():
    """Display words for the map, from projects.map_words in the config; English by default."""
    try:
        import config as C
        value = C.data().get("projects", {}).get("map_words", {})
    except Exception:  # noqa: BLE001 - a broken config must not stop the map
        return {}
    return value if isinstance(value, dict) else {}


def map_text(projects=None, words_=None):
    """The table between the markers of projects/README.md, grouped by area: the areas listed in
    words["areas"] first, in that order, then the others in the order their first project sorts."""
    w = words() if words_ is None else words_
    projects = read() if projects is None else projects
    other = w.get("other", "Other")
    seen = list(dict.fromkeys(p["area"] or other for p in projects))
    areas = [a for a in w.get("areas", []) if a in seen] + [a for a in seen if a not in w.get("areas", [])]
    head = w.get("head", "| Project | Status | Open first | Outside | Private |")
    out = []
    for area in areas:
        out += [f"## {area}", "", head, "|---|---|---|---|---|"]
        for p in [x for x in projects if (x["area"] or other) == area]:
            canon, first = p["canonical"], ""
            if canon:
                rel = canon[len(FOLDER) + 1:]
                exists = os.path.exists(os.path.join(P.instance_root(), canon))
                # A file not written yet is named, not linked, so the map holds no broken link.
                name = os.path.basename(rel)
                first = f"[`{name}`]({urllib.parse.quote(rel)})" if exists else f"`{name}`"
            status = w.get(p["status"], p["status"]) if p["status"] else "-"
            out.append(f"| [{p['name']}]({urllib.parse.quote(p['key'])}/) | {status} | {first} | "
                       + "<br>".join(path for path, _ in p["outside"]) + " | "
                       + "<br>".join(path for path, _ in p["private"]) + " |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _markers(text):
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == MAP_START]
    ends = [i for i, line in enumerate(lines) if line.strip() == MAP_END]
    return lines, starts, ends


def map_state():
    """'missing' (no projects/README.md), 'no markers', 'malformed' or 'ready'."""
    try:
        with open(P.projects_readme(), encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeError):
        return "missing"
    _, starts, ends = _markers(text)
    if not starts and not ends:
        return "no markers"
    if len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0]:
        return "ready"
    return "malformed"


def draw(add_markers=False):
    """Redraw the map between the markers of projects/README.md. Returns 'changed', 'current' or the
    map_state that stopped it. Only the lines between one marker pair are replaced; with add_markers
    (the command, never a hook) a README with no markers gets the pair at its end."""
    state = map_state()
    if state == "missing" or state == "malformed" or (state == "no markers" and not add_markers):
        return state
    path = P.projects_readme()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    table = map_text().rstrip("\n").split("\n")
    lines, starts, ends = _markers(text)
    if state == "no markers":
        new = text.rstrip("\n") + "\n\n" + "\n".join([MAP_START, *table, MAP_END]) + "\n"
    else:
        new = "\n".join(lines[:starts[0] + 1] + table + lines[ends[0]:])
    if new == text:
        return "current"
    # Written whole or not at all: an interrupted redraw must not cost the owner's text around the map.
    safeio.atomic_write(path, new)
    return "changed"
