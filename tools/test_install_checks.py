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

from testlib import run_test

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

PASSED, FAILED = [], []


def ok(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("✓ " if cond else "✗ ") + name + (f": {detail}" if detail and not cond else ""))


def make_repo(with_config=True):
    """Create a temporary repository with engine tools and Markdown files."""
    root = tempfile.mkdtemp(prefix="install-checks.")
    os.makedirs(os.path.join(root, "tools"))
    for name in ("memlib.py", "i18n.py", "linkcheck.py", "doctor.py", "gate.py", "now.py", "hookdiag.py",
                 "coherence.py"):
        src = os.path.join(HERE, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(root, "tools", name))
    os.makedirs(os.path.join(root, "system"))
    os.makedirs(os.path.join(root, "state"))
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("state/\n_private/\nsystem/memory-config.json\nsystem/instance-rules.md\n"
                "system/decisions.md\nsystem/rituals.local.md\n")
    if with_config:
        cfg = json.load(open(os.path.join(ROOT, "templates", "memory-config.json"), encoding="utf-8")) \
            if os.path.exists(os.path.join(ROOT, "templates", "memory-config.json")) else \
            json.load(open(os.path.join(ROOT, "system", "memory-config.json"), encoding="utf-8"))
        cfg.setdefault("instance", {})["name"] = "fixture"
        cfg["instance"]["context"] = "personal"
        cfg["tracks"] = []
        cfg["threads"] = []
        cfg["personal_pointer"] = None      # A new instance retains the null template value.
        json.dump(cfg, open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8"))
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=fixture@example.invalid", "-c", "user.name=fixture",
                    "commit", "-q", "--allow-empty", "-m", "init"], cwd=root, check=True)
    return root


def run(root, *args, env_extra=None):
    env = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_INTERNAL_RUN="")
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
            ["bash", os.path.join(ROOT, "tools", "test_fresh_install.sh"),
             f"--judge-{kind}", str(subprocess_rc), output_path],
            cwd=ROOT, capture_output=True, text=True, timeout=3,
        )


