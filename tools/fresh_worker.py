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
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M
import worker_batch as B


ROOT = M.ROOT
RUN_ROOT = os.path.join(ROOT, "_private", "work", "runs")
RECEIPT_MAX_BYTES = 4096
WRAPPER_RESULT_MISSING = 3
RESULT_CONTRACT_PREFIX = "RESULT_JSON: "
RESULT_VERDICTS = {"PASS", "FAIL", "INCONCLUSIVE"}
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
META_SCHEMA_VERSION = 2  # v2 (2026-09-16): kit_rev · kit_dirty · harness_sha256 · usage · read_scope · scope
# The kit revision this copy was synced from. The kit repo itself leaves it None (git HEAD is used);
# the instance sync step stamps the kit HEAD here so an instance copy never reports its own repo
# HEAD as the kit revision (independent review 2026-09-16, R5).
KIT_REV_EMBEDDED = None
# Stamped alongside KIT_REV_EMBEDDED by the sync: whether the kit engine dir was dirty at sync time and
# the normalized engine sha256 of the files that were copied (review R5). None in the kit itself.
KIT_SYNC_DIRTY = None
KIT_SYNC_ENGINE_SHA256 = None   # destination baseline: normalized engine sha of the copy right after sync
KIT_SYNC_SOURCE_SHA256 = None   # source manifest: sha over the kit files that were copied (review R5, 3rd pass)
ENGINE_FILES = ("fresh_worker.py", "memlib.py", "worker_batch.py")
SYNC_FILES = ("fresh_worker.py", "test_fresh_worker.py", "worker_batch.py",
              "test_worker_batch.py", "ask_codex.sh")
STAMP_PREFIXES = ("KIT_REV_EMBEDDED =", "KIT_SYNC_DIRTY =", "KIT_SYNC_ENGINE_SHA256 =", "KIT_SYNC_SOURCE_SHA256 =")
WORKTREE_INSTANCE_FILES = (
    "system/memory-config.json",
    "system/instance-rules.md",
    "system/decisions.md",
    "system/rituals.local.md",
)

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


def _under_policy_prefix(path, prefix):
    return path == prefix.rstrip("/") or path.startswith(prefix)


def _private_refs(source, body):
    """Return unique denied workspace paths named by the prompt or used as its source."""
    policy = M.EGRESS_MODEL_SEND
    deny = policy["deny_prefixes"]
    allow = policy["allow_prefixes"]
    found = []

    def add(path):
        path = path.replace(os.sep, "/")
        if path.startswith("./"):
            path = path[2:]
        if (any(_under_policy_prefix(path, prefix) for prefix in deny)
                and not any(_under_policy_prefix(path, prefix) for prefix in allow)
                and path not in found):
            found.append(path)

    source_rel = os.path.relpath(source, ROOT).replace(os.sep, "/")
    add(source_rel)
    root_prefix = ROOT.rstrip(os.sep).replace(os.sep, "/") + "/"
    for prefix in deny:
        spellings = (prefix, root_prefix + prefix)
        for spelling in spellings:
            pattern = (r"(?<![A-Za-z0-9_.-])(" + re.escape(spelling)
                       + r"[^\s`'\"<>\[\](){};,]*)")
            for match in re.finditer(pattern, body):
                raw = match.group(1).rstrip(".!?:")
                add(raw[len(root_prefix):] if raw.startswith(root_prefix) else raw)
    return found


def _private_source_texts(refs):
    """Snapshot named private text before a writable worker can alter it."""
    sources = {}
    for ref in refs:
        path = os.path.join(ROOT, *ref.split("/"))
        try:
            if not os.path.isfile(path) or not _inside_root(path):
                continue
            with open(path, encoding="utf-8") as source_file:
                text = source_file.read()
        except (OSError, UnicodeError):
            continue
        if text:
            sources[ref] = text
    return sources


