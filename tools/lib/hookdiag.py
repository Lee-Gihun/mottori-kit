#!/usr/bin/env python3
"""Read the three runtimes' hook declarations and report how far each of the kit's events is known to work.

A hook can be declared, have a valid command, be armed (the runtime agrees to run it), fire, and
reach the model. Each report says only what its source shows and leaves the rest "unknown": the
declaration file shows the first two, Codex's hooks/list and Antigravity's listing show arming.
doctor, hook_canary, options and context_budget read declarations through this module; at session
start the dispatcher calls clear_stale_verdict and then unarmed_notice.
"""
import json
import os
import sys
import re
import selectors
import shutil
import subprocess
import tempfile
import time
import urllib.parse

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P  # noqa: E402
import safeio  # noqa: E402


# Messages this module prints in more than one place, or too long to read inline.
AGY_UNUSED = (
    "agy has not been run by this user; doctor does not start it, because its first run opens "
    "a sign-in page"
)
EXITED = "codex app-server exited before answering (exit {code}): {stderr}"
UNARMED_NOTICE = (
    "Hooks of {runtimes} do not run in this folder yet (doctor, {at}); `python3 "
    "tools/doctor.py` names the one-time step."
)


# Each runtime's declaration file, relative to the instance root.
HOOK_FILES = {"claude": (".claude", "settings.json"), "codex": (".codex", "hooks.json"),
              "agy": (".agents", "hooks.json")}

# The events the kit declares in each runtime, in that runtime's spelling. Codex's hooks/list
# spells them with a lower-case first letter. Antigravity's per-prompt event is the first model
# call of a prompt, and it has no compaction event.
KIT_EVENTS = {
    "claude": ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "PreCompact"),
    "agy": ("SessionStart", "PreInvocation", "PostToolUse", "Stop"),
}
KIT_EVENTS["codex"] = KIT_EVENTS["claude"]

# Codex's tool names, against which a matcher is tried; a matcher that matches none of them can
# never fire in Codex. Claude Code's names, such as Glob and Grep, are not among them.
CODEX_TOOL_INVENTORY = (
    "exec_command", "write_stdin", "apply_patch", "update_plan", "view_image",
    "web__run", "mcp__node_repl__js", "request_user_input", "spawn_agent",
    "send_message", "wait_agent", "list_mcp_resources", "read_mcp_resource",
)


