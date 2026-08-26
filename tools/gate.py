#!/usr/bin/env python3
"""gate — 편집이 있었던 턴이 끝날 때 자동으로 도는 검증 게이트.

**왜 있나.** 2026-08-24 하루에 같은 실패를 세 번 했다. `rituals.md`에 "재편 후 linkcheck 필수"가
명시돼 있는데 새 산출물(킷)을 만들고 안 돌려서 깨진 참조 27개가 "검증 완료"로 나갔다.
조건부 문서는 **내가 읽어야겠다고 판단해야만** 열리고, 그 판단이 실패하는 것이 문제였다.

스킬로는 안 된다. 설명이 맞으면 뜨지만 **반드시 뜨지는 않는다** — `P(발동|해당사건) > 0`과
`P = 1`은 다르다. 검증은 계약이어야 하므로 결정적 훅이다.

**검사기 계약 (v2).** 각 검사기는 `--issues`로
    <안정ID>\\t<표시문구>      ← 시간이 만든 것은 ID 앞에 `~`
    #issues <N>               ← 반드시 마지막 줄
을 내고 **이슈 유무와 무관하게 exit 0**으로 끝난다. 종료코드는 "측정이 됐는가"만 뜻한다.

게이트가 측정 실패로 보는 것 (전부 차단):
  - nonzero exit
  - 트레일러가 없거나 마지막 줄이 아님
  - 선언 수와 실제 gated ID 수 불일치
  - 기준선과 **검사기 목록이 다름** (검사기를 지워서 우회하는 것을 막는다)

**개수가 아니라 집합이다.** 개수는 치환에 눈이 멀었다 — 링크 하나 고치고 하나 깨면 같은 수라
통과했다. `현재 - 기준선`이 비지 않으면 막고, 현재가 기준선의 진부분집합일 때만 당긴다.

**기준선은 사람만 만든다.** 삭제와 첫 설치를 기계가 구분할 수 없다. 세 운영 명령(check·resume·
precommit)은 기준선이 없으면 각자의 방식으로 거부하고, 쓰기는 `gate.py baseline` 하나에만 있다.
(줄어들 때 당기는 것은 조이는 방향이라 허용한다.)

**범위 (정직하게).** Stop 훅은 `Write|Edit|NotebookEdit`만 본다. Bash 편집·외부 writer·
Codex 편집·interrupt는 못 본다. 그래서 후방선 둘이 있다.
  gate.py precommit   커밋될 index를 검사 (`tools/install_hooks.sh`로 설치)
  gate.py resume      UserPromptSubmit에서 남은 dirty와 미해결 실패를 회수
`git commit --no-verify`는 전부 우회한다. 계약이 아니라 후방선이다.

사용:
    python3 tools/gate.py dirty     PostToolUse 훅에서 (표시만)
    python3 tools/gate.py check     Stop 훅에서
    python3 tools/gate.py resume    UserPromptSubmit 훅에서
    python3 tools/gate.py precommit pre-commit 훅에서 (fail closed)
    python3 tools/gate.py baseline  현재 이슈 집합을 기준선으로 (사람만)
    python3 tools/gate.py status    지금 상태 보기
"""
import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M

# **실행 root를 자기 파일에서 유도한다** (codex 라운드 4). `MOTTORI_INSTANCE`로 깨끗한 다른
# 클론을 가리키면 깨진 index가 통과했다. 훅은 이 변수를 지우고, 게이트는 불일치면 거부한다.
SELF_ROOT = os.path.dirname(HERE)

BASELINE = os.path.join(M.STATE, ".gate-baseline.json")

CHECKS = [
    ("linkcheck", [sys.executable, os.path.join(HERE, "linkcheck.py"), "--issues"]),
    ("now-check", [sys.executable, os.path.join(HERE, "now.py"), "check", "--issues"]),
]


def _root_ok():
    return os.path.realpath(M.ROOT) == os.path.realpath(SELF_ROOT)


def _gitdir():
    d = subprocess.run(["git", "-C", M.ROOT, "rev-parse", "--git-dir"],
                       capture_output=True, text=True).stdout.strip()
    if not d:
        return None
    return d if os.path.isabs(d) else os.path.join(M.ROOT, d)


