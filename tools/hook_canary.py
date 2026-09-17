#!/usr/bin/env python3
"""Opt-in SessionStart E2E for Codex and Claude: fresh positive plus hooks-disabled negative.

The nonce exists only in the child process environment and hook output. It is never placed in the
prompt, repository, or persistent session. Routine doctor must not invoke this model-backed test.

Usage: `python3 tools/hook_canary.py` (Codex), `--claude`, or `--all`.
"""
import datetime
import json
import os
import secrets
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULT_PATH = os.path.join(ROOT, "state", "hook-canary.json")
sys.path.insert(0, HERE)
import hookdiag  # noqa: E402

PROMPT = ("Do not use tools. If startup context contains a line beginning HOOK_CANARY:, "
          "respond with only the value after that prefix. Otherwise respond only ABSENT.")


def agent_messages(stream):
    """Extract model messages only; hook/tool payloads must never satisfy the canary."""
    messages, tool_count = [], 0
    for raw in stream.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item", {})
        kind = item.get("type")
        if kind == "agent_message":
            messages.append(item.get("text", ""))
        elif kind not in ("reasoning",):
            tool_count += 1
    return messages, tool_count


def _run(token, hooks_enabled):
    codex = shutil.which("codex")
    if not codex:
        raise FileNotFoundError("codex CLI 없음")
    cmd = [codex, "exec", "--ephemeral", "--json", "-C", ROOT, "-s", "read-only"]
    if not hooks_enabled:
        cmd += ["--disable", "hooks"]
    cmd.append(PROMPT)
    env = dict(os.environ, MOTTORI_HOOK_CANARY=token)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, timeout=180)


def _codex_canary(token):
    live = hookdiag.codex_hooks_list(ROOT)
    report = hookdiag.codex_runtime_report(live.get("hooks", []))
    injector = report["injector"]
    if not injector["declared"] or not injector["armed"]:
        print(f"canary 중단: SessionStart armed가 아님 ({injector})", file=sys.stderr)
        return False

    positive = _run(token, True)
    if positive.returncode:
        print(f"positive process 실패: {positive.stderr[-1000:]}", file=sys.stderr)
        return False
    pos_messages, pos_tools = agent_messages(positive.stdout)

    negative = _run(token, False)
    if negative.returncode:
        print(f"negative process 실패: {negative.stderr[-1000:]}", file=sys.stderr)
        return False
    neg_messages, neg_tools = agent_messages(negative.stdout)

    pos = pos_messages[-1].strip() if pos_messages else ""
    neg = neg_messages[-1].strip() if neg_messages else ""
    ok = pos == token and neg == "ABSENT" and pos_tools == 0 and neg_tools == 0
    print("SessionStart canary")
    print(f"  positive exact nonce: {'PASS' if pos == token else 'FAIL'}")
    print(f"  hooks-disabled negative: {'PASS' if neg == 'ABSENT' else 'FAIL'}")
    print(f"  model tool calls: positive={pos_tools} negative={neg_tools}")
    print("  dispatcher_fired/effect: " + ("verified" if ok else "not verified"))
    return ok


def _run_claude(token, hooks_enabled):
    claude = shutil.which("claude")
    if not claude:
        raise FileNotFoundError("claude CLI 없음")
    cmd = [claude, "-p", "--no-session-persistence", "--tools", "", "--model", "fable",
           "--effort", "high"]
    if not hooks_enabled:
        cmd.append("--safe-mode")
    cmd.append(PROMPT)
    env = dict(os.environ, MOTTORI_HOOK_CANARY=token)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, timeout=180)


def _claude_canary(token):
    positive = _run_claude(token, True)
    negative = _run_claude(token, False)
    pos, neg = positive.stdout.strip(), negative.stdout.strip()
    ok = (positive.returncode == 0 and negative.returncode == 0
          and pos == token and neg == "ABSENT")
    print("Claude SessionStart canary")
    print(f"  positive exact nonce: {'PASS' if pos == token else 'FAIL'}")
    print(f"  safe-mode negative: {'PASS' if neg == 'ABSENT' else 'FAIL'}")
    print("  tools: disabled by CLI")
    print("  dispatcher_fired/effect: " + ("verified" if ok else "not verified"))
    if not ok:
        print((positive.stderr + negative.stderr)[-1000:], file=sys.stderr)
    return ok


def _persist_results(rows, path=None):
    """Persist only verdicts and timestamps. The secret nonce must never reach disk."""
    path = path or RESULT_PATH
    try:
        payload = json.load(open(path, encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("runtimes"), dict):
            payload = {"schema_version": 1, "runtimes": {}}
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        payload = {"schema_version": 1, "runtimes": {}}

    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for runtime, ok in rows.items():
        verdict = "verified" if ok else "not_verified"
        payload["runtimes"][runtime] = {
            "checked_at": checked_at,
            "status": "PASS" if ok else "FAIL",
            "dispatcher_fired": verdict,
            "effect": verdict,
        }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp-{os.getpid()}"
    try:
        with open(temporary, "w", encoding="utf-8") as result_file:
            json.dump(payload, result_file, ensure_ascii=False, indent=2)
            result_file.write("\n")
            result_file.flush()
            os.fsync(result_file.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main():
    runtime = "codex"
    if "--all" in sys.argv:
        runtime = "all"
    elif "--claude" in sys.argv:
        runtime = "claude"
    token = secrets.token_hex(32)
    results = {}
    for name, function in (("codex", _codex_canary), ("claude", _claude_canary)):
        if runtime not in (name, "all"):
            continue
        try:
            results[name] = bool(function(token))
        except Exception as e:
            results[name] = False
            print(f"{name} canary 실패: {type(e).__name__}: {e}", file=sys.stderr)
    try:
        _persist_results(results)
    except Exception as e:
        print(f"canary 결과 저장 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
