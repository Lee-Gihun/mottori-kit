# CHANGELOG

**This file records what an existing instance must do, not merely what was added.**

The engine arrives through `git pull`, but **instance-owned files do not**: `system/memory-config.json`,
`system/instance-rules.md`, `system/decisions.md`, `system/rituals.local.md`, `state/`, and `_private/`. When a new
engine expects a new field or section in those files, a person must add it. This file records those manual steps.

Every item is marked `[Action required]`, `[Note]`, or `[Automatic]`. If any `[Action required]` item is
outstanding, `python3 tools/doctor.py` fails after the pull.

---

## v0.8 · 2026-09-18 (English canonical migration)

### `[Note]` Transcription listens harder on noisy audio and reports what it could not hear

Evidence: `test:tools/test_transcribe_filter.py::test_repeated_lines_become_one_noise_span`,
`test:tools/test_transcribe_filter.py::test_low_confidence_and_watermark_segments_are_dropped`,
`test:tools/test_transcribe_filter.py::test_clean_transcript_is_untouched`, and
`test:tools/test_transcribe_filter.py::test_prompt_file_overrides_generic_default`.

`tools/transcribe.py` now denoises before decoding (`afftdn` plus `speechnorm` instead of `dynaudnorm`), decodes
with strict thresholds and a vocabulary prompt, and drops hallucination-shaped segments: repeated sentences, low
confidence, high compression, and subtitle-credit watermarks. Dropped time of eight seconds or more is written to
`<stem>-noise-spans.txt` and counted in the QA file, so a span the machine could not hear is handed to a person
instead of being invented. Measured on a restaurant recording, the same span went from a hallucination loop to
readable sentences; a speaker far from the microphone under heavier noise still cannot be recovered, and source
separation (demucs) did not help there. The engine ships only generic prompts. Names and domain terms belong to
the instance in `_private/transcribe-prompts.json` (`{"ko": "...", "en": "..."}`), which never enters the kit.
`setup.sh` now seeds that file from `templates/transcribe-prompts.json`; an existing instance copies the template
by hand and edits it, and the tool works without the file. Seed data under `templates/*.json` may carry Hangul only
on `"ko"` lines, the same contract as the `ko` column of `tools/i18n.py`
(`test:tools/test_language.py::test_template_json_ko_fixture`). Existing transcripts are not rewritten; rerun the
tool on a recording whose transcript shows repeated lines or invented credits.

### `[Note]` Gate-definition approval is not applicable in an installed instance

Evidence: `test:tools/test_manifests.py::test_gate_definition_approval_is_not_applicable_in_installed_instance`.

KIT-DR-013 governs the kit tree, where gate definitions are authored. An installed instance (one with
`system/memory-config.json`) receives them through engine sync, and the origin kit's ledger already approved
that diff, so `tools/manifest_build.py --issues` now reports `~gate-definition-approval` as not applicable
there. The first implementation demanded an approval line in every instance and blocked every engine sync
(2026-09-18 port measurement). New regression suites under `tools/test_` are also classified by default
(`tool`, read by people and run by gates), so a new suite no longer leaves the review manifest unclassified.
The manifest also stopped keeping a hand-written list of files that count before Git indexes them: every
untracked, not ignored file under `tools/`, `system/`, `templates/`, `.github/workflows/`, and `.claude/commands/`
counts, so a worker clone or the fresh-install fixture sees the same inventory as the committed tree, and a new
file outside those locations fails `tools/test_manifests.py` first with the rule instead of the fresh-install
gate later with a ghost path (`test:tools/test_manifests.py::test_new_files_are_within_delivery_prefixes`).

### `[Note]` The CI workflow file is valid again and its job-level contexts are pinned

Evidence: `test:tools/test_manifests.py::test_workflow_job_env_uses_only_job_level_contexts`.

v0.8 (5/n) put `${{ runner.temp }}` in the job-level `env` of `.github/workflows/gates.yml`. GitHub rejects
that context there, so the workflow file was invalid and no job ran on a725859: the remote gate was silent,
not green. The log path now uses `github.workspace`, and `tools/test_manifests.py` rejects any job-level `env`
expression outside the contexts GitHub allows there (github, needs, strategy, matrix, vars, secrets, inputs),
so the local gate measures the rule before a push. Nothing to do after the pull.

### `[Note]` Translation stamps make semantic drift visible

Evidence: `test:tools/test_language.py::test_stamp_bind_and_source_drift_fixture`,
`test:tools/test_language.py::test_stamp_pending_fixture`,
`test:tools/test_language.py::test_stamp_korean_source_fixture`, and
`test:tools/test_language.py::test_stamp_newline_and_trailing_space_normalization_fixture`.

`python3 tools/i18n_stamp.py check` verifies that each completed translation starts with the normalized SHA-256
of its declared source and reports migration backlog entries separately as pending. English is the source for
kit-owned surfaces; Korean is the source for the two PRDs, WORKING-WITH-AI, deep-pass, person-ledger, and the
lenses. After translating a changed source, run `python3 tools/i18n_stamp.py bind <translated-file>` to record
the new source hash. `tools/test_language.py` runs the same check as part of the locale-pair gate.

### `[Note]` The review manifest is now a commit-gate checker

Evidence: `test:tools/test_manifests.py::test_issues_mode_reports_stale_paths`.

`tools/manifest_build.py --issues` turns every difference between the index and `system/review-manifest.yaml`
(missing paths, ghost paths, unclassified rows, stale content) into a gate issue. A checker that is absent from
the baseline is treated as an empty baseline, so nothing has to be done after a pull; if the new checker reports
issues they are fixed in that commit. Measured 2026-09-18: the CI workflow file was committed after the manifest
had been regenerated before `git add`, and the remote gate failed on its first run. Generated files are caught by
the gate, not by a person remembering the order of steps. A tree without the manifest (an installed instance) is
not applicable.

