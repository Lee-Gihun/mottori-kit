#!/usr/bin/env python3
"""Block a turn end or a commit on issues the recorded baseline does not hold.

Each checker prints stable-id<TAB>message rows and a final `#issues N` line (--issues); IDs that
start with ~ are advisory and never block. A finding exits zero and a failed measurement nonzero;
a missing or inconsistent trailer is a failure too. An issue the baseline lacks blocks, and so do
a checker that failed and a checker removed from the list. Fixed issues tighten the baseline;
only `gate.py baseline` adopts new ones, keeping the file it replaced for undo.

The same checkers (linkcheck, now-check) judge every turn end (check) and every commit
(precommit, after enforce.py's staged privacy check). When sessions share a folder, a Stop leaves
the issues of another session's work to that session (_others_work). Local hooks cannot prevent
--no-verify.

Commands: dirty, check, resume, precommit, baseline, manual-check, status (also with no argument).
"""
import collections
import contextlib
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import adopted
import config as C
import hook_input
import paths as P
import runlog
import safeio

# Messages this module prints in more than one place, or too long to read inline.
# A block on new issues is NEW_ISSUES with one tail: the general one, or one of the two for links
# in Markdown Git does not track, which `gate.py baseline` never measures.
NEW_ISSUES = "Issues absent before this turn appeared: {detail}. {tail}"
TAIL_ANY = (
    "Fix them before finishing. If intentional, run `python3 tools/gate.py baseline`; it keeps "
    "the replaced baseline as state/.gate-baseline.prev.json."
)
# State-check issues that mean the installation itself is incomplete. No baseline holds them, so
# a turn end stays blocked until the config is back.
NEVER_ACCEPTED = frozenset(("config-absent", "config-legacy-layout"))
TAIL_INCOMPLETE = (
    "The installation is incomplete, and `python3 tools/gate.py baseline` does not accept that. "
    "Put instance/config.json back, or run `bash setup.sh --force`, which keeps the settings "
    "that are left."
)
BASELINE_INCOMPLETE = (
    "cannot set the baseline: the installation is incomplete ({items}). Put instance/config.json "
    "back, or run `bash setup.sh --force`, which keeps the settings that are left"
)
UNTRACKED_END = (
    " If you leave it as it is, the next Stop passes and the file is checked again when it is "
    "next edited."
)
TAIL_LEFT = (
    "They are links in Markdown that Git does not track, edited in this folder by a session that "
    "did not finish checking them, so `python3 tools/gate.py baseline` cannot accept them. Fix "
    "the link before finishing if it is yours to fix." + UNTRACKED_END
)
TAIL_EDITED = (
    "They are links in Markdown this turn edited that Git does not track, which `python3 "
    "tools/gate.py baseline` cannot accept. Fix the link before finishing." + UNTRACKED_END
)
# The same block for a file in a folder nobody adopted: the link may be older than this turn, and
# only the folder's owner-side record can say so.
TAIL_EDITED_UNADOPTED = (
    "They are links in Markdown this turn edited that Git does not track, which `python3 "
    "tools/gate.py baseline` cannot accept. Fix the link before finishing. If the link was "
    "already broken when its folder was brought into the workspace, `python3 tools/adopt.py "
    "FOLDER` records that folder's broken links as known." + UNTRACKED_END
)
BASELINE_ABSENT = (
    "Gate baseline is absent. The machine cannot distinguish deletion from first installation, "
    "so it will not adopt automatically. Run `python3 tools/gate.py baseline` yourself."
)
BASELINE_CORRUPT = (
    "Gate baseline is corrupt ({path}). Inspect it and run `python3 tools/gate.py baseline`."
)
CHECKER_DEAD = (
    "Checkers produced no result: {items}. Unmeasurable is not a pass; determine what failed."
)
CHECKS_CHANGED = (
    "Checker list differs from baseline; {only_base}. This would allow bypass by deleting a "
    "checker. Explicitly migrate with `gate.py baseline`."
)
COUNT = "{name} {count}"
EDIT_NO_LOCK = (
    "[gate] edit not recorded: another check held the gate lock; {path} is checked at the next "
    "Stop unless Git ignores it"
)
LOCK_BLOCK = "Could not acquire the gate lock. Another check is running or the lock remains."
# Rule 1 of AGENTS.md: a turn that changed a frozen path with an edit tool stops once. The edit
# list is dropped when this Stop judges it, so the next Stop judges only later edits.
FROZEN_BLOCK = (
    "This turn changed {paths}, under a path that `frozen` in instance/config.json lists as read "
    "only (rule 1 in AGENTS.md). Unless the owner asked for this change in this conversation, put "
    "it back as it was (`git checkout -- PATH` for a file Git tracks) and tell the owner what "
    "happened."
)
FROZEN_SHOWN = 5
# An installation's own state checks (tools/now_instance.py) may report work that waits outside any
# turn, such as files a pipeline has not processed yet; checks.waiting in instance/config.json lists
# their issue prefixes. A set of such issues stops a turn once; the same set or a part of it never stops
# a turn again, and each prompt says the items are waiting (KIT-DR-089).
WAITING_CHECKER = "now-check"
WAITING_TAG = "waiting\t"
WAITING_ONCE = (
    "These are items that wait for work outside this turn, which no edit in it can clear, so the "
    "turn-end check stops only this once; the same set will not stop a turn again, and each prompt "
    "says they are waiting."
)
RESUME_WAITING = (
    "[gate] Items are waiting for work outside the turns: {detail}. They do not block; "
    "`python3 tools/gate.py status` lists them."
)
MEASURE_FAILED = "{name} measurement failed"
RESUME_OTHER = (
    "[gate] Another session on this folder left a check failing. It is not from this "
    "conversation and does not block it. {reason}"
)
RESUME_SELF_FAILED = (
    "[gate] The gate itself failed ({error_type}). Verification status for the previous turn "
    "is unknown. Run `python3 tools/gate.py status`."
)
RESUME_UNKNOWN = (
    "The reason was not recorded; the next Stop rechecks it, or run `python3 tools/gate.py "
    "status`."
)
ROOT_BLOCK = (
    "Gate execution root differs from the tool location ({root} vs {tool}). Check whether "
    "MOTTORI_INSTANCE is set."
)
RUN_ROOT_MISMATCH = "run root mismatch: instance root={root} vs tool location={self_root}"
SELF_FAILED = (
    "The gate itself failed ({error_type}). Repair the checker or inspect the cause with "
    "`python3 tools/gate.py status`."
)