def _egress_events(runtime, refs, source_texts, effective, result, rel_run):
    """Describe private references sent to the model and verified run-record copies."""
    events = [
        {"kind": "model_send_reference", "source": ref, "destination": f"model:{runtime}"}
        for ref in refs
    ]
    destinations = ((f"{rel_run}/prompt.md", effective),
                    (f"{rel_run}/result.txt", result or ""))
    for ref in refs:
        for destination, content in destinations:
            if ref in content:
                events.append({
                    "kind": "private_reference_copy",
                    "source": ref,
                    "destination": destination,
                })
    for ref, source_text in source_texts.items():
        for destination, content in destinations:
            if source_text in content:
                events.append({
                    "kind": "private_content_copy",
                    "source": ref,
                    "destination": destination,
                })
    return events


def _result_contract(result):
    """Validate the machine-readable final-result line without inferring from prose."""
    def invalid(error):
        return {
            "schema_version": 1,
            "valid": False,
            "verdict": "INCONCLUSIVE",
            "summary": "structured result unavailable",
            "evidence": [],
            "unknowns": [error],
            "error": error,
        }

    if not isinstance(result, str) or not result.strip():
        return invalid("result is missing")
    lines = result.splitlines()
    candidates = [line for line in lines if line.startswith(RESULT_CONTRACT_PREFIX)]
    if len(candidates) != 1:
        return invalid("exactly one RESULT_JSON line is required")
    if candidates[0] != next(line for line in reversed(lines) if line.strip()):
        return invalid("RESULT_JSON must be the final non-empty line")
    try:
        payload = json.loads(candidates[0][len(RESULT_CONTRACT_PREFIX):])
    except json.JSONDecodeError:
        return invalid("RESULT_JSON is not valid JSON")
    required = {"verdict", "summary", "evidence", "unknowns"}
    if not isinstance(payload, dict) or set(payload) != required:
        return invalid("RESULT_JSON fields must be verdict, summary, evidence, unknowns")
    if payload.get("verdict") not in RESULT_VERDICTS:
        return invalid("RESULT_JSON verdict is not PASS, FAIL, or INCONCLUSIVE")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        return invalid("RESULT_JSON summary must be a non-empty string")
    for field in ("evidence", "unknowns"):
        values = payload.get(field)
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip()
                                                   for value in values):
            return invalid(f"RESULT_JSON {field} must be a list of non-empty strings")
    if not payload["evidence"]:
        return invalid("RESULT_JSON evidence must contain at least one path or section")
    return {
        "schema_version": 1,
        "valid": True,
        **payload,
        "error": None,
    }


