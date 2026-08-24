#!/usr/bin/env python3
"""memory-map — 기억 시스템의 시각 지도를 memlib 스키마 + 라이브 상태에서 생성한다.

PRD-session-memory §11. 손으로 그리지 않는다: 이 페이지가 memlib과 다른 말을 하는 것은
구조적으로 불가능해야 한다 (원장→생성물 규칙). 열람: open system/memory-map.html
"""
import datetime
import html
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M

E = html.escape

CSS = """
:root{--bg:#FAF9F6;--card:#fff;--ink:#1F2933;--mut:#6B7280;--line:#E3E0D8;--acc:#0E7C66;
--warn:#B45309;--mono:ui-monospace,'SF Mono',Menlo,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#12161A;--card:#1A2026;--ink:#E7EAEA;--mut:#93A1AD;
--line:#2A333B;--acc:#3FBFA3;--warn:#E8A34C}}
:root[data-theme=dark]{--bg:#12161A;--card:#1A2026;--ink:#E7EAEA;--mut:#93A1AD;--line:#2A333B;--acc:#3FBFA3}
:root[data-theme=light]{--bg:#FAF9F6;--card:#fff;--ink:#1F2933;--mut:#6B7280;--line:#E3E0D8;--acc:#0E7C66}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.65 ui-sans-serif,-apple-system,'Apple SD Gothic Neo',sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 22px}
h1{font-size:30px;margin:6px 0 4px}h2{font-size:21px;margin:38px 0 12px;
border-bottom:1px solid var(--line);padding-bottom:6px}
.dek{color:var(--mut);margin:0 0 8px}
.gauges{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.g{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:10px 16px}
.g b{font-size:20px}.g span{display:block;color:var(--mut);font-size:12.5px}
.g.warn b{color:var(--warn)}
.ladder{display:flex;flex-direction:column;gap:0;margin:14px 0}
.rung{display:grid;grid-template-columns:150px 1fr 230px;gap:14px;align-items:center;
background:var(--card);border:1px solid var(--line);padding:13px 16px}
.rung:first-child{border-radius:10px 10px 0 0}.rung:last-child{border-radius:0 0 10px 10px}
.rung+.rung{border-top:none}
.rung .lv{font-weight:700;font-size:13.5px}.rung .what{font-size:14.5px}
.rung .who{font-family:var(--mono);font-size:12px;color:var(--mut)}
.rung.gen{background:color-mix(in srgb,var(--card) 88%,var(--acc))}
.divider{color:var(--mut);font-size:12.5px;text-align:center;padding:7px;border:1px dashed var(--line);border-top:none}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}
.c{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:15px 17px}
.c h3{margin:0 0 7px;font-size:16.5px}.c .meta{font-size:13px;color:var(--mut);line-height:1.7}
.c code{font-family:var(--mono);font-size:12px;background:var(--bg);padding:1px 5px;border-radius:4px}
.flow{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:15px 18px;margin:10px 0}
.flow b{color:var(--acc)}
.flow ol{margin:8px 0 0;padding-left:22px}.flow li{margin:4px 0;font-size:14.5px}
.arrow{color:var(--acc);font-weight:700}
footer{color:var(--mut);font-size:12.5px;margin:36px 0 8px;font-family:var(--mono)}
"""

STORES = [
    ("개인 사실 원장", "_private/ledger/ (rec.py)", "손으로 쓰는 진실 · 불가침",
     "사람이 손으로 쓰는 사실 원장. 감사 사슬 audit, 핫셋은 생성물. 이 시스템의 관할 밖."),
    ("에피소드 원장", "~/.claude/…/*.jsonl", "원문 · 최종 검증처",
     "전 대화 전사. 회상: <code>recall.py find</code>. 백업: _private/transcript-backup/."),
    ("작업 사건 원장", "state/journal-YYYY-MM.md", "append-only",
     "type 7종. 사건 시점 기록 — 컴팩션과 독립된 추출 경로. 쓰기: <code>now.py log</code>."),
    ("스레드 서류철", " · ".join(k for k, _n, _d in M.THREADS) or "(미등록)", "손으로 쓰는 진실 (깊이)",
     "다섯 칸: 위치·확정(+왜)·기각(+왜)·미결·다음 수. 복귀 의식의 대상. 정원사가 전사 대조 검증."),
    ("트랙 정본", " · ".join(c for _k, _n, c in M.TRACKS) or "(미등록)", "손으로 쓰는 진실 (상태)",
     "트랙별 공식 상태. 낙후는 <code>now.py check</code>가 [정본 낙후]로 탐지."),
    ("NOW", "state/NOW.md", "생성물 — 손 편집 금지",
     "지금의 단일 뷰. 자기 신선도 표시. 훅이 세션 시작·재개·컴팩션 후 자동 주입. 요약과 충돌 시 승자."),
    ("의미 기억", "auto-memory (user/feedback)", "내구재 + 포인터",
     "성향·프레임·교정. 상태류는 추방(포인터만). 부패는 check·정원사가 탐지, archive/로 supersede."),
    ("결정 기록", "system/decisions.md", "append-only (DR)",
     "설계 결정의 이유·기각 대안. journal이 dr:NNN으로 참조. 건당 5줄 상한."),
]

