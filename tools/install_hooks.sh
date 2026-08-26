#!/usr/bin/env bash
# active Git pre-commit backstop의 상태를 진단하거나 명시적으로 복구한다.
#
#   bash tools/install_hooks.sh --check   # read-only: current/missing/owned-drift/foreign
#   bash tools/install_hooks.sh --repair  # foreign은 거부, owned drift는 backup 뒤 atomic 교체
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "--check" && "$MODE" != "--repair" ]]; then
  echo "usage: bash tools/install_hooks.sh --check|--repair" >&2
  exit 2
fi

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
  # linked worktree의 `$GIT_DIR/hooks`는 dispatcher가 읽지 않는 admin 하위다. Git 자신에게
  # common hooks 경로를 묻는다.
  DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-path hooks)"
fi
HOOK="$DIR/pre-commit"

# Sentinel 도입 직전 canonical 둘만 migration 대상으로 인정한다. 임의 hook에 설명문으로
# "mottori gate"가 들어갔다고 소유권을 주장하면 --repair가 foreign 코드를 덮어쓴다.
LEGACY_HASHES="
28d6734242d51d3b6d63c4b31796864d659c320b85eb48fe803a5d7f807e12ee
89fe10c571d56547e4235da07a777490f31e32fd2b6169d47bd49f5b4cda261e
"

sha256() { shasum -a 256 "$1" | awk '{print $1}'; }

classify() {
  if [[ ! -e "$HOOK" ]]; then
    echo "missing"
  elif cmp -s "$TEMPLATE" "$HOOK" && [[ -x "$HOOK" ]]; then
    echo "current"
  elif cmp -s "$TEMPLATE" "$HOOK"; then
    echo "owned-drift"
  elif grep -Fxq "$(sha256 "$HOOK")" <<< "$LEGACY_HASHES"; then
    echo "owned-drift"
  else
    echo "foreign"
  fi
}

STATUS="$(classify)"
if [[ "$MODE" == "--check" ]]; then
  echo "$STATUS: $HOOK"
  if [[ "$STATUS" == "owned-drift" ]]; then
    echo "template sha256: $(sha256 "$TEMPLATE")"
    echo "installed sha256: $(sha256 "$HOOK")"
    diff -u "$HOOK" "$TEMPLATE" | sed -n '1,40p' || true
  fi
  [[ "$STATUS" == "current" ]]
  exit
fi

if [[ "$STATUS" == "foreign" ]]; then
  echo "foreign pre-commit을 덮어쓰지 않는다: $HOOK" >&2
  exit 2
fi

mkdir -p "$DIR"
BACKUP=""
if [[ "$STATUS" == "owned-drift" ]]; then
  BACKUP="$HOOK.bak.$(date +%Y%m%dT%H%M%S).$$"
  cp -p "$HOOK" "$BACKUP"
fi
TMP="$DIR/.pre-commit.$$.tmp"
cleanup() { rm -f "$TMP"; }
trap cleanup EXIT
cp "$TEMPLATE" "$TMP"
chmod 755 "$TMP"
mv -f "$TMP" "$HOOK"

rollback() {
  if [[ -n "$BACKUP" && -e "$BACKUP" ]]; then
    cp -p "$BACKUP" "$HOOK"
  else
    rm -f "$HOOK"
  fi
}

if ! cmp -s "$TEMPLATE" "$HOOK" || [[ ! -x "$HOOK" ]]; then
  rollback
  echo "repair 검증 실패, 원상 복구: $HOOK" >&2
  exit 1
fi

NONCE="probe-$$-$(date +%s)"
# `git hook run` forwards hook stdout on its own stderr channel. Capture both; checking only exit 0
# repeats the old `--ignore-missing` false proof.
GOT="$(git -C "$ROOT" hook run pre-commit -- --mottori-probe "$NONCE" 2>&1 || true)"
if [[ "$GOT" != "$NONCE" ]]; then
  rollback
  echo "git dispatcher probe 실패, 원상 복구: $HOOK" >&2
  exit 1
fi

echo "current: $HOOK (exact template + executable + git dispatcher probe)"
[[ -z "$BACKUP" ]] || echo "backup: $BACKUP"
