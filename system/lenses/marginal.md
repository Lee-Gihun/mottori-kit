<!-- source: marginal.ko.md sha256:e34921feb48d7cca47079f90b192cf7a11384a22fad4dd4bc8ee693f61d33c42 source-of-truth: ko -->
Korean: `marginal.ko.md`

# Marginal value lens

> Question: **Where would the next hour make the biggest improvement?**
>
> When to use: When you must split time, budget, or length across several places. When you are unsure
> whether to stop polishing. When you keep going because you do not want to waste what you already put
> in. When you keep going over something that is past. Turn it off while you are doing work you already
> decided to do.
>
> What to leave behind: One place to put the next unit into, and one place to take it from.

## Summary

When you decide how much to spend on what, look at the next unit instead of the total spent so far. Time
and money already spent do not come back whatever you choose, so they must not affect future choices.
So you ask only one thing: where will the next unit make the biggest improvement? The same question
works when you keep going over something that is past. Ask "will anything change if I think about this
for 10 more minutes?" If nothing will, stop.

## Example

You have two and a half days of work time left this week and three candidate tasks. One is adding more
tests to the payment feature, which already has 80% test coverage. One is fixing a flaky automated check
that has to be rerun three or four times a day. One is polishing the documentation for a new feature.
Take half a day as one unit and compare "the next half day" for each candidate. The tests already cover
the important paths, such as payment, refund, and duplicate payment, so another half day would change
little. Fixing the automated check stops five team members from losing 20 minutes each every day, so its
first half day has the largest effect. You put the next half day into the automated check and take that
time from the extra tests.

Numbers make it clearer. You have 4 hours to study. Subject A goes up 1 point per hour. Subject B goes up
5, 3, 2, and 0.5 points for each successive hour. Spending all the time on A gives 4 points. Splitting it
half and half gives 10 points. Spending all of it on B gives 10.5 points. Spending 3 hours on B and 1
hour on A gives 11 points, the highest. Keep putting hours into B only while B's next hour is worth more
than A's 1 point.

## Why it works

What you have already spent cannot be recovered whatever you do next, so it is right to leave it out of
the calculation. But people feel as if what they spent is something they still hold, so they keep
holding on. Asking about "the next unit" directly lets you get around that feeling. Also, for most work,
the more you do, the less one more unit improves things. So instead of putting everything into one
place, it is better overall to split units so that the effect of the next unit is about the same in
each place.

## How to use it

- **Ask about the next unit**: Take whatever is scarcest in the situation as one unit. It can be an
  hour, money, one slide, or one question. Ask where putting that unit in would improve things most. If
  putting it anywhere changes nothing, do not put it in. Deciding not to make something is also a
  choice.
- **Stop going over the past**: When regret or self-blame repeats, ask "will anything change if I think
  about this for 10 more minutes?" If nothing will, stop and spend those 10 minutes on one small action.
- **Notice the point where more does not add more**: If you keep doing the same thing, there comes a
  point where the effect drops clearly. Studying, polishing, meetings, and reading material all work
  this way.
- **Move units**: At regular intervals, pick two places. One is where taking a unit away loses little.
  The other is where putting a unit in gains a lot. Whether you are currently putting a lot or a little
  into a place is not the criterion. If the gain is still larger after subtracting the cost of moving,
  move one unit.
- **Look at cost as the next unit too**: The cost of "taking on one more thing" grows the more you have
  already taken on. When a schedule gets full, the time that gets pushed back grows sharply.

## Where to use it

- **When you split experiments or research**: Compare a sixth experiment in a direction you have
  already tried five times with a first experiment in a direction you have not tried. If the first five
  gave the same answer, you often learn more from the first experiment in the new direction. If you are
  reading the tenth source on the same topic, check whether you are learning almost nothing new, and
  move to another topic.
- **When you stop polishing**: Ship it when the improvement from one more hour of polishing becomes
  smaller than what you would gain by starting the next task in that hour.
- **When you decide whether to buy an add-on**: Do not judge by the total price. Subtract the part that
  overlaps with what you already have, and compare only the new part with the price. Do not see a new
  commitment as something added to your existing schedule. Judge it by what it replaces.
- **When you prepare for a meeting**: In a 30-minute meeting, you learn most when you ask about things
  only the other person knows, and least when they present again what you have already heard. Choose
  your questions in that order.

## Ways to misuse it

- **Cutting work that needs long stretches into small pieces**: Deep focused work, building trust, and
  building basic fitness only pay off when you spend long, unbroken time on them. If you split them into
  small units, you never reach the point where they pay off. Use this lens only when you split what to
  do. Do not use it while you are doing work you already decided to do.
- **Going only where you can measure**: Time flows only to work whose effect is easy to see in numbers,
  and relationships or health, whose effect is hard to see, stay short of time. Writing down separately
  the places you could not measure prevents this.
- **Using it as an excuse to break a promise**: Not counting what you already spent does not mean you
  may break promises. Breaking a promise lowers your future reputation and trust.
- **Treating an estimate like a measurement**: The effect of the next unit is mostly an estimate. Do not
  invent numbers to fill unknown cells. If the difference in size is clear, choose by a rough
  comparison, and write down the assumption together with "what would change the verdict if it were
  confirmed."

## With other lenses

- **Ergodicity** (the lens that first asks whether there is an irreversible loss): Even if the next unit
  has the largest effect, do not choose it if it carries a risk of irreversible loss.
- **Feedback loop** (the lens that looks at how others react to your action): The Feedback loop lens has
  the calculation for why the cost of "one more" grows sharply as a schedule fills up.
- **Ledger** (the lens that tracks what is scarce and what it costs): The Ledger lens has the method for
  leaving items you could not measure marked as "unmeasured."
- **Feynman** (the lens that checks understanding by calculating it yourself): Use this lens to decide
  how deep to check with the Feynman lens.

The full list of all 13 lenses is in [README](README.md).

## Usage records

Do not write actual usage records in this engine document. The location and format of records follow
the records section of `system/deep-pass.md`. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

The marginal revolution (Jevons, Menger, Walras) · Thaler's mental accounting · literature on the balance between exploration and exploitation.
