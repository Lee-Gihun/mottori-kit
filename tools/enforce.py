#!/usr/bin/env python3
"""The checks on what may leave through Git, each failing closed when it cannot measure:
``--issues --index`` judges the staged index, and no baseline waives what it finds (gate.py
precommit runs it); ``prepush`` is the pre-push hook.

The commit check refuses a private path, and a state or instance file that Git does not already
track. The push check is the backstop for a commit made with --no-verify, and refuses a private
path only. Neither decides which remote a folder may push to, or whether it may commit: that is
Git's and the owner's business.

``--issues`` is a machine protocol: each issue is ``stable-id<TAB>message`` and
the final line is ``#issues N``. Findings still exit zero; an inability to
measure exits nonzero and deliberately omits the trailer.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
from typing import Iterable

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C  # noqa: E402
import paths as P  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
INSTANCE_DAMAGED = (
    "{config} is missing, but this folder holds instance files ({paths}), so it is a damaged "
    "instance, not a kit before setup. Restore the config (git restore {config} where Git tracks "
    "it, or a {config}.bak-* copy), or run bash setup.sh again, which writes a new one from the "
    "template, then retry."
)
NEW_INSTANCE_PATH = (
    "new state or instance file is not in HEAD and cannot be committed: {path}. Unstage it "
    "with git restore --staged; it stays local."
)
PUSH_INPUT_UNREADABLE = (
    "the ref list from Git was not closed within {seconds} s or is not UTF-8"
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# Instance paths a commit may add only once HEAD tracks them; _private/ never (is_private_path).
FORBIDDEN_PREFIXES = tuple(P.tracked_name(path_of) + "/" for path_of in (P.state, P.instance))
TRACKED_STATE_EXCEPTIONS = {"state/.gitkeep"}
# A new month's public journal is a new path every month. It is allowed only once HEAD already
# tracks a journal, so the instance has shown it publishes journals. The pattern lives in code
# so that editing an ignore file cannot widen what may be committed.
TRACKED_STATE_PATTERN = re.compile(r"^state/" + P.JOURNAL_NAME.pattern)
ZERO_SHA = "0" * 40

class MeasurementError(RuntimeError):
    pass


def _run_git(root: Path, args: list[str], stdin: bytes | None = None) -> bytes:
    try:
        run = subprocess.run(
            ["git", *args], cwd=root, input=stdin, capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MeasurementError(f"git failed to run: {type(error).__name__}") from error
    if run.returncode:
        detail = run.stderr.decode("utf-8", errors="replace").strip()
        raise MeasurementError(detail or f"git {' '.join(args)} exit {run.returncode}")
    return run.stdout


def _decode_paths(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MeasurementError("Git path is not UTF-8") from error
    fields = text.split("\0")
    if fields[-1] != "":
        raise MeasurementError("Git NUL path stream was truncated")
    return [field for field in fields[:-1] if field]


def _index_entries(root: Path) -> list[tuple[str, str, str]]:
    raw = _run_git(root, ["ls-files", "-s", "-z"])
    records = _decode_paths(raw)
    entries: list[tuple[str, str, str]] = []
    for record in records:
        if "\t" not in record:
            raise MeasurementError("git ls-files record has no TAB")
        metadata, path = record.split("\t", 1)
        fields = metadata.split()
        if len(fields) != 3:
            raise MeasurementError("git ls-files metadata has an unexpected format")
        mode, _blob, stage = fields
        entries.append((mode, stage, path))
    return entries


def _has_head(root: Path) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root,
                          capture_output=True, check=False).returncode == 0


def _index_changes(root: Path, has_head: bool, entries: list[tuple[str, str, str]]) -> list[str]:
    if not has_head:
        return [path for _mode, _stage, path in entries]
    return _decode_paths(_run_git(root, ["diff", "--cached", "--name-only", "-z", "HEAD", "--"]))


def _head_paths(root: Path, has_head: bool) -> set[str]:
    """Return paths committed in HEAD without consulting mutable worktree ignore rules."""
    if not has_head:
        return set()
    return set(_decode_paths(_run_git(
        root, ["ls-tree", "-r", "--name-only", "-z", "HEAD", "--"])))


def _ignored_by_rules(root: Path, path: str) -> bool:
    """True when the repo's own ignore rules cover the path, i.e. it can only be staged by force-add."""
    run = subprocess.run(["git", "check-ignore", "--no-index", "-q", "--", path], cwd=root,
                         capture_output=True, check=False)
    if run.returncode not in (0, 1):
        raise MeasurementError(f"git check-ignore failed for {path}: {run.stderr.decode('utf-8', 'replace').strip()}")
    return run.returncode == 0


