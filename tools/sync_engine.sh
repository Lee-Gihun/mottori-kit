#!/usr/bin/env bash
# Upgrade the bounded-worker cluster in an existing, quiescent instance.
#   bash tools/sync_engine.sh /path/to/instance
# SYNC_FILES owns the cluster, including runtime and test dependencies. This does not
# update the whole kit, instance configuration, hooks, schedules, or execution authority.
# Reject links, publish files by atomic replacement, verify provenance and existing
# state consumers, and restore the prior cluster if any step fails. No commit is made.
set -euo pipefail
# Inherited repository/config overrides must not redefine source provenance.
for variable in $(compgen -v GIT_); do unset "$variable"; done
export PYTHONDONTWRITEBYTECODE=1
KIT="$(cd "$(dirname "$0")/.." && pwd -P)"
[ "$#" -eq 1 ] || { echo "usage: sync_engine.sh instance path" >&2; exit 2; }
INST="$1"
[ -d "$INST" ] || { echo "instance not found: $INST" >&2; exit 1; }
INST="$(cd "$INST" && pwd -P)"
[ -d "$INST/tools" ] && [ ! -L "$INST/tools" ] || {
  echo "instance tools/ must be a real directory: $INST" >&2; exit 1;
}
[ ! -L "$KIT/tools" ] || { echo "source tools/ is a symlink" >&2; exit 1; }
# Inspect the inventory without importing code before the source link checks.
[ -f "$KIT/tools/fresh_worker.py" ] && [ ! -L "$KIT/tools/fresh_worker.py" ] || {
  echo "source fresh_worker.py must be a regular file" >&2; exit 1;
}
FILES=$(python3 - "$KIT/tools/fresh_worker.py" <<'PYSOURCE'
import ast, sys
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
node = next(n for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "SYNC_FILES" for t in n.targets))
files = ast.literal_eval(node.value)
if not isinstance(files, (tuple, list)) or not files or any(not isinstance(f, str) for f in files):
    sys.exit("invalid SYNC_FILES")
if len(files) != len(set(files)):
    sys.exit("duplicate SYNC_FILES")
print("\n".join(files))
PYSOURCE
)
[ -n "$FILES" ] || { echo "empty SYNC_FILES" >&2; exit 1; }
for f in $FILES; do
  case "$f" in
    *[!A-Za-z0-9._-]*|"") echo "unsafe SYNC_FILES entry: $f" >&2; exit 1 ;;
  esac
  [ -f "$KIT/tools/$f" ] && [ ! -L "$KIT/tools/$f" ] || {
    echo "sync source must be a regular file: $f" >&2; exit 1;
  }
  if [ -e "$INST/tools/$f" ] || [ -L "$INST/tools/$f" ]; then
    [ -f "$INST/tools/$f" ] && [ ! -L "$INST/tools/$f" ] || {
      echo "sync destination must be a regular file: $f" >&2; exit 1;
    }
  fi
done
if [ -e "$KIT/tools/i18n.py" ] || [ -L "$KIT/tools/i18n.py" ]; then
  [ -f "$KIT/tools/i18n.py" ] && [ ! -L "$KIT/tools/i18n.py" ] || {
    echo "source localization must be a regular file" >&2; exit 1;
  }
fi
for f in now.py doctor.py i18n.py; do
  if [ -e "$INST/tools/$f" ] || [ -L "$INST/tools/$f" ]; then
    [ -f "$INST/tools/$f" ] && [ ! -L "$INST/tools/$f" ] || {
      echo "instance consumer must be a regular file: $f" >&2; exit 1;
    }
  fi
done
SRC_SHA=$(cd "$KIT/tools" && MOTTORI_INSTANCE="$KIT" python3 -c "import fresh_worker as f; print(f._source_manifest_sha256())")
STAGE=$(mktemp -d "$INST/tools/.sync-engine.XXXXXX")
MUTATED=0
COMMITTED=0
publish() {
  # os.replace replaces a destination link itself rather than following it.
  python3 - "$1" "$2" <<'PY'
import os, sys
os.replace(sys.argv[1], sys.argv[2])
PY
}
rollback() {
  for f in $FILES; do
    if [ -f "$STAGE/backup/$f" ]; then
      publish "$STAGE/backup/$f" "$INST/tools/$f"
    else
      rm -f "$INST/tools/$f"
    fi
  done
}
cleanup() {
  rc=$?
  if [ "$MUTATED" -eq 1 ] && [ "$COMMITTED" -ne 1 ]; then rollback; fi
  rm -rf "$STAGE"
  return "$rc"
}
trap cleanup EXIT
mkdir "$STAGE/backup" "$STAGE/new"
for f in $FILES; do
  cp -p "$KIT/tools/$f" "$STAGE/new/$f"
  [ ! -f "$INST/tools/$f" ] || cp -p "$INST/tools/$f" "$STAGE/backup/$f"
