# CHANGELOG

**이 파일의 형식은 "무엇이 추가됐다"가 아니라 "기존 인스턴스가 무엇을 해야 하는가"다.**

엔진은 `git pull`로 온다. 그러나 **인스턴스 소유 파일은 안 온다** — system/memory-config.json,
system/instance-rules.md, system/decisions.md, system/rituals.local.md, `state/`, `_private/`.
새 엔진이 그 파일들에 새 필드나 새 절을 기대하면 사람이 직접 넣어야 한다.
그 "직접 넣어야 하는 것"이 여기 적힌다.

각 항목은 `[해야 함]`, `[알아둘 것]`, `[자동]` 중 하나를 단다.
`[해야 함]`이 하나라도 있으면 pull 뒤에 `python3 tools/doctor.py`가 FAIL을 낸다.

---

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
