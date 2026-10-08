#!/usr/bin/env python3
"""Define instance configuration and state schemas shared by memory tools.

State rendering, retrieval, and other consumers read these definitions. Fact-ledger and worker-run schemas remain in their owning modules."""
import datetime
import hashlib
import os
import re
import urllib.parse


def _resolve_root():
    """Resolve the instance root from MOTTORI_INSTANCE or this module's location. Do not use CLAUDE_PROJECT_DIR implicitly: a runtime may set it to a nested working directory."""
    env = os.environ.get("MOTTORI_INSTANCE")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Bump the required schema version and list migration steps when the engine needs new config fields. Instance-owned config is not overwritten by updates.
SCHEMA_VERSION = 4
# Select localized migration instructions through MOTTORI_LANG.
SCHEMA_CHANGES = {
    2: {"ko": ("instance 블록 신설 — 데이터 국경의 근거값.\n"
               '      "instance": {"name": "...", "context": "work|personal", "remote_allowlist": []}\n'
               "      context가 없으면 밸브 검사가 personal로 간주하고 원격을 안 본다"),
        "en": ("new instance block: the ground truth for the data border.\n"
               '      "instance": {"name": "...", "context": "work|personal", "remote_allowlist": []}\n'
               "      without context the valve check assumes personal and ignores remotes")},
    3: {"ko": ("journal_visibility 신설 — public allowlist 밖 사건은 local-private로 fail-close.\n"
               '      "journal_visibility": {"public_tracks": ["system", "research", ...]}\n'
               "      private thread metadata는 추적 threads[]가 아니라 _private/state/threads.json에 둔다"),
        "en": ("new journal_visibility: events outside the public allowlist fail closed to local-private.\n"
               '      "journal_visibility": {"public_tracks": ["system", "research", ...]}\n'
               "      private thread metadata lives in _private/state/threads.json, not in tracked threads[]")},
    4: {"ko": ("legacy journal cutover 신설 — allowlist 추가가 과거 private-derived body를 재승격하지 않게 한다.\n"
               '      "legacy_cutoff": null|"ISO8601", "legacy_public_tracks": [...]\n'
               "      기존 인스턴스는 migration 시각과 그때의 public_tracks를 고정한다"),
        "en": ("new legacy journal cutover: adding to the allowlist must not re-promote old private-derived bodies.\n"
               '      "legacy_cutoff": null|"ISO8601", "legacy_public_tracks": [...]\n'
               "      existing instances pin the migration time and the public_tracks of that moment")},
}


def _schema_lang():
    try:
        from i18n import language
        return language()
    except Exception:  # noqa: BLE001
        return "ko"

ROOT = _resolve_root()
CONFIG_PATH = os.path.join(ROOT, "system", "memory-config.json")

CONFIG_WARNINGS = []
_CONFIG_LOAD_OK = [True]
_CONFIG_FINGERPRINT = [None]
_CONFIG_ERROR = [None]
_CONFIG_ERROR_DETAIL = [None]


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
        "egress": dict,
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
    if "remote_allowlist" in instance and not all(
            _valid_remote_allowlist_entry(x) for x in instance["remote_allowlist"]):
        raise ValueError("config.instance.remote_allowlist에 유효하지 않은 host/remote가 있음")

    egress = data.get("egress", {})
    if "model_send" in egress and not isinstance(egress["model_send"], dict):
        raise ValueError("config.egress.model_send가 object가 아님")
    model_send = egress.get("model_send", {})
    for key in ("deny_prefixes", "allow_prefixes"):
        if key in model_send and not (
                isinstance(model_send[key], list)
                and all(_valid_egress_prefix(x) for x in model_send[key])):
            raise ValueError(
                f"config.egress.model_send.{key}가 안전한 상대경로 prefix list가 아님")
    deny_prefixes = model_send.get("deny_prefixes", ["_private/"])
    allow_prefixes = model_send.get("allow_prefixes", [])
    relationship_errors = egress_prefix_relationship_errors(deny_prefixes, allow_prefixes)
    if relationship_errors:
        raise ValueError("config.egress.model_send.allow_prefixes 관계가 안전하지 않음: "
                         + "; ".join(relationship_errors))

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
        canonical = row["canonical"]
        if (os.path.isabs(canonical)
                or re.match(r"^[A-Za-z]:[/\\]", canonical)
                or canonical.startswith("\\\\")
                or ".." in re.split(r"[/\\]+", canonical)):
            raise ValueError(
                f"config.tracks[{i}].canonical이 안전한 상대경로가 아님")
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


