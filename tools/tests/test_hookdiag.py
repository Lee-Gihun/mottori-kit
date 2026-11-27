#!/usr/bin/env python3
"""hookdiag.py static capability and matcher regressions."""
import os
import shutil
import sys
import tempfile


TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import hookdiag  # noqa: E402


def test_static_report_keys_each_kit_event():
    config = {"hooks": {
        "SessionStart": [{"hooks": [{"command": "inject"}]}],
        "PreCompact": [{"hooks": [{"command": "record"}]}],
        "PreToolUse": [{"matcher": "exec_command", "hooks": [{"command": "owner's own"}]}],
        "PostToolUse": [{"matcher": "^apply_patch$", "hooks": [{"command": "observe"}]}],
        "Stop": [{"hooks": [{"command": "enforce"}]}],
        "UserPromptSubmit": [{"hooks": [{"command": "recover"}]}],
    }}
    report = hookdiag.static_report("codex", config)
    # Only the kit's events are reported; an event the kit does not declare is the owner's.
    assert list(report) == list(hookdiag.KIT_EVENTS["codex"]), report
    assert all(report[event]["declared"] for event in report)
    assert report["PostToolUse"]["matchers"] == ["^apply_patch$"]
    assert all(report[event]["armed"] == "unknown" for event in report)
    # Antigravity: named hooks at the top level, flat lists for lifecycle events, groups for tool
    # events; a name switched off is not read, and there is no compaction event.
    flat = [{"type": "command", "command": "run"}]
    agy = {"kit": {"enabled": True, "SessionStart": flat, "PreInvocation": flat, "Stop": flat,
                   "PostToolUse": [{"matcher": "^edit_file$", "hooks": flat}]},
           "off": {"enabled": False, "PreToolUse": [{"hooks": flat}]}}
    report = hookdiag.static_report("agy", agy)
    assert list(report) == ["SessionStart", "PreInvocation", "PostToolUse", "Stop"], report
    assert all(row["declared"] for row in report.values()), report
    assert report["PostToolUse"]["matchers"] == ["^edit_file$"], report


def test_static_report_rejects_empty_commands():
    config = {"hooks": {
        "SessionStart": [{"hooks": [{"command": "ok"}, {"command": "  "}]}],
    }}
    report = hookdiag.static_report("claude", config)
    assert report["SessionStart"]["declared"] is True
    assert report["SessionStart"]["command_valid"] is False
    assert report["PreCompact"]["declared"] is False


def test_matcher_reachable_handles_hits_misses_and_invalid_regex():
    assert hookdiag.matcher_reachable(None) is True
    assert hookdiag.matcher_reachable("exec_command|apply_patch") is True
    assert hookdiag.matcher_reachable("Glob|Grep") is False
    assert hookdiag.matcher_reachable("[") is False


def test_codex_runtime_report_requires_trust():
    hooks = [{
        "eventName": "sessionStart", "source": "project", "enabled": True,
        "trustStatus": "untrusted", "currentHash": "sha256:a", "command": "inject",
    }, {
        "eventName": "postToolUse", "source": "project", "enabled": True,
        "trustStatus": "trusted", "currentHash": "sha256:b", "matcher": "Glob",
        "command": "observe",
    }]
    report = hookdiag.codex_runtime_report(hooks)
    assert report["SessionStart"]["armed"] is False
    assert report["SessionStart"]["trust"] == "untrusted"
    assert report["PostToolUse"]["matcher_reachable"] is False
    hooks[0]["trustStatus"] = "trusted"
    assert hookdiag.codex_runtime_report(hooks)["SessionStart"]["armed"] is True


# A fake app-server: answers initialize and hooks/list. PAIRED sends the notification and the
# response in one write; BANNER prints a non-JSON line before anything else; EXIT fails at once
# with a reason on stderr; NULL answers hooks/list with a null result.
_FAKE_SERVER = """import json, sys
MODE = %r
if MODE == "banner":
    sys.stdout.write("starting app-server\\n"); sys.stdout.flush()
if MODE == "exit":
    sys.stderr.write("unknown subcommand app-server\\n"); sys.exit(2)
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("id") == 1:
        out = json.dumps({"id": 1, "result": {}}) + "\\n"
        if MODE == "paired":
            out = json.dumps({"method": "note", "params": {}}) + "\\n" + out
        sys.stdout.write(out); sys.stdout.flush()
    elif msg.get("id") == 2:
        result = None if MODE == "null" else {"data": [{"hooks": ["h"]}]}
        sys.stdout.write(json.dumps({"id": 2, "result": result}) + "\\n")
        sys.stdout.flush()
"""


def test_codex_hooks_list_reads_paired_and_noisy_output():
    tmp = tempfile.mkdtemp(prefix="hookdiag-fake-")
    try:
        for mode in ("paired", "banner", "exit", "null"):
            fake = os.path.join(tmp, f"codex-{mode}")
            with open(fake, "w", encoding="utf-8") as f:
                f.write(f"#!{sys.executable}\n" + _FAKE_SERVER % mode)
            os.chmod(fake, 0o755)
            try:
                entry = hookdiag.codex_hooks_list(tmp, codex_bin=fake, timeout=2)
            except RuntimeError as error:
                entry = str(error)
            if mode == "exit":
                # An early exit is reported with its stderr, not as a timeout.
                assert "unknown subcommand" in entry, entry
            elif mode == "null":
                assert entry == "hooks/list returned empty data", entry
            else:
                assert entry == {"hooks": ["h"]}, (mode, entry)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_unarmed_notice_only_reads_and_a_starting_runtime_clears_its_own_verdict():
    root = tempfile.mkdtemp(prefix="hookdiag-arming-")
    try:
        os.makedirs(os.path.join(root, ".git"))
        path = hookdiag.P.runtime_arming(root)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"claude": {"armed": false, "at": "2026-11-01"}, "codex": {"armed": false, "at": "2026-11-02"}}')
        before = open(path, "rb").read()
        notice = hookdiag.unarmed_notice(root, "claude")
        assert "Hooks of codex do not run" in notice and "2026-11-02" in notice, notice
        # Measuring the session start text reads this notice, so reading it must write nothing.
        assert open(path, "rb").read() == before
        hookdiag.clear_stale_verdict(root, "claude")
        assert '"claude": {"armed": true' in open(path, encoding="utf-8").read()
        assert hookdiag.unarmed_notice(root, "codex") == ""
        assert "codex" in hookdiag.unarmed_notice(root, "claude")
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_static_report_keys_each_kit_event,
    test_static_report_rejects_empty_commands,
    test_matcher_reachable_handles_hits_misses_and_invalid_regex,
    test_codex_runtime_report_requires_trust,
    test_codex_hooks_list_reads_paired_and_noisy_output,
    test_the_unarmed_notice_only_reads_and_a_starting_runtime_clears_its_own_verdict,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"hookdiag: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