# Bind execution to this file's root; an environment override must not redirect validation to a
# clean clone.
SELF_ROOT = os.path.dirname(HERE)

BASELINE = P.gate_baseline()
# The file `gate.py baseline` replaced, kept so an unwanted adoption can be undone by copying it back.
BASELINE_PREV = P.gate_baseline_prev()

# linkcheck's --session leaves out the contributor folders a running instance never reads and
# makes a path-shaped code span naming a missing file advisory.
CHECKS = [
    ("linkcheck", [sys.executable, os.path.join(HERE, "linkcheck.py"), "--issues", "--session"]),
    ("now-check", [sys.executable, os.path.join(HERE, "now.py"), "check", "--issues"]),
]
# Checkers this gate once ran. A baseline saved while they ran still names them, so reading drops
# their entries: otherwise that file would block every commit as a checker removed from CHECKS.
RETIRED_CHECKERS = ("evidencecheck", "manifest")
# Edited Markdown under these folders is private, generated or scratch, so its links are not checked.
EDITED_SKIP = ("_private/", "state/", "tmp/")
# Another session's edit entry this old belongs to a session that died mid-turn. A live turn rarely
# goes an hour without an edit, and an expired entry only restores the single-session rule.
EDIT_TTL_NS = 3600 * 10**9
CAUSE_LIMIT = 300


def _root_ok():
    return os.path.realpath(P.instance_root()) == os.path.realpath(SELF_ROOT)




# Edits since each session's last Stop: JSON {session id: {"t": last edit in ns, "files": paths}}.
EDITS = lambda: P.marker("mottori-gate-dirty")
# A blocked check remains pending until revalidated: JSON {session id: {"reason", "ids",
# "notified"}}, where notified lists the other sessions already shown that block.
PENDING = lambda: P.marker("mottori-gate-pending")
# The waiting sets that have already stopped a turn once, as a JSON list of "checker<TAB>issue".
ESCALATED = lambda: P.marker("mottori-gate-escalated")
LOCK = lambda: P.marker("mottori-gate-lock")


@contextlib.contextmanager
def _lock(timeout=150):
    """Serialize dirty marking, measurement, and baseline updates so a concurrent edit cannot
    lose its pending marker.
    """
    lock = safeio.locked(LOCK(), timeout=timeout)
    try:
        lock.__enter__()
    except safeio.StateLockTimeout:
        yield False
        return
    try:
        yield True
    finally:
        lock.__exit__(None, None, None)


@dataclasses.dataclass
class Measurement:
    """What measure() found. ids holds the issue IDs per checker, None for a checker that failed,
    whose one-line cause is in causes (the output tails stay on stderr). advisory holds the link
    issues that are path-shaped code spans: never a reason to block, and kept
    in the baseline only when it already held them (see _gated). edited_only holds the link issues
    only the edited-Markdown list found: they sit in files Git does not track, which `gate.py
    baseline` never measures, so a block must not offer it as the way to accept them. messages
    holds the message each issue ID carried; a now-check ID alone says neither what changed nor
    what to run, so a block reason repeats its row.
    """
    ids: dict
    advisory: frozenset = frozenset()
    edited_only: frozenset = frozenset()
    # Adopted link issues whose file was measured this turn and no longer has them: repaired, so
    # the record stops excusing them (cmd_check retires them; nothing else writes).
    repaired_adopted: frozenset = frozenset()
    causes: dict = dataclasses.field(default_factory=dict)
    messages: dict = dataclasses.field(default_factory=dict)


# One checker's run: its gated issue IDs (None when the measurement failed, cause then says
# why), its advisory (~) IDs without the prefix, and {issue ID: message}.
Checked = collections.namedtuple("Checked", "ids advisory messages cause",
                                 defaults=(frozenset(), None, None))


def _measurement_failure(reason, *outputs):
    """Print the failure and bounded subprocess tails on stderr; return the one-line cause."""
    print("[gate] " + reason[:1000], file=sys.stderr)
    for output in outputs:
        if output:
            text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output
            print(" | ".join(text.strip().splitlines()[-12:])[-4000:], file=sys.stderr)
    return reason[:CAUSE_LIMIT]


def _issues(cmd, cwd=None, instance=None, unpin_git=False):
    """Run one checker and return its Checked.

    unpin_git drops the commit hook's Git pinning, for a checker that runs Git in another tree.
    """
    env = dict(_unpinned_git_env() if unpin_git else os.environ, MOTTORI_INTERNAL_RUN="1")
    if instance is None:
        env.pop("MOTTORI_INSTANCE", None)
    else:
        env["MOTTORI_INSTANCE"] = instance
    label = "<checker>"
    try:
        label = os.path.basename(cmd[1] if len(cmd) > 1 else cmd[0])
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or P.instance_root(), env=env, timeout=120)
    except subprocess.TimeoutExpired as error:
        return Checked(None, cause=_measurement_failure(
            f"checker timed out: {label}: {error.timeout}s", error.stdout, error.stderr))
    except Exception as error:
        return Checked(None, cause=_measurement_failure(
            f"checker could not run: {label}: {type(error).__name__}: {error}"))
    if r.returncode != 0:
        # Findings still exit zero in machine-protocol mode.
        return Checked(None, cause=_measurement_failure(
            f"checker exited nonzero: {label}: exit={r.returncode}", r.stdout, r.stderr))
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines or not lines[-1].startswith("#issues "):
        # The trailer must be the final output line.
        return Checked(None, cause=_measurement_failure(
            f"checker missing final issue trailer: {label}", r.stdout, r.stderr))
    try:
        declared = int(lines[-1].split()[1])
    except (IndexError, ValueError):
        return Checked(None, cause=_measurement_failure(
            f"checker malformed issue trailer: {label}", r.stdout, r.stderr))
    ids = {l.split("\t", 1)[0] for l in lines[:-1]}
    gated = {i for i in ids if not i.startswith("~")}
    if declared != len(gated):
        return Checked(None, cause=_measurement_failure(
            f"checker issue count mismatch: {label}: declared={declared} actual={len(gated)}",
            r.stdout, r.stderr))
    return Checked(gated, frozenset(i[1:] for i in ids if i.startswith("~")),
                   dict(l.split("\t", 1) for l in lines[:-1] if "\t" in l))


