#!/usr/bin/env python3
"""Append journal events, render state, and detect state drift.

Commands:
  log [--private] "[track/type] text"  Append a validated event and regenerate NOW.
  render                             Regenerate NOW only.
  threads                            Show configured dossier pointers.
  hook-context                       Emit SessionStart additionalContext JSON.
  context [--public-only]             Emit the same state as plain text.
  precompact [--runtime NAME]         Record a compaction event.
  check [--issues] [--portable]       Report state drift.

NOW is generated. Edit the source journal or canonical document instead."""
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M

NOW_SOURCE_FINGERPRINT = M.file_fingerprint(__file__)


def _t(key, **kw):
    """Return catalog text from tools/i18n.py in the instance language.

    now.py is also copied alone with memlib.py into hook fixtures. Without the catalog it returns
    the key and its values, so commands still complete; state tokens come from memlib and stay
    well formed either way.
    """
    try:
        from i18n import t
        return t(key, **kw)
    except (ImportError, KeyError):
        return key + "".join(f" {name}={value}" for name, value in sorted(kw.items()))


class RuntimeInputChanged(RuntimeError):
    """A process-local policy or implementation snapshot no longer matches disk."""


class LoadedInputChanged(RuntimeInputChanged):
    """An import-time identity changed; continuing could cross the privacy boundary."""


class _SkipCheck(Exception):
    """Signal that a drift check does not apply to this instance."""


class ConfigChanged(LoadedInputChanged):
    """The privacy routing policy changed during a state transaction."""


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
    """Emit one mutation warning without echoing config or private-derived values."""
    if M.VISIBILITY_READY:
        return
    safe = []
    if any(w.startswith(M.CONFIG_WARNING_MISSING + ":") for w in M.CONFIG_WARNINGS):
        safe.append(_t("now.visibility_config_missing"))
    if any(w.startswith(M.CONFIG_WARNING_INVALID + ":") for w in M.CONFIG_WARNINGS):
        safe.append(_t("now.visibility_config_invalid"))
    if any(w.startswith(M.CONFIG_WARNING_VISIBILITY) for w in M.CONFIG_WARNINGS):
        safe.append(_t("now.visibility_unavailable",
                       config=M.CONFIG_SCHEMA, engine=M.SCHEMA_VERSION))
    detail = " · ".join(safe) or _t("now.visibility_generic")
    print(_t("now.visibility_fail_closed", detail=detail), file=sys.stderr)


def _assert_journal_tail(path):
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as tail:
            tail.seek(-1, os.SEEK_END)
            if tail.read(1) != b"\n":
                raise ValueError(_t("now.journal_tail_missing_newline", path=path))


