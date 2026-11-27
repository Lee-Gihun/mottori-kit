# Whom each part is for

The kit stands on the person's side. It keeps what the person said and decided as the origin, asks before
anything that cannot be undone or that leaves the machine, and returns work in a form a person can read.
It does not tell the model how to think.

Some parts are here for a different reason: a model, or the program that runs it, does not yet do
something by itself. A session loses its state when its context is compacted. A model does not know what
time it is. A part like that makes up for a gap, and a gap can close. So each such part says here what it
assumes, and it is measured again when the model or the runtime changes. If the gap has closed, the part
goes. A part that stays after its gap has closed no longer helps the model. It limits it.

This page sorts the kit's parts by that question: every core rule, hook step, optional part and skill, and
the tools behind them. It also gives the reason for each limit on what the model is shown, lists where the
kit still prescribes a method, and says what to do when a new model arrives. On the day a new model
arrives, start at section 7. Words that are the kit's own are explained in section 9.

Four labels are used:

- **Person.** Wanted however capable the model is.
- **Model.** Makes up for something a model does not do by itself. The row names it.
- **Runtime.** Makes up for something Claude Code, Codex or Antigravity does not do. The row names it.
- **Both.** The row says which half is which.

A row's basis is one of three: *measured* (a test or an incident with a number that bears on what the row
says), *outside* (a paper or a vendor's report) or *argued* (a reason with no such measurement yet). A
number the kit has about itself, and not about a model, is given as that and the row stays *argued*. The
basis cites a decision record (`decision:KIT-DR-021` is record 021 of `system/specs/kit-decisions.md`) or
a test, in the form `system/dev/evidence-schema.md` describes.

Two things about the rows. A hook step is written as its event and its name, as `tools/dispatch.py` lists
them: `SessionStart state` is the step `state` at session start. The kit's other pages call the person
"the owner". Where a basis says something happened to the owner, it happened in the installation the kit grew
from.

## 1. Parts for the person

These stay whatever the model can do.

| Part | What it keeps for the person | Basis |
|---|---|---|
| Rule 1 of `AGENTS.md`, frozen areas | Evidence, source material and personal areas the person listed in `instance/rules.md` stay as they are: they may be impossible to recover. | argued: the reason the rule gives. The turn-end check stops a turn once when an edit tool changed a path listed in `frozen`. `decision:KIT-DR-087` |
| Rule 3 of `AGENTS.md`, look up before claiming | The person's own statement stays the origin of the person's decisions; a guess is not mixed into the record, where it could not be separated later. | argued: the reason the rule gives. `evidence: none` |
| Rule 5 of `AGENTS.md`, what you hand over | Sends, commits and pushes stay the person's; a report answers in its first two sentences and can be followed and found. | measured for the rule placed in a task prompt: unrequested additions in 0 of 72 reports against 19 of 72 without it; the always-on copy is not measured. `decision:KIT-DR-022` |
| Rule 7 of `AGENTS.md`, no quiet change to a decision | A trail of what was decided when, so a later session can tell past from current requirements. | argued: the reason the rule gives. `evidence: none` |
| `SessionStart arming` | Names the runtimes whose hooks still wait for an approval that only the person can give. | argued: the approval of a runtime's hooks is the person's step. `decision:KIT-DR-042` |
| `SessionStart index` | Keeps the search of the person's own typed words caught up, behind the session. | argued: the owner decided the index is kept up to date behind the session, so a search does not wait for it. `decision:KIT-DR-055` |
| Git hooks: pre-commit (`gate.py precommit`) and pre-push (`enforce.py prepush`) | A backstop where no turn-end hook ran; a path under `_private/` does not enter a commit or leave in a push. | argued: the data border. `decision:KIT-DR-002`, `decision:KIT-DR-039`, `decision:KIT-DR-072` |
| `SETUP.md`, `system/CHECKLIST.md`, `setup.sh`, `install_hooks.sh`, `doctor.py`, `options.py`, `hook_canary.py`, `claude_auth.py` | One-time steps that are the person's (signing in, approving a runtime's hooks), and a state readable in one place. | argued. `decision:KIT-DR-011`, `decision:KIT-DR-039`, `decision:KIT-DR-052` |
| `facts.py` and its hotset | Who said a fact, and the file it came from. The hotset is the short list `facts.py hot` generates. | argued. `decision:KIT-DR-056` |
| `recall.py find` and `recall.py index` | The person's words as typed, findable later. | measured for the search by meaning: asked as one full question each, 111 of 119 earlier statements were found with the list by meaning beside the list by words, against 75 with the list by words alone. `decision:KIT-DR-046`, `decision:KIT-DR-055` |
| `triggers.py`, `notes.py`, `person_ledger.py` | The person's dated items, the notes the person would otherwise carry from one session to another, and the candidates for the ledger of what is already decided about the person (`system/person-ledger.md`). | argued. `decision:KIT-DR-044`, `decision:KIT-DR-038` |
| `adopt.py` | The person's existing material comes in as it is: nothing is reorganized on the first day, and no turn is stopped for a link that was already broken. | argued: reproduced in a fresh installation, where every edit of an old document stopped the turn once for a link the turn had not broken. `decision:KIT-DR-069` |
| `context_budget.py`, `linkcheck.py`, `coherence.py`, `skills.py`, `tasks.py`, `gate.py` baseline, manual-check and status | Checks the person can run by hand: what each session costs in fixed context (`context_budget.py`), links that can be followed (`linkcheck.py`), documents that disagree (`coherence.py`), skill copies that match their sources (`skills.py`), what runs in the background (`tasks.py`), and what the turn-end check found (`gate.py`). | argued. `decision:KIT-DR-025`, `decision:KIT-DR-030`, `decision:KIT-DR-063`, `decision:KIT-DR-034` |
| `tools/dev/skill_probe.py` | Starts real, billed sessions only after the person's yes, and records whether the thinking skills open, for the person who maintains the kit. | argued: the instrument of section 7 of this page. `decision:KIT-DR-065` |
| `tools/dev/evidencecheck.py`, `tools/dev/eval_recall.py`, `tools/dev/build_memory_map.py`, the tests under `tools/tests/` and the rules table (`system/dev/enforcement.md`) | For the person who maintains the kit: what the kit says about itself can be checked. | argued. `decision:KIT-DR-064` |
| `tools/hook.sh`, `tools/dispatch.py` and the notice of hook failures at session start | Every runtime event goes through one launcher that always answers, and a hook that failed leaves a line the person and doctor can read. | argued from an incident: in the original workspace a hook that failed looked installed and died silently. `decision:KIT-DR-001`, `decision:KIT-DR-042` |
| The documents `AGENTS.md` sends an agent to: `system/code-writing.md`, `system/debate/README.md`, `system/person-ledger.md` and the sections of `system/rituals.md` | How code and comments read to the next person, how two vendors' models argue a decision the person will make, what is recorded about the person, and the boundaries: what leaves the machine, what a browser may click. Section 6 lists where they prescribe a method. | argued. `decision:KIT-DR-017`, `decision:KIT-DR-043` |
| `system/skills/now/` | One command that shows the person the merged state and asks before any repair of the four critical kinds (`system/rituals.md#memory`). | argued. `decision:KIT-DR-035`, `decision:KIT-DR-063` |
| `system/skills/recall/` | The person's original words, quoted in the few lines that matter. | argued. `decision:KIT-DR-025`, `decision:KIT-DR-063` |
| `system/skills/garden/` | A report-only audit the person reads; it asks only on the four critical kinds. | argued. `decision:KIT-DR-035`, `decision:KIT-DR-063` |
| `system/skills/paper-to-kit/` | Papers become proposals graded by evidence; no kit file changes without the person. | argued. `decision:KIT-DR-035`, `decision:KIT-DR-063` |
| `system/skills/plain-writing/` | Text a person outside will read is written for that reader, and the person sends it. | measured: drawn from 63 drafts the owner had sent back (`system/skills/plain-writing/guide.md`); the 10-text pilot of KIT-DR-009 has no recorded result. `decision:KIT-DR-008`, `decision:KIT-DR-009` |
| `options.py on meaning` | The search by meaning runs on this machine, so the person's words never leave it. | measured: 111 of 119 earlier statements found, against 75 with the list by words alone (the `recall.py` row above). `decision:KIT-DR-046` |
| The Codex line of `python3 tools/options.py` | A model of another vendor, so the person's work is not tied to one. | argued. `decision:KIT-DR-043` |
| `options.py on loop`, the loop's consent and schedule (`loops.py start`) | Says what each source sends and takes a yes per source before anything is scheduled. | argued. `decision:KIT-DR-057`, `decision:KIT-DR-058` |
| Loop: person-ledger lane | Additions to the person ledger drafted only when the person turned the lane on. | argued. `decision:KIT-DR-059` |
| Loop: papers (sweep, triage, select, fetch, cards, proposals, digest) | New outside knowledge reaches the kit as proposals and a digest the person reads. | argued. `decision:KIT-DR-057`, `decision:KIT-DR-059` |
| Loop: judge | Chooses what is built from the proposals, at most two bundles a cycle, so what the person must read stays small. | argued; the number has no recorded reason (section 5). `decision:KIT-DR-059`, `decision:KIT-DR-061` |
| Loop: saved patch, report and journal line | The loop ends at a reviewed patch and applies nothing; the person's agent applies it. | argued. `decision:KIT-DR-061` |
| Loop: health check | Writes only when there is a problem, once when seen and once when over. | argued. `decision:KIT-DR-057`, `decision:KIT-DR-060` |
| Loop: token ceiling | The person's quota: no new stage starts past the ceiling the person set. | argued. `decision:KIT-DR-059` |

