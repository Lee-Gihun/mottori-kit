#!/usr/bin/env bash
# Initialize instance configuration, local documents, and state.
# Validate existing journals and merged config before writing.
# Usage: bash setup.sh [--name NAME] [--force]
# Without a terminal, use defaults; --force preserves instance-owned settings.
# Starter documents are copied from templates/.

set -euo pipefail
USAGE="usage: bash setup.sh [--name NAME] [--force]"
case "${1:-}" in -h|--help)
  echo "Set up this folder as your instance: configuration, starter documents, state and the Git backstop hooks."
  echo
  echo "$USAGE"
  echo "  --name NAME        the instance's name (default: the folder's name)"
  echo "  --force            run again on a set-up instance, keeping its settings"
  exit 0 ;;
esac
# Use a physical root so symlink aliases resolve consistently with the Python tools.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# Bind all child tools to this checkout instead of inheriting another instance root.
export MOTTORI_INSTANCE="$ROOT"
# An ASCII locale must not turn a non-ASCII instance name into an empty read or a crash.
export PYTHONIOENCODING=utf-8
cd "$ROOT"
# Prerequisites are checked here, so an agent runs this one command instead of a list of them.
command -v python3 >/dev/null 2>&1 || {
  echo "python3 was not found. Install Python 3.9 or later, then run setup again."; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || {
  echo "Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])') is too old: the kit needs 3.9 or later."
  exit 1; }
command -v git >/dev/null 2>&1 || {
  echo "git was not found. Install Git 2.5 or later, then run setup again."; exit 1; }
git --version | python3 -c 'import re, sys
found = re.search(r"(\d+)\.(\d+)", sys.stdin.read())
sys.exit(not (found and (int(found.group(1)), int(found.group(2))) >= (2, 5)))' || {
  echo "$(git --version) is too old: the kit needs Git 2.5 or later."; exit 1; }
# Claude Code also reads a rules file in any folder above this one; setup says so in its summary.
ABOVE=""; DIR="$(dirname "$ROOT")"
while [ -z "$ABOVE" ] && [ "$DIR" != "/" ] && [ -n "$DIR" ]; do
  for RULES_ABOVE in "$DIR/CLAUDE.md" "$DIR/CLAUDE.local.md" "$DIR/.claude/CLAUDE.md"; do
    [ ! -f "$RULES_ABOVE" ] || { ABOVE="$RULES_ABOVE"; break; }
  done
  DIR="$(dirname "$DIR")"
done
# The backstop hooks, the push check and the link check all read Git, so a ZIP download stops here.
# A copy inside another repository stops too: the gate state there belongs to that repository.
TOP="$(git rev-parse --show-toplevel 2>/dev/null)" && TOP="$(cd "$TOP" && pwd -P)" || TOP=""
[ "$TOP" = "$ROOT" ] || {
  echo "This folder is not the top of its own Git repository (a ZIP download has none, and a copy inside another repository would use that one). Get the kit with git clone, or run git init here first, then run bash setup.sh again."
  exit 1
}

NAME=""; FORCE=0; OLD_FLAG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name)    [ $# -ge 2 ] || { echo "--name requires a value"; exit 1; }; NAME="$2"; shift 2 ;;
    # An earlier version asked whether the folder was for work or personal use. Nothing reads the
    # answer now, so the flag is taken and said to be unused, and setup goes on.
    --context) [ $# -ge 2 ] || { echo "--context requires a value"; exit 1; }; OLD_FLAG="--context $2"; shift 2 ;;
    --force)   FORCE=1; shift ;;
    *) echo "unknown argument: $1"; echo "$USAGE"; exit 1 ;;
  esac
done

# Every path setup spells comes from tools/lib/paths.py, where the tools read them too.
PATHS="$(python3 tools/lib/paths.py config instance rules decisions rituals debate now private_now state private_state gate_baseline gate_baseline_prev)"
{ read -r CFG; read -r INSTANCE; read -r RULES; read -r DECISIONS; read -r RITUALS; read -r DEBATE
  read -r NOW_PAGE; read -r PRIVATE_NOW; read -r STATE_DIR; read -r PRIVATE_STATE; read -r GATE_BASELINE
  read -r GATE_BASELINE_PREV; } <<< "$PATHS"

