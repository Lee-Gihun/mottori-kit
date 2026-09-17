#!/usr/bin/env python3
"""Measure UTF-8 payload bytes retained by one Claude main-thread transcript.

With no path, the newest direct ``*.jsonl`` file in the current instance's
``~/.claude/projects/<key>`` directory is used. A path may name a transcript or
such a directory. ``--budget`` returns exit 1 when the measured total exceeds
the byte limit; malformed JSONL lines are reported but do not stop the scan.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys


SOURCE_ORDER = ("hook_injection", "worker_receipt", "tool_stdout", "user", "model")
TOP_TOOL_LIMIT = 20


class InputError(ValueError):
    pass


def _positive_int(value):
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("budget must be an integer byte count")
    if parsed <= 0:
        raise argparse.ArgumentTypeError("budget must be greater than zero")
    return parsed


def _project_dir():
    root = Path(os.environ.get(
        "MOTTORI_INSTANCE", Path(__file__).resolve().parent.parent
    )).expanduser().resolve()
    key = re.sub(r"[^A-Za-z0-9-]", "-", str(root))
    return Path.home() / ".claude" / "projects" / key


def _newest_transcript(directory):
    try:
        candidates = [path for path in directory.glob("*.jsonl") if path.is_file()]
    except OSError as exc:
        raise InputError(f"cannot read transcript directory: {exc}")
    if not candidates:
        raise InputError(f"no direct *.jsonl transcript in {directory}")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def resolve_transcript(value=None):
    path = Path(value).expanduser() if value else _project_dir()
    if path.is_dir():
        return _newest_transcript(path)
    if not path.is_file():
        raise InputError(f"transcript not found: {path}")
    return path


def _bytes(value):
    """Payload bytes, excluding the JSONL envelope and JSON string escaping."""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, list):
        return sum(_bytes(item) for item in value)
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return len(raw.encode("utf-8"))


def _result_text(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _is_worker_receipt(value):
    return _result_text(value).lstrip().startswith("FRESH_WORKER v1")


def analyze(path):
    sources = {name: {"bytes": 0, "items": 0} for name in SOURCE_ORDER}
    tool_names = {}
    tool_results = {}
    invalid_lines = 0

    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                invalid_lines += 1
                continue
            if not isinstance(event, dict) or event.get("isSidechain") is True:
                continue

            if event.get("type") == "system" and event.get("subtype") == "compact_boundary":
                sources["model"]["bytes"] += _bytes(event.get("content"))
                sources["model"]["items"] += 1
                continue

            attachment = event.get("attachment")
            if (event.get("type") == "attachment" and isinstance(attachment, dict)
                    and attachment.get("type") == "hook_additional_context"):
                sources["hook_injection"]["bytes"] += _bytes(attachment.get("content"))
                sources["hook_injection"]["items"] += 1
                continue

            message = event.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")

            if role == "assistant":
                blocks = content if isinstance(content, list) else [content]
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id")
                        if isinstance(tool_id, str):
                            name = block.get("name")
                            tool_names[tool_id] = name if isinstance(name, str) else "unknown"
                        size = _bytes(block.get("input"))
                    elif isinstance(block, dict) and block.get("type") == "thinking":
                        size = _bytes(block.get("thinking"))
                    elif isinstance(block, dict) and block.get("type") == "text":
                        size = _bytes(block.get("text"))
                    else:
                        size = _bytes(block)
                    sources["model"]["bytes"] += size
                    sources["model"]["items"] += 1
                continue

            if role != "user":
                continue
            blocks = content if isinstance(content, list) else [content]
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    payload = block.get("content")
                    size = _bytes(payload)
                    tool_id = block.get("tool_use_id")
                    key = tool_id if isinstance(tool_id, str) else "unknown"
                    tool_results[key] = tool_results.get(key, 0) + size
                    source = "worker_receipt" if _is_worker_receipt(payload) else "tool_stdout"
                    sources[source]["bytes"] += size
                    sources[source]["items"] += 1
                else:
                    size = _bytes(block.get("text")) if isinstance(block, dict) \
                        and isinstance(block.get("text"), str) else _bytes(block)
                    sources["user"]["bytes"] += size
                    sources["user"]["items"] += 1

    tools = [
        {"id": tool_id, "name": tool_names.get(tool_id, "unknown"), "bytes": size}
        for tool_id, size in tool_results.items()
    ]
    tools.sort(key=lambda row: (-row["bytes"], row["name"], row["id"]))
    return {
        "sources": sources,
        "total": sum(row["bytes"] for row in sources.values()),
        "tools": tools[:TOP_TOOL_LIMIT],
        "tool_count": len(tools),
        "invalid_lines": invalid_lines,
    }


def _print_report(path, report, budget=None):
    print(f"CONTEXT_BUDGET {path}")
    for name in SOURCE_ORDER:
        row = report["sources"][name]
        print(f"{name} bytes={row['bytes']} items={row['items']}")
    print(f"total bytes={report['total']}")
    print(f"top_tools shown={len(report['tools'])} total={report['tool_count']}")
    for index, row in enumerate(report["tools"], 1):
        print(f"{index}. bytes={row['bytes']} tool={row['name']} id={row['id']}")
    if report["invalid_lines"]:
        print(f"warning invalid_jsonl_lines={report['invalid_lines']}", file=sys.stderr)
    if budget is not None:
        over = report["total"] - budget
        if over > 0:
            print(f"budget WARN total={report['total']} budget={budget} over={over}")
        else:
            print(f"budget PASS total={report['total']} budget={budget} remaining={-over}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", nargs="?", help="one *.jsonl file or project transcript directory")
    parser.add_argument("--budget", type=_positive_int, metavar="BYTES")
    args = parser.parse_args(argv)
    try:
        path = resolve_transcript(args.transcript)
        report = analyze(path)
    except (InputError, OSError) as exc:
        print(f"context-budget input rejected: {exc}", file=sys.stderr)
        return 2
    _print_report(path, report, args.budget)
    return 1 if args.budget is not None and report["total"] > args.budget else 0


if __name__ == "__main__":
    sys.exit(main())
