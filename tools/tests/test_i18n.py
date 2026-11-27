#!/usr/bin/env python3
# English surfaces: setup, doctor, linkcheck and the session-start fallback print no Hangul.
import os
import json
import re
import shutil
import subprocess
import sys
import tempfile

from testlib import kit_paths, kit_repo


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)


HANGUL = re.compile(r"[\uac00-\ud7a3]")
PASSED = 0
FAILED = []
SKIPPED = []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print("✓ " + name)
    else:
        FAILED.append(name)
        print("✗ " + name + (": " + detail if detail else ""))


def run(*args, cwd=ROOT):
    env = dict(os.environ, LANG="ko_KR.UTF-8", LC_ALL="ko_KR.UTF-8", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)


def _hangul_outside(text, *paths):
    """Search for Hangul in output with the given folder paths removed.

    A workspace whose own folder name is Korean prints that name; the path is the user's, not a
    message the kit failed to translate."""
    for path in paths:
        for form in {path, os.path.realpath(path)}:
            text = text.replace(form, "")
    return HANGUL.search(text)


def test_english_surfaces():
    # In an installed instance (without setup.sh), user data such as journal and track names may
    # use that language, so "zero Hangul in EN output" cannot be measured and no setup fixture can
    # be built. Report the skip explicitly in the summary.
    if not os.path.isfile(os.path.join(ROOT, "setup.sh")):
        SKIPPED.append("EN surfaces (installed instance without setup.sh: user data may be Korean; "
                       "covered by this test in the kit, where setup.sh exists)")
        print("- EN surfaces: not applicable here — " + SKIPPED[-1])
        return
    # An installation's own doctor and link check name its own files and tracks, in its owner's
    # language; there only the setup fixture below, built from the kit's own files, is measured.
    if not os.path.isfile(os.path.join(ROOT, "instance", "config.json")):
        doctor = run(sys.executable, "tools/doctor.py")
        check("EN doctor stdout has no Hangul", not _hangul_outside(doctor.stdout, ROOT),
              doctor.stdout[-500:])

        links = run(sys.executable, "tools/linkcheck.py")
        check("EN linkcheck stdout has no Hangul", not _hangul_outside(links.stdout, ROOT),
              links.stdout[-500:])

    parent = tempfile.mkdtemp(prefix="english-setup-")
    clone = os.path.join(parent, "kit")
    try:
        if kit_paths(ROOT) is not None:
            # The kit's own files as they are now, committed once: an installation's documents and
            # data stay out (KIT-DR-089).
            kit_repo(ROOT, clone)
            check("setup fixture holds the kit's own files", os.path.isfile(os.path.join(clone, "setup.sh")))
            setup = run("bash", "setup.sh", "--name", "x", cwd=clone)
            check("EN setup stdout has no Hangul", not _hangul_outside(setup.stdout, ROOT, clone),
                  setup.stdout[-800:])
            check("EN setup completes", setup.returncode == 0, (setup.stdout + setup.stderr)[-1200:])
            return
        cloned = subprocess.run(["git", "clone", "-q", ROOT, clone], capture_output=True, text=True)
        check("setup fixture is a temporary clone", cloned.returncode == 0, cloned.stderr[-300:])
        if cloned.returncode != 0:
            return
        patch = subprocess.run(
            ["git", "diff", "--binary", "HEAD"], cwd=ROOT, capture_output=True
        )
        applied = subprocess.run(
            ["git", "apply"], cwd=clone, input=patch.stdout, capture_output=True
        ) if patch.returncode == 0 and patch.stdout else None
        untracked = subprocess.run(
            ["git", "ls-files", "-o", "--exclude-standard", "-z"],
            cwd=ROOT, capture_output=True
        )
        copied = untracked.returncode == 0
        if copied:
            for raw in untracked.stdout.split(b"\0"):
                if not raw:
                    continue
                rel = os.fsdecode(raw)
                source = os.path.join(ROOT, rel)
                if not os.path.isfile(source):
                    continue
                destination = os.path.join(clone, rel)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(source, destination)
        staged = subprocess.run(["git", "add", "-A"], cwd=clone, capture_output=True)
        mirrored = (patch.returncode == 0 and (applied is None or applied.returncode == 0)
                    and copied and staged.returncode == 0)
        detail = b"\n".join(filter(None, (
            patch.stderr,
            applied.stderr if applied is not None else b"",
            untracked.stderr,
            staged.stderr,
        ))).decode("utf-8", errors="replace")[-500:]
        check("setup fixture mirrors worktree", mirrored, detail)
        if not mirrored:
            return
        setup = run("bash", "setup.sh", "--name", "x", cwd=clone)
        check("EN setup stdout has no Hangul", not _hangul_outside(setup.stdout, ROOT, clone),
              setup.stdout[-800:])
        check("EN setup completes", setup.returncode == 0, (setup.stdout + setup.stderr)[-1200:])
    finally:
        shutil.rmtree(parent, ignore_errors=True)


HOOK_FAILED_TEXT = "[kit] State injection failed (now.py is missing or errored)."


def test_sessionstart_fallback_is_english():
    # The hook files are static, so a session-start failure prints the launcher's English fallback.
    for rel in ((".claude", "settings.json"), (".codex", "hooks.json")):
        payload = json.load(open(os.path.join(ROOT, *rel), encoding="utf-8"))
        command = payload["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        if '" event SessionStart ' in command:
            # An event line keeps its fallback in the launcher.
            command = open(os.path.join(ROOT, "tools", "hook.sh"), encoding="utf-8").read()
        check("session-start fallback is English: " + rel[0],
              HOOK_FAILED_TEXT in command and not HANGUL.search(command), command)


if __name__ == "__main__":
    test_english_surfaces()
    test_sessionstart_fallback_is_english()
    total = PASSED + len(FAILED)
    skipped = f" · not applicable {len(SKIPPED)}" if SKIPPED else ""
    print(f"english surfaces: {PASSED}/{total} passed{skipped}")
    sys.exit(0 if not FAILED else 1)
