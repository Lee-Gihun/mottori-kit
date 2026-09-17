Korean: `SETUP.ko.md`

# SETUP: How to configure this directory

**This document is an instruction sheet for an agent.** Clone the repository on a new machine, open Claude Code
or Codex in this directory, and say:

> Read SETUP.md and configure this directory. Show me the doctor result when you finish.

If you are doing it yourself, follow the steps below in order. It takes five minutes.
If this shell was opened from another mottori workspace, first run `unset MOTTORI_INSTANCE` or set it to the
absolute path of the new clone. Otherwise doctor will inspect the previous instance.

---

## 0. Understand what this is first (agents must read this)

This repository contains **only the engine**. It includes tools, rules, and hook wiring. It contains no data.
Setup gives this engine an **instance identity for this machine**.

After setup, this directory is the workspace. You do not need a separate project folder. Keep documents, notes,
and tracks here.

**Never do these two things.**

- Do not leave `instance.context` in `system/memory-config.json` set to `personal` and then add company material.
  This value is the basis for the valve check in `tools/doctor.py`.
- Do not add instance output under `state/` or `_private/` to Git. `.gitignore` already blocks it. Do not use
  `git add -f` to bypass that protection.

## 1. Check prerequisites

```bash
python3 --version     # 3.8 or later
git --version         # 2.5 or later
bash --version        # 3.2 or later
which claude codex    # Installation still works without them. Fresh workers and hook injection will not
node --version        # Used by the gardener, /garden. Everything else works without it
```

The core installation targets macOS and Linux. Hook installation chooses GNU `sha256sum`, BSD `shasum`, or
Python, in that order, for SHA-256. Temporary files use the operating system's default temporary directory.
Native Windows lacks the required `fcntl` locking and is unsupported. WSL has not yet been tested on hardware.

### Support matrix

| Target | Status | Evidence and scope |
|---|---|---|
| macOS, Darwin 25.3, Apple Silicon | Tested on hardware | The full regression suite and fresh install passed with Bash 3.2.57, Python 3.9.6, and Apple Git 2.50.1. |
| Bash 3.2 | Tested on hardware | The default Bash 3.2 on this machine checks normal and POSIX syntax for six shell entry points and passes fresh install. |
| A PATH without `shasum` | Fixture-tested | `tools/test_portability.py` provides only `sha256sum` and executes the hook-checksum branch. |
| Git 2.5 or later but earlier than 2.36 | Fixture-tested | The same test installs hooks through a Git wrapper that rejects `git hook run` and `--path-format`. No old Git binary was tested directly. |
| Default Ubuntu and Debian images | Expected to work | Static checks reject GNU/BSD-specific `sed -i`, `stat`, and `date` forms and fixed `/tmp`. This environment could not run a Linux container, so this is not hardware-tested. |
| Native Windows | Unsupported | The kit requires `fcntl` and the Unix hook execution model. WSL is also currently untested. |

Optional features that use `claude`, `codex`, `node`, `ffmpeg`, or `mlx_whisper` are outside the core
installation scope in each row. Section 3 and `tools/test_portability.py` are the authority for the verification
commands in this table.

## 2. Create the instance configuration

If you already completed `setup.sh` and hook `--repair` from README's quick start, do not repeat them here.
Continue with `--check` in section 2b and then section 3.

```bash
bash setup.sh
```

The interactive flow asks for an instance name and a context, either `personal` or `work`. It then creates
`system/memory-config.json`. A noninteractive form is also available:

```bash
bash setup.sh --name team-work --context work
```

Without a tty, such as under an agent, CI, or a pipe, the script does not prompt. It uses the directory name as
the instance name and `work` as the context, then prints that choice. On a personal machine, specify
`--context personal`.

`setup.sh` creates all of the following. Delete this list to undo a new installation.

1. `system/memory-config.json`. It copies the template, replaces the name and context, and adds the clone origin
   to the allowlist.
2. `system/instance-rules.md`, `system/decisions.md`, and `system/rituals.local.md`. It copies only files that do
   not already exist.
