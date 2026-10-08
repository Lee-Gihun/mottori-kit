#!/bin/bash
# Initialize instance configuration, local documents, and state.
# Validate existing journals and merged config before writing.
# Usage: bash setup.sh [--name NAME] [--context work|personal] [--force]
# Without a terminal, use defaults; --force preserves instance-owned settings.

set -euo pipefail
# Use a physical root so symlink aliases resolve consistently with the Python tools.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# Bind all child tools to this checkout instead of inheriting another instance root.
export MOTTORI_INSTANCE="$ROOT"
cd "$ROOT"
say() { python3 "$ROOT/tools/i18n.py" "$@"; }
DOC_LANG="$(python3 -c 'import sys; sys.path.insert(0, "tools"); import i18n; print(i18n.language())')"
DOC_SUFFIX=""
[ "$DOC_LANG" = "ko" ] && DOC_SUFFIX=".ko"

NAME=""; CONTEXT=""; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --name)    [ $# -ge 2 ] || { say setup.name_missing; exit 1; }; NAME="$2"; shift 2 ;;
    --context) [ $# -ge 2 ] || { say setup.context_missing; exit 1; }; CONTEXT="$2"; shift 2 ;;
    --force)   FORCE=1; shift ;;
    *) say setup.unknown_arg "arg=$1"; exit 1 ;;
  esac
done

CFG="system/memory-config.json"
RULES="system/instance-rules.md"

if [ -f "$CFG" ] && [ "$FORCE" -eq 0 ]; then
  say setup.already "path=$CFG"
  say setup.again
  exit 0
fi

# Without a terminal, use visible defaults rather than failing on input EOF.
DEFAULT_NAME="$(basename "$ROOT")"
DEFAULT_CONTEXT="work"
# On --force, preserve the existing instance identity unless explicitly overridden.
if [ -f "$CFG" ]; then
  OLD_NAME="$(python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c.get("instance",{}).get("name",""))' "$CFG" 2>/dev/null || true)"
  OLD_CONTEXT="$(python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c.get("instance",{}).get("context",""))' "$CFG" 2>/dev/null || true)"
  [ -n "$OLD_NAME" ] && DEFAULT_NAME="$OLD_NAME"
  [ -n "$OLD_CONTEXT" ] && DEFAULT_CONTEXT="$OLD_CONTEXT"
fi
if [ -z "$NAME" ]; then
  if [ -t 0 ]; then
    read -r -p "$(say setup.name_prompt "name=$DEFAULT_NAME")" NAME || NAME=""
  else
    say setup.name_default "name=$DEFAULT_NAME"
  fi
  NAME="${NAME:-$DEFAULT_NAME}"
fi
if [ -z "$CONTEXT" ]; then
  if [ -t 0 ]; then
    echo
    say setup.context_intro
    say setup.context_work
    say setup.context_personal
    read -r -p "$(say setup.context_prompt "context=$DEFAULT_CONTEXT")" CONTEXT || CONTEXT=""
  else
    say setup.context_default "context=$DEFAULT_CONTEXT"
  fi
  CONTEXT="${CONTEXT:-$DEFAULT_CONTEXT}"
fi
if [ "$CONTEXT" != "work" ] && [ "$CONTEXT" != "personal" ]; then
  say setup.context_invalid "context=$CONTEXT"; exit 1
fi

# Allow the cloned origin as the engine-update source. Ignore rules and credential restrictions
# own data protection.
ORIGIN="$(git remote get-url origin 2>/dev/null || true)"

python3 - "$NAME" "$CONTEXT" "$ORIGIN" <<'PY'
import datetime, json, os, shutil, sys
name, context, origin = sys.argv[1], sys.argv[2], sys.argv[3]
dst = "system/memory-config.json"
cfg = json.load(open("templates/memory-config.json", encoding="utf-8"))
# Validate the final config with the same schema authority before writing.
sys.path.insert(0, "tools")
import memlib as config_schema
from i18n import t

def legacy_watermark():
    """Migration 전에 존재한 tracked journal의 마지막 사건 시각.

    벽시계 migration 시각을 초 단위로 저장하면 바로 뒤 setup log가 같은 초에 legacy로
    빨려 들어간다. 기존 행 자체의 max timestamp를 경계로 쓰면 old/new 집합이 정확히 갈린다.
    malformed 행이 있으면 경계를 추측하지 않고 migration을 중단한다.
    """
    # Read all existing public and private journal rows with the canonical strict parser,
    # regardless of legacy visibility routing.
    rows = config_schema.parse_journal(
        strict=True, physical_visibilities=("public", "private"))
    latest = None
    for row in rows:
        if row["type"] not in cfg["journal_types"]:
            raise ValueError(
                t("setup.legacy_type", source=row["source"]))
        stamp = datetime.datetime.fromisoformat(row["ts"])
        if stamp.utcoffset() is None:
            raise ValueError(t("setup.legacy_timezone", source=row["source"]))
        latest = stamp if latest is None or stamp > latest else latest
    return latest.isoformat(timespec="seconds") if latest else None


def validate_legacy_threads(data, schema):
    """visibility provenance가 없던 v1~v3 thread의 자동 공개 승격을 거부한다."""
    if schema < 4 and data.get("threads"):
        raise ValueError(t("setup.legacy_threads"))

# Preflight journal syntax and final newlines before backups or writes, including recovery
# installs without config.
import glob as _glob
for _jp in sorted(_glob.glob("state/journal-*.md") + _glob.glob("_private/state/journal-*.md")):
    with open(_jp, "rb") as _f:
        _tail = _f.read()[-1:]
    if _tail and _tail != b"\n":
        raise SystemExit(t("setup.journal_newline", path=_jp))
