#!/usr/bin/env python3
"""Measure known-item retrieval from locally sampled transcript messages.

Select query words from an original message and measure whether that same message returns in the
top k results. Source omissions, parsing, eligibility, ranking, and wording are separate failure
causes.

It measures the literal transcript search (`find --json`), not the store that answers a search of the
owner's words (`find --role user`); each record says so in its "path" field, so a later measurement of
the store is not read as a change of this series.

This does not measure paraphrase retrieval or whether a retrieved message helped a task. Those
require separate queries and outcome observations.

Usage: python3 tools/dev/eval_recall.py [--n 20] [--max 8] [--quiet]
Append one measurement to _private/state/metrics-recall.jsonl."""
import argparse
import collections
import datetime
import json
import os
import random
import re
import subprocess
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P
import transcripts

# Messages this module prints in more than one place, or too long to read inline.
ERROR = (
    "[{band}] error: the search command failed (failed queries: {errors}, tried: {tried}), so "
    "no hit rate was recorded. Last error: {tail}"
)
FLOOR = (
    "This number is a **floor**: query words come from the original text, so wording mismatch "
    "is not measured."
)
MISSES = (
    "{count} miss(es) (to classify by cause: source, parser, eligibility, ranking, wording):"
)
RECORDED = "recorded: {path}"
TOO_FEW = (
    "Not enough transcript messages ({count}). Accumulate more sessions and measure again."
)
UNMEASURED = (
    "[{band}] unmeasured: no query words could be extracted from any sampled message "
    "({skipped} sampled). This is not a 0% hit rate."
)

METRICS = P.recall_metrics()

# Exclude common or structurally unhelpful query tokens. Transcripts mix languages, so common
# Korean function words are stop words too.
STOP = {"that", "this", "with", "from", "have", "been", "will",
        "그리고", "그런데", "그래서", "하지만", "이거", "저거", "그거", "이건", "저건", "그건",
        "있다", "없다", "한다", "된다", "그럼", "근데", "아니", "네가", "내가", "우리",
        "너무", "정말", "진짜", "조금", "많이", "이제", "지금", "다시", "그냥", "좀더",
        "같이", "대해", "위해", "통해"}
# Query tokens: runs of two or more Hangul syllables, or Latin words of four or more characters.
TOKEN = re.compile(r"[\uac00-\ud7a3]{2,}|[A-Za-z][A-Za-z0-9_.-]{3,}")


def _records():
    """The long messages of the newest Claude file, read with the same reader and ids as a search.

    It is not an archive-coverage or cross-runtime benchmark; those are planted-item tests.
    """
    files = [p for _, kind, p in transcripts.source_files({"claude"}) if kind == "claude-jsonl"]
    files.sort(key=os.path.getmtime, reverse=True)
    paths = set(files[:1])
    return [m for m in transcripts.iter_messages({"claude"}, paths=paths)
            if m["timestamp"] and len(m["text"]) > 200]


def _retrieved_id(stdout, record_id):
    """A different message in the same minute is not a successful retrieval."""
    try:
        rows = json.loads(stdout)
    except (ValueError, TypeError):
        return False
    return isinstance(rows, list) and any(isinstance(m, dict) and m.get("record_id") == record_id
                                         for m in rows)


def _doc_freq(texts):
    """Count the messages containing each token to estimate query-word rarity."""
    df = collections.Counter()
    for t in texts:
        for w in set(TOKEN.findall(t)):
            df[w] += 1
    return df


# Query difficulty by document frequency: rare identifiers test exact lookup, and common topic
# words exercise ranking.
BANDS = {"rare": (1, 5), "mid": (6, 40), "topic": (41, 400)}
# Words in one query.
QUERY_TERMS = 2


def _query_for(text, df, band="topic"):
    """An OR query of QUERY_TERMS words of text in the band, or None when it has too few."""
    lo, hi = BANDS[band]
    words = [w for w in set(TOKEN.findall(text)) if w not in STOP]
    inband = [w for w in words if lo <= df.get(w, 0) <= hi]
    if len(inband) < QUERY_TERMS:
        return None
    # The most common words of the band first; the word itself breaks ties, so the query does not
    # depend on set order and the hash seed.
    inband.sort(key=lambda w: (-df[w], -len(w), w))
    return "|".join(re.escape(w) for w in inband[:QUERY_TERMS])