# Variables that pin Git to one repository, worktree, index, or object store.
_GIT_PINNING_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX")


def _unpinned_git_env():
    """Return the environment without Git pinning variables, so Git resolves from its cwd."""
    return {k: v for k, v in os.environ.items() if k not in _GIT_PINNING_ENV}


def _checker_command(name, tree, filelist, repair):
    """Return (command, cwd, instance) for one checker. cwd None is the instance root and
    instance None leaves MOTTORI_INSTANCE unset. On an extracted staged tree the staged checker
    judges the staged files, while the live instance supplies config and ignored local data."""
    if not tree:
        # Only the Stop check may re-render a snapshot a new day made stale; status and baseline
        # stay read-only and still show what blocked.
        repair_flag = ["--repair"] if name == "now-check" and repair else []
        return dict(CHECKS)[name] + repair_flag, None, None

    if name == "linkcheck":
        listed = ["--filelist", filelist] if filelist else []
        return ([sys.executable, os.path.join(tree, "tools", "linkcheck.py"), "--issues", "--session",
                 "--tree", tree] + listed, tree, P.instance_root())
    # An installed kit's tree holds no config or state; they come from the live instance.
    instance = tree if os.path.isfile(P.config_file(tree)) else P.instance_root()
    return [sys.executable, os.path.join(tree, "tools", "now.py"), "check", "--issues",
            "--portable"], instance, instance


def _record(out, name, checked):
    """Put one checker's run into a Measurement; a link check's advisory IDs join its set."""
    out.messages.update(checked.messages or {})
    if checked.ids is None:
        out.ids[name] = None
        out.causes[name] = checked.cause or "no result"
        return
    out.ids[name] = set(checked.ids)
    if name == "linkcheck":
        out.advisory |= checked.advisory
        out.ids[name] |= checked.advisory


def _measure_edited(out, edited):
    """Add the link issues of edited Markdown that Git does not list (a kit instance ignores the
    user's own documents), read through an explicit file list; a deleted file has no links."""
    present = [p for p in edited if os.path.isfile(os.path.join(P.instance_root(), p))]
    listed = out.ids.get("linkcheck")
    if not present or listed is None:
        return
    command = dict(CHECKS)["linkcheck"]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as listing:
        listing.write("".join(p + "\n" for p in present))
    try:
        _record(out, "linkcheck", _issues(command + ["--filelist", listing.name]))
    finally:
        os.remove(listing.name)
    if out.ids["linkcheck"] is not None:
        # A link that was already broken when its folder was adopted is not this turn's issue.
        known = adopted.issue_ids()
        out.edited_only = frozenset(out.ids["linkcheck"] - listed - known)
        found = set(out.ids["linkcheck"])
        out.repaired_adopted = frozenset(i for i in known if i.split(" -> ", 1)[0] in present and i not in found)
        out.ids["linkcheck"] = set(out.edited_only) | listed


def measure(tree=None, filelist=None, repair=False, edited=()):
    """Run the checkers and return a Measurement. tree is an extracted staged tree to judge
    instead of the live one; edited names Markdown this session edited, read even when Git does
    not list it."""
    out = Measurement({})
    for name, _ in CHECKS:
        command, cwd, instance = _checker_command(name, tree, filelist, repair)
        # Checkers on an extracted tree run Git there or on the live root, never through the
        # index or repository a commit hook pinned.
        _record(out, name, _issues(command, cwd=cwd, instance=instance, unpin_git=bool(tree)))
    if edited and not tree:
        _measure_edited(out, edited)
    return out


def _load_baseline():
    """Return (issue-set mapping, state), where state is ok, absent, or corrupt."""
    if not os.path.exists(BASELINE):
        return {}, "absent"
    try:
        with open(BASELINE, encoding="utf-8") as source:
            raw = json.load(source)
        if not isinstance(raw, dict) or not raw:
            return {}, "corrupt"
        if raw.get("schema_version") == 3:
            # The sealed form an install of the last release wrote: its issue set is read and the
            # seal ignored; the next save writes the plain form.
            raw = raw.get("issues")
            if not isinstance(raw, dict):
                return {}, "corrupt"
        # A string value would otherwise be split into characters.
        if not all(isinstance(v, list) and all(isinstance(i, str) for i in v)
                   for v in raw.values()):
            return {}, "corrupt"
        return {k: set(v) for k, v in raw.items() if k not in RETIRED_CHECKERS}, "ok"
    except Exception:
        return {}, "corrupt"


def _save_baseline(cur):
    safeio.atomic_write(BASELINE, json.dumps({k: sorted(v) for k, v in cur.items()},
                                             ensure_ascii=False, indent=0))


def _gated(cur, base):
    """Return the issue IDs of a Measurement the baseline may follow. An advisory code span the
    baseline does not hold is left out, so it neither blocks nor keeps a fixed link from
    tightening the baseline, and a later Stop that saves the baseline never adopts it.
    """
    advisory = cur.advisory - (base.get("linkcheck") or set())
    return {k: v - advisory if k == "linkcheck" and v is not None else v for k, v in cur.ids.items()}


