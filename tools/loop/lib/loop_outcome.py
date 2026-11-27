#!/usr/bin/env python3
"""Reads and sets the outcome of one bundle's record.

A bundle's record is the dict the applier keeps for it in the cycle's apply/state.json. Its outcome is
one of four words, the same in the record and in what a person reads: saved (built, tested, its
evidence holds, reviewed with PASS; its patch file stays in the apply folder), refused (with the stage
and the reason), abandoned (both implementation attempts failed) and pending (not finished in this
run, with why and what continues it). A record without one of the first three is pending."""

SAVED, REFUSED, ABANDONED, PENDING = "saved", "refused", "abandoned", "pending"
OUTCOMES = (SAVED, REFUSED, ABANDONED, PENDING)


def pend(r, why):
    """Record that the bundle is not finished in this run; why says why and what continues it."""
    r["result"], r["outcome"] = f"{PENDING}: {why}", PENDING
    r.pop("refused_at", None)   # A pending attempt replaces an earlier refusal of the same record.


def refuse(r, stage, why, final=False):
    """Record that the bundle's attempt was refused at stage (tests, gate, review, delivery, patch or a
    stage error's own). A final refusal ends the bundle; another lets the next attempt try."""
    r["result"], r["refused_at"] = f"{REFUSED}: {why}", stage
    if final:
        r["reject_kind"] = "final"


def is_terminal(r):
    """Whether no later run takes the bundle up again."""
    return bundle_outcome(r) != PENDING


def bundle_outcome(r):
    """The outcome word of a bundle's record."""
    found = (r or {}).get("outcome")
    return found if found in OUTCOMES else PENDING
