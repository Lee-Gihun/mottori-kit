# CHANGELOG

This file holds one entry: what the kit is at this release, and what someone updating an earlier clone does.
Earlier entries are in the Git history of this file. The reasons behind each part are the decision records in
`system/specs/kit-decisions.md`.

Items marked `[Action required]` or `[Note]` carry at least one evidence marker
(`system/dev/evidence-schema.md`).

---

## v0.11 · 2026-11-27

### `[Note]` State and memory

Evidence: `decision:KIT-DR-006`, `decision:KIT-DR-021`, `decision:KIT-DR-054`.

State lives in files. `python3 tools/now.py log` writes one journal line per decision, and `state/NOW.md` is a
view drawn from the journal. Hooks inject that view, what you asked to keep under `_private/`, the dossier list
and the newest decisions at session start and after compaction, within a fixed byte cap.
What one installation writes for itself (config, rules, rituals, decision records, debate rounds) is in
`instance/`, and its state is in `state/` and `_private/`. All three stay out of Git.

### `[Action required]` Projects, and two documents that moved

Evidence: `decision:KIT-DR-093`, `decision:KIT-DR-094`, `decision:KIT-DR-095`, `decision:KIT-DR-096`.

Your work goes in `projects/`, one folder per project; every folder there counts, and a block at the top of its
`README.md` can give it a name, a status and folders that stay where they are (`outside`). `bash setup.sh
--force` creates the folder and its guide in an existing installation; the map in the guide is redrawn with the
state page. Setup now turns on search by meaning when an embedding server on this machine already answers with
its model and you have not said no, and doctor warns about a configuration path that names nothing. The
checklist is now `system/CHECKLIST.md` and the contributing guide `.github/CONTRIBUTING.md`: update a link or a
script that opens them at the root.

### `[Note]` Hooks and the three runtimes

Evidence: `decision:KIT-DR-015`, `decision:KIT-DR-042`, `decision:KIT-DR-051`.

Claude Code, Codex and Antigravity CLI read the same `AGENTS.md` and declare one hook line per event; the
kit's dispatcher, `tools/dispatch.py`, decides what runs. Live-session measurements and the gaps of each runtime
are in section 4 of `MANUAL.md`.

### `[Note]` Checks: the turn end, the commit and doctor

Evidence: `decision:KIT-DR-020`, `decision:KIT-DR-060`, `decision:KIT-DR-064`,
`test:tools/tests/test_gate.py::test_older_baseline_naming_retired_checkers_does_not_block_a_commit`,
`test:tools/tests/test_gate.py::test_a_turn_that_edited_a_frozen_path_stops_once`,
`test:tools/tests/test_gate.py::test_waiting_items_stop_a_turn_once_and_then_only_wait`.

`tools/gate.py` checks Markdown links and state freshness at the end of a turn and before a commit, and stops
once with the reason. At the end of a turn it also stops once when an edit tool changed a path listed in
`frozen` in `instance/config.json` (`decision:KIT-DR-087`), and a set of issues listed as waiting work in
`checks.waiting` stops one turn only (`decision:KIT-DR-089`). It has one scope: in a kit clone and in
an installed instance it checks the same things. A commit is checked only where setup has installed the Git
hooks. `python3 tools/doctor.py` prints only what needs attention, with what to type; `--all` prints every
row.

### `[Note]` Workers and other models

Evidence: `decision:KIT-DR-007`, `decision:KIT-DR-033`, `decision:KIT-DR-043`, `decision:KIT-DR-073`.

Broad reading and reviews run in a fresh bounded worker (`tools/fresh_worker.py`, `tools/ask.sh`), which returns
a receipt of at most 4,096 bytes with the verdict first. A worker can run on another runtime. No prompt is read
for path names: what a worker can open is decided by where it runs (`workers` in `MANUAL.md` section 2).

### `[Note]` Recall and notes between sessions

Evidence: `decision:KIT-DR-028`, `decision:KIT-DR-044`, `decision:KIT-DR-055`.

`python3 tools/recall.py find` searches past transcripts of the three runtimes, including compressed Codex
sessions when `zstd` is installed; `--role user` limits it to what the owner typed. Sessions leave each other
short notes with `tools/notes.py`.

### `[Note]` Skills

Evidence: `decision:KIT-DR-063`,
`test:tools/tests/test_skills.py::test_write_copies_every_file_and_check_names_each_difference`.

Each skill, slash commands included, has one source folder in `system/skills/<name>/`, and
`python3 tools/skills.py write` copies it to `.claude/skills/` and `.agents/skills/`. The kit ships nine.

### `[Note]` Optional parts and the improvement loop

Evidence: `decision:KIT-DR-057`, `decision:KIT-DR-061`, `decision:KIT-DR-088`,
`test:tools/tests/test_loop_sources.py::test_an_added_source_is_known_listed_judged_and_watched`.

Of three optional parts (`meaning`, `deliver`, `loop`), `deliver` is on after setup, `meaning` is on only when an
embedding server on this machine already answers, and `loop` is off;
`python3 tools/options.py` shows and switches them, and also says whether Codex is installed and how long Claude
Code keeps transcripts. The improvement loop runs on macOS only and ends at a reviewed patch that the owner's agent
applies; it never writes into the owner's files. It ships one source, papers, which reads new arXiv papers; a source
of the owner's own goes in `tools/loop/sources/`.