### `[Note]` Test evidence now proves execution and gate definitions require dispatcher approval

Every Python regression suite writes a timestamped `RAN <run-id> <time> tools/test_x.py::name` row through `tools/testlib.py` when
`MOTTORI_TEST_LOG` is set. Evidence checking now fails closed when a test marker names only a definition but
has no recent execution record. Fresh-install, CI, and `tools/gate.py` create the log. Files classified as
`gate-definition` in the review manifest require a dispatcher approval line bound to the changed path set and
binary diff SHA before `tools/manifest_build.py --check` passes.

Evidence: `test:tools/test_evidencecheck.py::test_TESTS_omission_mutation_is_caught`,
`test:tools/test_manifests.py::test_gate_definition_change_requires_dispatcher_approval`.

### `[Automatic]` The first canonical kit surfaces move to English with Korean locale files

The four root operational documents and AGENTS, three instance templates, five slash commands, the paper-to-kit
workflow, and the evidence schema and matrix move to English. Korean reader surfaces use the matching `.ko.md`
file or the `ko` column in `tools/i18n.py`. `tools/test_language.py` rejects Hangul on the migrated surfaces and
checks the heading shape and relative links of every delivered `.md` and `.ko.md` pair. Other canonical files
remain migration work.

Evidence: `test:tools/test_language.py::test_pair_fixture`.

Existing instances do not rename their local files. Instance-owned rules remain at
`system/instance-rules.md`, `system/decisions.md`, and `system/rituals.local.md`; the locale split applies to kit
files only.

### `[Automatic]` The language gate fails closed around an explicit migration backlog

`tools/test_language.py` scans every engine text file. Hangul is allowed only in the `ko` column of the i18n
table, `.ko.md` locale files, marked evidence quotations with an ASCII English rendering, test-fixture strings,
and historical CHANGELOG sections. Canonical files that have not migrated yet must be listed one per line in
`system/language-pending.txt`; an unlisted file with Hangul and a listed file with no Hangul both fail the gate.
The command summary reports the pending-file count. Required locale pairs are enumerated and checked in both
directions.

Evidence: `test:tools/test_language.py::test_pending_contract_fixture`.

## v0.7 · 2026-09-18 (스웜 파도 2 B그룹 통합)

### `[알아둘 것]` 공개 state를 추적하는 인스턴스에서도 index 검사가 돈다

근거 표지: `test:tools/test_enforce.py::test_tracked_public_state_is_not_forbidden`.

`tools/enforce.py`의 금지 경로 판정은 고정 목록이 아니라 "저장소의 ignore 규칙이 덮는 경로를 force-add했는가"다.
`_private/`는 어느 index에서든 위반이고, `state/`와 인스턴스 소유 파일(memory-config·decisions·instance-rules·
rituals.local)은 새 킷 인스턴스처럼 ignore돼 있을 때만 위반이다. 원 워크스페이스처럼 공개 projection과 결정 기록을
일부러 추적하는 인스턴스는 위반이 아니다. 이식 실측(2026-09-18): 고정 목록이 원 인스턴스의 추적 중인 state 파일
전부를 위반으로 냈다. 같은 이유로 `test_install_checks`의 X12, `test_enforce`의 sync inventory,
`test_tool_entrypoints`의 sync wrapper 검사는 킷 전용 파일이 없는 트리에서 "해당없음"을 출력 줄로 남기고 건너뛴다.
symlink·submodule 규칙은 이번 커밋이 올리는 항목(HEAD 대비 변경분)에만 걸린다. HEAD에 이미 있는 항목까지 걸면 과거
트리가 모든 커밋을 영구히 막는다 (`test:tools/test_enforce.py::test_tracked_markdown_symlink_in_head_is_not_reflagged`).
pre-push는 config 없는 킷 트리(setup.sh와 templates가 있는 checkout)를 인스턴스가 아니라고 판정해 허용 줄을 내고
통과시키며, 그 밖의 판정 불능은 그대로 차단한다 (`test:tools/test_enforce.py::test_prepush_allows_presetup_kit_tree_and_blocks_unknown_context`).

### `[자동]` 문장 감사표도 review manifest가 추적한다

근거 표지: `test:tools/test_manifests.py::test_review`.

`system/reviews/content-audit.tsv`를 fresh worker 전달 경로에 등록했다. 그래서 산출물이 아직
추적되지 않은 작업 클론과 상류에 적용된 뒤의 클론이 같은 text inventory를 검사한다.

### `[해야 함]` hook 재설치가 baseline을 봉인하고 work push를 닫는다

근거 표지: `test:tools/test_enforce.py::test_G10_signed_baseline_rejects_direct_mutation`.

pull 뒤 `bash tools/install_hooks.sh --repair`를 다시 실행한다. pre-commit과 pre-push가 한 쌍으로
설치되고 기존 gate baseline은 SHA-256과 repository-local HMAC으로 봉인된다. work context의 local
commit과 push, force-add한 state/private, staged symlink와 submodule은 fail-close한다. 같은 OS 사용자가
`.git`의 hook과 key를 함께 바꾸는 공격은 local source만으로 막을 수 없어 remote required check 또는
read-only 자격증명이 계속 필요하다.

### `[알아둘 것]` strict worker scope와 운영 준비 검사가 더 좁게 실패한다

근거 표지: `test:tools/test_fresh_worker.py::test_strict_scope_detects_git_and_immediate_parent_writes`.

