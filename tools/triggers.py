#!/usr/bin/env python3
"""Store deferred actions (triggers) and show the due ones at session start.

Records live in the instance's _private/triggers/triggers.jsonl, one JSON object per line:
  id, when, what, tier, source, created, fired, outcome, shown, last_shown,
  slept_until, leased_until, leased_by, ignored, retired, history, sticky
A trigger's when is date:YYYY-MM-DD. Its state (open, asleep, leased, fired or retired) is read
from these dates by state(); it is not stored.

T0: notify. T1: prepare reversible private drafts. T2: outward actions require human
execution and are surfaced as a draft plus a question, never executed unattended. No tier
implies outward delivery.

Triggers come from add and from scan, which reads experiment due dates and decision re-review
dates. A command that writes takes the store's lock and replaces the file whole, so list and due
without --mark read without one. The rules of each step sit with its function: _load (unreadable lines), due
(showing, sleeping, retiring, sticky rows), add and scan (reopening), claim (leases), _store_lock
(waiting for the lock).

Usage:
  triggers.py add --when date:YYYY-MM-DD --what "..." [--tier T1] [--source file:line] [--id ID] [--sticky]
  triggers.py due [--date YYYY-MM-DD] [--limit 5] [--mark]
  triggers.py hook [--date YYYY-MM-DD] [--format claude|text]
  triggers.py claim ID --holder NAME [--minutes 30]
  triggers.py fire ID [--outcome TEXT] [--holder NAME]
  triggers.py sleep ID [--days 7]
  triggers.py list [--all]
  triggers.py scan [--experiments FILE] [--decisions FILE] [--date YYYY-MM-DD]"""
import argparse
import contextlib
import datetime as dt
import functools
import hashlib
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C  # noqa: E402
import hook_input  # noqa: E402
import paths as P  # noqa: E402
import safeio  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
BAD_JSON = "not a JSON object"
BUSY = (
    "the trigger store is busy (another process holds its lock); run python3 tools/triggers.py "
    "due to see what is due"
)
CORRUPT_STORE = (
    "corrupt trigger store {path}: cannot read line(s) {lines} (line {first}: {reason}). "
    "Repairing or removing those lines restores add, fire and the other commands that write."
)
DUE_COUNT = "due {count}"
ERR_CYCLES_COUNT = (
    "the cycles_later pattern caught {value}, not a number of cycles; make its group catch "
    "digits, such as (\\d+)"
)
ERR_FIRED = "trigger {id} already fired on {date}"
ERR_LEASED = "trigger {id} is leased by {holder} until {until}"
HOOK_HINT = (
    "fire: python3 tools/triggers.py fire <id> --outcome '...' · sleep: python3 "
    "tools/triggers.py sleep <id>"
)
LIST_TOTAL = "total {count}"
RETIRED_NOTE = "{count} reminder(s) retired after being ignored; list --all shows them"
SKIPPED_NOTE = "{count} unreadable trigger row(s) skipped"

ROOT = P.instance_root()
STORE = P.triggers_store(ROOT)
STORE_DIR = os.path.dirname(STORE)

# Source parsers are data, not code: the instance config may override these patterns under
# ``triggers.sources`` (for example a Korean registry uses its own words for "closed" and
# "re-review"). Engine defaults are English so the kit tree stays language-clean.
DEFAULT_SOURCE_PATTERNS = {
    "experiments": {"row_id": r"\|\s*X\d+\s*\|", "closed_status": r"closed|done|withdrawn|retired"},
    "decisions": {"rereview_marker": "re-review", "cycles_later": r"(\d+)\s*cycles?\s*later"},
}

TIERS = ("T0", "T1", "T2")
TIER_LABEL = {"T0": "say", "T1": "prepare", "T2": "ask (outward action, never unattended)"}
WHEN_KINDS = ("date",)
HOOK_LIMIT = 5            # most triggers surfaced per session start
HOOK_LOCK_SECONDS = 1.0   # session start waits no longer than this for a busy store
WRITER_NOTICE_SECONDS = 3.0   # other writers wait without limit and say so after this long
HOOK_FIELD_CHARS = 200    # the hook shortens a longer what, source or lease holder; nothing else caps them
IGNORE_LIMIT = 3          # shown this many times without fire -> auto sleep
AUTO_SLEEP_DAYS = 7
CYCLE_DAYS = 7            # "N cycles later" in a decision record means N weekly cycles
RETIRE_AFTER_SLEEPS = 2   # a row ignored through this many auto-sleeps is retired, not slept again
MD_ROLLOVER_DAYS = 180    # an M/D date more than this before its reference date is in a later year
MD_LAST_YEAR_DAYS = 90    # an M/D date of the previous year at most this before its reference date is overdue
SCAN_PREFIXES = ("exp-", "rereview-")   # id prefixes scan gives the rows it makes
# add and scan return status words that code compares; these are their printed lines.
STATUS_LINE = {"added": "added {id}", "exists": "exists {id}", "reopened": "reopened {id}"}
SCAN_EVENT_LINE = {"moved": "moved {id} {when}", "reopened": "reopened {id} {when}",
                   "closed": "closed {id} {when}"}


