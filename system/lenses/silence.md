<!-- source: silence.ko.md sha256:97bbac1e8d7954f1dabc25721f67aca6cd3c0bf93230e0dd5fabd97d68fee49c source-of-truth: ko -->
Korean: `silence.ko.md`

# Silence lens

> Question: **What could never have entered this data in the first place?**
>
> When to use: When you are about to draw a conclusion from cases, reviews, data, or search results. When
> you are about to write "there is none." When you are guessing what people who are not present want.
>
> What to leave behind: One sentence on how this data was filtered before it reached you. A list of the
> missing things your conclusion depends on. One action for each missing thing (a question to ask, a
> decision with a condition attached until the answer comes, or a default that is less affected by what
> is missing).

## Summary

All data reaches you after something has filtered it. There is a well-known story. In World War II,
people looked at the bullet holes on bombers that came back and planned to add armor plates at those
spots. The statistician Wald is said to have argued the opposite. The spots without bullet holes are the
dangerous spots. Planes hit there did not come back, so they are not in the data. This is a case where
you can read all the evidence in front of you correctly and still be wrong. That is why there is a lens
that counts what is absent.

## Example

In a survey of people who canceled a service, "too expensive" came first at 38%. So you are about to
propose a price cut. Before you propose it, write one sentence on how these answers reached you. "Only
people who came to the cancel button themselves and did not skip the survey remain." Then you can see
the people who could not enter this data. People whose card expired so the service ended on its own.
People who keep paying without using it. People who skipped the survey and canceled. The conclusion to
cut prices assumes that these people also left for the same reason. So you attach a condition to the
conclusion. First check the share of people who answered the survey, and compare the usage records of
people who left without answering.

There is also a more common example. The statement "successful founders all dropped out of college"
reached you through this process. They succeeded, so articles were written, and you saw those articles.
People who dropped out and failed cannot enter this process.

## Why it works

Surviving, answering, being published, and being recorded are all filtering processes. If one kind of
case has a low chance of staying in the data, that kind looks rarer than it really is. If you ignore
that chance, your estimate leans to one side. The problem is that this chance is not in the data. You
cannot find it however carefully you look at the data. You can learn it only by asking, from outside the
data, how the data was made.

## How to use it

- **Write down the filtering process**: When you look at data, write in one sentence "What brought this
  to me?"
- **Look for failures first**: Before you listen to a success story, first look for cases where people did
  the same thing and failed.
- **Make a list of what you did not see**: Each time you collect data, put a list of "what I did not see"
  in the result. Then decide one action for each missing thing. Write one question to ask someone, or
  attach a condition to the decision until the answer comes, or choose a default that changes little
  whatever the missing thing turns out to be.
- **Read absence as a signal**: Do not leave a missing answer, a missing mention, or missing data as a
  plain blank. Write down what "should be there but is not," such as a party that does not answer, a
  table left out of a report, or a period skipped in a presentation.
- **How to write "there is none"**: Instead of writing "there is none," write "I searched this range,
  where, with what, and up to when, and did not find it." The short form is
  `Not found in corpus C · query Q · period T`. If a conclusion depends on the fact that something is absent, search one more
  source of a different kind where that thing could appear. If you cannot search more, weaken the claim
  that you "looked at everything." (This item came from real mistakes. In one task, failing to find
  something in a narrow range was written as "absent everywhere" several times.)
- **Be careful when you search outside**: If the tool you use to search more is an external service, the
  content of your search terms leaves your machine. If you cannot rewrite it in words that are safe to
  make public, do not search, and leave it as a missing item.
- **When old things look good**: One big reason old things look good is that the bad ones have
  disappeared. Remember this when you hear praise for old things.

## Where to use it

- **When you hear "I did X and Y happened"**: Ask how many people did X and did not get Y, and whether
  those people had any way to enter this data. If they did not, trust the statement less.
- **When you analyze accepted applicants or success cases**: The analysis means nothing if you do not
  know how the applicants were filtered and gathered. "Who did not apply at all" can be more important
  information.
- **When you read research results**: Reported scores are the scores of experiments that went well.
  Read them with the fact in mind that experiments that went badly do not become papers.
- **When you look back on past events**: What comes to mind is also filtered. Events with strong
  emotions stay in memory. Looking at a record that lists only dates and events reduces this bias.
- **When you design or plan**: Find who, among the people who will use the result, has no voice in the
  data you have. Do not fill in what that person wants by guessing. Turn it into a question to ask. As a
  design becomes more detailed, you get the feeling that "everything has been considered," and it becomes
  easy to forget what you never asked in the first place.

## Ways to misuse it

- **Calling only unfavorable evidence a "biased sample"**: This is picking only the evidence against you
  and throwing it out as a biased sample. It is justified only when you state the filtering process
  concretely and predict which way it pushed the result. Throwing evidence out without doing this is
  avoidance.
- **Seeing hidden things everywhere**: If you assume every dataset is missing something large, you can
  infer nothing. What matters is how much the missing thing shakes the conclusion, more than the fact
  that something is missing. If the conclusion does not depend on it, write one line and move on.
- **Being lenient with your own data**: You are lenient only about what is missing from data you
  collected yourself.
- **Making the list and stopping there**: This is writing down the missing things and doing nothing. If
  the same item appears on the list a second time, the problem is not too little looking. You have not
  decided what to do about it. If the same list is attached every time, that list has already become a
  formality.

## With other lenses

- **Fence** (the lens that asks what an old practice protects): Fence holds that "what remains may have
  a reason." This lens suspects that "you are looking only at what remains." When you use them together,
  first use this lens to see what is missing, then use Fence to find the reason for what remains.
- **Incentive** (the lens that looks at the speaker's interest): If you know who has a reason to produce
  which data and hide which data, you can guess what is missing.
- **Inversion** (the lens that starts by writing down the conditions for failure): Inversion finds the
  gaps in my plan. This lens finds the gaps in my evidence.
- **Mirror** (the lens that compares judgments about yourself with records): The "record that lists only
  dates and events," used when looking back on past events, is described in detail in the Mirror lens.

The full list of all 13 lenses is in the [README](README.md).

## Usage records

Do not write actual usage records in this engine document. Follow the recording section of
`system/deep-pass.md` for the location and format of records. The default location is the instance's
`_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Wald, bomber analysis (SRG, 1943) · Taleb, *The Black Swan* (silent evidence) · Literature on publication bias (funnel plot).
