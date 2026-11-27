#!/usr/bin/env python3
"""Fail closed on Hangul in the kit's own text: the files system/dev/kit-files.txt lists, so an
installation's own files, in its owner's language, are never judged (KIT-DR-089).

The approved surfaces are marked evidence quotations with an ASCII English rendering,
test-fixture strings, ``"ko"`` values of template JSON, and the files in ``HANGUL_ALLOWED``.
Every other text file is scanned, and engine source outside the tests may not write Hangul as a
``\\u`` escape either. An allowed file that no longer holds Hangul fails, so the list only shrinks.
"""
from __future__ import annotations

import ast
import posixpath
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANGUL = re.compile(r"[\uac00-\ud7a3]")
# A Hangul syllable written as an escape in source text, such as \uac00.
HANGUL_ESCAPE = re.compile(r"\\u(?:a[c-f]|b[0-9a-f]|c[0-9a-f]|d[0-7])[0-9a-f]{2}", re.I)
# The rendering must be English: Hangul inside the parenthesis does not count.
ASCII_RENDERING = re.compile(r"\([^()\uac00-\ud7a3]*[A-Za-z][^()\uac00-\ud7a3]*\)")
TEXT_SUFFIXES = {".md", ".py", ".sh", ".js", ".json", ".yaml", ".yml", ".tsv", ".txt"}
# Files that may hold Hangul: engine source that reads Korean words in data people wrote.
HANGUL_ALLOWED = frozenset({
    "tools/lib/config.py",
    "tools/context_budget.py",
    "tools/dev/eval_recall.py",
    "tools/facts.py",
    "tools/now.py",
    "tools/lib/recall_store.py",
    "tools/lib/transcripts.py",
})
# Fixtures pass this so only their own files are judged.
NONE: frozenset[str] = frozenset()


# The kit's own files, one path a line; an installation adds files of its own beside them.
KIT_FILES = "system/dev/kit-files.txt"


