#!/usr/bin/env python3
"""Trigger store: things the instance should surface later, with a hard action-tier boundary.

A trigger is a small JSON record kept in ``_private/triggers/triggers.jsonl`` of the instance:

    id, when, what, tier, source, privacy, destination, tz, state, created, fired, outcome,
    shown, slept_until, leased_until, history

``privacy`` defaults to ``private`` and ``destination`` to ``local``: a trigger never reaches an
outward channel on its own, whatever its tier. Mutating commands take an exclusive file lock and replace the store atomically; ``due`` and ``list``
are read-only and never change the store unless ``due --mark`` is given. ``hook`` marks what it showed.
A lease (``claim``) names a holder; ``fire`` requires a live lease held by the same holder (claim, then
fire) and refuses to fire twice. Lease timestamps are UTC.

``when`` is one of ``date:YYYY-MM-DD``, ``file_change:<path>``, ``state:<predicate>`` or
``event:<name>``. Only ``date`` triggers are evaluated by this tool; the other kinds are stored so a
loop or a person can fire them.

Tiers are constants, not knobs:

    T0  say it        (always allowed)
    T1  prepare it    (draft into the private area, reversible, allowed unattended)
    T2  act outward   (send, commit, pay, delete; never unattended; surfaced as a draft plus one ask)

Sources that create triggers today: the experiments registry (due column), decision records with a
re-review date, and explicit ``add`` calls (for example from a transcript extraction step).

Usage:
  triggers.py add --when date:2026-10-02 --what "..." [--tier T1] [--source file:line] [--id ID]
  triggers.py due [--date YYYY-MM-DD] [--limit 5] [--mark]   due date triggers (read-only by default)
  triggers.py hook [--date YYYY-MM-DD] [--format claude|text] SessionStart context; marks shown
  triggers.py claim ID [--minutes 30] [--holder NAME]       lease before acting on a trigger
  triggers.py fire ID [--outcome TEXT] [--holder NAME]      needs this holder's live lease; refuses a repeat
  triggers.py sleep ID [--days 7]
  triggers.py list [--all]
  triggers.py scan [--experiments FILE] [--decisions FILE] [--date YYYY-MM-DD]

Design decision: KIT-DR-014.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys

ROOT = os.environ.get("MOTTORI_INSTANCE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_DIR = os.path.join(ROOT, "_private", "triggers")
STORE = os.path.join(STORE_DIR, "triggers.jsonl")
DEFAULT_EXPERIMENTS = os.path.join(ROOT, "_private", "work", "experiments.md")
DEFAULT_DECISIONS = os.path.join(ROOT, "system", "decisions.md")
CONFIG_PATH = os.path.join(ROOT, "system", "memory-config.json")

# Source parsers are data, not code: the instance config may override these patterns under
# ``triggers.sources`` (for example a Korean registry uses its own words for "closed" and
# "re-review"). Engine defaults are English so the kit tree stays language-clean.
DEFAULT_SOURCE_PATTERNS = {
    "experiments": {"row_id": r"\|\s*X\d+\s*\|", "closed_status": r"closed|done|withdrawn|retired"},
    "decisions": {"rereview_marker": "re-review", "cycles_later": r"(\d+)\s*cycles?\s*later"},
}

TIERS = ("T0", "T1", "T2")
PRIVACY = ("private", "public")
DESTINATIONS = ("local", "owner")   # "owner" = the owner's own channel; never an external party
STATES = ("open", "leased", "fired", "asleep")
TIER_LABEL = {"T0": "say", "T1": "prepare", "T2": "ask (outward action, never unattended)"}
WHEN_KINDS = ("date", "file_change", "state", "event")
HOOK_LIMIT = 5            # most triggers surfaced per session start
IGNORE_LIMIT = 3          # shown this many times without fire -> auto sleep
AUTO_SLEEP_DAYS = 7
CYCLE_DAYS = 7            # "N cycles later" in a decision record means N weekly cycles
MUTATING = ("add", "due", "hook", "claim", "fire", "sleep", "scan")   # due only with --mark


def default_holder():
    return os.environ.get("MOTTORI_ACTOR") or f"{os.environ.get('USER', 'user')}@{os.uname().nodename}"


def _utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


class TriggerError(ValueError):
    pass


def _today(value=None):
    if value:
        return dt.date.fromisoformat(value)
    return dt.date.today()


@contextlib.contextmanager
def _locked(exclusive=True):
    """Serialize load-modify-save cycles across processes. Read-only commands take a shared lock."""
    if exclusive:
        os.makedirs(STORE_DIR, exist_ok=True)
    with open(STORE + ".lock", "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _load():
    if not os.path.isfile(STORE):
        return []
    rows = []
    for line in open(STORE, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise TriggerError(f"corrupt trigger store line: {exc}")
    return rows


def _save(rows):
    os.makedirs(STORE_DIR, exist_ok=True)
    try:
        os.chmod(STORE_DIR, 0o700)
    except OSError:
        pass
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, STORE)
    try:
        os.chmod(STORE, 0o600)
    except OSError:
        pass


def parse_when(value):
    if ":" not in value:
        raise TriggerError(f"when must be <kind>:<value>, got {value!r}")
    kind, rest = value.split(":", 1)
    if kind not in WHEN_KINDS:
        raise TriggerError(f"unknown when kind {kind!r} (allowed: {', '.join(WHEN_KINDS)})")
    if kind == "date":
        try:
            dt.date.fromisoformat(rest)
        except ValueError:
            raise TriggerError(f"date trigger needs YYYY-MM-DD, got {rest!r}")
    elif not rest:
        raise TriggerError(f"{kind} trigger needs a value")
    return kind, rest


def make_id(when, what, source):
    digest = hashlib.sha256(f"{when}\n{what}\n{source or ''}".encode("utf-8")).hexdigest()[:10]
    return f"tr-{digest}"


def _event(row, kind, today, note=None):
    row.setdefault("history", []).append({"at": (today or dt.date.today()).isoformat(), "event": kind,
                                          **({"note": note} if note else {})})


def add(rows, when, what, tier="T1", source=None, trigger_id=None, today=None,
        privacy="private", destination="local", tz="local"):
    parse_when(when)
    if tier not in TIERS:
        raise TriggerError(f"tier must be one of {', '.join(TIERS)}")
    if privacy not in PRIVACY:
        raise TriggerError(f"privacy must be one of {', '.join(PRIVACY)}")
    if destination not in DESTINATIONS:
        raise TriggerError(f"destination must be one of {', '.join(DESTINATIONS)}")
    if not what or not what.strip():
        raise TriggerError("what must not be empty")
    trigger_id = trigger_id or make_id(when, what, source)
    for row in rows:
        if row["id"] == trigger_id:
            return row, False
    row = {"id": trigger_id, "when": when, "what": what.strip(), "tier": tier, "source": source,
           "privacy": privacy, "destination": destination, "tz": tz, "state": "open",
           "created": (today or dt.date.today()).isoformat(), "fired": None, "outcome": None,
           "shown": 0, "slept_until": None, "leased_until": None, "history": []}
    _event(row, "added", today)
    rows.append(row)
    return row, True


def _is_due(row, today):
    if row.get("fired"):
        return False
    slept = row.get("slept_until")
    if slept and dt.date.fromisoformat(slept) > today:
        return False
    kind, rest = parse_when(row["when"])
    if kind != "date":
        return False
    return dt.date.fromisoformat(rest) <= today


def due(rows, today, limit=HOOK_LIMIT, mark=True):
    """Return due date triggers, least shown first (carry-over), then oldest.

    With ``mark`` a returned row counts as shown, and a row already shown IGNORE_LIMIT times without
    being fired is put to sleep for AUTO_SLEEP_DAYS (its ``ignored`` counter grows). Without ``mark``
    nothing is written: such rows are only left out of the listing. Returns (rows, changed).
    """
    hits = [r for r in rows if _is_due(r, today)]
    # carry-over: least shown first, so a cap never starves the items behind it
    hits.sort(key=lambda r: (r.get("shown", 0), r["when"], r["created"], r["what"], r["id"]))
    out, changed = [], False
    for row in hits:
        if row.get("shown", 0) >= IGNORE_LIMIT:
            if mark:
                row["slept_until"] = (today + dt.timedelta(days=AUTO_SLEEP_DAYS)).isoformat()
                row["ignored"] = row.get("ignored", 0) + 1
                row["shown"] = 0
                row["state"] = "asleep"
                _event(row, "auto-sleep", today, f"shown {IGNORE_LIMIT} times without fire")
                changed = True
            continue
        out.append(row)
    out = out[:limit]
    if mark:
        for row in out:
            row["shown"] = row.get("shown", 0) + 1
            if row.get("state") == "asleep":
                row["state"] = "open"
        changed = changed or bool(out)
    return out, changed


def format_line(row):
    tier = row["tier"]
    head = f"- [{tier} {TIER_LABEL[tier]}] {row['what']}"
    tail = f" ({row['when']}; source {row['source']}; id {row['id']})" if row.get("source") \
        else f" ({row['when']}; id {row['id']})"
    if tier == "T2":
        head += " -> draft only; the owner performs the outward action"
    return head + tail


def _find(rows, trigger_id):
    for row in rows:
        if row["id"] == trigger_id:
            return row
    raise TriggerError(f"unknown trigger id {trigger_id}")


def _live_lease(row, now):
    lease = row.get("leased_until")
    if not lease:
        return None
    until = dt.datetime.fromisoformat(lease)
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.timezone.utc)
    return row.get("leased_by") if until > now else None


def claim(rows, trigger_id, minutes, holder, now=None):
    """Lease a trigger before acting on it (UTC). A live lease held by someone else is refused."""
    row = _find(rows, trigger_id)
    if row.get("fired"):
        raise TriggerError(f"trigger {trigger_id} already fired on {row['fired']}")
    now = now or _utcnow()
    other = _live_lease(row, now)
    if other and other != holder:
        raise TriggerError(f"trigger {trigger_id} is leased by {other} until {row['leased_until']}")
    row["leased_until"] = (now + dt.timedelta(minutes=minutes)).isoformat()
    row["leased_by"] = holder
    row["state"] = "leased"
    _event(row, "claimed", now.date(), f"{holder} {minutes} min")
    return row


def fire(rows, trigger_id, outcome=None, today=None, holder=None, now=None):
    """Mark a trigger done. Needs a live lease held by ``holder`` (claim first); refuses a repeat."""
    row = _find(rows, trigger_id)
    if row.get("fired"):
        raise TriggerError(f"trigger {trigger_id} already fired on {row['fired']}")
    lessee = _live_lease(row, now or _utcnow())
    if not lessee:
        raise TriggerError(f"trigger {trigger_id} has no live lease; claim it first")
    if lessee != holder:
        raise TriggerError(f"trigger {trigger_id} is leased by {lessee} until {row['leased_until']}")
    row["fired"] = (today or dt.date.today()).isoformat()
    row["outcome"] = outcome
    row["state"] = "fired"
    row["leased_until"] = None
    row["leased_by"] = None
    _event(row, "fired", today, f"{holder}: {outcome}" if holder else outcome)
    return row


def sleep(rows, trigger_id, days, today=None):
    row = _find(rows, trigger_id)
    row["slept_until"] = ((today or dt.date.today()) + dt.timedelta(days=days)).isoformat()
    row["shown"] = 0
    row["state"] = "asleep"
    _event(row, "sleep", today, f"{days} days")
    return row


# ---- sources -----------------------------------------------------------------------------------

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MD = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")


def source_patterns(config_path=CONFIG_PATH):
    """Engine defaults overlaid with ``triggers.sources`` from the instance config, if present.

    The override must be an object of objects whose values are strings; regex-valued keys must
    compile. Anything else is a TriggerError naming the key, never a stack trace from a scan.
    """
    patterns = {k: dict(v) for k, v in DEFAULT_SOURCE_PATTERNS.items()}
    try:
        cfg = json.load(open(config_path, encoding="utf-8"))
    except OSError:
        return patterns
    except ValueError as exc:
        raise TriggerError(f"config is not valid JSON: {exc}")
    if not isinstance(cfg, dict):
        raise TriggerError("config top level must be an object")
    if "triggers" not in cfg:
        return patterns
    section = cfg["triggers"]
    if not isinstance(section, dict):
        raise TriggerError("config triggers must be an object")
    if "sources" not in section:
        return patterns
    override = section["sources"]
    if not isinstance(override, dict):
        raise TriggerError("config triggers.sources must be an object")
    for source, values in override.items():
        if source not in patterns:
            continue
        if not isinstance(values, dict):
            raise TriggerError(f"config triggers.sources.{source} must be an object")
        for key, value in values.items():
            if key not in patterns[source] or not isinstance(value, str) or not value:
                raise TriggerError(f"config triggers.sources.{source}.{key} must be a non-empty string")
            if key != "rereview_marker":
                try:
                    re.compile(value)
                except re.error as exc:
                    raise TriggerError(f"config triggers.sources.{source}.{key} is not a valid regex: {exc}")
            patterns[source][key] = value
    return patterns


def first_date(text, year, base=None, cycles_pattern=None):
    """First date in free text: ISO, then M/D (assumed in ``year``), then 'N cycles later' from base."""
    m = _ISO.search(text)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = _MD.search(text)
    if m:
        try:
            return dt.date(year, int(m[1]), int(m[2]))
        except ValueError:
            pass
    if cycles_pattern and base:
        m = re.search(cycles_pattern, text)
        if m:
            return base + dt.timedelta(days=CYCLE_DAYS * int(m[1]))
    return None


def scan_experiments(path, year, patterns):
    """Registry table rows '| Xn | title | trigger | due | ... |' -> trigger specs."""
    specs = []
    if not os.path.isfile(path):
        return specs
    row_id = re.compile(patterns["row_id"])
    closed = re.compile(patterns["closed_status"])
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        if not row_id.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        xid, title, _trigger, due_text, _measure, status = cells[:6]
        if closed.search(status):
            continue
        date = first_date(due_text, year)
        if not date:
            continue
        specs.append({"id": f"exp-{xid}", "when": f"date:{date.isoformat()}",
                      "what": f"experiment {xid} is due: {title[:80]} (status: {status[:40]})",
                      "tier": "T0", "source": f"{os.path.relpath(path, ROOT)}:{n}"})
    return specs


def scan_decisions(path, year, patterns):
    """DR headings '### DR-nnn title (YYYY-MM-DD · status · ... <re-review marker>)' -> triggers."""
    specs = []
    if not os.path.isfile(path):
        return specs
    marker = patterns["rereview_marker"]
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        m = re.match(r"###\s+(DR-\d+)\s+(.+?)\s+\((.+)\)\s*$", line)
        if not m or marker not in m[3]:
            continue
        meta = m[3]
        base = None
        b = _ISO.search(meta)
        if b:
            try:
                base = dt.date(int(b[1]), int(b[2]), int(b[3]))
            except ValueError:
                base = None
        tail = meta.split("\u00b7")[-1]
        date = first_date(tail, year, base=base, cycles_pattern=patterns["cycles_later"])
        if not date:
            continue
        specs.append({"id": f"rereview-{m[1]}", "when": f"date:{date.isoformat()}",
                      "what": f"re-review {m[1]}: {m[2][:80]}",
                      "tier": "T0", "source": f"{os.path.relpath(path, ROOT)}:{n}"})
    return specs


def scan_specs(experiments, decisions, today, patterns=None):
    """Read the sources (no store access, no lock) and return the trigger specs they imply."""
    patterns = patterns or source_patterns()
    return (scan_experiments(experiments, today.year, patterns["experiments"])
            + scan_decisions(decisions, today.year, patterns["decisions"]))


def scan(rows, experiments, decisions, today, patterns=None, specs=None):
    added = []
    if specs is None:
        specs = scan_specs(experiments, decisions, today, patterns)
    for spec in specs:
        row, new = add(rows, spec["when"], spec["what"], spec["tier"], spec["source"],
                       trigger_id=spec["id"], today=today)
        if new:
            added.append(row)
    return added


# ---- CLI ----------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add"); p.add_argument("--when", required=True); p.add_argument("--what", required=True)
    p.add_argument("--tier", default="T1", choices=TIERS); p.add_argument("--source"); p.add_argument("--id")
    p.add_argument("--privacy", default="private", choices=PRIVACY)
    p.add_argument("--destination", default="local", choices=DESTINATIONS)
    p.add_argument("--date")
    p = sub.add_parser("due"); p.add_argument("--date"); p.add_argument("--limit", type=int, default=HOOK_LIMIT)
    p.add_argument("--mark", action="store_true", help="count the listed triggers as shown")
    p = sub.add_parser("hook"); p.add_argument("--date"); p.add_argument("--format", default="claude",
                                                                        choices=("claude", "text"))
    p = sub.add_parser("claim"); p.add_argument("id"); p.add_argument("--minutes", type=int, default=30)
    p.add_argument("--holder", default=None)
    p = sub.add_parser("fire"); p.add_argument("id"); p.add_argument("--outcome"); p.add_argument("--date")
    p.add_argument("--holder", default=None)
    p = sub.add_parser("sleep"); p.add_argument("id"); p.add_argument("--days", type=int, default=AUTO_SLEEP_DAYS)
    p.add_argument("--date")
    p = sub.add_parser("list"); p.add_argument("--all", action="store_true")
    p = sub.add_parser("scan"); p.add_argument("--experiments", default=DEFAULT_EXPERIMENTS)
    p.add_argument("--decisions", default=DEFAULT_DECISIONS); p.add_argument("--date")
    a = ap.parse_args(argv)
    read_only = a.cmd == "list" or (a.cmd == "due" and not a.mark)
    if (read_only or a.cmd == "hook") and not os.path.isfile(STORE):
        # No store yet (fresh instance, kit dev tree): say so without creating anything.
        if a.cmd == "due":
            print("due 0")
        elif a.cmd == "list":
            print("total 0")
        return 0
    try:
        specs = None
        if a.cmd == "scan":
            specs = scan_specs(a.experiments, a.decisions, _today(a.date))   # source reads outside the lock
        with _locked(exclusive=not read_only):
            rows = _load()
            if a.cmd == "add":
                row, new = add(rows, a.when, a.what, a.tier, a.source, a.id, _today(a.date),
                               privacy=a.privacy, destination=a.destination)
                _save(rows)
                print(f"{'added' if new else 'exists'} {row['id']}")
            elif a.cmd == "due":
                hits, changed = due(rows, _today(a.date), a.limit, mark=a.mark)
                if changed:
                    _save(rows)
                for row in hits:
                    print(format_line(row))
                print(f"due {len(hits)}")
            elif a.cmd == "hook":
                hits, changed = due(rows, _today(a.date), HOOK_LIMIT, mark=True)
                if changed:
                    _save(rows)
                if hits:
                    body = "[triggers due today]\n" + "\n".join(format_line(r) for r in hits) + \
                           "\nfire: python3 tools/triggers.py fire <id> --outcome '...' · sleep: ... sleep <id>\n"
                    if a.format == "text":
                        print(body)
                    else:
                        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                                 "additionalContext": body}}, ensure_ascii=False))
            elif a.cmd == "claim":
                row = claim(rows, a.id, a.minutes, a.holder or default_holder()); _save(rows)
                print(f"leased {row['id']} until {row['leased_until']} by {row['leased_by']}")
            elif a.cmd == "fire":
                row = fire(rows, a.id, a.outcome, _today(a.date), holder=a.holder or default_holder())
                _save(rows); print(f"fired {row['id']}")
            elif a.cmd == "sleep":
                row = sleep(rows, a.id, a.days, _today(a.date)); _save(rows)
                print(f"sleeping {row['id']} until {row['slept_until']}")
            elif a.cmd == "list":
                for row in rows:
                    if a.all or not row.get("fired"):
                        print(format_line(row) + (f" fired {row['fired']}" if row.get("fired") else ""))
                print(f"total {len(rows)}")
            elif a.cmd == "scan":
                added = scan(rows, a.experiments, a.decisions, _today(a.date), specs=specs); _save(rows)
                for row in added:
                    print("added " + format_line(row))
                print(f"scan added {len(added)} total {len(rows)}")
    except TriggerError as exc:
        print(f"triggers: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
