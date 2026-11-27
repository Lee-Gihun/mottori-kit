#!/usr/bin/env python3
"""Prepare the folder a bounded worker runs in, watch what it writes there, and keep what it changed.

A worker runs in one of three places. The instance is the owner's workspace itself. A copy is a plain
folder outside the instance with its tracked and unignored files, the owner's own folders where Git
cannot list them (paths.owner_files), and nothing the model-send policy denies; it is deleted after
the run. A worktree is a Git worktree inside the run record, started from
HEAD (or HEAD plus the instance's tracked changes), with the instance's own policy files and the
read materials placed in it; what the worker changed there is captured as a patch before it is removed.

fresh_worker.py decides where a run goes and calls these functions. Two pieces of the run record
live here because these functions produce them: InputError, the refusal they raise, and the shapes of
the record's scope entry.
"""
import ctypes
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import uuid

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C  # noqa: E402
import paths as P  # noqa: E402
import safeio  # noqa: E402

WORKER_COPY_INSIDE = (
    "the temporary folder for the worker's copy is inside the workspace; set TMPDIR to a "
    "folder outside it"
)
# Longest list of changed paths, violations or dropped outputs kept in a run record.
SCOPE_LIST_CAP = 500
# Inherited Git control variables that would point nested Git commands at another repository.
GIT_PINNING_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                   "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX")
# Folder names of routine caches: ignored files under them are not listed as dropped.
CACHE_NAMES = frozenset({"cache", "caches", "node_modules", "__pycache__"})
# Path parts an ignored output may not have to be captured.
CAPTURE_RESERVED = CACHE_NAMES | {"_private", "credentials", "credential", "secrets", "secret", "keys"}
# clonefile(2) flag: clone a symlink itself rather than its target.
CLONE_NOFOLLOW = 1


class InputError(ValueError):
    """A request the worker run refuses; fresh_worker.py prints it and exits 2."""


def sha256_file(path):
    """The file's sha256 hex digest, or None when it does not exist."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except FileNotFoundError:
        return None
    return h.hexdigest()


def private_write(path, data):
    """Write bytes atomically with a private mode (0o600 from the first byte)."""
    safeio.atomic_write(path, data, mode=0o600)


def inside(path, root):
    """Whether path, after resolving symlinks, is root or below it."""
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
    except ValueError:
        return False


def root_relative(path, root):
    """path (absolute, or relative to root) as a root-relative path with / separators: "." for root
    itself, None when it is outside root. Lexical: symlinks are not resolved."""
    root = os.path.abspath(root)
    absolute = os.path.abspath(path if os.path.isabs(path) else os.path.join(root, path))
    try:
        rel = os.path.relpath(absolute, root)
    except ValueError:
        return None
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel.replace(os.sep, "/")


def has_symlink_component(root, rel):
    """Whether a component of root/rel below root is a symlink, checked from the top down.
    rel is root-relative with / separators. FileNotFoundError when a component is missing."""
    current = root
    for part in rel.split("/"):
        current = os.path.join(current, part)
        if stat.S_ISLNK(os.lstat(current).st_mode):
            return True
    return False


def git_env():
    """This process's environment without Git pins, so a Git command uses the repository at its cwd."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_PINNING_ENV}
    # Status refreshes must not take index.lock while the owner's own git command runs.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def git_process(args, cwd, input_bytes=None, timeout=30):
    """The finished Git process; InputError when Git cannot run at all."""
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, input=input_bytes, capture_output=True,
            timeout=timeout, check=False, env=git_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InputError(f"git failed to run: {type(e).__name__}")


def git_require(args, cwd, input_bytes=None):
    """Git's stdout bytes; InputError naming the command when it exits nonzero."""
    proc = git_process(args, cwd, input_bytes=input_bytes)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise InputError("git {command} failed: {detail}".format(command=" ".join(args[:2]), detail=detail or "exit " + str(proc.returncode)))
    return proc.stdout