def read(runtime, root):
    """Return the parsed declaration file of a runtime in root, or None when there is none.

    A file that is not JSON raises ValueError."""
    try:
        with open(os.path.join(root, *HOOK_FILES[runtime]), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def declared(runtime, config):
    """Return {event: [{"command", "matcher", "timeout"}]} from a runtime's declaration file.

    Claude Code and Codex keep the events under "hooks", each a list of groups of a matcher and
    handlers. Antigravity keeps named hooks at the top level; there a lifecycle event is a flat
    list of handlers and a tool event is a list of groups, and a hook name switched off is not
    run. Another shape raises AttributeError or TypeError."""
    tables = ([t for t in config.values() if t.get("enabled", True) is not False]
              if runtime == "agy" else [config.get("hooks", {})])
    out = {}
    for table in tables:
        for event, entries in table.items():
            if event == "enabled":
                continue
            for entry in entries:
                group = entry["hooks"] if "hooks" in entry else [entry]
                for handler in group:
                    out.setdefault(event, []).append({"command": handler.get("command", ""),
                                                      "matcher": entry.get("matcher"),
                                                      "timeout": handler.get("timeout")})
    return out


def static_report(runtime, config):
    """Return {event: row} for the kit's events from a declaration file; arming and later stay unknown."""
    report, hooks = {}, declared(runtime, config)
    for event in KIT_EVENTS[runtime]:
        handlers = hooks.get(event, [])
        commands = [x["command"] for x in handlers]
        report[event] = {
            "declared": bool(handlers),
            "command_valid": bool(commands) and all(isinstance(x, str) and x.strip() for x in commands),
            "armed": "unknown",
            "fired": "unknown",
            "effect": "unknown",
            "matchers": [x["matcher"] for x in handlers],
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
    """Return {event: row} for the kit's Codex events from the project hooks hooks/list reported."""
    report = {}
    project = [h for h in hooks if h.get("source") == "project"]
    for event in KIT_EVENTS["codex"]:
        names = (event, event[0].lower() + event[1:])
        event_hooks = [h for h in project if h.get("eventName") in names]
        trusts = [h.get("trustStatus", "unknown") for h in event_hooks]
        armed = (all(h.get("enabled") and h.get("trustStatus") in ("trusted", "managed")
                     for h in event_hooks) if event_hooks else False)
        matchers = [h.get("matcher") for h in event_hooks]
        report[event] = {
            "declared": bool(event_hooks),
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
    proc.stdin.write((json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8"))
    proc.stdin.flush()


def _receive_id(proc, wanted, timeout, buf):
    """Return the message with this id. Raise EOFError when the server closed its output or
    exited first, and TimeoutError when it is still running at the deadline."""
    # Read raw bytes into a caller-owned buffer: a buffered readline can strand later lines where
    # select() no longer sees them, and leftovers must survive into the next call.
    fd = proc.stdout.fileno()
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while True:
            while b"\n" in buf:
                line, _, rest = bytes(buf).partition(b"\n")
                buf[:] = rest
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue  # banners and log lines are not protocol messages
                if isinstance(msg, dict) and msg.get("id") == wanted:
                    return msg
            if time.monotonic() >= deadline:
                break
            events = selector.select(min(0.25, max(0, deadline - time.monotonic())))
            if not events:
                if proc.poll() is not None:
                    raise EOFError
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                raise EOFError
            buf.extend(chunk)
    finally:
        selector.close()
    raise TimeoutError(f"codex app-server response timeout: id={wanted}")


def codex_hooks_list(cwd, codex_bin=None, timeout=5.0):
    """Ask Codex's official hooks/list API for trustStatus/currentHash.

    This proves declared/armed state only. It does not claim dispatcher firing or model consumption.
    """
    binary = codex_bin or shutil.which("codex")
    if not binary:
        raise FileNotFoundError("codex CLI missing")
    # Stderr goes to a file, not a pipe nobody reads, so it can explain an early exit.
    errors = tempfile.TemporaryFile()
    proc = subprocess.Popen([binary, "app-server", "--stdio"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=errors, bufsize=0)
    buf = bytearray()
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "mottori-doctor", "version": "1"},
            "capabilities": {"experimentalApi": True},
        }})
        init = _receive_id(proc, 1, timeout, buf)
        if "error" in init:
            raise RuntimeError("codex initialize failed: {error}".format(error=init["error"]))
        _send(proc, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "hooks/list",
                     "params": {"cwds": [os.path.abspath(cwd)]}})
        response = _receive_id(proc, 2, timeout, buf)
        if "error" in response:
            raise RuntimeError("hooks/list failed: {error}".format(error=response["error"]))
        result = response.get("result")
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise RuntimeError("hooks/list returned empty data")
        return data[0]
    except EOFError:
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        errors.seek(0)
        tail = errors.read().decode("utf-8", "replace").strip()[-400:]
        raise RuntimeError(EXITED.format(code=proc.poll(), stderr=tail or "-")) from None
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
            proc.wait()
        errors.close()


# Antigravity keeps the folders the user trusted in an interactive session here
# (system/dev/runtime-capture.md); only that key is read.
AGY_SETTINGS = "~/.gemini/antigravity-cli/settings.json"


def agy_hooks_list(cwd, agy_bin=None, timeout=20, settings=AGY_SETTINGS):
    """Return the hooks Antigravity loads in cwd, from its /hooks listing in print mode.

    The listing runs no model turn and fires no hook, but print mode skips folder trust, so a
    listed hook is loaded, not armed; agy_trusted answers the other half.

    Without a login Antigravity opens a browser to sign in, print mode included. Its data folder
    is the sign that this user has run it, so without that folder the program is not started.
    The folder does not prove a login: after a sign-out the listing can still open that page."""
    binary = agy_bin or shutil.which("agy")
    if not binary:
        raise FileNotFoundError("agy CLI missing")
    if not os.path.isdir(os.path.dirname(os.path.expanduser(settings))):
        raise FileNotFoundError(AGY_UNUSED)
    proc = subprocess.run([binary, "-p", "/hooks", "--output-format", "json"], cwd=cwd,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=timeout)
    try:
        hooks = json.loads(proc.stdout)["command"]["data"]["hooks"]
    except (ValueError, KeyError, TypeError):
        hooks = None
    if proc.returncode or not isinstance(hooks, list):
        raise RuntimeError(EXITED.format(code=proc.returncode, stderr=proc.stderr.strip()[-400:] or "-"))
    return [h for h in hooks if isinstance(h, dict)]


def agy_trusted(root, settings=AGY_SETTINGS):
    """Whether the user trusted root or a folder above it. Trust is taken to cover subfolders,
    as the binary's function names suggest; that part is not measured."""
    try:
        with open(os.path.expanduser(settings), encoding="utf-8") as f:
            entries = json.load(f).get("trustedWorkspaces")
    except (OSError, ValueError, AttributeError):
        return False
    root = os.path.realpath(root)
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, str) and entry:
            path = urllib.parse.unquote(entry[7:]) if entry.startswith("file://") else entry
            path = os.path.realpath(os.path.expanduser(path))
            if root == path or root.startswith(path.rstrip(os.sep) + os.sep):
                return True
    return False


