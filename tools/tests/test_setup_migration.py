#!/usr/bin/env python3
"""Privacy E2E for setup.sh v1/v2/v3 to v4 migration and existing-v4 preservation.

Only the distribution kit has setup.sh, so this suite is kit-only. Each case runs in a
temporary clone-shaped tree and never touches real instance config or state. setup.sh writes the
config through tools/lib/config_migrate.py, so these cases are that module's tests too.
"""
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def base_config(schema):
    return {
        "schema_version": schema,
        "instance": {"name": "old", "context": "personal", "remote_allowlist": []},
        "episodic_sources": [],
        "tracks": [],
        "personal_pointer": None,
        "threads": [],
        "checks": {},
        "journal_types": ["decision", "state", "artifact", "correction", "lesson", "switch", "idea"],
        "thresholds": {
            "now_tail_events": 12,
            "now_recent_decisions": 8,
            "journal_stale_days": 2,
            "memory_rot_days": 14,
            "now_hook_max_bytes": 6000,
        },
    }


@contextlib.contextmanager
def fixture(old_cfg, rows):
    """Yield a temporary clone-shaped instance root; the whole tree goes away afterwards."""
    parent = tempfile.mkdtemp(prefix="setup-migration-")
    try:
        yield _build_fixture(os.path.join(parent, "repo"), old_cfg, rows)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _build_fixture(root, old_cfg, rows):
    # The kit's own files only, so an installation's documents and data stay out (KIT-DR-089).
    from testlib import copy_kit
    copy_kit(ROOT, root)
    shutil.rmtree(os.path.join(root, "instance"), ignore_errors=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    os.makedirs(os.path.join(root, "instance"), exist_ok=True)
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    if old_cfg is not None:
        write_config(root, old_cfg)
    with open(os.path.join(root, "state", "journal-2026-01.md"), "w", encoding="utf-8") as f:
        f.write("# journal\n\n" + "".join(rows))
    # This E2E observes setup migration and the real now engine. Separate suites own the
    # surrounding doctor and gate, so use deterministic no-ops in the temporary clone.
    for name in ("doctor.py", "gate.py"):
        with open(os.path.join(root, "tools", name), "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env python3\nraise SystemExit(0)\n")
    return root


def v4_config(**visibility):
    """A current-schema config whose visibility block is already complete."""
    cfg = base_config(4)
    cfg["journal_visibility"] = dict(
        {"public_tracks": ["system"], "legacy_cutoff": None, "legacy_public_tracks": []}, **visibility)
    return cfg


def fixture_env(root, env=None):
    """Bind every fixture subprocess to its temporary instance so inherited environment
    variables cannot redirect state access.
    """
    merged = dict(os.environ if env is None else env)
    merged["MOTTORI_INSTANCE"] = root
    # An embedding server running on this machine must not change what setup writes (KIT-DR-094).
    merged.setdefault("MOTTORI_NO_LOCAL_PROBE", "1")
    return merged


def run_setup(root, env=None):
    return subprocess.run(
        ["bash", "setup.sh", "--force", "--name", "fixture"],
        cwd=root, capture_output=True, text=True, env=fixture_env(root, env))


def run_setup_defaults(root, env=None):
    return subprocess.run(
        ["bash", "setup.sh", "--force"], stdin=subprocess.DEVNULL,
        cwd=root, capture_output=True, text=True, env=fixture_env(root, env))


def run_now(root, *args):
    return subprocess.run([sys.executable, "tools/now.py", *args], cwd=root,
                          capture_output=True, text=True, env=fixture_env(root))


def setup_visibility(root):
    """Run setup, require success, and return the migrated config and its complete visibility block."""
    result = run_setup(root)
    assert result.returncode == 0, result.stdout + result.stderr
    cfg = json.loads(text(root, "instance/config.json"))
    vis = cfg.get("journal_visibility", {})
    assert {"public_tracks", "legacy_cutoff", "legacy_public_tracks"} <= vis.keys(), cfg
    return cfg, vis


def write_config(root, cfg):
    with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def text(root, rel):
    path = os.path.join(root, rel)
    assert os.path.isfile(path), f"expected setup output: {rel}"
    with open(path, encoding="utf-8") as f:
        return f.read()


def file_snapshot(root):
    """File bytes from a small fixture tree, used to prove a hostile target is unchanged."""
    out = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root)
            with open(path, "rb") as f:
                out[rel] = f.read()
    return out


