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
GITDIR="$(git -C "$ROOT" rev-parse --git-dir)"
[[ "$GITDIR" = /* ]] || GITDIR="$ROOT/$GITDIR"
HOOK="$GITDIR/hooks/pre-commit"

if [[ -e "$HOOK" ]] && ! grep -q "mottori gate" "$HOOK" 2>/dev/null; then
  echo "이미 다른 pre-commit이 있다: $HOOK"
  echo "덮어쓰지 않는다. 내용을 확인하고 직접 합쳐라."
  exit 1
fi

mkdir -p "$(dirname "$HOOK")"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# mottori gate — 커밋될 index를 검사한다. tools/install_hooks.sh가 설치했다.
ROOT="$(git rev-parse --show-toplevel)"
exec python3 "$ROOT/tools/gate.py" precommit
EOF
chmod +x "$HOOK"
echo "설치됨: $HOOK"
echo "시험:   python3 $ROOT/tools/gate.py precommit"
