#!/usr/bin/env python3
"""Query the untracked fact ledger without embedding domain content in this tool.

Usage:
  python3 tools/rec.py hot                  Render the hotset, print it, and snapshot
  python3 tools/rec.py find QUERY           Search claims, text, tags, and speakers
      [--status=STATUS] [--tag=TAG] [--speaker=NAME] [--domain=DOMAIN] [--since=YYYY-MM-DD]
  python3 tools/rec.py show ID              Show one record
  python3 tools/rec.py audit ID             Follow provenance and verify paths
  python3 tools/rec.py check                Validate fields, links, limits, status, and supersession
  python3 tools/rec.py new ID [--claim= --status= --speaker= --tags=a,b --origin= --domain=]
  python3 tools/rec.py snapshot             Snapshot changes, retaining the latest 20

Search includes full text rather than relying only on tags. Speaker matching is partial so composite speaker fields are not silently missed. Scaffold TODOs remain check failures."""
import os, re, sys, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import STRINGS, t


def _resolve_root():
    """Follow MOTTORI_INSTANCE like memlib does, so a shared engine reads the active instance's ledger.

    memlib is not imported: it loads and validates the whole instance config, which this
    standalone ledger tool does not need.
    """
    env = os.environ.get("MOTTORI_INSTANCE")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _resolve_root()
LEDGER = os.path.join(ROOT, "_private/ledger")
FACTS = os.path.join(LEDGER, "facts")
HOTSET = os.path.join(LEDGER, "hotset.md")

HOT_CAP = 60  # PRD §11 D7
# Status values are data in record files. A record may carry the English or the Korean
# form; both map to one status key, so a ledger keeps working when the language changes.
REQUIRED = ["id", "claim", "status", "hot", "domain", "speaker", "date",
            "origin_kind", "origin"]
# Display statuses in order of violation risk.
ORDER = ["decided", "retracted", "confirmed", "inferred", "hearsay", "unresolved", "superseded"]


def status_key(value):
    """Return the status key for either language form of a status value, or None."""
    for key in ORDER:
        if value in STRINGS["rec.status." + key].values():
            return key
    return None


def _order_index(record):
    key = status_key(record["status"])
    return ORDER.index(key) if key else 9



def parse(path):
    text = open(path, encoding="utf-8").read()
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
                d[key] = [x.strip() for x in inner.split(",") if x.strip()]
            elif val == "":
                d[key] = []
            else:
                d[key] = val.strip('"')
        elif line.lstrip().startswith("- ") and key:
            if not isinstance(d.get(key), list):
                d[key] = []
            d[key].append(line.lstrip()[2:].strip())
    d["hot"] = str(d.get("hot", "")).lower() == "true"
    d["_body"] = body.strip()
    d["_path"] = path
    return d


def load():
    out = []
    for p in sorted(glob.glob(os.path.join(FACTS, "*.md"))):
        r = parse(p)
        if r:
            out.append(r)
    return out


def resolve(p):
    """Resolve ledger references as repository-relative or absolute file paths."""
    if os.path.isabs(p):
        return p
    return os.path.join(ROOT, p)


def exists(p):
    return os.path.exists(resolve(p))



def cmd_hot():
    recs = [r for r in load() if r["hot"]]
    lines = [
        t("rec.hot_title"),
        "",
        t("rec.hot_generated"),
        t("rec.hot_refresh"),
        t("rec.hot_rule"),
        t("rec.hot_count", count=len(recs), cap=HOT_CAP),
        "",
    ]
    if len(recs) > HOT_CAP:
        lines += [t("rec.hot_over_cap", count=len(recs), cap=HOT_CAP), ""]
    lines.append("---")
    for st in ORDER:
        group = [r for r in recs if status_key(r["status"]) == st]
        if not group:
            continue
        title = t("rec.hot_head." + st)
        note = t("rec.hot_note." + st) if "rec.hot_note." + st in STRINGS else ""
        lines += ["", f"## {title}", ""]
        if note:
            lines += [f"> {note}", ""]
        lines += [t("rec.hot_table_head"), "|---|---|---|---|"]
        for r in sorted(group, key=lambda x: x["id"]):
            claim = r["claim"].replace("|", "\\|")
            lines.append(f"| {claim} | {r['speaker']} | {r['date']} | `{r['id']}` |")
    lines += ["", "---", "", t("rec.hot_dig"), ""]
    os.makedirs(LEDGER, exist_ok=True)
    text = "\n".join(lines)
    open(HOTSET, "w", encoding="utf-8").write(text)
    # Print the content too: the command is the documented way to consult the hotset, and a
    # path alone forces a second read that is easy to skip.
    print(text)
    print(f"[hot] {len(recs)} records -> {os.path.relpath(HOTSET, ROOT)}")
    if len(recs) > HOT_CAP:
        print(f"[hot] WARNING over cap: {len(recs)}/{HOT_CAP}")