def _append_journal(line, path, event_time):
    """Caller holds the repo-wide state lock."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    _assert_journal_tail(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(f"# journal {event_time:%Y-%m}\n\n"
                    + _t("now.journal_header", retroactive=M.token("retroactive")) + "\n\n")
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _assert_config_unchanged():
    """Do not mutate under a policy different from the immutable config loaded at import."""
    path = os.path.join(M.ROOT, "system", "memory-config.json")
    current = M.config_fingerprint(path)
    if current != M.CONFIG_FINGERPRINT:
        raise ConfigChanged(_t("now.config_changed"))


def _assert_runtime_inputs_unchanged(scopes=("public", "private")):
    """Loaded identities must still match every scope being certified."""
    _assert_config_unchanged()
    checks = [
        (__file__, NOW_SOURCE_FINGERPRINT, "now.py source"),
        (M.__file__, M.MEMLIB_SOURCE_FINGERPRINT, "memlib.py source"),
    ]
    if "private" in scopes:
        checks.append(
            (M.PRIVATE_THREADS_PATH, M.PRIVATE_THREADS_FINGERPRINT,
             "private thread registry"))
    for path, expected, label in checks:
        if M.file_fingerprint(path) != expected:
            raise LoadedInputChanged(_t("now.input_changed", label=label))


def _rollback_journal(path, existed, size, previous_stat=None):
    """Undo only the just-appended bytes when a privacy policy race is detected."""
    if existed:
        with open(path, "r+b") as f:
            f.truncate(size)
            f.flush()
            os.fsync(f.fileno())
        if previous_stat is not None:
            os.chmod(path, previous_stat.st_mode & 0o7777)
            os.utime(path, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
    else:
        try:
            os.unlink(path)
        except FileNotFoundError:
            return
    try:
        dfd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def log(body, quiet=False, force_private=False):
    event_time = datetime.datetime.now().astimezone()
    line = f"- {_now_iso(event_time)} {body.strip()}"
    err = M.validate_line(line)
    if err:
        print(_t("now.log_refused", error=err, line=line), file=sys.stderr)
        return 1
    _warn_visibility_fail_closed()
    match = M.JOURNAL_LINE.match(line)
    visibility = M.journal_visibility(match.group("track"), force_private=force_private)
    # Fix event time and journal path once so append and rollback agree across a month boundary.
    journal_path = M.journal_path(dt=event_time, visibility=visibility)
    try:
        # Hold one lock across append and snapshot publication to prevent stale writers from winning.
        with M.locked():
            _assert_runtime_inputs_unchanged((visibility,))
            # Do not append after a corrupt existing event.
            _assert_journal_tail(journal_path)
            public_corruption = None
            if visibility == "public":
                M.parse_journal(strict=True, physical_visibilities=("public",))
            else:
                M.parse_journal(strict=True, physical_visibilities=("private",))
                # The local overlay also projects legacy rows from the public journal. A corrupt
                # public journal blocks that projection, but it must not block moving a sensitive
                # event into the local journal, which is the safe destination.
                try:
                    M.parse_journal(strict=True, physical_visibilities=("public",))
                except ValueError as error:
                    public_corruption = error
            _assert_runtime_inputs_unchanged((visibility,))
            existed = os.path.isfile(journal_path)
            size = os.path.getsize(journal_path) if existed else 0
            previous_stat = os.stat(journal_path) if existed else None
            try:
                _append_journal(line, journal_path, event_time)
                if public_corruption is None:
                    _render_unlocked((visibility,))
            except Exception:
                _rollback_journal(journal_path, existed, size, previous_stat)
                raise
    except Exception as e:  # Propagate failure so hook callers can use their fallback.
        print(_t("now.log_failed", error_type=type(e).__name__, error=e), file=sys.stderr)
        return 1
    if public_corruption is not None:
        print(_t("now.log_local_not_rendered", error=public_corruption), file=sys.stderr)
    if not quiet:
        print(_t("now.log_recorded", visibility=visibility, line=line))
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
        rows.append(_t("now.track_row", name=name, rel=rel, age=age, warn=warn,
                       snippet=snippet or _t("now.track_no_update_line")))
    # Do not render a null personal pointer.
    pointer = (_t("now.personal_pointer", path=M.PERSONAL_POINTER) if M.PERSONAL_POINTER
               else _t("now.personal_pointer_unset"))
    rows.append(_t("now.personal_row", pointer=pointer))
    return rows


def _thread_rows(visibility):
    """Return one display row per registered dossier of the given visibility, in config order."""
    rows = []
    for key, name, dossier in M.THREADS:
        if M.THREAD_VISIBILITY.get(key, "public") != visibility:
            continue
        rows.append(_t("now.thread_row", name=name, dossier=dossier) if dossier
                    else _t("now.thread_row_unset", name=name))
    return rows


def threads():
    """Print the configured deep-thread dossier registry."""
    if not M.THREADS:
        print(_t("now.threads_none"))
        return 0
    for key, name, dossier in M.THREADS:
        exists = ("" if (dossier and os.path.exists(os.path.join(M.ROOT, dossier)))
                  else _t("now.threads_file_missing"))
        print(f"{key:<12} {name}\n{'':<12} "
              + _t("now.threads_dossier", dossier=dossier or _t("now.threads_unset"), exists=exists))
    return 0


def _pointer_block():
    """Build canonical-document pointers from instance config."""
    parts = []
    for key, name, canon in M.TRACKS:
        refs = "+".join(f"`{p}`" for p in [canon] + M.track_also(key))
        parts.append(f"{name} {refs}")
    if M.PERSONAL_POINTER:
        parts.append(_t("now.pointer_personal", path=M.PERSONAL_POINTER))
    parts.append(_t("now.pointer_facts"))
    parts.append(_t("now.pointer_decisions"))
    parts.append(_t("now.pointer_recall"))
    # Wrap pointer rows in groups of three for readability.
    chunks = [" · ".join(parts[i:i + 3]) for i in range(0, len(parts), 3)]
    return "\n".join(chunks) or _t("now.no_tracks")


def _clip_event_body(body, max_bytes):
    if max_bytes is None or len(body.encode("utf-8")) <= max_bytes:
        return body
    marker = "…"
    room = max(0, max_bytes - len(marker.encode("utf-8")))
    return body.encode("utf-8")[:room].decode("utf-8", "ignore") + marker


def _omitted_threads_note(count):
    return _t("now.omitted_threads", count=count)


# Recognise the omitted-dossier note in either language so the injection can recount it.
def _omitted_threads_re():
    try:
        from i18n import STRINGS
        forms = STRINGS["now.omitted_threads"].values()
    except (ImportError, KeyError):
        forms = [_omitted_threads_note(0).replace("0", "{count}", 1)]
    return re.compile("^(?:" + "|".join(
        re.escape(form).replace(re.escape("{count}"), r"(?P<n%d>\d+)" % i)
        for i, form in enumerate(forms)) + ")$")


def _thread_block(rows, shown, empty):
    """Render the first `shown` dossier rows, then one note naming how many were left out."""
    if not rows:
        return empty
    kept = rows[:shown]
    if shown < len(rows):
        kept.append(_omitted_threads_note(len(rows) - shown))
    return "\n".join(kept)


def _fit_snapshot(builder, thread_count=0):
    """Fit a snapshot into NOW_MAX_BYTES by dropping whole lines in priority order.

    builder(decisions, recent, body_limit, threads) renders the snapshot with at most that many
    decision rows, recent rows and dossier rows, event bodies clipped to body_limit bytes. Lines
    go in this order: older recent events, older decisions, dossier rows from the end of the list
    (their place taken by a note with the omitted count and the command that lists them all),
    long event bodies, and finally every recent event and all but the newest decision. Status
    lines and section headings are never dropped. A snapshot whose fixed lines alone are over the
    budget is cut in the middle rather than failing, so session start still gets a state body.
    """
    decisions, recent = M.NOW_RECENT_DECISIONS, M.NOW_TAIL_EVENTS
    threads, body_limit = thread_count, None
    while True:
        out = builder(decisions, recent, body_limit, threads)
        if len(out.encode("utf-8")) <= M.NOW_MAX_BYTES:
            return out
        if recent > 3:
            recent -= 1
        elif decisions > 2:
            decisions -= 1
        elif threads > 0:
            threads -= 1
        elif body_limit is None:
            body_limit = 256
        elif body_limit > 32:
            body_limit //= 2
        elif recent > 0:
            recent -= 1
        elif decisions > 1:
            decisions -= 1
        else:
            return M.clip_utf8(out, M.NOW_MAX_BYTES)


_CONTENT_FINGERPRINT_PLACEHOLDER = (
    "<!-- state-content-sha256:" + "0" * 64 + " -->")


def _is_compaction(entry):
    body = entry.get("body", "")
    return entry.get("type") == "state" and any(
        marker in body for marker in M.token_forms("compaction"))


def _human_event_age(entries, now=None):
    """Days since the newest non-compaction event, or None when there is none.

    Every compaction appends to the journal, so the file mtime stays fresh even when nobody has
    recorded a decision for weeks. Freshness must follow what people recorded.
    """
    human = [e for e in entries if not _is_compaction(e)]
    if not human:
        return None
    now = now or datetime.datetime.now().astimezone()
    newest = max(M._parse_journal_timestamp(e["ts"]) for e in human)
    return (now.date() - newest.astimezone(now.tzinfo).date()).days


def _compaction_summary(entries):
    """Return one projection row that stands for every compaction event, or None.

    Compactions say that the conversation was summarized, not what was decided. Listing them one by
    one crowded decisions out of the fixed byte budget, so the projection keeps only the count,
    the runtimes, and the newest time. The source journal keeps every event.
    """
    runs = [e for e in entries if _is_compaction(e)]
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
    folded["body"] = _t("now.compaction_summary", marker=M.token("compaction"), count=len(runs),
                        parts=parts, last=runs[-1]["ts"][:16], tail=M.token("compaction_tail"))
    return folded


def _event_sections(entries, decision_limit, recent_limit):
    """Choose rows for the decision section and the recent section.

    Decisions exclude compactions. Recent events skip rows already shown as decisions and carry at
    most one compaction row, placed where the newest compaction happened.
    """
    decisions = [e for e in entries
                 if e["type"] in ("decision", "state") and not _is_compaction(e)]
    decisions = decisions[-decision_limit:] if decision_limit else []
    shown = {id(e) for e in decisions}
    summary = _compaction_summary(entries)
    last_compaction = next((e for e in reversed(entries) if _is_compaction(e)), None)
    timeline = []
    for e in entries:
        if e is last_compaction:
            timeline.append(summary)
        elif not _is_compaction(e) and id(e) not in shown:
            timeline.append(e)
    recent = timeline[-recent_limit:] if recent_limit else []
    return decisions, recent


def _public_snapshot(entries, fingerprint):
    jp = M.journal_path()
    j_age = _human_event_age(entries)
    if j_age is None:
        j_age = _age_days(jp)
    fresh = [_t("now.freshness_journal", age=j_age if j_age is not None else "?")
             + (" ⚠" if (j_age is None or j_age > M.JOURNAL_STALE_DAYS) else "")]

    def fmt(e, body_limit):
        return (f"- {e['ts'][:16]} [{e['track']}/{e['type']}] "
                f"{_clip_event_body(e['body'], body_limit)}")

    thread_rows = _thread_rows('public')

    def build(decision_limit, recent_limit, body_limit, thread_limit):
        decisions, recent = _event_sections(entries, decision_limit, recent_limit)
        none = _t("now.none")
        return f"""# NOW

