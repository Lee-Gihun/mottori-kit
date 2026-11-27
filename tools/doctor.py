#!/usr/bin/env python3
"""Check installation, configuration, hooks, and recorded verification.

Report unmeasured capabilities separately from automated checks. Hook declarations and successful commands do not prove delivery to a model.

Usage: python3 tools/doctor.py [--all] [--json] [--no-runtimes]
Without --all only the rows that need attention are printed. Exit 1 when any check fails, 2 on an
unknown argument."""
import argparse
import collections
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
# The tools many rows need. A tool only one row needs is imported inside that row, so if it is
# broken that row fails and the others still run.
import config as C  # noqa: E402
import dispatch  # noqa: E402
import enforce  # noqa: E402
import hookdiag  # noqa: E402
import journal as J  # noqa: E402
import paths as P  # noqa: E402
import runlog  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
ABSOLUTE_PATH = (
    "absolute path hard-coded; it will silently fail on another machine:\n      {items}"
)
AGENTS_MISMATCH = (
    "not a single authority (CLAUDE {claude} / AGENTS {agents} bytes); change CLAUDE.md to "
    "exact @AGENTS.md import"
)
AGY_UNARMED = (
    "\n      Needs your one-time step: start `agy` in {root} once and answer \"Yes, I trust "
    "this folder\". Until then an interactive Antigravity session runs none of the kit's hooks"
)
AGY_UNLISTED = (
    "\n      Antigravity lists no kit hook for: {events}. Check .agents/hooks.json (row hooks · "
    "agy wiring)"
)
AUTHORITY_MISSING = (
    "SessionStart failure fallback does not say to read public NOW together with the local "
    "overlay: {items}"
)
CHECK_CRASHED = "check crashed: {error_type}: {error}"
CODEX_MISSING = (
    "codex CLI missing; Codex sessions and the dispatcher (ask_codex.sh) are unavailable"
)
CODEX_UNARMED = (
    "\n      Needs your one-time step: start `codex` in {root} once, trust the folder, then "
    "choose \"Trust all\" on the hooks review (once per checkout path; CHECKLIST C). Until "
    "then Codex runs none of the kit's hooks"
)
CONFIG_INVALID = (
    C.CONFIG_NAME + " cannot be loaded; fix it before trusting the other rows: {detail}"
)
CONTEXT_OVER = (
    "fixed context {bytes} bytes (~{tokens} tokens); over warning line: {items}. Details: "
    "python3 tools/context_budget.py"
)
ENGINE_MODIFIED = (
    "locally modified engine files; the next pull may conflict or revert them:\n      {items}"
)
GIT_MISSING = (
    "git not found on PATH; install Git 2.5 or later, or add it to PATH. The rows that need "
    "Git are skipped until then"
)
GIT_OLD = "{root} · {version}; below 2.5: `rev-parse --git-path` is unavailable. Upgrade git"
GLOBAL_MISSING = (
    "global settings missing; current-time injection is disabled for each turn: see MANUAL.md "
    "section 1 (the global time hook)"
)
GROWTH_DISK_LOW = (
    "{value} left on this disk, below {limit}. The other items of this check show what in the "
    "workspace is growing"
)
GROWTH_GIT_OVER = (
    ".git holds {value}, over {limit}. Look at git count-objects -vH and git for-each-ref"
)
GROWTH_TMP_OVER = "tmp/ has {value} untouched for over {days} days, over {limit}. Largest: {items}"
GROWTH_WORK_OVER = (
    "job folders with no top-level page starting with README, STATE, HANDOFF, DOSSIER, or "
    "INDEX: {value}, over {limit}. Examples: {items}. Such a page says what the job is, its "
    "status, and what may be deleted"
)
HOOKSPATH_OUTSIDE = (
    "{detail} · or keep that core.hooksPath and have your own hooks run `python3 tools/gate.py "
    "precommit` (pre-commit) and `python3 tools/enforce.py prepush \"$@\"` (pre-push)"
)
HOOKS_DISABLED = (
    " · MOTTORI_DISABLE_HOOKS=1 is set here, so every Claude Code event hook of the kit gives "
    "an empty answer in this environment"
)
HOOKS_LIST_FAILED = "hooks/list unavailable: {error_type}: {error}"
HOOK_ERRORS_NONE = "no hook failure in state/.hook-errors.log in the last {days} days"
HOOK_ERRORS_RECENT = (
    "{count} hook failure line(s) in state/.hook-errors.log in the last {days} days; last: "
    "{last}"
)
HOOK_ERRORS_SHOWN = (
    "{count} hook failure line(s) in the last {days} days were already shown at session start; "
    "last: {last}"
)
HOOK_ERRORS_OVERRAN = (
    "{count} optional hook step(s) ran past their budget in the last {days} days, not announced "
    "at session start; last: {last}"
)
# AGENTS rule 2 sends the agent here for the one step that arms the hooks again.
CAPABILITY_MISSING = (
    "required capability missing: {items}. The kit's hook lines for this file are in Git: `git "
    "diff {path}` shows what changed, and `git checkout -- {path}` puts the kit's file back"
)
HOOK_FILE_MISSING = (
    "{path} missing; hooks are not installed for this runtime. It is a tracked file: restore "
    "it with `git checkout -- {path}`"
)
KIT_DIVERGED = (
    "{different} of {shared} shared tools diverged: {items}\n      use `python3 "
    "tools/kit_sync.py` to inspect differences and `--apply` to export"
)
MANUAL_CODEX_HOW = (
    "After one dispatch, verify that the response follows the rules (a person sends, commits "
    "and pushes; the answer is in the first two sentences)."
)
MANUAL_SESSION_HOW = (
    "A normal doctor run only checks that the hooks are declared and that their commands run. "
    "It does not start a model session. To check that a new session really receives the state, "
    "run (this spends model calls)\n       {command}\n     It passes when, in {runtimes}, a "
    "session sees the state with hooks on and does not see it with hooks off."
)
MORE = "\n      ... {count} more"
NOT_GIT = "not a git repository; linkcheck cannot count tracked files"
PERSON_LEDGER_COUNTS = (
    "last {date} · decision-relevant items not yet moved to the ledger {count} (threshold "
    "{threshold})"
)
PRECOMMIT_NOT_OWN_REPO = (
    "this folder is not the top of its own git repository, so no backstop hooks belong here. "
    "After git init here, run `bash tools/install_hooks.sh --repair`"
)
PRECOMPACT_JOURNAL_NONE = (
    "no journal has a '{marker}' line yet. Normal before the first compaction; after one, the "
    "PreCompact hook did not fire"
)
PRECOMPACT_MARKER = "[system/state] compaction occurred"
PRECOMPACT_MULTIPLE = (
    "{runtime} has {count} PreCompact commands and none is the kit's event line; the effect "
    "cannot be asserted"
)
PRE_SETUP_FAILURE = (
    "setup has not run (config missing), so the hook command was not run. Check again after "
    "`bash setup.sh`"
)
PRIVATE_SYMLINKS = (
    "tracked links into _private: {count}; their target path strings will reach the remote "
    "(contents will not; only structure and filenames):\n      {items}{more}"
)
RECEIPTS_DETAIL = (
    "last 7 days runs={runs} · tokens={usage} (usage from {measured} runs) · "
    "failures={failures} ({rate}%) · still marked running={running}"
)
REPAIR_NEEDED = "{detail} · run `bash tools/install_hooks.sh --repair`"
LINKS_OK_LISTED = (
    "no broken references in the files Git lists; your own folders are read at the end of a turn "
    "that edits them"
)
PUSH_HOOK_NOT_OURS = "another tool's pre-push hook is installed, so the kit does not check pushes here · {detail}"
RETENTION_SHORT = (
    "Claude Code terminal sessions keep transcripts {days} days (30 by default), so recall "
    "cannot find older conversations; the setting is cleanupPeriodDays"
)
ROOT_LABEL = "root"
RUNTIME_TRANSCRIPTS_MISSING = (
    "installed, but no transcript of it in recall's sources: {runtimes} ({counts}). If it has "
    "been used, add its source to episodic_sources in " + C.CONFIG_NAME + " (defaults: "
    "tools/lib/config.py)"
)
SCHEMA_NEWER = (
    "config schema v{config} > engine v{engine}; an old engine may ignore new privacy fields. "
    "Update the engine first"
)
SCHEMA_OLD = "config schema v{config} < engine expects v{engine}: {todo}"
SETTINGS_SHAPE = (
    "{path} has an unexpected shape; expected an object whose hooks map each event to a list "
    "of blocks, each with a hooks list"
)
SKILLS_STALE = "skill copies differ from {source}: {items}; run `{fix}`"
TIME_HOOK_MISSING = (
    "time injection hook missing; the model does not know 'today'. See MANUAL.md section 1 "
    "(the global time hook)"
)
TIME_PROJECT_ONLY = (
    "this folder's .claude/settings.json injects the current time; ~/.claude/settings.json has "
    "no time hook, so other folders do not get it: see MANUAL.md section 1 (the global time "
    "hook)"
)
TRAILER_MISSING = "{tool} trailer missing/not last: {last!r}"
TRANSCRIPTS_MISSING = (
    "missing: {path}\n      If no Claude Code session has run in this folder yet (a new "
    "install, or an instance used only through Codex or the command line), this is normal: "
    "check again after the first Claude Code session. If sessions did run here, the "
    "folder-name rule does not match this path: compare it with the folder names under "
    "~/.claude/projects and report the mismatch as an engine bug"
)
UNVERIFIED_SINCE = (
    "the current files are not covered by a link check record or a turn-end gate pass (last "
    "turn-end run: {last}). `python3 tools/linkcheck.py` records this state; link results are "
    "in the link check row. An old or missing turn-end run may mean the Stop hook is not "
    "firing in the runtime you use"
)


HOOK_NOT_DECLARED = "not declared"
HOOK_NOT_LISTED = "not in the runtime's hook list"
# Status words of install_hooks.sh --check, whose lines are a word, a tab, the hook's path, and
# optionally a tab and words for a person. current and chained hooks are in place; --repair
# installs a missing or owned-drift one; a foreign one is left to its owner.
HOOK_IN_PLACE = ("current", "chained")
HOOK_FREE = ("missing", "owned-drift")


ROOT = os.path.dirname(HERE)
# Set from the command line in __main__; a test that imports doctor gets the plain run.
JSON_OUTPUT = NO_RUNTIMES = ALL_OUTPUT = False
# The row a runtime-starting check shows under --no-runtimes.
RUNTIME_LEFT_OUT = "not run: --no-runtimes leaves out the rows that start a runtime program"

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
results = []


class SettingsShapeError(ValueError):
    """A hook file that is valid JSON of the wrong shape: its rows name the file, not a crash."""


def check(check_id, fn, needs_git=False):
    """Run one row and record (status, id, detail). A row that returns None does not apply to this
    instance and is not listed."""
    try:
        # One Git row names the repair; the rows that call Git would otherwise each crash.
        if needs_git and not shutil.which("git"):
            outcome = SKIP, f"needs Git; see the {LABELS['runtime_git']} row"
        else:
            outcome = fn()
    except SettingsShapeError as e:
        outcome = FAIL, str(e)
    except Exception as e:
        outcome = FAIL, CHECK_CRASHED.format(error_type=type(e).__name__, error=e)
    if outcome is None:
        return
    results.append((outcome[0], check_id, outcome[1]))


