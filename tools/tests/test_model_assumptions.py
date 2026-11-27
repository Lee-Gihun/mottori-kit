#!/usr/bin/env python3
"""Check that system/specs/model-assumptions.md names every hook step, optional part and skill.

Each is named in one code span of a fixed form, so a common word cannot stand in for it: a hook
step as its event and id (`SessionStart state`), an optional part as `options.py on <name>`, a
skill as its folder `system/skills/<name>/`.
"""
import ast
import os
from pathlib import Path
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import dispatch  # noqa: E402

ROOT = Path(TOOLS).parent
PAGE = ROOT / "system" / "specs" / "model-assumptions.md"


def option_names():
    """The names in tools/options.py OPTIONS, read from its source without importing it."""
    module = ast.parse((ROOT / "tools" / "options.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "OPTIONS" for t in node.targets):
            return [value.value for entry in node.value.elts
                    for key, value in zip(entry.keys, entry.values)
                    if isinstance(key, ast.Constant) and key.value == "name"]
    raise AssertionError("tools/options.py has no OPTIONS list")


def spans():
    """Every code span the page must hold."""
    steps = [f"{event} {step.id}" for table in (dispatch.STEPS, dispatch.AGY_STEPS)
             for event, steps in table.items() for step in steps]
    options = [f"options.py on {name}" for name in option_names()]
    skills = [f"system/skills/{p.name}/" for p in sorted((ROOT / "system" / "skills").iterdir())
              if (p / "SKILL.md").is_file()]
    return steps + options + skills


def missing(text):
    """The required spans that the page text does not hold."""
    return [span for span in spans() if f"`{span}`" not in text]


def test_the_page_names_every_step_option_and_skill():
    absent = missing(PAGE.read_text(encoding="utf-8"))
    assert absent == [], f"not named in {PAGE.name}: {absent}"


def test_the_lists_are_read_from_the_code():
    found = spans()
    assert "SessionStart state" in found and "Stop gate" in found and "PreCompact precompact" in found
    assert "UserPromptSubmit restate" in found
    assert "options.py on loop" in found and "system/skills/lenses/" in found
    assert len(found) == len(set(found)), found


def test_a_page_lacking_one_span_fails():
    text = PAGE.read_text(encoding="utf-8")
    for span in ("SessionStart state", "options.py on deliver", "system/skills/deep-pass/"):
        assert missing(text.replace(f"`{span}`", span)) == [span], span


TESTS = [
    test_the_page_names_every_step_option_and_skill,
    test_the_lists_are_read_from_the_code,
    test_a_page_lacking_one_span_fails,
]


if __name__ == "__main__":
    failed = 0
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as exc:  # noqa: BLE001 - report every failing test
            failed += 1
            print("FAIL", test.__name__, exc)
    print(f"model-assumptions tests: {len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
