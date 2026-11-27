#!/usr/bin/env python3
"""tools/tasks.py: the line about background work, reached through the dispatcher's steps.

Payloads have the shape Claude Code 2.1 sends to its hooks; every id and path is made up."""
import builtins
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

from testlib import hook_event


HERE = Path(__file__).resolve().parent.parent
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import tasks  # noqa: E402


class _Instance:
    """A scratch instance root with a Git directory and the runtime's task folders beside it."""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="tasks-"))
        (self.root / ".git").mkdir()
        (self.root / "instance").mkdir()
        self.runtime = self.root / "runtime"
        self.patches = [patch.object(tasks, "ROOT", str(self.root)),
                        patch.object(tasks, "_boot", lambda: 1000.0)]
        for p in self.patches:
            p.start()
        # A runner may itself be a probe; the scratch instance plays a real session's hook.
        os.environ.pop("MOTTORI_INTERNAL_RUN", None)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def session(self, sid):
        """(transcript path, scratchpad, task output folder) laid out as the runtime does."""
        base = self.runtime / "project"
        (base / sid / "scratchpad").mkdir(parents=True, exist_ok=True)
        (base / sid / "tasks").mkdir(exist_ok=True)
        transcript = base / f"{sid}.jsonl"
        transcript.write_text('{"type":"user"}\n', encoding="utf-8")
        return transcript, base / sid / "scratchpad", base / sid / "tasks"

    def stop(self, sid, tasks):
        transcript, scratch, _ = self.session(sid)
        payload = {"session_id": sid, "transcript_path": str(transcript), "cwd": str(self.root),
                   "scratchpad_dir": str(scratch), "prompt_id": "p-1", "hook_event_name": "Stop",
                   "stop_hook_active": False, "last_assistant_message": "started",
                   "background_tasks": tasks, "session_crons": []}
        return hook_event("Stop", payload, "tasks")

    def prompt(self, sid, prompt="how far is it?"):
        transcript, scratch, _ = self.session(sid)
        return _context(hook_event("UserPromptSubmit", {
            "session_id": sid, "transcript_path": str(transcript), "cwd": str(self.root),
            "scratchpad_dir": str(scratch), "prompt_id": "p-2", "hook_event_name": "UserPromptSubmit",
            "prompt": prompt}, "tasks"))

    def start(self, sid):
        transcript, scratch, _ = self.session(sid)
        return _context(hook_event("SessionStart", {
            "session_id": sid, "transcript_path": str(transcript), "cwd": str(self.root),
            "scratchpad_dir": str(scratch), "hook_event_name": "SessionStart", "source": "startup"},
            "tasks"))

    def config(self, data):
        (self.root / "instance" / "config.json").write_text(json.dumps(data), encoding="utf-8")


def _context(answer):
    return json.loads(answer)["hookSpecificOutput"]["additionalContext"] if answer else ""


def _shell(tid, what="sleep 600"):
    return {"id": tid, "type": "shell", "status": "running", "description": what, "command": what}


def _journal(folder, rows):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "journal.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def _launch(transcript, name, run, rows, at=None):
    """A workflow launch as the runtime lays it out: its script beside the runs, its journal in its run."""
    scripts = transcript.with_suffix("") / "workflows" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / f"{name}-{run}.js").write_text("export const meta = {}\n", encoding="utf-8")
    if at is not None:
        os.utime(scripts / f"{name}-{run}.js", (at, at))
    _journal(transcript.with_suffix("") / "subagents" / "workflows" / run, rows)


