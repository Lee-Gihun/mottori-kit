#!/usr/bin/env python3
"""doctor JSON output and isolated PreCompact simulation fixtures."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]


def _git_env():
    """Drop inherited GIT_* so a run from inside a git hook cannot touch the outer repository."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _run_doctor_json():
    """Run doctor --json on a copy of this tree's tools, which writes its records there."""
    root = tempfile.mkdtemp(prefix="doctor-json-")
    try:
        shutil.copytree(HERE, os.path.join(root, "tools"),
                        ignore=shutil.ignore_patterns("__pycache__", "tests"))
        return subprocess.run(
            [sys.executable, os.path.join(root, "tools", "doctor.py"), "--json"],
            cwd=root, capture_output=True, text=True,
            env=dict(os.environ, MOTTORI_INTERNAL_RUN="1", MOTTORI_INSTANCE=root),
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_json_schema_and_exit_status():
    result = _run_doctor_json()
    payload = json.loads(result.stdout)
    assert set(payload) == {"checks", "summary", "manual"}
    assert payload["checks"]
    assert all(set(row) == {"id", "name", "status", "detail"} for row in payload["checks"])
    # Each row's id names one check, and its name is that check's label.
    import doctor
    assert [row["name"] for row in payload["checks"]] == [doctor.LABELS[row["id"]] for row in payload["checks"]]
    assert len({row["id"] for row in payload["checks"]}) == len(payload["checks"])
    assert all(row["status"] in {"PASS", "FAIL", "WARN", "SKIP"}
               for row in payload["checks"])
    assert set(payload["summary"]) == {"total", "pass", "fail", "warn", "skip"}
    assert payload["summary"]["total"] == len(payload["checks"])
    assert payload["summary"]["fail"] == sum(
        row["status"] == "FAIL" for row in payload["checks"])
    assert result.returncode == (1 if payload["summary"]["fail"] else 0)
    # The manual list leaves out items already checked automatically.
    assert all(set(row) == {"name", "detail"} for row in payload["manual"])
    assert not any("PreCompact" in row["name"] for row in payload["manual"])
    assert any(row["name"] == "hooks · PreCompact fired in a real session"
               for row in payload["checks"])
    assert not result.stderr, result.stderr


def _restore_env(name, value):
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _fixture_root(commands):
    root = tempfile.mkdtemp(prefix="doctor-precompact-")
    os.makedirs(os.path.join(root, "tools", "lib"))
    for name in ("hook.sh", "dispatch.py", "now.py", "lib/config.py", "enforce.py",
                 "lib/hook_input.py", "lib/journal.py", "lib/paths.py", "lib/runlog.py", "lib/safeio.py"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    for runtime, command in commands.items():
        rel = (".claude", "settings.json") if runtime == "claude" else (".codex", "hooks.json")
        os.makedirs(os.path.join(root, rel[0]))
        payload = {"hooks": {"PreCompact": [{"hooks": [{
            "type": "command", "command": command,
        }]}]}}
        with open(os.path.join(root, *rel), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    return root


def _live_precompact_commands():
    commands = {}
    for runtime, rel in {
            "claude": (".claude", "settings.json"),
            "codex": (".codex", "hooks.json"),
    }.items():
        cfg = json.load(open(os.path.join(ROOT, *rel), encoding="utf-8"))
        commands[runtime] = cfg["hooks"]["PreCompact"][0]["hooks"][0]["command"]
    return commands


def _simulate_both(commands):
    import doctor
    root = _fixture_root(commands)
    old_root = doctor.ROOT
    try:
        doctor.ROOT = root
        return doctor, {runtime: doctor._simulate_precompact(runtime) for runtime in ("claude", "codex")}
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_precompact_simulation_passes_for_both_runtimes():
    doctor, results = _simulate_both(_live_precompact_commands())
    for runtime, (status, detail) in results.items():
        assert status == doctor.PASS, f"{runtime}: {detail}"
        assert doctor.PRECOMPACT_MARKER in detail


def test_precompact_simulation_fails_without_journal_effect():
    doctor, results = _simulate_both({"claude": "true", "codex": "true"})
    for runtime, (status, detail) in results.items():
        assert status == doctor.FAIL, f"{runtime}: {detail}"
        assert "journal" in detail


def test_doctor_reads_last_canary_result():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-canary-")
    old_root = doctor.ROOT
    checked_at = datetime.datetime(2026, 9, 17, 5, 30, tzinfo=datetime.timezone.utc).isoformat()
    try:
        os.makedirs(os.path.join(root, "state"))
        with open(os.path.join(root, "state", "hook-canary.json"), "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": 1,
                "runtimes": {
                    "codex": {
                        "checked_at": checked_at,
                        "status": "PASS",
                        "dispatcher_fired": "verified",
                        "effect": "verified",
                    },
                    "claude": {
                        "checked_at": checked_at,
                        "status": "PASS",
                        "dispatcher_fired": "verified",
                        "effect": "verified",
                    },
                },
            }, f)
        doctor.ROOT = root
        detail = doctor._canary("codex")[1]
        assert checked_at in detail
        assert "verified" in detail
        assert "unknown" not in detail
        os.makedirs(os.path.join(root, ".claude"))
        with open(os.path.join(root, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command":
                    "echo state/NOW.md _private/state/NOW.md unavailable"}]}],
                "PreCompact": [{"hooks": [{"type": "command", "command": "true"}]}],
            }}, f)
        _, wiring_detail = doctor._wiring("claude")
        assert checked_at in wiring_detail and "fired/effect=unknown" not in wiring_detail
        assert "not tested" in doctor._canary("missing")[1]
    finally:
        doctor.ROOT = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_context_budget_over_line_is_warn_not_fail():
    import context_budget
    import doctor
    original = context_budget.measure
    report = {"total": {"bytes": 30000, "tokens": 9000}, "warnings": ["memory_index", "total"]}
    try:
        context_budget.measure = lambda: report
        status, detail = doctor.c_context_budget()
        assert status == doctor.WARN, (status, detail)
        assert "memory_index" in detail and "context_budget.py" in detail
        report["warnings"] = []
        status, _detail = doctor.c_context_budget()
        assert status == doctor.PASS
        report["unmeasured"] = 2
        status, detail = doctor.c_context_budget()
        assert status == doctor.PASS and "; partial total, 2 hook(s) not counted" in detail, detail
    finally:
        context_budget.measure = original
    assert any(fn is doctor.c_context_budget for _id, _label, fn, _git in doctor.CHECKS)


