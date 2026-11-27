#!/usr/bin/env python3
"""Subprocess smoke/negative pairs for thin or optional distribution entrypoints."""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = sys.executable


def run(*args, env=None):
    return subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)


def _python_help(path, env=None):
    positive = run(PY, path, "--help", env=env)
    assert positive.returncode == 0, positive.stdout + positive.stderr
    negative = run(PY, path, "--definitely-unknown-option", env=env)
    assert negative.returncode != 0, negative.stdout + negative.stderr


def test_stdlib_cli_help_and_negative_options():
    _python_help("tools/dev/eval_recall.py")


def test_the_loops_entry_points_answer_help_and_start_nothing():
    """--help on a cycle script used to start a cycle with model runs; now each one prints its usage."""
    with tempfile.TemporaryDirectory(prefix="loop-help-") as td:
        env = dict(os.environ, MOTTORI_INSTANCE=td, PATH="/usr/bin:/bin")
        for command in (["bash", "tools/loop/papers_cycle.sh", "-h"],
                        [PY, "tools/loop/loops.py", "-h"],
                        [PY, "tools/loop/papers/fetch_arxiv.py", "--help"]):
            result = run(*command, env=env)
            assert result.returncode == 0 and ("Usage" in result.stdout or "python3 tools/loop/loops.py" in result.stdout), \
                (command, result.stdout, result.stderr)
            assert not os.listdir(td), (command, os.listdir(td))


def test_person_ledger_normal_and_unknown_command():
    """Run against a synthetic instance so the live journal and ledger are never read, and check
    that the stale warning fires exactly at the threshold. The threshold decision lives in doctor's
    person ledger check since stale stopped taking --issues, so that check is the one asked."""
    for count, expected in ((20, "WARN"), (19, "PASS")):
        with tempfile.TemporaryDirectory(prefix="person-ledger-") as td:
            root = pathlib.Path(td)
            (root / "_private").mkdir()
            (root / "state").mkdir()
            (root / "_private" / "self-portrait-mirror.md").write_text("last-reviewed: 2026-01-01\n", encoding="utf-8")
            lines = "".join(f"- 2026-01-02T10:00:{i:02d}+00:00 [system/correction] item {i}\n" for i in range(count))
            (root / "state" / "journal-2026-01.md").write_text(lines, encoding="utf-8")
            env = dict(os.environ, MOTTORI_INSTANCE=td)
            positive = run(PY, "tools/person_ledger.py", "stale", env=env)
            assert positive.returncode == 0, positive.stdout + positive.stderr
            assert _person_ledger_pending(positive.stdout) == count, positive.stdout
            check = run(PY, "-c", "import sys; sys.path.insert(0, 'tools'); import doctor; "
                        "print(doctor.c_person_ledger()[0])", env=env)
            assert check.returncode == 0, check.stdout + check.stderr
            assert check.stdout.strip().splitlines()[-1] == expected, check.stdout
    with tempfile.TemporaryDirectory(prefix="person-ledger-") as td:
        env = dict(os.environ, MOTTORI_INSTANCE=td)
        negative = run(PY, "tools/person_ledger.py", "not-a-command", env=env)
        no_ledger = [run(PY, "tools/person_ledger.py", cmd, env=env).stdout for cmd in ("stale", "candidates")]
    assert negative.returncode == 2
    assert no_ledger[0] == no_ledger[1] and "None" not in no_ledger[1], no_ledger
    assert not re.search(r"[\uac00-\ud7a3]", no_ledger[0]), no_ledger  # output follows the instance language


def _person_ledger_root(td, ledger, public=(), private=()):
    """Build a synthetic instance with a person ledger and public/private journals."""
    os.makedirs(os.path.join(td, "state"))
    os.makedirs(os.path.join(td, "_private", "state"))
    with open(os.path.join(td, "_private", "self-portrait-mirror.md"), "w", encoding="utf-8") as f:
        f.write(ledger)
    for rel, lines in (("state", public), ("_private/state", private)):
        with open(os.path.join(td, rel, "journal-2026-10.md"), "w", encoding="utf-8") as f:
            f.write("".join(lines))
    return dict(os.environ, MOTTORI_INSTANCE=td)


def _person_ledger_pending(stdout):
    """Read the pending count from the first stale line in either language: the first number that is
    not part of the date, since the threshold always follows it."""
    nums = re.findall(r"(?<![\d-])\d+(?![\d-])", stdout.splitlines()[0])
    return int(nums[0]) if nums else None


