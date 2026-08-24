#!/usr/bin/env python3
"""gate — 응답이 끝날 때 자동으로 도는 검증 게이트.

**왜 있나.** 2026-08-24 하루에 같은 실패를 세 번 했다. `rituals.md`에 "재편 후 linkcheck 필수"가
명시돼 있는데 새 산출물(킷)을 만들고 안 돌려서 깨진 참조 27개가 "검증 완료"로 나갔다.
조건부 문서는 **내가 읽어야겠다고 판단해야만** 열리고, 그 판단이 실패하는 것이 문제였다.

스킬로는 안 된다. 설명이 맞으면 뜨지만 **반드시 뜨지는 않는다** — `P(발동|해당사건) > 0`과
`P = 1`은 다르다 (codex 라운드 2). 검증은 계약이어야 하므로 결정적 훅이다.

**설계 (codex O3).**
  PostToolUse  Write/Edit 성공 → dirty 표시만 남긴다. 검사는 안 한다 (매 편집마다 돌면 비싸다)
  Stop         dirty면 검사하고, **기준선보다 나빠졌을 때만** 막는다
  pre-commit   세션 중단·외부 편집을 닫는 후방선 (별도)

**기준선보다 나빠졌을 때만 막는 이유.** 이 리포에는 이미 알려진 이슈가 있을 수 있다.
절대값으로 막으면 첫날부터 계속 막혀서 사람이 훅을 꺼버린다. 오늘 배운 것과 같다 —
안 고쳐질 경보는 경보가 아니라 소음이다.

사용:
    python3 tools/gate.py dirty     PostToolUse 훅에서 (표시만)
    python3 tools/gate.py check     Stop 훅에서 (검사하고 필요하면 차단)
    python3 tools/gate.py baseline  현재 상태를 기준선으로 저장
    python3 tools/gate.py status    지금 상태 보기
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M

DIRTY = os.path.join(M.STATE, ".gate-dirty")
BASELINE = os.path.join(M.STATE, ".gate-baseline.json")

# 검사기와 그 결과를 뽑는 정규식. 숫자가 작을수록 좋다는 규약.
CHECKS = [
    ("linkcheck", [sys.executable, os.path.join(HERE, "linkcheck.py")], r"broken: (\d+)"),
    ("now-check", [sys.executable, os.path.join(HERE, "now.py"), "check"], r"경고 (\d+)건"),
]


def _run(cmd, pat):
    """검사기를 돌리고 (숫자, 출력). 내부 호출이므로 실행 기록은 남기지 않는다."""
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=M.ROOT, env=env)
    out = r.stdout + r.stderr
    m = re.search(pat, out)
    if m:
        return int(m.group(1)), out
    return (0 if "깨끗함" in out or "이상 없음" in out else None), out


def measure():
    return {name: _run(cmd, pat)[0] for name, cmd, pat in CHECKS}


def _load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def cmd_dirty():
    os.makedirs(M.STATE, exist_ok=True)
    open(DIRTY, "w").write("1")
    return 0


def cmd_baseline():
    cur = measure()
    os.makedirs(M.STATE, exist_ok=True)
    json.dump(cur, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"기준선 저장: {cur}")
    return 0


def cmd_status():
    print(f"dirty     : {os.path.exists(DIRTY)}")
    print(f"기준선    : {_load(BASELINE, '(없음)')}")
    print(f"현재      : {measure()}")
    return 0


def cmd_check():
    """Stop 훅. 실패해도 절대 세션을 죽이지 않는다 — 어떤 예외든 조용히 통과."""
    try:
        # 루프 방지. 이미 Stop 훅 때문에 이어진 턴이면 다시 막지 않는다.
        # (한 번 막고 못 고치면 무한히 막히는 것이 이 훅의 가장 나쁜 실패다.)
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception:
            payload = {}
        if payload.get("stop_hook_active"):
            return 0
        if not os.path.exists(DIRTY):
            return 0
        base = _load(BASELINE, {})
        cur = measure()
        worse = [f"{k} {base.get(k)} → {cur[k]}" for k in cur
                 if cur[k] is not None and base.get(k) is not None and cur[k] > base[k]]
        try:
            os.remove(DIRTY)
        except OSError:
            pass
        if not worse:
            # 좋아졌으면 기준선을 당긴다. 안 그러면 고친 만큼 다시 나빠질 여지가 생긴다.
            if any(cur[k] is not None and base.get(k) is not None and cur[k] < base[k] for k in cur):
                json.dump(cur, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False)
            return 0
        M.log_run("gate", "blocked:" + ";".join(worse))
        print(json.dumps({"decision": "block", "reason":
              "이번 턴에 검사 결과가 기준선보다 나빠졌다: " + " · ".join(worse)
              + ". 고치고 끝내라. 의도한 변화면 `python3 tools/gate.py baseline`으로 기준선을 옮긴다."},
              ensure_ascii=False))
        return 0
    except Exception:
        return 0          # 게이트 자신의 고장이 세션을 막으면 안 된다


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    return {"dirty": cmd_dirty, "check": cmd_check,
            "baseline": cmd_baseline, "status": cmd_status}.get(cmd, cmd_status)()


if __name__ == "__main__":
    sys.exit(main())