def default_holder():
    return os.environ.get("MOTTORI_ACTOR") or f"{os.environ.get('USER', 'user')}@{os.uname().nodename}"


def _utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


class TriggerError(ValueError):
    pass


def _today(value=None):
    if value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            raise TriggerError(f"--date needs a real date as YYYY-MM-DD, got {repr(value)}")
    return dt.date.today()


def _load():
    """Return (rows, unreadable lines as (line number, reason)).

    A line is unreadable when it is not JSON or fails _check_row. Commands that write refuse while
    one exists; hook, due and list go on without those lines and say how many, so one damaged line
    cannot hide every reminder, but they then mark nothing as shown and never rewrite the store."""
    if not os.path.isfile(STORE):
        return [], []
    rows, bad = [], []
    for n, raw in enumerate(open(STORE, "rb"), 1):
        try:
            # Decoding per line keeps one non-UTF-8 line from failing the whole read.
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            row = json.loads(line)
        except ValueError:
            bad.append((n, BAD_JSON))
            continue
        try:
            _check_row(row)
            # Rows written before state was derived carry a state field; the next save drops it.
            row.pop("state", None)
            rows.append(row)
        except ValueError as exc:
            bad.append((n, str(exc)))
    return rows, bad


def hook_preview(today=None):
    """Return the text `triggers.py hook` would print now, without marking a reminder as shown or
    taking the store's lock; "" without a store."""
    if not os.path.isfile(STORE):
        return ""
    rows, bad = _load()
    hits = due(rows, today or _today(), HOOK_LIMIT, mark=False)[0]
    return hook_body(hits, len(bad), 0, _corrupt(bad) if bad else None)


def _corrupt(bad):
    """The refusal for a store with unreadable lines: where they are and how to get writes back."""
    lines = ", ".join(str(n) for n, _ in bad[:10]) + (", ..." if len(bad) > 10 else "")
    return CORRUPT_STORE.format(path=STORE, lines=lines, first=bad[0][0], reason=bad[0][1])


def _check_row(row):
    """Raise ValueError naming the first field the commands display, sort or change but could not use.

    A row with such a field counts as an unreadable line, like one that is not JSON, so it cannot
    make the session-start hook or a command stop with a traceback."""
    if not isinstance(row, dict):
        raise ValueError(BAD_JSON)
    def bad(key):
        # Only the field name: parse_when's message quotes the stored value, and the hook injects this.
        return ValueError(f"field {key}")
    for key in ("id", "when", "what"):
        if not isinstance(row.get(key), str):
            raise bad(key)
    if row.get("tier") not in TIERS:
        raise bad("tier")
    try:
        parse_when(row["when"])
    except TriggerError:
        raise bad("when")
    if not isinstance(row.get("source") or "", str):   # scan splits it at the last colon
        raise bad("source")
    for key in ("shown", "ignored"):
        if type(row.get(key, 0)) is not int:
            raise bad(key)
    if not isinstance(row.get("history", []), list):
        raise bad("history")
    for key in ("created", "slept_until", "fired", "retired", "last_shown", "leased_until"):
        value = row.get(key)
        if value is None and key != "created":
            continue
        try:
            (dt.datetime if key == "leased_until" else dt.date).fromisoformat(value)
        except (TypeError, ValueError):
            raise bad(key)


