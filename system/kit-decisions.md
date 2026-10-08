# 킷 설계 결정 기록 (KIT-DR)

**이 파일은 킷 자신의 설계 결정이다. 업스트림 소유 — 인스턴스는 고치지 않는다.**
`git pull`이 덮어쓴다. 여기 고칠 게 있으면 업스트림에 알려라.

인스턴스가 자기 워크스페이스에서 내리는 결정은 `system/decisions.md`에 쌓는다.
그 파일은 git 밖이라 pull과 충돌하지 않는다. **두 파일은 번호 계열이 다르다.**

append-only. 형식: `### DR-NNN 제목 (YYYY-MM-DD · active|superseded_by:DR-MMM)` →
결정 / 맥락 / 기각 대안 / 참조. 건당 짧게.
스키마 정본: `../tools/memlib.py` · PRD: `PRD-session-memory.md`.

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


### DR-017 Self-contained source commentary (2026-10-08 · active)
Decision: `code-writing.md` defines the shared writing contract. Comments and docstrings use concise English to explain current behavior, interfaces, invariants, and necessary rationale. Historical session narratives, review labels, and completed-run measurements belong in decision or observation records. Exact source terms, fixtures, tooling directives, licenses, and generated provenance remain intact. This changes no instance authorization.
Reason: evidence: none (normative writing policy). Carrying the origin story in source makes unrelated context a prerequisite for maintenance. Deleting all explanations loses the causal knowledge needed to change code safely. Rewrite incidents as current mechanisms, and keep the longer evidence at its proper source.
Verification: compare frozen source with executable AST, runtime literals, script tokens, and heredoc bodies. English CLI help derived from a docstring is an intentional display change, not byte-identical output. Preserve frozen history and never treat a recovered comment as newly verified evidence. Use cold-reader understanding and relevant regressions, not comment counts or a keyword gate.
Reconsider if maintainers cannot recover a necessary constraint locally or a commentary edit changes a runtime consumer unintentionally.


### DR-018 Reviewed engine transfer and runtime isolation (2026-10-08 · active)
Decision: distribute shared memory and bounded-worker mechanisms while preserving explicit kit variants. Instance schedules, operational records, commit delegation, recording adapters and credentials do not transfer with engine code. Lens definitions are reusable; application records are private instance data. The lens index, deep-pass and rituals are kit-owned policies.
Context: `decision:KIT-DR-004`, `decision:KIT-DR-016`. Installation, worker-cluster upgrade and a long-lived source workspace have different dependency and authority boundaries. A successful source check cannot establish a successful fresh install. Model agreement is a review observation, not empirical independence or measured user benefit.
Boundary: worker child environments separate provider credentials; the harness identity records that policy. Read scope is optional self-report, material hashes verify input identity, and write restrictions have their own evidence. The worker sync includes its direct runtime/test dependencies, checks existing consumers and rolls back failed publication. It does not update the full kit, instance config or schedules.
Verification: require normal controls before mutation claims, distinguish infrastructure errors from detected defects, run fresh installation in both declared languages, and preserve instance data in update fixtures. The evidence checker accepts English and Korean context labels with the same section boundaries. Release evidence records exact code identities and command results separately.
Rejected alternatives: blanket source overwrite; inheriting the source instance's automatic-commit authority; storing lens anecdotes in tracked definitions; calling self-reported reads enforced isolation; treating unavailable adapter output as healthy.
Reconsider: a supported installed consumer fails after a verified upgrade, a future export rewrites a kit-owned policy, or a concrete task requires a portable opt-in application engine. That engine needs separate execution/commit/egress controls and its own installed E2E before distribution.

KIT-DR-018 output-delivery supplement: collect safe ignored outputs only within explicit write prefixes; preserve bytes, hashes and replayable patches before cleanup. Failed or incomplete capture returns exit 5 and preserves the worktree. Termination during capture also preserves it. Capture failure takes precedence over strict-scope exit 4 without erasing scope metadata. Known bundled startup metadata is distinct from configured plugins; unknown or malformed plugin records still fail the canary. Temporary verification owns cleanup of its own runtime configuration side effects; the worker does not automatically clean up user configuration.

DR-018 diagnostic and fixture supplement: the drift diagnostic consumes a read-only exporter plan so ownership and normalization have one implementation. Missing inputs, privacy findings, or an unavailable plan fail validation. Development-tree gate tests use a small, actually executed synthetic evidence probe; full distribution regressions and installation checks remain separate release coverage. Evidence execution keeps its timeout and fail-closed verdict, with explicit failure diagnostics. This removes repeated full-suite execution from a focused fixture without treating fixture coverage as release evidence. The CI evidence step uses the checker's failing command mode; its machine-readable issue-list mode is reserved for callers that inspect the issue trailer.

RAN remains a test-entry record, not a success receipt. Every top-level gate attempt executes cited suites under a fresh run ID. Previous or late records cannot certify that attempt; the internal recursion guard remains.
