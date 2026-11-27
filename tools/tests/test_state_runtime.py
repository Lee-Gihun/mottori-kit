#!/usr/bin/env python3
"""State ledger regression tests: routing, atomicity, concurrency, and hook budget.

Every fixture lives in a temporary instance.  The live workspace journal and NOW are never used.
"""
import atexit
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import threading
import time
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = os.path.join(HERE, "now.py")
# The instance-shape runner marks its children as internal probes; hook-context then leaves the
# hook error log alone, which the hook-error tests below exercise as a real session.
os.environ.pop("MOTTORI_INTERNAL_RUN", None)
# config reads the instance config and thread registry on first use. Point it at an empty
# throwaway instance so this process never loads the real workspace (run_now sets its own root).
_IMPORT_ROOT = tempfile.mkdtemp(prefix="state-runtime-import-")
atexit.register(shutil.rmtree, _IMPORT_ROOT, ignore_errors=True)
os.environ["MOTTORI_INSTANCE"] = _IMPORT_ROOT
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as LIVE_C  # noqa: E402
import journal as LIVE_J  # noqa: E402
import now as LIVE_NOW  # noqa: E402
import paths as LIVE_P  # noqa: E402
import runlog as LIVE_RUNLOG  # noqa: E402
import safeio as LIVE_SAFEIO  # noqa: E402

# The heading tokens of the public NOW page, in page order.
PUBLIC_SECTION_TOKENS = [name for name, _ in LIVE_NOW._SECTIONS["public"]]

# The fixed text before the detail.
FAIL_CLOSE_WARNING = LIVE_NOW.VISIBILITY_FAIL_CLOSED.split("{detail}")[0]


def config(public_tracks=None, threads=None, legacy_cutoff="2026-08-26T23:59:59+09:00",
           legacy_public_tracks=None):
    public_tracks = (["system", "research"] if public_tracks is None else public_tracks)
    return {
        "schema_version": 4,
        "instance": {"name": "fixture"},
        "tracks": [],
        "threads": threads or [],
        "personal_pointer": "_private/README.md",
        "journal_visibility": {
            "public_tracks": public_tracks,
            "legacy_cutoff": legacy_cutoff,
            "legacy_public_tracks": (public_tracks if legacy_public_tracks is None
                                      else legacy_public_tracks),
        },
        "journal_types": ["decision", "state", "artifact", "correction", "lesson", "switch", "idea"],
        "thresholds": {
            "now_tail_events": 30,
            "now_recent_decisions": 20,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_max_bytes": 6000,
            "now_hook_max_bytes": 6000,
        },
    }


def instance(*, with_config=True, public_tracks=None, threads=None,
             legacy_cutoff="2026-08-26T23:59:59+09:00", legacy_public_tracks=None):
    root = tempfile.mkdtemp(prefix="state-runtime-")
    os.makedirs(os.path.join(root, "instance"), exist_ok=True)
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    if with_config:
        with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
            json.dump(config(public_tracks, threads, legacy_cutoff, legacy_public_tracks),
                      f, ensure_ascii=False)
    return root


