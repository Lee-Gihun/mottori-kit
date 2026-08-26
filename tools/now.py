#!/usr/bin/env python3
"""now — 작업 상태의 계기. PRD: system/PRD-session-memory.md (v3).

    now.py log "[track/type] 내용"   journal append (스키마 검증) + NOW 재생성
    now.py render                     NOW.md 재생성만
    now.py hook-context               SessionStart 훅용: NOW를 additionalContext JSON으로
    now.py precompact                 PreCompact 훅용: 컴팩션 사건 기록
    now.py check                      드리프트 계기 (5종 검출기, PRD §3.3)

NOW.md는 생성물이다 — 손으로 고치지 말 것. 고치고 싶은 내용이 있다면 그 내용의
정본(트랙 정본 또는 journal)을 고쳐라. (DIGEST·hotset과 같은 규칙.)
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M


def _now_iso():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M+09:00")


def _age_days(path):
    if not os.path.exists(path):
        return None
    return (datetime.datetime.now()
            - datetime.datetime.fromtimestamp(os.path.getmtime(path))).days


def log(body, quiet=False):
    line = f"- {_now_iso()} {body.strip()}"
    err = M.validate_line(line)
    if err:
        print(f"거부: {err}\n  줄: {line}", file=sys.stderr)
        return 1
    os.makedirs(M.STATE, exist_ok=True)
    p = M.journal_path()
    new = not os.path.exists(p)
    with open(p, "a", encoding="utf-8") as f:
        if new:
            f.write(f"# journal {datetime.datetime.now():%Y-%m}\n\n"
                    "형식: `- <ISO8601> [<track>/<type>] <내용> (→ ref)*` · "
                    "type 정의는 `tools/memlib.py` · 소급 기입은 `(소급)` 표기\n\n")
        f.write(line + "\n")
    render()
    if not quiet:
        print(f"기록: {line}")
    return 0


def _track_rows():
    rows = []
    for key, name, rel in M.TRACKS:
        p = os.path.join(M.ROOT, rel)
        age = _age_days(p)
        snippet = ""
        if os.path.exists(p):
            for raw in open(p, encoding="utf-8"):
                m = M.UPDATED_RE.search(raw)
                if m:
                    snippet = m.group(2).strip().rstrip("*·—: ").replace("**", "")[:110].rstrip("·— ")
                    break
        warn = " ⚠" if (age is not None and age > M.TRACK_STALE_DAYS) else ""
        rows.append(f"- **{name}** — {snippet or '(갱신줄 없음)'} "
                    f"(파일 {age}일 전{warn}) → `{rel}`")
    rows.append(f"- **개인** — 정본 `{M.PERSONAL_POINTER}` (개인 영역: NOW에 내용 비표시)")
    return rows


def threads():
    """스레드 서류철 레지스트리를 인쇄한다 (복귀 의식용).

    슬래시 커맨드가 목록을 본문에 박고 있었는데, 그러면 스레드가 바뀔 때마다
    커맨드 파일을 고쳐야 하고 이식하면 남의 스레드를 가리킨다 (DR-025).
    """
    if not M.THREADS:
        print("(등록된 스레드 없음 — system/memory-config.json의 threads에 추가)")
        return 0
    for key, name, dossier in M.THREADS:
        exists = "" if (dossier and os.path.exists(os.path.join(M.ROOT, dossier))) else "  [파일 없음]"
        print(f"{key:<12} {name}\n{'':<12} 서류철: {dossier or '미지정'}{exists}")
    return 0


def _pointer_block():
    """정본 포인터를 config에서 조립한다 (DR-025).

    이전에는 이 문단이 렌더러 안에 리터럴로 박혀 있었다. 생성물이 남의 리포 경로를
    가리키는 구조라, 트랙이 바뀌어도 NOW는 옛 포인터를 계속 인쇄했다.
    """
    parts = []
    for key, name, canon in M.TRACKS:
        refs = "+".join(f"`{p}`" for p in [canon] + M.track_also(key))
        parts.append(f"{name} {refs}")
    if M.PERSONAL_POINTER:
        parts.append(f"개인 `{M.PERSONAL_POINTER}`")
    parts.append("개인 사실 `python3 tools/rec.py find|hot`")
    parts.append("결정 기록 `system/decisions.md`")
    parts.append('회상 `python3 tools/recall.py find "질의"`')
    # 3개씩 끊어 줄바꿈 (NOW는 사람이 훑는 화면이다)
    chunks = [" · ".join(parts[i:i + 3]) for i in range(0, len(parts), 3)]
    return "\n".join(chunks) or "- (트랙 미정의)"


def render():
    entries = M.parse_journal()
    jp = M.journal_path()
    j_age = _age_days(jp)
    fresh = [f"journal {j_age if j_age is not None else '?'}일 전"
             + (" ⚠" if (j_age is None or j_age > M.JOURNAL_STALE_DAYS) else "")]

    threads = []
    for key, name, dossier in M.THREADS:
        threads.append(f"- {name} — " + (f"서류철 `{dossier}`" if dossier
                                         else "서류철 **미지정** (Phase 2)"))

    recent = entries[-M.NOW_TAIL_EVENTS:]
    decisions = [e for e in entries if e["type"] in ("decision", "state")][-M.NOW_RECENT_DECISIONS:]

    def fmt(e):
        return f"- {e['ts'][:16]} [{e['track']}/{e['type']}] {e['body']}"

    out = f"""# NOW

