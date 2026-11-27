#!/usr/bin/env python3
"""Reads the improvement loop's settings, the `loop` block of the instance configuration, with an
engine default for every key.

KEYS is the one place that names the keys; a key that starts with _ is a note. A key that is missing
takes its engine default. A value of the wrong form also reads as the default, and problems() names it
together with every unknown key and every key written twice: while there is one, the loop stops
(tools/loop/lib/loop_settings.py). A path entry is one literal path: no *, no empty, . or .. part and
no leading /. A runtime is one the worker tool knows. The block only adds to the never list: nothing
in it takes a path off the part the engine fixes (tools/loop/loop_policy.py). A root argument names
the instance root; without it, the tree this file lives in.

  python3 tools/loop/lib/loop_config.py      prints every key with the value in use"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import paths as P  # noqa: E402
import loop_sources  # noqa: E402

BLOCK = "loop"
# The stages that take a runtime order, and the order a stage takes when the block names none for it.
STAGES = ("judge", "implement", "triage", "card", "propose", "digest", "review") + tuple(
    stage for _, stages in loop_sources.each("STAGES") for stage in stages)
DEFAULT_ORDER = ("claude", "codex")
# What a reader returns for a configured JSON null that the key accepts; value() gives None for it.
NULL = object()
# The scheduled jobs: each source (tools/loop/lib/loop_sources.py) and the daily health check.
SOURCES = loop_sources.names()
HEALTH = "health"
JOBS = SOURCES + (HEALTH,)
DEFAULT_SCHEDULE = {**{name: dict(m.SCHEDULE) for name, m in loop_sources.added().items()},
                    "papers": {"weekday": 3, "hour": 3, "minute": 0},
                    "health": {"hour": 6, "minute": 0}}


def entry_problem(entry):
    """Why entry is not one literal path relative to the instance ("dir/" for a folder), or None."""
    if not isinstance(entry, str) or not entry or entry != entry.strip():
        return "not a path"
    if entry.startswith("/"):
        return "it starts with /"
    if "*" in entry:
        return "it holds *, and an entry names one path, not a pattern"
    if "\\" in entry or ":" in entry:
        return "it holds \\ or :"
    parts = (entry[:-1] if entry.endswith("/") else entry).split("/")
    if "" in parts:
        return "it has an empty part (//)"
    if "." in parts or ".." in parts:
        return "it has a . or .. part"
    return None


def _paths(raw):
    """A list of literal relative paths inside the instance ("dir/" for a folder), or None."""
    if not isinstance(raw, list) or any(entry_problem(x) for x in raw):
        return None
    return tuple(dict.fromkeys(raw))


def _orders(raw):
    """{"default" or a stage: [runtime, ...]} over the engine default, or None. Each runtime is one the
    worker tool knows (tools/lib/config.py WORKER_RUNTIMES)."""
    from config import WORKER_RUNTIMES  # Imported here: a tree with only the loop's files reads its other keys.
    if not isinstance(raw, dict) or not all(
            k in STAGES + ("default",) and isinstance(v, list) and v and all(r in WORKER_RUNTIMES for r in v)
            and len(set(v)) == len(v) for k, v in raw.items()):
        return None
    return {"default": DEFAULT_ORDER, **{k: tuple(v) for k, v in raw.items()}}


def _path(raw):
    """One relative path inside the instance, or None."""
    got = _paths([raw]) if isinstance(raw, str) else None
    return got[0] if got else None


def _optional_path(raw):
    """A relative path, or NULL for the JSON null that turns its use off."""
    return NULL if raw is None else _path(raw)


def _texts(raw):
    if raw is None:
        return NULL
    return tuple(raw) if isinstance(raw, list) and raw and all(isinstance(x, str) and x.strip() for x in raw) else None


def _prefix(raw):
    if raw is None:
        return NULL
    return raw if isinstance(raw, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]", raw) else None


def _time(raw, daily):
    """{"hour", "minute"} and, unless daily, "weekday" (0 Sunday to 6 Saturday), or None."""
    keys = {"hour": range(24), "minute": range(60)} | ({} if daily else {"weekday": range(7)})
    if not isinstance(raw, dict) or set(raw) != set(keys) or not all(
            isinstance(raw[k], int) and not isinstance(raw[k], bool) and raw[k] in r for k, r in keys.items()):
        return None
    return dict(raw)


def _schedule(raw):
    """{job: time} over the engine default; the sources run weekly, the health check daily."""
    if not isinstance(raw, dict) or not set(raw) <= set(JOBS):
        return None
    out = dict(DEFAULT_SCHEDULE)
    for job, when in raw.items():
        out[job] = _time(when, job == HEALTH)
        if out[job] is None:
            return None
    return out


def _commands(raw):
    """A list of commands, each a list of words run from the instance root."""
    if not isinstance(raw, list) or not all(isinstance(c, list) and c and all(isinstance(w, str) and w for w in c)
                                            for c in raw):
        return None
    return tuple(tuple(c) for c in raw)


def _flag(raw):
    return raw if isinstance(raw, bool) else None


def _count(raw):
    if raw is None:
        return NULL
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else None


def _line(raw):
    return raw if raw is None or (isinstance(raw, str) and raw and "\n" not in raw) else None


# key: (engine default, reader of a configured value that returns None when its form is wrong, meaning)
# A reader returns NULL for a null the key accepts.
KEYS = {
    "never": ((), _paths,
              "paths this installation adds to the loop's never list; a folder ends with /"),
    "clone_excluded": ((), _paths,
                       "folders left out of the isolated clone; its tests and commit check run without them"),
    "runtime_orders": ({"default": DEFAULT_ORDER}, _orders,
                       "the runtimes each stage tries in order; default is every stage not named. The reviewer "
                       "tries the other families first and the builder's family last whatever the order"),
    "token_ceiling": (None, _count, "the tokens a cycle may spend, counted from the tokens the model programs report: "
                                    "once they reach it, no new model stage starts; runs already going may finish, and "
                                    "a run without a count does not move it. null sets no ceiling"),
    "papers_client": ("improvement-loop-papers", lambda r: r if _line(r) and r.strip() == r else None,
                      "the client name the papers source sends to arXiv"),
    "papers_contact": (None, _line, "a contact address sent with the client name; none when null"),
    "papers_queries": (None, _texts, "the arXiv queries of the papers source; null keeps the engine's list "
                                   "(tools/loop/papers/sweep.py DEFAULT_QUERIES)"),
    "job_prefix": (None, _prefix, "the prefix of the scheduled jobs' labels; null builds it from the instance name"),
    "schedule": (DEFAULT_SCHEDULE, _schedule, "the day and time of each job, on the machine's clock: each source "
                                              "weekly (weekday 0 is Sunday), the health check daily"),
    "health_started_by": (None, _line, "what starts the daily health check when it is not the loop's own job; "
                                       "then the loop schedules no health job"),
    "health_extra_checks": ((), _commands, "commands the health check also runs; each prints a JSON list of "
                                           "[key, message] problems"),
}

# The readers an added source may name for its own keys (tools/loop/sources/README.md).
READERS = {"flag": _flag, "paths": _paths, "path": _path, "optional_path": _optional_path, "line": _line,
           "texts": _texts, "count": _count}
KEYS.update({key: (default, READERS[kind], meaning) for _, keys in loop_sources.each("KEYS")
             for key, (default, kind, meaning) in keys.items()})


def block(root=None):
    """The `loop` block as written, {} when the file or the block is missing, None when unreadable."""
    try:
        with open(P.config_file(root or ROOT), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    found = data.get(BLOCK, {}) if isinstance(data, dict) else None
    return found if isinstance(found, dict) else None


def value(key, root=None):
    """The value in use for key: the configured one when its form is right, else the engine default."""
    default, read, _ = KEYS[key]
    found = block(root) or {}
    if key not in found:
        return default
    got = read(found[key])
    return default if got is None else (None if got is NULL else got)


def job_label(job, root=None):
    """The scheduler's label of job: the configured prefix, else one built from the instance name
    and the folder it is in. Two installations can share a name, and a name with no Latin letter
    or digit leaves no slug, so the folder's path is what tells their jobs apart."""
    prefix = value("job_prefix", root)
    if not prefix:
        try:
            with open(P.config_file(root or ROOT), encoding="utf-8") as f:
                name = json.load(f)["instance"]["name"]
        except (OSError, ValueError, LookupError, TypeError):
            name = ""
        slug = re.sub(r"[^A-Za-z0-9]+", "-", name if isinstance(name, str) else "").strip("-").lower()
        folder = hashlib.sha1(os.path.realpath(root or ROOT).encode("utf-8")).hexdigest()[:8]
        prefix = f"local.{slug or 'instance'}-{folder}.loop"
    return f"{prefix}.{job}"