def _verdict(cur, base, state, mine=None, known=None):
    """Return (blocking reason or None, whether to tighten the baseline) for a Measurement. Never
    adopt new issues. mine names the files this session edited; None means every edit is its own. known
    ({checker: issue IDs}) holds issues judged as known here though the baseline lacks them;
    while one of them is present the baseline is not saved, so it is never adopted.
    """
    dead = sorted(k for k, v in cur.ids.items() if v is None)
    if dead:
        items = ", ".join(f"{k} ({cur.causes[k][:CAUSE_LIMIT]})" if cur.causes.get(k) else k for k in dead)
        return CHECKER_DEAD.format(items=items), False
    if state == "corrupt":
        return BASELINE_CORRUPT.format(path=BASELINE), False
    if state == "absent":
        # Before setup a folder has no baseline by construction: a turn there is not judged.
        return (None if C.not_set_up() else BASELINE_ABSENT), False
    only_b = sorted(set(base) - set(cur.ids))
    if only_b:
        # Removing a checker must not erase its findings.
        return CHECKS_CHANGED.format(only_base="baseline only: {items}".format(items=", ".join(only_b))), False
    # A new checker starts with an empty baseline: all its findings are new, while zero findings
    # can be recorded safely.
    grown = sorted(set(cur.ids) - set(base))
    # An incomplete installation is never known, whatever an earlier baseline file holds.
    base = {k: set(base.get(k, ())) - (NEVER_ACCEPTED if k == "now-check" else set()) for k in cur.ids}

    ids = _gated(cur, base)
    unknown = {k: ids[k] - base[k] for k in ids}
    new = {k: _shown(k, sorted(v - (known or {}).get(k, set())), cur.messages)
           for k, v in unknown.items()}
    new = {k: v for k, v in new.items() if v}
    if new:
        detail = " · ".join(f"{k}: " + "; ".join(v[:4])
                            + (f" {(len(v)-4)} more" if len(v) > 4 else "")
                            for k, v in new.items())
        untracked = set(new) == {"linkcheck"} and set(new["linkcheck"]) <= cur.edited_only
        tail = TAIL_INCOMPLETE if NEVER_ACCEPTED & set(unknown.get("now-check", ())) else TAIL_ANY
        if untracked:
            # A session that edited none of these files is told who did, not that it did.
            left = mine is not None and not any(i.split(" -> ", 1)[0] in mine
                                                for i in new["linkcheck"])
            known_folder = all(adopted.covers(i.split(" -> ", 1)[0]) for i in new["linkcheck"])
            tail = TAIL_LEFT if left else TAIL_EDITED if known_folder else TAIL_EDITED_UNADOPTED
        return NEW_ISSUES.format(detail=detail, tail=tail), False

    if any(unknown.values()):
        return None, False
    shrank = (all(ids[k] <= base[k] for k in ids) and any(ids[k] < base[k] for k in ids))
    return None, shrank or bool(grown)


def _waiting(checker, issue_id):
    """Whether an issue is waiting work (checks.waiting), which stops a turn only once."""
    prefixes = C.waiting_prefixes()
    return checker == WAITING_CHECKER and bool(prefixes) and issue_id.startswith(prefixes)


def _waiting_counts(issue_ids):
    """Count waiting issue IDs per prefix; their names can be long file names."""
    return [f"{prefix.rstrip(':')}: {n} waiting" for prefix in C.waiting_prefixes()
            for n in [sum(1 for i in issue_ids if i.startswith(prefix))] if n]


def _shown(checker, issue_ids, messages):
    """The issue IDs a block reason shows: a state-check issue with its message, waiting ones as counts."""
    if checker != WAITING_CHECKER:
        return issue_ids
    plain = [i for i in issue_ids if not _waiting(checker, i)]
    return ([f"{i} ({messages[i]})" if messages.get(i) else i for i in plain]
            + _waiting_counts([i for i in issue_ids if _waiting(checker, i)]))


def _new_ids(cur, base):
    """{checker: sorted new issue IDs} of a Measurement against base; a failed checker has none."""
    new = {k: sorted(v - (base.get(k) or set())) for k, v in _gated(cur, base).items() if v is not None}
    return {k: v for k, v in new.items() if v}


def _waiting_new(cur, base, state):
    """The new issues as "checker<TAB>issue" when every one of them is waiting work; otherwise None.
    A failed checker, a baseline that is not ok and a removed checker always stop the turn."""
    if state != "ok" or any(v is None for v in cur.ids.values()) or set(base) - set(cur.ids):
        return None
    new = [f"{k}\t{i}" for k, ids in _new_ids(cur, base).items() for i in ids]
    if not new or not all(_waiting(*x.split("\t", 1)) for x in new):
        return None
    return sorted(new)


def _escalated():
    try:
        value = json.loads(_read(ESCALATED()) or "[]")
        return set(value) if isinstance(value, list) else set()
    except (ValueError, TypeError):
        return set()


def _record_verdict(kind, session, cur=None, base=None, reason=None):
    """Hand a verdict to the installation's own tools/gate_instance.py, if it has one; the kit ships
    none. kind is pass, block, waiting (a waiting set passed), repeat (a turn end that already stopped
    once in its turn) or warn (a prompt repeated a block). Nothing that module does fails the gate."""
    try:
        import gate_instance
    except ImportError:
        return
    with contextlib.suppress(Exception):
        new = _new_ids(cur, base or {}) if cur is not None and kind != "pass" else None
        gate_instance.record(kind, session=session or None, new=new, reason=reason)


def _counts(ids):
    """Return "name N" per checker joined by " · ", or "name measurement failed" for one that failed."""
    return " · ".join(MEASURE_FAILED.format(name=k) if v is None else COUNT.format(name=k, count=len(v))
                      for k, v in ids.items())


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def _mark(p, val="1"):
    # A hook that reads without the lock must see the old or the new marker, never half of one.
    safeio.atomic_write(p, val)


def _edit_entries():
    """Return the edit list as {session id: {"t": last edit in ns, "files": edited paths}}."""
    return _json_entries(EDITS())


def _json_entries(path):
    """Return a marker's {session id: entry} mapping; a missing file or any other content (a
    hand edit, or the plain text the last release wrote) holds no entry."""
    with contextlib.suppress(ValueError, TypeError):
        entries = json.loads(_read(path))
        if isinstance(entries, dict) and all(isinstance(e, dict) for e in entries.values()):
            return entries
    return {}


def _files(entry):
    files = entry.get("files")
    return [f for f in files if isinstance(f, str)] if isinstance(files, list) else []


