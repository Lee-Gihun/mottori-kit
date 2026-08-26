# 세션 지침

이 워크스페이스는 코드베이스가 아니라 **작업 저장소**다. 여러 트랙을 한 자리에서 굴리고,
세션은 무한히 이어지며, 컨텍스트는 주기적으로 압축된다. 아래 일곱 개는 그 조건에서
실측으로 값을 증명한 규약이다.

인스턴스 고유 규약(이 워크스페이스에서만 참인 것)은 `system/instance-rules.md`에 있다.
없으면 아직 안 쓴 것이다 — `templates/instance-rules.md`를 복사해서 채워라.

**엔진 파일과 인스턴스 파일은 쌍을 이룬다.** 왼쪽은 `git pull`이 덮으므로 고치지 않는다.
오른쪽은 git 밖이라 안전하다. 왼쪽에 뭔가 쓰고 싶으면 오른쪽에 써라.

| 엔진 (업스트림 소유) | 인스턴스 (여기서 쓴다) |
|---|---|
| `CLAUDE.md` 상시 코어 7 | `system/instance-rules.md` |
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
   원문 = `python3 tools/recall.py find` · 처방 전엔 "이미 뭘 했는지"부터 묻는다. 기훈의
   결정·선호·계획은 **그의 발화가 원점** — 요약·기억은 파생물이다. *(Why: 귀속 편향 4회 실측 —
   추측이 정본을 오염시킨다.)*

4. **깊은 스레드 복귀 = 서류철 먼저.** 등록된 스레드는 `python3 tools/now.py threads`.
   깊은 세션을 떠날 땐 델타 5줄 append. *(Why: 컴팩션은 지금 태스크만 보존하고 다른 스레드의
   깊이를 뭉갠다 — 복귀 피상성의 직접 차단선.)*

5. **아웃바운드 금기.** 외부로 나가는 문안(메일·메시지·문서)에 em-dash 금지 · 발송·커밋·
   푸시는 사람 손 (명시적으로 위임한 경우만 예외). *(Why: AI-작성 티 방지 + 비가역 행위는
   소유자 집행 원칙.)*

6. **큰 작업(전수 수집·대규모 병렬·장기 실행) 주문 = `system/WORKING-WITH-AI.md` 먼저.**
   *(Why: 요약이 아니라 계측기 — 660편 실행으로 검증된 프레임.)*

7. **PRD·DR은 대화 중 슬쩍 바꾸지 않는다.** 정책 변경은 문서에서 고치고
   `system/decisions.md`에 DR로 남긴다. *(Why: 기록 없는 결정이 드리프트와 재논의의 뿌리 —
   이 규약 자체가 그 실측에서 나왔다.)*

## 조건부 로드 (해당 상황에서만 읽는다)

- 세션 의식·문서 규약 상세 → `system/rituals.md`
- 사고렌즈 → `system/lenses/README.md` (막힌 문제·설계·결정·명시 요청 시만)
- 총동원 딥패스 → `system/deep-pass.md` (깊이를 주문할 때)
- 런타임 간 토론 → `system/debate/README.md` (Claude·Codex 비동기 논쟁판)
- 기억 시스템 spec → `system/PRD-session-memory.md` · 정보 아키텍처 → `system/PRD-info-architecture.md`
- 설치·이식 → `SETUP.md` · 검증 → `python3 tools/doctor.py`

## 왜 상시 규칙이 일곱 개인가

동시에 지켜지는 지시의 수는 k=5~6에서 막힌다 (`2608.12426`). 규칙을 더 넣으면 각각이
덜 지켜진다. 그래서 새 규칙을 추가하고 싶을 때의 기본 동작은 **조건부 로드 문서로 보내는 것**이고,
상시 코어에 올리려면 기존 하나를 내려야 한다.
