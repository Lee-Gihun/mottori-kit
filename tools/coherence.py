#!/usr/bin/env python3
"""Report document consistency issues without changing files.

Checks links, an optional fact ledger, unindexed files newer than their hub, and stale document headers.
These checks do not establish that a response or action succeeded.

Usage: python3 tools/coherence.py [--quiet]
Exit 1 for issues, 0 otherwise. --quiet prints a one-line summary."""
import os, re, subprocess, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M

ROOT = M.ROOT
QUIET = "--quiet" in sys.argv
TODAY = datetime.date.today()

# Checker inventories are instance data from config: directory/index pairs.
HUBS = [tuple(x) for x in M.check_config("hubs", [])]
HUB_IGNORE_EXT = set(M.check_config("hub_ignore_ext", [".pyc", ".DS_Store"]))

# Status limits pair each path with the permitted age of its first header date.
STATUS_DOCS = [tuple(x) for x in M.check_config("status_docs", [])]
DATE_PAT = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def check_links():
    """Return (broken count or None, details). None means the checker could not produce a measurement."""
    r = run(["python3", "tools/linkcheck.py"])
    m = re.search(r"broken: (\d+)", r.stdout)
    n = int(m.group(1)) if m else None
    detail = [l for l in r.stdout.splitlines() if l.startswith("BROKEN")]
    if n is None:
        detail = [f"linkcheck 측정 실패 (exit {r.returncode}): {(r.stderr or r.stdout).strip()[-160:]}"]
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
            # Report a newer file only when the index does not mention it.
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
    if n_links is None:
        problems.append("linkcheck 측정 실패")
    elif n_links != 0:
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
