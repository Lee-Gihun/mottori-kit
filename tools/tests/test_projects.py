#!/usr/bin/env python3
"""The owner's projects: every folder under projects/ is one, and a block at the top of its README can
describe it (KIT-DR-093). A config path that names nothing is a doctor warning (KIT-DR-095).

Each test builds a scratch instance root and points the tools at it with MOTTORI_INSTANCE."""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import project_folders as projects  # noqa: E402

ROOT = os.path.dirname(TOOLS)

COURSE = """---
name: Course
area: Teaching
status: active
canonical: README.md
outside:
  - ~/no-such-folder-for-this-test: the course site's checkout
---

# Course
"""
OLD = """---
name: Old launch
area: Work
status: closed
canonical: tracker.md
---
"""


@contextlib.contextmanager
def root():
    folder = tempfile.mkdtemp(prefix="projects-")
    saved = os.environ.get("MOTTORI_INSTANCE")
    os.environ["MOTTORI_INSTANCE"] = folder
    try:
        yield folder
    finally:
        if saved is None:
            os.environ.pop("MOTTORI_INSTANCE", None)
        else:
            os.environ["MOTTORI_INSTANCE"] = saved
        shutil.rmtree(folder, ignore_errors=True)


def write(base, rel, text):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_every_folder_is_a_project_and_nothing_fails():
    """A folder brought in as it is has no block and is still a project; what is wrong is a warning."""
    with root() as base:
        write(base, "projects/course/README.md", COURSE)
        write(base, "projects/launch/README.md", OLD)
        write(base, "projects/launch/tracker.md", "# tracker\n")
        write(base, "projects/old-notes/a.md", "# notes, brought in as they are\n")
        write(base, "projects/plan/README.md", "---\nstatus: planned\ncanonical: PLAN.md\n---\n")
        found = {p["key"]: p for p in projects.read()}
        assert found["course"]["canonical"] == "projects/course/README.md", found["course"]
        assert found["course"]["outside"] == [("~/no-such-folder-for-this-test", "the course site's checkout")]
        assert found["old-notes"]["block"] is False and found["old-notes"]["status"] is None, found["old-notes"]
        warns = projects.problems()
        assert any("outside folder ~/no-such" in w for w in warns), warns
        assert any("canonical projects/plan/PLAN.md does not exist yet" in w for w in warns), warns
        assert not any("old-notes" in w for w in warns), warns
        rows = projects.context_rows()
        assert rows[0] == ("- in projects/: active course · planned plan · no status old-notes · "
                           "closed 1 (in projects/README.md)"), rows
        assert "- course outside: ~/no-such-folder-for-this-test" in rows, rows


def test_a_careless_block_is_read_and_what_is_unknown_is_named():
    with root() as base:
        write(base, "projects/a/README.md", "\ufeff\n---\nStatus: Paused\nOutside:\n- ~/x: one\n\t- ~/y: two\n"
                                            "statuss: active\n---\n")
        write(base, "projects/b/README.md", "---\nname: B\n")
        found = {p["key"]: p for p in projects.read()}
        assert found["a"]["status"] == "paused", found["a"]
        assert [path for path, _ in found["a"]["outside"]] == ["~/x", "~/y"], found["a"]
        warns = projects.problems()
        assert any("projects/a: unknown field 'statuss'" in w for w in warns), warns
        assert any("projects/b: the block at the top of README.md has no closing ---" in w for w in warns), warns


def test_a_folder_brought_in_with_front_matter_of_its_own_is_left_alone():
    """Someone else's front matter (a site generator's title and tags) is not the kit's block: none of
    it is read and nothing asks for the folder to be edited. Paths may be written from the workspace,
    a private part must be under _private/, a name with spaces still links, and a link to a folder
    elsewhere is named instead of counted."""
    with root() as base:
        write(base, "projects/blog/README.md", "---\ntitle: My blog\ntags: [a, b]\nstatus: draft\n---\n# Blog\n")
        write(base, "projects/Grant Proposal/README.md",
              "---\nstatus: active\ncanonical: projects/Grant Proposal/PLAN.md\nprivate:\n  - grades/\n---\n")
        write(base, "projects/Grant Proposal/PLAN.md", "# plan\n")
        elsewhere = os.path.join(base, "elsewhere")
        os.makedirs(elsewhere)
        os.symlink(elsewhere, os.path.join(base, "projects", "repo"))
        found = {p["key"]: p for p in projects.read()}
        assert found["blog"]["block"] is False and found["blog"]["foreign"] == ["title", "tags"]
        assert found["Grant Proposal"]["canonical"] == "projects/Grant Proposal/PLAN.md", found["Grant Proposal"]
        assert "repo" not in found
        warns = projects.problems()
        assert not any("blog" in w for w in warns), warns
        assert any("private part grades/ is not under _private/" in w for w in warns), warns
        assert any(w.startswith("projects/repo: a link to a folder elsewhere") for w in warns), warns
        text = projects.map_text(words_={})
        assert "[Grant Proposal](Grant%20Proposal/)" in text and "(Grant%20Proposal/PLAN.md)" in text, text


