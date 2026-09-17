# mottori-kit 구조 리뷰

검토일: 2026-09-17
범위: 현재 통합 트리에서 `git ls-files`가 반환한 96개 추적 파일 전체와 그 파일들이 읽거나 만드는 인스턴스 경로
방법: 추적 파일 집합, 정적 경로 참조, import와 subprocess, 훅 등록, 테스트 등록을 대조했다. manifest의 경로 일치는 실제 `git ls-files -z` 결과로 검사한다 (`tools/test_manifests.py:47-70`, `tools/test_manifests.py:103-110`).

## 1. 결론

상태 ledger, gate, fresh worker는 깊은 모듈이다. `now.py`의 CLI 뒤에 public/private 라우팅, 잠금,
원자적 projection과 rollback이 있고 (`tools/now.py:445-598`), gate는 여러 검사기의 안정 이슈 집합만
소비하며 (`tools/gate.py:119-188`), worker는 격리 실행과 scope 판정 뒤 4,096-byte receipt를 반환한다
(`tools/fresh_worker.py:711-744`, `tools/fresh_worker.py:889-914`).

통합 트리는 검토와 근거를 새 모듈로 분리했다. review manifest는 추적 text 집합을 재생성하고 사람의
분류를 보존하며 (`tools/manifest_build.py:32-111`), matrix 검사는 규칙 원점과 fixture를 대조한다
(`tools/test_manifests.py:139-201`). evidencecheck는 표지 문법, 로컬 ID, 필수 위치를 검사하되 외부
`paper:`와 `experiment:`는 차단하지 않고 REVIEW로 남긴다 (`tools/evidencecheck.py:74-90`,
`tools/evidencecheck.py:157-206`). paper-to-kit은 제안 전용 workflow와 runtime adapter를 분리하고 exact
canonical bytes를 검사한다 (`system/skills/paper-to-kit.md:3-9`, `tools/test_skill_parity.py:62-96`).

남은 구조 위험은 네 가지다.

1. sync 대상은 Python `SYNC_FILES`와 셸 복사 목록에 중복 선언된다 (`tools/fresh_worker.py:45`, `tools/sync_engine.sh:13-18`).
2. doctor의 ledger 검사는 `rec.py check` 종료코드를 보지 않아 crash나 출력 drift를 0건으로 읽을 수 있다 (`tools/doctor.py:650-659`).
3. release 전체 19개 Python suite와 doctor가 직접 소유한 15개 suite의 목록이 다르다 (`tools/doctor.py:583-622`, `tools/test_fresh_install.sh:91-95`).
4. memory map은 생성 fixture가 생겼지만 구조 설명 자체는 여전히 상수다 (`tools/build_memory_map.py:56-99`, `tools/test_coherence.py:73-92`).

구조적 orphan은 `tools/eval_recall.py` 한 개다. 자기 CLI 외 README, doctor, 회귀 suite에서 호출되지
않는다 (`tools/eval_recall.py:19-37`, `tools/doctor.py:583-622`). runtime convention 파일,
`state/.gitkeep`, `LICENSE`는 코드 호출이 없어도 각각 runtime, repository shape, 법적 metadata라는
consumer가 있으므로 orphan으로 세지 않는다.

## 2. 모듈 지도

