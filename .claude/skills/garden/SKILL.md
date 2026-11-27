---
name: garden
description: "Use only when the owner asks: a report-only gardener pass that checks state, journals, dossiers and memory against the record and proposes fixes, each with its evidence."
---

# Garden

Run the gardener pass on this repository yourself, in this session, report-only: you propose, you edit nothing
while you audit, and every proposal carries its evidence and what breaks if it is wrong. The contract is
`system/specs/design-memory-runtime.md#manual-garden`. Take the root from `git rev-parse --show-toplevel`.

1. Run `python3 tools/now.py check`. Judge each warning: real rot, a false positive, or already known. Do not
   repeat the raw output.
2. Run `python3 tools/now.py context` for the merged state view, and read the current journals in both `state/`
   and `_private/state/` without editing them. If `_private/state/` is absent, report the private half as
   unavailable, not as empty. Look for state in NOW that no journal event supports, journal events whose track
   file was never updated, and decision or switch lines that point to a record that does not exist
   (`python3 tools/lib/paths.py decisions` prints the decision file).
3. Check the dossiers against the record. Get the registry with `python3 tools/now.py threads`; if
   it is empty, skip this step and say so. In each registered dossier pick the three claims the most rests on
   (dates, numbers, who said what) and look each one up with
   `python3 tools/recall.py find "<the claim as a question>" --role user --max 2 --around 1` or in the file it
   names. Verdict: confirmed, contradicted or unfindable. For a contradiction cite where the transcript says
   otherwise (file and line, or the recall hit); do not quote it.
4. Memory hygiene: list the files in the `memory` folder inside the folder that
   `python3 -c "import sys; sys.path.insert(0, 'tools/lib'); import paths; print(paths.transcripts())"` prints.
   Flag project memories that read like state snapshots (they should be pointers), index lines in MEMORY.md that
   state facts which go stale, and memories that repeat what a file in this repository already owns. Propose
   moves; do not make them.
5. Write the report to `_private/state/gardener-<today>.md` (today from `date +%F`; create the folder if it is
   missing; never overwrite a report of an earlier day). It cites private state and transcripts, so it never
   goes under `state/`. Write it in the owner's language, under 120 lines, plain prose without em-dashes, with
   these sections: `## Verdict summary` (three lines), `## Findings` (by kind: evidence, proposal, risk),
   `## Dossier check` (a table), `## Questions for the owner` (only the kinds `system/rituals.md#memory` names),
   `## Recommended automatic actions` (the other items, within the bounds that section sets).

Then summarize the report for me. What follows the report goes by `system/rituals.md#memory`: ask me about the
kinds that section names. Carry out and report the corrections the report found in numbers, dates, pointers
and tool bugs, each in a form that can be undone, and propose the rest. This pass does not inherit the
authority of the optional improvement loop (`system/loop/README.md`).