def _under_policy_prefix(path, prefix):
    # Case-blind: on a case-insensitive volume _PRIVATE/x opens the same file as _private/x.
    path, prefix = path.casefold(), prefix.casefold()
    return path == prefix.rstrip("/") or path.startswith(prefix)


def policy_denies(path):
    """Whether the model-send policy keeps this root-relative path from a worker: under a denied
    prefix and under no allowed one."""
    policy = C.egress_model_send()
    return (any(_under_policy_prefix(path, prefix) for prefix in policy["deny_prefixes"])
            and not any(_under_policy_prefix(path, prefix) for prefix in policy["allow_prefixes"]))


def normalize_prefix(prefix, root):
    """A write prefix as a root-relative directory path with no symlink component, spelled as on
    disk. It may not exist yet."""
    rel = root_relative(prefix, root)
    if rel in (None, "."):
        raise InputError("write-prefix is outside the workspace or the whole root")
    current = os.path.abspath(root)
    canonical = []
    parts = rel.split("/")
    for i, part in enumerate(parts):
        part = _disk_spelling(current, part)
        current = os.path.join(current, part)
        canonical.append(part)
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise InputError("write-prefix has a symlink component")
        except FileNotFoundError:
            canonical.extend(parts[i + 1:])
            break  # the rest may be created by the worker
    return "/".join(canonical)


def _disk_spelling(folder, part):
    """The name of part as stored in folder when the file system resolves both to one entry.

    On a case-insensitive file system os.walk reports the stored spelling, so a prefix typed as OUT
    and a folder named out would otherwise be a false violation.
    """
    try:
        entries = os.listdir(folder)
    except OSError:
        entries = []
    if part in entries:
        return part
    # Compare in one Unicode form too: a Korean name may be stored decomposed on disk.
    folded = unicodedata.normalize("NFC", part).casefold()
    same = [e for e in entries if unicodedata.normalize("NFC", e).casefold() == folded]
    if len(same) == 1 and os.path.exists(os.path.join(folder, part)) \
            and os.path.samefile(os.path.join(folder, part), os.path.join(folder, same[0])):
        return same[0]
    return part


def snapshot(root):
    """Metadata fingerprints of every path under root except .git, keyed by root-relative path.

    Only a worktree (<run>/wt) is measured, so the run record is never inside it. lstat does not
    follow symlinks. ctime_ns detects a write that restores mtime, and the mode detects a permission
    change. A fingerprint is (kind, size, mtime_ns, ctime_ns, mode, dev, ino, nlink).
    """
    root = os.path.abspath(root)
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
            if d == ".git":
                continue
            try:
                st = os.lstat(os.path.join(dirpath, d))
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
            if rel == ".git":
                continue
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            snap[rel] = fingerprint(st, "link" if stat.S_ISLNK(st.st_mode) else "file")
    return snap


def under(path, prefix):
    """Whether a root-relative path is prefix or below it."""
    return path == prefix or path.startswith(prefix + "/")


def scope_report(prefixes, before, after, seconds, root):
    """The scope record of a measured run: what changed between two snapshots and which changes
    fall outside every write prefix. It reports; it never changes the run's status."""
    changed = sorted((set(before) | set(after)) - {p for p in before if p in after and before[p] == after[p]})
    violations = []
    if prefixes:
        violations = [{"path": path, "why": "outside write-prefix"} for path in changed
                      if not any(under(path, prefix) for prefix in prefixes)]
        violations += _link_violations(prefixes, after, root)
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


def pending_scope(prefixes, files_scanned, seconds):
    """The scope record while a run is still going."""
    return {"prefixes": prefixes, "status": "running", "changed_count": 0, "changed": [],
            "violation_count": 0, "violations": [], "files_scanned": files_scanned,
            "seconds": round(seconds, 3)}


