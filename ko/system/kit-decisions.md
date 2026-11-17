<!-- source: system/kit-decisions.md sha256:e44e201c50b34f3cee638c23ba4546ed1410bca24883f389c3f15c264ccebb3d source-of-truth: en -->
# 킷 설계 결정 기록 (KIT-DR)

**이 파일은 킷 자신의 설계 결정이다. 업스트림 소유 — 인스턴스는 고치지 않는다.**
`git pull`이 덮어쓴다. 여기 고칠 게 있으면 업스트림에 알려라.

인스턴스가 자기 워크스페이스에서 내리는 결정은 `system/decisions.md`에 쌓는다.
그 파일은 git 밖이라 pull과 충돌하지 않는다. **두 파일은 번호 계열이 다르다.**

append-only. 형식: `### DR-NNN 제목 (YYYY-MM-DD · active|superseded_by:DR-MMM)` →
결정 / 맥락 / 기각 대안 / 참조. 건당 짧게.
스키마 정본: `tools/memlib.py` · PRD: `PRD-session-memory.md`.

### DR-001 인스턴스 배선은 유도하거나 config로, 코드에 박지 않는다 (2026-08-24 · active)
결정: (a) **전사 디렉토리는 유도값** — `~/.claude/projects/<루트경로의 / 와 _ 를 - 로>`.
(b) 트랙·스레드·검사목록·정본 포인터는 `system/memory-config.json`.
(c) ROOT는 `__file__` 유도, 훅은 `$CLAUDE_PROJECT_DIR/tools/...`를 호출해 그 유도가 맞게 한다.
(d) tracks·threads에 내장 폴백을 두지 않는다 — 인스턴스 고유값의 폴백은 남의 워크스페이스를
가리킨다. 조용히 틀린 값보다 시끄럽게 빈 값이 싸다.
맥락: 원본 워크스페이스에서 절대경로 9곳과 프로젝트 키 4곳이 발견됐다. 훅이 `2>/dev/null || true`라
다른 머신에서 **설치된 것처럼 보이며 조용히 죽는 것**이 가장 나쁜 실패 모드였다.
evidence: none
기각 대안: 전사 경로를 config 항목으로 — 사람이 안 고치면 recall이 0건을 내고 정상 종료한다.

### DR-002 데이터 국경은 구조로 막는다 — 밸브 3층 (2026-08-24 · active)
결정: **1층 `.gitignore`** — 엔진만 추적, 인스턴스 데이터는 태생부터 git 밖.
**2층 인스턴스 선언** — `instance.context`와 `remote_allowlist`, doctor의 밸브 검사(탐지층).
**3층 자격증명** — work 클론은 pull-only.
맥락: 2층 단독은 밸브가 아니다. 사고를 내는 같은 tree가 자기 경계값도 고칠 수 있기 때문이다.
차단은 1층과 3층이 맡고 2층은 조기 경보다.
evidence: none
부수 결정: `~/.codex/sessions`는 머신 전역이므로 recall이 rollout 첫 줄 `payload.cwd`로
인스턴스를 거른다. Claude 전사는 프로젝트별 디렉토리라 이 문제가 없다.

### DR-003 훅은 fail-safe하되 침묵하지 않는다 (2026-08-24 · active)
결정: 훅은 항상 exit 0 (세션을 막지 않는다). 대신 SessionStart 실패 분기가 **유효 JSON으로
경고를 주입**하고, PreCompact 실패는 `state/.hook-errors.log`에 남는다.
맥락: fail-safe 자체는 옳다 — 훅이 세션을 막으면 그게 더 나쁘다. 문제는 셸의 `2>/dev/null || true`와
파이썬의 `except: pass`가 겹쳐 **이중 침묵**이 된 것이다. 설치돼 보이는데 죽은 상태가 만들어진다.
evidence: none
기각 대안: 실패 시 stderr 노출 — 도구를 일부러 안 깐 정상 상황에서도 시끄러워진다.
그래서 "훅 정의가 있는데 도구가 없다"는 경우에만 시끄럽게 한다.

### DR-004 규약 문서를 엔진/인스턴스 쌍으로 가른다 (2026-08-24 · active)
결정: `git pull`이 덮는 파일과 인스턴스가 쓰는 파일을 물리적으로 분리한다.
`CLAUDE.md`↔`system/instance-rules.md` · `system/rituals.md`↔`system/rituals.local.md` ·
`system/kit-decisions.md`↔`system/decisions.md`. 오른쪽은 전부 `.gitignore` 안이다.
`setup.sh`가 없는 것만 씨앗에서 만든다.
맥락: 킷은 **고치라고 만든 문서**와 **고치지 말라는 코드**를 같은 방식으로 배포했다. 코드는
pull이 깨끗이 덮지만 규약 문서는 양쪽이 고치면 충돌한다. 실증: 인스턴스가 rituals에 한 줄
추가하고 업스트림도 같은 파일을 고치면 divergent branches가 된다. DR 번호는 더 나쁘다 —
킷 DR-004와 인스턴스 DR-004가 같은 파일에서 부딪힌다.
evidence: none
검증: 인스턴스에 트랙·로컬의식·로컬DR·회사문서·journal을 쌓은 뒤 업스트림이 rituals와
kit-decisions를 고치고 pull. **충돌 0, 새 교훈 도착, 인스턴스 것 전부 보존, linkcheck 0.**
기각 대안: 병합 도구나 3-way merge — 문서는 자동 병합이 의미를 깨고, 사람이 매번 판정하게 된다.

### DR-005 config 스키마 버전과 업그레이드 안내 (2026-08-24 · active)
결정: `memory-config.json`에 `schema_version`을 둔다. 엔진이 새 필드를 요구하면
`memlib.SCHEMA_VERSION`을 올리고 `SCHEMA_CHANGES`에 **무엇을 해야 하는지** 적는다.
`doctor`가 뒤처짐을 FAIL로 내고 해야 할 일을 그대로 인쇄한다.
`CHANGELOG.md`의 항목은 `[해야 함]`·`[알아둘 것]`·`[자동]` 셋으로 태깅한다.
맥락: 엔진은 pull로 오는데 **config는 인스턴스 소유라 안 온다.** 2026-08-24에 `instance.context`를
추가했을 때, 그 필드가 없는 옛 config는 밸브 검사가 personal로 간주해 **원격을 아예 안 보는**
상태가 된다. 조용한 뒤처짐이고, 조용한 것이 이 리포에서 반복해 문제였다.
evidence: none
부수 결정: `doctor`의 업스트림 검사는 상류에서 SKIP한다. 표지는 상류 전용 내보내기 도구의 존재다. 상류에서 엔진 수정은 정상이므로 경고하면 늑대소년이 된다.
기각 대안: 자동 마이그레이션 — config는 사람이 읽고 판단할 값(어느 원격을 허용하나)을 담는다.
기계가 채우면 그 판단이 사라진다.

### DR-006 상태 ledger는 public projection과 local overlay를 분리한다 (2026-08-26 · active)
결정: allowlist 사건만 public journal로 보내고 나머지·`--private`는 local로 내리며, 둘을 합친 view를 정본으로 삼는다.
맥락: tracked journal이 private-derived 사건을 재출력했고 동시 append/render에는 stale writer·truncate window가 있었다.
evidence: none
안전성·마이그레이션: 오류는 private fail-close하고 lock·atomic publish·rollback으로 묶으며, journal provenance만 동결하고 legacy threads는 수동 분리한다.
기각 대안: tracks 겸용·오류 시 public은 privacy fail-open. 참조: `PRD-session-memory.md` §3.2, §9.

