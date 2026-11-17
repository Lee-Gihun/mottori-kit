<!-- source: isomorphism.ko.md sha256:7d9d255a5dd5bbc3a77f92caa7435d5ca0d5689b20a13e460ab81157528ee869 source-of-truth: ko -->
Korean: `isomorphism.ko.md`

# Structure mapping lens

> Question: **Is there a problem in another field with the same conditions that make this problem hard?**
>
> When to use: When you are stuck on a design or on a problem with no fixed answer, especially when
> you are looking for answers only inside your own field. When a discussion is about to end with
> "there is no right answer." When you check whether an idea is really new.
>
> What to leave behind: At most two mappings that survived. For each mapping, what maps to what,
> where it does not fit, and what you will therefore do in your own problem.

## Summary

Remove the words of the field from a problem, and the conditions that make the problem hard remain.
Usually these are linked conditions: when you satisfy one, another one breaks. A problem with the same
conditions has often been solved already in another field, or there is a record of failed attempts.
Analogy is a way to bring that record over. But what you get from an analogy is only a hypothesis. You
must check separately, by calculation or by measurement, whether it holds.

## Example

An online marketplace needs more sellers. If it loosens the entry standard, quality complaints rise. If
it tightens the standard, there are not enough sellers. Written without the words of the field, this
becomes: "If you widen the door, quality drops. If you narrow it to protect quality, the numbers fall
short." Hiring has dealt with the same condition through the probation period. The employer does not
decide on the interview alone. The person works first, and after a set period the employer looks at
the results and makes the hire permanent. In the mapping, the seller is the applicant and the entry
review is the interview. The move to bring over is this: "Do not decide only between approval and
rejection. Give a temporary entry with limited exposure, and switch it to a full entry when the seller
meets a performance standard." Also write down where the mapping does not fit. A probationary employee
works for only one company. A seller can be on other marketplaces at the same time and can leave at
any moment. So you do not bring over the part about making the temporary period long.

## Why it works

People get stuck more at recalling an analogy than at applying it. In one experiment, when people were
given no story to use as a reference, about 10% solved the problem. When they read a story first but
got no hint, about 30% solved it. When they got the hint "try using the earlier story," the figure
rose to about 75%. (These are the figures a textbook gives as a summary of Gick & Holyoak 1980. They
vary between experiments.) The answer was already in their heads, but they could not retrieve it. When
the surface looks different, people are poor at recalling the same structure. A language model that has
read text from many fields can serve as an index that covers this weakness. It is only an index, so do
the final check in the original literature.

## How to use it (five steps)

1. **Write down the conditions that make it hard**: Write in one sentence "the linked conditions that
   make this problem hard." If, when you rewrite the problem in later steps, you abstract so far that
   these conditions disappear, you have gone too far.
2. **Rewrite it in several frames without field words**: Do not rewrite it in only one frame. Write it
   in two or three. Change the frame: is it a problem of making something as large as possible
   (optimization), of keeping something steady (control), of who competes with whom (game), or of who
   buys and sells what (market)? For each frame, check that the conditions from step 1 still remain.
3. **Scan many fields**: For each rewrite, look for fields that may have a similar problem. Go through
   natural science, engineering, social institutions and law, biology and evolution, the military, and
   practical work in history, in turn. When you look for a solution, write down the three fields that
   come to mind first and search outside them. This is to reach fields that do not come to mind easily.
   When you check whether something is new, do the opposite and start with nearby fields. Earlier work
   is likely to be nearby. When nothing more comes to mind, ask a language model and name the field.
   For example: "Find cases in biology that dealt with the same conditions as these."
4. **Weigh the candidates**: For each candidate, write three things: what maps to what, where it does
   not fit, and the move to bring over ("if this analogy holds, here is what I will concretely do in my
   problem"). Drop any candidate for which you cannot write a move. For each remaining candidate, ask:
   "Does this connection change my next action (experiment, design, question)?" If it only points again
   at something you are already doing, write "nothing changed" and remove it. A general structure that
   appears in every field, such as "summarizing loses something," does not count as a connection.
5. **Try to refute and cut down**: Reread the remaining candidates with fresh eyes, trying to show that
   they are wrong. Cut what survives to at most two. Attach search terms for finding the original
   literature, and then read that literature.

Start light. Do step 1, one group of fields in step 3, and step 4. If it looks useful, do all five
steps. After the five steps, you can also ask the reverse question: does my solution solve an unsolved
problem in another field?

## Where to use it

- **When a design is stuck**: As in the example above, bring over solutions and failure records from a
  field that has already dealt with the same conditions. As another example, suppose you combine the
  verdicts of several grading models, and they are still wrong together in the same places. You can map
  this to Condorcet's jury theorem. The theorem says that a majority vote becomes accurate under the
  assumption that each juror is right more than half the time and that the jurors are independent. The
  move to bring over here is to reduce the correlation between the models instead of adding more
  grading models. This conclusion came out because, in that problem, the independence assumption was
  confirmed to be broken. Do not carry it unchanged to another problem that has several judges. First
  write down what the jurors are in your problem, what the right answer is, and whether the
  independence assumption holds.
- **When you check a claim that something is "new"**: Use the method in step 3 to scan from nearby
  fields first and find earlier work. Once you look, you can tell how new it really is.
- **When a choice is split**: Rewrite the same situation in two different frames. If the two frames
  point to different choices, the reason they differ is the question you actually need to answer.

## Ways to misuse it

- **Everything leads back to my theory**: If every case you look at ends with "my theory explains this
  too," be suspicious. It may be because the theory holds widely. It may also be because the theory is
  growing in a direction where it can never be shown to be wrong. If you cannot answer "what would have
  to be different if this theory were wrong," it is the second case.
- **The fun of finding connections pulls you along**: The pleasure of finding a connection has nothing
  to do with whether the connection is useful. Filter with the question from step 4, "does it change
  the next action?"
- **You do not write down where it does not fit**: The parts that do not fit decide what you bring over
  and what you leave behind. Bring over the structure. Leave behind the parts that do not fit (numbers,
  formulas, properties found only in that field). A remark that you could attach to any analogy, such
  as "people are not machines," separates nothing, so it does not count as writing something down.
- **You do it alone**: Useful analogies often come to mind when someone argues against you. Bring in a
  partner who will argue back.
- **You get stuck in one way of stating it**: Even if you rewrite the problem in several frames, you
  cannot see what is completely missing from the way you first wrote the problem. It helps to show the
  sentence that states the problem to another person first.

## With other lenses

- **Feynman** (the lens that checks understanding by calculating it yourself): Check a hypothesis that
  came from an analogy by deriving it again with the Feynman lens.
- **Ledger** (the lens that tracks what is scarce and what it costs): Use it to see whether the mapped
  items really correspond. Check whether something that is fixed in amount on one side is also fixed on
  the other side.
- **Mirror** (the lens that compares judgments about yourself with the record): Use it to see whether
  you welcome this connection because it is useful or because it makes your theory larger.

The full list of all 13 lenses is in [README](README.md).

## Usage records

Do not write actual usage records in this engine document. The location and format of records follow
the records section of `system/deep-pass.md`. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Gick & Holyoak (1980, 1983) · Holyoak & Koh (1987, surface similarity and retrieval) · Polya (analogy) · Hofstadter, *Surfaces and Essences* · Condorcet's jury theorem (1785).
