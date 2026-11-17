#!/usr/bin/env python3
"""Fixture tests for stale memory indexes and track-state drift."""
import datetime
import os
import shutil
import sys
import tempfile

from testlib import run_test

HERE = os.path.dirname(os.path.abspath(__file__))
# The assertions below match the Korean check labels.
os.environ["MOTTORI_LANG"] = "ko"
sys.path.insert(0, HERE)
import memlib as M
import importlib
now = importlib.import_module("now")


def fixture_8_8_stale_index(tmp):
    """An old index entry must not override newer track state."""
    mem = os.path.join(tmp, "memory")
    os.makedirs(mem)
    open(os.path.join(mem, "MEMORY.md"), "w", encoding="utf-8").write(
        "# Memory Index\n\n"
        "- [Session state](session-state-handoff.md) — 트랙 완주(8/8)"
        "→다음 국면(응답 대기) · 후속 B 화 8/11 · 후속 C 월 8/10\n")
    open(os.path.join(mem, "session-state-handoff.md"), "w").write("---\ntype: user\n---\nx")
    return mem


# Use fixture-owned tracks so results do not depend on live instance configuration.
FIXTURE_TRACKS = [("demo", "데모", "demo/tracker.md")]


def fixture_tracker_drift(tmp):
    """A newer journal event makes the older canonical track state stale."""
    root = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(root, "demo"))
    tracker = os.path.join(root, "demo", "tracker.md")
    open(tracker, "w", encoding="utf-8").write("# tracker\n마지막 업데이트: 2026-08-08\n")
    old = datetime.datetime(2026, 8, 8, 14, 30).timestamp()
    os.utime(tracker, (old, old))

    state = os.path.join(tmp, "state")
    os.makedirs(state)
    open(os.path.join(state, "journal-2026-08.md"), "w", encoding="utf-8").write(
        "# journal\n\n- 2026-08-13T10:00+09:00 [demo/state] 후속 사건 발생\n")
    return root, state


def run():
    tmp = tempfile.mkdtemp(prefix="memcheck-fixture-")
    failures = []
    # The labels below are now.py's Korean check output; pin the language so they stay comparable.
    old_lang = os.environ.get("MOTTORI_LANG")
    os.environ["MOTTORI_LANG"] = "ko"
    try:
        # --- Stale index fixture ---
        mem = fixture_8_8_stale_index(tmp)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            now.check(memory_dir=mem, root=os.path.join(tmp, "empty"))
        out1 = buf.getvalue()
        if "[인덱스 휘발성]" in out1:
            print("fixture 1 (stale 8/8 index): ✓ detected")
        else:
            failures.append("fixture 1: stale index not detected\n" + out1)

        # --- Track drift fixture ---
        root, state = fixture_tracker_drift(tmp)
        orig_state, orig_tracks = M.STATE, M.TRACKS
        M.STATE = state           # Redirect the journal.
        M.TRACKS = FIXTURE_TRACKS  # Isolate the fixture from live configuration.
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                now.check(memory_dir=os.path.join(tmp, "nomem"), root=root)
            out2 = buf.getvalue()
        finally:
            M.STATE, M.TRACKS = orig_state, orig_tracks
        if "[정본 낙후] demo/tracker.md" in out2:
            print("fixture 2 (tracker drift): ✓ detected")
        else:
            failures.append("fixture 2: stale canonical track not detected\n" + out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old_lang is None:
            os.environ.pop("MOTTORI_LANG", None)
        else:
            os.environ["MOTTORI_LANG"] = old_lang

    if failures:
        print("\nfailures:")
        for f in failures:
            print(" ", f)
        return 1
    print("all fixtures passed")
    return 0


if __name__ == "__main__":
    sys.exit(run_test(run, __file__))
