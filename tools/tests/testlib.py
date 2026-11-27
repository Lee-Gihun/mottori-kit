#!/usr/bin/env python3
"""Shared helpers of the regression suites: skip marks, HTTP stand-ins, the gate fixture and a loop source."""

from __future__ import annotations

import contextlib
import functools
import os
import shutil
import sys
from pathlib import Path
from typing import Callable, TypeVar
from unittest.mock import patch


T = TypeVar("T")


def skip_unless(available: Callable[[], bool], needs: str) -> Callable[[Callable[..., T]], Callable[..., T | None]]:
    """Mark a test that needs something this machine or this sandbox may not give. Where available()
    is false the test does not run: it prints one line `- skipped NAME: needs NEEDS` and returns None,
    and the runner counts it as a skip, not a pass."""
    def mark(test: Callable[..., T]) -> Callable[..., T | None]:
        @functools.wraps(test)
        def run(*args: object, **kwargs: object) -> T | None:
            if not available():
                print(f"{SKIP_MARK}{test.__name__}: needs {needs}", flush=True)
                return None
            return test(*args, **kwargs)
        return run
    return mark


# The start of the line a skipped test prints; tools/tests/run.py and the loop's test summary count it.
SKIP_MARK = "- skipped "


def terminal_opens() -> bool:
    """Whether a pseudo-terminal can be opened here; the loop's sandbox denies one."""
    import pty
    try:
        master, slave = pty.openpty()
    except OSError:
        return False
    os.close(master)
    os.close(slave)
    return True


# --- HTTP stand-ins that need no network address ---
# A test registers a stand-in under a loopback port number that nothing listens on. Every Python
# program the test starts while http_stand_ins() is open loads testlib through a sitecustomize module
# on PYTHONPATH, and its socket.create_connection then answers a connection to a registered port
# through a socket pair served by the stand-in's handler inside that program; any other address is
# refused. No address is bound and nothing leaves the process.
STAND_IN_ENV = "MOTTORI_TEST_HTTP_STAND_INS"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_STAND_IN_PORTS = iter(range(47001, 48000))


@contextlib.contextmanager
def http_stand_ins():
    """Open the registry of HTTP stand-ins for this test process and the programs it starts; yields
    its folder. os.environ carries PYTHONPATH and the registry's name, and this process routes its
    connections to the stand-ins, until the block ends."""
    import shutil
    import socket
    import tempfile
    folder = tempfile.mkdtemp(prefix="http-stand-ins-")
    site = os.path.join(folder, "site")
    os.makedirs(site)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(site, "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(f"import sys\nsys.path.append({here!r})\nimport testlib\nsys.path.remove({here!r})\n"
                "testlib.answer_in_process()\n")
    saved = {k: os.environ.get(k) for k in ("PYTHONPATH", STAND_IN_ENV)}
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (site, saved["PYTHONPATH"]) if p)
    os.environ[STAND_IN_ENV] = folder
    own = socket.create_connection
    answer_in_process()
    try:
        yield folder
    finally:
        socket.create_connection = own
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(folder, ignore_errors=True)


def register_stand_in(source_file: str, handler: str, state: str) -> str:
    """Register the class named handler of the module at source_file (a BaseHTTPRequestHandler) as a
    stand-in; its requests see state as self.server.state. Returns the URL root http://127.0.0.1:PORT."""
    import json
    port = next(_STAND_IN_PORTS)
    with open(os.path.join(os.environ[STAND_IN_ENV], f"{port}.json"), "w", encoding="utf-8") as f:
        json.dump({"file": os.path.abspath(source_file), "handler": handler, "state": state}, f)
    return f"http://127.0.0.1:{port}"


def answer_in_process() -> None:
    """Route this program's TCP connections to the registered stand-ins; a no-op outside a registry."""
    import socket
    registry = os.environ.get(STAND_IN_ENV)
    if not registry or getattr(socket.create_connection, "stand_in", False):
        return

    def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **_):
        import errno
        import json
        host, port = address[0], address[1]
        entry = os.path.join(registry, f"{port}.json")
        if host not in LOOPBACK or not os.path.isfile(entry):
            raise ConnectionRefusedError(errno.ECONNREFUSED, f"Connection refused (no stand-in at {host}:{port})")
        with open(entry, encoding="utf-8") as f:
            spec = json.load(f)
        client, served = socket.socketpair()
        client = _PairEnd(client.family, client.type, fileno=client.detach())
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            client.settimeout(timeout)
        import threading
        threading.Thread(target=_serve_one, args=(spec, served), daemon=True).start()
        return client
    connect.stand_in = True
    socket.create_connection = connect


