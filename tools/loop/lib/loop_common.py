#!/usr/bin/env python3
"""Small pieces the improvement loop's modules share: stage errors, hashing, reading and writing files,
a lock file, the run's time budget, process groups, and Git.

Nothing here knows a root folder: every path and working folder comes from the caller."""
import datetime
import hashlib
import json
import os
import posixpath
import signal
import subprocess
import sys
import tempfile
import time

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import safeio  # noqa: E402

# Variables that would point Git at another repository or index than the folder it runs in.
_GIT_PINNING_ENV = {
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX",
}


class StageError(Exception):
    def __init__(self, stage, reason, kind=None):
        super().__init__(f"{stage}: {reason}")
        # kind decides the outcome (e.g. "source-changed" leaves the bundle pending); reason is for people.
        self.stage, self.reason, self.kind = stage, reason, kind


class WorkerUnavailable(StageError):
    """The implementation worker or the run's time budget failed, not the implementation itself."""


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    try:
        with open(path, "rb") as f:
            return sha256_bytes(f.read())
    except OSError:
        return None


def read(path, default=""):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return default


def load_json(path):
    """The JSON object stored at path; a missing, unreadable or non-object file reads as {}."""
    try:
        s = json.loads(read(path, "{}"))
        return s if isinstance(s, dict) else {}
    except json.JSONDecodeError:
        return {}


def normal_path(f):
    """Require normalized relative paths; reject absolute paths, dot components, blanks, backslashes, and control characters."""
    return (isinstance(f, str) and f.strip() == f and f and not f.startswith("/") and "\\" not in f
            and not any(ord(c) < 32 for c in f) and posixpath.normpath(f) == f
            and all(part not in ("", ".", "..") for part in f.split("/")))


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in _GIT_PINNING_ENV}
    env.pop("MOTTORI_INSTANCE", None)
    env.update(extra)
    return env


def git(args, cwd, check=True, input_bytes=None):
    p = subprocess.run(["git", *args], cwd=cwd, env=clean_env(), input=input_bytes,
                       capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: "
                           + p.stderr.decode("utf-8", "replace").strip()[:300])
    return p


def head_sha(root):
    return git(["rev-parse", "HEAD"], root).stdout.decode().strip()


def blob_hash(cwd, path):
    p = git(["hash-object", "--", path], cwd, check=False)
    return p.stdout.decode().strip() if p.returncode == 0 else None


def int_env(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def today():
    return os.environ.get("MOTTORI_APPLY_TODAY") or datetime.date.today().isoformat()


def rel(root, path):
    return os.path.relpath(os.path.abspath(os.path.join(root, path)), root).replace(os.sep, "/")


def write(path, text, mode=0o600):
    """Atomically replace through a temporary file so interruption cannot leave partial content.
    The loop's files are owner-only unless mode says otherwise. A missing folder is made with the
    default mode first: safeio would make a new private folder owner-only, which the loop never did."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    safeio.atomic_write(path, text, mode)


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


_DEADLINE = [None]


def set_deadline(at):
    """Set the run's end (a time.monotonic() value), or clear it with None."""
    _DEADLINE[0] = at


def check_deadline(stage):
    if _DEADLINE[0] is not None and time.monotonic() > _DEADLINE[0]:
        raise WorkerUnavailable(stage, "the run went over its time limit (MOTTORI_APPLY_DEADLINE)")


def remaining(cap):
    if _DEADLINE[0] is None:
        return cap
    return max(1, min(cap, int(_DEADLINE[0] - time.monotonic())))


def stop_group(p):
    """Stop the process group of p: SIGTERM first, so fresh_worker can reap its runtime and remove its
    worktree, then SIGKILL what is left of the group."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        if sig == signal.SIGTERM:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def run_group(cmd, timeout, cwd, env):
    """Run a new process group and terminate its remaining processes on exit or timeout.
    Capture output in a file so an escaped descendant holding a pipe cannot hang collection."""
    with tempfile.TemporaryFile() as out:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out,
                             stderr=subprocess.STDOUT, start_new_session=True)
        timed = False
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed = True
        stop_group(p)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    rc = 124 if timed else p.returncode
    return rc, text, timed


def tool(root, *args):
    """Run tools/<args[0]> of root with the rest as its arguments; True when it ends 0."""
    try:
        p = subprocess.run([sys.executable, os.path.join(root, "tools", args[0]), *args[1:]], cwd=root,
                           env=clean_env(), capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def open_lock(path):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
