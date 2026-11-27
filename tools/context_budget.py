#!/usr/bin/env python3
"""Measure the context a Claude Code session here starts with before any work is done.

Items: instruction files the runtime reads by itself (CLAUDE.md with its @imports, AGENTS.md),
the name and description of each skill under .claude/skills/, which Claude Code lists to the model,
the state injected at SessionStart (now.py), other SessionStart hook output (triggers), hook output
added to every prompt, and the runtime's own memory index (Claude Code MEMORY.md). Hook output is
counted only for hooks .claude/settings.json declares, so an undeclared hook costs zero. Each
item gets bytes, characters, and an approximate token count. This is a lookup: it writes no file.

  context_budget.py [--json]
"""
import argparse
import json
import os
import re
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import now
import paths as P

# Messages this module prints in more than one place, or too long to read inline.
MEMORY_HINT = (
    "Memory index over its warning line ({path}): move lines that apply to one kind of work "
    "into a sub-index file <name>-index.md in the same folder and keep one line in MEMORY.md "
    "that links it. now.py check counts links one level down from MEMORY.md."
)
NOTE_ERROR = "{source} failed ({error_type}); see the estimate above"
NOTE_GATE_RESUME = (
    "gate.py resume: 0 unless the previous turn was blocked or gate issues are still pending"
)
NOTE_NOTES = (
    "notes.py hook: 0 unless another session left a note this one was not shown, at most 600 "
    "bytes"
)
NOTE_SETTINGS_SHAPE = (
    "{path} is empty or not valid hook JSON, so Claude Code runs none of its hooks; they count "
    "0"
)
NOTE_UNMEASURED = "unmeasured hook: {command}"
NOTE_TASKS = (
    "tasks.py: 0 when nothing runs in the background, at most {limit} bytes, and at a prompt "
    "only when it changed"
)
TOKEN_RULE = "approx: 1 per Hangul/CJK/kana char, 1 per 4 other chars"
TITLE = f"Fixed context per Claude Code session (tokens {TOKEN_RULE})"


# Warning lines in bytes. These are starting values, not measured optima: they keep the fixed
# cost well under what a single long tool output adds, and are meant to be tuned per instance in
# the instance config's thresholds.
DEFAULT_LIMITS = {
    "context_instructions_max_bytes": 8192,
    "context_memory_index_max_bytes": 12288,
    "context_fixed_max_bytes": 24576,
}
# State has no line of its own: the state step already caps it (now_hook_max_bytes), so a line
# under the cap fires whenever state is full. It still counts toward the total.
ITEM_LIMIT_KEYS = {
    "instructions": "context_instructions_max_bytes",
    "memory_index": "context_memory_index_max_bytes",
}
ITEM_ORDER = ("instructions", "skills", "state", "session_hooks", "prompt_hooks", "memory_index")
NOTE_SKILLS = ("each skill's name and description as its file gives them; the text Claude Code puts "
               "around them is not counted")
# Claude Code follows @imports this many hops deep.
IMPORT_DEPTH = 5
SETTINGS = os.path.join(".claude", "settings.json")

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
        rel = os.path.relpath(path, P.instance_root())
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
        path = os.path.join(P.instance_root(), name)
        if os.path.isfile(path):
            visit(path, 0)
    return {"method": "measured", "parts": parts, "notes": []}


def measure_skills():
    """The name and description lines of every skill Claude Code finds in this folder."""
    folder = os.path.join(P.instance_root(), ".claude", "skills")
    parts = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
        text = _read(os.path.join(folder, name, "SKILL.md"))
        front = re.match(r"---\n(.*?)\n---\n", text or "", re.S)
        if front:
            listed = "".join(line + "\n" for line in front.group(1).splitlines()
                             if line.startswith(("name:", "description:")))
            parts.append(_measure_text(f".claude/skills/{name}", listed))
    return {"method": "estimate" if parts else "measured", "parts": parts,
            "notes": [NOTE_SKILLS] if parts else []}


