#!/usr/bin/env python3
"""What a hook run is given: the runtime's JSON payload on stdin, and whether the run is a probe.

dispatch.py reads the payload once per hook event; gate.py, deliver.py and now.py read it
themselves only when they are run by hand with a payload piped in. Importing this module reads
nothing."""
import json
import os
import select
import sys
import time


def probe():
    """Whether this run is a probe whose output nobody reads, so nothing it prints may be recorded
    as shown: doctor sets MOTTORI_INTERNAL_RUN, the hook canary sets MOTTORI_HOOK_CANARY."""
    return bool(os.environ.get("MOTTORI_INTERNAL_RUN") or os.environ.get("MOTTORI_HOOK_CANARY"))


def hook_payload(timeout=1.0):
    """Return the hook's JSON object on stdin, or {} when stdin is absent, a terminal, not JSON,
    or not closed within timeout seconds, so a hand run or a parent that keeps the pipe open
    (silent or after a partial write) does not hang the hook."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        try:
            fd = sys.stdin.fileno()
        except (OSError, ValueError):
            fd = None   # An in-memory stream has no descriptor and cannot block: read it directly.
        if fd is None:
            raw = sys.stdin.read()
        else:
            # One deadline for the whole read: readiness for one byte is not end of input.
            chunks, deadline = [], time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([fd], [], [], left)[0]:
                    return {}
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        payload = json.loads(raw or "{}")
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