### DR-007 광역 작업은 fresh bounded worker, 지시 정본은 AGENTS 하나 (2026-08-29 · active)
결정: master는 사람의 inbox로 두고 광역 독해·감사·토론은 `fresh_worker.py`의 ephemeral run으로
격리한다. master에는 bounded receipt만 반환하고 전문 trace는 `_private/work/runs/`에 둔다.
정확한 byte·capability 계약은 `PRD-session-memory.md` §10.5가 정본이다.
공통 규약은 `AGENTS.md` 하나가 정본이며 Claude는 exact `@AGENTS.md`로 import한다.
맥락: 광역 tool trace와 누적 세션이 master context를 잠식했고, 바이트 동일한 지시 사본도 실제로
갈라졌다. 파일 수나 NOW 크기를 줄이는 것보다 원인을 만드는 실행을 격리하는 편이 직접적이었다.
evidence: none
경계: 두 adapter는 connector·web·network·plugin·fan-out을 닫고 훅에 기대지 않는다. runtime
fallback, public trace, detached scheduler, write-capable Claude는 v1 범위 밖이다.
기각 대안: 파일 대이동·NOW 축소는 원인인 광역 trace를 못 줄이고, DB·embedding index는 현재
계측상 병목이 아니며, runtime fallback과 public trace는 실패·국경을 숨기므로 기각한다.
재검토: 2주간 광역 작업 호출이 0이면 worker를 제거한다. 참조: `PRD-session-memory.md` §10.5.

### DR-008 외부 문안은 본문 전에 역할과 정합 앵커를 드러낸다 (2026-08-29 · active)
결정: 리포 밖의 사람이 읽거나 제출받을 발신 산출물을 쓰기 전에 `문서 역할`과 `정합 앵커` 두
줄을 작업 로그에 실제 값으로 내고, 승인 질문 없이 계속한다. 역할이 그대로면 한 번만 낸다.
맥락: 검색이 정답 파일을 반환해도 잘못 닫은 목적함수가 그 파일을 버리면 조회 규칙만으로는 실패를
막지 못한다. 두 줄은 독자·승인자·목적과 실제 근거를 사람이 즉시 검증할 수 있게 한다.
evidence: none
기각 대안: 새 인덱스와 검색 도구는 이미 나온 정답을 버리는 실패를 못 막고, 매 문단 승인 게이트는
인지부하가 커서 기각한다.
참조: `AGENTS.md` 코어 5 트리거와 `system/rituals.md` 외부 문안 절. 다음 외부 문안 5건에서
판정을 한 번도 바꾸지 못하면 두 줄 프리플라이트를 제거한다.

### DR-009 담백 생성은 닫기·골격·정지의 10건 파일럿으로 둔다 (2026-08-29 · active)
결정: 외부 문안은 근거와 임무를 고정한 뒤 `닫기 → 골격 → 정지`로 생성하고, 자세와 경제성을 본
다음 수신자가 연결을 복원할 수 있는지 마지막에 확인한다. 담백함을 길이 감소로 대리하지 않는다.
맥락: 반려 사례에서 장황함만이 아니라 요청하지 않은 두 번째 임무, 자기평가, 잘못된 수신자 상태,
끊긴 논리가 함께 나타났다. 단어 수를 줄이는 처방은 필요한 연결까지 없앴다.
evidence: none
기각 대안: 옛 5문장 삭제 규칙, 금지어 목록, 길이 상한, 새 문체 스킬은 원인보다 표면을 고쳐
기각한다.
참조: `system/rituals.md` 외부 문안 절. 10건 중 준수 후 구조 재작성 3건, 차갑거나 단절된 반려
2건, 검사상 삭제할 내용을 3번 복원하면 파일럿을 철회하거나 다시 설계한다.

### DR-010 worker run record는 하네스 정체·토큰·읽기 범위·write-set을 담는다 (2026-09-16 · active)
결정: `meta.json` v2에 `kit_rev`·`kit_dirty`·`harness_sha256`·`usage`·`read_scope`·`scope`를 기록한다. receipt는
`scope:` 한 줄 외 불변. `--write-prefix`는 선택이며 사후 탐지·기록만 하고 rollback하지 않는다. 위반이 run
status를 바꾸는 것은 `--strict-scope`일 때만이다(실 카나리 2026-09-16: 위반 2건 전부 동시 writer).
맥락: 같은 모델이 하네스만 바꿔 8.3→37.2%(`paper:2609.07925` §2)이므로 run을 해석하려면 하네스 정체가 영수증에
있어야 하는데 v1에는 prompt·결과 해시뿐이었다. 리드가 워커 출처를 못 보면 오답을 믿는다(`paper:2609.06702` App. F.2).
자연어 경계는 강제가 아니다(`paper:2609.04170` §3.3). 구현 전 설계 문서에서 독립 검증자(Codex)의 질문 4건을 닫았고, 구현 뒤 독립 리뷰 1차가 결함 7건(R1 기존 symlink 통과,
R2 같은 크기·mtime 복원·빈 디렉터리, R3 런타임 실패가 위반을 덮음, R4 호출자 미연결, R5 인스턴스 HEAD를 킷 rev로 오라벨,
R6 read_scope 문법, R7 fixture 빈칸)을 찾아 전부 반영했고, 2차 리뷰가 R8(hardlink 별명)·R9(없는 중첩 prefix 생성이 위반)·
R10(case-sensitive 볼륨에서 대소문자 보정)을, 3차 리뷰가 R5 잔여(목적지 기준선과 원천 manifest의 구분)·R11(각인 미검증)을 찾아
반영했다(fixture 31개, `tools/sync_engine.sh`가 원천 manifest·목적지 기준선을 모두 각인하고 각인을 재검증).
기각 대안: 외부 바이너리·모델 스냅샷·환경변수를 해시에 넣는 것(매 실행 달라져 비교 불가); usage를 이벤트
누적 합산(오합산); write-set rollback(사후 탐지가 파괴 반경을 키우지 않는다); prefix 필수화(호출자 전부가
깨진다, 다음 버전 후보).
참조: 원본 인스턴스의 private 작업장 papers-2026-09-13-kit(설계 문서 design-fresh-worker-receipt-v2, PROPOSALS, DR-draft,
독립 리뷰 REVIEW 1~3차), `tools/test_fresh_worker.py` 31 fixture, `tools/sync_engine.sh`.

### DR-011 릴리스 게이트는 낯선 첫 설치의 재현이다 (2026-09-17 · active)
결정: 엔진을 고친 뒤 `bash tools/test_fresh_install.sh`를 돌려 임시 클론에서 setup(비대화형·인자 없음) → 훅 →
linkcheck → doctor → 회귀 → setup 재실행이 전부 통과해야 릴리스한다. 사람만 풀 수 있는 상태(Codex 훅 미신뢰,
세션 전 전사 디렉토리 부재, tracks 미등록)는 doctor에서 FAIL이 아니라 warn+할 일이다. setup 전 상류 사본에서
setup이 만드는 경로로 가는 참조는 PENDING으로 분리해 센다.
맥락: v0.4는 자기 인스턴스에서만 검증됐다. 임시 클론에서 README대로 돌리자 setup이 tty 없이 조용히 exit 1 했고
인자를 줘도 doctor FAIL 4였다. 안 고쳐지는 FAIL은 사람이 FAIL을 무시하게 만든다(2026-08-24 교훈의 재발).
독립 감사(Codex 결함 감사·Claude 문서 감사 39건)가 --force 재실행의 context 뒤집힘, 킷 now.py의 개인 어댑터
import, git 2.36 전제 미기재를 추가로 잡았다.
evidence: none
기각 대안: 설치 문서만 고치기(문서는 코드와 다시 갈라진다) · doctor의 FAIL을 전부 warn으로(진짜 고장을 숨긴다) ·
CI 서비스 의존(킷은 로컬 첫 설치가 계약이라 로컬 스크립트가 정본이고 CI는 그 위에 얹는다).
참조: `tools/test_fresh_install.sh`, `CHANGELOG.md` v0.5, 원본 인스턴스의 private 작업장 kit-improve-2026-09-17
(감사 2건·리뷰).