def papers_user_agent(root=None):
    """What the papers source sends to arXiv as its User-Agent: the client name and the contact, if any."""
    contact = value("papers_contact", root)
    return value("papers_client", root) + (f" (contact: {contact})" if contact else "")


def problems(root=None):
    """One line for each key of the block the loop does not know and each value it cannot use."""
    found = block(root)
    if found is None:
        return [f"{P.tracked_name(P.config_file)} has no readable `{BLOCK}` object"]
    out = [f"{name}: occurs twice" for name in twice(root)]
    for key, raw in found.items():
        if not isinstance(key, str) or key.startswith("_"):
            continue
        if key not in KEYS:
            out.append(f"{BLOCK}.{key}: unknown setting")
        elif KEYS[key][1](raw) is None:
            out.extend(_why_not(key, raw))
    return out


def _why_not(key, raw):
    """The lines that say why the configured value of key cannot be used: each entry that is not one
    literal path, each runtime the worker tool does not know, or the value as a whole."""
    shown = lambda x: json.dumps(x, ensure_ascii=False)[:60]  # noqa: E731
    if KEYS[key][1] is _paths and isinstance(raw, list):
        bad = [(x, entry_problem(x)) for x in raw if entry_problem(x)]
        if bad:
            return [f"{BLOCK}.{key}: cannot use {shown(x)}: {why}; an entry is one literal path relative to the "
                    "instance, a folder ends with one /" for x, why in bad]
    if key == "runtime_orders" and isinstance(raw, dict):
        from config import WORKER_RUNTIMES
        names = [r for v in raw.values() if isinstance(v, list) for r in v if isinstance(r, str)]
        unknown = list(dict.fromkeys(r for r in names if r not in WORKER_RUNTIMES))
        if unknown:
            return [f"{BLOCK}.{key}: unknown runtime {shown(r)} (the worker tool knows "
                    f"{', '.join(WORKER_RUNTIMES)})" for r in unknown]
    return [f"{BLOCK}.{key}: cannot use {shown(raw)}"]


