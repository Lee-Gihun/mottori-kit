#!/usr/bin/env python3
"""Report document consistency issues without changing files.

Checks links, an optional fact ledger, unindexed files newer than their hub, and stale document headers.
These checks do not establish that a response or action succeeded.

Usage: python3 tools/coherence.py [--quiet]
Exit 1 for issues, 0 otherwise. --quiet prints a one-line summary."""
import os, re, subprocess, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M
from i18n import STRINGS, t

ROOT = M.ROOT
QUIET = "--quiet" in sys.argv
TODAY = datetime.date.today()

# Checker inventories are instance data from config: directory/index pairs.
HUBS = [tuple(x) for x in M.check_config("hubs", [])]
HUB_IGNORE_EXT = set(M.check_config("hub_ignore_ext", [".pyc", ".DS_Store"]))

# Status limits pair each path with the permitted age of its first header date.
STATUS_DOCS = [tuple(x) for x in M.check_config("status_docs", [])]
DATE_PAT = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def trailer_count(text, key):
    """Read a count from a catalog line in either language, or None when no form matches.

    The line was printed by another tool under its own language setting, so both forms are tried.
    """
    for lang in ("en", "ko"):
        pattern = re.escape(STRINGS[key][lang]).replace(r"\{count\}", r"(\d+)")
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def check_links():
    """Return (broken count or None, details). None means the checker could not produce a measurement."""
    r = run(["python3", "tools/linkcheck.py"])
    m = re.search(r"broken: (\d+)", r.stdout)
    n = int(m.group(1)) if m else None
    detail = [l for l in r.stdout.splitlines() if l.startswith("BROKEN")]
    if n is None:
        detail = [t("coherence.linkcheck_failed_detail", code=r.returncode,
                    detail=(r.stderr or r.stdout).strip()[-160:])]
    return n, detail


def check_ledger():
    if not os.path.isdir(os.path.join(ROOT, "_private/ledger/facts")):
        return None, []
    r = run(["python3", "tools/rec.py", "check"])
    n = trailer_count(r.stdout, "rec.check_trailer")
    n = -1 if n is None else n
    detail = [l for l in r.stdout.splitlines() if l.startswith("PROBLEM")]
    return n, detail


def check_hubs():
    issues = []
    for d, idx in HUBS:
        dpath, ipath = os.path.join(ROOT, d), os.path.join(ROOT, d, idx)
        if not os.path.exists(ipath):
            issues.append(t("coherence.hub_no_index", dir=d, index=idx))
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
            issues.append(t("coherence.hub_unlisted", dir=d, index=idx, count=len(missing),
                            names=", ".join(sorted(missing)[:5]) + (" …" if len(missing) > 5 else "")))
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
            issues.append(t("coherence.status_no_date", path=f))
            continue
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        age = (TODAY - d).days
        if age > max_days:
            issues.append(t("coherence.status_stale", path=f, age=age, max_days=max_days, date=d))
    return issues


def main():
    problems = []

    n_links, d_links = check_links()
    if n_links is None:
        problems.append(t("coherence.linkcheck_failed"))
    elif n_links != 0:
        problems.append(t("coherence.broken_links", count=n_links))

    n_led, d_led = check_ledger()
    if n_led not in (0, None):
        problems.append(t("coherence.ledger_problems", count=n_led))

    hub_issues = check_hubs()
    problems += hub_issues

    stale = check_status_docs()
    problems += stale

    if QUIET:
        if problems:
            print(t("coherence.quiet_issues", count=len(problems),
                    items=" | ".join(problems[:4]) + (" …" if len(problems) > 4 else "")))
        else:
            print(t("coherence.quiet_clean"))
        M.log_run("coherence", f"issues={len(problems)}")
        return 1 if problems else 0

    ledger = "OK" if n_led == 0 else (t("coherence.ledger_absent") if n_led is None else n_led)
    print(t("coherence.summary", today=TODAY, links="OK" if n_links == 0 else n_links, ledger=ledger,
            hubs="OK" if not hub_issues else t("coherence.count", count=len(hub_issues)),
            stale="OK" if not stale else t("coherence.count", count=len(stale))))
    for sec, items in (("links", d_links), ("ledger", d_led), ("hubs", hub_issues), ("stale", stale)):
        for it in items:
            print(f"  [{t('coherence.section.' + sec)}] {it}")
    print(t("coherence.total", count=len(problems)))
    M.log_run("coherence", f"issues={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