def _live(entry, now):
    stamp = entry.get("t")
    return isinstance(stamp, int) and now - stamp < EDIT_TTL_NS


def _own(sid, key):
    """Whether an entry is this session's; a run without a session id owns every entry."""
    return not sid or key in (sid, "")


def _edited_markdown(entries):
    """Return the Markdown the edit entries name.

    Private, generated and scratch folders stay out.
    """
    out = []
    for entry in entries.values():
        for rel in _files(entry):
            if rel.endswith(".md") and not rel.startswith(EDITED_SKIP) and rel not in out:
                out.append(rel)
    return out


def record_edit(session=None, paths=None, cwd=None):
    """Add the files an edit touched to this session's edit list. A relative path is read from
    cwd (default: the instance root). Without paths the turn is still marked; when every path
    lies outside the instance, nothing is recorded."""
    root = os.path.realpath(P.instance_root())
    sid = session or ""
    rels = []
    for path in paths or ():
        real = os.path.realpath(os.path.join(cwd or P.instance_root(), path))
        if os.path.commonpath([real, root]) == root:
            rels.append(os.path.relpath(real, root))
    if paths and not rels:
        return 0
    # A short wait only, and no write without the lock: a Stop that holds it reads the list once
    # and replaces it, so an unlocked write could be lost or could lose that Stop's update. A
    # tracked file a missed entry names is still seen, since every Stop measures the whole tree.
    with _lock(timeout=2) as got:
        if not got:
            # The hook sends stderr to the hook error log; a leading timestamp is what makes
            # doctor and the session-start notice count the line.
            for rel in rels or ["-"]:
                print(time.strftime("%Y-%m-%dT%H:%M:%S"), EDIT_NO_LOCK.format(path=rel),
                      file=sys.stderr)
            return 0
        # Each session's entry holds the time of its last edit and the files it edited: the Stop
        # link check reads that Markdown even when Git ignores it, and a link in a file only
        # another session is editing is left to that session.
        now = time.time_ns()
        entries = {k: e for k, e in _edit_entries().items() if k in (sid, "") or _live(e, now)}
        files = _files(entries.get(sid, {}))
        files += [rel for rel in dict.fromkeys(rels) if rel not in files]
        entries[sid] = {"t": now, "files": files}
        _mark(EDITS(), json.dumps(entries, ensure_ascii=False))
    return 0


def _drop_judged_edits(sid, entries, now):
    """Remove the edit entries this Stop judged and the other sessions' entries it found expired.

    entries and now are the reading the Stop exempted from, taken under the lock that every
    writer of the list holds, so an entry is either exempted and kept or judged and dropped.
    """
    kept = {k: e for k, e in entries.items() if not _own(sid, k) and _live(e, now)}
    if kept and kept != entries:
        _mark(EDITS(), json.dumps(kept, ensure_ascii=False))
    elif not kept:
        with contextlib.suppress(OSError):
            os.remove(EDITS())


def _cmd_baseline_locked():
    cur = measure().ids
    dead = [k for k, v in cur.items() if v is None]
    if dead:
        print("cannot set the baseline: {reason}".format(reason="checker failed: {checkers}".format(checkers=", ".join(dead))))
        return 1
    incomplete = sorted(NEVER_ACCEPTED & set(cur.get("now-check") or ()))
    if incomplete:
        print(BASELINE_INCOMPLETE.format(items=", ".join(incomplete)))
        return 1
    base, _ = _load_baseline()
    adopted = sorted(f"{checker}:{issue_id}" for checker, ids in cur.items()
                     for issue_id in ids - base.get(checker, set()))
    if os.path.exists(BASELINE):
        # Keep the replaced file so an unwanted adoption can be undone by copying it back.
        shutil.copyfile(BASELINE, BASELINE_PREV)
    # The measurement replaces the whole file, which is how a checker removed from CHECKS is
    # migrated away on purpose.
    _save_baseline(cur)
    for p in (PENDING(), ESCALATED()):
        with contextlib.suppress(OSError):
            os.remove(p)
    suffix = (" · adopted " + ", ".join(adopted) if adopted else "")
    counts = _counts(cur)
    print(f"baseline saved: {counts}{suffix}")
    return 0


def cmd_baseline():
    if not _root_ok():
        print(RUN_ROOT_MISMATCH.format(root=P.instance_root(), self_root=SELF_ROOT), file=sys.stderr)
        return 1
    with _lock() as got:
        if not got:
            print("cannot set the baseline: gate lock not acquired")
            return 1
        return _cmd_baseline_locked()


def cmd_status():
    base, state = _load_baseline()
    cur = measure().ids
    print(f"root      : {P.instance_root()}" + ("" if _root_ok() else f"  (!! does not match tool location {SELF_ROOT})"))
    print(f"dirty     : {os.path.exists(EDITS())}  ({EDITS()})")
    print(f"pending   : {os.path.exists(PENDING())}")
    print(f"baseline  : {state} · {_counts(base)}")
    print(f"current   : {_counts(cur)}")
    for k, v in cur.items():
        for i in sorted(v or [])[:10]:
            print(f"  {k}  {i}")
    return 0


def cmd_manual_check():
    """Judge the tree as the turn-end check would and write nothing; exit 0 PASS, 1 BLOCK, 2 UNCHECKED.

    For a runtime whose turn-end hook does not run. It reads the edit list so ignored Markdown a
    session edited is checked too, but clears no edit entry and no session's block and never
    tightens the baseline, so the next Stop judges exactly what it would have judged. With no
    session it judges every issue as its own, as a Stop without a session id does.
    """
    if not _root_ok():
        print("UNCHECKED: " + RUN_ROOT_MISMATCH.format(root=P.instance_root(), self_root=SELF_ROOT))
        return 2
    base, state = _load_baseline()
    cur = measure(edited=_edited_markdown(_edit_entries()))
    # A turn end renders a stale state page before it judges; this command writes nothing, so it
    # leaves that finding out instead of reporting a block the turn end would not give. That holds
    # only when a render can succeed: with a config that does not load, the turn end blocks too.
    stale = {i for i in (cur.ids.get("now-check") or set()) if i.startswith("now-input-newer")}
    if stale and not C.load_ok():
        print("UNCHECKED: the state page is behind its inputs and the config does not load, so the turn "
              "end cannot render it again; fix the config first (python3 tools/doctor.py names the problem)")
        return 2
    if stale:
        cur.ids["now-check"] = cur.ids["now-check"] - stale
        print("note: the state page is behind its inputs; the turn end renders it again before it judges")
    print(f"checks run: {_counts(cur.ids)}")
    reason, _ = _verdict(cur, base, state)
    if reason is None:
        print("PASS")
        return 0
    if state != "ok" or any(v is None for v in cur.ids.values()):
        print("UNCHECKED: " + reason)
        return 2
    print("BLOCK: " + reason)
    return 1


