#!/usr/bin/env python3
"""Reads a judge's answer and what it is bound to: the fields of a bundle and their validation, the
bundles selected and rejected, the materials a judgment reads, and the source identity.

A root argument names the working tree; without it, the tree this file lives in."""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_policy  # noqa: E402
import paths as P  # noqa: E402
from loop_common import StageError, git, normal_path, rel, sha256_bytes, sha256_file  # noqa: E402
from loop_contracts import json_blocks  # noqa: E402
import loop_sources  # noqa: E402
from loop_stores import PAPERS_BASE  # noqa: E402

MAX_FILES = 8
# The stage name of a judgment's errors.
JUDGE = "judge"
# The fields of a bundle in the judge's JSON block, and the keys of the block and of the paths reply.
BUNDLE_FIELDS = ("id", "title", "kind", "files", "change", "success_metric", "stop_condition",
                 "rollback", "source")
BUNDLES, REJECTED, SUMMARY = "bundles", "rejected", "summary"
PATHS, IDEA_ONLY = "paths", "idea_only"
# The one check a bundle names beside its specification (not in it, so spec_hash does not see it):
# test names a test that fails on the unchanged code and passes on the candidate, cost names the
# always-loaded context's size, unknown says that no check exists.
CHECK, CHECK_KINDS = "check", ("test", "cost", "unknown")
CONTEXT_BYTES = "context-bytes"
_TEST_TARGET = re.compile(r"(tools/tests/test_[^/:]+\.py)::(.+)")
ACT_NEEDS_CHECK = ("an act bundle needs a check that could show it does not help (kind test or cost); "
                   "with an unknown check only an observe bundle is selected")


def path_refusal(path):
    """Why no bundle may change path (tools/loop/loop_policy.py), or None."""
    return loop_policy.refusal(path)


def check_of(b):
    """The bundle's check with kind, target and pass; a bundle without one reads as unknown."""
    c = b.get(CHECK) if isinstance(b, dict) else None
    if not isinstance(c, dict) or c.get("kind") in (None, "unknown"):
        return {"kind": "unknown", "target": None, "pass": None}
    return {"kind": c.get("kind"), "target": c.get("target"), "pass": c.get("pass")}


def test_target(check):
    """(test file path, test name) a test check names."""
    m = _TEST_TARGET.fullmatch(str(check.get("target") or ""))
    return (m.group(1), m.group(2).strip()) if m else (None, None)


def check_problem(b):
    """Why the bundle's check cannot be read, or None (no check at all is unknown, not a problem)."""
    c = b.get(CHECK)
    if c is None:
        return None
    if not isinstance(c, dict) or c.get("kind") not in CHECK_KINDS:
        return "check must be an object whose kind is test, cost or unknown"
    if c["kind"] == "test" and test_target(c)[0] is None:
        return "a test check's target must be tools/tests/test_<name>.py::<test name>"
    if c["kind"] == "cost" and (c.get("target") != CONTEXT_BYTES or not (
            c.get("pass") is None or (isinstance(c["pass"], int) and not isinstance(c["pass"], bool)))):
        return f"a cost check's target must be {CONTEXT_BYTES}, and its pass a whole number of bytes or null"
    return None


def validate_bundle(b):
    """Return why a bundle cannot run, or None. A path refusal names the path (path_refusal)."""
    if not isinstance(b, dict):
        return "a bundle is not an object"
    missing = [k for k in BUNDLE_FIELDS if not b.get(k)]
    if missing:
        return "missing fields: " + ", ".join(missing)
    if not isinstance(b["source"], str) or not b["source"].strip():
        return "source must be a non-empty string naming the grounds"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", str(b["id"])):
        return "id must be lowercase letters, digits and hyphens, at most 40"
    if b["kind"] not in ("observe", "act"):
        return "kind must be observe or act"
    files = b["files"]
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        return f"files must be a list of 1 to {MAX_FILES} paths"
    for f in files:
        if not normal_path(f):
            return f"not a normalized relative path: {f}"
        why = path_refusal(f)
        if why:
            return why
    return check_problem(b) or loop_policy.tracked_alias(files, ROOT)


def judgment_data(text):
    """The last fenced JSON block with a bundles key; raise StageError on contract errors."""
    if not text or not text.strip():
        raise StageError(JUDGE, "the judgment is empty")
    data = None
    for cand in json_blocks(text):
        if isinstance(cand, dict) and BUNDLES in cand:
            data = cand
    if data is None:
        raise StageError(JUDGE, f"no JSON block with a '{BUNDLES}' key")
    if not isinstance(data.get(BUNDLES), list):
        raise StageError(JUDGE, f"'{BUNDLES}' is not a list")
    return data


