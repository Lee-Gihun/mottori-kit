#!/usr/bin/env python3
"""Truthful hook capability inspection.

Configuration, command validity, trust/arming, dispatcher firing, and model effect are different
claims.  This module never promotes an earlier stage into a later one.
"""
import json
import os
import re
import selectors
import shutil
import subprocess
import time


ROLE_EVENTS = {
    "injector": ("SessionStart", "sessionStart"),
    "side_effect": ("PreCompact", "preCompact"),
    "guard": ("PreToolUse", "preToolUse"),
    "observer": ("PostToolUse", "postToolUse"),
    "enforcer": ("Stop", "stop"),
    "recovery": ("UserPromptSubmit", "userPromptSubmit"),
}

# Codex tool identifiers are snake_case/MCP-qualified. Claude's Glob and Grep identifiers are not
# reachable in Codex. This inventory is deliberately conservative; unknown matchers report unknown,
# while a regex with zero hits reports unreachable rather than pretending it fired.
CODEX_TOOL_INVENTORY = (
    "exec_command", "write_stdin", "apply_patch", "update_plan", "view_image",
    "web__run", "mcp__node_repl__js", "request_user_input", "spawn_agent",
    "send_message", "wait_agent", "list_mcp_resources", "read_mcp_resource",
)


def _commands(config, event):
    out = []
    for block in config.get("hooks", {}).get(event, []):
        matcher = block.get("matcher")
        for handler in block.get("hooks", []):
            out.append({"command": handler.get("command", ""), "matcher": matcher})
    return out


def static_report(runtime, config):
    """Inspect repo JSON only. Later stages remain explicitly unknown."""
    report = {}
    for role, names in ROLE_EVENTS.items():
        event = names[0]
        handlers = _commands(config, event)
        commands = [x["command"] for x in handlers]
        report[role] = {
            "event": event,
            "declared": bool(handlers),
            "command_valid": bool(commands) and all(isinstance(x, str) and x.strip() for x in commands),
            "armed": "unknown",
            "fired": "unknown",
            "effect": "unknown",
            "matchers": [x["matcher"] for x in handlers],
            "runtime": runtime,
        }
    return report


def matcher_reachable(matcher, tools=CODEX_TOOL_INVENTORY):
    if not matcher:
        return True
    try:
        return any(re.search(matcher, name) for name in tools)
    except re.error:
        return False


def codex_runtime_report(hooks):
    """Convert official hooks/list metadata into the capability ladder."""
    report = {}
    project = [h for h in hooks if h.get("source") == "project"]
    for role, names in ROLE_EVENTS.items():
        event_hooks = [h for h in project if h.get("eventName") in names]
        declared = bool(event_hooks)
        trusts = [h.get("trustStatus", "unknown") for h in event_hooks]
        armed = (all(h.get("enabled") and h.get("trustStatus") in ("trusted", "managed")
                     for h in event_hooks) if event_hooks else False)
        matchers = [h.get("matcher") for h in event_hooks]
        report[role] = {
            "event": names[1],
            "declared": declared,
            "command_valid": bool(event_hooks) and all(bool(h.get("command")) for h in event_hooks),
            "armed": armed,
            "trust": ",".join(trusts) if trusts else "absent",
            "current_hashes": [h.get("currentHash") for h in event_hooks],
            "matcher_reachable": (all(matcher_reachable(x) for x in matchers)
                                  if event_hooks else False),
            "fired": "unknown",
            "effect": "unknown",
        }
    return report


def _send(proc, value):
    proc.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def _receive_id(proc, wanted, timeout):
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            events = selector.select(min(0.25, max(0, deadline - time.monotonic())))
            if not events:
                if proc.poll() is not None:
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                break
            msg = json.loads(line)
            if msg.get("id") == wanted:
                return msg
    finally:
        selector.close()
    raise TimeoutError(f"codex app-server response timeout: id={wanted}")


def codex_hooks_list(cwd, codex_bin=None, timeout=5.0):
    """Ask Codex's official hooks/list API for trustStatus/currentHash.

    This proves declared/armed state only. It does not claim dispatcher firing or model consumption.
    """
    binary = codex_bin or shutil.which("codex")
    if not binary:
        raise FileNotFoundError("codex CLI 없음")
    proc = subprocess.Popen([binary, "app-server", "--stdio"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "mottori-doctor", "version": "1"},
            "capabilities": {"experimentalApi": True},
        }})
        init = _receive_id(proc, 1, timeout)
        if "error" in init:
            raise RuntimeError(f"codex initialize 실패: {init['error']}")
        _send(proc, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "hooks/list",
                     "params": {"cwds": [os.path.abspath(cwd)]}})
        response = _receive_id(proc, 2, timeout)
        if "error" in response:
            raise RuntimeError(f"hooks/list 실패: {response['error']}")
        data = response.get("result", {}).get("data", [])
        if not data:
            raise RuntimeError("hooks/list가 빈 data를 반환")
        return data[0]
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()


def compact_summary(report):
    labels = {
        "injector": "주입", "side_effect": "컴팩션 기록", "guard": "사전 가드",
        "observer": "변경 관측", "enforcer": "Stop 차단", "recovery": "복구",
    }
    parts = []
    for role in ROLE_EVENTS:
        row = report[role]
        declared = "yes" if row["declared"] else "no"
        command = "valid" if row.get("command_valid") else "invalid"
        armed = row.get("armed", "unknown")
        extra = ""
        if row.get("declared") and row.get("matcher_reachable") is False:
            extra = "/matcher-unreachable"
        parts.append(f"{labels[role]}={declared}/{command}/{armed}{extra}")
    return " · ".join(parts) + " · fired/effect=unknown"
