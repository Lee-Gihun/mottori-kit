#!/usr/bin/env python3
"""hookdiag.py static capability and matcher regressions."""
import os
import sys

from testlib import run_test


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hookdiag  # noqa: E402


def test_static_report_maps_events_to_distinct_roles():
    config = {"hooks": {
        "SessionStart": [{"hooks": [{"command": "inject"}]}],
        "PreCompact": [{"hooks": [{"command": "record"}]}],
        "PreToolUse": [{"matcher": "exec_command", "hooks": [{"command": "guard"}]}],
        "PostToolUse": [{"hooks": [{"command": "observe"}]}],
        "Stop": [{"hooks": [{"command": "enforce"}]}],
        "UserPromptSubmit": [{"hooks": [{"command": "recover"}]}],
    }}
    report = hookdiag.static_report("codex", config)
    assert set(report) == set(hookdiag.ROLE_EVENTS)
    assert all(report[role]["declared"] for role in hookdiag.ROLE_EVENTS)
    assert report["injector"]["event"] == "SessionStart"
    assert report["observer"]["event"] == "PostToolUse"
    assert report["enforcer"]["event"] == "Stop"
    assert report["guard"]["matchers"] == ["exec_command"]
    assert all(report[role]["armed"] == "unknown" for role in report)


def test_static_report_rejects_empty_commands():
    config = {"hooks": {
        "SessionStart": [{"hooks": [{"command": "ok"}, {"command": "  "}]}],
    }}
    report = hookdiag.static_report("claude", config)
    assert report["injector"]["declared"] is True
    assert report["injector"]["command_valid"] is False
    assert report["side_effect"]["declared"] is False


def test_matcher_reachable_handles_hits_misses_and_invalid_regex():
    assert hookdiag.matcher_reachable(None) is True
    assert hookdiag.matcher_reachable("exec_command|apply_patch") is True
    assert hookdiag.matcher_reachable("Glob|Grep") is False
    assert hookdiag.matcher_reachable("[") is False


TESTS = [
    test_static_report_maps_events_to_distinct_roles,
    test_static_report_rejects_empty_commands,
    test_matcher_reachable_handles_hits_misses_and_invalid_regex,
]


def main():
    failed = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"hookdiag: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