def test_line_names_each_task_its_age_and_phase_counts():
    with _Instance() as inst:
        transcript, _, tasks = inst.session("s-a")
        (tasks / "b1.output").write_text("step 3 of 9\n", encoding="utf-8")
        (tasks / "b2.output").write_text("done\n[exited with code 0]\n", encoding="utf-8")
        record = inst.runtime / "agent-record.jsonl"
        record.write_text('{"secret":"agent conversation"}\n', encoding="utf-8")
        os.symlink(record, tasks / "a1.output")
        _launch(transcript, "review", "wf_1", [
            {"type": "started", "key": "k1", "phase": "review"},
            {"type": "started", "key": "k2", "phase": "review"},
            {"type": "result", "key": "k1", "result": "SECRET ANSWER"},
            {"type": "started", "key": "k3", "phase": "fix"}])
        with open(transcript.with_suffix("") / "subagents" / "workflows" / "wf_1" / "journal.jsonl", "a") as f:
            f.write('{"type":"started","key":"k4","pha\n')   # cut off mid-append: costs only itself
        (tasks / "w2.output").write_text('{"r":"done"}', encoding="utf-8")
        assert inst.stop("s-a", [
            _shell("b1", "python3 long_job.py"), _shell("b2"),
            {"id": "a1", "type": "subagent", "status": "running", "description": "Read the logs",
             "agent_type": "general-purpose"},
            {"id": "w1", "type": "workflow", "status": "running", "description": "review the tree",
             "name": "review"},
            {"id": "w2", "type": "workflow", "status": "running", "description": "finished", "name": "x"},
        ]) == ""
        opened = []
        real_open = builtins.open
        with patch.object(builtins, "open", lambda f, *a, **k: opened.append(str(f)) or real_open(f, *a, **k)):
            line = inst.prompt("s-a")
        assert line.startswith("[tasks] this session has background work running: "), line
        assert '"python3 long_job.py" (shell), started 0m ago, output last moved 0m ago' in line, line
        assert '"Read the logs" (subagent)' in line, line
        assert ('"review: review the tree" (workflow), started 0m ago, output last moved 0m ago, '
                "agents finished per phase: review 1/2, fix 0/1 (asked how far it is, give these "
                "counts phase by phase)") in line, line
        # Ended by its exit marker or by its result file: not called running.
        assert "sleep 600" not in line and "x: finished" not in line, line
        # No task output text reaches the line, and no conversation record is opened.
        for secret in ("step 3", "SECRET", "secret"):
            assert secret not in line, line
        assert not [p for p in opened if p.endswith(("a1.output", "agent-record.jsonl", "s-a.jsonl"))], opened
        # Asked again with nothing changed: nothing is added to the context.
        again = inst.prompt("s-a")
        assert again == "", again
        # The runtime's own notice that a task ended removes it; then nothing runs, nothing prints.
        told = inst.prompt("s-a", "<task-notification>\n<task-id>a1</task-id>\n")
        assert "long_job" in told and "Read the logs" not in told, told
        inst.stop("s-a", [])
        assert inst.prompt("s-a") == ""
        assert json.loads((inst.root / ".git" / "mottori-work" / "s-a.json").read_text())["tasks"] == []
        # Seven short tasks: four are listed and the rest counted, although all seven would fit in 600 bytes.
        inst.stop("s-a", [_shell(f"m{i}", "x" * 20) for i in range(7)])
        line = inst.start("s-a")
        assert line.count('"xxx') == 4 and line.endswith("; and 3 more."), line
        # The age is kept from the first turn end that saw the task, not reset by later ones.
        snap = inst.root / ".git" / "mottori-work" / "s-a.json"
        data = json.loads(snap.read_text(encoding="utf-8"))
        data["tasks"][0]["since"] -= 3700
        snap.write_text(json.dumps(data), encoding="utf-8")
        inst.stop("s-a", [_shell(f"m{i}", "x" * 20) for i in range(7)])
        assert "started 1h01m ago" in inst.start("s-a")
        # No task names its run; its run is the newest launch of its name before the turn end that
        # first saw it and since the machine started, whatever other runs are open beside it.
        inst.stop("s-a", [])
        transcript, _, _ = inst.session("s-w")
        now = time.time()
        wf = lambda tid, name: {"id": tid, "type": "workflow", "status": "running", "description": "d", "name": name}
        _launch(transcript, "alpha", "wf_a", [{"type": "started", "key": "a1", "phase": "alphaphase"}],
                now - 300)   # stopped by hand mid-agent: its journal stays open
        _launch(transcript, "two", "wf_cut", [{"type": "started", "key": "c1", "phase": "cut"}], 500)
        inst.stop("s-w", [wf("w2", "two")])
        line = inst.start("s-w")
        assert '"two: d"' in line and "per phase" not in line, line   # its own launch is not there yet
        _launch(transcript, "two", "wf_two", [{"type": "started", "key": f"b{i}", "phase": "build"}
                                              for i in range(3)], now - 100)
        _launch(transcript, "two", "wf_later", [{"type": "started", "key": "l1", "phase": "later"}], now + 60)
        line = inst.start("s-w")
        assert "per phase: build 0/3 (" in line, line
        # Another launch of that name in the window, here one that returned before that turn end, could be
        # the newest: no counts rather than another run's.
        _launch(transcript, "two", "wf_quick", [{"type": "started", "key": "q1", "phase": "quick"},
                                                {"type": "result", "key": "q1", "result": "r"}], now - 50)
        line = inst.start("s-w")
        assert '"two: d"' in line and "per phase" not in line, line
        (transcript.with_suffix("") / "workflows" / "scripts" / "two-wf_quick.js").unlink()
        # A second task of that name seen at a later turn end launched after the first one was seen.
        inst.stop("s-w", [wf("w2", "two"), wf("w3", "two")])
        line = inst.start("s-w")
        assert line.count('"two: d"') == 2 and line.count("per phase: build 0/3 (") == 1, line
        # Two launches of one name first seen at the same turn end cannot be told apart.
        inst.stop("s-w", [])
        inst.stop("s-w", [wf("w4", "two"), wf("w5", "two")])
        line = inst.start("s-w")
        assert line.count('"two: d"') == 2 and "per phase" not in line, line
        inst.stop("s-w", [])
        # A rerun after a turn end with nothing running: that turn end bounds its window, so the earlier
        # launches of the name do not hide its counts. Between phases a workflow has no agent running, yet
        # its run moved: counts and signs of life stay, for another session too.
        _launch(transcript, "two", "wf_again", [{"type": "started", "key": "b1", "phase": "build"},
                                                {"type": "result", "key": "b1", "result": "r"}])
        inst.stop("s-w", [wf("w2", "two")])
        snap = inst.root / ".git" / "mottori-work" / "s-w.json"
        data = json.loads(snap.read_text(encoding="utf-8"))
        data["at"] -= 3600
        snap.write_text(json.dumps(data), encoding="utf-8")
        line = inst.start("s-other")
        assert "another session" in line and "per phase: build 1/1 (" in line, line
        inst.stop("s-w", [])
        # Three sessions of six long tasks share the 600 bytes: each keeps its own line, untruncated.
        for sid in ("s-1", "s-2", "s-3"):
            inst.stop(sid, [_shell(f"{sid[-1]}t{i}", "y" * 200) for i in range(6)])
            _, _, tasks = inst.session(sid)
            for i in range(6):
                (tasks / f"{sid[-1]}t{i}.output").write_text("x\n", encoding="utf-8")
        line = inst.start("s-1")
        assert len(line.encode("utf-8")) <= 600 and line.count("[tasks]") == 3, line
        assert not line.endswith("..."), line


