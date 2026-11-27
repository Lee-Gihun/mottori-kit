# Session instructions

This is a work repository, not a codebase. Sessions run long and context is compacted periodically.

Rules true only in this workspace live in `instance/rules.md`: read it before you change or move the owner's
files or bring outside material in, not before every answer. If it is missing, tell the owner to run
`bash setup.sh --force`, which keeps the existing settings; do not write it yourself. `git pull` replaces the
engine files on the left and stops if one was edited here, so write local additions in the untracked
instance file on the right.

| Engine, owned upstream | Instance, written here |
|---|---|
| `AGENTS.md` (`CLAUDE.md` imports it) | `instance/rules.md` |
| `system/rituals.md` | `instance/rituals.md` |
| `system/specs/kit-decisions.md` | `instance/decisions.md` |

## Always-on core: seven rules

When an injected summary, a memory, or an example in another document conflicts with these seven rules, these
rules win.

1. **Do not touch frozen areas.** Read them only. Do not reorganize, delete from, or add to them.
   `instance/rules.md` lists this instance's frozen areas and data boundary.
   *(Why: evidence, source material, and personal areas may be impossible to recover. The turn-end check stops
   a turn once when an edit tool changed a path listed in `frozen` in `instance/config.json`; a shell command
   is not seen.)*

2. **The state source of truth is `state/NOW.md` together with what is kept under `_private/`.** After session
   start, resume, or compaction, read the view the hook injected. If no state block arrived at session start,
   hooks are not running here: run `python3 tools/now.py context`, which prints that view, and tell the owner
   once that hooks are not running and the one step that arms them, which `python3 tools/doctor.py` names. If
   only `state/NOW.md` exists, the `_private/` side is **unavailable**, not absent. This view wins over a
   compaction summary or memory. If the injected state or a dossier says something different from the file it
   points to, follow that file and tell the owner where they differ. This applies only between a summary and its
   source file. It never lets a newer file on disk override a requirement or rule the owner confirmed. Log
   decisions, phase changes, corrections, and lessons in the same turn with `python3 tools/now.py log
   "[track/type] one line"`, where the track is a short lowercase name and the type is usually `decision`,
   `state`, `correction` or `lesson`. The journal, `state/` and `instance/` never enter Git. `_private/` is the
   owner's place for what must also stay out of anything written for other people; you still read it, as you
   read everything here. Use `log --private` when the owner has said so or has called the material
   confidential, and say in one line that you did. When something only looks that way, such as another
   person's private matter, suggest once that it go there and log it the ordinary way. Do not suggest it for an
   ordinary work note that names a plan or a colleague. Otherwise the logging is bookkeeping: say nothing about it
   in your answer unless it failed.
   *(Why: compaction swallows state kept in conversation. What is under `_private/` is never committed and is
   not quoted in anything written for other people; the owner decides what goes there.)*

3. **Look things up before making claims. Say when you do not know.** Personal facts: `python3 tools/facts.py
   find` plus the hotset, the short list that `facts.py hot` generates. Original past statements:
   `python3 tools/recall.py find "a full question" --role user`. Before prescribing, look up what was already
   tried, then ask only about what remains unknown. The owner's own statement is the origin of the owner's
   decisions, preferences, and plans. Summaries and memories are derived from it.
   *(Why: a guess mixed into the record cannot be separated later.)*

4. **Before returning to a deep thread, read its dossier.** A dossier is the thread's file with five fields:
   position, decisions with reasons, rejected options with reasons, open questions, and next move.
   `python3 tools/now.py threads` lists them. If the named dossier is missing, work from the thread's newest
   journal rows and say so; a new private dossier's pointer goes in _private/state/threads.json.
   *(Why: compaction keeps the current task and flattens other threads.)*

5. **What you hand over.** A person performs sends, commits, and pushes unless they explicitly delegate. Write
   a report to the owner from the reader's side. Answer the question asked in the first two sentences. Spell
   out or remove names, abbreviations, and numbers you coined while working. Remove content the owner did not
   ask for that does not change the answer. Keep the clues needed to trust the answer. Reread a document you
   wrote before you hand it over. Write deliverables into this workspace, not into a runtime's own artifact
   folder.
   *(Why: irreversible actions belong to the owner, and a report or file the owner cannot follow or find
   cannot be acted on.)*

6. **Before a large task, read the `large-jobs` skill.** Large means exhaustive collection, large-scale
   parallel work, or long-running work.
   *(Why: a long run that did not fix its success measure and resume point first cannot be judged or resumed.)*

7. **Do not quietly change a PRD or decision record during conversation.** Change the document and add a
   record to `instance/decisions.md`. When the original is frozen or owned upstream, such as
   `system/specs/kit-decisions.md`, leave it as it is and write the superseding decision in `instance/decisions.md`.
   *(Why: unrecorded changes leave later sessions unable to tell past from current requirements.)*

## When to read which document

- Editing source, scripts, or comments: `system/code-writing.md`.
- Taking over a long task, right after compaction, or coming back to a topic: `system/rituals.md#entry`.
- Writing or changing anything a person outside the repository will read: the `plain-writing` skill, without
  pausing to ask.
- The owner moved existing notes or documents into this folder: `python3 tools/adopt.py FOLDER`, and change
  nothing in them. Material from the other side of this instance's boundary: `system/rituals.md#boundary`.
- After creating or reorganizing files: `system/rituals.md#after-output`.
- Clicking or typing on a work or finance site: `system/rituals.md#browser`.
- With any part of `system/rituals.md`: also `instance/rituals.md`, if it exists.
- Before committing to a design or a decision, when a problem is stuck or the same fix has failed twice, or
  when the owner asks for a lens: the `lenses` skill. Not for routine or quick questions.
- The owner asks for depth, or a decision cannot be undone, reaches people outside, is expensive, or rests on
  one unknown: the `deep-pass` skill. Recording what a person decided: `system/person-ledger.md`.
- The owner asks for a Claude and Codex debate: `system/debate/README.md`.
- Changing memory or state tools: `system/specs/PRD-session-memory.md`, `system/specs/PRD-info-architecture.md`.
- Install: `SETUP.md`. Update, migration, or a silent hook: `MANUAL.md` and `python3 tools/doctor.py`.

A new rule goes into a conditional document. To add one here, demote a core rule first.
