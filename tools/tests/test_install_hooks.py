#!/usr/bin/env python3
"""install_hooks.sh regressions in disposable Git repositories."""
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def isolated_env(extra=None):
    """Git environment that ignores the user's global and system config.

    A global core.hooksPath would otherwise send fixture hooks (and the test's own writes) to the
    user's real hooks folder."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    env.update(extra or {})
    return env


def fixture():
    root = tempfile.mkdtemp(prefix="install-hooks-fixture-")
    subprocess.run(["git", "init", "-q", root], check=True, env=isolated_env())
    os.makedirs(os.path.join(root, "tools", "lib"))
    for name in ("install_hooks.sh", "lib/precommit-hook.sh"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    return root


def run(root, mode, env_extra=None):
    env = isolated_env(env_extra)
    return subprocess.run(["bash", "tools/install_hooks.sh", mode], cwd=root,
                          capture_output=True, text=True, env=env)


def hook_path(root):
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=root, capture_output=True, text=True, check=True, env=isolated_env())
    hooks = result.stdout.strip()
    if not os.path.isabs(hooks):
        hooks = os.path.join(root, hooks)
    hooks = os.path.realpath(hooks)
    # Tests write into this folder; never let it point outside the disposable fixture.
    assert hooks.startswith(os.path.realpath(root) + os.sep), hooks
    return os.path.join(hooks, "pre-commit")


def statuses(result):
    """Return the (status, path) pairs of an installer's output, one per hook."""
    return [tuple(line.split("\t")[:2]) for line in result.stdout.splitlines() if "\t" in line]


