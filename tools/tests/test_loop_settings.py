#!/usr/bin/env python3
"""A wrong setting in the loop's block stops the loop instead of loosening it: every key is known or is a
problem, no value raises, `loops.py status` lists the problems first, the health check reports them,
and neither a cycle nor the applier judges or builds while one exists.

Every case runs in a scratch tree with stand-ins for launchctl and the workers; no model program starts."""
import json
import os
import shutil
import subprocess
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import test_loop_way_in as W  # noqa: E402

# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/lib/loop_config.py",
    "tools/loop/lib/loop_settings.py",
    "tools/loop/loops.py",
    "tools/loop/loop_watchdog.py",
)
STOPPED = "config error: loop is stopped (no cycle will judge or build until fixed)"
# Blocks with one problem each, and a word its line must hold.
WRONG = (
    ({"nevr": ["notes/"]}, "loop.nevr: unknown setting"),
    ({"never": ["evidence/", 3]}, "loop.never"),
    ({"never": "evidence/"}, "loop.never"),
    ({"runtime_orders": {"judge": [["claude"]]}}, "loop.runtime_orders"),
    ({"runtime_orders": {"judge": [{"a": 1}]}}, "loop.runtime_orders"),
    ({"landing": "worktree"}, "loop.landing: unknown setting"),
    ({"landing_paths": ["system/"]}, "loop.landing_paths: unknown setting"),
    ({"self_landing": True}, "loop.self_landing: unknown setting"),
    ({"commit_trailer": None}, "loop.commit_trailer: unknown setting"),
    ({"schedule": {"papers": {"weekday": [0], "hour": 1, "minute": 0}}}, "loop.schedule"),
    ({"token_ceilng": 100000}, "loop.token_ceilng: unknown setting"),
    ({"token_ceiling": "100000"}, "loop.token_ceiling"),
    ({"token_ceiling": -1}, "loop.token_ceiling"),
    ({"token_ceiling": True}, "loop.token_ceiling"),
)


def with_block(block, allow=("_private/work/papers/",)):
    cfg = json.loads(json.dumps(W.CONFIG))
    cfg["egress"]["model_send"]["allow_prefixes"] = list(allow)
    cfg["loop"] = block
    return cfg


def test_every_wrong_setting_is_a_listed_problem_and_none_raises():
    for block, word in WRONG:
        with W.instance(with_block(block)) as (root, env):
            r = W.run(root, env, "loop/loops.py", "status")
            lines = r.stdout.splitlines()
            assert r.returncode == 0 and "Traceback" not in r.stderr, (block, r.stdout, r.stderr)
            assert lines[:2] == [STOPPED, "  instance/config.json (loop):"], (block, r.stdout)
            assert any(line.startswith("  - ") and word in line for line in lines[2:]), (block, r.stdout)
            assert "python3 tools/loop/lib/loop_config.py" in r.stdout, r.stdout
            r = W.run(root, env, "loop/lib/loop_config.py")
            assert r.returncode == 0 and "Traceback" not in r.stderr, (block, r.stdout, r.stderr)
    # A note key (one that starts with _) and every known key with a right value are no problem.
    with W.instance(with_block({"_doc": "a note", "never": ["notes/"], "token_ceiling": 1000})) as (root, env):
        r = W.run(root, env, "loop/loops.py", "status")
        assert not r.stdout.startswith("config error"), r.stdout


def test_a_wrong_setting_stops_the_cycle_before_any_worker_and_the_health_check_says_so():
    with W.instance(with_block({"nevr": ["notes/"], "landing": "worktree"})) as (root, env):
        os.unlink(os.path.join(root, "tools", "loop", "papers_cycle.sh"))
        shutil.copy2(os.path.join(TOOLS, "loop", "papers_cycle.sh"), os.path.join(root, "tools", "loop", "papers_cycle.sh"))
        worker = os.path.join(root, "tools", "fresh_worker.py")
        W.write(root, "tools/fresh_worker.py", "import sys\nopen('worker-calls.txt', 'a').write(' '.join(sys.argv) + '\\n')\n")
        r = subprocess.run(["bash", "tools/loop/papers_cycle.sh", "--force"], cwd=root, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=120)
        assert not os.path.exists(os.path.join(root, "worker-calls.txt")), "a worker started"
        assert r.returncode != 0, r.stdout + r.stderr
        assert r.stdout.strip().splitlines()[-1:] == [(
            "stopped: 2 problems in instance/config.json (loop); nothing judged or built. "
            "See: python3 tools/loop/loops.py status")], r.stdout + r.stderr
        assert os.path.isfile(worker)
        assert not os.path.isdir(os.path.join(root, "_private", "papers")), "the cycle started"
        r = W.run(root, env, "loop/loop_watchdog.py", "--dry", "--no-auth")
        assert "[loop-settings] " in r.stdout and "python3 tools/loop/loops.py status" in r.stdout, r.stdout


