#!/usr/bin/env python3
"""Run one bounded, non-resumable Claude or Codex worker.

The master session should receive a small receipt, not the worker's broad read/tool trace.
Every run is ephemeral at the native runtime and has a self-contained private record instead:

    python3 tools/fresh_worker.py --runtime claude PROMPT_FILE
    python3 tools/fresh_worker.py --runtime codex  PROMPT_FILE

Claude v1 is a read-only reviewer. Codex v1 may write inside the workspace sandbox. There is no
runtime fallback and no write-capable Claude mode. Design decision: KIT-DR-007.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M


ROOT = M.ROOT
RUN_ROOT = os.path.join(ROOT, "_private", "work", "runs")
RECEIPT_MAX_BYTES = 4096
WRAPPER_RESULT_MISSING = 3

CAPABILITIES = {
    "claude": "read-only",
    "codex": "workspace-write",
}

CODEX_DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "memories",
    "multi_agent",
    "plugins",
    "recommended_plugins",
    "remote_plugin",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_suggest",
    "workspace_dependencies",
)


class InputError(ValueError):
    pass


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except FileNotFoundError:
        return None
    return h.hexdigest()


def _private_write(path, data):
    """Write bytes atomically with a private mode."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp = os.path.join(os.path.dirname(path), ".tmp-" + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _inside_root(path):
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(ROOT))) == os.path.realpath(ROOT)
    except ValueError:
        return False


def _reject_symlink_components(path):
    """Reject a symlink in any component below ROOT, not only the final file."""
    # Walk the lexical workspace path so a symlink component remains observable. macOS maps /var to
    # /private/var; using a real root with a lexical source would falsely look outside the workspace.
    root = os.path.abspath(ROOT)
    absolute = os.path.abspath(path)
    try:
        rel = os.path.relpath(absolute, root)
    except ValueError:
        raise InputError("prompt path가 workspace 밖이다")
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        raise InputError("prompt path가 workspace 밖이다")
    current = root
    for part in rel.split(os.sep):
        current = os.path.join(current, part)
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise InputError("prompt path에 symlink component가 있다")
        except FileNotFoundError:
            raise InputError("prompt file이 없다")


