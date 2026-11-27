#!/usr/bin/env python3
"""A source an installation adds (tools/loop/sources/README.md) reaches every part of the loop through one
seam: its settings and model steps are known, the applier lists and refuses its cycles as it says, the
judge reads what it names, its files count as the loop's own tools, and the health check runs its check.
A broken source module stops the loop with its path.

Every case runs in a scratch copy of tools/ with the test's own source, notes (tools/tests/testlib.py);
`on loop`, the schedule and the status of an added source are in test_loop_way_in.py and
test_loop_consent.py. No model program starts."""
import json
import subprocess
import sys

import test_loop_way_in as W

# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/lib/loop_sources.py",
)


def _py(root, env, code):
    return subprocess.run([sys.executable, "-c", "import sys; sys.path[:0] = ['tools/loop', 'tools/loop/lib', 'tools', "
                           "'tools/lib']\n" + code], cwd=root, env=env, capture_output=True, text=True, timeout=60)


def test_an_added_source_is_known_listed_judged_and_watched():
    cfg = json.loads(json.dumps(W.CONFIG))
    cfg["loop"] = {"notes_folder": "notes/", "runtime_orders": {"notes-review": ["claude"]}}
    with W.instance(cfg) as (root, env):
        r = W.run(root, env, "loop/lib/loop_config.py")
        assert r.returncode == 0 and "loop.notes_folder = \"notes/\"" in r.stdout and "problem:" not in r.stdout, r.stdout
        for day, failed in (("2026-11-01", False), ("2026-11-02", True)):
            W.write(root, f"_private/notes/{day}/REVIEW.md", "# notes review\n" + "x" * 250)
            if failed:
                W.write(root, f"_private/notes/{day}/FAILED", "collection failed\n")
        r = W.run(root, env, "loop/papers_apply.py", "--backlog", "--source", "notes", "--list")
        assert r.returncode == 0 and r.stdout.split() == ["_private/notes/2026-11-01"], r.stdout + r.stderr
        r = _py(root, env, "import loop_prompts, loop_policy, loop_judge, loop_run\n"
                "print(loop_prompts.judge_prompt('_private/notes/2026-11-01', 'notes', root='.'))\n"
                "print('tools/loop/notes_cycle.sh' in loop_policy.LOOP_TOOLS)\n"
                "import os\n"
                "ctx = type('Ctx', (), {'cyc': os.path.abspath('_private/notes/2026-11-02'), 'source': 'notes', 'root': '.'})\n"
                "try:\n    loop_judge.check_input(ctx)\nexcept Exception as e:\n    print('refused:', e)\n")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "- Notes review: `_private/notes/2026-11-01/REVIEW.md`" in r.stdout, r.stdout
        assert "\nTrue\n" in r.stdout and "refused: judge: the notes collection failed" in r.stdout, r.stdout
        W.write(root, "_private/notes/state.json", json.dumps({"last_cycle": "2026-11-02", "status": "failed"}))
        r = W.run(root, env, "loop/loop_watchdog.py", "--dry", "--no-auth")
        assert "[notes-failed] notes cycle failed" in r.stdout, r.stdout + r.stderr


def test_a_broken_source_module_stops_the_loop_with_its_path():
    with W.instance() as (root, env):
        W.write(root, "tools/loop/sources/broken.py", 'NAME = "other"\n')
        r = W.run(root, env, "loop/loops.py", "status")
        assert r.returncode != 0 and "broken.py: an added source must define" in r.stderr, r.stdout + r.stderr


TESTS = [
    test_an_added_source_is_known_listed_judged_and_watched,
    test_a_broken_source_module_stops_the_loop_with_its_path,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print("PASS", test.__name__)
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print("FAIL", test.__name__, type(error).__name__, str(error)[:400])
    print(f"loop sources: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
