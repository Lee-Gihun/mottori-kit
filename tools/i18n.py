#!/usr/bin/env python3
import os
import sys


STRINGS = {
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
        "en": "{count} shared tools byte-identical ({kit})",
        "ko": "공유 도구 {count}개 바이트 동일 ({kit})",
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
    "doctor.check.tools_portrait": {"en": "tools · person ledger", "ko": "도구 · 인물 원장"},
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
        "en": "Issues absent before this turn appeared: {detail}. Fix them before finishing. If intentional, run `python3 tools/gate.py baseline`.",
        "ko": "이번 턴에 없던 이슈가 생겼다 — {detail}. 고치고 끝내라. 의도한 변화면 `python3 tools/gate.py baseline`.",
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
    "setup.failed": {
        "en": "setup finished, but verification failed (doctor rc={doctor} · baseline rc={baseline}). Fix the FAIL items above and run python3 tools/doctor.py again.",
        "ko": "setup은 끝났지만 검증이 실패했다 (doctor rc={doctor} · baseline rc={baseline}). 위 FAIL을 고치고 python3 tools/doctor.py 를 다시 돌려라.",
    },
}


def language():
    explicit = os.environ.get("MOTTORI_LANG")
    if explicit in ("en", "ko"):
        return explicit
    locales = (os.environ.get("LC_ALL", ""), os.environ.get("LANG", ""))
    return "ko" if any(value.lower().startswith("ko") for value in locales) else "en"


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
