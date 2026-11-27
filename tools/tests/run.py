#!/usr/bin/env python3
"""Run the test files that certify this tree, a few side by side, and exit 1 if any failed.

Usage: python3 tools/tests/run.py [--full] [test_name.py ...]

Every test_*.py in this folder runs from the tree root with an empty temporary HOME, stdin from
/dev/null and without the variables in OWNER_ENV, so no test reads the owner's settings or waits on
a terminal. No test can start a real model program: PATH keeps no directory that holds one of
MODEL_PROGRAMS, and the variables that name a program or a model are dropped, so a test that needs
one brings its own stand-in. Up to JOBS files run at once, each in its own process and HOME; their
lines print in the order of the list. Names select a subset. A test that skipped (testlib's skip
helpers) is not a pass: a file with one is counted apart, and each reason is named once.
A Python test file runs through `run.py --one FILE`, which fails the file when a top-level
`def test_` function in it was never called, so a test left out of its file's run list fails.
--full adds the entries that need another command line; one whose file is missing fails, so in a
workspace, which has none of them, --full always fails. This is the one list of suites: CI runs
it instead of keeping its own.
"""
import ast
import functools
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from concurrent.futures import ThreadPoolExecutor

from testlib import SKIP_MARK

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# Messages this module prints in more than one place, or too long to read inline.
TESTS_USAGE = (
    "usage: python3 tools/tests/run.py [--full] [test_name.py ...]\nRuns every test file (or "
    "the named ones) a few side by side; --full adds the entries that need their own command line."
)

# Each of these points a tool at the owner's instance or configuration even under an empty HOME.
# MOTTORI_DISABLE_HOOKS comes from a worker's environment and would switch off the hooks under test.
OWNER_ENV = ("MOTTORI_INSTANCE", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL", "CODEX_HOME", "MOTTORI_DISABLE_HOOKS")
# A real one of these can sign in, spend money or open a window; setup and doctor must find none.
MODEL_PROGRAMS = ("claude", "codex", "agy", "opencode", "ollama", "gemini")
# MOTTORI_ variables that name a program, a command or a model, such as MOTTORI_FRESH_WORKER_CODEX_BIN.
PROGRAM_ENV_PREFIX = "MOTTORI_FRESH_WORKER_"
PROGRAM_ENV_SUFFIXES = ("_BIN", "_CMD", "_MODEL")
# Test files run at once. Each one is a separate process with its own HOME and temporary folders;
# more would crowd the files that themselves start copies side by side.
JOBS = 4
# The name run_one gives its call recorder in a test file's globals.
CALL_MARK = "_mottori_record_call"
# (label, file, arguments, environment): suites whose proof needs a different entry than `python3 FILE`.
FULL = (
    ("test_mutation.py --full", "test_mutation.py", ["--full"], {}),
    ("test_instance_shape.py --full", "test_instance_shape.py", ["--full"], {}),
    ("test_fresh_install.sh", "test_fresh_install.sh", [], {}),
)


def suites(names=(), full=False):
    """Return (label, argv, env) rows; a name that is not a test file here raises ValueError."""
    files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "test_*.py")))
    if not files:
        # An empty folder would otherwise print 0/0 passed and exit 0.
        raise FileNotFoundError(HERE)
    picked = [os.path.basename(n) for n in names]
    unknown = [n for n in picked if n not in files]
    if unknown:
        raise ValueError(", ".join(unknown))
    rows = [(name, one(name), {}) for name in picked or files]
    if full:
        # A deleted entry runs anyway and fails, so the full run cannot quietly shrink.
        rows += [(label, (["bash", os.path.join(HERE, name)] if name.endswith(".sh") else one(name))
                  + args, env) for label, name, args, env in FULL]
    return rows


def one(name):
    """The command line that runs one Python test file through run_one."""
    return [sys.executable, os.path.abspath(__file__), "--one", os.path.join(HERE, name)]


def run_one(path, args):
    """Run one test file as __main__ and return its exit status, 1 when a top-level test function
    was never called.

    Each `def test_NAME` at the top of the file is followed, in the compiled code only, by
    `NAME = <wrapper>(NAME)`, so every later reference (a run list, a call) reaches the wrapper,
    which records the call. A test that a skip helper skipped was still called."""
    path = os.path.abspath(path)
    with open(path, encoding="utf-8") as source:
        tree = ast.parse(source.read(), path)
    called, body = set(), []
    for node in tree.body:
        body.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            mark = ast.parse(f"{node.name} = {CALL_MARK}({node.name!r}, {node.name})").body[0]
            body.append(ast.copy_location(mark, node))
    tree.body = body
    code = compile(ast.fix_missing_locations(tree), path, "exec")

    def record(name, test):
        @functools.wraps(test)
        def run(*a, **k):
            called.add(name)
            return test(*a, **k)
        return run

    module = types.ModuleType("__main__")
    module.__file__ = path
    module.__dict__[CALL_MARK] = record
    sys.modules["__main__"] = module
    sys.argv = [path, *args]
    sys.path[0] = os.path.dirname(path)
    try:
        exec(code, module.__dict__)
        status = 0
    except SystemExit as stop:
        status = stop.code
    defined = [n.name for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name.startswith("test_")]
    never = sorted(set(defined) - called)
    if never:
        print("FAIL never ran: " + ", ".join(never), flush=True)
        return 1
    return status


