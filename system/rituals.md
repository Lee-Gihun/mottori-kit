Korean: `ko/system/rituals.md`

# Session rituals and conventions (conditionally loaded)

The seven always-on rules are in `AGENTS.md`. Claude reads the same file through the `@AGENTS.md` line in
`CLAUDE.md`. This document holds detailed conventions. Read only the section for the situation at hand.
Conditional loading follows the [memory selection contract](PRD-session-memory.md#retrieval). The kit wrote this
document itself, and the data boundary section depends on each instance's direction.

**Which section to read in which situation**

- Session start, resume, or right after compaction: [Session entry and recovery](#entry). Recording a decision or phase change: [Recording decisions and events](#events).
- The work will continue in another session or the other runtime: [Handing work over](#handoff).
- Claiming or correcting a fact about the owner: [Personal facts](#facts).
- After creating or reorganizing files: [Checks after output](#after-output) and [File conventions](#files).
- Writing for a person outside the repository: [Outbound material](#outbound). Bringing material in from outside: [Data boundary](#boundary).
- Using a lens: [Thinking lenses](#lenses). Using a browser on a work or finance site: [Browser](#browser). Recall and `/garden`: [Memory system](#memory).

<a id="entry"></a>
## Session entry and recovery

- The SessionStart hook injects state (`AGENTS.md` rule 2). If nothing was injected, the hook failed. Diagnose
  with `python3 tools/doctor.py` and read both NOW files directly.
  *(Why: the hook is built not to block the session when it fails, so it fails silently. Do not read a missing
  injection as "no news".)*
- **When taking over a long-running task, read that task's `HANDOFF.md` first.** Take progress numbers from that
  task's status tool, not from the conversation. *(Why: numbers in the conversation disappear or go stale
  after compaction. A tool on disk recounts the current value.)*
- Right after compaction, treat the summary's claims about state and depth as provisional until you check them
  against NOW, the journal, and the dossiers.
- After the first file read following compaction, write one line saying which procedure and which step you are
  in and which step is allowed next. If you cannot tell, write `unmeasured`. This rule is on trial.
  *(Why: agents are reported to lose their place in a procedure after compaction. Paper 2609.09153 §3.2.)*

<a id="handoff"></a>
## Handing work to another session or runtime

Use this when the work will continue somewhere else: a new session, the other runtime, or a session that
already runs beside this one.

- Before you stop, write a handoff note: `_private/state/handoff/<YYYY-MM-DD-HHMM>-<topic>.md`. It has five parts.
  1. What the owner asked for, in the owner's words.
  2. Where the work stands: done, not done, not verified.
  3. Decisions made in this session, with their reasons.
  4. Anything that exists only in this conversation and has to travel: the answer, the draft, the list. Put the
     text itself in the note, not a description of it.
  5. The next step for whoever continues, and the files to open first.
- Log one line so the next session finds the note:
  `python3 tools/now.py log --private "[<track>/state] handoff: <path of the note>"`. The line shows up among the
  recent decisions in the state the next session is given.
- If the thread has a dossier, also append the five-line delta there (`AGENTS.md` rule 4). The note carries this
  one transfer. The dossier carries the thread.
- The session that continues reads the note first, then the dossier.

*(Why: what lives only in a conversation has no other way to reach the next session. Without a note, the owner
ends up pasting the previous answer by hand. `decision:KIT-DR-027`.)*

<a id="events"></a>
## Recording decisions and events (decisions, phase changes, sending, submitting, or publishing)

- The logging command and the `--private` criterion are in `AGENTS.md` rule 2. Logging regenerates NOW
  automatically.
- Also update the date in the header of the track's source-of-truth file. Otherwise `python3 tools/now.py check`
  reports it as a stale source of truth. *(Why: keeping state and its update time together makes a stale
  source of truth recognizable.)*

<a id="facts"></a>
## Personal facts (the rec.py ledger)

- Lookup commands: `python3 tools/rec.py find <words>`, details `show <id>`, change history `audit <id>`,
  consistency check `check`.
- After changing or adding a record, regenerate the hotset with `python3 tools/rec.py hot`. The hotset is
  generated, so do not edit it by hand. *(Why: a hand edit is overwritten at the next generation and disagrees
  with the ledger until then.)*
- **When a source such as a recording transcript conflicts with a person's memory, do not quietly follow
  either.** Show the conflict with its source and let the person decide. Mark long quotations and the
  direction of a relationship as [uncertain] until confirmed.
  *(Why: this prevents fixing an attribution that differs from the original.)*

<a id="after-output"></a>
## Checks after output (after reorganizing or creating)

- Confirm zero broken references with `python3 tools/linkcheck.py` and zero drift with `python3 tools/now.py check`.
- When you update a state document, put the update date in its header and check that other documents holding
  the same fact agree. *(Why: copies of one fact must not remain in different states.)*
- **Run the existing checkers on new things too.** When you create a repository, a set of documents, or a
  dossier, run `linkcheck`, `now.py check`, and `coherence`, in that order, inside that output. Use the existing
  checkers before building a new one.
  *(Why: a new checker does not inherit the coverage of existing checks.)*
- **Running a tool and reading what it said are different acts.** Do not move on after seeing only the exit
  code. *(Why: a tool finishing successfully and its target being correct are separate facts.)*

<a id="files"></a>
## File conventions

- Name new work outputs in kebab-case with `YYYY-MM-DD`. Code and tool modules follow the conventions of their
  language. Original files received from outside keep their original names. *(Why: names with dates are easy
  to find and sort.)*
- Keep a message body meant for copy and paste in a separate `*-body.txt` file. After sending it, write
  `[sent on DATE]` at the top. *(Why: this keeps the sent version and drafts from being confused.)*
- Imports such as personal conversation exports go in the single landing point described under
  [Data boundary](#boundary).

<a id="outbound"></a>
## Writing outbound material (10-case pilot)

Before writing or changing the meaning of the body of something a person outside the repository will read or
receive, fill in the two lines below with real values and put them first in your working message to the owner.
Continue without asking for approval. Do not put the two lines in the body you will send (KIT-DR-008).

```text
Document role: reader / approver / goal (the one result that would count as success for this text)
Consistency anchors: track source of truth + actual paths checked on the filesystem now + paths of submitted or confirmed originals
```

"Actual paths checked on the filesystem now" means paths you just saw with `ls` or `find`, not a hand-maintained
index. Within one task, do not repeat the two lines while all three roles stay the same. Output them again when
any one changes. Internal reading, NOW, dossiers, analysis notes, and formatting changes that do not change
meaning are outside this section. Then write in this order (KIT-DR-009).

1. **Evidence and task.** Confirm facts in the actual originals. Settle on the narrowest single result the
   recipient must newly know or do.
2. **Close.** Do not turn an expected reaction from the recipient into a new goal or question.
3. **Skeleton.** For a short text, fix only what it asks or tells. For a long document, fix only the order of
   claims and evidence. Then freeze it.
4. **Stop.** Expand each skeleton item once. Do not add new goals, questions, or self-assessment that occur to
   you while writing. End at the last item.
5. **Stance and economy.** Keep the needed facts and the warmth of the relationship. Delete self-commentary that
   does no work, preemptive excuses, and repetition. Let facts stand in place of judgments about the writer.
6. **Reread as the recipient.** At the end, check whether the recipient can recover what each reference points
   to, the order of events, cause and effect, and the next action. If deletion cut a needed connection, restore it.

Plain writing is not short writing. It keeps the needed logic and warmth and carries no second task and no
self-assessment. There is no banned-word list and no length limit. The one exception is the em-dash ban in
`AGENTS.md` rule 5. It stands apart because an em dash is a punctuation mark that makes text read as AI-written,
not a word. If a source was misread, fix the fact first instead of covering it with style.

<a id="boundary"></a>
## Data boundary (the direction differs by instance)

Do not copy this section unchanged into another instance. Which side is inside and which is outside depends on
the instance's identity (`instance.context` in `system/memory-config.json`). Copying the conventions of a
personal workspace into a company workspace reverses the direction. It then blocks exports where it should
block imports.

**Three principles true in either direction.**

1. **A person does the importing.** An agent does not bring material across the boundary.
   *(Why: a person decides whether to import. The agent keeps it isolated. Reversing that order removes the
   decision.)*
2. **Imported material lands in one place.** It is one untracked folder under `_private/`, named in
   `system/instance-rules.md`. Reading and recall within a session are allowed. Commits, quotations, and
   external sends are not. Worker run records (`_private/work/runs/`) are generated output, not imports, so this
   rule does not cover them.
   *(Why: once material scatters, nobody knows which file has which sensitivity.)*
3. **Committed documents contain only abstract content.** Do not put measured numbers, internal code names,
   quotations from originals, or screenshots in the journal, NOW, dossiers, or artifacts.
   *(Why: what is committed goes to remotes, and what has left remains even after deletion.)*

**Write this instance's inside and outside in `system/instance-rules.md`.** Write at least three things: what
counts as imported material, where it lands, and what must never leave to any remote. The boundary check in
`tools/doctor.py` enforces that declaration mechanically.

<a id="lenses"></a>
## Thinking lenses

- Pick a viewpoint from the [lens list](lenses/README.md) and read the definition in that lens file. The listed
  lenses are a starting set. Choose a viewpoint made up on the spot by the same standard.
- When the owner makes a claim about themselves, check the existing evidence before settling on an
  interpretation. This check does not permit ignoring experience the owner reported or deciding preferences on
  the owner's behalf.
- Under the [deep-pass recording contract](deep-pass.md#recording), record the verdict, the viewpoints used,
  the source of corrections, and later observations in the instance's `_private/deep-pass/ledger.md`. To use
  another protected location, set it in the instance rules. If the ledger does not exist, copy the
  [blank template](../templates/deep-pass-ledger.md). If it exists, append to it.
- Do not write real cases into tracked lens files, deep-pass documents, or templates. Usage counts are
  observations, not evidence of effect or grounds for retirement. Back up local records separately from upstream
  engine updates.

<a id="browser"></a>
## Operating external systems through a browser

- **A person presses irreversible buttons:** submit, send, pay, sign. The agent fills in and prepares.
  *(Why: irreversible actions belong to the owner, the same reason as `AGENTS.md` rule 5.)*
- **Assume work and finance portals save automatically.** A click made only to look around can save data.
  **Reading is the default. Click and type only when instructed.** *(Why: the screen does not distinguish
  browsing from saving.)*
- A blank or filled field on a form may be **an earlier decision**, not an omission. Before filling it, look for
  the reason for that decision in the relevant source of truth (`AGENTS.md` rule 3). *(Why: filling a blank can
  silently reverse a past decision.)*
- A person handles logins and passwords. The agent does not enter credentials.
  *(Why: credentials must not remain in conversation records or logs.)*

<a id="memory"></a>
## Operating the memory system (details: `system/PRD-session-memory.md`)

- Recall: `python3 tools/recall.py find "query"`. Do not paste the results whole. Tie them to the current
  question in a few lines. When recall fails to find an original you know exists, log it with
  `python3 tools/now.py log "[system/lesson] recall miss: <query>"`. When three such entries accumulate, the
  session that logs the third tells the owner and proposes reconsidering meaning-based (embedding) search.
- Cleanup: `/garden` is a [manual, report-only audit](design-memory-runtime.md#manual-garden). The session
  carries out the follow-up fixes, within the scope the instance explicitly delegated. **Ask the owner for a
  decision only on structure, policy, personal facts, and frozen areas.** The agent performs mechanical,
  low-risk cleanup (number corrections, update dates, replacing a body with a path, tool bugs) and reports
  afterward. *(Why: escalating small decisions wastes the owner's attention.)*
- Do not act on side ideas. Log them in the journal as `idea` and handle them together at the periodic review.
  *(Why: acting on each idea as it comes expands the scope of the work.)*

<a id="local"></a>
## Rituals specific to this instance

This file is owned upstream. `git pull` overwrites it, so workspace-specific conventions written here disappear
or conflict at the next update. Write instance-specific rituals in `system/rituals.local.md`. It is outside Git
and safe. If it does not exist, none have been written yet. When you read this document, also read that file
if it exists. `system/instance-rules.md` owns the data boundary declaration.