def _pending():
    """Return the pending blocks as {session id: {"reason", "ids", "notified"}}."""
    return _json_entries(PENDING())


def _write_pending(entries):
    if entries:
        _mark(PENDING(), json.dumps(entries, ensure_ascii=False))
    else:
        with contextlib.suppress(OSError):
            os.remove(PENDING())


def _notified(entry):
    return entry.get("notified") if isinstance(entry.get("notified"), list) else []


def _mark_notified(sid, keys):
    """Record that sid has seen these blocks of other sessions.

    Only this write takes the lock, with a short wait: a prompt with nothing new to record must not
    stall behind another session's Stop. A missed write only repeats the notice once more.
    """
    if not keys:
        return
    with _lock(timeout=2) as got:
        if not got:
            return
        entries = _pending()
        for key in keys:
            if key in entries and sid not in _notified(entries[key]):
                entries[key]["notified"] = _notified(entries[key]) + [sid]
        _write_pending(entries)


def _keep_pending(sid, reason, ids=()):
    entries = _pending()
    entries[sid] = {"reason": reason, "ids": sorted(ids)}
    _write_pending(entries)


def _others_work(edits, pending, sid, now, links):
    """Return {checker: issue IDs} this session's Stop judges as known because they are other
    sessions' work; they never enter the baseline.

    Sessions sharing one folder are told apart by the hook payload's session_id, and the edit
    list and the pending marker keep one entry per session. Two kinds of issue are another
    session's: those its pending block holds (it clears them at its own Stop), and a broken link
    whose source document another session edited within EDIT_TTL_NS while this one did not,
    unless this session's own block already holds it. links is the measured link issues. Every
    other issue is judged as if the session were alone, so an issue another session left in a
    state file or through a shell command can still block whichever session ends its turn
    first. A run without a session id owns everything, so nothing is exempt.
    """
    if not sid:
        return {}
    known = {}
    for key, entry in pending.items():
        if key not in (sid, ""):
            for item in entry.get("ids") or ():
                if isinstance(item, str) and "\t" in item:
                    checker, issue = item.split("\t", 1)
                    known.setdefault(checker, set()).add(issue)
    mine = _own_files(edits, sid)
    own_ids = {i for k, e in pending.items() if _own(sid, k) for i in e.get("ids") or ()}
    others_files = {f for k, e in edits.items() if not _own(sid, k) and _live(e, now)
                    for f in _files(e)} - mine
    others_links = {i for i in links or () if i.split(" -> ", 1)[0] in others_files
                    and f"linkcheck\t{i}" not in own_ids}
    if others_links:
        known["linkcheck"] = known.get("linkcheck", set()) | others_links
    return known


def _own_files(edits, sid):
    """Return the files this session's edit entries name."""
    return {f for k, e in edits.items() if _own(sid, k) for f in _files(e)}


def _frozen_hits(files):
    """Return, sorted, the edited paths that are a frozen path or lie under one."""
    roots = C.frozen()
    return sorted(f for f in files if any(f == r or f.startswith(r + "/") for r in roots))



def cmd_check(session=None, continuing=False):
    """Judge a turn end (the Stop step): block on issues the baseline does not hold.

    Every Stop measures the files Git lists and the Markdown the turn edited with an edit tool; a
    shell edit or rename of a file Git ignores is not seen. A block
    reason stays pending, so the next prompt repeats it (cmd_resume) and the next Stop measures
    again. continuing is the runtime's hint that a turn end already stopped this turn.
    """
    reentrant = continuing is True
    sid = session or ""

    def reentrant_pass(reason=None):
        # The dispatcher's turns.block_once already sends a finding once per turn; this pass
        # stays for a direct `gate.py check`, which has no turn record. A lasting gate fault would
        # block every retry, and re-blocking a finding spends the turn without revealing a new
        # one. A finding, a lock timeout or a crash stays in pending, so the next prompt repeats
        # it and the next Stop measures; a root mismatch blocks every first Stop again instead.
        runlog.log_run("gate", "reentrant-pass@Stop", ok=True)
        if reason:
            _record_verdict("repeat", sid, reason=reason)
        return 0

    try:
        if not _root_ok():
            if reentrant:
                return reentrant_pass()
            return _block(ROOT_BLOCK.format(root=P.instance_root(), tool=SELF_ROOT))
        with _lock() as got:
            if not got:
                if reentrant:
                    if sid not in _pending():
                        _keep_pending(sid, LOCK_BLOCK)
                    return reentrant_pass()
                return _block(LOCK_BLOCK)
            reason = _judge_turn(sid)
        if not reason:
            return 0
        if reentrant:
            return reentrant_pass(reason)
        runlog.log_run("gate", "blocked@Stop")
        return _block(reason)
    except Exception as e:
        # Treat gate exceptions as failed measurement and retain pending state.
        with contextlib.suppress(Exception):
            _keep_pending(sid, SELF_FAILED.format(error_type=type(e).__name__))
        with contextlib.suppress(Exception):
            runlog.log_run("gate", f"error@Stop:{type(e).__name__}")
        if reentrant:
            return reentrant_pass()
        return _block(SELF_FAILED.format(error_type=type(e).__name__))