### DR-012 철학: 사람의 주의가 가장 비싼 자원, 토큰이 가장 싼 자원 (2026-09-17 · active)
결정: 킷의 목적함수는 소유자가 이렇게 정했다. "인간의 인지비용을 가장 비싼 자원으로, 토큰을 가장 낮은 비용
자원으로 두고 트레이드오프한다. 하나의 무한 스레드 아래에서 여러 작업이 굴러가도 견디게 해서 사람이 하나만
상대하게 한다." README 첫 절이 이 문장의 정본이다. 그 교환을 안전하게 만드는 운영 규칙 둘을 같이 둔다:
(1) **판정은 영수증으로만** — 토큰으로 산 독립 검증의 결과는 bounded receipt(KIT-DR-007·010)로만 올라온다.
전문이 사람에게 오면 교환이 거꾸로 된다. (2) **통과와 원인은 따로 검증한다** — 게이트(설치·회귀·링크)는
통과 여부만 말하고, 실패의 원인 가설은 제안자가 아닌 독립 검토가 다시 본다(KIT-DR-011).
맥락: 2026-09-17 하루의 실측이 세 문장을 다 만족한다. 소유자는 스레드 하나만 봤고, 그 아래에서 워커 6개
(Claude 문서 감사, Codex 결함 감사·리뷰 2회·전략 3라운드, 첫 설치 게이트 반복)가 돌았으며, 올라온 것은
영수증과 판정표였다. 게이트가 PASS를 만든 같은 날 독립 감사가 디스패처의 원인 가설 둘(overlay 순서·기준선
선행)을 다른 원인으로 정정했다. 토큰은 쌌고 사람의 시간은 한 스레드에 머물렀다.
evidence: none
후보였던 문장들: "판정은 영수증으로만"(Codex 3라운드 1위)과 "통과와 원인은 따로 검증한다"(같은 라운드의
새 후보)는 목적이 아니라 수단이라 규칙 자리로 내려갔다. "대화는 휘발성 매체다"는 상태 손실 문제(README
"무엇을 해결하나")의 설명으로 남고 철학 자리에는 안 앉는다.
기각 대안: 목적함수를 "두 모델의 교차 검증"으로 두는 것 — 그건 OpenAI 공식 플러그인이 이미 점유한 자리이고
(확산 조사 2026-09-17), 우리가 파는 것은 교차 검증이 아니라 그 결과가 사람에게 오는 방식이다.
참조: README 철학 절, KIT-DR-007·010·011, `tools/test_fresh_install.sh`.

### DR-013 게이트 정의 파일의 변경은 승인 원장의 한 줄로만 통과한다 (2026-09-18 · active)
결정: 게이트가 무엇을 잡는지 정하는 파일(언어 허용 규칙·pending 목록·근거/강제 상수·강제·테스트 매트릭스·manifest 규칙,
`tools/manifest_build.py`의 GATE_DEFINITION 집합)의 diff는 `system/gate-definition-approvals.md`(추적, append-only)에
`gate-definition-approval` 줄(decision 표지 = 해당 KIT-DR 번호, files = 정렬된 파일 목록, sha256 = diff 해시)이 정확히 맞을 때만 통과한다.
검사는 `tools/manifest_build.py --issues`가 하고 pre-commit과 CI가 같은 검사를 돈다.
맥락: 2026-09-18 실측 2건 — 워커가 회귀를 정의만 하고 실행 목록에 안 넣어 "통과"로 보였고, 다른 워커는 자기 게이트의 허용
목록을 넓혀 종료조건을 통과시켰다. 일한 쪽이 자기 영수증을 쓰는 구조에서는 문장으로 금지해도 잡히지 않는다.
승인 원장을 `_private/` 아래 스웜 파일로 둔 첫 초안은 CI에서 보이지 않아 모든 게이트 정의 변경이 원격에서 실패했으므로
추적 파일로 옮겼다.
evidence: test:tools/test_manifests.py::test_gate_definition_change_requires_dispatcher_approval
참조: KIT-DR-011·012, `system/review-manifest.yaml`의 gate-definition 분류, `.github/workflows/gates.yml`.
범위 보완(2026-09-18 동기화 실측): 검사는 게이트 정의가 작성되는 킷 트리(`system/memory-config.json` 없음)에만 적용한다.
설치된 인스턴스는 게이트 정의를 엔진 동기화로 받고 그 diff는 원천 킷의 원장이 이미 승인했으므로 `--issues`가
`~gate-definition-approval` 해당 없음으로 보고한다. 첫 구현은 인스턴스에서도 승인 줄을 요구해 모든 엔진 동기화가 막혔다.
evidence: test:tools/test_manifests.py::test_gate_definition_approval_is_not_applicable_in_installed_instance

### DR-014 트리거 저장소: "나중에 뜰 것"은 파일에 두고, 행동 티어는 상수다 (2026-09-19 · active-pilot · 3주기 후 재판정)
결정: `tools/triggers.py`가 날짜 트리거를 인스턴스의 `_private/triggers/triggers.jsonl`에 둔다(`add`·`due`·`hook`·`claim`·`fire`·`sleep`·`list`·`scan`).
`scan`은 실험 등록부의 만기 열과 재판정 날짜가 있는 결정 기록에서 안정된 id(`exp-X<n>`·`rereview-DR-<n>`)로 트리거를 만들어 재실행이 멱등이다.
행동 티어는 손잡이가 아니라 상수다: T0 말하기 · T1 준비하기(개인 영역에 초안, 되돌릴 수 있음) · T2 밖으로 나가기(발송·커밋·결제·삭제;
자동 없음, 초안 + 요청 한 줄로만 뜬다). `privacy`(기본 private)와 `destination`(기본 local, 외부 당사자 없음)은 티어와 직교하는 축이라
"T0는 항상 허용"이 외부 알림 허가가 되지 않는다. `due`는 `--mark` 없이는 읽기 전용이고 `hook`만 표시를 기록한다. 세션당 최대 5건,
표시 횟수 오름차순(carry-over)이라 cap이 뒤 항목을 굶기지 않으며, 세 번 보이고도 `fire`가 없으면 7일 자동 잠듦(무시 횟수 기록).
`claim`은 lease를 걸고 살아 있는 lease는 두 번째 claim을 거부하며, `fire`는 반복을 거부하고 `history`에 사건을 남긴다. 저장은 파일 잠금 안의
load-modify-save와 임시파일 교체다. 소스 파서의 언어 의존 단어(닫힘 상태·재판정 표지·"N주기 후")는 엔진에 영어 기본값만 두고
인스턴스 설정 `triggers.sources`가 덮어쓴다(킷 트리는 언어 게이트를 그대로 통과한다). SessionStart 훅 한 줄(`.claude/settings.json`·
`.codex/hooks.json` 동일 JSON 계약)은 별도 rollback 묶음이고 그 단위는 훅 줄 + 트리거 저장소다.
맥락: 소유자 2026-09-19 지시 — 교정된 판정(Jev형)과 능동성(Instinct형)을 킷에 녹이되 Claude Code 전용이면 안 되고 Codex로 옮겨도 그대로
돌아야 한다. 인스턴스의 Claude↔Codex 토론 10라운드에서 수렴(토론 파일은 원천 인스턴스의 debate 폴더, 2026-09-19 decide-triggers 쟁점; 킷 트리에는 없다).
Codex가 바꾼 것: `due` 읽기 전용, destination 축, lease·history·잠금, carry-over 정렬, 소스 파서를 데이터로, `tools/runtime/` 패키지 기각
(런타임 registry는 `fresh_worker.py` 안에), `decide`(교정 판정 registry·그림자 모드·판정 원장)는 다음 주기의 묶음으로.
evidence: test:tools/test_triggers.py::test_add_due_fire_and_tier_boundary · test:tools/test_triggers.py::test_hook_limits_and_auto_sleep_after_ignores ·
test:tools/test_triggers.py::test_claim_lease_refuses_second_holder_and_due_stays_read_only · test:tools/test_triggers.py::test_scan_experiments_and_decision_rereviews
재판정(3주기): fire 대 자동 잠듦 비율, 세션 시작 절이 실제로 행동을 바꾼 횟수, 두 하네스에서 같은 출력이 나왔는지.

