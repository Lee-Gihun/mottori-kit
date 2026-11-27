#!/usr/bin/env python3
"""The papers beat of the improvement loop: its stages in order, from the arXiv sweep to the applier.

Stages: backlog, weekly skip, sweep a window of arXiv (default 14 days), triage, pick at most
READ_PER_CYCLE score-3 papers not read in an earlier cycle into groups, fetch their full text, write
cards (three workers in parallel), record as read the papers a card names (READ_RECORD), write
proposals, an optional read-only digest, the collection record and REPORT.md, then judge and apply,
and REPORT.md drawn again at the end (tools/loop/lib/loop_report.py). A cycle that reached
loop.token_ceiling ends with the state loop_worker.CEILING, which is not a failure: nothing resumes it
until the owner raises the ceiling. A stage that fails
ends the cycle or is recorded, as each stage says; state.json names the stages that failed.
Resume skips the outputs that exist and retries the missing stages; a verified empty candidate set
is a legitimate noop; a failed digest is logged only. Each worker runs under PAPERS_WORKER_TIMEOUT
seconds (default loop_beat.WORKER_TIMEOUT). The collection's state stays apart from the applier's
outcome. A held lock skips the run. What the workers must write is defined here once
(CARDS_KEY, DIGEST_END, PROPOSAL_HEADING) and rendered into their prompts.

  bash tools/loop/papers_cycle.sh --force | --resume YYYY-MM-DD"""
import csv
import datetime
import glob
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import config as C  # noqa: E402
from loop_stores import PAPERS_BASE, PAPERS_HOME  # noqa: E402
from loop_beat import PROMPTS, WORKER_TIMEOUT, Beat, nonempty, render, write_json  # noqa: E402
from loop_common import clip, load_json, read, write  # noqa: E402
from loop_contracts import has_heading, json_block, json_blocks  # noqa: E402
import loop_report  # noqa: E402
import loop_sending  # noqa: E402
import loop_settings  # noqa: E402
import loop_sources  # noqa: E402
import loop_state  # noqa: E402
from loop_state import COLLECTION  # noqa: E402
import loop_worker  # noqa: E402

PDIR = PAPERS_HOME
LOG = f"{PDIR}/cycle.log"
STATE = f"{PDIR}/state.json"
CYCLES = PAPERS_BASE
GROUPS = "ABC"
# At most this many papers are read in full per cycle.
READ_PER_CYCLE = 8
# The ids of the papers a card named, each with the date of the cycle that read it.
READ_RECORD = f"{PDIR}/read.json"
# What the workers must write. A card worker's answer ends with a fenced JSON block whose CARDS_KEY
# holds the number of cards it wrote; the digest ends with a line that starts with DIGEST_END; each
# proposal in PROPOSALS.md has a heading line that starts with PROPOSAL_HEADING.
CARDS_KEY = "cards"
DIGEST_END = "RECEIPT: digest"
PROPOSAL_HEADING = "### "
# The form of an arXiv id the loop takes from the triage worker's answer: the current scheme, with an
# optional version. Only an id the sweep listed in candidates.tsv is taken; file names are built from it.
ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}(v\d+)?")
# The proposal prompt's friction evidence: what an added source that may send offers (its friction hook,
# tools/loop/sources/README.md), such as reports made from the owner's sessions; otherwise none.
NO_FRICTION = ("No friction evidence available: no report of your sessions is read. In each proposal's \"why now\", "
               "write `no friction evidence`. Do not choose an audit tool for the loop's own receipts or run records.")


class End(Exception):
    """Ends the cycle early with a status for its state file."""

    def __init__(self, status):
        super().__init__(status)
        self.status = status


class Cycle:
    def __init__(self, beat, date, force, resume):
        self.beat, self.date, self.force, self.resume = beat, date, force, resume
        self.dir = f"{CYCLES}/{date}-kit"
        self.since = self.until = self.window = ""
        self.ncand = self.ntop = self.ncards = 0
        self.props_ok = True

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def render(self, name, dst, group="", files=""):
        return render_prompt(f"{PROMPTS}/{name}.md", dst, self.dir, self.window, group, files)


