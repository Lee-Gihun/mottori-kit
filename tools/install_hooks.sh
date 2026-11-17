#!/usr/bin/env bash
# Check and repair owned Git hooks.
#
# Reject foreign hooks. Back up drifted owned hooks and replace them atomically.
# Usage: bash tools/install_hooks.sh --check|--repair
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "--check" && "$MODE" != "--repair" ]]; then
  echo "usage: bash tools/install_hooks.sh --check|--repair" >&2
  exit 2
fi

# Print a catalog message from tools/i18n.py in the instance language: say KEY FALLBACK [name=value]...
# A fixture may hold only this script and the hook template; then the English FALLBACK, already
# filled in by the caller, is printed instead.
say() {
  local key="$1" fallback="$2"
  shift 2
  if [[ -f "$ROOT/tools/i18n.py" ]] && python3 "$ROOT/tools/i18n.py" "$key" "$@" 2>/dev/null; then
    return 0
  fi
  printf '%s\n' "$fallback"
}

# doctor.py reads the first line of --check and accepts the status word in either language.
status_line() {
  local status="$1" target="$2"
  case "$status" in
    current) say install_hooks.status_current "current: $target" "target=$target" ;;
    missing) say install_hooks.status_missing "missing: $target" "target=$target" ;;
    owned-drift) say install_hooks.status_owned_drift "owned-drift: $target" "target=$target" ;;
    foreign) say install_hooks.status_foreign "foreign: $target" "target=$target" ;;
  esac
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$ROOT/tools/precommit-hook.sh"
[[ -f "$TEMPLATE" ]] || { echo "template-missing: $TEMPLATE" >&2; exit 2; }

