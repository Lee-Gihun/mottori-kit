# CHANGELOG

**이 파일의 형식은 "무엇이 추가됐다"가 아니라 "기존 인스턴스가 무엇을 해야 하는가"다.**

엔진은 `git pull`로 온다. 그러나 **인스턴스 소유 파일은 안 온다** — system/memory-config.json,
system/instance-rules.md, system/decisions.md, system/rituals.local.md, `state/`, `_private/`.
새 엔진이 그 파일들에 새 필드나 새 절을 기대하면 사람이 직접 넣어야 한다.
그 "직접 넣어야 하는 것"이 여기 적힌다.

각 항목은 `[해야 함]`, `[알아둘 것]`, `[자동]` 중 하나를 단다.
`[해야 함]`이 하나라도 있으면 pull 뒤에 `python3 tools/doctor.py`가 FAIL을 낸다.

---

## v0.5 · 2026-09-17

### `[알아둘 것]` 낯선 첫 설치가 실제로 통과한다 (`tools/test_fresh_install.sh`)

v0.4를 임시 디렉토리에 클론해 README대로 돌리자 `bash setup.sh`가 tty 없이 **아무 출력 없이 exit 1** 했고
(`read`가 EOF를 만나 set -e), 인자를 줘도 첫 doctor가 FAIL 4(codex 미신뢰·깨진 참조 2·회귀 12/13·검사 기록 없는
새 파일)였다. 이번 판은 그 경로를 검사기로 만들었다: `bash tools/test_fresh_install.sh`가 공백 든 임시 경로에
클론하고 작업트리 변경을 덮은 뒤 setup(비대화형·인자 없음) → 훅 설치 → linkcheck → doctor → 회귀 5종 → setup
재실행 순으로 재서 PASS/FAIL을 낸다. 엔진을 고친 뒤 이걸 돌린다. 고친 것: setup.sh가 tty 없으면 기본값으로
진행하고 인쇄한다 · `--force` 재실행은 기존 config의 이름·context를 기본값으로 쓴다(이전엔 비대화형이면 personal
인스턴스가 work로 뒤집혔다) · 첫 local 사건을 기록해 `_private/state/NOW.md`를 첫날부터 만든다 · 순서는 기준선 →
linkcheck → doctor(linkcheck 통과 기록이 doctor의 인증서다) · 쓰기 전에 public·private journal을 strict로 preflight
한다(마지막 줄 개행 포함; 실패하면 아무것도 안 바꾼다) · `pwd -P`로 물리 경로를 export한다(macOS `/var` 링크 아래에서
doctor의 ROOT 불일치) · `test_setup_migration.py` 픽스처가 부모의 `MOTTORI_INSTANCE`를 상속하지 않는다.

### `[알아둘 것]` 실패가 조용히 성공으로 읽히던 경로 넷을 닫았다 (독립 결함 감사 17건 반영)

`setup.sh`는 doctor·기준선이 실패하면 안내문을 끝까지 인쇄한 뒤 exit 1 한다(이전엔 FAIL을 보여주고도 0).
`linkcheck.py` normal mode는 broken이 있으면 exit 1이다(`--issues`는 그대로 0). Stop 게이트는 검사기 자신이
예외를 내면 무출력 0이 아니라 차단 JSON을 내고 pending을 남기며, UserPromptSubmit 회수 경로는 경고 JSON을
낸다(후방선 fail-closed). doctor의 linkcheck 인증서 해시가 공백 든 md 파일명에서 linkcheck와 갈라지던 것을
줄 단위로 고쳤다. 그 밖에: setup 전 doctor의 `훅 · claude 명령 유효성`은 고장이 아니라 "setup 전"으로 warn ·
`c_git`은 2.36 미만을 FAIL(업그레이드로 고칠 수 있는 결함) · 새 인스턴스 NOW의 개인 정본이 `None`으로 찍히던 것
정정 · CHECKLIST의 게이트 시험은 일회용 클론에서 하도록 바꿈(원본에서 게이트가 뚫리면 실제 커밋이 남았다).
회귀 `tools/test_install_checks.py`가 이 계약을 고정한다(doctor의 회귀 목록에 포함). 독립 검토 2회(Codex)의
FIX 판정을 반영했고, 남긴 것은 실제 Git 2.35 바이너리·Python 3.8 실기·shasum 없는 Linux·Claude/Codex 훅의
실제 발화(fired/effect)로, 전부 이 머신에서 재현할 수 없는 것들이다.

