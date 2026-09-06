# PRD — 세션·기억·상태 아키텍처 v3

**상태: ACTIVE — 2026-08-20 기훈 판정(D1~D15 전부 채택, /goal) · Phase 1 구현됨.**
이력: v1 2026-08-20 오후(상태 위생) → v2 저녁(깊이 손실·인지 구조·위임·문헌) →
**v3 같은 날, 기훈 요청으로 최종화** — 결정 감사(§8)·스키마 정본(§9)·훅/스킬/핸드오프
자동화(§10)·시각화(§11)·실행 계약과 자율성 규약(§12).
자매 문서: `PRD-info-architecture.md`(개인 사실 원장) · `WORKING-WITH-AI.md`(큰 작업 프레임).

---

## 0. 문제 — 두 종류의 손실

한 세션을 무한으로 쓰고 한 작업공간에서 트랙을 오간다. 컨텍스트가 길어지면 압축되고,
그때 **서로 다른 두 가지**가 사라진다.

### 0.1 상태 손실 (v1에서 실측한 것)

1. 낡은 상태 단언 — 8/8 메모리가 8/15까지 정본 행세 (수락·사퇴를 기훈이 알려줘야 했음)
2. 문서 간 드리프트 — 트래커 8일 지연; 트랙 정본과 실제 완주 시점이 어긋난 사례 다수
3. 교훈 비전이 — 경로 판정 버그를 오전에 고치고 오후에 재생산
4. 회상 트리거 실패 — 컴팩션 후 세션은 "무엇을 모르는지"를 모름
5. 팬아웃 — 한 사실이 다섯 문서에 거주, 수동 동기화
6. 자기 만료 무탐지 — START_HERE "유효기간 3일"이 만료된 채 정본 행세

### 0.2 깊이 손실 (v2의 추가 실측 — 더 아픈 쪽)

7. **주제 복귀 시 피상성.** SOI 논문 대화로 돌아오면 이전에 도달했던 깊이(확정된 결론, 기각된
   경로, 정립된 어휘)를 잃고 얕은 얘기를 다시 한다.
8. **동일 세션 내 망각.** 장기 트랙 논의는 전사 수십 개 분량의 맥락이 **같은 세션 안에**
   쌓였는데도, 컴팩션 후 내용을 잊고 딴소리를 한다.

### 0.3 근본 원인 (v1의 RC1~5 + v2의 RC6~7)

- **RC1** 대화를 장기기억으로 오용 (결정·정정이 대화에만 기록)
- **RC2** 쓰기 경로 다중화 (사실 하나 = N개 문서 수동 갱신)
- **RC3** 자동 로드 계층이 얇음 (인덱스 한 줄의 낡음 = 세션의 세계관)
- **RC4** 기억에 시제 없음 (유효기간·대체 의미론 부재)
- **RC5** 트랙 전환이 대화 속 사건 (디스크에 안 남음)
- **RC6. 컴팩션은 현재 태스크 최적화다.** 요약은 지금 하던 일의 연속성을 위해 쓰이므로,
  **다른 스레드의 깊이는 구조적으로 뭉개진다.** 상태(한 줄)는 살아도 논증의 결(왜 그 결론이었나,
  뭘 기각했나)은 죽는다. 이것이 증상 7·8의 기계적 원인 절반.
- **RC7. 에피소드 원장은 있는데 회상 도구가 없다.** 전 대화의 원문 전사가
  `~/.claude/projects/…/*.jsonl`로 **373MB 실재**한다. 잃은 게 아니라 **안 뒤진 것**이다.
  세션은 자기 과거를 grep한 적이 없다. 나머지 절반.

## 1. 문헌 판정 — 우리 코퍼스가 이 설계에 주는 것

최근 4개월 agent-memory 문헌은 이미 전수 독해·재고돼 있다(레이더). 아래는 그 판정을
**설계 입력으로 번역**한 것이다. 빌린 것은 통찰이지 결론이 아니다 — 각 항목은 우리 재고에서
반론까지 통과한 상태고, 등급을 병기한다.

| 발견 | 출처(등급) | 설계 함의 |
|---|---|---|
| append 로그 + grep이 정교한 메모리 하네스를 토큰 4~6배 싸게 따라잡거나 이김. **수동으로 읽기만 하면 이득 소멸** | `2607.20064`(B) | 원문 보존 + **요청 시 검색**이 정본. 요약본을 정본으로 삼지 말 것 |
| 에이전트가 정리한 저장소: 검색 비용은 줄지만 **조직화가 정답률로 환산된 사례 0** | `2607.26637`(B) | 정제물은 색인이지 진실이 아니다. 서류철은 작게, 원문 포인터 중심으로 |
| 태스크 연속성용 compactor는 세션 제약을 **평균 17%만** 보존. 별도 추출기가 90%+ 복원 | `2608.11242`(B) | **컴팩션과 독립된 추출 경로 필수** — 결정·제약·교훈은 압축 전에 사건 시점 기록 (journal이 그 추출기) |
| 컨텍스트 파일이 무한히 자라는 원인 = 지시보다 **근거가 먼저 썩음**. 근거 부착이 성장을 멈춤 | `2608.11095`(B, nov A) | 모든 상시 규칙·기억에 Why 부착 (현행 메모리의 "Why:" 관행 검증됨). 근거 없는 규칙 = 삭제 후보 |
| **동시 지시 준수는 k=5~6에서 막힌다.** 붕괴는 간섭이 아니라 독립 실패의 곱 | `2608.12426`(B) | **상시 로드 규칙에 예산이 있다.** CLAUDE.md 상시 불릿 28개는 예산 5배 초과 — 다이어트 필수 |
| 원본 trace 이중 색인 + 규칙 선택(LLM 0회)이 생성형 메모리 스택과 동급 이상 | `2607.29377`(B) | lexical 검색으로 충분한 규모에서 임베딩은 조기 최적화 |
| 검색 결과를 그대로 붓는 것보다 **타깃에 묶인 4필드 노트**가 +10.7pt, 토큰 -48.9% | `2608.12847`(A) | 회상 결과는 원문 투하가 아니라 **현재 질문에 묶어 몇 줄로** 주입 |
| 백만 토큰 in-context 붕괴는 랭킹이 아니라 **리드아웃** 실패 | `2607.01538`(A) | 컨텍스트에 쌓지 말고 좁게 가져와라 — "다 넣기"는 구조적으로 진다 |
| 같은 key의 낡은 기억을 **명시 폐기**해야 reversal 붕괴를 막음 | `2608.07429`(B) | supersede 의미론은 장식이 아니라 필수 (v1 §3.5 유지·강화) |
| 스킬을 문서로 쌓기 ≈ 그냥 맥락 유지 (0.602 vs 0.605) | `2608.03874`(B) | "통찰 DB"류 과공학 경계. 가치는 원문(경험)에, 정제는 얇게 |

