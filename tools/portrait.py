#!/usr/bin/env python3
"""인물 원장 수확기 — 저술하지 말고 수확한다 (`system/person-ledger.md`).

원장이 굶는 이유는 규칙이 약해서가 아니라 **손으로 따로 써야 해서**다. 저널·사실 원장·회상은
저절로 쌓이는데 원장만 별도 저술을 요구하면 바쁜 구간에서 정확히 굶는다. 그리고 바쁜 구간이
재료가 가장 많은 구간이라 손실이 가장 크다. 2026-08-26 실측: 3일 정지 동안 판정급 95건이
지나갔다.

그래서 이 도구는 **후보를 뽑아 올리기만** 한다. 채택은 판단이다 — 자동 채택하면 L3(내 해석)가
L1(그의 발화)의 옷을 입는다. 그 경계가 이 원장의 유일한 안전장치다.

  stale       마지막 갱신 이후 쌓인 판정급 항목 수 (검사기 계약 v2: --issues)
  candidates  후보 항목을 출력. 사람이 골라서 원장에 옮긴다
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M

PORTRAIT = os.path.join(M.ROOT, "_private", "self-portrait-mirror.md")

# 인물 원장에 재료가 되는 것만 센다. state·artifact는 진행 상황이라 인물 정보가 아니다.
# correction = 그가 내 모델을 고친 순간 (교전기록의 원료)
# decision   = 그가 실제로 내린 판정 (L2의 원료)
HARVEST_TYPES = ("correction", "decision")

# 이 수를 넘게 쌓이면 경고한다. 근거가 아니라 조절값이다 — 실측 3일/95건이 명백한 실패였고
# 한 세션이 판정급 5~15건을 만드니, 두어 세션 놓치는 것까지는 정상으로 본다.
STALE_THRESHOLD = 20


def _entries():
    """journal 전체를 (날짜, 타입, 본문)으로 읽는다. 월별 파일이 여러 개다."""
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
    """원장의 마지막 갱신일. 파일 안의 최신 날짜를 쓴다 — mtime은 무관한 편집에도 움직인다."""
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
        # 계약 v2: <안정ID>\t<표시문구>, #issues 는 마지막 줄, 이슈 유무와 무관하게 exit 0.
        # ID에 건수를 넣지 않는다 — 한 건 늘 때마다 새 이슈가 되면 기준선이 매번 깨진다.
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