### `[알아둘 것]` doctor·linkcheck·now.py check의 늑대소년 3건 제거

`훅 · codex armed`의 "미신뢰"는 사람이 codex를 한 번 띄워야만 풀리므로 FAIL이 아니라 warn+할 일이다. 상류 사본
(setup 전)의 linkcheck는 setup이 만드는 7개 경로(config·인스턴스 문서 셋·두 NOW·게이트 기준선)를 BROKEN이 아니라
`PENDING`으로 따로 센다 (`broken: 0 · pending(setup 전): N`); setup 뒤에는 같은 참조가 없으면 BROKEN이다.
`now.py check`의 드라이브 인박스 검사는 개인 장비 어댑터(`drive_inbox.py`)가 없으면 경고 없이 건너뛴다(이전엔 킷
클론마다 "인박스 검사 실패" 경고). `c_git`은 2.36 미만을 FAIL로 낸다(`install_hooks.sh`가 `git hook run`을 쓴다;
업그레이드로 고칠 수 있는 결함이라 FAIL이다). 킷 드리프트 검사는 `fresh_worker.py` 각인 줄을 정규화해 비교한다.

### `[알아둘 것]` 철학 한 줄과 LICENSE(MIT)

README 첫 절에 소유자가 정한 철학이 들어갔다: 사람의 주의가 가장 비싼 자원, 토큰이 가장 싼 자원, 사람은 무한
스레드 하나만 상대한다. 그 아래 규칙 둘(판정은 영수증으로만 · 통과와 원인은 따로 검증한다)은 KIT-DR-012.
LICENSE는 MIT다. 독립 문서 감사가 "라이선스 검사하는 조직에서는 사용 자체가 막힌다"고 지적했다.

### `[알아둘 것]` 문서가 코드와 맞는다 (독립 문서 감사 39건 반영)

SETUP: setup이 만드는 파일 전체 목록과 되돌리기 목록, git 2.36·macOS/Linux 전제, FAIL·warn·`--`의 뜻, Codex 훅
신뢰 승인 단계, `git pull` 뒤 재실행 순서(§5a), 트랙 등록 뒤 `render` 필요. README: 명령 넷 + 영어 quickstart 한 문단,
훅·검사 개수 정정. CHECKLIST: 훅은 프로젝트 수준, work 인스턴스의 origin은 allowlist에 등록됨, 변경 관측 matcher
위치. 소유자 이름은 킷 전체에서 역할어(소유자)로 치환됐다(`kit_sync`가 조사까지 변환하고 SCAN이 이름 단독을 잡는다).

## v0.4 · 2026-09-16

### `[자동]` fresh worker meta v2: kit_rev·kit_dirty·harness_sha256·usage·read_scope·scope

`meta.json` schema_version 2. 값이 없으면 null. receipt(4,096 byte)는 `scope:` 한 줄만 늘고 나머지는
그대로. 비교는 `harness_sha256`이 같은 run끼리만 한다. 정체 필드: `kit_rev`(`KIT_REV_EMBEDDED`가 각인돼
있으면 그 값, 아니면 엔진 리포 HEAD; `kit_rev_source`가 어느 쪽인지 말한다), `repo_rev`(실행 사본이 든 리포의
HEAD), `kit_dirty`(엔진 디렉토리 tools/ 범위 porcelain), `engine_sha256`(fresh_worker.py+memlib.py 내용 해시, git 무관),
`agents_sha256`(워커가 읽는 AGENTS.md). **인스턴스로 복사할 때는 `bash tools/sync_engine.sh <instance>`를 쓴다**: `KIT_REV_EMBEDDED`(킷 HEAD)·`KIT_SYNC_DIRTY`(킷 tools/가
동기화 시점에 dirty였나)·`KIT_SYNC_ENGINE_SHA256`(복사 직후 사본의 정규화 엔진 해시, 목적지 기준선)·`KIT_SYNC_SOURCE_SHA256`(킷 쪽에서 계산한 복사 파일 manifest 해시)을 각인한다.
각인 대상 줄이 정확히 한 번씩 없으면 실패하고, 각인 뒤 사본을 다시 import해 값과 `matches_copy=True`를 검증한다(독립 리뷰 R11). `engine_sha256`은 각인 줄을 빼고
계산하므로 킷 파일과 각인된 사본이 같은 코드면 같은 값이고, `kit_sync.matches_copy`가 동기화 뒤 사본이 손대졌는지 말한다
(독립 리뷰 R5, 2차). 안 하면 인스턴스 HEAD가 킷 rev로 잘못 라벨된다.
설계·worked example·anchor는 원본 인스턴스의 private 작업장(papers-2026-09-13-kit, 설계 문서 design-fresh-worker-receipt-v2)에 있다.