def status_of(check_id):
    """The status a check recorded earlier in this run, or None when it has not run."""
    return next((status for status, done, _ in results if done == check_id), None)


def sh(*cmd, cwd=ROOT):
    # Internal checks must not create explicit-run evidence.
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    # A tracked name that is not UTF-8 must not crash the row that prints it.
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", cwd=cwd, env=env)


def _hook_summary(report, runtime=None, absent=HOOK_NOT_DECLARED):
    """One phrase per kit event, event=declared/command/armed, then the canary's evidence."""
    parts = []
    for event, row in report.items():
        if not row["declared"]:
            # "no/invalid" read as a broken command; an absent event has no command to judge.
            parts.append(f"{event}={absent}")
            continue
        command = "valid" if row.get("command_valid") else "invalid"
        extra = "/matcher-unreachable" if row.get("matcher_reachable") is False else ""
        parts.append(f"{event}=yes/{command}/{row.get('armed', 'unknown')}{extra}")
    evidence = _canary(runtime)[1] if runtime else CANARY_UNKNOWN
    return " · ".join(parts) + " · " + evidence


def c_python():
    v = sys.version_info
    ok = v >= (3, 9)
    return (PASS if ok else FAIL), f"python {v.major}.{v.minor}.{v.micro}" + ("" if ok else (
        " (3.9+ required)"
    ))


# An optional runtime that is not installed is not applicable: a warning would ask a user who
# does not want that feature to install it. The detail names what it would enable.
def c_node():
    p = shutil.which("node")
    if p:
        return PASS, os.path.realpath(p)
    scripts = sorted(name for name in os.listdir(TOOLS) if name.endswith(".js"))
    return SKIP, "node missing; " + (f"only {', '.join(scripts)} cannot run" if scripts else "no tool here needs it")


def c_codex():
    p = shutil.which("codex")
    return (PASS, p) if p else (SKIP, CODEX_MISSING)


def c_claude():
    p = shutil.which("claude")
    return (PASS, p) if p else (SKIP, (
        "claude CLI missing; headless verification (claude -p) unavailable"
    ))


def c_git():
    if not shutil.which("git"):
        return FAIL, GIT_MISSING
    r = sh("git", "rev-parse", "--show-toplevel")
    if r.returncode:
        return WARN, NOT_GIT
    v = sh("git", "--version").stdout.strip()
    m = re.search(r"(\d+)\.(\d+)", v)
    if not m:
        return WARN, f"{r.stdout.strip()} · could not read git version ({v!r}); verify that it is 2.5+"
    if (int(m.group(1)), int(m.group(2))) < (2, 5):
        return FAIL, GIT_OLD.format(root=r.stdout.strip(), version=v)
    return PASS, r.stdout.strip() + f" · {v}"


def c_instance_root():
    # Resolve symlinks before comparing roots; /var and /private/var may name the same directory.
    if os.path.realpath(P.instance_root()) != os.path.realpath(ROOT):
        return FAIL, f"ROOT mismatch: instance root={P.instance_root()} vs tool location={ROOT}"
    return PASS, f"ROOT={P.instance_root()}"


def c_config():
    legacy = C.legacy_layout()
    if legacy:
        return FAIL, legacy
    if not os.path.exists(P.config_file()):
        return FAIL, f"missing: {P.config_file()}; run `bash setup.sh` or copy from templates/"
    if C.error() == "invalid":
        return FAIL, CONFIG_INVALID.format(detail=C.error_detail())
    if b"CHANGEME" in open(P.config_file(), "rb").read():
        return FAIL, "CHANGEME remains; the instance name/tracks have not been filled in"
    # Having no track is a valid configuration, so alone it is a note on a passing row.
    notes = [w for w in C.warnings() if w[0] == "doctor.config_warn_tracks"]
    problems = [w for w in C.warnings() if w not in notes]
    if problems:
        return WARN, " · ".join(C.warning_text(w) for w in C.warnings())
    summary = f"tracks {len(C.tracks())} · threads {len(C.threads())} · sources {len(C.episodic_sources())}"
    return PASS, " · ".join([summary] + [C.warning_text(w) for w in notes])


def c_transcripts():
    """Check the derived transcript directory.

    Absence never fails. Before any Claude Code session there is nothing to find, so the row is
    not applicable. Once a turn-end record exists and the folder is still missing, the row warns:
    the folder-name rule may not match, or the turn ends ran in Codex or Antigravity, which the
    message names as normal.
    """
    if not os.path.isdir(P.transcripts()):
        status = WARN if _last_turn_end_run() else SKIP
        return status, TRANSCRIPTS_MISSING.format(path=P.transcripts())
    n = len([f for f in os.listdir(P.transcripts()) if f.endswith(".jsonl")])
    # An empty folder with no turn end on record is a folder nobody has worked in yet.
    return (PASS if n else WARN if _last_turn_end_run() else SKIP), f"{P.transcripts()} · sessions {n}"


def _runtime_sessions():
    """Return {runtime: transcripts in recall's sources} for Codex and Antigravity where the
    program is installed. Zero means the runtime has not been used in this folder, or its store
    is somewhere the sources do not name."""
    import glob
    found = {}
    for name, program in (("codex", "codex"), ("agy", "agy")):
        if shutil.which(program):
            found[name] = sum(len(glob.glob(os.path.join(base, one), recursive=True))
                              for source, _kind, base, pat in C.episodic_sources() if source == name
                              for one in (pat, pat + ".zst"))
    return found


def _sessions_here():
    """Return {runtime: sessions of this folder that recall can read}, empty when recall fails.
    The stores hold every folder's sessions, so only recall's own listing says which are this one's."""
    listed = sh(sys.executable, "tools/recall.py", "sessions", "--all")
    if listed.returncode:
        return {}
    return collections.Counter(re.findall(r"^\[([^\]\s]+) *\] ", listed.stdout, re.M))


def c_runtime_transcripts():
    """Say when Codex or Antigravity is installed and recall's sources hold none of its
    transcripts: the store moved, the config leaves the source out, or it was never used. The
    last is by far the most common and needs nothing, so the row does not warn; --all shows it.
    Claude Code's store has its own row."""
    found = _runtime_sessions()
    if not found:
        return SKIP, "neither codex nor agy is installed"
    counts = ", ".join(f"{name} {n}" for name, n in found.items())
    missing = [name for name, n in found.items() if not n]
    if missing:
        return SKIP, RUNTIME_TRANSCRIPTS_MISSING.format(runtimes=", ".join(missing), counts=counts)
    # The stores are per machine, so these are every folder's sessions, not this folder's.
    return PASS, "transcript files recall can read on this machine: " + counts


def c_state():
    if not os.path.isdir(P.state()):
        return FAIL, f"missing: {P.state()}"
    if not os.access(P.state(), os.W_OK):
        return FAIL, f"not writable: {P.state()}"
    j = P.journal_file()
    errors = []
    entries = J.parse_journal(errors=errors)
    if errors:
        return FAIL, f"journal damage {len(errors)}; first item: {errors[0]}"
    state = "present" if os.path.exists(j) else (
        "absent (created on first log)"
    )
    return PASS, f"journal {state} · entries {len(entries)}"


def c_now():
    if not os.path.exists(P.now_page()):
        return WARN, "NOW.md missing; create it with `python3 tools/now.py render`"
    size = os.path.getsize(P.now_page())
    return ((PASS, f"{size} UTF-8 bytes (limit {C.threshold('now_max_bytes')})") if size <= C.threshold("now_max_bytes") else
            (FAIL, f"{size} bytes > limit {C.threshold('now_max_bytes')}; render/budget contract violated"))


def _hook_file(runtime):
    return "/".join(hookdiag.HOOK_FILES[runtime])


def _hook_cmds(runtime="claude"):
    """Return {event: [command]} of a runtime's declaration file, or None when it has none."""
    cfg = hookdiag.read(runtime, ROOT)
    return None if cfg is None else _commands(runtime, cfg)


def _commands(runtime, cfg):
    """Return {event: [command]} of a parsed declaration file; a wrong shape names the file."""
    out = {}
    try:
        for event, handlers in hookdiag.declared(runtime, cfg).items():
            for h in handlers:
                # Rows hand commands to string and path functions, so a non-string is a shape error.
                if not isinstance(h["command"], str):
                    raise TypeError(h["command"])
                out.setdefault(event, []).append(h["command"])
    except (AttributeError, TypeError, KeyError):
        raise SettingsShapeError(SETTINGS_SHAPE.format(path=_hook_file(runtime))) from None
    return out


def _wiring(runtime):
    """Judge one runtime's declaration file: the kit's events and the kit's own lines in it.

    Only the file is read; trust, firing and model effect are other rows' claims. A line that
    is not the kit's event line is the owner's own and is not judged (SETUP invites such lines).
    """
    cfg = hookdiag.read(runtime, ROOT)
    if cfg is None:
        return WARN, HOOK_FILE_MISSING.format(path=_hook_file(runtime))
    cmds = _commands(runtime, cfg)
    report = hookdiag.static_report(runtime, cfg)
    # Without these a session gets no state and a compaction goes unrecorded; Antigravity has no
    # compaction event, so its list leaves PreCompact out.
    essential = [e for e in ("SessionStart", "PreCompact") if e in report and not report[e]["declared"]]
    if essential:
        return FAIL, CAPABILITY_MISSING.format(items=", ".join(essential), path=_hook_file(runtime))
    invalid = [event for event, row in report.items()
               if row["declared"] and not row["command_valid"]]
    if invalid:
        return FAIL, "declared but command invalid: {items}".format(items=", ".join(invalid))
    hard = [f"{e}: {c}" for e, cs in cmds.items() for c in cs
            if _event_line([c], runtime, e) and re.search(r"/(Users|home)/[^/]+/", c)]
    if hard:
        return FAIL, ABSOLUTE_PATH.format(items="\n      ".join(hard))
    startup = cmds.get("SessionStart", [])
    authority_markers = ("state/NOW.md", "_private/state/NOW.md", "unavailable")
    # The event form keeps its fallback in the launcher, where the failure row runs it, so
    # an owner's own SessionStart lines beside it need not repeat the contract.
    launcher = _event_line(startup, runtime) is not None
    missing_authority = [] if launcher else [
        x for x in authority_markers if x not in "\n".join(startup)]
    if missing_authority:
        return FAIL, AUTHORITY_MISSING.format(items=", ".join(missing_authority))
    detail = _hook_summary(report, runtime) + " · command path=relative"
    missing_gate = [e for e, row in report.items() if not row["declared"]]
    if missing_gate:
        return WARN, detail + " · gate hooks missing: {items}".format(items=", ".join(missing_gate))
    return PASS, detail


def c_skills():
    """Each skill's copies in the runtimes' folders match its source in system/skills."""
    import skills
    found = skills.differences(ROOT)
    if found:
        return WARN, SKILLS_STALE.format(source=skills.SOURCE, items=", ".join(f"{kind} {path}" for kind, path in found),
                                         fix=skills.FIX)
    names = skills.sources(ROOT)
    return PASS, f"{len(names)} skills, copies match" if names else "no skills"


def c_hook_wiring():
    status, detail = _wiring("claude")
    if os.environ.get("MOTTORI_DISABLE_HOOKS") == "1":
        return (WARN if status == PASS else status), detail + HOOKS_DISABLED
    return status, detail


def c_hook_wiring_codex():
    return _wiring("codex")