`--write-prefix`를 선언한 run은 strict 옵션 유무와 관계없이 위반에서 exit 4이며, `--strict-scope`는
prefix 없이 실행되지 않는다. strict 검사는 `.git`과 전용 immediate parent의 직접 변경도 기록한다.
`python3 tools/doctor.py --ready`는 instance context 누락과
`instance-rules.md`의 `CHANGEME`를 FAIL로 둔다. 기본 doctor는 첫 설치의 기계 검증 계약을 유지한다.

### `[자동]` sync inventory 단일화와 실패 rollback

`sync_engine.sh`는 `fresh_worker.py`의 `SYNC_FILES`를 직접 읽고, 복사·각인·재수입·manifest 검증 중
실패하면 기존 destination 파일을 복원한다. `rec.py check`의 crash와 출력 trailer 부재도 doctor FAIL이다.

### `[알아둘 것]` private 경로와 모델 전송 등급을 분리한다

근거 표지: `test:tools/test_egress.py::test_strict_egress_refuses_before_runtime_or_run_record`.

config schema v4에 optional `egress.model_send`가 생겼다. 필드가 없으면 `_private/` deny가 기본이라
기존 인스턴스가 손으로 올릴 schema version은 없다. `fresh_worker.py`는 deny 경로 참조 수를 receipt에
표시하고 실제 private 원문이 run의 `prompt.md`나 `result.txt`에 복제되면 `egress.log`에 출발지와
목적지를 남긴다. `--strict-egress`는 해당 참조가 있는 실행을 runtime 시작 전에 거부한다. doctor는
유효 정책의 deny 목록이 비면 FAIL한다.

### `[자동]` 위험 기반 테스트 매트릭스와 변이·우회 핀이 회귀에 들어간다

근거 표지: `test:tools/test_matrix_check.py::main`.

배포 실행물 28개의 U·S·N·M·E2E 적용 여부를 `system/test-matrix.yaml`에서 관리한다. critical 8개는
세 경계 테스트와 변이 probe, fresh-install E2E가 모두 있어야 하며 필수 셀이 비거나 테스트 파일에서
도구 이름을 찾지 못하면 doctor 회귀가 실패한다. 기본 회귀는 과거 생존 변이 4개만 다시 재고,
`python3 tools/test_mutation.py --full`이 비교 반전·early return·상수 변경 24개 전부를 잰다.
H1 공격 29건은 `tools/test_bypass_pins.py`가 현재 동작을 고정하며, 열린 우회는 `EXPECT_HOLE=True`로
드러낸다. 60초 예산을 지키기 위해 중복 fresh-install 표면은 관련 suite의 `--full`로 분리했다.

### `[알아둘 것]` 예정된 worker batch의 slot coverage를 terminal meta로 판정한다

근거 표지: `paper:2609.01992`, `experiment:X11`.

`python3 tools/worker_batch.py create <manifest> --slots a,b,c --prompts ...`가 실행 전에 slot과
원본 prompt SHA를 고정한다. `fresh_worker.py --batch-manifest <manifest> --slot <name>`은 manifest
SHA, slot, 원본 prompt SHA를 meta.json v2의 선택형 `batch` 필드에 기록한다. 두 인자를 쓰지 않는
기존 단일 run의 meta 필드와 4,096-byte receipt 계약은 그대로다.

`python3 tools/worker_batch.py verify <manifest> --runs <runs-dir>`는 terminal meta를 대조해 완전하면
`PASS`(exit 0), terminal 누락이면 누락 slot과 `INCONCLUSIVE_COVERAGE`(exit 2), prompt SHA 불일치나
중복 terminal이면 `FAIL`(exit 1)을 낸다. 이 도구는 worker를 실행하거나 fan-out, scheduler를 제공하지
않는다.

### `[알아둘 것]` 첫 설치 게이트가 판독 불능 출력을 실패로 닫는다

근거 표지: `paper:2609.02246`, `experiment:X12`.

`tools/test_fresh_install.sh`는 linkcheck의 종료코드 0과 정확히 하나인 정상 요약 줄을 함께
확인한다. doctor는 종료코드 0에 더해 중복 키 없는 JSON, 검사 목록과 일치하는 summary를 요구한다.
빈 출력, 중복 요약, 깨진 JSON, `FAIL 0`인데 비정상 종료한 결과는 PASS가 아니라 `측정불능` FAIL이다.
정상 설치의 표 형식은 그대로다.

### `[자동]` 메인 컨텍스트 바이트와 파도 receipt를 계측한다

근거 표지: `test:tools/test_receipts.py::test_aggregate_eight_runs_into_one_bounded_wave_receipt`.

`python3 tools/context_budget.py [전사.jsonl] --budget <bytes>`가 main-thread JSONL의 훅 주입,
worker receipt, 도구 stdout, 사용자, 모델 payload를 UTF-8 bytes로 나누고 큰 도구 호출 20개를
보여준다. 합계가 예산을 넘으면 `budget WARN`과 exit 1을 반환한다. `python3 tools/receipts.py
aggregate <run-id>...`는 최대 8개 run의 판정, 증거 경로, 미지를 한 행씩 보존한 4,096-byte 이하
receipt 하나를 만든다. 기존 인스턴스가 손으로 바꿀 파일은 없다.

## v0.6 · 2026-09-17 (스웜 파도 1+2A 통합)

### `[알아둘 것]` 설치 전 개발 트리의 NOW 게이트가 반쪽 설치를 구분한다

근거 표지: `test:tools/test_devtree_gate.py::test_unconfigured_devtree_precommit_is_not_applicable`,
`test:tools/test_devtree_gate.py::test_partial_install_without_config_fails_closed`.

