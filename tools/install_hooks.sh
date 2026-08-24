#!/usr/bin/env bash
# git pre-commit 후방선을 설치한다.
#
# 왜 별도 설치인가: `.git/hooks/`는 clone으로 따라오지 않는다. 클론한 인스턴스는 이걸 한 번
# 돌려야 후방선이 생긴다 (SETUP.md 참조).
#
# 무엇을 막나: Stop 게이트가 못 보는 경로 — Bash 편집, 외부 writer, Codex 편집, 사용자
# interrupt. 커밋되는 index를 검사하고 새 이슈가 있으면 커밋을 막는다.
# `--no-verify`는 여전히 우회다. 계약이 아니라 후방선이다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# **활성 hooksPath를 해석한다** (codex 라운드 4). `core.hooksPath`가 다른 곳을 가리키는데
# `.git/hooks/`에 깔고 "설치됨"이라고 보고하면 후방선이 없는 채로 있다고 착각한다.
HOOKSPATH="$(git -C "$ROOT" config --get core.hooksPath || true)"
if [[ -n "$HOOKSPATH" ]]; then
  [[ "$HOOKSPATH" = /* ]] || HOOKSPATH="$ROOT/$HOOKSPATH"
  case "$(cd "$HOOKSPATH" 2>/dev/null && pwd || echo "$HOOKSPATH")" in
    "$ROOT"/*) DIR="$HOOKSPATH" ;;
    *) echo "core.hooksPath가 리포 밖을 가리킨다: $HOOKSPATH"
       echo "여기에는 설치하지 않는다. 설정을 확인하고 직접 배치해라."
       exit 1 ;;
  esac
else
  GITDIR="$(git -C "$ROOT" rev-parse --git-dir)"
  [[ "$GITDIR" = /* ]] || GITDIR="$ROOT/$GITDIR"
  DIR="$GITDIR/hooks"
fi
HOOK="$DIR/pre-commit"

if [[ -e "$HOOK" ]] && ! grep -q "mottori gate" "$HOOK" 2>/dev/null; then
  echo "이미 다른 pre-commit이 있다: $HOOK"
  echo "덮어쓰지 않는다. 내용을 확인하고 직접 합쳐라."
  exit 1
fi

mkdir -p "$DIR"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# mottori gate — 커밋될 index를 검사한다. tools/install_hooks.sh가 설치했다.
# MOTTORI_INSTANCE를 지우는 이유: 이 변수로 깨끗한 다른 클론을 가리키면 깨진 index가
# 통과했다 (codex 라운드 4 실측). 게이트도 자기 위치와 root가 다르면 거부한다.
unset MOTTORI_INSTANCE
ROOT="$(git rev-parse --show-toplevel)"
exec python3 "$ROOT/tools/gate.py" precommit
EOF
chmod +x "$HOOK"

# **설치했다고 말하기 전에 git이 실제로 이 훅을 부르는지 확인한다.**
if git -C "$ROOT" hook run --ignore-missing pre-commit >/dev/null 2>&1; then
  echo "설치됨: $HOOK  (git이 실제로 호출하는 것을 확인했다)"
else
  # hook run은 훅이 non-zero를 내도 실패한다. 훅 파일 존재 여부로 갈라서 보고한다.
  if [[ -x "$HOOK" ]]; then
    echo "설치됨: $HOOK"
    echo "주의: 확인 실행이 non-zero였다. 지금 index에 이슈가 있거나 기준선이 없을 수 있다."
    echo "      python3 $ROOT/tools/gate.py precommit  으로 직접 확인해라."
  else
    echo "설치 실패: $HOOK 를 만들지 못했다." >&2
    exit 1
  fi
fi
