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
    if any(w.startswith("config 없음:") for w in M.CONFIG_WARNINGS):
        safe.append("config 없음")
    if any(w.startswith("config 로드/검증 실패:") for w in M.CONFIG_WARNINGS):
        safe.append("config 로드/검증 실패")
    if any(w.startswith("journal_visibility 사용 불가") for w in M.CONFIG_WARNINGS):
        safe.append(
            f"journal_visibility 사용 불가 "
            f"(config schema={M.CONFIG_SCHEMA}, engine schema={M.SCHEMA_VERSION})")
    detail = " · ".join(safe) or "visibility config 사용 불가"
    print(f"[state] privacy fail-close: {detail}; 새 사건은 local에 기록", file=sys.stderr)


def _assert_journal_tail(path):
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as tail:
            tail.seek(-1, os.SEEK_END)
            if tail.read(1) != b"\n":
                raise ValueError(f"journal 손상: {path} 끝 개행 없음 — tail을 수리하기 전 append 거부")


def _append_journal(line, path, event_time):
    """Caller holds the repo-wide state lock."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    _assert_journal_tail(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(f"# journal {event_time:%Y-%m}\n\n"
                    "형식: `- <ISO8601> [<track>/<type>] <내용> (→ ref)*` · "
                    "type 정의는 `tools/memlib.py` · 소급 기입은 `(소급)` 표기\n\n")
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _assert_config_unchanged():
    """Do not mutate under a policy different from the immutable config loaded at import."""
    path = os.path.join(M.ROOT, "system", "memory-config.json")
    current = M.config_fingerprint(path)
    if current != M.CONFIG_FINGERPRINT:
        raise ConfigChanged("config가 명령 실행 중 바뀜 — 새 프로세스로 재시도")


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
            raise LoadedInputChanged(f"{label}가 명령 실행 중 바뀜 — 새 프로세스로 재시도")


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
        print(f"거부: {err}\n  줄: {line}", file=sys.stderr)
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
            physical = ("public",) if visibility == "public" else ("public", "private")
            M.parse_journal(strict=True, physical_visibilities=physical)
            _assert_runtime_inputs_unchanged((visibility,))
            existed = os.path.isfile(journal_path)
            size = os.path.getsize(journal_path) if existed else 0
            previous_stat = os.stat(journal_path) if existed else None
            try:
                _append_journal(line, journal_path, event_time)
                _render_unlocked((visibility,))
            except Exception:
                _rollback_journal(journal_path, existed, size, previous_stat)
                raise
    except Exception as e:  # Propagate failure so hook callers can use their fallback.
        print(f"상태 기록 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if not quiet:
        print(f"기록({visibility}): {line}")
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
    # Do not render a null personal pointer.
    pointer = f"정본 `{M.PERSONAL_POINTER}`" if M.PERSONAL_POINTER else "정본 미지정 (config personal_pointer)"
    rows.append(f"- **개인** — {pointer} (개인 영역: NOW에 내용 비표시)")
    return rows


def _thread_rows(visibility):
    rows = []
    for key, name, dossier in M.THREADS:
        if M.THREAD_VISIBILITY.get(key, "public") != visibility:
            continue
        rows.append(f"- {name} — " + (f"서류철 `{dossier}`" if dossier
                                     else "서류철 **미지정** (Phase 2)"))
    return rows


def threads():
    """Print the configured deep-thread dossier registry."""
    if not M.THREADS:
        print("(등록된 스레드 없음 — system/memory-config.json의 threads에 추가)")
        return 0
    for key, name, dossier in M.THREADS:
        exists = "" if (dossier and os.path.exists(os.path.join(M.ROOT, dossier))) else "  [파일 없음]"
        print(f"{key:<12} {name}\n{'':<12} 서류철: {dossier or '미지정'}{exists}")
    return 0


def _pointer_block():
    """Build canonical-document pointers from instance config."""
    parts = []
    for key, name, canon in M.TRACKS:
        refs = "+".join(f"`{p}`" for p in [canon] + M.track_also(key))
        parts.append(f"{name} {refs}")
    if M.PERSONAL_POINTER:
        parts.append(f"개인 `{M.PERSONAL_POINTER}`")
    parts.append("개인 사실 `python3 tools/rec.py find|hot`")
    parts.append("결정 기록 `system/decisions.md`")
    parts.append('회상 `python3 tools/recall.py find "질의"`')
    # Wrap pointer rows in groups of three for readability.
    chunks = [" · ".join(parts[i:i + 3]) for i in range(0, len(parts), 3)]
    return "\n".join(chunks) or "- (트랙 미정의)"


def _clip_event_body(body, max_bytes):
    if max_bytes is None or len(body.encode("utf-8")) <= max_bytes:
        return body
    marker = "…"
    room = max(0, max_bytes - len(marker.encode("utf-8")))
    return body.encode("utf-8")[:room].decode("utf-8", "ignore") + marker


def _fit_snapshot(builder):
    """Trim old repeated lines while retaining the fixed structure and recent events."""
    decisions, recent = M.NOW_RECENT_DECISIONS, M.NOW_TAIL_EVENTS
    body_limit = None
    while True:
        out = builder(decisions, recent, body_limit)
        if len(out.encode("utf-8")) <= M.NOW_MAX_BYTES:
            return out
        if recent > 3:
            recent -= 1
        elif decisions > 2:
            decisions -= 1
        elif body_limit is None:
            body_limit = 256
        elif body_limit > 32:
            body_limit //= 2
        else:
            raise ValueError("NOW mandatory section skeleton이 byte budget을 초과")


_CONTENT_FINGERPRINT_PLACEHOLDER = (
    "<!-- state-content-sha256:" + "0" * 64 + " -->")


def _public_snapshot(entries, fingerprint):
    entries = _fold_compactions(entries)
    jp = M.journal_path()
    j_age = _age_days(jp)
    fresh = [f"journal {j_age if j_age is not None else '?'}일 전"
             + (" ⚠" if (j_age is None or j_age > M.JOURNAL_STALE_DAYS) else "")]

    def fmt(e, body_limit):
        return (f"- {e['ts'][:16]} [{e['track']}/{e['type']}] "
                f"{_clip_event_body(e['body'], body_limit)}")

    def build(decision_limit, recent_limit, body_limit):
        recent = entries[-recent_limit:]
        decisions = [e for e in entries if e["type"] in ("decision", "state")][-decision_limit:]
        return f"""# NOW