def _growth_tree(root):
    """Build a workspace shaped like a used instance: Git history, stale tmp/, work folders."""
    old = time.time() - 30 * 86400
    os.makedirs(os.path.join(root, "tmp", "old-job"))
    with open(os.path.join(root, "tmp", "old-job", "copy.bin"), "wb") as f:
        f.write(b"x" * 4096)
    os.utime(os.path.join(root, "tmp", "old-job", "copy.bin"), (old, old))
    with open(os.path.join(root, "tmp", "fresh.txt"), "w", encoding="utf-8") as f:
        f.write("recent")
    work = os.path.join(root, "_private", "work")
    for name in ("guided", "bare-1", "bare-2"):
        os.makedirs(os.path.join(work, name))
    with open(os.path.join(work, "guided", "STATE.md"), "w", encoding="utf-8") as f:
        f.write("# job\n")
    with open(os.path.join(work, "bare-1", "notes.md"), "w", encoding="utf-8") as f:
        f.write("no guide page\n")
    os.makedirs(os.path.join(work, "bare-2", "sub"))
    with open(os.path.join(work, "bare-2", "sub", "README.md"), "w", encoding="utf-8") as f:
        f.write("guide below the top does not count\n")
    subprocess.run(["git", "init", "-q", root], check=True, env=_git_env())
    with open(os.path.join(root, "engine.py"), "w", encoding="utf-8") as f:
        f.write("print('engine')\n")
    subprocess.run(["git", "-C", root, "add", "engine.py"], check=True, env=_git_env())
    # A commit starts `git maintenance run --auto --detach`, which holds a lock file under .git
    # after the commit returns. Turn it off so nothing but the code under test can touch the tree.
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "maintenance.auto=false", "-c", "gc.auto=0",
                    "commit", "-q", "--no-verify", "-m", "x"], check=True, env=_git_env())


