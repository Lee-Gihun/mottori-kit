#!/usr/bin/env bash
# MOTTORI_PRECOMMIT_HOOK_V1
# mottori gate — 커밋될 index를 검사한다. tools/install_hooks.sh가 설치했다.
set -euo pipefail

# git hook run 전용 dispatch probe. 일반 git commit은 pre-commit에 인자를 전달하지 않는다.
if [[ "${1:-}" == "--mottori-probe" ]]; then
  [[ "${2:-}" == probe-* ]] || { echo "invalid mottori probe" >&2; exit 2; }
  printf '%s\n' "$2"
  exit 0
fi

# 이 변수가 깨끗한 다른 clone을 가리키면 깨진 index가 통과할 수 있다. gate.py도 root가
# 자기 위치와 다르면 fail-close한다.
unset MOTTORI_INSTANCE
ROOT="$(git rev-parse --show-toplevel)"
exec python3 "$ROOT/tools/gate.py" precommit
