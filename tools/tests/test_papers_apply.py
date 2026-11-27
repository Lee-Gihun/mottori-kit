#!/usr/bin/env python3
"""Test proposal application and the papers cycle in temporary repositories.

A fake runtime handles worker calls. Real model CLIs, cycle folders, and trigger
stores are not used."""
import ast
import datetime
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from testlib import macos_only

HERE = Path(__file__).resolve().parent.parent
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
CYCLE = "_private/work/papers/2026-10-07-kit"
# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/papers_apply.py",
    "tools/loop/loop_policy.py",
    "tools/loop/lib/loop_bundle.py",
    "tools/loop/lib/loop_checks.py",
    "tools/loop/lib/loop_common.py",
    "tools/loop/lib/loop_edits.py",
    "tools/loop/lib/loop_isolate.py",
    "tools/loop/lib/loop_judge.py",
    "tools/loop/lib/loop_judging.py",
    "tools/loop/lib/loop_macos_sandbox.py",
    "tools/loop/lib/loop_outcome.py",
    "tools/loop/lib/loop_prompts.py",
    "tools/loop/lib/loop_report.py",
    "tools/loop/lib/loop_review.py",
    "tools/loop/lib/loop_run.py",
    "tools/loop/lib/loop_state.py",
    "tools/loop/lib/loop_stores.py",
    "tools/loop/lib/loop_worker.py",
)
# Why a test that builds a candidate, or runs something in the sandbox, is skipped on another platform.
SANDBOX = "the sandbox a candidate is built and tested in"
TODAY = "2026-10-08"

FAKE_WORKER = r'''
import json, os, sys, itertools, hashlib, subprocess
args = sys.argv[1:]
prompt = args[-1]
resp = os.environ["FAKE_RESPONSES"]
base = os.path.basename(prompt)[:-3]
runtime = args[args.index("--runtime") + 1]
open(os.path.join(resp, "calls.log"), "a").write(json.dumps(args) + "\n")
def name_run(run):
    # The worker tool names its run in the --run-file; the printed receipt is for people.
    if "--run-file" in args:
        open(args[args.index("--run-file") + 1], "w").write(json.dumps({"run_id": os.path.basename(run), "run_dir": run}))
if os.path.exists(os.path.join(resp, "unavailable-" + runtime)):
    # Fails the way a runtime that cannot be called fails: exit 1, no result, the record says why.
    run = f"_private/work/runs/fake-{base}-{runtime}-{len(os.listdir(resp))}"
    os.makedirs(run, exist_ok=True)
    name_run(run)
    open(os.path.join(run, "meta.json"), "w").write(json.dumps({
        "runtime": runtime, "model": None, "status": "failed", "process_exit": 1, "launch_error": None,
        "result_bytes": 0, "unavailable": "model-not-available"}))
    open(os.path.join(run, "result-contract.json"), "w").write(json.dumps({"valid": False, "error": "result is missing"}))
    print(f"FRESH_WORKER v1\nrun: {run}\nstatus: failed")
    sys.exit(1)
count = sum(1 for line in open(os.path.join(resp, "calls.log")) if json.loads(line)[-1] == prompt)
src = os.path.join(resp, base + f"-attempt-{count}.txt")
if not os.path.exists(src):
    src = os.path.join(resp, base + ".txt")
if not os.path.exists(src):
    print("status: failed"); sys.exit(1)
text = open(src, encoding="utf-8").read()
sys.path.insert(0, "tools/lib")
import paths
files = [paths.tracked_name(path_of) for path_of in paths.POLICY_FILES]
identity = {"base_rev": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "instance_sha256": {p: hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else None for p in files},
            "material_sha256": {args[i + 1]: hashlib.sha256(open(args[i + 1], "rb").read()).hexdigest()
                                for i, arg in enumerate(args) if arg == "--read-material"},
            "material_integrity": True}
# The tree the worker tool starts from: HEAD, plus the tracked changes for a dirty worktree.
if "--worktree" in args:
    import tempfile
    with tempfile.TemporaryDirectory() as scratch:
        git_env = dict(os.environ, GIT_INDEX_FILE=os.path.join(scratch, "index"))
        subprocess.run(["git", "read-tree", "HEAD"], env=git_env, check=True)
        if args[args.index("--worktree") + 1] == "dirty":
            subprocess.run(["git", "add", "-u"], env=git_env, check=True)
        identity["base_tree"] = subprocess.check_output(["git", "write-tree"], env=git_env, text=True).strip()
hook = os.path.join(resp, base + ".sh")
if os.path.exists(hook):
    import subprocess
    subprocess.run(["bash", hook], check=False)
rcf = os.path.join(resp, base + ".rc")
rc = int(open(rcf).read()) if os.path.exists(rcf) else 0
n = len(os.listdir(resp))
run = f"_private/work/runs/fake-{base}-{n}"
os.makedirs(run, exist_ok=True)
name_run(run)
open(os.path.join(run, "meta.json"), "w").write(json.dumps({"worktree": identity, "runtime": runtime,
                                                           # FAKE_RECEIPT=lie: the record says failed, the receipt success.
                                                           "status": "success" if rc == 0 and os.environ.get("FAKE_RECEIPT") != "lie" else "failed",
                                                           "model": "fake-" + runtime + "-model"}))
open(os.path.join(run, "result.txt"), "w", encoding="utf-8").write(text)
last = [l for l in text.splitlines() if l.strip()][-1]
contract = {"valid": False, "verdict": "INCONCLUSIVE", "summary": ""}
if last.startswith("RESULT_JSON: "):
    contract = dict(json.loads(last[len("RESULT_JSON: "):]), valid=True)
open(os.path.join(run, "result-contract.json"), "w").write(json.dumps(contract))
if os.environ.get("FAKE_RECEIPT") == "nonsense":
    print("~~ nothing to read here ~~")
else:
    print(f"FRESH_WORKER v1\nrun: {run}\nstatus: {'success' if rc == 0 else 'failed'}\nresult:\n{text[:200]}")
sys.exit(rc)
'''

FAKE_TOOL = r'''
import json, os, sys
os.makedirs("_private", exist_ok=True)
open("_private/calls.log", "a").write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:], ensure_ascii=False) + "\n")
'''

TEST_LIB = '''import sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import lib
if lib.VALUE == 1:
    print("PASS value")
    sys.exit(0)
print("FAIL value")
sys.exit(1)
'''

PASS = 'RESULT_JSON: {"verdict":"PASS","summary":"ok","evidence":["tools/lib.py:1"],"unknowns":[]}'
FAIL = 'RESULT_JSON: {"verdict":"FAIL","summary":"bug found","evidence":["tools/lib.py:1"],"unknowns":[]}'


# A cost check every fixture change meets: the stand-in context_budget.py counts AGENTS.md, which it leaves alone.
COST_CHECK = {"kind": "cost", "target": "context-bytes", "pass": 1000}


def bundle(bid="bump", kind="observe", files=("tools/lib.py", "tools/tests/test_lib.py"), check=None):
    """A judged bundle. Observe by default: it needs no check. An act bundle needs one to be selected."""
    b = {"id": bid, "title": f"bundle {bid}", "kind": kind, "files": list(files),
         "change": "add the EXTRA constant", "success_metric": "test_lib passes", "stop_condition": "one regression",
         "rollback": "this commit", "rejudge_date": "2026-10-21", "source": "rank 1"}
    return dict(b, check=check) if check else b


def judge_text(bundles, lens=True, rejected=()):
    head = f"{LCo.LENS_HEADING}\n- ledger: does not change\n- inversion: does not change\n\n" if lens else ""
    data = {"summary": "s", "bundles": bundles, "rejected": list(rejected)}
    return head + "## Judgment\nbody\n\n```json\n" + json.dumps(data, ensure_ascii=False) + "\n```\n" + PASS + "\n"


EDIT_OK = "note\n@@@ EDIT tools/lib.py\n@@@ SEARCH\nVALUE = 1\n@@@ REPLACE\nVALUE = 1\nEXTRA = 2\n@@@ END\n" + PASS + "\n"
EDIT_BREAK = "@@@ EDIT tools/lib.py\n@@@ SEARCH\nVALUE = 1\n@@@ REPLACE\nVALUE = 2\n@@@ END\n" + PASS + "\n"
EDIT_OUTSIDE = "@@@ EDIT other.txt\n@@@ SEARCH\nother\n@@@ REPLACE\nchanged\n@@@ END\n" + PASS + "\n"