def cmd_find(args):
    filters, terms = {}, []
    for a in args:
        m = re.match(r"^--(\w+)=(.+)$", a)
        if m:
            filters[m.group(1)] = m.group(2)
        else:
            terms.append(a)
    recs = load()
    total = len(recs)
    for k, v in filters.items():
        if k == "since":
            recs = [r for r in recs if r.get("date", "") >= v]
        elif k == "tag":
            recs = [r for r in recs if v in r.get("tags", [])]
        elif k == "speaker":
            # Use partial matching so composite speaker fields are not silently excluded.
            recs = [r for r in recs if v in r.get("speaker", "")]
        else:
            recs = [r for r in recs if r.get(k) == v]
    if terms:
        def hit(r):
            hay = " ".join([r.get("claim", ""), r.get("_body", ""), r.get("id", ""),
                            r.get("speaker", ""), " ".join(r.get("tags", []))]).lower()
            return all(t.lower() in hay for t in terms)
        recs = [r for r in recs if hit(r)]
    if not recs:
        # Lexical containment over this ledger only: a miss is bounded by that scope and wording.
        shown = " ".join(f"--{k}={v}" for k, v in filters.items())
        scope = t("rec.find_scope", total=total, facts=os.path.relpath(FACTS, ROOT),
                  filters=f" ({shown})" if shown else "")
        print(t("rec.find_zero", scope=scope))
        return 0
    print(f"[find] {len(recs)} hit(s)\n")
    for r in sorted(recs, key=lambda x: (_order_index(x), x["id"])):
        flag = "🔥" if r["hot"] else "  "
        print(f"{flag} [{r['status']}] {r['claim']}")
        print(f"     {r['speaker']} · {r['date']} · `{r['id']}`")
    return 0


def cmd_show(rid):
    p = os.path.join(FACTS, rid + ".md")
    if not os.path.exists(p):
        print(t("rec.no_record", cmd="show", rid=rid))
        return 1
    print(open(p, encoding="utf-8").read())
    return 0


def cmd_audit(rid):
    p = os.path.join(FACTS, rid + ".md")
    if not os.path.exists(p):
        print(t("rec.no_record", cmd="audit", rid=rid))
        return 1
    r = parse(p)
    gap = r.get("origin_gap", "")
    print(t("rec.audit_claim", value=r['claim']))
    print(t("rec.audit_status", status=r['status'], speaker=r['speaker'], date=r['date']))
    print(t("rec.audit_record", path=os.path.relpath(p, ROOT)))
    print()
    print(t("rec.audit_chain"))
    chain = r.get("via") or [r["origin"]]
    for i, step in enumerate(chain):
        mark = "✓" if exists(step) else t("rec.audit_missing_mark")
        if i == 0:
            # A derived reference does not become an original when the origin is missing.
            arrow = t("rec.audit_origin_arrow") if not gap else t("rec.audit_best_arrow")
        else:
            arrow = "   ↓   "
        print(f"{arrow} [{mark}] {step}")
    print(t("rec.audit_this_record", path=os.path.relpath(p, ROOT)))
    print()
    print(t("rec.audit_origin_kind", kind=r.get('origin_kind', '—')))
    if gap:
        print(t("rec.audit_gap", gap=gap))
        print(t("rec.audit_gap_note"))
    else:
        print(t("rec.audit_no_gap"))
    return 0


def cmd_check():
    recs = load()
    ids = {r["id"] for r in recs}
    problems = []
    for r in recs:
        rid = r.get("id", os.path.basename(r["_path"]))
        for f in REQUIRED:
            if f not in r or r[f] in ("", None):
                problems.append(t("rec.problem_missing_field", rid=rid, field=f))
        status = status_key(r.get("status"))
        if status is None:
            problems.append(t("rec.problem_unknown_status", rid=rid, status=r.get('status')))
        if r["id"] != os.path.basename(r["_path"])[:-3]:
            problems.append(t("rec.problem_id_mismatch", rid=rid))
        for step in (r.get("via") or []) + [r.get("origin", "")]:
            if step and not exists(step):
                problems.append(t("rec.problem_missing_path", rid=rid, path=step))
        for link in re.findall(r"\[\[([^\]]+)\]\]", r.get("_body", "")):
            if link not in ids:
                problems.append(t("rec.problem_broken_link", rid=rid, link=link))
        # Supersession and withdrawal references must resolve.
        for fld in ("supersedes", "superseded_by"):
            val = r.get(fld)
            if val:
                for target in (val if isinstance(val, list) else [val]):
                    if target not in ids:
                        problems.append(t("rec.problem_missing_target", rid=rid, field=fld, target=target))
        # Superseded records need an explicit replacement link.
        if status == "superseded" and not r.get("superseded_by"):
            problems.append(t("rec.problem_superseded_without_link", rid=rid, status=r.get("status")))
    hot = sum(1 for r in recs if r["hot"])
    if hot > HOT_CAP:
        problems.append(t("rec.problem_hot_over_cap", count=hot, cap=HOT_CAP))
    dup = [i for i in ids if sum(1 for r in recs if r["id"] == i) > 1]
    for d in set(dup):
        problems.append(t("rec.problem_duplicate_id", rid=d))

    print(t("rec.check_counts", count=len(recs), hot=hot, cap=HOT_CAP))
    from collections import Counter
    print(t("rec.check_statuses"), dict(Counter(r["status"] for r in recs)))
    for p in problems:
        print("PROBLEM " + p)
    print(t("rec.check_trailer", count=len(problems)))
    return 1 if problems else 0


