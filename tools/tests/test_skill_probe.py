#!/usr/bin/env python3
"""The skill probe: it counts the skills a session opened, starts nothing without a yes, refuses a
tree that is not an installed copy or that sits below someone else's instruction file, names a run
with no result, and keeps its streams private.

Every session is a stand-in program named by MOTTORI_SKILL_PROBE_CLAUDE_BIN that writes a stream
built here by hand; no test reaches a real model program.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROBE = os.path.join(ROOT, "tools", "dev", "skill_probe.py")

# The stand-in: it logs each call, answers --version, and writes a stream whose skills follow the
# task sentence: "open:NAME" words become Skill calls, "no-result" leaves out the result event, and
# "no-model" leaves the model's name out of the first event.
STAND_IN = r'''#!{python}
import json, os, sys
with open(os.environ["PROBE_LOG"] if "PROBE_LOG" in os.environ else {log!r}, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "env": sorted(os.environ), "cwd": os.getcwd()}}) + "\n")
if sys.argv[1:] == ["--version"]:
    print("9.9.9 (stand-in)")
    sys.exit(0)
task = sys.argv[sys.argv.index("-p") + 1]
def say(event):
    print(json.dumps(event))
first = {{"type": "system", "subtype": "init", "tools": ["Skill", "Read"]}}
if "no-model" not in task:
    first["model"] = "model-the-session-ran"
say(first)
for word in task.split():
    if word.startswith("open:"):
        say({{"type": "assistant", "message": {{"content": [
            {{"type": "text", "text": "looking"}},
            {{"type": "tool_use", "id": "t1", "name": "Skill", "input": {{"skill": word[5:]}}}}]}}}})
if "no-result" not in task:
    say({{"type": "result", "subtype": "success", "result": "x" * len(task), "total_cost_usd": 0.25}})
'''


def _installation(parent):
    root = os.path.join(parent, "install")
    os.makedirs(os.path.join(root, "instance"))
    with open(os.path.join(root, "instance", "config.json"), "w") as f:
        f.write("{}\n")
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("_private/\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(git + ["-C", root, "add", "-A"], check=True)
    subprocess.run(git + ["-C", root, "commit", "-qm", "start"], check=True)
    return root


def _setup(tasks):
    parent = tempfile.mkdtemp(prefix="skill-probe-")
    root = _installation(parent)
    log = os.path.join(parent, "calls.jsonl")
    program = os.path.join(parent, "claude-stand-in")
    with open(program, "w") as f:
        f.write(STAND_IN.format(python=sys.executable, log=log))
    os.chmod(program, 0o755)
    tasks_file = os.path.join(parent, "tasks.json")
    with open(tasks_file, "w") as f:
        json.dump({"thinking_skills": ["lenses", "deep-pass"], "tasks": tasks}, f)
    env = {k: v for k, v in os.environ.items() if k not in ("PROBE_LOG",)}
    env["MOTTORI_SKILL_PROBE_CLAUDE_BIN"] = program
    env["PROBE_SECRET_VARIABLE"] = "must not reach the session"
    return parent, root, log, tasks_file, env


def _probe(args, env):
    return subprocess.run([sys.executable, PROBE, *args], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120)


def _calls(log):
    if not os.path.exists(log):
        return []
    with open(log) as f:
        return [json.loads(line) for line in f]


THREE = [
    {"id": "a1", "expect": "open", "text": "decide open:lenses now"},
    {"id": "a2", "expect": "open", "text": "plain question with no skill"},
    {"id": "b1", "expect": "closed", "text": "rename open:plugin:deep-pass open:recall"},
]


def test_counts_and_totals_over_two_runs():
    parent, root, log, tasks_file, env = _setup(THREE)
    try:
        run = _probe([root, tasks_file, "--runs", "2", "--model", "some-model", "yes"], env)
        assert run.returncode == 0, run.stdout + run.stderr
        out = run.stdout
        assert "model: model-the-session-ran\n" in out, out
        assert "version: 9.9.9 (stand-in)" in out, out
        assert "a1  should open  opened in 2 of 2 runs: lenses" in out, out
        assert "a2  should open  opened in 0 of 2 runs: none" in out, out
        assert "b1  should stay closed  opened in 2 of 2 runs: plugin:deep-pass" in out, out
        assert "a thinking skill opened in 2 of 4 runs of the tasks that should open one" in out, out
        assert "a thinking skill opened in 2 of 2 runs of the tasks that should not" in out, out
        lengths = sorted([len(t["text"]) for t in THREE] * 2)
        median = (lengths[2] + lengths[3]) / 2
        assert f"median answer length: {median:g} characters" in out, out
        assert "summed cost: $1.5000" in out, out
        sessions = [c for c in _calls(log) if c["argv"] != ["--version"]]
        assert len(sessions) == 6, sessions
        for call in sessions:
            argv = call["argv"]
            assert argv[argv.index("--model") + 1] == "some-model", argv
            assert argv[argv.index("--max-budget-usd") + 1] == "2", argv
            assert not any("dangerously" in a or "skip-permissions" in a for a in argv), argv
            assert "PROBE_SECRET_VARIABLE" not in call["env"], call["env"]
            assert os.path.realpath(call["cwd"]) == os.path.realpath(root), call
        folder = os.path.join(root, "_private", "work", "skill-probe")
        (stamp,) = os.listdir(folder)
        saved = sorted(os.listdir(os.path.join(folder, stamp)))
        assert saved == ["a1-1.jsonl", "a1-2.jsonl", "a2-1.jsonl", "a2-2.jsonl",
                         "b1-1.jsonl", "b1-2.jsonl", "summary.json"], saved
        with open(os.path.join(folder, stamp, "summary.json")) as f:
            summary = json.load(f)
        assert summary["should_open"] == {"opened": 2, "runs": 4}, summary
        assert summary["no_result"] == [], summary
        status = subprocess.run(["git", "-C", root, "status", "--porcelain"], capture_output=True,
                                text=True, check=True)
        assert status.stdout == "", status.stdout
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_starts_nothing_without_yes():
    parent, root, log, tasks_file, env = _setup(THREE)
    try:
        run = _probe([root, tasks_file, "--runs", "3", "--only", "a1,b1"], env)
        assert run.returncode == 0, run.stdout + run.stderr
        assert "This starts 6 Claude Code session(s)" in run.stdout, run.stdout
        assert "billed" in run.stdout and "$2" in run.stdout, run.stdout
        assert "Nothing was started" in run.stdout, run.stdout
        assert run.stdout.rstrip().endswith(f"--runs 3 --only a1,b1 yes`."), run.stdout
        assert _calls(log) == [], _calls(log)
        assert not os.path.exists(os.path.join(root, "_private")), os.listdir(root)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_refuses_its_own_tree_and_a_folder_not_installed():
    parent, root, log, tasks_file, env = _setup(THREE)
    try:
        own = _probe([ROOT, tasks_file, "yes"], env)
        assert own.returncode == 2 and own.stdout.startswith("refused: ") \
            and "tree this tool sits in" in own.stdout, own.stdout
        bare = os.path.join(parent, "bare")
        os.makedirs(bare)
        other = _probe([bare, tasks_file, "yes"], env)
        assert other.returncode == 2 and "has no instance/config.json" in other.stdout, other.stdout
        assert len(own.stdout.splitlines()) == 1 and len(other.stdout.splitlines()) == 1
        assert _calls(log) == [], _calls(log)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_a_stream_without_result_is_named_and_fails():
    tasks = [{"id": "c1", "expect": "open", "text": "open:lenses no-result no-model"},
             {"id": "c2", "expect": "closed", "text": "fine no-model"}]
    parent, root, log, tasks_file, env = _setup(tasks)
    try:
        run = _probe([root, tasks_file, "--runs", "1", "yes"], env)
        assert run.returncode == 1, run.stdout + run.stderr
        assert "model: the default (no session named its model)" in run.stdout, run.stdout
        assert "no result: _private/work/skill-probe/" in run.stdout and "c1-1.jsonl" in run.stdout, \
            run.stdout
        assert "c1  should open  opened in 0 of 0 runs: none" in run.stdout, run.stdout
        assert "a thinking skill opened in 0 of 0 runs of the tasks that should open one" in run.stdout
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_refuses_an_installation_below_an_instruction_file():
    parent, root, log, tasks_file, env = _setup(THREE)
    try:
        for name in ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md")):
            above = os.path.join(parent, name)
            os.makedirs(os.path.dirname(above), exist_ok=True)
            with open(above, "w") as f:
                f.write("someone else's instructions\n")
            run = _probe([root, tasks_file, "yes"], env)
            assert run.returncode == 2 and run.stdout.startswith("refused: "), run.stdout
            assert os.path.realpath(above) in run.stdout and "would read it too" in run.stdout, run.stdout
            assert len(run.stdout.splitlines()) == 1, run.stdout
            os.remove(above)
        assert _calls(log) == [], _calls(log)
        assert not os.path.exists(os.path.join(root, "_private")), os.listdir(root)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


TESTS = [test_counts_and_totals_over_two_runs, test_starts_nothing_without_yes,
         test_refuses_its_own_tree_and_a_folder_not_installed,
         test_refuses_an_installation_below_an_instruction_file,
         test_a_stream_without_result_is_named_and_fails]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
