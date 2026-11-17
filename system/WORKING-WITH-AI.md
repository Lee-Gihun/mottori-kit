<!-- source: ko/system/WORKING-WITH-AI.md sha256:22d045862d371bca63b9a027c4cedbc4166a40ecef8c1ff9bcf686f096300650 source-of-truth: ko -->
Korean: `ko/system/WORKING-WITH-AI.md`

# A frame for large work with AI

Written 2026-08-15. It comes from a post-mortem of the "paper radar" run. The paper radar was a task in the
original workspace that read all 660 arXiv papers and lab outputs from four months and measured the evidence level
of each field (26 hours, hit the usage limit 3 times, switched the execution platform once).
This document is not that project's documentation. It is **a frame for ordering and designing the next task**.

Reading order: read §0 first, then reread only the §7 checklist right before placing an order.

---

## 0. Premise: what actually changed

Almost every human knowledge practice was built on the constraint that **reading is expensive**. Abstracts,
review papers, impact factors, and an advisor's recommendations all exist for the same reason. Nobody could read
everything, so filtering had to come before reading.

What changed now is that **reading and verification became cheap at the same time**. Only two things are still
expensive: **human attention** and **the resolution of the question.**

So imitating human practice faster is not optimal. It inherits a constraint that has disappeared. A Cochrane
systematic review spends 12 months on 50 papers, and half of its procedure (fixing the question before searching,
screening before extraction) exists because reading was expensive. That half can be dropped.

**Two things that scale itself demands remain: decide the success measure first, and treat interruption as a
normal state.**

---

## 1. When reading is cheap, the question changes from "what to read" to "what to measure"

> **Order an instrument, not a summary. The reading list falls out as a by-product of measurement.**

"Which 20 papers should I read" is a question created by expensive reading. The new question is **which property
of this object you want to measure**.

Three measurements the radar actually produced, each of which exists only because everything was read:

- 2,157 distinct benchmark names, of which **fewer than 5% were used by two or more papers**. So leaderboard
  numbers cannot be compared with each other
- The agents field, second by paper count, had a mean evidence grade near the bottom. That field is where interest
  and evidence diverge most
- 5,915 reported numbers traced back to their originals, **3 without support**. This is a measured value for how
  far to trust this corpus

**Symptom:** if the output contains no "number that is true of this whole object", you ordered a summary.

## 2. The bottleneck moved from effort to the resolution of the question

> **Breadth is free. What is not free is vagueness.**
>
> "Free" here does not mean zero compute cost. It is a comparison: in this run, the range of human screening was
> not the bottleneck, and the vagueness of the question was the bottleneck that caused rework.

A machine executes a question at exactly its resolution. "Organize all the papers" ran at exactly that resolution
and became an archive. Asking a blurry question and getting a feel for it along the way only worked when reading
was expensive.

**This is not "ask narrowly".** Keep the scope large, but ask **a question whose answer comes out in measurable
form**.

- Bad: "Organize all papers from the last 4 months"
- Good: "Read everything from the last 4 months and measure **how this field verifies its own claims**. Find every
  pair of papers that refute each other."

## 3. Separate corpus size from output size

> **Reading everything and showing everything are different decisions.**

This was the radar's actual error. Reading 660 papers was right. Delivering a 660-item output was wrong. The same
corpus with a different rendering would have worked.

So **stating a reading budget first** is still valid, but for a different reason. It is not to shrink the corpus.
It is **to decide the output format**. With "5 papers a week", read all 660, but the output must be a four-week
curriculum.

**Symptom:** if the output has more than 10 times as many items as you can consume, the rendering is wrong.

## 4. Plausibility is not a signal. Only what is falsifiable is a signal

> **Every output is plausible. What carries information is only what could have been wrong and was checked.**

Everything of highest value in the radar was in this category.

- A number audit caught and fixed 3 unsupported numbers (the judging agent rendered a PDF at 400 dpi and measured
  marker pixels against grid lines)
- Of 4 substantive error reports, **2 were judged false positives and left unfixed** (thanks to the prompt stating
  "do not invent things to fix" and "not-an-error is a legitimate result")
- The schema forced the fields `what was not proven` and `limits the paper did not state itself`

> **Rule: put in one field where the output can embarrass itself. If that field is empty, the rest cannot be
> trusted either.**

Two attached rules. Both bit during the porting work on 2026-08-24.

- **Writing "not verified" is not a release from liability. It is open work.** Writing it in a comment feels like
  handling it, but nothing has been handled. If you leave an uncertainty, build the test that closes it, or put it
  where it will be met again (a checklist or an instrument). *(Measured: a docstring said a path rule was
  unverified for certain characters, and it shipped as is. Measured later, the rule was actually wrong.)*
