#!/usr/bin/env python3
"""A skipped test is not a passed test: the suite runner and the loop's test summary count skips
apart from passes and name each reason once."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest import mock

import testlib

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_checks as LK  # noqa: E402
import run as RUN  # noqa: E402

# A test file whose second test was skipped, as testlib's skip helpers print it.
SKIPPING = """
print("✓ test_one")
print("- skipped test_two: needs a pseudo-terminal")
print("✓ test_two")
print("- skipped test_three: needs a pseudo-terminal")
print("✓ test_three")
"""
PLAIN = 'print("✓ test_one")\n'
# A test file that skipped one test and failed another.
FAILING = """
print("- skipped test_two: needs a pseudo-terminal")
print("✓ test_two")
print("✗ test_three: boom")
raise SystemExit(1)
"""


def files(base):
    paths = {}
    for name, body in (("test_skipping.py", SKIPPING), ("test_plain.py", PLAIN)):
        paths[name] = os.path.join(base, name)
        with open(paths[name], "w", encoding="utf-8") as f:
            f.write(body)
    return paths


def test_the_runner_counts_skips_apart_and_names_the_reason_once():
    base = tempfile.mkdtemp(prefix="loop-skips-")
    try:
        paths = files(base)
        rows = [(name, [sys.executable, path], {}) for name, path in sorted(paths.items())]
        out = io.StringIO()
        with mock.patch.object(RUN, "suites", lambda names=(), full=False: rows), contextlib.redirect_stdout(out):
            code = RUN.main([])
        lines = out.getvalue().splitlines()
        assert code == 0, lines
        assert lines[-1] == "test files: 1/2 passed, 1 ran with skipped tests (2 skipped)", lines
        reasons = [line for line in lines if "pseudo-terminal" in line]
        assert reasons == ["skipped, needs a pseudo-terminal: test_skipping.py test_two, test_three"], lines
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_loops_test_summary_counts_skips_apart():
    base = tempfile.mkdtemp(prefix="loop-skips-")
    try:
        paths = files(base)
        iso = SimpleNamespace(tree=base, command=lambda argv, stage="verify": argv, env=lambda: dict(os.environ))
        res = LK.run_tests(iso, sorted(paths.values()))
        skipping = res["test_skipping.py"]
        assert skipping["passes"] == ["test_one"], skipping
        assert skipping["skips"] == [["test_two", "a pseudo-terminal"], ["test_three", "a pseudo-terminal"]], skipping
        assert LK.summarize_tests(res) == "2 of 2 test files passed, 2 tests skipped (needs a pseudo-terminal)", LK.summarize_tests(res)
        assert LK.summarize_tests({"test_plain.py": res["test_plain.py"]}) == "1 of 1 test files passed, 0 tests skipped"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_runner_counts_the_skips_of_a_file_that_failed():
    base = tempfile.mkdtemp(prefix="loop-skips-")
    try:
        rows = []
        for name, body in (("test_failing.py", FAILING), ("test_plain.py", PLAIN)):
            with open(os.path.join(base, name), "w", encoding="utf-8") as f:
                f.write(body)
            rows.append((name, [sys.executable, os.path.join(base, name)], {}))
        out = io.StringIO()
        with mock.patch.object(RUN, "suites", lambda names=(), full=False: rows), contextlib.redirect_stdout(out):
            code = RUN.main([])
        lines = out.getvalue().splitlines()
        assert code == 1, lines
        assert lines[-1] == "test files: 1/2 passed, 1 ran with skipped tests (1 skipped)", lines
        assert "skipped, needs a pseudo-terminal: test_failing.py test_two" in lines, lines
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_the_http_stand_ins_give_the_test_its_connection_function_back():
    import socket
    own = socket.create_connection
    with testlib.http_stand_ins():
        assert getattr(socket.create_connection, "stand_in", False), "the block did not route connections"
    assert socket.create_connection is own, "the stand-in connection function stayed after the block"


TESTS = [
    test_the_runner_counts_skips_apart_and_names_the_reason_once,
    test_the_loops_test_summary_counts_skips_apart,
    test_the_runner_counts_the_skips_of_a_file_that_failed,
    test_the_http_stand_ins_give_the_test_its_connection_function_back,
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
    print(f"loop_skips: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