### DR-015 런타임 어휘는 등록부 한 항목에서 파생되고, 하네스가 못 받는 역할은 선언한다 (2026-09-21 · active-pilot · 3주기 후 재판정)
결정: `tools/harness.py`가 하네스 배선의 등록부이자 런타임 어휘의 정본이다. 하네스 하나는 `RUNTIMES`의 한 항목이고
(바이너리 · 배선 경로 · 모드 `checked-in|generated` · 받는 역할 · **못 받는 역할의 사유**), 역할 어휘는 `hookdiag.ROLE_EVENTS`와
같은 6종(injector·recovery·observer·enforcer·side_effect·guard)을 쓴다. `tools/test_manifests.py`의 `CONSUMERS`는 리터럴이 아니라
이 표에서 파생된다 — 전에는 세 번째 하네스가 테스트 파일까지 고쳐야 했다. 한 항목으로 붙는 것은 **런타임 어휘**까지다.
새 하네스의 어댑터 코드·테스트·배포 메타데이터(review manifest·test matrix·번역 목록)는 여전히 따로 붙인다(opencode 추가가 그랬다).
opencode는 첫 generated 하네스다. 훅 표면이 없고, v2.0.11에서 설정의 `instructions` 항목이 로드되지 않음을 실측했다(2026-09-21).
그래서 injector는 런처가 진다: `harness.py open opencode`가 상태 파일을 다시 굽고 첫 프롬프트로 심는다. 직접 띄운 세션에는
상태가 안 들어간다. 슬래시 명령 4개는 `.claude/commands/*.md` 정본에서 렌더한다. 나머지 다섯 역할은 미배선이며 `status`가
gap으로 출력한다. `status`는 상태 파일과 명령 디렉토리가 다 있고 명령이 정본과 같을 때만 "배선됨"이라 한다(`check`와 같은
parity 함수). 데이터 국경: 주입 파일은 local private overlay를 담을 수 있으므로 **Git 밖임이 증명되지 않으면 public 상태만
쓴다**(fail-close). 그 출력구가 `now.py context [--public-only]`이고, 같은 본문을 훅 JSON 봉투 없이 평문으로 낸다.
검증은 배선 유무가 아니라 카나리 왕복이다(`harness.py verify`). 프롬프트는 nonce를 담지 않는다. 주입 본문이 파일인 하네스에서는
모델이 grep으로 같은 파일을 찾아 주입 없이도 통과할 수 있다(2026-09-21 실측: 첫 실험에서 모델이 grep을 불러 실험이 오염됐다).
도구는 끄지 못한다 — v2.0.11의 `opencode run`에는 도구를 끄는 플래그가 없고, 도구를 끈 설정으로 돌렸더니 무료 티어가 실행을
거부했다(403). 그래서 **도구를 쓴 실행은 증거로 세지 않는다**(inconclusive): 같은 정답도 도구 호출이 있으면 PASS가 아니다.
nonce는 실행 동안만 주입 파일(Git 밖)에 있다 — 그 파일이 재려는 채널이기 때문이다. 실행이 끝나면(타임아웃·예외 포함) nonce 없는
본문으로 다시 쓰고, 원장에는 판정만 남긴다.
맥락: 소유자 2026-09-21 지적 — "설치 → 세팅 → 사용" 시나리오가 없으면 킷이 하네스 불가지론을 주장할 수 없다. 실측으로 확인한 출발점:
`setup.sh`는 `.claude/`도 `.codex/`도 깔지 않았고(배선은 레포 체크인에 의존), 킷 전체에 `opencode`라는 단어가 0회였다.
관측된 제약: opencode v2.0.11의 플러그인 API는 공개 문서와 다르고(`export default {id, setup}`) 이벤트·세션 훅 시그니처가 아직
고정되지 않아, 플러그인이 필요한 나머지 역할은 이번 주기에서 붙이지 않았다.
evidence: test:tools/test_harness.py::test_every_runtime_declares_the_roles_it_cannot_take ·
test:tools/test_harness.py::test_state_falls_back_to_public_when_the_path_is_not_outside_git ·
test:tools/test_harness.py::test_canary_prompt_never_carries_the_nonce ·
test:tools/test_harness.py::test_a_tool_using_run_is_never_counted_as_proof ·
test:tools/test_harness.py::test_state_file_holds_no_nonce_after_a_canary_run ·
test:tools/test_harness.py::test_status_does_not_call_a_half_wired_opencode_wired
모델 레인 보완(2026-09-21, 소유자 사용 계획): 하네스는 모델 공급자별 레인이다 — Claude는 Claude Code, GPT는 Codex,
제3 모델(무료 티어·중국 모델 등)은 opencode. 그래서 카나리는 런타임당 한 번이 아니라 **모델마다** 재고 판정만
state/harness-canary.json 원장에 남긴다(`verify opencode --sweep`). 이 원장은 선택 생성물이라 verify를 돌린 적 없는 인스턴스에는
없다. 모델을 갈아탈 때 "이 모델이 킷 상태를 실제로 받아서 따르나"는 모델의 성질이지 배선의 성질이 아니기 때문이다. 약한 모델은
도구를 부르거나 지시를 못 따라 INCONCLUSIVE·FAIL로 떨어지고, 그 기록은 라우팅에 쓸 수 있는 측정 원장이다. 아직 자동으로 읽는
소비자는 없다.
정정(2026-09-28, 커밋 전 독립 감사): 초안의 네 주장을 구현에 맞게 좁혔다 — "실행은 도구를 전부 끈다"(구현은 도구를 쓴 실행을
판정 불가로 둔다), "nonce는 디스크에 안 닿는다"(실행 동안 주입 파일에 있다), "라우팅이 원장을 읽는다"(소비자 없음), "새 하네스는
한 항목으로 붙는다"(런타임 어휘만). 같은 감사로 `status`가 상태 파일 하나만 보고 배선됨이라 하던 것을 고쳤다.
재판정(3주기): opencode 세션이 실제로 쓰였는지, 카나리가 회귀를 잡았는지, 네 번째 하네스가 런타임 어휘를 정말 한 항목으로
얻었는지, 모델 원장이 라우팅 결정을 실제로 바꿨는지.

### DR-016 기억 요구와 구현 설계 분리, 인스턴스 권한 미승계 (2026-10-08 · active)
결정: 두 PRD는 원점·정정·데이터 경계와 작업 연속성·성공 조건을 정의한다. 구현 연결과 Mermaid 시각화는 `system/design-memory-runtime.md`에 둔다. Markdown 문서가 설계 정본이고 HTML 지도는 보조 관측 화면이다. 두 PRD의 `.ko.md`가 현재 정본이며 영어 `.md` 전문 번역은 원본 hash에 결속해 유지한다. §10.5 byte/capability 계약은 유지한다.
맥락: `decision:KIT-DR-004`. 업스트림 인스턴스의 자동 적용 위임·일정·실행 결과를 일반 이름 치환으로 이식하면 킷 설치가 권한 위임처럼 읽힌다. PRD와 설계는 kit-owned로 분류해 자동 덮어쓰지 않고 변경 시 별도 정합 검토한다. 수동 gardener는 report-only이며 선택적 주기 adapter의 권한을 상속하지 않는다.
엔진: 회상 후보의 인스턴스·역할·요약 필터와 native source identity를 먼저 적용한다. 보관 세션을 같은 규칙으로 읽고 중복을 제거한다. worker에 필요한 의존 파일은 engine inventory에 함께 둔다. 코드 배포와 개인 기록·자격증명·위임은 별개다.
기각 대안: main 문서를 그대로 복사하거나 번역 완료인 듯 두 정본을 유지하지 않는다. 설치·fixture PASS로 실제 dispatcher 효과나 사용자 부담 감소를 주장하지 않는다.
참조: `PRD-info-architecture.md`, `PRD-session-memory.md`, `design-memory-runtime.md`, `tools/test_recall.py`, `tools/test_fresh_worker.py`, `tools/test_memory_map.py`.

DR-016 보완: 처방 전에 이미 한 일을 먼저 조회하고 남은 미지만 묻는다. 일곱 규칙은 운용 기본값이며 보편적 모델 능력 상한으로 주장하지 않는다.

KIT-DR-016 verification supplement: Markdown dependency extraction now resolves relative links and inline file references against the document, preserving PRD-to-design connections. External URLs and out-of-tree paths do not become local dependencies. The new auth helper and map tests are included in the engine inventory and risk matrix; existing critical test requirements are unchanged. Source snapshot delivery, TERM cleanup, and worker-observed AGENTS provenance have dedicated worker regressions. Gate-definition approval is bound to the reviewed diff below, not inherited from the upstream instance.

