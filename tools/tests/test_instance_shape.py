#!/usr/bin/env python3
"""Exercise the engine inside the shape of a long-lived installed instance.

A plain run builds the instance, runs the commands an installed instance relies on, and checks that
they catch an engine broken in a copy of it. --full runs every engine test file inside the instance: in an
installation, the test files the kit ships (system/dev/kit-files.txt), not the ones the installation added.
"""
from __future__ import annotations

# doctor in the installed shape loads the configuration and runs a real PreCompact hook that
# appends a journal row, so this file is the end-to-end proof of these two modules:
# CRITICAL_E2E tools/lib/config.py
# CRITICAL_E2E tools/lib/journal.py

import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
# Kit test files that need the kit tree itself (setup.sh, templates/, the whole tree, the rules table,
# the model page) and so have no place in an installed instance; every other tracked file under tools/
# is engine.
KIT_ONLY_TESTS = frozenset({
    "tests/test_devtree_gate.py", "tests/test_fresh_install.sh", "tests/test_instance_shape.py",
    "tests/test_language.py", "tests/test_model_assumptions.py", "tests/test_mutation.py",
    "tests/test_permissions.py", "tests/test_portability.py",
    "tests/test_rules_table.py", "tests/test_runner.py", "tests/test_setup_migration.py",
    "tests/test_skill_parity.py", "tests/test_tool_coverage.py",
})
HANGUL = re.compile(r"[\uac00-\ud7a3]")


class ShapeFailure(RuntimeError):
    pass


def fail(assumption: str, detail: str) -> None:
    line = " ".join((detail or "no detail").strip().split())
    raise ShapeFailure(f"{assumption}: {line[:360]}")


def engine_names() -> list[str]:
    """The tracked files under tools/, as paths below it, without the kit-only tests."""
    listed = subprocess.run(["git", "ls-files", "-z", "tools"], cwd=ROOT, capture_output=True, text=True)
    if listed.returncode:
        fail("engine files", "git ls-files: " + listed.stderr)
    names = sorted(path[len("tools/"):] for path in listed.stdout.split("\0") if path)
    missing = sorted(KIT_ONLY_TESTS - set(names))
    if missing:
        fail("engine files", "kit-only tests not tracked: " + ", ".join(missing))
    return [name for name in names if name not in KIT_ONLY_TESTS]


