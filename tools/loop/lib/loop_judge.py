#!/usr/bin/env python3
"""Gets a cycle's judgment: checks the cycle's input, reuses JUDGE.md while it is bound to the same input
and source, and otherwise asks the judge worker, then asks once more for the files of the bundles its
judgment selected without naming any.

A judgment is bound to the input's hash, the worker-observed source identity and the hashes of the
materials it read; a changed input archives the old judgment as a new generation. The working tree
comes from ctx.root, or from the root argument where there is no ctx."""
import json
import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
from loop_common import StageError, WorkerUnavailable, load_json, read, rel, sha256_file, write  # noqa: E402
from loop_contracts import json_block, json_blocks  # noqa: E402
from loop_judging import (BUNDLES, IDEA_ONLY, JUDGE, PATHS, REJECTED, input_name, judge_materials,  # noqa: E402
                          judgment_data, material_hashes, needs_paths, parse_judge, source_materials, spec_hash,
                          verify_worker_source)
from loop_outcome import is_terminal  # noqa: E402
from loop_prompts import judge_prompt, paths_prompt  # noqa: E402
from loop_run import WORKER_TREE  # noqa: E402
from loop_state import OUTCOME_REL  # noqa: E402
import loop_sources  # noqa: E402
from loop_worker import run_in_order  # noqa: E402


def check_input(ctx):
    """(path, sha256) of the cycle's input document; StageError when it cannot be judged."""
    need = os.path.join(ctx.cyc, input_name(ctx.source))
    if not os.path.isfile(need) or os.path.islink(need):
        raise StageError(JUDGE, f"no input: {rel(ctx.root, need)}")
    if not read(need).strip():
        raise StageError(JUDGE, f"the input is empty: {rel(ctx.root, need)}")
    unusable = loop_sources.hook(ctx.source, "unusable")
    why = unusable(ctx.cyc) if unusable else None
    if why:
        raise StageError(JUDGE, why)
    return need, sha256_file(need)


def new_generation(ctx, judge_md, old_sha):
    """Archive the judgment and state of an older input; the records of its specifications carry over."""
    gen = os.path.join(ctx.apply_dir, f"gen-{(old_sha or 'legacy')[:12]}")
    base_gen, number = gen, 1
    while os.path.exists(gen):
        number += 1
        gen = f"{base_gen}-{number}"
    os.makedirs(gen, exist_ok=True)
    for src in (judge_md, os.path.join(ctx.cyc, OUTCOME_REL), ctx.state_path):
        if os.path.isfile(src):
            os.replace(src, os.path.join(gen, os.path.basename(src)))
    prior = dict(ctx.state.get("prior_results", {}))
    for record in (ctx.state.get("bundles") or {}).values():
        if record.get("spec") and record.get("source_identity"):
            key = record["spec"]
            if len(record.get("attempts", [])) >= len(prior.get(key, {}).get("attempts", [])):
                prior[key] = record
    ctx.state = {"prior_results": prior}
    ctx.save([])  # Generation change cannot erase reserved budgets if the next judge crashes.
    ctx.notes.append(f"the input changed, so it is judged as a new generation (the old judgment and state are in `{rel(ctx.root, gen)}`)")


def _unfinished(ctx, bundles, prior):
    """The judged bundles whose record is not settled (saved, refused or abandoned)."""
    return [b for b in bundles if not (prior.get(b["id"], {}).get("spec") == spec_hash(b) and
                                       is_terminal(prior.get(b["id"])))]


def _reused(ctx, judge_md, meta):
    """The saved judgment when it may be reused, else None: its materials are unchanged and, while a
    bundle is unfinished, its source is the current one."""
    try:
        parsed = parse_judge(read(judge_md))
        unfinished = _unfinished(ctx, parsed[0], ctx.state.get("bundles", {}))
        material_stale = (meta.get("material_identity") !=
                          material_hashes(source_materials(ctx.d, ctx.source, ctx.root), ctx.root))
        if unfinished and (material_stale or meta.get("source_identity") != ctx.source_identity):
            ctx.notes.append("the source of an unfinished bundle changed: judged once more on the current source")
            return None
        ctx.notes.append("judgment: JUDGE.md reused (same input and source, or settled results)")
        return parsed
    except StageError:
        return None