- **If a sample shares one property, a pattern may be chance, not a rule.** Before generalizing, ask "what does
  every item in this sample have that the population does not". Then **build** a sample that breaks it and
  measure. *(Measured: a name-mangling rule was set from 12 project keys, and all 12 were alphanumeric paths. The
  rule was `[/_]`. The actual one was `[^A-Za-z0-9-]`. Paths with spaces or dots would have silently produced
  empty results.)*

- **Record report verdicts with present (did the behavior happen) and effective (could it change the result)
  separated**. Leave an undecidable verdict as UNCLEAR, and UNCLEAR does not raise the higher-level verdict
  (paper 2609.07925 appendix F.4).

## 5. Conversation is a volatile medium

> **Everything that must survive lands in files, and a tool must recompute "what is left" from those files.**

This is the only reason the radar survived 3 usage limits and 1 platform switch. Progress state lived on disk, not
in the model's head, and one line of a state recomputation tool recomputes what is left.

This is not an operational detail. It is **the precondition that makes long AI work possible**. Without it, work
cannot outlive one session. With it, work can be continued indefinitely.

**Do not run broad reading, audits, or cross-runtime debates directly inside the endless main session (the
master) (KIT-DR-007).** Hand them to a worker with
`python3 tools/fresh_worker.py --runtime claude|codex <prompt-file>`. The worker starts fresh with no earlier
conversation and leaves no session behind. The full run record stays in `_private/work/runs/`, and only a short
receipt with a size limit (verdict, what was not verified, location of the full text) returns to the master
session. `PRD-session-memory.md` §10.5 is the source of truth for the exact receipt size limit and the capabilities
a worker gets. Delegating a small conversation or a one-file edit only adds round trips, so use it only for work
whose tool output would likely exceed the receipt limit. Both the Claude and Codex launch modes block user
connectors and spawning further workers, so write the needed NOW, dossier, and original paths directly into the
order.

Three attached rules, all of which actually bit in the radar:

- **Write after each item finishes.** If you collect results and write at the end, an interruption loses
  everything.
- **Do not judge freshness by mtime.** If a regenerator rewrites a file even when content is unchanged, it shakes
  its own clock and invalidates itself. In the radar, a watcher rewrote DIGEST every 2 minutes, and 178 papers in
  the final review were misclassified as provisional. **Judge frozen targets by content hash, and have
  regenerators skip writing when content is unchanged.**
- **Do not draw dependencies wider than they are.** One wrongly tied barrier made the cheapest output (113 Korean
  narrative write-ups) block the most expensive stage (re-review of 660 papers).

**There are four forms of order.** A read-only Claude worker, a Codex worker that can write to a work copy, a debate
round (one turn appended to the debate file at a time), and a role the session takes directly inside a deep pass.
Other forms such as garden cleanup or sync are added separately by an instance. When a new structure seems
needed, use an existing form first, and explain an exception only when there is a new isolation requirement
(paper 2609.02264: about six connection structures were actually useful, and the number of connections between
agents was negatively correlated with token use). Worker count and round trips do not stand in for cost. Measure
with actual tokens (usage in `meta.json`), time, and changes in verdicts.

**Use workers to gather information, and let the main session write the result.** A team that gave workers only
the planning matched the score of a team that handed over everything, at half the cost, and sub-agents did better
only on work with clear inputs and outputs (papers 2610.17471, 2609.09233). **In the order, write what the worker
may change, what it may only read, what it must deliver, and what it must not touch.** Writing these four fields
cut unrequested additions from 56 to 22, and naming the specific files in scope worked where a vague warning such
as "work may overlap" did not (papers 2611.01265, 2610.07261).

**Close the job.** When state lives on disk, the disk only grows. When a job starts, put one page at the top of
its folder (`STATE.md` or `README.md`). It says what the job is, its current status, where to start reading, and
what may be deleted. Make temporary copies and intermediate outputs in one place only (under `tmp/`). When the
job ends, write "done" and the date on that page, together with what to keep (results, evidence, how to rerun)
and what may be deleted. Whoever dispatched the work deletes the temporary copies it made. Anything that cannot
be rebuilt from something else, such as transcripts, journals, decision records, and manuscripts, is never
deleted automatically. Put what you would delete or compress in a list and ask the owner. *(Why: when finished
and running jobs, and originals and copies, are not told apart, nobody knows what to clear when the disk fills
up, and finished work cannot be found again. `decision:KIT-DR-027`.)*

## 6. People stand at the back, not the front

> **Filtering at the front loses scale. Judging at the back keeps scale and gains direction.**