## 2. Parts that make up for a model

Each row is a candidate to remove. "Try without it" says how to turn the part off today.

- **Rule 4 of `AGENTS.md`, dossier before a deep thread**
  - Assumes that a model does not keep other threads after its context is compacted: compaction keeps the
    current task and flattens the rest.
  - Basis: argued: that is the reason the rule gives. The kit's own number is about its view, not about a
    model: compaction rows had taken 68 of 70 lines of the recent decisions in the original installation's
    journal, so dossiers are now shown first. `decision:KIT-DR-021`
  - Try without it: delete rule 4 from `AGENTS.md`, or register no threads
- **`SessionStart state`, `PreCompact precompact`**
  - Assumes that a model does not carry what was decided and what is open into a new session or past a
    compaction. The precompact step writes the compaction into the journal so the next view shows it.
  - Basis: argued: a new session has none of the last one's conversation, and the reason rule 2 gives is that
    compaction swallows state kept in conversation. What the view shows first is `decision:KIT-DR-021`.
  - Try without it: `MOTTORI_DISABLE_HOOKS=1` turns off every hook of the kit; these two steps alone only by
    editing code (`tools/dispatch.py`)
- **`UserPromptSubmit time`**
  - Assumes that a model does not know the current date and time.
  - Basis: argued: `MANUAL.md` section 1 says the model does not know the current time by itself.
    `evidence: none`
  - Try without it: only by editing code (`tools/dispatch.py`). The step already prints nothing where the
    user's own hooks in Claude Code or Codex inject the time.