**요약 한 줄:** 문헌의 합의 방향은 "**원문이 정본, 검색은 요청 시, 주입은 타깃 결속, 정제는
색인일 뿐, 상시 규칙은 소수, 낡은 것은 명시 폐기**"다. 그리고 이 방향은 rec.py·레이더가
독립적으로 도달한 설계와 일치한다 — 수렴 증거로 취급한다.

## 2. 기억 모델 — 무엇이 어디 사는가

| 인지 대응 | 구현 | 성질 |
|---|---|---|
| 감각·단기기억 | 세션 컨텍스트 | 휘발, 압축됨. **캐시일 뿐** |
| **에피소드 기억** | 전사 원장 (`~/.claude/projects/…/*.jsonl`) | 이미 존재(373MB). **회상 도구만 부재** → recall.py |
| 의미 기억 (내구재) | auto-memory `user`/`feedback` + `system/lenses` + 프레임 문서 | 반감기 김. 현행 유지 |
| **작업 기억 포인터** | `state/NOW.md`(공유 가능 projection) + local private overlay(로컬 overlay) | 둘을 합친 local view가 "지금 무엇이 살아 있나" |
| 사건 기록 | `state/`와 `_private/state/`의 월별 journal (public/local) | 컴팩션 독립 추출 경로, 쓰기 시점 격리 |
| **스레드 장기 상태** | 스레드 서류철 (§3.3) | 깊이의 착지점 — 증상 7·8의 해독제 |
| 개인 사실 | `_private/ledger` (rec.py) | 불가침, 기존대로 |
| 1차 사고 | 사건 시점 기록 (journal·서류철 델타) | 참여자(세션)가 그 자리에서 |
| 2차 사고 | 정원사 패스 (§3.5) | 위임된 재검토·검증·정제 |

## 3. 아키텍처

### 3.1 권위 서열 (헌법)

```
[개인 사실]   _private/ledger (rec.py)                     ← 불가침
[에피소드]    전사 원장 *.jsonl                            ← 원문. 최종 검증처
[작업 사건]   state/의 월별 journal + _private/state/의 월별 journal  ← append-only, public/local 분리
[스레드 깊이] 스레드 서류철 (지정된 정본 1개/스레드)        ← 손으로 쓰는 진실
[트랙 상태]   트랙 정본 (tracker.md, TODO.md, …)
──────────── 이하 생성물·포인터·캐시 ────────────
[생성물]      state/NOW.md(public projection) + _private/state/NOW.md(local overlay)
              · START_HERE 온도판
[포인터]      auto-memory의 상태류 (내용 금지)
[캐시]        세션 컨텍스트 · 컴팩션 요약 — 상태·깊이 단언 모두 잠정,
              충돌 시 위 계층이 이긴다
```

#### 3.1.1 권위는 저장소가 아니라 주장의 종류에 붙는다 [DR-020 P1]

위 서열은 **파일**의 순서다. 그런데 같은 파일 안에서도 주장의 종류에 따라 권위가 다르다.
이걸 명시하지 않으면 "전사 원장이 최종 검증처"라는 규칙이 과잉 적용된다.

| 주장의 종류 | 정본 | 왜 |
|---|---|---|
| **기훈이 무엇을 말했나** | 전사 원장 원문 | 그의 발화가 원점이다. 요약·기억은 파생물 |
| **기훈이 무엇을 결정했나** | `system/decisions.md` (DR) + journal `decision` | 발화는 탐색을 포함한다. 결정은 따로 확정된 것만 |
| **지금 상태가 무엇인가** | 훅이 합친 public NOW + local overlay | 둘이 충돌하면 scope가 더 좁은 local이 이긴다. overlay 부재는 반드시 명시한다 |
| **개인 사실이 무엇인가** | `_private/ledger` | 불가침. 조회 없이 단언 금지 |
| **어느 스레드가 어디까지 갔나** | 그 스레드의 서류철 | 손으로 쓰는 진실. journal은 사건만 |

그리고 **`role=user`는 기훈의 발화가 아니다.** 세 오염원이 그 라벨을 공유한다.

1. **시스템 주입** (훅, 도구 결과, 리마인더) — 내용 패턴으로 판별
2. **서브에이전트 rollout에 복제된 부모 이력** — 파일 첫 줄 `session_meta`의 `thread_source`로
   판별한다. 같은 발화가 여러 파일에 잡히고 타임스탬프가 spawn 시각으로 다시 찍혀 있어
   **시점 판정까지 오염된다.** 접두어 필터로는 못 잡는다 (8/22 실측, prefix 단독안 기각)
3. **컴팩션 요약** — 원문이 아니라 파생물이므로 `role="요약본"`으로 태깅해 구분

