#!/bin/bash
# Codex에게 한 라운드를 발주한다.
#
# **기본은 새 세션이다.** (2026-08-23 판정 — DR-022)
#
# 왜 바뀌었나. 이전 기본값은 기훈의 루트 스레드에 이어붙이기(resume)였다. 의도는 그가 자기
# 앱에서 토론을 읽는 것이었는데, 실제로는 반대로 작동했다. 그가 앱에서 그 스레드를 열어 두면
# Codex 런타임의 단일 writer 락이 resume을 거부하고, 스크립트가 조용히 fresh로 폴백한다.
# 그러면 그 왕복은 별도 세션에서 완결되어 **그의 채팅 이력에 영원히 안 나타난다.**
# 8/23 새벽 실측: 발주 6건 중 resume 시도 2건이 전부 폴백, 나머지 4건은 애초에 fresh.
# 즉 "그가 앱을 켜고 있을수록 resume이 실패한다"는 역설이라 기본값으로 부적합하다.
#
# 대신 역할을 나눈다 (기훈-codex 합의, 루트 스레드 00:54).
#   - **자동 티키타카** = 이 스크립트. fresh_worker.py의 bounded·ephemeral Codex adapter를
#     호출해 전체 trace는 local-private run에 두고 이 호출자에게는 bounded receipt만 돌린다.
#   - **무한세션** = 기훈이 Codex 앱에서 직접 쓰는 본진. 필요할 때 그가 이렇게 부른다.
#     "Claude 최신 관련 대화와 메모리까지 확인하고, 디스크 정본을 기준으로 이어가."
#
# fresh worker의 dispatch contract가 AGENTS.md를 직접 읽게 하므로 코어 규약은 유지된다.
# 손실되는 것은 대화 누적뿐이고, 그건 애초에 디스크에 있어야 할 것이다.
#
# 사용:
#   bash tools/ask_codex.sh <프롬프트파일>                  # 새 세션 (기본)
#   bash tools/ask_codex.sh <프롬프트파일> --resume <SID>   # 특정 스레드 지정
#   bash tools/ask_codex.sh <프롬프트파일> --resume-root    # 루트 스레드 자동 탐지 (락이면 중단)
#
# 프롬프트는 반드시 파일로 준다. 명령줄에 직접 쓰면 백틱이 셸 명령으로 실행된다 (8/22 실측).

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 인스턴스 루트 유도 (DR-023)
cd "$ROOT"
PROMPT_FILE="$1"
[ -f "$PROMPT_FILE" ] || { echo "프롬프트 파일 없음: $PROMPT_FILE"; exit 1; }
LOG="system/debate/_dispatch.log"
ERR="/tmp/_ask_codex_err.log"
STAMP=$(date '+%Y-%m-%d %H:%M:%S')
MODE="${2:---fresh}"
SID="$3"

if [ "$MODE" = "--fresh" ] || [ -z "$MODE" ]; then
  echo "[$STAMP] FRESH <- $PROMPT_FILE" >> "$LOG"
  python3 "$ROOT/tools/fresh_worker.py" --runtime codex "$PROMPT_FILE"
  echo "[$STAMP] DONE fresh" >> "$LOG"
  exit 0
fi

if [ "$MODE" = "--resume-root" ]; then
  SID=$(python3 "$ROOT/tools/codex_root_thread.py")
  [ -n "$SID" ] || { echo "루트 스레드를 못 찾았다."; exit 1; }
  echo "루트 스레드 자동 탐지: $SID"
elif [ "$MODE" != "--resume" ] || [ -z "$SID" ]; then
  echo "사용법: $0 <프롬프트파일> [--fresh | --resume <SID> | --resume-root]"; exit 1
fi

echo "[$STAMP] RESUME $SID <- $PROMPT_FILE" >> "$LOG"
if codex exec --sandbox workspace-write resume "$SID" - < "$PROMPT_FILE" 2>"$ERR"; then
  cat "$ERR" >&2 || true
  echo "[$STAMP] DONE resume $SID" >> "$LOG"
  exit 0
fi
cat "$ERR" >&2 || true

# 폴백하지 않는다. 조용한 폴백이 8/22~23 사고의 원인이었다.
# resume을 명시적으로 요청했으면 그 요청이 실패했다는 사실 자체가 결과다.
if grep -q "active writer" "$ERR" 2>/dev/null; then
  echo ""
  echo "resume 거부됨 (앱이 스레드를 점유 중). **폴백하지 않는다.**"
  echo "선택지 둘: 앱에서 그 스레드를 닫고 재시도하거나, --fresh로 발주해라."
  echo "[$STAMP] BLOCKED resume $SID (active writer, no fallback)" >> "$LOG"
  exit 2
fi
echo "[$STAMP] FAILED resume $SID" >> "$LOG"
exit 1