def _save(rows):
    os.makedirs(STORE_DIR, exist_ok=True)
    try:
        os.chmod(STORE_DIR, 0o700)
    except OSError:
        pass
    safeio.atomic_write(STORE, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    try:
        os.chmod(STORE, 0o600)
    except OSError:
        pass


def parse_when(value):
    if ":" not in value:
        raise TriggerError(f"when must be <kind>:<value>, got {repr(value)}")
    kind, rest = value.split(":", 1)
    if kind not in WHEN_KINDS:
        raise TriggerError("unknown when kind {kind} (allowed: {allowed})".format(kind=repr(kind), allowed=", ".join(WHEN_KINDS)))
    try:
        dt.date.fromisoformat(rest)
    except ValueError:
        raise TriggerError(f"date trigger needs YYYY-MM-DD, got {repr(rest)}")
    return kind, rest


def make_id(when, what, source):
    digest = hashlib.sha256(f"{when}\n{what}\n{source or ''}".encode("utf-8")).hexdigest()[:10]
    return f"tr-{digest}"


def _event(row, kind, today, note=None):
    row.setdefault("history", []).append({"at": (today or dt.date.today()).isoformat(), "event": kind,
                                          **({"note": note} if note else {})})


def _one_line(text):
    # The hook injects one line per trigger; a stored line break would split it.
    return " ".join(str(text).split())


def _reopen(row, when, today):
    """Open a fired or retired row again at ``when`` if that date is later than its closing date.

    A producer with a fixed id (a recurring failure alarm, a re-dated source) re-adds it while the
    condition holds; without this the first fire or retirement would silence it for good. A row
    scan closed because its source stopped listing it ("source closed") reopens whenever it is
    listed again: a missing config or a half-written file must not end a reminder.
    """
    closed = row.get("fired") or row.get("retired")
    if not closed:
        return False
    if row.get("outcome") != "source closed":
        if when == row["when"]:
            return False
        if dt.date.fromisoformat(parse_when(when)[1]) <= dt.date.fromisoformat(closed):
            return False
    row.update({"when": when, "fired": None, "outcome": None, "retired": None, "shown": 0, "ignored": 0, "slept_until": None, "leased_until": None,
                "leased_by": None})
    _event(row, "reopened", today, when)
    return True


def add(rows, when, what, tier="T1", source=None, trigger_id=None, today=None, sticky=False):
    """Append a trigger, or return the existing one with the same id.

    Returns (row, status) with status "added", "exists" or "reopened". sticky marks an existing
    row too, so an item already in the store can be pinned.
    """
    parse_when(when)
    if tier not in TIERS:
        raise TriggerError("tier must be one of {tiers}".format(tiers=", ".join(TIERS)))
    if not what or not what.strip():
        raise TriggerError("what must not be empty")
    trigger_id = trigger_id or make_id(when, what, source)
    for row in rows:
        if row["id"] == trigger_id:
            if sticky and not row.get("sticky"):
                row["sticky"] = True
                _event(row, "sticky", today)
            return row, ("reopened" if _reopen(row, when, today) else "exists")
    row = {"id": trigger_id, "when": when, "what": _one_line(what), "tier": tier, "source": source,
           "created": (today or dt.date.today()).isoformat(), "fired": None,
           "outcome": None, "shown": 0, "slept_until": None, "leased_until": None, "history": []}
    if sticky:
        row["sticky"] = True
    _event(row, "added", today)
    rows.append(row)
    return row, "added"


def state(row, today=None, now=None):
    """A row's state, read from its fields: fired, retired, leased (a live lease), asleep (slept
    until a later day than today) or open."""
    if row.get("fired"):
        return "fired"
    if row.get("retired"):
        return "retired"
    if _live_lease(row, now or _utcnow()):
        return "leased"
    slept = row.get("slept_until")
    if slept and dt.date.fromisoformat(slept) > (today or dt.date.today()):
        return "asleep"
    return "open"


def _is_due(row, today):
    if state(row, today) in ("fired", "retired", "asleep"):
        return False
    return dt.date.fromisoformat(parse_when(row["when"])[1]) <= today


def _new_day(row, today):
    last = row.get("last_shown")
    return not last or dt.date.fromisoformat(last) < today


def due(rows, today, limit=HOOK_LIMIT, mark=True):
    """Return due date triggers: sticky first, then least shown (carry-over), then oldest. When
    sticky rows alone would fill ``limit``, the last place goes to the least-shown ordinary row.

    With ``mark`` a returned row counts as shown, and a row already shown IGNORE_LIMIT times without
    being fired is put to sleep for AUTO_SLEEP_DAYS (its ``ignored`` counter grows). Without ``mark``
    nothing is written: such rows are only left out of the listing.

    A row counts as shown only on a day later than the last day it was counted. The SessionStart hook
    also runs on resume, /clear, and compaction, so counting every run would put a trigger to sleep
    within one working day although the owner has seen it only once; and a clock set back to an
    earlier day must not count that day again. A sticky row is counted but never put to sleep.

    A row that would be put to sleep after RETIRE_AFTER_SLEEPS earlier sleeps is retired instead
    (with ``mark``), so a reminder nobody acts on ends.

    Returns (rows, changed, retired): retired counts the rows this call retired. The rows must have
    passed _check_row, which _load applies.
    """
    if limit < 0:
        raise TriggerError("--limit must be 0 or more")
    retired = 0
    keyed = [((not r.get("sticky"), r.get("shown", 0), r["when"], r["created"], r["what"], r["id"]), r)
             for r in rows if _is_due(r, today)]
    # carry-over: least shown first, so a cap never starves the items behind it
    keyed.sort(key=lambda kr: kr[0])
    hits = [r for _key, r in keyed]
    out, changed = [], False
    for row in hits:
        if row.get("shown", 0) >= IGNORE_LIMIT and _new_day(row, today) and not row.get("sticky"):
            if mark and row.get("ignored", 0) >= RETIRE_AFTER_SLEEPS:
                row["retired"] = today.isoformat()
                row["shown"] = 0
                _event(row, "retired", today, f"ignored through {RETIRE_AFTER_SLEEPS} sleeps")
                retired += 1
                changed = True
            elif mark:
                row["slept_until"] = (today + dt.timedelta(days=AUTO_SLEEP_DAYS)).isoformat()
                row["ignored"] = row.get("ignored", 0) + 1
                row["shown"] = 0
                _event(row, "auto-sleep", today, f"shown {IGNORE_LIMIT} times without fire")
                changed = True
            continue
        out.append(row)
    plain = next((r for r in out if not r.get("sticky")), None)
    if plain and limit > 1 and plain not in out[:limit]:
        # Sticky rows never sleep, so a full set of them would hide every ordinary row for good.
        out = out[:limit - 1] + [plain]
    else:
        out = out[:limit]
    if mark:
        for row in out:
            if not _new_day(row, today):
                continue
            row["shown"] = row.get("shown", 0) + 1
            row["last_shown"] = today.isoformat()
            changed = True
    return out, changed, retired


def format_line(row, width=None):
    """One display line. ``width`` shortens what, source and a lease holder (never the id) and then says so."""
    def cut(text):
        text = _one_line(text)
        return text[:width] + "..." if width and len(text) > width else text
    what, source = cut(row["what"]), row.get("source") and cut(row["source"])
    tier = row["tier"]
    head = f"- [{tier} {TIER_LABEL[tier]}] {what}"
    note = "; sticky" if row.get("sticky") else ""
    holder = _live_lease(row, _utcnow())
    if holder and holder != default_holder():
        # Only a loop claims, under its own name; a session that sees this leaves the row to it.
        note += f"; being handled by {cut(holder)}"
    tail = (" ({when}; source {source}; id {id}{sticky})".format(when=row["when"], source=source, id=row["id"], sticky=note)
            if source else " ({when}; id {id}{sticky})".format(when=row["when"], id=row["id"], sticky=note))
    if tier == "T2":
        head += " -> draft only; the owner performs the outward action"
    if (what != _one_line(row["what"]) or (source and source != _one_line(row["source"]))
            or (holder and cut(holder) != _one_line(holder))):
        tail += " (shortened; python3 tools/triggers.py list shows the whole row)"
    return head + tail


def hook_body(hits, skipped=0, retired=0, blocked=None):
    """The text the session-start hook injects; context_budget measures this same text.

    ``blocked`` is the refusal fire and sleep would give; it replaces the hint to run them."""
    lines = []
    if hits:
        lines.append("[triggers due today]")
        lines += [format_line(r, HOOK_FIELD_CHARS) for r in hits]
        if not blocked:
            lines.append(HOOK_HINT)
    if retired:
        lines.append(RETIRED_NOTE.format(count=retired))
    if skipped:
        lines.append(SKIPPED_NOTE.format(count=skipped))
    if blocked:
        lines.append(blocked)
    return "\n".join(lines) + "\n" if lines else ""


def _print_hook(body, form):
    if not body:
        return
    if form == "text":
        print(body)
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": body}},
                         ensure_ascii=False))


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