def c_hook_wiring_agy():
    return _wiring("agy")


def c_hook_codex_armed():
    """Read enabled, trustStatus, and currentHash through the official hooks/list API."""
    if NO_RUNTIMES:
        return SKIP, RUNTIME_LEFT_OUT
    try:
        entry = hookdiag.codex_hooks_list(ROOT)
        report = hookdiag.codex_runtime_report(entry.get("hooks", []))
    except FileNotFoundError as e:
        hookdiag.save_arming(ROOT, "codex", None)
        return SKIP, str(e)
    except Exception as e:
        return WARN, HOOKS_LIST_FAILED.format(error_type=type(e).__name__, error=e)
    required = [event for event, row in report.items() if not row["armed"]]
    # The approval matters once Codex is used here; before that it is a step for later.
    used = bool(required) and bool(_sessions_here().get("codex"))
    # Session start names an unarmed runtime from this verdict, so it never probes. A runtime
    # never used in this folder gets no verdict, and so no line at session start.
    hookdiag.save_arming(ROOT, "codex", None if required and not used else not required)
    # Here "declared" means Codex's hooks/list reported the hook, not that the file declares it.
    detail = _hook_summary(report, "codex", absent=HOOK_NOT_LISTED)
    invalid = [event for event, row in report.items()
               if row["declared"] and not row["command_valid"]]
    if invalid:
        return FAIL, detail + " · command invalid: " + ", ".join(invalid)
    if entry.get("errors"):
        return FAIL, detail + f" · loader errors={entry['errors']}"
    if required:
        # Untrusted but valid wiring needs a manual first runtime launch; report a warning with that action.
        return WARN if used else SKIP, (detail + " · unarmed: " + ", ".join(required)
                        + CODEX_UNARMED.format(root=os.path.realpath(ROOT)))
    return PASS, detail


def c_hook_agy_armed():
    """Antigravity's /hooks listing in print mode proves the hooks are loaded; print mode skips
    folder trust, so the trusted folder list decides whether an interactive session runs them."""
    if NO_RUNTIMES:
        return SKIP, RUNTIME_LEFT_OUT
    try:
        hooks = hookdiag.agy_hooks_list(ROOT)
    except FileNotFoundError as e:
        hookdiag.save_arming(ROOT, "agy", None)
        return SKIP, str(e)
    except Exception as e:
        return WARN, HOOKS_LIST_FAILED.format(error_type=type(e).__name__, error=e)
    trusted = hookdiag.agy_trusted(ROOT)
    report = hookdiag.agy_runtime_report(hooks, ROOT, trusted)
    detail = _hook_summary(report, absent=HOOK_NOT_LISTED)
    unlisted = [event for event, row in report.items() if not row["declared"]]
    armed = trusted and not unlisted
    used = not armed and bool(_sessions_here().get("agy"))
    hookdiag.save_arming(ROOT, "agy", None if not armed and not used else armed)
    if unlisted:
        return WARN if used else SKIP, detail + AGY_UNLISTED.format(events=", ".join(unlisted))
    if not trusted:
        return WARN if used else SKIP, detail + AGY_UNARMED.format(root=os.path.realpath(ROOT))
    return PASS, detail


def _event_line(commands, runtime, event="SessionStart"):
    """The kit's event line for this event and runtime, or None. Only that line carries the
    kit's contract, and an owner's own line may stand before it in any order."""
    for command in commands:
        match = dispatch.EVENT_LINE.search(command)
        if match and match.groups() == (event, runtime):
            return command
    return None


def _configured():
    """Before setup the hook command would fail and append an untimestamped line to the
    instance's own state/.hook-errors.log, so the probes do not run it then."""
    return os.path.exists(P.config_file())


SESSION_PROBE_SECONDS = 30