def test_restart_other_sessions_and_switch():
    with _Instance() as inst:
        inst.stop("s-a", [_shell("b1", "train model")])
        inst.stop("s-b", [_shell("b9", "index docs")])
        _, _, tasks_b = inst.session("s-b")
        (tasks_b / "b9.output").write_text("x\n", encoding="utf-8")
        line = inst.start("s-a")
        assert "this session has background work running" in line and "train model" in line, line
        assert '[tasks] another session on this folder has background work running: "index docs"' in line, line
        # Another session's task with no sign of life for half an hour is not shown.
        # A snapshot that cannot be read now is skipped and kept for its owner to rewrite.
        snap_b = inst.root / ".git" / "mottori-work" / "s-b.json"
        snap_b.chmod(0)
        try:
            assert "index docs" not in inst.prompt("s-a") and snap_b.exists()
        finally:
            snap_b.chmod(0o600)
        old = time.time() - tasks.QUIET_SECONDS - 60
        os.utime(tasks_b / "b9.output", (old, old))
        assert "index docs" not in inst.prompt("s-a")
        # A snapshot nobody rewrote for two weeks is removed.
        data = json.loads(snap_b.read_text(encoding="utf-8"))
        data["at"] -= 15 * 86400
        snap_b.write_text(json.dumps(data), encoding="utf-8")
        inst.prompt("s-a")
        assert not snap_b.exists()
        # A machine start after the snapshot: said once to the owner and once to the others.
        with patch.object(tasks, "_boot", lambda: time.time() + 5):
            # A hand run and a doctor probe show the notice to no session, so neither uses it up.
            with contextlib.redirect_stdout(io.StringIO()) as hand:
                tasks.main(["tasks.py"])
            assert "Cut off" in hand.getvalue(), hand.getvalue()
            with patch.dict(os.environ, {"MOTTORI_INTERNAL_RUN": "1"}):
                assert "Cut off" in inst.start("s-a") and "Cut off" in inst.start("s-x")
            told = inst.prompt("s-a")
            assert told.startswith("[tasks] Cut off by a machine restart at ") and "train model" in told, told
            assert "Not running now." in told, told
            assert "train model" not in inst.start("s-a")
            assert "(another session on this folder)" in inst.start("s-c")
            assert "train model" not in inst.start("s-d")
        # The off switch silences every step.
        inst.stop("s-a", [_shell("b1", "train model")])
        inst.config({"work_line": "off"})
        assert inst.start("s-a") == "" and inst.prompt("s-a") == ""
        inst.stop("s-a", [_shell("b2", "other")])
        inst.config({})
        assert "other" not in inst.start("s-a"), "a switched-off turn end saved nothing"


