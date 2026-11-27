#!/usr/bin/env python3
"""Finds and stops processes on this Mac by a pattern of their command line, through pgrep and pkill."""
import subprocess


def running(pattern):
    """True when a process whose command line matches pattern runs, False when none does, None when
    pgrep could not tell."""
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 0 and r.stdout.strip():
        return True
    return False if r.returncode == 1 else None


def stop(pattern):
    """Stop every process whose command line matches pattern; True when pkill found one."""
    return subprocess.run(["pkill", "-f", pattern], capture_output=True, text=True, timeout=20).returncode == 0
