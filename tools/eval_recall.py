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

METRICS = os.path.join(M.ROOT, "_private", "state", "metrics-recall.jsonl")

# Exclude common or structurally unhelpful query tokens.
STOP = set("그리고 그런데 그래서 하지만 이거 저거 그거 이건 저건 그건 있다 없다 한다 된다 "
           "the and for that this with from have been will你 그럼 근데 아니 네가 내가 우리 "
           "너무 정말 진짜 조금 많이 이제 지금 다시 그냥 좀더 같이 대해 위해 통해".split())
TOKEN = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9_.-]{3,}")


def _records(limit_files=1):
    """Latest Claude-file benchmark, using the same reader and IDs as retrieval.

    This sampling scope is intentionally unchanged; it is not an archive-coverage
    or cross-runtime benchmark. Those are separate planted-item regressions.
    """
    import recall
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
        print(f"전사 발화가 부족하다 ({len(turns)}개). 세션을 더 쌓고 다시 재라.")
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
        want = __import__("recall")._kst(ts)
        found = r.returncode == 0 and _retrieved_id(r.stdout, message["record_id"])
        if found:
            hits += 1
        else:
            misses.append({"ts": ts, "role": role, "q": q, "record_id": message["record_id"],
                           "head": text[:70].replace("\n", " ")})
        if not quiet:
            print(f"  {'찾음' if found else '실패'}  {want}  /{q[:46]}/")

    tried = n - skipped
    rate = hits / tried if tried else 0.0
    rec = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M"),
           "band": band, "n": tried, "hits": hits, "rate": round(rate, 3), "max_hits": max_hits,
           "seed": seed, "corpus_turns": len(turns), "skipped": skipped,
           "misses": misses[:5]}
    os.makedirs(os.path.dirname(METRICS), exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n[{band}] hit@{max_hits} = {hits}/{tried} ({rate:.0%}) · 코퍼스 발화 {len(turns)}개"
          + (f" · 질의어 못 뽑음 {skipped}개" if skipped else ""))
    if misses:
        print(f"\n실패 {len(misses)}건 (소스·파서·출처·순위·표현 차이 원인 분류 대상):")
        for m in misses[:5]:
            print(f"  {m['ts']} [{m['role']}] /{m['q'][:40]}/  {m['head']}")
    print(f"\n기록: {os.path.relpath(METRICS, M.ROOT)}")
    print("이 수치는 **바닥**이다 — 질의어를 원문에서 뽑았으므로 표현 불일치는 안 쟀다.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--max", type=int, default=8, dest="max_hits")
    ap.add_argument("--seed", type=int, default=20260824)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--band", choices=list(BANDS), default="topic",
                    help="질의어 난이도. rare=희귀토큰(쉬움) · topic=주제어(실사용)")
    a = ap.parse_args()
    sys.exit(run(a.n, a.max_hits, a.seed, a.quiet, a.band))
