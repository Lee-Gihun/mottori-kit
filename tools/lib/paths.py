#!/usr/bin/env python3
"""Say where every file the tools read or write lives, as functions of the instance root.

Importing this module reads no file. Each function takes an optional root and otherwise uses
instance_root(); only git_dir(), marker(), journals_in(), state_evidence(), legacy_moves(),
owner_names() and owner_files() look at the disk, and only when called.

Command line (setup.sh uses it):
  python3 tools/lib/paths.py NAME...   Print each named path relative to the instance root, one per
                                   line, a pair as two paths split by a tab; the names are the
                                   keys of SHELL_NAMES."""
import datetime
import os
import re
import subprocess
import sys


def instance_root():
    """Return the instance root every tool reads: MOTTORI_INSTANCE, or the folder above tools/.

    An empty value counts as unset, and ~ and relative paths are expanded once here, so no tool
    can resolve the same setting to a different folder than another."""
    env = os.environ.get("MOTTORI_INSTANCE")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _at(root, *parts):
    return os.path.join(root or instance_root(), *parts)


def _in(folder, *parts):
    """A path function for parts inside the folder that folder(root) returns."""
    return lambda root=None: os.path.join(folder(root), *parts)


def tracked_name(path_of):
    """The path Git records for one of this module's path functions, such as config_file.

    path_of is called with the root "/", so its result relative to "/" is the same path inside
    every instance, written with "/" as Git writes it."""
    return os.path.relpath(path_of("/"), "/").replace(os.sep, "/")


# What one installation owns. Each file starts at setup as the template of the same name.
def instance(root=None):
    return _at(root, "instance")


config_file = _in(instance, "config.json")
rules = _in(instance, "rules.md")
rituals = _in(instance, "rituals.md")
decisions = _in(instance, "decisions.md")
deep_pass_summary = _in(instance, "deep-pass-ledger.md")  # an optional public summary of the ledger
debate = _in(instance, "debate")  # debate rounds and their prompts
config_template = _in(lambda root: _at(root, "templates"), "config.json")


# The owner's projects, one folder each (KIT-DR-093). The kit creates the folder and its README at
# setup and never tracks anything in it.
def projects(root=None):
    return _at(root, "projects")


projects_readme = _in(projects, "README.md")
projects_template = _in(lambda root: _at(root, "templates"), "projects-README.md")
# The installation's policy files; a worker's worktree gets a copy of each.
POLICY_FILES = (config_file, rules, decisions, rituals)


# Each skill's one source folder (skills/<name>/), and the folders the runtimes read copies of it
# from, relative to the instance root.
def skills(root=None):
    return _at(root, "system", "skills")


SKILL_COPIES = (".claude/skills", ".agents/skills")


# The two state folders: state/ is tracked, _private/state/ never leaves this machine.
def state(root=None):
    return _at(root, "state")


def private_area(root=None):
    """The folder that never leaves this machine; every private store is inside it."""
    return _at(root, "_private")


def is_private(path):
    """Whether path lies in a private area or in a Git folder: neither is ever published.

    Judged by the folder names alone, so it holds for any instance root and for a worker's copy."""
    return bool({"_private", ".git"} & set(os.path.abspath(path).split(os.sep)))


private_state = _in(private_area, "state")
private_threads = _in(private_state, "threads.json")


def now_page(scope="public", root=None):
    """The NOW page of one side: "public" (state/NOW.md) or "private" (_private/state/NOW.md)."""
    return os.path.join(state(root) if scope == "public" else private_state(root), "NOW.md")


# Journal files: one per month in each state folder.
JOURNAL_NAME = re.compile(r"journal-\d{4}-\d{2}\.md$")
JOURNAL_GLOB = "journal-*.md"


def journal_name(dt):
    return f"journal-{dt:%Y-%m}.md"


def journal_file(dt=None, visibility="public", root=None):
    """The journal of dt's month (now by default) in the public or the private state folder."""
    dt = dt or datetime.datetime.now()
    folder = state(root) if visibility == "public" else private_state(root)
    return os.path.join(folder, journal_name(dt))


def journals_in(folder):
    """The journal files in one state folder, by name."""
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    return [os.path.join(folder, name) for name in names if JOURNAL_NAME.match(name)]


