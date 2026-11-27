#!/usr/bin/env python3
"""List the owner's projects and draw their map (KIT-DR-093).

Usage:
  python3 tools/projects.py [list]   the projects as a session sees them: folders by status, outside folders
  python3 tools/projects.py draw     redraw the map between the two marker lines in projects/README.md
                                     (a README without them gets them at its end)
  python3 tools/projects.py check    what doctor warns about, one line each

Every folder under projects/ is a project. A block at the top of its README.md can give it a name, an
area, a status, the file to open first, folders outside this one and private parts; the map is drawn
from the folders and their blocks, never edited by hand. The session-start render also redraws it.
"""
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import project_folders as projects  # noqa: E402

DRAWN = {
    "changed": (0, "projects/README.md redrawn"),
    "current": (0, "projects/README.md already current"),
    "missing": (1, "projects/README.md does not exist: bash setup.sh --force writes it"),
    "malformed": (1, f"projects/README.md needs exactly one {projects.MAP_START} line followed by one "
                     f"{projects.MAP_END} line; fix the marker lines and run this again"),
}


def main(argv):
    if argv in (["--help"], ["-h"]):
        print(__doc__.strip())
        return 0
    if argv in ([], ["list"]):
        rows = projects.context_rows(max_bytes=1 << 20)
        print("\n".join(rows) if rows else "no projects yet: projects/README.md says how to add one")
        return 0
    if argv == ["draw"]:
        code, text = DRAWN[projects.draw(add_markers=True)]
        print(text, file=sys.stderr if code else sys.stdout)
        return code
    if argv == ["check"]:
        rows = projects.problems()
        print("\n".join(rows) if rows else "no warnings")
        return 1 if rows else 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
