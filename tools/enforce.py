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


class MeasurementError(RuntimeError):
    pass


def _run_git(root: Path, args: list[str]) -> bytes:
    try:
        run = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MeasurementError(f"git 실행 실패: {type(error).__name__}") from error
    if run.returncode:
        detail = run.stderr.decode("utf-8", errors="replace").strip()
        raise MeasurementError(detail or f"git {' '.join(args)} exit {run.returncode}")
    return run.stdout


def _decode_paths(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MeasurementError("Git path가 UTF-8이 아니다") from error
    fields = text.split("\0")
    if fields[-1] != "":
        raise MeasurementError("Git NUL path stream이 잘렸다")
    return [field for field in fields[:-1] if field]


def _config(root: Path) -> tuple[dict, list[str]]:
    path = root / "system" / "memory-config.json"
    problems: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, [f"config 없음: {path}"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {}, [f"config 판독 실패: {type(error).__name__}"]
    if not isinstance(data, dict):
        return {}, ["config root가 object가 아니다"]
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
            raise MeasurementError("git ls-files record에 TAB이 없다")
        metadata, path = record.split("\t", 1)
        fields = metadata.split()
        if len(fields) != 3:
            raise MeasurementError("git ls-files metadata 형식이 다르다")
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
        # Initial commit: there is no history to protect yet, so the only signal is the repo's own
        # ignore rules (a force-add). Without this an origin-style instance that tracks its public
        # state could never make its first commit (2026-09-18: the evidencecheck e2e fixture).
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
    # symlink·submodule 규칙은 이번 커밋이 올리는 항목(HEAD 대비 변경분)에만 건다. HEAD에 이미 있는 항목까지
    # 걸면 과거 트리(예: 원 인스턴스 archive/의 추적 중인 .md symlink)가 모든 커밋을 영구히 막는다 (2026-09-18 실측).
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
        problems.append("instance.context는 personal 또는 work로 명시해야 한다")
    rules = root / "system" / "instance-rules.md"
    try:
        text = rules.read_text(encoding="utf-8")
    except FileNotFoundError:
        problems.append(f"instance-rules 없음: {rules}")
    except (OSError, UnicodeDecodeError) as error:
        problems.append(f"instance-rules 판독 실패: {type(error).__name__}")
    else:
        if "CHANGEME" in text:
            problems.append("instance-rules에 CHANGEME가 남아 있다")
        if not text.strip():
            problems.append("instance-rules가 비어 있다")
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
    """A kit checkout that was never set up: no instance config, but the installer and its template exist.
    It is not an instance, so instance.context cannot and need not be judged (2026-09-18: the kit dev tree)."""
    return (not (root / "system" / "memory-config.json").is_file()
            and (root / "setup.sh").is_file()
            and (root / "templates" / "memory-config.json").is_file())


def cmd_prepush(root: Path) -> int:
    context = instance_context(root)
    if context is None and is_presetup_kit_tree(root):
        print("push allowed: pre-setup kit tree (no instance config; setup.sh + templates present)")
        return 0
    if context is None:
        print("push blocked: instance.context를 판정할 수 없다", file=sys.stderr)
        return 1
    if context == "work":
        print("push blocked: work instance는 local pre-push에서 원격 반출을 허용하지 않는다",
              file=sys.stderr)
        return 1
    return 0


def _fallback(event: str, reason: str) -> str:
    authority = (
        "state/NOW.md와 존재할 때 _private/state/NOW.md를 함께 읽어라. "
        "local overlay 부재는 unavailable이지 상태 없음이 아니다."
    )
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
        print(_fallback(event, "hook project root 불일치로 상태 주입 또는 게이트 실행을 거부했다"))
        return 0
    code, output = _hook_subprocess(root, event, payload)
    if code != 0:
        print(_fallback(event, f"{event} hook 실행 실패(exit {code})"))
        return 0
    if event in ("SessionStart", "Stop"):
        try:
            parsed = json.loads(output) if output.strip() else None
        except json.JSONDecodeError:
            parsed = None
        if event == "SessionStart" and not isinstance(parsed, dict):
            print(_fallback(event, "SessionStart hook이 유효 JSON을 내지 않았다"))
            return 0
        if event == "Stop" and output.strip() and not isinstance(parsed, dict):
            print(_fallback(event, "Stop gate가 유효 JSON을 내지 않았다"))
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
        parser.error("--issues 또는 command가 필요하다")
    except MeasurementError as error:
        print(f"enforce measurement failed: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