def _plenty_of_disk(_path):
    return types.SimpleNamespace(total=100 * 1024 ** 4, used=0, free=50 * 1024 ** 4)


def _snapshot(root):
    rows = {}
    for base, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(base, name)
            st = os.lstat(path)
            rows[path] = (st.st_size, st.st_mtime_ns)
    return rows


def test_growth_fresh_install_shape_has_no_warning():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-fresh-")
    try:
        subprocess.run(["git", "init", "-q", root], check=True, env=_git_env())
        status, detail, items = doctor._growth_report(root, {}, disk_usage=_plenty_of_disk)
        assert status == doctor.PASS, (status, detail)
        assert items["disk"]["state"] == "ok"
        assert items["git"]["state"] == "ok"
        assert items["tmp"]["state"] == "na", items["tmp"]
        assert items["work"]["state"] == "na", items["work"]
        assert "job folders without a guide page: not applicable" in detail
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert any(fn is doctor.c_workspace_growth for _id, _label, fn, _git in doctor.CHECKS)


def test_growth_missing_folders_are_not_applicable():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-empty-")
    try:
        config = {"growth": {"work_dirs": ["no/such/dir"]}}
        status, detail, items = doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        assert status == doctor.PASS, (status, detail)
        assert [items[k]["state"] for k in ("git", "tmp", "work")] == ["na", "na", "na"], items
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_growth_lowered_lines_warn_each_item_and_never_fail():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-warn-")
    try:
        _growth_tree(root)
        config = {"thresholds": {
            "growth_disk_free_min_bytes": 200 * 1024 ** 4,
            "growth_git_max_bytes": 0,
            "growth_tmp_stale_max_bytes": 1024,
            "growth_unguided_work_dirs_max": 1,
        }}
        status, detail, items = doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        assert status == doctor.WARN, (status, detail)
        assert all(items[k]["state"] == "over" for k in ("disk", "git", "tmp", "work")), items
        assert items["tmp"]["value"] == 4096, items["tmp"]
        assert "old-job" in detail and "fresh.txt" not in detail
        # A guide page at the top of the folder counts; one deeper down does not.
        assert items["work"]["value"] == 2, items["work"]
        assert "bare-1" in detail and "bare-2" in detail and "guided" not in detail

        status, detail, items = doctor._growth_report(root, {}, disk_usage=_plenty_of_disk)
        assert status == doctor.PASS, (status, detail)
        assert all(items[k]["state"] == "ok" for k in ("disk", "git", "tmp", "work")), items
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_growth_check_writes_nothing():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-ro-")
    try:
        _growth_tree(root)
        before = _snapshot(root)
        config = {"thresholds": {"growth_git_max_bytes": 0, "growth_tmp_stale_max_bytes": 0,
                                 "growth_unguided_work_dirs_max": 0}}
        doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        doctor._growth_report(root, {}, disk_usage=_plenty_of_disk)
        after = _snapshot(root)
        changed = sorted(os.path.relpath(path, root) for path in set(before) | set(after)
                         if before.get(path) != after.get(path))
        assert not changed, changed
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_growth_large_tmp_stops_at_time_limit():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-growth-big-")
    try:
        for d in range(40):
            folder = os.path.join(root, "tmp", f"d{d}")
            os.makedirs(folder)
            for n in range(250):
                open(os.path.join(folder, f"f{n}"), "w").close()
        config = {"thresholds": {"growth_scan_budget_ms": 1}}
        started = time.monotonic()
        status, detail, items = doctor._growth_report(root, config, disk_usage=_plenty_of_disk)
        elapsed = time.monotonic() - started
        assert items["tmp"]["state"] == "unmeasured", items["tmp"]
        assert items["disk"]["state"] == "ok"
        assert status == doctor.WARN, (status, detail)
        assert "tmp/ untouched over 14 days: not measured within 1 ms" in detail, detail
        assert elapsed < 0.5, elapsed
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_python_floor_is_3_9():
    import collections
    import doctor
    Version = collections.namedtuple("Version", "major minor micro releaselevel serial")
    real_sys = doctor.sys
    try:
        doctor.sys = types.SimpleNamespace(version_info=Version(3, 8, 18, "final", 0))
        status, detail = doctor.c_python()
        assert status == doctor.FAIL and "3.9" in detail, (status, detail)
        doctor.sys = types.SimpleNamespace(version_info=Version(3, 9, 0, "final", 0))
        status, detail = doctor.c_python()
        assert status == doctor.PASS, (status, detail)
    finally:
        doctor.sys = real_sys


