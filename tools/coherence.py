#!/usr/bin/env python3
"""정합성 감지기 — 이 인스턴스의 문서 드리프트를 결정론으로 잡는다.

LLM 없이 결정론으로 드리프트를 감지한다 (수리는 안 한다 — 감지와 보고까지가 소관).
PRD-info-architecture §4.3(다중 방어)·§6.5(비용은 스캔에 있다 → 스캔을 공짜로)의 구현.

검사 4종:
  A. 링크 무결성        — linkcheck.py 위임
  B. 원장 정합성        — rec.py check 위임 (원장이 있을 때만)
  C. 허브 신선도        — 허브 README보다 새로운 파일이 디렉토리에 있는데 README에 미기재면 경고
  D. 상태 문서 유통기한  — 헤더의 갱신일이 문서별 허용 일수를 넘으면 경고

사용: python3 tools/coherence.py [--quiet]   (--quiet: 한 줄 요약만 — 훅용)
종료코드: 문제 있으면 1, 없으면 0.
"""
import os, re, subprocess, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M

ROOT = M.ROOT
QUIET = "--quiet" in sys.argv
TODAY = datetime.date.today()

# 검사 대상 목록은 전부 인스턴스 고유값이라 config에 산다 (DR-025).
# 허브 신선도: [디렉토리, 그 디렉토리의 인덱스 파일]
HUBS = [tuple(x) for x in M.check_config("hubs", [])]
HUB_IGNORE_EXT = set(M.check_config("hub_ignore_ext", [".pyc", ".DS_Store"]))

# 상태 문서 유통기한: [파일, 허용 일수] — 헤더의 첫 날짜(YYYY-MM-DD)를 갱신일로 간주
STATUS_DOCS = [tuple(x) for x in M.check_config("status_docs", [])]
DATE_PAT = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def check_links():
    r = run(["python3", "tools/linkcheck.py"])
    m = re.search(r"broken: (\d+)", r.stdout)
    n = int(m.group(1)) if m else -1
    detail = [l for l in r.stdout.splitlines() if l.startswith("BROKEN")]
    return n, detail


def check_ledger():
    if not os.path.isdir(os.path.join(ROOT, "_private/ledger/facts")):
        return None, []
    r = run(["python3", "tools/rec.py", "check"])
    m = re.search(r"문제: (\d+)건", r.stdout)
    n = int(m.group(1)) if m else -1
    detail = [l for l in r.stdout.splitlines() if l.startswith("PROBLEM")]
    return n, detail


def check_hubs():
    issues = []
    for d, idx in HUBS:
        dpath, ipath = os.path.join(ROOT, d), os.path.join(ROOT, d, idx)
        if not os.path.exists(ipath):
            issues.append(f"{d}: 인덱스 없음 ({idx})")
            continue
        itext = open(ipath, encoding="utf-8").read()
        imtime = os.path.getmtime(ipath)
        missing = []
        for f in os.listdir(dpath):
            fp = os.path.join(dpath, f)
            if f == idx or f.startswith(".") or os.path.isdir(fp):
                continue
            if os.path.splitext(f)[1] in HUB_IGNORE_EXT:
                continue
            # 인덱스보다 새로운 파일인데 인덱스 본문에 이름이 없다 → 미기재 신입
            if os.path.getmtime(fp) > imtime and f not in itext:
                missing.append(f)
        if missing:
            issues.append(f"{d}/{idx}: 미기재 신입 {len(missing)}개 — " + ", ".join(sorted(missing)[:5])
                          + (" …" if len(missing) > 5 else ""))
    return issues


def check_status_docs():
    issues = []
    for f, max_days in STATUS_DOCS:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        head = open(p, encoding="utf-8").read(600)
        m = DATE_PAT.search(head)
        if not m:
            issues.append(f"{f}: 헤더에 갱신일 없음")
            continue
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        age = (TODAY - d).days
        if age > max_days:
            issues.append(f"{f}: 갱신 {age}일 경과 (허용 {max_days}일, 헤더 {d})")
    return issues


def main():
    problems = []

    n_links, d_links = check_links()
    if n_links != 0:
        problems.append(f"깨진 링크 {n_links}")

    n_led, d_led = check_ledger()
    if n_led not in (0, None):
        problems.append(f"원장 문제 {n_led}")

    hub_issues = check_hubs()
    problems += hub_issues

    stale = check_status_docs()
    problems += stale

    if QUIET:
        if problems:
            print(f"[coherence] 이슈 {len(problems)}건: " + " | ".join(problems[:4])
                  + (" …" if len(problems) > 4 else ""))
        else:
            print("[coherence] 이상 없음")
        M.log_run("coherence", f"issues={len(problems)}")
        return 1 if problems else 0

    print(f"[coherence] {TODAY} — 링크 {'OK' if n_links == 0 else n_links}"
          f" · 원장 {'OK' if n_led == 0 else ('없음' if n_led is None else n_led)}"
          f" · 허브 {'OK' if not hub_issues else f'{len(hub_issues)}건'}"
          f" · 유통기한 {'OK' if not stale else f'{len(stale)}건'}")
    for sec, items in (("링크", d_links), ("원장", d_led), ("허브", hub_issues), ("유통기한", stale)):
        for it in items:
            print(f"  [{sec}] {it}")
    print(f"[coherence] 총 {len(problems)}건")
    M.log_run("coherence", f"issues={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
