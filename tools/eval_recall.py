#!/usr/bin/env python3
"""Measure known-item retrieval from locally sampled transcript messages.

Select query words from an original message and measure whether that same message returns in the top k results. Source omissions, parsing, eligibility, ranking, and wording are separate failure causes.

This does not measure paraphrase retrieval or whether a retrieved message helped a task. Those require separate queries and outcome observations.

Usage: python3 tools/eval_recall.py [--n 20] [--max 8] [--quiet]
Append one measurement to _private/state/metrics-recall.jsonl."""
import argparse
import collections
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M
import recall
from i18n import STRINGS, t

METRICS = os.path.join(M.ROOT, "_private", "state", "metrics-recall.jsonl")

# Exclude common or structurally unhelpful query tokens.
# Transcripts mix languages, so both stop lists apply regardless of the output language.
STOP = set(" ".join(STRINGS["eval_recall.stopwords"].values()).split())
# Query tokens: runs of two or more Hangul syllables, or Latin words of four or more characters.
TOKEN = re.compile(r"[\uac00-\ud7a3]{2,}|[A-Za-z][A-Za-z0-9_.-]{3,}")


def _records(limit_files=1):
    """Latest Claude-file benchmark, using the same reader and IDs as retrieval.

    This sampling scope is intentionally unchanged; it is not an archive-coverage
    or cross-runtime benchmark. Those are separate planted-item regressions.
    """
    files = [p for _, kind, p in recall._source_files({"claude"}) if kind == "claude-jsonl"]
    files.sort(key=os.path.getmtime, reverse=True)
    paths = set(files[:limit_files])
    return [m for m in recall.iter_messages({"claude"}, paths=paths)
            if m["timestamp"] and len(m["text"]) > 200]


def _turns(limit_files=1):
    """Compatibility tuple view for query-selection helpers."""
    return [(m["timestamp"][:16], m["role"], m["text"]) for m in _records(limit_files)]


def _retrieved_id(stdout, record_id):
    """A different message in the same minute is not a successful retrieval."""
    try:
        rows = json.loads(stdout)
    except (ValueError, TypeError):
        return False
    return isinstance(rows, list) and any(isinstance(m, dict) and m.get("record_id") == record_id
                                         for m in rows)


def _doc_freq(turns):
    """Count the messages containing each token to estimate query-word rarity."""
    df = collections.Counter()
    for _ts, _r, t in turns:
        for w in set(TOKEN.findall(t)):
            df[w] += 1
    return df


# Choose query difficulty by document frequency: rare identifiers test exact lookup; common topic words exercise ranking.
BANDS = {"rare": (1, 5), "mid": (6, 40), "topic": (41, 400)}


def _query_for(text, df, n_terms=2, band="topic"):
    """Build an OR query from n words in the requested document-frequency band. Topic words exercise ranking among competing messages."""
    lo, hi = BANDS[band]
    words = [w for w in set(TOKEN.findall(text)) if w not in STOP]
    inband = [w for w in words if lo <= df.get(w, 0) <= hi]
    if len(inband) < n_terms:
        return None                                   # Skip messages without enough words in the requested frequency band.
    inband.sort(key=lambda w: (-df[w], -len(w)))      # Prefer the most common words within the band.
    return "|".join(re.escape(w) for w in inband[:n_terms])


def run(n=20, max_hits=8, seed=20260824, quiet=False, band="topic"):
    records = _records()
    turns = [(m["timestamp"][:16], m["role"], m["text"]) for m in records]
    if len(turns) < n * 2:
        print(t("eval_recall.too_few", count=len(turns)))
        return 1
    df = _doc_freq(turns)
    rnd = random.Random(seed)                        # Use a fixed seed so repeated measurements sample the same messages.
    sample = rnd.sample(records, n)

    hits, misses, skipped = 0, [], 0
    for message in sample:
        ts, role, text = message["timestamp"][:16], message["role"], message["text"]
        q = _query_for(text, df, band=band)
        if not q:
            skipped += 1
            continue
        r = subprocess.run([sys.executable, os.path.join(HERE, "recall.py"), "find", q,
                            "--max", str(max_hits), "--around", "0", "--json"],
                           capture_output=True, text=True, cwd=M.ROOT)
        # Stable IDs, not display timestamps, identify the target original.
        want = recall._local_time(message["timestamp"])
        found = r.returncode == 0 and _retrieved_id(r.stdout, message["record_id"])
        if found:
            hits += 1
        else:
            misses.append({"ts": ts, "role": role, "q": q, "record_id": message["record_id"],
                           "head": text[:70].replace("\n", " ")})
        if not quiet:
            print(f"  {t('eval_recall.found') if found else t('eval_recall.missed')}  {want}  /{q[:46]}/")

    tried = n - skipped
    # With no query tried there is no hit rate; recording 0.0 would read as total failure.
    rate = round(hits / tried, 3) if tried else None
    rec = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M"),
           "band": band, "n": tried, "hits": hits, "rate": rate, "max_hits": max_hits,
           "status": "measured" if tried else "unmeasured",
           "seed": seed, "corpus_turns": len(turns), "skipped": skipped,
           "misses": misses[:5]}
    os.makedirs(os.path.dirname(METRICS), exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if not tried:
        print("\n" + t("eval_recall.unmeasured", band=band, skipped=skipped))
        print(t("eval_recall.recorded", path=os.path.relpath(METRICS, M.ROOT)))
        return 1

    print("\n" + t("eval_recall.summary", band=band, max_hits=max_hits, hits=hits, tried=tried,
                    rate=f"{rate:.0%}", turns=len(turns))
          + (t("eval_recall.skipped", count=skipped) if skipped else ""))
    if misses:
        print("\n" + t("eval_recall.misses", count=len(misses)))
        for m in misses[:5]:
            print(f"  {m['ts']} [{m['role']}] /{m['q'][:40]}/  {m['head']}")
    print("\n" + t("eval_recall.recorded", path=os.path.relpath(METRICS, M.ROOT)))
    print(t("eval_recall.floor"))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--max", type=int, default=8, dest="max_hits")
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--band", choices=list(BANDS), default="topic",
                    help=t("eval_recall.help_band"))
    a = ap.parse_args()
    sys.exit(run(a.n, a.max_hits, a.seed, a.quiet, a.band))
