#!/usr/bin/env python3
"""Generate separate public architecture and local status views.

Default: system/memory-map.html contains public design and status.
--local: _private/work/system-overview/index.html includes local status without source bodies.
The current interface is Korean; translation remains explicitly pending.
The optional local adapter exposes cycle_sources(root) and cycle_summary(path).
Writes generated views only; it does not run loops, recovery, authentication probes, or journal writes."""
import argparse
import datetime as dt
import html
import importlib.util
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(__file__))
import memlib as M

E = html.escape
CSS = """
dialog{width:min(960px,94vw);max-height:90vh;border:1px solid #dce0d8;border-radius:14px;padding:0;background:#fffefa;color:#22322d}dialog::backdrop{background:#15211aaa}dialog header{position:sticky;top:0;display:flex;justify-content:space-between;align-items:center;padding:14px 22px;background:#eeefe8;border-bottom:1px solid #dce0d8}dialog button{font:inherit;padding:5px 16px;cursor:pointer;border:1px solid #aab8aa;border-radius:20px;background:#fffefa}#reader-body{padding:14px 26px 26px}#reader-body pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:12px;background:#eef0e8;font-size:13px}#reader-body p{white-space:pre-wrap;overflow-wrap:anywhere}dialog table{margin:10px 0}
:root{--bg:#f5f4ef;--paper:#fffefa;--ink:#22322d;--muted:#68726d;--line:#dce0d8;--green:#17674f;--amber:#946217;--red:#a23c35}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 -apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif}
main{max-width:1100px;margin:auto;padding:34px 24px 50px}a{color:var(--green);text-underline-offset:4px}a:hover{text-decoration-thickness:2px}h1{font-size:36px;letter-spacing:-1px;line-height:1.3;margin:10px 0 14px}h2{font-size:24px;line-height:1.4;margin:30px 0 12px}h3{font-size:18px;line-height:1.4;margin:0 0 10px}p{margin:8px 0 14px}.eyebrow{color:var(--green);font-weight:650;letter-spacing:.04em;font-size:13px}.muted{color:var(--muted)}.small{font-size:13px}.lead{max-width:720px;font-size:18px}.nav{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}.nav a{padding:9px 16px;border:1px solid var(--line);border-radius:30px;text-decoration:none}.nav a[aria-current=true]{background:var(--ink);color:white;border-color:var(--ink)}.panel{display:block}.js .panel{display:none}.js .panel.active{display:block}.hero{padding:24px;background:var(--paper);border:1px solid var(--line);border-left:5px solid var(--green);border-radius:12px}.hero.warn{border-left-color:var(--amber)}.hero h2{margin-top:0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:18px 0}.card{background:var(--paper);padding:20px;border:1px solid var(--line);border-radius:12px}.metric{font-size:28px;font-weight:650;display:block;line-height:1.3;margin:4px 0}.badge{display:inline-block;background:#e6eee8;color:var(--green);border-radius:5px;font-size:12px;padding:2px 8px;margin:3px 0}.badge.warn{background:#f5ebd7;color:var(--amber)}.badge.unknown{background:#e9eae6;color:#5f6561}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--paper)}table{width:100%;border-collapse:collapse;font-size:14px;text-align:left}th,td{padding:12px 15px;border-bottom:1px solid var(--line);vertical-align:top}th{font-weight:600;background:#efefe8}tr:last-child td{border:0}code{font:12px/1.7 ui-monospace,Menlo,monospace;overflow-wrap:anywhere;background:#eceee7;border-radius:4px;padding:2px 5px}details{border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:12px 0;background:var(--paper)}summary{cursor:pointer;font-weight:600}ol{padding-left:22px}.flow{display:flex;gap:10px;align-items:stretch;margin:20px 0}.step{flex:1;background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:15px;min-width:0}.step strong{display:block;margin-bottom:7px}.arrow{align-self:center;color:var(--green)}footer{border-top:1px solid var(--line);margin-top:32px;padding-top:15px;color:var(--muted);font-size:12px}.notice{padding:12px 16px;background:#edece4;border-radius:8px}.sources{overflow-wrap:anywhere}@media(max-width:720px){main{padding:22px 16px}h1{font-size:29px}.grid{grid-template-columns:1fr}.flow{flex-direction:column}.arrow{transform:rotate(90deg)}.hero{padding:18px}th,td{padding:10px;font-size:13px}.nav a{font-size:14px;padding:7px 12px}}
"""