FLOWS = [
    ("컴팩션 생존 루프", [
        "PreCompact 훅이 journal에 '컴팩션 발생' 기록",
        "컨텍스트가 요약으로 재구성됨 (다른 스레드 깊이 소실)",
        "SessionStart(compact) 훅이 <b>NOW를 자동 주입</b>",
        "요약의 상태 단언과 NOW 충돌 시 → NOW 우선 (코어 2)",
        "깊이가 필요하면 → 서류철 → recall로 원문 슬라이스"]),
    ("스레드 복귀 의식", [
        "스레드 감지 (등록된 서류철) 또는 /dossier 호출",
        "<b>서류철부터 읽는다</b> — 위치·확정·기각·미결·다음 수",
        "원문이 걸린 판정은 recall 표적 질의 (통째 붓기 금지)",
        "떠날 때 델타 ≤5줄 append (마감 의식)"]),
    ("정원사 루프 (위임된 2차 사고)", [
        "/garden → wf_gardener.js (report-only 계약)",
        "check 해석 + 부패·중복·모순 탐지 + <b>서류철 주장을 전사와 대조</b>",
        "제안 리포트 state/gardener-*.md — 집행 금지",
        "세션이 요약 제시 → 사람 판정 → 집행 → journal + DR"]),
    ("사건 기록 의식", [
        "결정·국면·정정·교훈 발생 그 턴에",
        "<code>now.py log \"[track/type] 한 줄\"</code> — 스키마 검증 후 append",
        "NOW 자동 재생성 → 다음 주입에 반영",
        "드리프트는 <code>now.py check</code> 5종 검출기가 백스톱"]),
]


def _sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)


def gauges():
    entries = M.parse_journal()
    now_age = "?"
    if os.path.exists(M.NOW_PATH):
        now_age = f"{(datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(M.NOW_PATH))).seconds // 3600}h"
    tsize = 0
    if os.path.isdir(M.TRANSCRIPTS):
        tsize = sum(os.path.getsize(os.path.join(M.TRANSCRIPTS, f))
                    for f in os.listdir(M.TRANSCRIPTS) if f.endswith(".jsonl")) // 1048576
    chk = _sh(f"python3 {HERE}/now.py check | tail -1")
    warn = "warn" if "경고" in chk else ""
    drs = 0
    if os.path.exists(M.DECISIONS):
        drs = open(M.DECISIONS, encoding="utf-8").read().count("### DR-")
    items = [
        (f"{len(entries)}", "journal 사건", ""),
        (f"{now_age}", "NOW 나이", ""),
        (f"{tsize}MB", "전사 원장", ""),
        (f"{drs}", "결정 기록(DR)", ""),
        (E(chk[:28]), "check", warn),
    ]
    return "".join(f'<div class="g {w}"><b>{v}</b><span>{k}</span></div>' for v, k, w in items)


def ladder():
    rows = [
        ("불가침", "개인 사실 원장 — rec.py, 감사 사슬", "_private/ledger/", ""),
        ("원문", "에피소드 원장 — 전 대화 전사, 최종 검증처", "recall.py find", ""),
        ("원장", "작업 사건 journal — append-only, 사건 시점 기록", "now.py log", ""),
        ("진실", "스레드 서류철 + 트랙 정본 — 손으로 쓰는 깊이·상태", "dossiers · tracker…", ""),
        ("생성물", "NOW — 재계산되는 단일 뷰, 자기 신선도 표시", "now.py render", "gen"),
        ("포인터", "auto-memory 상태류 — 내용 금지, NOW를 가리킴", "memory/*.md", "gen"),
        ("캐시", "세션 컨텍스트·컴팩션 요약 — 충돌 시 위가 이긴다", "(휘발)", "gen"),
    ]
    out = []
    for i, (lv, what, who, cls) in enumerate(rows):
        out.append(f'<div class="rung {cls}"><span class="lv">{E(lv)}</span>'
                   f'<span class="what">{what}</span><span class="who">{E(who)}</span></div>')
        if i == 3:
            out.append('<div class="divider">▲ 손으로 쓰는 진실 · ▼ 파생 (권위는 위에서 아래로)</div>')
    return "".join(out)


def main():
    cards = "".join(
        f'<div class="c"><h3>{E(n)}</h3><div class="meta"><code>{E(p)}</code><br>'
        f'<b>{E(a)}</b><br>{d}</div></div>' for n, p, a, d in STORES)
    flows = "".join(
        f'<div class="flow"><b>{E(t)}</b><ol>' + "".join(f"<li>{s}</li>" for s in steps)
        + "</ol></div>" for t, steps in FLOWS)
    threads = " · ".join(f"{n} <code>{E(d or '미지정')}</code>" for _, n, d in M.THREADS)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    page = f"""<meta charset="utf-8"><title>memory map — 세션·기억·상태</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style>
<div class="wrap">
<h1>기억 시스템 지도</h1>
<p class="dek">스키마 정본 <code>tools/memlib.py</code> + 라이브 상태에서 생성 — 손으로 그리지
않으므로 구현과 이 그림은 갈라질 수 없다. 설계 전문: <code>system/PRD-session-memory.md</code>,
결정 이력: <code>system/decisions.md</code>.</p>
<div class="gauges">{gauges()}</div>

<h2>L0 — 권위 사다리 (충돌하면 위가 이긴다)</h2>
<div class="ladder">{ladder()}</div>

<h2>L1 — 저장소 카드</h2>
<div class="cards">{cards}</div>
<p class="dek" style="margin-top:10px">살아 있는 스레드: {threads}</p>

<h2>L2 — 네 개의 루프</h2>
{flows}

<footer>생성 {ts} · python3 tools/build_memory_map.py · 훅: SessionStart(NOW 주입) ·
PreCompact(기록) — .claude/settings.json</footer>
</div>
<script>
const m=matchMedia('(prefers-color-scheme: dark)');
const ap=()=>document.documentElement.dataset.theme=m.matches?'dark':'light';
m.addEventListener('change',ap);
</script>"""
    out = os.path.join(M.ROOT, "system", "memory-map.html")
    open(out, "w", encoding="utf-8").write(page)
    print(f"memory-map.html ({os.path.getsize(out)//1024}KB)")


if __name__ == "__main__":
    main()
