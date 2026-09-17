Korean: `AGENTS.ko.md`

# Session instructions

This workspace is not a codebase. It is a **work repository**. It runs multiple tracks in one place. Sessions
continue indefinitely, and context is compacted periodically. The seven rules below have proved their value by
measurement under those conditions.

Instance-specific rules, which are true only in this workspace, live in `system/instance-rules.md`. If that file
does not exist, the rules have not been written yet. Copy `templates/instance-rules.md` and complete it.

**Engine files and instance files come in pairs.** `git pull` can overwrite the engine file on the left, so do not
edit it. The instance file on the right is outside Git and safe to edit. If you want to add something to the left,
put it on the right instead.

| Engine, owned upstream | Instance, written here |
|---|---|
| `AGENTS.md`, the seven always-on core rules imported by `CLAUDE.md` | `system/instance-rules.md` |
| `system/rituals.md` | `system/rituals.local.md` |
| `system/kit-decisions.md` | `system/decisions.md` |

## Always-on core: Only these seven rules are always active

Do not keep rules without evidence.

1. **Do not touch frozen areas.** Do not reorganize, delete from, or add to them. Read only. A person must perform
   every external send. The frozen-area list and data boundaries for this instance are in
   `system/instance-rules.md`.
   *(Why: evidence, source material, and personal areas may be impossible to recover. One mistake can be
   catastrophic. Boundaries are enforced by structure, not discipline. The valve checks in `.gitignore` and
   `tools/doctor.py` provide that enforcement.)*

2. **The state source of truth is public NOW plus the local overlay.** After session start, resume, or compaction,
   inspect the view merged by the hook. Without the hook, read `state/NOW.md` together with
   `_private/state/NOW.md` when the latter exists. If only the public file is present, local state is
   **unavailable**, not absent. This view wins over a conflicting compaction summary or memory. Log decisions,
   phase changes, corrections, and lessons in the same turn with `python3 tools/now.py log "[track/type] one
   line"`. Use `log --private` for events derived from personal or company material, or when their status is
   uncertain.
   *(Why: compaction swallows state kept in conversation. Mixing a local event into public NOW bypasses the Git
   boundary.)*

3. **Look things up before making claims. Say when you do not know.** For personal facts, use
   `python3 tools/rec.py find` plus the hotset. For original past statements, use
   `python3 tools/recall.py find`. Before prescribing an action, ask what has already been tried. The owner's own
   statement is the origin for the owner's decisions, preferences, and plans. Summaries and memories are
   derivative.
   *(Why: attribution bias was measured four times. Guessing contaminates the source of truth.)*

4. **Before returning to a deep thread, read its dossier.** List registered threads with
   `python3 tools/now.py threads`. Before leaving a deep session, append a five-line delta.
   *(Why: compaction preserves the current task but flattens depth in other threads. This directly prevents a
   shallow return.)*

5. **Outbound restrictions.** Do not use em dashes in outbound email, messages, or documents. A person performs
   sends, commits, and pushes unless they explicitly delegate the action.
   *(Why: avoid the appearance of AI-written text, and let the owner execute irreversible actions.)*
   When writing outbound material or changing its meaning, continue without pausing and follow the "Writing
   outbound material" section of `system/rituals.md` (KIT-DR-008).

6. **Before a large task, read `system/WORKING-WITH-AI.md`.** Large tasks include exhaustive collection,
   large-scale parallel work, and long-running work.
   *(Why: it is an instrument, not a summary. The framework was verified in a run of 660 items.)*

7. **Do not quietly change a PRD or decision record during conversation.** Change policy in the document and add
   a decision record to `system/decisions.md`.
   *(Why: unrecorded decisions cause drift and repeated discussion. This rule came from that measured failure.)*

## Conditional loading

Read these only when the stated situation applies.

- Session rituals, outbound material, and detailed document conventions: `system/rituals.md`
- Thinking lenses: `system/lenses/README.md`, only for a blocked problem, design, decision, or explicit request
- Full deep pass: `system/deep-pass.md`, when depth is explicitly requested
- Cross-runtime debate: `system/debate/README.md`, the asynchronous board for Claude and Codex
- Memory system specification: `system/PRD-session-memory.md`; information architecture:
  `system/PRD-info-architecture.md`
- Installation and migration: `SETUP.md`; verification: `python3 tools/doctor.py`

## Why there are seven always-on rules

The number of instructions followed at once reaches a limit around k=5 to 6 (`2608.12426`). Adding more makes
each rule less reliable. The default destination for a new rule is therefore a conditionally loaded document. To
promote a rule into the always-on core, demote an existing one.