3. The first event in `state/journal-<month>.md`, `state/NOW.md`, the first local event in
   `_private/state/journal-<month>.md`, and `_private/state/NOW.md`.
4. A record of running `python3 tools/linkcheck.py` in `state/.tool-runs.log`, plus the gate baseline at
   `state/.gate-baseline.json`.
5. One final run of `python3 tools/doctor.py`, with its result displayed.

To upgrade an existing schema v1, v2, or v3 instance to v4, or to reapply setup while preserving a v4
configuration, run `bash setup.sh --force`. The existing config values become the defaults for name and context.
The context does not change to `work` when no tty is present. The existing config is saved as `.bak`. Tracks,
checks, and public lists are preserved.

The script stops if a v1 to v3 configuration contains nonempty `threads[]`. Those entries have no public-decision
provenance and cannot be promoted automatically. A person must first separate confirmed public entries from
local entries, then rerun setup. Only verified v4 `threads[]` are preserved as-is. For v3, existing public lists
are anchored to provenance in historical journal rows. For v1 and v2, that decision does not exist, so all
existing journal entries remain fail-closed as legacy-private. The boundary is the timestamp of the final journal
entry before migration. The script does not guess when a journal or config is malformed. Run
`python3 tools/doctor.py` again when migration finishes.

To undo a new installation, delete the files listed above: the four generated files under `system/`, `state/`,
`_private/state/`, and `.git/hooks/pre-commit` if section 2b installed it. To undo a migration, inspect the backup
and restore `system/memory-config.json.bak`. Setup performs no irreversible action.

## 2b. Install the verification backstop

```bash
bash tools/install_hooks.sh --repair
bash tools/install_hooks.sh --check
```

`.git/hooks/` does not come with a clone. Run this once to install the pre-commit backstop.

**Why it is needed.** The Stop gate sees only `Write`, `Edit`, and `NotebookEdit`. It cannot see Bash edits,
external writers, Codex edits, or user interrupts. Pre-commit checks the actual index being committed and closes
that gap. `--no-verify` can still bypass it. This is a backstop, not a contract.

If another pre-commit hook already exists, the installer stops without overwriting it. Inspect the existing hook
and merge them manually.

## 3. Verify the installation

```bash
python3 tools/doctor.py
```

During first initialization, `setup.sh` creates the linkcheck record and gate baseline. Run
`python3 tools/linkcheck.py && python3 tools/gate.py baseline` yourself only during a manual installation or
recovery. Without a baseline, the gate cannot distinguish deletion from a first installation, so it fails closed.

**Setup is complete only when FAIL is 0.** The three result markers mean:

- `FAIL`: the machine can or must fix this. Exit code 1. If any appear, do not trust state automation.
- `warn`: this can be normal depending on the environment. Examples include missing Codex or Claude, no
  transcript directory before the first session, no registered tracks, or Codex not yet trusting this
  directory's hooks. Warnings do not affect the exit code.
- `--`: this check does not apply to the instance. For example, remote checks do not apply to a personal context.

The same finding can be a FAIL in a work instance and a warning in a personal instance. One example is a tracked
symbolic link that points into `_private/`. The difference is whether company structure could reach a remote.

If you use Codex, launch `codex` once in this directory and approve hook trust. Until approval, `doctor` reports
`hook · codex armed` as a warning. See CHECKLIST.md section C.

`bash tools/test_fresh_install.sh` verifies that the full process works on an unfamiliar machine. It reproduces a
noninteractive setup in a temporary clone: setup, hooks, linkcheck, doctor, regressions, and setup rerun. Run it
after changing the engine.

If you manually test a temporary clone from inside an active mottori instance, run
`unset MOTTORI_INSTANCE CLAUDE_PROJECT_DIR` after entering the clone. Otherwise the nested test can point tools
back to the parent instance. The official test script performs this isolation automatically.

At the end, doctor prints four items under **"Cannot check automatically"**. A machine cannot verify them. Pass
the list to a person exactly as shown. Do not claim that they were checked.

## 4. Complete the instance rules