`tools/recall.py`가 이 셋을 기본으로 제외한다 (`--include-agents`, `--include-system`으로 복원).
런타임이 달라도 이 규칙은 같다. 파일 형식만 다르고 오염의 종류는 동일하다.

### 3.2 상태 ledger — public projection + local overlay [KIT-DR-006]

journal 한 줄 문법과 `now.py log|render|check` CLI는 유지하되, 기록 전에 track을
`journal_visibility.public_tracks`로 분류한다. 명시된 track만 추적 journal로 가고,
`personal`을 포함한 미등재 track은 `_private/state/`로 내려간다. `--private`는 public track도
강제로 내리는 **하향 override만** 제공한다. 설정 부재·파손·schema 불일치는 전부 local로
fail-close하며, quiet `precompact`를 포함한 mutation 명령마다 raw config 값을 싣지 않은 stderr
경고를 정확히 한 번 낸다. 분류는 내용 판정을 대신하지 않는다. private 사건에서 파생된
`system/*`도 호출자가 `--private`로 내려야 하고, public 승격은 공유 가능한 capsule을 새로
기록하는 사람의 판정이다. migration 이전의 추적 journal은 `legacy_cutoff`와 그 순간 고정한
`legacy_public_tracks`로 판정한다. 이후 allowlist 확대는 과거 private-derived body에 소급되지 않는다.

`state/NOW.md`는 공유 가능한 상태의 정본 projection, local private overlay는 로컬 overlay다.
SessionStart는 둘을 명시적으로 합쳐 local authoritative view를 만든다. overlay가 없는 clone은
그 사실을 `unavailable`로 말하며, public projection만 보고 전체 상태라고 단언하지 않는다.
registry 일부가 invalid면 `degraded`, local journal이 corrupt면 `unavailable/corrupt`로 구분한다.
local render 실패는 유효한 public injection까지 없애지 않고 public-only degraded view를 반환한다.
private 기록은 추적 journal과 public NOW의 bytes를 바꾸지 않는다. private thread 이름·dossier도
추적 config가 아니라 local private thread registry에 두고 public projection에서 제외한다.
local registry identity는 private scope의 입력일 뿐 public render/log를 막지 않는다. public key와
충돌하거나 local 안에서 중복된 key는 skip하고 registry를 `degraded`로 내린다.

한 repo-wide lock이 journal append → flush/fsync → 해당 snapshot render → same-filesystem temp
fsync → atomic replace를 직렬화한다. append만 또는 publish만 잠그면 stale last-writer가
가능하므로 둘은 한 transaction이다. hook reader는 lock 없이 old-or-new 완성본만 읽고,
journal이 snapshot보다 새로우면 lock을 얻어 재생성한다. renderer는 import 시점 config·source와,
private scope에서만 local registry의 content identity를 고정한다. journal·canonical을 포함한 동적 입력의 render 전후와
atomic replace 직후 fingerprint가 같을 때만 publish를 확정한다. post-publish 검증이 실패하면 이전
snapshot의 존재·bytes·mode·mtime을 먼저 복원하고, log transaction은 방금 append와 journal mtime도
rollback해 안전한 retry가 중복 사건이나 stale cursor를 만들지 않게 한다. 이 검증 없이 live 새 bytes를
marker에 쓰면 구 코드 산출물을 새 코드가 만든 것으로
false-certify할 수 있다. malformed 사건 줄은 조용히 버리지 않는다.
freshness의 `N일 전`은 elapsed 24시간이 아니라 local calendar-date 차이로 계산해 marker의
local-date clock과 같은 경계에서만 바뀐다. live snapshot marker는 freshness label 때문에
mtime까지 묶는다. Git index에는 mtime이 없으므로
pre-commit은 staged config·journal·canonical·renderer의 content-only fingerprint와, marker 자체만
placeholder로 정규화한 snapshot 전체 bytes를 함께 묶은 content marker를 검사한다. 따라서
checkout-index의 새 mtime은 허용하면서 staged NOW 본문 단독 변조는 거부한다.

기존 추적 history는 이 변경으로 지워지지 않는다. 새 renderer는 legacy `personal`/미등재 사건을
public NOW에서 재출력하지 않지만, 이미 reachable한 journal/blob 정리는 별도 파괴 작업이며
이 결정의 승인 범위가 아니다.

### 3.3 스레드 서류철 (dossier) — 깊이의 착지점 [신설]

**정의.** 살아 있는 깊은 스레드(예: SOI 논문, 리로케이션, 레이더 방법론)마다 **정본 문서
하나를 지정**한다. 신규 파일 강제가 아니다 — 이미 있는 문서를 지정하는 것이 우선이다
[울타리]. (논문 스레드 → 그 연구의 상태 문서, 이주 스레드 → 해당 계획 문서,
장기 작업 → 그 작업의 HANDOFF.md. "그 작업의 HANDOFF부터"라는 기존 규약의 일반화다.)

**서류철이 담는 것 (깊이의 다섯 칸):**
현재 위치 · 확정된 결론(+왜) · 기각된 경로(+왜 — 재탐색 방지) · 미결 질문 · 다음 수.
검색용 조직화가 아니라 **논증 상태의 저장**이다 — `2607.26637`의 "조직화≠정확도" 함정과
구별되는 지점. 크기 상한 유지(오래된 결론은 원문 포인터로 강등), 사실 인용엔 근거 부착
(`2608.11095`).

**두 가지 의식:**
- **마감 의식** — 깊은 세션을 떠나기 전, 서류철에 델타 5줄 이내 append (위 다섯 칸).
  원가: 쓰기 1회.
- **복귀 의식** — 스레드로 돌아올 때 **서류철부터 읽는다.** 필요하면 recall(§3.4)로 원문
  슬라이스 보강. **서류철을 안 읽고 깊은 스레드에 답하는 것 금지** — 피상성의 직접 차단선.

