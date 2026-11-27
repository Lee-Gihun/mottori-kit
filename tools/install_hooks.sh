#!/usr/bin/env bash
# Check and repair the kit's Git hooks, pre-commit and pre-push.
#
# Leave another tool's hook as it is and name the ways forward; install the free ones. Back up
# drifted owned hooks and replace them atomically.
# Usage: bash tools/install_hooks.sh --check|--repair
#
# Both modes print one line per hook: a status word, a tab, the hook's path, and optionally a tab
# and text for a person. Status words: current, chained (another tool's hook that runs the kit's
# check), foreign, missing, owned-drift. A reader takes the first two fields, never the text.
# --check exits 0 when both hooks are current or chained, else 1; details of a drifted hook go to
# stderr. --repair exits 0 when it leaves both hooks current or chained, 2 when a foreign hook
# is in the way. Exit 3: core.hooksPath points outside this repository, so nothing is written
# there; other refusals exit 2 with the reason on stderr.
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" == "-h" || "$MODE" == "--help" ]]; then
  echo "Check and repair the kit's Git hooks, pre-commit and pre-push."
  echo
  echo "usage: bash tools/install_hooks.sh --check|--repair"
  echo "  --check   print each hook's state; exit 0 when both are the kit's or run its check"
  echo "  --repair  install a missing or older kit hook, keeping a backup; another tool's hook is left as it is"
  exit 0
fi
if [[ "$MODE" != "--check" && "$MODE" != "--repair" ]]; then
  echo "usage: bash tools/install_hooks.sh --check|--repair" >&2
  exit 2
fi

status_line() {
  local status="$1" target="$2" line
  line="$(chain_line "$(basename "$target")")"
  case "$status" in
    current|missing) printf '%s\t%s\n' "$status" "$target" ;;
    chained) printf '%s\t%s\t%s\n' "$status" "$target" "not the kit's hook; it runs the kit's check" ;;
    owned-drift) printf '%s\t%s\t%s\n' "$status" "$target" "an older kit hook; bash tools/install_hooks.sh --repair replaces it and keeps a backup" ;;
    foreign) printf '%s\t%s\t%s\n' "$status" "$target" "not the kit's hook, left as it is; either add the line \`$line\` to it right after its first line, or move it out of the hooks folder and run bash tools/install_hooks.sh --repair" ;;
  esac
}

# Another tool's hook is never rewritten. It counts as installed when it runs the kit's check
# through this exact line; Git runs both hooks from the top of the work tree, so the paths are relative.
chain_line() {
  case "$1" in
    pre-commit) printf '%s' 'python3 tools/gate.py precommit || exit 1' ;;
    pre-push) printf '%s' 'python3 tools/enforce.py prepush "$@" || exit 1' ;;
  esac
}

# Physical path, so it compares equal to the realpath-resolved hook directory below even through a symlink.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEMPLATE="$ROOT/tools/lib/precommit-hook.sh"
[[ -f "$TEMPLATE" ]] || { echo "template-missing: $TEMPLATE" >&2; exit 2; }

# A kit folder inside another project's repository would install hooks that run on that
# project's commits and look for these tools at its root.
TOP="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" && TOP="$(cd "$TOP" && pwd -P)" || TOP=""
if [[ "$TOP" != "$ROOT" ]]; then
  echo "not-own-repo: $ROOT is not the top of its own git repository; run git init there first" >&2
  exit 2
fi

