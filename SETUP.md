# SETUP — 이 디렉토리를 세팅하는 법

**이 문서는 에이전트에게 주는 지시서다.** 새 머신에서 클론한 다음, Claude Code 또는 Codex를
이 디렉토리에서 열고 이렇게 말하면 된다:

> SETUP.md 읽고 이 디렉토리를 세팅해줘. 끝나면 doctor 결과를 보여줘.

사람이 직접 할 거면 아래를 순서대로 하면 된다. 5분 걸린다.
다른 mottori 워크스페이스에서 연 shell이면 먼저 `unset MOTTORI_INSTANCE`를 실행하거나
새 clone의 절대경로로 다시 지정해라. 안 그러면 doctor가 이전 인스턴스를 검사한다.

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
git --version         # 2.5 이상
bash --version        # 3.2 이상
which claude codex    # 없어도 설치는 된다. 둘 다 없으면 fresh worker와 훅 주입만 못 쓴다
node --version        # 정원사(/garden)용. 없어도 나머지는 다 돈다
```

코어 설치는 macOS와 Linux를 대상으로 한다. 훅 설치는 GNU `sha256sum`, BSD `shasum`, Python 순으로
SHA-256 구현을 고른다. 임시 파일은 운영체제의 기본 임시 디렉토리에 만든다. Windows native는
`fcntl` 잠금을 제공하지 않아 지원하지 않으며 WSL은 아직 실기 검증하지 않았다.

### 지원 매트릭스

| 대상 | 상태 | 근거와 범위 |
|---|---|---|
| macOS, Darwin 25.3, Apple Silicon | 실기 검증 | Bash 3.2.57, Python 3.9.6, Apple Git 2.50.1에서 전체 회귀와 fresh install을 통과했다. |
| Bash 3.2 | 실기 검증 | 이 머신의 기본 Bash 3.2로 여섯 셸 진입점의 일반 문법과 POSIX 모드 문법을 검사하고 fresh install을 통과했다. |
| `shasum` 없는 PATH | 픽스처 검증 | `tools/test_portability.py`가 `shasum`을 제공하지 않고 `sha256sum`만 제공해 훅 체크섬 분기를 실행한다. |
| Git 2.5 이상, 2.36 미만 | 픽스처 검증 | 같은 테스트가 `git hook run`과 `--path-format`을 거부하는 Git wrapper로 훅 설치를 실행한다. 실제 구버전 바이너리는 시험하지 않았다. |
| Ubuntu·Debian 기본 이미지 | 추정 지원 | GNU/BSD 전용 `sed -i`, `stat`, `date` 형식과 고정 `/tmp`를 정적 검사로 막는다. 이 작업 환경에서는 Linux 컨테이너를 실행하지 못해 실기 미검증이다. |
| Windows native | 미지원 | `fcntl`과 Unix 훅 실행 모델이 필요하다. WSL도 현재는 미검증이다. |

`claude`, `codex`, `node`, `ffmpeg`, `mlx_whisper`를 쓰는 선택 기능은 각 행의 코어 설치 검증 범위에
포함되지 않는다. 이 표의 검증 명령은 §3과 `tools/test_portability.py`가 정본이다.

## 2. 인스턴스 설정 만들기

README의 빠른 시작으로 `setup.sh`와 hook `--repair`를 이미 끝냈다면 이 절을 다시
실행하지 말고 §2b의 `--check`와 §3부터 확인해라.

```bash
bash setup.sh
```

대화형으로 인스턴스 이름과 context(personal/work)를 묻고
`system/memory-config.json`을 만든다. 비대화 모드도 있다:

```bash
bash setup.sh --name team-work --context work
```

tty가 없으면(에이전트·CI·파이프) 묻지 않고 기본값(이름=디렉토리명, context=work)을 쓰고 그 사실을
인쇄한다. 개인 머신이면 `--context personal`을 명시해라.

`setup.sh`가 만드는 것은 아래 전부다 (되돌리려면 이 목록을 지운다).
1. `system/memory-config.json` (templates에서 복사, 이름·context 치환, 클론 origin을 allowlist에 등록)
2. `system/instance-rules.md` · `system/decisions.md` · `system/rituals.local.md` (없는 것만 templates에서)
3. `state/journal-<월>.md` 첫 사건 + `state/NOW.md` · `_private/state/journal-<월>.md` 첫 local 사건 + `_private/state/NOW.md`
4. `python3 tools/linkcheck.py` 실행 기록(`state/.tool-runs.log`) + 게이트 기준선 `state/.gate-baseline.json`
5. 마지막에 `python3 tools/doctor.py`를 한 번 돌려 결과를 보여준다

기존 schema v1/v2/v3 인스턴스를 v4로 올리거나 v4 설정을 보존해 다시 적용할 때는
`bash setup.sh --force`를 실행한다. 이름·context는 기존 config 값이 기본값이 된다 (tty가 없어도
work로 바뀌지 않는다). 기존 config는 `.bak`으로 남고 트랙·검사·공개 목록은 보존된다.
단, v1~v3의 nonempty `threads[]`에는 public 판정 provenance가 없으므로 자동 승격하지 않고 중단한다.
확인된 public 항목과 local 항목을 사람이 먼저 분리한 뒤 재실행한다. 검증된 v4 `threads[]`만 그대로
보존한다. v3는 기존 공개 목록을 과거 journal 행의 provenance로 고정하고, v1/v2에는 그 판정이
없으므로 기존 journal 전부를 fail-closed legacy-private로 둔다. 경계는 migration 전 마지막 journal
timestamp다. malformed journal·config는 추측해 덮지 않는다. 끝나면 `python3 tools/doctor.py`를 다시 돌린다.

새 설치를 되돌리려면 위 목록의 파일(`system/` 넷, `state/`, `_private/state/`)과 `.git/hooks/pre-commit`
(2b에서 설치)을 지우면 된다. migration을 되돌릴 때는 내용을 확인한 뒤 `system/memory-config.json.bak`을
복원한다. 되돌릴 수 없는 일은 하지 않는다.

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
```