def _valid_remote_host(host):
    """Return whether host is a syntactically bounded DNS name or IP literal."""
    if not isinstance(host, str) or not host or len(host) > 253:
        return False
    host = host.rstrip(".")
    if ":" in host:  # URL parsing strips IPv6 brackets.
        import ipaddress
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False
    label = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
    return bool(host) and all(label.match(part) for part in host.split("."))


def _valid_egress_prefix(value):
    """Model-send policy prefixes are canonical workspace-relative directories."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if (not value.endswith("/") or "\\" in value or value.startswith(("/", "./"))
            or re.match(r"^[A-Za-z]:", value)
            or ".." in value.split("/")):
        return False
    return all(part not in ("", ".", "..") for part in value[:-1].split("/"))


def egress_prefix_relationship_errors(deny_prefixes, allow_prefixes):
    """Each allow must narrow a deny and may not override an equal or deeper deny."""
    errors = []
    for allow in allow_prefixes:
        ancestors = [deny for deny in deny_prefixes if allow.startswith(deny) and allow != deny]
        unsafe = [deny for deny in deny_prefixes if deny.startswith(allow)]
        if not ancestors:
            errors.append(f"allow_prefixes {allow!r} is not strictly below a deny prefix")
        if unsafe:
            errors.append(f"allow_prefixes {allow!r} is equal to or above deny {unsafe!r}")
    return errors


def _valid_remote_allowlist_entry(value):
    """Accept hosts, remote URLs/scp forms, and explicit local repository paths."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith(("/", "~/", "./", "../")):
        return True
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        try:
            parsed = urllib.parse.urlsplit(value)
            host = parsed.hostname
        except ValueError:
            return False
        return _valid_remote_host(host)
    scp = re.match(r"^(?:[^@/:\s]+@)?([^@/:\s]+):(.+)$", value)
    if scp:
        return _valid_remote_host(scp.group(1)) and not any(c.isspace() for c in scp.group(2))
    host, _, path = value.partition("/")
    return (_valid_remote_host(host)
            and not any(c.isspace() for c in path)
            and not value.startswith(("?", "#")))


def _load_config():
    """Load wiring data from config. Report missing or invalid configuration and use safe built-in defaults so diagnostics remain available."""
    import json as _json
    try:
        raw = open(CONFIG_PATH, "rb").read()
        _CONFIG_FINGERPRINT[0] = hashlib.sha256(raw).hexdigest()
        return _validate_config_shape(_json.loads(raw.decode("utf-8")))
    except FileNotFoundError:
        _CONFIG_LOAD_OK[0] = False
        _CONFIG_ERROR[0] = "missing"
        _CONFIG_ERROR_DETAIL[0] = f"config missing: {CONFIG_PATH}"
        _CONFIG_FINGERPRINT[0] = config_fingerprint(CONFIG_PATH)
        CONFIG_WARNINGS.append(f"config 없음: {CONFIG_PATH}")
        return {}
    except Exception as e:
        _CONFIG_LOAD_OK[0] = False
        _CONFIG_ERROR[0] = "invalid"
        _CONFIG_ERROR_DETAIL[0] = str(e)
        if _CONFIG_FINGERPRINT[0] is None:
            _CONFIG_FINGERPRINT[0] = config_fingerprint(CONFIG_PATH)
        CONFIG_WARNINGS.append(f"config 로드/검증 실패: {type(e).__name__}")
        return {}


_CFG = _load_config()
CONFIG_LOAD_OK = _CONFIG_LOAD_OK[0]
CONFIG_FINGERPRINT = _CONFIG_FINGERPRINT[0]
CONFIG_ERROR = _CONFIG_ERROR[0]
CONFIG_ERROR_DETAIL = _CONFIG_ERROR_DETAIL[0]