def dropped(name):
    """True when a variable of the caller's shell must not reach a test."""
    return name in OWNER_ENV or name.startswith(PROGRAM_ENV_PREFIX) or (
        name.startswith("MOTTORI_") and name.endswith(PROGRAM_ENV_SUFFIXES))


def model_free_path(path, links):
    """Return PATH without the directories that hold a model program.

    Each such directory is replaced, in its place, by a folder under links holding a link to each of
    its other programs, so git, node or zstd still resolve and the model programs do not exist.
    """
    kept = []
    for index, folder in enumerate(p for p in path.split(os.pathsep) if p):
        if not any(os.path.lexists(os.path.join(folder, name)) for name in MODEL_PROGRAMS):
            kept.append(folder)
            continue
        target = os.path.join(links, str(index))
        os.mkdir(target)
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        for name in names:
            program = os.path.join(folder, name)
            if name not in MODEL_PROGRAMS and os.path.isfile(program) and os.access(program, os.X_OK):
                os.symlink(program, os.path.join(target, name))
        kept.append(target)
    return os.pathsep.join(kept)


def main(argv):
    if argv[:1] == ["--one"] and len(argv) >= 2:
        return run_one(argv[1], argv[2:])
    if "-h" in argv or "--help" in argv:
        print(TESTS_USAGE)
        return 0
    full = "--full" in argv
    try:
        rows = suites([a for a in argv if a != "--full"], full)
    except ValueError as error:
        print(f"no such test file in tools/tests: {error}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print("no test files in tools/tests", file=sys.stderr)
        return 2
    links = tempfile.mkdtemp(prefix="mottori-test-path-")
    try:
        path = model_free_path(os.environ.get("PATH", os.defpath), links)
        failed_labels, skipped = run_rows(rows, path)
    finally:
        shutil.rmtree(links, ignore_errors=True)
    reasons = {}
    for label, name, needs in skipped:
        reasons.setdefault(needs, {}).setdefault(label, []).append(name)
    for needs, by_file in reasons.items():
        print(f"skipped, needs {needs}: " + "; ".join(f"{label} {', '.join(names)}" for label, names in by_file.items()))
    with_skips = len({label for label, _, _ in skipped})
    passed_with_skips = len({label for label, _, _ in skipped if label not in failed_labels})
    print(f"test files: {len(rows) - len(failed_labels) - passed_with_skips}/{len(rows)} passed"
          + (f", {with_skips} ran with skipped tests ({len(skipped)} skipped)" if skipped else ""))
    return 1 if failed_labels else 0


def skips(output):
    """(test name, what it needs) of each test the output says was skipped."""
    found = []
    for line in output.splitlines():
        if line.startswith(SKIP_MARK) and ": needs " in line:
            name, needs = line[len(SKIP_MARK):].split(": needs ", 1)
            found.append((name, needs))
    return found


def run_rows(rows, path):
    """Run the rows JOBS at a time, print one line per row in list order; return the labels of the
    rows that failed and the (label, test, need) of every skipped test, a failed file's included."""
    failed, skipped = [], []
    with ThreadPoolExecutor(max_workers=JOBS) as pool:
        runs = [pool.submit(run_row, argv_, extra, path) for _, argv_, extra in rows]
        for (label, _, _), run in zip(rows, runs):
            r, seconds = run.result()
            found = skips(r.stdout)
            skipped += [(label, name, needs) for name, needs in found]
            counted = f", {len(found)} skipped)" if found else ")"
            if r.returncode == 0:
                print(f"PASS {label} ({seconds}s" + counted, flush=True)
                continue
            failed.append(label)
            print(f"FAIL {label} (exit {r.returncode}, {seconds}s" + counted, flush=True)
            # Each failed check's own line, then the tail; the whole log would bury the other files'
            # lines. A failed line above the tail was cut off before, which left a CI run unexplained.
            lines = r.stdout.rstrip().splitlines()
            tail = lines[-20:]
            for line in [x for x in lines[:-20] if x.lstrip().startswith("✗")] + tail:
                print("    " + line, flush=True)
            for line in (r.stderr or "").rstrip().splitlines()[-8:]:
                print("    stderr: " + line, flush=True)
    return failed, skipped


def run_row(argv_, extra, path):
    """Run one test file with an empty HOME and the given PATH; return (result, seconds)."""
    home = tempfile.mkdtemp(prefix="mottori-test-home-")
    start = time.monotonic()
    try:
        env = {k: v for k, v in os.environ.items() if not dropped(k)}
        # MOTTORI_NO_LOCAL_PROBE: an embedding server running on this machine must not change what setup does.
        env.update(HOME=home, PATH=path, PYTHONDONTWRITEBYTECODE="1", MOTTORI_NO_LOCAL_PROBE="1", **extra)
        # A test that prints undecodable bytes must still get its pass or fail line.
        r = subprocess.run(argv_, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           errors="replace")
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return r, round(time.monotonic() - start)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
