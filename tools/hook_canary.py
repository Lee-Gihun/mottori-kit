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
import i18n  # noqa: E402
import claude_auth  # noqa: E402

PROMPT = ("Do not use tools. If startup context contains a line beginning HOOK_CANARY:, "
          "respond with only the value after that prefix. Otherwise respond only ABSENT.")


CODEX_EXTERNAL_FEATURES = (
    "apps", "browser_use", "browser_use_external", "computer_use", "goals",
    "image_generation", "in_app_browser", "memories", "multi_agent", "plugins",
    "recommended_plugins", "remote_plugin", "skill_mcp_dependency_install",
    "skill_search", "tool_suggest", "workspace_dependencies",
)
CLAUDE_SESSION_SETTINGS = {
    "disableClaudeAiConnectors": True,
    "syncClaudeAiPlugins": False,
    "syncClaudeAiSkills": False,
}
CLAUDE_BUILTIN_PLUGINS = frozenset({
    "cc-plugin-agents-md", "cc-plugin-telemetry", "cc-plugin-plugin-authoring",
})


def _runtime_env(token):
    """Bind the measured instance and discard inherited runtime injection paths."""
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith("GIT_") and key not in {"GIT_TERMINAL_PROMPT"}:
            env.pop(key)
    for key in (
        "CLAUDE_CODE_PLUGIN_DIRS", "CLAUDE_CODE_PLUGIN_SEED_DIR",
        "CLAUDE_CODE_SYNC_PLUGINS", "CLAUDE_CODE_SYNC_SESSION_REFS",
        "CLAUDE_CODE_SYNC_PLUGIN_INSTALL", "CLAUDE_CODE_SYNC_SKILLS",
        "CLAUDE_CODE_SAFE_MODE", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_RESTRICTED",
    ):
        env.pop(key, None)
    root = os.path.realpath(ROOT)
    env.update(MOTTORI_INSTANCE=root, CLAUDE_PROJECT_DIR=root,
               MOTTORI_HOOK_CANARY=token)
    return env


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
        raise FileNotFoundError(i18n.t("hookdiag.codex_missing"))
    cmd = [codex, "exec", "--ignore-user-config", "--ephemeral", "--json",
           "-C", ROOT, "-s", "read-only", "--config", 'web_search="disabled"',
           "--config", "mcp_servers={}", "--config", "agents.enabled=false"]
    for feature in CODEX_EXTERNAL_FEATURES:
        cmd += ["--disable", feature]
    if not hooks_enabled:
        cmd += ["--disable", "hooks"]
    cmd.append(PROMPT)
    env = {key: value for key, value in _runtime_env(token).items()
           if not key.upper().startswith(("CLAUDE_", "ANTHROPIC_"))}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, timeout=180)


def _codex_canary(token):
    live = hookdiag.codex_hooks_list(ROOT)
    report = hookdiag.codex_runtime_report(live.get("hooks", []))
    injector = report["injector"]
    if not injector["declared"] or not injector["armed"]:
        print(i18n.t("hook_canary.not_armed", injector=injector), file=sys.stderr)
        return False

    positive = _run(token, True)
    if positive.returncode:
        print(i18n.t("hook_canary.process_failed", kind="positive",
                     error=positive.stderr[-1000:]), file=sys.stderr)
        return False
    pos_messages, pos_tools = agent_messages(positive.stdout)

    negative = _run(token, False)
    if negative.returncode:
        print(i18n.t("hook_canary.process_failed", kind="negative",
                     error=negative.stderr[-1000:]), file=sys.stderr)
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
        raise FileNotFoundError(i18n.t("doctor.claude_missing"))
    cmd = [claude, "-p", "--no-session-persistence", "--tools", "", "--model", "fable",
           "--effort", "high", "--permission-mode", "dontAsk", "--setting-sources", "project",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--disable-slash-commands", "--no-chrome", "--settings",
           json.dumps(CLAUDE_SESSION_SETTINGS, separators=(",", ":")),
           "--output-format", "stream-json", "--verbose"]
    if not hooks_enabled:
        cmd.append("--safe-mode")
    cmd.append(PROMPT)
    env = claude_auth.env(_runtime_env(token))
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT, timeout=180)


def _builtin_plugins_only(plugins):
    """Accept known bundled metadata, never configured paths or unknown plugins."""
    if not isinstance(plugins, list):
        return False
    names = []
    for plugin in plugins:
        if not isinstance(plugin, dict):
            return False
        name = plugin.get("name")
        if (not isinstance(name, str) or name not in CLAUDE_BUILTIN_PLUGINS
                or plugin.get("path") != "builtin"
                or plugin.get("source") != name + "@builtin"):
            return False
        names.append(name)
    return len(names) == len(set(names))


def claude_messages(stream):
    """Require a tool-free startup and a successful result from the actual event stream."""
    results, tools, initialized, isolation = [], 0, 0, True
    for raw in stream.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            initialized += 1
            isolation = (isolation and event.get("tools") == []
                         and event.get("mcp_servers") == []
                         and _builtin_plugins_only(event.get("plugins")))
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            tools += sum(item.get("type") in {"tool_use", "server_tool_use"}
                         for item in content if isinstance(item, dict))
        if event.get("type") == "result":
            results.append(event.get("result") if event.get("is_error") is False else None)
    result = results[0] if len(results) == 1 and isinstance(results[0], str) else None
    return result, tools, initialized == 1 and isolation


def _claude_canary(token):
    positive = _run_claude(token, True)
    negative = _run_claude(token, False)
    pos, pos_tools, pos_isolated = claude_messages(positive.stdout)
    neg, neg_tools, neg_isolated = claude_messages(negative.stdout)
    ok = (positive.returncode == 0 and negative.returncode == 0
          and pos == token and neg == "ABSENT" and pos_tools == neg_tools == 0
          and pos_isolated and neg_isolated)
    print("Claude SessionStart canary")
    print(f"  positive exact nonce: {'PASS' if pos == token else 'FAIL'}")
    print(f"  safe-mode negative: {'PASS' if neg == 'ABSENT' else 'FAIL'}")
    print(f"  no tools/MCP/configured plugins: positive={pos_isolated} negative={neg_isolated}")
    print(f"  model tool calls: positive={pos_tools} negative={neg_tools}")
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
            print(i18n.t("hook_canary.runtime_failed", runtime=name,
                         error_type=type(e).__name__, error=e), file=sys.stderr)
    try:
        _persist_results(results)
    except Exception as e:
        print(i18n.t("hook_canary.persist_failed", error_type=type(e).__name__, error=e),
              file=sys.stderr)
        return 1
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
