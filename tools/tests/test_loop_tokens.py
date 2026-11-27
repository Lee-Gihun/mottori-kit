#!/usr/bin/env python3
"""What a cycle spends and reads: every model run of a cycle is counted in one file in its cycle folder,
a run without a count is not counted as zero, no new stage starts once loop.token_ceiling is reached, a
cycle stopped there is not a failed one and goes on once the ceiling is raised, the cycle report ends
with the count and status shows the last cycle's, and a papers cycle reads at most eight papers and
records as read only those a card names.

Every case runs in a scratch tree with stand-ins for the workers, the sweep and the fetch; no model
program starts and nothing reaches the network."""
import datetime
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_papers  # noqa: E402
import loop_report  # noqa: E402
import loop_watch_checks  # noqa: E402
import loop_worker  # noqa: E402
import test_loop_cycles as Y  # noqa: E402
import test_loop_way_in as W  # noqa: E402
import test_papers_apply as T  # noqa: E402

# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/lib/loop_worker.py",
    "tools/loop/lib/loop_papers.py",
)


def _instance(block=None):
    root = tempfile.mkdtemp(prefix="loop-tokens-")
    os.makedirs(os.path.join(root, "instance"))
    with open(os.path.join(root, "instance", "config.json"), "w") as f:
        json.dump({"loop": block or {}}, f)
    return root


def _launcher(root, totals):
    """A launch that leaves a run whose record carries the next total of totals (None: no count)."""
    started = []

    def launch(args, receipt):
        n = len(started)
        started.append(args)
        run = os.path.join(root, "runs", f"r{n}")
        os.makedirs(run)
        with open(os.path.join(run, "meta.json"), "w") as f:
            json.dump({"status": "success", "usage": {"input": None, "output": None, "total": totals[n]}}, f)
        with open(os.path.join(root, loop_worker.run_file(receipt)), "w") as f:
            json.dump({"run_dir": os.path.relpath(run, root)}, f)
        return 0, False
    return launch, started


def test_each_run_is_counted_in_its_cycle_folder_and_a_run_without_a_count_is_not_zero():
    root = _instance()
    try:
        os.makedirs(os.path.join(root, "cyc", "apply"))
        launch, started = _launcher(root, [100, None, 50])
        for receipt in ("cyc/triage.receipt", "cyc/card-A.receipt", "cyc/apply/judge.receipt"):
            loop_worker.run_stage("judge", ["worker"], "p.md", receipt, launch, root)
        assert len(started) == 3
        assert loop_worker.spent(os.path.join(root, "cyc")) == {"runs": 3, "tokens": 150, "uncounted": 1,
                                                                "not_started": [], "ceiling": None}
        assert not os.path.exists(os.path.join(root, "cyc", "apply", loop_worker.TOKENS))
        assert loop_worker.spent_line(os.path.join(root, "cyc")) == "3 model runs, 150 tokens, 1 run without a count"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_no_new_stage_starts_once_the_cycle_reaches_its_token_ceiling():
    root = _instance({"token_ceiling": 120})
    try:
        os.makedirs(os.path.join(root, "cyc"))
        launch, started = _launcher(root, [100, 30, 999])
        for receipt in ("cyc/triage.receipt", "cyc/card-A.receipt", "cyc/card-B.receipt"):
            o = loop_worker.run_stage("card", ["worker"], "p.md", receipt, launch, root)
        assert len(started) == 2, started
        assert o["status"] == loop_worker.CEILING and o["rc"] is None and o["run"] is None, o
        assert o["unavailable"] == "the cycle's token ceiling is reached: 130 tokens of 120", o
        assert loop_worker.spent(os.path.join(root, "cyc"))["not_started"] == ["card (card-B.receipt)"]
        report = os.path.join(root, "cyc", "REPORT.md")
        loop_report.draw("cyc", root)
        loop_report.draw("cyc", root)   # a second drawing replaces the report, never adds to it
        text = Path(report).read_text()
        assert text.splitlines()[-2:] == [
            "Token ceiling 120 reached at 130 tokens; these stages did not start: card (card-B.receipt).",
            "Model use this cycle: 2 model runs, 130 tokens, 0 runs without a count."] and text.count("Model use") == 1, text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_status_shows_the_last_cycles_model_use():
    cfg = json.loads(json.dumps(W.CONFIG))
    with W.instance(cfg) as (root, env):
        W.write(root, "_private/papers/state.json", json.dumps({"last_cycle": "2026-11-25",
                                                                "last_dir": "_private/work/papers/2026-11-25-kit"}))
        W.write(root, "_private/work/papers/2026-11-25-kit/tokens.json",
                json.dumps({"runs": 4, "tokens": 9000, "uncounted": 1, "not_started": [], "ceiling": None}))
        r = W.run(root, env, "loop/loops.py", "status")
        lines = r.stdout.splitlines()
        i = next(n for n, line in enumerate(lines) if line.startswith("papers "))
        assert lines[i + 1] == "  last cycle 2026-11-25 pending; 4 model runs, 9000 tokens, 1 run without a count", r.stdout
        assert lines[i + 2] == "  report: _private/work/papers/2026-11-25-kit/REPORT.md", r.stdout
        assert not lines[i + 3].startswith("  stopped"), r.stdout
        # A cycle stopped at the ceiling is named in a line of its own, while it would stop again.
        cfg["loop"] = dict(cfg.get("loop") or {}, token_ceiling=8000)
        W.write(root, "instance/config.json", json.dumps(cfg))
        W.write(root, "_private/work/papers/2026-11-25-kit/tokens.json",
                json.dumps({"runs": 4, "tokens": 9000, "uncounted": 1, "not_started": ["propose (propose.receipt)"],
                            "ceiling": 8000}))
        lines = W.run(root, env, "loop/loops.py", "status").stdout.splitlines()
        i = next(n for n, line in enumerate(lines) if line.startswith("papers "))
        assert lines[i + 3] == ("  stopped at the token ceiling: 9000 tokens of 8000 (loop.token_ceiling); "
                                "not started: propose (propose.receipt)"), lines