If a person enters as a pre-filter, the advantage that AI can read everything disappears. But there is one role
only a person can play, and it is **calibration**.

Not "approve this list" but **"which of these three actually changed your work."** It takes five minutes, and it
is **the only signal in the whole system not generated by AI**.

Without it, the selection criterion stays an AI-written criterion forever, and nobody knows how far it is from a
human one.

## 7. Checklist before ordering

Look at only this right before ordering. If you can answer all six, the resolution is sufficient.

1. **What does it measure?** Does at least one number come out that is true of the whole object
2. **How much can I consume?** (the value that sets the **output format**, not the corpus size)
3. **Which field can be wrong?** The field where the output can embarrass itself
4. **Where does it resume after an interruption?** Which file the state lands in, and what computes the remaining
   work
5. **How will success be known?** What would be different in six months if it succeeded
6. **Does it keep number lineage?** The line below

> **Number lineage.** For every important quantitative claim, keep the value, unit, object, period, definition,
> and location of the raw data (or the formula).
> **Keep competing values for the same estimand together with their time, scope, and denominator, and do not pick
> one before they are reconciled.** For a ratio, state the numerator and denominator when possible, and otherwise
> write `denominator unverified`.
>
> *(Why: observation. On one corpus, the original authors, the collection stage, and the review stage distorted
> numbers in the same direction. Mechanism. The value that makes a cleaner sentence gets chosen, and the
> distortion accumulates in the same direction stage by stage. Blocking point. The moment a number is copied into
> an output. **Caution:** the three stages share the same corpus and narrative, so they are correlated
> observations. Do not call this a "dominant bias" or an "independent replication". One run cannot say that.)*

**"If there are two values, keep both" is right only for competing values of the same estimand.** Putting two
different metrics side by side does not create comparability. A computed value needs **its input locations and
formula**, not a line number in an original.

### Order template

```
Read all of [object] and measure [the property you want to measure].
Do not reduce the breadth. Instead, render the output so that I only have to consume [consumable amount].
For each item, also write "where it would show if it were wrong".
Keep progress on disk, and also build a tool that recomputes the remaining work.
When it is done, I will look at [N] items and mark which were actually useful. We will rerank with that.
```

## 8. Do not inherit

These are relics of the era when reading was expensive. Carrying them over discards the newly gained capability.

- Fixing the question before searching (it is better to sweep broadly and let the question come from the data)
- Abstract screening before extraction (**selection has grounds only when it filters on the body, not the
  abstract**)
- A person's pre-approval gate
- The allocation "go deep only on what matters" (depth is cheap now. What is expensive is human attention, and that
  is an output-side problem)

## 9. What was verified this time (do not discard)

- **Do not transplant another runtime's, another harness's, or a paper's success method wholesale.** Fix one
  failure point of the target runtime and re-verify both sides (paper 2609.09134 §3.3: wholesale imitation lost
  14.9 points, fixing only the failed turns gained 1.7 points).

- State on disk, and a recomputation tool such as `status.py`
- **Re-review in clusters.** When one agent looks at 5 papers together, conflicts between papers appear that
  reading alone would never show. The best output of this work came from here
- PROVENANCE that states the gaps first. The radar's reliability comes from stating what it did not see
- Tracing numbers back and judging each one
- **Stage boundaries.** When the narrative writer suspected errors in an existing analysis, it was allowed only to
  report, not to fix. 2 of those reports were false positives, and the sound analysis was not damaged
- A live page a person can follow during the run (progress page pattern: progress bar, in-flight items, and
  **recent outputs with their content**, newest first)
- **In large work without a deterministic checker, the run that produced the output is not its only verifier.** A
  separate call to the same model does not count as independent confirmation (paper 2609.01481 §3.4.3: separates
  implementation tests from independent quality checks. Measured in the original workspace on 2026-09-03 and
  09-06: review by Codex, a different model, caught 1 and 33 defects respectively)

---

## Appendix: the run this frame came from

That run covered 660 papers (482 from arXiv and 178 lab outputs), 8 sources, 26 hours, 3 usage limits, and 1
switch to Codex. Its methods, tools, confirmed gaps, and self-verification results remain in that run's HANDOFF,
PROVENANCE, and QA documents (they are in the original workspace. This kit carries only the frame).

## Links to normative and numeric grounds

The imperative sentences in this document are procedures for not repeating, in the next broad task, the failures
observed in the 660-paper run in the appendix above. 660, 482, 178, 26 hours, 3 times, and 1 time are lineage
values of that single run, not general claims about a population. The original HANDOFF, PROVENANCE, and QA are in
the original workspace and cannot be independently re-verified in this kit. The small numeric examples in this
document are toy values that show how something works, not thresholds or population estimates.
