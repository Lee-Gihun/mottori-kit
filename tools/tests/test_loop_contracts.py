#!/usr/bin/env python3
"""Test what the loop requires of documents its model workers write: each requirement is a constant that the
prompts render and the readers use."""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_contracts as LC  # noqa: E402


def test_a_rendered_json_block_is_read_back_and_a_broken_one_is_left_out():
    value = {"cards": 3, "ids": ["2601.1", "café"]}
    text = "intro\n" + LC.json_block(value) + "\n" + LC.JSON_FENCE + "\n{broken\n```\n" + LC.json_block([1])
    assert LC.json_blocks(text) == [value, [1]], LC.json_blocks(text)
    assert LC.json_blocks("") == [] and LC.json_blocks(None) == []


def test_a_heading_is_found_only_at_the_start_of_a_line():
    assert LC.LENS_HEADING.startswith("## ") and LC.LENS_HEADING.isascii()
    assert LC.has_heading(f"# r\n\n{LC.LENS_HEADING}\n- item\n", LC.LENS_HEADING)
    assert not LC.has_heading(f"# r\nsee {LC.LENS_HEADING} below\n", LC.LENS_HEADING)
    assert not LC.has_heading("", LC.LENS_HEADING)


# Run in a scratch copy whose loop_contracts.py holds other values: the prompts and readers must follow it.
_FOLLOWS = r"""
import os, subprocess, sys
root = sys.argv[1]
sys.path[:0] = [os.path.join(root, "tools", "loop"), os.path.join(root, "tools", "loop", "lib")]
import loop_contracts as C, loop_edits, loop_judging, loop_prompts, papers_apply
assert C.LENS_HEADING == "## Moved lenses" and C.EDIT_END == "%%% STOP"
d = "_private/work/papers/2026-10-07-kit"
judge = loop_prompts.judge_prompt(d, "papers", root=root)
assert C.LENS_HEADING in judge and "## Lenses that changed the choice" not in judge, judge
impl = loop_prompts.impl_prompt(dict.fromkeys(loop_judging.BUNDLE_FIELDS, "x") | {"files": ["tools/a.py"]}, d)
assert impl.count(C.EDIT_END) == 2 and "@@@ END" not in impl, impl
block = f"%%% FILE tools/a.py\nA = 1\n{C.EDIT_END}\n"
assert loop_edits.parse_edits(block) == [("FILE", "tools/a.py", "A = 1\n", None)]
assert loop_edits.parse_edits("@@@ FILE tools/a.py\nA = 1\n@@@ END\n") == [], "old markers were read"
data = C.json_block({"bundles": []})
assert loop_judging.judgment_data(f"{C.LENS_HEADING}\n- x\n\n" + data) == {"bundles": []}
print("ok")
"""


def test_prompts_and_readers_follow_a_changed_constant():
    tools = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = tempfile.mkdtemp(prefix="contracts-follow-")
    try:
        os.makedirs(os.path.join(root, "tools", "lib"))
        os.makedirs(os.path.join(root, "tools", "loop", "lib"))
        for src in glob.glob(os.path.join(tools, "loop", "lib", "loop_*.py")) + glob.glob(os.path.join(tools, "loop", "loop_*.py")) + [
                os.path.join(tools, n) for n in ("loop/papers_apply.py", "lib/paths.py", "lib/safeio.py")]:
            shutil.copy2(src, os.path.join(root, "tools", os.path.relpath(src, tools)))
        path = os.path.join(root, "tools", "loop", "lib", "loop_contracts.py")
        text = open(path, encoding="utf-8").read()
        for old, new in (('LENS_HEADING = "## Lenses that changed the choice"', 'LENS_HEADING = "## Moved lenses"'),
                         ('EDIT_MARK = "@@@ "', 'EDIT_MARK = "%%% "'), ('EDIT_MARK + "END"', '"%%% STOP"')):
            assert text.count(old) == 1, old
            text = text.replace(old, new)
        open(path, "w", encoding="utf-8").write(text)
        subprocess.run(["git", "init", "-q", root], check=True)
        p = subprocess.run([sys.executable, "-c", _FOLLOWS, root], capture_output=True, text=True, cwd=root)
        assert p.returncode == 0 and p.stdout.strip() == "ok", p.stdout + p.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


# Words that would tell a worker to go through every lens instead of the one or two that could change the choice.
EVERY_LENS = ("every lens", "one line per lens", "each lens in", "lenses/*.md", "lens sweep")


def test_no_prompt_asks_for_every_lens():
    sys.path[:0] = [os.path.join(TOOLS, "loop", "lib")]
    import loop_beat
    import loop_prompts
    root = os.path.dirname(TOOLS)
    judge = loop_prompts.judge_prompt("_private/work/papers/2026-10-07-kit", "papers", root=root)
    texts = {"judge": judge}
    for path in glob.glob(os.path.join(root, loop_beat.PROMPTS, "*.md")):
        texts[os.path.basename(path)] = open(path, encoding="utf-8").read()
    for name, text in texts.items():
        low = text.lower()
        assert not [w for w in EVERY_LENS if w in low], (name, [w for w in EVERY_LENS if w in low])
        if "lens" in low:
            assert "{{LENS_SKILL}}" in text or LC.LENS_SKILL in text, name
    assert "sweep" not in LC.LENS_HEADING.lower()
    assert "the one or two lenses" in judge and "Leave the section out" in judge, judge


TESTS = [
    test_no_prompt_asks_for_every_lens,
    test_a_rendered_json_block_is_read_back_and_a_broken_one_is_left_out,
    test_a_heading_is_found_only_at_the_start_of_a_line,
    test_prompts_and_readers_follow_a_changed_constant,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
