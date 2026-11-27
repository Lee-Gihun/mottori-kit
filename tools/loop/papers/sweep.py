#!/usr/bin/env python3
"""Sweep arXiv keywords for candidate papers, then let triage score the abstracts.

The queries are loop.papers_queries of the instance configuration, else DEFAULT_QUERIES; a --queries
file replaces both. Every request names the client of loop.papers_client and loop.papers_contact.

Usage: sweep.py --since YYYYMMDD --until YYYYMMDD --out candidates.tsv [--queries FILE]"""
import argparse, csv, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402

# The engine's queries, about the kit's own subject: agent harnesses, memory, review and isolation.
DEFAULT_QUERIES = [
    'abs:"agent" AND (abs:harness OR abs:scaffold) AND abs:LLM',
    'abs:"context" AND (abs:compaction OR abs:"context window") AND abs:agent',
    'abs:memory AND abs:agent AND (abs:persistent OR abs:"long-horizon" OR abs:"long horizon")',
    'abs:"multi-agent" AND (abs:orchestration OR abs:delegation OR abs:"sub-agent" OR abs:subagent)',
    'abs:"code review" AND abs:LLM',
    'abs:"coding agent" OR abs:"software engineering agent"',
    'abs:"self-improving" OR abs:"self-evolving" AND abs:agent',
    'abs:sandbox AND abs:agent AND (abs:tool OR abs:permission)',
    'abs:"prompt injection" AND abs:agent',
    'abs:reproducib* AND abs:agent AND abs:workflow',
    'abs:verification AND abs:agent AND (abs:independent OR abs:verifier OR abs:critic)',
    'abs:"human attention" OR abs:"cognitive load" AND abs:LLM',
    'abs:receipt OR abs:provenance AND abs:agent',
    'abs:"agent" AND abs:evaluation AND abs:benchmark AND abs:2026',
    'abs:calibrat* AND (abs:classifier OR abs:decision) AND abs:agent',
    'abs:proactive AND abs:assistant AND abs:LLM',
]
API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}


def run(q, window, start=0, n=50, agent=None):
    sq = f"({q}) AND submittedDate:[{window[0]}0000 TO {window[1]}0000]"
    url = API + "?" + urllib.parse.urlencode({"search_query": sq, "start": start, "max_results": n,
                                              "sortBy": "submittedDate", "sortOrder": "descending"})
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": agent or loop_config.papers_user_agent()}),
                                  timeout=60).read()
    out = []
    for e in ET.fromstring(data).findall("a:entry", NS):
        aid = re.sub(r"v\d+$", "", e.find("a:id", NS).text.rsplit("/", 1)[-1])
        out.append((aid, e.find("a:published", NS).text[:10], " ".join(e.find("a:title", NS).text.split()),
                    ",".join(c.get("term") for c in e.findall("a:category", NS)),
                    " ".join(e.find("a:summary", NS).text.split())))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--queries", default=None, help="one arXiv query per line")
    a = ap.parse_args()
    queries = list(loop_config.value("papers_queries") or DEFAULT_QUERIES)
    agent = loop_config.papers_user_agent()
    if a.queries:
        queries = [l.strip() for l in open(a.queries, encoding="utf-8") if l.strip() and not l.startswith("#")]
    window = (a.since, a.until)
    seen = {}
    for q in queries:
        got = 0
        for start in (0, 50, 100):
            try:
                rows = run(q, window, start, agent=agent)
            except Exception as ex:
                print("ERR", q, start, ex, file=sys.stderr); break
            for aid, pub, title, cats, summ in rows:
                got += 1
                if aid not in seen:
                    seen[aid] = [pub, title, cats, summ, q]
                else:
                    seen[aid][4] += " | " + q
            time.sleep(3.5)
            if len(rows) < 50:
                break
        print(f"{q[:60]:60s} kept {got}", file=sys.stderr)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["arxiv_id", "published", "title", "categories", "queries", "abstract"])
        for aid, (pub, title, cats, summ, qs) in sorted(seen.items(), key=lambda kv: kv[1][0], reverse=True):
            w.writerow([aid, pub, title, cats, qs, summ[:700]])
    print("candidates", len(seen))


if __name__ == "__main__":
    main()
