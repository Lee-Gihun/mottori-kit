# SETUP — 이 디렉토리를 세팅하는 법

**이 문서는 에이전트에게 주는 지시서다.** 새 머신에서 클론한 다음, Claude Code 또는 Codex를
이 디렉토리에서 열고 이렇게 말하면 된다:

> SETUP.md 읽고 이 디렉토리를 세팅해줘. 끝나면 doctor 결과를 보여줘.

사람이 직접 할 거면 아래를 순서대로 하면 된다. 5분 걸린다.

---

## 0. 이게 무엇인지 먼저 (에이전트가 읽을 것)

이 리포는 **엔진만** 들어 있다. 도구·규약·훅 배선이 전부고, 데이터는 하나도 없다.
세팅이란 이 엔진에 **이 머신에서 쓸 인스턴스 정체를 부여하는 일**이다.

세팅이 끝나면 이 디렉토리는 그 자체로 작업 워크스페이스가 된다. 별도의 "프로젝트 폴더"를
만들 필요가 없다. 문서·노트·트랙을 여기 안에 두고 굴리면 된다.

**절대 하지 말 것 둘.**
- `system/memory-config.json`의 `instance.context`를 `personal`로 두고 회사 자료를 넣지 마라.
  그 값이 밸브의 근거값이다 (`tools/doctor.py`의 밸브 검사).
- 인스턴스가 만들어낸 것(`state/` `_private/`)을 git에 추가하지 마라. `.gitignore`가 이미
  막고 있으니 `git add -f`를 쓰지 않으면 된다.

## 1. 전제 확인

```bash
python3 --version     # 3.8 이상
git --version
which claude codex    # 둘 중 하나만 있어도 시작은 된다
node --version        # 정원사(/garden)용. 없어도 나머지는 다 돈다
```

## 2. 인스턴스 설정 만들기

```bash
bash setup.sh
```

대화형으로 인스턴스 이름과 context(personal/work)를 묻고
`system/memory-config.json`을 만든다. 비대화 모드도 있다:

```bash
bash setup.sh --name tinder-work --context work
```

`setup.sh`가 하는 일은 넷뿐이다.
1. `templates/memory-config.json` → `system/memory-config.json` 복사 후 이름·context 치환
2. `templates/instance-rules.md` → `system/instance-rules.md` 복사
3. `state/` 준비 + 첫 journal 엔트리 기록
4. `python3 tools/now.py render`로 첫 NOW 생성

기존 schema v1/v2/v3 인스턴스를 v4로 올리거나 v4 설정을 보존해 다시 적용할 때는 같은 이름·context로
`bash setup.sh --force`를 실행한다. 기존 config는 `.bak`으로 남고 트랙·검사·공개 목록은 보존된다.
단, v1~v3의 nonempty `threads[]`에는 public 판정 provenance가 없으므로 자동 승격하지 않고 중단한다.
확인된 public 항목과 local 항목을 사람이 먼저 분리한 뒤 재실행한다. 검증된 v4 `threads[]`만 그대로
보존한다. v3는 기존 공개 목록을 과거 journal 행의 provenance로 고정하고, v1/v2에는 그 판정이
없으므로 기존 journal 전부를 fail-closed legacy-private로 둔다. 경계는 migration 전 마지막 journal
timestamp다. malformed journal·config는 추측해 덮지 않는다. 끝나면 `python3 tools/doctor.py`를 다시 돌린다.

새 설치를 되돌리려면 만들어진 세 파일을 지우면 된다. migration을 되돌릴 때는 내용을 확인한
뒤 `system/memory-config.json.bak`을 복원한다. 되돌릴 수 없는 일은 하지 않는다.

## 2b. 검증 후방선 설치

```bash
bash tools/install_hooks.sh --repair
bash tools/install_hooks.sh --check
```

`.git/hooks/`는 clone으로 따라오지 않는다. 이걸 한 번 돌려야 pre-commit 후방선이 생긴다.

**왜 필요한가.** Stop 게이트는 `Write|Edit|NotebookEdit`만 본다. Bash 편집, 외부 writer,
Codex 편집, 사용자 interrupt는 못 본다. pre-commit은 실제로 커밋되는 index를 검사해서
그 구멍을 닫는다. (`--no-verify`는 여전히 우회다. 계약이 아니라 후방선이다.)