def _stand_in_class(spec):
    import importlib.util
    import sys as _sys
    name = "stand_in_" + os.path.basename(spec["file"])[:-3]
    module = _sys.modules.get(name)
    if module is None:
        loader = importlib.util.spec_from_file_location(name, spec["file"])
        module = importlib.util.module_from_spec(loader)
        _sys.modules[name] = module
        loader.loader.exec_module(module)
    return getattr(module, spec["handler"])


def _serve_one(spec, served):
    """Serve one connection with the stand-in's handler; a client that went away ends it quietly."""
    import types
    try:
        _stand_in_class(spec)(served, ("127.0.0.1", 0), types.SimpleNamespace(state=spec["state"]))
    except OSError:
        pass
    finally:
        served.close()


def _pair_end_class():
    import socket

    class PairEnd(socket.socket):
        """One end of a socket pair that takes the TCP options http.client sets and ignores them."""
        def setsockopt(self, level, *args):  # type: ignore[override]
            if level != socket.IPPROTO_TCP:
                super().setsockopt(level, *args)
    return PairEnd


_PairEnd = _pair_end_class()


_SANDBOX_RUNS: list[bool] = []


def _sandbox_runs() -> bool:
    """Whether macOS's sandbox-exec can start a program here; inside a sandbox it cannot."""
    if not _SANDBOX_RUNS:
        import subprocess
        try:
            ok = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"],
                                capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        _SANDBOX_RUNS.append(ok)
    return _SANDBOX_RUNS[0]


def macos_only(needs: str, sandbox: bool = False) -> Callable[[Callable[..., T]], Callable[..., T | None]]:
    """Mark a test that needs a program only macOS has, named in needs (its sandbox, its scheduler);
    with sandbox, also that sandbox-exec can start a program here, which it cannot inside the loop's
    own sandbox. Where that is missing the test does not run: it prints one line with the reason and
    returns None."""
    def mark(test: Callable[..., T]) -> Callable[..., T | None]:
        @functools.wraps(test)
        def run(*args: object, **kwargs: object) -> T | None:
            if sys.platform != "darwin" or (sandbox and not _sandbox_runs()):
                where = "macOS" if sys.platform != "darwin" else "a sandbox it can start here"
                print(f"{SKIP_MARK}{test.__name__}: needs {where} ({needs})", flush=True)
                return None
            return test(*args, **kwargs)
        return run
    return mark


@contextlib.contextmanager
def gate_stop_fixture(gate, root):
    """Point the gate's Stop markers at a scratch folder.

    Only ESCALATED may be created, because the kit gate has no escalation; a renamed
    marker must fail here rather than leave the gate writing to the real state folder.
    """
    root = Path(root)
    with patch.multiple(gate, EDITS=lambda: str(root / "dirty"),
                        PENDING=lambda: str(root / "pending"), LOCK=lambda: str(root / "lock"),
                        BASELINE=str(root / "baseline.json"),
                        BASELINE_PREV=str(root / "baseline.prev.json"),
                        _root_ok=lambda: True, measure=gate.measure,
                        _load_baseline=gate._load_baseline, _save_baseline=gate._save_baseline), \
            patch.object(gate, "ESCALATED", lambda: str(root / "escalated"), create=True), \
            patch.object(gate.runlog, "log_run", lambda *a, **k: None):
        yield gate


def hook_event(event, payload, step):
    """Run one Claude Code hook event through tools/dispatch.py in this process, with only the
    named step, and return the answer it would print; a step that fails or runs past its budget
    fails the test."""
    import io
    import sys
    import dispatch
    import turns
    steps = [entry for entry in dispatch.STEPS[event] if entry[0] == step]
    assert steps, (event, step)
    # Each call is its own turn here; test_dispatch.py tests the once-per-turn block stamp.
    with patch.dict(dispatch.STEPS, {event: steps}), contextlib.redirect_stderr(io.StringIO()) as err, \
            patch.object(turns, "block_once", lambda *args: args[-1]), \
            patch.object(turns, "count_prompt", lambda *args: []):
        text, status = dispatch.run("claude", event, payload)
    sys.stderr.write(err.getvalue())
    import runlog
    assert status == 0 and "hook failed (" not in err.getvalue() \
        and f"{runlog.HOOK_OVERRAN} (" not in err.getvalue(), err.getvalue()
    return text