def test_person_ledger_reads_private_journal():
    """Personal decisions and corrections are logged privately; the staleness count must include them."""
    with tempfile.TemporaryDirectory(prefix="person-ledger-private-") as td:
        env = _person_ledger_root(
            td, "# ledger\nlast-reviewed: 2026-09-06\n",
            public=["- 2026-10-01T10:00+00:00 [kit/decision] public one\n"],
            private=[f"- 2026-10-02T10:{i:02d}+00:00 [life/correction] private {i}\n" for i in range(25)])
        out = run(PY, "tools/person_ledger.py", "stale", env=env)
        assert out.returncode == 0, out.stdout + out.stderr
        assert _person_ledger_pending(out.stdout) == 26, out.stdout


def test_person_ledger_ignores_future_dates():
    """Only the last-reviewed line sets the start: a deadline or a past date in the prose does not, the
    review day itself is included, and without the line the tool asks for a start instead of guessing."""
    journal = ["- 2026-09-06T22:00+00:00 [kit/correction] later on the review day\n",
               "- 2026-10-01T10:00+00:00 [kit/decision] one\n"]
    with tempfile.TemporaryDirectory(prefix="person-ledger-future-") as td:
        env = _person_ledger_root(
            # A review line after today and one naming no real day are slips, not reviews.
            td, "# ledger\nlast-reviewed: 2026-09-06\nlast-reviewed: 2099-01-01\nlast-reviewed: 2026-09-31\n"
                "deadline 2099-03-01\nrenewal was 2026-09-30\n",
            public=journal)
        out = run(PY, "tools/person_ledger.py", "stale", env=env)
        assert out.returncode == 0, out.stdout + out.stderr
        assert "2026-09-06" in out.stdout.splitlines()[0], out.stdout
        assert _person_ledger_pending(out.stdout) == 2, out.stdout
    with tempfile.TemporaryDirectory(prefix="person-ledger-unreviewed-") as td:
        env = _person_ledger_root(td, "# ledger\nupdated 2026-09-06\n", public=journal)
        for cmd in ("stale", "candidates"):
            out = run(PY, "tools/person_ledger.py", cmd, env=env)
            assert out.returncode == 1 and "last-reviewed: YYYY-MM-DD" in out.stdout, out.stdout
        given = run(PY, "tools/person_ledger.py", "candidates", "2026-09-06", env=env)
        assert given.returncode == 0 and "later on the review day" in given.stdout, given.stdout
        for bad in (("candidates", "2026-9-6"), ("candidates", "06-09-2026"), ("stale", "--issues")):
            refused = run(PY, "tools/person_ledger.py", *bad, env=env)
            assert refused.returncode == 2 and "candidates [YYYY-MM-DD]" in refused.stdout, (bad, refused.stdout)


def _ask_codex_root(td):
    """Copy ask_codex.sh into a scratch instance whose fresh worker only leaves a marker, so a
    regression in mode parsing cannot start a real Codex job or write the real dispatch log."""
    marker = pathlib.Path(td, "inst", "worker-called")
    root = _ask_codex_instance(td, f"open({str(marker)!r}, 'w').close()\n")
    return root, marker


def _assert_nothing_dispatched(root, marker):
    assert not marker.exists(), "fresh worker was started"
    assert not (root / "state" / "debate-dispatch.log").exists(), "dispatch log was written"