<!-- state-inputs-sha256:{fingerprint} -->
{_CONTENT_FINGERPRINT_PLACEHOLDER}

{_t("now.public_notice", generated=M.token("generated_notice"), ts=_now_iso())}
{_t("now.freshness", items=" · ".join(fresh))}

## {M.token("section_tracks")}
{chr(10).join(_track_rows())}

## {M.token("section_threads")}
{_thread_block(thread_rows, thread_limit, _t("now.no_shared_threads"))}
{_t("now.return_ritual")}

## {M.token("section_decisions")}
{chr(10).join(fmt(e, body_limit) for e in decisions) or none}

## {M.token("section_events")}
{chr(10).join(fmt(e, body_limit) for e in recent) or none}

## {M.token("section_pointers")}
{_pointer_block()}
"""
    return _bind_content_fingerprint("public", _fit_snapshot(build, len(thread_rows)))


def _private_snapshot(entries, fingerprint):
    def fmt(e, body_limit):
        return (f"- {e['ts'][:16]} [{e['track']}/{e['type']}] "
                f"{_clip_event_body(e['body'], body_limit)}")

    thread_rows = _thread_rows('private')

    def build(decision_limit, recent_limit, body_limit, thread_limit):
        decisions, recent = _event_sections(entries, decision_limit, recent_limit)
        health = ("" if M.PRIVATE_THREADS_LOAD_OK else
                  "\n" + _t("now.private_degraded") + "\n")
        none = _t("now.none")
        return f"""# NOW — local private overlay

<!-- state-inputs-sha256:{fingerprint} -->
{_CONTENT_FINGERPRINT_PLACEHOLDER}

{_t("now.private_notice", generated=M.token("generated_notice"), ts=_now_iso())}
{health}

## {M.token("section_local_threads")}
{_thread_block(thread_rows, thread_limit, none)}

## {M.token("section_local_decisions")}
{chr(10).join(fmt(e, body_limit) for e in decisions) or none}