def test_private_parse_warning_keeps_error_in_english():
    import config as C
    warning = ("doctor.config_warn_private_parse", {"error": "Expecting value"})
    text = C.warning_text(warning)
    assert "Expecting value" in text and "parse failed" in text, text
    row = ("doctor.config_warn_private", {"index": 0, "problem": "doctor.config_warn_problem_object"})
    text = C.warning_text(row)
    assert text == "private thread registry[0] is not an object; skipped", text
    # The no-tracks warning names the file and key to edit.
    assert "instance/config.json" in C.warning_text(("doctor.config_warn_tracks", {}))


def test_coherence_row_counts_hub_and_status_issues():
    import coherence
    import doctor
    saved = coherence.check_hubs, coherence.check_status_docs
    try:
        coherence.check_hubs, coherence.check_status_docs = (lambda: ["hub"]), (lambda: ["old"])
        status, detail = doctor.c_coherence()
        assert status == doctor.WARN and "2" in detail, (status, detail)
    finally:
        coherence.check_hubs, coherence.check_status_docs = saved


def test_manual_items_name_only_what_is_installed_and_a_broken_config_names_its_error():
    import doctor
    from unittest.mock import patch
    C = doctor.C
    names = ("load_ok", "error", "error_detail")
    saved = {name: getattr(C, name) for name in names}
    saved_file = doctor.P.config_file
    broken = tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False)
    try:
        # Manual items need something to act with: none without a runtime, the canary names
        # only the runtimes installed, and the Codex rules check needs Codex.
        title = "Does Codex read AGENTS.md and follow its rules?"
        for installed, flag, codex_item in (((), None, False), (("claude",), "--claude", False),
                                            (("claude", "codex"), "--all", True)):
            with patch.object(doctor.shutil, "which", lambda name: name if name in installed else None):
                items = doctor._manual_items()
            hows = " ".join(how for _title, how in items)
            assert (flag is None) == (not items) and (flag is None or flag in hows), items
            assert any(name == title for name, _how in items) == codex_item, items
        # A broken config names the loader's error and skips the schema row.
        broken.write(b'\xff{"instance": {"name": "x"')
        broken.close()
        doctor.P.config_file = lambda root=None: broken.name
        C.load_ok = lambda: False
        C.error, C.error_detail = lambda: "invalid", lambda: "fixture loader detail"
        status, detail = doctor.c_config()
        assert status == doctor.FAIL and "fixture loader detail" in detail, (status, detail)
        assert doctor.c_schema()[0] == doctor.SKIP
    finally:
        for name, reader in saved.items():
            setattr(C, name, reader)
        doctor.P.config_file = saved_file
        os.unlink(broken.name)


def test_command_line_is_parsed():
    # --help and a mistyped flag stop before any check runs, so nothing is logged anywhere.
    instance = tempfile.mkdtemp(prefix="doctor-cli-")
    try:
        env = dict(os.environ, MOTTORI_INSTANCE=instance)
        env.pop("MOTTORI_INTERNAL_RUN", None)
        run = lambda *args: subprocess.run(  # noqa: E731
            [sys.executable, os.path.join(HERE, "doctor.py"), *args], cwd=ROOT, env=env,
            capture_output=True, text=True, stdin=subprocess.DEVNULL)
        shown = run("--help")
        assert shown.returncode == 0 and "--no-runtimes" in shown.stdout, shown
        import doctor
        assert "runtime · python" not in shown.stdout, shown.stdout
        typo = run("--jso")
        assert typo.returncode == 2 and "--jso" in typo.stderr, typo
        assert os.listdir(instance) == [], os.listdir(instance)
    finally:
        shutil.rmtree(instance, ignore_errors=True)


