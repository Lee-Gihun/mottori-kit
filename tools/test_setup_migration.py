#!/usr/bin/env python3
"""setup.sh의 v1/v2/v3→v4 migration과 기존 v4 보존 privacy E2E.

배포 킷에만 setup.sh가 있으므로 이 suite도 킷 전용이다. 각 case는 임시 clone 모양에서 돌며
실제 인스턴스 config/state에는 손대지 않는다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def base_config(schema):
    return {
        "schema_version": schema,
        "instance": {"name": "old", "context": "personal", "remote_allowlist": []},
        "episodic_sources": [],
        "tracks": [],
        "personal_pointer": None,
        "threads": [],
        "checks": {},
        "journal_types": ["decision", "state", "artifact", "correction", "lesson", "switch", "idea"],
        "thresholds": {
            "now_tail_events": 12,
            "now_recent_decisions": 8,
            "track_stale_days": 7,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_hook_max_bytes": 6000,
        },
    }


def fixture(old_cfg, rows):
    parent = tempfile.mkdtemp(prefix="setup-migration-")
    root = os.path.join(parent, "repo")
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
        ".git", "state", "_private", "__pycache__", "*.pyc"))
    for name in ("memory-config.json", "memory-config.json.bak"):
        try:
            os.remove(os.path.join(root, "system", name))
        except FileNotFoundError:
            pass
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    os.makedirs(os.path.join(root, "system"), exist_ok=True)
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    if old_cfg is not None:
        with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
            json.dump(old_cfg, f, ensure_ascii=False, indent=2)
    with open(os.path.join(root, "state", "journal-2026-01.md"), "w", encoding="utf-8") as f:
        f.write("# journal\n\n" + "".join(rows))
    # 이 E2E의 관측 대상은 setup migration과 실제 now engine이다. 주변 doctor/gate는 별도
    # suite가 소유하므로 임시 clone에서는 deterministic no-op으로 둔다.
    for name in ("doctor.py", "gate.py"):
        with open(os.path.join(root, "tools", name), "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env python3\nraise SystemExit(0)\n")
    return parent, root


def run_setup(root, env=None):
    return subprocess.run(
        ["bash", "setup.sh", "--force", "--name", "fixture", "--context", "personal"],
        cwd=root, capture_output=True, text=True, env=env)


def run_now(root, *args):
    return subprocess.run([sys.executable, "tools/now.py", *args], cwd=root,
                          capture_output=True, text=True)


def text(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def file_snapshot(root):
    """작은 fixture tree의 파일 bytes. hostile target 무변경 검증용."""
    out = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root)
            with open(path, "rb") as f:
                out[rel] = f.read()
    return out


def assert_setup_aborts_without_config_overwrite(root):
    cfg_path = os.path.join(root, "system", "memory-config.json")
    before = open(cfg_path, "rb").read()
    result = run_setup(root)
    after = open(cfg_path, "rb").read()
    backup = open(cfg_path + ".bak", "rb").read()
    assert result.returncode != 0, result.stdout + result.stderr
    assert before == after == backup


def test_fresh_setup_creates_v4_config_and_now():
    parent, root = fixture(None, [])
    try:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        cfg = json.load(open(os.path.join(root, "system", "memory-config.json"), encoding="utf-8"))
        assert cfg["schema_version"] == 4
        vis = cfg["journal_visibility"]
        assert vis["public_tracks"] == ["system"]
        assert vis["legacy_cutoff"] is None
        assert vis["legacy_public_tracks"] == []
        assert os.path.isfile(os.path.join(root, "state", "NOW.md"))
        assert "인스턴스 세팅" in text(root, "state/NOW.md")
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_setup_binds_instance_to_its_own_root():
    old = base_config(2)
    parent, root = fixture(old, [
        "- 2026-01-01T00:00:00+09:00 [system/state] OWN-ROOT-ROW\n",
    ])
    hostile = os.path.join(parent, "hostile-instance")
    try:
        hostile_cfg = base_config(4)
        hostile_cfg["journal_visibility"] = {
            "public_tracks": ["system"],
            "legacy_cutoff": None,
            "legacy_public_tracks": [],
        }
        os.makedirs(os.path.join(hostile, "system"), exist_ok=True)
        os.makedirs(os.path.join(hostile, "state"), exist_ok=True)
        with open(os.path.join(hostile, "system", "memory-config.json"), "w", encoding="utf-8") as f:
            json.dump(hostile_cfg, f, ensure_ascii=False, indent=2)
        with open(os.path.join(hostile, "state", "journal-2026-01.md"), "w", encoding="utf-8") as f:
            f.write("# journal\n\n"
                    "- 2026-01-02T00:00:00+09:00 [system/state] HOSTILE-ROW\n")
        before = file_snapshot(hostile)
        env = dict(os.environ, MOTTORI_INSTANCE=hostile)
        result = run_setup(root, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        cfg = json.load(open(os.path.join(root, "system", "memory-config.json"), encoding="utf-8"))
        assert cfg["journal_visibility"]["legacy_cutoff"] == "2026-01-01T00:00:00+09:00"
        assert file_snapshot(hostile) == before
        assert "OWN-ROOT-ROW" in text(root, "_private/state/NOW.md")
        assert "HOSTILE-ROW" not in text(root, "state/NOW.md")
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_setup_backup_is_gitignored():
    old = base_config(4)
    old["journal_visibility"] = {
        "public_tracks": ["system"],
        "legacy_cutoff": None,
        "legacy_public_tracks": [],
    }
    parent, root = fixture(old, [])
    try:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        backup = os.path.join(root, "system", "memory-config.json.bak")
        assert os.path.isfile(backup)
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", "system/memory-config.json.bak"],
            cwd=root)
        assert ignored.returncode == 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_v2_history_is_fail_closed_and_cannot_be_retro_promoted():
    old = base_config(2)
    parent, root = fixture(old, [
        "- 2026-01-01T00:00:00+09:00 [system/state] V2-OLD-SYSTEM\n",
        "- 2026-01-01T00:00:01+09:00 [novel/state] V2-OLD-NOVEL\n",
    ])
    try:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        cfg_path = os.path.join(root, "system", "memory-config.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        vis = cfg["journal_visibility"]
        assert cfg["schema_version"] == 4
        assert vis["legacy_cutoff"] == "2026-01-01T00:00:01+09:00"
        assert vis["legacy_public_tracks"] == []
        public = text(root, "state/NOW.md")
        local = text(root, "_private/state/NOW.md")
        assert "V2-OLD-SYSTEM" not in public and "V2-OLD-NOVEL" not in public
        assert "V2-OLD-SYSTEM" in local and "V2-OLD-NOVEL" in local

        vis["public_tracks"].append("novel")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        rendered = run_now(root, "render")
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        assert "V2-OLD-NOVEL" not in text(root, "state/NOW.md")
        logged = run_now(root, "log", "[novel/state] V2-NEW-NOVEL")
        assert logged.returncode == 0, logged.stdout + logged.stderr
        public = text(root, "state/NOW.md")
        assert "V2-NEW-NOVEL" in public and "V2-OLD-NOVEL" not in public
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_v1_empty_config_with_history_is_fail_closed():
    parent, root = fixture({}, [
        "- 2026-01-01T00:00:00+09:00 [novel/state] V1-OLD-NOVEL\n",
    ])
    try:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        cfg_path = os.path.join(root, "system", "memory-config.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        vis = cfg["journal_visibility"]
        assert vis["legacy_cutoff"] == "2026-01-01T00:00:00+09:00"
        assert vis["legacy_public_tracks"] == []
        vis["public_tracks"].append("novel")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        rendered = run_now(root, "render")
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        assert "V1-OLD-NOVEL" not in text(root, "state/NOW.md")
        assert "V1-OLD-NOVEL" in text(root, "_private/state/NOW.md")
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_v3_freezes_the_preexisting_approved_set():
    old = base_config(3)
    old["journal_visibility"] = {"public_tracks": ["system", "shared"]}
    parent, root = fixture(old, [
        "- 2026-01-01T00:00:00+09:00 [shared/state] V3-OLD-SHARED\n",
        "- 2026-01-01T00:00:01+09:00 [novel/state] V3-OLD-NOVEL\n",
    ])
    try:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        cfg = json.load(open(os.path.join(root, "system", "memory-config.json"), encoding="utf-8"))
        vis = cfg["journal_visibility"]
        assert vis["legacy_cutoff"] == "2026-01-01T00:00:01+09:00"
        assert vis["legacy_public_tracks"] == ["system", "shared"]
        public = text(root, "state/NOW.md")
        local = text(root, "_private/state/NOW.md")
        assert "V3-OLD-SHARED" in public and "V3-OLD-NOVEL" not in public
        assert "V3-OLD-NOVEL" in local
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_v4_preserves_existing_visibility_cutover_semantics():
    old = base_config(4)
    old["journal_visibility"] = {
        "public_tracks": ["system", "shared"],
        "legacy_cutoff": "2026-01-01T00:00:00+09:00",
        "legacy_public_tracks": ["system"],
    }
    old["threads"] = [{
        "key": "public-thread", "name": "PUBLIC-THREAD", "dossier": "research/HANDOFF.md",
    }]
    parent, root = fixture(old, [
        "- 2026-01-01T00:00:00+09:00 [system/state] V4-OLD-SYSTEM\n",
    ])
    try:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        cfg = json.load(open(os.path.join(root, "system", "memory-config.json"), encoding="utf-8"))
        vis = cfg["journal_visibility"]
        assert vis["public_tracks"] == ["system", "shared"]
        assert vis["legacy_cutoff"] == "2026-01-01T00:00:00+09:00"
        assert vis["legacy_public_tracks"] == ["system"]
        assert cfg["threads"] == old["threads"]
        assert "V4-OLD-SYSTEM" in text(root, "state/NOW.md")
        public_now = text(root, "state/NOW.md")
        assert "PUBLIC-THREAD" in public_now and "research/HANDOFF.md" in public_now
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_malformed_legacy_journal_aborts_without_overwriting_v2_config():
    old = base_config(2)
    parent, root = fixture(old, [
        "- 2026-01-01T00:00:00+09:00 [system/not-a-valid-type] PREFIX-LOOKS-VALID\n"
    ])
    try:
        before = open(os.path.join(root, "system", "memory-config.json"), "rb").read()
        result = run_setup(root)
        after = open(os.path.join(root, "system", "memory-config.json"), "rb").read()
        backup = open(os.path.join(root, "system", "memory-config.json.bak"), "rb").read()
        assert result.returncode != 0
        assert before == after == backup
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_legacy_type_removed_from_new_schema_aborts_before_overwrite():
    old = base_config(2)
    old["journal_types"] = ["legacy_only"]
    parent, root = fixture(old, [
        "- 2026-01-01T00:00:00+09:00 [system/legacy_only] OLD-ONLY-TYPE\n",
    ])
    try:
        assert_setup_aborts_without_config_overwrite(root)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_structurally_invalid_config_aborts_without_overwrite():
    old = base_config(2)
    old["tracks"] = "not-a-list"
    parent, root = fixture(old, [])
    try:
        assert_setup_aborts_without_config_overwrite(root)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_v2_legacy_thread_without_public_proof_aborts_without_overwrite():
    old = base_config(2)
    old["threads"] = [{
        "key": "legacy", "name": "LEGACY-THREAD", "dossier": "_private/work/HANDOFF.md",
    }]
    parent, root = fixture(old, [])
    try:
        assert_setup_aborts_without_config_overwrite(root)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_v3_legacy_thread_without_public_proof_aborts_without_overwrite():
    old = base_config(3)
    old["journal_visibility"] = {"public_tracks": ["system"]}
    old["threads"] = [{
        "key": "legacy", "name": "LEGACY-THREAD", "dossier": "_private/work/HANDOFF.md",
    }]
    parent, root = fixture(old, [])
    try:
        assert_setup_aborts_without_config_overwrite(root)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_v3_nonempty_threads_abort_even_with_ad_hoc_visibility_field():
    old = base_config(3)
    old["journal_visibility"] = {"public_tracks": ["system"]}
    old["threads"] = [{
        "key": "legacy", "name": "LEGACY-THREAD", "dossier": "research/HANDOFF.md",
        "visibility": "public",
    }]
    parent, root = fixture(old, [])
    try:
        assert_setup_aborts_without_config_overwrite(root)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


TESTS = [
    test_fresh_setup_creates_v4_config_and_now,
    test_setup_binds_instance_to_its_own_root,
    test_setup_backup_is_gitignored,
    test_v1_empty_config_with_history_is_fail_closed,
    test_v2_history_is_fail_closed_and_cannot_be_retro_promoted,
    test_v3_freezes_the_preexisting_approved_set,
    test_v4_preserves_existing_visibility_cutover_semantics,
    test_malformed_legacy_journal_aborts_without_overwriting_v2_config,
    test_legacy_type_removed_from_new_schema_aborts_before_overwrite,
    test_structurally_invalid_config_aborts_without_overwrite,
    test_v2_legacy_thread_without_public_proof_aborts_without_overwrite,
    test_v3_legacy_thread_without_public_proof_aborts_without_overwrite,
    test_v3_nonempty_threads_abort_even_with_ad_hoc_visibility_field,
]


def run():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as e:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
    print(f"setup migration: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
