#!/bin/bash
# setup — 엔진에 인스턴스 정체를 부여한다.
#
# 하는 일 넷. 전부 되돌릴 수 있다 (만든 파일을 지우면 원상복구).
#   1. templates/memory-config.json -> system/memory-config.json  (이름·context 치환)
#   2. templates/instance-rules.md  -> system/instance-rules.md
#   3. state/ 준비 + 첫 journal 엔트리
#   4. 첫 NOW 렌더
#
# 사용:  bash setup.sh                              (대화형)
#        bash setup.sh --name <이름> --context work|personal
#        bash setup.sh --force                      (기존 설정 덮어쓰기)

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# setup은 자기 checkout을 초기화하는 명령이다. 부모 shell의 인스턴스 override를 물려받으면
# 아래 memlib import와 now/gate가 다른 repo의 state를 읽거나 쓸 수 있으므로 자체 ROOT로 고정한다.
export MOTTORI_INSTANCE="$ROOT"
cd "$ROOT"

NAME=""; CONTEXT=""; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --name)    [ $# -ge 2 ] || { echo "--name 뒤에 값이 없다"; exit 1; }; NAME="$2"; shift 2 ;;
    --context) [ $# -ge 2 ] || { echo "--context 뒤에 값이 없다"; exit 1; }; CONTEXT="$2"; shift 2 ;;
    --force)   FORCE=1; shift ;;
    *) echo "모르는 인자: $1"; exit 1 ;;
  esac
done

CFG="system/memory-config.json"
RULES="system/instance-rules.md"

if [ -f "$CFG" ] && [ "$FORCE" -eq 0 ]; then
  echo "이미 세팅돼 있다: $CFG"
  echo "다시 하려면 --force. 상태를 확인하려면 python3 tools/doctor.py"
  exit 0
fi

# --- 1. 인스턴스 정체 ---
if [ -z "$NAME" ]; then
  DEFAULT_NAME="$(basename "$ROOT")"
  read -r -p "인스턴스 이름 [$DEFAULT_NAME]: " NAME
  NAME="${NAME:-$DEFAULT_NAME}"
fi
if [ -z "$CONTEXT" ]; then
  echo
  echo "context는 데이터 국경의 근거값이다."
  echo "  work     회사 머신·회사 자료. 원격 푸시를 doctor가 막는다"
  echo "  personal 개인 머신·개인 자료"
  read -r -p "context [work]: " CONTEXT
  CONTEXT="${CONTEXT:-work}"
fi
if [ "$CONTEXT" != "work" ] && [ "$CONTEXT" != "personal" ]; then
  echo "context는 work 또는 personal이어야 한다 (받은 값: $CONTEXT)"; exit 1
fi

# --- 2. config 생성 ---
# 클론해 온 origin은 킷 리포다. 엔진 업데이트를 받는 정상 경로이므로 allowlist에 넣는다.
# 넣지 않으면 doctor가 매번 FAIL을 내고, 늑대소년이 된 검사는 아무도 안 본다.
# **데이터 차단은 이 allowlist가 아니라 .gitignore와 pull-only 자격증명이 한다** (DR-002).
ORIGIN="$(git remote get-url origin 2>/dev/null || true)"

python3 - "$NAME" "$CONTEXT" "$ORIGIN" <<'PY'
import datetime, json, os, shutil, sys
name, context, origin = sys.argv[1], sys.argv[2], sys.argv[3]
dst = "system/memory-config.json"
cfg = json.load(open("templates/memory-config.json", encoding="utf-8"))
# fresh clone에서도 최종 merged config를 쓰기 전에 같은 schema authority로 검증한다.
sys.path.insert(0, "tools")
import memlib as config_schema

def legacy_watermark():
    """Migration 전에 존재한 tracked journal의 마지막 사건 시각.

    벽시계 migration 시각을 초 단위로 저장하면 바로 뒤 setup log가 같은 초에 legacy로
    빨려 들어간다. 기존 행 자체의 max timestamp를 경계로 쓰면 old/new 집합이 정확히 갈린다.
    malformed 행이 있으면 경계를 추측하지 않고 migration을 중단한다.
    """
    # journal grammar/type/body 검증과 물리 파일 탐색은 스키마 정본의 public parser가 맡는다.
    # visibility=None이라 legacy routing 결과와 무관하게 기존 tracked 행 전부를 받는다.
    rows = config_schema.parse_journal(
        strict=True, physical_visibilities=("public",))
    latest = None
    for row in rows:
        if row["type"] not in cfg["journal_types"]:
            raise ValueError(
                f"legacy journal type가 새 schema에 없음: {row['source']}")
        stamp = datetime.datetime.fromisoformat(row["ts"])
        if stamp.utcoffset() is None:
            raise ValueError(f"legacy journal timezone 누락: {row['source']}")
        latest = stamp if latest is None or stamp > latest else latest
    return latest.isoformat(timespec="seconds") if latest else None