def state_evidence(root=None):
    """Return the state files present under root that only a running instance writes, relative.

    now.py check and the commit and push checks share this one list, so a tree without its config
    is a damaged instance to all of them or to none."""
    root = str(root or instance_root())
    found = []
    for scope, folder in (("public", state(root)), ("private", private_state(root))):
        found += [now_page(scope, root)] + journals_in(folder)
    found.append(private_threads(root))
    return [os.path.relpath(path, root) for path in found if os.path.isfile(path)]


# Logs, records and generated pages in state/.
journal_lock = _in(state, ".journal.lock")  # serializes journal appends and NOW publication
debate_dispatch_log = _in(state, "debate-dispatch.log")
memory_map = _in(state, "memory-map.html")
build_log = _in(state, "build-log.md")
tool_runs = _in(state, ".tool-runs.log")
hook_errors = _in(state, ".hook-errors.log")
hook_errors_seen = _in(state, ".hook-errors.seen")  # byte offset of the log already reported
deliver_log = _in(state, ".deliver.jsonl")
hook_canary = _in(state, "hook-canary.json")
gate_baseline = _in(state, ".gate-baseline.json")
gate_baseline_prev = _in(state, ".gate-baseline.prev.json")
gate_adopted = _in(state, ".gate-adopted.json")  # link issues adopted folders came in with

# Private stores.
triggers_store = _in(private_area, "triggers", "triggers.jsonl")
notes_store = _in(private_area, "notes", "notes.jsonl")
ledger = _in(private_area, "ledger")  # the fact ledger; its records are in facts/
ledger_facts = _in(ledger, "facts")
ledger_hotset = _in(ledger, "hotset.md")
runs = _in(private_area, "work", "runs")  # worker run records
portrait = _in(private_area, "self-portrait-mirror.md")  # the person ledger person_ledger.py feeds
deep_pass_ledger = _in(private_area, "deep-pass", "ledger.md")  # starts on first use as its template
recall_store = _in(private_state, "recall-store.json")
recall_vectors = _in(private_state, "recall-vectors.bin")
recall_vectors_json = _in(private_state, "recall-vectors.json")  # the earlier format, converted once
recall_queries = _in(private_state, "recall-queries.jsonl")
recall_catch_up = _in(private_state, "recall-catch-up.json")  # the catch-up at session start
recall_codex_meta = _in(private_state, ".recall-codex-meta.json")  # Codex session metadata cache
recall_metrics = _in(private_state, "metrics-recall.jsonl")


def legacy_moves(root=None):
    """The (old, new) pairs of this installation's files still where they were before instance/
    existed, under system/; setup.sh --force moves them."""
    root = root or instance_root()
    system = _at(root, "system")

    def names(folder):
        folder = os.path.join(system, folder)
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    moves = [(old, new(root)) for old, new in (
        ("memory-config.json", config_file), ("instance-rules.md", rules),
        ("rituals.local.md", rituals), ("decisions.md", decisions), ("memory-map.html", memory_map),
        ("build-log.md", build_log), (os.path.join("debate", "_dispatch.log"), debate_dispatch_log))]
    # The config's backups keep their suffix; the debate folder keeps the kit's README.
    moves += [(name, config_file(root) + name[len("memory-config.json"):]) for name in names("")
              if name.startswith("memory-config.json.")]
    moves += [(os.path.join("debate", name), os.path.join(debate(root), name))
              for name in names("debate") if name not in ("README.md", "_dispatch.log")]
    return [(os.path.join(system, old), new) for old, new in moves
            if os.path.lexists(os.path.join(system, old))]


# Outside the instance.
def mangle_project_key(path):
    """Encode a Claude project-directory key using ASCII letters, digits, and hyphens."""
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


def transcripts(root=None):
    """The Claude transcript folder of this instance, whether or not it exists yet.

    Every character except ASCII letters, digits and hyphens becomes a hyphen, so non-ASCII names
    can collide. There is no fallback to a similarly named folder: that is another project's
    store. A renamed instance lists its previous roots in instance.root_aliases instead."""
    return os.path.join(os.path.expanduser("~/.claude/projects"),
                        mangle_project_key(root or instance_root()))


# Markers kept in the Git folder, which Git never tracks.
# Top-level folders the kit or its state owns.
KIT_OWNED = ("tools", "system", "templates", "instance", "state", "_private", "tmp",
             ".git", ".github", ".claude", ".codex", ".agents")
# Folders never walked into: version control and package stores hold no documents of the owner.
NEVER_WALKED = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__"})
# The rule of the kit's ignore file that denies every top-level name before it restores the engine.
DENY_ALL = b"/*"


