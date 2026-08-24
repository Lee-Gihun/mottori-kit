#!/usr/bin/env python3
"""링크 무결성 검증기 — 추적 중인 .md의 상대 경로 참조를 검사한다.

추적 중인 .md 파일의 상대 경로 참조([텍스트](경로), `경로/파일.ext`)가 실제로 존재하는지 검사한다.
동결/아카이브 구역(archive/, jobs/archive/, evidence/, research/00-CONTEXT 등)은 역사적 참조를
보존하므로 기본 제외한다. 재편·인덱스 갱신 후 반드시 실행 (CLAUDE.md 규칙).

사용: python3 tools/linkcheck.py [--all]   (--all = 제외 구역 포함 전수)
"""
import os, re, subprocess, sys, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M

ROOT = M.ROOT
INCLUDE_ALL = "--all" in sys.argv

# `--tree DIR`: 파일 내용을 다른 트리에서 읽는다 (pre-commit이 index를 꺼내 검사할 때).
# 설정과 제외 목록은 인스턴스 것을 그대로 쓴다 — 트리만 갈아끼우는 것이 요점이다.
def _opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv[:-1] else default

TREE = os.path.abspath(_opt("--tree", ROOT))
FILELIST = _opt("--filelist")          # 주면 git 대신 이 파일에서 목록을 읽는다

# 역사적/동결 문서: 옛 경로를 의도적으로 담고 있어 기본 제외.
# 목록은 인스턴스 고유값이라 config에 산다 (DR-025) — 왜 제외하는지도 거기 적혀 있다.
EXCLUDE_PREFIXES = tuple(M.check_config("linkcheck_exclude_prefixes", []))

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODEREF = re.compile(r"`([A-Za-z0-9_\-./·]+\.(?:md|txt|tex|py|html|json|pdf|docx|sh))`")

def tracked_md():
    if FILELIST:
        return [l for l in open(FILELIST, encoding="utf-8").read().splitlines() if l.strip()]
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "--cached", "--others",
                          "--exclude-standard", "*.md"], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]

def is_real_path(t):
    # 오탐 필터: 섹션 앵커, 줄번호, 축약 표기, 한글 구분점 포함 표기
    if t.startswith(("§", "L")) and not "/" in t: return False
    if "..." in t or "·" in t: return False
    return True

def strip_fences(text):
    """펜스 코드블록을 지운다.

    블록 안은 실행 예시지 참조가 아니다. 일부러 깨진 경로를 보여주는 검증 절차
    (CHECKLIST의 게이트 시험)가 문서 자신을 FAIL 시키는 것을 실측하고 넣었다.
    코드블록이 기여하던 실제 커버리지는 거의 없다 — 인라인 백틱(CODEREF)과
    마크다운 링크는 블록 밖에서 잡히고, 블록 안의 셸 명령은 원래 두 패턴 어디에도
    안 걸렸다.

    앞의 공백을 허용하는 이유: 리스트 항목 안의 코드블록은 들여쓰기된다. 첫 판이
    `^```` 로만 잡아서 그런 블록을 통째로 놓쳤다 (클린 클론 e2e에서 실측)."""
    return re.sub(r"^[ \t]*```.*?^[ \t]*```", "", text, flags=re.S | re.M)


_IGN_CACHE = {}

def _is_ignored(rel):
    """`git check-ignore`가 이 경로를 무시 대상이라고 증명하는가. 호출당 프로세스라 캐시한다."""
    if rel not in _IGN_CACHE:
        r = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", "--", rel],
                           capture_output=True)
        _IGN_CACHE[rel] = (r.returncode == 0)
    return _IGN_CACHE[rel]


