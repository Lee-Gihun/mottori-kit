#!/usr/bin/env python3
"""Read, validate, route and append journal rows: `- <ISO8601> [<track>/<type>] <one-line text>`.

A row goes to the public journal (state/journal-YYYY-MM.md) only when its track is in the
configured public allowlist; every other row, and every row while that allowlist is unusable,
goes to the private one (_private/state/). Importing this module reads no file.

Command line (setup.sh uses it):
  python3 tools/lib/journal.py rows      Check every journal strictly; print its rows as JSON
                                     [[type, time, source], ...] in time order.
  python3 tools/lib/journal.py count public|private
                                     Print how many rows the journals of that folder hold."""
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config  # noqa: E402
import paths  # noqa: E402
import safeio  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
HEADER = (
    "Format: `- <ISO8601> [<track>/<type>] <text> (→ ref)*` · types are listed in "
    "journal_types of `{config}` · mark an entry written after the fact with "
    "`{retroactive}`"
)
LINE_TRACK = (
    "track '{track}' has characters a journal track cannot use: only a-z, 0-9, Hangul, _ and - "
    "are allowed"
)
LINE_TYPE = "type '{type}' is not defined (allowed: {allowed})"
TAIL_MISSING_NEWLINE = (
    "journal corrupt: {path} has no final newline; append refused until the tail is repaired"
)

# The marker people add to an event recorded after the fact; the header of each file names it.
RETROACTIVE = "(retroactive)"
BODY_MAX = 300

LINE = re.compile(
    r"^- (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}))"
    r" \[(?P<track>" + config.TRACK_NAME + r")/(?P<type>" + config.TYPE_NAME + r")\] (?P<body>.+)$"
)
# Only to say which part of a refused row is wrong.
_LOOSE_LINE = re.compile(r"^- \S+ \[(?P<track>[^/\]]*)/(?P<type>[^\]]*)\] .+$")


def journal_visibility(track, force_private=False):
    """The journal a new row of this track goes to: the ordinary one, unless the owner asked for
    the private area (--private) or the installation keeps a list of public tracks and this track
    is not on it. Nothing promotes a private row to public."""
    if force_private:
        return "private"
    return "public" if config.track_is_public(track) else "private"


def validate_line(line):
    """Return a schema error, or None for a valid journal entry."""
    # The reader splits with str.splitlines, which also breaks at CR and Unicode separators;
    # a row holding one would be cut there, dropping the rest of the event from every view.
    pieces = line.strip().splitlines()
    if len(pieces) > 1:
        return f"text contains a line break (U+{ord(line.strip()[len(pieces[0])]):04X}); a journal row must be one line"
    m = LINE.match(line.strip())
    loose = None if m else _LOOSE_LINE.match(line.strip())
    if loose and not re.fullmatch(config.TRACK_NAME, loose["track"]):
        return LINE_TRACK.format(track=loose["track"])
    if loose and not re.fullmatch(config.TYPE_NAME, loose["type"]):
        return LINE_TYPE.format(type=loose["type"], allowed=", ".join(config.journal_types()))
    if not m:
        return "format mismatch: expected '- <ISO8601> [<track>/<type>] <text>'"
    return _row_schema_error(m)


def _row_schema_error(m):
    """The schema error of a row that already matched LINE, or None."""
    types = config.journal_types()
    if m.group("type") not in types:
        return LINE_TYPE.format(type=m.group("type"), allowed=", ".join(types))
    if len(m.group("body")) > BODY_MAX:
        return "text exceeds 300 characters; a journal row records one event, not a document"
    return None


def shown_path(path):
    """A path for messages: relative inside the instance, so no home folder leaks out."""
    rel = os.path.relpath(path, paths.instance_root())
    return path if rel.startswith("..") else rel


# One session start fingerprints and projects every monthly journal several times. Each file is
# read and parsed once per identity; every write changes ctime, so a changed file is read again.
_CACHE = {}