`setup.sh`가 첫 초기화에서 linkcheck 기록과 게이트 기준선을 만든다. 수동 설치·복구 때만
`python3 tools/linkcheck.py && python3 tools/gate.py baseline`을 직접 실행한다. 기준선이 없으면
게이트는 삭제와 첫 설치를 구분할 수 없어 fail-closed로 막는다.

**FAIL이 0이어야 세팅 완료다.** 표시 셋의 뜻:
- `FAIL` 기계가 고칠 수 있거나 고쳐야 하는 것. 종료코드 1. 하나라도 있으면 상태 자동화를 믿지 마라
- `warn` 상황에 따라 정상인 것 (codex·claude 미설치, 아직 세션을 안 돌려 전사 디렉토리 없음, tracks 미등록,
  Codex가 아직 이 디렉토리의 훅을 신뢰하지 않음). 종료코드에 안 들어간다
- `--` 이 인스턴스에 해당 없음 (예: personal이면 원격 검사 안 함)

같은 발견이 work 인스턴스에서는 FAIL, personal에서는 warn인 것이 있다 (`_private`을 가리키는 추적
심볼릭 링크). 회사 구조가 원격에 나가느냐의 차이다.

Codex를 쓰면 이 디렉토리에서 `codex`를 한 번 띄워 훅 신뢰를 승인해야 Codex 세션에 상태가 주입된다.
승인 전엔 doctor가 `훅 · codex armed`를 warn으로 알려준다 (CHECKLIST C).

낯선 머신에서 이 절차 전체가 실제로 통과하는지는 `bash tools/test_fresh_install.sh`가 임시 클론에서
비대화형으로 재현한다 (setup → 훅 → linkcheck → doctor → 회귀 → 재실행). 엔진을 고친 뒤 이걸 돌린다.

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

등록한 뒤 `python3 tools/now.py render`를 한 번 돌리면 `state/NOW.md`의 온도판에 그 트랙의 신선도가
뜬다 (config를 손으로 고치면 NOW가 낡은 상태가 되고, `now.py check`가 그걸 이슈로 잡는다).

## 5a. 엔진을 업데이트할 때 (`git pull` 뒤)

```bash
git pull
bash tools/install_hooks.sh --check      # 훅 템플릿이 바뀌었으면 --repair
python3 tools/linkcheck.py && python3 tools/gate.py baseline   # 검사기가 바뀌었으면 기준선 갱신
python3 tools/doctor.py                  # CHANGELOG의 [해야 함] 항목이 있으면 여기서 FAIL로 뜬다
```

`CHANGELOG.md`가 "기존 인스턴스가 무엇을 해야 하는가"의 정본이다. 새 설치는 최신 템플릿이므로
옛 버전의 `[해야 함]` 항목을 다시 할 필요가 없다.

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

`AGENTS.md`가 공통 규약의 단일 정본이고 `CLAUDE.md`는 exact `@AGENTS.md` import다. Codex는
`AGENTS.md`를 자동으로 읽으므로 두 런타임이 같은 규약 위에서 돈다.

광역 독해·감사·런타임 토론은 master 세션에 전량을 쌓지 않고 fresh worker로 격리한다:

```bash
python3 tools/fresh_worker.py --runtime claude <프롬프트파일>
python3 tools/fresh_worker.py --runtime codex  <프롬프트파일>
bash tools/ask_codex.sh <프롬프트파일>   # Codex fresh worker의 호환 진입점
```

프롬프트는 이 workspace 안의 regular UTF-8 파일이어야 하며 symlink는 거부한다. 명령줄에 내용을
직접 쓰면 백틱이 셸 명령으로 실행될 수 있다. 기본 실행은 동기식이고, 전체 trace는
`_private/work/runs/`에 두며 호출자에게는 bounded receipt만 반환한다. 정확한 byte·capability
계약은 `system/PRD-session-memory.md` §10.5가 정본이다.

## 8. 마지막 — 사람에게 넘길 것

`CHECKLIST.md`를 열어 아직 안 된 항목을 사람에게 보고해라.
그 문서가 "설치 후 사람이 확인해야 하는 것"의 정본이다.

## 절차 근거 연결

이 문서의 명령 순서는 `tools/test_fresh_install.sh`가 임시 클론에서 같은 순서로 재현하며,
설치 후 사람 확인으로 넘기는 경계는 `CHECKLIST.md`와 KIT-DR-011이 정한다. 복구 불가능한
작업을 피하는 절차는 설치 실패를 사용자 데이터 손실로 키우지 않기 위함이다. 소요 시간과
버전 숫자는 지정된 테스트 환경의 측정값이지 모든 머신에 대한 보장이 아니다.