Open `system/instance-rules.md` and declare the boundaries of this workspace. At minimum, state what is imported,
where it lands, and what must never go to any remote.

The "Data boundary" section of `system/rituals.md` explains why each instance needs its own declaration. Copying
the wrong direction makes the rule operate backward.

## 5. Register the first track

Add each active line of work to `tracks` in `system/memory-config.json`. One track has one canonical document. You
may leave the array empty and add tracks later.

```json
{ "key": "onboarding", "name": "Onboarding", "canonical": "onboarding/tracker.md" }
```

After registering a track, run `python3 tools/now.py render`. The temperature board in `state/NOW.md` will show
the track's freshness. Editing the config makes NOW stale until it is rendered again. `now.py check` reports that
condition.

## 5a. Update the engine after `git pull`

```bash
git pull
bash tools/install_hooks.sh --check      # Use --repair if the hook template changed
python3 tools/linkcheck.py && python3 tools/gate.py baseline   # Refresh if a checker changed
python3 tools/doctor.py                  # [Action required] items in CHANGELOG appear here as FAIL
```

`CHANGELOG.md` is the source of truth for actions required by existing instances. A new installation already uses
the latest templates, so it does not need to repeat `[Action required]` items from older versions.

## 5b. Self-check: Does the documentation close over itself?

```bash
python3 tools/linkcheck.py
```

The goal is **`broken: 0`**. A broken reference means that this repository points to a file it does not contain.
An agent following that document will see an unusable path.

Immediately after setup, one generated ledger file is still absent: the hotset produced by `rec.py hot`. It
appears after you record the first fact. To create it now, run:

```bash
python3 tools/rec.py new <id> --claim="..." --status="$(python3 -c 'print("\uD655\uC815")')" --origin="..." --domain=...
python3 tools/rec.py hot
```

Only `rec.py new` works before the ledger exists. `hot`, `find`, and `check` require a ledger. Querying an empty
ledger would make "there are no facts" indistinguishable from "the ledger was never created." The escaped status
value in the command means "confirmed" and is one of the values accepted by the tool.

## 6. Global configuration (optional, once)

This repository's `.claude/settings.json` already injects the current time on every prompt. To use the same hook
in other directories, add it to `~/.claude/settings.json`.

```json
{ "hooks": { "UserPromptSubmit": [ { "hooks": [
  { "type": "command", "command": "date '+[now: %Y-%m-%d %H:%M %Z (%a)]'" } ] } ] } }
```

Why: the model does not know the current time by itself. Without this hook, date calculations can silently be
wrong.

## 7. Connect Codex (optional)

`AGENTS.md` is the single source of truth for shared rules. `CLAUDE.md` is an exact `@AGENTS.md` import. Codex
reads `AGENTS.md` automatically, so both runtimes operate under the same rules. `AGENTS.ko.md` is the Korean
locale surface.

Isolate broad reading, audits, and runtime debates in a fresh worker instead of adding the full trace to the
master session:

```bash
python3 tools/fresh_worker.py --runtime claude <prompt-file>
python3 tools/fresh_worker.py --runtime codex  <prompt-file>
bash tools/ask_codex.sh <prompt-file>   # Compatibility entry point for a fresh Codex worker
```

The prompt must be a regular UTF-8 file inside this workspace. Symlinks are rejected. If you put prompt content
directly on the command line, backticks can execute as shell commands. The default run is synchronous. Full
traces stay in `_private/work/runs/`, and the caller receives only a bounded receipt. The exact byte and
capability contract is defined in `system/PRD-session-memory.md` section 10.5.

## 8. Final handoff to a person

Open `CHECKLIST.md` and report the remaining items to a person. That document is the source of truth for
checks a person must perform after installation.

## Procedural evidence

`tools/test_fresh_install.sh` reproduces this command order in a temporary clone. `CHECKLIST.md` and KIT-DR-011
define the handoff boundary for human checks. Avoiding irreversible recovery steps prevents an installation
failure from becoming user-data loss. Time and version numbers are measurements from the specified test
environment, not guarantees for every machine.
