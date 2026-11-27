#!/usr/bin/env python3
"""Query the untracked fact ledger without embedding domain content in this tool.

Usage:
  python3 tools/facts.py hot                Render the hotset, print it, and snapshot
  python3 tools/facts.py find QUERY         Search claims, text, tags, and speakers
      [--status=STATUS] [--tag=TAG] [--speaker=NAME] [--domain=DOMAIN] [--since=YYYY-MM-DD]
  python3 tools/facts.py show ID            Show one record
  python3 tools/facts.py audit ID           Follow provenance and verify paths
  python3 tools/facts.py check              Validate fields, links, limits, status, and supersession
  python3 tools/facts.py new ID [--claim= --status= --speaker= --tags=a,b --origin= --origin_kind= --domain= --date=]
  python3 tools/facts.py snapshot           Snapshot changes, retaining the latest 20

Search includes full text rather than relying only on tags. Speaker matching is partial so composite speaker fields are not silently missed. Scaffold TODOs remain check failures."""
import collections
import datetime
import glob
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C  # noqa: E402
import paths as P  # noqa: E402
import safeio  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
AUDIT_GAP_NOTE = (
    "    The origin is lost; the step marked best-avail is the **best source still "
    "available**. When quoting it verbatim, state the limit of its grade."
)
AUDIT_MISSING_MARK = "✗ missing"
AUDIT_ORIGIN_MISSING = (
    "⚠️  origin gap: not declared, but the origin file is missing; fix origin or fill "
    "origin_gap"
)
FIND_ZERO = (
    "[find] 0 hits in the searched scope: {scope}. Not found here is not proof of absence; do "
    "not fill the gap by guessing (system/specs/PRD-info-architecture.md#retrieval). Try other words "
    "or another form of the word."
)
HOT_DIG = (
    "**To dig deeper**: `python3 tools/facts.py show <id>` · `python3 tools/facts.py audit <id>` "
    "(the chain back to the origin)"
)
HOT_GENERATED = (
    "> **Generated file. Do not edit it.** The source of truth is the atomic notes in "
    "`_private/ledger/facts/`."
)
HOT_TABLE_HEAD = "| Fact | Source | Date | id |"
NEW_BAD_VALUE = (
    "[new] --{field} must be UTF-8 text without a double quote or a newline; use single quotes "
    "or corner brackets"
)
NEW_EVIDENCE = (
    "**Evidence**: (quote verbatim when possible. If the origin is lost, say so in origin_gap)"
)
NEW_ORIGIN_MISSING = (
    "[new] WARNING origin is not an existing file, so `facts.py check` will report it: {path}. "
    "Give the path of the file that holds the evidence, relative to the repository root"
)
NEW_TRANSITION = (
    "[new] Change an existing record by a status transition, not an edit (README: "
    "superseded/retracted + supersedes)"
)
NO_RECORD = "[{cmd}] no such record: {rid}"
PROBLEM_UNPARSABLE = (
    "{path}: front matter cannot be read; this record is invisible to every command"
)
REC_UNPARSED = (
    "[{cmd}] WARNING {count} fact file(s) could not be read and are missing above; see `facts.py "
    "check`"
)
SNAPSHOT_UNCHANGED = "[snapshot] unchanged; skipped"


ROOT = P.instance_root()
LEDGER = P.ledger(ROOT)
FACTS = P.ledger_facts(ROOT)
HOTSET = P.ledger_hotset(ROOT)

# system/specs/PRD-info-architecture.md requires a hotset cap and demotion conditions; the value 60
# itself has no recorded source.
HOT_CAP = 60
REQUIRED = ["id", "claim", "status", "hot", "domain", "speaker", "date",
            "origin_kind", "origin"]
# Display statuses in order of violation risk.
ORDER = ["decided", "retracted", "confirmed", "inferred", "hearsay", "unresolved", "superseded"]
# Fields read as lists; a single scalar value is wrapped so callers can iterate safely.
LIST_FIELDS = ("tags", "via", "supersedes")
# The filters find accepts, each written --NAME=VALUE.
FIND_FILTERS = ("status", "tag", "speaker", "domain", "since")
USAGE_FIND = ("usage: facts.py find QUERY [--status=STATUS] [--tag=TAG] [--speaker=NAME] "
              "[--domain=DOMAIN] [--since=YYYY-MM-DD]")
