#!/usr/bin/env bash
# MOTTORI_PRECOMMIT_HOOK_V1
# One file serves both of the kit's Git hooks, and it picks its job by the name it runs under:
# as pre-commit it verifies the installed hooks and runs the gate on the index to be committed;
# as pre-push it runs the push check. tools/install_hooks.sh installs it under both names.
set -euo pipefail

# Installer probe; ordinary pre-commit invocation passes no arguments.
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
    exec python3 "$ROOT/tools/enforce.py" --root "$ROOT" prepush "$@"
    ;;
  pre-commit)
    # A running owned hook verifies the installed pair before trusting the gate. This catches
    # drift in the companion pre-push hook and in the template. Another tool's pre-push hook (Git
    # LFS installs one) is the owner's and stops no commit: doctor reports that pushes are not
    # checked. Replacing this file itself remains outside a repo-local hook's authority.
    if ! CHECK="$(bash "$ROOT/tools/install_hooks.sh" --check 2>&1)"; then
      if printf '%s\n' "$CHECK" | cut -f1 | grep -qvxE 'current|chained|foreign'; then
        echo "mottori hook self-check failed (installed hooks differ from tools/lib/precommit-hook.sh):" >&2
        printf '%s\n' "$CHECK" >&2
        echo "fix: bash tools/install_hooks.sh --repair" >&2
        exit 1
      fi
    fi
    exec python3 "$ROOT/tools/gate.py" precommit
    ;;
  *)
    echo "unknown mottori hook entrypoint: $0" >&2
    exit 2
    ;;
esac