### DR-017 코드 안 설명의 자족성 (2026-10-08 · active)
결정: 공통 작성 원칙은 `code-writing.md`다. 주석과 docstring은 현재 동작·인터페이스·불변 조건·필요한 이유를 간결한 영어로 설명한다. 세션 사연·리뷰 번호·완료한 실행의 측정치는 결정 또는 관측 기록에 둔다. 정확한 원문 용어·fixture·도구 지시자·라이선스·생성 각인은 보존한다. 인스턴스 권한은 바꾸지 않는다.
이유: 코드에 발생 경위를 싣는 것은 유지보수에 무관한 맥락을 요구한다. 설명을 모두 지우면 안전한 수정에 필요한 원인 지식도 잃는다. 사건을 현재의 작동 조건으로 다시 쓰고 긴 증거는 해당 기록에 둔다.
검증: 동결한 소스와 실행 AST·런타임 문자열·스크립트 토큰·heredoc을 비교한다. docstring 유래 CLI 도움말의 영어화는 의도된 표시 변경으로 구별한다. 동결 이력을 보존하고 옛 주석을 새로 검증한 사실로 취급하지 않는다. 주석 수나 금지어 관문 대신 새 독자의 이해와 관련 회귀로 판단한다.
재검토: 필요한 제약을 코드 근처에서 찾을 수 없거나 주석 편집이 의도하지 않은 런타임 소비자를 바꾸면 다시 검토한다.


### DR-018 Reviewed engine transfer and runtime isolation (2026-10-08 · active)
Decision: distribute shared memory and bounded-worker mechanisms while preserving explicit kit variants. Instance schedules, operational records, commit delegation, recording adapters and credentials do not transfer with engine code. Lens definitions are reusable; application records are private instance data. The lens index, deep-pass and rituals are kit-owned policies.
Context: `decision:KIT-DR-004`, `decision:KIT-DR-016`. Installation, worker-cluster upgrade and a long-lived source workspace have different dependency and authority boundaries. A successful source check cannot establish a successful fresh install. Model agreement is a review observation, not empirical independence or measured user benefit.
Boundary: worker child environments separate provider credentials; the harness identity records that policy. Read scope is optional self-report, material hashes verify input identity, and write restrictions have their own evidence. The worker sync includes its direct runtime/test dependencies, checks existing consumers and rolls back failed publication. It does not update the full kit, instance config or schedules.
Verification: require normal controls before mutation claims, distinguish infrastructure errors from detected defects, run fresh installation in both declared languages, and preserve instance data in update fixtures. The evidence checker accepts English and Korean context labels with the same section boundaries. Release evidence records exact code identities and command results separately.
Rejected alternatives: blanket source overwrite; inheriting the source instance's automatic-commit authority; storing lens anecdotes in tracked definitions; calling self-reported reads enforced isolation; treating unavailable adapter output as healthy.
Reconsider: a supported installed consumer fails after a verified upgrade, a future export rewrites a kit-owned policy, or a concrete task requires a portable opt-in application engine. That engine needs separate execution/commit/egress controls and its own installed E2E before distribution.

KIT-DR-018 output-delivery supplement: collect safe ignored outputs only within explicit write prefixes; preserve bytes, hashes and replayable patches before cleanup. Failed or incomplete capture returns exit 5 and preserves the worktree. Termination during capture also preserves it. Capture failure takes precedence over strict-scope exit 4 without erasing scope metadata. Known bundled startup metadata is distinct from configured plugins; unknown or malformed plugin records still fail the canary. Temporary verification owns cleanup of its own runtime configuration side effects; the worker does not automatically clean up user configuration.

DR-018 진단·검증 보완: 동기화 진단은 exporter의 읽기 전용 계획을 사용해 소유 범위와 정규화를 공유한다. 입력 누락·개인정보 검증 실패·계획을 얻지 못한 경우는 FAIL이다. 개발 트리 게이트 회귀는 실제 실행되는 작은 합성 증거에 결속하며, 배포 전체 회귀와 설치 검증은 별도로 유지한다. 증거 실행의 제한 시간과 차단 판정은 유지하고 실패 이유를 진단에 남긴다. 이 보완은 집중된 회귀 안의 전체 검사 중복을 없애며, 합성 표본 검증을 배포 검증으로 대신 세지 않는다. CI 증거 단계는 문제가 있으면 실패하는 일반 명령을 사용한다. 항상 정상 종료하는 기계용 목록 모드는 이슈 개수를 직접 판정하는 호출자에만 쓴다.

RAN은 테스트 진입 기록이며 성공 증명이 아니다. 게이트의 최상위 시도마다 새 실행 ID로 인용된 suite를 실제 실행한다. 이전 또는 늦게 도착한 기록을 새 시도의 성공 근거로 쓰지 않으며 내부 재귀 방지는 유지한다.

### DR-019 쉬운 말로 다시 쓴 렌즈 문서와 고를 수 있는 목록 (2026-11-18 · active)
결정: 렌즈 정의 13개와 렌즈 목록을, 이 저장소를 처음 보는 사람이나 모델이 렌즈를 골라 쓸 수 있게 다시 쓴다. 정의마다 머리에 묻는 질문, 켜는 때, 쓰고 나서 남기는 것을 두고, 이어서 요지, 흔한 일의 예시, 왜 통하나, 쓰는 방법, 쓰는 자리, 잘못 쓰는 경우, 다른 렌즈와 함께 쓰는 법, 출처를 둔다. 목록에는 "켜는 때" 칸, 원래 얻으려던 것에서 시작하는 네 단계 절차, 겹치는 렌즈를 가르는 기준, 킷의 다른 부분 없이 이 폴더만 쓰는 방법을 넣는다. 렌즈 폴더의 정본은 한국어 파일이다. 번역되지 않은 사본이던 영어 파일 열두 개는 원본에 결속된 번역이 됐다.
맥락: `decision:KIT-DR-018`. 정의를 원본 인스턴스의 사용 기록과 대조해 검토했고, 맥락 없는 독자에게 읽혔고, 미리 기준을 적어 둔 전후 비교로 시험했고, 다른 계열 모델의 검토를 받았다. 그 비교에서 새 목록은 두 모델이 의도한 렌즈를 더 자주 고르게 했다(옛 목록 157/208, 새 목록 130/156. 나아졌다고 부르기로 미리 정한 선에는 못 미쳤고, 일곱 번 가운데 낮았던 적은 없다). 새 정의를 읽고 쓴 조언에는 다음에 할 일이 더 자주 들어 있었다(35/52에서 40/52). 이 시험은 글로 쓴 상황에 조언을 구하는 것이어서, 실제 일을 하는 도중에 에이전트가 멈춰서 렌즈를 쓰는지는 재지 못한다.
경계: 렌즈는 13개 그대로다. 후보 셋(목적, 독자, 대조)은 검토하고 넣지 않았으며 이유를 목록에 적었다. 적용 기록은 비공개 인스턴스 자료이고 정의에 옮기지 않는다. 비교 자료는 원본 인스턴스에 둔다.
재검토: 실제 일에서 한 비교가 어떤 정의 때문에 결정이 나빠졌다고 보이거나, 지금 시험 중인 내놓기 전 점검의 결과로 독자 후보를 렌즈로 둘 만해지면 다시 본다.