def test_check_prints_one_status_line_per_hook():
    """--check prints "status<TAB>path[<TAB>text]" for each hook, whatever the state."""
    root = fixture()
    try:
        hook = hook_path(root)
        push = os.path.join(os.path.dirname(hook), "pre-push")
        checked = run(root, "--check")
        assert statuses(checked) == [("missing", hook), ("missing", push)], checked.stdout
        assert run(root, "--repair").returncode == 0
        checked = run(root, "--check")
        assert checked.stdout.splitlines() == [f"current\t{hook}", f"current\t{push}"], checked.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_repair_then_check_installs_exact_executable():
    root = fixture()
    try:
        # Repair has no seal step any more: a baseline and a gate.py that fails if called show it
        # neither runs the gate nor claims a sealed baseline.
        os.makedirs(os.path.join(root, "state"))
        with open(os.path.join(root, "state", ".gate-baseline.json"), "w", encoding="utf-8") as f:
            f.write("{}\n")
        with open(os.path.join(root, "tools", "gate.py"), "w", encoding="utf-8") as f:
            f.write("raise SystemExit(1)\n")
        hook = hook_path(root)
        missing = run(root, "--check")
        assert missing.returncode != 0 and ("missing", hook) in statuses(missing)
        assert not os.path.exists(hook)

        repaired = run(root, "--repair")
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        assert ("current", hook) in statuses(repaired), repaired.stdout
        assert "sealed" not in repaired.stdout, repaired.stdout
        checked = run(root, "--check")
        assert checked.returncode == 0 and ("current", hook) in statuses(checked)
        assert os.path.isfile(hook), f"expected installed hook: {hook}"
        assert open(hook, "rb").read() == open(
            os.path.join(root, "tools", "lib", "precommit-hook.sh"), "rb").read()
        assert os.stat(hook).st_mode & stat.S_IXUSR
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_reports_owned_drift_and_repair_backs_it_up():
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        hook = hook_path(root)
        assert os.path.isfile(hook), f"expected installed hook: {hook}"
        text = open(hook, encoding="utf-8").read().replace(
            "# MOTTORI_PRECOMMIT_HOOK_V1\n", "")
        with open(hook, "w", encoding="utf-8") as f:
            f.write(text)
        drifted_hash = hashlib.sha256(open(hook, "rb").read()).hexdigest()
        stamp = os.path.join(os.path.dirname(hook), "mottori-hooks.stamp")
        installed = open(stamp, encoding="utf-8").read()

        # Bytes the stamp does not name are another tool's hook.
        foreign = run(root, "--check")
        assert foreign.returncode != 0 and ("foreign", hook) in statuses(foreign), foreign.stdout + foreign.stderr
        # Repair refuses a foreign hook, so the next step is to move it out first, not repair alone.
        assert "replaces it" not in foreign.stdout and "move it out" in foreign.stdout, foreign.stdout
        # A hook whose bytes the stamp names is the kit's, so it is owned drift.
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(installed.replace(installed.split("\n")[0].split(" ")[1], drifted_hash))
        checked = run(root, "--check")
        assert checked.returncode != 0 and ("owned-drift", hook) in statuses(checked), checked.stdout + checked.stderr
        repaired = run(root, "--repair")
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
        assert result.stderr.startswith(f"foreign\t{hook}\t") and "gate.py precommit" in result.stderr, result.stderr
        assert before == after
        assert not [name for name in os.listdir(os.path.dirname(hook))
                    if name.startswith("pre-commit.bak.")]
        # A dangling link and a directory are someone's setup too; neither hashes to a legacy
        # hook, and repair refuses them instead of crashing on the copy.
        os.remove(hook)
        os.symlink(os.path.join(root, "absent-hook"), hook)
        checked = run(root, "--check")
        assert checked.stdout.startswith(f"foreign\t{hook}\t") and "--repair" in checked.stdout, checked.stdout
        result = run(root, "--repair")
        assert result.returncode == 2 and os.path.islink(hook), result.stdout + result.stderr
        os.remove(hook)
        os.mkdir(hook)
        checked = run(root, "--check")
        assert checked.stdout.startswith(f"foreign\t{hook}\t"), checked.stdout + checked.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_another_tools_push_hook_stops_no_commit_and_a_missing_one_does():
    """Another tool's pre-push hook is the owner's. A missing or changed hook of the kit's own is drift."""
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        hook = hook_path(root)
        push = os.path.join(os.path.dirname(hook), "pre-push")
        plain = subprocess.run([hook], cwd=root, capture_output=True, text=True, env=isolated_env())
        with open(push, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n# another tool\nexit 0\n")
        os.chmod(push, 0o755)
        went_on = subprocess.run([hook], cwd=root, capture_output=True, text=True, env=isolated_env())
        assert "hook self-check failed" not in went_on.stderr, went_on.stderr
        assert went_on.returncode == plain.returncode, (plain.stderr, went_on.stderr)
        os.remove(push)
        refused = subprocess.run([hook], cwd=root, capture_output=True, text=True, env=isolated_env())
        assert refused.returncode == 1 and "fix: bash tools/install_hooks.sh --repair" in refused.stderr, refused.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_failed_repair_restores_current_hook_and_preserves_missing_hook():
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        hook = hook_path(root)
        push_hook = os.path.join(os.path.dirname(hook), "pre-push")
        assert os.path.isfile(hook), f"expected installed hook: {hook}"
        assert os.path.isfile(push_hook), f"expected installed hook: {push_hook}"
        os.remove(push_hook)
        # Owned drift (template bytes, not executable) differs from what repair writes, so a
        # rollback that leaves the new hook in place is visible in the mode check below.
        os.chmod(hook, 0o644)
        before = open(hook, "rb").read()
        before_mode = stat.S_IMODE(os.stat(hook).st_mode)
        # A template whose probe answers wrongly makes the post-install probe fail.
        template = os.path.join(root, "tools", "lib", "precommit-hook.sh")
        text = open(template, encoding="utf-8").read()
        assert "printf '%s\\n' \"$2\"" in text
        with open(template, "w", encoding="utf-8") as f:
            f.write(text.replace("printf '%s\\n' \"$2\"", "printf 'wrong\\n'"))

        failed = run(root, "--repair")
        # "probe" tells the probe rollback apart from the byte-verification rollback.
        assert failed.returncode == 1 and "restored" in failed.stderr and "probe" in failed.stderr, \
            failed.stdout + failed.stderr
        assert open(hook, "rb").read() == before
        assert stat.S_IMODE(os.stat(hook).st_mode) == before_mode
        assert not os.path.lexists(push_hook)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_template_change_after_install_is_owned_drift_not_foreign():
    """Ownership stamps keep an installed hook repairable after its template changes."""
    root = fixture()
    try:
        repaired = run(root, "--repair")
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        template = os.path.join(root, "tools", "lib", "precommit-hook.sh")
        with open(template, "a", encoding="utf-8") as f:
            f.write("# template comment changed after install\n")
        checked = run(root, "--check")
        assert checked.returncode != 0 and "owned-drift" in checked.stdout and "foreign" not in checked.stdout, \
            checked.stdout + checked.stderr
        assert "install_hooks.sh --repair" in checked.stdout.splitlines()[0], checked.stdout
        repaired_again = run(root, "--repair")
        assert repaired_again.returncode == 0, repaired_again.stdout + repaired_again.stderr
        assert run(root, "--check").returncode == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_output_is_english():
    """Every line check and repair print is English, with no Hangul."""
    hangul = re.compile("[\uac00-\ud7a3]")
    root = fixture()
    try:
        results = [run(root, "--check"), run(root, "--repair"), run(root, "--check")]
        hook = hook_path(root)
        os.chmod(hook, 0o644)
        results += [run(root, "--check"), run(root, "--repair")]
        with open(hook, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho foreign\n")
        results += [run(root, "--check"), run(root, "--repair")]
        text = "".join(r.stdout + r.stderr for r in results)
        assert not hangul.search(text), text
        assert results[0].stdout.startswith("missing\t") and results[2].stdout.startswith("current\t")
        assert "template sha256: " in results[3].stderr and "backup: " in results[4].stdout
        assert results[-1].returncode == 2 and results[-1].stderr.startswith("foreign\t")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_failed_probe_restores_prior_hook():
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        hook = hook_path(root)
        before = open(hook, "rb").read()
        before_mode = stat.S_IMODE(os.stat(hook).st_mode)
        template = os.path.join(root, "tools", "lib", "precommit-hook.sh")
        # Executable so verification passes and the probe step is reached, but never echoes the nonce.
        with open(template, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(template, 0o755)

        failed = run(root, "--repair")
        assert failed.returncode == 1, failed.stdout + failed.stderr
        assert "probe failed" in failed.stderr, failed.stderr
        assert open(hook, "rb").read() == before
        assert stat.S_IMODE(os.stat(hook).st_mode) == before_mode
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_suite_ignores_global_hookspath():
    """A user's global core.hooksPath must not receive the suite's fake hooks."""
    outside = tempfile.mkdtemp(prefix="install-hooks-global-")
    cfg_dir = tempfile.mkdtemp(prefix="install-hooks-gitconfig-")
    cfg = os.path.join(cfg_dir, "gitconfig")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(f"[core]\n\thooksPath = {outside}\n")
    saved = os.environ.get("GIT_CONFIG_GLOBAL")
    os.environ["GIT_CONFIG_GLOBAL"] = cfg
    error = None
    try:
        try:
            test_foreign_precommit_aborts_without_overwrite()
        except Exception as exc:  # noqa: BLE001
            error = exc
        assert os.listdir(outside) == [], os.listdir(outside)
        if error is not None:
            raise error
    finally:
        if saved is None:
            os.environ.pop("GIT_CONFIG_GLOBAL", None)
        else:
            os.environ["GIT_CONFIG_GLOBAL"] = saved
        shutil.rmtree(outside, ignore_errors=True)
        shutil.rmtree(cfg_dir, ignore_errors=True)


def test_outside_repo_hookspath_is_refused():
    root = fixture()
    outside = tempfile.mkdtemp(prefix="install-hooks-outside-")
    try:
        subprocess.run(["git", "-C", root, "config", "core.hooksPath", outside],
                       check=True, env=isolated_env())
        result = run(root, "--repair")
        assert result.returncode == 3, result.stdout + result.stderr
        assert "outside-repo hooksPath" in result.stderr, result.stderr
        own = os.path.join(os.path.realpath(root), ".git", "hooks")
        assert f'core.hooksPath "{own}"' in result.stderr, result.stderr
        assert os.listdir(outside) == [], os.listdir(outside)
        # Git expands a leading ~; read raw, it once became a folder named ~ inside the repository.
        subprocess.run(["git", "-C", root, "config", "core.hooksPath", "~/x"],
                       check=True, env=isolated_env())
        result = run(root, "--repair", env_extra={"HOME": outside})
        assert result.returncode == 3 and "outside-repo hooksPath" in result.stderr, result.stderr
        assert not os.path.exists(os.path.join(root, "~")), os.listdir(root)
        assert os.listdir(outside) == [], os.listdir(outside)
        # In a linked worktree the repository's hooks folder lies outside the worktree, and the
        # printed command must work there: .git is a file, so .git/hooks cannot be created.
        git = ["git", "-c", "user.name=f", "-c", "user.email=f@example.invalid"]
        subprocess.run(["git", "-C", root, "config", "--unset", "core.hooksPath"], check=True, env=isolated_env())
        subprocess.run(git + ["-C", root, "add", "-A"], check=True, env=isolated_env())
        subprocess.run(git + ["-C", root, "commit", "-qm", "f"], check=True, env=isolated_env())
        linked = os.path.join(outside, "linked wt")
        subprocess.run(["git", "-C", root, "worktree", "add", "-q", "--detach", linked],
                       check=True, env=isolated_env())
        subprocess.run(["git", "-C", root, "config", "core.hooksPath", outside], check=True, env=isolated_env())
        result = run(linked, "--repair")
        assert result.returncode == 3 and f'core.hooksPath "{own}"' in result.stderr, result.stderr
        subprocess.run(["git", "-C", linked, "config", "core.hooksPath", own], check=True, env=isolated_env())
        result = run(linked, "--repair")
        assert result.returncode == 0 and os.path.isfile(os.path.join(own, "pre-commit")), result.stderr
        shutil.rmtree(linked)
        # A kit folder inside another project's repository installs nothing there.
        nested = os.path.join(root, "nested-kit")
        shutil.copytree(os.path.join(root, "tools"), os.path.join(nested, "tools"))
        result = run(nested, "--repair")
        assert result.returncode == 2 and "not-own-repo" in result.stderr, result.stdout + result.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_symlinked_root_with_hookspath():
    root = fixture()
    link_dir = tempfile.mkdtemp(prefix="install-hooks-link-")
    link = os.path.join(link_dir, "repo")
    try:
        os.symlink(root, link)
        subprocess.run(["git", "-C", root, "config", "core.hooksPath", ".githooks"],
                       check=True, env=isolated_env())
        # cd inside bash so the logical (symlinked) path reaches the installer.
        result = subprocess.run(
            ["bash", "-c", 'cd "$1" && bash tools/install_hooks.sh --repair', "_", link],
            capture_output=True, text=True, env=isolated_env())
        assert result.returncode == 0, result.stdout + result.stderr
        assert os.path.isfile(os.path.join(root, ".githooks", "pre-commit"))
        assert run(root, "--check").returncode == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(link_dir, ignore_errors=True)


def test_check_reports_failing_hook_first():
    """doctor.py shows the first --check line, so it must name the hook that is not current."""
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        push_hook = os.path.join(os.path.dirname(hook_path(root)), "pre-push")
        os.remove(push_hook)
        checked = run(root, "--check")
        assert checked.returncode == 1, checked.stdout + checked.stderr
        assert statuses(checked)[0] == ("missing", push_hook), checked.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_repair_never_deletes_a_backup():
    """Backups are made only when a drifted hook is replaced, and the owner may have set one aside
    under any name, so repair never deletes one."""
    root = fixture()
    try:
        assert run(root, "--repair").returncode == 0
        hook = hook_path(root)
        kept = [hook + ".bak.my-original", hook + ".bak.20260101T123456.42.keep"]
        for path in kept:
            with open(path, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n")
        for _ in range(2):
            os.chmod(hook, 0o644)  # owned drift: template bytes without the executable bit
            repaired = run(root, "--repair")
            assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        backups = [name for name in os.listdir(os.path.dirname(hook)) if name.startswith("pre-commit.bak.")]
        assert len(backups) == 4, backups
        assert all(os.path.exists(path) for path in kept), backups
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_check_prints_one_status_line_per_hook,
    test_repair_then_check_installs_exact_executable,
    test_template_change_after_install_is_owned_drift_not_foreign,
    test_check_reports_owned_drift_and_repair_backs_it_up,
    test_foreign_precommit_aborts_without_overwrite,
    test_another_tools_push_hook_stops_no_commit_and_a_missing_one_does,
    test_failed_repair_restores_current_hook_and_preserves_missing_hook,
    test_output_is_english,
    test_failed_probe_restores_prior_hook,
    test_suite_ignores_global_hookspath,
    test_outside_repo_hookspath_is_refused,
    test_symlinked_root_with_hookspath,
    test_check_reports_failing_hook_first,
    test_repair_never_deletes_a_backup,
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
