#!/usr/bin/env python3
"""install_hooks.sh regressions in disposable Git repositories."""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))


def fixture():
    root = tempfile.mkdtemp(prefix="install-hooks-fixture-")
    subprocess.run(["git", "init", "-q", root], check=True)
    os.makedirs(os.path.join(root, "tools"))
    for name in ("install_hooks.sh", "precommit-hook.sh"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    return root


def run(root, mode, lang=None, env_extra=None):
    env = dict(os.environ)
    env["MOTTORI_LANG"] = lang or "ko"
    env.update(env_extra or {})
    return subprocess.run(["bash", "tools/install_hooks.sh", mode], cwd=root,
                          capture_output=True, text=True, env=env)


def hook_path(root):
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=root, capture_output=True, text=True, check=True)
    hooks = result.stdout.strip()
    if not os.path.isabs(hooks):
        hooks = os.path.join(root, hooks)
    return os.path.join(os.path.realpath(hooks), "pre-commit")


def test_repair_then_check_installs_exact_executable():
    root = fixture()
    try:
        hook = hook_path(root)
        missing = run(root, "--check")
        assert missing.returncode != 0 and "없음(missing):" in missing.stdout
        assert not os.path.exists(hook)

        repaired = run(root, "--repair")
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        assert "정확한 템플릿" in repaired.stdout and "exact template" not in repaired.stdout
        checked = run(root, "--check")
        assert checked.returncode == 0 and "현재(current):" in checked.stdout
        checked_en = run(root, "--check", lang="en")
        assert checked_en.returncode == 0 and "current:" in checked_en.stdout
        assert open(hook, "rb").read() == open(
            os.path.join(root, "tools", "precommit-hook.sh"), "rb").read()
        assert os.stat(hook).st_mode & stat.S_IXUSR
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_reports_owned_drift_and_repair_backs_it_up():
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        hook = hook_path(root)
        text = open(hook, encoding="utf-8").read().replace(
            "# MOTTORI_PRECOMMIT_HOOK_V1\n", "")
        with open(hook, "w", encoding="utf-8") as f:
            f.write(text)
        drifted_hash = hashlib.sha256(open(hook, "rb").read()).hexdigest()
        # This fixture imitates the canonical pre-sentinel hook. Its hash changes with every template edit,
        # so the contract (a legacy hash is owned-drift) is pinned through the env, not the in-file list (2026-09-18).
        legacy = {"MOTTORI_LEGACY_HOOK_HASHES": drifted_hash}

        checked = run(root, "--check", env_extra=legacy)
        assert checked.returncode != 0 and "소유 표류(owned-drift):" in checked.stdout, checked.stdout + checked.stderr
        foreign = run(root, "--check")
        assert foreign.returncode != 0 and "외부 훅(foreign):" in foreign.stdout, foreign.stdout + foreign.stderr
        repaired = run(root, "--repair", env_extra=legacy)
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        backups = [os.path.join(os.path.dirname(hook), name)
                   for name in os.listdir(os.path.dirname(hook))
                   if name.startswith("pre-commit.bak.")]
        assert len(backups) == 1
        assert hashlib.sha256(open(backups[0], "rb").read()).hexdigest() == drifted_hash
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_foreign_precommit_aborts_without_overwrite():
    root = fixture()
    try:
        hook = hook_path(root)
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        foreign = b"#!/bin/sh\necho foreign-hook\n"
        with open(hook, "wb") as f:
            f.write(foreign)
        before = hashlib.sha256(open(hook, "rb").read()).hexdigest()

        result = run(root, "--repair")
        after = hashlib.sha256(open(hook, "rb").read()).hexdigest()
        assert result.returncode == 2
        assert "foreign pre-commit" in result.stderr
        assert before == after
        assert not [name for name in os.listdir(os.path.dirname(hook))
                    if name.startswith("pre-commit.bak.")]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_failed_repair_restores_current_hook_and_preserves_missing_hook():
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        hook = hook_path(root)
        push_hook = os.path.join(os.path.dirname(hook), "pre-push")
        os.remove(push_hook)
        before = open(hook, "rb").read()
        before_mode = stat.S_IMODE(os.stat(hook).st_mode)
        os.makedirs(os.path.join(root, "state"), exist_ok=True)
        with open(os.path.join(root, "state", ".gate-baseline.json"), "w", encoding="utf-8") as f:
            f.write("{malformed\n")
        with open(os.path.join(root, "tools", "gate.py"), "w", encoding="utf-8") as f:
            f.write("raise SystemExit(1)\n")

        failed = run(root, "--repair")
        assert failed.returncode == 1 and "hook 원상 복구" in failed.stderr
        assert open(hook, "rb").read() == before
        assert stat.S_IMODE(os.stat(hook).st_mode) == before_mode
        assert not os.path.lexists(push_hook)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_template_change_after_install_is_owned_drift_not_foreign():
    """2026-09-18 실측 2회: 템플릿 주석 한 줄이 바뀌면 설치본 전부가 foreign이 돼 --repair도 커밋도 막혔다.
    설치 시 스탬프로 소유권을 기록해 템플릿이 바뀌어도 owned-drift → --repair 가능해야 한다."""
    root = fixture()
    try:
        repaired = run(root, "--repair")
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        template = os.path.join(root, "tools", "precommit-hook.sh")
        with open(template, "a", encoding="utf-8") as f:
            f.write("# template comment changed after install\n")
        checked = run(root, "--check")
        assert checked.returncode != 0 and "owned-drift" in checked.stdout and "foreign" not in checked.stdout, \
            checked.stdout + checked.stderr
        repaired_again = run(root, "--repair")
        assert repaired_again.returncode == 0, repaired_again.stdout + repaired_again.stderr
        assert run(root, "--check").returncode == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_repair_then_check_installs_exact_executable,
    test_template_change_after_install_is_owned_drift_not_foreign,
    test_check_reports_owned_drift_and_repair_backs_it_up,
    test_foreign_precommit_aborts_without_overwrite,
    test_failed_repair_restores_current_hook_and_preserves_missing_hook,
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
    print(f"install hooks: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