def _probe_session(command, cwd, label, env=None):
    """Run one SessionStart command the way a runtime does and return (context, problem).

    A minimal event goes to stdin, so a command that waits for its event does not hang; the
    process group is killed at the time limit, since a shell's children keep its pipes open.
    MOTTORI_INTERNAL_RUN tells the state step not to advance the seen cursor or trim logs, so a
    probe never hides a failure from the next real session. Only exit 0, the SessionStart event
    name and a non-blank context pass; problem is None then.
    """
    import signal
    env = dict(os.environ if env is None else env, MOTTORI_INTERNAL_RUN="1")
    env.pop("MOTTORI_INSTANCE", None)
    # The probe measures the hooks themselves; the wiring row reports the switch.
    env.pop("MOTTORI_DISABLE_HOOKS", None)
    event = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "cwd": cwd})
    proc = subprocess.Popen(["bash", "-c", command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd, env=env, start_new_session=True)
    try:
        stdout, _ = proc.communicate(event.encode("utf-8"), timeout=SESSION_PROBE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return None, f"no answer within {SESSION_PROBE_SECONDS} s at {label}; the hook was stopped"
    stdout = stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        return None, f"exit {proc.returncode} at {label}; hooks must always exit 0"
    try:
        output = json.loads(stdout)["hookSpecificOutput"]
        name, ctx = output.get("hookEventName"), output.get("additionalContext")
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, f"invalid JSON at {label}: {stdout[:80]!r}"
    if name != "SessionStart":
        return None, f"hookEventName is {name!r} at {label}, not SessionStart"
    if not isinstance(ctx, str) or not ctx.strip():
        return None, f"blank additionalContext at {label}"
    return ctx, None


def c_hook_codex_run():
    """Execute the declared Codex hook command directly. This checks root resolution, including from subdirectories, but not dispatcher firing, trust, or model effect."""
    cmds = _hook_cmds("codex") or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return SKIP, "Codex hook missing"
    if not _configured():
        return (SKIP, "see the config row") if C.legacy_layout() else (WARN, PRE_SETUP_FAILURE)
    command = _event_line(cs, "codex") or cs[0]
    sub = os.path.join(ROOT, "system") if os.path.isdir(os.path.join(ROOT, "system")) else ROOT
    # The launcher's fallback answer starts with "[kit]"; a context without it is the state.
    fell_back, sizes = False, {}
    for label, cwd in ((ROOT_LABEL, ROOT), ("subdirectory", sub)):
        ctx, problem = _probe_session(command, cwd, label)
        if problem:
            return FAIL, problem
        fell_back = fell_back or ctx.startswith("[kit]")
        sizes[label] = "failure branch" if ctx.startswith("[kit]") else f"{len(ctx)} character(s)"
    if fell_back:
        return FAIL, f"injection failed inside the instance: {sizes}"
    # Outside any checkout the line finds no launcher and fails, which Codex only logs; state
    # injected there would come from a root the session does not belong to.
    ctx, _ = _probe_session(command, tempfile.gettempdir(), "outside repo")
    if ctx and not ctx.startswith("[kit]"):
        return WARN, (
            "injected outside the repo; git-root fallback may select the wrong location"
        )
    status, evidence = _canary("codex")
    return status, "command checked only · root/subdirectory JSON OK · " + evidence


def c_hook_success():
    """Execute the declared SessionStart command and validate its success-path JSON."""
    cmds = _hook_cmds() or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return FAIL, "SessionStart hook missing"
    if not _configured():
        return (SKIP, "see the config row") if C.legacy_layout() else (WARN, PRE_SETUP_FAILURE)
    command = _event_line(cs, "claude") or cs[0]
    ctx, problem = _probe_session(command, ROOT, ROOT_LABEL,
                                  env=dict(os.environ, CLAUDE_PROJECT_DIR=ROOT))
    if problem:
        return FAIL, problem
    if ctx.startswith("[kit]"):
        # The hook's stderr went to its log, so rerun now.py itself to show why it failed.
        rerun = sh(sys.executable, "tools/now.py", "hook-context")
        tail = (rerun.stderr.strip().splitlines() or [""])[-1][:160]
        stderr = f" · stderr: {tail}" if tail else ""
        return FAIL, f"entered failure branch; now.py does not run{stderr}"
    status, evidence = _canary("claude")
    return status, f"command-valid only · {len(ctx.encode('utf-8'))} UTF-8 bytes · {evidence}"


def c_hook_failure():
    """Require valid JSON on the hook failure path as well."""
    cmds = _hook_cmds() or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return SKIP, ""
    # The launcher alone, without the tools it starts: what a session gets when they fail.
    with tempfile.TemporaryDirectory(prefix="doctor-hook-failure-") as project:
        os.makedirs(os.path.join(project, "tools"))
        if os.path.isfile(os.path.join(ROOT, "tools", "hook.sh")):
            shutil.copy2(os.path.join(ROOT, "tools", "hook.sh"), os.path.join(project, "tools"))
        command = _event_line(cs, "claude") or cs[0]
        ctx, problem = _probe_session(command, project, "failure branch",
                                      env=dict(os.environ, CLAUDE_PROJECT_DIR=project))
    if problem:
        return FAIL, problem
    missing = [x for x in ("state/NOW.md", "_private/state/NOW.md", "unavailable") if x not in ctx]
    if missing:
        return FAIL, "failure branch authority guidance missing: {items}".format(items=", ".join(missing))
    return (PASS if "[kit]" in ctx else WARN), "warning is injected into the model on failure"


HOOK_ERRORS_DAYS = 7


def c_hook_errors():
    """Report recent lines in the hook error log; lines not yet shown at session start warn.

    Only the kit's SessionStart hook is executed here; the other hooks have side effects, so
    their failures are read from the log they append to instead of being reproduced. The session
    start notice advances a byte cursor past what it showed. That cursor records display, not
    repair, so the failures before it are history: listed, never a warning. The notice never
    shows an optional step that ran past its budget, so those lines are counted on their own and
    warn wherever the cursor stands.
    """
    try:
        data = open(P.hook_errors(ROOT), "rb").read()
    except FileNotFoundError:
        return PASS, HOOK_ERRORS_NONE.format(days=HOOK_ERRORS_DAYS)
    try:
        seen = int(open(P.hook_errors_seen(ROOT), encoding="utf-8").read().strip())
    except (OSError, ValueError):
        seen = 0
    # As in the session notice, a cursor past the end means the log shrank and restarts.
    if not 0 <= seen <= len(data):
        seen = 0
    cutoff = (datetime.date.today() - datetime.timedelta(days=HOOK_ERRORS_DAYS)).isoformat()

    def recent(part):
        return [line for line in runlog.hook_error_entries(part.decode("utf-8", "replace"))
                if line[:10] >= cutoff]
    overran = [line for line in recent(data) if runlog.overran(line)]
    shown, unseen = ([line for line in recent(part) if not runlog.overran(line)]
                     for part in (data[:seen], data[seen:]))
    parts = []
    for lines, message in ((unseen, HOOK_ERRORS_RECENT), (overran, HOOK_ERRORS_OVERRAN),
                           (shown, HOOK_ERRORS_SHOWN)):
        if lines:
            parts.append(message.format(count=len(lines), days=HOOK_ERRORS_DAYS, last=lines[-1][:160]))
    if not parts:
        return PASS, HOOK_ERRORS_NONE.format(days=HOOK_ERRORS_DAYS)
    return (WARN if unseen or overran else PASS), " · ".join(parts)


CANARY_MAX_AGE_DAYS = 30
CANARY_UNKNOWN = "live firing not tested"


def _canary(runtime):
    """Return (status, phrase) from the last model-backed canary result, without running a model.

    A working command alone cannot prove delivery to a model, so status is WARN when that canary
    failed, did not verify, or is older than CANARY_MAX_AGE_DAYS. No result keeps PASS, since the
    canary is opt-in, and so does one that cannot be read, which the phrase names, unless the row
    itself still records a failure.
    """
    status, phrase, _proven = _canary_record(runtime)
    return status, phrase


def _canary_record(runtime):
    """Return (status, phrase, proven) of the last canary result; proven is True only for a passing,
    verified result not older than CANARY_MAX_AGE_DAYS."""
    row = None
    try:
        with open(P.hook_canary(ROOT), encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("schema_version") != 1:
            raise ValueError("schema_version")
        row = payload.get("runtimes", {}).get(runtime)
        if not isinstance(row, dict):
            return PASS, CANARY_UNKNOWN, False
        status, fired, effect, at = row["status"], row["dispatcher_fired"], row["effect"], row["checked_at"]
        if status not in (PASS, FAIL) or fired not in ("verified", "not_verified") \
                or effect not in ("verified", "not_verified"):
            raise ValueError("result fields")
    except FileNotFoundError:
        return PASS, CANARY_UNKNOWN, False
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        # A damaged row that says the canary failed or did not verify must not read as a pass.
        seen = row if isinstance(row, dict) else {}
        failed = seen.get("status") == FAIL or "not_verified" in (seen.get("dispatcher_fired"), seen.get("effect"))
        return (WARN if failed else PASS), f"{CANARY_UNKNOWN} (canary result unreadable: {type(error).__name__})", False
    if status == FAIL or "not_verified" in (fired, effect):
        return WARN, f"live firing not verified (last canary {at}: fired {fired}, effect {effect})", False
    phrase = f"live firing verified {at}"
    try:
        stamp = datetime.datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return PASS, phrase, False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    old = datetime.datetime.now(datetime.timezone.utc) - stamp > datetime.timedelta(days=CANARY_MAX_AGE_DAYS)
    if old:
        return WARN, f"live firing verified {at}, over {CANARY_MAX_AGE_DAYS} days ago", False
    return PASS, phrase, True


def _precompact_fixture_config():
    return {
        "schema_version": 4,
        "instance": {"name": "doctor-fixture"},
        "tracks": [],
        "threads": [],
        "personal_pointer": None,
        "journal_visibility": {
            "public_tracks": ["system"],
            "legacy_cutoff": None,
            "legacy_public_tracks": [],
        },
        "journal_types": ["decision", "state", "artifact", "correction", "lesson", "switch", "idea"],
        "thresholds": {
            "now_tail_events": 12,
            "now_recent_decisions": 8,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_max_bytes": 6000,
            "now_hook_max_bytes": 6000,
        },
    }


def _simulate_precompact(runtime):
    """Run the declared PreCompact command in a disposable instance and inspect its journal."""
    cmds = _hook_cmds(runtime) or {}
    commands = cmds.get("PreCompact") or []
    if not commands:
        return FAIL, f"{runtime} PreCompact command missing"
    # An owner's own PreCompact line may stand beside the kit's event line; only that line is run.
    command = _event_line(commands, runtime, "PreCompact")
    if command is None and len(commands) != 1:
        return FAIL, PRECOMPACT_MULTIPLE.format(runtime=runtime, count=len(commands))
    command = command or commands[0]

    source_tools = os.path.join(ROOT, "tools")
    required = [os.path.join(source_tools, name)
                for name in ("hook.sh", "dispatch.py", "now.py", "lib/config.py", "enforce.py",
                             "lib/hook_input.py", "lib/journal.py", "lib/paths.py", "lib/runlog.py", "lib/safeio.py")]
    missing = [path for path in required if not os.path.isfile(path)]
    if missing:
        return FAIL, "simulation tools missing: {items}".format(items=", ".join(missing))

    with tempfile.TemporaryDirectory(prefix=f"doctor-{runtime}-precompact-") as fixture:
        os.makedirs(os.path.join(fixture, "tools", "lib"))
        os.makedirs(os.path.dirname(P.config_file(fixture)))
        os.makedirs(P.state(fixture))
        for source in required:
            shutil.copy2(source, os.path.join(fixture, "tools", os.path.relpath(source, source_tools)))
        with open(P.config_file(fixture),
                  "w", encoding="utf-8") as config_file:
            json.dump(_precompact_fixture_config(), config_file, ensure_ascii=False)

        # Inherited GIT_* variables (set when run from a git hook) would point git init and the
        # hook's own git calls at the real repository instead of the fixture.
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        if runtime == "codex":
            init = subprocess.run(["git", "init", "-q", fixture], capture_output=True, text=True,
                                  env=clean_env)
            if init.returncode:
                return FAIL, f"temporary git init failed: {(init.stderr or init.stdout).strip()[:120]}"

        env = dict(clean_env, CLAUDE_PROJECT_DIR=fixture, MOTTORI_INTERNAL_RUN="1")
        env.pop("MOTTORI_INSTANCE", None)
        env.pop("MOTTORI_DISABLE_HOOKS", None)
        payload = json.dumps({"hook_event_name": "PreCompact", "cwd": fixture})
        run = subprocess.run(["bash", "-c", command], cwd=fixture, env=env, input=payload,
                             capture_output=True, text=True)
        journals = []
        state_dir = P.state(fixture)
        for name in os.listdir(state_dir):
            if P.JOURNAL_NAME.match(name):
                journals.append(os.path.join(state_dir, name))
        texts = [open(path, encoding="utf-8").read() for path in journals]
        effect = any(PRECOMPACT_MARKER in text for text in texts)
        if run.returncode != 0:
            tail = (run.stderr or run.stdout).strip().splitlines()
            detail = f" · {tail[-1][:120]}" if tail else ""
            return FAIL, f"command exit={run.returncode}{detail}"
        if not effect:
            error_log = P.hook_errors(fixture)
            fallback_lines = (open(error_log, encoding="utf-8").read().strip().splitlines()
                              if os.path.isfile(error_log) else [])
            fallback = fallback_lines[-1] if fallback_lines else "none"
            return FAIL, f"command exited 0 but journal effect is missing · fallback={fallback[:120]}"
        return PASS, f"recorded '{PRECOMPACT_MARKER}' in the temporary instance journal"


def c_precompact_claude():
    return _simulate_precompact("claude")


def c_precompact_codex():
    return _simulate_precompact("codex")


# Days a new workspace may go without a recorded compaction before the missing event is a warning.
COMPACTION_GRACE_DAYS = 14


def _older_than(entries, days):
    """Whether the journal's first row is more than `days` old; False when it cannot be read."""
    try:
        first = datetime.datetime.fromisoformat(entries[0]["ts"])
    except (IndexError, KeyError, TypeError, ValueError):
        return False
    if first.tzinfo is None:
        first = first.astimezone()
    return (datetime.datetime.now().astimezone() - first).days > days


def c_precompact_journal():
    """Look for a recorded compaction event in the public and local journals.

    The simulations above prove the command works. A recorded event shows that something ran
    now.py precompact here, which used to be a manual check; it does not prove which runtime
    dispatched it. A row that only quotes the marker is not an event."""
    import now
    # Damaged rows are skipped here: the state row already fails on them.
    entries = J.parse_journal(errors=[])
    events = [e for e in entries if now.is_compaction(e)]
    if events:
        return PASS, "a compaction event is recorded, the latest at {when}".format(when=events[-1]["ts"])
    # Before the first Claude Code session nothing can have compacted, and a workspace in its
    # first weeks may simply not have reached one: the missing event warns only after that.
    status = WARN if os.path.isdir(P.transcripts()) and _older_than(entries, COMPACTION_GRACE_DAYS) else SKIP
    return status, PRECOMPACT_JOURNAL_NONE.format(marker=PRECOMPACT_MARKER)


def _injects_time(commands):
    """True when a command runs date itself, or is the kit's event line of an event whose steps
    include the dispatcher's time step."""
    commands = list(commands)
    for command in commands:
        match = dispatch.EVENT_LINE.search(command)
        if match and any(step.id == "time" for step in dispatch.steps(*match.groups())):
            return True
    return dispatch.injects_time(commands)


def c_global_hook():
    """Check the global UserPromptSubmit timestamp hook, which is not cloned with the repo."""
    p = os.path.expanduser("~/.claude/settings.json")
    if not os.path.exists(p):
        has = False
    else:
        try:
            cfg = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            return WARN, f"global settings parse failed: {e}"
        try:
            ups = hookdiag.declared("claude", cfg).get("UserPromptSubmit", [])
            has = _injects_time(h["command"] for h in ups if isinstance(h["command"], str))
        except (AttributeError, TypeError, KeyError):
            return WARN, SETTINGS_SHAPE.format(path="~/.claude/settings.json")
    if has:
        return PASS, "time injection hook present"
    # Inside this folder the project settings may already inject the time; only others lack it.
    try:
        project = (_hook_cmds("claude") or {}).get("UserPromptSubmit", [])
    except SettingsShapeError as e:
        return WARN, str(e)  # named here too, so it is not read as missing global settings
    except ValueError:
        project = []  # the wiring row already reports the syntax error
    if _injects_time(project):
        # Sessions here get the time; the gap is in other folders, so nothing here needs fixing.
        return SKIP, TIME_PROJECT_ONLY
    return WARN, (GLOBAL_MISSING if not os.path.exists(p) else TIME_HOOK_MISSING)


def c_precommit_install():
    """Read the installed Git hooks' states from install_hooks.sh --check without repairing them.

    Each hook line is a status word, a tab, the hook's path and optionally words for a person;
    only the first two fields decide. Exit 3 means core.hooksPath points outside this folder; any
    other run without hook lines is a refusal whose own line says why.
    """
    script = os.path.join(ROOT, "tools", "install_hooks.sh")
    if not os.path.exists(script):
        return WARN, "installer missing"
    # In a folder inside another project's repository, --repair would install into that project.
    top = sh("git", "rev-parse", "--show-toplevel").stdout.strip()
    if not top or os.path.realpath(top) != os.path.realpath(ROOT):
        return WARN, PRECOMMIT_NOT_OWN_REPO
    r = sh("bash", script, "--check")
    hooks = [line.split("\t", 2) for line in (r.stdout + r.stderr).splitlines()
             if line.split("\t", 1)[0] in HOOK_IN_PLACE + HOOK_FREE + ("foreign",) and "\t" in line]
    if not hooks:
        first = ((r.stderr + r.stdout).strip().splitlines() or [f"exit={r.returncode}"])[0]
        # --repair refuses a shared hooks folder, so name the way out.
        if r.returncode == 3:
            return FAIL, HOOKSPATH_OUTSIDE.format(detail=first)
        return FAIL, first
    if r.returncode == 0 and all(fields[0] in HOOK_IN_PLACE for fields in hooks):
        if all(fields[0] == "current" for fields in hooks):
            return PASS, "current: " + " + ".join(fields[1] for fields in hooks)
        return PASS, " · ".join(_hook_line(fields) for fields in hooks)
    # Every hook counts: a foreign hook must not hide behind a missing one, and each foreign line
    # already names its two ways forward.
    foreign = [_hook_line(fields) for fields in hooks if fields[0] == "foreign"]
    free = [_hook_line(fields) for fields in hooks if fields[0] in HOOK_FREE]
    if foreign:
        # Another tool's pre-push hook is the owner's: commits are still checked, pushes are not.
        if not free and all(os.path.basename(fields[1]) == "pre-push" for fields in hooks if fields[0] == "foreign"):
            return WARN, PUSH_HOOK_NOT_OURS.format(detail=" · ".join(foreign))
        return FAIL, REPAIR_NEEDED.format(detail=" · ".join(foreign)) if free else " · ".join(foreign)
    # A missing or drifted hook leaves commits or pushes unchecked; --repair installs it.
    return FAIL, REPAIR_NEEDED.format(detail=free[0])


def _hook_line(fields):
    """One hook of install_hooks.sh --check as a person reads it: status, path, its words."""
    status, target, words = (fields + ["", ""])[:3]
    return f"{status}: {target}" + (f" ({words})" if words else "")


def c_tools_run():
    """Run now.py check --issues and require its #issues trailer.

    check, not render, so the row writes no generated state. The row asks whether the check runs,
    not whether it finds issues: exit 1 with the trailer passes, a crash or a missing trailer fails."""
    # linkcheck and coherence have their own rows with crash detection, so only now.py runs here.
    bad = []
    r = sh(sys.executable, "tools/now.py", "check", "--issues")
    if r.returncode not in (0, 1):   # now.py uses exit 1 for reported findings.
        bad.append(f"tools/now.py exit={r.returncode} {r.stderr.strip()[:80]}")
    else:
        # Require the final #issues trailer: exit 1 alone cannot distinguish findings from a crash.
        last = (r.stdout.strip().splitlines() or [""])[-1]
        if not re.match(r"^#issues \d+$", last):
            bad.append(TRAILER_MISSING.format(tool="tools/now.py", last=last[:40]))
    if bad:
        return FAIL, " · ".join(bad)
    # A reminder the check gives without blocking, such as a track summary behind its decisions,
    # is shown here so it reaches the owner (KIT-DR-081 (13)).
    reminders = [line.split("\t", 1)[1] for line in r.stdout.splitlines()
                 if line.startswith("~canonical-stale") and "\t" in line]
    if reminders:
        return WARN, "\n      ".join(reminders[:3]) + (MORE.format(count=len(reminders) - 3) if len(reminders) > 3 else "")
    return PASS, "now.py check runs OK (trailer verified)"


def c_links():
    """Inspect linkcheck findings, not only whether its process ran.

    The --issues form exits 0 with one "source -> target" row per finding and a final #issues
    trailer, so neither the language setting nor the summary wording affects this row."""
    r = sh(sys.executable, "tools/linkcheck.py", "--issues")
    if r.returncode or "Traceback" in r.stderr:
        first = (r.stderr.strip().splitlines() or ["?"])[-1]
        return FAIL, f"checker crashed (exit={r.returncode}): {first[:100]}"
    lines = r.stdout.strip().splitlines()
    m = re.fullmatch(r"#issues (\d+)", lines[-1] if lines else "")
    if not m:
        return FAIL, TRAILER_MISSING.format(tool="tools/linkcheck.py", last=(lines or [""])[-1][:40])
    # A link an adopted folder already had broken is recorded as known by adopt.py, as the turn-end
    # check reads it, so a folder brought in as it is does not fail doctor once Git keeps it.
    import adopted
    known = adopted.issue_ids()
    found = [line.split("\t", 1)[0] for line in lines[:-1]]
    kept = [i for i in found if i not in known]
    n = int(m.group(1)) - (len(found) - len(kept))
    had = len(found) - len(kept)
    note = f"; {had} that an adopted folder already had are recorded as known by adopt.py" if had else ""
    if not n:
        # In a kit installation Git lists none of the owner's own folders, so the run did not read them.
        if P.owner_names(ROOT):
            return PASS, LINKS_OK_LISTED + note
        return PASS, "no broken references" + note
    detail = kept[:5]
    more = MORE.format(count=n - len(detail)) if n > len(detail) else ""
    # Code spans that only name a file (one still to be made, or generated data) never block the
    # turn-end check, so they are information here, not a failure. The session run skips the
    # contributor folders, so only when its advisory rows account for every finding is none of
    # them a blocker.
    session = sh(sys.executable, "tools/linkcheck.py", "--issues", "--session")
    rows = session.stdout.strip().splitlines()
    advisory = sum(line.startswith("~") and line[1:].split("\t", 1)[0] not in known for line in rows)
    level = WARN if session.returncode == 0 and rows[-1:] == ["#issues 0"] and advisory == n else FAIL
    return level, "broken references {count}:\n      {details}{more}".format(count=n, details="\n      ".join(detail), more=more)


def c_coherence():
    """Run the hub and status-date checks; the link and ledger rows already cover the rest."""
    import coherence
    n = len(coherence.check_hubs()) + len(coherence.check_status_docs())
    if not n and not coherence.configured():
        # An empty list checks nothing, and a pass would read as a check that found nothing.
        return SKIP, coherence.NOTHING_LISTED
    return (PASS if not n else WARN), f"coherence issues {n}"


def c_projects():
    """The owner's project folders (KIT-DR-093). Every folder under projects/ is a project; what is
    wrong with one is a warning, since a planned project's first file or an outside folder on another
    machine can be missing for a while."""
    import project_folders as projects
    if not os.path.isdir(P.projects()):
        return SKIP, "no projects/ folder yet; `bash setup.sh --force` creates it with its guide"
    found = projects.read()
    if not found:
        return PASS, "projects/ holds no project yet; projects/README.md says how to add one"
    counts = collections.Counter(p["status"] or "no status" for p in found)
    summary = ", ".join(f"{counts[s]} {s}" for s in (*projects.STATUSES, "no status") if counts[s])
    foreign = [p["folder"] for p in found if p["foreign"]]
    if foreign:
        summary += f"; {len(foreign)} with a README block of another kind, not read: " + ", ".join(foreign[:3])
    warns = projects.problems(found)
    if warns:
        more = f"\n      (+{len(warns) - 8} more: python3 tools/projects.py check)" if len(warns) > 8 else ""
        return WARN, f"{len(found)} projects ({summary}); " + "\n      ".join(warns[:8]) + more
    outside = sorted({path for p in found for path, _ in p["outside"] if not projects.URL.match(path)})
    reach = (f" · folders outside this one ({len(outside)}): each runtime reaches them with --add-dir, and "
             "Claude Code also with permissions.additionalDirectories" if outside else "")
    return PASS, f"{len(found)} projects ({summary}){reach}"


def _config_paths():
    """(field, path) for every path in the config that names a file or folder inside this workspace."""
    data = C.data()
    out = [("frozen", x) for x in data.get("frozen", [])]
    loop = data.get("loop", {}) if isinstance(data.get("loop"), dict) else {}
    out += [("loop.never", x) for x in loop.get("never", [])]
    out += [("loop.clone_excluded", x) for x in loop.get("clone_excluded", [])]
    egress = data.get("egress", {}) if isinstance(data.get("egress"), dict) else {}
    send = egress.get("model_send", {}) if isinstance(egress.get("model_send"), dict) else {}
    # A folder kept out of worker copies that was moved: the files at its new place go to workers.
    out += [("egress.model_send.deny_prefixes", x) for x in send.get("deny_prefixes", []) if x != "_private/"]
    for row in data.get("tracks", []):
        out.append(("tracks.canonical", row.get("canonical")))
        out += [("tracks.also", x) for x in row.get("also", [])]
    out += [("threads.dossier", row.get("dossier")) for row in data.get("threads", []) if row.get("dossier")]
    checks = data.get("checks", {}) if isinstance(data.get("checks"), dict) else {}
    out += [("checks.status_docs", row[0]) for row in checks.get("status_docs", []) if row]
    for row in checks.get("hubs", []):
        if isinstance(row, list) and row:
            # A pair of a folder and its index file, which lives in that folder.
            out += [("checks.hubs", row[0])] + ([("checks.hubs", os.path.join(row[0], row[1]))] if len(row) > 1 else [])
    out.append(("personal_pointer", data.get("personal_pointer")))
    return [(f, x) for f, x in out if isinstance(x, str) and x and not os.path.isabs(x) and not x.startswith("~")]


def c_config_paths():
    """A config path that names nothing on disk: after a reorganization the frozen list, the loop's
    never-list, the worker copies' exclusions or a track's document would no longer cover what the
    owner meant, without a word
    (KIT-DR-095). It is a warning, because a path can also name a folder not made yet, which the
    turn-end check still covers once it exists."""
    if not C.load_ok():
        return SKIP, f"no usable config; see the {LABELS['wiring_config']} row"
    paths = _config_paths()
    missing = [f"{field}: {path}" for field, path in paths
               if not os.path.exists(os.path.join(P.instance_root(), path.rstrip("/")))]
    prefixes = C.data().get("checks", {}).get("linkcheck_exclude_prefixes", []) if isinstance(
        C.data().get("checks"), dict) else []
    unmatched = []
    for prefix in prefixes:
        if isinstance(prefix, str) and prefix.startswith(("./", "/")):
            # The link check compares the path as written with paths like docs/a.md, so this matches nothing.
            unmatched.append(f"checks.linkcheck_exclude_prefixes: {prefix} (write it without the leading "
                             f"{prefix[:prefix.index('/') + 1]})")
            continue
        parent = os.path.dirname(os.path.join(P.instance_root(), prefix))
        base = os.path.basename(prefix)
        try:
            hit = any(n.startswith(base) for n in os.listdir(parent)) if base else os.path.isdir(parent)
        except OSError:
            hit = False
        if not hit:
            unmatched.append(f"checks.linkcheck_exclude_prefixes: {prefix}")
    if missing or unmatched:
        return WARN, CONFIG_PATHS_MISSING.format(items="\n      ".join(missing[:10] + unmatched[:6]))
    if not paths and not prefixes:
        return SKIP, "the config names no path inside this folder"
    return PASS, f"{len(paths) + len(prefixes)} config paths name something on disk"


CONFIG_PATHS_MISSING = (
    "config paths that name nothing on disk: renamed, moved or not made yet. A renamed one covers "
    "nothing at the new place; fix it in instance/config.json:\n      {items}"
)


def c_worker_receipts():
    """Report recent worker costs and failure rates; only unreadable receipts warn."""
    import receipts as R
    now = datetime.datetime.now(datetime.timezone.utc)
    # Only run folders named inside the window are read, and no prompt bodies.
    records, errors = R.load_runs(P.runs(ROOT),
                                  since=now - datetime.timedelta(days=7), prompt=False)
    recent = R.recent_runs(records, days=7, now=now)
    totals = R.totals(recent)
    runs = totals["runs"]
    failures = totals["failures"]
    rate = failures / runs * 100 if runs else 0.0
    usage = R.usage_text(totals["usage"])
    detail = RECEIPTS_DETAIL.format(runs=runs, usage=usage, measured=totals["measured"], failures=failures, rate=f"{rate:.1f}", running=totals["running"])
    if errors:
        return WARN, detail + f" · unreadable={len(errors)}"
    # A past failure cannot be cleared by anything the owner does now, so the rate is information.
    return PASS, detail


def _transcript_retention():
    """Say how long Claude Code keeps the transcripts recall reads; information, never a status.

    Claude Code silently deletes terminal session files older than cleanupPeriodDays (default 30),
    so recall's reach ends there. options.retention reads the setting for this row and the options list.
    """
    import options
    days, problem = options.retention(ROOT)
    if problem:
        return f"transcript retention not measured: {problem}"
    if days <= options.RETENTION_DEFAULT:
        return RETENTION_SHORT.format(days=days)
    return f"transcripts kept {days} days (cleanupPeriodDays)"


def c_recall():
    # --all lifts the listing cap, so the rows are the count and no footer is read.
    r = sh(sys.executable, "tools/recall.py", "sessions", "--all")
    if r.returncode:
        return FAIL, r.stderr.strip()[:150]
    # Count only session rows; notices such as "no records yet" are not sessions.
    n = len(re.findall(r"^\[[^\]\s]+ *\] ", r.stdout, re.M))
    # With no transcript folder yet the transcript row carries the warning; zero is expected here.
    status = PASS if n else WARN if os.path.isdir(P.transcripts()) and _last_turn_end_run() else SKIP
    return status, f"{n} past session(s) readable" + " · " + _transcript_retention()


def c_context_budget():
    """Warn, never fail, when the fixed per-session context crosses a configured warning line."""
    import context_budget as CB
    report = CB.measure()
    total = report["total"]
    # The total leaves out hooks it cannot run safely; say so instead of implying a full count.
    count = report.get("unmeasured", 0)
    partial = f"; partial total, {count} hook(s) not counted" if count else ""
    if report["warnings"]:
        return WARN, CONTEXT_OVER.format(bytes=total["bytes"], tokens=total["tokens"], items=", ".join(report["warnings"])) + partial
    return PASS, "fixed context {bytes} bytes (~{tokens} tokens)".format(bytes=total["bytes"], tokens=total["tokens"]) + partial


GROWTH_DEFAULT_LIMITS = {
    "growth_disk_free_min_bytes": 5 * 1024 ** 3,
    "growth_git_max_bytes": 1024 ** 3,
    "growth_tmp_stale_days": 14,
    "growth_tmp_stale_max_bytes": 500 * 1024 ** 2,
    "growth_unguided_work_dirs_max": 10,
    "growth_scan_budget_ms": 1500,
}
GROWTH_DEFAULT_WORK_DIRS = ["_private/work"]
# Top-level page names that tell a reader what a job folder is and what may be deleted.
GROWTH_GUIDE_PREFIXES = ("README", "STATE", "HANDOFF", "DOSSIER", "INDEX")
GROWTH_EXAMPLES = 5


class _OutOfTime(Exception):
    """Raised when a growth measurement reaches the shared deadline."""


def _size_text(n):
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"


def _growth_git_bytes(root, deadline):
    """Return the object store size from git count-objects, or None when root has no .git.

    count-objects reads pack indexes and loose object counts only, so it stays cheap on a
    large history. Inherited GIT_* variables could point Git at another repository.
    """
    if not os.path.exists(os.path.join(root, ".git")):
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _OutOfTime
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", "-C", root, "count-objects", "-v"], capture_output=True,
                           text=True, env=env, timeout=remaining)
    except subprocess.TimeoutExpired:
        raise _OutOfTime from None
    except FileNotFoundError:
        return None  # no git binary: not measurable, which is not the same as out of time
    if r.returncode:
        return None
    fields = dict(line.split(": ", 1) for line in r.stdout.splitlines() if ": " in line)
    kib = sum(int(fields.get(k, 0)) for k in ("size", "size-pack", "size-garbage"))
    return kib * 1024


def _growth_stale_tmp(tmp, cutoff, deadline):
    """Sum bytes of files under tmp last modified before cutoff, grouped by top-level entry.

    Symlinks are not followed so a link to a large tree elsewhere is not counted. The walk
    checks the deadline at every entry so a folder with very many files stops on time.
    """
    by_top = {}
    stack = [(tmp, None)]
    while stack:
        path, top = stack.pop()
        try:
            entries = os.scandir(path)
        except OSError:
            continue
        with entries:
            for entry in entries:
                if time.monotonic() > deadline:
                    raise _OutOfTime
                name = top or entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((entry.path, name))
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_mtime < cutoff:
                    by_top[name] = by_top.get(name, 0) + st.st_size
    return by_top


def _growth_unguided(root, work_dirs, deadline):
    """List job folders, directly under each configured work dir, with no top-level guide page.

    Returns None when none of the configured work dirs exists.
    """
    found, seen_any = [], False
    for rel in work_dirs:
        base = os.path.join(root, rel)
        if not os.path.isdir(base):
            continue
        seen_any = True
        for child in sorted(os.scandir(base), key=lambda e: e.name):
            if time.monotonic() > deadline:
                raise _OutOfTime
            if child.name.startswith(".") or not child.is_dir(follow_symlinks=False):
                continue
            try:
                guided = any(e.name.upper().startswith(GROWTH_GUIDE_PREFIXES)
                             and e.is_file(follow_symlinks=False)
                             for e in os.scandir(child.path))
            except OSError:
                continue
            if not guided:
                found.append(f"{rel.rstrip('/')}/{child.name}")
    return found if seen_any else None


# One sign of growth: its key, the words that name it, the config key of its threshold, how it
# is measured, whether a value crosses the threshold, the line shown then, and how a value reads.
# measure(root, work_dirs, deadline, days, disk_usage) returns (value, examples), or None when
# the thing measured does not exist here.
Growth = collections.namedtuple("Growth", "key name limit measure over line shown")


def _disk_free(root, work_dirs, deadline, days, disk_usage):
    return disk_usage(root).free, []


def _git_size(root, work_dirs, deadline, days, disk_usage):
    size = _growth_git_bytes(root, deadline)
    return None if size is None else (size, [])


def _stale_tmp(root, work_dirs, deadline, days, disk_usage):
    path = os.path.join(root, "tmp")
    if not os.path.isdir(path):
        return None
    by_top = _growth_stale_tmp(path, time.time() - days * 86400, deadline)
    largest = sorted(by_top, key=lambda k: -by_top[k])[:GROWTH_EXAMPLES]
    return sum(by_top.values()), [f"tmp/{k} {_size_text(by_top[k])}" for k in largest]


def _unguided_work(root, work_dirs, deadline, days, disk_usage):
    found = _growth_unguided(root, work_dirs, deadline)
    return None if found is None else (len(found), found[:GROWTH_EXAMPLES])


# In the order the detail lists them. The tmp/ walk is open-ended, so it is measured last and
# gets whatever time the others leave.
GROWTH = [
    Growth("disk", "disk free", "growth_disk_free_min_bytes", _disk_free,
           lambda value, limit: value < limit, GROWTH_DISK_LOW, _size_text),
    Growth("git", ".git", "growth_git_max_bytes", _git_size,
           lambda value, limit: value > limit, GROWTH_GIT_OVER, _size_text),
    Growth("tmp", "tmp/ untouched over {days} days", "growth_tmp_stale_max_bytes", _stale_tmp,
           lambda value, limit: value > limit, GROWTH_TMP_OVER, _size_text),
    Growth("work", "job folders without a guide page", "growth_unguided_work_dirs_max",
           _unguided_work, lambda value, limit: value > limit, GROWTH_WORK_OVER, str),
]


def _growth_settings(config):
    """Return (limits, work_dirs) from the config, with the defaults for what it leaves out."""
    config = config if isinstance(config, dict) else {}
    configured = config.get("thresholds", {})
    limits = {k: configured.get(k, v) for k, v in GROWTH_DEFAULT_LIMITS.items()}
    growth = config.get("growth", {})
    work_dirs = growth.get("work_dirs", GROWTH_DEFAULT_WORK_DIRS) if isinstance(growth, dict) \
        else GROWTH_DEFAULT_WORK_DIRS
    if not isinstance(work_dirs, list):
        work_dirs = GROWTH_DEFAULT_WORK_DIRS
    return limits, [d for d in work_dirs if isinstance(d, str) and d]


def _growth_report(root, config, disk_usage=shutil.disk_usage):
    """Measure the signs that the workspace is growing and return (status, detail, items).

    items maps each key of GROWTH to {"state": ok, over, na or unmeasured, ...}. Crossing a line
    is a WARN, never a FAIL: deleting is the owner's decision, so the detail says only what is how
    large and where to look, and nothing is written, moved or deleted. All measurements share
    one deadline; one that does not finish in time is reported as not measured. A missing folder
    makes its item not applicable, so a fresh installation has no warning from this check.
    """
    limits, work_dirs = _growth_settings(config)
    budget_ms, days = limits["growth_scan_budget_ms"], limits["growth_tmp_stale_days"]
    deadline = time.monotonic() + budget_ms / 1000
    items = {}
    for g in sorted(GROWTH, key=lambda g: g.key == "tmp"):
        limit = limits[g.limit]
        # An unreadable folder is reported like a timeout: this check warns, it never fails.
        try:
            found = g.measure(root, work_dirs, deadline, days, disk_usage)
        except (_OutOfTime, OSError):
            items[g.key] = {"state": "unmeasured"}
            continue
        if found is None:
            items[g.key] = {"state": "na"}
            continue
        value, examples = found
        items[g.key] = {"state": "over" if g.over(value, limit) else "ok", "value": value,
                        "limit": limit, "examples": examples}
    parts, warnings = [], []
    for g in GROWTH:
        row, name = items[g.key], g.name.format(days=days)
        if row["state"] == "na":
            parts.append(f"{name}: not applicable")
        elif row["state"] == "unmeasured":
            warnings.append(f"{name}: not measured within {budget_ms} ms")
        else:
            parts.append(f"{name} {g.shown(row['value'])}")
        if row["state"] == "over":
            warnings.append(g.line.format(value=g.shown(row["value"]), limit=g.shown(row["limit"]),
                                          days=days, items=", ".join(row["examples"])))
    lines = ([" · ".join(parts)] if parts else []) + warnings
    return (WARN if warnings else PASS), "\n      ".join(lines), items


def c_workspace_growth():
    """Warn, never fail, when the workspace shows signs of unchecked growth."""
    config = C.data() if isinstance(C.data(), dict) else {}
    status, detail, _items = _growth_report(P.instance_root(), config)
    return status, detail


def c_ledger():
    d = P.ledger_facts()
    if not os.path.isdir(d):
        return SKIP, "ledger not initialized (facts.py creates it on first record)"
    n = len([f for f in os.listdir(d) if f.endswith(".md")])
    r = sh(sys.executable, "tools/facts.py", "check")
    if r.returncode != 0 or "Traceback" in r.stderr:
        # Exit 1 with PROBLEM lines on stdout is a finding; a crash explains itself on stderr.
        problems = [x for x in r.stdout.splitlines() if x.startswith("PROBLEM ")]
        detail = (problems[:1] if problems and "Traceback" not in r.stderr else
                  r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1]
        return FAIL, f"facts.py check failed: {detail[:160]} (python3 tools/facts.py check lists every problem)"
    # facts.py check exits 1 on any problem, so exit 0 is the clean verdict; its trailer is prose.
    return PASS, f"facts {n} · consistency issues 0"


def c_person_ledger():
    """Check whether unprocessed person-ledger candidates have accumulated since its last update."""
    import person_ledger
    if not os.path.exists(person_ledger.PORTRAIT):
        return None  # the person ledger is opt-in; until it exists there is nothing to check
    since = person_ledger.last_update()
    if not since:
        return WARN, (
            "ledger has no `last-reviewed: YYYY-MM-DD` line; freshness cannot be measured"
        )
    n = len(person_ledger.pending(since))
    msg = PERSON_LEDGER_COUNTS.format(date=since, count=n, threshold=person_ledger.STALE_THRESHOLD)
    if n >= person_ledger.STALE_THRESHOLD:
        return WARN, f"{msg}; run python3 tools/person_ledger.py candidates"
    return PASS, msg


def c_egress():
    """Check that the model-send policy loads and that each allowed prefix narrows a denied one."""
    if C.error() == "invalid":
        # The config load refuses an unsafe policy; keep naming that cause to the owner.
        cause = C.error_cause()
        if cause in ("allow_prefixes", "allow_unsafe"):
            return FAIL, "egress.model_send allow_prefixes validation failed"
        return FAIL, "memory config validation failed; model-send policy is unavailable"
    deny = C.egress_model_send().get("deny_prefixes", [])
    allow = C.egress_model_send().get("allow_prefixes", [])
    relationship_errors = C.egress_prefix_relationship_errors(deny, allow)
    if relationship_errors:
        return FAIL, (
            "egress.model_send allow_prefixes must strictly narrow deny_prefixes: {detail}"
        ).format(detail="; ".join(relationship_errors))
    return PASS, f"model-send policy deny={len(deny)} · allow={len(allow)}"


def c_symlinks():
    """Find tracked symlinks that expose private targets or paths. Git stores the link target; consumers may later dereference it."""
    # Use NUL-separated paths so Git quoting cannot change filenames. Names stay bytes, since
    # Git allows names that are not UTF-8, and are decoded only for display.
    r = subprocess.run(["git", "ls-files", "-s", "-z"], capture_output=True, cwd=ROOT)
    if r.returncode:
        return SKIP, NOT_GIT
    links = [rec.split(b"\t", 1)[1] for rec in r.stdout.split(b"\0")
             if rec.startswith(b"120000") and b"\t" in rec]
    if not links:
        return PASS, "tracked symbolic links 0"

    def shown(name):
        return name.decode("utf-8", "backslashreplace")[-52:]
    priv = os.path.realpath(os.fsencode(P.private_area(ROOT)))
    into_private = []
    for l in links:
        full = os.path.join(os.fsencode(ROOT), l)
        try:
            raw = os.readlink(full)
        except OSError:
            raw = b""
        # Compare whole path components: a sibling such as _private_old is not private.
        target = os.path.realpath(full)
        if os.path.commonpath([target, priv]) == priv or b"_private" in raw.split(b"/"):
            into_private.append(f"{shown(l)}  ->  {shown(raw)}")
    if into_private:
        more = MORE.format(count=len(into_private) - 3) if len(into_private) > 3 else ""
        head = PRIVATE_SYMLINKS.format(count=len(into_private), items="\n      ".join(into_private[:3]), more=more)
        return WARN, head + "\n      cleanup: git rm --cached <path> (the file remains on disk)"
    return WARN, f"tracked symbolic links with targets outside _private: {len(links)}"


def _linkcheck_scope():
    """Hash the same file paths and bytes that linkcheck uses for its verification record."""
    import linkcheck
    r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                        "--exclude-standard", "*.md"], cwd=ROOT, capture_output=True, check=True)
    paths = [os.fsdecode(path) for path in r.stdout.split(b"\0") if path]
    # One shared function keeps this hash byte-identical to the one linkcheck records.
    return linkcheck.scope_hash(paths, ROOT)


