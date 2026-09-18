#!/usr/bin/env bash
# active Git pre-commit backstop의 상태를 진단하거나 명시적으로 복구한다.
#
#   bash tools/install_hooks.sh --check   # read-only: current/missing/owned-drift/foreign
#   bash tools/install_hooks.sh --repair  # foreign은 거부, owned drift는 backup 뒤 atomic 교체
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "--check" && "$MODE" != "--repair" ]]; then
  echo "usage: bash tools/install_hooks.sh --check|--repair" >&2
  exit 2
fi
LANG_CODE="${MOTTORI_LANG:-ko}"

status_line() {
  local status="$1" target="$2"
  if [[ "$LANG_CODE" == "en" ]]; then
    echo "$status: $target"
    return
  fi
  case "$status" in
    current) echo "현재(current): $target" ;;
    missing) echo "없음(missing): $target" ;;
    owned-drift) echo "소유 표류(owned-drift): $target" ;;
    foreign) echo "외부 훅(foreign): $target" ;;
  esac
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$ROOT/tools/precommit-hook.sh"
[[ -f "$TEMPLATE" ]] || { echo "template-missing: $TEMPLATE" >&2; exit 2; }

HOOKSPATH="$(git -C "$ROOT" config --get core.hooksPath || true)"
if [[ -n "$HOOKSPATH" ]]; then
  if [[ "$HOOKSPATH" = /* ]]; then
    DIR="$HOOKSPATH"
  else
    DIR="$ROOT/$HOOKSPATH"
  fi
  RESOLVED="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$DIR")"
  case "$RESOLVED" in
    "$ROOT"|"$ROOT"/*) DIR="$RESOLVED" ;;
    *) echo "outside-repo hooksPath: $RESOLVED" >&2; exit 2 ;;
  esac
else
  # linked worktree의 `$GIT_DIR/hooks`는 dispatcher가 읽지 않는 admin 하위다. Git 자신에게
  # common hooks 경로를 묻는다. --path-format은 Git 2.31+ 전용이라 결과를 직접 절대화한다.
  RAW_DIR="$(git -C "$ROOT" rev-parse --git-path hooks)"
  case "$RAW_DIR" in
    /*) DIR="$RAW_DIR" ;;
    *) DIR="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.join(sys.argv[1], sys.argv[2])))' "$ROOT" "$RAW_DIR")" ;;
  esac
fi
HOOK="$DIR/pre-commit"
PUSH_HOOK="$DIR/pre-push"

# Sentinel 도입 직전 canonical 둘만 migration 대상으로 인정한다. 임의 hook에 설명문으로
# "mottori gate"가 들어갔다고 소유권을 주장하면 --repair가 foreign 코드를 덮어쓴다.
# 2026-09-18 실측: v0.4~v0.6으로 배포된 precommit-hook.sh(동일 내용) 해시가 빠져 있어 실제 설치본 전부가
# foreign으로 분류되고 CHANGELOG의 "[해야 함] install_hooks.sh --repair"를 수행할 수 없었다.
LEGACY_HASHES="
a90b84bf06dbc075c3c269b3e61c61ebdf25ea55f4fb8bd268f24fe1acc41c3e
c078fa3e14b9a9152bad2ba4540efac5e3ca19e9d8b7467028e07f80dd022141
28d6734242d51d3b6d63c4b31796864d659c320b85eb48fe803a5d7f807e12ee
89fe10c571d56547e4235da07a777490f31e32fd2b6169d47bd49f5b4cda261e
97c1f2144a63fbc3fb120cce56bd32a14b77948872183b73435a2e985fd951f9
2749f33d184abd3c18069f206e9d3717acc4d56e9f1bee68dce6517298e4e7ee
"
# Tests and migrations may add hashes without editing this file; a hook marked owned only gets
# replaced by our own template, so this cannot make the installer overwrite something with foreign code.
if [[ -n "${MOTTORI_LEGACY_HOOK_HASHES:-}" ]]; then
  LEGACY_HASHES="$LEGACY_HASHES
${MOTTORI_LEGACY_HOOK_HASHES//,/
}"
fi

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
  fi
}

# Ownership stamp: the installer records the sha256 of what it installed. A hook whose hash equals its
# stamp is ours even after the template changed (2026-09-18 twice: a template edit orphaned every
# installed hook as "foreign" and the hook self-check silently blocked all commits). Hand-maintained
# LEGACY_HASHES stays only for installs made before the stamp existed.
STAMP="$DIR/mottori-hooks.stamp"
stamped_hash() {  # stamped_hash <hook-basename>
  [[ -f "$STAMP" ]] && awk -v n="$1" '$1==n {print $2}' "$STAMP" || true
}
classify() {
  local target="$1"
  local name; name="$(basename "$target")"
  if [[ ! -e "$target" ]]; then
    echo "missing"
  elif cmp -s "$TEMPLATE" "$target" && [[ -x "$target" ]]; then
    echo "current"
  elif cmp -s "$TEMPLATE" "$target"; then
    echo "owned-drift"
  elif [[ -n "$(stamped_hash "$name")" && "$(stamped_hash "$name")" == "$(sha256 "$target")" ]]; then
    echo "owned-drift"
  elif grep -Fxq "$(sha256 "$target")" <<< "$LEGACY_HASHES"; then
    echo "owned-drift"
  else
    echo "foreign"
  fi
}

STATUS="$(classify "$HOOK")"
PUSH_STATUS="$(classify "$PUSH_HOOK")"
if [[ "$MODE" == "--check" ]]; then
  if [[ "$STATUS" == "current" && "$PUSH_STATUS" == "current" ]]; then
    if [[ "$LANG_CODE" == "en" ]]; then
      echo "current: $HOOK + $PUSH_HOOK"
    else
      echo "현재(current): $HOOK + $PUSH_HOOK"
    fi
    exit 0
  fi
  status_line "$STATUS" "$HOOK"
  status_line "$PUSH_STATUS" "$PUSH_HOOK"
  if [[ "$STATUS" == "owned-drift" ]]; then
    if [[ "$LANG_CODE" == "en" ]]; then
      echo "template sha256: $(sha256 "$TEMPLATE")"
      echo "installed sha256: $(sha256 "$HOOK")"
    else
      echo "템플릿 sha256: $(sha256 "$TEMPLATE")"
      echo "설치본 sha256: $(sha256 "$HOOK")"
    fi
    diff -u "$HOOK" "$TEMPLATE" | sed -n '1,40p' || true
  fi
  exit 1
fi

if [[ "$STATUS" == "foreign" || "$PUSH_STATUS" == "foreign" ]]; then
  echo "foreign pre-commit/pre-push를 덮어쓰지 않는다: $HOOK ($STATUS), $PUSH_HOOK ($PUSH_STATUS)" >&2
  exit 2
fi

mkdir -p "$DIR"
BACKUP=""
PUSH_BACKUP=""
ROLLBACK_DIR="$(mktemp -d "$DIR/.mottori-hook-rollback.XXXXXX")"
HOOK_EXISTED=0
PUSH_HOOK_EXISTED=0
if [[ -e "$HOOK" || -L "$HOOK" ]]; then
  cp -p "$HOOK" "$ROLLBACK_DIR/pre-commit"
  HOOK_EXISTED=1
fi
if [[ -e "$PUSH_HOOK" || -L "$PUSH_HOOK" ]]; then
  cp -p "$PUSH_HOOK" "$ROLLBACK_DIR/pre-push"
  PUSH_HOOK_EXISTED=1
fi
if [[ "$STATUS" == "owned-drift" ]]; then
  BACKUP="$HOOK.bak.$(date +%Y%m%dT%H%M%S).$$"
  cp -p "$HOOK" "$BACKUP"
fi
if [[ "$PUSH_STATUS" == "owned-drift" ]]; then
  PUSH_BACKUP="$PUSH_HOOK.bak.$(date +%Y%m%dT%H%M%S).$$"
  cp -p "$PUSH_HOOK" "$PUSH_BACKUP"
fi
TMP="$DIR/.pre-commit.$$.tmp"
PUSH_TMP="$DIR/.pre-push.$$.tmp"
cleanup() { rm -f "$TMP" "$PUSH_TMP"; rm -rf "$ROLLBACK_DIR"; }
trap cleanup EXIT
cp "$TEMPLATE" "$TMP"
cp "$TEMPLATE" "$PUSH_TMP"
chmod 755 "$TMP"
chmod 755 "$PUSH_TMP"
mv -f "$TMP" "$HOOK"
mv -f "$PUSH_TMP" "$PUSH_HOOK"

rollback() {
  if [[ "$HOOK_EXISTED" -eq 1 ]]; then
    cp -p "$ROLLBACK_DIR/pre-commit" "$HOOK"
  else
    rm -f "$HOOK"
  fi
  if [[ "$PUSH_HOOK_EXISTED" -eq 1 ]]; then
    cp -p "$ROLLBACK_DIR/pre-push" "$PUSH_HOOK"
  else
    rm -f "$PUSH_HOOK"
  fi
}

if ! cmp -s "$TEMPLATE" "$HOOK" || [[ ! -x "$HOOK" ]] \
   || ! cmp -s "$TEMPLATE" "$PUSH_HOOK" || [[ ! -x "$PUSH_HOOK" ]]; then
  rollback
  echo "repair 검증 실패, 원상 복구: $HOOK" >&2
  exit 1
fi

# setup measures the baseline before hooks. Repair signs that measured set with keyed hash+HMAC
# without running the release regression boundary again.
# Fixtures without a baseline are hook-only tests and intentionally skip this step.
if [[ -f "$ROOT/state/.gate-baseline.json" ]] && ! python3 "$ROOT/tools/gate.py" seal-baseline >/dev/null; then
  rollback
  echo "baseline seal 실패, hook 원상 복구" >&2
  exit 1
fi

NONCE="probe-$$-$(date +%s)"
# Git 2.36보다 오래된 배포판에도 hook dispatcher는 commit 때 executable pre-commit을 실행한다.
# 설치된 파일 자체를 probe하면 신규 `git hook run` 명령 없이 같은 실행 가능성을 검증할 수 있다.
GOT="$("$HOOK" --mottori-probe "$NONCE" 2>&1 || true)"
if [[ "$GOT" != "$NONCE" ]]; then
  rollback
  echo "git dispatcher probe 실패, 원상 복구: $HOOK" >&2
  exit 1
fi

printf 'pre-commit %s\npre-push %s\n' "$(sha256 "$HOOK")" "$(sha256 "$PUSH_HOOK")" > "$STAMP"

if [[ "$LANG_CODE" == "en" ]]; then
  echo "current: $HOOK + $PUSH_HOOK (exact template + executable + direct hook probe + sealed baseline)"
else
  echo "현재(current): $HOOK + $PUSH_HOOK (정확한 템플릿 + 실행 가능 + 직접 훅 검사 + 봉인된 기준선)"
fi
if [[ "$LANG_CODE" == "en" ]]; then
  [[ -z "$BACKUP" ]] || echo "backup: $BACKUP"
  [[ -z "$PUSH_BACKUP" ]] || echo "backup: $PUSH_BACKUP"
else
  [[ -z "$BACKUP" ]] || echo "백업(backup): $BACKUP"
  [[ -z "$PUSH_BACKUP" ]] || echo "백업(backup): $PUSH_BACKUP"
fi
