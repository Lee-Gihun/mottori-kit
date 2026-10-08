# Recall

Run `python3 tools/recall.py find "$ARGUMENTS"` to recover the original past conversation. Do not paste the
whole result. Translate only a few lines connected to the current discussion
(`system/PRD-session-memory.md#retrieval`).
Log a known-item failure only when the source item is independently known to exist but retrieval failed.
Investigate source availability, parser, filtering, ranking, and expression mismatch; mark an unknown cause
unknown. An ordinary zero-match result proves neither a known-item failure nor that the original is absent.
