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
    안 걸렸다."""
    return re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)


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
            # 존재는 TREE 먼저, 없으면 ROOT. `--tree`(index) 모드에서 gitignore된 대상
            # (심볼릭 링크가 가리키는 `_private/` 등)이 통째로 깨진 것으로 보이지 않게
            # 하려는 것이다. 그 대가로 "worktree엔 있고 index엔 없는 대상"은 못 잡는다.
            cands = [os.path.join(base, t2), os.path.join(TREE, t2)]
            if TREE != ROOT:
                cands += [os.path.join(ROOT, os.path.dirname(rel), t2), os.path.join(ROOT, t2)]
            if not any(os.path.exists(c) for c in cands):
                broken.append((rel, t))
    return broken, checked

if __name__ == "__main__":
    broken, checked = check()

    if "--issues" in sys.argv:
        # **이슈 집합 계약** (codex 라운드 3). 개수는 치환에 눈이 먼다 — 링크 하나 고치고
        # 하나 깨면 같은 수가 된다. ID를 내보내고 게이트가 집합 차를 본다.
        # 마지막 줄의 트레일러가 계약이다. 이게 없으면 "이슈 0"이 아니라 "측정 실패"다.
        for rel, t in sorted(broken):
            print(f"{rel} -> {t}")
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