<!-- state-inputs-sha256:{fingerprint} -->
{_CONTENT_FINGERPRINT_PLACEHOLDER}

*생성 {_now_iso()} · `python3 tools/now.py render` — **손 편집 금지** (public projection).
공유 가능한 상태에 대해서만 이 파일이 정본이다. local 상태는 local private overlay와 합친다.*
*입력 신선도: {' · '.join(fresh)}*

## 트랙 온도판
{chr(10).join(_track_rows())}

## 살아 있는 스레드 (서류철)
{chr(10).join(_thread_rows('public')) or '- (공유 스레드 없음)'}
*(복귀 의식: 깊은 스레드로 돌아올 때 서류철부터 읽는다 — PRD §3.3)*

## 최근 결정·국면
{chr(10).join(fmt(e, body_limit) for e in decisions) or '- (없음)'}

## 최근 사건
{chr(10).join(fmt(e, body_limit) for e in recent) or '- (없음)'}

## 정본 포인터
{_pointer_block()}
"""
    return _bind_content_fingerprint("public", _fit_snapshot(build))


def _private_snapshot(entries, fingerprint):
    entries = _fold_compactions(entries)
    def fmt(e, body_limit):
        return (f"- {e['ts'][:16]} [{e['track']}/{e['type']}] "
                f"{_clip_event_body(e['body'], body_limit)}")

    def build(decision_limit, recent_limit, body_limit):
        recent = entries[-recent_limit:]
        decisions = [e for e in entries if e["type"] in ("decision", "state")][-decision_limit:]
        health = ("" if M.PRIVATE_THREADS_LOAD_OK else
                  "\n> [DEGRADED: local thread registry가 불완전하다. doctor로 수리 필요.]\n")
        return f"""# NOW — local private overlay

<!-- state-inputs-sha256:{fingerprint} -->
{_CONTENT_FINGERPRINT_PLACEHOLDER}

*생성 {_now_iso()} · `_private/state/` 로컬 전용 생성물.
이 파일만으로 public 상태를 대체하지 않는다. `state/NOW.md`와 합친 view가 local 정본이다.*
{health}

## 로컬 스레드 (서류철)
{chr(10).join(_thread_rows('private')) or '- (없음)'}

## 최근 로컬 결정·국면
{chr(10).join(fmt(e, body_limit) for e in decisions) or '- (없음)'}

## 최근 로컬 사건
{chr(10).join(fmt(e, body_limit) for e in recent) or '- (없음)'}
"""
    return _bind_content_fingerprint("private", _fit_snapshot(build))


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
            f"snapshot rollback 실패 ({detail}); 원인={type(original_error).__name__}"
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
            f"snapshot input이 {phase} 중 바뀜: " + ", ".join(changed))


def _normalized_snapshot_bytes(text):
    """Remove the content marker's self-reference while preserving every other byte."""
    normalized, count = _CONTENT_FINGERPRINT_RE.subn(
        _CONTENT_FINGERPRINT_PLACEHOLDER, text)
    if count != 1:
        raise ValueError("snapshot content marker가 정확히 하나여야 함")
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
        raise ValueError("snapshot content marker placeholder가 정확히 하나여야 함")
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
        raise RuntimeError("visibility config가 준비되지 않아 public snapshot publish를 동결")
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
        print(f"NOW render 실패: {type(e).__name__}: {e}", file=sys.stderr)
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


