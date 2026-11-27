#!/usr/bin/env bash
# Ask one or two runtimes the same prompt, each as a fresh, bounded worker. Two names run at once,
# and both run ids are printed and logged before the wait, so an interrupted caller can still
# find both runs.
#
# Usage:
#   bash tools/ask.sh <runtime>[,<runtime>] <prompt-file> [--web] [other tools/fresh_worker.py options]
#
# Pass prompt bytes through a file to avoid shell interpolation. Durable context belongs on disk.

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"   # Resolve the physical instance root from this script.
# Every tool below must read and write this checkout, not one an inherited variable points at.
export MOTTORI_INSTANCE="$ROOT"
usage() {
  cat <<EOF
usage: $0 <runtime>[,<runtime>] <prompt-file> [--web] [fresh_worker.py options]
  runtime: claude, codex or gemini; two names run at once and both run ids are printed first. By default
    claude and codex read this workspace and gemini a copy without the private area, so two runtimes
    read the same files only when config workers sets both to the same "where".
  --web: this worker gets the network and web search, and runs in a copy without the private area
    (with config workers.<runtime>.where instance, web_in_instance true runs it in the workspace). Without it every worker is offline.
  Refusals and the next step:
    the prompt file is outside the workspace: copy it into the workspace;
    the prompt file is under a path the model-send policy denies and the worker runs in a copy or a worktree: put the file elsewhere;
    codex --web outside the workspace: Codex's sandbox reads the whole disk, so ask claude or gemini with --web,
    or accept that with config workers.codex.where instance and web_in_instance true.
  Model, effort and folder per runtime: config key workers (see MANUAL.md section 2).
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  -*|"") usage; exit 1 ;;
esac
IFS=, read -r -a RUNTIMES <<< "$1"
if [ $# -lt 2 ] || [ "${#RUNTIMES[@]}" -gt 2 ] || [ "${RUNTIMES[0]}" = "${RUNTIMES[1]:-}" ]; then
  usage
  exit 1
fi
for RT in "${RUNTIMES[@]}"; do
  case "$RT" in claude|codex|gemini) ;; *) usage; exit 1 ;; esac
done

# A relative prompt path is the caller's: rewrite it relative to the root. fresh_worker.py joins a
# relative path to its own root, so the cwd and the script path may each be spelled
# differently (symlink alias, letter case); compare physical folders, and keep it as typed at the root.
# An absolute path spelled through the script's own symlinked path keeps the rest as typed, so
# the worker's symlink check still sees every component below the root.
LOGICAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$2" in
  "$LOGICAL_ROOT"/*) PROMPT_FILE="$ROOT${2#"$LOGICAL_ROOT"}" ;;
  /*) PROMPT_FILE="$2" ;;
  *) PROMPT_FILE="$(python3 -c 'import os, sys
here = os.getcwd()
os.chdir(sys.argv[2])
root = os.getcwd()
print(sys.argv[1] if here == root else os.path.relpath(os.path.join(here, sys.argv[1]), root))' "$2" "$ROOT")" ;;
esac
shift 2
cd "$ROOT"

[ -f "$PROMPT_FILE" ] || { echo "prompt file missing: $PROMPT_FILE"; exit 1; }
LOG="$(python3 tools/lib/paths.py debate_dispatch_log)"
mkdir -p "$(dirname "$LOG")"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

if [ "${#RUNTIMES[@]}" -eq 1 ]; then
  log "${RUNTIMES[0]} FRESH <- $PROMPT_FILE"
  # Record the outcome either way; under set -e a failed run would otherwise leave only FRESH.
  RC=0
  python3 "$ROOT/tools/fresh_worker.py" --runtime "${RUNTIMES[0]}" --finish-note "$@" "$PROMPT_FILE" || RC=$?
  if [ "$RC" -eq 0 ]; then log "${RUNTIMES[0]} DONE fresh"; else log "${RUNTIMES[0]} FAILED fresh (exit $RC)"; fi
  exit "$RC"
fi

# A template keeps the folder under TMPDIR; plain mktemp -d on macOS uses the per-user temporary folder.
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ask.XXXXXX")"
PIDS=()
trap 'rm -rf "$TMP"' EXIT
# The workers clean up their own copies on TERM; the wait below then reports how each ended.
trap 'kill "${PIDS[@]}" 2>/dev/null || true' INT TERM
for i in 0 1; do
  log "${RUNTIMES[$i]} FRESH <- $PROMPT_FILE"
  python3 "$ROOT/tools/fresh_worker.py" --runtime "${RUNTIMES[$i]}" --finish-note "$@" "$PROMPT_FILE" \
    > "$TMP/$i.out" 2> "$TMP/$i.err" &
  PIDS+=("$!")
done
for i in 0 1; do
  ID=""
  # The worker prints its run id when the run record exists; a worker refused before that has none.
  while :; do
    ID="$(grep -Eo "[0-9]{8}T[0-9]{6}[-+][0-9]{4}-${RUNTIMES[$i]}-[0-9a-f]{8}" "$TMP/$i.err" | head -n 1 || true)"
    [ -n "$ID" ] && break
    kill -0 "${PIDS[$i]}" 2>/dev/null || break
    sleep 0.1
  done
  echo "asked ${RUNTIMES[$i]}: run ${ID:--}" >&2
  log "${RUNTIMES[$i]} ASKED run ${ID:--}"
done
RC=0
for i in 0 1; do
  CODE=0
  wait "${PIDS[$i]}" || CODE=$?
  cat "$TMP/$i.out"
  cat "$TMP/$i.err" >&2
  if [ "$CODE" -eq 0 ]; then log "${RUNTIMES[$i]} DONE fresh"; else log "${RUNTIMES[$i]} FAILED fresh (exit $CODE)"; fi
  if [ "$RC" -eq 0 ]; then RC="$CODE"; fi
done
exit "$RC"
