#!/usr/bin/env python3
"""Takes one bundle of a cycle from its record to its outcome: the reserved implementation attempts, the
build and checks of each candidate and the review; the bundle ends saved, refused, abandoned or pending
(tools/loop/lib/loop_outcome.py).

Each specification has at most MAX_IMPLEMENTATION_ATTEMPTS attempts, reserved durably before the worker
starts. A saved bundle's patch stays in the cycle's apply folder; nothing here writes into the working
tree, which comes from ctx.root."""
import datetime
import json
import os
import re
import shutil
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
from loop_checks import (baseline, checked_statement, context_bytes, context_over, evidence,  # noqa: E402
                         evidence_line, gate_candidate, new_failures, require_comparable_baseline, run_tests,
                         summarize_tests)
from loop_common import StageError, WorkerUnavailable, check_deadline, clip, normal_path, rel, sha256_bytes, write  # noqa: E402
from loop_edits import UnsafeEdit, apply_edits, build_candidate, parse_edits  # noqa: E402
from loop_isolate import Isolate  # noqa: E402
from loop_judging import (check_of, correction_materials, path_refusal, source_snapshot, spec_hash,  # noqa: E402
                          spec_of, verify_source_materials, verify_worker_source)
from loop_outcome import ABANDONED, PENDING, REFUSED, SAVED, is_terminal, pend, refuse  # noqa: E402
from loop_prompts import correction_prompt, impl_prompt, material_prompt  # noqa: E402
from loop_review import review  # noqa: E402
from loop_run import WORKER_TREE  # noqa: E402
from loop_worker import CEILING, run_in_order  # noqa: E402
import loop_policy  # noqa: E402

MAX_IMPLEMENTATION_ATTEMPTS = 2
# Consecutive runs that left one bundle pending because no model runtime could be called, before such a
# failure spends an attempt, so a worker that always crashes on one prompt still ends abandoned.
WORKER_ENV_HOLD_MAX = 3
_TEST_FILE = r"tools/tests/test_[^/]+\.py"


def _attempt_names(bid):
    """The files one attempt writes in the apply folder; a new attempt starts without them."""
    return (f"impl-{bid}.result.md", f"impl-{bid}.receipt", f"{bid}.patch",
            f"{bid}.tests.json", f"{bid}.tests.txt", f"review-{bid}.result.md",
            f"{bid}.original-tests.json", f"{bid}.counterfactual-tests.json",
            f"{bid}.verification.json", f"review-{bid}.receipt", f"{bid}.gate.txt")


def prior_record(ctx, b, prev):
    """Give the bundle the record a previous run left for the same specification, if any: this cycle's
    record of the bundle, else the one an older input of the cycle left (prior_results)."""
    b["_spec"] = spec_hash(b)
    p = prev.get(b["id"])
    if not p or p.get("spec") != b["_spec"]:
        candidates = [r for r in ctx.state.get("prior_results", {}).values() if r.get("spec") == b["_spec"]]
        p = max(candidates, key=lambda r: len(r.get("attempts", [])), default=None)
    if not p:
        return
    b["_r"] = dict(p)
    if is_terminal(b["_r"]):
        ctx.notes.append(f"{b['id']}: the previous run's result is kept ({p['result']})")


def archive_attempt(ctx, b, attempt):
    target = os.path.join(ctx.root, attempt["artifacts"])
    os.makedirs(target, exist_ok=True)
    bid = b["id"]
    for name in (*_attempt_names(bid), f"{bid}.spec.json"):
        src = os.path.join(ctx.apply_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(target, name))
    for kind in ("impl", "review"):
        src = os.path.join(ctx.cyc, "prompts", f"{kind}-{bid}.md")
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(target, f"{kind}-prompt.md"))
    write(os.path.join(target, "attempt.json"), json.dumps(attempt, ensure_ascii=False, indent=1) + "\n")


