#!/usr/bin/env python3
"""Run the papers cycle of the loop in scratch trees.

Workers, the sweep and the fetch are stand-ins; nothing reaches the network or a model program."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parent
PY = sys.executable
# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/papers_cycle.sh",
    "tools/loop/lib/loop_beat.py",
    "tools/loop/lib/loop_papers.py",
)
PASSED, FAILED = [], []
# The allowance of the papers source to send (tools/options.py on loop sources=papers yes).
ALLOWED_TO_SEND = {"model_send": {"deny_prefixes": ["_private/"], "allow_prefixes": ["_private/work/papers/"]}}


def ok(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    suffix = f": {detail}" if detail and not condition else ""
    print(("✓ " if condition else "✗ ") + name + suffix)


def run(*args, cwd=None, env=None, timeout=20):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        [str(a) for a in args], cwd=cwd, env=merged,
        capture_output=True, text=True, timeout=timeout,
    )


def write(path, text, executable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def copy_tool(root, name):
    dst = Path(root, "tools", name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / name, dst)
    return dst


def copy_loop(root):
    """Copy the loop's modules (tools/loop/loop_*.py, tools/loop/lib/loop_*.py) and the engine modules they import into a scratch tree's tools folder."""
    for src in sorted(HERE.glob("loop/lib/loop_*.py")) + sorted(HERE.glob("loop/loop_*.py")):
        copy_tool(root, src.relative_to(HERE).as_posix())
    for name in ("lib/paths.py", "lib/safeio.py", "lib/config.py"):
        copy_tool(root, name)
    # Papers may send. The stage orders these tests expect: collection stages try codex first, the others claude.
    write(Path(root, "instance/config.json"), json.dumps({"egress": ALLOWED_TO_SEND, "loop": {"runtime_orders": {
        "default": ["claude", "codex"], "triage": ["codex", "claude"], "card": ["codex", "claude"],
        "propose": ["codex", "claude"], "review": ["codex", "claude"]}}}))


def isolated_env(root, extra=None):
    home = Path(root, "home")
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "MOTTORI_INSTANCE": os.path.realpath(root),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_PROXY": "*",
        "no_proxy": "*",
    }
    if extra:
        env.update(extra)
    return env


def stub_calls(root, name):
    return read_text(Path(root, name + "-calls.txt")).splitlines()


def last_now_call(root):
    p = Path(root, "now-calls.txt")
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    return lines[-1] if lines else ""


def read_text(path):
    path = Path(path)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


PAPERS_WORKER = r"""
import json, os, sys
rt, prompt = sys.argv[sys.argv.index("--runtime") + 1], sys.argv[-1]
name, d = os.path.basename(prompt)[:-3], os.path.dirname(os.path.dirname(prompt))
open("worker-calls.txt", "a").write(f"{name} {rt}\n")
if os.environ.get("FW_MODE") == "hang" and name == "triage":
    import time
    time.sleep(600)
# A card worker's count: a sentence that says one thing and the fenced JSON block the beat reads.
CARDS = os.environ.get("FW_CARDS", 'RECEIPT: cards 1\n```json\n{"cards": 1}\n```\n')
run = os.path.abspath(f"_private/work/runs/{name}-{rt}")
os.makedirs(run, exist_ok=True)
json.dump({"run_id": os.path.basename(run), "run_dir": run}, open(sys.argv[sys.argv.index("--run-file") + 1], "w"))
meta = {"capability": "read-only" if "--read-only" in sys.argv else "workspace-write", "status": "success", "unavailable": None}
# FW_RECEIPT: nonsense prints a receipt nothing can be read from; FW_FAILS names stages whose record
# says the run failed while the receipt says success.
say = (lambda: print("~~ no receipt here ~~")) if os.environ.get("FW_RECEIPT") == "nonsense" else \
    (lambda: print(f"run: {run}\nstatus: success"))
if rt in os.environ.get("FW_DOWN", "").split(","):
    meta.update(status="failed", unavailable="model-not-available", result_bytes=0)
    json.dump(meta, open(f"{run}/meta.json", "w")); say(); sys.exit(1)
body, target = {"triage": ("2601.00001\t3\tverify\n", "triage.tsv"), "propose": ("### p1\n" + "x" * 250 + "\n", "PROPOSALS.md"),
                "digest-en": ("digest\nRECEIPT: digest\n", None)}.get(name, ("card\n" + CARDS, f"cards/group-{name[5:]}.md"))
open(f"{run}/result.txt", "w").write(body)
meta["result_bytes"] = len(body)
if name in os.environ.get("FW_FAILS", "").split(","):
    meta["status"] = "failed"