### DR-020 턴 끝 검사는 세션 범위, 출시 검사는 출시 때만 (2026-11-18 · active)
결정: 게이트 검사를 두 범위로 가른다. 세션 범위는 링크 검사와 상태 검사 둘이고, 설치된 작업 폴더의 턴 끝 `check`, `baseline`, `precommit`에서 돈다. 출시 범위는 네 검사기 전부와 인용된 테스트 묶음 다시 돌리기이고, 킷 개발 트리의 `precommit`·`baseline`과 `gate.py release`에서 돈다. 킷 개발 트리는 설정 파일이 없고 `setup.sh`와 설정 템플릿이 있는 트리다(푸시 훅과 같은 판정 함수). `MOTTORI_GATE_SCOPE=release|session`이 이 판정을 덮고, 모르는 값은 더 엄한 출시 범위로 읽는다. 기준선은 같은 범위에서 잰 검사기끼리만 비교한다. `resume`은 측정하지 않고 막았던 이유 한 줄만 알린다. Stop 훅이 같은 턴에 다시 불리면 한 번 통과시키고 미해결 표시는 남긴다. `check`는 편집 표시, 미해결 표시, 작업 트리 지문 변화 가운데 하나가 있을 때만 돈다. 검사기가 결과를 못 내면 막는 사유에 검사기 이름과 원인 한 줄을 넣는다. 게이트 훅 셋은 자기 실패를 `state/.hook-errors.log`에 남긴다.
맥락: `decision:KIT-DR-003`, `decision:KIT-DR-011`, `decision:KIT-DR-013`. 임시 HOME의 새 설치에서 무시되는 문서 한 줄을 고친 뒤 턴 끝 검사가 83.6초, `setup.sh`가 86.7초 걸렸다(2026-11-18). 턴 끝 검사가 킷 자신의 출시 검사를 사용자 턴마다 돌렸기 때문이다. 고친 뒤 같은 측정이 0.4초와 3.0초이고, 변화 없는 트리에서는 0.08초다. 원본 인스턴스의 판정 기록에서는 시험이 만든 가짜를 뺀 차단 395건 가운데 그 턴이 만든 문제가 10건쯤이었고, 세션 이름이 있는 316건 가운데 240건이 직전과 같은 문제로 다시 막힌 것이었다.
evidence: test:tools/test_devtree_gate.py::test_installed_check_runs_no_cited_suite · test:tools/test_devtree_gate.py::test_devtree_precommit_and_release_run_cited_suites · test:tools/test_enforce.py::test_session_check_keeps_release_checkers_in_baseline · test:tools/test_enforce.py::test_resume_reports_pending_reason_without_measuring · test:tools/test_enforce.py::test_H03_H04_stop_hook_active_passes_once_and_keeps_pending
경계: CI는 게이트를 거치지 않고 회귀 묶음 전부와 네 검사기를 직접 돈다. 출시 검사는 줄지 않았다. 지문은 무시된 경로와, 크기와 수정 시각이 모두 같은 덮어쓰기를 놓친다. Codex에는 턴 끝 훅이 없어 이 검사가 Claude Code에서만 돈다.
기각 대안: 출시 검사를 턴 끝에서 비동기로 돌리기(결과가 다음 턴에 와서 어느 턴이 만든 문제인지 흐려진다) · 검사 결과를 캐시하기(캐시를 언제 버릴지가 또 하나의 검사기가 된다).
재검토: 설치본에서 세션 범위가 놓친 문제가 커밋이나 CI에서 거듭 잡히면 범위를 다시 가른다.

### DR-021 세션 시작 주입은 서류철과 가장 새 결정을 먼저 싣는다 (2026-11-18 · active)
결정: 세션 시작 주입은 NOW 글을 가운데에서 자르지 않는다. 절 단위로 나눠 순서대로 채운다. 트랙 온도판, 정본 포인터, 상태 표시는 고정이다. 다음이 공개와 로컬 각각의 가장 새 결정 하나, 다음이 서류철 이름, 다음이 나머지 결정, 다음이 최근 사건이고 새것부터 넣는다. 다 못 실은 서류철은 그 수와 목록을 보는 명령(`python3 tools/now.py threads`)을 적은 한 줄로 남는다. 만들어지는 NOW 파일도 서류철 목록을 같은 방식으로 줄인다. 목록이 길다는 이유로 주입이 실패하지 않는다. 공개와 로컬은 남은 자리를 반씩 쓰고 한쪽이 남긴 자리는 다른 쪽이 쓴다. 사건 한 줄은 400바이트에서 자르고, 빼놓은 줄 수를 한 줄로 알린다. 상한 6,000바이트는 그대로다. 컴팩션 사건은 결정 절에 넣지 않고 사건 절에서 한 줄로 접는다. 저널 신선도는 컴팩션이 아닌 마지막 사건으로 잰다. 공개 저널이 깨져 있어도 `log --private`는 로컬 저널에 쓴다. 트리거의 "보여 준 횟수"는 하루에 한 번만 오르고, 훅이 안내하는 명령은 그대로 실행된다. 뜰 수 없는 조건 종류는 `add`가 거부한다.
맥락: `decision:KIT-DR-006`, `decision:KIT-DR-014`. 저널이 길어지면 가운데 자르기가 서류철 목록과 최근 결정을 통째로 빼 버렸다. 압축 뒤 복귀에 가장 필요한 두 가지다. 컴팩션 사건이 최근 결정 자리를 채웠고(원본 인스턴스의 11월 공개 저널 70줄 가운데 68줄), 저널 신선도가 그 줄들 때문에 늘 "0일 전"이었다. 공개와 로컬 저널 각 1,000줄의 시험에서 새 주입은 상한 안에 들고 서류철과 결정 절이 모두 남는다. 트리거는 훅이 돌 때마다 횟수가 올라 하루 안에 "세 번 무시"가 되어 잠들었다.
evidence: test:tools/test_state_runtime.py::test_hook_context_keeps_dossiers_and_newest_decisions_with_long_journals · test:tools/test_state_runtime.py::test_hook_context_names_omitted_dossiers_when_both_lists_are_long · test:tools/test_state_runtime.py::test_hook_context_survives_sixty_long_dossier_names_on_one_side · test:tools/test_state_runtime.py::test_snapshot_drops_compactions_from_decisions_and_dedups_recent · test:tools/test_state_runtime.py::test_private_log_survives_corrupt_public_journal · test:tools/test_triggers.py::test_shown_counts_once_per_calendar_day · test:tools/test_triggers.py::test_hook_fire_instruction_runs_as_written
경계: 결정이 많고 길면 최근 사건 절은 비고 빼놓은 줄 수만 남는다. 기억 색인의 낱말 검사와 녹음 검사는 그 도구가 있는 인스턴스에서만 돌고, 낱말 검사는 막지 않는 안내가 됐다.
재검토: 주입에 서류철 목록도 그 생략 줄도 없거나 가장 새 결정이 빠진 것이 한 번이라도 관측되면 채우는 순서를 다시 본다.

### DR-022 내놓기 전 점검: 걸린 것을 기록하고, 맞는 비율을 보인 신호만 막는다 (2026-11-18 · active-pilot · 2026-12-16 재판정)
결정: Stop 훅 둘째 자리에 `tools/deliver.py`를 둔다. 모델을 부르지 않는다. 턴의 마지막 답과 도구 호출만 보고 신호를 판정한다. `unopened`는 이번 턴에 쓴 읽을거리 문서(1,500자 이상)를 다시 열어 보지 않고 내놓은 경우다. 무엇을 "내놓음"으로 칠지 가르는 전달 도구 이름은 인스턴스 설정 `deliver.send_tools`에 적는다. `reader`는 긴 작업 끝의 긴 보고다. 신호마다 "기록만"과 "막기" 가운데 하나로 돈다. 기본값은 `unopened`만 기록하고 아무것도 막지 않는다. 막는 신호는 턴을 한 번만 멈추고, 사유에는 걸린 신호와 주인의 원래 요청만 싣는다. 걸릴 때마다 `state/.deliver.jsonl`에 남긴다. 막은 경우에는 같은 턴의 재진입 때 답이 바뀌었는지를 한 번 이어 적는다(`deliver.py stats`). 다른 턴이나 다른 훅이 막은 뒤의 재진입은 세지 않는다. 점검 자신의 실패는 턴을 막지 않는다. 낱말만 보고 판정하는 신호(주인에게 일을 넘기는 문장, 통과했다는 주장)는 넣지 않는다.
맥락: `decision:KIT-DR-012`, `decision:KIT-DR-003`. 원본 인스턴스에서 주인이 다섯 달 동안 친 말 6,697개를 전부 읽어 바로잡는 말 2,243줄을 셌다. 글 규칙이 이미 있던 잘못 묶음 13개 가운데 12개가 규칙 뒤에도 세 번 넘게 되풀이됐고, 8개는 1,000발화당 비율이 그대로거나 늘었다. 작은 대조 시험에서는 과제 지시문 안에 둔 짧은 규칙이 시키지 않은 덧붙임을 72건 중 0건으로 줄였다(규칙 없음 19건, 다시 읽기 2건, 처음 읽는 사람 검토 1건). 그래서 규칙은 일이 일어나는 자리에 두고, 턴 끝에는 좁은 검사만 둔다. 신호 넷을 과거 8,817턴에 먼저 대 봤다. `unopened`는 2.1%에서 걸렸고 무작위 40건 가운데 35건이 맞았다. `reader`는 4.6%, 14건이 맞았다. 일을 넘기는 문장 신호는 2건, 통과 주장 신호는 37건 가운데 0건이 맞아 코드에서 뺐다. 그 뒤 후보 셋을 같은 방법으로 대 봤다. 이름으로만 가리키고 보내지 않은 문서는 40건 가운데 12건, 만든 뒤 들여다본 흔적이 없는 결과물은 14건, 풀이 없이 나온 내부 이름은 0건이 맞았다. 셋 다 넣지 않았다.
evidence: test:tools/test_deliver.py::test_unopened_document_blocks_once_and_quotes_request · test:tools/test_deliver.py::test_default_only_records · test:tools/test_deliver.py::test_configured_delivery_tools · test:tools/test_deliver.py::test_stats_links_a_reentry_only_to_its_own_blocked_turn · test:tools/test_deliver.py::test_broken_input_never_blocks
경계: 원본 인스턴스에서 "결과물을 안 열어 보고 냈다"는 실제 불만 18건 가운데 `unopened`가 잡은 것은 1건이다. 나머지는 영상, 그림, 화면이었다. "다시 열어 봤다"는 그 턴의 뒤 도구 호출에 파일 이름이 나오는 것을 뜻한다. 도구 결과는 읽지 않으므로 파일 이름만 찍는 명령도 통과한다. 이 점검은 Claude Code의 Stop 훅에서만 돈다. 시험의 덧붙임 숫자는 지어낸 과제 12개에서 나온 것이고 실제 일에서 잰 것이 아니다.
기각 대안: 턴마다 다른 모델에게 답을 검토시키기(턴마다 비용과 지연이 붙고, 대조 시험에서 지시문 안 규칙보다 못했다) · 규칙 문장을 더 쓰기(위 집계).
재판정(2026-12-16): 설치본의 기록에서 신호별 걸린 횟수와 막은 뒤 답이 바뀐 비율. 바뀐 비율이 반 아래인 신호는 "기록만"으로 내린다. 새 신호는 과거 대화에 대 본 맞는 비율 없이는 넣지 않는다.

