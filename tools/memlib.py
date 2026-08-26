#!/usr/bin/env python3
"""memlib — 세션·기억·상태 아키텍처의 스키마 정본.

PRD: system/PRD-session-memory.md (v3) §9.
이 파일이 유일한 스키마 정의처다. now.py·recall.py·정원사·memory-map이 전부
여기서 import 한다. 스키마 변경은 반드시 system/decisions.md에 DR로 남긴다.
"""
import datetime
import hashlib
import os
import re


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
SCHEMA_VERSION = 4
SCHEMA_CHANGES = {
    2: ("instance 블록 신설 — 데이터 국경의 근거값.\n"
        '      "instance": {"name": "...", "context": "work|personal", "remote_allowlist": []}\n'
        "      context가 없으면 밸브 검사가 personal로 간주하고 원격을 안 본다"),
    3: ("journal_visibility 신설 — public allowlist 밖 사건은 local-private로 fail-close.\n"
        '      "journal_visibility": {"public_tracks": ["system", "research", ...]}\n'
        "      private thread metadata는 추적 threads[]가 아니라 _private/state/threads.json에 둔다"),
    4: ("legacy journal cutover 신설 — allowlist 추가가 과거 private-derived body를 재승격하지 않게 한다.\n"
        '      "legacy_cutoff": null|"ISO8601", "legacy_public_tracks": [...]\n'
        "      기존 인스턴스는 migration 시각과 그때의 public_tracks를 고정한다"),
}

ROOT = _resolve_root()
CONFIG_PATH = os.path.join(ROOT, "system", "memory-config.json")

CONFIG_WARNINGS = []
_CONFIG_LOAD_OK = [True]
_CONFIG_FINGERPRINT = [None]


def file_fingerprint(path, missing_marker=b"<missing>"):
    """Content identity for an input file without trusting its mtime."""
    try:
        raw = open(path, "rb").read()
    except FileNotFoundError:
        raw = missing_marker
    except OSError as e:
        raw = f"<unreadable:{type(e).__name__}>".encode()
    return hashlib.sha256(raw).hexdigest()


def config_fingerprint(path=None):
    """Content identity for the exact config snapshot a process is using."""
    return file_fingerprint(path or CONFIG_PATH, b"<missing-config>")


# Hash the bytes this process imported, not whatever happens to be on disk later while rendering.
# now.py verifies the live bytes still match before publish; the pair prevents old code from
# certifying an output with a new source hash after a concurrent edit.
MEMLIB_SOURCE_FINGERPRINT = file_fingerprint(__file__)