NOW.md는 살아 있는 스레드 목록 + 서류철 링크를 표시한다.

### 3.4 `tools/recall.py` — 에피소드 회상 [신설]

전사 원장(373MB jsonl)에 대한 검색 도구. **잃어버린 게 아니라 안 뒤진 것**을 뒤지게 한다.

```
recall.py find "키워드|정규식" [--role user|assistant] [--since 날짜] [--around N]
  → 매치 슬라이스(전후 N턴)를 사람이 읽을 형태로 출력
recall.py sessions        → 세션 파일 목록·기간·크기
```

**사용 규약 (문헌 각인):**
- 주제 복귀·깊은 논의 재개 전, **표적 질의**로 원문 확인 (수동 전체 읽기 금지 — `2607.20064`:
  읽기만 하면 이득 소멸, 요청 시 검색이라야 이긴다)
- 회상 결과를 컨텍스트에 통째로 붓지 않는다 (`2607.01538` 리드아웃 붕괴). **현재 질문에 묶인
  몇 줄로 번역해 사용** (`2608.12847`의 타깃 결속 노트 원칙)
- 기훈 발화의 원문이 필요한 판정(그가 정확히 뭐라 했나)에는 요약이 아니라 **반드시 recall**
  — PRD-info-architecture §4.1의 "발화가 원점" 규칙의 도구화

구현: 표준 라이브러리 grep/파싱만. 무의존성. (임베딩은 §3.7 게이트.)

### 3.5 정원사 (gardener) — 위임된 2차 사고 [신설]

주기적(주 1회 또는 요청 시) 위임 에이전트 패스. **제안만 하고 집행하지 않는다** —
레이더의 신고→판정 분리(오탐 2건을 오탐으로 지킨 그 구조)를 그대로 쓴다.

**하는 일:**
1. `now.py check` 실행 + 결과 해석
2. 부패 후보 식별: N일 무갱신 상태류, 근거(Why) 없는 규칙·기억, supersede 누락
3. **서류철 검증 (표본):** 서류철의 결론 문장을 recall로 전사와 대조 — 요약의 요약이 아니라
   원문 대조 (자기 판정 게이트의 커널을 아는 설계: 검증 없는 정제는 FRAMES급 손실을 낳는다)
4. 중복·모순 발견: 같은 사실의 다중 거주, 문서 간 충돌
5. (선택) 스레드 교차 연결 — 레이더 pass2의 클러스터 재고처럼, 스레드 여럿을 같은 책상에 놓고
   충돌·연결 표면화

**산출:** 제안 리포트 1건 (`state/` 아래 `gardener-YYYY-MM-DD.md`). 집행은 세션+기훈 판정 후.

### 3.6 상시 규칙 다이어트 [신설 — 문헌 직격]

`2608.12426`: 신뢰 가능한 동시 제약 수는 **5~6개**. 현행 CLAUDE.md 상시 불릿 **28개** —
예산 5배 초과 상태로 모든 턴에 로드되고 있다. 규칙이 많을수록 각각이 덜 지켜진다는 것이
측정된 사실이므로, 규칙 추가로 문제를 풀려는 관성 자체를 뒤집는다:

- **상시 코어 ≤ 7:** ①권위 서열 ②컴팩션 복구 프로토콜 ③단언 전 조회 ④불가침 목록
  ⑤사건 즉시 기록 ⑥복귀 의식(서류철 먼저) ⑦아웃바운드 규칙(em-dash 등)
- 나머지는 **조건부 로드 문서**로 이동 (rituals.md (`system/` 아래, P3 예정), 기존 WORKING-WITH-AI처럼
  "X할 때 읽어라" 패턴) — 조건부 로드는 이미 세 번 검증된 관행이다
- 모든 상시 규칙에 **Why 한 줄 부착** (`2608.11095`) — 근거를 못 쓰는 규칙은 삭제 후보

### 3.7 임베딩·그래프 — 보류하되 문을 열어둔다 [기훈 제안 검토]

**현재 판정: 채택 안 함. 단 조건 명시부 보류다** — 배제가 아니다.

근거: ①우리 규모(전사 수백 MB, 단일 사용자)에서 lexical이 충분하다는 문헌 3건
(`2607.29377` LLM 0회로 동급, `2607.20064` grep 승, `2608.12847` 검색은 이미 포화·병목은
주입) ②우리 데이터의 특수성 — 고유명사 밀도 높음(논문 id, 인명, 파일명), 시간 구조 강함,
한/영 혼용 — lexical에 유리한 분포 ③임베딩은 색인 신선도·API 의존·불투명 실패라는
유지보수 비용을 상시 부과한다 [한계효용].

**채택 트리거 (하나라도 실측되면 재평가):**
- recall known-item 실패 — "분명 나눈 대화를 못 찾는" 사례가 기록으로 3회 누적
- 표현 불일치 실패 — 같은 개념을 다른 어휘로 논의해 lexical이 원리적으로 못 잇는 사례 실증
- 전사 규모가 grep 응답성을 해치는 지점 (>수 GB)
- 스레드 교차 연결 수요가 정원사 수동 패스 비용을 넘는 시점 (그때는 그래프도 함께 재평가 —
  현행 경량 그래프: 메모리 `[[링크]]` + rec.py 관계 + 서류철 포인터로 충분한지 먼저 측정)

트리거 발동 시 1순위 후보는 Gemini 임베딩 + 로컬 색인이며, 그때도 **원문 정본·lexical 병행**
원칙은 불변이다 (임베딩은 색인 추가지 권위 변경이 아니다).

### 3.8 안 하는 것 (non-goals, v1 계승)

