<!-- source: README.ko.md sha256:d94e36006b986a2852c840a2e99da63164ac730137217ccf97f49372679ecf3b source-of-truth: ko -->
Korean: `README.ko.md`

# Thinking lenses

This is the invocation index. Open a lens's document before using it: its mechanism, worked examples,
and failure terrain matter more than its label.

The 13 shipped lenses form a seed library for recurring reasoning failures. They are not a complete
checklist or a ceiling on possible perspectives. Consider task-specific perspectives alongside them and
keep those that add a distinct counterexample, constraint, or answer.

## Tools and responsibilities

- **Lens:** a question that tests a claim or decision.
- **Ad hoc perspective:** a task-specific question subject to the same selection test as a named lens.
- **[Deep pass](../deep-pass.md):** a procedure combining evidence, perspectives, judgment, and review when depth is requested.
- **Role:** a viewpoint with a stake and evidence. Do not simulate a real person's private views; use attributable statements or leave a question.
- **[Debate](../debate/README.md):** another model's challenge to assumptions and evidence. Model diversity is not proof of independent evidence.
- **Fresh reader:** a context-free comprehension probe, which can use the same model family. It does not replace substantive review.
- **Record:** an instance observation of what was considered, changed, and later supported or rejected. It is not part of the engine definition.

## The library

| Lens | Invocation question | Definition |
|---|---|---|
| Ledger | What quantity must balance, and where is a cost or constraint being omitted? | [ledger.md](ledger.md) |
| Feynman | Do we know the mechanism, or only its name? Can we calculate a small case? | [feynman.md](feynman.md) |
| Inversion | What would make this fail, and what is the cheapest relevant falsification? | [inversion.md](inversion.md) |
| Limits | What happens at the boundaries, and where might the governing behavior change? | [limits.md](limits.md) |
| Isomorphism | Which other field has the same difficult constraint, and where does the analogy break? | [isomorphism.md](isomorphism.md) |
| Fence | What failure did this practice prevent, and does that condition still exist? | [fence.md](fence.md) |
| Marginal utility | Where would the next unit of effort change the outcome most? | [marginal.md](marginal.md) |
| Jensen | What new opportunity has become possible, and where does the whole system lose value? | [jensen.md](jensen.md) |
| Mirror | If I am the source of this judgment, what evidence supports it? | [mirror.md](mirror.md) |
| Incentive | What is the speaker or system rewarded for believing or producing? | [incentive.md](incentive.md) |
| Ergodic | If this goes wrong, is there another attempt? What happens with repeated exposure? | [ergodic.md](ergodic.md) |
| Silence | What cannot appear in these data because of how they were collected? | [silence.md](silence.md) |
| Feedback | How will the system respond to this intervention, and where is the delay? | [feedback-loop.md](feedback-loop.md) |

## Combinations, not mandatory sequences

Choose an order that matches the dependencies in the task. These are starting examples:

- A blocked problem: ledger, limits, inversion.
- Incoming evidence or advice: silence, incentive, Feynman.
- A decision: ergodic, marginal utility, inversion.
- A system intervention: feedback, fence, ledger.
- A proposed connection between fields: isomorphism, followed by a concrete check.

For the owner's self-claims, the [rituals](../rituals.md) require checking existing evidence before promoting
an interpretation. This does not authorize dismissing the owner's stated experience or inventing preferences.

## Selection, recording, and revision

Use lenses for blocked problems, design, decisions, or explicit requests. Do not attach lens labels to every
small answer. A task can use none, a few, or a new perspective; coverage is not measured by reciting all 13.

The current library size is a maintenance choice. Adding, merging, or retiring a shared definition requires
an explicit policy decision grounded in the failure it addresses and the outcomes of relevant comparisons.
Use counts alone do not measure effectiveness. A rarely used lens may protect a rare important decision;
a frequently named lens may have changed nothing. Record both successful challenges and unchanged results.

Keep application records in the instance's `_private/deep-pass/ledger.md`, following the
[recording contract](../deep-pass.md#recording) and [blank template](../../templates/deep-pass-ledger.md).
Never append cases to these tracked lens files. Shared examples must be deliberately reviewed for reuse;
removing a name from a private case does not make it publishable.

This index is kit-owned. Its policy and the individual definitions are reusable material; instance
observations and local review schedules are not. Review lenses as reasoning aids with explicit limits,
not as universal laws or evidence of quality merely because their names appear in an answer.