### DR-023 일꾼 영수증은 판정이 먼저, 산출물은 실행 뒤에 확인한다 (2026-11-18 · active)
결정: 영수증 상한은 4,096 UTF-8 바이트 그대로다. 머리말 순서를 고친다. `verdict:`, 일꾼이 적은 `unknowns:`, 전문을 여는 명령 `full:`, 그리고 `--expect`를 줬으면 `expect:`가 본문보다 앞에 온다. 머리말 값의 개행과 제어 문자는 눈에 보이는 꼴로 바꿔, 값 안의 글이 머리말 줄을 만들지 못하게 한다. 일꾼이 적은 "확인 못 한 것"이 잘리면 값 앞에 전체 수와 잘린 수를 적는다. 긴 결과는 앞에서부터 남기고 끝에 잘랐다는 표시와 전문 명령을 둔다. `--expect PATH`는 실행 전에 경로가 작업 폴더 안인지 보고, 실행 뒤에 그 파일이 비어 있지 않은 일반 파일인지 본다. 하나라도 없으면 성공이던 실행을 `expected-output-missing`으로 바꾸고 종료 코드 6을 낸다. 영수증 판정은 일꾼이 PASS라고 적었어도 INCONCLUSIVE다. 끝 상태 이름은 `tools/worker_batch.py` 한 곳에서 정의한다. 프롬프트에 금지 경로 글자가 있으면 지금처럼 거부하고, 거부 문구가 "금지하려던 것이면 경로 글자를 빼고 말로 적어라"를 알려 준다. 실행될 수 없던 반출 기록 코드와 `--strict-egress`, `ask_codex.sh --resume-root`와 도우미 `codex_root_thread.py`를 지운다.
맥락: `decision:KIT-DR-007`, `decision:KIT-DR-010`, `decision:KIT-DR-012`. KIT-DR-010은 영수증을 "`scope:` 한 줄 외 불변"으로 정했다. 이 결정이 그 문장을 고친다. 사람이 영수증만 보고 판단하려면 판정이 맨 앞에 있고, 모르는 것은 글이 잘려도 수가 남아야 한다. 일꾼이 PASS를 적고 파일을 남기지 않은 실행을 영수증만으로는 가릴 수 없었다.
evidence: test:tools/test_fresh_worker.py::test_receipt_byte_cap_keeps_the_start_and_puts_verdict_unknowns_and_location_first · test:tools/test_fresh_worker.py::test_receipt_header_values_cannot_forge_lines_and_count_cut_unknowns · test:tools/test_fresh_worker.py::test_expect_missing_or_empty_output_downgrades_a_pass · test:tools/test_fresh_worker.py::test_expect_outside_root_is_refused_before_a_run · test:tools/test_egress.py::test_prohibition_naming_a_private_path_is_refused_with_wording_advice · test:tools/test_worker_batch.py::test_status_vocabulary_is_shared_by_worker_and_ledger
경계: 금지 경로 검사는 프롬프트 글자를 보는 것이고 일꾼의 읽기를 막는 가림막이 아니다. `--expect`는 실행 뒤에 비어 있지 않은 파일이 있는지만 본다. 내용이 맞는지, 이번 실행이 쓴 것인지는 보지 않는다. `--expect`가 없는 실행은 전과 같다.
재검토: 영수증만 보고 내린 판단이 전문을 열었을 때 뒤집힌 사례가 나오면 머리말에 무엇을 더 올릴지 다시 본다.

### DR-024 한국어판은 `ko/`에 모으고 짝은 색인이 안다 (2026-11-18 · active)
결정: 뿌리 트리의 문서는 영어다. 한국어판은 `ko/` 아래 같은 상대 경로와 같은 파일 이름에 둔다(`README.ko.md`였던 것이 `ko/README.md`). 짝 표 `ko/INDEX.md`는 도구가 만들고(`python3 tools/i18n_stamp.py index`), 검사는 표가 파일과 어긋나면 실패한다. 한국어 문서 안의 링크는 한국어판이 있는 대상이면 한국어판으로 간다. 어느 쪽이 원본인지는 짝마다 스탬프에 적힌 대로 둔다. "영어가 본판"은 뿌리 트리에 놓이고 에이전트가 자동으로 읽는다는 뜻이다. 한글 허용 범위는 `ko/` 아래 파일, 문구 사전의 한국어 값, 한국어 입력을 다루는 시험 자료다.
맥락: `decision:KIT-DR-004`, `decision:KIT-DR-016`, `decision:KIT-DR-019`. 소유자 2026-11-18 지시: 영어를 본판으로 두고 한국어 파일은 한곳에 모으며 짝은 색인 파일에서 알 수 있게 한다. 42쌍이 영어 파일 옆에 흩어져 있었고, 한국어 렌즈 문서의 목록 링크가 영어 목록으로 갔다. 명령 폴더에 있던 한국어 명령 파일은 런타임에 따로 등록됐다.
evidence: test:tools/test_language.py::test_pair_index_fixture · test:tools/test_language.py::test_korean_link_to_english_fixture · test:tools/test_language.py::test_stamp_bind_and_source_drift_fixture
경계: 어느 런타임도 한국어 규칙 파일을 자동으로 읽지 않는다. 옮기기 전에도 그랬다. 이미 설치된 작업 폴더에는 옛 `*.ko.md` 사본이 남을 수 있다(무시되는 인스턴스 파일은 `git pull`이 지우지 않는다).
재검토: 세 번째 언어가 들어오거나, 한국어 사용자가 한국어 규칙을 자동으로 읽게 해 달라는 요구가 실제로 나오면 다시 본다.

