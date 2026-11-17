#!/usr/bin/env python3
"""Measure the context every session starts with before any work is done.

Items: instruction files the runtime reads by itself (CLAUDE.md with its @imports, AGENTS.md),
the state injected at SessionStart (now.py), other SessionStart hook output (triggers), hook output
added to every prompt, and the runtime's own memory index (Claude Code MEMORY.md). Each item gets
bytes, characters, and an approximate token count. This is a lookup: it writes no file.

  context_budget.py [--json]
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M
from i18n import t


# Warning lines in bytes. These are starting values, not measured optima: they keep the fixed
# cost well under what a single long tool output adds, and are meant to be tuned per instance in
# system/memory-config.json thresholds.
DEFAULT_LIMITS = {
    "context_instructions_max_bytes": 8192,
    # 90% of the default 6,000-byte state injection cap (now_hook_max_bytes): a line at or
    # above the cap could never be crossed, so it would never warn.
    "context_state_max_bytes": 5400,
    "context_memory_index_max_bytes": 12288,
    "context_fixed_max_bytes": 24576,
}
ITEM_LIMIT_KEYS = {
    "instructions": "context_instructions_max_bytes",
    "state": "context_state_max_bytes",
    "memory_index": "context_memory_index_max_bytes",
}
ITEM_ORDER = ("instructions", "state", "session_hooks", "prompt_hooks", "memory_index")
# Claude Code follows @imports this many hops deep.
IMPORT_DEPTH = 5
TOKEN_RULE = "approx: 1 per Hangul/CJK/kana char, 1 per 4 other chars"

_WIDE = re.compile("[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u3400-\u4dbf\u4e00-\u9fff"
                   "\uac00-\ud7a3\uf900-\ufaff]")
# An @path import may start with any letter, including a non-ASCII one; only a path that names
# a readable file is counted, so an e-mail address or a stray @ costs nothing.
_IMPORT = re.compile(r"(?:^|\s)@((?:~/|\.{1,2}/|/)?[^\s`'\")\]@][^\s`'\")\]]*)")


def estimate_tokens(text):
    wide = len(_WIDE.findall(text))
    other = len(text) - wide
    return wide + (other + 3) // 4


def _measure_text(name, text):
    return {"name": name, "bytes": len(text.encode("utf-8")), "chars": len(text),
            "tokens": estimate_tokens(text)}


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _rel(path):
    try:
        rel = os.path.relpath(path, M.ROOT)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def _imports(text, base_dir):
    """Paths a memory file imports with @path, skipping code spans and fenced blocks."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        for match in _IMPORT.finditer(re.sub(r"`[^`]*`", "", line)):
            target = os.path.expanduser(match.group(1))
            path = target if os.path.isabs(target) else os.path.join(base_dir, target)
            if os.path.isfile(path):
                out.append(path)
    return out


def measure_instructions():
    """CLAUDE.md files and their imports (Claude Code) plus AGENTS.md (Codex), each counted once."""
    seen, parts = set(), []

    def visit(path, depth):
        real = os.path.realpath(path)
        if real in seen:
            return
        text = _read(path)
        if text is None:
            return
        seen.add(real)
        parts.append(_measure_text(_rel(path), text))
        if depth < IMPORT_DEPTH:
            for child in _imports(text, os.path.dirname(path)):
                visit(child, depth + 1)

    for name in ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"), "CLAUDE.local.md",
                 "AGENTS.md"):
        path = os.path.join(M.ROOT, name)
        if os.path.isfile(path):
            visit(path, 0)
    return {"method": "measured", "parts": parts, "notes": []}


def measure_state():
    """The SessionStart state body.

    now.build_context() re-renders a stale NOW snapshot before reading it, so it is called only
    when no snapshot is stale. Otherwise the existing snapshot files, capped at the hook byte
    limit, stand in for it.
    """
    import now
    try:
        fresh = not any(now._snapshot_stale(scope) for scope in ("public", "private"))
    except Exception:
        fresh = False
    if fresh:
        try:
            return {"method": "exact",
                    "parts": [_measure_text("now.py hook-context", now.build_context())],
                    "notes": []}
        except Exception as e:
            note = t("context_budget.note_error", source="build_context", error_type=type(e).__name__)
        else:
            note = None
    else:
        note = None
    texts = [text for text in (_read(M.NOW_PATH), _read(M.PRIVATE_NOW_PATH)) if text]
    joined = M.clip_utf8("".join(texts), M.NOW_HOOK_MAX_BYTES) if texts else ""
    notes = [note] if note else []
    if not texts:
        notes.append(t("context_budget.note_now_absent"))
    return {"method": "estimate", "parts": [_measure_text("state/NOW.md", joined)],
            "notes": notes}


def measure_triggers(today=None):
    """The body triggers.py hook injects, built the way it does without counting it as shown."""
    import triggers
    if not os.path.isfile(triggers.STORE):
        return {"method": "measured", "parts": [], "notes": []}
    try:
        # _load() directly: the CLI's shared lock creates a lock file, and this tool writes nothing.
        rows = triggers._load()
        hits, _changed = triggers.due(rows, today or triggers._today(), triggers.HOOK_LIMIT,
                                      mark=False)
    except Exception as e:
        return {"method": "unmeasured", "parts": [],
                "notes": [t("context_budget.note_error", source="triggers", error_type=type(e).__name__)]}
    if not hits:
        return {"method": "measured", "parts": [], "notes": []}
    # Same text as triggers.py hook.
    body = "[triggers due today]\n" + "\n".join(triggers.format_line(r) for r in hits) + \
           ("\nfire: python3 tools/triggers.py claim <id> && "
            "python3 tools/triggers.py fire <id> --outcome '...' · "
            "sleep: python3 tools/triggers.py sleep <id>\n")
    return {"method": "measured", "parts": [_measure_text("triggers.py hook", body)], "notes": []}


def _hook_commands(event):
    cfg = _read(os.path.join(M.ROOT, ".claude", "settings.json"))
    try:
        hooks = json.loads(cfg or "{}").get("hooks", {}).get(event, [])
        return [h.get("command", "") for block in hooks for h in block.get("hooks", [])]
    except (ValueError, AttributeError):
        return []


def measure_session_hooks():
    item = measure_triggers()
    for command in _hook_commands("SessionStart"):
        if "tools/now.py" in command or "tools/triggers.py" in command:
            continue
        item["notes"].append(t("context_budget.note_unmeasured", command=command[:60]))
    return item


def measure_prompt_hooks():
    parts, notes = [], []
    for command in _hook_commands("UserPromptSubmit"):
        date = re.fullmatch(r"date '(\+[^']*)'", command.strip())
        if date:
            out = subprocess.run(["date", date.group(1)], capture_output=True, text=True).stdout
            parts.append(_measure_text("date", out))
        elif "tools/gate.py" in command and "resume" in command:
            # gate resume prints only after a turn that failed verification.
            notes.append(t("context_budget.note_gate_resume"))
        else:
            notes.append(t("context_budget.note_unmeasured", command=command[:60]))
    return {"method": "measured", "parts": parts, "notes": notes}


def memory_index_path():
    # Same derivation as now.py check: the auto-memory folder sits in the transcript folder.
    return os.path.join(M.TRANSCRIPTS, "memory", "MEMORY.md")


def measure_memory_index():
    text = _read(memory_index_path())
    if text is None:
        return {"method": "absent", "parts": [], "notes": []}
    return {"method": "measured", "parts": [_measure_text("MEMORY.md", text)], "notes": []}


def _limits():
    configured = M._CFG.get("thresholds", {}) if isinstance(M._CFG, dict) else {}
    return {key: configured.get(key, value) for key, value in DEFAULT_LIMITS.items()}


def measure():
    limits = _limits()
    measured = {
        "instructions": measure_instructions(),
        "state": measure_state(),
        "session_hooks": measure_session_hooks(),
        "prompt_hooks": measure_prompt_hooks(),
        "memory_index": measure_memory_index(),
    }
    items, leaves, warnings = [], [], []
    for key in ITEM_ORDER:
        row = measured[key]
        totals = {f: sum(p[f] for p in row["parts"]) for f in ("bytes", "chars", "tokens")}
        limit = limits.get(ITEM_LIMIT_KEYS.get(key))
        over = limit is not None and totals["bytes"] > limit
        if over:
            warnings.append(key)
        items.append({"key": key, **totals, "limit": limit, "over": over,
                      "method": row["method"], "parts": row["parts"], "notes": row["notes"]})
        leaves.extend({"item": key, "name": p["name"], "bytes": p["bytes"],
                       "tokens": p["tokens"]} for p in row["parts"])
    total = {f: sum(row[f] for row in items) for f in ("bytes", "chars", "tokens")}
    total["limit"] = limits["context_fixed_max_bytes"]
    total["over"] = total["bytes"] > total["limit"]
    if total["over"]:
        warnings.append("total")
    leaves.sort(key=lambda leaf: (-leaf["bytes"], leaf["name"]))
    return {"items": items, "total": total, "top": leaves[:3], "warnings": warnings,
            "token_rule": TOKEN_RULE}


def _row(label, values, limit, over):
    mark = f"{limit:>7}" if limit is not None else f"{'-':>7}"
    flag = "  " + t("context_budget.over") if over else ""
    return (f"{label:<30} {values['bytes']:>8} {values['chars']:>8} {values['tokens']:>8}"
            f" {mark}{flag}")


def print_report(report):
    print(t("context_budget.title"))
    print(f"{t('context_budget.col_item'):<30} {'bytes':>8} {'chars':>8} {'~tokens':>8} {'warn':>7}")
    for row in report["items"]:
        label = t(f"context_budget.item.{row['key']}")
        if row["method"] == "absent":
            print(f"{label:<30} {t('context_budget.absent')}")
            continue
        if row["method"] in ("estimate", "unmeasured"):
            label += f" ({t('context_budget.' + row['method'])})"
        print(_row(label, row, row["limit"], row["over"]))
        if len(row["parts"]) > 1:
            for part in row["parts"]:
                print(_row("  " + part["name"], part, None, False))
        for note in row["notes"]:
            print(f"  · {note}")
    total = report["total"]
    print(_row(t("context_budget.total"), total, total["limit"], total["over"]))
    top = ", ".join(f"{leaf['name']} {leaf['bytes']}" for leaf in report["top"])
    print(t("context_budget.top", items=top or "-"))
    if "memory_index" in report["warnings"]:
        print(t("context_budget.memory_hint", path=memory_index_path()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    report = measure()
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
