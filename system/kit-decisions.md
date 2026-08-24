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
기각 대안: 전사 경로를 config 항목으로 — 사람이 안 고치면 recall이 0건을 내고 정상 종료한다.

### DR-002 데이터 국경은 구조로 막는다 — 밸브 3층 (2026-08-24 · active)
결정: **1층 `.gitignore`** — 엔진만 추적, 인스턴스 데이터는 태생부터 git 밖.
**2층 인스턴스 선언** — `instance.context`와 `remote_allowlist`, doctor의 밸브 검사(탐지층).
**3층 자격증명** — work 클론은 pull-only.
맥락: 2층 단독은 밸브가 아니다. 사고를 내는 같은 tree가 자기 경계값도 고칠 수 있기 때문이다.
차단은 1층과 3층이 맡고 2층은 조기 경보다.
부수 결정: `~/.codex/sessions`는 머신 전역이므로 recall이 rollout 첫 줄 `payload.cwd`로
인스턴스를 거른다. Claude 전사는 프로젝트별 디렉토리라 이 문제가 없다.

### DR-003 훅은 fail-safe하되 침묵하지 않는다 (2026-08-24 · active)
결정: 훅은 항상 exit 0 (세션을 막지 않는다). 대신 SessionStart 실패 분기가 **유효 JSON으로
경고를 주입**하고, PreCompact 실패는 `state/.hook-errors.log`에 남는다.
맥락: fail-safe 자체는 옳다 — 훅이 세션을 막으면 그게 더 나쁘다. 문제는 셸의 `2>/dev/null || true`와
파이썬의 `except: pass`가 겹쳐 **이중 침묵**이 된 것이다. 설치돼 보이는데 죽은 상태가 만들어진다.
기각 대안: 실패 시 stderr 노출 — 도구를 일부러 안 깐 정상 상황에서도 시끄러워진다.
그래서 "훅 정의가 있는데 도구가 없다"는 경우에만 시끄럽게 한다.