def gate_verdict(ctx, r, gate):
    """Apply the clone commit check. Return True when review may proceed. A base that fails the check
    too is only noted: no commit is made here, but the owner's own next commit may be refused."""
    r["gate"] = gate["summary"]
    if gate["status"] == "env":
        ctx.blocked.append(gate["line"])
    elif gate["status"] == "patch":
        refuse(r, "gate", f"the commit check (gate) fails while the base passes: {gate['line']}")
        return False
    return True


def _implementation(ctx, b, r):
    """The implementation worker's final answer."""
    bid, d, root = b["id"], ctx.d, ctx.root
    impl_path = os.path.join(ctx.apply_dir, f"impl-{bid}.result.md")
    stage = f"implement({bid})"
    verify_source_materials(ctx, stage, root)
    prompt = impl_prompt(b, d) + material_prompt(ctx.material_identity) + correction_prompt(r, check_of(b))
    write(os.path.join(ctx.cyc, "prompts", f"impl-{bid}.md"), prompt)
    w = run_in_order("implement", None, f"{d}/prompts/impl-{bid}.md",
                     os.path.join(ctx.apply_dir, f"impl-{bid}.receipt"), extra=WORKER_TREE,
                     read_materials=(*ctx.material_identity, *correction_materials(r, root)), root=root)
    r["impl_runtime"] = w["runtime"]
    if w["result"]:
        write(impl_path, w["result"])
    if w["rc"] != 0 or w["status"] != "success" or not w["result"].strip():
        raise WorkerUnavailable(stage, f"implementation worker failed rc={w['rc']} status={w['status']} {w['detail']}")
    r.pop("worker_env_holds", None)
    verify_worker_source(w, r["source_identity"], stage, root)
    verify_source_materials(ctx, stage, root)
    write(impl_path, w["result"])
    r["impl_summary"] = clip((w["contract"] or {}).get("summary", ""), 120)
    return w["result"]


def _edits(r, impl_text):
    """The edit blocks of the final answer, or None after recording why there are none."""
    try:
        edits = parse_edits(impl_text)
    except ValueError as e:
        refuse(r, "delivery", f"malformed edit blocks ({e})")
        return None
    if not edits:
        refuse(r, "delivery", f"the implementation worker gave no edit block ({r.get('impl_summary', '')})")
        return None
    return edits


def _refused_candidate(ctx, b, r, c):
    """The checks that need no test run, in order; True after a refusal (the candidate starts no test run)."""
    if not c["changed"]:
        refuse(r, "patch", "the patch is an empty diff", final=True)
        return True
    outside = [p for p in c["changed"] if p not in b["files"] or not normal_path(p)
               or path_refusal(p)]
    if outside:
        refuse(r, "patch", "changes outside the bundle: " + ", ".join(outside), final=True)
        return True
    if loop_policy.loop_only(c["changed"]) and not loop_policy.loop_only(b["files"]):
        # The cycle's cap of one loop-only bundle was counted on the declared files.
        refuse(r, "patch", "the patch changes only the loop's own tools, but its bundle was judged as more: "
               + ", ".join(c["changed"]), final=True)
        return True
    context, r["loaded_files"] = context_over(c["iso"], c["changed"])
    if context:
        refuse(r, "patch", context)
        return True
    c["gate"] = gate_candidate(ctx, b["id"], c["base_sha"], c["patch_path"], c["changed"], ctx.root)
    if c["gate"]["status"] == "patch":
        gate_verdict(ctx, r, c["gate"])
        return True
    return False


