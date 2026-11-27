#!/usr/bin/env python3
"""Harvest person-ledger candidates without accepting them automatically.

Read journal decisions and corrections from the ledger's last review on. The review date is the one
line `last-reviewed: YYYY-MM-DD` in the ledger, and that day is included, because entries logged
later on the review day were not reviewed. A reviewer chooses which candidates belong in the ledger;
harvesting alone does not turn an interpretation into an attributed fact.

Usage: python3 tools/person_ledger.py [stale | candidates [YYYY-MM-DD]]
  stale       count the decisions and corrections not yet harvested since the last review (the default)
  candidates  list journal decisions and corrections since the last review, or since the given day"""
import datetime
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import journal as J
import paths as P

# Messages this module prints in more than one place, or too long to read inline.
CANDIDATES_HEAD = (
    "# Person ledger candidates from {date} on: {count}\n# Never adopt automatically. Pick "
    "what to move into the ledger.\n# Adopt only when both hold: (1) a short cue cannot restore "
    "it (2) without it the owner would have to say it again"
)
NO_REVIEW_LINE = (
    "[person_ledger] the person ledger has no `last-reviewed: YYYY-MM-DD` line. Add one after a "
    "review, or give the start day: python3 tools/person_ledger.py candidates YYYY-MM-DD"
)
STALE = (
    "[person_ledger] last review {date} · decision or correction entries from that day on not yet "
    "harvested: {count} (threshold {threshold})"
)

# The person ledger records how the instance's owner decides and what they correct. Its file,
# _private/self-portrait-mirror.md, is the one this tool reads.
PORTRAIT = P.portrait()

# Only decisions and corrections contribute person-ledger candidates; state and artifacts describe task progress.
HARVEST_TYPES = ("correction", "decision")

# Operational backlog threshold, not a measured universal limit.
STALE_THRESHOLD = 20

# One fixed form: any other date in the ledger prose is a plan, a deadline or a quoted event, not a review.
REVIEWED = re.compile(r"^last-reviewed:[ \t]*(\d{4}-\d{2}-\d{2})[ \t]*$", re.M)


def _entries():
    """Public and private journal events as (date, track, type, body), oldest first.

    Most personal decisions and corrections are logged with `log --private`, so the private journal
    must count too. Its bodies only reach the local terminal through `candidates`."""
    return [(e["ts"][:10], e["track"], e["type"], e["body"]) for e in J.parse_journal()]


def last_update():
    """Return the latest review date, "" when the ledger has no valid review line, None without a ledger.

    A review line after today is a typing slip and would hide every candidate, so it is ignored."""
    if not os.path.exists(PORTRAIT):
        return None
    with open(PORTRAIT, encoding="utf-8", errors="replace") as fh:
        found = REVIEWED.findall(fh.read())
    today = datetime.date.today().isoformat()
    dates = [d for d in found if C.is_day(d) and d <= today]
    return max(dates) if dates else ""


def pending(since):
    """Return harvestable journal entries on or after `since`; doctor shares this filter."""
    return [e for e in _entries() if since and e[0] >= since and e[2] in HARVEST_TYPES]


def stale():
    since = last_update()
    if since is None:
        print("[person_ledger] no person ledger; nothing to check")
        return 0
    if not since:
        # Guessing a start from other dates either hides corrections or floods old ones.
        print(NO_REVIEW_LINE)
        return 1
    pending_rows = pending(since)
    print(STALE.format(date=since, count=len(pending_rows), threshold=STALE_THRESHOLD))
    if pending_rows:
        by_day = {}
        for d, _, typ, _ in pending_rows:
            by_day.setdefault(d, []).append(typ)
        for d in sorted(by_day):
            kinds = ", ".join(f"{k}×{by_day[d].count(k)}" for k in sorted(set(by_day[d])))
            print(f"    {d}  {kinds}")
        print("  → python3 tools/person_ledger.py candidates")
    return 0


def candidates(since=None):
    since = since or last_update()
    if not since:
        return stale()  # no ledger or no review line: say so in stale's words
    rows = pending(since)
    if not rows:
        print(f"[person_ledger] no candidates from {since} on")
        return 0
    print(CANDIDATES_HEAD.format(date=since, count=len(rows)) + "\n")
    for d, track, typ, body in rows:
        print(f"- {d} | [{track}/{typ}] {body}")
    return 0


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("stale", [])
    if cmd in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if cmd == "stale" and not args:
        sys.exit(stale())
    if cmd == "candidates" and len(args) <= 1 and all(C.is_day(a) for a in args):
        sys.exit(candidates(args[0] if args else None))
    # An ignored option or a start that compares wrongly as text would look honoured.
    print(__doc__)
    sys.exit(2)