config와 state 입력이 둘 다 없는 상류 개발 트리에서 direct·portable NOW 검사는 명시적 `해당없음`과
gated 0을 낸다. NOW 또는 journal은 있지만 config만 없는 반쪽 설치는 `config-absent`로 fail-close한다.
`gate.py selfcheck`는 direct와 precommit의 checker-qualified gated ID 집합을 비교하고 다르면 WARN에 두
집합을 모두 보여준다. 기존 인스턴스가 손으로 바꿀 파일은 없다.

### `[Automatic]` The release gate now measures long-lived installed-instance shape

Evidence: `experiment:w2-16-instance-shape-release-gate`.

`tools/test_instance_shape.py` builds a synthetic instance with no setup.sh or templates, tracked public state
and instance configuration, a historical Markdown symlink, and Korean user data. It runs the ENGINE regressions,
doctor, gate, pre-commit, pre-push, and English doctor in that tree, then detects all seven revived tree-shape
defects. `system/engine-inventory.txt` owns the ENGINE copy list.

### `[알아둘 것]` 공용 엔진 회귀는 설치된 인스턴스에서도 돈다

근거 표지: `test:tools/test_evidencecheck.py::test_tree_without_any_target_is_not_applicable`.

이식 실측(2026-09-17): 스웜이 킷 트리에서 만든 회귀 7개가 설치된 인스턴스에서 실패했다. 원인은
전부 "트리 모양 가정"이었다. 고친 계약: `tools/evidencecheck.py`는 대상 파일(kit-decisions·CHANGELOG·
enforcement-matrix)이 하나도 없는 트리를 해당없음(issues 0)으로 보고하고, 하나라도 있으면 나머지 부재를
`missing-file`로 낸다. `memlib.SCHEMA_CHANGES`는 언어별 문안이라 `MOTTORI_LANG=en` doctor 출력에 한글이
없다. doctor 회귀 목록은 공용 suite와 킷 전용 suite(`test_setup_migration`·`test_portability`·
`test_manifests`·`test_skill_parity`, 하나라도 없으면 FAIL)로 나뉜다. `test_memlib_journal`·`test_coherence`는
`templates/`(킷) 또는 `system/`(인스턴스)의 config로 fixture를 만들고, `test_i18n`의 영어 표면 검사는
`setup.sh`가 없는 트리에서 "해당없음"을 요약 줄에 남기고 건너뛴다. 인스턴스 쪽 `kit_sync`는 ssh git URL의
`git@host`를 개인 식별자로 보지 않는다.

### `[알아둘 것]` macOS와 Linux의 셸 차이를 회귀로 막는다

근거 표지: `test:tools/test_portability.py::test_shell_syntax`.

설치 셸은 Bash 3.2 문법만 쓰며 임시 파일을 운영체제 기본 임시 디렉토리에 만든다. pre-commit 설치는
`sha256sum`을 먼저 쓰고 `shasum`, Python 순으로 폴백하며, Git 2.36의 `git hook run`과 Git 2.31의
`--path-format` 없이 설치본을 검증한다. `tools/test_portability.py`가 금지 패턴, Bash 일반·POSIX 문법,
`shasum` 없는 PATH와 구버전 Git 명령 부재 픽스처를 검사하고 doctor 회귀 목록에도 포함된다.
지원 범위와 실기·추정 구분은 `SETUP.md`의 지원 매트릭스가 정본이다.

### `[알아둘 것]` fresh worker가 detached worktree에서 원본과 분리되어 쓸 수 있다

근거 표지: `test:tools/test_fresh_worker.py::test_worktree_patch_extracts_modified_new_and_deleted_files`.

`fresh_worker.py --worktree=head|dirty`는 run 디렉토리 아래에 detached worktree를 만들고 worker의
cwd와 `MOTTORI_INSTANCE`를 그곳으로 바꾼다. `head`는 HEAD 그대로, `dirty`는 원본의 tracked diff를
먼저 적용한다. worker 종료 뒤 수정·신규·삭제를 `patch.diff`로, 신규 경로를 `untracked.txt`로 남기고
worktree를 제거한다. meta v2에는 worktree mode·base revision·patch hash·파일 목록이, receipt에는
`patch: N files (+A/-D)`가 추가된다. 4,096-byte 상한은 그대로다.

worktree에는 local instance 파일 네 개만 복사하고 빈 `state/`를 제공한다. 복사본은 patch에 들어가지
않는다. `--write-prefix`와 `--strict-scope`는 격리된 worktree를 기준으로 검사하므로 dispatcher와 상태
logger의 동시 쓰기가 worker 위반으로 섞이지 않는다. `ask_codex.sh`는 `MOTTORI_WORKTREE=1`이면 dirty
worktree 모드를 전달한다.

### `[알아둘 것]` journal 경계와 config 경로 검증이 fail-close한다

근거 표지: `test:tools/test_state_runtime.py::test_unterminated_tail_refuses_append_without_merging`.

`parse_journal(strict=True)`는 UTF-8 BOM과 마지막 줄 개행 누락을 손상으로 거부한다. non-strict는 같은
경계를 `errors`에 남긴다. `+0900` offset은 기존 문법대로 수용하며, 사건은 timestamp 문자열이 아니라
파싱한 aware datetime으로 안정 정렬한다. config는 track canonical의 절대경로와 `..` 탈출, host·remote·
명시적 local path로 해석할 수 없는 `remote_allowlist` 항목을 거부한다. 고정 seed 생성 회귀 303건을
`tools/test_memlib_journal.py`에 두고 doctor 회귀 목록에 포함했다.

### `[자동]` 배포 도구 7개의 회귀가 doctor 기본 게이트에 들어간다

