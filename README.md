<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/hero-dark.svg">
    <img src=".github/assets/hero-light.svg" width="100%" alt="Over 21 days one conversation moves between a checkout bug at work, a novel&#x27;s fourth chapter and an apartment hunt, and is compacted four times. Under it each topic has its own file on disk, a line no compaction cuts: written down when the topic first comes up, handed back whenever the talk returns to it.">
  </picture>
</p>

# mottori-kit

**A workspace for weeks of work with one AI agent, for Claude Code, Codex and Antigravity.**

It is for long-running work that lives in documents: decisions, research, writing, plans. It uses more tokens so
that you spend less of your attention on:

- explaining on Thursday what you decided on Monday
- finding the dead link in the document the agent called finished
- being the one who asks "what would make this fail?"
- rewriting the email it drafted for you

If something has to happen every time, a hook or a check should do it, not a rule that someone has to remember,
whether that someone is you or the agent. I tried written rules first. In five months of my own sessions there
were thirteen kinds of mistake the agent already had a rule against, such as handing over a document it had not
reopened, and twelve of them kept happening. So the kit loads only seven rules. The rest is files that hold what
you decided, hooks that put it back in front of the agent, and checks that run when work is handed over.

It runs on your machine, with no server, no database and no sync. Your notes stay on your disk, and only what your
agent reads in a session goes to its model provider.

[Setup](SETUP.md) · [Manual](MANUAL.md) · [The seven rules](AGENTS.md) ·
[Design decisions](system/specs/kit-decisions.md) · [Changelog](CHANGELOG.md)

## Try it

Clone it as a folder of its own, next to your code repositories:

```bash
git clone https://github.com/Lee-Gihun/mottori-kit ~/work
cd ~/work
```

Open Claude Code, Codex or Antigravity there and say:

> Read SETUP.md and set up this folder. Show me what doctor, the kit's health check, says when you finish.

Then tell the agent something you have decided. It writes one line:

```bash
python3 tools/now.py log "[launch/decision] Beta opens Dec 2 with two pricing tiers."
```

Every new session now starts with your recent decisions in front of the agent, and so does every session after a
compaction. `python3 tools/now.py context` prints what the agent will be given.

**Your work goes in `projects/`, one folder per project.** Each folder's `README.md` starts with a short block
that says what the project is, its status and the file to open first; the map in `projects/README.md` and the
project lines at session start are drawn from those blocks. A folder of notes you already have moves in whole as
one project: `mv ~/notes projects/ && python3 tools/adopt.py projects/notes`. Nothing in it is renamed, and the
links already broken in it will not stop your turns.

**Working on a code repository?** Leave it where it is and name it under `outside` in its project's block, so
the agent knows where it is. Add it to a session with `claude --add-dir ~/code/api`; Codex and Antigravity take the
same flag. What you decide about the code is logged here, with everything else.

**Or take only the lenses.** Copy [`system/skills/lenses/`](system/skills/lenses/SKILL.md) into any project, or
read the table yourself. There is nothing to install.

## In a long session

You keep one conversation going and switch between jobs inside it. The context is compacted again and again.

| | What the kit does |
|---|---|
| Decisions | The agent logs a decision in one line when you make it. Hooks put those lines back in front of it, so a compaction does not lose them. |
| Long threads | Each has one file: where it stands, what was decided and why, what was rejected and why, what is open, and the next move. The agent is told to read it before it answers. |
| "Done" | A check on links and state runs when the turn ends, over the kit's files and the documents the turn edited. It stops the turn once and says why. It also stops a turn in which an edit tool changed a folder you listed as read-only. `python3 tools/linkcheck.py --mine` checks all of your own folders. |
| Broad reading | A separate worker does it. A short receipt comes back: the verdict, what is still unknown, and where the full trace is. |
| Switching agents | All three runtimes read the same rules and the same state. |
| What you said | `python3 tools/recall.py find "why did we settle on two pricing tiers" --role user` searches the words you typed in past sessions, in all three runtimes. It does not search the agent's summaries of them. |

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/session-dark.svg">
    <img src=".github/assets/session-light.svg" width="100%" alt="Five moments in a session. At session start the current state is injected. While you work, the agent logs each decision in one line. An edit marks the workspace as changed. At the end of the turn a check runs on links and state. Before compaction, Claude Code and Codex record that one is coming. After compaction the session starts again from the files.">
  </picture>