NEW_KEYS = ("claim", "status", "speaker", "tags", "origin", "origin_kind", "domain", "date")
# Fields every command treats as one string; a bracket or dash list here is a malformed record.
TEXT_FIELDS = ("id", "claim", "status", "speaker", "date", "origin", "domain", "origin_kind")

# Status values are data in record files. A record may carry the English or the Korean form;
# status_key maps both to one status key, so a ledger keeps working when the language changes.
STATUS_KOREAN = {
    "decided": "\uacb0\uc815\ub428",
    "retracted": "\ucca0\ud68c\ub428",
    "confirmed": "\ud655\uc815",
    "inferred": "\ucd94\ub860",
    "hearsay": "\uc804\uc5b8",
    "unresolved": "\ubbf8\ud574\uacb0",
    "superseded": "\ub300\uccb4\ub428",
}
# Hotset section heading and the note under it, by status.
HOT_HEAD = {
    "decided": "A. Decided: do not propose again",
    "retracted": "B. Retracted: do not repeat",
    "confirmed": "C. Confirmed: checked against the origin",
    "inferred": "D. Inferred: not an observation",
    "hearsay": "E. Hearsay",
    "unresolved": "F. Unresolved: say it is unknown",
    "superseded": "G. Superseded",
}
HOT_HEAD_UNKNOWN = "H. Unknown status: fix the status (see `facts.py check`)"
HOT_NOTE = {
    "decided": "Proposing this item again is a bug (re-proposing a decided item).",
    "retracted": "Stating this claim again is a bug (restating a retracted claim).",
    "inferred": "Do not quote it as a fact (an inference is not a confirmed fact).",
    "unresolved": "Do not fill it by guessing (system/specs/PRD-info-architecture.md#retrieval).",
}
# Placeholders `facts.py new` writes into a scaffold; check fails on one left in a record.
TODO_ORIGIN = "TODO-origin-path"
TODO_CLAIM = "TODO-one-sentence-claim"
TODO_STATUS = "TODO-status"
TODO_DOMAIN = "TODO-domain"
TODO_TAGS = "TODO-tags"
TODO_SPEAKER = "TODO-speaker"
TODO_ORIGIN_KIND = "TODO-audio|transcript|transcript-derived|message|document|session-utterance"
TODOS = {TODO_ORIGIN, TODO_CLAIM, TODO_STATUS, TODO_DOMAIN, TODO_TAGS, TODO_SPEAKER, TODO_ORIGIN_KIND}


def status_key(value):
    """Return the status key for a status value in English or Korean, or None."""
    for key in ORDER:
        if value in (key, STATUS_KOREAN[key]):
            return key
    return None


def _order_index(record):
    key = status_key(record.get("status"))
    return ORDER.index(key) if key else 9



def _unquote(val):
    # YAML allows either quote style around a scalar.
    return val[1:-1] if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"" else val


def parse(path):
    try:
        text = open(path, encoding="utf-8").read()
    except UnicodeDecodeError:
        # Reported as unparsable by check and audit instead of crashing them.
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm, body = text[3:end], text[end + 4:]
    d, key = {}, None
    for line in fm.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                d[key] = [_unquote(x.strip()) for x in inner.split(",") if x.strip()]
            else:
                d[key] = _unquote(val)
            if key in LIST_FIELDS and not isinstance(d[key], list):
                d[key] = [d[key]] if d[key] else []
        elif line.lstrip().startswith("- ") and key:
            if not isinstance(d.get(key), list):
                d[key] = []
            d[key].append(_unquote(line.lstrip()[2:].strip()))
    d["_body"] = body.strip()
    d["_path"] = path
    return d


# Fact files whose front matter could not be read; check reports them so they are not
# silently invisible to every command.
UNPARSED = []


def is_hot(record):
    """Projection default: anything but an accepted true spelling stays out; check reports the rest."""
    return str(record.get("hot", "")).lower() == "true"


