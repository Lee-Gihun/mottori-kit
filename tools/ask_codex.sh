#!/usr/bin/env bash
# Compatibility entry for one fresh Codex worker; tools/ask.sh does the work. There is no resume mode.
#
# Usage:
#   bash tools/ask_codex.sh <prompt-file>
#
# MOTTORI_WORKTREE=1 runs in an isolated dirty worktree; MOTTORI_WRITE_PREFIX limits the measured
# write scope inside it.

set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # Logical: ask.sh resolves an alias spelling itself.
export MOTTORI_INSTANCE="$(cd "$DIR/.." && pwd -P)"

case "${1:-}" in -h|--help)
  echo "Hand one prompt file to a fresh Codex worker (tools/ask.sh codex does the work)."
  echo
  echo "usage: bash tools/ask_codex.sh <prompt-file>"
  echo "  <prompt-file>  the prompt, a file inside this folder; every call is a new worker"
  exit 0 ;;
esac
# Arguments first: an option or no argument is a usage error, not a missing prompt file.
case "${1:-}" in -*|"") set -- ;; esac
if [ $# -ne 1 ]; then
  echo "usage: $0 <prompt-file>"
  exit 1
fi
ARGS=()
if [ "${MOTTORI_WORKTREE:-}" = "1" ]; then
  # With an optional value, a bare --worktree would take the prompt path as its value.
  ARGS+=(--worktree=dirty)
fi
if [ -n "${MOTTORI_WRITE_PREFIX:-}" ]; then
  ARGS+=(--write-prefix "$MOTTORI_WRITE_PREFIX")
fi
exec bash "$DIR/ask.sh" codex "$1" "${ARGS[@]}"
