# Ledger lens

> Question: **What is scarce here and has to be shared? If someone gains, who pays for it?**
>
> When to use: When you hear a proposal that says "both get better." When you get a report that one
> number went up. When you compare options with a single total score.
>
> What to leave behind: An account table. The name of what is scarce, who pays in each account, and
> "unmeasured" for any account you could not measure.

## Summary

Every situation has something whose amount is fixed, so it has to be shared. Time, budget, people's
attention, and space on a screen are examples. This document calls that thing the "currency." Once you
decide what the currency is, you can rewrite any claim as "who pays how much and who receives how
much." If you write it out and see only a receiver and no payer, first look for a cost you left out.

## Example

A team reports that a new search model scores 3 points higher in accuracy than the old model. Write
down side by side what went into each model: training time, the number of attempts with different
settings, model size, and response speed. Once it is written down, you see that the new model was tuned
by changing its settings twenty times. The old model used the default settings. The new model is also
twice as large, so its responses are that much slower. In that case, what the report actually says may
be "spending more makes it better." Match what went into both models and compare again. If the new
model still leads, then you have grounds to say the new model is better.

## Why it works

When the amount of something is fixed, spending more on one side means spending less on the other. So
an explanation that says more was spent on both sides has a calculation error somewhere. It does happen
that cutting waste makes both sides better with the same amount. In that case you must be able to write
down what waste was cut. A story is easy to make plausible, but it is hard to make this calculation
balance as well. So when you write down the items one by one, the places with mistakes or hidden costs
show up.

## How to use it

- **Decide the currency**: First decide what has a fixed amount in this situation. Time, budget,
  attention, memory, and the compute used for training are common candidates. The unit you notice
  first is often not the currency. For example, you may be working hard to reduce the number of unread
  emails, while the thing that is actually scarce is a person's attention.
- **Suspect free gains**: When you hear "both get better," look for who pays. If you cannot find a
  payer, it is one of three things. The way of sharing changed, waste was reduced, or a cost was hidden.
  Check the hidden cost first.
- **Use the same unit**: Convert what you put in and what you got into the same unit before you compare.
  Something without a unit, such as "we worked hard," cannot be compared.
- **Find where the cost moved**: If a cost seems to have disappeared, first check whether it moved to
  another person or to a later time.
- **Split the accounts**: Do not merge gains and costs into one average or one total score. Write each
  item separately. If you merge them, a large loss in one item is hidden by the gains in another item.
  Among the separate items, also include things whose amount is not fixed (trust, learning, fun).

## Where to use it

- **When you compare experiment results**: When you get a report that a score went up, ask what was
  spent more. Data, compute, and the number of tuning rounds are the candidates. A budget that is not
  written in the report often explains the result.
- **When you choose between options**: Write down time, learning speed, room to choose a different path
  later, and trust separately, then compare.
- **When you are tired all the time**: Write down where attention comes in and where it goes out. It
  comes in from sleep, exercise, and focused time. It goes out through switching between tasks, things
  you put off without deciding, and repeated worry.

## Ways to misuse it

- **Asking "who paid" about things whose amount is not fixed**: With time and attention, when one side
  grows the other side shrinks. Information, trust, and relationships can be newly created, and many
  people can hold them at once. For these, "both get better" can be true. Do not be suspicious only
  because there is no payer.
- **Writing down only what you can measure**: If you leave out items that are hard to measure, such as
  relationships, reputation, and fun, the missing items get damaged while you grow the written items.
  Write "unmeasured" for an item you could not measure, and keep it in the table.
- **Pretending to be precise**: If you write a value you know only roughly to several decimal places,
  the table looks more reliable than it is.
- **Treating the split as fact**: Splitting items makes conflicting claims look organized, so it feels
  as if the explanation is finished. But the split is a frame you chose. Until you check that things
  really behave that way, keep it as a hypothesis.

## With other lenses

- **Limits** (the lens that pushes a value to zero and to infinity): After you set up items with the
  Ledger lens, check each item with the Limits lens.
- **Feedback loop** (the lens that looks at how the other side reacts to your action): A ledger is a
  calculation at one point in time. Use the Feedback loop lens for the parts that affect each other
  over time.
- **Silence** (the lens that looks for what is missing from the data): The items in the ledger may not
  be all of them. Use the Silence lens to find the missing items.

The full list of all 13 lenses is in the [README](SKILL.md).

## Usage records

Do not write usage records in this file. For their location and format, see the "Records" section of
[guide.md](guide.md).

## Sources

The correspondence between conservation laws and symmetries (Noether) · Munger (suspicion of accounting
numbers that hide costs) · Jaynes, *Probability Theory*, preface.