def load():
    out = []
    del UNPARSED[:]
    for p in sorted(glob.glob(os.path.join(FACTS, "*.md"))):
        r = parse(p)
        if r:
            out.append(r)
        else:
            UNPARSED.append(p)
    return out


def resolve(p):
    """Resolve ledger references as repository-relative or absolute file paths."""
    if os.path.isabs(p):
        return p
    return os.path.join(ROOT, p)


def exists(p):
    # Evidence is a file; a directory such as "." would otherwise pass as present.
    return os.path.isfile(resolve(p))



def _hot_rows(group):
    rows = []
    # str() because a list id would make sorted() compare a list with a string.
    for r in sorted(group, key=lambda x: str(x.get("id", ""))):
        claim = str(r.get("claim", "")).replace("|", "\\|")
        rows.append(f"| {claim} | {r.get('speaker', '')} | {r.get('date', '')} | `{r.get('id', '')}` |")
    return rows


def cmd_hot():
    recs = [r for r in load() if is_hot(r)]
    lines = [
        "# Hotset: read on demand via `facts.py hot`",
        "",
        HOT_GENERATED,
        "> Refresh: edit the records, then run `python3 tools/facts.py hot` again.",
        "> **Rule**: read this before asserting a fact or proposing an action.",
        f"> {len(recs)} record(s) / cap {HOT_CAP}",
        "",
    ]
    if len(recs) > HOT_CAP:
        lines += [f"> ⚠️ **Over cap ({len(recs)}/{HOT_CAP})**: demote items whose phase has ended to cold.", ""]
    lines.append("---")
    for st in ORDER:
        group = [r for r in recs if status_key(r.get("status")) == st]
        if not group:
            continue
        title = HOT_HEAD[st]
        note = HOT_NOTE.get(st, "")
        lines += ["", f"## {title}", ""]
        if note:
            lines += [f"> {note}", ""]
        lines += [HOT_TABLE_HEAD, "|---|---|---|---|"]
        lines += _hot_rows(group)
    # A hot record with an unknown status is counted in the header, so it must also be shown.
    unknown = [r for r in recs if status_key(r.get("status")) is None]
    if unknown:
        lines += ["", f"## {HOT_HEAD_UNKNOWN}", ""]
        lines += [HOT_TABLE_HEAD, "|---|---|---|---|"]
        lines += _hot_rows(unknown)
    lines += ["", "---", "", HOT_DIG, ""]
    os.makedirs(LEDGER, exist_ok=True)
    text = "\n".join(lines)
    # Another session may be reading the hotset while this one renders it.
    safeio.atomic_write(HOTSET, text)
    # Print the content too: the command is the documented way to consult the hotset, and a
    # path alone forces a second read that is easy to skip.
    print(text)
    # The over-cap warning is already in the text printed above (facts.hot_over_cap).
    print(f"[hot] {len(recs)} record(s) -> {os.path.relpath(HOTSET, ROOT)}")
    if UNPARSED:
        # An unreadable hot record would otherwise vanish from the hotset without a trace.
        print(REC_UNPARSED.format(cmd="hot", count=len(UNPARSED)))


