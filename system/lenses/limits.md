<!-- source: limits.ko.md sha256:48507ffaa00cf2544ba249eebb65912af21b43a21a6ac4b280946d0d729463ba source-of-truth: ko -->
Korean: `limits.ko.md`

# Limits lens

> Question: **What happens when you push the value to zero, and to infinity? From where does it start
> to behave differently?**
>
> When to use: When you have to decide "how much," such as a count, a size, or a range. When you hear a
> claim like "more is better." When a new formula or rule has been checked only at middle values.
>
> What to leave behind: One line each on what happens at both ends, and the point where the behavior
> starts to change. If you do not know that point, write that you do not know.

## Summary

When a claim or a formula is wrong, it is often visibly wrong at the extremes. In the middle range, many
factors mix together, so it looks plausible. So you push an adjustable value to zero and to infinity.
This is a check you can do in your head without an experiment. While you push the value, you sometimes
meet a point where it starts to behave in a completely different way. Where that point is matters as
much as the result at the ends.

## Example

There is a proposal to raise app notifications from 3 times a week to 7 times a week. First push it to
zero. If you send no notifications at all and use only email and in-app banners, what do you lose?
When you work it out, what you lose is roughly "people who left items in their cart coming back within
a day." Now increase it without end. If you send dozens a day, people turn notifications off or delete
the app. Then what you really need to know is "from how many per week does the number of people who
turn notifications off rise sharply?" The proposal changes from "raise the total count" to "keep the
cart notification, and first measure on a small scale how the rate of turning notifications off
changes with the count." Write down that you do not know yet where that point is.

With a formula, it is even simpler. Take the value that controls how evenly probability is spread (the
temperature in softmax). As it approaches 0, all the probability gathers on the option with the highest
score (if several options tie for the highest, they share it). When it becomes very large, all options
get the same probability. If a newly proposed method is said to keep this property but does not behave
this way at the two ends, also doubt the performance gains it showed at middle values.

## Why it works

When you send a value to an end, one factor usually overwhelms the rest. You can no longer blur the
answer by leaning on other factors, so it becomes clear whether the claim is right or wrong. Points
where behavior changes appear for the same reason. Many systems change little by little, and once they
pass a certain point, a different factor takes control and their character changes.

## How to use it

- **Push to zero and to infinity**: Send values such as a count, a size, a weight, or a period to both
  ends. Also push the effort or cost you put in. On the zero side, ask "if I do nothing and use only
  what already exists, what do I lose?" Among the things you would lose then, the ones you must not lose
  are candidates for the work you need to do.
- **Push only one value**: Send only one value to an end and leave the rest as they are. This shows which
  value drives the conclusion.
- **Plug in the simplest cases**: Try the case with nothing, the case with only one, and the case of
  comparing something with itself. If the definition or rule makes no sense here, it is not polished
  enough.
- **Find the point where it changes**: Change the value little by little and find the point where "from
  here it behaves differently." When you find it, write down what drives the behavior before that point
  and what drives it after.
- **Push time**: Ask "what if I keep doing this for 10 years?" and "what if I do it for just one day?"
  Use this to check habits or strategies.
- **If everyone did it**: Ask "what happens if everyone does this?"

## Where to use it

- **When you design a product or a policy**: Pick one axis, such as how much the user controls directly
  and how much the system does on its own. Write down how it breaks at each end. The range between the
  two points where it starts to break is the range you can design within.
- **When you check a new formula**: See whether setting a coefficient to 0 gives the same result as the
  existing method, and whether making it very large gives what you expected. If it differs, you must be
  able to explain why.
- **When you read someone else's claim**: When you see a claim that "increasing X improves Y," picture
  what happens when X is increased all the way. If it makes no sense at the end, there is a point
  somewhere in the middle where the behavior changes. A claim that did not measure that point may be
  claiming a wider range than is true.
- **When you decide on a large expense or a habit**: Ask "what would my life look like if I multiplied
  this by 100?"
- **When your worry is large**: Follow "if the worst thing actually happens, what exactly would I do?"
  to the end. When you follow it, the worry often turns into a response plan you can carry out. What
  remains after that is what you actually need to prepare for.

## Ways to misuse it

- **Assuming the middle is right because the ends are right**: Even when both ends are right, the middle
  can behave differently. Checking the ends is the minimum check.
- **Judging reality by an end you cannot reach**: Do not decide the range of reality from the result of
  an extreme that cannot actually happen. An extreme shows structure, but it does not make predictions.
- **Only naming every bend**: Calling a place where change speeds up "emergence" or a "tipping point" is
  not an explanation. You must write where that point is and what drives the behavior before and after
  it.
- **Saying the middle is the answer because both ends are bad**: If you conclude "a reasonable middle"
  only because both extremes are bad, you have decided nothing. Write where the problem at each end
  starts. That tells you where in the middle to be.

## With other lenses

- **Ledger** (the lens that tracks what is scarce and what it costs): After you set up items with the
  Ledger lens, check the ends of each item with this lens.
- **Feynman** (the lens that checks understanding by calculating it yourself): Pushing to the ends is
  the cheapest small calculation you can do.
- **Feedback loop** (the lens that looks at how the other side reacts to your action): Use this lens to
  find the effect where waiting grows sharply as spare capacity approaches 0, and use the Feedback loop
  lens to explain it.

The full list of all 13 lenses is in the [README](README.md).

## Usage records

Do not write actual usage records in this engine document. The location and format of records follow
the records section of `system/deep-pass.md`. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Anderson, "More Is Different" (1972) · Asymptotic analysis · Polya, *How to Solve It* (boundary cases) ·
Kant's universalizability test.