# An installation from before the instance folder still has its files at their old places. Without
# --force setup stops with the line every tool says (config.py get prints it); with --force each
# file moves once, keeping its bytes and mode, unless one is at both places. An installation that
# already has its configuration in the instance folder has nothing to move: a file at one of the
# old places is then the owner's own.
MOVES=""
[ -f "$CFG" ] || MOVES="$(python3 tools/lib/paths.py legacy)"
if [ -n "$MOVES" ]; then
  [ "$FORCE" -eq 1 ] || { python3 tools/lib/config.py get instance.name >/dev/null; exit 1; }
  BOTH="$(printf '%s\n' "$MOVES" | while IFS="$(printf '\t')" read -r OLD NEW; do
    [ ! -e "$NEW" ] || echo "  $OLD and $NEW"; done)"
  if [ -n "$BOTH" ]; then
    printf 'setup stopped: these files are at both places; keep one of each and run bash setup.sh --force again:\n%s\n' "$BOTH"
    exit 1
  fi
  echo "moved to their new places:"
  # The configuration moves last: until it has, a rerun still finds an installation to move.
  { printf '%s\n' "$MOVES" | awk -F'\t' -v c="$CFG" '$2 != c'
    printf '%s\n' "$MOVES" | awk -F'\t' -v c="$CFG" '$2 == c'; } | while IFS="$(printf '\t')" read -r OLD NEW; do
    mkdir -p "$(dirname "$NEW")" && mv "$OLD" "$NEW" && echo "  $OLD -> $NEW"
  done
fi

# .git/hooks is not cloned, so setup installs the pre-commit and pre-push backstop itself. A current
# pair is left untouched, and a hook that is not the kit's is never overwritten: the installer
# installs the free one, and doctor's row names the hook in the way with the two ways forward.
# The installer prints "status<TAB>path<TAB>text" per hook; only the first two fields are read.
# Prints one labelled line, and one line per backup of an older kit hook it replaced.
# The flag an earlier version took changes nothing now; say so once wherever a run ends.
old_flag_note() {
  [ -z "$OLD_FLAG" ] || echo "  $OLD_FLAG is no longer used: the kit does not tell work and personal folders apart"
}

install_backstop() {
  local out rc=0
  if out="$(bash tools/install_hooks.sh --check 2>/dev/null)"; then
    echo "Installed  $(backstop_paths "$out") (already in place; undo: MANUAL.md section 5)"
    return 0
  fi
  out="$(bash tools/install_hooks.sh --repair 2>&1)" || rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "Installed  $(backstop_paths "$out") (undo: MANUAL.md section 5)"
    printf '%s\n' "$out" | sed -n 's/^backup: /Backup     /p'
  elif [ "$rc" -eq 2 ] && printf '%s\n' "$out" | grep -q "^foreign$(printf '\t')"; then
    printf '%s\n' "$out" | python3 -c '
import os, sys
root = sys.argv[1]
done, skipped = [], []
for line in sys.stdin:
    fields = line.rstrip("\n").split("\t")
    if len(fields) < 2:
        continue
    path = os.path.relpath(fields[1], root) if fields[1].startswith(root + os.sep) else fields[1]
    (skipped if fields[0] == "foreign" else done).append(path)
parts = [p + " installed" for p in done] + [p + " skipped (foreign hook left untouched)" for p in skipped]
print("Backstop   " + "; ".join(parts))' "$ROOT"
  else
    echo "Backstop   not installed: $(printf '%s\n' "$out" | tail -n 1). bash tools/install_hooks.sh --check shows the state."
  fi
}

# The hooks the installer named, as "<folder>/pre-commit and pre-push", relative to this folder.
backstop_paths() {
  printf '%s\n' "$1" | python3 -c '
import os, sys
root = sys.argv[1]
paths = [line.rstrip("\n").split("\t")[1] for line in sys.stdin if line.count("\t") >= 1]
shown = [os.path.relpath(p, root) if p.startswith(root + os.sep) else p for p in paths]
folders = {os.path.dirname(p) for p in shown}
if len(folders) == 1 and shown:
    print(shown[0] + "".join(" and " + os.path.basename(p) for p in shown[1:]))
else:
    print(" and ".join(shown))' "$ROOT"
}