def cmd_find(args):
    filters, terms = {}, []
    for a in args:
        if a.startswith("--"):
            m = re.match(r"^--(\w+)=(.+)$", a)
            if not m or m.group(1) not in FIND_FILTERS:
                # An unknown filter, or "--status decided" read as two words, would otherwise match
                # nothing and look like an empty result.
                print(USAGE_FIND)
                return 1
            filters[m.group(1)] = m.group(2)
        else:
            terms.append(a)
    recs = load()
    total = len(recs)
    for k, v in filters.items():
        if k == "since":
            # A list date reads as "[..." and sorts after every digit, so it is kept, not hidden.
            recs = [r for r in recs if str(r.get("date", "")) >= v]
        elif k == "tag":
            recs = [r for r in recs if v in r.get("tags", [])]
        elif k == "speaker":
            # Use partial matching so composite speaker fields are not silently excluded.
            recs = [r for r in recs if v in str(r.get("speaker", ""))]
        elif k == "status":
            # Records may store either language form of a status.
            want = status_key(v) or v
            recs = [r for r in recs if (status_key(r.get("status")) or r.get("status")) == want]
        else:
            recs = [r for r in recs if r.get(k) == v]
    if terms:
        def hit(r):
            # str() because a bracket or dash list in claim or speaker parses as a list.
            hay = " ".join(str(x) for x in [r.get("claim", ""), r.get("_body", ""), r.get("id", ""),
                                            r.get("speaker", ""), " ".join(r.get("tags", []))]).lower()
            return all(t.lower() in hay for t in terms)
        recs = [r for r in recs if hit(r)]
    if not recs:
        # Lexical containment over this ledger only: a miss is bounded by that scope and wording.
        shown = " ".join(f"--{k}={v}" for k, v in filters.items())
        scope = "{total} record(s) under {facts} (claim, body, id, speaker, tags){filters}".format(total=total, facts=os.path.relpath(FACTS, ROOT), filters=f" ({shown})" if shown else "")
        print(FIND_ZERO.format(scope=scope))
    else:
        print(f"[find] {len(recs)} hit(s)" + "\n")
        for r in sorted(recs, key=lambda x: (_order_index(x), str(x.get("id", "")))):
            flag = "🔥" if is_hot(r) else "  "
            print(f"{flag} [{r.get('status', '')}] {r.get('claim', '')}")
            print(f"     {r.get('speaker', '')} · {r.get('date', '')} · `{r.get('id', '')}`")
    if UNPARSED:
        # An unreadable record was not searched, so a miss above is not a miss in the ledger.
        print(REC_UNPARSED.format(cmd="find", count=len(UNPARSED)))
    return 0


def cmd_show(rid):
    p = os.path.join(FACTS, rid + ".md")
    if not os.path.exists(p):
        print(NO_RECORD.format(cmd="show", rid=rid))
        return 1
    try:
        print(open(p, encoding="utf-8").read())
    except UnicodeDecodeError:
        print(PROBLEM_UNPARSABLE.format(path=os.path.relpath(p, ROOT)))
        return 1
    return 0


def cmd_audit(rid):
    p = os.path.join(FACTS, rid + ".md")
    if not os.path.exists(p):
        print(NO_RECORD.format(cmd="audit", rid=rid))
        return 1
    r = parse(p)
    if r is None:
        print(PROBLEM_UNPARSABLE.format(path=os.path.relpath(p, ROOT)))
        return 1
    gap = r.get("origin_gap", "")
    origin = r.get("origin", "")
    # The declared origin is checked itself, so an existing derived step cannot stand in for it.
    origin_ok = isinstance(origin, str) and bool(origin) and exists(origin)
    print("claim  : {value}".format(value=r.get("claim", "")))
    print("status : {status}   speaker: {speaker}   date: {date}".format(status=r.get("status", ""), speaker=r.get("speaker", ""), date=r.get("date", "")))
    print(f"record : {os.path.relpath(p, ROOT)}")
    print()
    print("Audit chain (origin -> derived):")
    missing = AUDIT_MISSING_MARK
    print(f"  origin [{'✓' if origin_ok else missing}] {origin}")
    # new writes origin as the first via step too; it is shown once, above.
    derived = [s for s in (r.get("via") or []) if s != origin]
    for i, step in enumerate(derived):
        # With a declared gap the first derived step is the best source still available.
        arrow = "best-avail" if gap and i == 0 else "   ↓   "
        mark = "✓" if isinstance(step, str) and step and exists(step) else missing
        print(f"{arrow} [{mark}] {step}")
    print(f"   ↓    [✓] {os.path.relpath(p, ROOT)}  ← this record")
    print()
    print("origin kind: {kind}".format(kind=r.get("origin_kind") or AUDIT_MISSING_MARK))
    if gap:
        print(f"⚠️  origin gap: {gap}")
        print(AUDIT_GAP_NOTE)
    elif not origin_ok:
        print(AUDIT_ORIGIN_MISSING)
    else:
        print("origin gap: none (the origin file exists)")
    return 0


def _record_id(r):
    """The id a problem names: the record's own, or its file name when the id is unusable."""
    rid = r.get("id")
    return rid if isinstance(rid, str) and rid else os.path.basename(r["_path"])