def unmeasured_scope(prefixes, where):
    """The scope record of a run outside a worktree, where other sessions' edits would be counted
    as the worker's, so nothing is measured."""
    return {"prefixes": prefixes,
            "status": "unchecked (copy)" if where == "copy" else "unchecked (shared workspace)",
            "changed_count": None, "changed": [], "violation_count": None, "violations": [],
            "files_scanned": None, "seconds": 0.0}


def _link_violations(prefixes, after, root):
    """Links under a prefix that reach outside it: a symlink whose target is outside every prefix,
    pre-existing links included, and a hardlink with an alias outside the snapshot."""
    root_real = os.path.realpath(root)

    def link_escapes(path):
        target_real = os.path.realpath(os.path.join(root, path))
        if not inside(target_real, root_real):
            return True
        target_rel = os.path.relpath(target_real, root_real).replace(os.sep, "/")
        return not any(under(target_rel, prefix) for prefix in prefixes)

    seen = {}
    for entry in after.values():
        if entry[0] == "file":
            key = (entry[5], entry[6])
            seen[key] = seen.get(key, 0) + 1
    violations = []
    for path, entry in after.items():
        if not any(under(path, prefix) for prefix in prefixes):
            continue
        if entry[0] == "link" and link_escapes(path):
            violations.append({"path": path, "why": "symlink under write-prefix escapes it"})
        elif entry[0] == "file" and entry[7] > seen.get((entry[5], entry[6]), 1):
            violations.append({"path": path, "why": "hardlink under write-prefix has an alias outside the workspace"})
    return violations


def _clonefile():
    try:
        clone = ctypes.CDLL(None, use_errno=True).clonefile
    except (OSError, AttributeError):
        return None  # not macOS: a plain data copy
    clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
    return clone


_CLONEFILE = _clonefile()


def _copy_file(source, target):
    # An APFS clone shares the source's blocks, so copying a large instance costs no disk space.
    if _CLONEFILE is None or _CLONEFILE(os.fsencode(source), os.fsencode(target), CLONE_NOFOLLOW) != 0:
        shutil.copyfile(source, target)  # another volume or file system
        shutil.copymode(source, target)  # a clone keeps the mode; a data copy must be given it


