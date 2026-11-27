#!/bin/bash
# Run one papers cycle of the improvement loop (tools/loop/lib/loop_papers.py) from the instance root.
# Usage: bash tools/loop/papers_cycle.sh --force | --resume YYYY-MM-DD
# Schedule: python3 tools/loop/loops.py start papers; stop: python3 tools/loop/loops.py stop papers
# --help prints this and starts nothing: any other argument would start a cycle with model runs.
case "${1:-}" in -h|--help) sed -n '2,4p' "$0" | sed 's/^# //'; exit 0 ;; esac
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "${BASH_SOURCE[0]}")/../.." && exec python3 tools/loop/lib/loop_papers.py "$@"
