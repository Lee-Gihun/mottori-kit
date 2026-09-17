#!/usr/bin/env python3
"""Parity tests for canonical paper-to-kit runtime adapters."""

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "skill_adapters.py"
SOURCE = ROOT / "system" / "skills" / "paper-to-kit.md"
CLAUDE = ROOT / ".claude" / "commands" / "paper-to-kit.md"
EVIDENCE_SCHEMA = ROOT / "system" / "evidence-schema.md"
EVIDENCECHECK = ROOT / "tools" / "evidencecheck.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("skill_adapters", str(TOOL))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata(source):
    frontmatter = source.split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in frontmatter.splitlines() if ": " in line)


def test_canonical_contract_is_machine_visible():
    source = SOURCE.read_text(encoding="utf-8")
    meta = metadata(source)
    assert meta["workflow"] == "paper-to-kit"
    assert meta["version"] == "1"
    assert meta["side_effects"] == "proposals-only"
    assert meta["kit_writes"] == "0"
    assert meta["human_gate"] == "required"
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


def test_both_runtime_adapters_embed_exact_canonical_bytes():
    tool = load_tool()
    source = tool.read_source(SOURCE)
    for runtime in ("claude", "codex"):
        rendered = tool.render_adapter(runtime, source, tool.source_label(SOURCE))
        assert tool.extract_canonical(rendered) == source


def test_cli_generates_both_runtimes_and_detects_stale_output():
    temporary = pathlib.Path(tempfile.mkdtemp(prefix="skill-parity."))
    try:
        for runtime in ("claude", "codex"):
            output = temporary / runtime / ("command.md" if runtime == "claude" else "SKILL.md")
            made = subprocess.run(
                [sys.executable, str(TOOL), runtime, str(output)],
                cwd=str(ROOT), capture_output=True, text=True)
            assert made.returncode == 0, made.stdout + made.stderr
            checked = subprocess.run(
                [sys.executable, str(TOOL), runtime, str(output), "--check"],
                cwd=str(ROOT), capture_output=True, text=True)
            assert checked.returncode == 0 and "PASS" in checked.stdout
            output.write_text(output.read_text(encoding="utf-8") + "stale\n", encoding="utf-8")
            stale = subprocess.run(
                [sys.executable, str(TOOL), runtime, str(output), "--check"],
                cwd=str(ROOT), capture_output=True, text=True)
            assert stale.returncode == 1 and "STALE" in stale.stdout
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def test_committed_claude_adapter_has_exact_parity():
    checked = subprocess.run(
        [sys.executable, str(TOOL), "claude", str(CLAUDE), "--check"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr


TESTS = (
    test_canonical_contract_is_machine_visible,
    test_paper_marker_contract_matches_evidence_schema,
    test_both_runtime_adapters_embed_exact_canonical_bytes,
    test_cli_generates_both_runtimes_and_detects_stale_output,
    test_committed_claude_adapter_has_exact_parity,
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
