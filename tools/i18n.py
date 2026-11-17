#!/usr/bin/env python3
import json
import os
import sys


STRINGS = {
    # State path: journal, NOW snapshots, session injection, runtime adapters, hook installer, setup.
    "memlib.cfg_root": {
        "en": "config root is not an object",
        "ko": "config root가 object가 아님",
    },
    "memlib.cfg_container": {
        "en": "config.{key} is not a {type}",
        "ko": "config.{key}가 {type}가 아님",
    },
    "memlib.cfg_schema_int": {
        "en": "config.schema_version is not an int",
        "ko": "config.schema_version이 int가 아님",
    },
    "memlib.cfg_remote_list": {
        "en": "config.instance.remote_allowlist is not a list",
        "ko": "config.instance.remote_allowlist가 list가 아님",
    },
    "memlib.cfg_remote_invalid": {
        "en": "config.instance.remote_allowlist has an invalid host/remote",
        "ko": "config.instance.remote_allowlist에 유효하지 않은 host/remote가 있음",
    },
    "memlib.cfg_model_send": {
        "en": "config.egress.model_send is not an object",
        "ko": "config.egress.model_send가 object가 아님",
    },
    "memlib.cfg_prefix_list": {
        "en": "config.egress.model_send.{key} is not a list of safe relative path prefixes",
        "ko": "config.egress.model_send.{key}가 안전한 상대경로 prefix list가 아님",
    },
    "memlib.cfg_prefix_relationship": {
        "en": "config.egress.model_send.allow_prefixes relationship is unsafe: {errors}",
        "ko": "config.egress.model_send.allow_prefixes 관계가 안전하지 않음: {errors}",
    },
    "memlib.cfg_source_object": {
        "en": "config.episodic_sources[{i}] is not an object",
        "ko": "config.episodic_sources[{i}]가 object가 아님",
    },
    "memlib.cfg_source_empty": {
        "en": "config.episodic_sources[{i}].{key} is empty",
        "ko": "config.episodic_sources[{i}].{key}가 비어 있음",
    },
    "memlib.cfg_track_object": {
        "en": "config.tracks[{i}] is not an object",
        "ko": "config.tracks[{i}]가 object가 아님",
    },
    "memlib.cfg_track_empty": {
        "en": "config.tracks[{i}].{key} is empty",
        "ko": "config.tracks[{i}].{key}가 비어 있음",
    },
    "memlib.cfg_track_canonical": {
        "en": "config.tracks[{i}].canonical is not a safe relative path",
        "ko": "config.tracks[{i}].canonical이 안전한 상대경로가 아님",
    },
    "memlib.cfg_track_also": {
        "en": "config.tracks[{i}].also is not a list of strings",
        "ko": "config.tracks[{i}].also가 string list가 아님",
    },
    "memlib.cfg_thread_object": {
        "en": "config.threads[{i}] is not an object",
        "ko": "config.threads[{i}]가 object가 아님",
    },
    "memlib.cfg_thread_empty": {
        "en": "config.threads[{i}].{key} is empty",
        "ko": "config.threads[{i}].{key}가 비어 있음",
    },
    "memlib.cfg_thread_dossier": {
        "en": "config.threads[{i}].dossier is not a string or null",
        "ko": "config.threads[{i}].dossier가 string/null이 아님",
    },
    "memlib.cfg_thread_private": {
        "en": "config.threads[{i}] must not hold private metadata; move it to _private/state/threads.json",
        "ko": "config.threads[{i}] private metadata 금지 — _private/state/threads.json으로 이동",
    },
    "memlib.cfg_thread_visibility": {
        "en": "config.threads[{i}].visibility={visibility!r} is not supported",
        "ko": "config.threads[{i}].visibility={visibility!r} 미지원",
    },
    "memlib.cfg_public_tracks": {
        "en": "config.journal_visibility.public_tracks is not a list of non-empty strings",
        "ko": "config.journal_visibility.public_tracks가 non-empty string list가 아님",
    },
    "memlib.cfg_legacy_tracks": {
        "en": "config.journal_visibility.legacy_public_tracks is not a list of strings",
        "ko": "config.journal_visibility.legacy_public_tracks가 string list가 아님",
    },
    "memlib.cfg_cutoff_type": {
        "en": "config.journal_visibility.legacy_cutoff is not ISO8601 or null",
        "ko": "config.journal_visibility.legacy_cutoff가 ISO8601/null이 아님",
    },
    "memlib.cfg_cutoff_iso": {
        "en": "config.journal_visibility.legacy_cutoff is not ISO8601",
        "ko": "config.journal_visibility.legacy_cutoff가 ISO8601이 아님",
    },
    "memlib.cfg_cutoff_tz": {
        "en": "config.journal_visibility.legacy_cutoff has no timezone",
        "ko": "config.journal_visibility.legacy_cutoff에 timezone이 없음",
    },
    "memlib.cfg_legacy_missing": {
        "en": "schema v4 journal_visibility legacy fields missing",
        "ko": "schema v4 journal_visibility legacy fields 누락",
    },
    "memlib.cfg_legacy_null": {
        "en": "legacy_cutoff is null but legacy_public_tracks is not empty",
        "ko": "legacy_cutoff=null인데 legacy_public_tracks가 비어 있지 않음",
    },
    "memlib.cfg_journal_types": {
        "en": "config.journal_types is not a list of non-empty strings",
        "ko": "config.journal_types가 non-empty string list가 아님",
    },
    "memlib.cfg_personal_pointer": {
        "en": "config.personal_pointer is not a string or null",
        "ko": "config.personal_pointer가 string/null이 아님",
    },
    "memlib.cfg_threshold_int": {
        "en": "config.thresholds.{key} is not a non-negative int",
        "ko": "config.thresholds.{key}가 non-negative int가 아님",
    },
    "memlib.cfg_threshold_positive": {
        "en": "config.thresholds.{key} is not a positive int",
        "ko": "config.thresholds.{key}가 positive int가 아님",
    },
    "memlib.cfg_threshold_range": {
        "en": "config.thresholds.{key} is outside 1024..6000",
        "ko": "config.thresholds.{key}가 1024..6000 범위가 아님",
    },
    "memlib.line_format": {
        "en": "format mismatch: expected '- <ISO8601> [<track>/<type>] <text>'",
        "ko": "형식 불일치: '- <ISO8601> [<track>/<type>] <내용>' 이어야 함",
    },
    "memlib.line_type": {
        "en": "type '{type}' is not defined (allowed: {allowed})",
        "ko": "type '{type}' 미정의 (허용: {allowed})",
    },
    "memlib.line_too_long": {
        "en": "text exceeds 300 characters; a journal row records one event, not a document",
        "ko": "내용이 300자 초과 — journal은 한 줄 사건 기록이지 문서가 아님",
    },
    "memlib.journal_bom": {
        "en": "UTF-8 BOM is not allowed",
        "ko": "UTF-8 BOM 금지",
    },
    "memlib.journal_no_newline": {
        "en": "last line has no newline",
        "ko": "마지막 줄 개행 없음",
    },
    "memlib.journal_no_tz": {
        "en": "{path}:{lineno}: timestamp has no timezone",
        "ko": "{path}:{lineno}: timestamp timezone 없음",
    },
    "memlib.clip_marker": {
        "en": "[… middle cut: original {bytes} bytes …]",
        "ko": "[… 중간 절단: 원문 {bytes} bytes …]",
    },
    "memlib.journal_corrupt": {
        "en": "journal corrupt: {detail}",
        "ko": "journal 손상: {detail}",
    },
    "memlib.registry_not_list": {
        "en": "not a list",
        "ko": "list가 아님",
    },
    "memlib.schema_change_2": {
        "en": "new instance block: the ground truth for the data border.\n      \"instance\": {{\"name\": \"...\", \"context\": \"work|personal\", \"remote_allowlist\": []}}\n      without context the valve check assumes personal and ignores remotes",
        "ko": "instance 블록 신설 — 데이터 국경의 근거값.\n      \"instance\": {{\"name\": \"...\", \"context\": \"work|personal\", \"remote_allowlist\": []}}\n      context가 없으면 밸브 검사가 personal로 간주하고 원격을 안 본다",
    },
    "memlib.schema_change_3": {
        "en": "new journal_visibility: events outside the public allowlist fail closed to local-private.\n      \"journal_visibility\": {{\"public_tracks\": [\"system\", \"research\", ...]}}\n      private thread metadata lives in _private/state/threads.json, not in tracked threads[]",
        "ko": "journal_visibility 신설 — public allowlist 밖 사건은 local-private로 fail-close.\n      \"journal_visibility\": {{\"public_tracks\": [\"system\", \"research\", ...]}}\n      private thread metadata는 추적 threads[]가 아니라 _private/state/threads.json에 둔다",
    },
    "memlib.schema_change_4": {
        "en": "new legacy journal cutover: adding to the allowlist must not re-promote old private-derived bodies.\n      \"legacy_cutoff\": null|\"ISO8601\", \"legacy_public_tracks\": [...]\n      existing instances pin the migration time and the public_tracks of that moment",
        "ko": "legacy journal cutover 신설 — allowlist 추가가 과거 private-derived body를 재승격하지 않게 한다.\n      \"legacy_cutoff\": null|\"ISO8601\", \"legacy_public_tracks\": [...]\n      기존 인스턴스는 migration 시각과 그때의 public_tracks를 고정한다",
    },
    "now.visibility_config_missing": {
        "en": "config missing",
        "ko": "config 없음",
    },
    "now.visibility_config_invalid": {
        "en": "config load/validation failed",
        "ko": "config 로드/검증 실패",
    },
    "now.visibility_unavailable": {
        "en": "journal_visibility unavailable (config schema={config}, engine schema={engine})",
        "ko": "journal_visibility 사용 불가 (config schema={config}, engine schema={engine})",
    },
    "now.visibility_generic": {
        "en": "visibility config unavailable",
        "ko": "visibility config 사용 불가",
    },
    "now.visibility_fail_closed": {
        "en": "[state] privacy fail-close: {detail}; new events are recorded locally",
        "ko": "[state] privacy fail-close: {detail}; 새 사건은 local에 기록",
    },
    "now.journal_tail_missing_newline": {
        "en": "journal corrupt: {path} has no final newline; append refused until the tail is repaired",
        "ko": "journal 손상: {path} 끝 개행 없음 — tail을 수리하기 전 append 거부",
    },
    "now.journal_header": {
        "en": "Format: `- <ISO8601> [<track>/<type>] <text> (→ ref)*` · types are defined in `tools/memlib.py` · mark an entry written after the fact with `{retroactive}`",
        "ko": "형식: `- <ISO8601> [<track>/<type>] <내용> (→ ref)*` · type 정의는 `tools/memlib.py` · 소급 기입은 `{retroactive}` 표기",
    },
    "now.config_changed": {
        "en": "config changed while the command ran; retry in a new process",
        "ko": "config가 명령 실행 중 바뀜 — 새 프로세스로 재시도",
    },
    "now.input_changed": {
        "en": "{label} changed while the command ran; retry in a new process",
        "ko": "{label}가 명령 실행 중 바뀜 — 새 프로세스로 재시도",
    },
    "now.log_refused": {
        "en": "refused: {error}\n  line: {line}",
        "ko": "거부: {error}\n  줄: {line}",
    },
    "now.log_failed": {
        "en": "state record failed: {error_type}: {error}",
        "ko": "상태 기록 실패: {error_type}: {error}",
    },
    "now.log_local_not_rendered": {
        "en": "recorded in the local journal but could not refresh local NOW: public {error}",
        "ko": "local journal에 기록했지만 local NOW는 갱신하지 못함: public {error}",
    },
    "now.log_recorded": {
        "en": "recorded ({visibility}): {line}",
        "ko": "기록({visibility}): {line}",
    },
    "now.track_row": {
        "en": "- **{name}**: {snippet} (file {age}d ago{warn}), source `{rel}`",
        "ko": "- **{name}** — {snippet} (파일 {age}일 전{warn}) → `{rel}`",
    },
    "now.track_no_update_line": {
        "en": "(no update line)",
        "ko": "(갱신줄 없음)",
    },
    "now.personal_pointer": {
        "en": "canonical `{path}`",
        "ko": "정본 `{path}`",
    },
    "now.personal_pointer_unset": {
        "en": "canonical not set (config personal_pointer)",
        "ko": "정본 미지정 (config personal_pointer)",
    },
    "now.personal_row": {
        "en": "- **Personal**: {pointer} (personal area: contents are not shown in NOW)",
        "ko": "- **개인** — {pointer} (개인 영역: NOW에 내용 비표시)",
    },
    "now.thread_row": {
        "en": "- {name}: dossier `{dossier}`",
        "ko": "- {name} — 서류철 `{dossier}`",
    },
    "now.thread_row_unset": {
        "en": "- {name}: dossier **not set** (Phase 2)",
        "ko": "- {name} — 서류철 **미지정** (Phase 2)",
    },
    "now.threads_none": {
        "en": "(no threads registered; add them to threads in system/memory-config.json)",
        "ko": "(등록된 스레드 없음 — system/memory-config.json의 threads에 추가)",
    },
    "now.threads_file_missing": {
        "en": "  [file missing]",
        "ko": "  [파일 없음]",
    },
    "now.threads_dossier": {
        "en": "dossier: {dossier}{exists}",
        "ko": "서류철: {dossier}{exists}",
    },
    "now.threads_unset": {
        "en": "not set",
        "ko": "미지정",
    },
    "now.pointer_personal": {
        "en": "personal `{path}`",
        "ko": "개인 `{path}`",
    },
    "now.pointer_facts": {
        "en": "personal facts `python3 tools/rec.py find|hot`",
        "ko": "개인 사실 `python3 tools/rec.py find|hot`",
    },
    "now.pointer_decisions": {
        "en": "decision log `system/decisions.md`",
        "ko": "결정 기록 `system/decisions.md`",
    },
    "now.pointer_recall": {
        "en": "recall `python3 tools/recall.py find \"query\"`",
        "ko": "회상 `python3 tools/recall.py find \"질의\"`",
    },
    "now.no_tracks": {
        "en": "- (no tracks defined)",
        "ko": "- (트랙 미정의)",
    },
    "now.compaction_summary": {
        "en": "{marker} {count} times ({parts}) · last {last}{tail}",
        "ko": "{marker} {count}회 ({parts}) · 마지막 {last}{tail}",
    },
    "now.freshness_journal": {
        "en": "journal {age}d ago",
        "ko": "journal {age}일 전",
    },
    "now.public_notice": {
        "en": "{generated}{ts} · `python3 tools/now.py render`. **Do not edit by hand** (public projection).\nThis file is canonical only for shareable state. Local state is merged from the local private overlay.*",
        "ko": "{generated}{ts} · `python3 tools/now.py render` — **손 편집 금지** (public projection).\n공유 가능한 상태에 대해서만 이 파일이 정본이다. local 상태는 local private overlay와 합친다.*",
    },
    "now.freshness": {
        "en": "*Input freshness: {items}*",
        "ko": "*입력 신선도: {items}*",
    },
    "now.no_shared_threads": {
        "en": "- (no shared threads)",
        "ko": "- (공유 스레드 없음)",
    },
    "now.return_ritual": {
        "en": "*(Return ritual: when coming back to a deep thread, read its dossier first. PRD §3.3)*",
        "ko": "*(복귀 의식: 깊은 스레드로 돌아올 때 서류철부터 읽는다 — PRD §3.3)*",
    },
    "now.none": {
        "en": "- (none)",
        "ko": "- (없음)",
    },
    "now.private_degraded": {
        "en": "> [DEGRADED: local thread registry is incomplete. Repair it with doctor.]",
        "ko": "> [DEGRADED: local thread registry가 불완전하다. doctor로 수리 필요.]",
    },
    "now.private_notice": {
        "en": "{generated}{ts} · generated for `_private/state/` only.\nThis file alone does not replace public state. The view merged with `state/NOW.md` is the local canonical state.*",
        "ko": "{generated}{ts} · `_private/state/` 로컬 전용 생성물.\n이 파일만으로 public 상태를 대체하지 않는다. `state/NOW.md`와 합친 view가 local 정본이다.*",
    },
    "now.rollback_failed": {
        "en": "snapshot rollback failed ({detail}); cause={cause}",
        "ko": "snapshot rollback 실패 ({detail}); 원인={cause}",
    },
    "now.snapshot_input_changed": {
        "en": "snapshot input changed during {phase}: {scopes}",
        "ko": "snapshot input이 {phase} 중 바뀜: {scopes}",
    },
    "now.snapshot_marker_count": {
        "en": "snapshot must contain exactly one content marker",
        "ko": "snapshot content marker가 정확히 하나여야 함",
    },
    "now.snapshot_placeholder_count": {
        "en": "snapshot must contain exactly one content marker placeholder",
        "ko": "snapshot content marker placeholder가 정확히 하나여야 함",
    },
    "now.public_publish_frozen": {
        "en": "visibility config is not ready; public snapshot publish is frozen",
        "ko": "visibility config가 준비되지 않아 public snapshot publish를 동결",
    },
    "now.render_failed": {
        "en": "NOW render failed: {error_type}: {error}",
        "ko": "NOW render 실패: {error_type}: {error}",
    },
    "now.omitted_threads": {
        "en": "[{count} dossiers omitted · `python3 tools/now.py threads`]",
        "ko": "[서류철 {count}개 생략 · `python3 tools/now.py threads`]",
    },
    "now.omitted_events": {
        "en": "[… {count} older event lines omitted …]",
        "ko": "[… 더 오래된 사건 {count}줄 생략 …]",
    },
    "now.public_missing": {
        "en": "public NOW missing: {path}",
        "ko": "public NOW 부재: {path}",
    },
    "now.private_omitted": {
        "en": "[local private overlay omitted: this wiring injects public state only. Local state is unavailable, not absent]",
        "ko": "[local private overlay 생략 — 이 배선은 public 상태만 주입한다. local 상태는 unavailable이지 없음이 아니다]",
    },
    "now.private_corrupt": {
        "en": "[local private overlay unavailable/corrupt: only public state was injected. Do not assert that local state is absent before repairing it with doctor]",
        "ko": "[local private overlay unavailable/corrupt — public 상태만 주입됨. doctor로 수리하기 전 local 상태를 없음으로 단언하지 말 것]",
    },
    "now.private_unavailable": {
        "en": "[local private overlay unavailable: do not assert that it is absent]",
        "ko": "[local private overlay unavailable — 없음으로 단언하지 말 것]",
    },
    "now.injection_head": {
        "en": "[state injection · public {age}d ago · local overlay {status}]\nThe view that merges the public projection and the local overlay is canonical.",
        "ko": "[상태 자동 주입 · public {age}일 전 · local overlay {status}]\npublic projection과 local overlay를 합친 view가 정본이다.",
    },
    "now.injection_degraded": {
        "en": "[DEGRADED: visibility config unavailable · public snapshot frozen · new events go local]",
        "ko": "[DEGRADED: visibility config 불가 · public snapshot frozen · 새 사건은 local]",
    },
    "now.hook_budget_too_small": {
        "en": "now_hook_max_bytes is smaller than the fixed header",
        "ko": "now_hook_max_bytes가 고정 헤더보다 작다",
    },
    "now.hook_budget_error": {
        "en": "hook byte budget miscalculated",
        "ko": "hook byte budget 계산 오류",
    },
    "now.hook_context_failed": {
        "en": "hook-context failed: {error_type}: {error}",
        "ko": "hook-context 실패: {error_type}: {error}",
    },
    "now.context_failed": {
        "en": "context failed: {error_type}: {error}",
        "ko": "context 실패: {error_type}: {error}",
    },
    "now.check_warnings": {
        "en": "check: {count} warnings",
        "ko": "check: 경고 {count}건",
    },
    "now.check_clean": {
        "en": "check: clean",
        "ko": "check: 깨끗함",
    },
    "now.check_config_absent": {
        "en": "[NOW config missing] state inputs exist but system/memory-config.json does not",
        "ko": "[NOW config 부재] state 입력은 있지만 system/memory-config.json이 없음",
    },
    "now.check_not_applicable": {
        "en": "[NOW check not applicable] development tree before setup, with no config and no state inputs",
        "ko": "[NOW 검사 해당없음] config와 state 입력이 없는 설치 전 개발 트리",
    },
    "now.check_journal_corrupt": {
        "en": "[journal corrupt] {item}",
        "ko": "[journal 손상] {item}",
    },
    "now.check_now_absent": {
        "en": "[NOW missing] {path}",
        "ko": "[NOW 부재] {path}",
    },
    "now.check_now_input_newer_staged": {
        "en": "[NOW inputs are newer] staged journal and snapshot disagree",
        "ko": "[NOW 입력이 더 새로움] staged journal과 snapshot 불일치",
    },
    "now.check_canonical_stale": {
        "en": "[canonical behind] {rel} ({file_date}) < newest journal {track} event ({journal_date})",
        "ko": "[정본 낙후] {rel} ({file_date}) < journal {track} 최신 사건 ({journal_date})",
    },
    "now.check_index_volatile": {
        "en": "[volatile index] MEMORY.md:{line_no} {line}",
        "ko": "[인덱스 휘발성] MEMORY.md:{line_no} {line}",
    },
    "now.check_subindex_unreadable": {
        "en": "[sub-index unreadable] {name}: {error}",
        "ko": "[하위 색인 읽기 실패] {name}: {error}",
    },
    "now.check_index_missing": {
        "en": "[index missing] {name}: the file exists but no index line points to it",
        "ko": "[인덱스 누락] {name} — 파일은 있는데 인덱스 줄 없음",
    },
    "now.check_index_ghost": {
        "en": "[ghost index] {name}: {source} has a line but the file does not exist",
        "ko": "[유령 인덱스] {name} — {source}에 줄은 있는데 파일 없음",
    },
    "now.check_memory_rot": {
        "en": "[rot candidate] {name}: project memory not updated for {age}d (consider turning it into a pointer)",
        "ko": "[부패 후보] {name} — project형 {age}일 무갱신 (포인터화 검토)",
    },
    "now.check_recording_gaps": {
        "en": "[recording gaps unrecovered] {name}: {count} candidates. python3 tools/regap.py _private/recordings/{name}",
        "ko": "[녹취 결손 미복구] {name} — 후보 {count}건. python3 tools/regap.py _private/recordings/{name}",
    },
    "now.check_recording_unread": {
        "en": "[recording not read] {name}: a transcript exists but no line-by-line reading. python3 tools/analyze_recording.py _private/recordings/{name}",
        "ko": "[녹취 정독 미완] {name} — 전사만 있고 정독이 없다. python3 tools/analyze_recording.py _private/recordings/{name}",
    },
    "now.check_inbox_unmounted": {
        "en": "[drive inbox missing] check Google Drive desktop sync. python3 tools/drive_inbox.py --list",
        "ko": "[드라이브 인박스 없음] 구글 드라이브 데스크톱 동기화 확인 필요. python3 tools/drive_inbox.py --list",
    },
    "now.check_inbox_pending": {
        "en": "[inbox unprocessed] {name}: {status}{reason}. python3 tools/drive_inbox.py",
        "ko": "[인박스 미처리] {name} — {status}{reason}. python3 tools/drive_inbox.py",
    },
    "now.check_inbox_failed": {
        "en": "[drive inbox check failed] {error}",
        "ko": "[드라이브 인박스 검사 실패] {error}",
    },
    "now.check_now_stale": {
        "en": "[NOW stale] {age}d old (threshold 3d)",
        "ko": "[NOW 낡음] {age}일 전 (임계 3일)",
    },
    "now.check_now_input_newer": {
        "en": "[NOW inputs are newer] snapshot not yet published after a journal commit",
        "ko": "[NOW 입력이 더 새로움] journal commit 뒤 snapshot publish 미완",
    },
    "now.check_journal_rollover": {
        "en": "[journal month rollover] {name} does not exist yet (the previous one is {age}d old)",
        "ko": "[journal 월 전환] {name} 아직 없음 (직전 것이 {age}일 전)",
    },
    "now.check_journal_absent": {
        "en": "[journal missing] {path}",
        "ko": "[journal 부재] {path}",
    },
    "now.check_journal_stale": {
        "en": "[journal stale] {age}d old (threshold {threshold}d)",
        "ko": "[journal 낡음] {age}일 전 (임계 {threshold}일)",
    },
    "now.render_done": {
        "en": "NOW.md regenerated ({bytes} bytes)",
        "ko": "NOW.md 재생성 ({bytes} bytes)",
    },
    "now.unknown_command": {
        "en": "unknown command: {command}\n{doc}",
        "ko": "모르는 명령: {command}\n{doc}",
    },
    "harness.command_now": {
        "en": "Read and summarize canonical state (public NOW + local overlay)",
        "ko": "상태 정본(public NOW + local overlay)을 읽고 요약한다",
    },
    "harness.command_recall": {
        "en": "Recall the original text of past conversations",
        "ko": "과거 대화 원문을 회상한다",
    },
    "harness.command_dossier": {
        "en": "Return ritual: read the dossier of a deep thread",
        "ko": "깊은 스레드의 서류철을 읽는 복귀 의식",
    },
    "harness.command_handoff": {
        "en": "Hand the current work over to another session or runtime with a note on disk",
        "ko": "하던 일을 넘김 메모와 함께 다른 세션이나 런타임에 넘긴다",
    },
    "harness.command_garden": {
        "en": "Run the gardener pass (report-only)",
        "ko": "정원사 패스(report-only)를 돌린다",
    },
    "harness.generated_banner": {
        "en": "<!-- generated by tools/harness.py; do not edit by hand -->",
        "ko": "<!-- generated by tools/harness.py — 손으로 고치지 말 것 -->",
    },
    "harness.gap_claude": {
        "en": "guard (PreToolUse) is left to the instance",
        "ko": "guard(PreToolUse)는 인스턴스 재량이다",
    },
    "harness.gap_codex": {
        "en": "recovery, observer, and enforcer are not wired: Codex has no hook surface for them (doctor reports WARN)",
        "ko": "recovery·observer·enforcer는 Codex 훅 표면이 없어 미배선 (doctor가 WARN)",
    },
    "harness.gap_opencode": {
        "en": "the injector works only through the launcher (`harness.py open opencode`); a session started directly gets no state. recovery, observer, enforcer, side_effect, and guard need the v2 plugin API, whose signatures are not fixed yet; not wired",
        "ko": "injector는 런처(`harness.py open opencode`) 경로에서만 선다 — 직접 띄운 세션엔 상태가 안 들어간다. recovery·observer·enforcer·side_effect·guard는 v2 플러그인 API가 필요하고 시그니처가 아직 고정되지 않았다 — 미배선",
    },
    "harness.state_failed": {
        "en": "# Kit state injection failed\n\n`tools/now.py context` failed: {detail}\nRun `python3 tools/doctor.py`; until fixed, read `state/NOW.md` directly, together with `_private/state/NOW.md` when it exists. A missing local overlay means unavailable, not no state.\n",
        "ko": "# 킷 상태 주입 실패\n\n`tools/now.py context`가 실패했다: {detail}\n`python3 tools/doctor.py`로 진단하고, 그동안은 `state/NOW.md`와 존재할 때 `_private/state/NOW.md`를 직접 읽어라. local overlay 부재는 unavailable이지 상태 없음이 아니다.\n",
    },
    "harness.install_title": {
        "en": "opencode wiring: {root}",
        "ko": "opencode 배선: {root}",
    },
    "harness.install_unchanged": {
        "en": "  (no change; already current)",
        "ko": "  (변경 없음 — 이미 최신)",
    },
    "harness.install_public_only": {
        "en": "  ⚠ The state file is not proven to be outside Git, so only **public state** is injected (fail-close).\n    To also inject the private overlay, add `{line}` to .gitignore.",
        "ko": "  ⚠ 상태 파일이 Git 밖이라고 보증되지 않아 **public 상태만** 주입한다 (fail-close).\n    개인 overlay까지 주입하려면 .gitignore에 `{line}`를 넣어라.",
    },
    "harness.install_outside_git": {
        "en": "  The state file is outside Git: public + local overlay are injected.",
        "ko": "  상태 파일은 Git 밖이다 — public + local overlay 주입.",
    },
    "harness.install_unverified": {
        "en": "  Unverified: slash command registration. v2 introspection does not open the project scope, so it could not be checked.\n    Check that `/now` appears in a session; if it does not, this line is open work.",
        "ko": "  미확인: 슬래시 명령 등록 — v2 introspection이 프로젝트 범위로 안 열려 확인 못 했다.\n    세션에서 `/now`가 보이는지 확인하고, 안 보이면 이 줄이 미결 작업이다.",
    },
    "harness.install_next": {
        "en": "  Next: python3 tools/harness.py open opencode   (seed the state and launch)\n        python3 tools/harness.py verify opencode  (measure whether the injection reaches the model)",
        "ko": "  다음: python3 tools/harness.py open opencode   (상태를 심고 띄운다)\n        python3 tools/harness.py verify opencode  (그 주입이 모델에 닿는지 실측)",
    },
    "harness.gitignore_comment": {
        "en": "# Generated for opencode session injection; it can hold the local overlay, so it stays outside Git (harness.py)",
        "ko": "# opencode 세션 주입용 생성물 — local overlay를 담을 수 있어 Git 밖에 둔다 (harness.py)",
    },
    "harness.status_instance": {
        "en": "instance: {root}",
        "ko": "인스턴스: {root}",
    },
    "harness.state_wired": {
        "en": "wired",
        "ko": "배선됨",
    },
    "harness.state_stale": {
        "en": "wiring stale",
        "ko": "배선 낡음",
    },
    "harness.state_partial": {
        "en": "partly wired",
        "ko": "반쪽 배선",
    },
    "harness.state_unwired": {
        "en": "not wired",
        "ko": "미배선",
    },
    "harness.state_not_installed": {
        "en": "not installed",
        "ko": "미설치",
    },
    "harness.status_roles": {
        "en": "roles {covered}/{total}  ({mode})",
        "ko": "역할 {covered}/{total}  ({mode})",
    },
    "harness.scope_outside_git": {
        "en": "outside Git; public + local overlay injected",
        "ko": "Git 밖 — public + local overlay 주입",
    },
    "harness.scope_unproven": {
        "en": "not proven outside Git; public state only (fail-close)",
        "ko": "Git 밖 미증명 — public 상태만 주입 (fail-close)",
    },
    "harness.status_state_file": {
        "en": "       state file: {scope}",
        "ko": "       상태 파일: {scope}",
    },
    "harness.wiring_missing": {
        "en": "wiring files are missing from the repository: {items}",
        "ko": "배선 파일이 레포에 없다: {items}",
    },
    "harness.install_checked_in": {
        "en": "{runtime}: wiring is checked into the repository (not generated).",
        "ko": "{runtime}: 배선은 레포에 체크인돼 있다 (생성 대상 아님).",
    },
    "harness.check_unwired": {
        "en": "-- opencode not wired (nothing to check)",
        "ko": "-- opencode 미배선 (검사 대상 없음)",
    },
    "harness.check_pass": {
        "en": "PASS opencode generated-file parity",
        "ko": "PASS opencode 생성물 parity",
    },
    "harness.scope_public_only": {
        "en": "public only",
        "ko": "public만",
    },
    "harness.refresh_done": {
        "en": "state regenerated: {path} ({bytes} bytes, {scope})",
        "ko": "상태 재생성: {path} ({bytes} bytes, {scope})",
    },
    "harness.canary_timeout": {
        "en": "no answer within {seconds}s",
        "ko": "{seconds}s 안에 응답 없음",
    },
    "harness.canary_tools": {
        "en": "tools used: {tools}",
        "ko": "도구 사용: {tools}",
    },
    "harness.canary_no_tools": {
        "en": "no tools used",
        "ko": "도구 사용 0",
    },
    "harness.canary_empty": {
        "en": "(empty answer)",
        "ko": "(빈 응답)",
    },
    "harness.verify_other_runtime": {
        "en": "the {runtime} canary is handled by tools/hook_canary.py.",
        "ko": "{runtime} 카나리는 tools/hook_canary.py가 담당한다.",
    },
    "harness.verify_no_opencode": {
        "en": "opencode is not installed. Install it and run again.",
        "ko": "opencode가 없다. 설치 후 다시 실행해라.",
    },
    "harness.verify_no_models": {
        "en": "no model is available. Run `opencode auth login` first.",
        "ko": "부를 수 있는 모델이 없다. `opencode auth login` 먼저.",
    },
    "harness.verify_summary": {
        "en": "{passed}/{total} models received the kit state · ledger {ledger}",
        "ko": "{passed}/{total} 모델이 킷 상태를 받았다 · 원장 {ledger}",
    },
    "harness.verify_none_passed": {
        "en": "  If every result is inconclusive or refused, the cause may be the model or tier, not the injection.",
        "ko": "  판정 불가·거부가 전부면 주입이 아니라 모델·티어 문제일 수 있다.",
    },
    "harness.seed_prompt": {
        "en": "Below is the current state the kit placed in this session. Where it conflicts with the conversation, this is canonical.\nBase your answers on this text, not on summaries or memory.",
        "ko": "아래는 킷이 이 세션에 심은 현재 상태다. 대화 맥락과 충돌하면 이것이 정본이다.\n요약·기억이 아니라 이 본문을 근거로 삼아라.",
    },
    "harness.open_missing": {
        "en": "{runtime} is not on PATH.",
        "ko": "{runtime}가 PATH에 없다.",
    },
    "harness.help_description": {
        "en": "Single entry point for harness wiring",
        "ko": "하네스 배선의 단일 진입점",
    },
    "harness.help_status": {
        "en": "installation, wiring, and role coverage",
        "ko": "설치·배선·역할 커버리지",
    },
    "harness.help_install": {
        "en": "install wiring into this instance",
        "ko": "이 인스턴스에 배선을 깐다",
    },
    "harness.help_check": {
        "en": "generated-file parity (no model call)",
        "ko": "생성물 parity (모델 호출 없음)",
    },
    "harness.help_refresh": {
        "en": "regenerate the injected state file",
        "ko": "주입용 상태 파일 재생성",
    },
    "harness.help_verify": {
        "en": "measure the canary round trip",
        "ko": "카나리 왕복 실측",
    },
    "harness.help_sweep": {
        "en": "measure every available model",
        "ko": "부를 수 있는 모델을 전부 잰다",
    },
    "harness.help_open": {
        "en": "bake the state and launch the harness",
        "ko": "상태를 굽고 하네스를 띄운다",
    },
    "install_hooks.status_current": {
        "en": "current: {target}",
        "ko": "현재(current): {target}",
    },
    "install_hooks.status_missing": {
        "en": "missing: {target}",
        "ko": "없음(missing): {target}",
    },
    "install_hooks.status_owned_drift": {
        "en": "owned-drift: {target}",
        "ko": "소유 표류(owned-drift): {target}",
    },
    "install_hooks.status_foreign": {
        "en": "foreign: {target}",
        "ko": "외부 훅(foreign): {target}",
    },
    "install_hooks.current_pair": {
        "en": "current: {hook} + {push_hook}",
        "ko": "현재(current): {hook} + {push_hook}",
    },
    "install_hooks.template_sha": {
        "en": "template sha256: {sha}",
        "ko": "템플릿 sha256: {sha}",
    },
    "install_hooks.installed_sha": {
        "en": "installed sha256: {sha}",
        "ko": "설치본 sha256: {sha}",
    },
    "install_hooks.foreign_refused": {
        "en": "refusing to overwrite a foreign pre-commit/pre-push: {hook} ({status}), {push_hook} ({push_status})",
        "ko": "foreign pre-commit/pre-push를 덮어쓰지 않는다: {hook} ({status}), {push_hook} ({push_status})",
    },
    "install_hooks.repair_failed": {
        "en": "repair verification failed, restored: {hook}",
        "ko": "repair 검증 실패, 원상 복구: {hook}",
    },
    "install_hooks.seal_failed": {
        "en": "baseline seal failed, hook restored",
        "ko": "baseline seal 실패, hook 원상 복구",
    },
    "install_hooks.probe_failed": {
        "en": "git dispatcher probe failed, restored: {hook}",
        "ko": "git dispatcher probe 실패, 원상 복구: {hook}",
    },
    "install_hooks.repaired": {
        "en": "current: {hook} + {push_hook} (exact template + executable + direct hook probe + sealed baseline)",
        "ko": "현재(current): {hook} + {push_hook} (정확한 템플릿 + 실행 가능 + 직접 훅 검사 + 봉인된 기준선)",
    },
    "install_hooks.backup": {
        "en": "backup: {path}",
        "ko": "백업(backup): {path}",
    },
    "setup.journal_initialized": {
        "en": "instance set up: {name} ({context}), initialized after cloning the kit",
        "ko": "인스턴스 세팅: {name} ({context}) — 킷 클론 후 초기화",
    },
    "setup.journal_local_initialized": {
        "en": "local overlay initialized by setup ({name})",
        "ko": "local overlay 초기화 — setup ({name})",
    },
    "doctor.check_crashed": {
        "en": "check crashed: {error_type}: {error}",
        "ko": "검사 자체가 터짐: {error_type}: {error}",
    },
    "doctor.python_old": {"en": " (3.8+ required)", "ko": " (3.8+ 필요)"},
    "doctor.node_missing": {
        "en": "node missing; only the gardener (wf_gardener.js) is unavailable",
        "ko": "node 없음 — 정원사(wf_gardener.js)만 못 쓴다",
    },
    "doctor.codex_missing": {
        "en": "codex CLI missing; ask_codex.sh unavailable. Check permissions/installation",
        "ko": "codex CLI 없음 — 티키타카(ask_codex.sh) 불가. 권한/설치 확인",
    },
    "worker.private_ref_refused": {
        "en": "model-send deny ref refused: {refs}. The check reads prompt text, not intent. "
              "If you wrote the path to forbid it, remove the path and say it in words, "
              "for example \"do not open the private folder\".",
        "ko": "model-send deny ref를 거부했다: {refs}. 이 검사는 뜻이 아니라 프롬프트 글자를 본다. "
              "금지하려고 경로를 적었다면 경로 글자를 빼고 \"개인 폴더를 열지 마라\"처럼 말로 적어라.",
    },
    "hookdiag.codex_missing": {"en": "codex CLI missing", "ko": "codex CLI 없음"},
    "hookdiag.initialize_failed": {
        "en": "codex initialize failed: {error}",
        "ko": "codex initialize 실패: {error}",
    },
    "hookdiag.list_failed": {
        "en": "hooks/list failed: {error}",
        "ko": "hooks/list 실패: {error}",
    },
    "hookdiag.list_empty": {
        "en": "hooks/list returned empty data",
        "ko": "hooks/list가 빈 data를 반환",
    },
    "hook_canary.not_armed": {
        "en": "canary stopped: SessionStart is not armed ({injector})",
        "ko": "canary 중단: SessionStart armed가 아님 ({injector})",
    },
    "hook_canary.process_failed": {
        "en": "{kind} process failed: {error}",
        "ko": "{kind} process 실패: {error}",
    },
    "hook_canary.runtime_failed": {
        "en": "{runtime} canary failed: {error_type}: {error}",
        "ko": "{runtime} canary 실패: {error_type}: {error}",
    },
    "hook_canary.persist_failed": {
        "en": "failed to save canary results: {error_type}: {error}",
        "ko": "canary 결과 저장 실패: {error_type}: {error}",
    },
    "codex_root.dispatch_prefix": {
        "en": "[Claude Code requested ",
        "ko": "[Claude Code가 ",
    },
    "hook.sessionstart_failed": {
        "en": "[kit] State injection failed (now.py is missing or errored). Run `python3 tools/doctor.py`; until fixed, read state/NOW.md together with _private/state/NOW.md when it exists. A missing local overlay means unavailable, not no state.",
        "ko": "[kit] 상태 자동 주입이 실패했다 (now.py 없음 또는 오류). `python3 tools/doctor.py`로 진단하고, 그동안은 state/NOW.md와 존재할 때 _private/state/NOW.md를 함께 읽어라. local overlay 부재는 unavailable이지 상태 없음이 아니다.",
    },
    "hook.precompact_failed": {
        "en": "precompact hook failed",
        "ko": "precompact 훅 실패",
    },
    "doctor.claude_missing": {
        "en": "claude CLI missing; headless verification (claude -p) unavailable",
        "ko": "claude CLI 없음 — 헤드리스 검증(claude -p) 불가",
    },
    "doctor.not_git": {
        "en": "not a git repository; linkcheck cannot count tracked files",
        "ko": "git 저장소가 아니다 — linkcheck가 추적 파일을 못 센다",
    },
    "doctor.git_unreadable": {
        "en": "{root} · could not read git version ({version!r}); verify that it is 2.5+",
        "ko": "{root} · git 버전을 못 읽음 ({version!r}) — 2.5 이상인지 직접 확인",
    },
    "doctor.git_old": {
        "en": "{root} · {version}; below 2.5: `rev-parse --git-path` is unavailable. Upgrade git",
        "ko": "{root} · {version} — 2.5 미만: `rev-parse --git-path`를 지원하지 않는다. git을 올려라",
    },
    "doctor.root_mismatch": {
        "en": "ROOT mismatch: memlib={memlib} vs actual={actual}",
        "ko": "ROOT 불일치: memlib={memlib} vs 실제={actual}",
    },
    "doctor.config_missing": {
        "en": "missing: {path}; run `bash setup.sh` or copy from templates/",
        "ko": "없음: {path} — `bash setup.sh` 또는 templates/에서 복사",
    },
    "doctor.config_changeme": {
        "en": "CHANGEME remains; the instance name/tracks have not been filled in",
        "ko": "CHANGEME가 남아 있다 — 인스턴스 이름·트랙을 아직 안 채웠다",
    },
    "doctor.config_counts": {
        "en": "tracks {tracks} · threads {threads} · sources {sources}",
        "ko": "트랙 {tracks}개 · 스레드 {threads}개 · 소스 {sources}개",
    },
    "doctor.config_warn_missing": {"en": "config missing: {path}", "ko": "config 없음: {path}"},
    "doctor.config_warn_load": {"en": "config load/validation failed: {error_type}", "ko": "config 로드/검증 실패: {error_type}"},
    "doctor.config_warn_visibility": {
        "en": "journal_visibility unavailable; all new events fail closed to _private/state (config schema={config}, engine schema={engine})",
        "ko": "journal_visibility 사용 불가 — 새 사건은 전부 _private/state로 fail-close (config schema={config}, engine schema={engine})",
    },
    "doctor.config_warn_tracks": {"en": "tracks undefined; the NOW dashboard will be empty", "ko": "tracks 미정의 — NOW 온도판이 빈다"},
    "doctor.config_warn_private": {
        "en": "private thread registry[{index}] {problem}; skipped",
        "ko": "private thread registry[{index}] {problem} — skip",
    },
    "doctor.config_warn_problem_object": {"en": "is not an object", "ko": "object 아님"},
    "doctor.config_warn_problem_key": {"en": "has invalid key/name", "ko": "key/name invalid"},
    "doctor.config_warn_problem_dossier": {"en": "has an invalid dossier", "ko": "dossier invalid"},
    "doctor.config_warn_problem_collision": {"en": "collides with a public key", "ko": "public key collision"},
    "doctor.config_warn_problem_duplicate": {"en": "has a duplicate key", "ko": "duplicate key"},
    "doctor.config_warn_private_parse": {
        "en": "private thread registry parse failed",
        "ko": "private thread registry 파싱 실패",
    },
    "doctor.config_warn_unknown": {"en": "unclassified config warning", "ko": "분류되지 않은 config 경고"},
    "doctor.hook_role_injector": {"en": "injection", "ko": "주입"},
    "doctor.hook_role_side_effect": {"en": "compaction record", "ko": "컴팩션 기록"},
    "doctor.hook_role_guard": {"en": "pre-tool guard", "ko": "사전 가드"},
    "doctor.hook_role_observer": {"en": "change observer", "ko": "변경 관측"},
    "doctor.hook_role_enforcer": {"en": "Stop block", "ko": "Stop 차단"},
    "doctor.hook_role_recovery": {"en": "recovery", "ko": "복구"},
    "doctor.transcripts_fresh": {
        "en": "missing: {path}\n      No Claude Code session has run in this directory yet (normal for a new install). Check again after the first session",
        "ko": "없음: {path}\n      이 디렉토리에서 Claude Code 세션을 아직 안 돌렸다 (신규 설치면 정상). 첫 세션 뒤 다시 확인해라",
    },
    "doctor.transcripts_stale": {
        "en": "missing: {path}\n      journals exist but transcripts do not; the path-mangling rule does not match this path",
        "ko": "없음: {path}\n      journal은 쌓였는데 전사가 없다 — 경로 맹글링 규칙이 이 경로에 안 맞는다",
    },
    "doctor.transcript_sessions": {
        "en": "{path} · sessions {count}",
        "ko": "{path} · 세션 {count}개",
    },
    "doctor.missing": {"en": "missing: {path}", "ko": "없음: {path}"},
    "doctor.not_writable": {"en": "not writable: {path}", "ko": "쓰기 불가: {path}"},
    "doctor.journal_damaged": {
        "en": "journal damage {count}; first item: {first}",
        "ko": "journal 손상 {count}건 · 첫 항목: {first}",
    },
    "doctor.journal_state": {
        "en": "journal {state} · entries {count}",
        "ko": "journal {state} · 엔트리 {count}줄",
    },
    "doctor.journal_present": {"en": "present", "ko": "있음"},
    "doctor.journal_absent": {"en": "absent (created on first log)", "ko": "없음(첫 log에 생성)"},
    "doctor.now_missing": {
        "en": "NOW.md missing; create it with `python3 tools/now.py render`",
        "ko": "NOW.md 없음 — `python3 tools/now.py render`로 생성",
    },
    "doctor.now_size": {
        "en": "{size} UTF-8 bytes (limit {limit})",
        "ko": "{size} UTF-8 bytes (상한 {limit})",
    },
    "doctor.now_oversize": {
        "en": "{size} bytes > limit {limit}; render/budget contract violated",
        "ko": "{size} bytes > 상한 {limit} — render/예산 계약 위반",
    },
    "doctor.hook_file_missing": {
        "en": "{path} missing; hooks are not installed for this runtime",
        "ko": "{path} 없음 — 이 런타임은 훅 미설치",
    },
    "doctor.capability_missing": {
        "en": "required capability missing: {items}",
        "ko": "필수 capability 누락: {items}",
    },
    "doctor.command_invalid": {
        "en": "declared but command invalid: {items}",
        "ko": "선언됐지만 command invalid: {items}",
    },
    "doctor.absolute_path": {
        "en": "absolute path hard-coded; it will silently fail on another machine:\n      {items}",
        "ko": "절대경로 하드코딩 — 다른 머신에서 조용히 죽는다:\n      {items}",
    },
    "doctor.authority_missing": {
        "en": "SessionStart failure fallback does not state the public+local authority contract: {items}",
        "ko": "SessionStart 실패 fallback이 public+local 권위 계약을 못 말한다: {items}",
    },
    "doctor.pretool_dead": {
        "en": " · PreToolUse matcher has zero hits on Codex tool names",
        "ko": " · PreToolUse matcher가 Codex 도구명에 0-hit",
    },
    "doctor.codex_lifecycle_missing": {
        "en": " · repo gate lifecycle absent (backstop=pre-commit)",
        "ko": " · repo gate lifecycle 부재(후방선=pre-commit)",
    },
    "doctor.claude_lifecycle_missing": {
        "en": " · Claude gate lifecycle missing: {items}",
        "ko": " · Claude gate lifecycle 누락: {items}",
    },
    "doctor.hooks_list_failed": {
        "en": "hooks/list unavailable: {error_type}: {error}",
        "ko": "hooks/list 조회 불가: {error_type}: {error}",
    },
    "doctor.codex_unarmed": {
        "en": "\n      Start `codex` once in this directory and approve hook trust (CHECKLIST C). Until approval, state is not injected into Codex sessions",
        "ko": "\n      이 디렉토리에서 `codex`를 한 번 띄워 훅 신뢰를 승인해라 (CHECKLIST C). 승인 전엔 Codex 세션에 상태가 주입되지 않는다",
    },
    "doctor.guard_unreachable": {
        "en": " · guard armed but matcher-unreachable",
        "ko": " · guard armed지만 matcher-unreachable",
    },
    "doctor.codex_hook_missing": {"en": "Codex hook missing", "ko": "Codex 훅 없음"},
    "doctor.root_label": {"en": "root", "ko": "루트"},
    "doctor.subdir_label": {"en": "subdirectory", "ko": "서브디렉토리"},
    "doctor.outside_label": {"en": "outside repo", "ko": "리포 밖"},
    "doctor.invalid_json_at": {
        "en": "invalid JSON at {label}: {stdout!r}",
        "ko": "{label}에서 유효 JSON이 아니다: {stdout!r}",
    },
    "doctor.nonzero_at": {
        "en": "exit {code} at {label}; hooks must always exit 0",
        "ko": "{label}에서 exit {code} — 훅은 항상 0이어야 한다",
    },
    "doctor.failure_branch": {"en": "failure branch", "ko": "실패분기"},
    "doctor.chars": {"en": "{count} chars", "ko": "{count}자"},
    "doctor.injection_failed": {
        "en": "injection failed inside the instance: {details}",
        "ko": "인스턴스 안에서 주입 실패: {details}",
    },
    "doctor.outside_injected": {
        "en": "injected outside the repo; git-root fallback may select the wrong location",
        "ko": "리포 밖에서도 주입됐다 — git root 폴백이 엉뚱한 곳을 잡을 수 있다",
    },
    "doctor.codex_command_ok": {
        "en": "command-valid only · root/subdirectory JSON OK · dispatcher/fired/effect=unknown",
        "ko": "command-valid only · 루트/서브디렉토리 JSON OK · dispatcher/fired/effect=unknown",
    },
    "doctor.session_hook_missing": {"en": "SessionStart hook missing", "ko": "SessionStart 훅 없음"},
    "doctor.invalid_json": {
        "en": "invalid JSON: {error} · stdout[:120]={stdout!r}",
        "ko": "유효 JSON이 아니다: {error} · stdout[:120]={stdout!r}",
    },
    "doctor.pre_setup_failure": {
        "en": "failure branch verified only; setup has not run (config missing). Check again after `bash setup.sh`",
        "ko": "실패 분기 확인만 완료 — setup 전(config 없음). `bash setup.sh` 뒤 다시 본다",
    },
    "doctor.now_failed": {
        "en": "entered failure branch; now.py does not run{stderr}",
        "ko": "실패 분기로 떨어졌다 — now.py가 안 돈다{stderr}",
    },
    "doctor.failure_nonzero": {
        "en": "failure branch exited {code}; hooks must always exit 0 so sessions are not blocked",
        "ko": "실패 분기가 exit {code} — 훅은 항상 0이어야 세션을 안 막는다",
    },
    "doctor.failure_invalid_json": {
        "en": "failure branch is not valid JSON: {error}",
        "ko": "실패 분기가 유효 JSON이 아니다: {error}",
    },
    "doctor.failure_authority_missing": {
        "en": "failure branch authority guidance missing: {items}",
        "ko": "실패 분기의 권위 안내 누락: {items}",
    },
    "doctor.failure_warns_model": {
        "en": "warning is injected into the model on failure",
        "ko": "실패 시 모델에게 경고가 주입된다",
    },
    "doctor.global_missing": {
        "en": "global settings missing; current-time injection is disabled for each turn",
        "ko": "전역 설정 없음 — 턴마다 현재 시각 주입이 꺼져 있다",
    },
    "doctor.global_parse_failed": {
        "en": "global settings parse failed: {error}",
        "ko": "전역 설정 파싱 실패: {error}",
    },
    "doctor.time_hook_present": {"en": "time injection hook present", "ko": "시각 주입 훅 있음"},
    "doctor.time_hook_missing": {
        "en": "time injection hook missing; the model does not know 'today'. See the global-settings section of SETUP.md",
        "ko": "시각 주입 훅 없음 — 모델이 '오늘'을 모른다. SETUP.md의 전역 설정 절 참조",
    },
    "doctor.installer_missing": {"en": "installer missing", "ko": "installer 없음"},
    "doctor.repair_needed": {
        "en": "{detail} · run `bash tools/install_hooks.sh --repair`",
        "ko": "{detail} · `bash tools/install_hooks.sh --repair` 필요",
    },
    "doctor.commands_missing": {"en": "slash commands missing", "ko": "슬래시 커맨드 없음"},
    "doctor.trailer_missing": {
        "en": "{tool} trailer missing/not last: {last!r}",
        "ko": "{tool} 트레일러 없음/비말미: {last!r}",
    },
    "doctor.tools_ok": {
        "en": "now/linkcheck/coherence run OK (trailers verified)",
        "ko": "now/linkcheck/coherence 실행 OK (트레일러 확인)",
    },
    "doctor.checker_crashed": {
        "en": "checker crashed (exit={code}): {detail}",
        "ko": "검사기가 죽었다 (exit={code}): {detail}",
    },
    "doctor.linkcheck_unreadable": {
        "en": "could not read linkcheck output: {output!r}",
        "ko": "linkcheck 출력을 못 읽었다: {output!r}",
    },
    "doctor.links_ok": {"en": "references {refs} · broken 0", "ko": "참조 {refs}개 · 깨짐 0"},
    "doctor.more": {"en": "\n      ... {count} more", "ko": "\n      … 외 {count}개"},
    "doctor.links_broken": {
        "en": "broken references {count}:\n      {details}{more}",
        "ko": "깨진 참조 {count}개:\n      {details}{more}",
    },
    "doctor.coherence_ok": {"en": "coherence issues {count}", "ko": "정합성 이슈 {count}건"},
    "doctor.output_unreadable": {
        "en": "could not read output; its format changed or the tool is malfunctioning: {output!r}",
        "ko": "출력을 못 읽었다 — 형식이 바뀌었거나 도구가 이상하다: {output!r}",
    },
    "doctor.upstream_suites_missing": {
        "en": "upstream-only regression configuration missing: {items}",
        "ko": "상류 전용 회귀 구성 누락: {items}",
    },
    "doctor.kit_suites_missing": {
        "en": "distribution-kit regression configuration missing: {items}",
        "ko": "배포 킷 회귀 구성 누락: {items}",
    },
    "doctor.regression_failed": {
        "en": "regression failed:\n      {details}",
        "ko": "회귀 실패:\n      {details}",
    },
    "doctor.regression_ok": {
        "en": "{count} suites green: {items}",
        "ko": "suite {count}개 green: {items}",
    },
    "doctor.regression_release_only": {
        "en": "release/CI boundary only; interactive doctor skips regression suites",
        "ko": "release/CI 경계 전용; interactive doctor에서는 회귀 suite를 실행하지 않음",
    },
    "doctor.recall_ok": {"en": "source query OK ({count} lines)", "ko": "소스 조회 OK ({count}줄)"},
    "doctor.ledger_missing": {
        "en": "ledger not initialized (rec.py creates it on first record)",
        "ko": "원장 미개설 (rec.py는 첫 기록 때 만든다)",
    },
    "doctor.ledger_counts": {
        "en": "facts {facts} · consistency issues {issues}",
        "ko": "사실 {facts}건 · 정합성 문제 {issues}건",
    },
    "doctor.portrait_missing": {"en": "person ledger missing", "ko": "인물 원장 없음"},
    "doctor.portrait_undated": {
        "en": "ledger has no date; freshness cannot be measured",
        "ko": "원장에 날짜가 없어 신선도를 못 잰다",
    },
    "doctor.portrait_counts": {
        "en": "last {date} · unharvested decision-grade items {count} (threshold {threshold})",
        "ko": "마지막 {date} · 미수확 판정급 {count}건 (임계 {threshold})",
    },
    "doctor.egress_empty": {
        "en": "egress.model_send.deny_prefixes is empty; model sends are not classified",
        "ko": "egress.model_send.deny_prefixes가 비었다. 모델 전송 등급이 열려 있다",
    },
    "doctor.egress_invalid": {
        "en": "egress.model_send allow_prefixes validation failed",
        "ko": "egress.model_send allow_prefixes 검증에 실패했다",
    },
    "doctor.egress_config_invalid": {
        "en": "memory config validation failed; model-send policy is unavailable",
        "ko": "memory config 검증에 실패해 모델 전송 정책을 판정할 수 없다",
    },
    "doctor.egress_overlap": {
        "en": "egress.model_send allow_prefixes must strictly narrow deny_prefixes: {detail}",
        "ko": "egress.model_send allow_prefixes는 deny_prefixes보다 엄격히 깊어야 한다: {detail}",
    },
    "doctor.egress_ok": {
        "en": "model-send policy deny={deny} · allow={allow}",
        "ko": "모델 전송 정책 deny={deny} · allow={allow}",
    },
    "doctor.valve_skip": {
        "en": "context={context}; remote check skipped{extra}. Change context to work if handling company material",
        "ko": "context={context} — 원격 검사 안 함{extra}. 회사 자료를 다루면 context를 work로 바꿔라",
    },
    "doctor.remote_extra": {"en": " · {count} remotes present", "ko": " · 원격 {count}개 있음"},
    "doctor.no_remotes": {
        "en": "no remotes; there is no path for company material to leave",
        "ko": "원격 없음 — 회사 자료가 나갈 경로가 아예 없다",
    },
    "doctor.bad_remotes": {
        "en": "work instance has remotes outside the allowlist:\n      {items}\n      remove the remotes or add them to the allowlist",
        "ko": "work 인스턴스가 allowlist 밖 원격을 가졌다:\n      {items}\n      원격을 지우거나 allowlist에 넣어라",
    },
    "doctor.remotes_ok": {
        "en": "all {count} remotes are in the allowlist (by host)",
        "ko": "원격 {count}개 전부 allowlist 안 (host 기준)",
    },
    "doctor.symlinks_zero": {"en": "tracked symbolic links 0", "ko": "추적 심볼릭 링크 0"},
    "doctor.private_symlinks": {
        "en": "{count} tracked links point into _private; target path strings will reach the remote (contents will not; only structure and filenames):\n      {items}{more}",
        "ko": "_private을 가리키는 추적 링크 {count}개 — 대상 경로 문자열이 원격에 올라간다 (내용은 안 간다. 구조와 파일명만):\n      {items}{more}",
    },
    "doctor.symlink_cleanup": {
        "en": "\n      cleanup: git rm --cached <path> (the file remains on disk)",
        "ko": "\n      정리하려면: git rm --cached <경로> (파일은 디스크에 남는다)",
    },
    "doctor.symlinks_outside": {
        "en": "{count} tracked symbolic links (targets outside _private)",
        "ko": "추적 심볼릭 링크 {count}개 (대상이 _private 밖)",
    },
    "doctor.no_run_log": {
        "en": "no check execution log (instrument not running)",
        "ko": "검사 실행 기록 자체가 없다 (계기 미가동)",
    },
    "doctor.linkcheck_recorded": {
        "en": "linkcheck pass recorded for the current file state",
        "ko": "지금 파일 상태에서 linkcheck 통과 기록 있음",
    },
    "doctor.unverified_no_new": {
        "en": "current state is unverified (no new files); run `python3 tools/linkcheck.py`",
        "ko": "지금 상태는 미검증 (새 파일은 없다) — `python3 tools/linkcheck.py`",
    },
    "doctor.unverified_new": {
        "en": "{count} new files exist without a linkcheck record:\n      {items}\n      run `python3 tools/linkcheck.py`",
        "ko": "새 파일 {count}개가 있는 상태인데 linkcheck 기록이 없다:\n      {items}\n      `python3 tools/linkcheck.py`",
    },
    "doctor.claude_md_missing": {"en": "CLAUDE.md missing", "ko": "CLAUDE.md 없음"},
    "doctor.agents_md_missing": {
        "en": "AGENTS.md missing; neither runtime can read the single authority",
        "ko": "AGENTS.md 없음 — 두 런타임 모두 단일 정본을 못 읽는다",
    },
    "doctor.agents_ok": {
        "en": "AGENTS.md single-authority import ({bytes} bytes)",
        "ko": "AGENTS.md 단일 정본 import ({bytes} bytes)",
    },
    "doctor.agents_mismatch": {
        "en": "not a single authority (CLAUDE {claude} / AGENTS {agents} bytes); change CLAUDE.md to exact @AGENTS.md import",
        "ko": "단일 정본 아님 (CLAUDE {claude} / AGENTS {agents} bytes) — CLAUDE.md를 exact @AGENTS.md import로 고쳐라",
    },
    "doctor.schema_newer": {
        "en": "config schema v{config} > engine v{engine}; an old engine may ignore new privacy fields. Update the engine first",
        "ko": "config schema v{config} > 엔진 v{engine} — 옛 엔진이 새 privacy 필드를 무시할 수 있다. 엔진부터 갱신해라",
    },
    "doctor.schema_ok": {
        "en": "schema v{config} (engine expects v{engine})",
        "ko": "schema v{config} (엔진 기대 v{engine})",
    },
    "doctor.schema_old": {
        "en": "config schema v{config} < engine expects v{engine}; apply the following to config:\n      {todo}\n      then raise \"schema_version\" to {engine}",
        "ko": "config schema v{config} < 엔진 기대 v{engine} — 아래를 config에 반영해라:\n      {todo}\n      반영 후 \"schema_version\": {engine} 로 올린다",
    },
    "doctor.upstream_here": {
        "en": "this is upstream (kit_sync present); engine modifications are normal",
        "ko": "여기가 상류다 (kit_sync 보유) — 엔진 수정이 정상",
    },
    "doctor.engine_modified": {
        "en": "locally modified engine files; the next pull may conflict or revert them:\n      {items}",
        "ko": "로컬에서 수정된 엔진 파일 — 다음 pull에서 충돌하거나 되돌아간다:\n      {items}",
    },
    "doctor.upstream_behind": {
        "en": "{count} commits behind upstream; run `git pull` and doctor again",
        "ko": "업스트림보다 {count}커밋 뒤처짐 — `git pull` 후 doctor를 다시 돌려라",
    },
    "doctor.upstream_ok": {
        "en": "local engine modifications 0{status}",
        "ko": "엔진 로컬 수정 0{status}",
    },
    "doctor.upstream_sync": {"en": " · upstream synchronized", "ko": " · 업스트림 동기"},
    "doctor.upstream_unset": {"en": " · upstream not configured", "ko": " · 업스트림 미설정"},
    "doctor.kit_missing": {"en": "no kit copy to compare", "ko": "비교할 킷 사본 없음"},
    "doctor.kit_sync_missing": {"en": "kit_sync missing ({error})", "ko": "kit_sync 없음 ({error})"},
    "doctor.kit_diverged": {
        "en": "{different} of {shared} shared tools diverged: {items}\n      use `python3 tools/kit_sync.py` to inspect differences and `--apply` to export",
        "ko": "공유 {shared}개 중 {different}개 갈라짐: {items}\n      `python3 tools/kit_sync.py` 로 차이를 보고 `--apply`로 내보낸다",
    },
    "doctor.kit_same": {
        "en": "{count} shared tools match after export normalization ({kit})",
        "ko": "공유 도구 {count}개 내보내기 정규화 후 일치 ({kit})",
    },
    "doctor.personal_exposure": {
        "en": "context=personal; {count} exposed paths (tracking track documents is normal)",
        "ko": "context=personal — 노출 {count}개 (트랙 문서 추적은 정상)",
    },
    "doctor.untracked_exposure": {"en": "untracked exposure {count}", "ko": "untracked 노출 {count}개"},
    "doctor.ignore_misses": {
        "en": "paths not covered by ignore rules: {items}",
        "ko": "ignore 규칙이 안 잡는 경로: {items}",
    },
    "doctor.exposed_paths": {
        "en": "{count} untracked paths exposed; one commit could send them: {items}",
        "ko": "untracked 노출 {count}개 — 커밋 한 번이면 나간다: {items}",
    },
    "doctor.already_tracked": {"en": "already tracked: {items}", "ko": "이미 추적 중: {items}"},
    "doctor.ignore_ok": {
        "en": "all {count} probes ignored · untracked exposure 0",
        "ko": "probe {count}개 전부 ignore · untracked 노출 0",
    },
    "doctor.check.runtime_python": {"en": "runtime · python", "ko": "런타임 · python"},
    "doctor.check.runtime_node": {"en": "runtime · node", "ko": "런타임 · node"},
    "doctor.check.runtime_codex": {"en": "runtime · codex CLI", "ko": "런타임 · codex CLI"},
    "doctor.check.runtime_claude": {"en": "runtime · claude CLI", "ko": "런타임 · claude CLI"},
    "doctor.check.runtime_git": {"en": "runtime · git", "ko": "런타임 · git"},
    "doctor.check.wiring_root": {"en": "wiring · memlib ROOT", "ko": "배선 · memlib ROOT"},
    "doctor.check.wiring_config": {"en": "wiring · config", "ko": "배선 · config"},
    "doctor.check.wiring_transcripts": {"en": "wiring · transcript path", "ko": "배선 · 전사 경로 유도"},
    "doctor.check.wiring_state": {"en": "wiring · state/", "ko": "배선 · state/"},
    "doctor.check.wiring_now": {"en": "wiring · NOW.md", "ko": "배선 · NOW.md"},
    "doctor.check.hook_claude": {"en": "hooks · claude wiring", "ko": "훅 · 배선 claude"},
    "doctor.check.hook_codex": {"en": "hooks · codex wiring", "ko": "훅 · 배선 codex"},
    "doctor.check.hook_armed": {"en": "hooks · codex armed", "ko": "훅 · codex armed"},
    "doctor.check.hook_codex_command": {"en": "hooks · codex command validity", "ko": "훅 · codex 명령 유효성"},
    "doctor.check.hook_claude_command": {"en": "hooks · claude command validity", "ko": "훅 · claude 명령 유효성"},
    "doctor.check.hook_failure": {"en": "hooks · failure branch", "ko": "훅 · 실패 분기"},
    "doctor.check.hook_precompact_claude": {
        "en": "hooks · PreCompact claude", "ko": "훅 · PreCompact claude"
    },
    "doctor.check.hook_precompact_codex": {
        "en": "hooks · PreCompact codex", "ko": "훅 · PreCompact codex"
    },
    "doctor.check.hook_time": {"en": "hooks · claude global time", "ko": "훅 · claude 전역 시각"},
    "doctor.check.hook_precommit": {"en": "hooks · pre-commit installation", "ko": "훅 · pre-commit 설치본"},
    "doctor.check.hook_commands": {"en": "hooks · slash commands", "ko": "훅 · 슬래시 커맨드"},
    "doctor.check.tools_run": {"en": "tools · execution", "ko": "도구 · 실행"},
    "doctor.check.tools_links": {"en": "tools · link integrity", "ko": "도구 · 링크 무결성"},
    "doctor.check.tools_coherence": {"en": "tools · coherence", "ko": "도구 · 정합성"},
    "doctor.check.tools_regression": {"en": "tools · regression fixtures", "ko": "도구 · 회귀 픽스처"},
    "doctor.check.tools_receipts": {"en": "tools · worker receipts", "ko": "도구 · 워커 영수증"},
    "doctor.check.tools_recall": {"en": "tools · recall sources", "ko": "도구 · recall 소스"},
    "doctor.check.tools_ledger": {"en": "tools · ledger", "ko": "도구 · 원장"},
    "doctor.check.tools_context": {"en": "tools · fixed session context", "ko": "도구 · 세션 고정 컨텍스트"},
    "doctor.check.tools_portrait": {"en": "tools · person ledger", "ko": "도구 · 인물 원장"},
    "doctor.check.valve_egress": {"en": "valve · model send", "ko": "밸브 · 모델 전송"},
    "doctor.check.valve_remote": {"en": "valve · remote check", "ko": "밸브 · 원격 검사"},
    "doctor.check.valve_ignored": {"en": "valve · fuel untracked", "ko": "밸브 · 연료 비추적"},
    "doctor.check.valve_symlinks": {"en": "valve · tracked symlinks", "ko": "밸브 · 추적 심볼릭링크"},
    "doctor.check.gate_missed": {"en": "gate · output check omitted", "ko": "게이트 · 산출물 검사누락"},
    "doctor.check.agents": {"en": "rules · AGENTS single authority", "ko": "규약 · AGENTS 단일 정본"},
    "doctor.check.schema": {"en": "engine · config schema", "ko": "엔진 · config 스키마"},
    "doctor.check.upstream": {"en": "engine · upstream", "ko": "엔진 · 업스트림"},
    "doctor.check.drift": {"en": "engine · kit drift", "ko": "엔진 · 킷 드리프트"},
    "doctor.receipts_detail": {
        "en": "last 7 days runs={runs} · tokens={usage} · failures={failures} ({rate}%)",
        "ko": "최근 7일 runs={runs} · tokens={usage} · failures={failures} ({rate}%)",
    },
    "doctor.receipts_unreadable": {
        "en": " · unreadable={count}", "ko": " · 판독 불가={count}"
    },
    "doctor.precompact_missing": {
        "en": "{runtime} PreCompact command missing",
        "ko": "{runtime} PreCompact 명령 없음",
    },
    "doctor.precompact_multiple": {
        "en": "{runtime} has {count} PreCompact commands; exactly one is required to assert the effect",
        "ko": "{runtime} PreCompact 명령 {count}개 · 하나여야 효과를 단정할 수 있다",
    },
    "doctor.precompact_tools_missing": {
        "en": "simulation tools missing: {items}", "ko": "시뮬레이션 도구 누락: {items}"
    },
    "doctor.precompact_git_failed": {
        "en": "temporary git init failed: {detail}", "ko": "임시 git init 실패: {detail}"
    },
    "doctor.precompact_exit": {
        "en": "command exit={code}{detail}", "ko": "명령 exit={code}{detail}"
    },
    "doctor.precompact_no_effect": {
        "en": "command exited 0 but journal effect is missing · fallback={fallback}",
        "ko": "명령은 exit 0이나 journal 효과 없음 · fallback={fallback}",
    },
    "doctor.precompact_effect": {
        "en": "recorded '{marker}' in the temporary instance journal",
        "ko": "임시 인스턴스 journal에 '{marker}' 기록",
    },
    "doctor.precompact_marker": {
        "en": "[system/state] compaction occurred", "ko": "[system/state] 컴팩션 발생"
    },
    "doctor.manual.session_title": {
        "en": "Are the SessionStart dispatcher and model effect actually connected?",
        "ko": "SessionStart dispatcher와 모델 effect가 실제로 이어졌는가",
    },
    "doctor.manual.session_how": {
        "en": "routine doctor measures only declared/command-valid/armed. Only when explicitly spending the cost, run\n       python3 tools/hook_canary.py --all\n     Both runtimes must pass fresh positive and hooks-disabled negative cases to verify fired/effect.",
        "ko": "routine doctor는 declared/command-valid/armed까지만 잰다. 명시적으로 비용을 쓸 때만\n       python3 tools/hook_canary.py --all\n     양 런타임의 fresh positive와 hooks-disabled negative를 함께 통과해야 fired/effect를 검증한다.",
    },
    "doctor.manual.precompact_title": {
        "en": "Does the PreCompact hook actually run during compaction?",
        "ko": "PreCompact 훅이 컴팩션 때 실제로 도는가",
    },
    "doctor.manual.precompact_how": {
        "en": "The PreCompact command is verified; actual dispatcher firing remains unverified. After the next compaction, check whether a '[system/state] compaction occurred' line was appended to state/journal-*.md.",
        "ko": "PreCompact 명령은 검증됨, 실제 발화만 미확인이다. 다음 컴팩션 후 state/journal-*.md 끝에 '[system/state] 컴팩션 발생' 줄이 붙었는지 본다.",
    },
    "doctor.manual.codex_title": {
        "en": "Does Codex read AGENTS.md and follow its rules?",
        "ko": "Codex가 AGENTS.md를 읽고 규약을 따르는가",
    },
    "doctor.manual.codex_how": {
        "en": "After one dispatch, verify that the response follows the rules (user language, no em dash, verdict format).",
        "ko": "확인법: 발주 1회 후 응답이 규약(한국어·em-dash 금지·판정 형식)을 지키는지 본다.",
    },
    "doctor.manual.policy_title": {
        "en": "Does company policy allow these tools?",
        "ko": "회사 정책상 이 도구들을 써도 되는가",
    },
    "doctor.manual.policy_how": {
        "en": "Transcription/recording tools (tools/transcribe.py, etc.) may be subject to recording-consent and data-egress policy. Do not run them before checking company policy.",
        "ko": "전사·녹취(tools/transcribe.py 등)는 녹음 동의와 데이터 반출 정책에 걸릴 수 있다. 회사 규정을 확인하기 전에는 녹취 도구를 돌리지 마라.",
    },
    "doctor.heading": {"en": "doctor - {root}\n", "ko": "doctor — {root}\n"},
    "doctor.summary": {
        "en": "\nchecks {total} - ok {ok} · FAIL {fail} · warn {warn} · not applicable {skip}",
        "ko": "\n검사 {total}개 — ok {ok} · FAIL {fail} · warn {warn} · 해당없음 {skip}",
    },
    "doctor.manual_heading": {
        "en": "\n{count} checks cannot be automated (human verification required):",
        "ko": "\n자동 검사 불가 {count}개 (사람이 확인해야 한다):",
    },
    "doctor.finish_fail": {
        "en": "\nFix {count} FAIL items first. Until then, do not trust this instance's state automation.",
        "ko": "\nFAIL {count}개를 먼저 고쳐라. 그 전에는 이 인스턴스의 상태 자동화를 믿지 마라.",
    },
    "linkcheck.issue": {"en": "broken reference {rel} -> {target}", "ko": "깨진 참조 {rel} -> {target}"},
    "linkcheck.scope_all": {"en": "ALL (including frozen)", "ko": "ALL (동결 포함)"},
    "linkcheck.scope_live": {"en": "live documents (frozen excluded)", "ko": "라이브 문서 (동결 제외)"},
    "linkcheck.scope": {"en": "[linkcheck] scope={scope}, refs={count}", "ko": "[linkcheck] scope={scope}, refs={count}"},
    "linkcheck.broken": {"en": "BROKEN {rel} -> {target}", "ko": "BROKEN {rel} -> {target}"},
    "linkcheck.pending": {
        "en": "PENDING {rel} -> {target}  (created by setup.sh; upstream copy before setup)",
        "ko": "PENDING {rel} -> {target}  (setup.sh가 만든다 · setup 전 상류 사본)",
    },
    "linkcheck.optional": {
        "en": "OPTIONAL {rel} -> {target}  (ignored instance destination; created on first use)",
        "ko": "OPTIONAL {rel} -> {target}  (ignore된 인스턴스 목적지 · 처음 사용할 때 생성)",
    },
    "linkcheck.optional_count": {"en": "[linkcheck] optional(first use): {count}", "ko": "[linkcheck] optional(첫 사용): {count}"},
    "linkcheck.summary": {"en": "[linkcheck] broken: {count}", "ko": "[linkcheck] broken: {count}"},
    "linkcheck.pending_count": {"en": " · pending(before setup): {count}", "ko": " · pending(setup 전): {count}"},
    "gate.checker_dead": {
        "en": "Checkers produced no result: {items}. Unmeasurable is not a pass; determine what failed.",
        "ko": "검사기가 결과를 못 냈다: {items}. 측정 불능은 통과가 아니다 — 죽었는지 확인해라.",
    },
    "gate.baseline_corrupt": {
        "en": "Gate baseline is corrupt ({path}). Inspect it and run `python3 tools/gate.py baseline`.",
        "ko": "게이트 기준선이 깨졌다 ({path}). 확인하고 `python3 tools/gate.py baseline`.",
    },
    "gate.baseline_absent": {
        "en": "Gate baseline is absent. The machine cannot distinguish deletion from first installation, so it will not adopt automatically. Run `python3 tools/gate.py baseline` yourself.",
        "ko": "게이트 기준선이 없다. 지운 것과 처음 설치한 것을 기계가 구분할 수 없어서 자동으로 채택하지 않는다. `python3 tools/gate.py baseline`을 직접 돌려라.",
    },
    "gate.checks_changed": {
        "en": "Checker list differs from baseline; {only_base}{only_current}. This would allow bypass by deleting a checker. Explicitly migrate with `gate.py baseline`.",
        "ko": "검사기 목록이 기준선과 다르다 — {only_base}{only_current}. 검사기를 지워서 통과시키는 경로다. `gate.py baseline`으로 명시 이관해라.",
    },
    "gate.only_base": {"en": "baseline only: {items} ", "ko": "기준선에만: {items} "},
    "gate.only_current": {"en": "current only: {items}", "ko": "현재에만: {items}"},
    "gate.more": {"en": " {count} more", "ko": " 외 {count}건"},
    "gate.new_issues": {
        "en": "Issues absent before this turn appeared: {detail}. Fix them before finishing. If intentional, have the dispatcher run `gate.py approve-adoption --adopt <checker:issue-id> ...`, then run `python3 tools/gate.py baseline`.",
        "ko": "이번 턴에 없던 이슈가 생겼다: {detail}. 고치고 끝내라. 의도한 변화면 dispatcher가 `gate.py approve-adoption --adopt <checker:issue-id> ...`를 실행한 뒤 `python3 tools/gate.py baseline`.",
    },
    "gate.root_block": {
        "en": "Gate execution root differs from the tool location ({root} vs {tool}). Check whether MOTTORI_INSTANCE is set.",
        "ko": "게이트 실행 root가 도구 위치와 다르다 ({root} vs {tool}). MOTTORI_INSTANCE가 걸려 있는지 확인해라.",
    },
    "gate.lock_block": {
        "en": "Could not acquire the gate lock. Another check is running or the lock remains.",
        "ko": "게이트 잠금을 못 얻었다. 다른 검사가 도는 중이거나 잠금이 남았다.",
    },
    "gate.self_failed": {
        "en": "The gate itself failed ({error_type}). Repair the checker or inspect the cause with `python3 tools/gate.py status`.",
        "ko": "게이트 자신이 실패했다 ({error_type}). 검사기를 고치거나 `python3 tools/gate.py status`로 원인을 봐라.",
    },
    "gate.resume_failed": {
        "en": "[gate] The previous turn did not pass verification. {reason}",
        "ko": "[게이트] 지난 턴이 검증을 통과하지 못했다. {reason}",
    },
    "gate.resume_unknown": {
        "en": "The reason was not recorded; the next Stop rechecks it, or run `python3 tools/gate.py status`.",
        "ko": "이유가 기록되지 않았다. 다음 Stop이 다시 검사한다. 지금 보려면 `python3 tools/gate.py status`.",
    },
    "gate.resume_self_failed": {
        "en": "[gate] The gate itself failed ({error_type}). Verification status for the previous turn is unknown. Run `python3 tools/gate.py status`.",
        "ko": "[게이트] 게이트 자신이 실패했다 ({error_type}). 지난 턴의 검증 상태를 알 수 없다. `python3 tools/gate.py status`.",
    },
    "setup.name_missing": {"en": "--name requires a value", "ko": "--name 뒤에 값이 없다"},
    "setup.context_missing": {"en": "--context requires a value", "ko": "--context 뒤에 값이 없다"},
    "setup.unknown_arg": {"en": "unknown argument: {arg}", "ko": "모르는 인자: {arg}"},
    "setup.already": {"en": "already set up: {path}", "ko": "이미 세팅돼 있다: {path}"},
    "setup.again": {
        "en": "Use --force to run again. To inspect status, run python3 tools/doctor.py",
        "ko": "다시 하려면 --force. 상태를 확인하려면 python3 tools/doctor.py",
    },
    "setup.name_prompt": {"en": "Instance name [{name}]: ", "ko": "인스턴스 이름 [{name}]: "},
    "setup.name_default": {
        "en": "  (no tty) using default instance name: {name}  - change with --name <name>",
        "ko": "  (tty 없음) 인스턴스 이름 기본값 사용: {name}  — 바꾸려면 --name <이름>",
    },
    "setup.context_intro": {
        "en": "context is the basis of the data boundary.",
        "ko": "context는 데이터 국경의 근거값이다.",
    },
    "setup.context_work": {
        "en": "  work     company machine/company material. doctor blocks remote pushes",
        "ko": "  work     회사 머신·회사 자료. 원격 푸시를 doctor가 막는다",
    },
    "setup.context_personal": {
        "en": "  personal personal machine/personal material",
        "ko": "  personal 개인 머신·개인 자료",
    },
    "setup.context_prompt": {"en": "context [{context}]: ", "ko": "context [{context}]: "},
    "setup.context_default": {
        "en": "  (no tty) using default context: {context}  - use --context personal on a personal machine",
        "ko": "  (tty 없음) context 기본값 사용: {context}  — 개인 머신이면 --context personal",
    },
    "setup.context_invalid": {
        "en": "context must be work or personal (received: {context})",
        "ko": "context는 work 또는 personal이어야 한다 (받은 값: {context})",
    },
    "setup.legacy_type": {
        "en": "legacy journal type is absent from the new schema: {source}",
        "ko": "legacy journal type가 새 schema에 없음: {source}",
    },
    "setup.legacy_timezone": {
        "en": "legacy journal timezone missing: {source}",
        "ko": "legacy journal timezone 누락: {source}",
    },
    "setup.legacy_threads": {
        "en": "legacy threads[] lack public-decision evidence; manually separate public/local entries and run again",
        "ko": "legacy threads[]는 public 판정 증거가 없음; public/local 수동 분리 후 재실행 필요",
    },
    "setup.journal_newline": {
        "en": "journal does not end with a newline; nothing changed: {path}",
        "ko": "journal 마지막 줄이 개행으로 끝나지 않는다 — 아무것도 안 바꿨다: {path}",
    },
    "setup.preflight_failed": {
        "en": "existing journal preflight failed; nothing changed: {error}",
        "ko": "기존 journal preflight 실패 — 아무것도 안 바꿨다: {error}",
    },
    "setup.config_parse_failed": {
        "en": "     existing config parse failed; original will not be overwritten: {error}",
        "ko": "     기존 config 파싱 실패, 원본을 덮지 않는다: {error}",
    },
    "setup.schema_type": {
        "en": "existing schema_version is not an int",
        "ko": "기존 schema_version이 int가 아님",
    },
    "setup.schema_newer": {
        "en": "existing config v{old} is newer than this engine v{new}",
        "ko": "기존 config v{old}가 이 엔진 v{new}보다 새롭다",
    },
    "setup.config_written": {"en": "  {path}  ({name} / {context})", "ko": "  {path}  ({name} / {context})"},
    "setup.preserved": {
        "en": "     preserved: {tracks} tracks · {threads} threads · backup {path}.bak",
        "ko": "     보존: 트랙 {tracks}개 · 스레드 {threads}개 · 백업 {path}.bak",
    },
    "setup.origin_registered": {
        "en": "     origin registered automatically: {origin}",
        "ko": "     origin 자동 등록: {origin}",
    },
    "setup.work_remote_warning": {
        "en": "\n  Warning: this is a work instance with a remote.\n    {origin}\n  .gitignore prevents state/, _private/, and config from being tracked, so data cannot reach this remote.\n  However, engine code can be pushed. If code changed at work must not reach a personal repository,\n  clone again with pull-only credentials or remove the remote (CHECKLIST.md B).",
        "ko": "\n  주의: 이 인스턴스는 work인데 원격이 붙어 있다.\n    {origin}\n  .gitignore가 state/·_private/·config를 추적하지 않으므로 데이터는 이 원격으로 못 간다.\n  다만 **엔진 코드는 밀 수 있다.** 회사에서 고친 코드가 개인 저장소로 나가면 안 된다면\n  pull-only 자격증명으로 다시 클론하거나 원격을 지워라 (CHECKLIST.md B).",
    },
    "setup.rules_created": {
        "en": "  {path}  (still empty; fill in the boundary declaration)",
        "ko": "  {path}  (아직 비어 있다 — 국경 선언을 채워라)",
    },
    "setup.decisions_created": {
        "en": "  system/decisions.md  (instance DRs; kit design DRs are in system/kit-decisions.md)",
        "ko": "  system/decisions.md  (인스턴스 DR. 킷 설계 DR은 system/kit-decisions.md)",
    },
    "setup.rituals_created": {
        "en": "  system/rituals.local.md  (extension point for rituals.md; starts empty)",
        "ko": "  system/rituals.local.md  (rituals.md의 확장점. 빈 채로 시작)",
    },
    "setup.baseline_failed": {
        "en": "  gate baseline failed (rc={code}):",
        "ko": "  게이트 기준선 실패 (rc={code}):",
    },
    "setup.state_written": {
        "en": "  state/journal-{month}.md · state/NOW.md · _private/state/NOW.md",
        "ko": "  state/journal-{month}.md · state/NOW.md · _private/state/NOW.md",
    },
    "setup.verification": {"en": "verification:", "ko": "검증:"},
    "setup.remaining": {
        "en": "\nTwo items remain.\n  1. Declare the boundary in system/instance-rules.md\n  2. Open CHECKLIST.md and complete the human-verification items",
        "ko": "\n다음 둘이 남았다.\n  1. system/instance-rules.md 에 국경을 선언해라\n  2. CHECKLIST.md 를 열어 사람이 확인할 항목을 처리해라",
    },
    "deliver.head": {
        "en": "[pre-delivery check] Look once more before this reaches the owner. Fix only what applies below. If nothing needs fixing, write only \"checked: unchanged\".",
        "ko": "[내놓기 전 점검] 주인에게 가기 전에 한 번만 다시 본다. 아래에 해당하는 것만 고친다. 고칠 것이 없으면 \"점검함: 그대로\"라고만 쓴다.",
    },
    "deliver.unopened": {
        "en": "- You delivered {files} without reopening it after writing it this turn. Read it from start to end yourself, and say in one line what you fixed.",
        "ko": "- 이번 턴에 쓴 {files}를 다시 열어 보지 않고 내놓았다. 처음부터 끝까지 직접 읽고, 고친 데가 있으면 한 줄로 적는다.",
    },
    "deliver.reader": {
        "en": "- This is a long report after long work. Reread it as the recipient. (1) Is the answer to what the owner asked within the first two sentences? (2) Do names, abbreviations, or numbers you coined while working appear without explanation? (3) Is there content the owner did not ask for that does not change the answer? If you fix anything, write the whole report again.",
        "ko": "- 긴 작업 뒤의 긴 보고다. 받는 사람 자리에서 다시 읽는다. (1) 맨 앞 두 문장 안에 주인이 물은 것의 답이 있나. (2) 일하는 동안 붙인 이름, 약어, 번호가 풀이 없이 나오나. (3) 주인이 묻지 않았고 답을 바꾸지도 않는 내용이 있나. 고쳤다면 보고 전문을 다시 쓴다.",
    },
    "deliver.request": {
        "en": "What the owner asked: \"{request}\"",
        "ko": "주인이 물은 것: \"{request}\"",
    },
    "deliver.none": {"en": "no signal fired", "ko": "걸린 신호 없음"},
    "deliver.stats_head": {
        "en": "blocked {blocks} turns; {after} were seen again, and the answer changed in {changed}",
        "ko": "막은 턴 {blocks}개. 그 가운데 다시 본 것 {after}개, 답이 바뀐 것 {changed}개",
    },
    "deliver.stats_row": {
        "en": "recorded only {observed} · blocked {fired} · seen again {seen} · changed {changed}",
        "ko": "기록만 {observed} · 막음 {fired} · 다시 봄 {seen} · 바뀜 {changed}",
    },
    "setup.failed": {
        "en": "setup finished, but verification failed (doctor rc={doctor} · baseline rc={baseline}). Fix the FAIL items above and run python3 tools/doctor.py again.",
        "ko": "setup은 끝났지만 검증이 실패했다 (doctor rc={doctor} · baseline rc={baseline}). 위 FAIL을 고치고 python3 tools/doctor.py 를 다시 돌려라.",
    },
    "recall.no_transcripts": {
        "en": "No Claude conversation records exist for this folder yet ({path}). Records of other projects are not searched.",
        "ko": "이 폴더의 Claude 대화 기록이 아직 없다 ({path}). 다른 프로젝트의 기록은 찾지 않는다.",
    },
    "recall.unverified_files": {
        "en": "{count} Claude record file(s) have no working-folder field, so they were included without confirming that they belong to this folder.",
        "ko": "Claude 기록 파일 {count}개는 작업 폴더 정보가 없어, 이 폴더 것인지 확인하지 못한 채 포함했다.",
    },
    "recall.literal_fallback": {
        "en": "Not a valid regular expression ({error}); searched for the literal text instead.",
        "ko": "정규식으로 읽을 수 없어 ({error}) 글자 그대로 찾았다.",
    },
    "recall.scope": {
        "en": "{files} file(s) from {sources}, {messages} message(s) read{filters}",
        "ko": "{sources}의 파일 {files}개, 메시지 {messages}개{filters}",
    },
    "recall.zero_hits": {
        "en": "No match for /{pattern}/ in the searched scope: {scope}. This does not mean the original is absent. Try other words, a different form of the word, or the other language (Korean/English).",
        "ko": "찾은 범위에서 /{pattern}/ 를 못 찾았다: {scope}. 원문이 없다는 뜻은 아니다. 낱말이나 활용형을 바꾸거나 다른 언어(한국어/영어)로 다시 찾아볼 것.",
    },
    "context_budget.title": {
        "en": "Fixed context per session (tokens approx: 1 per Hangul/CJK/kana char, 1 per 4 other chars)",
        "ko": "세션마다 고정으로 들어가는 컨텍스트 (토큰은 어림: 한글·한자·가나 글자당 1, 나머지 4글자당 1)",
    },
    "context_budget.col_item": {"en": "item", "ko": "항목"},
    "context_budget.item.instructions": {"en": "instruction files", "ko": "지침 파일"},
    "context_budget.item.state": {"en": "state injection", "ko": "상태 주입"},
    "context_budget.item.session_hooks": {"en": "other SessionStart hooks", "ko": "세션 시작 훅(트리거)"},
    "context_budget.item.prompt_hooks": {"en": "per-prompt hooks (one turn)", "ko": "프롬프트마다 훅(한 턴)"},
    "context_budget.item.memory_index": {"en": "runtime memory index", "ko": "런타임 기억 색인"},
    "context_budget.absent": {"en": "absent", "ko": "없음"},
    "context_budget.estimate": {"en": "estimate", "ko": "어림"},
    "context_budget.unmeasured": {"en": "unmeasured", "ko": "못 잼"},
    "context_budget.over": {"en": "OVER", "ko": "OVER 경고선 넘음"},
    "context_budget.total": {"en": "total", "ko": "합계"},
    "context_budget.top": {"en": "largest three: {items}", "ko": "가장 큰 셋: {items}"},
    "context_budget.note_error": {
        "en": "{source} failed ({error_type}); see the estimate above",
        "ko": "{source} 실패 ({error_type}); 위 값은 어림",
    },
    "context_budget.note_now_absent": {
        "en": "state/NOW.md absent: the hook injects its short failure notice instead",
        "ko": "state/NOW.md 없음: 훅은 대신 짧은 실패 안내를 넣는다",
    },
    "context_budget.note_unmeasured": {
        "en": "unmeasured hook: {command}",
        "ko": "못 잰 훅: {command}",
    },
    "context_budget.note_gate_resume": {
        "en": "gate.py resume: 0 unless the previous turn failed verification",
        "ko": "gate.py resume: 지난 턴이 검증에 막혔을 때만 출력, 평소 0",
    },
    "context_budget.memory_hint": {
        "en": "Memory index over its warning line ({path}): move lines that apply to one kind of work into a sub-index file <name>-index.md in the same folder and keep one line in MEMORY.md that links it. now.py check counts links one level down from MEMORY.md.",
        "ko": "기억 색인이 경고선을 넘었다 ({path}): 한 종류의 일에만 해당하는 줄은 같은 폴더의 하위 색인 파일 <이름>-index.md로 옮기고, MEMORY.md에는 그 파일을 가리키는 한 줄만 둔다. now.py check는 MEMORY.md에서 한 단계 아래 링크까지 색인된 것으로 센다.",
    },
    "doctor.context_ok": {
        "en": "fixed context {bytes} bytes (~{tokens} tokens)",
        "ko": "고정 컨텍스트 {bytes}바이트 (토큰 어림 {tokens})",
    },
    "doctor.check.workspace_growth": {"en": "workspace · growth", "ko": "작업 폴더 · 자람"},
    "doctor.growth_item_disk": {"en": "disk free", "ko": "디스크 남은 자리"},
    "doctor.growth_item_git": {"en": ".git", "ko": ".git"},
    "doctor.growth_item_tmp": {
        "en": "tmp/ untouched over {days} days",
        "ko": "tmp/에서 {days}일 넘게 안 고친 것",
    },
    "doctor.growth_item_work": {
        "en": "job folders without a guide page",
        "ko": "길잡이 없는 일 폴더",
    },
    "doctor.growth_na": {"en": "{item}: not applicable", "ko": "{item}: 해당 없음"},
    "doctor.growth_unmeasured": {
        "en": "{item}: not measured within {ms} ms",
        "ko": "{item}: {ms}ms 안에 재지 못함",
    },
    "doctor.growth_disk_low": {
        "en": "{size} left on this disk, below {limit}. The other items of this check show "
              "what in the workspace is growing",
        "ko": "이 디스크에 남은 자리 {size}, 경고선 {limit} 미만. 작업 폴더에서 무엇이 자라는지는 "
              "이 검사의 다른 항목에서 본다",
    },
    "doctor.growth_git_over": {
        "en": ".git holds {size}, over {limit}. The kit tracks only the engine, so a large .git "
              "means something other than the engine is entering Git. Look at "
              "git count-objects -vH and git for-each-ref",
        "ko": ".git 크기 {size}, 경고선 {limit} 초과. 킷은 엔진만 추적하므로 .git이 크면 엔진이 "
              "아닌 것이 Git에 들어가고 있다는 뜻이다. git count-objects -vH와 git for-each-ref를 본다",
    },
    "doctor.growth_tmp_over": {
        "en": "tmp/ has {size} untouched for over {days} days, over {limit}. Largest: {items}",
        "ko": "tmp/에서 {days}일 넘게 안 고친 것 {size}, 경고선 {limit} 초과. 큰 것: {items}",
    },
    "doctor.growth_work_over": {
        "en": "{count} job folders have no top-level page starting with README, STATE, HANDOFF, "
              "DOSSIER, or INDEX, over {limit}. Examples: {items}. Such a page says what the job "
              "is, its status, and what may be deleted",
        "ko": "맨 위에 README, STATE, HANDOFF, DOSSIER, INDEX로 시작하는 문서가 없는 일 폴더 {count}개, "
              "경고선 {limit}개 초과. 예: {items}. 그 문서에는 무슨 일인지, 지금 상태, 지워도 되는 것을 적는다",
    },
    "doctor.context_over": {
        "en": "fixed context {bytes} bytes (~{tokens} tokens); over warning line: {items}. Details: python3 tools/context_budget.py",
        "ko": "고정 컨텍스트 {bytes}바이트 (토큰 어림 {tokens}); 경고선 넘음: {items}. 자세히: python3 tools/context_budget.py",
    },
    "recall.more": {
        "en": "[{hidden} more of {total} matches not shown. Full output: --full · narrow: --max, --role, --since, --source]",
        "ko": "[일치 {total}건 중 {hidden}건 더 있음. 전부 보기: --full · 좁히기: --max, --role, --since, --source]",
    },
    "recall.help_around": {
        "en": "messages of context before and after each hit (default 0; {full} with --full or --json)",
        "ko": "매치마다 앞뒤로 보일 문맥 메시지 수 (기본 0, --full이나 --json이면 {full})",
    },
    "recall.help_full": {
        "en": "print every selected hit with its neighbouring messages (default output is capped at {max_bytes} bytes)",
        "ko": "고른 매치를 앞뒤 문맥과 함께 전부 출력 (기본 출력은 {max_bytes}바이트에서 자른다)",
    },
    "recall.help_include_agents": {
        "en": "also search Codex subagent rollouts and known agent hand-off messages (Claude subagent transcripts are not searched)",
        "ko": "Codex 서브에이전트 rollout과 알려진 에이전트 전달문도 검색 (Claude 하위 에이전트 전사는 찾지 않는다)",
    },
    "rec.find_scope": {
        "en": "{total} record(s) under {facts} (claim, body, id, speaker, tags){filters}",
        "ko": "{facts} 아래 레코드 {total}건 (주장·본문·id·발화자·태그){filters}",
    },
    "rec.find_zero": {
        "en": "[find] 0 hits in the searched scope: {scope}. Not found here is not proof of absence; do not fill the gap by guessing (PRD §4.4). Try other words or the other language (Korean/English).",
        "ko": "[find] 찾은 범위에서 0건: {scope}. 여기서 못 찾았다고 없는 것은 아니다. 추측으로 메우지 말 것 (PRD §4.4). 낱말을 바꾸거나 다른 언어(한국어/영어)로 다시 찾아볼 것.",
    },
    "eval_recall.unmeasured": {
        "en": "[{band}] unmeasured: no query words could be extracted from any of the {skipped} sampled messages. This is not a 0% hit rate.",
        "ko": "[{band}] 측정 못 함: 표본 {skipped}개 발화 어디에서도 질의어를 뽑지 못했다. 0% 적중이 아니다.",
    },
    # Lookup, checks, and worker tools.
    # Ledger status values are data written into fact records. Readers accept both forms.
    "rec.status.decided": {"en": "decided", "ko": "결정됨"},
    "rec.status.retracted": {"en": "retracted", "ko": "철회됨"},
    "rec.status.confirmed": {"en": "confirmed", "ko": "확정"},
    "rec.status.inferred": {"en": "inferred", "ko": "추론"},
    "rec.status.hearsay": {"en": "hearsay", "ko": "전언"},
    "rec.status.unresolved": {"en": "unresolved", "ko": "미해결"},
    "rec.status.superseded": {"en": "superseded", "ko": "대체됨"},
    # Hotset sections; a status without a note entry has no note line.
    "rec.hot_head.decided": {"en": "A. Decided: do not propose again", "ko": "A. 결정됨 — 재제안 금지"},
    "rec.hot_head.retracted": {"en": "B. Retracted: do not repeat", "ko": "B. 철회됨 — 재발 금지"},
    "rec.hot_head.confirmed": {"en": "C. Confirmed: checked against the origin", "ko": "C. 확정 — 원점 확인된 사실"},
    "rec.hot_head.inferred": {"en": "D. Inferred: not an observation", "ko": "D. 추론 — 관측이 아니다"},
    "rec.hot_head.hearsay": {"en": "E. Hearsay", "ko": "E. 전언"},
    "rec.hot_head.unresolved": {"en": "F. Unresolved: say it is unknown", "ko": "F. 미해결 — 모르면 모른다고 한다"},
    "rec.hot_head.superseded": {"en": "G. Superseded", "ko": "G. 대체됨"},
    "rec.hot_note.decided": {"en": "Proposing this item again is a bug (I-1).", "ko": "이 항목을 다시 제안하면 버그다 (I-1)."},
    "rec.hot_note.retracted": {"en": "Stating this claim again is a bug (I-5).", "ko": "이 주장을 다시 말하면 버그다 (I-5)."},
    "rec.hot_note.inferred": {"en": "Do not quote it as a fact (I-3).", "ko": "사실처럼 인용하지 말 것 (I-3)."},
    "rec.hot_note.unresolved": {"en": "Do not fill it by guessing (PRD §4.4).", "ko": "추측으로 메우지 않는다 (PRD §4.4)."},
    "rec.hot_title": {"en": "# Hotset: loaded at session start (PRD §6.4)", "ko": "# 핫셋 — 세션 시작 시 로드 (PRD §6.4)"},
    "rec.hot_generated": {
        "en": "> **Generated file. Do not edit it.** The source of truth is the atomic notes in `_private/ledger/facts/`.",
        "ko": "> **생성물이다. 직접 고치지 말 것** — 정본은 `_private/ledger/facts/` 원자 노트다.",
    },
    "rec.hot_refresh": {
        "en": "> Refresh: edit the records, then run `python3 tools/rec.py hot` again.",
        "ko": "> 갱신: 레코드를 고친 뒤 `python3 tools/rec.py hot` 재실행.",
    },
    "rec.hot_rule": {
        "en": "> **Rule**: read this before asserting a fact (T1) or proposing an action (T2).",
        "ko": "> **규율**: 사실 단언(T1)·행동 제안(T2) 전에 여기부터 본다.",
    },
    "rec.hot_count": {"en": "> {count} record(s) / cap {cap}", "ko": "> 레코드 {count}건 / 상한 {cap}"},
    "rec.hot_over_cap": {
        "en": "> ⚠️ **Over cap ({count}/{cap})**: demote items whose phase has ended to cold (D7).",
        "ko": "> ⚠️ **상한 초과({count}/{cap})** — 국면 종료 항목을 콜드로 강등할 것 (D7).",
    },
    "rec.hot_table_head": {"en": "| Fact | Source | Date | id |", "ko": "| 사실 | 출처 | 날짜 | id |"},
    "rec.hot_dig": {
        "en": "**To dig deeper**: `python3 tools/rec.py show <id>` · `python3 tools/rec.py audit <id>` (the chain back to the origin)",
        "ko": "**깊이 파려면**: `python3 tools/rec.py show <id>` · `python3 tools/rec.py audit <id>` (원점까지의 사슬)",
    },
    "rec.no_record": {"en": "[{cmd}] no such record: {rid}", "ko": "[{cmd}] 그런 레코드 없음: {rid}"},
    "rec.audit_claim": {"en": "claim  : {value}", "ko": "주장   : {value}"},
    "rec.audit_status": {
        "en": "status : {status}   speaker: {speaker}   date: {date}",
        "ko": "등급   : {status}   발화자: {speaker}   날짜: {date}",
    },
    "rec.audit_record": {"en": "record : {path}", "ko": "레코드 : {path}"},
    "rec.audit_chain": {"en": "Audit chain (origin -> derived):", "ko": "감사 사슬 (원점 → 파생):"},
    "rec.audit_missing_mark": {"en": "✗ missing", "ko": "✗ 없음"},
    "rec.audit_origin_arrow": {"en": "  origin", "ko": "  원점 "},
    "rec.audit_best_arrow": {"en": "best-avail", "ko": "최선가용"},
    "rec.audit_this_record": {"en": "   ↓    [✓] {path}  ← this record", "ko": "   ↓    [✓] {path}  ← 이 레코드"},
    "rec.audit_origin_kind": {"en": "origin kind: {kind}", "ko": "원점 종류: {kind}"},
    "rec.audit_gap": {"en": "⚠️  origin gap: {gap}", "ko": "⚠️  원점 결손: {gap}"},
    "rec.audit_gap_note": {
        "en": "    The first chain item is not the origin but the **best source still available**. When quoting it verbatim, state the limit of its grade.",
        "ko": "    사슬 첫 항목은 원점이 아니라 **현존 최선 가용 소스**다. 축자 인용이 필요하면 등급 한계를 함께 밝힐 것.",
    },
    "rec.audit_no_gap": {"en": "origin gap: none (the origin file exists)", "ko": "원점 결손: 없음 (원점 파일이 실재)"},
    "rec.problem_missing_field": {"en": "{rid}: required field missing `{field}`", "ko": "{rid}: 필수 필드 누락 `{field}`"},
    "rec.problem_unknown_status": {"en": "{rid}: unknown status `{status}`", "ko": "{rid}: 알 수 없는 상태 `{status}`"},
    "rec.problem_id_mismatch": {"en": "{rid}: id does not match the file name", "ko": "{rid}: id와 파일명 불일치"},
    "rec.problem_missing_path": {"en": "{rid}: path missing → {path}", "ko": "{rid}: 경로 없음 → {path}"},
    "rec.problem_broken_link": {"en": "{rid}: broken link → [[{link}]]", "ko": "{rid}: 끊긴 링크 → [[{link}]]"},
    "rec.problem_missing_target": {"en": "{rid}: {field} target missing → {target}", "ko": "{rid}: {field} 대상 없음 → {target}"},
    "rec.problem_superseded_without_link": {
        "en": "{rid}: status `{status}` requires `superseded_by`",
        "ko": "{rid}: 상태가 `{status}`인데 `superseded_by` 없음",
    },
    "rec.problem_hot_over_cap": {
        "en": "hotset over cap: {count}/{cap} (D7: demote items whose phase has ended)",
        "ko": "핫셋 상한 초과: {count}/{cap} (D7 — 국면 종료 항목 강등 필요)",
    },
    "rec.problem_duplicate_id": {"en": "duplicate id: {rid}", "ko": "중복 id: {rid}"},
    "rec.check_counts": {"en": "[check] {count} record(s) · hot {hot}/{cap}", "ko": "[check] 레코드 {count}건 · 핫 {hot}/{cap}"},
    "rec.check_statuses": {"en": "[check] statuses:", "ko": "[check] 상태:"},
    # Read back by doctor.py and coherence.py; both forms are accepted there.
    "rec.check_trailer": {"en": "[check] problems: {count}", "ko": "[check] 문제: {count}건"},
    "rec.snapshot_unchanged": {"en": "[snapshot] unchanged; skipped", "ko": "[snapshot] 변경 없음 — 건너뜀"},
    "rec.snapshot_done": {
        "en": "[snapshot] {name} ({count} fact(s), ring {ring}/20)",
        "ko": "[snapshot] {name} (facts {count}건, 링 {ring}/20)",
    },
    "rec.new_bad_id": {"en": "[new] id must be kebab-case: {rid}", "ko": "[new] id는 kebab-case여야 한다: {rid}"},
    "rec.new_exists": {"en": "[new] already exists: {path}", "ko": "[new] 이미 존재: {path}"},
    "rec.new_transition": {
        "en": "[new] Change an existing record by a **status transition**, not an edit (README: superseded/retracted + supersedes)",
        "ko": "[new] 기존 레코드 수정은 편집이 아니라 **상태 전이**로 (README — 대체됨/철회됨 + supersedes)",
    },
    "rec.todo_origin": {"en": "TODO-origin-path", "ko": "TODO-원점-경로"},
    "rec.todo_claim": {"en": "TODO-one-sentence-claim", "ko": "TODO-한-문장-주장"},
    "rec.todo_status": {"en": "TODO-status", "ko": "TODO-상태"},
    "rec.todo_domain": {"en": "TODO-domain", "ko": "TODO-도메인"},
    "rec.todo_tags": {"en": "TODO-tags", "ko": "TODO-태그"},
    "rec.todo_speaker": {"en": "TODO-speaker", "ko": "TODO-발화자"},
    "rec.todo_origin_kind": {
        "en": "TODO-audio|transcript|transcript-derived|message|document|session-utterance",
        "ko": "TODO-오디오|전사|전사파생|메시지|문서|세션발화",
    },
    "rec.new_evidence": {
        "en": "**Evidence**: (quote verbatim when possible. If the origin is lost, say so in origin_gap)",
        "ko": "**근거**: (가능하면 축자 인용. 원점이 유실됐으면 origin_gap에 정직하게)",
    },
    "rec.new_scope": {"en": "**Caveats/scope**: ", "ko": "**주의/범위**: "},
    "rec.new_next": {
        "en": "[new] next: fill the TODOs → `rec.py check` → `rec.py hot`",
        "ko": "[new] 다음: TODO 채우기 → `rec.py check` → `rec.py hot`",
    },
    "rec.no_ledger": {"en": "[rec] no ledger: {path}", "ko": "[rec] 원장이 없다: {path}"},
    "coherence.linkcheck_failed_detail": {
        "en": "linkcheck measurement failed (exit {code}): {detail}",
        "ko": "linkcheck 측정 실패 (exit {code}): {detail}",
    },
    "coherence.hub_no_index": {"en": "{dir}: index missing ({index})", "ko": "{dir}: 인덱스 없음 ({index})"},
    "coherence.hub_unlisted": {
        "en": "{dir}/{index}: {count} new file(s) not listed: {names}",
        "ko": "{dir}/{index}: 미기재 신입 {count}개 — {names}",
    },
    "coherence.status_no_date": {"en": "{path}: no update date in the header", "ko": "{path}: 헤더에 갱신일 없음"},
    "coherence.status_stale": {
        "en": "{path}: updated {age} day(s) ago (allowed {max_days}, header {date})",
        "ko": "{path}: 갱신 {age}일 경과 (허용 {max_days}일, 헤더 {date})",
    },
    "coherence.linkcheck_failed": {"en": "linkcheck measurement failed", "ko": "linkcheck 측정 실패"},
    "coherence.broken_links": {"en": "broken links {count}", "ko": "깨진 링크 {count}"},
    "coherence.ledger_problems": {"en": "ledger problems {count}", "ko": "원장 문제 {count}"},
    # The three summary lines below are read back by doctor.py; it accepts both forms.
    "coherence.quiet_issues": {"en": "[coherence] {count} issue(s): {items}", "ko": "[coherence] 이슈 {count}건: {items}"},
    "coherence.quiet_clean": {"en": "[coherence] no issues", "ko": "[coherence] 이상 없음"},
    "coherence.total": {"en": "[coherence] total {count}", "ko": "[coherence] 총 {count}건"},
    "coherence.summary": {
        "en": "[coherence] {today}: links {links} · ledger {ledger} · hubs {hubs} · staleness {stale}",
        "ko": "[coherence] {today} — 링크 {links} · 원장 {ledger} · 허브 {hubs} · 유통기한 {stale}",
    },
    "coherence.ledger_absent": {"en": "absent", "ko": "없음"},
    "coherence.count": {"en": "{count}", "ko": "{count}건"},
    "coherence.section.links": {"en": "links", "ko": "링크"},
    "coherence.section.ledger": {"en": "ledger", "ko": "원장"},
    "coherence.section.hubs": {"en": "hubs", "ko": "허브"},
    "coherence.section.stale": {"en": "staleness", "ko": "유통기한"},
    "doctor.canary_unreadable": {
        "en": "fired/effect=unknown (canary result unreadable: {error_type})",
        "ko": "fired/effect=unknown (canary 결과 판독 실패: {error_type})",
    },
    "doctor.precompact_fallback_none": {"en": "none", "ko": "없음"},
    # install_hooks.sh --check first-line prefixes; doctor accepts both forms.
    "doctor.form.hooks_current": {"en": "current:", "ko": "현재(current):"},
    "doctor.form.hooks_missing": {"en": "missing:", "ko": "없음(missing):"},
    "doctor.form.coherence_links_ok": {"en": "links OK", "ko": "링크 OK"},
    "doctor.ledger_check_failed": {"en": "rec.py check failed: {detail}", "ko": "rec.py check 실패: {detail}"},
    "doctor.ledger_no_trailer": {
        "en": "rec.py check output has no `problems: N` trailer",
        "ko": "rec.py check 결과에 `문제: N건` trailer가 없다",
    },
    "doctor.work_symlinks": {
        "en": "{count} tracked symlink(s) in the work index",
        "ko": "work index의 추적 symlink {count}개",
    },
    "doctor.index_privacy_failed": {
        "en": "index privacy measurement failed: {error_type}",
        "ko": "index privacy 측정 실패: {error_type}",
    },
    "doctor.index_privacy_violation": {"en": "index privacy violation: {issues}", "ko": "index privacy 위반: {issues}"},
    "gate.approval_no_control_plane": {
        "en": "no Git control plane, so no adoption approval boundary can be set",
        "ko": "Git control plane이 없어 채택 승인 경계를 세울 수 없다",
    },
    "gate.approval_missing": {"en": "approval missing: {path}", "ko": "승인물이 없다: {path}"},
    "gate.approval_not_json": {"en": "approval is not JSON: {path}", "ko": "승인물이 JSON이 아니다: {path}"},
    "gate.approval_malformed": {"en": "approval is malformed: {path}", "ko": "승인물 형식이 잘못됐다: {path}"},
    "gate.approval_payload_hash": {"en": "approval payload hash does not match", "ko": "승인물 payload hash가 맞지 않는다"},
    "gate.approval_key_unreadable": {"en": "cannot read the approval signing key", "ko": "승인물 서명 키를 읽을 수 없다"},
    "gate.approval_signature": {"en": "approval signature does not match", "ko": "승인물 서명이 맞지 않는다"},
    "gate.approval_not_bound_baseline": {
        "en": "approval is not bound to the current baseline",
        "ko": "승인물이 현재 baseline에 결속되지 않았다",
    },
    "gate.approval_not_bound_issues": {
        "en": "approval is not bound to the current issue set",
        "ko": "승인물이 현재 이슈 집합에 결속되지 않았다",
    },
    "gate.approve_root_mismatch": {
        "en": "approval root mismatch: M.ROOT={root} vs tool location={self_root}",
        "ko": "승인 root 불일치: M.ROOT={root} vs 도구 위치={self_root}",
    },
    "gate.approve_refused": {"en": "cannot approve: {reason}", "ko": "승인할 수 없다: {reason}"},
    "gate.approve_unsealed": {"en": "baseline is not sealed", "ko": "baseline이 봉인되지 않았다"},
    "gate.approve_checkers_failed": {"en": "checker failed: {checkers}", "ko": "검사기 실패: {checkers}"},
    "gate.approve_no_control_plane": {"en": "no Git control plane", "ko": "Git control plane이 없다"},
    "gate.approve_write_failed": {"en": "cannot write approval: {path}: {error}", "ko": "승인물을 쓸 수 없다: {path}: {error}"},
    "gate.approve_saved": {"en": "adoption approval saved: {items}", "ko": "채택 승인 저장: {items}"},
    "gate.baseline_refused": {"en": "cannot set the baseline: {reason}", "ko": "기준선을 못 세운다 — {reason}"},
    "gate.baseline_dirty_sealed": {
        "en": "the tracked tree of a sealed install is not clean",
        "ko": "sealed 설치의 tracked tree가 clean하지 않다",
    },
    "gate.baseline_corrupt": {"en": "the sealed baseline is corrupt", "ko": "sealed baseline이 손상됐다"},
    "gate.baseline_saved": {"en": "baseline saved: {counts}{suffix}", "ko": "기준선 저장: {counts}{suffix}"},
    "gate.count": {"en": "{name} {count}", "ko": "{name} {count}건"},
    "gate.run_root_mismatch": {
        "en": "run root mismatch: M.ROOT={root} vs tool location={self_root}",
        "ko": "실행 root 불일치: M.ROOT={root} vs 도구 위치={self_root}",
    },
    "gate.baseline_no_lock": {"en": "cannot set the baseline: gate lock not acquired", "ko": "기준선을 못 세운다: gate lock을 얻지 못했다"},
    "gate.seal_root_mismatch": {"en": "baseline seal root mismatch", "ko": "baseline seal root 불일치"},
    "gate.seal_refused": {"en": "baseline seal refused: baseline {state}", "ko": "baseline seal 거부: baseline {state}"},
    "gate.status_root_mismatch": {"en": "  (!! does not match tool location {self_root})", "ko": "  (!! 도구 위치 {self_root}와 불일치)"},
    "gate.status_baseline": {"en": "baseline  : {state} · {counts}", "ko": "기준선    : {state} — {counts}"},
    "gate.status_current": {"en": "current   : {counts}", "ko": "현재      : {counts}"},
    "gate.measure_failed": {"en": "{name} measurement failed", "ko": "{name} 측정실패"},
    "gate.precommit_root_mismatch": {
        "en": "[gate] run root mismatch ({root} vs {self_root}). Blocking the commit.",
        "ko": "[gate] 실행 root 불일치 ({root} vs {self_root}). 커밋을 막는다.",
    },
    "gate.precommit_checkout_failed": {"en": "[gate] could not check out the index: {error}", "ko": "[gate] index를 꺼내지 못했다: {error}"},
    "gate.precommit_no_git_tree": {
        "en": "[gate] could not create Git metadata in the temporary index tree",
        "ko": "[gate] index 임시 트리에 Git metadata를 만들지 못했다",
    },
    "gate.precommit_broken_tools": {
        "en": "[gate] Python tools in the index do not compile: {tools}",
        "ko": "[gate] index의 파이썬 도구가 깨져 있다: {tools}",
    },
    "gate.precommit_broken_tools_why": {
        "en": "  Committing broken checkers would disable this gate itself.",
        "ko": "  검사기가 깨진 채 커밋되면 이 게이트 자체가 무력해진다.",
    },
    "gate.precommit_privacy_unmeasured": {
        "en": "[gate] could not measure staged privacy enforcement",
        "ko": "[gate] staged privacy enforcement를 측정하지 못했다",
    },
    "gate.precommit_crashed": {
        "en": "[gate] the gate itself failed: {error}. Blocking the commit.",
        "ko": "[gate] 게이트 자신이 실패했다: {error}. 커밋을 막는다.",
    },
    "gate.release_root_mismatch": {"en": "[gate] run root mismatch ({root} vs {self_root}).", "ko": "[gate] 실행 root 불일치 ({root} vs {self_root})."},
    "gate.usage_baseline": {"en": "usage: gate.py baseline", "ko": "사용: gate.py baseline"},
    "gate.usage_adopt": {
        "en": "usage: gate.py approve-adoption --adopt <checker:issue-id> ...",
        "ko": "사용: gate.py approve-adoption --adopt <checker:issue-id> ...",
    },
    "enforce.git_failed": {"en": "git failed to run: {error_type}", "ko": "git 실행 실패: {error_type}"},
    "enforce.path_not_utf8": {"en": "Git path is not UTF-8", "ko": "Git path가 UTF-8이 아니다"},
    "enforce.path_stream_truncated": {"en": "Git NUL path stream was truncated", "ko": "Git NUL path stream이 잘렸다"},
    "enforce.config_missing": {"en": "config missing: {path}", "ko": "config 없음: {path}"},
    "enforce.config_unreadable": {"en": "config unreadable: {error_type}", "ko": "config 판독 실패: {error_type}"},
    "enforce.config_not_object": {"en": "config root is not an object", "ko": "config root가 object가 아니다"},
    "enforce.ls_files_no_tab": {"en": "git ls-files record has no TAB", "ko": "git ls-files record에 TAB이 없다"},
    "enforce.ls_files_metadata": {"en": "git ls-files metadata has an unexpected format", "ko": "git ls-files metadata 형식이 다르다"},
    "enforce.context_required": {
        "en": "instance.context must be set to personal or work",
        "ko": "instance.context는 personal 또는 work로 명시해야 한다",
    },
    "enforce.rules_missing": {"en": "instance-rules missing: {path}", "ko": "instance-rules 없음: {path}"},
    "enforce.rules_unreadable": {"en": "instance-rules unreadable: {error_type}", "ko": "instance-rules 판독 실패: {error_type}"},
    "enforce.rules_changeme": {"en": "instance-rules still contains CHANGEME", "ko": "instance-rules에 CHANGEME가 남아 있다"},
    "enforce.rules_empty": {"en": "instance-rules is empty", "ko": "instance-rules가 비어 있다"},
    "enforce.push_unknown_context": {
        "en": "push blocked: cannot determine instance.context",
        "ko": "push blocked: instance.context를 판정할 수 없다",
    },
    "enforce.push_work": {
        "en": "push blocked: a work instance does not allow remote export from local pre-push",
        "ko": "push blocked: work instance는 local pre-push에서 원격 반출을 허용하지 않는다",
    },
    "enforce.fallback_authority": {
        "en": "Read state/NOW.md together with _private/state/NOW.md when it exists. A missing local overlay means unavailable, not no state.",
        "ko": "state/NOW.md와 존재할 때 _private/state/NOW.md를 함께 읽어라. local overlay 부재는 unavailable이지 상태 없음이 아니다.",
    },
    "enforce.hook_root_mismatch": {
        "en": "refused state injection or gate run because the hook project root does not match",
        "ko": "hook project root 불일치로 상태 주입 또는 게이트 실행을 거부했다",
    },
    "enforce.hook_failed": {"en": "{event} hook failed (exit {code})", "ko": "{event} hook 실행 실패(exit {code})"},
    "enforce.sessionstart_invalid_json": {
        "en": "SessionStart hook did not print valid JSON",
        "ko": "SessionStart hook이 유효 JSON을 내지 않았다",
    },
    "enforce.stop_invalid_json": {"en": "Stop gate did not print valid JSON", "ko": "Stop gate가 유효 JSON을 내지 않았다"},
    "enforce.command_required": {"en": "--issues or a command is required", "ko": "--issues 또는 command가 필요하다"},
    "evidencecheck.help_tree": {"en": "tree to check (default: the root this tool belongs to)", "ko": "검사할 트리 (기본: 도구가 속한 루트)"},
    "evidencecheck.help_local_root": {"en": "local root used to find runs and instance DRs", "ko": "run과 인스턴스 DR을 찾을 로컬 루트"},
    "evidencecheck.help_test_log": {
        "en": "RAN execution evidence log (default: environment variable or the .git log)",
        "ko": "RAN 실행 증거 로그 (기본: 환경변수 또는 .git 로그)",
    },
    "evidencecheck.help_issues": {"en": "stable issue set for the gate", "ko": "게이트용 안정 이슈 집합"},
    "evidencecheck.required_context": {
        "en": "required evidence marker missing {path} {decision} context section",
        "ko": "필수 근거 표지 없음 {path} {decision} 맥락 절",
    },
    "evidencecheck.required_changelog": {
        "en": "required evidence marker missing CHANGELOG.md {heading}",
        "ko": "필수 근거 표지 없음 CHANGELOG.md {heading}",
    },
    "evidencecheck.required_test": {
        "en": "required test marker missing {path} ENFORCED row {row}",
        "ko": "필수 test 표지 없음 {path} ENFORCED 행 {row}",
    },
    "evidencecheck.missing_file": {"en": "checked file missing {path}", "ko": "검사 대상 파일 없음 {path}"},
    "evidencecheck.syntax": {"en": "marker syntax violation {where} {marker}", "ko": "표지 문법 위반 {where} {marker}"},
    "evidencecheck.missing_local": {"en": "local ID missing {where} {marker}", "ko": "로컬 ID 없음 {where} {marker}"},
    "evidencecheck.no_run_evidence_log": {
        "en": "no run evidence {where} {marker} log={log}",
        "ko": "실행 증거 없음 {where} {marker} log={log}",
    },
    "evidencecheck.no_run_evidence": {"en": "no run evidence {where} {marker}", "ko": "실행 증거 없음 {where} {marker}"},
    "evidencecheck.review": {
        "en": "REVIEW external existence undetermined {where} {marker}",
        "ko": "REVIEW 외부 존재 미판정 {where} {marker}",
    },
    "recall.label_system": {"en": " [injected]", "ko": " [주입]"},
    "recall.label_summary": {"en": " [summary]", "ko": " [요약본]"},
    "recall.hit_header": {"en": "■ hit {hit} · ", "ko": "■ 매치 {hit} · "},
    "recall.sessions_more": {
        "en": "({shown}/{total} shown, newest first · all: `recall.py sessions --all`)",
        "ko": "({shown}/{total}개 최신순 표시 · 전량은 `recall.py sessions --all`)",
    },
    "recall.help_json": {
        "en": "structured results including source location, native ID, and record ID",
        "ko": "원문 위치·native ID·record ID를 포함한 구조화 결과",
    },
    "recall.help_source": {
        "en": "all (default)|claude|codex|dumps; a comma-separated list is allowed",
        "ko": "all(기본)|claude|codex|dumps, 콤마 목록 가능",
    },
    "recall.help_include_system": {
        "en": "also show system-injected records (plugin lists, full AGENTS text, command wrappers, and so on)",
        "ko": "시스템 주입 레코드도 표시 (플러그인 목록·AGENTS 전문·커맨드 래퍼 등)",
    },
    "recall.help_order": {
        "en": "score=match quality (default) · recent=newest first · oldest=file order (previous behaviour)",
        "ko": "score=매치품질(기본) · recent=최신순 · oldest=파일순(이전 동작)",
    },
    "recall.help_all_instances": {
        "en": "also search Codex sessions and Claude records written in other folders (default: this instance only; DR-025)",
        "ko": "다른 폴더에서 쓴 Codex 세션과 Claude 기록까지 검색 (기본은 이 인스턴스만 — DR-025)",
    },
    "recall.max_too_small": {"en": "--max must be 1 or more", "ko": "--max는 1 이상이어야 한다"},
    # Query-word stop lists, not display text: eval_recall.py uses both lists in every language.
    "eval_recall.stopwords": {
        "en": "the and for that this with from have been will你",
        "ko": "그리고 그런데 그래서 하지만 이거 저거 그거 이건 저건 그건 있다 없다 한다 된다 그럼 근데 아니 네가 내가 우리 너무 정말 진짜 조금 많이 이제 지금 다시 그냥 좀더 같이 대해 위해 통해",
    },
    "eval_recall.too_few": {
        "en": "Not enough transcript messages ({count}). Accumulate more sessions and measure again.",
        "ko": "전사 발화가 부족하다 ({count}개). 세션을 더 쌓고 다시 재라.",
    },
    "eval_recall.found": {"en": "found", "ko": "찾음"},
    "eval_recall.missed": {"en": "missed", "ko": "실패"},
    "eval_recall.recorded": {"en": "recorded: {path}", "ko": "기록: {path}"},
    "eval_recall.summary": {
        "en": "[{band}] hit@{max_hits} = {hits}/{tried} ({rate}) · corpus messages {turns}",
        "ko": "[{band}] hit@{max_hits} = {hits}/{tried} ({rate}) · 코퍼스 발화 {turns}개",
    },
    "eval_recall.skipped": {"en": " · no query words {count}", "ko": " · 질의어 못 뽑음 {count}개"},
    "eval_recall.misses": {
        "en": "{count} miss(es) (to classify by cause: source, parser, eligibility, ranking, wording):",
        "ko": "실패 {count}건 (소스·파서·출처·순위·표현 차이 원인 분류 대상):",
    },
    "eval_recall.floor": {
        "en": "This number is a **floor**: query words come from the original text, so wording mismatch is not measured.",
        "ko": "이 수치는 **바닥**이다 — 질의어를 원문에서 뽑았으므로 표현 불일치는 안 쟀다.",
    },
    "eval_recall.help_band": {
        "en": "query difficulty. rare=rare tokens (easy) · topic=topic words (real use)",
        "ko": "질의어 난이도. rare=희귀토큰(쉬움) · topic=주제어(실사용)",
    },
    "ask_codex.prompt_missing": {"en": "prompt file missing: {path}", "ko": "프롬프트 파일 없음: {path}"},
    "ask_codex.usage": {
        "en": "usage: {script} <prompt-file> [--fresh | --resume <SID>]",
        "ko": "사용법: {script} <프롬프트파일> [--fresh | --resume <SID>]",
    },
    "ask_codex.usage_resume": {
        "en": "  --resume skips the worker contract (user config ignored, features locked, run record, receipt cap) and writes straight into that thread.",
        "ko": "  --resume은 일꾼 계약(사용자 설정 무시, 기능 차단, 실행 기록, 영수증 상한)을 건너뛰고 그 스레드에 바로 이어 쓴다.",
    },
    "ask_codex.resume_refused": {
        "en": "resume refused (the app holds the thread). **No fallback.**",
        "ko": "resume 거부됨 (앱이 스레드를 점유 중). **폴백하지 않는다.**",
    },
    "ask_codex.resume_choices": {
        "en": "Two options: close the thread in the app and retry, or dispatch with --fresh.",
        "ko": "선택지 둘: 앱에서 그 스레드를 닫고 재시도하거나, --fresh로 발주해라.",
    },
    "worker.prompt_outside": {"en": "prompt path is outside the workspace", "ko": "prompt path가 workspace 밖이다"},
    "worker.prompt_symlink": {"en": "prompt path has a symlink component", "ko": "prompt path에 symlink component가 있다"},
    "worker.prompt_missing": {"en": "prompt file does not exist", "ko": "prompt file이 없다"},
    "worker.prompt_unsafe_open": {
        "en": "cannot open the prompt file safely: {error_type}",
        "ko": "prompt file을 안전하게 열 수 없다: {error_type}",
    },
    "worker.prompt_not_regular": {"en": "prompt is not a regular file", "ko": "prompt가 regular file이 아니다"},
    "worker.prompt_empty": {"en": "prompt is empty", "ko": "prompt가 비어 있다"},
    "worker.prompt_not_utf8": {"en": "prompt is not UTF-8 text", "ko": "prompt가 UTF-8 text가 아니다"},
    "worker.prefix_outside": {"en": "write-prefix is outside the workspace", "ko": "write-prefix가 workspace 밖이다"},
    "worker.prefix_outside_or_root": {
        "en": "write-prefix is outside the workspace or the whole root",
        "ko": "write-prefix가 workspace 밖이거나 루트 전체다",
    },
    "worker.prefix_symlink": {"en": "write-prefix has a symlink component", "ko": "write-prefix에 symlink component가 있다"},
    "worker.parent_unmeasurable": {
        "en": "cannot measure the workspace parent: {error_type}",
        "ko": "workspace parent를 측정할 수 없다: {error_type}",
    },
    "worker.git_failed": {"en": "git failed to run: {error_type}", "ko": "git 실행 실패: {error_type}"},
    "worker.git_command_failed": {"en": "git {command} failed: {detail}", "ko": "git {command} 실패: {detail}"},
    "worker.worktree_cleanup_failed": {"en": "worktree cleanup failed: {detail}", "ko": "worktree 정리 실패: {detail}"},
    "worker.strict_scope_needs_prefix": {
        "en": "--strict-scope needs at least one --write-prefix",
        "ko": "--strict-scope에는 하나 이상의 --write-prefix가 필요하다",
    },
    "receipts.total": {
        "en": "total runs={runs} tokens={tokens} failures={failures}",
        "ko": "합계 runs={runs} tokens={tokens} failures={failures}",
    },
    "receipts.unreadable": {"en": "warning unreadable={count}", "ko": "경고 unreadable={count}"},
    "receipts.bad_duration": {"en": "a period must look like 7d or 24h", "ko": "기간은 7d 또는 24h 형식이어야 한다"},
    "receipts.run_not_found": {"en": "run not found: {run_id}", "ko": "run을 찾을 수 없다: {run_id}"},
    "receipts.cost_title": {"en": "token totals by runtime (input/output/total)", "ko": "런타임별 토큰 합계 (input/output/total)"},
    "receipts.no_runs": {"en": "(no runs)", "ko": "(run 없음)"},
    "receipts.daily_title": {"en": "daily histogram (total tokens)", "ko": "하루 단위 히스토그램 (total tokens)"},
    "receipts.none": {"en": "none", "ko": "없음"},
    "receipts.wave_too_many": {
        "en": "one wave can aggregate at most {max} runs",
        "ko": "한 파도는 run {max}개까지 집계할 수 있다",
    },
}


