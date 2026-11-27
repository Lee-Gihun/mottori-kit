#!/bin/sh
# Launcher for every runtime hook. Two forms:
#   sh tools/hook.sh event EVENT RUNTIME   what a runtime declares: tools/dispatch.py runs the kit's steps
#   sh tools/hook.sh TOOL [ARGS...]         one tool called directly
#
# The root comes from this file's own location and MOTTORI_INSTANCE is dropped, so a hook of one
# instance never reads another instance's state through an inherited variable. Stderr goes to
# state/.hook-errors.log only when that log can be written; otherwise it stays on the inherited
# stderr, so a missing or read-only state folder never stops the tool from running. A failure
# leaves one timestamped line in the log, which is what doctor and the session notice count.
#
# The event form always exits 0 with a whole answer. The dispatcher's output is held until it
# exits: if it fails or passes its time limit, what it printed is dropped and the runtime's
# fallback answer goes out instead. MOTTORI_DISABLE_HOOKS=1 gives the empty answer before Python
# starts. The direct form returns the tool's exit status unchanged.
case "${1:-}" in -h|--help)
  echo "The launcher every runtime hook runs; a runtime starts it, a person does not need to."
  echo
  echo "usage: sh tools/hook.sh event EVENT RUNTIME < payload"
  echo "       sh tools/hook.sh TOOL [ARGS...]"
  echo "  event EVENT RUNTIME  run the kit's steps for one hook event (tools/dispatch.py)"
  echo "  TOOL [ARGS...]       run one tool under tools/ directly"
  exit 0 ;;
esac
root=$(cd "$(dirname "$0")/.." && pwd) || exit 1
unset MOTTORI_INSTANCE
log="$root/state/.hook-errors.log"
if [ -f "$log" ] && [ -w "$log" ]; then
  sink=$log
elif [ ! -e "$log" ] && [ -d "$root/state" ] && [ -w "$root/state" ]; then
  sink=$log
else
  sink=
fi

if [ "$1" = event ]; then
  event=$2
  runtime=$3
  # The empty answer: no output for Claude Code and Codex; Antigravity reads JSON after every exit 0.
  empty=
  [ "$runtime" = agy ] && empty='{}'
  if [ "${MOTTORI_DISABLE_HOOKS:-}" = 1 ]; then
    [ -n "$empty" ] && printf '%s\n' "$empty"
    exit 0
  fi
  [ -n "$sink" ] && exec 2>>"$sink"
  # Each limit sits under the timeout declared for the event and above its steps' budgets.
  case $event in
    SessionStart) limit=25 ;;
    Stop) limit=185 ;;
    PreCompact) limit=15 ;;
    *) limit=10 ;;
  esac
  # A background job's stdin is /dev/null unless given explicitly, so the payload goes via fd 3.
  exec 3<&0
  answer=$(
    python3 "$root/tools/dispatch.py" "$event" "$runtime" <&3 &
    pid=$!
    (
      trap 'kill "$nap" 2>/dev/null; exit 0' TERM
      sleep "$limit" & nap=$!
      wait "$nap" && kill -9 "$pid" 2>/dev/null
    ) >/dev/null 2>&1 </dev/null &
    dog=$!
    wait "$pid"
    rc=$?
    kill "$dog" 2>/dev/null
    exit "$rc"
  )
  rc=$?
  if [ "$rc" -eq 0 ]; then
    [ -n "$answer" ] && printf '%s\n' "$answer"
    exit 0
  fi
  [ -n "$sink" ] && printf '%s hook failed (event %s %s, rc=%s)\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S')" "$event" "$runtime" "$rc" >&2
  # The text is written out here: no Python runs on this failure path.
  failed='[kit] State injection failed (now.py is missing or errored). Run `python3 tools/doctor.py`; until fixed, read state/NOW.md together with _private/state/NOW.md when it exists. A missing local overlay means unavailable, not no state.'
  case "$runtime:$event" in
    claude:SessionStart|codex:SessionStart)
      printf '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "%s"}}\n' "$failed"
      ;;
    agy:SessionStart)
      printf '{"injectSteps": [{"systemMessage": {"systemMessage": "%s"}}]}\n' "$failed"
      ;;
    *)
      [ -n "$empty" ] && printf '%s\n' "$empty"
      ;;
  esac
  exit 0
fi

tool=$1
shift
name="tools/$tool"
[ $# -gt 0 ] && name="$name $*"
if [ -n "$sink" ]; then
  python3 "$root/tools/$tool" "$@" 2>>"$sink"
else
  python3 "$root/tools/$tool" "$@"
fi
rc=$?
if [ "$rc" -ne 0 ] && [ -n "$sink" ]; then
  printf '%s hook failed (%s, rc=%s)\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$name" "$rc" \
    >>"$sink" 2>/dev/null
fi
exit "$rc"
