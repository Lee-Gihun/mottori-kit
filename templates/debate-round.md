Korean: `debate-round.ko.md`

# Debate round template

This tracked file is a blank copy source, not an instance discussion log.
Copy it to an ignored instance prompt such as `system/debate/_p_review.md`, then replace the placeholders.
Store responses in the instance's private discussion record. Do not put actual cases in this template.
Follow the debate contract in `system/debate/README.md` and the instance's data boundary.

## Dispatch prompt

You are reviewing a proposed decision. Do not edit code, configuration, policy, or source records.
The caller owns the discussion log and will preserve your response.

- **Question and intended reader:** TO-FILL.
- **Current proposal and strongest alternative:** TO-FILL.
- **Sources allowed for this review:** list exact existing paths and the relevant scope within each. Include `AGENTS.md` and only the current contracts needed for the question.
- **Material excluded from this review:** TO-FILL. Do not inspect unrelated instance files, private records, connectors, or external sites.
- **What was observed, and what is only proposed:** TO-FILL, with evidence paths or reproducible checks.
- **Previous round and changed proposal:** TO-FILL, or say this is the first round.

Perform these checks:

1. State what you actually read and what remained unread. Unread is not absent.
2. Select a strategic assumption that could be false. Attack it, or state the evidence and limits supporting it.
3. Work through the omitted perspective most likely to change this decision. Do not merely name a lens.
4. For each material finding, identify the claim, consequence, evidence, and smallest correction.
5. Give one checkable evidence anchor for an execution or state claim. Read the relevant artifact or run a permitted check only if your runtime supports it. If you cannot perform the check, mark it not run and identify what the caller must verify. Never invent command output or a hash.
6. Address the previous response directly. Quote the relevant permitted statement before disputing it.

"No material change" is a valid result. Do not manufacture defects to meet a quota, weaken an acceptance
condition to obtain agreement, or treat another model's confidence as independent evidence.

## Response contract

Return a concise review containing:

- Actual runtime and model, with unavailable identity marked unknown.
- Sources read and material not read.
- What changed in your judgment and why.
- Strongest remaining objection, including the strategic assumption examined.
- Evidence anchors and checks not performed.
- Decision for each proposal: accept, revise with a concrete correction, or reject with a reason.
- Whether another round has a concrete new question or whether no new decision-relevant evidence remains.

A single response is advice. A completed exchange also addresses objections to that response.
The caller records convergence, unresolved disagreement, or a blocked/inconclusive ending according to
what happened. Agreement alone is not evidence that the proposal works.