def kit_files(root: Path) -> list[str] | None:
    """The paths the kit ships, from its list, or None for a tree without one (a test fixture)."""
    listing = root / KIT_FILES
    if not listing.is_file():
        return None
    return [line for line in listing.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


def engine_paths(root: Path) -> list[Path]:
    listed = kit_files(root)
    candidates = [root / rel for rel in listed] if listed is not None else list(root.rglob("*"))
    paths: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith((".git/", "_private/", "state/", "instance/")):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        paths.append(path)
    return sorted(paths)


def allowed_file_issues(root: Path, allowed: frozenset[str]) -> list[str]:
    """Report allowed files that are missing or no longer hold Hangul."""
    issues = []
    for rel in sorted(allowed):
        candidate = root / rel
        text = candidate.read_text(encoding="utf-8") if candidate.is_file() else ""
        if not (HANGUL.search(text) or HANGUL_ESCAPE.search(text)):
            issues.append(f"HANGUL_ALLOWED: entry has no Hangul: {rel}")
    return issues


def python_string_lines(path: Path) -> set[int]:
    """Return source lines occupied by string literals in a Python fixture."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            allowed.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return allowed


def shell_fixture_lines(path: Path) -> set[int]:
    """Allow Hangul only when every occurrence on a shell-test line is quoted."""
    allowed: set[int] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        quote = None
        quoted_positions = set()
        escaped = False
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                if quote:
                    quoted_positions.add(index)
                continue
            if char == "\\" and quote != "'":
                escaped = True
                continue
            if char in ("'", '\"'):
                if quote == char:
                    quote = None
                elif quote is None:
                    quote = char
                continue
            if quote:
                quoted_positions.add(index)
        hangul_positions = {match.start() for match in HANGUL.finditer(line)}
        if hangul_positions and hangul_positions <= quoted_positions:
            allowed.add(number)
    return allowed


def json_ko_lines(path: Path) -> set[int]:
    """Instance seed data under ``templates/``: Hangul is allowed only on lines carrying a ``"ko"`` value."""
    allowed: set[int] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.match(r'\s*"ko"\s*:', line):
            allowed.add(number)
    return allowed


def allowed_lines(path: Path, rel: str) -> set[int]:
    if rel.startswith("templates/") and rel.endswith(".json"):
        return json_ko_lines(path)
    if path.name.startswith("test_") or "/test_" in rel:
        if path.suffix == ".py":
            return python_string_lines(path)
        if path.suffix == ".sh":
            return shell_fixture_lines(path)
        return set()
    return set()


def is_engine_source(rel: str) -> bool:
    """True for code the kit runs: setup.sh and tools/, without the tests and their fixtures."""
    if rel == "setup.sh":
        return True
    name = posixpath.basename(rel)
    return (rel.startswith("tools/") and "/tests/" not in rel and not name.startswith("test_")
            and posixpath.splitext(rel)[1] in (".py", ".sh", ".js"))


def language_issues(root: Path = ROOT, allowed_files: frozenset[str] = HANGUL_ALLOWED) -> list[str]:
    issues = allowed_file_issues(root, allowed_files)
    for path in engine_paths(root):
        rel = path.relative_to(root).as_posix()
        if rel in allowed_files:
            continue
        allowed = allowed_lines(path, rel)
        lines = path.read_text(encoding="utf-8").splitlines()
        if is_engine_source(rel):
            issues.extend(f"{rel}:{number}: Hangul escape in engine source"
                          for number, line in enumerate(lines, 1) if HANGUL_ESCAPE.search(line))
        evidence_next = False
        for number, line in enumerate(lines, 1):
            if "language:evidence-ko" in line:
                evidence_next = True
                # The marker exempts only the next line, never Korean written beside it.
                if HANGUL.search(line) and number not in allowed:
                    issues.append(f"{rel}:{number}: Hangul outside an allowed surface")
                continue
            if not HANGUL.search(line):
                evidence_next = False
                continue
            if number in allowed:
                evidence_next = False
                continue
            if evidence_next:
                evidence_next = False
                if ASCII_RENDERING.search(line):
                    continue
                issues.append(f"{rel}:{number}: evidence quote lacks ASCII English rendering")
                continue
            issues.append(f"{rel}:{number}: Hangul outside an allowed surface")
            evidence_next = False
    return issues


def test_fixture_allowlist() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "test_sample.py").write_text(
            'EXPECTED = "테스트 문자열"\n# 한국어 주석은 허용하지 않는다\n', encoding="utf-8"
        )
        assert language_issues(root, NONE) == [
            "test_sample.py:2: Hangul outside an allowed surface"
        ]


def test_evidence_rendering_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence.md"
        evidence.write_text("language:evidence-ko\n> 한국어 (한국어)\n", encoding="utf-8")
        assert language_issues(root, NONE) == ["evidence.md:2: evidence quote lacks ASCII English rendering"]
        evidence.write_text("language:evidence-ko\n> 한국어 (English rendering)\n", encoding="utf-8")
        assert language_issues(root, NONE) == []
        evidence.write_text("language:evidence-ko 한국어 문장\n", encoding="utf-8")
        assert language_issues(root, NONE) == ["evidence.md:1: Hangul outside an allowed surface"]
        evidence.write_text("language:evidence-ko\n> 한국어 (한국어 a)\n", encoding="utf-8")
        assert language_issues(root, NONE) == ["evidence.md:2: evidence quote lacks ASCII English rendering"]


def test_allowed_surface_rules_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "tools").mkdir()
        (root / "tools" / "test_x.sh").write_text(
            'echo 한국어\necho "한국어"\n', encoding="utf-8"
        )
        (root / "tools" / "notes.py").write_text(
            'M = "\\uac8c\\uc774\\ud2b8"\nN = "English"\n', encoding="utf-8"
        )
        (root / "tools" / "tests").mkdir()
        (root / "tools" / "tests" / "fixture.py").write_text('M = "\\uac8c"\n', encoding="utf-8")
        assert sorted(language_issues(root, NONE)) == [
            "tools/notes.py:1: Hangul escape in engine source",
            "tools/test_x.sh:1: Hangul outside an allowed surface",
        ]


def test_allowed_files_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        allowed = frozenset({"legacy.md"})
        (root / "legacy.md").write_text("# 아직 이식 전\n", encoding="utf-8")
        assert language_issues(root, allowed) == []
        (root / "new.md").write_text("# 목록 밖 한글\n", encoding="utf-8")
        assert language_issues(root, allowed) == ["new.md:1: Hangul outside an allowed surface"]
        (root / "new.md").unlink()
        (root / "legacy.md").write_text("# Migrated\n", encoding="utf-8")
        assert language_issues(root, allowed) == ["HANGUL_ALLOWED: entry has no Hangul: legacy.md"]


def test_template_json_ko_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "templates").mkdir()
        target = root / "templates" / "seed.json"
        target.write_text('{\n  "ko": "한국어 값",\n  "en": "English value"\n}\n', encoding="utf-8")
        assert language_issues(root, NONE) == []
        target.write_text('{\n  "ko": "한국어 값",\n  "en": "한글 in the wrong key"\n}\n', encoding="utf-8")
        assert language_issues(root, NONE) == ["templates/seed.json:3: Hangul outside an allowed surface"]


def test_the_kit_file_list_names_every_tracked_file():
    """In the kit's own tree the list is exactly what Git tracks; an installation (it has an
    instance/config.json) adds files of its own, so there only the listed files must exist."""
    import subprocess
    listed = kit_files(ROOT)
    assert listed is not None, f"{KIT_FILES} is missing"
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    tracked = sorted(path for path in tracked if path)
    if (ROOT / "instance" / "config.json").is_file():
        gone = [rel for rel in listed if not (ROOT / rel).exists()]
        assert not gone, f"{KIT_FILES} names files this installation does not have: {gone[:10]}"
        print("- the kit file list: an installation, so its own files are left out")
        return
    assert sorted(listed) == tracked, ("the kit file list differs from what Git tracks; rewrite it with "
                                       f"`git ls-files > {KIT_FILES}`: missing "
                                       f"{sorted(set(tracked) - set(listed))[:10]}, extra {sorted(set(listed) - set(tracked))[:10]}")


def main() -> int:
    test_the_kit_file_list_names_every_tracked_file()
    test_template_json_ko_fixture()
    test_fixture_allowlist()
    test_evidence_rendering_fixture()
    test_allowed_surface_rules_fixture()
    test_allowed_files_fixture()
    issues = language_issues()
    for issue in issues:
        print(f"FAIL {issue}")
    if issues:
        print(f"language: FAIL ({len(issues)} issues; allowed files: {len(HANGUL_ALLOWED)})")
        return 1
    print(f"language: PASS (all surfaces accounted for; allowed files: {len(HANGUL_ALLOWED)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