HOOKSPATH="$(git -C "$ROOT" config --get core.hooksPath || true)"
if [[ -n "$HOOKSPATH" ]]; then
  if [[ "$HOOKSPATH" = /* ]]; then
    DIR="$HOOKSPATH"
  else
    DIR="$ROOT/$HOOKSPATH"
  fi
  RESOLVED="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$DIR")"
  case "$RESOLVED" in
    "$ROOT"|"$ROOT"/*) DIR="$RESOLVED" ;;
    *) echo "outside-repo hooksPath: $RESOLVED" >&2; exit 2 ;;
  esac
else
  # Ask Git for the common hook directory, including linked worktrees; avoid newer-version-only flags.
  RAW_DIR="$(git -C "$ROOT" rev-parse --git-path hooks)"
  case "$RAW_DIR" in
    /*) DIR="$RAW_DIR" ;;
    *) DIR="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.join(sys.argv[1], sys.argv[2])))' "$ROOT" "$RAW_DIR")" ;;
  esac
fi
HOOK="$DIR/pre-commit"
PUSH_HOOK="$DIR/pre-push"

# Recognize legacy ownership by exact bytes, never by a matching phrase.
LEGACY_HASHES="
a90b84bf06dbc075c3c269b3e61c61ebdf25ea55f4fb8bd268f24fe1acc41c3e
c078fa3e14b9a9152bad2ba4540efac5e3ca19e9d8b7467028e07f80dd022141
28d6734242d51d3b6d63c4b31796864d659c320b85eb48fe803a5d7f807e12ee
89fe10c571d56547e4235da07a777490f31e32fd2b6169d47bd49f5b4cda261e
97c1f2144a63fbc3fb120cce56bd32a14b77948872183b73435a2e985fd951f9
2749f33d184abd3c18069f206e9d3717acc4d56e9f1bee68dce6517298e4e7ee
"
# Tests and migrations may add hashes without editing this file; a hook marked owned only gets
# replaced by our own template, so this cannot make the installer overwrite something with foreign code.
if [[ -n "${MOTTORI_LEGACY_HOOK_HASHES:-}" ]]; then
  LEGACY_HASHES="$LEGACY_HASHES
${MOTTORI_LEGACY_HOOK_HASHES//,/
}"
fi

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
  fi
}

# A hash stamp preserves ownership across template updates; legacy hashes cover only unstamped versions.
STAMP="$DIR/mottori-hooks.stamp"
stamped_hash() {  # stamped_hash <hook-basename>
  [[ -f "$STAMP" ]] && awk -v n="$1" '$1==n {print $2}' "$STAMP" || true
}
classify() {
  local target="$1"
  local name; name="$(basename "$target")"
  if [[ ! -e "$target" ]]; then
    echo "missing"
  elif cmp -s "$TEMPLATE" "$target" && [[ -x "$target" ]]; then
    echo "current"
  elif cmp -s "$TEMPLATE" "$target"; then
    echo "owned-drift"
  elif [[ -n "$(stamped_hash "$name")" && "$(stamped_hash "$name")" == "$(sha256 "$target")" ]]; then
    echo "owned-drift"
  elif grep -Fxq "$(sha256 "$target")" <<< "$LEGACY_HASHES"; then
    echo "owned-drift"
  else
    echo "foreign"
  fi
}

STATUS="$(classify "$HOOK")"
PUSH_STATUS="$(classify "$PUSH_HOOK")"
if [[ "$MODE" == "--check" ]]; then
  if [[ "$STATUS" == "current" && "$PUSH_STATUS" == "current" ]]; then
    say install_hooks.current_pair "current: $HOOK + $PUSH_HOOK" "hook=$HOOK" "push_hook=$PUSH_HOOK"
    exit 0
  fi
  status_line "$STATUS" "$HOOK"
  status_line "$PUSH_STATUS" "$PUSH_HOOK"
  if [[ "$STATUS" == "owned-drift" ]]; then
    TEMPLATE_SHA="$(sha256 "$TEMPLATE")"
    INSTALLED_SHA="$(sha256 "$HOOK")"
    say install_hooks.template_sha "template sha256: $TEMPLATE_SHA" "sha=$TEMPLATE_SHA"
    say install_hooks.installed_sha "installed sha256: $INSTALLED_SHA" "sha=$INSTALLED_SHA"
    diff -u "$HOOK" "$TEMPLATE" | sed -n '1,40p' || true
  fi
  exit 1
fi

if [[ "$STATUS" == "foreign" || "$PUSH_STATUS" == "foreign" ]]; then
  say install_hooks.foreign_refused \
    "refusing to overwrite a foreign pre-commit/pre-push: $HOOK ($STATUS), $PUSH_HOOK ($PUSH_STATUS)" \
    "hook=$HOOK" "status=$STATUS" "push_hook=$PUSH_HOOK" "push_status=$PUSH_STATUS" >&2
  exit 2
fi

mkdir -p "$DIR"
BACKUP=""
PUSH_BACKUP=""
ROLLBACK_DIR="$(mktemp -d "$DIR/.mottori-hook-rollback.XXXXXX")"
HOOK_EXISTED=0
PUSH_HOOK_EXISTED=0
if [[ -e "$HOOK" || -L "$HOOK" ]]; then
  cp -p "$HOOK" "$ROLLBACK_DIR/pre-commit"
  HOOK_EXISTED=1
fi
if [[ -e "$PUSH_HOOK" || -L "$PUSH_HOOK" ]]; then
  cp -p "$PUSH_HOOK" "$ROLLBACK_DIR/pre-push"
  PUSH_HOOK_EXISTED=1
fi
if [[ "$STATUS" == "owned-drift" ]]; then
  BACKUP="$HOOK.bak.$(date +%Y%m%dT%H%M%S).$$"
  cp -p "$HOOK" "$BACKUP"
fi
if [[ "$PUSH_STATUS" == "owned-drift" ]]; then
  PUSH_BACKUP="$PUSH_HOOK.bak.$(date +%Y%m%dT%H%M%S).$$"
  cp -p "$PUSH_HOOK" "$PUSH_BACKUP"
fi
TMP="$DIR/.pre-commit.$$.tmp"
PUSH_TMP="$DIR/.pre-push.$$.tmp"
cleanup() { rm -f "$TMP" "$PUSH_TMP"; rm -rf "$ROLLBACK_DIR"; }
trap cleanup EXIT
cp "$TEMPLATE" "$TMP"
cp "$TEMPLATE" "$PUSH_TMP"
chmod 755 "$TMP"
chmod 755 "$PUSH_TMP"
mv -f "$TMP" "$HOOK"
mv -f "$PUSH_TMP" "$PUSH_HOOK"

rollback() {
  if [[ "$HOOK_EXISTED" -eq 1 ]]; then
    cp -p "$ROLLBACK_DIR/pre-commit" "$HOOK"
  else
    rm -f "$HOOK"
  fi
  if [[ "$PUSH_HOOK_EXISTED" -eq 1 ]]; then
    cp -p "$ROLLBACK_DIR/pre-push" "$PUSH_HOOK"
  else
    rm -f "$PUSH_HOOK"
  fi
}

if ! cmp -s "$TEMPLATE" "$HOOK" || [[ ! -x "$HOOK" ]] \
   || ! cmp -s "$TEMPLATE" "$PUSH_HOOK" || [[ ! -x "$PUSH_HOOK" ]]; then
  rollback
  say install_hooks.repair_failed "repair verification failed, restored: $HOOK" "hook=$HOOK" >&2
  exit 1
fi

# setup measures the baseline before hooks. Repair signs that measured set with keyed hash+HMAC
# without running the release regression boundary again.
# Fixtures without a baseline are hook-only tests and intentionally skip this step.
if [[ -f "$ROOT/state/.gate-baseline.json" ]] && ! python3 "$ROOT/tools/gate.py" seal-baseline >/dev/null; then
  rollback
  say install_hooks.seal_failed "baseline seal failed, hook restored" >&2
  exit 1
fi

NONCE="probe-$$-$(date +%s)"
# Probe the executable directly to support Git versions without git hook run.
GOT="$("$HOOK" --mottori-probe "$NONCE" 2>&1 || true)"
if [[ "$GOT" != "$NONCE" ]]; then
  rollback
  say install_hooks.probe_failed "git dispatcher probe failed, restored: $HOOK" "hook=$HOOK" >&2
  exit 1
fi

printf 'pre-commit %s\npre-push %s\n' "$(sha256 "$HOOK")" "$(sha256 "$PUSH_HOOK")" > "$STAMP"

say install_hooks.repaired \
  "current: $HOOK + $PUSH_HOOK (exact template + executable + direct hook probe + sealed baseline)" \
  "hook=$HOOK" "push_hook=$PUSH_HOOK"
[[ -z "$BACKUP" ]] || say install_hooks.backup "backup: $BACKUP" "path=$BACKUP"
[[ -z "$PUSH_BACKUP" ]] || say install_hooks.backup "backup: $PUSH_BACKUP" "path=$PUSH_BACKUP"