def test_missing_transcripts_warn_only_after_a_claude_turn():
    # A Codex-only or command-line instance has journal entries and no Claude transcripts; only
    # a Claude Code turn-end record shows that a session should have left a transcript folder.
    import doctor
    runs = tempfile.NamedTemporaryFile("w", delete=False)
    runs.close()
    saved = doctor.P.transcripts, doctor.J.parse_journal, doctor.P.tool_runs
    try:
        missing = os.path.join(tempfile.gettempdir(), f"no-transcripts-{os.getpid()}")
        doctor.P.transcripts = lambda root=None: missing
        doctor.J.parse_journal = lambda *args, **kwargs: [{}] * 50
        doctor.P.tool_runs = lambda root=None: runs.name
        status, detail = doctor.c_transcripts()
        assert status == doctor.SKIP and "Codex" in detail, (status, detail)
        with open(runs.name, "w", encoding="utf-8") as f:
            f.write("2026-11-20T10:00:00+09:00\tgate\t-\tpass@Stop\n")
        status, detail = doctor.c_transcripts()
        assert status == doctor.WARN, (status, detail)
    finally:
        doctor.P.transcripts, doctor.J.parse_journal, doctor.P.tool_runs = saved
        os.unlink(runs.name)


def test_rows_say_what_is_true_for_this_folder():
    import doctor
    home = tempfile.mkdtemp(prefix="doctor-home-")
    saved = os.environ.get("HOME"), doctor._hook_cmds, doctor.C.load_ok
    real_cmds = doctor._hook_cmds
    real_root = doctor.ROOT
    try:
        os.environ["HOME"] = home
        doctor.ROOT = home
        assert "git checkout -- .claude/settings.json" in doctor._wiring("claude")[1]
        doctor.ROOT = real_root
        doctor._hook_cmds = lambda runtime="claude": {"UserPromptSubmit": ["date '+%F'"]}
        status, detail = doctor.c_global_hook()
        assert status == doctor.SKIP and "other folders" in detail, (status, detail)
        # A date in an error handler goes to a log, so it does not inject the time.
        resume = ['sh tools/hook.sh gate.py resume || date "+%FT%T failed" >> state/.hook-errors.log']
        doctor._hook_cmds = lambda runtime="claude": {"UserPromptSubmit": resume}
        missing = doctor.GLOBAL_MISSING
        assert doctor.c_global_hook() == (doctor.WARN, missing)

        def broken(runtime="claude"):
            raise json.JSONDecodeError("Expecting value", "", 0)
        doctor._hook_cmds = broken
        assert doctor.c_global_hook() == (doctor.WARN, missing)
        # Valid JSON with the wrong shape is named rather than reported as missing global settings.
        doctor._hook_cmds, doctor.ROOT = real_cmds, os.path.join(home, "project")
        os.makedirs(os.path.join(doctor.ROOT, ".claude"))
        with open(os.path.join(doctor.ROOT, ".claude", "settings.json"), "w") as f:
            f.write("[]")
        status, detail = doctor.c_global_hook()
        assert status == doctor.WARN and detail.startswith(".claude/settings.json "), detail
        # The config row already reports a missing config; a schema row would repeat it as v1.
        doctor.C.load_ok = lambda: False
        assert doctor.c_schema()[0] == doctor.SKIP
        doctor.C.load_ok = saved[2]
        # Transcript retention: the default 30 days is named, a longer user setting is plain, and
        # the instance's own file wins even when it cannot be measured.
        retention = doctor._transcript_retention
        assert "30 days" in retention() and "cleanupPeriodDays" in retention(), retention()
        os.makedirs(os.path.join(home, ".claude"))
        with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
            json.dump({"cleanupPeriodDays": 90}, f)
        assert retention() == "transcripts kept 90 days (cleanupPeriodDays)", retention()
        local = os.path.join(doctor.ROOT, ".claude", "settings.local.json")
        with open(local, "w") as f:
            json.dump({"cleanupPeriodDays": "90"}, f)
        assert "not measured" in retention() and "not a number" in retention(), retention()
        with open(local, "w") as f:
            f.write("{")
        assert "not measured" in retention() and "settings.local.json" in retention(), retention()
    finally:
        os.environ["HOME"] = saved[0]
        doctor._hook_cmds, doctor.C.load_ok, doctor.ROOT = saved[1], saved[2], real_root
        shutil.rmtree(home, ignore_errors=True)