### DR-025 세션마다 고정으로 드는 컨텍스트를 재고, 회상 기본 출력에 상한을 둔다 (2026-11-18 · active)
결정: `python3 tools/context_budget.py`가 세션마다 고정으로 들어가는 것을 바이트와 어림 토큰으로 잰다. 지시 파일(`CLAUDE.md`와 그것이 가져오는 파일, `AGENTS.md`), 세션 시작 상태 주입, 트리거 훅 출력, 프롬프트마다 붙는 훅 출력, 런타임 기억 색인이다. 파일을 쓰지 않는다. `doctor`는 항목이 설정의 경고선을 넘으면 경고만 한다. `recall.py find`의 기본 출력은 출처와 짧은 발췌만 싣고 안내 줄까지 합쳐 4,000바이트 안에 들며, 잘렸으면 남은 건수와 `--full`을 알린다. `--full`의 출력은 전과 같고, `--full`과 `--around`에는 상한이 없다. Claude 세션은 거기 적힌 작업 폴더가 이 작업 폴더이거나 적어 둔 별칭일 때만 찾는다. 그래서 두 폴더가 같은 대화 폴더 이름으로 바뀌어도 다른 프로젝트는 찾지 않는다. 0건이면 찾은 범위를 말한다.
맥락: `decision:KIT-DR-012`, `decision:KIT-DR-002`. 새 설치의 고정 컨텍스트는 약 6.7KB이고 대부분이 규칙 일곱 개다. 원본 인스턴스는 39.7KB였고 그중 29.1KB가 기억 색인이었다. 규칙 문서가 "일곱 개만 늘 유효"라고 말해도 실제 상시 지시의 대부분은 재지 않은 색인이었다. 색인을 일의 종류별 하위 색인으로 나눠 6.6KB로 줄였다. 흔한 낱말 하나의 회상 출력이 17.8KB였고 새 기본값에서는 3.6KB다.
evidence: test:tools/test_context_budget.py::test_defaults_do_not_warn_on_small_install · test:tools/test_context_budget.py::test_stale_state_is_estimated_without_writing_any_file · test:tools/test_recall.py::test_default_output_is_capped_and_says_how_to_see_more · test:tools/test_recall.py::test_full_keeps_previous_output_shape · test:tools/test_recall.py::test_missing_transcript_dir_never_borrows_another_project · test:tools/test_recall.py::test_claude_records_from_another_folder_with_the_same_store_name_are_excluded · test:tools/test_recall.py::test_default_output_stays_under_the_cap_with_a_long_query
경계: 작업 폴더가 한 줄도 적히지 않은 대화 파일은 지금도 찾고, 그런 파일의 수를 알린다. 런타임이 직접 넣는 것(시스템 프롬프트, 도구 정의, 스킬 목록)과 사용자 전역 설정은 재지 못한다. 토큰 수는 어림이고 실제 토크나이저와 대조하지 않았다. 경고선은 측정에서 나온 값이 아니라 출발값이다.
재검토: 경고선이 실제 사용에서 늘 울리거나 한 번도 안 울리면 값을 다시 정한다.

### DR-026 도구 출력은 인스턴스 언어를 따르고, 그 언어는 설정에 남는다 (2026-11-18 · active)
결정: 사람이나 모델이 읽는 도구 출력은 문구 사전에서 온다. 만들어지는 `state/NOW.md`, 세션 시작 주입, 기록·거부·오류 문구, 도움말이 여기 든다. 언어는 `MOTTORI_LANG`, 설정의 `instance.lang`, 셸 로캘 순서로 정한다. `setup.sh`가 설치 때의 언어를 `instance.lang`에 적는다. 파일에 쓰이고 코드가 다시 읽는 낱말(저널의 컴팩션 표지, NOW의 절 제목, 소급 표지, 원장의 상태값)은 쓰는 쪽이 지금 언어로 쓰고 읽는 쪽이 두 언어를 모두 받는다. 한국어 출력은 옮기기 전과 바이트까지 같다. 다만 훅 설정 파일에 든 대체 문구 다섯 군데는 영어 하나로 바꿨다. 영어 문구에는 em-dash와 화살표를 쓰지 않는다.
맥락: `decision:KIT-DR-024`. 영어로 설치해도 상태 화면과 명령 출력이 한국어였다. 언어를 환경 변수와 로캘로만 정했기 때문에, 한국어로 설치한 폴더도 로캘이 영어인 셸이나 예약 실행에서는 다른 언어로 돌 수 있었다. 만들어지는 상태 파일과 저널 표지가 언어를 따르게 된 뒤에는 그 언어가 폴더마다 고정돼야 한다. 한국어 명령 208개의 출력을 옮기기 전과 뒤에 떠서 바이트로 비교했고, 한 언어로 쓴 상태를 다른 언어로 읽는 왕복을 56가지 확인했다.
evidence: test:tools/test_state_runtime.py::test_english_instance_writes_english_state_and_injection · test:tools/test_state_runtime.py::test_state_tokens_are_read_in_both_languages · test:tools/test_i18n.py::test_configured_language_beats_locale · test:tools/test_rec.py::test_status_values_are_read_in_either_language · test:tools/test_evidencecheck.py::test_issue_ids_do_not_depend_on_language
경계: 예전에 설치한 폴더에는 `instance.lang`이 없어 전처럼 로캘을 따른다. 한 줄을 넣어야 고정된다(CHANGELOG). 녹음·전사 도구, 기억 지도 도구, 강제 표의 설명 칸은 아직 한국어가 남아 있고 `system/language-pending.txt`에 적혀 있다. 한국어 문서나 전사를 읽는 파서의 표지는 한국어 그대로다.
재검토: 언어를 바꾼 폴더에서 옛 저널이나 원장이 잘못 읽히는 일이 관측되면 두 언어 읽기의 표를 다시 본다.

### DR-027 세션을 떠나고 일을 닫는 절차를 둔다 (2026-11-18 · active)
결정: (1) 일이 다른 세션이나 런타임에서 이어질 때 떠나는 세션이 넘김 메모를 파일로 남긴다(`system/rituals.md`의 일을 넘기는 절, Claude Code에서는 `/handoff`). 메모는 다섯 부분이고, 대화 안에만 있는 글은 설명하지 않고 글 자체를 싣는다. 저널에 한 줄을 남겨 다음 세션이 받는 상태에 메모 경로가 보이게 한다. (2) 일 폴더 맨 위에 한 장을 두고, 일이 끝나면 "끝남"과 남길 것, 지워도 되는 것을 적는다. 임시 사본은 한 자리에만 만들고 일을 맡긴 쪽이 지운다. 다시 만들 수 없는 것은 자동으로 지우지 않는다(`system/WORKING-WITH-AI.md`). (3) `doctor`가 남은 디스크, `.git` 크기, 오래된 임시 자리의 크기, 길잡이 없는 일 폴더 수를 재고 경고만 한다. (4) 트리거에 `add --sticky`를 둔다. 주인이 꼭 봐야 하는 알림은 보여 준 횟수 때문에 잠들지 않고 목록 맨 앞에 온다. (5) Codex 훅 카나리는 사용자 설정을 그대로 둔 채 돈다.
맥락: `decision:KIT-DR-012`, `decision:KIT-DR-014`, `decision:KIT-DR-021`. 원본 인스턴스의 세션 53개를 전부 읽었다. 새 세션의 42%는 다른 세션이 도는 중에 따로 연 것이었고, 두 세션 이상을 쓴 날이 153일 가운데 56일이었다. "스레드 하나"는 목표이고 실제는 여러 갈래였다. 앞 일을 이어받은 세션 19개 가운데 9개에서 주인이 800자 넘게 붙여 넣었고 그중 8개는 다른 세션이나 런타임의 답이었다. 서류철과 상태는 정한 것을 나르지만 대화 안에만 있던 글은 나를 길이 없었다. 같은 인스턴스에서 디스크가 98%까지 찼고, 일 폴더 125개 가운데 93개에 무슨 일인지와 끝났는지를 알려 주는 파일이 없었다. 주인에게 보내는 알림 여섯 개는 세 번 뜨고 잠들어 하나도 처리되지 않았다. Codex 카나리는 프로젝트 신뢰가 사용자 설정에 적혀 있어서, 그 설정을 무시하면 실제로는 도는 훅을 실패로 보고했다. 같은 호출에서 사용자 설정을 두면 모델이 훅이 넣은 값을 받았고, 무시하면 받지 못했다.
evidence: test:tools/test_triggers.py::test_sticky_triggers_never_auto_sleep_and_lead_the_hook · test:tools/test_hook_runtime.py::test_canary_children_pin_instance_and_block_ambient_tools · test:tools/test_doctor_json.py::test_growth_lowered_lines_warn_each_item_and_never_fail · test:tools/test_doctor_json.py::test_growth_check_writes_nothing
경계: 넘기기는 절차와 명령 문서이고 엔진이 강제하지 않는다. Codex에는 슬래시 명령이 없어 같은 절차를 말로 청한다. 자람 검사는 경고만 하고 아무것도 지우지 않는다. 카나리는 연결 도구와 외부 기능을 하나씩 끄지만 사용자의 다른 설정은 그대로 쓴다.
재검토: 넘김 메모를 썼는데도 이어받는 세션에서 긴 붙여넣기가 이어지면 메모의 칸을 다시 본다. 자람 검사가 늘 울리거나 한 번도 울리지 않으면 경고선을 다시 정한다.