def check():
    broken, checked = [], 0
    for rel in tracked_md():
        if not INCLUDE_ALL and rel.startswith(EXCLUDE_PREFIXES):
            continue
        fp = os.path.join(TREE, rel)
        try:
            text = strip_fences(open(fp, encoding="utf-8").read())
        except Exception:
            continue
        base = os.path.dirname(fp)
        targets = set()
        for m in LINK.finditer(text):
            t = m.group(1)
            if t.startswith(("http://", "https://", "mailto:", "#")): continue
            t = t.split("#")[0]
            if t and is_real_path(t): targets.add(t)
        for m in CODEREF.finditer(text):
            t = m.group(1)
            if "/" in t and is_real_path(t): targets.add(t)
        for t in targets:
            t2 = urllib.parse.unquote(t)
            checked += 1
            # TREE(=`--tree`면 index를 꺼낸 트리) 안에 있으면 통과. 심볼릭 링크 자체가
            # 엔트리인 경우가 있어 lexists도 본다.
            cands = [os.path.join(base, t2), os.path.join(TREE, t2)]
            if any(os.path.exists(c) or os.path.lexists(c) for c in cands):
                continue
            # **ROOT 폴백은 조건부다** (codex 라운드 4). 무조건 폴백하면 "worktree엔 있고
            # index엔 없는 대상"을 통째로 놓친다 — 그 커밋을 다른 클론에서 받으면 참조가 깨진다.
            # gitignore된 대상만 local-only 참조로 봐준다. 실측: 이 리포의 ROOT 전용 참조
            # 98건은 전부 gitignore 대상이었다.
            if TREE != ROOT:
                rc = [os.path.join(ROOT, os.path.dirname(rel), t2), os.path.join(ROOT, t2)]
                hit = next((c for c in rc if os.path.exists(c) or os.path.lexists(c)), None)
                if hit and _is_ignored(os.path.relpath(hit, ROOT)):
                    continue
            broken.append((rel, t))
    return broken, checked

if __name__ == "__main__":
    broken, checked = check()

    if "--issues" in sys.argv:
        # **이슈 집합 계약** (codex 라운드 3~4). 개수는 치환에 눈이 먼다 — 링크 하나 고치고
        # 하나 깨면 같은 수가 된다. `안정ID\t표시문구`를 내고 게이트가 집합 차를 본다.
        # 마지막 줄의 트레일러가 계약이다. 이게 없으면 "이슈 0"이 아니라 "측정 실패"다.
        # 이슈가 있어도 exit 0 — 종료코드는 "측정이 됐는가"만 뜻한다.
        #
        # ID에 파일과 대상을 둘 다 쓴다. 대상만 쓰면 같은 깨진 대상을 여러 파일에 퍼뜨리는
        # 것을 구분 못 한다. rename이 새 ID를 만드는 비용은 그 놓침보다 싸다 (codex 라운드 4).
        for rel, t in sorted(broken):
            print(f"{rel} -> {t}\t깨진 참조 {rel} -> {t}")
        print(f"#issues {len(broken)}")
        sys.exit(0)

    scope = "ALL (동결 포함)" if INCLUDE_ALL else "라이브 문서 (동결 제외)"
    print(f"[linkcheck] scope={scope}, refs={checked}")
    for rel, t in sorted(broken):
        print(f"BROKEN {rel} -> {t}")
    print(f"[linkcheck] broken: {len(broken)}")
    # **자기가 실제로 읽은 것의 해시를 남긴다** (codex 라운드 3 지적).
    # 이전엔 memlib이 git index 해시를 남겼는데, linkcheck는 worktree bytes를 읽고
    # untracked도 본다. 인증서의 입력과 검사기의 입력이 달랐다.
    import hashlib as _h
    _d = _h.sha1()
    for _f in sorted(tracked_md()):
        _d.update(_f.encode())
        try:
            _d.update(open(os.path.join(ROOT, _f), "rb").read())
        except OSError:
            _d.update(b"<missing>")
    M.log_run("linkcheck", f"broken={len(broken)}", scope=_d.hexdigest()[:12],
              ok=(len(broken) == 0))
