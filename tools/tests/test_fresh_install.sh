#!/usr/bin/env bash
# Reproduce a noninteractive first install in a temporary clone.
# Check setup, hook installation, linkcheck findings, doctor results, and the worker launcher.
# Full regression suites and installed-instance tests run separately at the release boundary.
# CRITICAL_E2E setup.sh
# CRITICAL_E2E tools/lib/config.py
# CRITICAL_E2E tools/lib/journal.py
# CRITICAL_E2E tools/now.py
# CRITICAL_E2E tools/gate.py
# CRITICAL_E2E tools/linkcheck.py
# CRITICAL_E2E tools/doctor.py
# CRITICAL_E2E tools/fresh_worker.py
# CRITICAL_E2E tools/install_hooks.sh
#
# Usage: bash tools/tests/test_fresh_install.sh [--keep]
# Parser fixtures: --judge-linkcheck|--judge-doctor <subprocess-exit> <output-file>
# Exit zero only when installation, hooks, doctor, linkcheck, and the worker launcher pass.
set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

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
    r"(?: · pending\(before setup\): (0|[1-9][0-9]*))?"
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
cleanup() { [ "$KEEP" -eq 1 ] && echo "kept: $DEST" || rm -rf "$TMP"; }
trap cleanup EXIT

# Prevent the caller's instance override from redirecting the fixture to live state.
unset MOTTORI_INSTANCE CLAUDE_PROJECT_DIR
# Doctor's hook probe can start the Codex app server, which writes state under HOME; keep that in
# the fixture so the caller's home stays untouched and warning counts do not depend on the machine.
mkdir -p "$TMP/home"
export HOME="$TMP/home" CODEX_HOME="$TMP/home/.codex"

fail=0
step() { printf '%-34s %s\n' "$1" "$2"; }

if [ -f "$KIT/system/dev/kit-files.txt" ]; then
  # The kit's own files as they are now, committed once: an installation's documents and data stay
  # out of the fixture (KIT-DR-089).
  python3 "$KIT/tools/tests/testlib.py" kit-repo "$KIT" "$DEST" || { echo "kit copy failed"; exit 1; }
else
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
fi
cd "$DEST"
# Index delivery files so data-exposure checks treat them as the next committed engine.
git add -A >/dev/null 2>&1 || { echo "git add failed"; exit 1; }
step "worktree copy (patch+untracked)" "ok ($(git ls-files | wc -l | tr -d ' ') tracked)"

# The instance files setup.sh creates; the rerun check below requires them to be unchanged.
INSTANCE_FILES=(instance/config.json instance/rules.md instance/decisions.md instance/rituals.md)
instance_missing() { local f; for f in "${INSTANCE_FILES[@]}"; do [ -f "$f" ] || return 0; done; return 1; }
instance_unchanged() { local f; for f in "${INSTANCE_FILES[@]}"; do cmp -s "$f" "$TMP/before/$f" || return 1; done; }

# Run default setup noninteractively, with stdin closed.
out="$(bash setup.sh < /dev/null 2>&1)"; rc=$?
if [ $rc -ne 0 ] || instance_missing || [ ! -d instance/debate ] || [ -n "$(ls -A instance/debate)" ] \
   || [ -n "$(find instance system state -name 'deep-pass-ledger*')$(git ls-files -oi --exclude-standard system)" ] || git status --porcelain --untracked-files=all | grep -q '^??'; then
  step "setup.sh (noninteractive, no args)" "FAIL exit=$rc"
  # Show setup failures from its nested checks.
  echo "$out" | grep -E "^\[ FAIL \]|BROKEN|regression failed|verification failed" | head -8; fail=1
else
  step "setup.sh (noninteractive, no args)" "ok  (instance/ holds its four files and an empty debate/, nothing of the installation in system/, no ledger outside _private/; git status clean)"
fi

# setup.sh installs the hook backstop itself; --check confirms the exact template is in place.
if bash tools/install_hooks.sh --check >/dev/null 2>&1; then
  step "hooks installed by setup" "ok"
else
  step "hooks installed by setup" "FAIL"; fail=1
fi

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
  tail -n 6 "$doctor_err"
  fail=1
fi

# Run the worker launcher end to end with a stub runtime (the same injection test_fresh_worker.py
# uses), so no model or network is involved.
# The launcher only accepts a prompt inside the workspace.
worker_prompt="fresh-install-prompt.md"; worker_stub="$TMP/worker-stub"
printf 'fresh install probe\n' > "$worker_prompt"
cat > "$worker_stub" <<'STUB'
#!/usr/bin/env python3
import pathlib, sys
args = sys.argv[1:]
sys.stdin.read()
pathlib.Path(args[args.index("--output-last-message") + 1]).write_text("STUB_OK\n", encoding="utf-8")
STUB
chmod 755 "$worker_stub"
worker_out="$(MOTTORI_FRESH_WORKER_CODEX_BIN="$worker_stub" python3 tools/fresh_worker.py --runtime codex "$worker_prompt" 2>&1)"; worker_rc=$?
if [ $worker_rc -eq 0 ] && echo "$worker_out" | grep -q "^FRESH_WORKER v1$"; then
  step "fresh_worker (stub runtime)" "ok"
else
  step "fresh_worker (stub runtime)" "FAIL exit=$worker_rc"
  echo "$worker_out" | tail -n 5; fail=1
fi

# A second setup without --force must refuse to overwrite the instance and must
# not rewrite or add a hook file, which a file newer than the marker would show.
mkdir -p "$TMP/before/instance" && cp -p "${INSTANCE_FILES[@]}" "$TMP/before/instance/" 2>/dev/null
touch "$TMP/before/marker"
out2="$(bash setup.sh < /dev/null 2>&1)"; rc2=$?
if [ $rc2 -eq 0 ] && echo "$out2" | grep -Eq "already set up" \
   && instance_unchanged && [ -z "$(find .git/hooks -newer "$TMP/before/marker")" ]; then
  step "setup.sh rerun (no overwrite)" "ok"; else
  step "setup.sh rerun (no overwrite)" "FAIL exit=$rc2"; fail=1; fi

echo
[ $fail -eq 0 ] && echo "fresh install: PASS" || echo "fresh install: FAIL (items above)"
exit $fail