def render_prompt(template, dst, cycle_dir, window="", group="", files=""):
    """Render a papers prompt template; return whether it was written."""
    allowed = loop_sending.allowed(C.egress_model_send())
    offered = [friction(".") for name, friction in loop_sources.each("friction") if name in allowed]
    values = {"DIR": cycle_dir, "WINDOW": window, "GROUP": group, "FILES": files,
              "CARDS_BLOCK": json_block({CARDS_KEY: 3}).strip(), "DIGEST_END": DIGEST_END,
              "PROPOSAL_HEADING": PROPOSAL_HEADING.strip(),
              "FRICTION": " ".join(f for f in offered if f) or NO_FRICTION}
    return render(template, dst, values)


def card_count(answer):
    """The number of cards a card worker's answer reports in its fenced JSON block, or 0."""
    counts = [v[CARDS_KEY] for v in json_blocks(answer) if isinstance(v, dict)
              and isinstance(v.get(CARDS_KEY), int) and not isinstance(v.get(CARDS_KEY), bool)]
    return counts[-1] if counts else 0


def set_state(status, fails):
    try:
        s = load_json(STATE)   # An unreadable state starts over.
        c = CURRENT
        s.update({"last_cycle": c.date, "last_dir": c.dir, "status": status, "fails": fails[:300],
                  "failed_stages": c.beat.failed_stages})
        write_json(STATE, s, ensure_ascii=False, indent=1)
        return True
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return False


def finish(c, status):
    """Record the collection's end and draw REPORT.md, print the run's last line, record the state and a
    failure line, release the lock, run the watchdog; return the exit status."""
    b = c.beat
    state = {"ok": "pending", "noop": "done"}.get(status, status)
    if not b.in_log(draw_report, c, state):
        b.log("REPORT could not be written")
    if os.path.isfile(c.path("REPORT.md")):
        print(f"papers {loop_report.end_line(c.dir)}")
    if not set_state(status, b.failures):
        b.log("state write FAILED")
    if status == "failed":
        b.journal(clip(f"papers cycle failed: {c.date} ({c.dir}, log {LOG}). {b.failures}", 280),
                  "NOW failure receipt FAILED")
    b.release_lock()
    b.watchdog()
    if status == "failed":
        b.log(f"done: FAILED cycle {c.date} (exit 1): {b.failures}")
        return 1
    b.log(f"done cycle {c.date} ({status})")
    return 0


def weekly_skip(c):
    """Whether a scheduled run comes within seven days of the last cycle."""
    last = "" if c.force else str(load_json(STATE).get("last_cycle", ""))
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(last)).days
    except ValueError:   # No last cycle, or not a date.
        return False
    if 0 <= age < 7:
        c.beat.log(f"skip: last cycle {last} ({age} d)")
        return True
    return False


def open_cycle(c):
    for sub in ("cards", "sources/arxiv", "prompts"):
        os.makedirs(c.path(sub), exist_ok=True)
    os.chmod(c.dir, 0o700)
    try:
        until = datetime.date.fromisoformat(c.date)
        since = until - datetime.timedelta(days=int(os.environ.get("PAPERS_WINDOW_DAYS") or "14"))
        c.until, c.since = until.strftime("%Y%m%d"), since.strftime("%Y%m%d")
    except ValueError as e:
        print(f"papers window: {e}", file=sys.stderr)
    c.window = f"{c.since}~{c.until}"
    c.beat.log(f"start cycle {c.date} window {c.window} (force={int(c.force)} resume={c.resume or 'no'})")
    set_state("running", "")


def contact_allowed(c, stage):
    """Read the allowance to send again right before stage contacts arXiv: it may have been taken back
    since the cycle started (tools/options.py off loop). Without it the cycle ends there, failed."""
    C.reload()   # The configuration as it is now, not as this process first read it.
    refused = loop_settings.cycle_refusal("papers", C.egress_model_send())
    if refused:
        c.beat.fail(stage, refused)
        raise End("failed")


def sweep(c):
    b, cand = c.beat, c.path("candidates.tsv")
    if not nonempty(cand):
        contact_allowed(c, "sweep")
        if b.run(["python3", "tools/loop/papers/sweep.py", "--since", c.since, "--until", c.until, "--out", cand],
                 out=c.path("sweep.log"), mode="w"):
            b.fail("sweep", f"sweep failed ({c.path('sweep.log')})")
            if os.path.lexists(cand):
                os.unlink(cand)
            raise End("failed")
    c.ncand = max(read(cand).count("\n") - 1, 0)   # The first line names the columns.
    b.log(f"candidates {c.ncand}")
    if c.ncand <= 0:
        b.log("no candidates (the sweep succeeded and found none)")
        raise End("noop")


