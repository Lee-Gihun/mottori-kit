# Owner's manual (after day one)

Open this document when your workspace is already set up and you need to turn an optional feature on, edit
`instance/config.json`, update the kit, fix a hook that stopped firing, or undo setup. For a fresh install,
hand [SETUP.md](SETUP.md) to your agent; for where files live, see [Where things are](#where-things-are).

<a id="where-things-are"></a>
## Where things are

```text
Yours (ignored by Git; back these up yourself)
  instance/         Your config.json, rules.md, rituals.md, decisions.md and debate/
  state/            NOW.md, the journals and logs (written through tools/now.py)
  _private/         What stays on this machine: what you asked to keep there, and the kit's own stores
                    (the fact ledger, reminders, notes between sessions, worker runs)
  projects/         Your work, one folder per project; projects/README.md is the map (see below)

The kit's (tracked; git pull overwrites these)
  AGENTS.md         The seven rules that are always loaded (CLAUDE.md imports it)
  tools/            The commands you or your agent run
  system/           What the agent reads when a situation comes up: skills, guides, design records
  templates/        The blank forms setup copies into instance/ and projects/
  .claude/ .codex/ .agents/   Each runtime's hooks. The skill copies are in .claude/skills/ and .agents/skills/
  .github/          The README's images and the continuous integration workflow
  setup.sh README.md SETUP.md MANUAL.md CHANGELOG.md LICENSE
```

**What `_private/` is for.** It is the place for what must stay out of Git and out of anything written for other
people: material given to you in confidence, another person's private matter, anything you say so about. Git
never takes it, and the agent's rules tell it not to quote it in what it writes for other people. The agent
still reads it, so it goes to your model provider like anything else the agent reads. Nothing is put there by
guess: the agent suggests it when something looks like that, and you decide. It is not hidden from the agent,
nor from a worker that runs in this folder. A worker that runs in a copy does not get it.

**Projects.** Your work lives in `projects/`, one folder per project: a paper, a product launch, a course you
teach, a side project. Its documents, scripts and small code go in its folder together. Every folder there is a
project, named after the folder, so a folder you bring in as it is counts as one. A short block at the top of
its `README.md` can add a name, an area, a status, the file to open first, folders outside this one and the
parts under `_private/`; every line of it is optional. The map in `projects/README.md` is drawn from the folders
and their blocks whenever the state page is, every session starts with the open project folders by status and
their outside folders, and doctor warns about what a block names but cannot find. Nothing about a project makes
doctor fail. When a project ends, only its status changes; the folder stays.

A folder that already lives elsewhere stays there: its own repository, a folder a scheduled job or another
program writes to, a folder with its own virtual environment or its own agent instructions. Name it under
`outside` in the project's block. The agent then knows where it is, and doctor says whether it exists on this
machine. Each runtime reaches it with `--add-dir`, and Claude Code also with `permissions.additionalDirectories`
in `.claude/settings.local.json`; those permissions are yours, and the kit does not write them. What of a
project must never reach Git (an employer's material, scans of identity papers, recordings of other people) goes
in a folder of the same name under `_private/`, named under `private`. The status board and the dossier list are
separate lists, `tracks` and `threads` in `instance/config.json` (section 2), so a project shows on the board
only when it is also a track ([KIT-DR-093](system/specs/kit-decisions.md)).

**Keeping folders of your own in Git.** Everything you create at the root is ignored, so nothing you write
reaches a remote by accident. To keep a folder of your own in Git, for a private remote of yours, add a line such
as `!/notes/` below the marker at the end of `.gitignore`. `git pull` merges the kit's lines above the marker and
keeps yours, and doctor does not count your lines, or changes to your own tracked files, as engine changes.

`tools/`, `tools/lib/`, `tools/loop/`, `tools/tests/`, `system/`, `system/skills/`, `system/specs/` and `templates/`
each have a README of their own.

<a id="optional"></a>
## 1. Optional features and built-in tools

Nothing here is needed on the first day. Of the three optional parts, `deliver` is on after setup and `loop` is
off. `meaning` is on after setup when it costs nothing: an embedding server on this machine already answers with
its model and you have not said no to it before (KIT-DR-094); otherwise it is off, and a search says so on its
last line. Setup turns nothing else on and prints one line with the command that lists them. The same list
also says whether Codex is installed and how long Claude Code keeps transcripts here, which are facts about the
machine, not switches.

```bash
python3 tools/options.py                # the list, each option's state, benefit and need
python3 tools/options.py on meaning     # check the need, ask before a download, write the settings and run the first step
python3 tools/options.py off meaning    # turn it off; the list then shows that you said no
```

`on` changes nothing while a need is missing: it prints the exact steps instead. After writing the settings it reads
the option back the way the option's own tool reads it; when that still reads as off, or when the option's first
step fails, it puts the settings back and the option stays off. The one download it makes is the model of
`meaning`, and only after it named the model and you said yes. It never starts a service or gives an approval
that is yours, such as a login or a hook trust. What it writes goes into `instance/config.json`, and `off` records
the no there under `options.declined`. `on` and `off` draw the state page again at their end, so the next commit
is not stopped for a page older than the config. A `--force` rerun of setup keeps all of it.

### Walking the owner through one option (for an agent)

1. Read the option's line in `python3 tools/options.py` and say in two sentences what it gives and what it costs:
   what it needs, what leaves the machine, and when it starts to pay off.
2. Ask one question: turn it on now or not?
3. On a yes, run `python3 tools/options.py on NAME`. If it prints steps, give them to the owner as printed and run
   the command again when they are done. Those steps are the owner's own: installing a program, starting a server,
   signing in to a vendor, approving hooks, and changing a setting that applies to every folder. When `on meaning`
   names a model to download and no terminal can ask, it prints the same command with the word `yes` added: tell
   the owner the model, its size and its source, and run that command only after the owner said yes.
4. On a no, run `python3 tools/options.py off NAME`.

### The optional parts

- **meaning: search by meaning.** `python3 tools/recall.py find` adds a list ranked by meaning beside the word
  list. On one person's history, 119 earlier statements were each looked for with one full-sentence question: 111
  were found with both lists, 75 with the word list alone (KIT-DR-046).

  Turning it on. `on meaning` writes `instance.recall_meaning` in the config (`endpoint`, `model`, `query_prefix`
  and `document_prefix`) with the defaults for Ollama's OpenAI-compatible route
  (`http://127.0.0.1:11434/v1/embeddings`) and `embeddinggemma`. It refuses an endpoint that is not 127.0.0.1,
  localhost or ::1, because the texts sent are your own words. It checks that the endpoint answers within two
  seconds and then runs `python3 tools/recall.py index`. Any model behind the same route works:
  `python3 tools/options.py on meaning model=NAME endpoint=URL`, then set the prefixes that model expects.

  When something is missing. When Ollama is installed but no server answers with the model, it names the model,
  its size and its source and asks once; on yes it downloads the model with `ollama pull` and goes on as above.
  Without a terminal it changes nothing and prints the same command with the word `yes`, which stands for that
  yes. When the `ollama` program is not installed, it says so in one line with the command that installs it and
  changes nothing.

  What it costs. `embeddinggemma` is about 0.6 GB under its own licence terms, which is why the kit does not ship
  it. The first index embeds every message (about four minutes for 9,000 messages). The vectors are kept in
  `_private/state/recall-vectors.bin`, safe to delete like the store.

  Keeping up. When the store of your messages or the vectors are behind at session start, one detached process
  catches up, and a search never waits for it. A search still reads what the transcripts added for at most 3
  seconds, so a message typed a minute ago is in the store and can be found. It leaves out your newest message,
  the one that asked for this search, and says so. It embeds
  what is missing for at most 3 seconds only while no catch-up runs, and its last line says how many of the
  messages the list by meaning holds.
- **deliver: delivery check.** On after setup: `"deliver": {"block": ["unopened"]}` stops a turn once when a long
  document written in that turn is handed over without being reread (KIT-DR-022 measured the signal right in 35
  of 40 sampled hits). `off deliver` turns it off; put `"unopened"` in `observe` instead to record without
  stopping. The check is a step of the kit's `Stop` line in
  `.claude/settings.json` and runs after the gate, on Claude Code only; when no `Stop` line runs it, `on deliver`
  changes nothing and prints an entry to add,
  `{"hooks": [{"type": "command", "command": "sh \"$CLAUDE_PROJECT_DIR/tools/hook.sh\" deliver.py hook || true"}]}`.
  `python3 tools/deliver.py stats` shows what it recorded.
- **loop: the improvement loop.** macOS only. Weekly patches to this kit from arXiv (`papers`) and from any
  source this installation added (`tools/loop/sources/`), saved with a report for you or your agent to apply;
  the loop never writes into your files. `on loop` states what each source sends and takes your yes (replacing
  any earlier choice); it schedules nothing.
  `python3 tools/loop/loops.py` runs, schedules and shows status; `off loop` unschedules it and removes send
  permissions. Read [system/loop/README.md](system/loop/README.md) before you turn it on.

### Two facts the list also shows

Neither is a switch of this kit: `on` and `off` change nothing for them and say so.

- **Codex, a second model family.** The list says whether the `codex` program is installed. `AGENTS.md` is the
  single source of truth for shared rules and `CLAUDE.md` is an exact `@AGENTS.md` import, so both runtimes work
  under the same rules. Workers and reviews reach Codex through
  `python3 tools/fresh_worker.py --runtime codex <prompt-file>` or `bash tools/ask_codex.sh <prompt-file>`; the
  prompt files go to that vendor, and what the worker can open besides is set by where it runs (`workers`,
  section 2). Signing in and approving this folder's hooks on the first launch are yours (SETUP.md step 3), and
  doctor's `hooks · codex armed` row shows the second.
- **History.** The list says how many days Claude Code keeps transcripts here. `python3 tools/recall.py` can
  search only the session transcripts that still exist. Claude Code's documentation says it deletes terminal
  session files older than `cleanupPeriodDays` days (default 30) without a message, while desktop app sessions are
  kept unless `desktopSessionCleanupPeriodDays` is set. The setting is in `~/.claude/settings.json` and applies to
  every folder, so it is yours to change, for example `"cleanupPeriodDays": 365`. The recall row of
  `python3 tools/doctor.py` shows the value in effect.

### The time hook in other folders

This folder's `.claude/settings.json` already injects the current time on every prompt. To use the same hook in
other folders, add it to `~/.claude/settings.json`; once it is there, this folder adds no second time line. Codex
does the same with a time hook in `~/.codex/hooks.json`. Setup leaves both to you.

```json
{ "hooks": { "UserPromptSubmit": [ { "hooks": [
  { "type": "command", "command": "date '+[now: %Y-%m-%d %H:%M %Z (%a)]'" } ] } ] } }
```

Why: the model does not know the current time by itself. Without this hook, date calculations can silently be
wrong.

### Parts with no switch

These are not in the options list. They work as soon as you use them; the one that can be turned off says how.

- **Deferred triggers.** `python3 tools/triggers.py add --when date:2026-12-01 --what "review the pricing decision"`
  stores a dated trigger; the session-start hook lists the ones that are due, and `python3 tools/triggers.py list`
  shows every open one.
- **Notes between sessions.** `python3 tools/notes.py add "<at most 240 bytes>" --for <topic>` leaves a note that
  each other session on this folder is shown once, at its next prompt or start; `python3 tools/notes.py done <id>
  "<what was done>"` closes it. When to write one: [Session entry and recovery](system/rituals.md#entry).
- **Fact ledger.** `python3 tools/facts.py new <id> --claim=... --status=confirmed --speaker=me --tags=...
  --origin=<file> --origin_kind=document --domain=personal` records one fact with the existing file that holds its
  evidence, and `python3 tools/facts.py hot` builds the short hotset. A field left out is written as a TODO
  placeholder to fill in the file by hand; `facts.py check` and doctor report it until it is filled. See [Personal
  facts](system/rituals.md#facts).
- **Person ledger.** What a person decided, recorded in layers: [system/person-ledger.md](system/person-ledger.md).
  `python3 tools/person_ledger.py candidates` lists journal entries waiting for review.
- **Workers and receipts.** Broad reading, web searches and test runs can go to fresh workers with their own
  context, which return a receipt with the verdict first. `bash tools/ask.sh <runtime>[,<runtime>] <prompt-file>`
  (runtime `claude`, `codex` or `gemini`; two names run at once) runs a fresh worker on a regular UTF-8 file inside
  this workspace and returns a receipt of at most 4,096 bytes; `python3 tools/fresh_worker.py --runtime <runtime>
  <prompt-file>` does the same for one runtime with every option, and `bash tools/ask_codex.sh <prompt-file>` asks
  Codex with none. Full traces stay in
  `_private/work/runs/`, and `python3 tools/receipts.py list` and `show <run>` read them. The contract is section
  10.5 of [system/specs/PRD-session-memory.md](system/specs/PRD-session-memory.md). Gemini runs through the
  Antigravity CLI (`agy`), read-only, and each run stays in your Antigravity history. The settings are under
  `workers` (section 2).
- **Background work line.** On by default on Claude Code. A session on this folder can leave a shell command, a
  subagent or a workflow running. At session start, and at each prompt where something changed, the agent gets
  one line of at most 600 bytes: each task, how long it has run and when its output last moved. For a workflow
  whose run can be identified it also gives the agents finished in each phase. Tasks that a machine restart cut
  off are named once. The line never carries a task's output. `"work_line": "off"` in `instance/config.json`
  switches it off.
- **Prompts in Claude Code.** The kit allows no command in advance. The first time the agent runs one of the
  kit's commands, Claude Code asks, and "don't ask again" keeps that command quiet from then on. That choice is
  yours for a reason: a saved rule names the script by a path relative to wherever the agent runs it, so
  `python3 tools/now.py` would also match a same-named file in a subfolder the agent had moved into. Do not save
  such a rule in a workspace that holds folders you did not write. What the kit does ship are rules that always
  ask, in every permission mode: an edit to `tools/`, `setup.sh`, `AGENTS.md`, `CLAUDE.md`, the runtimes' hook
  folders, `instance/config.json`, `instance/rules.md`, and the three files that hold what the turn-end check
  has accepted.
  Delete the `permissions` block of `.claude/settings.json` to remove them. Codex and Antigravity have their own
  approval settings, which the kit does not write.
- **Existing material.** Move a folder of your own notes or documents into the workspace
  whole, then run `python3 tools/adopt.py FOLDER`. It moves, renames and edits nothing. It records the links
  already broken in the folder's Markdown in a file of its own in the state folder, so the turn-end check
  stops a turn only for a link the turn broke. It names instruction files inside the folder (`CLAUDE.md`,
  `AGENTS.md`, `.claude/` and the like), which a runtime reads when it works there, and
  Git repositories inside it, which keep working. It writes an inventory page in the private state folder and
  prints its path: the parts of the folder with their size and newest date, and at most 150 documents with
  their first heading. A second run drops the links that were fixed and records none broken since;
  `--again` accepts the folder as it is now, `--dry` writes nothing, and no argument lists the adopted folders.
- **A repository beside the workspace.** A code repository stays where it is: its paths, its tooling and its
  remote do not change. Start the session in this folder and add the repository to it: `claude --add-dir PATH`,
  `codex --add-dir PATH` or `agy --add-dir PATH`. In Claude Code 2.1.292 this was run in a live session: the agent
  read the repository's files without a prompt, edits there followed the usual permission rules, the kit's hooks
  and state stayed in force, and the repository's own `CLAUDE.md` was not loaded. Without the option the same read
  was refused. For Codex and Antigravity the option is in their help text and was not run by us. To keep a
  repository added in Claude Code, list it yourself under `permissions.additionalDirectories` in the local
  settings file of the `.claude` folder (settings.local.json), which Git ignores here; the kit writes no
  permission for you. The turn-end check
  reads only files inside this folder, so documents in the repository are not link-checked.
- **Thinking lenses.** Thirteen questions to look at once before committing to a design or a decision, or when the
  same fix has failed twice. They are for you first: an agent that uses one shows you its question in one line:
  [system/skills/lenses/SKILL.md](system/skills/lenses/SKILL.md). The lenses and
  [system/skills/large-jobs/SKILL.md](system/skills/large-jobs/SKILL.md) also work on their own, outside the workspace.
- **Paper workflow.** `/paper-to-kit` turns papers into proposals for the kit:
  [system/skills/paper-to-kit/SKILL.md](system/skills/paper-to-kit/SKILL.md).
- **Gardener.** `/garden` runs a cleanup audit that reports and corrects only what you delegated:
  [manual garden](system/specs/design-memory-runtime.md#manual-garden).
- **Saved headless credential.** Headless Claude calls, such as workers, use your normal login. When that login
  fails unattended, `claude setup-token` and then `python3 tools/claude_auth.py save` (hidden input, saved outside the
  repository with mode 600) are your own steps; `python3 tools/claude_auth.py check` makes one real headless call.
- **Context budget.** `python3 tools/context_budget.py` measures what every session starts with, in bytes and
  approximate tokens.

### What the built-in parts cost

| | Cost | What keeps it bounded |
|---|---|---|
| Context a new session starts with (fresh installation) | 9.8 KB, about 2,500 tokens: [the seven rules](AGENTS.md) 7.2 KB, the names and descriptions of the nine skills 2.2 KB, the state 0.4 KB (measured 2026-11-26) | `python3 tools/context_budget.py` measures your own workspace, and `doctor` warns past your threshold. |
| State put in at session start | at most 6,000 bytes | The newest decisions and the thread list go in first. What is past the limit is left out, with a count and the command that lists it. |
| The check at the end of a turn | usually under a second. It waits, up to 150 seconds, while another session on the folder is being checked. | It checks links and state only. The full test suite runs in [continuous integration](.github/workflows/gates.yml). |
| A search of past sessions | at most 4,000 bytes by default | `--full` and `--max` raise it. |
| A worker's receipt | at most 4,096 bytes | The verdict, the unknowns and the command for the full trace come before the body. |

The reason for each limit, and which limits have no recorded reason, are in section 5 of
[system/specs/model-assumptions.md](system/specs/model-assumptions.md).

<a id="config"></a>
## 2. Configuration reference (instance/config.json)

Setup copies `templates/config.json` to `instance/config.json`. Every key is described here, once. A key left
out takes the default named below. Unknown keys are accepted, so an older engine reads a newer config. After
any edit, run `python3 tools/now.py render`: editing the config makes the state page stale until it is drawn
again, and `python3 tools/now.py check` reports that. The loop's keys are not repeated here:
`python3 tools/loop/lib/loop_config.py` prints every key of the `loop` block with the value in use and what it
means.

| Key | What it does |
|---|---|
| `schema_version` | The config's format, 4 today. `bash setup.sh --force` upgrades an older one (section 3). |
| `instance.name` | The installation's name, set by setup. |
| `instance.agent_openers` | Regular expressions for the opening words of prompts that this installation's own tools send to an agent. A message that starts with one (case ignored) is not listed as the owner's words; the kit's own worker prompts are recognised without an entry. |
| `instance.root_aliases` | Earlier paths of this folder, after a move or rename, so recall still counts their sessions as this installation's. |
| `instance.recall_meaning` | The `meaning` option's settings (section 1). A slip in this block turns off only the list by meaning. |
| `egress.model_send` | `deny_prefixes` (default `["_private/"]`) and `allow_prefixes`: the paths a worker's copy leaves out. A prompt file or read material under a denied path is refused for a worker in a copy or a worktree. A worker in the instance can open those paths, and no prompt is read for their names. What Git ignores and what may be sent to a model are separate settings. An empty `deny_prefixes` is allowed: a copy still leaves out `_private/` and the kit's state. `options.py on loop` and `off loop` write the loop's send permissions here. |
| `tracks` | Active lines of work, each `{"key", "name", "canonical", "also"}` with one canonical file whose "Last updated" line the state page reads. When that line is older than the track's newest decision, `now.py check` and doctor remind you; the reminder never stops a turn. A canonical file inside this folder's `_private/` is shown as a path only and never read, also through a symlink. |
| `journal_visibility.public_tracks` | `null` after setup: every line goes to the journal behind `state/NOW.md`, unless it is logged with `--private`, which keeps it under `_private/`. An installation from an earlier version may hold a list of tracks here; then a line of a track outside the list goes under `_private/` too. A configuration that cannot be read sends every line there until it is repaired. |
| `journal_visibility.legacy_cutoff`, `legacy_public_tracks` | Set by a migration from an older config: they freeze which old rows were public, so a later list cannot promote old rows. A new installation leaves them empty. |
| `personal_pointer` | A path to a personal area shown as a pointer on the state page; its contents are never shown. `null` by default. |
| `frozen` | The paths rule 1 of `AGENTS.md` keeps read only, relative to this folder; a folder ends with `/`. The turn-end check stops a turn once when an edit tool changed one of them or a file under one. Empty by default; `instance/rules.md` section 1 says why each is frozen. |
| `threads` | Deep threads that may be shared, each `{"key", "name", "dossier"}`; `python3 tools/now.py threads` lists them. Private ones go into _private/state/threads.json in the same shape. |
| `projects.map_words` | Optional words for the map in `projects/README.md`: `head` (the table's header row), one word per status (`active`, `paused`, `planned`, `closed`) and `areas`, the order of the area headings; an area not listed follows the listed ones. Without it the map is in English. |
| `checks` | Optional lists for the link check and `tools/coherence.py`: `linkcheck_exclude_prefixes` (frozen or archived areas that keep old paths on purpose), `hubs` (pairs of folder and index file: warn when the folder holds a newer file its index does not list), `hub_ignore_ext` (default `[".pyc"]`), `status_docs` (pairs of file and allowed days: warn when the first date in its header is older), `volatile_index_words` (patterns for wording that goes stale; `now.py check` flags a `MEMORY.md` line that matches), `waiting` (prefixes of the issues an installation's own state check (a `now_instance.py` it adds to `tools/`) reports for work that waits outside any turn, such as files a pipeline has not processed: such a set stops one turn, then each prompt only says it is waiting). A missing key means none. |
| `journal_types` | The types a journal line may carry. Default: decision, state, artifact, correction, lesson, switch, idea. |
| `thresholds` | Overrides of numeric limits; a missing key keeps the default in `tools/lib/config.py` (`now_*`, `journal_stale_days`, `memory_rot_days`), `tools/context_budget.py` (`context_*_max_bytes`) or `tools/doctor.py` (`growth_*`). |
| `thresholds.now_hook_max_bytes` | The most the state view injected at session start may take, in UTF-8 bytes. Default 6000; allowed 1024 to 6000. The value 6000 has no recorded reason of its own. What is recorded is why it must stay small: Codex cuts an injected block past about 10 KB to its head and tail and gives the model a warning and the path of the full text in place of the middle (`system/dev/runtime-capture.md`, the row "Where injected context is cut"). |
| `thresholds.now_max_bytes` | The most the state pages `state/NOW.md` and `_private/state/NOW.md` may take, in UTF-8 bytes; doctor fails a page over it. Default 6000; allowed 1024 to 6000, for the same reason. |
| `thresholds.now_tail_events` | Recent events the state view lists. Default 12; at least 1. |
| `thresholds.now_recent_decisions` | Recent decisions the state view lists. Default 8; at least 1. |
| `thresholds.journal_stale_days` | Days after the last recorded event when the state page marks the journal stale. Default 2. |
| `thresholds.memory_rot_days` | Days after which `now.py check` names a Claude Code project memory that does not point to the state page. Default 14. |
| `thresholds.context_instructions_max_bytes` | `tools/context_budget.py` warns when the instruction files a session loads pass this many bytes. Default 8192. |
| `thresholds.context_memory_index_max_bytes` | The same warning for the memory index. Default 12288. |
| `thresholds.context_fixed_max_bytes` | The same warning for the whole fixed context of a session. Default 24576. The three context lines are starting values, not measurements. |
| `thresholds.growth_disk_free_min_bytes` | Doctor warns when the disk holding this folder has less free space. Default 5368709120 (5 GiB). |
| `thresholds.growth_git_max_bytes` | Doctor warns when `.git` is larger. Default 1073741824 (1 GiB). |
| `thresholds.growth_tmp_stale_days` | Days after which a file in `tmp/` counts as untouched. Default 14. |
| `thresholds.growth_tmp_stale_max_bytes` | Doctor warns when untouched files in `tmp/` take more. Default 524288000 (500 MiB). |
| `thresholds.growth_unguided_work_dirs_max` | Doctor warns when more job folders than this have no guide page (a top-level `README`, `STATE`, `HANDOFF`, `DOSSIER` or `INDEX` file). Default 10. |
| `thresholds.growth_scan_budget_ms` | The time doctor's growth checks may take together, in milliseconds. Default 1500. |
| `growth.work_dirs` | The folders whose job folders the growth check above looks at, relative to this folder. Default `["_private/work"]`. |
| `episodic_sources` | The transcript sources recall reads. Without it, recall reads this folder's Claude Code transcripts, Codex sessions under `~/.codex/sessions` and `~/.codex/archived_sessions`, and Antigravity conversations under `~/.gemini/antigravity-cli/brain` whose index places them in this folder. A list of `{"name", "kind", "base", "glob"}` rows replaces them; `{TRANSCRIPTS}` in `base` stands for this installation's Claude transcript folder. |
| `deliver` | The delivery check: `block` and `observe`, each a list of signals (section 1). Setup writes `block: ["unopened"]`; empty lists mean off. |
| `deliver.send_tools` | Tool names that count as handing a file to the owner; shell-style wildcards are allowed. Default `["SendUserFile", "Artifact"]`. |
| `deliver.reader_min_chars`, `reader_min_tools` | The `reader` signal fires on a final report of at least this many characters at the end of a turn with at least this many tool calls. Defaults 1200 and 8. |
| `workers` | Per runtime (`claude`, `codex`, `gemini`): `model`, `effort`, `where` and `web_in_instance`. Details are below the table. |
| `work_line` | `"off"` switches the background work line off. |
| `ledger.snapshot_extras` | Files beside `_private/ledger/facts/` that `python3 tools/facts.py snapshot` copies and hashes; without it only `README.md`. |
| `triggers.experiments` | A table of experiments that `python3 tools/triggers.py scan` reads when `--experiments` is not given; without it scan reads only the decision records. `triggers.sources` overrides the words scan matches. |
| `options.declined` | The optional parts you said no to; the list shows them as such. |
| `loop` | The improvement loop's settings; see `python3 tools/loop/lib/loop_config.py`. |

**`workers` in detail.** Without the key, a Claude or Codex worker runs in this folder and a Gemini worker in a
copy, each with its runtime's default model. `where` decides what the worker can open, whatever its prompt says.
`instance`: everything in this folder, `_private/` included. `copy`: a temporary folder with the kit's files and
your own folders and files, without the paths `egress.model_send` denies, the `state/`, `instance/` and `tmp/`
folders, symbolic links and package folders such as `node_modules`. A Claude or Gemini worker did not read outside
its folder when measured (macOS, Claude Code 2.1.292 and Antigravity 1.5.17). A Codex worker can read the rest of
the disk, so a copy does not keep a Codex worker out of `_private/`. The receipt names the model, the effort, the
folder and the network.

Every worker is offline. `--web` gives one call the network and its runtime's web search and runs it in a copy.
`"web_in_instance": true` under a runtime whose `where` is `instance` runs its `--web` calls in this folder
instead; the risk is that one worker then holds your private files, text from the web, and a way to send them
out. Codex's sandbox reads the whole disk, so `codex --web` runs only with that switch and is refused otherwise.

The variables `MOTTORI_FRESH_WORKER_CLAUDE_MODEL`, `MOTTORI_FRESH_WORKER_CODEX_MODEL` and
`MOTTORI_FRESH_WORKER_CODEX_EFFORT` still override the config. Example:
`"workers": {"codex": {"model": "<a model your account has>", "effort": "high"}, "gemini": {"where": "copy"}}`.

Four environment variables set a time limit that has no key here:

| Variable | What it does |
|---|---|
| `MOTTORI_FRESH_WORKER_TIMEOUT` | Seconds a worker started by `tools/fresh_worker.py` may run when its call gives no `--timeout`. Default 5400; at most 7 days. |
| `PAPERS_WINDOW_DAYS` | How many days back the loop's papers source searches arXiv. Default 14. |
| `MOTTORI_APPLY_DEADLINE` | Seconds the loop's judge, build, test and review run of one cycle (`tools/loop/papers_apply.py`, for both sources) may take in all. Default 21600 (6 hours). |
| `MOTTORI_APPLY_WORKER_TIMEOUT` | Seconds each worker start inside that run may take, within its deadline. Default 5400. |

<a id="update"></a>
## 3. Update and migrate

```bash
git pull
bash tools/install_hooks.sh --check      # Use --repair if the hook template changed
python3 tools/now.py render             # Redraw the state page first, so the baseline does not record a stale one
python3 tools/linkcheck.py && python3 tools/gate.py baseline   # Refresh if a checker changed
python3 tools/doctor.py                  # Config schema migrations appear here as FAIL
```

The first commit after an update can stop once because the state page was drawn before the update; opening a
session or `python3 tools/now.py render` draws it again. `python3 tools/linkcheck.py` should end with
`broken: 0`: a broken reference means a document points to a file this folder does not contain.

`CHANGELOG.md` is the source of truth for actions an existing installation must take: read its `[Action required]`
items after a pull. A new installation already uses the latest templates and does not repeat them.

**Config migration.** To apply setup again while keeping the config, run `bash setup.sh --force`. The name stays
unless `--name` gives another. The existing config is copied to `instance/config.json.bak-YYYYmmddTHHMMSS` after all
checks pass, under a new name on every run, so no backup is ever overwritten. Tracks, checks, public lists and every
other key the installation set (`egress`, `thresholds`) are carried over, and only keys the template has and the old
config lacks are added. Two keys of earlier versions, `instance.context` and `instance.remote_allowlist`, are no
longer used: setup drops them and says so, and a folder that was set up as `work` then commits and pushes like any
other. If a value could not be kept, setup prints its key on a line that starts with "reset to the template".

A config from before v0.10 (schema 1 to 3) is not moved: setup stops and says to move it aside and run setup again,
which writes a new config, keeps the journal rows written before it off the public page, and leaves documents as
they are. Setup does not guess when a journal or config is malformed. Run `python3 tools/doctor.py` again when setup
finishes.

**An installation made before v0.11** keeps its own files under `system/`: the config, rules, rituals, decision
records, debate rounds and the pages tools generated there. After the pull, session start, doctor and every
command that needs the config say so in one line and name `bash setup.sh --force`. Run it once. It moves each file
to its place under `instance/` or `state/`, keeping its bytes and mode, and lists what it moved; a second run moves
nothing. If a file exists at both places, it moves nothing and names both: keep the one you want, delete the other,
and run it again.

**Fixing the kit on a company machine.** Nothing carries a change from there to the public repository by itself,
and no check can prove that a change holds no company material. A person reads the diff before it leaves. For an
ordinary bug it is simpler to record only the symptom, then reproduce and fix it on your own machine.

<a id="hooks"></a>
## 4. Troubleshoot hooks and gate limits

**How each runtime was tested.** Claude Code, Codex and Antigravity CLI (`agy`) read the same `AGENTS.md`, and
each declares the kit's hooks in its own form.

| Runtime | How it was tested | One step that is yours |
|---|---|---|
| Claude Code (`2.1.292`) | Live sessions on a fresh installation | Trust the folder at the first interactive start. |
| Antigravity CLI (`agy` `1.5.14`) | Live sessions on a fresh installation. It has no hook for a compaction, so the state is given again at the next prompt. | Answer "Yes, I trust this folder" at the first start. |
| Codex (`0.169.1`) | Hooks declared, and tested by replaying captured hook inputs through the same code. Not yet run in a live session by us. | Trust the folder, then choose "Trust all" on the hooks review, once per checkout path ([SETUP.md step 3](SETUP.md#3-run-doctor-and-arm-your-runtime)). |

What each runtime sends and where they differ is in the [capture record](system/dev/runtime-capture.md).

**How the hooks are wired.** Claude Code's `.claude/settings.json` declares one line per event the kit uses
(session start, each prompt, after an edit, turn end, before compaction):
`sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" event <Event> claude`. What runs for each event is decided inside
`tools/dispatch.py`, in one process, so a kit update does not change these lines; put hooks of your own beside
them. Codex declares the same events in `.codex/hooks.json`, each
`sh "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/tools/hook.sh" event <Event> codex`, and Antigravity in
`.agents/hooks.json`, each `sh ../tools/hook.sh event <Event> agy` (no compaction event there). Do not edit these
lines, their timeouts or their order: Codex would ask for approval again. Antigravity starts no session event for
a continued conversation or after a compaction, so its next prompt gets the state when the conversation has not
received the current one. The kit's skills, such as `/now`, `/recall`,
`/dossier` and `/garden`, are copies in `.claude/skills/` and `.agents/skills/` of the folders in `system/skills/`;
doctor shows the wiring of every runtime, and its `tools · skills` row whether the copies match.

**When a hook seems silent.**

- When a step of a hook fails, the others still answer and a line goes to `state/.hook-errors.log`.
- `MOTTORI_DISABLE_HOOKS=1` in the environment makes every Claude Code event hook of the kit answer nothing, and
  doctor says so; your own lines and the direct `hook.sh TOOL` form still run.
- Codex runs no kit hook before its hooks review is approved:
  [SETUP.md step 3](SETUP.md#3-run-doctor-and-arm-your-runtime).
- At a stop Claude Code shows "Stop hook error occurred": that is the kit's turn-end check, and its reason reaches
  the model.
- Where a runtime's turn-end hook does not run, `python3 tools/gate.py manual-check` gives the turn-end verdict by
  hand.
- If this shell came from another mottori workspace, run `unset MOTTORI_INSTANCE` or set it to the absolute path of
  this folder; otherwise doctor inspects the other installation. When you test a temporary clone from inside an
  active installation, run `unset MOTTORI_INSTANCE CLAUDE_PROJECT_DIR` after entering the clone, or the tools point
  back to the parent.
- When `codex` is installed, doctor runs it for its hook checks, and that run may create Codex's own state folder
  (`~/.codex/`) in your home folder.

**Git hooks that are not the kit's.** `.git/hooks/` does not come with a clone, so setup installs the pre-commit and
pre-push hooks (`.git/hooks/pre-commit`, `.git/hooks/pre-push` and `.git/hooks/mottori-hooks.stamp`); a rerun
leaves a current pair unchanged, and an older kit version is replaced, kept as `.git/hooks/pre-*.bak.<timestamp>`.
They are needed because the turn-end check runs only when a turn-end hook runs: not for Codex without hook trust,
plain `git` outside a session, or an interrupt. The pre-commit hook checks what is being committed and the pre-push
hook what is about to be pushed. `--no-verify` still bypasses both, so they are a backstop, not a guarantee.
The kit's GitHub workflow (`.github/workflows/gates.yml`) runs only in a repository named `mottori-kit`, so a
workspace you push to your own GitHub repository under another name runs nothing there.

If another tool's pre-commit or pre-push hook already exists, setup leaves it as it is, installs the other hook
and names the hook in the way. Another tool's pre-commit hook makes doctor's hook row fail, because the kit then
checks no commit. Another tool's pre-push hook stops no commit, and doctor warns that pushes from this folder are
not checked. There are two ways forward. Either add the line the message prints right after the hook's first
line: `python3 tools/gate.py precommit || exit 1` in a pre-commit, `python3 tools/enforce.py prepush "$@" || exit 1`
in a pre-push. The installer then reports that
hook as `chained` and never rewrites it. This works for a shell hook only, and a pre-push hook that itself reads
what Git passes on standard input (`git lfs` does) cannot share it this way. Or move the existing hook out of
`.git/hooks/`, run `bash tools/install_hooks.sh --repair`, and run the old hook's checks some other way.
`bash tools/install_hooks.sh --check` reports the hooks without changing them.

When `core.hooksPath` points outside this folder, for example a global `~/.githooks`, setup installs nothing there,
because those hooks run for your other repositories too, and says so in one line. Choose one: set this repository
back to its own hooks folder with the `git config core.hooksPath ...` command the refusal prints (it names the
resolved hooks folder, which also works in a linked worktree) and run `bash tools/install_hooks.sh --repair`, or
keep your hooks folder and, for this repository, have its pre-commit run `python3 tools/gate.py precommit` and its
pre-push run `python3 tools/enforce.py prepush "$@"`, the two commands `tools/lib/precommit-hook.sh` runs. Doctor
keeps reporting the hook row as FAIL in the second case.

**A partial installation.** Before setup, a tree with neither config nor state input reports the state check as not
applicable. If `state/NOW.md` or a journal remains while `instance/config.json` is absent, the tree is a partial
installation and the gate fails closed with `config-absent`. In that state `python3 tools/now.py render` does not
publish the public page and leaves an old one unchanged, including one without a `state-content-sha256` marker.
Restore or create the config, then run `python3 tools/now.py render`; do not add a marker by hand. Without a gate
baseline the gate cannot tell a deletion from a first installation, so it fails closed: `python3 tools/linkcheck.py
&& python3 tools/gate.py baseline` creates one during a manual installation or a recovery.

**What the turn-end check sees and misses.** At the end of every turn `tools/gate.py` checks state freshness and the
links in the Markdown files Git does not ignore, plus every Markdown file an edit tool changed in this turn outside
`_private/`, `state/` and `tmp/`, even one Git ignores. The edit tools it watches are Claude Code's `Write`, `Edit`
and `NotebookEdit`, Codex's `apply_patch`, and Antigravity's `write_file` and `edit_file` with their older names
`write_to_file`, `replace_file_content` and `multi_replace_file_content`. A Markdown file written or moved by a shell
command (`mv`) in a Git-ignored folder is not checked, in every runtime, by design;
`python3 tools/linkcheck.py --filelist FILE`, with the file's path in FILE, still reports its broken link. A
link that was already broken when its folder was adopted (`python3 tools/adopt.py FOLDER`) is not counted
against the turn that edits its file. Shell edits to tracked files and other writers are seen at turn end,
because every turn end measures the documents, and at pre-commit. A turn that ends through an interrupt is
checked again at the next turn end; `gate.py resume` repeats this session's last block reason and names
another session's block once; it never measures. Two things do not block this session's turn end: an issue
that another session is already blocked on, and a broken link in a document that only another session is still
editing (KIT-DR-034 gives the conditions). Every other issue blocks whichever session ends its turn first, as
if it were alone. A turn whose edit tool changed a path listed in `frozen` stops once, for the session that
made the edit; the edit has already happened, and a shell command that changes the same path is not seen.
Issues whose prefix is listed in `checks.waiting` stop a turn once per set of them;
the same set or part of it never stops a turn again, and each prompt says the items are waiting. An
installation that keeps its own record of verdicts adds a `gate_instance.py` to `tools/` with a
`record(kind, session, new, reason)` function; the kit ships none, and nothing that module does fails the
check. `git commit --no-verify` bypasses every check.

<a id="undo"></a>
## 5. Undo setup or a migration

To undo a new installation, delete the `instance/` and `_private/` folders and everything in `state/` except the
tracked `state/.gitkeep`. Then delete the hooks setup installed, in the folder its hook lines named (`.git/hooks/`
unless `core.hooksPath` says otherwise; `bash tools/install_hooks.sh --check` names it): `pre-commit` and
`pre-push` where they are the kit's, `mottori-hooks.stamp` and any `pre-*.bak.*` backups. In another tool's hook,
remove only the line you added to it. Last, delete the gate's working files `.git/mottori-*`, such as
`.git/mottori-gate-lock`.

To undo a migration, inspect the backup and restore the newest `instance/config.json.bak-*`. Setup overwrites no
earlier backup.
