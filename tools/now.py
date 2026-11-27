#!/usr/bin/env python3
"""Append journal events, render state, and detect state drift.

Usage: python3 tools/now.py COMMAND [options]

Commands:
  log [--private] "[track/type] text"  Append a validated event and regenerate NOW.
                                     `log --help` lists the types and tracks of this workspace.
  render                             Regenerate NOW only.
  threads                            Show configured dossier pointers.
  hook-context                       Emit SessionStart additionalContext JSON.
  context [--public-only]             Emit the same state as plain text.
  precompact [--runtime NAME]         Record a compaction event.
  check [--issues] [--portable] [--repair]
                                      Report state drift. Read-only unless --repair, which
                                      re-renders a stale live snapshot first (the turn-end gate).

NOW is generated. Edit the source journal or canonical document instead."""
import datetime
import functools
import hashlib
import json
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import hook_input
import journal as J
import paths as P
import runlog
import safeio

# Messages this module prints in more than one place, or too long to read inline.
CHECK_CANONICAL_STALE = (
    "[canonical behind] {rel} ({file_date}) < newest {track} decision, state or correction "
    "event ({journal_date}). If {rel} is where the track is summed up, update it and its "
    "\"Last updated\" line"
)
CHECK_JOURNAL_ROLLOVER = (
    "[journal month rollover] {name} does not exist yet (the previous one is {age}d old)"
)
CHECK_NOT_APPLICABLE = (
    "[NOW check not applicable] development tree before setup, with no config and no state "
    "inputs"
)
CHECK_NOW_ABSENT = "[NOW missing] {path}"
CHECK_NOW_INPUT_NEWER = (
    "[NOW inputs are newer] state/NOW.md was rendered at {rendered}; since then {what}. Run "
    "python3 tools/now.py render"
)
CHECK_NOW_INPUT_NEWER_STAGED = (
    "[NOW inputs are newer] staged journal and snapshot disagree. Run python3 tools/now.py "
    "render and stage state/NOW.md"
)
INJECTION_DEGRADED = (
    "[DEGRADED: visibility config unavailable · public snapshot frozen · new events go local]"
)
INJECTION_HEAD = (
    "[state injection · journal {age} · private overlay {status}]\nMerged public and private "
    "state (overrides conversation summaries)."
)
THREADS_PRIVATE_UNREADABLE = (
    "[private threads unavailable: _private/state/threads.json cannot be read, so the private "
    "dossiers are not listed here. They are not gone; repair or restore that file.]"
)
LOG_HELP = (
    'Usage: python3 tools/now.py log [--private] "[track/type] one line"\n'
    "  type    one of: {types}\n"
    "  track   {tracks}\n"
    "  --private keeps the line under _private/, on this machine only.\n"
    'Example: python3 tools/now.py log "[checkout/decision] Fix the cart race with a lock, not a queue."'
)
LOG_TRACKS_ANY = "any short name, such as the project's; registered here: {names}"
LOG_TRACKS_LISTED = (
    "any short name; lines of {names} are ordinary, and a line of another track is kept under "
    "_private/"
)
NOT_SET_UP = (
    "[state injection] This workspace is not set up yet, so it has no state. Run `bash setup.sh` in "
    "{root} and show the owner what it prints. SETUP.md has the details."
)
PUBLIC_LABEL = "\n# Public state\n\n"
PRIVATE_LABEL = "\n# Private overlay\n\n"
# Under its part's title a private section takes the public section's name.
INJECTED_HEADING = {"section_local_threads": "section_threads",
                    "section_local_decisions": "section_decisions",
                    "section_local_events": "section_events"}
PRIVATE_CORRUPT = (
    "[local private overlay unavailable/corrupt: only public state was injected. Do not assert "
    "that local state is absent; run python3 tools/doctor.py to find what is broken, then fix "
    "_private/state/threads.json or the local journal]"
)
PRIVATE_DEGRADED = (
    "> [DEGRADED: local thread registry is incomplete. Run python3 tools/doctor.py to find "
    "what is broken, then fix _private/state/threads.json.]"
)
PRIVATE_LEGACY_UNAVAILABLE = (
    "> [DEGRADED: local rows kept in the tracked journal are not shown until it is repaired: "
    "{error}]"
)
PRIVATE_NOTICE = (
    "{generated}{ts} · generated for `_private/state/` only.\nThis file alone does not replace "
    "public state. The view merged with `state/NOW.md` is the local canonical state.*"
)
PRIVATE_OMITTED = (
    "[local private overlay omitted: this wiring injects public state only. Local state is "
    "unavailable, not absent]"
)
PUBLIC_NOTICE = (
    "{generated}{ts} by `python3 tools/now.py render`. Do not edit by hand; local state is in "
    "the local private overlay.*"
)
PUBLIC_UNAVAILABLE = (
    "[DEGRADED: public state unavailable: {reason}. The last page is not shown because the "
    "current policy has not certified it]"
)
LOG_REFUSED = (
    "refused: {error}.\nA valid line: python3 tools/now.py log \"[<track>/<type>] <text>\", for "
    "example \"[system/decision] Weekly review moves to Monday\"."
)
RENDER_FAILED = "NOW render failed: {error_type}: {error}"
STALE_OTHER = (
    "the journal is unchanged, so another input changed: the date, the configuration, a track "
    "document, a project's README or the tools"
)
THREAD_ROW_UNSET = (
    "- {name}: dossier **not set** (add one where this thread is registered: "
    "{config}, or _private/state/threads.json for a private thread)"
)
VISIBILITY_FAIL_CLOSED = (
    "[state] Cannot tell which events may be shared ({detail}), so new events go to the "
    "private journal only"
)

# State tokens: text the journal and the pages carry and this module reads back.
STATE_TOKENS = {
    # PreCompact event body in the journal, and the reader that folds compactions in NOW.
    "compaction": "compaction occurred",
    "compaction_tail": " \u2014 context after this point is a summary",
    # First line of the generated-file notice in NOW snapshots; the injection drops the notice.
    "generated_notice": "*Generated ",
    # NOW section headings; _SECTIONS below gives their order.
    "section_tracks": "Track status",
    "section_threads": "Live threads (dossiers)",
    "section_projects": "Projects (where their files are)",
    "section_decisions": "Recent decisions and phases",
    "section_events": "Recent events",
    "section_pointers": "Canonical pointers",
    "section_local_threads": "Local threads (dossiers)",
    "section_local_decisions": "Recent local decisions and phases",
    "section_local_events": "Recent local events",
}
# Korean forms that journals and snapshots written while the kit also spoke Korean still carry.
# Readers accept them; nothing writes them.
LEGACY_TOKEN_FORMS = {
    "compaction": "\ucef4\ud329\uc158 \ubc1c\uc0dd",
    "compaction_tail": " \u2014 \uc774\ud6c4 \ucee8\ud14d\uc2a4\ud2b8\ub294 \uc694\uc57d\ubcf8",
    "generated_notice": "*\uc0dd\uc131 ",
}


def token(name):
    """Return the form of a state token that a writer emits."""
    return STATE_TOKENS[name]


def token_forms(name):
    """Return every recognised form of a state token, the written form first."""
    legacy = LEGACY_TOKEN_FORMS.get(name)
    return (STATE_TOKENS[name],) + ((legacy,) if legacy else ())


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

# The engine sources that shape a page. Their bytes as this process imported them go into each
# page's marker, so a page an older engine rendered reads as stale to a newer one.
ENGINE_SOURCE_FINGERPRINTS = tuple(safeio.file_fingerprint(path)
                                   for path in (__file__, C.__file__, J.__file__))


def _now_iso(now=None):
    now = now or datetime.datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    return now.isoformat(timespec="seconds")