def is_private_path(path: str) -> bool:
    """The rule for private paths that the commit and the push checks share."""
    # casefold: on a case-insensitive disk _PRIVATE/x.md is the same file as _private/x.md.
    return path.casefold().startswith("_private/")


def _forbidden_in_index(root: Path, path: str, head_paths: set[str], has_head: bool) -> bool:
    """Block private/instance paths absent from HEAD, independent of editable ignore rules.

    Existing tracked public state and instance files remain compatible with the origin workspace.
    `_private/` stays forbidden even when a path was already committed historically.
    """
    if path in TRACKED_STATE_EXCEPTIONS:
        return False
    if is_private_path(path):
        return True
    folded = path.casefold()
    if folded.startswith(FORBIDDEN_PREFIXES):
        if has_head:
            if TRACKED_STATE_PATTERN.match(path) and any(
                    TRACKED_STATE_PATTERN.match(p) for p in head_paths):
                return False
            return path not in head_paths
        # Without HEAD, use force-add detection so an instance may create its initial public state.
        return _ignored_by_rules(root, path)
    return False


def index_issues(root: Path = ROOT) -> list[tuple[str, str]]:
    """Return absolute staged-index violations. Baselines never waive these."""
    issues: list[tuple[str, str]] = []
    # An installation whose config is gone is damaged, and nothing is committed from it until it is whole.
    damaged = damaged_outputs(root)
    if damaged:
        issues.append(("instance-config-missing", _damage(root, damaged)))
    entries = _index_entries(root)
    has_head = _has_head(root)
    head_paths = _head_paths(root, has_head)
    # Apply symlink and submodule restrictions to newly staged changes, not unchanged legacy entries.
    changed = set(_index_changes(root, has_head, entries))
    for mode, stage, path in entries:
        if stage != "0":
            issues.append((f"index-unmerged:{path}", f"unmerged index entry: {path}"))
        if _forbidden_in_index(root, path, head_paths, has_head):
            if is_private_path(path):
                issues.append((f"forbidden-index-path:{path}", f"private path staged: {path}"))
            else:
                issues.append((f"new-instance-path:{path}", NEW_INSTANCE_PATH.format(path=path)))
        if mode == "160000" and path in changed:
            issues.append((f"index-submodule:{path}", f"submodule gitlink is not allowed: {path}"))
        if mode == "120000" and path in changed and path.lower().endswith(".md"):
            issues.append((f"index-markdown-symlink:{path}",
                           f"staged symlink is not allowed here: {path}"))
    return sorted(set(issues))


def _print_issues(issues: Iterable[tuple[str, str]]) -> int:
    rows = sorted(set(issues))
    for issue_id, message in rows:
        print(f"{issue_id}\t{message}")
    print(f"#issues {len(rows)}")
    return 0


def cmd_issues(root: Path, use_index: bool) -> int:
    # All current enforce rules concern the Git index. The flag is explicit so
    # callers cannot accidentally mistake a worktree scan for a commit scan.
    if not use_index:
        print("--issues needs --index: every enforce rule checks the Git index", file=sys.stderr)
        return 2
    return _print_issues(index_issues(root))


def damaged_outputs(root: Path) -> list[str]:
    """Instance files present in a tree whose config is missing; empty when the config exists.

    They are the rules file setup writes, the state files now.py check also takes as evidence of
    an installed instance, and any file still at its place from before the instance folder. The
    gate baseline is not one: a kit development tree saves one too.
    """
    if os.path.isfile(P.config_file(str(root))):
        return []
    rules = [P.tracked_name(P.rules)] if os.path.isfile(P.rules(str(root))) else []
    legacy = [os.path.relpath(old, root) for old, _ in P.legacy_moves(str(root))]
    return rules + P.state_evidence(root) + legacy


def _damage(root: Path, damaged: list[str]) -> str:
    """What the commit and push checks say about a tree with instance files but no config."""
    return C.legacy_layout(str(root)) or INSTANCE_DAMAGED.format(
        config=C.CONFIG_NAME, paths=", ".join(damaged))


