#!/usr/bin/env python3
"""Fail closed on Hangul, locale drift, and ``tools/i18n_stamp.py`` failures.

The five approved categories are i18n ``ko`` values, files under ``ko/``, marked
evidence quotations with an ASCII English rendering, test-fixture strings, and
historical CHANGELOG sections. Every other engine text file is scanned. A file
that has not migrated must appear in ``system/language-pending.txt``; stale
pending entries fail. Required locale pairs are enumerated in both directions: the
English file ``X.md`` pairs with the Korean file ``ko/X.md``.
"""
from __future__ import annotations

import ast
import contextlib
import io
import posixpath
import re
import tempfile
from pathlib import Path

from testlib import run_test

import i18n_stamp


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
REQUIRED_LOCALE_PAIRS = i18n_stamp.REQUIRED_LOCALE_PAIRS
LOCALE_PREFIX = i18n_stamp.LOCALE_DIR + "/"


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


def json_ko_lines(path: Path) -> set[int]:
    """Instance seed data under ``templates/``: Hangul is allowed only on lines carrying a ``"ko"`` value,
    the same contract as the ``ko`` column of ``tools/i18n.py``."""
    allowed: set[int] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.match(r'\s*"ko"\s*:', line):
            allowed.add(number)
    return allowed


def allowed_lines(path: Path, rel: str) -> set[int] | None:
    if rel.startswith(LOCALE_PREFIX):
        return None
    if rel.startswith("templates/") and rel.endswith(".json"):
        return json_ko_lines(path)
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


def resolved_links(text: str, rel: str) -> set[str]:
    """Resolve a document's relative links to repository paths, folding ko/ onto English paths.

    A Korean file at ``ko/X.md`` links to ``ko/Y.md`` where the English file links to ``Y.md``,
    and to ``../Y.md`` when ``Y.md`` has no Korean version. Both resolve to ``Y.md`` here, so the
    two files of a pair compare equal when they reach the same documents.
    """
    base = posixpath.dirname(rel)
    found = set()
    for target in markdown_links(text):
        if not target:
            continue
        path = posixpath.normpath(posixpath.join(base, target))
        found.add(path[len(LOCALE_PREFIX):] if path.startswith(LOCALE_PREFIX) else path)
    return found


def english_link_issues(root: Path, rel: str, text: str) -> list[str]:
    """Report links from a Korean file to an English file that has a Korean version under ko/."""
    base = posixpath.dirname(rel)
    issues = []
    for target in sorted(markdown_links(text)):
        if not target:
            continue
        path = posixpath.normpath(posixpath.join(base, target))
        if path.startswith(LOCALE_PREFIX) or path.startswith("../"):
            continue
        if (root / path).is_file() and (root / (LOCALE_PREFIX + path)).is_file():
            issues.append(f"{rel}: link {target} reaches the English file; use {LOCALE_PREFIX}{path}")
    return issues


def heading_shape(text: str) -> tuple[int, ...]:
    return tuple(len(match.group(1)) for match in re.finditer(r"^(#{1,6})\s+\S", text, re.MULTILINE))


def locale_pair_issues(root: Path = ROOT, required_pairs: set[str] | None = None) -> list[str]:
    issues: list[str] = []
    required = REQUIRED_LOCALE_PAIRS if required_pairs is None else required_pairs
    for rel in i18n_stamp.canonical_set(root, required):
        canonical = root / rel
        locale_rel = i18n_stamp.locale_rel(rel)
        locale = root / locale_rel
        if not canonical.is_file():
            issues.append(f"{rel}: required canonical file missing")
            continue
        if not locale.is_file():
            issues.append(f"{rel}: required locale file missing: {locale_rel}")
            continue
        ko_text = locale.read_text(encoding="utf-8")
        en_text = canonical.read_text(encoding="utf-8")
        if not heading_shape(ko_text) or not heading_shape(en_text):
            issues.append(f"{rel}: both locale files must have a title")
        elif heading_shape(ko_text) != heading_shape(en_text):
            issues.append(f"{rel}: locale heading hierarchy differs from canonical file")
        if resolved_links(ko_text, locale_rel) != resolved_links(en_text, rel):
            issues.append(f"{rel}: locale relative Markdown links differ from canonical file")
        issues.extend(english_link_issues(root, locale_rel, ko_text))
    issues.extend(
        item.message
        for item in i18n_stamp.check(root, required).stale
        if item.source is not None and (root / item.source).is_file() and (root / item.target).is_file()
    )
    return issues


