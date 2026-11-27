#!/usr/bin/env python3
"""List the bounded worker runs fresh_worker.py recorded, and render and show their receipts.

A receipt is the short text a worker run prints for its caller: the verdict first, then where the
full result lives, then the run's facts and the start of the result, within a byte budget.
`show` prints one run's record and its whole receipt without loading the worker engine.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
RESULT_CHANGED = (
    "result.txt no longer matches the result_sha256 the run recorded; the verdict is withheld"
)
RUN_NOT_FOUND = "run not found: {run_id}"
TOTAL = (
    "total runs={runs} tokens={tokens} (usage from {measured} runs) failures={failures} still "
    "marked running={running}"
)


# The one list of run statuses fresh_worker.py writes and this ledger counts. An interrupted run
# has no finished_at, so it is kept apart from the finished statuses.
FINISHED_STATUSES = (
    "success",
    "failed",
    "failed-missing-result",
    # Records written before scope_violation moved into scope.status still carry it here.
    "scope_violation",
    "artifact-capture-failed",
    "artifact-capture-incomplete",
    "read-material-changed",
    "expected-output-missing",
    "timeout",
)
INTERRUPTED_STATUS = "interrupted"
FAILED_STATUSES = frozenset(FINISHED_STATUSES) - {"success"} | {INTERRUPTED_STATUS}

# Bytes, not characters: a Hangul character and three or four ASCII characters cost about the same
# tokens, so a byte cap bounds the caller's context cost evenly across languages.
RECEIPT_MAX_BYTES = 4096
RECEIPT_LINE_MAX_BYTES = 512
RESULT_CONTRACT_PREFIX = "RESULT_JSON: "
RESULT_VERDICTS = {"PASS", "FAIL", "INCONCLUSIVE"}
# The first line of every worker prompt, and the capability that adds the read-only block.
CONTRACT_HEADER = "[fresh bounded worker contract]"
READ_ONLY = "read-only"
_HEADER_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
# Bytes kept for the start of a partly shown unknown, so a counted line never ends on a bare "; ".
_UNKNOWN_MIN_START_BYTES = 24


ROOT = Path(P.instance_root())
RUNS = Path(P.runs(str(ROOT)))


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


def worker_prompt(capability, body):
    """The prompt a worker gets: the contract blocks, then the caller's prompt body. A read-only
    worker gets a second block. The list below finds the body again after these blocks."""
    common = (
        CONTRACT_HEADER + "\n"
        f"- runtime capability: {capability}\n"
        "- This is a fresh, non-resumable worker. Read AGENTS.md and the named disk sources.\n"
        "- Do not commit, push, send, pay, submit, or change state journals/NOW; the dispatcher owns state.\n"
        "- Put durable work in the exact artifact paths authorized by the request.\n"
        "- Include READ_SCOPE: with the files actually read, and UNREAD: with requested material not read. "
        "These optional declarations are self-reports, not proof of access or use.\n"
        "- End with a concise result that lists evidence, changed artifact paths, tests, and remaining unknowns.\n"
        "- Every factual claim in the result names the file path (and line or section) it came from; "
        "a claim without a source goes under remaining unknowns.\n"
        "- End with exactly one machine-readable final line: " + RESULT_CONTRACT_PREFIX +
        '{"verdict":"PASS|FAIL|INCONCLUSIVE","summary":"...","evidence":["path:line"],'
        '"unknowns":["..."]}. Use an empty unknowns list when nothing remains.\n\n'
    )
    if capability == READ_ONLY:
        common += (
            "- You are a read-only reviewer. Write/Edit/Bash and external action tools are unavailable.\n"
            "- Report executable verification that the dispatcher should run; do not claim you ran it.\n\n"
        )
    return common + body


def _prompt_first_line(run_dir, capability):
    """The first line of the caller's prompt in a run's prompt.md, cut to 60 characters. Every
    prompt the engine has written is the header, blocks of "-" lines that each end in a blank line,
    then the body; reading that shape also finds the body under older contract wording."""
    path = run_dir / "prompt.md"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "-"
    if not lines:
        return "-"
    if lines[0] == CONTRACT_HEADER:
        i = 1
        for _block in range(2 if capability == READ_ONLY else 1):
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


def _load_run(meta_path, prompt=True):
    """One run's record from its meta.json; raises OSError or ValueError when unreadable."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("meta root is not an object")
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    scope = meta.get("scope") if isinstance(meta.get("scope"), dict) else {}
    runtime = meta.get("runtime") if isinstance(meta.get("runtime"), str) else "-"
    run_id = meta.get("run_id") if isinstance(meta.get("run_id"), str) else meta_path.parent.name
    return {
        "run_id": run_id,
        "started_at": meta.get("started_at"),
        "_started": _parse_time(meta.get("started_at")),
        "runtime": runtime,
        "status": meta.get("status") if isinstance(meta.get("status"), str) else "-",
        "usage": {key: _number(usage.get(key)) for key in ("input", "output", "total")},
        "scope": scope.get("status") if isinstance(scope.get("status"), str) else "-",
        "patch_files": _patch_count(meta),
        "prompt": _prompt_first_line(meta_path.parent, meta.get("capability")) if prompt else "-",
        "_dir": meta_path.parent,
        "_meta": meta,
    }


