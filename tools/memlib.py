#!/usr/bin/env python3
"""memlib — 세션·기억·상태 아키텍처의 스키마 정본.

PRD: system/PRD-session-memory.md (v3) §9.
이 파일이 유일한 스키마 정의처다. now.py·recall.py·정원사·memory-map이 전부
여기서 import 한다. 스키마 변경은 반드시 system/decisions.md에 DR로 남긴다.
"""
import os
import re
import datetime

import sys


def _resolve_root():
    """인스턴스 루트를 정한다. 규칙 둘, 마법 없음 (DR-025).

    1. `MOTTORI_INSTANCE` 환경변수 — 도구가 인스턴스 밖(형제 킷 디렉토리)에 살 때
    2. `__file__` 유도 — 도구가 인스턴스 안에 있을 때 (기본 배치)

    훅은 `$CLAUDE_PROJECT_DIR/tools/now.py`를 호출하므로 2번이 자동으로 맞다.
    `CLAUDE_PROJECT_DIR`를 여기서 암묵적으로 읽지 않는 이유: 하위 디렉토리에서
    시작된 세션(예: research/radar)이 루트를 그 하위로 잘못 잡는다.
    """
    env = os.environ.get("MOTTORI_INSTANCE")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 킷이 기대하는 설정 스키마 버전 (KIT-DR-005).
# 엔진이 새 필드를 요구하게 되면 여기를 올리고 SCHEMA_CHANGES에 무엇을 해야 하는지 적는다.
# 인스턴스는 pull로 엔진만 받으므로, 자기 config는 스스로 고쳐야 한다. doctor가 그걸 알린다.
# 2026-08-24 실측: instance.context를 추가했을 때 옛 config는 그 필드가 없어 밸브가
# 조용히 꺼진 채로 돌 뻔했다. 조용한 뒤처짐이 이 상수의 존재 이유다.
SCHEMA_VERSION = 2
SCHEMA_CHANGES = {
    2: ("instance 블록 신설 — 데이터 국경의 근거값.\n"
        '      "instance": {"name": "...", "context": "work|personal", "remote_allowlist": []}\n'
        "      context가 없으면 밸브 검사가 personal로 간주하고 원격을 안 본다"),
}

ROOT = _resolve_root()
CONFIG_PATH = os.path.join(ROOT, "system", "memory-config.json")

CONFIG_WARNINGS = []


def _load_config():
    """배선 데이터를 JSON에서 읽는다 (DR-014). 데이터=config, 로직=이 파일.
    config가 없거나 깨져도 도구는 죽지 않는다 — 내장 기본값으로 동작하고 경고만 낸다.
    (계기는 자기 설정 오류로 침묵하면 안 된다 — 되먹임 렌즈의 fail-safe 원칙.)"""
    import json as _json
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return _json.load(f)
    except FileNotFoundError:
        CONFIG_WARNINGS.append(f"config 없음: {CONFIG_PATH}")
        return {}
    except Exception as e:
        CONFIG_WARNINGS.append(f"config 파싱 실패: {e}")
        print(f"[memlib] config 파싱 실패, 내장 기본값 사용: {e}", file=sys.stderr)
        return {}


_CFG = _load_config()


def _expand(path):
    """config의 경로 자리표시자를 푼다. `{TRANSCRIPTS}`는 아래에서 정의된 뒤 다시 바인딩된다."""
    return os.path.expanduser(path.replace("{ROOT}", ROOT)
                                  .replace("{TRANSCRIPTS}", _TRANSCRIPTS_LAZY[0] or ""))


_TRANSCRIPTS_LAZY = [None]


def transcript_dir(root=None):
    """Claude Code 전사 디렉토리를 인스턴스 경로에서 **유도**한다 (DR-025).

    맹글링 규칙: **영숫자와 하이픈이 아닌 모든 문자를 `-`로** 치환.
    2026-08-24 실측으로 확정했다. 특수문자를 섞은 디렉토리에서 실제 세션을 돌려
    Claude Code가 만든 키와 대조: `k a.b_c-d킷` -> `k-a-b-c-d-`.
    즉 `/` `_` `.` 공백 한글이 전부 하이픈이 된다.

    *처음엔 `[/_]`만으로 잡았다가 틀렸다.* 표본 12개가 전부 영숫자 경로여서 규칙이
    과소적합했다. 공백이나 점이 든 경로(`~/My Work/kit`, `~/work.v2`)에서 조용히
    빈 결과가 났을 것이다 — 이 함수가 막으려던 바로 그 실패다.

    **한글 경로 주의:** 한글은 전부 하이픈이 되므로 서로 다른 한글 이름이 같은 키로
    충돌할 수 있다 (`킷한글`과 `킷영문` 둘 다 `---`). 그래서 유도 실패 시 글롭으로
    되짚되, 후보가 둘 이상이면 판정을 포기하고 부재를 보고한다.

    이 값을 설정으로 받지 않는 이유: 설정이면 이식 때 사람이 고쳐야 하고,
    안 고치면 **조용히 빈 결과**가 나온다. 회상이 0건인데 도구는 정상 종료한다.
    """
    root = root or ROOT
    base = os.path.expanduser("~/.claude/projects")
    key = mangle_project_key(root)
    derived = os.path.join(base, key)
    if os.path.isdir(derived):
        return derived
    # 유도 실패: 규칙이 바뀌었거나 세션을 아직 안 돌렸다. 끝 세그먼트로 되짚는다.
    tail = mangle_project_key(os.path.basename(root))
    if os.path.isdir(base) and tail.strip("-"):
        hits = [d for d in os.listdir(base) if d.endswith(tail)]
        if len(hits) == 1:
            return os.path.join(base, hits[0])
    return derived  # 없으면 없는 경로를 그대로 — 호출부(doctor)가 부재를 보고한다