def language():
    """Return "en" or "ko": MOTTORI_LANG, then the language saved at install, then the locale."""
    explicit = os.environ.get("MOTTORI_LANG")
    if explicit in ("en", "ko"):
        return explicit
    configured = configured_language()
    if configured:
        return configured
    locales = (os.environ.get("LC_ALL", ""), os.environ.get("LANG", ""))
    return "ko" if any(value.lower().startswith("ko") for value in locales) else "en"


_CONFIGURED = {}


def configured_language():
    """Return `instance.lang` from the instance config, or None when it is absent or unreadable.

    Generated state files and journal markers are written in the instance language, so that
    language must not change with the locale of whichever shell or scheduler runs a tool.
    """
    root = os.environ.get("MOTTORI_INSTANCE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in _CONFIGURED:
        try:
            with open(os.path.join(root, "system", "memory-config.json"), encoding="utf-8") as f:
                value = json.load(f).get("instance", {}).get("lang")
        except (OSError, ValueError, AttributeError):
            value = None
        _CONFIGURED[root] = value if value in ("en", "ko") else None
    return _CONFIGURED[root]


def t(key, **kw):
    return STRINGS[key][language()].format(**kw)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 2
    values = {}
    for arg in args[1:]:
        name, sep, value = arg.partition("=")
        if not sep:
            return 2
        values[name] = value
    print(t(args[0], **values))
    return 0


if __name__ == "__main__":
    sys.exit(main())