def _refuse_closed_or_leased(row, holder, now):
    """Refuse a fired or a retired row, and a live lease held by anyone but holder."""
    if row.get("fired"):
        raise TriggerError(ERR_FIRED.format(id=row["id"], date=row["fired"]))
    if row.get("retired"):
        raise TriggerError("trigger {id} was retired on {date}".format(id=row["id"], date=row["retired"]))
    lessee = _live_lease(row, now)
    if lessee and lessee != holder:
        raise TriggerError(ERR_LEASED.format(id=row["id"], holder=lessee, until=row["leased_until"]))


def claim(rows, trigger_id, minutes, holder, now=None):
    """Lease a trigger before acting on it, for minutes from now (UTC).

    Leases are optional: an instance's own loop that names its holder calls this (the kit ships
    none), and hook and due then show the row as being handled to everyone else."""
    row = _find(rows, trigger_id)
    now = now or _utcnow()
    _refuse_closed_or_leased(row, holder, now)
    row["leased_until"] = (now + dt.timedelta(minutes=minutes)).isoformat()
    row["leased_by"] = holder
    # History dates are local calendar days like every other event; the lease itself stays UTC.
    _event(row, "claimed", now.astimezone().date(), f"{holder} {minutes} min")
    return row


def fire(rows, trigger_id, outcome=None, today=None, holder=None, now=None):
    """Mark a trigger done.

    A person fires without claiming: on one machine every session has the same default holder,
    so a required lease guarded nothing and only made a plain fire fail.
    """
    row = _find(rows, trigger_id)
    _refuse_closed_or_leased(row, holder, now or _utcnow())
    row["fired"] = (today or dt.date.today()).isoformat()
    row["outcome"] = outcome
    row["leased_until"] = None
    row["leased_by"] = None
    _event(row, "fired", today, f"{holder}: {outcome}" if holder else outcome)
    return row