JS = r"""
document.documentElement.classList.add('js');
function show(){let id=location.hash.slice(1)||'status';if(!['status','flow','sources'].includes(id))id='status';document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===id));document.querySelectorAll('.nav a').forEach(a=>a.setAttribute('aria-current',String(a.hash==='#'+id)));}
addEventListener('hashchange',show);show();
const reader=document.querySelector('#reader'), body=document.querySelector('#reader-body');
document.querySelector('#reader-close').onclick=()=>reader.close();
function inline(el,text,base){
 const rx=/\[([^\]]+)\]\(([^)]+)\)/g;let from=0,m;
 while((m=rx.exec(text))){el.append(document.createTextNode(text.slice(from,m.index)));let url;
  try{url=new URL(m[2],base);}catch(e){}
  if(url&&['http:','https:','file:'].includes(url.protocol)){const a=document.createElement('a');a.textContent=m[1];a.href=url.href;el.append(a);}else el.append(document.createTextNode(m[1]));from=rx.lastIndex;
 }el.append(document.createTextNode(text.slice(from)));
}
function renderText(text,base=location.href){
 body.replaceChildren();let code=null,table=null;
 for(const line of text.split('\n')){
  if(line.startsWith('```')){if(code){code=null;}else{code=document.createElement('pre');body.append(code);}continue;}
  if(code){code.textContent+=line+'\n';continue;}
  if(/^\|[- :|]+\|$/.test(line))continue;
  if(line.startsWith('|')){
   if(!table){table=document.createElement('table');let wrap=document.createElement('div');wrap.className='tablewrap';wrap.append(table);body.append(wrap);}
   let row=table.insertRow();line.replace(/^\||\|$/g,'').split('|').forEach(cell=>inline(row.insertCell(),cell.trim().replace(/`/g,''),base));continue;
  }table=null;
  let anchor=line.match(/^<a id="([\w-]+)"><\/a>$/);if(anchor){let span=document.createElement('span');span.id='doc-'+anchor[1];body.append(span);continue;}
  if(!line.trim())continue;
  let m=line.match(/^(#{1,6})\s+(.*)/);let el=document.createElement(m?'h'+Math.min(m[1].length+1,4):'p');
  inline(el,(m?m[2]:line).replace(/\*\*([^*]+)\*\*/g,'$1').replace(/`([^`]+)`/g,'$1').replace(/^>\s?/,''),base);body.append(el);
 }
}
document.addEventListener('click',async e=>{
 const a=e.target.closest('a');if(!a||!new URL(a.href).pathname.endsWith('.md'))return;
 if(new URL(a.href).origin!==location.origin)return;
 e.preventDefault();document.querySelector('#reader-title').textContent=a.textContent;if(!reader.open)reader.showModal();renderText('문서를 여는 중입니다.');
 try{const response=await fetch(a.href);if(!response.ok)throw Error('HTTP '+response.status);renderText(await response.text(),a.href);reader.scrollTop=0;const hash=new URL(a.href).hash.slice(1);if(hash)document.getElementById('doc-'+decodeURIComponent(hash))?.scrollIntoView();}
 catch(error){renderText('문서를 열지 못했습니다. 원본 위치: '+a.getAttribute('href')+'\n로컬 서버에서 지도를 열어야 문서를 바로 읽을 수 있습니다.');}
});
"""


def read_json(path):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None


def file_observation(path, now):
    path = Path(path)
    try:
        # Availability/freshness does not prove content, injection, or effectiveness.
        stat = path.stat()
        age = (now - dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc)).total_seconds() / 3600
        return {"status": "STALE" if age > 48 else "AVAILABLE", "age_hours": round(age, 1)}
    except OSError:
        return {"status": "UNAVAILABLE", "age_hours": None}


