#!/usr/bin/env python3
"""Fixture tests for the worker receipt ledger CLI."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
RECEIPTS = HERE / "receipts.py"


def _iso(days_ago):
    timezone = datetime.timezone(datetime.timedelta(hours=9))
    value = datetime.datetime.now(timezone) - datetime.timedelta(days=days_ago)
    return value.isoformat(timespec="seconds")


def _fixture(root, run_id, runtime, status, usage, prompt, days_ago, changed=0,
             worktree_files=None):
    run = root / "_private" / "work" / "runs" / run_id
    run.mkdir(parents=True)
    meta = {
        "schema_version": 2,
        "run": f"_private/work/runs/{run_id}",
        "run_id": run_id,
        "runtime": runtime,
        "status": status,
        "usage": usage,
        "scope": {
            "status": "ok" if runtime == "codex" else "unchecked",
            "changed_count": changed,
            "violation_count": 0,
        },
        "started_at": _iso(days_ago),
        "finished_at": _iso(days_ago),
        "process_exit": 0 if status == "success" else 1,
        "wrapper_exit": 0 if status == "success" else 1,
        "capability": "workspace-write" if runtime == "codex" else "read-only",
        "prompt_sha256": "a" * 64,
        "stream_sha256": "b" * 64,
        "result_sha256": "c" * 64,
        "result_bytes": 3,
    }
    if worktree_files is not None:
        meta["worktree"] = {
            "mode": "head",
            "files": worktree_files,
            "added": 2,
            "deleted": 1,
        }
    (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    contract = (
        "[fresh bounded worker contract]\n"
        "- runtime capability: fixture\n"
        "- common rule\n\n"
    )
    if runtime == "claude":
        contract += "- read-only reviewer\n- report only\n\n"
    (run / "prompt.md").write_text(contract + prompt + "\nsecond line\n", encoding="utf-8")
    (run / "result.txt").write_text("ok\n", encoding="utf-8")


def _root():
    root = Path(tempfile.mkdtemp(prefix="receipts-fixture-"))
    _fixture(root, "success-codex", "codex", "success",
             {"input": 100, "output": 20, "total": 120},
             "Codex successful prompt " + "x" * 80, 0, changed=7,
             worktree_files=["added.txt", "changed.txt"])
    _fixture(root, "failed-claude", "claude", "failed",
             {"input": 50, "output": 10, "total": 60},
             "Claude failed prompt", 1)
    _fixture(root, "null-usage", "codex", "success",
             {"input": None, "output": None, "total": None},
             "- Null usage prompt", 10)
    return root


def _run(root, *args):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root))
    return subprocess.run(
        [sys.executable, str(RECEIPTS), *args], cwd=root, env=env,
        text=True, capture_output=True,
    )


def test_list_table_and_totals():
    root = _root()
    try:
        result = _run(root, "list")
        assert result.returncode == 0, result.stderr
        assert "100/20/120" in result.stdout
        assert "-/-/-" in result.stdout
        assert "scope=ok" in result.stdout and "patch=2" in result.stdout
        assert "Codex successful prompt" in result.stdout
        assert "prompt=- Null usage prompt" in result.stdout
        codex_line = next(line for line in result.stdout.splitlines() if "success-codex" in line)
        meta = json.loads((root / "_private" / "work" / "runs" / "success-codex" /
                           "meta.json").read_text(encoding="utf-8"))
        assert codex_line.startswith(meta["started_at"][:19].replace("T", " "))
        shown_prompt = codex_line.split("prompt=", 1)[1].rsplit(" id=", 1)[0]
        assert len(shown_prompt) == 60
        assert "합계 runs=3 tokens=150/30/180 failures=1" in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_list_json_since_and_runtime_filters():
    root = _root()
    try:
        result = _run(root, "list", "--since", "7d", "--runtime", "codex", "--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert [row["run_id"] for row in payload["runs"]] == ["success-codex"]
        assert len(payload["runs"][0]["prompt"]) == 60
        assert payload["runs"][0]["usage"] == {"input": 100, "output": 20, "total": 120}
        assert payload["totals"] == {
            "runs": 1,
            "usage": {"input": 100, "output": 20, "total": 120},
            "failures": 0,
        }

        recent = _run(root, "list", "--since", "7d")
        assert recent.returncode == 0, recent.stderr
        assert "success-codex" in recent.stdout and "failed-claude" in recent.stdout
        assert "null-usage" not in recent.stdout
        assert "합계 runs=2 tokens=150/30/180 failures=1" in recent.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_show_meta_summary_and_receipt():
    root = _root()
    try:
        result = _run(root, "show", "success-codex")
        assert result.returncode == 0, result.stderr
        assert "META success-codex" in result.stdout
        assert "usage: 100/20/120" in result.stdout
        assert "scope: ok (changed 7, violations 0)" in result.stdout
        assert "RECEIPT\nFRESH_WORKER v1" in result.stdout
        assert "run: _private/work/runs/success-codex" in result.stdout
        assert "patch: 2 files (+2/-1)" in result.stdout
        assert result.stdout.endswith("result:\nok\n")

        sys.path.insert(0, str(HERE))
        import fresh_worker
        long_result = "head\n" + "긴 결과\n" * 2000 + "tail\n"
        run = root / "_private" / "work" / "runs" / "success-codex"
        (run / "result.txt").write_text(long_result, encoding="utf-8")
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        replay = _run(root, "show", "success-codex")
        assert replay.stdout.split("RECEIPT\n", 1)[1] == fresh_worker._receipt(meta, long_result)

        missing = _run(root, "show", "../outside")
        assert missing.returncode == 1 and "run을 찾을 수 없다" in missing.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cost_runtime_totals_and_daily_histogram():
    root = _root()
    try:
        result = _run(root, "cost")
        assert result.returncode == 0, result.stderr
        assert "codex runs=2 tokens=100/20/120 unknown=1" in result.stdout
        assert "claude runs=1 tokens=50/10/60 unknown=0" in result.stdout
        assert "하루 단위 히스토그램" in result.stdout
        assert result.stdout.count("runs=1 tokens=") >= 3
        assert "#" in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_recent_runs_threshold():
    root = _root()
    sys.path.insert(0, str(HERE))
    import doctor
    old_root = doctor.ROOT
    try:
        doctor.ROOT = str(root)
        status, detail = doctor.c_worker_receipts()
        assert status == doctor.PASS
        assert "runs=2" in detail and "tokens=150/30/180" in detail
        assert "failures=1 (50.0%)" in detail

        meta_path = root / "_private" / "work" / "runs" / "success-codex" / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["status"] = "failed"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        status, detail = doctor.c_worker_receipts()
        assert status == doctor.WARN and "failures=2 (100.0%)" in detail
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


TESTS = [test_list_table_and_totals, test_list_json_since_and_runtime_filters,
         test_show_meta_summary_and_receipt, test_cost_runtime_totals_and_daily_histogram,
         test_doctor_recent_runs_threshold]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
