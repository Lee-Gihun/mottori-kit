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

# 역사적/동결 문서: 옛 경로를 의도적으로 담고 있어 기본 제외.
# 목록은 인스턴스 고유값이라 config에 산다 (DR-025) — 왜 제외하는지도 거기 적혀 있다.
EXCLUDE_PREFIXES = tuple(M.check_config("linkcheck_exclude_prefixes", []))

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODEREF = re.compile(r"`([A-Za-z0-9_\-./·]+\.(?:md|txt|tex|py|html|json|pdf|docx|sh))`")

def tracked_md():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "--cached", "--others",
                          "--exclude-standard", "*.md"], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]

def is_real_path(t):
    # 오탐 필터: 섹션 앵커, 줄번호, 축약 표기, 한글 구분점 포함 표기
    if t.startswith(("§", "L")) and not "/" in t: return False
    if "..." in t or "·" in t: return False
    return True

def check():
    broken, checked = [], 0
    for rel in tracked_md():
        if not INCLUDE_ALL and rel.startswith(EXCLUDE_PREFIXES):
            continue
        fp = os.path.join(ROOT, rel)
        try:
            text = open(fp, encoding="utf-8").read()
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
            if not (os.path.exists(os.path.join(base, t2)) or os.path.exists(os.path.join(ROOT, t2))):
                broken.append((rel, t))
    return broken, checked

if __name__ == "__main__":
    broken, checked = check()
    scope = "ALL (동결 포함)" if INCLUDE_ALL else "라이브 문서 (동결 제외)"
    print(f"[linkcheck] scope={scope}, refs={checked}")
    for rel, t in sorted(broken):
        print(f"BROKEN {rel} -> {t}")
    print(f"[linkcheck] broken: {len(broken)}")
    sys.exit(1 if broken else 0)