def _effective_prompt(runtime, body):
    capability = CAPABILITIES[runtime]
    common = (
        "[fresh bounded worker contract]\n"
        f"- runtime capability: {capability}\n"
        "- This is a fresh, non-resumable worker. Read AGENTS.md and the named disk sources.\n"
        "- Do not commit, push, send, pay, submit, or change state journals/NOW; the dispatcher owns state.\n"
        "- Put durable work in the exact artifact paths authorized by the request.\n"
        "- End with a concise result that lists evidence, changed artifact paths, tests, and remaining unknowns.\n"
        "- Every factual claim in the result names the file path (and line or section) it came from; "
        "a claim without a source goes under remaining unknowns.\n"
        "- End with exactly one machine-readable final line: RESULT_JSON: "
        '{"verdict":"PASS|FAIL|INCONCLUSIVE","summary":"...","evidence":["path:line"],'
        '"unknowns":["..."]}. Use an empty unknowns list when nothing remains.\n\n'
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


def _git(args, cwd):
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _kit_identity(engine_dir=None):
    """(repo_rev, engine_dirty) of the git repo that holds this engine file. Both None without git.

    engine_dirty is scoped to the engine directory (tools/), not the whole tree: an instance tree is
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
    """sha256 over the engine files with the sync stamp lines removed, so the kit file and a stamped
    instance copy of the same code hash the same (review R5)."""
    engine_dir = engine_dir or ENGINE_DIR
    h = hashlib.sha256()
    for name in ENGINE_FILES:
        try:
            with open(os.path.join(engine_dir, name), "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            h.update(f"{name}:missing\n".encode("utf-8"))
            continue
        kept = [line for line in raw.split(b"\n")
                if not any(line.startswith(prefix.encode("utf-8")) for prefix in STAMP_PREFIXES)]
        h.update(f"{name}:".encode("utf-8"))
        h.update(hashlib.sha256(b"\n".join(kept)).hexdigest().encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _source_manifest_sha256(engine_dir=None):
    """sha256 over the files a sync copies (stamp lines excluded), computed on the source side."""
    engine_dir = engine_dir or ENGINE_DIR
    h = hashlib.sha256()
    for name in SYNC_FILES:
        try:
            with open(os.path.join(engine_dir, name), "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            h.update(f"{name}:missing\n".encode("utf-8"))
            continue
        kept = [line for line in raw.split(b"\n")
                if not any(line.startswith(prefix.encode("utf-8")) for prefix in STAMP_PREFIXES)]
        digest = hashlib.sha256(b"\n".join(kept)).hexdigest()
        h.update(f"{name}:{digest}\n".encode("utf-8"))
    return h.hexdigest()


def _engine_identity(engine_dir=None, root=None):
    """What actually ran: the kit revision (embedded at sync time, else git HEAD), the repo HEAD of
    the running copy, the normalized sha256 of the engine files, whether the copy still matches what
    the sync stamped, and the sha256 of AGENTS.md the worker is told to read (instance content, so it
    is kept out of harness_sha256)."""
    engine_dir = engine_dir or ENGINE_DIR
    root = root or ROOT
    repo_rev, engine_dirty = _kit_identity(engine_dir)
    engine_sha = _engine_sha256(engine_dir)
    if KIT_REV_EMBEDDED:
        kit_rev, source = KIT_REV_EMBEDDED, "embedded"
    elif repo_rev:
        kit_rev, source = repo_rev, "git"
    else:
        kit_rev, source = None, None
    return {
        "kit_rev": kit_rev,
        "kit_rev_source": source,
        "kit_dirty": engine_dirty,
        "kit_sync": {"dirty": KIT_SYNC_DIRTY,
                     "engine_sha256": KIT_SYNC_ENGINE_SHA256,      # destination baseline at sync time
                     "source_sha256": KIT_SYNC_SOURCE_SHA256,      # what the kit shipped (SYNC_FILES)
                     "matches_copy": (KIT_SYNC_ENGINE_SHA256 == engine_sha) if KIT_SYNC_ENGINE_SHA256 else None},
        "repo_rev": repo_rev,
        "engine_sha256": engine_sha,
        "agents_sha256": _sha256(os.path.join(root, "AGENTS.md")),
    }


def _harness_sha256(runtime, command, run_specific=()):
    """Identity of the adapter contract, independent of prompt body and run paths.

    Inputs: runtime, capability, the common contract prefix, the command options in order (binary
    and run-specific paths removed), and the disabled-feature list. Canonical JSON, sha256.
    """
    opts = [arg for arg in command[1:] if arg not in set(run_specific)]
    payload = {
        "runtime": runtime,
        "capability": CAPABILITIES[runtime],
        "contract_prefix": _effective_prompt(runtime, ""),
        "command_opts": opts,
        "disabled_features": sorted(CODEX_DISABLED_FEATURES) if runtime == "codex" else [],
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _usage(runtime, stream_path):
    """The runtime's last usage object, normalized. Never summed across events."""
    raw = None
    last_assistant = None
    try:
        f = open(stream_path, encoding="utf-8", errors="replace")
    except OSError:
        return {"raw": None, "input": None, "output": None, "total": None}
    with f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if runtime == "codex":
                if kind == "turn.completed" and isinstance(event.get("usage"), dict):
                    raw = event["usage"]
            else:
                if kind == "result" and isinstance(event.get("usage"), dict):
                    raw = event["usage"]
                elif kind == "assistant":
                    msg = event.get("message")
                    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                        last_assistant = msg["usage"]
    if runtime == "claude" and raw is None:
        raw = last_assistant
    if raw is None:
        return {"raw": None, "input": None, "output": None, "total": None}

    def num(key):
        value = raw.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    if runtime == "codex":
        inp = num("input_tokens")
    else:
        parts = [num("input_tokens"), num("cache_creation_input_tokens"), num("cache_read_input_tokens")]
        inp = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None
    out = num("output_tokens")
    total = inp + out if inp is not None and out is not None else None
    return {"raw": raw, "input": inp, "output": out, "total": total}


def _read_scope(result):
    """First line (starts with 읽음 or 읽기 범위) and last UNREAD line of the result, preserved as strings."""
    if not result:
        return None
    lines = result.lstrip("﻿").splitlines()
    declared = None
    unread = None
    for line in lines:
        s = line.strip()
        if s:  # first non-empty line, stripped; a leading BOM is removed (review R6)
            if s.startswith(("읽음", "읽기 범위")):
                declared = s
            break
    for line in reversed(lines):
        s = line.strip()
        if s.startswith(("UNREAD:", "끝까지 못 읽은 것:")):
            unread = s
            break
    if declared is None and unread is None:
        return None
    return {"declared": declared, "unread": unread}


WRAPPER_SCOPE_VIOLATION = 4
SCOPE_LIST_CAP = 500


def _normalize_prefix(prefix, root=None):
    """A write prefix is a ROOT-relative directory path with no symlink component. It may not exist yet."""
    root = os.path.abspath(root or ROOT)
    absolute = os.path.abspath(prefix if os.path.isabs(prefix) else os.path.join(root, prefix))
    try:
        rel = os.path.relpath(absolute, root)
    except ValueError:
        raise InputError("write-prefix가 workspace 밖이다")
    if rel in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep):
        raise InputError("write-prefix가 workspace 밖이거나 루트 전체다")
    current = root
    canonical = []
    parts = rel.split(os.sep)
    for i, part in enumerate(parts):
        # On a case-insensitive filesystem the on-disk spelling is what os.walk reports; use it,
        # otherwise a prefix typed as OUT and a directory named out would be a false violation.
        try:
            entries = os.listdir(current)
        except OSError:
            entries = []
        if part not in entries:
            same = [e for e in entries if e.lower() == part.lower()]
            # Only when the filesystem itself resolves the typed spelling to that entry (i.e. it is
            # case-insensitive here); on a case-sensitive volume OUT and out are different paths (R10).
            if len(same) == 1 and os.path.exists(os.path.join(current, part)) \
                    and os.path.samefile(os.path.join(current, part), os.path.join(current, same[0])):
                part = same[0]
        current = os.path.join(current, part)
        canonical.append(part)
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise InputError("write-prefix에 symlink component가 있다")
        except FileNotFoundError:
            canonical.extend(parts[i + 1:])
            break  # the rest may be created by the worker
    return "/".join(canonical)


