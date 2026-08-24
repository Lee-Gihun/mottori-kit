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
cd "$ROOT"

NAME=""; CONTEXT=""; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --name)    NAME="$2"; shift 2 ;;
    --context) CONTEXT="$2"; shift 2 ;;
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
python3 - "$NAME" "$CONTEXT" <<'PY'
import json, sys
name, context = sys.argv[1], sys.argv[2]
cfg = json.load(open("templates/memory-config.json", encoding="utf-8"))
cfg["instance"]["name"] = name
cfg["instance"]["context"] = context
cfg["tracks"] = []          # 트랙은 첫 작업이 생길 때 사람이 추가한다
json.dump(cfg, open("system/memory-config.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print(f"  system/memory-config.json  ({name} / {context})")
PY

# --- 3. 인스턴스 규약 ---
if [ ! -f "$RULES" ]; then
  cp templates/instance-rules.md "$RULES"
  echo "  $RULES  (아직 비어 있다 — 국경 선언을 채워라)"
fi

# --- 4. 상태 초기화 ---
mkdir -p state
python3 tools/now.py log "[system/state] 인스턴스 세팅: $NAME ($CONTEXT) — 킷 클론 후 초기화" >/dev/null
python3 tools/now.py render >/dev/null
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