- **`Stop deliver`, `options.py on deliver`**
  - Assumes that a model does not reread a long document it wrote before handing it over.
  - Basis: measured on 8,817 past turns: the signal `unopened` (a document written in the turn and handed over
    without being opened again) was right in 35 of 40 sampled hits, and the signal `reader` (a long report at
    the end of a long working turn) in 14 of 40. `decision:KIT-DR-022`
  - Try without it: `python3 tools/options.py off deliver` (it is off by default)

## 3. Parts that make up for a runtime

These go when the runtime does the thing itself, whatever the model can do.

- **`SessionStart tasks`, `UserPromptSubmit tasks`, `Stop tasks`**
  - Assumes that the runtime does not show the agent what runs in the background without a tool call, what a
    restart cut off, or what another session runs.
  - Basis: measured in 30 headless runs of three designs: of the 16 questions per design about how a job was
    going, the agent answered without a tool call 0 times with no work line, 4 times with a line when the work
    changed and 2 times with a line at every prompt. `decision:KIT-DR-045`
  - Try without it: `"work_line": "off"` in `instance/config.json`
- **The History line of `python3 tools/options.py`**
  - Assumes that the runtime does not keep transcripts: Claude Code deletes them after `cleanupPeriodDays`, 30
    days by default.
  - Basis: outside: the runtime's own setting and default. `evidence: none`
  - Try without it: the line only reports the days; the setting is in Claude Code's settings files, the
    folder's or the user's
- **`SessionStart restate`, `UserPromptSubmit restate` (Antigravity only)**
  - Assumes that the runtime does not send an event for a compaction or a continued conversation, so the state
    is given again when the transcript shows a compaction (a `CHECKPOINT` row).
  - Basis: measured by the capture of what Antigravity sends: `decision:KIT-DR-042`
  - Try without it: only by editing code (`tools/dispatch.py`)
- **A finding blocks once per turn (the turn record, `tools/lib/turns.py`)**
  - Assumes that the runtime does not end a turn that a hook keeps blocking. A reason blocks once in a turn;
    one that is still there is held and said at the next prompt. Antigravity's continuation flag stays false,
    so the kit reads its execution count and keeps its own record.
  - Basis: measured by the capture: `decision:KIT-DR-042`, `decision:KIT-DR-053`,
    `test:tools/tests/test_dispatch.py::test_each_finding_blocks_once_per_turn`
  - Try without it: only by editing code (`tools/dispatch.py`, `tools/lib/turns.py`)

## 4. Parts that do both

- **Rule 2 of `AGENTS.md`, state on disk and logging**
  - The person's half: The record outlives the chat, what the person keeps under `_private/` stays out of Git
    and out of anything written for others, and a rule the person confirmed is not overridden by a newer file.
  - The model's half: The model loses what was said when its context is compacted.
  - Basis: argued. `decision:KIT-DR-006`, `decision:KIT-DR-021`
  - Try without the model's half: the logging duty only by deleting its sentences from rule 2; the injected
    view as in the state row of section 2
- **Rule 6 of `AGENTS.md` and `system/skills/large-jobs/`**
  - The person's half: A success measure fixed before the run, so the person can judge the result.
  - The model's half: Unclear: the resume half answers usage limits and interruptions, which belong to the
    environment as much as to the model.
  - Basis: argued from one run of 660 papers (`system/skills/large-jobs/frame.md`). `evidence: none`
  - Try without the model's half: delete rule 6 from `AGENTS.md`, or the skill's folder from `system/skills/`,
    `.claude/skills/` and `.agents/skills/`
- **`SessionStart reminders`**
  - The person's half: The person's own dated items surface on their date.
  - The model's half: The model does not raise a dated item unprompted.
  - Basis: argued. The kit's own incident is about the reminders, not about a model: six notices for the owner
    stopped being shown after three showings and none was handled. `decision:KIT-DR-027`,
    `decision:KIT-DR-038`, `test:tools/tests/test_triggers.py::test_hook_limits_and_auto_sleep_after_ignores`
  - Try without the model's half: keep the reminder store empty; there is no switch
- **`SessionStart notes`, `UserPromptSubmit notes`**
  - The person's half: The person is not the messenger between sessions, and a note is never the person's
    approval.
  - The model's half: A session does not see what another session on the folder learned. Unclear whether this
    is the model's gap or the runtime's.
  - Basis: argued from the owner's habit of moving between sessions. `decision:KIT-DR-044`
  - Try without the model's half: leave no notes; there is no switch
- **`Stop gate`, `PostToolUse edited` (which files the turn changed), `UserPromptSubmit resume` (what the last
  turn left)**
  - The person's half: What is handed over can be followed: links resolve and the state page is fresh. A
    memory index that names files that do not exist is a reminder, not a block.
  - The model's half: Agents leave broken links and stale state at the end of a turn.
  - Basis: measured, and the number is small: in the original installation about 10 of 395 blocks were caused
    by the turn that was blocked, and 240 of the 316 that carried a session name repeated the block before, so
    the check now looks only at what the session changed. `decision:KIT-DR-020`, `decision:KIT-DR-034`,
    `test:tools/tests/test_install_checks.py::test_gate_check_blocks_when_measure_raises`,
    `test:tools/tests/test_enforce.py::test_resume_reports_pending_reason_without_measuring`
  - Try without the model's half: `MOTTORI_DISABLE_HOOKS=1` (every hook); `python3 tools/gate.py baseline`
    adopts the current issues
