<!-- source: ko/system/lenses/feynman.md sha256:8cb5a5bdc09365b627f4ca3803c913ea737fed81b2a52ca02b59c005ff321b95 source-of-truth: ko -->
Korean: `ko/system/lenses/feynman.md`

# Feynman lens

> Question: **Do you only know the name, or do you know how it works? Did you calculate a small example
> yourself?**
>
> When to use: When an explanation goes on with only terms and analogies. When you are about to accept
> someone else's conclusion as evidence. When you are about to decide based on the feeling that you
> "understood."
>
> What to leave behind: A prediction written down in advance, the result of one case calculated by
> hand, and the place where you got stuck.

## Summary

Knowing the name of something is different from knowing how it works. The feeling of understanding can
appear just from recalling a sentence you memorized, so you cannot judge by that feeling alone. So you
do it again yourself. You explain it without technical terms, and you calculate the smallest case by
hand. If you get stuck somewhere along the way, your understanding reaches only up to that point.

## Example

You are about to change a training setting because you believe this claim: "If you compute in several
parts and combine them, the result is the same as one large computation." First, write down the
prediction "the results will be exactly the same." Then use a very small example with four numbers.
By hand, compute the value from two computations of two numbers each, combined, and the value from one
computation of all four numbers. When you do it, you find that the value doubles if you do not divide
by the number of parts when you combine. The prediction was wrong, and you now know the place to check
in the code (the place where the division happens).

There is also an example of explaining without terms. Try to explain attention without using that word,
like this. "Each position in a sentence sends a question to every position. It takes the answers that
come back and averages them, weighted by how similar each one is to its own question. The score for
similarity is divided by √d (d is the dimension of the vector) and then turned into probabilities." If
you cannot answer "why divide by √d" here, that is the place to study. (Answer: if you take the dot
product of two vectors whose components are independent with mean 0 and variance 1, its variance is d.
As d grows, the scores spread out widely, so the probability piles up on one entry. Then almost no
signal is left for learning.)

## Why it works

A technical term shortens a long idea, but it also hides the parts you did not understand. If you are
not allowed to use the term, you cannot hide them, so the parts you do not know show up. A small
calculation works for the same reason. A spoken explanation can stay plausible even when it is wrong.
In a calculation, if your thinking is wrong, the numbers do not match.

## How to use it

- **Explain without terms**: Explain it to someone from a neighboring field without using a single word
  from the field. If the explanation does not come, or if the listener cannot say it back in their own
  words, you do not know it yet.
- **Shrink it and calculate**: Reduce the problem to two or three items and one step, then run it
  yourself by hand or in code. If the problem has no numbers, follow one case step by step from input
  to result. A step that does not connect is a place you do not know.
- **Write the prediction first**: Before you calculate, write down the result you expect. After the
  calculation, compare the two. If they are the same, your thinking has been confirmed once. If they
  differ, either your thinking or your calculation is wrong, so find which one. If you do not write the
  prediction down, you will look at the result and feel "I knew it," and the check loses its meaning.
- **Answer the follow-up questions**: Think of the chain of questions that someone seeing this for the
  first time would ask, up to the third question. See whether you can answer that far.

## Where to use it

- **When you adopt a new method**: Do one core calculation yourself at a small size. Use the numbers you
  calculated as evidence, not the figures in the paper.
- **When you accept a claim from a paper**: Derive one core claim again from the authors' equations. If
  the derivation does not work, trust the claim that much less.
- **When you give reasons for a decision**: Explain "why this choice is good" without industry terms. If
  all that is left are sentences you heard from others, such as "because the market is big," the
  decision is someone else's conclusion that you copied.
- **When you check what you learned**: A day later, write what you felt you learned on a blank sheet of
  paper. Only the part you can write is what you actually learned.
- **When you pass it on to others**: In a talk or a document, write what a thing does instead of listing
  field names. It is enough if a first-time listener can say it back in their own words within 20
  seconds.

## Ways to misuse it

- **Listing only analogies**: If the talk is fluent but made entirely of analogies, it is not evidence
  of understanding. A number has to come out, or one case followed to the end.
- **Trusting the small example too much**: Something that was right in a small example can be wrong at a
  larger scale. Also, numbers that match inside an example you made only mean that your thinking has no
  contradiction. They do not mean it matches reality. Mark any step you did not measure yourself as
  "not checked."
- **Trying to redo everything**: There is not enough time to derive everything yourself. Choose only the
  claims that a decision depends on.

## With other lenses

- **Marginal value** (the lens that asks where to spend the next unit): Use the Marginal value lens to
  decide how deep to check.
- **Mirror** (the lens that compares judgments about yourself against records): The feeling "I
  understood" is a report about yourself, so it is weak evidence. Use only the results of redoing it
  yourself as evidence.
- **Structure mapping** (the lens that looks for the same problem in another field): A hypothesis that
  came from an analogy can be trusted only after you derive it again with this lens.
- **Limits** (the lens that pushes a value to zero and to infinity): Use the Limits lens to see whether
  something that was right in a small example stays right as the scale grows.

The full list of all 13 lenses is in the [README](README.md).

## Usage records

Do not write actual usage records in this engine document. The location and format of records follow
the records section of `system/deep-pass.md`. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Feynman, *Surely You're Joking, Mr. Feynman!* (the chapter on physics education in Brazil) · "What I
cannot create, I do not understand" · The tradition of learning by building things yourself from the
ground up.