`recall.py`·`rec.py`·`hookdiag.py`·`install_hooks.sh`·`coherence.py`·`build_memory_map.py`·
`codex_root_thread.py`의 공개 경계를 임시 디렉토리와 서브프로세스로 검증하는 회귀 17개를 추가했다.
`python3 tools/doctor.py`는 새 suite 5개를 기본 회귀 목록에서 실행한다. 새 suite 합계는 이 변경 시점
실측 1.5초라 `--full` 분리 없이 매번 실행한다.

### `[자동]` worker run 영수증 원장과 7일 건전성 계기

`python3 tools/receipts.py list`가 `_private/work/runs/*/meta.json`을 사람이 훑는 한 줄/run과 합계로
보여준다. `show <id>`는 meta 요약과 bounded receipt를 재출력하고, `cost`는 런타임별 토큰 합계와
하루 단위 히스토그램을 낸다. doctor는 최근 7일 run 수·토큰·실패율을 다시 계산하며 실패율이 50%를
초과하면 warn이다. 기존 인스턴스가 손으로 바꿀 파일은 없다.

### `[자동]` doctor JSON 출력과 PreCompact 명령 효과 검사

`python3 tools/doctor.py --json`은 검사별 `name`·`status`·`detail`, 상태별 요약, 수동 확인 목록을
JSON으로 내며 텍스트 기본 출력은 그대로다. 첫 설치 게이트도 이 계약을 읽어 FAIL과 warn을 센다.
Claude와 Codex의 PreCompact 명령은 각각 임시 인스턴스에서 실행해 journal의 `컴팩션 발생` 기록까지
확인한다. 사람이 확인할 것은 명령 효과가 아니라 실제 런타임 dispatcher의 발화다. SessionStart와
PreCompact의 실제 발화는 별도 작업으로 세어 수동 목록은 4개다. `hook_canary.py --all`은 nonce 없이
런타임별 마지막 판정과 시각을 state 아래의 hook-canary.json에 남기고, doctor는 파일이 있을 때
fired/effect 표시에 반영한다.

### `[알아둘 것]` 설치 표면이 사용자 언어를 따른다

근거 표지: `test:tools/test_i18n.py::test_language_selection`.

`doctor`, `setup`, `linkcheck`, 게이트 차단문은 `MOTTORI_LANG=en|ko`를 우선하고, 미설정이면
`LC_ALL` 또는 `LANG`이 `ko`로 시작할 때 한국어, 그 밖에는 영어를 쓴다. 기존 한국어 문장은
`MOTTORI_LANG=ko`에서 유지된다. 판정과 종료코드는 바뀌지 않는다.

### `[자동]` 추적 텍스트와 규칙 강제 수준을 manifest 두 개로 검사한다

`system/review-manifest.yaml`은 추적 텍스트의 분류·소유자·소비자·의존성을 전수 기록하고,
`system/enforcement-matrix.yaml`은 규칙 원천별 경계·픽스처·우회 기록·잔여 위험을 판정한다.
`tools/test_manifests.py`가 누락·유령·미분류·fixture 경로와 ENFORCED 행의 닫힘을 검사하며 doctor
회귀 목록에도 포함된다. 새 엔진 텍스트나 doctor·훅 규칙을 추가하면 manifest도 함께 갱신한다.

### `[해야 함]` 근거 참조 계약이 게이트에 들어갔다

근거 표지: `test:tools/test_evidencecheck.py::test_gate_consumes_evidencecheck_issues_end_to_end`.
DR 맥락, CHANGELOG의 `[해야 함]`·`[알아둘 것]`, enforcement matrix의 ENFORCED 행에 근거 표지를
요구한다. `tools/evidencecheck.py`가 문법과 로컬 ID 존재를 검사하고 gate와 pre-commit이 이슈
집합을 소비한다. 표지의 내용 적합성은 독립 검토가 맡는다.
pull 뒤 `python3 tools/gate.py baseline`을 사람이 한 번 실행해 새 검사기 목록을 명시적으로 채택한다.

### `[알아둘 것]` 논문에서 킷 제안까지 가는 정본 workflow와 runtime adapter 생성기

근거 표지: `test:tools/test_skill_parity.py::test_both_runtime_adapters_embed_exact_canonical_bytes`.

`system/skills/paper-to-kit.md` v1이 수집, 논문별 카드, 독립 교차 대조, 근거 표지와 예약 실험을
가진 제안, 사람 판정 대기를 한 경로로 고정한다. workflow의 쓰기는 실행 디렉터리 안 분석 산출물뿐이고
킷 파일 수정은 0건이다. Claude command는 정본에서 생성된다. Codex skill 설치 경로는 아직 고정하지
않았으며 `python3 tools/skill_adapters.py codex <출력할-SKILL.md>`처럼 대상 경로를 명시한다.
`tools/test_skill_parity.py`가 두 runtime adapter에 정본 bytes가 그대로 들어가는지, 생성물이 낡으면
검사가 실패하는지 확인한다.

## v0.5 · 2026-09-17

### `[알아둘 것]` 낯선 첫 설치가 실제로 통과한다 (`tools/test_fresh_install.sh`)

근거 표지: `test:tools/test_install_checks.py::test_linkcheck_exit_codes_and_pending`.