def sh(root, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError(p.stderr)
    return p.stdout


def copy_loop(tools):
    """Copy the loop's modules (tools/loop/loop_*.py, tools/loop/lib/loop_*.py), the applier and the engine modules the beats import into a scratch tree's tools folder."""
    (tools / "lib").mkdir(exist_ok=True)
    (tools / "loop" / "lib").mkdir(parents=True, exist_ok=True)
    for src in sorted(HERE.glob("loop/lib/loop_*.py")) + sorted(HERE.glob("loop/loop_*.py")) + [HERE / "loop" / "papers_apply.py", HERE / "lib" / "paths.py",
                                                 HERE / "lib" / "safeio.py", HERE / "lib" / "config.py"]:
        shutil.copy2(src, tools / src.relative_to(HERE))


def set_config(root, **block):
    """Write the fixture's settings: papers may send, and the loop block has the keys given."""
    (root / "instance" / "config.json").write_text(json.dumps({"egress": {"model_send": {
        "deny_prefixes": ["_private/"], "allow_prefixes": ["_private/work/papers/"]}},
        "loop": block}))


def fixture():
    """A scratch tree with the loop, a fake library and a papers cycle. Its configuration is ignored by
    Git there, so a test can change it between runs without a commit."""
    root = Path(tempfile.mkdtemp(prefix="papers-apply-fixture-"))
    (root / "tools").mkdir()
    copy_loop(root / "tools")
    shutil.copy2(HERE / "fresh_worker.py", root / "tools" / "fresh_worker.py")
    (root / "tools" / "lib.py").write_text("VALUE = 1\n")
    (root / "tools" / "tests").mkdir()
    (root / "tools" / "tests" / "test_lib.py").write_text(TEST_LIB)
    (root / "tools" / "triggers.py").write_text(FAKE_TOOL)
    (root / "tools" / "now.py").write_text(FAKE_TOOL)
    (root / "system" / "lenses").mkdir(parents=True)
    (root / "instance").mkdir()
    (root / "system" / "lenses" / "README.md").write_text("# Lenses\n")
    (root / "system" / "lenses" / "ledger.md").write_text("# Ledger\n")
    (root / "other.txt").write_text("other\n")
    (root / ".gitignore").write_text("_private/\n_fake/\ninstance/config.json\n")
    set_config(root)
    hooks = root / "_fake" / "hooks"
    hooks.mkdir(parents=True)
    (root / "_fake" / "fake_worker.py").write_text(FAKE_WORKER)
    (root / "_fake" / "resp").mkdir()
    cyc = root / CYCLE
    cyc.mkdir(parents=True)
    (cyc / "PROPOSALS.md").write_text("# Proposals\n" + "### rank 1 something\n" * 30)
    (root / "_private" / "work" / "experiments.md").write_text(
        "# Registry\n\n| ID | Experiment | Trigger | Due | Measures | Status | Verdicts |\n|---|---|---|---|---|---|---|\n"
        "| X1 | a | b | c | d | e | f |\n\n## Verdicts\n| X16 | z | b | c | d | e | f |\n\n2026-09-28 verdict:\n- done\n")
    sh(root, "init", "-q")
    sh(root, "config", "user.name", "t")
    sh(root, "config", "user.email", "t@example.invalid")
    sh(root, "config", "core.hooksPath", str(hooks))
    sh(root, "add", "-A")
    sh(root, "commit", "-q", "-m", "init")
    return root


def worker_env(root, today=TODAY):
    return {"MOTTORI_APPLY_WORKER_CMD": f"{sys.executable} {root / '_fake' / 'fake_worker.py'}",
            "FAKE_RESPONSES": str(root / "_fake" / "resp"), "MOTTORI_APPLY_TODAY": today}


def respond(root, **files):
    for name, text in files.items():
        (root / "_fake" / "resp" / f"{name.replace('_', '-')}.txt").write_text(text)


def run_apply(root, *args):
    return run_apply_env(root, {}, *args)


def head(root):
    return sh(root, "rev-parse", "HEAD").strip()


def calls(root):
    p = root / "_private" / "calls.log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def load(module_path, name):
    spec = importlib.util.spec_from_file_location(name, module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PA = load(HERE / "loop" / "papers_apply.py", "papers_apply_under_test")
LS = load(HERE / "loop" / "lib" / "loop_state.py", "loop_state_under_test")
LJ = load(HERE / "loop" / "lib" / "loop_judging.py", "loop_judging_under_test")
# The applier's own modules, as the applier above imported them.
import loop_checks as LK  # noqa: E402
import loop_common as LC  # noqa: E402
import loop_edits as LE  # noqa: E402
import loop_isolate as LI  # noqa: E402
import loop_prompts as LP  # noqa: E402
import loop_worker as LW  # noqa: E402
import loop_bundle as LB  # noqa: E402
import loop_run as LR  # noqa: E402
import loop_policy as LPo  # noqa: E402
import loop_outcome as LO  # noqa: E402
import loop_report as LRp  # noqa: E402
import loop_contracts as LCo  # noqa: E402
import loop_config as LCf  # noqa: E402


# ---------------------------------------------------------------- Unit tests
def test_parse_judge_json_and_bundle_cap():
    sel, rej, summ = LJ.parse_judge(judge_text(
        [bundle("a", "act", check=COST_CHECK), bundle("b", "observe"), bundle("c", "act", check=COST_CHECK)],
        rejected=[{"id": "-", "title": "rank 5", "reason": "weak grounds"}]))
    assert [b["id"] for b in sel] == ["a", "b"], sel
    assert any(r["id"] == "c" and "cap" in r["reason"] for r in rej), rej
    assert any("weak grounds" in r["reason"] for r in rej), rej
    assert summ == "s"
    # Rule, gate and engine files are selectable like any harness file; a never-list path is refused by name.
    sel, rej, _ = LJ.parse_judge(judge_text([bundle("p", "act", files=("AGENTS.md",), check=COST_CHECK),
                                             bundle("r", "observe", files=("state/NOW.md",)),
                                             bundle("q", "observe", files=("tools/gate.py",))]))
    assert [b["id"] for b in sel] == ["p", "q"], sel
    assert any(r["id"] == "r" and r["reason"] == "on the never list: state/NOW.md" for r in rej), rej


def test_parse_judge_accepts_a_judgment_without_lens_section_and_requires_json():
    # The lens section is written only when a lens changed the selection.
    sel, rej, _ = LJ.parse_judge(judge_text([bundle()], lens=False))
    assert [b["id"] for b in sel] == ["bump"] and rej == [], (sel, rej)
    try:
        LJ.parse_judge(LCo.LENS_HEADING + "\n- x\nbody only\n" + PASS)
    except LC.StageError as e:
        assert "JSON" in e.reason, e.reason
    else:
        raise AssertionError("StageError expected")


def test_report_names_a_refused_idea_without_id_by_its_title():
    root = Path(tempfile.mkdtemp(prefix="report-refused-"))
    try:
        refused = [{"id": "-", "title": "rank 4 idea", "reason": "weak grounds"},
                   {"id": "-", "title": "rank 5 idea", "reason": "weak grounds"},
                   {"id": "G1-2", "title": "a titled bundle", "reason": "duplicate id"}]
        rec = {"state": "done", "failure": None, "source": "papers", "cycle": CYCLE, "run_on": TODAY,
               "input": {"name": "PROPOSALS.md", "sha256": None}, "judge_summary": "s", "base_summary": None,
               "bundles": [], "refused": refused, "counts": LRp.counts([], refused), "blocked": [], "notes": []}
        (root / CYCLE / "apply").mkdir(parents=True)
        (root / CYCLE / LS.OUTCOME_REL).write_text(json.dumps(rec))
        LRp.draw(CYCLE, str(root))
        text = report_md(root)
        assert "- **rank 4 idea** refused, weak grounds" in text and "- **rank 5 idea** refused, weak grounds" in text, text
        assert "- **G1-2** refused, duplicate id" in text and "**-**" not in text, text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_parse_edits():
    edits = LE.parse_edits(EDIT_OK + "@@@ FILE tools/new.py\nx = 1\n@@@ END\n")
    assert edits[0][:2] == ("EDIT", "tools/lib.py") and edits[1] == ("FILE", "tools/new.py", "x = 1\n", None)


@macos_only(SANDBOX, sandbox=True)
def test_review_fail_rejects():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=FAIL)
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr
        assert outcome_of(root)["state"] == "done" and entry(root)["outcome"] == "abandoned"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_edit_outside_bundle_rejects():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OUTSIDE, review_bump=PASS)
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before
        assert "edits a file outside the bundle: other.txt" in entry(root)["reason"], entry(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_failure_is_loud_and_retryable():
    root = fixture()
    try:
        r = run_apply(root, CYCLE)  # Missing judgment output is a worker failure.
        assert r.returncode != 0
        failure = outcome_of(root)["failure"]
        assert outcome_of(root)["state"] == "failed" and failure["stage"] == "judge", report_md(root)
        assert report_md(root).splitlines()[2].startswith("**Status:** failed at judge: the judge worker failed"), report_md(root)
        assert "the judge worker failed rc=" in failure["reason"] and "source identity" not in failure["reason"], failure
        assert LS.apply_status(str(root / CYCLE)) == "failed"
        assert not any(x[0] == "triggers.py" for x in calls(root)), calls(root)
        respond(root, judge=LCo.LENS_HEADING + "\n- x\nbody only\n" + PASS + "\n")
        r = run_apply(root, CYCLE)
        assert r.returncode != 0 and "JSON" in outcome_of(root)["failure"]["reason"], outcome_of(root)
        respond(root, judge=judge_text([]))
        r = run_apply(root, CYCLE)
        assert r.returncode == 0, r.stdout + r.stderr
        assert outcome_of(root)["state"] == "done"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_judge_only_writes_no_apply():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]))
        r = run_apply(root, CYCLE, "--judge-only")
        assert r.returncode == 0 and "bundles 1" in r.stdout, r.stdout + r.stderr
        assert (root / CYCLE / "JUDGE.md").exists() and not (root / CYCLE / "REPORT.md").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_lock_prevents_concurrent_run():
    root = fixture()
    try:
        respond(root, judge=judge_text([]))
        lockp = root / CYCLE / "apply" / ".lock"
        lockp.parent.mkdir(parents=True, exist_ok=True)
        with open(lockp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = run_apply(root, CYCLE)
        assert r.returncode == 0 and "running" in r.stdout, r.stdout
        assert not (root / CYCLE / "REPORT.md").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write_outcome(cyc, state, sha=None, name="PROPOSALS.md"):
    """An outcome record as the applier writes it, with only the fields loop_state reads."""
    (cyc / "apply").mkdir(parents=True, exist_ok=True)
    (cyc / "apply" / "outcome.json").write_text(json.dumps({"state": state, "input": {"name": name, "sha256": sha}}))


def test_backlog_order():
    root = Path(tempfile.mkdtemp(prefix="papers-backlog-"))
    try:
        base = root / "_private" / "work" / "papers"
        spec = {"2026-09-19-kit": "done", "2026-09-30-kit": "failed", "2026-10-07-kit": None,
                "2026-09-24-dair": None, "2026-08-01-kit": "noprop", "2026-09-10-kit": "closed"}
        for name, apply in spec.items():
            (base / name).mkdir(parents=True)
            if apply != "noprop":
                (base / name / "PROPOSALS.md").write_text("x" * 300)
            if apply in ("done", "failed"):
                write_outcome(base / name, apply)
                (base / name / "APPLY.md").write_text("nonsense nobody reads\n")
            if apply == "closed":   # Judged before the outcome record existed.
                (base / name / "APPLY.md").write_text("# a\n\nStatus: failed (stage: judge, reason: x)\n")
        got = PA.backlog_dirs(str(root))
        assert got == ["_private/work/papers/2026-09-30-kit", "_private/work/papers/2026-10-07-kit"], got
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- Failure and recovery cases
def extra(root, name, text):
    (root / "_fake" / "resp" / name).write_text(text)


def worker_calls(root):
    p = root / "_fake" / "resp" / "calls.log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def report_md(root, cyc=CYCLE):
    return (root / cyc / "REPORT.md").read_text()


def _reports(root, st):
    """The applier's report and the cycle's report, as far as they were written, for a failure message."""
    out = []
    for p in (root / CYCLE / "REPORT.md", root / st.get("last_dir", "-") / "REPORT.md"):
        out.append(f"{p.name} in {p.parent.name}: " + (p.read_text()[-1500:] if p.is_file() else "(not written)"))
    return "\n".join(out)


def outcome_of(root, cyc=CYCLE):
    return json.loads((root / cyc / "apply" / "outcome.json").read_text())


def entry(root, bid="bump", cyc=CYCLE):
    """The bundle's entry in the cycle's outcome record."""
    return next(e for e in outcome_of(root, cyc)["bundles"] if e["id"] == bid)


@macos_only(SANDBOX, sandbox=True)
def test_r1_candidate_tests_cannot_write_outside_isolate():
    root = fixture()
    try:
        sentinel = Path(tempfile.mkdtemp(prefix="papers-sentinel-")) / "s.txt"
        sentinel.write_text("orig\n")
        evil = ("import subprocess, sys\nopen(%r, 'w').write('pwned')\n"
                "subprocess.run(['git', '-C', %r, 'commit', '--allow-empty', '-q', '-m', 'evil'], check=True)\n"
                "print('PASS evil')\n") % (str(sentinel), str(root))
        impl = "@@@ FILE tools/tests/test_lib.py\n" + evil + "@@@ END\n" + PASS + "\n"
        respond(root, judge=judge_text([bundle()]), impl_bump=impl, review_bump=PASS)
        before = head(root)
        n_commits = sh(root, "rev-list", "--count", "HEAD")
        r = run_apply(root, CYCLE)
        assert r.returncode == 0, r.stdout + r.stderr
        assert sentinel.read_text() == "orig\n", "a write outside the isolated copy happened"
        assert head(root) == before and sh(root, "rev-list", "--count", "HEAD") == n_commits
        assert "new test failures: test_lib.py" in entry(root)["reason"], entry(root)
        shutil.rmtree(sentinel.parent, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_r2_review_nonzero_exit_with_pass_is_not_adopted():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        extra(root, "review-bump.rc", "17")
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr
        t = report_md(root)
        assert entry(root)["outcome"] == "abandoned" and "rc=17" in t, t
        assert LS.apply_status(str(root / CYCLE)) == "done"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_r2_patch_replaced_during_review_is_rejected():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        extra(root, "review-bump.sh", f"echo 'diff --git a/x b/x' > {CYCLE}/apply/bump.patch\n")
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr
        # Changed patch bytes are not saved: the bundle is pending, and the next run builds it again.
        assert entry(root)["outcome"] == "pending" and "the patch bytes changed during the review" in entry(root)["reason"], entry(root)
        assert LS.apply_status(str(root / CYCLE)) == "pending"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_r3_r13_head_move_leaves_the_change_pending_and_judges_again():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        extra(root, "review-bump.sh", "echo moved > other.txt && git add other.txt && git commit -q -m other-session\n")
        r = run_apply(root, CYCLE)
        assert r.returncode == 0, r.stdout + r.stderr
        assert sh(root, "log", "--format=%s", "-2").splitlines() == ["other-session", "init"]
        assert entry(root)["outcome"] == "pending", entry(root)
        assert len(list((root / CYCLE / "apply").glob("tests-baseline-*.json"))) == 1
        assert (root / "tools" / "lib.py").read_text() == "VALUE = 1\n"
        # The next run judges again on the moved source and builds the change there.
        (root / "_fake" / "resp" / "review-bump.sh").unlink()
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and entry(root)["outcome"] == "saved", r.stdout + r.stderr + report_md(root)
        assert len([c for c in worker_calls(root) if c[-1].endswith("judge.md")]) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_r4_paths_normalized_and_symlinks_refused():
    for bad in ("system/./decisions.md", "tools//x.py", "./tools/x.py", "tools/../AGENTS.md", "tools/x.py "):
        assert LJ.validate_bundle(bundle(files=(bad,))), bad
    tree = Path(tempfile.mkdtemp(prefix="papers-sym-"))
    out = Path(tempfile.mkdtemp(prefix="papers-out-"))
    try:
        (out / "target.py").write_text("outside\n")
        (tree / "tools").mkdir()
        os.symlink(out / "target.py", tree / "tools" / "alias.py")
        os.symlink(out, tree / "linkdir")
        for edits, allowed in (([("FILE", "tools/alias.py", "x\n", None)], {"tools/alias.py"}),
                               ([("FILE", "linkdir/new.py", "x\n", None)], {"linkdir/new.py"})):
            try:
                LE.apply_edits(str(tree), edits, allowed)
            except ValueError:
                pass
            else:
                raise AssertionError(f"a write through a symlink was not refused: {edits}")
        assert (out / "target.py").read_text() == "outside\n" and not (out / "new.py").exists()
    finally:
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
    root = fixture()
    try:
        real = root / "_private" / "work" / "papers" / "real"
        real.mkdir()
        (real / "PROPOSALS.md").write_text("x" * 300)
        os.symlink(real, root / "_private" / "work" / "papers" / "2026-10-01-kit")
        r = run_apply(root, "_private/work/papers/2026-10-01-kit")
        assert r.returncode == 2 and not (real / "REPORT.md").exists(), r.stdout + r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_r6_hung_worker_is_killed_and_fails_loudly():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK)
        # A per-run duration, so a concurrent run of this suite cannot match our leftover check.
        nap = f"sleep 41.{os.getpid() % 10000:04d}"
        extra(root, "impl-bump.sh", nap + "\n")
        import time as _t
        t0 = _t.monotonic()
        env_extra = {"MOTTORI_APPLY_WORKER_TIMEOUT": "2"}
        r = run_apply_env(root, env_extra, CYCLE)
        assert _t.monotonic() - t0 < 60, "the time limit did not stop the worker"
        # A hung worker says nothing about the idea: pending for the next run, no attempt spent.
        assert "status=timeout" in report_md(root) and entry(root)["outcome"] == "pending", report_md(root)
        left = subprocess.run(["pgrep", "-fx", nap], capture_output=True, text=True).stdout.strip()
        assert not left, f"child processes left: {left}"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run_apply_env(root, extra_env, *args):
    # Inherited MOTTORI_* settings (timeouts, instance) would change what these tests assume, so only
    # explicit overrides reach the child.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MOTTORI_"))}
    env.update(worker_env(root), **extra_env)
    return subprocess.run([sys.executable, str(root / "tools" / "loop" / "papers_apply.py"), *args], cwd=root,
                          capture_output=True, text=True, env=env)


def test_r7_outcome_record_broken_or_missing_is_not_done():
    d = Path(tempfile.mkdtemp(prefix="papers-status-"))
    try:
        (d / "PROPOSALS.md").write_text("p" * 300)
        sha = LC.sha256_file(str(d / "PROPOSALS.md"))
        assert LS.apply_status(str(d)) is None
        # APPLY.md is for people: whatever it says, the record decides.
        (d / "APPLY.md").write_text("Status: done\n")
        for state in ("done", "pending", "token-ceiling", "failed"):
            write_outcome(d, state, sha)
            assert LS.apply_status(str(d)) == state, state
        record = d / "apply" / "outcome.json"
        # A record made before the outcome words of this loop has no state: the cycle is closed.
        record.write_text(json.dumps({"status": "held", "input": {"name": "PROPOSALS.md", "sha256": sha}}))
        assert LS.apply_status(str(d)) == "closed" and not LS.needs_processing(str(d))
        for text in ("x" * 120, "", "{}", '{"state": "complete"}', "[1]"):
            record.write_text(text)
            assert LS.apply_status(str(d)) == "failed", text
        record.write_bytes(b"\xff\xfe broken")
        assert LS.apply_status(str(d)) == "failed"
        # A symlink is refused even when its target holds a complete record.
        record.unlink()
        (d / "elsewhere.json").write_text(json.dumps({"state": "done"}))
        record.symlink_to(d / "elsewhere.json")
        assert LS.apply_status(str(d)) == "failed"
        record.unlink()
        write_outcome(d, "done", sha)
        (d / "PROPOSALS.md").write_text("q" * 300)
        assert LS.apply_status(str(d)) == "stale"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_r8_papers_cycle_shell_propagates_stage_failures():
    root = cycle_fixture()
    try:
        (root / "tools" / "loop" / "papers" / "fetch_arxiv.py").write_text("pass\n")
        # Triage exits with no output; the cycle must fail.
        (root / "tools" / "fresh_worker.py").write_text(
            FAKE_TOOL.replace("os.path.basename(sys.argv[0])", "'fresh_worker.py'") + "print('status: failed')\nsys.exit(3)\n")
        r, st, logt = run_cycle(root)
        assert r.returncode == 1 and st["status"] == "failed" and st["failed_stages"] == ["triage"], (r.returncode, st, logt)
        assert [x[:3] for x in calls(root) if x[0] == "now.py"] == [["now.py", "log", "--private"]], calls(root)
        # A failed worker with output still must not be accepted as a completed digest.
        date = st["last_cycle"]
        d = root / "_private" / "work" / "papers" / f"{date}-kit"
        (d / "triage.tsv").write_text("2601.00001\t3\tverify\n")
        r, st, logt = run_cycle(root, None, None, "--resume", date)
        assert r.returncode == 1 and st["status"] == "failed", (st, logt)
        # No card file ends the cycle before the proposal and digest workers are paid for.
        assert st["failed_stages"] == ["cards"] and not (d / "DIGEST-EN.md").exists(), st
        prompts = [x[-1] for x in calls(root) if x[0] == "fresh_worker.py"]
        assert not any(x.endswith(("propose.md", "digest-en.md")) for x in prompts), prompts
        assert not any(x[0] == "papers_apply.py" and "--backlog" not in x for x in calls(root)), \
            "the applier was called without proposals"
        # Skip when another process owns the lock.
        lk = root / "_private" / "papers" / "cycle.lock"
        with open(lk, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r, _, logt = run_cycle(root)
        assert r.returncode == 0 and "cycle.lock" in logt.splitlines()[-1], logt
    finally:
        shutil.rmtree(root, ignore_errors=True)


FAKE_CYCLE_WORKER = r"""
import json, os, sys, time
args = sys.argv[1:]
prompt = args[-1]
os.makedirs("_private", exist_ok=True)
open("_private/calls.log", "a").write(json.dumps(["fresh_worker.py"] + args) + "\n")
d = os.path.dirname(os.path.dirname(prompt))
name = os.path.basename(prompt)[:-3]
modes = json.loads(os.environ.get("FAKE_CYCLE", "{}"))
mode = modes.get(name, modes.get(name.split("-")[0], "ok"))
if mode.startswith("sleep:"):
    open(os.path.join("_private", f"sleeper-{name}.pid"), "w").write(str(os.getpid()))
    time.sleep(float(mode[6:]))
    mode = "ok"
if mode == "fail":
    print("status: failed"); sys.exit(3)
if name == "triage":
    open(os.path.join(d, "triage.tsv"), "w").write("2601.00001\t3\tverify\n")
elif name.startswith("card-"):
    open(os.path.join(d, "cards", f"group-{name[5:]}.md"), "w").write("card\n")
    print('```json\n{"cards": 1}\n```')
elif name == "propose":
    open(os.path.join(d, "PROPOSALS.md"), "w").write("### p1\n" + "x" * 250 + "\n")
elif name == "digest-en":
    run = "_private/work/runs/fake-digest"
    os.makedirs(run, exist_ok=True)
    open(os.path.join(run, "result.txt"), "w").write("digest\nRECEIPT: digest\n")
    open(os.path.join(run, "meta.json"), "w").write(json.dumps({"status": "success"}))
    open(args[args.index("--run-file") + 1], "w").write(json.dumps({"run_id": "fake-digest", "run_dir": run}))
    print(f"run: {run}")
print("status: success")
"""


def cycle_fixture(apply_rc=0):
    root = Path(tempfile.mkdtemp(prefix="papers-cycle-full-"))
    (root / "tools" / "loop" / "papers").mkdir(parents=True)
    (root / "system" / "loop" / "prompts").mkdir(parents=True)
    shutil.copy2(HERE / "loop" / "papers_cycle.sh", root / "tools" / "loop" / "papers_cycle.sh")
    copy_loop(root / "tools")
    for t in ("triage", "card", "propose", "digest-en"):
        (root / "system" / "loop" / "prompts" / f"{t}.md").write_text(f"{t} {{{{DIR}}}}\n")
    (root / "tools" / "loop" / "papers" / "sweep.py").write_text(
        "import sys\na=sys.argv; o=a[a.index('--out')+1]\nopen(o,'w').write('arxiv_id\\tx\\ttitle\\n2601.00001\\tx\\tT one\\n')\n")
    (root / "tools" / "loop" / "papers" / "fetch_arxiv.py").write_text(
        "import os,sys\nfor l in open(sys.argv[1]):\n    i=l.split('\\t')[0].strip()\n"
        "    if i: open(os.path.join(sys.argv[2], i+'-x.txt'),'w').write('t')\n")
    (root / "tools" / "fresh_worker.py").write_text(FAKE_CYCLE_WORKER)
    # The papers source may send (tools/options.py on loop sources=papers yes).
    (root / "instance").mkdir()
    (root / "instance" / "config.json").write_text(json.dumps({"egress": {"model_send": {
        "deny_prefixes": ["_private/"], "allow_prefixes": ["_private/work/papers/"]}}}))
    for t in ("now.py", "triggers.py", "loop/loop_watchdog.py"):
        (root / "tools" / t).write_text(FAKE_TOOL)
    (root / "tools" / "loop" / "papers_apply.py").write_text(
        FAKE_TOOL + f"import sys\nsys.exit(0 if '--backlog' in sys.argv else {apply_rc})\n")
    return root


def run_cycle(root, modes=None, env_extra=None, *args):
    env = dict(os.environ, FAKE_CYCLE=json.dumps(modes or {}), **(env_extra or {}))
    r = subprocess.run(["bash", str(root / "tools" / "loop" / "papers_cycle.sh"), *(args or ("--force",))], cwd=root,
                       capture_output=True, text=True, timeout=180, env=env)
    st = json.loads((root / "_private" / "papers" / "state.json").read_text())
    return r, st, (root / "_private" / "papers" / "cycle.log").read_text()


def test_papers_cycle_hung_worker_is_bounded_and_releases_lock():
    root = cycle_fixture()
    try:
        import time as _t
        t0 = _t.monotonic()
        r, st, logt = run_cycle(root, {"triage": "sleep:40"}, {"PAPERS_WORKER_TIMEOUT": "2"})
        assert _t.monotonic() - t0 < 25, "worker budget was not enforced"
        assert r.returncode == 1 and st["status"] == "failed", (st, logt)
        assert "triage" in st["fails"] and "124" in st["fails"], st
        d = root / "_private" / "work" / "papers" / f"{st['last_cycle']}-kit"
        assert "TIMEOUT" in (d / "triage.receipt").read_text() and "exit 124" in (d / "triage.receipt").read_text()
        pid = int((root / "_private" / "sleeper-triage.pid").read_text())
        _t.sleep(0.5)
        try:
            os.kill(pid, 0)
            left = True
        except ProcessLookupError:
            left = False
        if left:
            os.kill(pid, 9)
        assert not left, f"worker left running: pid {pid}"
        r, st, logt = run_cycle(root, {}, None, "--force")
        assert "cycle.lock" not in logt and st["status"] == "ok", (st, logt)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_papers_cycle_ok_path_has_no_slack_summary_or_publication_prompt():
    root = cycle_fixture()
    try:
        r, st, logt = run_cycle(root)
        assert r.returncode == 0 and st["status"] == "ok", (st, logt)
        c = calls(root)
        # Spelled in two parts so the removed-notifier scan in test_instance_tools does not count this check as a caller.
        assert not any(x[0] == "garden_" + "notify.py" for x in c), c
        d = root / "_private" / "work" / "papers" / f"{st['last_cycle']}-kit"
        assert (d / "REPORT.md").is_file() and not (d / "REVIEW.md").exists()
        report = (d / "REPORT.md").read_text().lower()
        assert "publish" not in report and "local commit" not in report, report
        # A clean cycle adds nothing to what a session start shows.
        assert not any(x[0] == "now.py" for x in c), c
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_papers_cycle_with_an_abandoned_bundle_completes_quietly():
    # The beat runs the real applier; its one bundle breaks a test in both attempts.
    root = fixture()
    try:
        shutil.copy2(HERE / "loop" / "papers_cycle.sh", root / "tools" / "loop" / "papers_cycle.sh")
        (root / "tools" / "loop" / "papers").mkdir()
        (root / "tools" / "loop" / "papers" / "sweep.py").write_text(
            "import sys\na=sys.argv; o=a[a.index('--out')+1]\nopen(o,'w').write('arxiv_id\\tx\\ttitle\\n2601.00001\\tx\\tT one\\n')\n")
        (root / "tools" / "loop" / "papers" / "fetch_arxiv.py").write_text(
            "import os,sys\nfor l in open(sys.argv[1]):\n    i=l.split('\\t')[0].strip()\n"
            "    if i: open(os.path.join(sys.argv[2], i+'-x.txt'),'w').write('t')\n")
        (root / "system" / "loop" / "prompts").mkdir(parents=True)
        for t in ("triage", "card", "propose", "digest-en"):
            (root / "system" / "loop" / "prompts" / f"{t}.md").write_text(f"{t} {{{{DIR}}}}\n")
        (root / "tools" / "fresh_worker.py").write_text(FAKE_CYCLE_WORKER)   # The applier's workers are MOTTORI_APPLY_WORKER_CMD.
        (root / "tools" / "loop" / "loop_watchdog.py").write_text(FAKE_TOOL)
        sh(root, "add", "-A"); sh(root, "commit", "-q", "-m", "beat")
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_BREAK, review_bump=PASS)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MOTTORI_"))}
        env.update(worker_env(root))
        for n in (1, 2):   # The second run is a resume of the same cycle.
            r = subprocess.run(["bash", str(root / "tools" / "loop" / "papers_cycle.sh"), "--resume", CYCLE.split("/")[-1][:10]],
                               cwd=root, capture_output=True, text=True, timeout=600, env=env)
            st = json.loads((root / "_private" / "papers" / "state.json").read_text())
            logt = (root / "_private" / "papers" / "cycle.log").read_text()
            # The applier's own report says why a stage failed; the cycle log only says that it did.
            assert r.returncode == 0 and st["status"] == "ok" and not st["fails"], (
                n, st, logt[-800:], _reports(root, st), r.stderr[-800:])
            assert LS.apply_status(str(root / CYCLE)) == "done" and entry(root)["outcome"] == "abandoned", report_md(root)
            # A finished cycle adds nothing to the journal.
            assert not [x for x in calls(root) if x[0] == "now.py"], calls(root)
            assert "watchdog" not in logt, logt[-800:]
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_papers_cycle_apply_failure_adds_no_duplicate_alert():
    root = cycle_fixture(apply_rc=1)
    try:
        r, st, logt = run_cycle(root)
        assert r.returncode == 1 and st["failed_stages"] == ["apply"], (st, logt)
        assert not any(x[0] == "triggers.py" and any("papers-judge-" in y for y in x) for x in calls(root)), calls(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_papers_cycle_digest_failure_is_not_fatal():
    root = cycle_fixture()
    try:
        r, st, logt = run_cycle(root, {"digest-en": "fail"})
        assert r.returncode == 0 and st["status"] == "ok" and st["failed_stages"] == [], (st, logt)
        d = root / "_private" / "work" / "papers" / f"{st['last_cycle']}-kit"
        assert not (d / "DIGEST-EN.md").exists() and "digest failed" in logt, logt
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_papers_cycle_failed_proposals_skip_digest_worker():
    root = cycle_fixture()
    try:
        r, st, logt = run_cycle(root, {"propose": "fail"})
        assert r.returncode == 1 and st["failed_stages"] == ["proposals"], (st, logt)
        prompts = [x[-1] for x in calls(root) if x[0] == "fresh_worker.py"]
        assert any(x.endswith("propose.md") for x in prompts), prompts
        assert not any(x.endswith("digest-en.md") for x in prompts), prompts
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_r13_new_failures_compares_test_ids():
    base = {"t.py": {"rc": 1, "timeout": False, "passes": ["b"], "fails": ["a"]}}
    swap = {"t.py": {"rc": 1, "timeout": False, "passes": ["a"], "fails": ["b"]}}
    assert LK.new_failures(base, swap), "missed a swap of failures (A fixed, B broken)"
    tmo = {"t.py": {"rc": 124, "timeout": True, "passes": [], "fails": []}}
    # Named as a timeout, not only as an exit-code change, also when the base timed out too.
    assert any("timeout" in x for x in LK.new_failures({"t.py": {"rc": 1, "timeout": False, "passes": [], "fails": []}}, tmo))
    assert any("timeout" in x for x in LK.new_failures(tmo, tmo))
    missing = {"t.py": {"rc": 1, "timeout": False, "passes": [], "fails": ["a"]}}
    assert any("not run" in x for x in LK.new_failures(base, missing))
    crash = {"t.py": {"rc": 2, "timeout": False, "passes": ["b"], "fails": ["a"]}}
    assert any("rc" in reason for reason in LK.new_failures(base, crash)), "missed a crash shown only by a changed exit code"
    same = {"t.py": {"rc": 1, "timeout": False, "passes": ["b"], "fails": ["a"]}}
    assert LK.new_failures(base, same) == []
    assert LK.parse_test_output("✓ x\n✗ y: boom\nPASS z\nFAIL value\n") == (["x", "z"], ["value", "y"])


def test_parse_edits_rejects_malformed_header():
    for text in ("@@@ EDIT tools/a b.py\n@@@ SEARCH\nx\n@@@ REPLACE\ny\n@@@ END",
                 "@@@ EDIT tools/a.py\n@@@ SEARCH\nx\n@@@ REPLACE\ny\n@@@ END\n@@@ FILE\nz\n@@@ END"):
        try:
            LE.parse_edits(text)
        except ValueError:
            continue
        raise AssertionError(f"malformed header skipped silently: {text!r}")
    assert len(LE.parse_edits("note\n" + EDIT_OK)) == 1


def test_judge_without_meta_sha_starts_new_generation():
    root = fixture()
    try:
        respond(root, judge=judge_text([], rejected=[{"id": "x", "reason": "insufficient evidence"}]))
        assert run_apply(root, CYCLE).returncode == 0
        (root / CYCLE / "apply/judge-input.json").write_text("{}\n")
        r = run_apply(root, CYCLE, "--force")
        assert r.returncode == 0, r.stdout + r.stderr
        assert (root / CYCLE / "apply/gen-legacy").is_dir(), sorted(p.name for p in (root / CYCLE / "apply").iterdir())
        assert len([c for c in worker_calls(root) if c[-1].endswith("judge.md")]) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _abandoned_and_pending(root):
    """Two bundles: brk breaks a test in both attempts, and late has no implementation answer, as when
    no model runtime can be called."""
    (root / "tools" / "d.py").write_text("D = 1\n")
    sh(root, "add", "tools/d.py"); sh(root, "commit", "-q", "-m", "d")
    respond(root, judge=judge_text([bundle("brk", "act", check=COST_CHECK), bundle("late", "observe", files=("tools/d.py",))]),
            impl_brk=EDIT_BREAK)


@macos_only(SANDBOX, sandbox=True)
def test_status_lists_abandoned_and_pending():
    root = fixture()
    try:
        _abandoned_and_pending(root)
        r = run_apply(root, CYCLE)
        status = [e["outcome"] for e in outcome_of(root)["bundles"]]
        assert r.returncode == 0 and status == ["abandoned", "pending"], status
        # The pending bundle is taken up again by the next run.
        assert LS.apply_status(str(root / CYCLE)) == "pending", status
        assert "no model runtime could be called" in entry(root, "late")["reason"], entry(root, "late")
        # Abandonment is a normal outcome: the report carries it, no failure notification.
        assert not any(x[0] == "triggers.py" and any(str(y).startswith("apply-failed-") for y in x)
                       for x in calls(root)), calls(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_a_cycle_without_a_saved_change_journals_nothing():
    root = fixture()
    try:
        _abandoned_and_pending(root)
        for _ in range(2):
            run_apply(root, "--backlog")
        logs = [x for x in calls(root) if x[0] == "now.py" and "log" in x]
        assert logs == [], logs
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-brk.md")]) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_cycle_judged_before_the_outcome_record_is_closed():
    # An APPLY.md of the old form with no outcome record beside it: not processed again, files left as they are.
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        cyc = root / CYCLE
        (cyc / "apply").mkdir()
        old = "# a\n\nStatus: held (bump: switch)\n\n<!-- apply-end -->\n"
        (cyc / "APPLY.md").write_text(old)
        (cyc / "apply/state.json").write_text(json.dumps({"bundles": {"bump": {"hold": "switch", "result": "held: x"}}}))
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and "closed" in r.stdout and worker_calls(root) == [], r.stdout + r.stderr
        assert (cyc / "APPLY.md").read_text() == old and not (cyc / "apply/outcome.json").exists()
        assert LS.needs_processing(str(cyc)) is False and PA.backlog_dirs(str(root)) == []
        assert not (cyc / "REPORT.md").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_classification_uses_kind_not_text():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        M = load(root / "tools" / "loop" / "papers_apply.py", "papers_apply_fixture_kind")
        unsafe = getattr(LE, "UnsafeEdit", ValueError)

        def refuse(*a, **k):
            raise unsafe("reworded refusal with none of the old key words")
        with patch.dict(os.environ, worker_env(root)), patch.object(LB, "build_candidate", side_effect=refuse):
            M.process(CYCLE, "papers")
        record = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        # A safety refusal is final whatever its wording: no second implementation attempt.
        assert record.get("outcome") == "refused", record
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_landing_setting_stops_the_run_as_an_unknown_setting():
    for key, value in (("landing", "worktree"), ("landing_paths", ["tools/"]), ("self_landing", True),
                       ("commit_trailer", "Signed-off-by: x")):
        root = fixture()
        try:
            (root / "instance" / "config.json").write_text(json.dumps({"loop": {key: value}}))
            respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
            before = head(root)
            r = run_apply(root, CYCLE)
            assert r.returncode == 1 and head(root) == before and r.stdout.startswith("stopped: 1 problem"), r.stdout
            assert f"loop.{key}: unknown setting" in LCf.problems(str(root)), key
            assert not worker_calls(root) and not (root / CYCLE / "REPORT.md").exists(), key
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_r16_auth_check_requires_exact_sentinel_and_reports_source():
    sys.path.insert(0, str(HERE))
    import claude_auth as CA
    assert CA.judge(0, "token revoked", "")[0] is False
    assert CA.judge(0, "ok", "")[0] is False
    assert CA.judge(0, "Error: OAuth token has expired\n" + CA.SENTINEL, "")[0] is False
    assert CA.judge(1, CA.SENTINEL, "")[0] is False
    assert CA.judge(0, CA.SENTINEL + "\n", "")[0] is True
    old = os.environ.get(CA.ENV_KEY)
    os.environ[CA.ENV_KEY] = "x"
    try:
        assert CA.ENV_KEY in CA.source()
    finally:
        if old is None:
            os.environ.pop(CA.ENV_KEY)
        else:
            os.environ[CA.ENV_KEY] = old


@macos_only(SANDBOX, sandbox=True)
def test_b_final_answer_delivery_repairs_once_and_retains_originals():
    root = fixture()
    try:
        first = "The edit blocks were above.\n" + PASS
        respond(root, judge=judge_text([bundle()]), impl_bump=first,
                impl_bump_attempt_2=EDIT_OK, review_bump=PASS)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and entry(root)["outcome"] == "saved", r.stdout + r.stderr
        state = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        assert len(state["attempts"]) == 2 and state["attempts"][0]["failure_stage"] == "delivery", state
        first_dir = root / state["attempts"][0]["artifacts"]
        assert (first_dir / "impl-bump.result.md").read_text() == first
        second_dir = root / state["attempts"][1]["artifacts"]
        prompt = (second_dir / "impl-prompt.md").read_text()
        assert "in your one final answer" in prompt and "## One correction" in prompt and str(first_dir.relative_to(root)) in prompt
        assert state["outcome"] == "saved" and state["effect"] == "UNKNOWN (no check)", state
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_b_review_correction_has_exact_patch_and_review():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=FAIL,
                review_bump_attempt_2=PASS)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0, r.stdout + r.stderr
        state = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        a = state["attempts"][0]
        assert a["failure_stage"] == "review"
        old = root / a["artifacts"]
        assert (old / "review-bump.result.md").read_text() == FAIL
        assert "EXTRA = 2" in (old / "bump.patch").read_text()
        assert (old / "bump.tests.json").exists()
        feedback = state["attempts"][0]["feedback"]
        assert "codex (model fake-codex-model)" in feedback, feedback
        assert feedback in (root / state["attempts"][1]["artifacts"] / "impl-prompt.md").read_text()
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_b_crash_reservation_survives_restart_and_force_cannot_reset():
    root = fixture()
    try:
        pa = load(root / "tools/loop/lib/loop_bundle.py", "crash_pa")
        cyc = root / CYCLE
        ctx = LR.Ctx(CYCLE, str(cyc), str(cyc / "apply"), "papers", str(root))
        ctx.source_identity = LJ.source_snapshot(str(root))
        b = bundle()
        b["_spec"] = LJ.spec_hash(b)
        b["_r"] = {"spec": b["_spec"]}
        def crash(c, selected, record):
            durable = json.loads(Path(c.state_path).read_text())["bundles"]["bump"]
            assert len(durable["attempts"]) == 1 and durable["attempts"][0]["status"] == "running"
            raise KeyboardInterrupt("simulated process loss after durable reservation")
        pa.bundle_attempt = crash
        try:
            pa.run_bundle(ctx, b, b["_r"])
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("crash was swallowed")
        ctx2 = LR.Ctx(CYCLE, str(cyc), str(cyc / "apply"), "papers", str(root))
        ctx2.source_identity = LJ.source_snapshot(str(root))
        ctx2.state = json.loads(Path(ctx.state_path).read_text())
        b["_r"] = ctx2.state["bundles"]["bump"]
        seen = []
        def failed(c, selected, record):
            seen.append(1)
            record["result"] = "refused: the implementation worker gave no edit blocks"
        pa.bundle_attempt = failed
        pa.run_bundle(ctx2, b, b["_r"])
        assert len(seen) == 1 and len(b["_r"]["attempts"]) == 2
        assert b["_r"]["attempts"][0]["failure_stage"] == "interrupted"
        assert b["_r"]["outcome"] == "abandoned"
        pa.run_bundle(ctx2, b, b["_r"])
        assert len(seen) == 1, "a spent budget dispatched again"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_b_abandonment_is_terminal_and_never_auto_healed():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_BREAK, review_bump=PASS)
        before = head(root)
        r = run_apply(root, CYCLE)
        # A bundle that used up its attempts is abandoned, not a failed run.
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr
        assert entry(root)["outcome"] == "abandoned" and "new test failures: test_lib.py" in entry(root)["reason"], entry(root)
        refused = outcome_of(root)["refused"]
        assert refused == [] and f"- **bump** {entry(root)['reason']}" in report_md(root), refused   # the judge refused nothing
        assert not [x for x in calls(root) if x[0] == "now.py"], calls(root)
        assert not any(c[-1].endswith("review-bump.md") for c in worker_calls(root))
        assert LS.apply_status(str(root / CYCLE)) == "done"
        assert not any(x[0] == "triggers.py" and any(str(y).startswith("apply-failed-") for y in x)
                       for x in calls(root)), calls(root)
        assert not LS.needs_processing(str(root / CYCLE))
        run_apply(root, CYCLE, "--force")
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 2
        # The watchdog judges the state this real run wrote; ROOT is pointed at the fixture instead of copying the file in.
        wd = load(HERE / "loop" / "loop_watchdog.py", "exhausted_wd")
        wd.ROOT, wd.TODAY = str(root), datetime.date.fromisoformat(TODAY)   # Inside the watchdog lookback window.
        probs = wd.check_papers(LS)   # Abandonment is no problem: the report says it, never an alert or a repair.
        # Problem keys carry the cycle date, not its status, so the date is what an alert would show.
        date = os.path.basename(CYCLE)[:10]
        assert not any(date in k for k, _ in probs) and not wd.HEAL_CMDS, (probs, wd.HEAL_CMDS)
        assert outcome_of(root)["counts"]["abandoned"] == 1 and len(outcome_of(root)["bundles"]) == 1
        assert [a["failure_stage"] for a in entry(root)["attempts"]] == ["tests", "tests"], entry(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_b_policy_source_changed_is_pending_without_writing_target():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        extra(root, "impl-bump.sh", "printf changed > instance/decisions.md\n")
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr
        assert entry(root)["outcome"] == "pending", entry(root)
        assert (root / "tools/lib.py").read_text() == "VALUE = 1\n"
        assert not any(c[-1].endswith("review-bump.md") for c in worker_calls(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_b_valid_noop_and_semantic_rejection_do_not_trigger_retry():
    root = fixture()
    try:
        noop = "@@@ FILE tools/lib.py\nVALUE = 1\n@@@ END\n" + PASS
        respond(root, judge=judge_text([bundle()]), impl_bump=noop)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and "empty diff" in entry(root)["reason"], entry(root)
        run_apply(root, CYCLE, "--force")
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 1
        assert outcome_of(root)["counts"]["refused"] == 1
        other = root / "_private/work/papers/2026-10-08-kit"
        other.mkdir(); (other / "PROPOSALS.md").write_text("x" * 300)
        respond(root, judge=judge_text([], rejected=[{"id": "x", "reason": "insufficient evidence"}]))
        r = run_apply(root, str(other))
        assert r.returncode == 0
        assert outcome_of(root, "_private/work/papers/2026-10-08-kit")["bundles"] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_b_partial_candidate_never_leaks_and_safety_rejection_is_not_migrated():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK + EDIT_OUTSIDE, review_bump=PASS)
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before
        assert "edits a file outside the bundle: other.txt" in entry(root)["reason"], entry(root)
        assert (root / "tools/lib.py").read_text() == "VALUE = 1\n"
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_b_input_generation_change_cannot_reset_same_spec_source_budget():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_BREAK)
        run_apply(root, CYCLE)
        state_path = root / CYCLE / "apply/state.json"
        first = json.loads(state_path.read_text())["bundles"]["bump"]
        originals = {str(p.relative_to(root)): p.read_bytes()
                     for a in first["attempts"] for p in (root / a["artifacts"]).iterdir() if p.is_file()}
        proposal = root / CYCLE / "PROPOSALS.md"
        proposal.write_text(proposal.read_text() + "\nAdditional evidence, unchanged implementation spec.\n")
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and entry(root)["outcome"] == "abandoned", r.stdout + r.stderr
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 2
        record = json.loads(state_path.read_text())["bundles"]["bump"]
        assert record["attempts"] == first["attempts"]
        assert all((root / path).read_bytes() == data for path, data in originals.items())
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_r4_real_fresh_worker_isolate_reads_judge_review_and_correction_materials():
    root = fixture()
    try:
        (root / 'tools/lib.py').write_text('VALUE = 1\ndef elapsed_days(hours):\n    return 0\n')
        for name in ("lib/config.py", "lib/safeio.py", "claude_auth.py", "receipts.py",
                     "lib/paths.py", "lib/worker_sandbox.py"):
            shutil.copy2(HERE / name, root / "tools" / name)
        (root / "instance/config.json").write_text(json.dumps({
            "schema_version": 4, "journal_visibility": {"public_tracks": ["system"],
                "legacy_cutoff": None, "legacy_public_tracks": []},
            "egress": {"model_send": {"deny_prefixes": ["_private/"],
                "allow_prefixes": ["_private/work/papers/"]}}}))
        sh(root, "add", "-f", "tools/lib.py", "tools/lib/config.py", "tools/lib/safeio.py", "tools/claude_auth.py",
           "tools/receipts.py", "tools/lib/paths.py", "tools/lib/worker_sandbox.py", "instance/config.json")
        sh(root, "commit", "-q", "-m", "real isolated runtime support")
        cards = root / CYCLE / "cards"; cards.mkdir()
        (cards / "one.md").write_text("Material identity canary: SYNTHETIC-CLOSED-LOOP-7C14.")
        # A behavioral assertion, not missing-import failure: old implementation returns 0.
        edit_with_test = ("@@@ EDIT tools/lib.py\n@@@ SEARCH\n    return 0\n@@@ REPLACE\n    return hours // 24\n@@@ END\n"
                         "@@@ EDIT tools/tests/test_lib.py\n@@@ SEARCH\nimport lib\n@@@ REPLACE\nimport lib\n"
                         "if lib.elapsed_days(49) != 2:\n"
                         "    print('FAIL whole_days: expected 2 for 49 hours, got', lib.elapsed_days(49))\n"
                         "    sys.exit(1)\nprint('PASS whole_days')\n@@@ END\n" + PASS)
        runtime = root / "_fake/isolated_runtime.py"
        body = '''import json, os, pathlib, re, sys
args = sys.argv[1:]; body = sys.stdin.read(); root = pathlib.Path.cwd()
assert root.name == 'wt', str(root)
cycle = root / CYCLE_PATH
if 'You are the judge of the improvement loop' in body:
    assert 'Proposals' in (cycle / 'PROPOSALS.md').read_text()
    assert 'SYNTHETIC-CLOSED-LOOP-7C14' in (cycle / 'cards/one.md').read_text()
    result = JUDGE_TEXT
elif 'You are the implementation worker of the improvement loop' in body:
    assert 'Proposals' in (cycle / 'PROPOSALS.md').read_text()
    assert 'SYNTHETIC-CLOSED-LOOP-7C14' in (cycle / 'cards/one.md').read_text()
    if '## One correction' in body:
        named = re.search(r'Original output: `([^`]+)`', body).group(1)
        source = root / named
        assert 'edits were above' in (source / 'impl-bump.result.md').read_text()
        assert json.loads((source / 'attempt.json').read_text())['failure_stage'] == 'delivery'
        result = EDIT_TEXT
    else:
        result = 'edits were above.\\n' + PASS_TEXT
else:
    assert 'return hours // 24' in (cycle / 'apply/bump.patch').read_text()
    assert '0 new failures' in (cycle / 'apply/bump.tests.txt').read_text()
    assert json.loads((cycle / 'apply/bump.spec.json').read_text())['id'] == 'bump'
    assert 'Proposals' in (cycle / 'PROPOSALS.md').read_text()
    assert 'SYNTHETIC-CLOSED-LOOP-7C14' in (cycle / 'cards/one.md').read_text()
    tests = json.loads((cycle / 'apply/bump.tests.json').read_text())
    original = json.loads((cycle / 'apply/bump.original-tests.json').read_text())
    assert tests['test_lib.py']['passes'] == ['value', 'whole_days'] and original['test_lib.py']['passes'] == ['value']
    counter = json.loads((cycle / 'apply/bump.counterfactual-tests.json').read_text())['test_lib.py']
    assert counter['rc'] == 1 and counter['fails'] == ['whole_days'] and not counter['timeout']
    assert 'expected 2 for 49 hours, got 0' in counter['output']
    assert 'Traceback' not in counter['output'] and not counter['output_truncated']
    verification = json.loads((cycle / 'apply/bump.verification.json').read_text())
    import hashlib
    for path, digest in {**verification['material_identity'], **verification['test_artifact_sha256']}.items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest
    result = PASS_TEXT
if '--output-last-message' in args:
    pathlib.Path(args[args.index('--output-last-message') + 1]).write_text(result)
    print(json.dumps({'type': 'turn.completed'}))
else:
    print(json.dumps({'type': 'result', 'result': result}))
'''
        specification = bundle()
        specification.update(change='elapsed_days uses completed 24-hour days',
                             success_metric='49 hours returns 2; new whole_days fails on original implementation',
                             stop_condition='source canary SYNTHETIC-CLOSED-LOOP-7C14 mismatch or original behavior regression')
        declarations = (f"CYCLE_PATH = {CYCLE!r}\nJUDGE_TEXT = {judge_text([specification])!r}\n"
                        f"EDIT_TEXT = {edit_with_test!r}\nPASS_TEXT = {PASS!r}\n")
        runtime.write_text("#!/usr/bin/env python3\n" + declarations + body); runtime.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MOTTORI_APPLY_")) and k not in ("CLAUDE_CODE_OAUTH_TOKEN", "MOTTORI_INSTANCE")}
        env.update(MOTTORI_FRESH_WORKER_CLAUDE_BIN=str(runtime), MOTTORI_FRESH_WORKER_CODEX_BIN=str(runtime),
                   MOTTORI_APPLY_WORKER_CMD=f"{sys.executable} {root / 'tools/fresh_worker.py'}", HOME=str(root / '_fake/home'),
                   MOTTORI_APPLY_TODAY=TODAY)
        (root / "_fake/home").mkdir()
        r = subprocess.run([sys.executable, str(root / "tools/loop/papers_apply.py"), CYCLE],
                           cwd=root, env=env, capture_output=True, text=True, timeout=90)
        assert r.returncode == 0 and entry(root)["outcome"] == "saved", r.stdout + r.stderr + report_md(root)
        assert TODAY in report_md(root), report_md(root)[:300]
        state = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        assert len(state['attempts']) == 2, state
        metas = [json.loads(p.read_text()) for p in (root / "_private/work/runs").glob('*/meta.json')]
        assert len(metas) == 4 and all(m['status'] == 'success' for m in metas), metas
        assert all(m['worktree']['material_integrity'] for m in metas)
        assert any(CYCLE + '/PROPOSALS.md' in m['worktree']['material_sha256'] for m in metas)
        assert any(CYCLE + '/apply/bump.patch' in m['worktree']['material_sha256'] for m in metas)
        assert any(any('attempt-1/impl-bump.result.md' in path for path in m['worktree']['material_sha256']) for m in metas)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_refusals_name_the_path_and_each_branch_is_needed():
    # Each assertion fails when its branch in loop_policy.refusal is removed: a never-list path would read
    # as outside the area, the definition module and a path outside the harness would pass.
    expect = {"_private/work/x.md": "on the never list", "state/NOW.md": "on the never list",
              ".git/config": "on the never list", "vault/a.pdf": "on the never list",
              "instance/config.json": "on the never list",
              "tools/loop/loop_policy.py": "changes the definition of the never list and the allowed area",
              "README.md": "outside the allowed area", ".gitignore": "a file Git itself reads from the tree",
              "research/notes.md": "outside the allowed area"}
    # The installation's additions are pinned here, so the tree's own configuration does not decide the answers.
    with patch.object(LCf, "block", lambda root=None: {"never": ["vault/"]}):
        for path, why in expect.items():
            got = LJ.validate_bundle(bundle(files=(path,)))
            assert got == f"{why}: {path}", (path, got)
        for path in ("tools/gate.py", "tools/loop/papers_apply.py", "tools/tests/run.py", "AGENTS.md", "CLAUDE.md",
                     "setup.sh", "instance/decisions.md", ".claude/settings.json", "templates/x.md"):
            assert LJ.validate_bundle(bundle(files=(path,))) is None, path
    for value in (None, "", "   ", []):
        b = bundle(); b['source'] = value
        assert LJ.validate_bundle(b), value


@macos_only(SANDBOX, sandbox=True)
def test_r4_original_test_oracle_catches_forged_pass_output():
    root = fixture()
    try:
        forged = EDIT_BREAK + '@@@ FILE tools/tests/test_lib.py\nprint("PASS value")\n@@@ END\n' + PASS
        respond(root, judge=judge_text([bundle()]), impl_bump=forged, review_bump=PASS)
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr
        assert 'original-oracle:test_lib.py' in report_md(root)
        assert not any(c[-1].endswith('review-bump.md') for c in worker_calls(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_r4_budget_survives_source_change_after_one_failed_attempt():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_BREAK)
        run_apply(root, CYCLE)
        state_path = root / CYCLE / 'apply/state.json'
        state = json.loads(state_path.read_text()); record = state['bundles']['bump']
        # Restart after the first durable failed reservation, before the correction was dispatched.
        record['attempts'] = record['attempts'][:1]
        LO.pend(record, 'the working tree changed during the run')
        state_path.write_text(json.dumps(state))
        out = root / CYCLE / 'apply/outcome.json'; o = json.loads(out.read_text()); o['state'] = 'pending'
        out.write_text(json.dumps(o))
        sh(root, 'commit', '--allow-empty', '-q', '-m', 'new source')
        before_calls = len([c for c in worker_calls(root) if c[-1].endswith('impl-bump.md')])
        run_apply(root, CYCLE)
        after = json.loads(state_path.read_text())['bundles']['bump']
        assert len(after['attempts']) == 2 and after['outcome'] == 'abandoned', after
        assert len([c for c in worker_calls(root) if c[-1].endswith('impl-bump.md')]) == before_calls + 1
        assert after['attempts'][0]['source_identity'] != after['attempts'][1]['source_identity']
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_no_stage_names_a_model():
    # Each worker runs with the model the worker tool resolves; the loop passes no model of its own.
    seen = []
    def fake_run(cmd, timeout, cwd, env):
        seen.append(sorted(k for k in env if k.startswith("MOTTORI_FRESH_WORKER_") and k.endswith("_MODEL")))
        return 0, "status: success\n", False
    with tempfile.TemporaryDirectory(prefix="apply-model-") as directory:
        receipt = str(Path(directory) / "receipt.txt")
        with patch.object(LW, "run_group", side_effect=fake_run), patch.dict(os.environ):
            for key in [k for k in os.environ if k.startswith("MOTTORI_FRESH_WORKER_")]:
                os.environ.pop(key)
            LW.run_in_order("implement", None, "prompt.md", receipt)
            LW.run_in_order("review", "claude", "prompt.md", receipt)
    assert seen == [[], []], seen
    files = _loop_files()
    assert len(files) > 10 and HERE / "loop" / "lib" / "loop_worker.py" in files and HERE / "loop" / "papers_cycle.sh" in files, files
    for f in files:
        source = f.read_text(encoding="utf-8")
        assert "gpt-" not in source and '"opus"' not in source and "_MODEL" not in source, f


def _loop_files():
    """Every file of the loop outside its tests, as loop_policy lists them."""
    files = set()
    for entry in LPo.LOOP_TOOLS:
        if entry.startswith("tools/tests/"):
            continue
        path = HERE.parent / entry
        files |= set(path.rglob("*.py")) if entry.endswith("/") else set(HERE.parent.glob(entry))
    return sorted(files)


def test_no_function_hides_a_name_of_its_module():
    # A local variable or argument named like a function, class or import of its module makes that
    # name mean something else inside the function.
    hidden = []
    for f in _loop_files():
        if f.suffix != ".py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names |= {a.asname or a.name.split(".")[0] for a in node.names}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                args = fn.args
                local = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
                local |= {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                hidden += [f"{f.name}:{getattr(fn, 'name', 'lambda')}:{x}" for x in sorted(local & names)]
    assert not hidden, hidden


@macos_only(SANDBOX, sandbox=True)
def test_r5_source_card_change_cannot_silently_reach_review_or_commit():
    root = fixture()
    try:
        cards = root / CYCLE / 'cards'; cards.mkdir()
        (cards / 'one.md').write_text('canary original')
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        extra(root, 'impl-bump.sh', f"echo changed > {CYCLE}/cards/one.md\n")
        before = head(root)
        result = run_apply(root, CYCLE)
        assert result.returncode == 0 and entry(root)['outcome'] == 'pending', result.stdout + result.stderr
        assert 'a read material changed' in entry(root)['reason'], entry(root)
        assert head(root) == before and not any(c[-1].endswith('review-bump.md') for c in worker_calls(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_counterfactual_diagnostic_pass_is_valid_and_repair_receives_fail_cause():
    for insertion, should_crash in (("print('PASS observation')", False),
                                   ("if not hasattr(lib, 'EXTRA'):\n    import missing_counterfactual_fixture_module", True)):
        root = fixture()
        try:
            edit = EDIT_OK + ("@@@ EDIT tools/tests/test_lib.py\n@@@ SEARCH\nimport lib\n@@@ REPLACE\nimport lib\n"
                              + insertion + "\n@@@ END\n")
            respond(root, judge=judge_text([bundle()]), impl_bump=edit,
                    review_bump=FAIL if should_crash else PASS)
            result = run_apply(root, CYCLE)
            path = root / CYCLE / 'apply/bump.counterfactual-tests.json'
            diagnostic = json.loads(path.read_text())['test_lib.py']
            if should_crash:
                assert result.returncode == 0 and diagnostic['rc'] != 0, result.stdout + result.stderr
                assert diagnostic['fails'] == [] and 'ModuleNotFoundError' in diagnostic['output']
                calls = [c for c in worker_calls(root) if c[-1].endswith('impl-bump.md')]
                assert len(calls) == 2 and any('attempt-1/bump.counterfactual-tests.json' in arg for arg in calls[1])
                archived = next((root / CYCLE / 'apply/attempts').glob('*/attempt-1/bump.counterfactual-tests.json'))
                prior = json.loads(archived.read_text())['test_lib.py']
                assert prior['rc'] == diagnostic['rc'] and 'ModuleNotFoundError' in prior['output']
            else:
                assert result.returncode == 0 and diagnostic['rc'] == 0 and entry(root)['outcome'] == 'saved', result.stdout + result.stderr
            prompt = (root / CYCLE / 'prompts/review-bump.md').read_text()
            assert 'an import or setup error' in prompt and 'Do not require a counterfactual failure for every change' in prompt
        finally:
            shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- Commit check and harness files
# Both checks run, so a patch failure stays visible on a base the environment already blocks.
FAKE_GATE = r"""import os, subprocess, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bad = False
if os.path.exists(os.path.join(root, "ENV_BLOCKED")):
    print("[gate] Issues not in the gate baseline appeared: now-check: now-input-newer.", file=sys.stderr)
    bad = True
staged = subprocess.run(["git", "-C", root, "show", ":tools/lib.py"], capture_output=True, text=True).stdout
if "GATE_BAD" in staged:
    print("[gate] staged lib carries GATE_BAD", file=sys.stderr)
    bad = True
sys.exit(1 if bad else 0)
"""
EDIT_GATE_BAD = ("@@@ EDIT tools/lib.py\n@@@ SEARCH\nVALUE = 1\n@@@ REPLACE\nVALUE = 1\nEXTRA = 'GATE_BAD'\n@@@ END\n"
                 + PASS + "\n")


def with_gate(root, env_blocked):
    (root / "tools" / "gate.py").write_text(FAKE_GATE)
    paths = ["tools/gate.py"]
    if env_blocked:
        (root / "ENV_BLOCKED").write_text("state mismatch\n")
        paths.append("ENV_BLOCKED")
    sh(root, "add", *paths)
    sh(root, "commit", "-q", "-m", "gate fixture")


@macos_only(SANDBOX, sandbox=True)
def test_a_base_that_fails_the_commit_check_is_only_a_note():
    root = fixture()
    try:
        with_gate(root, env_blocked=True)
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr
        text = report_md(root)
        assert outcome_of(root)["blocked"][0].startswith("[gate] Issues not in the gate baseline"), outcome_of(root)
        assert text.splitlines()[4] == LRp.GATE_BLOCKED + outcome_of(root)["blocked"][0], text
        # Nothing here commits, so the change is built, reviewed and saved all the same.
        assert entry(root)["outcome"] == "saved" and outcome_of(root)["state"] == "done", text
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_loop_a_gate_failure_caused_by_patch_is_a_rejection_before_review():
    root = fixture()
    try:
        with_gate(root, env_blocked=False)
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_GATE_BAD, review_bump=PASS)
        before = head(root)
        r = run_apply(root, CYCLE)
        assert head(root) == before, r.stdout + r.stderr
        text = report_md(root)
        assert "GATE_BAD" in text and LRp.GATE_BLOCKED not in text and not outcome_of(root)["blocked"], text
        assert not [c for c in worker_calls(root) if c[-1].endswith("review-bump.md")]
        record = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        assert record["attempts"][0]["failure_stage"] == "gate", record
    finally:
        shutil.rmtree(root, ignore_errors=True)


CONTEXT_BUDGET = r'''
import json, os, sys
limit = int(open(os.path.join(os.path.dirname(__file__), "limit.txt")).read())
size = os.path.getsize("AGENTS.md") if os.path.isfile("AGENTS.md") else 0
parts = [{"name": "AGENTS.md", "bytes": size, "chars": size, "tokens": size // 4}] if size else []
item = {"key": "instructions", "bytes": size, "chars": size, "tokens": size // 4, "limit": limit,
        "over": size > limit, "method": "measured", "parts": parts, "notes": []}
print(json.dumps({"items": [item], "total": {"bytes": size, "chars": size, "tokens": size // 4,
                  "limit": 100000, "over": False}, "warnings": ["instructions"] if size > limit else []}))
'''


def with_context_budget(root, limit):
    """A stand-in tools/context_budget.py with the --json shape of the real one, counting AGENTS.md only."""
    (root / "tools" / "context_budget.py").write_text(CONTEXT_BUDGET)
    (root / "tools" / "limit.txt").write_text(str(limit))
    sh(root, "add", "tools"); sh(root, "commit", "-q", "-m", "context budget")


@macos_only(SANDBOX, sandbox=True)
def test_gate_and_rule_file_bundles_are_saved_and_the_tree_is_left_alone():
    root = fixture()
    try:
        with_context_budget(root, 1000)
        gate_b = bundle("gate-fix", "act", ("tools/gate.py",), check=COST_CHECK)
        rules_b = bundle("rules-note", "observe", ("AGENTS.md",))
        respond(root, judge=judge_text([gate_b, rules_b]),
                impl_gate_fix="@@@ FILE tools/gate.py\nimport sys\nsys.exit(0)\n@@@ END\n" + PASS + "\n",
                review_gate_fix=PASS,
                impl_rules_note="@@@ FILE AGENTS.md\n# rules\n@@@ END\n" + PASS + "\n",
                review_rules_note=PASS)
        before = head(root)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and head(root) == before, r.stdout + r.stderr + report_md(root)
        assert [e["outcome"] for e in outcome_of(root)["bundles"]] == ["saved", "saved"], outcome_of(root)
        assert not (root / "tools" / "gate.py").exists() and not (root / "AGENTS.md").exists()
        assert sh(root, "status", "--porcelain", "--untracked-files=no") == ""
        assert not any(x[0] == "triggers.py" for x in calls(root)), calls(root)
        # The reviewer of a rule-file change is told the two rules about such files; others are not.
        assert "always-loaded rule file" in (root / CYCLE / "prompts" / "review-rules-note.md").read_text()
        assert "always-loaded rule file" not in (root / CYCLE / "prompts" / "review-gate-fix.md").read_text()
    finally:
        shutil.rmtree(root, ignore_errors=True)


SECOND_EDIT = "@@@ EDIT tools/second.py\n@@@ SEARCH\nSECOND = 1\n@@@ REPLACE\nSECOND = 2\n@@@ END\n" + PASS + "\n"


@macos_only(SANDBOX, sandbox=True)
def test_two_changes_to_tracked_files_are_saved_in_one_run_on_one_snapshot():
    root = fixture()
    try:
        (root / "tools/second.py").write_text("SECOND = 1\n")
        sh(root, "add", "tools/second.py"); sh(root, "commit", "-q", "-m", "second target")
        with_context_budget(root, 1000)
        respond(root, judge=judge_text([bundle(), bundle("second", "act", ("tools/second.py",), check=COST_CHECK)]),
                impl_bump=EDIT_OK, review_bump=PASS, impl_second=SECOND_EDIT, review_second=PASS)
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and outcome_of(root)["state"] == "done", r.stdout + r.stderr + report_md(root)
        assert [e["outcome"] for e in outcome_of(root)["bundles"]] == ["saved", "saved"], outcome_of(root)
        assert (root / "tools/lib.py").read_text() == "VALUE = 1\n" and (root / "tools/second.py").read_text() == "SECOND = 1\n"
        # Both patches apply to the working tree they were built on.
        for bid in ("bump", "second"):
            sh(root, "apply", "--check", f"{CYCLE}/apply/{bid}.patch")
        records = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]
        assert records["bump"]["snapshot_rev"] == records["second"]["snapshot_rev"], records
        w = [c[-1].rsplit("/", 1)[-1] for c in worker_calls(root)]
        assert w == ["judge.md", "impl-bump.md", "review-bump.md", "impl-second.md", "review-second.md"], w
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_rule_file_over_the_warning_line_is_refused_with_both_numbers():
    root = fixture()
    try:
        with_context_budget(root, 10)
        respond(root, judge=judge_text([bundle("rules-long", "observe", ("AGENTS.md",))]),
                impl_rules_long="@@@ FILE AGENTS.md\n" + "# a rule that is too long\n" * 2 + "@@@ END\n" + PASS + "\n",
                review_rules_long=PASS)
        r = run_apply(root, CYCLE)
        text = report_md(root)
        assert r.returncode == 0 and not (root / "AGENTS.md").exists(), r.stdout + r.stderr + text
        assert "fixed context over its warning line: instructions 52 bytes > 10" in text, text
        assert not [c for c in worker_calls(root) if c[-1].endswith("review-rules-long.md")], worker_calls(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def candidate_test_results(root, bid):
    """Every file the candidate test run of a bundle leaves, in the apply folder or an attempt archive."""
    apply = root / CYCLE / "apply"
    return sorted(str(p.relative_to(apply)) for name in (f"{bid}.tests.json", f"{bid}.tests.txt")
                  for p in apply.rglob(name))


@macos_only(SANDBOX, sandbox=True)
def test_rule_file_over_the_warning_line_is_refused_before_the_candidate_test_run():
    root = fixture()
    try:
        with_context_budget(root, 10)
        respond(root, judge=judge_text([bundle("rules-long", "observe", ("AGENTS.md",))]),
                impl_rules_long="@@@ FILE AGENTS.md\n" + "# a rule that is too long\n" * 2 + "@@@ END\n" + PASS + "\n",
                review_rules_long=PASS)
        run_apply(root, CYCLE)
        text = report_md(root)
        assert "fixed context over its warning line: instructions 52 bytes > 10" in text, text
        # The builder still gets its one correction, and neither attempt starts a candidate test run.
        assert len([c for c in worker_calls(root) if c[-1].endswith("impl-rules-long.md")]) == 2, worker_calls(root)
        assert candidate_test_results(root, "rules-long") == [], candidate_test_results(root, "rules-long")
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_commit_check_failure_of_the_patch_is_refused_before_the_candidate_test_run():
    root = fixture()
    try:
        with_gate(root, env_blocked=False)
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_GATE_BAD, review_bump=PASS)
        run_apply(root, CYCLE)
        text = report_md(root)
        assert "GATE_BAD" in text, text
        assert candidate_test_results(root, "bump") == [], candidate_test_results(root, "bump")
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_a_baseline_file_without_comparable_results_stops_the_cycle_before_any_build():
    root = fixture()
    try:
        crash = root / "tools" / "tests" / "test_crash.py"
        crash.write_text("import sys\nprint('crash setup refused')\nsys.exit(3)\n")
        sh(root, "add", "tools/tests/test_crash.py"); sh(root, "commit", "-q", "-m", "a file that ends without ids")
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        for _ in range(2):
            r = run_apply(root, CYCLE)
            text = report_md(root)
            assert r.returncode == 1 and outcome_of(root)["failure"]["stage"] == "baseline", r.stdout + r.stderr + text
            assert "test_crash.py" in text and "crash setup refused" in text, text
        assert not [c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")], worker_calls(root)
        record = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        assert not record.get("attempts"), record
        assert not [c for c in calls(root) if c[0] == "now.py"], calls(root)   # a failure is the health check's to say
        crash.write_text("print('PASS crash')\n")
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and entry(root)["outcome"] == "saved", r.stdout + r.stderr + report_md(root)
        journal = [c for c in calls(root) if c[0] == "now.py"]
        assert len(journal) == 1 and ": 1 saved change to review and apply" in journal[0][-1], journal
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_installation_adds_to_the_never_list_and_removes_nothing():
    root = fixture()
    try:
        assert LPo.refusal("notes/a.md", str(root)) == "outside the allowed area: notes/a.md"
        assert LPo.refusal("system/x.md", str(root)) is None
        # Entries the engine fixes, repeated or not, stay; an entry cannot be taken off by the block.
        set_config(root, never=["system/x.md", "tools/frozen/", "instance/config.json"])
        assert LPo.never(str(root)) == LPo.ENGINE_NEVER + ("system/x.md", "tools/frozen/")
        assert LPo.refusal("system/x.md", str(root)) == "on the never list: system/x.md"
        assert LPo.refusal("tools/frozen/a.py", str(root)) == "on the never list: tools/frozen/a.py"
        assert "`tools/frozen/`" in LPo.render(str(root))
        for never in ([], ["../x/"], "system/", None):
            set_config(root, never=never)
            assert LPo.never(str(root)) == LPo.ENGINE_NEVER, never
            for path in ("instance/config.json", "state/NOW.md", ".git/config", "_private/x.md"):
                assert LPo.refusal(path, str(root)) == f"on the never list: {path}", (never, path)
            assert LPo.refusal("tools/loop/loop_policy.py", str(root)).startswith("changes the definition")
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_loop_tool_is_saved_and_one_loop_only_bundle_per_cycle():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle("loop-a", "observe", ("tools/loop/loop_watchdog.py",)),
                                        bundle("loop-b", "act", ("tools/loop/papers_cycle.sh",), check=COST_CHECK),
                                        bundle("policy", "observe", ("tools/loop/loop_policy.py",))]),
                impl_loop_a="@@@ FILE tools/loop/loop_watchdog.py\nX = 1\n@@@ END\n" + PASS + "\n", review_loop_a=PASS)
        r = run_apply(root, CYCLE)
        text = report_md(root)
        assert r.returncode == 0 and entry(root, "loop-a")["outcome"] == "saved", r.stdout + text
        rejected = json.dumps(outcome_of(root)["refused"])
        assert "loop-b" in rejected and "only the loop's own tools" in rejected, text
        assert "changes the definition of the never list and the allowed area: tools/loop/loop_policy.py" in rejected, text
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_bundle_without_files_is_asked_once_then_idea_only():
    root = fixture()
    try:
        named, vague = bundle("named"), bundle("vague", "observe")
        named["files"], vague["files"] = [], []
        respond(root, judge=judge_text([named, vague]), impl_named=EDIT_OK, review_named=PASS,
                judge_paths='```json\n{"paths": [{"id": "named", "files": ["tools/lib.py", "tools/tests/test_lib.py"]}], '
                            '"idea_only": [{"id": "vague", "reason": "no file owns this habit"}]}\n```\n' + PASS + "\n")
        r = run_apply(root, CYCLE)
        text = report_md(root)
        assert r.returncode == 0 and entry(root, "named")["outcome"] == "saved", r.stdout + text
        assert "idea only: no file owns this habit" in text, text
        asked = [c for c in worker_calls(root) if c[-1].endswith("judge-paths.md")]
        assert len(asked) == 1, asked
        # The stored judgment carries the answer, so the next run reuses it without asking again.
        assert run_apply(root, CYCLE).returncode == 0
        assert len([c for c in worker_calls(root) if c[-1].endswith("judge-paths.md")]) == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_review_falls_back_to_a_fresh_worker_of_the_builders_family():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        extra(root, "unavailable-codex", "")
        r = run_apply(root, CYCLE)
        text = report_md(root)
        assert r.returncode == 0 and outcome_of(root)["state"] == "done", r.stdout + r.stderr + text
        assert "reviewed by claude (model fake-claude-model), same family as the builder" in text, text
        rev = [c[c.index("--runtime") + 1] for c in worker_calls(root) if c[-1].endswith("review-bump.md")]
        assert rev == ["codex", "claude"], rev
        assert [c[c.index("--runtime") + 1] for c in worker_calls(root) if c[-1].endswith("judge.md")] == ["claude"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_review_walks_the_other_families_in_order():
    root = fixture()
    try:
        respond(root, review_x=PASS)
        (root / CYCLE / "prompts").mkdir(parents=True)
        (root / CYCLE / "prompts" / "review-x.md").write_text("review\n")
        M = load(root / "tools" / "loop" / "papers_apply.py", "papers_apply_fixture_order")
        receipt = str(root / CYCLE / "review-x.receipt")
        set_config(root, runtime_orders={"review": ["codex", "gemini", "claude"]})
        with patch.dict(os.environ, worker_env(root)):
            order = [e["runtime"] for e in LW.loop_runtimes.order("review", built_by="claude", root=str(root))]
            assert order == ["codex", "gemini", "claude"], order
            first = LW.run_in_order("review", "claude", f"{CYCLE}/prompts/review-x.md", receipt, root=str(root))
            assert LW.reviewer_line({"reviewer": first}) == "codex (model fake-codex-model)", first
            extra(root, "unavailable-codex", "")
            second = LW.run_in_order("review", "claude", f"{CYCLE}/prompts/review-x.md", receipt, root=str(root))
            assert second["runtime"] == "gemini" and second["skipped"] == ["codex"], second
            assert LW.reviewer_line({"reviewer": second}) == "gemini (model fake-gemini-model)"
            extra(root, "unavailable-gemini", "")
            extra(root, "unavailable-claude", "")
            try:
                LW.run_in_order("review", "claude", f"{CYCLE}/prompts/review-x.md", receipt, root=str(root))
            except LC.WorkerUnavailable as e:
                assert "codex, gemini, claude" in e.reason, e.reason
            else:
                raise AssertionError("WorkerUnavailable expected")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_judge_is_not_given_the_experiment_registry():
    root = fixture()
    try:
        respond(root, judge=judge_text([]))
        registry = (root / "_private" / "work" / "experiments.md").read_bytes()
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and outcome_of(root)["state"] == "done", r.stdout + r.stderr
        judge = next(a for a in worker_calls(root) if a[-1].endswith("judge.md"))
        materials = [judge[i + 1] for i, a in enumerate(judge) if a == "--read-material"]
        assert materials and not any("experiments.md" in m for m in materials), materials
        assert "experiments.md" not in (root / CYCLE / "prompts" / "judge.md").read_text()
        assert not (root / CYCLE / "apply" / "inputs").exists()
        assert (root / "_private" / "work" / "experiments.md").read_bytes() == registry
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_judge_prompt_renders_the_policy_and_asks_nothing_of_the_owner():
    prompt = LP.judge_prompt("_private/work/papers/2026-10-07-kit", "papers")
    assert LPo.render() in prompt
    assert "owner" not in prompt.lower() and LCo.LENS_HEADING in prompt
    assert LCo.LENS_SKILL in prompt, prompt
    assert "A stop condition is about this change's measurements only. Do not put commit paths or hook states" in prompt


def test_loop_a_top_selection_skips_papers_carded_in_earlier_cycles():
    body = (f"import sys; sys.path.insert(0, {str(HERE / 'loop' / 'lib')!r}); from loop_papers import select_top; "
            "select_top(sys.argv[1], sys.argv[2])")
    root = Path(tempfile.mkdtemp(prefix="papers-top-"))
    try:
        cur = root / "2026-11-18-kit"
        cur.mkdir()
        # 2601.00001 was named by a card of an older cycle; 2601.00003 was selected there but no card named
        # it, so it is not in the record and may be picked again; 2601.00004 was read by a newer cycle (a
        # resume of an older date must not exclude anything).
        (root / "read.json").write_text(json.dumps({"read": {"2601.00001": "2026-11-11", "2601.00004": "2026-11-25"}}))
        (cur / "candidates.tsv").write_text("arxiv_id\tx\ttitle\n2601.00001v2\tx\tOld One\n2601.00002\tx\tNew Two\n"
                                            "2601.00003\tx\tNo Card\n2601.00004\tx\tNewer\n")
        (cur / "triage.tsv").write_text("2601.00001v2\t3\tverify\n2601.00002\t3\tverify\n"
                                        "2601.00003\t3\tverify\n2601.00004\t3\tverify\n")
        p = subprocess.run([sys.executable, "-c", body, str(cur), str(root / "read.json")], capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr
        ids = [line.split("\t")[0] for line in (cur / "top.tsv").read_text().splitlines()]
        assert ids == ["2601.00002", "2601.00003", "2601.00004"], ids
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_a_worker_run_is_read_from_its_record_not_its_receipt():
    for receipt, saved in (("nonsense", True), ("lie", False)):
        root = fixture()
        try:
            respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
            r = run_apply_env(root, {"FAKE_RECEIPT": receipt}, CYCLE)
            assert (r.returncode == 0) == saved, (receipt, r.stdout + r.stderr)
            assert (root / CYCLE / "apply" / "bump.patch").is_file() == saved, receipt
            assert LS.apply_status(str(root / CYCLE)) == ("done" if saved else "failed"), (receipt, report_md(root))
            # The receipt is still kept for a person.
            assert (root / CYCLE / "apply" / "judge.receipt").is_file()
        finally:
            shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_a_reviewed_patch_is_saved_from_the_working_tree_and_nothing_is_written():
    root = fixture()
    try:
        (root / "tools" / "lib.py").write_text("VALUE = 1\n# local edit\n")
        (root / "other.txt").write_text("dirty elsewhere\n")
        (root / "tools" / "new.py").write_text("NEW = 1\n")
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        before, status = head(root), sh(root, "status", "--porcelain")
        r = run_apply(root, CYCLE)
        text = report_md(root)
        assert r.returncode == 0 and outcome_of(root)["state"] == "done", r.stdout + r.stderr + text
        assert entry(root)["outcome"] == "saved" and entry(root)["patch"] == f"{CYCLE}/apply/bump.patch", entry(root)
        # Nothing in the tree moved: no commit, no staged or written file.
        assert head(root) == before and sh(root, "status", "--porcelain") == status
        assert (root / "tools" / "lib.py").read_text() == "VALUE = 1\n# local edit\n"
        patch_text = (root / CYCLE / "apply" / "bump.patch").read_text()
        assert "# local edit" in patch_text, "the candidate must be built on the working-tree snapshot"
        sh(root, "apply", "--check", f"{CYCLE}/apply/bump.patch")
        impl = next(a for a in worker_calls(root) if a[-1].endswith("impl-bump.md"))
        assert impl[impl.index("--worktree") + 1] == "dirty" and impl[impl.index("--runtime") + 1] == "claude", impl
        rev = next(a for a in worker_calls(root) if a[-1].endswith("review-bump.md"))
        assert rev[rev.index("--runtime") + 1] == "codex", rev
        assert "reviewed by codex (model fake-codex-model)" in text and "same family" not in text, text
        # A saved change is journaled once, privately, naming the report; a second run builds nothing again.
        said = [x for x in calls(root) if x[0] == "now.py"]
        assert said == [["now.py", "log", "--private", "[system/state] loop papers 2026-10-07: 1 saved change to "
                         f"review and apply, see {CYCLE}/REPORT.md"]], said
        n = len(worker_calls(root))
        assert "skip" in run_apply(root, CYCLE).stdout and len(worker_calls(root)) == n
        assert run_apply(root, CYCLE, "--force").returncode == 0 and len(worker_calls(root)) == n
        assert [x for x in calls(root) if x[0] == "now.py"] == said
        # What to do comes first: the saved change's block with its patch and the commands, exactly.
        patch_rel = f"{CYCLE}/apply/bump.patch"
        head_lines = text.splitlines()[:30]
        assert head_lines[2] == "**Status:** done. 1 saved." and head_lines[4] == "## Saved: yours to apply (1)", head_lines
        for line in (f"- Patch: `{patch_rel}`", f"git apply --check {patch_rel}", f"git apply {patch_rel}",
                     "python3 tools/tests/run.py", f"If the tests fail, or to undo it later: `git apply -R {patch_rel}`",
                     "- Files: `tools/lib.py`, `tools/tests/test_lib.py`"):
            assert line in head_lines, (line, head_lines)
        assert "0 tests skipped in the sandbox" in text, text
        # The owner's next session learns of it: the line shows in the state view of a real installation.
        with patch.dict(os.environ):   # importing it points MOTTORI_INSTANCE at an empty instance
            import test_state_runtime as SR
        inst = SR.instance()
        try:
            SR.run_now(inst, *said[0][1:])
            view = SR.run_now(inst, "context").stdout
            assert said[0][-1].split("] ", 1)[1] in view, view
        finally:
            shutil.rmtree(inst, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# The gate baseline is git-ignored, so the clone has it only if the apply step copies it in.
BASELINE_GATE = r"""import os, sys
baseline = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", ".gate-baseline.json")
try:
    ok = open(baseline).read() == "baseline\n"
except OSError:
    ok = False
if not ok:
    print(f"[gate] Gate baseline is corrupt ({baseline}).", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
"""


def with_baseline_gate(root):
    (root / "tools" / "gate.py").write_text(BASELINE_GATE)
    with open(root / ".gitignore", "a") as f:
        f.write("state/.gate-baseline.json\n")
    sh(root, "add", "tools/gate.py", ".gitignore")
    sh(root, "commit", "-q", "-m", "baseline gate fixture")
    (root / "state").mkdir(exist_ok=True)
    (root / "state" / ".gate-baseline.json").write_text("baseline\n")


@macos_only(SANDBOX, sandbox=True)
def test_loop_b_clone_commit_check_receives_the_ignored_baseline():
    root = fixture()
    try:
        with_baseline_gate(root)
        check = subprocess.run([sys.executable, "tools/gate.py"], cwd=root, capture_output=True, text=True)
        assert check.returncode == 0, "the fixture gate must pass in the real tree: " + check.stderr
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        r = run_apply(root, CYCLE)
        text = report_md(root)
        assert r.returncode == 0 and "corrupt" not in text and outcome_of(root)["state"] == "done", r.stdout + r.stderr + text
        assert (root / CYCLE / "apply" / "bump.gate.txt").read_text().startswith("exit 0")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- Overhaul regressions
def test_new_failures_sees_prose_named_check():
    base_text = "✓ papers_cycle normal a\n✗ papers_cycle negative b\n✓ kit_sync normal c\n✓ kit_sync negative d\n"
    cand_text = "✗ papers_cycle normal a: boom\n✗ papers_cycle negative b\n✓ kit_sync normal c (0.3s)\n"
    passes, fails = LK.parse_test_output(base_text)
    base = {"t.py": {"rc": 1, "timeout": False, "passes": passes, "fails": fails}}
    passes, fails = LK.parse_test_output(cand_text)
    cand = {"t.py": {"rc": 1, "timeout": False, "passes": passes, "fails": fails}}
    bad = " ".join(LK.new_failures(base, cand))
    assert "new failures papers_cycle normal a" in bad and "not run kit_sync negative d" in bad, bad
    # A file that crashes without failing IDs blocks even when the base crashed the same way.
    crashed = {"t.py": {"rc": 1, "timeout": False, "passes": [], "fails": []}}
    assert LK.new_failures(crashed, crashed), "a crash on both sides hid the whole file"
    # A repeated name still counts, so losing one copy is a missing check.
    twice = LK.parse_test_output("✓ same\n✓ same\n")
    assert twice == (["same", "same #2"], []), twice


@macos_only(SANDBOX, sandbox=True)
def test_sandbox_blocks_unix_socket_and_secrets():
    import socket
    import threading
    keys = ("SSH_AUTH_SOCK", "GH_PAT", "SLACK_WEBHOOK_URL")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        os.environ.update(SSH_AUTH_SOCK="/nonexistent/agent.sock", GH_PAT="x", SLACK_WEBHOOK_URL="https://example.invalid/h")
        env = LI.sandbox_env("/h", "/t")
        assert not any(k in env for k in keys), sorted(env)
        assert env.get("PATH") and env["HOME"] == "/h", env
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    sbx = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
    if not os.path.exists(sbx):
        return
    outside = tempfile.mkdtemp(prefix="pa-sock-")
    writable = os.path.realpath(tempfile.mkdtemp(prefix="pa-sbx-"))
    try:
        path = os.path.join(outside, "s")
        server = socket.socket(socket.AF_UNIX)
        server.bind(path)
        server.listen(1)
        def accept():
            try:
                server.accept()
            except OSError:
                pass   # Closed at the end of the test.
        threading.Thread(target=accept, daemon=True).start()
        profile = os.path.join(writable, "p.sb")
        Path(profile).write_text(LI.sandbox_profile(writable))
        code = "import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); print('connected')"
        p = subprocess.run([sbx, "-f", profile, sys.executable, "-c", code, path], capture_output=True, text=True)
        assert p.returncode != 0 and "connected" not in p.stdout, p.stdout + p.stderr
        server.close()
    finally:
        shutil.rmtree(outside, ignore_errors=True)
        shutil.rmtree(writable, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_sandbox_denies_reading_private_and_agent_homes():
    sbx = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
    if not os.path.exists(sbx):
        return
    base = os.path.realpath(tempfile.mkdtemp(prefix="pa-read-"))
    try:
        root, home, writable = (os.path.join(base, n) for n in ("root", "home", "w"))
        for d in (root + "/_private", home + "/.ssh", home + "/.claude", writable):
            os.makedirs(d)
        for f in (root + "/_private/secret.md", home + "/.ssh/id", home + "/.claude/t.jsonl", root + "/public.md"):
            Path(f).write_text("x")
        profile = os.path.join(writable, "p.sb")
        Path(profile).write_text(LI.sandbox_profile(writable, root=root, home=home, readable=[root]))
        code = "import sys; open(sys.argv[1]).read(); print('read')"
        for f in (root + "/_private/secret.md", home + "/.ssh/id", home + "/.claude/t.jsonl"):
            p = subprocess.run([sbx, "-f", profile, sys.executable, "-c", code, f], capture_output=True, text=True)
            assert p.returncode != 0 and "read" not in p.stdout, (f, p.stdout, p.stderr)
        p = subprocess.run([sbx, "-f", profile, sys.executable, "-c", code, root + "/public.md"], capture_output=True, text=True)
        assert p.returncode == 0 and "read" in p.stdout, p.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_git_and_python_in_the_sandbox_print_nothing_on_stderr():
    # Tests compare what these print; a tool that complains inside the sandbox only would fail them there.
    sbx = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
    if not os.path.exists(sbx):
        return
    base = os.path.realpath(tempfile.mkdtemp(prefix="pa-quiet-"))
    try:
        root, home, tmp = (os.path.join(base, n) for n in ("root", "home", "tmp"))
        for d in (root, home, tmp):
            os.makedirs(d)
        profile = os.path.join(base, "p.sb")
        Path(profile).write_text(LI.sandbox_profile(base, root=root, home=home))
        env = LI.sandbox_env(home, tmp)
        for cmd in (["git", "--version"], ["python3", "-c", "print('ok')"]):
            p = subprocess.run([sbx, "-f", profile, *cmd], capture_output=True, text=True, env=env, cwd=root)
            assert p.returncode == 0 and p.stdout and p.stderr == "", (cmd, p.stdout, p.stderr)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_snapshot_after_git_mv():
    root = fixture()
    try:
        (root / "tools" / "a.py").write_text("A = 1\n")
        sh(root, "add", "tools/a.py"); sh(root, "commit", "-q", "-m", "a")
        sh(root, "mv", "tools/a.py", "tools/b.py")
        M = load(root / "tools" / "loop" / "papers_apply.py", "papers_apply_fixture_mv")
        try:
            snap, overlaid = LI.build_snapshot(str(root))
            names = sh(Path(LI._SNAPSHOT_REPOS[snap]), "ls-tree", "-r", "--name-only", snap).split()
            assert "tools/b.py" in names and "tools/a.py" not in names, (names, overlaid)
        finally:
            LI.cleanup_snapshots()
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_gate_clone_mirrors_new_dir_untracked_and_deleted():
    root = fixture()
    try:
        (root / "tools" / "d.py").write_text("D = 1\n")
        sh(root, "add", "tools/d.py"); sh(root, "commit", "-q", "-m", "d")
        (root / "tools" / "sub").mkdir()
        (root / "tools" / "sub" / "b.py").write_text("B = 1\n")
        sh(root, "add", "tools/sub/b.py")
        (root / "tools" / "u.py").write_text("U = 1\n")
        (root / "tools" / "d.py").unlink()
        M = load(root / "tools" / "loop" / "papers_apply.py", "papers_apply_fixture_gateclone")
        with LI.Isolate(head(root), str(root)) as iso:
            LK._prepare_gate_clone(iso, (), str(root))
            tree = Path(iso.tree)
            assert (tree / "tools/sub/b.py").read_text() == "B = 1\n"
            assert (tree / "tools/u.py").read_text() == "U = 1\n"
            assert not (tree / "tools/d.py").exists(), "a file deleted in the main tree stayed in the gate clone"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_isolate_and_snapshot_leave_out_the_excluded_folders():
    root = fixture()
    try:
        set_config(root, clone_excluded=["vault/"])
        (root / "vault").mkdir()
        (root / "vault" / "big.txt").write_text("vault\n")
        sh(root, "add", "vault"); sh(root, "commit", "-q", "-m", "vault")
        M = load(root / "tools" / "loop" / "papers_apply.py", "papers_apply_fixture_sparse")
        with LI.Isolate(head(root), str(root)) as iso:
            assert (Path(iso.tree) / "tools" / "lib.py").is_file()
            assert not (Path(iso.tree) / "vault").exists(), "the clone checked out vault/"
            assert sh(Path(iso.tree), "status", "--porcelain") == ""
        (root / "tools" / "lib.py").write_text("VALUE = 1\n# dirty\n")
        (root / "vault" / "big.txt").write_text("changed\n")
        try:
            snap, overlaid = LI.build_snapshot(str(root))
            repo = Path(LI._SNAPSHOT_REPOS[snap])
            assert not (repo / "vault").exists() and "vault/big.txt" not in overlaid, overlaid
            assert sh(repo, "show", f"{snap}:vault/big.txt") == "vault\n"
            assert sh(repo, "show", f"{snap}:tools/lib.py") == "VALUE = 1\n# dirty\n"
        finally:
            LI.cleanup_snapshots()
        set_config(root)   # The engine default leaves nothing out.
        with LI.Isolate(head(root), str(root)) as iso:
            assert (Path(iso.tree) / "vault" / "big.txt").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_loop_a_gate_new_failure_on_failing_base_is_patch():
    root = fixture()
    try:
        with_gate(root, env_blocked=True)
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_GATE_BAD, review_bump=PASS)
        run_apply(root, CYCLE)
        text = report_md(root)
        assert "GATE_BAD" in text and entry(root)["outcome"] == "abandoned", text
        assert not [c for c in worker_calls(root) if c[-1].endswith("review-bump.md")]
        record = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        assert record["attempts"][0]["failure_stage"] == "gate", record
    finally:
        shutil.rmtree(root, ignore_errors=True)


@macos_only(SANDBOX, sandbox=True)
def test_worker_failure_is_pending_without_spending_budget():
    root = fixture()
    try:
        respond(root, judge=judge_text([bundle()]), impl_bump=EDIT_OK, review_bump=PASS)
        extra(root, "impl-bump.rc", "1")
        r = run_apply(root, CYCLE)
        impl = [c for c in worker_calls(root) if c[-1].endswith("impl-bump.md")]
        assert len(impl) == 1, (len(impl), r.stdout + r.stderr)
        record = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        assert record["outcome"] == "pending" and not record.get("attempts"), record
        assert LS.apply_status(str(root / CYCLE)) == "pending" and PA.backlog_dirs(str(root)) == [CYCLE]
        (root / "_fake" / "resp" / "impl-bump.rc").unlink()
        r = run_apply(root, CYCLE)
        assert r.returncode == 0 and outcome_of(root)["state"] == "done", r.stdout + r.stderr + report_md(root)
        record = json.loads((root / CYCLE / "apply/state.json").read_text())["bundles"]["bump"]
        assert record["outcome"] == "saved" and len(record["attempts"]) == 1, record
        assert "worker_env_holds" not in record, record
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _render_with_cycle_script(script, template, out_dir):
    """Run the render_prompt() of a cycle script's beat on a real template, from the repository root."""
    module = {"papers_cycle.sh": "loop_papers"}[script]
    m = "def render_prompt(" in (HERE / "loop" / "lib" / f"{module}.py").read_text(encoding="utf-8")
    assert m, f"{script}: render() not found"
    dst = Path(out_dir) / "prompt.md"
    prog = (f"import sys; sys.path.insert(0, 'tools/loop/lib'); import {module}; "
            "sys.exit(0 if " + module + ".render_prompt(sys.argv[1], sys.argv[2], sys.argv[3]) else 1)")
    r = subprocess.run([sys.executable, "-c", prog, template, str(dst), str(out_dir)], cwd=HERE.parent,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and dst.is_file(), (script, r.stderr)
    return dst.read_text(encoding="utf-8")


def test_loop_prompts_render_protected_list_from_applier():
    # The worker prompts show the never list and the allowed area as loop_policy renders them.
    out = Path(tempfile.mkdtemp(prefix="prompt-render-"))
    try:
        for script, template in (("papers_cycle.sh", "system/loop/prompts/propose.md"),):
            t = _render_with_cycle_script(script, template, out)
            assert "{{PROTECTED}}" not in t, (template, "placeholder left")
            assert LPo.render() in t, template
            assert "owner" not in t.lower(), template
    finally:
        shutil.rmtree(out, ignore_errors=True)


# Every test function of this file runs; none can be left out of a hand-kept list.
TESTS = [f for name, f in list(globals().items()) if name.startswith("test_") and callable(f)]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"papers_apply: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
