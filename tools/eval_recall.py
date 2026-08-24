#!/usr/bin/env python3
"""eval_recall — 회상이 실제로 찾아내는가를 잰다.

**왜 있나.** PRD-session-memory §3.7이 임베딩 도입 게이트를 이렇게 정해뒀다:
"known-item 실패가 기록으로 3회 누적되면 재평가." 그런데 2026-08-24 실측 결과
**journal에 그 계수가 0건이었다.** 아무도 안 세고 있었으므로 게이트는 영원히 안 열린다.
결정을 문서에 적어두는 것과 그 결정이 발동할 수 있게 만드는 것은 다른 일이다.

**무엇을 재나.** 전사에서 과거 발화를 무작위로 뽑고, 그 발화의 특징적인 낱말로 회상을 걸어
**그 발화가 결과에 돌아오는가**를 본다. hit@k.

**무엇을 못 재나 (숨기지 않는다).**
- **표현 불일치.** 같은 개념을 다른 어휘로 물었을 때를 못 잰다. 질의를 원문에서 뽑기 때문이다.
  그런데 §3.7의 두 번째 트리거가 정확히 그 경우다. 그걸 재려면 모델이 바꿔 말해줘야 한다.
  즉 **이 도구가 재는 것은 바닥이다.** 바닥에서 실패하면 위는 볼 것도 없고,
  바닥을 통과해도 위가 통과한다는 뜻은 아니다.
- 회상 결과가 **쓸모 있었는가**. 찾은 것과 도움이 된 것은 다르다.

사용:
    python3 tools/eval_recall.py [--n 20] [--max 8] [--quiet]
결과는 state/metrics-recall.jsonl에 한 줄 append (append-only, 추이용).
"""
import argparse
import collections
import glob
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M

METRICS = os.path.join(M.STATE, "metrics-recall.jsonl")

# 질의어로 쓰기에 나쁜 것들. 흔하거나 검색에 의미가 없다.
STOP = set("그리고 그런데 그래서 하지만 이거 저거 그거 이건 저건 그건 있다 없다 한다 된다 "
           "the and for that this with from have been will你 그럼 근데 아니 네가 내가 우리 "
           "너무 정말 진짜 조금 많이 이제 지금 다시 그냥 좀더 같이 대해 위해 통해".split())
TOKEN = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9_.-]{3,}")


def _turns(limit_files=1):
    """claude 전사에서 (ts, role, text) 목록. 최신 세션부터."""
    out = []
    for name, kind, base, pat in M.EPISODIC_SOURCES:
        if kind != "claude-jsonl":
            continue
        files = sorted(glob.glob(os.path.join(base, pat)), key=os.path.getmtime, reverse=True)
        for fp in files[:limit_files]:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("isCompactSummary"):
                        continue
                    got = __import__("recall")._text_of(d)
                    if not got:
                        continue
                    r, text = got
                    ts = (d.get("timestamp") or "")[:16]
                    if ts and len(text) > 200 and not text.startswith("This session is being"):
                        out.append((ts, r, text))
    return out


def _doc_freq(turns):
    """낱말별 등장 발화 수. 희소한 낱말이 좋은 질의어다."""
    df = collections.Counter()
    for _ts, _r, t in turns:
        for w in set(TOKEN.findall(t)):
            df[w] += 1
    return df


# 난이도. 질의어의 문서빈도(df) 대역으로 정한다.
#   rare  = 그 발화에만 있는 토큰 (UUID, 희귀 어형). **너무 쉽다 — 바닥의 바닥**
#   topic = 흔한 주제어. 후보가 수십~수백이라 순위 경쟁이 생긴다. **실사용에 가깝다**
# 2026-08-24 실측: rare로 재니 12/12(100%)였다. 그건 grep이 정확한 토큰을 찾는다는 확인일 뿐
# 아무것도 안 잰 것이다. 사람은 UUID로 검색하지 않는다.
BANDS = {"rare": (1, 5), "mid": (6, 40), "topic": (41, 400)}


def _query_for(text, df, n_terms=2, band="topic"):
    """이 발화를 찾기 위한 질의어. 지정한 df 대역의 낱말 n개를 OR로 묶는다.

    사람이 "그때 그 얘기"를 찾을 때 쓰는 것에 가깝게: 정확한 문장이 아니라
    기억에 남은 낱말 두어 개. 그 낱말은 보통 **흔한 주제어**다.
    """
    lo, hi = BANDS[band]
    words = [w for w in set(TOKEN.findall(text)) if w not in STOP]
    inband = [w for w in words if lo <= df.get(w, 0) <= hi]
    if len(inband) < n_terms:
        return None                                   # 이 대역의 낱말이 부족한 발화는 건너뛴다
    inband.sort(key=lambda w: (-df[w], -len(w)))      # 대역 안에서 가장 흔한 것 = 가장 어려움
    return "|".join(re.escape(w) for w in inband[:n_terms])


def run(n=20, max_hits=8, seed=20260824, quiet=False, band="topic"):
    turns = _turns()
    if len(turns) < n * 2:
        print(f"전사 발화가 부족하다 ({len(turns)}개). 세션을 더 쌓고 다시 재라.")
        return 1
    df = _doc_freq(turns)
    rnd = random.Random(seed)                        # 씨앗 고정 — 추이를 비교하려면 같은 표본
    sample = rnd.sample(turns, n)

    hits, misses, skipped = 0, [], 0
    for ts, role, text in sample:
        q = _query_for(text, df, band=band)
        if not q:
            skipped += 1
            continue
        r = subprocess.run([sys.executable, os.path.join(HERE, "recall.py"), "find", q,
                            "--max", str(max_hits), "--around", "0"],
                           capture_output=True, text=True, cwd=M.ROOT)
        # 출력의 매치 헤더에 찍히는 KST 시각으로 원본 발화를 식별한다
        want = __import__("recall")._kst(ts)
        found = want in r.stdout
        if found:
            hits += 1
        else:
            misses.append({"ts": ts, "role": role, "q": q, "head": text[:70].replace("\n", " ")})
        if not quiet:
            print(f"  {'찾음' if found else '실패'}  {want}  /{q[:46]}/")

    tried = n - skipped
    rate = hits / tried if tried else 0.0
    rec = {"date": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M"),
           "band": band, "n": tried, "hits": hits, "rate": round(rate, 3), "max_hits": max_hits,
           "seed": seed, "corpus_turns": len(turns), "skipped": skipped,
           "misses": misses[:5]}
    os.makedirs(M.STATE, exist_ok=True)
    with open(METRICS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n[{band}] hit@{max_hits} = {hits}/{tried} ({rate:.0%}) · 코퍼스 발화 {len(turns)}개"
          + (f" · 질의어 못 뽑음 {skipped}개" if skipped else ""))
    if misses:
        print(f"\n실패 {len(misses)}건 (§3.7 known-item 게이트의 계수 대상):")
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
