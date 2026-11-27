#!/usr/bin/env python3
"""A cycle's report: the applier's outcome record, REPORT.md drawn from the cycle's records, the one line
a run ends with, and the journal line that tells the owner's next session about saved changes.

REPORT.md is drawn whole each time a beat or the applier ends, from the beat's collection record
(loop_state.COLLECTION), the outcome record (loop_state.OUTCOME_REL) and the cycle's model use
(tools/loop/lib/loop_worker.py). Programs read the records; REPORT.md is for the owner and their agent,
and starts with what to do now."""
import json
import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
from loop_checks import evidence_line  # noqa: E402
from loop_common import clip, load_json, today, tool, write  # noqa: E402
from loop_judging import input_name  # noqa: E402
from loop_outcome import ABANDONED, OUTCOMES, PENDING, REFUSED, SAVED, bundle_outcome  # noqa: E402
from loop_state import CEILING, COLLECTION, DONE, FAILED, OUTCOME_REL, cycle_state, read_outcome  # noqa: E402
from loop_worker import ceiling_line, reviewer_line, spent, spent_line  # noqa: E402

# The line under the status of a cycle whose starting commit fails the kit pre-commit check too.
GATE_BLOCKED = ("Before your next commit: the kit pre-commit check fails on the starting commit too, so Git's "
                "pre-commit hook may refuse your next commit for the same reason: ")


def cycle_status(ctx, bundles, failure=None):
    """The cycle's state word. failure is the (stage, reason) of a run that stopped. Failed comes first,
    then token-ceiling (a stage did not start because the cycle reached loop.token_ceiling), then
    pending (a bundle is not finished), else done."""
    if failure:
        return FAILED
    if ctx.ceiling:
        return CEILING
    if any(bundle_outcome(b.get("_r")) == PENDING for b in bundles):
        return PENDING
    return DONE


def counts(bundles, refused_ideas=()):
    """The number of changes with each outcome; an idea the judge refused counts as refused."""
    outcomes = [bundle_outcome(b.get("_r")) for b in bundles]
    c = {word: outcomes.count(word) for word in OUTCOMES}
    c[REFUSED] += len(refused_ideas)
    return c


def _bundle_entry(b):
    r = b.get("_r", {})
    return {"id": b["id"], "title": b["title"], "kind": b["kind"], "change": b.get("change"),
            "files": b.get("files", []), "outcome": bundle_outcome(r), "reason": r.get("result"),
            "patch": r.get("patch"), "tests": r.get("tests"), "review": r.get("review"),
            "builder": r.get("impl_runtime"), "reviewer": r.get("reviewer"), "base_rev": r.get("base_rev"),
            "evidence": r.get("evidence"),
            "attempts": [{k: a.get(k) for k in ("number", "status", "failure_stage", "artifacts")}
                         for a in r.get("attempts", [])]}


def outcome_record(ctx, failure, summary, bundles, rejected, inp_sha):
    """The record of this run over the cycle: state, input, each change's outcome, the ideas the judge
    refused, and the counts."""
    refused = [{"id": x["id"], "title": x.get("title", ""), "reason": x["reason"]} for x in rejected]
    return {"state": cycle_status(ctx, bundles, failure),
            "failure": {"stage": failure[0], "reason": failure[1]} if failure else None,
            "source": ctx.source, "cycle": ctx.d, "run_on": today(),
            "input": {"name": input_name(ctx.source), "sha256": inp_sha or None},
            "judge_summary": summary or None, "base_summary": ctx.base_summary or None,
            "bundles": [_bundle_entry(b) for b in bundles], "refused": refused, "counts": counts(bundles, refused),
            "blocked": list(dict.fromkeys(ctx.blocked)), "notes": list(ctx.notes)}


def count_words(c):
    """The counts that are not zero, in the order a person acts on them."""
    said = [f"{c[w]} {w}" for w in (SAVED, PENDING, REFUSED, ABANDONED) if c.get(w)]
    return ", ".join(said) or "nothing saved"


def _status(state, rec, col, cyc):
    if rec.get("failure"):
        f = rec["failure"]
        return f"**Status:** failed at {f['stage']}: {f['reason']}. The next run tries again."
    if state == FAILED:
        return f"**Status:** failed: {col.get('failure') or 'the outcome record cannot be read'}. The next run tries again."
    if state == CEILING:
        stopped = ceiling_line(cyc) or "stopped at loop.token_ceiling"
        return f"**Status:** {CEILING}. The cycle {stopped}. Raising loop.token_ceiling lets the next run continue it."
    if not rec:
        return f"**Status:** {state}." + (" Collected; the judge has not run yet." if state == PENDING else "")
    return f"**Status:** {state}. {count_words(rec['counts'])}."


def _saved(e):
    patch = e["patch"]
    return [f"### {e['id']}: {e['title']}", "", f"{e['change'] or '(no description)'}", "",
            f"- Files: {', '.join(f'`{p}`' for p in e['files'])}",
            f"- Evidence: {evidence_line(e.get('evidence'))}",
            f"- Built by {e['builder'] or 'an unrecorded runtime'}, reviewed by {reviewer_line(e)}.",
            f"- Tests: {e['tests'] or 'not recorded'}",
            f"- Review: {e['review'] or 'not recorded'}",
            f"- Patch: `{patch}`", "",
            "Read the block and the patch, then from the kit folder:", "", "```text",
            f"git apply --check {patch}", f"git apply {patch}", "python3 tools/tests/run.py", "```", "",
            f"If the tests fail, or to undo it later: `git apply -R {patch}`", ""]