def triage(c):
    b, out = c.beat, c.path("triage.tsv")
    if not nonempty(out):
        prompt = c.path("prompts", "triage.md")
        if not c.render("triage", prompt):
            b.fail("triage", "triage prompt could not be rendered")
        rc = b.walk("triage", prompt, c.path("triage.receipt"), out)["rc"]
        if rc:
            b.fail("triage", f"triage worker rc={rc}")
    if not nonempty(out):
        b.fail("triage", f"no triage output ({c.path('triage.receipt')})")
        raise End("failed")


def _base(paper_id):
    """An arXiv id without its version suffix."""
    return re.sub(r'v\d+$', '', paper_id.strip())


def select_top(R, record=None):
    """Write top.tsv and group-{A,B,C}.list for cycle folder R and print what was picked.

    The triage worker's answer names the papers; a row counts only when its id is one the sweep listed
    and has the form of an arXiv id (ARXIV_ID), since the fetcher builds file names from it.
    The 14-day window overlaps the previous weekly cycle, so a paper the record (READ_RECORD's form)
    says an earlier cycle read is skipped (arXiv version suffixes are ignored when matching); a newer
    cycle never excludes papers from a resumed older one. At most READ_PER_CYCLE papers are taken."""
    cand = {r[0]: r for r in csv.reader(open(f'{R}/candidates.tsv', encoding='utf-8'), delimiter='\t') if r and r[0] != 'arxiv_id'}
    rows = [line.rstrip('\n').split('\t') for line in open(f'{R}/triage.tsv', encoding='utf-8') if line.strip() and not line.startswith('#')]
    here = os.path.basename(os.path.abspath(R))[:10]
    read_by = load_json(record).get('read', {}) if record else {}
    seen = {_base(i) for i, day in read_by.items() if isinstance(day, str) and day < here}
    scored = [r for r in rows if len(r) >= 3 and r[1].strip() == '3' and r[0] in cand and ARXIV_ID.fullmatch(r[0])]
    top = [r for r in scored if _base(r[0]) not in seen][:READ_PER_CYCLE]
    print('skip read in earlier cycles', len(scored) - len([r for r in scored if _base(r[0]) not in seen]))
    groups = {'A': [], 'B': [], 'C': []}
    for r in top:
        tag = r[2]
        g = 'A' if re.search(r'receipt|verify|isolation|install', tag) else ('B' if re.search(r'context|memory|enforce|skill', tag) else 'C')
        groups[g].append(r[0])
    with open(f'{R}/top.tsv', 'w', encoding='utf-8') as f:
        for r in top:
            slug = re.sub(r'[^a-z0-9]+', '-', cand.get(r[0], ['', '', 'x'])[2].lower())[:50].strip('-')
            f.write(f'{r[0]}\t{slug}\n')
    for g, ids in groups.items():
        open(f'{R}/group-{g}.list', 'w', encoding='utf-8').write('\n'.join(ids) + ('\n' if ids else ''))
    print('top', len(top), {g: len(v) for g, v in groups.items()})


def top_and_fetch(c):
    """Select this run's papers, then fetch exactly those: the selection of an earlier run is removed first,
    and a selection that fails ends the cycle before the fetcher starts."""
    b = c.beat
    for name in ["top.tsv"] + [f"group-{g}.list" for g in GROUPS]:
        if os.path.isfile(c.path(name)) or os.path.islink(c.path(name)):
            os.unlink(c.path(name))
    if not b.in_log(select_top, c.dir, READ_RECORD):
        b.fail("top", "top selection failed")
        if os.path.lexists(c.path("top.tsv")):
            os.unlink(c.path("top.tsv"))
        raise End("failed")
    contact_allowed(c, "fetch")
    if b.run(["python3", "tools/loop/papers/fetch_arxiv.py", c.path("top.tsv"), c.path("sources", "arxiv")],
             out=c.path("fetch.log"), mode="w"):
        b.log("fetch nonzero (a missing full text shows at the cards stage)")
    c.ntop = read(c.path("top.tsv")).count("\n")
    b.log(f"top {c.ntop}")


