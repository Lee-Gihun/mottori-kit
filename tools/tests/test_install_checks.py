#!/usr/bin/env python3
"""Installation checks in isolated repositories with fixture configuration.

Cover broken versus pending links, runtime readiness, Git version support,
checker failures, and path names containing spaces."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
PY = sys.executable

PASSED, FAILED = [], []


def ok(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("✓ " if cond else "✗ ") + name + (f": {detail}" if detail and not cond else ""))


def make_repo(with_config=True):
    """Create a temporary repository with engine tools and Markdown files."""
    root = tempfile.mkdtemp(prefix="install-checks.")
    os.makedirs(os.path.join(root, "tools", "lib"))
    for name in ("lib/paths.py", "lib/config.py", "lib/journal.py", "lib/safeio.py",
                 "lib/runlog.py", "lib/hook_input.py", "lib/adopted.py",
                 "enforce.py", "linkcheck.py", "doctor.py", "gate.py", "now.py", "lib/memory_index.py",
                 "lib/hookdiag.py",
                 "coherence.py", "hook.sh", "dispatch.py"):
        src = os.path.join(HERE, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(root, "tools", name))
    os.makedirs(os.path.join(root, "instance"))
    os.makedirs(os.path.join(root, "state"))
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("state/\n_private/\ninstance/config.json\ninstance/rules.md\n"
                "instance/decisions.md\ninstance/rituals.md\n")
    if with_config:
        cfg = json.load(open(os.path.join(ROOT, "templates", "config.json"), encoding="utf-8")) \
            if os.path.exists(os.path.join(ROOT, "templates", "config.json")) else \
            json.load(open(os.path.join(ROOT, "instance", "config.json"), encoding="utf-8"))
        cfg.setdefault("instance", {})["name"] = "fixture"
        cfg["instance"]["context"] = "personal"
        cfg["tracks"] = []
        cfg["threads"] = []
        cfg["personal_pointer"] = None      # A new instance retains the null template value.
        json.dump(cfg, open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8"))
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    commit(root, "init", "--allow-empty")
    return root


def commit(root, message, *args):
    subprocess.run(["git", "-c", "user.email=fixture@example.invalid", "-c", "user.name=fixture",
                    "commit", "-q", *args, "-m", message], cwd=root, check=True)


def last_json(result, fallback):
    """The probe prints its answer last; a crashed probe yields fallback so the assertion shows why."""
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return fallback


def state_hook_cmd(root):
    """A SessionStart command that injects state only when run inside root, as the real hook does."""
    good = '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"state ok"}}'
    bad = '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"[kit] outside"}}'
    # The root is quoted: an installed instance path may contain spaces.
    return f"case \"$(pwd -P)\" in \"{os.path.realpath(root)}\"*) echo '{good}';; *) echo '{bad}';; esac"


def run(root, *args, env_extra=None):
    env = dict(os.environ, MOTTORI_INSTANCE=root)
    env.pop("MOTTORI_INTERNAL_RUN", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PY, *args], cwd=root, capture_output=True, text=True, env=env)


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def run_fresh_judge(kind, subprocess_rc, output):
    """Run only the deployment kit's initial-install check."""
    with tempfile.TemporaryDirectory(prefix="fresh-judge.") as tmp:
        output_path = os.path.join(tmp, f"{kind}.out")
        write(tmp, f"{kind}.out", output)
        return subprocess.run(
            ["bash", os.path.join(ROOT, "tools", "tests", "test_fresh_install.sh"),
             f"--judge-{kind}", str(subprocess_rc), output_path],
            cwd=ROOT, capture_output=True, text=True, timeout=3,
        )


# ------------------------------------------------------------ X12  fresh gate parsing
def test_fresh_install_rejects_malformed_summaries():
    if not os.path.isfile(os.path.join(ROOT, "tools", "tests", "test_fresh_install.sh")):
        # The initial-install gate belongs to the deployment kit, not installed instances.
        print("- X12: not applicable here (no tools/tests/test_fresh_install.sh: installed instance)")
        return
    valid_doctor = json.dumps({
        "checks": [{"name": "fixture", "status": "PASS", "detail": "ok"}],
        "summary": {"total": 1, "pass": 1, "fail": 0, "warn": 0, "skip": 0},
        "manual": [],
    })
    malformed = (
        run_fresh_judge("linkcheck", 0, ""),
        run_fresh_judge("linkcheck", 0,
                        "[linkcheck] broken: 0\n[linkcheck] broken: 0\n"),
        run_fresh_judge("doctor", 0, "{broken json\n"),
    )
    ok("X12 malformed summaries -> 3/3 unmeasurable FAIL",
       all(r.returncode != 0 and "unmeasurable" in (r.stdout + r.stderr) for r in malformed),
       "\n".join(r.stdout + r.stderr for r in malformed))

    # Each rejection rule on its own: a well-formed summary must still fail on the exit code or
    # the reported count, so deleting any one rule makes this check fail.
    failing_doctor = json.dumps({
        "checks": [{"name": "fixture", "status": "FAIL", "detail": "bad"}],
        "summary": {"total": 1, "pass": 0, "fail": 1, "warn": 0, "skip": 0},
        "manual": [],
    })
    rejected = (
        run_fresh_judge("linkcheck", 1, "[linkcheck] broken: 0\n"),
        run_fresh_judge("linkcheck", 0, "[linkcheck] broken: 2\n"),
        run_fresh_judge("doctor", 0, failing_doctor),
    )
    ok("X12 nonzero linkcheck, broken links, doctor FAIL -> 3/3 unmeasurable FAIL",
       all(r.returncode != 0 and "unmeasurable" in (r.stdout + r.stderr) for r in rejected),
       "\n".join(r.stdout + r.stderr for r in rejected))

    abnormal = run_fresh_judge("doctor", 7, valid_doctor)
    ok("X12 nonzero doctor with FAIL 0 is unmeasurable FAIL",
       abnormal.returncode != 0 and "unmeasurable" in (abnormal.stdout + abnormal.stderr),
       abnormal.stdout + abnormal.stderr)

    normal_link = run_fresh_judge("linkcheck", 0, "[linkcheck] broken: 0\n")
    normal_doctor = run_fresh_judge("doctor", 0, valid_doctor)
    ok("X12 normal summaries keep PASS",
       normal_link.returncode == 0 and normal_doctor.returncode == 0,
       normal_link.stdout + normal_link.stderr + normal_doctor.stdout + normal_doctor.stderr)