def backups_of(cfg_path):
    folder, base = os.path.split(cfg_path)
    return [os.path.join(folder, n) for n in os.listdir(folder) if n.startswith(base + ".bak")]


def abort_reason(template, /, **kw):
    """The text of an abort, or its fixed prefix when placeholders are not given."""
    return template.format(**kw) if kw else template.split("{")[0].strip()


def assert_setup_aborts_without_config_overwrite(root, reason):
    cfg_path = os.path.join(root, "instance", "config.json")
    before = open(cfg_path, "rb").read()
    result = run_setup(root)
    after = open(cfg_path, "rb").read()
    assert result.returncode != 0, result.stdout + result.stderr
    # A refusal is the one-line translated reason, not a Python stack trace.
    assert "Traceback" not in result.stderr, result.stderr
    assert reason in result.stdout + result.stderr, (reason, result.stdout + result.stderr)
    assert before == after
    # A failed run must not leave a backup that differs from the original.
    assert all(open(b, "rb").read() == before for b in backups_of(cfg_path))


def test_fresh_setup_creates_v4_config_and_now():
    with fixture(None, []) as root:
        cfg, vis = setup_visibility(root)
        assert cfg["schema_version"] == 4
        # A new installation keeps no list of public tracks: nothing is private until the owner says so.
        assert vis["public_tracks"] is None
        assert vis["legacy_cutoff"] is None
        assert vis["legacy_public_tracks"] == []
        now_text = text(root, "state/NOW.md")
        assert "instance set up" in now_text, now_text
        logged = run_now(root, "log", "[launch/decision] FRESH-ORDINARY")
        assert logged.returncode == 0 and logged.stdout.startswith("recorded: "), logged.stdout + logged.stderr
        kept = run_now(root, "log", "--private", "[launch/state] FRESH-KEPT-LOCAL")
        assert kept.returncode == 0 and "recorded under _private/ (--private)" in kept.stdout, kept.stdout
        assert "FRESH-ORDINARY" in text(root, "state/NOW.md") and "FRESH-KEPT-LOCAL" not in text(root, "state/NOW.md")
        assert "FRESH-KEPT-LOCAL" in text(root, "_private/state/NOW.md")
        # A rerun keeps "no list" as it is.
        assert setup_visibility(root)[1]["public_tracks"] is None


def test_setup_asks_nothing_and_writes_one_kind_of_installation():
    with fixture(None, []) as root:
        # An agent runs setup, so it asks nothing. Instance files without a config get a new config.
        result = run_setup_defaults(root)
        assert result.returncode == 0, result.stdout + result.stderr
        cfg = json.loads(text(root, "instance/config.json"))
        # There is one kind of installation: no work or personal context, no list of remotes.
        assert set(cfg["instance"]) == {"name", "agent_openers"}, cfg["instance"]
        assert "context" not in result.stdout and "personal" not in result.stdout, result.stdout
        # The flag an earlier version took is accepted, said to be unused, and changes nothing.
        old_flag = subprocess.run(["bash", "setup.sh", "--force", "--context", "work"], stdin=subprocess.DEVNULL,
                                  cwd=root, capture_output=True, text=True, env=fixture_env(root))
        assert old_flag.returncode == 0 and "--context work is no longer used" in old_flag.stdout, old_flag.stdout
        assert "context" not in json.loads(text(root, "instance/config.json"))["instance"]
        plain = subprocess.run(["bash", "setup.sh", "--context", "work"], stdin=subprocess.DEVNULL,
                               cwd=root, capture_output=True, text=True, env=fixture_env(root))
        assert "--context work is no longer used" in plain.stdout, plain.stdout
        made = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "--allow-empty",
                               "-m", "an ordinary commit"], cwd=root, capture_output=True, text=True,
                              env=fixture_env(root))
        assert made.returncode == 0, "a commit was refused: " + made.stdout + made.stderr
        # Without a terminal one line counts the optional parts that are off, and nothing is turned on.
        assert "optional parts are off. Run python3 tools/options.py" in result.stdout, result.stdout
        assert "Turn any on now?" not in result.stdout, result.stdout
        assert "options" not in cfg and "recall_meaning" not in cfg, cfg
        # The reread check is on in a new installation (KIT-DR-084).
        assert cfg["deliver"]["block"] == ["unopened"] and cfg["deliver"]["observe"] == [], cfg["deliver"]