def _validate_config_shape(data):
    """Privacy routing config must be an object with safe container shapes.

    Unknown keys remain forward-compatible.  Known containers are validated before any module-level
    `.get()` calls so a syntactically valid but structurally invalid JSON file fails closed instead
    of crashing import before a private journal can be written.
    """
    if not isinstance(data, dict):
        raise ValueError("config root가 object가 아님")

    containers = {
        "instance": dict,
        "episodic_sources": list,
        "tracks": list,
        "journal_visibility": dict,
        "threads": list,
        "checks": dict,
        "journal_types": list,
        "thresholds": dict,
    }
    for key, typ in containers.items():
        if key in data and not isinstance(data[key], typ):
            raise ValueError(f"config.{key}가 {typ.__name__}가 아님")
    if "schema_version" in data and (isinstance(data["schema_version"], bool)
                                      or not isinstance(data["schema_version"], int)):
        raise ValueError("config.schema_version이 int가 아님")

    instance = data.get("instance", {})
    if "remote_allowlist" in instance and not isinstance(instance["remote_allowlist"], list):
        raise ValueError("config.instance.remote_allowlist가 list가 아님")

    for i, row in enumerate(data.get("episodic_sources", [])):
        if not isinstance(row, dict):
            raise ValueError(f"config.episodic_sources[{i}]가 object가 아님")
        for key in ("name", "kind", "base", "glob"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"config.episodic_sources[{i}].{key}가 비어 있음")

    for i, row in enumerate(data.get("tracks", [])):
        if not isinstance(row, dict):
            raise ValueError(f"config.tracks[{i}]가 object가 아님")
        for key in ("key", "name", "canonical"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"config.tracks[{i}].{key}가 비어 있음")
        if "also" in row and not (isinstance(row["also"], list)
                                   and all(isinstance(x, str) for x in row["also"])):
            raise ValueError(f"config.tracks[{i}].also가 string list가 아님")

    for i, row in enumerate(data.get("threads", [])):
        if not isinstance(row, dict):
            raise ValueError(f"config.threads[{i}]가 object가 아님")
        for key in ("key", "name"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"config.threads[{i}].{key}가 비어 있음")
        if row.get("dossier") is not None and not isinstance(row.get("dossier"), str):
            raise ValueError(f"config.threads[{i}].dossier가 string/null이 아님")
        visibility = row.get("visibility", "public")
        if visibility == "private":
            raise ValueError(
                f"config.threads[{i}] private metadata 금지 — _private/state/threads.json으로 이동")
        if visibility != "public":
            raise ValueError(f"config.threads[{i}].visibility={visibility!r} 미지원")

    visibility = data.get("journal_visibility", {})
    if "public_tracks" in visibility and not (
            isinstance(visibility["public_tracks"], list)
            and all(isinstance(x, str) and x for x in visibility["public_tracks"])):
        raise ValueError("config.journal_visibility.public_tracks가 non-empty string list가 아님")
    legacy_tracks = visibility.get("legacy_public_tracks")
    if legacy_tracks is not None and not (
            isinstance(legacy_tracks, list)
            and all(isinstance(x, str) and x for x in legacy_tracks)):
        raise ValueError("config.journal_visibility.legacy_public_tracks가 string list가 아님")
    legacy_cutoff = visibility.get("legacy_cutoff")
    if legacy_cutoff is not None:
        if not isinstance(legacy_cutoff, str):
            raise ValueError("config.journal_visibility.legacy_cutoff가 ISO8601/null이 아님")
        try:
            parsed_cutoff = datetime.datetime.fromisoformat(legacy_cutoff)
        except ValueError as e:
            raise ValueError("config.journal_visibility.legacy_cutoff가 ISO8601이 아님") from e
        if parsed_cutoff.utcoffset() is None:
            raise ValueError("config.journal_visibility.legacy_cutoff에 timezone이 없음")
    if data.get("schema_version", 1) >= 4 and not all(
            key in visibility for key in ("legacy_cutoff", "legacy_public_tracks")):
        raise ValueError("schema v4 journal_visibility legacy fields 누락")
    if legacy_cutoff is None and legacy_tracks:
        raise ValueError("legacy_cutoff=null인데 legacy_public_tracks가 비어 있지 않음")
    if "journal_types" in data and not (
            data["journal_types"] and all(isinstance(x, str) and x for x in data["journal_types"])):
        raise ValueError("config.journal_types가 non-empty string list가 아님")
    if "personal_pointer" in data and data["personal_pointer"] is not None \
            and not isinstance(data["personal_pointer"], str):
        raise ValueError("config.personal_pointer가 string/null이 아님")
    thresholds = data.get("thresholds", {})
    for key, value in thresholds.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"config.thresholds.{key}가 non-negative int가 아님")
    for key in ("now_tail_events", "now_recent_decisions"):
        if key in thresholds and thresholds[key] < 1:
            raise ValueError(f"config.thresholds.{key}가 positive int가 아님")
    for key in ("now_max_bytes", "now_hook_max_bytes"):
        if key in thresholds and not 1024 <= thresholds[key] <= 6000:
            raise ValueError(f"config.thresholds.{key}가 1024..6000 범위가 아님")
    return data