def _last_turn_end_run():
    """Return the time of the latest turn-end gate record of any outcome, or None."""
    last = None
    for parts in runlog.rows():
        if len(parts) >= 4 and parts[1] == "gate" and "@Stop" in parts[3]:
            last = parts[0]
    return last


def c_missed_gate():
    """Report whether a link check covered the current files: a recorded linkcheck pass over these
    bytes, or a turn-end gate pass over this working tree. Neither is a defect by itself, because
    shell edits and hookless runtimes change files between checks, so this is a warning; broken
    links are measured and failed by the link check row in the same run."""
    if sh("git", "rev-parse", "--is-inside-work-tree").returncode:
        return SKIP, NOT_GIT
    # A record covers Markdown source bytes only; a deleted link target leaves them unchanged,
    # so a failed link row in this run outranks either recorded pass. The warnings stay: they
    # are how a missing run log or a Stop hook that never fires stays visible.
    def recorded(detail):
        if status_of("tools_links") == FAIL:
            return SKIP, f"the {LABELS['tools_links']} row failed in this run, so no recorded pass is claimed"
        return PASS, detail
    if not os.path.exists(P.tool_runs()):
        return WARN, "no check execution log (instrument not running)"
    # Bind evidence to the exact bytes read by linkcheck, including unstaged and untracked inputs.
    cur_scope = _linkcheck_scope()
    if runlog.ran_at_head("linkcheck", cur_scope, require_ok=True):
        return recorded("linkcheck pass recorded for the current Markdown source bytes")
    # A passing turn-end gate records the same identity of the documents it measured.
    if runlog.ran_at_head("gate", cur_scope, require_ok=True):
        return recorded("the last turn-end gate pass covered the current working tree")
    # The last turn-end time keeps a Stop hook that never fires visible here.
    last = _last_turn_end_run() or "never recorded"
    return WARN, UNVERIFIED_SINCE.format(last=last)