def _age_days(path, now=None):
    if not os.path.exists(path):
        return None
    if now is None:
        now = datetime.datetime.now().astimezone()
        modified = datetime.datetime.fromtimestamp(os.path.getmtime(path)).astimezone()
    else:
        if now.tzinfo is None:
            now = now.astimezone()
        modified = datetime.datetime.fromtimestamp(os.path.getmtime(path), tz=now.tzinfo)
    return (now.date() - modified.date()).days


def _warn_visibility_fail_closed():
    """Emit one mutation warning that names the failing config key, never a private-derived value."""
    if C.visibility_ready():
        return
    safe = []
    keys = dict(C.warnings())
    if "doctor.config_warn_missing" in keys:
        safe.append("config missing")
    if "doctor.config_warn_load" in keys:
        safe.append("config load/validation failed: {detail}".format(detail=keys["doctor.config_warn_load"]["detail"]))
    if "doctor.config_warn_visibility" in keys:
        safe.append(f"journal_visibility unavailable (config schema={C.schema()}, engine schema={C.SCHEMA_VERSION})")
    detail = " · ".join(safe) or "visibility config unavailable"
    print(VISIBILITY_FAIL_CLOSED.format(detail=detail), file=sys.stderr)


def _assert_config_unchanged():
    """Refuse to route or render under a config other than the one this process loaded.

    Checked inside the state lock before each append and each render: another session may change
    the config while this one waits for the lock, and the stale policy could send a now-local row
    to the tracked journal.
    """
    if safeio.file_fingerprint(C.path(), b"<missing-config>") != C.fingerprint():
        raise RuntimeError("config changed while the command ran; retry in a new process")