- **`now.py` log, context, threads, check and render**
  - The person's half: The state ledger and its views, readable by the person.
  - The model's half: As rule 2: the model does not keep state across a compaction.
  - Basis: argued. `decision:KIT-DR-006`, `decision:KIT-DR-021`, `decision:KIT-DR-036`
  - Try without the model's half: the views are only read when called; the state row of section 2
- **`fresh_worker.py`, `ask.sh`, `ask_codex.sh`, `receipts.py`**
  - The person's half: The person's attention: a receipt (the short report a worker hands back) that can be
    judged alone, the vendor the person chose, a copy that leaves the private folders out.
  - The model's half: The main session's context fills up with broad reading.
  - Basis: argued. `decision:KIT-DR-007`, `decision:KIT-DR-023`, `decision:KIT-DR-043`
  - Try without the model's half: do the broad work in the main session: a worker runs only when called
- **`system/skills/dossier/`**
  - The person's half: One command to resume a thread from its file.
  - The model's half: Compaction flattens the threads other than the current one.
  - Basis: argued. `decision:KIT-DR-021`, `decision:KIT-DR-063`
  - Try without the model's half: delete the skill's folder from `system/skills/`, `.claude/skills/` and
    `.agents/skills/` (`skills.py write` leaves a copy with no source alone)
- **`system/skills/lenses/`**
  - The person's half: The owner said a lens helps a person's insight, and that what steers a person's
    thinking is seeing it. So the table can be used without an agent, and an agent that uses a lens shows the
    owner its question in one line.
  - The model's half: Unclear: the owner also said it must not bind the model. The skill assumes a model may
    not look from another side before it commits to a design or decision.
  - Basis: measured on one model, in installations of the kit alone (section 8): a thinking skill opened in 10
    of 30 runs where one should and in 0 of 30 where none should; and answers with the lens skill opened were
    preferred by three blind judges in 52%, 58% and 56% of the decided pairs over an installation without it,
    which is no difference by the line set beforehand. After that the skill was changed to show the owner the
    question, and it did in 9 of 9 runs where it opened (`decision:KIT-DR-066`). The earlier 24 of 30, and 16
    of 30 blind pairs against 9, were measured with another instruction file also in context.
    `decision:KIT-DR-065`, `decision:KIT-DR-063`, `decision:KIT-DR-019`
  - Try without the model's half: delete its line in `AGENTS.md` and the skill's folder from `system/skills/`,
    `.claude/skills/` and `.agents/skills/`
- **`system/skills/deep-pass/`**
  - The person's half: Five returns the person can check, ending in one recommendation.
  - The model's half: Unclear: steps 3, 4 and 6 prescribe a method and give no reason on record.
  - Basis: argued. `decision:KIT-DR-063`, `decision:KIT-DR-018`
  - Try without the model's half: delete its line in `AGENTS.md` and the skill's folder from `system/skills/`,
    `.claude/skills/` and `.agents/skills/`
- **Loop: builder, sandbox tests, commit check and a reviewer that did not build**
  - The person's half: The loop writes nothing into the person's tree: it builds in a copy, runs the tests in
    a deny-by-default sandbox, and ends at a saved patch.
  - The model's half: The model that builds a change can be wrong, and a model's agreement with itself is not
    independence, so a reviewer from another model family is tried first.
  - Basis: argued. `decision:KIT-DR-058`, `decision:KIT-DR-059`, `decision:KIT-DR-061`, `decision:KIT-DR-018`
  - Try without the model's half: only by editing code (`tools/loop/`); with a single runtime in
    `loop.runtime_orders` the reviewer has no other family

## 5. Limits on what the model is shown

A person's attention is scarcer than tokens, so a cap on what the model sees needs a reason of its own.
These are the caps: how many bytes, lines or items a hook, a tool or a prompt lets through. Where the kit
has no recorded reason for a value, the row says so. Time budgets and lock waits are mechanics and are
explained beside their constants in the code. A setting named in the last column is a key of
`instance/config.json` (`MANUAL.md` section 2). The list was made by reading the code on 2026-11-26, and
a cap that is missing from it is a defect of this page.