## {M.token("section_local_events")}
{chr(10).join(fmt(e, body_limit) for e in recent) or none}
"""
    return _bind_content_fingerprint("private", _fit_snapshot(build, len(thread_rows)))


def _publish_if_changed(path, text):
    try:
        if os.path.isfile(path) and open(path, encoding="utf-8").read() == text:
            # Refresh the validation cursor when inputs were touched without changing bytes.
            os.utime(path, None)
            return False
    except OSError:
        pass
    M.atomic_write(path, text)
    return True


def _snapshot_backup(path):
    """Capture exactly the snapshot state a failed publish transaction must restore."""
    try:
        with open(path, "rb") as f:
            previous_stat = os.fstat(f.fileno())
            data = f.read()
        return True, data, previous_stat
    except FileNotFoundError:
        return False, None, None


def _fsync_parent(path):
    try:
        dfd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _restore_snapshot(path, backup):
    existed, data, previous_stat = backup
    if not existed:
        try:
            os.unlink(path)
        except FileNotFoundError:
            return
        _fsync_parent(path)
        return
    M.atomic_write(path, data.decode("utf-8"))
    os.chmod(path, previous_stat.st_mode & 0o7777)
    os.utime(path, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))


def _restore_attempted_snapshots(attempted, backups, original_error):
    failures = []
    for scope, path in reversed(attempted):
        try:
            _restore_snapshot(path, backups[scope])
        except Exception as error:  # keep restoring earlier scopes after one rollback failure.
            failures.append((scope, error))
    if failures:
        detail = ", ".join(f"{scope}:{type(error).__name__}" for scope, error in failures)
        raise RuntimeError(
            _t("now.rollback_failed", detail=detail, cause=type(original_error).__name__)
        ) from failures[0][1]


_FINGERPRINT_RE = re.compile(r"^<!-- state-inputs-sha256:([0-9a-f]{64}) -->$", re.M)
_CONTENT_FINGERPRINT_RE = re.compile(
    r"^<!-- state-content-sha256:([0-9a-f]{64}) -->$", re.M)


def _fingerprint_file(digest, path, portable=False):
    """Hash content and metadata because both can change rendered freshness labels."""
    rel = os.path.relpath(path, M.ROOT)
    digest.update(rel.encode("utf-8", "surrogateescape") + b"\0")
    try:
        stat = os.stat(path)
        if not portable:
            digest.update(f"{stat.st_mtime_ns}:".encode())
        digest.update(f"{stat.st_size}".encode() + b"\0")
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                digest.update(block)
    except (FileNotFoundError, NotADirectoryError):
        digest.update(b"<missing>")


def _input_fingerprint(scope, portable=False):
    """Fingerprint every input that can change a public or local projection.

    Journal mtime alone missed valid policy, thread-registry, canonical-file, and renderer changes.
    The marker lives in the generated snapshot, so a fresh runtime can cheaply decide whether the
    bytes were rendered under the policy it has actually loaded.
    """
    digest = hashlib.sha256()
    # Git trees lack mtimes: staged checks use content markers while live checks also track metadata.
    flavor = "state-content-v1" if portable else "state-snapshot-v1"
    digest.update((flavor + "\0" + scope + "\0" +
                   datetime.datetime.now().astimezone().date().isoformat()).encode())
    threads = [(key, name, dossier) for key, name, dossier in M.THREADS
               if M.THREAD_VISIBILITY.get(key, "public") == scope]
    policy = {
        "config_fingerprint": M.CONFIG_FINGERPRINT,
        "now_source_fingerprint": NOW_SOURCE_FINGERPRINT,
        "memlib_source_fingerprint": M.MEMLIB_SOURCE_FINGERPRINT,
        "visibility_ready": M.VISIBILITY_READY,
        "public_tracks": M.PUBLIC_JOURNAL_TRACKS,
        "legacy_cutoff": M.LEGACY_CUTOFF.isoformat() if M.LEGACY_CUTOFF else None,
        "legacy_public_tracks": M.LEGACY_PUBLIC_TRACKS,
        "threads": threads,
        "limits": (M.NOW_TAIL_EVENTS, M.NOW_RECENT_DECISIONS, M.NOW_MAX_BYTES),
    }
    if scope == "public":
        policy.update({"tracks": M.TRACKS, "personal_pointer": M.PERSONAL_POINTER})
    else:
        policy["private_threads_fingerprint"] = M.PRIVATE_THREADS_FINGERPRINT
        policy["private_threads_load_ok"] = M.PRIVATE_THREADS_LOAD_OK
    digest.update(json.dumps(policy, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    paths = []
    bases = [M.STATE] if scope == "public" else [M.STATE, M.PRIVATE_STATE]
    for base in bases:
        if os.path.isdir(base):
            paths.extend(os.path.join(base, name) for name in sorted(os.listdir(base))
                         if re.match(r"journal-\d{4}-\d{2}\.md$", name))
    if scope == "public":
        paths.extend(os.path.join(M.ROOT, rel) for _key, _name, rel in M.TRACKS)
    for path in paths:
        _fingerprint_file(digest, path, portable=portable)
    return digest.hexdigest()


def _assert_projection_inputs_unchanged(scopes, before, phase):
    _assert_runtime_inputs_unchanged(scopes)
    current = {scope: _input_fingerprint(scope) for scope in scopes}
    changed = [scope for scope in scopes if before[scope] != current[scope]]
    if changed:
        raise RuntimeInputChanged(
            _t("now.snapshot_input_changed", phase=phase, scopes=", ".join(changed)))


def _normalized_snapshot_bytes(text):
    """Remove the content marker's self-reference while preserving every other byte."""
    normalized, count = _CONTENT_FINGERPRINT_RE.subn(
        _CONTENT_FINGERPRINT_PLACEHOLDER, text)
    if count != 1:
        raise ValueError(_t("now.snapshot_marker_count"))
    return normalized.encode("utf-8")


def _snapshot_content_fingerprint(scope, text):
    """Bind portable inputs and the complete rendered snapshot without recursion."""
    snapshot = _normalized_snapshot_bytes(text)
    digest = hashlib.sha256()
    digest.update(b"state-snapshot-content-v2\0")
    digest.update(scope.encode("ascii") + b"\0")
    digest.update(bytes.fromhex(_input_fingerprint(scope, portable=True)))
    digest.update(len(snapshot).to_bytes(8, "big"))
    digest.update(snapshot)
    return digest.hexdigest()


def _bind_content_fingerprint(scope, text):
    markers = _CONTENT_FINGERPRINT_RE.findall(text)
    if markers != ["0" * 64]:
        raise ValueError(_t("now.snapshot_placeholder_count"))
    fingerprint = _snapshot_content_fingerprint(scope, text)
    return text.replace(
        _CONTENT_FINGERPRINT_PLACEHOLDER,
        f"<!-- state-content-sha256:{fingerprint} -->",
        1,
    )


def _private_inputs_present():
    """Distinguish absent local state from an explicitly present empty/degraded overlay."""
    # Legacy private events may still live in tracked journals; inspect the private projection before declaring local state absent.
    if M.parse_journal(visibility="private", physical_visibilities=("public",)):
        return True
    if not os.path.isdir(M.PRIVATE_STATE):
        return False
    if os.path.isfile(M.PRIVATE_THREADS_PATH):
        return True
    if any(re.match(r"journal-\d{4}-\d{2}\.md$", name)
           for name in os.listdir(M.PRIVATE_STATE)):
        return True
    return False