def read_prompt(path):
    source = os.path.abspath(os.path.expanduser(path) if os.path.isabs(path)
                             else os.path.join(ROOT, path))
    if not _inside_root(source):
        raise InputError("prompt path가 workspace 밖이다")
    _reject_symlink_components(source)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except FileNotFoundError:
        raise InputError("prompt file이 없다")
    except OSError as e:
        raise InputError(f"prompt file을 안전하게 열 수 없다: {type(e).__name__}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise InputError("prompt가 regular file이 아니다")
        with os.fdopen(fd, "rb") as f:
            raw = f.read()
        fd = None
    finally:
        if fd is not None:
            os.close(fd)
    if not raw:
        raise InputError("prompt가 비어 있다")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError("prompt가 UTF-8 text가 아니다")
    return source, text


def _effective_prompt(runtime, body):
    capability = CAPABILITIES[runtime]
    common = (
        "[fresh bounded worker contract]\n"
        f"- runtime capability: {capability}\n"
        "- This is a fresh, non-resumable worker. Read AGENTS.md and the named disk sources.\n"
        "- Do not commit, push, send, pay, submit, or change state journals/NOW; the dispatcher owns state.\n"
        "- Put durable work in the exact artifact paths authorized by the request.\n"
        "- End with a concise result that lists evidence, changed artifact paths, tests, and remaining unknowns.\n\n"
    )
    if runtime == "claude":
        common += (
            "- You are a read-only reviewer. Write/Edit/Bash and external action tools are unavailable.\n"
            "- Report executable verification that the dispatcher should run; do not claim you ran it.\n\n"
        )
    return common + body


def _new_run(runtime):
    os.makedirs(RUN_ROOT, mode=0o700, exist_ok=True)
    os.chmod(RUN_ROOT, 0o700)
    now = datetime.datetime.now().astimezone()
    rid = f"{now:%Y%m%dT%H%M%S%z}-{runtime}-{uuid.uuid4().hex[:8]}"
    path = os.path.join(RUN_ROOT, rid)
    os.mkdir(path, 0o700)
    return rid, path, now


def _claude_command():
    binary = os.environ.get("MOTTORI_FRESH_WORKER_CLAUDE_BIN", "claude")
    return [
        binary,
        "-p",
        # Safe mode disables user/project plugins, hooks, skills, MCP servers, and browser control.
        # The prompt explicitly tells the reviewer to Read AGENTS.md; strict empty MCP closes managed
        # connector surfaces that `--tools` alone does not remove (live canary, 2026-08-29).
        "--safe-mode",
        "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--model", os.environ.get("MOTTORI_FRESH_WORKER_CLAUDE_MODEL", "fable"),
        "--effort", "high",
        "--permission-mode", "dontAsk",
        "--tools", "Read", "Glob", "Grep",
        "--no-session-persistence",
        "--no-chrome",
        "--output-format", "stream-json",
        "--verbose",
    ]


def _codex_command(result_path):
    binary = os.environ.get("MOTTORI_FRESH_WORKER_CODEX_BIN", "codex")
    command = [
        binary, "exec",
        # Ignore the desktop user's plugins, MCP servers, memories, and connector settings. The
        # project config currently enables live search, so override that layer too and explicitly
        # close command-network egress. Authentication still comes from CODEX_HOME.
        "--ignore-user-config",
        "--model", os.environ.get("MOTTORI_FRESH_WORKER_CODEX_MODEL", "gpt-5.6-sol"),
        "--config", 'model_reasoning_effort="high"',
        "--config", 'web_search="disabled"',
        "--config", "sandbox_workspace_write.network_access=false",
        "--config", "agents.enabled=false",
    ]
    for feature in CODEX_DISABLED_FEATURES:
        command.extend(("--disable", feature))
    command.extend([
        "--sandbox", "workspace-write",
        "--ephemeral",
        "--json",
        "--color", "never",
        "--output-last-message", result_path,
        "-",
    ])
    return command


def _claude_result(stream_path):
    result = None
    with open(stream_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result" and isinstance(event.get("result"), str):
                result = event["result"]
    return result


def _write_meta(path, meta):
    _private_write(path, json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _receipt(meta, result):
    fixed = (
        "FRESH_WORKER v1\n"
        f"run: {meta['run']}\n"
        f"runtime: {meta['runtime']}\n"
        f"capability: {meta['capability']}\n"
        f"status: {meta['status']}\n"
        f"process_exit: {meta['process_exit']}\n"
        f"wrapper_exit: {meta['wrapper_exit']}\n"
        f"prompt_sha256: {meta['prompt_sha256']}\n"
        f"stream_sha256: {meta['stream_sha256']}\n"
        f"result_sha256: {meta['result_sha256']}\n"
        f"result_bytes: {meta['result_bytes']}\n"
        "result:\n"
    )
    room = RECEIPT_MAX_BYTES - len(fixed.encode("utf-8"))
    if room < 128:
        raise AssertionError("receipt fixed fields exceed byte budget")
    body = result if result else "[final result unavailable; inspect the private run record]"
    receipt = fixed + M.clip_utf8(body, room)
    if len(receipt.encode("utf-8")) > RECEIPT_MAX_BYTES:
        raise AssertionError("receipt byte budget calculation failed")
    return receipt


def run(runtime, prompt_file):
    source, body = read_prompt(prompt_file)
    run_id, run_dir, started = _new_run(runtime)
    rel_run = os.path.relpath(run_dir, ROOT)
    prompt_path = os.path.join(run_dir, "prompt.md")
    stream_path = os.path.join(run_dir, "stream.jsonl")
    stderr_path = os.path.join(run_dir, "stderr.log")
    result_path = os.path.join(run_dir, "result.txt")
    meta_path = os.path.join(run_dir, "meta.json")
    effective = _effective_prompt(runtime, body)
    _private_write(prompt_path, effective)

    capability = CAPABILITIES[runtime]
    command = _claude_command() if runtime == "claude" else _codex_command(result_path)
    meta = {
        "schema_version": 1,
        "run": rel_run,
        "run_id": run_id,
        "runtime": runtime,
        "capability": capability,
        "source_prompt": os.path.relpath(source, ROOT),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": None,
        "process_exit": None,
        "wrapper_exit": None,
        "status": "running",
        "command": command,
        "prompt_sha256": _sha256(prompt_path),
        "stream_sha256": None,
        "stderr_sha256": None,
        "result_sha256": None,
        "result_bytes": 0,
    }
    _write_meta(meta_path, meta)

    t0 = time.monotonic()
    process_exit = None
    launch_error = None
    stream_fd = os.open(stream_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(stream_fd, "wb") as stream, os.fdopen(stderr_fd, "wb") as err:
            try:
                proc = subprocess.run(
                    command,
                    input=effective.encode("utf-8"),
                    stdout=stream,
                    stderr=err,
                    cwd=ROOT,
                    check=False,
                )
                process_exit = proc.returncode
            except FileNotFoundError as e:
                launch_error = f"runtime binary not found: {e.filename}"
                err.write((launch_error + "\n").encode("utf-8"))
                process_exit = 127
    except BaseException:
        # A killed dispatcher still leaves a truthful running/partial record for later inspection.
        meta["status"] = "interrupted"
        meta["duration_seconds"] = round(time.monotonic() - t0, 3)
        meta["stream_sha256"] = _sha256(stream_path)
        meta["stderr_sha256"] = _sha256(stderr_path)
        _write_meta(meta_path, meta)
        raise

    result = None
    if runtime == "claude" and process_exit == 0:
        result = _claude_result(stream_path)
        if result is not None:
            _private_write(result_path, result)
    elif runtime == "codex" and os.path.isfile(result_path):
        result = open(result_path, encoding="utf-8", errors="replace").read()
        os.chmod(result_path, 0o600)

    if process_exit == 0 and (result is None or not result.strip()):
        result = None
        wrapper_exit = WRAPPER_RESULT_MISSING
        status_name = "failed-missing-result"
    else:
        wrapper_exit = process_exit
        status_name = "success" if process_exit == 0 else "failed"

    finished = datetime.datetime.now().astimezone()
    meta.update({
        "finished_at": finished.isoformat(timespec="seconds"),
        "duration_seconds": round(time.monotonic() - t0, 3),
        "process_exit": process_exit,
        "wrapper_exit": wrapper_exit,
        "status": status_name,
        "launch_error": launch_error,
        "stream_sha256": _sha256(stream_path),
        "stderr_sha256": _sha256(stderr_path),
        "result_sha256": _sha256(result_path),
        "result_bytes": os.path.getsize(result_path) if os.path.isfile(result_path) else 0,
    })
    _write_meta(meta_path, meta)
    sys.stdout.write(_receipt(meta, result))
    return wrapper_exit


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime", required=True, choices=sorted(CAPABILITIES))
    ap.add_argument("prompt_file")
    args = ap.parse_args(argv)
    try:
        return run(args.runtime, args.prompt_file)
    except InputError as e:
        print(f"fresh-worker input rejected: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
