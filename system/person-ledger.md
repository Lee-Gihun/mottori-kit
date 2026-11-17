<!-- source: ko/system/person-ledger.md sha256:0a5a07919d5481326da9a1c07c3f473bf0160c71a03dcd9049bfd828d82ef50a source-of-truth: ko -->
Korean: `ko/system/person-ledger.md`

# Person ledger: recording one person in layers

> Question it answers: **What has already been decided, and what do I still need to ask?**

This is a ledger of what has already been decided about the owner and what is still to be asked. A deep pass
(`deep-pass.md`) also reads it when it checks the owner's decisions. The owner is the one person a model cannot
know from training, so the owner alone gets a thick file.

## This file does not answer "who is he"

It answers two questions only: **what has already been decided** and **what still has to be asked.** A portrait
of the person is not the goal. It is a by-product that appears when those two are not filled, and the main
failure of this document is the by-product swallowing the body.

The right size follows from this. With zero lines, everything must be asked every time, and **the cost is his
attention**. With unlimited lines, everything gets guessed by extrapolation, which amounts to acting out a real
person. So the criterion is not length but one test.

```
Admission   1. A model cannot work it out from a short cue          (fence lens)
      AND   2. He would be annoyed at having to say it twice       (marginal lens)
```

Meeting only the first makes it trivia. Meeting only the second means the model knows it anyway. A line gets in
only when both hold.

## Write the sampling bias at the top

**Every person ledger is the output of some channel, and a channel does not report on itself.** So the first
block says what the ledger was built from and **therefore what in principle cannot get in**. If this is pushed
down into a later correction, conclusions keep coming out biased while the bias is already known.

A typical gap: a ledger built from conversation logs **does not contain what he resolved with other people.** It
is absent from the logs, so it reads as "no such relationship exists", and that misreading is the most painful
kind of misreading about a person.

## Four layers

```
L1  Statement       What he said. Original text, date, source. The origin: it can be quoted; a summary is derived
L2  Decision        Decisions he actually made and the reasons he gave then. Observed
L3  Interpretation  My model. Lowest grade. It cannot enter without a date, evidence, and a refutation condition
L4  Unknown         What still has to be asked. Do not guess the answer; write it as a question to ask
```

**L1 and L2 accumulate. L3 has to earn its place.** Mixing grades in one paragraph lets the lowest grade borrow
the trust of the highest. Fluent prose works exactly that way.

**L3 carries three fields:** when it was written, what it was based on, and **what observation would show it
wrong.** Without the third, it is an impression, not an interpretation. Write L3 **as items, not prose.** A
paragraph cannot be audited line by line, and what cannot be audited cannot be corrected, even by the person.

**L4 takes what would otherwise overflow into L3.** The moment you want to extrapolate is the moment to write
one line in L4. If the person can be asked, ask instead of guessing. This person can be asked right away.

## Harvest instead of authoring

A ledger starves not because the rule is weak but because **it has to be written separately by hand.** The
journal, the fact ledger, and recall fill up on their own. If only this ledger needs separate authoring, it
starves exactly in busy periods. Busy periods have the most material, so the loss is largest.

So L1 and L2 candidates are **lifted from material that already accumulates**, and only adoption takes judgment.
Automatic adoption is forbidden. If adopted automatically, an interpretation (L3) gets recorded as a statement
(L1).

## Cancel instead of deleting

A wrong interpretation is not deleted. It stays with a strikethrough and a link to the correction. **What I
believed is data about how I fail**, and deleting it repeats the same error. For the same reason, the person's
own corrections are kept at the highest grade. They are records of the person directly correcting my model, so
they are the most costly to forge.

**Do not judge a frame's expiry by date alone.** A section written on the premise of a particular decision does
not just become old when that decision closes. It becomes **wrong to quote**. Writing the premise at the head of
the section makes the expiry visible.

## Failure modes

- **Fluency inflation:** prose grows while the operating layers do not. Detect it with the length ratio by layer.
- **Failure sample:** if only the correction log grows, it is a **map of my failures**, not a portrait of the
  person. Things he was consistently right about, so that nothing needed correcting, cannot in principle enter
  this log. Add counter-samples on purpose: preferences confirmed repeatedly without correction.
- **Frozen mood reading:** quoting a reading of his state at one point in time as present-tense months later.
  Always put a reference date on a state reading, and update by adding a new item, not by editing the original.
- **Ledger exemption:** applying evidence rules to other documents while letting this file off.

## Retirement and review

If looking up the ledger never changes a decision, or no L4 item ever goes out as a real question, this
structure is only cost. Then keep L1 and the correction record and fold the rest.

## Links to normative grounds

Grade separation, the ban on automatic adoption, and keeping cancelled records prevent an attribution error in
which a fluent derived interpretation is promoted as if it were the owner's own words. L1 through L4 are schema
labels based on distance from evidence, not measured quantities. A promotion criterion such as "three times" is
this document's operating limit, not a claim about a population.
