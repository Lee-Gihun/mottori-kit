#!/usr/bin/env python3
"""Find the owner's Codex root thread by the number of eligible owner turns.

Do not rank by modification time: a newly dispatched session may be newer.
Exclude subagent rollouts, known system envelopes, and ask_codex dispatch prompts."""
import glob
import json
import os
import re

import i18n

DISPATCH = re.compile(r"^" + re.escape(i18n.STRINGS["codex_root.dispatch_prefix"]["ko"]))
SYS = re.compile(r"^\s*<|^\s*#\s*AGENTS\.md instructions|^You are an agent in a team")


def authored_turns(path):
    """Return (owner-authored turn count, session_id), or None for subagents/unreadable data."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            meta = json.loads(f.readline())
            if meta.get("type") != "session_meta":
                return None
            p = meta.get("payload") or {}
            src = p.get("source") if isinstance(p.get("source"), dict) else {}
            if p.get("thread_source") == "subagent" or "subagent" in src:
                return None
            sid = p.get("id") or os.path.basename(path)[24:-6]
            n = 0
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                q = d.get("payload") or {}
                if q.get("type") != "message" or q.get("role") != "user":
                    continue
                t = "".join(c.get("text", "") for c in (q.get("content") or [])
                            if isinstance(c, dict)).strip()
                if not t or SYS.search(t) or DISPATCH.search(t):
                    continue
                n += 1
            return (n, sid)
    except Exception:
        return None


def main():
    best = None
    for fp in glob.glob(os.path.expanduser("~/.codex/sessions/**/*.jsonl"), recursive=True):
        got = authored_turns(fp)
        if not got or got[0] == 0:
            continue
        key = (got[0], os.path.getmtime(fp))
        if best is None or key > best[0]:
            best = (key, got[1])
    print(best[1] if best else "")


if __name__ == "__main__":
    main()
