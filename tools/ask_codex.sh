#!/bin/bash
# Dispatch one Codex task. Fresh, bounded execution is the default.
# Explicit resume fails without falling back to another session.
#
# Usage:
#   bash tools/ask_codex.sh <prompt-file>
#   bash tools/ask_codex.sh <prompt-file> --resume <SID>
#   bash tools/ask_codex.sh <prompt-file> --resume-root
#
# Pass prompt bytes through a file to avoid shell interpolation. Durable context belongs on disk.

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # Resolve the instance root from this script.
cd "$ROOT"
PROMPT_FILE="$1"
[ -f "$PROMPT_FILE" ] || { echo "프롬프트 파일 없음: $PROMPT_FILE"; exit 1; }
LOG="system/debate/_dispatch.log"
ERR="$(mktemp)"
trap 'rm -f "$ERR"' EXIT
STAMP=$(date '+%Y-%m-%d %H:%M:%S')
MODE="${2:---fresh}"
SID="$3"

if [ "$MODE" = "--fresh" ] || [ -z "$MODE" ]; then
  echo "[$STAMP] FRESH <- $PROMPT_FILE" >> "$LOG"
  ARGS=(--runtime codex)
  # MOTTORI_WORKTREE=1 copies the tracked diff into an isolated dirty worktree.
  if [ "${MOTTORI_WORKTREE:-}" = "1" ]; then
    ARGS+=(--worktree)
  fi
  # MOTTORI_WRITE_PREFIX optionally limits the measured write scope inside the worktree.
  if [ -n "${MOTTORI_WRITE_PREFIX:-}" ]; then
    ARGS+=(--write-prefix "$MOTTORI_WRITE_PREFIX")
  fi
  python3 "$ROOT/tools/fresh_worker.py" "${ARGS[@]}" "$PROMPT_FILE"
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

# An explicitly requested resume failure must remain visible; never silently start a fresh session.
if grep -q "active writer" "$ERR" 2>/dev/null; then
  echo ""
  echo "resume 거부됨 (앱이 스레드를 점유 중). **폴백하지 않는다.**"
  echo "선택지 둘: 앱에서 그 스레드를 닫고 재시도하거나, --fresh로 발주해라."
  echo "[$STAMP] BLOCKED resume $SID (active writer, no fallback)" >> "$LOG"
  exit 2
fi
echo "[$STAMP] FAILED resume $SID" >> "$LOG"
exit 1