def card_job(c, g):
    """The card worker of group g, or None when the group needs none (a failure is recorded)."""
    if nonempty(c.path("cards", f"group-{g}.md")):
        return None
    ids = read(c.path(f"group-{g}.list")).split()
    if not ids:
        return None
    files = [p for i in ids for p in sorted(glob.glob(os.path.join(c.dir, "sources", "arxiv", glob.escape(i) + "-*.txt")))]
    if not files:
        c.beat.fail("cards", f"card {g}: no full text (fetch.log)")
        return None
    prompt = c.path("prompts", f"card-{g}.md")
    c.render("card", prompt, g, "\n".join(f"- `{p}`" for p in files))
    return lambda: c.beat.walk("card", prompt, c.path(f"card-{g}.receipt"), c.path("cards", f"group-{g}.md"))["rc"]


def cards(c):
    b = c.beat
    jobs = [(g, job) for g in GROUPS for job in (card_job(c, g),) if job]
    results = b.parallel(jobs)
    for g, _ in jobs:
        if results.get(g, 1):
            b.fail("cards", f"card worker {g} rc={results.get(g, 1)}")
        if not nonempty(c.path("cards", f"group-{g}.md")):
            b.fail("cards", f"no card output {g}")
    receipts = sorted(glob.glob(c.path("card-*.receipt")))
    c.ncards = sum(card_count(loop_worker.outcome(p, root=".")["result"]) for p in receipts)
    b.log(f"cards {c.ncards}")
    b.log(f"read {record_read(c)}")
    if not glob.glob(c.path("cards", "group-*.md")):
        b.fail("cards", "no cards")
        raise End("failed")


def record_read(c):
    """Record as read each paper of this cycle whose id (without its version) a card names; return how many."""
    named = {}
    for g in GROUPS:
        card = read(c.path("cards", f"group-{g}.md"))
        for i in read(c.path(f"group-{g}.list")).split():
            if re.search(re.escape(_base(i)) + r"(?![0-9])", card):
                named[_base(i)] = c.date
    record = load_json(READ_RECORD)
    record["read"] = {**named, **(record.get("read") if isinstance(record.get("read"), dict) else {})}
    write_json(READ_RECORD, record, indent=1)
    return len(named)


def proposals(c):
    b, out = c.beat, c.path("PROPOSALS.md")
    if not nonempty(out):
        prompt = c.path("prompts", "propose.md")
        c.render("propose", prompt)
        rc = b.walk("propose", prompt, c.path("propose.receipt"), out)["rc"]
        if rc:
            b.fail("proposals", f"proposal worker rc={rc}")
    if not nonempty(out) or os.path.getsize(out) < 200:
        b.fail("proposals", "PROPOSALS.md missing or under 200 bytes")
        c.props_ok = False


def _newer(a, b):
    # Compared in whole seconds.
    return int(os.stat(a).st_mtime) > int(os.stat(b).st_mtime)


def digest(c):
    """The optional digest: accepted only from a worker that ended 0 with success status.

    No program reads the digest, so its failure is logged and shown in REPORT, not fatal, and it is
    not built from missing proposals."""
    b, out, receipt = c.beat, c.path("DIGEST-EN.md"), c.path("digest.receipt")
    kept = (nonempty(out) and nonempty(c.path("PROPOSALS.md")) and _newer(out, c.path("PROPOSALS.md"))
            and loop_worker.outcome(receipt, root=".")["status"] == "success")
    prompt = c.path("prompts", "digest-en.md")
    c.render("digest-en", prompt)
    if not c.props_ok:
        b.log("digest skipped (no proposals)")
        return
    if kept:
        b.log("digest kept")
        return
    o = b.walk("digest", prompt, receipt)
    rc = o["rc"]
    if rc == 0 and o["status"] == "success" and has_heading(o["result"], DIGEST_END):
        write(out, o["result"])
        b.log("digest ok")
    else:
        if os.path.lexists(out):
            os.unlink(out)
        b.log(f"digest failed, cycle continues (rc={rc}, {receipt})")