def mangle_project_key(path):
    """Claude Code의 프로젝트 디렉토리 이름 규칙 (2026-08-24 실측)."""
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


STATE = os.path.join(ROOT, "state")
NOW_PATH = os.path.join(STATE, "NOW.md")
DECISIONS = os.path.join(ROOT, "system", "decisions.md")
TRANSCRIPTS = transcript_dir()
_TRANSCRIPTS_LAZY[0] = TRANSCRIPTS

# 인스턴스 정체 (DR-026). context는 단방향 밸브의 근거값 — doctor가 이걸로 원격을 검사한다.
_INST = _CFG.get("instance", {})
INSTANCE_NAME = _INST.get("name", os.path.basename(ROOT))
INSTANCE_CONTEXT = _INST.get("context", "personal")   # personal | work
REMOTE_ALLOWLIST = _INST.get("remote_allowlist", [])
CONFIG_SCHEMA = _CFG.get("schema_version", 1)   # 없으면 1 (instance 블록 이전)


def schema_gap():
    """config가 엔진보다 뒤처졌으면 (현재, 기대, 해야 할 일 목록)을 준다. 아니면 None."""
    if CONFIG_SCHEMA >= SCHEMA_VERSION:
        return None
    todo = [f"v{v}: {SCHEMA_CHANGES[v]}" for v in sorted(SCHEMA_CHANGES)
            if CONFIG_SCHEMA < v <= SCHEMA_VERSION]
    return CONFIG_SCHEMA, SCHEMA_VERSION, todo

# 에피소드 소스 레지스트리 (DR-013). recall이 이것만 본다 — 소스 추가는 여기 한 줄.
#  kind: claude-jsonl(type=user/assistant) · codex-jsonl(response_item/payload.message)
#        · text(플레인 md/txt, 파일:줄 단위)
# 주의: dumps는 _private 등급 — 세션 내 열람만, 산출물·커밋에 인용 금지 (코어 1).
#  이 기본값은 인스턴스 독립이다 (경로가 전부 유도값). tracks·threads와 달리 폴백해도 안전하다.
_DEFAULT_SOURCES = [
    ("claude", "claude-jsonl", TRANSCRIPTS, "*.jsonl"),
    ("codex",  "codex-jsonl",  os.path.expanduser("~/.codex/sessions"), "**/*.jsonl"),
]
EPISODIC_SOURCES = ([(x["name"], x["kind"], _expand(x["base"]), x["glob"])
                     for x in _CFG.get("episodic_sources", [])] or _DEFAULT_SOURCES)

# ------------------------------------------------------------------ journal

# 한 줄 문법:  - <ISO8601+09:00> [<track>/<type>] <내용 한 줄> (→ ref)*
# 소급 기입은 내용 끝에 "(소급)" 표기 (DR-003).
# type 의미: decision(결정→dr:NNN) · state(국면) · artifact(산출물) · correction(정정)
# · lesson(교훈, 마주치는 자리에 사본) · switch(전환) · idea(발산 적립→P4 심사)
JOURNAL_TYPES = tuple(_CFG.get("journal_types",
    ("decision", "state", "artifact", "correction", "lesson", "switch", "idea")))
JOURNAL_LINE = re.compile(
    r"^- (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2})?)"
    r" \[(?P<track>[a-z가-힣_-]+)/(?P<type>[a-z]+)\] (?P<body>.+)$"
)


def journal_path(dt=None):
    dt = dt or datetime.datetime.now()
    return os.path.join(STATE, f"journal-{dt:%Y-%m}.md")


def validate_line(line):
    """스키마 위반이면 이유 문자열, 통과면 None. 쓰기 시점 검증 (PRD §9)."""
    m = JOURNAL_LINE.match(line.strip())
    if not m:
        return "형식 불일치: '- <ISO8601> [<track>/<type>] <내용>' 이어야 함"
    if m.group("type") not in JOURNAL_TYPES:
        return f"type '{m.group('type')}' 미정의 (허용: {', '.join(JOURNAL_TYPES)})"
    if len(m.group("body")) > 300:
        return "내용이 300자 초과 — journal은 한 줄 사건 기록이지 문서가 아님"
    return None