def log(body, quiet=False, force_private=False):
    event_time = datetime.datetime.now().astimezone()
    line = f"- {_now_iso(event_time)} {body.strip()}"
    err = J.validate_line(line)
    if err:
        print(LOG_REFUSED.format(error=err.rstrip(".")), file=sys.stderr)
        return 1
    _warn_visibility_fail_closed()
    match = J.LINE.match(line)
    visibility = J.journal_visibility(match.group("track"), force_private=force_private)
    # Fix event time and journal path once so the row's month and its journal file agree.
    journal_path = P.journal_file(event_time, visibility)
    render_error = None
    try:
        # Hold one lock across append and snapshot publication to prevent stale writers from winning.
        with J.state_lock():
            _assert_config_unchanged()
            # Only the destination journal: a damaged tracked journal must not block moving a
            # sensitive event into the local journal, and the local page names the damage.
            J.parse_journal(strict=True, physical_visibilities=(visibility,))
            J.append(line, journal_path, event_time)
            try:
                _render_unlocked(visibility)
                # Without the hook, AGENTS rule 2 reads the local page; one whose inputs are gone must go.
                if visibility == "public" and not _private_inputs_present():
                    _render_unlocked("private")
            except Exception as error:
                # The event is valid and routed correctly; losing it costs more than a NOW
                # that stays stale until the next render.
                render_error = error
    except Exception as e:  # Propagate failure so hook callers can use their fallback.
        print(f"state record failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if render_error is not None:
        print(f"recorded, NOW not rendered: {type(render_error).__name__}: {render_error}", file=sys.stderr)
    if not quiet:
        track = match.group("track")
        why = ("--private" if force_private else f'track "{track}" is not in public_tracks')
        print(f"recorded under {P.tracked_name(P.private_area)}/ ({why}): {line}" if visibility == "private"
              else f"recorded: {line}")
    return 0


def _update_line(path):
    """Return the rest of a canonical's first update line, or None without the line or the file.

    The update line is the one freshness a track document has: the page shows it and check
    compares its date with the track's journal, so a file time never disagrees with it."""
    if not os.path.exists(path):
        return None
    # A stray byte in a hand-edited canonical must not block every state render.
    for raw in open(path, encoding="utf-8", errors="replace"):
        m = UPDATED_RE.search(raw)
        if m:
            return m.group(2)
    return None


def _track_snippet(path):
    """Return the part of a canonical's update line that the state page shows, or ""."""
    line = _update_line(path)
    if line is None:
        return ""
    return line.strip().rstrip("*·—: ").replace("**", "")[:110].rstrip("·— ")


def _update_day(path):
    """Return the first YYYY-MM-DD date of a canonical's update line, or None."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", _update_line(path) or "")
    return m.group(0) if m else None


def _track_path(rel):
    """Return a track canonical's path, or None when it is written or resolves inside the private folder."""
    # A canonical in the private folder (also through a symlink) is shown as a pointer only.
    # casefold: on a case-insensitive disk _PRIVATE/x.md is the same file as _private/x.md.
    path = os.path.join(P.instance_root(), rel)
    if os.path.normpath(rel).casefold().split(os.sep)[0] == P.tracked_name(P.private_area):
        return None
    # samefile, not a path prefix: the private folder may itself be a link out of the tree, and a
    # link target may spell the root in another letter case.
    priv = P.private_area()
    parent = os.path.realpath(path)
    while parent != os.path.dirname(parent):
        parent = os.path.dirname(parent)
        try:
            if os.path.samefile(parent, priv):
                return None
        except OSError:
            continue
    return path


def _tracks(scope):
    """Registered tracks of one side. A track is on the ordinary page unless the installation keeps a
    list of public tracks and it is not on it; then its board row and pointers go to the local page,
    as its journal rows do."""
    return [t for t in C.tracks() if C.track_is_public(t[0]) == (scope == "public")]


def _track_rows(scope):
    rows = []
    for key, name, rel in _tracks(scope):
        path = _track_path(rel)
        snippet =(_track_snippet(path) or "(no update line)" if path
                   else "(private file, not read)")
        rows.append(f"- **{name}**: {snippet}, source `{rel}`")
    if scope != "public":
        return rows
    # An unset personal pointer has no row: there is nothing to point at.
    if C.personal_pointer():
        rows.append(f"- **Personal**: canonical `{C.personal_pointer()}` (personal area: contents are not shown in NOW)")
    return rows


def _dossier_missing(dossier):
    return not (dossier and os.path.exists(os.path.join(P.instance_root(), dossier)))


def _thread_row(name, dossier):
    """One dossier row; the injection and the threads command share it so both mark a moved file."""
    if not dossier:
        return THREAD_ROW_UNSET.format(name=name, config=C.CONFIG_NAME)
    return (f"- {name}: dossier `{dossier}`"
            + ("  [file missing]" if _dossier_missing(dossier) else ""))


def _thread_rows(visibility):
    """Return one display row per registered dossier of the given visibility, in config order."""
    return [_thread_row(name, dossier) for key, name, dossier in C.threads()
            if C.thread_visibility().get(key, "public") == visibility]


def threads():
    """Print the configured deep-thread dossier registry.

    A private registry that cannot be read is said to be unavailable: its threads are not gone."""
    unreadable = not C.private_threads_ok()
    if unreadable:
        print(THREADS_PRIVATE_UNREADABLE)
    if not C.threads():
        if not unreadable:
            print(f"(no threads registered; add them to threads in {C.CONFIG_NAME})")
        return 1 if unreadable else 0
    for key, name, dossier in C.threads():
        print(f"{key:<12} {_thread_row(name, dossier)}")
    return 0


def _project_rows():
    """The project folders by status and the open ones' outside folders (KIT-DR-093)."""
    try:
        import project_folders as projects
        return projects.context_rows()
    except Exception as e:  # noqa: BLE001 - a broken project file must not take the state page down
        return [f"- (projects could not be read: {type(e).__name__}; python3 tools/doctor.py)"]


def _pointer_block(scope):
    """Build canonical-document pointer lines from instance config; none when nothing is set."""
    parts = []
    for key, name, canon in _tracks(scope):
        refs = "+".join(f"`{p}`" for p in [canon] + C.track_also(key))
        parts.append(f"{name} {refs}")
    if C.personal_pointer() and scope == "public":
        parts.append(f"personal `{C.personal_pointer()}`")
    # Wrap pointer rows in groups of three for readability.
    return [" · ".join(parts[i:i + 3]) for i in range(0, len(parts), 3)]


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
    marker = "\n\n" + f"[… middle cut: original {len(raw)} bytes …]" + "\n\n"
    marker_n = len(marker.encode("utf-8"))
    room = max(0, max_bytes - marker_n)
    head = _utf8_prefix(text, int(room * 0.42))
    tail = _utf8_suffix(text, room - len(head.encode("utf-8")))
    # Prefer line boundaries without increasing the retained byte count.
    if "\n" in head:
        head = head[:head.rfind("\n") + 1]
    # Drop the tail's first line only when it starts mid-line in the original text.
    tail_start = len(raw) - len(tail.encode("utf-8"))
    if "\n" in tail and raw[tail_start - 1:tail_start] != b"\n":
        tail = tail[tail.find("\n") + 1:]
    out = head.rstrip() + marker + tail.lstrip()
    return _utf8_prefix(out, max_bytes)


def _nbytes(text):
    return len(text.encode("utf-8"))


def _clip_line(text, max_bytes):
    """Cut text to max_bytes UTF-8 bytes, ellipsis included; None means no limit."""
    if max_bytes is None or _nbytes(text) <= max_bytes:
        return text
    return _utf8_prefix(text, max_bytes - _nbytes("…")) + "…"


def _omitted_threads_note(count):
    return f"[{count} dossier(s) omitted · `python3 tools/now.py threads`]"


def _event_line(e, body_limit):
    return (f"- {e['ts'][:16]} [{e['track']}/{e['type']}] "
            f"{_clip_line(e['body'], body_limit)}")


def _fit_snapshot(builder, thread_count=0):
    """Return the limits of the largest page that fits NOW_MAX_BYTES, dropping lines by priority.

    builder(decisions, recent, body_limit, threads) renders the page with at most that many
    decision rows, recent rows and dossier rows, event bodies clipped to body_limit bytes. Lines
    go in this order: older recent events, older decisions, long event bodies, dossier rows from
    the end of the list (their place taken by a note with the omitted count and the command that
    lists them all), and finally every recent event and all but one decision. Dossier rows
    outrank long bodies because a new session needs them to resume a thread. Status
    lines and section headings are never dropped. When even the smallest limits are over the
    budget they are returned anyway and the caller cuts the page, so session start still gets a
    state body.
    """
    limits = (C.threshold("now_recent_decisions"), C.threshold("now_tail_events"), None,
              thread_count)
    while _nbytes(builder(*limits)) > C.threshold("now_max_bytes"):
        smaller = _smaller_page(*limits)
        if smaller is None:
            return limits
        limits = smaller
    return limits


def _smaller_page(decisions, recent, body_limit, threads):
    """The next smaller page limits in _fit_snapshot's order, or None at the smallest."""
    if recent > 3:
        return decisions, recent - 1, body_limit, threads
    if decisions > 2:
        return decisions - 1, recent, body_limit, threads
    if body_limit is None:
        return decisions, recent, 256, threads
    if body_limit > 32:
        return decisions, recent, body_limit // 2, threads
    if threads > 0:
        return decisions, recent, body_limit, threads - 1
    if recent > 0:
        return decisions, recent - 1, body_limit, threads
    if decisions > 1:
        return decisions - 1, recent, body_limit, threads
    return None


@functools.lru_cache(maxsize=None)
def _compaction_tag_re():
    """Match the runtime tag after a compaction marker written in any language."""
    markers = "|".join(re.escape(marker) for marker in token_forms("compaction"))
    return re.compile(r"(?:" + markers
                       + r") \((?P<runtime>[a-z]+) · s:(?P<sid>[0-9a-f]{8}|unknown)\)")


def is_compaction(entry):
    """Whether a row is one precompact wrote: a system state row in the runtime's marker format.

    A human row that starts with the same words ("compaction occurred in the soil sample") is an
    ordinary event. Rows written before the runtime tag existed are the marker and tail alone.
    """
    if entry.get("track") != "system" or entry.get("type") != "state":
        return False
    body = entry.get("body", "")
    return bool(_compaction_tag_re().match(body)) or body in {
        marker + tail for marker in token_forms("compaction")
        for tail in token_forms("compaction_tail")}


def _human_event_age(entries, now=None):
    """Days since the newest non-compaction event, or None when there is none.

    Every compaction appends to the journal, so the file mtime stays fresh even when nobody has
    recorded a decision for weeks. Freshness must follow what people recorded.
    """
    now = now or datetime.datetime.now().astimezone()
    # A future-dated row (clock skew, a typo) would give a negative age and hide staleness.
    stamps = [C.parse_timestamp(e["ts"]) for e in entries if not is_compaction(e)]
    stamps = [ts for ts in stamps if ts <= now]
    if not stamps:
        return None
    return (now.date() - max(stamps).astimezone(now.tzinfo).date()).days


def _compaction_summary(entries):
    """Return one projection row for the compactions since the newest recorded event, or None.

    Compactions say that the conversation was summarized, not what was decided. Listing them one by
    one crowded decisions out of the fixed byte budget, so the projection keeps only the count,
    the runtimes, and the newest time. Compactions before the newest recorded event tell a new
    session nothing it can act on, so they are not counted. The source journal keeps every event.
    """
    last_human = max((i for i, e in enumerate(entries) if not is_compaction(e)), default=-1)
    runs = [e for e in entries[last_human + 1:] if is_compaction(e)]
    if not runs:
        return None
    tag_re = _compaction_tag_re()
    counts = {}
    for e in runs:
        m = tag_re.search(e.get("body", ""))
        rt = m.group("runtime") if m else "unknown"
        counts[rt] = counts.get(rt, 0) + 1
    parts = " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    folded = dict(runs[-1])
    # The row a compaction writes ends "context after this point is a summary", which is true only of
    # the session that compacted; the folded row is read by every new session, so it leaves that out.
    folded["body"] = "{marker} {count} time(s) ({parts}) · last {last}{tail}".format(marker=token("compaction"), count=len(runs), parts=parts, last=runs[-1]["ts"][:16], tail="")
    return folded


# Row types that change a topic's state. A correction replaces an earlier decision, so it must
# compete for the same places; otherwise the corrected decision outlives its correction.
STATE_CHANGE_TYPES = ("decision", "state", "correction")

# Without a window every topic ever used would hold a decision place for ever, and old decisions
# would crowd out current work. Counted back from the newest row, so a pause does not empty it.
TOPIC_RESERVE_DAYS = 14


def _newest_per_recent_topic(rows):
    """Positions of the newest row of each journal topic, oldest first.

    Only topics with a row dated within TOPIC_RESERVE_DAYS of the newest row count. Rows are in
    journal time order. Registered tracks get no special treatment.
    """
    if not rows:
        return []
    stamps = [C.parse_timestamp(e["ts"]) for e in rows]
    cutoff = max(stamps) - datetime.timedelta(days=TOPIC_RESERVE_DAYS)
    return sorted({e["track"]: i for i, e in enumerate(rows) if stamps[i] >= cutoff}.values())


def _event_sections(entries, decision_limit, recent_limit):
    """Choose rows for the decision section and the recent section.

    Decisions are STATE_CHANGE_TYPES rows except compactions. Each journal topic with a decision
    dated within TOPIC_RESERVE_DAYS of the newest one keeps its newest decision before the other
    places go to the newest rows, so a busy topic cannot evict every decision of another one in a
    long session; when there are fewer places than topics, the newest of those rows win.
    Recent events skip rows already shown as decisions and carry at most one compaction row,
    placed where the newest compaction happened.
    """
    decisions = [e for e in entries
                 if e["type"] in STATE_CHANGE_TYPES and not is_compaction(e)]
    reserved = _newest_per_recent_topic(decisions)[-decision_limit:] if decision_limit else []
    rest = [i for i in range(len(decisions)) if i not in reserved]
    rest = rest[max(0, len(rest) - max(0, decision_limit - len(reserved))):]
    decisions = [decisions[i] for i in sorted(reserved + rest)]
    shown = {id(e) for e in decisions}
    summary = _compaction_summary(entries)
    last_compaction = next((e for e in reversed(entries) if is_compaction(e)), None)
    timeline = []
    for e in entries:
        if e is last_compaction:
            if summary is not None:
                timeline.append(summary)
        elif not is_compaction(e) and id(e) not in shown:
            timeline.append(e)
    recent = timeline[-recent_limit:] if recent_limit else []
    return decisions, recent


# Sections of each side in page order: (heading token, kind). A fixed section's rows are stored
# in the view under its token.
_SECTIONS = {
    "public": (("section_tracks", "fixed"), ("section_projects", "fixed"), ("section_threads", "threads"),
               ("section_decisions", "decisions"), ("section_events", "events"),
               ("section_pointers", "fixed")),
    "private": (("section_tracks", "fixed"), ("section_local_threads", "threads"),
                ("section_local_decisions", "decisions"), ("section_local_events", "events"),
                ("section_pointers", "fixed")),
}


def _view(scope, entries):
    """Select one side of the state view as data, sized so its disk page fits NOW_MAX_BYTES.

    The disk page and the injected body are both rendered from this view, so no step parses
    generated text back into rows.
    """
    generated = token("generated_notice")
    if scope == "public":
        # No file-time fallback: compactions keep the journal mtime fresh while nobody records.
        age = _human_event_age(entries)
        freshness = ("journal {age}d ago".format(age=age if age is not None else "?")
                     + (" \u26a0" if (age is None or age > C.threshold("journal_stale_days")) else ""))
        view = {"title": "# NOW", "status": f"*Input freshness: {freshness}*", "age": freshness[len("journal "):],
                "notice": PUBLIC_NOTICE.format(generated=generated, ts=_now_iso()),
                "section_tracks": _track_rows("public"), "section_projects": _project_rows(),
                "section_pointers": _pointer_block("public")}
    else:
        legacy = _legacy_problem()
        status = ([] if C.private_threads_ok() else [PRIVATE_DEGRADED]) + (
            [PRIVATE_LEGACY_UNAVAILABLE.format(error=legacy)] if legacy else [])
        view = {"title": "# NOW \u2014 local private overlay",
                "status": "".join(f"\n{line}\n" for line in status),
                "notice": PRIVATE_NOTICE.format(generated=generated, ts=_now_iso())}
        if _tracks("private"):
            view.update(section_tracks=_track_rows("private"),
                        section_pointers=_pointer_block("private"))
    view.update(scope=scope, entries=entries, threads=_thread_rows(scope))
    view["limits"] = _fit_snapshot(lambda *limits: _page(view, limits), len(view["threads"]))
    return view


# What an empty section shows, by heading token; other sections show "- (none)".
_EMPTY = {"section_threads": "- (no shared threads)", "section_pointers": "- (no tracks defined)",
          "section_tracks": "- (no tracks defined)", "section_projects": "- (no projects yet: projects/README.md)"}


def _sections(view, limits):
    """Yield (heading token, kind, rows, omitted dossier count, reserved) for the rows kept.

    reserved holds the positions of decision rows kept as their topic's newest.
    """
    decision_limit, recent_limit, body_limit, thread_limit = limits
    events = dict(zip(("decisions", "events"),
                      _event_sections(view["entries"], decision_limit, recent_limit)))
    # Lines past the row limits: neither section shows them, so the events section says how many.
    shown = {id(e) for e in events["decisions"] + events["events"]}
    beyond = sum(1 for e in view["entries"] if not is_compaction(e) and id(e) not in shown)
    for name, kind in _SECTIONS[view["scope"]]:
        if kind == "threads":
            yield (name, kind, view["threads"][:thread_limit],
                   len(view["threads"]) - thread_limit, ())
        elif kind == "fixed":
            # The local page has board and pointer sections only when a track is local.
            if name in view:
                yield name, kind, view[name], 0, ()
        else:
            rows = events[kind]
            yield (name, kind, [_event_line(e, body_limit) for e in rows],
                   beyond if kind == "events" else 0,
                   _newest_per_recent_topic(rows) if kind == "decisions" else ())


def _page(view, limits):
    """Render the disk page with a blank marker of the real one's length."""
    out = f"{view['title']}\n\n{_MARKER_BLANK}\n\n{view['notice']}\n{view['status']}\n"
    for name, kind, rows, omitted, _reserved in _sections(view, limits):
        if omitted:
            rows = rows + [_omitted_threads_note(omitted) if kind == "threads" else _omission_note(omitted)]
        empty = _EMPTY.get(name, "- (none)")
        out += f"\n## {token(name)}\n{chr(10).join(rows) or empty}\n"
    return out


def _legacy_problem():
    """The error that keeps legacy local rows in the tracked journals out of the local view.

    None when they can be read, and when the visibility policy is not ready: without a policy
    every tracked row would classify as local and flood the local page, so none are read.
    """
    if not C.visibility_ready():
        return None
    try:
        J.parse_journal(visibility="private", strict=True, physical_visibilities=("public",))
    except ValueError as error:
        return error
    return None


def _entries(scope):
    """Parse the journal rows of one scope; local rows include legacy ones in tracked journals.

    A damaged tracked journal does not hide the local journal: its legacy rows are left out and
    the local page says so (_legacy_problem).
    """
    if scope == "public":
        physical = ("public",)
    elif C.visibility_ready() and _legacy_problem() is None:
        physical = ("public", "private")
    else:
        physical = ("private",)
    return J.parse_journal(visibility=scope, strict=True, physical_visibilities=physical)


# One marker binds a page to what it was rendered from: the hash of the inputs, read before the
# render, and of the page itself with this line blanked. A page that inputs, a hand edit or another
# engine version changed since is stale; so is a page from an earlier calendar day.
_MARKER_RE = re.compile(r"^<!-- state-content-sha256:([0-9a-f]{64}) -->$", re.M)
_MARKER_BLANK = "<!-- state-content-sha256:" + "0" * 64 + " -->"
_RENDERED_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}")


