#!/usr/bin/env python3
"""doctor JSON output and isolated PreCompact simulation fixtures."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

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


TESTS = [
    test_json_schema_and_exit_status,
    test_precompact_simulation_passes_for_both_runtimes,
    test_precompact_simulation_fails_without_journal_effect,
    test_doctor_reads_last_canary_result,
]


def run():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(error).__name__}: {error}")
    print(f"doctor json: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
