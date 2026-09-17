#!/usr/bin/env python3
"""Portability regression checks for the kit's shell entry points."""
import os
import re
import shutil
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHELL_FILES = [
    "setup.sh",
    "tools/install_hooks.sh",
    "tools/precommit-hook.sh",
    "tools/sync_engine.sh",
    "tools/test_fresh_install.sh",
    "tools/ask_codex.sh",
]


def source(path):
    return open(os.path.join(ROOT, path), encoding="utf-8").read()


def code_lines(text):
    """Drop blank and comment-only lines so documentation can name hazards."""
    return [(lineno, line) for lineno, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")]


def test_forbidden_patterns():
    forbidden = [
        ("sed -i", re.compile(r"\bsed\s+-i(?:\s|$)")),
        ("stat -f", re.compile(r"(?:^|[;&|]\s*)stat\s+-f(?:\s|$)")),
        ("date -v", re.compile(r"\bdate\s+-v")),
        ("fixed /tmp path", re.compile(r"/tmp/")),
        ("git hook run", re.compile(r"\bgit(?:\s+-C\s+\S+)?\s+hook\s+run\b")),
        ("git --path-format", re.compile(r"--path-format(?:=|\s)")),
        ("associative array", re.compile(r"\b(?:declare|typeset)\s+-A\b")),
        ("bash lowercase expansion", re.compile(r"\$\{[^}\n]+,,[^}\n]*\}")),
        ("bash uppercase expansion", re.compile(r"\$\{[^}\n]+\^\^[^}\n]*\}")),
        ("mapfile/readarray/coproc", re.compile(r"\b(?:mapfile|readarray|coproc)\b")),
        ("bash 4 pipe operator", re.compile(r"(?:\|&|&>>)")),
    ]
    candidates = list(SHELL_FILES)
    candidates.extend(
        os.path.join("tools", name)
        for name in os.listdir(HERE)
        if name.endswith(".py") and name != "test_portability.py"
    )
    failures = []
    for path in candidates:
        for lineno, line in code_lines(source(path)):
            for label, pattern in forbidden:
                if pattern.search(line):
                    failures.append(f"{path}:{lineno}: {label}: {line.strip()}")
    assert not failures, "\n" + "\n".join(failures)


def test_shasum_has_sha256sum_fallback():
    for path in SHELL_FILES:
        text = "\n".join(line for _lineno, line in code_lines(source(path)))
        if re.search(r"\bshasum\b", text):
            assert re.search(r"\bsha256sum\b", text), (
                f"{path}: shasum is used without a sha256sum branch")


def test_shell_syntax():
    for path in SHELL_FILES:
        absolute = os.path.join(ROOT, path)
        for args in (["bash", "-n", absolute], ["bash", "--posix", "-n", absolute]):
            result = subprocess.run(args, capture_output=True, text=True)
            assert result.returncode == 0, f"{' '.join(args)}\n{result.stderr}"


def fixture_repo():
    root = tempfile.mkdtemp(prefix="portability-hooks-")
    subprocess.run(["git", "init", "-q", root], check=True)
    os.makedirs(os.path.join(root, "tools"))
    for name in ("install_hooks.sh", "precommit-hook.sh"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    with open(os.path.join(root, "tools", "gate.py"), "w", encoding="utf-8") as f:
        f.write("raise SystemExit(0)\n")
    return root


def test_installer_without_new_git_subcommands():
    root = fixture_repo()
    shim = tempfile.mkdtemp(prefix="portability-git-")
    real_git = shutil.which("git")
    wrapper = os.path.join(shim, "git")
    try:
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
            f.write("case \" $* \" in\n")
            f.write("  *\" --path-format\"*|*\" hook run \"*) exit 97 ;;\n")
            f.write("esac\n")
            f.write(f'exec "{real_git}" "$@"\n')
        os.chmod(wrapper, 0o755)
        env = dict(os.environ, PATH=shim + os.pathsep + os.environ.get("PATH", ""))
        result = subprocess.run(
            ["bash", "tools/install_hooks.sh", "--repair"], cwd=root, env=env,
            capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(shim, ignore_errors=True)


def test_installer_prefers_sha256sum_without_shasum():
    root = fixture_repo()
    shim = tempfile.mkdtemp(prefix="portability-sha-")
    marker = os.path.join(shim, "sha256sum-used")
    try:
        hook_dir = os.path.join(root, ".git", "hooks")
        os.makedirs(hook_dir, exist_ok=True)
        hook = os.path.join(hook_dir, "pre-commit")
        with open(hook, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho foreign\n")
        os.chmod(hook, 0o755)

        for command in ("dirname", "git", "python3", "cmp", "grep", "awk"):
            target = shutil.which(command)
            assert target, f"test prerequisite missing: {command}"
            os.symlink(target, os.path.join(shim, command))
        fake_sum = os.path.join(shim, "sha256sum")
        with open(fake_sum, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
            f.write(f': > "{marker}"\n')
            f.write("printf '%064d  %s\\n' 0 \"$1\"\n")
        os.chmod(fake_sum, 0o755)

        env = dict(os.environ, PATH=shim)
        result = subprocess.run(
            ["/bin/bash", "tools/install_hooks.sh", "--check"], cwd=root, env=env,
            capture_output=True, text=True)
        assert result.returncode != 0 and "foreign" in (result.stdout + result.stderr)
        assert os.path.exists(marker), "sha256sum branch was not used"
        assert "shasum" not in os.listdir(shim), "fixture accidentally provides shasum"
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(shim, ignore_errors=True)


TESTS = [
    test_forbidden_patterns,
    test_shasum_has_sha256sum_fallback,
    test_shell_syntax,
    test_installer_without_new_git_subcommands,
    test_installer_prefers_sha256sum_without_shasum,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"ok  {test.__name__}")
        except Exception as exc:
            failed.append((test.__name__, exc))
            print(f"FAIL {test.__name__}: {exc}")
    print(f"portability: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