# The papers cycle's worker stand-in with a token count in each run's record, and card workers whose
# cards name only some of their papers.
WORKER = Y.PAPERS_WORKER.replace('meta["result_bytes"] = len(body)',
                                 'meta["result_bytes"] = len(body)\n'
                                 'meta["usage"] = {"input": 900, "output": 100, "total": 1000}')
SWEEP = ("import sys\na=sys.argv; o=a[a.index('--out')+1]\n"
         "open(o,'w').write('arxiv_id\\tx\\ttitle\\n' + ''.join(f'2601.{i:05d}\\tx\\tT {i}\\n' for i in range(1, 13)))\n")
FETCH = ("import os,sys\nfor l in open(sys.argv[1]):\n    i=l.split('\\t')[0].strip()\n"
         "    i and open(os.path.join(sys.argv[2], i+'-x.txt'),'w').write('t')\n"
         "    i and open('fetch-calls.txt','a').write(i+'\\n')\n")


def _papers(td, ceiling=None):
    Y.papers_fixture(td)
    Y.write(Path(td, "tools/fresh_worker.py"), WORKER)
    Y.write(Path(td, "tools/loop/papers/sweep.py"), SWEEP)
    Y.write(Path(td, "tools/loop/papers/fetch_arxiv.py"), FETCH)
    cfg = json.loads(Path(td, "instance/config.json").read_text())
    if ceiling is not None:
        cfg["loop"]["token_ceiling"] = ceiling
    Path(td, "instance/config.json").write_text(json.dumps(cfg))
    # The triage worker scores twelve papers 3; each card names the first paper of its group only.
    rows = "".join(f"2601.{i:05d}\\t3\\tverify\\n" for i in range(1, 13))
    worker = Path(td, "tools/fresh_worker.py")
    worker.write_text(worker.read_text().replace('("2601.00001\\t3\\tverify\\n", "triage.tsv")', f'("{rows}", "triage.tsv")')
                      .replace('("card\\n" + CARDS', '("card paper:" + (open(f"{d}/group-{name[5:]}.list").read().split()[0] if name.startswith("card-") else "")'
                               ' + "\\n" + CARDS'))
    return Y.run("bash", "tools/loop/papers_cycle.sh", "--force", cwd=td, env=Y.isolated_env(td), timeout=120)