### `[알아둘 것]` worker 결과의 주장에는 출처 경로가 붙는다

common 계약에 한 줄이 늘었다: 출처 없는 주장은 remaining unknowns로 내려간다 (2609.06702 App. F.2).
기존 발주문은 그대로 돈다.

### `[알아둘 것]` `--write-prefix DIR`(반복 가능)로 Codex 워커의 write-set을 검사한다

실행 전후 workspace 스냅샷(lstat: kind·size·mtime_ns·ctime_ns·mode, 디렉터리 포함, `.git`·run-record 트리 제외)을
비교해 prefix 밖 변경과 symlink 탈출을 `scope.violations`에 기록한다. prefix 아래 **기존** symlink도 밖을 가리키면
위반이다(쓰기가 스냅샷 밖으로 새는 문). 같은 크기로 쓰고 mtime을 되돌려도 ctime이 잡는다(독립 리뷰 R1·R2). prefix 아래 파일의 링크 수가 스냅샷이 보는 같은 inode 수보다
많으면 workspace 밖에 별명이 있는 hardlink라 위반이다(R8). 없는 prefix는 baseline 전에 디스패처가 만들어 그 생성이 위반으로
잡히지 않게 한다(R9). prefix의 대소문자 보정은 파일시스템이 실제로 그 표기를 같은 항목으로 푸는 경우에만 한다(R10). **기본은 기록만**(run status 불변). `--strict-scope`를 함께 주면 위반 시 status
`scope_violation`(wrapper_exit 4, 런타임 자체 exit보다 우선하며 `process_exit`는 meta에 남는다, R3). 사후 탐지만이고 rollback·삭제는 없다.
호출자: 배포본의 `ask_codex.sh`는 `MOTTORI_WRITE_PREFIX` 환경변수를 통과시킨다(R4). 원본 인스턴스의 확장인 정원 주기 스크립트(킷에 안 실림)는 검토 워커에 `--write-prefix "$DIR"`를 넘긴다. prefix를 안 주면 write-set만 기록하고
status는 `unchecked`다. 이유: 2026-09-16 실 카나리에서 위반 2건이 전부 동시 쓰기(디스패처의 문서 편집,
인스턴스의 `state/.tool-runs.log`)였다. 동시 writer와 워커를 가르려면 worktree 격리가 필요하다(다음 버전 후보).
DR-049 closeout의 "allowlist·denylist 검사기" 구체화 (2609.04170 §2.2·§3.6).

### `[알아둘 것]` 규약 문서에 근거 행 8줄

rituals(컴팩션 뒤 절차 위치 1줄), WORKING-WITH-AI(§4 present/effective, §5 발주 형태 넷, §9 국소 correction),
README(Why는 실측 우선), PRD-session-memory §3.8(토폴로지 비목표), debate/README(파일 목록은 생성물만).
전부 논문 식별자와 DR-053이 붙어 있다. 인스턴스 사본에도 같은 줄이 있다.

## v0.3 · 2026-08-29

### `[알아둘 것]` 공통 지시 정본이 `AGENTS.md` 하나로 바뀌었다

`CLAUDE.md`는 이제 exact `@AGENTS.md` import다. 인스턴스 규약이 필요하면 이전처럼
system/instance-rules.md에 쓴다. 업스트림 `AGENTS.md`나 `CLAUDE.md`에 직접 쓴 내용은 pull 전에
인스턴스 파일로 옮겨라.

### `[알아둘 것]` fresh 발주의 프롬프트는 workspace 안에 둔다

`ask_codex.sh`의 기본 경로가 bounded worker로 바뀌었다. `/tmp`나 symlink의 프롬프트는 거부한다.
`system/debate/_p_*.md`처럼 workspace 안의 무시되는 파일을 쓴다.

### `[자동]` 광역 작업 trace를 master context에서 격리한다