def run_now(root, *args, env=None, check=True, stdin=None):
    e = dict(os.environ, MOTTORI_INSTANCE=root)
    # A nested suite inherits the internal-run flag, under which hook-context marks nothing shown.
    e.pop("MOTTORI_INTERNAL_RUN", None)
    if env:
        e.update(env)
    r = subprocess.run([sys.executable, NOW, *args], capture_output=True, text=True, env=e, cwd=root,
                       input=stdin if stdin is not None else "")
    if check and r.returncode:
        raise AssertionError(f"now.py {' '.join(args)} exit={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    return r


def read(path):
    assert os.path.isfile(path), f"expected output file: {path}"
    with open(path, encoding="utf-8") as f:
        return f.read()


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# now.py derives the journal filename from the current time. Hard-coding it breaks on the
# first day of each month.
JOURNAL_NOW = "journal-%s.md" % datetime.datetime.now().strftime("%Y-%m")


def event(token, track="system", typ="state", second=0):
    return f"- 2026-08-26T23:40:{second:02d}+09:00 [{track}/{typ}] {token}\n"


def edit_config(root, change):
    """Apply change(cfg) to the fixture config on disk and return its path."""
    path = os.path.join(root, "instance", "config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    change(cfg)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    return path


def run_script(root, script, *argv):
    """Run a snippet as its own process so it imports the tools against this instance."""
    return subprocess.run([sys.executable, "-c", script, *argv], capture_output=True, text=True,
                          env=dict(os.environ, MOTTORI_INSTANCE=root), cwd=root)


def _probe(root, expr):
    r = run_script(root, f"import sys; sys.path.insert(0, {HERE!r}); import now; print({expr})")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _hook_ctx(root, *args):
    r = run_now(root, "hook-context", *args)
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def _hook_ctx_env(root, env):
    r = run_now(root, "hook-context", env=env)
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_before_setup_the_session_start_says_only_how_to_set_up():
    """A kit folder before setup has no config and no state: the injection is one line naming
    bash setup.sh, and nothing is written."""
    root = instance(with_config=False)
    try:
        ctx = _hook_ctx(root)
        assert ctx.startswith("[state injection] This workspace is not set up yet") and "bash setup.sh" in ctx, ctx
        assert ctx.count("\n") == 1, ctx
        assert os.listdir(os.path.join(root, "state")) == [] and not os.path.exists(os.path.join(root, "_private"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

def test_routing_and_public_immutability():
    root = instance()
    try:
        run_now(root, "log", "[system/state] PUBLIC-CANARY")
        public_journal = os.path.join(root, "state", JOURNAL_NOW)
        public_now = os.path.join(root, "state", "NOW.md")
        before = (digest(public_journal), digest(public_now))

        run_now(root, "log", "--private", "[system/state] FORCED-PRIVATE")
        run_now(root, "log", "[personal/state] PERSONAL-PRIVATE")
        run_now(root, "log", "[novel/state] UNKNOWN-PRIVATE")

        assert before == (digest(public_journal), digest(public_now)), \
            "private writes changed tracked state"
        local_journal = os.path.join(root, "_private", "state", JOURNAL_NOW)
        local_now = os.path.join(root, "_private", "state", "NOW.md")
        local = read(local_journal) + read(local_now)
        assert all(x in local for x in ("FORCED-PRIVATE", "PERSONAL-PRIVATE", "UNKNOWN-PRIVATE"))
        assert "PUBLIC-CANARY" in read(public_now)
        assert not any(x in read(public_now) for x in ("FORCED-PRIVATE", "PERSONAL-PRIVATE", "UNKNOWN-PRIVATE"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_legacy_filter_and_private_thread():
    threads = [
        {"key": "shared", "name": "SHARED-THREAD", "dossier": "shared.md"},
    ]
    root = instance(threads=threads)
    try:
        jp = os.path.join(root, "state", JOURNAL_NOW)
        with open(jp, "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + event("PUBLIC-LEGACY", "system", second=1)
                    + event("PRIVATE-LEGACY", "personal", second=2))
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        with open(os.path.join(local_state, "threads.json"), "w", encoding="utf-8") as f:
            json.dump([{"key": "local", "name": "LOCAL-THREAD",
                        "dossier": "_private/local.md"}], f)
        run_now(root, "render")
        public = read(os.path.join(root, "state", "NOW.md"))
        local = read(os.path.join(root, "_private", "state", "NOW.md"))
        assert "PUBLIC-LEGACY" in public and "PRIVATE-LEGACY" not in public
        assert "SHARED-THREAD" in public and "LOCAL-THREAD" not in public
        assert "PRIVATE-LEGACY" in local and "LOCAL-THREAD" in local
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_legacy_allowlist_expansion_does_not_retro_promote():
    root = instance(public_tracks=["system"], legacy_public_tracks=["system"])
    try:
        journal = os.path.join(root, "state", JOURNAL_NOW)
        with open(journal, "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + event("LEGACY-PUBLIC", "system", second=1)
                    + event("LEGACY-MUST-STAY-PRIVATE", "novel", second=2))
        run_now(root, "render")
        public_path = os.path.join(root, "state", "NOW.md")
        assert "LEGACY-PUBLIC" in read(public_path)
        assert "LEGACY-MUST-STAY-PRIVATE" not in read(public_path)

        edit_config(root, lambda c: c["journal_visibility"]["public_tracks"].append("novel"))
        run_now(root, "render")
        assert "LEGACY-MUST-STAY-PRIVATE" not in read(public_path)

        run_now(root, "log", "[novel/state] EXPLICIT-NEW-PUBLIC-CAPSULE")
        public = read(public_path)
        assert "EXPLICIT-NEW-PUBLIC-CAPSULE" in public
        assert "LEGACY-MUST-STAY-PRIVATE" not in public
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_legacy_private_rows_create_overlay_without_existing_private_dir():
    root = instance(public_tracks=["system"], legacy_public_tracks=[])
    try:
        journal = os.path.join(root, "state", JOURNAL_NOW)
        with open(journal, "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + event("LEGACY-LOCAL-ONLY", "personal", second=1))
        assert not os.path.isdir(os.path.join(root, "_private"))
        run_now(root, "render")
        public = read(os.path.join(root, "state", "NOW.md"))
        local = read(os.path.join(root, "_private", "state", "NOW.md"))
        assert "LEGACY-LOCAL-ONLY" not in public
        assert "LEGACY-LOCAL-ONLY" in local
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_missing_config_fails_closed():
    root = instance(with_config=False)
    try:
        r = run_now(root, "log", "[system/state] NO-CONFIG-CANARY")
        assert r.stderr.count(FAIL_CLOSE_WARNING) == 1, r.stderr
        assert "config missing" in r.stderr
        assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
        assert "NO-CONFIG-CANARY" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
        # No config and no public page still give a usable local side, not a traceback.
        assert "NO-CONFIG-CANARY" in _hook_ctx(root).split("# Private overlay")[1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_schema_mismatch_warns_once_in_quiet_precompact():
    root = instance()
    try:
        edit_config(root, lambda c: c.update(schema_version=3))
        r = run_now(root, "precompact")
        assert r.stdout == ""
        assert r.stderr.count(FAIL_CLOSE_WARNING) == 1, r.stderr
        assert "schema=3" in r.stderr and "engine schema=4" in r.stderr
        assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
        assert "compaction occurred" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_utf8_hook_budget_and_overlay_fairness():
    root = instance()
    try:
        # Keep the injection tighter than the two snapshots so both sides must drop rows.
        edit_config(root, lambda c: c["thresholds"].update(now_hook_max_bytes=5000))
        public_journal = os.path.join(root, "state", JOURNAL_NOW)
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        private_journal = os.path.join(local_state, JOURNAL_NOW)
        with open(public_journal, "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + "".join(
                event(f"PUBLIC-{i:02d}-" + "공" * 240, second=i) for i in range(30)))
        with open(private_journal, "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + "".join(
                event(f"PRIVATE-{i:02d}-" + "로" * 240, second=i) for i in range(30)))
        run_now(root, "render")
        ctx = _hook_ctx(root)
        assert len(ctx.encode("utf-8")) <= 5000
        assert "# Public state" in ctx and "# Private overlay" in ctx
        # Each part's title is said once: the pages' own titles stay on disk.
        assert "# NOW" not in ctx, ctx
        # Both sides share the room: each keeps its newest events and reports what it dropped.
        public_part, local_part = ctx.split("# Private overlay", 1)
        assert "PUBLIC-29-" in public_part and "PRIVATE-29-" in local_part, ctx
        assert " older event line(s) omitted · the journal in state/ keeps them …]" in ctx and ctx.count(" older event line(s) omitted · the journal in state/ keeps them …]") <= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_multibyte_bodies_preserve_mandatory_snapshot_sections():
    root = instance()
    try:
        journal = os.path.join(root, "state", JOURNAL_NOW)
        with open(journal, "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + "".join(
                event("🙂" * 300, second=i) for i in range(10)))
        run_now(root, "render")
        public = read(os.path.join(root, "state", "NOW.md"))
        assert len(public.encode("utf-8")) <= 6000
        assert all(f"## {section}" in public for section in map(LIVE_NOW.token, PUBLIC_SECTION_TOKENS))
        assert "…" in public, "event bodies were not byte-clipped"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_project_block_is_an_input_of_the_state_page():
    """KIT-DR-093: the projects section is read from each project's README, so a new or changed block
    makes the page stale and a render shows it."""
    root = instance()
    try:
        run_now(root, "log", "[system/state] PROJECTS-INPUT")
        page = os.path.join(root, "state", "NOW.md")
        assert "- (no projects yet" in read(page)
        os.makedirs(os.path.join(root, "projects", "course"))
        with open(os.path.join(root, "projects", "course", "README.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: Course\narea: Teaching\nstatus: active\ncanonical: README.md\n---\n")
        assert run_now(root, "check", check=False).returncode != 0
        run_now(root, "render")
        assert "- in projects/: active course" in read(page), read(page)
        # A new name changes only the map, which the next session start then redraws.
        guide = os.path.join(root, "projects", "README.md")
        with open(guide, "w", encoding="utf-8") as f:
            f.write("# Projects\n\n<!-- projects:start -->\n<!-- projects:end -->\n")
        run_now(root, "render")
        with open(os.path.join(root, "projects", "course", "README.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: Evening course\narea: Teaching\nstatus: active\n---\n")
        assert run_now(root, "check", check=False).returncode != 0
        _hook_ctx(root)
        assert "[Evening course](course/)" in read(guide), read(guide)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_absent_overlay_stays_unavailable_and_is_not_created():
    root = instance()
    try:
        os.makedirs(os.path.join(root, "_private", "unrelated"), exist_ok=True)
        run_now(root, "log", "[system/state] PUBLIC-WITH-NO-LOCAL-STATE")
        ctx = _hook_ctx(root)
        assert "private overlay unavailable]" in ctx
        assert "PUBLIC-WITH-NO-LOCAL-STATE" in ctx
        # Most sections of a fresh instance are empty, and an empty section is not injected.
        assert not any(text in ctx for text in ("- (none)", "- (no shared threads)")), ctx
        assert "## " + LIVE_NOW.token("section_events") not in ctx and "now.py threads" not in ctx
        assert not os.path.exists(os.path.join(root, "_private", "state", "NOW.md"))
        # A local page whose only input went away is removed, so the hook and a manual read of
        # the local page agree that local state is unavailable.
        run_now(root, "log", "--private", "[system/decision] WITHDRAWN-LOCAL")
        local = os.path.join(root, "_private", "state")
        os.rename(os.path.join(local, JOURNAL_NOW), os.path.join(local, "withdrawn.txt"))
        # A public log renders only its side, yet must not leave the withdrawn local page behind.
        run_now(root, "log", "[system/state] PUBLIC-AFTER-WITHDRAW")
        assert not os.path.exists(os.path.join(local, "NOW.md"))
        assert "private overlay unavailable]" in _hook_ctx(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_corrupt_local_overlay_does_not_suppress_public_injection():
    root = instance()
    try:
        run_now(root, "log", "[system/state] PUBLIC-SURVIVES-LOCAL-CORRUPTION")
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        with open(os.path.join(local_state, JOURNAL_NOW), "w", encoding="utf-8") as f:
            f.write("# journal\n\n- malformed local event\n")
        r = run_now(root, "hook-context", check=False)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "PUBLIC-SURVIVES-LOCAL-CORRUPTION" in ctx
        assert "private overlay unavailable/corrupt]" in ctx
        assert "Do not assert that local state is absent" in ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_invalid_private_registry_is_explicitly_degraded():
    root = instance()
    try:
        run_now(root, "log", "[system/state] PUBLIC-WITH-DEGRADED-LOCAL")
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        with open(os.path.join(local_state, "threads.json"), "w", encoding="utf-8") as f:
            json.dump([42, {"key": "missing-name"}], f)
        ctx = _hook_ctx(root)
        assert "private overlay degraded]" in ctx
        assert "DEGRADED: local thread registry" in ctx
        assert "PUBLIC-WITH-DEGRADED-LOCAL" in ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_invalid_budget_config_fails_closed_without_empty_public_snapshot():
    mutations = (
        ("thresholds", "now_max_bytes", 0),
        ("thresholds", "now_hook_max_bytes", 0),
        ("thresholds", "now_tail_events", 0),
        ("thresholds", "now_recent_decisions", 0),
        (None, "journal_types", []),
    )
    for parent, key, value in mutations:
        root = instance()
        try:
            edit_config(root, lambda c: (c[parent] if parent else c).update({key: value}))
            token = "INVALID-CONFIG-" + key
            r = run_now(root, "log", f"[system/state] {token}", check=False)
            assert r.returncode == 0, r.stderr
            assert r.stderr.count(FAIL_CLOSE_WARNING) == 1, r.stderr
            assert not os.path.exists(os.path.join(root, "state", "NOW.md"))
            assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
            assert token in read(os.path.join(root, "_private", "state", JOURNAL_NOW))
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_config_warning_does_not_echo_invalid_values():
    root = instance()
    secret = "PRIVATE-WARNING-VALUE-CANARY"
    try:
        edit_config(root, lambda c: c.update(threads=[{"key": "x", "name": "x",
                                                         "visibility": secret}]))
        r = run_now(root, "log", "[system/state] SANITIZED-WARNING", check=False)
        assert r.returncode == 0, r.stderr
        assert r.stderr.count(FAIL_CLOSE_WARNING) == 1, r.stderr
        assert secret not in r.stderr
        # A name the row pattern refuses reaches the person through doctor, not as a schema migration.
        edit_config(root, lambda c: (c.update(threads=[]),
                                     c["journal_visibility"].update(public_tracks=["API"])))
        probe = ("import sys; sys.path.insert(0, sys.argv[1]); import doctor; "
                 "print(doctor.c_config()); print(doctor.c_schema())")
        rows = run_script(root, probe, HERE).stdout
        config_row, schema_row = rows.splitlines()[-2:]
        assert "public_tracks" in config_row and "v1" not in schema_row, rows
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_age_days_uses_local_calendar_boundary():
    root = tempfile.mkdtemp(prefix="calendar-age-")
    path = os.path.join(root, "cursor")
    zone = datetime.timezone(datetime.timedelta(hours=9))
    modified = datetime.datetime(2026, 8, 27, 23, 55, tzinfo=zone)
    now = datetime.datetime(2026, 8, 28, 0, 5, tzinfo=zone)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("cursor")
        os.utime(path, (modified.timestamp(), modified.timestamp()))
        assert LIVE_NOW._age_days(path, now=now) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_failed_journal_append_is_undone_and_reports_its_cause():
    root = tempfile.mkdtemp(prefix="append-undo-")
    when = datetime.datetime(2026, 11, 20, 9, 0, tzinfo=datetime.timezone.utc)
    try:
        jp = os.path.join(root, "journal-2026-11.md")
        LIVE_J.append("- first", jp, when)
        before = open(jp, "rb").read()
        # A full disk mid-append must leave no partial row, or the strict parser refuses the file.
        with mock.patch.object(LIVE_J.os, "fsync", side_effect=OSError(28, "No space left")):
            try:
                LIVE_J.append("- second", jp, when)
            except Exception as e:  # noqa: BLE001 - another cause is this test failing, not the runner
                assert isinstance(e, OSError) and e.errno == 28, e
            else:
                raise AssertionError("a failed append did not raise")
        assert open(jp, "rb").read() == before
        locked = os.path.join(root, "locked")
        os.makedirs(locked, mode=0o555)
        try:
            LIVE_J.append("- x", os.path.join(locked, "journal-2026-11.md"), when)
        except PermissionError:
            pass  # The cause, not the FileNotFoundError of undoing a file that was never made.
        else:
            raise AssertionError("append into a read-only folder did not fail")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stale_recovery_and_corruption_visibility():
    root = instance()
    try:
        run_now(root, "log", "[system/state] BEFORE-RECOVERY")
        jp = os.path.join(root, "state", JOURNAL_NOW)
        time.sleep(0.02)
        with open(jp, "a", encoding="utf-8") as f:
            f.write(event("RECOVERED-BY-HOOK", second=7))
            f.flush()
            os.fsync(f.fileno())
        ctx = _hook_ctx(root)
        assert "RECOVERED-BY-HOOK" in ctx

        old = open(os.path.join(root, "state", "NOW.md"), "rb").read()
        with open(jp, "a", encoding="utf-8") as f:
            f.write("- this looks like an event but is corrupt\n")
        r = run_now(root, "render", check=False)
        assert r.returncode != 0 and "corrupt" in r.stderr
        assert open(os.path.join(root, "state", "NOW.md"), "rb").read() == old
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_touch_then_render_clears_stale_marker():
    root = instance()
    try:
        run_now(root, "log", "[system/state] TOUCH-SEED")
        jp = os.path.join(root, "state", JOURNAL_NOW)
        # The page is bound to journal content, not file times: a touch alone changes nothing.
        st = os.stat(jp)
        os.utime(jp, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        assert _probe(root, "now._snapshot_stale('public')") == "False"
        with open(jp, "a", encoding="utf-8") as f:
            f.write(event("HAND-APPENDED", second=5))
        assert _probe(root, "now._snapshot_stale('public')") == "True"
        run_now(root, "render")
        assert _probe(root, "now._snapshot_stale('public')") == "False"
        # A hand edit of the generated page reads as stale too, so the next start renders it again.
        now_md = os.path.join(root, "state", "NOW.md")
        with open(now_md, "a", encoding="utf-8") as f:
            f.write("- a line nobody logged\n")
        assert _probe(root, "now._snapshot_stale('public', portable=True)") == "True"
        # check --repair re-renders a stale snapshot itself, so it reports nothing afterwards.
        after = run_now(root, "check", "--issues", "--repair")
        assert "now-input-newer" not in after.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_broken_visibility_config_freezes_public_snapshot():
    root = instance()
    try:
        run_now(root, "log", "[system/state] GOOD-BEFORE-CONFIG-BREAK")
        public_now = os.path.join(root, "state", "NOW.md")
        before = open(public_now, "rb").read()
        with open(os.path.join(root, "instance", "config.json"), "a", encoding="utf-8") as f:
            f.write("}garbage")
        r = run_now(root, "render", check=False)
        assert r.returncode != 0 and "visibility" in r.stderr
        assert open(public_now, "rb").read() == before
        run_now(root, "log", "[system/state] FAIL-CLOSED-NEW-EVENT")
        assert open(public_now, "rb").read() == before
        assert "FAIL-CLOSED-NEW-EVENT" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
        # Session start says public state is unavailable and repeats none of the frozen page. The
        # local side reads only the local journal: tracked rows would all classify as local.
        r = run_now(root, "hook-context", check=False)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "GOOD-BEFORE-CONFIG-BREAK" not in ctx and "instance/config.json" in ctx, ctx
        assert "FAIL-CLOSED-NEW-EVENT" in ctx.split("# Private overlay")[1], ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_policy_change_invalidates_public_snapshot():
    root = instance()
    try:
        os.makedirs(os.path.join(root, "_private", "state"), exist_ok=True)
        run_now(root, "log", "[system/state] POLICY-CHANGE-CANARY")
        public_now = os.path.join(root, "state", "NOW.md")
        assert "POLICY-CHANGE-CANARY" in read(public_now)

        edit_config(root, lambda c: c["journal_visibility"].update(public_tracks=["research"]))

        run_now(root, "hook-context")
        assert "POLICY-CHANGE-CANARY" not in read(public_now), \
            "SessionStart reused a projection rendered under an older visibility policy"
        assert "POLICY-CHANGE-CANARY" in read(
            os.path.join(root, "_private", "state", "NOW.md"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_private_registry_change_invalidates_local_snapshot():
    root = instance()
    try:
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        registry = os.path.join(local_state, "threads.json")
        with open(registry, "w", encoding="utf-8") as f:
            json.dump([{"key": "a", "name": "LOCAL-THREAD-A", "dossier": "a.md"}], f)
        run_now(root, "render")
        local_now = os.path.join(local_state, "NOW.md")
        assert "LOCAL-THREAD-A" in read(local_now)

        with open(registry, "w", encoding="utf-8") as f:
            json.dump([{"key": "b", "name": "LOCAL-THREAD-B", "dossier": "b.md"}], f)
        run_now(root, "hook-context")
        local = read(local_now)
        assert "LOCAL-THREAD-B" in local and "LOCAL-THREAD-A" not in local
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_public_hook_survives_post_import_private_registry_change():
    root = instance()
    try:
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        registry = os.path.join(local_state, "threads.json")
        with open(registry, "w", encoding="utf-8") as f:
            json.dump([{"key": "a", "name": "LOCAL-A", "dossier": "a.md"}], f)
        run_now(root, "log", "[system/state] PUBLIC-BEFORE-REGISTRY-RACE")
        run_now(root, "render")
        journal = os.path.join(root, "state", JOURNAL_NOW)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(event("PUBLIC-AFTER-REGISTRY-RACE", second=8))
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
now.C.threads()  # the process reads the registry before it changes
json.dump([{{'key': 'b', 'name': 'LOCAL-B', 'dossier': 'b.md'}}],
          open({registry!r}, 'w', encoding='utf-8'), ensure_ascii=False)
raise SystemExit(now.hook_context())
"""
        r = run_script(root, script)
        assert r.returncode == 0, r.stdout + r.stderr
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "PUBLIC-AFTER-REGISTRY-RACE" in ctx
        # The process shows the registry it loaded; the page it wrote names that registry, so
        # the next start renders the new one.
        assert "LOCAL-B" not in ctx
        assert "LOCAL-B" in _hook_ctx(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_structurally_invalid_config_fails_closed_without_import_crash():
    root = instance()
    try:
        with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        r = run_now(root, "log", "[system/state] ROOT-LIST-CONFIG", check=False)
        assert r.returncode == 0, r.stderr
        assert "ROOT-LIST-CONFIG" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
        assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = instance()
    try:
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        with open(os.path.join(local_state, "threads.json"), "w", encoding="utf-8") as f:
            json.dump([42, {"key": "missing-name"}], f)
        r = run_now(root, "log", "--private", "[system/state] BAD-THREAD-REGISTRY", check=False)
        assert r.returncode == 0, r.stderr
        assert "BAD-THREAD-REGISTRY" in read(os.path.join(local_state, JOURNAL_NOW))
        assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_change_after_import_aborts_before_public_mutation():
    root = instance()
    try:
        run_now(root, "log", "[system/state] CONFIG-RACE-SEED")
        journal = os.path.join(root, "state", JOURNAL_NOW)
        before = open(journal, "rb").read()
        cfg_path = os.path.join(root, "instance", "config.json")
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
now.C.data()  # the process reads the config before it changes
path = {cfg_path!r}
cfg = json.load(open(path, encoding='utf-8'))
cfg['journal_visibility']['public_tracks'] = ['research']
json.dump(cfg, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
raise SystemExit(now.log('[system/state] MUST-NOT-USE-STALE-POLICY', quiet=True))
"""
        r = run_script(root, script)
        assert r.returncode != 0 and "config" in r.stderr
        assert open(journal, "rb").read() == before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_month_boundary_pins_one_journal_for_append():
    root = instance()
    try:
        august_path = os.path.join(root, "state", "journal-2026-08.md")
        september_path = os.path.join(root, "state", "journal-2026-09.md")
        script = f"""
import datetime, os, sys, time
# log() reads the clock in the local zone; pin it so the +09:00 instants stay on their dates.
os.environ["TZ"] = "Asia/Seoul"
time.tzset()
sys.path.insert(0, {HERE!r})
import now
real_datetime = datetime.datetime
zone = datetime.timezone(datetime.timedelta(hours=9))
august = real_datetime(2026, 8, 31, 23, 59, 59, tzinfo=zone)
september = real_datetime(2026, 9, 1, 0, 0, 0, tzinfo=zone)
class RolloverDateTime(real_datetime):
    calls = 0
    @classmethod
    def now(cls, tz=None):
        cls.calls += 1
        value = august if cls.calls <= 2 else september
        return value if tz is None else value.astimezone(tz)
now.datetime.datetime = RolloverDateTime
now._render_unlocked = lambda scope: None
rc = now.log('[system/state] MONTH-BOUNDARY-AUGUST', quiet=True)
ok = (rc == 0 and '2026-08-31T23:59:59' in open({august_path!r}).read()
      and not os.path.exists({september_path!r}) and RolloverDateTime.calls == 1)
raise SystemExit(0 if ok else 9)
"""
        r = run_script(root, script)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_change_during_render_leaves_a_stale_page():
    root = instance()
    try:
        run_now(root, "log", "[system/state] RENDER-RACE-SEED")
        now_path = os.path.join(root, "state", "NOW.md")
        before = open(now_path, "rb").read()
        journal = os.path.join(root, "state", JOURNAL_NOW)
        with open(journal, "a", encoding="utf-8") as f:
            # After the legacy cutoff, so the new policy decides where this row belongs.
            f.write("- 2026-11-01T10:00:00+09:00 [system/state] MUST-NOT-PUBLISH\n")
        cfg_path = os.path.join(root, "instance", "config.json")
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
real = now._snapshot
def racing_snapshot(scope, entries, fingerprint):
    text = real(scope, entries, fingerprint)
    cfg = json.load(open({cfg_path!r}, encoding='utf-8'))
    cfg['journal_visibility']['public_tracks'] = ['research']
    json.dump(cfg, open({cfg_path!r}, 'w', encoding='utf-8'), ensure_ascii=False)
    return text
now._snapshot = racing_snapshot
now.render()
"""
        r = run_script(root, script)
        assert r.returncode == 0, r.stderr
        assert b"MUST-NOT-PUBLISH" not in before
        # The page names the policy it was rendered under, so the next start renders it again
        # under the new one, where the system track is local.
        assert _probe(root, "now._snapshot_stale('public')") == "True"
        run_now(root, "hook-context")
        assert "MUST-NOT-PUBLISH" not in read(now_path)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_page_from_an_older_engine_is_rendered_again():
    root = instance()
    code = tempfile.mkdtemp(prefix="state-runtime-code-")
    try:
        os.makedirs(os.path.join(code, "lib"))
        for name in ("now.py", "lib/config.py", "enforce.py", "lib/hook_input.py", "lib/journal.py",
                     "lib/paths.py", "lib/runlog.py", "lib/safeio.py"):
            shutil.copy2(os.path.join(HERE, name), os.path.join(code, name))
        copied_now = os.path.join(code, "now.py")
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        subprocess.run([sys.executable, copied_now, "log", "[system/state] SOURCE-RACE-SEED"],
                       check=True, capture_output=True, text=True, env=env, cwd=root)
        now_path = os.path.join(root, "state", "NOW.md")
        before = open(now_path, "rb").read()
        journal = os.path.join(root, "state", JOURNAL_NOW)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(event("SOURCE-MUST-NOT-PUBLISH", second=4))
        script = f"""
import sys
sys.path.insert(0, {code!r})
import now
real = now._snapshot
def racing_snapshot(scope, entries, fingerprint):
    text = real(scope, entries, fingerprint)
    with open(now.__file__, 'a', encoding='utf-8') as f:
        f.write('\\n# concurrent source edit\\n')
    return text
now._snapshot = racing_snapshot
raise SystemExit(now.render())
"""
        r = run_script(root, script)
        assert r.returncode == 0, r.stderr
        assert b"SOURCE-MUST-NOT-PUBLISH" not in before
        # The page carries the hash of the engine that rendered it; the edited engine renders again.
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                            "import now; print(now._snapshot_stale('public'))", code],
                           capture_output=True, text=True, env=env, cwd=root)
        assert r.stdout.strip() == "True", r.stdout + r.stderr
    finally:
        shutil.rmtree(code, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_render_failure_keeps_logged_event():
    # A render failure keeps the recorded event: the caller gets success plus a warning, so
    # nothing retries and the event is stored exactly once.
    script = f"""
import sys
sys.path.insert(0, {HERE!r})
import now
if sys.argv[1] == 'publish':
    def fail(path, text, mode=None):
        raise OSError('injected publish failure')
    now.safeio.atomic_write = fail
first = now.log('[system/state] KEPT-EXACTLY-ONCE', quiet=True)
count = open(now.P.journal_file(), encoding='utf-8').read().count('KEPT-EXACTLY-ONCE')
raise SystemExit(0 if first == 0 and count == 1 else 9)
"""
    for broken in ("publish", "canonical"):
        root = instance()
        try:
            if broken == "canonical":
                canon = _with_track(root)
                with open(canon, "wb") as f:
                    f.write(b"# system\n\xff broken byte\n")
            r = run_script(root, script, broken)
            assert r.returncode == 0, broken + ": " + r.stdout + r.stderr
            if broken == "publish":
                assert "injected publish failure" in r.stderr, r.stderr
            else:
                r = run_now(root, "precompact", "--runtime", "claude", check=False)
                assert r.returncode == 0, r.stderr
                assert "(claude" in read(os.path.join(root, "state", JOURNAL_NOW))
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_portable_fingerprint_ignores_calendar_day():
    root = instance()
    try:
        run_now(root, "log", "[system/state] CALENDAR-DAY-SEED")
        script = f"""
import datetime, sys
sys.path.insert(0, {HERE!r})
import now
real = datetime.datetime
class Tomorrow(real):
    @classmethod
    def now(cls, tz=None):
        return real.now(tz) + datetime.timedelta(days=1)
assert now._snapshot_stale('public', portable=True) is False
now.datetime.datetime = Tomorrow
portable = now._snapshot_stale('public', portable=True)
live = now._snapshot_stale('public')
raise SystemExit(0 if portable is False and live is True else 9)
"""
        r = run_script(root, script)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_rerenders_after_date_change():
    root = instance()
    try:
        run_now(root, "log", "[system/state] MIDNIGHT-SEED")
        script = f"""
import contextlib, datetime, io, sys
sys.path.insert(0, {HERE!r})
import now
real = datetime.datetime
class Tomorrow(real):
    @classmethod
    def now(cls, tz=None):
        return real.now(tz) + datetime.timedelta(days=1)
def marker():
    return now._MARKER_RE.findall(open(now.P.now_page(), encoding='utf-8').read())
before = marker()
now.datetime.datetime = Tomorrow
out = io.StringIO()
with contextlib.redirect_stdout(out):
    now.check(issues=True, repair=True)
text = out.getvalue()
print(text)
ok = ('\\nnow-input-newer\\t' not in '\\n' + text) and marker() != before
raise SystemExit(0 if ok else 9)
"""
        r = run_script(root, script)
        assert r.returncode == 0, r.stdout + r.stderr
        # An old NOW.md file time alone is not a finding: check re-renders a stale snapshot, and
        # journal-stale reports human inactivity.
        old = time.time() - 8 * 86400
        os.utime(os.path.join(root, "state", "NOW.md"), (old, old))
        out = run_now(root, "check", "--issues", "--repair", check=False).stdout
        assert "now-stale" not in out and "now-input-newer" not in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_without_repair_never_writes_snapshots():
    """doctor, the gardener and gate status measure with plain check; only the Stop check repairs."""
    root = instance()
    try:
        run_now(root, "log", "[system/state] READ-ONLY-CHECK-SEED")
        jp = [os.path.join(root, "state", f) for f in os.listdir(os.path.join(root, "state"))
              if f.startswith("journal-")][0]
        with open(jp, "a", encoding="utf-8") as f:
            f.write(event("WRITTEN-AFTER-RENDER", second=6))
        # Two minutes on, so the journal time cannot coincide with the render time in the message.
        later = time.time() + 120
        os.utime(jp, (later, later))
        now_md = os.path.join(root, "state", "NOW.md")
        before = open(now_md, "rb").read()
        out = run_now(root, "check", "--issues", check=False).stdout
        assert open(now_md, "rb").read() == before
        assert "\nnow-input-newer\t" in "\n" + out, out
        # The message says what changed (the journal, and when) instead of guessing a cause.
        written = datetime.datetime.fromtimestamp(later).strftime("%Y-%m-%d %H:%M")
        assert f"the journal was written at {written}" in out, out
        assert LIVE_NOW.STALE_OTHER not in out, out
        # Only the Stop path asks for --repair; status (like release and baseline) measures plainly.
        probe = r"""
import sys
sys.path.insert(0, sys.argv[1])
import gate
seen = []
gate._issues = lambda c, **kw: (seen.append(list(c)), gate.Checked(set()))[1]
gate.cmd_status()
plain = [c for c in seen if "now.py" in " ".join(c)]
seen.clear()
gate.measure(repair=True)
fixed = [c for c in seen if "now.py" in " ".join(c)]
ok = plain and fixed and all("--repair" not in c for c in plain) and all("--repair" in c for c in fixed)
raise SystemExit(0 if ok else 9)
"""
        r = run_script(root, probe, HERE)
        assert r.returncode == 0, r.stdout + r.stderr
        assert open(now_md, "rb").read() == before
        out = run_now(root, "check", "--issues", "--repair", check=False).stdout
        assert open(now_md, "rb").read() != before
        assert "now-input-newer" not in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_month_rollover_with_old_previous_journal_is_advisory():
    root = instance()
    try:
        first = datetime.datetime.now().astimezone().replace(
            day=1, hour=12, minute=0, second=0, microsecond=0)
        last_prev = first - datetime.timedelta(days=1)
        prev = os.path.join(root, "state", "journal-%s.md" % last_prev.strftime("%Y-%m"))
        with open(prev, "w", encoding="utf-8") as f:
            f.write("# journal %s\n\n- %s [system/state] PREVIOUS-MONTH\n"
                    % (last_prev.strftime("%Y-%m"), last_prev.isoformat(timespec="seconds")))
        old = time.time() - 5 * 86400
        os.utime(prev, (old, old))
        run_now(root, "render")
        out = run_now(root, "check", "--issues", check=False).stdout
        assert "\n~journal-" in "\n" + out, out
        assert "\njournal-absent\t" not in "\n" + out, out
        assert "#issues 0" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unterminated_tail_refuses_append_without_merging():
    root = instance()
    try:
        run_now(root, "log", "[system/state] COMPLETE-SEED")
        jp = os.path.join(root, "state", JOURNAL_NOW)
        with open(jp, "ab") as f:
            f.write(b"- 2026-08-26T23:59")
        before = open(jp, "rb").read()
        r = run_now(root, "log", "[system/state] MUST-NOT-MERGE", check=False)
        # A cut-off row is corrupt to the strict parser, which refuses before the append.
        assert r.returncode != 0 and "corrupt" in r.stderr, r.stderr
        assert open(jp, "rb").read() == before
        assert b"MUST-NOT-MERGE" not in before
        # A complete row that only lacks its newline is refused too, naming the missing newline.
        with open(jp, "wb") as f:
            f.write(before[:-len(b"- 2026-08-26T23:59")].rstrip(b"\n"))
        before = open(jp, "rb").read()
        r = run_now(root, "log", "[system/state] MUST-NOT-MERGE", check=False)
        assert r.returncode != 0 and "newline" in r.stderr, r.stderr
        assert open(jp, "rb").read() == before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_strict_parser_rejects_schema_invalid_event():
    for line in (event("INVALID-TYPE", typ="notallowed", second=9).rstrip("\n"),
                 "- 2026-08-26T23:40:09 [system/state] NO-TIMEZONE"):
        root = instance()
        try:
            run_now(root, "log", "[system/state] SCHEMA-SEED")
            public_now = os.path.join(root, "state", "NOW.md")
            old = open(public_now, "rb").read()
            assert LIVE_J.validate_line(line) is not None, line
            with open(os.path.join(root, "state", JOURNAL_NOW), "a", encoding="utf-8") as f:
                f.write(line + "\n")
            r = run_now(root, "render", check=False)
            assert r.returncode != 0 and "corrupt" in r.stderr, (line, r.stderr)
            assert open(public_now, "rb").read() == old, line
            issues = run_now(root, "check", "--issues")
            assert "journal-corrupt" in issues.stdout, (line, issues.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_private_thread_key_collisions_cannot_change_public_projection():
    root = instance(threads=[
        {"key": "shared", "name": "PUBLIC-SHARED", "dossier": "shared.md"},
    ])
    try:
        run_now(root, "log", "[system/state] PUBLIC-COLLISION-SEED")
        public_now = os.path.join(root, "state", "NOW.md")
        before = open(public_now, "rb").read()
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        with open(os.path.join(local_state, "threads.json"), "w", encoding="utf-8") as f:
            json.dump([
                {"key": "shared", "name": "LOCAL-MUST-NOT-SHADOW", "dossier": "x.md"},
                {"key": "dup", "name": "LOCAL-FIRST", "dossier": "first.md"},
                {"key": "dup", "name": "LOCAL-SECOND", "dossier": "second.md"},
            ], f)
        ctx = _hook_ctx(root)
        assert open(public_now, "rb").read() == before
        assert "PUBLIC-SHARED" in ctx and "LOCAL-MUST-NOT-SHADOW" not in ctx
        assert "LOCAL-FIRST" in ctx and "LOCAL-SECOND" not in ctx
        assert "private overlay degraded]" in ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_atomic_write_preserves_old_on_replace_failure():
    root = tempfile.mkdtemp(prefix="atomic-write-")
    try:
        target = os.path.join(root, "NOW.md")
        with open(target, "w", encoding="utf-8") as f:
            f.write("OLD-COMPLETE")
        with mock.patch("os.replace", side_effect=OSError("fault-before-replace")):
            try:
                LIVE_SAFEIO.atomic_write(target, "NEW-COMPLETE")
            except OSError:
                pass
            else:
                raise AssertionError("fault injection did not propagate")
        assert read(target) == "OLD-COMPLETE"
        assert not [x for x in os.listdir(root) if x != "NOW.md"], "temporary file leaked"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_parallel_writers_exactly_once():
    root = instance()
    try:
        procs = []
        for i in range(12):
            private = i % 2 == 1
            args = [sys.executable, NOW, "log"]
            if private:
                args.append("--private")
            args.append(f"[system/artifact] PARALLEL-{i:02d}")
            env = dict(os.environ, MOTTORI_INSTANCE=root)
            procs.append(subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True, env=env, cwd=root))
        failures = []
        for p in procs:
            out, err = p.communicate(timeout=30)
            if p.returncode:
                failures.append(f"exit={p.returncode} {out} {err}")
        assert not failures, failures
        public = read(os.path.join(root, "state", JOURNAL_NOW))
        private = read(os.path.join(root, "_private", "state", JOURNAL_NOW))
        combined = public + private
        for i in range(12):
            assert combined.count(f"PARALLEL-{i:02d}") == 1
        assert public.count("# journal") == 1 and private.count("# journal") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_render_transaction_prevents_stale_last_writer():
    root = instance(public_tracks=["system"])
    # This process renders the fixture instance itself; its config is read again on first use.
    os.environ["MOTTORI_INSTANCE"] = root
    LIVE_C.reload()
    try:
        with open(os.path.join(root, "state", JOURNAL_NOW), "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + event("A-BASE", second=1))

        entered, release = threading.Event(), threading.Event()
        original = LIVE_SAFEIO.atomic_write

        def blocked(path, text, mode=None):
            if threading.current_thread().name == "old-render" and path == LIVE_P.now_page():
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test release timeout")
            return original(path, text, mode)

        with mock.patch.object(LIVE_SAFEIO, "atomic_write", blocked):
            a = threading.Thread(target=LIVE_NOW.render, name="old-render")
            a.start()
            assert entered.wait(5), "renderer never reached publish seam"
            result = []
            b = threading.Thread(target=lambda: result.append(
                LIVE_NOW.log("[system/state] B-NEW", quiet=True)), name="new-log")
            b.start()
            time.sleep(0.1)
            release.set()
            a.join(5)
            b.join(5)
            assert not a.is_alive() and not b.is_alive() and result == [0]
        assert "B-NEW" in read(LIVE_P.now_page())
    finally:
        os.environ["MOTTORI_INSTANCE"] = _IMPORT_ROOT
        LIVE_C.reload()
        shutil.rmtree(root, ignore_errors=True)


def test_hook_internal_failure_is_nonzero():
    root = instance()
    try:
        # A state folder that is a file leaves no lock to take: the hook must fail loudly.
        shutil.rmtree(os.path.join(root, "state"))
        open(os.path.join(root, "state"), "w").close()
        r = run_now(root, "hook-context", check=False)
        assert r.returncode != 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _journal_text(root):
    out = ""
    for rel in (("state", JOURNAL_NOW), ("_private", "state", JOURNAL_NOW)):
        path = os.path.join(root, *rel)
        if os.path.exists(path):
            out += read(path)
    return out


def test_precompact_tags_runtime_and_session_hash():
    root = instance()
    try:
        r = run_now(root, "precompact", "--runtime", "claude", stdin=json.dumps({"session_id": "sess-123"}))
        assert r.stdout == ""
        expected = hashlib.sha256(b"sess-123").hexdigest()[:8]
        assert f"compaction occurred (claude · s:{expected})" in _journal_text(root), _journal_text(root)
        run_now(root, "precompact", "--runtime", "codex")
        assert "compaction occurred (codex · s:unknown)" in _journal_text(root)
        run_now(root, "precompact", stdin="not json at all")
        assert "compaction occurred (unknown · s:unknown)" in _journal_text(root)
        run_now(root, "precompact", "--runtime", "Bad Runtime!", stdin="{}")
        assert _journal_text(root).count("(unknown · s:unknown)") == 2
        # One byte then an open pipe: readiness for the first byte is not end of input.
        p = subprocess.Popen([sys.executable, NOW, "precompact"], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=root,
                             env=dict(os.environ, MOTTORI_INSTANCE=root))
        p.stdin.write(b"{")
        p.stdin.flush()
        try:
            assert p.wait(timeout=10) == 0
        finally:
            p.kill()
            p.stdin.close()
            p.wait()
        assert _journal_text(root).count("(unknown · s:unknown)") == 3
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _long_journal(path, prefix, n, newest_decision, filler):
    """Write n events: mostly artifacts, a decision every 50 lines, compactions in between."""
    lines = ["# journal\n\n"]
    start = datetime.datetime(2026, 11, 1, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    for i in range(n):
        ts = (start + datetime.timedelta(minutes=i)).isoformat(timespec="seconds")
        if i == n - 20:
            body, typ = newest_decision, "decision"
        elif i % 50 == 0:
            body, typ = f"{prefix}-OLD-DECISION-{i:04d} " + filler * 60, "decision"
        elif i % 7 == 0:
            body, typ = "compaction occurred (claude · s:unknown) — context after this point is a summary", "state"
        else:
            body, typ = f"{prefix}-EVENT-{i:04d} " + filler * 60, "artifact"
        lines.append(f"- {ts} [system/{typ}] {body}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(lines))


def test_hook_context_keeps_dossiers_and_newest_decisions_with_long_journals():
    public_threads = [{"key": f"pub{i}", "name": f"PUBLIC-THREAD-{i}", "dossier": f"research/pub{i}.md"}
                      for i in range(5)]
    # travel may be journaled publicly but is not a registered track.
    root = instance(threads=public_threads, public_tracks=["system", "research", "travel"])
    try:
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        with open(os.path.join(local_state, "threads.json"), "w", encoding="utf-8") as f:
            json.dump([{"key": f"loc{i}", "name": f"LOCAL-THREAD-{i}",
                        "dossier": f"_private/loc{i}.md"} for i in range(3)], f)
        _long_journal(os.path.join(root, "state", JOURNAL_NOW), "PUB", 1000,
                      "PUB-NEWEST-DECISION", "공")
        # A long session that left a topic: its one decision, ten days before the newest of 21
        # decisions on the busy topic, predates 1000 busy rows. The topic is not registered. A
        # registered topic whose decision is twenty days old holds no place.
        edit_config(root, lambda c: c.update(tracks=[
            {"key": "research", "name": "Research", "canonical": "research/README.md"}]))
        with open(os.path.join(root, "state", JOURNAL_NOW), "r+", encoding="utf-8") as f:
            rows = f.read().replace("\n\n", "\n\n- 2026-10-12T16:20:00+09:00 "
                                    "[research/decision] STALE-TOPIC-DECISION\n"
                                    "- 2026-10-22T16:20:00+09:00 "
                                    "[travel/decision] OLDER-TOPIC-DECISION\n", 1)
            f.seek(0)
            f.write(rows)
        _long_journal(os.path.join(local_state, JOURNAL_NOW), "LOC", 1000,
                      "LOC-NEWEST-DECISION", "로")
        run_now(root, "render")
        ctx = _hook_ctx(root)
        assert len(ctx.encode("utf-8")) <= 6000
        assert ctx.startswith("[state injection · journal "), ctx[:80]
        assert "private overlay available]" in ctx.splitlines()[0]
        assert "# Public state" in ctx and "# Private overlay" in ctx
        public_part, local_part = ctx.split("# Private overlay", 1)
        for i in range(5):
            assert f"PUBLIC-THREAD-{i}: dossier `research/pub{i}.md`" in public_part, i
        for i in range(3):
            assert f"LOCAL-THREAD-{i}: dossier `_private/loc{i}.md`" in local_part, i
        assert "## Canonical pointers" in public_part and "## Track status" in public_part
        assert "PUB-NEWEST-DECISION" in public_part, public_part
        assert "OLDER-TOPIC-DECISION" in public_part, public_part
        now_page = read(os.path.join(root, "state", "NOW.md"))
        assert "OLDER-TOPIC-DECISION" in now_page, now_page
        assert "STALE-TOPIC-DECISION" not in now_page and "STALE-TOPIC-DECISION" not in ctx
        assert "LOC-NEWEST-DECISION" in local_part, local_part
        # File-management lines stay in NOW but carry nothing the model can act on.
        assert "sha256:" not in ctx and "Do not edit by hand" not in ctx
        assert "middle cut" not in ctx
        assert re.search(r"\[… \d+ older event line\(s\) omitted[^\]]*\]", ctx), ctx
        # Decisions are kept newest first: no older decision survives while a newer one is dropped.
        kept = [int(x) for x in re.findall(r"PUB-OLD-DECISION-(\d{4})", public_part)]
        listed = [int(x) for x in re.findall(r"PUB-OLD-DECISION-(\d{4})",
                                             read(os.path.join(root, "state", "NOW.md")))]
        assert kept == listed[len(listed) - len(kept):], (kept, listed)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # More topics than places: the newest row of each topic competes, and the newest of those win
    # over a busy topic's older rows.
    day = datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc)
    rows = [{"ts": (day + datetime.timedelta(hours=i)).isoformat(), "track": f"topic{min(i, 3)}",
             "type": "decision", "body": f"T{i}"} for i in range(6)]
    decisions, _recent = LIVE_NOW._event_sections(rows, 3, 0)
    assert [e["body"] for e in decisions] == ["T1", "T2", "T5"], decisions
    # A correction competes with the decision it corrects; when one place is left the newer wins.
    rows = [{"ts": f"2026-11-20T09:{m:02d}:00+09:00", "track": "system", "type": typ, "body": body}
            for m, typ, body in [(0, "decision", "Monday"), (1, "correction", "Tuesday")]
            + [(10 + i, "lesson", f"note {i}") for i in range(12)]]
    assert [e["body"] for e in LIVE_NOW._event_sections(rows, 8, 12)[0]] == ["Monday", "Tuesday"]
    assert [e["body"] for e in LIVE_NOW._event_sections(rows, 1, 12)[0]] == ["Tuesday"]


def _dossier_note_count(text):
    """Return the omitted-dossier count named in a state body, or 0 when no note is present."""
    found = re.findall(r"\[(\d+) dossier\(s\) omitted · `python3 tools/now\.py threads`", text)
    assert len(found) <= 1, found
    return int(found[0]) if found else 0


def test_hook_context_names_omitted_dossiers_when_both_lists_are_long():
    public_threads = [{"key": f"pub{i}", "name": f"PUBLIC-{i:02d}-" + "P" * 70,
                       "dossier": f"research/pub{i}.md"} for i in range(28)]
    root = instance(threads=public_threads)
    try:
        local_state = os.path.join(root, "_private", "state")
        os.makedirs(local_state, exist_ok=True)
        with open(os.path.join(local_state, "threads.json"), "w", encoding="utf-8") as f:
            json.dump([{"key": f"loc{i}", "name": f"LOCAL-{i:02d}-" + "L" * 70,
                        "dossier": f"_private/loc{i}.md"} for i in range(28)], f)
        run_now(root, "log", "[system/decision] PUBLIC-NEWEST")
        run_now(root, "log", "--private", "[system/decision] LOCAL-NEWEST")
        ctx = _hook_ctx(root)
        assert len(ctx.encode("utf-8")) <= 6000
        assert ctx.startswith("[state injection · journal "), ctx[:80]
        public_part, local_part = ctx.split("# Private overlay", 1)
        assert "PUBLIC-NEWEST" in public_part and "LOCAL-NEWEST" in local_part, ctx
        assert "middle cut" not in ctx
        for part, prefix in ((public_part, "PUBLIC"), (local_part, "LOCAL")):
            shown = set(re.findall(prefix + r"-(\d\d)-", part))
            omitted = _dossier_note_count(part)
            assert omitted > 0 and len(shown) + omitted == 28, (prefix, len(shown), omitted)
            # The list is cut from its end: the first rows stay.
            assert shown == {f"{i:02d}" for i in range(len(shown))}, shown
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_context_survives_sixty_long_dossier_names_on_one_side():
    threads = [{"key": f"p{i}", "name": f"public dossier {i} " + "x" * 70,
                "dossier": f"research/p{i}.md"} for i in range(60)]
    root = instance(threads=threads)
    try:
        run_now(root, "log", "[system/decision] NEWEST-DECISION")
        now_text = read(os.path.join(root, "state", "NOW.md"))
        assert len(now_text.encode("utf-8")) <= 6000
        assert "NEWEST-DECISION" in now_text
        listed = len(re.findall(r"public dossier \d+ ", now_text))
        assert listed + _dossier_note_count(now_text) == 60, listed
        result = run_now(root, "hook-context", check=False)
        assert result.returncode == 0, result.stderr
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert len(ctx.encode("utf-8")) <= 6000
        assert ctx.startswith("[state injection · journal "), ctx[:80]
        assert "NEWEST-DECISION" in ctx and "## Canonical pointers" in ctx, ctx
        listed = len(re.findall(r"public dossier \d+ ", ctx))
        assert listed + _dossier_note_count(ctx) == 60, listed
        # A tighter hook budget drops more names but still keeps the reopen command.
        edit_config(root, lambda c: c["thresholds"].update(now_hook_max_bytes=1500,
                                                           now_max_bytes=1500))
        run_now(root, "render")
        ctx = _hook_ctx(root)
        assert len(ctx.encode("utf-8")) <= 1500, len(ctx.encode("utf-8"))
        assert "NEWEST-DECISION" in ctx and _dossier_note_count(ctx) > 0, ctx
        listed = len(re.findall(r"public dossier \d+ ", ctx))
        assert listed + _dossier_note_count(ctx) == 60, (listed, ctx)
        en = run_now(root, "context").stdout
        assert "tools/now.py threads" in en, en
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_context_keeps_long_event_lines_whole():
    root = instance()
    try:
        jp = os.path.join(root, "state", JOURNAL_NOW)
        lines = ["# journal\n\n"]
        for i in range(12):
            lines.append(f"- 2026-11-01T10:{i:02d}:00+09:00 [system/artifact] SMALL-{i:02d}\n")
        lines.append("- 2026-11-01T11:00:00+09:00 [system/artifact] HUGE-" + "🙂" * 290 + "\n")
        with open(jp, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        # A small budget makes one 1.2KB event a large share of the room.
        edit_config(root, lambda c: c["thresholds"].update(now_hook_max_bytes=2600))
        run_now(root, "render")
        ctx = _hook_ctx(root)
        assert len(ctx.encode("utf-8")) <= 2600
        ctx.encode("utf-8").decode("utf-8")
        huge = [line for line in ctx.splitlines() if "HUGE-" in line]
        # A cut row lost the end of a decision; the row goes in whole and older rows give way.
        assert len(huge) == 1 and "🙂" * 290 in huge[0], huge
        assert "SMALL-11" in ctx and "SMALL-10" in ctx, ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_snapshot_drops_compactions_from_decisions_and_dedups_recent():
    root = instance()
    try:
        jp = os.path.join(root, "state", JOURNAL_NOW)
        lines = ["- 2026-09-02T21:00:00+09:00 [system/decision] REAL-ALPHA\n"]
        for i in range(5):
            rt = "codex" if i % 2 == 0 else "claude"
            lines.append(f"- 2026-09-02T21:{10 + i:02d}:00+09:00 [system/state] compaction occurred ({rt} · s:deadbeef) — context after this point is a summary\n")
        lines.append("- 2026-09-02T21:30:00+09:00 [system/state] REAL-BETA\n")
        lines.append("- 2026-09-02T21:35:00+09:00 [system/artifact] PLAIN-ARTIFACT\n")
        lines.append("- 2026-09-02T21:40:00+09:00 [system/state] compaction occurred — context after this point is a summary\n")
        lines.append("- 2026-09-02T21:41:00+09:00 [system/state] compaction occurred (claude · s:unknown) — context after this point is a summary\n")
        lines.append("- 2026-09-02T21:50:00+09:00 [system/state] REAL-GAMMA\n")
        lines.append("- 2026-09-02T21:55:00+09:00 [system/state] compaction occurred (claude · s:unknown) — context after this point is a summary\n")
        # A compaction dated now: freshness must still follow REAL-GAMMA, not this row.
        fresh = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
        lines.append(f"- {fresh} [system/state] compaction occurred (claude · s:unknown) — context after this point is a summary\n")
        with open(jp, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        decisions = now.split("## Recent decisions and phases")[1].split("## Recent events")[0]
        recent = now.split("## Recent events")[1].split("## Canonical pointers")[0]
        assert "compaction" not in decisions, decisions
        for token in ("REAL-ALPHA", "REAL-BETA", "REAL-GAMMA"):
            assert now.count(token) == 1 and token in decisions, token
        assert "PLAIN-ARTIFACT" in recent
        compaction_lines = [line for line in recent.splitlines() if "compaction" in line]
        assert len(compaction_lines) == 1, recent
        # Only compactions after the newest recorded event are counted (21:55 and the one dated now).
        assert "2 time(s)" in compaction_lines[0] and fresh[:16] in compaction_lines[0], compaction_lines
        assert read(jp).count("compaction occurred") == 9  # Keep the source journal uncollapsed.
        # Freshness follows the last non-compaction event, not the journal mtime the compactions keep fresh.
        # The code counts days in the machine's zone, so convert REAL-GAMMA's time the same way.
        gamma = datetime.datetime.fromisoformat("2026-09-02T21:50:00+09:00").astimezone().date()
        expected = (datetime.date.today() - gamma).days
        assert f"journal {expected}d ago ⚠" in now, now
        issues = run_now(root, "check", "--issues", check=False).stdout
        assert "~journal-stale" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_private_log_survives_corrupt_public_journal():
    root = instance()
    try:
        run_now(root, "log", "[system/state] PUBLIC-BEFORE")
        with open(os.path.join(root, "state", JOURNAL_NOW), "a", encoding="utf-8") as f:
            f.write("- broken line\n")
        r = run_now(root, "log", "--private", "[system/decision] LOCAL-WHILE-PUBLIC-BROKEN", check=False)
        assert r.returncode == 0, r.stderr
        assert "LOCAL-WHILE-PUBLIC-BROKEN" in read(os.path.join(root, "_private", "state", JOURNAL_NOW))
        # The local page is rendered from the local journal and names the damaged tracked one.
        local = read(os.path.join(root, "_private", "state", "NOW.md"))
        assert "LOCAL-WHILE-PUBLIC-BROKEN" in local and f"{JOURNAL_NOW}:" in local, local
        assert not r.stderr.strip(), r.stderr
        ctx = _hook_ctx(root)
        assert "private overlay degraded]" in ctx and "LOCAL-WHILE-PUBLIC-BROKEN" in ctx, ctx
        r = run_now(root, "log", "[system/state] PUBLIC-AFTER", check=False)
        assert r.returncode == 1 and "journal corrupt" in r.stderr
        assert "PUBLIC-AFTER" not in read(os.path.join(root, "state", JOURNAL_NOW))
    finally:
        shutil.rmtree(root, ignore_errors=True)


HANGUL = re.compile("[\uac00-\ud7a3]")
# The locale never chooses a language: under a Korean one every output is still English.
KO_LOCALE = {"LANG": "ko_KR.UTF-8", "LC_ALL": "ko_KR.UTF-8"}


def test_english_instance_writes_english_state_and_injection():
    """NOW files, the journal header, the injection and messages are English whatever the locale."""
    root = instance(threads=[{"key": "pub", "name": "PUB-THREAD", "dossier": None}])
    try:
        os.makedirs(os.path.join(root, "_private", "state"), exist_ok=True)
        with open(os.path.join(root, "_private", "state", "threads.json"), "w") as f:
            json.dump([{"key": "loc", "name": "LOC-THREAD", "dossier": "_private/x.md"}], f)
        outputs = [
            run_now(root, "log", "[system/decision] EN-DECISION", env=KO_LOCALE),
            run_now(root, "log", "--private", "[system/state] EN-LOCAL", env=KO_LOCALE),
            run_now(root, "precompact", "--runtime", "claude", env=KO_LOCALE),
            run_now(root, "log", "no brackets", env=KO_LOCALE, check=False),
            run_now(root, "render", env=KO_LOCALE),
            run_now(root, "threads", env=KO_LOCALE),
            run_now(root, "context", env=KO_LOCALE),
            run_now(root, "context", "--public-only", env=KO_LOCALE),
            run_now(root, "hook-context", env=KO_LOCALE),
            run_now(root, "check", env=KO_LOCALE, check=False),
            run_now(root, "bogus", env=KO_LOCALE, check=False),
        ]
        files = [read(os.path.join(root, "state", "NOW.md")),
                 read(os.path.join(root, "_private", "state", "NOW.md")),
                 read(os.path.join(root, "state", JOURNAL_NOW)),
                 read(os.path.join(root, "_private", "state", JOURNAL_NOW))]
        text = "".join(r.stdout + r.stderr for r in outputs) + "".join(files)
        assert not HANGUL.search(text), HANGUL.search(text) and text[max(0, HANGUL.search(text).start() - 200):][:400]
        public = files[0]
        for name in PUBLIC_SECTION_TOKENS:
            assert "## " + LIVE_NOW.token(name) in public, name
        assert "compaction occurred (claude · s:" in files[2], files[2]
        assert "EN-DECISION" in outputs[6].stdout and "LOC-THREAD" in outputs[6].stdout
        # The injection marks a moved dossier the way the threads command does.
        missing = "LOC-THREAD: dossier `_private/x.md`  [file missing]"
        assert missing in outputs[5].stdout and missing in outputs[6].stdout, outputs[6].stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_state_tokens_are_read_in_both_languages():
    """A compaction row an older engine wrote in Korean is counted with the English ones."""
    root = instance()
    try:
        today = datetime.date.today()
        old = (today - datetime.timedelta(days=5)).isoformat()
        with open(os.path.join(root, "state", JOURNAL_NOW), "w", encoding="utf-8") as f:
            f.write(f"- {old}T09:00:00+09:00 [system/decision] OLD-DECISION\n")
            # Written now, so it is newer than every recorded event below and keeps its row.
            stamp = (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=1))
            f.write(f"- {stamp.isoformat(timespec='seconds')} [system/state] 컴팩션 발생 "
                    "(claude · s:unknown) — 이후 컨텍스트는 요약본\n")
        run_now(root, "precompact", "--runtime", "codex")
        # A tight injection budget makes the decision and event tiers decide which lines stay.
        edit_config(root, lambda c: c["thresholds"].update(now_hook_max_bytes=1400))
        with open(os.path.join(root, "state", JOURNAL_NOW), "a", encoding="utf-8") as f:
            for i in range(24):
                typ = "decision" if i % 3 == 0 else "artifact"
                f.write(f"- {old}T10:{i:02d}:00+09:00 [system/{typ}] ITEM-{i:02d} {'z' * 30}\n")
        journal = read(os.path.join(root, "state", JOURNAL_NOW))
        assert "compaction occurred (codex" in journal, journal
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        decisions = now.split("## Recent decisions and phases")[1].split("## ")[0]
        recent = now.split("## Recent events")[1].split("## ")[0]
        assert "OLD-DECISION" in decisions and "ompaction" not in decisions \
            and "컴팩션" not in decisions, decisions
        assert "ITEM-21" in decisions, decisions
        rows = [line for line in recent.splitlines() if "compaction" in line]
        assert len(rows) == 1 and "2 time(s)" in rows[0] and "claude 1" in rows[0] \
            and "codex 1" in rows[0], recent
        assert "컴팩션" not in recent, recent
        issues = run_now(root, "check", "--issues", check=False).stdout
        assert "~journal-stale" in issues, issues
        # The injection is built from the same journal rows and has no generated notice.
        ctx = run_now(root, "context").stdout
        assert read(os.path.join(root, "state", "NOW.md")) == now, "context re-rendered"
        assert re.findall(r"(?m)^- \d{4}-.*(?:ITEM|OLD)-.*$", ctx), ctx
        assert "*Generated " not in ctx, ctx
        assert "ITEM-21" in ctx and "omitted" in ctx, ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_now_hook_context_reports_hook_errors():
    """Fail-open hooks write only to state/.hook-errors.log; SessionStart must surface new lines once."""
    root = instance()
    try:
        run_now(root, "log", "[system/state] HOOK-ERRORS-FIXTURE")
        log_path = os.path.join(root, "state", ".hook-errors.log")
        line = "2026-11-18T09:00:00 Stop gate check hook failed (tools/gate.py check, rc=1)"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(line + "\n")
        # Probes leave the failure for the next real session; the canary carries only its nonce.
        _hook_ctx_env(root, {"MOTTORI_INTERNAL_RUN": "1"})
        assert _hook_ctx_env(root, {"MOTTORI_HOOK_CANARY": "N0NCE"}) == "HOOK_CANARY:N0NCE\n"
        first = json.loads(run_now(root, "hook-context").stdout)
        ctx = first["hookSpecificOutput"]["additionalContext"]
        assert ctx.count(line) == 1, ctx
        again = json.loads(run_now(root, "hook-context").stdout)
        assert line not in again["hookSpecificOutput"]["additionalContext"]
        # A crash: the wrapper appends the traceback, then its own timestamped summary line.
        crash = "2026-11-18T10:00:00 Stop gate check hook failed (tools/gate.py check, rc=1)"
        later = "2026-11-18T10:05:00 deliver hook failed: OSError: boom"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("Traceback (most recent call last):\n"
                    '  File "tools/gate.py", line 1, in <module>\n'
                    "RuntimeError: boom\n" + crash + "\n" + later + "\n")
        third = json.loads(run_now(root, "hook-context").stdout)
        ctx3 = third["hookSpecificOutput"]["additionalContext"]
        assert ctx3.count(later) == 1 and line not in ctx3, ctx3
        assert "2 since 2026-11-18T10:00:00" in ctx3, ctx3
        assert "Traceback" not in ctx3, ctx3
        # Parallel PostToolUse runs can log the same line twice: two failures, not one. A long
        # unspaced first token must not break the start; only its timestamp is shown.
        dirty = "2026-11-18T11:00:00 PostToolUse gate dirty hook failed (tools/gate.py dirty, rc=1)"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("2026-11-18T11:00:00" + "x" * 8000 + "\n" + dirty + "\n" + dirty + "\n")
        fourth = json.loads(run_now(root, "hook-context").stdout)
        ctx4 = fourth["hookSpecificOutput"]["additionalContext"]
        assert "[hook failures: 3 since 2026-11-18T11:00:00, last: " + dirty in ctx4, ctx4
        # Only the shell appends to the log, so the notice bounds it and keeps the newer part.
        newest = "2026-11-18T12:00:00 Stop gate check hook failed (tools/gate.py check, rc=1)"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write((dirty + "\n") * 4000 + newest + "\n")
        _hook_ctx_env(root, {"MOTTORI_INTERNAL_RUN": "1"})
        assert os.path.getsize(log_path) > LIVE_RUNLOG.LOG_MAX_BYTES   # A probe trims nothing.
        ctx5 = _hook_ctx(root)
        assert os.path.getsize(log_path) <= LIVE_RUNLOG.LOG_MAX_BYTES, os.path.getsize(log_path)
        assert ("last: " + newest) in ctx5, ctx5
        assert newest not in _hook_ctx(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_optional_step_past_its_budget_is_logged_and_not_announced():
    """A step that is not required and overruns leaves its line in the log, which doctor counts,
    and no notice in the next session start; a required step's failure is announced once."""
    import dispatch
    from unittest.mock import patch

    def log_of(steps):
        with patch.dict(dispatch.STEPS, {"SessionStart": steps}), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            dispatch.run("claude", "SessionStart", {})
        return err.getvalue()
    state = dispatch.Step("state", 1, True, False, lambda e: print("STATE"))
    slow = dispatch.Step("index", 0.2, False, False, lambda e: time.sleep(2))
    broken = dispatch.Step("state", 0.2, True, False, lambda e: time.sleep(2))
    overran, failed = log_of([state, slow]), log_of([broken])
    assert "SessionStart step index" in overran, overran
    assert "hook failed (SessionStart step state" in failed, failed
    root = instance()
    try:
        run_now(root, "log", "[system/state] OVERRAN-FIXTURE")
        log_path = os.path.join(root, "state", ".hook-errors.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(overran)
        ctx = _hook_ctx(root)
        assert "[hook failures" not in ctx and "step index" not in ctx, ctx
        assert LIVE_RUNLOG.hook_error_entries(read(log_path)) == [overran.strip()]
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(failed + overran)
        ctx = _hook_ctx(root)
        assert "[hook failures: 1 since " in ctx and "step state" in ctx, ctx
        assert "[hook failures" not in _hook_ctx(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- second-pass fixes (p006)


def _with_track(root, rel="docs/system.md", body="# system\nLast updated: 2026-11-01 first\n"):
    edit_config(root, lambda c: c.update(tracks=[{"key": "system", "name": "SYS",
                                                  "canonical": rel}]))
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def test_portable_check_ignores_tracker_body_edit():
    root = instance()
    try:
        canon = _with_track(root)
        run_now(root, "log", "[system/state] TRACKER-SEED")
        assert _probe(root, "now._snapshot_stale('public', portable=True)") == "False"
        with open(canon, "a", encoding="utf-8") as f:
            f.write("a body line the state page does not show\n")
        assert _probe(root, "now._snapshot_stale('public', portable=True)") == "False"
        with open(canon, "w", encoding="utf-8") as f:
            f.write("# system\nLast updated: 2026-11-02 second\n")
        assert _probe(root, "now._snapshot_stale('public', portable=True)") == "True"
        # The update line is the canonical's one freshness, in local days: seen from UTC-8, an
        # event stamped 01:00 on 11-20 in UTC+9 falls on 11-19. The seed row above carries the
        # real clock, so it is replaced to keep the case independent of the day the suite runs.
        with open(os.path.join(root, "state", JOURNAL_NOW), "w", encoding="utf-8") as f:
            f.write("- 2026-11-20T01:00:00+09:00 [system/decision] EAST-EVENT\n")
        la = {"TZ": "America/Los_Angeles"}
        old = datetime.datetime.fromisoformat("2026-01-01T00:00:00+09:00").timestamp()
        for line, behind in (("Last updated: 2026-11-19 east", None),
                             ("Last updated: 2026-11-18 east", "(2026-11-18)"),
                             ("no update line here", "(no dated update line)")):
            with open(canon, "w", encoding="utf-8") as f:
                f.write(f"# system\n{line}\n")
            # An old file time never makes a canonical behind; only its update line does.
            os.utime(canon, (old, old))
            issues = run_now(root, "check", "--issues", env=la, check=False).stdout
            if behind is None:
                assert "canonical-stale" not in issues, issues
            else:
                # A reminder: printed as an advisory row, never counted toward a block.
                assert f"~canonical-stale:docs/system.md\t[canonical behind] docs/system.md {behind}" in issues, issues
                gated = [l for l in issues.splitlines()[:-1] if not l.startswith("~")]
                assert not [l for l in gated if "canonical-stale" in l], issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_injection_and_page_pack_differently():
    """Each page is fitted alone to its own budget; the injection then fits both sides into one
    budget, places the page's rows whole, and gives the room the local side leaves to the public
    side. A per-page packer cannot share one budget between two pages, which is why now.py has
    two packers."""
    root = instance(public_tracks=["system"])
    try:
        edit_config(root, lambda c: c["thresholds"].update(now_max_bytes=3000,
                                                             now_hook_max_bytes=3000))
        for i in range(12):
            run_now(root, "log", f"[system/decision] DECISION-{i:02d} " + "d" * 250)
        page = read(os.path.join(root, "state", "NOW.md"))
        assert len(page.encode()) <= 3000 and "DECISION-11" in page, page
        ctx = run_now(root, "context").stdout
        public, _private = ctx.split("# Private overlay")
        rows = [line for line in ctx.splitlines() if "DECISION-" in line]
        assert rows and all(line in page.splitlines() for line in rows), rows
        # More than an even split: the small local side lent its room to the public side.
        assert len(public.encode()) > 3000 // 2, len(public.encode())
        assert len(ctx.encode()) <= 3000
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_context_survives_corrupt_public_journal():
    root = instance()
    try:
        run_now(root, "log", "[system/state] LAST-GOOD-EVENT")
        with open(os.path.join(root, "state", JOURNAL_NOW), "a", encoding="utf-8") as f:
            f.write("- broken line without track\n")
        r = run_now(root, "hook-context", check=False)
        assert r.returncode == 0, r.stderr
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        # The last page is not certified under the current input: name the row, repeat nothing.
        assert "LAST-GOOD-EVENT" not in ctx and "without track" not in ctx, ctx
        assert f"{JOURNAL_NOW}:6: malformed journal row" in ctx, ctx
        issues = run_now(root, "check", "--issues", check=False).stdout
        assert "without track" not in issues and f"{JOURNAL_NOW}:6" in issues, issues
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_context_without_snapshot_reports_corrupt_journal():
    root = instance()
    try:
        with open(os.path.join(root, "state", JOURNAL_NOW), "w", encoding="utf-8") as f:
            f.write("# journal\n\n- broken line without track\n")
        ctx = _hook_ctx(root)
        assert f"{JOURNAL_NOW}:3:" in ctx and "without track" not in ctx, ctx
        # An OS error names its files by absolute path; the public side keeps them inside the instance.
        with open(os.path.join(root, "state", JOURNAL_NOW), "w", encoding="utf-8") as f:
            f.write("# journal\n\n")
        os.makedirs(os.path.join(root, "state", "NOW.md"))
        ctx = _hook_ctx(root)
        assert "state/NOW.md" in ctx and root not in ctx, ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_non_utf8_now_is_overwritten():
    root = instance()
    try:
        run_now(root, "log", "[system/state] BEFORE-BAD-BYTES")
        now_path = os.path.join(root, "state", "NOW.md")
        with open(now_path, "wb") as f:
            f.write(b"\xff\xfe not utf-8\n")
        r = run_now(root, "log", "[system/state] AFTER-BAD-BYTES", check=False)
        assert r.returncode == 0, r.stderr
        assert "AFTER-BAD-BYTES" in read(now_path)
        assert not r.stderr.strip(), r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_render_refreshes_private_when_public_frozen():
    root = instance()
    try:
        run_now(root, "log", "--private", "[system/state] PRIVATE-SEED")
        with open(os.path.join(root, "instance", "config.json"), "a", encoding="utf-8") as f:
            f.write("}garbage")
        with open(os.path.join(root, "_private", "state", JOURNAL_NOW), "a",
                  encoding="utf-8") as f:
            f.write("- 2026-11-02T10:00:00+09:00 [system/state] PRIVATE-NEW-ROW\n")
        r = run_now(root, "render", check=False)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "PRIVATE-NEW-ROW" in read(os.path.join(root, "_private", "state", "NOW.md"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_fit_keeps_dossiers_before_dropping_long_bodies():
    body = "x" * 1100

    def builder(decisions, recent, body_limit, threads):
        rows = [f"- event {i} " + LIVE_NOW._clip_line(body, body_limit)
                for i in range(min(decisions, 5))]
        dossiers = [f"- dossier {i}" for i in range(threads)]
        return "# NOW\n" + "\n".join(rows) + "\n" + "\n".join(dossiers) + "\n"

    limits = {"now_max_bytes": 2000, "now_recent_decisions": 20, "now_tail_events": 30}
    with mock.patch.object(LIVE_C, "threshold", limits.__getitem__):
        out = builder(*LIVE_NOW._fit_snapshot(builder, 5))
    assert all(f"- dossier {i}" in out for i in range(5)), out
    assert "…" in out, out


def test_state_event_mentioning_compaction_stays_a_decision():
    root = instance()
    try:
        run_now(root, "log", "[system/state] MENTION-DECISION after compaction occurred, reread the dossier")
        # Starting with the marker words does not make a human row a compaction.
        run_now(root, "log", "[research/state] compaction occurred in the soil sample. MEASURE-AGAIN")
        run_now(root, "log", "[system/state] compaction occurred in the second sample. MEASURE-TWICE")
        run_now(root, "precompact", "--runtime", "claude")
        now = read(os.path.join(root, "state", "NOW.md"))
        decisions = now.split("## Recent decisions and phases")[1].split("## Recent events")[0]
        for token in ("MENTION-DECISION", "MEASURE-AGAIN", "MEASURE-TWICE"):
            assert token in decisions, now
        assert "compaction occurred 1 time(s)" in now, now
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_freshness_ignores_future_rows_and_compaction_only_journals():
    root = instance()
    try:
        jp = os.path.join(root, "state", JOURNAL_NOW)
        today = datetime.datetime.now().astimezone()
        past = (today - datetime.timedelta(days=5)).replace(microsecond=0)
        future = (today + datetime.timedelta(days=40)).replace(microsecond=0)
        with open(jp, "w", encoding="utf-8") as f:
            f.write("# journal\n\n"
                    f"- {past.isoformat()} [system/state] PAST-ROW\n"
                    f"- {future.isoformat()} [system/state] FUTURE-ROW\n")
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        assert "journal 5d ago ⚠" in now, now
        with open(jp, "w", encoding="utf-8") as f:
            f.write("# journal\n\n"
                    f"- {past.isoformat()} [system/state] compaction occurred (claude · s:unknown)\n")
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        assert "journal ?d ago ⚠" in now, now
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_injection_fixed_lines_over_budget_keeps_byte_cap():
    # A short public side leaves the rest of the room to the local side.
    plans = {"public": LIVE_NOW._text_plan("A" * 100),
             "private": LIVE_NOW._text_plan(("B" * 79 + "\n") * 10)}
    public, private = LIVE_NOW._fit_injection(plans, 850)
    used = len((public + private).encode())
    assert public.count("A") == 100 and 700 < used <= 850, (used, public, private)
    root = instance()
    try:
        def many_tracks(cfg):
            cfg["tracks"] = [{"key": f"t{i}", "name": f"트랙-{i}", "canonical": f"docs/t{i}.md"}
                             for i in range(30)]
            # Public tracks: their board rows are the public side's fixed lines.
            cfg["journal_visibility"]["public_tracks"] += [f"t{i}" for i in range(30)]
            cfg["thresholds"]["now_hook_max_bytes"] = 1024
        edit_config(root, many_tracks)
        run_now(root, "log", "[system/state] CAP-SEED")
        r = run_now(root, "hook-context")
        raw = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"].encode("utf-8")
        assert len(raw) <= 1024, len(raw)
        text = raw.decode("utf-8")
        assert text.startswith("[state injection"), text
        # A disk page cut at its own cap goes in as it stands, so the local decision keeps a place.
        edit_config(root, lambda c: c["thresholds"].update(now_hook_max_bytes=1500,
                                                           now_max_bytes=1024))
        run_now(root, "log", "--private", "[system/decision] CUT-LOCAL")
        assert "CUT-LOCAL" in _hook_ctx(root).split("# Private overlay")[1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_drift_messages_name_their_fix():
    N = LIVE_NOW
    for text in (N.CHECK_NOW_INPUT_NEWER, N.CHECK_NOW_INPUT_NEWER_STAGED):
        assert "now.py render" in text and "state/NOW.md" in text, text
    # state/NOW.md is ignored in a kit instance; only the staged-tree form may ask to stage it.
    assert "stage" not in N.CHECK_NOW_INPUT_NEWER, N.CHECK_NOW_INPUT_NEWER
    assert "{rel}" in N.CHECK_CANONICAL_STALE and "Last updated" in N.CHECK_CANONICAL_STALE
    import memory_index
    assert "state/NOW.md" in memory_index.CHECK_MEMORY_ROT, memory_index.CHECK_MEMORY_ROT


def test_public_snapshot_spends_no_bytes_on_restated_rules():
    root = instance(threads=[{"key": "pub", "name": "PUB-THREAD", "dossier": None}])
    try:
        run_now(root, "log", "[system/state] RULES-SEED")
        run_now(root, "precompact", "--runtime", "claude")
        run_now(root, "log", "[system/state] AFTER-COMPACTION")
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        for gone in ("PRD §3.3", "Phase 2", "public projection", "facts.py", "recall.py",
                     "instance/decisions.md"):
            assert gone not in now, (gone, now)
        # A compaction before the newest recorded event no longer needs a row.
        assert not any(form in now for form in LIVE_NOW.token_forms("compaction")), now
        ctx = _hook_ctx(root)
        assert "AFTER-COMPACTION" in ctx and "RULES-SEED" in ctx, ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_track_row_shows_update_line_without_file_age_warning():
    root = instance()
    try:
        canon = _with_track(root)
        old = time.time() - 30 * 86400
        os.utime(canon, (old, old))
        run_now(root, "log", "[system/state] TRACK-ROW-SEED")
        now = read(os.path.join(root, "state", "NOW.md"))
        row = next(line for line in now.splitlines() if line.startswith("- **SYS**"))
        assert "2026-11-01 first" in row and "docs/system.md" in row, row
        assert "⚠" not in row and "file" not in row, row
        # The row is public: a canonical in the private folder, even through a symlink, is
        # shown as a pointer and its update line is not copied.
        secret = os.path.join(root, "_private", "canon.md")
        os.makedirs(os.path.dirname(secret), exist_ok=True)
        with open(secret, "w", encoding="utf-8") as f:
            f.write("Last updated: 2026-11-02 PRIVATE-CANON\n")
        os.unlink(canon)
        os.symlink(secret, canon)
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        assert "PRIVATE-CANON" not in now and "docs/system.md" in now, now
        # On a case-insensitive disk a case variant names the same private file.
        edit_config(root, lambda c: c["tracks"][0].update(canonical="_PRIVATE/canon.md"))
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        assert "PRIVATE-CANON" not in now and "_PRIVATE/canon.md" in now, now
        # A link whose absolute target spells the root in another case climbs out of a
        # relative comparison; on a case-sensitive disk the swapped path does not exist.
        swapped = os.path.join(os.path.realpath(root).swapcase(), "_private", "canon.md")
        os.unlink(canon)
        os.symlink(swapped, canon)
        edit_config(root, lambda c: c["tracks"][0].update(canonical="docs/system.md"))
        run_now(root, "render")
        now = read(os.path.join(root, "state", "NOW.md"))
        assert "PRIVATE-CANON" not in now and "docs/system.md" in now, now
        # A private folder that is itself a link to a folder outside the tree stays private.
        outside = tempfile.mkdtemp()
        os.rename(os.path.join(root, "_private"), os.path.join(outside, "p"))
        os.symlink(os.path.join(outside, "p"), os.path.join(root, "_private"))
        edit_config(root, lambda c: c["tracks"][0].update(canonical="_private/canon.md"))
        run_now(root, "render")
        shutil.rmtree(outside, ignore_errors=True)
        now = read(os.path.join(root, "state", "NOW.md"))
        assert "PRIVATE-CANON" not in now and "_private/canon.md" in now, now
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # A track whose key is not in public_tracks is private everywhere: its board row and pointer
    # go to the local page only, and its canonical is no input of the public page.
    root = instance()
    try:
        canon = _with_track(root, "pricing/tracker.md", "Last updated: THURSDAY-TRIAL\n")
        edit_config(root, lambda c: c["tracks"][0].update(key="pricing", name="PRICING-PILOT"))
        run_now(root, "log", "[system/state] SPLIT-SEED")
        run_now(root, "render")
        public = read(os.path.join(root, "state", "NOW.md"))
        local = read(os.path.join(root, "_private", "state", "NOW.md"))
        assert "PRICING-PILOT" not in public and "pricing/tracker.md" not in public, public
        assert "THURSDAY-TRIAL" in local and "pricing/tracker.md" in local, local
        assert "PRICING-PILOT" not in run_now(root, "context", "--public-only").stdout
        before = _probe(root, "now._input_fingerprint('public')")
        with open(canon, "w", encoding="utf-8") as f:
            f.write("Last updated: FRIDAY\n")
        assert _probe(root, "now._input_fingerprint('public')") == before
    finally:
        shutil.rmtree(root, ignore_errors=True)

TESTS = [
    test_before_setup_the_session_start_says_only_how_to_set_up,
    test_a_project_block_is_an_input_of_the_state_page,
    test_hook_context_keeps_dossiers_and_newest_decisions_with_long_journals,
    test_hook_context_keeps_long_event_lines_whole,
    test_snapshot_drops_compactions_from_decisions_and_dedups_recent,
    test_private_log_survives_corrupt_public_journal,
    test_precompact_tags_runtime_and_session_hash,
    test_routing_and_public_immutability,
    test_legacy_filter_and_private_thread,
    test_legacy_allowlist_expansion_does_not_retro_promote,
    test_legacy_private_rows_create_overlay_without_existing_private_dir,
    test_missing_config_fails_closed,
    test_schema_mismatch_warns_once_in_quiet_precompact,
    test_utf8_hook_budget_and_overlay_fairness,
    test_multibyte_bodies_preserve_mandatory_snapshot_sections,
    test_absent_overlay_stays_unavailable_and_is_not_created,
    test_corrupt_local_overlay_does_not_suppress_public_injection,
    test_invalid_private_registry_is_explicitly_degraded,
    test_invalid_budget_config_fails_closed_without_empty_public_snapshot,
    test_config_warning_does_not_echo_invalid_values,
    test_age_days_uses_local_calendar_boundary,
    test_failed_journal_append_is_undone_and_reports_its_cause,
    test_stale_recovery_and_corruption_visibility,
    test_touch_then_render_clears_stale_marker,
    test_broken_visibility_config_freezes_public_snapshot,
    test_config_policy_change_invalidates_public_snapshot,
    test_private_registry_change_invalidates_local_snapshot,
    test_public_hook_survives_post_import_private_registry_change,
    test_structurally_invalid_config_fails_closed_without_import_crash,
    test_config_change_after_import_aborts_before_public_mutation,
    test_month_boundary_pins_one_journal_for_append,
    test_config_change_during_render_leaves_a_stale_page,
    test_page_from_an_older_engine_is_rendered_again,
    test_render_failure_keeps_logged_event,
    test_portable_fingerprint_ignores_calendar_day,
    test_check_rerenders_after_date_change,
    test_month_rollover_with_old_previous_journal_is_advisory,
    test_unterminated_tail_refuses_append_without_merging,
    test_strict_parser_rejects_schema_invalid_event,
    test_private_thread_key_collisions_cannot_change_public_projection,
    test_atomic_write_preserves_old_on_replace_failure,
    test_parallel_writers_exactly_once,
    test_render_transaction_prevents_stale_last_writer,
    test_hook_internal_failure_is_nonzero,
    test_english_instance_writes_english_state_and_injection,
    test_state_tokens_are_read_in_both_languages,
    test_hook_context_names_omitted_dossiers_when_both_lists_are_long,
    test_hook_context_survives_sixty_long_dossier_names_on_one_side,
    test_now_hook_context_reports_hook_errors,
    test_an_optional_step_past_its_budget_is_logged_and_not_announced,
    test_portable_check_ignores_tracker_body_edit,
    test_injection_and_page_pack_differently,
    test_hook_context_survives_corrupt_public_journal,
    test_hook_context_without_snapshot_reports_corrupt_journal,
    test_non_utf8_now_is_overwritten,
    test_render_refreshes_private_when_public_frozen,
    test_fit_keeps_dossiers_before_dropping_long_bodies,
    test_state_event_mentioning_compaction_stays_a_decision,
    test_freshness_ignores_future_rows_and_compaction_only_journals,
    test_injection_fixed_lines_over_budget_keeps_byte_cap,
    test_drift_messages_name_their_fix,
    test_public_snapshot_spends_no_bytes_on_restated_rules,
    test_track_row_shows_update_line_without_file_age_warning,
    test_check_without_repair_never_writes_snapshots,
]


def run():
    failures = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as e:  # noqa: BLE001 - fixture runner must report all failures
            failures.append((test.__name__, f"{type(e).__name__}: {e}"))
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
    print(f"state runtime: {len(TESTS) - len(failures)}/{len(TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
