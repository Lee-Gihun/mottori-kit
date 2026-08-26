# mottori-kit

무한 세션에서 상태와 깊이를 잃지 않기 위한 **에이전트 워크스페이스 엔진**.
Claude Code와 Codex가 같은 규약 위에서 돌고, 컴팩션을 넘어 작업이 이어진다.

`git clone` → `bash setup.sh` → `python3 tools/doctor.py`. 5분이면 쓸 수 있다.

---

## 무엇을 해결하나

무한 세션의 실패는 둘이고 원인이 다르다.

**상태 손실.** 낡은 스냅샷이 정본 행세를 한다. 실측: 8/8자 메모리가 8/15까지 현재 상태로
행세했고, 사람이 직접 정정해줘야 했다.
→ 상태를 대화가 아니라 **디스크**에 둔다. 명시된 public track은 `state/journal-*.md`와
`state/NOW.md`로, 미등재·`--private` 사건은 `_private/state/`의 local journal과 overlay로 간다.
SessionStart 훅은 두 NOW를 합쳐 주입하며, local이 없는 clone은 그 상태를 `unavailable`로 밝힌다.

**깊이 손실.** 컴팩션은 *지금 하던 일*의 연속성을 위해 요약하므로 다른 스레드의 논증 결이
구조적으로 뭉개진다. 며칠 전 결론에 도달했던 주제로 돌아가면 얕은 얘기를 다시 한다.
→ 스레드마다 **서류철** 하나를 지정한다. 다섯 칸(위치·확정+왜·기각+왜·미결·다음 수).
복귀할 땐 서류철부터 읽고, 떠날 땐 델타 5줄을 남긴다.

그리고 잃은 게 아니라 **안 뒤진 것**이 있다. 전 대화 원문이 `~/.claude/projects/`에 통째로
남아 있다 (이 리포의 원본 인스턴스 기준 단일 세션 523MB). `recall.py`가 그걸 grep한다.

## 구성

```
tools/           엔진. 16개 중 핵심 넷은 memlib · now · recall · rec
  memlib.py      스키마 정본. 나머지가 전부 여기서 import
  now.py         journal append · NOW 렌더 · 드리프트 검사 · 훅 진입점
  recall.py      전사 원장 표적 검색 (Claude jsonl + Codex rollout)
  rec.py         개인 사실 원장 — 원자 노트 + 감사 사슬
  ask_codex.sh   Codex 발주. 두 런타임 티키타카의 실행부
  doctor.py      설치 검증기
system/          규약. PRD 둘 · rituals · 렌즈 13종 · deep-pass · WORKING-WITH-AI
.claude/         Claude 훅 3종 + 슬래시 커맨드 4종
.codex/          Codex 훅 2종 (SessionStart · PreCompact)
templates/       인스턴스가 채울 것들
```

## 설계 원칙 넷

**상태는 디스크에.** 남아야 하는 것은 전부 파일로 떨어지고, "남은 게 뭔지"를 그 파일들로부터
다시 계산하는 도구가 있다. 이게 없으면 한 세션을 못 넘고, 있으면 무한히 이어붙일 수 있다.

**생성물과 원장을 나눈다.** `NOW.md`·`hotset.md`·`memory-map.html`은 손으로 고치지 않는다.
고칠 게 있으면 원장을 고치고 다시 만든다. 그래야 그림과 구현이 갈라질 수 없다.

**규칙에 Why를 붙인다.** 근거를 못 쓰는 규칙은 삭제 후보다. 컨텍스트 파일이 무한히 자라는
원인은 지시가 아니라 근거가 먼저 썩기 때문이다.

**상시 규칙은 일곱 개.** 동시 준수 가능한 지시 수는 k=5~6에서 막힌다. 더 넣으면 각각이
덜 지켜진다. 나머지는 조건부 로드 문서로 보낸다.

## 데이터는 하나도 안 들어 있다

이 리포는 엔진만 추적한다. `state/` `_private/` `system/memory-config.json`은
`.gitignore`가 태생부터 막는다. 규율이 아니라 구조다 — git이 안 보므로 실수로 푸시할 수 없다.

뒤집어 말하면 **인스턴스 데이터는 이 리포로 백업되지 않는다.** 그 백업은 따로 마련해야 한다.

## 안 실은 것

- **녹취 워처 3종** (`watch_recordings` `ingest_recording` `recording_watchd`) — 개인 장비
  어댑터라 계정 경로가 박혀 있다. 전사 엔진(`transcribe.py` `diarize.py`)만 실었고,
  회사 머신에서 미팅 녹음은 기능 문제가 아니라 동의·보존 정책 문제다. 정책 확인 전엔 돌리지 마라.
- **동결 구역 체크섬 원장** — 인스턴스 고유 데이터다. 패턴만 쓰면
  `shasum -a 256 <구역>/** > integrity.sha256`, 검증은 `shasum -c`. 원장은 구역 **밖**에 둔다.
- **과거 결정 기록·토론 라운드·인물 원장** — 전부 원본 인스턴스의 역사다.

## 시작

```bash
git clone <이 리포> ~/work
cd ~/work
bash setup.sh
python3 tools/doctor.py
```

자세한 절차는 `SETUP.md`. 설치 후 사람이 확인할 것은 `CHECKLIST.md`.