def validate_legacy_threads(data, schema):
    """visibility provenance가 없던 v1~v3 thread의 자동 공개 승격을 거부한다."""
    if schema < 4 and data.get("threads"):
        raise ValueError(
            "legacy threads[]는 public 판정 증거가 없음; public/local 수동 분리 후 재실행 필요")

# --force 재실행이 손으로 등록한 트랙·스레드·검사목록을 지우면 안 된다
# (2026-08-24 적대 검증: 이전 판은 tracks=[]로 초기화해 조용히 날렸다).
old = {}
had_old = os.path.exists(dst)
if had_old:
    shutil.copy2(dst, dst + ".bak")
    try:
        old = json.load(open(dst, encoding="utf-8"))
    except Exception as e:
        print(f"     기존 config 파싱 실패, 원본을 덮지 않는다: {e}", file=sys.stderr)
        raise SystemExit(2)
    # JSON 문법만 맞고 known container가 잘못된 config도 보존 로직 전에 거부한다. 이 검증을
    # write 뒤의 now.py에 미루면 실패했는데도 merged config가 원본을 덮는다.
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
        raise ValueError("기존 schema_version이 int가 아님")
    if old_schema > cfg["schema_version"]:
        raise ValueError(
            f"기존 config v{old_schema}가 이 엔진 v{cfg['schema_version']}보다 새롭다")
    validate_legacy_threads(old, old_schema)
    old_vis = old.get("journal_visibility")
    watermark = legacy_watermark()
    if old_schema >= 4:
        # 위의 memlib config shape 검증이 v4 cutover 쌍·timezone·track type을 보증한다.
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
        # v1/v2에는 과거 visibility 판정의 증거가 없다. 추측해서 공개하지 않고 기존 tracked
        # journal 전부를 legacy-private로 동결한다. 새 사건은 template의 live allowlist를 쓴다.
        cfg["journal_visibility"]["legacy_cutoff"] = watermark
        cfg["journal_visibility"]["legacy_public_tracks"] = []

cfg["instance"]["name"] = name
cfg["instance"]["context"] = context
cfg["instance"]["remote_allowlist"] = [origin] if origin else []
# old 조각을 합친 최종 config도 쓰기 전에 같은 스키마 정본으로 검증한다.
config_schema._validate_config_shape(cfg)
json.dump(cfg, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"  {dst}  ({name} / {context})")
if had_old:
    print(f"     보존: 트랙 {len(cfg['tracks'])}개 · 스레드 {len(cfg['threads'])}개 · 백업 {dst}.bak")
if origin:
    print(f"     origin 자동 등록: {origin}")
PY

if [ -n "$ORIGIN" ] && [ "$CONTEXT" = "work" ]; then
  cat <<EOF

  주의: 이 인스턴스는 work인데 원격이 붙어 있다.
    $ORIGIN
  .gitignore가 state/·_private/·config를 추적하지 않으므로 데이터는 이 원격으로 못 간다.
  다만 **엔진 코드는 밀 수 있다.** 회사에서 고친 코드가 개인 저장소로 나가면 안 된다면
  pull-only 자격증명으로 다시 클론하거나 원격을 지워라 (CHECKLIST.md B).
EOF
fi

# --- 3. 인스턴스 소유 문서 (업스트림 파일과 쌍을 이룬다) ---
if [ ! -f "$RULES" ]; then
  cp templates/instance-rules.md "$RULES"
  echo "  $RULES  (아직 비어 있다 — 국경 선언을 채워라)"
fi
if [ ! -f system/decisions.md ]; then
  cp templates/decisions.md system/decisions.md
  echo "  system/decisions.md  (인스턴스 DR. 킷 설계 DR은 system/kit-decisions.md)"
fi
if [ ! -f system/rituals.local.md ]; then
  cp templates/rituals.local.md system/rituals.local.md
  echo "  system/rituals.local.md  (rituals.md의 확장점. 빈 채로 시작)"
fi

# --- 4. 상태 초기화 ---
mkdir -p state
python3 tools/now.py log "[system/state] 인스턴스 세팅: $NAME ($CONTEXT) — 킷 클론 후 초기화" >/dev/null
python3 tools/now.py render >/dev/null
python3 tools/gate.py baseline >/dev/null 2>&1 || true
echo "  state/journal-$(date +%Y-%m).md · state/NOW.md"

# --- 5. 검증 ---
echo
echo "검증:"
python3 tools/doctor.py || true

cat <<EOF

다음 둘이 남았다.
  1. system/instance-rules.md 에 국경을 선언해라
  2. CHECKLIST.md 를 열어 사람이 확인할 항목을 처리해라
EOF
