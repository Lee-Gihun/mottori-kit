#!/usr/bin/env python3
"""No model program the improvement loop starts may write: every stage starts the worker tool with
--read-only, and with it the worker tool gives every runtime's program no right to write."""
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
import loop_config  # noqa: E402
import loop_worker  # noqa: E402

WORKER = os.path.join(TOOLS, "fresh_worker.py")
# Stand-ins that record their arguments and answer the way each runtime does.
STAND_INS = {
    "codex": """
import json, pathlib, sys
args = sys.argv[1:]
open(pathlib.Path(__file__).parent / "codex.args", "w").write(json.dumps(args))
sys.stdin.read()
pathlib.Path(args[args.index("--output-last-message") + 1]).write_text("the answer\\n")
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}}))
""",
    "claude": """
import json, pathlib, sys
open(pathlib.Path(__file__).parent / "claude.args", "w").write(json.dumps(sys.argv[1:]))
sys.stdin.read()
print(json.dumps({"type": "result", "result": "the answer"}))
""",
    "gemini": """
import json, pathlib, sys
open(pathlib.Path(__file__).parent / "gemini.args", "w").write(json.dumps(sys.argv[1:]))
print(json.dumps({"response": "the answer", "conversation_id": "c"}))
""",
}


def instance():
    root = Path(tempfile.mkdtemp(prefix="loop-read-only-"))
    (root / "instance").mkdir()
    (root / "instance" / "config.json").write_text(json.dumps({"schema_version": 4, "journal_visibility": {
        "public_tracks": ["system"], "legacy_cutoff": None, "legacy_public_tracks": []}}), encoding="utf-8")
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (root / "prompt.md").write_text("answer\n", encoding="utf-8")
    for name, body in STAND_INS.items():
        path = root / "bin" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("#!" + sys.executable + "\n" + body, encoding="utf-8")
        path.chmod(0o755)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                                  "commit", "-q", "-m", "init"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def worker(root, runtime, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MOTTORI_FRESH_WORKER_", "CODEX_", "CLAUDE_"))}
    env.update(HOME=str(root / "home"), MOTTORI_INSTANCE=str(root),
               **{f"MOTTORI_FRESH_WORKER_{runtime.upper()}_BIN": str(root / "bin" / runtime)})
    return subprocess.run([sys.executable, WORKER, "--runtime", runtime, *args, "prompt.md"], cwd=root,
                          env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def meta_of(root, run):
    line = next(x for x in run.stdout.splitlines() if x.startswith("run: "))
    return json.loads((root / line.split(": ", 1)[1] / "meta.json").read_text(encoding="utf-8"))


def test_read_only_gives_no_runtime_a_right_to_write():
    root = instance()
    try:
        for runtime, where in (("codex", ()), ("codex", ("--worktree=head",)), ("claude", ()), ("gemini", ())):
            r = worker(root, runtime, "--read-only", *where)
            assert r.returncode == 0, (runtime, r.stdout, r.stderr)
            meta = meta_of(root, r)
            assert meta["capability"] == "read-only" and meta["status"] == "success", (runtime, meta["status"])
            args = json.loads((root / "bin" / f"{runtime}.args").read_text())
            if runtime == "codex":
                assert args[args.index("--sandbox") + 1] == "read-only", args
            if runtime == "claude":
                tools = args[args.index("--tools") + 1:args.index("--no-session-persistence")]
                assert tools == ["Read", "Glob", "Grep"] and "dontAsk" in args, args
            if runtime == "gemini":
                assert "write_file(*)" in args[args.index("--settings") + 1], args
        # The answer is the output, so there is no write to measure or to expect.
        for extra in (("--write-prefix", "out"), ("--expect", "out/x.md")):
            r = worker(root, "codex", "--read-only", *extra)
            assert r.returncode == 2 and "--read-only" in r.stderr, (extra, r.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_every_stage_starts_every_runtime_read_only():
    """Each stage walks its whole order here (every runtime reports it cannot be called), and each
    start the loop asks of the worker tool carries --read-only and no right to write."""
    root = tempfile.mkdtemp(prefix="loop-read-only-stages-")
    try:
        starts = []

        def launch(args, receipt):
            starts.append(args)
            run = tempfile.mkdtemp(prefix="run-", dir=root)
            with open(os.path.join(run, "meta.json"), "w") as f:
                json.dump({"status": "failed", "unavailable": "not-installed"}, f)
            with open(os.path.join(root, loop_worker.run_file(receipt)), "w") as f:
                json.dump({"run_dir": run}, f)
            return 1, False
        orders = {"default": ["codex", "claude", "gemini"]}
        with open(os.path.join(root, "x.receipt"), "w"):
            pass
        os.makedirs(os.path.join(root, "instance"))
        with open(os.path.join(root, "instance", "config.json"), "w") as f:
            json.dump({"loop": {"runtime_orders": orders}}, f)
        for stage in sorted(loop_config.STAGES):
            starts.clear()
            loop_worker.run_stage(stage, ["worker"], "p.md", "x.receipt", launch, root,
                                  built_by="claude" if stage == "review" else None)
            runtimes = [a[a.index("--runtime") + 1] for a in starts]
            assert set(runtimes) >= {"codex", "claude"}, (stage, runtimes)
            for args in starts:
                assert "--read-only" in args and "--write-prefix" not in args and "--expect" not in args, (stage, args)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stage_output_replaces_a_link_at_its_place_and_leaves_its_target_alone():
    """The loop writes a stage's answer by moving a new file into place: a link already standing where
    the output goes is replaced, and the file it points to keeps its bytes and its mode."""
    from unittest import mock
    import loop_beat
    root = tempfile.mkdtemp(prefix="loop-stage-output-")
    try:
        run = os.path.join(root, "run")
        os.makedirs(run)
        with open(os.path.join(run, "result.txt"), "w") as f:
            f.write("the answer\n")
        other = os.path.join(root, "other.txt")
        with open(other, "w") as f:
            f.write("not the loop's\n")
        os.chmod(other, 0o644)
        dst = os.path.join(root, "OUT.md")
        os.symlink(other, dst)
        o = {"unavailable": None, "run": run,
             "meta": {"capability": "read-only", "status": "success", "result_bytes": 11}}
        with mock.patch.object(loop_beat.loop_worker, "run_stage", return_value=o):
            loop_beat.Beat(os.path.join(root, "log")).walk("card", os.path.join(root, "p.md"),
                                                           os.path.join(root, "r.receipt"), answer_file=dst)
        with open(other) as f:
            assert f.read() == "not the loop's\n" and os.stat(other).st_mode & 0o777 == 0o644
        assert not os.path.islink(dst) and open(dst).read() == "the answer\n", os.readlink(dst) if os.path.islink(dst) else ""
        assert os.stat(dst).st_mode & 0o777 == 0o600
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_read_only_gives_no_runtime_a_right_to_write,
    test_every_stage_starts_every_runtime_read_only,
    test_a_stage_output_replaces_a_link_at_its_place_and_leaves_its_target_alone,
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
    print(f"loop_read_only: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
