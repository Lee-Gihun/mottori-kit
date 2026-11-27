#!/usr/bin/env python3
"""Says whether the improvement loop runs on this machine and hands out the module of each kind of
platform command: schedule, alert, process and sandbox.

The loop runs where a module of every kind exists. Each kind lives in tools/loop/lib/loop_<platform>_<kind>.py
and offers the same functions on every platform, so another platform is one more set of modules and
no change elsewhere. Today there is one platform, macOS. The modules are found beside this one, on the
path its importer already has."""
import importlib
import sys

# sys.platform value: the platform's name in the module names.
PLATFORMS = {"darwin": "macos"}
KINDS = ("schedule", "alert", "process", "sandbox")
REFUSAL = ("The improvement loop runs on macOS only for now: its isolation, schedule and alerts use "
           "macOS programs.")
# The few words the options list shows for the reason.
SHORT = "macOS only"


def name(system=None):
    """The platform's name in the module names, or None where the loop does not run."""
    return PLATFORMS.get(system or sys.platform)


def supported(system=None):
    return name(system) is not None


def module(kind, system=None):
    """The module of kind for this platform. Raises RuntimeError with REFUSAL where the loop does not run."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    plat = name(system)
    if plat is None:
        raise RuntimeError(REFUSAL)
    return importlib.import_module(f"loop_{plat}_{kind}")