def _expand(path):
    """Resolve config path placeholders; TRANSCRIPTS is rebound after its derived path is available."""
    return os.path.expanduser(path.replace("{ROOT}", ROOT)
                                  .replace("{TRANSCRIPTS}", _TRANSCRIPTS_LAZY[0] or ""))


_TRANSCRIPTS_LAZY = [None]


def transcript_dir(root=None):
    """Derive the Claude transcript directory from the instance root.

    Replace every character except ASCII letters, digits, and hyphens with a hyphen. Non-ASCII names can collide under this encoding. If the derived path is absent, use a unique suffix match; do not choose among multiple candidates."""
    root = root or ROOT
    base = os.path.expanduser("~/.claude/projects")
    key = mangle_project_key(root)
    derived = os.path.join(base, key)
    if os.path.isdir(derived):
        return derived
    # If the derived directory is absent, try a unique suffix match.
    tail = mangle_project_key(os.path.basename(root))
    if os.path.isdir(base) and tail.strip("-"):
        hits = [d for d in os.listdir(base) if d.endswith(tail)]
        if len(hits) == 1:
            return os.path.join(base, hits[0])
    return derived  # Keep the missing path so diagnostics can report it.


def mangle_project_key(path):
    """Encode a Claude project-directory key using ASCII letters, digits, and hyphens."""
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


STATE = os.path.join(ROOT, "state")
NOW_PATH = os.path.join(STATE, "NOW.md")
PRIVATE_STATE = os.path.join(ROOT, "_private", "state")
PRIVATE_NOW_PATH = os.path.join(PRIVATE_STATE, "NOW.md")
PRIVATE_THREADS_PATH = os.path.join(PRIVATE_STATE, "threads.json")
DECISIONS = os.path.join(ROOT, "system", "decisions.md")
TRANSCRIPTS = transcript_dir()
_TRANSCRIPTS_LAZY[0] = TRANSCRIPTS

# Instance context controls remote-policy diagnostics.
_INST = _CFG.get("instance", {})
INSTANCE_NAME = _INST.get("name", os.path.basename(ROOT))
INSTANCE_CONTEXT = _INST.get("context", "personal")   # personal | work
REMOTE_ALLOWLIST = _INST.get("remote_allowlist", [])
CONFIG_SCHEMA = _CFG.get("schema_version", 1)   # Default to schema version 1 for configs predating the instance block.

# Model-send policy is independent of Git visibility and has safe defaults for old configs.
_DEFAULT_EGRESS_MODEL_SEND = {"deny_prefixes": ["_private/"], "allow_prefixes": []}
_MODEL_SEND = _CFG.get("egress", {}).get("model_send", {})
EGRESS_MODEL_SEND = {
    "deny_prefixes": list(_MODEL_SEND.get(
        "deny_prefixes", _DEFAULT_EGRESS_MODEL_SEND["deny_prefixes"])),
    "allow_prefixes": list(_MODEL_SEND.get(
        "allow_prefixes", _DEFAULT_EGRESS_MODEL_SEND["allow_prefixes"])),
}


def schema_gap():
    """Return (current version, required version, migration steps), or None when current."""
    if CONFIG_SCHEMA >= SCHEMA_VERSION:
        return None
    lang = _schema_lang()
    todo = [f"v{v}: {SCHEMA_CHANGES[v].get(lang, SCHEMA_CHANGES[v]['ko'])}" for v in sorted(SCHEMA_CHANGES)
            if CONFIG_SCHEMA < v <= SCHEMA_VERSION]
    return CONFIG_SCHEMA, SCHEMA_VERSION, todo

# Retrieval sources: claude-jsonl, codex-jsonl, or plain text; defaults use the instance.
# Private dumps may be read within the session, but must not be quoted in artifacts or committed.
_DEFAULT_SOURCES = [
    ("claude", "claude-jsonl", TRANSCRIPTS, "*.jsonl"),
    ("codex",  "codex-jsonl",  os.path.expanduser("~/.codex/sessions"), "**/*.jsonl"),
    ("codex",  "codex-jsonl",  os.path.expanduser("~/.codex/archived_sessions"), "**/*.jsonl"),
]
# Only this instance's previous roots belong here; unrelated roots would cross the data boundary.
ROOT_ALIASES = [_expand(x) for x in (_CFG.get("instance", {}).get("root_aliases") or [])]