# A source of the improvement loop that a test adds to a copied tools/ tree (tools/loop/sources/README.md).
# copy_tools leaves out every source the installation itself added, so a test sees only its own.
LOOP_SOURCE = '''import json
import os

NAME = "notes"
BASE = "_private/notes"
HOME = "_private/notes"
PROGRAM = ["/bin/bash", "tools/loop/notes_cycle.sh"]
SCHEDULE = {"weekday": 0, "hour": 21, "minute": 0}
CYCLE_NAME = r"\\d{4}-\\d{2}-\\d{2}$"
INPUT = "REVIEW.md"
STAGES = ("notes-review",)
KEYS = {"notes_folder": ("notes/", "path", "the folder the notes source reads")}
LOOP_FILES = ("tools/loop/notes_cycle.sh",)
HEAL_GROUPS = {"notes-failed": "notes-cycle"}
FRICTION_SENT = ("Because notes is on too, its proposal worker also reads the notes reviews.",
                 "While notes is off, it reads no notes review.")
COST = "A notes cycle costs one model run."


def material(d):
    return f"- Notes review: `{d}/REVIEW.md`"


def sends(root):
    return ["notes: every file in notes/ goes to the model runtime you use."]


def unusable(cycle_dir):
    return "the notes collection failed" if os.path.exists(os.path.join(cycle_dir, "FAILED")) else None


def watch(root, today, ls, heal_cmds):
    state = os.path.join(root, HOME, "state.json")
    if os.path.isfile(state) and json.load(open(state)).get("status") == "failed":
        heal_cmds["notes-failed"] = ["bash", "tools/loop/notes_cycle.sh", "--force"]
        return [("notes-failed", "notes cycle failed")]
    return []


def friction(root):
    return "Read the latest `_private/notes/*/REVIEW.md` for friction."


def status_note(root):
    return "notes: reads notes/ only"
'''


def copy_tools(src_root, dst_root):
    """Copy src_root/tools to dst_root/tools without tests, caches or the sources the installation added."""
    def ignore(folder, names):
        added = os.path.normpath(folder).endswith(os.path.join("loop", "sources"))
        return {n for n in names if n in ("tests", "__pycache__") or (added and n.endswith(".py"))}
    shutil.copytree(os.path.join(src_root, "tools"), os.path.join(dst_root, "tools"), ignore=ignore)


def add_loop_source(root):
    """Add the notes source and a stand-in cycle script that only says it ran to the tools/ tree at root."""
    folder = os.path.join(root, "tools", "loop", "sources")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "notes.py"), "w", encoding="utf-8") as f:
        f.write(LOOP_SOURCE)
    with open(os.path.join(root, "tools", "loop", "notes_cycle.sh"), "w", encoding="utf-8") as f:
        f.write('echo notes cycle ran with "$@"\n')


def kit_paths(root):
    """The kit's own files under root, from system/dev/kit-files.txt, or None for a tree without the
    list. A test that copies or clones a tree copies these, so an installation's own documents and
    data, which may be large and link to its private area, never enter the copy (KIT-DR-089)."""
    listing = Path(root) / "system" / "dev" / "kit-files.txt"
    if not listing.is_file():
        return None
    return [line for line in listing.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


def engine_tests(names, kit_files):
    """The engine's test files among names (paths below tools/). Where the kit file list names the kit's
    own files, a test an installation added is left out: it reads that installation's own data, which the
    synthetic instance of tools/tests/test_instance_shape.py does not have, and the installation runs it
    in its own tree (KIT-DR-091)."""
    tests = sorted(name for name in names if Path(name).name.startswith("test_") and name.endswith(".py"))
    if kit_files is None:
        return tests
    kit = set(kit_files)
    return [name for name in tests if "tools/" + name in kit]


def copy_kit(src, dst):
    """Copy the kit's own files of src's working tree to dst, keeping modes and links; a tree without
    the list is copied whole, without .git, state, the private area and caches."""
    listed = kit_paths(src)
    if listed is None:
        shutil.copytree(src, dst, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "state", "_private", "__pycache__"))
        return
    for rel in listed:
        source, target = Path(src) / rel, Path(dst) / rel
        if not (source.is_file() or source.is_symlink()):
            continue   # removed in this working tree
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            os.symlink(os.readlink(source), target)
        else:
            shutil.copy2(source, target)


def kit_repo(src, dst):
    """A Git repository at dst whose one commit holds the kit's own files of src's working tree."""
    import subprocess
    copy_kit(src, dst)
    git = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
           "-c", "core.hooksPath=/dev/null"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "kit files"]):
        subprocess.run(git + args, cwd=dst, check=True, capture_output=True)


if __name__ == "__main__":
    # bash tests call: python3 tools/tests/testlib.py kit-repo SRC DST
    if sys.argv[1:2] == ["kit-repo"] and len(sys.argv) == 4:
        kit_repo(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("usage: python3 tools/tests/testlib.py kit-repo SRC DST")
