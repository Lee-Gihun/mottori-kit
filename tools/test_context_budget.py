#!/usr/bin/env python3
"""Fixture tests for the main-thread context byte budget CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
CONTEXT_BUDGET = HERE / "context_budget.py"


def _write_transcript(path, events):
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def _run(path, *args):
    return subprocess.run(
        [sys.executable, str(CONTEXT_BUDGET), str(path), *args],
        text=True,
        capture_output=True,
    )


def test_sources_utf8_top_tools_and_budget_warning():
    root = Path(tempfile.mkdtemp(prefix="context-budget-fixture-"))
    try:
        transcript = root / "session.jsonl"
        events = [
            {
                "type": "attachment",
                "isSidechain": False,
                "attachment": {
                    "type": "hook_additional_context",
                    "hookEvent": "SessionStart",
                    "content": ["한글"],
                },
            },
            {"type": "user", "isSidechain": False,
             "message": {"role": "user", "content": "abc"}},
            {"type": "system", "subtype": "compact_boundary", "isSidechain": False,
             "content": "요약"},
            {"type": "assistant", "isSidechain": False, "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "모델"},
                    {"type": "tool_use", "id": "small", "name": "Read", "input": {}},
                    {"type": "tool_use", "id": "receipt", "name": "Bash", "input": {}},
                ],
            }},
            {"type": "user", "isSidechain": False, "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "small", "content": "12345"}],
            }},
            {"type": "user", "isSidechain": False, "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "receipt",
                             "content": "FRESH_WORKER v1\nx"}],
            }},
            {"type": "user", "isSidechain": True,
             "message": {"role": "user", "content": "not-main"}},
        ]
        _write_transcript(transcript, events)

        result = _run(transcript, "--budget", "44")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "hook_injection bytes=6 items=1" in result.stdout
        assert "worker_receipt bytes=17 items=1" in result.stdout
        assert "tool_stdout bytes=5 items=1" in result.stdout
        assert "user bytes=3 items=1" in result.stdout
        assert "model bytes=16 items=4" in result.stdout
        assert "total bytes=47" in result.stdout
        top = [line for line in result.stdout.splitlines() if line.startswith(("1. ", "2. "))]
        assert "bytes=17 tool=Bash id=receipt" in top[0]
        assert "bytes=5 tool=Read id=small" in top[1]
        assert "budget WARN total=47 budget=44 over=3" in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_only_largest_twenty_tool_calls_are_shown():
    root = Path(tempfile.mkdtemp(prefix="context-budget-top20-"))
    try:
        transcript = root / "session.jsonl"
        uses = [
            {"type": "tool_use", "id": f"t{i:02d}", "name": "Bash", "input": {}}
            for i in range(22)
        ]
        results = [
            {"type": "tool_result", "tool_use_id": f"t{i:02d}", "content": "x" * (i + 1)}
            for i in range(22)
        ]
        _write_transcript(transcript, [
            {"type": "assistant", "message": {"role": "assistant", "content": uses}},
            {"type": "user", "message": {"role": "user", "content": results}},
        ])

        result = _run(transcript)
        assert result.returncode == 0, result.stdout + result.stderr
        rows = [line for line in result.stdout.splitlines()
                if line[:1].isdigit() and ". bytes=" in line]
        assert len(rows) == 20
        assert rows[0].startswith("1. bytes=22 tool=Bash id=t21")
        assert rows[-1].startswith("20. bytes=3 tool=Bash id=t02")
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [test_sources_utf8_top_tools_and_budget_warning,
         test_only_largest_twenty_tool_calls_are_shown]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