</p>

## Thinking and writing

**Thinking lenses** are thirteen questions, each for a side of a problem that is easy to miss. Four of them:

| When | Ask |
|---|---|
| You will run or send it soon, and only reasons for success have piled up | What would make it fail for certain? |
| You want to remove a practice whose reason you do not know | What was it preventing? Does that condition still exist? |
| The speaker gains from the conclusion | Would they have said it even if it were not true? |
| You are about to write "there is none" | What could never have entered this data in the first place? |

An agent may use one before it commits to a design or a decision. When it does, its answer ends with the question
and what it changed, as in the picture at the top. [All thirteen](system/skills/lenses/SKILL.md), each with a
worked example.

**Deep pass** is for one hard question: a decision that cannot be undone, reaches people outside, or is
expensive. The agent reads before it forms options, tries to break the answer it favours, and comes back with one
recommendation, the strongest objection to it, and what would reverse it.
[The steps](system/skills/deep-pass/SKILL.md).

**Plain writing** is for anything a person outside will read. The guide was built from 63 drafts that were sent
back, most of them for a reason other than length, so it starts from who will read the text and the one thing it
has to do.
[The guide](system/skills/plain-writing/SKILL.md).

A fourth skill, [large jobs](system/skills/large-jobs/SKILL.md), asks six questions before a job that runs many
workers or outlives the session.

## The improvement loop

Once a week it reads new arXiv papers and your own corrections, builds at most two proposed changes in a copy
of the kit, runs the tests in a sandbox, and has a model that did not build the change review it. What passes
is saved as a patch for you to apply. The loop writes nothing into your files. It sends your session messages
and the kit's files to your runtime's model, so it stays off until you turn it on. It runs on macOS only.
[How it works](system/loop/README.md).

## When a better model arrives

I expect models to keep getting better and my attention to stay what it is. So the kit is meant to save my
attention, not to coach the model.

I checked the coaching on the part I like best, the thinking lenses: do they improve the agent's answers? Three
judge models from three vendors compared 26 pairs of answers without knowing which was which, one written with the
lens skill and one without. Where a judge picked a side, it was the lens side 52%, 58% and 56% of the time, too
close to tell from chance on 26 pairs. So the lenses stay for the person, which is why the agent shows you its
question. Whether seeing the question helps a person decide has not been measured.

The kit still coaches the model in 24 places, and [one page](system/specs/model-assumptions.md) lists each with
its reason. The same page says what each part is there for: you, or a gap in today's models and runtimes, such
as a session that forgets across a compaction. When a better model arrives, you test the parts that fill a gap
again and drop the ones whose gap is gone. The page has the steps.

## Before you install

- Sessions you start in this folder get the kit. It does not install into a code repository, and it is not a
  plugin.
- Requirements: Python 3.9 or later, Git and Bash. There are no packages to install: the kit uses only Python's
  standard library. It was tested on macOS and is expected to work on Linux.
- On a company machine, read [the checklist](system/CHECKLIST.md) section A before you clone: your IT policy on outside
  repositories, project hooks and outside models.
- A fresh installation adds about 2,500 tokens to each new session: the [seven rules](AGENTS.md)
  and the names and descriptions of nine skills. The check at the end of a turn usually takes under a second.
- Claude Code and Antigravity were run in live sessions on a fresh installation. Codex was tested by replaying
  captured hook inputs and has not been run live yet. [How each was tested](MANUAL.md#hooks).
- This is a preview. No one new to the kit has used it alone for a week yet, so whether it saves a newcomer's
  attention is not measured.
- Everything that is yours is ignored by Git, so back it up yourself. What must stay out of anything written
  for other people goes under `_private/`: the agent suggests it, and you decide.
  [Where things are](MANUAL.md#where-things-are).
- Of three optional parts, the delivery check starts on, search by meaning starts on only when an embedding
  server on this machine already answers, and the improvement loop stays off until you turn it on.
  [What each needs and sends](MANUAL.md#optional).

[MIT license](LICENSE) · [Contributing](.github/CONTRIBUTING.md)