def test_a_papers_cycle_reads_eight_papers_records_what_its_cards_name_and_ends_its_report_with_the_count():
    with tempfile.TemporaryDirectory(prefix="tokens-papers.") as td:
        r = _papers(td)
        cycle = next(Path(td, "_private/work/papers").glob("*-kit"))
        fetched = Y.read_text(Path(td, "fetch-calls.txt")).split()
        assert r.returncode == 0 and len(fetched) == 8, (r.stdout + r.stderr, fetched)
        read = json.loads(Y.read_text(Path(td, "_private/papers/read.json")))["read"]
        named = sorted(Path(cycle, f"group-{g}.list").read_text().split()[0] for g in "ABC"
                       if Path(cycle, f"group-{g}.list").read_text().split())
        assert sorted(read) == named and set(read.values()) == {cycle.name[:10]}, (read, named)
        calls = Y.read_text(Path(td, "worker-calls.txt")).splitlines()
        last = Y.read_text(cycle / "REPORT.md").rstrip("\n").splitlines()[-1]
        assert last == f"Model use this cycle: {len(calls)} model runs, {1000 * len(calls)} tokens, 0 runs without a count.", last
        assert not Path(td, "_private/papers/LATEST.md").exists()   # status names the latest report instead
        assert r.stdout.splitlines()[-1] == f"papers {cycle.name[:10]} pending. Report: {cycle.relative_to(td)}/REPORT.md", r.stdout


def test_a_paper_counts_as_read_only_in_later_cycles():
    with tempfile.TemporaryDirectory(prefix="tokens-read.") as td:
        cycle = Path(td, "2026-11-25-kit")
        cycle.mkdir()
        (cycle / "candidates.tsv").write_text("arxiv_id\tx\ttitle\n" + "".join(f"2601.{i:05d}\tx\tT\n" for i in range(1, 11)))
        (cycle / "triage.tsv").write_text("".join(f"2601.{i:05d}\t3\tverify\n" for i in range(1, 11)))
        record = Path(td, "read.json")
        record.write_text(json.dumps({"read": {"2601.00001": "2026-11-18", "2601.00002v2": "2026-11-25",
                                               "2601.00003": "2026-12-02"}}))
        loop_papers.select_top(str(cycle), str(record))
        top = [line.split("\t")[0] for line in (cycle / "top.tsv").read_text().splitlines()]
        assert top == [f"2601.{i:05d}" for i in range(2, 10)], top


def test_a_ceiling_below_the_first_stage_starts_no_later_stage_and_the_report_says_which():
    with tempfile.TemporaryDirectory(prefix="tokens-ceiling.") as td:
        _papers(td, ceiling=500)
        cycle = next(Path(td, "_private/work/papers").glob("*-kit"))
        calls = Y.read_text(Path(td, "worker-calls.txt")).splitlines()
        assert calls == ["triage codex"], calls
        lines = Y.read_text(cycle / "REPORT.md").rstrip("\n").splitlines()
        assert lines[-2].startswith("Token ceiling 500 reached at 1000 tokens; these stages did not start: card (card-A.receipt)."), lines[-2:]
        assert lines[-1] == "Model use this cycle: 1 model run, 1000 tokens, 0 runs without a count.", lines[-1]


def _ceiling(td, value):
    cfg = json.loads(Path(td, "instance/config.json").read_text()) if Path(td, "instance/config.json").is_file() else {}
    cfg.setdefault("loop", {})["token_ceiling"] = value
    Y.write(Path(td, "instance/config.json"), json.dumps(cfg))


def test_a_papers_cycle_stopped_at_its_ceiling_is_not_failed_is_not_resumed_and_goes_on_once_it_is_raised():
    with tempfile.TemporaryDirectory(prefix="tokens-stopped.") as td:
        r = _papers(td, ceiling=500)
        cycle = next(Path(td, "_private/work/papers").glob("*-kit"))
        date = cycle.name[:10]
        state = json.loads(Y.read_text(Path(td, "_private/papers/state.json")))
        log = Y.read_text(Path(td, "_private/papers/cycle.log"))
        assert r.returncode == 0 and state["status"] == loop_worker.CEILING, (r.returncode, state, log[-400:])
        assert "FAILED" not in log and f"done cycle {date} ({loop_worker.CEILING})" in log, log[-400:]
        heal = {}
        found = loop_watch_checks.check_papers(td, datetime.date.fromisoformat(date), None, heal)
        assert len(found) == 1 and not heal, (found, heal)
        key, message = found[0]
        assert key == f"papers-token-ceiling-{date}" and message.startswith(
            f"papers cycle {date} stopped at the token ceiling: 1000 tokens of 500 (loop.token_ceiling); not started: card (card-"), found
        assert message.endswith("Nothing is retried. Raise loop.token_ceiling in the configuration, then "
                                f"`bash tools/loop/papers_cycle.sh --resume {date}` continues it"), message
        # A resume under the same ceiling starts no model run and leaves the cycle as it is.
        Y.run("bash", "tools/loop/papers_cycle.sh", "--resume", date, cwd=td, env=Y.isolated_env(td), timeout=120)
        assert Y.read_text(Path(td, "worker-calls.txt")).splitlines() == ["triage codex"]
        assert json.loads(Y.read_text(Path(td, "_private/papers/state.json")))["status"] == loop_worker.CEILING
        _ceiling(td, 100000)
        assert loop_watch_checks.check_papers(td, datetime.date.fromisoformat(date), None, {}) != found
        r = Y.run("bash", "tools/loop/papers_cycle.sh", "--resume", date, cwd=td, env=Y.isolated_env(td), timeout=120)
        calls = Y.read_text(Path(td, "worker-calls.txt")).splitlines()
        state = json.loads(Y.read_text(Path(td, "_private/papers/state.json")))
        assert r.returncode == 0 and state["status"] == "ok" and len(calls) > 1 and calls.count("triage codex") == 1, (state, calls)
        assert loop_worker.spent(str(cycle))["not_started"] == [] and "Token ceiling" not in Y.read_text(cycle / "REPORT.md")
        assert loop_watch_checks.check_papers(td, datetime.date.fromisoformat(date), None, {}) == []