EPISODIC_SOURCES = ([(x["name"], x["kind"], _expand(x["base"]), x["glob"])
                     for x in _CFG.get("episodic_sources", [])] or _DEFAULT_SOURCES)

# ------------------------------------------------------------------ journal

# Journal rows: - <ISO8601> [<track>/<type>] <single-line body> followed by optional references. Types distinguish decisions, state, artifacts, corrections, lessons, switches, and ideas.
JOURNAL_TYPES = tuple(_CFG.get("journal_types",
    ("decision", "state", "artifact", "correction", "lesson", "switch", "idea")))
JOURNAL_LINE = re.compile(
    r"^- (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}))"
    r" \[(?P<track>[a-z가-힣_-]+)/(?P<type>[a-z]+)\] (?P<body>.+)$"
)

# Keep privacy classification separate from the track-display registry.
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
    """Select a new event's physical journal path. There is no override that promotes private content to public."""
    if force_private:
        return "private"
    return "public" if track in PUBLIC_JOURNAL_TRACKS else "private"


def journal_path(dt=None, visibility="public"):
    dt = dt or datetime.datetime.now()
    base = STATE if visibility == "public" else PRIVATE_STATE
    return os.path.join(base, f"journal-{dt:%Y-%m}.md")


def validate_line(line):
    """Return a schema error, or None for a valid journal entry."""
    m = JOURNAL_LINE.match(line.strip())
    if not m:
        return "형식 불일치: '- <ISO8601> [<track>/<type>] <내용>' 이어야 함"
    if m.group("type") not in JOURNAL_TYPES:
        return f"type '{m.group('type')}' 미정의 (허용: {', '.join(JOURNAL_TYPES)})"
    if len(m.group("body")) > 300:
        return "내용이 300자 초과 — journal은 한 줄 사건 기록이지 문서가 아님"
    return None


def _parse_journal_timestamp(value):
    """Parse the journal grammar on Python versions that reject compact UTC offsets."""
    compact = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    return datetime.datetime.fromisoformat(compact)


