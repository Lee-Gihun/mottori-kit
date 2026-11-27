#!/usr/bin/env python3
"""Read and validate the instance configuration, paths.config_file().

Importing this module reads no file. The first call that needs a value reads the configuration
and the private thread registry, once per process. A file that is missing or breaks a rule gives
safe defaults and a warning, so the diagnostics still run. config_migrate.py writes the file at
setup.

Command line (setup.sh uses it):
  python3 tools/lib/config.py get KEY.PATH                 Print one value of the current config, or nothing.
                                                       Exit 1 when the files are still at their old places."""
import datetime
import hashlib
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths  # noqa: E402
import safeio  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
CONFIG_NAME = paths.tracked_name(paths.config_file)
LEGACY_LAYOUT = ("{count} files of this installation are still at their old places, such as {old}; "
                 "bash setup.sh --force moves them into {folder}/")
CFG_LEGACY_TRACKS = "config.journal_visibility.legacy_public_tracks is not a list of strings"
CFG_THREAD_PRIVATE = (
    "config.threads[{i}] must not hold private metadata; move it to _private/state/threads.json"
)
CFG_WORKERS = (
    "config.workers.{key} is not valid: an entry is claude, codex or gemini, with model, "
    "effort (a lower-case word), where (instance or copy) and web_in_instance (true or false)"
)

# Bump the version when the engine needs new config fields, and teach setup to move the old form.
# v0.10, the first release, already wrote schema 4; earlier forms are not moved (KIT-DR-086).
SCHEMA_VERSION = 4

# The names a track and a journal type may have. A configured name outside them is a warning,
# not an error: it only means no journal row can be logged under it.
TRACK_NAME = r"[a-z0-9가-힣_-]+"
TYPE_NAME = r"[a-z]+"
WORKER_RUNTIMES = ("claude", "codex", "gemini")
# The program the worker tool starts for each runtime.
WORKER_PROGRAMS = {"claude": "claude", "codex": "codex", "gemini": "agy"}
DEFAULT_JOURNAL_TYPES = ("decision", "state", "artifact", "correction", "lesson", "switch", "idea")
DEFAULT_THRESHOLDS = {"now_tail_events": 12, "now_recent_decisions": 8, "journal_stale_days": 2,
                      "memory_rot_days": 14, "now_hook_max_bytes": 6000, "now_max_bytes": 6000}
DEFAULT_EGRESS_MODEL_SEND = {"deny_prefixes": ["_private/"], "allow_prefixes": []}
# Files beside the fact records that facts.py snapshot keeps (config ledger.snapshot_extras).
DEFAULT_LEDGER_EXTRAS = ("README.md",)


# ------------------------------------------------------------------ value checks

_TIMESTAMP = re.compile(
    r"(?P<clock>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)(?P<fraction>\.\d{1,9})?"
    r"(?P<zone>Z|[+-]\d{2}:?\d{2})")


def parse_timestamp(text):
    """Return an aware datetime for an ISO8601 time with a zone, or None for anything else.

    The configuration's cutoff, journal rows and runtime transcripts share this reading. Python
    3.9 fromisoformat rejects a trailing Z, an offset without a colon and fractions that are not
    3 or 6 digits."""
    m = _TIMESTAMP.fullmatch(text) if isinstance(text, str) else None
    if not m:
        return None
    fraction = "." + m["fraction"][1:7].ljust(6, "0") if m["fraction"] else ""
    zone = "+00:00" if m["zone"] == "Z" else m["zone"][:3] + ":" + m["zone"][-2:]
    try:
        return datetime.datetime.fromisoformat(m["clock"] + fraction + zone)
    except ValueError:
        return None


