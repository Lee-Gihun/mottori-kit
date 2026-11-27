---
name: now
description: "Use at the start of a session, after a resume or a compaction, or when asked for the current state: read the merged state view (the public NOW page and the local overlay), summarize it, then run the state check and apply the safe repairs."
---

# NOW

Run `python3 tools/now.py context`, which prints `state/NOW.md` together with what is kept under `_private/`,
and summarize the current state. If the local overlay is missing, call it "unavailable", not "absent". Next run
`python3 tools/now.py check`. Apply each repair that is safe and can be undone, then report it; propose the
rest. Propose, do not apply, a repair of one of the four critical kinds in `system/rituals.md#memory`:
something leaves the machine, data that cannot be rebuilt is deleted, an untouchable folder is touched, or money
or a usage limit is spent. If the merged view conflicts with the
conversation context, the merged view is authoritative.
