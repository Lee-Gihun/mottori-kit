Read `AGENTS.md`. You are card worker {{GROUP}} of the papers source of the improvement loop.

## What to read

The kit's philosophy and decisions: {{ENGINE_DOCS}}.

Papers to read (full text):
{{FILES}}

## What to write

Write one file: `{{DIR}}/cards/group-{{GROUP}}.md`, in English.

One card per paper you read in full. A paper you did not read gets no card:
only a paper whose arXiv id a card names counts as read, and a later cycle may offer it again.

Each card starts with the paper's title and arXiv id, then has these sections, in this order:

1. How it actually works: the mechanism, from the paper, and from its code when the code is public.
2. The numbers that carry the claim, and their setup (subjects, scale, duration, metrics, baselines).
3. What the paper does not show.
4. Which file of this kit it speaks to (path, and line where it helps), and whether it grounds or refutes what
   that file does.
5. The smallest change to that file, under the rule of no wholesale transplant; or "none" with the reason.
6. The cheapest check that could show the change does not help: a test that fails on the unchanged code and
   passes after the change (name the file and what it asserts), or the size of the always-loaded context
   (`python3 tools/context_budget.py --json`) measured before and after, or "unknown" when no such check
   exists.
7. What goes wrong if the method is copied whole.

Quote one or two sentences of the paper with line numbers where a section rests on them.

## Lenses

Write the cards your own way first. Then pick from {{LENS_SKILL}} the one or two lenses that could change a
card's point of contact or its change, and use them.

When a lens changed a card, open the card file with a `{{LENS_HEADING}}` section, a line for each lens that
changed something: what it changed. Leave the section out when no lens changed anything.

## Rules

Plain style, no em-dash, at most 25 lines per paper.

## Your final answer

End your final answer with this fenced JSON block, with the number of cards you wrote in place of 3:
{{CARDS_BLOCK}}