def environment() -> dict[str, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MOTTORI_INTERNAL_RUN="1")
    env.pop("MOTTORI_INSTANCE", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def run(root: Path, *command: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=root, env=environment(), text=True,
                              capture_output=True, timeout=timeout, check=False,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as error:
        fail("subprocess timeout", " ".join(command) + f" after {error.timeout}s")


INSTANCE_IGNORES = ["/_private/", "state/hook-canary.json", "state/.hook-errors.log",
                    "state/.hook-errors.seen"]


def require_ok(label: str, result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode:
        tail = (result.stdout + "\n" + result.stderr).strip().splitlines()[-3:]
        fail(label, f"exit={result.returncode} " + " | ".join(tail))


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = run(root, "git", *args)
    require_ok("git " + " ".join(args), result)
    return result


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_config() -> dict:
    return {
        "schema_version": 4,
        "instance": {"name": "shape-fixture"},
        "egress": {"model_send": {"deny_prefixes": ["_private/"], "allow_prefixes": []}},
        "episodic_sources": [],
        "tracks": [{"key": "공유", "name": "한국어 트랙", "canonical": "tracks/work.md", "also": []}],
        "personal_pointer": None,
        "journal_visibility": {
            "public_tracks": ["system", "공유"],
            "legacy_cutoff": None,
            "legacy_public_tracks": [],
        },
        "threads": [],
        "checks": {
            "linkcheck_exclude_prefixes": ["archive/"],
            "hubs": [],
            "hub_ignore_ext": [".pyc", ".DS_Store"],
            "status_docs": [],
        },
        "journal_types": ["decision", "state", "artifact", "correction", "lesson", "switch", "idea"],
        "thresholds": {
            "now_tail_events": 12,
            "now_recent_decisions": 8,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_max_bytes": 6000,
            "now_hook_max_bytes": 6000,
        },
    }


def build_fixture(parent: Path, names: list[str]) -> Path:
    root = parent / "installed instance"
    (root / "tools").mkdir(parents=True)
    for name in names:
        (root / "tools" / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "tools" / name, root / "tools" / name)

    # The loop's templates and its document are engine files under system/; its tools read them there.
    shutil.copytree(ROOT / "system" / "loop", root / "system" / "loop")

    for rel in (Path(".claude/settings.json"), Path(".codex/hooks.json"), Path(".agents/hooks.json")):
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, destination)

    # Hooks rewrite these state files on every run; an installed instance ignores them so they never
    # show as untracked (tools/tests/test_hook_runtime.py checks this).
    write(root / ".gitignore", "\n".join(INSTANCE_IGNORES) + "\n")
    write(root / "AGENTS.md", "# Synthetic instance rules\n")
    write(root / "CLAUDE.md", "@AGENTS.md\n")
    write(root / "instance/config.json",
          json.dumps(fixture_config(), ensure_ascii=False, indent=2) + "\n")
    write(root / "instance/decisions.md", "# 결정 기록\n\n가짜 구조 데이터다.\n")
    write(root / "instance/rules.md", "# Instance rules\n\nFixture only.\n")
    write(root / "instance/rituals.md", "# Local rituals\n\nFixture only.\n")
    write(root / "tracks/work.md", "# 한국어 트랙\n\n마지막 갱신: 2026-09-18\n한국어 사용자 데이터다.\n")
    write(root / "archive/target.txt", "historical target\n")
    os.symlink("target.txt", root / "archive/legacy.md")

    month = datetime.datetime.now().strftime("%Y-%m")
    write(root / "state" / f"journal-{month}.md",
          "# journal\n\n- 2026-09-18T05:00:00+09:00 [공유/state] 한국어 저널 데이터\n")
    rendered = run(root, sys.executable, "tools/now.py", "render")
    require_ok("render tracked NOW", rendered)
    if (root / "_private").exists():
        fail("private absence", "NOW rendering created _private")

    git(root, "init", "-q")
    git(root, "config", "user.name", "shape-fixture")
    git(root, "config", "user.email", "shape@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "synthetic installed instance")
    write(root / "history.txt", "second commit keeps the symlink in history\n")
    git(root, "add", "history.txt")
    git(root, "commit", "-qm", "later instance history")

    if (root / "setup.sh").exists() or (root / "templates").exists():
        fail("installed shape", "setup.sh or templates exists")
    ignored = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    if ignored != INSTANCE_IGNORES:
        fail("installed shape", f"unexpected ignore rules: {ignored!r}")
    if (root / "_private").exists():
        fail("installed shape", "_private exists")
    tracked = set(git(root, "ls-files").stdout.splitlines())
    required = {
        "instance/config.json", "instance/decisions.md", "state/NOW.md",
        f"state/journal-{month}.md", "archive/legacy.md",
    }
    if not required <= tracked:
        fail("installed shape", "untracked required paths: " + ", ".join(sorted(required - tracked)))
    mode = git(root, "ls-files", "-s", "archive/legacy.md").stdout.split()[0]
    if mode != "120000":
        fail("installed shape", f"legacy Markdown path mode={mode}")
    return root


def install_gate_baseline(root: Path) -> None:
    baseline = run(root, sys.executable, "tools/gate.py", "baseline")
    require_ok("gate baseline", baseline)
    hooks = run(root, "bash", "tools/install_hooks.sh", "--repair")
    require_ok("hook installation", hooks)


def run_regressions(root: Path, names: list[str]) -> int:
    from testlib import engine_tests, kit_paths
    tests = engine_tests(names, kit_paths(ROOT))
    for name in tests:
        result = run(root, sys.executable, "tools/" + name, timeout=360)
        require_ok("engine regression " + name, result)
    return len(tests)


def run_required_commands(root: Path) -> None:
    doctor = run(root, sys.executable, "tools/doctor.py", timeout=600)
    require_ok("doctor installed shape", doctor)
    if HANGUL.search(doctor.stdout):
        fail("English engine output boundary", "Hangul leaked from Korean user data into doctor stdout")

    # Every tool finds the instance through tools/lib/paths.py; the installed copy must name this folder.
    located = run(root, sys.executable, "-c",
                  "import sys; sys.path.insert(0, 'tools/lib'); import paths; print(paths.instance_root())")
    require_ok("instance root from tools/lib/paths.py", located)
    if Path(located.stdout.strip()).resolve() != root.resolve():
        fail("instance root", located.stdout.strip() + " is not " + str(root))

    status = run(root, sys.executable, "tools/gate.py")
    require_ok("gate status installed shape", status)

    issues = run(root, sys.executable, "tools/enforce.py", "--issues", "--index", "--root", str(root))
    require_ok("index enforcement measurement", issues)
    forbidden = ("new-instance-path:state/" in issues.stdout
                 or "new-instance-path:instance/config.json" in issues.stdout
                 or "index-markdown-symlink:archive/legacy.md" in issues.stdout)
    if forbidden:
        fail("tracked state and legacy symlink", issues.stdout)

    precommit = run(root, sys.executable, "tools/gate.py", "precommit", timeout=300)
    require_ok("gate precommit installed shape", precommit)

    prepush = run(root, sys.executable, "tools/enforce.py", "prepush")
    require_ok("instance prepush", prepush)


def clone_fixture(source: Path, parent: Path, name: str) -> Path:
    destination = parent / name
    shutil.copytree(source, destination, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return destination


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        fail(label, f"mutation seam count={text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def caught_by_commands(mutant: Path, label: str) -> bool:
    """True when run_required_commands rejects the mutant with a failure under the given label."""
    try:
        run_required_commands(mutant)
    except ShapeFailure as error:
        return str(error).startswith(label + ":")
    return False


# Where a probe inserts code: the first line of doctor's main.
DOCTOR_MAIN = "def main():\n    results.clear()\n"


def mutation_probes(root: Path, parent: Path) -> list[tuple[str, bool]]:
    """Break the engine in copies of the fixture and return (probe, caught) for each copy."""
    probes: list[tuple[str, bool]] = []

    # An engine that reads its config from the kit's templates/ must fail in the installed shape.
    mutant = clone_fixture(root, parent, "mutant-templates")
    replace_once(mutant / "tools/lib/paths.py",
                 'config_file = _in(instance, "config.json")',
                 'config_file = _in(lambda root: _at(root, "templates"), "config.json")',
                 "templates assumption")
    probes.append(("templates required", caught_by_commands(mutant, "doctor installed shape")))

    # An engine that needs the kit's installer must fail in the installed shape.
    mutant = clone_fixture(root, parent, "mutant-setup")
    replace_once(mutant / "tools/doctor.py", DOCTOR_MAIN,
                 DOCTOR_MAIN + "    if not os.path.isfile(os.path.join(ROOT, \"setup.sh\")):\n"
                 "        sys.exit(1)\n",
                 "setup.sh assumption")
    probes.append(("setup.sh required", caught_by_commands(mutant, "doctor installed shape")))

    # The fixture's user data is Korean, so an engine that prints it breaks the English boundary.
    mutant = clone_fixture(root, parent, "mutant-language")
    replace_once(mutant / "tools/doctor.py", DOCTOR_MAIN,
                 DOCTOR_MAIN + "    print(open(os.path.join(ROOT, \"tracks\", \"work.md\"), "
                 "encoding=\"utf-8\").read())\n",
                 "user language assumption")
    probes.append(("English boundary sees user data",
                   caught_by_commands(mutant, "English engine output boundary")))

    mutant = clone_fixture(root, parent, "mutant-state")
    path = mutant / "tools/enforce.py"
    replace_once(path,
                 "if folded.startswith(FORBIDDEN_PREFIXES):\n"
                 "        if has_head:\n",
                 "if folded.startswith(FORBIDDEN_PREFIXES):\n"
                 "        return True\n"
                 "        if has_head:\n",
                 "tracked state assumption")
    result = run(mutant, sys.executable, "tools/enforce.py", "--issues", "--index", "--root", str(mutant))
    probes.append(("tracked state forbidden", "new-instance-path:state/NOW.md" in result.stdout))

    mutant = clone_fixture(root, parent, "mutant-symlink")
    path = mutant / "tools/enforce.py"
    replace_once(path,
                 "if mode == \"120000\" and path in changed and path.lower().endswith(\".md\"):",
                 "if mode == \"120000\" and path.lower().endswith(\".md\"):",
                 "historical symlink assumption")
    result = run(mutant, sys.executable, "tools/enforce.py", "--issues", "--index", "--root", str(mutant))
    probes.append(("historical Markdown symlink forbidden",
                   "index-markdown-symlink:archive/legacy.md" in result.stdout))

    mutant = clone_fixture(root, parent, "mutant-prepush")
    (mutant / "instance/config.json").unlink()
    # Instance files beside the installer would make it a damaged instance, not a pre-setup kit.
    (mutant / "instance/rules.md").unlink(missing_ok=True)
    for folder in ("state", "_private/state"):
        shutil.rmtree(mutant / folder, ignore_errors=True)
    write(mutant / "setup.sh", "#!/usr/bin/env bash\n")
    write(mutant / "templates/config.json", "{}\n")
    control = run(mutant, sys.executable, "tools/enforce.py", "prepush")
    path = mutant / "tools/enforce.py"
    replace_once(path,
                 "    return rules + P.state_evidence(root) + legacy\n",
                 "    return rules + P.state_evidence(root) + legacy + [C.CONFIG_NAME]\n",
                 "pre-setup kit assumption")
    result = run(mutant, sys.executable, "tools/enforce.py", "prepush")
    probes.append(("configless kit push blocked", control.returncode == 0 and result.returncode != 0))

    return probes


def main(argv: list[str]) -> int:
    """Check the installed shape; with --full, run every engine test file inside it instead."""
    full = argv == ["--full"]
    if argv and not full:
        print("usage: test_instance_shape.py [--full]")
        return 2
    try:
        names = engine_names()
        with tempfile.TemporaryDirectory(prefix="instance-shape-") as temporary:
            parent = Path(temporary)
            fixture = build_fixture(parent, names)
            install_gate_baseline(fixture)
            if full:
                regression_count = run_regressions(fixture, names)
            else:
                run_required_commands(fixture)
                probes = mutation_probes(fixture, parent)
                missed = [name for name, detected in probes if not detected]
                if missed:
                    fail("mutation detection", ", ".join(missed))
        print(f"engine files: {len(names)} tracked under tools/")
        if full:
            print(f"installed regressions: PASS {regression_count}/{regression_count}")
        else:
            print("installed commands: PASS doctor (English), instance root, gate status, "
                  "gate precommit, enforce prepush")
            for name, _detected in probes:
                print("mutation probe: DETECTED " + name)
            print(f"mutation probes: PASS {len(probes)}/{len(probes)}")
        print("instance shape: PASS")
        return 0
    except ShapeFailure as error:
        print("instance shape: FAIL " + str(error))
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"instance shape: FAIL unexpected {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
