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
    # 내부 호출 표시 — 검사기가 자기 실행 기록을 남기지 않게 (memlib.log_run 참조)
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)


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

HOOK_FILES = {"claude": (".claude", "settings.json"), "codex": (".codex", "hooks.json")}


def _hook_cmds(runtime="claude"):
    p = os.path.join(ROOT, *HOOK_FILES[runtime])
    if not os.path.exists(p):
        return None
    cfg = json.load(open(p, encoding="utf-8"))
    out = {}
    for event, blocks in cfg.get("hooks", {}).items():
        for b in blocks:
            for h in b.get("hooks", []):
                out.setdefault(event, []).append(h.get("command", ""))
    return out


def _wiring(runtime):
    """훅 명령줄에 절대경로가 박혀 있으면 이식 즉시 죽는다 — 그게 이번 작업의 발단이다."""
    cmds = _hook_cmds(runtime)
    if cmds is None:
        return (WARN, f"{'/'.join(HOOK_FILES[runtime])} 없음 — 이 런타임은 훅 미설치")
    need = ("SessionStart", "PreCompact")
    missing = [e for e in need if e not in cmds]
    if missing:
        return FAIL, f"훅 누락: {', '.join(missing)}"
    hard = [f"{e}: {c}" for e, cs in cmds.items() for c in cs
            if re.search(r"/(Users|home)/[^/]+/", c)]
    if hard:
        return FAIL, "절대경로 하드코딩 — 다른 머신에서 조용히 죽는다:\n      " + "\n      ".join(hard)
    return PASS, f"{len(cmds)}종 · 경로 상대"


def c_hook_wiring():
    return _wiring("claude")


def c_hook_wiring_codex():
    return _wiring("codex")


def c_hook_codex_run():
    """Codex 훅은 CLAUDE_PROJECT_DIR을 못 받는다 — git root 폴백이 실제로 도는지 잰다.
    서브디렉토리에서도 인스턴스 루트를 잡아야 한다 (여기가 틀리면 조용히 남의 NOW를 읽는다)."""
    cmds = _hook_cmds("codex") or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return SKIP, "Codex 훅 없음"
    sub = os.path.join(ROOT, "system") if os.path.isdir(os.path.join(ROOT, "system")) else ROOT
    outs = {}
    for label, cwd in (("루트", ROOT), ("서브디렉토리", sub), ("리포 밖", "/tmp")):
        r = subprocess.run(["bash", "-c", cs[0]], capture_output=True, text=True, cwd=cwd)
        try:
            ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        except Exception:
            return FAIL, f"{label}에서 유효 JSON이 아니다: {r.stdout[:80]!r}"
        if r.returncode != 0:
            return FAIL, f"{label}에서 exit {r.returncode} — 훅은 항상 0이어야 한다"
        outs[label] = "실패분기" if ctx.startswith("[kit]") else f"{len(ctx)}자"
    if outs["루트"] == "실패분기" or outs["서브디렉토리"] == "실패분기":
        return FAIL, f"인스턴스 안에서 주입 실패: {outs}"
    if outs["리포 밖"] != "실패분기":
        return WARN, "리포 밖에서도 주입됐다 — git root 폴백이 엉뚱한 곳을 잡을 수 있다"
    return PASS, f"루트·서브디렉토리 주입 OK · 리포 밖 실패분기 OK"


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


def c_links():
    """**결과를 본다.** 실행 여부만 보던 게 2026-08-24 사고의 자리다 — 킷에서 깨진 참조
    27개가 doctor를 통과했다. 도구를 돌리는 것과 도구가 뭐라 했는지 보는 것은 다른 일이다."""
    r = sh(sys.executable, "tools/linkcheck.py")
    m = re.search(r"broken: (\d+)", r.stdout)
    if not m:
        return FAIL, f"linkcheck 출력을 못 읽었다: {(r.stdout + r.stderr)[:120]!r}"
    n = int(m.group(1))
    if not n:
        refs = re.search(r"refs=(\d+)", r.stdout)
        return PASS, f"참조 {refs.group(1) if refs else '?'}개 · 깨짐 0"
    detail = [l for l in r.stdout.splitlines() if l.startswith("BROKEN")][:5]
    more = f"\n      … 외 {n - len(detail)}개" if n > len(detail) else ""
    return FAIL, f"깨진 참조 {n}개:\n      " + "\n      ".join(detail) + more


