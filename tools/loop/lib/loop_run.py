#!/usr/bin/env python3
"""Holds what one applier run carries over one cycle folder: its folders and state file, the notes for
REPORT.md, and the base its candidates are built on: one snapshot of the working tree (tracked changes
and untracked files Git does not ignore), taken once per run, since that is the tree a saved patch is
applied to. A root argument names the working tree; without it, the tree this file lives in."""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
from loop_common import write  # noqa: E402
from loop_isolate import build_snapshot  # noqa: E402

# Workers read the working tree with its tracked changes (the worker tool's --worktree dirty).
WORKER_TREE = ("--worktree", "dirty")


class Ctx:
    def __init__(self, d, cyc, apply_dir, source, root=None):
        self.d, self.cyc, self.apply_dir, self.source = d, cyc, apply_dir, source
        self.root = root or ROOT
        self.notes, self.base_cache, self.base_summary = [], {}, ""
        self.state_path = os.path.join(apply_dir, "state.json")
        self.state = {}
        self._snapshot = None
        self.blocked = []         # first lines of commit checks that fail on the unpatched base
        self.ceiling = False      # a stage did not start because the cycle reached loop.token_ceiling

    def test_base(self):
        """The snapshot commit of the working tree candidates are built and tested on."""
        if self._snapshot is None:
            self._snapshot = build_snapshot(self.root)
            if self._snapshot[1]:
                write(os.path.join(self.apply_dir, f"snapshot-{self._snapshot[0][:12]}.json"),
                      json.dumps({"snapshot": self._snapshot[0], "head": self.source_identity["base_rev"],
                                  "taken": datetime.datetime.now().isoformat(timespec="seconds"),
                                  "sha256": self._snapshot[1]}, ensure_ascii=False, indent=1) + "\n")
        return self._snapshot[0]

    def save(self, bundles):
        self.state.setdefault("bundles", {})
        for b in bundles:
            if "_r" in b:
                self.state["bundles"][b["id"]] = b["_r"]
        write(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=1) + "\n")