def test_ledger_failure_names_the_first_problem():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-ledger-")
    os.makedirs(os.path.join(root, "_private", "ledger", "facts"))
    saved = os.environ.get("MOTTORI_INSTANCE"), doctor.sh
    try:
        os.environ["MOTTORI_INSTANCE"] = root
        doctor.sh = lambda *cmd, **kw: types.SimpleNamespace(
            returncode=1, stderr="",
            stdout="PROBLEM f1: path missing: talk\nPROBLEM f2: path missing: x\n")
        status, detail = doctor.c_ledger()
        assert status == doctor.FAIL and "f1: path missing: talk" in detail, (status, detail)
    finally:
        doctor.sh = saved[1]
        _restore_env("MOTTORI_INSTANCE", saved[0])
        shutil.rmtree(root, ignore_errors=True)


def test_precompact_journal_marker_check():
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-journal-marker-")
    saved = os.environ.get("MOTTORI_INSTANCE"), doctor.P.transcripts
    try:
        os.environ["MOTTORI_INSTANCE"] = root
        os.makedirs(os.path.join(root, "state"))
        os.makedirs(os.path.join(root, "_private", "state"))
        # Before any Claude Code session the transcript row warns instead of this one.
        doctor.P.transcripts = lambda root=None: os.path.join(os.environ["MOTTORI_INSTANCE"], "no-transcripts")
        status, _detail = doctor.c_precompact_journal()
        assert status == doctor.SKIP, status
        doctor.P.transcripts = lambda root=None: os.environ["MOTTORI_INSTANCE"]
        # A workspace with no journal row, or in its first weeks, has had no reason to compact.
        status, _detail = doctor.c_precompact_journal()
        assert status == doctor.SKIP, status
        import datetime
        recent = (datetime.datetime.now().astimezone() - datetime.timedelta(days=2)).isoformat(timespec="seconds")
        journal = os.path.join(root, "state", "journal-2026-11.md")
        with open(journal, "w", encoding="utf-8") as f:
            f.write(f"- {recent} [system/state] instance set up\n")
        status, _detail = doctor.c_precompact_journal()
        assert status == doctor.SKIP, status
        with open(journal, "w", encoding="utf-8") as f:
            # A row that only quotes the marker is not a compaction event.
            f.write("- 2026-09-01T10:00:00+09:00 [system/lesson] why is [system/state] "
                    "compaction occurred never recorded\n")
        status, _detail = doctor.c_precompact_journal()
        assert status == doctor.WARN, status
        marker = doctor.PRECOMPACT_MARKER
        with open(os.path.join(root, "_private", "state", "journal-2026-10.md"), "w",
                  encoding="utf-8") as f:
            f.write("- 2026-10-03T10:00:00+09:00 " + marker + " (claude · s:unknown)\n")
        status, detail = doctor.c_precompact_journal()
        assert status == doctor.PASS, (status, detail)
        assert "2026-10-03T10:00:00+09:00" in detail, detail
    finally:
        doctor.P.transcripts = saved[1]
        _restore_env("MOTTORI_INSTANCE", saved[0])
        shutil.rmtree(root, ignore_errors=True)