def test_ask_codex_has_no_root_thread_lookup():
    """Resume was removed: neither --resume-root nor --resume reaches codex or the worker."""
    with tempfile.TemporaryDirectory(prefix="ask-codex-resume-") as td:
        prompt = pathlib.Path(td, "prompt.md")
        prompt.write_text("prompt\n", encoding="utf-8")
        marker = pathlib.Path(td, "codex-called")
        fake_bin = pathlib.Path(td, "bin")
        fake_bin.mkdir()
        fake = fake_bin / "codex"
        fake.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        fake.chmod(0o755)
        env = dict(os.environ, HOME=td, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
        root, worker = _ask_codex_root(td)
        for extra in (["--resume-root"], ["--resume", "SID"]):
            result = subprocess.run(["bash", "tools/ask_codex.sh", str(prompt), *extra], cwd=root,
                                    env=env, capture_output=True, text=True, timeout=20)
            assert result.returncode == 1, result.stdout + result.stderr
            assert "usage" in result.stdout.lower(), result.stdout
            assert "--resume" not in result.stdout, result.stdout
            assert not marker.exists()
            _assert_nothing_dispatched(root, worker)
        assert not (ROOT / "tools" / "codex_root_thread.py").exists()


def test_ask_codex_logs_a_failed_fresh_run():
    """A failed fresh dispatch leaves FAILED in the log, so it is distinguishable from an interruption."""
    with tempfile.TemporaryDirectory(prefix="ask-codex-fail-") as td:
        root = _ask_codex_instance(td, "raise SystemExit(3)\n")
        (root / "p.md").write_text("prompt\n", encoding="utf-8")
        result = subprocess.run(["bash", "tools/ask_codex.sh", "p.md"], cwd=root,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 3, result.stdout + result.stderr
        log = (root / "state" / "debate-dispatch.log").read_text(encoding="utf-8")
        assert "FAILED fresh (exit 3)" in log and "DONE fresh" not in log, log


def _ask_codex_instance(td, worker_body):
    """A throwaway instance holding ask_codex.sh, the ask.sh it calls, and a stub worker, so no real
    Codex run starts."""
    root = pathlib.Path(td, "inst")
    (root / "tools" / "lib").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    for name in ("ask_codex.sh", "ask.sh", "lib/paths.py"):
        shutil.copy(ROOT / "tools" / name, root / "tools" / name)
    (root / "tools" / "fresh_worker.py").write_text(worker_body, encoding="utf-8")
    return root


_READ_PROMPT_STUB = """import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fresh_worker_real as F
try:
    F.read_workspace_text(sys.argv[-1])
    print("READ_OK", sys.argv[-1])
except Exception as e:
    print("REJECT", e)
    sys.exit(3)
"""


def test_ask_codex_relative_prompt_from_subfolder_and_alias():
    """A relative prompt typed in a subfolder or through a symlinked cwd reaches the real reader."""
    with tempfile.TemporaryDirectory(prefix="ask-codex-rel-") as td:
        root = pathlib.Path(td, "inst")
        shutil.copytree(ROOT / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        (root / "state").mkdir(parents=True)
        os.rename(root / "tools" / "fresh_worker.py", root / "tools" / "fresh_worker_real.py")
        (root / "tools" / "fresh_worker.py").write_text(_READ_PROMPT_STUB, encoding="utf-8")
        alias = pathlib.Path(td, "alias")
        alias.symlink_to(root)
        sub = root / "sub dir \ud3f4\ub354"
        sub.mkdir()
        (root / "p.md").write_text("prompt\n", encoding="utf-8")
        (sub / "q.md").write_text("prompt\n", encoding="utf-8")
        # An inherited instance pointing elsewhere must not redirect the prompt the script checked.
        env = dict(os.environ, MOTTORI_INSTANCE=td)
        cases = (
            (alias, root / "tools" / "ask_codex.sh", "p.md", "p.md"),
            (root, alias / "tools" / "ask_codex.sh", "p.md", "p.md"),
            (alias / sub.name, root / "tools" / "ask_codex.sh", "q.md", f"{sub.name}/q.md"),
            # An absolute prompt spelled through the symlinked checkout stays inside that checkout,
            # spelled from the physical root the script works in.
            (alias, alias / "tools" / "ask_codex.sh", str(alias / "p.md"), str(root.resolve() / "p.md")),
        )
        for cwd, script, arg, seen in cases:
            result = subprocess.run(["bash", str(script), arg], cwd=cwd, env=env,
                                    capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, (cwd, script, result.stdout + result.stderr)
            assert f"READ_OK {seen}" in result.stdout, (cwd, script, result.stdout)


def test_ask_codex_log_outcome_time():
    """The outcome line carries the time the run ended, not the time it started."""
    with tempfile.TemporaryDirectory(prefix="ask-codex-time-") as td:
        root = _ask_codex_instance(td, "import time\ntime.sleep(1.1)\n")
        (root / "p.md").write_text("prompt\n", encoding="utf-8")
        result = subprocess.run(["bash", "tools/ask_codex.sh", "p.md"], cwd=root,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        lines = (root / "state" / "debate-dispatch.log").read_text(encoding="utf-8").splitlines()
        start = next(x for x in lines if " FRESH " in x)
        done = next(x for x in lines if " DONE fresh" in x)
        assert start[:21] != done[:21], lines


def test_shell_wrappers_reject_missing_required_input():
    with tempfile.TemporaryDirectory(prefix="ask-codex-missing-") as td:
        root, worker = _ask_codex_root(td)
        ask = subprocess.run(["bash", "tools/ask_codex.sh", "absent.md"], cwd=root,
                             capture_output=True, text=True, timeout=20)
        assert ask.returncode != 0 and "prompt file missing" in ask.stdout, ask.stdout + ask.stderr
        # Arguments are checked before the prompt file: no argument is a usage error, and --help
        # prints the help and exits 0; neither starts a worker.
        ask = subprocess.run(["bash", "tools/ask_codex.sh"], cwd=root, capture_output=True, text=True,
                             timeout=20)
        assert ask.returncode == 1 and ask.stdout.startswith("usage:"), ask.stdout + ask.stderr
        ask = subprocess.run(["bash", "tools/ask_codex.sh", "--help"], cwd=root, capture_output=True,
                             text=True, timeout=20)
        assert ask.returncode == 0 and "usage: bash tools/ask_codex.sh" in ask.stdout, ask.stdout + ask.stderr
        _assert_nothing_dispatched(root, worker)


def test_ask_codex_worktree_switch_and_missing_log_folder():
    with tempfile.TemporaryDirectory(prefix="ask-codex-worktree-") as td:
        root = _ask_codex_instance(td, "import sys\nprint('ARGS', sys.argv[1:])\n")
        shutil.rmtree(root / "state")  # the log folder is created on demand
        (root / "p.md").write_text("prompt\n", encoding="utf-8")
        result = subprocess.run(["bash", "tools/ask_codex.sh", "p.md"], cwd=root,
                                env=dict(os.environ, MOTTORI_WORKTREE="1"),
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        # A bare --worktree would take the prompt path as its optional value.
        assert "'--worktree=dirty', 'p.md'" in result.stdout, result.stdout
        assert "DONE fresh" in (root / "state" / "debate-dispatch.log").read_text(encoding="utf-8")


def test_readme_lists_every_tool():
    """Each tool is named in a README kept by hand: the one in tools/, or the one in the tool's own
    folder or the folder above it. An installation lists the tools it adds in a README.local.md
    beside one of them, so the kit's own README stays the kit's. A tool added without its line fails
    here, and so does a line whose tool is gone."""
    tools = ROOT / "tools"
    if not (tools / "README.md").is_file():
        # A tree without the index has nothing to hold against its files.
        print("- tools/README.md index: not applicable here")
        return
    readmes = {folder: "\n".join((folder / name).read_text(encoding="utf-8")
                                  for name in ("README.md", "README.local.md") if (folder / name).is_file())
               for folder in [tools, *(p for p in tools.rglob("*") if p.is_dir())]
               if (folder / "README.md").is_file() or (folder / "README.local.md").is_file()}

    def named(path):
        folders = [f for f in (path.parent, path.parent.parent, tools) if f in readmes]
        return any(f"`{path.relative_to(f).as_posix()}`" in readmes[f] for f in folders)
    missing = sorted(
        path.relative_to(tools).as_posix()
        for path in [*tools.iterdir(), *tools.glob("lib/*"), *tools.glob("dev/*"), *tools.glob("tests/*"),
                     *tools.glob("loop/*"), *tools.glob("loop/lib/*")]
        if path.is_file() and path.suffix in (".py", ".sh", ".js") and not path.name.startswith("test_")
        and not named(path)
    )
    assert not missing, f"no README under tools/ names: {missing}"
    stale = sorted(f"{folder.relative_to(ROOT).as_posix()}/README: {name}"
                   for folder, text in readmes.items()
                   for name in re.findall(r"^- `([^`*]+\.(?:py|sh|js))`", text, re.M)
                   if not (folder / name).is_file())
    assert not stale, f"a README under tools/ names missing files: {stale}"


def _dev_imports(source, dev_modules):
    """Return the names a source reaches in tools/tests or tools/dev, by import or importlib call."""
    import ast
    names = []
    tree = ast.parse(source)
    loaders = {"import_module", "__import__", "spec_from_file_location", "run_path", "run_module"}
    # A path kept in a variable is read through every assignment to that name.
    assigned = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            loaders |= {alias.asname for alias in node.names if alias.name in loaders and alias.asname}
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)
    # ast.walk reaches imports inside functions too, where a lazy import would otherwise hide.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names += [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) in loaders:
            leaves = [leaf for arg in node.args for leaf in ast.walk(arg)]
            leaves += [leaf for name in leaves if isinstance(name, ast.Name)
                       for value in assigned.get(name.id, ()) for leaf in ast.walk(value)]
            names += [leaf.value for leaf in leaves
                      if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str)]
    parts = {name: name.replace("/", ".").split(".") for name in names}
    return [name for name in names if parts[name][0] in dev_modules or {"tests", "dev"} & set(parts[name])]


def test_tools_import_nothing_from_tests_or_dev():
    """Hooks run tools/*.py, so a module of tools/tests or tools/dev imported there joins the runtime."""
    dev_modules = {path.stem for folder in ("tests", "dev") for path in (ROOT / "tools" / folder).glob("*.py")}
    for source in ("import tests.testlib", "from tests import testlib", "from tools.dev import evidencecheck",
                   "import importlib\nimportlib.import_module('evidencecheck')", "__import__('testlib')",
                   "spec_from_file_location('x', join('tools', 'dev', 'x.py'))",
                   "runner = join('tools', 'tests', 'run.py')\nspec_from_file_location('x', join(ROOT, runner))",
                   "from importlib import import_module as im\nim('build_memory_map')",
                   "import runpy\nrunpy.run_path('tools/dev/evidencecheck.py')"):
        assert _dev_imports(source, dev_modules), source
    assert not _dev_imports("from subprocess import run\nimport os.path", dev_modules)
    found = [(path.name, name) for path in sorted([*(ROOT / "tools").glob("*.py"), *(ROOT / "tools").glob("lib/*.py")])
             for name in _dev_imports(path.read_text(encoding="utf-8"), dev_modules)]
    assert found == [], found


def path_block(depth):
    """The lines a file puts the kit's folders on sys.path with, from its own location. depth is
    how many folders lie between the instance root and the file: tools/x.py is 1, tools/lib/x.py 2."""
    folder = "os.path.abspath(__file__)"
    for _ in range(depth):
        folder = f"os.path.dirname({folder})"
    return (f"TOOLS = {folder}",
            'sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]')


# A further folder a file may put on sys.path besides the block: tools/dev, for the tests of the
# contributor tools.
PATH_EXTRA = ('sys.path.insert(0, os.path.join(HERE, "dev"))', 'sys.path.insert(0, os.path.join(TOOLS, "dev"))')
# The loop's folders, put on the path right after the block by a file that imports a loop module.
PATH_LOOP = ('sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib"))'
             ' if p not in sys.path]')


def path_issues(rel, source, kit_modules, dev_modules=frozenset(), loop_modules=frozenset()):
    """Return what is wrong with how the file at rel (relative to the root) finds the kit's modules.

    A tool is read whole. A test needs the lines only for what it imports at its top level, and
    inside a test function sys.path may point at the fixture tree that test builds."""
    import ast
    tree = ast.parse(source)
    own = rel.rsplit("/", 1)[-1][:-3]
    in_test = rel.startswith("tools/tests/")

    def imports(nodes, every=False):
        found = set()
        for leaf in (leaf for node in nodes for leaf in ast.walk(node)):
            if isinstance(leaf, ast.Import):
                found |= {alias.name.split(".")[0] for alias in leaf.names}
            elif isinstance(leaf, ast.ImportFrom) and leaf.module and not leaf.level:
                found.add(leaf.module.split(".")[0])
            elif isinstance(leaf, ast.Call) and getattr(leaf.func, "id", None) in ("_tool", "__import__"):
                found |= {arg.value for arg in leaf.args if isinstance(arg, ast.Constant)}
        return found if every else found & (kit_modules - {own})

    top_level = [node for node in tree.body if not isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    needs = imports(top_level if in_test else tree.body)
    top = [ast.get_source_segment(source, node) for node in tree.body]
    block = list(path_block(rel.count("/")))
    has_block = any(top[i:i + 2] == block for i in range(len(top)))
    has_loop = any(top[i:i + 3] == [*block, PATH_LOOP] for i in range(len(top)))
    issues = []
    if needs and not has_block:
        issues.append(f"{rel}: imports {sorted(needs)} without the lines {block}")
    if bool(needs & loop_modules) != has_loop:
        issues.append(f"{rel}: the loop line {PATH_LOOP} must follow the block exactly when a loop module is imported")
    if has_block and not imports(tree.body) and not (dev_modules & imports(tree.body, every=True)):
        issues.append(f"{rel}: puts the kit's folders on sys.path but imports no kit module")
    simple = (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign)
    for node in (tree.body if in_test else ast.walk(tree)):
        if isinstance(node, simple) and any(
                isinstance(leaf, ast.Attribute) and leaf.attr == "path"
                and isinstance(leaf.value, ast.Name) and leaf.value.id == "sys" for leaf in ast.walk(node)):
            line = ast.get_source_segment(source, node)
            if line not in (block[1], *PATH_EXTRA, PATH_LOOP) or (line == block[1] and not has_block):
                issues.append(f"{rel}:{node.lineno}: {line}")
    return issues


def test_every_tool_puts_the_kit_folders_on_the_path_the_same_way():
    """One spelling of the sys.path lines per folder depth, computed from the file's own place."""
    loop_modules = {path.stem for folder in ("loop", "loop/lib") for path in (ROOT / "tools" / folder).glob("*.py")}
    kit_modules = {path.stem for folder in ("", "lib") for path in (ROOT / "tools" / folder).glob("*.py")} | loop_modules
    dev_modules = {path.stem for path in (ROOT / "tools" / "dev").glob("*.py")}
    good = "import os\nimport sys\n" + "\n".join(path_block(2)) + "\nimport paths\n"
    assert not path_issues("tools/lib/x.py", good, kit_modules)
    for bad in (good.replace("dirname(os.path.dirname(", "dirname(("),  # the block of another depth
                "import sys\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport paths\n",
                "import sys\nsys.path.insert(0, 'tools')\nimport paths\n",
                good + "def f():\n    sys.path.insert(0, os.getcwd())\n",
                "import os\nimport sys\n" + "\n".join(path_block(2)) + "\n"):
        assert path_issues("tools/lib/x.py", bad, kit_modules), bad
    loopy = "import os\nimport sys\n" + "\n".join(path_block(3)) + "\n"
    for source, wrong in ((loopy + "import loop_common\n", True), (loopy + PATH_LOOP + "\nimport loop_common\n", False),
                          (loopy + PATH_LOOP + "\nimport paths\n", True)):
        assert bool(path_issues("tools/loop/lib/x.py", source, kit_modules | {"loop_common"},
                                loop_modules={"loop_common"})) == wrong, source
    issues = []
    for path in sorted((ROOT / "tools").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if not rel.startswith("tools/tests/fixtures/"):
            issues += path_issues(rel, path.read_text(encoding="utf-8"), kit_modules, dev_modules, loop_modules)
    assert not issues, "\n".join(issues)


def test_garden_command_carries_the_steps_and_stays_report_only():
    """/garden is a prompt the session's own agent follows in any runtime; no workflow file runs it."""
    command = ROOT / ".claude" / "commands" / "garden.md"
    if not command.is_file():
        # The instance-shape test's synthetic instance copies tools/ and the hook declarations only.
        print("- /garden command: not in this tree")
        return
    text = " ".join(command.read_text(encoding="utf-8").split())
    for step in ("python3 tools/now.py check", "python3 tools/now.py context", "python3 tools/now.py threads",
                 "python3 tools/recall.py find", "print(paths.transcripts())"):
        assert step in text, step
    assert "report-only" in text and "edit nothing while you audit" in text, text[:200]
    # The private half of state is audited and the report stays private.
    assert "_private/state/" in text and "unavailable, not as empty" in text
    assert "`_private/state/gardener-<today>.md`" in text and "never goes under `state/`" in text
    # The owner is asked only about the kinds the rituals name.
    assert "`## Questions for the owner` (only the kinds `system/rituals.md#memory` names)" in text
    assert "## Recommended automatic actions" in text
    assert not list((ROOT / "tools").glob("*.js")), "a workflow script is back under tools/"

TESTS = (
    test_stdlib_cli_help_and_negative_options,
    test_the_loops_entry_points_answer_help_and_start_nothing,
    test_person_ledger_normal_and_unknown_command,
    test_person_ledger_reads_private_journal,
    test_person_ledger_ignores_future_dates,
    test_ask_codex_has_no_root_thread_lookup,
    test_ask_codex_logs_a_failed_fresh_run,
    test_ask_codex_relative_prompt_from_subfolder_and_alias,
    test_ask_codex_log_outcome_time,
    test_shell_wrappers_reject_missing_required_input,
    test_ask_codex_worktree_switch_and_missing_log_folder,
    test_readme_lists_every_tool,
    test_garden_command_carries_the_steps_and_stays_report_only,
    test_tools_import_nothing_from_tests_or_dev,
    test_every_tool_puts_the_kit_folders_on_the_path_the_same_way,
)


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"tool entrypoints: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
