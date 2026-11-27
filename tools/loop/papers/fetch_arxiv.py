#!/usr/bin/env python3
"""Extract arXiv HTML as plain text, falling back to PDF plus pdftotext. Skip existing files.

Every request names the client of loop.papers_client and loop.papers_contact.

Usage: fetch_arxiv.py top.tsv OUT_DIR
Input rows: arxiv_id<TAB>slug. Output: OUT_DIR/<id>-<slug>.txt."""
import csv, html, os, re, subprocess, sys, time, urllib.request
from html.parser import HTMLParser

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402

if sys.argv[1:2] in (["-h"], ["--help"]) or len(sys.argv) != 3:
    print(__doc__)
    sys.exit(0 if sys.argv[1:2] in (["-h"], ["--help"]) else 2)
PAPERS = [tuple(r[:2]) for r in csv.reader(open(sys.argv[1], encoding="utf-8"), delimiter="\t")
          if r and not r[0].startswith("#")]
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": loop_config.papers_user_agent()}
BLOCK = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br", "figcaption",
         "table", "blockquote", "pre"}


class T(HTMLParser):
    def __init__(s):
        super().__init__(); s.out = []; s.skip = 0

    def handle_starttag(s, tag, a):
        if tag in ("script", "style", "svg", "math"): s.skip += 1
        if tag in BLOCK: s.out.append("\n")
        if tag == "math": s.out.append(" [math] ")

    def handle_endtag(s, tag):
        if tag in ("script", "style", "svg", "math"): s.skip = max(0, s.skip - 1)
        if tag in BLOCK: s.out.append("\n")

    def handle_data(s, d):
        if not s.skip: s.out.append(d)


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()


def html_to_text(b):
    p = T(); p.feed(b.decode("utf-8", "replace")); t = html.unescape("".join(p.out))
    t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n\s*\n+", "\n", t); return t.strip()


log = []
for pid, slug in PAPERS:
    out = os.path.join(OUT, f"{pid}-{slug}.txt")
    if os.path.exists(out):
        log.append(f"{pid} exists"); continue
    try:
        b = get(f"https://arxiv.org/html/{pid}"); t = html_to_text(b); src = "html"
        if len(t) < 5000: raise ValueError("html too short")
    except Exception as e:
        try:
            pdf = get(f"https://arxiv.org/pdf/{pid}"); pdfp = os.path.join(OUT, f"{pid}.pdf")
            open(pdfp, "wb").write(pdf)
            t = subprocess.run(["pdftotext", "-layout", pdfp, "-"], capture_output=True, text=True,
                               timeout=120).stdout; src = "pdf"
        except Exception as e2:
            log.append(f"{pid} FAILED html={e} pdf={e2}"); continue
    open(out, "w", encoding="utf-8").write(t); log.append(f"{pid} {src} {len(t)} chars"); time.sleep(3)
print("\n".join(log))