def _ephem(name):
    """마커는 **추적 밖**에 산다. `state/`에 뒀더니 커밋돼서 리포에 들어갔다 (실측)."""
    g = _gitdir()
    return os.path.join(g, name) if g else os.path.join(M.STATE, "." + name)


DIRTY = lambda: _ephem("mottori-gate-dirty")
PENDING = lambda: _ephem("mottori-gate-pending")     # 막힌 뒤 아직 재검증 안 된 상태
LOCK = lambda: _ephem("mottori-gate-lock")


@contextlib.contextmanager
def _lock(timeout=150):
    """dirty 표시·검사·기준선 갱신을 직렬화한다.

    없으면 lost wakeup이 난다 (codex 라운드 4 재현): A가 검사 중일 때 B가 편집하고 dirty를
    다시 찍으면, A가 옛 결과로 통과한 뒤 B의 마커까지 지웠다."""
    p = LOCK()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    f = open(p, "w")
    end = time.time() + timeout
    got = False
    while time.time() < end:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
            break
        except OSError:
            time.sleep(0.05)
    try:
        yield got
    finally:
        if got:
            with contextlib.suppress(OSError):
                fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _issues(cmd, cwd=None, instance=None):
    """검사기 하나 → 게이트가 무는 ID 집합. 측정 실패면 None."""
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    if instance is None:
        env.pop("MOTTORI_INSTANCE", None)
    else:
        env["MOTTORI_INSTANCE"] = instance
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or M.ROOT, env=env, timeout=120)
    except Exception:
        return None
    if r.returncode != 0:
        return None                      # issues 모드는 이슈가 있어도 0으로 끝나야 한다
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines or not lines[-1].startswith("#issues "):
        return None                      # 트레일러는 반드시 마지막 줄
    try:
        declared = int(lines[-1].split()[1])
    except (IndexError, ValueError):
        return None
    ids = {l.split("\t", 1)[0] for l in lines[:-1]}
    gated = {i for i in ids if not i.startswith("~")}
    if declared != len(gated):
        return None
    return gated


def measure(tree=None, filelist=None):
    out = {}
    for name, cmd in CHECKS:
        c = list(cmd)
        if tree and name == "linkcheck":
            c += ["--tree", tree] + (["--filelist", filelist] if filelist else [])
        if tree and name == "now-check":
            # pre-commit은 worktree가 아니라 index에서 꺼낸 엔진과 상태를 검사해야 한다.
            # 인스턴스 저장소(visa)는 config/state가 tracked라 extracted tree가 정본이고,
            # 배포 킷은 둘 다 의도적으로 ignored라 staged 엔진을 현재 local instance에 대입한다.
            staged_now = os.path.join(tree, "tools", "now.py")
            staged_config = os.path.join(tree, "system", "memory-config.json")
            instance = tree if os.path.isfile(staged_config) else M.ROOT
            c = [sys.executable, staged_now, "check", "--issues", "--portable"]
            out[name] = _issues(c, cwd=instance, instance=instance)
        else:
            out[name] = _issues(c)
    return out


def _load_baseline():
    """(집합 dict, 상태). 상태: ok · absent · corrupt."""
    if not os.path.exists(BASELINE):
        return {}, "absent"
    try:
        raw = json.load(open(BASELINE, encoding="utf-8"))
        if not isinstance(raw, dict) or not raw:
            return {}, "corrupt"
        return {k: set(v) for k, v in raw.items()}, "ok"
    except Exception:
        return {}, "corrupt"