def test_errors_and_unknown_input_are_silent():
    with _Instance() as inst:
        for payload in ({}, {"background_tasks": "x"}, {"session_id": "../up", "background_tasks": [{"id": "a"}]},
                        {"session_id": "s", "background_tasks": [1, None, {"id": 5}, {"id": "../x"}]},
                        {"session_id": "s", "background_tasks": [{"id": "t"}], "transcript_path": 7}):
            assert hook_event("Stop", payload, "tasks") == ""
        store = inst.root / ".git" / "mottori-work"
        assert sorted(p.name for p in store.iterdir()) == ["s.json"], list(store.iterdir())
        shutil.rmtree(store)
        store.mkdir()
        (store / "broken.json").write_text("{not json", encoding="utf-8")
        (store / "other.json").write_text(json.dumps({"session": "z", "at": "soon", "tasks": [{}]}),
                                          encoding="utf-8")
        (store / ".seen.json").write_text("[1, 2]", encoding="utf-8")
        # A session is running something, yet a payload naming no valid session shows it to nobody.
        inst.stop("s-live", [_shell("l1", "live job")])
        for payload in ({}, {"prompt": 5}, {"session_id": ["x"]}, {"session_id": 7, "prompt": 3},
                        {"session_id": "../../x"}):
            assert hook_event("UserPromptSubmit", payload, "tasks") == ""
            assert hook_event("SessionStart", payload, "tasks") == ""
        (store / "s-live.json").unlink()
        (inst.root / "instance" / "config.json").write_text("{", encoding="utf-8")
        assert inst.prompt("s") == ""
        assert sorted(p.name for p in store.iterdir()) == [".seen.json"], "damaged snapshots are removed"
        # No Git directory: nothing saved, nothing printed.
        shutil.rmtree(inst.root / ".git")
        assert inst.stop("s", [_shell("b1")]) == "" and inst.prompt("s") == ""
    # The machine start is read from the system itself, since every case above replaces it, and also
    # where the search path lacks the folder of the system's tools, as a scheduled cycle's does.
    assert 0 < tasks._boot() < time.time(), tasks._boot()
    with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
        assert 0 < tasks._boot() < time.time(), tasks._boot()
    # The command itself: exit 0 for the line, 2 with usage for an argument it does not know.
    env = dict(os.environ)
    ok = subprocess.run([sys.executable, str(HERE / "tasks.py")], capture_output=True, text=True,
                        stdin=subprocess.DEVNULL, env=env)
    assert ok.returncode == 0 and ok.stderr == "", ok
    bad = subprocess.run([sys.executable, str(HERE / "tasks.py"), "nope"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, env=env)
    assert bad.returncode == 2 and bad.stderr.startswith("usage: tasks.py"), bad


def test_a_prompt_with_nothing_running_reads_no_boot_time():
    """The machine start is read by a process on macOS; a prompt with nothing running starts none."""
    with _Instance() as inst:
        inst.stop("s-a", [])   # A turn end with nothing running leaves an empty snapshot.
        inst.stop("s-b", [])
        reads = []
        with patch.object(tasks, "_boot", lambda: reads.append(1) or 1000.0):
            assert inst.prompt("s-a") == "" and inst.start("s-b") == ""
        assert reads == [], f"{len(reads)} boot time reads on prompts with nothing running"


def test_another_workflow_never_gives_its_counts():
    """A workflow stopped mid-agent leaves its journal open; a workflow launched after it, of
    another name or the same one, shows only its own counts, now and later."""
    for second in ("beta", "alpha"):
        with _Instance() as inst:
            transcript, _, _ = inst.session("s-a")
            wf = lambda tid, name: {"id": tid, "type": "workflow", "status": "running",
                                    "description": "d", "name": name}
            now = time.time()
            _launch(transcript, "alpha", "wf_a", [{"type": "started", "key": "a1", "phase": "alphaphase"},
                                                  {"type": "started", "key": "a2", "phase": "alphaphase"},
                                                  {"type": "result", "key": "a1", "result": "r"}], now - 300)
            inst.stop("s-a", [wf("wa", "alpha")])
            assert "alphaphase 1/2" in inst.start("s-a")
            snap = inst.root / ".git" / "mottori-work" / "s-a.json"
            data = json.loads(snap.read_text(encoding="utf-8"))
            data["at"] -= 200   # that turn end came after the first launch
            data["tasks"][0]["since"] -= 200
            snap.write_text(json.dumps(data), encoding="utf-8")
            _launch(transcript, second, "wf_b", [], now - 50)
            (transcript.with_suffix("") / "subagents" / "workflows" / "wf_b" / "journal.jsonl").unlink()
            inst.stop("s-a", [wf("wb", second)])   # the first one stopped: gone from the list
            line = inst.start("s-a")
            assert f'"{second}: d"' in line and "per phase" not in line, (second, line)
            for rows, counts in (([{"type": "started", "key": "b1", "phase": "betaphase"}], "betaphase 0/1"),
                                 ([{"type": "started", "key": "b1", "phase": "betaphase"},
                                   {"type": "result", "key": "b1", "result": "r"},
                                   {"type": "started", "key": "b2", "phase": "next"}], "betaphase 1/1, next 0/1")):
                _launch(transcript, second, "wf_b", rows, now - 50)
                line = inst.start("s-a")
                assert f"per phase: {counts} (" in line and "alphaphase" not in line, (second, line)


def test_finished_runs_add_no_file_reads_to_a_prompt():
    """A prompt reads one journal for one running workflow, however many runs finished before it."""
    counts = []
    for finished in (0, 30):
        with _Instance() as inst:
            transcript, _, _ = inst.session("s-a")
            now = time.time()
            for j in range(finished):
                _launch(transcript, ("live", "other")[j % 2], f"wf_old{j}",
                        [{"type": "started", "key": "k", "phase": "p"},
                         {"type": "result", "key": "k", "result": "r" * 2000}], now - 1000)
            _launch(transcript, "live", "wf_live", [{"type": "started", "key": "k", "phase": "p"}], now - 10)
            inst.stop("s-a", [{"id": "w", "type": "workflow", "status": "running", "description": "d",
                               "name": "live"}])
            data = json.loads((inst.root / ".git" / "mottori-work" / "s-a.json").read_text())
            data["tasks"][0]["after"] = now - 100   # the turn end before the launch
            (inst.root / ".git" / "mottori-work" / "s-a.json").write_text(json.dumps(data))
            opened = []
            real_open = builtins.open
            with patch.object(builtins, "open", lambda f, *a, **k: opened.append(str(f)) or real_open(f, *a, **k)):
                assert "per phase: p 0/1 (" in inst.prompt("s-a")
            counts.append(len(opened))
            assert sum(p.endswith("journal.jsonl") for p in opened) == 1, opened
    assert counts[0] == counts[1], counts


def test_the_index_catching_up_is_quiet_and_a_failure_is_said_once():
    import fcntl
    with _Instance() as inst:
        status = inst.root / "_private" / "state" / "recall-catch-up.json"
        status.parent.mkdir(parents=True)
        started = time.time() - 120
        status.write_text(json.dumps({"started": started}), encoding="utf-8")
        with open(str(status) + ".lock", "a+b") as held:   # the catch-up process holds it
            fcntl.flock(held.fileno(), fcntl.LOCK_EX)
            assert inst.start("s-a") == ""   # a search's last line says how much is indexed
        status.write_text(json.dumps({"started": started, "ended": time.time(), "messages": 12,
                                      "meaning": [10, 12], "failed": None}), encoding="utf-8")
        assert inst.prompt("s-a") == "" and inst.start("s-b") == ""
        # A failure is said once; the same failure of a later catch-up is not said again.
        failed = {"started": started + 1, "ended": time.time(), "failed": "OSError: disk full"}
        status.write_text(json.dumps(failed), encoding="utf-8")
        assert inst.start("s-c") == (
            "[tasks] Bringing the search index up to date behind the session failed (OSError: disk "
            "full); a search answers from what is indexed now, and the next session start tries again.")
        assert inst.prompt("s-c") == "" and inst.start("s-d") == ""
        said = json.loads(status.read_text(encoding="utf-8"))["said"]
        status.write_text(json.dumps(dict(failed, started=started + 2, said=said)), encoding="utf-8")
        assert inst.start("s-e") == ""


TESTS = [
    test_line_names_each_task_its_age_and_phase_counts,
    test_restart_other_sessions_and_switch,
    test_errors_and_unknown_input_are_silent,
    test_a_prompt_with_nothing_running_reads_no_boot_time,
    test_another_workflow_never_gives_its_counts,
    test_finished_runs_add_no_file_reads_to_a_prompt,
    test_the_index_catching_up_is_quiet_and_a_failure_is_said_once,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"tasks: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
