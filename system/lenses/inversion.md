<!-- source: inversion.ko.md sha256:319b8ca843c15a42393f95a1b76a69a120eaee008e1fd3e1e374ae44f22f62a1 source-of-truth: ko -->
Korean: `inversion.ko.md`

# Inversion lens

> Question: **What would make this fail for sure? What is the cheapest way to check whether my idea is
> wrong?**
>
> When to use: Just before you run, send, or lock in a design. When there are too many candidates. When
> you have piled up only reasons why it will work.
>
> What to leave behind: A few conditions that make it fail, and for each condition what you removed,
> reduced, or put an alarm on, or your reason for leaving it as it is. One cheapest disproof.

## Summary

"How do I succeed?" has endless, vague answers. If you turn it around and ask "what would make this
fail for sure?", you can write much more concrete answers. So you flip the problem, write down the
conditions that make it fail for sure, and avoid them. Avoiding the failure conditions does not
guarantee success, but it shrinks the range you need to look at. The mathematician Jacobi's "invert,
always invert" and Charlie Munger's "tell me where I'm going to die, so I'll never go there" are the
same idea.

## Example

You are about to release a new recommendation model to half of the users. Assume "this launch failed"
and write down the reasons. The input values were computed differently in training and in serving. The
model leaned toward popular items, so users with rare tastes became less satisfied. Responses got
slower. For each reason, choose a signal that warns you in advance: the difference in input value
distributions, the click rate of the group of users with rare tastes, and response time. As a result,
you extended by one week the period of running it out of sight of real users, and you put an alarm on
the metrics for the group of users with rare tastes.

## Why it works

Conditions for failure are easier to find than conditions for success. Success has many causes that
overlap, so it is hard to tell what it was due to. Failure conditions can be separated and checked one
at a time. Also, each time you remove a failure condition, the range you need to look at shrinks.

## How to use it

- **A failure report written in advance**: Before you start, assume "this work failed" and write down
  two or three reasons. For each reason, choose one signal that can warn you in advance.
- **The cheapest disproof**: Start with the cheapest experiment that can show your hypothesis is wrong.
  Collecting many pieces of evidence that it is right still does not settle a hypothesis. If the
  measurement is reliable, one piece of evidence that it is wrong is enough. But a test that will
  obviously pass tells you nothing, even if it is cheap. Pick the cheapest test among the ones that can
  actually fail.
- **Elimination criteria first**: When there are many candidates, write the criteria for dropping them
  before the criteria for choosing.
- **Write the stopping conditions in advance**: Before you start, write down "if I see this, I stop."
  While the work is in progress, it is hard to judge well because you do not want to waste what you
  already put in.
- **Think by removing**: When you hear the claim "it worked because of X," ask whether it would have
  worked without X.
- **Work backward from the finished state**: First write down what things look like when the work is
  done, then work backward from there to today's task. Counting backward from the date you need also
  tells you whether there is a reason to hurry now.
- **Filter out fake success**: When you choose a metric, first write down cases where the metric
  improved but things actually failed. Examples are a case where the metric rises only for one group of
  users while another group loses, and a case that is marked as learned when nothing was learned. Do
  not use a metric that cannot tell these cases apart.

## Where to use it

- **When you review a design**: Handle two or three ways it can fail before the ways it can work. For
  each way, check whether the current design blocks it.
- **When you design an experiment**: First write down "the conditions under which this experiment
  proves nothing." Common ones are not matching the comparison targets well enough, noise in the
  measurement that is larger than the expected effect, and not controlling other factors that affect
  the result. Prevent noise by calculating the number of repeats or the sample size in advance.
- **When you read a paper**: First ask "if this claim were wrong, which table should have shown it?" If
  that table is not in the paper, that is also information.
- **When you choose between options**: For each option, first write down "the path where things are
  worst three years from now." Compare the options on how likely that path is and whether you can undo
  it if you end up on it.
- **When you prepare a meeting or a piece of writing**: Before a meeting, first write down "the ways
  these 30 minutes fail," and turn them into a list of "things not to say." For writing, first write
  down the worst way it could be read, and remove that wording.
- **When you change daily habits**: If you write down "how would I surely become exhausted and
  collapse?", you see the items you are already doing. Remove those items before you add good habits.

## Ways to misuse it

- **Using only this lens**: This lens is a filtering tool, so it does not create new options. If you use
  only this lens, you cannot start anything.
- **Trying to block every failure you can think of**: Not every failure you can imagine is worth
  blocking. Choose by looking at how likely it is, how large the damage is, and whether it can be
  undone, together.
- **Blocking healthy things along with the failure**: If you block a failure path with a ban, the ban can
  also block normal paths. Before you write a ban, count what else gets blocked with it. Also check
  whether you can avoid the same failure by separating it out or by loosening a condition instead of
  banning.
- **Using it after the decision**: If you have already decided and you write down only why the other
  side fails, it becomes rationalization. Ask yourself whether you did this review before or after you
  decided.
- **Only writing things down**: If you write down failure conditions but do not check for each one
  whether it is blocked now, it is the same as not using the lens. For each condition, write what you
  removed, what you reduced, and what alarm you added. If you left it as it is because it is already
  blocked or because blocking it costs more, write that reason.

## With other lenses

- **Ergodicity** (the lens that first asks whether there is a loss you cannot undo): Among the failure
  conditions found by inversion, block the ones that cannot be undone first, even if they are unlikely.
- **Silence** (the lens that looks for what is missing from the data): Inversion finds what is missing
  from your plan. Silence finds what is missing from your evidence.
- **Structure mapping** (the lens that looks for the same problem in another field): If you need a new
  option, find it with the Structure mapping lens.
- **Mirror** (the lens that compares judgments about yourself against records): Use the Mirror lens to
  check whether an inversion was written after the decision.

The full list of all 13 lenses is in the [README](README.md).

## Usage records

Do not write actual usage records in this engine document. The location and format of records follow
the records section of `system/deep-pass.md`. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Jacobi "man muss immer umkehren" · Munger, *Poor Charlie's Almanack* · Klein's premortem · Popper's
falsificationism.
