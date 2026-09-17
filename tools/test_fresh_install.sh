#!/usr/bin/env bash
# test_fresh_install — 낯선 사람의 첫 설치를 그대로 재현해서 잰다.
#
# README의 약속은 `git clone → bash setup.sh → python3 tools/doctor.py` 이고 SETUP.md는
# "FAIL이 0이어야 세팅 완료"라고 말한다. 이 스크립트는 그 약속을 임시 클론에서 **비대화형으로**
# 돌리고(에이전트·CI가 실제로 돌리는 방식), doctor FAIL 수·linkcheck broken 수·회귀 테스트
# 결과를 표로 낸다. 2026-09-17 실측: 이 검사기 없이 릴리스한 v0.4는 첫 설치에서
# setup.sh가 조용히 exit 1 했고, 인자를 줘도 doctor FAIL 4·linkcheck 2·회귀 12/13이었다.
#
# 사용:  bash tools/test_fresh_install.sh            (이 킷을 임시 디렉토리에 클론해서 검사)
#        bash tools/test_fresh_install.sh --keep     (임시 디렉토리를 지우지 않고 경로를 인쇄)
# 종료코드: doctor FAIL 0 · linkcheck broken 0 · 회귀 전부 통과면 0, 아니면 1.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEEP=0; [ "${1:-}" = "--keep" ] && KEEP=1
TMP="$(mktemp -d "${TMPDIR:-/tmp}/kit-fresh.XXXXXX")"
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
lc="$(python3 tools/linkcheck.py 2>&1)"; broken="$(echo "$lc" | sed -n 's/.*broken: \([0-9]*\).*/\1/p' | tail -1)"
[ "${broken:-x}" = "0" ] && step "linkcheck broken" "0" || { step "linkcheck broken" "${broken:-측정불능}"; echo "$lc" | grep BROKEN | head -5; fail=1; }

# 4. doctor
dr="$(python3 tools/doctor.py 2>&1)"
nf="$(echo "$dr" | sed -n 's/.*ok \([0-9]*\) · FAIL \([0-9]*\) · warn \([0-9]*\).*/\2/p' | tail -1)"
nw="$(echo "$dr" | sed -n 's/.*ok \([0-9]*\) · FAIL \([0-9]*\) · warn \([0-9]*\).*/\3/p' | tail -1)"
if [ "${nf:-x}" = "0" ]; then step "doctor FAIL / warn" "0 / ${nw:-?}"; else
  step "doctor FAIL / warn" "${nf:-측정불능} / ${nw:-?}"; echo "$dr" | grep -E "^\[ FAIL \]" | head -6; fail=1; fi

# 5. 회귀 픽스처 (킷에 실린 것 전부)
for t in tools/test_*.py; do
  if python3 "$t" >"$TMP/test.log" 2>&1; then step "$(basename "$t")" "ok"; else
    step "$(basename "$t")" "FAIL"; tail -3 "$TMP/test.log"; fail=1; fi
done

# 6. 두 번째 setup은 멈춰야 한다 (덮어쓰기 금지 계약)
out2="$(bash setup.sh < /dev/null 2>&1)"; rc2=$?
if [ $rc2 -eq 0 ] && echo "$out2" | grep -q "이미 세팅"; then step "setup.sh 재실행 (덮지 않음)" "ok"; else
  step "setup.sh 재실행 (덮지 않음)" "FAIL exit=$rc2"; fail=1; fi

echo
[ $fail -eq 0 ] && echo "fresh install: PASS" || echo "fresh install: FAIL (위 항목)"
exit $fail