def _judge_turn(sid):
    """Measure under the gate lock, update the baseline, the edit list and the pending marker,
    and return the block reason or None."""
    # Every writer of the edit list holds the lock, so this one reading decides both which
    # entries are exempt and which are dropped.
    edits = _edit_entries()
    now = time.time_ns()
    pending = _pending()
    # Taken before measuring, so doctor never credits this pass with a later edit.
    identity = _documents_identity()
    base, state = _load_baseline()
    cur = measure(repair=True, edited=_edited_markdown(edits))
    if cur.repaired_adopted:
        adopted.retire(cur.repaired_adopted)
    judged = base
    known = _others_work(edits, pending, sid, now, cur.ids.get("linkcheck"))
    reason, advance = _verdict(cur, judged, state, _own_files(edits, sid), known)
    frozen = _frozen_hits(_own_files(edits, sid))
    if frozen:
        more = f" and {len(frozen) - FROZEN_SHOWN} more" if len(frozen) > FROZEN_SHOWN else ""
        note = FROZEN_BLOCK.format(paths=", ".join(frozen[:FROZEN_SHOWN]) + more)
        reason = f"{reason}\n{note}" if reason else note
    if advance:
        _save_baseline(_gated(cur, base))
    _drop_judged_edits(sid, edits, now)
    seen = {k: set(v) | known.get(k, set()) for k, v in judged.items()}
    waiting = _waiting_new(cur, seen, state) if reason and not frozen else None

    def keep_pending(text):
        # Keep unresolved failures pending so the next Stop rechecks them, and keep the text so the
        # next prompt can repeat it without measuring. Waiting issues belong to no session.
        _keep_pending(sid, text, (f"{k}\t{i}" for k, v in cur.ids.items() if v
                                  for i in v - seen.get(k, set())
                                  if not _waiting(k, i) and not (k == "linkcheck" and i in cur.advisory)))

    # The next prompt repeats this as items that wait, not as a turn that failed.
    notice = (WAITING_TAG + RESUME_WAITING.format(detail="; ".join(
        _waiting_counts([x.split("\t", 1)[1] for x in waiting]))) if waiting else None)
    if waiting and set(waiting) <= _escalated():
        # A set that has stopped a turn once, or a part of it, passes; clearing one item does not
        # stop the next turn again.
        keep_pending(notice)
        runlog.log_run("gate", "waiting@Stop", ok=True)
        _record_verdict("waiting", sid, cur, seen, reason)
        return None
    if waiting:
        _mark(ESCALATED(), json.dumps(sorted(set(waiting) | _escalated()), ensure_ascii=False))
        reason = reason + " " + WAITING_ONCE
    if reason:
        keep_pending(notice or reason)
        _record_verdict("block", sid, cur, seen, reason)
        return reason
    # Another session's block stays until that session's own Stop measures it.
    _write_pending({k: e for k, e in _pending().items() if sid and k not in (sid, "")})
    with contextlib.suppress(OSError):
        os.remove(ESCALATED())
    # doctor compares this identity with the current documents to tell whether a passing
    # turn-end check saw them.
    runlog.log_run("gate", "pass@Stop", ok=True, scope=identity)
    _record_verdict("pass", sid)
    return None


def _read(p):
    try:
        with open(p, encoding="utf-8") as marker:
            return marker.read()
    except (OSError, UnicodeDecodeError):
        return None


def cmd_resume(session=None):
    """Repeat the last block reason at UserPromptSubmit without measuring or blocking.

    The prompt hook has a short runtime limit and stalls the model while it runs, so measurement
    is left to the next Stop, which still sees the edit list and the pending marker. Another
    session's block is named once per session: this conversation did not cause it and need not
    fix it.
    """
    try:
        if not _root_ok():
            return 0
        sid = session or ""
        failed, others, waiting, notified = [], [], [], []
        for key, entry in _pending().items():
            reason = str(entry.get("reason") or "").strip() or RESUME_UNKNOWN
            mine = not sid or key in (sid, "")
            if not mine and sid in _notified(entry):
                continue
            if reason.startswith(WAITING_TAG.strip()):
                # Items waiting for work outside the turns: nothing failed in any turn.
                waiting.append(reason[len(WAITING_TAG):].strip())
            elif mine:
                failed.append(f"[gate] The previous turn did not pass verification. {reason}")
            else:
                others.append(RESUME_OTHER.format(reason=reason))
            if not mine:
                notified.append(key)
        _mark_notified(sid, notified)
        lines = failed + others + list(dict.fromkeys(waiting))
        if not lines:
            return 0
        runlog.log_run("gate", "resume-warn" if failed else "resume-other" if others else "resume-waiting")
        if failed:
            _record_verdict("warn", None, reason="\n".join(failed))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(lines)}},
            ensure_ascii=False))
        return 0
    except Exception as e:
        with contextlib.suppress(Exception):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": RESUME_SELF_FAILED.format(error_type=type(e).__name__)}},
                ensure_ascii=False))
        return 0


def open_block(session):
    """Return the block the last Stop of this session recorded, {"reason", "ids"}, or {}."""
    return _pending().get(session or "") or {}


def _documents_identity():
    """Return linkcheck's identity of the live Markdown names and bytes, or None if Git fails."""
    # No optional locks: this read must not take git's index lock from a concurrent commit.
    env = dict(_unpinned_git_env(), GIT_OPTIONAL_LOCKS="0")
    try:
        import linkcheck
        listed = subprocess.run(["git", "-C", P.instance_root(), "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard", "*.md"], capture_output=True, env=env,
                                timeout=30)
        if listed.returncode != 0:
            return None
        return linkcheck.scope_hash([os.fsdecode(p) for p in listed.stdout.split(b"\0") if p], P.instance_root())
    except (Exception, SystemExit):
        # A broken checker must surface as the checker's own failure in measure, not end Stop here.
        return None


