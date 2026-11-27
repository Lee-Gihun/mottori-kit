---
name: recall
description: "Use when the original words of a past conversation are needed: search past conversations with the recall tool for the words the user gave and quote only the few lines that matter."
---

# Recall

Run `python3 tools/recall.py find "<question>" --role user`, where the question is the text the user wrote
with this command, turned into one full sentence when it is a single word. `--role user` returns only what the
user typed, not the agent's summaries of it. Do not paste the whole result. Quote or paraphrase only the few
lines connected to the current discussion (`system/specs/PRD-session-memory.md#retrieval`).
Log a known-item failure only when the source item is independently known to exist but retrieval failed.
Investigate source availability, parser, filtering, ranking, and expression mismatch; mark an unknown cause
unknown. An ordinary zero-match result proves neither a known-item failure nor that the original is absent.