def measure_state():
    """The SessionStart state body.

    now.build_context() re-renders a stale NOW snapshot before reading it, so it is called only
    when the snapshots are current. Otherwise the existing snapshot files, capped at the hook byte
    limit, stand in for it.
    """
    note = None
    try:
        fresh = now.snapshots_current()
    except Exception:
        fresh = False
    if fresh:
        try:
            return {"method": "exact",
                    "parts": [_measure_text("now.py hook-context", now.build_context())],
                    "notes": []}
        except Exception as e:
            note = NOTE_ERROR.format(source="build_context", error_type=type(e).__name__)
    texts = [text for text in (_read(P.now_page()), _read(P.now_page("private"))) if text]
    joined = now.clip_utf8("".join(texts), C.threshold("now_hook_max_bytes")) if texts else ""
    notes = [note] if note else []
    if not texts:
        notes.append("state/NOW.md absent: the hook injects its short failure notice instead")
    return {"method": "estimate", "parts": [_measure_text("state/NOW.md", joined)],
            "notes": notes}


def measure_triggers(today=None):
    """The body the reminders step injects, built the way it does without counting it as shown."""
    import triggers
    try:
        body = triggers.hook_preview(today)
    except Exception as e:
        return {"method": "unmeasured", "parts": [],
                "notes": [NOTE_ERROR.format(source="triggers", error_type=type(e).__name__)]}
    if not body:
        return {"method": "measured", "parts": [], "notes": []}
    return {"method": "measured", "parts": [_measure_text("triggers.py hook", body)], "notes": []}


def _hook_steps():
    """Return ({event: [(step id, None) or (None, command)]}, problem): a line of the launcher's
    event form stands for the dispatcher's steps, measured one by one, and any other line for
    its command, which is not run.
    problem names the settings file when it is not JSON of the documented shape; Claude Code then
    runs none of its hooks, so they count zero."""
    text = _read(os.path.join(P.instance_root(), SETTINGS))
    if text is None:
        return {}, None
    try:
        # A blank file is named like a malformed one: doctor reports it the same way.
        import hookdiag
        declared = {event: [h["command"] for h in handlers]
                    for event, handlers in hookdiag.declared("claude", json.loads(text)).items()}
    except (ValueError, AttributeError, TypeError, KeyError):
        return {}, NOTE_SETTINGS_SHAPE.format(path=SETTINGS)
    import dispatch
    out = {}
    for event, commands in declared.items():
        for command in commands:
            line = dispatch.EVENT_LINE.search(command) if isinstance(command, str) else None
            out.setdefault(event, []).extend(
                [(step.id, None) for step in dispatch.steps(*line.groups())] if line
                else [(None, command if isinstance(command, str) else repr(command))])
    return out, None


def tasks_limit():
    import tasks
    return tasks.MAX_BYTES


def _unarmed():
    # One line, and only when doctor last found another installed runtime's hooks not armed.
    import hookdiag
    return _measure_text("hookdiag.py unarmed", hookdiag.unarmed_notice(P.instance_root(), "claude"))


def _date():
    import dispatch
    return _measure_text("date", time.strftime(dispatch.TIME_FORMAT) + "\n")


# What a dispatcher step adds, by step id: a measured part, or a note on what it adds and when.
# A step missing here is not run, since it may write files or print private material, and counts
# as unmeasured. The state and reminders steps are measured as items of their own.
STEP_COST = {
    "arming": _unarmed,
    "time": _date,
    # Notes print only what a session has not been shown, at most notes.PRINT_MAX bytes.
    "notes": lambda: NOTE_NOTES,
    # Its size depends on what other sessions run at that moment, which a measurement here would
    # not see.
    "tasks": lambda: NOTE_TASKS.format(limit=tasks_limit()),
    # gate resume prints only after a turn that failed verification.
    "resume": lambda: NOTE_GATE_RESUME,
}


def _add_steps(item, hooks, skip=()):
    """Add each hook's cost to an item: a part, a note, or one more unmeasured hook."""
    for step, command in hooks:
        if step in skip:
            continue
        if step not in STEP_COST:
            item["notes"].append(NOTE_UNMEASURED.format(command=_shown(step, command)))
            item["unmeasured"] += 1
            continue
        cost = STEP_COST[step]()
        item["parts" if isinstance(cost, dict) else "notes"].append(cost)
    if item["unmeasured"] and item["method"] == "measured":
        item["method"] = "partial"
    return item