def _workspace_snapshot(exclude_rel, root=None, include_git=False, include_parent=False):
    """Return metadata fingerprints for the worker's observable write boundary.

    Normal report-only runs omit .git and the parent. Strict runs include .git and the immediate
    parent entries so writes to the two control surfaces cannot disappear from the write-set. The
    parent scan is deliberately one level: recursive observation would cross into unrelated
    workspaces and still would not be confinement. The runtime sandbox remains the outer boundary.

    Only lstat is used (no hashing), so a snapshot of a large tree costs well under a second.
    ctime_ns is included because a writer can restore mtime with utime but cannot restore ctime,
    and mode catches chmod (review R2). Symlinks are recorded as their own entries (kind 'link');
    their targets are not followed.
    """
    root = os.path.abspath(root or ROOT)
    runs_rel = os.path.relpath(RUN_ROOT, root).replace(os.sep, "/")
    if runs_rel == ".." or runs_rel.startswith("../"):
        runs_rel = None
    snap = {}

    def fingerprint(st, kind):
        return (kind, st.st_size, st.st_mtime_ns, st.st_ctime_ns, stat.S_IMODE(st.st_mode),
                st.st_dev, st.st_ino, st.st_nlink)

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            # The run-record tree belongs to the wrapper, not the worker. Strict runs do include
            # .git because refs, config, index, and hooks are enforcement control surfaces.
            if (d == ".git" and not include_git) or rel == exclude_rel \
                    or (runs_rel is not None and rel == runs_rel):
                continue
            full = os.path.join(dirpath, d)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                snap[rel] = fingerprint(st, "link")
                continue
            snap[rel] = fingerprint(st, "dir")
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if rel == ".git" and not include_git:
                continue
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            kind = "link" if stat.S_ISLNK(st.st_mode) else "file"
            snap[rel] = fingerprint(st, kind)
    if include_parent:
        parent = os.path.dirname(root)
        # The OS temp root is a shared high-churn namespace. Treating every unrelated mktemp as a
        # worker write makes strict mode unusable and still proves no confinement. Real workspaces
        # and nested attack fixtures have a dedicated immediate parent and are measured below.
        if os.path.realpath(parent) == os.path.realpath(tempfile.gettempdir()):
            return snap
        try:
            names = os.listdir(parent)
        except OSError as error:
            raise InputError(f"workspace parent를 측정할 수 없다: {type(error).__name__}")
        own_name = os.path.basename(root)
        for name in names:
            if name == own_name:
                continue
            path = os.path.join(parent, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            kind = "link" if stat.S_ISLNK(st.st_mode) else ("dir" if stat.S_ISDIR(st.st_mode) else "file")
            snap["../" + name] = fingerprint(st, kind)
    return snap


def _under(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def _scope_report(prefixes, before, after, seconds, root=None):
    changed = sorted((set(before) | set(after)) - {p for p in before if p in after and before[p] == after[p]})
    violations = []
    root = root or ROOT
    root_real = os.path.realpath(root)

    def link_escapes(path):
        target_real = os.path.realpath(os.path.join(root, path))
        if not target_real.startswith(root_real + os.sep):
            return True
        target_rel = os.path.relpath(target_real, root_real).replace(os.sep, "/")
        return not any(_under(target_rel, prefix) for prefix in prefixes)

    for path in changed:
        inside = any(_under(path, prefix) for prefix in prefixes)
        if prefixes and not inside:
            violations.append({"path": path, "why": "outside write-prefix"})
    if prefixes:
        # Every symlink that lives under a prefix, changed or not, is a door: a write through a
        # pre-existing link lands outside the snapshot and would otherwise be invisible (review R1).
        # Fail closed: such a link is a violation whenever it points outside the allowed prefixes.
        # A hardlink is the same door without a name: if a file under a prefix has more links than the
        # snapshot can see for its inode, some alias lives outside the workspace (review R8).
        seen = {}
        for entry in after.values():
            if entry[0] == "file":
                key = (entry[5], entry[6])
                seen[key] = seen.get(key, 0) + 1
        for path, entry in after.items():
            if not any(_under(path, prefix) for prefix in prefixes):
                continue
            if entry[0] == "link" and link_escapes(path):
                violations.append({"path": path, "why": "symlink under write-prefix escapes it"})
            elif entry[0] == "file" and entry[7] > seen.get((entry[5], entry[6]), 1):
                violations.append({"path": path, "why": "hardlink under write-prefix has an alias outside the workspace"})
        violations.sort(key=lambda v: v["path"])
    if not prefixes:
        status = "unchecked"
    elif violations:
        status = "scope_violation"
    else:
        status = "ok"
    return {
        "prefixes": list(prefixes),
        "status": status,
        "changed_count": len(changed),
        "changed": changed[:SCOPE_LIST_CAP],
        "violation_count": len(violations),
        "violations": violations[:SCOPE_LIST_CAP],
        "files_scanned": len(after),
        "seconds": round(seconds, 3),
    }


def _git_process(args, cwd, input_bytes=None, timeout=30):
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, input=input_bytes, capture_output=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InputError(f"git 실행 실패: {type(e).__name__}")


def _git_require(args, cwd, input_bytes=None):
    proc = _git_process(args, cwd, input_bytes=input_bytes)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise InputError(f"git {' '.join(args[:2])} 실패: {detail or 'exit ' + str(proc.returncode)}")
    return proc.stdout


def _remove_worktree(worktree):
    proc = _git_process(["worktree", "remove", "--force", worktree], ROOT)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"worktree 정리 실패: {detail or proc.returncode}")


def _prepare_worktree(run_dir, mode):
    base_raw = _git_require(["rev-parse", "HEAD"], ROOT)
    base_rev = base_raw.decode("ascii", errors="strict").strip()
    worktree = os.path.join(run_dir, "wt")
    added = False
    try:
        _git_require(["worktree", "add", "--detach", worktree, "HEAD"], ROOT)
        added = True
        if mode == "dirty":
            dirty = _git_require(["diff", "HEAD", "--binary"], ROOT)
            if dirty:
                _git_require(["apply", "-"], worktree, input_bytes=dirty)
        copied = []
        for rel in WORKTREE_INSTANCE_FILES:
            source = os.path.join(ROOT, rel)
            if not os.path.isfile(source):
                continue
            destination = os.path.join(worktree, rel)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(rel)
        os.makedirs(os.path.join(worktree, "state"), exist_ok=True)
        return os.path.realpath(worktree), {
            "mode": mode,
            "base_rev": base_rev,
            "patch_sha256": None,
            "files": [],
            "added": 0,
            "deleted": 0,
        }, copied
    except BaseException:
        if added:
            _remove_worktree(worktree)
        raise


def _worktree_pathspec(copied):
    return [".", *[f":(exclude){rel}" for rel in copied]]


def _capture_worktree(worktree, run_dir, copied):
    pathspec = _worktree_pathspec(copied)
    raw_untracked = _git_require(
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *pathspec], worktree,
    )
    untracked = sorted(
        p for p in raw_untracked.decode("utf-8", errors="surrogateescape").split("\0") if p
    )
    if untracked:
        _git_require(["add", "-N", "--", *untracked], worktree)
    patch = _git_require(["diff", "HEAD", "--binary", "--", *pathspec], worktree)
    raw_files = _git_require(["diff", "HEAD", "--name-only", "-z", "--", *pathspec], worktree)
    files = sorted(
        p for p in raw_files.decode("utf-8", errors="surrogateescape").split("\0") if p
    )
    numstat = _git_require(["diff", "HEAD", "--numstat", "-z", "--", *pathspec], worktree)
    added = deleted = 0
    fields = numstat.decode("utf-8", errors="surrogateescape").split("\0")
    for field in fields:
        if not field:
            continue
        columns = field.split("\t", 2)
        if len(columns) >= 2:
            if columns[0].isdigit():
                added += int(columns[0])
            if columns[1].isdigit():
                deleted += int(columns[1])
    patch_path = os.path.join(run_dir, "patch.diff")
    untracked_path = os.path.join(run_dir, "untracked.txt")
    _private_write(patch_path, patch)
    _private_write(untracked_path, "".join(f"{path}\n" for path in untracked))
    return {
        "patch_sha256": _sha256(patch_path),
        "files": files,
        "added": added,
        "deleted": deleted,
    }