def _page_fingerprint(inputs, page):
    blanked = _MARKER_RE.sub(_MARKER_BLANK, page)
    return hashlib.sha256(bytes.fromhex(inputs) + blanked.encode("utf-8")).hexdigest()


def _snapshot(scope, entries, inputs):
    view = _view(scope, entries)
    page = clip_utf8(_page(view, view["limits"]), C.threshold("now_max_bytes"))
    marker = f"<!-- state-content-sha256:{_page_fingerprint(inputs, page)} -->"
    return page.replace(_MARKER_BLANK, marker, 1)


def _input_fingerprint(scope):
    """Hash every input that can change one side's page, by content, for both the live and the
    staged check (a Git tree has no meaningful file times).

    Both engine sources are inputs, so a page rendered by an older engine reads as stale.
    """
    digest = hashlib.sha256(scope.encode() + b"\0")
    # A dossier that appears or disappears changes its row's missing-file mark.
    threads = [(key, name, dossier, _dossier_missing(dossier)) for key, name, dossier in C.threads()
               if C.thread_visibility().get(key, "public") == scope]
    policy = {
        "config_fingerprint": C.fingerprint(),
        "engine_source_fingerprints": ENGINE_SOURCE_FINGERPRINTS,
        "visibility_ready": C.visibility_ready(),
        "public_tracks": C.public_journal_tracks(),
        "legacy_cutoff": C.legacy_cutoff().isoformat() if C.legacy_cutoff() else None,
        "legacy_public_tracks": C.legacy_public_tracks(),
        "threads": threads,
        "limits": (C.threshold("now_tail_events"), C.threshold("now_recent_decisions"), C.threshold("now_max_bytes")),
        "tracks": _tracks(scope),
    }
    if scope == "public":
        policy["personal_pointer"] = C.personal_pointer()
        # The projects section and the map are read from each project's README, so a changed block,
        # or a first file written, renders the page and so redraws the map.
        policy["projects"] = _project_rows()
        policy["projects_map"] = _project_map_text()
    else:
        policy["private_threads_fingerprint"] = C.private_threads_fingerprint()
        policy["private_threads_load_ok"] = C.private_threads_ok()
    digest.update(json.dumps(policy, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    bases = [P.state()] if scope == "public" else [P.state(), P.private_state()]
    for base in bases:
        for path in P.journals_in(base):
            # The bytes come from the journal module's cache, which the parser shares.
            digest.update(os.path.relpath(path, P.instance_root()).encode("utf-8", "surrogateescape")
                          + b"\0" + J.journal_bytes(path) + b"\0")
    # Each side hashes only its own canonicals, so a local track's edit leaves the public page.
    # The page shows only a canonical's update line, so a body edit does not make it stale.
    for _key, _name, rel in _tracks(scope):
        path = _track_path(rel)
        if path is not None:
            digest.update(rel.encode("utf-8", "surrogateescape") + b"\0"
                          + _track_snippet(path).encode("utf-8") + b"\0")
    return digest.hexdigest()


def _private_inputs_present():
    """Distinguish absent local state from an explicitly present empty/degraded overlay."""
    if _tracks("private"):
        return True
    # Legacy private events may still live in tracked journals; inspect the private projection
    # before declaring local state absent. Without a ready policy that projection is not read.
    if C.visibility_ready() and J.parse_journal(visibility="private", physical_visibilities=("public",)):
        return True
    if not os.path.isdir(P.private_state()):
        return False
    if os.path.isfile(P.private_threads()):
        return True
    return bool(P.journals_in(P.private_state()))


def _render_unlocked(scope):
    """Render and publish one scope ("public" or "private"); the caller holds the state lock."""
    _assert_config_unchanged()
    if scope == "public" and not C.visibility_ready():
        raise RuntimeError(C.legacy_layout() or "visibility config is not ready; public snapshot "
                           "publish is frozen")
    path = P.now_page(scope)
    if scope == "private" and not _private_inputs_present():
        # A page left from inputs that are gone would let the manual fallback (read the local page
        # when it exists) see a state the hook calls unavailable.
        if os.path.isfile(path):
            os.unlink(path)
            safeio.fsync_parent(path)
        return
    # Hash the inputs before the render reads them: an edit in between leaves a page that reads
    # as stale at the next start, never one certified for bytes it did not see.
    inputs = _input_fingerprint(scope)
    safeio.atomic_write(path, _snapshot(scope, _entries(scope), inputs))
    if scope == "public":
        _redraw_project_map()


def _project_map_text():
    try:
        import project_folders as projects
        return projects.map_text()
    except Exception as e:  # noqa: BLE001 - see _project_rows
        return type(e).__name__


def _redraw_project_map():
    """The projects map is drawn from the same blocks as the projects section, so it is redrawn with
    the page; only between an existing marker pair, never by adding markers (KIT-DR-093)."""
    try:
        import project_folders as projects
        projects.draw()
    except Exception:  # noqa: BLE001 - a map that cannot be drawn must not take the state page down
        pass


def render():
    """Render each scope on its own so one failure (a frozen public config, a corrupt local
    journal) does not leave the other snapshot stale, as session start already does."""
    failed = False
    try:
        with J.state_lock():
            for scope in ("public", "private"):
                try:
                    _render_unlocked(scope)
                except Exception as e:
                    failed = True
                    print(RENDER_FAILED.format(error_type=type(e).__name__, error=e),
                          file=sys.stderr)
    except Exception as e:  # the lock itself could not be taken
        print(RENDER_FAILED.format(error_type=type(e).__name__, error=e), file=sys.stderr)
        return 1
    return 1 if failed else 0


def snapshots_current():
    """Whether both pages on disk are the ones the current inputs render, so reading the state
    renders nothing."""
    return not any(_snapshot_stale(scope) for scope in ("public", "private"))


def _snapshot_stale(scope, portable=False):
    """Whether the page on disk is not the one the current inputs render. portable: a staged Git
    tree, whose file times say nothing about when the page was rendered."""
    path = P.now_page(scope)
    if scope == "private" and not _private_inputs_present():
        return os.path.isfile(path)
    try:
        text = open(path, encoding="utf-8").read()
    except (OSError, UnicodeError):
        return True
    markers = _MARKER_RE.findall(text)
    if markers != [_page_fingerprint(_input_fingerprint(scope), text)]:
        return True
    if portable:
        return False
    # Age labels count calendar days, so a page from an earlier day is stale with the same inputs.
    # The render time is the page's first timestamp (its notice); a checkout resets file times.
    rendered = _RENDERED_RE.search(text)
    rendered = rendered and C.parse_timestamp(rendered.group(0))
    today = datetime.datetime.now().astimezone()
    return not rendered or rendered.astimezone(today.tzinfo).date() != today.date()


def _ensure_snapshots():
    scopes = tuple(s for s in ("public", "private") if _snapshot_stale(s))
    # Preserve the previous public snapshot on config errors; expose degraded state during recovery.
    if not C.visibility_ready():
        scopes = tuple(s for s in scopes if s != "public")
    public_error = private_error = None
    if not scopes:
        return public_error, private_error
    with J.state_lock():
        # A failed render keeps the old snapshot out of the context; the caller says public state is unavailable.
        if "public" in scopes:
            try:
                _render_unlocked("public")
            except Exception as e:
                public_error = e
        if "private" in scopes:
            try:
                _render_unlocked("private")
            except Exception as e:  # caller marks local unavailable/corrupt; public remains usable.
                private_error = e
    return public_error, private_error


# Injection assembly. The SessionStart body is built from the same view as the disk page, in
# priority order instead of clipping the page text, because a middle cut removed the dossier list
# and the newest decisions while keeping older filler. Rows go in whole: a cut row loses the end
# of a decision, often its condition, and the allocator already bounds the total.
# This is a second packer beside _fit_snapshot on purpose: _fit_snapshot fits each page alone to
# its own budget, and this one takes the rows of both fitted pages into one shared budget, where
# the room one side leaves goes to the other (test_state_runtime.py,
# test_injection_and_page_pack_differently, shows it).


def _omission_note(count):
    return f"[… {count} older event line(s) omitted · the journal in state/ keeps them …]"


# Block item standing for the omitted-dossier note; rendered only when some rows are left out.
_THREAD_NOTE = object()
# Kinds of droppable lines; _fit_injection decides the order in which they are placed.
_TIER_DECISION, _TIER_THREAD, _TIER_EVENT = 2, 3, 4
# A count with more digits than any real one: sizing renders the notes with it, so the room kept
# for a note is never shorter than the note the final render writes.
_WIDEST_COUNT = 10 ** 6


def _text_plan(text):
    """A side made only of fixed text: a status message, or the cut page just rendered."""
    drop = ("<!-- state-",) + token_forms("generated_notice")
    kept = "\n".join(x for x in text.splitlines() if not x.startswith(drop))
    # A middle cut opens with a blank line, which may land right under a heading.
    kept = re.sub(r"^(## .*)\n\n+", r"\1\n", kept, flags=re.M)
    return [(None, re.sub(r"\n{3,}", "\n\n", kept).strip("\n").split("\n"))], [], (0, 0)


def _side_plan(view):
    """Return (blocks, candidates, omitted_threads) for one side of the view.

    Each block item is a fixed string, an index into candidates, or _THREAD_NOTE. A candidate is
    a droppable line: an event row (decision tier or event tier) or a dossier row (thread tier).
    omitted_threads is the count the disk page already leaves out. The file-management lines of
    the page (fingerprints, generated-file notice) serve drift checks and human editors, not the
    model reading the injection, so the plan has none.
    """
    status = view["status"].strip() if view["scope"] == "private" else ""
    blocks = [(None, [status] if status else [])]
    candidates, omitted_threads, omitted_events = [], 0, 0
    for name, kind, rows, omitted, reserved in _sections(view, view["limits"]):
        items = list(rows) if kind == "fixed" else []
        tier = {"threads": _TIER_THREAD, "decisions": _TIER_DECISION}.get(kind, _TIER_EVENT)
        # _event_sections already keeps decision rows out of the recent rows.
        for i, row in enumerate(rows if kind != "fixed" else ()):
            # Dossiers keep list order. Events rank by time, then by place on the page; a topic's
            # newest decision ranks above the other decisions, as it does in the page.
            rank = ((-len(candidates),) if kind == "threads"
                    else (i in reserved, row[2:18], len(candidates)))
            candidates.append({"tier": tier, "rank": rank, "order": len(candidates),
                               "text": row, "cost": _nbytes(row) + 1})
            items.append(len(candidates) - 1)
        if kind == "threads":
            omitted_threads += omitted
            items.append(_THREAD_NOTE)
        elif kind == "events":
            omitted_events += omitted
        blocks.append((token(INJECTED_HEADING.get(name, name)), items))
    return blocks, candidates, (omitted_threads, omitted_events)


def _render_side(plan, chosen, sizing=False):
    """Render one side with the chosen candidates; dropped lines are counted in notes.

    sizing=True renders the widest possible notes instead, which sizes the fixed part.
    """
    blocks, candidates, (already_omitted, events_beyond) = plan
    dropped = [c for c in candidates if c["order"] not in chosen]
    events = events_beyond + sum(1 for c in dropped if c["tier"] != _TIER_THREAD)
    if sizing:
        has_threads = already_omitted or any(c["tier"] == _TIER_THREAD for c in candidates)
        threads = _WIDEST_COUNT if has_threads else 0
    else:
        threads = already_omitted + sum(1 for c in dropped if c["tier"] == _TIER_THREAD)
    parts = []
    for heading, items in blocks:
        lines = []
        for x in items:
            if x is _THREAD_NOTE:
                if threads:
                    lines.append(_omitted_threads_note(threads))
            elif isinstance(x, str):
                lines.append(x)
            elif x in chosen:
                lines.append(candidates[x]["text"])
        if heading is None:
            parts.append("\n".join(lines))
        elif lines or sizing:
            # A heading with nothing under it costs context and tells the model nothing; sizing
            # still counts every heading, since any section may get rows.
            parts.append("\n".join([f"## {heading}"] + lines))
    if sizing and (events_beyond or any(c["tier"] != _TIER_THREAD for c in candidates)):
        parts.append(_omission_note(_WIDEST_COUNT))
    elif not sizing and events:
        parts.append(_omission_note(events))
    return "\n\n".join(p for p in parts if p) + "\n"


def _allocate(pools, room):
    """Pick lines from each side's pool, best rank first, within room bytes.

    Each side first gets an equal share; whatever a side leaves unused goes to the other side's
    next-best lines. A side stops at its first line that does not fit, so a kept line never
    ranks below a dropped one from the same pool.
    """
    chosen = {side: set() for side in pools}
    pos = {side: 0 for side in pools}
    active = [side for side, pool in pools.items() if pool]
    used = 0
    if not active:
        return chosen, used
    share = room // len(active)
    for side in active:
        spent, pool = 0, pools[side]
        while pos[side] < len(pool) and spent + pool[pos[side]]["cost"] <= share:
            chosen[side].add(pool[pos[side]]["order"])
            spent += pool[pos[side]]["cost"]
            pos[side] += 1
        used += spent
    blocked = set()
    while True:
        heads = [side for side in active
                 if side not in blocked and pos[side] < len(pools[side])]
        if not heads:
            break
        side = max(heads, key=lambda x: pools[x][pos[x]]["rank"])
        item = pools[side][pos[side]]
        if used + item["cost"] > room:
            blocked.add(side)
            continue
        chosen[side].add(item["order"])
        used += item["cost"]
        pos[side] += 1
    return chosen, used


def _fit_injection(plans, room):
    """Build both injected bodies within room bytes, in priority order.

    Fixed first: titles, status and freshness lines, warnings, track rows, canonical pointers,
    and room for the omission notes, including the dossier note that names the command listing
    every dossier. Then the first decision or phase change of each side. Then dossier rows in
    list order. Then the remaining decisions and phase changes, and other recent events. Decisions
    go each recent topic's newest first, then newest first; events go newest first. Lines
    already placed are not repeated, and dropped lines are counted in the notes.
    """
    fixed = sum(_nbytes(_render_side(plan, set(), sizing=True)) for plan in plans.values())
    left = room - fixed
    if left < 0:
        # The fixed lines alone exceed the budget. Keep the byte cap as the hard limit.
        public_full = _render_side(plans["public"], set())
        private_full = _render_side(plans["private"], set())
        half = room // 2
        # Half is reserved for the public side only up to what it needs.
        public_room = min(_nbytes(public_full), max(half, room - _nbytes(private_full)))
        return (clip_utf8(public_full, public_room),
                clip_utf8(private_full, room - public_room))
    chosen = {side: set() for side in plans}
    # (tier, how many lines per side this stage may place; None means all that fit)
    stages = ((_TIER_DECISION, 1), (_TIER_THREAD, None), (_TIER_DECISION, None), (_TIER_EVENT, None))
    for tier, limit in stages:
        pools = {}
        for side, (_blocks, cands, _omitted) in plans.items():
            pool = sorted((c for c in cands if c["tier"] == tier and c["order"] not in chosen[side]),
                          key=lambda c: c["rank"], reverse=True)
            pools[side] = pool[:limit]
        picked, used = _allocate(pools, left)
        for side in plans:
            chosen[side] |= picked[side]
        left -= used
    return tuple(_render_side(plans[side], chosen[side]) for side in ("public", "private"))


def _injected_side(scope, path):
    """Return (plan, journal age) of one side; the age is the public page's, None for the private side."""
    view = _view(scope, _entries(scope))
    # Past the smallest limits the disk page was cut; its fixed rows would fill the hook room and
    # drop every candidate of both sides, so the cut page goes in as it stands.
    if _nbytes(_page(view, view["limits"])) > C.threshold("now_max_bytes"):
        return _text_plan(open(path, encoding="utf-8", errors="replace").read()), view.get("age")
    return _side_plan(view), view.get("age")


def _not_set_up():
    """True in a kit folder before setup: no config, no earlier layout and no state inputs, so
    there is nothing to inject but the way to set it up."""
    return C.not_set_up()


def build_context(public_only=False, notice=None):
    """Build the state text a session start injects, the same for every runtime.

    The caller wraps it for its runtime. public_only leaves out the local private overlay, for a
    delivery surface that cannot safely carry it; notice is one extra line in the head."""
    canary = os.environ.get("MOTTORI_HOOK_CANARY")
    if canary:
        # The round trip needs only the nonce; loading pages would put the owner's state into the
        # canary's prompt to a model provider.
        return f"HOOK_CANARY:{canary}\n"
    if _not_set_up():
        return NOT_SET_UP.format(root=P.instance_root()) + "\n"
    public_error, private_error = _ensure_snapshots()
    age = None
    if public_error is None and C.visibility_ready() and os.path.isfile(P.now_page()):
        public, age = _injected_side("public", P.now_page())
    else:
        # The last page on disk was certified under an earlier policy or input, so its rows may no
        # longer be shareable: say where the problem is instead of repeating them.
        if isinstance(public_error, OSError) and public_error.filename:
            # str() of an OS error holds absolute paths, and this text can reach a hosted model.
            names = [J.shown_path(str(n))
                     for n in (public_error.filename, public_error.filename2) if n]
            reason = f"{public_error.strerror}: " + " -> ".join(
                n if not os.path.isabs(n) else os.path.basename(n) for n in names)
        elif public_error is not None:
            reason = str(public_error)
        elif not C.visibility_ready():
            reason = C.legacy_layout() or ("visibility config is not ready; public snapshot "
                                           f"publish is frozen ({C.CONFIG_NAME})")
        else:
            reason = f"public NOW missing: {os.path.relpath(P.now_page(), P.instance_root())}"
        public = _text_plan(PUBLIC_UNAVAILABLE.format(reason=reason))
    private_inputs = _private_inputs_present()
    private_available = (private_error is None and private_inputs
                         and os.path.isfile(P.now_page("private"))
                         and not public_only)
    if public_only:
        private = _text_plan(PRIVATE_OMITTED)
        private_status = "omitted"
    elif private_available:
        private, _age = _injected_side("private", P.now_page("private"))
        private_status = ("available" if C.private_threads_ok() and _legacy_problem() is None
                          else "degraded")
    elif private_error is not None:
        private = _text_plan(PRIVATE_CORRUPT)
        private_status = "unavailable/corrupt"
    else:
        private = _text_plan((
            "[local private overlay unavailable: do not assert that it is absent]"
        ))
        private_status = "unavailable"
    head = INJECTION_HEAD.format(age="?d ago" if age is None else age, status=private_status) + "\n"
    if not C.visibility_ready():
        head += INJECTION_DEGRADED + "\n"
    if notice:
        head += notice + "\n"
    public_label, private_label = PUBLIC_LABEL, PRIVATE_LABEL
    fixed = head + public_label + private_label
    room = C.threshold("now_hook_max_bytes") - len(fixed.encode("utf-8"))
    if room < 256:
        raise ValueError("now_hook_max_bytes is smaller than the fixed header")
    public_body, private_body = _fit_injection({"public": public, "private": private}, room)
    context = head + public_label + public_body + private_label + private_body
    if len(context.encode("utf-8")) > C.threshold("now_hook_max_bytes"):
        raise AssertionError("hook byte budget miscalculated")
    return context


def _hook_errors_notice():
    """Summarise hook-errors log lines not yet reported as one line, with the offset to mark.

    The other hooks fail open and write failures only to this log; SessionStart is the one place
    that reaches the agent, so new lines are reported here once, except an optional step past its
    budget (runlog.overran), which only doctor counts. A shrunk log restarts from zero.
    """
    path = P.hook_errors()
    # The launcher only appends, so the log is bounded here.
    dropped = runlog.trim_log(path)
    try:
        seen = int(open(P.hook_errors_seen(), encoding="utf-8").read().strip())
    except (OSError, ValueError):
        seen = 0
    seen = max(seen - dropped, 0)
    if dropped:
        # A notice dropped later must not leave a mark that points into the pre-trim file.
        _mark_hook_errors(seen)
    try:
        with open(path, "rb") as f:
            if seen > os.fstat(f.fileno()).st_size:
                seen = 0
            f.seek(seen)
            data = f.read()
    except OSError:
        return None, None
    end = seen + len(data)
    text = data.decode("utf-8", "replace")
    lines = [x for x in text.splitlines() if x.strip()]
    if not lines:
        return None, end
    # Identical lines stay separate: parallel PostToolUse runs log one line per failure.
    entries = runlog.hook_error_entries(text)
    if entries:
        # An optional step past its budget stays in the log for doctor; the agent is not told.
        entries = [e for e in entries if not runlog.overran(e)]
        if not entries:
            return None, end
        # Only the matched timestamp: a long unspaced first token must not eat the byte budget.
        since = runlog.HOOK_ERROR_ENTRY.match(entries[0]).group(0)
    else:
        entries, since = lines, "?"
    return (f"[hook failures: {len(entries)} since {since}, last: {_clip_line(entries[-1], 240)} (state/.hook-errors.log)]", end)


def _mark_hook_errors(offset):
    """Record how much of the hook-errors log has been reported; never fail the hook over it."""
    if offset is None:
        return
    try:
        # Atomic: a session starting meanwhile must not read an empty cursor and report it all again.
        safeio.atomic_write(P.hook_errors_seen(), str(offset))
    except OSError:
        pass


def session_state():
    """Return the state a session starts with, headed by the hook failures not yet reported.

    The failures count as reported once this returns. A probe leaves them for the next real
    session and does not trim the logs it inspects."""
    notice, offset = (None, None) if hook_input.probe() else _hook_errors_notice()
    try:
        context = build_context(notice=notice)
    except ValueError:
        # The notice is extra: if it cannot fit, inject the state without it and keep it unreported.
        if not notice:
            raise
        context, offset = build_context(), None
    _mark_hook_errors(offset)
    return context


def hook_context():
    """Print session_state() as Claude Code's SessionStart answer, for a hook line that runs
    this command itself."""
    try:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": session_state()}}, ensure_ascii=False))
    except Exception as e:
        print(f"hook-context failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


def context(public_only=False):
    """Print the shared state body for runtimes without a hook envelope."""
    try:
        sys.stdout.write(build_context(public_only=public_only))
    except Exception as e:
        print(f"context failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


def _hook_session_hash(payload=None):
    """Hash the hook's session_id to eight characters; use unknown rather than inferred attribution."""
    sid = (hook_input.hook_payload() if payload is None else payload).get("session_id")
    return hashlib.sha256(str(sid).encode("utf-8")).hexdigest()[:8] if sid else "unknown"


def precompact(runtime=None, payload=None):
    """Record a PreCompact event with runtime and session hash; payload defaults to stdin."""
    runtime = runtime if runtime and re.fullmatch(r"[a-z]+", runtime) else "unknown"
    return log(f"[system/state] {token('compaction')} ({runtime} · s:{_hook_session_hash(payload)})"
               + token("compaction_tail"), quiet=True)


def _stale_message():
    """Say what changed since the public snapshot was rendered, from file times.

    Only the journal is examined; the other fingerprint inputs are named, not blamed.
    """
    # check() reports a missing state/NOW.md as now-absent and never reaches this function.
    rendered = datetime.datetime.fromtimestamp(os.path.getmtime(P.now_page())).astimezone()
    written = max((os.path.getmtime(path) for path in P.journals_in(P.state())), default=0)
    if written > rendered.timestamp():
        # No count of lines: entry times can be backdated or share the render second, so only the
        # file time says exactly that the journal changed after the render.
        what = "the journal was written at {written}".format(written=datetime.datetime.fromtimestamp(
            written).strftime("%Y-%m-%d %H:%M"))
    else:
        what = STALE_OTHER
    return CHECK_NOW_INPUT_NEWER.format(rendered=rendered.strftime("%Y-%m-%d %H:%M"), what=what)


class _Findings:
    """What check found: each finding has a stable id, so new wording, ages or line numbers do
    not make a known issue new, and is gated (the turn-end gate counts it) or advisory."""

    def __init__(self):
        self.notices, self.warns = [], []

    def add(self, gated, ident, text):
        self.warns.append((gated, ident, text))

    def notice(self, ident, text):
        self.notices.append((ident, text))

    def report(self, issues):
        """Print the findings and return check's result.

        In issues mode each line is stable-id<TAB>message, an advisory id carries a ~ prefix, and
        the last line counts the gated ones; the result is then 0. Otherwise the result is the
        number of warnings."""
        if issues:
            for ident, text in self.notices:
                print(f"~{ident}\t{text}")
            for gated, ident, text in self.warns:
                print(f"{ident if gated else '~' + ident}\t{text}")
            print(f"#issues {sum(1 for gated, _ident, _text in self.warns if gated)}")
            return 0
        for _ident, text in self.notices:
            print("--", text)
        for _gated, _ident, text in self.warns:
            print("⚠", text)
        print(f"check: {len(self.warns)} warning(s)" if self.warns else "check: clean")
        return len(self.warns)


def check(memory_dir=None, root=None, issues=False, portable=False, repair=False):
    """Report state drift and return its count; in issues mode print the gate protocol instead.

    Read-only by default: doctor, the gardener and fixture tests call it to measure. Only with
    repair (the turn-end gate passes --repair) does the live path re-render a stale snapshot first.
    portable checks a staged Git tree, which has no local-only files and no meaningful file times,
    so only the journals and the public page are judged there.
    """
    root = root or P.instance_root()
    found = _Findings()
    if _before_setup(root, found):
        return found.report(issues)
    entries = _journal_damage(found, portable)
    if portable:
        _staged_page(found)
        return found.report(issues)
    _canonicals_behind(root, entries, found)
    # Imported here, so the commands hooks run (log, precompact, hook-context) need only the
    # modules imported at the top. The assistant's memory folder sits beside the transcript folder.
    import memory_index
    memory_index.audit(memory_dir or os.path.join(P.transcripts(), "memory"), found.add)
    _instance_checks(root, found)
    _page_freshness(root, repair, found)
    _journal_age(entries, found)
    return found.report(issues)


def _before_setup(root, found):
    """Whether the live instance has no config: a kit tree before setup, or a damaged instance.

    A fixture root given by a caller is never an installation, so it is not judged here."""
    if os.path.realpath(root) != os.path.realpath(P.instance_root()):
        return False
    if os.path.isfile(P.config_file(root)):
        return False
    legacy = C.legacy_layout(root)
    if legacy:
        found.add(True, "config-legacy-layout", legacy)
    elif P.state_evidence(root):
        found.add(True, "config-absent",
                  f"[NOW config missing] state inputs exist but {C.CONFIG_NAME} does not")
    else:
        found.notice("now-not-applicable", CHECK_NOT_APPLICABLE)
    return True


def _journal_damage(found, portable):
    """Report each damaged journal row and return the readable rows."""
    errors = []
    entries = J.parse_journal(errors=errors, physical_visibilities=("public",) if portable else None)
    for item in errors:
        found.add(True, "journal-corrupt:" + hashlib.sha1(item.encode()).hexdigest()[:10],
                  f"[journal corrupt] {item}")
    return entries


def _page_tracked():
    """Whether Git tracks the public page in this instance; a kit installation ignores state/."""
    import subprocess
    try:
        listed = subprocess.run(["git", "-C", P.instance_root(), "ls-files", "-z", "--",
                                 os.path.relpath(P.now_page(), P.instance_root())],
                                capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell: judge the page as before
    return listed.returncode != 0 or bool(listed.stdout)


def _staged_page(found):
    # A page Git does not track is not part of any commit, so a commit does not judge it; the
    # turn-end check renders it again when it is stale.
    if not _page_tracked():
        return
    if not os.path.isfile(P.now_page()):
        found.add(True, "now-absent", CHECK_NOW_ABSENT.format(path=P.now_page()))
    elif _snapshot_stale("public", portable=True):
        found.add(True, "now-input-newer", CHECK_NOW_INPUT_NEWER_STAGED)


def _canonicals_behind(root, entries, found):
    """A canonical is behind when its update line is older than its track's newest state change.

    Only a change of the track's state counts: an idea or a lesson would block the turn until an
    edit that reconciles nothing. A canonical without a dated update line is behind as well."""
    latest = {}
    for e in entries:
        if e["type"] in STATE_CHANGE_TYPES:
            latest[e["track"]] = e["ts"]
    for key, _name, rel in C.tracks():
        path = os.path.join(root, rel)
        if key not in latest or not os.path.exists(path):
            continue
        day = _update_day(path)
        # The update line is written in local days, so the event date is taken in the local zone.
        event_day = C.parse_timestamp(latest[key]).astimezone().date().isoformat()
        if day is None or day < event_day:
            # A reminder, not a handover failure: it never stops a turn (KIT-DR-081). The file may be
            # in a folder the owner adopted, which the rules say not to edit.
            found.add(False, f"canonical-stale:{rel}", CHECK_CANONICAL_STALE.format(
                rel=rel, file_date=day or "no dated update line", track=key,
                journal_date=event_day))


def _instance_checks(root, found):
    """An instance may add its own checks in tools/now_instance.py; the kit ships none."""
    try:
        import now_instance
    except ModuleNotFoundError as e:
        if e.name != "now_instance":
            raise
    else:
        now_instance.check(root, found.add)


def _page_freshness(root, repair, found):
    """Whether the public page is the one the current inputs render.

    A new calendar day alone makes the page stale; with repair it is rendered again, as session
    start does, and only what a render could not fix is reported. The render always targets
    P.instance_root(), so a check of another root never repairs."""
    if not os.path.exists(P.now_page()):
        found.add(True, "now-absent", CHECK_NOW_ABSENT.format(path=P.now_page()))
        return
    if not _snapshot_stale("public"):
        return
    if repair and os.path.abspath(root) == os.path.abspath(P.instance_root()):
        try:
            _ensure_snapshots()
        except Exception:  # noqa: BLE001 - the still-stale snapshot is reported below
            pass
    if _snapshot_stale("public"):
        found.add(True, "now-input-newer", _stale_message())


def _journal_age(entries, found):
    """Days since the newest recorded public event, and a month whose journal does not exist yet.

    Compactions touch the journal on every summary, so the age follows recorded events. Any
    earlier journal makes a missing one a month rollover, whatever its age; only a workspace with
    no journal at all is gated."""
    current = P.journal_file()
    age = _age_days(current)
    if age is None:
        older = [x for x in (_age_days(path) for path in P.journals_in(P.state())) if x is not None]
        if older:
            found.add(False, "journal-rollover", CHECK_JOURNAL_ROLLOVER.format(
                name=os.path.basename(current), age=min(older)))
        else:
            found.add(True, "journal-absent", f"[journal missing] {current}")
        return
    human_age = _human_event_age([e for e in entries if e.get("visibility") == "public"])
    if human_age is not None:
        age = human_age
    if age > C.threshold("journal_stale_days"):
        found.add(False, "journal-stale",
                  f"[journal stale] {age}d old (threshold {C.threshold('journal_stale_days')}d)")


def log_help():
    """How to write a journal line here: the types this workspace takes and the tracks it knows."""
    listed = C.public_journal_tracks()
    registered = ", ".join(key for key, _name, _canonical in C.tracks()) or "none yet"
    tracks = (LOG_TRACKS_ANY.format(names=registered) if listed is None
              else LOG_TRACKS_LISTED.format(names=", ".join(listed) or "no track"))
    return LOG_HELP.format(types=", ".join(C.journal_types()), tracks=tracks)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd in ("-h", "--help"):
        print(__doc__)
        return 0
    if cmd == "log":
        args = sys.argv[2:]
        if not args or args[0] in ("-h", "--help"):
            # An agent that is unsure asks here first; answering saves it reading the config and this file.
            print(log_help())
            return 0 if args else 1
        force_private = "--private" in args
        args = [x for x in args if x != "--private"]
        return log(" ".join(args), force_private=force_private)
    if cmd == "render":
        r = render()
        if r == 0:
            print(f"NOW.md regenerated ({os.path.getsize(P.now_page())} bytes)")
        return r
    if cmd == "check":
        n = check(issues="--issues" in sys.argv, portable="--portable" in sys.argv,
                  repair="--repair" in sys.argv)
        return 0 if n == 0 else 2
    if cmd == "threads":
        return threads()
    if cmd == "hook-context":
        return hook_context()
    if cmd == "context":
        return context(public_only="--public-only" in sys.argv)
    if cmd == "precompact":
        args = sys.argv[2:]
        runtime = None
        if "--runtime" in args:
            i = args.index("--runtime")
            runtime = args[i + 1] if i + 1 < len(args) else None
        return precompact(runtime)
    print(f"unknown command: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