DB·프레임워크 도입 없음 · rec.py 불가침 · 디렉토리 대개편 없음 (`state/` 하나) ·
auto-memory 메커니즘 개조 없음 · journal에 대화 미러링 없음 · **"통찰 저장소" 구축 없음**
(`2608.03874`: 스킬 문서화 ≈ 무이득 — 가치는 원문에 있고 recall이 그 문을 연다).

## 4. 성공 기준 (v1 + 깊이 항목)

1. 컴팩션 복구 결정적 — NOW 1회 읽기로 국면·루프·최근 사건 복원 (상태 질문 3개, 재질문 0)
2. 낡은 단언 탐지기 존재 — 8/8-스타일 사고 재현 픽스처를 check가 잡음
3. 상태 사실의 손 쓰기 집 5→2
4. **깊이 복원 — 주제 복귀 시 이전 확정 결론·기각 경로를 서류철+recall로 재진술. 기훈이
   "피상적"이라 느끼는 복귀가 관측되면 그 자체를 실패 사례로 journal에 기록하고 원인 분석**
5. **recall known-item 리콜 — "그때 그 얘기" 질의 실패를 기록, 3회 누적 시 §3.7 게이트 발동**
6. 의식 원가 ≤ 툴콜 1회, public NOW와 SessionStart additionalContext 각각 ≤ 6,000 UTF-8 bytes.
   주입은 public/local 양쪽에 최소 예산을 보장하고 절단 사실을 표시
7. **규칙 준수율 — 다이어트 후 상시 규칙 위반이 체감 감소하는가 (기훈 관측 기준)**
8. **광역 worker 반환량 — fresh worker 한 건이 master context에 반환하는 receipt ≤ 4,096
   UTF-8 bytes.** native session persistence는 0이고, 전문 trace는 local-private run record에 남는다

## 5. 단계별 목표 (실행 계약은 §12)

**Phase 1 — 척추 (~반나절).** 목표: 컴팩션 생존의 최소 완결.
`tools/memlib.py`(스키마 정본, §9) → `state/` + journal 소급 ~15줄 → `now.py log|render` →
`recall.py find|sessions` 최소판 → **SessionStart 훅으로 NOW 자동 주입(§10.1)** →
상태류 메모리 2건 포인터화 → `system/decisions.md` 개설 + 판정된 D들을 DR로 기록.
*검증: 컴팩션 복구 시뮬레이션(요약만 든 새 세션 관점에서 상태 질문 3개) + recall
known-item 테스트(과거 대화 심은 질의 3개).*

**Phase 2 — 계기·위임·표면 (P1 검증 후).** 목표: 규율 슬립을 탐지가 흡수.
`now.py check` 5종 검출기(+과거 사고 재현 픽스처) → supersede 의식 + `memory/archive/` →
서류철 지정 3개(살아 있는 스레드) + 복귀/마감 의식 가동 → 정원사 v0
(`tools/wf_gardener.js`, report-only) → 스킬 4종(§10.2).

**Phase 3 — 다이어트·시각화 (별도 판정 게이트).** CLAUDE.md 상시 코어 ≤7 재편(코어 목록은
기훈 선정) + rituals.md (`system/` 아래, P3 예정) 분리 + 규칙별 Why 부착 → START_HERE 온도판 처리(D3) →
memory-map.html (`system/` 아래, P3 예정) 생성기(§11).

**Phase 4 — 운용 재평가 (2주 후).** 성공 기준 4·5·7 실측 → 임베딩/그래프/정원사 주기
재판정 → 본 PRD 개정(이력 명기).

## 6. 셀프 그릴링 (v2 추가 라운드)

- **"서류철이 `2607.26637`의 '조직화≠정확도' 함정 아닌가."** → 그 논문의 함정은 검색 효율을
  위한 저장소 재조직이 정답률을 못 사는 것. 서류철은 검색 조직화가 아니라 **논증 상태의 체크포인트**
  다 — 레이더 HANDOFF가 세션 한도 3회를 넘겨준 것과 같은 종. 단 함정의 교훈은 받는다: 작게,
  포인터 중심으로, 원문 검증 대상으로.
- **"recall이 373MB에서 실용적인가."** → grep은 이 규모에서 초 단위다. 병목은 검색이 아니라
  주입이며(문헌 §1), 주입 규약이 §3.4에 있다.
- **"정원사도 자기 판정 게이트다."** → 그래서 ①원문(전사) 대조 의무 ②제안만, 집행 분리
  ③레이더에서 이 분리가 오탐 2건을 지킨 실측이 있다. 자기 요약을 자기 근거로 쓰는 순환만
  끊으면 위임은 안전해진다.
- **"다이어트가 오히려 규칙 유실을 낳지 않나."** → 이동이지 삭제가 아니다. 조건부 로드는
  WORKING-WITH-AI·lenses에서 이미 작동 중인 패턴이고, 문헌은 '28개 상시'가 '7개 상시 + 조건부'
  보다 **더 많이 어겨진다**고 말한다. 현상 유지 쪽이 유실이다.
- **"이 조합이 SOTA일 가능성."** → 성분(append 로그, lexical 회상, 정제-검증 분리, k 예산)은
  전부 문헌에 있다. 새로움은 **단일 사용자 무한 세션에서의 조합과 운용 데이터**다. 논문화는
  부차 목표로만 두고, 운용 실측(성공 기준 4·5·7)이 쌓이면 그때 판단한다 — 지금 그걸 목표로
  삼으면 설계가 논문을 향해 왜곡된다 [거울].
- **"전사 원장 자체가 유실되면."** → 하네스 관리 디렉토리라 보존 정책이 우리 소관 밖이다.
  **에피소드 기억의 단일 사본 문제** — D11에서 백업 판정 필요.
- **"훅이 실패하면 세션이 막히나."** → 모든 훅은 `|| true` fail-safe + 타임아웃 짧게. 훅은
  의식의 백업이지 유일 경로가 아니다 — 훅이 죽어도 수동 의식과 check가 남는다 (이중화).