def sleep(rows, trigger_id, days, today=None, holder=None, now=None):
    """Hide a trigger for days. A sticky row leaves the list only this way or by fire."""
    row = _find(rows, trigger_id)
    # Sleeping a row a loop is handling would hide it from that loop's next pass.
    _refuse_closed_or_leased(row, holder or default_holder(), now or _utcnow())
    row["slept_until"] = ((today or dt.date.today()) + dt.timedelta(days=days)).isoformat()
    row["shown"] = 0
    _event(row, "sleep", today, f"{days} days")
    return row


# ---- sources -----------------------------------------------------------------------------------

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MD = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")


def source_patterns(config_path=None):
    """Engine defaults overlaid with ``triggers.sources`` from the instance config, if present.

    Values must be non-empty strings; the regex-valued keys must compile, and cycles_later must
    capture the count. A malformed override is a TriggerError naming the key, never a stack trace
    from a scan."""
    try:
        override = C.trigger_sources(config_path)
    except ValueError as error:
        raise TriggerError(str(error))
    if not isinstance(override, dict):
        raise TriggerError("config triggers.sources must be an object")
    patterns = {k: dict(v) for k, v in DEFAULT_SOURCE_PATTERNS.items()}
    for source, values in override.items():
        if source not in patterns:
            continue
        if not isinstance(values, dict):
            raise TriggerError(f"config triggers.sources.{source} must be an object")
        for key, value in values.items():
            _check_source_pattern(f"triggers.sources.{source}.{key}", key, value, patterns[source])
            patterns[source][key] = value
    return patterns


def _check_source_pattern(name, key, value, known):
    if key not in known or not (isinstance(value, str) and value):
        raise TriggerError(f"config {name} must be a non-empty string")
    if key == "rereview_marker":
        return  # plain text, found as written
    try:
        compiled = re.compile(value)
    except re.error as exc:
        raise TriggerError(f"config {name} is not a valid regex: {exc}")
    if key == "cycles_later" and not compiled.groups:
        # The scan reads the count from group 1.
        raise TriggerError(f"config {name} needs a capture group for the count, such as (\\d+)")


def _md_years(month, day, start):
    # Several years are tried because 2/29 exists only in leap years.
    for year in range(start, start + 5):
        try:
            yield dt.date(year, month, day)
        except ValueError:
            pass


def md_on_or_after(month, day, after):
    """First occurrence on or after ``after``: a decision's re-review never comes before the decision."""
    return next((d for d in _md_years(month, day, after.year) if d >= after), None)


def md_near(month, day, ref):
    """In the year of ``ref``, or a later year when it would lie more than MD_ROLLOVER_DAYS before
    ``ref`` (a January date written in December means next January). A date of the previous year
    at most MD_LAST_YEAR_DAYS before ``ref`` wins: a December date first read in January is overdue,
    not due next December. That window is shorter than a year's half because a registry is mostly
    written ahead: in May, 11/30 still means the coming November."""
    try:
        last_year = dt.date(ref.year - 1, month, day)
    except ValueError:
        last_year = None
    if last_year and (ref - last_year).days <= MD_LAST_YEAR_DAYS:
        return last_year
    return next((d for d in _md_years(month, day, ref.year) if (ref - d).days <= MD_ROLLOVER_DAYS), None)