try:
    config_schema.parse_journal(strict=True, physical_visibilities=("public", "private"))
except Exception as _e:
    raise SystemExit(t("setup.preflight_failed", error=_e))

# Preserve manually configured tracks, threads, and checker inventories on --force.
old = {}
had_old = os.path.exists(dst)
if had_old:
    shutil.copy2(dst, dst + ".bak")
    try:
        old = json.load(open(dst, encoding="utf-8"))
    except Exception as e:
        print(t("setup.config_parse_failed", error=e), file=sys.stderr)
        raise SystemExit(2)
    # Reject invalid config container shapes before merging or overwriting the original.
    config_schema._validate_config_shape(old)
cfg["tracks"]  = old.get("tracks", [])
cfg["threads"] = old.get("threads", [])
if old.get("checks"):
    cfg["checks"] = old["checks"]
if old.get("personal_pointer"):
    cfg["personal_pointer"] = old["personal_pointer"]
if had_old:
    old_schema = old.get("schema_version", 1)
    if isinstance(old_schema, bool) or not isinstance(old_schema, int):
        raise ValueError(t("setup.schema_type"))
    if old_schema > cfg["schema_version"]:
        raise ValueError(t("setup.schema_newer", old=old_schema, new=cfg["schema_version"]))
    validate_legacy_threads(old, old_schema)
    old_vis = old.get("journal_visibility")
    watermark = legacy_watermark()
    if old_schema >= 4:
        # The shared schema validator guarantees the cutover pair, timezone, and track types.
        cfg["journal_visibility"]["public_tracks"] = list(dict.fromkeys(
            old_vis["public_tracks"]))
        cfg["journal_visibility"]["legacy_cutoff"] = old_vis["legacy_cutoff"]
        cfg["journal_visibility"]["legacy_public_tracks"] = list(dict.fromkeys(
            old_vis["legacy_public_tracks"]))
    elif old_schema == 3:
        approved = list(dict.fromkeys(old_vis["public_tracks"]))
        cfg["journal_visibility"]["public_tracks"] = approved
        cfg["journal_visibility"]["legacy_cutoff"] = watermark
        cfg["journal_visibility"]["legacy_public_tracks"] = approved if watermark else []
    else:
        # Old configs lack visibility provenance. Freeze existing tracked events as private and
        # use the live allowlist only for new events.
        cfg["journal_visibility"]["legacy_cutoff"] = watermark
        cfg["journal_visibility"]["legacy_public_tracks"] = []

cfg["instance"]["name"] = name
cfg["instance"]["context"] = context
cfg["instance"]["remote_allowlist"] = [origin] if origin else []
# Validate the fully merged config before writing.
config_schema._validate_config_shape(cfg)
json.dump(cfg, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(t("setup.config_written", path=dst, name=name, context=context))
if had_old:
    print(t("setup.preserved", tracks=len(cfg["tracks"]), threads=len(cfg["threads"]), path=dst))
if origin:
    print(t("setup.origin_registered", origin=origin))
PY

if [ -n "$ORIGIN" ] && [ "$CONTEXT" = "work" ]; then
  say setup.work_remote_warning "origin=$ORIGIN"
fi

if [ ! -f "$RULES" ]; then
  cp "templates/instance-rules${DOC_SUFFIX}.md" "$RULES"
  say setup.rules_created "path=$RULES"
fi
if [ ! -f system/decisions.md ]; then
  cp "templates/decisions${DOC_SUFFIX}.md" system/decisions.md
  say setup.decisions_created
fi
if [ ! -f system/rituals.local.md ]; then
  cp "templates/rituals.local${DOC_SUFFIX}.md" system/rituals.local.md
  say setup.rituals_created
fi

mkdir -p state _private/state
# Copy generic vocabulary into an instance-owned private file for local customization.
if [ ! -f _private/transcribe-prompts.json ] && [ -f templates/transcribe-prompts.json ]; then
  cp templates/transcribe-prompts.json _private/transcribe-prompts.json
fi
python3 tools/now.py log "[system/state] 인스턴스 세팅: $NAME ($CONTEXT) — 킷 클론 후 초기화" >/dev/null
# Create an initial local event so the overlay is present from the first render; record only
# setup state.
python3 tools/now.py log --private "[system/state] local overlay 초기화 — setup ($NAME)" >/dev/null
python3 tools/now.py render >/dev/null
# Create the baseline before linkcheck, then record linkcheck success before doctor inspects its
# evidence.
BASELINE_RC=0
BASELINE_ERR="$(mktemp)"
trap 'rm -f "$BASELINE_ERR"' EXIT
python3 tools/gate.py baseline >/dev/null 2>"$BASELINE_ERR" || BASELINE_RC=$?
[ "$BASELINE_RC" -eq 0 ] || { say setup.baseline_failed "code=$BASELINE_RC"; sed 's/^/     /' "$BASELINE_ERR" | tail -5; }
python3 tools/linkcheck.py >/dev/null 2>&1 || true
say setup.state_written "month=$(date +%Y-%m)"

# Print the remaining guidance, but preserve a failed validation exit status.
echo
say setup.verification
DOCTOR_RC=0
python3 tools/doctor.py || DOCTOR_RC=$?

say setup.remaining
if [ "$DOCTOR_RC" -ne 0 ] || [ "$BASELINE_RC" -ne 0 ]; then
  echo
  say setup.failed "doctor=$DOCTOR_RC" "baseline=$BASELINE_RC"
  exit 1
fi