이미 다른 pre-commit이 있으면 덮어쓰지 않고 멈춘다. 그때는 내용을 보고 직접 합쳐라.

## 3. 검증

```bash
python3 tools/doctor.py
python3 tools/gate.py baseline    # 이 리포의 현재 이슈를 기준선으로
```

기준선을 안 세우면 게이트는 삭제와 첫 설치를 구분할 수 없어 fail-closed로 막는다.
`setup.sh`는 첫 초기화에서 baseline을 만들지만, 수동 설치·복구 때는 위 명령을 직접 실행한다.

**FAIL이 0이어야 세팅 완료다.** warn은 상황에 따라 정상이다 (예: codex CLI 미설치).

doctor가 마지막에 인쇄하는 **"자동 검사 불가"** 네 개는 기계가 확인할 수 없는 것들이다.
그 목록을 사람에게 그대로 전달해라. 확인했다고 대신 말하지 마라.

## 4. 인스턴스 규약 채우기

`system/instance-rules.md`를 열어 이 워크스페이스의 국경을 선언한다.
최소 셋: 무엇이 반입물인가 · 어디로 착지하는가 · 어느 원격으로도 나가면 안 되는 것은 무엇인가.

`system/rituals.md`의 "데이터 국경" 절이 왜 이걸 인스턴스마다 따로 쓰는지 설명한다.
방향을 잘못 베끼면 규약이 거꾸로 작동한다.

## 5. 첫 트랙 등록

`system/memory-config.json`의 `tracks`에 지금 굴리는 작업 갈래를 넣는다.
트랙 하나 = 정본 문서 하나. 없으면 빈 배열로 두고 나중에 추가해도 된다.

```json
{ "key": "onboarding", "name": "온보딩", "canonical": "onboarding/tracker.md" }
```

등록하면 `state/NOW.md`의 온도판에 그 트랙의 신선도가 자동으로 뜬다.

## 5b. 자기 점검 — 문서가 자기 안에서 닫히는가

```bash
python3 tools/linkcheck.py
```

**`broken: 0`이 목표다.** 여기서 깨진 참조가 나오면 이 리포가 없는 파일을 가리키고 있다는
뜻이고, 그 문서를 읽는 에이전트는 따라갈 수 없는 경로를 보게 된다.

setup 직후에는 원장 핫셋 하나가 남는다 (`rec.py hot`의 산출물이라 첫 사실을 기록해야
생긴다). 지금 만들 거면:

```bash
python3 tools/rec.py new <id> --claim="..." --status=확정 --origin="..." --domain=...
python3 tools/rec.py hot
```

*(`rec.py new`만 원장 부재 상태에서 돈다. `hot`·`find`·`check`는 원장이 있어야 한다 —
빈 원장에 대고 조회하면 "없다"와 "안 만들었다"를 구별할 수 없기 때문이다.)*

## 6. 전역 설정 (선택, 한 번만)

턴마다 현재 시각을 주입하는 훅은 이 리포의 `.claude/settings.json`에 이미 들어 있다.
다른 디렉토리에서도 쓰고 싶으면 `~/.claude/settings.json`에 같은 걸 넣는다.

```json
{ "hooks": { "UserPromptSubmit": [ { "hooks": [
  { "type": "command", "command": "date '+[now: %Y-%m-%d %H:%M %Z (%a)]'" } ] } ] } }
```

*(Why: 모델은 자기가 몇 시인지 모른다. 날짜 계산이 필요한 대화에서 이게 없으면 조용히 틀린다.)*

## 7. Codex 연결 (선택)

`AGENTS.md`는 `CLAUDE.md`와 바이트 동일하다. Codex는 `AGENTS.md`를 자동으로 읽으므로
두 런타임이 같은 규약 위에서 돈다. 발주는:

```bash
nohup bash tools/ask_codex.sh <프롬프트파일> > /tmp/codex.log 2>&1 &
```

프롬프트는 **반드시 파일로** 준다 (명령줄에 직접 쓰면 백틱이 셸 명령으로 실행된다 — 실측).
기본은 새 세션이다. 이유는 `tools/ask_codex.sh` 머리말에 적혀 있다.

## 8. 마지막 — 사람에게 넘길 것

`CHECKLIST.md`를 열어 아직 안 된 항목을 사람에게 보고해라.
그 문서가 "설치 후 사람이 확인해야 하는 것"의 정본이다.