realpath_in_root() { python3 -c 'import os,sys; print(os.path.realpath(os.path.join(sys.argv[1], sys.argv[2])))' "$ROOT" "$1"; }
# Ask Git for the hook directory so its own rules apply: ~ expansion and relative core.hooksPath,
# and the common directory of a linked worktree. Avoid newer-version-only flags.
DIR="$(realpath_in_root "$(git -C "$ROOT" rev-parse --git-path hooks)")"
# A hooksPath outside this folder is shared with other repositories; writing there would change them
# too. The repository's own hooks folder is the exception: in a linked worktree it lies outside.
if [[ -n "$(git -C "$ROOT" config --get core.hooksPath || true)" ]]; then
  OWN_HOOKS="$(realpath_in_root "$(git -C "$ROOT" rev-parse --git-common-dir)/hooks")"
  case "$DIR" in
    "$ROOT"|"$ROOT"/*|"$OWN_HOOKS") ;;
    *) echo "outside-repo hooksPath: $DIR; to install here, run git config core.hooksPath \"$OWN_HOOKS\", then bash tools/install_hooks.sh --repair" >&2
       exit 3 ;;
  esac
fi
HOOK="$DIR/pre-commit"
PUSH_HOOK="$DIR/pre-push"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
  fi
}

# The stamp holds the hash of each hook this installer wrote, so an older kit hook is still known
# as the kit's after the template changes. Ownership is recognized by exact bytes, never by a phrase.
STAMP="$DIR/mottori-hooks.stamp"
stamped_hash() {  # stamped_hash <hook-basename>
  [[ -f "$STAMP" ]] && awk -v n="$1" '$1==n {print $2}' "$STAMP" || true
}
classify() {
  local target="$1" hash
  local name; name="$(basename "$target")"
  # A directory or an unreadable file has no hash; an empty one must match nothing.
  hash="$(sha256 "$target" 2>/dev/null)" || hash=""
  if [[ -L "$target" && ! -e "$target" ]]; then
    echo "foreign"  # A dangling link is someone's hook setup, not a free slot.
  elif [[ ! -e "$target" ]]; then
    echo "missing"
  elif cmp -s "$TEMPLATE" "$target" 2>/dev/null && [[ -x "$target" ]]; then
    echo "current"
  elif cmp -s "$TEMPLATE" "$target" 2>/dev/null; then
    echo "owned-drift"
  elif [[ -n "$hash" && "$(stamped_hash "$name")" == "$hash" ]]; then
    echo "owned-drift"
  elif [[ -f "$target" && -x "$target" ]] \
       && awk -v l="$(chain_line "$name")" '{ gsub(/^[ \t]+|[ \t]+$/, "") } $0 == l { f = 1 } END { exit !f }' "$target"; then
    echo "chained"
  else
    echo "foreign"
  fi
}

STATUS="$(classify "$HOOK")"
PUSH_STATUS="$(classify "$PUSH_HOOK")"
ok() { [[ "$1" == "current" || "$1" == "chained" ]]; }
if [[ "$MODE" == "--check" ]]; then
  # Setup shows the first line, so a hook that is not in place comes first; else pre-commit does.
  if ok "$STATUS" && ! ok "$PUSH_STATUS"; then
    status_line "$PUSH_STATUS" "$PUSH_HOOK"
    status_line "$STATUS" "$HOOK"
  else
    status_line "$STATUS" "$HOOK"
    status_line "$PUSH_STATUS" "$PUSH_HOOK"
  fi
  ok "$STATUS" && ok "$PUSH_STATUS" && exit 0
  if [[ "$STATUS" == "owned-drift" ]]; then
    {
      echo "template sha256: $(sha256 "$TEMPLATE")"
      echo "installed sha256: $(sha256 "$HOOK")"
      diff -u "$HOOK" "$TEMPLATE" | sed -n '1,40p' || true
    } >&2
  fi
  exit 1
fi

# Repair writes every hook that is missing or drifted and leaves a current, chained or foreign
# one as it is, so one foreign hook does not leave the other unchecked; a foreign hook still
# makes the repair fail. A drifted hook is first copied to a dated backup, which is also what a
# failed repair restores.
install_it() { [[ "$1" == "missing" || "$1" == "owned-drift" ]]; }
INSTALL_HOOK=0; INSTALL_PUSH=0
install_it "$STATUS" && INSTALL_HOOK=1
install_it "$PUSH_STATUS" && INSTALL_PUSH=1

mkdir -p "$DIR"
backup() {  # backup <hook> <status>: print the backup's path, empty for a hook not backed up
  [[ "$2" == "owned-drift" ]] || return 0
  local copy; copy="$1.bak.$(date +%Y%m%dT%H%M%S).$$"
  cp -p "$1" "$copy" && printf '%s' "$copy"
}
BACKUP="$(backup "$HOOK" "$STATUS")"
PUSH_BACKUP="$(backup "$PUSH_HOOK" "$PUSH_STATUS")"
TMP="$DIR/.pre-commit.$$.tmp"
PUSH_TMP="$DIR/.pre-push.$$.tmp"
cleanup() { rm -f "$TMP" "$PUSH_TMP"; }
trap cleanup EXIT
if [[ "$INSTALL_HOOK" -eq 1 ]]; then
  cp "$TEMPLATE" "$TMP"; chmod 755 "$TMP"; mv -f "$TMP" "$HOOK"
fi
if [[ "$INSTALL_PUSH" -eq 1 ]]; then
  cp "$TEMPLATE" "$PUSH_TMP"; chmod 755 "$PUSH_TMP"; mv -f "$PUSH_TMP" "$PUSH_HOOK"
fi

restore() {  # restore <hook> <installed 0|1> <backup>
  [[ "$2" -eq 1 ]] || return 0
  if [[ -n "$3" ]]; then cp -p "$3" "$1"; else rm -f "$1"; fi
}
rollback() {
  restore "$HOOK" "$INSTALL_HOOK" "$BACKUP"
  restore "$PUSH_HOOK" "$INSTALL_PUSH" "$PUSH_BACKUP"
}
# A hook left as it is passes verification on its own; only a written one must match the template.
written_ok() { [[ "$1" -eq 0 ]] || { cmp -s "$TEMPLATE" "$2" && [[ -x "$2" ]]; }; }

if ! written_ok "$INSTALL_HOOK" "$HOOK" || ! written_ok "$INSTALL_PUSH" "$PUSH_HOOK"; then
  rollback
  echo "repair verification failed, restored: $HOOK" >&2
  exit 1
fi

NONCE="probe-$$-$(date +%s)"
# Probe the executable directly to support Git versions without git hook run.
PROBE="$HOOK"; [[ "$INSTALL_HOOK" -eq 1 ]] || PROBE="$PUSH_HOOK"
GOT="$NONCE"
[[ "$INSTALL_HOOK" -eq 0 && "$INSTALL_PUSH" -eq 0 ]] || GOT="$("$PROBE" --mottori-probe "$NONCE" 2>&1 || true)"
if [[ "$GOT" != "$NONCE" ]]; then
  rollback
  echo "git dispatcher probe failed, restored: $HOOK" >&2
  exit 1
fi

# The stamp names every hook that is now the template, written here or already current.
[[ "$INSTALL_HOOK" -eq 1 ]] && STATUS=current
[[ "$INSTALL_PUSH" -eq 1 ]] && PUSH_STATUS=current
{
  [[ "$STATUS" != "current" ]] || printf 'pre-commit %s\n' "$(sha256 "$HOOK")"
  [[ "$PUSH_STATUS" != "current" ]] || printf 'pre-push %s\n' "$(sha256 "$PUSH_HOOK")"
} > "$STAMP"

for pair in "$STATUS $HOOK" "$PUSH_STATUS $PUSH_HOOK"; do
  [[ "${pair%% *}" == "foreign" ]] || status_line "${pair%% *}" "${pair#* }"
done
[[ -z "$BACKUP" ]] || echo "backup: $BACKUP"
[[ -z "$PUSH_BACKUP" ]] || echo "backup: $PUSH_BACKUP"
[[ "$STATUS" != "foreign" ]] || status_line foreign "$HOOK" >&2
[[ "$PUSH_STATUS" != "foreign" ]] || status_line foreign "$PUSH_HOOK" >&2
[[ "$STATUS" != "foreign" && "$PUSH_STATUS" != "foreign" ]] || exit 2
