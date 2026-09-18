#!/usr/bin/env python3
"""Deterministic mutation probes for the eight critical distribution tools.

Default mode reruns the four mutations that survived M1.  ``--full`` runs the
complete 8 tools x 3 mutation matrix.  Every mutant lives in a fresh temporary
copy; the source worktree is never edited.
"""
from dataclasses import dataclass
import os
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class Mutation:
    id: str
    tool: str
    kind: str
    old: str
    new: str
    test: str
    survivor: bool = False


MUTATIONS = (
    Mutation("memlib-compare", "tools/memlib.py", "comparison",
             "row_dt <= LEGACY_CUTOFF", "row_dt > LEGACY_CUTOFF",
             "tools/test_memlib_journal.py"),
    Mutation("memlib-return", "tools/memlib.py", "early-return",
             "def journal_visibility(track, force_private=False):\n",
             "def journal_visibility(track, force_private=False):\n    return \"private\"\n",
             "tools/test_memlib_journal.py"),
    Mutation("memlib-constant", "tools/memlib.py", "constant",
             'len(m.group("body")) > 300', 'len(m.group("body")) > 301',
             "tools/test_memlib_journal.py", True),

    Mutation("now-compare", "tools/now.py", "comparison",
             'tail.read(1) != b"\\n"', 'tail.read(1) == b"\\n"',
             "tools/test_state_runtime.py"),
    Mutation("now-return", "tools/now.py", "early-return",
             'def _assert_runtime_inputs_unchanged(scopes=("public", "private")):\n',
             'def _assert_runtime_inputs_unchanged(scopes=("public", "private")):\n    return\n',
             "tools/test_state_runtime.py"),
    Mutation("now-string", "tools/now.py", "constant",
             'M.parse_journal(visibility="private", physical_visibilities=("public",))',
             'M.parse_journal(visibility="public", physical_visibilities=("public",))',
             "tools/test_state_runtime.py"),

    Mutation("gate-compare", "tools/gate.py", "comparison",
             "declared != len(gated)", "declared == len(gated)",
             "tools/test_hook_runtime.py"),
    Mutation("gate-return", "tools/gate.py", "early-return",
             "def _issues(cmd, cwd=None, instance=None):\n",
             "def _issues(cmd, cwd=None, instance=None):\n    return set()\n",
             "tools/test_hook_runtime.py"),
    Mutation("gate-string", "tools/gate.py", "constant",
             'startswith("#issues ")', 'startswith("#issue ")',
             "tools/test_hook_runtime.py"),

    Mutation("linkcheck-compare", "tools/linkcheck.py", "comparison",
             "if TREE != ROOT:", "if TREE == ROOT:",
             "tools/test_install_checks.py", True),
    Mutation("linkcheck-return", "tools/linkcheck.py", "early-return",
             "def check():\n", "def check():\n    check.pending = []\n    return [], 0\n",
             "tools/test_install_checks.py"),
    Mutation("linkcheck-string", "tools/linkcheck.py", "constant",
             '"system/memory-config.json", "system/instance-rules.md",',
             '"system/memory-config.json", "system/instance-rule.md",',
             "tools/test_install_checks.py"),

    Mutation("doctor-compare", "tools/doctor.py", "comparison",
             "< (2, 5):", ">= (2, 5):", "tools/test_install_checks.py"),
    Mutation("doctor-return", "tools/doctor.py", "early-return",
             "def _allowed(url, allowlist):\n",
             "def _allowed(url, allowlist):\n    return True\n",
             "tools/test_install_checks.py", True),
    Mutation("doctor-constant", "tools/doctor.py", "constant",
             "< (2, 5):", "< (2, 6):", "tools/test_install_checks.py"),

    Mutation("fresh-worker-compare", "tools/fresh_worker.py", "comparison",
             "if rel in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep):",
             "if rel not in (os.curdir, os.pardir) or rel.startswith(os.pardir + os.sep):",
             "tools/test_fresh_worker.py"),
    Mutation("fresh-worker-return", "tools/fresh_worker.py", "early-return",
             "    def link_escapes(path):\n",
             "    def link_escapes(path):\n        return False\n",
             "tools/test_fresh_worker.py"),
    Mutation("fresh-worker-constant", "tools/fresh_worker.py", "constant",
             "WRAPPER_RESULT_MISSING = 3", "WRAPPER_RESULT_MISSING = 2",
             "tools/test_fresh_worker.py"),

    Mutation("install-hooks-compare", "tools/install_hooks.sh", "comparison",
             '[[ "$STATUS" == "current" && "$PUSH_STATUS" == "current" ]]',
             '[[ "$STATUS" != "current" && "$PUSH_STATUS" == "current" ]]',
             "tools/test_install_hooks.py"),
    Mutation("install-hooks-return", "tools/install_hooks.sh", "early-return",
             "classify() {\n", 'classify() {\n  echo "current"\n  return\n',
             "tools/test_install_hooks.py"),
    Mutation("install-hooks-string", "tools/install_hooks.sh", "constant",
             'HOOK="$DIR/pre-commit"', 'HOOK="$DIR/pre-push"',
             "tools/test_install_hooks.py"),

    Mutation("setup-compare", "setup.sh", "comparison",
             '[ "$CONTEXT" != "work" ]', '[ "$CONTEXT" == "work" ]',
             "tools/test_setup_migration.py"),
    Mutation("setup-return", "setup.sh", "early-return",
             'cd "$ROOT"\n', 'cd "$ROOT"\nexit 0\n',
             "tools/test_setup_migration.py"),
    Mutation("setup-constant", "setup.sh", "constant",
             'DEFAULT_CONTEXT="work"', 'DEFAULT_CONTEXT="personal"',
             "tools/test_setup_migration.py", True),
)