def c_coherence():
    """정합성 감지기의 **결과**를 본다."""
    r = sh(sys.executable, "tools/coherence.py", "--quiet")
    m = re.search(r"(?:총|이슈) (\d+)건", r.stdout)
    if m is None and ("이상 없음" in r.stdout or "링크 OK" in r.stdout):
        return PASS, r.stdout.strip().splitlines()[0][:90]
    if m is None:
        return WARN, f"출력을 못 읽었다: {r.stdout.strip()[:90]!r}"
    n = int(m.group(1))
    head = r.stdout.strip().splitlines()[0]
    return (PASS if not n else WARN), head[:110]


def c_regression():
    """회귀 픽스처가 실제로 통과하는가. **doctor가 이걸 안 돌리고 있었다** (적대 검증 V1-9).

    검출기가 살아 있는지를 재는 유일한 자동 수단인데 검사 목록에 없었다.
    계측기가 자기 옆의 계측기를 안 보고 있었던 셈이다.
    """
    r = sh(sys.executable, "tools/test_memcheck.py")
    if r.returncode == 0:
        n = r.stdout.count("✓ 검출")
        return PASS, f"픽스처 {n}개 전부 검출"
    fails = [l.strip() for l in r.stdout.splitlines() if "미검출" in l or "실패" in l]
    return FAIL, ("과거 사고 재현 픽스처가 실패한다 — 검출기가 죽었을 수 있다:\n      "
                  + "\n      ".join(fails[:4] or [(r.stdout + r.stderr)[:150]]))


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

def _remote_host(url):
    """원격 URL에서 host를 뽑는다. scp 문법(git@host:path)과 로컬 경로도 처리."""
    u = url.strip()
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?([^/:]+)", u)
    if m:
        return m.group(1).lower()
    m = re.match(r"^(?:[^@]+@)?([^/:@]+):", u)          # git@github.com:user/repo
    if m:
        return m.group(1).lower()
    return ("local:" + os.path.realpath(os.path.expanduser(u))) if u.startswith(("/", "~", ".")) else ""


def _allowed(url, allowlist):
    """**부분 문자열 비교 금지** (2026-08-24 적대 검증).

    이전 판의 `any(a in url for a in allowlist)`는
    `https://evil.invalid/https://github.com/trusted/repo`를 통과시켰다.
    허용 항목을 URL의 **경로 안에 심으면** 그대로 뚫린다.
    이제 host를 뽑아 host끼리 비교하고, 허용 항목에 경로가 있으면 경로도 경계까지 본다.
    """
    def path_of(u):
        u = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?[^/]+/?", "", u.strip())
        u = re.sub(r"^(?:[^@]+@)?[^/:@]+:", "", u)
        return re.sub(r"\.git$", "", u).strip("/").lower()

    host = _remote_host(url)
    if not host:
        return False
    for a in allowlist:
        a = (a or "").strip().rstrip("/")
        if not a:                       # 빈 항목이 전부 허용이 되면 안 된다
            continue
        ah = _remote_host(a) or a.split("/")[0].lower()
        if ah != host:
            continue
        ap = path_of(a)
        if not ap:
            return True                 # host만 지정 = 그 host 전체 허용
        up = path_of(url)
        if up == ap or up.startswith(ap + "/"):
            return True
    return False


def c_valve():
    import memlib as M
    r = sh("git", "remote", "-v")
    remotes = sorted({l.split()[1] for l in r.stdout.splitlines() if len(l.split()) > 1})
    if M.INSTANCE_CONTEXT != "work":
        # 조용한 SKIP은 "괜찮다"로 읽힌다. 무엇을 안 재는지 말하고 원격 수도 보인다.
        # (config는 이 tree 안에 있어 스스로 고칠 수 있다 — 이 검사는 차단이 아니라 진술이다.
        #  실제 차단은 .gitignore 기본거부와 pull-only 자격증명이다. DR-026)
        extra = f" · 원격 {len(remotes)}개 있음" if remotes else ""
        return SKIP, (f"context={M.INSTANCE_CONTEXT} — 원격 검사 안 함{extra}. "
                      "회사 자료를 다루면 context를 work로 바꿔라")
    if not remotes:
        return PASS, "원격 없음 — 회사 자료가 나갈 경로가 아예 없다"
    bad = [u for u in remotes if not _allowed(u, M.REMOTE_ALLOWLIST)]
    if bad:
        return FAIL, ("work 인스턴스가 allowlist 밖 원격을 가졌다:\n      "
                      + "\n      ".join(bad)
                      + "\n      원격을 지우거나 allowlist에 넣어라")
    return PASS, f"원격 {len(remotes)}개 전부 allowlist 안 (host 기준)"


