#!/usr/bin/env bash
# Reproduce a noninteractive first install in a temporary clone.
# Check setup, hook installation, linkcheck findings, and doctor results.
# Full regression suites and installed-instance tests run separately at the release boundary.
# CRITICAL_E2E setup.sh
# CRITICAL_E2E tools/memlib.py
# CRITICAL_E2E tools/now.py
# CRITICAL_E2E tools/gate.py
# CRITICAL_E2E tools/linkcheck.py
# CRITICAL_E2E tools/doctor.py
# CRITICAL_E2E tools/fresh_worker.py
# CRITICAL_E2E tools/install_hooks.sh
#
# Usage: bash tools/test_fresh_install.sh [--keep]
# Parser fixtures: --judge-linkcheck|--judge-doctor <subprocess-exit> <output-file>
# Exit zero only when installation, hooks, doctor, and linkcheck pass.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

judge_linkcheck() {
  python3 - "$1" "$2" <<'PY'
import re
import sys

path, raw_rc = sys.argv[1:]
try:
    subprocess_rc = int(raw_rc)
    text = open(path, encoding="utf-8").read()
except (OSError, UnicodeError, ValueError) as exc:
    print(f"unmeasurable: cannot read linkcheck output or exit code ({exc})")
    raise SystemExit(1)

pattern = re.compile(
    r"\[linkcheck\] broken: (0|[1-9][0-9]*)"
    r"(?: · pending\((?:setup 전|before setup)\): (0|[1-9][0-9]*))?"
)
matches = [match for line in text.splitlines() if (match := pattern.fullmatch(line))]
if len(matches) != 1:
    print(f"unmeasurable: not exactly one linkcheck summary line (found={len(matches)})")
    raise SystemExit(1)
match = matches[0]
if subprocess_rc != 0:
    print(f"unmeasurable: linkcheck exited abnormally (exit={subprocess_rc})")
    raise SystemExit(1)
broken = int(match.group(1))
if broken != 0:
    print(f"unmeasurable: linkcheck exit=0 but broken={broken}")
    raise SystemExit(1)
print(broken)
PY
}

judge_doctor() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

path, raw_rc = sys.argv[1:]

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result

try:
    subprocess_rc = int(raw_rc)
    with open(path, encoding="utf-8") as source:
        payload = json.load(source, object_pairs_hook=unique_object)
    checks = payload["checks"]
    summary = payload["summary"]
    if not isinstance(checks, list) or not isinstance(summary, dict):
        raise ValueError("checks/summary type")
    statuses = ("PASS", "FAIL", "WARN", "SKIP")
    counted = {status: 0 for status in statuses}
    for row in checks:
        if not isinstance(row, dict):
            raise ValueError("check row type")
        if not all(isinstance(row.get(key), str) for key in ("name", "status", "detail")):
            raise ValueError("check row schema")
        if row["status"] not in counted:
            raise ValueError("check status")
        counted[row["status"]] += 1
    fields = ("total", "pass", "fail", "warn", "skip")
    if not all(type(summary.get(key)) is int and summary[key] >= 0 for key in fields):
        raise ValueError("summary schema")
    expected = {
        "total": len(checks),
        "pass": counted["PASS"],
        "fail": counted["FAIL"],
        "warn": counted["WARN"],
        "skip": counted["SKIP"],
    }
    if any(summary[key] != value for key, value in expected.items()):
        raise ValueError("summary/check mismatch")
except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
    print(f"unmeasurable: cannot read the doctor JSON summary ({exc})")
    raise SystemExit(1)

if subprocess_rc != 0:
    print(f"unmeasurable: doctor exited abnormally (exit={subprocess_rc}, FAIL={summary['fail']})")
    raise SystemExit(1)
if summary["fail"] != 0:
    print(f"unmeasurable: doctor exit=0 but FAIL={summary['fail']}")
    raise SystemExit(1)
print(summary["fail"], summary["warn"])
PY
}

case "${1:-}" in
  --judge-linkcheck)
    [ "$#" -eq 3 ] || { echo "usage: $1 <subprocess-exit> <output-file>"; exit 2; }
    judge_linkcheck "$3" "$2"
    exit $?
    ;;
  --judge-doctor)
    [ "$#" -eq 3 ] || { echo "usage: $1 <subprocess-exit> <output-file>"; exit 2; }
    judge_doctor "$3" "$2"
    exit $?
    ;;
esac