def _pushed_paths(root: Path, lines: list[str]) -> list[str]:
    """Paths added or changed by the commits a push sends that the receiver does not have.

    Git writes each destination ref's object id on the receiver to the hook. Commits reachable from
    it are already there. A new ref (the zero id), or an id this repository lacks, gives no such
    floor, so every reachable commit is inspected. Cached remote-tracking refs are not evidence of
    what the receiver holds: a remote can push to another URL, and a receiver can be replaced after
    the last fetch.
    """
    paths: list[str] = []
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 4:
            raise MeasurementError(f"unexpected pre-push line: {line!r}")
        _local_ref, local_sha, _remote_ref, remote_sha = fields
        if local_sha == ZERO_SHA:
            continue  # A branch deletion sends no content.
        exclude = []
        if remote_sha != ZERO_SHA and subprocess.run(
                ["git", "cat-file", "-e", f"{remote_sha}^{{commit}}"], cwd=root,
                capture_output=True, check=False, timeout=30).returncode == 0:
            exclude = ["--not", remote_sha]
        commits = _run_git(root, ["rev-list", local_sha, *exclude]).decode("ascii").split()
        if not commits:
            continue
        # -m lists merge changes per parent; deletions are left out so removing a leaked file can be pushed.
        listed = _run_git(root, ["diff-tree", "--stdin", "--no-commit-id", "-r", "-m", "--root",
                                 "--name-only", "-z", "--diff-filter=d"],
                          stdin=("\n".join(commits) + "\n").encode("ascii"))
        paths.extend(_decode_paths(listed))
    return sorted(set(paths))


def _hook_lines(timeout: float = 30.0) -> list[str]:
    """Return the ref lines Git writes to a pre-push hook before closing the pipe.

    Input still open at the deadline, or not UTF-8, cannot be judged, so it stops the push
    instead of hanging it or passing it.
    """
    fd = sys.stdin.fileno()
    chunks, deadline = [], time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise MeasurementError(PUSH_INPUT_UNREADABLE.format(seconds=int(timeout)))
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise MeasurementError(PUSH_INPUT_UNREADABLE.format(seconds=int(timeout))) from error


PUSH_LEAK_NEXT = (
    "  The receiver does not have that commit yet, so the file can be taken out of history before it "
    "leaves: `git rebase -i` the commits not yet pushed and drop the file from the one that added it "
    "(`git rm --cached <path>`, then `git commit --amend`). A later commit that deletes it does not "
    "help: the push still sends the commit that added it."
)


def _push_blocked(reason: str) -> int:
    print(f"push blocked: {reason}", file=sys.stderr)
    return 1


def cmd_prepush(root: Path, url: str | None = None) -> int:
    """The pre-push check. It is the backstop for a commit made with --no-verify, so it repeats
    the one rule no baseline waives: no private path leaves."""
    # An installation whose config is gone is damaged: nothing is pushed from it until it is whole.
    damaged = damaged_outputs(root)
    if damaged:
        return _push_blocked(_damage(root, damaged))
    # Only git, which passes the remote and its URL, writes refs and closes stdin; a manual run may
    # inherit an open pipe nobody writes, and reading it would never return.
    hooked = url is not None and sys.stdin is not None and not sys.stdin.isatty()
    lines = _hook_lines() if hooked else []
    leaked = [path for path in _pushed_paths(root, lines) if is_private_path(path)]
    for path in leaked:
        _push_blocked(f"a pushed commit contains a private path: {path}")
    if leaked:
        # Removing the file in a later commit leaves it in the earlier one, which the push still sends.
        print(PUSH_LEAK_NEXT, file=sys.stderr)
    return 1 if leaked else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues", action="store_true")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    sub = parser.add_subparsers(dest="command")
    push = sub.add_parser("prepush")
    # Git passes the remote name and URL to a pre-push hook; both are optional for manual runs, and
    # only the URL is used.
    push.add_argument("remote", nargs="?")
    push.add_argument("url", nargs="?")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.issues:
            return cmd_issues(root, args.index)
        if args.command == "prepush":
            return cmd_prepush(root, args.url)
        parser.error("--issues or a command is required")
    except MeasurementError as error:
        print(f"enforce measurement failed: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