*생성 {_now_iso()} · `python3 tools/now.py render` — **손 편집 금지** (생성물).
컴팩션·요약과 이 파일이 충돌하면 **이 파일이 이긴다** (PRD §3.1).*
*입력 신선도: {' · '.join(fresh)}*

## 트랙 온도판
{chr(10).join(_track_rows())}

## 살아 있는 스레드 (서류철)
{chr(10).join(threads)}
*(복귀 의식: 깊은 스레드로 돌아올 때 서류철부터 읽는다 — PRD §3.3)*

## 최근 결정·국면
{chr(10).join(fmt(e) for e in decisions) or '- (없음)'}

## 최근 사건
{chr(10).join(fmt(e) for e in recent) or '- (없음)'}

## 정본 포인터
{_pointer_block()}
"""
    os.makedirs(M.STATE, exist_ok=True)
    open(M.NOW_PATH, "w", encoding="utf-8").write(out)
    return 0


def hook_context():
    """SessionStart 훅: NOW를 additionalContext로 주입. 실패해도 세션을 막지 않는다."""
    try:
        if not os.path.exists(M.NOW_PATH):
            return 0
        body = open(M.NOW_PATH, encoding="utf-8").read()
        age = _age_days(M.NOW_PATH)
        head = (f"[state/NOW.md — 세션 시작 자동 주입 (파일 {age}일 전 생성). "
                "요약·기억의 상태 단언과 충돌하면 이 내용이 이긴다.]\n\n")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": head + body[:M.NOW_HOOK_MAX_BYTES]}}, ensure_ascii=False))
    except Exception:
        pass
    return 0


def precompact():
    try:
        log("[system/state] 컴팩션 발생 — 이후 컨텍스트는 요약본", quiet=True)
    except Exception:
        pass
    return 0


VOLATILE_RE = None  # lazy


def check(memory_dir=None, root=None, issues=False):
    """드리프트 계기 — PRD §3.3의 5종 검출기. 반환: 경고 수.

    `issues=True`면 게이트용 이슈 집합 계약으로 출력한다. 시간이 흘러서 저절로 생기는
    이슈(`~` 접두)와 편집이 만든 이슈를 가른다 — 전자로 Stop을 막으면 이번 턴에 고칠 수
    없는 경보가 되고, 못 고칠 경보는 곧 꺼진다 (codex 라운드 3).
    """
    import hashlib as _h
    import glob as _glob
    import re as _re
    root = root or M.ROOT
    # auto-memory는 전사 디렉토리 아래 산다. 전사 경로가 유도값이므로 이것도 유도값이다 (DR-025).
    memory_dir = memory_dir or os.path.join(M.TRANSCRIPTS, "memory")

    # (gated, 안정 ID, 사람이 읽는 문구).
    # **ID와 문구를 가른 이유** (codex 라운드 4): 문구 전체를 ID로 쓰면 표시 문구만 고쳐도
    # 게이트가 "새 이슈"로 막았다. ID엔 상태를 식별하는 것만 넣고 날짜·줄번호·나이는 문구로 뺀다.
    warns = []
    def W(gated, ident, text):
        warns.append((gated, ident, text))

    # 1) 트랙 정본 낙후: journal의 해당 트랙 최신 사건보다 정본 파일이 오래됨
    #    시간만 흘러서는 안 생긴다 (codex가 시계를 9/1로 고정해 확인). 편집 유발이라 gated.
    entries = M.parse_journal()
    latest = {}
    for e in entries:
        latest[e["track"]] = e["ts"]
    for key, name, rel in M.TRACKS:
        p = os.path.join(root, rel)
        if key in latest and os.path.exists(p):
            fdate = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
            jdate = latest[key][:10]
            if fdate < jdate:
                W(True, f"canonical-stale:{rel}",
                  f"[정본 낙후] {rel} ({fdate}) < journal {key} 최신 사건 ({jdate})")

    # 2) MEMORY.md 인덱스 휘발성 (8/8 사고의 패턴)
    idx = os.path.join(memory_dir, "MEMORY.md")
    # 8/8 사고의 시그니처는 날짜가 아니라 상태 어휘였다 (대기·콜·온사이트·딜 국면).
    # 제정일·이관일 같은 provenance 날짜는 정상이므로 날짜 자체는 물지 않는다 (dr:008).
    vol = _re.compile(r"대기\b|콜 대기|온사이트|딜 국면|→ 딜|R\d [화수목금월]|예정\)")
    if os.path.exists(idx):
        for i, line in enumerate(open(idx, encoding="utf-8"), 1):
            if line.startswith("- ") and vol.search(line):
                # ID에 줄번호를 안 쓴다 — 위에 한 줄만 넣어도 전부 새 이슈가 됐다.
                m = _re.search(r"\]\(([a-z0-9-]+\.md)\)", line)
                k = m.group(1) if m else _h.sha1(line.strip().encode()).hexdigest()[:8]
                W(True, f"index-volatile:{k}",
                  f"[인덱스 휘발성] MEMORY.md:{i} {line.strip()[:80]}")

    # 3) 메모리 파일 ↔ 인덱스 정합
    if os.path.exists(idx):
        text = open(idx, encoding="utf-8").read()
        files = {f for f in os.listdir(memory_dir)
                 if f.endswith(".md") and f != "MEMORY.md"}
        linked = set(_re.findall(r"\]\(([a-z0-9-]+\.md)\)", text))
        for f in sorted(files - linked):
            W(True, f"index-missing:{f}", f"[인덱스 누락] {f} — 파일은 있는데 인덱스 줄 없음")
        for f in sorted(linked - files):
            W(True, f"index-ghost:{f}", f"[유령 인덱스] {f} — 인덱스 줄은 있는데 파일 없음")

    # 4) type:project 메모리 부패 후보 (14일 무갱신). 시간 유발이라 자문용.
    for f in sorted(os.listdir(memory_dir)) if os.path.isdir(memory_dir) else []:
        fp = os.path.join(memory_dir, f)
        if not f.endswith(".md") or f == "MEMORY.md":
            continue
        try:
            head = open(fp, encoding="utf-8").read(400)
        except Exception:
            continue
        if "type: project" in head:
            age = (datetime.datetime.now()
                   - datetime.datetime.fromtimestamp(os.path.getmtime(fp))).days
            if age > M.MEMORY_ROT_DAYS and "state/NOW.md" not in open(fp, encoding="utf-8").read():
                W(False, f"memory-rot:{f}",
                  f"[부패 후보] {f} — project형 {age}일 무갱신 (포인터화 검토)")

    # 4b) 녹취 파이프라인. 전사만 하고 멈춘 것을 잡는다.
    #     (2026-08-25 실측: 전사·결손복구까지 하고 정독을 안 해서 재료만 쌓였다.
    #      건너뛸 수 있으면 워크플로우가 아니다.)
    rec_root = os.path.join(root, "_private", "recordings")
    if os.path.isdir(rec_root):
        for name in sorted(os.listdir(rec_root)):
            rd = os.path.join(rec_root, name)
            # watch_recordings 의 명명 규약(YYYY-MM-DD-슬러그)을 따르는 것만 본다.
            # prep 같은 작업 폴더는 녹취가 아니다.
            if not os.path.isdir(rd) or not re.match(r"^\d{4}-\d{2}-\d{2}-", name):
                continue
            try:
                files = os.listdir(rd)
            except OSError:
                continue
            if not any(f.endswith("-timestamped.txt") for f in files):
                continue
            # 정독을 이미 마친 것 (analysis.md 가 정독 산출이던 이전 판)은 제외한다.
            # 도구 도입 전에 손으로 끝낸 건이 있다.
            if "analysis.md" in files and "linebyline" not in files \
                    and os.path.exists(os.path.join(rd, ".정독완료")):
                continue
            qa = [f for f in files if f.endswith("-QA.md")]
            gap_rows = 0
            if qa:
                try:
                    with open(os.path.join(rd, qa[0]), encoding="utf-8") as fh:
                        gap_rows = len(re.findall(
                            r"^\|\s*[\d:.]+\s*\|\s*[\d:.]+\s*\|", fh.read(), re.M))
                except OSError:
                    pass
            if gap_rows and "결손복구.md" not in files:
                W(True, "rec-gaps:" + name,
                  "[녹취 결손 미복구] {} — 후보 {}건. "
                  "python3 tools/regap.py _private/recordings/{}".format(
                      name, gap_rows, name))
            if "analysis-linebyline.md" not in files:
                W(True, "rec-unread:" + name,
                  "[녹취 정독 미완] {} — 전사만 있고 정독이 없다. "
                  "python3 tools/analyze_recording.py _private/recordings/{}".format(
                      name, name))

    # 4c) 구글 드라이브 인박스. 올린 것은 무조건 정독까지 간다.
    #     (기훈 2026-08-25: "구글 드라이브 inbox recording에 올리는건 무조건 정독하는거")
    #     정독 여부는 판단 대상이 아니므로 게이트로 강제한다.
    try:
        if os.path.join(root, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(root, "tools"))
        import drive_inbox as _di
        _path, _rows = _di.survey()
        if _path is None:
            # 마운트를 못 찾는 것도 사건이다. 조용히 0건으로 넘어가면
            # 인박스에 올린 것이 영영 안 보인다.
            W(False, "drive-inbox-unmounted",
              "[드라이브 인박스 없음] 구글 드라이브 데스크톱 동기화 확인 필요. "
              "python3 tools/drive_inbox.py --list")
        else:
            for _f, _fp, _st, _why in _rows:
                if _st != "완료":
                    W(True, "drive-inbox:" + _f,
                      "[인박스 미처리] {} — {}{}. python3 tools/drive_inbox.py".format(
                          _f, _st, " ({})".format(_why) if _why else ""))
    except Exception as _e:  # noqa: BLE001
        W(False, "drive-inbox-error",
          "[드라이브 인박스 검사 실패] {}".format(_e))

    # 5) NOW 나이
    a = _age_days(M.NOW_PATH)
    if a is None:
        W(True, "now-absent", f"[NOW 부재] {M.NOW_PATH}")
    elif a > 3:
        W(False, "now-stale", f"[NOW 낡음] {a}일 전 (임계 3일)")

    # 6) journal 나이. **월 경계를 부재와 가르는 이유** (codex 라운드 4): journal 경로는
    #    월별이라 매달 1일이면 이번 달 파일이 없다. 그것만으로 hard issue를 내면 달력이
    #    게이트를 막는다. 직전 달 것이 신선하면 정상 rollover(자문), 아예 하나도 없으면 부재(gated).
    jp = M.journal_path()
    ja = _age_days(jp)
    if ja is None:
        others = sorted(_glob.glob(os.path.join(os.path.dirname(jp), "journal-*.md")))
        newest = min((x for x in (_age_days(o) for o in others) if x is not None), default=None)
        if newest is not None and newest <= M.JOURNAL_STALE_DAYS:
            W(False, "journal-rollover",
              f"[journal 월 전환] {os.path.basename(jp)} 아직 없음 (직전 것이 {newest}일 전)")
        else:
            W(True, "journal-absent", f"[journal 부재] {jp}")
    elif ja > M.JOURNAL_STALE_DAYS:
        W(False, "journal-stale", f"[journal 낡음] {ja}일 전 (임계 {M.JOURNAL_STALE_DAYS}일)")

    if issues:
        # 계약: `안정ID\t표시문구`, 시간 유발은 `~` 접두, 마지막 줄은 반드시 트레일러.
        # 이슈 유무와 무관하게 exit 0 — 종료코드는 "측정이 됐는가"만 뜻한다 (codex 라운드 4).
        gated = 0
        for g, ident, text in warns:
            print(f"{ident if g else '~' + ident}\t{text}")
            gated += 1 if g else 0
        print(f"#issues {gated}")
        return 0

    for g, ident, text in warns:
        print("⚠", text)
    print(f"check: 경고 {len(warns)}건" if warns else "check: 깨끗함")
    return len(warns)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "log":
        return log(" ".join(sys.argv[2:]))
    if cmd == "render":
        r = render()
        print(f"NOW.md 재생성 ({os.path.getsize(M.NOW_PATH)} bytes)")
        return r
    if cmd == "check":
        n = check(issues="--issues" in sys.argv)
        return 0 if n == 0 else 2
    if cmd == "threads":
        return threads()
    if cmd == "hook-context":
        return hook_context()
    if cmd == "precompact":
        return precompact()
    print(f"모르는 명령: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
