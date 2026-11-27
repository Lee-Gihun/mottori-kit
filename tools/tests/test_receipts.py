#!/usr/bin/env python3
"""Fixture tests for the worker receipt ledger CLI."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent.parent
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
        "result_sha256": hashlib.sha256(b"ok\n").hexdigest(),
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
    # Build prompt.md with the real worker preamble so a preamble change breaks this test.
    sys.path.insert(0, str(HERE))
    import receipts
    (run / "prompt.md").write_text(
        receipts.worker_prompt(meta["capability"], prompt + "\nsecond line\n"), encoding="utf-8")
    (run / "result.txt").write_text("ok\n", encoding="utf-8")
    (run / "result-contract.json").write_text(json.dumps({
        "schema_version": 1,
        "valid": True,
        "verdict": "PASS",
        "summary": "ok",
        "evidence": ["tools/fixture.py:1"],
        "unknowns": [],
        "error": None,
    }), encoding="utf-8")


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
        assert "prompt=Claude failed prompt id=failed-claude" in result.stdout
        codex_line = next(line for line in result.stdout.splitlines() if "success-codex" in line)
        meta = json.loads((root / "_private" / "work" / "runs" / "success-codex" /
                           "meta.json").read_text(encoding="utf-8"))
        assert codex_line.startswith(meta["started_at"][:19].replace("T", " "))
        shown_prompt = codex_line.split("prompt=", 1)[1].rsplit(" id=", 1)[0]
        assert len(shown_prompt) == 60
        assert "total runs=3 tokens=150/30/180 (usage from 2 runs) failures=1 still marked running=0" \
            in result.stdout, result.stdout
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
        import receipts
        long_result = "head\n" + "긴 결과\n" * 2000 + "tail\n"
        run = root / "_private" / "work" / "runs" / "success-codex"
        (run / "result.txt").write_text(long_result, encoding="utf-8")
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        meta["result_sha256"] = hashlib.sha256(long_result.encode("utf-8")).hexdigest()
        (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        # The clipped receipt names `show` as the way back to the full text, so show never clips.
        clipped = receipts.render_receipt(meta, long_result)
        assert "python3 tools/receipts.py show success-codex" in clipped
        replay = _run(root, "show", "success-codex")
        shown = replay.stdout.split("RECEIPT\n", 1)[1]
        assert shown == receipts.render_receipt(meta, long_result, max_bytes=None)
        assert shown.endswith("result:\n" + long_result)
        assert shown.split("result:\n", 1)[0] == clipped.split("result:\n", 1)[0]

        # Bytes changed after the run: the verdict they carry is not shown as the run's.
        (run / "result.txt").write_text(
            'RESULT_JSON: {"verdict":"FAIL","summary":"s","evidence":["a"],"unknowns":["u"]}\n',
            encoding="utf-8")
        changed = _run(root, "show", "success-codex")
        assert changed.returncode == 0, changed.stderr
        assert "verdict: WITHHELD (result.txt differs from result_sha256)" in changed.stdout
        assert "verdict: FAIL" not in changed.stdout and "unknowns:" not in changed.stdout
        assert "no longer matches the result_sha256" in changed.stdout

        # No recorded hash means nothing to compare, not a change.
        meta["result_sha256"] = None
        (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        unrecorded = _run(root, "show", "success-codex")
        assert "verdict: FAIL" in unrecorded.stdout and "WITHHELD" not in unrecorded.stdout, unrecorded.stdout
        assert "recorded no result_sha256" in unrecorded.stdout

        for bad in ("../outside", ".."):
            missing = _run(root, "show", bad)
            assert missing.returncode == 1 and "run not found" in missing.stderr, bad
    finally:
        shutil.rmtree(root, ignore_errors=True)


# The contract blocks as the first published engine wrote them, before later rules were added.
_OLDEST_BLOCKS = (
    "[fresh bounded worker contract]\n- runtime capability: {capability}\n"
    "- This is a fresh, non-resumable worker. Read AGENTS.md and the named disk sources.\n\n"
)
_OLDEST_READ_ONLY = "- You are a read-only reviewer.\n\n"


def test_prompt_line_is_the_body_as_written():
    """The list shows the first line of the caller's body as written, a leading "-" included, under
    today's contract blocks and under the oldest ones; a prompt.md without blocks shows its own
    first line."""
    sys.path.insert(0, str(HERE))
    import receipts

    def oldest(capability, body):
        blocks = _OLDEST_BLOCKS.format(capability=capability)
        return blocks + (_OLDEST_READ_ONLY if capability == receipts.READ_ONLY else "") + body

    with tempfile.TemporaryDirectory(prefix="receipts-prompt-line-") as td:
        run = Path(td)
        for layout in (receipts.worker_prompt, oldest):
            for capability in (receipts.READ_ONLY, "workspace-write"):
                for body, shown in (("- first item\n- second\n", "- first item"),
                                    ("\n\n-x\nmore\n", "-x"), ("plain\n", "plain")):
                    (run / "prompt.md").write_text(layout(capability, body), encoding="utf-8")
                    assert receipts._prompt_first_line(run, capability) == shown, \
                        (layout.__name__, capability, body)
        (run / "prompt.md").write_text("\n- written by hand\n", encoding="utf-8")
        assert receipts._prompt_first_line(run, "workspace-write") == "- written by hand"


def test_status_vocabulary_is_shared_by_worker_and_ledger():
    sys.path.insert(0, str(HERE))
    import fresh_worker
    import receipts
    assert fresh_worker.R is receipts
    assert set(receipts.FINISHED_STATUSES) == {
        "success", "failed", "failed-missing-result", "scope_violation",
        "artifact-capture-failed", "artifact-capture-incomplete", "read-material-changed",
        "expected-output-missing", "timeout",
    }
    assert receipts.FAILED_STATUSES == (
        set(receipts.FINISHED_STATUSES) - {"success"}) | {receipts.INTERRUPTED_STATUS}


def test_receipt_format_has_one_implementation():
    sys.path.insert(0, str(HERE))
    import receipts
    assert not hasattr(receipts, "_receipt") and not hasattr(receipts, "_clip_utf8")


def test_preserved_and_capture_failures_count_as_failures():
    root = _root()
    try:
        _fixture(root, "capture-failed", "codex", "artifact-capture-failed",
                 {"input": 1, "output": 1, "total": 2}, "capture prompt", 0)
        result = _run(root, "list")
        assert result.returncode == 0, result.stderr
        assert "failures=2" in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_running_is_counted_apart_not_as_failure():
    # A run's --timeout can be up to 7 days, so its age cannot tell a live run from a lost one.
    root = Path(tempfile.mkdtemp(prefix="receipts-stale-fixture-"))
    try:
        _fixture(root, "stale-running", "codex", "running",
                 {"input": None, "output": None, "total": None}, "stale prompt", 2)
        _fixture(root, "fresh-running", "codex", "running",
                 {"input": None, "output": None, "total": None}, "fresh prompt", 0)
        result = _run(root, "list")
        assert result.returncode == 0, result.stderr
        assert "total runs=2 tokens=0/0/0 (usage from 0 runs) failures=0 still marked running=2" \
            in result.stdout, result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_recent_failure_rate_is_information():
    root = _root()
    sys.path.insert(0, str(HERE))
    import doctor
    old_root = doctor.ROOT
    try:
        doctor.ROOT = str(root)
        # A run folder named before the window is not read: its broken metadata would warn.
        old_run = root / "_private" / "work" / "runs" / "20200101T000000+0000-codex-00000000"
        old_run.mkdir()
        (old_run / "meta.json").write_text("{", encoding="utf-8")
        read = []
        original = Path.read_text
        Path.read_text = lambda self, *a, **k: read.append(self.name) or original(self, *a, **k)
        try:
            status, detail = doctor.c_worker_receipts()
        finally:
            Path.read_text = original
        assert status == doctor.PASS, detail
        assert "prompt.md" not in read, read
        assert "runs=2" in detail and "tokens=150/30/180" in detail
        assert "failures=1 (50.0%)" in detail

        meta_path = root / "_private" / "work" / "runs" / "success-codex" / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["status"] = "failed"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        status, detail = doctor.c_worker_receipts()
        # A past failure rate is information: nothing the owner does now clears it.
        assert status == doctor.PASS and "failures=2 (100.0%)" in detail
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_english_output_has_no_hangul():
    root = _root()
    try:
        outputs = [_run(root, *args) for args in (("list",), ("show", "missing"))]
        text = "\n".join(run.stdout + run.stderr for run in outputs)
        assert "total runs=3 tokens=150/30/180 (usage from 2 runs) failures=1 still marked running=0" \
            in text, text
        assert "run not found: missing" in text, text
        assert not re.search("[가-힣]", text), text
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [test_list_table_and_totals, test_english_output_has_no_hangul,
         test_show_meta_summary_and_receipt,
         test_prompt_line_is_the_body_as_written,
         test_receipt_format_has_one_implementation,
         test_status_vocabulary_is_shared_by_worker_and_ledger,
         test_preserved_and_capture_failures_count_as_failures,
         test_running_is_counted_apart_not_as_failure,
         test_doctor_recent_failure_rate_is_information]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