def c_agents_parity():
    """Require CLAUDE.md to import the single AGENTS.md source exactly. A copied policy can diverge after either file is edited."""
    a, b = os.path.join(ROOT, "CLAUDE.md"), os.path.join(ROOT, "AGENTS.md")
    if not os.path.exists(a):
        return FAIL, "CLAUDE.md missing"
    if not os.path.exists(b):
        return FAIL, "AGENTS.md missing; neither runtime can read the single authority"
    x, y = open(a, "rb").read(), open(b, "rb").read()
    if x in (b"@AGENTS.md", b"@AGENTS.md\n"):
        return PASS, f"AGENTS.md single-authority import ({len(y)} bytes)"
    return FAIL, AGENTS_MISMATCH.format(claude=len(x), agents=len(y))


def c_schema():
    """Report config migrations required by the current engine. Instance-owned config is not replaced by an engine update."""
    if not C.load_ok():
        # The config row already reports a missing or broken file; a schema row would call it v1.
        return SKIP, f"no usable config to compare; see the {LABELS['wiring_config']} row"
    if C.schema() > C.SCHEMA_VERSION:
        return FAIL, SCHEMA_NEWER.format(config=C.schema(), engine=C.SCHEMA_VERSION)
    gap = C.schema_gap()
    if gap is None:
        return PASS, f"schema v{C.schema()} (engine expects v{C.SCHEMA_VERSION})"
    cur, want, todo = gap
    return FAIL, SCHEMA_OLD.format(config=cur, engine=want, todo="\n      ".join(todo))


