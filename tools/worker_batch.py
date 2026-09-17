#!/usr/bin/env python3
"""Create and verify committed slot coverage for bounded worker batches.

This tool records the expected slots and prompt hashes. It does not launch workers or schedule
them. Exit codes for ``verify`` are 0 PASS, 2 INCONCLUSIVE_COVERAGE, and 1 FAIL.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid


ROOT_LEXICAL = Path(os.environ.get(
    "MOTTORI_INSTANCE", Path(__file__).resolve().parent.parent,
)).expanduser().absolute()
ROOT = ROOT_LEXICAL.resolve()
SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SLOT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
TERMINAL_STATUSES = {"success", "failed", "failed-missing-result", "scope_violation"}


class BatchError(ValueError):
    pass


def _inside(path, root):
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _workspace_path(path):
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = Path(os.path.abspath(candidate))
    # macOS exposes /var as /private/var. Preserve lexical in-workspace symlinks for the check below,
    # but rebase the operating system's root alias onto the physical instance root.
    if not _inside(candidate, ROOT) and _inside(candidate, ROOT_LEXICAL):
        candidate = ROOT / candidate.relative_to(ROOT_LEXICAL)
    if not _inside(candidate, ROOT):
        raise BatchError("path is outside the workspace")
    return candidate


def _reject_symlink_components(path, include_final=True):
    relative = path.relative_to(ROOT)
    current = ROOT
    parts = relative.parts if include_final else relative.parts[:-1]
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if include_final:
                raise BatchError(f"file does not exist: {relative}")
            return
        if stat.S_ISLNK(mode):
            raise BatchError(f"symlink component is not allowed: {relative}")


def _read_regular(path, label):
    candidate = _workspace_path(path)
    _reject_symlink_components(candidate)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as exc:
        raise BatchError(f"cannot open {label}: {type(exc).__name__}")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise BatchError(f"{label} is not a regular file")
        with os.fdopen(fd, "rb") as stream:
            data = stream.read()
        fd = None
    finally:
        if fd is not None:
            os.close(fd)
    return candidate, data


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _validate_manifest(document):
    if not isinstance(document, dict) or set(document) != {"schema_version", "slots"}:
        raise BatchError("manifest root has invalid fields")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise BatchError("manifest schema_version is not 1")
    rows = document.get("slots")
    if not isinstance(rows, list) or not rows:
        raise BatchError("manifest slots must be a non-empty list")
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"name", "prompt", "prompt_sha256"}:
            raise BatchError(f"manifest slot {index} has invalid fields")
        name = row.get("name")
        if not isinstance(name, str) or SLOT_RE.fullmatch(name) is None:
            raise BatchError(f"manifest slot {index} has an invalid name")
        if name in seen:
            raise BatchError(f"duplicate slot: {name}")
        seen.add(name)
        prompt = row.get("prompt")
        if not isinstance(prompt, str) or not prompt or Path(prompt).is_absolute():
            raise BatchError(f"manifest slot {name} has an invalid prompt path")
        normalized = os.path.normpath(prompt).replace(os.sep, "/")
        if normalized == ".." or normalized.startswith("../"):
            raise BatchError(f"manifest slot {name} prompt is outside the workspace")
        if normalized != prompt:
            raise BatchError(f"manifest slot {name} prompt path is not normalized")
        digest = row.get("prompt_sha256")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise BatchError(f"manifest slot {name} has an invalid prompt SHA")
    return document


def load_manifest(path):
    _, raw = _read_regular(path, "manifest")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchError(f"manifest is not valid UTF-8 JSON: {type(exc).__name__}")
    return _validate_manifest(document), _sha256(raw)


def _write_new(path, data):
    target = _workspace_path(path)
    _reject_symlink_components(target, include_final=False)
    if not target.parent.is_dir():
        raise BatchError("manifest parent directory does not exist")
    if target.exists() or target.is_symlink():
        raise BatchError("manifest already exists")
    temporary = target.parent / (".tmp-worker-batch-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


def create_manifest(manifest_path, slots, prompts):
    if not slots or len(slots) != len(prompts):
        raise BatchError("--slots and --prompts must contain the same non-zero count")
    if len(slots) != len(set(slots)):
        raise BatchError("slot names must be unique")
    rows = []
    for slot, prompt in zip(slots, prompts):
        if SLOT_RE.fullmatch(slot) is None:
            raise BatchError(f"invalid slot name: {slot}")
        source, raw = _read_regular(prompt, f"prompt for {slot}")
        if not raw:
            raise BatchError(f"prompt for {slot} is empty")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            raise BatchError(f"prompt for {slot} is not UTF-8")
        rows.append({
            "name": slot,
            "prompt": source.relative_to(ROOT).as_posix(),
            "prompt_sha256": _sha256(raw),
        })
    document = {"schema_version": SCHEMA_VERSION, "slots": rows}
    raw = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = _write_new(manifest_path, raw)
    return target, _sha256(raw)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_terminal(meta):
    return (
        meta.get("status") in TERMINAL_STATUSES
        and isinstance(meta.get("finished_at"), str)
        and _is_int(meta.get("process_exit"))
        and _is_int(meta.get("wrapper_exit"))
    )


def verify_coverage(manifest_path, runs_dir):
    manifest, manifest_sha = load_manifest(manifest_path)
    expected = {row["name"]: row for row in manifest["slots"]}
    runs = _workspace_path(runs_dir)
    terminals = {slot: [] for slot in expected}
    errors = []
    if runs.exists() and not runs.is_dir():
        raise BatchError("runs path is not a directory")
    if runs.is_dir():
        _reject_symlink_components(runs)
        run_dirs = []
        for child in runs.iterdir():
            try:
                if stat.S_ISDIR(child.lstat().st_mode):
                    run_dirs.append(child)
            except OSError:
                continue
        for run_dir in sorted(run_dirs):
            meta_path = run_dir / "meta.json"
            try:
                if not stat.S_ISREG(meta_path.lstat().st_mode):
                    continue
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(meta, dict):
                continue
            batch = meta.get("batch")
            if not isinstance(batch, dict) or batch.get("manifest_sha256") != manifest_sha:
                continue
            slot = batch.get("slot")
            if not isinstance(slot, str) or slot not in expected:
                errors.append(f"unknown slot in {meta_path.parent.name}")
                continue
            if not _is_terminal(meta):
                continue
            if meta.get("schema_version") != 2:
                errors.append(f"meta schema mismatch for {slot}")
                continue
            if batch.get("prompt_sha256") != expected[slot]["prompt_sha256"]:
                errors.append(f"prompt SHA mismatch for {slot}")
                continue
            terminals[slot].append(meta_path)
    for slot, records in terminals.items():
        if len(records) > 1:
            errors.append(f"duplicate terminal meta for {slot}")
    if errors:
        return "FAIL", [], errors
    missing = [row["name"] for row in manifest["slots"] if not terminals[row["name"]]]
    if missing:
        return "INCONCLUSIVE_COVERAGE", missing, []
    return "PASS", [], []


def _slots(value):
    slots = [item.strip() for item in value.split(",")]
    if not slots or any(not item for item in slots):
        raise argparse.ArgumentTypeError("--slots must be a comma-separated non-empty list")
    return slots


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("manifest")
    create.add_argument("--slots", required=True, type=_slots)
    create.add_argument("--prompts", required=True, nargs="+")
    verify = subparsers.add_parser("verify")
    verify.add_argument("manifest")
    verify.add_argument("--runs", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            target, digest = create_manifest(args.manifest, args.slots, args.prompts)
            print(f"created: {target.relative_to(ROOT).as_posix()}")
            print(f"manifest_sha256: {digest}")
            return 0
        verdict, missing, errors = verify_coverage(args.manifest, args.runs)
        print(verdict)
        if missing:
            print("missing: " + ",".join(missing))
        for error in errors:
            print(error, file=sys.stderr)
        return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE_COVERAGE": 2}[verdict]
    except BatchError as exc:
        if args.command == "verify":
            print("FAIL")
            print(str(exc), file=sys.stderr)
            return 1
        print(f"worker-batch input rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
