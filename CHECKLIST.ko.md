<!-- source: CHECKLIST.md sha256:f3fcfa9f3799622cab5973ef2cd57f16d8af599078a2c949cb0699e93dab5576 source-of-truth: en -->
# CHECKLIST — 설치 후 확인할 것

`bash setup.sh`와 `python3 tools/doctor.py`가 끝난 뒤의 목록이다.
doctor와 겹치는 기계 확인도 몇 개 있지만, **여기서는 사람이 결과를 판정한다.** doctor는 훅을
declared·command-valid·armed(Codex 신뢰)까지 재고, 실제로 발화해 모델에 들어갔는지(fired/effect)는
못 잰다. 그 구멍이 C절이다.

- `[ ]` 사람이 판단해야 하는 것
- `[기계]` 명령 한 줄로 확인되는 것 — 붙여넣고 결과를 보면 된다

---

## A. 정책 — 다른 걸 하기 전에

이걸 먼저 통과해야 나머지가 의미 있다.

- `[ ]` **회사 머신에 개인 GitHub 리포를 클론해도 되는가.** IT 정책 확인. 안 되면
  회사 Git 호스트에 미러를 두거나, 압축본을 옮기는 방식으로 바꾼다
- `[ ]` **프로젝트 훅이 허용되는가.** 상태 주입 훅은 이 리포의 `.claude/settings.json`(프로젝트
  수준)에 있다. MDM이 관리하는 맥은 프로젝트 훅을 막거나 승인을 요구할 수 있다. 막히면 상태
  자동 주입이 안 돈다 (수동 `python3 tools/now.py render` + 직접 읽기로 대체 가능하지만 그게 원래
  없애려던 규율이다). Claude Code는 리포 루트에서 열어야 `$CLAUDE_PROJECT_DIR`이 이 디렉토리를 가리킨다
- `[ ]` **전사·녹취 도구를 써도 되는가.** `tools/transcribe.py` `tools/diarize.py`는
  미팅 오디오를 다룬다. 녹음 동의와 데이터 보존 정책에 걸린다.
  **정책 확인 전에는 돌리지 마라.** 안 쓸 거면 지우지 말고(추적 엔진 파일이라 다음 pull과
  충돌한다) `system/instance-rules.md`에 실행 금지를 적어라
- `[ ]` **회사 자료를 외부 모델에 넣어도 되는가.** Claude·Codex 사용 승인의 범위가
  어디까지인지. 승인 범위 밖 데이터는 이 워크스페이스에도 두지 않는다

## B. 밸브 — 회사 자료가 나가지 않는가

- `[기계]` 원격이 없거나 허용된 것만인가
  ```bash
  git remote -v          # setup.sh는 클론 origin을 allowlist에 넣는다 (엔진 업데이트 경로). 그 밖의 원격은 doctor가 잡는다
  ```
- `[기계]` 연료가 정말 git 밖인가
  ```bash
  git status --short     # state/ _private/ 가 안 보여야 한다
  git check-ignore -v state/NOW.md system/memory-config.json
  ```
- `[ ]` **원격을 둘 거면 pull-only 자격증명으로 클론했는가.** 엔진 업데이트만 받고
  이쪽에서 밀 수 없게. `.gitignore`가 데이터를 막고 자격증명이 코드를 막는 이중 구조다
- `[ ]` `system/instance-rules.md`의 국경 선언을 채웠는가 (CHANGEME가 남아 있으면 안 썼다는 뜻)

## C. 훅: doctor가 명령 효과까지 알고 실제 발화는 모르는 것

doctor는 SessionStart 명령 출력과 PreCompact 명령의 journal 효과를 임시 인스턴스에서 확인한다.
그 명령이 런타임 dispatcher에서 **실제로 발화했는지**, SessionStart 출력이 모델 컨텍스트에
들어갔는지는 확인할 수 없다.

- `[ ]` **SessionStart 주입 확인.** 새 세션을 열고 그대로 물어라:
  > 지금 NOW에 뭐라고 적혀 있어?

  파일을 읽지 않고 바로 답하면 주입된 것이다. 읽으러 가면 주입이 안 된 것이다
- `[ ]` **PreCompact 실제 발화 확인.** 명령 효과는 doctor가 검증했다. 다음 실제 컴팩션이 일어난 뒤:
  ```bash
  tail -3 state/journal-$(date +%Y-%m).md   # "컴팩션 발생" 줄이 있어야 한다
  test ! -e state/.hook-errors.log && echo "훅 오류 로그 없음" || cat state/.hook-errors.log
  ```
- `[ ]` **Codex 훅 신뢰 승인.** Codex는 훅을 처음 볼 때 신뢰를 물어본다.
  승인하지 않으면 조용히 안 돈다. `codex` 한 번 띄워서 프롬프트가 뜨는지 확인
- `[ ]` **Codex가 AGENTS.md를 읽는가.** 발주 한 번 던지고, 응답이 규약(한국어,
  em-dash 없음, 판정 형식)을 지키는지 본다

## D. 첫 사용 — 실제로 도는지

- `[기계]` 첫 사건 기록 → NOW 재생성 왕복
  ```bash
  python3 tools/now.py log "[system/state] 설치 검증"
  cat state/NOW.md
  ```
- `[기계]` 회상이 이 인스턴스만 보는가 (다른 인스턴스 세션이 섞이면 안 된다)
  ```bash
  python3 tools/recall.py sessions
  ```
  첫 Claude 또는 Codex 세션 전에는 출력 없이 종료코드 0이어도 정상이다. 세션을 한 번
  연 뒤에는 현재 인스턴스 경로만 나오는지 확인해라.