| module | 좁은 interface | 숨기는 책임 | 주요 consumer | 검증과 남은 구멍 |
|---|---|---|---|---|
| 상태 ledger | `now.py log/render/check` | visibility 라우팅, journal append, 두 NOW, lock/rollback | hooks, gate, operator | transaction fixture가 있다 (`tools/test_state_runtime.py:533-1054`). |
| 회상 | `recall.py sessions/find` | Claude/Codex source 발견, cwd 격리, authored 필터, ranking | AGENTS, slash command, doctor | Codex cwd와 injection fixture가 있다 (`tools/test_recall.py:77-109`); Claude parser와 ranking 동률은 별도 fixture가 없다. |
| 개인 원장 | `rec.py new/find/check/audit` | fact schema, origin audit, hotset, snapshot | AGENTS, coherence, doctor | new-find-check-audit는 검증한다 (`tools/test_rec.py:27-46`); snapshot ring과 중간 실패는 미검증이다. |
| 훅 | runtime JSON과 installed pre-commit | SessionStart, PreCompact, gate lifecycle | Claude, Codex, Git | runtime와 installer fixture가 분리돼 있다 (`tools/test_hook_runtime.py:16-235`, `tools/test_install_hooks.py:39-99`). |
| gate | `baseline/status/check/precommit` | checker issue set, baseline, lock/token, extracted index | hooks, pre-commit | checker crash와 index tree를 검사한다 (`tools/test_install_checks.py:181-226`, `tools/test_hook_runtime.py:235-291`). |
| worker | `fresh_worker.py <runtime> <prompt>` | fresh runtime, run record, usage, write scope, receipt | operator, ask_codex | worktree와 scope fixture가 있다 (`tools/test_fresh_worker.py:454-717`). |
| 영수증 | `receipts.py list/show/cost` | private run meta 집계와 bounded rendering | operator, doctor | list/show/cost/threshold fixture가 있다 (`tools/test_receipts.py:91-203`). |
| doctor | 단일 PASS/FAIL/WARN/SKIP 보고 | runtime, wiring, hooks, tools, valves, regressions | setup, operator | 37개 자동 check와 4개 manual을 등록한다 (`tools/doctor.py:979-1027`); ledger 판정은 fail-open 가능하다. |
| setup/release | `setup.sh`, `test_fresh_install.sh` | instance seed, migration, hooks, doctor, full regressions, rerun | 새 instance operator | full regressions와 setup rerun을 실행한다 (`tools/test_fresh_install.sh:91-104`). |
| review manifest | `manifest_build.py`, `test_manifests.py` | 96개 text inventory, 분류 보존, rule/source coverage | reviewer, doctor | missing/ghost와 matrix 원점을 검사한다 (`tools/test_manifests.py:73-110`, `tools/test_manifests.py:194-202`). |
| 근거 계약 | `evidencecheck.py --issues` | marker syntax, local resolver, required placement, REVIEW | gate, pre-commit, reviewer | local missing과 external REVIEW를 분리한다 (`tools/test_evidencecheck.py:69-124`). |
| paper workflow | canonical workflow와 generated adapter | cards, crosscheck, proposal-only boundary, human gate | Claude/Codex adapter | schema 교차 fixture와 exact-byte parity가 있다 (`tools/test_skill_parity.py:32-96`). |

## 3. 결합과 권위

```text
event -> now.py -> memlib visibility -> public/private journal -> two NOW -> SessionStart
transcripts -> recall.py -> cwd/authored filters -> bounded slice
facts -> rec.py -> check/audit -> hotset/snapshots

edit -> gate -> linkcheck + now check + evidencecheck -> issue-set delta -> pass/block
prompt -> fresh_worker -> private run record -> receipts.py -> bounded receipt / doctor metric

git ls-files -> manifest_build -> review-manifest -> test_manifests
DR/CHANGELOG/matrix -> evidencecheck -> blocking issues + nonblocking REVIEW
paper list -> canonical workflow -> cards/crosscheck/proposals -> human judgment
```

권위는 주장 종류별로 갈린다.

