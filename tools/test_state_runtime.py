#!/usr/bin/env python3
"""State ledger regression tests: routing, atomicity, concurrency, and hook budget.

Every fixture lives in a temporary instance.  The live workspace journal and NOW are never used.
"""
import contextlib
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = os.path.join(HERE, "now.py")
FAIL_CLOSE_WARNING = "[state] privacy fail-close:"
sys.path.insert(0, HERE)
import memlib as LIVE_M  # noqa: E402
import now as LIVE_NOW  # noqa: E402


def config(public_tracks=None, threads=None, legacy_cutoff="2026-08-26T23:59:59+09:00",
           legacy_public_tracks=None):
    public_tracks = (["system", "research"] if public_tracks is None else public_tracks)
    return {
        "schema_version": 4,
        "instance": {"name": "fixture", "context": "personal", "remote_allowlist": []},
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
            "track_stale_days": 7,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_max_bytes": 6000,
            "now_hook_max_bytes": 6000,
        },
    }


def instance(*, with_config=True, public_tracks=None, threads=None,
             legacy_cutoff="2026-08-26T23:59:59+09:00", legacy_public_tracks=None):
    root = tempfile.mkdtemp(prefix="state-runtime-")
    os.makedirs(os.path.join(root, "system"), exist_ok=True)
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    if with_config:
        with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
            json.dump(config(public_tracks, threads, legacy_cutoff, legacy_public_tracks),
                      f, ensure_ascii=False)
    return root


def run_now(root, *args, env=None, check=True):
    e = dict(os.environ, MOTTORI_INSTANCE=root)
    if env:
        e.update(env)
    r = subprocess.run([sys.executable, NOW, *args], capture_output=True, text=True, env=e, cwd=root)
    if check and r.returncode:
        raise AssertionError(f"now.py {' '.join(args)} exit={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}")
    return r


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# now.py는 현재 시각으로 저널 파일명을 정한다. 하드코딩하면 매달 1일에 깨진다.
# (2026-09-01 실측: 월 롤오버로 13건 동시 실패)
JOURNAL_NOW = "journal-%s.md" % datetime.datetime.now().strftime("%Y-%m")


