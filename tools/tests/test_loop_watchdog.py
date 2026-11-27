#!/usr/bin/env python3
"""Test loop_watchdog alert routing, episode ids, healing bookkeeping and probe handling in temporary roots."""
import contextlib
import datetime
import fcntl
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from testlib import add_loop_source, macos_only

HERE = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today()
# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/loop_watchdog.py",
    "tools/loop/lib/loop_watch_checks.py",
    "tools/loop/lib/loop_watch_heal.py",
    "tools/loop/lib/loop_watch_say.py",
    "tools/loop/lib/loop_macos_alert.py",
    "tools/loop/lib/loop_macos_process.py",
)

FAKE_TOOL = r'''
import json, os, sys
os.makedirs("_private", exist_ok=True)
open("_private/calls.log", "a").write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:], ensure_ascii=False) + "\n")
'''

# Minimal loop_state surface the watchdog reads; each cycle folder may carry stub.json.
STUB_STATE = r'''
import json, os
def _cfg(d):
    p = os.path.join(d, "stub.json")
    return json.load(open(p)) if os.path.exists(p) else {}
def apply_status(d):
    return _cfg(d).get("state", "done")
PENDING, DONE, FAILED, CEILING, STALE, CLOSED = "pending", "done", "failed", "token-ceiling", "stale", "closed"
def read_outcome(d):
    return _cfg(d) if os.path.exists(os.path.join(d, "stub.json")) else None
def needs_processing(d):
    return False
'''


def outcome(cyc, state):
    """An outcome record as the applier writes it, with only the fields loop_state reads."""
    (cyc / "apply").mkdir(parents=True, exist_ok=True)
    (cyc / "apply" / "outcome.json").write_text(json.dumps({"state": state, "input": {"name": "PROPOSALS.md", "sha256": None}}))


