#!/usr/bin/env python3
"""원장 조회기 — 정보 아키텍처 PRD §6.2 구현.

기록 본체는 `_private/ledger/facts/` (비추적, PRD §11 D2). 이 스크립트는 도메인 내용을
담지 않으므로 추적 공간에 둔다.

사용:
  python3 tools/rec.py hot                 핫셋 렌더 → _private/ledger/hotset.md (스냅샷 자동 동반)
  python3 tools/rec.py find <말>           전문 검색 (claim·본문·태그·인물)
      --status=결정됨  --tag=레벨  --speaker=벤  --domain=<도메인>  --since=2026-08-01
      (speaker는 부분 일치 — "벤"은 "벤·비네이"도 잡는다. 복합 발화자 침묵 미스 방지)
  python3 tools/rec.py show <id>           레코드 하나 출력
  python3 tools/rec.py audit <id>          감사 사슬 (사실 → 파생 → 원점) + 파일 실재 검증
  python3 tools/rec.py check               정합성 검증 (필수 필드·경로·링크·상한·상태·대체 관계)
  python3 tools/rec.py new <id> [--claim= --status= --speaker= --tags=a,b --origin= --domain=]
                                           신규 레코드 스캐폴드 — 남긴 TODO는 check가 잡는다
  python3 tools/rec.py snapshot            원장 스냅샷 (내용 변경 시에만, 최근 20개 링 보존)

설계 메모: 태그에만 의존하지 않는다(PRD §6.2, A-2 대비). find는 본문 전문을 함께 훑는다.
"""
import os, re, sys, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "_private/ledger")
FACTS = os.path.join(LEDGER, "facts")
HOTSET = os.path.join(LEDGER, "hotset.md")

HOT_CAP = 60  # PRD §11 D7
STATUSES = {"확정", "전언", "추론", "미해결", "결정됨", "대체됨", "철회됨"}
REQUIRED = ["id", "claim", "status", "hot", "domain", "speaker", "date",
            "origin_kind", "origin"]
# 표시 순서: 위반 위험이 큰 것부터 (PRD §6.4)
ORDER = ["결정됨", "철회됨", "확정", "추론", "전언", "미해결", "대체됨"]
HEAD = {
    "결정됨": ("A. 결정됨 — 재제안 금지", "이 항목을 다시 제안하면 버그다 (I-1)."),
    "철회됨": ("B. 철회됨 — 재발 금지", "이 주장을 다시 말하면 버그다 (I-5)."),
    "확정":   ("C. 확정 — 원점 확인된 사실", ""),
    "추론":   ("D. 추론 — 관측이 아니다", "사실처럼 인용하지 말 것 (I-3)."),
    "전언":   ("E. 전언", ""),
    "미해결": ("F. 미해결 — 모르면 모른다고 한다", "추측으로 메우지 않는다 (PRD §4.4)."),
    "대체됨": ("G. 대체됨", ""),
}


# ---- frontmatter 파서 (의존성 없음, 스키마가 고정이라 최소 구현) --------
def parse(path):
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm, body = text[3:end], text[end + 4:]
    d, key = {}, None
    for line in fm.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                d[key] = [x.strip() for x in inner.split(",") if x.strip()]
            elif val == "":
                d[key] = []
            else:
                d[key] = val.strip('"')
        elif line.lstrip().startswith("- ") and key:
            if not isinstance(d.get(key), list):
                d[key] = []
            d[key].append(line.lstrip()[2:].strip())
    d["hot"] = str(d.get("hot", "")).lower() == "true"
    d["_body"] = body.strip()
    d["_path"] = path
    return d


def load():
    out = []
    for p in sorted(glob.glob(os.path.join(FACTS, "*.md"))):
        r = parse(p)
        if r:
            out.append(r)
    return out


def resolve(p):
    """원장이 가리키는 경로를 실제 파일로 해석. 리포 상대경로와 절대경로 모두 허용."""
    if os.path.isabs(p):
        return p
    return os.path.join(ROOT, p)


def exists(p):
    return os.path.exists(resolve(p))


