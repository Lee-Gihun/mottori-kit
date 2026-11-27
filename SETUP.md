# Setup (day-one playbook for your agent)

This document is for an agent setting up a freshly cloned workspace (or a person installing by hand without an
agent). For day-30 tasks (updating the kit, turning options on, fixing a silent hook, editing
`instance/config.json`, or undoing setup), open [MANUAL.md](MANUAL.md) instead.

On a company machine, the owner completes [system/CHECKLIST.md](system/CHECKLIST.md) section A before the clone.

## The short path

1. Run one command. It asks nothing, checks the prerequisites itself, creates the instance files and runs
   doctor.

   ```bash
   bash setup.sh
   ```

2. Show the owner what it printed, as it is. If it stopped, it says why and what to do.
3. Tell the owner the one approval their runtime needs from them (section 3), then stop. Existing material,
   tracks and dossiers wait until the owner asks for them (section 4).

Do not run the prerequisite commands yourself, and do not start a first-day item the owner did not ask for. The
sections below are the reference for each step.

## 0. Rules the setup agent must follow

- This repository holds only the kit: tools, rules and hook wiring, no data. Setup writes this machine's own
  config and state files next to it. The folder map is [MANUAL.md#where-things-are](MANUAL.md#where-things-are).
- Never add files under `instance/`, `state/` or `_private/` to Git. `.gitignore` already keeps them out, and the
  commit check refuses them; do not use `git add -f` to get around it.
- The kit does not decide which remote this folder may push to, or whether it may commit. On a company machine
  that is the company's policy and Git's own permissions.

## 1. Check prerequisites

```bash
python3 --version     # 3.9 or later
git --version         # 2.5 or later
bash --version        # 3.2 or later
which claude codex agy  # optional: without a runtime, setup still works, but no hook runs and no worker starts
zstd --version        # optional: lets recall read compressed Codex sessions
```

`setup.sh` checks Python and Git itself and stops with the reason, so run these by hand only when it stops. It
also prints a note when a folder above this one holds a `CLAUDE.md`: Claude Code reads those too, and the agent
would then follow two sets of rules. Pass the note to the owner and suggest another place for the folder.

The kit runs on macOS and Linux. Native Windows lacks the `fcntl` locking the kit needs and is not supported; WSL
has not been tested. Hook installation uses GNU `sha256sum`, BSD `shasum` or Python, in that order, and temporary
files go to the operating system's default temporary folder.

| Target | Status | Evidence and scope |
|---|---|---|
| macOS, Darwin 25.3, Apple Silicon | Tested on hardware | The full regression suite and fresh install passed with Bash 3.2.57, Python 3.9.6, and Apple Git 2.50.1. |
| Bash 3.2 | Tested on hardware | The default Bash 3.2 of macOS checks normal and POSIX syntax for six shell entry points and passes fresh install. |
| A PATH without `shasum` | Fixture-tested | The portability test provides only `sha256sum` and executes the hook-checksum branch. |
| Git 2.5 or later but earlier than 2.36 | Fixture-tested | The same test installs hooks through a Git wrapper that rejects `git hook run` and `--path-format`. No old Git binary was tested directly. |
| Default Ubuntu and Debian images | Expected to work | Static checks reject GNU/BSD-specific `sed -i`, `stat`, and `date` forms and fixed `/tmp`. No Linux container was run, so this is not hardware-tested. |
| Native Windows | Not supported | The kit requires `fcntl` and the Unix hook execution model. WSL is also untested. |

Optional features that use `claude` or `codex` are outside the scope of each row. How the table is tested
is in [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## 2. Run setup

```bash
bash setup.sh [--name <name>]
```

Setup asks nothing: an agent runs it. The instance's name is the folder's name unless `--name` gives another.
When the config is missing but instance files remain, setup writes a new config from the template and keeps the
files. Setup takes about fifteen seconds, about half of it in its doctor run, which asks each installed runtime
for its hook list.

Setup stops before writing anything when the folder is not the top of its own Git repository, for example a ZIP
download without `.git` or a kit folder inside another project's repository. Use `git clone`, or run `git init` in
the folder, then run setup again.

What setup creates:

1. `instance/config.json` from the template, with the name ([MANUAL.md section 2](MANUAL.md#config)).
2. `instance/rules.md`, `instance/rituals.md` and `instance/decisions.md` from the templates, and an empty
   `instance/debate/`. It copies only files that do not exist yet.
3. The first event in `state/journal-<month>.md` and `state/NOW.md`, and the first private event in
   `_private/state/journal-<month>.md` and `_private/state/NOW.md`. The events are written only while the public
   journal has no rows, so a rerun adds none.
4. A record of `python3 tools/linkcheck.py` in `state/.tool-runs.log`, and the gate baseline
   `state/.gate-baseline.json`. A `--force` run keeps a baseline that exists.
5. The pre-commit and pre-push hooks under `.git/hooks/`. Every run writes them when they are missing or from an
   older kit version. When another tool's hook is in the way or `core.hooksPath` points outside this folder, setup
   leaves it and says so: [MANUAL.md section 4](MANUAL.md#hooks) has the two ways forward.
6. The list of optional parts ([MANUAL.md section 1](MANUAL.md#optional)). The delivery check is on as the
   template config has it. Setup itself turns on one part, search by meaning, and only when an embedding server
   on this machine (by default `http://127.0.0.1:11434`) already answers with its model and the owner has not
   declined it. With `MOTTORI_NO_LOCAL_PROBE=1` in the environment, setup does not ask that server.
7. One run of `python3 tools/doctor.py`. That run and the baseline decide setup's exit status. When Codex is
   installed, doctor's first look at recall's sources writes a cache file under `_private/state/`: the working
   folder and id of each Codex session on this machine, other projects' included, so recall can keep to this
   folder's. It stays on this machine and is rebuilt when deleted.

On a complete install a rerun without `--force` changes one thing: it writes the Git hooks that are missing or
older. It prints the commands to use next (`--force`, doctor, `python3 tools/options.py`) and exits 0 without running
doctor. When the rules file, `state/NOW.md` or the gate baseline is missing, as after an interrupted first
setup, a rerun exits 1, names the missing files and points to `bash setup.sh --force`, which creates them. Undoing
setup: [MANUAL.md section 5](MANUAL.md#undo).

## 3. Run doctor and arm your runtime

```bash
python3 tools/doctor.py
```

**Setup is done when doctor reports 0 failures.** `FAIL` is something to fix, and doctor then exits 1: do not trust
state automation or hooks until it is fixed. `warn` can be normal for this machine, for example no tracks yet, and
does not change the exit status. Run `python3 tools/doctor.py --all` only when troubleshooting.

Then arm each runtime the owner uses. These are one-time approvals that only a person can give:

- **Codex.** Launch `codex` once in this folder and choose "Trust all" on the hooks review, once per checkout path.
  Until then Codex skips the kit's hooks without saying so. Doctor's `hooks · codex armed` row does not apply
  until Codex has had a session in this folder, and after that it warns and names this step until it is done.
- **Antigravity.** Start `agy` once in this folder and answer "Yes, I trust this folder"; doctor's
  `hooks · agy armed` row warns until then once Antigravity has had a session here.
- **Claude Code.** Trust the folder on the first interactive launch.
  No command is allowed in advance, so for the first days Claude Code asks once for each kit command the agent
  runs, such as logging a decision or searching what was said. Choosing "don't ask again" for that command ends
  it; doctor and the turn-end hooks run without asking.

Doctor tests the hook commands outside a session and never replaces
[system/CHECKLIST.md](system/CHECKLIST.md) section C. Pass what it says it did not check to the owner as
printed, and never claim it was checked.

## 4. When the owner asks for more

None of this is needed on the first day.

1. **Rules.** When material comes in that belongs to someone else, such as company material, ask the owner to
   open `instance/rules.md` and say what is brought in, where it lands, and what must never leave. Until then the
   file can stay as the template. The "Data boundary" section of [system/rituals.md](system/rituals.md#boundary)
   has the three principles.
2. **Material the owner already has (optional).** Setup made `projects/` with its guide, `projects/README.md`.
   Bring a folder of notes in whole as one project and leave it as it is. Do not reorganize it, rename anything
   in it or fix its links on the first day.

   ```bash
   mv ~/old-notes projects/            # the owner runs this, or approves it once
   python3 tools/adopt.py projects/old-notes
   ```

   The folder is now a project named after it, with no block, and doctor stays at 0 failures. `adopt.py` records
   the links that are already broken in it, so they stop no later turn. It names the instruction files inside it,
   such as an old `CLAUDE.md`, for the owner to fold into `instance/rules.md`. And it writes one inventory page:
   read that page, not the folder, before proposing what to put on the status board.

   A code repository, or any folder a program or a scheduled job writes to, is not moved in. It stays where it is
   and is named under `outside` in its project's block; the owner adds it to a session with the runtime's
   `--add-dir` option ([MANUAL.md section 1](MANUAL.md#optional), "A repository beside the workspace").
3. **First project (optional).** Give each line of work a folder under `projects/`. The block at the top of its
   `README.md`, shown in `projects/README.md`, can give it a name, a status and folders outside this one. To
   also show it on the status board, add it to `tracks` in `instance/config.json` and run
   `python3 tools/now.py render` ([MANUAL.md section 2](MANUAL.md#config)). The board shows the date of the
   track's file from a line in it such as `Last updated: 2026-12-01`.

   ```json
   { "key": "onboarding", "name": "Onboarding", "canonical": "projects/onboarding/tracker.md" }
   ```

4. **First dossier (optional).** A deep thread with a dossier goes into `threads` in the same file;
   `python3 tools/now.py threads` lists them. List only threads that may be shared; private ones go into
   _private/state/threads.json in the same shape.

   ```json
   { "key": "checkout", "name": "Checkout bug", "dossier": "projects/shop/checkout-bug.md" }
   ```

5. **Handoff.** Name [system/CHECKLIST.md](system/CHECKLIST.md) once: it holds the checks only a person can do.

Do not turn on other optional parts unless the owner asks ([MANUAL.md section 1](MANUAL.md#optional)).