def _render_unlocked(scopes=("public", "private")):
    _assert_runtime_inputs_unchanged(scopes)
    if "public" in scopes and not M.VISIBILITY_READY:
        raise RuntimeError(_t("now.public_publish_frozen"))
    before = {scope: _input_fingerprint(scope) for scope in scopes}
    rendered = {}
    if "public" in scopes:
        public = M.parse_journal(visibility="public", strict=True,
                                 physical_visibilities=("public",))
        rendered["public"] = _public_snapshot(public, before["public"])
    if "private" in scopes and _private_inputs_present():
        private = M.parse_journal(visibility="private", strict=True,
                                  physical_visibilities=("public", "private"))
        rendered["private"] = _private_snapshot(private, before["private"])

    # Rendering reads journals, canonicals and local registry.  A before/after identity pair makes
    # the marker certify the bytes actually observed, rather than newer bytes read only by hashing.
    _assert_projection_inputs_unchanged(scopes, before, "render")

    targets = []
    if "public" in rendered:
        targets.append(("public", M.NOW_PATH, rendered["public"]))
    if "private" in rendered:
        targets.append(("private", M.PRIVATE_NOW_PATH, rendered["private"]))
    backups = {scope: _snapshot_backup(path) for scope, path, _text in targets}
    attempted = []
    try:
        for scope, path, text in targets:
            _assert_projection_inputs_unchanged(scopes, before, "pre-publish")
            attempted.append((scope, path))
            _publish_if_changed(path, text)
            # atomic replace/touch happens after the last pre-publish check. Certify both
            # loaded identity and all dynamic scope inputs immediately after it returns.
            _assert_projection_inputs_unchanged(scopes, before, "publish")
    except Exception as error:
        _restore_attempted_snapshots(attempted, backups, error)
        raise


def render():
    try:
        with M.locked():
            _render_unlocked(("public",))
            if _private_inputs_present():
                _render_unlocked(("private",))
    except Exception as e:
        print(_t("now.render_failed", error_type=type(e).__name__, error=e), file=sys.stderr)
        return 1
    return 0


def _snapshot_stale(scope, portable=False):
    path = M.NOW_PATH if scope == "public" else M.PRIVATE_NOW_PATH
    if scope == "private" and not _private_inputs_present():
        return False
    if scope == "private" and (
            M.file_fingerprint(M.PRIVATE_THREADS_PATH) != M.PRIVATE_THREADS_FINGERPRINT):
        return True
    if not os.path.isfile(path):
        return True
    try:
        text = open(path, encoding="utf-8").read()
        content_markers = _CONTENT_FINGERPRINT_RE.findall(text)
        if len(content_markers) != 1:
            return True
        if content_markers[0] != _snapshot_content_fingerprint(scope, text):
            return True
        if portable:
            return False
        input_markers = _FINGERPRINT_RE.findall(text)
        if len(input_markers) != 1:
            return True
        return input_markers[0] != _input_fingerprint(scope)
    except (OSError, UnicodeError, ValueError):
        return True


def _ensure_snapshots():
    scopes = tuple(s for s in ("public", "private") if _snapshot_stale(s))
    # Preserve the previous public snapshot on config errors; expose degraded state during recovery.
    if not M.VISIBILITY_READY:
        scopes = tuple(s for s in scopes if s != "public")
    if not scopes:
        return None
    private_error = None
    with M.locked():
        # local corruption must not erase an otherwise valid public SessionStart injection.
        if "public" in scopes:
            _render_unlocked(("public",))
        if "private" in scopes:
            try:
                _render_unlocked(("private",))
            except Exception as e:  # caller marks local unavailable/corrupt; public remains usable.
                private_error = e
    return private_error


# Injection assembly. NOW snapshots are written for people and for drift checks; the SessionStart
# injection is built from their sections in priority order instead of clipping their text, because
# a middle cut removed the dossier list and the newest decisions while keeping older filler.
_INJECT_EVENT_RE = re.compile(r"^- (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2})")
# Snapshots rendered in either language are recognised, so a language switch keeps the priorities.
_INJECT_DECISION_SECTIONS = (M.token_forms("section_decisions")
                             + M.token_forms("section_local_decisions"))
_INJECT_EVENT_SECTIONS = M.token_forms("section_events") + M.token_forms("section_local_events")
# One event line may not take more than this, so a single long body cannot crowd out the rest.
INJECT_LINE_MAX_BYTES = 400


def _nbytes(text):
    return len(text.encode("utf-8"))


def _clip_line(line, max_bytes=INJECT_LINE_MAX_BYTES):
    if _nbytes(line) <= max_bytes:
        return line
    marker = "…"
    return M._utf8_prefix(line, max_bytes - _nbytes(marker)) + marker


def _omission_note(count):
    return _t("now.omitted_events", count=count)


def _snapshot_blocks(text):
    """Split a NOW snapshot into blocks of (heading or None, lines).

    File-management lines are dropped: the fingerprint comments and the generated-file notice
    serve drift checks and human editors, not the model reading the injection.
    """
    blocks = [(None, [])]
    in_notice = False
    notice = M.token_forms("generated_notice")
    for line in text.splitlines():
        if line.startswith("## "):
            in_notice = False
            blocks.append((line[3:].strip(), []))
            continue
        if blocks[-1][0] is None:
            if line.startswith("<!-- state-"):
                continue
            if line.startswith(notice):
                in_notice = True
            if in_notice:
                closed = line.rstrip().endswith("*") and not line.startswith(notice)
                if closed:
                    in_notice = False
                continue
        blocks[-1][1].append(line)
    out = []
    for heading, lines in blocks:
        # Dropped notice lines leave blank runs behind; keep at most one blank line in a row.
        lines[:] = [x for i, x in enumerate(lines)
                    if x.strip() or (i and lines[i - 1].strip())]
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        if heading is not None or lines:
            out.append((heading, lines))
    return out


_INJECT_THREAD_SECTIONS = M.token_forms("section_threads") + M.token_forms("section_local_threads")
# Block item standing for the omitted-dossier note; rendered only when some rows are left out.
_THREAD_NOTE = object()
# Kinds of droppable lines; _fit_injection decides the order in which they are placed.
_TIER_DECISION, _TIER_THREAD, _TIER_EVENT = 2, 3, 4


