<!-- source: ko/system/lenses/ergodic.md sha256:8fc84bda2d5fc23efb2a1902f59a877cd484ff1f4840c0f1dbf310e3260220de source-of-truth: ko -->
Korean: `ko/system/lenses/ergodic.md`

# Ergodicity lens

> Question: **If this goes wrong, do I get another chance? If I repeat this 100 times, what happens to me?**
>
> When to use: When someone says "the expected value is good" or "once is fine." When you face a
> decision and it is not clear whether you can reverse it. If the decision is reversible, make it
> quickly and turn this lens off.
>
> What to leave behind: Whether the decision is reversible or not, and one line on the case in which it
> becomes irreversible. If the decision is irreversible, a way to delay it or split it.

## Summary

When people say "profitable on average," there are two kinds of average. One is the average when ten
thousand identical people each do it once at the same time. The other is the average when one person
does it many times in a row. These two averages differ when there is a state you cannot leave once you
enter it, such as bankruptcy, death, or lost trust. The usual expected value is the first average. But a
person lives one life, one step after another. So the average that matters to me is the second one.
(In mathematics, the property that makes the two averages equal is called "ergodicity." The lens takes
its name from that.)

## Example

You decided to change the name and logo of a service. You must decide whether to change everything at
once. Split the changes into those you can reverse and those you cannot. The colors and fonts of the app
and web screens can be reversed by deploying again. A large print order, new signs, a trademark
registration, and a press announcement are hard to reverse. So you change the screens this week and
watch the response for 2 to 3 weeks. You delay the printing and the signs until after that, and first
print a small test batch.

There is also an example with numbers. Take a bet on a coin toss. Heads multiplies your money by 1.5.
Tails multiplies it by 0.6. If ten thousand people each play once, the average is 1.05 times, a 5% gain.
If one person keeps playing, the result is different. Over two tosses with one heads and one tails, you
get 1.5 × 0.6 = 0.9 times, which is a 10% loss. That is a loss of about 5% per toss on average. The
expected value is a gain, but if you keep playing, your money approaches 0. Russian roulette is a more
extreme case. With one bullet in a six-shot revolver, the chance of survival is five in six. If the
reward is large, the expected value of one round looks good. But if you repeat it, the chance of
survival approaches 0. It is a bet you cannot repeat, whatever the reward.

## Why it works

Wealth grows and shrinks in proportion to what you already have. It moves by multiplication, not by
addition. When something moves by multiplication and reaches 0 once, anything you multiply after that
still gives 0. Reputation and health are similar. If you lose a lot, the chances to gain later shrink.
When you repeat things like this, you must look at the result of many multiplications converted to a
per-round value (the geometric mean). In the coin bet above, the ordinary average is 1.05, but this value
is √(1.5 × 0.6) ≈ 0.95.

## How to use it

- **Ask whether there is another chance**: When you decide, first ask "If the worst result happens, do I
  still get another chance?" If not, do not do it because "the expected value is good," even when the
  chance of the worst result is low.
- **Sort decisions by whether they are reversible**: Make reversible decisions quickly. Try it, and if it
  is wrong, reverse it. Only irreversible decisions need careful analysis. Many decisions are reversible
  but get treated as irreversible, and this slows them down.
- **Delay or split irreversible decisions**: Delay until the needed information arrives, and start with
  the reversible early part. Ways to do this include a trial run, paying only a deposit, and confirming
  in stages.
- **When unsure, choose the option you can fix later**: For example, when you decide what information to
  publish, something left out can be added later, but something published cannot be taken back. So when
  unsure, leave it unpublished.
- **Calculate how much builds up with repetition**: When someone says "once is fine," convert it to how
  many times a year it happens and calculate. If the chance is the same p each time and does not depend
  on earlier results, the chance that it happens at least once in n tries is 1 − (1 − p)ⁿ. A 1% event
  done every week gives about 41% in a year. A 5% event done every month gives about 46% in a year.
  Events that become more likely after they happen once do not fit this formula, so analyze them
  separately.
- **Take attempts with small losses and large gains**: Some attempts have a single refusal as the worst
  result and no upper limit on the good result. Contacting someone, applying, asking for a favor, and
  showing your work are like this. Do not delay these attempts.
- **Make it safe to stop in the middle**: Design long tasks so that an interruption does not force you to
  start over. Save progress to files and add checkpoints often.

## Where to use it

- **When you compare options**: If the option with the largest expected gain carries an irreversible
  risk, choose an option without that risk.
- **When you design a long task**: Ask "If it stops here, where do I restart?" If any stage has the
  answer "from the beginning," fix the design.
- **Matters of health and reputation**: Cutting sleep, an unreasonable deadline, and a statement that
  puts your credibility at stake can each look minor once, but they build up. Set an upper limit on how
  much you can stake at one time.
- **When "just this once" keeps repeating**: Convert it to how many times a year and judge again.

## Ways to misuse it

- **Treating every loss like bankruptcy**: Then you can do nothing. Define irreversible states narrowly.
  Include only losses that take several years to recover from or cannot be recovered. Do not include
  embarrassment, failure, or rejection. But when a loss can be recovered by itself and still blocks the
  path to the next chance, treat it as close to an irreversible state. Losing trust and therefore not
  getting the next chance is such a case.
- **Treating a reversible decision as irreversible**: Changing jobs or the city you live in is usually
  reversible. If you think it is irreversible, you become too cautious. So check that you sorted the
  decision correctly.
- **Using the repetition calculation on a one-time decision**: For a decision that does not repeat, the
  "if you do it many times" calculation does not apply directly. For such a decision, ask only "Is there
  another chance?"
- **Getting wrong what repeats**: Consider the judgment "I can come back to this city later, so let us
  save money this time." What can come back is the city. The people you came with now and this period of
  life will not come back. First write down what repeats and what happens only once.

## With other lenses

- **Marginal value** (the lens that asks where to spend the next unit): Even if the next unit has the
  largest effect, do not choose it if it carries a risk of becoming irreversible. This lens comes first.
- **Inversion** (the lens that starts by writing down the conditions for failure): Use this lens to pick
  out the irreversible ones among the failure conditions that inversion found.
- **Feedback loop** (the lens that looks at how others respond to my action): Falls into irreversible
  states often happen through a flow that grows by itself. If you notice that flow early, you can stop it
  in advance.

The full list of all 13 lenses is in the [README](README.md).

## Usage records

Do not write actual usage records in this engine document. Follow the recording section of
`system/deep-pass.md` for the location and format of records. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Kelly (1956) · Ole Peters, ergodicity economics · Taleb, *Antifragile* and *Skin in the Game* (the logic of risk taking) · Bezos, shareholder letters (reversible and irreversible decisions).