def _build_and_test(ctx, b, r, edits, base_sha, patch_path):
    """Build the candidate in a clone pinned to base_sha, run the checks that need no test run, then the
    baseline and the candidate's tests. Return the candidate, or None after a refusal."""
    root = ctx.root
    with Isolate(base_sha, root) as iso:
        original_tests = {path: open(os.path.join(iso.tree, path), "rb").read()
                          for path in b["files"] if re.fullmatch(_TEST_FILE, path)
                          and os.path.isfile(os.path.join(iso.tree, path))}
        try:
            patch, changed, new_files, expected = build_candidate(iso, edits, b["files"])
        except ValueError as e:
            refuse(r, "patch", f"the patch cannot be applied ({e})", final=isinstance(e, UnsafeEdit))
            return None
        write(patch_path, patch)
        c = {"iso": iso, "patch_path": patch_path, "patch_sha": sha256_bytes(patch), "base_sha": base_sha,
             "changed": changed, "new_files": new_files, "expected": expected, "original_tests": original_tests}
        if _refused_candidate(ctx, b, r, c):
            return None
        c["base"] = baseline(ctx, base_sha, root)
        c["tests"] = run_tests(iso, keep_failing=True)
        if check_of(b)["kind"] == "cost":
            with Isolate(base_sha, root) as base_iso:
                before = context_bytes(base_iso.command, base_iso.tree, base_iso.env())
            c["cost"] = (before, context_bytes(iso.command, iso.tree, iso.env()))
    del c["iso"]
    return c


def _diagnostics(ctx, b, c, edits):
    """(oracle, counterfactual): the original tests on the candidate code, and the candidate's tests on
    the base code. Each runs in a fresh clone, since candidate tests may have changed their own."""
    root, base_sha = ctx.root, c["base_sha"]
    # Re-run the pre-change oracle against candidate production code without executing
    # the rewritten tests that could merely print the baseline PASS IDs.
    originals_changed = {path: raw for path, raw in c["original_tests"].items() if path in c["changed"]}
    oracle = {}
    if originals_changed:
        with Isolate(base_sha, root) as oracle_iso:
            apply_edits(oracle_iso.tree, edits, b["files"])
            for path, raw in originals_changed.items():
                write(os.path.join(oracle_iso.tree, path), raw, mode=0o644)
            oracle = run_tests(oracle_iso, [os.path.join(oracle_iso.tree, path) for path in originals_changed])
    # Distinct diagnostic: candidate tests against unchanged base implementation. This asks
    # whether the new test detects the old defect, not whether old tests still pass new code.
    # No blanket FAIL requirement: features, refactors and observational changes differ.
    counterfactual = {}
    changed_tests = [path for path in c["changed"] if re.fullmatch(_TEST_FILE, path)]
    if changed_tests:
        with Isolate(base_sha, root) as counter_iso:
            apply_edits(counter_iso.tree, [edit for edit in edits if edit[1] in changed_tests], changed_tests)
            counterfactual = run_tests(counter_iso, [os.path.join(counter_iso.tree, path) for path in changed_tests],
                                       diagnostic=True)
    return oracle, counterfactual


def _test_verdict(ctx, b, r, c, oracle, counterfactual):
    """Write the test results, compare them with the baseline, and return the new failures."""
    bid, apply_dir, base, cand = b["id"], ctx.apply_dir, c["base"], c["tests"]
    write(os.path.join(apply_dir, f"{bid}.tests.json"), json.dumps(cand, ensure_ascii=False, indent=1) + "\n")
    bad = new_failures(base, cand)
    # The output of a file with new failures stays for the next attempt's correction prompt.
    for name, res in cand.items():
        if "output" in res and not new_failures({name: base[name]} if name in base else {}, {name: res}):
            del res["output"]
    r["test_output"] = {name: res["output"] for name, res in cand.items() if "output" in res}
    oracle_base = {name: base[name] for name in oracle if name in base}
    bad += [f"original-oracle:{issue}" for issue in new_failures(oracle_base, oracle)]
    if oracle:
        write(os.path.join(apply_dir, f"{bid}.original-tests.json"), json.dumps(oracle, ensure_ascii=False, indent=1) + "\n")
    if counterfactual:
        write(os.path.join(apply_dir, f"{bid}.counterfactual-tests.json"),
              json.dumps(counterfactual, ensure_ascii=False, indent=1) + "\n")
    r["tests"] = (f"{summarize_tests(cand)} in the sandbox, {len(bad)} new failures (starting commit "
                  f"{c['base_sha'][:12]}: {summarize_tests(base)})")
    c["tests_txt"] = os.path.join(apply_dir, f"{bid}.tests.txt")
    write(c["tests_txt"], r["tests"] + "\n" + "\n".join(f"- {x}" for x in bad) + "\n")
    return bad


