Korean: `ko/AGENTS.md`

# Session instructions

This is a work repository, not a codebase. Sessions run long and context is compacted periodically.

Rules true only in this workspace live in `system/instance-rules.md`. If it is missing, copy
`templates/instance-rules.md` and fill it in. `git pull` overwrites the engine files on the left, so write local
additions in the untracked instance file on the right.

| Engine, owned upstream | Instance, written here |
|---|---|
| `AGENTS.md` (`CLAUDE.md` imports it) | `system/instance-rules.md` |
| `system/rituals.md` | `system/rituals.local.md` |
| `system/kit-decisions.md` | `system/decisions.md` |

## Always-on core: seven rules

When an injected summary, a memory, or an example in another document conflicts with these seven rules, these
rules win.

1. **Do not touch frozen areas.** Read them only. Do not reorganize, delete from, or add to them.
   `system/instance-rules.md` lists this instance's frozen areas and data boundary.
   *(Why: evidence, source material, and personal areas may be impossible to recover. `.gitignore` and the
   boundary checks in `tools/doctor.py` enforce this.)*

2. **The state source of truth is public NOW plus the local overlay.** After session start, resume, or
   compaction, read the view the hook injected. Without the hook, read `state/NOW.md` and, when it exists,
   `_private/state/NOW.md`. If only the public file exists, local state is **unavailable**, not absent. This view
   wins over a compaction summary or memory. If the injected state or a dossier says something different from
   the file it points to, follow that file and tell the owner where they differ. This applies only between a
   summary and its source file. It never lets a newer file on disk override a requirement or rule the owner
   confirmed. Log decisions, phase changes, corrections, and lessons in the same turn with
   `python3 tools/now.py log "[track/type] one line"`. Use `log --private` for events from personal or company
   material, or when unsure.
   *(Why: compaction swallows state kept in conversation. A local event in public NOW leaves through Git.)*

3. **Look things up before making claims. Say when you do not know.** Personal facts: `python3 tools/rec.py
   find` plus the hotset, the short list that `rec.py hot` generates. Original past statements:
   `python3 tools/recall.py find`. Before prescribing, look up what was already tried, then ask only about what
   remains unknown. The owner's own statement is the origin of the owner's decisions, preferences, and plans.
   Summaries and memories are derived from it.
   *(Why: a guess mixed into the record cannot be separated later.)*

4. **Before returning to a deep thread, read its dossier.** A dossier is the thread's file with five fields:
   position, decisions with reasons, rejected options with reasons, open questions, and next move.
   `python3 tools/now.py threads` lists them. Before leaving a deep session, append five lines on what changed. When another
   session or runtime will continue the work, write a handoff note first (`system/rituals.md#handoff`).
   *(Why: compaction keeps the current task and flattens other threads.)*

5. **What you hand over.** Outbound material (email, messages, documents for readers outside the repository)
   contains no em dashes. A person performs sends, commits, and pushes unless they explicitly delegate. Before
   writing or changing outbound material, follow `system/rituals.md#outbound` without pausing (KIT-DR-008).
   Write a report to the owner from the reader's side. Answer the question asked in the first two sentences.
   Spell out or remove names, abbreviations, and numbers you coined while working. Remove content the owner did
   not ask for that does not change the answer. Keep the clues needed to trust the answer. Reread a document
   you wrote before you hand it over; `tools/deliver.py` records at turn end when that was skipped.
   *(Why: an em dash marks text as AI-written. Irreversible actions belong to the owner. Hard-to-follow
   reports were the largest group of owner corrections. In a small test, this rule next to the task cut
   unasked content from 19 of 72 answers to 0.)*

6. **Before a large task, read `system/WORKING-WITH-AI.md`.** Large means exhaustive collection, large-scale
   parallel work, or long-running work.
   *(Why: a long run that did not fix its success measure and resume point first cannot be judged or resumed.)*

7. **Do not quietly change a PRD or decision record during conversation.** Change the document and add a
   record to `system/decisions.md`.
   *(Why: unrecorded changes leave later sessions unable to tell past from current requirements.)*

## When to read which document

- Editing source, scripts, or comments: `system/code-writing.md`.
- Session start, resume, or right after compaction: `system/rituals.md#entry`.
- Handing work to another session or runtime: `system/rituals.md#handoff`.
- Writing anything a person outside the repository will read: `system/rituals.md#outbound`.
- Bringing material in from outside: `system/rituals.md#boundary`.
- After creating or reorganizing files: `system/rituals.md#after-output`.
- Clicking or typing on a work or finance site: `system/rituals.md#browser`.
- With any part of `system/rituals.md`: also `system/rituals.local.md`, if it exists.
- A problem still stuck after two attempts, or the owner asks for a lens: `system/lenses/README.md`.
- The owner asks for depth: `system/deep-pass.md`. Recording what a person decided: `system/person-ledger.md`.
- Writing an evidence marker such as `decision:` or `paper:`: `system/evidence-schema.md`.
- The owner asks for a Claude and Codex debate: `system/debate/README.md`.
- Changing memory or state tools: `system/PRD-session-memory.md`, `system/PRD-info-architecture.md`.
- Install, migration, or a silent hook: `SETUP.md` and `python3 tools/doctor.py`.
- A report, promise, or choice of work inside an organization: `system/work-craft.md` (draft).

A new rule goes into a conditional document. To add one here, demote a core rule first.
