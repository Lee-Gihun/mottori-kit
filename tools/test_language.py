#!/usr/bin/env python3
"""Fail closed on Hangul outside approved categories or the migration backlog.

The five approved categories are i18n ``ko`` values, ``.ko.md`` files, marked
evidence quotations with an ASCII English rendering, test-fixture strings, and
historical CHANGELOG sections. Every other engine text file is scanned. A file
that has not migrated must appear in ``system/language-pending.txt``; stale
pending entries fail. Required locale pairs are enumerated in both directions.
"""
from __future__ import annotations

import ast
import re
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HANGUL = re.compile(r"[\uac00-\ud7a3]")
ASCII_RENDERING = re.compile(r"\([^()]*[A-Za-z][^()]*\)")
TEXT_SUFFIXES = {".md", ".py", ".sh", ".js", ".json", ".yaml", ".yml", ".tsv", ".txt"}
INSTANCE_PATHS = {
    "system/decisions.md",
    "system/instance-rules.md",
    "system/memory-config.json",
    "system/rituals.local.md",
}
PENDING_PATH = "system/language-pending.txt"
REQUIRED_LOCALE_PAIRS = {
    ".claude/commands/dossier.md",
    ".claude/commands/garden.md",
    ".claude/commands/now.md",
    ".claude/commands/paper-to-kit.md",
    ".claude/commands/recall.md",
    "AGENTS.md",
    "CHANGELOG.md",
    "CHECKLIST.md",
    "README.md",
    "SETUP.md",
    "system/PRD-info-architecture.md",
    "system/PRD-session-memory.md",
    "system/WORKING-WITH-AI.md",
    "system/deep-pass.md",
    "system/enforcement-matrix.md",
    "system/evidence-schema.md",
    "system/kit-decisions.md",
    "system/lenses/README.md",
    "system/lenses/ergodic.md",
    "system/lenses/feedback-loop.md",
    "system/lenses/fence.md",
    "system/lenses/feynman.md",
    "system/lenses/incentive.md",
    "system/lenses/inversion.md",
    "system/lenses/isomorphism.md",
    "system/lenses/jensen.md",
    "system/lenses/ledger.md",
    "system/lenses/limits.md",
    "system/lenses/marginal.md",
    "system/lenses/mirror.md",
    "system/lenses/silence.md",
    "system/person-ledger.md",
    "system/reviews/architecture.md",
    "system/rituals.md",
    "system/skills/paper-to-kit.md",
    "templates/decisions.md",
    "templates/instance-rules.md",
    "templates/rituals.local.md",
}


def engine_paths(root: Path) -> list[Path]:
    candidates = list(root.rglob("*"))
    paths: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith((".git/", "_private/", "state/")):
            continue
        if rel in INSTANCE_PATHS or rel.startswith("system/debate/_"):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        paths.append(path)
    return sorted(paths)


def pending_paths(root: Path) -> tuple[set[str], list[str]]:
    path = root / PENDING_PATH
    if not path.is_file():
        return set(), [f"{PENDING_PATH}: pending-file missing"]
    entries: set[str] = set()
    issues: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        rel = raw.strip()
        if not rel or rel.startswith("#"):
            continue
        if rel in entries:
            issues.append(f"{PENDING_PATH}:{number}: duplicate pending entry: {rel}")
            continue
        entries.add(rel)
        candidate = root / rel
        if not candidate.is_file() or not HANGUL.search(candidate.read_text(encoding="utf-8")):
            issues.append(f"{PENDING_PATH}:{number}: stale pending entry has no Hangul: {rel}")
    return entries, issues


def ko_value_lines(path: Path) -> set[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "ko":
                allowed.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))
    return allowed


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


def historical_changelog_lines(path: Path) -> set[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    versions = [number for number, line in enumerate(lines, 1) if re.match(r"^##\s+v\d", line)]
    return set() if len(versions) < 2 else set(range(versions[1], len(lines) + 1))


def allowed_lines(path: Path, rel: str) -> set[int] | None:
    if rel.endswith(".ko.md"):
        return None
    if path.name.startswith("test_") or "/test_" in rel:
        if path.suffix == ".py":
            return python_string_lines(path)
        if path.suffix == ".sh":
            return shell_fixture_lines(path)
        return set()
    if rel == "tools/i18n.py":
        return ko_value_lines(path)
    if rel == "CHANGELOG.md":
        return historical_changelog_lines(path)
    return set()


def language_issues(root: Path = ROOT) -> list[str]:
    pending, issues = pending_paths(root)
    for path in engine_paths(root):
        rel = path.relative_to(root).as_posix()
        if rel in pending:
            continue
        allowed = allowed_lines(path, rel)
        if allowed is None:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        evidence_next = False
        for number, line in enumerate(lines, 1):
            if "language:evidence-ko" in line:
                evidence_next = True
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


def markdown_links(text: str) -> set[str]:
    return {
        target.split("#", 1)[0]
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)
        if target and not re.match(r"(?:https?|mailto):", target)
    }


