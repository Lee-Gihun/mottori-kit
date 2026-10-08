#!/usr/bin/env python3
"""Harvest person-ledger candidates without accepting them automatically.

Read journal decisions and corrections since the ledger's last update. A reviewer chooses which candidates belong in the ledger; harvesting alone does not turn an interpretation into an attributed fact.

Commands: stale [--issues], candidates."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M

PORTRAIT = os.path.join(M.ROOT, "_private", "self-portrait-mirror.md")

# Only decisions and corrections contribute person-ledger candidates; state and artifacts describe task progress.
HARVEST_TYPES = ("correction", "decision")

# Operational backlog threshold, not a measured universal limit.
STALE_THRESHOLD = 20


def _entries():
    """Read journal events as (date, type, body)."""
    d = os.path.join(M.ROOT, "state")
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not re.match(r"^journal-\d{4}-\d{2}\.md$", fn):
            continue
        with open(os.path.join(d, fn), encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^- (\d{4}-\d{2}-\d{2})T\S*\s+\[([^/]+)/([^\]]+)\]\s*(.*)", line)
                if m:
                    out.append((m.group(1), m.group(2), m.group(3), m.group(4).rstrip()))
    return out


def _last_update():
    """Read the latest date in the ledger; unrelated file edits must not change freshness."""
    if not os.path.exists(PORTRAIT):
        return None
    with open(PORTRAIT, encoding="utf-8") as fh:
        dates = re.findall(r"20\d\d-\d\d-\d\d", fh.read())
    return max(dates) if dates else None


def stale(issues=False):
    since = _last_update()
    if since is None:
        if issues:
            print("#issues 0")
        else:
            print("[portrait] 원장 없음 — 검사 해당 없음")
        return 0
    pending = [e for e in _entries() if e[0] > since and e[2] in HARVEST_TYPES]
    if issues:
        # Keep counts out of stable issue IDs. Machine mode reports findings then a final count trailer and exits zero.
        if len(pending) >= STALE_THRESHOLD:
            print(f"portrait-stale\t인물 원장 미수확 {len(pending)}건 (마지막 {since})")
        print(f"#issues {1 if len(pending) >= STALE_THRESHOLD else 0}")
        return 0
    print(f"[portrait] 마지막 갱신 {since} · 이후 판정급 {len(pending)}건 미수확"
          f" (임계 {STALE_THRESHOLD})")
    if pending:
        by_day = {}
        for d, _, t, _ in pending:
            by_day.setdefault(d, []).append(t)
        for d in sorted(by_day):
            kinds = ", ".join(f"{k}×{by_day[d].count(k)}" for k in sorted(set(by_day[d])))
            print(f"    {d}  {kinds}")
        print("  → python3 tools/portrait.py candidates")
    return 0


def candidates(since=None):
    since = since or _last_update()
    rows = [e for e in _entries() if since and e[0] > since and e[2] in HARVEST_TYPES]
    if not rows:
        print(f"[portrait] {since} 이후 후보 없음")
        return 0
    print(f"# 인물 원장 후보 — {since} 이후 {len(rows)}건")
    print("# 자동 채택 금지. 골라서 옮긴다 (correction→교전기록 · decision→판정 기록).")
    print("# 채택 기준 둘 다 만족: ①짧은 큐로 복원 안 됨 ②두 번 말하게 하면 그가 짜증남\n")
    for d, track, typ, body in rows:
        print(f"- {d} | [{track}/{typ}] {body}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stale"
    if cmd == "stale":
        sys.exit(stale(issues="--issues" in sys.argv))
    elif cmd == "candidates":
        arg = [a for a in sys.argv[2:] if not a.startswith("-")]
        sys.exit(candidates(arg[0] if arg else None))
    else:
        print(__doc__)
        sys.exit(2)
