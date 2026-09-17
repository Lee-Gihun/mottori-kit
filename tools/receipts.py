#!/usr/bin/env python3
"""Human-readable ledger for bounded worker run receipts."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path(os.environ.get("MOTTORI_INSTANCE", Path(__file__).resolve().parent.parent)).expanduser().resolve()
RUNS = ROOT / "_private" / "work" / "runs"
FAILED_STATUSES = {"failed", "failed-missing-result", "interrupted", "scope_violation"}
RECEIPT_MAX_BYTES = 4096


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.datetime.now().astimezone().tzinfo)
        return parsed
    except ValueError:
        return None


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _prompt_first_line(run_dir, runtime):
    path = run_dir / "prompt.md"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "-"
    if not lines:
        return "-"
    if lines[0] == "[fresh bounded worker contract]":
        # The run snapshot prepends one common contract block and, for Claude,
        # a second read-only block. The useful prompt starts after those blocks.
        i = 1
        while i < len(lines) and lines[i].startswith("-"):
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if runtime == "claude":
            while i < len(lines) and lines[i].startswith("-"):
                i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
        line = lines[i] if i < len(lines) else "-"
    else:
        line = next((line for line in lines if line.strip()), "-")
    return line.strip()[:60] or "-"


def _patch_count(meta):
    worktree = meta.get("worktree")
    if isinstance(worktree, dict) and isinstance(worktree.get("files"), list):
        return len(worktree["files"])
    return None


def load_runs(root=RUNS):
    root = Path(root)
    records, errors = [], []
    if not root.is_dir():
        return records, errors
    for meta_path in sorted(root.glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                raise ValueError("meta root is not an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"run_id": meta_path.parent.name, "error": str(exc)})
            continue
        usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        scope = meta.get("scope") if isinstance(meta.get("scope"), dict) else {}
        runtime = meta.get("runtime") if isinstance(meta.get("runtime"), str) else "-"
        run_id = meta.get("run_id") if isinstance(meta.get("run_id"), str) else meta_path.parent.name
        records.append({
            "run_id": run_id,
            "started_at": meta.get("started_at"),
            "_started": _parse_time(meta.get("started_at")),
            "runtime": runtime,
            "status": meta.get("status") if isinstance(meta.get("status"), str) else "-",
            "usage": {key: _number(usage.get(key)) for key in ("input", "output", "total")},
            "scope": scope.get("status") if isinstance(scope.get("status"), str) else "-",
            "patch_files": _patch_count(meta),
            "prompt": _prompt_first_line(meta_path.parent, runtime),
            "_dir": meta_path.parent,
            "_meta": meta,
        })
    records.sort(key=lambda row: row["_started"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
                 reverse=True)
    return records, errors


def _totals(records):
    usage = {
        key: sum(row["usage"][key] or 0 for row in records)
        for key in ("input", "output", "total")
    }
    return {
        "runs": len(records),
        "usage": usage,
        "failures": sum(1 for row in records if row["status"] in FAILED_STATUSES),
    }


def recent_runs(records, days=7, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)
    return [row for row in records
            if row["_started"] is not None and row["_started"] >= cutoff]


def _usage_text(usage):
    return "/".join("-" if usage[key] is None else str(usage[key])
                    for key in ("input", "output", "total"))


def _time_text(row):
    value = row["_started"]
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "-"


def _print_list(records, errors):
    for row in records:
        patch = f" patch={row['patch_files']}" if row["patch_files"] is not None else ""
        print(f"{_time_text(row)} {row['runtime']} {row['status']} "
              f"usage={_usage_text(row['usage'])} scope={row['scope']}{patch} "
              f"prompt={row['prompt']} id={row['run_id']}")
    totals = _totals(records)
    print(f"합계 runs={totals['runs']} tokens={_usage_text(totals['usage'])} "
          f"failures={totals['failures']}")
    if errors:
        print(f"경고 unreadable={len(errors)}", file=sys.stderr)


def _public_row(row):
    return {key: row[key] for key in (
        "run_id", "started_at", "runtime", "status", "usage", "scope",
        "patch_files", "prompt",
    )}


def _duration(value):
    match = re.fullmatch(r"([1-9][0-9]*)([dh])", value)
    if not match:
        raise argparse.ArgumentTypeError("기간은 7d 또는 24h 형식이어야 한다")
    amount = int(match.group(1))
    return datetime.timedelta(days=amount) if match.group(2) == "d" \
        else datetime.timedelta(hours=amount)


def cmd_list(args):
    records, errors = load_runs()
    if args.since is not None:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - args.since
        records = [row for row in records
                   if row["_started"] is not None and row["_started"] >= cutoff]
    if args.runtime:
        records = [row for row in records if row["runtime"] == args.runtime]
    if args.json:
        print(json.dumps({
            "runs": [_public_row(row) for row in records],
            "totals": _totals(records),
            "errors": errors,
        }, ensure_ascii=False, indent=2))
    else:
        _print_list(records, errors)
    return 0


def _meta_value(meta, key):
    value = meta.get(key)
    return "-" if value is None else str(value)


def _utf8_prefix(text, byte_limit):
    if byte_limit <= 0:
        return ""
    return text.encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore")


def _utf8_suffix(text, byte_limit):
    if byte_limit <= 0:
        return ""
    return text.encode("utf-8")[-byte_limit:].decode("utf-8", errors="ignore")


def _clip_utf8(text, byte_limit):
    raw = text.encode("utf-8")
    if len(raw) <= byte_limit:
        return text
    marker = f"\n\n[… 중간 절단: 원문 {len(raw)} bytes …]\n\n"
    room = max(0, byte_limit - len(marker.encode("utf-8")))
    head = _utf8_prefix(text, int(room * 0.42))
    tail = _utf8_suffix(text, room - len(head.encode("utf-8")))
    if "\n" in head:
        head = head[:head.rfind("\n") + 1]
    if "\n" in tail:
        tail = tail[tail.find("\n") + 1:]
    return _utf8_prefix(head.rstrip() + marker + tail.lstrip(), byte_limit)


def _receipt(meta, result):
    scope = meta.get("scope") if isinstance(meta.get("scope"), dict) else {}
    worktree = meta.get("worktree") if isinstance(meta.get("worktree"), dict) else {}
    patch_line = ""
    if worktree.get("mode") is not None:
        patch_line = (
            f"patch: {len(worktree['files'])} files "
            f"(+{worktree['added']}/-{worktree['deleted']})\n"
        )
    fixed = (
        "FRESH_WORKER v1\n"
        f"run: {_meta_value(meta, 'run')}\n"
        f"runtime: {_meta_value(meta, 'runtime')}\n"
        f"capability: {_meta_value(meta, 'capability')}\n"
        f"status: {_meta_value(meta, 'status')}\n"
        f"process_exit: {_meta_value(meta, 'process_exit')}\n"
        f"wrapper_exit: {_meta_value(meta, 'wrapper_exit')}\n"
        f"prompt_sha256: {_meta_value(meta, 'prompt_sha256')}\n"
        f"stream_sha256: {_meta_value(meta, 'stream_sha256')}\n"
        f"result_sha256: {_meta_value(meta, 'result_sha256')}\n"
        f"result_bytes: {_meta_value(meta, 'result_bytes')}\n"
        f"scope: {scope.get('status', '-')} (changed {scope.get('changed_count', '-')}, "
        f"violations {scope.get('violation_count', '-')})\n"
        f"{patch_line}"
        "result:\n"
    )
    body = result if result else "[final result unavailable; inspect the private run record]"
    room = max(0, RECEIPT_MAX_BYTES - len(fixed.encode("utf-8")))
    return fixed + _clip_utf8(body, room)


def cmd_show(args):
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", args.id):
        print(f"run을 찾을 수 없다: {args.id}", file=sys.stderr)
        return 1
    records, _ = load_runs()
    row = next((record for record in records if record["run_id"] == args.id), None)
    if row is None:
        print(f"run을 찾을 수 없다: {args.id}", file=sys.stderr)
        return 1
    meta = row["_meta"]
    scope = meta.get("scope") if isinstance(meta.get("scope"), dict) else {}
    print(f"META {row['run_id']}")
    print(f"time: {_meta_value(meta, 'started_at')} -> {_meta_value(meta, 'finished_at')}")
    print(f"runtime: {row['runtime']} · capability: {_meta_value(meta, 'capability')}")
    print(f"status: {row['status']} · process_exit: {_meta_value(meta, 'process_exit')} "
          f"· wrapper_exit: {_meta_value(meta, 'wrapper_exit')}")
    print(f"usage: {_usage_text(row['usage'])}")
    print(f"scope: {row['scope']} (changed {scope.get('changed_count', '-')}, "
          f"violations {scope.get('violation_count', '-')})")
    print(f"prompt: {row['prompt']}")
    try:
        result = (row["_dir"] / "result.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        result = ""
    print("RECEIPT")
    sys.stdout.write(_receipt(meta, result))
    return 0


def _run_date(row):
    value = row.get("started_at")
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return "unknown"


def cmd_cost(_args):
    records, errors = load_runs()
    print("런타임별 토큰 합계 (input/output/total)")
    runtimes = sorted({row["runtime"] for row in records if row["runtime"] != "-"})
    if not runtimes:
        print("(run 없음)")
    for runtime in runtimes:
        subset = [row for row in records if row["runtime"] == runtime]
        total = _totals(subset)
        unknown = sum(1 for row in subset if row["usage"]["total"] is None)
        print(f"{runtime} runs={len(subset)} tokens={_usage_text(total['usage'])} unknown={unknown}")

    daily = {}
    for row in records:
        bucket = daily.setdefault(_run_date(row), {"runs": 0, "tokens": 0})
        bucket["runs"] += 1
        bucket["tokens"] += row["usage"]["total"] or 0
    peak = max((bucket["tokens"] for bucket in daily.values()), default=0)
    print("하루 단위 히스토그램 (total tokens)")
    if not daily:
        print("(run 없음)")
    for day in sorted(daily):
        bucket = daily[day]
        width = 0 if not bucket["tokens"] else max(1, round(bucket["tokens"] / peak * 40))
        bar = "#" * width if width else "-"
        print(f"{day} {bar} runs={bucket['runs']} tokens={bucket['tokens']}")
    if errors:
        print(f"경고 unreadable={len(errors)}", file=sys.stderr)
    return 0


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="list worker runs")
    listing.add_argument("--since", type=_duration, metavar="7d")
    listing.add_argument("--runtime", choices=("codex", "claude"))
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)
    show = sub.add_parser("show", help="show one run")
    show.add_argument("id")
    show.set_defaults(func=cmd_show)
    cost = sub.add_parser("cost", help="token totals and daily histogram")
    cost.set_defaults(func=cmd_cost)
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.error(f"{args.command}: not implemented")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
