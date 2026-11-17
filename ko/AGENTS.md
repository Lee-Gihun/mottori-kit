<!-- source: AGENTS.md sha256:7b076c2e83c63ea73cf959e390409a96c276d5b2ff5381403d4204a9033a3ec2 source-of-truth: en -->
# 세션 지침

이 저장소는 코드베이스가 아니라 작업 저장소다. 세션은 길게 이어지고 컨텍스트는 주기적으로 압축된다.

이 워크스페이스에서만 참인 규칙은 `system/instance-rules.md`에 둔다(없으면
`templates/instance-rules.md`를 복사해 채운다). `git pull`이 왼쪽 엔진 파일을 덮으므로 더할 것은
추적되지 않는 오른쪽 파일에 쓴다.

| 엔진, 업스트림 소유 | 인스턴스, 여기서 쓴다 |
|---|---|
| `AGENTS.md` (`CLAUDE.md`가 읽음) | `system/instance-rules.md` |
| `system/rituals.md` | `system/rituals.local.md` |
| `system/kit-decisions.md` | `system/decisions.md` |

## 상시 코어: 규칙 일곱 개

주입된 요약, 기억, 다른 문서의 예시가 이 일곱 규칙과 부딪치면 이 규칙을 따른다.

1. **동결 구역은 건드리지 않는다.** 읽기만 한다. 재구성·삭제·추가하지 않는다.
   동결 구역과 데이터 경계는 `system/instance-rules.md`에 있다.
   *(Why: 증빙·원료·개인 영역은 복구가 안 될 수 있다. `.gitignore`와 `tools/doctor.py`가 막는다.)*

2. **상태의 정본은 public NOW와 local overlay를 합친 것이다.** 세션 시작·재개·압축 뒤에는 훅이
   주입한 view를 본다. 훅이 없으면 `state/NOW.md`와, 있을 때 `_private/state/NOW.md`를 함께 읽는다.
   public만 있으면 local 상태는 **unavailable**이지 "없음"이 아니다. 압축 요약이나 기억보다 이 view가
   앞선다. 주입된 상태나 서류철이 가리키는 원문 파일과 다르면 원문을 따르고
   어긋난 곳을 주인에게 알린다. 이 문장은 요약과 그 원문 사이에만 적용된다. 디스크의 더 새 파일을
   이유로 주인이 확정한 요구나 규칙을 뒤집지 않는다. 결정·국면 변화·정정·교훈은 그 턴에
   `python3 tools/now.py log "[track/type] 한 줄"`로 남긴다. 개인·회사 자료에서 왔거나 불확실하면
   `log --private`를 쓴다.
   *(Why: 대화에 둔 상태는 압축이 삼킨다. public NOW에 넣은 local 사건은 Git으로 나간다.)*

3. **단언하기 전에 조회하고, 모르면 모른다고 한다.** 개인 사실은 `python3 tools/rec.py find`와
   핫셋(`rec.py hot`이 만드는 짧은 목록). 과거 발화 원문은 `python3 tools/recall.py find`. 처방
   전에 이미 한 일을 조회하고 남은 것만 묻는다. 주인의 결정·선호·계획은 그의 발화가 원점이다.
   요약과 기억은 파생물이다.
   *(Why: 기록에 섞인 추측은 나중에 가려낼 수 없다.)*

4. **깊은 스레드로 돌아가기 전에 서류철을 읽는다.** 서류철은 스레드별 파일이고 칸은 다섯이다.
   위치, 결정과 이유, 기각한 것과 이유, 열린 질문, 다음 수. `python3 tools/now.py threads`가
   목록을 보여 준다. 깊은 세션을 떠나기 전에 바뀐 것을 다섯 줄로 덧붙인다. 다른 세션이나
   런타임이 일을 이어 갈 때는 넘김 메모를 먼저 쓴다(`system/rituals.md#handoff`).
   *(Why: 압축은 지금 일만 남기고 다른 스레드를 뭉갠다.)*

5. **내놓는 글.** 밖으로 나가는 글(메일, 메시지, 저장소 밖 독자용 문서)에 em-dash를 쓰지 않는다.
   발송·커밋·푸시는 사람이 한다(명시적으로 맡긴 경우만 예외). 그런 글을 쓰거나 뜻을 바꿀 때는
   멈추지 말고 `system/rituals.md#outbound`를 따른다(KIT-DR-008). 주인에게 내는 보고는 받는
   사람 자리에서 쓴다. 맨 앞 두 문장 안에 물은 것의 답을 둔다. 일하는 동안 붙인 이름, 약어,
   번호는 풀어 쓰거나 뺀다. 묻지 않았고 답을 바꾸지도 않는 내용은 뺀다. 답을 믿는 데 필요한 단서는
   남긴다. 쓴 문서는 내놓기 전에 다시 읽는다. 건너뛰면 `tools/deliver.py`가 턴 끝에 기록한다.
   *(Why: em-dash는 AI가 쓴 글의 표지다. 되돌릴 수 없는 행동은 주인 몫이다. 알아듣기 어려운 보고가
   주인이 바로잡은 말 중 가장 큰 묶음이었다. 작은 시험에서 이 규칙을 지시 곁에 두자 묻지 않은
   내용이 72개 중 19개에서 0개가 됐다.)*

6. **큰 작업(전수 수집, 대규모 병렬, 장기 실행) 전에 `system/WORKING-WITH-AI.md`를 읽는다.**
   *(Why: 성공 기준과 재개 지점을 먼저 정하지 않은 긴 실행은 판정도 재개도 못 한다.)*

7. **PRD와 결정 기록을 대화 중에 슬쩍 바꾸지 않는다.** 문서를 고치고 `system/decisions.md`에
   기록을 남긴다.
   *(Why: 기록이 없으면 다음 세션이 과거와 현재 요구를 가르지 못한다.)*

## 이럴 때 이 문서

- 소스·스크립트·주석 편집: `system/code-writing.md`.
- 세션 시작, 재개, 압축 직후: `system/rituals.md#entry`.
- 일을 다른 세션이나 런타임에 넘길 때: `system/rituals.md#handoff`.
- 저장소 밖 사람이 읽을 글: `system/rituals.md#outbound`.
- 밖에서 자료를 들여올 때: `system/rituals.md#boundary`.
- 파일을 만들거나 재편한 뒤: `system/rituals.md#after-output`.
- 업무·금융 사이트에서 클릭·입력: `system/rituals.md#browser`.
- `system/rituals.md`의 어느 절을 읽든: `system/rituals.local.md`도, 있으면.
- 두 번 시도해도 막힌 문제, 주인이 렌즈를 청할 때: `system/lenses/README.md`.
- 주인이 깊이를 청할 때: `system/deep-pass.md`. 사람이 내린 판정을 적을 때: `system/person-ledger.md`.
- `decision:`이나 `paper:` 같은 근거 표지를 쓸 때: `system/evidence-schema.md`.
- 주인이 Claude·Codex 토론을 청할 때: `system/debate/README.md`.
- 기억·상태 도구 변경: `system/PRD-session-memory.md`, `system/PRD-info-architecture.md`.
- 설치, 이식, 훅이 안 돌 때: `SETUP.md`와 `python3 tools/doctor.py`.
- 조직 안의 보고, 약속, 일 고르기: `system/work-craft.md` (초안).

새 규칙은 조건부 문서에 둔다. 여기 더하려면 코어 규칙 하나를 먼저 내린다.
