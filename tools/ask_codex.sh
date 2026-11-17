#!/bin/bash
# Dispatch one Codex task. Fresh, bounded execution is the default.
# Explicit resume fails without falling back to another session.
#
# Usage:
#   bash tools/ask_codex.sh <prompt-file>
#   bash tools/ask_codex.sh <prompt-file> --resume <SID>
#
# --resume calls `codex exec resume` directly and bypasses the fresh-worker contract: user config,
# feature lockdown, run record, and receipt cap do not apply. The thread id must be given explicitly
# because session history is shared across projects.
#
# Pass prompt bytes through a file to avoid shell interpolation. Durable context belongs on disk.

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # Resolve the instance root from this script.
cd "$ROOT"

# Print a catalog message in the instance language. sync_engine.sh copies this script without
# tools/i18n.py, and an older catalog may lack the key, so fall back to the English text given.
say() {
  local key="$1" fallback="$2"
  shift 2
  python3 "$ROOT/tools/i18n.py" "$key" "$@" 2>/dev/null || printf '%s\n' "$fallback"
}

PROMPT_FILE="$1"
[ -f "$PROMPT_FILE" ] || { say ask_codex.prompt_missing "prompt file missing: $PROMPT_FILE" "path=$PROMPT_FILE"; exit 1; }
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
  # Record the outcome either way; under set -e a failed run would otherwise leave only FRESH.
  RC=0
  python3 "$ROOT/tools/fresh_worker.py" "${ARGS[@]}" "$PROMPT_FILE" || RC=$?
  if [ "$RC" -eq 0 ]; then
    echo "[$STAMP] DONE fresh" >> "$LOG"
  else
    echo "[$STAMP] FAILED fresh (exit $RC)" >> "$LOG"
  fi
  exit "$RC"
fi

if [ "$MODE" != "--resume" ] || [ -z "$SID" ]; then
  say ask_codex.usage "usage: $0 <prompt-file> [--fresh | --resume <SID>]" "script=$0"
  say ask_codex.usage_resume "  --resume skips the worker contract (user config ignored, features locked, run record, receipt cap) and writes straight into that thread."
  exit 1
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
  say ask_codex.resume_refused "resume refused (the app holds the thread). **No fallback.**"
  say ask_codex.resume_choices "Two options: close the thread in the app and retry, or dispatch with --fresh."
  echo "[$STAMP] BLOCKED resume $SID (active writer, no fallback)" >> "$LOG"
  exit 2
fi
echo "[$STAMP] FAILED resume $SID" >> "$LOG"
exit 1