def test_setup_binds_instance_to_its_own_root():
    # No config here: setup writes one and freezes the row it finds, so the row shows where it was bound.
    with fixture(None, [
        "- 2026-01-01T00:00:00+09:00 [system/state] OWN-ROOT-ROW\n",
    ]) as root:
        hostile = os.path.join(os.path.dirname(root), "hostile-instance")
        os.makedirs(os.path.join(hostile, "instance"), exist_ok=True)
        os.makedirs(os.path.join(hostile, "state"), exist_ok=True)
        write_config(hostile, v4_config())
        with open(os.path.join(hostile, "state", "journal-2026-01.md"), "w", encoding="utf-8") as f:
            f.write("# journal\n\n"
                    "- 2026-01-02T00:00:00+09:00 [system/state] HOSTILE-ROW\n")
        before = file_snapshot(hostile)
        # Call setup directly: run_setup's fixture_env would replace the hostile path with root.
        result = subprocess.run(
            ["bash", "setup.sh", "--force", "--name", "fixture"],
            cwd=root, capture_output=True, text=True,
            env=dict(os.environ, MOTTORI_INSTANCE=hostile))
        assert result.returncode == 0, result.stdout + result.stderr
        cfg = json.loads(text(root, "instance/config.json"))
        assert "journal_visibility" in cfg, cfg
        assert cfg["journal_visibility"]["legacy_cutoff"] == "2026-01-01T00:00:00+09:00", cfg
        assert file_snapshot(hostile) == before
        assert "OWN-ROOT-ROW" in text(root, "_private/state/NOW.md")
        assert "HOSTILE-ROW" not in text(root, "state/NOW.md")


def test_setup_backup_is_gitignored():
    with fixture(v4_config(), []) as root:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        backups = backups_of(os.path.join(root, "instance", "config.json"))
        assert len(backups) == 1, backups
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", os.path.relpath(backups[0], root)],
            cwd=root)
        assert ignored.returncode == 0


def test_v4_preserves_existing_visibility_cutover_semantics():
    old = v4_config(
        public_tracks=["system", "shared"],
        # Older than the newest row, so a recomputed watermark would differ from it.
        legacy_cutoff="2025-12-31T00:00:00+09:00",
        legacy_public_tracks=["system"],
    )
    old["threads"] = [{
        "key": "public-thread", "name": "PUBLIC-THREAD", "dossier": "research/HANDOFF.md",
    }]
    with fixture(old, [
        "- 2026-01-01T00:00:00+09:00 [system/state] V4-OLD-SYSTEM\n",
        "- 2026-01-01T00:00:01+0900 [system/state] V4-COMPACT-OFFSET\n",
    ]) as root:
        cfg, vis = setup_visibility(root)
        assert vis["public_tracks"] == ["system", "shared"]
        assert vis["legacy_cutoff"] == "2025-12-31T00:00:00+09:00"
        assert vis["legacy_public_tracks"] == ["system"]
        assert cfg["threads"] == old["threads"]
        public_now = text(root, "state/NOW.md")
        assert "V4-OLD-SYSTEM" in public_now
        assert "PUBLIC-THREAD" in public_now and "research/HANDOFF.md" in public_now


def test_previous_release_track_key_keeps_state_working_after_update():
    """v0.10 setup wrote this config and accepted any track key; after the pull, render and the
    setup update path must still succeed, and the config warnings must name the key to rename."""
    old = v4_config()
    old["tracks"] = [{"key": "Launch", "name": "Launch", "canonical": "launch/tracker.md"}]
    with fixture(old, ["- 2026-01-01T00:00:00+09:00 [system/state] OLD-RELEASE-ROW\n"]) as root:
        rendered = run_now(root, "render")
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        assert "OLD-RELEASE-ROW" in text(root, "state/NOW.md")
        cfg, _ = setup_visibility(root)
        assert cfg["tracks"] == old["tracks"], cfg["tracks"]
        # The warnings are formatted by this tree's config.py; a placeholder clash would crash here too.
        code = "import json, config as C; print(json.dumps(C.warnings()))"
        r = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(root, "tools", "lib"),
                           env=fixture_env(root), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        import config
        texts = [config.warning_text(w) for w in json.loads(r.stdout)]
        assert any("config.tracks[0].key" in t for t in texts), texts


