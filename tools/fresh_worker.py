#!/usr/bin/env python3
"""Run one bounded, non-resumable Claude, Codex or Gemini (Antigravity) worker and print its receipt.

The full trace of each run stays in a private run record under _private/work/runs.
Claude and Gemini workers are read-only.
A Codex worker may write within the folder it runs in, unless --read-only puts it in its read-only sandbox.
A run never falls back to another runtime.
The config key workers sets each runtime's model, effort and folder (instance or copy).
A worker is offline unless --web is given.
A --web run works in a copy, except where config puts that runtime in the instance and sets
web_in_instance. codex --web runs only that way.
A --worktree run works in a Git worktree, and what it changed is kept as a patch.
What a prompt says is not judged. Where a worker runs decides what its folder holds: the instance holds
everything the session can open, and a copy leaves out every path the model-send policy denies. A prompt
file or read material from such a path is refused for a copy or a worktree.

Usage: python3 tools/fresh_worker.py --runtime claude|codex|gemini [--web] [--read-only] PROMPT_FILE"""
import argparse
import dataclasses
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import claude_auth  # noqa: E402
import config as C  # noqa: E402
import paths as P  # noqa: E402
import receipts as R  # noqa: E402
import worker_sandbox as S  # noqa: E402
from worker_sandbox import InputError  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
WORKER_CODEX_WEB_REFUSED = (
    "codex --web is refused: Codex's sandbox reads the whole disk, so a Codex worker with the "
    "network could read the private area even from a copy. Ask claude or gemini with --web, or "
    "accept that risk with config workers.codex.where instance and web_in_instance true"
)
WORKER_COPY_KEEPS_NO_WRITES = (
    "this {runtime} worker runs in a copy that is deleted after the run, so --write-prefix, "
    "--expect and --worktree cannot be kept. Drop them, or drop --web, or set config "
    "workers.{runtime}.where to instance"
)
WORKER_PROMPT_FILE_DENIED = (
    "the prompt file is under a path the model-send policy denies ({path}), and this worker runs "
    "in a copy or a worktree, which is given nothing from there. Put the prompt file somewhere "
    "else in the workspace"
)
WORKER_PROMPT_OUTSIDE = (
    "prompt path is outside the workspace; a worker reads only a prompt file inside it. Copy "
    "the prompt into the workspace, for example {example}, and pass that path"
)
WORKER_STARTED = (
    "fresh-worker run {run_id} started; python3 tools/receipts.py show {run_id} prints its "
    "result once it ends"
)
WORKER_WORKTREE_NOT_ROOT = (
    "--worktree needs a Git repository whose top level is the instance root; Git found {top}"
)
WORKER_READ_ONLY_WRITES = (
    "this worker has no right to write (a Claude or Gemini worker, or --read-only), so --write-prefix "
    "and --expect have nothing to measure; its answer is its output. Drop them, or ask codex"
)
CODEX_LOGIN_FIX = "Codex is not logged in: run `codex login` in a terminal, then ask again"
# What a run records in "unavailable" when its runtime could not be called at all; null otherwise.
NOT_INSTALLED = "not-installed"
NOT_SIGNED_IN = "not-signed-in"
MODEL_NOT_AVAILABLE = "model-not-available"
# A runtime's answer that the account cannot use the model asked for (Codex: "The '<model>' model
# is not supported when using Codex with a ChatGPT account"; Claude: "There's an issue with the
# selected model").
MODEL_REFUSED = re.compile(r"model is not supported|issue with the selected model|model_not_found|"
                           r"not_found_error[^\n]{0,80}model", re.I)
# Bytes of the end of the output stream read for the error rows that say why a run failed.
ERROR_ROWS_BYTES = 65536

ROOT = P.instance_root()
RUN_ROOT = P.runs(ROOT)
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
# Lines and characters of stderr a failed run's receipt shows.
STDERR_TAIL_LINES = 3
STDERR_TAIL_CHARS = 300
# Exit statuses of the wrapper itself; any other nonzero exit is the runtime's own.
WRAPPER_RESULT_MISSING = 3
WRAPPER_MATERIAL_CHANGED = 4
WRAPPER_CAPTURE_FAILED = 5
WRAPPER_EXPECT_MISSING = 6
WRAPPER_TIMEOUT = 7
# Scheduled loops call the worker with no outer limit, so a hung runtime must end here.
DEFAULT_TIMEOUT_SECONDS = 5400
# subprocess waits pass the timeout to poll() in int milliseconds, which overflows near 24.8 days.
MAX_TIMEOUT_SECONDS = 7 * 24 * 3600
# The run record's schema version.
META_SCHEMA_VERSION = 3
# The modules a run imports; engine_sha256 hashes them so a run names the exact code that ran.
ENGINE_FILES = ("fresh_worker.py", "lib/config.py", "receipts.py", "claude_auth.py",
                "lib/worker_sandbox.py", "lib/paths.py", "lib/safeio.py")
# The instance's own policy files a worktree run gets.
WORKTREE_INSTANCE_FILES = tuple(P.tracked_name(path_of) for path_of in P.POLICY_FILES)
# Test hook: a stand-in program for a runtime, named by MOTTORI_FRESH_WORKER_<RUNTIME>_BIN.
TEST_PROGRAM_ENV = "MOTTORI_FRESH_WORKER_{}_BIN"
# The usage of a run whose runtime reported none.
NO_USAGE = {"raw": None, "input": None, "output": None, "total": None}