# ------------------------------------------------------------ J · F  linkcheck
def test_linkcheck_exit_codes_and_pending():
    root = make_repo(with_config=False)
    try:
        write(root, "README.md", "see `instance/config.json` and [rules](instance/rules.md)\n")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("F pre-setup: setup-created targets are PENDING, exit 0",
           r.returncode == 0 and "PENDING" in r.stdout and "broken: 0" in r.stdout, r.stdout[-300:])
        # A nested link names a setup-created file only when it resolves there from its document.
        write(root, "system/typo.md", "[x](nope-zz.md) [r](instance/rules.md)\n")
        subprocess.run(["git", "add", "system/typo.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("J broken → exit 1", r.returncode == 1 and "BROKEN system/typo.md -> nope-zz.md" in r.stdout
           and "BROKEN system/typo.md -> instance/rules.md" in r.stdout, r.stdout[-300:])
        r = run(root, "tools/linkcheck.py", "--issues")
        ok("J --issues stays exit 0 with #issues trailer", r.returncode == 0 and "#issues 2" in r.stdout,
           r.stdout[-200:])
        os.remove(os.path.join(root, "system", "typo.md"))
        subprocess.run(["git", "rm", "-q", "--cached", "system/typo.md"], cwd=root, check=True)
        # Before setup a generated baseline is pending; after setup its absence is broken.
        write(root, "SETUP.md", "baseline lives at `state/.gate-baseline.json`\n")
        subprocess.run(["git", "add", "SETUP.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("F pre-setup: gate baseline reference is PENDING",
           r.returncode == 0 and "PENDING SETUP.md -> state/.gate-baseline.json" in r.stdout, r.stdout[-300:])
        # Once configuration exists, a missing baseline must be reported as broken.
        write(root, "instance/config.json", "{}")
        r = run(root, "tools/linkcheck.py")
        ok("F post-setup: missing instance-rules is BROKEN, exit 1",
           r.returncode == 1 and "BROKEN README.md -> instance/rules.md" in r.stdout, r.stdout[-300:])
        ok("F post-setup: missing gate baseline is BROKEN",
           "BROKEN SETUP.md -> state/.gate-baseline.json" in r.stdout, r.stdout[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ L  scope hash with spaces
def test_linkcheck_optional_destinations_are_exact_and_instance_owned():
    for configured in (False, True):
        root = make_repo(with_config=configured)
        phase = "post-setup" if configured else "pre-setup"
        destinations = ("_private/deep-pass/ledger.md", "instance/debate/_p_review.md")
        try:
            with open(os.path.join(root, ".gitignore"), "a") as stream:
                stream.write("instance/debate/_p_review.md\n")
            write(root, "README.md", "[ledger](_private/deep-pass/ledger.md)\n"
                  "[prompt](instance/debate/_p_review.md)\n")
            # A plain run keeps the kit's first-use files to itself; --all lists them.
            plain = run(root, "tools/linkcheck.py")
            ok(f"a plain run does not list first-use destinations ({phase})",
               plain.returncode == 0 and "OPTIONAL" not in plain.stdout, plain.stdout)
            result = run(root, "tools/linkcheck.py", "--all")
            ok(f"optional destinations remain distinct from setup pending ({phase})",
               result.returncode == 0 and result.stdout.count("OPTIONAL README.md ->") == 2
               and "PENDING" not in result.stdout, result.stdout)
            if os.path.isfile(os.path.join(ROOT, "tools", "tests", "test_fresh_install.sh")):
                judged = run_fresh_judge("linkcheck", result.returncode, result.stdout)
                ok(f"fresh-install parser accepts actual optional output ({phase})",
                   judged.returncode == 0, judged.stdout + judged.stderr)

            for destination in destinations:
                write(root, destination, "# synthetic instance record\n")
            result = run(root, "tools/linkcheck.py")
            ok(f"existing optional destinations are ordinary valid references ({phase})",
               result.returncode == 0 and "OPTIONAL" not in result.stdout, result.stdout)
            for destination in destinations:
                os.remove(os.path.join(root, destination))
            result = run(root, "tools/linkcheck.py", "--all")
            ok(f"first use does not make later absence a required-file failure ({phase})",
               result.returncode == 0 and result.stdout.count("OPTIONAL README.md ->") == 2,
               result.stdout)

            with open(os.path.join(root, "README.md"), "a") as stream:
                stream.write("[typo](_private/deep-pass/ledger-typo.md)\n"
                             "[other prompt](instance/debate/_p_typo.md)\n")
            result = run(root, "tools/linkcheck.py")
            ok(f"neighboring private paths and prompt typos remain broken ({phase})",
               result.returncode == 1
               and "BROKEN README.md -> _private/deep-pass/ledger-typo.md" in result.stdout
               and "BROKEN README.md -> instance/debate/_p_typo.md" in result.stdout,
               result.stdout)

            write(root, destinations[0], "# synthetic tracked fixture\n")
            subprocess.run(["git", "add", "-f", destinations[0]], cwd=root, check=True)
            os.remove(os.path.join(root, destinations[0]))
            result = run(root, "tools/linkcheck.py")
            ok(f"a tracked missing destination cannot use the instance exception ({phase})",
               result.returncode == 1
               and "BROKEN README.md -> _private/deep-pass/ledger.md" in result.stdout,
               result.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_linkcheck_measures_non_ascii_spaced_filenames():
    root = make_repo(with_config=True)
    try:
        name = "system/\ud55c\uae00 \uacf5\ubc31.md"
        write(root, name, "[missing](missing-unicode-fixture.md)\n")
        subprocess.run(["git", "config", "core.quotePath", "true"], cwd=root, check=True)
        subprocess.run(["git", "add", name], cwd=root, check=True)
        normal = run(root, "tools/linkcheck.py")
        code = ("import sys; sys.path.insert(0,'tools'); import doctor; "
                "print(doctor.c_missed_gate()[0])")
        after_broken = run(root, "-c", code)
        ok("a failed linkcheck run is not the certificate doctor looks for",
           after_broken.returncode == 0 and after_broken.stdout.strip()
           and not after_broken.stdout.strip().endswith("PASS"),
           after_broken.stdout + after_broken.stderr)
        issues = run(root, "tools/linkcheck.py", "--issues")
        ok("non-ASCII spaced Markdown is measured with Git quotePath enabled",
           normal.returncode == 1
           and f"BROKEN {name} -> missing-unicode-fixture.md" in normal.stdout
           and "broken: 1" in normal.stdout, normal.stdout + normal.stderr)
        ok("machine issues include the same non-ASCII spaced Markdown",
           issues.returncode == 0
           and f"{name} -> missing-unicode-fixture.md\t" in issues.stdout
           and issues.stdout.rstrip().endswith("#issues 1"), issues.stdout + issues.stderr)

        write(root, name, "# valid document\n")
        normal = run(root, "tools/linkcheck.py")
        certificate = run(root, "-c", code)
        ok("doctor recognizes a successful check of non-ASCII Markdown",
           normal.returncode == 0 and certificate.stdout.strip().endswith("PASS"),
           normal.stdout + certificate.stdout + certificate.stderr)
        write(root, name, "# revised document\n")
        stale = run(root, "-c", code)
        ok("editing non-ASCII Markdown invalidates the earlier certificate",
           stale.returncode == 0 and not stale.stdout.strip().endswith("PASS"),
           stale.stdout + stale.stderr)
        refreshed = run(root, "tools/linkcheck.py")
        certificate = run(root, "-c", code)
        ok("rerunning linkcheck refreshes the non-ASCII document certificate",
           refreshed.returncode == 0 and certificate.stdout.strip().endswith("PASS"),
           refreshed.stdout + certificate.stdout + certificate.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_linkcheck_extracted_tree_uses_only_ignored_root_fallback():
    root = make_repo(with_config=True)
    tree = tempfile.mkdtemp(prefix="linkcheck-extracted.")
    try:
        write(root, "_private/local.md", "# local only\n")
        write(tree, "README.md", "[local](_private/local.md)\n")
        filelist = os.path.join(tree, "files.txt")
        with open(filelist, "w", encoding="utf-8") as f:
            f.write("README.md\n")
        r = run(root, "tools/linkcheck.py", "--tree", tree, "--filelist", filelist)
        ok("L extracted tree accepts ignored local-only ROOT fallback",
           r.returncode == 0 and "broken: 0" in r.stdout, r.stdout[-300:])
        write(tree, "docs/n.md", "[local](_private/local.md)\n")
        with open(filelist, "a", encoding="utf-8") as f:
            f.write("docs/n.md\n")
        r = run(root, "tools/linkcheck.py", "--tree", tree, "--filelist", filelist)
        ok("L the ROOT fallback keeps a link relative to its document",
           r.returncode == 1 and "BROKEN docs/n.md -> _private/local.md" in r.stdout, r.stdout[-300:])
        # ROOT has no docs/ folder, so the fallback candidate must be normalized to exist.
        write(tree, "docs/n.md", "[local](../_private/local.md)\n")
        r = run(root, "tools/linkcheck.py", "--tree", tree, "--filelist", filelist)
        ok("L the ROOT fallback resolves a ../ link from a folder only the tree has",
           r.returncode == 0 and "broken: 0" in r.stdout, r.stdout[-300:])

        write(root, "tracked.md", "# tracked but absent from extracted tree\n")
        subprocess.run(["git", "add", "tracked.md"], cwd=root, check=True)
        write(tree, "README.md", "[tracked](tracked.md)\n")
        r = run(root, "tools/linkcheck.py", "--tree", tree, "--filelist", filelist)
        ok("L extracted tree rejects tracked worktree-only fallback",
           r.returncode == 1 and "BROKEN README.md -> tracked.md" in r.stdout,
           r.stdout[-300:])
    finally:
        shutil.rmtree(tree, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_linkcheck_exclude_config_applies_only_without_all():
    root = make_repo(with_config=True)
    try:
        config_path = os.path.join(root, "instance", "config.json")
        config = json.load(open(config_path, encoding="utf-8"))
        config.setdefault("checks", {})["linkcheck_exclude_prefixes"] = ["archive/"]
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        write(root, "archive/old.md", "[missing](gone.md)\n")
        subprocess.run(["git", "add", "archive/old.md"], cwd=root, check=True)

        normal = run(root, "tools/linkcheck.py")
        all_files = run(root, "tools/linkcheck.py", "--all")
        ok("linkcheck exclude key hides archive in default mode",
           normal.returncode == 0 and "broken: 0" in normal.stdout, normal.stdout)
        ok("linkcheck --all overrides exclude key",
           all_files.returncode == 1 and "BROKEN archive/old.md -> gone.md" in all_files.stdout,
           all_files.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ E · git  doctor severities
def test_doctor_codex_armed_and_git_version():
    root = make_repo(with_config=True)
    try:
        code = r'''
import os, sys, types; sys.path.insert(0, "tools")
import doctor, hookdiag
def fake_list(_root, **kw): return {"hooks": [], "errors": []}
def report(armed, valid=True):
    return {e: {"declared": True, "command_valid": valid, "armed": armed, "matcher_reachable": True}
            for e in hookdiag.KIT_EVENTS["codex"]}
hookdiag.codex_hooks_list = fake_list
hookdiag.codex_runtime_report = lambda hooks: report(False)
doctor._sessions_here = lambda: {"codex": 3}
print("unarmed", doctor.c_hook_codex_armed()[0])
doctor._sessions_here = lambda: {"claude": 5}
print("unarmed_unused", doctor.c_hook_codex_armed()[0])
hookdiag.codex_runtime_report = lambda hooks: report(True)
print("armed", doctor.c_hook_codex_armed()[0])
hookdiag.codex_runtime_report = lambda hooks: report(False, valid=False)
print("invalid", doctor.c_hook_codex_armed()[0])
unlisted = dict(report(True), Stop={"declared": False, "armed": False})
hookdiag.codex_runtime_report = lambda hooks: unlisted
detail = doctor.c_hook_codex_armed()[1]
print("unlisted", doctor.HOOK_NOT_LISTED in detail
      and doctor.HOOK_NOT_DECLARED not in detail)
hookdiag.codex_runtime_report = lambda hooks: report(True)
hookdiag.codex_hooks_list = lambda _r, **kw: {"hooks": [], "errors": ["boom"]}
print("loader", doctor.c_hook_codex_armed()[0])
class R:
    def __init__(self, out, rc=0): self.stdout=out; self.returncode=rc; self.stderr=""
def fake_sh(*cmd, cwd=None):
    if cmd[:2] == ("git", "--version"): return R(fake_sh.version)
    return R(os.path.join(os.sep, "tmp", "x"))
doctor.sh = fake_sh
for v, tag in (("git version 2.4.12", "too_old"), ("git version 2.5.0", "minimum"), ("git version 2.35.9", "old"), ("git version 2.36.0", "new"), ("git version 2.50.1 (Apple Git-155)", "apple"), ("weird", "unparsable")):
    fake_sh.version = v
    print(tag, doctor.c_git()[0])
'''
        r = run(root, "-c", code)
        out = dict(l.split(" ", 1) for l in r.stdout.strip().splitlines() if " " in l)
        ok("E codex unarmed → WARN", out.get("unarmed") == "WARN", r.stdout + r.stderr[-300:])
        ok("E codex unarmed and never used in this folder → not applicable yet",
           out.get("unarmed_unused") == "SKIP", r.stdout + r.stderr[-300:])
        ok("E codex armed → PASS", out.get("armed") == "PASS", r.stdout)
        ok("E codex command invalid → FAIL", out.get("invalid") == "FAIL", r.stdout)
        ok("E codex loader error → FAIL", out.get("loader") == "FAIL", r.stdout)
        ok("E codex row names an unlisted hook as such", out.get("unlisted") == "True", r.stdout)
        ok("git 2.4 → FAIL", out.get("too_old") == "FAIL", r.stdout)
        ok("git 2.5 minimum → PASS", out.get("minimum") == "PASS", r.stdout)
        ok("git 2.35 → PASS", out.get("old") == "PASS", r.stdout)
        ok("git 2.36 → PASS", out.get("new") == "PASS", r.stdout)
        ok("git 2.50 (Apple) → PASS", out.get("apple") == "PASS", r.stdout)
        ok("git unparsable → WARN", out.get("unparsable") == "WARN", r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_link_row_says_when_the_owners_folders_were_not_read():
    """A clean link row in a kit installation covers the files Git lists, and says so."""
    import doctor
    from unittest.mock import patch
    clean = lambda *args: _Result(0, "#issues 0\n")  # noqa: E731
    with patch.object(doctor, "sh", clean):
        with patch.object(doctor.P, "owner_names", lambda *a, **k: ["notes"]):
            ok("doctor: a clean link row names what it did not read",
               doctor.c_links() == (doctor.PASS, doctor.LINKS_OK_LISTED), repr(doctor.c_links()))
        with patch.object(doctor.P, "owner_names", lambda *a, **k: []):
            ok("doctor: a clean link row is plain where Git lists the whole workspace",
               doctor.c_links() == (doctor.PASS, "no broken references"), repr(doctor.c_links()))


def test_doctor_shows_the_track_summary_reminder_the_check_gives():
    """The reminder never stops a turn, so doctor is where it reaches the owner."""
    import doctor
    from unittest.mock import patch
    out = "~canonical-stale:projects/plan.md\t[canonical behind] projects/plan.md (2026-01-01) < newest\n#issues 0\n"
    with patch.object(doctor, "sh", lambda *a: _Result(0, out)):
        status, detail = doctor.c_tools_run()
    ok("doctor: a track summary behind its decisions is a warning with its text",
       status == doctor.WARN and "projects/plan.md" in detail, repr((status, detail)))
    with patch.object(doctor, "sh", lambda *a: _Result(0, "#issues 0\n")):
        ok("doctor: no reminder, a plain pass", doctor.c_tools_run()[0] == doctor.PASS)


def test_doctor_precommit_reads_the_check_status_words():
    """doctor decides on the status word and path of each line of install_hooks.sh --check,
    never on the words for a person after them."""
    import doctor
    from unittest.mock import patch
    original = doctor.sh
    # A stub installer in a fixture root makes every case reach the status lines; without it the
    # checker would stop at installer_missing and the real tree's file would decide the result.
    with tempfile.TemporaryDirectory(prefix="doctor-precommit-") as temporary, \
            patch.object(doctor, "ROOT", temporary):
        write(temporary, "tools/install_hooks.sh", "exit 0\n")

        def installer(code, value, top=temporary):
            # The git top-level probe answers with the fixture root unless a case overrides it.
            return lambda *args: _Result(0, top + "\n") if args[0] == "git" else _Result(code, value)
        try:
            doctor.sh = installer(0, "current\t/h/pre-commit\ncurrent\t/h/pre-push\n")
            ok("doctor accepts two current hooks", doctor.c_precommit_install() ==
               (doctor.PASS, "current: /h/pre-commit + /h/pre-push"), repr(doctor.c_precommit_install()))
            doctor.sh = installer(1, "missing\t/hooks\n")
            status, detail = doctor.c_precommit_install()
            ok("doctor fails a missing hook with the repair",
               status == doctor.FAIL and "--repair" in detail, repr((status, detail)))
            # A foreign hook printed after a missing one still decides the row, and its words show.
            doctor.sh = installer(1, "missing\t/h/pre-commit\nforeign\t/h/pre-push\tadd the line x\n")
            status, detail = doctor.c_precommit_install()
            ok("doctor names a foreign hook listed second",
               status == doctor.FAIL and "/h/pre-push (add the line x)" in detail, repr((status, detail)))
            # Another tool's pre-push beside the kit's pre-commit is the owner's: a warning, with its words.
            doctor.sh = installer(2, "current\t/h/pre-commit\nforeign\t/h/pre-push\tadd the line x\n")
            status, detail = doctor.c_precommit_install()
            ok("doctor warns about another tool's pre-push hook",
               status == doctor.WARN and "does not check pushes" in detail and "(add the line x)" in detail,
               repr((status, detail)))
            doctor.sh = installer(2, "foreign\t/h/pre-commit\tadd the line y\ncurrent\t/h/pre-push\n")
            status, detail = doctor.c_precommit_install()
            ok("doctor fails another tool's pre-commit hook", status == doctor.FAIL, repr((status, detail)))
            doctor.sh = installer(0, "chained\t/h/pre-push\tnot the kit's\ncurrent\t/h/pre-commit\n")
            status, _ = doctor.c_precommit_install()
            ok("doctor accepts a chained hook", status == doctor.PASS, repr(status))
            # Words that read like a status decide nothing.
            doctor.sh = installer(0, "chained\t/h/pre-push\tcurrent\nmissing\t/h/pre-commit\tcurrent\n")
            status, _ = doctor.c_precommit_install()
            ok("doctor ignores the words after the path", status == doctor.FAIL, repr(status))
            doctor.sh = installer(1, "owned-drift\t/hooks\n")
            status, detail = doctor.c_precommit_install()
            ok("doctor names the repair for the drift token",
               status == doctor.FAIL and "--repair" in detail, repr((status, detail)))
            doctor.sh = installer(3, "outside-repo hooksPath: /elsewhere\n")
            status, detail = doctor.c_precommit_install()
            ok("doctor names the way out of an outside hooksPath",
               status == doctor.FAIL and "core.hooksPath" in detail, repr((status, detail)))
            doctor.sh = installer(1, "missing\t/hooks\n", top=os.path.dirname(temporary))
            status, detail = doctor.c_precommit_install()
            ok("doctor inside another repository says git init, not --repair alone",
               status == doctor.WARN and "git init" in detail, repr((status, detail)))
            doctor.sh = installer(0, "something else\n")
            status, _ = doctor.c_precommit_install()
            ok("doctor rejects unrecognised exit-0 hook status", status == doctor.FAIL,
               repr(status))
        finally:
            doctor.sh = original


def test_doctor_engine_drift_uses_export_policy():
    import doctor
    from unittest.mock import patch

    with tempfile.TemporaryDirectory(prefix="doctor-export-") as temporary:
        root, kit = os.path.join(temporary, "source"), os.path.join(temporary, "kit")
        for base, content in ((root, "source bytes\n"), (kit, "kit bytes\n")):
            for name in ("shared.py", "variant.py", "unowned.py"):
                write(base, "tools/" + name, content)
        exporter = (
            "import json, os\n"
            "KIT = os.environ['MOTTORI_KIT']\n"
            "ENGINE = ['shared.py', 'variant.py']\n"
            "PRESERVED_VARIANTS = {'variant.py': 'Different policy.'}\n"
            "def plan_export(selected):\n"
            "    assert selected == {'tools/shared.py'}\n"
            "    with open(os.path.join(os.path.dirname(__file__), 'plan.json')) as stream:\n"
            "        return json.load(stream)\n"
        )
        plan = {"same": ["shared.py"], "changed": [], "missing": []}
        with patch.object(doctor, "ROOT", root), patch.dict(os.environ, {"MOTTORI_KIT": kit}), \
                patch.object(sys, "dont_write_bytecode", True):
            write(root, "tools/kit_sync.py", exporter)
            write(root, "tools/plan.json", json.dumps(plan))
            status, detail = doctor.c_engine_drift()
            ok("doctor accepts tools that are the same bytes and ignores intentional variants and unowned overlap",
               status == doctor.PASS and "1" in detail, repr((status, detail)))

            drift = dict(plan, same=[], changed=["shared.py"])
            write(root, "tools/plan.json", json.dumps(drift))
            status, detail = doctor.c_engine_drift()
            ok("doctor reports true export drift", status == doctor.WARN and "shared.py" in detail,
               repr((status, detail)))

            crashed = doctor.CHECK_CRASHED.format(error_type="kit_sync", error="").split(":")[0]
            # The flag marks an exporter finding, which has its own message; a broken plan is a crash.
            failures = (
                ("missing source", dict(plan, missing=["tools/shared.py"]), True),
                ("missing result field", {"same": ["shared.py"]}, False),
                ("wrong field type", dict(plan, same="shared.py"), False),
                ("incomplete scope", dict(plan, same=[]), False),
                ("unexpected scope", dict(plan, same=["unowned.py"]), False),
                ("duplicated result", dict(plan, same=["shared.py", "shared.py"]), False),
            )
            for label, broken, finding in failures:
                write(root, "tools/plan.json", json.dumps(broken))
                status, detail = doctor.c_engine_drift()
                ok("doctor fails closed on export " + label,
                   status == doctor.FAIL and "PRIVATE-SENTINEL" not in detail
                   and (crashed not in detail) == finding, repr((status, detail)))
            write(root, "tools/plan.json", json.dumps(plan))
            for label, broken in (
                ("runtime error", exporter + "raise RuntimeError('PRIVATE-SENTINEL')\n"),
                ("syntax error", "def broken PRIVATE-SENTINEL\n"),
                ("destination mismatch", exporter + "KIT += '-different'\n"),
                ("empty scope", exporter + "ENGINE = []\n"),
            ):
                write(root, "tools/kit_sync.py", broken)
                status, detail = doctor.c_engine_drift()
                ok("doctor fails closed on exporter " + label,
                   status == doctor.FAIL and "PRIVATE-SENTINEL" not in detail,
                   repr((status, detail)))
            os.unlink(os.path.join(root, "tools/kit_sync.py"))
            ok("doctor does not list kit drift in a tree without an exporter",
               doctor.c_engine_drift() is None)
            write(root, "tools/kit_sync.py", "raise AssertionError('must not load')\n")
            with patch.dict(os.environ, {"MOTTORI_KIT": root}):
                ok("doctor skips the kit's own tree before importing the exporter",
                   doctor.c_engine_drift()[0] == doctor.SKIP)


def test_doctor_does_not_fail_a_tracked_symlink_to_a_public_file():
    root = make_repo(with_config=True)
    try:
        # Only a link into the private area fails; a link to a public file is the owner's business.
        write(root, "docs/a.md", "# public\n")
        os.symlink("docs/a.md", os.path.join(root, "leak.md"))
        subprocess.run(["git", "add", "docs/a.md", "leak.md"], cwd=root, check=True)
        code = ("import sys; sys.path.insert(0, 'tools'); import doctor; "
                "status, detail = doctor.c_symlinks(); print(status); print(detail)")
        r = run(root, "-c", code)
        ok("doctor does not fail a tracked symlink to a public file",
           r.returncode == 0 and r.stdout.splitlines()[0] != "FAIL", r.stdout + r.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ K  gate fail-closed
def test_gate_check_blocks_when_measure_raises():
    root = make_repo(with_config=True)
    try:
        code = r'''
import sys, os, io, json; sys.path.insert(0, "tools")
import gate
# A saved baseline keeps a missing-baseline block from standing in for the exception path.
gate._save_baseline(gate.measure().ids)
gate._mark(gate.EDITS())
def boom(*a, **k): raise RuntimeError("measure exploded")
gate.measure = boom
sys.stdin = io.StringIO("{}")
buf = io.StringIO(); real = sys.stdout; sys.stdout = buf
rc = gate.cmd_check()
sys.stdout = real
out = buf.getvalue()
print("rc", rc)
print("pending", os.path.exists(gate.PENDING()))
try:
    d = json.loads(out)
    print("json", d.get("decision") == "block" and "RuntimeError" in str(d.get("reason")))
except Exception as e:
    print("json", False, repr(out[:120]))
# Resume path: even after an exception, pending stays set and a UserPromptSubmit warning JSON is printed.
gate._mark(gate.EDITS())
buf = io.StringIO(); sys.stdout = buf
rc2 = gate.cmd_resume()
sys.stdout = real
out2 = buf.getvalue()
try:
    d2 = json.loads(out2)
    h = d2.get("hookSpecificOutput", {})
    print("resume", rc2 == 0 and h.get("hookEventName") == "UserPromptSubmit"
          and "gate" in h.get("additionalContext", "").lower()
          and os.path.exists(gate.PENDING()))
except Exception as e:
    print("resume", False, repr(out2[:120]))
# Resume failure path: an exception inside cmd_resume itself still prints the warning JSON.
def root_boom(): raise OSError("root check exploded")
gate._root_ok = root_boom
buf = io.StringIO(); sys.stdout = buf
rc3 = gate.cmd_resume()
sys.stdout = real
out3 = buf.getvalue()
try:
    d3 = json.loads(out3)
    h3 = d3.get("hookSpecificOutput", {})
    print("resume_raise", rc3 == 0 and h3.get("hookEventName") == "UserPromptSubmit"
          and "OSError" in h3.get("additionalContext", ""))
except Exception as e:
    print("resume_raise", False, repr(out3[:120]))
'''
        r = run(root, "-c", code)
        lines = dict(l.split(" ", 1) for l in r.stdout.strip().splitlines() if " " in l)
        ok("K gate exception → pending marker kept", lines.get("pending") == "True", r.stdout + r.stderr[-300:])
        ok("K gate exception → Stop block JSON naming RuntimeError",
           lines.get("json", "").startswith("True"), r.stdout + r.stderr[-300:])
        ok("K resume after failed check → warning JSON, pending kept",
           lines.get("resume", "").startswith("True"), r.stdout + r.stderr[-300:])
        ok("K resume exception → resume_self_failed JSON naming OSError",
           lines.get("resume_raise", "").startswith("True"), r.stdout + r.stderr[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_gate_verdict_checker_key_growth_and_shrink():
    """Removing a checker blocks validation; adding one starts with an empty baseline."""
    import gate
    reason, pull = gate._verdict(gate.Measurement({"linkcheck": set(), "new-checker": set()}), {"linkcheck": set()}, "ok")
    ok("gate key-set growth with zero issues passes and records the new key",
       reason is None and pull is True, repr((reason, pull)))
    reason, pull = gate._verdict(gate.Measurement({"linkcheck": set(), "new-checker": {"x|1"}}), {"linkcheck": set()}, "ok")
    ok("gate key-set growth cannot hide issues: the new checker's issues are new issues",
       reason is not None and pull is False and "x|1" in reason, repr((reason, pull)))
    reason, pull = gate._verdict(gate.Measurement({"linkcheck": set()}), {"linkcheck": set(), "gone": set()}, "ok")
    ok("gate key-set shrink (a removed checker) is still blocked",
       reason is not None and pull is False and "gone" in reason, repr((reason, pull)))


def test_doctor_unrecorded_clean_links_warn_and_show_turn_end_gate():
    """An edit after the last link-check record is not a defect when links are clean.

    Broken links stay FAIL through the link check row, and the missed-gate row names the
    last turn-end gate run so a Stop hook that never fires stays visible.
    """
    root = make_repo(with_config=True)
    try:
        # gate.py reads the instance role through enforce.py.
        shutil.copy2(os.path.join(HERE, "enforce.py"), os.path.join(root, "tools", "enforce.py"))
        write(root, "docs/a.md", "[b](b.md)\n")
        write(root, "docs/b.md", "# b\n")
        subprocess.run(["git", "add", "docs"], cwd=root, check=True)
        commit(root, "docs")
        recorded = run(root, "tools/linkcheck.py")
        # A shell edit after the record plus an untracked new file: the reported state.
        write(root, "docs/a.md", "[b](b.md) edited\n")
        write(root, "docs/c.md", "[a](a.md)\n")
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor, runlog; "
                "print(json.dumps({'gate': doctor.c_missed_gate(), 'links': doctor.c_links(), "
                "'stop': runlog.last_run('gate')[0]}))")

        def probe():
            r = run(root, "-c", code)
            return last_json(r, {"gate": ["?", r.stdout + r.stderr], "links": ["?", ""], "stop": None})

        before = probe()
        ok("doctor: clean links edited after the last record are WARN, not FAIL",
           recorded.returncode == 0 and before["links"][0] == "PASS"
           and before["gate"][0] == "WARN", json.dumps(before, ensure_ascii=False))
        # The warning states missing coverage without claiming a turn-end pass that never ran,
        # and points the Stop hook advice at the runtime in use, since every runtime has the hook.
        ok("doctor: the coverage warning claims no earlier pass and names no single runtime",
           "changed after" not in before["gate"][1]
           and "Claude Code" not in before["gate"][1], json.dumps(before, ensure_ascii=False))
        gate_env = {k: v for k, v in dict(os.environ, MOTTORI_INSTANCE=root).items()
                    if k != "MOTTORI_INTERNAL_RUN"}
        subprocess.run([PY, "tools/gate.py", "baseline"], cwd=root, capture_output=True,
                       text=True, env=gate_env)
        gate = subprocess.run([PY, "tools/gate.py", "check"], cwd=root, input="{}",
                              capture_output=True, text=True, env=gate_env)
        after_gate = probe()
        ok("doctor: a turn-end gate pass over the current tree is PASS",
           gate.returncode == 0 and '"block"' not in gate.stdout and after_gate["gate"][0] == "PASS",
           gate.stdout + gate.stderr + json.dumps(after_gate, ensure_ascii=False))
        write(root, "docs/a.md", "[b](b.md) edited again by a shell\n")
        stale = probe()
        ok("doctor: an edit after the turn-end run is WARN naming that run's time",
           stale["gate"][0] == "WARN" and bool(stale["stop"]) and stale["stop"] in stale["gate"][1]
           and stale["stop"] not in before["gate"][1], json.dumps(stale, ensure_ascii=False))
        write(root, "docs/c.md", "If approved, create `plans/next.md`.\n")
        proposed = probe()
        ok("doctor: a code span naming a file still to be made is WARN, not FAIL",
           proposed["links"][0] == "WARN" and "plans/next.md" in proposed["links"][1],
           json.dumps(proposed, ensure_ascii=False))
        write(root, "docs/c.md", "[gone](missing-fixture.md) `plans/next.md`\n")
        broken = probe()
        ok("doctor: an actually broken link is still FAIL",
           broken["links"][0] == "FAIL", json.dumps(broken, ensure_ascii=False))
        # The coverage row stays a warning in the broken state: the FAIL belongs to the link row.
        ok("doctor: the coverage row does not repeat the link row's FAIL",
           broken["gate"][0] == "WARN", json.dumps(broken, ensure_ascii=False))
        # The turn-end check does not read contributor folders, but the full link check still
        # reports their links, so an advisory code span elsewhere does not soften this one.
        write(root, "docs/c.md", "If approved, create `plans/next.md`.\n")
        write(root, "system/dev/notes.md", "[gone](gone-dev.md)\n")
        dev = probe()
        ok("doctor: a broken link in a contributor-folder document is still FAIL",
           dev["links"][0] == "FAIL" and "gone-dev.md" in dev["links"][1],
           json.dumps(dev, ensure_ascii=False))
        os.remove(os.path.join(root, "system", "dev", "notes.md"))
        os.remove(os.path.join(root, "tools", "gate.py"))
        no_gate = probe()
        ok("doctor: without gate.py the coverage row warns instead of crashing",
           no_gate["gate"][0] == "WARN", json.dumps(no_gate, ensure_ascii=False))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_hook_check_warns_on_failed_or_stale_canary():
    """A working hook command is not a PASS when the last model canary failed or is old."""
    import datetime
    root = make_repo(with_config=True)
    try:
        cmd = state_hook_cmd(root)
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
                f"doctor._hook_cmds = lambda runtime='claude': {{'SessionStart': [{cmd!r}]}}; "
                "print(json.dumps([doctor.c_hook_success()[0], doctor.c_hook_codex_run()[0]]))")
        fresh = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

        def probe(row):
            if row is None:
                path = os.path.join(root, "state", "hook-canary.json")
                if os.path.exists(path):
                    os.remove(path)
            else:
                rows = {runtime: dict(row) for runtime in ("claude", "codex")}
                write(root, "state/hook-canary.json",
                      json.dumps({"schema_version": 1, "runtimes": rows}))
            r = run(root, "-c", code)
            return last_json(r, ["?", r.stdout + r.stderr])

        base = {"checked_at": fresh, "status": "PASS",
                "dispatcher_fired": "verified", "effect": "verified"}
        ok("doctor: hook checks PASS with a fresh passing canary",
           probe(base) == ["PASS", "PASS"], repr(probe(base)))
        ok("doctor: hook checks PASS when no canary was ever run",
           probe(None) == ["PASS", "PASS"], repr(probe(None)))
        failed = dict(base, status="FAIL")
        ok("doctor: hook checks WARN when the last canary failed",
           probe(failed) == ["WARN", "WARN"], repr(probe(failed)))
        unverified = dict(base, effect="not_verified")
        ok("doctor: hook checks WARN when the canary did not verify the effect",
           probe(unverified) == ["WARN", "WARN"], repr(probe(unverified)))
        stale = dict(base, checked_at="2026-01-01T00:00:00+00:00")
        ok("doctor: hook checks WARN when the last canary is older than 30 days",
           probe(stale) == ["WARN", "WARN"], repr(probe(stale)))
        damaged_failure = {"status": "FAIL", "dispatcher_fired": "verified"}
        ok("doctor: hook checks WARN when a damaged canary row still records a failure",
           probe(damaged_failure) == ["WARN", "WARN"], repr(probe(damaged_failure)))
        damaged_pass = {"status": "PASS", "dispatcher_fired": "verified"}
        ok("doctor: hook checks PASS when a damaged canary row records no failure",
           probe(damaged_pass) == ["PASS", "PASS"], repr(probe(damaged_pass)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ N  doctor check details
class _Result:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = code, stdout, stderr


def test_doctor_codex_command_detail_is_not_spliced():
    """The Codex hook-run PASS detail joins the canary evidence instead of cutting a sentence."""
    import doctor
    from unittest.mock import patch
    cmd = state_hook_cmd(doctor.ROOT)
    evidence = "fired=verified · effect=verified · last canary=2026-11-18 (PASS)"
    with patch.object(doctor, "_hook_cmds", lambda runtime="claude": {"SessionStart": [cmd]}), \
            patch.object(doctor, "_canary", lambda runtime: (doctor.PASS, evidence)), \
            patch.object(doctor, "_configured", lambda: True):
        status, detail = doctor.c_hook_codex_run()
    ok("doctor: Codex hook-run detail has no spliced 'dispatcher/fired=' phrase",
       status == doctor.PASS and "dispatcher/fired=" not in detail and evidence in detail,
       repr((status, detail)))


def test_doctor_codex_without_gate_hooks_warns():
    import doctor
    from unittest.mock import patch
    start = "python3 tools/now.py hook-context || echo 'state/NOW.md _private/state/NOW.md unavailable'"
    compact = "python3 tools/now.py precompact --runtime codex"
    hooks = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": start}]}],
                       "PreCompact": [{"hooks": [{"type": "command", "command": compact}]}]}}
    with tempfile.TemporaryDirectory(prefix="doctor-codex-wiring-") as root:
        write(root, ".codex/hooks.json", json.dumps(hooks))
        with patch.object(doctor, "ROOT", root):
            status, detail = doctor._wiring("codex")
            # Codex has every gate event now, so a file without them is no longer an accepted gap.
            ok("doctor: Codex wiring without the gate hooks is WARN naming them",
               status == doctor.WARN and " · gate hooks missing: UserPromptSubmit, PostToolUse, Stop" in detail,
               repr((status, detail)))


def test_doctor_warns_on_recent_hook_errors():
    import datetime
    import doctor
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix="doctor-hook-errors-") as root:
        with patch.object(doctor, "ROOT", root):
            check = doctor.c_hook_errors
            ok("doctor: no hook error log is PASS", check()[0] == doctor.PASS)
            today = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            write(root, "state/.hook-errors.log",
                  "2020-01-01T00:00:00 SessionStart old hook failed\n"
                  "Traceback (most recent call last):\n"
                  f"{today} SessionStart triggers hook failed (tools/triggers.py hook, rc=1)\n")
            status, detail = check()
            ok("doctor: a hook failure dated today is WARN naming the hook",
               status == doctor.WARN and "triggers.py" in detail, repr((status, detail)))
            ok("doctor: a traceback line is not counted as a hook failure",
               detail.startswith(doctor.HOOK_ERRORS_RECENT.format(count=1,
                                          days=doctor.HOOK_ERRORS_DAYS, last="")), detail)
            # Lines the session start notice already showed are history; a new one still warns.
            shown_line = f"{today} SessionStart triggers hook failed (shown)\n"
            write(root, "state/.hook-errors.log", shown_line)
            write(root, "state/.hook-errors.seen", str(len(shown_line.encode("utf-8"))))
            status, detail = check()
            ok("doctor: a failure already shown at session start is PASS, still listed",
               status == doctor.PASS and "(shown)" in detail, repr((status, detail)))
            write(root, "state/.hook-errors.log", shown_line + f"{today} PostToolUse new failure\n")
            status, detail = check()
            ok("doctor: a failure after the shown cursor is WARN",
               status == doctor.WARN and "new failure" in detail and detail.startswith(
                   doctor.HOOK_ERRORS_RECENT.format(count=1, days=doctor.HOOK_ERRORS_DAYS,
                                                    last="")), repr((status, detail)))
            # An optional step past its budget is never announced, so the cursor does not make
            # it history: it is counted on its own and warns.
            overran = f"{today} hook overran (SessionStart step index, timed out after 1s)\n"
            write(root, "state/.hook-errors.log", shown_line + overran)
            write(root, "state/.hook-errors.seen", str(len((shown_line + overran).encode("utf-8"))))
            status, detail = check()
            ok("doctor: a step past its budget is counted on its own and never called shown",
               status == doctor.WARN and detail.count("step index") == 1
               and doctor.HOOK_ERRORS_OVERRAN.format(count=1, days=doctor.HOOK_ERRORS_DAYS, last="") in detail
               and doctor.HOOK_ERRORS_SHOWN.format(count=1, days=doctor.HOOK_ERRORS_DAYS, last="") in detail,
               repr((status, detail)))
            os.remove(os.path.join(root, "state", ".hook-errors.seen"))
            old = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
            write(root, "state/.hook-errors.log", f"{old} SessionStart drive inbox hook failed\n")
            ok("doctor: a hook failure 30 days old is PASS", check()[0] == doctor.PASS)
    ok("doctor: hook error log row is registered",
       any(fn is doctor.c_hook_errors for _id, _label, fn, _git in doctor.CHECKS))
    # Doctor runs the real SessionStart command before this row; that probe must not mark an
    # unseen failure as shown, or no session and no doctor run would ever report it.
    root = make_repo(with_config=True)
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        write(root, "state/.hook-errors.log", f"{today} PostToolUse probe-order failure\n")
        write(root, "state/.hook-errors.seen", "0")
        cmd = 'python3 "$MOTTORI_INSTANCE/tools/now.py" hook-context'
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
                f"doctor._hook_cmds = lambda runtime='claude': {{'SessionStart': [{cmd!r}]}}; "
                "doctor.c_hook_success(); doctor.c_hook_codex_run(); "
                "print(json.dumps(doctor.c_hook_errors()))")
        r = run(root, "-c", code)
        status, detail = last_json(r, ["?", r.stdout + r.stderr])
        ok("doctor: an unseen failure still warns after doctor's own SessionStart probes",
           status == "WARN" and "probe-order" in detail
           and open(os.path.join(root, "state", ".hook-errors.seen")).read() == "0",
           repr((status, detail)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_state_injection_failure_names_the_error():
    root = make_repo(with_config=True)
    try:
        write(root, "tools/now.py", "raise RuntimeError('fixture-now-boom')\n")
        write(root, "tools/hook.sh", open(os.path.join(HERE, "hook.sh"), encoding="utf-8").read())
        cmd = ('sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" now.py hook-context || printf \'%s\' '
               "'{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": \"[kit] failed\"}}'")
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
                f"doctor._hook_cmds = lambda runtime='claude': {{'SessionStart': [{cmd!r}]}}; "
                "print(json.dumps(doctor.c_hook_success()))")
        r = run(root, "-c", code)
        status, detail = last_json(r, ["?", r.stdout + r.stderr])
        ok("doctor: failed state injection names the now.py error",
           status == "FAIL" and "fixture-now-boom" in detail, repr((status, detail)))

        def probe(command):
            r = run(root, "-c", code.replace(repr(cmd), repr(command)))
            return last_json(r, ["?", r.stdout + r.stderr])
        envelope = '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}'
        ok("doctor: a SessionStart command that exits non-zero is FAIL even with valid JSON",
           probe("echo '%s'; exit 9" % (envelope % ("SessionStart", "x")))[0] == "FAIL")
        ok("doctor: a blank context is FAIL",
           probe("echo '%s'" % (envelope % ("SessionStart", " ")))[0] == "FAIL")
        ok("doctor: another event name is FAIL",
           probe("echo '%s'" % (envelope % ("Stop", "x")))[0] == "FAIL")
        # The probe hands the command an event and the internal-run flag, and does not wait on an
        # idle stdin; a command that reads its event and checks the flag passes.
        status, detail = probe('read -r event; case "$event" in *SessionStart*) ;; *) exit 3;; esac; '
                               '[ "$MOTTORI_INTERNAL_RUN" = 1 ] || exit 4; '
                               "echo '%s'" % (envelope % ("SessionStart", "x")))
        ok("doctor: the probe sends a SessionStart event and marks the run internal",
           status == "PASS", repr((status, detail)))
        # Before setup the probes must not append the failure to the instance's own log.
        os.remove(os.path.join(root, "instance", "config.json"))
        os.remove(os.path.join(root, "state", ".hook-errors.log"))  # written by the failure above
        r = run(root, "-c", code.replace(
            "doctor.c_hook_success()", "[doctor.c_hook_success()[0], doctor.c_hook_codex_run()[0]]"))
        ok("doctor: before setup the hook probes warn and leave the hook error log alone",
           last_json(r, None) == ["WARN", "WARN"]
           and not os.path.exists(os.path.join(root, "state", ".hook-errors.log")),
           r.stdout + r.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_precompact_ignores_inherited_git_env():
    root = make_repo(with_config=True)
    scratch = tempfile.mkdtemp(prefix="doctor-git-env-")
    try:
        subprocess.run(["git", "init", "-q", scratch], check=True)
        command = ('sh "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/tools/hook.sh" '
                   "now.py precompact --runtime codex || true")
        write(root, ".codex/hooks.json", json.dumps(
            {"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": command}]}]}}))
        code = ("import sys; sys.path.insert(0,'tools'); import doctor; "
                "print(doctor._simulate_precompact('codex')[0])")
        r = run(root, "-c", code, env_extra={"GIT_DIR": os.path.join(scratch, ".git"),
                                             "GIT_WORK_TREE": scratch})
        leaked = os.path.exists(os.path.join(scratch, "state"))
        ok("doctor: Codex PreCompact simulation passes with GIT_DIR/GIT_WORK_TREE set",
           r.stdout.strip().endswith("PASS"), r.stdout + r.stderr[-300:])
        ok("doctor: Codex PreCompact simulation writes nothing into the GIT_DIR repository",
           not leaked, repr(os.listdir(scratch)))
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)


def test_doctor_time_hook_matches_the_date_command():
    import doctor
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix="doctor-home-") as home:
        def status_for(command):
            settings = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command",
                                                                   "command": command}]}]}}
            write(home, ".claude/settings.json", json.dumps(settings))
            with patch.dict(os.environ, {"HOME": home}):
                return doctor.c_global_hook()[0]
        ok("doctor: a prompt hook that only contains the letters 'date' is not PASS",
           status_for("python3 tools/update_index.py") != doctor.PASS)
        ok("doctor: the date command is PASS", status_for("date '+%F %T'") == doctor.PASS)
        ok("doctor: date inside $(...), backticks or by full path is PASS",
           all(status_for(c) == doctor.PASS
               for c in ('echo "now: $(date)"', "echo `date`", "/bin/date +%F")))
        write(home, ".claude/settings.json", "[]")
        with patch.dict(os.environ, {"HOME": home}):
            status, detail = doctor.c_global_hook()
        ok("doctor: a settings file that is a JSON list is a shape WARN, not a crash",
           status == doctor.WARN and detail == doctor.SETTINGS_SHAPE.format(path="~/.claude/settings.json"), repr((status, detail)))
        # The project file is shape-checked once where it is loaded, for every row that reads it.
        with patch.object(doctor, "ROOT", home), patch.object(doctor, "results", []):
            doctor.check("wiring", doctor.c_hook_wiring)
            status, _name, detail = doctor.results[0]
        ok("doctor: a project settings file of the wrong shape names the file, not a crash",
           status == doctor.FAIL and detail == doctor.SETTINGS_SHAPE.format(path=".claude/settings.json"),
           repr((status, detail)))
        write(home, ".claude/settings.json",
              json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": 5}]}]}}))
        with patch.object(doctor, "ROOT", home), patch.object(doctor, "results", []):
            doctor.check("failure", doctor.c_hook_failure)
            status, _name, detail = doctor.results[0]
        ok("doctor: a hook command that is not a string names the file, not a crash",
           status == doctor.FAIL and detail == doctor.SETTINGS_SHAPE.format(path=".claude/settings.json"),
           repr((status, detail)))


def test_doctor_has_no_slash_command_row():
    import doctor
    ok("doctor: the always-passing slash command row is gone",
       not any(getattr(fn, "__name__", "") == "c_commands" for _id, _label, fn, _git in doctor.CHECKS))


def test_doctor_tools_run_probes_only_now_trailer():
    import doctor
    from unittest.mock import patch
    calls = []

    def fake(stdout):
        def sh(*cmd, **_kw):
            calls.append(cmd)
            return _Result(1, stdout)
        return sh
    with patch.object(doctor, "sh", fake("x\n#issues 0\n")):
        status = doctor.c_tools_run()[0]
    ok("doctor: tools-run with the #issues trailer is PASS and runs one command",
       status == doctor.PASS and len(calls) == 1, repr((status, calls)))
    with patch.object(doctor, "sh", fake("x\n")):
        status = doctor.c_tools_run()[0]
    ok("doctor: tools-run without the trailer is FAIL", status == doctor.FAIL)


def test_doctor_recall_counts_sessions_not_notices():
    import doctor
    from unittest.mock import patch
    import paths
    import transcripts as reader
    notice = reader.NO_TRANSCRIPTS.format(path="/nonexistent")
    # A folder with no session readable warns only once a turn end is on record there.
    for transcripts, turn_end, expected in (("/nonexistent", "2026-11-01", doctor.SKIP),
                                            (HERE, None, doctor.SKIP), (HERE, "2026-11-01", doctor.WARN)):
        with patch.object(doctor, "sh", lambda *a, **k: _Result(0, notice + "\n")), \
                patch.object(doctor, "_last_turn_end_run", lambda t=turn_end: t), \
                patch.object(paths, "transcripts", lambda root=None, t=transcripts: t):
            status, detail = doctor.c_recall()
        ok(f"doctor: recall with only the no-records notice is {expected}",
           status == expected, repr((status, detail)))
    rows = ("[claude] a.jsonl                                                 1.0 MB\n"
            "[codex ] b.jsonl                                                 2.0 MB\n")
    # The retention text reads the real user and instance settings, whose day count would
    # leak digits into the count assertion when this runs outside the runner.
    with patch.object(doctor, "sh", lambda *a, **k: _Result(0, rows)), \
            patch.object(doctor, "_transcript_retention", lambda: "retention"):
        status, detail = doctor.c_recall()
    ok("doctor: recall with two session rows is PASS with count 2",
       status == doctor.PASS and "2" in detail and "1" not in detail.replace("2", ""),
       repr((status, detail)))


def test_doctor_growth_git_threshold_and_message():
    import doctor
    root = make_repo(with_config=True)
    try:
        plenty = lambda _path: type("U", (), {"free": 10 ** 15})()
        over = doctor._growth_report(root, {"thresholds": {"growth_git_max_bytes": 1}},
                                     disk_usage=plenty)
        roomy = doctor._growth_report(root, {"thresholds": {"growth_git_max_bytes": 10 ** 15}},
                                      disk_usage=plenty)
        ok("doctor: growth honours a configured .git limit",
           over[2]["git"]["state"] == "over" and roomy[2]["git"]["state"] == "ok",
           repr((over[2]["git"], roomy[2]["git"])))
        ok("doctor: the .git warning does not blame the kit's engine-only tracking",
           over[2]["git"]["state"] == "over" and "engine" not in over[1],
           repr((over[2]["git"], over[1])))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_person_ledger_counts_private_journal():
    root = make_repo(with_config=True)
    try:
        shutil.copy2(os.path.join(HERE, "person_ledger.py"), os.path.join(root, "tools", "person_ledger.py"))
        write(root, "_private/self-portrait-mirror.md", "# ledger\nlast-reviewed: 2026-01-01\n")
        write(root, "_private/state/journal-2026-02.md", "".join(
            f"- 2026-02-{day:02d}T10:00+00:00 [system/decision] fixture decision {day}\n"
            for day in range(1, 21)))
        code = ("import sys; sys.path.insert(0,'tools'); import doctor; "
                "print(doctor.c_person_ledger()[0])")
        r = run(root, "-c", code)
        ok("doctor: 20 private decisions after the ledger date make the ledger stale",
           r.stdout.strip().endswith("WARN"), r.stdout + r.stderr[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_symlink_to_private_sibling_is_not_private():
    root = make_repo(with_config=True)
    try:
        write(root, "_private_old/x.md", "old\n")
        os.symlink("_private_old/x.md", os.path.join(root, "old.md"))
        subprocess.run(["git", "add", "old.md"], cwd=root, check=True)
        code = ("import sys; sys.path.insert(0, 'tools'); import doctor; "
                "status, detail = doctor.c_symlinks(); "
                "print(status, detail == 'tracked symbolic links with targets outside _private: 1')")
        r = run(root, "-c", code)
        ok("doctor: a symlink into _private_old is reported as outside, not private",
           r.stdout.strip() == "WARN True", r.stdout + r.stderr[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_linkcheck_scope_uses_the_shared_hash():
    root = make_repo(with_config=True)
    try:
        write(root, "docs/a b.md", "# a\n")
        write(root, "state/NOW.md", "# generated\n")
        subprocess.run(["git", "add", "docs"], cwd=root, check=True)
        code = ("import sys, subprocess, os; sys.path.insert(0,'tools'); import doctor, linkcheck; "
                "paths = [os.fsdecode(p) for p in subprocess.run(['git', 'ls-files', '-z', "
                "'--cached', '--others', '--exclude-standard', '*.md'], capture_output=True)"
                ".stdout.split(b'\\0') if p]; "
                "print(doctor._linkcheck_scope() == linkcheck.scope_hash(paths, doctor.ROOT))")
        r = run(root, "-c", code)
        ok("doctor: link-check scope equals linkcheck.scope_hash", r.stdout.strip() == "True",
           r.stdout + r.stderr[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_status_reads_renames_and_unicode_names():
    root = make_repo(with_config=True)
    try:
        write(root, "tools/engine_fixture.py", "x = 1\n")
        subprocess.run(["git", "add", "tools/engine_fixture.py"], cwd=root, check=True)
        commit(root, "engine")
        subprocess.run(["git", "mv", "tools/engine_fixture.py", "tools/engine_renamed.py"],
                       cwd=root, check=True)
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
                "print(json.dumps(doctor.c_upstream()))")
        r = run(root, "-c", code)
        status, detail = last_json(r, ["?", r.stdout + r.stderr])
        ok("doctor: a staged rename of an engine file is WARN naming it",
           status == "WARN" and "tools/engine_renamed.py" in detail, repr((status, detail)))
        subprocess.run(["git", "reset", "-q", "--hard"], cwd=root, check=True)
        # Commit the fixture's own files so the only untracked path is the one under test.
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        commit(root, "fixture")
        # A file under the private area that was forced into the index is named, decoded, by the row.
        name = "_private/한글 메모.txt"
        write(root, name, "x\n")
        subprocess.run(["git", "add", "-f", name], cwd=root, check=True)
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
                "print(json.dumps(doctor.c_ignored(), ensure_ascii=False))")
        r = run(root, "-c", code)
        ok("doctor: a staged private file with a Korean spaced name fails the row and is named decoded",
           '"FAIL"' in r.stdout and name in r.stdout, r.stdout + r.stderr[-300:])
        subprocess.run(["git", "rm", "-q", "--cached", name], cwd=root, check=True)
        # A name that is not UTF-8 (possible on Linux) is staged straight into the index.
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=root, input=b"x\n",
                              capture_output=True, check=True).stdout.decode().strip()
        subprocess.run(["git", "update-index", "--add", "--cacheinfo", "100644", blob,
                        os.fsdecode(b"tools/\xff\xfe bad.md")], cwd=root, check=True)
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
                "print(json.dumps([doctor.c_upstream(), doctor.c_ignored()]))")
        r = run(root, "-c", code)
        upstream, ignored = last_json(r, [None, r.stdout + r.stderr[-300:]])
        ok("doctor: a non-UTF-8 staged name is listed escaped, not a crash",
           upstream is not None and upstream[0] == "WARN" and "\\xff\\xfe bad.md" in upstream[1]
           and ignored[0] in ("PASS", "WARN", "FAIL"), repr((upstream, ignored)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_full_shape_run_takes_only_the_kit_tests_in_an_installation():
    """In an installation, the synthetic instance of the full shape run runs the test files the kit
    ships; a test the installation added reads its own data and runs in its own tree (KIT-DR-091)."""
    from testlib import engine_tests
    names = ["lib/x.py", "tests/test_kit.py", "tests/test_own_data.py", "tests/testlib.py"]
    in_kit = engine_tests(names, ["tools/lib/x.py", "tools/tests/test_kit.py", "tools/tests/testlib.py"])
    ok("an installation's own test file stays out of the synthetic instance's run",
          in_kit == ["tests/test_kit.py"], repr(in_kit))
    every = engine_tests(names, None)
    ok("a tree without the kit file list runs every test file",
          every == ["tests/test_kit.py", "tests/test_own_data.py"], repr(every))


def test_doctor_counts_only_the_kit_files_as_engine_changes():
    """An installation that keeps folders of its own in Git (KIT-DR-090): a change to them, or to the
    lines below the marker of .gitignore, is not an engine change; a change to a kit file is."""
    root = make_repo(with_config=True)
    marker = "# --- this installation's own lines ---"
    code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
            "print(json.dumps(doctor.c_upstream()))")
    try:
        write(root, "tools/engine_fixture.py", "x = 1\n")
        write(root, "notes/mine.md", "# mine\n")
        write(root, ".gitignore", f"*.tmp\n{marker}\n")
        write(root, "system/dev/kit-files.txt", ".gitignore\nsystem/dev/kit-files.txt\ntools/engine_fixture.py\n")
        subprocess.run(["git", "add", "-f", ".gitignore", "tools/engine_fixture.py", "notes/mine.md",
                        "system/dev/kit-files.txt"], cwd=root, check=True)
        commit(root, "kit and own")
        write(root, "notes/mine.md", "# mine, changed\n")
        write(root, ".gitignore", f"*.tmp\n{marker}\n!/notes/\n")
        status, detail = last_json(run(root, "-c", code), ["?", ""])
        ok("doctor: an own folder and the ignore file's own block are not engine changes",
           status == "PASS", repr((status, detail)))
        write(root, ".gitignore", f"*.tmp\n*.log\n{marker}\n!/notes/\n")
        write(root, "tools/engine_fixture.py", "x = 2\n")
        status, detail = last_json(run(root, "-c", code), ["?", ""])
        ok("doctor: a kit file and the kit's lines of the ignore file are engine changes",
           status == "WARN" and "tools/engine_fixture.py" in detail and ".gitignore" in detail
           and "notes/mine.md" not in detail, repr((status, detail)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_personal_untracked_count_is_information():
    root = make_repo(with_config=True)
    try:
        for i in range(25):
            write(root, f"notes/n{i}.txt", "x\n")
        code = ("import sys; sys.path.insert(0,'tools'); import doctor; "
                "print(doctor.c_ignored()[0])")
        r = run(root, "-c", code)
        ok("doctor: 25 untracked files of the owner's are PASS",
           r.stdout.strip().endswith("PASS"), r.stdout + r.stderr[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_kit_export_finding_is_not_a_crash():
    import doctor
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix="doctor-export-invalid-") as temporary:
        root, kit = os.path.join(temporary, "source"), os.path.join(temporary, "kit")
        write(kit, "tools/shared.py", "kit\n")
        write(root, "tools/kit_sync.py",
              "import os\nKIT = os.environ['MOTTORI_KIT']\nENGINE = ['shared.py']\n"
              "PRESERVED_VARIANTS = {}\n"
              "def plan_export(selected):\n"
              "    return {'same': [], 'changed': [], 'missing': ['tools/shared.py']}\n")
        with patch.object(doctor, "ROOT", root), patch.dict(os.environ, {"MOTTORI_KIT": kit}), \
                patch.object(sys, "dont_write_bytecode", True):
            status, detail = doctor.c_engine_drift()
    crashed = doctor.CHECK_CRASHED.format(error_type="kit_sync", error="")
    ok("doctor: an export that would miss a file is FAIL with its own message, not 'check crashed'",
       status == doctor.FAIL and crashed.split(":")[0] not in detail
       and "PRIVATE-SENTINEL" not in detail, repr((status, detail)))


def test_doctor_text_output_keeps_pass_detail():
    import doctor
    import io
    from contextlib import redirect_stdout
    from unittest.mock import patch
    fake = [("fixture_row", "fixture row", lambda: (doctor.PASS, "fixture-pass-detail"), False)]
    out = io.StringIO()
    with patch.object(doctor, "CHECKS", fake), patch.dict(doctor.LABELS, fixture_row="fixture row"), \
            patch.object(doctor, "JSON_OUTPUT", False), patch.object(doctor, "ALL_OUTPUT", True), \
            redirect_stdout(out):
        doctor.main()
    ok("doctor: --all text output shows a PASS row's detail", "fixture-pass-detail" in out.getvalue(),
       out.getvalue()[-300:])


def test_doctor_manual_list_holds_only_what_a_person_can_check():
    root = make_repo(with_config=True)
    try:
        code = ("import sys, json; sys.path.insert(0,'tools'); import doctor; "
                "print(json.dumps([n for n, _ in doctor._manual()], ensure_ascii=False))")
        marker = "[system/state] compaction occurred"
        write(root, "state/journal-2026-11.md", f"- 2026-11-01T10:00 {marker}\n")
        r = run(root, "-c", code)
        names = last_json(r, [r.stdout + r.stderr])
        joined = " ".join(names)
        # The canary item needs an installed runtime and the Codex rules item needs Codex.
        runtimes = (1 if shutil.which("claude") or shutil.which("codex") else 0) + bool(shutil.which("codex"))
        ok("doctor: with a recorded compaction the list holds neither PreCompact nor a policy item",
           "PreCompact" not in joined and len(names) == runtimes, repr(names))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ M  NOW personal pointer
def test_now_renders_unspecified_personal_pointer():
    root = make_repo(with_config=True)
    try:
        r = run(root, "tools/now.py", "log", "[system/state] fixture")
        r = run(root, "tools/now.py", "render")
        now = open(os.path.join(root, "state", "NOW.md"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(root, "state", "NOW.md")) else ""
        ok("M fresh NOW has no row for an unset personal pointer, and never `None`",
           now and "**Personal**" not in now and "`None`" not in now,
           (now[:300] or r.stderr[-300:]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ Python minimum
def test_python_minimum_is_one_number():
    """README, SETUP, the CI matrix and doctor must state the same minimum Python.

    recall.py and build_memory_map.py use str.removesuffix and Path.is_relative_to,
    which exist only from 3.9, so a lower stated minimum lets doctor pass on an
    interpreter where those tools crash."""
    import re as _re
    import doctor

    docs = ("README.md", "SETUP.md", ".github/workflows/gates.yml")
    if not all(os.path.isfile(os.path.join(ROOT, rel)) for rel in docs):
        # An installed instance may not carry the kit's own documents and CI files.
        print("- Python minimum: not applicable outside the kit tree")
        return

    def read(rel):
        return open(os.path.join(ROOT, rel), encoding="utf-8").read()

    def ver(text):
        return tuple(int(x) for x in text.split("."))

    readme = _re.search(r"Requirements: Python (\d+\.\d+) or later", read("README.md"))
    setup = _re.search(r"python3 --version\s+# (\d+\.\d+) or later", read("SETUP.md"))
    matrix = [ver(m) for m in _re.findall(r'python: "(\d+\.\d+)"', read(".github/workflows/gates.yml"))]
    found = {
        "README.md": ver(readme.group(1)) if readme else None,
        "SETUP.md": ver(setup.group(1)) if setup else None,
        "gates.yml": min(matrix) if matrix else None,
    }

    class _V(tuple):
        major, minor, micro = property(lambda s: s[0]), property(lambda s: s[1]), property(lambda s: s[2])

    def doctor_accepts(v):
        saved = doctor.sys.version_info
        doctor.sys.version_info = _V(v)
        try:
            return doctor.c_python()[0] == doctor.PASS
        finally:
            doctor.sys.version_info = saved

    accepted = [v for v in ((3, 7), (3, 8), (3, 9), (3, 10)) if doctor_accepts(v + (0,))]
    found["doctor"] = min(accepted) if accepted else None
    ok("Python minimum: README, SETUP, CI matrix and doctor all say 3.9",
       all(v == (3, 9) for v in found.values()), json.dumps({k: list(v) if v else v for k, v in found.items()}))


def test_ci_runs_only_in_the_kit_repository():
    """The workflow's one job runs only in a repository named like the kit, so a user's workspace
    pushed under another name runs nothing; it covers Python 3.9 and 3.12 on Linux and macOS and
    runs the suite and the three static checks."""
    import re as _re
    path = os.path.join(ROOT, ".github", "workflows", "gates.yml")
    if not os.path.isfile(path):
        print("- CI workflow: not applicable outside the kit tree")
        return
    text = open(path, encoding="utf-8").read()
    jobs = _re.findall(r"^  ([\w-]+):$", text.split("\njobs:\n", 1)[1], _re.M)
    ok("CI: one job, run only in a repository named mottori-kit",
       jobs == ["gates"] and "\n    if: github.event.repository.name == 'mottori-kit'\n" in text, text[:600])
    rows = set(_re.findall(r'\{os: ([\w.-]+), python: "(\d+\.\d+)"\}', text))
    ok("CI: Python 3.9 and 3.12 on Linux and macOS",
       rows == {("ubuntu-24.04", "3.9"), ("ubuntu-latest", "3.12"), ("macos-latest", "3.9"),
                ("macos-latest", "3.12")}, repr(rows))
    commands = [line.strip() for line in text.splitlines()
                if line.strip().startswith(("python3 ", "git diff", "run: python3"))]
    ok("CI: the suite, linkcheck, evidencecheck and git diff --check, nothing else",
       commands == ["run: python3 tools/tests/run.py --full", "python3 tools/linkcheck.py",
                    "python3 tools/dev/evidencecheck.py", 'git diff --check "$BASE" HEAD'], repr(commands))


def test_a_commit_does_not_judge_a_state_page_git_ignores():
    """A page Git ignores is in no commit, so a changed config does not stop a commit over it; a
    tracked page is judged as before."""
    root = make_repo(with_config=True)
    try:
        run(root, "tools/now.py", "log", "[system/state] fixture")
        cfg_path = os.path.join(root, "instance", "config.json")
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        cfg["thresholds"] = {"now_hook_max_bytes": 5000}
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"))
        r = run(root, "tools/now.py", "check", "--issues", "--portable")
        ok("now check --portable: an ignored page is not asked to be staged",
           "now-input-newer" not in r.stdout, r.stdout + r.stderr)
        subprocess.run(["git", "add", "-f", "state/NOW.md"], cwd=root, check=True)
        r = run(root, "tools/now.py", "check", "--issues", "--portable")
        ok("now check --portable: a tracked stale page is still judged", "now-input-newer" in r.stdout,
           r.stdout + r.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_lines_past_the_row_limits_are_counted_in_the_view():
    """Well under the byte cap, the view shows eight decisions and twelve recent lines; the rest are
    counted in one line instead of vanishing."""
    root = make_repo(with_config=True)
    try:
        for i in range(30):
            run(root, "tools/now.py", "log", f"[launch/decision] decision number {i:02d}")
        r = run(root, "tools/now.py", "context")
        shown = [n for n in range(30) if f"decision number {n:02d}" in r.stdout]
        ok("now context: lines past the row limits are counted",
           len(shown) < 30 and f"[… {30 - len(shown)} older event line(s) omitted" in r.stdout
           and len(r.stdout.encode("utf-8")) < 6000, r.stdout[-600:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_unreadable_private_thread_list_is_said_to_be_unavailable():
    """A private registry that cannot be read is not the same as no threads."""
    root = make_repo(with_config=True)
    try:
        write(root, "_private/state/threads.json", "not json")
        r = run(root, "tools/now.py", "threads")
        ok("now.py threads: an unreadable private registry is unavailable, not absent",
           r.returncode == 1 and "private threads unavailable" in r.stdout
           and "no threads registered" not in r.stdout, r.stdout + r.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_log_help_answers_with_the_types_and_tracks_of_this_workspace():
    """An agent unsure how to write a line asks the command itself, which answers and writes nothing."""
    root = make_repo(with_config=True)
    try:
        before = sorted(os.listdir(os.path.join(root, "state"))) if os.path.isdir(os.path.join(root, "state")) else []
        for args, code in ((("log", "--help"), 0), (("log", "-h"), 0), (("log",), 1)):
            r = run(root, "tools/now.py", *args)
            ok(f"now.py {' '.join(args)}: usage with the types and the tracks",
               r.returncode == code and "type    one of: decision" in r.stdout and "track   " in r.stdout
               and "--private keeps the line under _private/" in r.stdout, r.stdout + r.stderr)
        after = sorted(os.listdir(os.path.join(root, "state"))) if os.path.isdir(os.path.join(root, "state")) else []
        ok("now.py log --help writes no journal line", before == after, repr((before, after)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_fresh_install_rejects_malformed_summaries,
               test_linkcheck_exit_codes_and_pending,
               test_linkcheck_optional_destinations_are_exact_and_instance_owned,
               test_linkcheck_measures_non_ascii_spaced_filenames,
               test_linkcheck_extracted_tree_uses_only_ignored_root_fallback,
               test_linkcheck_exclude_config_applies_only_without_all,
               test_doctor_codex_armed_and_git_version,
               test_doctor_precommit_reads_the_check_status_words,
               test_doctor_link_row_says_when_the_owners_folders_were_not_read,
               test_doctor_shows_the_track_summary_reminder_the_check_gives,
               test_doctor_engine_drift_uses_export_policy,
               test_doctor_does_not_fail_a_tracked_symlink_to_a_public_file,
               test_gate_check_blocks_when_measure_raises,
               test_gate_verdict_checker_key_growth_and_shrink,
               test_doctor_unrecorded_clean_links_warn_and_show_turn_end_gate,
               test_doctor_hook_check_warns_on_failed_or_stale_canary,
               test_doctor_codex_command_detail_is_not_spliced,
               test_doctor_codex_without_gate_hooks_warns,
               test_doctor_warns_on_recent_hook_errors,
               test_doctor_state_injection_failure_names_the_error,
               test_doctor_precompact_ignores_inherited_git_env,
               test_doctor_time_hook_matches_the_date_command,
               test_doctor_has_no_slash_command_row,
               test_doctor_tools_run_probes_only_now_trailer,
               test_doctor_recall_counts_sessions_not_notices,
               test_doctor_growth_git_threshold_and_message,
               test_doctor_person_ledger_counts_private_journal,
               test_doctor_symlink_to_private_sibling_is_not_private,
               test_doctor_linkcheck_scope_uses_the_shared_hash,
               test_doctor_status_reads_renames_and_unicode_names,
               test_doctor_counts_only_the_kit_files_as_engine_changes,
               test_the_full_shape_run_takes_only_the_kit_tests_in_an_installation,
               test_doctor_personal_untracked_count_is_information,
               test_doctor_kit_export_finding_is_not_a_crash,
               test_doctor_text_output_keeps_pass_detail,
               test_doctor_manual_list_holds_only_what_a_person_can_check,
               test_now_renders_unspecified_personal_pointer,
               test_a_commit_does_not_judge_a_state_page_git_ignores,
               test_lines_past_the_row_limits_are_counted_in_the_view,
               test_an_unreadable_private_thread_list_is_said_to_be_unavailable,
               test_log_help_answers_with_the_types_and_tracks_of_this_workspace,
               test_python_minimum_is_one_number,
               test_ci_runs_only_in_the_kit_repository):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            FAILED.append(fn.__name__)
            print(f"✗ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"install checks: {len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(0 if not FAILED else 1)
