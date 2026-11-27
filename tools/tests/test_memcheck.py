#!/usr/bin/env python3
"""Fixture tests for stale memory indexes and track-state drift."""
import datetime
import os
import shutil
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import paths as P
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
        "# journal\n\n- 2026-08-13T10:00+09:00 [demo/state] 후속 사건 발생\n"
        # An idea does not change the track's state, so it must not move the compared date.
        "- 2026-08-20T10:00+09:00 [demo/idea] 떠오른 생각\n")
    return root, state


def run():
    tmp = tempfile.mkdtemp(prefix="memcheck-fixture-")
    failures = []
    live_state, live_private = P.state(), P.private_state()
    orig = (P.state, P.private_state, C.tracks, C.check_config)

    def redirect(state, private_state, tracks, checks):
        P.state, P.private_state = (lambda root=None: state), (lambda root=None: private_state)
        C.tracks = lambda: tracks
        C.check_config = lambda key, default=None: checks.get(key, default)

    try:
        # --- Stale index fixture ---
        mem = fixture_8_8_stale_index(tmp)
        # Seal off the live journals and tracks: a malformed journal line is echoed into the output.
        empty = (os.path.join(tmp, "empty-state"), os.path.join(tmp, "empty-private-state"), [])
        import io, contextlib
        # The words that mark a stale status are the instance's own; with none configured the
        # index is not judged, and with the instance's words the stale line is found.
        redirect(*empty, {})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            now.check(memory_dir=mem, root=os.path.join(tmp, "empty"))
        if "[volatile index]" in buf.getvalue():
            failures.append("fixture 1: index judged with no volatile words configured\n" + buf.getvalue())
        redirect(*empty, {"volatile_index_words": ["대기\\b"]})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            now.check(memory_dir=mem, root=os.path.join(tmp, "empty"))
        out1 = buf.getvalue()
        if "[volatile index]" in out1:
            print("fixture 1 (stale 8/8 index): ✓ detected")
        else:
            failures.append("fixture 1: stale index not detected\n" + out1)

        # --- Track drift fixture ---
        root, state = fixture_tracker_drift(tmp)
        private_state = os.path.join(tmp, "private-state")
        os.makedirs(private_state)
        private_journal = os.path.join(private_state, "journal-2026-08.md")
        open(private_journal, "w", encoding="utf-8").write("# journal\n\n- bad\n")
        # Redirect both journals and isolate the fixture from live configuration.
        redirect(state, private_state, FIXTURE_TRACKS, {"volatile_index_words": ["대기\\b"]})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            now.check(memory_dir=os.path.join(tmp, "nomem"), root=root)
        out2 = buf.getvalue()
        if "[canonical behind] demo/tracker.md" in out2 and "(2026-08-13)" in out2:
            print("fixture 2 (tracker drift): ✓ detected")
        else:
            failures.append("fixture 2: stale canonical track not detected\n" + out2)
        # The fixture's malformed private line proves the private journal was read from the fixture.
        if private_journal not in out2:
            failures.append("fixture 2: fixture private journal was not read")
        # Output must never name a live journal: a malformed line is echoed and may be private.
        for label, out in (("fixture 1", out1), ("fixture 2", out2)):
            for live in (live_state, live_private):
                if os.path.join(live, "journal-") in out:
                    failures.append(label + ": read a live journal outside the fixture")
    finally:
        P.state, P.private_state, C.tracks, C.check_config = orig
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nfailures:")
        for f in failures:
            print(" ", f)
        return 1
    print("all fixtures passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
