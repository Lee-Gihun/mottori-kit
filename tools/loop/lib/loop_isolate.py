#!/usr/bin/env python3
"""Builds the isolated place a candidate is tested in: a temporary clone pinned to a base commit, the
sandbox that lets tests write only there with their own HOME and TMPDIR and no network, and the
snapshot commit of the working tree a clone can be pinned to.

A root argument names the working tree; without it, the tree this file lives in."""
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402
import loop_platform  # noqa: E402
import loop_policy  # noqa: E402
from loop_common import StageError, clean_env, git, head_sha, normal_path, sha256_bytes  # noqa: E402
from loop_edits import safe_target, write_nofollow  # noqa: E402
from loop_stores import PRIVATE  # noqa: E402

_SNAPSHOT_REPOS = {}   # snapshot commit -> temporary repository that holds it
_SECRET_ENV = re.compile(r"TOKEN|SECRET|PASSWORD|API_KEY|_KEY$|CREDENTIAL", re.I)


def sandbox_profile(writable, root=None, home=None, readable=()):
    """Model-written tests may write only in `writable` and read only there, under `readable`, the
    toolchain and the system's files. The private area and the agent and ssh folders of the real home
    stay denied even inside a readable folder (HOME inside the sandbox is a fake one), because test
    output is saved and handed to an external reviewer."""
    home = os.path.realpath(home or pwd.getpwuid(os.getuid()).pw_dir)
    secret = [os.path.join(os.path.realpath(root or ROOT), PRIVATE)] + \
             [os.path.join(home, d) for d in (".claude", ".codex", ".ssh")]
    return loop_platform.module("sandbox").profile(writable, [os.path.realpath(p) for p in readable], secret)


def object_stores(repo):
    """The object folders a shared clone at repo reads: its own and, through each alternates file,
    those of the repositories it was cloned from."""
    out, todo = [], [os.path.join(repo, ".git", "objects")]
    while todo:
        store = os.path.realpath(todo.pop())
        if store in out:
            continue
        out.append(store)
        try:
            with open(os.path.join(store, "info", "alternates"), encoding="utf-8") as f:
                todo += [os.path.join(store, line.strip()) for line in f if line.strip() and not line.startswith("#")]
        except OSError:
            pass
    return out


# Variables model-written tests may inherit. An allowlist, because secret names (SSH_AUTH_SOCK, GH_PAT,
# SLACK_WEBHOOK_URL) do not follow one pattern; everything the sandbox needs is set explicitly below.
_SANDBOX_ENV_KEEP = ("PATH", "LANG", "LANGUAGE", "TERM", "TZ", "USER", "LOGNAME", "SHELL",
                     "PYTHONIOENCODING", "PYTHONUTF8", "__CF_USER_TEXT_ENCODING")


def sandboxed(rules, argv, stage="verify"):
    """argv run in the platform's sandbox under the profile text rules; raises StageError without a sandbox."""
    cmd = loop_platform.module("sandbox").command(rules, argv)
    if not cmd:
        raise StageError(stage, "the sandbox program is missing: candidate tests do not run without isolation")
    return cmd


def sandbox_env(home, tmpdir):
    env = {k: v for k, v in clean_env().items()
           if (k in _SANDBOX_ENV_KEEP or k.startswith("LC_")) and not _SECRET_ENV.search(k)}
    env.update(HOME=home, TMPDIR=tmpdir, TMP=tmpdir, TEMP=tmpdir,
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1")
    tools = loop_platform.module("sandbox").extra_path()
    if tools:
        env["PATH"] = os.pathsep.join(p for p in (tools, env.get("PATH")) if p)
    return env


def _sparse_checkout(repo, root):
    """Leave the installation's loop.clone_excluded folders out of the clone's working tree; their
    entries stay in its index as skip-worktree, so its commits keep them unchanged."""
    git(["config", "core.sparseCheckout", "true"], repo)
    git(["config", "core.sparseCheckoutCone", "false"], repo)
    info = os.path.join(repo, ".git", "info")
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, "sparse-checkout"), "w") as f:
        f.write("/*\n" + "".join(f"!/{p}\n" for p in loop_config.value("clone_excluded", root)))


class Isolate:
    """Create a temporary shared clone pinned to base SHA, with its own .git and read-only object alternates.
    Sandbox tests to this clone and dedicated HOME/TMPDIR, denying external writes and network."""

    def __init__(self, sha, root=None):
        self.sha, self.root = sha, root or ROOT

    def __enter__(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="papers-apply-iso-"))
        self.tree = os.path.join(self.tmp, "tree")
        self.home = os.path.join(self.tmp, "home")
        self.tmpdir = os.path.join(self.tmp, "tmp")
        os.makedirs(self.home)
        os.makedirs(self.tmpdir)
        try:
            # A snapshot commit lives only in its temporary repository; clone from there for it.
            git(["clone", "-q", "--shared", "--no-checkout", _SNAPSHOT_REPOS.get(self.sha, self.root), self.tree],
                self.tmp)
            _sparse_checkout(self.tree, self.root)
            git(["checkout", "-q", "--detach", self.sha], self.tree)
            git(["config", "user.name", "papers-apply-isolate"], self.tree)
            git(["config", "user.email", "isolate@example.invalid"], self.tree)
        except BaseException:
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise
        # Kept in memory and handed to each start, never in a file a sandboxed program could write.
        self.rules = sandbox_profile(self.tmp, self.root, readable=object_stores(self.tree))
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self):
        return sandbox_env(self.home, self.tmpdir)

    def command(self, argv, stage="verify"):
        """argv run in the sandbox of this clone; raises StageError without a sandbox."""
        return sandboxed(self.rules, argv, stage)