v0.4를 임시 디렉토리에 클론해 README대로 돌리자 `bash setup.sh`가 tty 없이 **아무 출력 없이 exit 1** 했고
(`read`가 EOF를 만나 set -e), 인자를 줘도 첫 doctor가 FAIL 4(codex 미신뢰·깨진 참조 2·회귀 12/13·검사 기록 없는
새 파일)였다. 이번 판은 그 경로를 검사기로 만들었다: `bash tools/test_fresh_install.sh`가 공백 든 임시 경로에
클론하고 작업트리 변경을 덮은 뒤 setup(비대화형·인자 없음) → 훅 설치 → linkcheck → doctor → 회귀 5종 → setup
재실행 순으로 재서 PASS/FAIL을 낸다. 엔진을 고친 뒤 이걸 돌린다. 고친 것: setup.sh가 tty 없으면 기본값으로
진행하고 인쇄한다 · `--force` 재실행은 기존 config의 이름·context를 기본값으로 쓴다(이전엔 비대화형이면 personal
인스턴스가 work로 뒤집혔다) · 첫 local 사건을 기록해 `_private/state/NOW.md`를 첫날부터 만든다 · 순서는 기준선 →
linkcheck → doctor(linkcheck 통과 기록이 doctor의 인증서다) · 쓰기 전에 public·private journal을 strict로 preflight
한다(마지막 줄 개행 포함; 실패하면 아무것도 안 바꾼다) · `pwd -P`로 물리 경로를 export한다(macOS `/var` 링크 아래에서
doctor의 ROOT 불일치) · `test_setup_migration.py` 픽스처가 부모의 `MOTTORI_INSTANCE`를 상속하지 않는다.

### `[알아둘 것]` 실패가 조용히 성공으로 읽히던 경로 넷을 닫았다 (독립 결함 감사 17건 반영)

근거 표지: `test:tools/test_install_checks.py::test_gate_check_blocks_when_measure_raises`.

`setup.sh`는 doctor·기준선이 실패하면 안내문을 끝까지 인쇄한 뒤 exit 1 한다(이전엔 FAIL을 보여주고도 0).
`linkcheck.py` normal mode는 broken이 있으면 exit 1이다(`--issues`는 그대로 0). Stop 게이트는 검사기 자신이
예외를 내면 무출력 0이 아니라 차단 JSON을 내고 pending을 남기며, UserPromptSubmit 회수 경로는 경고 JSON을
낸다(후방선 fail-closed). doctor의 linkcheck 인증서 해시가 공백 든 md 파일명에서 linkcheck와 갈라지던 것을
줄 단위로 고쳤다. 그 밖에: setup 전 doctor의 `훅 · claude 명령 유효성`은 고장이 아니라 "setup 전"으로 warn ·
`c_git`은 2.36 미만을 FAIL(업그레이드로 고칠 수 있는 결함) · 새 인스턴스 NOW의 개인 정본이 `None`으로 찍히던 것
정정 · CHECKLIST의 게이트 시험은 일회용 클론에서 하도록 바꿈(원본에서 게이트가 뚫리면 실제 커밋이 남았다).
회귀 `tools/test_install_checks.py`가 이 계약을 고정한다(doctor의 회귀 목록에 포함). 독립 검토 2회(Codex)의
FIX 판정을 반영했고, 남긴 것은 실제 Git 2.35 바이너리·Python 3.8 실기·shasum 없는 Linux·Claude/Codex 훅의
실제 발화(fired/effect)로, 전부 이 머신에서 재현할 수 없는 것들이다.

### `[알아둘 것]` doctor·linkcheck·now.py check의 늑대소년 3건 제거

근거 표지: `test:tools/test_install_checks.py::test_doctor_codex_armed_and_git_version`.

`훅 · codex armed`의 "미신뢰"는 사람이 codex를 한 번 띄워야만 풀리므로 FAIL이 아니라 warn+할 일이다. 상류 사본
(setup 전)의 linkcheck는 setup이 만드는 7개 경로(config·인스턴스 문서 셋·두 NOW·게이트 기준선)를 BROKEN이 아니라
`PENDING`으로 따로 센다 (`broken: 0 · pending(setup 전): N`); setup 뒤에는 같은 참조가 없으면 BROKEN이다.
`now.py check`의 드라이브 인박스 검사는 개인 장비 어댑터(`drive_inbox.py`)가 없으면 경고 없이 건너뛴다(이전엔 킷
클론마다 "인박스 검사 실패" 경고). 킷 드리프트 검사는 `fresh_worker.py` 각인 줄을 정규화해 비교한다.

### `[알아둘 것]` 철학 한 줄과 LICENSE(MIT)

근거 표지: `decision:KIT-DR-012`.

README 첫 절에 소유자가 정한 철학이 들어갔다: 사람의 주의가 가장 비싼 자원, 토큰이 가장 싼 자원, 사람은 무한
스레드 하나만 상대한다. 그 아래 규칙 둘(판정은 영수증으로만 · 통과와 원인은 따로 검증한다)은 KIT-DR-012.
LICENSE는 MIT다. 독립 문서 감사가 "라이선스 검사하는 조직에서는 사용 자체가 막힌다"고 지적했다.

### `[알아둘 것]` 문서가 코드와 맞는다 (독립 문서 감사 39건 반영)

근거 표지: `experiment:documentation-audit-20260917`.

SETUP: setup이 만드는 파일 전체 목록과 되돌리기 목록, git 2.36·macOS/Linux 전제, FAIL·warn·`--`의 뜻, Codex 훅
신뢰 승인 단계, `git pull` 뒤 재실행 순서(§5a), 트랙 등록 뒤 `render` 필요. README: 명령 넷 + 영어 quickstart 한 문단,
훅·검사 개수 정정. CHECKLIST: 훅은 프로젝트 수준, work 인스턴스의 origin은 allowlist에 등록됨, 변경 관측 matcher
위치. 소유자 이름은 킷 전체에서 역할어(소유자)로 치환됐다(`kit_sync`가 조사까지 변환하고 SCAN이 이름 단독을 잡는다).

## v0.4 · 2026-09-16

### `[자동]` fresh worker meta v2: kit_rev·kit_dirty·harness_sha256·usage·read_scope·scope

