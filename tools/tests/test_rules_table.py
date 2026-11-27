#!/usr/bin/env python3
"""Check the rules table system/dev/enforcement.md: every cited test exists, every status is one of four.

A row has six cells: id, rule, where it is enforced, test, status, and what can still go wrong. The test
cell is `none`, a test marker `test:tools/tests/test_x.py::name` naming a function that exists, or the
path of a shell test file. A row that is not ENFORCED says what can still go wrong.
"""
import os
from pathlib import Path
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path.insert(0, os.path.join(TOOLS, "dev"))
import evidencecheck  # noqa: E402

ROOT = Path(TOOLS).parent

TABLE = "system/dev/enforcement.md"
STATUSES = ("ENFORCED", "DETECTED", "REVIEW", "UNENFORCED")


def rows(text):
    """Return the cells of each table row below the header row."""
    lines = [line for line in text.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[2:]]


def problems(tree):
    """Return one line for each thing wrong with the table of a tree."""
    found, seen = [], set()
    for cells in rows((Path(tree) / TABLE).read_text(encoding="utf-8")):
        if len(cells) != 6:
            found.append(f"row with {len(cells)} cells: {cells[:1]}")
            continue
        rule_id, _rule, _where, test, status, risk = cells
        if rule_id in seen:
            found.append(f"{rule_id}: id used twice")
        seen.add(rule_id)
        if status not in STATUSES:
            found.append(f"{rule_id}: status {status!r} is not one of {', '.join(STATUSES)}")
        if status != "ENFORCED" and not risk:
            found.append(f"{rule_id}: a {status} row has nothing on what can still go wrong")
        test = test.strip("`")
        if test.startswith("test:"):
            if evidencecheck.problem("test", test[len("test:"):], str(tree)):
                found.append(f"{rule_id}: {test} names no function")
        elif test != "none" and not (test.startswith("tools/tests/test_") and test.endswith(".sh")
                                     and os.path.isfile(os.path.join(tree, test))):
            found.append(f"{rule_id}: test cell {test!r} is not none, a test marker or a shell test file")
    return found


def test_the_table_holds():
    assert problems(ROOT) == [], problems(ROOT)


def test_a_row_citing_a_missing_function_fails():
    with tempfile.TemporaryDirectory(prefix="rules-table-") as tmp:
        tests = Path(tmp) / "tools" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_x.py").write_text("def test_here():\n    pass\n", encoding="utf-8")
        (tests / "test_y.sh").write_text("exit 0\n", encoding="utf-8")
        table = Path(tmp) / TABLE
        table.parent.mkdir(parents=True)
        head = "| Id | Rule | Enforced at | Test | Status | What can still go wrong |\n|---|---|---|---|---|---|\n"
        good = ("| a | A rule. | `tools/x.py` | `test:tools/tests/test_x.py::test_here` | ENFORCED | |\n"
                "| b | A rule. | `tools/x.py` | `tools/tests/test_y.sh` | DETECTED | Something. |\n"
                "| c | A rule. | none | none | UNENFORCED | Everything. |\n")
        table.write_text(head + good, encoding="utf-8")
        assert problems(tmp) == [], problems(tmp)
        table.write_text(head + good.replace("::test_here", "::test_gone"), encoding="utf-8")
        assert problems(tmp) == ["a: test:tools/tests/test_x.py::test_gone names no function"], problems(tmp)


def test_a_bad_status_or_a_silent_risk_fails():
    with tempfile.TemporaryDirectory(prefix="rules-table-") as tmp:
        table = Path(tmp) / TABLE
        table.parent.mkdir(parents=True)
        table.write_text("| Id | Rule | Enforced at | Test | Status | What can still go wrong |\n"
                         "|---|---|---|---|---|---|\n"
                         "| a | A rule. | none | none | CHECKED | Something. |\n"
                         "| b | A rule. | none | none | REVIEW | |\n"
                         "| b | A rule. | none | tools/tests/test_z.py | ENFORCED | |\n", encoding="utf-8")
        assert problems(tmp) == [
            "a: status 'CHECKED' is not one of ENFORCED, DETECTED, REVIEW, UNENFORCED",
            "b: a REVIEW row has nothing on what can still go wrong",
            "b: id used twice",
            "b: test cell 'tools/tests/test_z.py' is not none, a test marker or a shell test file",
        ], problems(tmp)


if __name__ == "__main__":
    for test in (test_the_table_holds, test_a_row_citing_a_missing_function_fails,
                 test_a_bad_status_or_a_silent_risk_fails):
        test()
        print("PASS " + test.__name__)
