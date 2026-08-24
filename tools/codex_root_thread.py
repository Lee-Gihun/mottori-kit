#!/usr/bin/env python3
"""기훈의 Codex 루트 스레드 id를 찾아 출력한다.

판별 기준은 최신 수정 시각이 아니라 **기훈이 직접 친 발화의 수**다. mtime으로 고르면
ask_codex.sh가 방금 만든 발주 세션이 잡힌다 (2026-08-22 실측). 제외 대상:

- 서브에이전트 rollout: 첫 줄 session_meta의 thread_source == "subagent" 또는 source.subagent
- 시스템 주입 레코드: role=user지만 태그로 시작하거나 AGENTS.md 전문, team-of-agents 프리앰블
- ask_codex.sh 발주문: "[Claude Code가 " 로 시작하는 프롬프트
"""
import glob
import json
import os
import re

DISPATCH = re.compile(r"^\[Claude Code가 ")
SYS = re.compile(r"^\s*<|^\s*#\s*AGENTS\.md instructions|^You are an agent in a team")


def authored_turns(path):
    """(기훈 발화 수, session_id) 또는 None (서브에이전트·판독 불가)."""
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
