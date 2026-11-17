<!-- source: README.ko.md sha256:be1353f29b15d0a108d77e2155dff272735239f58a7fc17c62d637346b926dea source-of-truth: ko -->
Korean: `README.ko.md`

# Thinking lenses

These are 13 question tools for stuck problems, design, and decisions. This file is a list for choosing
a lens. After you choose a lens, open that lens's document. How to use it, examples, and ways to misuse
it are in that document.

You can use this folder without the rest of the kit. Copy the whole folder, and add one line to your
agent instruction file (`AGENTS.md` or `CLAUDE.md`): "When dealing with stuck problems, design, or
decisions, read this README first." When you use it this way, write each lens's "What to leave behind"
in your own notes. The paths in the "Records" section below apply only if you installed the kit.

## How to use

1. Write one sentence each for the problem, what you originally wanted to get, and your current tentative
   conclusion.
2. Look at "When to use" in the table below, and choose one or two lenses that actually apply to this
   problem. If several apply, see "When two lenses seem to fit" below the table. If none apply, do not
   use any.
3. Open the document of the lens you chose, and actually do one of the items in "How to use it."
4. Write down the "What to leave behind" at the top of the document. If the conclusion from step 1 did
   not change, write that it did not change. Also check whether the conclusion reaches "what you
   originally wanted to get" from step 1.

## The 13 lenses