def owner_names(root=None, env=None):
    """Top-level names that are the owner's and that Git cannot list in a kit installation.

    The kit's ignore file denies every top-level name and restores only the engine, so there Git
    lists none of the owner's own folders. A name is the owner's when that deny-all rule is what
    ignores it and neither the kit nor its state owns it. Where the ignore file has no such rule,
    Git's own list already holds the owner's files and this returns nothing. Names that start
    with a dot are settings, not documents, and are left out. env is the environment Git runs in.
    """
    root = root or instance_root()
    try:
        names = sorted(n for n in os.listdir(root) if not n.startswith(".") and n not in KIT_OWNED)
    except OSError:
        return []
    if not names:
        return []
    try:
        # --no-index: a folder with one tracked file in it is still the owner's folder.
        proc = subprocess.run(["git", "-C", root, "check-ignore", "--no-index", "-v", "-z", "--stdin"],
                              input=b"".join(os.fsencode(n) + b"\0" for n in names),
                              capture_output=True, env=env, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    # Exit 1 means nothing is ignored. -z gives four NUL-ended fields for each ignored name:
    # the file that holds the rule, its line, the rule and the name.
    fields = proc.stdout.split(b"\0") if proc.returncode == 0 else []
    return [os.fsdecode(fields[i + 3]) for i in range(0, len(fields) - 3, 4) if fields[i + 2] == DENY_ALL]


def owner_files(root=None, env=None):
    """The files under owner_names(root), as root-relative paths with / separators.

    Symbolic links are neither followed nor returned, and the folders in NEVER_WALKED are not entered.
    """
    root = root or instance_root()
    found = []
    for name in owner_names(root, env):
        top = os.path.join(root, name)
        if os.path.islink(top):
            continue
        if os.path.isfile(top):
            found.append(name)
            continue
        for folder, names, files in os.walk(top):
            names[:] = sorted(n for n in names
                              if n not in NEVER_WALKED and not os.path.islink(os.path.join(folder, n)))
            here = os.path.relpath(folder, root).replace(os.sep, "/")
            found.extend(f"{here}/{f}" for f in sorted(files)
                         if not os.path.islink(os.path.join(folder, f)))
    return found


def git_dir(root=None):
    """The checkout's Git folder (a linked worktree's .git file names its own), or None."""
    git = _at(root, ".git")
    if os.path.isdir(git):
        return git
    if os.path.isfile(git):
        try:
            with open(git, encoding="utf-8") as f:
                head, _, target = f.read().partition(":")
        except OSError:
            return None
        if head.strip() == "gitdir" and target.strip():
            target = os.path.join(root or instance_root(), target.strip())
            return target if os.path.isdir(target) else None
    return None


def marker(name, root=None):
    """The untracked path of one marker: in the Git folder, or state/.<name> without one."""
    git = git_dir(root)
    return os.path.join(git, name) if git else os.path.join(state(root), "." + name)


def runtime_arming(root=None):
    """doctor's last verdict on whether each runtime's hooks are armed, a marker beside the gate's."""
    return marker("mottori-runtime-arming", root)


def work_snapshots(root=None):
    """The folder of background-work snapshots, inside the Git folder; None without one."""
    git = git_dir(root)
    return os.path.join(git, "mottori-work") if git else None


# Paths setup.sh spells, by the name it asks for.
SHELL_NAMES = {
    "config": config_file,
    "projects_readme": projects_readme,
    "instance": instance,
    "rules": rules,
    "decisions": decisions,
    "rituals": rituals,
    "debate": debate,
    "debate_dispatch_log": debate_dispatch_log,
    "state": state,
    "private_state": private_state,
    "now": now_page,
    "private_now": lambda root: now_page("private", root),
    "journal": lambda root: journal_file(root=root),
    "gate_baseline": gate_baseline,
    "gate_baseline_prev": gate_baseline_prev,
    "legacy": legacy_moves,
}


def main(argv=None):
    names = sys.argv[1:] if argv is None else argv
    if not names or any(name not in SHELL_NAMES for name in names):
        print(__doc__.split("Command line", 1)[1].split("\n", 1)[1].rstrip(), file=sys.stderr)
        return 2
    root = instance_root()
    for name in names:
        found = SHELL_NAMES[name](root=root)
        for item in found if isinstance(found, list) else [found]:
            print("\t".join(os.path.relpath(path, root).replace(os.sep, "/")
                            for path in (item if isinstance(item, tuple) else (item,))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