CAPABILITIES = {
    "claude": "read-only",
    "codex": "workspace-write",
    "gemini": "read-only",
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


def read_workspace_text(path, what="prompt"):
    """(absolute path, text) of a UTF-8 regular file inside ROOT with no symlink below ROOT. what
    names the file in a refusal: the prompt, or a read material."""
    path = os.path.expanduser(path)
    source = os.path.abspath(path if os.path.isabs(path) else os.path.join(ROOT, path))
    # The path is judged as written, so a symlink below ROOT stays visible to the walk. A real
    # root with a lexical path would look outside on macOS, which maps /var to /private/var.
    rel = S.root_relative(source, ROOT)
    if rel is None or not S.inside(source, ROOT):
        raise InputError(WORKER_PROMPT_OUTSIDE.format(
            example=P.tracked_name(P.debate) + "/_p_review.md"))
    try:
        linked = S.has_symlink_component(os.path.abspath(ROOT), rel)
    except FileNotFoundError:
        raise InputError(f"{what} file does not exist")
    if linked:
        raise InputError(f"{what} path has a symlink component")
    # O_NONBLOCK: opening a FIFO with no writer would block before the timeout applies; the
    # regular-file check below then refuses it.
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except FileNotFoundError:
        raise InputError(f"{what} file does not exist")
    except OSError as e:
        raise InputError(f"cannot open the {what} file safely: {type(e).__name__}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise InputError(f"{what} is not a regular file")
        with os.fdopen(fd, "rb") as f:
            raw = f.read()
        fd = None
    finally:
        if fd is not None:
            os.close(fd)
    if not raw:
        raise InputError(f"{what} is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError(f"{what} is not UTF-8 text")
    return source, text


def _runtime_env(runtime, workdir):
    """Pass provider settings only to their runtime; never load Claude tokens for Codex."""
    if runtime not in claude_auth.VENDOR_ENV:
        raise InputError("unsupported runtime")
    others = [name for name in claude_auth.VENDOR_ENV if name != runtime]
    if runtime == "claude":
        # claude_auth.env below drops the Codex settings, as it does for every headless Claude call.
        others.remove("codex")
    # git_env drops the caller's Git pins, so the worker's git commands use its own cwd.
    env = claude_auth.without_vendors(S.git_env(), others)
    # MOTTORI_DISABLE_HOOKS: the kit's hooks would give the worker the caller's state and turn-end
    # checks it does not own.
    env.update(MOTTORI_INSTANCE=workdir, MOTTORI_DISABLE_HOOKS="1", PWD=os.path.realpath(workdir))
    # The caller's folders would tell a worker in a copy where the instance is.
    for key in ("OLDPWD", "CLAUDE_PROJECT_DIR"):
        env.pop(key, None)
    return claude_auth.env(env) if runtime == "claude" else env


def _program(runtime):
    """The runtime's program (config.WORKER_PROGRAMS), or the stand-in a test names with TEST_PROGRAM_ENV."""
    return os.environ.get(TEST_PROGRAM_ENV.format(runtime.upper()), C.WORKER_PROGRAMS[runtime])


def _requested(runtime):
    """(model, effort) asked for, None meaning the runtime's own default.

    MOTTORI_FRESH_WORKER_CLAUDE_MODEL, _CODEX_MODEL and _CODEX_EFFORT win over config.workers.
    """
    entry = C.workers().get(runtime, {})
    model = (os.environ.get(f"MOTTORI_FRESH_WORKER_{runtime.upper()}_MODEL") if runtime != "gemini" else None) \
        or entry.get("model")
    # Only lower-case letters pass, so the value cannot close the quotes and inject another key; an
    # invalid variable falls through to the config value instead of discarding it.
    efforts = [os.environ.get("MOTTORI_FRESH_WORKER_CODEX_EFFORT") if runtime == "codex" else None,
               entry.get("effort")]
    effort = next((e for e in efforts if isinstance(e, str) and re.fullmatch(r"[a-z]+", e)), None)
    defaults = {"claude": ("opus", "high"), "codex": (None, "high"), "gemini": (None, None)}[runtime]
    return model or defaults[0], effort or defaults[1]


def _placement(runtime, web):
    """Where the worker runs: instance or copy. A --web worker reads text from outside and has a
    way out, so it gets a copy without the private area unless the owner set web_in_instance."""
    entry = C.workers().get(runtime, {})
    where = entry.get("where", "copy" if runtime == "gemini" else "instance")
    if not web or (where == "instance" and entry.get("web_in_instance", False)):
        return where
    if runtime == "codex":
        # Codex's workspace-write sandbox reads the whole disk, so from a copy it could still
        # read the private area while it has the network.
        raise InputError(WORKER_CODEX_WEB_REFUSED)
    return "copy"


def _new_run(runtime):
    os.makedirs(RUN_ROOT, mode=0o700, exist_ok=True)
    os.chmod(RUN_ROOT, 0o700)
    now = datetime.datetime.now().astimezone()
    rid = f"{now:%Y%m%dT%H%M%S%z}-{runtime}-{uuid.uuid4().hex[:8]}"
    path = os.path.join(RUN_ROOT, rid)
    os.mkdir(path, 0o700)
    return rid, path, now


def _claude_command(web=False):
    binary = _program("claude")
    model, effort = _requested("claude")
    web_tools = ["WebSearch", "WebFetch"] if web else []
    return [
        binary,
        "-p",
        # Safe mode and an empty MCP config disable ambient plugins, hooks, connectors, and browser tools.
        "--safe-mode",
        "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--model", model,
        "--effort", effort,
        "--permission-mode", "dontAsk",
        "--tools", "Read", "Glob", "Grep", *web_tools,
        # dontAsk refuses a tool nobody approved, so the web tools are approved by name.
        *(["--allowedTools", *web_tools] if web else []),
        "--no-session-persistence",
        "--no-chrome",
        "--output-format", "stream-json",
        "--verbose",
    ]


def capability(runtime, read_only=False):
    """What the run's model program may do: read-only, or its runtime's own capability."""
    return "read-only" if read_only else CAPABILITIES[runtime]


def _codex_command(result_path, web=False, where="instance", read_only=False):
    binary = _program("codex")
    model, effort = _requested("codex")
    command = [
        binary, "exec",
        # Ignore the desktop user's plugins, MCP servers, memories, and connector settings. A
        # project's own config can turn on live search, so the lines below set search and the
        # command network for this run. Authentication still comes from CODEX_HOME.
        "--ignore-user-config",
        # _requested lets only lower-case letters through, so effort cannot close these quotes.
        "--config", 'model_reasoning_effort="%s"' % effort,
        "--config", 'web_search="%s"' % ("live" if web else "disabled"),
        "--config", "sandbox_workspace_write.network_access=%s" % ("true" if web else "false"),
        "--config", "agents.enabled=false",
    ]
    # No built-in model name: which models exist depends on the user's Codex account.
    if model:
        command.extend(("--model", model))
    for feature in CODEX_DISABLED_FEATURES:
        command.extend(("--disable", feature))
    command.extend([
        # Read-only: the model's commands may read and write nothing; Codex itself still writes the
        # last message to result_path, outside the model's sandbox.
        "--sandbox", "read-only" if read_only else "workspace-write",
        # A copy has no .git, and with the user's config ignored no folder is trusted either.
        *(["--skip-git-repo-check"] if where == "copy" else []),
        "--ephemeral",
        "--json",
        "--color", "never",
        "--output-last-message", result_path,
        "-",
    ])
    return command


def _gemini_command(prompt, timeout, web=False):
    """agy in print mode with JSON output, its sandbox, accept-edits mode and a print timeout.

    accept-edits is used, never the default automatic mode. One-run permission rules deny every
    write and any command outside the sandbox, and without --web the URL actions too. The prompt
    goes in argv, because on stdin agy expects its stream format, whose result shape is unknown
    (system/dev/runtime-capture.md).
    """
    binary = _program("gemini")
    model, effort = _requested("gemini")
    deny = ["write_file(*)", "unsandboxed(*)"] + ([] if web else ["read_url(*)", "execute_url(*)"])
    command = [
        binary, "-p", prompt,
        "--output-format", "json",
        "--sandbox",
        "--mode", "accept-edits",
        "--disable-slash-commands",
        "--print-timeout", f"{int(timeout)}s",
        "--settings", json.dumps({"permissions": {"deny": deny}}, separators=(",", ":")),
    ]
    if model:
        command.extend(("--model", model))
    if effort:
        command.extend(("--effort", effort))
    return command


def _gemini_result(stream_path):
    """(result, error, run-record fields). agy exits 0 on a refused action, so a denial or an empty
    answer is the failure here, with its reason; _usage reads the usage."""
    try:
        envelope = json.loads(open(stream_path, encoding="utf-8", errors="replace").read())
    except (OSError, json.JSONDecodeError):
        envelope = None
    if not isinstance(envelope, dict):
        return None, "agy output is not one JSON object", {"conversation_id": None}
    conversation = {"conversation_id": envelope.get("conversation_id")
                    if isinstance(envelope.get("conversation_id"), str) else None}
    denied = envelope.get("denied_actions")
    if denied:
        names = ", ".join(
            f"{d.get('action', '?')} ({d.get('display_name', '?')})" if isinstance(d, dict) else str(d)
            for d in (denied if isinstance(denied, list) else [denied]))
        return None, f"agy refused actions the worker needed: {names}", conversation
    response = envelope.get("response")
    if not isinstance(response, str) or not response.strip():
        detail = envelope.get("error") or envelope.get("finished_reason") or envelope.get("status")
        return None, "agy gave an empty response" + (f" ({detail})" if detail else ""), conversation
    return response, None, conversation


def _claude_result(stream_path):
    """(result text, error text, run-record fields). A login or API failure arrives in the stream,
    not on stderr."""
    result = error = None
    with open(stream_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "error" or event.get("is_error") is True:
                text = event.get("result") if isinstance(event.get("result"), str) else event.get("error")
                if isinstance(text, dict):
                    text = text.get("message") or text.get("type")
                error = str(text or event.get("message") or event.get("subtype") or "error event")
            elif event.get("type") == "result" and isinstance(event.get("result"), str):
                # Only an error after the last successful result decides the run.
                result, error = event["result"], None
    return result, error, {}


def _stream_reader(parse):
    """A result reader for a runtime whose answer is in its output stream: parse(stream path)
    gives (result, error, run-record fields); the result counts only after exit 0 and no error."""
    def read(paths, process_exit):
        result, error, extra = parse(paths["stream"])
        if process_exit != 0 or error is not None:
            result = None
        if result is not None:
            S.private_write(paths["result"], result)
        return result, error, extra
    return read


def _move_runtime_result(paths):
    """Move the result file Codex wrote inside a worktree into the run record, when it is there."""
    if paths["runtime_result"] != paths["result"] and os.path.isfile(paths["runtime_result"]):
        with open(paths["runtime_result"], "rb") as f:
            S.private_write(paths["result"], f.read())
        os.unlink(paths["runtime_result"])


def _read_codex(paths, process_exit):
    """Codex writes its last message to a file; in a worktree that file is moved to the record."""
    if not os.path.isfile(paths["runtime_result"]):
        return None, None, {}
    _move_runtime_result(paths)
    os.chmod(paths["result"], 0o600)
    with open(paths["result"], encoding="utf-8", errors="replace") as f:
        return f.read(), None, {}


@dataclasses.dataclass(frozen=True)
class Runtime:
    """What a run needs to know about one runtime. command(run, prompt) builds its argv;
    read(run paths, process exit) returns (result text or None, runtime error or None, extra
    run-record fields); usage_event is the type of the output event whose usage is the run total,
    None when the output is one JSON envelope with its own usage."""
    command: object
    read: object
    usage_event: object
    input_keys: tuple = ("input_tokens",)  # the usage keys that add up to the input tokens
    # agy takes the prompt in argv and exits 0 on a refused action.
    prompt_on_stdin: bool = True
    error_fails_exit_0: bool = False


RUNTIMES = {
    "claude": Runtime(command=lambda run, prompt: _claude_command(run.web),
                      read=_stream_reader(_claude_result), usage_event="result",
                      input_keys=("input_tokens", "cache_creation_input_tokens",
                                  "cache_read_input_tokens")),
    "codex": Runtime(command=lambda run, prompt: _codex_command(run.paths["runtime_result"], run.web,
                                                                run.where, run.read_only),
                     read=_read_codex, usage_event="turn.completed"),
    "gemini": Runtime(command=lambda run, prompt: _gemini_command(prompt, run.timeout, run.web),
                      read=_stream_reader(_gemini_result), usage_event=None,
                      prompt_on_stdin=False, error_fails_exit_0=True),
}


def _git(args, cwd):
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10,
                           env=S.git_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _kit_identity(engine_dir=None):
    """(kit_rev, kit_dirty): the HEAD of the git repo that holds the engine, and whether the engine
    directory differs from it. Both None without git.

    kit_dirty is scoped to the engine directory (tools/), not the whole tree: an instance tree is
    always dirty with journals, and that would be false precision about the engine. The exact code
    identity is engine_sha256 (see _engine_identity), which does not depend on git at all.
    """
    engine_dir = engine_dir or ENGINE_DIR
    top = _git(["rev-parse", "--show-toplevel"], engine_dir)
    if not top:
        return None, None
    rev = _git(["rev-parse", "HEAD"], top)
    rel = os.path.relpath(os.path.realpath(engine_dir), os.path.realpath(top))
    porcelain = _git(["status", "--porcelain", "--", rel], top)
    dirty = None if porcelain is None else bool(porcelain.strip())
    return rev, dirty


def _engine_sha256(engine_dir=None):
    """Hash the engine files, so a run names the exact code that ran without depending on git."""
    engine_dir = engine_dir or ENGINE_DIR
    h = hashlib.sha256()
    for name in ENGINE_FILES:
        try:
            with open(os.path.join(engine_dir, name), "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            h.update(f"{name}:missing\n".encode("utf-8"))
            continue
        h.update(f"{name}:".encode("utf-8"))
        h.update(hashlib.sha256(raw).hexdigest().encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _engine_identity(engine_dir=None, root=None, workdir=None):
    """What actually ran: the git HEAD of the engine's checkout, the sha256 of the engine files, the
    sha256 of the AGENTS.md the worker reads in its workdir, and that of the root's AGENTS.md, which
    the engine runs from."""
    engine_dir = engine_dir or ENGINE_DIR
    root = root or ROOT
    kit_rev, engine_dirty = _kit_identity(engine_dir)
    return {
        "kit_rev": kit_rev,
        "kit_rev_source": "git" if kit_rev else None,
        "kit_dirty": engine_dirty,
        "engine_sha256": _engine_sha256(engine_dir),
        "agents_sha256": S.sha256_file(os.path.join(workdir or root, "AGENTS.md")),
        "root_agents_sha256": S.sha256_file(os.path.join(root, "AGENTS.md")),
    }


def _usage(runtime, stream_path):
    """The runtime's last usage object, normalized. Never summed across events.

    Claude's result event carries the CLI's cumulative total for the run; without it there is
    no run total, so usage stays null rather than showing one API call's numbers.
    """
    spec = RUNTIMES[runtime]
    raw = None
    try:
        f = open(stream_path, encoding="utf-8", errors="replace")
    except OSError:
        return dict(NO_USAGE)
    with f:
        # agy's usage keys were not captured, so only its raw usage object is certain.
        lines = f if spec.usage_event else [f.read().replace("\n", " ")]
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (isinstance(event, dict) and isinstance(event.get("usage"), dict)
                    and (spec.usage_event is None or event.get("type") == spec.usage_event)):
                raw = event["usage"]
    if raw is None:
        return dict(NO_USAGE)

    def num(key):
        value = raw.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    parts = [num(key) for key in spec.input_keys if num(key) is not None]
    inp = sum(parts) if parts else None
    out = num("output_tokens")
    total = inp + out if inp is not None and out is not None else None
    return {"raw": raw, "input": inp, "output": out, "total": total}


def _snapshot_read_materials(paths):
    """Explicit per-file copies only. No directory expansion, private-root mount, or symlink."""
    if len(paths) > 128:
        raise InputError("read materials exceed 128 files")
    snapshots, total = {}, 0
    for path in paths:
        if (not isinstance(path, str) or not path or os.path.isabs(path) or "\\" in path or
                any(part in ("", ".", "..") for part in path.split("/")) or
                any(ord(c) < 32 for c in path)):
            raise InputError("read material must be a canonical ROOT-relative file")
        _source, body = read_workspace_text(path, "read material")
        if S.policy_denies(path):
            raise InputError("read material denied by model-send policy: " + path)
        if path in WORKTREE_INSTANCE_FILES:
            raise InputError("read material cannot override instance policy: " + path)
        raw = body.encode("utf-8")
        total += len(raw)
        if len(raw) > 2 * 1024 * 1024 or total > 16 * 1024 * 1024:
            raise InputError("read material byte budget exceeded (2 MiB/file, 16 MiB total)")
        if path in snapshots and snapshots[path] != raw:
            raise InputError("read material changed between duplicate references: " + path)
        snapshots[path] = raw
    return snapshots


def _write_meta(path, meta):
    # backslashreplace writes a lone surrogate from a non-UTF-8 file name as a JSON escape, so the
    # record stays valid UTF-8 and readable.
    S.private_write(path, (json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                   .encode("utf-8", "backslashreplace"))


def _stderr_tail(path):
    """The last few stderr lines, so a failed run's cause (for example a 401) reaches the caller."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size - 8192))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    # A whole colour sequence goes, not just its ESC, and a tab still separates the words around it.
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).replace("\t", " ")
    lines = ["".join(ch for ch in line if ch.isprintable()).strip() for line in text.splitlines()]
    tail = "\n".join([line for line in lines if line][-STDERR_TAIL_LINES:])[-STDERR_TAIL_CHARS:]
    return [line.strip() for line in tail.splitlines()]


def _expect_paths(paths):
    """Validate --expect paths before any run: inside ROOT, also after resolving symlinks."""
    checked = []
    for path in paths:
        if not path or "\0" in path:
            raise InputError("--expect path is empty")
        rel = S.root_relative(path, ROOT)
        if rel in (None, ".") or not S.inside(os.path.join(ROOT, rel), ROOT):
            raise InputError("--expect path is outside the workspace: " + path)
        if rel not in checked:
            checked.append(rel)
    return checked


def _check_expect(workdir, paths):
    """Each expected output must be a non-empty regular file that stays inside workdir."""
    missing = []
    for rel in paths:
        full = os.path.join(workdir, *rel.split("/"))
        if not S.inside(full, workdir):
            why = "outside workspace"
        elif not os.path.lexists(full):
            why = "absent"
        elif not os.path.isfile(full):
            why = "not a file"
        elif os.path.getsize(full) == 0:
            why = "empty"
        else:
            continue
        missing.append({"path": rel, "why": why})
    return {"paths": list(paths), "present": len(paths) - len(missing), "missing": missing}


def _timeout_seconds(value):
    """Seconds the runtime may run: the option, else MOTTORI_FRESH_WORKER_TIMEOUT, else the default."""
    if value is None:
        value = os.environ.get("MOTTORI_FRESH_WORKER_TIMEOUT") or DEFAULT_TIMEOUT_SECONDS
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = None
    if seconds is None or not 0 < seconds <= MAX_TIMEOUT_SECONDS:
        raise InputError(f"--timeout must be a positive number of seconds, at most {MAX_TIMEOUT_SECONDS}")
    return seconds


@dataclasses.dataclass
class Run:
    """What one run settled before its runtime starts; each phase below reads it.

    worktree_meta is the record's worktree entry, filled in as the run goes. before is the
    worktree's snapshot at the start ({} outside a worktree) and scope_seconds the time it took.
    """
    runtime: str
    run_id: str
    run_dir: str
    workdir: str
    where: str
    web: bool
    timeout: float
    worktree_meta: dict
    placed: list
    prefixes: list
    expect: list
    before: dict
    scope_seconds: float
    paths: dict
    read_only: bool = False

    @property
    def in_worktree(self):
        return self.worktree_meta["mode"] is not None


def _run_paths(run_dir, workdir, run_id, in_worktree):
    """The files of one run record. In a worktree Codex writes its result inside the worktree,
    and the result is moved into the record afterwards."""
    paths = {name: os.path.join(run_dir, file) for name, file in (
        ("prompt", "prompt.md"), ("stream", "stream.jsonl"), ("stderr", "stderr.log"),
        ("result", "result.txt"), ("contract", "result-contract.json"), ("meta", "meta.json"))}
    paths["runtime_result"] = (os.path.join(workdir, f".mottori-worker-result-{run_id}")
                               if in_worktree else paths["result"])
    return paths


def _start_scope(workdir, write_prefixes, in_worktree):
    """(write prefixes as root-relative paths, the snapshot before the run, seconds it took).

    The prefixes are created before the snapshot, so the dispatcher's setup is not counted as
    worker output. Only a worktree has the worker as its sole writer, so only there is the
    write-set measured.
    """
    prefixes = [S.normalize_prefix(p, workdir) for p in write_prefixes]
    for prefix in prefixes:
        os.makedirs(os.path.join(workdir, prefix), exist_ok=True)
    t_scope = time.monotonic()
    before = S.snapshot(workdir) if in_worktree else {}
    return prefixes, before, time.monotonic() - t_scope


def _run_meta(run, source, started, command, effective):
    """The run record as it stands before the runtime starts."""
    model, effort = _requested(run.runtime)
    return {
        "schema_version": META_SCHEMA_VERSION,
        "run": os.path.relpath(run.run_dir, ROOT).replace(os.sep, "/"),
        "run_id": run.run_id,
        "runtime": run.runtime,
        "capability": capability(run.runtime, run.read_only),
        "where": run.where,
        "network": run.web,
        "model": model,
        "effort": effort,
        **_engine_identity(workdir=run.workdir),
        "usage": dict(NO_USAGE),
        "worktree": run.worktree_meta,
        "scope": S.pending_scope(run.prefixes, len(run.before), run.scope_seconds),
        "source_prompt": os.path.relpath(source, ROOT),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": None,
        "process_exit": None,
        "wrapper_exit": None,
        "status": "running",
        "unavailable": None,
        # The prompt is in prompt.md; agy's copy of it in argv is not repeated here.
        "command": [("<prompt.md>" if arg == effective else arg) for arg in command],
        "prompt_sha256": S.sha256_file(run.paths["prompt"]),
        "stream_sha256": None,
        "stderr_sha256": None,
        "result_sha256": None,
        "result_bytes": 0,
    }


def _launch(run, command, effective, stream_fd, stderr_fd):
    """Run the runtime in its own process group with its output on the two open files, which this
    closes. Returns (process exit, launch error, timed out)."""
    process_exit = launch_error = None
    timed_out = False
    with os.fdopen(stream_fd, "wb") as stream, os.fdopen(stderr_fd, "wb") as err:
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stream,
                stderr=err,
                cwd=run.workdir,
                env=_runtime_env(run.runtime, run.workdir),
                start_new_session=True,
            )
            try:
                stdin = effective if RUNTIMES[run.runtime].prompt_on_stdin else ""
                proc.communicate(stdin.encode("utf-8"), timeout=run.timeout)
                process_exit = proc.returncode
            except subprocess.TimeoutExpired:
                # The finally below reaps the whole group; the run is recorded, not raised.
                timed_out = True
            finally:
                _stop_runtime_group(proc)
        except OSError as e:
            missing = isinstance(e, FileNotFoundError)
            launch_error = (f"runtime binary not found: {e.filename}" if missing
                            else f"runtime could not start: {type(e).__name__}: {e.strerror}")
            err.write((launch_error + "\n").encode("utf-8"))
            process_exit = 127 if missing else 126
    return process_exit, launch_error, timed_out


def _capture(run, after):
    """Capture the worktree into the record; after None takes the snapshot now. A failure is
    recorded in the worktree entry, and the worktree stays until a capture completes."""
    worktree_meta = run.worktree_meta
    try:
        if after is None:
            after = S.snapshot(run.workdir)
        worktree_meta.update(S.capture_worktree(run.workdir, run.run_dir, run.placed, run.prefixes,
                                                run.before, after, worktree_meta.get("base_tree")))
    except Exception as error:
        worktree_meta.update(capture_status="failed", capture_error=f"{type(error).__name__}: {error}")
    if worktree_meta.get("capture_status") == "complete":
        worktree_meta.pop("preserved_path", None)


def _status(runtime, process_exit, timed_out, runtime_error, result, worktree_meta, expect_report):
    """(run status, wrapper exit) from what the run left. The first failure in this order wins:
    capture, read materials, timeout, an agy refusal, a missing result, the runtime's exit; a
    missing expected output only turns a success into expected-output-missing."""
    if worktree_meta.get("capture_status") in ("failed", "incomplete"):
        status, wrapper_exit = "artifact-capture-" + worktree_meta["capture_status"], WRAPPER_CAPTURE_FAILED
    elif worktree_meta.get("material_integrity") is False:
        status, wrapper_exit = "read-material-changed", WRAPPER_MATERIAL_CHANGED
    elif timed_out:
        status, wrapper_exit = "timeout", WRAPPER_TIMEOUT
    elif runtime_error is not None and RUNTIMES[runtime].error_fails_exit_0 and process_exit == 0:
        status, wrapper_exit = "failed", 1
    elif process_exit == 0 and (result is None or not result.strip()):
        status, wrapper_exit = "failed-missing-result", WRAPPER_RESULT_MISSING
    else:
        status, wrapper_exit = ("success" if process_exit == 0 else "failed"), process_exit
    if expect_report is not None and expect_report["missing"] and status == "success":
        # The run did not deliver what the dispatcher asked for; earlier failures keep their own.
        status, wrapper_exit = "expected-output-missing", WRAPPER_EXPECT_MISSING
    if status not in R.FINISHED_STATUSES:
        # The receipt ledger classifies runs by this shared list.
        raise AssertionError(f"unregistered worker status: {status}")
    return status, wrapper_exit


def _login_lost(runtime, errors, stderr_tail):
    """Whether the runtime's error or stderr says its login is missing or expired."""
    if runtime == "claude":
        return claude_auth.is_auth_error("\n".join(errors + (stderr_tail or [])))
    # Codex prints its 401 when the login expired; a stray "401" (a line number) is not that.
    return runtime == "codex" and bool(re.search(r"401 Unauthorized|status(?: code)?:? 401\b",
                                                 "\n".join(stderr_tail or [])))


def _runtime_errors(runtime, runtime_error, stderr_tail):
    """The error lines for the receipt, with the one step that fixes a lost login."""
    errors = [runtime_error] if runtime_error else []
    if _login_lost(runtime, errors, stderr_tail):
        errors.append(claude_auth.AUTH_FIX if runtime == "claude" else CODEX_LOGIN_FIX)
    return errors or None


def _error_rows(stream_path):
    """The error rows at the end of the output stream, as text (Codex reports a refused model
    only there, with nothing on stderr)."""
    try:
        with open(stream_path, "rb") as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size - ERROR_ROWS_BYTES))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and (row.get("type") in ("error", "turn.failed") or row.get("is_error") is True):
            rows.append(line)
    return rows


def _unavailable(runtime, meta, launch_error, stream_path):
    """Why the runtime could not be called (its program is missing, its login is lost, or the
    account cannot use the model), or None, also for a runtime that ran and answered badly."""
    if meta["status"] == "success":
        return None
    if launch_error and meta["process_exit"] == 127:
        return NOT_INSTALLED
    errors = meta.get("runtime_error") or []
    if _login_lost(runtime, errors, meta.get("stderr_tail")):
        return NOT_SIGNED_IN
    if MODEL_REFUSED.search("\n".join(errors + (meta.get("stderr_tail") or []) + _error_rows(stream_path))):
        return MODEL_NOT_AVAILABLE
    return None


def _finish(run, meta, process_exit, timed_out):
    """Read the result, measure and capture the worktree, choose the status and write the final
    record. Returns (result text or None, wrapper exit)."""
    runtime, paths, worktree_meta = run.runtime, run.paths, run.worktree_meta
    if run.in_worktree:
        # The worktree now holds the worker's output: _run keeps it until capture completes,
        # also when the result handling below fails.
        worktree_meta.update(capture_status="in_progress", preserved_path=run.workdir)
    result, runtime_error, extra = RUNTIMES[runtime].read(paths, process_exit)
    meta.update(extra)
    S.private_write(paths["contract"], json.dumps(R.result_contract(result), ensure_ascii=False,
                                                  indent=2, sort_keys=True) + "\n")
    t_scope = time.monotonic()
    after = S.snapshot(run.workdir) if run.in_worktree else {}
    scope = (S.scope_report(run.prefixes, run.before, after,
                            run.scope_seconds + (time.monotonic() - t_scope), run.workdir)
             if run.in_worktree else S.unmeasured_scope(run.prefixes, run.where))
    if run.in_worktree:
        material_changes = S.read_material_violations(run.workdir, worktree_meta.get("material_sha256", {}))
        worktree_meta["material_integrity"] = not material_changes
        worktree_meta["material_changes"] = material_changes
        # Write the record that names the kept worktree before capture: a TERM can interrupt any
        # write that follows.
        _write_meta(paths["meta"], meta)
        _capture(run, after)
    expect_report = _check_expect(run.workdir, run.expect) if run.expect else None
    if expect_report is not None and run.in_worktree:
        S.mark_uncaptured(expect_report, run.workdir, worktree_meta)
    status, wrapper_exit = _status(runtime, process_exit, timed_out, runtime_error, result,
                                   worktree_meta, expect_report)
    if status == "failed-missing-result":
        result = None
    if expect_report is not None:
        meta["expect"] = expect_report
    stderr_tail = _stderr_tail(paths["stderr"]) if status != "success" else None
    meta.update({
        "finished_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "process_exit": process_exit,
        "wrapper_exit": wrapper_exit,
        "status": status,
        "stderr_tail": stderr_tail,
        "runtime_error": _runtime_errors(runtime, runtime_error, stderr_tail),
        "usage": _usage(runtime, paths["stream"]),
        "scope": scope,
    })
    return result, wrapper_exit


def _record_files(meta, paths):
    """Hash the run's stream, stderr and result into the record."""
    meta["stream_sha256"] = S.sha256_file(paths["stream"])
    meta["stderr_sha256"] = S.sha256_file(paths["stderr"])
    # A result the runtime wrote before an interruption is recorded with its hash too, so show can
    # still tell later edits from the bytes the run left.
    meta["result_sha256"] = S.sha256_file(paths["result"])
    meta["result_bytes"] = os.path.getsize(paths["result"]) if os.path.isfile(paths["result"]) else 0


def _record_interrupted(run, meta, t0):
    """Leave a truthful partial record, never "running", when the run was killed or crashed.

    Interrupted while the runtime ran, the worktree's contents are captured before _run removes
    it, and the worktree is kept when that capture cannot finish.
    """
    paths, worktree_meta = run.paths, run.worktree_meta
    if run.in_worktree and "capture_status" not in worktree_meta:
        worktree_meta.update(capture_status="in_progress", preserved_path=run.workdir)
        try:
            _write_meta(paths["meta"], meta)
            _move_runtime_result(paths)
        except Exception as error:
            worktree_meta.update(capture_status="failed", capture_error=f"{type(error).__name__}: {error}")
        else:
            _capture(run, None)
    meta["status"] = R.INTERRUPTED_STATUS
    meta["duration_seconds"] = round(time.monotonic() - t0, 3)
    meta["stderr_tail"] = _stderr_tail(paths["stderr"])
    _record_files(meta, paths)
    _write_meta(paths["meta"], meta)


def _run_once(run, source, body, started):
    """Run the runtime once in the run's workdir (the instance, a copy or a worktree) and record
    the run. Returns (receipt text, wrapper exit)."""
    paths = run.paths
    effective = R.worker_prompt(capability(run.runtime, run.read_only), body)
    S.private_write(paths["prompt"], effective)
    command = RUNTIMES[run.runtime].command(run, effective)
    meta = _run_meta(run, source, started, command, effective)
    _write_meta(paths["meta"], meta)
    t0 = time.monotonic()
    stream_fd = os.open(paths["stream"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stderr_fd = os.open(paths["stderr"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        process_exit, launch_error, timed_out = _launch(run, command, effective, stream_fd, stderr_fd)
        result, wrapper_exit = _finish(run, meta, process_exit, timed_out)
        meta["duration_seconds"] = round(time.monotonic() - t0, 3)
        meta["launch_error"] = launch_error
        meta["unavailable"] = _unavailable(run.runtime, meta, launch_error, paths["stream"])
        _record_files(meta, paths)
        _write_meta(paths["meta"], meta)
    except BaseException:
        _record_interrupted(run, meta, t0)
        raise
    return R.render_receipt(meta, result), wrapper_exit


def _stop_runtime_group(proc):
    """Reap only this runtime group, including descendants left after its leader exits."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        # macOS answers EPERM when every member left in the group is a zombie; nothing is left to kill.
        except (ProcessLookupError, PermissionError):
            break
        if sig == signal.SIGTERM:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _interrupt_run(signum, frame):
    # A second TERM must not interrupt the owned child/worktree cleanup.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def run(*args, **kwargs):
    """TERM/INT run the same cleanup as exceptions. SIGKILL cannot run Python cleanup."""
    old = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for sig in old:
            signal.signal(sig, _interrupt_run)
        return _run(*args, **kwargs)
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


def _record_cleanup_error(run_dir, error):
    print(f"fresh-worker warning: {error}", file=sys.stderr)
    meta_path = os.path.join(run_dir, "meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["worktree"]["cleanup_error"] = str(error)
        _write_meta(meta_path, meta)
    except (OSError, ValueError, KeyError, TypeError):
        pass


def _finish_note(run_id, runtime, run_dir):
    # The receipt is already out, so a note that cannot be saved only warns.
    try:
        with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as f:
            status = json.load(f).get("status") or "-"
        import notes
        notes.finish(run_id, runtime, status)
    except Exception as error:  # noqa: BLE001 - the run's outcome must not change
        print(f"fresh-worker warning: finish note not saved ({type(error).__name__}: {error})",
              file=sys.stderr)


def _write_run_file(path, run_id, run_dir):
    """Tell a caller where the run is, as JSON, once its folder exists; meta.json there says how it ended."""
    S.private_write(path, json.dumps({"run_id": run_id, "run_dir": run_dir}) + "\n")


def _refuse_options(write_prefixes, worktree_mode, expect, read_materials, read_only, runtime=None):
    """Refuse a configuration or a combination of options that cannot work, before anything is prepared."""
    if C.error() == "invalid":
        raise InputError("memory config validation failed: " + (C.error_detail() or "unknown"))
    if read_materials and worktree_mode is None:
        raise InputError("--read-material requires an isolated --worktree")
    # A Claude or Gemini worker is read-only whatever the flags say, so it cannot meet a write scope.
    if (read_only or CAPABILITIES.get(runtime) == "read-only") and (write_prefixes or expect):
        raise InputError(WORKER_READ_ONLY_WRITES)


def _run(runtime, prompt_file, write_prefixes=(), worktree_mode=None,
         expect=(), read_materials=(), timeout=None, web=False, finish_note=False, run_file=None,
         read_only=False):
    _refuse_options(write_prefixes, worktree_mode, expect, read_materials, read_only, runtime)
    where = _placement(runtime, web)
    if where == "copy" and (write_prefixes or expect or worktree_mode is not None):
        # A copy is deleted after the run, so nothing written there could be delivered.
        raise InputError(WORKER_COPY_KEEPS_NO_WRITES.format(runtime=runtime))
    source, body = read_workspace_text(prompt_file)
    if where == "copy" or worktree_mode is not None:
        # The prompt's words are not read for paths. Its file is judged like a read material: a
        # copy or a worktree is given nothing from a path the model-send policy denies.
        source_rel = os.path.relpath(source, ROOT).replace(os.sep, "/")
        if S.policy_denies(source_rel):
            raise InputError(WORKER_PROMPT_FILE_DENIED.format(path=source_rel))
    expect = _expect_paths(expect)
    for prefix in write_prefixes:
        S.normalize_prefix(prefix, ROOT)  # refuse before a run directory exists
    material_snapshots = _snapshot_read_materials(read_materials)
    timeout = _timeout_seconds(timeout)
    if worktree_mode is not None:
        # In a nested instance without its own .git, Git finds the enclosing project and the
        # worktree would check that out instead.
        top = S.git_require(["rev-parse", "--show-toplevel"], ROOT).decode("utf-8", "replace").strip()
        if os.path.realpath(top) != os.path.realpath(ROOT):
            raise InputError(WORKER_WORKTREE_NOT_ROOT.format(top=top))
    copy = S.prepare_copy(ROOT) if where == "copy" else None
    try:
        run_id, run_dir, started = _new_run(runtime)
    except BaseException:
        if copy:
            shutil.rmtree(copy, ignore_errors=True)
        raise
    # A caller that runs two workers at once learns each run id before either ends.
    print(WORKER_STARTED.format(run_id=run_id), file=sys.stderr, flush=True)
    if run_file:
        try:
            _write_run_file(run_file, run_id, run_dir)
        except OSError as error:
            os.rmdir(run_dir)   # still empty: a run nobody can find leaves nothing behind
            if copy:
                shutil.rmtree(copy, ignore_errors=True)
            raise InputError(f"--run-file cannot be written: {error}") from error
    workdir = copy or ROOT
    placed = []
    worktree_meta = {"mode": None, "base_rev": None, "patch_sha256": None, "files": [], "added": 0,
                     "deleted": 0}
    if worktree_mode is not None:
        try:
            workdir, worktree_meta, placed = S.prepare_worktree(
                ROOT, run_dir, worktree_mode, WORKTREE_INSTANCE_FILES, material_snapshots)
        except BaseException:
            try:
                os.rmdir(run_dir)  # only when empty: a failed preparation leaves no run behind
            except OSError:
                pass
            raise
    try:
        in_worktree = worktree_mode is not None
        prefixes, before, scope_seconds = _start_scope(workdir, write_prefixes, in_worktree)
        run_state = Run(runtime=runtime, run_id=run_id, run_dir=run_dir, workdir=workdir, where=where,
                        web=web, timeout=timeout, worktree_meta=worktree_meta, placed=placed,
                        prefixes=prefixes, expect=expect, before=before, scope_seconds=scope_seconds,
                        paths=_run_paths(run_dir, workdir, run_id, in_worktree), read_only=read_only)
        receipt, wrapper_exit = _run_once(run_state, source, body, started)
    finally:
        if copy:
            shutil.rmtree(copy, ignore_errors=True)
        if worktree_mode is not None and worktree_meta.get("capture_status") not in (
                "in_progress", "failed", "incomplete"):
            try:
                S.remove_worktree(ROOT, workdir)
            except RuntimeError as error:
                # A leftover worktree must not hide the run's outcome or its receipt.
                _record_cleanup_error(run_dir, error)
    sys.stdout.write(receipt)
    if finish_note:
        _finish_note(run_id, runtime, run_dir)
    return wrapper_exit


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime", required=True, choices=sorted(CAPABILITIES))
    ap.add_argument("--write-prefix", action="append", default=[], metavar="DIR",
                    help="ROOT-relative directory the worker may write under (repeatable). With "
                         "--worktree, changes outside every prefix are reported after the run (report "
                         "only) and ignored outputs under a prefix are captured. In the shared "
                         "workspace the write-set is not measured.")
    ap.add_argument("--worktree", nargs="?", const="dirty", choices=("head", "dirty"),
                    help="Run in <run>/wt and extract patch.diff plus untracked.txt. 'head' starts "
                         "from HEAD; 'dirty' first applies the original tree's tracked git diff. "
                         "A bare --worktree means dirty.")
    ap.add_argument("--read-material", action="append", default=[], metavar="FILE",
                    help="Snapshot one policy-approved UTF-8 file into the worktree at the same "
                         "ROOT-relative path. Repeat per file; no directories or symlinks. "
                         "Hashes and post-run integrity are recorded in worktree metadata.")
    ap.add_argument("--expect", action="append", default=[], metavar="PATH",
                    help="ROOT-relative output the worker must leave as a non-empty file (repeatable). "
                         "Checked after the run; a missing or empty one turns a success into "
                         "expected-output-missing with exit 6 and an INCONCLUSIVE receipt verdict. "
                         "Paths outside the workspace are rejected before the run.")
    ap.add_argument("--timeout", metavar="SECONDS",
                    help="Stop the runtime and its process group after this many seconds and record "
                         "status timeout with exit 7. Default: MOTTORI_FRESH_WORKER_TIMEOUT, else "
                         f"{DEFAULT_TIMEOUT_SECONDS}.")
    ap.add_argument("--web", action="store_true",
                    help="Give this one worker the network and its runtime's web search. It runs in "
                         "a copy without the private area unless config workers.<runtime>.where is "
                         "instance and web_in_instance is true; codex --web runs only that way. "
                         "Without it every worker is offline.")
    ap.add_argument("--run-file", metavar="FILE",
                    help="Write {\"run_id\", \"run_dir\"} as JSON to FILE as soon as the run's folder "
                         "exists, so a program learns where the run is without reading the receipt; "
                         "meta.json in run_dir says how it ended. No file is written when the input "
                         "is rejected before a run starts.")
    ap.add_argument("--read-only", action="store_true",
                    help="Give the model program no right to write anywhere, for every runtime: Codex "
                         "runs in its read-only sandbox (Claude and Gemini are read-only already). "
                         "Its final answer is its output. Refused with --write-prefix and --expect.")
    # tools/ask.sh passes it, so a session that did not wait for the receipt learns the run ended.
    ap.add_argument("--finish-note", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("prompt_file")
    args = ap.parse_args(argv)
    try:
        return run(args.runtime, args.prompt_file, write_prefixes=args.write_prefix,
                   worktree_mode=args.worktree, expect=args.expect,
                   read_materials=args.read_material, timeout=args.timeout, web=args.web,
                   finish_note=args.finish_note, run_file=args.run_file, read_only=args.read_only)
    except InputError as e:
        print(f"fresh-worker input rejected: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