def c_symlinks():
    """추적되는 심볼릭 링크는 밸브의 구멍이다.

    2026-08-24 실측: `ln -s _private/work/secret.md leak.md` 후 `git add leak.md`가
    통과한다. git이 저장하는 것은 내용이 아니라 대상 경로라 내용 자체는 안 나가지만,
    경로가 구조를 드러내고 아카이브·역참조 설정에 따라 내용까지 갈 수 있다.
    """
    # -z로 읽는다. git은 특수문자 경로를 따옴표로 감싸므로 줄 단위 파싱은 경로를 망친다
    # (2026-08-24 실측: 따옴표 붙은 경로를 readlink에 넘겨 33개를 "문제 없음"으로 오판했다).
    import memlib as M
    r = subprocess.run(["git", "ls-files", "-s", "-z"], capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        return SKIP, "git 저장소 아님"
    links = [rec.split("\t", 1)[1] for rec in r.stdout.split("\0")
             if rec.startswith("120000") and "\t" in rec]
    if not links:
        return PASS, "추적 심볼릭 링크 0"
    priv = os.path.realpath(os.path.join(ROOT, "_private"))
    into_private = []
    for l in links:
        full = os.path.join(ROOT, l)
        try:
            raw = os.readlink(full)
        except OSError:
            raw = ""
        if os.path.realpath(full).startswith(priv) or "_private" in raw:
            into_private.append(f"{l[-52:]}  ->  {raw[-52:]}")
    if into_private:
        more = f"\n      … 외 {len(into_private) - 3}개" if len(into_private) > 3 else ""
        head = (f"_private을 가리키는 추적 링크 {len(into_private)}개 — 대상 경로 문자열이"
                " 원격에 올라간다 (내용은 안 간다. 구조와 파일명만):\n      "
                + "\n      ".join(into_private[:3]) + more)
        # 심각도는 인스턴스에 달렸다. work면 회사 구조가 나가는 것이라 차단이고,
        # personal이면 자기 프라이빗 원격에 자기 파일명이 가는 것이라 경고다.
        # (2026-08-24: 안 고쳐질 FAIL을 계속 띄우면 사람이 FAIL을 무시하게 된다 — 오늘의 교훈.)
        if M.INSTANCE_CONTEXT == "work":
            return FAIL, head
        return WARN, head + "\n      정리하려면: git rm --cached <경로> (파일은 디스크에 남는다)"
    return WARN, f"추적 심볼릭 링크 {len(links)}개 (대상이 _private 밖)"


def c_missed_gate():
    """**새 산출물이 커밋됐는데 그 전에 검사기가 안 돌았나** (DR-033).

    이것이 2026-08-24의 대표 미스다. 킷을 만들고 커밋했는데 `linkcheck`를 안 돌려
    깨진 참조 27개가 "검증 완료"로 나갔다. 그때는 **안 돌렸다는 사실 자체가 관측되지
    않았다** — 도구 실행에 기록이 없었기 때문이다.

    자기보고가 아니다. git이 새 파일을 세고, 도구가 자기 실행을 남긴다. 둘 다 기계다.
    """
    import memlib as M
    r = sh("git", "log", "-1", "--format=%cI")
    if r.returncode or not r.stdout.strip():
        return SKIP, "커밋 없음"
    ct = r.stdout.strip()
    added = sh("git", "show", "--diff-filter=A", "--name-only", "--format=", "HEAD").stdout.split()
    if not added:
        return PASS, "마지막 커밋에 새 파일 없음"
    last = M.last_run("linkcheck")
    if last is None:
        return WARN, (f"마지막 커밋이 새 파일 {len(added)}개를 넣었는데 linkcheck 실행 기록이 없다\n"
                      "      (기록은 오늘 신설됐다. 이 경고는 다음 커밋부터 의미가 생긴다)")
    if last < ct:
        return FAIL, (f"새 파일 {len(added)}개를 커밋했는데 그 뒤로 linkcheck를 안 돌렸다:\n      "
                      + ", ".join(added[:4])
                      + f"\n      마지막 linkcheck {last[:16]} < 커밋 {ct[:16]}")
    return PASS, f"새 파일 {len(added)}개 · 커밋 뒤 linkcheck 실행됨"


def c_agents_parity():
    """CLAUDE.md와 AGENTS.md가 같은가.

    두 런타임이 같은 규약 위에서 돌게 하려고 바이트 동일 사본을 둔다. 2026-08-24 실측:
    두 파일이 함께 존재한 커밋 3개 전부 동일했다 — **드리프트는 한 번도 안 났다.**
    다만 그걸 지켜온 것은 구조가 아니라 사람이 손으로 맞춘 것이고 표본은 4일이다.
    그래서 메커니즘(포인터·심볼릭링크)을 바꾸는 대신 탐지기를 둔다. 비용이 0에 가깝다.
    """
    a, b = os.path.join(ROOT, "CLAUDE.md"), os.path.join(ROOT, "AGENTS.md")
    if not os.path.exists(a):
        return FAIL, "CLAUDE.md 없음"
    if not os.path.exists(b):
        return WARN, "AGENTS.md 없음 — Codex가 규약을 못 읽는다"
    x, y = open(a, "rb").read(), open(b, "rb").read()
    if x == y:
        return PASS, f"바이트 동일 ({len(x)} bytes)"
    return FAIL, (f"갈라졌다 (CLAUDE {len(x)} / AGENTS {len(y)} bytes) — "
                  "두 런타임이 다른 규약을 읽는다. cp CLAUDE.md AGENTS.md")


def c_schema():
    """config가 엔진보다 뒤처졌나 (KIT-DR-005).

    엔진은 `git pull`로 오지만 **config는 인스턴스 소유라 안 온다.** 새 엔진이 새 필드를
    요구하면 옛 config는 그 필드가 없고, 없는 채로 조용히 다른 동작을 한다.
    2026-08-24 실측: instance.context가 없으면 밸브 검사가 personal로 간주해 원격을 안 본다.
    """
    import memlib as M
    gap = M.schema_gap()
    if gap is None:
        return PASS, f"schema v{M.CONFIG_SCHEMA} (엔진 기대 v{M.SCHEMA_VERSION})"
    cur, want, todo = gap
    return FAIL, (f"config schema v{cur} < 엔진 기대 v{want} — 아래를 config에 반영해라:\n      "
                  + "\n      ".join(todo)
                  + f'\n      반영 후 "schema_version": {want} 로 올린다')


def c_upstream():
    """엔진 파일을 로컬에서 고쳤나 · 업스트림과 몇 커밋 차이인가.

    엔진은 업스트림 소유다. 로컬에서 고치면 다음 pull에서 충돌하거나 조용히 되돌아간다.
    고칠 게 있으면 인스턴스 소유 짝(rituals.local.md 등)에 쓰거나 업스트림에 알린다.
    """
    r = sh("git", "rev-parse", "--is-inside-work-tree")
    if r.returncode:
        return SKIP, "git 저장소 아님"
    # 상류(엔진을 저작하는 인스턴스)에서는 엔진 수정이 정상이다. 표지는 kit_sync.py의 존재 —
    # 내보내기 도구는 상류에만 산다 (kit_sync.py의 EXCLUDED 참조).
    if os.path.exists(os.path.join(ROOT, "tools", "kit_sync.py")):
        return SKIP, "여기가 상류다 (kit_sync 보유) — 엔진 수정이 정상"
    # 추적 파일 중 수정된 것 = 전부 엔진 (인스턴스 소유는 추적 안 되므로)
    mod = [l[3:] for l in sh("git", "status", "--porcelain").stdout.splitlines()
           if l[:2].strip() in ("M", "MM", "AM", "D")]
    up = sh("git", "rev-list", "--count", "HEAD..@{u}")
    behind = up.stdout.strip() if up.returncode == 0 else None
    msgs = []
    if mod:
        msgs.append("로컬에서 수정된 엔진 파일 — 다음 pull에서 충돌하거나 되돌아간다:\n      "
                    + ", ".join(mod[:6]))
    if behind and behind != "0":
        msgs.append(f"업스트림보다 {behind}커밋 뒤처짐 — `git pull` 후 doctor를 다시 돌려라")
    if msgs:
        return WARN, "\n      ".join(msgs)
    return PASS, ("엔진 로컬 수정 0" + (f" · 업스트림 동기" if behind == "0" else " · 업스트림 미설정"))


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
    """연료가 git에서 안 보이는가. **추적 여부가 아니라 노출 여부**를 본다.

    2026-08-24 적대 검증: 이전 판은 probe가 이미 tracked일 때만 경고해서,
    `.gitignore`를 통째로 지워 연료가 untracked로 드러난 가장 위험한 상태를 PASS로 셌다.
    """
    r = sh("git", "rev-parse", "--is-inside-work-tree")
    if r.returncode:
        return SKIP, "git 저장소 아님"
    import memlib as M
    probes = ["state/NOW.md", "state/journal-x.md", "_private/x.md",
              "system/memory-config.json", "company/tracker.md", "notes.md"]
    not_ignored = [x for x in probes if sh("git", "check-ignore", "-q", x).returncode != 0]
    tracked = [x for x in probes if sh("git", "ls-files", "--error-unmatch", x).returncode == 0]
    st = sh("git", "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    exposed = [l[3:] for l in st if l.startswith("??")]

    if M.INSTANCE_CONTEXT != "work":
        # 개인 인스턴스는 트랙 문서를 일부러 추적한다. 규칙 부재는 정상이고 노출만 본다.
        return (PASS, f"context=personal — 노출 {len(exposed)}개 (트랙 문서 추적은 정상)") \
            if len(exposed) < 20 else (WARN, f"untracked 노출 {len(exposed)}개")

    msgs = []
    still = [x for x in not_ignored if x not in tracked]
    if still:
        msgs.append("ignore 규칙이 안 잡는 경로: " + ", ".join(still))
    if exposed:
        msgs.append(f"untracked 노출 {len(exposed)}개 — 커밋 한 번이면 나간다: "
                    + ", ".join(exposed[:4]))
    if tracked:
        msgs.append("이미 추적 중: " + ", ".join(tracked))
    if msgs:
        return FAIL, "\n      ".join(msgs)
    return PASS, f"probe {len(probes)}개 전부 ignore · untracked 노출 0"

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
    ("훅 · 배선 claude",        c_hook_wiring),
    ("훅 · 배선 codex",         c_hook_wiring_codex),
    ("훅 · codex 실행",         c_hook_codex_run),
    ("훅 · 성공 분기",          c_hook_success),
    ("훅 · 실패 분기",          c_hook_failure),
    ("훅 · 전역 시각 주입",     c_global_hook),
    ("훅 · 슬래시 커맨드",      c_commands),
    ("도구 · 실행",            c_tools_run),
    ("도구 · 링크 무결성",      c_links),
    ("도구 · 정합성",          c_coherence),
    ("도구 · 회귀 픽스처",      c_regression),
    ("도구 · recall 소스",     c_recall),
    ("도구 · 원장",            c_ledger),
    ("밸브 · 원격 검사",        c_valve),
    ("밸브 · 연료 비추적",      c_ignored),
    ("밸브 · 추적 심볼릭링크",   c_symlinks),
    ("게이트 · 산출물 검사누락",  c_missed_gate),
    ("규약 · CLAUDE=AGENTS",    c_agents_parity),
    ("엔진 · config 스키마",    c_schema),
    ("엔진 · 업스트림",         c_upstream),
    ("엔진 · 킷 드리프트",      c_engine_drift),
]

# 자동 검사 불가 — 이 목록이 이 도구의 반증 가능 칸이다.
# 여기 있는 것을 "확인했다"고 말하면 거짓이다. 사람이 해야 한다.
MANUAL = [
    ("SessionStart 훅이 실제로 모델 컨텍스트에 들어갔는가",
     "훅 출력은 모델에게만 가고 셸로 안 온다. doctor는 '유효 JSON을 뱉는다'까지만 안다.\n"
     "     카나리아 법 (2026-08-24 실측으로 작동 확인):\n"
     "       python3 tools/now.py log \"[system/artifact] 카나리아 ZEBRA-7741\"\n"
     "       claude -p \"NOW 파일을 읽지 말고, 주입된 내용만으로 답해라. 카나리아 문자열은?\"\n"
     "     문자열이 그대로 나오면 주입된 것이다. 파일을 읽으러 가면 훅이 안 도는 것이다."),
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

    __import__("sys").path.insert(0, HERE)
    import memlib as _M; _M.log_run("doctor", f"fail={n[FAIL]} warn={n[WARN]}")
    if n[FAIL]:
        print(f"\nFAIL {n[FAIL]}개를 먼저 고쳐라. 그 전에는 이 인스턴스의 상태 자동화를 믿지 마라.")
    return 1 if n[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