# ---- 명령 --------------------------------------------------------------
def cmd_hot():
    recs = [r for r in load() if r["hot"]]
    lines = [
        "# 핫셋 — 세션 시작 시 로드 (PRD §6.4)",
        "",
        "> **생성물이다. 직접 고치지 말 것** — 정본은 `_private/ledger/facts/` 원자 노트다.",
        "> 갱신: 레코드를 고친 뒤 `python3 tools/rec.py hot` 재실행.",
        "> **규율**: 사실 단언(T1)·행동 제안(T2) 전에 여기부터 본다.",
        f"> 레코드 {len(recs)}건 / 상한 {HOT_CAP}",
        "",
    ]
    if len(recs) > HOT_CAP:
        lines += [f"> ⚠️ **상한 초과({len(recs)}/{HOT_CAP})** — 국면 종료 항목을 콜드로 강등할 것 (D7).", ""]
    lines.append("---")
    for st in ORDER:
        group = [r for r in recs if r["status"] == st]
        if not group:
            continue
        title, note = HEAD.get(st, (st, ""))
        lines += ["", f"## {title}", ""]
        if note:
            lines += [f"> {note}", ""]
        lines += ["| 사실 | 출처 | 날짜 | id |", "|---|---|---|---|"]
        for r in sorted(group, key=lambda x: x["id"]):
            claim = r["claim"].replace("|", "\\|")
            lines.append(f"| {claim} | {r['speaker']} | {r['date']} | `{r['id']}` |")
    lines += ["", "---", "",
              "**깊이 파려면**: `python3 tools/rec.py show <id>` · "
              "`python3 tools/rec.py audit <id>` (원점까지의 사슬)", ""]
    os.makedirs(LEDGER, exist_ok=True)
    open(HOTSET, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[hot] {len(recs)} records -> {os.path.relpath(HOTSET, ROOT)}")
    if len(recs) > HOT_CAP:
        print(f"[hot] WARNING over cap: {len(recs)}/{HOT_CAP}")


def cmd_find(args):
    filters, terms = {}, []
    for a in args:
        m = re.match(r"^--(\w+)=(.+)$", a)
        if m:
            filters[m.group(1)] = m.group(2)
        else:
            terms.append(a)
    recs = load()
    for k, v in filters.items():
        if k == "since":
            recs = [r for r in recs if r.get("date", "") >= v]
        elif k == "tag":
            recs = [r for r in recs if v in r.get("tags", [])]
        elif k == "speaker":
            # 부분 일치 — "벤·비네이"·"벤·HR" 같은 복합 발화자가 정확 일치에서 빠지는 침묵 미스 방지
            recs = [r for r in recs if v in r.get("speaker", "")]
        else:
            recs = [r for r in recs if r.get(k) == v]
    if terms:
        def hit(r):
            hay = " ".join([r.get("claim", ""), r.get("_body", ""), r.get("id", ""),
                            r.get("speaker", ""), " ".join(r.get("tags", []))]).lower()
            return all(t.lower() in hay for t in terms)
        recs = [r for r in recs if hit(r)]
    if not recs:
        print("[find] 0 hits — 기록에 없다. 지어내지 말 것 (PRD §4.4).")
        return 0
    print(f"[find] {len(recs)} hit(s)\n")
    for r in sorted(recs, key=lambda x: (ORDER.index(x["status"]) if x["status"] in ORDER else 9, x["id"])):
        flag = "🔥" if r["hot"] else "  "
        print(f"{flag} [{r['status']}] {r['claim']}")
        print(f"     {r['speaker']} · {r['date']} · `{r['id']}`")
    return 0


def cmd_show(rid):
    p = os.path.join(FACTS, rid + ".md")
    if not os.path.exists(p):
        print(f"[show] 그런 레코드 없음: {rid}")
        return 1
    print(open(p, encoding="utf-8").read())
    return 0


def cmd_audit(rid):
    p = os.path.join(FACTS, rid + ".md")
    if not os.path.exists(p):
        print(f"[audit] 그런 레코드 없음: {rid}")
        return 1
    r = parse(p)
    gap = r.get("origin_gap", "")
    print(f"주장   : {r['claim']}")
    print(f"등급   : {r['status']}   발화자: {r['speaker']}   날짜: {r['date']}")
    print(f"레코드 : {os.path.relpath(p, ROOT)}")
    print()
    print("감사 사슬 (원점 → 파생):")
    chain = r.get("via") or [r["origin"]]
    for i, step in enumerate(chain):
        mark = "✓" if exists(step) else "✗ 없음"
        if i == 0:
            # 원점이 유실된 레코드의 첫 항목은 원점이 아니다 — 등급 인플레이션 방지
            arrow = "  원점 " if not gap else "최선가용"
        else:
            arrow = "   ↓   "
        print(f"{arrow} [{mark}] {step}")
    print(f"   ↓    [✓] {os.path.relpath(p, ROOT)}  ← 이 레코드")
    print()
    print(f"원점 종류: {r.get('origin_kind','—')}")
    if gap:
        print(f"⚠️  원점 결손: {gap}")
        print("    사슬 첫 항목은 원점이 아니라 **현존 최선 가용 소스**다. 축자 인용이 필요하면 등급 한계를 함께 밝힐 것.")
    else:
        print("원점 결손: 없음 (원점 파일이 실재)")
    return 0


def cmd_check():
    recs = load()
    ids = {r["id"] for r in recs}
    problems = []
    for r in recs:
        rid = r.get("id", os.path.basename(r["_path"]))
        for f in REQUIRED:
            if f not in r or r[f] in ("", None):
                problems.append(f"{rid}: 필수 필드 누락 `{f}`")
        if r.get("status") not in STATUSES:
            problems.append(f"{rid}: 알 수 없는 상태 `{r.get('status')}`")
        if r["id"] != os.path.basename(r["_path"])[:-3]:
            problems.append(f"{rid}: id와 파일명 불일치")
        for step in (r.get("via") or []) + [r.get("origin", "")]:
            if step and not exists(step):
                problems.append(f"{rid}: 경로 없음 → {step}")
        for link in re.findall(r"\[\[([^\]]+)\]\]", r.get("_body", "")):
            if link not in ids:
                problems.append(f"{rid}: 끊긴 링크 → [[{link}]]")
        # 대체/철회 관계 (PRD §6.1) — 참조 대상이 실재해야 한다
        for fld in ("supersedes", "superseded_by"):
            val = r.get(fld)
            if val:
                for t in (val if isinstance(val, list) else [val]):
                    if t not in ids:
                        problems.append(f"{rid}: {fld} 대상 없음 → {t}")
        # 대체됨 상태인데 관계 필드가 없으면 어디로 대체됐는지 추적 불가
        if r.get("status") == "대체됨" and not r.get("superseded_by"):
            problems.append(f"{rid}: 상태가 `대체됨`인데 `superseded_by` 없음")
    hot = sum(1 for r in recs if r["hot"])
    if hot > HOT_CAP:
        problems.append(f"핫셋 상한 초과: {hot}/{HOT_CAP} (D7 — 국면 종료 항목 강등 필요)")
    dup = [i for i in ids if sum(1 for r in recs if r["id"] == i) > 1]
    for d in set(dup):
        problems.append(f"중복 id: {d}")

    print(f"[check] 레코드 {len(recs)}건 · 핫 {hot}/{HOT_CAP}")
    from collections import Counter
    print("[check] 상태:", dict(Counter(r["status"] for r in recs)))
    for p in problems:
        print("PROBLEM " + p)
    print(f"[check] 문제: {len(problems)}건")
    return 1 if problems else 0


def ledger_hash():
    """원장 내용 해시 — 스냅샷 중복 방지용."""
    import hashlib
    h = hashlib.sha256()
    paths = sorted(glob.glob(os.path.join(FACTS, "*.md")))
    paths.append(os.path.join(LEDGER, "_telemetry.md"))
    for p in paths:
        if os.path.exists(p):
            h.update(os.path.basename(p).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


def cmd_snapshot(quiet=False):
    """원장은 비추적(D2)이라 git 이력이 없다 — 유일본 보호는 스냅샷 링(최근 20)이 담당한다.

    내용이 안 변했으면 만들지 않는다. 자동 실행은 hot에 편승할 뿐, 매 턴 돌지 않는다(§6.9)."""
    import shutil, datetime
    snaps = os.path.join(LEDGER, ".snapshots")
    os.makedirs(snaps, exist_ok=True)
    hfile = os.path.join(snaps, "LATEST")
    cur = ledger_hash()
    if os.path.exists(hfile) and open(hfile).read().strip() == cur:
        if not quiet:
            print("[snapshot] 변경 없음 — 건너뜀")
        return 0
    name = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S") + "-" + cur[:8]
    dst = os.path.join(snaps, name)
    os.makedirs(dst)
    shutil.copytree(FACTS, os.path.join(dst, "facts"))
    for extra in ("_telemetry.md", "_verification-20q.md", "README.md"):
        src = os.path.join(LEDGER, extra)
        if os.path.exists(src):
            shutil.copy2(src, dst)
    open(hfile, "w").write(cur)
    dirs = sorted(d for d in os.listdir(snaps) if os.path.isdir(os.path.join(snaps, d)))
    for old in dirs[:-20]:
        shutil.rmtree(os.path.join(snaps, old))
    n = len(glob.glob(os.path.join(dst, "facts", "*.md")))
    print(f"[snapshot] {name} (facts {n}건, 링 {min(len(dirs),20)}/20)")
    return 0


def cmd_new(args):
    import datetime
    if not args:
        print("usage: rec.py new <id> [--claim=..] [--status=..] [--speaker=..] [--tags=a,b] [--origin=..] [--domain=..] [--date=..]")
        return 1
    rid = args[0]
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", rid):
        print(f"[new] id는 kebab-case여야 한다: {rid}")
        return 1
    path = os.path.join(FACTS, rid + ".md")
    if os.path.exists(path):
        print(f"[new] 이미 존재: {os.path.relpath(path, ROOT)}")
        print("[new] 기존 레코드 수정은 편집이 아니라 **상태 전이**로 (README — 대체됨/철회됨 + supersedes)")
        return 1
    opts = {}
    for a in args[1:]:
        m = re.match(r"^--(\w+)=(.+)$", a)
        if m:
            opts[m.group(1)] = m.group(2)
    today = datetime.date.today().isoformat()
    origin = opts.get("origin", "TODO-원점-경로")
    claim = opts.get("claim", "TODO-한-문장-주장")
    os.makedirs(FACTS, exist_ok=True)
    # 남긴 TODO는 check가 잡는다 (미지 상태·없는 경로) — 빈칸으로 통과되는 스캐폴드는 스키마 드리프트만 만든다
    lines = [
        "---",
        f"id: {rid}",
        f"claim: \"{claim}\"",
        f"status: {opts.get('status', 'TODO-상태')}",
        "hot: true",
        f"domain: {opts.get('domain', 'TODO-도메인')}",
        f"tags: [{opts.get('tags', 'TODO-태그')}]",
        f"speaker: {opts.get('speaker', 'TODO-발화자')}",
        f"date: {opts.get('date', today)}",
        f"recorded: {today}",
        f"origin_kind: {opts.get('origin_kind', 'TODO-오디오|전사|전사파생|메시지|문서|세션발화')}",
        f"origin: {origin}",
        "origin_gap: \"\"",
        "via:",
        f"  - {origin}",
        "---",
        "",
        f"# {claim}",
        "",
        "**근거**: (가능하면 축자 인용. 원점이 유실됐으면 origin_gap에 정직하게)",
        "",
        "**주의/범위**: ",
        "",
    ]
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[new] {os.path.relpath(path, ROOT)}")
    print("[new] 다음: TODO 채우기 → `rec.py check` → `rec.py hot`")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "new":
        return cmd_new(rest)  # new는 원장 부재 시에도 첫 레코드를 만들 수 있어야 한다
    if not os.path.isdir(FACTS):
        print(f"[rec] 원장이 없다: {os.path.relpath(FACTS, ROOT)}")
        return 1
    if cmd == "hot":
        cmd_snapshot(quiet=True)  # 렌더 트리거에 편승 — 원장이 변한 시점마다 자동 보호
        return cmd_hot() or 0
    if cmd == "find":
        return cmd_find(rest)
    if cmd == "show":
        return cmd_show(rest[0]) if rest else 1
    if cmd == "audit":
        return cmd_audit(rest[0]) if rest else 1
    if cmd == "check":
        return cmd_check()
    if cmd == "snapshot":
        return cmd_snapshot()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