def test_a_config_from_before_v0_10_is_refused_with_the_way_forward():
    """Schemas 1 to 3 are not moved; setup says how to start a new config and overwrites nothing."""
    for schema in (1, 2, 3):
        old = base_config(schema)
        with fixture(old, ["- 2026-01-01T00:00:00+09:00 [system/state] OLD\n"]) as root:
            assert_setup_aborts_without_config_overwrite(root, abort_reason(
                "existing config is schema v{schema}, from before v0.10", schema=schema))


def test_malformed_legacy_journal_aborts_without_overwriting_v2_config():
    with fixture(base_config(2), [
        "- 2026-01-01T00:00:00+09:00 [system/not-a-valid-type] PREFIX-LOOKS-VALID\n"
    ]) as root:
        assert_setup_aborts_without_config_overwrite(root, abort_reason("existing journal preflight failed; nothing changed: {error}"))


def test_structurally_invalid_config_aborts_without_overwrite():
    old = base_config(2)
    old["tracks"] = "not-a-list"
    with fixture(old, []) as root:
        assert_setup_aborts_without_config_overwrite(
            root, abort_reason("config.{key} is not a {type}", key="tracks", type="list"))


def test_force_preserves_instance_settings_and_backups():
    """A second --force keeps hand-set settings and never overwrites the first backup.

    A dropped egress deny prefix widens what is sent to models, so a rerun must carry
    instance settings forward rather than reset them to the template."""
    old = v4_config()
    old["egress"] = {"model_send": {"deny_prefixes": ["_private/", "secret-notes/"],
                                    "allow_prefixes": []}}
    old["thresholds"]["custom_fixture_limit"] = 42
    # Option states are the user's: a rerun turns nothing on or off and keeps a remembered no.
    old["deliver"] = {"block": [], "observe": ["unopened"]}
    old["recall_meaning"] = {"endpoint": "http://127.0.0.1:9/v1/embeddings", "model": "fixture-model",
                             "query_prefix": "q: ", "document_prefix": "d: "}
    old["options"] = {"declined": ["codex"]}
    with fixture(old, []) as root:
        cfg_path = os.path.join(root, "instance", "config.json")
        original = open(cfg_path, "rb").read()
        for _ in range(2):
            result = run_setup(root)
            assert result.returncode == 0, result.stdout + result.stderr
        cfg = json.loads(text(root, "instance/config.json"))
        assert "secret-notes/" in cfg["egress"]["model_send"]["deny_prefixes"], cfg["egress"]
        assert cfg["thresholds"].get("custom_fixture_limit") == 42, cfg["thresholds"]
        for key in ("deliver", "recall_meaning", "options"):
            kept = {k: v for k, v in cfg[key].items() if not k.startswith("_")}
            assert kept == old[key], (key, cfg.get(key))
        backups = backups_of(cfg_path)
        assert any(open(b, "rb").read() == original for b in backups), backups


def test_a_starter_language_key_is_read_and_dropped_on_force():
    """An older setup wrote instance.lang. The config still loads, --force drops the key without
    calling it a reset, and the option that set it is an unknown argument."""
    old = v4_config()
    old["instance"]["lang"] = "ko"
    with fixture(old, []) as root:
        loaded = subprocess.run([sys.executable, "tools/lib/config.py", "get", "instance.name"],
                                cwd=root, capture_output=True, text=True, env=fixture_env(root))
        assert loaded.returncode == 0 and loaded.stdout.strip() == "old", loaded.stdout + loaded.stderr
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "reset to the template" not in result.stdout, result.stdout
        cfg = json.loads(text(root, "instance/config.json"))
        assert "lang" not in cfg["instance"], cfg["instance"]
        refused = subprocess.run(["bash", "setup.sh", "--lang", "ko"], stdin=subprocess.DEVNULL, cwd=root,
                                 capture_output=True, text=True, env=fixture_env(root))
        assert refused.returncode != 0, refused.stdout
        assert "unknown argument: --lang" in refused.stdout and "usage: bash setup.sh" in refused.stdout, refused.stdout


