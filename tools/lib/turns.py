#!/usr/bin/env python3
"""The turn record: what the dispatcher sent to each session, so a finding blocks once per turn.

The dispatcher (tools/dispatch.py) asks block_once at every turn end and count_prompt at every
prompt; Antigravity's restate step keeps what its conversation last received here too. The record
is kept apart from the gate's pending marker because the gate can pass while another step blocks.
"""
import hashlib
import json
import os
import sys
import time

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P
import safeio

# JSON {"runtime\tsession": entry}; an entry unchanged for RECORD_DAYS goes.
RECORD = lambda: P.marker("mottori-turn-record")
RECORD_DAYS = 7


def update(runtime, session, change, fallback):
    """Apply change(entry) to one session's entry, save it, and return what change returned, or
    fallback when the record cannot be read or written. An entry change leaves empty is removed."""
    path = RECORD()
    try:
        with safeio.locked(path + ".lock", timeout=2):
            try:
                with open(path, encoding="utf-8") as f:
                    entries = json.load(f)
            except (OSError, ValueError):
                entries = {}
            now = time.time()
            entries = {k: v for k, v in (entries.items() if isinstance(entries, dict) else ())
                       if isinstance(v, dict) and now - v.get("t", 0) < RECORD_DAYS * 86400}
            key = f"{runtime}\t{session or ''}"
            entry = entries.setdefault(key, {})
            result = change(entry)
            if entry:
                entry["t"] = now
            else:
                del entries[key]
            safeio.atomic_write(path, json.dumps(entries, ensure_ascii=False))
            return result
    except Exception as error:  # noqa: BLE001 - a broken record must not cost the answer
        print(time.strftime("%Y-%m-%dT%H:%M:%S"),
              f"hook failed (turn record, {type(error).__name__}: {error})", file=sys.stderr)
        return fallback


def _finding_ids(session, reasons):
    """Return the findings in these block reasons. The gate names all its open issues in one
    reason, so its reason stands for the issue ids of the block it just recorded, and fixing one
    issue does not make the others new; any other reason is one finding, its text's hash."""
    try:
        import gate
        held = gate.open_block(session)
    except Exception:  # noqa: BLE001 - without the gate's block each reason is one finding
        held = {}
    ids = set()
    for reason in reasons:
        if held.get("ids") and reason == held.get("reason"):
            ids.update(str(i) for i in held["ids"])
        else:
            ids.add(hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16])
    return ids


def block_once(runtime, session, turn, continuing, reasons):
    """Return the block reasons a turn end sends: a finding blocks once per turn.

    This is the rule for every step of a turn end. A finding already sent in this turn is
    deferred and named at the next prompt instead (count_prompt). The entry keeps only the
    findings still open, so a fixed one that comes back blocks again. turn is the runtime's turn
    id; without one the prompt count stands in. When the record cannot be used, continuing (the
    runtime's hint that a turn end already stopped this turn) alone decides."""
    ids = _finding_ids(session, reasons) if reasons else set()

    def change(entry):
        key = turn or f"prompt {entry.get('prompts', 0)}"
        new = ids - set(entry.get("ids") or () if entry.get("turn") == key else ())
        entry.pop("ids", None)
        entry.pop("deferred", None)
        if ids:
            entry.update(turn=key, ids=sorted(ids))
        if reasons and not new:
            entry["deferred"] = reasons
        return reasons if new else []
    return update(runtime, session, change, [] if continuing else reasons)


def count_prompt(runtime, session):
    """Count a prompt of this session and return the reasons the last turn deferred."""
    def change(entry):
        # Counted even when the prompt has a turn id: a Stop that lacks it falls back to the count.
        entry["prompts"] = entry.get("prompts", 0) + 1
        return entry.pop("deferred", None) or []
    return update(runtime, session, change, [])