def _status_entries(*extra):
    """Return (XY, path) pairs from git status --porcelain -z.

    The NUL form keeps non-ASCII and spaced names undecorated. A rename or copy record is
    followed by its source path, which is skipped so each change is listed once. Output is
    read as bytes: a name that is not UTF-8 is shown with backslash escapes instead of
    failing the decode, and stays printable.
    """
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    out = subprocess.run(["git", "status", "--porcelain", "-z", *extra], capture_output=True,
                         cwd=ROOT, env=env).stdout
    fields = [field.decode("utf-8", "backslashreplace") for field in out.split(b"\0")]
    entries, i = [], 0
    while i < len(fields):
        record = fields[i]
        i += 1
        if len(record) < 4:
            continue
        xy = record[:2]
        entries.append((xy, record[3:]))
        if "R" in xy or "C" in xy:
            i += 1
    return entries


def _kit_files():
    """The kit's own files from system/dev/kit-files.txt, or None where the list is missing."""
    try:
        with open(os.path.join(ROOT, "system", "dev", "kit-files.txt"), encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip() and not line.startswith("#")}
    except OSError:
        return None


GITIGNORE_MARKER = "# --- this installation's own lines ---"


def _engine_ignore_changed():
    """Whether .gitignore changed above the marker, where the kit's lines are."""
    head = sh("git", "show", "HEAD:.gitignore")
    try:
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            now = f.read()
    except OSError:
        return True
    return head.returncode != 0 or head.stdout.split(GITIGNORE_MARKER)[0] != now.split(GITIGNORE_MARKER)[0]


def c_upstream():
    """Report local engine modifications and upstream revision differences. Instance-specific changes belong in the instance extension files."""
    r = sh("git", "rev-parse", "--is-inside-work-tree")
    if r.returncode:
        return SKIP, NOT_GIT
    # The exporter exists only in the source workspace, where engine edits are expected.
    if os.path.exists(os.path.join(ROOT, "tools", "kit_sync.py")):
        return SKIP, "this is upstream (kit_sync present); engine modifications are normal"
    # A tracked change to one of the kit's own files is an engine change; an installation that keeps
    # its own folders in Git (lines below the marker in .gitignore) changes those freely (KIT-DR-090).
    mod = [path for xy, path in _status_entries() if xy not in ("??", "!!")]
    listed = _kit_files()
    if listed is not None:
        mod = [path for path in mod if path in listed and (path != ".gitignore" or _engine_ignore_changed())]
    up = sh("git", "rev-list", "--count", "HEAD..@{u}")
    behind = up.stdout.strip() if up.returncode == 0 else None
    msgs = []
    if mod:
        msgs.append(ENGINE_MODIFIED.format(items=", ".join(mod[:6])))
    if behind and behind != "0":
        msgs.append(f"behind upstream by {behind} commit(s); run `git pull` and doctor again")
    if msgs:
        return WARN, "\n      ".join(msgs)
    # Doctor does not fetch, so this compares with what the last fetch saw.
    status = " · not behind upstream as of the last fetch" if behind == "0" else " · upstream not configured"
    return PASS, f"local engine modifications 0{status}"


def c_engine_drift():
    """Compare shared tools through the exporter's read-only policy, not directory overlap."""
    path = os.path.join(ROOT, "tools", "kit_sync.py")
    if not os.path.isfile(path):
        return None  # the exporter exists only in the source workspace; elsewhere this never applies
    kit = os.environ.get("MOTTORI_KIT") or os.path.expanduser("~/mottori-kit")
    if not os.path.isdir(os.path.join(kit, "tools")) or os.path.realpath(kit) == os.path.realpath(ROOT):
        return SKIP, "no kit copy to compare"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_doctor_kit_sync", path)
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        if os.path.realpath(exporter.KIT) != os.path.realpath(kit):
            raise ValueError("export destination mismatch")
        expected = {name for name in exporter.ENGINE if name not in exporter.PRESERVED_VARIANTS}
        if not expected:
            raise ValueError("empty export scope")
        plan = exporter.plan_export({"tools/" + name for name in expected})
        same, changed, missing = (plan[key] for key in ("same", "changed", "missing"))
        if not all(isinstance(items, list) and all(isinstance(item, str) for item in items)
                   for items in (same, changed, missing)):
            raise ValueError("invalid export plan")
        if missing:
            # A finding of the exporter, not a doctor crash.
            return FAIL, (
                "kit export would miss files; run python3 tools/kit_sync.py locally"
            )
        if set(same + changed) != expected or len(same) + len(changed) != len(expected):
            raise ValueError("incomplete export plan")
    except Exception as error:
        # Report only the failure class: an export error can name a path outside this folder.
        return FAIL, CHECK_CRASHED.format(error_type="kit_sync", error=f"Read-only export plan failed ({type(error).__name__}).")
    if changed:
        return WARN, KIT_DIVERGED.format(shared=len(expected), different=len(changed), items=", ".join(changed))
    return PASS, f"shared tools that are the same bytes in the kit: {len(expected)} ({kit})"