def parse_journal():
    """모든 journal 파일의 엔트리를 시간순으로 돌려준다."""
    out = []
    if not os.path.isdir(STATE):
        return out
    for f in sorted(os.listdir(STATE)):
        if not re.match(r"journal-\d{4}-\d{2}\.md$", f):
            continue
        for line in open(os.path.join(STATE, f), encoding="utf-8"):
            m = JOURNAL_LINE.match(line.strip())
            if m:
                out.append(m.groupdict())
    out.sort(key=lambda e: e["ts"])
    return out


# ------------------------------------------------------------------- tracks

# NOW의 온도판은 여기 등록된 정본에서 추출한다. personal은 포인터만 —
# NOW.md는 git 추적 파일(DR D4)이므로 _private 내용을 절대 싣지 않는다.
#
# **여기에 내장 기본값을 두지 않는다** (DR-025). 트랙은 인스턴스 고유값이라
# 폴백은 남의 리포 경로를 가리키게 된다. 빈 채로 두고 경고하는 편이 낫다 —
# 조용히 틀린 값보다 시끄럽게 빈 값이 싸다.
TRACKS = [(x["key"], x["name"], x["canonical"]) for x in _CFG.get("tracks", [])]
if not TRACKS:
    CONFIG_WARNINGS.append("tracks 미정의 — NOW 온도판이 빈다")
PERSONAL_POINTER = _CFG.get("personal_pointer")

# 트랙의 보조 정본 (예: 비자 = TODO.md + messages.md). 온도판은 canonical만 보고,
# 포인터 블록은 둘 다 인쇄한다.
_ALSO = {x["key"]: x.get("also", []) for x in _CFG.get("tracks", [])}


def track_also(key):
    return _ALSO.get(key, [])


# 검사기(linkcheck·coherence)가 쓰는 인스턴스 고유 목록. 로직은 도구에, 목록은 여기에.
_CHECKS = _CFG.get("checks", {})


def check_config(key, default=None):
    v = _CHECKS.get(key)
    return default if v is None else v

UPDATED_RE = re.compile(r"(마지막 갱신|마지막 업데이트|마지막 정비)[:：]?\s*(.+)")

# ------------------------------------------------------------------ threads

# 스레드 서류철 레지스트리 (PRD §3.3). dossier=None 이면 미지정.
# tracks와 같은 이유로 내장 기본값 없음 (DR-025).
THREADS = [(x["key"], x["name"], x.get("dossier")) for x in _CFG.get("threads", [])]

# ---------------------------------------------------------------------- NOW

# NOW 섹션 고정 순서 (PRD §9). 이 상수가 렌더러와 시각화의 공통 정본.
NOW_SECTIONS = [
    "트랙 온도판",
    "살아 있는 스레드 (서류철)",
    "최근 결정·국면",
    "최근 사건",
    "정본 포인터",
]
_TH = _CFG.get("thresholds", {})
NOW_TAIL_EVENTS = _TH.get("now_tail_events", 12)
NOW_RECENT_DECISIONS = _TH.get("now_recent_decisions", 8)
TRACK_STALE_DAYS = _TH.get("track_stale_days", 7)
JOURNAL_STALE_DAYS = _TH.get("journal_stale_days", 2)
MEMORY_ROT_DAYS = _TH.get("memory_rot_days", 14)
NOW_HOOK_MAX_BYTES = _TH.get("now_hook_max_bytes", 6000)

# ------------------------------------------------------------------- 실행 기록

TOOL_RUNS = os.path.join(STATE, ".tool-runs.log")


def log_run(tool, result=""):
    """검사기가 돌았다는 사실을 남긴다 (DR-033).

    왜 필요한가. 2026-08-24에 새 산출물(킷)을 만들고 `linkcheck`를 안 돌려 깨진 참조 27개가
    통과했다. 그런데 **"안 돌렸다"를 아무도 모른다** — 도구 실행에 기록이 없기 때문이다.
    사람이 세기로 한 것은 안 세어진다는 것이 오늘의 반복 교훈이라, 기계가 남긴다.
    """
    # doctor가 자기 검사로 호출한 경우는 기록하지 않는다. 안 그러면 "누가 일부러 돌렸다"와
    # "계측기가 자기 검사로 돌렸다"를 구별할 수 없어 미스 검출기가 언제나 통과한다
    # (2026-08-24 실측: 첫 판이 정확히 이 이유로 오늘의 실패를 재현했는데 못 잡았다).
    if os.environ.get("MOTTORI_INTERNAL_RUN"):
        return
    try:
        os.makedirs(STATE, exist_ok=True)
        ts = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        with open(TOOL_RUNS, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{tool}\t{result}\n")
    except Exception:
        pass          # 기록 실패가 검사를 막으면 안 된다


def last_run(tool):
    """이 도구가 마지막으로 돈 시각 (ISO). 기록이 없으면 None."""
    if not os.path.exists(TOOL_RUNS):
        return None
    hit = None
    for line in open(TOOL_RUNS, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[1] == tool:
            hit = parts[0]
    return hit


# ----------------------------------------------------------------------- DR

DR_HEADER = re.compile(r"^### DR-(\d{3}) (.+) \((\d{4}-\d{2}-\d{2}) · (active|superseded_by:DR-\d{3})\)")