def is_day(text):
    """Return whether text is a real date written YYYY-MM-DD.

    fromisoformat alone accepts 20260101 on newer Pythons, and dates in records and ledgers are
    compared as text, so only this one form counts."""
    if not (isinstance(text, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def safe_relative_path(path):
    """Return whether path is relative and cannot climb out of the instance root."""
    return not (os.path.isabs(path)
                or re.match(r"^[A-Za-z]:[/\\]", path)
                or path.startswith("\\\\")
                or ".." in re.split(r"[/\\]+", path))


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


def _text(value):
    return isinstance(value, str) and bool(value)


def _texts(value):
    return isinstance(value, list) and all(_text(x) for x in value)


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _patterns(value):
    """A list of non-empty regular expressions that all compile."""
    if not _texts(value):
        return False
    try:
        for pattern in value:
            re.compile(pattern)
    except re.error:
        return False
    return True


_WORKER_VALUES = {
    "model": lambda v: isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", v),
    "effort": lambda v: isinstance(v, str) and re.fullmatch(r"[a-z]+", v),
    "where": lambda v: v in ("instance", "copy"),
    "web_in_instance": lambda v: isinstance(v, bool),
}


# ------------------------------------------------------------------ the rules

def _key(path, test, message):
    """A rule on one dotted key: when the key is present and test(value) is false, message."""
    def rule(data, warn):
        value = data
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return None if test(value) else message
    return rule


def _each_row(key, fields, check=None):
    """A rule on each row of a list: an object whose fields are non-empty text, then check."""
    def rule(data, warn):
        for i, row in enumerate(data.get(key, [])):
            if not isinstance(row, dict):
                return f"config.{key}[{i}] is not an object"
            for field in fields:
                if not _text(row.get(field)):
                    return f"config.{key}[{i}].{field} is empty"
            problem = check(i, row, warn) if check else None
            if problem:
                return problem
        return None
    return rule


def _track_row(i, row, warn):
    if not re.fullmatch(TRACK_NAME, row["key"]):
        warn("config.cfg_track_name", field=f"tracks[{i}].key")
    if not safe_relative_path(row["canonical"]):
        return f"config.tracks[{i}].canonical is not a safe relative path"
    if "also" in row and not (isinstance(row["also"], list)
                               and all(isinstance(x, str) for x in row["also"])):
        return f"config.tracks[{i}].also is not a list of strings"
    return None


def _thread_row(i, row, warn):
    dossier = row.get("dossier")
    if dossier is not None and not isinstance(dossier, str):
        return f"config.threads[{i}].dossier is not a string or null"
    # The re-entry hook reads the dossier into the model's context, so it must stay inside.
    if dossier is not None and not safe_relative_path(dossier):
        return f"config.threads[{i}].dossier is not a safe relative path"
    visibility = row.get("visibility", "public")
    if visibility == "private":
        return CFG_THREAD_PRIVATE.format(i=i)
    if visibility != "public":
        return f"config.threads[{i}].visibility is not supported (only public)"
    return None


class ConfigProblem(ValueError):
    """A failed rule that also names its cause as a value, for a reader that advises per cause."""

    def __init__(self, text, cause):
        super().__init__(text)
        self.cause = cause


def _model_send(data, warn):
    """The deny and allow prefixes: safe, each allow below a deny. An empty deny list is allowed:
    a worker's copy still leaves out _private/ and the kit's state (KIT-DR-083).

    Causes: "deny_prefixes" or "allow_prefixes" for a list that is not safe prefixes, and
    "allow_unsafe" for an allow prefix that does not narrow a deny prefix."""
    model_send = data.get("egress", {}).get("model_send", {})
    for key in ("deny_prefixes", "allow_prefixes"):
        if key in model_send and not (isinstance(model_send[key], list)
                                      and all(_valid_egress_prefix(x) for x in model_send[key])):
            return ConfigProblem(
                f"config.egress.model_send.{key} is not a list of safe relative path prefixes", key)
    errors = egress_prefix_relationship_errors(
        model_send.get("deny_prefixes", DEFAULT_EGRESS_MODEL_SEND["deny_prefixes"]),
        model_send.get("allow_prefixes", []))
    if errors:
        return ConfigProblem("config.egress.model_send.allow_prefixes relationship is unsafe: "
                             + "; ".join(errors), "allow_unsafe")
    return None


def _workers(data, warn):
    # Checked before any run, so a typo names its key instead of falling back to a default.
    for runtime, entry in data.get("workers", {}).items():
        if runtime.startswith("_"):
            continue
        bad = [runtime] if runtime not in WORKER_RUNTIMES or not isinstance(entry, dict) else [
            f"{runtime}.{key}" for key, value in entry.items()
            if not key.startswith("_") and not (key in _WORKER_VALUES and _WORKER_VALUES[key](value))]
        if bad:
            return CFG_WORKERS.format(key=bad[0])
    return None


def _visibility(data, warn):
    """The public allowlist and its legacy cutover pair, which schema 4 requires."""
    visibility = data.get("journal_visibility", {})
    if not all(re.fullmatch(TRACK_NAME, x) for x in (visibility.get("public_tracks") or [])):
        warn("config.cfg_track_name", field="journal_visibility.public_tracks")
    # The two cutover keys take their defaults (none, []) when left out, as a missing key does elsewhere.
    legacy_tracks = visibility.get("legacy_public_tracks", [])
    if legacy_tracks is not None and not _texts(legacy_tracks):
        return CFG_LEGACY_TRACKS
    cutoff = visibility.get("legacy_cutoff")
    if cutoff is not None and not isinstance(cutoff, str):
        return "config.journal_visibility.legacy_cutoff is not ISO8601 or null"
    if cutoff is not None and parse_timestamp(cutoff) is None:
        return "config.journal_visibility.legacy_cutoff is not an ISO8601 time with a timezone"
    if data.get("schema_version", 1) >= 4:
        # Without these the public page freezes; name the key instead of loading silently.
        if "public_tracks" not in visibility:
            return "config.journal_visibility.public_tracks is missing (schema 4 requires it)"
        if legacy_tracks is None:
            return CFG_LEGACY_TRACKS
    if cutoff is None and legacy_tracks:
        return "legacy_cutoff is null but legacy_public_tracks is not empty"
    return None


def _journal_types(data, warn):
    if "journal_types" in data and not (data["journal_types"] and _texts(data["journal_types"])):
        return "config.journal_types is not a list of non-empty strings"
    if not all(re.fullmatch(TYPE_NAME, x) for x in data.get("journal_types", [])):
        warn("config.cfg_type_name")
    return None


def _thresholds(data, warn):
    thresholds = data.get("thresholds", {})
    for key, value in thresholds.items():
        if not _int(value) or value < 0:
            return f"config.thresholds.{key} is not a non-negative int"
    for key in ("now_tail_events", "now_recent_decisions"):
        if key in thresholds and thresholds[key] < 1:
            return f"config.thresholds.{key} is not a positive int"
    for key in ("now_max_bytes", "now_hook_max_bytes"):
        if key in thresholds and not 1024 <= thresholds[key] <= 6000:
            return f"config.thresholds.{key} is outside 1024..6000"
    return None


_CONTAINERS = (("instance", dict), ("egress", dict), ("episodic_sources", list), ("tracks", list),
               ("journal_visibility", dict), ("threads", list), ("checks", dict),
               ("journal_types", list), ("thresholds", dict), ("workers", dict),
               ("ledger", dict))

# Every key the load checks, in the order its first failure is reported. Optional blocks that
# turn off only their own feature (deliver, triggers.sources, instance.recall_meaning) are
# checked by their readers (below, and triggers.py for triggers.sources), so a slip there never
# refuses the whole configuration.
RULES = [_key(key, lambda v, t=typ: isinstance(v, t), f"config.{key} is not a {typ.__name__}")
         for key, typ in _CONTAINERS] + [
    _key("schema_version", _int, "config.schema_version is not an int"),
    # A string would be iterated per character and yield the alias "/", which makes every folder
    # count as this instance for recall.
    _key("instance.root_aliases", _texts,
         "config.instance.root_aliases is not a list of non-empty strings"),
    _key("instance.agent_openers", _patterns,
         "config.instance.agent_openers is not a list of regular expressions"),
    _key("egress.model_send", lambda v: isinstance(v, dict),
         "config.egress.model_send is not an object"),
    _model_send,
    _workers,
    _each_row("episodic_sources", ("name", "kind", "base", "glob")),
    _each_row("tracks", ("key", "name", "canonical"), _track_row),
    _each_row("threads", ("key", "name"), _thread_row),
    # null: no list, every track is ordinary. A list: a track outside it goes under the private area.
    _key("journal_visibility.public_tracks", lambda v: v is None or _texts(v),
         "config.journal_visibility.public_tracks is neither null nor a list of non-empty strings"),
    _visibility,
    _journal_types,
    _key("personal_pointer", lambda v: v is None or isinstance(v, str),
         "config.personal_pointer is not a string or null"),
    _thresholds,
    _key("ledger.snapshot_extras", lambda v: _texts(v) and all(safe_relative_path(x) for x in v),
         "config.ledger.snapshot_extras is not a list of safe relative paths"),
    _key("triggers.experiments", lambda v: v is None or (_text(v) and safe_relative_path(v)),
         "config.triggers.experiments is not a safe relative path or null"),
    # "." or "./" would freeze the whole folder, and every edit would stop the turn.
    _key("checks.waiting", _texts,
         "config.checks.waiting is not a list of non-empty strings"),
    _key("frozen", lambda v: _texts(v) and all(safe_relative_path(x) and os.path.normpath(x) != "."
                                               for x in v),
         "config.frozen is not a list of relative paths inside this folder"),
]


def validate(data, warnings=None):
    """Return data when every rule passes; otherwise raise ValueError naming the first failure.

    Unknown keys are accepted, so an older engine reads a newer config. Name warnings are added
    to warnings as (id, values) pairs, once each."""
    found = [] if warnings is None else warnings

    def warn(warning_id, /, **values):
        if (warning_id, values) not in found:
            found.append((warning_id, values))

    if not isinstance(data, dict):
        raise ValueError("config root is not an object")
    for rule in RULES:
        problem = rule(data, warn)
        if problem:
            raise problem if isinstance(problem, ConfigProblem) else ValueError(problem)
    return data


# ------------------------------------------------------------------ the loaded snapshot

class _Snapshot:
    """One process's reading of the configuration and the private thread registry."""

    def __init__(self):
        # (warning id, values) pairs, not display text: doctor turns the id into text.
        self.warnings = []
        self.path = paths.config_file()
        self.cause = None
        self.data, self.fingerprint, self.error, self.detail = self._load()
        self.ok = self.error is None
        self.schema = self.data.get("schema_version", 1)
        self._visibility()
        self.tracks = [(x["key"], x["name"], x["canonical"]) for x in self.data.get("tracks", [])]
        if not self.tracks and self.ok:
            self.warnings.append(("doctor.config_warn_tracks", {}))
        self._threads()

    def _load(self):
        """Return (config, hash of the bytes read, error kind None/missing/invalid, detail)."""
        fingerprint = None
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
            fingerprint = hashlib.sha256(raw).hexdigest()
            return validate(json.loads(raw.decode("utf-8")), self.warnings), fingerprint, None, None
        except FileNotFoundError:
            line = legacy_layout()
            self.warnings.append(("config.legacy_layout", {"line": line}) if line else
                                 ("doctor.config_warn_missing", {"path": self.path}))
            return ({}, safeio.file_fingerprint(self.path, b"<missing-config>"), "missing",
                    line or f"config missing: {self.path}")
        except Exception as e:
            # Validation messages name the key and the allowed form, which is what the owner must fix.
            self.warnings.append(("doctor.config_warn_load", {"detail": str(e) or type(e).__name__}))
            self.cause = getattr(e, "cause", None)
            return ({}, fingerprint or safeio.file_fingerprint(self.path, b"<missing-config>"),
                    "invalid", str(e))

    def _visibility(self):
        vis = self.data.get("journal_visibility", {})
        public, legacy, cutoff = (vis.get("public_tracks"), vis.get("legacy_public_tracks", []),
                                  vis.get("legacy_cutoff"))
        # null with the key present means "no list"; a config without the key is not ready.
        no_list = public is None and "public_tracks" in vis
        self.visibility_ready = (self.ok and self.schema == SCHEMA_VERSION
                                 and (no_list or _texts(public)) and _texts(legacy)
                                 and (cutoff is None or isinstance(cutoff, str)))
        ready = self.visibility_ready
        # None: every track is ordinary. A tuple: only these are, and () when the config is not
        # usable, so a row goes under the private area until the config is repaired.
        self.public_tracks = (None if ready and no_list
                              else tuple(dict.fromkeys(public or ())) if ready else ())
        self.legacy_tracks = tuple(dict.fromkeys(legacy or ())) if ready else ()
        self.legacy_cutoff = parse_timestamp(cutoff) if ready and cutoff else None
        # A config that did not load reports schema 1 from the empty fallback; the load warning says why.
        if not ready and self.ok:
            self.warnings.append(("doctor.config_warn_visibility",
                                  {"config": self.schema, "engine": SCHEMA_VERSION}))

    def _threads(self):
        public = list(self.data.get("threads", []))
        private, self.threads_fingerprint, self.threads_ok = self._private_threads(
            {row["key"] for row in public})
        rows = public + [dict(x, visibility="private") for x in private]
        self.thread_rows = rows
        self.threads = [(x["key"], x["name"], x.get("dossier")) for x in rows]
        self.thread_visibility = {x["key"]: x.get("visibility", "public") for x in rows}

    def _private_threads(self, public_keys):
        """Return (valid rows, hash of the bytes read, whether every row was valid)."""
        path = paths.private_threads()
        fingerprint = None
        try:
            with open(path, "rb") as f:
                raw = f.read()
            fingerprint = hashlib.sha256(raw).hexdigest()
            rows = json.loads(raw.decode("utf-8"))
            if not isinstance(rows, list):
                raise ValueError("not a list")
            valid, keys = [], set()
            for i, row in enumerate(rows):
                problem = _private_thread_problem(row, public_keys, keys)
                if problem:
                    self.warnings.append(("doctor.config_warn_private", {"index": i, "problem": problem}))
                    continue
                keys.add(row["key"])
                valid.append(row)
            return valid, fingerprint, len(valid) == len(rows)
        except FileNotFoundError:
            return [], safeio.file_fingerprint(path), True
        except Exception as e:
            self.warnings.append(("doctor.config_warn_private_parse", {"error": str(e)}))
            return [], fingerprint or safeio.file_fingerprint(path), False


def _private_thread_problem(row, public_keys, private_keys):
    """The warning id of a private registry row that cannot be used, or None."""
    if not isinstance(row, dict):
        return "doctor.config_warn_problem_object"
    if not all(_text(row.get(k)) for k in ("key", "name")):
        return "doctor.config_warn_problem_key"
    if row.get("dossier") is not None and not (
            isinstance(row["dossier"], str) and safe_relative_path(row["dossier"])):
        return "doctor.config_warn_problem_dossier"
    if row["key"] in public_keys:
        return "doctor.config_warn_problem_collision"
    if row["key"] in private_keys:
        return "doctor.config_warn_problem_duplicate"
    return None


_SNAPSHOT = None


def _s():
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = _Snapshot()
    return _SNAPSHOT


def reload():
    """Forget the snapshot, so the next call reads the files again; for a process that switches
    instance, as the state tests do."""
    global _SNAPSHOT
    _SNAPSHOT = None


# ------------------------------------------------------------------ readers

def data():
    """The validated configuration, or {} when it is missing or invalid."""
    return _s().data


def path():
    """The configuration file this process read."""
    return _s().path


def fingerprint():
    """Hash of the configuration bytes this process read."""
    return _s().fingerprint


def error():
    """None, "missing" or "invalid"."""
    return _s().error


def error_detail():
    return _s().detail


def error_cause():
    """The cause value of the rule that refused the configuration, or None (see ConfigProblem)."""
    return _s().cause


def load_ok():
    return _s().ok


def warnings():
    """The (warning id, values) pairs of loading the configuration and the thread registry."""
    return _s().warnings


# The text a person reads for each warning id; a registry row's problem value is itself an id here.
WARNING_TEXT = {
    "doctor.config_warn_load": "config load/validation failed, so new events go to _private/state only: {detail}",
    "doctor.config_warn_missing": "config missing: {path}",
    "config.legacy_layout": "{line}",
    "doctor.config_warn_private": "private thread registry[{index}] {problem}; skipped",
    "doctor.config_warn_private_parse": "private thread registry parse failed: {error}",
    "doctor.config_warn_problem_collision": "collides with a public key",
    "doctor.config_warn_problem_dossier": "has an invalid dossier",
    "doctor.config_warn_problem_duplicate": "has a duplicate key",
    "doctor.config_warn_problem_key": "has invalid key/name",
    "doctor.config_warn_problem_object": "is not an object",
    "doctor.config_warn_tracks": (
        'no tracks yet, so the state view has no track lines. Add one under "tracks" in {config_path}, '
        'for example: {{"key": "onboarding", "name": "Onboarding", "canonical": "onboarding/tracker.md"}}'),
    "doctor.config_warn_visibility": ("journal_visibility unavailable; all new events fail closed to "
                                      "_private/state (config schema={config}, engine schema={engine})"),
    "config.cfg_track_name": ("config.{field} has a name that a journal track cannot use, so no row can be "
                              "logged under it: rename it in {config_path} with only a-z, 0-9, "
                              "Hangul, _ and -"),
    "config.cfg_type_name": ("config.journal_types has a name that a journal type cannot use, so no row can "
                             "be logged with it: rename it in {config_path} with only a-z"),
}


def warning_text(warning):
    """The sentence for one (warning id, values) pair of warnings()."""
    key, values = warning
    if "problem" in values:
        values = dict(values, problem=WARNING_TEXT[values["problem"]])
    return WARNING_TEXT[key].format(config_path=CONFIG_NAME, **values)


def legacy_layout(root=None):
    """The one line every command that needs the configuration says while this installation's
    files are still where they were before the instance folder existed, or None.

    An installation whose configuration is already in the instance folder is on the current
    layout. A file at one of the old places is then the owner's own file, and no command stops
    for it."""
    root = root or paths.instance_root()
    if os.path.isfile(paths.config_file(root)):
        return None
    moves = paths.legacy_moves(root)
    if not moves:
        return None
    return LEGACY_LAYOUT.format(count=len(moves), old=os.path.relpath(moves[0][0], root),
                                folder=paths.tracked_name(paths.instance))


def not_set_up(root=None):
    """True in a kit folder before setup: no config, no earlier layout and no state inputs. Such
    a folder has nothing to inject and no baseline to judge a turn against."""
    root = root or paths.instance_root()
    return not (os.path.isfile(paths.config_file(root)) or legacy_layout(root)
                or paths.state_evidence(root))


def schema():
    """The configuration's schema version; 1 for a config that predates the field."""
    return _s().schema


def schema_gap():
    """Return (current version, required version, migration steps), or None when current."""
    current = schema()
    if current >= SCHEMA_VERSION:
        return None
    todo = ["this config is from before v0.10, which setup no longer moves: move it aside "
            "(mv instance/config.json instance/config.json.old) and run bash setup.sh again"]
    return current, SCHEMA_VERSION, todo


def instance():
    return data().get("instance", {})


def _expand(value):
    """Resolve the {ROOT} and {TRANSCRIPTS} placeholders and ~ in a configured path."""
    return os.path.expanduser(value.replace("{ROOT}", paths.instance_root())
                                   .replace("{TRANSCRIPTS}", paths.transcripts()))


def root_aliases():
    """Previous roots of this instance only; unrelated roots would cross the data boundary."""
    return [_expand(x) for x in (instance().get("root_aliases") or [])]


def agent_openers():
    """The instance's openers of prompts an agent sent, as regular expressions; the search of the
    owner's words leaves out a message that starts with one."""
    return list(instance().get("agent_openers") or [])


def egress_model_send():
    """The model-send policy, with safe defaults for an old config."""
    model_send = data().get("egress", {}).get("model_send", {})
    return {key: list(model_send.get(key, default))
            for key, default in DEFAULT_EGRESS_MODEL_SEND.items()}


def episodic_sources():
    """Retrieval sources as (name, kind, base folder, glob); the defaults read this instance.

    Kinds are claude-jsonl, codex-jsonl, agy-jsonl or plain text."""
    configured = [(x["name"], x["kind"], _expand(x["base"]), x["glob"])
                  for x in data().get("episodic_sources", [])]
    return configured or [
        ("claude", "claude-jsonl", paths.transcripts(), "*.jsonl"),
        ("codex", "codex-jsonl", os.path.expanduser("~/.codex/sessions"), "**/*.jsonl"),
        ("codex", "codex-jsonl", os.path.expanduser("~/.codex/archived_sessions"), "**/*.jsonl"),
        ("agy", "agy-jsonl", os.path.expanduser("~/.gemini/antigravity-cli/brain"),
         "*/.system_generated/logs/transcript.jsonl"),
    ]


def journal_types():
    return tuple(data().get("journal_types", DEFAULT_JOURNAL_TYPES))


def visibility_ready():
    """Whether the public allowlist and its cutover are usable; without them rows go private."""
    return _s().visibility_ready


def public_journal_tracks():
    """The tracks whose rows go to the ordinary journal when the installation keeps a list, or
    None when it keeps none and every track does."""
    return _s().public_tracks


def track_is_public(track):
    """Whether a row of this track goes to the ordinary journal unless it is logged --private."""
    tracks = public_journal_tracks()
    return tracks is None or track in tracks


def legacy_public_tracks():
    return _s().legacy_tracks


def legacy_cutoff():
    return _s().legacy_cutoff


def tracks():
    """(key, name, canonical) of each track; tracks are instance data with no defaults."""
    return _s().tracks


def track_also(key):
    """A track's secondary canonical documents."""
    return {x["key"]: x.get("also", []) for x in data().get("tracks", [])}.get(key, [])


def personal_pointer():
    return data().get("personal_pointer")


def workers():
    """Per-runtime worker settings (model, effort, where, web_in_instance)."""
    return data().get("workers", {})


def check_config(key, default=None):
    """Return checks.<key> from the configuration, or default; each checker validates its rows."""
    value = data().get("checks", {}).get(key)
    return default if value is None else value


def threshold(key):
    return data().get("thresholds", {}).get(key, DEFAULT_THRESHOLDS.get(key))


def threads():
    """(key, name, dossier) of each public and private deep thread; a null dossier is unassigned."""
    return _s().threads


def thread_rows():
    """Every usable thread row as written, public ones first; private rows carry visibility."""
    return _s().thread_rows


def thread_visibility():
    return _s().thread_visibility


def private_threads_fingerprint():
    return _s().threads_fingerprint


def private_threads_ok():
    return _s().threads_ok


def ledger_snapshot_extras():
    return tuple(data().get("ledger", {}).get("snapshot_extras", DEFAULT_LEDGER_EXTRAS))


def triggers_experiments():
    """The experiments table triggers.py scans by default, as an absolute path, or None."""
    section = data().get("triggers")
    rel = section.get("experiments") if isinstance(section, dict) else None
    return os.path.join(paths.instance_root(), rel) if rel else None


def document(file=None, root=None):
    """The configuration file (or file) as JSON before any rule: (value, None), (None, None)
    when it is missing or unreadable, or (None, the JSON error). Readers of optional blocks use
    it, so a slip elsewhere in the file does not turn their feature off."""
    try:
        with open(file or paths.config_file(root), encoding="utf-8") as f:
            return json.load(f), None
    except OSError:
        return None, None
    except ValueError as e:
        return None, e


def frozen():
    """The paths rule 1 of AGENTS.md freezes, normalized (a folder may end with "/"); a broken
    config means none, and the turn-end check then blocks on the config itself (KIT-DR-087)."""
    s = _s()
    value = s.data.get("frozen", []) if s.ok else []
    return [os.path.normpath(p) for p in value] if _texts(value) else []


def waiting_prefixes():
    """The prefixes of the state-check issues that wait for work outside any turn (checks.waiting);
    a broken config means none (KIT-DR-089)."""
    s = _s()
    checks = s.data.get("checks", {}) if s.ok else {}
    value = checks.get("waiting", []) if isinstance(checks, dict) else []
    return tuple(value) if _texts(value) else ()


def deliver():
    """The optional deliver block; a broken config or block means none."""
    value, _ = document()
    block = value.get("deliver", {}) if isinstance(value, dict) else {}
    return block if isinstance(block, dict) else {}


MEANING_OFF_HINT = "by meaning: off (python3 tools/options.py on meaning)"


def meaning_off_hint():
    """The words a search adds while the list by meaning is off and the owner has not said no to it
    (KIT-DR-094); empty otherwise, so a no is not repeated at every search, and empty in a tree with
    no usable config, where there is nothing to turn on."""
    if not load_ok():
        return ""
    opts = data().get("options", {})
    said_no = "meaning" in (opts.get("declined", []) if isinstance(opts, dict) else [])
    return "" if recall_meaning() is not None or said_no else MEANING_OFF_HINT


def recall_meaning():
    """The search's meaning settings with their prefixes, or None when the list is off or the
    block is malformed (recall_meaning.py tells the two apart by instance()["recall_meaning"])."""
    cfg = instance().get("recall_meaning")
    if not (cfg and isinstance(cfg, dict)
            and all(_text(cfg.get(k)) for k in ("endpoint", "model"))
            and all(isinstance(cfg.get(k, ""), str) for k in ("query_prefix", "document_prefix"))):
        return None
    return {"endpoint": cfg["endpoint"], "model": cfg["model"],
            "query_prefix": cfg.get("query_prefix", ""),
            "document_prefix": cfg.get("document_prefix", "")}


def trigger_sources(file=None):
    """The triggers.sources block as written, {} when there is none; ValueError when the file or
    the blocks around it cannot hold one. triggers.py checks the block's patterns."""
    cfg, problem = document(file)
    if problem is not None:
        raise ValueError(f"config is not valid JSON: {problem}")
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError("config top level must be an object")
    section = cfg.get("triggers", {})
    if not isinstance(section, dict):
        raise ValueError("config triggers must be an object")
    return section.get("sources", {})


def work_line_off(root=None):
    """Whether "work_line": "off" turns the background-work line off."""
    value, _ = document(root=root)
    return isinstance(value, dict) and value.get("work_line") == "off"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if len(argv) == 2 and argv[0] == "get":
        line = legacy_layout()
        if line:
            print(line, file=sys.stderr)
            return 1
        value, _ = document()
        for part in argv[1].split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            print(value)
        return 0
    print(__doc__.split("Command line", 1)[1].split("\n", 1)[1].rstrip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
