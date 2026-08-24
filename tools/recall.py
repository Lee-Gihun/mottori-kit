#!/usr/bin/env python3
"""recall — 에피소드 회상: 전사 원장(*.jsonl)에 대한 표적 검색.

PRD: system/PRD-session-memory.md (v3) §3.4. 잃어버린 게 아니라 안 뒤진 것을 뒤진다.

    recall.py find "패턴" [--source all|claude|codex|dumps] [--role user|assistant]
                          [--since YYYY-MM-DD] [--around 2] [--max 8] [--thinking]
    recall.py sessions

소스 레지스트리는 tools/memlib.py EPISODIC_SOURCES가 정본이다 (claude 전사 + codex 세션
+ _private/dumps 챗 덤프). dumps 결과는 세션 내 열람 전용 — 산출물·커밋 인용 금지.

사용 규약 (문헌 각인 — PRD §1):
- 표적 질의만. 전체 읽기 금지 (수동 통독은 이득이 소멸한다, 2607.20064).
- 결과를 컨텍스트에 통째로 붓지 말 것 (리드아웃 붕괴, 2607.01538).
  현재 질문에 묶인 몇 줄로 번역해 쓴다 (2608.12847).
- 기훈 발화의 원문이 걸린 판정에는 요약이 아니라 이 도구다 (발화=원점).
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M


def _kst(ts):
    """전사 타임스탬프는 UTC다 — 표시에서 KST(+9)로 변환한다."""
    if not ts:
        return ts
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", ""))
        return (dt + datetime.timedelta(hours=9)).strftime("%m-%d %H:%M") + "K"
    except Exception:
        return ts


import glob as _glob


_CWD_CACHE = {}


def _codex_cwd(fp):
    """codex rollout이 어느 디렉토리에서 돌았는지. 첫 줄 `payload.cwd` (2026-08-24 실측)."""
    if fp in _CWD_CACHE:
        return _CWD_CACHE[fp]
    cwd = None
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            d = json.loads(f.readline())
        cwd = (d.get("payload") or {}).get("cwd")
    except Exception:
        pass
    _CWD_CACHE[fp] = cwd
    return cwd


def _same_instance(cwd):
    """이 rollout이 이 인스턴스에서 돌았는가. **판정 불가는 거부**한다 (2026-08-24 적대 검증).

    처음엔 셋 다 틀렸다.
    - `startswith(ROOT)`는 경로 경계를 안 봐서 `/x/repo-evil`이 `/x/repo`를 통과했다.
    - `cwd` 미기록(옛 포맷)을 "판정 불가라 남긴다"로 처리해 타 인스턴스가 그대로 보였다.
    - 상대 경로 `cwd`는 realpath가 **현재** 작업 디렉토리 기준으로 풀려 엉뚱하게 통과했다.

    데이터 국경에서는 가용성보다 기밀성이 앞선다. 모르면 안 보여준다.
    일부러 열려면 `--all-instances`.
    """
    if not cwd or not os.path.isabs(cwd):
        return False
    try:
        real = os.path.realpath(cwd)
        root = os.path.realpath(M.ROOT)
        return real == root or os.path.commonpath([real, root]) == root
    except ValueError:      # 드라이브가 다르면 commonpath가 던진다
        return False


def _source_files(names, all_instances=False):
    """(source_name, kind, filepath) 목록. 소스 순서·경로는 memlib이 정본.

    **Codex 세션은 인스턴스로 거른다** (DR-025). `~/.codex/sessions`는 머신 전역이라
    거르지 않으면 이 인스턴스의 recall이 다른 인스턴스의 대화를 읽는다. 개인 맥에서
    회사 세션이, 회사 맥에서 개인 세션이 검색되는 양방향 누출이다.
    Claude 전사는 프로젝트별 디렉토리라 이 문제가 없다 (경로 자체가 필터다).
    `--all-instances`로 의도적으로 열 수 있다.
    """
    out = []
    for name, kind, base, pat in M.EPISODIC_SOURCES:
        if names and name not in names:
            continue
        if not os.path.isdir(base):
            continue
        fs = sorted(_glob.glob(os.path.join(base, pat), recursive=True), key=os.path.getmtime)
        if kind == "codex-jsonl" and not all_instances:
            fs = [f for f in fs if _same_instance(_codex_cwd(f))]
        out.extend((name, kind, f) for f in fs)
    return out


# 발화 정규화 (DR-020, 2026-08-22 Codex와의 토론 라운드 1~3에서 확정)
# role=user는 "기훈의 발화"와 동의어가 아니다. 두 종류의 오염이 있다.
#   (1) 시스템 주입: 플러그인 목록·환경 컨텍스트·AGENTS.md 전문·로컬 커맨드 래퍼가 user로 기록
#   (2) 부모 이력 복제: Codex 서브에이전트 rollout이 부모 대화를 통째로 복사해 별도 파일로 저장.
#       같은 발화가 N곳에서 잡히고 타임스탬프는 spawn 시각으로 다시 찍혀 시점 판정까지 오염된다.
# 판별은 role이 아니라 (1) 내용 패턴 (2) 파일 첫 줄 session_meta로 한다.
_SYS_INJECT = re.compile(
    r"^\s*<(recommended_plugins|environment_context|codex_internal_context|app-context"
    r"|system-reminder|command-name|command-message|command-args|local-command"
    r"|user_instructions|task-notification)\b"
    r"|^\s*#\s*AGENTS\.md instructions"
    r"|^\s*You are an agent in a team of agents",
    re.I)


def _is_system_injected(text):
    return bool(_SYS_INJECT.search(text or ""))


_META_CACHE = {}


def _file_identity(fp):
    """(kind, parent_id, boundary) — kind는 'user'|'subagent'|'unknown'.

    Codex rollout 첫 줄 session_meta가 파일 정체성의 정본이다 (실측 8/22):
      thread_source="subagent" + parent_thread_id, 또는 source.subagent 존재.
    paginated 이력에는 subagent_history_start_ordinal(1-based 경계)이 있고,
    legacy에는 없다 — 이 설치본의 관측 대상은 전부 legacy였으므로 경계는 선택적으로 쓴다.
    """
    if fp in _META_CACHE:
        return _META_CACHE[fp]
    ident = ("unknown", None, None)
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            first = json.loads(f.readline())
        if first.get("type") == "session_meta":
            p = first.get("payload") or {}
            src = p.get("source") if isinstance(p.get("source"), dict) else {}
            is_sub = p.get("thread_source") == "subagent" or "subagent" in src
            ident = ("subagent" if is_sub else "user",
                     p.get("parent_thread_id"),
                     p.get("subagent_history_start_ordinal"))
    except Exception:
        pass
    _META_CACHE[fp] = ident
    return ident


def _text_of_codex(d):
    """codex rollout 줄에서 (role, text, ts) — response_item/payload.message만."""
    if d.get("type") != "response_item":
        return None
    p = d.get("payload") or {}
    if p.get("type") != "message" or p.get("role") not in ("user", "assistant"):
        return None
    parts = [b.get("text") or "" for b in (p.get("content") or [])
             if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")]
    text = "\n".join(x for x in parts if x)
    # codex user 턴에는 <app-context> 등 시스템 주입이 섞인다 — 잡음 컷
    if text.startswith("<app-context>") or text.startswith("<environment_context>"):
        return None
    return (p["role"], text, (d.get("timestamp") or "")[:16]) if text else None


def _text_of(d, include_thinking=False):
    """user/assistant 줄에서 검색 대상 텍스트를 뽑는다. (role, text) 또는 None."""
    t = d.get("type")
    if t not in ("user", "assistant"):
        return None
    m = d.get("message") or {}
    c = m.get("content")
    if t == "user":
        if isinstance(c, str):
            return ("user", c)
        if isinstance(c, list):  # tool_result 등 — 도구 산출은 잡음이 많아 기본 제외
            parts = [b.get("content") for b in c if isinstance(b, dict)
                     and b.get("type") == "text"]
            joined = " ".join(p for p in parts if isinstance(p, str))
            return ("user", joined) if joined else None
        return None
    parts = []
    if isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(b.get("text") or "")
            elif include_thinking and b.get("type") == "thinking":
                parts.append(b.get("thinking") or "")
    return ("assistant", "\n".join(p for p in parts if p)) if parts else None


def _snip(text, rx, width=260):
    m = rx.search(text)
    if not m:
        return text[:width].replace("\n", " ")
    a = max(0, m.start() - width // 2)
    s = text[a:a + width].replace("\n", " ")
    return ("…" if a else "") + s + ("…" if a + width < len(text) else "")


def _score(text, branches, rx):
    """매치 품질. 어휘 검색에서 임베딩 전에 해야 할 일 (2026-08-24).

    질의 `a|b|c`에서 **몇 갈래가 맞았는지**가 1차 신호다. 하나만 맞은 발화와 셋 다 맞은
    발화를 같은 취급하면 순위가 없는 것과 다름없다. 실측: 순위 없이 파일 순서로 자르니
    주제어 대역 hit@8이 0%였다.

    (1) 맞은 갈래 수  (2) 총 출현 횟수  (3) 길이 정규화 없음 — 긴 발화가 유리한 건
    회상 용도에서 오히려 맞다. 짧은 맞장구보다 긴 논의가 찾고 싶은 것이다.
    """
    if not branches:
        return (1, len(rx.findall(text)))
    matched = sum(1 for b in branches if b.search(text))
    total = sum(len(b.findall(text)) for b in branches)
    return (matched, total)


def _branches(pattern):
    """최상위 `|`로 갈라진 갈래들. 갈라지지 않으면 빈 목록."""
    if "|" not in pattern:
        return []
    depth, parts, cur = 0, [], ""
    for ch in pattern:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    try:
        return [re.compile(x, re.I) for x in parts if x.strip()]
    except re.error:
        return []


def _match_stamps(pattern, sources, all_instances, thinking,
                  include_agents, include_system, role, since):
    """1차 스캔: 매치의 타임스탬프만 모은다. 순위를 매기려면 전수를 봐야 한다."""
    rx = re.compile(pattern, re.I)
    br = _branches(pattern)
    out = []
    for sname, kind, fp in _source_files(sources, all_instances):
        fkind, _p, _b = _file_identity(fp) if kind == "codex-jsonl" else ("user", None, None)
        if fkind == "subagent" and not include_agents:
            continue
        if kind == "text":
            for ln in open(fp, encoding="utf-8", errors="replace"):
                if rx.search(ln):
                    # 텍스트 소스(dumps 등)는 시각이 없다. 점수는 같은 식으로 매기고
                    # 시각은 빈 문자열이라 최신순에서는 자연히 뒤로 간다.
                    out.append((_score(ln, br, rx), ""))
            continue
        for line in open(fp, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if kind == "codex-jsonl":
                got = _text_of_codex(d)
                if not got:
                    continue
                r, text, ts = got
            else:
                got = _text_of(d, include_thinking=thinking)
                if not got:
                    continue
                r, text = got
                if r == "user" and _is_system_injected(text) and not include_system:
                    continue
                ts = (d.get("timestamp") or "")[:16]
            if since and ts and ts[:10] < since:
                continue
            if (role in (None, r)) and text and rx.search(text):
                out.append((_score(text, br, rx), ts or ""))
    return out


def find(pattern, role=None, since=None, around=2, max_hits=8, thinking=False, sources=None,
         include_agents=False, include_system=False, all_instances=False,
         order="recent"):
    """기본은 authored-only: 기훈이 실제로 친 것과 Claude/Codex가 실제로 답한 것만.

    include_agents=True면 서브에이전트 rollout도 검색하되 부모 복제본은 접어서 표시한다.
    include_system=True면 시스템 주입 레코드도 [주입] 태그와 함께 보여준다.
    """
    rx = re.compile(pattern, re.I)

    # **순위 (2026-08-24 신설).** 이전에는 파일을 순서대로 읽다가 max_hits에서 멈췄다.
    # 그 결과 언제나 **가장 오래된 N건**이 나왔다. 실측: "설계|금지"의 상위 8건이 전부
    # 05-31~06-06이었고, 찾던 07-22 발화는 1300번째였다. hit@8이 주제어 대역에서 0%.
    # "그때 그 얘기"를 찾는 도구가 정확히 반대로 동작하고 있었다.
    #
    # 최신순이 기본이다. 회상의 실제 용도가 최근 맥락 복구이기 때문이다.
    # 비용은 전수 스캔 2.2초 (543MB 단일 세션 실측). 조기 중단으로 아끼던 시간보다
    # 틀린 결과를 받는 대가가 크다.
    _br = _branches(pattern)
    if order in ("score", "recent"):
        scored = _match_stamps(pattern, sources, all_instances, thinking,
                               include_agents, include_system, role, since)
        key = (lambda x: (x[0], x[1])) if order == "score" else (lambda x: (x[1], x[0]))
        _floor = sorted(scored, key=key, reverse=True)[max_hits - 1] if len(scored) > max_hits else None
        _floorkey = key
    else:
        _floor = _floorkey = None
    hits = 0
    _seen_texts = {}
    _seen_ids = set()
    skipped_agents = skipped_system = 0
    for sname, kind, fp in _source_files(sources, all_instances):
        if hits >= max_hits:
            break
        sid = os.path.basename(fp)[:24]
        fkind, _parent, _boundary = _file_identity(fp) if kind == "codex-jsonl" else ("user", None, None)
        if fkind == "subagent" and not include_agents:
            skipped_agents += 1
            continue
        if kind == "text":
            lines = open(fp, encoding="utf-8", errors="replace").read().splitlines()
            for i, ln in enumerate(lines):
                if hits >= max_hits:
                    break
                if rx.search(ln):
                    hits += 1
                    print(f"■ 매치 {hits} · [{sname}] {os.path.basename(fp)}:{i+1}")
                    a, b = max(0, i - around), min(len(lines), i + around + 1)
                    for j in range(a, b):
                        mark = "▶" if j == i else " "
                        print(f"  {mark} {lines[j][:240]}")
                    print()
            continue
        ring = []
        pending = 0
        for line in open(fp, encoding="utf-8", errors="replace"):
            if hits >= max_hits and pending <= 0:
                break
            try:
                d = json.loads(line)
            except Exception:
                continue
            if kind == "codex-jsonl":
                got = _text_of_codex(d)
                if not got:
                    continue
                r, text, raw_ts = got
                if r == "user" and _is_system_injected(text):
                    skipped_system += 1
                    if not include_system:
                        continue
                # 부모 복제본 접기: 같은 native message id가 이미 나왔으면 건너뛴다
                _mid = ((d.get("payload") or {}).get("id"))
                if _mid:
                    if _mid in _seen_ids:
                        continue
                    _seen_ids.add(_mid)
            else:
                got = _text_of(d, include_thinking=thinking)
                if not got:
                    continue
                r, text = got
                if r == "user" and _is_system_injected(text):
                    skipped_system += 1
                    if not include_system:
                        continue
                # 컴팩션 요약은 user 레코드지만 Claude가 쓴 요약이다. 그 안에 인용된 과거 발화가
                # 요약 시각의 발화로 오독되면 T4 위치재와 같은 오귀속이 난다. 제외 대신 태그.
                if d.get("isCompactSummary") or text.startswith(
                        "This session is being continued from a previous conversation"):
                    r = "요약본"
                raw_ts = (d.get("timestamp") or "")[:16]
            ts = _kst(raw_ts)
            if since and raw_ts and raw_ts[:10] < since:
                continue
            if pending > 0:
                print(f"    {ts} {r:9s} | {text[:200].strip()}".replace(chr(10), ' '))
                pending -= 1
                if pending == 0:
                    print()
                ring.append((ts, r, text))
                ring = ring[-around:] if around else []
                continue
            if (role in (None, r)) and text and rx.search(text):
                if _floor is not None and _floorkey(
                        (_score(text, _br, rx), raw_ts or "")) < _floorkey(_floor):
                    continue          # 상위 N에 못 드는 매치
                hits += 1
                # codex rollout이 과거 히스토리를 재포함해 같은 발화가 나중 날짜로 재보고될 수
                # 있다 (8/22 실측: 7/7 대화가 8/8 rollout에 중복). 시점 판정 오염 방지 태그.
                _k = re.sub(r"\s+", " ", text.strip())[:160]
                _dup = _seen_texts.get(_k)
                _tag = ""
                if _dup and _dup[0] != sname:
                    _tag = f"  [동일 원문 — 최초 {_dup[0]} {_dup[1]}]" if _dup[1] <= ts else f"  [동일 원문 — {_dup[0]} {_dup[1]}에도 존재]"
                else:
                    _seen_texts[_k] = (sname, ts)
                print(f"■ 매치 {hits} · [{sname}] {sid} · {ts} · {r}{_tag}")
                for pts, pr, ptext in ring[-around:]:
                    print(f"    {pts} {pr:9s} | {ptext[:200].strip()}".replace(chr(10), ' '))
                print(f"  ▶ {ts} {r:9s} | {_snip(text, rx)}")
                pending = around
            ring.append((ts, r, text))
            ring = ring[-max(around, 1):]
    if not hits:
        print(f"매치 없음: /{pattern}/  — known-item 실패라면 journal에 기록할 것 (임베딩 게이트 §3.7)")
    else:
        note = []
        if skipped_agents:
            note.append(f"서브에이전트 파일 {skipped_agents}개 제외 (--include-agents)")
        if skipped_system and not include_system:
            note.append(f"시스템 주입 {skipped_system}건 제외 (--include-system)")
        print(f"({hits}건 표시, --max {max_hits}" + (" · " + " · ".join(note) if note else "") + ")")
    return 0


def sessions():
    for sname, kind, fp in _source_files(None):
        sz = os.path.getsize(fp) / 1048576
        print(f"[{sname:6s}] {os.path.basename(fp)[:52]:54s} {sz:8.1f} MB")
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("find")
    f.add_argument("pattern")
    f.add_argument("--role", choices=["user", "assistant"])
    f.add_argument("--since")
    f.add_argument("--around", type=int, default=2)
    f.add_argument("--max", type=int, default=8, dest="max_hits")
    f.add_argument("--thinking", action="store_true")
    f.add_argument("--source", default=None, help="all(기본)|claude|codex|dumps, 콤마 목록 가능")
    f.add_argument("--include-agents", action="store_true",
                   help="서브에이전트 rollout도 검색 (부모 복제본은 접힘)")
    f.add_argument("--include-system", action="store_true",
                   help="시스템 주입 레코드도 표시 (플러그인 목록·AGENTS 전문·커맨드 래퍼 등)")
    f.add_argument("--order", choices=["score","recent","oldest"], default="score",
                   help="score=매치품질(기본) · recent=최신순 · oldest=파일순(이전 동작)")
    f.add_argument("--all-instances", action="store_true",
                   help="다른 인스턴스의 Codex 세션까지 검색 (기본은 이 인스턴스만 — DR-025)")
    sub.add_parser("sessions")
    a = ap.parse_args()
    if a.cmd == "find":
        srcs = None if (a.source in (None, "all")) else set(a.source.split(","))
        return find(a.pattern, a.role, a.since, a.around, a.max_hits, a.thinking, srcs,
                    include_agents=a.include_agents, include_system=a.include_system,
                    all_instances=a.all_instances, order=a.order)
    if a.cmd == "sessions":
        return sessions()
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