def first_date(text, md_rule, base=None, cycles_pattern=None):
    """First date in free text: ISO, then M/D read by ``md_rule(month, day)``, then 'N cycles
    later' from base."""
    m = _ISO.search(text)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    m = _MD.search(text)
    if m:
        date = md_rule(int(m[1]), int(m[2]))
        if date:
            return date
    if cycles_pattern and base:
        m = re.search(cycles_pattern, text)
        if m:
            try:
                cycles = int(m[1])
            except (TypeError, ValueError):
                # A configured pattern whose group caught a word, nothing, or no group at all.
                raise TriggerError(ERR_CYCLES_COUNT.format(value=repr(m[1])))
            return base + dt.timedelta(days=CYCLE_DAYS * cycles)
    return None


def scan_experiments(path, patterns, today):
    """Registry table rows '| Xn | title | trigger | due | ... |' -> trigger specs."""
    specs = []
    if not path or not os.path.isfile(path):
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
        date = first_date(due_text, functools.partial(md_near, ref=today))
        if not date:
            continue
        # An ISO date is written out in the cell; any other date's year was guessed from today.
        specs.append({"id": f"exp-{xid}", "when": f"date:{date.isoformat()}",
                      "what": f"experiment {xid} is due: {title[:80]} (status: {status[:40]})",
                      "tier": "T0", "source": f"{os.path.relpath(path, ROOT)}:{n}",
                      "year_guessed": date.isoformat() not in due_text})
    return specs


def scan_decisions(path, patterns, today):
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
        # The date belongs to the segment that carries the marker; other segments may hold the
        # base date, later notes, or ratios like 5/5 that would read as a month/day.
        parts = meta.split("\u00b7")
        if len(parts) > 1:
            tail = next(p for p in parts if marker in p)
        else:
            tail = _ISO.sub("", meta, count=1)
        md_rule = (functools.partial(md_on_or_after, after=base) if base
                   else functools.partial(md_near, ref=today))
        date = first_date(tail, md_rule, base=base, cycles_pattern=patterns["cycles_later"])
        if not date:
            continue
        specs.append({"id": f"rereview-{m[1]}", "when": f"date:{date.isoformat()}",
                      "what": f"re-review {m[1]}: {m[2][:80]}",
                      "tier": "T0", "source": f"{os.path.relpath(path, ROOT)}:{n}",
                      "year_guessed": base is None})
    return specs


def scan_specs(experiments, decisions, today, patterns=None):
    """Read the sources (no store access, no lock) and return the trigger specs they imply."""
    patterns = patterns or source_patterns()
    # A source listing one id twice would move that row back and forth on every scan; the first wins.
    unique = {}
    for spec in (scan_experiments(experiments, patterns["experiments"], today)
                 + scan_decisions(decisions, patterns["decisions"], today)):
        unique.setdefault(spec["id"], spec)
    return list(unique.values())


def scan(rows, experiments, decisions, today, patterns=None, specs=None, changes=None):
    """Add the triggers the sources imply and follow edits to the rows scan owns.

    A row with a listed id that another source made (a hand-added row) is left alone. An open row
    whose source date changed moves to the new date; a fired or retired row whose source now gives
    a later date, or that scan closed itself, reopens (see _reopen); an open exp-/rereview- row that
    scan made (source "<file>:<line>") is closed when that file exists but no longer lists it. A
    stored row keeps its year when the source gives the same month and day with a year guessed
    from the scan date.
    ``changes``, when given, receives (event, row) pairs.
    Returns the added rows.
    """
    added = []
    changes = changes if changes is not None else []
    if specs is None:
        specs = scan_specs(experiments, decisions, today, patterns)
    for spec in specs:
        existing = next((r for r in rows if r["id"] == spec["id"]), None)
        if existing:
            if (existing.get("source") or "").rpartition(":")[0] != spec["source"].rpartition(":")[0]:
                # Another source (a hand-added row) owns this id: scan changes nothing in it.
                continue
            # Scan made this row from the same file, so the current line is its text.
            existing.update({k: spec[k] for k in ("what", "tier", "source")})
        if (existing and spec.get("year_guessed") and existing["when"].startswith("date:")
                and existing["when"][-5:] == spec["when"][-5:]):
            # The year of an M/D date without a base follows the scan date; the stored row already
            # fixed it, so a later scan must not move or reopen the row by a year.
            spec = dict(spec, when=existing["when"])
        if (existing and not existing.get("fired") and not existing.get("retired")
                and existing["when"] != spec["when"]):
            existing.update({"when": spec["when"], "shown": 0, "ignored": 0, "slept_until": None})
            _event(existing, "moved", today, spec["when"])
            changes.append(("moved", existing))
            continue
        row, status = add(rows, spec["when"], spec["what"], spec["tier"], spec["source"],
                          trigger_id=spec["id"], today=today)
        if status == "added":
            added.append(row)
        elif status == "reopened":
            changes.append(("reopened", row))
    # Close only rows scan itself made from a file it actually read (source "<file>:<line>"):
    # a missing file says nothing, and hand-added rows may share the id prefix.
    owned = {prefix: re.compile(re.escape(os.path.relpath(path, ROOT)) + r":\d+$")
             for prefix, path in (("exp-", experiments), ("rereview-", decisions))
             if path and os.path.isfile(path)}
    listed = {s["id"] for s in specs}
    for row in rows:
        prefix = next((p for p in SCAN_PREFIXES if row["id"].startswith(p)), None)
        if (prefix in owned and owned[prefix].match(row.get("source") or "")
                and row["id"] not in listed and not row.get("fired")
                and not row.get("retired")):
            row.update({"fired": today.isoformat(), "outcome": "source closed",
                        "leased_until": None, "leased_by": None})
            _event(row, "fired", today, "source closed")
            changes.append(("closed", row))
    return added