- **"시각화가 또 하나의 썩는 문서가 되지 않나."** → memory-map은 손으로 그리지 않는다.
  스키마 정본(§9)과 라이브 상태에서 **생성**되므로, 구현과 그림이 갈라질 수 없다 —
  DIGEST·NOW와 같은 원장→생성물 규칙의 적용이다.
- **"결정 기록이 관료제가 되지 않나."** → DR은 설계 결정에만, 한 건당 5줄 상한, 단일 파일
  append. 이 PRD의 판정(D1~D15)이 첫 엔트리들이라 개설 비용은 0에 가깝다. 기록 없는 결정이
  이 시스템에서 얼마나 비쌌는지(v1 §0)가 개설의 근거다.

## 7. 결정 필요 사항 (v1 D1~D5 + v2 추가)

- **D1~D5**: v1과 동일 (state/ 위치=루트, journal=md 문법, START_HERE 온도판=포인터,
  **public journal만** git 추적, 소급=이번 주) — D4는 KIT-DR-006으로 범위를 좁힘
- **D6. 서류철 규약** — 기존 문서 지정 방식(제안) vs 전용 dossier 파일 신설. 첫 지정 3개:
  SOI / 리로케이션 / 레이더.
- **D7. recall 검색 범위** — 이 프로젝트 세션만(제안) vs `~/.claude/projects` 전체.
- **D8. 정원사 주기** — 주 1회 고정 vs 요청 시만(제안: 요청 시로 시작, 운용 후 재판정).
- **D9. CLAUDE.md 다이어트** — Phase 3으로 분리해뒀다. 상시 코어 7개의 목록 자체를 기훈이
  고르는 게 맞다. *지금 판정 불요, Phase 3 진입 시.*
- **D10. 임베딩 트리거 수치** — known-item 실패 3회(제안)가 적정한가.
- **D11. 전사 백업** — 373MB 단일 사본. repo 밖 로컬 백업 1곳 권고(제안: 채택. `_private`
  취급 등급으로, 클라우드 금지 규칙 준수).
- **D12. 훅 채택 범위** — SessionStart(NOW 자동 주입) + PreCompact(사건 기록)를 repo의
  `.claude/settings.json`에 추가. *제안: 채택 — 의식을 규율에서 인프라로 옮기는 핵심 수.*
- **D13. 스킬 4종** — `/now` `/recall` `/dossier` `/garden` (기훈용 진입점). *제안: Phase 2.*
- **D14. memory-map 생성 방식** — 스키마 정본에서 생성(제안) vs 손 작성. 위치는
  memory-map.html (`system/` 아래, P3 예정), 열람은 `open` 또는 jupyter 루트 조정.
- **D15. 결정 기록 위치** — `system/decisions.md` 단일 append 파일(제안) vs 건별 파일.
  판정된 D1~D15 자체가 첫 DR 엔트리가 된다.

## 8. 결정 기록 (DR) — 설계의 감사 가능성 [신설]

이 시스템의 모든 설계 결정은 **이유·맥락·기각 대안과 함께** 남는다. 근거는 이 PRD 자신이
실측한 비용(기록 없는 결정 → 재논의·드리프트·같은 실수)과 `2608.11095`(근거가 먼저 썩는다),
그리고 rec.py 감사 사슬의 선례다.

- **위치:** `system/decisions.md` 단일 append 파일 (D15). 건당 ≤5줄.
- **스키마:** `### DR-NNN 제목 (날짜 · active|superseded_by:DR-MMM)` → 결정 / 맥락(왜 지금) /
  기각 대안(+왜) / 참조(rec:, 논문 id, 파일).
- **연결:** journal의 `decision` 줄은 `→ dr:NNN`으로 DR을 가리킨다. 코드 주석·문서도 dr id로
  인용한다 (경로 버그 재발 방지책이 코드 주석이었듯, 결정의 Why도 마주치는 자리에).
- **정원사가 감사:** superseded 미표기·근거 없는 결정을 검출 대상에 포함.

## 9. 스키마 정본 — 한 곳에서 정의, 나머지는 파생 [신설]

스키마가 문서·도구·시각화에 세 번 적히면 세 번 썩는다. **정본은 `tools/memlib.py`의 선언부
하나**이고, now.py·recall.py·정원사·memory-map이 전부 그것을 import한다.

정의 대상 (초안 — 구현 시 memlib에 최종 기입, 변경은 DR로):
- **journal 줄:** `- <ISO8601+09:00> [<track>/<type>] <한 줄> (→ ref)*` · timezone 필수 · type ∈ {decision,
  state, artifact, correction, lesson, switch} · ref ∈ {rec:, dr:, paper id, 경로}
- **journal visibility:** 별도 `journal_visibility.public_tracks` allowlist. 미등재·설정 오류는 local,
  `--private`만 하향 override. legacy는 cutoff+당시 public set으로 고정해 소급 승격을 금지한다.
  track 온도판 레지스트리와 보안 분류 레지스트리를 겸용하지 않는다
- **NOW 섹션 (고정 순서):** 생성시각+입력 신선도 → 트랙 온도판 → 살아 있는 스레드(서류철 링크)
  → 열린 루프 → 최근 사건 N줄 → 정본 포인터
- **서류철 다섯 칸 헤더:** `## 현재 위치` `## 확정 (+왜)` `## 기각 (+왜)` `## 미결` `## 다음 수`
- **정원사 리포트:** 검출 항목별 {증거, 제안, 위험} + 판정 대기 목록
- **DR 엔트리:** §8의 형식
- 검증: `now.py log`는 스키마 위반 줄을 거부한다 (쓰기 시점 검증 — 사후 정리보다 싸다)

## 10. 자동화 계층 — 훅 · 스킬 · 워크플로 · 핸드오프 [신설]

