#!/usr/bin/env python3
"""Fixture tests for the trigger store CLI (tools/triggers.py)."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = Path(__file__).resolve().parent
TRIGGERS = HERE / "triggers.py"


def _run(root, *args):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root))
    return subprocess.run([sys.executable, str(TRIGGERS), *args], text=True,
                          capture_output=True, env=env)


def _fixture():
    root = Path(tempfile.mkdtemp(prefix="triggers-fixture-"))
    (root / "system").mkdir()
    (root / "_private" / "work").mkdir(parents=True)
    return root


def test_add_due_fire_and_tier_boundary():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "date:2026-09-20", "--what", "send the minutes",
                 "--tier", "T2", "--source", "x.md:3", "--date", "2026-09-19")
        assert r.returncode == 0 and r.stdout.startswith("added tr-"), r
        tid = r.stdout.split()[1]
        r = _run(root, "add", "--when", "date:2026-09-20", "--what", "send the minutes",
                 "--tier", "T2", "--source", "x.md:3", "--date", "2026-09-19")
        assert r.stdout.startswith("exists"), "same when/what/source must be idempotent"
        r = _run(root, "due", "--date", "2026-09-19")
        assert r.stdout.strip() == "due 0", r.stdout
        r = _run(root, "due", "--date", "2026-09-21")
        assert "[T2 ask" in r.stdout and "draft only" in r.stdout and "due 1" in r.stdout, r.stdout
        r = _run(root, "fire", tid, "--outcome", "sent by owner", "--date", "2026-09-21", "--holder", "owner")
        assert r.returncode == 2 and "no live lease" in r.stderr, "fire needs a claim first"
        r = _run(root, "claim", tid, "--holder", "owner")
        assert r.returncode == 0
        r = _run(root, "fire", tid, "--outcome", "sent by owner", "--date", "2026-09-21", "--holder", "owner")
        assert r.returncode == 0, r.stderr
        r = _run(root, "due", "--date", "2026-09-22")
        assert r.stdout.strip() == "due 0"
        store = root / "_private" / "triggers" / "triggers.jsonl"
        row = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
        assert row["fired"] == "2026-09-21" and row["outcome"] == "sent by owner"
        assert row["state"] == "fired" and row["privacy"] == "private" and row["destination"] == "local"
        assert [e["event"] for e in row["history"]] == ["added", "claimed", "fired"]
        assert oct(store.stat().st_mode & 0o777) == "0o600"
        r = _run(root, "fire", tid, "--date", "2026-09-22")
        assert r.returncode == 2 and "already fired" in r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_only_commands_touch_nothing_on_a_fresh_root():
    root = _fixture()
    try:
        r = _run(root, "hook", "--date", "2026-09-19")
        assert r.returncode == 0 and r.stdout == ""
        r = _run(root, "due", "--date", "2026-09-19")
        assert r.stdout.strip() == "due 0"
        r = _run(root, "list")
        assert r.stdout.strip() == "total 0"
        assert not (root / "_private" / "triggers").exists(), "read-only commands must not create the store"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_invalid_inputs_exit_2():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "soon", "--what", "x")
        assert r.returncode == 2 and "when must be" in r.stderr
        r = _run(root, "add", "--when", "date:2026-13-01", "--what", "x")
        assert r.returncode == 2 and "YYYY-MM-DD" in r.stderr
        r = _run(root, "add", "--when", "event:", "--what", "x")
        assert r.returncode == 2
        r = _run(root, "fire", "tr-nope")
        assert r.returncode == 2 and "unknown trigger id" in r.stderr
        r = _run(root, "add", "--when", "event:x", "--what", "x", "--destination", "external")
        assert r.returncode == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_limits_and_auto_sleep_after_ignores():
    root = _fixture()
    try:
        for i in range(7):
            r = _run(root, "add", "--when", "date:2026-09-01", "--what", f"item {i}", "--tier", "T0",
                     "--date", "2026-08-30")
            assert r.returncode == 0
        r = _run(root, "hook", "--date", "2026-09-19")
        payload = json.loads(r.stdout)["hookSpecificOutput"]
        assert payload["hookEventName"] == "SessionStart"
        assert payload["additionalContext"].count("\n- [T0") == 5, payload["additionalContext"]
        seen = set(re.findall(r"item \d", payload["additionalContext"]))
        r = _run(root, "hook", "--date", "2026-09-19", "--format", "text")
        seen |= set(re.findall(r"item \d", r.stdout))
        assert len(seen) == 7, f"carry-over must show every due item within two sessions: {sorted(seen)}"
        for _ in range(5):
            _run(root, "hook", "--date", "2026-09-19")
        rows = [json.loads(l) for l in (root / "_private" / "triggers" / "triggers.jsonl")
                .read_text(encoding="utf-8").splitlines()]
        slept = [x for x in rows if x.get("slept_until")]
        assert slept and all(x["ignored"] == 1 and x["state"] == "asleep" for x in slept), rows
        assert all(e["event"] == "auto-sleep" for x in slept for e in x["history"][-1:])
        r = _run(root, "due", "--date", "2026-09-30")
        assert "due 5" in r.stdout, "auto sleep must expire after the sleep window"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_claim_lease_refuses_second_holder_and_due_stays_read_only():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "draft the minutes", "--date", "2026-08-30")
        tid = r.stdout.split()[1]
        r = _run(root, "claim", tid, "--minutes", "30", "--holder", "alice")
        assert r.returncode == 0 and r.stdout.startswith("leased ") and "by alice" in r.stdout, r
        r = _run(root, "claim", tid, "--minutes", "30", "--holder", "bob")
        assert r.returncode == 2 and "is leased by alice" in r.stderr
        r = _run(root, "claim", tid, "--minutes", "30", "--holder", "alice")
        assert r.returncode == 0, "the holder may renew its own lease"
        r = _run(root, "fire", tid, "--holder", "bob", "--date", "2026-09-19")
        assert r.returncode == 2 and "is leased by alice" in r.stderr
        for _ in range(4):
            r = _run(root, "due", "--date", "2026-09-19")
            assert "due 1" in r.stdout, "due without --mark must never count as shown"
        store = root / "_private" / "triggers" / "triggers.jsonl"
        before = store.read_text(encoding="utf-8")
        for _ in range(3):
            _run(root, "hook", "--date", "2026-09-19")      # shown reaches the ignore limit
        r = _run(root, "due", "--date", "2026-09-19")
        assert "due 0" in r.stdout, "a read-only due hides an about-to-sleep item"
        after = store.read_text(encoding="utf-8")
        assert json.loads(after.splitlines()[0])["slept_until"] is None, "read-only due must not write a sleep"
        r = _run(root, "fire", tid, "--holder", "alice", "--outcome", "done", "--date", "2026-09-19")
        assert r.returncode == 0, r.stderr
        r = _run(root, "claim", tid, "--holder", "alice")
        assert r.returncode == 2 and "already fired" in r.stderr
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "second item", "--date", "2026-08-30")
        r = _run(root, "hook", "--date", "2026-09-19", "--format", "text")
        assert r.stdout.startswith("[triggers due today]") and "second item" in r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scan_experiments_and_decision_rereviews():
    root = _fixture()
    try:
        (root / "_private" / "work" / "experiments.md").write_text(
            "# registry\n\n| ID | 실험 | 트리거 | 만기 | 재는 것 | 상태 | 판정 |\n|---|---|---|---|---|---|---|\n"
            "| X1 | pilot one | approval | 9/20 report | fill rate | 진행 중 | path |\n"
            "| X2 | no date | approval | after the next job | n | 트리거 대기 | path |\n"
            "| X3 | closed one | approval | 2026-09-10 | n | 완료 | path |\n"
            "| X4 | iso date | approval | 2026-10-04 | n | 적용 | path |\n", encoding="utf-8")
        (root / "system" / "decisions.md").write_text(
            "### DR-051 loops run mechanically (2026-09-06 · active-pilot · 3주기 후 재판정)\n\n"
            "### DR-052 attribution pilot (2026-09-07 · active-pilot · 9/20 재판정)\n\n"
            "### DR-054 export names (2026-09-17 · active)\n", encoding="utf-8")
        (root / "system" / "memory-config.json").write_text(json.dumps({"triggers": {"sources": {
            "experiments": {"closed_status": "완료|철회|종료"},
            "decisions": {"rereview_marker": "재판정", "cycles_later": "(\\d+)\\s*주기\\s*후"}}}},
            ensure_ascii=False), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 0, r.stderr
        assert "scan added 4 total 4" in r.stdout, r.stdout
        rows = {json.loads(l)["id"]: json.loads(l) for l in
                (root / "_private" / "triggers" / "triggers.jsonl").read_text(encoding="utf-8").splitlines()}
        assert rows["exp-X1"]["when"] == "date:2026-09-20" and rows["exp-X1"]["source"].endswith(":5")
        assert "exp-X2" not in rows and "exp-X3" not in rows
        assert rows["exp-X4"]["when"] == "date:2026-10-04"
        assert rows["rereview-DR-051"]["when"] == "date:2026-09-27", rows["rereview-DR-051"]
        assert rows["rereview-DR-052"]["when"] == "date:2026-09-20"
        assert "rereview-DR-054" not in rows
        r = _run(root, "scan", "--date", "2026-09-19")
        assert "scan added 0 total 4" in r.stdout, "scan must be idempotent"
        (root / "system" / "memory-config.json").write_text(json.dumps({"triggers": {"sources": {
            "decisions": {"cycles_later": "(unclosed"}}}}), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "not a valid regex" in r.stderr, r
        (root / "system" / "memory-config.json").write_text(json.dumps({"triggers": {"sources": ["x"]}}), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "must be an object" in r.stderr, r
        (root / "system" / "memory-config.json").write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "top level must be an object" in r.stderr, r
        (root / "system" / "memory-config.json").write_text(json.dumps({"triggers": "x"}), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "triggers must be an object" in r.stderr, r
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_add_due_fire_and_tier_boundary,
    test_read_only_commands_touch_nothing_on_a_fresh_root,
    test_invalid_inputs_exit_2,
    test_hook_limits_and_auto_sleep_after_ignores,
    test_claim_lease_refuses_second_holder_and_due_stays_read_only,
    test_scan_experiments_and_decision_rereviews,
]


if __name__ == "__main__":
    for test in TESTS:
        run_test(test, __file__)
        print("PASS", test.__name__)