| Lens | When to use | What it asks | Document |
|---|---|---|---|
| **Ledger** (counting the cost) | You see only the gains and not the costs. You heard "both get better" | What is scarce here and must be shared, and who pays for the gain? | [ledger.md](ledger.md) |
| **Feynman** (working it out yourself) | You can explain it with terms but have never calculated it yourself | Do you know only the name, or how it works? Did you calculate a small example? | [feynman.md](feynman.md) |
| **Inversion** (working backward) | You will execute or send it soon. Only reasons for success have piled up | What would make it fail for certain? What is the cheapest way to check whether you are wrong? | [inversion.md](inversion.md) |
| **Limits** (pushing to the extremes) | You must decide a count, a size, or a range | What happens if you push the value to 0 and to infinity? From where does it behave differently? | [limits.md](limits.md) |
| **Structure mapping** (looking in other fields) | You are stuck and looking for answers only inside your own field. You want to check whether an idea is really new | Does another field have the same conditions that make this problem hard? | [isomorphism.md](isomorphism.md) |
| **Fence** (old practices) | You want to remove a practice whose reason you do not know. You are about to build a new structure | What was this practice preventing? Does that condition still exist? | [fence.md](fence.md) |
| **Marginal value** (the next unit) | You must split limited time or money across several places. You are unsure whether to continue or stop | Where would the next hour improve things the most? | [marginal.md](marginal.md) |
| **Jensen Huang** (choosing where to stand) | You decide where to stand in a company, a product, or a career | Is now the time to choose the game, or to do well in a game already chosen? | [jensen.md](jensen.md) |
| **Mirror** (judging yourself) | A judgment about yourself (for an AI, a judgment about its own work) is about to be used as evidence | Do the records support this judgment I made about myself? | [mirror.md](mirror.md) |
| **Incentive** (the speaker's interest) | The speaker gains from the conclusion. You are preparing a request or a proposal | Which conclusion benefits this person? Would they have said this even if it were not true? | [incentive.md](incentive.md) |
| **Ergodicity** (irreversible loss) | If it goes wrong, the chance to try again disappears. Someone says "once is fine" | If it goes wrong, is there another chance? What happens if you repeat it 100 times? | [ergodic.md](ergodic.md) |
| **Silence** (missing data) | You are looking only at successful cases, people who answered, and things you found. You are about to write "there is none" | What could never have entered this data in the first place? | [silence.md](silence.md) |
| **Feedback loop** (response and delay) | People or systems adapt to your action. Things return to how they were after you fix them | If you act, how does the other side respond? How late does that response come? | [feedback-loop.md](feedback-loop.md) |

### When two lenses seem to fit

- When you use data or a report as evidence, Ledger, Incentive, and Silence all apply. If you want to
  know the costs inside the result, use Ledger. If the speaker's interest is the concern, use Incentive.
  If how the data was collected is the concern, use Silence.
- Right before a decision, Inversion and Ergodicity both apply. If a wrong outcome could remove the
  chance to try again, use Ergodicity first. If not, use Inversion.
- When you decide an amount, Limits and Marginal value both apply. Deciding how large one value should be
  is Limits. Splitting a fixed amount across several places is Marginal value.

## Combinations

Use these only when they fit the problem. They are not a fixed order.

- When you restart a stuck problem: Ledger (what is scarce), Limits (push the value to the extremes),
  Inversion (conditions for failure)
- When you receive advice or evidence: Silence (how the data was filtered), Incentive (the speaker's
  interest), Feynman (calculate it again yourself)
- When you decide: Ergodicity (is it reversible), Marginal value (where to put it), Inversion (a failure
  report written in advance)
- When you change a system: Feedback loop (how it responds), Fence (what the existing practice
  protects), Ledger (cost)
- When you prepare for a conversation or meeting: Silence (turn what is not in the data into questions),
  Inversion (what not to say), Marginal value (spend time on what only the other person knows)
- When you check whether an idea is really new: all five steps of Structure mapping

In a problem that involves something the owner (the person who gave the agent the work) said about
themselves, use the Mirror lens first. This is not an example. It is a rule of the
[ritual rules](../rituals.md). It does not mean you may ignore experience the owner described or invent
preferences for them.

## Rules

- **Do not use lenses on every question.** There are four cases for using them: when a problem is stuck,
  when you design, when you decide, and when someone asks you to use them. Attaching lens names to a
  light question is misuse. You may use no lens, use only part of one, or use a perspective you made on
  the spot. Do not measure the scope of a review by whether all 13 were mentioned.
- **Close each lens you used with "What to leave behind."** The "What to leave behind" at the top of
  each document is the minimum evidence that you actually used that lens. If the conclusion did not
  change, write that it did not change. This rule came from the usage records of the original
  repository. In several lenses, lines that only wrote down a list, a flow, or missing items and then
  stopped kept repeating.
- **The size of the list is a choice made to keep it manageable.** Adding, merging, or removing a lens
  needs a decision based on the failure the lens is meant to prevent and on comparison results. Usage
  counts alone cannot show the effect. A rarely used lens may protect rare but important decisions. An
  often called lens may have changed nothing.
- **Candidates reviewed and not added.** Purpose (is what you are aiming at now the same as what you
  originally wanted to get) is not a lens. It went into steps 1 and 4 of "How to use." Reader (can the
  recipient read this and use it right away) was not added as a lens because it is a check that applies
  right before you deliver a result, more than while you think. Contrast (what was it compared with, and
  were the conditions of the comparison the same) is partly covered by the "think it through without it"
  method of the Inversion lens and by the Silence lens. In a small test in the original repository
  (2026-11), none of the three candidates earned a place as a separate lens.

## Related tools

- **Lenses** (the 13 in this folder): Question tools. They are a starting list collected to prevent
  repeated failures. They are not all possible perspectives, and they are not a list you must check in
  full.
- **Perspectives made on the spot**: Perspectives made new for each problem. They compete as candidates
  in the same place as the fixed lenses. There is one test for adopting one. Does it produce a different
  objection or a different answer from the perspectives already adopted?
- **[Deep pass](../deep-pass.md)**: A procedure that ties together evidence, perspectives, verdicts, and
  review when someone asks for depth.
- **Roles**: A seat that speaks from a specific position. Do not act out the private views of a real
  person. Use what that person actually said, with a source, or write down questions to ask that person.
- **[Debate](../debate/README.md)**: A procedure that has a different model attack the assumptions and
  evidence. A different model alone does not guarantee that the evidence is independent.
- **Cold reader**: A worker that tests whether something is understood when read without the earlier
  context. It may be a model of the same family. It does not replace a review of the content.

## Records

Leave usage records in the instance's `_private/deep-pass/ledger.md`, following the
[recording contract](../deep-pass.md#recording) and the [blank template](../../templates/deep-pass-ledger.md).
Write down both cases where the verdict changed and cases where it stayed the same. If you record only
the changes, you will read the lens's effect as larger than it is. Do not attach cases to tracked lens
files. A personal case does not become safe to publish just because the names were removed.

## How to read the lens documents

The "do this" and "do not do this" sentences in the lens documents are not written as laws that hold
everywhere. They are procedures that turn the failure the document describes into questions you can
check in a real problem. "Ways to misuse it" records the limits beyond which the procedure is used too
broadly. "Sources" records where the idea came from. The examples are there to show the method. Even if
your problem looks like an example on the surface, do not copy the example's conclusion. The numbers in
the examples show the structure of a calculation. Do not read them as estimates for any group or as
reference values that hold everywhere.

The kit owns this list. The list's rules and the lens definitions are material to reuse in many places.
Each instance's observations and review schedules are not.