`fresh_worker.py`는 Claude read-only 또는 Codex workspace-write의 ephemeral run을 만들고, 전체
trace는 `_private/work/runs/`에 보관한다. 호출자에게는 bounded receipt만 반환한다.
`recall.py sessions`도 최신 40개만 기본 표시하며 `--all`일 때만 전량을 낸다.

### `[알아둘 것]` 외부 문안은 본문 전에 두 줄을 보인다

에이전트가 발신 산출물을 쓰기 전에 독자·승인자·목적함수와 실제 근거 경로를 먼저 보여주고 바로
계속한다. 승인 단계가 아니다. 담백한 문체는 새 스킬이나 길이 제한이 아니라 `system/rituals.md`의
10건 파일럿으로 들어갔다.

## v0.2 · 2026-08-24

### `[해야 함]` config schema v1 → v2

system/memory-config.json에 `instance` 블록과 `schema_version`이 필요하다.

```json
{
  "schema_version": 2,
  "instance": {
    "name": "이 인스턴스 이름",
    "context": "work",
    "remote_allowlist": ["클론해 온 origin URL"]
  }
}
```

**안 넣으면 조용히 다르게 동작한다.** `context`가 없으면 밸브 검사가 `personal`로 간주하고
원격을 아예 안 본다. 회사 인스턴스에서 그건 밸브가 꺼진 상태다.
`python3 tools/doctor.py`의 `엔진 · config 스키마` 항목이 FAIL로 알려준다.

### `[해야 함]` 규약 문서가 엔진/인스턴스 쌍으로 갈라졌다

지금까지 `system/rituals.md`와 system/decisions.md에 직접 쓴 게 있다면 옮겨야 한다.
그대로 두면 다음 pull에서 충돌하거나 되돌아간다.

| 엔진 (pull이 덮는다) | 여기로 옮긴다 (git 밖) |
|---|---|
| `system/rituals.md` | system/rituals.local.md |
| `system/kit-decisions.md` (신설) | system/decisions.md |
| `CLAUDE.md` 상시 코어 | system/instance-rules.md |

`setup.sh`를 다시 돌리면(`--force` 불필요) 없는 파일만 씨앗에서 만들어 준다.
기존 `decisions.md`에 킷 DR과 인스턴스 DR이 섞여 있으면 킷 DR(001~003)을 지운다.
그 내용은 `system/kit-decisions.md`에 있다.

### `[알아둘 것]` `.gitignore`가 기본 거부로 바뀌었다

이전에는 `state/`와 `_private/`만 무시했다. 그래서 **평범한 경로의 회사 자료가 그냥 커밋됐다**
(company/tracker.md 같은 것). 지금은 전부 무시하고 엔진 파일만 되살린다.

작업 문서를 만들면 이제 기본으로 git 밖이다. 그게 의도다.
**뒤집어 말하면 그 문서들은 이 리포로 백업되지 않는다** — 별도 백업이 필요하다.

### `[알아둘 것]` 전사 경로 유도 규칙이 바뀌었다

`~/.claude/projects` 디렉토리명 규칙을 `[/_]` → `-`로 알고 있었는데 실제로는
`[^A-Za-z0-9-]` → `-`다. 공백이나 점이 든 경로(`~/My Work/kit`, `~/work.v2`)에 클론했다면
이전 판에서는 `recall`이 조용히 0건을 반환했다. 지금은 맞는다.

### `[자동]` doctor 검사가 21개에서 29개로

추가된 것: 링크 무결성·정합성의 **결과 파싱** (이전엔 종료코드만 봤다) · 회귀 픽스처 실행 ·
Codex 훅 3종 · 추적 심볼릭 링크 · config 스키마 · 업스트림 동기 · 킷 드리프트.

### `[자동]` 밸브 수리 4건

`.gitignore` 기본 거부 · ignore 규칙 부재 검출 · allowlist를 부분 문자열이 아닌 host 기준 비교 ·
`recall` 인스턴스 격리(경로 접두 충돌·cwd 미기록·상대 경로 전부 차단).

---

## v0.1 · 2026-08-24

첫 추출. 원본 워크스페이스에서 엔진만 떼어냈다.

- 도구 14개 (memlib · now · recall · rec 핵심 넷 + 검사기 + Codex 발주 + doctor)
- 규약 20문서 (PRD 둘 · rituals · 렌즈 13종 · deep-pass · WORKING-WITH-AI)
- 훅 5종 (Claude 3 + Codex 2), 전부 경로 상대
- 인스턴스 배선을 system/memory-config.json으로 분리
