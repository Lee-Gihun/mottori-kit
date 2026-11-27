#!/usr/bin/env python3
"""The loop's sources: papers, which the kit ships, and any source an installation adds.

An installation adds a source by placing one module in tools/loop/sources/; tools/loop/sources/README.md
says what the module defines. The rest of the loop reaches an added source only through this module, so
the kit's own code names no source but papers (KIT-DR-088)."""
import glob
import importlib.util
import os

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# A source module puts the folders it imports from on the path itself, as every tool does.
FOLDER = os.path.join(TOOLS, "loop", "sources")
PAPERS = "papers"
# What an added source's module must define: its name (the file's name), the folder of its cycle
# folders (what may be sent, and what the applier judges), the folder of its own files (state.json,
# cycle.log, the scheduler's log), its cycle program relative to the instance root, its weekly time, the
# pattern of a cycle folder's name, the document in a cycle folder that the applier judges, and the judge
# prompt's line naming it.
REQUIRED = ("NAME", "BASE", "HOME", "PROGRAM", "SCHEDULE", "CYCLE_NAME", "INPUT", "material")
BAD_SOURCE = "{path}: an added source must define {missing} and NAME must be the file's name, other than papers"
_ADDED = None


def load(folder=None):
    """{name: module} of the source modules in folder (default tools/loop/sources/), in name order."""
    out = {}
    for path in sorted(glob.glob(os.path.join(folder or FOLDER, "*.py"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(f"loop_source_{stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        missing = [k for k in REQUIRED if not hasattr(mod, k)]
        if missing or getattr(mod, "NAME", None) != stem or stem == PAPERS:
            raise ImportError(BAD_SOURCE.format(path=path, missing=", ".join(missing or REQUIRED)))
        out[stem] = mod
    return out


def added():
    """{name: module} of the sources this installation added; none in the kit."""
    global _ADDED
    if _ADDED is None:
        _ADDED = load()
    return _ADDED


def names():
    """Every source the loop knows: the added ones in name order, then papers."""
    return tuple(added()) + (PAPERS,)


def get(name):
    """The module of an added source."""
    return added()[name]


def hook(name, attr, default=None):
    """What an added source defines under attr, or default; papers defines none of these hooks."""
    return default if name == PAPERS else getattr(get(name), attr, default)


def each(attr):
    """[(name, what it defines under attr)] for the added sources that define attr."""
    return [(n, getattr(m, attr)) for n, m in added().items() if hasattr(m, attr)]
