#!/usr/bin/env python3
"""Reads what the improvement loop's stores say about a cycle: its state and whether it still needs processing.

A cycle's state comes from the outcome record the applier writes whole (OUTCOME_REL), and before the
applier has run from the collection record its beat writes (COLLECTION); never from REPORT.md, which
is drawn from those records for a person. A cycle folder with an APPLY.md (the report of an earlier
version of the loop) and no outcome record, or whose record has no "state", is CLOSED: never processed
again. Other tools (the beats, the applier, status, the health check) read a cycle's state only through
these functions."""
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
from loop_common import load_json, sha256_file  # noqa: E402

# A cycle's state. The applier records PENDING (a bundle is not finished, the same word as its outcome), DONE, FAILED or CEILING (the
# run stopped at loop.token_ceiling; tools/loop/lib/loop_worker.py); STALE is a recorded state whose
# input has changed since, CLOSED a folder from before the record (see the module docstring).
PENDING, DONE, FAILED, CEILING, STALE, CLOSED = "pending", "done", "failed", "token-ceiling", "stale", "closed"
RECORDED = (PENDING, DONE, FAILED, CEILING)
# The outcome record of the last applier run over a cycle, relative to the cycle folder.
OUTCOME_REL = "apply/outcome.json"
# What a beat records about its collection in each cycle folder: the state (pending until the applier
# has run, or done, failed, token-ceiling), the failure, and the lines REPORT.md shows of what was
# collected (tools/loop/lib/loop_report.py).
COLLECTION = "collection.json"
INPUTS = ("PROPOSALS.md", "REVIEW.md")


def read_outcome(cycle_abs):
    """The cycle's outcome record; None when there is none, {} when it is not a readable record."""
    p = os.path.join(cycle_abs, OUTCOME_REL)
    if not os.path.lexists(p):
        return None
    if os.path.islink(p) or not os.path.isfile(p):
        return {}
    data = load_json(p)
    return data if data.get("state") in RECORDED or "state" not in data else {}


def apply_status(cycle_abs):
    """The cycle's state bound to its current input: None (never judged), CLOSED, STALE, or the
    recorded state. A record that cannot be read is FAILED, never complete."""
    record = read_outcome(cycle_abs)
    if record is None:
        return CLOSED if os.path.lexists(os.path.join(cycle_abs, "APPLY.md")) else None
    if record and "state" not in record:
        return CLOSED
    st = record.get("state", FAILED)
    if st == FAILED:
        return st
    inp = record.get("input") or {}
    digest = inp.get("sha256")
    if inp.get("name") in INPUTS and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) \
            and sha256_file(os.path.join(cycle_abs, inp["name"])) != digest:
        return STALE
    return st


def needs_processing(cycle_abs):
    return apply_status(cycle_abs) not in (DONE, CLOSED)


def cycle_state(cycle_abs):
    """The cycle's state word for a person and for status: the outcome record's, else the one the beat's
    collection record (COLLECTION) holds. STALE reads as PENDING, since the next run judges it again.
    None for a folder with neither."""
    st = apply_status(cycle_abs)
    if st is not None:
        return PENDING if st == STALE else st
    return load_json(os.path.join(cycle_abs, COLLECTION)).get("state")