def _load_config():
    """배선 데이터를 JSON에서 읽는다 (DR-014). 데이터=config, 로직=이 파일.
    config가 없거나 깨져도 도구는 죽지 않는다 — 내장 기본값으로 동작하고 경고만 낸다.
    (계기는 자기 설정 오류로 침묵하면 안 된다 — 되먹임 렌즈의 fail-safe 원칙.)"""
    import json as _json
    try:
        raw = open(CONFIG_PATH, "rb").read()
        _CONFIG_FINGERPRINT[0] = hashlib.sha256(raw).hexdigest()
        return _validate_config_shape(_json.loads(raw.decode("utf-8")))
    except FileNotFoundError:
        _CONFIG_LOAD_OK[0] = False
        _CONFIG_FINGERPRINT[0] = config_fingerprint(CONFIG_PATH)
        CONFIG_WARNINGS.append(f"config 없음: {CONFIG_PATH}")
        return {}
    except Exception as e:
        _CONFIG_LOAD_OK[0] = False
        if _CONFIG_FINGERPRINT[0] is None:
            _CONFIG_FINGERPRINT[0] = config_fingerprint(CONFIG_PATH)
        CONFIG_WARNINGS.append(f"config 로드/검증 실패: {type(e).__name__}")
        return {}


_CFG = _load_config()
CONFIG_LOAD_OK = _CONFIG_LOAD_OK[0]
CONFIG_FINGERPRINT = _CONFIG_FINGERPRINT[0]


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
PRIVATE_STATE = os.path.join(ROOT, "_private", "state")
PRIVATE_NOW_PATH = os.path.join(PRIVATE_STATE, "NOW.md")
PRIVATE_THREADS_PATH = os.path.join(PRIVATE_STATE, "threads.json")
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
    r"^- (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}))"
    r" \[(?P<track>[a-z가-힣_-]+)/(?P<type>[a-z]+)\] (?P<body>.+)$"
)

# TRACKS는 NOW 온도판 레지스트리다. 보안 분류를 거기에 겸용하면 system 같은 사건 namespace를
# canonical 문서가 있는 track으로 오인한다. 별도 allowlist가 이 경계를 소유한다 (DR-043).
_VIS = _CFG.get("journal_visibility", {})
_PUBLIC_RAW = _VIS.get("public_tracks") if isinstance(_VIS, dict) else None
_LEGACY_RAW = _VIS.get("legacy_public_tracks") if isinstance(_VIS, dict) else None
_LEGACY_CUTOFF_RAW = _VIS.get("legacy_cutoff") if isinstance(_VIS, dict) else None
_VISIBILITY_READY = (CONFIG_LOAD_OK and CONFIG_SCHEMA == SCHEMA_VERSION
                     and isinstance(_PUBLIC_RAW, list)
                     and all(isinstance(x, str) and x for x in _PUBLIC_RAW)
                     and isinstance(_LEGACY_RAW, list)
                     and all(isinstance(x, str) and x for x in _LEGACY_RAW)
                     and (_LEGACY_CUTOFF_RAW is None or isinstance(_LEGACY_CUTOFF_RAW, str)))
PUBLIC_JOURNAL_TRACKS = tuple(dict.fromkeys(_PUBLIC_RAW or ())) if _VISIBILITY_READY else ()
LEGACY_PUBLIC_TRACKS = tuple(dict.fromkeys(_LEGACY_RAW or ())) if _VISIBILITY_READY else ()
LEGACY_CUTOFF = (datetime.datetime.fromisoformat(_LEGACY_CUTOFF_RAW)
                 if _VISIBILITY_READY and _LEGACY_CUTOFF_RAW else None)
VISIBILITY_READY = _VISIBILITY_READY
if not _VISIBILITY_READY:
    CONFIG_WARNINGS.append(
        "journal_visibility 사용 불가 — 새 사건은 전부 _private/state로 fail-close "
        f"(config schema={CONFIG_SCHEMA}, engine schema={SCHEMA_VERSION})")


