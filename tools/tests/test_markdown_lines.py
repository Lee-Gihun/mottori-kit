#!/usr/bin/env python3
"""Keep the kit's Markdown readable as source: no line of prose runs past LIMIT characters (KIT-DR-092).

The files judged are the Markdown files system/dev/kit-files.txt lists, so an installation's own notes
are never judged. A line is prose unless it is one of these, which stay as they are:

- a line inside a fenced code block, or in the front matter at the top of a file (a skill's
  description is read as one line);
- a heading, which Markdown cannot continue on a second line (a decision record's heading carries its
  status there);
- a table row, which cannot be wrapped, or an HTML line;
- a line that cannot be broken within the limit: its first space outside inline code comes after
  LIMIT, as in a long URL, a long evidence marker or a long inline code span.

A long line of prose is wrapped at a space; a line break inside a paragraph does not change what
Markdown renders.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT_FILES = "system/dev/kit-files.txt"
# The longest line of prose a kit Markdown file may hold. Lines are wrapped near 110, so a word or two
# of slack fits before a line counts as too long.
LIMIT = 120
# A code span opens on a backtick run that is not backslash-escaped and closes on a run of the same length.
SPAN_OPENER = re.compile(r"\\.|`+")
# Separators that stay at the end of the line before them.
SEPARATORS = ("·", "—", "–")
# The indentation, blockquote markers and list marker a line starts with; a break there wraps nothing.
LEAD = re.compile(r"[ \t]*(?:>[ \t]?)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)?")


def kit_markdown(root: Path) -> list[str]:
    """The Markdown paths the kit ships, from its list, or every Markdown file of a tree without one."""
    listing = root / KIT_FILES
    if listing.is_file():
        names = [line for line in listing.read_text(encoding="utf-8").splitlines()
                 if line and not line.startswith("#")]
    else:
        names = [p.relative_to(root).as_posix() for p in root.rglob("*.md")]
    # An installation's own state and private material are never the kit's.
    return sorted(name for name in names if name.endswith(".md") and (root / name).is_file()
                  and not name.startswith((".git/", "_private/", "state/", "instance/")))


def code_spans(line: str) -> list[tuple[int, int]]:
    """The (start, end) of each inline code span of one line."""
    spans, pos = [], 0
    while True:
        m = SPAN_OPENER.search(line, pos)
        if not m:
            return spans
        pos = m.end()
        if m.group().startswith("\\"):
            continue
        close = re.compile(r"(?<!`)`{%d}(?!`)" % len(m.group())).search(line, pos)
        if close:
            spans.append((m.start(), close.end()))
            pos = close.end()


def breakable(line: str) -> bool:
    """Whether the line has a space outside inline code where it could be broken within LIMIT.

    A lone separator such as the " · " between evidence markers stays with the word before it, so
    the space in front of it is not a place to break."""
    start = LEAD.match(line).end()
    spans = code_spans(line)
    return any(line[i] == " " and line[:i].strip() and not any(a <= i < b for a, b in spans)
               and line[i + 1:].split(" ", 1)[0] not in SEPARATORS
               for i in range(start, min(len(line), LIMIT + 1)))


def long_lines(text: str) -> list[tuple[int, int]]:
    """(line number, length) of each prose line longer than LIMIT."""
    lines = text.split("\n")
    found, fence, first = [], None, 0
    if lines and lines[0] == "---":
        first = next((i + 1 for i in range(1, len(lines)) if lines[i] == "---"), 0)
    for number, line in enumerate(lines, 1):
        if number <= first:
            continue
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            continue
        if len(line) <= LIMIT or stripped.startswith(("#", "|", "<")):
            continue
        if breakable(line):
            found.append((number, len(line)))
    return found


def problems(root: Path) -> list[str]:
    found = []
    for name in kit_markdown(root):
        for number, length in long_lines((root / name).read_text(encoding="utf-8")):
            found.append(f"{name}:{number}: {length} characters of prose; wrap it at a space")
    return found


def test_kit_markdown_keeps_prose_lines_within_the_limit():
    found = problems(ROOT)
    assert found == [], f"{len(found)} lines over {LIMIT} characters:\n" + "\n".join(found[:40])


def test_a_long_prose_line_fails_and_the_lines_that_cannot_wrap_pass():
    word = "word " * 30
    long_code = "`" + "x" * 130 + "`"
    with tempfile.TemporaryDirectory(prefix="markdown-lines-") as tmp:
        root = Path(tmp)
        (root / "system" / "dev").mkdir(parents=True)
        (root / KIT_FILES).write_text("doc.md\nskill.md\n", encoding="utf-8")
        (root / "notes.md").write_text(word + "\n", encoding="utf-8")  # not a kit file
        (root / "skill.md").write_text(f"---\ndescription: \"{word}\"\n---\n\nShort.\n", encoding="utf-8")
        allowed = (f"# {word}\n\n| {word} | cell |\n|---|---|\n\n```text\n{word}\n```\n\n"
                   f"<img alt=\"{word}\">\n\nhttps://example.org/{'a' * 130}\n\n"
                   f"- {long_code} {word}\n\n" + "evidence:\n" + "test:" + "y" * 130 + " ·\n")
        (root / "doc.md").write_text(allowed, encoding="utf-8")
        assert problems(root) == [], problems(root)
        (root / "doc.md").write_text(allowed + f"\n- {word}\n\n> {word}\n", encoding="utf-8")
        assert problems(root) == [f"doc.md:{n}: 152 characters of prose; wrap it at a space"
                                  for n in (len(allowed.split("\n")) + 1, len(allowed.split("\n")) + 3)], \
            problems(root)


TESTS = [
    test_kit_markdown_keeps_prose_lines_within_the_limit,
    test_a_long_prose_line_fails_and_the_lines_that_cannot_wrap_pass,
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
    print(f"markdown-lines tests: {len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