| 주장 | 정본 | 파생물 | 근거 |
|---|---|---|---|
| 현재 상태 | public NOW + local overlay | SessionStart context | `AGENTS.md:26-31`, `tools/now.py:648-696` |
| 사건 | public/private monthly journal | NOW projection | `system/PRD-session-memory.md:85-99`, `tools/now.py:289-359` |
| 개인 사실 | private fact files | hotset/snapshot | `tools/rec.py:23-33`, `tools/rec.py:99-130` |
| 킷 결정 | `system/kit-decisions.md` | README/CHANGELOG 요약 | `system/kit-decisions.md:1-11` |
| 근거 표지 문법 | `system/evidence-schema.md` | checker 구현과 workflow 표지 | `system/evidence-schema.md:7-30`, `tools/evidencecheck.py:12-23` |
| review 대상 집합 | `git ls-files`의 text 파일 | `system/review-manifest.yaml` | `tools/manifest_build.py:32-51`, `tools/test_manifests.py:47-70` |
| workflow 의미 | `system/skills/paper-to-kit.md` | Claude/Codex adapter | `tools/skill_adapters.py:17-63` |
| worker 실행 | private `meta.json`과 stream/result | stdout receipt | `tools/fresh_worker.py:707-744` |

public/private 경계는 default deny Git allowlist (`.gitignore:16-57`), journal public-track allowlist
(`tools/memlib.py:310-337`), transcript cwd filter (`tools/recall.py:62-101`), worker private run record
(`tools/fresh_worker.py:197-205`)의 네 층이다. `REPORT.md` 같은 실행 산출물은 engine allowlist에 없다
(`.gitignore:16-33`).

## 4. 추적 파일 전수 inventory

아래 96행은 현재 `git ls-files`와 정확히 같은 집합이다. kind, owner, consumer의 기계 정본은
`system/review-manifest.yaml`이며, test는 missing과 ghost를 양방향 비교한다
(`tools/test_manifests.py:73-110`). 직접 경로 참조가 없는 convention 파일도 consumer를 명시했다.