def build_snapshot(root=None):
    """Commit the current working tree into a temporary clone and return (commit, overlaid paths).

    The commit is HEAD plus every tracked path as it is now in the working tree (modified, added to
    the index, or deleted) plus untracked, non-ignored files inside the allowed area (loop_policy.ALLOWED, the harness).
    Ignored files and the private area never enter. With a clean tree the snapshot is HEAD itself.
    Fixed author data and dates make the commit id a pure function of HEAD and the tree contents,
    so an unchanged working tree yields the same snapshot on the next run."""
    root = root or ROOT
    head = head_sha(root)
    # --no-renames lists both sides of a staged rename, so the old path is removed from the snapshot.
    listed = git(["diff", "--name-only", "--no-renames", "-z", "HEAD"], root).stdout.decode("utf-8", "replace").split("\0")
    untracked = git(["ls-files", "--others", "--exclude-standard", "-z", "--",
                     *loop_policy.ALLOWED], root).stdout.decode("utf-8", "replace").split("\0")
    left_out = loop_config.value("clone_excluded", root)
    paths = sorted({p for p in listed + untracked if p and normal_path(p) and not p.startswith(PRIVATE + "/")
                    and not p.startswith(left_out)})
    if not paths:
        return head, {}
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="papers-apply-snap-"))
    repo = os.path.join(tmp, "repo")
    try:
        git(["clone", "-q", "--shared", "--no-checkout", root, repo], tmp)
        _sparse_checkout(repo, root)
        git(["checkout", "-q", "--detach", head], repo)
        overlaid = {}
        for path in paths:
            src = os.path.join(root, path)
            if os.path.islink(src) or (os.path.lexists(src) and not os.path.isfile(src)):
                continue   # Links and special files keep their HEAD state; edits never follow links.
            try:
                fp, st = safe_target(repo, path)
            except ValueError:
                continue
            if not os.path.lexists(src):
                if st is not None:
                    os.unlink(fp)
                overlaid[path] = None
                continue
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(src, "rb") as f:
                data = f.read()
            write_nofollow(fp, data)
            os.chmod(fp, os.stat(src).st_mode & 0o777)
            overlaid[path] = sha256_bytes(data)
        git(["add", "-A", "--", *paths], repo)
        fixed = "2000-01-01T00:00:00+0000"
        env = clean_env(GIT_AUTHOR_NAME="papers-apply-snapshot", GIT_AUTHOR_EMAIL="snapshot@example.invalid",
                        GIT_COMMITTER_NAME="papers-apply-snapshot", GIT_COMMITTER_EMAIL="snapshot@example.invalid",
                        GIT_AUTHOR_DATE=fixed, GIT_COMMITTER_DATE=fixed)
        c = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "commit", "-q", "--no-verify",
                            "--allow-empty", "-m", f"working-tree snapshot of {head[:12]}"],
                           cwd=repo, env=env, capture_output=True)
        if c.returncode != 0:
            raise RuntimeError("snapshot commit failed: " + c.stderr.decode("utf-8", "replace")[:200])
        sha = git(["rev-parse", "HEAD"], repo).stdout.decode().strip()
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _SNAPSHOT_REPOS[sha] = repo
    return sha, overlaid


def cleanup_snapshots():
    for repo in list(_SNAPSHOT_REPOS.values()):
        shutil.rmtree(os.path.dirname(repo), ignore_errors=True)
    _SNAPSHOT_REPOS.clear()


def snapshot_adds(sha, head, root=None):
    """The paths base commit sha has and commit head lacks: a snapshot's untracked files."""
    repo = _SNAPSHOT_REPOS.get(sha, root or ROOT)
    diff = git(["diff-tree", "-r", "-z", "--name-only", "--no-renames", "--diff-filter=A", head, sha], repo).stdout
    return sorted(p for p in diff.decode("utf-8", "replace").split("\0") if p)


def unlike_snapshot(sha, tree_id, placed, root=None):
    """Paths where a tree (Git tree id tree_id, with the files placed on it: path to sha256) differs
    from the base commit sha; a review counts only when its worker read that commit."""
    repo = _SNAPSHOT_REPOS.get(sha, root or ROOT)
    diff = git(["diff-tree", "-r", "-z", "--name-only", "--no-renames", sha, tree_id], repo).stdout
    out = []
    for path in sorted(p for p in diff.decode("utf-8", "replace").split("\0") if p):
        blob = git(["cat-file", "blob", f"{sha}:{path}"], repo, check=False)
        if path not in placed or blob.returncode != 0 or sha256_bytes(blob.stdout) != placed[path]:
            out.append(path)
    return out

