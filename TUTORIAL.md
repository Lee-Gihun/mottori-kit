# Your first hour

One evening with the kit, in one conversation. You fix a bug in a shop's checkout, decide how chapter 4 of a
novel opens, and note an apartment viewing, then let the conversation compact and come back to the bug. Use your
own topics if you have them; the steps are the same.

Lines in quotes are what you say to your agent. Commands are for a terminal in the same folder, when you want to
see for yourself what the agent was given. The outputs below are from a fresh installation; dates and counts will
differ.

## 1. Set it up (five minutes)

```bash
git clone https://github.com/Lee-Gihun/mottori-kit ~/work
cd ~/work
```

Open Claude Code, Codex or Antigravity in `~/work` and say:

> Read SETUP.md and set up this folder. Show me what doctor, the kit's health check, says when you finish.

It ends with a line like this:

```text
doctor: ok · /Users/you/work
35 checks passed, 8 did not apply.
```

If setup stops, it says why and what to do; [the manual](MANUAL.md#4-troubleshoot-hooks-and-gate-limits) covers
the rest. Codex and Antigravity ask you once to approve the kit's hooks, and Claude Code asks you to trust the
folder. That approval is yours to give; the agent cannot give it.

## 2. Decide something

> Checkout bug: two buyers can get the last item. Let's fix it with a lock on the item row, not a queue. A queue
> adds a second of wait at sale peaks.

Besides answering, the agent writes a line like this to the journal:

```text
recorded: - 2026-11-27T17:48:01+09:00 [checkout/decision] Fix the cart race with a lock, not a queue: a queue adds a second of wait at sale peaks
```

`checkout` is the topic, which the agent names, and `decision` is the kind of line. You do not have to ask for
it: rule 2 of [the seven rules](AGENTS.md) tells the agent to log decisions in the same turn.

## 3. Switch topics in the same chat

> Different thing. Chapter 4 should open at the night market, not the palace.

> And I saw the Mapo flat today. Quiet in the day; I still need to ask about Friday nights.

No new session. Each gets its own line, under its own topic. To see what the next session, or this one after a
compaction, will be given:

```bash
python3 tools/now.py context
```

```text
## Recent decisions and phases
- 2026-11-27T17:48 [checkout/decision] Fix the cart race with a lock, not a queue: a queue adds a second of wait at sale peaks
- 2026-11-27T17:48 [novel/decision] Chapter 4 opens at the night market, not the palace
- 2026-11-27T17:48 [apartment/state] Mapo flat viewed: quiet by day; ask about Friday nights
```

## 4. Give the long topic its own file

> The checkout bug will take a while. Make it a project, with a dossier for the bug.

The agent makes a project folder, such as `projects/shop/`, with a `README.md` whose first lines say what the
project is and which file to open first, and a dossier for the bug with five fields:

```text
- Position: The race is in the cart's stock check. Fix chosen, not built yet.
- Decisions, with reasons: A lock on the item row: one buyer waits a few milliseconds, nobody pays for stock that is gone.
- Rejected, with reasons: A queue for every checkout: adds about a second at sale peaks.
- Open questions: Does the payment provider retry on timeout?
- Next move: Write the failing test that buys the last item from two sessions at once.
```

It also names the dossier in `instance/config.json`, so that every session starts knowing the thread exists.
Claude Code asks you before that edit, as it does before any edit to the kit's configuration; approve it. Then:

```bash
python3 tools/now.py threads
```

```text
checkout     - Checkout bug: dossier `projects/shop/checkout-bug.md`
```

If the shop's code lives in its own repository, say where: "the code is in ~/code/shop". The project's README
records it under `outside`. To work on the code, start your next session with `claude --add-dir ~/code/shop`.

## 5. Let it compact, and come back

Talk about the novel and the apartment until the conversation compacts, or type `/compact` in Claude Code or
Codex to compact now. Then:

> Back to the checkout bug.

Before it continues, the agent opens the dossier and tells you where the bug stands, what was settled and what is
open. The next move is the failing test. You did not repeat anything.

## 6. Watch a turn get stopped

> Write short notes for chapter 4 in projects/novel/ch4-notes.md, linking to the chapter 3 outline at
> ch3-outline.md.

There is no `ch3-outline.md`. When the turn ends, the check stops it once and tells the agent why:

```text
Issues absent before this turn appeared: linkcheck: projects/novel/ch4-notes.md -> ch3-outline.md.
```

The agent then fixes the link, or tells you why it left it, for example because the outline is still to come.
The next end of a turn lets it pass, and the file is checked again when it is next edited. To check every folder
that is yours at any time:

```bash
python3 tools/linkcheck.py --mine
```

## 7. Find what you said

After a session or two, search your own words, as you typed them:

```bash
python3 tools/recall.py find "what did I say about the queue" --role user
```

Or ask the agent: "What exactly did I say about Friday nights?" It searches the same way and quotes you.

## 8. Ask for a question before a decision

> I'm about to sign the lease for the Mapo flat. Use a lens first.

The answer ends with the question it used, in terms of your case, and what it changed. In one run:

```text
Lens (inversion): what would make you regret this lease for certain, and what's the cheapest way to find out
first? It changed my answer from "go ahead" to "visit tonight, then sign."
```

A lens is offered, never required; the agent may also find that the answer held.

## Where things went

| Folder | What is in it | In Git? |
|---|---|---|
| `projects/` | One folder per project, and `projects/README.md`, a map drawn from them | Only what you add below the marked line in `.gitignore` |
| `state/` | The journal, one line per decision, and `NOW.md`, the view drawn from it | No |
| `instance/` | Your settings, your rules and your decision records | No |
| `_private/` | What must stay out of Git and out of anything written for other people | No, and the commit check refuses it |

Everything that is yours is ignored by Git, so back the folder up yourself.

## Next

- A folder of notes you already have: move it into `projects/` and run `python3 tools/adopt.py projects/FOLDER`.
  Nothing in it is renamed.
- Optional parts, such as search by meaning and the weekly improvement loop: `python3 tools/options.py`.
- Everything else, including updating the kit: [the manual](MANUAL.md).