def test_the_map_is_drawn_between_one_marker_pair_and_nowhere_else():
    with root() as base:
        write(base, "projects/course/README.md", COURSE)
        write(base, "projects/README.md", "# Projects\n\nKept by hand.\n\n<!-- projects:start -->\nold\n"
                                          "<!-- projects:end -->\n\nAlso kept.\n")
        assert projects.draw() == "changed"
        text = open(os.path.join(base, "projects/README.md"), encoding="utf-8").read()
        assert "Kept by hand." in text and "Also kept." in text and "\nold\n" not in text, text
        assert "| [Course](course/) | active | [`README.md`](course/README.md) | ~/no-such" in text, text
        assert projects.draw() == "current"
        # A lone marker: nothing is written, however often it is drawn, and doctor says why.
        lone = "# Projects\n\n<!-- projects:start -->\nmy notes\n"
        write(base, "projects/README.md", lone)
        assert projects.draw() == projects.draw(add_markers=True) == "malformed"
        assert open(os.path.join(base, "projects/README.md"), encoding="utf-8").read() == lone
        assert any("the map needs exactly one" in w for w in projects.problems())
        # No markers: a hook draws nothing; the command adds the pair at the end.
        write(base, "projects/README.md", "# Mine\n")
        assert projects.draw() == "no markers"
        assert projects.draw(add_markers=True) == "changed"


def test_a_file_not_written_yet_is_named_not_linked():
    with root() as base:
        write(base, "projects/plan/README.md", "---\nname: Plan\nstatus: planned\ncanonical: PLAN.md\n---\n")
        text = projects.map_text(words_={})
        assert "| [Plan](plan/) | planned | `PLAN.md` |" in text, text


def test_the_owner_orders_areas_and_names_the_columns():
    with root() as base:
        spaced = COURSE.replace("~/no-such-folder-for-this-test: the course site's checkout",
                                "~/My Courses/site: the course site's checkout")
        write(base, "projects/course/README.md", spaced)
        write(base, "projects/launch/README.md", OLD.replace("status: closed", "status: paused"))
        write(base, "projects/launch/tracker.md", "# tracker\n")
        found = {p["key"]: p for p in projects.read()}
        assert found["course"]["outside"] == [("~/My Courses/site", "the course site's checkout")], found["course"]
        words = {"areas": ["Work", "Teaching"], "head": "| W | S | O | X | P |", "paused": "on hold"}
        text = projects.map_text(words_=words)
        assert text.index("## Work") < text.index("## Teaching"), text
        assert "| W | S | O | X | P |" in text and "| on hold |" in text, text


def test_the_session_start_section_has_a_byte_cap():
    with root() as base:
        for i in range(60):
            block = f"---\nstatus: active\noutside:\n  - ~/code/p{i:02d}-repo: r\n---\n"
            write(base, f"projects/p{i:02d}/README.md", block)
        rows = projects.context_rows()
        assert sum(len(r.encode()) + 1 for r in rows) <= projects.CONTEXT_MAX_BYTES + 80, rows
        assert rows[-1].startswith("- … ") and "projects/README.md" in rows[-1], rows[-1]
    with root() as base:
        # Long names fill the first line alone; it is cut too.
        for i in range(60):
            write(base, f"projects/project-{i:02d}-field-notes/README.md", "---\nstatus: active\n---\n")
        rows = projects.context_rows()
        assert len(rows) == 1 and len(rows[0].encode()) <= projects.CONTEXT_MAX_BYTES, rows
        assert rows[0].endswith("(60 in all: projects/README.md)"), rows[0][-80:]


