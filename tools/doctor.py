#!/usr/bin/env python3
"""Check installation, configuration, hooks, and recorded verification.

Report unmeasured capabilities separately from automated checks. Hook declarations and successful commands do not prove delivery to a model.

Usage: python3 tools/doctor.py [--verbose] [--json] [--release]
Exit 1 when any check fails."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from i18n import language, t
ROOT = os.path.dirname(HERE)
VERBOSE = "--verbose" in sys.argv
JSON_OUTPUT = "--json" in sys.argv
READY_MODE = "--ready" in sys.argv
RELEASE_MODE = "--release" in sys.argv

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
results = []


def check(name, fn):
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = FAIL, t("doctor.check_crashed", error_type=type(e).__name__, error=e)
    results.append((status, name, detail))


def sh(*cmd, cwd=ROOT):
    # Internal checks must not create explicit-run evidence.
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)


def _config_warning(message):
    if language() == "ko":
        return message
    match = re.match(r"config 없음: (.*)", message)
    if match:
        return t("doctor.config_warn_missing", path=match.group(1))
    match = re.match(r"config 로드/검증 실패: (.*)", message)
    if match:
        return t("doctor.config_warn_load", error_type=match.group(1))
    match = re.match(r"journal_visibility .*\(config schema=(.*), engine schema=(.*)\)", message)
    if match:
        return t("doctor.config_warn_visibility", config=match.group(1), engine=match.group(2))
    if message == "tracks 미정의 — NOW 온도판이 빈다":
        return t("doctor.config_warn_tracks")
    match = re.match(r"private thread registry\[(\d+)\] (.*) — skip", message)
    if match:
        problems = {
            "object 아님": "doctor.config_warn_problem_object",
            "key/name invalid": "doctor.config_warn_problem_key",
            "dossier invalid": "doctor.config_warn_problem_dossier",
            "public key collision": "doctor.config_warn_problem_collision",
            "duplicate key": "doctor.config_warn_problem_duplicate",
        }
        problem = t(problems.get(match.group(2), "doctor.config_warn_unknown"))
        return t("doctor.config_warn_private", index=match.group(1), problem=problem)
    if message.startswith("private thread registry 파싱 실패:"):
        return t("doctor.config_warn_private_parse")
    return t("doctor.config_warn_unknown")


def _hook_summary(report, runtime=None):
    role_keys = {
        "injector": "doctor.hook_role_injector",
        "side_effect": "doctor.hook_role_side_effect",
        "guard": "doctor.hook_role_guard",
        "observer": "doctor.hook_role_observer",
        "enforcer": "doctor.hook_role_enforcer",
        "recovery": "doctor.hook_role_recovery",
    }
    parts = []
    for role in role_keys:
        row = report[role]
        declared = "yes" if row["declared"] else "no"
        command = "valid" if row.get("command_valid") else "invalid"
        armed = row.get("armed", "unknown")
        extra = "/matcher-unreachable" if row.get("declared") and row.get("matcher_reachable") is False else ""
        parts.append(f"{t(role_keys[role])}={declared}/{command}/{armed}{extra}")
    evidence = _canary_evidence(runtime) if runtime else "fired/effect=unknown"
    return " · ".join(parts) + " · " + evidence




def c_python():
    v = sys.version_info
    ok = v >= (3, 8)
    return (PASS if ok else FAIL), f"python {v.major}.{v.minor}.{v.micro}" + ("" if ok else t("doctor.python_old"))


def c_node():
    p = shutil.which("node")
    return (PASS, os.path.realpath(p)) if p else (WARN, t("doctor.node_missing"))


def c_codex():
    p = shutil.which("codex")
    return (PASS, p) if p else (WARN, t("doctor.codex_missing"))


def c_claude():
    p = shutil.which("claude")
    return (PASS, p) if p else (WARN, t("doctor.claude_missing"))


def c_git():
    r = sh("git", "rev-parse", "--show-toplevel")
    if r.returncode:
        return WARN, t("doctor.not_git")
    v = sh("git", "--version").stdout.strip()
    m = re.search(r"(\d+)\.(\d+)", v)
    if not m:
        return WARN, t("doctor.git_unreadable", root=r.stdout.strip(), version=v)
    if (int(m.group(1)), int(m.group(2))) < (2, 5):
        return FAIL, t("doctor.git_old", root=r.stdout.strip(), version=v)
    return PASS, r.stdout.strip() + f" · {v}"




def c_memlib():
    import memlib as M
    # Resolve symlinks before comparing roots; /var and /private/var may name the same directory.
    if os.path.realpath(M.ROOT) != os.path.realpath(ROOT):
        return FAIL, t("doctor.root_mismatch", memlib=M.ROOT, actual=ROOT)
    return PASS, f"ROOT={M.ROOT}"


def c_config():
    import memlib as M
    if not os.path.exists(M.CONFIG_PATH):
        return FAIL, t("doctor.config_missing", path=M.CONFIG_PATH)
    raw = open(M.CONFIG_PATH, encoding="utf-8").read()
    if "CHANGEME" in raw:
        return FAIL, t("doctor.config_changeme")
    if READY_MODE:
        import enforce
        problems = enforce.ready_problems(Path(ROOT))
        if problems:
            return FAIL, " · ".join(problems)
    if M.CONFIG_WARNINGS:
        return WARN, " · ".join(_config_warning(w) for w in M.CONFIG_WARNINGS)
    return PASS, t("doctor.config_counts", tracks=len(M.TRACKS), threads=len(M.THREADS),
                   sources=len(M.EPISODIC_SOURCES))


def c_transcripts():
    """Check the derived transcript directory. Absence is normal before a first session but may indicate invalid discovery in an established instance."""
    import memlib as M
    if not os.path.isdir(M.TRANSCRIPTS):
        fresh = len(M.parse_journal()) < 5
        if fresh:
            return WARN, t("doctor.transcripts_fresh", path=M.TRANSCRIPTS)
        return FAIL, t("doctor.transcripts_stale", path=M.TRANSCRIPTS)
    n = len([f for f in os.listdir(M.TRANSCRIPTS) if f.endswith(".jsonl")])
    return (PASS if n else WARN), t("doctor.transcript_sessions", path=M.TRANSCRIPTS, count=n)


def c_state():
    import memlib as M
    if not os.path.isdir(M.STATE):
        return FAIL, t("doctor.missing", path=M.STATE)
    if not os.access(M.STATE, os.W_OK):
        return FAIL, t("doctor.not_writable", path=M.STATE)
    j = M.journal_path()
    errors = []
    entries = M.parse_journal(errors=errors)
    if errors:
        return FAIL, t("doctor.journal_damaged", count=len(errors), first=errors[0])
    state = t("doctor.journal_present") if os.path.exists(j) else t("doctor.journal_absent")
    return PASS, t("doctor.journal_state", state=state, count=len(entries))


def c_now():
    import memlib as M
    if not os.path.exists(M.NOW_PATH):
        return WARN, t("doctor.now_missing")
    size = os.path.getsize(M.NOW_PATH)
    return ((PASS, t("doctor.now_size", size=size, limit=M.NOW_MAX_BYTES)) if size <= M.NOW_MAX_BYTES else
            (FAIL, t("doctor.now_oversize", size=size, limit=M.NOW_MAX_BYTES)))




HOOK_FILES = {"claude": (".claude", "settings.json"), "codex": (".codex", "hooks.json")}


def _hook_cmds(runtime="claude"):
    p = os.path.join(ROOT, *HOOK_FILES[runtime])
    if not os.path.exists(p):
        return None
    cfg = json.load(open(p, encoding="utf-8"))
    out = {}
    for event, blocks in cfg.get("hooks", {}).items():
        for b in blocks:
            for h in b.get("hooks", []):
                out.setdefault(event, []).append(h.get("command", ""))
    return out


def _wiring(runtime):
    """Inspect JSON declarations only; do not infer trust, firing, or model effect."""
    cmds = _hook_cmds(runtime)
    if cmds is None:
        return WARN, t("doctor.hook_file_missing", path="/".join(HOOK_FILES[runtime]))
    import hookdiag
    p = os.path.join(ROOT, *HOOK_FILES[runtime])
    report = hookdiag.static_report(runtime, json.load(open(p, encoding="utf-8")))
    essential = [role for role in ("injector", "side_effect") if not report[role]["declared"]]
    if essential:
        return FAIL, t("doctor.capability_missing", items=", ".join(essential))
    invalid = [role for role, row in report.items()
               if row["declared"] and not row["command_valid"]]
    if invalid:
        return FAIL, t("doctor.command_invalid", items=", ".join(invalid))
    hard = [f"{e}: {c}" for e, cs in cmds.items() for c in cs
            if re.search(r"/(Users|home)/[^/]+/", c)]
    if hard:
        return FAIL, t("doctor.absolute_path", items="\n      ".join(hard))
    startup = "\n".join(cmds.get("SessionStart", []))
    authority_markers = ("state/NOW.md", "_private/state/NOW.md", "unavailable")
    missing_authority = [x for x in authority_markers if x not in startup]
    if missing_authority:
        return FAIL, t("doctor.authority_missing", items=", ".join(missing_authority))
    detail = _hook_summary(report, runtime) + " · command path=relative"
    if runtime == "codex":
        gaps = [r for r in ("observer", "enforcer") if not report[r]["declared"]]
        guard_matchers = report["guard"].get("matchers", [])
        dead_guard = bool(guard_matchers) and not any(
            hookdiag.matcher_reachable(m) for m in guard_matchers)
        if dead_guard:
            detail += t("doctor.pretool_dead")
        if gaps:
            detail += t("doctor.codex_lifecycle_missing")
        return (WARN if gaps or dead_guard else PASS), detail
    missing_gate = [r for r in ("observer", "enforcer", "recovery") if not report[r]["declared"]]
    return ((WARN, detail + t("doctor.claude_lifecycle_missing", items=", ".join(missing_gate)))
            if missing_gate else (PASS, detail))


def c_hook_wiring():
    return _wiring("claude")


def c_hook_wiring_codex():
    return _wiring("codex")


def c_hook_codex_armed():
    """Read enabled, trustStatus, and currentHash through the official hooks/list API."""
    try:
        import hookdiag
        entry = hookdiag.codex_hooks_list(ROOT)
        report = hookdiag.codex_runtime_report(entry.get("hooks", []))
    except FileNotFoundError as e:
        return SKIP, str(e)
    except Exception as e:
        return WARN, t("doctor.hooks_list_failed", error_type=type(e).__name__, error=e)
    required = [r for r in ("injector", "side_effect") if not report[r]["armed"]]
    detail = _hook_summary(report, "codex")
    invalid = [role for role, row in report.items()
               if row["declared"] and not row["command_valid"]]
    if invalid:
        return FAIL, detail + " · command invalid: " + ", ".join(invalid)
    if entry.get("errors"):
        return FAIL, detail + f" · loader errors={entry['errors']}"
    if required:
        # Untrusted but valid wiring needs a manual first runtime launch; report a warning with that action.
        return WARN, (detail + " · unarmed: " + ", ".join(required)
                      + t("doctor.codex_unarmed"))
    if report["guard"]["declared"] and not report["guard"]["matcher_reachable"]:
        return WARN, detail + t("doctor.guard_unreachable")
    return PASS, detail


def c_hook_codex_run():
    """Execute the declared Codex hook command directly. This checks root resolution, including from subdirectories, but not dispatcher firing, trust, or model effect."""
    cmds = _hook_cmds("codex") or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return SKIP, t("doctor.codex_hook_missing")
    sub = os.path.join(ROOT, "system") if os.path.isdir(os.path.join(ROOT, "system")) else ROOT
    outs = {}
    labels = (t("doctor.root_label"), t("doctor.subdir_label"), t("doctor.outside_label"))
    for label, cwd in ((labels[0], ROOT), (labels[1], sub),
                       (labels[2], tempfile.gettempdir())):
        r = subprocess.run(["bash", "-c", cs[0]], capture_output=True, text=True, cwd=cwd)
        try:
            ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        except Exception:
            return FAIL, t("doctor.invalid_json_at", label=label, stdout=r.stdout[:80])
        if r.returncode != 0:
            return FAIL, t("doctor.nonzero_at", label=label, code=r.returncode)
        outs[label] = t("doctor.failure_branch") if ctx.startswith("[kit]") else t("doctor.chars", count=len(ctx))
    if outs[labels[0]] == t("doctor.failure_branch") or outs[labels[1]] == t("doctor.failure_branch"):
        return FAIL, t("doctor.injection_failed", details=outs)
    if outs[labels[2]] != t("doctor.failure_branch"):
        return WARN, t("doctor.outside_injected")
    return (PASS, t("doctor.codex_command_ok").replace("fired/effect=unknown", "")
            + _canary_evidence("codex"))


def c_hook_success():
    """Execute the declared SessionStart command and validate its success-path JSON."""
    cmds = _hook_cmds() or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return FAIL, t("doctor.session_hook_missing")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)
    r = subprocess.run(["bash", "-c", cs[0]], capture_output=True, text=True, env=env, cwd=ROOT)
    try:
        d = json.loads(r.stdout)
        ctx = d["hookSpecificOutput"]["additionalContext"]
    except Exception as e:
        return FAIL, t("doctor.invalid_json", error=e, stdout=r.stdout[:120])
    if ctx.startswith("[kit]"):
        import memlib as M
        if not os.path.exists(M.CONFIG_PATH):
            # Missing config or NOW before setup is uninitialized state, not a broken installed hook.
            return WARN, t("doctor.pre_setup_failure")
        tail = (r.stderr.strip().splitlines() or [""])[-1][:160]
        stderr = f" · stderr: {tail}" if tail else ""
        return FAIL, t("doctor.now_failed", stderr=stderr)
    return (PASS, f"command-valid only · {len(ctx.encode('utf-8'))} UTF-8 bytes · "
            + _canary_evidence("claude"))


def c_hook_failure():
    """Require valid JSON on the hook failure path as well."""
    cmds = _hook_cmds() or {}
    cs = cmds.get("SessionStart") or []
    if not cs:
        return SKIP, ""
    env = dict(os.environ, CLAUDE_PROJECT_DIR="/nonexistent-instance-xyz")
    r = subprocess.run(["bash", "-c", cs[0]], capture_output=True, text=True, env=env, cwd="/")
    if r.returncode != 0:
        return FAIL, t("doctor.failure_nonzero", code=r.returncode)
    try:
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except Exception as e:
        return FAIL, t("doctor.failure_invalid_json", error=e)
    missing = [x for x in ("state/NOW.md", "_private/state/NOW.md", "unavailable") if x not in ctx]
    if missing:
        return FAIL, t("doctor.failure_authority_missing", items=", ".join(missing))
    return (PASS if "[kit]" in ctx else WARN), t("doctor.failure_warns_model")


def _canary_evidence(runtime):
    """Return the last persisted model-backed canary result without running a model."""
    path = os.path.join(ROOT, "state", "hook-canary.json")
    try:
        payload = json.load(open(path, encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("schema_version")
        row = payload.get("runtimes", {}).get(runtime)
        if not isinstance(row, dict):
            return "fired/effect=unknown"
        checked_at = row["checked_at"]
        status = row["status"]
        fired = row["dispatcher_fired"]
        effect = row["effect"]
        if status not in (PASS, FAIL) or fired not in ("verified", "not_verified") \
                or effect not in ("verified", "not_verified"):
            raise ValueError("result fields")
        return f"fired={fired} · effect={effect} · last canary={checked_at} ({status})"
    except FileNotFoundError:
        return "fired/effect=unknown"
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return f"fired/effect=unknown (canary 결과 판독 실패: {type(error).__name__})"


def _precompact_fixture_config():
    return {
        "schema_version": 4,
        "instance": {"name": "doctor-fixture", "context": "personal", "remote_allowlist": []},
        "tracks": [],
        "threads": [],
        "personal_pointer": None,
        "journal_visibility": {
            "public_tracks": ["system"],
            "legacy_cutoff": None,
            "legacy_public_tracks": [],
        },
        "journal_types": ["decision", "state", "artifact", "correction", "lesson", "switch", "idea"],
        "thresholds": {
            "now_tail_events": 12,
            "now_recent_decisions": 8,
            "track_stale_days": 7,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_max_bytes": 6000,
            "now_hook_max_bytes": 6000,
        },
    }


def _simulate_precompact(runtime):
    """Run the declared PreCompact command in a disposable instance and inspect its journal."""
    cmds = _hook_cmds(runtime) or {}
    commands = cmds.get("PreCompact") or []
    if not commands:
        return FAIL, t("doctor.precompact_missing", runtime=runtime)
    if len(commands) != 1:
        return FAIL, t("doctor.precompact_multiple", runtime=runtime, count=len(commands))

    source_tools = os.path.join(ROOT, "tools")
    required = [os.path.join(source_tools, name) for name in ("now.py", "memlib.py")]
    missing = [path for path in required if not os.path.isfile(path)]
    if missing:
        return FAIL, t("doctor.precompact_tools_missing", items=", ".join(missing))

    with tempfile.TemporaryDirectory(prefix=f"doctor-{runtime}-precompact-") as fixture:
        os.makedirs(os.path.join(fixture, "tools"))
        os.makedirs(os.path.join(fixture, "system"))
        os.makedirs(os.path.join(fixture, "state"))
        for source in required:
            shutil.copy2(source, os.path.join(fixture, "tools", os.path.basename(source)))
        with open(os.path.join(fixture, "system", "memory-config.json"),
                  "w", encoding="utf-8") as config_file:
            json.dump(_precompact_fixture_config(), config_file, ensure_ascii=False)

        if runtime == "codex":
            init = subprocess.run(["git", "init", "-q", fixture], capture_output=True, text=True)
            if init.returncode:
                return FAIL, t("doctor.precompact_git_failed",
                               detail=(init.stderr or init.stdout).strip()[:120])

        env = dict(os.environ, CLAUDE_PROJECT_DIR=fixture, MOTTORI_INTERNAL_RUN="1")
        env.pop("MOTTORI_INSTANCE", None)
        payload = json.dumps({"hook_event_name": "PreCompact", "cwd": fixture})
        run = subprocess.run(["bash", "-c", commands[0]], cwd=fixture, env=env, input=payload,
                             capture_output=True, text=True)
        journals = []
        state_dir = os.path.join(fixture, "state")
        for name in os.listdir(state_dir):
            if re.match(r"journal-\d{4}-\d{2}\.md$", name):
                journals.append(os.path.join(state_dir, name))
        marker = "[system/state] 컴팩션 발생"
        effect = any(marker in open(path, encoding="utf-8").read() for path in journals)
        if run.returncode != 0:
            tail = (run.stderr or run.stdout).strip().splitlines()
            detail = f" · {tail[-1][:120]}" if tail else ""
            return FAIL, t("doctor.precompact_exit", code=run.returncode, detail=detail)
        if not effect:
            error_log = os.path.join(state_dir, ".hook-errors.log")
            fallback_lines = (open(error_log, encoding="utf-8").read().strip().splitlines()
                              if os.path.isfile(error_log) else [])
            fallback = fallback_lines[-1] if fallback_lines else "없음"
            return FAIL, t("doctor.precompact_no_effect", fallback=fallback[:120])
        return PASS, t("doctor.precompact_effect", marker=t("doctor.precompact_marker"))


def c_precompact_claude():
    return _simulate_precompact("claude")


def c_precompact_codex():
    return _simulate_precompact("codex")


def c_global_hook():
    """Check the global UserPromptSubmit timestamp hook, which is not cloned with the repo."""
    p = os.path.expanduser("~/.claude/settings.json")
    if not os.path.exists(p):
        return WARN, t("doctor.global_missing")
    try:
        cfg = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return WARN, t("doctor.global_parse_failed", error=e)
    ups = cfg.get("hooks", {}).get("UserPromptSubmit", [])
    has = any("date" in h.get("command", "") for b in ups for h in b.get("hooks", []))
    return (PASS, t("doctor.time_hook_present")) if has else \
           (WARN, t("doctor.time_hook_missing"))


def c_precommit_install():
    """Compare active installed hooks with tracked templates without repairing them."""
    script = os.path.join(ROOT, "tools", "install_hooks.sh")
    if not os.path.exists(script):
        return WARN, t("doctor.installer_missing")
    r = sh("bash", script, "--check")
    detail = (r.stdout + r.stderr).strip().splitlines()
    first = detail[0] if detail else f"exit={r.returncode}"
    if r.returncode == 0 and first.startswith(("current:", "현재(current):")):
        return PASS, first
    if first.startswith(("missing:", "없음(missing):")):
        return WARN, t("doctor.repair_needed", detail=first)
    return FAIL, first


def c_commands():
    d = os.path.join(ROOT, ".claude", "commands")
    if not os.path.isdir(d):
        return WARN, t("doctor.commands_missing")
    got = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
    return PASS, "/" + " /".join(got)




def c_tools_run():
    """Run checker entrypoints through their machine protocol. Use check, not render, to avoid overwriting generated state. A successful measurement is distinct from an issue-free result."""
    bad = []
    for args in (["tools/now.py", "check", "--issues"], ["tools/linkcheck.py"], ["tools/coherence.py", "--quiet"]):
        r = sh(sys.executable, *args)
        if r.returncode not in (0, 1):   # These tools use exit 1 for reported findings.
            bad.append(f"{args[0]} exit={r.returncode} {r.stderr.strip()[:80]}")
        elif "--issues" in args:
            # Require the final #issues trailer: exit 1 alone cannot distinguish findings from a crash.
            last = (r.stdout.strip().splitlines() or [""])[-1]
            if not re.match(r"^#issues \d+$", last):
                bad.append(t("doctor.trailer_missing", tool=args[0], last=last[:40]))
    return (FAIL, " · ".join(bad)) if bad else (PASS, t("doctor.tools_ok"))


def c_links():
    """Inspect linkcheck findings, not only whether its process ran."""
    r = sh(sys.executable, "tools/linkcheck.py")
    if r.returncode not in (0, 1) or "Traceback" in r.stderr:
        first = (r.stderr.strip().splitlines() or ["?"])[-1]
        return FAIL, t("doctor.checker_crashed", code=r.returncode, detail=first[:100])
    m = re.search(r"broken: (\d+)", r.stdout)
    if not m:
        return FAIL, t("doctor.linkcheck_unreadable", output=(r.stdout + r.stderr)[:120])
    n = int(m.group(1))
    if not n:
        refs = re.search(r"refs=(\d+)", r.stdout)
        return PASS, t("doctor.links_ok", refs=refs.group(1) if refs else "?")
    detail = [l for l in r.stdout.splitlines() if l.startswith("BROKEN")][:5]
    more = t("doctor.more", count=n - len(detail)) if n > len(detail) else ""
    return FAIL, t("doctor.links_broken", count=n, details="\n      ".join(detail), more=more)


def c_coherence():
    """Inspect coherence findings and distinguish checker failure from reported issues."""
    r = sh(sys.executable, "tools/coherence.py", "--quiet")
    # A checker crash is a failure, not a warning or a zero-issue result.
    if r.returncode not in (0, 1) or "Traceback" in r.stderr or "Error" in r.stderr:
        first = (r.stderr.strip().splitlines() or ["?"])[-1]
        return FAIL, t("doctor.checker_crashed", code=r.returncode, detail=first[:100])
    m = re.search(r"(?:총|이슈) (\d+)건", r.stdout)
    if m is None and ("이상 없음" in r.stdout or "링크 OK" in r.stdout):
        return PASS, t("doctor.coherence_ok", count=0)
    if m is None:
        return FAIL, t("doctor.output_unreadable", output=(r.stdout+r.stderr).strip()[:90])
    n = int(m.group(1))
    return (PASS if not n else WARN), t("doctor.coherence_ok", count=n)


def _is_kit_tree(root=ROOT):
    """Recognize a distribution checkout without requiring every marker to survive."""
    markers = (
        "setup.sh",
        "templates/memory-config.json",
        "system/engine-inventory.txt",
        "system/review-manifest.yaml",
    )
    return any(os.path.isfile(os.path.join(root, marker)) for marker in markers)


def c_regression():
    """Run the regression suites available in this distribution or installed instance."""
    if not RELEASE_MODE:
        return SKIP, t("doctor.regression_release_only")
    # Do not call suites that invoke doctor here; doing so would recurse.
    scripts = ["test_memcheck.py", "test_memlib_journal.py", "test_state_runtime.py",
               "test_hook_runtime.py", "test_fresh_worker.py", "test_worker_batch.py",
               "test_install_checks.py",
               "test_recall.py", "test_rec.py",
               "test_hookdiag.py", "test_install_hooks.py", "test_coherence.py",
               "test_evidencecheck.py", "test_egress.py"]
    kit_sync = os.path.join(ROOT, "tools", "kit_sync.py")
    kit_tree = _is_kit_tree()
    # Require both distribution markers so deleting one cannot silently reduce the test set.
    if os.path.isfile(kit_sync):
        upstream_suites = ("test_recording_language.py", "test_slack_pipeline.py",
                           "test_instance_tools.py")
        missing = [
            os.path.join("tools", script)
            for script in upstream_suites
            if not os.path.isfile(os.path.join(ROOT, "tools", script))
        ]
        if missing:
            return FAIL, t("doctor.upstream_suites_missing", items=", ".join(missing))
        scripts.extend(upstream_suites)
    elif kit_tree:
        # Distribution-only suites require kit-specific files; missing suites fail closed.
        kit_suites = ("test_setup_migration.py", "test_portability.py", "test_manifests.py",
                      "test_skill_parity.py", "test_matrix_check.py", "test_language.py",
                      "test_devtree_gate.py")
        required = ("setup.sh", "templates/memory-config.json", "system/engine-inventory.txt") \
            + tuple(os.path.join("tools", s) for s in kit_suites) \
            + ("tools/test_instance_shape.py",)
        missing = [path for path in required if not os.path.isfile(os.path.join(ROOT, path))]
        if missing:
            return FAIL, t("doctor.kit_suites_missing", items=", ".join(missing))
        scripts.extend(kit_suites)
    # An installed instance has neither the origin-only exporter nor the kit-only installer.
    # Its tools directory is the engine inventory, so only the shared suites above apply.
    passed, bad = [], []
    for script in scripts:
        r = sh(sys.executable, "tools/" + script)
        if r.returncode == 0:
            passed.append(script)
        else:
            tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
            bad.append(script + ": " + " | ".join(tail))
    return ((FAIL, t("doctor.regression_failed", details="\n      ".join(bad))) if bad else
            (PASS, t("doctor.regression_ok", count=len(passed), items=", ".join(passed))))


def c_worker_receipts():
    """Recompute recent worker costs and failure rates from recorded receipts."""
    import receipts as R
    records, errors = R.load_runs(os.path.join(ROOT, "_private", "work", "runs"))
    recent = R.recent_runs(records, days=7)
    totals = R._totals(recent)
    runs = totals["runs"]
    failures = totals["failures"]
    rate = failures / runs * 100 if runs else 0.0
    usage = R._usage_text(totals["usage"])
    detail = t("doctor.receipts_detail", runs=runs, usage=usage,
               failures=failures, rate=f"{rate:.1f}")
    if errors:
        return WARN, detail + t("doctor.receipts_unreadable", count=len(errors))
    return (WARN if rate > 50 else PASS), detail


def c_recall():
    r = sh(sys.executable, "tools/recall.py", "sessions")
    if r.returncode:
        return FAIL, r.stderr.strip()[:150]
    n = len(re.findall(r"\.jsonl", r.stdout)) or len(r.stdout.strip().splitlines())
    return (PASS if n else WARN), t("doctor.recall_ok", count=n)


def c_ledger():
    import memlib as M
    d = os.path.join(M.ROOT, "_private", "ledger", "facts")
    if not os.path.isdir(d):
        return SKIP, t("doctor.ledger_missing")
    n = len([f for f in os.listdir(d) if f.endswith(".md")])
    r = sh(sys.executable, "tools/rec.py", "check")
    if r.returncode != 0 or "Traceback" in r.stderr:
        detail = (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1]
        return FAIL, f"rec.py check 실패: {detail[:120]}"
    m = re.search(r"문제: (\d+)건", r.stdout)
    if not m:
        return FAIL, "rec.py check 결과에 `문제: N건` trailer가 없다"
    bad = int(m.group(1))
    return (PASS if not bad else WARN), t("doctor.ledger_counts", facts=n, issues=bad)


def c_portrait():
    """Check whether unprocessed person-ledger candidates have accumulated since its last update."""
    import portrait as P
    if not os.path.exists(P.PORTRAIT):
        return SKIP, t("doctor.portrait_missing")
    since = P._last_update()
    if not since:
        return WARN, t("doctor.portrait_undated")
    n = len([e for e in P._entries() if e[0] > since and e[2] in P.HARVEST_TYPES])
    msg = t("doctor.portrait_counts", date=since, count=n, threshold=P.STALE_THRESHOLD)
    if n >= P.STALE_THRESHOLD:
        return WARN, msg + " — python3 tools/portrait.py candidates"
    return PASS, msg




def c_egress():
    """Require at least one denied path prefix in the model-send policy."""
    import memlib as M
    if M.CONFIG_ERROR == "invalid":
        key = ("doctor.egress_invalid" if "allow_prefixes" in (M.CONFIG_ERROR_DETAIL or "")
               else "doctor.egress_config_invalid")
        return FAIL, t(key)
    deny = M.EGRESS_MODEL_SEND.get("deny_prefixes", [])
    allow = M.EGRESS_MODEL_SEND.get("allow_prefixes", [])
    if not deny:
        return FAIL, t("doctor.egress_empty")
    relationship_errors = M.egress_prefix_relationship_errors(deny, allow)
    if relationship_errors:
        return FAIL, t("doctor.egress_overlap", detail="; ".join(relationship_errors))
    return PASS, t("doctor.egress_ok", deny=len(deny), allow=len(allow))

def _remote_host(url):
    """Extract a remote host, including scp-style syntax and local paths."""
    u = url.strip()
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?([^/:]+)", u)
    if m:
        return m.group(1).lower()
    m = re.match(r"^(?:[^@]+@)?([^/:@]+):", u)          # git@github.com:user/repo
    if m:
        return m.group(1).lower()
    return ("local:" + os.path.realpath(os.path.expanduser(u))) if u.startswith(("/", "~", ".")) else ""


def _allowed(url, allowlist):
    """Compare parsed hosts and path boundaries, never URL substrings. A trusted host embedded in an untrusted URL path must not pass."""
    def path_of(u):
        u = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^@/]+@)?[^/]+/?", "", u.strip())
        u = re.sub(r"^(?:[^@]+@)?[^/:@]+:", "", u)
        return re.sub(r"\.git$", "", u).strip("/").lower()

    host = _remote_host(url)
    if not host:
        return False
    for a in allowlist:
        a = (a or "").strip().rstrip("/")
        if not a:                       # An empty allowlist entry must not allow every remote.
            continue
        ah = _remote_host(a) or a.split("/")[0].lower()
        if ah != host:
            continue
        ap = path_of(a)
        if not ap:
            return True                 # A host-only entry allows that entire host.
        up = path_of(url)
        if up == ap or up.startswith(ap + "/"):
            return True
    return False


def c_valve():
    import memlib as M
    r = sh("git", "remote", "-v")
    remotes = sorted({l.split()[1] for l in r.stdout.splitlines() if len(l.split()) > 1})
    if M.INSTANCE_CONTEXT != "work":
        # Report when this policy is not applicable; this check diagnoses rather than blocks egress.
        extra = t("doctor.remote_extra", count=len(remotes)) if remotes else ""
        return SKIP, t("doctor.valve_skip", context=M.INSTANCE_CONTEXT, extra=extra)
    if not remotes:
        return PASS, t("doctor.no_remotes")
    bad = [u for u in remotes if not _allowed(u, M.REMOTE_ALLOWLIST)]
    if bad:
        return FAIL, t("doctor.bad_remotes", items="\n      ".join(bad))
    return PASS, t("doctor.remotes_ok", count=len(remotes))


def c_symlinks():
    """Find tracked symlinks that expose private targets or paths. Git stores the link target; consumers may later dereference it."""
    # Use NUL-separated paths so Git quoting cannot change filenames.
    import memlib as M
    r = subprocess.run(["git", "ls-files", "-s", "-z"], capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        return SKIP, t("doctor.not_git")
    links = [rec.split("\t", 1)[1] for rec in r.stdout.split("\0")
             if rec.startswith("120000") and "\t" in rec]
    if not links:
        return PASS, t("doctor.symlinks_zero")
    if M.INSTANCE_CONTEXT == "work":
        shown = []
        for link in links[:3]:
            blob = subprocess.run(["git", "show", f":{link}"], cwd=ROOT,
                                  capture_output=True, text=True)
            target = blob.stdout.strip() if blob.returncode == 0 else "<index target unreadable>"
            shown.append(f"{link[-52:]}  ->  {target[-52:]}")
        more = t("doctor.more", count=len(links) - len(shown)) if len(links) > len(shown) else ""
        return FAIL, (f"work index의 추적 symlink {len(links)}개\n      "
                      + "\n      ".join(shown) + more)
    priv = os.path.realpath(os.path.join(ROOT, "_private"))
    into_private = []
    for l in links:
        full = os.path.join(ROOT, l)
        try:
            raw = os.readlink(full)
        except OSError:
            raw = ""
        if os.path.realpath(full).startswith(priv) or "_private" in raw:
            into_private.append(f"{l[-52:]}  ->  {raw[-52:]}")
    if into_private:
        more = t("doctor.more", count=len(into_private) - 3) if len(into_private) > 3 else ""
        head = t("doctor.private_symlinks", count=len(into_private),
                 items="\n      ".join(into_private[:3]), more=more)
        # Work instances fail on path exposure; personal instances report it as a warning.
        if M.INSTANCE_CONTEXT == "work":
            return FAIL, head
        return WARN, head + t("doctor.symlink_cleanup")
    return WARN, t("doctor.symlinks_outside", count=len(links))


def _linkcheck_scope():
    """Hash the same file paths and bytes that linkcheck uses for its verification record."""
    import hashlib
    r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others",
                        "--exclude-standard", "*.md"], cwd=ROOT, capture_output=True, check=True)
    d = hashlib.sha1()
    # Exclude generated projections from the verification identity: rendering can change their timestamps.
    # The link checker still reads these files; only certificate identity excludes them.
    _GEN = ("state/NOW.md", "_private/state/NOW.md")
    paths = [os.fsdecode(path) for path in r.stdout.split(b"\0") if path]
    for f in sorted(path for path in paths if path not in _GEN):
        d.update(os.fsencode(f))
        try:
            d.update(open(os.path.join(ROOT, f), "rb").read())
        except OSError:
            d.update(b"<missing>")
    return d.hexdigest()[:12]


def c_missed_gate():
    """Check for a successful linkcheck record bound to the current file bytes. Missing evidence is a failure when new files are present and a warning otherwise."""
    import memlib as M
    if sh("git", "rev-parse", "--is-inside-work-tree").returncode:
        return SKIP, t("doctor.not_git")
    if not os.path.exists(M.TOOL_RUNS):
        return WARN, t("doctor.no_run_log")
    # Bind evidence to the exact bytes read by linkcheck, including unstaged and untracked inputs.
    cur_scope = _linkcheck_scope()
    if M.ran_at_head("linkcheck", cur_scope, require_ok=True):
        return PASS, t("doctor.linkcheck_recorded")
    # Warn on unverified edits; fail when new files lack verification.
    added = [x for x in sh("git", "show", "--diff-filter=A", "--name-only", "--format=",
                           "HEAD").stdout.splitlines() if x.strip()]
    untracked_new = [l[3:] for l in sh("git", "status", "--porcelain").stdout.splitlines()
                     if l.startswith(("A ", "??"))]
    new_files = added + untracked_new
    if not new_files:
        return WARN, t("doctor.unverified_no_new")
    return FAIL, t("doctor.unverified_new", count=len(new_files), items=", ".join(new_files[:4]))


def c_agents_parity():
    """Require CLAUDE.md to import the single AGENTS.md source exactly. A copied policy can diverge after either file is edited."""
    a, b = os.path.join(ROOT, "CLAUDE.md"), os.path.join(ROOT, "AGENTS.md")
    if not os.path.exists(a):
        return FAIL, t("doctor.claude_md_missing")
    if not os.path.exists(b):
        return FAIL, t("doctor.agents_md_missing")
    x, y = open(a, "rb").read(), open(b, "rb").read()
    if x in (b"@AGENTS.md", b"@AGENTS.md\n"):
        return PASS, t("doctor.agents_ok", bytes=len(y))
    return FAIL, t("doctor.agents_mismatch", claude=len(x), agents=len(y))


def c_schema():
    """Report config migrations required by the current engine. Instance-owned config is not replaced by an engine update."""
    import memlib as M
    if M.CONFIG_SCHEMA > M.SCHEMA_VERSION:
        return FAIL, t("doctor.schema_newer", config=M.CONFIG_SCHEMA, engine=M.SCHEMA_VERSION)
    gap = M.schema_gap()
    if gap is None:
        return PASS, t("doctor.schema_ok", config=M.CONFIG_SCHEMA, engine=M.SCHEMA_VERSION)
    cur, want, todo = gap
    return FAIL, t("doctor.schema_old", config=cur, engine=want, todo="\n      ".join(todo))


def c_upstream():
    """Report local engine modifications and upstream revision differences. Instance-specific changes belong in the instance extension files."""
    r = sh("git", "rev-parse", "--is-inside-work-tree")
    if r.returncode:
        return SKIP, t("doctor.not_git")
    # The exporter exists only in the source workspace, where engine edits are expected.
    if os.path.exists(os.path.join(ROOT, "tools", "kit_sync.py")):
        return SKIP, t("doctor.upstream_here")
    # Instance-owned files are untracked; tracked modifications affect the engine.
    mod = [l[3:] for l in sh("git", "status", "--porcelain").stdout.splitlines()
           if l[:2].strip() in ("M", "MM", "AM", "D")]
    up = sh("git", "rev-list", "--count", "HEAD..@{u}")
    behind = up.stdout.strip() if up.returncode == 0 else None
    msgs = []
    if mod:
        msgs.append(t("doctor.engine_modified", items=", ".join(mod[:6])))
    if behind and behind != "0":
        msgs.append(t("doctor.upstream_behind", count=behind))
    if msgs:
        return WARN, "\n      ".join(msgs)
    status = t("doctor.upstream_sync") if behind == "0" else t("doctor.upstream_unset")
    return PASS, t("doctor.upstream_ok", status=status)


def c_engine_drift():
    """Detect differences between the source engine and kit after export normalization. This reports drift; it does not authorize or perform export."""
    kit = os.environ.get("MOTTORI_KIT") or os.path.expanduser("~/mottori-kit")
    if not os.path.isdir(os.path.join(kit, "tools")) or os.path.realpath(kit) == os.path.realpath(ROOT):
        return SKIP, t("doctor.kit_missing")
    try:
        import kit_sync
    except Exception as e:
        return SKIP, t("doctor.kit_sync_missing", error=e)
    # Normalize intentional export differences before reporting drift.
    mine, theirs = os.path.join(ROOT, "tools"), os.path.join(kit, "tools")
    shared = sorted(set(os.listdir(mine)) & set(os.listdir(theirs)))
    diff = []
    for f in shared:
        a, b = os.path.join(mine, f), os.path.join(theirs, f)
        if not os.path.isfile(a):
            continue
        try:
            want = kit_sync.depersonalize(open(a, encoding="utf-8").read())
            have = open(b, encoding="utf-8").read()
            # Normalize sync stamps the same way as kit_sync.
            if f == "fresh_worker.py" and hasattr(kit_sync, "unstamp"):
                want, have = kit_sync.unstamp(want), kit_sync.unstamp(have)
            if want != have:
                diff.append(f)
        except UnicodeDecodeError:
            pass
    if diff:
        return WARN, t("doctor.kit_diverged", shared=len(shared), different=len(diff),
                       items=", ".join(diff))
    return PASS, t("doctor.kit_same", count=len(shared), kit=kit)


def c_ignored():
    """Check whether instance data is exposed to Git, including untracked files whose ignore coverage was removed."""
    r = sh("git", "rev-parse", "--is-inside-work-tree")
    if r.returncode:
        return SKIP, t("doctor.not_git")
    import memlib as M
    probes = ["state/NOW.md", "state/journal-x.md", "_private/x.md",
              "system/memory-config.json", "company/tracker.md", "notes.md"]
    not_ignored = [x for x in probes if sh("git", "check-ignore", "-q", x).returncode != 0]
    tracked = [x for x in probes if sh("git", "ls-files", "--error-unmatch", x).returncode == 0]
    st = sh("git", "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    exposed = [l[3:] for l in st if l.startswith("??")]

    if M.INSTANCE_CONTEXT != "work":
        # A personal instance may intentionally track public documents; check actual data exposure.
        return (PASS, t("doctor.personal_exposure", count=len(exposed))) \
            if len(exposed) < 20 else (WARN, t("doctor.untracked_exposure", count=len(exposed)))

    msgs = []
    try:
        import enforce
        absolute = [row for row in enforce.index_issues(Path(ROOT))
                    if not row[0].startswith("work-local-change:")]
    except Exception as error:
        msgs.append(f"index privacy 측정 실패: {type(error).__name__}")
    else:
        if absolute:
            msgs.append("index privacy 위반: " + ", ".join(issue for issue, _ in absolute[:6]))
    still = [x for x in not_ignored if x not in tracked]
    if still:
        msgs.append(t("doctor.ignore_misses", items=", ".join(still)))
    if exposed:
        msgs.append(t("doctor.exposed_paths", count=len(exposed), items=", ".join(exposed[:4])))
    if tracked:
        msgs.append(t("doctor.already_tracked", items=", ".join(tracked)))
    if msgs:
        return FAIL, "\n      ".join(msgs)
    return PASS, t("doctor.ignore_ok", count=len(probes))



CHECKS = [
    (t("doctor.check.runtime_python"),        c_python),
    (t("doctor.check.runtime_node"),          c_node),
    (t("doctor.check.runtime_codex"),         c_codex),
    (t("doctor.check.runtime_claude"),        c_claude),
    (t("doctor.check.runtime_git"),           c_git),
    (t("doctor.check.wiring_root"),           c_memlib),
    (t("doctor.check.wiring_config"),         c_config),
    (t("doctor.check.wiring_transcripts"),    c_transcripts),
    (t("doctor.check.wiring_state"),          c_state),
    (t("doctor.check.wiring_now"),            c_now),
    (t("doctor.check.hook_claude"),           c_hook_wiring),
    (t("doctor.check.hook_codex"),            c_hook_wiring_codex),
    (t("doctor.check.hook_armed"),            c_hook_codex_armed),
    (t("doctor.check.hook_codex_command"),    c_hook_codex_run),
    (t("doctor.check.hook_claude_command"),   c_hook_success),
    (t("doctor.check.hook_failure"),          c_hook_failure),
    (t("doctor.check.hook_precompact_claude"), c_precompact_claude),
    (t("doctor.check.hook_precompact_codex"), c_precompact_codex),
    (t("doctor.check.hook_time"),             c_global_hook),
    (t("doctor.check.hook_precommit"),        c_precommit_install),
    (t("doctor.check.hook_commands"),         c_commands),
    (t("doctor.check.tools_run"),             c_tools_run),
    (t("doctor.check.tools_links"),           c_links),
    (t("doctor.check.tools_coherence"),       c_coherence),
    (t("doctor.check.tools_regression"),      c_regression),
    (t("doctor.check.tools_receipts"),        c_worker_receipts),
    (t("doctor.check.tools_recall"),          c_recall),
    (t("doctor.check.tools_ledger"),          c_ledger),
    (t("doctor.check.tools_portrait"),        c_portrait),
    (t("doctor.check.valve_egress"),          c_egress),
    (t("doctor.check.valve_remote"),          c_valve),
    (t("doctor.check.valve_ignored"),         c_ignored),
    (t("doctor.check.valve_symlinks"),        c_symlinks),
    (t("doctor.check.gate_missed"),           c_missed_gate),
    (t("doctor.check.agents"),                c_agents_parity),
    (t("doctor.check.schema"),                c_schema),
    (t("doctor.check.upstream"),              c_upstream),
    (t("doctor.check.drift"),                 c_engine_drift),
]

# These capabilities require human verification and are not automated PASS results.
MANUAL = [
    (t("doctor.manual.session_title"), t("doctor.manual.session_how")),
    (t("doctor.manual.precompact_title"), t("doctor.manual.precompact_how")),
    (t("doctor.manual.codex_title"), t("doctor.manual.codex_how")),
    (t("doctor.manual.policy_title"), t("doctor.manual.policy_how")),
]


def main():
    results.clear()
    if not JSON_OUTPUT:
        print(t("doctor.heading", root=ROOT))
    for name, fn in CHECKS:
        check(name, fn)
    n = {s: sum(1 for st, _, _ in results if st == s) for s in (PASS, FAIL, WARN, SKIP)}
    if JSON_OUTPUT:
        payload = {
            "checks": [
                {"name": name, "status": status, "detail": detail}
                for status, name, detail in results
            ],
            "summary": {
                "total": len(results),
                "pass": n[PASS],
                "fail": n[FAIL],
                "warn": n[WARN],
                "skip": n[SKIP],
            },
            "manual": [{"name": title, "detail": how} for title, how in MANUAL],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        width = max(len(name) for _, name, _ in results)
        icon = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn ", SKIP: "  --  "}
        for status, name, detail in results:
            line = f"[{icon[status]}] {name.ljust(width)}"
            if detail and (status != PASS or VERBOSE):
                line += f"  {detail}"
            elif detail and status == PASS:
                line += f"  {detail}"
            print(line)

        print(t("doctor.summary", total=len(results), ok=n[PASS], fail=n[FAIL],
                warn=n[WARN], skip=n[SKIP]))

        print(t("doctor.manual_heading", count=len(MANUAL)))
        for i, (title, how) in enumerate(MANUAL, 1):
            print(f"  {i}. {title}")
            print(f"     {how}")

    __import__("sys").path.insert(0, HERE)
    import memlib as _M; _M.log_run("doctor", f"fail={n[FAIL]} warn={n[WARN]}")
    if n[FAIL] and not JSON_OUTPUT:
        print(t("doctor.finish_fail", count=n[FAIL]))
    return 1 if n[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