def _field_problems(rid, r):
    """Problems of one record's own fields: missing, left as a scaffold TODO, or malformed."""
    problems = []
    for f in REQUIRED:
        if f not in r or r[f] in ("", None, []):
            problems.append(f"{rid}: required field missing `{f}`")
    for f, val in r.items():
        # Scaffold placeholders written by new fail like a missing field.
        if not f.startswith("_") and any(v in TODOS for v in (val if isinstance(val, list) else [val])):
            problems.append(f"{rid}: `{f}` still holds the TODO placeholder written by `facts.py new`")
    for f in TEXT_FIELDS:
        if not isinstance(r.get(f, ""), str):
            problems.append(f"{rid}: `{f}` must be one plain value, not a list")
    # An empty value is already reported as a missing field.
    if r.get("hot") not in ("", None, []) and str(r["hot"]).lower() not in ("true", "false"):
        problems.append("{rid}: `hot` must be true or false, not `{value}`".format(rid=rid, value=r["hot"]))
    # A list or a scaffold placeholder is already reported above.
    if (status_key(r.get("status")) is None and isinstance(r.get("status", ""), str)
            and r.get("status") not in TODOS):
        problems.append("{rid}: unknown status `{status}`".format(rid=rid, status=r.get('status')))
    date = r.get("date")
    if isinstance(date, str) and date and date not in TODOS and not C.is_day(date):
        problems.append(f"{rid}: `date` must be a real YYYY-MM-DD date, not `{date}`")
    if r.get("id", "") != os.path.basename(r["_path"])[:-3]:
        problems.append(f"{rid}: id does not match the file name")
    return problems


def _link_problems(rid, r, ids):
    """Problems of what one record points to: evidence files, links and supersession."""
    problems = []
    # new writes origin as the first via step too; one missing file is one problem.
    steps = [x for x in (r.get("via") or []) + [r.get("origin", "")]
             if x and isinstance(x, str) and x not in TODOS]
    for step in dict.fromkeys(steps):
        if not exists(step):
            problems.append(f"{rid}: path missing → {step}")
    for link in re.findall(r"\[\[([^\]]+)\]\]", r.get("_body", "")):
        if link not in ids:
            problems.append(f"{rid}: broken link → [[{link}]]")
    # Supersession and withdrawal references must resolve.
    for fld in ("supersedes", "superseded_by"):
        val = r.get(fld)
        for target in (val if isinstance(val, list) else [val]) if val else ():
            if target == r.get("id"):
                problems.append(f"{rid}: {fld} points to the record itself")
            elif target not in ids:
                problems.append(f"{rid}: {fld} target missing → {target}")
    if status_key(r.get("status")) == "superseded":
        # Superseded records need an explicit replacement link.
        if not r.get("superseded_by"):
            problems.append("{rid}: status `{status}` requires `superseded_by`".format(rid=rid, status=r.get("status")))
        # A replaced claim in the hotset would be read as current.
        if is_hot(r):
            problems.append(f"{rid}: a superseded record must not be hot; set `hot: false`")
    return problems


def cmd_check():
    recs = load()
    ids = {r.get("id") for r in recs if isinstance(r.get("id"), str) and r.get("id")}
    problems = [PROBLEM_UNPARSABLE.format(path=os.path.relpath(p, ROOT)) for p in UNPARSED]
    for r in recs:
        rid = _record_id(r)
        problems += _field_problems(rid, r) + _link_problems(rid, r, ids)
    hot = sum(1 for r in recs if is_hot(r))
    if hot > HOT_CAP:
        problems.append(f"hotset over cap: {hot}/{HOT_CAP} (demote items whose phase has ended)")
    dup = [i for i in ids if sum(1 for r in recs if r.get("id") == i) > 1]
    for d in set(dup):
        problems.append(f"duplicate id: {d}")

    print(f"[check] {len(recs)} record(s) · hot {hot}/{HOT_CAP}")
    print("[check] statuses:", dict(collections.Counter(str(r.get("status", "")) for r in recs)))
    for p in problems:
        print("PROBLEM " + p)
    print(f"[check] problems: {len(problems)}")
    return 1 if problems else 0