def _name_time(name):
    """The start time a run folder name begins with (fresh_worker's run id), or None."""
    try:
        return datetime.datetime.strptime(name[:20], "%Y%m%dT%H%M%S%z")
    except ValueError:
        return None


def load_runs(root=RUNS, since=None, prompt=True):
    """All readable runs, newest first. since skips older run folders by name before reading them;
    prompt=False leaves the prompt files unread."""
    root = Path(root)
    records, errors = [], []
    if not root.is_dir():
        return records, errors
    for meta_path in sorted(root.glob("*/meta.json")):
        named = _name_time(meta_path.parent.name)
        if since is not None and named is not None and named < since:
            continue
        try:
            records.append(_load_run(meta_path, prompt))
        except (OSError, ValueError) as exc:
            errors.append({"run_id": meta_path.parent.name, "error": str(exc)})
    records.sort(key=lambda row: row["_started"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
                 reverse=True)
    return records, errors


def totals(records):
    """Counts of recorded statuses only. A run still marked running may be live or lost; its age
    cannot tell (a --timeout can be up to 7 days), so it is counted apart, not as a failure."""
    usage = {
        key: sum(row["usage"][key] or 0 for row in records)
        for key in ("input", "output", "total")
    }
    return {
        "runs": len(records),
        "usage": usage,
        "measured": sum(1 for row in records if any(v is not None for v in row["usage"].values())),
        "failures": sum(1 for row in records if row["status"] in FAILED_STATUSES),
        "running": sum(1 for row in records if row["status"] == "running"),
    }


def recent_runs(records, days=7, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)
    return [row for row in records
            if row["_started"] is not None and row["_started"] >= cutoff]


def usage_text(usage):
    return "/".join("-" if usage[key] is None else str(usage[key])
                    for key in ("input", "output", "total"))


def _time_text(row):
    value = row["_started"]
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "-"


def _print_list(records, errors):
    for row in records:
        patch = f" patch={row['patch_files']}" if row["patch_files"] is not None else ""
        print(f"{_time_text(row)} {row['runtime']} {row['status']} "
              f"usage={usage_text(row['usage'])} scope={row['scope']}{patch} "
              f"prompt={row['prompt']} id={row['run_id']}")
    sums = totals(records)
    print(TOTAL.format(runs=sums['runs'], tokens=usage_text(sums['usage']), measured=sums['measured'], failures=sums['failures'], running=sums['running']))
    if errors:
        print(f"warning unreadable={len(errors)}", file=sys.stderr)


def cmd_list(_args):
    records, errors = load_runs()
    _print_list(records, errors)
    return 0


def result_contract(result):
    """Validate the machine-readable final-result line without inferring from prose."""
    def invalid(error):
        return {
            "schema_version": 1,
            "valid": False,
            "verdict": "INCONCLUSIVE",
            "summary": "structured result unavailable",
            "evidence": [],
            "unknowns": [error],
            "error": error,
        }

    if not isinstance(result, str) or not result.strip():
        return invalid("result is missing")
    lines = result.splitlines()
    candidates = [line for line in lines if line.startswith(RESULT_CONTRACT_PREFIX)]
    if len(candidates) != 1:
        return invalid("exactly one RESULT_JSON line is required")
    if candidates[0] != next(line for line in reversed(lines) if line.strip()):
        return invalid("RESULT_JSON must be the final non-empty line")
    try:
        payload = json.loads(candidates[0][len(RESULT_CONTRACT_PREFIX):])
    except json.JSONDecodeError:
        return invalid("RESULT_JSON is not valid JSON")
    required = {"verdict", "summary", "evidence", "unknowns"}
    if not isinstance(payload, dict) or set(payload) != required:
        return invalid("RESULT_JSON fields must be verdict, summary, evidence, unknowns")
    if not isinstance(payload.get("verdict"), str) or payload["verdict"] not in RESULT_VERDICTS:
        return invalid("RESULT_JSON verdict is not PASS, FAIL, or INCONCLUSIVE")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        return invalid("RESULT_JSON summary must be a non-empty string")
    for field in ("evidence", "unknowns"):
        values = payload.get(field)
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip()
                                                   for value in values):
            return invalid(f"RESULT_JSON {field} must be a list of non-empty strings")
    if not payload["evidence"]:
        return invalid("RESULT_JSON evidence must contain at least one path or section")
    return {
        "schema_version": 1,
        "valid": True,
        **payload,
        "error": None,
    }


