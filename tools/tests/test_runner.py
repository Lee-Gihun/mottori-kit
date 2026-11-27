#!/usr/bin/env python3
"""Pin the contract of tools/tests/run.py, the one list of suites CI uses."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "tests" / "run.py"
OWNER_ENV = ("MOTTORI_INSTANCE", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL", "CODEX_HOME",
             "MOTTORI_DISABLE_HOOKS")
# The passing probe fails unless the runner gave it an empty HOME, a closed stdin and none of the
# variables that point at the owner's instance or configuration.
PASSING = (
    "import os, sys\n"
    f"leaked = [k for k in {OWNER_ENV!r} if k in os.environ]\n"
    "assert not leaked, leaked\n"
    "home = os.environ['HOME']\n"
    "assert os.path.isdir(home) and not os.listdir(home), home\n"
    "assert sys.stdin.read() == ''\n"
    "here = os.path.realpath(os.path.abspath(__file__))\n"
    "assert os.path.realpath(os.getcwd()) == os.path.dirname(os.path.dirname(os.path.dirname(here)))\n"
    "print('probe ok')\n"
)
# Undecodable bytes must not cost the failing file its line.
FAILING = ("import sys\nsys.stdout.buffer.write(b'\\xff\\n')\n"
           "print('the failing check says why')\nraise SystemExit(3)\n")
# Defines three tests and runs two; the third is skipped by its skip mark, which still counts as
# run. test_left_out is in no run list, so the runner must fail the file and name it.
PARTIAL = (
    "from testlib import skip_unless\n"
    "def test_listed():\n    pass\n"
    "@skip_unless(lambda: False, 'nothing')\n"
    "def test_skipped():\n    raise AssertionError('a skipped test ran')\n"
    "def test_left_out():\n    pass\n"
    "def helper_not_a_test():\n    pass\n"
    "if __name__ == '__main__':\n"
    "    for test in (test_listed, test_skipped):\n        test()\n"
)


MODEL_PROGRAMS = ("claude", "codex", "agy", "opencode", "ollama", "gemini")
# Tries to start each model program by name and through the worker variable; the helper shares
# their folder and must still run.
REACHING = (
    "import os, shutil, subprocess\n"
    f"for name in {MODEL_PROGRAMS!r}:\n"
    "    assert shutil.which(name) is None, shutil.which(name)\n"
    "    try:\n"
    "        subprocess.run([name], timeout=10)\n"
    # Inside the loop's sandbox a PATH folder the sandbox does not let it look in answers "not
    # permitted" instead of "not found"; either way no model program started.
    "    except (FileNotFoundError, PermissionError):\n"
    "        pass\n"
    "assert 'MOTTORI_FRESH_WORKER_CODEX_BIN' not in os.environ\n"
    "assert subprocess.run(['helper'], capture_output=True, text=True).stdout == 'helper ran\\n'\n"
)


def fixture(parent: Path) -> Path:
    root = parent / "tree"
    (root / "tools" / "tests").mkdir(parents=True)
    shutil.copy2(RUNNER, root / "tools" / "tests" / "run.py")
    # The runner reads the skip mark from testlib, which every test file imports too.
    shutil.copy2(RUNNER.parent / "testlib.py", root / "tools" / "tests" / "testlib.py")
    (root / "tools" / "tests" / "test_a.py").write_text(PASSING, encoding="utf-8")
    (root / "tools" / "tests" / "test_b.py").write_text(FAILING, encoding="utf-8")
    return root


def runner(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, **{name: "/owner" for name in OWNER_ENV})
    return subprocess.run([sys.executable, str(root / "tools" / "tests" / "run.py"), *args],
                          cwd=str(root), env=env, capture_output=True, text=True, timeout=120)


def test_one_line_per_file_and_failure_exits_nonzero():
    with tempfile.TemporaryDirectory(prefix="runner-") as tmp:
        root = fixture(Path(tmp))
        result = runner(root)
        lines = result.stdout.splitlines()
        assert result.returncode == 1, result.stdout + result.stderr
        assert any(line.startswith("PASS test_a.py") for line in lines), result.stdout
        assert any(line.startswith("FAIL test_b.py (exit 3") for line in lines), result.stdout
        assert "    the failing check says why" in lines, result.stdout
        assert lines[-1] == "test files: 1/2 passed", result.stdout


def test_names_select_a_subset_and_unknown_names_are_refused():
    with tempfile.TemporaryDirectory(prefix="runner-") as tmp:
        root = fixture(Path(tmp))
        subset = runner(root, "test_a.py")
        assert subset.returncode == 0, subset.stdout + subset.stderr
        assert "test_b.py" not in subset.stdout and subset.stdout.splitlines()[-1] == "test files: 1/1 passed"
        usage = runner(root, "--help")
        assert usage.returncode == 0 and usage.stdout.startswith("usage:"), usage.stdout + usage.stderr
        unknown = runner(root, "test_missing.py")
        assert unknown.returncode == 2 and "test_missing.py" in unknown.stderr, unknown.stdout + unknown.stderr


def test_full_entries_cannot_go_missing():
    with tempfile.TemporaryDirectory(prefix="runner-") as tmp:
        root = fixture(Path(tmp))
        (root / "tools" / "tests" / "test_b.py").unlink()
        (root / "tools" / "tests" / "test_fresh_install.sh").write_text("exit 0\n", encoding="utf-8")
        full = runner(root, "--full")
        assert full.returncode == 1, full.stdout + full.stderr
        assert "PASS test_fresh_install.sh" in full.stdout, full.stdout
        assert "FAIL test_mutation.py --full" in full.stdout, full.stdout
        assert "FAIL test_instance_shape.py --full" in full.stdout, full.stdout
        assert full.stdout.splitlines()[-1] == "test files: 2/4 passed", full.stdout
        (root / "tools" / "tests" / "test_a.py").unlink()
        empty = runner(root)
        assert empty.returncode == 2 and "no test files" in empty.stderr, empty.stdout + empty.stderr


def test_a_test_function_its_file_never_runs_fails_the_file():
    with tempfile.TemporaryDirectory(prefix="runner-") as tmp:
        root = fixture(Path(tmp))
        tests = root / "tools" / "tests"
        (tests / "test_c.py").write_text(PARTIAL, encoding="utf-8")
        result = runner(root, "test_c.py")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "FAIL test_c.py (exit 1" in result.stdout, result.stdout
        assert "    FAIL never ran: test_left_out" in result.stdout.splitlines(), result.stdout
        assert "skipped, needs nothing: test_c.py test_skipped" in result.stdout, result.stdout
        (tests / "test_c.py").write_text(PARTIAL.replace("(test_listed, test_skipped)",
                                                         "(test_listed, test_skipped, test_left_out)"),
                                         encoding="utf-8")
        result = runner(root, "test_c.py")
        assert result.returncode == 0, result.stdout + result.stderr
        # A failing file is still a failure, with its own exit status, when every test was called.
        (tests / "test_d.py").write_text("def test_only():\n    raise SystemExit(4)\n"
                                         "test_only()\n", encoding="utf-8")
        result = runner(root, "test_d.py")
        assert "FAIL test_d.py (exit 4" in result.stdout, result.stdout


def test_no_test_reaches_a_model_program_on_the_callers_path():
    with tempfile.TemporaryDirectory(prefix="runner-") as tmp:
        root = fixture(Path(tmp))
        (root / "tools" / "tests" / "test_b.py").unlink()
        (root / "tools" / "tests" / "test_a.py").write_text(REACHING, encoding="utf-8")
        bin_dir, marker = Path(tmp) / "bin", Path(tmp) / "marker"
        bin_dir.mkdir()
        for name in MODEL_PROGRAMS:
            (bin_dir / name).write_text(f"#!/bin/sh\necho {name} >> '{marker}'\n", encoding="utf-8")
        (bin_dir / "helper").write_text("#!/bin/sh\necho helper ran\n", encoding="utf-8")
        for program in bin_dir.iterdir():
            program.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                   MOTTORI_FRESH_WORKER_CODEX_BIN=str(bin_dir / "codex"))
        result = subprocess.run([sys.executable, str(root / "tools" / "tests" / "run.py")], cwd=str(root),
                                env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not marker.exists(), marker.read_text(encoding="utf-8")


if __name__ == "__main__":
    for test in (test_one_line_per_file_and_failure_exits_nonzero,
                 test_names_select_a_subset_and_unknown_names_are_refused,
                 test_full_entries_cannot_go_missing,
                 test_a_test_function_its_file_never_runs_fails_the_file,
                 test_no_test_reaches_a_model_program_on_the_callers_path):
        test()
        print("PASS " + test.__name__)
