#!/usr/bin/env python3
"""Reference parsing in tools/linkcheck.py, run against isolated fixture repositories.

Markdown links must resolve exactly as a renderer would resolve them. Backticked
prose paths get two allowances: an editor-style ":line[:col]" suffix and resolution
against parent folders. A backticked path that resolves nowhere is still broken."""
import os
import shutil
import subprocess
import sys
import tempfile

from test_install_checks import make_repo as install_repo, run, write

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The modules linkcheck.py imports, besides those the shared fixture copies.
LINKCHECK_IMPORTS = ("lib/config.py", "lib/paths.py", "lib/runlog.py", "lib/safeio.py")

PASSED, FAILED = [], []


def ok(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("✓ " if cond else "✗ ") + name + (f": {detail}" if detail and not cond else ""))


def make_repo(with_config=True):
    """The shared fixture repository, with every module linkcheck.py imports."""
    root = install_repo(with_config=with_config)
    for name in LINKCHECK_IMPORTS:
        shutil.copy2(os.path.join(TOOLS, name), os.path.join(root, "tools", name))
    return root


def check(root, files):
    """Write and stage fixture documents, then return the checker's normal-mode result."""
    for rel, text in files.items():
        write(root, rel, text)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return run(root, "tools/linkcheck.py")


def broken_lines(result):
    return sorted(line for line in result.stdout.splitlines() if line.startswith("BROKEN "))