def day(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def copy_loop(tools):
    """Copy the loop's modules (tools/loop/loop_*.py, tools/loop/lib/loop_*.py), the applier and the engine modules the watchdog imports into a scratch tree's tools folder."""
    (tools / "lib").mkdir(exist_ok=True)
    (tools / "loop" / "lib").mkdir(parents=True, exist_ok=True)
    for src in sorted(HERE.glob("loop/lib/loop_*.py")) + sorted(HERE.glob("loop/loop_*.py")) + [HERE / "loop" / "papers_apply.py", HERE / "lib" / "paths.py",
                                                 HERE / "lib" / "safeio.py"]:
        shutil.copy2(src, tools / src.relative_to(HERE))


def fixture(real_triggers=True, real_state=False):
    root = Path(tempfile.mkdtemp(prefix="watchdog-fixture-"))
    t = root / "tools"
    t.mkdir()
    copy_loop(t)
    if real_triggers:
        shutil.copy2(HERE / "triggers.py", t / "triggers.py")
        # triggers.py reads its config, finds its store and saves it through these.
        for name in ("lib/config.py", "lib/hook_input.py", "lib/paths.py", "lib/safeio.py"):
            shutil.copy2(HERE / name, t / name)
    else:
        (t / "triggers.py").write_text(FAKE_TOOL)
    (t / "now.py").write_text(FAKE_TOOL)
    if not real_state:
        (t / "loop" / "lib" / "loop_state.py").write_text(STUB_STATE)
    (t / "loop" / "papers_cycle.sh").write_text("sleep 1\n")
    last = day(-1)
    cyc = root / "_private" / "work" / "papers" / f"{last}-kit"
    cyc.mkdir(parents=True)
    (cyc / "PROPOSALS.md").write_text("p" * 300)   # No DIGEST-EN.md: it has no reader (DR-079), so its absence is healthy.
    (root / "_private" / "papers").mkdir(parents=True)
    (root / "_private" / "papers" / "state.json").write_text(
        json.dumps({"last_cycle": last, "last_dir": f"_private/work/papers/{last}-kit", "status": "ok"}))
    # The test's own added source (tools/tests/testlib.py), so a health check covers more than papers.
    add_loop_source(str(root))
    (root / "_private" / "notes").mkdir(parents=True)
    (root / "_private" / "notes" / "state.json").write_text(json.dumps({"last_cycle": last, "status": "ok"}))
    return root, last, cyc


def fail_notes(root, last):
    """Leave the added source's cycle as a crashed run does."""
    (root / "_private" / "notes" / "state.json").write_text(json.dumps({"last_cycle": last, "status": "failed"}))


_N = [0]


def load(root):
    _N[0] += 1
    spec = importlib.util.spec_from_file_location(f"wd_{_N[0]}", root / "tools" / "loop" / "loop_watchdog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # check_extra runs the installation's own checks; the fixture has none to depend on.
    mod.check_extra = lambda: []
    return mod


def rows(root):
    p = root / "_private" / "triggers" / "triggers.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def calls(root):
    p = root / "_private" / "calls.log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


class Env:
    """Run the watchdog against the fixture without notifications or a foreign instance root."""

    def __init__(self, root, **extra):
        self.root, self.extra = root, extra

    def __enter__(self):
        self.saved = dict(os.environ)
        self.cwd = os.getcwd()
        os.environ.pop("MOTTORI_INSTANCE", None)
        os.environ.pop("MOTTORI_WATCHDOG_HEAL", None)
        os.environ["MOTTORI_NO_NOTIFY"] = "1"
        os.environ["MOTTORI_WATCHDOG_SPAWN_GRACE"] = "0.3"
        os.environ.update(self.extra)
        os.chdir(self.root)
        return self

    def __exit__(self, *a):
        os.chdir(self.cwd)
        os.environ.clear()
        os.environ.update(self.saved)
        shutil.rmtree(self.root, ignore_errors=True)


def test_watchdog_recurring_failure_new_trigger():
    root, *_ = fixture()
    with Env(root):
        wd = load(root)
        d1, d2, d3 = (TODAY - datetime.timedelta(days=n) for n in (2, 1, 0))
        wd.TODAY = d1
        wd.alert([("auth", "login lost")])
        wd.alert([("auth", "login lost")])
        assert len(rows(root)) == 1, rows(root)        # One trigger per failure episode.
        p = root / "_private" / "triggers" / "triggers.jsonl"
        r = rows(root)[0]
        r.update(fired=d1.isoformat())
        p.write_text(json.dumps(r) + "\n")
        wd.TODAY = d2
        wd.alert([])
        wd.TODAY = d3
        wd.alert([("auth", "login lost again")])
        opened = [x for x in rows(root) if not x.get("fired") and not x.get("retired")]
        assert len(opened) == 1 and len(rows(root)) == 2, rows(root)


def test_watchdog_names_a_cycle_stopped_at_its_token_ceiling_once_and_starts_no_repair():
    root, last, cyc = fixture()
    with Env(root):
        (cyc / "PROPOSALS.md").unlink()   # It stopped before its proposals.
        (cyc / "tokens.json").write_text(json.dumps({"runs": 1, "tokens": 1000, "uncounted": 0, "ceiling": 500,
                                                     "not_started": ["card (card-A.receipt)"]}))
        (root / "instance").mkdir()
        (root / "instance" / "config.json").write_text(json.dumps({"loop": {"token_ceiling": 500}}))
        (root / "_private" / "papers" / "state.json").write_text(json.dumps({
            "last_cycle": last, "last_dir": f"_private/work/papers/{last}-kit", "status": "token-ceiling",
            "fails": "no card output A; no cards", "failed_stages": ["cards"]}))
        wd = load(root)
        notes = []
        wd._notify = notes.append
        for _ in range(3):
            with patch.object(wd, "check_schedule", return_value=[]), patch.object(wd, "check_daily_heartbeat", return_value=[]):
                assert wd.run(["--no-auth"]) == 1
        key = f"papers-token-ceiling-{last}"
        said = [c for c in calls(root) if c[0] == "now.py"]
        assert len(said) == 1 and key in said[0][-1] and len(notes) == 1, (said, notes)
        assert [r["id"].startswith("loop-" + key) or key in r["id"] for r in rows(root)] == [True], rows(root)
        # No repair: no resume was started, reserved or counted.
        assert not wd.HEAL_CMDS and not list((root / "_private" / "loops").glob("heal-*-*")), list((root / "_private" / "loops").iterdir())
        report = (root / "_private" / "loops" / "WATCHDOG.md").read_text()
        assert "papers-cycle-failed" not in report and "papers-no-proposals" not in report and (
            f"stopped at the token ceiling: 1000 tokens of 500 (loop.token_ceiling); not started: card (card-A.receipt)") in report, report


def test_watchdog_says_a_failure_once_and_once_when_it_is_over():
    root, *_ = fixture()
    with Env(root):
        wd = load(root)
        notes = []
        wd._notify = notes.append

        def day_run(n, problems):
            wd.TODAY = TODAY + datetime.timedelta(days=n)
            with patch.object(wd, "check_schedule", return_value=problems), \
                 patch.object(wd, "check_daily_heartbeat", return_value=[]):
                wd.run(["--no-auth"])
            return [c for c in calls(root) if c[0] == "now.py"]
        for n in range(3):
            said = day_run(n, [("launchd-papers", "launchd job missing")])
        assert len(said) == 1 and len(notes) == 1 and len(rows(root)) == 1, (said, notes, rows(root))
        said = day_run(3, [])
        episodes = json.loads((root / "_private" / "loops" / "alert-episodes.json").read_text())
        assert len(said) == 2 and "launchd-papers" in said[-1][-1] and len(notes) == 1 and not episodes, said
        assert rows(root)[0]["fired"] and rows(root)[0]["outcome"] == "over", rows(root)
        assert day_run(4, []) == said                 # Nothing wrong: nothing more is said.
        # The watchdog's own failure is said once too, and once when a run completes again.
        wd.record_error("boom")
        wd.record_error("boom again")
        assert len(notes) == 2 and sum("watchdog-error" in r["id"] for r in rows(root)) == 1, (notes, rows(root))
        said = day_run(5, [])
        episodes = json.loads((root / "_private" / "loops" / "alert-episodes.json").read_text())
        ended = [r for r in rows(root) if "watchdog-error" in r["id"]]
        assert len(said) == 3 and "watchdog-error" not in episodes and ended[0]["outcome"] == "over", (said, ended)


def test_watchdog_running_cycle_not_flagged():
    root, last, cyc = fixture(real_triggers=False)
    with Env(root):
        (cyc / "PROPOSALS.md").unlink()
        st = root / "_private" / "papers" / "state.json"
        st.write_text(json.dumps({"last_cycle": last, "last_dir": f"_private/work/papers/{last}-kit",
                                  "status": "running"}))
        wd = load(root)
        lock = root / "_private" / "papers" / "cycle.lock"
        with open(lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            keys = [k for k, _ in wd.check_papers(None)]
            assert "papers-no-proposals" not in keys, keys
            assert not wd.HEAL_CMDS, wd.HEAL_CMDS
        keys = [k for k, _ in wd.check_papers(None)]
        assert "papers-cycle-failed" in keys, keys


def test_watchdog_abandoned_is_not_alerted():
    root, last, cyc = fixture(real_triggers=False)
    with Env(root):
        (cyc / "APPLY.md").write_text("# a\n")
        (cyc / "stub.json").write_text(json.dumps({"state": "done", "counts": {"abandoned": 1}}))
        wd = load(root)
        out = io.StringIO()
        with patch.object(wd, "check_schedule", return_value=[]), contextlib.redirect_stdout(out):
            rc = wd.run(["--no-auth", "--daily"])
        # An abandoned change is no problem, and with no problem the health check says nothing.
        assert rc == 0 and out.getvalue() == "" and not (root / "_private" / "loops" / "WATCHDOG.md").exists(), out.getvalue()
        assert not [c for c in calls(root) if c[0] in ("triggers.py", "now.py")], calls(root)


def test_watchdog_reads_cycle_state_from_loop_state_alone():
    # The watchdog reads cycles through tools/loop/lib/loop_state.py; the applier need not be there or load.
    root, last, cyc = fixture(real_triggers=False)
    with Env(root):
        (root / "tools" / "loop" / "papers_apply.py").unlink()
        (cyc / "APPLY.md").write_text("# a\n")
        (cyc / "stub.json").write_text(json.dumps({"state": "done", "counts": {"saved": 1}}))
        wd = load(root)
        with patch.object(wd, "check_schedule", return_value=[]):
            rc = wd.run(["--no-auth", "--daily"])
        assert rc == 0 and not (root / "_private" / "loops" / "WATCHDOG.md").exists()


def test_watchdog_after_an_abandoned_bundle_starts_nothing_and_ends_an_old_alert_once():
    # A cycle whose bundle used up its attempts completed; an alert left open from before is over.
    root, last, cyc = fixture(real_triggers=False, real_state=True)
    with Env(root):
        wd = load(root)
        outcome(cyc, "done")
        (cyc / "apply/state.json").write_text(json.dumps({"bundles": {"a": {"outcome": "abandoned", "spec": "x", "attempts": []}}}))
        loops = root / "_private" / "loops"
        loops.mkdir(parents=True)
        (loops / "alert-episodes.json").write_text(json.dumps({"papers-cycle-failed": day(-10)}))
        for n in range(3):
            wd = load(root)
            with patch.object(wd, "check_schedule", return_value=[]):
                assert wd.run(["--no-auth", "--daily"]) == 0, (loops / "WATCHDOG.md").read_text()
        said = [c for c in calls(root) if c[0] == "now.py"]
        assert len(said) == 1 and "papers-cycle-failed" in said[0][-1], said
        triggers = [c for c in calls(root) if c[0] == "triggers.py"]
        assert triggers == [["triggers.py", "fire", f"loop-papers-cycle-failed-{day(-10)}", "--outcome", "over"]], triggers
        assert not list(loops.glob("heal-*-*-*")) and json.loads((loops / "alert-episodes.json").read_text()) == {}


def test_watchdog_alerts_only_unrepairable():
    root, last, cyc = fixture()
    with Env(root):
        (cyc / "PROPOSALS.md").unlink()
        wd = load(root)
        with patch.object(wd, "check_schedule", return_value=[("launchd-papers", "launchd job missing")]):
            wd.run(["--no-auth", "--daily"])
        ids = [r["id"] for r in rows(root)]
        assert any(i.startswith("loop-launchd-papers") for i in ids), ids
        assert not any("papers-no-proposals" in i for i in ids), ids
        assert "papers-no-proposals" in (root / "_private" / "loops" / "WATCHDOG.md").read_text()
    root, last, cyc = fixture()
    with Env(root):
        (cyc / "PROPOSALS.md").unlink()
        loops = root / "_private" / "loops"
        loops.mkdir(parents=True)
        (loops / "heal-state.json").write_text(json.dumps({"papers-cycle": {"attempts": 2, "last": day(-7)}}))
        wd = load(root)
        with patch.object(wd, "check_schedule", return_value=[]):
            wd.run(["--no-auth", "--daily"])
        ids = [r["id"] for r in rows(root)]
        assert any("heal-blocked" in i for i in ids), ids
        assert not any("papers-no-proposals" in i for i in ids), ids


def test_watchdog_missing_state_message():
    root, last, cyc = fixture(real_triggers=False)
    with Env(root):
        # The English digest has no reader (DR-079); a missing or failed one must not ask for a rerun.
        (cyc / "digest.receipt").write_text("run: x\nstatus: failed\n")
        assert load(root).check_papers(None) == []
        (root / "_private" / "papers" / "state.json").write_text("{}")
        wd = load(root)
        probs = dict(wd.check_papers(None))
        assert "None" not in probs["papers-stale"], probs
        # A source that never ran here and is not scheduled was never turned on: nothing to report.
        (root / "_private" / "papers" / "state.json").unlink()
        assert load(root).check_papers(None) == []


def test_watchdog_bad_heal_state():
    root, *_ = fixture(real_triggers=False)
    with Env(root):
        wd = load(root)
        loops = root / "_private" / "loops"
        loops.mkdir(parents=True)
        wd.HEAL_CMDS["x"] = [sys.executable, "-c", "pass"]
        wd.HEAL_CMDS["y"] = [sys.executable, "-c", "pass"]
        (loops / "heal-state.json").write_text(json.dumps({"x": [1], "y": {"attempts": "lots", "last": 3}}))
        lines = wd.heal([("x", "m"), ("y", "m")], mode="run")
        hs = json.loads((loops / "heal-state.json").read_text())
        assert len(lines) == 2 and all(hs[k] == {"attempts": 1, "last": TODAY.isoformat()} for k in "xy"), (lines, hs)
        assert all((loops / f"heal-{k}-{TODAY}").is_file() for k in "xy"), lines


def test_watchdog_alert_timeout():
    root, *_ = fixture(real_triggers=False)
    with Env(root):
        (root / "tools" / "triggers.py").write_text("import time\ntime.sleep(5)\n")
        wd = load(root)
        wd.DELIVERY_TIMEOUT = 1
        t0 = time.monotonic()
        errors = wd.alert([("auth", "m")])
        assert time.monotonic() - t0 < 4, "alert waited for a stuck trigger store"
        assert any("auth" in e for e in errors), errors


@macos_only("the notification an alert shows")
def test_watchdog_auth_login_loss_alerts_and_probe_failure_retries():
    # The real probe subprocess path, through a fixture claude_auth.py.
    root, *_ = fixture()
    with Env(root):
        auth = root / "tools" / "claude_auth.py"
        wd = load(root)
        auth.write_text("raise SystemExit(0)\n")
        assert wd.check_auth() == []
        auth.write_text("print('Headless Claude authentication failed.')\nraise SystemExit(1)\n")
        (key, msg), = wd.check_auth()
        assert key == "auth" and "Headless Claude authentication failed." in msg and wd._heal_command(key) is None, msg

        def run(*args):
            with patch.object(wd, "check_schedule", return_value=[]):
                wd.run(list(args))
            return [r["id"] for r in rows(root)]
        assert run("--daily") == [f"loop-auth-{TODAY}"]   # A lost login alerts at once.
        auth.write_text("print('Authentication probe exited with status 1.')\nraise SystemExit(2)\n")
        run("--daily")
        # A failed probe is retried, not alerted; the lost-login episode ends.
        assert not any("auth-probe" in " ".join(c) for c in calls(root) if c[0] == "now.py"), calls(root)
        text = (root / "_private" / "loops" / "WATCHDOG.md").read_text()
        assert "[auth-probe]" in text and "status 1" in text and "[auth]" not in text, text
        state = root / "_private" / "loops" / "heal-state.json"
        run("--no-auth")
        hs = json.loads(state.read_text())
        assert hs["auth-probe"]["attempts"] == 1, hs              # A run without the probe keeps the count.
        state.write_text(json.dumps({"auth-probe": {"attempts": 2, "last": day(-7)}}))
        wd.TODAY += datetime.timedelta(days=1)
        ids = run("--daily")
        assert any(i.startswith("loop-heal-blocked-auth-probe") for i in ids), ids   # The third failed attempt alerts.


def test_watchdog_episode_kept_across_unchecked_runs():
    root, *_ = fixture()
    with Env(root):
        wd = load(root)
        for n, (args, auth) in enumerate([(["--daily"], True), (["--no-auth"], False), (["--daily"], True)]):
            wd.TODAY = TODAY + datetime.timedelta(days=n // 2)
            with patch.object(wd, "check_schedule", return_value=[]), \
                 patch.object(wd, "check_auth", return_value=[("auth", "login lost")] if auth else []):
                wd.run(args)
        ids = [r["id"] for r in rows(root) if "auth" in r["id"]]
        assert ids == [f"loop-auth-{TODAY}"], ids     # A --no-auth run does not end the auth episode.


def test_watchdog_heal_crash_still_alerts():
    root, last, cyc = fixture()
    with Env(root):
        (cyc / "PROPOSALS.md").unlink()
        (root / "_private" / "loops" / "heal-state.json").mkdir(parents=True)
        wd = load(root)
        with patch.object(wd, "check_schedule", return_value=[("launchd-papers", "launchd job missing")]):
            rc = wd.main(["--no-auth", "--daily"])
        ids = [r["id"] for r in rows(root)]
        assert rc == 1, rc
        assert any(i.startswith("loop-launchd-papers") for i in ids), ids
        assert any(i.startswith("loop-papers-no-proposals") for i in ids), ids   # The crashed heal marked nothing as handled.
        assert any(i.startswith("loop-heal-error") for i in ids), ids
        assert "launchd-papers" in (root / "_private" / "loops" / "WATCHDOG.md").read_text()


def test_watchdog_episode_save_failure_still_alerts():
    root, *_ = fixture()
    with Env(root):
        (root / "_private" / "loops" / "alert-episodes.json").mkdir(parents=True)
        wd = load(root)
        with patch.object(wd, "check_schedule", return_value=[("launchd-papers", "launchd job missing")]):
            rc = wd.main(["--no-auth", "--daily"])
        ids = [r["id"] for r in rows(root)]
        assert rc == 1, rc
        assert f"loop-launchd-papers-{TODAY}" in ids, ids
        assert "IsADirectoryError" in (root / "_private" / "loops" / "WATCHDOG.md").read_text()


def test_watchdog_leaves_cycles_judged_before_the_outcome_record_alone():
    # Folders with an APPLY.md of the old form and no outcome record are closed: no alert, no repair,
    # not counted. A folder whose material was never judged is still reported.
    root, last, cyc = fixture(real_triggers=False, real_state=True)
    with Env(root):
        papers = root / "_private" / "work" / "papers"
        for n, (status, hold) in enumerate((("done", None), ("held (a: switch)", "switch"), ("failed (stage: judge, reason: x)", None)), 2):
            old = papers / f"{day(-n)}-kit"
            (old / "apply").mkdir(parents=True)
            (old / "PROPOSALS.md").write_text("p" * 300)
            (old / "APPLY.md").write_text(f"# a\n\nStatus: {status}\n\n<!-- apply-end -->\n")
            (old / "apply" / "state.json").write_text(json.dumps({"bundles": {"a": {"hold": hold, "result": "held: x"}}}))
        loops = root / "_private" / "loops"
        loops.mkdir(parents=True)
        outcome(cyc, "done")
        for _ in range(3):
            wd = load(root)
            with patch.object(wd, "check_schedule", return_value=[]):
                assert wd.run(["--no-auth", "--daily"]) == 0, (loops / "WATCHDOG.md").read_text()
            assert not wd.HEAL_CMDS, wd.HEAL_CMDS
        ls = wd._load_state_reader()
        assert all(ls.apply_status(str(papers / f"{day(-n)}-kit")) == "closed" for n in (2, 3, 4))
        assert not [c for c in calls(root) if c[0] in ("triggers.py", "now.py")], calls(root)
        unjudged = papers / f"{day(-5)}-kit"
        unjudged.mkdir()
        (unjudged / "PROPOSALS.md").write_text("p" * 300)
        assert f"papers-unjudged-{day(-5)}" in [k for k, _ in wd.check_papers(ls)]


def test_watchdog_starts_nothing_for_a_beats_last_cycle_closed_before_the_outcome_record():
    # The beats' state files can name a cycle closed before outcome records existed: its old failure
    # sentence and its old review heading are not read, so no repair starts and nothing is said.
    root, last, cyc = fixture(real_triggers=False, real_state=True)
    with Env(root):
        (cyc / "APPLY.md").write_text("# a\n\nState: broken\n")
        p = root / "_private/papers/state.json"
        s = json.loads(p.read_text())
        s.update(status="failed", fails="card worker B rc=1; judging and applying failed rc=1")
        p.write_text(json.dumps(s, ensure_ascii=False))
        wd = load(root)
        ls = wd._load_state_reader()
        keys = [k for k, _ in wd.check_papers(ls)]
        assert "papers-cycle-failed" not in keys and not wd.HEAL_CMDS, keys


def test_watchdog_multi_cycle_atomic_heal_and_backoff():
    root, last, cyc = fixture(real_triggers=False, real_state=True)
    with Env(root, MOTTORI_WATCHDOG_SPAWN_GRACE="1"):
        fail_notes(root, last)
        wd = load(root)
        ls = wd._load_state_reader()
        old = day(-9)
        ocyc = root / "_private" / "work" / "papers" / f"{old}-kit"
        ocyc.mkdir(parents=True)
        (ocyc / "PROPOSALS.md").write_text("p" * 300)
        outcome(ocyc, "failed")
        outcome(cyc, "done")
        (cyc / "apply" / "outcome.json").write_text("x" * 150)      # A malformed outcome record is incomplete.
        probs = wd.check_papers(ls) + wd.check_added(ls)
        keys = [k for k, _ in probs]
        assert f"papers-unjudged-{old}" in keys and f"papers-unjudged-{last}" in keys, keys   # Inspect earlier cycles too.
        assert "notes-failed" in keys, keys
        assert "--backlog" in wd.HEAL_CMDS[f"papers-unjudged-{old}"]
        spec = importlib.util.spec_from_file_location("applier_for_watchdog_test", root / "tools" / "loop" / "papers_apply.py")
        applier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(applier)
        assert f"_private/work/papers/{old}-kit" in applier.backlog_dirs(str(root))   # Backlog recovery must select the pending cycle.
        lines = wd.heal(probs, mode="record")
        assert len(lines) == 2 and not list((root / "_private" / "loops").glob("heal-*-*-*")), lines  # Recording a result does not reserve a recovery attempt.
        ok_key, dead_key = "t-ok", "t-dead"
        wd.HEAL_CMDS[ok_key] = [sys.executable, "-c", "import time; time.sleep(3)"]
        wd.HEAL_CMDS[dead_key] = [sys.executable, "-c", "import sys; sys.exit(5)"]
        first = wd.heal([(ok_key, "m"), (dead_key, "m")], mode="run")
        assert any(dead_key in x and "rc=5" in x for x in first) and not any(ok_key in x and "rc=" in x for x in first), first
        # An instant death is a counted attempt: its marker stays.
        assert (root / "_private" / "loops" / f"heal-{dead_key}-{TODAY}").is_file(), first
        hs = json.loads((root / "_private" / "loops" / "heal-state.json").read_text())
        assert hs[dead_key]["attempts"] == 1 and hs[ok_key]["attempts"] == 1, hs
        kept = wd.heal([(dead_key, "m")], mode="run")
        assert any("backoff" in x for x in kept), kept                   # The retry follows backoff.
        # Two readers can see stale state; O_EXCL must allow only one reservation.
        (root / "_private" / "loops" / "heal-state.json").unlink()
        second = wd.heal([(ok_key, "m"), (dead_key, "m")], mode="run")
        # A second same-day reservation fails on the marker; the instant death kept its marker.
        assert all(any(f"heal-{k}-{TODAY}" in x for x in second) for k in (ok_key, dead_key)), second
        sp = root / "_private" / "loops" / "heal-state.json"
        hs = json.loads(sp.read_text()) if sp.exists() else {}
        assert dead_key not in hs and ok_key not in hs, hs   # Both reservations failed, so the deleted state gains neither key.
        hs = {dead_key: {"attempts": 3, "last": TODAY.isoformat()}}
        sp.write_text(json.dumps(hs))
        third = wd.heal([(dead_key, "m")], mode="run")
        assert any("backoff" in x for x in third), third
        assert wd.heal(probs, mode="off") == []
        # A group whose failure is gone loses its retry count.
        wd.heal([], mode="run")
        hs = json.loads(sp.read_text())
        assert dead_key not in hs, hs


def test_watchdog_unjudged_and_self_heal_record_mode():
    root, last, cyc = fixture(real_triggers=False, real_state=True)
    with Env(root):
        fail_notes(root, last)
        wd = load(root)
        ls = wd._load_state_reader()
        probs = wd.check_papers(ls) + wd.check_added(ls)
        keys = [k for k, _ in probs]
        assert f"papers-unjudged-{last}" in keys and "notes-failed" in keys, keys
        lines = wd.heal(probs, mode="record")
        assert len(lines) == 2, lines  # One application run, and one run of the added source's cycle.
        assert any("papers_apply.py --backlog --source papers" in x for x in lines), lines
        assert any("notes_cycle.sh --force" in x for x in lines), lines
        outcome(cyc, "failed")
        assert f"papers-unjudged-{last}" in [k for k, _ in wd.check_papers(ls)]
        outcome(cyc, "done")
        assert f"papers-unjudged-{last}" not in [k for k, _ in wd.check_papers(ls)]


def test_watchdog_stale_does_not_hide_detail_and_future_dates_flagged():
    root, last, cyc = fixture(real_triggers=False)
    with Env(root):
        (root / "_private" / "papers" / "state.json").write_text(
            json.dumps({"last_cycle": day(3), "last_dir": f"_private/work/papers/{day(3)}-kit", "status": "ok"}))
        fail_notes(root, day(-9))
        wd = load(root)
        keys = [k for k, _ in wd.check_papers(None) + wd.check_added(None)]
        assert "papers-future" in keys and "notes-failed" in keys, keys
        assert wd._heal_command("notes-failed"), "an added source's failure must keep its repair command"
        assert "watchdog-daily-missing" in [k for k, _ in wd.check_daily_heartbeat()]


def test_an_installation_that_never_turned_the_loop_on_has_no_daily_check_to_miss():
    root, last, cyc = fixture(real_triggers=False)
    with Env(root):
        for source in ("papers", "notes"):
            (root / "_private" / source / "state.json").unlink()
        wd = load(root)
        with patch.object(wd.checks.loop_platform, "supported", return_value=False):
            assert wd.check_daily_heartbeat() == [], "a loop that was never on has no daily run"
            # Once a daily run has completed, a stale one is reported whatever else is true.
            (root / "_private" / "loops").mkdir(parents=True, exist_ok=True)
            (root / "_private" / "loops" / "watchdog-daily.json").write_text(json.dumps({"last": day(-9)}))
            assert "watchdog-daily-missing" in [k for k, _ in wd.check_daily_heartbeat()]


def test_watchdog_abandonment_does_not_reenter_via_cycle_failed_alias():
    root, last, cyc = fixture(real_triggers=False, real_state=True)
    with Env(root):
        wd = load(root)
        ls = wd._load_state_reader()
        outcome(cyc, "done")
        (cyc / "apply/state.json").write_text(json.dumps({"bundles": {"a": {"outcome": "abandoned", "spec": "x", "attempts": []}}}))
        p = root / "_private/papers/state.json"
        s = json.loads(p.read_text()); s.update(status="failed", fails="apply failed", failed_stages=["apply"]); p.write_text(json.dumps(s))
        probs = wd.check_papers(ls)
        assert "papers-cycle-failed" not in [key for key, _ in probs], probs
        assert not any("abandoned" in key for key, _ in probs), probs   # The cycle's REPORT.md says it.
        assert all("abandoned" not in key for key in wd.HEAL_CMDS)
        s["failed_stages"].append("cards"); p.write_text(json.dumps(s))
        probs = wd.check_papers(ls)
        assert "papers-cycle-failed" in [key for key, _ in probs], probs


def test_watchdog_help_unknown_and_dry_have_no_operational_effects():
    root, *_ = fixture(real_triggers=False)
    with Env(root):
        wd = load(root)
        with patch.object(wd, "run", side_effect=AssertionError("operational run")):
            for args, code in ((["--help"], 0), (["--unknown-option"], 2)):
                try:
                    wd.main(args)
                except SystemExit as e:
                    assert e.code == code
                else:
                    raise AssertionError("argparse did not exit")

        def files():
            # The whole fixture, not only _private: a dry run must write nowhere.
            return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts}
        before = files()
        with patch.object(wd, "check_auth", side_effect=AssertionError("auth")), \
             patch.object(wd, "alert", side_effect=AssertionError("alert")), \
             patch.object(wd, "heal", side_effect=AssertionError("heal")), \
             patch.object(wd, "record_error", side_effect=AssertionError("error write")), \
             patch.object(wd, "check_schedule", return_value=[]):
            wd.main(["--dry", "--daily"])
        assert before == files(), "--dry changed operational files"


def test_watchdog_crash_is_recorded_not_swallowed():
    root, *_ = fixture(real_triggers=False)
    with Env(root):
        wd = load(root)

        def boom(args):
            raise RuntimeError("watchdog broke")
        wd.run = boom
        assert wd.main([]) == 3
        assert "watchdog broke" in (root / "_private" / "loops" / "WATCHDOG-ERROR.md").read_text()


TESTS = [
    test_watchdog_recurring_failure_new_trigger,
    test_watchdog_says_a_failure_once_and_once_when_it_is_over,
    test_watchdog_names_a_cycle_stopped_at_its_token_ceiling_once_and_starts_no_repair,
    test_watchdog_running_cycle_not_flagged,
    test_watchdog_abandoned_is_not_alerted,
    test_watchdog_reads_cycle_state_from_loop_state_alone,
    test_watchdog_after_an_abandoned_bundle_starts_nothing_and_ends_an_old_alert_once,
    test_watchdog_leaves_cycles_judged_before_the_outcome_record_alone,
    test_watchdog_alerts_only_unrepairable,
    test_watchdog_missing_state_message,
    test_watchdog_bad_heal_state,
    test_watchdog_alert_timeout,
    test_watchdog_auth_login_loss_alerts_and_probe_failure_retries,
    test_watchdog_episode_kept_across_unchecked_runs,
    test_watchdog_heal_crash_still_alerts,
    test_watchdog_episode_save_failure_still_alerts,
    test_watchdog_starts_nothing_for_a_beats_last_cycle_closed_before_the_outcome_record,
    test_watchdog_multi_cycle_atomic_heal_and_backoff,
    test_watchdog_unjudged_and_self_heal_record_mode,
    test_watchdog_stale_does_not_hide_detail_and_future_dates_flagged,
    test_an_installation_that_never_turned_the_loop_on_has_no_daily_check_to_miss,
    test_watchdog_abandonment_does_not_reenter_via_cycle_failed_alias,
    test_watchdog_help_unknown_and_dry_have_no_operational_effects,
    test_watchdog_crash_is_recorded_not_swallowed,
]


def main():
    # A test function this list does not run would pass unseen, so it fails the file.
    failed = sorted(n for n, f in globals().items() if n.startswith("test_") and callable(f) and f not in TESTS)
    for name in failed:
        print(f"✗ {name}: not in TESTS")
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"loop_watchdog: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