def test_a_wrong_setting_stops_the_applier_before_any_worker():
    import test_papers_apply as T
    root = T.fixture()
    try:
        T.set_config(root, nevr=["notes/"])
        T.respond(root, judge=T.judge_text([T.bundle()]), impl_bump=T.EDIT_OK, review_bump=T.PASS)
        before = T.head(root)
        r = T.run_apply(root, T.CYCLE)
        assert r.returncode == 1 and T.head(root) == before, r.stdout + r.stderr
        assert r.stdout.strip() == ("stopped: 1 problem in instance/config.json (loop); nothing judged or built. "
                                    "See: python3 tools/loop/loops.py status"), r.stdout + r.stderr
        assert not (root / "_fake" / "resp" / "calls.log").exists(), "a worker started"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# Path entries that are not one literal path: a doubled slash, a pattern, a step out, a leading slash, a step here.
NOT_LITERAL = ("notes//", "system/lenses//", "system/lenses/*.md", "../x", "/x", "./x")


def test_an_entry_that_is_not_one_literal_path_is_a_problem_that_names_it():
    for key in ("never", "clone_excluded"):
        for entry in NOT_LITERAL:
            block = {key: ["system/kept.md", entry]}
            with W.instance(with_block(block)) as (root, env):
                r = W.run(root, env, "loop/loops.py", "status")
                lines = r.stdout.splitlines()
                assert lines[:1] == [STOPPED], (key, entry, r.stdout)
                assert any(line.startswith(f"  - loop.{key}: cannot use {json.dumps(entry)}: ") for line in lines), (
                    key, entry, r.stdout)


def test_a_key_twice_in_the_loop_block_is_a_problem():
    cases = (('"never": ["evidence/"], "never": ["other/"]', "loop.never: occurs twice"),
             ('"schedule": {"papers": {"weekday": 0, "hour": 1, "hour": 2, "minute": 0}}',
              "loop.schedule.papers.hour: occurs twice"))
    for inner, line in cases:
        with W.instance(with_block({})) as (root, env):
            path = os.path.join(root, "instance", "config.json")
            text = open(path, encoding="utf-8").read().replace('"loop": {}', '"loop": {' + inner + '}')
            assert inner in text, text
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            r = W.run(root, env, "loop/loops.py", "status")
            assert r.stdout.splitlines()[:1] == [STOPPED] and f"  - {line}" in r.stdout, (inner, r.stdout)


def test_a_runtime_name_the_worker_tool_does_not_know_is_a_problem():
    with W.instance(with_block({"runtime_orders": {"judge": ["claud", "codex"]}})) as (root, env):
        r = W.run(root, env, "loop/loops.py", "status")
        assert r.stdout.splitlines()[:1] == [STOPPED], r.stdout
        assert '  - loop.runtime_orders: unknown runtime "claud"' in r.stdout, r.stdout


def test_the_settings_know_the_runtimes_the_worker_tool_knows():
    sys.path[:0] = [TOOLS, os.path.join(TOOLS, "lib")]
    import config
    import fresh_worker
    assert set(config.WORKER_RUNTIMES) == set(fresh_worker.RUNTIMES), (config.WORKER_RUNTIMES, fresh_worker.RUNTIMES)


TESTS = [
    test_every_wrong_setting_is_a_listed_problem_and_none_raises,
    test_an_entry_that_is_not_one_literal_path_is_a_problem_that_names_it,
    test_a_key_twice_in_the_loop_block_is_a_problem,
    test_a_runtime_name_the_worker_tool_does_not_know_is_a_problem,
    test_the_settings_know_the_runtimes_the_worker_tool_knows,
    test_a_wrong_setting_stops_the_cycle_before_any_worker_and_the_health_check_says_so,
    test_a_wrong_setting_stops_the_applier_before_any_worker,
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
    print(f"loop_settings: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