def journal_visibility(track, force_private=False):
    """새 사건의 물리 경로를 판정한다. public으로 올리는 override는 의도적으로 없다."""
    if force_private:
        return "private"
    return "public" if track in PUBLIC_JOURNAL_TRACKS else "private"


def journal_path(dt=None, visibility="public"):
    dt = dt or datetime.datetime.now()
    base = STATE if visibility == "public" else PRIVATE_STATE
    return os.path.join(base, f"journal-{dt:%Y-%m}.md")


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


def parse_journal(visibility=None, strict=False, errors=None, physical_visibilities=None):
    """public/local journal을 합쳐 시간순으로 읽는다.

    `visibility`은 public/private/None(all). 추적 journal의 legacy 사건은 migration cutoff 당시
    고정한 public set으로 projection하므로 allowlist 확대가 과거 private body를 재승격하지 않는다.
    private 물리 파일의 사건은 public track이어도 `--private` 하향 결정을 보존한다.
    """
    out = []
    errors = errors if errors is not None else []
    order = 0
    for base, physical in ((STATE, "public"), (PRIVATE_STATE, "private")):
        if physical_visibilities is not None and physical not in physical_visibilities:
            continue
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if not re.match(r"journal-\d{4}-\d{2}\.md$", f):
                continue
            path = os.path.join(base, f)
            for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
                raw = line.strip()
                m = JOURNAL_LINE.match(raw)
                if not m:
                    if strict and raw.startswith("- "):
                        raise ValueError(f"journal 손상: {path}:{lineno}: {raw[:100]}")
                    if raw.startswith("- "):
                        errors.append(f"{path}:{lineno}: {raw[:100]}")
                    continue
                schema_error = validate_line(raw)
                if schema_error:
                    message = f"{path}:{lineno}: {schema_error}"
                    if strict:
                        raise ValueError("journal 손상: " + message)
                    errors.append(message)
                    continue
                row = m.groupdict()
                try:
                    row_dt = datetime.datetime.fromisoformat(row["ts"])
                except ValueError as e:
                    if strict:
                        raise ValueError(f"journal 손상: {path}:{lineno}: timestamp {row['ts']}") from e
                    errors.append(f"{path}:{lineno}: timestamp {row['ts']}")
                    continue
                if row_dt.utcoffset() is None:
                    message = f"{path}:{lineno}: timestamp timezone 없음"
                    if strict:
                        raise ValueError("journal 손상: " + message)
                    errors.append(message)
                    continue
                if physical == "private":
                    scope = "private"
                elif LEGACY_CUTOFF is not None and row_dt <= LEGACY_CUTOFF:
                    scope = "public" if row["track"] in LEGACY_PUBLIC_TRACKS else "private"
                else:
                    scope = journal_visibility(row["track"])
                if visibility is None or visibility == scope:
                    row.update(visibility=scope, source=path, order=order)
                    out.append(row)
                order += 1
    out.sort(key=lambda e: (e["ts"], e["order"]))
    return out


def lock_path():
    """테스트가 STATE를 재지정해도 같은 인스턴스 안에서 따라가는 repo-wide state lock."""
    return os.path.join(STATE, ".journal.lock")


class StateLockTimeout(TimeoutError):
    pass


def locked(path=None, timeout=10.0):
    """한 repo의 journal append와 snapshot publish를 직렬화하는 context manager."""
    import contextlib
    import fcntl
    import time

    @contextlib.contextmanager
    def _hold():
        p = path or lock_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a+", encoding="utf-8") as lock_file:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise StateLockTimeout(f"state lock timeout: {p}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return _hold()