def build_context(public_only=False):
    """Build runtime-neutral injected state. The caller supplies the envelope. public_only excludes the private overlay when the delivery surface cannot safely carry it."""
    private_error = _ensure_snapshots()
    if not os.path.isfile(M.NOW_PATH):
        raise FileNotFoundError(f"public NOW 부재: {M.NOW_PATH}")
    public = open(M.NOW_PATH, encoding="utf-8").read()
    age = _age_days(M.NOW_PATH)
    private_inputs = _private_inputs_present()
    private_available = (private_error is None and private_inputs
                         and os.path.isfile(M.PRIVATE_NOW_PATH)
                         and not public_only)
    if public_only:
        private = ("[local private overlay 생략 — 이 배선은 public 상태만 주입한다. "
                   "local 상태는 unavailable이지 없음이 아니다]")
        private_status = "omitted"
    elif private_available:
        private = open(M.PRIVATE_NOW_PATH, encoding="utf-8").read()
        private_status = "available" if M.PRIVATE_THREADS_LOAD_OK else "degraded"
    elif private_error is not None:
        private = ("[local private overlay unavailable/corrupt — public 상태만 주입됨. "
                   "doctor로 수리하기 전 local 상태를 없음으로 단언하지 말 것]")
        private_status = "unavailable/corrupt"
    else:
        private = "[local private overlay unavailable — 없음으로 단언하지 말 것]"
        private_status = "unavailable"
    canary = os.environ.get("MOTTORI_HOOK_CANARY")
    head = (f"[상태 자동 주입 · public {age}일 전 · local overlay "
            f"{private_status}]\n"
            "public projection과 local overlay를 합친 view가 정본이다.\n")
    if not M.VISIBILITY_READY:
        head += "[DEGRADED: visibility config 불가 · public snapshot frozen · 새 사건은 local]\n"
    if canary:
        head += f"HOOK_CANARY:{canary}\n"
    public_label = "\n## PUBLIC STATE\n"
    private_label = "\n## LOCAL PRIVATE OVERLAY\n"
    fixed = head + public_label + private_label
    room = M.NOW_HOOK_MAX_BYTES - len(fixed.encode("utf-8"))
    if room < 256:
        raise ValueError("now_hook_max_bytes가 고정 헤더보다 작다")
    if private_available:
        public_budget = int(room * 0.62)
        private_budget = room - public_budget
    else:
        marker_n = len(private.encode("utf-8"))
        private_budget = marker_n
        public_budget = room - marker_n
    context = (head + public_label + M.clip_utf8(public, public_budget)
               + private_label + M.clip_utf8(private, private_budget))
    if len(context.encode("utf-8")) > M.NOW_HOOK_MAX_BYTES:
        raise AssertionError("hook byte budget 계산 오류")
    return context