| 추적 파일 | kind / owner | consumer | 현재 파일 근거 |
|---|---|---|---|
| `.claude/commands/dossier.md` | tool / kit | human, Claude | (`.claude/commands/dossier.md:1`) |
| `.claude/commands/garden.md` | tool / kit | human, Claude | (`.claude/commands/garden.md:1`) |
| `.claude/commands/now.md` | tool / kit | human, Claude | (`.claude/commands/now.md:1`) |
| `.claude/commands/paper-to-kit.md` | tool / kit | human, Claude | (`.claude/commands/paper-to-kit.md:1`) |
| `.claude/commands/recall.md` | tool / kit | human, Claude | (`.claude/commands/recall.md:1`) |
| `.claude/settings.json` | hook / kit | Claude, tool | (`.claude/settings.json:1`) |
| `.codex/hooks.json` | hook / kit | Codex, tool | (`.codex/hooks.json:1`) |
| `.gitignore` | rule / kit | human, Git/tool | (`.gitignore:1`) |
| `AGENTS.md` | rule / kit | human, Claude, Codex | (`AGENTS.md:1`) |
| `CHANGELOG.md` | evidence / kit | human, Claude, Codex | (`CHANGELOG.md:1`) |
| `CHECKLIST.md` | rule / kit | human, agents | (`CHECKLIST.md:1`) |
| `CLAUDE.md` | rule / kit | Claude | (`CLAUDE.md:1`) |
| `LICENSE` | evidence / kit | human/legal tool | (`LICENSE:1`) |
| `README.md` | evidence / kit | human, agents | (`README.md:1`) |
| `SETUP.md` | rule / kit | human, agents | (`SETUP.md:1`) |
| `setup.sh` | tool / kit | human, setup tests | (`setup.sh:1`) |
| `state/.gitkeep` | generated / kit | Git checkout | (`.gitignore:53-55`) |
| `system/PRD-info-architecture.md` | rule / kit | human, agents | (`system/PRD-info-architecture.md:1`) |
| `system/PRD-session-memory.md` | rule / kit | human, agents | (`system/PRD-session-memory.md:1`) |
| `system/WORKING-WITH-AI.md` | rule / kit | human, agents | (`system/WORKING-WITH-AI.md:1`) |
| `system/debate/README.md` | rule / kit | human, agents | (`system/debate/README.md:1`) |
| `system/deep-pass.md` | rule / kit | human, agents | (`system/deep-pass.md:1`) |
| `system/enforcement-matrix.md` | evidence / kit | human, agents, tool | (`system/enforcement-matrix.md:1`) |
| `system/enforcement-matrix.yaml` | generated / kit | human, agents, tool | (`system/enforcement-matrix.yaml:1`) |
| `system/evidence-schema.md` | rule / kit | human, agents, tool | (`system/evidence-schema.md:1`) |
| `system/kit-decisions.md` | rule / kit | human, agents | (`system/kit-decisions.md:1`) |
| `system/lenses/README.md` | rule / kit | human, agents | (`system/lenses/README.md:1`) |
| `system/lenses/ergodic.md` | rule / kit | human, agents | (`system/lenses/ergodic.md:1`) |
| `system/lenses/feedback-loop.md` | rule / kit | human, agents | (`system/lenses/feedback-loop.md:1`) |
| `system/lenses/fence.md` | rule / kit | human, agents | (`system/lenses/fence.md:1`) |
| `system/lenses/feynman.md` | rule / kit | human, agents | (`system/lenses/feynman.md:1`) |
| `system/lenses/incentive.md` | rule / kit | human, agents | (`system/lenses/incentive.md:1`) |
| `system/lenses/inversion.md` | rule / kit | human, agents | (`system/lenses/inversion.md:1`) |
| `system/lenses/isomorphism.md` | rule / kit | human, agents | (`system/lenses/isomorphism.md:1`) |
| `system/lenses/jensen.md` | rule / kit | human, agents | (`system/lenses/jensen.md:1`) |
| `system/lenses/ledger.md` | rule / kit | human, agents | (`system/lenses/ledger.md:1`) |
| `system/lenses/limits.md` | rule / kit | human, agents | (`system/lenses/limits.md:1`) |
| `system/lenses/marginal.md` | rule / kit | human, agents | (`system/lenses/marginal.md:1`) |
| `system/lenses/mirror.md` | rule / kit | human, agents | (`system/lenses/mirror.md:1`) |
| `system/lenses/silence.md` | rule / kit | human, agents | (`system/lenses/silence.md:1`) |
| `system/person-ledger.md` | rule / kit | human, agents | (`system/person-ledger.md:1`) |
| `system/review-manifest.yaml` | generated / kit | human, agents, tool | (`system/review-manifest.yaml:1`) |
| `system/reviews/architecture.md` | evidence / kit | human, agents | (`system/reviews/architecture.md:1`) |
| `system/rituals.md` | rule / kit | human, agents | (`system/rituals.md:1`) |
| `system/skills/paper-to-kit.md` | rule / kit | human, agents, tool | (`system/skills/paper-to-kit.md:1`) |
| `templates/decisions.md` | template / kit | setup, human | (`templates/decisions.md:1`) |
| `templates/instance-rules.md` | template / kit | setup, human | (`templates/instance-rules.md:1`) |
| `templates/memory-config.json` | template / kit | setup, memlib | (`templates/memory-config.json:1`) |
| `templates/rituals.local.md` | template / kit | setup, human | (`templates/rituals.local.md:1`) |
| `tools/ask_codex.sh` | tool / kit | human, Codex | (`tools/ask_codex.sh:1`) |
| `tools/build_memory_map.py` | tool / kit | human | (`tools/build_memory_map.py:1`) |
| `tools/codex_root_thread.py` | tool / kit | ask_codex | (`tools/codex_root_thread.py:1`) |
| `tools/coherence.py` | tool / kit | doctor, human | (`tools/coherence.py:1`) |
| `tools/diarize.py` | tool / kit | transcribe, human | (`tools/diarize.py:1`) |
| `tools/doctor.py` | tool / kit | setup, human | (`tools/doctor.py:1`) |
| `tools/eval_recall.py` | tool / kit | manual CLI only | (`tools/eval_recall.py:1`) |
| `tools/evidencecheck.py` | tool / kit | gate, human | (`tools/evidencecheck.py:1`) |
| `tools/fresh_worker.py` | tool / kit | human, ask_codex | (`tools/fresh_worker.py:1`) |
| `tools/gate.py` | tool / kit | hooks, pre-commit | (`tools/gate.py:1`) |
| `tools/hook_canary.py` | tool / kit | doctor, human | (`tools/hook_canary.py:1`) |
| `tools/hookdiag.py` | tool / kit | doctor, canary | (`tools/hookdiag.py:1`) |
| `tools/i18n.py` | tool / kit | tools | (`tools/i18n.py:1`) |
| `tools/install_hooks.sh` | tool / kit | setup, human | (`tools/install_hooks.sh:1`) |
| `tools/linkcheck.py` | tool / kit | gate, doctor | (`tools/linkcheck.py:1`) |
| `tools/manifest_build.py` | tool / kit | reviewer | (`tools/manifest_build.py:1`) |
| `tools/memlib.py` | tool / kit | state/recall tools | (`tools/memlib.py:1`) |
| `tools/now.py` | tool / kit | hooks, human | (`tools/now.py:1`) |
| `tools/portrait.py` | tool / kit | doctor, human | (`tools/portrait.py:1`) |
| `tools/precommit-hook.sh` | hook / kit | Git | (`tools/precommit-hook.sh:1`) |
| `tools/rec.py` | tool / kit | human, coherence | (`tools/rec.py:1`) |
| `tools/recall.py` | tool / kit | human, agents | (`tools/recall.py:1`) |
| `tools/receipts.py` | tool / kit | human, doctor | (`tools/receipts.py:1`) |
| `tools/skill_adapters.py` | tool / kit | Claude/Codex packaging | (`tools/skill_adapters.py:1`) |
| `tools/sync_engine.sh` | tool / kit | human | (`tools/sync_engine.sh:1`) |
| `tools/test_coherence.py` | tool / kit | regression | (`tools/test_coherence.py:1`) |
| `tools/test_doctor_json.py` | tool / kit | regression | (`tools/test_doctor_json.py:1`) |
| `tools/test_evidencecheck.py` | tool / kit | regression | (`tools/test_evidencecheck.py:1`) |
| `tools/test_fresh_install.sh` | tool / kit | release gate | (`tools/test_fresh_install.sh:1`) |
| `tools/test_fresh_worker.py` | tool / kit | regression | (`tools/test_fresh_worker.py:1`) |
| `tools/test_hook_runtime.py` | tool / kit | regression | (`tools/test_hook_runtime.py:1`) |
| `tools/test_hookdiag.py` | tool / kit | regression | (`tools/test_hookdiag.py:1`) |
| `tools/test_i18n.py` | tool / kit | regression | (`tools/test_i18n.py:1`) |
| `tools/test_install_checks.py` | tool / kit | regression | (`tools/test_install_checks.py:1`) |
| `tools/test_install_hooks.py` | tool / kit | regression | (`tools/test_install_hooks.py:1`) |
| `tools/test_manifests.py` | tool / kit | regression | (`tools/test_manifests.py:1`) |
| `tools/test_memcheck.py` | tool / kit | regression | (`tools/test_memcheck.py:1`) |
| `tools/test_memlib_journal.py` | tool / kit | regression | (`tools/test_memlib_journal.py:1`) |
| `tools/test_portability.py` | tool / kit | regression | (`tools/test_portability.py:1`) |
| `tools/test_rec.py` | tool / kit | regression | (`tools/test_rec.py:1`) |
| `tools/test_recall.py` | tool / kit | regression | (`tools/test_recall.py:1`) |
| `tools/test_receipts.py` | tool / kit | regression | (`tools/test_receipts.py:1`) |
| `tools/test_setup_migration.py` | tool / kit | regression | (`tools/test_setup_migration.py:1`) |
| `tools/test_skill_parity.py` | tool / kit | regression | (`tools/test_skill_parity.py:1`) |
| `tools/test_state_runtime.py` | tool / kit | regression | (`tools/test_state_runtime.py:1`) |
| `tools/transcribe.py` | tool / kit | human | (`tools/transcribe.py:1`) |
| `tools/wf_gardener.js` | tool / kit | garden command | (`tools/wf_gardener.js:1`) |

