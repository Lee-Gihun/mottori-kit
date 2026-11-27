#!/usr/bin/env python3
"""The check each change names and the review: a bundle's check is read beside its specification, the
evidence comes from the loop's own runs, and the review reads what was tested."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

from testlib import macos_only
import test_papers_apply as T  # noqa: E402

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import fresh_worker as FW  # noqa: E402
import loop_checks as LK  # noqa: E402
import loop_isolate as LI  # noqa: E402
import loop_review as LR  # noqa: E402
import paths as P  # noqa: E402
import worker_sandbox as S  # noqa: E402
from loop_common import sha256_bytes, sha256_file  # noqa: E402
from loop_contracts import LENS_HEADING  # noqa: E402
import loop_judging as LJ  # noqa: E402
from loop_judging import source_snapshot  # noqa: E402

def tree(base, files):
    for rel, text in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return SimpleNamespace(tree=base, command=lambda argv, stage="verify": argv, env=lambda: dict(os.environ))


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=cwd, check=True, capture_output=True).stdout.decode()


def review_fixture(base, raw=None, staged=()):
    """A working tree with one commit, a tracked edit and an untracked file the snapshot holds (and the
    untracked files of raw, path to bytes, of which staged are added to Git's index); the review's
    context and candidate for that snapshot."""
    root = os.path.join(base, "root")
    tree(root, {"tools/a.py": "A = 1\n"})
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    tree(root, {"tools/a.py": "A = 2\n", "tools/helper.py": "B = 1\n"})
    for rel, data in (raw or {}).items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        with open(os.path.join(root, rel), "wb") as f:
            f.write(data)
    if staged:
        git(root, "add", "--", *staged)
    snap, _ = LI.build_snapshot(root)
    d = "_private/work/papers/2026-01-01-kit"
    apply_dir = os.path.join(root, d, "apply")
    tree(root, {f"{d}/apply/b1.patch": "patch\n", f"{d}/apply/b1.tests.txt": "ok\n", f"{d}/apply/b1.spec.json": "{}\n"})
    ctx = SimpleNamespace(root=root, d=d, apply_dir=apply_dir, cyc=os.path.join(root, d), material_identity={},
                          source="papers")
    cand = {"patch_path": os.path.join(apply_dir, "b1.patch"), "patch_sha": sha256_file(os.path.join(apply_dir, "b1.patch")),
            "base_sha": snap, "tests_txt": os.path.join(apply_dir, "b1.tests.txt"),
            "spec_path": os.path.join(apply_dir, "b1.spec.json"), "detail_paths": []}
    ctx.source_identity = source_snapshot(root)
    return root, ctx, {"source_identity": ctx.source_identity}, cand


def reviewer(root, seen):
    """A review worker that builds its tree the way the worker tool does and passes."""
    def run(stage, built_by, prompt_rel, receipt, extra=(), read_materials=(), root=root):
        try:
            with mock.patch.object(FW, "ROOT", root):
                for p in read_materials:
                    FW.read_workspace_text(p, "read material")   # The worker tool takes a material as text only.
        except FW.InputError as e:
            return {"rc": 2, "status": "failed", "result": "", "runtime": "codex", "model": None, "own": False,
                    "skipped": [], "detail": str(e), "contract": None}
        mats = {p: open(os.path.join(root, p), "rb").read() for p in read_materials}
        run_dir = tempfile.mkdtemp(prefix="loop-review-run-")
        wt, meta, _ = S.prepare_worktree(root, run_dir, "dirty", [P.tracked_name(x) for x in P.POLICY_FILES], mats)
        S.remove_worktree(root, wt)
        shutil.rmtree(run_dir, ignore_errors=True)
        seen.update(materials=list(read_materials), meta=meta)
        return {"rc": 0, "status": "success", "result": "PASS", "runtime": "codex", "model": None, "own": False,
                "skipped": [], "detail": "", "contract": {"valid": True, "verdict": "PASS", "summary": "fine"},
                "worktree": meta, "materials_expected": {p: sha256_bytes(raw) for p, raw in mats.items()}}
    return run


def test_the_reviewer_reads_the_untracked_files_the_tests_ran_with():
    base = os.path.realpath(tempfile.mkdtemp(prefix="loop-review-tree-"))
    try:
        root, ctx, r, cand = review_fixture(base)
        seen = {}
        with mock.patch.object(LR, "run_in_order", reviewer(root, seen)):
            passed = LR.review(ctx, {"id": "b1", "title": "t"}, r, cand)
        assert passed, r
        assert "tools/helper.py" in seen["materials"], ("the reviewer's tree lacks a file the tests ran with", seen["materials"])
    finally:
        LI.cleanup_snapshots()
        shutil.rmtree(base, ignore_errors=True)


def test_a_review_of_a_tree_other_than_the_tested_snapshot_does_not_count():
    base = os.path.realpath(tempfile.mkdtemp(prefix="loop-review-tree-"))
    try:
        root, ctx, r, cand = review_fixture(base)
        tree(root, {"tools/a.py": "A = 3\n"})   # edited after the tests ran on the snapshot
        with mock.patch.object(LR, "run_in_order", reviewer(root, {})):
            passed = LR.review(ctx, {"id": "b1", "title": "t"}, r, cand)
        assert not passed and r.get("outcome") == "pending" and "tools/a.py" in r.get("result", ""), r
    finally:
        LI.cleanup_snapshots()
        shutil.rmtree(base, ignore_errors=True)


def test_an_untracked_file_that_is_not_text_is_named_to_the_reviewer_and_the_review_goes_on():
    base = os.path.realpath(tempfile.mkdtemp(prefix="loop-review-tree-"))
    try:
        root, ctx, r, cand = review_fixture(base, {"tools/blob.bin": b"\x00\xff\xfe\x01", "tools/pkg/__init__.py": b""})
        seen = {}
        with mock.patch.object(LR, "run_in_order", reviewer(root, seen)):
            passed = LR.review(ctx, {"id": "b1", "title": "t"}, r, cand)
        assert passed, r
        assert sorted(p for p in seen["materials"] if p.startswith("tools/")) == ["tools/helper.py"], seen["materials"]
        prompt = open(os.path.join(ctx.cyc, "prompts", "review-b1.md"), encoding="utf-8").read()
        assert "- `tools/blob.bin` (binary file, 4 bytes)\n" in prompt and "- `tools/pkg/__init__.py` (empty file, 0 bytes)\n" in prompt, prompt
        # A file that is not shown still has to be the one the tests ran with.
        with open(os.path.join(root, "tools/blob.bin"), "wb") as f:
            f.write(b"\x00changed after the tests")
        again = {"source_identity": ctx.source_identity}
        with mock.patch.object(LR, "run_in_order", reviewer(root, {})):
            assert not LR.review(ctx, {"id": "b1", "title": "t"}, again, cand)
        assert again.get("outcome") == "pending" and "tools/blob.bin" in again.get("result", ""), again
    finally:
        LI.cleanup_snapshots()
        shutil.rmtree(base, ignore_errors=True)


def test_a_new_file_the_owner_staged_is_not_handed_to_the_reviewer_twice():
    base = os.path.realpath(tempfile.mkdtemp(prefix="loop-review-tree-"))
    try:
        root, ctx, r, cand = review_fixture(base, {"tools/staged.py": b"S = 1\n"}, staged=("tools/staged.py",))
        seen = {}
        with mock.patch.object(LR, "run_in_order", reviewer(root, seen)):
            passed = LR.review(ctx, {"id": "b1", "title": "t"}, r, cand)
        assert passed, r
        # The worker tool's tree holds the staged file already; it is not a read material too.
        assert "tools/staged.py" not in seen["materials"] and "tools/helper.py" in seen["materials"], seen["materials"]
    finally:
        LI.cleanup_snapshots()
        shutil.rmtree(base, ignore_errors=True)


# A bundle as a judgment without a check records it, and its spec hash.
STORED = {"id": "bump", "title": "bundle bump", "kind": "act", "files": ["tools/lib.py", "tools/tests/test_lib.py"],
          "change": "add the EXTRA constant", "success_metric": "test_lib passes", "stop_condition": "one regression",
          "rollback": "this commit", "source": "rank 1"}
STORED_SPEC = "99f517190203549c36e1ed8f2e4d95f3ce255932f9c9e3096b40b1c819a8525b"
TEST_CHECK = {"kind": "test", "target": "tools/tests/test_lib.py::extra", "pass": "fails without EXTRA"}


def judged(*bundles):
    return LJ.parse_judge(LENS_HEADING + "\n- ledger: does not change\n\n```json\n"
                          + json.dumps({"summary": "s", "bundles": list(bundles)}) + "\n```\n")


def test_a_stored_judgment_without_a_check_validates_and_keeps_its_spec_hash():
    observe = dict(STORED, kind="observe")
    assert LJ.validate_bundle(observe) is None and LJ.spec_hash(observe) != STORED_SPEC
    assert LJ.validate_bundle(STORED) is None and LJ.spec_hash(STORED) == STORED_SPEC, LJ.spec_hash(STORED)
    assert LJ.spec_hash(dict(STORED, check=TEST_CHECK)) == STORED_SPEC
    assert LJ.check_of(STORED) == {"kind": "unknown", "target": None, "pass": None}, LJ.check_of(STORED)
    selected, _, _ = judged(observe)
    assert [b["id"] for b in selected] == ["bump"], selected


def test_an_act_bundle_with_an_unknown_check_is_refused_at_judgment():
    for b in (STORED, dict(STORED, check={"kind": "unknown"})):
        selected, rejected, _ = judged(b)
        assert not selected and "act bundle needs a check" in rejected[0]["reason"], rejected
    selected, _, _ = judged(dict(STORED, check=TEST_CHECK))
    assert [b["id"] for b in selected] == ["bump"], selected


def test_a_check_must_have_one_of_three_kinds_and_a_target_its_kind_reads():
    for bad in ({"kind": "metric", "target": "x"}, {"kind": "test", "target": "tools/lib.py"},
                {"kind": "cost", "target": "seconds"}, {"kind": "cost", "target": "context-bytes", "pass": "less"}, "test"):
        assert LJ.validate_bundle(dict(STORED, check=bad)), bad
    assert LJ.validate_bundle(dict(STORED, check={"kind": "cost", "target": "context-bytes", "pass": 1200})) is None


ADDS = b"diff --git a/tools/lib.py b/tools/lib.py\n--- a/tools/lib.py\n+++ b/tools/lib.py\n@@ -1 +1,2 @@\n VALUE = 1\n+EXTRA = 2\n"
REMOVES = b"diff --git a/tools/lib.py b/tools/lib.py\n--- a/tools/lib.py\n+++ b/tools/lib.py\n@@ -1,2 +1 @@\n VALUE = 1\n-EXTRA = 2\n"
DOCS = b"diff --git a/system/x.md b/system/x.md\n--- a/system/x.md\n+++ b/system/x.md\n@@ -1 +1,2 @@\n a\n+b\n"


def run_of(passes=(), fails=(), rc=0, output=""):
    return {"rc": rc, "timeout": False, "passes": list(passes), "fails": list(fails), "skips": [], "output": output}


def test_the_evidence_of_a_test_check_comes_from_the_two_runs():
    before = {"test_lib.py": run_of(fails=["extra"], rc=1, output="✗ extra: AssertionError: no EXTRA\n")}
    after = {"test_lib.py": run_of(passes=["extra"])}
    e = LK.evidence(TEST_CHECK, ADDS, "", before, {}, after, None)
    assert e["holds"] and e["before"] == "failed" and e["after"] == "passed", e
    e = LK.evidence(TEST_CHECK, ADDS, "", {"test_lib.py": run_of(passes=["extra"])}, {}, after, None)
    assert not e["holds"] and "did not fail" in e["reason"], e
    imported = {"test_lib.py": run_of(fails=["extra"], rc=1, output="✗ extra: ModuleNotFoundError: No module named 'lib'\n")}
    e = LK.evidence(TEST_CHECK, ADDS, "", imported, {}, after, None)
    assert not e["holds"] and e["before"] == "failed by an import error", e
    crashed = {"test_lib.py": run_of(rc=1, output="Traceback ... ImportError\n")}
    assert not LK.evidence(TEST_CHECK, ADDS, "", crashed, {}, after, None)["holds"]
    e = LK.evidence(TEST_CHECK, ADDS, "", before, {}, {"test_lib.py": run_of(fails=["extra"], rc=1)}, None)
    assert not e["holds"] and e["after"] == "failed", e


def test_the_evidence_of_a_cost_check_is_the_two_numbers():
    cost = {"kind": "cost", "target": "context-bytes", "pass": None}
    e = LK.evidence(cost, ADDS, "", {}, {}, {}, (5000, 4800))
    assert e["holds"] and (e["before"], e["after"]) == (5000, 4800), e
    assert not LK.evidence(cost, ADDS, "", {}, {}, {}, (5000, 5000))["holds"]
    assert LK.evidence(dict(cost, **{"pass": 5100}), ADDS, "", {}, {}, {}, (5000, 5050))["holds"]
    assert not LK.evidence(cost, ADDS, "", {}, {}, {}, (5000, None))["holds"]


def test_a_cost_check_needs_its_two_numbers_also_for_a_removal_or_a_documents_patch():
    cost = {"kind": "cost", "target": "context-bytes", "pass": None}
    for patch in (REMOVES, DOCS):
        e = LK.evidence(cost, patch, "callers searched", {}, {}, {}, (5000, 5100))
        assert not e["holds"] and (e["before"], e["after"]) == (5000, 5100) and "not smaller" in e["reason"], e
        e = LK.evidence(cost, patch, "callers searched", {}, {}, {}, (5000, 4900))
        assert e["holds"] and (e["before"], e["after"]) == (5000, 4900) and "statement" not in e, e
        assert not LK.evidence(cost, patch, "callers searched", {}, {}, {}, None)["holds"]


def test_a_removal_or_a_documents_patch_carries_the_builders_statement():
    for patch in (REMOVES, DOCS):
        e = LK.evidence(TEST_CHECK, patch, "callers searched; nothing reads EXTRA", {}, {}, {}, None)
        assert e["holds"] and e["statement"] == "callers searched; nothing reads EXTRA", e
        assert not LK.evidence(TEST_CHECK, patch, "", {}, {}, {}, None)["holds"]
    unknown = LK.evidence({"kind": "unknown", "target": None, "pass": None}, ADDS, "", {}, {}, {}, None)
    assert unknown["holds"] and unknown["before"] is None, unknown
    assert LK.checked_statement("edit blocks\nChecked: callers searched; none.\nRESULT_JSON: {}") == "callers searched; none."


def test_context_bytes_counts_only_a_run_that_ended_0_in_time():
    line = json.dumps({"items": [], "total": {"bytes": 4321}})
    for rc, timed, want in ((0, False, 4321), (1, False, None), (0, True, None), (124, True, None)):
        with mock.patch.object(LK, "run_group", return_value=(rc, "noise\n" + line + "\n", timed)):
            assert LK.context_bytes(lambda argv: argv, "/tree", {}) == want, (rc, timed)


# The candidate's test: it fails on the unchanged code because EXTRA is missing.
EXTRA_TEST = ("@@@ EDIT tools/tests/test_lib.py\n@@@ SEARCH\nif lib.VALUE == 1:\n@@@ REPLACE\n"
              "if getattr(lib, 'EXTRA', None) != 2:\n    print('FAIL extra: EXTRA is missing')\n    sys.exit(1)\n"
              "print('PASS extra')\nif lib.VALUE == 1:\n@@@ END\n")
# The same check written so that the unchanged code fails it by an import error.
IMPORT_TEST = ("@@@ EDIT tools/tests/test_lib.py\n@@@ SEARCH\nif lib.VALUE == 1:\n@@@ REPLACE\n"
               "try:\n    from lib import EXTRA\nexcept ImportError as e:\n    print('FAIL extra: ' + type(e).__name__)\n"
               "    sys.exit(1)\nprint('PASS extra')\nif lib.VALUE == 1:\n@@@ END\n")
EXTRA_CHECK = {"kind": "test", "target": "tools/tests/test_lib.py::extra"}
LONG_AGENTS = "# Rules\n" + "a rule every session reads\n" * 20


def reviews(root):
    return [c for c in T.worker_calls(root) if c[-1].endswith("review-bump.md")]


@macos_only(T.SANDBOX, sandbox=True)
def test_a_test_check_whose_test_did_not_fail_before_is_refused_before_review():
    for check, impl, why in ((dict(EXTRA_CHECK, target="tools/tests/test_lib.py::value"), T.EDIT_OK,
                              "did not fail on the unchanged code (passed)"),
                             (EXTRA_CHECK, T.EDIT_OK.replace(T.PASS, "") + IMPORT_TEST + T.PASS + "\n",
                              "did not fail on the unchanged code (failed by an import error)")):
        root = T.fixture()
        try:
            T.respond(root, judge=T.judge_text([T.bundle(kind="act", check=check)]), impl_bump=impl, review_bump=T.PASS)
            r = T.run_apply(root, T.CYCLE)
            e = T.entry(root)
            assert r.returncode == 0 and e["outcome"] == "abandoned" and why in (e["reason"] or ""), e
            assert not reviews(root), reviews(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)


@macos_only(T.SANDBOX, sandbox=True)
def test_a_test_check_that_holds_is_saved_with_its_evidence_in_the_report():
    root = T.fixture()
    try:
        impl = T.EDIT_OK.replace(T.PASS, "") + EXTRA_TEST + T.PASS + "\n"
        T.respond(root, judge=T.judge_text([T.bundle(kind="act", check=EXTRA_CHECK)]), impl_bump=impl, review_bump=T.PASS)
        r = T.run_apply(root, T.CYCLE)
        e = T.entry(root)
        assert r.returncode == 0 and e["outcome"] == "saved", r.stdout + r.stderr + T.report_md(root)
        ev = e["evidence"]
        assert ev["holds"] and (ev["before"], ev["after"]) == ("failed", "passed"), ev
        assert ev["check"] == {"kind": "test", "target": "tools/tests/test_lib.py::extra", "pass": None}, ev
        line = "Evidence: test tools/tests/test_lib.py::extra: failed on the unchanged code, passed on the change"
        assert line in T.report_md(root), T.report_md(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(T.SANDBOX, sandbox=True)
def test_the_review_prompt_names_the_check_and_what_the_loop_measured():
    root = T.fixture()
    try:
        impl = T.EDIT_OK.replace(T.PASS, "") + EXTRA_TEST + T.PASS + "\n"
        T.respond(root, judge=T.judge_text([T.bundle(kind="act", check=EXTRA_CHECK)]), impl_bump=impl, review_bump=T.PASS)
        T.run_apply(root, T.CYCLE)
        prompt = (root / T.CYCLE / "prompts" / "review-bump.md").read_text()
        assert "The change's check: test tools/tests/test_lib.py::extra" in prompt, prompt
        assert ("What the loop measured: test tools/tests/test_lib.py::extra: failed on the unchanged code, "
                "passed on the change") in prompt, prompt
    finally:
        shutil.rmtree(root, ignore_errors=True)


def agents_fixture():
    root = T.fixture()
    T.with_context_budget(root, 100000)
    (root / "AGENTS.md").write_text(LONG_AGENTS)
    T.sh(root, "add", "AGENTS.md")
    T.sh(root, "commit", "-q", "-m", "rules")
    return root


SHORT_AGENTS = "# Rules\na rule every session reads\n"
SHORTER = "@@@ FILE AGENTS.md\n" + SHORT_AGENTS + "@@@ END\n"


@macos_only(T.SANDBOX, sandbox=True)
def test_a_cost_check_is_saved_only_with_two_numbers_and_a_smaller_one():
    cost = {"kind": "cost", "target": "context-bytes", "pass": None}
    for impl, saved in ((T.EDIT_OK.replace(T.PASS, "") + SHORTER + T.PASS + "\n", True), (T.EDIT_OK, False)):
        root = agents_fixture()
        try:
            files = ("tools/lib.py", "AGENTS.md")
            T.respond(root, judge=T.judge_text([T.bundle(kind="act", files=files, check=cost)]), impl_bump=impl,
                      review_bump=T.PASS)
            r = T.run_apply(root, T.CYCLE)
            e = T.entry(root)
            assert r.returncode == 0 and (e["outcome"] == "saved") == saved, r.stdout + T.report_md(root)
            if saved:
                ev = e["evidence"]
                assert ev["holds"] and ev["before"] == len(LONG_AGENTS) and ev["after"] == len(SHORT_AGENTS), ev
                assert f"Evidence: context-bytes {len(LONG_AGENTS)} -> {len(SHORT_AGENTS)}" in T.report_md(root), T.report_md(root)
            else:
                assert "not smaller" in T.entry(root)["reason"] and not reviews(root), T.entry(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)


@macos_only(T.SANDBOX, sandbox=True)
def test_a_documents_patch_with_a_cost_check_is_saved_only_when_its_number_is_smaller():
    cost = {"kind": "cost", "target": "context-bytes", "pass": None}
    longer = "@@@ FILE AGENTS.md\n" + LONG_AGENTS + "one more rule\n@@@ END\n"
    checked = "Checked: the rules compared with the code that enforces them.\n"
    for impl, saved in ((SHORTER + checked + T.PASS + "\n", True), (longer + checked + T.PASS + "\n", False)):
        root = agents_fixture()
        try:
            T.respond(root, judge=T.judge_text([T.bundle(kind="act", files=("AGENTS.md",), check=cost)]),
                      impl_bump=impl, review_bump=T.PASS)
            r = T.run_apply(root, T.CYCLE)
            e = T.entry(root)
            assert r.returncode == 0 and (e["outcome"] == "saved") == saved, r.stdout + T.report_md(root)
            if saved:
                ev = e["evidence"]
                assert (ev["before"], ev["after"]) == (len(LONG_AGENTS), len(SHORT_AGENTS)), ev
            else:
                assert "not smaller" in T.entry(root)["reason"] and not reviews(root), T.entry(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)


@macos_only(T.SANDBOX, sandbox=True)
def test_a_documents_patch_is_saved_with_the_builders_statement_as_evidence():
    for checked, saved in (("Checked: the rule's wording compared with the code that enforces it.\n", True), ("", False)):
        root = agents_fixture()
        try:
            T.respond(root, judge=T.judge_text([T.bundle(kind="act", files=("AGENTS.md",), check=EXTRA_CHECK)]),
                      impl_bump=SHORTER + checked + T.PASS + "\n", review_bump=T.PASS)
            r = T.run_apply(root, T.CYCLE)
            e = T.entry(root)
            assert r.returncode == 0 and (e["outcome"] == "saved") == saved, r.stdout + T.report_md(root)
            if saved:
                assert e["evidence"]["statement"] == checked[len("Checked: "):].strip(), e
            else:
                assert "no 'Checked:' line" in T.entry(root)["reason"], T.entry(root)
        finally:
            shutil.rmtree(root, ignore_errors=True)


@macos_only(T.SANDBOX, sandbox=True)
def test_the_correction_prompt_carries_the_failing_tests_output_and_names_the_check():
    root = T.fixture()
    try:
        T.respond(root, judge=T.judge_text([T.bundle()]), impl_bump=T.EDIT_BREAK, impl_bump_attempt_2=T.EDIT_OK,
                  review_bump=T.PASS)
        r = T.run_apply(root, T.CYCLE)
        state = json.loads((root / T.CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        prompt = (root / state["attempts"][1]["artifacts"] / "impl-prompt.md").read_text()
        assert r.returncode == 0 and state["attempts"][0]["failure_stage"] == "tests", state
        assert "Output of test_lib.py (clipped):" in prompt and "FAIL value" in prompt, prompt[-800:]
        assert "The bundle's check: unknown" in prompt, prompt[-800:]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_long_failing_test_files_kept_output_holds_its_failure_lines():
    """The candidate's run keeps a failed file's output for the correction prompt: the lines that report
    failures and the end of the output, not only its beginning."""
    with tempfile.TemporaryDirectory(prefix="loop-checks-long.") as td:
        tests = os.path.join(td, "tools", "tests")
        os.makedirs(tests)
        body = ('for i in range(400):\n    print(f"\u2713 a passing check number {i}")\n'
                'print("\u2717 the_value: AssertionError: expected 1, got 2")\n'
                'print("tail line of the output")\nraise SystemExit(1)\n')
        open(os.path.join(tests, "test_long.py"), "w", encoding="utf-8").write(body)
        iso = SimpleNamespace(tree=td, command=lambda argv: argv, env=lambda: dict(os.environ))
        out = LK.run_tests(iso, keep_failing=True)["test_long.py"]["output"]
        assert "\u2717 the_value: AssertionError: expected 1, got 2" in out, out[-300:]
        assert "tail line of the output" in out and len(out) <= 4000, (len(out), out[-300:])


TESTS = [
    test_a_new_file_the_owner_staged_is_not_handed_to_the_reviewer_twice,
    test_the_review_prompt_names_the_check_and_what_the_loop_measured,
    test_the_reviewer_reads_the_untracked_files_the_tests_ran_with,
    test_a_review_of_a_tree_other_than_the_tested_snapshot_does_not_count,
    test_an_untracked_file_that_is_not_text_is_named_to_the_reviewer_and_the_review_goes_on,
    test_a_stored_judgment_without_a_check_validates_and_keeps_its_spec_hash,
    test_an_act_bundle_with_an_unknown_check_is_refused_at_judgment,
    test_a_check_must_have_one_of_three_kinds_and_a_target_its_kind_reads,
    test_the_evidence_of_a_test_check_comes_from_the_two_runs,
    test_the_evidence_of_a_cost_check_is_the_two_numbers,
    test_a_cost_check_needs_its_two_numbers_also_for_a_removal_or_a_documents_patch,
    test_a_removal_or_a_documents_patch_carries_the_builders_statement,
    test_context_bytes_counts_only_a_run_that_ended_0_in_time,
    test_a_test_check_whose_test_did_not_fail_before_is_refused_before_review,
    test_a_test_check_that_holds_is_saved_with_its_evidence_in_the_report,
    test_a_cost_check_is_saved_only_with_two_numbers_and_a_smaller_one,
    test_a_documents_patch_with_a_cost_check_is_saved_only_when_its_number_is_smaller,
    test_a_documents_patch_is_saved_with_the_builders_statement_as_evidence,
    test_the_correction_prompt_carries_the_failing_tests_output_and_names_the_check,
    test_a_long_failing_test_files_kept_output_holds_its_failure_lines,
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
    print(f"loop_checks: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
