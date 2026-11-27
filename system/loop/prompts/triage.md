Read `AGENTS.md`. You are the triage worker of the papers source of the improvement loop.

## What to read

Input: `{{DIR}}/candidates.tsv` (arXiv {{WINDOW}}; columns: arxiv_id, published, title, categories, queries,
abstract).

Context: the kit's philosophy and current decisions in {{ENGINE_DOCS}}, and the loop's rule for paper cycles:
at most two rollback bundles per cycle, no wholesale transplant.

## What to write

Write one file: `{{DIR}}/triage.tsv`.

Task: from the abstracts alone, score every candidate 0 to 3:

- 3 = it can ground a real decision of the kit: worker isolation, receipts, a separate verifier,
  context budget, hook or gate enforcement, install gate, documentary evidence, a calibrated classifier,
  proactive triggers;
- 2 = related but indirect;
- 1 = distantly related;
- 0 = unrelated.

One row per candidate:
`arxiv_id\tscore\ttag(receipt|isolation|verify|context|enforce|install|skill|memory|calibrate|proactive|other)\tone-line reason`,
in English.

Last line: `#summary\ttotal <n>\tscore3 <n>\tscore2 <n>`.

## Rules

- Be strict: at most 15 papers score 3.
- Do not guess beyond the abstracts.
