#!/usr/bin/env python3
"""What the improvement loop requires of documents its model workers write, each requirement defined once.

A prompt shows a requirement by rendering it from the constant here, and every reader of the document
uses the same constant, so changing one value changes the prompt and the readers together."""
import json
import os
import re

# The optional section where a worker says what each lens it used changed; left out when none changed anything.
LENS_HEADING = "## Lenses that changed the choice"
# The lens skill a worker may read after working the task its own way. Its pages are every *.md beside
# SKILL.md except SKILL.md and guide.md.
LENS_SKILL = "system/skills/lenses/SKILL.md"
LENS_NOT_PAGES = ("SKILL.md", "guide.md")
# The opening line of a fenced JSON block. A value the loop takes from a model's answer (a count, a
# list of ids, the judge's bundles) comes from such a block, never from a sentence.
JSON_FENCE = "```json"
_JSON_BLOCK = re.compile(re.escape(JSON_FENCE) + r"\s*\n(.*?)\n```", re.S)
# The edit blocks of an implementation worker's final answer. A block opens with EDIT_FILE or EDIT_EDIT
# and a path; an EDIT block then has EDIT_SEARCH and EDIT_REPLACE; every block ends with EDIT_END.
EDIT_MARK = "@@@ "
EDIT_FILE, EDIT_EDIT = EDIT_MARK + "FILE", EDIT_MARK + "EDIT"
EDIT_SEARCH, EDIT_REPLACE, EDIT_END = EDIT_MARK + "SEARCH", EDIT_MARK + "REPLACE", EDIT_MARK + "END"


def has_heading(text, heading):
    """Whether a line of text starts with heading."""
    return re.search(r"^" + re.escape(heading), text or "", re.M) is not None


def lens_skill(root):
    """The lens skill as a prompt names it: its path, or a note that this installation has none."""
    if os.path.isfile(os.path.join(root, LENS_SKILL)):
        return f"`{LENS_SKILL}`"
    return f"the lens skill (`{LENS_SKILL}`, missing in this installation: skip the lenses)"


def json_blocks(text):
    """The value of each fenced JSON block of text, in order; a block that is not JSON is left out."""
    values = []
    for block in _JSON_BLOCK.findall(text or ""):
        try:
            values.append(json.loads(block))
        except json.JSONDecodeError:
            continue
    return values


def json_block(value):
    """value as a fenced JSON block, the form a prompt shows and json_blocks reads."""
    return f"{JSON_FENCE}\n{json.dumps(value, ensure_ascii=False)}\n```\n"