**설계 원리: 의식의 3중화.** 같은 보증을 ①인프라(훅, 자동) ②도구(CLI, 세션이 수행)
③탐지(check, 사후)가 겹쳐 제공한다. 어느 한 층의 슬립이 시스템을 죽이지 못한다 [에르고드].

### 10.1 훅 (repo `.claude/settings.json` — 이미 훅 인프라 작동 중인 환경)

| 훅 | 동작 | 왜 |
|---|---|---|
| **SessionStart** (startup·resume·compact) | public NOW + local overlay를 6,000 UTF-8 bytes 안에서 구조적으로 합쳐 주입. overlay의 available·degraded·unavailable/corrupt를 구분하고 local 실패 때도 public은 주입 | 컴팩션 복구 첫 수를 **규율에서 인프라로** — RC3·RC4의 구조적 차단 |
| **PreCompact** | `now.py log "[system/state] 컴팩션 발생"` 기록 | 압축 시점이 journal에 남아, 사후 세션이 "언제부터 요약인지" 안다 |
| UserPromptSubmit | (기존 타임스탬프 훅 유지, 추가 없음) | 노이즈 금지 |

전 훅 fail-safe + 즉시 반환. 다만 내부 실패는 non-zero로 돌려 shell fallback이 실제로 발화해야
한다. 훅은 백업이지 유일 경로가 아니다. `doctor`의 direct command 검사는 command-valid만
증명하며 dispatcher-fired/effect를 PASS로 올리지 않는다. 실제 주입은 opt-in fresh-session
positive/disabled-negative canary로만 검증한다.

### 10.2 스킬 (기훈용 진입점, Phase 2)

`/now`(NOW 표시+check 요약) · `/recall <질의>`(회상 의식 포함 실행) · `/dossier <스레드>`
(복귀 의식: 서류철 열기→요약→델타 준비) · `/garden`(정원사 발주). 스킬 본문은 해당 의식의
규약을 담아, 누가 불러도 같은 절차가 돈다.

### 10.3 워크플로 (위임 에이전트)

정원사 = `tools/wf_gardener.js` (레이더 워크플로 문법 계승: 스키마 강제 산출, flag→adjudicate).
서류철 검증 단계는 recall 슬라이스를 증거로 첨부한 제안만 낸다. 실행 루프:
정원사 리포트 → 세션이 요약 제시 → 사람 판정 → 집행 → journal `decision` + DR.

### 10.4 핸드오프 계약 (Codex·타 플랫폼·미래 세션 공통)

읽기 순서 고정: **public NOW + local overlay → 필요한 scope의 journal 최근 ~20줄 →
(작업 스레드의) 서류철 → 필요 시 recall.** local overlay가 없으면 그 부재를 상태로 취급한다.
전부 플랫폼 독립적 플레인 파일이므로 핸드오프 문서를 따로 쓰지 않는다 — 레이더 HANDOFF가
장기 작업용이었다면, NOW가 세션 수준의 상시 HANDOFF다. 런타임 공통 규약은 `AGENTS.md`가
단일 정본이고 Claude가 exact `@AGENTS.md`로 import한다 (8/29 첫 mirror drift 뒤 KIT-DR-007).

### 10.5 fresh bounded worker (KIT-DR-007)

무한 master는 기훈의 인간용 inbox로 유지할 수 있지만, 광역 독해·감사·런타임 토론은
`tools/fresh_worker.py`의 fresh+ephemeral worker로 격리한다. 정확한 prompt snapshot, event stream,
stderr, final result, content hash가 `_private/work/runs/`의 자기완결 run record이고, master에는
고정 필드+UTF-8-safe result로 된 4,096-byte receipt만 반환한다. Claude v1 capability는 read-only
review (`Read|Glob|Grep`), Codex v1은 workspace-write sandbox다. capability는 숨기지 않고 receipt와
meta에 쓴다. resume·runtime fallback·public landing·detached scheduler·write-capable Claude는 v1
범위 밖이다. 이 모듈을 2주간 광역 작업이 한 번도 호출하지 않으면 shallow wrapper로 판정해 제거한다.

두 adapter는 훅에 의존하지 않고 dispatch prompt가 `AGENTS.md`와 필요한 public/local 정본 경로를
명시한다. Claude는 safe mode와 strict empty MCP config로 훅·스킬·connector action을 닫는다.
Codex는 user config를 무시하고 web·command network·apps·plugins·memories·fan-out을 닫는다.
2026-08-29 live canary에서 built-in tool allowlist만으로 Claude의 Gmail·Drive action이 남고,
Codex에서는 `workspace-write`만으로 desktop plugin/fan-out이 남는 것을 각각 확인해 이 경계를
추가했다. 최종 canary는 두 runtime 모두 native session 수 불변과 의도한 tool boundary를 통과했다.

### 10.6 현재 의미 계약 수동 파일럿 (DR-049 · 2026-09-16 만료)

교정이 journal·서류철에는 남았지만 다음 산출물의 현재 의미와 완료 검증에 결속되지 않은 실패를
14일 동안 코드 없이 시험한다. 이것은 새 상시 규칙이나 정본이 아니다. 원문·유저 발화·DR이
계속 정본이고, 계약은 작업 하나에 묶인 삭제 가능한 private projection이다. DR-045의 외부 두 줄은
그대로 두며, 내부 계약을 사용자에게 추가로 발화하지 않는다.