def hook_context():
    """Wrap the shared state body as SessionStart hookSpecificOutput JSON."""
    try:
        context = build_context()
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context}}, ensure_ascii=False))
    except Exception as e:
        print(f"hook-context 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


def context(public_only=False):
    """Print the shared state body for runtimes without a hook envelope."""
    try:
        sys.stdout.write(build_context(public_only=public_only))
    except Exception as e:
        print(f"context 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


COMPACTION_TOKEN = "컴팩션 발생"


def _compaction_tag_re():
    import re as _re
    return _re.compile(r"컴팩션 발생 \((?P<runtime>[a-z]+) · s:(?P<sid>[0-9a-f]{8}|unknown)\)")


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
    return log(f"[system/state] {COMPACTION_TOKEN} ({runtime} · s:{_hook_session_hash()}) — 이후 컨텍스트는 요약본",
               quiet=True)


def _fold_compactions(entries):
    """Fold consecutive compaction events by runtime in the projection only.
    Do not cross non-compaction events or alter the original journal."""
    tag_re = _compaction_tag_re()
    out, run = [], []

    def flush():
        if not run:
            return
        if len(run) == 1:
            out.append(run[0])
            run.clear()
            return
        counts = {}
        for e in run:
            m = tag_re.search(e.get("body", ""))
            rt = m.group("runtime") if m else "unknown"
            counts[rt] = counts.get(rt, 0) + 1
        parts = " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        folded = dict(run[0])
        folded["body"] = (f"{COMPACTION_TOKEN} {len(run)}회 ({parts}) ~{run[-1]['ts'][:16]}"
                          " — 이후 컨텍스트는 요약본")
        out.append(folded)
        run.clear()

    for e in entries:
        if e.get("type") == "state" and COMPACTION_TOKEN in e.get("body", ""):
            run.append(e)
        else:
            flush()
            out.append(e)
    flush()
    return out


VOLATILE_RE = None


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
        print(f"check: 경고 {len(warns)}건" if warns else "check: 깨끗함")
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
                W(True, "config-absent",
                  "[NOW config 부재] state 입력은 있지만 "
                  "system/memory-config.json이 없음")
            else:
                N("now-not-applicable",
                  "[NOW 검사 해당없음] config와 state 입력이 없는 설치 전 개발 트리")
            return finish()

    # Canonical documents are stale when their track has a newer journal event; this is edit-induced.
    parse_errors = []
    entries = M.parse_journal(
        errors=parse_errors,
        physical_visibilities=("public",) if portable else None,
    )
    for item in parse_errors:
        ident = _h.sha1(item.encode()).hexdigest()[:10]
        W(True, "journal-corrupt:" + ident, "[journal 손상] " + item)
    if portable:
        # Staged trees lack local recordings, inboxes, and mtimes; validate only portable tracked state there.
        if not os.path.isfile(M.NOW_PATH):
            W(True, "now-absent", f"[NOW 부재] {M.NOW_PATH}")
        elif _snapshot_stale("public", portable=True):
            W(True, "now-input-newer", "[NOW 입력이 더 새로움] staged journal과 snapshot 불일치")
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
                  f"[정본 낙후] {rel} ({fdate}) < journal {key} 최신 사건 ({jdate})")

    # Detect volatile state claims in the memory index, not provenance dates.
    idx = os.path.join(memory_dir, "MEMORY.md")

    vol = _re.compile(r"대기\b|콜 대기|온사이트|딜 국면|→ 딜|R\d [화수목금월]|예정\)")
    if os.path.exists(idx):
        for i, line in enumerate(open(idx, encoding="utf-8"), 1):
            if line.startswith("- ") and vol.search(line):
                # Exclude line numbers from stable IDs.
                m = _re.search(r"\]\(([a-z0-9-]+\.md)\)", line)
                k = m.group(1) if m else _h.sha1(line.strip().encode()).hexdigest()[:8]
                W(True, f"index-volatile:{k}",
                  f"[인덱스 휘발성] MEMORY.md:{i} {line.strip()[:80]}")

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
                W(True, f"subindex-unreadable:{sub}", f"[하위 색인 읽기 실패] {sub}: {e}")
                continue
            for x in _re.findall(r"\]\(([a-z0-9-]+\.md)\)", sub_text):
                if x not in linked:
                    via.setdefault(x, sub)
        linked |= set(via)
        for f in sorted(files - linked):
            W(True, f"index-missing:{f}", f"[인덱스 누락] {f} — 파일은 있는데 인덱스 줄 없음")
        for f in sorted(linked - files):
            src = via.get(f, "MEMORY.md")
            W(True, f"index-ghost:{f}", f"[유령 인덱스] {f} — {src}에 줄은 있는데 파일 없음")

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
                  f"[부패 후보] {f} — project형 {age}일 무갱신 (포인터화 검토)")

    # Detect recordings that stopped before the required reading output.
    rec_root = os.path.join(root, "_private", "recordings")
    if os.path.isdir(rec_root):
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
            W(False, "drive-inbox-unmounted",
              "[드라이브 인박스 없음] 구글 드라이브 데스크톱 동기화 확인 필요. "
              "python3 tools/drive_inbox.py --list")
        else:
            for _f, _fp, _st, _why in _rows:
                if _st != "완료":
                    W(True, "drive-inbox:" + _f,
                      "[인박스 미처리] {} — {}{}. python3 tools/drive_inbox.py".format(
                          _f, _st, " ({})".format(_why) if _why else ""))
    except _SkipCheck:
        pass
    except Exception as _e:  # noqa: BLE001
        W(False, "drive-inbox-error",
          "[드라이브 인박스 검사 실패] {}".format(_e))

    # Check NOW freshness.
    a = _age_days(M.NOW_PATH)
    if a is None:
        W(True, "now-absent", f"[NOW 부재] {M.NOW_PATH}")
    elif a > 3:
        W(False, "now-stale", f"[NOW 낡음] {a}일 전 (임계 3일)")
    elif _snapshot_stale("public", portable=portable):
        W(True, "now-input-newer", "[NOW 입력이 더 새로움] journal commit 뒤 snapshot publish 미완")

    # Use the previous month's journal during normal rollover; distinguish a recent prior journal from total absence.
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
            print(f"NOW.md 재생성 ({os.path.getsize(M.NOW_PATH)} bytes)")
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
    print(f"모르는 명령: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