def _search(query, max_hits):
    """Run one literal search; return (stdout, None), or (None, the last error line) on failure."""
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "recall.py"), "find", query,
                            "--max", str(max_hits), "--around", "0", "--json"],
                           capture_output=True, text=True, cwd=P.instance_root(), timeout=120)
    except subprocess.TimeoutExpired:
        return None, "timeout after 120s"
    if r.returncode != 0:
        lines = r.stderr.strip().splitlines()
        return None, lines[-1] if lines else f"exit {r.returncode}"
    return r.stdout, None


def _measure(sample, df, band, max_hits, quiet):
    """Search for each sampled message; return (hits, misses, skipped, errors, last error)."""
    hits, misses, skipped, errors, err_tail = 0, [], 0, 0, ""
    for message in sample:
        ts, role, text = message["timestamp"][:16], message["role"], message["text"]
        q = _query_for(text, df, band=band)
        if not q:
            skipped += 1
            continue
        stdout, error = _search(q, max_hits)
        # A failed search says nothing about retrieval; counting it as a miss would hide a broken tool as a low rate.
        if error is not None:
            errors += 1
            err_tail = error
            continue
        # Stable IDs, not display timestamps, identify the target original.
        found = _retrieved_id(stdout, message["record_id"])
        if found:
            hits += 1
        else:
            misses.append({"ts": ts, "role": role, "q": q, "record_id": message["record_id"],
                           "head": text[:70].replace("\n", " ")})
        if not quiet:
            print(f"  {'found' if found else 'missed'}  {transcripts.local_time(message['timestamp'])}  /{q[:46]}/")
    return hits, misses, skipped, errors, err_tail


def run(n=20, max_hits=8, seed=20260824, quiet=False, band="topic"):
    records = _records()
    if len(records) < n * 2:
        print(TOO_FEW.format(count=len(records)))
        return 1
    df = _doc_freq(m["text"] for m in records)
    # A fixed seed draws the same sample from the same messages. The newest transcript usually
    # grows between runs, so two rows are seldom drawn from the same messages.
    rnd = random.Random(seed)
    hits, misses, skipped, errors, err_tail = _measure(rnd.sample(records, n), df, band, max_hits, quiet)
    tried = n - skipped
    # With no query tried there is no hit rate; recording 0.0 would read as total failure.
    rate = round(hits / tried, 3) if tried and not errors else None
    rec = {"date": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M"),
           "band": band, "path": "transcript", "n": tried, "hits": hits, "rate": rate, "max_hits": max_hits,
           "status": "error" if errors else ("measured" if tried else "unmeasured"),
           "seed": seed, "corpus_turns": len(records), "skipped": skipped,
           "misses": misses[:5]}
    if errors:
        rec["errors"] = errors
    os.makedirs(os.path.dirname(METRICS), exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    recorded = RECORDED.format(path=os.path.relpath(METRICS, P.instance_root()))
    if errors:
        print("\n" + ERROR.format(band=band, errors=errors, tried=tried, tail=err_tail))
        print(recorded)
        return 1
    if not tried:
        print("\n" + UNMEASURED.format(band=band, skipped=skipped))
        print(recorded)
        return 1
    print("\n" + "[{band}] hit@{max_hits} = {hits}/{tried} ({rate}) · corpus messages {turns}".format(band=band, max_hits=max_hits, hits=hits, tried=tried, rate=f"{rate:.0%}", turns=len(records))
          + (f" · no query words {skipped}" if skipped else ""))
    if misses:
        print("\n" + MISSES.format(count=len(misses)))
        for m in misses[:5]:
            print(f"  {m['ts']} [{m['role']}] /{m['q'][:40]}/  {m['head']}")
    print("\n" + recorded)
    print(FLOOR)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--max", type=int, default=8, dest="max_hits")
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--band", choices=list(BANDS), default="topic",
                    help=(
                        "query difficulty. rare=rare tokens (easy) · topic=topic words (real "
                        "use)"
                    ))
    a = ap.parse_args()
    sys.exit(run(a.n, a.max_hits, a.seed, a.quiet, a.band))