KEEP=0; [ "${1:-}" = "--keep" ] && KEEP=1
TMP="$(mktemp -d)"
DEST="$TMP/kit fresh"          # Use a path containing a space to exercise path handling.
MOTTORI_TEST_LOG="$TMP/test-runs.log"
MOTTORI_TEST_RUN_ID="fresh-install-$(date +%s)-$$"
export MOTTORI_TEST_LOG
export MOTTORI_TEST_RUN_ID
: > "$MOTTORI_TEST_LOG"
cleanup() { [ "$KEEP" -eq 1 ] && echo "kept: $DEST" || rm -rf "$TMP"; }
trap cleanup EXIT

# Prevent the caller's instance override from redirecting the fixture to live state.
unset MOTTORI_INSTANCE CLAUDE_PROJECT_DIR

fail=0
step() { printf '%-34s %s\n' "$1" "$2"; }

git clone -q "$KIT" "$DEST" || { echo "clone failed"; exit 1; }
# Overlay the uncommitted delivery tree onto the clone: use a patch for modifications,
# deletions, modes, and symlinks, then copy new untracked files.
( cd "$KIT" && git diff --binary HEAD ) > "$TMP/worktree.patch"
if [ -s "$TMP/worktree.patch" ]; then
  ( cd "$DEST" && git apply "$TMP/worktree.patch" ) || { echo "worktree patch failed to apply"; exit 1; }
fi
( cd "$KIT" && git ls-files -o --exclude-standard -z ) | while IFS= read -r -d '' f; do
  [ -e "$KIT/$f" ] || [ -L "$KIT/$f" ] || continue
  mkdir -p "$DEST/$(dirname "$f")" && cp -Rp "$KIT/$f" "$DEST/$f" || { echo "copy failed: $f"; exit 1; }
done || exit 1
cd "$DEST"
# Index delivery files so data-exposure checks treat them as the next committed engine.
git add -A >/dev/null 2>&1 || { echo "git add failed"; exit 1; }
step "worktree copy (patch+untracked)" "ok ($(git ls-files | wc -l | tr -d ' ') tracked)"

# Run default setup noninteractively, with stdin closed.
out="$(bash setup.sh < /dev/null 2>&1)"; rc=$?
if [ $rc -ne 0 ] || [ ! -f system/memory-config.json ]; then
  step "setup.sh (noninteractive, no args)" "FAIL exit=$rc"
  # Show setup failures from its nested checks (setup.sh may print them in either language).
  echo "$out" | grep -E "^\[ FAIL \]|BROKEN|회귀 실패|검증이 실패" | head -8; fail=1
else
  step "setup.sh (noninteractive, no args)" "ok  (config, instance-rules, decisions, rituals.local created)"
fi

# Install the hook backstop.
bash tools/install_hooks.sh --repair >/dev/null 2>&1 && step "install_hooks --repair" "ok" || { step "install_hooks --repair" "FAIL"; fail=1; }

# Check links.
lc_file="$TMP/linkcheck.out"
python3 tools/linkcheck.py >"$lc_file" 2>&1; lc_rc=$?
lc_judgment="$(judge_linkcheck "$lc_file" "$lc_rc")"; lc_judge_rc=$?
if [ $lc_judge_rc -eq 0 ]; then
  step "linkcheck broken" "$lc_judgment"
else
  step "linkcheck broken" "unmeasurable"
  echo "$lc_judgment"
  grep BROKEN "$lc_file" | head -5
  fail=1
fi

# Read doctor through its JSON contract, not localized display text.
doctor_json="$TMP/doctor.json"; doctor_err="$TMP/doctor.err"
python3 tools/doctor.py --json >"$doctor_json" 2>"$doctor_err"; doctor_rc=$?
metrics="$(judge_doctor "$doctor_json" "$doctor_rc")"; metrics_rc=$?
nf=""; nw=""
[ $metrics_rc -eq 0 ] && read -r nf nw <<< "$metrics"
if [ "${nf:-x}" = "0" ]; then
  step "doctor FAIL / warn" "0 / ${nw:-?}"
else
  step "doctor FAIL / warn" "unmeasurable / ?"
  echo "$metrics"
  tail -6 "$doctor_err"
  fail=1
fi

# A second setup without --force must refuse to overwrite the instance (either language).
out2="$(bash setup.sh < /dev/null 2>&1)"; rc2=$?
if [ $rc2 -eq 0 ] && echo "$out2" | grep -Eq "이미 세팅|already set up"; then step "setup.sh rerun (no overwrite)" "ok"; else
  step "setup.sh rerun (no overwrite)" "FAIL exit=$rc2"; fail=1; fi

echo
[ $fail -eq 0 ] && echo "fresh install: PASS" || echo "fresh install: FAIL (items above)"
exit $fail