def _save_baseline(cur):
    os.makedirs(M.STATE, exist_ok=True)
    tmp = BASELINE + ".tmp"
    json.dump({k: sorted(v) for k, v in cur.items()},
              open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.replace(tmp, BASELINE)


def _verdict(cur, base, state):
    """(막을 이유 or None, 기준선을 당길지). **채택은 절대 안 한다.**"""
    dead = sorted(k for k, v in cur.items() if v is None)
    if dead:
        return (f"검사기가 결과를 못 냈다: {', '.join(dead)}. "
                "측정 불능은 통과가 아니다 — 죽었는지 확인해라."), False
    if state == "corrupt":
        return f"게이트 기준선이 깨졌다 ({BASELINE}). 확인하고 `python3 tools/gate.py baseline`.", False
    if state == "absent":
        return ("게이트 기준선이 없다. 지운 것과 처음 설치한 것을 기계가 구분할 수 없어서 "
                "자동으로 채택하지 않는다. `python3 tools/gate.py baseline`을 직접 돌려라."), False
    if set(cur) != set(base):
        only_c, only_b = sorted(set(cur) - set(base)), sorted(set(base) - set(cur))
        return ("검사기 목록이 기준선과 다르다 — "
                + (f"기준선에만: {', '.join(only_b)} " if only_b else "")
                + (f"현재에만: {', '.join(only_c)}" if only_c else "")
                + ". 검사기를 지워서 통과시키는 경로다. `gate.py baseline`으로 명시 이관해라."), False

    new = {k: sorted(cur[k] - base[k]) for k in cur}
    new = {k: v for k, v in new.items() if v}
    if new:
        detail = " · ".join(f"{k}: " + "; ".join(v[:4]) + (f" 외 {len(v)-4}건" if len(v) > 4 else "")
                            for k, v in new.items())
        return ("이번 턴에 없던 이슈가 생겼다 — " + detail
                + ". 고치고 끝내라. 의도한 변화면 `python3 tools/gate.py baseline`."), False

    shrank = (all(cur[k] <= base[k] for k in cur) and any(cur[k] < base[k] for k in cur))
    return None, shrank


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def _mark(p, val="1"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(val)


def cmd_dirty():
    with _lock(timeout=150) as got:
        # 잠금을 못 얻어도 표시는 남긴다. 안 남기는 쪽이 더 나쁜 실패다.
        _mark(DIRTY(), str(time.time_ns()))
    return 0


def cmd_baseline():
    if not _root_ok():
        print(f"실행 root 불일치: M.ROOT={M.ROOT} vs 도구 위치={SELF_ROOT}", file=sys.stderr)
        return 1
    cur = measure()
    dead = [k for k, v in cur.items() if v is None]
    if dead:
        print(f"기준선을 못 세운다 — 검사기 실패: {', '.join(dead)}")
        return 1
    with _lock():
        _save_baseline(cur)
    for p in (PENDING(),):
        with contextlib.suppress(OSError):
            os.remove(p)
    print("기준선 저장: " + " · ".join(f"{k} {len(v)}건" for k, v in cur.items()))
    return 0


def cmd_status():
    base, state = _load_baseline()
    cur = measure()
    print(f"root      : {M.ROOT}" + ("" if _root_ok() else f"  (!! 도구 위치 {SELF_ROOT}와 불일치)"))
    print(f"dirty     : {os.path.exists(DIRTY())}  ({DIRTY()})")
    print(f"pending   : {os.path.exists(PENDING())}")
    print(f"기준선    : {state} — " + " · ".join(f"{k} {len(v)}건" for k, v in base.items()))
    print("현재      : " + " · ".join(
        f"{k} {'측정실패' if v is None else str(len(v)) + '건'}" for k, v in cur.items()))
    for k, v in cur.items():
        for i in sorted(v or [])[:10]:
            print(f"  {k}  {i}")
    return 0


def cmd_check():
    """Stop 훅. dirty이거나 미해결 실패(pending)가 있으면 검사한다."""
    try:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception:
            payload = {}
        if payload.get("stop_hook_active"):
            return 0
        if not _root_ok():
            return _block(f"게이트 실행 root가 도구 위치와 다르다 ({M.ROOT} vs {SELF_ROOT}). "
                          "MOTTORI_INSTANCE가 걸려 있는지 확인해라.")
        if not (os.path.exists(DIRTY()) or os.path.exists(PENDING())):
            return 0

        with _lock() as got:
            if not got:
                return _block("게이트 잠금을 못 얻었다. 다른 검사가 도는 중이거나 잠금이 남았다.")
            token = _read(DIRTY())
            base, state = _load_baseline()
            cur = measure()
            # 검사 도중 새 편집이 들어왔으면 마커를 지우지 않는다 (lost wakeup 차단).
            moved = _read(DIRTY()) != token
            reason, advance = _verdict(cur, base, state)
            if advance and not moved:
                _save_baseline(cur)
            if reason:
                # **막은 뒤에도 재검증이 남아야 한다.** 마커만 지우면 다음 Stop이 조용히 통과했다.
                _mark(PENDING())
                if not moved:
                    with contextlib.suppress(OSError):
                        os.remove(DIRTY())
                M.log_run("gate", "blocked@Stop")
                return _block(reason)
            if not moved:
                for p in (DIRTY(), PENDING()):
                    with contextlib.suppress(OSError):
                        os.remove(p)
            M.log_run("gate", "pass@Stop", ok=True)
            return 0
    except Exception:
        return 0


def _read(p):
    try:
        return open(p).read()
    except OSError:
        return None


def cmd_resume():
    """UserPromptSubmit 훅. interrupt로 Stop이 안 돈 턴과, 막혔는데 안 고쳐진 상태를 회수한다.

    막지 않고 알린다 — 사용자가 방금 새 지시를 넣은 순간에 차단하면 성가시기만 하다."""
    try:
        if not _root_ok():
            return 0
        if not (os.path.exists(DIRTY()) or os.path.exists(PENDING())):
            return 0
        with _lock(timeout=30) as got:
            if not got:
                return 0
            token = _read(DIRTY())
            base, state = _load_baseline()
            cur = measure()
            moved = _read(DIRTY()) != token
            reason, advance = _verdict(cur, base, state)
            if advance and not moved:
                _save_baseline(cur)
            if reason:
                _mark(PENDING())
                if not moved:
                    with contextlib.suppress(OSError):
                        os.remove(DIRTY())
                M.log_run("gate", "resume-warn")
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": "[게이트] 지난 턴이 검증을 통과하지 못했다. " + reason}},
                    ensure_ascii=False))
                return 0
            if not moved:
                for p in (DIRTY(), PENDING()):
                    with contextlib.suppress(OSError):
                        os.remove(p)
            return 0
    except Exception:
        return 0


