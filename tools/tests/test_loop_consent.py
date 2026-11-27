#!/usr/bin/env python3
"""Consent says what is true and is checked where it matters: `on loop` says what the chosen sources
send and nothing about the others, choosing again leaves exactly the chosen sources, a cycle checks its
own allowance before anything leaves, a papers-only cycle reads no other source's report, and the papers
the fetcher names come only from the sweep. The second source is the test's own added one (testlib.py).

Every case runs in a scratch tree with stand-ins for launchctl, the sweep, the fetch and the workers;
nothing reaches the network or a model program."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_papers  # noqa: E402
from testlib import add_loop_source, macos_only, skip_unless, terminal_opens  # noqa: E402
import test_loop_cycles as Y  # noqa: E402
import test_loop_way_in as W  # noqa: E402
import test_papers_apply as T  # noqa: E402

# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/options.py",
    "tools/loop/lib/loop_sending.py",
    "tools/loop/lib/loop_papers.py",
)
NOTES = "_private/notes/"
PAPERS = "_private/work/papers/"
# The end of the question that asks which sources may send (tools/options.py LOOP_ASK).
W_LOOP_ASK_END = "[n]o? [n]"


def allowing(*prefixes, **block):
    cfg = json.loads(json.dumps(W.CONFIG))
    cfg["egress"]["model_send"]["allow_prefixes"] = list(prefixes)
    if block:
        cfg["loop"] = block
    return cfg


@macos_only(W.MACOS)
def test_on_loop_says_what_the_chosen_sources_send():
    with W.instance() as (root, env):
        r = W.run(root, env, "options.py", "on", "loop", "sources=notes")
        out = r.stdout
        assert r.returncode == 1 and out.startswith("The improvement loop (notes only). What leaves"), out
        assert "  - notes: every file in notes/ goes to the model runtime you use." in out, out
        assert "papers:" not in out, out
        assert "A notes cycle costs one model run." in out, out
        assert "can read any file your account can read" in out, out
        assert "The loop needs Claude Code or Codex installed, and neither is" in out, out
        r = W.run(root, env, "options.py", "on", "loop", "sources=papers")
        out = r.stdout
        assert ("  - papers: the search queries and the client name (improvement-loop-papers) go to arXiv (no contact "
                "address while loop.papers_contact is empty)") in out, out
        assert "While notes is off, it reads no notes review." in out and "notes:" not in out, out
        r = W.run(root, env, "options.py", "on", "loop")
        assert "notes: every file" in r.stdout and "Because notes is on too" in r.stdout, r.stdout
        r = W.run(root, env, "options.py")
        assert "from new arXiv papers (papers)" in r.stdout, r.stdout
        assert "checked by a reviewer that did not build it" in r.stdout, r.stdout
    with W.instance(allowing(NOTES, papers_contact="a@example.invalid")) as (root, env):
        r = W.run(root, env, "options.py", "on", "loop")
        assert "and your contact address (a@example.invalid) go to arXiv" in r.stdout, r.stdout
        r = W.run(root, env, "loop/loops.py", "status")
        assert r.stdout.splitlines()[1] == "  notes: reads notes/ only", r.stdout


@macos_only(W.MACOS)
def test_choosing_again_leaves_exactly_the_chosen_sources():
    with W.instance(allowing("_private/shared/")) as (root, env):
        for choice, allowed in (("all", ["_private/shared/", NOTES, PAPERS]), ("papers", ["_private/shared/", PAPERS]),
                                ("notes", ["_private/shared/", NOTES])):
            r = W.run(root, env, "options.py", "on", "loop", f"sources={choice}", "yes")
            assert r.returncode == 0, r.stdout + r.stderr
            assert W.config(root)["egress"]["model_send"]["allow_prefixes"] == allowed, (choice, W.config(root))


def _at_terminal(root, env, args, answers):
    """Run options.py with args on a pseudo-terminal, answering each question in turn; (exit, output)."""
    import pty
    import select
    import time
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, os.path.join(root, "tools", "options.py"), *args], cwd=root, env=env,
                         stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    out, pending, end = b"", list(answers), time.time() + 60
    try:
        while time.time() < end:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
                if pending and out.rstrip().endswith((b"]", b"?")):
                    os.write(master, pending.pop(0).encode() + b"\n")
            elif p.poll() is not None:
                break
        p.wait(timeout=10)
    finally:
        os.close(master)
    return p.returncode, out.decode("utf-8", "replace").replace("\r\n", "\n")


@macos_only(W.MACOS)
@skip_unless(terminal_opens, "a pseudo-terminal, which the loop's sandbox does not give")
def test_at_a_terminal_the_statement_of_the_sources_chosen_comes_before_the_yes():
    notes_line = "  - notes: every file in notes/"
    # notes and no both start with n, so the question offers each source by its number: 2 is papers.
    for answers, saved in ((["a", "n"], []), (["a", "y"], [NOTES, PAPERS]), (["2"], [PAPERS])):
        with W.instance() as (root, env):
            rc, out = _at_terminal(root, env, ["on", "loop", "sources=papers"], answers)
            assert W.config(root)["egress"]["model_send"]["allow_prefixes"] == saved, (answers, out)
            after = out.split(W_LOOP_ASK_END, 1)[-1]
            if answers[0] == "a":
                # The notes statement was not shown for sources=papers, so it comes after the choice.
                assert notes_line not in out.split(W_LOOP_ASK_END, 1)[0], out
                assert notes_line in after and after.index(notes_line) < after.index("[y/N]"), out
            else:
                assert notes_line not in out and "[y/N]" not in out, out
            assert rc == (0 if saved else 1), (answers, rc, out)


def _papers_cycle(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MOTTORI_"))}
    return subprocess.run(["bash", str(root / "tools" / "loop" / "papers_cycle.sh"), "--force"], cwd=root,
                          capture_output=True, text=True, timeout=180, env=env)


def _send(root, *prefixes):
    (root / "instance").mkdir(exist_ok=True)
    (root / "instance" / "config.json").write_text(json.dumps({"egress": {"model_send": {
        "deny_prefixes": ["_private/"], "allow_prefixes": list(prefixes)}}}))


def test_a_cycle_without_its_allowance_ends_before_anything_leaves():
    root = T.cycle_fixture()
    try:
        _send(root, NOTES)
        r = _papers_cycle(root)
        assert r.returncode == 1 and r.stdout.strip() == (
            "papers is not allowed to send to a model runtime. To allow it: python3 tools/options.py on loop"), r.stdout
        assert not list(root.glob("_private/work/papers/*-kit/candidates.tsv")) and not T.calls(root), T.calls(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# Takes back every allowance to send, as `options.py off loop` does while a cycle runs.
WITHDRAW = (T.FAKE_TOOL + "import json\np = 'instance/config.json'\ncfg = json.load(open(p))\n"
            "cfg['egress']['model_send']['allow_prefixes'] = []\njson.dump(cfg, open(p, 'w'))\n")


def test_the_papers_source_reads_its_allowance_again_before_it_contacts_arxiv():
    sweep = ("import sys\na=sys.argv; o=a[a.index('--out')+1]\nopen('_private/sweep-calls.txt','a').write('x')\n"
             "open(o,'w').write('arxiv_id\\tx\\ttitle\\n2601.00001\\tx\\tT one\\n')\n")
    fetch = "open('_private/fetch-calls.txt', 'a').write('x')\n"
    # Taken back while the backlog runs (before the sweep), or by the sweep itself (before the fetch).
    for where in ("tools/loop/papers_apply.py", "tools/loop/papers/sweep.py"):
        root = T.cycle_fixture()
        try:
            _send(root, PAPERS)
            (root / "tools" / "loop" / "papers" / "sweep.py").write_text(sweep)
            (root / "tools" / "loop" / "papers" / "fetch_arxiv.py").write_text(fetch)
            (root / where).write_text(WITHDRAW + (root / where).read_text())
            r = _papers_cycle(root)
            log = (root / "_private" / "papers" / "cycle.log").read_text()
            assert r.returncode == 1 and "papers is not allowed to send" in log, (where, r.stdout, log[-600:])
            assert not (root / "_private" / "fetch-calls.txt").exists(), (where, "the fetch contacted arXiv")
            swept = (root / "_private" / "sweep-calls.txt").exists()
            assert swept == (where.endswith("sweep.py")), (where, "the sweep contacted arXiv")
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_the_applier_without_its_sources_allowance_ends_before_any_model_call():
    root = T.fixture()
    try:
        cfg = json.loads((root / "instance" / "config.json").read_text())
        cfg["egress"]["model_send"]["allow_prefixes"] = [NOTES]
        (root / "instance" / "config.json").write_text(json.dumps(cfg))
        T.respond(root, judge=T.judge_text([T.bundle()]), impl_bump=T.EDIT_OK, review_bump=T.PASS)
        refusal = "papers is not allowed to send to a model runtime. To allow it: python3 tools/options.py on loop"
        for args in ((T.CYCLE,), (T.CYCLE, "--judge-only"), ("--backlog",), ("--backlog", "--source", "papers")):
            r = T.run_apply(root, *args)
            assert r.returncode == 1 and r.stdout.strip() == refusal, (args, r.stdout + r.stderr)
            assert not (root / "_fake" / "resp" / "calls.log").exists(), (args, "a worker started")
        assert not (root / T.CYCLE / "apply" / "state.json").exists(), "the cycle was processed"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_papers_only_cycle_reads_no_other_report_and_reaches_its_proposals():
    for prefixes, other in (((PAPERS,), False), ((NOTES, PAPERS), True)):
        root = T.cycle_fixture()
        add_loop_source(str(root))
        try:
            shutil.copy2(Path(TOOLS).parent / "system" / "loop" / "prompts" / "propose.md",
                         root / "system" / "loop" / "prompts" / "propose.md")
            _send(root, *prefixes)
            r = _papers_cycle(root)
            cycle = next(root.glob("_private/work/papers/*-kit"))
            prompt = (cycle / "prompts" / "propose.md").read_text()
            assert ("_private/notes" in prompt) == other, prompt
            assert ("No friction evidence available" in prompt) == (not other), prompt
            assert r.returncode == 0 and (cycle / "PROPOSALS.md").is_file(), r.stdout + r.stderr
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_a_failed_selection_starts_no_fetch_and_a_fetch_reads_only_this_selection():
    import datetime
    fetch = "import sys\nopen('fetch-calls.txt', 'a').write(open(sys.argv[1]).read())\n"
    # The selection fails after it wrote its list (its groups cannot be written) or before (an unreadable triage).
    for broken in ("groups", "triage", ""):
        with tempfile.TemporaryDirectory(prefix="consent-select.") as td:
            Y.papers_fixture(td)
            Y.write(Path(td, "tools/loop/papers/fetch_arxiv.py"), fetch)
            cycle = Path(td, "_private/work/papers", f"{datetime.date.today().isoformat()}-kit")
            cycle.mkdir(parents=True)
            Y.write(cycle / "top.tsv", "2601.99999\tan-earlier-selection\n")   # left by an earlier run
            if broken == "groups":
                (cycle / "group-A.list").mkdir()
            elif broken == "triage":
                (cycle / "triage.tsv").write_bytes(b"2601.00001\t3\t\xff\n")
            r = Y.run("bash", "tools/loop/papers_cycle.sh", "--force", cwd=td, env=Y.isolated_env(td), timeout=120)
            fetched = Y.read_text(Path(td, "fetch-calls.txt"))
            if broken:
                log = Y.read_text(Path(td, "_private/papers/cycle.log"))
                assert r.returncode == 1 and "top selection failed" in log, r.stdout + log[-400:]
                assert fetched == "" and not (cycle / "top.tsv").exists(), (broken, fetched)
                assert "card" not in Y.read_text(Path(td, "worker-calls.txt")), "a card worker started"
            else:
                assert fetched.split() == ["2601.00001", "t-one"], fetched


def test_paper_ids_come_only_from_the_sweep():
    with tempfile.TemporaryDirectory(prefix="consent-ids.") as td:
        Path(td, "candidates.tsv").write_text("arxiv_id\tpublished\ttitle\n2601.00001\tx\tOne\n2601.00003v2\tx\tThree\n"
                                              "../../x\tx\tEscape\n")
        Path(td, "triage.tsv").write_text("2601.00001\t3\tverify\tr\n2601.00002\t3\tverify\tnot listed\n"
                                          "../../x\t3\tverify\tlisted but no arXiv id\n2601.00003v2\t3\tmemory\tr\n"
                                          "#summary\ttotal 4\n")
        loop_papers.select_top(td)
        top = [line.split("\t")[0] for line in Path(td, "top.tsv").read_text().splitlines()]
        assert top == ["2601.00001", "2601.00003v2"], top
        lists = "".join(Path(td, f"group-{g}.list").read_text() for g in "ABC")
        assert sorted(lists.split()) == top, lists


TESTS = [
    test_on_loop_says_what_the_chosen_sources_send,
    test_choosing_again_leaves_exactly_the_chosen_sources,
    test_at_a_terminal_the_statement_of_the_sources_chosen_comes_before_the_yes,
    test_a_cycle_without_its_allowance_ends_before_anything_leaves,
    test_the_applier_without_its_sources_allowance_ends_before_any_model_call,
    test_the_papers_source_reads_its_allowance_again_before_it_contacts_arxiv,
    test_a_papers_only_cycle_reads_no_other_report_and_reaches_its_proposals,
    test_a_failed_selection_starts_no_fetch_and_a_fetch_reads_only_this_selection,
    test_paper_ids_come_only_from_the_sweep,
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
    print(f"loop_consent: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
