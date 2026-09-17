#!/usr/bin/env bash
# test_fresh_install — 낯선 사람의 첫 설치를 그대로 재현해서 잰다.
#
# README의 약속은 `git clone → bash setup.sh → python3 tools/doctor.py` 이고 SETUP.md는
# "FAIL이 0이어야 세팅 완료"라고 말한다. 이 스크립트는 그 약속을 임시 클론에서 **비대화형으로**
# 돌리고(에이전트·CI가 실제로 돌리는 방식), doctor FAIL 수·linkcheck broken 수·회귀 테스트
# 결과를 표로 낸다. 2026-09-17 실측: 이 검사기 없이 릴리스한 v0.4는 첫 설치에서
# setup.sh가 조용히 exit 1 했고, 인자를 줘도 doctor FAIL 4·linkcheck 2·회귀 12/13이었다.
# CRITICAL_E2E setup.sh
# CRITICAL_E2E tools/memlib.py
# CRITICAL_E2E tools/now.py
# CRITICAL_E2E tools/gate.py
# CRITICAL_E2E tools/linkcheck.py
# CRITICAL_E2E tools/doctor.py
# CRITICAL_E2E tools/fresh_worker.py
# CRITICAL_E2E tools/install_hooks.sh
#
# 사용:  bash tools/test_fresh_install.sh            (이 킷을 임시 디렉토리에 클론해서 검사)
#        bash tools/test_fresh_install.sh --keep     (임시 디렉토리를 지우지 않고 경로를 인쇄)
# 내부 회귀용: --judge-linkcheck|--judge-doctor <subprocess-exit> <output-file>
# 종료코드: doctor FAIL 0 · linkcheck broken 0 · 회귀 전부 통과면 0, 아니면 1.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

judge_linkcheck() {
  python3 - "$1" "$2" <<'PY'
import re
import sys

path, raw_rc = sys.argv[1:]
try:
    subprocess_rc = int(raw_rc)
    text = open(path, encoding="utf-8").read()
except (OSError, UnicodeError, ValueError) as exc:
    print(f"측정불능: linkcheck 출력 또는 종료코드를 읽을 수 없음 ({exc})")
    raise SystemExit(1)

pattern = re.compile(
    r"\[linkcheck\] broken: (0|[1-9][0-9]*)"
    r"(?: · pending\((?:setup 전|before setup)\): (0|[1-9][0-9]*))?"
)
matches = [match for line in text.splitlines() if (match := pattern.fullmatch(line))]
if len(matches) != 1:
    print(f"측정불능: linkcheck 요약 줄이 정확히 하나가 아님 (found={len(matches)})")
    raise SystemExit(1)
match = matches[0]
if subprocess_rc != 0:
    print(f"측정불능: linkcheck 비정상 종료 (exit={subprocess_rc})")
    raise SystemExit(1)
broken = int(match.group(1))
if broken != 0:
    print(f"측정불능: linkcheck exit=0이지만 broken={broken}")
    raise SystemExit(1)
print(broken)
PY
}

judge_doctor() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

path, raw_rc = sys.argv[1:]

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result

try:
    subprocess_rc = int(raw_rc)
    with open(path, encoding="utf-8") as source:
        payload = json.load(source, object_pairs_hook=unique_object)
    checks = payload["checks"]
    summary = payload["summary"]
    if not isinstance(checks, list) or not isinstance(summary, dict):
        raise ValueError("checks/summary type")
    statuses = ("PASS", "FAIL", "WARN", "SKIP")
    counted = {status: 0 for status in statuses}
    for row in checks:
        if not isinstance(row, dict):
            raise ValueError("check row type")
        if not all(isinstance(row.get(key), str) for key in ("name", "status", "detail")):
            raise ValueError("check row schema")
        if row["status"] not in counted:
            raise ValueError("check status")
        counted[row["status"]] += 1
    fields = ("total", "pass", "fail", "warn", "skip")
    if not all(type(summary.get(key)) is int and summary[key] >= 0 for key in fields):
        raise ValueError("summary schema")
    expected = {
        "total": len(checks),
        "pass": counted["PASS"],
        "fail": counted["FAIL"],
        "warn": counted["WARN"],
        "skip": counted["SKIP"],
    }
    if any(summary[key] != value for key, value in expected.items()):
        raise ValueError("summary/check mismatch")
except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
    print(f"측정불능: doctor JSON 요약을 읽을 수 없음 ({exc})")
    raise SystemExit(1)

if subprocess_rc != 0:
    print(f"측정불능: doctor 비정상 종료 (exit={subprocess_rc}, FAIL={summary['fail']})")
    raise SystemExit(1)
if summary["fail"] != 0:
    print(f"측정불능: doctor exit=0이지만 FAIL={summary['fail']}")
    raise SystemExit(1)
print(summary["fail"], summary["warn"])
PY
}

case "${1:-}" in
  --judge-linkcheck)
    [ "$#" -eq 3 ] || { echo "usage: $1 <subprocess-exit> <output-file>"; exit 2; }
    judge_linkcheck "$3" "$2"
    exit $?
    ;;
  --judge-doctor)
    [ "$#" -eq 3 ] || { echo "usage: $1 <subprocess-exit> <output-file>"; exit 2; }
    judge_doctor "$3" "$2"
    exit $?
    ;;
esac

