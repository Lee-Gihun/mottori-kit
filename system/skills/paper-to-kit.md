# paper-to-kit workflow

---
workflow: paper-to-kit
version: 1
side_effects: proposals-only
kit_writes: 0
human_gate: required
---

Create proposals for this kit from a set of papers. The workflow ends by waiting for human judgment. It does
not include accepting a proposal or implementing it in the kit.

## Inputs

Accept the following values.

- `papers`: an explicit list containing a DOI, arXiv ID, or title and original location for each paper; or
  `source_url`: a read-only URL that provides a paper list. Exactly one of these must be present.
- `period`: inclusive start and end dates in `YYYY-MM-DD..YYYY-MM-DD` format.
- `run_dir`: the working directory for cards and proposals. Confine every write to this directory.
- Optional `input_revision`: a new revision string supplied by the caller when the same URL must be collected
  again.

Choose paper identifiers in this order: DOI, arXiv ID, another stable ID, then a normalized source URL as a
last resort. A `paper:` evidence marker accepts only an arXiv ID or DOI under the canonical syntax in
`system/evidence-schema.md`. If neither can be verified, grade the card `X` and do not use it as proposal
evidence. Build a card filename `card_key` by replacing every character outside alphanumerics, `.`, `_`, and
`-` with `_`, then append the first eight characters of the identifier's SHA-256. This prevents collisions and
path traversal. Deduplicate and sort the input list by identifier. Serialize the sorted identifiers, normalized
URLs, `period`, and `input_revision` as key-sorted JSON and use its SHA-256 as `input_fingerprint`. Do not discard
out-of-period items. Keep each as an `X` card so the exclusion reason survives.

## Stages

### 1. Collect

Attach a stable identifier, title, publication date, authors, and source location to every paper. For URL input,
first freeze the list for the requested period in `MANIFEST.md`. Use only permitted read-only retrieval. Do not
log in, pay, submit, or send messages. If the full text cannot be read, do not infer its contents; grade the card
`X`.

Record the workflow version, original input, period, `input_revision`, `input_fingerprint`, sorted paper
identifiers and `card_key` values, and card status in `MANIFEST.md`.

### 2. Cards

Assign one independent bounded worker to each paper. Its read scope is that paper and this workflow. Its write
scope is one assigned card. `cards/<card-key>.md` has these fields:

```markdown
# <title>
paper:<arXiv id or DOI>
source: <original-location>
published: <YYYY-MM-DD or unknown>
grade: <A|B|C|X>
grade_reason: <one sentence>

## Question
## Method
## Findings
## Limits
## Kit relevance
## Traceable claims
- <claim> | evidence: <verifiable section, figure, table, or page>
```

Grade both evidence traceability and transfer distance to the kit, then use the lower grade.

- `A`: methods and results are traceable in the original, and an agent or workflow mechanism is tested directly,
  so the implication for the kit is direct.
- `B`: evidence is traceable, but transfer to the kit requires at least one explicit assumption.
- `C`: the implication is useful, but evidence is indirect or one of method, result, or application conditions is
  insufficient. Permit only an exploratory experiment, not an implementation proposal.
- `X`: full text is unavailable, the paper is outside the period, duplicated, off-topic, or cannot be judged.
  Do not use it as proposal evidence.

Do not confuse summary confidence with the grade. State the weakest grading dimension in `grade_reason`.

### 3. Cross-check

A reviewer who wrote none of the cards compares all cards together and creates `CROSSCHECK.md`.

- Merge duplicates from the same study or data and choose a representative identifier.
- Tabulate cards with conflicting conclusions, different application conditions, and shared limitations.
- Check every card, not a sample, to confirm that its grade and central claims return to evidence locations in
  the original. If they do not, lower the grade or change it to `X` and preserve the reason.
- Distinguish claims supported by one paper from claims supported independently by several papers.
- Put unresolved conflicts and missing originals under `Unknowns`.

### 4. Proposals

Use only `A` and `B` cards, plus `C` cards explicitly limited to exploratory experiments, as proposal candidates.
Every proposal has at least one `paper:` row for each supporting paper. Use exactly the syntax
`paper:<arXiv id or DOI>` from `system/evidence-schema.md`. Spaces, generic stable IDs, and URLs are not valid
`paper:` payloads; put the source location in `source:`.

Design a falsifiable experiment for each proposal and reserve one `experiment:` ID. The ID is
`PTK-<first 8 uppercase characters of input_fingerprint>-E<two-digit sequence>`. Sort proposals by expected
utility, reversibility, and evidence grade. Break ties by title and evidence identifier, then assign sequence
numbers so identical input keeps identical IDs. The reservation applies only inside that `PROPOSALS.md`; it does
not change an external ledger or kit state.

### 5. Wait for human judgment

Set every proposal's `decision` to `pending` and finish with `status: awaiting-human-judgment`. Do not run an
experiment or change a kit file before a person decides to accept, reject, or defer the proposal.

## `PROPOSALS.md` output schema

Use the following fields and order. Create the file even when there is no proposal, with `proposal_count: 0` and
the reason under `## No proposal`.

```markdown
# Paper to Kit Proposals
workflow_version: 1
input_fingerprint: <sha256>
period: <YYYY-MM-DD..YYYY-MM-DD>
status: awaiting-human-judgment
proposal_count: <N>

## P-01 <proposal title>
decision: pending
paper:<arXiv id or DOI>
paper:<arXiv id or DOI for additional evidence>
experiment:PTK-<8HEX>-E01
evidence_grade: <A|B|C>

### Proposed kit change
target: <kit file or rule to review if a person accepts>
change: <proposed change>
rationale: <reason tied to the cross-check>

### Experiment design
hypothesis: <falsifiable hypothesis>
baseline: <current behavior and measurement>
intervention: <one variable to change>
metric: <measurement that separates success from failure>
sample: <targets and repetition count>
stop_rule: <stopping condition>
rollback: <restoration method>

### Risks and unknowns
- <risk or unknown>
```

`paper:` is a paper-evidence marker containing an arXiv ID or DOI. `experiment:` reserves an experiment ID. An
item missing either marker is not a proposal and must not enter `PROPOSALS.md`.

## Side-effect boundary

The only permitted writes are `MANIFEST.md`, `cards/*.md`, `CROSSCHECK.md`, and `PROPOSALS.md` below `run_dir`.
All are analysis or proposal artifacts. There must be zero changes to kit or instance files, including
`system/`, `tools/`, `.claude/`, `.codex/`, `.agents/`, `templates/`, `state/`, and `_private/`. Do not send
externally, commit, push, submit, pay, or run experiments. If an out-of-scope change is found, stop and report its
path instead of reporting success.

## Reruns

When `input_fingerprint` matches the existing `MANIFEST.md` and cards satisfy the schema, reuse the cards without
repeating collection or card workers. Recreate only missing or damaged cards. Rerun cross-checking and proposal
assembly over reused cards to confirm deterministic IDs and current validation results.

To force a fresh read of the same URL, use a new `input_revision` and a new `run_dir`; do not overwrite existing
outputs. When the input differs, do not silently reuse old card contents.

## Completion conditions

Complete only when all conditions hold.

1. `MANIFEST.md` fixes the input and period, and the fingerprint can be recomputed.
2. Every paper has a schema-valid card or an explicit `X` card.
3. Independent cross-checking is complete, with conflicts and unknowns preserved.
4. Every proposal has `paper:` and `experiment:` markers and a complete experiment design.
5. `PROPOSALS.md` has `status: awaiting-human-judgment`, and every decision is `pending`.
6. There are zero changes outside `run_dir`, especially zero kit-file changes.