def _asked(ctx, need, inp_sha, judge_md, meta_path, judge_only):
    """Ask the judge worker; return (parsed judgment, its binding)."""
    root, d, source = ctx.root, ctx.d, ctx.source
    prompt = judge_prompt(d, source, root)
    write(os.path.join(ctx.cyc, "prompts", "judge.md"), prompt)
    try:
        r = run_in_order("judge", None, f"{d}/prompts/judge.md", os.path.join(ctx.apply_dir, "judge.receipt"),
                         extra=WORKER_TREE, read_materials=judge_materials(d, source, root), root=root)
    except WorkerUnavailable as e:
        raise StageError(JUDGE, e.reason, kind=e.kind) from e
    if r["rc"] != 0 or r["status"] != "success" or not r["result"].strip():
        raise StageError(JUDGE, f"the judge worker failed rc={r['rc']} status={r['status']} {r['detail']}")
    verify_worker_source(r, ctx.source_identity, JUDGE, root)
    if r["materials_expected"].get(f"{d}/{input_name(source)}") != inp_sha or sha256_file(need) != inp_sha:
        raise StageError(JUDGE, "the input changed during the judgment")
    text = ask_for_paths(ctx, r["result"], root)
    parsed = parse_judge(text)
    write(judge_md, text)
    meta = {"input": input_name(source), "sha": inp_sha, "source_identity": ctx.source_identity,
            "explicit_rejudge": judge_only,
            "material_identity": {p: digest for p, digest in r["materials_expected"].items()
                                  if p in source_materials(d, source, root)}}
    write(meta_path, json.dumps(meta) + "\n")
    return parsed, meta


def judgment(ctx, need, inp_sha, judge_only):
    """(parsed judgment, its binding) for the cycle: reused when bound to the current input and source,
    otherwise asked anew. --judge-only always asks."""
    judge_md = os.path.join(ctx.cyc, "JUDGE.md")
    meta_path = os.path.join(ctx.apply_dir, "judge-input.json")
    meta = load_json(meta_path)
    # A judgment without a recorded input hash cannot be bound to this input, so it counts as changed.
    if os.path.isfile(judge_md) and meta.get("sha") != inp_sha:
        new_generation(ctx, judge_md, meta.get("sha"))
    parsed = None
    if os.path.isfile(judge_md) and not judge_only:
        parsed = _reused(ctx, judge_md, meta)
    if parsed is None:
        parsed, meta = _asked(ctx, need, inp_sha, judge_md, meta_path, judge_only)
    return parsed, meta


def ask_for_paths(ctx, text, root=None):
    """Return the judgment with files for the bundles that named none. The judge is asked once; a bundle
    still without files moves to the rejected list as an idea only, with the judge's reason."""
    try:
        data = judgment_data(text)
    except StageError:
        return text   # parse_judge reports the contract error.
    pathless = [b for b in data[BUNDLES] if needs_paths(b)]
    if not pathless:
        return text
    prompt = paths_prompt(pathless)
    write(os.path.join(ctx.cyc, "prompts", "judge-paths.md"), prompt)
    answer, named, why = "", {}, {}
    try:
        w = run_in_order("judge", None, f"{ctx.d}/prompts/judge-paths.md",
                         os.path.join(ctx.apply_dir, "judge-paths.receipt"), extra=WORKER_TREE,
                         root=root)
        if w["rc"] == 0 and w["status"] == "success":
            answer = w["result"]
    except WorkerUnavailable as e:
        why = {b.get("id"): f"the judge could not be asked ({e.reason})" for b in pathless}
    for reply in json_blocks(answer):
        if isinstance(reply, dict):
            named.update({x.get("id"): x.get("files") for x in reply.get(PATHS) or [] if isinstance(x, dict)})
            why.update({x.get("id"): str(x.get("reason", "")) for x in reply.get(IDEA_ONLY) or [] if isinstance(x, dict)})
    bundles, rejected = [], list(data.get(REJECTED) or [])
    for b in data[BUNDLES]:
        if not needs_paths(b):
            bundles.append(b)
            continue
        files = named.get(b.get("id"))
        if files and isinstance(files, list):
            bundles.append(dict(b, files=files))
        else:
            rejected.append({"id": b.get("id", "-"), "title": b.get("title", ""),
                             "reason": "idea only: " + (why.get(b.get("id")) or "the judge named no files")})
    merged = dict(data, **{BUNDLES: bundles, REJECTED: rejected})
    return text + "\n\n## Paths asked once\n" + answer.strip() + "\n\n" + json_block(merged)
