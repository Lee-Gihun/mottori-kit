---
name: dossier
description: "Use when returning to a deep thread that has a dossier, named by the user: read the dossier and summarize the current position, settled conclusions and open questions before starting."
---

# Dossier

Run the return ritual for a thread by reading its dossier. The thread is the one the user named in the text
written with this command.

List registered threads with `python3 tools/now.py threads`. That command is the authority: it reads the
`threads` array in `instance/config.json` plus the private thread list (`threads.json` in the local
private state folder) when it exists. Do not hard-code the list here.

Follow "Coming back to a topic" in `system/rituals.md#entry`: summarize (1) the current position, (2) settled
conclusions, and (3) open questions, open the original or search the topic's own words with recall when needed,
then begin.