## 5. 중복, 모순, 검사 공백

| 구분 | 현재 사실 | 판정 |
|---|---|---|
| sync inventory | source hash 목록과 실제 copy loop가 따로 있다 (`tools/fresh_worker.py:45`, `tools/sync_engine.sh:13-18`). | 단일 authority와 temp-instance rollback fixture가 필요하다. |
| doctor 중복 | `c_tools_run`이 linkcheck/coherence를 실행하고 전용 check가 다시 실행한다 (`tools/doctor.py:524-580`). | 실행 가능성과 결과 판정을 structured probe 하나로 합칠 후보이다. |
| release suite 목록 | doctor는 15개 suite를 직접 열거하고 fresh-install은 glob으로 19개 전부를 돈다 (`tools/doctor.py:589-622`, `tools/test_fresh_install.sh:91-95`). | 목록 drift를 막으려면 release owner를 하나로 정해야 한다. |
| schema authority | memlib은 공통 state schema를 소유하지만 rec, gardener, memory map은 일부 경로와 구조를 독립 정의한다 (`tools/memlib.py:2-6`, `tools/rec.py:21-33`, `tools/wf_gardener.js:10-17`, `tools/build_memory_map.py:56-99`). | “유일한 schema”의 범위를 state/config로 좁히거나 실제 registry를 공유해야 한다. |
| evidence resolver | local 세 종류는 존재를 검사하고 외부 두 종류는 REVIEW다 (`tools/evidencecheck.py:74-90`, `tools/evidencecheck.py:177-186`). | REVIEW를 PASS로 표현하지 않으므로 현재 경계와 일치한다. 원문 적합성은 여전히 사람 판정이다. |
| personal ledger | new/find/check/audit fixture는 생겼다 (`tools/test_rec.py:27-70`). | snapshot rotation, atomic failure, malformed frontmatter의 전용 fixture는 남는다. |
| recall | cwd 격리와 authored filter fixture는 생겼다 (`tools/test_recall.py:77-109`). | Claude transcript parser와 ranking tie의 결정론 검사는 남는다. |
| memory map | 생성 fixture는 생겼다 (`tools/test_coherence.py:73-92`). | hardcoded store/flow가 실제 registry에서 derive된다는 검사는 없다. |
| gardener | external agent JSON schema에 의존한다 (`tools/wf_gardener.js:51-101`). | deterministic local fixture가 없다. |

삭제·병합 우선순위는 P0 sync inventory 단일화와 doctor ledger fail-close, P1 doctor 중복 실행과 release
suite owner 통합, P2 `eval_recall.py` 연결 또는 삭제 순서다. `now.py`, `gate.py`, `fresh_worker.py`는
caller가 알아야 할 복잡성을 실제로 감추므로 삭제 후보가 아니다.

## 6. 철학 대조

README의 목적함수는 사람의 주의를 비싸게, 토큰을 싸게 두고 transcript 대신 검증된 receipt를
올리는 것이다 (`README.md:57-72`). 구조는 worker receipt (`tools/fresh_worker.py:711-744`), 상태
projection (`tools/now.py:550-700`), manifest coverage (`tools/test_manifests.py:103-110`), checker issue
set (`tools/gate.py:119-170`)으로 이를 구현한다.

반대로 짧은 판정이 원인이나 범위를 숨기면 철학을 배반한다. doctor ledger의 거짓 PASS 가능성,
sync의 이중 목록, doctor와 release의 suite 목록 차이가 그 자리다. 다음 개선의 목적은 파일 수 감축이
아니라 authority를 한 seam에 모으고, 그 interface를 통과한 결과만 receipt로 인정하는 것이다.