def _utf8_prefix(text, max_bytes):
    """Longest prefix of text within max_bytes that ends on a UTF-8 character boundary."""
    return text.encode("utf-8")[:max(0, max_bytes)].decode("utf-8", errors="ignore")


def _clip_line(text, max_bytes=RECEIPT_LINE_MAX_BYTES):
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    return _utf8_prefix(text, max_bytes - len("…".encode("utf-8"))) + "…"


def _header_value(value):
    """Show line breaks and other control characters in a header value as escapes.

    Receipt readers split the header into "name: value" lines, so a raw line break inside a
    value written by a worker could add a second verdict or a false full-text command.
    """
    out = []
    for ch in str(value):
        if ch in _HEADER_ESCAPES:
            out.append(_HEADER_ESCAPES[ch])
        elif unicodedata.category(ch) in ("Cc", "Zl", "Zp"):
            code = ord(ch)
            out.append(f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}")
        else:
            out.append(ch)
    return "".join(out)


def _unknowns_line(unknowns, max_bytes=RECEIPT_LINE_MAX_BYTES):
    """Join the worker's unknowns on one header line.

    When they do not all fit, the line starts with the total and the number not fully shown
    (a cut item counts as not shown), then as many whole items as fit and the start of the
    next one; a reader then knows that something is missing even when the cut item was the
    important one.
    """
    items = [_header_value(item) for item in unknowns]
    plain = "unknowns: " + "; ".join(items)
    if len(plain.encode("utf-8")) <= max_bytes:
        return plain
    total = len(items)
    for whole in range(total - 1, -1, -1):
        listed = "".join(item + "; " for item in items[:whole])
        shown = whole + 1
        if len(f"unknowns: {total} total, {total - shown} not fully shown; {listed}{items[whole]}"
               .encode("utf-8")) > max_bytes:
            shown = whole  # the next item will be cut
        lead = f"unknowns: {total} total, {total - shown} not fully shown; {listed}"
        if whole == 0 or len(lead.encode("utf-8")) + _UNKNOWN_MIN_START_BYTES <= max_bytes:
            return _clip_line(lead + items[whole], max_bytes)
    return _clip_line(plain, max_bytes)


def _expect_line(expect):
    total = len(expect["paths"])
    if not expect["missing"]:
        return f"expect: {expect['present']}/{total} present"
    missing = ", ".join(f"{_header_value(item['path'])} ({item['why']})"
                        for item in expect["missing"])
    return _clip_line(f"expect: missing {missing}; {expect['present']}/{total} present")