def _write_meta(path, meta):
    _private_write(path, json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _receipt(meta, result):
    patch_line = ""
    worktree = meta.get("worktree") or {}
    if worktree.get("mode") is not None:
        patch_line = (
            f"patch: {len(worktree['files'])} files "
            f"(+{worktree['added']}/-{worktree['deleted']})\n"
        )
    egress_count = (meta.get("egress") or {}).get("private_ref_count", 0)
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
        f"egress: {egress_count} private refs\n"
        f"scope: {meta['scope']['status']} (changed {meta['scope']['changed_count']}, "
        f"violations {meta['scope']['violation_count']})\n"
        f"{patch_line}"
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


def _run_workspace(runtime, source, body, run_id, run_dir, started, workspace,
                   worktree_meta, copied, egress_refs, egress_source_texts,
                   write_prefixes=(), strict_scope=False, strict_egress=False, batch=None):
    prefixes = [_normalize_prefix(p, root=workspace) for p in write_prefixes]
    rel_run = os.path.relpath(run_dir, ROOT).replace(os.sep, "/")
    for prefix in prefixes:
        # A prefix may not exist yet; create it before the baseline so its own creation is not a
        # change outside itself (review R9). Creating it is the dispatcher's act, not the worker's.
        os.makedirs(os.path.join(workspace, prefix), exist_ok=True)
    t_scope = time.monotonic()
    exclude_rel = rel_run if os.path.realpath(workspace) == os.path.realpath(ROOT) else "__outside__"
    strict_root = os.path.realpath(workspace) == os.path.realpath(ROOT)
    before = _workspace_snapshot(
        exclude_rel, root=workspace, include_git=strict_scope,
        include_parent=(strict_scope and strict_root),
    )
    scope_seconds = time.monotonic() - t_scope
    prompt_path = os.path.join(run_dir, "prompt.md")
    stream_path = os.path.join(run_dir, "stream.jsonl")
    stderr_path = os.path.join(run_dir, "stderr.log")
    result_path = os.path.join(run_dir, "result.txt")
    result_contract_path = os.path.join(run_dir, "result-contract.json")
    runtime_result_path = (os.path.join(workspace, f".mottori-worker-result-{run_id}")
                           if worktree_meta["mode"] is not None else result_path)
    meta_path = os.path.join(run_dir, "meta.json")
    egress_path = os.path.join(run_dir, "egress.log")
    effective = _effective_prompt(runtime, body)
    _private_write(prompt_path, effective)

    capability = CAPABILITIES[runtime]
    command = _claude_command() if runtime == "claude" else _codex_command(runtime_result_path)
    identity = _engine_identity()
    meta = {
        "schema_version": META_SCHEMA_VERSION,
        "run": rel_run,
        "run_id": run_id,
        "runtime": runtime,
        "capability": capability,
        **identity,
        "harness_sha256": _harness_sha256(runtime, command, run_specific=(runtime_result_path,)),
        "usage": {"raw": None, "input": None, "output": None, "total": None},
        "read_scope": None,
        "egress": {
            "private_ref_count": len(egress_refs),
            "private_refs": egress_refs,
            "strict": strict_egress,
            "log": f"{rel_run}/egress.log" if egress_refs else None,
            "event_count": 0,
        },
        "worktree": worktree_meta,
        "scope": {"prefixes": prefixes, "status": "running", "changed_count": 0, "changed": [],
                  "violation_count": 0, "violations": [], "files_scanned": len(before),
                  "seconds": round(scope_seconds, 3)},
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
    if batch is not None:
        meta["batch"] = batch
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
                    cwd=workspace,
                    env=dict(os.environ, MOTTORI_INSTANCE=workspace),
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
    elif runtime == "codex" and os.path.isfile(runtime_result_path):
        result = open(runtime_result_path, encoding="utf-8", errors="replace").read()
        if runtime_result_path != result_path:
            _private_write(result_path, result)
            os.unlink(runtime_result_path)
        else:
            os.chmod(result_path, 0o600)

    _private_write(
        result_contract_path,
        json.dumps(_result_contract(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    egress_events = _egress_events(
        runtime, egress_refs, egress_source_texts, effective, result, rel_run)
    if egress_events:
        _private_write(
            egress_path,
            "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
                    for event in egress_events),
        )

    t_scope = time.monotonic()
    after = _workspace_snapshot(
        exclude_rel, root=workspace, include_git=strict_scope,
        include_parent=(strict_scope and strict_root),
    )
    scope = _scope_report(prefixes, before, after, scope_seconds + (time.monotonic() - t_scope),
                          root=workspace)
    if worktree_meta["mode"] is not None:
        worktree_meta.update(_capture_worktree(workspace, run_dir, copied))

    if strict_scope and scope["status"] == "scope_violation":
        # Post-run detection only: nothing is deleted or rolled back; the paths are on record.
        # A violation outranks the runtime's own exit code (review R3): process_exit stays in meta.
        # Strict mode makes the declared write-prefix an enforcement boundary. Without it the same
        # scope report remains observable but does not replace the runtime result (PRD §10.5).
        wrapper_exit = WRAPPER_SCOPE_VIOLATION
        status_name = "scope_violation"
        if process_exit == 0 and (result is None or not result.strip()):
            result = None
    elif process_exit == 0 and (result is None or not result.strip()):
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
        "usage": _usage(runtime, stream_path),
        "read_scope": _read_scope(result),
        "egress": {
            **meta["egress"],
            "event_count": len(egress_events),
        },
        "scope": scope,
    })
    _write_meta(meta_path, meta)
    return _receipt(meta, result), wrapper_exit


def _batch_identity(batch_manifest, slot, source, body):
    if batch_manifest is None and slot is None:
        return None
    if batch_manifest is None or slot is None:
        raise InputError("--batch-manifest and --slot must be used together")
    try:
        manifest, manifest_sha = B.load_manifest(batch_manifest)
    except B.BatchError as e:
        raise InputError(f"batch manifest rejected: {e}")
    row = next((item for item in manifest["slots"] if item["name"] == slot), None)
    if row is None:
        raise InputError("slot is not present in the batch manifest")
    source_rel = os.path.relpath(source, ROOT).replace(os.sep, "/")
    if source_rel != row["prompt"]:
        raise InputError("prompt path does not match the batch slot")
    prompt_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if prompt_sha != row["prompt_sha256"]:
        raise InputError("prompt SHA does not match the batch slot")
    return {
        "manifest_sha256": manifest_sha,
        "slot": slot,
        "prompt_sha256": prompt_sha,
    }


def run(runtime, prompt_file, write_prefixes=(), strict_scope=False, strict_egress=False,
        worktree_mode=None, batch_manifest=None, slot=None):
    if strict_scope and not write_prefixes:
        raise InputError("--strict-scope에는 하나 이상의 --write-prefix가 필요하다")
    source, body = read_prompt(prompt_file)
    egress_refs = _private_refs(source, body)
    if egress_refs:
        raise InputError(
            "model-send deny ref를 기본 경로에서 거부했다: " + ", ".join(egress_refs))
    egress_source_texts = _private_source_texts(egress_refs)
    batch = _batch_identity(batch_manifest, slot, source, body)
    run_id, run_dir, started = _new_run(runtime)
    workspace = ROOT
    copied = []
    worktree_meta = {
        "mode": None,
        "base_rev": None,
        "patch_sha256": None,
        "files": [],
        "added": 0,
        "deleted": 0,
    }
    if worktree_mode is not None:
        workspace, worktree_meta, copied = _prepare_worktree(run_dir, worktree_mode)
    try:
        receipt, wrapper_exit = _run_workspace(
            runtime, source, body, run_id, run_dir, started, workspace, worktree_meta, copied,
            egress_refs, egress_source_texts, write_prefixes=write_prefixes,
            strict_scope=strict_scope, strict_egress=strict_egress, batch=batch,
        )
    finally:
        if worktree_mode is not None:
            _remove_worktree(workspace)
    sys.stdout.write(receipt)
    return wrapper_exit


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime", required=True, choices=sorted(CAPABILITIES))
    ap.add_argument("--write-prefix", action="append", default=[], metavar="DIR",
                    help="ROOT-relative directory the worker may write under (repeatable). Changes "
                         "outside every prefix are reported after the run. With --strict-scope they "
                         "fail with wrapper exit 4; without a prefix the write-set is unchecked.")
    ap.add_argument("--strict-scope", action="store_true",
                    help="Require at least one --write-prefix and fail on prefix violations. In "
                         "worktree mode scope is measured inside the isolate and the original tree "
                         "is not writable by the worker.")
    ap.add_argument("--strict-egress", action="store_true",
                    help="Compatibility flag. Denied model-send references are always rejected "
                         "before a run is created or a runtime is started.")
    ap.add_argument("--worktree", nargs="?", const="dirty", choices=("head", "dirty"),
                    help="Run in <run>/wt and extract patch.diff plus untracked.txt. 'head' starts "
                         "from HEAD; 'dirty' first applies the original tree's tracked git diff. "
                         "A bare --worktree means dirty.")
    ap.add_argument("--batch-manifest",
                    help="Manifest created by worker_batch.py. Must be paired with --slot; the "
                         "manifest and source prompt hashes are recorded in meta.json v2.")
    ap.add_argument("--slot",
                    help="Expected slot name in --batch-manifest. Does not launch or schedule peers.")
    ap.add_argument("prompt_file")
    args = ap.parse_args(argv)
    try:
        return run(args.runtime, args.prompt_file, write_prefixes=args.write_prefix,
                   strict_scope=args.strict_scope, strict_egress=args.strict_egress,
                   worktree_mode=args.worktree,
                   batch_manifest=args.batch_manifest, slot=args.slot)
    except InputError as e:
        print(f"fresh-worker input rejected: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