json.dump(meta, open(f"{run}/meta.json", "w"))
say()
"""


def papers_fixture(root):
    copy_tool(root, "loop/papers_cycle.sh")
    copy_loop(root)
    for t in ("triage", "card", "propose", "digest-en"):
        write(Path(root, "system/loop/prompts", f"{t}.md"), f"{t} {{{{DIR}}}}\n")
    # The sweep and the fetch read prepared rows, so nothing reaches the network.
    write(Path(root, "tools/loop/papers/sweep.py"), "import sys\na=sys.argv; o=a[a.index('--out')+1]\nopen(o,'w').write('arxiv_id\\tx\\ttitle\\n2601.00001\\tx\\tT one\\n')\n")
    write(Path(root, "tools/loop/papers/fetch_arxiv.py"), "import os,sys\nfor l in open(sys.argv[1]):\n    i=l.split('\\t')[0].strip()\n    i and open(os.path.join(sys.argv[2], i+'-x.txt'),'w').write('t')\n")
    write(Path(root, "tools/fresh_worker.py"), PAPERS_WORKER)
    for name in ("now.py", "triggers.py", "loop/loop_watchdog.py", "loop/papers_apply.py"):
        write(Path(root, "tools", name), "")


def test_papers_cycle_walks_to_the_next_runtime_only_when_one_cannot_be_called():
    cases = (("", "triage codex|card-A codex|propose codex|digest-en claude", 0),
             ("codex", "triage codex|triage claude|card-A codex|card-A claude|propose codex|propose claude|digest-en claude", 0),
             ("codex,claude", "triage codex|triage claude", 1))
    for down, expected, rc in cases:
        with tempfile.TemporaryDirectory(prefix="instance-papers-walk.") as td:
            papers_fixture(td)
            r = run("bash", "tools/loop/papers_cycle.sh", "--force", cwd=td, env=isolated_env(td, {"FW_DOWN": down}), timeout=120)
            calls = "|".join(read_text(Path(td, "worker-calls.txt")).splitlines())
            cycle = next(Path(td, "_private/work/papers").glob("*-kit"), Path(td, "missing"))
            state = json.loads(read_text(Path(td, "_private/papers/state.json")) or "{}")
            files = all(read_text(cycle / f).startswith(b) for f, b in (("triage.tsv", "2601.00001"), ("PROPOSALS.md", "### p1"),
                                                                          ("cards/group-A.md", "card"), ("DIGEST-EN.md", "digest")))
            # Every worker is told that its answer is the file.
            told = "cannot write files" in read_text(cycle / "prompts/triage.md")
            ok(f"papers_cycle {'negative' if rc else 'normal'} with {down + ' unavailable' if down else 'every runtime answering'} runs {expected}",
               r.returncode == rc and calls == expected and (files and state.get("status") == "ok") == (rc == 0)
               and told,
               f"rc={r.returncode} {calls} {state} | " + read_text(Path(td, "_private/papers/cycle.log"))[-300:])


def test_papers_cycle_reads_each_run_from_its_record_not_its_receipt():
    for extra, name, digest in (({"FW_RECEIPT": "nonsense", "FW_DOWN": "codex"}, "a nonsense receipt", True),
                                ({"FW_FAILS": "digest-en"}, "a run whose record says failed", False)):
        with tempfile.TemporaryDirectory(prefix="instance-papers-data.") as td:
            papers_fixture(td)
            r = run("bash", "tools/loop/papers_cycle.sh", "--force", cwd=td, env=isolated_env(td, extra), timeout=120)
            cycle = next(Path(td, "_private/work/papers").glob("*-kit"), Path(td, "missing"))
            state = json.loads(read_text(Path(td, "_private/papers/state.json")) or "{}")
            calls = "|".join(read_text(Path(td, "worker-calls.txt")).splitlines())
            report = read_text(cycle / "REPORT.md")
            ok(f"papers_cycle normal with {name} follows the run's record",
               r.returncode == 0 and state.get("status") == "ok" and (cycle / "DIGEST-EN.md").is_file() == digest
               and ("triage claude" in calls) == bool(extra.get("FW_DOWN"))
               and ("No paper digest: its worker failed" in report) == (not digest),
               f"rc={r.returncode} {state} {calls} | " + report[-300:])


def test_papers_cycle_takes_counts_from_data_and_names_no_experiment():
    """The card count comes from the card workers' JSON blocks; no prompt or report reserves an experiment."""
    with tempfile.TemporaryDirectory(prefix="instance-papers-contract.") as td:
        papers_fixture(td)
        for t in ("triage", "card", "propose", "digest-en"):
            write(Path(td, "system/loop/prompts", f"{t}.md"), read_text(ROOT / "system/loop/prompts" / f"{t}.md"))
        write(Path(td, "_private/work/experiments.md"), "# registry\n\n| X41 | a | b | c | d | e | f |\n")
        registry = read_text(Path(td, "_private/work/experiments.md"))
        # The worker's sentence says 7 cards, its block 2; a proposal names an experiment number.
        cards = 'RECEIPT: cards 7\n```json\n{"cards": 2}\n```\n'
        write(Path(td, "tools/loop/papers_apply.py"), "import sys\nsys.exit(3 if '--backlog' in sys.argv else 0)\n")
        r = run("bash", "tools/loop/papers_cycle.sh", "--force", cwd=td, env=isolated_env(td, {"FW_CARDS": cards}), timeout=120)
        cycle = next(Path(td, "_private/work/papers").glob("*-kit"), Path(td, "missing"))
        log = read_text(Path(td, "_private/papers/cycle.log"))
        report = read_text(cycle / "REPORT.md")
        prompts = "".join(read_text(p) for p in (cycle / "prompts").glob("*.md"))
        ok("papers_cycle normal takes the card count from the JSON block, not the sentence",
           r.returncode == 0 and "cards 2" in log and "cards 7" not in log and "paper summaries 2," in report, log[-300:] + report[:300])
        ok("papers_cycle normal prompts and report carry no experiment number and the registry is untouched",
           not re.search(r"X\d", prompts + report) and "experiment:" not in prompts + report
           and "registry" not in (prompts + report).lower()
           and read_text(Path(td, "_private/work/experiments.md")) == registry and "{{" not in prompts,
           re.findall(r".{20}X\d.{20}", prompts + report)[:3])
        ok("papers_cycle negative a backlog run that fails says what happened, not that something retries it",
           "backlog apply ended with exit 3" in log, log[-300:])
        ok("papers_cycle normal the report promises no retry that would not come",
           "tries again" not in report, report[-400:])


