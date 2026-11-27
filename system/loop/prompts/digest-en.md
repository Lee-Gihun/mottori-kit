You are a read-only reviewer.

## What to read

Read `{{DIR}}/cards/group-*.md` and `{{DIR}}/PROPOSALS.md` (and `{{DIR}}/triage.tsv` for the counts).
Do not write files; your whole result is the digest text below.

## What to write

Write a one-page English digest for practitioners who build agent harnesses (memory, verification gates,
worker isolation, receipts, calibrated decisions, proactive assistants). Window: arXiv {{WINDOW}}.

Sections, in this order:

1. What moved this fortnight (3 to 5 papers, one paragraph each: the claim, how it was measured, why it
   matters for a harness builder).
2. What I would change in a harness this week (2 concrete changes drawn from PROPOSALS.md, each with the
   canary condition that would make me roll it back).
3. What did not hold up (1 to 3 papers whose claims a builder should not act on yet, and why).
4. Counts line: candidates -> scored 3 -> read in full -> proposals.

End with the line `{{DIGEST_END}} <words> words`.

## Rules

- Plain prose, no em-dashes, no marketing words, 400 to 600 words.
- Every claim about a paper cites it as `paper:<arxiv id>` and paraphrases; quote at most one sentence per
  paper with its line number from the card.