def agy_runtime_report(hooks, root, trusted):
    """Return {event: row} for the kit's Antigravity events from its hook listing: an event is
    declared when an enabled hook from this checkout's .agents/hooks.json acts on it, and armed
    when the folder is also trusted."""
    own = os.path.realpath(os.path.join(root, ".agents", "hooks.json"))
    events = {a.get("event") for h in hooks if h.get("enabled", True) is not False
              and isinstance(h.get("source"), str) and os.path.realpath(h["source"]) == own
              for a in h.get("actions") or () if isinstance(a, dict) and a.get("command")}
    report = {}
    for event in KIT_EVENTS["agy"]:
        listed = event in events
        report[event] = {"declared": listed, "command_valid": listed,
                         "armed": listed and trusted, "fired": "unknown", "effect": "unknown"}
    return report


def _verdicts(root):
    """doctor's saved verdicts as {runtime: {"armed", "at"}}, or {} when there are none to read."""
    try:
        with open(P.runtime_arming(root), encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return {}
    return rows if isinstance(rows, dict) else {}


def save_arming(root, runtime, armed):
    """Record doctor's verdict for one runtime: True, False, or None when it is not installed."""
    rows = _verdicts(root)
    rows[runtime] = {"armed": armed, "at": time.strftime("%Y-%m-%d")}
    try:
        safeio.atomic_write(P.runtime_arming(root), json.dumps(rows))
    except OSError:
        pass


def clear_stale_verdict(root, runtime):
    """Record runtime as armed when doctor last found it unarmed: a session of it is starting, so its
    hooks run, and the old verdict would keep naming it to the other runtimes."""
    row = _verdicts(root).get(runtime)
    if isinstance(row, dict) and row.get("armed") is False:
        save_arming(root, runtime, True)


def unarmed_notice(root, runtime):
    """One line naming the other installed runtimes doctor last found unarmed, or "". It only reads
    doctor's saved verdicts, and runs no probe."""
    rows = _verdicts(root)
    names = sorted(k for k, v in rows.items()
                   if k != runtime and isinstance(v, dict) and v.get("armed") is False)
    if not names:
        return ""
    return UNARMED_NOTICE.format(runtimes=", ".join(names), at=max(str(rows[k].get("at", "?")) for k in names))