def test_markdown_link_typo_is_reported():
    root = make_repo(with_config=True)
    try:
        r = check(root, {"docs/guide.md": "# guide\n",
                         "README.md": "[guide](docs/guide.md) and [typo](docs/gide.md)\n"})
        ok("a Markdown link typo is broken and fails the run",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> docs/gide.md"], r.stdout)
        # A renderer resolves a link from its document, so a root-level namesake does not save it.
        r = check(root, {"docs/gide.md": "[back](README.md)\n"})
        ok("a nested link resolves from its document, not from the repository root",
           r.returncode == 1 and broken_lines(r) == ["BROKEN docs/gide.md -> README.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_angle_bracket_destinations_with_spaces():
    root = make_repo(with_config=True)
    try:
        r = check(root, {"my docs/a b.md": "# a b\n",
                         "README.md": "[ok](<my docs/a b.md#part>)\n"
                                      "[missing](<my docs/no such.md>)\n"
                                      "[plain](<my docs/a b.md>)\n"})
        ok("angle-bracket destinations are checked, spaces and fragments included",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> my docs/no such.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_inline_code_is_not_a_link():
    root = make_repo(with_config=True)
    try:
        r = check(root, {"README.md": "Call `AsType[E](e)` or `x[0](y)`; see [gone](gone.md).\n"})
        ok("bracket syntax inside inline code is not read as a link; a real link beside it is",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> gone.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    root = make_repo(with_config=True)
    try:
        # A code span closes only on a backtick run of the same length, so a single backtick
        # inside a double-backtick span, or an unmatched longer run, must not hide a later link.
        r = check(root, {"README.md": "Use ``foo`bar`` and [x](missing.md) or `y`.\n"
                                      "A ```lone run then [z](absent.md) and `w`.\n"})
        ok("a link after a double-backtick span or an unmatched backtick run is still checked",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> absent.md",
                                                     "BROKEN README.md -> missing.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    root = make_repo(with_config=True)
    try:
        # A backslash-escaped backtick is literal text and opens no span, so a renderer draws
        # both links; a backslash inside a span is literal and does not stop the span closing.
        r = check(root, {"README.md": "Escaped \\`tick [x](m1.md) and `z`.\n"
                                      "\\``foo` [y](m2.md) `w`.\n"
                                      "Code `a\\` then [v](m3.md) and `u`.\n"})
        ok("an escaped backtick opens no code span; a backslash inside a span is literal",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> m1.md",
                                                     "BROKEN README.md -> m2.md",
                                                     "BROKEN README.md -> m3.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_backticked_line_suffix():
    root = make_repo(with_config=True)
    try:
        r = check(root, {"lib/code.py": "pass\n",
                         "README.md": "See `lib/code.py:12` and `lib/code.py:12:5`.\n"
                                      "Also `lib/gone.py:3`.\n"})
        ok("backticked path:line and path:line:col resolve the path; a missing path stays broken",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> lib/gone.py"], r.stdout)
        r = check(root, {"README.md": "[jump](lib/code.py:12)\n"})
        ok("a Markdown link with a :line suffix stays strict",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> lib/code.py:12"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_backticked_path_resolves_against_parent_folders():
    root = make_repo(with_config=True)
    try:
        r = check(root, {"proj/lib/a.py": "pass\n",
                         "proj/notes/deep/log.md": "Run `lib/a.py` first.\n"})
        ok("a backticked path relative to a parent folder resolves",
           r.returncode == 0 and broken_lines(r) == [], r.stdout)
        r = check(root, {"proj/notes/deep/log.md": "Run [a](lib/a.py) first.\n"})
        ok("the same path as a Markdown link stays strict",
           r.returncode == 1 and broken_lines(r) == ["BROKEN proj/notes/deep/log.md -> lib/a.py"], r.stdout)
        r = check(root, {"proj/notes/deep/log.md": "Run `lib/a.py` and [a](lib/a.py).\n"})
        ok("a path written both ways is judged by the strict link rule",
           r.returncode == 1 and broken_lines(r) == ["BROKEN proj/notes/deep/log.md -> lib/a.py"], r.stdout)
        r = check(root, {"other/log.md": "Run `lib/a.py` first.\n"})
        ok("folders that are not ancestors are not searched",
           broken_lines(r) == ["BROKEN other/log.md -> lib/a.py",
                               "BROKEN proj/notes/deep/log.md -> lib/a.py"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_backticked_path_with_unknown_first_folder_is_broken():
    """A typo in the first folder of a backticked path must not be waved through as foreign."""
    root = make_repo(with_config=True)
    try:
        r = check(root, {"tools/real.py": "pass\n",
                         "README.md": "Run `tols/real.py` and `vendor/elsewhere/x.py`.\n"})
        ok("backticked paths whose first folder exists nowhere are broken",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> tols/real.py",
                                                     "BROKEN README.md -> vendor/elsewhere/x.py"], r.stdout)
        # The turn-end check of an installed instance blocks only on Markdown links: a code span
        # is an advisory row, and contributor folders are not read at all.
        write(root, "system/dev/record.md", "[gone](gone.md) and `tols/real.py`\n")
        write(root, "notes.md", "[gone](gone.md)\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py", "--issues", "--session")
        rows = [line.split("\t")[0] for line in r.stdout.splitlines()]
        ok("--session makes code spans advisory and skips contributor folders",
           r.returncode == 0 and rows == ["~README.md -> tols/real.py", "~README.md -> vendor/elsewhere/x.py",
                                          "notes.md -> gone.md", "#issues 1"], r.stdout)
        r = run(root, "tools/linkcheck.py", "--issues")
        ok("without --session a code span and a contributor document still count",
           r.stdout.splitlines()[-1] == "#issues 5", r.stdout)
        os.remove(os.path.join(root, "system/dev/record.md"))
        os.remove(os.path.join(root, "notes.md"))
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        # After setup a required instance file is broken even when its folder does not exist yet.
        # Split so the exporter's public wording substitution leaves this fixture unchanged.
        r = check(root, {"README.md": "Read `_private/state/NOW.md" "`.\n"})
        ok("a missing setup-created file under an absent folder is broken after setup",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> _private/state/NOW.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_capital_L_targets_are_checked():
    """Only L12-style line anchors are skipped; a file name that starts with L is a real target."""
    root = make_repo(with_config=True)
    try:
        r = check(root, {"README.md": "[lic](LICENSE.md) [lab](Lab.md) [x](L12873) [y](L3-L9)\n"})
        ok("missing files starting with a capital L are broken; line anchors are not",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> LICENSE.md",
                                                     "BROKEN README.md -> Lab.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unreadable_markdown_is_reported():
    """A Markdown file that is not UTF-8 must not pass silently with its links unchecked."""
    root = make_repo(with_config=True)
    try:
        os.makedirs(os.path.join(root, "docs"), exist_ok=True)
        with open(os.path.join(root, "docs", "bin.md"), "wb") as f:
            f.write(b"\xff\xfe[bad](nope.md)\n")
        r = check(root, {"README.md": "# ok\n"})
        ok("an undecodable Markdown file is reported and fails the run",
           r.returncode == 1 and broken_lines(r) == ["BROKEN docs/bin.md -> <unreadable>"], r.stdout)
        r = run(root, "tools/linkcheck.py", "--issues")
        ok("--issues lists the undecodable file too",
           any(line.startswith("docs/bin.md -> <unreadable>\t") for line in r.stdout.splitlines()),
           r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unstaged_deletion_is_not_broken():
    """A tracked file removed with plain rm is still listed by Git but is not a broken file."""
    root = make_repo(with_config=True)
    try:
        check(root, {"README.md": "# ok\n", "docs/old.md": "[a](../README.md)\n"})
        subprocess.run(["git", "-c", "user.email=f@example.invalid", "-c", "user.name=f",
                        "commit", "-q", "-m", "x"], cwd=root, check=True)
        os.remove(os.path.join(root, "docs", "old.md"))
        r = run(root, "tools/linkcheck.py")
        ok("a tracked file deleted without staging passes normal mode",
           r.returncode == 0 and broken_lines(r) == [], r.stdout)
        r = run(root, "tools/linkcheck.py", "--issues")
        ok("--issues lists nothing for the unstaged deletion",
           not any("old.md" in line for line in r.stdout.splitlines()), r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tree_run_records_no_certificate():
    """A --tree run reads other bytes than the live files, so it must not certify them."""
    root = make_repo(with_config=True)
    staged = tempfile.mkdtemp(prefix="linkcheck-tree.")
    try:
        check(root, {"README.md": "# clean\n"})
        write(staged, "README.md", "[gone](gone.md)\n")
        log = os.path.join(root, "state", ".tool-runs.log")
        before = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
        r = run(root, "tools/linkcheck.py", "--tree", staged)
        after = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
        added = [l for l in after[len(before):].splitlines() if "\tlinkcheck\t" in l]
        ok("a normal-mode --tree run reads the staged bytes but records no certificate",
           r.returncode == 1 and broken_lines(r) == ["BROKEN README.md -> gone.md"] and not added,
           r.stdout + repr(added))
        r = run(root, "tools/linkcheck.py")
        after2 = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
        ok("a live run still records its certificate",
           r.returncode == 0 and "\tlinkcheck\t" in after2[len(after):], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(staged, ignore_errors=True)


def test_files_setup_copies_are_pending_before_setup():
    """A fresh clone names the instance files setup.sh will copy; before setup they are pending, after it
    a missing one is broken."""
    doc = {"README.md": "See `instance/rules.md` and `instance/decisions.md`.\n"}
    root = make_repo(with_config=False)
    try:
        r = check(root, doc)
        pending = sorted(l.split("  (")[0] for l in r.stdout.splitlines() if l.startswith("PENDING "))
        ok("before setup, the instance files setup copies are pending, not broken",
           r.returncode == 0 and not broken_lines(r) and pending == [
               "PENDING README.md -> instance/decisions.md", "PENDING README.md -> instance/rules.md"],
           r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    root = make_repo(with_config=True)
    try:
        r = check(root, doc)
        ok("after setup, a missing instance file is broken",
           r.returncode == 1 and "BROKEN README.md -> instance/decisions.md" in broken_lines(r), r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_skill_links_only_inside_its_own_folder():
    """Each runtime reads a copy of one skill folder alone, so a link out of it would break there.
    Another file is named in code font instead, and that is still checked as a path."""
    root = make_repo(with_config=True)
    try:
        r = check(root, {
            "system/rituals.md": "# rituals\n",
            "system/skills/other/SKILL.md": "# other\n",
            "system/skills/alpha/guide.md": "# guide\n",
            "system/skills/alpha/pages/one.md": "[guide](../guide.md) and `system/rituals.md`\n",
            "system/skills/alpha/SKILL.md": "[one](pages/one.md), [rituals](../../rituals.md), "
                                            "[other](../other/SKILL.md), [web](https://example.invalid)\n"})
        ok("a link from a skill to a file outside its folder is broken although the file exists",
           r.returncode == 1 and broken_lines(r) == [
               "BROKEN system/skills/alpha/SKILL.md -> ../../rituals.md",
               "BROKEN system/skills/alpha/SKILL.md -> ../other/SKILL.md"], r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_plain_run_says_when_the_owners_own_folders_were_not_read():
    """In a kit installation Git lists none of the owner's folders, so a plain run did not read
    them. It says so, and says nothing where Git's list is the whole workspace."""
    root = make_repo(with_config=True)
    try:
        r = check(root, {"README.md": "# readme\n"})
        ok("a workspace whose files Git lists gets no note", "not in this run" not in r.stdout, r.stdout)
        # The kit's own rule: deny every top-level name, then restore the engine.
        write(root, ".gitignore", "/*\n!/.gitignore\n!/README.md\n!/tools/\n!/instance/\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        write(root, "notes/a.md", "[gone](missing.md)\n")
        write(root, "plan.md", "a top-level file\n")
        r = run(root, "tools/linkcheck.py")
        ok("a kit installation is told its own folders were not in the run",
           "not in this run: 2 top-level names of your own" in r.stdout and "linkcheck.py --mine" in r.stdout
           and not broken_lines(r), r.stdout)
        mine = run(root, "tools/linkcheck.py", "--mine")
        ok("--mine reads the owner's own folders and finds their broken link",
           mine.returncode == 1 and broken_lines(mine) == ["BROKEN notes/a.md -> missing.md"], mine.stdout)
        r = run(root, "tools/linkcheck.py", "--issues")
        ok("the machine-read form stays rows and a trailer", "not in this run" not in r.stdout, r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_markdown_link_typo_is_reported,
               test_angle_bracket_destinations_with_spaces,
               test_inline_code_is_not_a_link,
               test_backticked_line_suffix,
               test_backticked_path_resolves_against_parent_folders,
               test_backticked_path_with_unknown_first_folder_is_broken,
               test_capital_L_targets_are_checked,
               test_unreadable_markdown_is_reported,
               test_unstaged_deletion_is_not_broken,
               test_tree_run_records_no_certificate,
               test_files_setup_copies_are_pending_before_setup,
               test_a_skill_links_only_inside_its_own_folder,
               test_a_plain_run_says_when_the_owners_own_folders_were_not_read):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            FAILED.append(fn.__name__)
            print(f"✗ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"linkcheck: {len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(0 if not FAILED else 1)