# ---- CLI ----------------------------------------------------------------------------------------

@contextlib.contextmanager
def _writer_lock():
    """Wait for the store lock as long as it takes, saying so once the wait is noticeable.

    A writer that gave up would leave its caller (a person or a loop that does not retry) with a
    lost add or fire; a silent wait would look like a hang."""
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(safeio.locked(STORE + ".lock", timeout=WRITER_NOTICE_SECONDS))
        except safeio.StateLockTimeout:
            print("triggers: waiting for the trigger store: another process holds its lock. This command "
                  "goes on when it is free", file=sys.stderr, flush=True)
            stack.enter_context(safeio.locked(STORE + ".lock", timeout=float("inf")))
        yield


def build_parser():
    ap = argparse.ArgumentParser(description=(
        "Dated deferred triggers shown at session start (stored in _private/triggers/triggers.jsonl)."
    ))
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="{add,list,due,sleep,fire,scan,claim,hook}")
    p = sub.add_parser("add", help="add a trigger (--when date:YYYY-MM-DD --what \"...\")")
    p.add_argument("--when", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--tier", default="T1", choices=TIERS)
    p.add_argument("--source")
    p.add_argument("--id")
    p.add_argument("--date")
    p.add_argument("--sticky", action="store_true", help="never auto-sleep; listed before other triggers")
    p = sub.add_parser("due", help="show the triggers due today")
    p.add_argument("--date")
    p.add_argument("--limit", type=int, default=HOOK_LIMIT)
    p.add_argument("--mark", action="store_true", help="count the listed triggers as shown")
    p = sub.add_parser("hook", help="print due triggers for session start (used by programs)")
    p.add_argument("--date")
    p.add_argument("--format", default="claude", choices=("claude", "text"))
    p = sub.add_parser("claim", help="lease a trigger for an automated runner (used by programs)")
    p.add_argument("id")
    p.add_argument("--minutes", type=int, default=30)
    # Required: every session of one person shares the default holder, so a lease under it coordinates nothing.
    p.add_argument("--holder", required=True)
    p = sub.add_parser("fire", help="mark a trigger done by its id")
    p.add_argument("id")
    p.add_argument("--outcome")
    p.add_argument("--date")
    p.add_argument("--holder", default=None)
    p = sub.add_parser("sleep", help="snooze a trigger by its id (--days N)")
    p.add_argument("id")
    p.add_argument("--days", type=int, default=AUTO_SLEEP_DAYS)
    p.add_argument("--date")
    p = sub.add_parser("list", help="list open triggers (--all includes closed ones)")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("scan", help="add re-review dates from decisions and experiments")
    p.add_argument("--experiments", help="the experiments table (default: triggers.experiments in the config)")
    p.add_argument("--decisions", default=P.decisions())
    p.add_argument("--date")
    return ap


def _cmd_add(a, rows, bad):
    row, status = add(rows, a.when, a.what, a.tier, a.source, a.id, _today(a.date), sticky=a.sticky)
    _save(rows)
    print(STATUS_LINE[status].format(id=row["id"]))


def _cmd_due(a, rows, bad):
    # A store whose lines were dropped is never rewritten, so nothing is marked either: a
    # retirement that cannot be saved would be announced again on every run.
    hits, changed, retired = due(rows, _today(a.date), a.limit, mark=a.mark and not bad)
    if changed:
        _save(rows)
    for row in hits:
        print(format_line(row))
    if retired:
        print(RETIRED_NOTE.format(count=retired))
    if bad:
        print(SKIPPED_NOTE.format(count=len(bad)))
    print(DUE_COUNT.format(count=len(hits)))


def _cmd_hook(a, rows, bad):
    hits, changed, retired = due(rows, _today(a.date), HOOK_LIMIT, mark=not bad)   # as in due
    if changed:
        _save(rows)
    _print_hook(hook_body(hits, len(bad), retired, _corrupt(bad) if bad else None), a.format)


def _cmd_claim(a, rows, bad):
    row = claim(rows, a.id, a.minutes, a.holder)
    _save(rows)
    print("leased {id} until {until} by {holder}".format(id=row["id"], until=row["leased_until"], holder=row["leased_by"]))


def _cmd_fire(a, rows, bad):
    row = fire(rows, a.id, a.outcome, _today(a.date), holder=a.holder or default_holder())
    _save(rows)
    print("fired {id}".format(id=row["id"]))


def _cmd_sleep(a, rows, bad):
    row = sleep(rows, a.id, a.days, _today(a.date))
    _save(rows)
    print("sleeping {id} until {until}".format(id=row["id"], until=row["slept_until"]))


def _cmd_list(a, rows, bad):
    shown = 0
    for row in rows:
        if a.all or not (row.get("fired") or row.get("retired")):
            shown += 1
            print(format_line(row) + (" fired {date}".format(date=row["fired"]) if row.get("fired") else "")
                  + (" retired {date}".format(date=row["retired"]) if row.get("retired") else ""))
    if bad:
        print(SKIPPED_NOTE.format(count=len(bad)))
    hidden = len(rows) - shown
    print(f"total {shown} ({hidden} fired or retired hidden; list --all shows them)" if hidden
          else LIST_TOTAL.format(count=shown))


def _cmd_scan(a, rows, bad):
    changes = []
    added = scan(rows, a.experiments, a.decisions, _today(a.date), specs=a.specs, changes=changes)
    _save(rows)
    for row in added:
        print(f"added {format_line(row)}")
    for event, row in changes:
        print(SCAN_EVENT_LINE[event].format(id=row["id"], when=row["when"]))
    print(f"scan added {len(added)} total {len(rows)}")


COMMANDS = {"add": _cmd_add, "due": _cmd_due, "hook": _cmd_hook, "claim": _cmd_claim,
            "fire": _cmd_fire, "sleep": _cmd_sleep, "list": _cmd_list, "scan": _cmd_scan}
# Commands that go on past unreadable lines; every other command refuses to write over them.
READERS = ("hook", "due", "list")


def _store_lock(a, read_only):
    """No lock for a reader, since saves replace the store whole; a bounded wait for the hook,
    which session start must not hold up; an unbounded one for every other writer."""
    if read_only:
        return contextlib.nullcontext()
    if a.cmd == "hook":
        return safeio.locked(STORE + ".lock", timeout=HOOK_LOCK_SECONDS)
    return _writer_lock()


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "scan" and not a.experiments:
        a.experiments = C.triggers_experiments()
    if a.cmd == "hook" and hook_input.probe():
        # Nobody reads a probe's output, so no reminder may count as shown; the canary's prompt
        # to a model provider must not carry the owner's reminders either.
        return 0
    read_only = a.cmd == "list" or (a.cmd == "due" and not a.mark)
    if (read_only or a.cmd == "hook") and not os.path.isfile(STORE):
        # No store yet (fresh instance, kit dev tree): say so without creating anything.
        if a.cmd == "due":
            print(DUE_COUNT.format(count=0))
        elif a.cmd == "list":
            print(LIST_TOTAL.format(count=0))
        return 0
    try:
        # The sources are read outside the lock.
        a.specs = scan_specs(a.experiments, a.decisions, _today(a.date)) if a.cmd == "scan" else None
        with _store_lock(a, read_only):
            rows, bad = _load()
            if bad and a.cmd not in READERS:
                raise TriggerError(_corrupt(bad))
            COMMANDS[a.cmd](a, rows, bad)
    except safeio.StateLockTimeout:
        # Only the hook has a bound. Session start must not wait on a stuck holder; nothing was
        # read, so nothing is counted.
        _print_hook(BUSY + "\n", a.format)
    except TriggerError as exc:
        print(f"triggers: {exc}", file=sys.stderr)
        return 2
    except OverflowError:
        # A huge --days, --minutes or "N cycles later" count lands past the last date Python has.
        print("triggers: a date or count is out of range", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