def observe(local=False):
    root = Path(M.ROOT)
    now = dt.datetime.now(dt.timezone.utc)
    data = {"observed_at": now.astimezone().isoformat(timespec="seconds"), "local": local,
            "public_now": file_observation(root / "state/NOW.md", now),
            "local_now": file_observation(root / "_private/state/NOW.md", now) if local else None,
            "journal_events": len(M.parse_journal(visibility="public")), "sources": [], "cycles": [],
            "loop_status": "UNAVAILABLE", "loop_error": None, "effect": "UNKNOWN"}
    for name, kind, base, pattern in M.EPISODIC_SOURCES:
        # Public snapshots expose registry kinds only, never home paths or availability.
        label = name + (" · 보관" if Path(base).name == "archived_sessions" else " · 활성" if kind == "codex-jsonl" else "")
        data["sources"].append({"name": label, "kind": kind,
                                "status": ("AVAILABLE" if Path(base).is_dir() else "UNAVAILABLE") if local else "UNMEASURED"})
    if not local:
        return data
    script = root / "tools/papers_apply.py"
    if not script.is_file():
        return data
    try:
        spec = importlib.util.spec_from_file_location("map_cycle_reader", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not all(callable(getattr(mod, name, None)) for name in ("cycle_sources", "cycle_summary")):
            data["loop_error"] = "판정 결과를 읽는 인터페이스가 아직 없습니다."
            return data
        for source, parent, suffix in mod.cycle_sources(str(root)):
            parent = Path(parent)
            if not parent.resolve().is_relative_to(root.resolve()):
                raise ValueError("adapter location outside instance")
            for folder in sorted(parent.glob("*")):
                name = folder.name.removesuffix(suffix) if suffix else folder.name
                try:
                    date = dt.date.fromisoformat(name)
                except ValueError:
                    continue
                if folder.is_symlink() or not 0 <= (now.date() - date).days <= 35:
                    continue
                if not (folder / "APPLY.md").is_file():
                    continue
                summary = mod.cycle_summary(str(folder))
                data["cycles"].append({"date": name, "source": source, "path": str(folder.relative_to(root)),
                                       "summary": summary})
        data["loop_status"] = "AVAILABLE"
    except Exception as exc:
        # Error text can contain private paths or content; disclose its type only.
        data["loop_error"] = f"관측 실패 ({type(exc).__name__}). 상태를 정상으로 간주하지 않습니다."
    return data


def render(data, output):
    root = Path(M.ROOT)
    def link(path, label):
        if not (root / path).is_file():
            return f'<span class="muted">{E(label)} (이 인스턴스에 없음)</span>'
        target = os.path.relpath(root / path, output.parent)
        return f'<a href="{quote(target, safe="/.-")}">{E(label)}</a>'
    def badge(value):
        cls = "warn" if value in ("STALE", "FAIL") else "unknown" if value in ("UNKNOWN", "UNAVAILABLE", "UNMEASURED") else ""
        return f'<span class="badge {cls}">{E(value)}</span>'
    cycles = data["cycles"]
    selected = sum(c["summary"].get("selected", 0) for c in cycles)
    totals = {}
    for c in cycles:
        for key, value in c["summary"].get("counts", {}).items():
            totals[key] = totals.get(key, 0) + value
    applied = totals.get("applied", 0)
    failed = sum(totals.get(k, 0) for k in ("repair-exhausted", "legacy-failed"))
    if not data["local"]:
        title, explain = "대화를 이어가는 구조를 한눈에", "이 페이지는 공개 설계 지도입니다. 개인 상태를 읽지 않습니다. 현재 관측은 로컬 지도를 생성해 확인합니다."
    elif data["loop_status"] != "AVAILABLE":
        title, explain = "현재 실행 결과를 아직 확인하지 못했어요", data["loop_error"] or "루프 결과가 없거나 읽을 수 없습니다. 미측정을 정상으로 간주하지 않습니다."
    elif failed:
        title, explain = f"구현이 멈춘 과거 묶음 {failed}개", f"최근 35일 기록에서 {selected}개를 선택하고 {applied}개를 적용했습니다. 기각 이유와 구현 실패를 구분해 확인합니다. 이 기록만으로 현재 코드 수정의 효과를 판단할 수는 없습니다."
    else:
        title, explain = f"선택 {selected}개 · 적용 {applied}개", "절차가 끝난 것과 실제로 도움이 된 것은 다릅니다. 적용 후 재발 여부와 사용자의 추가 설명 부담은 후속 관측이 필요합니다."
    if not data["local"]:
        next_action = "현재 상태가 필요하면 로컬 지도를 생성합니다. 아래 흐름과 문서에서 설계를 확인할 수 있습니다."
        approval = "공개 설계에는 개인 승인 대기 상태를 담지 않습니다."
    elif data["loop_status"] != "AVAILABLE":
        next_action = "판정 기록을 읽을 수 없는 원인을 먼저 확인합니다. 미확인 상태에서 재실행하지 않습니다."
        approval = "현재 승인 대기 여부도 미확인입니다."
    elif failed:
        next_action = "메인 에이전트가 실패 기록과 재개 조건을 확인합니다. 소진된 명세는 자동 반복하지 않습니다."
        approval = "보류 이유는 판정 원문에서 확인합니다." if totals.get("held", 0) else "선택된 묶음 기록에는 승인 대기가 없습니다."
    else:
        next_action = "다음 실행의 결과와 같은 마찰의 재발 여부를 관측합니다."
        approval = "보류 이유는 판정 원문에서 확인합니다." if totals.get("held", 0) else "선택된 묶음 기록에는 승인 대기가 없습니다."
    overlay = ""
    if data["local"]:
        obs = data["local_now"]
        overlay = f'<p class="small">local overlay: {badge(obs["status"])} · {obs["age_hours"] if obs["age_hours"] is not None else "미확인"}시간<br>{link("_private/state/NOW.md", "local NOW 보기")}</p>'
    rows = []
    for c in sorted(cycles, key=lambda c: (c["date"], c["source"]), reverse=True):
        s = c["summary"]
        counts = s.get("counts", {})
        fail = sum(counts.get(k, 0) for k in ("repair-exhausted", "legacy-failed"))
        names = {"legacy-review": "옛 리뷰 실패", "legacy-delivery": "옛 출력 누락", "review": "리뷰", "delivery": "출력", "tests": "테스트", "patch": "패치", "interrupted": "중단"}
        stages = ', '.join(f'{names.get(k,k)} {v}' for k,v in s.get('failure_stages',{}).items())
        rows.append(f'<tr><td>{E(c["date"])}<br>{E({"papers":"논문", "garden":"정원"}.get(c["source"], c["source"]))}</td><td>{s.get("selected",0)}</td><td>{counts.get("applied",0)}</td><td>{fail}<br><span class="small muted">{E(stages)}</span></td><td>{counts.get("held",0)}</td><td>{link(c["path"]+"/APPLY.md", "판정 원문")}</td></tr>')
    table = '<div class="tablewrap"><table><thead><tr><th>주기</th><th>선택</th><th>적용</th><th>구현 실패</th><th>보류</th><th>근거</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>' if rows else '<p class="notice">이 화면에는 관측된 주기 기록이 없습니다.</p>'
    source_rows = ''.join(f'<tr><td>{E(s["name"])}</td><td><code>{E(s["kind"])}</code></td><td>{badge(s["status"])}</td></tr>' for s in data["sources"])
    age = data["public_now"]["age_hours"]
    age_label = f'{age:g}시간' if age is not None else '미확인'
    local_note = ('개인 원문은 화면에 복사하지 않습니다. 로컬 관측과 원문 링크가 있어 외부 공유용이 아닙니다.' if data["local"] else '현재 상태가 필요하면 <code>python3 tools/build_memory_map.py --local</code>을 실행합니다.')
    dossiers = ('<h2>작업 서류철</h2><p>' + ' · '.join(link(path, name) for _, name, path in M.THREADS if path) + '</p>') if data['local'] else ''
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>기억 시스템 지도</title><style>{CSS}</style></head><body><main>
<div class="eyebrow">기억 · 복귀 · 자율 개선</div><h1>말했던 맥락으로, 다음 일을 이어가기</h1>
<p class="lead">기록이 쌓이는 데서 끝나지 않고, 필요한 근거를 찾아 실제 작업에 쓰는 시스템입니다.</p>
<p class="small muted">관측 {E(data['observed_at'])} · {'로컬 전용' if data['local'] else '공개 설계'} 스냅샷 · 새로고침만으로 다시 측정되지는 않습니다.</p>
<nav class="nav" aria-label="지도 탐색"><a href="#status" aria-current="true">지금 상태</a><a href="#flow">어떻게 이어지나</a><a href="#sources">근거와 권한</a></nav>
<section id="status" class="panel active"><div class="hero {'warn' if failed else ''}"><h2>{E(title)}</h2><p>{E(explain)}</p><p class="small"><b>다음 작업:</b> {E(next_action)}</p><p class="small muted">{E(approval)}</p></div>
<div class="grid"><div class="card"><h3>현재 상태의 입구</h3><span class="metric">{age_label}</span>{badge(data['public_now']['status'])}<p class="small">public NOW 파일 나이입니다. 48시간 초과를 STALE로 표시합니다. 내용의 최신성이나 훅 주입 성공을 보증하지 않습니다.</p>{overlay}{link('state/NOW.md','public NOW 보기')}</div><div class="card"><h3>판단할 근거</h3><p>원문 → 현재 결정 → 실행 증거</p><p class="small">어떤 주장을 확인하는지에 따라 돌아갈 곳이 달라집니다.</p><a href="#sources">근거의 역할 보기</a><p class="small muted">public journal 사건 {data['journal_events']}건. 저장량은 개선 효과가 아닙니다.</p></div><div class="card"><h3>실제 도움이 됐나</h3><span class="metric">UNKNOWN</span><p class="small">테스트·적용 뒤 같은 마찰이 줄었는지 별도로 관측합니다. 이 지도는 효과를 추정하지 않습니다.</p>{link('system/design-memory-runtime.md','검증 연결 보기')}</div></div>
<h2>최근 주기의 흐름</h2><p class="muted small">최근 35일의 저장된 판정 기록. “구현 실패”에는 옛 형식의 구현 기각과 수정 예산 소진을 포함합니다. 정당한 아이디어 기각과는 별개입니다.</p>{table}<p>{link('system/loops.md','실행·정지와 복구 방법')} · {link('system/design-memory-runtime.md','설계와 검증')}</p></section>
<section id="flow" class="panel"><h2>기억이 답변까지 도달하는 길</h2><p class="muted">아래 흐름은 설계 설명입니다. 각 단계의 존재가 다음 단계의 성공을 보증하지 않습니다.</p><div class="flow"><div class="step"><strong>1. 원점을 남긴다</strong><span class="small">사용자 발화, 결정, 실행 결과를 출처와 함께 보존합니다.</span></div><span class="arrow">→</span><div class="step"><strong>2. 같은 범위에서 찾는다</strong><span class="small">인스턴스·역할·요약 구분을 적용한 후보만 검색합니다.</span></div><span class="arrow">→</span><div class="step"><strong>3. 현재 할 일을 복원한다</strong><span class="small">NOW와 서류철을 읽고, 필요한 원문까지 돌아갑니다.</span></div><span class="arrow">→</span><div class="step"><strong>4. 결과를 확인한다</strong><span class="small">실제 행동과 사용자가 겪는 추가 왕복을 확인합니다.</span></div></div>
<div class="grid"><article class="card"><h3>새 세션이라면</h3><ol><li>public NOW와 local overlay를 함께 읽습니다.</li><li>지금 작업의 서류철을 엽니다.</li><li>없는 정보만 좁혀 묻습니다.</li></ol>{link('system/PRD-session-memory.md','복귀 요구')}</article><article class="card"><h3>옛 맥락이 필요하면</h3><ol><li>기존 결정과 원점 포인터를 찾습니다.</li><li>회상 결과의 파일·행·ID를 확인합니다.</li><li>새 증거가 있으면 옛 결정을 재검토합니다.</li></ol>{link('system/PRD-info-architecture.md','정보와 정정 요구')}</article><article class="card"><h3>개선안이 실패하면</h3><ol><li>아이디어·출력·구현·적용 중 실패 단계를 가릅니다.</li><li>구현 오류는 제한된 수정과 재검증으로 돌립니다.</li><li>예산 소진은 드러내고 자동 반복하지 않습니다.</li></ol>{link('system/loops.md','루프 운영')}</article></div>
<details><summary>두 종류의 정원 작업</summary><p>수동 <code>/garden</code>은 검토 보고서를 만듭니다. 정기 <code>garden_cycle.sh</code>가 설치되고 별도로 위임된 인스턴스에서는 판정·구현·검증을 거칩니다. 같은 이름이 권한까지 같다는 뜻은 아닙니다.</p></details></section>
<section id="sources" class="panel"><h2>무엇을 주장하느냐에 따라 근거가 달라진다</h2><div class="tablewrap"><table><thead><tr><th>확인할 것</th><th>돌아갈 곳</th><th>주의할 점</th></tr></thead><tbody><tr><td>사용자가 실제로 한 말</td><td>전사 원문과 native ID</td><td>assistant 요약을 사용자 발화로 승격하지 않음</td></tr><tr><td>지금 유효한 결정</td><td>최근 결정·정정·적용 범위</td><td>오래된 원문이라는 이유만으로 최신 결정을 이기지 않음</td></tr><tr><td>현재 진행 상태</td><td>public NOW + local overlay</td><td>local 부재는 “없음”이 아니라 unavailable</td></tr><tr><td>실제로 실행됐는가</td><td>파일·테스트·런타임 영수증</td><td>설정 존재와 실행·효과를 구별</td></tr></tbody></table></div>
{dossiers}<h2>등록된 검색 소스</h2><p class="small muted">배선은 <code>system/memory-config.json</code>에서 읽습니다. AVAILABLE은 디렉터리 존재만 뜻합니다. 본문 완전성은 별도 검사 대상입니다.</p><div class="tablewrap"><table><thead><tr><th>소스</th><th>형식</th><th>경로 관측</th></tr></thead><tbody>{source_rows}</tbody></table></div>
<h2>문서 역할</h2><p class="sources">{link('system/PRD-info-architecture.md','정보 PRD')}는 원점·정정·국경, {link('system/PRD-session-memory.md','세션 PRD')}는 복귀·성공 조건을 정합니다. {link('system/design-memory-runtime.md','설계 문서')}는 모듈·상태·테스트를 연결하고, {link('system/loops.md','운영 문서')}는 실행·중단을 다룹니다. 권한 변경 이유는 {link('system/decisions.md','DR')}에 남깁니다.</p>
<p class="notice">{local_note}</p></section>
<footer>기억 시스템 지도 · tools/build_memory_map.py · 설명은 설계 문서를, 숫자는 관측 시점의 파일을 따릅니다. 파일 존재·검사 통과·사용자 효과는 서로 다른 증거입니다.</footer></main>
<dialog id="reader"><header><strong id="reader-title">문서</strong><button id="reader-close" type="button">닫기</button></header><article id="reader-body"></article></dialog><script>{JS}</script></body></html>'''


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--local", action="store_true", help="관측과 링크가 담긴 로컬 전용 지도")
    args = ap.parse_args(argv)
    output = Path(M.ROOT) / ("_private/work/system-overview/index.html" if args.local else "system/memory-map.html")
    data = observe(args.local)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data, output), encoding="utf-8")
    if args.local:
        output.chmod(0o600)
        snapshot = output.with_name("snapshot.json")
        snapshot.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        snapshot.chmod(0o600)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