def _side_plan(text, side):
    """Return (blocks, candidates, omitted_threads) for one snapshot.

    Each block item is a fixed string, an index into candidates, or _THREAD_NOTE. A candidate is
    a droppable line: an event row (decision tier or event tier) or a dossier row (thread tier).
    omitted_threads is the count already named by the snapshot's own omitted-dossier note.
    """
    blocks, candidates, seen = [], [], set()
    note_re = _omitted_threads_re()
    omitted_threads = 0
    for heading, lines in _snapshot_blocks(text):
        threads = heading in _INJECT_THREAD_SECTIONS
        tier = (_TIER_DECISION if heading in _INJECT_DECISION_SECTIONS
                else _TIER_EVENT if heading in _INJECT_EVENT_SECTIONS else None)
        items = []
        for line in lines:
            if threads:
                note = note_re.match(line)
                if note:
                    omitted_threads += int(next(v for v in note.groupdict().values() if v))
                    continue
                if line.startswith("- "):
                    clipped = _clip_line(line)
                    candidates.append({"side": side, "tier": _TIER_THREAD,
                                       "rank": (-len(candidates),), "order": len(candidates),
                                       "text": clipped, "cost": _nbytes(clipped) + 1})
                    items.append(len(candidates) - 1)
                    continue
                if _THREAD_NOTE not in items:
                    items.append(_THREAD_NOTE)
                items.append(line)
                continue
            m = _INJECT_EVENT_RE.match(line) if tier else None
            if not m:
                items.append(line)
                continue
            clipped = _clip_line(line)
            if clipped in seen:
                continue
            seen.add(clipped)
            candidates.append({"side": side, "tier": tier, "rank": (m.group("ts"), len(candidates)),
                               "order": len(candidates), "text": clipped,
                               "cost": _nbytes(clipped) + 1})
            items.append(len(candidates) - 1)
        if threads and _THREAD_NOTE not in items:
            items.append(_THREAD_NOTE)
        blocks.append((heading, items))
    return blocks, candidates, omitted_threads


def _render_side(plan, chosen, sizing=False):
    """Render one side with the chosen candidates; dropped lines are counted in notes.

    sizing=True renders the widest possible notes instead, which sizes the fixed part.
    """
    blocks, candidates, already_omitted = plan
    dropped = [c for c in candidates if c["order"] not in chosen]
    events = sum(1 for c in dropped if c["tier"] != _TIER_THREAD)
    if sizing:
        has_threads = already_omitted or any(c["tier"] == _TIER_THREAD for c in candidates)
        threads = 10 ** 6 if has_threads else 0
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
        else:
            parts.append("\n".join([f"## {heading}"] + lines))
    if sizing and any(c["tier"] != _TIER_THREAD for c in candidates):
        parts.append(_omission_note(10 ** 6))
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


def _fit_injection(public_text, private_text, room):
    """Build both injected bodies within room bytes, in priority order.

    Fixed first: titles, status and freshness lines, warnings, track rows, canonical pointers,
    and room for the omission notes, including the dossier note that names the command listing
    every dossier. Then the newest decision or phase change of each side. Then dossier rows in
    list order. Then the remaining decisions and phase changes, newest first, and other recent
    events, newest first. Lines already placed are not repeated, and dropped lines are counted
    in the notes.
    """
    plans = {"public": _side_plan(public_text, "public"),
             "private": _side_plan(private_text, "private")}
    fixed = sum(_nbytes(_render_side(plan, set(), sizing=True)) for plan in plans.values())
    left = room - fixed
    if left < 0:
        # The fixed lines alone exceed the budget. Keep the byte cap as the hard limit.
        public_full = _render_side(plans["public"], set())
        private_full = _render_side(plans["private"], set())
        half = room // 2
        public_room = max(half, room - _nbytes(private_full))
        return (M.clip_utf8(public_full, public_room),
                M.clip_utf8(private_full, room - public_room))
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


def build_context(public_only=False):
    """Build runtime-neutral injected state. The caller supplies the envelope. public_only excludes the private overlay when the delivery surface cannot safely carry it."""
    private_error = _ensure_snapshots()
    if not os.path.isfile(M.NOW_PATH):
        raise FileNotFoundError(_t("now.public_missing", path=M.NOW_PATH))
    public = open(M.NOW_PATH, encoding="utf-8").read()
    age = _age_days(M.NOW_PATH)
    private_inputs = _private_inputs_present()
    private_available = (private_error is None and private_inputs
                         and os.path.isfile(M.PRIVATE_NOW_PATH)
                         and not public_only)
    if public_only:
        private = _t("now.private_omitted")
        private_status = "omitted"
    elif private_available:
        private = open(M.PRIVATE_NOW_PATH, encoding="utf-8").read()
        private_status = "available" if M.PRIVATE_THREADS_LOAD_OK else "degraded"
    elif private_error is not None:
        private = _t("now.private_corrupt")
        private_status = "unavailable/corrupt"
    else:
        private = _t("now.private_unavailable")
        private_status = "unavailable"
    canary = os.environ.get("MOTTORI_HOOK_CANARY")
    head = _t("now.injection_head", age=age, status=private_status) + "\n"
    if not M.VISIBILITY_READY:
        head += _t("now.injection_degraded") + "\n"
    if canary:
        head += f"HOOK_CANARY:{canary}\n"
    public_label = "\n## PUBLIC STATE\n"
    private_label = "\n## LOCAL PRIVATE OVERLAY\n"
    fixed = head + public_label + private_label
    room = M.NOW_HOOK_MAX_BYTES - len(fixed.encode("utf-8"))
    if room < 256:
        raise ValueError(_t("now.hook_budget_too_small"))
    public_body, private_body = _fit_injection(public, private, room)
    context = head + public_label + public_body + private_label + private_body
    if len(context.encode("utf-8")) > M.NOW_HOOK_MAX_BYTES:
        raise AssertionError(_t("now.hook_budget_error"))
    return context


def hook_context():
    """Wrap the shared state body as SessionStart hookSpecificOutput JSON."""
    try:
        context = build_context()
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context}}, ensure_ascii=False))
    except Exception as e:
        print(_t("now.hook_context_failed", error_type=type(e).__name__, error=e), file=sys.stderr)
        return 1
    return 0


def context(public_only=False):
    """Print the shared state body for runtimes without a hook envelope."""
    try:
        sys.stdout.write(build_context(public_only=public_only))
    except Exception as e:
        print(_t("now.context_failed", error_type=type(e).__name__, error=e), file=sys.stderr)
        return 1
    return 0