def test_the_applier_leaves_a_cycle_stopped_at_its_ceiling_alone_until_the_ceiling_is_raised():
    root = T.fixture()
    try:
        cycle = root / T.CYCLE
        (cycle / loop_worker.TOKENS).write_text(json.dumps({"runs": 1, "tokens": 1000, "uncounted": 0,
                                                             "not_started": [], "ceiling": None}))
        T.set_config(root, token_ceiling=500)
        T.respond(root, judge=T.judge_text([], rejected=[{"id": "x", "title": "t", "reason": "weak grounds"}]))
        # The first run that meets the ceiling records it as the cycle's state, not as a failure.
        first = T.run_apply(root, T.CYCLE)
        assert first.returncode == 0 and T.outcome_of(root)["state"] == "token-ceiling", (first.stdout + first.stderr)
        assert T.outcome_of(root)["failure"] is None, T.outcome_of(root)
        second = T.run_apply(root, T.CYCLE)
        assert second.returncode == 0 and second.stdout.strip() == (
            f"skip: {T.CYCLE} stopped at the token ceiling: 1000 tokens of 500 (loop.token_ceiling); not started: "
            "judge (judge.receipt); raise loop.token_ceiling to continue it"), second.stdout + second.stderr
        assert T.worker_calls(root) == []
        T.set_config(root, token_ceiling=5000)
        third = T.run_apply(root, T.CYCLE)
        assert third.returncode == 0 and len(T.worker_calls(root)) == 1, third.stdout + third.stderr
        assert loop_worker.spent(str(cycle))["not_started"] == [] and T.outcome_of(root)["state"] == "done", T.outcome_of(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_card_and_proposal_prompts_ask_for_the_decided_sections_in_order():
    prompts = Path(TOOLS).parent / "system" / "loop" / "prompts"
    card = (prompts / "card.md").read_text()
    sections = ("How it actually works", "The numbers that carry the claim", "What the paper does not show",
                "Which file of this kit it speaks to", "The smallest change", "The cheapest check that could show the "
                "change does not help", "What goes wrong if the method is copied whole")
    at = [card.find(x) for x in sections]
    assert -1 not in at and at == sorted(at), dict(zip(sections, at))
    assert "only a paper whose arXiv id a card names counts as read" in card, card
    propose = (prompts / "propose.md").read_text()
    for field in ("files to change", "who is affected", "`test`", "`cost`", "`unknown`", "`context-bytes`",
                  "expected cost"):
        assert field in propose, field
    assert "canary" not in propose, propose


TESTS = [
    test_each_run_is_counted_in_its_cycle_folder_and_a_run_without_a_count_is_not_zero,
    test_no_new_stage_starts_once_the_cycle_reaches_its_token_ceiling,
    test_status_shows_the_last_cycles_model_use,
    test_a_papers_cycle_reads_eight_papers_records_what_its_cards_name_and_ends_its_report_with_the_count,
    test_a_paper_counts_as_read_only_in_later_cycles,
    test_a_ceiling_below_the_first_stage_starts_no_later_stage_and_the_report_says_which,
    test_a_papers_cycle_stopped_at_its_ceiling_is_not_failed_is_not_resumed_and_goes_on_once_it_is_raised,
    test_the_applier_leaves_a_cycle_stopped_at_its_ceiling_alone_until_the_ceiling_is_raised,
    test_the_card_and_proposal_prompts_ask_for_the_decided_sections_in_order,
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
    print(f"loop_tokens: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
