<!-- source: AGENTS.md sha256:3c526eff40df42aab8fe10eefcca7bf842a20e0dc1b12018628bcfdacde57089 source-of-truth: en -->
# 세션 지침

이 워크스페이스는 코드베이스가 아니라 **작업 저장소**다. 여러 트랙을 한 자리에서 굴리고,
세션은 이어지고 컨텍스트는 주기적으로 압축된다. 상시 규약은 데이터 경계·원점 귀속·
세션 연속성을 보존한다.

인스턴스 고유 규약(이 워크스페이스에서만 참인 것)은 `system/instance-rules.md`에 있다.
없으면 아직 안 쓴 것이다 — `templates/instance-rules.md`를 복사해서 채워라.

**엔진 파일과 인스턴스 파일은 쌍을 이룬다.** 왼쪽은 `git pull`이 덮으므로 고치지 않는다.
오른쪽은 git 밖이라 안전하다. 왼쪽에 뭔가 쓰고 싶으면 오른쪽에 써라.

| 엔진 (업스트림 소유) | 인스턴스 (여기서 쓴다) |
|---|---|
| `AGENTS.md` 상시 코어 7 (`CLAUDE.md`가 import) | `system/instance-rules.md` |
| `system/rituals.md` | `system/rituals.local.md` |
| `system/kit-decisions.md` | `system/decisions.md` |

## 상시 코어 (이 7개만 항상 유효 — 근거 없는 규칙은 두지 않는다)

1. **불가침.** 동결 구역은 재구성·삭제·추가 금지, 읽기만 한다. 외부 발송은 사람 손으로만.
   이 인스턴스의 동결 구역 목록과 데이터 국경은 `system/instance-rules.md`.
   *(Why: 증빙·원료·개인 영역은 복구 불가 — 한 번의 실수가 파산인 영역. 그리고 국경은
   규율이 아니라 구조로 막는다 — `.gitignore`와 `tools/doctor.py`의 밸브 검사가 그 집행부다.)*

2. **상태 정본 = public NOW + local overlay.** 세션 시작·재개·컴팩션 후 훅이 합친 view를
   확인한다. 훅이 없으면 `state/NOW.md`와, 존재할 때 `_private/state/NOW.md`를 함께 읽는다.
   public만 있으면 local 상태는 **unavailable**이지 "없음"이 아니다. 컴팩션 요약·기억과
   충돌하면 이 view가 이긴다. 결정·국면·정정·교훈은 그 턴에 `python3 tools/now.py log
   "[track/type] 한 줄"`; 개인·회사 유래 또는 불확실하면 `log --private`로 내린다. *(Why:
   상태를 대화에 두면 압축이 삼키고, local 사건을 public NOW에 섞으면 Git이 국경을 우회한다.)*

3. **단언 전 조회, 모르면 모른다.** 개인 사실 = `python3 tools/rec.py find` + 핫셋 · 과거 발화
   원문 = `python3 tools/recall.py find` · 처방 전엔 이미 뭘 했는지 먼저 조회하고 남은 미지만 묻는다. 소유자의
   결정·선호·계획은 **그의 발화가 원점** — 요약·기억은 파생물이다. *(Why: 귀속에는 조회 가능한 원점이 필요하다. 추측은 정본을 오염시킨다.)*

4. **깊은 스레드 복귀 = 서류철 먼저.** 등록된 스레드는 `python3 tools/now.py threads`.
   깊은 세션을 떠날 땐 델타 5줄 append. *(Why: 컴팩션은 지금 태스크만 보존하고 다른 스레드의
   깊이를 뭉갠다 — 복귀 피상성의 직접 차단선.)*

5. **아웃바운드 금기.** 외부로 나가는 문안(메일·메시지·문서)에 em-dash 금지 · 발송·커밋·
   푸시는 사람 손 (명시적으로 위임한 경우만 예외). *(Why: AI-작성 티 방지 + 비가역 행위는
   소유자 집행 원칙.)*
   발신 산출물을 쓰거나 의미를 바꿀 때는 멈추지 말고 `system/rituals.md`의 외부 문안 절을 따른다
   (KIT-DR-008).

6. **큰 작업(전수 수집·대규모 병렬·장기 실행) 주문 = `system/WORKING-WITH-AI.md` 먼저.**
   *(Why: 큰 작업은 성공 조건·근거 범위·중단과 재개 방법을 먼저 정해야 한다.)*

7. **PRD·DR은 대화 중 슬쩍 바꾸지 않는다.** 정책 변경은 문서에서 고치고
   `system/decisions.md`에 DR로 남긴다. *(Why: 결정 기록이 없으면 다음 세션이 과거와 현재 요구를 구별할 수 없다.)*

## 조건부 로드

- 코드·스크립트·주석·docstring: `system/code-writing.md` (소스 편집 때) (해당 상황에서만 읽는다)

- 세션 의식·외부 문안·문서 규약 상세 → `system/rituals.md`
- 사고렌즈 → `system/lenses/README.md` (막힌 문제·설계·결정·명시 요청 시만)
- 총동원 딥패스 → `system/deep-pass.md` (깊이를 주문할 때)
- 런타임 간 토론 → `system/debate/README.md` (Claude·Codex 비동기 논쟁판)
- 기억 시스템 spec → `system/PRD-session-memory.md` · 정보 아키텍처 → `system/PRD-info-architecture.md`
- 설치·이식 → `SETUP.md` · 검증 → `python3 tools/doctor.py`
- 조직 안의 보고·약속·일 고르기 판단 → `system/work-craft.md` (초안)

## 왜 상시 규칙이 일곱 개인가

일곱 개는 중요한 경계와 복구 규칙을 상시 유지하기 위한 운용 기본값이며 모델의 보편 능력 상한이 아니다.
새 규칙의 기본 위치는 **조건부 로드 문서**다. 상시 코어에 올리려면 기존 하나를 내리고,
새 규칙이 막을 실패와 기존 의무의 중복을 확인한다.