def test_growth_fixtures_ignore_outer_git_env():
    # A git hook exports GIT_INDEX_FILE; the fixtures must not stage into that outer index.
    outer = tempfile.mkdtemp(prefix="doctor-outer-repo-")
    root = tempfile.mkdtemp(prefix="doctor-growth-env-")
    saved = os.environ.get("GIT_INDEX_FILE")
    try:
        subprocess.run(["git", "init", "-q", outer], check=True, env=_git_env())
        os.environ["GIT_INDEX_FILE"] = os.path.join(outer, ".git", "index")
        _growth_tree(root)
        status = subprocess.run(["git", "-C", outer, "status", "--porcelain"], check=True,
                                capture_output=True, text=True, env=_git_env()).stdout
        assert status == "", status
    finally:
        if saved is None:
            os.environ.pop("GIT_INDEX_FILE", None)
        else:
            os.environ["GIT_INDEX_FILE"] = saved
        shutil.rmtree(outer, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_tracked_names_need_not_be_utf8():
    # Git stores any bytes as a name; the macOS file system refuses them, so the link is made
    # in the index only, which is all the symlink row reads.
    import doctor
    root = tempfile.mkdtemp(prefix="doctor-bytes-")
    saved = doctor.ROOT, doctor.C.load_ok
    try:
        subprocess.run(["git", "init", "-q", root], check=True, env=_git_env())
        blob = subprocess.run(["git", "-C", root, "hash-object", "-w", "--stdin"], input=b"_private/x",
                              capture_output=True, check=True, env=_git_env()).stdout.strip()
        subprocess.run([b"git", b"-C", os.fsencode(root), b"update-index", b"--add", b"--cacheinfo",
                        b"120000," + blob + b",link-\xff"], check=True, env=_git_env())
        doctor.ROOT = root
        doctor.C.load_ok = lambda: True
        # The link's target cannot be resolved on this disk, so the row warns and does not crash.
        status, detail = doctor.c_symlinks()
        assert status == doctor.WARN, (status, detail)
        # The index measurement refuses such a name on purpose; the row must say why.
        status, detail = doctor.c_ignored()
        assert status == doctor.FAIL and "Git path is not UTF-8" in detail, detail
    finally:
        doctor.ROOT, doctor.C.load_ok = saved
        shutil.rmtree(root, ignore_errors=True)


def test_recorded_link_pass_yields_to_a_failed_link_row():
    import doctor
    saved = doctor.P.tool_runs, doctor.runlog.ran_at_head
    runs = tempfile.NamedTemporaryFile("w", delete=False)
    runs.close()
    try:
        doctor.P.tool_runs = lambda root=None: runs.name
        doctor.runlog.ran_at_head = lambda *args, **kwargs: True
        doctor.results.clear()
        assert doctor.c_missed_gate() == (doctor.PASS, "linkcheck pass recorded for the current Markdown source bytes")
        doctor.results.append((doctor.FAIL, "tools_links", "BROKEN x -> y"))
        status, detail = doctor.c_missed_gate()
        assert status != doctor.PASS and doctor.LABELS["tools_links"] in detail, detail
        # Only the pass is withheld: a missing run log still warns beside a failed link row.
        os.unlink(runs.name)
        assert doctor.c_missed_gate() == (doctor.WARN, "no check execution log (instrument not running)")
        open(runs.name, "w").close()
    finally:
        doctor.P.tool_runs, doctor.runlog.ran_at_head = saved
        doctor.results.clear()
        os.unlink(runs.name)


def test_runtime_transcripts_row_says_so_for_an_installed_runtime_with_none():
    import doctor
    from unittest.mock import patch
    base = tempfile.mkdtemp(prefix="doctor-runtimes-")
    try:
        sources = [("codex", "codex-jsonl", os.path.join(base, "codex"), "**/*.jsonl"),
                   ("agy", "agy-jsonl", os.path.join(base, "agy"), "*/transcript.jsonl")]
        for installed, files, status, detail in (
                ((), (), doctor.SKIP, ""), (("agy",), (), doctor.SKIP, "agy 0"),
                (("agy",), ("agy/c/transcript.jsonl",), doctor.PASS, "agy 1"),
                (("agy", "codex"), (), doctor.SKIP, "codex 0, agy 1"),
                (("agy", "codex"), ("codex/2026/r.jsonl.zst",), doctor.PASS, "codex 1, agy 1")):
            for name in files:
                os.makedirs(os.path.dirname(os.path.join(base, name)), exist_ok=True)
                open(os.path.join(base, name), "w").close()
            with patch.object(doctor.shutil, "which", lambda name: name if name in installed else None), \
                    patch.object(doctor.C, "episodic_sources", lambda: sources):
                with patch.object(doctor, "_last_turn_end_run", lambda: "2026-11-01T10:00:00+09:00"):
                    got = doctor.c_runtime_transcripts()
                with patch.object(doctor, "_last_turn_end_run", lambda: None):
                    unused = doctor.c_runtime_transcripts()
            # A runtime never used is the usual reason for no transcripts, so it is never a warning.
            assert got[0] == status and detail in got[1], (installed, got)
            assert unused[0] == status, (installed, unused)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_missing_git_is_one_row():
    import doctor
    from unittest.mock import patch
    which = lambda name: None if name == "git" else "/bin/" + name  # noqa: E731
    try:
        doctor.results.clear()
        with patch.object(doctor.shutil, "which", which):
            for check_id, _label, fn, needs_git in doctor.CHECKS:
                if fn is doctor.c_git or needs_git:
                    doctor.check(check_id, fn, needs_git)
        failed = [row for row in doctor.results if row[0] == doctor.FAIL]
        assert [row[1] for row in failed] == ["runtime_git"], failed
        assert all(row[0] == doctor.SKIP for row in doctor.results if row not in failed), doctor.results
    finally:
        doctor.results.clear()


def test_no_runtimes_leaves_out_the_rows_that_start_a_runtime():
    import doctor
    from unittest import mock
    started = []
    with mock.patch.object(doctor, "NO_RUNTIMES", True), \
            mock.patch.object(doctor.hookdiag, "codex_hooks_list", lambda *a, **k: started.append("codex")), \
            mock.patch.object(doctor.hookdiag, "agy_hooks_list", lambda *a, **k: started.append("agy")):
        for row in (doctor.c_hook_codex_armed, doctor.c_hook_agy_armed):
            assert row() == (doctor.SKIP, doctor.RUNTIME_LEFT_OUT), row
    assert started == [], started


TESTS = [
    test_json_schema_and_exit_status,
    test_no_runtimes_leaves_out_the_rows_that_start_a_runtime,
    test_python_floor_is_3_9,
    test_runtime_transcripts_row_says_so_for_an_installed_runtime_with_none,
    test_private_parse_warning_keeps_error_in_english,
    test_coherence_row_counts_hub_and_status_issues,
    test_manual_items_name_only_what_is_installed_and_a_broken_config_names_its_error,
    test_command_line_is_parsed,
    test_tracked_names_need_not_be_utf8,
    test_recorded_link_pass_yields_to_a_failed_link_row,
    test_missing_git_is_one_row,
    test_missing_transcripts_warn_only_after_a_claude_turn,
    test_rows_say_what_is_true_for_this_folder,
    test_ledger_failure_names_the_first_problem,
    test_precompact_journal_marker_check,
    test_context_budget_over_line_is_warn_not_fail,
    test_precompact_simulation_passes_for_both_runtimes,
    test_precompact_simulation_fails_without_journal_effect,
    test_doctor_reads_last_canary_result,
    test_growth_fresh_install_shape_has_no_warning,
    test_growth_missing_folders_are_not_applicable,
    test_growth_lowered_lines_warn_each_item_and_never_fail,
    test_growth_check_writes_nothing,
    test_growth_large_tmp_stops_at_time_limit,
    test_growth_fixtures_ignore_outer_git_env,
]

def run():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as error:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(error).__name__}: {error}")
    print(f"doctor json: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