def _parsed_file(path):
    """Return (raw bytes, items) of one journal file; items are ("error", problem) or
    ("row", fields, time) in file order, independent of the visibility policy."""
    st = os.stat(path)
    key = (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    hit = _CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    with open(path, "rb") as f:
        raw_bytes = f.read()
    shown = shown_path(path)
    items = []
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        items.append(("error", f"{shown}:1: " + "UTF-8 BOM is not allowed"))
    if raw_bytes and not raw_bytes.endswith(b"\n"):
        # Named at the last line, the one without the newline.
        last = raw_bytes.count(b"\n") + 1
        items.append(("error", f"{shown}:{last}: last line has no newline"))
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        items.append(("error", f"{shown}: invalid UTF-8 at byte {e.start}"))
        text = ""
    for lineno, line in enumerate(text.splitlines(), 1):
        items.append(_item(shown, lineno, line.strip()))
    items = [item for item in items if item is not None]
    _CACHE[path] = (key, (raw_bytes, items))
    return raw_bytes, items


def _item(shown, lineno, raw):
    m = LINE.match(raw)
    if not m:
        # Never the row's text: a private row in a tracked journal would reach the error log,
        # the public-only context and the gate's issue list.
        return ("error", f"{shown}:{lineno}: " + "malformed journal row") if raw.startswith("- ") else None
    schema_error = _row_schema_error(m)
    if schema_error:
        return ("error", f"{shown}:{lineno}: {schema_error}")
    row_dt = config.parse_timestamp(m["ts"])
    if row_dt is None:
        return ("error", f"{shown}:{lineno}: timestamp {m['ts']}")
    return ("row", m.groupdict(), row_dt)


def journal_bytes(path):
    """The bytes of one journal file, read at most once while the file is unchanged."""
    return _parsed_file(path)[0]


def _scope(physical, row, row_dt):
    """The visibility of a stored row. A row in the public file dated before the legacy cutoff
    keeps the allowlist of that time, so a later allowlist cannot promote old private content."""
    if physical == "private":
        return "private"
    cutoff = config.legacy_cutoff()
    if cutoff is not None and row_dt <= cutoff:
        return "public" if row["track"] in config.legacy_public_tracks() else "private"
    return journal_visibility(row["track"])


def parse_journal(visibility=None, strict=False, errors=None, physical_visibilities=None):
    """Read the public and private journals in time order; strict raises on the first damage."""
    out = []
    errors = errors if errors is not None else []
    order = 0
    for base, physical in ((paths.state(), "public"), (paths.private_state(), "private")):
        if physical_visibilities is not None and physical not in physical_visibilities:
            continue
        for path in paths.journals_in(base):
            for item in _parsed_file(path)[1]:
                if item[0] == "error":
                    if strict:
                        raise ValueError(f"journal corrupt: {item[1]}")
                    errors.append(item[1])
                    continue
                row, row_dt = dict(item[1]), item[2]
                scope = _scope(physical, row, row_dt)
                if visibility is None or visibility == scope:
                    row.update(visibility=scope, source=path, order=order, _parsed_dt=row_dt)
                    out.append(row)
                order += 1
    out.sort(key=lambda e: (e["_parsed_dt"], e["order"]))
    for row in out:
        del row["_parsed_dt"]
    return out


def state_lock(timeout=10.0):
    """Serialize journal appends and NOW publication for this instance."""
    return safeio.locked(paths.journal_lock(), timeout=timeout)


def _assert_tail(path):
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as tail:
            tail.seek(-1, os.SEEK_END)
            if tail.read(1) != b"\n":
                raise ValueError(TAIL_MISSING_NEWLINE.format(path=path))


def append(line, path, event_time):
    """Append one validated row to path, starting a new month's file with its header.

    The caller holds state_lock(). A failed write (a full disk) is rolled back, so no partial
    row is left for the strict parser to refuse every later append over."""
    new = not os.path.exists(path)
    _assert_tail(path)
    size = 0 if new else os.path.getsize(path)
    try:
        with safeio.open_append(path) as f:
            if new:
                f.write(f"# journal {event_time:%Y-%m}\n\n"
                        + HEADER.format(retroactive=RETROACTIVE,
                                        config=paths.tracked_name(paths.config_file)) + "\n\n")
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        if new:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass  # open() itself failed; raise its error, not this one.
        else:
            os.truncate(path, size)
        raise


def _rows():
    """The preflight setup runs before it migrates: every journal parses strictly, which includes
    its final newline. Return [[type, time, source], ...] in time order."""
    try:
        rows = parse_journal(strict=True)
    except Exception as e:
        raise SystemExit(f"existing journal preflight failed; nothing changed: {e}")
    return [[row["type"], row["ts"], row["source"]] for row in rows]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if argv == ["rows"]:
        print(json.dumps(_rows(), ensure_ascii=False))
        return 0
    if len(argv) == 2 and argv[0] == "count" and argv[1] in ("public", "private"):
        print(len(parse_journal(physical_visibilities=(argv[1],))))
        return 0
    print(__doc__.split("Command line", 1)[1].split("\n", 1)[1].rstrip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
