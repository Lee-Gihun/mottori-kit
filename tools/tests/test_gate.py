#!/usr/bin/env python3
"""Regression pins for tools/gate.py: baseline handling, the commit check and Stop behaviour."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from testlib import gate_stop_fixture, hook_event


HERE = Path(__file__).resolve().parent.parent
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]

import gate  # noqa: E402
import paths  # noqa: E402
import runlog  # noqa: E402


def _root(root):
    """Point the instance root at root for the duration."""
    return patch.dict(os.environ, {"MOTTORI_INSTANCE": str(root)})


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)


def _repo():
    """Return a committed scratch repository with one tracked README."""
    root = Path(tempfile.mkdtemp(prefix="gate-fixture-"))
    _git(root, "init", "-q")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "-c", "user.name=fixture", "-c", "user.email=f@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    return root


def _run_check(payload):
    """Run the Stop event's gate step through the dispatcher; the hook always exits 0."""
    return 0, hook_event("Stop", payload, "gate")


def test_now_check_block_repeats_the_checker_row():
    row = "state/NOW.md was rendered at 10:00; since then 2 lines. Run python3 tools/now.py render"
    script = f"print('now-input-newer\\t{row}'); print('#issues 1')"
    checked = gate._issues([sys.executable, "-c", script])
    cur = gate.Measurement({"now-check": checked.ids}, messages=checked.messages)
    reason, _advance = gate._verdict(cur, {"now-check": set()}, "ok")
    assert reason and row in reason, reason


