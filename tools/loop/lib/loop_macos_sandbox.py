#!/usr/bin/env python3
"""Runs a program on this Mac in sandbox-exec with a profile that denies everything it does not
allow: writes in one folder only, reads of that folder, the folders it is given, the toolchain and the
system's own files, and no network, no terminal and no service outside the sandbox."""
import os
import shutil
import subprocess
import sys

_DEVELOPER_TOOLS = []
_TOOLCHAIN = []

# What the sandboxed runs were measured to need beyond the run's folder, the readable folders and the
# toolchain, each with what needs it. Everything else is denied: other files of the owner, the
# network, pseudo-terminals, and every service outside the sandbox but one (so no launch services,
# job creation or Apple events).
SYSTEM_READS = (
    "/System",              # the system's libraries and frameworks every program loads
    "/usr/lib",             # libraries outside the shared cache (xcodebuild's libobjc-trampolines)
    "/usr/share",           # locale data (Python's locale module in the tests)
    "/usr/bin", "/bin",     # sh, bash, env, tr, git and python3 started by the tests
    "/private/etc/localtime", "/private/var/db/timezone",   # the local time zone (else UTC)
    "/private/var/select",  # the links /bin/sh and the /usr/bin shims (python3, git) follow
    # The /usr/bin shims fall back to xcodebuild when their lookup cache was made for another HOME,
    # which every test's fresh HOME is; xcodebuild first checks the Xcode licence recorded here.
    "/Library/Preferences/com.apple.dt.Xcode.plist",
    "/usr/sbin/sysctl",     # tools/tasks.py reads the boot time with it (test_tasks.py)
)
# The one service outside the sandbox a program may ask: where the per-user temporary folder is. The
# /usr/bin shims ask it for their lookup cache; without the answer every call of one runs
# xcodebuild for two seconds instead of a tenth of one (test_instance_tools.py times its watcher).
MACH_SERVICE = "com.apple.bsd.dirhelper"
DEVICES = ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom", "/dev/dtracehelper")


def _quote(path):
    return path.replace("\\", "\\\\").replace('"', '\\"')


def _subpaths(paths):
    return " ".join(f'(subpath "{_quote(p)}")' for p in paths)


def _ancestors(paths):
    """Every folder above each path: programs look at them (realpath, getcwd) to find the path."""
    out = {"/", "/var", "/etc", "/tmp"}   # the links to /private every temporary path goes through
    for p in paths:
        while p not in ("/", ""):
            p = os.path.dirname(p)
            out.add(p)
    return sorted(out)


def toolchain():
    """The folders of the Python and the Git that run here, and of the developer tools, real paths."""
    if not _TOOLCHAIN:
        found = {os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix)}
        # The folder the interpreter really runs from, which command() starts it by: in some
        # installations it is not under the prefix.
        for exe in {sys.executable, getattr(sys, "_base_executable", sys.executable)}:
            if exe:
                found.add(os.path.dirname(os.path.realpath(exe)))
        tools = extra_path()
        if tools:
            developer = os.path.realpath(os.path.dirname(os.path.dirname(tools)))
            # Inside Xcode the /usr/bin shims also load from the rest of the application bundle.
            app = os.path.dirname(os.path.dirname(developer))
            found.add(app if app.endswith(".app") else developer)
            # The shims' lookup cache in the per-user temporary folder (tool paths), read only.
            try:
                p = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True, text=True, timeout=10)
                if p.returncode == 0 and p.stdout.strip():
                    found.add(os.path.join(os.path.realpath(p.stdout.strip()), "xcrun_db"))
            except (OSError, subprocess.SubprocessError):
                pass
        git = shutil.which("git")
        if git:
            found.add(os.path.dirname(os.path.realpath(git)))
            p = subprocess.run([git, "--exec-path"], capture_output=True, text=True, timeout=10)
            if p.returncode == 0 and p.stdout.strip():
                found.add(os.path.realpath(p.stdout.strip()))
        _TOOLCHAIN.extend(sorted(found))
    return list(_TOOLCHAIN)


def profile(writable, readable, secret):
    """The sandbox profile: deny by default; read and write under writable, read under each path of
    readable, the toolchain and SYSTEM_READS, never under a path of secret; no network of any kind."""
    reads = [writable, *readable, *toolchain(), *SYSTEM_READS]
    devices = " ".join(f'(literal "{d}")' for d in DEVICES)
    metadata = " ".join(f'(literal "{_quote(p)}")' for p in _ancestors(reads))
    return f"""(version 1)
(deny default)
(allow process-fork)
(allow process-exec {_subpaths(reads)})
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow ipc-posix-sem)
(allow mach-lookup (global-name "{MACH_SERVICE}"))
(allow file-read-metadata {metadata})
(allow file-read* (literal "/") {_subpaths(reads)} {devices} (literal "/dev/fd") (regex #"^/dev/fd/"))
(allow file-write* (subpath "{_quote(writable)}") {devices} (regex #"^/dev/fd/"))
(deny file-read* file-write* {_subpaths(secret)})
"""


def program():
    """The sandbox-exec program, or None when this Mac has none."""
    return shutil.which("sandbox-exec") or ("/usr/bin/sandbox-exec" if os.path.exists("/usr/bin/sandbox-exec") else None)


def command(rules, argv):
    """argv run under the profile text rules, or None when there is no sandbox program. The text goes
    on the command line, so no file a sandboxed program could rewrite decides what a later start may do."""
    sbx = program()
    if not sbx:
        return None
    # A program named by a link is started by its real path. The rules allow real paths only, and
    # following a link means reading it: Homebrew's python3 is a link in /opt/homebrew/opt, and the
    # sandbox refused to start it ("execvp() ... Operation not permitted"), so on a Mac whose loop runs
    # Homebrew's Python every test failed before any change was made.
    exe = os.path.realpath(argv[0]) if argv and os.path.isabs(argv[0]) else argv[0] if argv else None
    return [sbx, "-p", rules, *([exe] if argv else []), *argv[1:]]


def extra_path():
    """The folder of the developer tools that macOS's /usr/bin shims (git, python3) start through xcrun,
    or None. Inside the sandbox a shim cannot write xcrun's lookup cache in the per-user temporary
    folder and says so on stderr at every call; the same tools run quietly from their own folder."""
    if not _DEVELOPER_TOOLS:
        try:
            p = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, timeout=10)
            folder = os.path.join(p.stdout.strip(), "usr", "bin") if p.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            folder = ""
        _DEVELOPER_TOOLS.append(folder if folder and os.path.isdir(folder) else None)
    return _DEVELOPER_TOOLS[0]