def test_pair_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        required = {"guide.md"}
        (root / "ko").mkdir()
        (root / "guide.md").write_text("# Guide\n\n[Setup](SETUP.md)\n", encoding="utf-8")
        (root / "ko" / "guide.md").write_text("# Guide locale\n\n[Setup](../SETUP.md)\n", encoding="utf-8")
        i18n_stamp.bind(root / "ko" / "guide.md", root)
        assert locale_pair_issues(root, required) == []
        (root / "ko" / "guide.md").write_text("## Guide locale\n\n[Other](../OTHER.md)\n", encoding="utf-8")
        i18n_stamp.bind(root / "ko" / "guide.md", root)
        assert len(locale_pair_issues(root, required)) == 2
        (root / "ko" / "guide.md").unlink()
        assert locale_pair_issues(root, required) == ["guide.md: required locale file missing: ko/guide.md"]
        (root / "ko" / "guide.md").write_text("# Guide locale\n", encoding="utf-8")
        (root / "guide.md").unlink()
        assert locale_pair_issues(root, required) == ["guide.md: required canonical file missing"]


def test_stamp_bind_and_source_drift_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        source = root / "guide.md"
        target = root / "ko" / "guide.md"
        target.parent.mkdir()
        source.write_text("# Guide\n", encoding="utf-8")
        target.write_text("# Guide locale\n", encoding="utf-8")
        i18n_stamp.bind(target, root)
        assert i18n_stamp.check(root, {"guide.md"}).stale == ()
        assert re.fullmatch(
            r"<!-- source: guide\.md sha256:[0-9a-f]{64} source-of-truth: en -->",
            target.read_text(encoding="utf-8").splitlines()[0],
        )
        source.write_text("# Changed guide\n", encoding="utf-8")
        report = i18n_stamp.check(root, {"guide.md"})
        assert len(report.stale) == 1
        assert "source hash changed" in report.stale[0].message
        pending = "\n".join(sorted(REQUIRED_LOCALE_PAIRS - {"guide.md"})) + "\n"
        write_pending(root, pending)
        with contextlib.redirect_stdout(io.StringIO()):
            assert i18n_stamp.main(["--root", str(root), "check"]) == 1


def test_stamp_pending_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root, "legacy.md\n")
        (root / "legacy.md").write_text("# 아직 번역 전\n", encoding="utf-8")
        report = i18n_stamp.check(root, {"legacy.md"}, {"legacy.md": "pending"})
        assert report.stale == ()
        assert report.pending == ("legacy.md",)


def test_stamp_completed_pair_cannot_be_downgraded_by_pending_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        source = root / "guide.md"
        target = root / "ko" / "guide.md"
        target.parent.mkdir()
        source.write_text("# Guide\n", encoding="utf-8")
        target.write_text("# Guide locale\n", encoding="utf-8")
        i18n_stamp.bind(target, root)
        target.write_text("# Guide locale\n", encoding="utf-8")
        write_pending(root, "guide.md\n")
        report = i18n_stamp.check(root, {"guide.md"})
        assert len(report.stale) == 1
        assert report.stale[0].message == (
            "ko/guide.md: completed pair cannot be pending without an explicit inventory transition"
        )


def test_stamp_missing_required_pair_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        (root / "guide.md").write_text("# Guide\n", encoding="utf-8")
        report = i18n_stamp.check(root, {"guide.md"})
        assert len(report.stale) == 1
        assert report.stale[0].message == "ko/guide.md: translated file missing"


def test_stamp_korean_source_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        lens_dir = root / "system" / "lenses"
        lens_dir.mkdir(parents=True)
        source = root / "ko" / "system" / "lenses" / "feynman.md"
        source.parent.mkdir(parents=True)
        target = lens_dir / "feynman.md"
        source.write_text("# 원천\n", encoding="utf-8")
        target.write_text("# Source\n", encoding="utf-8")
        i18n_stamp.bind(target, root)
        assert i18n_stamp.check(root, {"system/lenses/feynman.md"}).stale == ()
        assert "source: ko/system/lenses/feynman.md" in target.read_text(encoding="utf-8").splitlines()[0]
        assert "source-of-truth: ko" in target.read_text(encoding="utf-8").splitlines()[0]


def test_stamp_newline_and_trailing_space_normalization_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        source = root / "guide.md"
        target = root / "ko" / "guide.md"
        target.parent.mkdir()
        source.write_bytes(b"# Guide\r\n\r\nBody\r\n")
        target.write_text("# Guide locale\n\nBody\n", encoding="utf-8")
        i18n_stamp.bind(target, root)
        source.write_bytes(b"# Guide\n\nBody\n")
        assert i18n_stamp.check(root, {"guide.md"}).stale == ()
        source.write_bytes(b"# Guide  \n\nBody\n")
        report = i18n_stamp.check(root, {"guide.md"})
        assert len(report.stale) == 1
        assert "source hash changed" in report.stale[0].message