done
MUTATED=1
for f in $FILES; do publish "$STAGE/new/$f" "$INST/tools/$f"; done
REV=$(git -C "$KIT" rev-parse HEAD)
TOOL_STATUS=$(git -C "$KIT" status --porcelain -- tools)
DIRTY=False
[ -z "$TOOL_STATUS" ] || DIRTY=True
ESHA=$(cd "$INST/tools" && MOTTORI_INSTANCE="$INST" python3 -c "import fresh_worker as f; print(f._engine_sha256())")
python3 - "$INST/tools/fresh_worker.py" "$REV" "$DIRTY" "$ESHA" "$SRC_SHA" <<'PY'
import sys
p, rev, dirty, esha, ssha = sys.argv[1:]
t = open(p, encoding="utf-8").read()
pairs = [("KIT_REV_EMBEDDED = None", f'KIT_REV_EMBEDDED = "{rev}"'),
         ("KIT_SYNC_DIRTY = None", f"KIT_SYNC_DIRTY = {dirty}"),
         ("KIT_SYNC_ENGINE_SHA256 = None", f'KIT_SYNC_ENGINE_SHA256 = "{esha}"'),
         ("KIT_SYNC_SOURCE_SHA256 = None", f'KIT_SYNC_SOURCE_SHA256 = "{ssha}"')]
for old, new in pairs:
    n = t.count(old)
    if n != 1:
        sys.exit(f"stamp placeholder {old!r} occurs {n} times (expected 1); not stamped")
    t = t.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(t)
PY
VERIFY=$(cd "$INST/tools" && MOTTORI_INSTANCE="$INST" MOTTORI_INTERNAL_RUN=1 python3 - "$REV" "$ESHA" "$SRC_SHA" <<'PY'
import contextlib, importlib, io, json, os, sys, tempfile
import fresh_worker as f
import memlib as m
rev, esha, ssha = sys.argv[1:]
i = f._engine_identity()
ok = (i["kit_rev"] == rev and i["kit_rev_source"] == "embedded" and i["kit_sync"]["engine_sha256"] == esha
      and i["kit_sync"]["source_sha256"] == ssha and i["kit_sync"]["matches_copy"] is True
      and f._source_manifest_sha256() == ssha)
if not ok:
    sys.exit("worker provenance mismatch")
if m.CONFIG_ERROR:
    sys.exit("instance configuration is missing or invalid; configuration migration is separate")
# memlib is shared with consumers outside this cluster. Verify their existing interface
# without running every doctor check or changing the instance state.
for name in ("doctor", "now"):
    if not os.path.isfile(name + ".py"):
        continue
    try:
        consumer = importlib.import_module(name)
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            if name == "now":
                # The real hook may refresh snapshots. Keep generated bytes and its lock
                # temporary while reading the instance's existing configuration and inputs.
                with tempfile.TemporaryDirectory(prefix="worker-sync-state-") as scratch:
                    m.NOW_PATH = os.path.join(scratch, "NOW.md")
                    m.PRIVATE_NOW_PATH = os.path.join(scratch, "private-NOW.md")
                    m.lock_path = lambda: os.path.join(scratch, ".journal.lock")
                    if consumer.hook_context() not in (None, 0):
                        raise ValueError("hook_context returned failure")
                payload = json.loads(out.getvalue())
                hook = payload["hookSpecificOutput"]
                if hook["hookEventName"] != "SessionStart" or not isinstance(hook["additionalContext"], str):
                    raise ValueError("invalid SessionStart context")
            else:
                for check in (consumer.c_memlib, consumer.c_config, consumer.c_schema):
                    status, _detail = check()
                    if status != consumer.PASS:
                        raise ValueError("configuration compatibility check did not pass")
    except Exception as exc:
        sys.exit(f"instance {name} compatibility check failed ({type(exc).__name__}); cluster rolled back")
print("ok")
PY
)
[ "$VERIFY" = "ok" ] || { echo "sync verification failed" >&2; exit 1; }
COMMITTED=1
echo "synced worker cluster -> $INST/tools (rev $REV dirty=$DIRTY source=$SRC_SHA engine=$ESHA verified)"