`meta.json` schema_version 2. 값이 없으면 null. receipt(4,096 byte)는 `scope:` 한 줄만 늘고 나머지는
그대로. 비교는 `harness_sha256`이 같은 run끼리만 한다. 정체 필드: `kit_rev`(`KIT_REV_EMBEDDED`가 각인돼
있으면 그 값, 아니면 엔진 리포 HEAD; `kit_rev_source`가 어느 쪽인지 말한다), `repo_rev`(실행 사본이 든 리포의
HEAD), `kit_dirty`(엔진 디렉토리 tools/ 범위 porcelain), `engine_sha256`(fresh_worker.py+memlib.py 내용 해시, git 무관),
`agents_sha256`(워커가 읽는 AGENTS.md). **인스턴스로 복사할 때는 `bash tools/sync_engine.sh <instance>`를 쓴다**: `KIT_REV_EMBEDDED`(킷 HEAD)·`KIT_SYNC_DIRTY`(킷 tools/가
동기화 시점에 dirty였나)·`KIT_SYNC_ENGINE_SHA256`(복사 직후 사본의 정규화 엔진 해시, 목적지 기준선)·`KIT_SYNC_SOURCE_SHA256`(킷 쪽에서 계산한 복사 파일 manifest 해시)을 각인한다.
각인 대상 줄이 정확히 한 번씩 없으면 실패하고, 각인 뒤 사본을 다시 import해 값과 `matches_copy=True`를 검증한다(독립 리뷰 R11). `engine_sha256`은 각인 줄을 빼고
계산하므로 킷 파일과 각인된 사본이 같은 코드면 같은 값이고, `kit_sync.matches_copy`가 동기화 뒤 사본이 손대졌는지 말한다
(독립 리뷰 R5, 2차). 안 하면 인스턴스 HEAD가 킷 rev로 잘못 라벨된다.
설계·worked example·anchor는 원본 인스턴스의 private 작업장(papers-2026-09-13-kit, 설계 문서 design-fresh-worker-receipt-v2)에 있다.

### `[알아둘 것]` worker 결과의 주장에는 출처 경로가 붙는다

근거 표지: `paper:2609.06702`.

common 계약에 한 줄이 늘었다: 출처 없는 주장은 remaining unknowns로 내려간다 (2609.06702 App. F.2).
기존 발주문은 그대로 돈다.

### `[알아둘 것]` `--write-prefix DIR`(반복 가능)로 Codex 워커의 write-set을 검사한다

근거 표지: `paper:2609.04170`.

실행 전후 workspace 스냅샷(lstat: kind·size·mtime_ns·ctime_ns·mode, 디렉터리 포함, `.git`·run-record 트리 제외)을
비교해 prefix 밖 변경과 symlink 탈출을 `scope.violations`에 기록한다. prefix 아래 **기존** symlink도 밖을 가리키면
위반이다(쓰기가 스냅샷 밖으로 새는 문). 같은 크기로 쓰고 mtime을 되돌려도 ctime이 잡는다(독립 리뷰 R1·R2). prefix 아래 파일의 링크 수가 스냅샷이 보는 같은 inode 수보다
많으면 workspace 밖에 별명이 있는 hardlink라 위반이다(R8). 없는 prefix는 baseline 전에 디스패처가 만들어 그 생성이 위반으로
잡히지 않게 한다(R9). prefix의 대소문자 보정은 파일시스템이 실제로 그 표기를 같은 항목으로 푸는 경우에만 한다(R10). **기본은 기록만**(run status 불변). `--strict-scope`를 함께 주면 위반 시 status
`scope_violation`(wrapper_exit 4, 런타임 자체 exit보다 우선하며 `process_exit`는 meta에 남는다, R3). 사후 탐지만이고 rollback·삭제는 없다.
호출자: 배포본의 `ask_codex.sh`는 `MOTTORI_WRITE_PREFIX` 환경변수를 통과시킨다(R4). 원본 인스턴스의 확장인 정원 주기 스크립트(킷에 안 실림)는 검토 워커에 `--write-prefix "$DIR"`를 넘긴다. prefix를 안 주면 write-set만 기록하고
status는 `unchecked`다. 이유: 2026-09-16 실 카나리에서 위반 2건이 전부 동시 쓰기(디스패처의 문서 편집,
인스턴스의 `state/.tool-runs.log`)였다. 동시 writer와 워커를 가르려면 worktree 격리가 필요하다(다음 버전 후보).
DR-049 closeout의 "allowlist·denylist 검사기" 구체화 (2609.04170 §2.2·§3.6).

### `[알아둘 것]` 규약 문서에 근거 행 8줄

근거 표지: `paper:2609.09134`.

rituals(컴팩션 뒤 절차 위치 1줄), WORKING-WITH-AI(§4 present/effective, §5 발주 형태 넷, §9 국소 correction),
README(Why는 실측 우선), PRD-session-memory §3.8(토폴로지 비목표), debate/README(파일 목록은 생성물만).
전부 논문 식별자와 DR-053이 붙어 있다. 인스턴스 사본에도 같은 줄이 있다.

## v0.3 · 2026-08-29

### `[알아둘 것]` 공통 지시 정본이 `AGENTS.md` 하나로 바뀌었다

근거 표지: `decision:KIT-DR-007`.

`CLAUDE.md`는 이제 exact `@AGENTS.md` import다. 인스턴스 규약이 필요하면 이전처럼
system/instance-rules.md에 쓴다. 업스트림 `AGENTS.md`나 `CLAUDE.md`에 직접 쓴 내용은 pull 전에
인스턴스 파일로 옮겨라.