if [ -f "$CFG" ] && [ "$FORCE" -eq 0 ]; then
  old_flag_note
  # The config is written first, so an interrupted first run leaves it without the later outputs.
  MISSING=""
  for f in "$RULES" "$NOW_PAGE" "$GATE_BASELINE"; do
    [ -e "$f" ] || MISSING="${MISSING:+$MISSING, }$f"
  done
  if [ -n "$MISSING" ]; then
    echo "setup is not complete: $MISSING missing, so an earlier run stopped part way. Run bash setup.sh --force to finish it; it keeps your settings."
    exit 1
  fi
  echo "already set up: $CFG"
  install_backstop
  echo "Use --force to run again. To inspect status, run python3 tools/doctor.py; optional parts: python3 tools/options.py"
  exit 0
fi

# Setup asks nothing: an agent runs it. The name is the folder's, or the one the instance already
# has, unless --name gives another.
DEFAULT_NAME="$(basename "$ROOT")"
if [ -f "$CFG" ]; then
  OLD_NAME="$(python3 tools/lib/config.py get instance.name 2>/dev/null || true)"
  [ -n "$OLD_NAME" ] && DEFAULT_NAME="$OLD_NAME"
fi
NAME="${NAME:-$DEFAULT_NAME}"
old_flag_note

# What this run creates, for the summary: each output that does not exist yet.
JOURNAL="$(python3 tools/lib/paths.py journal)"
CREATED=""
for f in "$CFG" "$RULES" "$DECISIONS" "$RITUALS" "$JOURNAL" "$NOW_PAGE" "$PRIVATE_NOW"; do
  [ -e "$f" ] || CREATED="${CREATED}${f}"$'\n'
done

# Check every journal before anything is written, then merge and migrate the config from the
# template; tools/lib/config_migrate.py prints what it kept and refuses with one line naming the reason.
JOURNAL_ROWS="$(python3 tools/lib/journal.py rows)"
mkdir -p "$INSTANCE"
MIGRATED="$(printf '%s' "$JOURNAL_ROWS" | python3 tools/lib/config_migrate.py "$NAME")"

# Each instance document starts as the template of the same name; an existing one is kept.
copy_template() {
  [ -f "$1" ] || cp "templates/$(basename "$1")" "$1"
}
copy_template "$RULES"
copy_template "$DECISIONS"
copy_template "$RITUALS"
mkdir -p "$DEBATE"
# The owner's projects get one folder with its guide; the kit tracks nothing in it (KIT-DR-093).
PROJECTS_README="$(python3 tools/lib/paths.py projects_readme)"
if [ ! -f "$PROJECTS_README" ]; then
  mkdir -p "$(dirname "$PROJECTS_README")"
  cp templates/projects-README.md "$PROJECTS_README"
  CREATED="${CREATED}${PROJECTS_README}"$'\n'
elif ! grep -q '^<!-- projects:start -->$' "$PROJECTS_README"; then
  # A guide of the owner's own: it is left as it is, and the map is drawn only where they put the markers.
  echo "note: $PROJECTS_README is yours and has no map markers; python3 tools/projects.py draw adds them at its end."
fi

mkdir -p "$STATE_DIR" "$PRIVATE_STATE"
# Log the setup events on the first install only: each rerun would add rows.
PUBLIC_ROWS="$(python3 tools/lib/journal.py count public)"
if [ "$PUBLIC_ROWS" -eq 0 ]; then
  # tools/now.py validates and routes the rows.
  python3 tools/now.py log "[system/state] instance set up: $NAME, initialized after cloning the kit" >/dev/null
  # Create an initial local event so the overlay is present from the first render; record only
  # setup state.
  python3 tools/now.py log --private "[system/state] local overlay initialized by setup ($NAME)" >/dev/null
fi
python3 tools/now.py render >/dev/null
# Create the baseline before linkcheck, then record linkcheck success before doctor inspects its
# evidence. An existing baseline is left alone: saving again would silently adopt today's issues
# and clear a block another session is waiting on (python3 tools/gate.py baseline does that on
# purpose).
BASELINE_RC=0
BASELINE_LINES=""
if [ ! -e "$GATE_BASELINE" ]; then
  # A template keeps the file under TMPDIR; plain mktemp on macOS uses the per-user temporary folder.
  BASELINE_ERR="$(mktemp "${TMPDIR:-/tmp}/setup-baseline.XXXXXX")"
  trap 'rm -f "$BASELINE_ERR"' EXIT
  # The first save creates state/.gate-baseline.json, which SETUP.md links to, so the baseline that
  # save records would still list those links as broken; record it again with the file in place.
  python3 tools/gate.py baseline >/dev/null 2>&1 || true
  python3 tools/gate.py baseline >/dev/null 2>"$BASELINE_ERR" || BASELINE_RC=$?
  # A fresh install has no earlier baseline to restore, so the copy of the throwaway save goes.
  rm -f "$GATE_BASELINE_PREV"
  [ "$BASELINE_RC" -eq 0 ] || BASELINE_LINES="$(printf 'gate baseline failed (exit %s):\n' "$BASELINE_RC"; sed 's/^/  /' "$BASELINE_ERR" | tail -n 5)"
