#!/usr/bin/env python3
"""The loop's policy holds against a hostile proposal: no file Git itself reads, one name for one file,
every file an edit wrote is in the patch, no mode changes, and the cap on loop-only changes counts the
paths the patch changes.

Unit cases use scratch Git repositories; flow cases run the applier with a fake worker, as
tools/tests/test_papers_apply.py does. No model program starts."""
import os
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
from testlib import macos_only  # noqa: E402
import test_papers_apply as T  # noqa: E402
import loop_config  # noqa: E402
import loop_edits  # noqa: E402
import loop_judging  # noqa: E402

# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/loop_policy.py",
    "tools/loop/lib/loop_edits.py",
    "tools/loop/lib/loop_judging.py",
)


def repo(files, ignore=""):
    """A scratch Git repository holding files ({path: text}) in one commit, and .gitignore when given."""
    root = Path(tempfile.mkdtemp(prefix="loop-guard-"))
    for path, text in {**files, **({".gitignore": ignore} if ignore else {})}.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    T.sh(root, "init", "-q")
    T.sh(root, "add", "-A")
    T.sh(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    return root


def judged(*files):
    return loop_judging.validate_bundle(T.bundle(files=files))


def test_no_bundle_names_a_file_git_itself_reads():
    for path in ("tools/.gitattributes", "system/notes/.gitignore", ".gitmodules", "tools/.GitAttributes"):
        assert judged(path) == f"a file Git itself reads from the tree: {path}", (path, judged(path))
    assert judged("tools/gitattributes.md") is None


def test_a_file_an_edit_wrote_that_git_ignores_refuses_the_bundle():
    root = repo({"tools/lib.py": "VALUE = 1\n"}, ignore="tools/local.txt\n")
    try:
        edits = loop_edits.parse_edits("@@@ FILE tools/local.txt\nkept out of the patch\n@@@ END\n"
                                       "@@@ EDIT tools/lib.py\n@@@ SEARCH\nVALUE = 1\n@@@ REPLACE\nVALUE = 2\n@@@ END\n")
        try:
            loop_edits.build_candidate(SimpleNamespace(tree=str(root)), edits, ["tools/lib.py", "tools/local.txt"])
        except loop_edits.UnsafeEdit as e:
            assert "tools/local.txt" in str(e) and "not in the patch" in str(e), e
        else:
            raise AssertionError("a file Git ignores reached the tests without being in the patch")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_patch_that_changes_a_mode_is_refused():
    root = repo({"tools/run.sh": "echo one\n"})
    try:
        os.chmod(root / "tools" / "run.sh", 0o755)
        edits = loop_edits.parse_edits("@@@ EDIT tools/run.sh\n@@@ SEARCH\necho one\n@@@ REPLACE\necho two\n@@@ END\n")
        try:
            loop_edits.build_candidate(SimpleNamespace(tree=str(root)), edits, ["tools/run.sh"])
        except loop_edits.UnsafeEdit as e:
            assert "mode" in str(e) and "tools/run.sh" in str(e), e
        else:
            raise AssertionError("a patch that changes a file mode was accepted")
        # A new file is 0644 and its patch says so; that is no mode change.
        T.sh(root, "checkout", "--", "tools/run.sh")
        os.chmod(root / "tools" / "run.sh", 0o644)
        edits = loop_edits.parse_edits("@@@ FILE tools/new.py\nX = 1\n@@@ END\n")
        patch_bytes, changed, _, _ = loop_edits.build_candidate(SimpleNamespace(tree=str(root)), edits, ["tools/new.py"])
        assert changed == ["tools/new.py"] and b"new file mode 100644" in patch_bytes, patch_bytes
        assert loop_edits.mode_change(patch_bytes) is None
        assert loop_edits.mode_change(b"diff --git a/x b/x\nold mode 100644\nnew mode 100755\n") == "x"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_one_file_has_one_name():
    nfd = unicodedata.normalize("NFD", "system/메모/")
    with patch.object(loop_config, "block", lambda root=None: {"never": [nfd, "system/Frozen/"]}):
        for path in (unicodedata.normalize("NFC", "system/메모/a.md"), "system/frozen/b.md", "SYSTEM/FROZEN/c.md"):
            assert (judged(path) or "").startswith("on the never list: "), (path, judged(path))
    assert judged("tools/loop/Loop_Policy.py") == ("changes the definition of the never list and the allowed area: "
                                                   "tools/loop/Loop_Policy.py")
    # Another spelling of a path this tree tracks is refused at judgment, as are two spellings in one bundle.
    assert judged("tools/Gate.py") == "another spelling of the tracked path tools/gate.py: tools/Gate.py", judged("tools/Gate.py")
    assert judged("tools/new_one.py", "tools/New_One.py") == "two spellings of one path: tools/new_one.py, tools/New_One.py"
    assert judged("tools/gate.py") is None


def test_a_spelling_check_that_cannot_list_the_tracked_files_refuses():
    import loop_policy
    outside = tempfile.mkdtemp(prefix="loop-guard-nogit-")
    try:
        why = loop_policy.tracked_alias(["tools/new_one.py"], outside)
        assert why and "git ls-files" in why, why
    finally:
        shutil.rmtree(outside, ignore_errors=True)


@macos_only(T.SANDBOX, sandbox=True)
def test_the_cap_on_loop_only_changes_counts_the_paths_the_patch_changes():
    root = T.fixture()
    try:
        edit = "@@@ FILE tools/loop/lib/loop_note.py\nNOTE = 1\n@@@ END\n" + T.PASS + "\n"
        T.respond(root, judge=T.judge_text([T.bundle(files=("tools/lib.py", "tools/loop/lib/loop_note.py"))]),
                  impl_bump=edit, review_bump=T.PASS)
        r = T.run_apply(root, T.CYCLE)
        assert r.returncode == 0 and not (root / "tools" / "loop" / "lib" / "loop_note.py").exists(), T.report_md(root)
        assert "changes only the loop's own tools" in T.entry(root)["reason"], T.entry(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_a_spelling_check_that_cannot_list_the_tracked_files_refuses,
    test_no_bundle_names_a_file_git_itself_reads,
    test_a_file_an_edit_wrote_that_git_ignores_refuses_the_bundle,
    test_a_patch_that_changes_a_mode_is_refused,
    test_one_file_has_one_name,
    test_the_cap_on_loop_only_changes_counts_the_paths_the_patch_changes,
]


def main():
    unlisted = sorted(n for n, f in globals().items() if n.startswith("test_") and callable(f) and f not in TESTS)
    for name in unlisted:
        print(f"✗ {name}: not in TESTS")
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"loop_guard: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