KEEP=0; [ "${1:-}" = "--keep" ] && KEEP=1
TMP="$(mktemp -d)"
DEST="$TMP/kit fresh"          # 공백 든 경로: 2026-08-24 실측 버그(경로 유도 규칙)의 재발 방지
cleanup() { [ "$KEEP" -eq 1 ] && echo "kept: $DEST" || rm -rf "$TMP"; }
trap cleanup EXIT

# 부모 셸의 인스턴스 override를 물려받으면 임시 클론이 남의 state를 읽는다.
unset MOTTORI_INSTANCE CLAUDE_PROJECT_DIR

fail=0
step() { printf '%-34s %s\n' "$1" "$2"; }

git clone -q "$KIT" "$DEST" || { echo "clone 실패"; exit 1; }
# clone은 HEAD만 가져온다. 아직 커밋 안 한 수정·새 파일(gitignore 밖)을 덮어 **다음 커밋이 배포할
# 트리**를 잰다. 2026-09-17 실측: 이 덮기 없이는 고친 setup.sh가 아니라 옛 setup.sh를 재고 있었다.
# 수정·삭제는 patch로(삭제·symlink·모드까지 보존, 독립 리뷰 6), 미추적 새 파일은 복사로 가져온다.
( cd "$KIT" && git diff --binary HEAD ) > "$TMP/worktree.patch"
if [ -s "$TMP/worktree.patch" ]; then
  ( cd "$DEST" && git apply "$TMP/worktree.patch" ) || { echo "작업트리 patch 적용 실패"; exit 1; }
fi
( cd "$KIT" && git ls-files -o --exclude-standard -z ) | while IFS= read -r -d '' f; do
  [ -e "$KIT/$f" ] || [ -L "$KIT/$f" ] || continue
  mkdir -p "$DEST/$(dirname "$f")" && cp -Rp "$KIT/$f" "$DEST/$f" || { echo "복사 실패: $f"; exit 1; }
done || exit 1
cd "$DEST"
# 가져온 변경은 다음 커밋에서 추적될 것이므로 index에 올린다. 안 올리면 doctor의 "연료 비추적"
# 검사가 새 엔진 파일을 미추적 노출로 오판한다.
git add -A >/dev/null 2>&1 || { echo "git add 실패"; exit 1; }
step "작업트리 복제 (patch+untracked)" "ok ($(git ls-files | wc -l | tr -d ' ') tracked)"

# 1. 비대화형 setup (stdin 닫힘). 인자 없이 돌린다: 에이전트가 SETUP.md대로 하는 첫 경로.
out="$(bash setup.sh < /dev/null 2>&1)"; rc=$?
if [ $rc -ne 0 ] || [ ! -f system/memory-config.json ]; then
  step "setup.sh (비대화형, 인자 없음)" "FAIL exit=$rc"
  # 원인이 보여야 고친다. setup 안의 doctor FAIL·깨진 참조 줄만 추려 보인다.
  echo "$out" | grep -E "^\[ FAIL \]|BROKEN|회귀 실패|검증이 실패" | head -8; fail=1
else
  step "setup.sh (비대화형, 인자 없음)" "ok  (config·instance-rules·decisions·rituals.local 생성)"
fi

# 2. 후방선 설치
bash tools/install_hooks.sh --repair >/dev/null 2>&1 && step "install_hooks --repair" "ok" || { step "install_hooks --repair" "FAIL"; fail=1; }

# 3. linkcheck
lc_file="$TMP/linkcheck.out"
python3 tools/linkcheck.py >"$lc_file" 2>&1; lc_rc=$?
lc_judgment="$(judge_linkcheck "$lc_file" "$lc_rc")"; lc_judge_rc=$?
if [ $lc_judge_rc -eq 0 ]; then
  step "linkcheck broken" "$lc_judgment"
else
  step "linkcheck broken" "측정불능"
  echo "$lc_judgment"
  grep BROKEN "$lc_file" | head -5
  fail=1
fi

# 4. doctor. 사람용 문자열을 grep하지 않고 공개 JSON 계약만 읽는다.
doctor_json="$TMP/doctor.json"; doctor_err="$TMP/doctor.err"
python3 tools/doctor.py --json >"$doctor_json" 2>"$doctor_err"; doctor_rc=$?
metrics="$(judge_doctor "$doctor_json" "$doctor_rc")"; metrics_rc=$?
nf=""; nw=""
[ $metrics_rc -eq 0 ] && read -r nf nw <<< "$metrics"
if [ "${nf:-x}" = "0" ]; then
  step "doctor FAIL / warn" "0 / ${nw:-?}"
else
  step "doctor FAIL / warn" "측정불능 / ?"
  echo "$metrics"
  tail -6 "$doctor_err"
  fail=1
fi

# 5. 회귀 픽스처 (킷에 실린 것 전부)
for t in tools/test_*.py; do
  if python3 "$t" >"$TMP/test.log" 2>&1; then step "$(basename "$t")" "ok"; else
    step "$(basename "$t")" "FAIL"; tail -3 "$TMP/test.log"; fail=1; fi
done

# 6. 두 번째 setup은 멈춰야 한다 (덮어쓰기 금지 계약)
out2="$(bash setup.sh < /dev/null 2>&1)"; rc2=$?
if [ $rc2 -eq 0 ] && echo "$out2" | grep -Eq "이미 세팅|already set up"; then step "setup.sh 재실행 (덮지 않음)" "ok"; else
  step "setup.sh 재실행 (덮지 않음)" "FAIL exit=$rc2"; fail=1; fi

echo
[ $fail -eq 0 ] && echo "fresh install: PASS" || echo "fresh install: FAIL (위 항목)"
exit $fail