fi
python3 tools/linkcheck.py >/dev/null 2>&1 || true
BACKSTOP="$(install_backstop)"

# doctor prints its short form; the number of failures comes from the row it records in the run
# log (tools/lib/runlog.py), so nothing here reads the sentences it prints.
DOCTOR_RC=0
DOCTOR_OUT="$(python3 tools/doctor.py)" || DOCTOR_RC=$?
FAILURES="$(python3 -c 'import sys; sys.path.insert(0, "tools/lib"); import runlog
rows = [r for r in runlog.rows() if len(r) >= 4 and r[1] == "doctor"]
fields = dict(f.split("=", 1) for f in (rows[-1][3].split() if rows else []) if "=" in f)
print(fields.get("fail", "?"))')"
[ "$FAILURES" = "1" ] && REPORTED="1 failure" || REPORTED="$FAILURES failures"

# The summary: what was set up, what was created and installed, doctor, what is left.
if [ "$DOCTOR_RC" -ne 0 ]; then
  echo "Setup incomplete for \"$NAME\" in $ROOT: doctor reported $REPORTED."
elif [ "$BASELINE_RC" -ne 0 ]; then
  echo "Setup incomplete for \"$NAME\" in $ROOT: the gate baseline failed."
else
  echo "Set up \"$NAME\" in $ROOT."
fi
echo
# Instance files, four to a line, then the state files.
python3 -c '
import sys
created = [f for f in sys.argv[1].split("\n") if f]
inst = [f for f in created if f.startswith("instance/")]
groups = [inst[i:i + 4] for i in range(0, len(inst), 4)] + [[f for f in created if f not in inst]]
lines = [", ".join(g) for g in groups if g]
for i, line in enumerate(lines):
    print(("Created    " if i == 0 else "           ") + line)' "$CREATED"
# config_migrate's first line names the config; the lines after it say what a rerun kept.
printf '%s\n' "$MIGRATED" | tail -n +2 | sed 's/^ */           /'
printf '%s\n' "$BACKSTOP"
[ -z "$ABOVE" ] || echo "Note: Claude Code also reads $ABOVE, in a folder above this one, so its agent would follow both sets of rules. Moving this folder elsewhere avoids that."
[ -z "$BASELINE_LINES" ] || { echo; printf '%s\n' "$BASELINE_LINES"; }
echo
printf '%s\n' "$DOCTOR_OUT"
echo
if [ "$DOCTOR_RC" -ne 0 ] || [ "$BASELINE_RC" -ne 0 ]; then
  if [ "$DOCTOR_RC" -ne 0 ]; then
    echo "Fix the $REPORTED above and run \`python3 tools/doctor.py\` again (exit 0 required)."
    echo "Do not trust state automation or hooks until doctor reports 0 failures."
  else
    echo "Fix the baseline problem above, run \`python3 tools/gate.py baseline\`, then \`python3 tools/doctor.py\`."
  fi
  echo "After doctor passes: complete system/CHECKLIST.md; $RULES can stay as the template until outside material comes in."
  exit 1
fi
echo "Next"
echo "  Tell your agent something you have decided. It is written down and given back at every session start."
echo "  A folder of notes you already have: move it into projects/ whole, then run python3 tools/adopt.py projects/FOLDER."
if command -v codex >/dev/null 2>&1 || command -v agy >/dev/null 2>&1; then
  echo "  Codex or Antigravity: the first time you start one here, approve the kit's hooks (SETUP.md section 3)."
fi
echo "  system/CHECKLIST.md lists what only a person can check: a backup of this folder and, on a company machine, your IT policy."
# What the private folder is for, said once here: the agent suggests it and the owner decides.
echo "  $(dirname "$PRIVATE_STATE")/ is for what must stay out of Git and out of what the agent writes for other people."
echo "  Your agent suggests it when something looks like that; you decide."

# Optional parts: one line with how many are off. Nothing is asked; the list by meaning is turned on only
# when its local server already answers with the model (KIT-DR-094).
echo
python3 tools/options.py setup || true
