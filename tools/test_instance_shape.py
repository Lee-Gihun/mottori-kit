#!/usr/bin/env python3
"""Exercise the engine inside the shape of a long-lived installed instance."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

from testlib import run_test


ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "system" / "engine-inventory.txt"
ENGINE_COUNT = 51
ENGINE_SHA256 = "c792d1ff7fa3178644dea1eaacfa27cb65a6f5674fe8168488a66866f267d190"
HANGUL = re.compile(r"[\uac00-\ud7a3]")


class ShapeFailure(RuntimeError):
    pass


def fail(assumption: str, detail: str) -> None:
    line = " ".join((detail or "no detail").strip().split())
    raise ShapeFailure(f"{assumption}: {line[:360]}")


def engine_names() -> list[str]:
    names = [line.strip() for line in INVENTORY.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if len(names) != len(set(names)):
        fail("engine inventory", "duplicate entry")
    if any(Path(name).name != name or name in {".", ".."} for name in names):
        fail("engine inventory", "entries must be safe tool basenames")
    missing = [name for name in names if not (ROOT / "tools" / name).is_file()]
    if missing:
        fail("engine inventory", "missing kit files: " + ", ".join(missing))
    digest = hashlib.sha256(("\n".join(sorted(names)) + "\n").encode()).hexdigest()
    if len(names) != ENGINE_COUNT or digest != ENGINE_SHA256:
        fail("engine inventory", f"pinned ENGINE mismatch count={len(names)} sha256={digest}")
    return names


def environment(lang: Optional[str] = None) -> dict[str, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MOTTORI_INTERNAL_RUN="1")
    env.pop("MOTTORI_INSTANCE", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if lang is not None:
        env["MOTTORI_LANG"] = lang
    return env


def run(root: Path, *command: str, lang: Optional[str] = None,
        timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=root, env=environment(lang), text=True,
                              capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        fail("subprocess timeout", " ".join(command) + f" after {error.timeout}s")


def require_ok(label: str, result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode:
        tail = (result.stdout + "\n" + result.stderr).strip().splitlines()[-3:]
        fail(label, f"exit={result.returncode} " + " | ".join(tail))


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = run(root, "git", *args)
    require_ok("git " + " ".join(args), result)
    return result


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_config() -> dict:
    return {
        "schema_version": 4,
        "instance": {"name": "shape-fixture", "context": "personal", "remote_allowlist": []},
        "egress": {"model_send": {"deny_prefixes": ["_private/"], "allow_prefixes": []}},
        "episodic_sources": [],
        "tracks": [{"key": "공유", "name": "한국어 트랙", "canonical": "tracks/work.md", "also": []}],
        "personal_pointer": None,
        "journal_visibility": {
            "public_tracks": ["system", "공유"],
            "legacy_cutoff": None,
            "legacy_public_tracks": [],
        },
        "threads": [],
        "checks": {
            "linkcheck_exclude_prefixes": ["archive/"],
            "hubs": [],
            "hub_ignore_ext": [".pyc", ".DS_Store"],
            "status_docs": [],
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


def build_fixture(parent: Path, names: list[str]) -> Path:
    root = parent / "installed instance"
    (root / "tools").mkdir(parents=True)
    for name in names:
        shutil.copy2(ROOT / "tools" / name, root / "tools" / name)

    for rel in (Path(".claude/settings.json"), Path(".codex/hooks.json")):
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, destination)

    write(root / ".gitignore", "/_private/\n")
    write(root / "AGENTS.md", "# Synthetic instance rules\n")
    write(root / "CLAUDE.md", "@AGENTS.md\n")
    write(root / "system/memory-config.json",
          json.dumps(fixture_config(), ensure_ascii=False, indent=2) + "\n")
    write(root / "system/decisions.md", "# 결정 기록\n\n가짜 구조 데이터다.\n")
    write(root / "system/instance-rules.md", "# Instance rules\n\nFixture only.\n")
    write(root / "system/rituals.local.md", "# Local rituals\n\nFixture only.\n")
    write(root / "tracks/work.md", "# 한국어 트랙\n\n마지막 갱신: 2026-09-18\n한국어 사용자 데이터다.\n")
    write(root / "archive/target.txt", "historical target\n")
    os.symlink("target.txt", root / "archive/legacy.md")

    month = datetime.datetime.now().strftime("%Y-%m")
    write(root / "state" / f"journal-{month}.md",
          "# journal\n\n- 2026-09-18T05:00:00+09:00 [공유/state] 한국어 저널 데이터\n")
    rendered = run(root, sys.executable, "tools/now.py", "render", lang="ko")
    require_ok("render tracked NOW", rendered)
    if (root / "_private").exists():
        fail("private absence", "NOW rendering created _private")

    git(root, "init", "-q")
    git(root, "config", "user.name", "shape-fixture")
    git(root, "config", "user.email", "shape@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "synthetic installed instance")
    write(root / "history.txt", "second commit keeps the symlink in history\n")
    git(root, "add", "history.txt")
    git(root, "commit", "-qm", "later instance history")

    if (root / "setup.sh").exists() or (root / "templates").exists():
        fail("installed shape", "setup.sh or templates exists")
    ignored = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    if ignored != ["/_private/"]:
        fail("installed shape", f"unexpected ignore rules: {ignored!r}")
    if (root / "_private").exists():
        fail("installed shape", "_private exists")
    tracked = set(git(root, "ls-files").stdout.splitlines())
    required = {
        "system/memory-config.json", "system/decisions.md", "state/NOW.md",
        f"state/journal-{month}.md", "archive/legacy.md",
    }
    if not required <= tracked:
        fail("installed shape", "untracked required paths: " + ", ".join(sorted(required - tracked)))
    mode = git(root, "ls-files", "-s", "archive/legacy.md").stdout.split()[0]
    if mode != "120000":
        fail("installed shape", f"legacy Markdown path mode={mode}")
    return root


def install_gate_baseline(root: Path) -> None:
    baseline = run(root, sys.executable, "tools/gate.py", "baseline")
    require_ok("gate baseline", baseline)
    hooks = run(root, "bash", "tools/install_hooks.sh", "--repair")
    require_ok("hook installation", hooks)


def run_regressions(root: Path, names: list[str]) -> int:
    tests = sorted(name for name in names if name.startswith("test_") and name.endswith(".py"))
    for name in tests:
        result = run(root, sys.executable, "tools/" + name, timeout=360)
        require_ok("engine regression " + name, result)
    return len(tests)


def run_required_commands(root: Path) -> None:
    doctor = run(root, sys.executable, "tools/doctor.py", timeout=600)
    require_ok("doctor installed shape", doctor)

    status = run(root, sys.executable, "tools/gate.py")
    require_ok("gate status installed shape", status)

    issues = run(root, sys.executable, "tools/enforce.py", "--issues", "--index", "--root", str(root))
    require_ok("index enforcement measurement", issues)
    forbidden = ("forbidden-index-path:state/" in issues.stdout
                 or "forbidden-index-path:system/memory-config.json" in issues.stdout
                 or "index-markdown-symlink:archive/legacy.md" in issues.stdout)
    if forbidden:
        fail("tracked state and legacy symlink", issues.stdout)

    precommit = run(root, sys.executable, "tools/gate.py", "precommit", timeout=300)
    require_ok("gate precommit installed shape", precommit)

    prepush = run(root, sys.executable, "tools/enforce.py", "prepush")
    require_ok("personal instance prepush", prepush)

    english = run(root, sys.executable, "tools/doctor.py", lang="en", timeout=600)
    require_ok("English doctor installed shape", english)
    if HANGUL.search(english.stdout):
        fail("English engine output boundary", "Hangul leaked from Korean user data into doctor stdout")


def clone_fixture(source: Path, parent: Path, name: str) -> Path:
    destination = parent / name
    shutil.copytree(source, destination, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return destination


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        fail(label, f"mutation seam count={text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def mutation_probes(root: Path, parent: Path) -> list[tuple[str, bool]]:
    probes: list[tuple[str, bool]] = []

    mutant = clone_fixture(root, parent, "mutant-templates")
    path = mutant / "tools/test_coherence.py"
    replace_once(path,
                 "source = next(p for p in (os.path.join(ROOT, \"templates\", \"memory-config.json\"),\n"
                 "                              os.path.join(ROOT, \"system\", \"memory-config.json\"))\n"
                 "                  if os.path.isfile(p))",
                 "source = os.path.join(ROOT, \"templates\", \"memory-config.json\")",
                 "templates assumption")
    probes.append(("templates required", run(mutant, sys.executable, "tools/test_coherence.py").returncode != 0))

    mutant = clone_fixture(root, parent, "mutant-setup")
    path = mutant / "tools/test_i18n.py"
    replace_once(path,
                 "if not os.path.isfile(os.path.join(ROOT, \"setup.sh\")):",
                 "if False and not os.path.isfile(os.path.join(ROOT, \"setup.sh\")):",
                 "setup.sh assumption")
    replace_once(path,
                 "    doctor = run(sys.executable, \"tools/doctor.py\")",
                 "    setup = run(\"bash\", \"setup.sh\")\n"
                 "    check(\"mutant requires setup.sh\", setup.returncode == 0, setup.stderr)\n"
                 "    return\n"
                 "    doctor = run(sys.executable, \"tools/doctor.py\")",
                 "setup.sh assumption")
    result = run(mutant, sys.executable, "-c",
                 "import sys; sys.path.insert(0,'tools'); import test_i18n as t; "
                 "t.test_english_surfaces(); raise SystemExit(1 if t.FAILED else 0)")
    probes.append(("setup.sh required", result.returncode != 0))

    mutant = clone_fixture(root, parent, "mutant-sync")
    path = mutant / "tools/test_tool_entrypoints.py"
    replace_once(path,
                 "if not (ROOT / \"tools\" / \"sync_engine.sh\").is_file():",
                 "if False and not (ROOT / \"tools\" / \"sync_engine.sh\").is_file():",
                 "sync_engine assumption")
    result = run(mutant, sys.executable, "-c",
                 "import sys; sys.path.insert(0,'tools'); import test_tool_entrypoints as t; "
                 "t.test_shell_wrappers_reject_missing_required_input()")
    probes.append(("sync_engine.sh required", result.returncode != 0))

    mutant = clone_fixture(root, parent, "mutant-state")
    path = mutant / "tools/enforce.py"
    replace_once(path,
                 "if path in FORBIDDEN_EXACT or path.startswith(FORBIDDEN_PREFIXES):\n"
                 "        if has_head:\n"
                 "            return path not in head_paths\n"
                 "        # Initial commit: there is no history to protect yet, so the only signal is the repo's own\n"
                 "        # ignore rules (a force-add). Without this an origin-style instance that tracks its public\n"
                 "        # state could never make its first commit (2026-09-18: the evidencecheck e2e fixture).\n"
                 "        return _ignored_by_rules(root, path)",
                 "if path in FORBIDDEN_EXACT or path.startswith(FORBIDDEN_PREFIXES):\n"
                 "        return True",
                 "tracked state assumption")
    result = run(mutant, sys.executable, "tools/enforce.py", "--issues", "--index", "--root", str(mutant))
    probes.append(("tracked state forbidden", "forbidden-index-path:state/NOW.md" in result.stdout))

    mutant = clone_fixture(root, parent, "mutant-symlink")
    path = mutant / "tools/enforce.py"
    replace_once(path,
                 "if mode == \"120000\" and path in changed and (context == \"work\" or path.lower().endswith(\".md\")):",
                 "if mode == \"120000\" and (context == \"work\" or path.lower().endswith(\".md\")):",
                 "historical symlink assumption")
    result = run(mutant, sys.executable, "tools/enforce.py", "--issues", "--index", "--root", str(mutant))
    probes.append(("historical Markdown symlink forbidden",
                   "index-markdown-symlink:archive/legacy.md" in result.stdout))

    mutant = clone_fixture(root, parent, "mutant-language")
    path = mutant / "tools/test_i18n.py"
    replacement = (
        "        for base in (\"state\", \"tracks\"):\n"
        "            for directory, _dirs, files in os.walk(os.path.join(ROOT, base)):\n"
        "                for name in files:\n"
        "                    payload = open(os.path.join(directory, name), encoding=\"utf-8\").read()\n"
        "                    if HANGUL.search(payload):\n"
        "                        check(\"mutant rejects Korean user data\", False, name)\n"
        "                        return\n"
        "        return\n"
        "    doctor = run(sys.executable, \"tools/doctor.py\")"
    )
    replace_once(path,
                 "        return\n    doctor = run(sys.executable, \"tools/doctor.py\")",
                 replacement,
                 "user language assumption")
    result = run(mutant, sys.executable, "-c",
                 "import sys; sys.path.insert(0,'tools'); import test_i18n as t; "
                 "t.test_english_surfaces(); raise SystemExit(1 if t.FAILED else 0)")
    probes.append(("English policy scans user data", result.returncode != 0))

    mutant = clone_fixture(root, parent, "mutant-prepush")
    (mutant / "system/memory-config.json").unlink()
    write(mutant / "setup.sh", "#!/usr/bin/env bash\n")
    write(mutant / "templates/memory-config.json", "{}\n")
    control = run(mutant, sys.executable, "tools/enforce.py", "prepush")
    path = mutant / "tools/enforce.py"
    replace_once(path,
                 "if context is None and is_presetup_kit_tree(root):",
                 "if False and context is None and is_presetup_kit_tree(root):",
                 "pre-setup kit assumption")
    result = run(mutant, sys.executable, "tools/enforce.py", "prepush")
    probes.append(("configless kit push blocked", control.returncode == 0 and result.returncode != 0))

    return probes


def main() -> int:
    try:
        names = engine_names()
        with tempfile.TemporaryDirectory(prefix="instance-shape-") as temporary:
            parent = Path(temporary)
            fixture = build_fixture(parent, names)
            install_gate_baseline(fixture)
            regression_count = run_regressions(fixture, names)
            run_required_commands(fixture)
            probes = mutation_probes(fixture, parent)
            missed = [name for name, detected in probes if not detected]
            if missed:
                fail("mutation detection", ", ".join(missed))
        print(f"engine inventory: PASS {len(names)} files, pinned ENGINE set matches")
        print(f"installed regressions: PASS {regression_count}/{regression_count}")
        print("installed commands: PASS doctor, gate status, gate precommit, enforce prepush, English doctor")
        for name, _detected in probes:
            print("mutation probe: DETECTED " + name)
        print(f"mutation probes: PASS {len(probes)}/7")
        print("instance shape: PASS")
        return 0
    except ShapeFailure as error:
        print("instance shape: FAIL " + str(error))
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"instance shape: FAIL unexpected {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run_test(main, __file__))
