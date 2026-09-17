# 근거 표지 스키마

근거 표지는 결정이나 변경의 근거를 기계가 찾을 수 있게 하는 포인터다. 검사기는 모든 표지의
문법과 로컬 대상의 존재만 판정한다. 외부 원본의 존재와 표지가 주장을 실제로 뒷받침하는지는
독립 검토가 판정한다.

## 허용 문법

| 종류 | 문법 | 예 |
|---|---|---|
| 논문 | `paper:<arXiv id 또는 DOI>` | `paper:2609.09134`, `paper:10.1000/example` |
| 실험 | `experiment:<id>` | `experiment:fresh-install-20260917` |
| 실행 | `run:<run id>` | `run:20260917T163052+0900-codex-f58c6c0b` |
| 결정 | `decision:<DR-nnn 또는 KIT-DR-nnn>` | `decision:DR-001`, `decision:KIT-DR-012` |
| 테스트 | `test:<tools/test_x.py::name>` | `test:tools/test_evidencecheck.py::test_malformed_marker_fails` |

arXiv ID는 신형 `YYMM.number`와 구형 `archive/YYMMNNN`을 허용하고 버전 접미사 `vN`을 허용한다.
DOI는 `10.` 접두와 registrant 번호, `/` 뒤 suffix가 모두 있어야 한다. experiment ID는 영문자,
숫자, `.`, `_`, `-`를 쓴다. run ID는 여기에 `+`도 허용한다. 문장 부호와 경계를 모호하게 하지
않도록 표지는 인라인 코드로 감싸는 것을 권장한다.

## 로컬 존재 판정

- `decision:KIT-DR-nnn`은 `system/kit-decisions.md`의 `### DR-nnn` 제목으로 해석한다.
- `decision:DR-nnn`은 로컬 루트의 `system/decisions.md` 제목으로 해석한다.
- `test:tools/test_x.py::name`은 검사 트리의 파일과 Python 함수 이름이 모두 있어야 한다.
- `run:<run id>`는 로컬 루트의 `_private/work/runs/<run id>/` 디렉터리가 있어야 한다.
- `paper:`와 `experiment:`은 이 저장소 밖에 원본이 있을 수 있으므로 문법만 검사하고
  `REVIEW 외부 존재 미판정`으로 표시한다. 이 표시는 차단 이슈가 아니다.

pre-commit에서는 추출한 index를 검사 트리로 쓰되, git 밖에 있는 run과 인스턴스 DR은 현재 로컬
루트에서 찾는다.

## 필수 위치

- `system/kit-decisions.md`의 모든 DR은 `맥락:` 절에 허용 표지 하나 이상을 둔다. 근거 포인터를
  소급해서 만들 수 없는 기존 DR은 본문을 고치지 않고 독립된 `evidence: none` 표지를 둔다.
- `CHANGELOG.md`의 `[해야 함]`과 `[알아둘 것]` 항목은 절 안에 허용 표지 하나 이상을 둔다. 근거가
  없으면 숨기지 않고 정확히 `evidence: none`이라고 쓴다.
- `system/enforcement-matrix.md`에서 상태가 `ENFORCED`인 행은 같은 행에 `test:` 표지를 둔다.

`evidence: none`은 CHANGELOG의 두 필수 태그와 기존 DR 맥락에만 쓰는 명시적 예외다. 근거가
있다는 뜻이 아니며 표지 적합성을 증명하거나 다른 필수 위치를 면제하지 않는다.

## 검사기 출력 계약

`python3 tools/evidencecheck.py`는 이슈가 있으면 exit 1, 없으면 exit 0이다. `--issues`는 이슈 유무와
무관하게 exit 0이며 다음 형식을 쓴다.

```text
<안정 ID>\t<표시 문구>
~review|<파일>|<표지>\tREVIEW <표시 문구>
#issues <N>
```

트레일러는 항상 마지막 줄이다. `~review|` 행은 이슈 수에 포함되지 않는다. `tools/gate.py`와
pre-commit 훅은 차단 이슈 집합만 다른 검사기와 같은 방식으로 소비한다.