def _receipt_verdict(meta, contract, withheld):
    """(verdict line value, the worker's own verdict when the run status outranks it, else None)."""
    expect = meta.get("expect") if isinstance(meta.get("expect"), dict) else None
    status = meta.get("status")
    if withheld is not None:
        return f"WITHHELD ({_header_value(withheld)})", None
    # A timeout or failure is named even when an expected output is also missing.
    if expect is not None and expect["missing"] and status in (None, "success", "expected-output-missing"):
        return "INCONCLUSIVE (expected output missing)", None
    if status is not None and status != "success":
        # The worker's own PASS cannot outrank a run the wrapper judged failed.
        worker = contract["verdict"] if contract["valid"] and contract["verdict"] != "INCONCLUSIVE" else None
        return f"INCONCLUSIVE (run status: {_header_value(status)})", worker
    if contract["valid"]:
        return contract["verdict"], None
    return f"INCONCLUSIVE ({_header_value(contract['error'])})", None


def _run_facts(meta):
    """The header lines after the decision fields: the run's place, runtime, exits and hashes."""
    def field(key, record=meta):
        value = record.get(key)
        return "-" if value is None else _header_value(value)

    scope = meta.get("scope") if isinstance(meta.get("scope"), dict) else {}
    worktree = meta.get("worktree") if isinstance(meta.get("worktree"), dict) else {}
    lines = [
        f"run: {_clip_line(field('run'), 256)}",
        f"runtime: {field('runtime')}",
        f"capability: {field('capability')}",
        f"where: {field('where')}",
        f"network: {'-' if meta.get('network') is None else ('on' if meta.get('network') else 'off')}"
        # agy's URL actions are denied, but whether that also stops its search tools is unmeasured.
        + (" (unverified: agy search)" if meta.get("runtime") == "gemini" and meta.get("network") is False else ""),
        f"model: {field('model')}",
        f"effort: {field('effort')}",
        f"status: {field('status')}",
        f"process_exit: {field('process_exit')}",
        f"wrapper_exit: {field('wrapper_exit')}",
        *(_clip_line(f"stderr: {_header_value(line)}") for line in meta.get("stderr_tail") or ()
          if isinstance(line, str)),
        *(_clip_line(f"error: {_header_value(line)}") for line in meta.get("runtime_error") or ()
          if isinstance(line, str)),
        f"prompt_sha256: {field('prompt_sha256')}",
        f"stream_sha256: {field('stream_sha256')}",
        f"result_sha256: {field('result_sha256')}",
        f"result_bytes: {field('result_bytes')}",
        f"scope: {field('status', scope)} "
        f"(changed {field('changed_count', scope)}, violations {field('violation_count', scope)})",
    ]
    if worktree.get("mode") is not None:
        dropped = worktree.get("ignored_dropped_count")
        lines.append(f"patch: {len(worktree['files'])} files "
                     f"(+{worktree['added']}/-{worktree['deleted']})"
                     + (f"; {dropped} ignored outputs dropped" if dropped else "")
                     + ("; dropped-output listing unavailable" if worktree.get("ignored_dropped_error") else ""))
    return lines


def _fit(fixed, body, max_bytes, show):
    """The header and as much of the body as max_bytes allows, from its start, with a marker that
    says how much was kept and where the full result is. max_bytes None keeps everything."""
    fixed_bytes = len(fixed.encode("utf-8"))
    body_bytes = len(body.encode("utf-8"))
    if max_bytes is None or fixed_bytes + body_bytes <= max_bytes:
        return fixed + body

    def marker(kept):
        return (f"\n[truncated: kept the first {kept} of {body_bytes} bytes; "
                f"full result: {show}]\n")

    # The kept count is part of the marker, so size the marker for the widest count first.
    room = max_bytes - fixed_bytes - len(marker(body_bytes).encode("utf-8"))
    if room < 128:
        raise AssertionError("receipt fixed fields exceed the byte budget")
    kept = _utf8_prefix(body, room)
    receipt = fixed + kept + marker(len(kept.encode("utf-8")))
    if len(receipt.encode("utf-8")) > max_bytes:
        raise AssertionError("receipt byte budget calculation failed")
    return receipt