표본은 건수가 아니라 실패 계열로 사전 고정한다. `assembly`(현재 핵심·폐기 frame 조립),
`binding`(이미 명시된 규칙의 실행), `observation`(rendered·interactive·lifecycle 실제 표면) 각 1건이다.
한 private 파일에 작업 전 `PRE`와 작업 후 `RESULT`를 append한다. `PRE`는 case ID와 사전 고정한
계열 슬롯을 첫 줄에 두고, 중심·보존, 폐기·불확실, source/handling, 관측할 표면·방법·중단 조건을
담는다. 그 prefix의 byte length와 SHA-256을 private journal에 남겨 선행성을 증명한다. `RESULT`는
선언 표면마다 `PASS|FAIL|UNKNOWN|STALE`, 근거, 실패 사건별 계열, agent/user catch, 준비 시간을
남긴다. 판정이 비면 절차 실패이고,
관측하지 못한 것은 `UNKNOWN`이지 통과가 아니다.

안전 중단선은 private leak 또는 contract-caused nuance loss 각 1건이다. 합격하려면 세 계열을
모두 채우고 준비 시간 중앙값이 5분 이하여야 하며, 폐기 frame 재등장·핵심의 avoidable omission·
실제 표면에서 뒤집힌 PASS가 0이어야 한다. 동시에 최소 1건에서 계약이 누락·재발·거짓 완료를
막거나 PASS 대신 정직한 UNKNOWN을 만들어 실제 판단을 바꿔야 한다. 세 건 모두 판단을 안 바꾸면
무사고여도 폐기한다. 공동편집 중 새 방향 전환은 실패가 아니며, `PRE`에 있던 계약을 놓친 경우만
센다.

14일 안에 세 계열이 안 차면 evidence insufficient로 만료하고 자동화하지 않는다. 같은 결정론적
assembly 동작이 세 건 중 두 번 반복될 때만 read-only renderer를 검토한다. 세 건 모두 준비가
2분 미만이고 conflict·unknown이 없다면 자동화의 한계효용이 없다고 판정한다. closeout은
agent/user catch를 분리 계수하고, 반복 실패가 binding이면 실행 시 심문을, observation이면 해당
실제 surface probe를 검토한다. 종료 증거는 보존하고 후속 closeout DR이 DR-049를 supersede한다.
파일럿 동안에는 AGENTS·CLAUDE·훅·`now.py`·`fresh_worker.py`·검사기 registry를 바꾸지 않는다.

## 11. 시각화 — memory-map.html (`system/` 아래, P3 예정) [신설]

목적: 시스템이 **어떻게 작동하는지**를 overview→디테일로 한 장에서 이해.

- **L0 (조감):** 저장소 박스(컨텍스트·전사·journal·NOW·서류철·auto-memory·ledger·정본) +
  흐름 화살표(기록·생성·회상·복귀·정제) + 훅 배지. 권위 서열을 세로축으로.
- **L1 (카드):** 저장소별 {스키마, 권위, 반감기, 도구, 의식}. 클릭 시 앵커 이동.
- **L2 (시퀀스):** 컴팩션 복구·스레드 복귀·정원사 루프의 순서도 + 라이브 계기
  (journal 줄 수, NOW 나이, 전사 크기, check 결과).
- **생성물이다:** build_memory_map.py (`tools/` 아래, P3 예정)가 memlib 스키마 + 라이브 상태에서 렌더.
  손 편집 금지 — 그림과 구현이 갈라질 수 없게 (§6 그릴링 참조). 렌더 기술은 radar site와
  동일한 자립형 HTML/CSS/SVG (외부 의존 없음).

## 12. 실행 계약 — 판정 후 이렇게 진행한다 [신설]

**자율성 3단 (문 분류의 적용):**
- **①구현 세부** (파일 구조, 함수 분해, 문구): 자율. 보고는 완료 시점에 일괄.
- **②설계 조정** (스키마 필드 추가, 의식 문구 조정, 검출기 추가 — 양방향 문): **진행하되
  DR로 기록하고 완료 보고에 명시.** 되돌리기 쉬우므로 속도 우선.
- **③계약 변경** (권위 서열, 상시 규칙 세트, 불가침 목록, 기훈 소유 문서의 의미 변경,
  Phase 3 다이어트 — 일방향 문): **중단하고 판정 요청.**

**발산 처리:** 구현 중 떠오르는 확장 아이디어는 실행하지 않고 journal `idea` 줄로 적립
(type 7번째로 추가 — DR 대상), Phase 4 재평가에서 일괄 심사. 스코프 크립의 구조적 차단.

**리뷰·검증 (Phase마다):**
1. 자기 검증 — Phase 명세의 체크리스트 + 픽스처 테스트 (check 검출기는 과거 사고 재현으로,
   recall은 known-item 심기로) 
2. 완료 보고 형식 고정 — {변경 파일 목록, 검증 결과, 내린 DR 목록, 발산 적립 목록, 남은 것}
3. 기훈 검수 포인트 명시 — 각 Phase 보고에 "네가 실제로 확인할 것 ≤3개"를 지정
   (예: P1이면 "컴팩션 후 첫 응답에 NOW가 반영되는가"를 다음 컴팩션 때 관찰)

**정제 방식:** PRD·DR은 대화 중 슬쩍 바꾸지 않는다 — 변경은 문서에서, 이력과 함께.
운용 2주 후 Phase 4에서 실측 기반 개정 1회를 예약해 둔다 (그때까지 설계 동결이 기본).

**산출물 요약 (전 Phase):** `state/`(journal·NOW·gardener 리포트) · `tools/`(memlib, now,
recall, wf_gardener, build_memory_map) · `system/`(decisions.md, rituals.md, memory-map.html) ·
`.claude/settings.json` 훅 2종 · 스킬 4종 · CLAUDE.md/AGENTS.md 개정 · 메모리 2건 포인터화.

---

*v1 본문의 §3.2~3.5(상태 층 상세)·성공 기준 1~3·그릴링 1라운드는 v2에 계승·요약됐다.
전문이 필요하면 git 이력에서 v1을 본다. **판정 대상: D1~D15. 판정 즉시 Phase 1 착수.***