def ledger_hash():
    """Hash ledger content to avoid duplicate snapshots."""
    import hashlib
    h = hashlib.sha256()
    paths = sorted(glob.glob(os.path.join(FACTS, "*.md")))
    paths.append(os.path.join(LEDGER, "_telemetry.md"))
    for p in paths:
        if os.path.exists(p):
            h.update(os.path.basename(p).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


def cmd_snapshot(quiet=False):
    """Snapshot the untracked ledger only when content changes, retaining the newest 20 snapshots. hot invokes this automatically; it is not a per-turn task."""
    import shutil, datetime
    snaps = os.path.join(LEDGER, ".snapshots")
    os.makedirs(snaps, exist_ok=True)
    hfile = os.path.join(snaps, "LATEST")
    cur = ledger_hash()
    if os.path.exists(hfile) and open(hfile).read().strip() == cur:
        if not quiet:
            print(t("rec.snapshot_unchanged"))
        return 0
    name = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S") + "-" + cur[:8]
    dst = os.path.join(snaps, name)
    os.makedirs(dst)
    shutil.copytree(FACTS, os.path.join(dst, "facts"))
    for extra in ("_telemetry.md", "_verification-20q.md", "README.md"):
        src = os.path.join(LEDGER, extra)
        if os.path.exists(src):
            shutil.copy2(src, dst)
    open(hfile, "w").write(cur)
    dirs = sorted(d for d in os.listdir(snaps) if os.path.isdir(os.path.join(snaps, d)))
    for old in dirs[:-20]:
        shutil.rmtree(os.path.join(snaps, old))
    n = len(glob.glob(os.path.join(dst, "facts", "*.md")))
    print(t("rec.snapshot_done", name=name, count=n, ring=min(len(dirs), 20)))
    return 0


def cmd_new(args):
    import datetime
    if not args:
        print("usage: rec.py new <id> [--claim=..] [--status=..] [--speaker=..] [--tags=a,b] [--origin=..] [--domain=..] [--date=..]")
        return 1
    rid = args[0]
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", rid):
        print(t("rec.new_bad_id", rid=rid))
        return 1
    path = os.path.join(FACTS, rid + ".md")
    if os.path.exists(path):
        print(t("rec.new_exists", path=os.path.relpath(path, ROOT)))
        print(t("rec.new_transition"))
        return 1
    opts = {}
    for a in args[1:]:
        m = re.match(r"^--(\w+)=(.+)$", a)
        if m:
            opts[m.group(1)] = m.group(2)
    today = datetime.date.today().isoformat()
    origin = opts.get("origin", t("rec.todo_origin"))
    claim = opts.get("claim", t("rec.todo_claim"))
    os.makedirs(FACTS, exist_ok=True)
    # Leave unresolved fields as TODOs so check cannot accept an incomplete scaffold.
    lines = [
        "---",
        f"id: {rid}",
        f"claim: \"{claim}\"",
        f"status: {opts.get('status', t('rec.todo_status'))}",
        "hot: true",
        f"domain: {opts.get('domain', t('rec.todo_domain'))}",
        f"tags: [{opts.get('tags', t('rec.todo_tags'))}]",
        f"speaker: {opts.get('speaker', t('rec.todo_speaker'))}",
        f"date: {opts.get('date', today)}",
        f"recorded: {today}",
        f"origin_kind: {opts.get('origin_kind', t('rec.todo_origin_kind'))}",
        f"origin: {origin}",
        "origin_gap: \"\"",
        "via:",
        f"  - {origin}",
        "---",
        "",
        f"# {claim}",
        "",
        t("rec.new_evidence"),
        "",
        t("rec.new_scope"),
        "",
    ]
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[new] {os.path.relpath(path, ROOT)}")
    print(t("rec.new_next"))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "new":
        return cmd_new(rest)  # Allow creation of the first record when the ledger directory is absent.
    if not os.path.isdir(FACTS):
        print(t("rec.no_ledger", path=os.path.relpath(FACTS, ROOT)))
        return 1
    if cmd == "hot":
        cmd_snapshot(quiet=True)  # Snapshot content changes when rendering the hotset.
        return cmd_hot() or 0
    if cmd == "find":
        return cmd_find(rest)
    if cmd == "show":
        return cmd_show(rest[0]) if rest else 1
    if cmd == "audit":
        return cmd_audit(rest[0]) if rest else 1
    if cmd == "check":
        return cmd_check()
    if cmd == "snapshot":
        return cmd_snapshot()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