def atomic_write(path, text):
    """같은 디렉터리 temp를 fsync한 뒤 replace한다. 실패하면 기존 완성본을 보존한다."""
    import tempfile

    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    old_mode = os.stat(path).st_mode & 0o777 if os.path.isfile(path) else 0o644
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=parent)
    try:
        os.fchmod(fd, old_mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
        try:
            dfd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass  # 일부 파일시스템은 directory fsync를 지원하지 않는다. replace 원자성은 유지.
    finally:
        if fd != -1:
            os.close(fd)
        if tmp is not None:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def _utf8_prefix(text, budget):
    if budget <= 0:
        return ""
    return text.encode("utf-8")[:budget].decode("utf-8", "ignore")


def _utf8_suffix(text, budget):
    if budget <= 0:
        return ""
    raw = text.encode("utf-8")
    return raw[-budget:].decode("utf-8", "ignore")


def clip_utf8(text, max_bytes):
    """UTF-8 경계에서 중간을 줄여 header와 최신 tail을 함께 보존한다."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    marker = f"\n\n[… 중간 절단: 원문 {len(raw)} bytes …]\n\n"
    marker_n = len(marker.encode("utf-8"))
    room = max(0, max_bytes - marker_n)
    head = _utf8_prefix(text, int(room * 0.42))
    tail = _utf8_suffix(text, room - len(head.encode("utf-8")))
    # 가능한 한 줄 중간을 피한다. 이 조정은 잘라내는 쪽으로만 움직인다.
    if "\n" in head:
        head = head[:head.rfind("\n") + 1]
    if "\n" in tail:
        tail = tail[tail.find("\n") + 1:]
    out = head.rstrip() + marker + tail.lstrip()
    return _utf8_prefix(out, max_bytes)


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
_PRIVATE_THREADS_FINGERPRINT = [None]
_PRIVATE_THREADS_LOAD_OK = [True]
_PUBLIC_THREADS = list(_CFG.get("threads", []))
_PUBLIC_THREAD_KEYS = {row["key"] for row in _PUBLIC_THREADS}


def _private_threads():
    """로컬 thread 이름·dossier는 추적 config가 아니라 local private thread registry에 둔다."""
    import json as _json
    try:
        raw = open(PRIVATE_THREADS_PATH, "rb").read()
        _PRIVATE_THREADS_FINGERPRINT[0] = hashlib.sha256(raw).hexdigest()
        rows = _json.loads(raw.decode("utf-8"))
        if not isinstance(rows, list):
            raise ValueError("list가 아님")
        valid = []
        private_keys = set()
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                _PRIVATE_THREADS_LOAD_OK[0] = False
                CONFIG_WARNINGS.append(f"private thread registry[{i}] object 아님 — skip")
                continue
            if not all(isinstance(row.get(k), str) and row[k] for k in ("key", "name")):
                _PRIVATE_THREADS_LOAD_OK[0] = False
                CONFIG_WARNINGS.append(f"private thread registry[{i}] key/name invalid — skip")
                continue
            if row.get("dossier") is not None and not isinstance(row.get("dossier"), str):
                _PRIVATE_THREADS_LOAD_OK[0] = False
                CONFIG_WARNINGS.append(f"private thread registry[{i}] dossier invalid — skip")
                continue
            if row["key"] in _PUBLIC_THREAD_KEYS:
                _PRIVATE_THREADS_LOAD_OK[0] = False
                CONFIG_WARNINGS.append(
                    f"private thread registry[{i}] public key collision — skip")
                continue
            if row["key"] in private_keys:
                _PRIVATE_THREADS_LOAD_OK[0] = False
                CONFIG_WARNINGS.append(
                    f"private thread registry[{i}] duplicate key — skip")
                continue
            private_keys.add(row["key"])
            valid.append(row)
        return valid
    except FileNotFoundError:
        _PRIVATE_THREADS_FINGERPRINT[0] = file_fingerprint(PRIVATE_THREADS_PATH)
        return []
    except Exception as e:
        _PRIVATE_THREADS_LOAD_OK[0] = False
        if _PRIVATE_THREADS_FINGERPRINT[0] is None:
            _PRIVATE_THREADS_FINGERPRINT[0] = file_fingerprint(PRIVATE_THREADS_PATH)
        CONFIG_WARNINGS.append(f"private thread registry 파싱 실패: {e}")
        return []


_PRIVATE_THREADS = _private_threads()
PRIVATE_THREADS_FINGERPRINT = _PRIVATE_THREADS_FINGERPRINT[0]
PRIVATE_THREADS_LOAD_OK = _PRIVATE_THREADS_LOAD_OK[0]
_THREAD_ROWS = _PUBLIC_THREADS + [dict(x, visibility="private") for x in _PRIVATE_THREADS]
THREADS = [(x["key"], x["name"], x.get("dossier")) for x in _THREAD_ROWS]
THREAD_VISIBILITY = {x["key"]: x.get("visibility", "public") for x in _THREAD_ROWS}

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
NOW_MAX_BYTES = _TH.get("now_max_bytes", 6000)

# ------------------------------------------------------------------- 실행 기록

TOOL_RUNS = os.path.join(STATE, ".tool-runs.log")


def _index_hash():
    """추적 파일 내용의 상태 해시. 커밋 여부와 무관하게 내용이 같으면 같다."""
    import subprocess as _sp, hashlib as _h
    try:
        out = _sp.run(["git", "ls-files", "-s"], capture_output=True, text=True, cwd=ROOT).stdout
        return _h.sha1(out.encode()).hexdigest()[:12] if out else "-"
    except Exception:
        return "-"


def log_run(tool, result="", scope=None, ok=None):
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
        # **추적 내용의 상태 해시**를 남긴다 (2026-08-24, codex 라운드 2 지적 반영).
        # 시각은 같은 초에서 뒤집혔고, HEAD는 더 나빴다 — 커밋 전에 제대로 검사한 것을
        # 커밋 후에 미스로 오판했다. 검사 대상은 커밋 ID가 아니라 **내용**이다.
        # `git ls-files -s`는 경로·모드·blob 해시라 내용이 바뀔 때만 바뀌고,
        # 커밋 자체로는 안 바뀐다. 그래서 사전 검증이 인정된다.
        # scope: 검사기가 실제로 읽은 것의 해시. 없으면 index 해시로 폴백.
        # ok: 검사가 통과했나. **실패한 실행을 "검증됨"으로 세면 안 된다** (codex 라운드 3).
        head = scope or _index_hash()
        with open(TOOL_RUNS, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{tool}\t{head}\t{result}\t{'ok' if ok else 'ng' if ok is not None else '-'}\n")
    except Exception:
        pass          # 기록 실패가 검사를 막으면 안 된다


def last_run(tool):
    """이 도구가 마지막으로 돈 (시각, HEAD). 기록이 없으면 (None, None)."""
    if not os.path.exists(TOOL_RUNS):
        return (None, None)
    hit = (None, None)
    for line in open(TOOL_RUNS, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3 and parts[1] == tool:
            hit = (parts[0], parts[2])
    return hit


def verified_now(tool):
    """지금 이 내용 상태에서 그 도구가 돈 적이 있나."""
    return ran_at_head(tool, _index_hash())


def ran_at_head(tool, head, require_ok=True):
    """이 상태 해시에서 그 도구가 **통과한** 적이 있나.

    `require_ok`가 기본 True인 이유: 같은 상태에서 `broken=27`로 실패한 실행도
    "기록이 있다"로 세면 검증됐다고 보고하게 된다 (codex 라운드 3 지적).
    """
    if not os.path.exists(TOOL_RUNS) or not head or head == "-":
        return False
    for line in open(TOOL_RUNS, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3 and parts[1] == tool and parts[2] == head[:12]:
            if not require_ok:
                return True
            if len(parts) >= 5 and parts[4] == "ok":
                return True
    return False


# ----------------------------------------------------------------------- DR

DR_HEADER = re.compile(r"^### DR-(\d{3}) (.+) \((\d{4}-\d{2}-\d{2}) · (active|superseded_by:DR-\d{3})\)")