def _compaction_tag_re():
    """Match the runtime tag after a compaction marker written in any language."""
    import re as _re
    markers = "|".join(_re.escape(marker) for marker in M.token_forms("compaction"))
    return _re.compile(r"(?:" + markers
                       + r") \((?P<runtime>[a-z]+) · s:(?P<sid>[0-9a-f]{8}|unknown)\)")


def _hook_session_hash():
    """Hash hook stdin session_id to eight characters; use unknown rather than inferred attribution.
    Wait at most 0.5 seconds so an idle stdin cannot hang the hook."""
    import hashlib as _h
    import json as _json
    import select as _select
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return "unknown"
        ready, _, _ = _select.select([sys.stdin], [], [], 0.5)
        if not ready:
            return "unknown"
        raw = sys.stdin.read()
        sid = _json.loads(raw).get("session_id") if raw.strip() else None
        if not sid:
            return "unknown"
        return _h.sha256(str(sid).encode("utf-8")).hexdigest()[:8]
    except Exception:
        return "unknown"


def precompact(runtime=None):
    """Record a PreCompact event with runtime and session hash."""
    import re as _re
    runtime = runtime if runtime and _re.fullmatch(r"[a-z]+", runtime) else "unknown"
    return log(f"[system/state] {M.token('compaction')} ({runtime} · s:{_hook_session_hash()})"
               + M.token("compaction_tail"), quiet=True)


VOLATILE_RE = None

# File and status names written by optional instance adapters (recording reader, gap recovery,
# drive inbox). Those adapters write Korean names; the kit has no writer for them, so only that
# form is recognised. Escaped because engine source is English.
_RECORDING_READ_MARKER = ".\uc815\ub3c5\uc644\ub8cc"
_RECORDING_GAP_REPORT = "\uacb0\uc190\ubcf5\uad6c.md"
_INBOX_DONE = "\uc644\ub8cc"


