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
# pwd -P: 심볼릭 링크를 푼 물리 경로. macOS의 /var → /private/var 같은 링크 아래에서 논리 경로를
# export하면 memlib ROOT와 도구의 realpath가 달라 doctor가 "ROOT 불일치"를 낸다 (2026-09-17 실측).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
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
# tty가 없으면(에이전트·CI·파이프) 묻지 않고 기본값을 쓴다. 이전 판은 `read`가 EOF를 만나
# set -e로 아무 말 없이 exit 1 했다 (2026-09-17 실측: SETUP.md 지시대로 에이전트가 돌린 첫 경로가
# 바로 이것이라 "5분 설치"가 0분에 죽었다). 기본값은 화면에 남기고 override 방법을 적는다.
DEFAULT_NAME="$(basename "$ROOT")"
DEFAULT_CONTEXT="work"
# --force 재실행이면 기존 config의 정체를 기본값으로 쓴다. 이전 판은 이름·context를 다시 묻고
# 비대화형이면 work로 떨어져, personal 인스턴스가 재실행 한 번에 조용히 work로 바뀔 수 있었다
# (2026-09-17 문서 감사). 정체는 사람이 정한 값이라 기계가 바꾸면 안 된다.
if [ -f "$CFG" ]; then
  OLD_NAME="$(python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c.get("instance",{}).get("name",""))' "$CFG" 2>/dev/null || true)"
  OLD_CONTEXT="$(python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c.get("instance",{}).get("context",""))' "$CFG" 2>/dev/null || true)"
  [ -n "$OLD_NAME" ] && DEFAULT_NAME="$OLD_NAME"
  [ -n "$OLD_CONTEXT" ] && DEFAULT_CONTEXT="$OLD_CONTEXT"
fi
if [ -z "$NAME" ]; then
  if [ -t 0 ]; then
    read -r -p "인스턴스 이름 [$DEFAULT_NAME]: " NAME || NAME=""
  else
    echo "  (tty 없음) 인스턴스 이름 기본값 사용: $DEFAULT_NAME  — 바꾸려면 --name <이름>"
  fi
  NAME="${NAME:-$DEFAULT_NAME}"
fi
if [ -z "$CONTEXT" ]; then
  if [ -t 0 ]; then
    echo
    echo "context는 데이터 국경의 근거값이다."
    echo "  work     회사 머신·회사 자료. 원격 푸시를 doctor가 막는다"
    echo "  personal 개인 머신·개인 자료"
    read -r -p "context [$DEFAULT_CONTEXT]: " CONTEXT || CONTEXT=""
  else
    echo "  (tty 없음) context 기본값 사용: $DEFAULT_CONTEXT  — 개인 머신이면 --context personal"
  fi
  CONTEXT="${CONTEXT:-$DEFAULT_CONTEXT}"
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
    # public·private 둘 다 strict로 읽는다. private가 malformed면 여기서 멈춰야 config·public journal이
    # 먼저 바뀌는 부분 변경이 안 생긴다 (2026-09-17 독립 리뷰 1(b)).
    rows = config_schema.parse_journal(
        strict=True, physical_visibilities=("public", "private"))
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

# 쓰기 전 전면 preflight. 기존 journal(public·private)이 문법에 맞고 마지막 줄이 개행으로 끝나는지
# 먼저 본다. 이전 판은 config 백업·쓰기가 journal 검사보다 앞서, private journal이 손상된 --force에서
# exit 1인데도 config와 public journal이 먼저 바뀌는 부분 변경이 났다 (2026-09-17 독립 리뷰 2회 지적).
# config가 없는 복구 설치에서도 같은 검사를 한다.
import glob as _glob
for _jp in sorted(_glob.glob("state/journal-*.md") + _glob.glob("_private/state/journal-*.md")):
    with open(_jp, "rb") as _f:
        _tail = _f.read()[-1:]
    if _tail and _tail != b"\n":
        raise SystemExit(f"journal 마지막 줄이 개행으로 끝나지 않는다 — 아무것도 안 바꿨다: {_jp}")
try:
    config_schema.parse_journal(strict=True, physical_visibilities=("public", "private"))
except Exception as _e:
    raise SystemExit(f"기존 journal preflight 실패 — 아무것도 안 바꿨다: {_e}")

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
mkdir -p state _private/state
python3 tools/now.py log "[system/state] 인스턴스 세팅: $NAME ($CONTEXT) — 킷 클론 후 초기화" >/dev/null
# local overlay도 첫날부터 실체로 둔다. render는 local 입력이 하나라도 있어야 overlay를 쓰는데,
# AGENTS.md·rituals.md가 `_private/state/NOW.md`를 가리키므로 overlay가 없으면 첫 doctor가
# 깨진 참조 2개를 내고 SessionStart 주입은 local을 unavailable로 보고한다 (2026-09-17 실측).
# 첫 local 사건 한 줄이 그 입력이다. 내용은 setup 사실뿐이라 국경 문제가 없다.
python3 tools/now.py log --private "[system/state] local overlay 초기화 — setup ($NAME)" >/dev/null
python3 tools/now.py render >/dev/null
# 기준선 → linkcheck → doctor 순이다. linkcheck의 통과 기록이 doctor의 "산출물 검사누락" 인증서라
# 안 남기면 HEAD 커밋이 추가한 파일이 미검증 새 파일로 잡히고(2026-09-17 실측: tools/sync_engine.sh),
# 기준선 파일(SETUP.md가 가리킨다)은 linkcheck 전에 있어야 그 참조가 깨진 것으로 안 센다.
BASELINE_RC=0
python3 tools/gate.py baseline >/dev/null 2>/tmp/setup-baseline.err || BASELINE_RC=$?
[ "$BASELINE_RC" -eq 0 ] || { echo "  게이트 기준선 실패 (rc=$BASELINE_RC):"; sed 's/^/     /' /tmp/setup-baseline.err | tail -5; }
python3 tools/linkcheck.py >/dev/null 2>&1 || true
echo "  state/journal-$(date +%Y-%m).md · state/NOW.md · _private/state/NOW.md"

# --- 5. 검증 ---
# 실패를 삼키지 않는다. 이전 판은 doctor FAIL이 떠도 exit 0이라 자동화가 설치 성공으로 오판했다
# (2026-09-17 독립 감사 I). 안내문은 끝까지 인쇄하고 종료코드로 사실을 전한다.
echo
echo "검증:"
DOCTOR_RC=0
python3 tools/doctor.py || DOCTOR_RC=$?

cat <<EOF

다음 둘이 남았다.
  1. system/instance-rules.md 에 국경을 선언해라
  2. CHECKLIST.md 를 열어 사람이 확인할 항목을 처리해라
EOF
if [ "$DOCTOR_RC" -ne 0 ] || [ "$BASELINE_RC" -ne 0 ]; then
  echo
  echo "setup은 끝났지만 검증이 실패했다 (doctor rc=$DOCTOR_RC · baseline rc=$BASELINE_RC). 위 FAIL을 고치고 python3 tools/doctor.py 를 다시 돌려라."
  exit 1
fi