def test_the_command_lists_draws_and_checks():
    with root() as base:
        def run(*args):
            return subprocess.run([sys.executable, os.path.join(TOOLS, "projects.py"), *args], cwd=ROOT,
                                  capture_output=True, text=True, env=dict(os.environ, MOTTORI_INSTANCE=base))
        assert run("draw").returncode == 1 and "setup.sh --force" in run("draw").stderr
        write(base, "projects/README.md", "# Projects\n")
        write(base, "projects/course/README.md", COURSE)
        listed = run()
        assert listed.returncode == 0 and "- in projects/: active course" in listed.stdout, listed.stderr
        assert run("draw").stdout.strip() == "projects/README.md redrawn"
        assert run("draw").stdout.strip() == "projects/README.md already current"
        checked = run("check")
        assert checked.returncode == 1 and "projects/course: outside folder ~/no-such" in checked.stdout
        assert run("--help").returncode == 0 and run("bogus").returncode == 2


def test_doctor_warns_about_a_config_path_that_names_nothing():
    with root() as base:
        os.makedirs(os.path.join(base, "instance"))
        os.makedirs(os.path.join(base, "docs/evidence"))
        cfg = {"schema_version": 4, "instance": {"name": "t"}, "frozen": ["docs/evidence/", "evidence/"],
               "personal_pointer": "me/profile.md",
               "checks": {"hubs": [["docs", "INDEX.md"]], "linkcheck_exclude_prefixes": ["./docs/"]},
               "egress": {"model_send": {"deny_prefixes": ["_private/", "old-client/"]}},
               "journal_visibility": {"public_tracks": None, "legacy_cutoff": None, "legacy_public_tracks": []}}
        write(base, "instance/config.json", json.dumps(cfg))
        code = ("import sys; sys.path[:0] = ['tools', 'tools/lib']; import doctor; "
                "print(doctor.c_config_paths())")
        def run():
            return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                                  env=dict(os.environ, MOTTORI_INSTANCE=base)).stdout
        out = run()
        assert "WARN" in out and "frozen: evidence/" in out and "frozen: docs/evidence" not in out, out
        assert "personal_pointer: me/profile.md" in out and "checks.hubs: docs/INDEX.md" in out, out
        assert "egress.model_send.deny_prefixes: old-client/" in out and "without the leading ./" in out, out
        write(base, "instance/config.json", json.dumps({k: v for k, v in cfg.items()
                                                        if k not in ("frozen", "personal_pointer", "checks",
                                                                     "egress")}))
        assert "SKIP" in run(), run()


def test_setup_gives_a_new_instance_the_projects_guide():
    # Only the kit ships setup and its templates; the installed-shape copy holds tools/ only.
    if not os.path.exists(os.path.join(ROOT, "setup.sh")):
        print("- setup and its templates: not in this tree")
        return
    text = open(os.path.join(ROOT, "templates", "projects-README.md"), encoding="utf-8").read()
    assert "<!-- projects:start -->" in text and "<!-- projects:end -->" in text
    setup = open(os.path.join(ROOT, "setup.sh"), encoding="utf-8").read()
    assert "projects-README.md" in setup and "paths.py projects_readme" in setup


def test_the_root_holds_only_what_a_runtime_github_or_a_first_reader_needs():
    """KIT-DR-096: the checklist lives in system/ and the contributing guide in .github/."""
    if not os.path.exists(os.path.join(ROOT, "system", "dev", "kit-files.txt")):
        print("- the kit's file list: not in this tree")
        return
    listed = open(os.path.join(ROOT, "system", "dev", "kit-files.txt"), encoding="utf-8").read().split()
    top = {p for p in listed if "/" not in p}
    assert top == {".gitignore", "AGENTS.md", "CHANGELOG.md", "CLAUDE.md", "LICENSE", "MANUAL.md", "README.md",
                   "SETUP.md", "setup.sh"}, sorted(top)
    assert "system/CHECKLIST.md" in listed and ".github/CONTRIBUTING.md" in listed


TESTS = [
    test_every_folder_is_a_project_and_nothing_fails,
    test_a_careless_block_is_read_and_what_is_unknown_is_named,
    test_a_folder_brought_in_with_front_matter_of_its_own_is_left_alone,
    test_the_map_is_drawn_between_one_marker_pair_and_nowhere_else,
    test_a_file_not_written_yet_is_named_not_linked,
    test_the_owner_orders_areas_and_names_the_columns,
    test_the_session_start_section_has_a_byte_cap,
    test_the_command_lists_draws_and_checks,
    test_doctor_warns_about_a_config_path_that_names_nothing,
    test_setup_gives_a_new_instance_the_projects_guide,
    test_the_root_holds_only_what_a_runtime_github_or_a_first_reader_needs,
]


if __name__ == "__main__":
    failed = 0
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as exc:  # noqa: BLE001 - report every failing test
            failed += 1
            print("FAIL", test.__name__, f"{type(exc).__name__}: {str(exc)[:400]}")
    print(f"projects tests: {len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