def _detail_paths(ctx, b, c, oracle, counterfactual):
    bid, root, apply_dir = b["id"], ctx.root, ctx.apply_dir
    paths = [rel(root, os.path.join(apply_dir, f"{bid}.tests.json")),
             rel(root, os.path.join(apply_dir, f"tests-baseline-{c['base_sha'][:12]}.json"))]
    if oracle:
        paths.append(rel(root, os.path.join(apply_dir, f"{bid}.original-tests.json")))
    if counterfactual:
        paths.append(rel(root, os.path.join(apply_dir, f"{bid}.counterfactual-tests.json")))
    return paths


def bundle_attempt(ctx, b, r):
    """One implementation attempt: build, check and test the candidate, then the review; SAVED after a PASS."""
    bid, root = b["id"], ctx.root
    spec_path = os.path.join(ctx.apply_dir, f"{bid}.spec.json")
    write(spec_path, json.dumps(spec_of(b), ensure_ascii=False, indent=1) + "\n")
    answer = _implementation(ctx, b, r)
    edits = _edits(r, answer)
    if edits is None:
        return
    patch_path = os.path.join(ctx.apply_dir, f"{bid}.patch")
    r["patch"] = rel(root, patch_path)
    # Validate baseline and candidate from the same pinned base SHA.
    check_deadline(f"verify({bid})")
    if source_snapshot(root) != r["source_identity"]:
        raise StageError(f"verify({bid})", "the source changed before verification", kind="source-changed")
    c = _build_and_test(ctx, b, r, edits, r["snapshot_rev"], patch_path)
    if c is None:
        return
    oracle, counterfactual = _diagnostics(ctx, b, c, edits)
    bad = _test_verdict(ctx, b, r, c, oracle, counterfactual)
    if bad:
        refuse(r, "tests", "new test failures: " + ", ".join(bad[:4]))
        return
    with open(patch_path, "rb") as f:
        r["evidence"] = evidence(check_of(b), f.read(), checked_statement(answer), counterfactual, c["base"],
                                 c["tests"], c.get("cost"))
    if not r["evidence"]["holds"]:
        refuse(r, "evidence", "the bundle's check does not hold: " + r["evidence"]["reason"])
        return
    c["detail_paths"] = _detail_paths(ctx, b, c, oracle, counterfactual)
    if not gate_verdict(ctx, r, c["gate"]):
        return
    if c["gate"]["status"] != "skipped":
        c["detail_paths"].append(rel(root, os.path.join(ctx.apply_dir, f"{bid}.gate.txt")))
    c["spec_path"] = spec_path
    if review(ctx, b, r, c):
        r["outcome"], r["result"], r["effect"] = SAVED, f"{SAVED}: {r['patch']}", evidence_line(r["evidence"])


def _reserve(ctx, b, r, attempts):
    """Check the source and the base, then reserve the next attempt durably before any worker starts.
    Return the attempt, or None when the bundle is pending. A baseline that cannot be compared stops the
    cycle here."""
    root, identity = ctx.root, ctx.source_identity
    if source_snapshot(root) != identity:
        pend(r, "the working tree changed during the run; the next run builds it on the tree as it is then")
        return None
    r["snapshot_rev"] = ctx.test_base()
    require_comparable_baseline(ctx, r["snapshot_rev"], root)
    sid = sha256_bytes(json.dumps(identity, sort_keys=True).encode())[:12]
    n = len(attempts) + 1
    if not r.get("attempt_namespace"):
        namespace = f"{ctx.d}/apply/attempts/{b['id']}-{b['_spec'][:12]}-{sid}"
        base_namespace, number = namespace, 1
        while os.path.exists(os.path.join(root, namespace)):
            number += 1
            namespace = f"{base_namespace}-{number}"
        r["attempt_namespace"] = namespace
    artifact_rel = f"{r['attempt_namespace']}/attempt-{n}"
    attempt = {"number": n, "status": "running", "source_identity": identity,
               "artifacts": artifact_rel, "started_at": datetime.datetime.now().isoformat(timespec="seconds")}
    attempts.append(attempt)
    for key in ("result", "outcome", "tests", "review", "patch", "reject_kind", "refused_at", "evidence",
                "test_output"):
        r.pop(key, None)
    os.makedirs(os.path.join(root, artifact_rel), exist_ok=True)
    ctx.save([b])  # Reservation is durable BEFORE the implementation worker starts, including crash cases.
    for name in _attempt_names(b["id"]):
        path = os.path.join(ctx.apply_dir, name)
        if os.path.isfile(path):
            os.unlink(path)  # Previous versions have already been retained in the attempt directory.
    return attempt