def test_an_earlier_configs_context_and_remote_list_are_dropped_and_said_so():
    old = v4_config()
    old["instance"].update(context="work", remote_allowlist=["https://example.invalid/kit.git"])
    with fixture(old, []) as root:
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        instance = json.loads(text(root, "instance/config.json"))["instance"]
        assert "context" not in instance and "remote_allowlist" not in instance, instance
        assert "no longer used and removed: instance.context, instance.remote_allowlist" in result.stdout, result.stdout
        # The second run has nothing left to drop and says nothing about it.
        again = run_setup(root)
        assert again.returncode == 0 and "no longer used" not in again.stdout, again.stdout


def journal_rows(root):
    """Count event rows in the public and private journals of a fixture tree."""
    count = 0
    for folder in ("state", os.path.join("_private", "state")):
        path = os.path.join(root, folder)
        if not os.path.isdir(path):
            continue
        for name in os.listdir(path):
            if re.match(r"journal-\d{4}-\d{2}\.md$", name):
                with open(os.path.join(path, name), encoding="utf-8") as f:
                    count += sum(1 for line in f if re.match(r"- \d{4}-\d{2}-\d{2}T", line))
    return count


def test_force_rerun_adds_no_journal_rows():
    """Reruns must not grow the journal, and must not save the gate baseline again: a save adopts
    every current issue and clears a block another session is waiting on."""
    with fixture(None, []) as root:
        calls = os.path.join(root, "baseline-calls")
        with open(os.path.join(root, "tools", "gate.py"), "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env python3\nimport sys\n"
                    "if sys.argv[1:] == ['baseline']:\n"
                    f"    open({calls!r}, 'a').write('x')\n"
                    "    open('state/.gate-baseline.json', 'a').close()\n")
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        first = journal_rows(root)
        assert first > 0, first
        saves = open(calls).read()
        for _ in range(2):
            result = run_setup(root)
            assert result.returncode == 0, result.stdout + result.stderr
        assert journal_rows(root) == first, (first, journal_rows(root))
        assert open(calls).read() == saves, "a rerun saved the gate baseline again"
        # An interrupted first run leaves the config without the later outputs; a plain rerun
        # must name what is missing instead of reporting the instance as set up.
        os.remove(os.path.join(root, "state", "NOW.md"))
        plain = subprocess.run(["bash", "setup.sh"], cwd=root, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, env=fixture_env(root))
        assert plain.returncode != 0 and "state/NOW.md" in plain.stdout, plain.stdout + plain.stderr
        assert "already set up" not in plain.stdout, plain.stdout


