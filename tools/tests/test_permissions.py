#!/usr/bin/env python3
"""The project's permission rules for Claude Code. The kit allows nothing in advance, and an edit
to what the checks and the boundary rest on always asks, in every permission mode.

No allow rule is shipped, on purpose. A rule names a script by a path relative to wherever the
agent runs the command, so `python3 tools/now.py` would also run a same-named file planted in a
subfolder the agent had moved into, without a prompt.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rules():
    with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as source:
        return json.load(source)["permissions"]


def test_no_command_is_allowed_in_advance():
    assert not rules().get("allow"), rules().get("allow")
    assert "defaultMode" not in rules() and "additionalDirectories" not in rules(), rules()


def test_an_edit_to_what_the_checks_rest_on_always_asks():
    ask = rules()["ask"]
    # The kit's code and the lines that start it.
    for path in ("/tools/**", "/setup.sh", "/.claude/**", "/.codex/**", "/.agents/**"):
        assert f"Edit({path})" in ask, path
    # The rules every session loads, and the owner's boundary and configuration.
    for path in ("/AGENTS.md", "/CLAUDE.md", "/instance/rules.md", "/instance/config.json"):
        assert f"Edit({path})" in ask, path
    # What the turn-end check has accepted.
    for path in ("/state/.gate-baseline.json", "/state/.gate-adopted.json"):
        assert f"Edit({path})" in ask, path


def test_every_rule_is_an_edit_rule_anchored_at_the_project_root():
    for rule in rules()["ask"]:
        assert rule.startswith("Edit(/") and rule.endswith(")"), rule
    assert "deny" not in rules()


TESTS = [
    test_no_command_is_allowed_in_advance,
    test_an_edit_to_what_the_checks_rest_on_always_asks,
    test_every_rule_is_an_edit_rule_anchored_at_the_project_root,
]


def main():
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f"✗ {test.__name__}: {type(error).__name__}: {error}")
    print(f"permissions: {len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