def prepare_copy(root):
    """Make a copy of the instance at root and return its path.

    The copy holds the tracked files and the untracked files Git does not ignore, as they are on
    disk now, so a draft written this turn is seen. In a kit installation Git ignores every folder
    of the owner's own, so those are found by walking them (paths.owner_files). The copy has no
    .git and no link back: a symlink is left out, and so is any path the model-send policy denies.
    """
    listed = git_require(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], root)
    owned = [os.fsencode(rel) for rel in P.owner_files(root, git_env())]
    copy = os.path.realpath(tempfile.mkdtemp(prefix="mottori-worker-copy-"))
    try:
        if inside(copy, root):
            raise InputError(WORKER_COPY_INSIDE)
        for raw in sorted((set(listed.split(b"\0")) | set(owned)) - {b""}):
            rel = os.fsdecode(raw)
            if policy_denies(rel):
                continue
            source = os.path.join(root, rel)
            if not os.path.isfile(source):
                continue  # a submodule or a tracked file deleted on disk
            if has_symlink_component(root, rel):
                continue  # a symlinked parent folder would bring in what it points at
            target = os.path.join(copy, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _copy_file(source, target)
        return copy
    except BaseException:
        shutil.rmtree(copy, ignore_errors=True)
        raise


def prepare_worktree(root, run_dir, mode, instance_files, read_materials=None):
    """Make the worktree <run_dir>/wt from the instance at root.

    mode "head" starts from HEAD; "dirty" also applies the instance's tracked changes. The instance
    files that exist and the read materials (path to bytes) are then placed in it. Returns the
    worktree's path, its worktree record and the list of placed paths, which capture leaves out.
    """
    base_rev = git_require(["rev-parse", "HEAD"], root).decode("ascii", errors="strict").strip()
    worktree = os.path.join(run_dir, "wt")
    added = False
    try:
        # HEAD can move between rev-parse and worktree creation. Use the revision
        # recorded in the receipt, rather than resolving HEAD a second time.
        git_require(["worktree", "add", "--detach", worktree, base_rev], root)
        added = True
        if mode == "dirty":
            dirty = git_require(["diff", "HEAD", "--binary"], root)
            if dirty:
                # Staged in the disposable index, so the start tree below includes the inherited
                # changes and a worker edit that restores HEAD still shows in the patch.
                git_require(["apply", "--index", "-"], worktree, input_bytes=dirty)
        base_tree = git_require(["write-tree"], worktree).decode("ascii", errors="strict").strip()
        placed = []
        instance_sha256 = {rel: None for rel in instance_files}
        for rel in instance_files:
            source = os.path.join(root, rel)
            if not os.path.isfile(source):
                continue
            destination = os.path.join(worktree, rel)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            placed.append(rel)
            instance_sha256[rel] = sha256_file(destination)
        os.makedirs(P.state(worktree), exist_ok=True)
        material_sha256 = copy_read_materials(worktree, read_materials or {})
        placed.extend(material_sha256)
        return os.path.realpath(worktree), {
            "mode": mode,
            "base_rev": base_rev,
            "base_tree": base_tree,
            "instance_sha256": instance_sha256,
            "material_sha256": material_sha256,
            "material_integrity": True,
            "patch_sha256": None,
            "files": [],
            "added": 0,
            "deleted": 0,
        }, placed
    except BaseException:
        if added:
            try:
                remove_worktree(root, worktree)
            except RuntimeError:
                pass  # the original refusal is what the caller must see
        raise


def remove_worktree(root, worktree):
    """Remove a worktree of the repository at root; RuntimeError when Git refuses."""
    proc = git_process(["worktree", "remove", "--force", worktree], root)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"worktree cleanup failed: {(detail or proc.returncode)}")


def copy_read_materials(worktree, snapshots):
    """Write each read material (path to bytes) read-only at its path in the worktree; return their
    sha256 by path. A material may not replace a file the worktree already has."""
    hashes = {}
    for rel, raw in snapshots.items():
        current = worktree
        for part in rel.split("/")[:-1]:
            current = os.path.join(current, part)
            if os.path.lexists(current):
                if os.path.islink(current) or not os.path.isdir(current):
                    raise InputError("read material destination has a non-directory component: " + rel)
            else:
                os.mkdir(current, 0o700)
        target = os.path.join(worktree, rel)
        if os.path.lexists(target):
            raise InputError("read material cannot shadow a worktree source file: " + rel)
        private_write(target, raw)
        os.chmod(target, 0o400)
        hashes[rel] = hashlib.sha256(raw).hexdigest()
    return hashes


def read_material_violations(worktree, hashes):
    """The read materials the worker changed, replaced with a link, or removed."""
    changed = []
    for rel, expected in hashes.items():
        try:
            linked = has_symlink_component(worktree, rel)
        except OSError:
            linked = False  # a missing component: the file check below reports it
        path = os.path.join(worktree, rel)
        if linked or not os.path.isfile(path) or sha256_file(path) != expected:
            changed.append(rel)
    return changed


def _capture_exclusion(rel, entry):
    """Why an ignored output is not captured, or None. A conservative export rule, not a sandbox."""
    parts = rel.split("/")
    if any(p.startswith(".") or p.lower() in CAPTURE_RESERVED for p in parts):
        return "private, hidden, credential, or cache path"
    name = parts[-1].lower()
    if (name.startswith(("credentials.", "credential.", "secrets.", "secret.", "id_rsa", "id_ed25519"))
            or name.endswith((".pem", ".key", ".p12", ".pfx", ".keychain"))):
        return "credential-shaped filename"
    if any(ord(c) < 32 for c in rel):
        return "filename is not representable in the line-delimited artifact list"
    if entry[0] != "file" or entry[7] != 1:
        return "output is not a single-link regular file"
    return None