def test_setup_leaves_foreign_and_enclosing_repository_hooks_alone():
    """A foreign hook is kept with a next step that works, and a kit folder inside another
    project's repository writes nothing into that repository."""
    with fixture(None, []) as root:
        hook = os.path.join(root, ".git", "hooks", "pre-commit")
        with open(hook, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        result = run_setup(root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert open(hook, encoding="utf-8").read() == "#!/bin/sh\nexit 0\n"
        # The free pre-push is still installed, and the output names the hook in the way; the ways
        # forward are doctor's row, which this fixture replaces with a no-op.
        assert os.path.exists(os.path.join(root, ".git", "hooks", "pre-push"))
        assert ".git/hooks/pre-commit skipped (foreign hook left untouched)" in result.stdout, result.stdout
    with fixture(None, []) as root:
        shutil.rmtree(os.path.join(root, ".git"))
        outer = os.path.dirname(root)
        subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
        # Another session's pending block in the enclosing repository must survive.
        pending = os.path.join(outer, ".git", "mottori-gate-pending")
        with open(pending, "w", encoding="utf-8") as f:
            f.write('{"OTHER": {"reason": "x"}}\n')
        result = run_setup(root)
        assert result.returncode != 0, result.stdout + result.stderr
        assert "This folder is not the top of its own Git repository" in result.stdout, result.stdout + result.stderr
        hooks = os.listdir(os.path.join(outer, ".git", "hooks"))
        assert not [n for n in hooks if not n.endswith(".sample")], hooks
        assert os.path.exists(pending)
        assert not os.path.exists(os.path.join(root, "instance", "config.json"))
    # A folder in no repository at all (a ZIP download) stops before writing anything.
    with fixture(None, []) as root:
        shutil.rmtree(os.path.join(root, ".git"))
        result = run_setup(root)
        assert result.returncode != 0, result.stdout + result.stderr
        assert "This folder is not the top of its own Git repository" in result.stdout, result.stdout + result.stderr
        assert not os.path.exists(os.path.join(root, "instance", "config.json"))


def test_configless_recovery_freezes_history_private():
    """Without a config there is no record of what was public, so existing rows stay private; the
    combined view at session start still shows them."""
    with fixture(None, [
        "- 2026-01-01T00:00:00+09:00 [system/state] CONFIGLESS-OLD-SYSTEM\n",
    ]) as root:
        _cfg, vis = setup_visibility(root)
        assert vis["legacy_cutoff"] == "2026-01-01T00:00:00+09:00", vis
        assert vis["legacy_public_tracks"] == [], vis
        assert "CONFIGLESS-OLD-SYSTEM" not in text(root, "state/NOW.md")
        assert "CONFIGLESS-OLD-SYSTEM" in text(root, "_private/state/NOW.md")


def test_a_saved_track_list_is_kept_on_update():
    """A list the installation holds is kept as it is, ["system"] included: nothing tells an owner's
    choice from the earlier template's default, so nothing widens what is public."""
    for tracks in (["system"], ["system", "launch"]):
        with fixture(v4_config(public_tracks=tracks), []) as root:
            result = subprocess.run(["bash", "setup.sh", "--force"], stdin=subprocess.DEVNULL, cwd=root,
                                    capture_output=True, text=True, env=fixture_env(root))
            assert result.returncode == 0, result.stdout + result.stderr
            vis = json.loads(text(root, "instance/config.json"))["journal_visibility"]
            assert vis["public_tracks"] == tracks, vis


def test_newer_schema_aborts():
    """A config from a newer kit, or with a non-integer schema_version, is refused untouched."""
    for schema, reason in (
        (5, abort_reason("existing config v{old} is newer than this engine v{new}", old=5, new=4)),
        ("4", abort_reason("config.schema_version is not an int")),
    ):
        old = v4_config()
        old["schema_version"] = schema
        with fixture(old, []) as root:
            assert_setup_aborts_without_config_overwrite(root, reason)


def test_template_ships_no_placeholder_track_and_still_validates():
    """setup.sh discards the template's tracks on a fresh install, so the template ships none; the
    empty array must still pass the config schema and surface the no-tracks warning to the owner."""
    with open(os.path.join(ROOT, "templates", "config.json"), encoding="utf-8") as handle:
        template = json.load(handle)
    assert template["tracks"] == [], template["tracks"]
    with open(os.path.join(ROOT, "MANUAL.md"), encoding="utf-8") as handle:
        manual = handle.read()
    assert '| `tracks` | Active lines of work, each `{"key", "name", "canonical", "also"}`' in manual, \
        "MANUAL.md section 2 gives the track shape"
    with tempfile.TemporaryDirectory(prefix="template-config-") as fixture:
        os.makedirs(os.path.join(fixture, "instance"))
        shutil.copy(os.path.join(ROOT, "templates", "config.json"),
                    os.path.join(fixture, "instance", "config.json"))
        code = ("import json, config as C; C.validate(json.load(open(C.path(), encoding='utf-8'))); "
                "print(('doctor.config_warn_tracks', {}) in C.warnings())")
        env = dict(os.environ, MOTTORI_INSTANCE=fixture)
        r = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(ROOT, "tools", "lib"), env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.strip() == "True", r.stdout


OLD_LAYOUT = {  # where a file lived under system/ before instance/, and where it moves
    "system/memory-config.json": "instance/config.json",
    "system/memory-config.json.bak-1": "instance/config.json.bak-1",
    "system/instance-rules.md": "instance/rules.md",
    "system/rituals.local.md": "instance/rituals.md",
    "system/decisions.md": "instance/decisions.md",
    "system/debate/round.md": "instance/debate/round.md",
    "system/debate/_dispatch.log": "state/debate-dispatch.log",
    "system/memory-map.html": "state/memory-map.html",
}


def _old_layout(root):
    for rel in OLD_LAYOUT:
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        body = json.dumps(v4_config()) if rel.endswith(".json") else f"bytes of {rel}\n"
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(body)
    os.chmod(os.path.join(root, "system/instance-rules.md"), 0o600)
    return {rel: open(os.path.join(root, rel), "rb").read() for rel in OLD_LAYOUT}


def test_old_layout_says_one_line_until_force_moves_each_file_once():
    """Files still under system/ are not a new install: every command says one line, and
    setup.sh --force moves each file once with its bytes and mode; a second run moves nothing."""
    with fixture(None, []) as root:
        before = _old_layout(root)
        # Until the move, .gitignore keeps the old places out of Git.
        offered = subprocess.run(["git", "add", "-A", "-n"], cwd=root, capture_output=True,
                                 text=True, check=True).stdout
        assert not any(old in offered for old in OLD_LAYOUT), offered
        get = subprocess.run([sys.executable, "tools/lib/config.py", "get", "instance.name"], cwd=root,
                             capture_output=True, text=True, env=fixture_env(root))
        line = get.stderr.strip()
        assert get.returncode == 1 and "8 files" in line and "bash setup.sh --force" in line, get
        assert line in run_now(root, "check").stdout
        plain = subprocess.run(["bash", "setup.sh"], cwd=root, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, env=fixture_env(root))
        assert plain.returncode == 1 and plain.stdout.strip() + plain.stderr.strip() == line, plain
        moved = run_setup(root)
        assert moved.returncode == 0, moved.stdout + moved.stderr
        for old, new in OLD_LAYOUT.items():
            assert f"  {old} -> {new}" in moved.stdout, moved.stdout
            assert not os.path.exists(os.path.join(root, old)), old
        # The update's config merge rewrites config.json and backs up the moved bytes first.
        for old, new in OLD_LAYOUT.items():
            if new != "instance/config.json":
                assert open(os.path.join(root, new), "rb").read() == before[old], new
        assert os.stat(os.path.join(root, "instance/rules.md")).st_mode & 0o777 == 0o600
        again = run_setup(root)
        assert again.returncode == 0 and "moved" not in again.stdout, again.stdout


def test_old_layout_file_at_both_places_stops_the_move():
    with fixture(None, []) as root:
        _old_layout(root)
        with open(os.path.join(root, "instance/rules.md"), "w", encoding="utf-8") as f:
            f.write("newer rules\n")
        result = run_setup(root)
        assert result.returncode == 1, result.stdout
        assert "system/instance-rules.md and instance/rules.md" in result.stdout, result.stdout
        assert all(os.path.exists(os.path.join(root, old)) for old in OLD_LAYOUT)


def test_a_file_at_an_old_place_is_the_owners_own_once_the_config_is_in_the_instance_folder():
    with fixture(None, []) as root:
        assert run_setup(root).returncode == 0
        mine = os.path.join(root, "system/decisions.md")
        with open(mine, "w", encoding="utf-8") as f:
            f.write("# my decisions\n")
        get = subprocess.run([sys.executable, "tools/lib/config.py", "get", "instance.name"], cwd=root,
                             capture_output=True, text=True, env=fixture_env(root))
        assert get.returncode == 0 and "old places" not in get.stderr, get
        assert "old places" not in run_now(root, "check").stdout
        again = run_setup(root)
        assert again.returncode == 0 and "moved" not in again.stdout and "both places" not in again.stdout, again.stdout
        assert open(mine, encoding="utf-8").read() == "# my decisions\n", "setup touched the owner's file"


TESTS = [
    test_a_config_from_before_v0_10_is_refused_with_the_way_forward,
    test_fresh_setup_creates_v4_config_and_now,
    test_setup_asks_nothing_and_writes_one_kind_of_installation,
    test_setup_binds_instance_to_its_own_root,
    test_setup_backup_is_gitignored,
    test_v4_preserves_existing_visibility_cutover_semantics,
    test_previous_release_track_key_keeps_state_working_after_update,
    test_malformed_legacy_journal_aborts_without_overwriting_v2_config,
    test_structurally_invalid_config_aborts_without_overwrite,
    test_force_preserves_instance_settings_and_backups,
    test_a_starter_language_key_is_read_and_dropped_on_force,
    test_force_rerun_adds_no_journal_rows,
    test_an_earlier_configs_context_and_remote_list_are_dropped_and_said_so,
    test_setup_leaves_foreign_and_enclosing_repository_hooks_alone,
    test_configless_recovery_freezes_history_private,
    test_a_saved_track_list_is_kept_on_update,
    test_newer_schema_aborts,
    test_template_ships_no_placeholder_track_and_still_validates,
    test_old_layout_says_one_line_until_force_moves_each_file_once,
    test_old_layout_file_at_both_places_stops_the_move,
    test_a_file_at_an_old_place_is_the_owners_own_once_the_config_is_in_the_instance_folder,
]


def run():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as e:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
    print(f"setup migration: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
