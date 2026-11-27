# Fence lens

> Question: **What was this practice protecting against? Does that condition still exist?**
>
> When to use: When you want to remove or skip a practice, piece of code, or rule whose reason you do
> not know. In the other direction, when "we have always done it this way" is the only reason given.
> When you are about to build a new structure.
>
> What to leave behind: The failure this practice was preventing, whether that condition still exists,
> and a verdict (keep, keep only part, remove). If you removed it, the condition for bringing it back.

## Summary

There is a fence in the middle of a field, and nobody knows why it is there. One person says, "It is
useless, so let us take it down." The writer Chesterton answers like this. If you do not know what it
is for, do not take it down. Go and find out why it was built. After that, if you still want to take
it down, take it down. A practice that has lasted a long time has lasted while someone paid the cost of
keeping it. Do not conclude that there is no reason just because you cannot see one. The reason may
simply never have been written down.

## Example

There is a one-hour metrics review meeting every Monday. Since a dashboard appeared where anyone can see
the metrics at any time, the meeting looks useless, and you want to cancel it. Before cancelling it,
find the person who decides to keep this meeting even though it costs ten people an hour each. It was
the head of the business unit. What he got from the meeting was not the numbers. It was this: when a
strange number appeared, several teams looked at it together on the same day and decided who would own
it. The dashboard shows the numbers but does not assign owners, so that condition still exists. So you
cut the meeting to 15 minutes and keep only "numbers that changed a lot from last week, and assigning an
owner." You also write down a condition: "If two teams investigate the same problem separately more
than twice a month, go back to the one-hour meeting."

The same holds for code. A configuration file has a timeout of 30 seconds, and nobody knows why. Before
deleting it, you search the change history and find an outage record from three years ago. The value
was added because an external API sometimes responded slowly. If you still use that API, leave the value
as it is. If only some calls use it, keep the value only for those calls. If you no longer use it,
delete the value with a comment that says "restore this if we start using it again."

## Why it works

A practice that has lasted a long time has survived many chances to disappear. If it survived while
someone paid to keep it, it may have been preventing something or earning something to that degree.
Practices often hold past failures that nobody recorded. If you remove a practice without finding them
out, you go through the same failure again. This is not a lens for protecting old things. It says:
decide after you know what the practice was protecting.

## How to use it

- **Find the reason before removing it**: First find out why it was made. If you decide to remove it,
  also write down the condition "if this happens, bring it back." Then you can reverse the removal if
  it was a mistake.
- **Look at the code history**: When you meet code that looks strange, search its change history before
  you change it. It may exist because of an exceptional case that you have not run into yet.
- **See who pays the cost**: Write down separately the person who actually spends the time and money,
  the person who decides to keep the practice, and the person who benefits. These are often not the
  same person. The real function of a practice is easiest to find in what the person who decides to
  keep it gets out of it. But the fact that it benefits one person does not by itself reveal the
  function of the whole practice.
- **See whether the condition is gone**: Check whether the condition that made the practice necessary
  still exists. If the condition is gone, you can remove the practice. The practice of filtering papers
  by reading only the abstract started when reading one paper took a lot of time. If a language model
  can now read the full text for you and that cost has dropped a lot, the reason to keep the practice
  has also shrunk.
- **Keep only part**: Besides keep and remove, there is a third verdict. Keep only the part that still
  protects against something and remove the rest. Or leave the practice as it is and open one way
  around it for the cases that need it. In practice, this verdict comes up most often.
- **Look before building something new**: When you are about to build a new structure, first look for
  a practice that already does that job.

## Where to use it

- **When you clean up an old system**: Before removing a step that looks unnecessary, remove it in a
  test environment and see whether the outage it was preventing happens again. If it does not, work out
  whether the condition is gone or whether you identified the wrong outage.
- **When you read a claim that overturns the accepted view**: First find the data that the accepted view
  explained, and see whether the new claim also explains that data. If it does not, it is hard to say
  that the accepted view has been overturned.
- **When you propose changing a rule or metric in an organization**: First find out what it was
  protecting. Then bring it up as the question "What did this protect?" instead of the proposal "Let us
  remove it."
- **When you drop an old habit**: Write down what the habit was protecting. Drop it together with the
  condition "if this happens again, bring it back."

## Ways to misuse it

- **Keeping everything**: Keeping every practice is not using this lens. The question to ask is "does
  it still protect against something now?" The fact that it used to is not a reason to keep it. In the
  other direction, confirming that a practice protects something does not make it untouchable. What you
  confirmed becomes a condition that the new design must meet.
- **Being strict only with other people's practices**: You examine practices that others made strictly
  and look at practices you made loosely.
- **Treating survival as proof that it is right**: A practice may have survived for reasons other than
  its function. It may be the wish of a powerful person, or chance. So also ask what made this practice
  survive. In the other direction, the diagnosis "it is just politics" is also not a reason to remove a
  practice until you confirm that it protects nothing.

## With other lenses

- **Silence** (the lens that looks for what is missing from the data): Fence assumes "what survived may
  have a reason." Silence suspects "you are looking only at what survived." When you use them together,
  first use Silence to see what is missing, then use Fence to find the reason for what remains.
- **Feedback loop** (the lens that looks at how others react to your action): A practice can be part of
  a mechanism that keeps a system stable. If you remove such a practice, the system becomes unstable.
- **Inversion** (the lens that starts by writing down the conditions for failure): Before you decide to
  remove something, ask "what fails if we remove it?"

The full list of all 13 lenses is in [README](SKILL.md).

## Usage records

Do not write usage records in this file. For their location and format, see the "Records" section of
[guide.md](guide.md).

## Sources

Chesterton, *The Thing* (1929) "The Drift from Domesticity" · Chesterton's fence as used in systems
operations · Taleb's Lindy effect.