def parse_judge(text):
    """Parse the judgment into selected, rejected, and summary values; raise StageError on contract errors."""
    data = judgment_data(text)
    selected, rejected, seen, kinds = [], [], set(), set()
    for b in data[BUNDLES]:
        why = validate_bundle(b)
        if why:
            rejected.append({"id": b.get("id", "?") if isinstance(b, dict) else "?",
                             "title": b.get("title", "") if isinstance(b, dict) else "", "reason": why})
            continue
        if b["id"] in seen:
            rejected.append({"id": b["id"], "title": b["title"], "reason": "duplicate id"})
            continue
        if b["kind"] == "act" and check_of(b)["kind"] == "unknown":
            rejected.append({"id": b["id"], "title": b["title"], "reason": ACT_NEEDS_CHECK})
            continue
        if b["kind"] in kinds or len(selected) >= 2:
            rejected.append({"id": b["id"], "title": b["title"], "reason": "over the cap of one observe and one act bundle per cycle"})
            continue
        if loop_policy.loop_only(b["files"]) and any(loop_policy.loop_only(x["files"]) for x in selected):
            rejected.append({"id": b["id"], "title": b["title"],
                             "reason": "at most one bundle per cycle changes only the loop's own tools"})
            continue
        seen.add(b["id"])
        kinds.add(b["kind"])
        selected.append(b)
    for r in data.get(REJECTED) or []:
        if isinstance(r, dict):
            rejected.append({"id": r.get("id", "-"), "title": r.get("title", ""),
                             "reason": "refused by the judge: " + str(r.get("reason", ""))})
    return selected, rejected, str(data.get(SUMMARY, ""))


def source_snapshot(root):
    """Exactly the worktree base of root and its copied policy files; no private text in this identity."""
    files = [P.tracked_name(path_of) for path_of in P.POLICY_FILES]
    if not isinstance(files, (tuple, list)) or any(not normal_path(p) for p in files):
        raise StageError("source", "the list of copied policy files is malformed")
    base_rev = git(["rev-parse", "HEAD"], cwd=root).stdout.decode().strip()
    return {"base_rev": base_rev, "instance_sha256": {p: sha256_file(os.path.join(root, p)) for p in files}}


def input_name(source):
    return "PROPOSALS.md" if source == "papers" else loop_sources.get(source).INPUT


def needs_paths(b):
    """A bundle that names no files: the judge is asked once for them before it is judged."""
    return isinstance(b, dict) and not b.get("files")


def spec_of(b):
    return {k: b.get(k) for k in BUNDLE_FIELDS}


def spec_hash(b):
    return sha256_bytes(json.dumps(spec_of(b), ensure_ascii=False, sort_keys=True).encode("utf-8"))


def verify_worker_source(worker, expected, stage, root=None):
    actual = worker.get("worktree") or {}
    if (actual.get("base_rev") != expected["base_rev"] or
            actual.get("instance_sha256") != expected["instance_sha256"]):
        raise StageError(stage, "the worker's source identity differs or its record has none", kind="source-changed")
    if (actual.get("material_sha256", {}) != worker.get("materials_expected", {}) or
            actual.get("material_integrity") is False):
        raise StageError(stage, "the materials the worker read differ from the snapshot or changed")
    if source_snapshot(root or ROOT) != expected:
        raise StageError(stage, "HEAD or a copied policy file changed while the worker ran", kind="source-changed")


def previous_reports(d, source, root=None):
    """The reports of the last three cycles of source before d: REPORT.md, or the APPLY.md a folder from
    an earlier version of the loop holds (its REPORT.md says only what was collected)."""
    root = root or ROOT
    base = os.path.join(root, PAPERS_BASE if source == "papers" else loop_sources.get(source).BASE)
    folders = sorted(f for f in glob.glob(os.path.join(base, "*")) if f < os.path.join(root, d))
    paths = [next((p for p in (os.path.join(f, "APPLY.md"), os.path.join(f, "REPORT.md")) if os.path.isfile(p)), None)
             for f in folders]
    return [rel(root, p) for p in paths if p][-3:]


def previous_report_paths(d, source, root=None):
    return "\n".join(f"- `{p}`" for p in previous_reports(d, source, root)) or "- No earlier report (nothing to observe)."


def judge_materials(d, source, root=None):
    root = root or ROOT
    paths = [f"{d}/{input_name(source)}", f"{d}/REPORT.md"]
    if source == "papers":
        paths += [rel(root, p) for p in sorted(glob.glob(os.path.join(root, d, "cards", "*.md")))]
    paths += previous_reports(d, source, root)
    return [p for p in dict.fromkeys(paths) if os.path.isfile(os.path.join(root, p))]


def source_materials(d, source, root=None):
    """Grounding documents shared by judge, implementation, and independent reviewer."""
    # This cycle's REPORT.md is drawn again when the run ends, so it is no material to pin.
    return [p for p in judge_materials(d, source, root) if p != f"{d}/REPORT.md"]


def material_hashes(paths, root=None):
    return {p: sha256_file(os.path.join(root or ROOT, p)) for p in paths}


def verify_source_materials(ctx, stage, root=None):
    if material_hashes(source_materials(ctx.d, ctx.source, root), root) != ctx.material_identity:
        raise StageError(stage, "a read material changed; the source needs a new judgment", kind="source-changed")


def correction_materials(r, root=None):
    root = root or ROOT
    attempts = r.get("attempts", [])
    if len(attempts) < 2:
        return []
    directory = os.path.join(root, attempts[-2]["artifacts"])
    return [rel(root, p) for p in sorted(glob.glob(os.path.join(directory, "*")))
            if os.path.isfile(p) and (p.endswith(".result.md") or p.endswith(".patch") or p.endswith(".original-tests.json") or
                                     p.endswith(".tests.json") or p.endswith(".tests.txt") or p.endswith(".verification.json") or
                                     p.endswith(".counterfactual-tests.json") or p.endswith(".gate.txt") or
                                     os.path.basename(p) == "attempt.json")]