- `[기계]` Codex 발주 왕복 (codex CLI가 있을 때)
  ```bash
  printf '%s\n' "한 줄로 답해라: 지금 이 리포의 상시 코어는 몇 개인가." \
    > system/debate/_p_canary.md
  bash tools/ask_codex.sh system/debate/_p_canary.md > /tmp/codex.log
  tail -15 /tmp/codex.log
  rm system/debate/_p_canary.md
  ```
  `FRESH_WORKER v1`, `capability: workspace-write`, `status: success`가 보여야 한다. receipt는
  4,096 bytes 이하여야 하고 전문은 출력되지 않아야 한다.
- `[ ]` 슬래시 커맨드 `/now` `/recall` `/dossier` `/garden`이 뜨는가
- `[기계]` **검증 게이트가 실제로 막는가.** 세 판 다 확인해라. 하나라도 통과하면 게이트가
  없는 것과 같다. **일회용 클론에서 한다.** 원본에서 하면, 게이트가 뚫렸을 때 1)의 커밋이 실제
  history에 남는다 (2026-09-17 독립 감사 P).
  ```bash
  T="$(mktemp -d)" && git clone -q . "$T/gatetest" && cd "$T/gatetest"
  bash setup.sh --name gatetest --context personal >/dev/null
  bash tools/install_hooks.sh --repair
  bash tools/install_hooks.sh --check
  python3 tools/gate.py baseline

  # 1) 깨진 참조를 만들면 커밋이 막히는가
  #    경로가 system/ 아래인 이유: 리포 루트는 기본거부라 git add 자체가 안 된다
  printf '[없는것](nope-zz.md)\n' > system/_gatetest.md
  git add system/_gatetest.md && git commit -m "막혀야 정상"   # 막혀야 한다. 뚫려도 일회용 클론이다
  git reset -q HEAD system/_gatetest.md 2>/dev/null; rm -f system/_gatetest.md

  # 2) 검사기가 죽으면 "이슈 0"이 아니라 차단인가
  python3 tools/gate.py dirty
  cp tools/linkcheck.py /tmp/lc.bak && printf 'def ((((\n' >> tools/linkcheck.py
  echo '{}' | python3 tools/gate.py check     # "측정 불능" 차단이 떠야 한다
  cp /tmp/lc.bak tools/linkcheck.py

  # 3) 기준선이 깨지거나 사라지면 둘 다 차단인가 (자동 채택 금지)
  cp state/.gate-baseline.json /tmp/bl.bak
  rm state/.gate-baseline.json
  python3 tools/gate.py dirty && echo '{}' | python3 tools/gate.py check
  cp /tmp/bl.bak state/.gate-baseline.json
  printf '{ 깨짐' > state/.gate-baseline.json
  python3 tools/gate.py dirty && echo '{}' | python3 tools/gate.py check
  cp /tmp/bl.bak state/.gate-baseline.json

  cd - >/dev/null && rm -rf "$T"      # 일회용 클론 정리
  ```
  **게이트가 못 보는 것 (범위를 알고 써라).** 변경 관측(PostToolUse)은 `Write|Edit|NotebookEdit`만
  본다. Bash 편집, 외부 writer, Codex 편집은 pre-commit에서만 걸린다. interrupt로 끝난 턴은
  다음 프롬프트의 `gate.py resume`이 회수한다. `git commit --no-verify`는 전부 우회한다.

## E. 백업 — 이 리포가 안 해주는 것

**`.gitignore`가 데이터를 막는다는 건 데이터가 백업되지 않는다는 뜻이다.**
`state/`의 journal과 서류철, `_private/`의 원장은 이 머신에만 있다.

- `[ ]` 이 워크스페이스가 회사 백업 대상 경로에 있는가 (Time Machine, 회사 MDM 백업 등)
- `[ ]` 아니면 별도 백업을 정했는가
- `[ ]` **`git clean -xdf`의 위험을 안다.** 이 명령은 untracked 파일을 지운다 —
  즉 `state/`와 `_private/`를 통째로 날린다. 이 디렉토리에서 쓰지 마라

## F. 첫 주 안에

- `[ ]` 트랙 하나 등록 (`system/memory-config.json`의 `tracks`)
- `[ ]` 여러 날 이어지는 주제가 생기면 서류철 하나 지정 (`threads`)
- `[ ]` 컴팩션을 한 번 겪고 나서: 복구된 첫 응답이 상태를 알고 있는가.
  모르면 훅이 안 도는 것이고, C의 첫 항목으로 돌아간다

## G. 엔진을 고쳤을 때

이 킷의 도구를 회사에서 고쳤다면, 그 수정이 개인 머신으로 자동으로 가는 경로는 **없다**.
의도적으로 없앤 것이다. 자동 경로를 만들면 "이 수정이 회사 IP를 안 담았다"를 기계가
판정해야 하는데, 그건 문자열 검사로 증명할 수 없다.

- `[ ]` 일반 버그면: 증상만 적어 두고 개인 머신에서 재현해서 고친다
- `[ ]` 그래도 올려야 하면: 사람이 diff를 눈으로 읽고 회사 식별자·수치·코드네임이 없는지
  확인한 뒤 별도 쓰기 권한으로 올린다

## 항목 근거 연결

이 체크리스트는 자동 검사가 관찰할 수 없는 사람 권한, 회사 정책, 복구 가능성만 남긴다.
각 항목의 Why는 `tools/doctor.py`가 자동 판정하지 못하는 경계와 `system/instance-rules.md`의
인스턴스 선언을 서로 대조하려는 것이다. 훅과 명령 개수는 현재 배선을 확인하는 점검값이며,
그 숫자 자체가 정책은 아니다.