def measure_session_hooks(hooks):
    item = measure_triggers() if any(step == "reminders" for step, _ in hooks) else \
        {"method": "measured", "parts": [], "notes": []}
    # An unreadable trigger store leaves its hook out of the total like any hook not run.
    item["unmeasured"] = 1 if item["method"] == "unmeasured" else 0
    # The index step starts work behind the session and prints nothing.
    return _add_steps(item, hooks, skip=("state", "reminders", "index"))


def measure_prompt_hooks(hooks):
    return _add_steps({"method": "measured", "parts": [], "notes": [], "unmeasured": 0}, hooks)


def _shown(step, command):
    return f"step {step}" if step else command[:60]


def memory_index_path():
    # Same derivation as now.py check: the auto-memory folder sits in the transcript folder.
    return os.path.join(P.transcripts(), "memory", "MEMORY.md")


def measure_memory_index():
    text = _read(memory_index_path())
    if text is None:
        return {"method": "absent", "parts": [], "notes": []}
    return {"method": "measured", "parts": [_measure_text("MEMORY.md", text)], "notes": []}


def _limits():
    configured = C.data().get("thresholds", {}) if isinstance(C.data(), dict) else {}
    return {key: configured.get(key, value) for key, value in DEFAULT_LIMITS.items()}


def measure():
    limits = _limits()
    hooks, problem = _hook_steps()
    session = hooks.get("SessionStart", [])
    measured = {
        "instructions": measure_instructions(),
        "skills": measure_skills(),
        "state": (measure_state() if ("state", None) in session
                  else {"method": "measured", "parts": [], "notes": []}),
        "session_hooks": measure_session_hooks(session),
        "prompt_hooks": measure_prompt_hooks(hooks.get("UserPromptSubmit", [])),
        "memory_index": measure_memory_index(),
    }
    if problem:
        measured["session_hooks"].update(method="unmeasured", unmeasured=1,
                                         notes=measured["session_hooks"]["notes"] + [problem])
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
    # The total leaves these hooks out, so callers can say it is partial.
    unmeasured = sum(measured[key].get("unmeasured", 0) for key in ITEM_ORDER)
    if total["over"]:
        warnings.append("total")
    leaves.sort(key=lambda leaf: (-leaf["bytes"], leaf["name"]))
    return {"items": items, "total": total, "top": leaves[:3], "warnings": warnings,
            "token_rule": TOKEN_RULE, "unmeasured": unmeasured}


def _row(label, values, limit, over):
    mark = f"{limit:>7}" if limit is not None else f"{'-':>7}"
    flag = "  " + "OVER" if over else ""
    return (f"{label:<30} {values['bytes']:>8} {values['chars']:>8} {values['tokens']:>8}"
            f" {mark}{flag}")


# Row labels of the report, by item key.
ITEM_LABEL = {
    "instructions": "instruction files",
    "skills": "skill names and descriptions",
    "state": "state injection",
    "session_hooks": "other SessionStart hooks",
    "prompt_hooks": "per-prompt hooks (one turn)",
    "memory_index": "runtime memory index",
}


def print_report(report):
    print(TITLE)
    print(f"{'item':<30} {'bytes':>8} {'chars':>8} {'~tokens':>8} {'warn':>7}")
    for row in report["items"]:
        label = ITEM_LABEL[row["key"]]
        if row["method"] == "absent":
            print(f"{label:<30} absent")
            continue
        if row["method"] in ("estimate", "unmeasured", "partial"):
            label += f" ({row['method']})"
        print(_row(label, row, row["limit"], row["over"]))
        if len(row["parts"]) > 1:
            for part in row["parts"]:
                print(_row("  " + part["name"], part, None, False))
        for note in row["notes"]:
            print(f"  · {note}")
    total = report["total"]
    print(_row("total", total, total["limit"], total["over"]))
    top = ", ".join(f"{leaf['name']} {leaf['bytes']}" for leaf in report["top"])
    print("largest three: {items}".format(items=top or "-"))
    if "memory_index" in report["warnings"]:
        print(MEMORY_HINT.format(path=memory_index_path()))


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
