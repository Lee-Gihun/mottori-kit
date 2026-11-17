#!/usr/bin/env python3
"""doctor JSON output and isolated PreCompact simulation fixtures."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types

from testlib import run_test

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
def _run_doctor_json():
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "doctor.py"), "--json"],
        cwd=ROOT, capture_output=True, text=True,
        env=dict(os.environ, MOTTORI_INTERNAL_RUN="1", MOTTORI_LANG="ko"),
    )


def test_json_schema_and_exit_status():
    result = _run_doctor_json()
    payload = json.loads(result.stdout)
    assert set(payload) == {"checks", "summary", "manual"}
    assert payload["checks"]
    assert all(set(row) == {"name", "status", "detail"} for row in payload["checks"])
    assert all(row["status"] in {"PASS", "FAIL", "WARN", "SKIP"}
               for row in payload["checks"])
    assert set(payload["summary"]) == {"total", "pass", "fail", "warn", "skip"}
    assert payload["summary"]["total"] == len(payload["checks"])
    assert payload["summary"]["fail"] == sum(
        row["status"] == "FAIL" for row in payload["checks"])
    assert result.returncode == (1 if payload["summary"]["fail"] else 0)
    assert len(payload["manual"]) == 4
    assert all(set(row) == {"name", "detail"} for row in payload["manual"])
    assert any("PreCompact" in row["name"] and "명령은 검증됨" in row["detail"]
               and "실제 발화만 미확인" in row["detail"] for row in payload["manual"])
    assert not result.stderr, result.stderr


def _fixture_root(commands):
    root = tempfile.mkdtemp(prefix="doctor-precompact-")
    os.makedirs(os.path.join(root, "tools"))
    os.makedirs(os.path.join(root, "system"))
    os.makedirs(os.path.join(root, "state"))
    for name in ("now.py", "memlib.py"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    config = {
        "schema_version": 4,
        "instance": {"name": "fixture", "context": "personal", "remote_allowlist": []},
        "tracks": [],
        "threads": [],
        "personal_pointer": None,
        "journal_visibility": {
            "public_tracks": ["system"],
            "legacy_cutoff": None,
            "legacy_public_tracks": [],
        },
        "journal_types": ["decision", "state", "artifact", "correction", "lesson",
                          "switch", "idea"],
        "thresholds": {
            "now_tail_events": 12,
            "now_recent_decisions": 8,
            "track_stale_days": 7,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_max_bytes": 6000,
            "now_hook_max_bytes": 6000,
        },
    }
    with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    for runtime, command in commands.items():
        rel = (".claude", "settings.json") if runtime == "claude" else (".codex", "hooks.json")
        os.makedirs(os.path.join(root, rel[0]))
        payload = {"hooks": {"PreCompact": [{"hooks": [{
            "type": "command", "command": command,
        }]}]}}
        with open(os.path.join(root, *rel), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    subprocess.run(["git", "init", "-q", root], check=True)
    return root


def _live_precompact_commands():
    commands = {}
    for runtime, rel in {
            "claude": (".claude", "settings.json"),
            "codex": (".codex", "hooks.json"),
    }.items():
        cfg = json.load(open(os.path.join(ROOT, *rel), encoding="utf-8"))
        commands[runtime] = cfg["hooks"]["PreCompact"][0]["hooks"][0]["command"]
    return commands


def test_precompact_simulation_passes_for_both_runtimes():
    import doctor
    root = _fixture_root(_live_precompact_commands())
    old_root = doctor.ROOT
    try:
        doctor.ROOT = root
        for runtime in ("claude", "codex"):
            status, detail = doctor._simulate_precompact(runtime)
            assert status == doctor.PASS, f"{runtime}: {detail}"
            assert doctor.t("doctor.precompact_marker") in detail
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_precompact_simulation_fails_without_journal_effect():
    import doctor
    root = _fixture_root({"claude": "true", "codex": "true"})
    old_root = doctor.ROOT
    try:
        doctor.ROOT = root
        for runtime in ("claude", "codex"):
            status, detail = doctor._simulate_precompact(runtime)
            assert status == doctor.FAIL, f"{runtime}: {detail}"
            assert "journal" in detail
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_reads_last_canary_result():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-canary-")
    old_root = doctor.ROOT
    checked_at = datetime.datetime(2026, 9, 17, 5, 30, tzinfo=datetime.timezone.utc).isoformat()
    try:
        os.makedirs(os.path.join(root, "state"))
        with open(os.path.join(root, "state", "hook-canary.json"), "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": 1,
                "runtimes": {
                    "codex": {
                        "checked_at": checked_at,
                        "status": "PASS",
                        "dispatcher_fired": "verified",
                        "effect": "verified",
                    },
                    "claude": {
                        "checked_at": checked_at,
                        "status": "PASS",
                        "dispatcher_fired": "verified",
                        "effect": "verified",
                    },
                },
            }, f)
        doctor.ROOT = root
        detail = doctor._canary_evidence("codex")
        assert checked_at in detail
        assert "verified" in detail
        assert "unknown" not in detail
        os.makedirs(os.path.join(root, ".claude"))
        with open(os.path.join(root, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command":
                    "echo state/NOW.md _private/state/NOW.md unavailable"}]}],
                "PreCompact": [{"hooks": [{"type": "command", "command": "true"}]}],
            }}, f)
        _, wiring_detail = doctor._wiring("claude")
        assert checked_at in wiring_detail and "fired/effect=unknown" not in wiring_detail
        assert "unknown" in doctor._canary_evidence("missing")
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_context_budget_over_line_is_warn_not_fail():
    import context_budget
    import doctor
    original = context_budget.measure
    report = {"total": {"bytes": 30000, "tokens": 9000}, "warnings": ["memory_index", "total"]}
    try:
        context_budget.measure = lambda: report
        status, detail = doctor.c_context_budget()
        assert status == doctor.WARN, (status, detail)
        assert "memory_index" in detail and "context_budget.py" in detail
        report["warnings"] = []
        status, _detail = doctor.c_context_budget()
        assert status == doctor.PASS
    finally:
        context_budget.measure = original
    assert any(fn is doctor.c_context_budget for _name, fn in doctor.CHECKS)


def _growth_tree(root):
    """Build a workspace shaped like a used instance: Git history, stale tmp/, work folders."""
    old = time.time() - 30 * 86400
    os.makedirs(os.path.join(root, "tmp", "old-job"))
    with open(os.path.join(root, "tmp", "old-job", "copy.bin"), "wb") as f:
        f.write(b"x" * 4096)
    os.utime(os.path.join(root, "tmp", "old-job", "copy.bin"), (old, old))
    with open(os.path.join(root, "tmp", "fresh.txt"), "w", encoding="utf-8") as f:
        f.write("recent")
    work = os.path.join(root, "_private", "work")
    for name in ("guided", "bare-1", "bare-2"):
        os.makedirs(os.path.join(work, name))
    with open(os.path.join(work, "guided", "STATE.md"), "w", encoding="utf-8") as f:
        f.write("# job\n")
    with open(os.path.join(work, "bare-1", "notes.md"), "w", encoding="utf-8") as f:
        f.write("no guide page\n")
    os.makedirs(os.path.join(work, "bare-2", "sub"))
    with open(os.path.join(work, "bare-2", "sub", "README.md"), "w", encoding="utf-8") as f:
        f.write("guide below the top does not count\n")
    subprocess.run(["git", "init", "-q", root], check=True)
    with open(os.path.join(root, "engine.py"), "w", encoding="utf-8") as f:
        f.write("print('engine')\n")
    subprocess.run(["git", "-C", root, "add", "engine.py"], check=True)
    # A commit starts `git maintenance run --auto --detach`, which holds a lock file under .git
    # after the commit returns. Turn it off so nothing but the code under test can touch the tree.
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "maintenance.auto=false", "-c", "gc.auto=0",
                    "commit", "-q", "--no-verify", "-m", "x"], check=True)


def _plenty_of_disk(_path):
    return types.SimpleNamespace(total=100 * 1024 ** 4, used=0, free=50 * 1024 ** 4)


def _snapshot(root):
    rows = {}
    for base, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(base, name)
            st = os.lstat(path)
            rows[path] = (st.st_size, st.st_mtime_ns)
    return rows


def test_growth_fresh_install_shape_has_no_warning():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-fresh-")
    try:
        subprocess.run(["git", "init", "-q", root], check=True)
        status, detail, items = doctor._growth_report(root, {}, disk_usage=_plenty_of_disk)
        assert status == doctor.PASS, (status, detail)
        assert items["disk"]["state"] == "ok"
        assert items["git"]["state"] == "ok"
        assert items["tmp"]["state"] == "na", items["tmp"]
        assert items["work"]["state"] == "na", items["work"]
        assert doctor.t("doctor.growth_na", item=doctor.t("doctor.growth_item_work")) in detail
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert any(fn is doctor.c_workspace_growth for _name, fn in doctor.CHECKS)


def test_growth_missing_folders_are_not_applicable():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-empty-")
    try:
        config = {"growth": {"work_dirs": ["no/such/dir"]}}
        status, detail, items = doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        assert status == doctor.PASS, (status, detail)
        assert [items[k]["state"] for k in ("git", "tmp", "work")] == ["na", "na", "na"], items
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_growth_lowered_lines_warn_each_item_and_never_fail():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-warn-")
    try:
        _growth_tree(root)
        config = {"thresholds": {
            "growth_disk_free_min_bytes": 200 * 1024 ** 4,
            "growth_git_max_bytes": 0,
            "growth_tmp_stale_max_bytes": 1024,
            "growth_unguided_work_dirs_max": 1,
        }}
        status, detail, items = doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        assert status == doctor.WARN, (status, detail)
        assert all(items[k]["state"] == "over" for k in ("disk", "git", "tmp", "work")), items
        assert items["tmp"]["value"] == 4096, items["tmp"]
        assert "old-job" in detail and "fresh.txt" not in detail
        # A guide page at the top of the folder counts; one deeper down does not.
        assert items["work"]["value"] == 2, items["work"]
        assert "bare-1" in detail and "bare-2" in detail and "guided" not in detail

        status, detail, items = doctor._growth_report(root, {}, disk_usage=_plenty_of_disk)
        assert status == doctor.PASS, (status, detail)
        assert all(items[k]["state"] == "ok" for k in ("disk", "git", "tmp", "work")), items
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_growth_check_writes_nothing():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-ro-")
    try:
        _growth_tree(root)
        before = _snapshot(root)
        config = {"thresholds": {"growth_git_max_bytes": 0, "growth_tmp_stale_max_bytes": 0,
                                 "growth_unguided_work_dirs_max": 0}}
        doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        doctor._growth_report(root, {}, disk_usage=_plenty_of_disk)
        after = _snapshot(root)
        changed = sorted(os.path.relpath(path, root) for path in set(before) | set(after)
                         if before.get(path) != after.get(path))
        assert not changed, changed
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_growth_large_tmp_stops_at_time_limit():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-big-")
    try:
        for d in range(40):
            folder = os.path.join(root, "tmp", f"d{d}")
            os.makedirs(folder)
            for n in range(250):
                open(os.path.join(folder, f"f{n}"), "w").close()
        config = {"thresholds": {"growth_scan_budget_ms": 1}}
        started = time.monotonic()
        status, detail, items = doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        elapsed = time.monotonic() - started
        assert items["tmp"]["state"] == "unmeasured", items["tmp"]
        assert items["disk"]["state"] == "ok"
        assert status == doctor.WARN, (status, detail)
        assert doctor.t("doctor.growth_unmeasured", item=doctor.t("doctor.growth_item_tmp", days=14),
                        ms=1) in detail, detail
        assert elapsed < 0.5, elapsed
    finally:
        shutil.rmtree(root, ignore_errors=True)


FAST_TESTS = [
    test_context_budget_over_line_is_warn_not_fail,
    test_precompact_simulation_passes_for_both_runtimes,
    test_precompact_simulation_fails_without_journal_effect,
    test_doctor_reads_last_canary_result,
    test_growth_fresh_install_shape_has_no_warning,
    test_growth_missing_folders_are_not_applicable,
    test_growth_lowered_lines_warn_each_item_and_never_fail,
    test_growth_check_writes_nothing,
    test_growth_large_tmp_stops_at_time_limit,
]

FULL_TESTS = [test_json_schema_and_exit_status, *FAST_TESTS]


def run():
    tests = FULL_TESTS if "--full" in sys.argv else FAST_TESTS
    failed = []
    for test in tests:
        try:
            run_test(test, __file__)
            print(f"✓ {test.__name__}")
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(error).__name__}: {error}")
    mode = "full" if tests is FULL_TESTS else "fast"
    print(f"doctor json ({mode}): {len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