def test_pair_index_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root, "legacy.md\n")
        (root / "ko").mkdir()
        (root / "guide.md").write_text("# Guide\n", encoding="utf-8")
        (root / "ko" / "guide.md").write_text("# Guide locale\n", encoding="utf-8")
        (root / "legacy.md").write_text("# 아직 번역 전\n", encoding="utf-8")
        required = {"guide.md", "legacy.md"}
        states = {"guide.md": "completed", "legacy.md": "pending"}
        assert i18n_stamp.check(root, required, states).index == (
            "ko/INDEX.md: pair index missing; run python3 tools/i18n_stamp.py index",
        )
        i18n_stamp.bind(root / "ko" / "guide.md", root)
        index = i18n_stamp.write_index(root, required, states)
        rows = [line for line in index.read_text(encoding="utf-8").splitlines() if line.startswith("| [")]
        assert rows == [
            "| [guide.md](../guide.md) | [ko/guide.md](guide.md) | en | current |",
            "| [legacy.md](../legacy.md) | [ko/legacy.md](legacy.md) | en | pending |",
        ]
        assert i18n_stamp.check(root, required, states).index == ()
        index.write_text(index.read_text(encoding="utf-8").replace("| current |", "| pending |"), encoding="utf-8")
        assert i18n_stamp.check(root, required, states).index == (
            "ko/INDEX.md: pair index differs from the files; run python3 tools/i18n_stamp.py index",
        )
        i18n_stamp.write_index(root, required, states)
        (root / "guide.md").write_text("# Changed guide\n", encoding="utf-8")
        report = i18n_stamp.check(root, required, states)
        assert len(report.stale) == 1 and len(report.index) == 1
        i18n_stamp.bind(root / "ko" / "guide.md", root)
        assert i18n_stamp.check(root, required, states).index == ()
        (root / "ko" / "extra.md").write_text("# Extra\n", encoding="utf-8")
        assert len(i18n_stamp.check(root, required, states).index) == 1


def test_korean_link_to_english_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root)
        (root / "ko").mkdir()
        (root / "notes.md").write_text("# Notes\n", encoding="utf-8")
        (root / "guide.md").write_text("# Guide\n\n[Setup](SETUP.md) [Notes](notes.md)\n", encoding="utf-8")
        (root / "SETUP.md").write_text("# Setup\n", encoding="utf-8")
        (root / "ko" / "SETUP.md").write_text("# Setup locale\n", encoding="utf-8")
        (root / "ko" / "guide.md").write_text(
            "# Guide locale\n\n[Setup](../SETUP.md) [Notes](../notes.md)\n", encoding="utf-8"
        )
        for target in ("ko/guide.md", "ko/SETUP.md"):
            i18n_stamp.bind(root / target, root)
        required = {"guide.md", "SETUP.md"}
        assert locale_pair_issues(root, required) == [
            "ko/guide.md: link ../SETUP.md reaches the English file; use ko/SETUP.md"
        ]
        (root / "ko" / "guide.md").write_text(
            "# Guide locale\n\n[Setup](SETUP.md) [Notes](../notes.md)\n", encoding="utf-8"
        )
        i18n_stamp.bind(root / "ko" / "guide.md", root)
        assert locale_pair_issues(root, required) == []


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


def test_template_json_ko_fixture() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_pending(root, "")
        (root / "templates").mkdir()
        target = root / "templates" / "seed.json"
        target.write_text('{\n  "ko": "한국어 값",\n  "en": "English value"\n}\n', encoding="utf-8")
        assert language_issues(root) == []
        target.write_text('{\n  "ko": "한국어 값",\n  "en": "한글 in the wrong key"\n}\n', encoding="utf-8")
        assert language_issues(root) == ["templates/seed.json:3: Hangul outside an allowed surface"]


def main() -> int:
    run_test(test_template_json_ko_fixture, __file__)
    run_test(test_pair_fixture, __file__)
    run_test(test_stamp_bind_and_source_drift_fixture, __file__)
    run_test(test_stamp_pending_fixture, __file__)
    run_test(test_stamp_completed_pair_cannot_be_downgraded_by_pending_fixture, __file__)
    run_test(test_stamp_missing_required_pair_fixture, __file__)
    run_test(test_stamp_korean_source_fixture, __file__)
    run_test(test_stamp_newline_and_trailing_space_normalization_fixture, __file__)
    run_test(test_pair_index_fixture, __file__)
    run_test(test_korean_link_to_english_fixture, __file__)
    run_test(test_fixture_allowlist, __file__)
    run_test(test_evidence_rendering_fixture, __file__)
    run_test(test_pending_contract_fixture, __file__)
    pending, _ = pending_paths(ROOT)
    issues = language_issues() + locale_pair_issues() + list(i18n_stamp.check().index)
    for issue in issues:
        print(f"FAIL {issue}")
    if issues:
        print(f"language: FAIL ({len(issues)} issues; pending files: {len(pending)})")
        return 1
    print(f"language: PASS (all surfaces accounted for; pending files: {len(pending)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