def event(token, track="system", typ="state", second=0):
    return f"- 2026-08-26T23:40:{second:02d}+09:00 [{track}/{typ}] {token}\n"


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

        cfg_path = os.path.join(root, "system", "memory-config.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        cfg["journal_visibility"]["public_tracks"].append("novel")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
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
        assert "config 없음" in r.stderr
        assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
        assert "NO-CONFIG-CANARY" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_schema_mismatch_warns_once_in_quiet_precompact():
    root = instance()
    try:
        cfg_path = os.path.join(root, "system", "memory-config.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        cfg["schema_version"] = 3
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        r = run_now(root, "precompact")
        assert r.stdout == ""
        assert r.stderr.count(FAIL_CLOSE_WARNING) == 1, r.stderr
        assert "schema=3" in r.stderr and "engine schema=4" in r.stderr
        assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
        assert "컴팩션 발생" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_utf8_hook_budget_and_overlay_fairness():
    root = instance()
    try:
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
        r = run_now(root, "hook-context", env={"MOTTORI_HOOK_CANARY": "CANARY-ONLY-HOOK"})
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert len(ctx.encode("utf-8")) <= 6000
        assert "## PUBLIC STATE" in ctx and "## LOCAL PRIVATE OVERLAY" in ctx
        assert "# NOW" in ctx and "local private overlay" in ctx
        assert "CANARY-ONLY-HOOK" in ctx
        assert "절단" in ctx
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
        assert all(f"## {section}" in public for section in LIVE_M.NOW_SECTIONS)
        assert "…" in public, "event bodies were not byte-clipped"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_absent_overlay_stays_unavailable_and_is_not_created():
    root = instance()
    try:
        os.makedirs(os.path.join(root, "_private", "unrelated"), exist_ok=True)
        run_now(root, "log", "[system/state] PUBLIC-WITH-NO-LOCAL-STATE")
        r = run_now(root, "hook-context")
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "local overlay unavailable]" in ctx
        assert "PUBLIC-WITH-NO-LOCAL-STATE" in ctx
        assert not os.path.exists(os.path.join(root, "_private", "state", "NOW.md"))
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
        assert "local overlay unavailable/corrupt]" in ctx
        assert "없음으로 단언하지 말 것" in ctx
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
        r = run_now(root, "hook-context")
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "local overlay degraded]" in ctx
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
            cfg_path = os.path.join(root, "system", "memory-config.json")
            cfg = json.load(open(cfg_path, encoding="utf-8"))
            if parent:
                cfg[parent][key] = value
            else:
                cfg[key] = value
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
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
        cfg_path = os.path.join(root, "system", "memory-config.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        cfg["threads"] = [{"key": "x", "name": "x", "visibility": secret}]
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        r = run_now(root, "log", "[system/state] SANITIZED-WARNING", check=False)
        assert r.returncode == 0, r.stderr
        assert r.stderr.count(FAIL_CLOSE_WARNING) == 1, r.stderr
        assert secret not in r.stderr
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
        r = run_now(root, "hook-context")
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "RECOVERED-BY-HOOK" in ctx

        old = open(os.path.join(root, "state", "NOW.md"), "rb").read()
        with open(jp, "a", encoding="utf-8") as f:
            f.write("- this looks like an event but is corrupt\n")
        r = run_now(root, "render", check=False)
        assert r.returncode != 0 and "손상" in r.stderr
        assert open(os.path.join(root, "state", "NOW.md"), "rb").read() == old
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_touch_then_render_clears_stale_marker():
    root = instance()
    try:
        run_now(root, "log", "[system/state] TOUCH-SEED")
        jp = os.path.join(root, "state", JOURNAL_NOW)
        time.sleep(0.02)
        os.utime(jp, None)
        before = run_now(root, "check", "--issues")
        assert "now-input-newer" in before.stdout
        run_now(root, "render")
        after = run_now(root, "check", "--issues")
        assert "now-input-newer" not in after.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_broken_visibility_config_freezes_public_snapshot():
    root = instance()
    try:
        run_now(root, "log", "[system/state] GOOD-BEFORE-CONFIG-BREAK")
        public_now = os.path.join(root, "state", "NOW.md")
        before = open(public_now, "rb").read()
        with open(os.path.join(root, "system", "memory-config.json"), "a", encoding="utf-8") as f:
            f.write("}garbage")
        r = run_now(root, "render", check=False)
        assert r.returncode != 0 and "visibility" in r.stderr
        assert open(public_now, "rb").read() == before
        run_now(root, "log", "[system/state] FAIL-CLOSED-NEW-EVENT")
        assert open(public_now, "rb").read() == before
        assert "FAIL-CLOSED-NEW-EVENT" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_policy_change_invalidates_public_snapshot():
    root = instance()
    try:
        os.makedirs(os.path.join(root, "_private", "state"), exist_ok=True)
        run_now(root, "log", "[system/state] POLICY-CHANGE-CANARY")
        public_now = os.path.join(root, "state", "NOW.md")
        assert "POLICY-CHANGE-CANARY" in read(public_now)

        cfg_path = os.path.join(root, "system", "memory-config.json")
        cfg = json.loads(read(cfg_path))
        cfg["journal_visibility"]["public_tracks"] = ["research"]
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)

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
json.dump([{{'key': 'b', 'name': 'LOCAL-B', 'dossier': 'b.md'}}],
          open({registry!r}, 'w', encoding='utf-8'), ensure_ascii=False)
raise SystemExit(now.hook_context())
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode == 0, r.stdout + r.stderr
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "PUBLIC-AFTER-REGISTRY-RACE" in ctx
        assert "local overlay unavailable/corrupt]" in ctx
        assert "LOCAL-B" not in ctx
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_structurally_invalid_config_fails_closed_without_import_crash():
    root = instance()
    try:
        with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        r = run_now(root, "log", "[system/state] ROOT-LIST-CONFIG", check=False)
        assert r.returncode == 0, r.stderr
        assert "ROOT-LIST-CONFIG" in read(
            os.path.join(root, "_private", "state", JOURNAL_NOW))
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
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_change_after_import_aborts_before_public_mutation():
    root = instance()
    try:
        run_now(root, "log", "[system/state] CONFIG-RACE-SEED")
        journal = os.path.join(root, "state", JOURNAL_NOW)
        before = open(journal, "rb").read()
        cfg_path = os.path.join(root, "system", "memory-config.json")
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
path = {cfg_path!r}
cfg = json.load(open(path, encoding='utf-8'))
cfg['journal_visibility']['public_tracks'] = ['research']
json.dump(cfg, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
raise SystemExit(now.log('[system/state] MUST-NOT-USE-STALE-POLICY', quiet=True))
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode != 0 and "config" in r.stderr
        assert open(journal, "rb").read() == before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_change_during_log_rolls_back_public_append():
    root = instance()
    try:
        run_now(root, "log", "[system/state] ROLLBACK-SEED")
        journal = os.path.join(root, "state", JOURNAL_NOW)
        before = open(journal, "rb").read()
        cfg_path = os.path.join(root, "system", "memory-config.json")
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
real = now._append_journal
def racing_append(line, path, event_time):
    cfg = json.load(open({cfg_path!r}, encoding='utf-8'))
    cfg['journal_visibility']['public_tracks'] = ['research']
    json.dump(cfg, open({cfg_path!r}, 'w', encoding='utf-8'), ensure_ascii=False)
    return real(line, path, event_time)
now._append_journal = racing_append
rc = now.log('[system/state] MUST-ROLL-BACK', quiet=True)
raise SystemExit(0 if rc != 0 else 9)
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode == 0, r.stderr
        assert open(journal, "rb").read() == before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_month_boundary_pins_one_journal_for_append_and_rollback():
    root = instance()
    try:
        august_path = os.path.join(root, "state", JOURNAL_NOW)
        september_path = os.path.join(root, "state", "journal-2026-09.md")
        script = f"""
import datetime, os, sys
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
def fail_render(scopes):
    raise OSError('injected failure after append')
now.datetime.datetime = RolloverDateTime
now._render_unlocked = fail_render
rc = now.log('[system/state] MONTH-BOUNDARY-MUST-ROLL-BACK', quiet=True)
ok = (rc != 0 and not os.path.exists({august_path!r})
      and not os.path.exists({september_path!r}) and RolloverDateTime.calls == 1)
raise SystemExit(0 if ok else 9)
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_config_change_during_render_never_publishes_new_projection():
    root = instance()
    try:
        run_now(root, "log", "[system/state] RENDER-RACE-SEED")
        now_path = os.path.join(root, "state", "NOW.md")
        before = open(now_path, "rb").read()
        journal = os.path.join(root, "state", JOURNAL_NOW)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(event("MUST-NOT-PUBLISH", second=3))
        cfg_path = os.path.join(root, "system", "memory-config.json")
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
real = now._public_snapshot
def racing_snapshot(entries, fingerprint):
    text = real(entries, fingerprint)
    cfg = json.load(open({cfg_path!r}, encoding='utf-8'))
    cfg['journal_visibility']['public_tracks'] = ['research']
    json.dump(cfg, open({cfg_path!r}, 'w', encoding='utf-8'), ensure_ascii=False)
    return text
now._public_snapshot = racing_snapshot
rc = now.render()
raise SystemExit(0 if rc != 0 else 9)
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode == 0, r.stderr
        assert open(now_path, "rb").read() == before
        assert b"MUST-NOT-PUBLISH" not in before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_identity_change_inside_atomic_publish_rolls_back_log_and_snapshot():
    root = instance()
    try:
        run_now(root, "log", "[system/state] ATOMIC-PUBLISH-SEED")
        journal = os.path.join(root, "state", JOURNAL_NOW)
        now_path = os.path.join(root, "state", "NOW.md")
        cfg_path = os.path.join(root, "system", "memory-config.json")
        before_journal = open(journal, "rb").read()
        before_now = open(now_path, "rb").read()
        before_config = open(cfg_path, "rb").read()
        before_journal_stat = os.stat(journal)
        before_now_stat = os.stat(now_path)
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
real = now.M.atomic_write
fired = False
def racing_atomic_write(path, text):
    global fired
    result = real(path, text)
    if path == now.M.NOW_PATH and not fired:
        fired = True
        cfg = json.load(open({cfg_path!r}, encoding='utf-8'))
        cfg['journal_visibility']['public_tracks'] = ['research']
        json.dump(cfg, open({cfg_path!r}, 'w', encoding='utf-8'), ensure_ascii=False)
    return result
now.M.atomic_write = racing_atomic_write
rc = now.log('[system/state] ATOMIC-PUBLISH-MUST-ROLL-BACK', quiet=True)
raise SystemExit(0 if rc != 0 else 9)
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        after_journal = open(journal, "rb").read()
        after_now = open(now_path, "rb").read()
        after_journal_stat = os.stat(journal)
        after_now_stat = os.stat(now_path)
        with open(cfg_path, "wb") as f:
            f.write(before_config)
        assert r.returncode == 0, (
            f"atomic publish identity race was accepted: exit={r.returncode}; "
            f"append_rolled_back={after_journal == before_journal}; "
            f"snapshot_restored={after_now == before_now}; stderr={r.stderr}")
        assert after_journal == before_journal
        assert after_now == before_now
        assert (after_journal_stat.st_mode & 0o7777,
                after_journal_stat.st_mtime_ns) == (
                    before_journal_stat.st_mode & 0o7777,
                    before_journal_stat.st_mtime_ns)
        assert (after_now_stat.st_mode & 0o7777,
                after_now_stat.st_mtime_ns) == (
                    before_now_stat.st_mode & 0o7777,
                    before_now_stat.st_mtime_ns)
        checked = run_now(root, "check", "--issues")
        assert "now-input-newer" not in checked.stdout, checked.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_first_log_atomic_publish_race_restores_absence():
    root = instance()
    try:
        cfg_path = os.path.join(root, "system", "memory-config.json")
        before_config = open(cfg_path, "rb").read()
        script = f"""
import json, sys
sys.path.insert(0, {HERE!r})
import now
real = now.M.atomic_write
fired = False
def racing_atomic_write(path, text):
    global fired
    result = real(path, text)
    if path == now.M.NOW_PATH and not fired:
        fired = True
        cfg = json.load(open({cfg_path!r}, encoding='utf-8'))
        cfg['journal_visibility']['public_tracks'] = ['research']
        json.dump(cfg, open({cfg_path!r}, 'w', encoding='utf-8'), ensure_ascii=False)
    return result
now.M.atomic_write = racing_atomic_write
rc = now.log('[system/state] FIRST-PUBLISH-MUST-DISAPPEAR', quiet=True)
raise SystemExit(0 if rc != 0 else 9)
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        with open(cfg_path, "wb") as f:
            f.write(before_config)
        assert r.returncode == 0, r.stdout + r.stderr
        assert not os.path.exists(os.path.join(root, "state", JOURNAL_NOW))
        assert not os.path.exists(os.path.join(root, "state", "NOW.md"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_source_change_during_render_cannot_false_certify():
    root = instance()
    code = tempfile.mkdtemp(prefix="state-runtime-code-")
    try:
        for name in ("now.py", "memlib.py"):
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
real = now._public_snapshot
def racing_snapshot(entries, fingerprint):
    text = real(entries, fingerprint)
    with open(now.__file__, 'a', encoding='utf-8') as f:
        f.write('\\n# concurrent source edit\\n')
    return text
now._public_snapshot = racing_snapshot
rc = now.render()
raise SystemExit(0 if rc != 0 else 9)
"""
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode == 0, r.stderr
        assert open(now_path, "rb").read() == before
        assert b"SOURCE-MUST-NOT-PUBLISH" not in before
    finally:
        shutil.rmtree(code, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_source_change_during_log_rolls_back_public_append():
    root = instance()
    code = tempfile.mkdtemp(prefix="state-runtime-code-")
    try:
        for name in ("now.py", "memlib.py"):
            shutil.copy2(os.path.join(HERE, name), os.path.join(code, name))
        copied_now = os.path.join(code, "now.py")
        copied_memlib = os.path.join(code, "memlib.py")
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        subprocess.run([sys.executable, copied_now, "log", "[system/state] SOURCE-LOG-SEED"],
                       check=True, capture_output=True, text=True, env=env, cwd=root)
        journal = os.path.join(root, "state", JOURNAL_NOW)
        before = open(journal, "rb").read()
        script = f"""
import sys
sys.path.insert(0, {code!r})
import now
real = now._append_journal
def racing_append(line, path, event_time):
    result = real(line, path, event_time)
    with open({copied_memlib!r}, 'a', encoding='utf-8') as f:
        f.write('\\n# concurrent routing edit\\n')
    return result
now._append_journal = racing_append
rc = now.log('[system/state] SOURCE-MUST-ROLL-BACK', quiet=True)
raise SystemExit(0 if rc != 0 else 9)
"""
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode == 0, r.stderr
        assert open(journal, "rb").read() == before
    finally:
        shutil.rmtree(code, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_render_failure_rolls_back_log_for_exact_retry():
    root = instance()
    try:
        script = f"""
import os, sys
sys.path.insert(0, {HERE!r})
import now
real = now.M.atomic_write
def fail(path, text):
    raise OSError('injected publish failure')
now.M.atomic_write = fail
first = now.log('[system/state] RETRY-MUST-BE-EXACTLY-ONCE', quiet=True)
now.M.atomic_write = real
second = now.log('[system/state] RETRY-MUST-BE-EXACTLY-ONCE', quiet=True)
journal = now.M.journal_path()
count = open(journal, encoding='utf-8').read().count('RETRY-MUST-BE-EXACTLY-ONCE')
raise SystemExit(0 if first != 0 and second == 0 and count == 1 else 9)
"""
        env = dict(os.environ, MOTTORI_INSTANCE=root)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           env=env, cwd=root)
        assert r.returncode == 0, r.stdout + r.stderr
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
        assert r.returncode != 0 and "끝 개행" in r.stderr
        assert open(jp, "rb").read() == before
        assert b"MUST-NOT-MERGE" not in before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_strict_parser_rejects_schema_invalid_event():
    root = instance()
    try:
        run_now(root, "log", "[system/state] SCHEMA-SEED")
        public_now = os.path.join(root, "state", "NOW.md")
        old = open(public_now, "rb").read()
        jp = os.path.join(root, "state", JOURNAL_NOW)
        with open(jp, "a", encoding="utf-8") as f:
            f.write(event("INVALID-TYPE", typ="notallowed", second=9))
        r = run_now(root, "render", check=False)
        assert r.returncode != 0 and "손상" in r.stderr
        assert open(public_now, "rb").read() == old
        issues = run_now(root, "check", "--issues")
        assert "journal-corrupt" in issues.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_timezone_less_journal_event_is_corrupt():
    root = instance()
    try:
        run_now(root, "log", "[system/state] TIMEZONE-SEED")
        public_now = os.path.join(root, "state", "NOW.md")
        old = open(public_now, "rb").read()
        line = "- 2026-08-26T23:40:09 [system/state] NO-TIMEZONE"
        assert LIVE_M.validate_line(line) is not None
        jp = os.path.join(root, "state", JOURNAL_NOW)
        with open(jp, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        rendered = run_now(root, "render", check=False)
        assert rendered.returncode != 0 and "손상" in rendered.stderr
        assert open(public_now, "rb").read() == old
        issues = run_now(root, "check", "--issues")
        assert "journal-corrupt" in issues.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_private_thread_registry_is_local_only():
    root = instance(threads=[{"key": "shared", "name": "PUBLIC-THREAD", "dossier": "shared.md"}])
    try:
        os.makedirs(os.path.join(root, "_private", "state"), exist_ok=True)
        with open(os.path.join(root, "_private", "state", "threads.json"), "w", encoding="utf-8") as f:
            json.dump([{"key": "secret", "name": "LOCAL-REGISTRY-THREAD",
                        "dossier": "_private/secret.md"}], f)
        run_now(root, "render")
        assert "LOCAL-REGISTRY-THREAD" not in read(os.path.join(root, "state", "NOW.md"))
        assert "LOCAL-REGISTRY-THREAD" in read(os.path.join(root, "_private", "state", "NOW.md"))
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
        hooked = run_now(root, "hook-context")
        ctx = json.loads(hooked.stdout)["hookSpecificOutput"]["additionalContext"]
        assert open(public_now, "rb").read() == before
        assert "PUBLIC-SHARED" in ctx and "LOCAL-MUST-NOT-SHADOW" not in ctx
        assert "LOCAL-FIRST" in ctx and "LOCAL-SECOND" not in ctx
        assert "local overlay degraded]" in ctx
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
                LIVE_M.atomic_write(target, "NEW-COMPLETE")
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
    root = instance()
    attrs = {}
    names = ("ROOT", "STATE", "NOW_PATH", "PRIVATE_STATE", "PRIVATE_NOW_PATH",
             "TRACKS", "THREADS", "PERSONAL_POINTER", "PUBLIC_JOURNAL_TRACKS",
             "VISIBILITY_READY", "CONFIG_FINGERPRINT")
    try:
        for name in names:
            attrs[name] = getattr(LIVE_M, name)
        LIVE_M.ROOT = root
        LIVE_M.STATE = os.path.join(root, "state")
        LIVE_M.NOW_PATH = os.path.join(root, "state", "NOW.md")
        LIVE_M.PRIVATE_STATE = os.path.join(root, "_private", "state")
        LIVE_M.PRIVATE_NOW_PATH = os.path.join(root, "_private", "state", "NOW.md")
        LIVE_M.TRACKS = []
        LIVE_M.THREADS = []
        LIVE_M.PERSONAL_POINTER = "_private/README.md"
        LIVE_M.PUBLIC_JOURNAL_TRACKS = ("system",)
        LIVE_M.VISIBILITY_READY = True
        LIVE_M.CONFIG_FINGERPRINT = LIVE_M.config_fingerprint(
            os.path.join(root, "system", "memory-config.json"))
        with open(os.path.join(root, "state", JOURNAL_NOW), "w", encoding="utf-8") as f:
            f.write("# journal\n\n" + event("A-BASE", second=1))

        entered, release = threading.Event(), threading.Event()
        original = LIVE_M.atomic_write

        def blocked(path, text):
            if threading.current_thread().name == "old-render" and path == LIVE_M.NOW_PATH:
                entered.set()
                if not release.wait(5):
                    raise AssertionError("test release timeout")
            return original(path, text)

        with mock.patch.object(LIVE_M, "atomic_write", blocked):
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
        assert "B-NEW" in read(LIVE_M.NOW_PATH)
    finally:
        for name, value in attrs.items():
            setattr(LIVE_M, name, value)
        shutil.rmtree(root, ignore_errors=True)


def test_hook_internal_failure_is_nonzero():
    root = instance()
    try:
        shutil.rmtree(os.path.join(root, "state"))
        os.makedirs(os.path.join(root, "state", "NOW.md"))
        r = run_now(root, "hook-context", check=False)
        assert r.returncode != 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
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
    test_stale_recovery_and_corruption_visibility,
    test_touch_then_render_clears_stale_marker,
    test_broken_visibility_config_freezes_public_snapshot,
    test_config_policy_change_invalidates_public_snapshot,
    test_private_registry_change_invalidates_local_snapshot,
    test_public_hook_survives_post_import_private_registry_change,
    test_structurally_invalid_config_fails_closed_without_import_crash,
    test_config_change_after_import_aborts_before_public_mutation,
    test_config_change_during_log_rolls_back_public_append,
    test_month_boundary_pins_one_journal_for_append_and_rollback,
    test_config_change_during_render_never_publishes_new_projection,
    test_identity_change_inside_atomic_publish_rolls_back_log_and_snapshot,
    test_first_log_atomic_publish_race_restores_absence,
    test_source_change_during_render_cannot_false_certify,
    test_source_change_during_log_rolls_back_public_append,
    test_render_failure_rolls_back_log_for_exact_retry,
    test_unterminated_tail_refuses_append_without_merging,
    test_strict_parser_rejects_schema_invalid_event,
    test_timezone_less_journal_event_is_corrupt,
    test_private_thread_registry_is_local_only,
    test_private_thread_key_collisions_cannot_change_public_projection,
    test_atomic_write_preserves_old_on_replace_failure,
    test_parallel_writers_exactly_once,
    test_render_transaction_prevents_stale_last_writer,
    test_hook_internal_failure_is_nonzero,
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
