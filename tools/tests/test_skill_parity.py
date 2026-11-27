#!/usr/bin/env python3
"""What the paper-to-kit, now and garden skills promise, pinned in their bodies."""

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS = ROOT / "system" / "skills"
SOURCE = SKILLS / "paper-to-kit" / "SKILL.md"
EVIDENCE_SCHEMA = ROOT / "system" / "dev" / "evidence-schema.md"
EVIDENCECHECK = ROOT / "tools" / "dev" / "evidencecheck.py"


def metadata(source):
    """The workflow's own block under its title; the skill's front matter comes before it."""
    block = source.split("# paper-to-kit workflow\n\n---\n", 1)[1].split("---\n", 1)[0]
    return dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)


def test_canonical_contract_is_machine_visible():
    source = SOURCE.read_text(encoding="utf-8")
    meta = metadata(source)
    assert meta["workflow"] == "paper-to-kit"
    assert meta["version"] == "1"
    assert meta["side_effects"] == "proposals-only"
    assert meta["kit_writes"] == "0"
    assert meta["human_gate"] == "critical-only"
    # KIT-DR-035: only these four kinds of decision wait for a person, in the words of rituals.md.
    for kind in ("leaves the machine", "cannot be rebuilt", "untouchable folder",
                 "usage limit"):
        assert kind in source, kind
    assert "decision: ready" in source and "decision: pending" in source
    assert "paper:<arXiv id or DOI>" in source
    assert "experiment:PTK-<8HEX>-E01" in source


def test_paper_marker_contract_matches_evidence_schema():
    source = SOURCE.read_text(encoding="utf-8")
    schema = EVIDENCE_SCHEMA.read_text(encoding="utf-8")
    canonical = "`paper:<arXiv id or DOI>`"
    assert canonical in source
    assert canonical in schema
    assert "paper: <stable-paper-id-or-url>" not in source

    spec = importlib.util.spec_from_file_location("evidencecheck", str(EVIDENCECHECK))
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    pattern = checker.PAYLOAD["paper"]
    for valid in ("2609.09134", "2609.09134v2", "hep-th/9901001", "10.1000/example"):
        assert pattern.fullmatch(valid), valid
    for invalid in ("https://example.org/paper", "stable-paper-id", " 2609.09134"):
        assert not pattern.fullmatch(invalid), invalid


def test_manual_commands_stop_only_on_critical_kinds():
    """The garden and now skills act on reversible fixes and wait for the owner only on the critical kinds."""
    critical = ("leaves the machine", "cannot be rebuilt", "untouchable folder", "usage limit")
    for name in ("garden", "now"):
        text = " ".join((SKILLS / name / "SKILL.md").read_text(encoding="utf-8").split())
        assert "Execute nothing until after my decision" not in text, name
        assert "propose a repair for each warning" not in text, name
        if name == "garden":
            # The garden skill keeps no copy of the owner-question list; it defers to the one list in
            # rituals#memory, so the critical kinds must be named there.
            assert "system/rituals.md#memory" in text, name
            rituals = (ROOT / "system" / "rituals.md").read_text(encoding="utf-8")
            section = rituals.split('<a id="memory"></a>', 1)[1].split("<a id=", 1)[0]
            text += " " + " ".join(section.split())
        missing = [kind for kind in critical if kind not in text]
        assert not missing, (name, missing)


TESTS = (
    test_canonical_contract_is_machine_visible,
    test_paper_marker_contract_matches_evidence_schema,
    test_manual_commands_stop_only_on_critical_kinds,
)


if __name__ == "__main__":
    failed = []
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print("FAIL", test.__name__, type(error).__name__, error)
    print(f"skill parity: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