def _settle(ctx, b, r, attempt):
    """Record how an attempt ended, archive it, and return True when the bundle is settled or pending."""
    result, test_output = r.get("result", ""), r.pop("test_output", None)
    if r.get("reject_kind") == "final":
        r["outcome"] = REFUSED
    elif r.get("outcome") not in (SAVED, PENDING):
        attempt.setdefault("failure_stage", r.get("refused_at") or "patch")
        attempt["feedback"] = result
        if test_output:
            attempt["test_output"] = test_output
    attempt["status"] = r.get("outcome", "failed")
    attempt.setdefault("feedback", result)
    archive_attempt(ctx, b, attempt)
    ctx.save([b])
    return r.get("outcome") in (SAVED, REFUSED, PENDING)


def _given_back(ctx, b, r, attempts, e):
    """Pend the bundle and give the reserved attempt back when no model runtime could be called or the
    cycle reached its token ceiling; True when it did. A runtime that keeps failing on one bundle spends
    an attempt from the WORKER_ENV_HOLD_MAX-th time on, so it still ends."""
    if not isinstance(e, WorkerUnavailable):
        return False
    if e.kind == CEILING:
        ctx.ceiling = True
        pend(r, f"{e.reason}; raising loop.token_ceiling lets the next run continue it")
    elif r.get("worker_env_holds", 0) < WORKER_ENV_HOLD_MAX:
        r["worker_env_holds"] = r.get("worker_env_holds", 0) + 1
        pend(r, f"no model runtime could be called ({e.reason}); the next run tries again")
    else:
        return False
    attempts.pop()
    ctx.save([b])
    return True


def _attempt(ctx, b, r, attempts, attempt):
    """Run one reserved attempt. Return True when the bundle is settled or pending."""
    try:
        bundle_attempt(ctx, b, r)
    except StageError as e:
        if _given_back(ctx, b, r, attempts, e):
            return True
        if e.kind == "source-changed":
            pend(r, f"{e.reason}; the next run builds it again")
        else:
            refuse(r, e.stage, f"{e.stage}: {e.reason}")
        attempt["failure_stage"] = e.stage
    return _settle(ctx, b, r, attempt)


def run_bundle(ctx, b, r):
    """Two durable dispatch reservations, then ABANDONED with the last attempt's reason."""
    r["source_identity"], r["base_rev"] = ctx.source_identity, ctx.source_identity["base_rev"]
    attempts = r.setdefault("attempts", [])
    if attempts and attempts[-1].get("status") == "running":
        attempts[-1].update(status="failed", failure_stage="interrupted",
                            feedback="the reserved attempt stopped before its end was recorded; it counts as one attempt")
        archive_attempt(ctx, b, attempts[-1])
    while len(attempts) < MAX_IMPLEMENTATION_ATTEMPTS:
        attempt = _reserve(ctx, b, r, attempts)
        if attempt is None or _attempt(ctx, b, r, attempts, attempt):
            return
    r["outcome"] = ABANDONED
    r["result"] = (f"{ABANDONED}: {len(attempts)}/{MAX_IMPLEMENTATION_ATTEMPTS} attempts, last: "
                   f"{attempts[-1].get('feedback', 'interrupted')}")
    ctx.save([b])