def parse_journal(visibility=None, strict=False, errors=None, physical_visibilities=None):
    """Read public and local journals in time order.

    Legacy public visibility uses the frozen cutoff and allowlist, so a later allowlist expansion cannot promote old private content. Events physically stored in the private journal remain private."""
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
            raw_bytes = open(path, "rb").read()
            boundary_errors = []
            if raw_bytes.startswith(b"\xef\xbb\xbf"):
                boundary_errors.append("UTF-8 BOM 금지")
            if raw_bytes and not raw_bytes.endswith(b"\n"):
                boundary_errors.append("마지막 줄 개행 없음")
            for boundary_error in boundary_errors:
                message = f"{path}:1: {boundary_error}"
                if strict:
                    raise ValueError("journal 손상: " + message)
                errors.append(message)
            text = raw_bytes.decode("utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
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
                    row_dt = _parse_journal_timestamp(row["ts"])
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
                    row.update(visibility=scope, source=path, order=order, _parsed_dt=row_dt)
                    out.append(row)
                order += 1
    out.sort(key=lambda e: (e["_parsed_dt"], e["order"]))
    for row in out:
        del row["_parsed_dt"]
    return out


def lock_path():
    """Return the repository state-lock path, including when a test overrides STATE."""
    return os.path.join(STATE, ".journal.lock")


class StateLockTimeout(TimeoutError):
    pass


def locked(path=None, timeout=10.0):
    """Serialize journal appends and snapshot publication for one repository."""
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
    """Fsync a sibling temporary file and atomically replace the destination. Preserve the previous complete file if writing fails."""
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
            pass  # Some filesystems lack directory fsync; atomic replacement still holds.
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
    """Truncate the middle at UTF-8 boundaries, preserving the header and newest tail."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    marker = f"\n\n[… 중간 절단: 원문 {len(raw)} bytes …]\n\n"
    marker_n = len(marker.encode("utf-8"))
    room = max(0, max_bytes - marker_n)
    head = _utf8_prefix(text, int(room * 0.42))
    tail = _utf8_suffix(text, room - len(head.encode("utf-8")))
    # Prefer line boundaries without increasing the retained byte count.
    if "\n" in head:
        head = head[:head.rfind("\n") + 1]
    if "\n" in tail:
        tail = tail[tail.find("\n") + 1:]
    out = head.rstrip() + marker + tail.lstrip()
    return _utf8_prefix(out, max_bytes)


# ------------------------------------------------------------------- tracks

# Tracks are instance data with no built-in defaults. Public NOW contains only a pointer for private content.
TRACKS = [(x["key"], x["name"], x["canonical"]) for x in _CFG.get("tracks", [])]
if not TRACKS:
    CONFIG_WARNINGS.append("tracks 미정의 — NOW 온도판이 빈다")
PERSONAL_POINTER = _CFG.get("personal_pointer")

# Tracks can have secondary canonical documents. The temperature view uses the primary;
# the pointer block prints both.
_ALSO = {x["key"]: x.get("also", []) for x in _CFG.get("tracks", [])}


def track_also(key):
    return _ALSO.get(key, [])


# Checker inventories are instance data; checker logic remains in its tools.
_CHECKS = _CFG.get("checks", {})


def check_config(key, default=None):
    v = _CHECKS.get(key)
    return default if v is None else v

UPDATED_RE = re.compile(r"(마지막 갱신|마지막 업데이트|마지막 정비)[:：]?\s*(.+)")

# ------------------------------------------------------------------ threads

# Deep-thread registry. A null dossier means no dossier is assigned; no instance-specific defaults.
_PRIVATE_THREADS_FINGERPRINT = [None]
_PRIVATE_THREADS_LOAD_OK = [True]
_PUBLIC_THREADS = list(_CFG.get("threads", []))
_PUBLIC_THREAD_KEYS = {row["key"] for row in _PUBLIC_THREADS}


def _private_threads():
    """Read private thread names and dossiers from the local registry, not tracked config."""
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

# Shared fixed section order for the renderer and visualization.
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



TOOL_RUNS = os.path.join(STATE, ".tool-runs.log")


def _index_hash():
    """Hash tracked file content independently of commit identity."""
    import subprocess as _sp, hashlib as _h
    try:
        out = _sp.run(["git", "ls-files", "-s"], capture_output=True, text=True, cwd=ROOT).stdout
        return _h.sha1(out.encode()).hexdigest()[:12] if out else "-"
    except Exception:
        return "-"


def log_run(tool, result="", scope=None, ok=None):
    """Record an explicit checker run and its content identity. Internal diagnostic invocations are excluded so inspecting evidence cannot create the evidence being inspected."""
    # Do not let doctor create the explicit-run evidence it is checking.
    if os.environ.get("MOTTORI_INTERNAL_RUN"):
        return
    try:
        os.makedirs(STATE, exist_ok=True)
        ts = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        # Use the checker's actual input hash when supplied, otherwise the index content hash. Record whether it passed; mere execution is not verification.
        head = scope or _index_hash()
        with open(TOOL_RUNS, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{tool}\t{head}\t{result}\t{'ok' if ok else 'ng' if ok is not None else '-'}\n")
    except Exception:
        pass          # Failure to record evidence must not stop the checker.


def last_run(tool):
    """Return the last (timestamp, content hash), or (None, None) when absent."""
    if not os.path.exists(TOOL_RUNS):
        return (None, None)
    hit = (None, None)
    for line in open(TOOL_RUNS, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3 and parts[1] == tool:
            hit = (parts[0], parts[2])
    return hit


def verified_now(tool):
    """Return whether the tool ran against this content identity."""
    return ran_at_head(tool, _index_hash())


def ran_at_head(tool, head, require_ok=True):
    """Return whether the tool passed against this content identity. A failed run is not verification, so require_ok defaults to true."""
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
