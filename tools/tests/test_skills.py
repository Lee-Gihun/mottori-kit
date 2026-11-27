#!/usr/bin/env python3
"""Skills have one source folder each, and tools/skills.py copies it to the runtimes' folders."""

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "skills.py"
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import skills  # noqa: E402

NAME = re.compile(r"[a-z0-9-]{1,64}")


def run(root, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          cwd=root, env={"PATH": "/usr/bin:/bin", "MOTTORI_INSTANCE": str(root),
                                         "HOME": str(root), "PYTHONDONTWRITEBYTECODE": "1"})


def put(root, rel, text):
    path = pathlib.Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_write_copies_every_file_and_check_names_each_difference():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        assert run(root, "check").returncode == 0 and not run(root, "check").stdout, "no source: nothing"
        put(root, "system/skills/alpha/SKILL.md", '---\nname: alpha\ndescription: "A."\n---\n\nBody.\n')
        put(root, "system/skills/alpha/pages/one.md", "# one\n")
        put(root, ".claude/skills/mine/SKILL.md", "the owner's own skill\n")
        first = run(root, "check")
        assert first.returncode == 1, first.stdout
        for copy in (".claude/skills", ".agents/skills"):
            for rel in ("SKILL.md", "pages/one.md"):
                assert f"missing {copy}/alpha/{rel}\n" in first.stdout, first.stdout
        assert "python3 tools/skills.py write" in first.stdout, first.stdout
        assert "mine" not in first.stdout, first.stdout
        written = run(root, "write")
        assert written.returncode == 0 and written.stdout.count("wrote ") == 4, written.stdout
        for copy in (".claude/skills", ".agents/skills"):
            assert ((root / copy / "alpha/SKILL.md").read_bytes()
                    == (root / "system/skills/alpha/SKILL.md").read_bytes())
        clean = run(root, "check")
        assert clean.returncode == 0 and clean.stdout == "" and clean.stderr == "", clean

        # One changed byte, one deleted copy, one added file: each is named, and write undoes each.
        changed = root / ".agents/skills/alpha/SKILL.md"
        changed.write_bytes(changed.read_bytes().replace(b"Body.", b"Body!"))
        (root / ".claude/skills/alpha/pages/one.md").unlink()
        put(root, ".claude/skills/alpha/extra/stray.md", "not in the source\n")
        found = run(root, "check")
        assert found.returncode == 1, found.stdout
        assert found.stdout.splitlines()[:-1] == [
            "extra .claude/skills/alpha/extra/stray.md",
            "missing .claude/skills/alpha/pages/one.md",
            "different .agents/skills/alpha/SKILL.md"], found.stdout
        assert run(root, "write").returncode == 0
        assert run(root, "check").returncode == 0
        assert not (root / ".claude/skills/alpha/extra").exists(), "the emptied folder is removed"
        assert (root / ".claude/skills/mine/SKILL.md").read_text(encoding="utf-8") == "the owner's own skill\n"
        assert run(root, "nonsense").returncode == 2


def test_doctor_row_names_each_difference_and_the_fix():
    import doctor
    from unittest import mock
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        with mock.patch.object(doctor, "ROOT", str(root)):
            assert doctor.c_skills()[0] == doctor.PASS, "no skills: nothing to compare"
            put(root, "system/skills/alpha/SKILL.md", "x\n")
            status, detail = doctor.c_skills()
            assert status == doctor.WARN, (status, detail)
            assert "missing .claude/skills/alpha/SKILL.md" in detail, detail
            assert "python3 tools/skills.py write" in detail, detail
            skills.write(root)
            assert doctor.c_skills()[0] == doctor.PASS


def test_every_skill_has_the_two_front_matter_fields():
    """Each SKILL.md opens with front matter of exactly name (its folder's name) and description
    (a JSON string of at most 1024 characters)."""
    if not (ROOT / skills.SOURCE).is_dir():
        return
    found = sorted((ROOT / skills.SOURCE).glob("*/SKILL.md"))
    assert found, "a skills folder with no SKILL.md"
    for path in found:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), path
        head = text[4:].split("\n---\n", 1)[0].splitlines()
        assert [line.split(":", 1)[0] for line in head] == ["name", "description"], (path, head)
        name = head[0][len("name: "):]
        assert head[0].startswith("name: ") and name == path.parent.name and NAME.fullmatch(name), path
        raw = head[1][len("description: "):]
        assert head[1].startswith("description: ") and raw.startswith('"'), path
        description = json.loads(raw)
        assert isinstance(description, str) and 0 < len(description) <= 1024, path
    for folder in (ROOT / skills.SOURCE).iterdir():
        assert not folder.is_dir() or (folder / "SKILL.md").is_file(), folder


def test_this_trees_copies_match_their_sources():
    assert skills.differences(ROOT) == [], "run python3 tools/skills.py write"


def test_output_is_english():
    hangul = re.compile("[가-힣]")
    with tempfile.TemporaryDirectory() as tmp:
        put(tmp, "system/skills/alpha/SKILL.md", "x\n")
        text = run(tmp, "check").stdout + run(tmp, "write").stdout + run(tmp, "--help").stdout
        text += run(tmp, "nonsense").stderr
        assert not hangul.search(text) and "—" not in text, text


TESTS = [
    test_write_copies_every_file_and_check_names_each_difference,
    test_doctor_row_names_each_difference_and_the_fix,
    test_every_skill_has_the_two_front_matter_fields,
    test_this_trees_copies_match_their_sources,
    test_output_is_english,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"skills: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
