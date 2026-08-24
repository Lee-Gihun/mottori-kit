#!/usr/bin/env python3
"""doctor — 설치 검증기. 이 인스턴스에서 기계장치가 실제로 살아 있는가를 잰다.

왜 있나. 훅은 fail-safe라 실패해도 조용히 exit 0 한다 (PRD §10.1 — 훅이 세션을 막으면
안 되므로 이 설계 자체는 옳다). 대가로 **설치된 것처럼 보이는데 죽어 있는 상태**가 가능하다.
2026-08-24 이식 작업에서 실측: 경로 하드코딩 8곳 중 훅 2곳이 정확히 이 모드로 죽는다.
doctor는 그 침묵을 깨는 쪽 계기다.

원칙 하나. **검사 못 하는 것을 숨기지 않는다.** 자동 검사 가능한 것만 보고하면
"전부 PASS"가 거짓말이 된다. MANUAL 칸이 이 도구의 반증 가능 칸이다 (WORKING-WITH-AI §4).

사용: python3 tools/doctor.py [--verbose]
종료코드: FAIL이 하나라도 있으면 1.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
VERBOSE = "--verbose" in sys.argv

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
results = []


def check(name, fn):
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = FAIL, f"검사 자체가 터짐: {type(e).__name__}: {e}"
    results.append((status, name, detail))


def sh(*cmd, cwd=ROOT):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


# ----------------------------------------------------------------- 런타임

def c_python():
    v = sys.version_info
    ok = v >= (3, 8)
    return (PASS if ok else FAIL), f"python {v.major}.{v.minor}.{v.micro}" + ("" if ok else " (3.8+ 필요)")


def c_node():
    p = shutil.which("node")
    return (PASS, os.path.realpath(p)) if p else (WARN, "node 없음 — 정원사(wf_gardener.js)만 못 쓴다")


def c_codex():
    p = shutil.which("codex")
    return (PASS, p) if p else (WARN, "codex CLI 없음 — 티키타카(ask_codex.sh) 불가. 권한/설치 확인")


def c_claude():
    p = shutil.which("claude")
    return (PASS, p) if p else (WARN, "claude CLI 없음 — 헤드리스 검증(claude -p) 불가")


def c_git():
    r = sh("git", "rev-parse", "--show-toplevel")
    if r.returncode:
        return WARN, "git 저장소가 아니다 — linkcheck가 추적 파일을 못 센다"
    return PASS, r.stdout.strip()


# ------------------------------------------------------------------ 배선

def c_memlib():
    import memlib as M
    if M.ROOT != ROOT:
        return FAIL, f"ROOT 불일치: memlib={M.ROOT} vs 실제={ROOT}"
    return PASS, f"ROOT={M.ROOT}"


def c_config():
    import memlib as M
    if not os.path.exists(M.CONFIG_PATH):
        return FAIL, f"없음: {M.CONFIG_PATH} — `bash setup.sh` 또는 templates/에서 복사"
    raw = open(M.CONFIG_PATH, encoding="utf-8").read()
    if "CHANGEME" in raw:
        return FAIL, "CHANGEME가 남아 있다 — 인스턴스 이름·트랙을 아직 안 채웠다"
    if M.CONFIG_WARNINGS:
        return WARN, " · ".join(M.CONFIG_WARNINGS)
    return PASS, f"트랙 {len(M.TRACKS)}개 · 스레드 {len(M.THREADS)}개 · 소스 {len(M.EPISODIC_SOURCES)}개"


def c_transcripts():
    """전사 경로 유도 (DR-025). 여기가 조용히 틀리면 recall이 0건을 반환하고도 정상 종료한다.

    부재의 의미가 인스턴스 나이에 따라 다르다. 갓 클론한 곳은 세션을 안 돌렸으니 없는 게
    정상이고, 오래 쓴 곳에 없으면 유도가 틀린 것이다. 첫 설치마다 FAIL을 띄우면
    사람이 FAIL을 무시하게 된다 — 계측기가 자기 신호를 죽이는 실패다.
    """
    import memlib as M
    if not os.path.isdir(M.TRANSCRIPTS):
        fresh = len(M.parse_journal()) < 5
        msg = (f"없음: {M.TRANSCRIPTS}\n      ")
        if fresh:
            return WARN, msg + "이 디렉토리에서 Claude Code 세션을 아직 안 돌렸다 (신규 설치면 정상). 첫 세션 뒤 다시 확인해라"
        return FAIL, msg + "journal은 쌓였는데 전사가 없다 — 경로 맹글링 규칙이 이 경로에 안 맞는다"
    n = len([f for f in os.listdir(M.TRANSCRIPTS) if f.endswith(".jsonl")])
    return (PASS if n else WARN), f"{M.TRANSCRIPTS} · 세션 {n}개"


def c_state():
    import memlib as M
    if not os.path.isdir(M.STATE):
        return FAIL, f"없음: {M.STATE}"
    if not os.access(M.STATE, os.W_OK):
        return FAIL, f"쓰기 불가: {M.STATE}"
    j = M.journal_path()
    entries = M.parse_journal()
    return PASS, f"journal {'있음' if os.path.exists(j) else '없음(첫 log에 생성)'} · 엔트리 {len(entries)}줄"


def c_now():
    import memlib as M
    if not os.path.exists(M.NOW_PATH):
        return WARN, "NOW.md 없음 — `python3 tools/now.py render`로 생성"
    return PASS, f"{os.path.getsize(M.NOW_PATH)} bytes"


# ------------------------------------------------------------------- 훅

def _hook_cmds():
    p = os.path.join(ROOT, ".claude", "settings.json")
    if not os.path.exists(p):
        return None
    cfg = json.load(open(p, encoding="utf-8"))
    out = {}
    for event, blocks in cfg.get("hooks", {}).items():
        for b in blocks:
            for h in b.get("hooks", []):
                out.setdefault(event, []).append(h.get("command", ""))
    return out


def c_hook_wiring():
    """훅 명령줄에 절대경로가 박혀 있으면 이식 즉시 죽는다 — 그게 이번 작업의 발단이다."""
    cmds = _hook_cmds()
    if cmds is None:
        return FAIL, ".claude/settings.json 없음 — 훅 미설치"
    need = ("SessionStart", "PreCompact")
    missing = [e for e in need if e not in cmds]
    if missing:
        return FAIL, f"훅 누락: {', '.join(missing)}"
    hard = [f"{e}: {c}" for e, cs in cmds.items() for c in cs
            if re.search(r"/(Users|home)/[^/]+/", c)]
    if hard:
        return FAIL, "절대경로 하드코딩 — 다른 머신에서 조용히 죽는다:\n      " + "\n      ".join(hard)
    return PASS, f"{len(cmds)}종 · 전부 $CLAUDE_PROJECT_DIR 상대"


def c_hook_success():
    """SessionStart 훅의 성공 분기가 실제로 유효 JSON을 내는가 (훅 커맨드 그대로 실행)."""
    cmds = _hook_cmds() or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return FAIL, "SessionStart 훅 없음"
    env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)
    r = subprocess.run(["bash", "-c", cs[0]], capture_output=True, text=True, env=env, cwd=ROOT)
    try:
        d = json.loads(r.stdout)
        ctx = d["hookSpecificOutput"]["additionalContext"]
    except Exception as e:
        return FAIL, f"유효 JSON이 아니다: {e} · stdout[:120]={r.stdout[:120]!r}"
    if ctx.startswith("[kit]"):
        return FAIL, "실패 분기로 떨어졌다 — now.py가 안 돈다"
    return PASS, f"{len(ctx)} chars 주입 예정"


def c_hook_failure():
    """실패 분기도 유효 JSON이어야 한다. 아니면 훅이 죽을 때 두 번 죽는다."""
    cmds = _hook_cmds() or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return SKIP, ""
    env = dict(os.environ, CLAUDE_PROJECT_DIR="/nonexistent-instance-xyz")
    r = subprocess.run(["bash", "-c", cs[0]], capture_output=True, text=True, env=env, cwd="/")
    if r.returncode != 0:
        return FAIL, f"실패 분기가 exit {r.returncode} — 훅은 항상 0이어야 세션을 안 막는다"
    try:
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except Exception as e:
        return FAIL, f"실패 분기가 유효 JSON이 아니다: {e}"
    return (PASS if "[kit]" in ctx else WARN), "실패 시 모델에게 경고가 주입된다"


def c_global_hook():
    """UserPromptSubmit 타임스탬프 훅은 전역 설정에 산다 — 클론으로 안 따라온다."""
    p = os.path.expanduser("~/.claude/settings.json")
    if not os.path.exists(p):
        return WARN, "전역 설정 없음 — 턴마다 현재 시각 주입이 꺼져 있다"
    try:
        cfg = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return WARN, f"전역 설정 파싱 실패: {e}"
    ups = cfg.get("hooks", {}).get("UserPromptSubmit", [])
    has = any("date" in h.get("command", "") for b in ups for h in b.get("hooks", []))
    return (PASS, "시각 주입 훅 있음") if has else \
           (WARN, "시각 주입 훅 없음 — 모델이 '오늘'을 모른다. SETUP.md의 전역 설정 절 참조")


def c_commands():
    d = os.path.join(ROOT, ".claude", "commands")
    if not os.path.isdir(d):
        return WARN, "슬래시 커맨드 없음"
    got = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
    return PASS, "/" + " /".join(got)


# ---------------------------------------------------------------- 도구 동작

def c_tools_run():
    """도구가 import·실행되는가. render는 생성물을 덮으므로 check만 돌린다."""
    bad = []
    for args in (["tools/now.py", "check"], ["tools/linkcheck.py"], ["tools/coherence.py", "--quiet"]):
        r = sh(sys.executable, *args)
        if r.returncode not in (0, 1):   # coherence·linkcheck는 문제 발견 시 1을 낸다
            bad.append(f"{args[0]} exit={r.returncode} {r.stderr.strip()[:80]}")
    return (FAIL, " · ".join(bad)) if bad else (PASS, "now/linkcheck/coherence 실행 OK")


def c_recall():
    r = sh(sys.executable, "tools/recall.py", "sessions")
    if r.returncode:
        return FAIL, r.stderr.strip()[:150]
    n = len(re.findall(r"\.jsonl", r.stdout)) or len(r.stdout.strip().splitlines())
    return (PASS if n else WARN), f"소스 조회 OK ({n}줄)"


def c_ledger():
    import memlib as M
    d = os.path.join(M.ROOT, "_private", "ledger", "facts")
    if not os.path.isdir(d):
        return SKIP, "원장 미개설 (rec.py는 첫 기록 때 만든다)"
    n = len([f for f in os.listdir(d) if f.endswith(".md")])
    r = sh(sys.executable, "tools/rec.py", "check")
    m = re.search(r"문제: (\d+)건", r.stdout)
    bad = int(m.group(1)) if m else 0
    return (PASS if not bad else WARN), f"사실 {n}건 · 정합성 문제 {bad}건"


# --------------------------------------------------------- 단방향 밸브 (DR-026)

def c_valve():
    import memlib as M
    r = sh("git", "remote", "-v")
    remotes = sorted({l.split()[1] for l in r.stdout.splitlines() if len(l.split()) > 1})
    if M.INSTANCE_CONTEXT != "work":
        return SKIP, f"context={M.INSTANCE_CONTEXT} (밸브는 work 인스턴스에만 적용)"
    if not remotes:
        return PASS, "원격 없음 — 회사 자료가 나갈 경로가 아예 없다"
    allow = M.REMOTE_ALLOWLIST
    bad = [u for u in remotes if not any(a in u for a in allow)]
    if bad:
        return FAIL, ("work 인스턴스가 allowlist 밖 원격을 가졌다:\n      "
                      + "\n      ".join(bad)
                      + "\n      회사 자료가 개인 저장소로 나갈 수 있다. 원격을 지우거나 allowlist에 넣어라")
    return PASS, f"원격 {len(remotes)}개 전부 allowlist 안"


def c_engine_drift():
    """킷과 인스턴스의 엔진이 갈라졌는가. 예방이 아니라 **탐지**다 (DR-027).

    사본 둘을 두는 대가는 드리프트인데, 자동 동기화를 만들면 "이 수정이 반출해도 되는
    것인가"를 기계가 판정해야 한다. 그건 문자열 검사로 증명할 수 없다. 그래서 탐지만 한다.
    """
    kit = os.environ.get("MOTTORI_KIT") or os.path.expanduser("~/mottori-kit")
    if not os.path.isdir(os.path.join(kit, "tools")) or os.path.realpath(kit) == os.path.realpath(ROOT):
        return SKIP, "비교할 킷 사본 없음"
    try:
        import kit_sync
    except Exception as e:
        return SKIP, f"kit_sync 없음 ({e})"
    # 탈개인화 치환을 거친 뒤 비교한다. 안 그러면 **의도된 차이**가 드리프트로 잡혀
    # 매번 warn이 뜨고, 그러면 진짜 드리프트가 났을 때 아무도 안 본다.
    mine, theirs = os.path.join(ROOT, "tools"), os.path.join(kit, "tools")
    shared = sorted(set(os.listdir(mine)) & set(os.listdir(theirs)))
    diff = []
    for f in shared:
        a, b = os.path.join(mine, f), os.path.join(theirs, f)
        if not os.path.isfile(a):
            continue
        try:
            want = kit_sync.depersonalize(open(a, encoding="utf-8").read())
            if want != open(b, encoding="utf-8").read():
                diff.append(f)
        except UnicodeDecodeError:
            pass
    if diff:
        return WARN, (f"공유 {len(shared)}개 중 {len(diff)}개 갈라짐: {', '.join(diff)}"
                      "\n      `python3 tools/kit_sync.py` 로 차이를 보고 `--apply`로 내보낸다")
    return PASS, f"공유 도구 {len(shared)}개 바이트 동일 ({kit})"


def c_ignored():
    """연료가 실제로 git에서 안 보이는가. 밸브의 실측."""
    r = sh("git", "rev-parse", "--is-inside-work-tree")
    if r.returncode:
        return SKIP, "git 저장소 아님"
    leaked = []
    for probe in ("state/NOW.md", "_private/x", "system/memory-config.json"):
        c = sh("git", "check-ignore", "-q", probe)
        tracked = sh("git", "ls-files", "--error-unmatch", probe)
        if c.returncode != 0 and tracked.returncode == 0:
            leaked.append(probe)
    if leaked:
        return WARN, "추적 중 (인스턴스 정책에 따라 정상일 수 있다): " + ", ".join(leaked)
    return PASS, "연료 경로가 git 밖"


# -------------------------------------------------------------------- 실행

CHECKS = [
    ("런타임 · python",        c_python),
    ("런타임 · node",          c_node),
    ("런타임 · codex CLI",     c_codex),
    ("런타임 · claude CLI",    c_claude),
    ("런타임 · git",           c_git),
    ("배선 · memlib ROOT",     c_memlib),
    ("배선 · config",          c_config),
    ("배선 · 전사 경로 유도",   c_transcripts),
    ("배선 · state/",          c_state),
    ("배선 · NOW.md",          c_now),
    ("훅 · 배선(경로 하드코딩)", c_hook_wiring),
    ("훅 · 성공 분기",          c_hook_success),
    ("훅 · 실패 분기",          c_hook_failure),
    ("훅 · 전역 시각 주입",     c_global_hook),
    ("훅 · 슬래시 커맨드",      c_commands),
    ("도구 · 실행",            c_tools_run),
    ("도구 · recall 소스",     c_recall),
    ("도구 · 원장",            c_ledger),
    ("밸브 · 원격 검사",        c_valve),
    ("밸브 · 연료 비추적",      c_ignored),
    ("엔진 · 킷 드리프트",      c_engine_drift),
]

# 자동 검사 불가 — 이 목록이 이 도구의 반증 가능 칸이다.
# 여기 있는 것을 "확인했다"고 말하면 거짓이다. 사람이 해야 한다.
MANUAL = [
    ("SessionStart 훅이 실제로 모델 컨텍스트에 들어갔는가",
     "훅 출력은 모델에게만 가고 셸로 안 온다. doctor는 '유효 JSON을 뱉는다'까지만 안다. "
     "확인법: 새 세션을 열고 '지금 NOW에 뭐라고 적혀 있어?'라고 물어라. 파일을 안 읽고 답하면 주입된 것이다."),
    ("PreCompact 훅이 컴팩션 때 실제로 도는가",
     "컴팩션을 인위적으로 못 일으킨다. 확인법: 다음 컴팩션 후 state/journal-*.md 끝에 "
     "'[system/state] 컴팩션 발생' 줄이 붙었는지 본다."),
    ("Codex가 AGENTS.md를 읽고 규약을 따르는가",
     "확인법: 발주 1회 후 응답이 규약(한국어·em-dash 금지·판정 형식)을 지키는지 본다."),
    ("회사 정책상 이 도구들을 써도 되는가",
     "전사·녹취(tools/transcribe.py 등)는 녹음 동의와 데이터 반출 정책에 걸릴 수 있다. "
     "회사 규정을 확인하기 전에는 녹취 도구를 돌리지 마라."),
]


def main():
    print(f"doctor — {ROOT}\n")
    for name, fn in CHECKS:
        check(name, fn)
    width = max(len(n) for _, n, _ in results)
    icon = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn ", SKIP: "  --  "}
    for status, name, detail in results:
        line = f"[{icon[status]}] {name.ljust(width)}"
        if detail and (status != PASS or VERBOSE):
            line += f"  {detail}"
        elif detail and status == PASS:
            line += f"  {detail}"
        print(line)

    n = {s: sum(1 for st, _, _ in results if st == s) for s in (PASS, FAIL, WARN, SKIP)}
    print(f"\n검사 {len(results)}개 — ok {n[PASS]} · FAIL {n[FAIL]} · warn {n[WARN]} · 해당없음 {n[SKIP]}")

    print(f"\n자동 검사 불가 {len(MANUAL)}개 (사람이 확인해야 한다):")
    for i, (title, how) in enumerate(MANUAL, 1):
        print(f"  {i}. {title}")
        print(f"     {how}")

    if n[FAIL]:
        print(f"\nFAIL {n[FAIL]}개를 먼저 고쳐라. 그 전에는 이 인스턴스의 상태 자동화를 믿지 마라.")
    return 1 if n[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
