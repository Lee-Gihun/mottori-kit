<!-- source: ko/system/lenses/mirror.md sha256:486737f9bc5e9450c258d1502a4e1828b3def896e42100277d323495dc47be7a source-of-truth: ko -->
Korean: `ko/system/lenses/mirror.md`

# Mirror lens

> Question: **Do the records support this judgment I made about myself?**
>
> When to use: When a claim about yourself is about to be used as a basis for a judgment. This covers
> claims that put you down and claims that build you up. For an AI assistant, it also covers claims about
> its own work, such as "I verified it" or "it works". Once you have checked the records and changed the
> sentence, turn this lens off and go back to the original problem.
>
> What to leave behind: The claim rewritten as a sentence the records support. If there are no records,
> "unknown".

## Summary

To measure something you need a measuring tool. When you judge yourself, the measuring tool and the
thing measured are the same. So statements like "I am hopeless" or "I have always been like this" can
carry that day's mood and fatigue. We often demand checks for facts about the outside world, yet accept
claims about ourselves without checking. This lens demands the same check for claims about yourself.

## Example

You are writing a review of the quarter, and this sentence comes out first: "This quarter I only handled
incidents and got almost no feature work done." Drop the adjectives and look only at records that
already exist. These are the list of merged code changes, the incident response log, and the calendar.
Of 23 code changes, 14 were feature work. There were 5 incidents, and two of them took two days each.
The sentence the records support is "I shipped 14 feature changes and spent about four days on two large
incidents." The gap between the first sentence ("almost no") and the records (14) shows which way and how
far your current judgment is tilted. If there is a period with no records, write "that period has no
records, so it is unknown".

## Why it works

Stories about yourself contain parts made up after the fact. This is especially true of explanations of
"why I did that". When you make them up, your current mood, fatigue, and recent experiences weigh
heavily. So reports about yourself mix your actual state with your current state, and inside you there
is no way to separate the two. What can separate them is the records left outside. A record that holds
only dates and events is much less colored by that day's mood.

The direction of the tilt is not fixed to one per person. It differs by area. The same person can
understate their own progress and still trust their own judgment without checking. So do not harden a
result you checked in one area into a personality label such as "I am someone who sells myself short".
Check each area separately, and leave areas you have not checked as "unknown".

Records have errors too. When a meeting recording is transcribed, who said what can get switched, and an
owner can be written down wrong. If a conclusion depends on one line of a record, check the original
once more.

## How to use it

- **Treat what you say about yourself as the weakest evidence**: Treat claims about yourself, especially
  self-mockery and pessimism, as the weakest kind of evidence. Use them as evidence only after you check
  the records.
- **Look at records that hold only dates and events**: Records that already exist, such as a calendar,
  sent email, or code change history, are enough. You do not need to write new ones. Read them without
  adjectives and interpretation. With that record in front of you, ask "what sentence about the person
  in this record does the record support".
- **Check your current state first**: Before you judge, check three things. Did you sleep enough? Did
  something upset you badly recently? Do you have a stake in the outcome of this judgment? If any one
  applies, write one line on which way it would tilt the judgment, and add evidence from records or from
  other people's eyes. If you are in a state where your judgment will be badly clouded and the decision
  can wait, set a date to look again and postpone acting.
- **Put yourself in the analysis**: When you analyze an organization or a relationship you belong to,
  include yourself as an item. Write down how your presence and your mood change what you see. Also write
  down how your strengths change the other person's role. For example, if you put out a finished version
  early, a colleague gets pushed from co-creator to reviewer.
- **Write predictions down and check them**: Write down predictions such as "I don't think I can do
  this", then compare them with the results later. You can measure which way and how far your judgment
  tilts.
- **Check positive claims the same way**: "This method works", "I am strong at this kind of work", and
  "this failure was the tool's fault" go through the same check as self-mockery. First look at where the
  assessment came from. Check whether you made it yourself, or whether an AI or another person gave it to
  you.
- **Count how many times you corrected your judgment**: Over a set period, count together how many
  judgments you made whose outcome can be checked, how many of those outcomes you checked, and how many
  you corrected as "my judgment back then was wrong". If you had few chances to check, leave it as
  unknown. If some judgment's outcome missed and you did not correct it, or if you often put yourself
  down but your correction count is close to 0, you are not seeing the cases where your judgment is
  wrong.

## Where to use it

- **When a claim about yourself comes up** (the most common use): When something like "I am hopeless"
  comes up, stop and look at the records. Rewrite it as a sentence the records support, then go back to
  the original problem.
- **When you evaluate past work**: Do not decide whether it went well by feel. Decide by comparing it
  with the prediction you wrote down at the start.
- **When you guess how others see you**: Write down separately how much your anxiety changes that guess.
- **When you evaluate your own theory**: If everything seems to be explained by your theory, ask someone
  else to argue against it, to find out whether the theory is good or you just want it to be.

## Ways to misuse it

- **Looking only at yourself, over and over**: If you start looking with this lens at what you saw with
  this lens, it never ends. Once you have checked the records and changed the sentence, stop there.
- **Using records to punish yourself**: Use records to correct a tilted judgment. Do not use them to
  scold yourself.
- **Using it on others**: Do not use it to argue against what another person says about themselves by
  saying "show me the records". This lens is for the person who made the judgment to use on themselves.
  An AI assistant uses it in two cases. One is for the AI's own recommendations and conclusions. The other
  is for what the owner (the person who gave the AI assistant the work) says about themselves. In the
  second case, compare against records the owner has entrusted to it, and do not argue. Return the
  sentence the records support.
- **Checking only negative claims**: This is when you check only self-mockery and let positive claims and
  your own judgments pass. It looks like humble self-correction, but in fact it blocks the signals that
  would tell you your judgment is wrong. You can tell by recalling when you last checked a positive claim.
- **Recording a label someone else gave as fact**: This is when a personality label that another person
  or an AI attached after one or two cases gets written into memory or a rules file as if it were a
  checked result. That label tilts the next judgment in advance, and the tilted judgment is then used as
  evidence for the label.

## With other lenses

- **Before other lenses**: In a problem that involves a claim about yourself, go through this lens first
  and then use other lenses.
- **Incentive** (the lens that looks at the speaker's interest): Use the Incentive lens on what others
  say, and this lens on what you say.
- **Inversion** (the lens that starts by writing down the conditions for failure): Use this lens to check
  whether you did Inversion before or after deciding. If you did it after, it may be rationalization.

The full list of all 13 is in the [README](README.md).

## Usage records

Do not write actual usage records in this engine document. The location and format of records follow the records section of `system/deep-pass.md`. The default location is the instance's `_private/deep-pass/ledger.md`. Copy `templates/deep-pass-ledger.md` to use it.

## Sources

Schwarz & Clore (1983, mood enters judgment as if it were information) · Nisbett & Wilson (1977, reports on the reasons for one's own behavior can be made up after the fact) · Tetlock, *Superforecasting* (writing predictions down and checking them) · The Stoic evening review (Seneca, *De Ira* 3.36).
