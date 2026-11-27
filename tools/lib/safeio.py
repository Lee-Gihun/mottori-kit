#!/usr/bin/env python3
"""Write a file atomically, hold a lock file, and name a file by the hash of its bytes.

These are the file primitives every tool shares. Importing this module reads no file."""
import contextlib
import hashlib
import os
import sys
import tempfile
import time

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths  # noqa: E402


class StateLockTimeout(TimeoutError):
    pass


def fsync_parent(path):
    """Make a rename or unlink of path durable."""
    try:
        dfd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass  # Some filesystems lack directory fsync; the rename itself is still atomic.


def new_file_mode(path):
    """The mode a file the tools create gets: owner-only in a private area, 0o644 elsewhere."""
    return 0o600 if paths.is_private(path) else 0o644


def make_parent(path):
    """Create the folder of path; a folder created inside a private area is owner-only."""
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700 if paths.is_private(path) else 0o777, exist_ok=True)


def open_append(path):
    """Open path for appending text, creating it with the mode of new_file_mode()."""
    make_parent(path)
    return open(path, "a", encoding="utf-8",
                opener=lambda name, flags: os.open(name, flags, new_file_mode(name)))


def atomic_write(path, text, mode=None):
    """Replace path with text through an fsynced sibling temporary file.

    The file keeps its mode unless mode is given. A new file is readable by its owner only when
    it lies in a private area (paths.is_private) and by everyone otherwise; the temporary file has
    that mode before any byte is written. A failed write leaves the previous complete file. text
    may be bytes, written as they are."""
    parent = os.path.dirname(path)
    make_parent(path)
    if mode is None:
        mode = os.stat(path).st_mode & 0o777 if os.path.isfile(path) else new_file_mode(path)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
        fsync_parent(path)
    finally:
        if fd != -1:
            os.close(fd)
        if tmp is not None:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


@contextlib.contextmanager
def locked(path, timeout=10.0):
    """Hold an exclusive lock on the file at path, waiting at most timeout seconds."""
    import fcntl
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise StateLockTimeout(f"state lock timeout: {path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def file_fingerprint(path, missing_marker=b"<missing>"):
    """The SHA-256 of a file's bytes, or of a marker when it is missing or unreadable."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        raw = missing_marker
    except OSError as e:
        raw = f"<unreadable:{type(e).__name__}>".encode()
    return hashlib.sha256(raw).hexdigest()