def render_receipt(meta, result, max_bytes=RECEIPT_MAX_BYTES, withheld=None):
    """The caller-facing receipt of one run record and its result text.

    fresh_worker.py prints it within max_bytes; show prints it whole with max_bytes=None. withheld
    names why no verdict may be read from result (show: the result bytes changed). The decision
    fields come first: verdict, the worker's unknowns, and where the full text lives. A long result
    keeps its beginning, so a cut can drop the RESULT_JSON tail but never the verdict.
    """
    expect = meta.get("expect") if isinstance(meta.get("expect"), dict) else None
    run_id = _clip_line(_header_value(meta.get("run_id")
                                      or os.path.basename(str(meta.get("run") or ""))
                                      or "<run-id>"), 256)
    show = f"python3 tools/receipts.py show {run_id}"
    contract = result_contract(result)
    verdict, worker_verdict = _receipt_verdict(meta, contract, withheld)
    head = ["FRESH_WORKER v1", f"verdict: {verdict}"]
    if worker_verdict is not None:
        head.append(f"worker_verdict: {worker_verdict}")
    if withheld is None and contract["valid"] and contract["unknowns"]:
        head.append(_unknowns_line(contract["unknowns"]))
    head.append(f"full: {show}")
    if expect is not None:
        head.append(_expect_line(expect))
    head += _run_facts(meta)
    body = result if result else "[final result unavailable; inspect the private run record]"
    body += "" if body.endswith("\n") else "\n"
    return _fit("\n".join(head) + "\nresult:\n", body, max_bytes, show)


def _meta_value(meta, key):
    value = meta.get(key)
    return "-" if value is None else str(value)


def cmd_show(args):
    # A run id starts with its timestamp, so "." and ".." never name a run folder.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", args.id):
        print(RUN_NOT_FOUND.format(run_id=args.id), file=sys.stderr)
        return 1
    try:
        row = _load_run(RUNS / args.id / "meta.json")
    except (OSError, ValueError):
        print(RUN_NOT_FOUND.format(run_id=args.id), file=sys.stderr)
        return 1
    meta = row["_meta"]
    scope = meta.get("scope") if isinstance(meta.get("scope"), dict) else {}
    print(f"META {row['run_id']}")
    print(f"time: {_meta_value(meta, 'started_at')} -> {_meta_value(meta, 'finished_at')}")
    print(f"runtime: {row['runtime']} · capability: {_meta_value(meta, 'capability')}")
    print(f"status: {row['status']} · process_exit: {_meta_value(meta, 'process_exit')} "
          f"· wrapper_exit: {_meta_value(meta, 'wrapper_exit')}")
    print(f"usage: {usage_text(row['usage'])}")
    print(f"scope: {row['scope']} (changed {_meta_value(scope, 'changed_count')}, "
          f"violations {_meta_value(scope, 'violation_count')})")
    print(f"prompt: {row['prompt']}")
    try:
        raw = (row["_dir"] / "result.txt").read_bytes()
    except OSError:
        raw = None
    result = "" if raw is None else raw.decode("utf-8", errors="replace")
    # The verdict is read from result.txt, so it is withheld when a recorded hash no longer matches;
    # a run that recorded no hash still shows it, with a note that the bytes are unverified.
    withheld = None
    recorded = meta.get("result_sha256")
    if not isinstance(recorded, str):
        if raw is not None:
            print((
                "this run recorded no result_sha256, so result.txt cannot be checked against it"
            ))
    elif raw is None or hashlib.sha256(raw).hexdigest() != recorded:
        withheld = "result.txt differs from result_sha256"
        print(RESULT_CHANGED)
    print("RECEIPT")
    # A clipped receipt points here for the full text, so this view never clips the result.
    sys.stdout.write(render_receipt(meta, result, max_bytes=None, withheld=withheld))
    return 0


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="list worker runs")
    listing.set_defaults(func=cmd_list)
    show = sub.add_parser("show", help="show one run")
    show.add_argument("id")
    show.set_defaults(func=cmd_show)
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
