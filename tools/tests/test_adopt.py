#!/usr/bin/env python3
"""tools/adopt.py takes a folder as it is: its old broken links stop no turn, a link broken later
still does, and nothing in the folder is changed.

Each case runs the real command against a scratch workspace root named by MOTTORI_INSTANCE.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]

import adopted  # noqa: E402
import gate  # noqa: E402


@contextlib.contextmanager
def workspace():
    """Yield a scratch workspace root holding one folder of old material."""
    parent = Path(tempfile.mkdtemp(prefix="adopt-"))
    root = parent / "ws"
    try:
        (root / "instance").mkdir(parents=True)
        (root / "instance/config.json").write_text(json.dumps(
            {"schema_version": 4, "instance": {"name": "fixture"},
             "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                                    "legacy_public_tracks": []}}) + "\n", encoding="utf-8")
        notes = root / "notes"
        (notes / "sub").mkdir(parents=True)
        (notes / "plan.md").write_text("# Old plan\n\n[budget](budget.md) [n](sub/n1.md)\n",
                                       encoding="utf-8")
        (notes / "sub/n1.md").write_text("# n1\n\n[gone](../missing.md)\n", encoding="utf-8")
        (notes / "CLAUDE.md").write_text("# Old rules\n", encoding="utf-8")
        (notes / "site/.git").mkdir(parents=True)
        (notes / "site/index.html").write_text("x\n", encoding="utf-8")
        yield root
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def adopt(root, *args):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root))
    return subprocess.run([sys.executable, os.path.join(TOOLS, "adopt.py"), *args], cwd=root, env=env,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def snapshot(folder):
    """Every file under folder with its bytes, to show that a run changed nothing in it."""
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def record(root):
    return json.loads((root / "state/.gate-adopted.json").read_text(encoding="utf-8"))


def test_adopting_records_the_broken_links_and_changes_nothing_in_the_folder():
    with workspace() as root:
        before = snapshot(root / "notes")
        done = adopt(root, "notes")
        assert done.returncode == 0, done.stderr
        assert snapshot(root / "notes") == before
        assert record(root)["linkcheck"] == ["notes/plan.md -> budget.md",
                                             "notes/sub/n1.md -> ../missing.md"]
        assert record(root)["folders"]["notes"]["broken_links"] == 2
        assert "links already broken: 2" in done.stdout
        assert "Nothing in the folder was moved, renamed or edited." in done.stdout


def test_report_names_instruction_files_and_repositories_inside():
    with workspace() as root:
        out = adopt(root, "notes").stdout
        assert "notes/CLAUDE.md" in out and "instance/rules.md" in out, out
        assert "notes/site" in out and "Git repositories inside" in out, out
        page = (root / "_private/state/adopt-notes.md").read_text(encoding="utf-8")
        assert "`notes/plan.md`: Old plan" in page and "`notes/CLAUDE.md`" in page, page
        # The instruction file is reported, not listed as one of the owner's documents.
        assert "notes/CLAUDE.md`:" not in page, page


def test_dry_run_writes_nothing():
    with workspace() as root:
        done = adopt(root, "notes", "--dry")
        assert done.returncode == 0 and "would be recorded" in done.stdout, done.stdout
        assert not (root / "state").exists() and not (root / "_private").exists()


def test_second_run_drops_fixed_links_and_does_not_accept_new_ones():
    with workspace() as root:
        adopt(root, "notes")
        (root / "notes/budget.md").write_text("# Budget\n", encoding="utf-8")
        with (root / "notes/plan.md").open("a", encoding="utf-8") as plan:
            plan.write("[new](not-there.md)\n")
        done = adopt(root, "notes")
        assert record(root)["linkcheck"] == ["notes/sub/n1.md -> ../missing.md"], record(root)
        assert "links broken since the folder was adopted: 1" in done.stdout, done.stdout
        assert "notes/plan.md -> not-there.md" in done.stdout
        again = adopt(root, "notes", "--again")
        assert again.returncode == 0
        assert record(root)["linkcheck"] == ["notes/plan.md -> not-there.md",
                                             "notes/sub/n1.md -> ../missing.md"]


def test_another_folder_keeps_its_record():
    with workspace() as root:
        (root / "other").mkdir()
        (root / "other/a.md").write_text("[x](nope.md)\n", encoding="utf-8")
        adopt(root, "notes")
        adopt(root, "other")
        assert sorted(record(root)["folders"]) == ["notes", "other"]
        assert "other/a.md -> nope.md" in record(root)["linkcheck"]
        assert "notes/plan.md -> budget.md" in record(root)["linkcheck"]
        listed = adopt(root).stdout
        assert "notes/: adopted" in listed and "other/: adopted" in listed, listed


def test_refuses_what_is_not_a_folder_of_the_owner():
    with workspace() as root:
        (root / "tools").mkdir()
        for argument, word in (("tools", "belongs to the kit"), (".", "not the workspace itself"),
                               ("/usr", "is not inside this workspace"), ("nowhere", "no such folder")):
            done = adopt(root, argument)
            assert done.returncode != 0 and word in done.stderr, (argument, done.stderr)
        assert not (root / "state").exists()


def test_a_repository_outside_is_told_to_stay_where_it_is():
    with workspace() as root:
        repository = root.parent / "api"
        (repository / ".git").mkdir(parents=True)
        done = adopt(root, str(repository))
        assert done.returncode != 0 and "Leave it where it is" in done.stderr, done.stderr
        assert "--add-dir" in done.stderr and "mv " not in done.stderr, done.stderr
        assert repository.is_dir() and not (root / "state").exists()


def test_a_link_is_not_followed_out_of_the_folder():
    with workspace() as root:
        outside = root.parent / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("[x](gone.md)\n", encoding="utf-8")
        os.symlink(outside, root / "notes/linked")
        done = adopt(root, "notes")
        assert done.returncode == 0
        assert not any("linked" in i for i in record(root)["linkcheck"]), record(root)
        assert "secret" not in (root / "_private/state/adopt-notes.md").read_text(encoding="utf-8")


def test_the_turn_end_check_reads_the_same_issue_ids():
    """The record must name issues the way the gate's own link check names them, or it adopts
    nothing."""
    with workspace() as root:
        adopt(root, "notes")
        listing = root.parent / "list.txt"
        listing.write_text("notes/plan.md\nnotes/sub/n1.md\n", encoding="utf-8")
        checked = gate._issues(dict(gate.CHECKS)["linkcheck"] + ["--filelist", str(listing)],
                               cwd=str(root), instance=str(root))
        assert checked.ids == set(record(root)["linkcheck"]), checked


def test_an_adopted_link_is_not_this_turns_issue_and_a_new_one_is():
    with workspace() as root:
        adopt(root, "notes")
        old = {"notes/plan.md -> budget.md"}

        def issues(cmd, **_):
            return gate.Checked(set(old) if "--filelist" in cmd else set())

        with patch.dict(os.environ, {"MOTTORI_INSTANCE": str(root)}), patch.object(gate, "_issues", issues):
            calm = gate.measure(edited=["notes/plan.md"])
            assert calm.ids["linkcheck"] == set() and calm.edited_only == frozenset(), calm
            old.add("notes/plan.md -> not-there.md")
            cur = gate.measure(edited=["notes/plan.md"])
            assert cur.edited_only == {"notes/plan.md -> not-there.md"}, cur
            reason, _ = gate._verdict(cur, {"linkcheck": set(), "now-check": set()}, "ok")
            # Inside an adopted folder the link is new, so the block does not offer adoption.
            assert reason == gate.NEW_ISSUES.format(
                detail="linkcheck: notes/plan.md -> not-there.md", tail=gate.TAIL_EDITED), reason
            assert adopted.covers("notes/plan.md") and not adopted.covers("fresh/a.md")


def test_a_repaired_adopted_link_loses_its_excuse():
    """An adopted broken link that a measured turn no longer finds is retired from the record, so a
    later break of the same link is that turn's issue."""
    with workspace() as root:
        adopt(root, "notes")
        broken = {"notes/plan.md -> budget.md"}

        def issues(cmd, **_):
            return gate.Checked(set(broken) if "--filelist" in cmd else set())

        with patch.dict(os.environ, {"MOTTORI_INSTANCE": str(root)}), patch.object(gate, "_issues", issues):
            assert "notes/plan.md -> budget.md" in adopted.issue_ids(str(root))
            broken.clear()
            repaired = gate.measure(edited=["notes/plan.md"])
            assert repaired.repaired_adopted == {"notes/plan.md -> budget.md"}, repaired
            adopted.retire(repaired.repaired_adopted, str(root))
            assert "notes/plan.md -> budget.md" not in adopted.issue_ids(str(root))
            broken.add("notes/plan.md -> budget.md")
            again = gate.measure(edited=["notes/plan.md"])
            assert again.edited_only == {"notes/plan.md -> budget.md"}, again


def test_an_unreadable_record_adopts_nothing():
    with workspace() as root:
        (root / "state").mkdir()
        (root / "state/.gate-adopted.json").write_text("{not json", encoding="utf-8")
        assert adopted.issue_ids(str(root)) == frozenset() and not adopted.covers("notes/a.md", str(root))


TESTS = [
    test_adopting_records_the_broken_links_and_changes_nothing_in_the_folder,
    test_report_names_instruction_files_and_repositories_inside,
    test_dry_run_writes_nothing,
    test_second_run_drops_fixed_links_and_does_not_accept_new_ones,
    test_another_folder_keeps_its_record,
    test_refuses_what_is_not_a_folder_of_the_owner,
    test_a_repository_outside_is_told_to_stay_where_it_is,
    test_a_link_is_not_followed_out_of_the_folder,
    test_the_turn_end_check_reads_the_same_issue_ids,
    test_an_adopted_link_is_not_this_turns_issue_and_a_new_one_is,
    test_a_repaired_adopted_link_loses_its_excuse,
    test_an_unreadable_record_adopts_nothing,
]


def main():
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f"✗ {test.__name__}: {type(error).__name__}: {error}")
    print(f"adopt: {len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
