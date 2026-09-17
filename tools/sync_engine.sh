#!/usr/bin/env bash
# Copy the engine files from this kit into an instance and stamp the sync identity (KIT-DR-010, review R5/R11).
#   bash tools/sync_engine.sh /path/to/instance
# Stamps KIT_REV_EMBEDDED (kit HEAD), KIT_SYNC_DIRTY (kit tools/ dirty at sync), KIT_SYNC_SOURCE_SHA256
# (manifest of the kit files copied, computed on the kit side), KIT_SYNC_ENGINE_SHA256 (normalized engine
# sha of the destination copy right after sync). Every placeholder must be replaced exactly once and the
# stamped copy is re-imported to verify the values and matches_copy=True; otherwise exit 1.
# Commit is the instance owner's act.
set -euo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INST="${1:?instance path}"
[ -d "$INST/tools" ] || { echo "instance tools/ not found: $INST"; exit 1; }
SRC_SHA=$(cd "$KIT/tools" && MOTTORI_INSTANCE="$KIT" python3 -c "import fresh_worker as f; print(f._source_manifest_sha256())")
# SYNC_FILES is the single inventory authority. The shell must not carry a second copy list.
FILES=$(cd "$KIT/tools" && MOTTORI_INSTANCE="$KIT" python3 -c \
  'import fresh_worker as f; print("\n".join(f.SYNC_FILES))')
[ -n "$FILES" ] || { echo "empty SYNC_FILES" >&2; exit 1; }
STAGE=$(mktemp -d "$INST/tools/.sync-engine.XXXXXX")
MUTATED=0
COMMITTED=0
rollback() {
  for f in $FILES; do
    if [ -f "$STAGE/backup/$f" ]; then
      cp -p "$STAGE/backup/$f" "$INST/tools/$f"
    else
      rm -f "$INST/tools/$f"
    fi
  done
}
cleanup() {
  rc=$?
  if [ "$MUTATED" -eq 1 ] && [ "$COMMITTED" -ne 1 ]; then rollback; fi
  rm -rf "$STAGE"
  return $rc
}
trap cleanup EXIT
mkdir "$STAGE/backup" "$STAGE/new"
for f in $FILES; do
  case "$f" in
    *[!A-Za-z0-9._-]*|"") echo "unsafe SYNC_FILES entry: $f" >&2; exit 1 ;;
  esac
  [ -f "$KIT/tools/$f" ] || { echo "sync source missing: $f" >&2; exit 1; }
  cp -p "$KIT/tools/$f" "$STAGE/new/$f"
  [ ! -f "$INST/tools/$f" ] || cp -p "$INST/tools/$f" "$STAGE/backup/$f"
done
MUTATED=1
for f in $FILES; do cp -p "$STAGE/new/$f" "$INST/tools/$f"; done
REV=$(git -C "$KIT" rev-parse HEAD)
DIRTY=$(git -C "$KIT" status --porcelain -- tools | grep -q . && echo True || echo False)
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
VERIFY=$(cd "$INST/tools" && MOTTORI_INSTANCE="$INST" python3 - "$REV" "$ESHA" "$SRC_SHA" <<'PY'
import sys, fresh_worker as f
rev, esha, ssha = sys.argv[1:]
i = f._engine_identity()
ok = (i["kit_rev"] == rev and i["kit_rev_source"] == "embedded" and i["kit_sync"]["engine_sha256"] == esha
      and i["kit_sync"]["source_sha256"] == ssha and i["kit_sync"]["matches_copy"] is True
      and f._source_manifest_sha256() == ssha)
print("ok" if ok else f"MISMATCH {i}")
PY
)
[ "$VERIFY" = "ok" ] || { echo "sync verification failed: $VERIFY"; exit 1; }
COMMITTED=1
echo "synced $(echo "$FILES" | tr '\n' ' ') -> $INST/tools (rev ${REV:0:8} dirty=$DIRTY source=${SRC_SHA:0:10} engine=${ESHA:0:10} verified)"