def c_ignored():
    """Whether the private area stays out of Git: its ignore line is in place, nothing under it is
    tracked, and nothing the commit check refuses is staged."""
    r = sh("git", "rev-parse", "--is-inside-work-tree")
    if r.returncode:
        return SKIP, NOT_GIT
    private = P.tracked_name(P.private_area)
    msgs = []
    try:
        staged = enforce.index_issues(Path(ROOT))
    except Exception as error:
        # The measurement error already names the cause (such as a name that is not UTF-8).
        msgs.append("index privacy measurement failed: {detail}".format(detail=f"{type(error).__name__}: {error}"
                    if str(error) else type(error).__name__))
    else:
        if staged:
            msgs.append("index privacy violation: {issues}".format(issues=", ".join(issue for issue, _ in staged[:6])))
    if sh("git", "check-ignore", "-q", f"{private}/x.md").returncode != 0:
        msgs.append(f"{private}/ is not covered by an ignore rule; put its line back in .gitignore")
    tracked = [line for line in sh("git", "ls-files", "--", f"{private}/").stdout.splitlines() if line]
    if tracked:
        msgs.append("already tracked: {items}".format(items=", ".join(tracked[:4]))
                    + (MORE.format(count=len(tracked) - 4) if len(tracked) > 4 else ""))
    if msgs:
        return FAIL, "\n      ".join(msgs)
    return PASS, f"{private}/ is ignored, and nothing under it is tracked or staged"


# Each check: (id, label, function, needs_git), in the order the rows print. The id names the check
# in --json and wherever one check reads another's result; the label is the name a person sees. A
# row that needs Git is skipped without it, naming the Git row instead.
CHECKS = [
    ("runtime_python",            "runtime · python",                          c_python, False),
    ("runtime_node",              "runtime · node",                            c_node, False),
    ("runtime_codex",             "runtime · codex CLI",                       c_codex, False),
    ("runtime_claude",            "runtime · claude CLI",                      c_claude, False),
    ("runtime_git",               "runtime · git",                             c_git, False),
    ("wiring_root",               "wiring · instance root",                    c_instance_root, False),
    ("wiring_config",             "wiring · config",                           c_config, False),
    ("wiring_transcripts",        "wiring · transcript path",                  c_transcripts, False),
    ("wiring_runtime_transcripts","wiring · other runtimes' transcripts",      c_runtime_transcripts, False),
    ("wiring_state",              "wiring · state/",                           c_state, False),
    ("wiring_now",                "wiring · NOW.md",                           c_now, False),
    ("hooks_claude_wiring",       "hooks · claude wiring",                     c_hook_wiring, False),
    ("hooks_codex_wiring",        "hooks · codex wiring",                      c_hook_wiring_codex, False),
    ("hooks_agy_wiring",          "hooks · agy wiring",                        c_hook_wiring_agy, False),
    ("hooks_codex_armed",         "hooks · codex armed",                       c_hook_codex_armed, False),
    ("hooks_agy_armed",           "hooks · agy armed",                         c_hook_agy_armed, False),
    ("hooks_codex_command",       "hooks · codex command validity",            c_hook_codex_run, True),
    ("hooks_claude_command",      "hooks · claude command validity",           c_hook_success, False),
    ("hooks_failure_branch",      "hooks · failure branch",                    c_hook_failure, False),
    ("hooks_error_log",           "hooks · error log",                         c_hook_errors, False),
    ("hooks_precompact_claude",   "hooks · PreCompact claude",                 c_precompact_claude, False),
    ("hooks_precompact_codex",    "hooks · PreCompact codex",                  c_precompact_codex, True),
    ("hooks_precompact_fired",    "hooks · PreCompact fired in a real session",c_precompact_journal, False),
    ("hooks_global_time",         "hooks · claude global time",                c_global_hook, False),
    ("hooks_git",                 "hooks · Git hook installation",             c_precommit_install, True),
    ("tools_run",                 "tools · execution",                         c_tools_run, False),
    ("tools_links",               "tools · link integrity",                    c_links, True),
    ("tools_skills",              "tools · skills",                            c_skills, False),
    ("tools_coherence",           "tools · coherence",                         c_coherence, False),
    ("tools_projects",            "tools · projects",                          c_projects, False),
    ("wiring_config_paths",       "wiring · config paths",                     c_config_paths, False),
    ("tools_receipts",            "tools · worker receipts",                   c_worker_receipts, False),
    ("tools_recall",              "tools · recall sources",                    c_recall, False),
    ("tools_context",             "tools · fixed session context",             c_context_budget, False),
    ("workspace_growth",          "workspace · growth",                        c_workspace_growth, False),
    ("tools_ledger",              "tools · ledger",                            c_ledger, False),
    ("tools_person_ledger",       "tools · person ledger",                     c_person_ledger, False),
    ("boundary_model_send",       "boundary · model send",                     c_egress, False),
    ("boundary_untracked",        "boundary · private data untracked",         c_ignored, True),
    ("boundary_symlinks",         "boundary · tracked symlinks",               c_symlinks, True),
    ("gate_unchecked",            "gate · output check omitted",               c_missed_gate, True),
    ("rules_agents",              "rules · AGENTS single authority",           c_agents_parity, False),
    ("engine_schema",             "engine · config schema",                    c_schema, False),
    ("engine_upstream",           "engine · upstream",                         c_upstream, True),
    ("engine_kit_drift",          "engine · kit drift",                        c_engine_drift, False),
]
LABELS = {check_id: label for check_id, label, _fn, _git in CHECKS}

# These capabilities require human verification and are not automated PASS results.
def _manual_items():
    # A manual item is listed only when the user can act on it here: the canary names only the
    # runtimes installed, and the Codex rules check needs Codex.
    installed = [name for name in ("claude", "codex") if shutil.which(name)]
    items = []
    if installed:
        flag = {("claude", "codex"): " --all", ("claude",): " --claude", ("codex",): ""}
        items.append(("Are the SessionStart dispatcher and model effect actually connected?", MANUAL_SESSION_HOW.format(runtimes=" + ".join(installed), command="python3 tools/hook_canary.py" + flag[tuple(installed)])))
    if "codex" in installed:
        items.append(("Does Codex read AGENTS.md and follow its rules?", MANUAL_CODEX_HOW))
    return items


def _manual():
    """List the capabilities that still need a person to verify them, built per run."""
    return _manual_items()


# The names a person knows the runtimes by; a canary covers only the first two.
RUNTIME_NAMES = {"claude": "Claude Code", "codex": "Codex", "agy": "Antigravity"}
CANARY_FLAG = {("claude", "codex"): " --all", ("claude",): " --claude", ("codex",): ""}
NOT_CHECKED = (
    "Not checked by doctor: whether {names} actually {verb} these hooks in a live session (doctor "
    "checked the commands outside a session). Verify once in a real session (system/CHECKLIST.md section "
    "C){canary}."
)
CANARY_CLAUSE = " or run python3 tools/hook_canary.py{flag} (makes live model calls)"
FAIL_FIRST = "Fix the failures above first. Until then, do not trust this instance's state automation."
ALL_POINTER = "Run python3 tools/doctor.py --all for every row."


def _plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def _verdict(n):
    """The first line's verdict: ok, or the failures and warnings counted."""
    parts = [_plural(n[FAIL], "failure")] if n[FAIL] else []
    parts += [_plural(n[WARN], "warning")] if n[WARN] else []
    return ", ".join(parts) or "ok"


def _counts(n):
    """The passed and not-applicable counts; a count that is zero is left out."""
    parts = [f"{_plural(n[PASS], 'check')} passed"] if n[PASS] else []
    parts += [f"{n[SKIP]} did not apply"] if n[SKIP] else []
    return ", ".join(parts) + "." if parts else ""


def not_checked():
    """The limit sentence, or None: names each installed runtime without a fresh passing canary."""
    unproven = [r for r in RUNTIME_NAMES if shutil.which(r) and not _canary_record(r)[2]]
    if not unproven:
        return None
    names = [RUNTIME_NAMES[r] for r in unproven]
    names = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    coverable = tuple(r for r in unproven if r in ("claude", "codex"))
    canary = CANARY_CLAUSE.format(flag=CANARY_FLAG[coverable]) if coverable else ""
    return NOT_CHECKED.format(names=names, verb="fires" if len(unproven) == 1 else "fire", canary=canary)


def _print_attention():
    """The default form: FAIL rows, then warn rows, each with its detail."""
    for status, word in ((FAIL, "FAIL"), (WARN, "warn")):
        for done, check_id, detail in results:
            if done == status:
                print(f"\n{word}  {LABELS[check_id]}: {detail}")


def _print_all(manual):
    """The --all form: every row in a table, then what cannot be automated."""
    width = max(len(LABELS[check_id]) for _, check_id, _ in results)
    icon = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn ", SKIP: "  --  "}
    print()
    for status, check_id, detail in results:
        line = f"[{icon[status]}] {LABELS[check_id].ljust(width)}"
        if detail:
            line += f"  {detail}"
        print(line)
    if manual:
        print(f"\n{len(manual)} check(s) cannot be automated (human verification required):")
    for i, (title, how) in enumerate(manual, 1):
        print(f"  {i}. {title}")
        print(f"     {how}")


def _json_payload(n, manual):
    return {
        "checks": [
            {"id": check_id, "name": LABELS[check_id], "status": status, "detail": detail}
            for status, check_id, detail in results
        ],
        "summary": {
            "total": len(results),
            "pass": n[PASS],
            "fail": n[FAIL],
            "warn": n[WARN],
            "skip": n[SKIP],
        },
        "manual": [{"name": title, "detail": how} for title, how in manual],
    }


def main():
    results.clear()
    for check_id, _label, fn, needs_git in CHECKS:
        check(check_id, fn, needs_git)
    n = {s: sum(1 for st, _, _ in results if st == s) for s in (PASS, FAIL, WARN, SKIP)}
    manual = _manual()
    if JSON_OUTPUT:
        print(json.dumps(_json_payload(n, manual), ensure_ascii=False, indent=2))
    else:
        print(f"doctor: {_verdict(n)} · {ROOT}")
        if ALL_OUTPUT:
            _print_all(manual)
        else:
            _print_attention()
        if n[FAIL] and ALL_OUTPUT:
            print("\n" + FAIL_FIRST)
        limit = None if ALL_OUTPUT else not_checked()
        if limit:
            print("\n" + limit)
        counts = _counts(n)
        tail = counts if ALL_OUTPUT else " ".join(x for x in (counts, ALL_POINTER) if x)
        print(("\n" if (n[FAIL] or n[WARN] or limit or ALL_OUTPUT) else "") + tail)

    runlog.log_run("doctor", f"fail={n[FAIL]} warn={n[WARN]}")
    return 1 if n[FAIL] else 0


if __name__ == "__main__":
    # Parsed here, not at import, so --help prints usage before any check runs or anything is
    # logged. No abbreviations: a mistyped flag is refused, not read as another.
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag, text in (("all", "print every row, and the checks only a person can make"),
                       ("json", "print the results as one JSON object"),
                       ("no-runtimes", "leave out the rows that start a runtime program (codex, agy)")):
        parser.add_argument("--" + flag, action="store_true", help=text)
    args = parser.parse_args()
    JSON_OUTPUT, NO_RUNTIMES, ALL_OUTPUT = args.json, args.no_runtimes, args.all
    sys.exit(main())