| Limit | Value | Set in | Why this value | Change it |
|---|---|---|---|---|
| State injected at session start | 6,000 bytes | `tools/lib/config.py`, `now_hook_max_bytes` | No recorded reason for 6,000 itself: it is older than the capture (`decision:KIT-DR-021` says the cap is unchanged). What is recorded is why it must stay small: Codex cuts an injected block past about 10 KB to its head and tail, and gives the model a warning and the path of the full text in place of the middle (`system/dev/runtime-capture.md`, the row "Where injected context is cut"). | `thresholds.now_hook_max_bytes`, 1024 to 6000 only; the range has no recorded reason either |
| The NOW page | 6,000 bytes | `tools/lib/config.py`, `now_max_bytes` | Kept at the injection's cap; no recorded reason of its own (`decision:KIT-DR-021` says the cap is unchanged). | `thresholds.now_max_bytes`, 1024 to 6000 only |
| Recent events and recent decisions in the view | 12 and 8 | `tools/lib/config.py`, `now_tail_events`, `now_recent_decisions` | no recorded reason; a starting value | `thresholds.now_tail_events`, `thresholds.now_recent_decisions` |
| How a page over its cap shrinks | recent events down to 3, then decisions down to 2, then event bodies cut to 256 bytes and halved down to 32, then dossier rows from the end of the list, then the last recent events and all but one decision | `tools/now.py`, `_smaller_page` | The order is explained in `_fit_snapshot`'s docstring (dossier rows outrank long bodies, because a new session needs them to resume a thread); the numbers 3, 2, 256 and 32 have no recorded reason; a starting value. | only by editing code |
| A track's latest line in the state view | 110 characters | `tools/now.py`, `_track_snippet` | no recorded reason; a starting value | only by editing code |
| The notice of hook failures at session start | the last failure cut at 240 bytes | `tools/now.py`, where the notice is built | no recorded reason; a starting value | only by editing code |
| One journal row | 300 characters | `tools/lib/journal.py`, `BODY_MAX` | Its refusal says a journal row records one event, not a document. | only by editing code |
| Notes from other sessions | a note 240 bytes, a topic 40 bytes, at most 5 shown, 600 bytes together | `tools/notes.py`, `TEXT_MAX`, `TOPIC_MAX`, `SHOW_MAX`, `PRINT_MAX` | no recorded reason; a starting value (`decision:KIT-DR-044` sets them) | only by editing code |
| Reminders at session start | at most 5; a field cut at 200 characters | `tools/triggers.py`, `HOOK_LIMIT`, `HOOK_FIELD_CHARS` | no recorded reason; a starting value | only by editing code |
| The background work line | 4 tasks per session, 600 bytes; a task's description cut at 80 characters | `tools/tasks.py`, `SHOWN`, `MAX_BYTES` | The comment says the rest are counted so the line stays short; the numbers have no recorded reason (`decision:KIT-DR-045` measured the line, not its size). | `"work_line": "off"` turns the whole line off |
| Recall's default output | 4,000 bytes; at most 8 hits; excerpts of 180 and 120 characters; notices 200 and 600 bytes | `tools/lib/recall_literal.py`, `COMPACT_MAX_BYTES`, `COMPACT_SNIPPET_CHARS`, `COMPACT_NEARBY_CHARS`, `NOTICE_QUERY_MAX_BYTES`, `NOTICE_LINE_MAX_BYTES`; `tools/recall.py`, `--max` default 8 | A common word printed about 18 KB in full (the comment beside `COMPACT_MAX_BYTES`, `decision:KIT-DR-025`); the excerpt lengths are about two or three terminal lines. | `--full`, `--max N` |
| Messages around a hit | 0 in the short form; 2 with `--full`, `--json` or a message opened by its locator | `tools/recall.py`, `FULL_AROUND_DEFAULT` | no recorded reason; a starting value | `--around N` |
| Recall's `--full` output | an excerpt of 260 characters around the hit; each message beside it cut at 200 | `tools/lib/recall_literal.py`, `_snip` and the printing of `--full` | no recorded reason; a starting value | only by editing code |
| `recall.py sessions` | the newest 40 session files | `tools/recall.py`, `sessions` | no recorded reason; a starting value | only by editing code |
| What a search of the owner's words leaves out | one message: the newest of the session written last, when it was typed in the last 10 minutes; the search says so | `tools/lib/recall_store.py`, `RECENT_MINUTES`, `_asking` | The message of the turn that is asking is already in its transcript and would match itself. Measured in two fresh installations: with the earlier rule, which left out everything typed in the last ten minutes, a new session could not quote what the owner had typed a minute before; with this rule it quoted it (`decision:KIT-DR-077`). The ten minutes have no recorded reason. | only by editing code |
| Recall's list lines | a list line 150 characters; 4 short-reply lines, 2 of them by meaning; 4 word lines beside the meaning list; 300 characters kept before a short reply; a message kept to 2,000 characters | `tools/lib/recall_store.py`, `LINE_CHARS`, `SHORT_LINES`, `SHORT_BY_MEANING`, `BESIDE_LINES`, `TAIL_CHARS`, `TEXT_CHARS` | The comments say what each does; `TEXT_CHARS` keeps the store small because a few long pasted messages hold most of the text. The other numbers have no recorded reason; a starting value. | `--max` for the list lengths; the rest only by editing code |
| A reminder shown without being acted on | sleeps 7 days after 3 showings; retired after 2 sleeps | `tools/triggers.py`, `IGNORE_LIMIT`, `AUTO_SLEEP_DAYS`, `RETIRE_AFTER_SLEEPS` | no recorded reason; a starting value | only by editing code |
| A note between sessions | kept 7 days | `tools/notes.py`, `DAYS` | no recorded reason; a starting value | only by editing code |
| Doctor's growth check | warns below 5 GB free disk, a `.git` over 1 GB, `tmp/` files over 500 MB untouched 14 days, more than 10 work folders without a guide page; the scan stops after 1.5 s | `tools/doctor.py`, `GROWTH_DEFAULT_LIMITS` | no recorded reason; starting values | `thresholds` in `instance/config.json` |
| A worker's receipt | 4,096 bytes; a header line 512 bytes | `tools/receipts.py`, `RECEIPT_MAX_BYTES`, `RECEIPT_LINE_MAX_BYTES` | Bytes bound the caller's context cost evenly across languages (the comment); the value was kept, not measured (`decision:KIT-DR-023`). | only by editing code |
| A failed worker's stderr in the receipt | 3 lines, 300 characters | `tools/fresh_worker.py`, `STDERR_TAIL_LINES`, `STDERR_TAIL_CHARS` | no recorded reason; a starting value | only by editing code |
| A block's cause | 300 characters | `tools/gate.py`, `CAUSE_LIMIT` | no recorded reason; a starting value | only by editing code |
| Delivery check: a document | 1,500 characters | `tools/deliver.py`, `MIN_DOCUMENT_CHARS` | A shorter document is cheap to check in the message itself (the comment). | only by editing code |
| Inventory of an adopted folder: documents listed | 150, newest first; a first heading cut at 80 characters | `tools/adopt.py`, `MAX_DOCUMENTS`, `HEADING_CHARS` | no recorded reason; a starting value for one page an agent reads whole | only by editing code |
| Inventory of an adopted folder: parts listed | 40 | `tools/adopt.py`, `MAX_CHILDREN` | no recorded reason; a starting value | only by editing code |
| Delivery check: the `reader` signal | 1,200 characters and 8 tool calls | `tools/deliver.py`, `reader_min_chars`, `reader_min_tools` | no recorded reason; a starting value (`decision:KIT-DR-022` measured the signal's hit rate, 14 of 40) | `deliver.reader_min_chars`, `deliver.reader_min_tools` |
| Delivery check: the owner's request quoted back | 600 characters | `tools/deliver.py`, where the message is built | no recorded reason; a starting value | only by editing code |
| Fixed-context warnings | 8,192, 12,288 and 24,576 bytes | `tools/context_budget.py`, `DEFAULT_LIMITS` | Starting values, not measurements (`decision:KIT-DR-025`). | `thresholds.context_instructions_max_bytes`, `thresholds.context_memory_index_max_bytes`, `thresholds.context_fixed_max_bytes` |
| The hotset | 60 facts | `tools/facts.py`, `HOT_CAP` | The PRD requires a cap; the comment says the value 60 has no recorded source. | only by editing code |
| Loop: bundles a cycle (a bundle is one proposed change with its files) | at most 2 (one observe, one act) | `tools/loop/lib/loop_judging.py` ("one observe and one act bundle per cycle"), said again in the prompts of `tools/loop/lib/loop_prompts.py` | no recorded reason; a starting value | only by editing code |
| Loop: files a bundle | at most 8 | `tools/loop/lib/loop_judging.py`, `MAX_FILES` | no recorded reason; a starting value | only by editing code |
| Loop: papers read in full | at most 8 a cycle | `tools/loop/lib/loop_papers.py`, `READ_PER_CYCLE` | no recorded reason; a starting value | only by editing code |
| Loop prompt `card.md` | at most 25 lines per paper; one or two lenses | `system/loop/prompts/card.md`, "at most 25 lines" | no recorded reason; a starting value | only by editing the prompt |
| Loop prompt `triage.md` | scores 0 to 3; at most 15 papers score 3 | `system/loop/prompts/triage.md`, "at most 15 papers" | no recorded reason; a starting value | only by editing the prompt |
| Loop prompt `propose.md` | the last three cycles; at most 120 lines | `system/loop/prompts/propose.md`, "at most 120 lines" | no recorded reason; a starting value | only by editing the prompt |
| Loop prompt `digest-en.md` | 400 to 600 words; 3 to 5 papers; 1 to 3 papers that did not hold up | `system/loop/prompts/digest-en.md`, "400 to 600 words" | no recorded reason; a starting value | only by editing the prompt |
| The loop's built prompts | up to three earlier cycles | `tools/loop/lib/loop_prompts.py`, "up to three earlier cycles" | no recorded reason; a starting value | only by editing code |
| Skill `garden` | three claims per dossier; `--max 2 --around 1`; a report under 120 lines | `system/skills/garden/SKILL.md`, "three claims" | no recorded reason; a starting value | only by editing the skill |
| Skill `lenses` | one or two of thirteen questions | `system/skills/lenses/SKILL.md`, "one or two rows" | The thirteen are a choice made to keep the table manageable (`system/skills/lenses/guide.md`); "one or two" has no recorded reason. | only by editing the skill |

## 6. Where the kit still prescribes a method

A boundary with the person is the kit's business: what is recorded, what is asked, what is shown and in
what form. A method is the model's own business unless there is a reason: steps in a fixed order, a
quantity, "always use this". These are the places where the kit still prescribes a method. A reason on the
person's side keeps the place. A reason about the model, or no reason, makes it a candidate to try without
when the model changes.

| Where | What it prescribes | Reason on record |
|---|---|---|
| `AGENTS.md` (10 places) | Run `now.py context` when no state arrived; log decisions in the same turn; `facts.py find` and `recall.py find` before a claim; read the dossier first; answer in the first two sentences; read the `large-jobs` skill before a large task; the routing lines to `lenses` and `deep-pass`. | person for most (the owner learns hooks are off; the owner's words are the origin; a report that can be followed); model for logging ("compaction swallows state") and the dossier; none for the routing lines |
| `system/skills/now/SKILL.md` | Read, summarize, run `now.py check`, apply safe repairs, propose the rest, in that order. | person (the four critical kinds) |
| `system/skills/recall/SKILL.md` | Quote only the few lines that matter; on a miss, look at source, parser, filter, ranking and wording. | person (attention) for the first; none for the second |
| `system/skills/dossier/SKILL.md` | Summarize position, settled conclusions and open questions, then begin. | none in the file |
| `system/skills/garden/SKILL.md` | Five numbered steps; three claims per dossier; `--max 2 --around 1`; a report under 120 lines with fixed sections. | person (the owner reads the report); none for the quantities |
| `system/skills/paper-to-kit/SKILL.md` | Five stages; one worker per paper; a reviewer who wrote no card; every card checked, not a sample. | person for the four critical kinds; none for the stage method beyond traceable evidence |
| `system/skills/lenses/SKILL.md` | Work the problem your own way first, then look at the table once; one or two rows; show the owner the question in one line. | person (the owner thinks with a question the owner can see; the owner's condition that a lens must not bind the model) |
| `system/skills/deep-pass/SKILL.md` | Seven steps; read the owner's words before options; try to break the favoured answer; a fresh reader; another vendor attacks; five returns. | person for the five returns; none for steps 3, 4 and 6 |
| `system/skills/plain-writing/SKILL.md` | Six steps in a fixed order; no em dash; the owner sends it. | person (the recipient's reading; the owner sends) |
| `system/skills/large-jobs/SKILL.md` | Answer six questions or the job is not ready; one number true of the whole body; write each item as it finishes. | person for the whole skill (how much a person can take in); model for the worker scope |
| `system/skills/deep-pass/steps.md` (about 20) | Read current files before alternatives; write the prediction before the test; change the actual operation when output turns formulaic; ask a different model family to attack an assumption. | model for the formulaic-output case; none for most |
| `system/skills/large-jobs/frame.md` (about 25) | Do not run broad reading inside the main session; write after each item; judge frozen targets by content hash; let the main session write the result. | model (the main context, `decision:KIT-DR-007`) and one run of 660 papers |
| `system/skills/lenses/guide.md` | Close each lens used with "What to leave behind" in the record; record changed and unchanged verdicts. | model (lines that only listed kept repeating); person for the record |
| The thirteen lens pages in `system/skills/lenses/` (each with a "What to leave behind" line and 5 to 22 method bullets) | `inversion.md`: write two or three reasons the work failed; `feynman.md`: a prediction written in advance; `isomorphism.md`: at most two mappings. | none on the person's side: method arguments from their sources |
| `system/skills/plain-writing/guide.md` (about 30) | Two lines before the body; a four-line form; three gates; one fact that makes a request smaller and one line of thanks. | person (63 rejected drafts; the recipient); drop conditions stated in the guide |
| `system/rituals.md` (about 30) | Read the page at the top of a folder first, because numbers in the conversation go stale; do not move on after seeing only the exit code, because a tool finishing and its target being correct are separate facts. | model for the first; the truth of what is handed over for the second |
| `system/loop/prompts/card.md` | Seven sections in this order; at most 25 lines; work the cards your own way, then one or two lenses. | none |
| `system/loop/prompts/triage.md` | Be strict: at most 15 papers score 3. | none |
| `system/loop/prompts/propose.md` | Read the reports of the last three cycles; at most two bundles; at most 120 lines. | model (avoid repeating a failure) |
| `system/loop/prompts/digest-en.md` | 400 to 600 words; 3 to 5 papers; papers that did not hold up. | person (the owner reads it) |
| `tools/loop/lib/loop_prompts.py` (builder and reviewer prompts) | Follow the existing test style; the reviewer's blocking list, one blocking defect is a FAIL. | person (protects the owner's tree) for the reviewer; none for the test style |
| Texts tools print for the model: `tools/gate.py`, `tools/deliver.py`, `tools/tasks.py`, `tools/receipts.py` | Fix links before finishing; look once more and say what you fixed; report a background job by its phase counts; name a source for every claim and end with one machine-readable line. | person (a report the owner can read and claims the owner can check); model for the reread; for the phase counts, fewer tool calls and tokens (`decision:KIT-DR-045`) |

## 7. When the model changes

Nothing here runs by itself. A vendor announces a new model, and then a person decides to look.

1. Make a throwaway installation: clone the kit into a new folder and run
   `bash setup.sh --name probe` there. Choose a place with no `CLAUDE.md` in any folder
   above it. Claude Code reads those too, and the probe refuses such an installation.
2. Measure whether the thinking skills still open when they should and stay closed when they should not.
   From the kit's own clone, with `../probe` the throwaway installation:
   `python3 tools/dev/skill_probe.py ../probe system/dev/skill-probe-tasks.json --runs 3`.
   That is 60 real Claude Code sessions on your account, one at a time, each billed and capped at $2 by
   default (`--budget-usd`), so the tool first says what it would start and starts it only after a yes.
   It prints the model the sessions named and the program's version, one line per task (whether it should
   open a skill, in how many of the three runs one was opened, and which), then four totals: a thinking
   skill opened in X of 30 runs where it should be and in Z of 30 where it should not, the median answer
   length and the summed cost. On 2026-11-26 the 60 sessions took 15 minutes and cost $3.79 together. It
   measures Claude Code only, on the account's default model unless `--model NAME` says another. A session
   started this way is headless: nobody is there to approve a command, so the lookups the rules ask for
   are refused. The rows of section 8 were measured the same way.
   Compare the two counts with the newest row of section 8. The probe says whether a skill was opened. It
   does not say whether the answer was better.
3. Go through sections 2 and 4. Most rows have no ready measurement, and the page does not pretend they do.
   Where you have a reason to think a gap has closed (the vendor says so, or you see the part firing for
   nothing), work in the throwaway installation with that part turned off as its row says, and see whether
   the failure its basis describes comes back. Deleting a skill leaves links to it in other pages, and
   doctor then fails on them; there `python3 tools/gate.py baseline` adopts them, so the turn-end check
   does not step in.
4. Write what you measured as a new row in section 8. When a part changes or goes, write a decision record.

## 8. Measurements so far

- **2026-11-26, claude-opus-5-5; Claude Code 2.1.292**
  - What was measured: The probe of section 7 again, after the lens skill was changed to show the owner the
    question it asked
  - Result: A thinking skill opened in 15 of 30 runs where one should (lenses 9, deep-pass 4, plain-writing 2)
    and in 0 of 30 where none should. In all 9 runs where the lens skill opened, the answer ended with a line
    that named the lens and its question. Before the change 3 of 26 answers written with the lens skill opened
    named the lens, all three on the task that asks for one. Median answer 823.5 characters over all sixty; 15
    minutes; $3.96.
  - Record: `decision:KIT-DR-066`
- **2026-11-26, claude-opus-5-5; Claude Code 2.1.292**
  - What was measured: Whether an answer is better with the lens skill opened (step 3 of section 7, tried on
    the lens skill): the ten tasks that should open one, three runs each, in an installation without the lens
    and deep-pass skills and in one told to open the lens skill. The 26 pairs where the skill really opened
    were judged blind by models of three vendors, and two of them marked one point per task, fixed beforehand,
    as made or not.
  - Result: The lens side was preferred in 11, 15 and 14 of the 26 pairs against 10, 11 and 11: 52%, 58% and
    56% of the decided pairs, and the line written before the runs called anything between 40% and 60% no
    difference. The fixed point was made in 21 of 23 answers with the lens and in 20 of 23 without, the same
    for both judges. The answers were as long (median ratio 0.91), and thirty sessions cost $3.35 with the
    lens against $2.71 without. One model, tasks answered in one turn, and a skill opened because a line said
    so, not because the model chose to.
  - Record: `decision:KIT-DR-065`
- **2026-11-26, claude-opus-5-5; Claude Code 2.1.292**
  - What was measured: Whether a thinking skill opens unasked: the probe of section 7, twenty tasks with three
    runs each, in an installation with no other instruction file above it
  - Result: Opened in 10 of 30 runs where one should (lenses 7, deep-pass 2, plain-writing 1; five of the ten
    tasks never opened one) and in 0 of 30 where none should. In 27 of those first 30 runs the session's shell
    command, a lookup the rules ask for, was refused, because a headless session has nobody to approve it, so
    these are answers given without the lookups. Median answer 867.5 characters over all sixty; 15 minutes;
    $3.79.
  - Record: `decision:KIT-DR-065`
- **2026-11-26, One model, which the record does not name; Claude Code**
  - What was measured: Whether the lens skill opens unasked, and answers with and without lenses
  - Result: Opened in 24 of 30 runs where it should have been (ten task sentences, three runs each) and in 0
    of 20 where it should not; across the four installations tried it was never opened where it should not be
    (0 of 70). Preferred to answers of an installation with no lenses in 16 of 30 blind pairs against 9, with
    5 undecided, at the same length (ratio 0.98). After the body was revised for cold readers, opened in 8 of
    10 runs where it should have been. These installations sat inside the maintainer's own workspace, and each
    session read that workspace's instruction file too, so the figures are not of the kit alone.
  - Record: `decision:KIT-DR-063`
- **2026-11-21, codex-cli 0.169.1 and agy 1.5.13, the cheapest model each runtime offered**
  - What was measured: What each runtime sends to hooks, and where an injected block is cut
  - Result: A SessionStart block of 1,503 lines reached the model as its first and last 76 lines, about 10 KB;
    Antigravity sends no event for a compaction or a continued conversation, and its continuation flag is
    false at every Stop.
  - Record: `decision:KIT-DR-042`; the versions are in `system/dev/runtime-capture.md`
- **2026-11-20, Claude Code 2.1.292, model opus**
  - What was measured: The background work line: off, a line when it changed, a line at every prompt, 30
    headless runs
  - Result: Answers with no tool call: 0, 4 and 2 of 16; mean output tokens 402, 309 and 275.
  - Record: `decision:KIT-DR-045`

## 9. Words used on this page

- **Installation.** A folder where `setup.sh` has run.
- **State view.** The one page of current state that the session-start hook injects: `state/NOW.md` together
  with what is kept under `_private/`. It is made from the journal: the dated one-line records `now.py log` writes.
- **Compaction.** The runtime replacing earlier conversation with a summary when the context fills.
- **Thread and dossier.** A topic that runs for weeks, and its file of five fields (rule 4 of `AGENTS.md`).
- **Gate.** The turn-end check (`tools/gate.py`): links and state. A finding is one thing it found.
- **Worker and receipt.** A fresh model session given one bounded task (`tools/fresh_worker.py`), and the short
  report it hands back.
- **The loop.** The optional weekly cycle that gathers proposals to change the kit, builds them in a copy and
  ends at a patch (`system/loop/README.md`). A bundle is one proposed change with its files.
- **Thinking skills.** `lenses`, `deep-pass`, `plain-writing` and `large-jobs`.
- **The four critical kinds.** Something leaves the machine, data that cannot be rebuilt is deleted, an
  untouchable folder is touched, or money or a usage limit is spent (`system/rituals.md#memory`).
- **Headless.** Started by a command, with nobody at the keyboard.