def _staged_tools_compile(tmp):
    """index에 올라간 파이썬 도구가 문법적으로 성립하는가.

    안 보면 이 구멍이 난다 (codex 라운드 4): 검사기를 깨진 채로 stage하고 worktree만
    되돌리면, 훅은 worktree 검사기로 index 문서를 검사해서 통과시킨다."""
    import py_compile
    bad = []
    ls = subprocess.run(["git", "-C", M.ROOT, "ls-files", "--cached", "tools/*.py"],
                        capture_output=True, text=True).stdout.split()
    for rel in ls:
        p = os.path.join(tmp, rel)
        if not os.path.exists(p):
            continue
        try:
            py_compile.compile(p, cfile=os.path.join(tmp, ".pyc-scratch"), doraise=True)
        except Exception as e:
            bad.append(f"{rel}: {type(e).__name__}")
    return bad


def cmd_precommit():
    """pre-commit 훅. 커밋되는 index를 검사하고, 조금이라도 못 미더우면 막는다 (fail closed)."""
    if not _root_ok():
        print(f"[gate] 실행 root 불일치 ({M.ROOT} vs {SELF_ROOT}). 커밋을 막는다.", file=sys.stderr)
        return 1
    tmp = tempfile.mkdtemp(prefix="mottori-gate-")
    try:
        r = subprocess.run(["git", "-C", M.ROOT, "checkout-index", "-a", "--prefix", tmp + "/"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[gate] index를 꺼내지 못했다: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        bad = _staged_tools_compile(tmp)
        if bad:
            print("[gate] index의 파이썬 도구가 깨져 있다: " + ", ".join(bad), file=sys.stderr)
            print("  검사기가 깨진 채 커밋되면 이 게이트 자체가 무력해진다.", file=sys.stderr)
            return 1
        fl = os.path.join(tmp, ".gate-filelist")
        ls = subprocess.run(["git", "-C", M.ROOT, "ls-files", "--cached", "*.md"],
                            capture_output=True, text=True).stdout
        open(fl, "w", encoding="utf-8").write(ls)

        base, state = _load_baseline()
        cur = measure(tree=tmp, filelist=fl)
        reason, _ = _verdict(cur, base, state)
        if reason:
            print("[gate] " + reason, file=sys.stderr)
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