def check(memory_dir=None, root=None, issues=False, portable=False):
    """Report state drift and return its count. In issues mode, distinguish advisory time-based findings from gated edit-induced findings."""
    import hashlib as _h
    import glob as _glob
    import re as _re
    root = root or M.ROOT
    # Derive the auto-memory directory from the transcript directory.
    memory_dir = memory_dir or os.path.join(M.TRANSCRIPTS, "memory")

    # Separate stable issue identity from display text so wording, age, and line changes do not create new issues.
    warns = []
    notices = []
    def W(gated, ident, text):
        warns.append((gated, ident, text))

    def N(ident, text):
        notices.append((ident, text))

    def finish():
        if issues:
            # Protocol: stable-id<TAB>message, optional ~ prefix for advisory findings, then a final count trailer.
            gated = 0
            for ident, text in notices:
                print(f"~{ident}\t{text}")
            for gated_issue, ident, text in warns:
                print(f"{ident if gated_issue else '~' + ident}\t{text}")
                gated += 1 if gated_issue else 0
            print(f"#issues {gated}")
            return 0
        for _ident, text in notices:
            print("--", text)
        for _gated, _ident, text in warns:
            print("⚠", text)
        print(_t("now.check_warnings", count=len(warns)) if warns else _t("now.check_clean"))
        return len(warns)

    # Distinguish pre-setup development trees from broken installations; fixture root overrides are not installations.
    if os.path.realpath(root) == os.path.realpath(M.ROOT):
        config_path = os.path.join(root, "system", "memory-config.json")
        if not os.path.isfile(config_path):
            state_dir = os.path.join(root, "state")
            private_state_dir = os.path.join(root, "_private", "state")
            state_dirs = (state_dir, private_state_dir)
            has_now = any(os.path.isfile(os.path.join(path, "NOW.md"))
                          for path in state_dirs)
            has_journal = any(_glob.glob(os.path.join(path, "journal-*.md"))
                              for path in state_dirs)
            has_private_threads = os.path.isfile(
                os.path.join(private_state_dir, "threads.json"))
            if has_now or has_journal or has_private_threads:
                W(True, "config-absent", _t("now.check_config_absent"))
            else:
                N("now-not-applicable", _t("now.check_not_applicable"))
            return finish()

    # Canonical documents are stale when their track has a newer journal event; this is edit-induced.
    parse_errors = []
    entries = M.parse_journal(
        errors=parse_errors,
        physical_visibilities=("public",) if portable else None,
    )
    for item in parse_errors:
        ident = _h.sha1(item.encode()).hexdigest()[:10]
        W(True, "journal-corrupt:" + ident, _t("now.check_journal_corrupt", item=item))
    if portable:
        # Staged trees lack local recordings, inboxes, and mtimes; validate only portable tracked state there.
        if not os.path.isfile(M.NOW_PATH):
            W(True, "now-absent", _t("now.check_now_absent", path=M.NOW_PATH))
        elif _snapshot_stale("public", portable=True):
            W(True, "now-input-newer", _t("now.check_now_input_newer_staged"))
        return finish()
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
                  _t("now.check_canonical_stale", rel=rel, file_date=fdate, track=key,
                     journal_date=jdate))

    # Detect volatile state claims in the memory index, not provenance dates.
    # The vocabulary is Korean wording for a status that goes stale (a wait, a scheduled item), so
    # a match is advisory: ordinary words must not block the turn-end gate. The words are data,
    # kept in Korean only and escaped because engine source is English.
    idx = os.path.join(memory_dir, "MEMORY.md")

    vol = _re.compile("\ub300\uae30\\b|\ucf5c \ub300\uae30|\uc628\uc0ac\uc774\ud2b8|\ub51c \uad6d\uba74|\u2192 \ub51c"
                      "|R\\d [\ud654\uc218\ubaa9\uae08\uc6d4]|\uc608\uc815\\)")
    if os.path.exists(idx):
        for i, line in enumerate(open(idx, encoding="utf-8"), 1):
            if line.startswith("- ") and vol.search(line):
                # Exclude line numbers from stable IDs.
                m = _re.search(r"\]\(([a-z0-9-]+\.md)\)", line)
                k = m.group(1) if m else _h.sha1(line.strip().encode()).hexdigest()[:8]
                W(False, f"index-volatile:{k}",
                  _t("now.check_index_volatile", line_no=i, line=line.strip()[:80]))

    # Check memory-file and index consistency.
    if os.path.exists(idx):
        text = open(idx, encoding="utf-8").read()
        files = {f for f in os.listdir(memory_dir)
                 if f.endswith(".md") and f != "MEMORY.md"}
        linked = set(_re.findall(r"\]\(([a-z0-9-]+\.md)\)", text))
        # Count links in one level of *-index.md files directly linked by MEMORY.md as indexed.
        via = {}  # Map a sub-index link to its source index for missing-target reports.
        for sub in [x for x in linked if x.endswith("-index.md") and x in files]:
            try:
                sub_text = open(os.path.join(memory_dir, sub), encoding="utf-8").read()
            except Exception as e:
                W(True, f"subindex-unreadable:{sub}",
                  _t("now.check_subindex_unreadable", name=sub, error=e))
                continue
            for x in _re.findall(r"\]\(([a-z0-9-]+\.md)\)", sub_text):
                if x not in linked:
                    via.setdefault(x, sub)
        linked |= set(via)
        for f in sorted(files - linked):
            W(True, f"index-missing:{f}", _t("now.check_index_missing", name=f))
        for f in sorted(linked - files):
            src = via.get(f, "MEMORY.md")
            W(True, f"index-ghost:{f}", _t("now.check_index_ghost", name=f, source=src))

    # Old project-memory entries are advisory rot candidates.
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
                  _t("now.check_memory_rot", name=f, age=age))

    # Detect recordings that stopped before the required reading output. Each finding names the
    # tool that resolves it, so it runs only when that tool is installed; otherwise the gate would
    # block on a command the instance cannot run.
    rec_root = os.path.join(root, "_private", "recordings")
    has_regap = os.path.isfile(os.path.join(root, "tools", "regap.py"))
    has_reader = os.path.isfile(os.path.join(root, "tools", "analyze_recording.py"))
    if os.path.isdir(rec_root) and (has_regap or has_reader):
        for name in sorted(os.listdir(rec_root)):
            rd = os.path.join(rec_root, name)
            # Only date-slug folders following the recording adapter convention are recordings.
            if not os.path.isdir(rd) or not re.match(r"^\d{4}-\d{2}-\d{2}-", name):
                continue
            try:
                files = os.listdir(rd)
            except OSError:
                continue
            if not any(f.endswith("-timestamped.txt") for f in files):
                continue
            # Accept the previous analysis.md output convention for completed readings.
            if "analysis.md" in files and "linebyline" not in files \
                    and os.path.exists(os.path.join(rd, _RECORDING_READ_MARKER)):
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
            if has_regap and gap_rows and _RECORDING_GAP_REPORT not in files:
                W(True, "rec-gaps:" + name,
                  _t("now.check_recording_gaps", name=name, count=gap_rows))
            if has_reader and "analysis-linebyline.md" not in files:
                W(True, "rec-unread:" + name, _t("now.check_recording_unread", name=name))

    # The optional inbox adapter requires reading completion for imported items. Skip the check when the adapter is absent.
    try:
        if os.path.join(root, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(root, "tools"))
        if not os.path.exists(os.path.join(root, "tools", "drive_inbox.py")):
            raise _SkipCheck()
        import drive_inbox as _di
        _path, _rows = _di.survey()
        if _path is None:
            # Report an unavailable mount rather than treating it as an empty inbox.
            W(False, "drive-inbox-unmounted", _t("now.check_inbox_unmounted"))
        else:
            for _f, _fp, _st, _why in _rows:
                if _st != _INBOX_DONE:
                    W(True, "drive-inbox:" + _f,
                      _t("now.check_inbox_pending", name=_f, status=_st,
                         reason=" ({})".format(_why) if _why else ""))
    except _SkipCheck:
        pass
    except Exception as _e:  # noqa: BLE001
        W(False, "drive-inbox-error",
          _t("now.check_inbox_failed", error=_e))

    # Check NOW freshness.
    a = _age_days(M.NOW_PATH)
    if a is None:
        W(True, "now-absent", _t("now.check_now_absent", path=M.NOW_PATH))
    elif a > 3:
        W(False, "now-stale", _t("now.check_now_stale", age=a))
    elif _snapshot_stale("public", portable=portable):
        W(True, "now-input-newer", _t("now.check_now_input_newer"))

    # Use the previous month's journal during normal rollover; distinguish a recent prior journal from total absence.
    jp = M.journal_path()
    ja = _age_days(jp)
    if ja is not None:
        # Compactions touch the journal on every summary; staleness follows recorded events.
        human_age = _human_event_age([e for e in entries if e.get("visibility") == "public"])
        if human_age is not None:
            ja = human_age
    if ja is None:
        others = sorted(_glob.glob(os.path.join(os.path.dirname(jp), "journal-*.md")))
        newest = min((x for x in (_age_days(o) for o in others) if x is not None), default=None)
        if newest is not None and newest <= M.JOURNAL_STALE_DAYS:
            W(False, "journal-rollover",
              _t("now.check_journal_rollover", name=os.path.basename(jp), age=newest))
        else:
            W(True, "journal-absent", _t("now.check_journal_absent", path=jp))
    elif ja > M.JOURNAL_STALE_DAYS:
        W(False, "journal-stale",
          _t("now.check_journal_stale", age=ja, threshold=M.JOURNAL_STALE_DAYS))

    return finish()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "log":
        args = sys.argv[2:]
        force_private = "--private" in args
        args = [x for x in args if x != "--private"]
        return log(" ".join(args), force_private=force_private)
    if cmd == "render":
        r = render()
        if r == 0:
            print(_t("now.render_done", bytes=os.path.getsize(M.NOW_PATH)))
        return r
    if cmd == "check":
        n = check(issues="--issues" in sys.argv, portable="--portable" in sys.argv)
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
    print(_t("now.unknown_command", command=cmd, doc=__doc__))
    return 1


if __name__ == "__main__":
    sys.exit(main())
