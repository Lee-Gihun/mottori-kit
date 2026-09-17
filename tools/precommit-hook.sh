#!/usr/bin/env bash
# MOTTORI_PRECOMMIT_HOOK_V1
# The mottori gate checks the index to be committed. Installed by tools/install_hooks.sh.
set -euo pipefail

# Dispatch probe used only by `git hook run`; an ordinary commit passes no arguments to pre-commit.
if [[ "${1:-}" == "--mottori-probe" ]]; then
  [[ "${2:-}" == probe-* ]] || { echo "invalid mottori probe" >&2; exit 2; }
  printf '%s\n' "$2"
  exit 0
fi

# If this variable points to another clean clone, a broken index could pass. gate.py also
# fails closed when the root differs from its own location.
unset MOTTORI_INSTANCE
ROOT="$(git rev-parse --show-toplevel)"

case "$(basename "$0")" in
  pre-push)
    exec python3 "$ROOT/tools/enforce.py" --root "$ROOT" prepush
    ;;
  pre-commit)
    # A running owned hook verifies the complete installed pair before trusting the gate. This
    # catches drift in the companion pre-push hook and template. Replacing this file itself remains
    # outside a repo-local hook's authority and is reported as REVIEW in the enforcement matrix.
    if ! bash "$ROOT/tools/install_hooks.sh" --check >/dev/null 2>&1; then
      echo "mottori hook self-check failed (installed hooks differ from tools/precommit-hook.sh):" >&2
      bash "$ROOT/tools/install_hooks.sh" --check >&2 || true
      echo "fix: bash tools/install_hooks.sh --repair" >&2
      exit 1
    fi
    exec python3 "$ROOT/tools/gate.py" precommit
    ;;
  *)
    echo "unknown mottori hook entrypoint: $0" >&2
    exit 2
    ;;
esac