def heading_shape(text: str) -> tuple[int, ...]:
    return tuple(len(match.group(1)) for match in re.finditer(r"^(#{1,6})\s+\S", text, re.MULTILINE))


def locale_path(canonical: Path) -> Path:
    return canonical.with_name(canonical.stem + ".ko.md")


def locale_pair_issues(root: Path = ROOT, required_pairs: set[str] | None = None) -> list[str]:
    issues: list[str] = []
    required = REQUIRED_LOCALE_PAIRS if required_pairs is None else required_pairs
    canonical_paths = {root / rel for rel in required}
    canonical_paths.update(
        locale.with_name(locale.name[:-len(".ko.md")] + ".md")
        for locale in engine_paths(root)
        if locale.name.endswith(".ko.md")
    )
    for canonical in sorted(canonical_paths):
        rel = canonical.relative_to(root).as_posix()
        locale = locale_path(canonical)
        if not canonical.is_file():
            issues.append(f"{rel}: required canonical file missing")
            continue
        if not locale.is_file():
            issues.append(f"{rel}: required locale file missing: {locale.name}")
            continue
        ko_text = locale.read_text(encoding="utf-8")
        en_text = canonical.read_text(encoding="utf-8")
        if not heading_shape(ko_text) or not heading_shape(en_text):
            issues.append(f"{rel}: both locale files must have a title")
        elif heading_shape(ko_text) != heading_shape(en_text):
            issues.append(f"{rel}: locale heading hierarchy differs from canonical file")
        if markdown_links(ko_text) != markdown_links(en_text):
            issues.append(f"{rel}: locale relative Markdown links differ from canonical file")
    return issues


def test_pair_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        required = {"guide.md"}
        (root / "guide.md").write_text("# Guide\n\n[Setup](SETUP.md)\n", encoding="utf-8")
        (root / "guide.ko.md").write_text("# Guide locale\n\n[Setup](SETUP.md)\n", encoding="utf-8")
        assert locale_pair_issues(root, required) == []
        (root / "guide.ko.md").write_text("## Guide locale\n\n[Other](OTHER.md)\n", encoding="utf-8")
        assert len(locale_pair_issues(root, required)) == 2
        (root / "guide.ko.md").unlink()
        assert locale_pair_issues(root, required) == ["guide.md: required locale file missing: guide.ko.md"]
        (root / "guide.ko.md").write_text("# Guide locale\n", encoding="utf-8")
        (root / "guide.md").unlink()
        assert locale_pair_issues(root, required) == ["guide.md: required canonical file missing"]


def write_pending(root: Path, entries: str = "") -> None:
    (root / "system").mkdir(exist_ok=True)
    (root / PENDING_PATH).write_text(entries, encoding="utf-8")


def test_fixture_allowlist() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        (root / "test_sample.py").write_text(
            'EXPECTED = "테스트 문자열"\n# 한국어 주석은 허용하지 않는다\n', encoding="utf-8"
        )
        assert language_issues(root) == [
            "test_sample.py:2: Hangul outside an allowed surface"
        ]


def test_evidence_rendering_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        evidence = root / "evidence.md"
        evidence.write_text("language:evidence-ko\n> 한국어 (한국어)\n", encoding="utf-8")
        assert language_issues(root) == ["evidence.md:2: evidence quote lacks ASCII English rendering"]
        evidence.write_text("language:evidence-ko\n> 한국어 (English rendering)\n", encoding="utf-8")
        assert language_issues(root) == []


def test_pending_contract_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root, "legacy.md\n")
        (root / "legacy.md").write_text("# 아직 이식 전\n", encoding="utf-8")
        assert language_issues(root) == []
        (root / "new.md").write_text("# 목록 밖 한글\n", encoding="utf-8")
        assert language_issues(root) == ["new.md:1: Hangul outside an allowed surface"]
        (root / "new.md").unlink()
        (root / "legacy.md").write_text("# Migrated\n", encoding="utf-8")
        assert language_issues(root) == [
            "system/language-pending.txt:1: stale pending entry has no Hangul: legacy.md"
        ]


def main() -> int:
    test_pair_fixture()
    test_fixture_allowlist()
    test_evidence_rendering_fixture()
    test_pending_contract_fixture()
    pending, _ = pending_paths(ROOT)
    issues = language_issues() + locale_pair_issues()
    for issue in issues:
        print(f"FAIL {issue}")
    if issues:
        print(f"language: FAIL ({len(issues)} issues; pending files: {len(pending)})")
        return 1
    print(f"language: PASS (all surfaces accounted for; pending files: {len(pending)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
