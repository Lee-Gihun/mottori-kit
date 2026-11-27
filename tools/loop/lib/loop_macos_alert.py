#!/usr/bin/env python3
"""Shows one notification on this Mac through osascript, unless MOTTORI_NO_NOTIFY is set."""
import os
import subprocess


def notify(title, message):
    """Show message under title; return None when shown or skipped, else the reason it was not."""
    if os.environ.get("MOTTORI_NO_NOTIFY"):
        return None
    quote = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    r = subprocess.run(["osascript", "-e", f'display notification "{quote(message)}" with title "{quote(title)}"'],
                       capture_output=True, text=True, timeout=20)
    return None if r.returncode == 0 else (r.stderr.strip() or f"osascript exit {r.returncode}")
