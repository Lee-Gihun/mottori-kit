#!/usr/bin/env python3
"""Generate the public design map at paths.memory_map().

The page is a design view: it carries no observation time or live counts, so
rerunning it does not change the file unless the design or registry changed.
Writes the generated view only; it does not run loops, recovery, authentication probes, or journal writes."""
import argparse
import html
import os
from pathlib import Path
import sys
from urllib.parse import quote

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import paths as P

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
 e.preventDefault();document.querySelector('#reader-title').textContent=a.textContent;if(!reader.open)reader.showModal();renderText('Opening the document.');
 try{const response=await fetch(a.href);if(!response.ok)throw Error('HTTP '+response.status);renderText(await response.text(),a.href);reader.scrollTop=0;const hash=new URL(a.href).hash.slice(1);if(hash)document.getElementById('doc-'+decodeURIComponent(hash))?.scrollIntoView();}
 catch(error){renderText('Could not open the document. Its location: '+a.getAttribute('href')+'\nOpen the map from a local server to read documents in place.');}
});
"""


def observe():
    data = {"sources": []}
    for name, kind, base, pattern in C.episodic_sources():
        # Public snapshots expose registry kinds only, never home paths or availability.
        label = name + (" · archived" if Path(base).name == "archived_sessions" else " · active" if kind == "codex-jsonl" else "")
        data["sources"].append({"name": label, "kind": kind, "status": "UNMEASURED"})
    return data


def render(data, output):
    root = Path(P.instance_root())
    def link(path, label):
        if not (root / path).is_file():
            return f'<span class="muted">{E(label)} (not in this instance)</span>'
        target = os.path.relpath(root / path, output.parent)
        return f'<a href="{quote(target, safe="/.-")}">{E(label)}</a>'
    def badge(value):
        cls = "warn" if value in ("STALE", "FAIL") else "unknown" if value in ("UNKNOWN", "UNAVAILABLE", "UNMEASURED") else ""
        return f'<span class="badge {cls}">{E(value)}</span>'
    title, explain = "How a conversation is carried on, at a glance", "This page is a public design map. It holds no personal state and no current observations."
    next_action = "The flow and the documents below show the design."
    approval = "The public design holds no personal approvals waiting."
    source_rows = ''.join(f'<tr><td>{E(s["name"])}</td><td><code>{E(s["kind"])}</code></td><td>{badge(s["status"])}</td></tr>' for s in data["sources"])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Memory system map</title><style>{CSS}</style></head><body><main>
<div class="eyebrow">Memory · return · self-improvement</div><h1>Carry on the next piece of work from what was said</h1>
<p class="lead">A system that does not stop at piling up records: it finds the evidence a task needs and uses it in the work.</p>
<nav class="nav" aria-label="Map navigation"><a href="#status" aria-current="true">Current state</a><a href="#flow">How it carries on</a><a href="#sources">Evidence and authority</a></nav>
<section id="status" class="panel active"><div class="hero"><h2>{E(title)}</h2><p>{E(explain)}</p><p class="small"><b>Next step:</b> {E(next_action)}</p><p class="small muted">{E(approval)}</p></div>
<div class="grid"><div class="card"><h3>Where the current state starts</h3><p class="small">The current state is public NOW read together with the local overlay. This map shows neither their age nor their content.</p>{link('state/NOW.md','See public NOW')}</div><div class="card"><h3>Evidence to judge by</h3><p>Original words → current decision → evidence of execution</p><p class="small">Where to go back to depends on which claim is being checked.</p><a href="#sources">See what each kind of evidence is for</a></div><div class="card"><h3>Did it actually help?</h3><span class="metric">UNKNOWN</span><p class="small">Whether the same friction went down after tests and adoption is observed separately. This map does not estimate the effect.</p>{link('system/specs/design-memory-runtime.md','See how it is verified')}</div></div>
<p>{link('system/loop/README.md','Running, stopping and recovery')} · {link('system/specs/design-memory-runtime.md','Design and verification')}</p></section>
<section id="flow" class="panel"><h2>How memory reaches an answer</h2><p class="muted">The flow below describes the design. That a step exists does not guarantee the next step succeeds.</p><div class="flow"><div class="step"><strong>1. Keep the origin</strong><span class="small">The user's words, decisions and results of execution are kept with their source.</span></div><span class="arrow">→</span><div class="step"><strong>2. Search within the same scope</strong><span class="small">Only candidates that pass the instance, role and summary distinctions are searched.</span></div><span class="arrow">→</span><div class="step"><strong>3. Restore the current task</strong><span class="small">NOW and the dossier are read, going back to the original words where needed.</span></div><span class="arrow">→</span><div class="step"><strong>4. Check the result</strong><span class="small">The actual actions and the extra round trips the user goes through are checked.</span></div></div>
<div class="grid"><article class="card"><h3>In a new session</h3><ol><li>Read public NOW together with the local overlay.</li><li>Open the dossier of the current work.</li><li>Ask only about what is missing.</li></ol>{link('system/specs/PRD-session-memory.md','Return requirements')}</article><article class="card"><h3>When old context is needed</h3><ol><li>Find the existing decisions and origin pointers.</li><li>Check the file, line and ID of each recall result.</li><li>Reconsider an old decision when there is new evidence.</li></ol>{link('system/specs/PRD-info-architecture.md','Information and correction requirements')}</article><article class="card"><h3>When an improvement fails</h3><ol><li>Tell which stage failed: idea, output, implementation or adoption.</li><li>Send an implementation error back through a bounded fix and a new verification.</li><li>Show a spent budget and do not repeat automatically.</li></ol>{link('system/loop/README.md','Running the loops')}</article></div>
<details><summary>What /garden may change</summary><p>The manual <code>/garden</code> writes a review report and corrects only what you delegated. It inherits no authority of the improvement loop.</p></details></section>
<section id="sources" class="panel"><h2>The evidence depends on what is claimed</h2><div class="tablewrap"><table><thead><tr><th>To check</th><th>Where to go back to</th><th>Watch for</th></tr></thead><tbody><tr><td>What the user actually said</td><td>The transcript text and its native ID</td><td>An assistant summary is never promoted to the user's words</td></tr><tr><td>The decision in force now</td><td>The latest decisions, corrections and their scope</td><td>Older original words do not beat a later decision just by being original</td></tr><tr><td>The current state of work</td><td>public NOW + local overlay</td><td>A missing local overlay is unavailable, not “none”</td></tr><tr><td>Whether it actually ran</td><td>Files, tests and runtime receipts</td><td>A setting that exists is not a run, and a run is not an effect</td></tr></tbody></table></div>
<h2>Registered search sources</h2><p class="small muted">The wiring is read from <code>{html.escape(P.tracked_name(P.config_file))}</code>. The public map does not observe paths, so it shows UNMEASURED. Whether the text is complete is checked separately.</p><div class="tablewrap"><table><thead><tr><th>Source</th><th>Format</th><th>Path observed</th></tr></thead><tbody>{source_rows}</tbody></table></div>
<h2>What each document is for</h2><p class="sources">The {link('system/specs/PRD-info-architecture.md','information PRD')} sets origins, corrections and borders, and the {link('system/specs/PRD-session-memory.md','session PRD')} sets return and success conditions. The {link('system/specs/design-memory-runtime.md','design document')} connects modules, state and tests, and the {link('system/loop/README.md','operations document')} covers running and stopping. The reason for a change of authority is kept in a {link(P.tracked_name(P.decisions),'DR')}.</p>
</section>
<footer>Memory system map · tools/dev/build_memory_map.py · The descriptions follow the design documents. A file that exists, a check that passes and an effect on the user are different evidence.</footer></main>
<dialog id="reader"><header><strong id="reader-title">Document</strong><button id="reader-close" type="button">Close</button></header><article id="reader-body"></article></dialog><script>{JS}</script></body></html>'''


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args(argv)
    output = Path(P.memory_map())
    data = observe()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data, output), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
