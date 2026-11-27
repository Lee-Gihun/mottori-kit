#!/usr/bin/env python3
"""Asks an independent reviewer about the exact bytes of a tested patch and records its verdict.

The reviewer reads the patch, the bundle's spec, the test results and the judgment's materials, in a
tree that must hold what the tests ran on: the worker tool builds it from HEAD and the working tree's
tracked changes, the snapshot's untracked files are handed to it as read materials, and after the run
the tree it read is compared with the snapshot commit. The worker tool takes a material as text only, so
an untracked file that is empty or not UTF-8 text is named in the prompt with its size and not shown; it
must still hold the snapshot's bytes. Its verdict counts only for that commit and the patch bytes it saw,
and only from a worker run that ended cleanly."""
import json
import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402
from loop_checks import evidence_line  # noqa: E402
from loop_common import StageError, clip, git, rel, sha256_file, write  # noqa: E402
from loop_isolate import snapshot_adds, unlike_snapshot  # noqa: E402
from loop_judging import material_hashes, verify_source_materials, verify_worker_source  # noqa: E402
from loop_stores import PRIVATE  # noqa: E402
from loop_outcome import pend, refuse  # noqa: E402
from loop_prompts import (material_prompt, not_shown_prompt, review_prompt,  # noqa: E402
                          verification_prompt)
from loop_run import WORKER_TREE  # noqa: E402
from loop_worker import reviewer_line, run_in_order  # noqa: E402

TEST_ROLES = {"baseline": "base tests on base implementation", "candidate": "candidate tests on candidate implementation",
              "original-tests": "base tests on candidate implementation",
              "counterfactual-tests": "candidate test edits only on base implementation; diagnostic, not a universal failure gate"}


def _prompt(ctx, b, r, cand, verification_path, not_shown):
    root = ctx.root
    prompt = review_prompt(b, ctx.d, rel(root, cand["patch_path"]), rel(root, cand["tests_txt"]),
                           rel(root, cand["spec_path"]), cand["patch_sha"], evidence_line(r.get("evidence")),
                           rules=bool(r.get("loaded_files")))
    prompt += material_prompt(ctx.material_identity)
    prompt += verification_prompt([*cand["detail_paths"], rel(root, verification_path)])
    return prompt + not_shown_prompt(not_shown)


def _untracked_in(ctx, base_sha):
    """(shown, not shown) of the files the tested snapshot adds to HEAD that are on disk and not in
    Git's index: the worker tool's tree, HEAD with the working tree's tracked changes, lacks only
    those (a new file the owner staged is already in it). Shown are the paths handed over as read
    materials; not shown maps a path the worker tool cannot take as text to the prompt's words for it."""
    shown, not_shown = [], {}
    adds = snapshot_adds(base_sha, ctx.source_identity["base_rev"], ctx.root)
    listed = git(["--literal-pathspecs", "ls-files", "-z", "--", *adds], ctx.root).stdout if adds else b""
    staged = set(listed.decode("utf-8", "replace").split("\0"))
    for p in (p for p in adds if p not in staged):
        path = os.path.join(ctx.root, p)
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        with open(path, "rb") as f:
            raw = f.read()
        try:
            raw.decode("utf-8")
            text = bool(raw)
        except UnicodeDecodeError:
            text = False
        if text:
            shown.append(p)
        else:
            not_shown[p] = f"{'binary' if raw else 'empty'} file, {len(raw)} bytes"
    return shown, not_shown


def _read_elsewhere(ctx, v, base_sha, not_shown):
    """The paths where the tree the reviewer read differs from the tested snapshot. Folders the clone
    leaves out (loop.clone_excluded) and the private area are not in the snapshot and are not compared;
    a file that was not shown counts as read while the working tree still holds the snapshot's bytes."""
    tree = (v.get("worktree") or {}).get("base_tree")
    if not tree:
        return ["(the worker's record names no tree)"]
    skip = tuple(loop_config.value("clone_excluded", ctx.root)) + (PRIVATE + "/",)
    placed = {**{p: sha256_file(os.path.join(ctx.root, p)) for p in not_shown},
              **(v["worktree"].get("material_sha256") or {})}
    return [p for p in unlike_snapshot(base_sha, tree, placed, ctx.root) if not p.startswith(skip)]


def review(ctx, b, r, cand):
    """Return True when the patch is saved: a PASS on these bytes.

    cand holds the candidate's patch_path, patch_sha, base_sha, tests_txt, spec_path and detail_paths."""
    bid, root, apply_dir, patch_sha = b["id"], ctx.root, ctx.apply_dir, cand["patch_sha"]
    stage = f"review({bid})"
    verify_source_materials(ctx, stage, root)
    verification_path = os.path.join(apply_dir, f"{bid}.verification.json")
    write(verification_path, json.dumps({"source_identity": r["source_identity"], "patch_sha256": patch_sha,
          "material_identity": ctx.material_identity, "test_artifact_sha256": material_hashes(cand["detail_paths"], root),
          "test_roles": TEST_ROLES}, indent=1) + "\n")
    shown, not_shown = _untracked_in(ctx, cand["base_sha"])
    prompt = _prompt(ctx, b, r, cand, verification_path, not_shown)
    write(os.path.join(ctx.cyc, "prompts", f"review-{bid}.md"), prompt)
    v = run_in_order("review", r.get("impl_runtime") or "claude", f"{ctx.d}/prompts/review-{bid}.md",
                     os.path.join(apply_dir, f"review-{bid}.receipt"),
                     extra=WORKER_TREE,
                     read_materials=(*ctx.material_identity, rel(root, cand["patch_path"]), rel(root, cand["tests_txt"]),
                                     rel(root, cand["spec_path"]), *cand["detail_paths"], rel(root, verification_path),
                                     *shown),
                     root=root)
    r["reviewer"] = {"runtime": v["runtime"], "model": v["model"], "own": v["own"], "skipped": v["skipped"]}
    if v["result"]:
        write(os.path.join(apply_dir, f"review-{bid}.result.md"), v["result"])
    c = v["contract"] or {}
    verdict = c.get("verdict") if c.get("valid") is True else None
    if v["rc"] != 0 or v["status"] != "success":
        raise StageError(stage, f"review worker failed rc={v['rc']} status={v['status']} "
                                f"(a PASS in its text does not count) {v['detail']}")
    verify_worker_source(v, r["source_identity"], stage, root)
    verify_source_materials(ctx, stage, root)
    r["review"] = f"{verdict or 'INCONCLUSIVE'}: {clip(c.get('summary', ''), 140)}"
    elsewhere = _read_elsewhere(ctx, v, cand["base_sha"], not_shown)
    if elsewhere:
        pend(r, "the reviewer read a tree that differs from the snapshot the tests ran on (the next run builds it "
                "again): " + ", ".join(elsewhere[:5]))
        return False
    if sha256_file(cand["patch_path"]) != patch_sha:
        pend(r, "the patch bytes changed during the review; the next run builds it again")
        return False
    if verdict != "PASS":
        refuse(r, "review", f"review {verdict or 'INCONCLUSIVE'} ({reviewer_line(r)})")
        return False
    return True
