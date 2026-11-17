<!-- source: feedback-loop.ko.md sha256:3235005ef57ccc05dc338281f8583aa76b49936b4655a3e10922ff108a4fbd07 source-of-truth: ko -->
Korean: `feedback-loop.ko.md`

# Feedback loop lens

> Question: **If I act, how does the other side respond? How late does that response come?**
>
> When to use: When you create a new rule, metric, procedure, or automation. When you change something
> and it returns to how it was. When a state of "busy" or "overwhelmed" continues. Do not use it on work
> whose results do not come back into later actions.
>
> What to leave behind: What increases what, what decreases what, and where responses arrive late. Then
> one line on what you changed because of it.

## Summary

An object that does not move gets pushed when you push it. People and organizations push back. When I
act, the other side adapts to it, and then responds again from the changed state. So a plan that never
asks "and what happens after that?" has decided only the first move. When a metric becomes a target, it
stops being trustworthy. This is the same effect, because people change their behavior to fit the
metric.

## Example

A request comes in to use "average time to handle one inquiry" as the performance metric for a customer
support team. Before you set the metric, write down what team members will do once they know about it.
They pass hard inquiries to other teams. They close a ticket before it is solved and let the customer
reopen it. They pick short inquiries first. All three are easier than actually solving the customer's
problem. So you do not use handling time alone. You also track the share of customers who contact
support again within one week. If people close tickets without solving them, this second number gets
worse, and the trick becomes visible.

## Why it works

There are two kinds of flows in which things affect each other. One is a flow that grows by itself. The
result makes the cause larger. Money that earns interest and reputation work this way. The other is a
flow that shrinks by itself. The result holds the cause down. A thermostat and prices work this way. How
a system behaves depends on which of the two is stronger. If a flow that shrinks by itself has a stage
where the response comes late, the system swings back and forth. This is why the water goes hot and cold
when you adjust a shower.

The same frame explains why slack is needed. Take the simplest model (M/M/1 in queueing theory). Work
arrives at random, the time to handle one item also varies, and there is one place that handles the
work. In this model, the average wait before handling starts is ρ/(1-ρ) times the time to handle one
item. ρ is the share of handling capacity actually in use. At 50% ρ the wait is 1 times, at 80% it is 4
times, at 90% it is 9 times, and at 95% it is 19 times. Suppose a place handles 10 items per hour. If
the incoming work grows by only half an item, from 9 to 9.5 per hour, the wait jumps from 9 times to 19
times. Slack looks like waste, but it absorbs work that arrives unevenly. When work starts to pile up,
the time spent switching between tasks and the amount of rework both grow. Then the handling capacity
itself shrinks, and things break down faster than this calculation says. These numbers are here to show
the shape: as slack shrinks, waiting grows sharply. The multiple changes with how much the handling time
varies, so it is not a value to apply directly to a personal schedule.

## How to use it

- **Draw the flows**: Before you act, draw with a few arrows what increases what and what decreases what.
  For a flow that grows by itself, mark where the mechanism that stops it is. For a flow that shrinks by
  itself, mark the value it aims at.
- **Handle late responses**: If there is a stage where the response comes late, look for a way to shorten
  that time. If you cannot shorten it, set the date to check the result in advance.
- **Ask "and after that?" twice**: Look at what comes after the immediate result, and at what comes after
  that. Ask only twice. If you go further, guesses pile on guesses and become hard to trust.
- **Separate amounts piled up from amounts moving in and out**: Look separately at the amount piled up
  now and the amount that comes in and goes out per period. The number of waiting inquiries is a piled-up
  amount. New inquiries per day and handled inquiries per day are amounts moving in and out. A piled-up
  amount goes down only when there is a run of days on which more goes out than comes in. Trust, stamina,
  skill, and sleep debt are also piled-up amounts. Trying to repay sleep debt built up over many days with
  one weekend lie-in is the mistake of trying to clear a piled-up amount with one day of movement.
- **Set an upper limit on how full to get**: For schedules, servers, and cash flow, set a rule that says
  "fill only up to this much." Many start at 70 to 80%. The more uneven the incoming work, the lower the
  limit. Read the feeling of "busy" as a signal that the slack has run out.
- **Separate the visible response from the actual change**: Write down separately the response the other
  side sees right away, what was actually applied, and the result that shows up later. If you make a
  "received" notice look like "fixed," trust drops when the other side learns that it was not fixed.
- **Predict how people will respond to a metric**: Before you choose a metric, write down what people will
  do once they know it. If hitting the number is easier than reaching the real goal, do not use that
  metric alone. Add another metric that exposes number gaming.
- **Check whether something uses its own output as evidence**: Check whether there is a path through which
  an automation or evaluation tool uses results it produced as evidence for its own judgment. And when you
  fix something after seeing the results, do not measure it again on the same data. Confirm it on new
  data.

## Where to use it

- **When you introduce a new rule or procedure**: Predict the state after people get used to it. The
  effect right after introduction often looks larger than it really is, because people have not yet
  responded.
- **When you build a habit**: Build a flow in which you act, record it where you can see it, and want to
  act again because you see the record. If the record is missing, the flow breaks and you rely on
  willpower alone.
- **When you plan a schedule**: In the early period at a new organization, you want to fill your schedule
  to earn trust. A full schedule breaks down when a single unexpected task appears. Do not fill the
  schedule completely. Build trust through the number of promises you keep.
- **When you stay overwhelmed**: Before treating it as a matter of mood, look at how full the schedule is.

## Ways to misuse it

- **Only drawing**: This is the case where you are busy drawing flows and do not act. If you cannot write
  in one line what you changed because of the drawing, you have only laid out arrows. The change is
  usually one of these: a path you cut, a limit you set, or a signal you separated.
- **Underrating immediate gains**: This is the case where you get absorbed in finding later effects and
  give up a clear gain. Let later effects count in the decision only when they are large enough to
  outweigh the present gain.
- **Seeing loops everywhere**: If there is no path through which the result comes back into later actions
  and changes the result again, turn this lens off. Whether you make the decision only once is not the
  test. A reward rule that you set once also keeps changing behavior after that.

## With other lenses

- **Ledger** (the lens that counts what is scarce and what it costs): Ledger is a calculation at one point
  in time. This lens looks at changes over time.
- **Limits** (the lens that pushes a value to 0 and to infinity): The Limits lens finds that waiting grows
  sharply as slack approaches 0, and this lens explains it.
- **Ergodicity** (the lens that first asks whether there is an irreversible loss): Falls into irreversible
  states often ride a flow that grows by itself.
- **Fence** (the lens that asks what an old practice protects): An old practice may be part of a flow
  that keeps the system stable. Check before you remove it.

The full list of all 13 lenses is in the [README](README.md).

## Usage records

Do not write actual usage records in this engine document. Follow the recording section of
`system/deep-pass.md` for the location and format of records. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Forrester, *Industrial Dynamics* · Meadows, *Thinking in Systems* · Queueing theory (Erlang, M/M/1) · Goodhart (1975) and Strathern's formulation · Senge's system archetypes.