### `[알아둘 것]` fresh 발주의 프롬프트는 workspace 안에 둔다

근거 표지: `test:tools/test_fresh_worker.py::test_prompt_boundaries_fail_closed`.

`ask_codex.sh`의 기본 경로가 bounded worker로 바뀌었다. `/tmp`나 symlink의 프롬프트는 거부한다.
`system/debate/_p_*.md`처럼 workspace 안의 무시되는 파일을 쓴다.

### `[자동]` 광역 작업 trace를 master context에서 격리한다

`fresh_worker.py`는 Claude read-only 또는 Codex workspace-write의 ephemeral run을 만들고, 전체
trace는 `_private/work/runs/`에 보관한다. 호출자에게는 bounded receipt만 반환한다.
`recall.py sessions`도 최신 40개만 기본 표시하며 `--all`일 때만 전량을 낸다.

### `[알아둘 것]` 외부 문안은 본문 전에 두 줄을 보인다

근거 표지: `decision:KIT-DR-008`.

에이전트가 발신 산출물을 쓰기 전에 독자·승인자·목적함수와 실제 근거 경로를 먼저 보여주고 바로
계속한다. 승인 단계가 아니다. 담백한 문체는 새 스킬이나 길이 제한이 아니라 `system/rituals.md`의
10건 파일럿으로 들어갔다.

## v0.2 · 2026-08-24

### `[해야 함]` config schema v1 → v2

근거 표지: `decision:KIT-DR-005`.

system/memory-config.json에 `instance` 블록과 `schema_version`이 필요하다.

```json
{
  "schema_version": 2,
  "instance": {
    "name": "이 인스턴스 이름",
    "context": "work",
    "remote_allowlist": ["클론해 온 origin URL"]
  }
}
```

**안 넣으면 조용히 다르게 동작한다.** `context`가 없으면 밸브 검사가 `personal`로 간주하고
원격을 아예 안 본다. 회사 인스턴스에서 그건 밸브가 꺼진 상태다.
`python3 tools/doctor.py`의 `엔진 · config 스키마` 항목이 FAIL로 알려준다.

### `[해야 함]` 규약 문서가 엔진/인스턴스 쌍으로 갈라졌다

근거 표지: `decision:KIT-DR-004`.

지금까지 `system/rituals.md`와 system/decisions.md에 직접 쓴 게 있다면 옮겨야 한다.
그대로 두면 다음 pull에서 충돌하거나 되돌아간다.

| 엔진 (pull이 덮는다) | 여기로 옮긴다 (git 밖) |
|---|---|
| `system/rituals.md` | system/rituals.local.md |
| `system/kit-decisions.md` (신설) | system/decisions.md |
| `CLAUDE.md` 상시 코어 | system/instance-rules.md |

`setup.sh`를 다시 돌리면(`--force` 불필요) 없는 파일만 씨앗에서 만들어 준다.
기존 `decisions.md`에 킷 DR과 인스턴스 DR이 섞여 있으면 킷 DR(001~003)을 지운다.
그 내용은 `system/kit-decisions.md`에 있다.

### `[알아둘 것]` `.gitignore`가 기본 거부로 바뀌었다

근거 표지: `decision:KIT-DR-002`.

이전에는 `state/`와 `_private/`만 무시했다. 그래서 **평범한 경로의 회사 자료가 그냥 커밋됐다**
(company/tracker.md 같은 것). 지금은 전부 무시하고 엔진 파일만 되살린다.

작업 문서를 만들면 이제 기본으로 git 밖이다. 그게 의도다.
**뒤집어 말하면 그 문서들은 이 리포로 백업되지 않는다** — 별도 백업이 필요하다.

### `[알아둘 것]` 전사 경로 유도 규칙이 바뀌었다

근거 표지: `experiment:transcript-path-derivation-20260824`.

`~/.claude/projects` 디렉토리명 규칙을 `[/_]` → `-`로 알고 있었는데 실제로는
`[^A-Za-z0-9-]` → `-`다. 공백이나 점이 든 경로(`~/My Work/kit`, `~/work.v2`)에 클론했다면
이전 판에서는 `recall`이 조용히 0건을 반환했다. 지금은 맞는다.

### `[자동]` doctor 검사가 21개에서 29개로

추가된 것: 링크 무결성·정합성의 **결과 파싱** (이전엔 종료코드만 봤다) · 회귀 픽스처 실행 ·
Codex 훅 3종 · 추적 심볼릭 링크 · config 스키마 · 업스트림 동기 · 킷 드리프트.

### `[자동]` 밸브 수리 4건

`.gitignore` 기본 거부 · ignore 규칙 부재 검출 · allowlist를 부분 문자열이 아닌 host 기준 비교 ·
`recall` 인스턴스 격리(경로 접두 충돌·cwd 미기록·상대 경로 전부 차단).

---

## v0.1 · 2026-08-24

첫 추출. 원본 워크스페이스에서 엔진만 떼어냈다.

- 도구 14개 (memlib · now · recall · rec 핵심 넷 + 검사기 + Codex 발주 + doctor)
- 규약 20문서 (PRD 둘 · rituals · 렌즈 13종 · deep-pass · WORKING-WITH-AI)
- 훅 5종 (Claude 3 + Codex 2), 전부 경로 상대
- 인스턴스 배선을 system/memory-config.json으로 분리

## 기록 근거 연결

이 파일의 명령형 문장은 새 규칙이 아니라 해당 릴리스에서 기존 인스턴스가 해야 할
마이그레이션을 적은 것이다. Why는 각 항목의 근거 표지, KIT-DR, 테스트 경로에 있으며,
개수 변화는 해당 릴리스 시점의 등록 목록을 세어 보여주는 이력값이다.