def _copy_repo(destination):
    shutil.copytree(
        ROOT, destination,
        ignore=shutil.ignore_patterns(".git", "state", "_private", "__pycache__", "*.pyc"),
    )
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)


def _apply(root, mutation):
    path = os.path.join(root, mutation.tool)
    text = open(path, encoding="utf-8").read()
    count = text.count(mutation.old)
    if count != 1:
        raise AssertionError(f"{mutation.id}: mutation anchor occurs {count} times")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text.replace(mutation.old, mutation.new, 1))


def _run_test(root, test):
    env = dict(os.environ, MOTTORI_INSTANCE=root, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, test], cwd=root, env=env,
        capture_output=True, text=True, timeout=90,
    )


def run_mutation(mutation):
    parent = tempfile.mkdtemp(prefix=f"mutation-{mutation.id}-")
    clone = os.path.join(parent, "repo")
    try:
        _copy_repo(clone)
        _apply(clone, mutation)
        result = _run_test(clone, mutation.test)
        if result.returncode == 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
            return False, " | ".join(tail)
        return True, (result.stdout + result.stderr).strip().splitlines()[-1]
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def main():
    full = "--full" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv[:-1] else None
    selected = MUTATIONS if full else tuple(m for m in MUTATIONS if m.survivor)
    if only is not None:
        selected = tuple(m for m in MUTATIONS if m.id == only)
        if not selected:
            print(f"unknown mutation: {only}")
            return 2
    caught = 0
    for mutation in selected:
        detected, detail = run_mutation(mutation)
        caught += int(detected)
        print(f"{'CAUGHT' if detected else 'SURVIVED'} {mutation.id} "
              f"({mutation.tool}, {mutation.kind})"
              + (f": {detail}" if not detected else ""))
    mode = "single" if only is not None else ("full" if full else "M1-survivor smoke")
    print(f"mutation ({mode}): {caught}/{len(selected)} caught")
    return 0 if caught == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(run_test(main, __file__))