def _staged_tools_compile(tmp):
    """Check Python syntax in the staged tree rather than a potentially different worktree
    copy. Only the runtime tools, at the top of tools/ and in tools/lib/, are compiled: tests and
    contributor tools are code a running instance never starts, and the suite compiles them.
    """
    import py_compile
    bad = []
    listed = subprocess.run(
        ["git", "-C", P.instance_root(), "ls-files", "-z", "--cached", "tools/*.py"],
        capture_output=True,
    )
    if listed.returncode != 0 or (listed.stdout and not listed.stdout.endswith(b"\0")):
        raise ValueError("staged Python file list measurement failed")
    for raw_path in listed.stdout.split(b"\0"):
        if not raw_path:
            continue
        rel = os.fsdecode(raw_path)
        # The pathspec's * also matches "/", so subfolders are filtered here.
        if "/" in rel[len("tools/"):] and not rel.startswith("tools/lib/"):
            continue
        p = os.path.join(tmp, rel)
        if not os.path.exists(p):
            bad.append(f"{rel}: missing staged file")
            continue
        try:
            py_compile.compile(p, cfile=os.path.join(tmp, ".pyc-scratch"), doraise=True)
        except Exception as e:
            bad.append(f"{rel}: {type(e).__name__}")
    return bad


def _staged_markdown_paths():
    """Read staged Markdown paths without Git's quotePath transformation."""
    listed = subprocess.run(
        ["git", "-c", "core.quotePath=false", "-C", P.instance_root(),
         "ls-files", "-z", "--cached", "*.md"], capture_output=True,
    )
    if listed.returncode != 0 or (listed.stdout and not listed.stdout.endswith(b"\0")):
        raise ValueError("staged Markdown file list measurement failed")
    try:
        paths = [p.decode("utf-8") for p in listed.stdout.split(b"\0") if p]
    except UnicodeDecodeError as error:
        raise ValueError("staged Markdown path is not UTF-8") from error
    if any("\n" in path or "\r" in path for path in paths):
        raise ValueError("newline in staged Markdown path")
    return paths


def cmd_precommit():
    """Check the index that will be committed and fail closed when measurement is incomplete."""
    if not _root_ok():
        print(f"[gate] run root mismatch ({P.instance_root()} vs {SELF_ROOT}). Blocking the commit.", file=sys.stderr)
        return 1
    tmp = tempfile.mkdtemp(prefix="mottori-gate-")
    try:
        r = subprocess.run(["git", "-C", P.instance_root(), "checkout-index", "-a", "--prefix", tmp + "/"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[gate] could not check out the index: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        bad = _staged_tools_compile(tmp)
        if bad:
            print("[gate] Python tools in the index do not compile: {tools}".format(tools=", ".join(bad)), file=sys.stderr)
            print("  Committing broken checkers would disable this gate itself.", file=sys.stderr)
            return 1
        enforce_cmd = [sys.executable, os.path.join(HERE, "enforce.py"),
                       "--issues", "--index", "--root", P.instance_root()]
        # The staged privacy issues: no baseline waives them.
        privacy = _issues(enforce_cmd, cwd=P.instance_root())
        if privacy.ids is None:
            print("[gate] could not measure staged privacy enforcement", file=sys.stderr)
            return 1
        if privacy.ids:
            # An ID alone does not say how to recover, so each one carries its checker message.
            print("[gate] absolute staged violation: {items}".format(items="; ".join(
                f"{i} ({privacy.messages[i]})" if privacy.messages.get(i) else i for i in sorted(privacy.ids)[:8])),
                  file=sys.stderr)
            return 1
        fl = os.path.join(tmp, ".gate-filelist")
        try:
            paths = _staged_markdown_paths()
        except ValueError as error:
            print(f"[gate] could not read the staged Markdown list: {error}", file=sys.stderr)
            return 1
        with open(fl, "w", encoding="utf-8") as filelist:
            filelist.write("".join(path + "\n" for path in paths))

        base, state = _load_baseline()
        cur = measure(tree=tmp, filelist=fl)
        reason, _ = _verdict(cur, base, state)
        if reason:
            print("[gate] " + reason, file=sys.stderr)
            return 1
        runlog.log_run("gate", "precommit-pass", ok=True)
        return 0
    except Exception as e:
        print(f"[gate] the gate itself failed: {e}. Blocking the commit.", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _hook_command(command):
    """Run `gate.py dirty|check|resume` on the hook payload piped in on stdin."""
    payload = hook_input.hook_payload()
    sid = payload.get("session_id")
    sid = sid if isinstance(sid, str) else ""
    if command == "check":
        return cmd_check(sid, payload.get("stop_hook_active") is True)
    if command == "resume":
        return cmd_resume(sid)
    tool_input = payload.get("tool_input")
    path = (tool_input.get("file_path") or tool_input.get("notebook_path")
            if isinstance(tool_input, dict) else None)
    return record_edit(sid, [path] if isinstance(path, str) and path else None,
                       payload.get("cwd") if isinstance(payload.get("cwd"), str) else None)


HELP = """Block a turn end or a commit on issues the recorded baseline does not hold.

usage: python3 tools/gate.py [COMMAND]
  status        show the baseline and today's issues (the default)
  baseline      adopt today's issues as the baseline, keeping the file it replaces for undo
  manual-check  judge the tree as the turn-end check would, writing nothing (for a runtime without that hook)
  check         the turn-end check (used by the Stop hook)
  dirty         record an edited file (used by the edit hook)
  resume        say at a prompt that the last turn did not pass (used by the prompt hook)
  precommit     check what will be committed (used by the Git pre-commit hook)"""


def main():
    if len(sys.argv) < 2:
        return cmd_status()
    cmd = sys.argv[1]
    if cmd in ("-h", "--help"):
        print(HELP)
        return 0
    if cmd == "baseline":
        if len(sys.argv) != 2:
            print("usage: gate.py baseline", file=sys.stderr)
            return 2
        return cmd_baseline()
    commands = {"dirty": lambda: _hook_command("dirty"), "check": lambda: _hook_command("check"),
                "resume": lambda: _hook_command("resume"),
                "precommit": cmd_precommit, "status": cmd_status,
                "manual-check": cmd_manual_check}
    if cmd not in commands:
        # A misspelled hook command must fail loudly instead of running the status display.
        print("usage: gate.py [{commands}]".format(commands=", ".join(["baseline", *commands])), file=sys.stderr)
        return 2
    return commands[cmd]()


if __name__ == "__main__":
    sys.exit(main())
