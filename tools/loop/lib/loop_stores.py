#!/usr/bin/env python3
"""Where the improvement loop keeps its files: each beat's folder, the cycle folders and the loop's own store.

Every path is relative to the instance root and written with "/". All of them lie in the private
area that tools/lib/paths.py names; each module that writes or reads one of these places takes it from
here, and names the files inside it itself.
"""
import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P  # noqa: E402

PRIVATE = P.tracked_name(P.private_area)
# The papers beat's own files (state.json, cycle.log, cycle.lock, read.json).
PAPERS_HOME = f"{PRIVATE}/papers"
# One folder per papers cycle, named DATE-kit.
PAPERS_BASE = f"{PRIVATE}/work/papers"
# The loop's own store: the watchdog's files.
LOOPS = f"{PRIVATE}/loops"
