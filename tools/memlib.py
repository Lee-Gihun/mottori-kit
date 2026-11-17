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
# Migration instructions per schema version, as format templates (literal braces doubled). Text
# comes from tools/i18n.py ("memlib.schema_change_<v>"); the English value here is used when this
# module runs without the catalog, because tools/sync_engine.sh can deliver memlib.py on its own.
SCHEMA_CHANGES = {
    2: ("new instance block: the ground truth for the data border.\n"
        '      "instance": {{"name": "...", "context": "work|personal", "remote_allowlist": []}}\n'
        "      without context the valve check assumes personal and ignores remotes"),
    3: ("new journal_visibility: events outside the public allowlist fail closed to local-private.\n"
        '      "journal_visibility": {{"public_tracks": ["system", "research", ...]}}\n'
        "      private thread metadata lives in _private/state/threads.json, not in tracked threads[]"),
    4: ("new legacy journal cutover: adding to the allowlist must not re-promote old private-derived bodies.\n"
        '      "legacy_cutoff": null|"ISO8601", "legacy_public_tracks": [...]\n'
        "      existing instances pin the migration time and the public_tracks of that moment"),
}


def language():
    """Return the instance language, "en" or "ko".

    Uses tools/i18n.py when it is importable. Without it (memlib.py and now.py are copied alone
    into sync targets and hook fixtures), apply the same rule so state tokens written into the
    journal still match the language the instance asked for.
    """
    try:
        from i18n import language as catalog_language
    except ImportError:
        explicit = os.environ.get("MOTTORI_LANG")
        if explicit in ("en", "ko"):
            return explicit
        import json
        root = os.environ.get("MOTTORI_INSTANCE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            with open(os.path.join(root, "system", "memory-config.json"), encoding="utf-8") as f:
                configured = json.load(f).get("instance", {}).get("lang")
        except (OSError, ValueError, AttributeError):
            configured = None
        if configured in ("en", "ko"):
            return configured
        locales = (os.environ.get("LC_ALL", ""), os.environ.get("LANG", ""))
        return "ko" if any(value.lower().startswith("ko") for value in locales) else "en"
    return catalog_language()


def message(key, english, /, **kw):
    """Return catalog text for key in the instance language.

    english must equal the catalog's English value; it is the fallback when tools/i18n.py is
    missing or older than this module (a sync can update memlib.py without the catalog).
    """
    try:
        from i18n import STRINGS
        template = STRINGS[key][language()]
    except (ImportError, KeyError):
        template = english
    return template.format(**kw)


# State tokens: text that state files carry and code reads back. Writers emit the instance
# language; readers accept every form, so a journal or snapshot written under one language keeps
# working after the instance switches. The Korean forms are escaped because engine source is kept
# in English; tools/test_memlib_journal.py pins each escape to its readable Korean text.
STATE_TOKENS = {
    # PreCompact event body in the journal, and the reader that folds compactions in NOW.
    "compaction": {"en": "compaction occurred", "ko": "\ucef4\ud329\uc158 \ubc1c\uc0dd"},
    "compaction_tail": {"en": " \u2014 context after this point is a summary",
                        "ko": " \u2014 \uc774\ud6c4 \ucee8\ud14d\uc2a4\ud2b8\ub294 \uc694\uc57d\ubcf8"},
    # Marker people add to an event recorded after the fact; the journal header names it.
    "retroactive": {"en": "(retroactive)", "ko": "(\uc18c\uae09)"},
    # First line of the generated-file notice in NOW snapshots; the injection drops the notice.
    "generated_notice": {"en": "*Generated ", "ko": "*\uc0dd\uc131 "},
    # NOW section headings, located by the injection builder.
    "section_tracks": {"en": "Track status", "ko": "\ud2b8\ub799 \uc628\ub3c4\ud310"},
    "section_threads": {"en": "Live threads (dossiers)",
                        "ko": "\uc0b4\uc544 \uc788\ub294 \uc2a4\ub808\ub4dc (\uc11c\ub958\ucca0)"},
    "section_decisions": {"en": "Recent decisions and phases",
                          "ko": "\ucd5c\uadfc \uacb0\uc815\xb7\uad6d\uba74"},
    "section_events": {"en": "Recent events", "ko": "\ucd5c\uadfc \uc0ac\uac74"},
    "section_pointers": {"en": "Canonical pointers", "ko": "\uc815\ubcf8 \ud3ec\uc778\ud130"},
    "section_local_threads": {"en": "Local threads (dossiers)",
                              "ko": "\ub85c\uceec \uc2a4\ub808\ub4dc (\uc11c\ub958\ucca0)"},
    "section_local_decisions": {"en": "Recent local decisions and phases",
                                "ko": "\ucd5c\uadfc \ub85c\uceec \uacb0\uc815\xb7\uad6d\uba74"},
    "section_local_events": {"en": "Recent local events",
                             "ko": "\ucd5c\uadfc \ub85c\uceec \uc0ac\uac74"},
}


def token(name, lang=None):
    """Return the form of a state token that a writer emits now."""
    return STATE_TOKENS[name][lang or language()]


def token_forms(name):
    """Return every recognised form of a state token, the current language first."""
    current = token(name)
    return (current,) + tuple(v for v in STATE_TOKENS[name].values() if v != current)


ROOT = _resolve_root()
CONFIG_PATH = os.path.join(ROOT, "system", "memory-config.json")

CONFIG_WARNINGS = []
# CONFIG_WARNINGS entries are a protocol between this module and its readers, not display text:
# doctor._config_warning and now._warn_visibility_fail_closed match these prefixes and print
# their own localized message. They are deliberately the same in every language so the readers
# keep matching after an instance switches language.
CONFIG_WARNING_MISSING = "config \uc5c6\uc74c"
CONFIG_WARNING_INVALID = "config \ub85c\ub4dc/\uac80\uc99d \uc2e4\ud328"
CONFIG_WARNING_VISIBILITY = "journal_visibility \uc0ac\uc6a9 \ubd88\uac00"
CONFIG_WARNING_NO_TRACKS = "tracks \ubbf8\uc815\uc758 \u2014 NOW \uc628\ub3c4\ud310\uc774 \ube48\ub2e4"
CONFIG_WARNING_NOT_OBJECT = "object \uc544\ub2d8"
CONFIG_WARNING_REGISTRY_PARSE = "private thread registry \ud30c\uc2f1 \uc2e4\ud328"
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
        raise ValueError(message("memlib.cfg_root", "config root is not an object"))

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
            raise ValueError(message(
                "memlib.cfg_container",
                "config.{key} is not a {type}", key=key, type=typ.__name__))
    if "schema_version" in data and (isinstance(data["schema_version"], bool)
                                      or not isinstance(data["schema_version"], int)):
        raise ValueError(message("memlib.cfg_schema_int", "config.schema_version is not an int"))

    instance = data.get("instance", {})
    if "remote_allowlist" in instance and not isinstance(instance["remote_allowlist"], list):
        raise ValueError(message(
            "memlib.cfg_remote_list",
            "config.instance.remote_allowlist is not a list"))
    if "remote_allowlist" in instance and not all(
            _valid_remote_allowlist_entry(x) for x in instance["remote_allowlist"]):
        raise ValueError(message(
            "memlib.cfg_remote_invalid",
            "config.instance.remote_allowlist has an invalid host/remote"))

    egress = data.get("egress", {})
    if "model_send" in egress and not isinstance(egress["model_send"], dict):
        raise ValueError(message(
            "memlib.cfg_model_send",
            "config.egress.model_send is not an object"))
    model_send = egress.get("model_send", {})
    for key in ("deny_prefixes", "allow_prefixes"):
        if key in model_send and not (
                isinstance(model_send[key], list)
                and all(_valid_egress_prefix(x) for x in model_send[key])):
            raise ValueError(
                message("memlib.cfg_prefix_list", "config.egress.model_send.{key} is not a list of safe relative path prefixes", key=key))
    deny_prefixes = model_send.get("deny_prefixes", ["_private/"])
    allow_prefixes = model_send.get("allow_prefixes", [])
    relationship_errors = egress_prefix_relationship_errors(deny_prefixes, allow_prefixes)
    if relationship_errors:
        raise ValueError(message(
            "memlib.cfg_prefix_relationship",
            "config.egress.model_send.allow_prefixes relationship is unsafe: {errors}",
            errors="; ".join(relationship_errors)))

    for i, row in enumerate(data.get("episodic_sources", [])):
        if not isinstance(row, dict):
            raise ValueError(message(
                "memlib.cfg_source_object",
                "config.episodic_sources[{i}] is not an object", i=i))
        for key in ("name", "kind", "base", "glob"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(message(
                    "memlib.cfg_source_empty",
                    "config.episodic_sources[{i}].{key} is empty", i=i, key=key))

    for i, row in enumerate(data.get("tracks", [])):
        if not isinstance(row, dict):
            raise ValueError(message(
                "memlib.cfg_track_object",
                "config.tracks[{i}] is not an object", i=i))
        for key in ("key", "name", "canonical"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(message(
                    "memlib.cfg_track_empty",
                    "config.tracks[{i}].{key} is empty", i=i, key=key))
        canonical = row["canonical"]
        if (os.path.isabs(canonical)
                or re.match(r"^[A-Za-z]:[/\\]", canonical)
                or canonical.startswith("\\\\")
                or ".." in re.split(r"[/\\]+", canonical)):
            raise ValueError(
                message("memlib.cfg_track_canonical", "config.tracks[{i}].canonical is not a safe relative path", i=i))
        if "also" in row and not (isinstance(row["also"], list)
                                   and all(isinstance(x, str) for x in row["also"])):
            raise ValueError(message(
                "memlib.cfg_track_also",
                "config.tracks[{i}].also is not a list of strings", i=i))

    for i, row in enumerate(data.get("threads", [])):
        if not isinstance(row, dict):
            raise ValueError(message(
                "memlib.cfg_thread_object",
                "config.threads[{i}] is not an object", i=i))
        for key in ("key", "name"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(message(
                    "memlib.cfg_thread_empty",
                    "config.threads[{i}].{key} is empty", i=i, key=key))
        if row.get("dossier") is not None and not isinstance(row.get("dossier"), str):
            raise ValueError(message(
                "memlib.cfg_thread_dossier",
                "config.threads[{i}].dossier is not a string or null", i=i))
        visibility = row.get("visibility", "public")
        if visibility == "private":
            raise ValueError(
                message("memlib.cfg_thread_private", "config.threads[{i}] must not hold private metadata; move it to _private/state/threads.json", i=i))
        if visibility != "public":
            raise ValueError(message(
                "memlib.cfg_thread_visibility",
                "config.threads[{i}].visibility={visibility!r} is not supported", i=i, visibility=visibility))

    visibility = data.get("journal_visibility", {})
    if "public_tracks" in visibility and not (
            isinstance(visibility["public_tracks"], list)
            and all(isinstance(x, str) and x for x in visibility["public_tracks"])):
        raise ValueError(message(
            "memlib.cfg_public_tracks",
            "config.journal_visibility.public_tracks is not a list of non-empty strings"))
    legacy_tracks = visibility.get("legacy_public_tracks")
    if legacy_tracks is not None and not (
            isinstance(legacy_tracks, list)
            and all(isinstance(x, str) and x for x in legacy_tracks)):
        raise ValueError(message(
            "memlib.cfg_legacy_tracks",
            "config.journal_visibility.legacy_public_tracks is not a list of strings"))
    legacy_cutoff = visibility.get("legacy_cutoff")
    if legacy_cutoff is not None:
        if not isinstance(legacy_cutoff, str):
            raise ValueError(message(
                "memlib.cfg_cutoff_type",
                "config.journal_visibility.legacy_cutoff is not ISO8601 or null"))
        try:
            parsed_cutoff = datetime.datetime.fromisoformat(legacy_cutoff)
        except ValueError as e:
            raise ValueError(message("memlib.cfg_cutoff_iso", "config.journal_visibility.legacy_cutoff is not ISO8601")) from e
        if parsed_cutoff.utcoffset() is None:
            raise ValueError(message(
                "memlib.cfg_cutoff_tz",
                "config.journal_visibility.legacy_cutoff has no timezone"))
    if data.get("schema_version", 1) >= 4 and not all(
            key in visibility for key in ("legacy_cutoff", "legacy_public_tracks")):
        raise ValueError(message(
            "memlib.cfg_legacy_missing",
            "schema v4 journal_visibility legacy fields missing"))
    if legacy_cutoff is None and legacy_tracks:
        raise ValueError(message(
            "memlib.cfg_legacy_null",
            "legacy_cutoff is null but legacy_public_tracks is not empty"))
    if "journal_types" in data and not (
            data["journal_types"] and all(isinstance(x, str) and x for x in data["journal_types"])):
        raise ValueError(message(
            "memlib.cfg_journal_types",
            "config.journal_types is not a list of non-empty strings"))
    if "personal_pointer" in data and data["personal_pointer"] is not None \
            and not isinstance(data["personal_pointer"], str):
        raise ValueError(message(
            "memlib.cfg_personal_pointer",
            "config.personal_pointer is not a string or null"))
    thresholds = data.get("thresholds", {})
    for key, value in thresholds.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(message(
                "memlib.cfg_threshold_int",
                "config.thresholds.{key} is not a non-negative int", key=key))
    for key in ("now_tail_events", "now_recent_decisions"):
        if key in thresholds and thresholds[key] < 1:
            raise ValueError(message(
                "memlib.cfg_threshold_positive",
                "config.thresholds.{key} is not a positive int", key=key))
    for key in ("now_max_bytes", "now_hook_max_bytes"):
        if key in thresholds and not 1024 <= thresholds[key] <= 6000:
            raise ValueError(message(
                "memlib.cfg_threshold_range",
                "config.thresholds.{key} is outside 1024..6000", key=key))
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
        CONFIG_WARNINGS.append(f"{CONFIG_WARNING_MISSING}: {CONFIG_PATH}")
        return {}
    except Exception as e:
        _CONFIG_LOAD_OK[0] = False
        _CONFIG_ERROR[0] = "invalid"
        _CONFIG_ERROR_DETAIL[0] = str(e)
        if _CONFIG_FINGERPRINT[0] is None:
            _CONFIG_FINGERPRINT[0] = config_fingerprint(CONFIG_PATH)
        CONFIG_WARNINGS.append(f"{CONFIG_WARNING_INVALID}: {type(e).__name__}")
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

    Replace every character except ASCII letters, digits, and hyphens with a hyphen. Non-ASCII names can collide under this encoding. The derived path is returned even when it does not exist yet."""
    # No fallback to a similarly named folder: a suffix match such as "...-clientwork-kit" or
    # "...-toolkit" is another project's transcript store, and reading it crosses the data
    # boundary. A renamed instance declares its previous roots in instance.root_aliases instead.
    root = root or ROOT
    base = os.path.expanduser("~/.claude/projects")
    return os.path.join(base, mangle_project_key(root))


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
    todo = [f"v{v}: {message(f'memlib.schema_change_{v}', SCHEMA_CHANGES[v])}"
            for v in sorted(SCHEMA_CHANGES) if CONFIG_SCHEMA < v <= SCHEMA_VERSION]
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
    r" \[(?P<track>[a-z\uac00-\ud7a3_-]+)/(?P<type>[a-z]+)\] (?P<body>.+)$"
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
        f"{CONFIG_WARNING_VISIBILITY} \u2014 \uc0c8 \uc0ac\uac74\uc740 \uc804\ubd80 "
        "_private/state\ub85c fail-close "
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
        return message(
            "memlib.line_format",
            "format mismatch: expected '- <ISO8601> [<track>/<type>] <text>'")
    if m.group("type") not in JOURNAL_TYPES:
        return message("memlib.line_type", "type '{type}' is not defined (allowed: {allowed})",
                       type=m.group("type"), allowed=", ".join(JOURNAL_TYPES))
    if len(m.group("body")) > 300:
        return message(
            "memlib.line_too_long",
            "text exceeds 300 characters; a journal row records one event, not a document")
    return None


def _parse_journal_timestamp(value):
    """Parse the journal grammar on Python versions that reject compact UTC offsets."""
    compact = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    return datetime.datetime.fromisoformat(compact)


def _journal_corrupt(detail):
    return message("memlib.journal_corrupt", "journal corrupt: {detail}", detail=detail)


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
                boundary_errors.append(message("memlib.journal_bom", "UTF-8 BOM is not allowed"))
            if raw_bytes and not raw_bytes.endswith(b"\n"):
                boundary_errors.append(message(
                    "memlib.journal_no_newline",
                    "last line has no newline"))
            for boundary_error in boundary_errors:
                problem = f"{path}:1: {boundary_error}"
                if strict:
                    raise ValueError(_journal_corrupt(problem))
                errors.append(problem)
            text = raw_bytes.decode("utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                raw = line.strip()
                m = JOURNAL_LINE.match(raw)
                if not m:
                    if strict and raw.startswith("- "):
                        raise ValueError(_journal_corrupt(f"{path}:{lineno}: {raw[:100]}"))
                    if raw.startswith("- "):
                        errors.append(f"{path}:{lineno}: {raw[:100]}")
                    continue
                schema_error = validate_line(raw)
                if schema_error:
                    problem = f"{path}:{lineno}: {schema_error}"
                    if strict:
                        raise ValueError(_journal_corrupt(problem))
                    errors.append(problem)
                    continue
                row = m.groupdict()
                try:
                    row_dt = _parse_journal_timestamp(row["ts"])
                except ValueError as e:
                    if strict:
                        raise ValueError(_journal_corrupt(
                            f"{path}:{lineno}: timestamp {row['ts']}")) from e
                    errors.append(f"{path}:{lineno}: timestamp {row['ts']}")
                    continue
                if row_dt.utcoffset() is None:
                    problem = message("memlib.journal_no_tz",
                                      "{path}:{lineno}: timestamp has no timezone",
                                      path=path, lineno=lineno)
                    if strict:
                        raise ValueError(_journal_corrupt(problem))
                    errors.append(problem)
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
    marker = "\n\n" + message("memlib.clip_marker", "[… middle cut: original {bytes} bytes …]",
                              bytes=len(raw)) + "\n\n"
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
    CONFIG_WARNINGS.append(CONFIG_WARNING_NO_TRACKS)
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

# Labels that introduce the "last updated" line of a canonical track document. People write
# these documents in either language, so both sets are recognised; group 2 is the rest of the line.
UPDATED_LABELS = {
    "en": ("Last updated", "Last update", "Last maintained"),
    "ko": ("\ub9c8\uc9c0\ub9c9 \uac31\uc2e0", "\ub9c8\uc9c0\ub9c9 \uc5c5\ub370\uc774\ud2b8",
           "\ub9c8\uc9c0\ub9c9 \uc815\ube44"),
}
UPDATED_RE = re.compile("(" + "|".join(re.escape(label) for label in
                                      UPDATED_LABELS["ko"] + UPDATED_LABELS["en"])
                        + r")[:\uff1a]?\s*(.+)")

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
            raise ValueError(message("memlib.registry_not_list", "not a list"))
        valid = []
        private_keys = set()
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                _PRIVATE_THREADS_LOAD_OK[0] = False
                CONFIG_WARNINGS.append(
                    f"private thread registry[{i}] {CONFIG_WARNING_NOT_OBJECT} \u2014 skip")
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
        CONFIG_WARNINGS.append(f"{CONFIG_WARNING_REGISTRY_PARSE}: {e}")
        return []


_PRIVATE_THREADS = _private_threads()
PRIVATE_THREADS_FINGERPRINT = _PRIVATE_THREADS_FINGERPRINT[0]
PRIVATE_THREADS_LOAD_OK = _PRIVATE_THREADS_LOAD_OK[0]
_THREAD_ROWS = _PUBLIC_THREADS + [dict(x, visibility="private") for x in _PRIVATE_THREADS]
THREADS = [(x["key"], x["name"], x.get("dossier")) for x in _THREAD_ROWS]
THREAD_VISIBILITY = {x["key"]: x.get("visibility", "public") for x in _THREAD_ROWS}

# ---------------------------------------------------------------------- NOW

# Shared fixed section order for the renderer and visualization.
NOW_SECTION_TOKENS = ("section_tracks", "section_threads", "section_decisions",
                      "section_events", "section_pointers")
NOW_SECTIONS = [token(name) for name in NOW_SECTION_TOKENS]
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