# ------------------------------------------------------------ X12  fresh gate parsing
def test_fresh_install_rejects_malformed_summaries():
    if not os.path.isfile(os.path.join(ROOT, "tools", "test_fresh_install.sh")):
        # The initial-install gate belongs to the deployment kit, not installed instances.
        print("- X12: not applicable here (no tools/test_fresh_install.sh: installed instance)")
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
       all(r.returncode != 0 and "측정불능" in (r.stdout + r.stderr) for r in malformed),
       "\n".join(r.stdout + r.stderr for r in malformed))

    abnormal = run_fresh_judge("doctor", 7, valid_doctor)
    ok("X12 nonzero doctor with FAIL 0 is unmeasurable FAIL",
       abnormal.returncode != 0 and "측정불능" in (abnormal.stdout + abnormal.stderr),
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
        write(root, "README.md", "see `system/memory-config.json` and [rules](system/instance-rules.md)\n")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("F pre-setup: setup-created targets are PENDING, exit 0",
           r.returncode == 0 and "PENDING" in r.stdout and "broken: 0" in r.stdout, r.stdout[-300:])
        write(root, "system/typo.md", "[x](nope-zz.md)\n")
        subprocess.run(["git", "add", "system/typo.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("J broken → exit 1", r.returncode == 1 and "BROKEN system/typo.md -> nope-zz.md" in r.stdout,
           r.stdout[-300:])
        r = run(root, "tools/linkcheck.py", "--issues")
        ok("J --issues stays exit 0 with #issues trailer", r.returncode == 0 and "#issues 1" in r.stdout,
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
        write(root, "system/memory-config.json", "{}")
        r = run(root, "tools/linkcheck.py")
        ok("F post-setup: missing instance-rules is BROKEN, exit 1",
           r.returncode == 1 and "BROKEN README.md -> system/instance-rules.md" in r.stdout, r.stdout[-300:])
        ok("F post-setup: missing gate baseline is BROKEN",
           "BROKEN SETUP.md -> state/.gate-baseline.json" in r.stdout, r.stdout[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ L  scope hash with spaces
def test_linkcheck_optional_destinations_are_exact_and_instance_owned():
    for configured in (False, True):
        root = make_repo(with_config=configured)
        phase = "post-setup" if configured else "pre-setup"
        destinations = ("_private/deep-pass/ledger.md", "system/debate/_p_review.md")
        try:
            with open(os.path.join(root, ".gitignore"), "a") as stream:
                stream.write("system/debate/_p_review.md\n")
            write(root, "README.md", "[ledger](_private/deep-pass/ledger.md)\n"
                  "[prompt](system/debate/_p_review.md)\n")
            result = run(root, "tools/linkcheck.py")
            ok(f"optional destinations remain distinct from setup pending ({phase})",
               result.returncode == 0 and result.stdout.count("OPTIONAL README.md ->") == 2
               and "PENDING" not in result.stdout, result.stdout)
            if os.path.isfile(os.path.join(ROOT, "tools", "test_fresh_install.sh")):
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
            result = run(root, "tools/linkcheck.py")
            ok(f"first use does not make later absence a required-file failure ({phase})",
               result.returncode == 0 and result.stdout.count("OPTIONAL README.md ->") == 2,
               result.stdout)

            with open(os.path.join(root, "README.md"), "a") as stream:
                stream.write("[typo](_private/deep-pass/ledger-typo.md)\n"
                             "[other prompt](system/debate/_p_typo.md)\n")
            result = run(root, "tools/linkcheck.py")
            ok(f"neighboring private paths and prompt typos remain broken ({phase})",
               result.returncode == 1
               and "BROKEN README.md -> _private/deep-pass/ledger-typo.md" in result.stdout
               and "BROKEN README.md -> system/debate/_p_typo.md" in result.stdout,
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
        code = ("import sys; sys.path.insert(0,'tools'); import doctor; "
                "print(doctor.c_missed_gate()[0])")
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


def test_scope_hash_matches_with_spaced_filename():
    root = make_repo(with_config=True)
    try:
        write(root, "system/a b.md", "# spaced\n")
        subprocess.run(["git", "add", "system/a b.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("L linkcheck runs on spaced filename", r.returncode == 0, r.stdout[-200:])
        code = ("import sys; sys.path.insert(0,'tools'); import doctor; "
                "print(doctor.c_missed_gate()[0])")
        r = run(root, "-c", code)
        ok("L doctor.c_missed_gate PASS after linkcheck (scope hashes agree)",
           r.stdout.strip().endswith("PASS"), r.stdout[-200:] + r.stderr[-200:])
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
        config_path = os.path.join(root, "system", "memory-config.json")
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
    return {r: {"declared": True, "command_valid": valid, "armed": armed, "matcher_reachable": True}
            for r in ("injector", "side_effect", "guard", "observer", "enforcer", "recovery")}
hookdiag.codex_hooks_list = fake_list
hookdiag.compact_summary = lambda rep: "x"
hookdiag.codex_runtime_report = lambda hooks: report(False)
print("unarmed", doctor.c_hook_codex_armed()[0])
hookdiag.codex_runtime_report = lambda hooks: report(True)
print("armed", doctor.c_hook_codex_armed()[0])
hookdiag.codex_runtime_report = lambda hooks: report(False, valid=False)
print("invalid", doctor.c_hook_codex_armed()[0])
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
        ok("E codex armed → PASS", out.get("armed") == "PASS", r.stdout)
        ok("E codex command invalid → FAIL", out.get("invalid") == "FAIL", r.stdout)
        ok("E codex loader error → FAIL", out.get("loader") == "FAIL", r.stdout)
        ok("git 2.4 → FAIL", out.get("too_old") == "FAIL", r.stdout)
        ok("git 2.5 minimum → PASS", out.get("minimum") == "PASS", r.stdout)
        ok("git 2.35 → PASS", out.get("old") == "PASS", r.stdout)
        ok("git 2.36 → PASS", out.get("new") == "PASS", r.stdout)
        ok("git 2.50 (Apple) → PASS", out.get("apple") == "PASS", r.stdout)
        ok("git unparsable → WARN", out.get("unparsable") == "WARN", r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_remote_allowlist_is_host_and_path_bounded():
    import doctor
    allowlist = ["https://github.com/trusted/repo"]
    ok("valve exact remote is allowed",
       doctor._allowed("https://github.com/trusted/repo.git", allowlist))
    ok("valve child path is allowed",
       doctor._allowed("https://github.com/trusted/repo/child.git", allowlist))
    ok("valve embedded trusted URL on hostile host is rejected",
       not doctor._allowed(
           "https://evil.invalid/https://github.com/trusted/repo", allowlist))
    ok("valve sibling path is rejected",
       not doctor._allowed("https://github.com/trusted/repository", allowlist))


def test_doctor_precommit_accepts_localized_status_tokens():
    import doctor
    original = doctor.sh

    class Result:
        stderr = ""

        def __init__(self, code, output):
            self.returncode = code
            self.stdout = output

    try:
        for output in ("current: /hooks\n", "현재(current): /hooks\n"):
            doctor.sh = lambda *args, value=output: Result(0, value)
            status, _ = doctor.c_precommit_install()
            ok(f"doctor accepts localized current token {output.split(':', 1)[0]}",
               status == doctor.PASS, repr((status, output)))
        for output in ("missing: /hooks\n", "없음(missing): /hooks\n"):
            doctor.sh = lambda *args, value=output: Result(1, value)
            status, _ = doctor.c_precommit_install()
            ok(f"doctor accepts localized missing token {output.split(':', 1)[0]}",
               status == doctor.WARN, repr((status, output)))
    finally:
        doctor.sh = original


def test_doctor_kit_shape_markers_fail_closed_individually():
    import doctor
    with tempfile.TemporaryDirectory(prefix="doctor-kit-shape-") as temporary:
        for marker in ("setup.sh", "templates/memory-config.json",
                       "system/engine-inventory.txt", "system/review-manifest.yaml"):
            root = os.path.join(temporary, marker.replace("/", "-"))
            write(root, marker, "fixture\n")
            ok(f"kit shape marker survives partial deletion: {marker}", doctor._is_kit_tree(root))
        empty = os.path.join(temporary, "installed")
        os.makedirs(empty)
        ok("installed shape has no kit marker", not doctor._is_kit_tree(empty))


def test_doctor_keeps_release_regressions_out_of_interactive_run():
    import doctor
    original_mode, original_sh = doctor.RELEASE_MODE, doctor.sh
    try:
        doctor.RELEASE_MODE = False
        doctor.sh = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("interactive doctor executed a release suite")
        )
        status, detail = doctor.c_regression()
        ok("interactive doctor skips release regression suites",
           status == doctor.SKIP and "release/CI" in detail, repr((status, detail)))
    finally:
        doctor.RELEASE_MODE, doctor.sh = original_mode, original_sh


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
        plan = {"same": ["shared.py"], "changed": [], "missing": [], "leaks": []}
        with patch.object(doctor, "ROOT", root), patch.dict(os.environ, {"MOTTORI_KIT": kit}), \
                patch.object(sys, "dont_write_bytecode", True):
            write(root, "tools/kit_sync.py", exporter)
            write(root, "tools/plan.json", json.dumps(plan))
            status, detail = doctor.c_engine_drift()
            ok("doctor accepts export-normalized tools and ignores intentional variants and unowned overlap",
               status == doctor.PASS and "1" in detail, repr((status, detail)))

            drift = dict(plan, same=[], changed=["shared.py"])
            write(root, "tools/plan.json", json.dumps(drift))
            status, detail = doctor.c_engine_drift()
            ok("doctor reports true export drift", status == doctor.WARN and "shared.py" in detail,
               repr((status, detail)))

            failures = (
                ("missing source", dict(plan, missing=["tools/shared.py"])),
                ("privacy finding", dict(plan, leaks=["PRIVATE-SENTINEL"])),
                ("missing result field", {"same": ["shared.py"]}),
                ("wrong field type", dict(plan, same="shared.py")),
                ("incomplete scope", dict(plan, same=[])),
                ("unexpected scope", dict(plan, same=["unowned.py"])),
                ("duplicated result", dict(plan, same=["shared.py", "shared.py"])),
            )
            for label, broken in failures:
                write(root, "tools/plan.json", json.dumps(broken))
                status, detail = doctor.c_engine_drift()
                ok("doctor fails closed on export " + label,
                   status == doctor.FAIL and "PRIVATE-SENTINEL" not in detail,
                   repr((status, detail)))
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
            ok("doctor skips an installed tree without an exporter",
               doctor.c_engine_drift()[0] == doctor.SKIP)
            write(root, "tools/kit_sync.py", "raise AssertionError('must not load')\n")
            with patch.dict(os.environ, {"MOTTORI_KIT": root}):
                ok("doctor skips the kit's own tree before importing the exporter",
                   doctor.c_engine_drift()[0] == doctor.SKIP)


def test_doctor_work_context_rejects_tracked_private_symlink():
    root = make_repo(with_config=True)
    try:
        config_path = os.path.join(root, "system", "memory-config.json")
        config = json.load(open(config_path, encoding="utf-8"))
        config["instance"]["context"] = "work"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        write(root, "_private/secret.md", "secret\n")
        os.symlink("_private/secret.md", os.path.join(root, "leak.md"))
        subprocess.run(["git", "add", "leak.md"], cwd=root, check=True)
        code = ("import sys; sys.path.insert(0, 'tools'); import doctor; "
                "status, detail = doctor.c_symlinks(); print(status); print(detail)")
        result = run(root, "-c", code)
        ok("doctor work context rejects every tracked symlink",
           result.returncode == 0 and result.stdout.splitlines()[0] == "FAIL"
           and "leak.md" in result.stdout, result.stdout + result.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ K  gate fail-closed
def test_gate_check_blocks_when_measure_raises():
    root = make_repo(with_config=True)
    try:
        code = r'''
import sys, os, io, json; sys.path.insert(0, "tools")
import gate
gate._mark(gate.DIRTY())
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
    print("json", d.get("decision") == "block" and isinstance(d.get("reason"), str) and bool(d.get("reason")))
except Exception as e:
    print("json", False, repr(out[:120]))
# resume 경로: 예외여도 pending 유지 + UserPromptSubmit 경고 JSON
gate._mark(gate.DIRTY())
buf = io.StringIO(); sys.stdout = buf
rc2 = gate.cmd_resume()
sys.stdout = real
out2 = buf.getvalue()
try:
    d2 = json.loads(out2)
    h = d2.get("hookSpecificOutput", {})
    print("resume", rc2 == 0 and h.get("hookEventName") == "UserPromptSubmit"
          and ("게이트" in h.get("additionalContext", "") or "gate" in h.get("additionalContext", "").lower())
          and os.path.exists(gate.PENDING()))
except Exception as e:
    print("resume", False, repr(out2[:120]))
'''
        r = run(root, "-c", code)
        lines = dict(l.split(" ", 1) for l in r.stdout.strip().splitlines() if " " in l)
        ok("K gate exception → pending marker kept", lines.get("pending") == "True", r.stdout + r.stderr[-300:])
        ok("K gate exception → Stop block JSON with decision=block and reason",
           lines.get("json", "").startswith("True"), r.stdout + r.stderr[-300:])
        ok("K resume exception → UserPromptSubmit warning JSON, pending kept",
           lines.get("resume", "").startswith("True"), r.stdout + r.stderr[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_gate_verdict_checker_key_growth_and_shrink():
    """Removing a checker blocks validation; adding one starts with an empty baseline."""
    import gate
    reason, pull = gate._verdict({"linkcheck": set(), "new-checker": set()}, {"linkcheck": set()}, "ok")
    ok("gate key-set growth with zero issues passes and records the new key",
       reason is None and pull is True, repr((reason, pull)))
    reason, pull = gate._verdict({"linkcheck": set(), "new-checker": {"x|1"}}, {"linkcheck": set()}, "ok")
    ok("gate key-set growth cannot hide issues: the new checker's issues are new issues",
       reason is not None and pull is False and "x|1" in reason, repr((reason, pull)))
    reason, pull = gate._verdict({"linkcheck": set()}, {"linkcheck": set(), "gone": set()}, "ok")
    ok("gate key-set shrink (a removed checker) is still blocked",
       reason is not None and pull is False and "gone" in reason, repr((reason, pull)))


# ------------------------------------------------------------ M  NOW personal pointer
def test_now_renders_unspecified_personal_pointer():
    root = make_repo(with_config=True)
    try:
        r = run(root, "tools/now.py", "log", "[system/state] fixture")
        r = run(root, "tools/now.py", "render")
        now = open(os.path.join(root, "state", "NOW.md"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(root, "state", "NOW.md")) else ""
        ok("M fresh NOW says 정본 미지정, never `None`",
           "정본 미지정" in now and "`None`" not in now, (now[:300] or r.stderr[-300:]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_fresh_install_rejects_malformed_summaries,
               test_linkcheck_exit_codes_and_pending,
               test_linkcheck_optional_destinations_are_exact_and_instance_owned,
               test_linkcheck_measures_non_ascii_spaced_filenames,
               test_scope_hash_matches_with_spaced_filename,
               test_linkcheck_extracted_tree_uses_only_ignored_root_fallback,
               test_linkcheck_exclude_config_applies_only_without_all,
               test_doctor_codex_armed_and_git_version,
               test_doctor_remote_allowlist_is_host_and_path_bounded,
               test_doctor_precommit_accepts_localized_status_tokens,
               test_doctor_kit_shape_markers_fail_closed_individually,
               test_doctor_keeps_release_regressions_out_of_interactive_run,
               test_doctor_engine_drift_uses_export_policy,
               test_doctor_work_context_rejects_tracked_private_symlink,
               test_gate_check_blocks_when_measure_raises,
               test_gate_verdict_checker_key_growth_and_shrink,
               test_now_renders_unspecified_personal_pointer):
        try:
            run_test(fn, __file__)
        except Exception as e:  # noqa: BLE001
            FAILED.append(fn.__name__)
            print(f"✗ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"install checks: {len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(0 if not FAILED else 1)