### `[Note]` Language

Evidence: `decision:KIT-DR-062`.

The kit is published in English only. What an owner writes in `instance/` stays in the owner's language.

### `[Note]` Changing the kit

Evidence: `decision:KIT-DR-064`,
`test:tools/tests/test_runner.py::test_a_test_function_its_file_never_runs_fails_the_file`,
`test:tools/tests/test_install_checks.py::test_ci_runs_only_in_the_kit_repository`.

`python3 tools/tests/run.py --full` runs every suite; a test function its file never runs fails that file.
`system/dev/enforcement.md` says which rule is checked by what, and `tools/dev/evidencecheck.py` checks that each
marker in the decision records, this file and that table is well formed and names something in the tree.
Continuous integration runs the suite and those checks, and only in a repository named `mottori-kit`.
A line of prose in the kit's Markdown longer than 120 characters fails a test (`decision:KIT-DR-092`).

### `[Note]` Whom each part is for

Evidence: `decision:KIT-DR-065`,
`test:tools/tests/test_model_assumptions.py::test_the_page_names_every_step_option_and_skill`,
`test:tools/tests/test_skill_probe.py::test_starts_nothing_without_yes`.

`system/specs/model-assumptions.md` sorts every part by whom it is for: the person, a model, a runtime, or both. A
part that makes up for a model or a runtime says what it assumes and how to try without it. Every cap on what the
model is shown gives its reason, or says that none is recorded. Section 7 says what to measure when the model
changes.
`tools/dev/skill_probe.py` repeats the measurement of whether the thinking skills open, after your yes.

### `[Action required]` Updating an earlier clone

Evidence:
`test:tools/tests/test_setup_migration.py::test_old_layout_says_one_line_until_force_moves_each_file_once`,
`test:tools/tests/test_setup_migration.py::test_force_preserves_instance_settings_and_backups`,
`test:tools/tests/test_setup_migration.py::test_a_starter_language_key_is_read_and_dropped_on_force`,
`test:tools/tests/test_setup_migration.py::test_an_earlier_configs_context_and_remote_list_are_dropped_and_said_so`.

After `git pull`, run `bash setup.sh --force`, then `python3 tools/doctor.py`. Setup keeps the name and
every setting of the installation and copies the old config to `instance/config.json.bak-<time>`. A config from
before v0.10 is not moved: setup says to move it aside and run setup again. An installation made before the
`instance/` folder has its files moved there once, each keeping its bytes; if a file exists at both places, setup
moves nothing and names both.
Setup also installs the Git pre-commit and pre-push hooks if they are missing and leaves a hook that is not the
kit's alone. Fix what doctor then lists. `MANUAL.md` section 3 has the details.

Two config keys of earlier versions, `instance.context` and `instance.remote_allowlist`, are dropped, and
setup says so. The kit no longer tells work and personal folders apart and no longer refuses a commit or a
push by the kind of folder or by remote (`decision:KIT-DR-072`). A folder that was set up as `work` commits
and pushes like any other after this update: what may leave a company machine is the company's policy and your
Git account's permissions. The commit check still keeps `_private/`, `instance/` and `state/` out of Git, and
the push check still refuses a private path.

### `[Note]` Lenses show their question, and every folder has a page

Evidence: `decision:KIT-DR-066`, `decision:KIT-DR-067`, `decision:KIT-DR-068`,
`test:tools/tests/test_tool_entrypoints.py::test_readme_lists_every_tool`.

An agent that uses a thinking lens now ends with one line that names the lens and its question, so the person
can think with it. Below the table one open question asks what the table missed. The README starts from what
the kit is for, and `tools/`, `tools/lib/`, `tools/loop/`, `tools/tests/`, `system/`, `system/skills/`,
`system/specs/` and `templates/` each have a README.

### `[Note]` Bringing in what you already have

Evidence: `decision:KIT-DR-069`,
`test:tools/tests/test_adopt.py::test_an_adopted_link_is_not_this_turns_issue_and_a_new_one_is`.

`python3 tools/adopt.py FOLDER` takes a folder of your own material as it is. Before, each edit of an old document
stopped the turn once for a link that was already broken. Now those links are recorded when the folder is adopted,
and only a link broken later stops a turn. The run also names instruction files inside the folder and writes one
inventory page.

### `[Note]` A quieter start

Evidence: `decision:KIT-DR-070`, `test:tools/tests/test_permissions.py::test_no_command_is_allowed_in_advance`.

Setup is one command that checks its own prerequisites. A new folder no longer shows warnings about what it
cannot have yet, and the turn-end check stays silent until setup has run. The owner's own notes are adopted in
place, not treated as imports. In Claude Code an edit to the kit's code, rules, configuration or accepted
findings always asks. The kit allows no command in advance.

### `[Note]` A tutorial, and a README told in scenes

Evidence: `decision:KIT-DR-097`,
`test:tools/tests/test_tool_entrypoints.py::test_the_tutorial_and_readme_name_only_commands_that_exist`.

`TUTORIAL.md` walks the first hour: a decision, a second topic in the same chat, a file for a long topic, a
compaction, a stopped turn, a search of your own words and a lens. The README shows each part of the kit in one
short scene, all from the same three topics, and its first picture is one of them: a topic picked up on day 22
where it was left on day 1.
