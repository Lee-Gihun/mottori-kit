#!/usr/bin/env python3
"""Report document consistency issues without changing documents (appends one run line to state/.tool-runs.log).

Checks unindexed files newer than their hub and stale document headers. Links and the fact ledger
have their own checkers (linkcheck.py, facts.py check), and doctor runs all of them.
These checks do not establish that a response or action succeeded.

Usage: python3 tools/coherence.py [--help]
Exit 1 for issues, 0 otherwise. A malformed checks row in the instance config is one issue."""
import datetime, json, os, re, sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import paths as P
import runlog

# Importing this module reads no file; each check reads the configuration when it runs.

# Messages this module prints in more than one place, or too long to read inline.
STATUS_NO_DATE = "{path}: no update date in the header"

# What a row of each checks.<key> list holds, named in the issue a malformed row raises.
ROW_SHAPE = {
    "hubs": "[directory, index file]",
    "status_docs": "[file, allowed days as a whole number]",
    "hub_ignore_ext": 'a file extension such as ".pyc"',
}
SECTION = {"hubs": "hubs", "stale": "staleness"}


def _config_rows(key, valid, default):
    """Read checks.<key> as a list of rows; a malformed row becomes an issue, not a crash.

    The config loader only checks that checks is an object, so the row shape is checked here."""
    value = C.check_config(key, default)
    shape = ROW_SHAPE[key]
    if not isinstance(value, list):
        return [], ["{config} {name} must be a list, each row {shape}".format(
            config=C.CONFIG_NAME, name="checks." + key, shape=shape)]
    rows, issues = [], []
    for i, row in enumerate(value, 1):
        if valid(row):
            rows.append(tuple(row) if isinstance(row, list) else row)
        else:
            issues.append((
                "{config} {name} row {row} must be {shape}, not {value}"
            ).format(config=C.CONFIG_NAME, name="checks." + key, row=i, shape=shape, value=json.dumps(row, ensure_ascii=False)))
    return rows, issues


def _pair(second):
    return lambda row: (isinstance(row, list) and len(row) == 2 and isinstance(row[0], str)
                        and isinstance(row[1], second) and not isinstance(row[1], bool))


DATE_PAT = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def check_hubs():
    # Checker inventories are instance data from config: directory/index pairs. Dotfiles are always
    # skipped, so the default needs no .DS_Store.
    root = P.instance_root()
    hubs, issues = _config_rows("hubs", _pair(str), [])
    ignore, ignore_issues = _config_rows("hub_ignore_ext", lambda row: isinstance(row, str), [".pyc"])
    issues += ignore_issues
    for d, idx in hubs:
        dpath, ipath = os.path.join(root, d), os.path.join(root, d, idx)
        if not os.path.exists(ipath):
            issues.append(f"{d}: index missing ({idx})")
            continue
        itext = open(ipath, encoding="utf-8").read()
        imtime = os.path.getmtime(ipath)
        missing = []
        for f in os.listdir(dpath):
            fp = os.path.join(dpath, f)
            if f == idx or f.startswith(".") or os.path.isdir(fp):
                continue
            if os.path.splitext(f)[1] in ignore:
                continue
            # Report a newer file only when the index does not mention it.
            # Bounded match so a.md is not counted as listed inside data.md; a path prefix like dir/a.md still counts.
            listed = re.search(r"(?<![\w.-])" + re.escape(f) + r"(?![\w-])", itext)
            if os.path.getmtime(fp) > imtime and not listed:
                missing.append(f)
        if missing:
            issues.append("{dir}/{index}: {count} new file(s) not listed: {names}".format(dir=d, index=idx, count=len(missing), names=", ".join(sorted(missing)[:5]) + (" …" if len(missing) > 5 else "")))
    return issues


def check_status_docs(today=None):
    # Status limits pair each path with the permitted age of its first header date.
    root, today = P.instance_root(), today or datetime.date.today()
    status_docs, issues = _config_rows("status_docs", _pair(int), [])
    for f, max_days in status_docs:
        p = os.path.join(root, f)
        if not os.path.exists(p):
            # A renamed or deleted status document would otherwise pass as fresh.
            issues.append(f"{f}: listed in checks.status_docs but missing")
            continue
        head = open(p, encoding="utf-8").read(600)
        m = DATE_PAT.search(head)
        if not m:
            issues.append(STATUS_NO_DATE.format(path=f))
            continue
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            # An impossible date such as 2026-13-40 is one issue for this file, not a crash of the run.
            issues.append(STATUS_NO_DATE.format(path=f))
            continue
        age = (today - d).days
        if age > max_days:
            issues.append(f"{f}: updated {age} day(s) ago (allowed {max_days}, header {d})")
    return issues


def configured():
    """Whether the instance lists anything for this tool to check."""
    hubs, _ = _config_rows("hubs", _pair(str), [])
    status_docs, _ = _config_rows("status_docs", _pair(int), [])
    return bool(hubs or status_docs)


NOTHING_LISTED = "nothing to check: checks.hubs and checks.status_docs list nothing"


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return 0
    if not configured() and not (check_hubs() or check_status_docs()):
        print(f"[coherence] {NOTHING_LISTED} in {C.CONFIG_NAME}")
        return 0
    today = datetime.date.today()
    hub_issues, stale = check_hubs(), check_status_docs(today)
    problems = hub_issues + stale
    hubs = len(hub_issues) if hub_issues else "OK"
    print(f"[coherence] {today}: hubs {hubs} · staleness {len(stale) if stale else 'OK'}")
    for sec, items in (("hubs", hub_issues), ("stale", stale)):
        for it in items:
            print(f"  [{SECTION[sec]}] {it}")
    print(f"[coherence] total {len(problems)}")
    runlog.log_run("coherence", f"issues={len(problems)}", ok=not problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