class _Pairs(dict):
    """A JSON object as read, with the keys it holds more than once."""

    def __init__(self, pairs):
        super().__init__(pairs)
        names = [k for k, _ in pairs]
        self.twice = list(dict.fromkeys(k for k in names if names.count(k) > 1))


def twice(root=None):
    """The dotted name of every key that occurs more than once in the `loop` block, or of the block itself;
    JSON reading would silently keep the last."""
    try:
        with open(P.config_file(root or ROOT), encoding="utf-8") as f:
            data = json.load(f, object_pairs_hook=_Pairs)
    except (OSError, ValueError):
        return []
    if not isinstance(data, _Pairs):
        return []
    out = [BLOCK] if BLOCK in data.twice else []

    def walk(obj, name):
        if isinstance(obj, _Pairs):
            out.extend(f"{name}.{k}" for k in obj.twice)
            for k, v in obj.items():
                walk(v, f"{name}.{k}")
        elif isinstance(obj, list):
            for v in obj:
                walk(v, name)
    walk(data.get(BLOCK), BLOCK)
    return out


if __name__ == "__main__":
    for k, (_, _, meaning) in KEYS.items():
        print(f"{BLOCK}.{k} = {json.dumps(value(k), ensure_ascii=False)}\n    {meaning}")
    for line in problems():
        print(f"problem: {line}")
