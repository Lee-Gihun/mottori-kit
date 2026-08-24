# CHECKLIST — 설치 후 확인할 것

`bash setup.sh`와 `python3 tools/doctor.py`가 끝난 뒤의 목록이다.
doctor가 기계적으로 잡는 건 여기 없다. **여기 있는 건 doctor가 못 잡는 것들이다.**

- `[ ]` 사람이 판단해야 하는 것
- `[기계]` 명령 한 줄로 확인되는 것 — 붙여넣고 결과를 보면 된다

---

## A. 정책 — 다른 걸 하기 전에

이걸 먼저 통과해야 나머지가 의미 있다.

- `[ ]` **회사 머신에 개인 GitHub 리포를 클론해도 되는가.** IT 정책 확인. 안 되면
  회사 Git 호스트에 미러를 두거나, 압축본을 옮기는 방식으로 바꾼다
- `[ ]` **user-level 훅이 허용되는가.** MDM이 관리하는 맥은 `~/.claude/settings.json`을
  무시하도록 걸려 있을 수 있다. 무시되면 상태 자동 주입이 안 돈다
  (수동 `python3 tools/now.py render` + 직접 읽기로 대체 가능하지만 그게 원래 없애려던 규율이다)
- `[ ]` **전사·녹취 도구를 써도 되는가.** `tools/transcribe.py` `tools/diarize.py`는
  미팅 오디오를 다룬다. 녹음 동의와 데이터 보존 정책에 걸린다.
  **정책 확인 전에는 돌리지 마라.** 안 쓸 거면 두 파일을 지워라
- `[ ]` **회사 자료를 외부 모델에 넣어도 되는가.** Claude·Codex 사용 승인의 범위가
  어디까지인지. 승인 범위 밖 데이터는 이 워크스페이스에도 두지 않는다

## B. 밸브 — 회사 자료가 나가지 않는가

- `[기계]` 원격이 없거나 허용된 것만인가
  ```bash
  git remote -v          # work 인스턴스는 비어 있는 게 기본
  ```
- `[기계]` 연료가 정말 git 밖인가
  ```bash
  git status --short     # state/ _private/ 가 안 보여야 한다
  git check-ignore -v state/NOW.md system/memory-config.json
  ```
- `[ ]` **원격을 둘 거면 pull-only 자격증명으로 클론했는가.** 엔진 업데이트만 받고
  이쪽에서 밀 수 없게. `.gitignore`가 데이터를 막고 자격증명이 코드를 막는 이중 구조다
- `[ ]` `system/instance-rules.md`의 국경 선언을 채웠는가 (CHANGEME가 남아 있으면 안 썼다는 뜻)

## C. 훅 — doctor가 "유효 JSON"까지만 아는 것

doctor는 훅 명령이 올바른 JSON을 뱉는 것까지 확인한다. 그 JSON이 **실제로 모델
컨텍스트에 들어갔는지**는 확인할 수 없다. 훅 출력은 모델에게만 가고 셸로 안 오기 때문이다.

- `[ ]` **SessionStart 주입 확인.** 새 세션을 열고 그대로 물어라:
  > 지금 NOW에 뭐라고 적혀 있어?

  파일을 읽지 않고 바로 답하면 주입된 것이다. 읽으러 가면 주입이 안 된 것이다
- `[ ]` **PreCompact 기록 확인.** 다음 컴팩션이 일어난 뒤:
  ```bash
  tail -3 state/journal-$(date +%Y-%m).md   # "컴팩션 발생" 줄이 있어야 한다
  cat state/.hook-errors.log 2>/dev/null    # 있으면 훅이 실패한 기록이다
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
- `[기계]` Codex 발주 왕복 (codex CLI가 있을 때)
  ```bash
  echo "한 줄로 답해라: 지금 이 리포의 상시 코어는 몇 개인가." > /tmp/_p.md
  nohup bash tools/ask_codex.sh /tmp/_p.md > /tmp/codex.log 2>&1 &
  sleep 60 && tail -5 /tmp/codex.log
  ```
- `[ ]` 슬래시 커맨드 `/now` `/recall` `/dossier` `/garden`이 뜨는가
- `[기계]` **검증 게이트가 실제로 막는가.** 세 판 다 확인해라. 하나라도 통과하면 게이트가
  없는 것과 같다.
  ```bash
  bash tools/install_hooks.sh && python3 tools/gate.py baseline

  # 1) 깨진 참조를 만들면 커밋이 막히는가
  #    경로가 system/ 아래인 이유: 리포 루트는 기본거부라 git add 자체가 안 된다
  printf '[없는것](nope-zz.md)\n' > system/_gatetest.md
  git add system/_gatetest.md && git commit -m "막혀야 정상"   # 막혀야 한다
  git reset -q HEAD system/_gatetest.md && rm system/_gatetest.md

  # 2) 검사기가 죽으면 "이슈 0"이 아니라 차단인가
  python3 tools/gate.py dirty
  cp tools/linkcheck.py /tmp/lc.bak && printf 'def ((((\n' >> tools/linkcheck.py
  echo '{}' | python3 tools/gate.py check     # "측정 불능" 차단이 떠야 한다
  cp /tmp/lc.bak tools/linkcheck.py

  # 3) 기준선이 깨지면 차단인가 (삭제는 채택 + 통보, 손상은 차단)
  cp state/.gate-baseline.json /tmp/bl.bak && printf '{ 깨짐' > state/.gate-baseline.json
  python3 tools/gate.py dirty && echo '{}' | python3 tools/gate.py check
  cp /tmp/bl.bak state/.gate-baseline.json
  ```
  **게이트가 못 보는 것 (범위를 알고 써라).** Stop 훅은 `Write|Edit|NotebookEdit`만 본다.
  Bash 편집, 외부 writer, Codex 편집은 pre-commit에서만 걸린다. interrupt로 끝난 턴은
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
