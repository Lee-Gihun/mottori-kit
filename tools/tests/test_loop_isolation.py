#!/usr/bin/env python3
"""The sandbox the loop tests a candidate in: what a program inside one start can and cannot do, and
that nothing it does reaches the rules of the next start."""
import os
import re
import shutil
import subprocess
import sys
import tempfile

from testlib import macos_only

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_checks as LK  # noqa: E402
import loop_isolate as LI  # noqa: E402

SANDBOX = "the sandbox a candidate is tested in"
# A program that replaces every sandbox rule file it can find near its HOME with one that allows all.
OVERWRITE_RULES = r"""
import glob, os
top = os.path.dirname(os.environ["HOME"])
for path in glob.glob(os.path.join(top, "**", "*.sb"), recursive=True):
    try:
        open(path, "w").write("(version 1)\n(allow default)\n")
        print("rewrote", path)
    except OSError as error:
        print("could not rewrite", path, error)
"""
WRITE_MARKER = "import sys; open(sys.argv[1], 'w').write('escaped')"


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


def repo(base):
    """A Git repository with one commit holding two test files: the first rewrites the rules, the
    second writes the marker file named in its argument list."""
    root = os.path.join(base, "root")
    os.makedirs(os.path.join(root, "tools", "tests"))
    with open(os.path.join(root, "tools", "tests", "test_a_rules.py"), "w") as f:
        f.write(OVERWRITE_RULES)
    with open(os.path.join(root, "tools", "tests", "test_b_marker.py"), "w") as f:
        f.write(f"open({os.path.join(base, 'outside', 'marker')!r}, 'w').write('escaped')\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


@macos_only(SANDBOX, sandbox=True)
def test_a_start_cannot_change_the_rules_of_the_next_start():
    base = os.path.realpath(tempfile.mkdtemp(prefix="loop-iso-rules-"))
    try:
        root = repo(base)
        os.makedirs(os.path.join(base, "outside"))
        marker = os.path.join(base, "outside", "marker")
        sha = git(root, "rev-parse", "HEAD").strip()
        with LI.Isolate(sha, root) as iso:
            first = subprocess.run(iso.command([sys.executable, "-c", OVERWRITE_RULES]), env=iso.env(),
                                   cwd=iso.tree, capture_output=True, text=True)
            second = subprocess.run(iso.command([sys.executable, "-c", WRITE_MARKER, marker]), env=iso.env(),
                                    cwd=iso.tree, capture_output=True, text=True)
        assert not os.path.exists(marker), ("a later start wrote outside its folder", first.stdout, second.stderr)
        assert second.returncode != 0, second.stdout + second.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_rules_deny_by_default():
    """Asserted on the text for the ways out no harmless probe can show: Apple events, launch
    services and job creation are never allowed, and nothing allows the network."""
    rules = LI.sandbox_profile("/w", root="/r", home="/h")
    lines = rules.splitlines()
    assert lines[:2] == ["(version 1)", "(deny default)"], lines[:2]
    for allowed in ("(allow default", "(allow network", "(allow appleevent", "(allow lsopen",
                    "(allow job-creation", "(allow iokit", "(allow ipc-posix-shm", "(allow system-socket"):
        assert allowed not in rules, allowed
    # One Mach service may be looked up, by its name: where the per-user temporary folder is.
    lookups = [line for line in lines if line.startswith("(allow mach")]
    assert lookups == ['(allow mach-lookup (global-name "com.apple.bsd.dirhelper"))'], lookups


PROBE = r"""
import ctypes, errno, os, socket, sys
what, arg = sys.argv[1], sys.argv[2:]
try:
    if what == "read":
        open(arg[0]).read()
    elif what == "write":
        open(arg[0], "w").write("x")
    elif what == "connect":
        family = socket.AF_INET6 if ":" in arg[0] else socket.AF_INET
        s = socket.socket(family)
        s.settimeout(2)
        s.connect((arg[0], int(arg[1])))
    elif what == "terminal":
        os.openpty()
    elif what == "lookup":
        # Asks the bootstrap server for a send right to a service; it starts nothing and sends nothing.
        lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
        port = ctypes.c_uint32()
        bootstrap = ctypes.c_uint32.in_dll(lib, "bootstrap_port")
        kr = lib.bootstrap_look_up(bootstrap, arg[0].encode(), ctypes.byref(port))
        if kr != 0:
            raise PermissionError(kr, "lookup refused")
    print("allowed")
except OSError as error:
    print("denied" if error.errno in (errno.EPERM, errno.EACCES) or what == "lookup" else
          f"other {error.errno} {error}")
"""


@macos_only(SANDBOX, sandbox=True)
def test_from_inside_only_the_run_folder_and_nothing_outside_the_sandbox():
    base = os.path.realpath(tempfile.mkdtemp(prefix="loop-iso-inside-"))
    try:
        home, root, run, outside = (os.path.join(base, n) for n in ("home", "root", "run", "outside"))
        for d in (home + "/Documents", home + "/.ssh", root + "/_private", run, outside):
            os.makedirs(d)
        for f in (home + "/Documents/secret.txt", home + "/.ssh/id", root + "/_private/s.md", root + "/public.md"):
            with open(f, "w") as out:
                out.write("secret")
        rules = LI.sandbox_profile(run, root=root, home=home)

        def inside(*args):
            p = subprocess.run(LI.sandboxed(rules, [sys.executable, "-c", PROBE, *args]),
                               capture_output=True, text=True, env=LI.sandbox_env(run, run), cwd=run)
            return (p.stdout.strip() or p.stderr.strip()[-200:])
        seen = {args: inside(*args) for args in (
            ("read", home + "/Documents/secret.txt"), ("read", home + "/.ssh/id"), ("read", root + "/public.md"),
            ("write", outside + "/x"), ("write", run + "/x"),
            ("connect", "127.0.0.1", "9"), ("connect", "::1", "9"), ("connect", "192.0.2.1", "9"),
            ("terminal",), ("lookup", "com.apple.coreservices.launchservicesd"))}
        want = {args: "allowed" if args == ("write", run + "/x") else "denied" for args in seen}
        assert seen == want, {k: v for k, v in seen.items() if v != want[k]}
        assert not os.path.exists(outside + "/x")
    finally:
        shutil.rmtree(base, ignore_errors=True)


LISTENERS = re.compile(r"HTTPServer|\.bind\(\(")


def test_no_test_file_serves_on_a_network_address():
    """A test that serves on an address fails in the loop's sandbox, which denies every address."""
    here = os.path.dirname(os.path.abspath(__file__))
    serving = []
    for name in sorted(os.listdir(here)):
        if name.startswith("test_") and name.endswith(".py") and name != os.path.basename(__file__):
            with open(os.path.join(here, name), encoding="utf-8") as f:
                serving += [f"{name}:{n}" for n, line in enumerate(f, 1)
                            if LISTENERS.search(line)]
    assert not serving, serving


@macos_only(SANDBOX, sandbox=True)
def test_the_files_that_served_on_loopback_pass_in_the_sandbox():
    """Run in the loop's own sandbox, as its test stage runs them, both files end with exit 0; a test
    that needs a terminal is counted as skipped there."""
    root = os.path.dirname(TOOLS)
    sha, _ = LI.build_snapshot(root)
    try:
        with LI.Isolate(sha, root) as iso:
            res = LK.run_tests(iso, [os.path.join(iso.tree, "tools", "tests", n)
                                     for n in ("test_options.py", "test_recall_store.py")])
    finally:
        LI.cleanup_snapshots()
    assert all(r["rc"] == 0 for r in res.values()), {n: (r["rc"], r["fails"][:3], r["tail"]) for n, r in res.items()}


TESTS = [
    test_a_start_cannot_change_the_rules_of_the_next_start,
    test_no_test_file_serves_on_a_network_address,
    test_the_rules_deny_by_default,
    test_from_inside_only_the_run_folder_and_nothing_outside_the_sandbox,
    test_the_files_that_served_on_loopback_pass_in_the_sandbox,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"loop_isolation: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