def test_papers_cycle_workers_are_bounded():
    """A worker that hangs is stopped at the beat's one worker bound."""
    with tempfile.TemporaryDirectory(prefix="instance-papers-bound.") as td:
        papers_fixture(td)
        # The bound is loop_beat.WORKER_TIMEOUT; this run sets it to 2 seconds instead of hours.
        write(Path(td, "bounded.py"), "import sys\nsys.path.insert(0, 'tools/loop/lib')\nimport loop_beat\n"
              "loop_beat.WORKER_TIMEOUT = 2\nimport loop_papers\nsys.exit(loop_papers.main(['--force']))\n")
        t0 = time.monotonic()
        try:
            r = run(PY, "bounded.py", cwd=td, env=isolated_env(td, {"FW_MODE": "hang"}), timeout=45)
        except subprocess.TimeoutExpired:
            r = None
        took = time.monotonic() - t0
        cycle = next(Path(td, "_private/work/papers").glob("*-kit"), Path(td, "missing"))
        state = json.loads(read_text(Path(td, "_private/papers/state.json")) or "{}")
        ok("papers_cycle negative a hung triage worker is stopped at the worker bound",
           r is not None and r.returncode == 1 and took < 30 and "triage" in state.get("failed_stages", [])
           and "TIMEOUT 2s" in read_text(cycle / "triage.receipt"),
           f"took {took:.0f}s {state} | " + read_text(cycle / "triage.receipt")[-200:])


def test_papers_cycle_weekly_skip():
    """A scheduled rerun within seven days of the last cycle spends no model worker again; --force runs."""
    with tempfile.TemporaryDirectory(prefix="instance-papers-skip.") as td:
        papers_fixture(td)
        first = run("bash", "tools/loop/papers_cycle.sh", cwd=td, env=isolated_env(td), timeout=120)
        before = read_text(Path(td, "worker-calls.txt")).splitlines()
        r = run("bash", "tools/loop/papers_cycle.sh", cwd=td, env=isolated_env(td), timeout=120)
        after = read_text(Path(td, "worker-calls.txt")).splitlines()
        log = read_text(Path(td, "_private/papers/cycle.log"))
        ok("papers_cycle normal second run in the same week is skipped",
           first.returncode == 0 and before and r.returncode == 0 and "skip: last cycle" in log and after == before,
           log[-300:])


TESTS = (
    test_papers_cycle_walks_to_the_next_runtime_only_when_one_cannot_be_called,
    test_papers_cycle_reads_each_run_from_its_record_not_its_receipt,
    test_papers_cycle_workers_are_bounded,
    test_papers_cycle_takes_counts_from_data_and_names_no_experiment,
    test_papers_cycle_weekly_skip,
)


def main():
    # A test function this list does not run would pass unseen, so it fails the file.
    for name in sorted(n for n, f in list(globals().items()) if n.startswith("test_") and callable(f) and f not in TESTS):
        ok(f"{name} is in TESTS", False)
    for test in TESTS:
        try:
            test()
        except Exception as exc:
            ok(test.__name__ + " harness", False, f"{type(exc).__name__}: {exc}")
    print(f"loop_cycles: {len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