def _read_capture_output(worktree, rel):
    if has_symlink_component(worktree, rel):
        raise InputError("symlink encountered during output capture")
    fd = os.open(os.path.join(worktree, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise InputError("output capture requires a single-link regular file")
        return stream.read()


def _ignored_paths(worktree, candidates):
    """The subset of candidate paths that Git ignores in the worktree."""
    if not candidates:
        return []
    result = git_process(["check-ignore", "--stdin", "-z"], worktree,
                         input_bytes=b"\0".join(os.fsencode(p) for p in candidates) + b"\0")
    if result.returncode not in (0, 1):
        raise InputError("ignored output discovery failed")
    if ((result.returncode == 0 and (not result.stdout or not result.stdout.endswith(b"\0")))
            or (result.returncode == 1 and result.stdout)):
        raise InputError("ignored output discovery returned an incomplete listing")
    ignored = sorted(os.fsdecode(p) for p in result.stdout.split(b"\0") if p)
    if not set(ignored).issubset(candidates):
        raise InputError("ignored output discovery returned an unexpected path")
    return ignored


def _require_utf8_names(paths):
    # The artifact list and run record are UTF-8; refuse here instead of failing mid-write.
    for path in paths:
        try:
            path.encode("utf-8")
        except UnicodeEncodeError:
            raise InputError("output file name is not UTF-8: " + ascii(path))


def _nul_list(raw):
    return sorted(p for p in raw.decode("utf-8", errors="surrogateescape").split("\0") if p)


def _dropped_outputs(worktree, changed):
    """(ignored outputs the cleanup will delete, why that list is unavailable or None).

    Used without a prefix, when nothing ignored is captured. Caches from test runs are routine, so
    they are left out. The list only informs: when Git cannot answer (for example for a path inside
    an embedded repository), the reason is recorded and the capture goes on.
    """
    try:
        return _ignored_paths(worktree, sorted(
            path for path in changed if not any(part in CACHE_NAMES for part in path.split("/")))), None
    except InputError as error:
        return [], str(error)


def _copy_ignored_outputs(worktree, run_dir, ignored, after):
    """Copy each ignored output that passes the export rule to <run_dir>/untracked.

    Returns (captured paths, skipped paths with why, sha256 by captured path).
    """
    captured, skipped, output_hashes = [], [], {}
    for rel in ignored:
        reason = _capture_exclusion(rel, after[rel])
        if reason:
            skipped.append({"path": rel, "why": reason})
            continue
        raw = _read_capture_output(worktree, rel)
        parent = run_dir
        for part in ("untracked", *rel.split("/")[:-1]):
            parent = os.path.join(parent, part)
            try:
                os.mkdir(parent, 0o700)
            except FileExistsError:
                if not stat.S_ISDIR(os.lstat(parent).st_mode):
                    raise InputError("artifact destination has a non-directory component")
        destination = os.path.join(parent, rel.split("/")[-1])
        private_write(destination, raw)
        digest = hashlib.sha256(raw).hexdigest()
        if sha256_file(destination) != digest:
            raise InputError("captured output hash mismatch")
        captured.append(rel)
        output_hashes[rel] = digest
    return captured, skipped, output_hashes


def _build_patch(worktree, pathspec, captured, base_tree):
    """(patch bytes, changed file names, untracked file names) against the start tree.

    Untracked files and the captured ignored outputs are marked intent-to-add first, so the patch
    holds them as new files. That marking changes only the disposable worktree index.
    """
    untracked = _nul_list(git_require(
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *pathspec], worktree))
    _require_utf8_names(untracked)
    if untracked:
        git_require(["add", "-N", "--", *untracked], worktree)
    if captured:
        git_require(["add", "-N", "-f", "--", *captured], worktree)
        untracked = sorted(set(untracked) | set(captured))
    # The patch is against the tree the worker started from, not HEAD: in dirty mode they differ.
    base = base_tree or "HEAD"
    patch = git_require(["diff", base, "--binary", "--", *pathspec], worktree)
    files = _nul_list(git_require(["diff", base, "--name-only", "-z", "--", *pathspec], worktree))
    _require_utf8_names(files)
    return patch, files, untracked


def _count_numstat(worktree, pathspec, base_tree):
    """(lines added, lines deleted) against the start tree; binary files count zero."""
    numstat = git_require(["diff", base_tree or "HEAD", "--numstat", "-z", "--", *pathspec], worktree)
    added = deleted = 0
    for field in numstat.decode("utf-8", errors="surrogateescape").split("\0"):
        columns = field.split("\t", 2) if field else []
        if len(columns) >= 2:
            added += int(columns[0]) if columns[0].isdigit() else 0
            deleted += int(columns[1]) if columns[1].isdigit() else 0
    return added, deleted


def capture_worktree(worktree, run_dir, placed, prefixes=(), before=None, after=None, base_tree=None):
    """Keep what the worker changed in the worktree before it is removed: patch.diff, untracked.txt,
    and the ignored outputs under a write prefix in <run_dir>/untracked. Returns the fields that
    update the run's worktree record."""
    before, after = before or {}, after or {}
    changed = [path for path, entry in after.items()
               if entry[0] != "dir" and before.get(path) != entry and path not in placed]
    candidates = sorted(path for path in changed if any(under(path, p) for p in prefixes))
    ignored = _ignored_paths(worktree, candidates)
    dropped, dropped_error = ([], None) if prefixes else _dropped_outputs(worktree, changed)
    captured, skipped, output_hashes = _copy_ignored_outputs(worktree, run_dir, ignored, after)
    # literal: a name with glob characters must not also exclude worker outputs it would match.
    pathspec = [".", *[f":(exclude,literal){rel}" for rel in placed]]
    patch, files, untracked = _build_patch(worktree, pathspec, captured, base_tree)
    added, deleted = _count_numstat(worktree, pathspec, base_tree)
    patch_path = os.path.join(run_dir, "patch.diff")
    private_write(patch_path, patch)
    private_write(os.path.join(run_dir, "untracked.txt"), "".join(f"{path}\n" for path in untracked))
    for rel, digest in output_hashes.items():
        if hashlib.sha256(_read_capture_output(worktree, rel)).hexdigest() != digest:
            raise InputError("output changed during capture")
    return {
        "capture_status": "incomplete" if skipped else "complete",
        "ignored_captured": captured,
        "ignored_dropped": dropped[:SCOPE_LIST_CAP],
        "ignored_dropped_count": len(dropped),
        "ignored_dropped_error": dropped_error,
        "capture_skipped": skipped,
        "output_sha256": output_hashes,
        "patch_sha256": sha256_file(patch_path),
        "files": files,
        "added": added,
        "deleted": deleted,
    }


def mark_uncaptured(expect_report, worktree, worktree_meta):
    """Add to an expect report each expected output a worktree run did not carry out.

    Only the patch and the captured ignored outputs outlive a worktree.
    """
    exported = set(worktree_meta.get("files") or ()) | set(worktree_meta.get("ignored_captured") or ())
    missing_paths = {item["path"] for item in expect_report["missing"]}
    for rel in expect_report["paths"]:
        if rel in missing_paths or rel in exported:
            continue
        # A path that exists unchanged in the start tree is already in the owner's tree.
        start = worktree_meta.get("base_tree") or worktree_meta["base_rev"]
        at_base = git_process(["cat-file", "-e", f"{start}:{rel}"], worktree)
        if at_base.returncode == 0:
            continue
        expect_report["missing"].append({"path": rel, "why": "not captured from worktree"})
    expect_report["present"] = len(expect_report["paths"]) - len(expect_report["missing"])
    return expect_report