def collected(c):
    """REPORT.md's lines about what the collection found and wrote, from the cycle folder's files."""
    tri = [line for line in read(c.path("triage.tsv")).splitlines() if line.strip() and not line.startswith("#")]
    n3 = sum(1 for line in tri if line.split("\t")[1:2] == ["3"])
    heads = re.findall(r"^" + re.escape(PROPOSAL_HEADING) + r"(.+)$", read(c.path("PROPOSALS.md")), re.M)
    lines = [f"Searched arXiv {c.window}: papers found {c.ncand}, scored 3 {n3}, read in full {c.ntop}, "
             f"paper summaries {c.ncards}, proposals {len(heads)}."]
    lines += [f"Proposal: {h}" for h in heads]
    for label, name in (("Proposals", "PROPOSALS.md"), ("Paper digest", "DIGEST-EN.md"), ("Scan data", "triage.tsv")):
        if nonempty(c.path(name)):
            lines.append(f"{label}: `{c.path(name)}`")
    if heads and not nonempty(c.path("DIGEST-EN.md")):
        lines.append(f"No paper digest: its worker failed (`{c.path('digest.receipt')}`).")
    return lines


def draw_report(c, state):
    """Write the collection record (loop_state.COLLECTION) and draw REPORT.md from the cycle's records."""
    if not os.path.isdir(c.dir):
        return
    write_json(c.path(COLLECTION), {"title": f"Papers cycle report: {c.date} (arXiv {c.window})", "state": state,
                                    "failure": c.beat.failures or None, "log": LOG if c.beat.fails else None,
                                    "collected": collected(c)}, ensure_ascii=False, indent=1)
    loop_report.draw(c.dir)


def report(c):
    if not c.beat.in_log(draw_report, c, "pending"):
        c.beat.fail("report", "REPORT could not be written")


def apply(c):
    """Judge, build, test and review when proposals exist; the applier saves patches and writes no tracked file."""
    out = c.path("PROPOSALS.md")
    if nonempty(out) and os.path.getsize(out) >= 200:
        rc = c.beat.tool("loop/papers_apply.py", c.dir)
        if rc:
            c.beat.fail("apply", f"judge and apply failed rc={rc} ({c.path('REPORT.md')})")


STAGES = (sweep, triage, top_and_fetch, cards, proposals, digest, report, apply)
CURRENT = None


def parse(argv):
    """(force, resume date or "") from the command line; a bad --resume ends with status 2."""
    first = argv[0] if argv else ""
    if first == "--force":
        return True, ""
    if first == "--resume":
        date = argv[1] if len(argv) > 1 else ""
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
            print("--resume YYYY-MM-DD", file=sys.stderr)
            sys.exit(2)
        return True, date
    return False, ""


def main(argv=None):
    global CURRENT
    refused = loop_settings.cycle_refusal("papers", C.egress_model_send())
    if refused:
        print(refused)
        return 1
    os.makedirs(PDIR, exist_ok=True)
    os.chmod(PDIR, 0o700)
    force, resume = parse(sys.argv[1:] if argv is None else argv)
    date = resume or datetime.date.today().isoformat()
    beat = Beat(LOG, worker_timeout=float(os.environ.get("PAPERS_WORKER_TIMEOUT") or WORKER_TIMEOUT))
    if not beat.take_lock(f"{PDIR}/cycle.lock"):
        beat.log("skip: another papers cycle is running (cycle.lock)")
        return 0
    beat.stop_workers_on_signals()
    os.makedirs(CYCLES, exist_ok=True)
    os.chmod(CYCLES, 0o700)
    c = CURRENT = Cycle(beat, date, force, resume)
    if not resume:
        beat.backlog([])
    if weekly_skip(c):
        return 0
    if loop_state.apply_status(c.dir) is not None and not force:
        beat.log(f"skip: {c.dir} has an apply outcome")
        return 0
    open_cycle(c)
    try:
        for stage in STAGES:
            stage(c)
    except End as e:
        stopped = loop_worker.ceiling_line(c.dir)
        return finish(c, loop_worker.CEILING if stopped and e.status == "failed" else e.status)
    # A clean cycle journals nothing; finish journals a failure. Stages missing at the ceiling are not one.
    return finish(c, (loop_worker.CEILING if loop_worker.ceiling_line(c.dir) else "failed") if beat.fails else "ok")


if __name__ == "__main__":
    sys.exit(main())