def test_baseline_adopts_new_issue_and_keeps_previous_file():
    root = _repo()
    try:
        with gate_stop_fixture(gate, root / ".git"), _root(root):
            gate._save_baseline({"linkcheck": {"known"}, "now-check": set()})
            before = Path(gate.BASELINE).read_bytes()
            current = {"linkcheck": {"known", "new-one"}, "now-check": set()}
            gate.measure = lambda **_: gate.Measurement({k: set(v) for k, v in current.items()})
            # Uncommitted and staged edits do not hold the baseline back.
            (root / "README.md").write_text("unfinished\n", encoding="utf-8")
            (root / "other.md").write_text("staged\n", encoding="utf-8")
            _git(root, "add", "other.md")
            Path(gate.PENDING()).write_text("old reason", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                assert gate.cmd_baseline() == 0
            assert "new-one" in out.getvalue(), out.getvalue()
            issues, state = gate._load_baseline()
            assert state == "ok" and issues["linkcheck"] == {"known", "new-one"}, issues
            assert json.loads(Path(gate.BASELINE).read_text(encoding="utf-8")) == {
                "linkcheck": ["known", "new-one"], "now-check": []}
            assert Path(gate.BASELINE_PREV).read_bytes() == before
            assert not Path(gate.PENDING()).exists()
            Path(gate.EDITS()).write_text("1", encoding="utf-8")
            code, output = _run_check({})
            assert code == 0 and output == "", output
            # A corrupt file is replaced by an explicit baseline and kept as the previous copy.
            Path(gate.BASELINE).write_text("{ corrupt", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                assert gate.cmd_baseline() == 0
            assert Path(gate.BASELINE_PREV).read_text(encoding="utf-8") == "{ corrupt"
            assert gate._load_baseline()[1] == "ok"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_incomplete_installation_is_never_accepted_into_the_baseline():
    root = _repo()
    try:
        with gate_stop_fixture(gate, root / ".git"), _root(root):
            gate._save_baseline({"linkcheck": set(), "now-check": set()})
            row = "[NOW config missing] state inputs exist but instance/config.json does not"
            gate.measure = lambda **_: gate.Measurement(
                {"linkcheck": set(), "now-check": {"config-absent"}}, messages={"config-absent": row})
            Path(gate.EDITS()).write_text("1", encoding="utf-8")
            code, output = _run_check({})
            reason = json.loads(output)["reason"]
            # The block names the way back and does not offer the baseline as a way to accept it.
            assert "setup.sh --force" in reason and "If intentional" not in reason, reason
            before = Path(gate.BASELINE).read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                assert gate.cmd_baseline() == 1
            assert "installation is incomplete (config-absent)" in out.getvalue(), out.getvalue()
            assert Path(gate.BASELINE).read_bytes() == before, "the refused baseline was written"
            # A baseline file that already lists it, from before this rule, does not make it known.
            gate._save_baseline({"linkcheck": set(), "now-check": {"config-absent"}})
            Path(gate.EDITS()).write_text("1", encoding="utf-8")
            code, output = _run_check({"session_id": "s2"})
            assert json.loads(output)["decision"] == "block", output
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_previously_sealed_baseline_still_reads():
    root = Path(tempfile.mkdtemp(prefix="gate-legacy-"))
    try:
        path = root / "baseline.json"
        path.write_text(json.dumps({
            "schema_version": 3, "issues": {"linkcheck": ["a"]}, "adoptions": [],
            "payload_sha256": "0" * 64, "signature": "0" * 64}), encoding="utf-8")
        with patch.object(gate, "BASELINE", str(path)):
            assert gate._load_baseline() == ({"linkcheck": {"a"}}, "ok")
            path.write_text(json.dumps({"linkcheck": "ab"}), encoding="utf-8")
            assert gate._load_baseline() == ({}, "corrupt")
            path.write_text(json.dumps([1, 2]), encoding="utf-8")
            assert gate._load_baseline() == ({}, "corrupt")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_corrupt_baseline_block_names_path_and_command():
    reason = gate.BASELINE_CORRUPT.format(path="/x/baseline.json")
    assert "/x/baseline.json" in reason and "gate.py baseline" in reason, reason


def test_reentrant_stop_passes_on_gate_failure():
    root = Path(tempfile.mkdtemp(prefix="gate-reentrant-fail-"))
    try:
        with gate_stop_fixture(gate, root):
            gate._load_baseline = lambda: ({"linkcheck": set(), "now-check": set()}, "ok")

            def broken(**_):
                raise OSError("checker store unavailable")

            gate.measure = broken
            Path(gate.EDITS()).write_text("1", encoding="utf-8")
            code, output = _run_check({"stop_hook_active": True})
            assert code == 0 and output == "", output
            assert Path(gate.PENDING()).exists()
            code, output = _run_check({})
            assert code == 0 and json.loads(output)["decision"] == "block", output

            @contextlib.contextmanager
            def no_lock(timeout=150):
                yield False

            Path(gate.PENDING()).unlink()
            with patch.object(gate, "_lock", no_lock):
                code, output = _run_check({"stop_hook_active": True})
                assert code == 0 and output == "", output
                assert gate._pending() == {"": {"reason": gate.LOCK_BLOCK, "ids": []}}
                code, output = _run_check({})
                assert json.loads(output)["decision"] == "block", output
            with patch.object(gate, "_root_ok", lambda: False):
                code, output = _run_check({"stop_hook_active": True})
                assert code == 0 and output == "", output
                code, output = _run_check({})
                assert json.loads(output)["decision"] == "block", output
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _resume(payload):
    text = hook_event("UserPromptSubmit", payload, "resume")
    return json.loads(text)["hookSpecificOutput"]["additionalContext"] if text else ""


def test_a_session_is_judged_only_for_its_own_block():
    root = Path(tempfile.mkdtemp(prefix="gate-sessions-"))
    saves = []
    try:
        with gate_stop_fixture(gate, root):
            gate._load_baseline = lambda: ({"linkcheck": set(), "now-check": set()}, "ok")
            gate._save_baseline = saves.append
            current = {"linkcheck": {"L9"}, "now-check": set()}
            gate.measure = lambda **_: gate.Measurement({k: set(v) for k, v in current.items()})
            failed = "[gate] The previous turn did not pass verification."
            other = gate.RESUME_OTHER.format(reason="").strip()

            def stop(sid, edit=True):
                if edit:
                    Path(gate.EDITS()).write_text("1", encoding="utf-8")
                return _run_check({"session_id": sid} if sid else {})

            # A's block is named to B once as another session's, and to A as its previous turn.
            assert "L9" in json.loads(stop("A")[1])["reason"]
            note = _resume({"session_id": "B"})
            assert other in note and "L9" in note and failed not in note, note
            # A prompt with nothing new to record never waits for the lock another Stop may hold.
            with patch.object(gate, "_lock", None):
                assert _resume({"session_id": "B"}) == ""
                assert failed in _resume({"session_id": "A"})
            # B passes with or without edits while A's issue stands, and A's block stays.
            assert stop("B", edit=False) == (0, "")
            assert stop("B") == (0, "")
            assert failed in _resume({"session_id": "A"})
            # B's own new issue blocks B and is the only one named.
            current["linkcheck"] = {"L9", "L10"}
            reason = json.loads(stop("B")[1])["reason"]
            assert "L10" in reason and "L9" not in reason, reason
            assert gate._pending()["B"]["ids"] == ["linkcheck\tL10"], gate._pending()
            current["linkcheck"] = {"L9"}
            assert stop("B") == (0, "")
            # A's own Stop clears A's block once the issue is gone, whoever fixed it.
            current["linkcheck"] = set()
            assert stop("A", edit=False) == (0, "") and not Path(gate.PENDING()).exists()
            # A run without a session id judges and clears everything, as before.
            current["linkcheck"] = {"L9"}
            assert "L9" in json.loads(stop("A")[1])["reason"]
            assert "L9" in json.loads(stop(None)[1])["reason"]
            assert failed in _resume({})
            current["linkcheck"] = set()
            assert stop(None) == (0, "") and not Path(gate.PENDING()).exists()

            # Edits are kept per session: a broken link in a document only another session is
            # still editing is that session's; every other issue is judged as if alone.
            def edit(sid, rel):
                hook_event("PostToolUse", {"session_id": sid, "tool_input": {"file_path": str(root / rel)}},
                           "edited")

            def fresh(*issues, state=()):
                for marker in (gate.EDITS(), gate.PENDING()):
                    Path(marker).unlink(missing_ok=True)
                current["linkcheck"], current["now-check"] = set(issues), set(state)

            with _root(root):
                fresh("a.md -> x")
                edit("A", "a.md")
                assert _run_check({"session_id": "B"}) == (0, "")
                assert _resume({"session_id": "B"}) == ""
                assert "a.md -> x" in json.loads(_run_check({"session_id": "A"})[1])["reason"]
                # The blocking Stop drops A's edit entry; while B edits, A's block stays A's.
                edit("B", "a.md")
                assert "a.md -> x" in json.loads(_run_check({"session_id": "A"})[1])["reason"]
                assert _run_check({"session_id": "B"}) == (0, "")
                fresh("a.md -> x", "b.md -> y")
                edit("A", "a.md")
                edit("B", "b.md")
                reason = json.loads(_run_check({"session_id": "B"})[1])["reason"]
                assert "b.md -> y" in reason and "a.md" not in reason, reason
                # A document both edited, a file no session edited through an edit tool, and a
                # state-check issue block whichever session ends its turn first.
                for issues, state, edits in ((("s.md -> q",), (), "s.md"),
                                             (("c.md -> z",), (), "b.md"),
                                             ((), ("journal-corrupt:1",), "j.md")):
                    fresh(*issues, state=state)
                    edit("A", "a.md")
                    edit("A", edits)
                    edit("B", edits)
                    assert '"block"' in _run_check({"session_id": "B"})[1], issues or state
                # Another session's edit entry counts for one hour after its last edit. A edits
                # first, so the turn-end check, not the edit hook, decides the expiry.
                for minutes, blocked in ((59, False), (61, True)):
                    fresh("d.md -> w")
                    edit("DEAD", "d.md")
                    edit("A", "a.md")
                    marks = json.loads(Path(gate.EDITS()).read_text(encoding="utf-8"))
                    marks["DEAD"]["t"] -= minutes * 60 * 10**9
                    Path(gate.EDITS()).write_text(json.dumps(marks), encoding="utf-8")
                    assert ('"block"' in _run_check({"session_id": "A"})[1]) == blocked, minutes
                assert not Path(gate.EDITS()).exists()
                # An entry that expires while the Stop measures was exempted by it, so it stays
                # for a later Stop to judge instead of being dropped unjudged.
                fresh("d.md -> w")
                edit("DEAD", "d.md")
                edit("A", "a.md")
                marks = json.loads(Path(gate.EDITS()).read_text(encoding="utf-8"))
                marks["DEAD"]["t"] -= 59 * 60 * 10**9
                Path(gate.EDITS()).write_text(json.dumps(marks), encoding="utf-8")
                offset, real_ns, measured = [0], time.time_ns, gate.measure

                def slow_measure(**kw):
                    offset[0] += 120 * 10**9
                    return measured(**kw)

                with patch.object(gate.time, "time_ns", lambda: real_ns() + offset[0]), \
                        patch.object(gate, "measure", slow_measure):
                    assert _run_check({"session_id": "A"}) == (0, "")
                    assert "DEAD" in json.loads(Path(gate.EDITS()).read_text(encoding="utf-8"))
                    assert '"block"' in _run_check({"session_id": "A"})[1]
                assert not Path(gate.EDITS()).exists()
            assert saves == [], saves
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_unknown_subcommand_is_an_error():
    err = io.StringIO()
    with patch.object(sys, "argv", ["gate.py", "chek"]), contextlib.redirect_stderr(err), \
            contextlib.redirect_stdout(io.StringIO()) as out, \
            patch.object(gate, "cmd_status", lambda: print("STATUS") or 0):
        assert gate.main() == 2
    assert "check" in err.getvalue() and out.getvalue() == "", (err.getvalue(), out.getvalue())
    with patch.object(sys, "argv", ["gate.py"]), patch.object(gate, "cmd_status", lambda: 0):
        assert gate.main() == 0


def test_every_stop_measures():
    """A shell rename of an ignored file a tracked document links to changes no Git input, so
    a Stop with no marker must still measure (it once reused the last pass)."""
    root = Path(tempfile.mkdtemp(prefix="gate-every-stop-"))
    current = {"linkcheck": set(), "now-check": set()}
    try:
        with gate_stop_fixture(gate, root):
            gate._load_baseline = lambda: ({"linkcheck": set(), "now-check": set()}, "ok")
            gate._save_baseline = lambda cur: None
            gate.measure = lambda **_: gate.Measurement({k: set(v) for k, v in current.items()})
            assert _run_check({}) == (0, "")
            current["linkcheck"] = {"README.md -> notes/draft.md"}
            code, output = _run_check({})
            assert code == 0 and "notes/draft.md" in json.loads(output)["reason"], output
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_older_baseline_naming_retired_checkers_does_not_block_a_commit():
    """A baseline saved while evidencecheck and manifest ran lets a commit through; a checker
    removed without a new baseline still blocks; only runtime tools are compiled."""
    repo = _repo()
    state = repo / "state"
    state.mkdir(exist_ok=True)

    def baseline(**issues):
        Path(gate.BASELINE).write_text(json.dumps(issues), encoding="utf-8")

    def precommit():
        with contextlib.redirect_stderr(io.StringIO()) as err:
            return gate.cmd_precommit(), err.getvalue()

    try:
        with patch.multiple(gate, _root_ok=lambda: True, BASELINE=str(state / "b.json"),
                            _issues=lambda *a, **k: gate.Checked(set()),
                            measure=lambda **_: gate.Measurement({"linkcheck": set(), "now-check": set()})), \
                _root(repo), patch.object(runlog, "log_run", lambda *a, **k: None):
            baseline(linkcheck=[], **{"now-check": [], "evidencecheck": ["required|CHANGELOG.md|x"],
                                      "manifest": []})
            code, err = precommit()
            assert code == 0, err
            baseline(linkcheck=[], oldcheck=[], **{"now-check": []})
            code, err = precommit()
            assert code == 1 and "oldcheck" in err, err
            baseline(linkcheck=[], **{"now-check": []})
            # A broken contributor file is not code a running instance starts; a broken tool is.
            (repo / "tools" / "tests").mkdir(parents=True)
            (repo / "tools" / "tests" / "broken.py").write_text("def (:\n", encoding="utf-8")
            _git(repo, "add", "tools")
            code, err = precommit()
            assert code == 0, err
            (repo / "tools" / "broken.py").write_text("def (:\n", encoding="utf-8")
            _git(repo, "add", "tools")
            code, err = precommit()
            assert code == 1 and "tools/broken.py" in err and "tests/broken.py" not in err, err
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_dirty_does_not_wait_for_held_lock():
    root = Path(tempfile.mkdtemp(prefix="gate-dirty-lock-"))
    lock, dirty = root / "lock", root / "dirty"
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,sys,time; f=open(sys.argv[1],'w'); fcntl.flock(f, fcntl.LOCK_EX);"
         " print('held', flush=True); time.sleep(60)", str(lock)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with patch.multiple(gate, LOCK=lambda: str(lock), EDITS=lambda: str(dirty)), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            started = time.monotonic()
            hook_event("PostToolUse", {}, "edited")
            elapsed = time.monotonic() - started
        assert elapsed < 5, elapsed
        # Without the lock the list is left alone: a Stop that holds it would replace the write.
        assert not dirty.exists()
        notice = " " + gate.EDIT_NO_LOCK.format(path="-") + "\n"
        assert err.getvalue().endswith(notice), err.getvalue()
        assert runlog.hook_error_entries(err.getvalue()), err.getvalue()
        # A wall clock that jumps forward must not end the wait before the first try.
        wall = iter(range(0, 10**9, 10**6))
        with patch.multiple(gate, LOCK=lambda: str(root / "free-lock")), \
                patch.object(gate.time, "time", lambda: float(next(wall))), \
                gate._lock(timeout=5) as got:
            assert got
    finally:
        holder.kill()
        holder.wait()
        holder.stdout.close()
        shutil.rmtree(root, ignore_errors=True)


def test_documents_identity_takes_no_git_lock_and_has_a_timeout():
    """The identity read runs beside a concurrent commit, so it must neither take Git's index
    lock nor wait on Git for ever."""
    seen = []
    real_run = subprocess.run

    def spy(cmd, **kwargs):
        seen.append(kwargs)
        return real_run(cmd, **kwargs)

    with patch.object(gate.subprocess, "run", spy):
        gate._documents_identity()
    assert seen and all(kw.get("env", {}).get("GIT_OPTIONAL_LOCKS") == "0" for kw in seen), seen
    assert all(kw.get("timeout") for kw in seen), seen

    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    with patch.object(gate.subprocess, "run", slow):
        assert gate._documents_identity() is None


def test_markers_are_utf8_under_a_legacy_locale():
    root = Path(tempfile.mkdtemp(prefix="gate-locale-"))
    try:
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import gate; "
                "gate._mark(sys.argv[2], '\\uac8c\\uc774\\ud2b8'); "
                "assert gate._read(sys.argv[2]) == '\\uac8c\\uc774\\ud2b8'")
        env = dict(os.environ, LC_ALL="en_US.ISO8859-1", LANG="en_US.ISO8859-1", PYTHONUTF8="0")
        result = subprocess.run([sys.executable, "-c", code, str(HERE), str(root / "marker")],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-600:]
        assert (root / "marker").read_bytes().decode("utf-8") == "게이트"
        # A write that fails half way leaves the previous marker whole for a reader without the lock.
        with contextlib.suppress(UnicodeEncodeError):
            gate._mark(str(root / "marker"), "half\udcff")
        assert gate._read(str(root / "marker")) == "게이트"
        assert sorted(os.listdir(root)) == ["marker"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_only_stop_asks_now_check_to_repair():
    """A new day makes the NOW snapshot stale; only the Stop measurement may re-render it."""
    seen = []
    with patch.object(gate, "_issues",
                                          lambda cmd, **_: seen.append(list(cmd)) or gate.Checked(set())):
        gate.measure()
        plain = [cmd for cmd in seen if "now.py" in cmd[1]]
        seen.clear()
        gate.measure(repair=True)
        repaired = [cmd for cmd in seen if "now.py" in cmd[1]]
        others = [cmd for cmd in seen if "now.py" not in cmd[1]]
    assert plain and "--repair" not in plain[0], plain
    assert repaired and repaired[0][-1] == "--repair", repaired
    assert others and all("--repair" not in cmd for cmd in others), others
    assert all("--repair" not in cmd for _name, cmd in gate.CHECKS), "the shared command list changed"
    # linkcheck reports path-shaped code spans as advisory; a span counts only if the baseline
    # already holds it, so a new one neither blocks nor is saved.
    seen.clear()
    proposal = "proposal.md -> plans/next.md"

    def advisory_links(cmd, **_):
        seen.append(list(cmd))
        return gate.Checked(set(), frozenset({proposal}) if "--session" in cmd else frozenset())

    with patch.object(gate, "_issues", advisory_links):
        cur = gate.measure()
        assert proposal in cur.ids["linkcheck"], cur
        assert gate._verdict(cur, {"linkcheck": set(), "now-check": set()}, "ok")[0] is None
        # Fixing a link in the edit that adds a code span still tightens the baseline, and the
        # span is not saved with it, so the link breaking again blocks.
        fixed = "rat.md -> gone-L.md"
        reason, tighten = gate._verdict(cur, {"linkcheck": {fixed}, "now-check": set()}, "ok")
        assert reason is None and tighten, (reason, tighten)
        saved = gate._gated(cur, {"linkcheck": {fixed}})
        assert saved["linkcheck"] == set(), saved
        cur.ids["linkcheck"].add(fixed)
        assert gate._verdict(cur, saved, "ok")[0], saved
    links = [cmd for cmd in seen if "linkcheck.py" in cmd[1]]
    assert links and all("--session" in cmd for cmd in links), links
    root = Path(tempfile.mkdtemp(prefix="gate-stop-repair-"))
    try:
        calls = []
        with gate_stop_fixture(gate, root):
            gate._load_baseline = lambda: ({"linkcheck": set(), "now-check": set()}, "ok")
            gate.measure = lambda **kw: calls.append(kw) or gate.Measurement({"linkcheck": set(), "now-check": set()})
            assert _run_check({}) == (0, "")
        assert calls and calls[0].get("repair") is True, calls

        def spanned(*links):
            m = gate.Measurement({"linkcheck": {proposal, *links}, "now-check": set()},
                                 frozenset({proposal}))
            return lambda **_: m

        saved = []
        gone = "README.md -> gone.md"
        with gate_stop_fixture(gate, root), patch.object(gate, "_save_baseline", saved.append):
            # The Stop whose edit fixes a held link and adds a span saves neither.
            gate._load_baseline = lambda: ({"linkcheck": {fixed}, "now-check": set()}, "ok")
            gate.measure = spanned()
            assert _run_check({"session_id": "s1"}) == (0, "")
            assert saved and saved[-1]["linkcheck"] == set(), saved
            # A real new link blocks, and the block does not hold the span.
            gate.measure = spanned(gone)
            code, output = _run_check({"session_id": "s1"})
            assert code == 0 and gone in json.loads(output)["reason"], output
            assert gate._pending()["s1"]["ids"] == [f"linkcheck\t{gone}"], gate._pending()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_edited_markdown_is_link_checked_in_the_turn_that_edited_it():
    """Markdown a turn edited is link-checked even when Git ignores it, by that turn's Stop only."""
    root = Path(tempfile.mkdtemp(prefix="gate-edited-"))
    broken, lists = [True], []

    def issues(cmd, **_):
        if "--filelist" not in cmd:
            return gate.Checked(set())
        listed = Path(cmd[cmd.index("--filelist") + 1]).read_text(encoding="utf-8").split()
        lists.append(listed)
        return gate.Checked({f"{rel} -> gone.md" for rel in listed if broken[0]})

    def hook(command, payload):
        event, step = {gate.record_edit: ("PostToolUse", "edited"),
                       gate.cmd_check: ("Stop", "gate")}[command]
        return hook_event(event, payload, step)

    for rel in ("launch/plan.md", "_private/note.md", "notes.txt"):
        (root / rel).parent.mkdir(exist_ok=True)
        (root / rel).write_text("[x](gone.md)\n", encoding="utf-8")
    try:
        with patch.multiple(gate, EDITS=lambda: str(root / "dirty"),
                            PENDING=lambda: str(root / "pending"), LOCK=lambda: str(root / "lock"),
                            ESCALATED=lambda: str(root / "escalated"), _issues=issues,
                            _root_ok=lambda: True,
                            _load_baseline=lambda: ({"linkcheck": set(), "now-check": set()}, "ok"),
                            _save_baseline=lambda cur: None, create=True), \
                _root(root), patch.object(runlog, "log_run", lambda *a, **k: None):
            for rel in ("launch/plan.md", "_private/note.md", "notes.txt", "/elsewhere/x.md"):
                hook(gate.record_edit, {"tool_input": {"file_path": str(root / rel)}})
            blocked = hook(gate.cmd_check, {})
            assert lists == [["launch/plan.md"]], lists
            # A baseline never measures an untracked file, so the block must not offer it. The
            # folder was never adopted, so the block names the command that adopts one.
            assert json.loads(blocked)["reason"] == gate.NEW_ISSUES.format(
                detail="linkcheck: launch/plan.md -> gone.md", tail=gate.TAIL_EDITED_UNADOPTED), blocked
            # The block drops the list with the marker, so a later Stop does not judge the file
            # again unless a turn edits it again.
            assert not (root / "dirty").exists()
            assert hook(gate.cmd_check, {}) == "" and len(lists) == 1, lists
            hook(gate.record_edit, {"tool_input": {"file_path": str(root / "notes.txt")}})
            assert hook(gate.cmd_check, {}) == "" and len(lists) == 1, lists
            hook(gate.record_edit, {"tool_input": {"file_path": str(root / "launch/plan.md")}})
            assert "launch/plan.md -> gone.md" in hook(gate.cmd_check, {})
            broken[0] = False
            hook(gate.record_edit, {"tool_input": {"file_path": str(root / "launch/plan.md")}})
            assert hook(gate.cmd_check, {}) == "" and len(lists) == 3, lists
            # A session that edited nothing, judging a file a dead session left unchecked, is
            # not told that it edited the file.
            broken[0] = True
            dead = time.time_ns() - 2 * 3600 * 10**9
            Path(root / "dirty").write_text(json.dumps(
                {"DEAD": {"t": dead, "files": ["launch/plan.md"]}}), encoding="utf-8")
            assert json.loads(hook(gate.cmd_check, {"session_id": "B"}))["reason"] == gate.NEW_ISSUES.format(
                detail="linkcheck: launch/plan.md -> gone.md", tail=gate.TAIL_LEFT)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_turn_that_edited_a_frozen_path_stops_once():
    """Rule 1: an edit tool's change under a path in config.frozen stops that session's turn once."""
    import config as C
    root = Path(tempfile.mkdtemp(prefix="gate-frozen-"))
    (root / "instance").mkdir()
    cfg = {"schema_version": 4, "instance": {"name": "fixture"}, "tracks": [],
           "journal_visibility": {"public_tracks": None, "legacy_cutoff": None,
                                  "legacy_public_tracks": []},
           "frozen": ["evidence/", "archive/2025.md"]}
    (root / "instance" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def hook(command, payload):
        event, step = {gate.record_edit: ("PostToolUse", "edited"),
                       gate.cmd_check: ("Stop", "gate")}[command]
        return hook_event(event, payload, step)

    def edit(sid, rel):
        hook(gate.record_edit, {"session_id": sid, "tool_input": {"file_path": str(root / rel)}})

    try:
        with patch.multiple(gate, EDITS=lambda: str(root / "dirty"),
                            PENDING=lambda: str(root / "pending"), LOCK=lambda: str(root / "lock"),
                            ESCALATED=lambda: str(root / "escalated"),
                            _issues=lambda cmd, **_: gate.Checked(set()), _root_ok=lambda: True,
                            _load_baseline=lambda: ({"linkcheck": set(), "now-check": set()}, "ok"),
                            _save_baseline=lambda cur: None, create=True), \
                _root(root), patch.object(runlog, "log_run", lambda *a, **k: None):
            C.reload()
            assert C.frozen() == ["evidence", "archive/2025.md"], C.frozen()
            for rel in ("evidence/scan.pdf", "notes.md", "archive/2025.md", "evidence-old/a.md"):
                edit("A", rel)
            reason = json.loads(hook(gate.cmd_check, {"session_id": "A"}))["reason"]
            assert reason == gate.FROZEN_BLOCK.format(paths="archive/2025.md, evidence/scan.pdf"), reason
            # The Stop dropped the edits it judged: the next one passes unless the turn edits again.
            assert hook(gate.cmd_check, {"session_id": "A"}) == ""
            # Another session's frozen edit is that session's to answer.
            edit("B", "evidence/other.pdf")
            edit("A", "notes.md")
            assert hook(gate.cmd_check, {"session_id": "A"}) == ""
            assert "evidence/other.pdf" in hook(gate.cmd_check, {"session_id": "B"})
            for bad in (["../outside/"], ["./"], ["/abs/"], "evidence/"):
                try:
                    C.validate({**cfg, "frozen": bad})
                except ValueError as e:
                    assert "config.frozen" in str(e), e
                else:
                    raise AssertionError(f"frozen={bad!r} was accepted")
    finally:
        C.reload()
        shutil.rmtree(root, ignore_errors=True)


def test_waiting_items_stop_a_turn_once_and_then_only_wait():
    """checks.waiting: a set of state-check issues that wait for work outside the turns stops one turn,
    is shown as counts, and is repeated at each prompt as waiting, not as a failed turn."""
    import config as C
    root = Path(tempfile.mkdtemp(prefix="gate-waiting-"))
    (root / "instance").mkdir()
    cfg = {"schema_version": 4, "instance": {"name": "fixture"}, "tracks": [],
           "journal_visibility": {"public_tracks": None, "legacy_cutoff": None, "legacy_public_tracks": []},
           "checks": {"waiting": ["inbox:"]}}
    (root / "instance" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    state = {"now-check": {"inbox:Some Person.m4a", "inbox:b.m4a"}}
    recorded = []

    def issues(cmd, **_):
        return gate.Checked(set(state["now-check"]) if "now.py" in " ".join(map(str, cmd)) else set())

    def hook(command, payload):
        event, step = {gate.cmd_check: ("Stop", "gate"), gate.cmd_resume: ("UserPromptSubmit", "resume")}[command]
        return hook_event(event, payload, step)

    def resume(sid):
        out = hook(gate.cmd_resume, {"session_id": sid})
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    instance_hook = type("M", (), {"record": staticmethod(lambda kind, **kw: recorded.append(kind))})
    try:
        with patch.multiple(gate, EDITS=lambda: str(root / "dirty"), PENDING=lambda: str(root / "pending"),
                            LOCK=lambda: str(root / "lock"), ESCALATED=lambda: str(root / "escalated"),
                            _issues=issues, _root_ok=lambda: True,
                            _load_baseline=lambda: ({"linkcheck": set(), "now-check": set()}, "ok"),
                            _save_baseline=lambda cur: None, create=True), \
                _root(root), patch.object(runlog, "log_run", lambda *a, **k: None), \
                patch.dict(sys.modules, {"gate_instance": instance_hook}):
            C.reload()
            reason = json.loads(hook(gate.cmd_check, {"session_id": "A"}))["reason"]
            assert "inbox: 2 waiting" in reason and "Some Person" not in reason, reason
            assert gate.WAITING_ONCE in reason and (root / "escalated").exists(), reason
            failed = "[gate] The previous turn did not pass verification."
            context = resume("A")
            assert failed not in context and "inbox: 2 waiting" in context, context
            # The same set, and a part of it, never stops a turn again, in any session.
            assert hook(gate.cmd_check, {"session_id": "B"}) == ""
            state["now-check"] = {"inbox:b.m4a"}
            assert hook(gate.cmd_check, {"session_id": "A"}) == "" and "inbox: 1 waiting" in resume("A")
            # A new item makes a new set, which stops once more; a non-waiting issue always stops.
            state["now-check"] = {"inbox:b.m4a", "inbox:c.m4a"}
            assert "inbox: 2 waiting" in json.loads(hook(gate.cmd_check, {"session_id": "A"}))["reason"]
            state["now-check"] = {"inbox:b.m4a", "journal-corrupt:1"}
            assert "journal-corrupt:1" in json.loads(hook(gate.cmd_check, {"session_id": "A"}))["reason"]
            # Once nothing waits, the turn passes and the record of sets is cleared.
            state["now-check"] = set()
            assert hook(gate.cmd_check, {"session_id": "A"}) == "" and not (root / "escalated").exists()
            assert recorded[:2] == ["block", "waiting"] and recorded[-1] == "pass", recorded
            (root / "escalated").write_text('[["x"]]', encoding="utf-8")
            assert gate._escalated() == set()
    finally:
        C.reload()
        shutil.rmtree(root, ignore_errors=True)


def test_staged_checks_use_the_staged_linkcheck_without_git_pinning():
    """A commit hook's Git pinning must not reach the checkers of the extracted tree, and the
    staged copy of linkcheck, not the working copy, judges it with the live instance's config."""
    tree = Path(tempfile.mkdtemp(prefix="gate-staged-"))
    real_gitdir = paths.git_dir()
    try:
        (tree / "tools").mkdir(parents=True)
        probe = ("import os\nprint(f\"{os.path.basename(__file__)}:{'GIT_INDEX_FILE' in os.environ}:{'GIT_DIR' in os.environ}"
                 "\\t{os.environ.get('MOTTORI_INSTANCE')}\")\nprint('#issues 1')\n")
        for checker in ("linkcheck.py", "now.py"):
            (tree / "tools" / checker).write_text(probe, encoding="utf-8")
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(tree / "outer-index"),
                                     "GIT_DIR": str(tree / "outer.git")}), \
                contextlib.redirect_stderr(io.StringIO()):
            out = gate.measure(tree=str(tree))
            assert paths.git_dir() == real_gitdir
        for checker, script in (("linkcheck", "linkcheck.py"), ("now-check", "now.py")):
            assert out.ids[checker] == {script + ":False:False"}, (checker, out)
        assert out.messages["linkcheck.py:False:False"] == paths.instance_root()
    finally:
        shutil.rmtree(tree, ignore_errors=True)


TESTS = [
    test_older_baseline_naming_retired_checkers_does_not_block_a_commit,
    test_now_check_block_repeats_the_checker_row,
    test_baseline_adopts_new_issue_and_keeps_previous_file,
    test_an_incomplete_installation_is_never_accepted_into_the_baseline,
    test_previously_sealed_baseline_still_reads,
    test_corrupt_baseline_block_names_path_and_command,
    test_reentrant_stop_passes_on_gate_failure,
    test_a_session_is_judged_only_for_its_own_block,
    test_unknown_subcommand_is_an_error,
    test_every_stop_measures,
    test_staged_checks_use_the_staged_linkcheck_without_git_pinning,
    test_dirty_does_not_wait_for_held_lock,
    test_documents_identity_takes_no_git_lock_and_has_a_timeout,
    test_markers_are_utf8_under_a_legacy_locale,
    test_only_stop_asks_now_check_to_repair,
    test_edited_markdown_is_link_checked_in_the_turn_that_edited_it,
    test_a_turn_that_edited_a_frozen_path_stops_once,
    test_waiting_items_stop_a_turn_once_and_then_only_wait,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print("FAIL", test.__name__, type(error).__name__, str(error)[:300])
    print(f"gate tests: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
