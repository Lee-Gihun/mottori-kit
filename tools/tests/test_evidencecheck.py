#!/usr/bin/env python3
"""Pin tools/dev/evidencecheck.py: marker form, that a marker names something here, and the
required places, run on small fixture trees."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "tools" / "dev" / "evidencecheck.py"
DECISIONS = "system/specs/kit-decisions.md"
MODEL_PAGE = "system/specs/model-assumptions.md"
GOOD_DECISIONS = (
    "# Decisions\n\n"
    "### DR-001 First\n"
    "Context: `test:tools/tests/test_probe.py::test_probe` and `paper:2609.09134v2`.\n"
    "Decision: keep it.\n\n"
    "### DR-002 Second\n"
    "Context: `decision:KIT-DR-001`.\n"
)
GOOD_CHANGELOG = (
    "# Changelog\n\n## v1\n\n"
    "### `[Action required]` Do the thing\n\n"
    "Evidence: `decision:KIT-DR-002`.\n\n"
    "### `[Note]` Nothing to back it\n\n"
    "evidence: none\n"
)


def tree(**files):
    """A fixture tree with the four checked files in order, overridden by files (path: text)."""
    root = Path(tempfile.mkdtemp(prefix="evidence-"))
    texts = {DECISIONS: GOOD_DECISIONS, "CHANGELOG.md": GOOD_CHANGELOG,
             "system/dev/enforcement.md": "| id | test |\n|---|---|\n| R1 | `test:tools/tests/test_probe.py::test_probe` |\n",
             MODEL_PAGE: "| Part | Basis |\n|---|---|\n| state | measured. `decision:KIT-DR-001` |\n",
             "tools/tests/test_probe.py": "def test_probe():\n    pass\n"}
    texts.update(files)
    for rel, text in texts.items():
        if text is None:
            continue
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def check(root):
    result = subprocess.run([sys.executable, str(CHECKER), "--tree", str(root)], capture_output=True,
                            text=True, env=dict(os.environ, MOTTORI_INSTANCE=str(root)), timeout=60)
    return result.returncode, result.stdout.splitlines()


def judged(**files):
    root = tree(**files)
    try:
        return check(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_tree_in_order_passes_silently():
    assert judged() == (0, [])


def test_a_marker_naming_a_missing_test_fails():
    code, lines = judged(**{"system/dev/enforcement.md":
                            "| R1 | `test:tools/tests/test_probe.py::test_gone` |\n"})
    assert code == 1, lines
    assert lines == ["system/dev/enforcement.md:1: test:tools/tests/test_probe.py::test_gone "
                     "names nothing in this tree"], lines


def test_the_model_page_is_read_as_a_fourth_target():
    code, lines = judged(**{MODEL_PAGE: "| state | `test:tools/tests/test_probe.py::test_gone` |\n"})
    assert code == 1 and lines == [f"{MODEL_PAGE}:1: test:tools/tests/test_probe.py::test_gone "
                                   "names nothing in this tree"], lines


def test_a_malformed_marker_fails():
    code, lines = judged(**{"system/dev/enforcement.md": "x\n`test:tools/tests/probe.py::test_probe`\n"})
    assert code == 1 and lines == ["system/dev/enforcement.md:2: test:tools/tests/probe.py::test_probe malformed"], lines
    code, lines = judged(**{"system/dev/enforcement.md": "`paper:https://example.org/x`\n"})
    assert code == 1 and "malformed" in lines[0], lines


def test_decision_markers_resolve_to_record_headings():
    code, lines = judged(**{"CHANGELOG.md": GOOD_CHANGELOG.replace("KIT-DR-002", "KIT-DR-009")})
    # The item then holds no valid marker either.
    assert code == 1 and lines == ["CHANGELOG.md:7: decision:KIT-DR-009 names nothing in this tree",
                                   "CHANGELOG.md: [Action required] Do the thing has no valid marker "
                                   "and no `evidence: none`"], lines
    # A decision without the KIT- prefix is the instance's own record.
    instance = "### DR-007 Local\nContext: evidence: none\n"
    changelog = GOOD_CHANGELOG.replace("KIT-DR-002", "DR-007")
    assert judged(**{"CHANGELOG.md": changelog})[0] == 1
    assert judged(**{"CHANGELOG.md": changelog, "instance/decisions.md": instance}) == (0, [])


def test_required_places_need_a_valid_marker_or_evidence_none():
    bare = GOOD_DECISIONS.replace("Context: `decision:KIT-DR-001`.", "Context: nothing cited.")
    code, lines = judged(**{DECISIONS: bare})
    assert code == 1 and lines == [f"{DECISIONS}: KIT-DR-002 context has no valid marker and no "
                                   "`evidence: none`"], lines
    assert judged(**{DECISIONS: bare.replace("nothing cited.", "evidence: none")}) == (0, [])
    # A marker after the context section does not count for it.
    late = bare.replace("nothing cited.", "nothing.\nDecision: see `decision:KIT-DR-001`.")
    assert judged(**{DECISIONS: late})[0] == 1
    code, lines = judged(**{"CHANGELOG.md": GOOD_CHANGELOG.replace("evidence: none", "no pointer")})
    assert code == 1 and lines == ["CHANGELOG.md: [Note] Nothing to back it has no valid marker and "
                                   "no `evidence: none`"], lines


def test_an_instance_without_the_files_passes_and_a_partial_tree_fails():
    assert judged(**{DECISIONS: None, "CHANGELOG.md": None, "system/dev/enforcement.md": None,
                     MODEL_PAGE: None}) == (0, [])
    code, lines = judged(**{"system/dev/enforcement.md": None})
    assert code == 1 and lines == ["system/dev/enforcement.md: missing"], lines


def test_prose_and_bracketed_markers_are_read_as_written():
    text = ("Verification test: run it by hand.\n"
            "See [the paper](paper:10.1000/a(b)c) and (`test:tools/tests/test_probe.py::test_probe`).\n")
    assert judged(**{"system/dev/enforcement.md": text}) == (0, [])


TESTS = (
    test_a_tree_in_order_passes_silently,
    test_a_marker_naming_a_missing_test_fails,
    test_the_model_page_is_read_as_a_fourth_target,
    test_a_malformed_marker_fails,
    test_decision_markers_resolve_to_record_headings,
    test_required_places_need_a_valid_marker_or_evidence_none,
    test_an_instance_without_the_files_passes_and_a_partial_tree_fails,
    test_prose_and_bracketed_markers_are_read_as_written,
)


if __name__ == "__main__":
    failed = []
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print("FAIL", test.__name__, type(error).__name__, str(error)[:400])
    print(f"evidencecheck tests: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