def _refused_name(x):
    """A refused idea's id, or its title when the judge gave it no id ("-")."""
    return (x.get("title") or "-") if x["id"] == "-" else x["id"]


def _groups(rec):
    entries = rec.get("bundles") or []
    saved = [e for e in entries if e["outcome"] == SAVED]
    pending = [e for e in entries if e["outcome"] == PENDING]
    ended = [f"- **{e['id']}** {e['reason'] or e['outcome']}" for e in entries if e["outcome"] in (REFUSED, ABANDONED)]
    ended += [f"- **{_refused_name(x)}** "
              + (x["reason"] if x["reason"].startswith(REFUSED) else f"refused, {x['reason']}")
              for x in rec.get("refused") or []]
    L = []
    if saved:
        L += [f"## Saved: yours to apply ({len(saved)})", ""]
        for e in saved:
            L += _saved(e)
    if pending:
        L += [f"## Pending ({len(pending)})", ""] + [f"- **{e['id']}** {e['reason'] or PENDING}" for e in pending] + [""]
    if ended:
        L += [f"## Refused and abandoned ({len(ended)})", ""] + ended + [""]
    return L


def _details(d, rec):
    inp, picked = rec["input"], ", ".join(f"{e['id']} ({e['kind']})" for e in rec["bundles"]) or "nothing"
    L = ["## Run details", "", f"- Run on: {rec['run_on']}", f"- The judge picked: {picked}",
         f"- Judgment: `{d}/JUDGE.md` (summary: {rec['judge_summary'] or '-'})",
         f"- Input: `{inp['name']}` (sha256 {(inp['sha256'] or '-')[:16]})",
         f"- Sandbox test baseline: {rec['base_summary'] or 'not run'}"]
    for e in rec["bundles"]:
        L += [f"- Attempt {a['number']} of `{e['id']}`: {a['status'] or 'unknown'}"
              + (f" at {a['failure_stage']}" if a["failure_stage"] else "") + f" (`{a['artifacts']}/attempt.json`)"
              for a in e["attempts"]]
    L += [f"- Note: {n}" for n in rec["notes"]]
    return L + [""]


def _model_use(cyc):
    c = spent(cyc)
    L = [f"Token ceiling {c['ceiling']} reached at {c['tokens']} tokens; these stages did not start: "
         f"{', '.join(dict.fromkeys(c['not_started']))}."] if c["not_started"] else []
    return L + [f"Model use this cycle: {spent_line(cyc)}."]


def draw(d, root="."):
    """Write REPORT.md of the cycle folder d (relative to root) from its records."""
    cyc = os.path.join(root, d)
    col, rec = load_json(os.path.join(cyc, COLLECTION)), read_outcome(cyc) or {}
    state = cycle_state(cyc) or PENDING
    L = [f"# {col.get('title') or 'Cycle report: ' + os.path.basename(d)}", "", _status(state, rec, col, cyc)]
    if rec.get("blocked"):
        L += ["", f"{GATE_BLOCKED}{rec['blocked'][0]}"]
    L += [""]
    groups = _groups(rec) if rec else []
    L += groups or (["Nothing to do: no change was saved.", ""] if state != PENDING else [])
    collected = (col.get("collected", []) + ([f"The collection failed: {col['failure']}"] if col.get("failure") and rec else [])
                 + ([f"Log: `{col['log']}`"] if col.get("log") else []))
    L += ["## What this cycle collected", ""] + [f"- {line}" for line in collected] + [""]
    if rec.get("bundles") is not None:
        L += _details(d, rec)
    write(os.path.join(cyc, "REPORT.md"), "\n".join(L + _model_use(cyc)) + "\n")


def in_words(d, root="."):
    """The cycle folder d in a few words: its date, state and counts."""
    cyc = os.path.join(root, d)
    rec = read_outcome(cyc) or {}
    said = f" · {count_words(rec['counts'])}" if rec.get("counts") else ""
    return f"{os.path.basename(d)[:10]} {cycle_state(cyc) or PENDING}{said}"


def end_line(d, root="."):
    """The one line a run ends with: the cycle, its state and counts, and its report."""
    return f"{in_words(d, root)}. Report: {d}/REPORT.md"


def journal_run(ctx, record):
    """One private journal line when the run leaves saved changes the journal has not named yet, so that
    the owner's next session sees them in its state view (python3 tools/now.py context); nothing else."""
    saved = sorted(e["id"] for e in record["bundles"] if e["outcome"] == SAVED)
    if not saved or ctx.state.get("journaled") == saved:
        return
    n = len(saved)
    line = (f"[system/state] loop {ctx.source} {os.path.basename(ctx.d)[:10]}: {n} saved change{'' if n == 1 else 's'} "
            f"to review and apply, see {ctx.d}/REPORT.md")
    if tool(ctx.root, "now.py", "log", "--private", clip(line, 290)):
        ctx.state["journaled"] = saved
        try:
            ctx.save([])
        except OSError:
            pass   # The next run journals once more; nothing else depends on it.
    else:
        ctx.notes.append("the journal line about saved changes was not written (now.py ended nonzero)")
        record["notes"] = list(ctx.notes)
        print("warning: the journal line was not written", file=sys.stderr)


def write_outcome(ctx, record):
    """Write the record whole, draw REPORT.md from it, and print the run's last line."""
    write(os.path.join(ctx.cyc, OUTCOME_REL), json.dumps(record, ensure_ascii=False, indent=1) + "\n")
    draw(ctx.d, ctx.root)
    print(f"{ctx.source} {end_line(ctx.d, ctx.root)}")
