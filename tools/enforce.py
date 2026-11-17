#!/usr/bin/env python3
"""Fail-close enforcement seams for Git egress and runtime hooks.

``--issues`` is a machine protocol: each issue is ``stable-id<TAB>message`` and
the final line is ``#issues N``. Findings still exit zero; an inability to
measure exits nonzero and deliberately omits the trailer.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CANARY_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
FORBIDDEN_PREFIXES = ("state/", "_private/")
FORBIDDEN_EXACT = {
    "system/memory-config.json",
    "system/instance-rules.md",
    "system/decisions.md",
    "system/rituals.local.md",
}
TRACKED_STATE_EXCEPTIONS = {"state/.gitkeep"}

# English text of every message this module prints, used when tools/i18n.py cannot be imported.
# The hook dispatcher must still print its fail-closed fallback when the engine is partly broken.
# test_enforce.py pins these values to the catalog's English entries.
FALLBACK_TEXT = {
    "enforce.git_failed": "git failed to run: {error_type}",
    "enforce.path_not_utf8": "Git path is not UTF-8",
    "enforce.path_stream_truncated": "Git NUL path stream was truncated",
    "enforce.config_missing": "config missing: {path}",
    "enforce.config_unreadable": "config unreadable: {error_type}",
    "enforce.config_not_object": "config root is not an object",
    "enforce.ls_files_no_tab": "git ls-files record has no TAB",
    "enforce.ls_files_metadata": "git ls-files metadata has an unexpected format",
    "enforce.context_required": "instance.context must be set to personal or work",
    "enforce.rules_missing": "instance-rules missing: {path}",
    "enforce.rules_unreadable": "instance-rules unreadable: {error_type}",
    "enforce.rules_changeme": "instance-rules still contains CHANGEME",
    "enforce.rules_empty": "instance-rules is empty",
    "enforce.push_unknown_context": "push blocked: cannot determine instance.context",
    "enforce.push_work": "push blocked: a work instance does not allow remote export from local pre-push",
    "enforce.fallback_authority": ("Read state/NOW.md together with _private/state/NOW.md when it exists. "
                                   "A missing local overlay means unavailable, not no state."),
    "enforce.hook_root_mismatch": "refused state injection or gate run because the hook project root does not match",
    "enforce.hook_failed": "{event} hook failed (exit {code})",
    "enforce.sessionstart_invalid_json": "SessionStart hook did not print valid JSON",
    "enforce.stop_invalid_json": "Stop gate did not print valid JSON",
    "enforce.command_required": "--issues or a command is required",
}


def _t(key: str, **kw: object) -> str:
    """Return catalog text in the instance language, or English when the catalog is unavailable."""
    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        from i18n import t
        return t(key, **kw)
    except Exception:
        return FALLBACK_TEXT[key].format(**kw)


class MeasurementError(RuntimeError):
    pass


def _run_git(root: Path, args: list[str]) -> bytes:
    try:
        run = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MeasurementError(_t("enforce.git_failed", error_type=type(error).__name__)) from error
    if run.returncode:
        detail = run.stderr.decode("utf-8", errors="replace").strip()
        raise MeasurementError(detail or f"git {' '.join(args)} exit {run.returncode}")
    return run.stdout


def _decode_paths(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MeasurementError(_t("enforce.path_not_utf8")) from error
    fields = text.split("\0")
    if fields[-1] != "":
        raise MeasurementError(_t("enforce.path_stream_truncated"))
    return [field for field in fields[:-1] if field]


def _config(root: Path) -> tuple[dict, list[str]]:
    path = root / "system" / "memory-config.json"
    problems: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, [_t("enforce.config_missing", path=path)]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {}, [_t("enforce.config_unreadable", error_type=type(error).__name__)]
    if not isinstance(data, dict):
        return {}, [_t("enforce.config_not_object")]
    return data, problems


def instance_context(root: Path = ROOT) -> str | None:
    config, _ = _config(root)
    instance = config.get("instance") if isinstance(config, dict) else None
    context = instance.get("context") if isinstance(instance, dict) else None
    return context if context in ("personal", "work") else None


def _index_entries(root: Path) -> list[tuple[str, str, str]]:
    raw = _run_git(root, ["ls-files", "-s", "-z"])
    records = _decode_paths(raw)
    entries: list[tuple[str, str, str]] = []
    for record in records:
        if "\t" not in record:
            raise MeasurementError(_t("enforce.ls_files_no_tab"))
        metadata, path = record.split("\t", 1)
        fields = metadata.split()
        if len(fields) != 3:
            raise MeasurementError(_t("enforce.ls_files_metadata"))
        mode, _blob, stage = fields
        entries.append((mode, stage, path))
    return entries


def _index_changes(root: Path) -> list[str]:
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=root,
        capture_output=True, check=False,
    )
    if head.returncode:
        return [path for _mode, _stage, path in _index_entries(root)]
    return _decode_paths(_run_git(root, ["diff", "--cached", "--name-only", "-z", "HEAD", "--"]))


def _head_paths(root: Path) -> set[str]:
    """Return paths committed in HEAD without consulting mutable worktree ignore rules."""
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=root,
        capture_output=True, check=False,
    )
    if head.returncode:
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


def _forbidden_in_index(root: Path, path: str, head_paths: set[str], has_head: bool) -> bool:
    """Block private/instance paths absent from HEAD, independent of editable ignore rules.

    Existing tracked public state and instance files remain compatible with the origin workspace.
    `_private/` stays forbidden even when a path was already committed historically.
    """
    if path in TRACKED_STATE_EXCEPTIONS:
        return False
    if path.startswith("_private/"):
        return True
    if path in FORBIDDEN_EXACT or path.startswith(FORBIDDEN_PREFIXES):
        if has_head:
            return path not in head_paths
        # Without HEAD, use force-add detection so an instance may create its initial public state.
        return _ignored_by_rules(root, path)
    return False


def index_issues(root: Path = ROOT) -> list[tuple[str, str]]:
    """Return absolute staged-index violations. Baselines never waive these."""
    context = instance_context(root)
    issues: list[tuple[str, str]] = []
    entries = _index_entries(root)
    head_paths = _head_paths(root)
    has_head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root,
                              capture_output=True, check=False).returncode == 0
    # Apply symlink and submodule restrictions to newly staged changes, not unchanged legacy entries.
    changed = set(_index_changes(root))
    for mode, stage, path in entries:
        if stage != "0":
            issues.append((f"index-unmerged:{path}", f"unmerged index entry: {path}"))
        if _forbidden_in_index(root, path, head_paths, has_head):
            issues.append((f"forbidden-index-path:{path}", f"instance/private path staged: {path}"))
        if mode == "160000" and path in changed:
            issues.append((f"index-submodule:{path}", f"submodule gitlink is not allowed: {path}"))
        if mode == "120000" and path in changed and (context == "work" or path.lower().endswith(".md")):
            issues.append((f"index-symlink:{path}" if context == "work" else
                           f"index-markdown-symlink:{path}",
                           f"staged symlink is not allowed here: {path}"))
    if context == "work":
        for path in _index_changes(root):
            issues.append((f"work-local-change:{path}",
                           f"work instance may not create local commits: {path}"))
    return sorted(set(issues))


def ready_problems(root: Path = ROOT) -> list[str]:
    config, problems = _config(root)
    instance = config.get("instance") if isinstance(config, dict) else None
    context = instance.get("context") if isinstance(instance, dict) else None
    if context not in ("personal", "work"):
        problems.append(_t("enforce.context_required"))
    rules = root / "system" / "instance-rules.md"
    try:
        text = rules.read_text(encoding="utf-8")
    except FileNotFoundError:
        problems.append(_t("enforce.rules_missing", path=rules))
    except (OSError, UnicodeDecodeError) as error:
        problems.append(_t("enforce.rules_unreadable", error_type=type(error).__name__))
    else:
        if "CHANGEME" in text:
            problems.append(_t("enforce.rules_changeme"))
        if not text.strip():
            problems.append(_t("enforce.rules_empty"))
    return problems


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
        return _print_issues([])
    return _print_issues(index_issues(root))


def cmd_ready(root: Path) -> int:
    problems = ready_problems(root)
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    return 1 if problems else 0


def is_presetup_kit_tree(root: Path = ROOT) -> bool:
    """Recognize a kit checkout before setup by its installer and config template. Without instance config, no instance context is available to validate."""
    return (not (root / "system" / "memory-config.json").is_file()
            and (root / "setup.sh").is_file()
            and (root / "templates" / "memory-config.json").is_file())


def cmd_prepush(root: Path) -> int:
    context = instance_context(root)
    if context is None and is_presetup_kit_tree(root):
        print("push allowed: pre-setup kit tree (no instance config; setup.sh + templates present)")
        return 0
    if context is None:
        print(_t("enforce.push_unknown_context"), file=sys.stderr)
        return 1
    if context == "work":
        print(_t("enforce.push_work"), file=sys.stderr)
        return 1
    return 0


def _fallback(event: str, reason: str) -> str:
    authority = _t("enforce.fallback_authority")
    if event == "Stop":
        return json.dumps({"decision": "block", "reason": f"[kit] {reason}"}, ensure_ascii=False)
    hook_event = "UserPromptSubmit" if event in ("UserPromptSubmit", "PostToolUse") else event
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": hook_event,
        "additionalContext": f"[kit] {reason}. {authority}",
    }}, ensure_ascii=False)


def _git_root(cwd: Path) -> Path | None:
    run = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=cwd,
        capture_output=True, text=True, check=False,
    )
    return Path(run.stdout.strip()).resolve() if run.returncode == 0 and run.stdout.strip() else None


def _valid_hook_root(root: Path, claimed_root: str | None) -> bool:
    cwd_root = _git_root(Path.cwd())
    if cwd_root != root.resolve():
        return False
    if claimed_root and Path(claimed_root).resolve() != root.resolve():
        return False
    return True


def _hook_subprocess(root: Path, event: str, payload: str) -> tuple[int, str]:
    if event == "SessionStart":
        command = [sys.executable, str(root / "tools" / "now.py"), "hook-context"]
    elif event == "PreCompact":
        command = [sys.executable, str(root / "tools" / "now.py"), "precompact"]
    elif event == "UserPromptSubmit":
        command = [sys.executable, str(root / "tools" / "gate.py"), "resume"]
    elif event == "PostToolUse":
        command = [sys.executable, str(root / "tools" / "gate.py"), "dirty"]
    elif event == "Stop":
        command = [sys.executable, str(root / "tools" / "gate.py"), "check"]
    else:
        raise ValueError(f"unknown hook event: {event}")
    env = dict(os.environ)
    canary = env.get("MOTTORI_HOOK_CANARY")
    if canary is not None and not CANARY_RE.fullmatch(canary):
        env.pop("MOTTORI_HOOK_CANARY", None)
    env.pop("MOTTORI_INSTANCE", None)
    try:
        run = subprocess.run(
            command, cwd=root, env=env, input=payload, text=True,
            capture_output=True, check=False, timeout=150,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return run.returncode, run.stdout


def cmd_hook(root: Path, event: str, claimed_root: str | None) -> int:
    payload = sys.stdin.read()
    if not _valid_hook_root(root, claimed_root):
        print(_fallback(event, _t("enforce.hook_root_mismatch")))
        return 0
    code, output = _hook_subprocess(root, event, payload)
    if code != 0:
        print(_fallback(event, _t("enforce.hook_failed", event=event, code=code)))
        return 0
    if event in ("SessionStart", "Stop"):
        try:
            parsed = json.loads(output) if output.strip() else None
        except json.JSONDecodeError:
            parsed = None
        if event == "SessionStart" and not isinstance(parsed, dict):
            print(_fallback(event, _t("enforce.sessionstart_invalid_json")))
            return 0
        if event == "Stop" and output.strip() and not isinstance(parsed, dict):
            print(_fallback(event, _t("enforce.stop_invalid_json")))
            return 0
    if output:
        sys.stdout.write(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues", action="store_true")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("ready")
    sub.add_parser("prepush")
    hook = sub.add_parser("hook")
    hook.add_argument("--runtime", required=True, choices=("claude", "codex"))
    hook.add_argument("--event", required=True,
                      choices=("SessionStart", "PreCompact", "UserPromptSubmit", "PostToolUse", "Stop"))
    hook.add_argument("--claimed-root")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.issues:
            return cmd_issues(root, args.index)
        if args.command == "ready":
            return cmd_ready(root)
        if args.command == "prepush":
            return cmd_prepush(root)
        if args.command == "hook":
            return cmd_hook(root, args.event, args.claimed_root)
        parser.error(_t("enforce.command_required"))
    except MeasurementError as error:
        print(f"enforce measurement failed: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