def ledger_hash(base=None):
    """Hash ledger content to avoid duplicate snapshots; base is the ledger or a snapshot copy."""
    import hashlib
    base = base or LEDGER
    h = hashlib.sha256()
    paths = sorted(glob.glob(os.path.join(base, "facts", "*.md")))
    # The side files a snapshot copies (config ledger.snapshot_extras) are hashed too, so an edit
    # to one of them is not skipped as "unchanged".
    paths += [os.path.join(base, extra) for extra in C.ledger_snapshot_extras()]
    for p in paths:
        if os.path.exists(p):
            h.update(os.path.basename(p).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


def cmd_snapshot(quiet=False):
    """Snapshot the untracked ledger only when content changes, retaining the newest 20 snapshots. hot invokes this automatically; it is not a per-turn task."""
    import shutil, tempfile, time
    snaps = os.path.join(LEDGER, ".snapshots")
    os.makedirs(snaps, exist_ok=True)
    hfile = os.path.join(snaps, "LATEST")
    latest = open(hfile).read().strip() if os.path.exists(hfile) else ""
    if ledger_hash() == latest:
        if not quiet:
            print(SNAPSHOT_UNCHANGED)
        return 0
    # The copy is hashed, not the source, so an edit during copying cannot label one version's
    # bytes with another's hash; a hidden staging name keeps a partial copy out of the ring.
    stage = tempfile.mkdtemp(prefix=".stage-", dir=snaps)
    try:
        shutil.copytree(FACTS, os.path.join(stage, "facts"))
        for extra in C.ledger_snapshot_extras():
            src = os.path.join(LEDGER, extra)
            if os.path.exists(src):
                shutil.copy2(src, stage)
        cur = ledger_hash(stage)
        if cur == latest:
            if not quiet:
                print(SNAPSHOT_UNCHANGED)
            return 0
        name = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S") + "-" + cur[:8]
        dst = os.path.join(snaps, name)
        try:
            os.rename(stage, dst)
        except OSError:
            if not os.path.isdir(dst):
                raise
            # Another session published the same content in the same second.
            return 0
        safeio.atomic_write(hfile, cur)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    dirs = sorted(d for d in os.listdir(snaps)
                  if not d.startswith(".") and os.path.isdir(os.path.join(snaps, d)))
    for old in dirs[:-20]:
        # A concurrent run may be pruning the same old snapshot.
        shutil.rmtree(os.path.join(snaps, old), ignore_errors=True)
    for d in os.listdir(snaps):
        stale = os.path.join(snaps, d)
        try:
            # A run killed mid-copy leaves its stage behind; no live copy takes a day.
            if d.startswith(".stage-") and os.path.getmtime(stale) < time.time() - 86400:
                shutil.rmtree(stale, ignore_errors=True)
        except OSError:
            pass  # another run removed it first
    n = len(glob.glob(os.path.join(dst, "facts", "*.md")))
    print(f"[snapshot] {name} ({n} fact(s), ring {min(len(dirs), 20)}/20)")
    return 0


USAGE_NEW = ("usage: facts.py new <id> [--claim=..] [--status=..] [--speaker=..] [--tags=a,b] "
             "[--origin=..] [--origin_kind=..] [--domain=..] [--date=..]")


def _new_options(args):
    """Return the --key=value options of `new` as a dict, or None after printing why not."""
    opts = {}
    for a in args:
        m = re.match(r"^--(\w+)=(.+)$", a, re.S)
        if not m or m.group(1) not in NEW_KEYS:
            # A silently dropped argument would leave a TODO the caller believes was filled.
            print(USAGE_NEW)
            return None
        try:
            m.group(2).encode("utf-8")
            encodable = True
        except UnicodeEncodeError:
            # A shell byte that is not UTF-8 arrives as a lone surrogate and cannot be written.
            encodable = False
        if not encodable or '"' in m.group(2) or m.group(2).splitlines() != [m.group(2)]:
            # Values are written unescaped into front matter; a quote or any line break that
            # str.splitlines honours (CR, U+2028 and others, trailing ones too) would cut them.
            print(NEW_BAD_VALUE.format(field=m.group(1)))
            return None
        opts[m.group(1)] = m.group(2)
    return opts


def _scaffold(rid, opts, today):
    """The text of a new record; unresolved fields stay TODOs so check cannot accept it."""
    origin = opts.get("origin", TODO_ORIGIN)
    claim = opts.get("claim", TODO_CLAIM)
    lines = [
        "---",
        f"id: {rid}",
        f"claim: \"{claim}\"",
        f"status: {opts.get('status', TODO_STATUS)}",
        # A replaced claim must stay out of the hotset, which check enforces.
        f"hot: {'false' if status_key(opts.get('status')) == 'superseded' else 'true'}",
        f"domain: {opts.get('domain', TODO_DOMAIN)}",
        f"tags: [{opts.get('tags', TODO_TAGS)}]",
        f"speaker: {opts.get('speaker', TODO_SPEAKER)}",
        f"date: {opts.get('date', today)}",
        f"recorded: {today}",
        f"origin_kind: {opts.get('origin_kind', TODO_ORIGIN_KIND)}",
        f"origin: {origin}",
        "origin_gap: \"\"",
        "via:",
        f"  - {origin}",
        "---",
        "",
        f"# {claim}",
        "",
        NEW_EVIDENCE,
        "",
        "**Caveats/scope**: ",
        "",
    ]
    return "\n".join(lines)


def cmd_new(args):
    if not args:
        print(USAGE_NEW)
        return 1
    rid = args[0]
    # fullmatch: "$" also matches before a final newline, which would put a newline in the file name.
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", rid):
        print(f"[new] id must be kebab-case: {rid}")
        return 1
    opts = _new_options(args[1:])
    if opts is None:
        return 1
    if "origin" in opts and not exists(opts["origin"]):
        # check resolves origin as a file path; saying so now beats a bare doctor FAIL later.
        print(NEW_ORIGIN_MISSING.format(path=opts["origin"]))
    path = os.path.join(FACTS, rid + ".md")
    os.makedirs(FACTS, exist_ok=True)
    try:
        # Exclusive creation: a separate existence check would let two sessions creating the
        # same id both succeed, the later write silently replacing the earlier fact.
        with open(path, "x", encoding="utf-8") as f:
            f.write(_scaffold(rid, opts, datetime.date.today().isoformat()))
    except FileExistsError:
        print(f"[new] already exists: {os.path.relpath(path, ROOT)}")
        print(NEW_TRANSITION)
        return 1
    print(f"[new] {os.path.relpath(path, ROOT)}")
    if any(k not in opts for k in NEW_KEYS if k != "date"):  # date defaults to today, not a TODO
        print("[new] next: fill the TODOs → `facts.py check` → `facts.py hot`")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd in ("-h", "--help"):
        print(__doc__)
        return 0
    if cmd == "new":
        return cmd_new(rest)  # Allow creation of the first record when the ledger directory is absent.
    if not os.path.isdir(FACTS):
        if cmd == "check":
            # The ledger is optional; a check of nothing passes instead of reading as a failure.
            print(f"[check] no ledger yet: {os.path.relpath(FACTS, ROOT)} (facts.py new creates it)")
            return 0
        # Nothing recorded is an answer to a search, not a failure of it.
        print(f"[facts] no facts recorded yet (no ledger at {os.path.relpath(FACTS, ROOT)}); "
              "`python3 tools/facts.py new ID --claim=...` records the first")
        return 0 if cmd in ("find", "hot") else 1
    if cmd == "hot":
        try:
            cmd_snapshot(quiet=True)  # Snapshot content changes when rendering the hotset.
        except OSError as exc:
            # The snapshot is a side effect; the hotset must still render.
            print(f"[hot] WARNING snapshot failed: {exc}")
        return cmd_hot() or 0
    if cmd == "find":
        return cmd_find(rest)
    if cmd == "show":
        if not rest:
            print("usage: facts.py show <id>")
            return 1
        return cmd_show(rest[0])
    if cmd == "audit":
        if not rest:
            print("usage: facts.py audit <id>")
            return 1
        return cmd_audit(rest[0])
    if cmd == "check":
        return cmd_check()
    if cmd == "snapshot":
        return cmd_snapshot()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
