#!/usr/bin/env python3
"""gate — 편집이 있었던 턴이 끝날 때 자동으로 도는 검증 게이트.

**왜 있나.** 2026-08-24 하루에 같은 실패를 세 번 했다. `rituals.md`에 "재편 후 linkcheck 필수"가
명시돼 있는데 새 산출물(킷)을 만들고 안 돌려서 깨진 참조 27개가 "검증 완료"로 나갔다.
조건부 문서는 **내가 읽어야겠다고 판단해야만** 열리고, 그 판단이 실패하는 것이 문제였다.

스킬로는 안 된다. 설명이 맞으면 뜨지만 **반드시 뜨지는 않는다** — `P(발동|해당사건) > 0`과
`P = 1`은 다르다. 검증은 계약이어야 하므로 결정적 훅이다.

**개수가 아니라 이슈 집합을 본다** (codex 라운드 3). 개수는 치환에 눈이 멀었다 — 링크 하나
고치고 하나 깨면 같은 수라서 통과했다. 지금은 각 검사기가 `--issues`로 ID를 내보내고
게이트가 `현재 - 기준선`을 본다. 하나라도 새로 생기면 막는다.

**측정 불능은 개선이 아니다.** 검사기가 죽거나 트레일러(`#issues N`)를 안 내면 "이슈 0"이
아니라 "측정 실패"다. 막는다.

**시간이 만든 이슈는 안 문다.** 검사기가 `~` 접두로 표시한 것 (NOW 낡음, 부패 후보 등)은
이번 턴에 고칠 수 없다. 못 고칠 경보는 곧 꺼지는 경보다.

**범위 (정직하게).** `Write|Edit|NotebookEdit`만 dirty로 만든다. Bash 편집·외부 writer·
Codex 편집·사용자 interrupt는 이 훅이 못 본다. 그래서 후방선 둘이 있다.
  pre-commit          커밋되는 index를 검사 (`tools/install_hooks.sh`)
  UserPromptSubmit    interrupt로 남은 dirty를 다음 턴에 회수 (`gate.py resume`)

사용:
    python3 tools/gate.py dirty     PostToolUse 훅에서 (표시만)
    python3 tools/gate.py check     Stop 훅에서 (검사하고 필요하면 차단)
    python3 tools/gate.py resume    UserPromptSubmit 훅에서 (남은 dirty 회수)
    python3 tools/gate.py precommit pre-commit 훅에서 (index 검사, fail closed)
    python3 tools/gate.py baseline  현재 이슈 집합을 기준선으로 저장
    python3 tools/gate.py status    지금 상태 보기
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M

BASELINE = os.path.join(M.STATE, ".gate-baseline.json")

# 검사기: (이름, argv). 각자 `--issues`로 ID 한 줄씩 + `#issues N` 트레일러를 낸다.
CHECKS = [
    ("linkcheck", [sys.executable, os.path.join(HERE, "linkcheck.py"), "--issues"]),
    ("now-check", [sys.executable, os.path.join(HERE, "now.py"), "check", "--issues"]),
]


def _dirty_path():
    """마커는 **추적 밖**에 산다. `state/`에 뒀더니 커밋돼서 리포에 들어갔다 (실측).
    `.git/`은 clone으로 안 따라오고 gitignore 규칙에도 안 걸린다."""
    gitdir = subprocess.run(["git", "-C", M.ROOT, "rev-parse", "--git-dir"],
                            capture_output=True, text=True).stdout.strip()
    if gitdir:
        if not os.path.isabs(gitdir):
            gitdir = os.path.join(M.ROOT, gitdir)
        return os.path.join(gitdir, "mottori-gate-dirty")
    return os.path.join(M.STATE, ".gate-dirty")     # git이 아닌 인스턴스의 폴백


def _issues(cmd, cwd=None):
    """검사기 하나를 돌려 이슈 ID 집합. 트레일러가 없으면 None (= 측정 실패)."""
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or M.ROOT, env=env, timeout=120)
    except Exception:
        return None
    lines = r.stdout.splitlines()        # 계약은 stdout이다. stderr는 진단용으로만 본다
    trailer = [l for l in lines if l.startswith("#issues ")]
    if not trailer:
        return None                      # 죽었거나 계약을 안 지켰다
    ids = {l for l in lines
           if l and not l.startswith(("#issues ", "~"))}   # `~` = 시간이 만든 것
    try:
        declared = int(trailer[-1].split()[1])
    except (IndexError, ValueError):
        return None
    if declared != len(ids):
        return None                      # 선언과 실제가 어긋나면 못 믿는다
    return ids


def measure(tree=None, filelist=None):
    """모든 검사기의 이슈 집합. 값이 None인 항목은 측정 실패."""
    out = {}
    for name, cmd in CHECKS:
        c = list(cmd)
        if tree and name == "linkcheck":
            c += ["--tree", tree] + (["--filelist", filelist] if filelist else [])
        out[name] = _issues(c)
    return out


def _load_baseline():
    """(집합 dict, 상태). 상태: ok · absent · corrupt.
    **없는 것과 깨진 것은 다르다.** 없으면 첫 실행이라 채택하고, 깨졌으면 막는다."""
    if not os.path.exists(BASELINE):
        return {}, "absent"
    try:
        raw = json.load(open(BASELINE, encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}, "corrupt"
        return {k: set(v) for k, v in raw.items()}, "ok"
    except Exception:
        return {}, "corrupt"


def _save_baseline(cur):
    os.makedirs(M.STATE, exist_ok=True)
    json.dump({k: sorted(v) for k, v in cur.items()},
              open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def _verdict(cur, base, state):
    """(막을 이유 or None, 기준선을 갱신할지)."""
    dead = sorted(k for k, v in cur.items() if v is None)
    if dead:
        return f"검사기가 결과를 못 냈다: {', '.join(dead)}. 측정 불능은 통과가 아니다 — 죽었는지 확인해라.", False
    if state == "corrupt":
        return f"게이트 기준선이 깨졌다 ({BASELINE}). 확인하고 `gate.py baseline`으로 다시 세워라.", False
    if state == "absent":
        return None, True                # 첫 실행. 채택하되 조용히는 아니다 (호출부가 알린다)

    new = {k: sorted(cur[k] - base.get(k, set())) for k in cur}
    new = {k: v for k, v in new.items() if v}
    if new:
        detail = " · ".join(f"{k}: " + "; ".join(v[:4]) + (f" 외 {len(v)-4}건" if len(v) > 4 else "")
                            for k, v in new.items())
        return ("이번 턴에 없던 이슈가 생겼다 — " + detail +
                ". 고치고 끝내라. 의도한 변화면 `python3 tools/gate.py baseline`으로 기준선을 옮긴다."), False

    # 새 이슈가 없다. 줄었을 때만 기준선을 당긴다 (모든 성분이 부분집합 + 하나라도 진부분집합).
    shrank = (all(cur[k] <= base.get(k, set()) for k in cur)
              and any(cur[k] < base.get(k, set()) for k in cur))
    return None, shrank


def cmd_dirty():
    p = _dirty_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("1")
    return 0


def cmd_baseline():
    cur = measure()
    dead = [k for k, v in cur.items() if v is None]
    if dead:
        print(f"기준선을 못 세운다 — 검사기 실패: {', '.join(dead)}")
        return 1
    _save_baseline(cur)
    print("기준선 저장: " + " · ".join(f"{k} {len(v)}건" for k, v in cur.items()))
    return 0


def cmd_status():
    base, state = _load_baseline()
    cur = measure()
    print(f"dirty     : {os.path.exists(_dirty_path())}  ({_dirty_path()})")
    print(f"기준선    : {state} — " + " · ".join(f"{k} {len(v)}건" for k, v in base.items()))
    print("현재      : " + " · ".join(
        f"{k} {'측정실패' if v is None else str(len(v)) + '건'}" for k, v in cur.items()))
    for k, v in cur.items():
        for i in sorted(v or [])[:10]:
            print(f"  {k}  {i}")
    return 0


def _run_gate(consume_dirty=True, label="Stop"):
    """검사하고 판정. 훅에서 부르므로 어떤 예외도 세션을 죽이면 안 된다."""
    p = _dirty_path()
    base, state = _load_baseline()
    cur = measure()
    if consume_dirty:
        try:
            os.remove(p)
        except OSError:
            pass
    reason, advance = _verdict(cur, base, state)
    if advance:
        _save_baseline({k: v for k, v in cur.items() if v is not None})
    if reason:
        M.log_run("gate", f"blocked@{label}")
        return _block(reason)
    if state == "absent":
        # 기준선 부재는 사면이다. **조용한 사면은 만들지 않는다** — 눈에 보이게 한다.
        M.log_run("gate", "baseline-bootstrap", ok=True)
        print(json.dumps({"decision": "block", "reason":
              "게이트 기준선이 없어서 지금 상태를 기준선으로 채택했다 ("
              + " · ".join(f"{k} {len(v)}건" for k, v in cur.items())
              + "). 의도한 상태가 맞는지 한 번 보고 계속해라."}, ensure_ascii=False))
        return 0
    M.log_run("gate", "pass", ok=True)
    return 0


def cmd_check():
    """Stop 훅. dirty일 때만 검사한다."""
    try:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception:
            payload = {}
        # 루프 방지. 이미 Stop 훅 때문에 이어진 턴이면 다시 막지 않는다.
        if payload.get("stop_hook_active"):
            return 0
        if not os.path.exists(_dirty_path()):
            return 0
        return _run_gate(consume_dirty=True, label="Stop")
    except Exception:
        return 0


def cmd_resume():
    """UserPromptSubmit 훅. interrupt로 Stop이 안 돈 턴의 dirty를 다음 턴에 회수한다.

    공식 훅 계약상 Stop은 사용자 interrupt에 실행되지 않는다. 그 공백이 이 명령의 존재 이유다.
    막는 게 아니라 알린다 — 사용자가 방금 새 지시를 넣은 순간에 차단하면 성가시기만 하다."""
    try:
        if not os.path.exists(_dirty_path()):
            return 0
        base, state = _load_baseline()
        cur = measure()
        try:
            os.remove(_dirty_path())
        except OSError:
            pass
        reason, advance = _verdict(cur, base, state)
        if advance:
            _save_baseline({k: v for k, v in cur.items() if v is not None})
        if reason:
            M.log_run("gate", "resume-warn")
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "[게이트] 지난 턴이 검사 없이 끝났다 (interrupt 추정). "
                                     + reason}}, ensure_ascii=False))
        return 0
    except Exception:
        return 0


def cmd_precommit():
    """pre-commit 훅. **커밋되는 index**를 검사하고, 측정 불능이면 막는다 (fail closed).

    Stop 게이트가 못 보는 것 — Bash 편집, 외부 writer, Codex 편집, interrupt — 이 여기서
    걸린다. `--no-verify`는 여전히 우회이므로 절대 계약은 아니다.
    """
    tmp = tempfile.mkdtemp(prefix="mottori-gate-")
    try:
        r = subprocess.run(["git", "-C", M.ROOT, "checkout-index", "-a", "--prefix", tmp + "/"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[gate] index를 꺼내지 못했다: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        fl = os.path.join(tmp, ".gate-filelist")
        ls = subprocess.run(["git", "-C", M.ROOT, "ls-files", "--cached", "*.md"],
                            capture_output=True, text=True).stdout
        open(fl, "w", encoding="utf-8").write(ls)

        base, state = _load_baseline()
        cur = measure(tree=tmp, filelist=fl)
        dead = sorted(k for k, v in cur.items() if v is None)
        if dead:
            print(f"[gate] 검사기가 결과를 못 냈다: {', '.join(dead)}. 커밋을 막는다.", file=sys.stderr)
            return 1
        if state == "corrupt":
            print(f"[gate] 기준선이 깨졌다 ({BASELINE}). 커밋을 막는다.", file=sys.stderr)
            return 1
        new = {k: sorted(cur[k] - base.get(k, set())) for k in cur}
        new = {k: v for k, v in new.items() if v}
        if new and state == "ok":
            print("[gate] 커밋될 index에 새 이슈가 있다:", file=sys.stderr)
            for k, v in new.items():
                for i in v[:8]:
                    print(f"  {k}  {i}", file=sys.stderr)
            print("  고치고 다시 커밋해라. 의도한 변화면 `python3 tools/gate.py baseline`.",
                  file=sys.stderr)
            return 1
        M.log_run("gate", "precommit-pass", ok=True)
        return 0
    except Exception as e:
        print(f"[gate] 게이트 자신이 실패했다: {e}. 커밋을 막는다.", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    return {"dirty": cmd_dirty, "check": cmd_check, "resume": cmd_resume,
            "precommit": cmd_precommit, "baseline": cmd_baseline,
            "status": cmd_status}.get(cmd, cmd_status)()


if __name__ == "__main__":
    sys.exit(main())
