#!/usr/bin/env python3
"""Structural and coverage checks for the review and enforcement manifests."""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from testlib import run_test


ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "system" / "review-manifest.yaml"
MATRIX = ROOT / "system" / "enforcement-matrix.yaml"
DELIVERY_PATHS = {
    ".github/workflows/gates.yml",
    "system/engine-inventory.txt",
    "system/enforcement-matrix.yaml",
    "system/language-pending.txt",
    "system/reviews/content-audit.tsv",
    "system/review-manifest.yaml",
    "system/test-matrix.yaml",
    "tools/context_budget.py",
    "tools/enforce.py",
    "tools/i18n_stamp.py",
    "tools/manifest_build.py",
    "tools/test_bypass_pins.py",
    "tools/test_context_budget.py",
    "tools/test_devtree_gate.py",
    "tools/test_egress.py",
    "tools/test_enforce.py",
    "tools/test_instance_shape.py",
    "tools/test_language.py",
    "tools/test_manifests.py",
    "tools/test_matrix_check.py",
    "tools/test_mutation.py",
    "tools/testlib.py",
    "tools/test_tool_entrypoints.py",
    "tools/test_worker_batch.py",
    "tools/worker_batch.py",
}
APPROVAL_FILE = Path("system/gate-definition-approvals.md")


def locale_paths() -> set[str]:
    paths = {path.relative_to(ROOT).as_posix() for path in ROOT.glob("*.ko.md")}
    for base in (ROOT / "system", ROOT / "templates", ROOT / ".claude" / "commands"):
        if base.is_dir():
            paths.update(path.relative_to(ROOT).as_posix() for path in base.rglob("*.ko.md"))
    instance_locales = {
        "system/decisions.ko.md", "system/instance-rules.ko.md", "system/rituals.local.ko.md"
    }
    return {path for path in paths if path not in instance_locales and not path.startswith("system/debate/_")}
KINDS = {"rule", "evidence", "tool", "hook", "template", "generated", "gate-definition"}
OWNERS = {"kit", "instance"}
CONSUMERS = {"human", "claude", "codex", "tool"}
BOUNDARIES = {"hook", "gate", "precommit", "test", "doctor", "none"}
STATUSES = {"ENFORCED", "DETECTED", "REVIEW", "UNENFORCED"}


class Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, condition: bool, message: str) -> None:
        if not condition:
            self.items.append(message)


def load_yaml_subset(path: Path, problems: Problems) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        problems.items.append(f"{path.relative_to(ROOT)} syntax: {type(exc).__name__}: {exc}")
        return {}
    problems.add(isinstance(value, dict), f"{path.relative_to(ROOT)} root must be a mapping")
    return value if isinstance(value, dict) else {}


def expected_paths() -> set[str]:
    raw = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    paths = {item.decode("utf-8") for item in raw.split(b"\0") if item}
    # In a non-resumable worker these files cannot be added to the index. The
    # fresh-install gate stages them and therefore exercises the strict path.
    paths.update(
        path for path in DELIVERY_PATHS
        if path == "system/review-manifest.yaml" or (ROOT / path).is_file()
    )
    paths.update(locale_paths())
    text = set()
    for path in paths:
        candidate = ROOT / path
        if not candidate.is_file():
            continue
        data = candidate.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if b"\0" not in data:
            text.add(path)
    return text


def test_review(document: dict, problems: Problems) -> None:
    rows = document.get("files")
    problems.add(document.get("schema_version") == 1, "review schema_version must be 1")
    problems.add(isinstance(rows, list), "review files must be a list")
    if not isinstance(rows, list):
        return
    by_path = {}
    for index, row in enumerate(rows):
        label = f"review files[{index}]"
        problems.add(isinstance(row, dict), f"{label} must be a mapping")
        if not isinstance(row, dict):
            continue
        problems.add(set(row) == {"path", "kind", "owner", "consumers", "depends_on", "reviewed_at"},
                     f"{label} has wrong fields")
        path = row.get("path")
        problems.add(isinstance(path, str) and bool(path), f"{label}.path must be non-empty")
        if isinstance(path, str):
            problems.add(path not in by_path, f"duplicate review path: {path}")
            by_path[path] = row
        problems.add(row.get("kind") in KINDS, f"{label}.kind is unclassified")
        problems.add(row.get("owner") in OWNERS, f"{label}.owner invalid")
        consumers = row.get("consumers")
        problems.add(isinstance(consumers, list) and bool(consumers), f"{label}.consumers unclassified")
        if isinstance(consumers, list):
            problems.add(set(consumers) <= CONSUMERS, f"{label}.consumers invalid")
            problems.add(len(consumers) == len(set(consumers)), f"{label}.consumers duplicated")
        deps = row.get("depends_on")
        problems.add(isinstance(deps, list), f"{label}.depends_on must be a list")
        problems.add(row.get("reviewed_at") is None, f"{label}.reviewed_at must be null")

    expected = expected_paths()
    actual = set(by_path)
    problems.add(actual == expected,
                 "review paths differ: missing=" + repr(sorted(expected - actual))
                 + " ghost=" + repr(sorted(actual - expected)))
    for path, row in by_path.items():
        for dep in row.get("depends_on", []):
            problems.add(dep in actual, f"{path} dependency is not manifested: {dep}")
    expected_gate_definitions = {
        "system/enforcement-matrix.yaml", "system/language-pending.txt",
        "system/review-manifest.yaml", "system/test-matrix.yaml",
        ".github/workflows/gates.yml", "tools/enforce.py", "tools/evidencecheck.py",
        "tools/gate.py", "tools/manifest_build.py", "tools/test_language.py",
    }
    actual_gate_definitions = {
        path for path, row in by_path.items() if row.get("kind") == "gate-definition"
    }
    problems.add(actual_gate_definitions == expected_gate_definitions,
                 "gate-definition classification differs")


def test_gate_definition_change_requires_dispatcher_approval() -> None:
    with tempfile.TemporaryDirectory(prefix="manifest-approval-") as tmp:
        root = Path(tmp)
        (root / "tools").mkdir()
        (root / "system").mkdir()
        shutil.copy2(ROOT / "tools" / "manifest_build.py", root / "tools" / "manifest_build.py")
        for rel in (
            "tools/evidencecheck.py", "tools/enforce.py", "tools/test_language.py",
            "system/enforcement-matrix.yaml", "system/language-pending.txt",
            "system/test-matrix.yaml",
        ):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture {rel}\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(
            "# CHANGELOG\n\nSee `tools/evidencecheck.py`.\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "fixture sources"], cwd=root, check=True,
        )
        generated = subprocess.run(
            [sys.executable, "tools/manifest_build.py"], cwd=root,
            capture_output=True, text=True,
        )
        assert generated.returncode == 0, generated.stdout + generated.stderr
        converged = subprocess.run(
            [sys.executable, "tools/manifest_build.py"], cwd=root,
            capture_output=True, text=True,
        )
        assert converged.returncode == 0, converged.stdout + converged.stderr
        subprocess.run(["git", "add", "system/review-manifest.yaml"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "manifest baseline"], cwd=root, check=True,
        )
        target = root / "tools" / "evidencecheck.py"
        target.write_text(
            target.read_text(encoding="utf-8") + "changed gate definition\n", encoding="utf-8"
        )

        subprocess.run(["git", "add", "tools/evidencecheck.py"], cwd=root, check=True)
        target.write_text(target.read_text(encoding="utf-8").replace(
            "changed gate definition\n", "worktree differs from staged gate definition\n"
        ), encoding="utf-8")
        staged_env = dict(os.environ, MOTTORI_APPROVAL_MODE="staged",
                          MOTTORI_APPROVAL_REPO=str(root))
        missing = subprocess.run(
            [sys.executable, "tools/manifest_build.py", "--issues"], cwd=root,
            capture_output=True, text=True, env=staged_env,
        )
        assert missing.returncode == 0
        assert "gate-definition-approval|" in missing.stdout, missing.stdout

        changelog = root / "CHANGELOG.md"
        changelog.write_text(
            "# CHANGELOG\n\nSee `tools/evidencecheck.py`.\n\n### `[Note]` fixture\n\n"
            "gate-definition-approval: decision:KIT-DR-012 files=tools/evidencecheck.py sha256=bad\n",
            encoding="utf-8",
        )
        self_approved = subprocess.run(
            [sys.executable, "tools/manifest_build.py", "--issues"], cwd=root,
            capture_output=True, text=True, env=staged_env,
        )
        assert "gate-definition-approval|" in self_approved.stdout, self_approved.stdout

        diff = subprocess.run(
            ["git", "diff", "--cached", "--binary", "HEAD", "--", "tools/evidencecheck.py"],
            cwd=root, check=True, capture_output=True,
        ).stdout
        digest = hashlib.sha256(diff).hexdigest()
        approval = root / APPROVAL_FILE
        approval.parent.mkdir(parents=True, exist_ok=True)
        approval.write_text(
            "# WAVEE dispatcher decisions\n\n"
            "gate-definition-approval: decision:KIT-DR-012 "
            f"files=tools/evidencecheck.py sha256={digest}\n",
            encoding="utf-8",
        )
        approved = subprocess.run(
            [sys.executable, "tools/manifest_build.py", "--issues"], cwd=root,
            capture_output=True, text=True, env=staged_env,
        )
        assert "gate-definition-approval|" not in approved.stdout, approved.stdout

        subprocess.run(["git", "checkout", "--", "tools/evidencecheck.py"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "changed gate definition"], cwd=root, check=True,
        )
        base = subprocess.run(
            ["git", "rev-parse", "HEAD^"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        ci_env = dict(os.environ, MOTTORI_APPROVAL_MODE="commit",
                      MOTTORI_APPROVAL_BASE=base, MOTTORI_APPROVAL_REPO=str(root))
        approval.unlink()
        ci_missing = subprocess.run(
            [sys.executable, "tools/manifest_build.py", "--issues"], cwd=root,
            capture_output=True, text=True, env=ci_env,
        )
        assert "gate-definition-approval|" in ci_missing.stdout, ci_missing.stdout

        subprocess.run(["git", "rm", "-q", "system/review-manifest.yaml"], cwd=root, check=True)
        deleted = subprocess.run(
            [sys.executable, "tools/manifest_build.py", "--issues"], cwd=root,
            capture_output=True, text=True,
            env=dict(os.environ, MOTTORI_APPROVAL_MODE="staged", MOTTORI_APPROVAL_REPO=str(root)),
        )
        assert "~manifest-absent\t" in deleted.stdout, deleted.stdout
        assert "gate-definition-approval|" in deleted.stdout, deleted.stdout


def doctor_source_keys() -> set[str]:
    previous_lang = os.environ.get("MOTTORI_LANG")
    os.environ["MOTTORI_LANG"] = "ko"
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import doctor  # pylint: disable=import-outside-toplevel

        return {name for name, _ in doctor.CHECKS} | {title for title, _ in doctor.MANUAL}
    finally:
        if previous_lang is None:
            os.environ.pop("MOTTORI_LANG", None)
        else:
            os.environ["MOTTORI_LANG"] = previous_lang


def hook_source_keys() -> set[str]:
    keys = set()
    for runtime, rel in (("claude", ".claude/settings.json"), ("codex", ".codex/hooks.json")):
        config = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        for event, blocks in config.get("hooks", {}).items():
            for block_index, block in enumerate(blocks):
                for hook_index, _hook in enumerate(block.get("hooks", [])):
                    keys.add(f"{runtime}:{event}:{block_index}:{hook_index}")
    return keys


def test_matrix(document: dict, problems: Problems) -> None:
    rows = document.get("rules")
    problems.add(document.get("schema_version") == 1, "matrix schema_version must be 1")
    problems.add(isinstance(rows, list), "matrix rules must be a list")
    if not isinstance(rows, list):
        return
    ids = set()
    origins: dict[str, set[str]] = {}
    required = {"id", "origin", "source_key", "sources", "invariant", "boundary", "fail_close",
                "fixtures", "bypass_log", "residual", "status"}
    for index, row in enumerate(rows):
        label = f"matrix rules[{index}]"
        problems.add(isinstance(row, dict), f"{label} must be a mapping")
        if not isinstance(row, dict):
            continue
        problems.add(set(row) == required, f"{label} has wrong fields")
        rid = row.get("id")
        problems.add(isinstance(rid, str) and bool(rid), f"{label}.id invalid")
        if isinstance(rid, str):
            problems.add(rid not in ids, f"duplicate matrix id: {rid}")
            ids.add(rid)
        origin, source_key = row.get("origin"), row.get("source_key")
        problems.add(isinstance(origin, str) and bool(origin), f"{label}.origin invalid")
        problems.add(isinstance(source_key, str) and bool(source_key), f"{label}.source_key invalid")
        if isinstance(origin, str) and isinstance(source_key, str):
            origins.setdefault(origin, set()).add(source_key)
        sources = row.get("sources")
        problems.add(isinstance(sources, list) and bool(sources), f"{label}.sources invalid")
        problems.add(isinstance(row.get("invariant"), str) and bool(row.get("invariant")),
                     f"{label}.invariant invalid")
        problems.add(row.get("boundary") in BOUNDARIES, f"{label}.boundary invalid")
        problems.add(row.get("status") in STATUSES, f"{label}.status invalid")
        fixtures = row.get("fixtures")
        problems.add(isinstance(fixtures, dict) and set(fixtures) == {"positive", "negative"},
                     f"{label}.fixtures invalid")
        if isinstance(fixtures, dict):
            for polarity in ("positive", "negative"):
                path = fixtures.get(polarity)
                problems.add(path is None or (isinstance(path, str) and (ROOT / path).is_file()),
                             f"{label}.fixtures.{polarity} missing: {path}")
        problems.add(isinstance(row.get("bypass_log"), (bool, type(None))),
                     f"{label}.bypass_log must be bool or null")
        problems.add(row.get("residual") is None or isinstance(row.get("residual"), str),
                     f"{label}.residual invalid")
        if row.get("status") == "ENFORCED":
            problems.add(row.get("boundary") != "none", f"{label} ENFORCED boundary is none")
            problems.add(isinstance(row.get("fail_close"), str) and bool(row.get("fail_close")),
                         f"{label} ENFORCED fail_close is open")
            problems.add(isinstance(fixtures, dict) and all(fixtures.get(k) for k in ("positive", "negative")),
                         f"{label} ENFORCED fixtures are open")
            problems.add(row.get("bypass_log") is True, f"{label} ENFORCED bypass_log is open")
            problems.add(isinstance(row.get("residual"), str) and bool(row.get("residual")),
                         f"{label} ENFORCED residual is open")

    for core in range(1, 8):
        problems.add(str(core) in origins.get("AGENTS", set()), f"AGENTS core {core} not inventoried")
    for dr in range(1, 13):
        key = f"DR-{dr:03d}"
        problems.add(key in origins.get("KIT-DR", set()), f"{key} not inventoried")
    problems.add(origins.get("CHANGELOG") == {"v0.2-config", "v0.2-doc-pairs"},
                 "CHANGELOG [해야 함] inventory differs")
    problems.add(origins.get("doctor") == doctor_source_keys(), "doctor CHECKS/MANUAL inventory differs")
    problems.add(origins.get("hook") == hook_source_keys(), "hook command inventory differs")


def test_issues_mode_reports_stale_paths(problems: Problems) -> None:
    """gate 프로토콜: 현재 트리는 #issues 0, manifest에서 한 행을 지운 임시 사본은 manifest-missing 한 건."""
    import shutil
    import tempfile
    builder = ROOT / "tools" / "manifest_build.py"
    head_probe = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    if head_probe.returncode == 0:
        current_env = dict(os.environ, MOTTORI_APPROVAL_MODE="commit",
                           MOTTORI_APPROVAL_BASE=head_probe.stdout.strip(),
                           MOTTORI_APPROVAL_REPO=str(ROOT))
        run = subprocess.run([sys.executable, str(builder), "--issues"], cwd=ROOT,
                             capture_output=True, text=True, env=current_env)
        problems.add(run.returncode == 0 and run.stdout.rstrip().endswith("#issues 0"),
                     f"issues mode on the current tree must report 0: {run.stdout[-200:]}")
    with tempfile.TemporaryDirectory(prefix="manifest-issues-") as tmp:
        clone = Path(tmp) / "kit"
        clone.mkdir()
        for rel in sorted(expected_paths()):
            source = ROOT / rel
            if not source.is_file() and not source.is_symlink():
                continue
            target = clone / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                target.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, target)
        subprocess.run(["git", "init", "-q"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "manifest fixture"], cwd=clone, check=True, capture_output=True,
        )
        clone_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=clone, check=True, capture_output=True, text=True
        ).stdout.strip()
        clone_env = dict(os.environ, MOTTORI_APPROVAL_MODE="commit",
                         MOTTORI_APPROVAL_BASE=clone_head, MOTTORI_APPROVAL_REPO=str(clone))
        manifest = clone / "system" / "review-manifest.yaml"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        dropped = document["files"].pop(0)["path"]
        manifest.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stale = subprocess.run([sys.executable, str(clone / "tools" / "manifest_build.py"), "--issues"],
                               cwd=clone, capture_output=True, text=True, env=clone_env)
        problems.add(f"manifest-missing|{dropped}\t" in stale.stdout and stale.stdout.rstrip().endswith("#issues 1"),
                     f"issues mode must report the dropped path as missing: {stale.stdout[-300:]}")
        manifest.unlink()
        absent = subprocess.run([sys.executable, str(clone / "tools" / "manifest_build.py"), "--issues"],
                                cwd=clone, capture_output=True, text=True, env=clone_env)
        problems.add(absent.stdout.rstrip().endswith("#issues 0") and "not applicable" in absent.stdout,
                     f"a tree without the manifest is not applicable: {absent.stdout[-200:]}")


def main() -> int:
    problems = Problems()
    review = load_yaml_subset(REVIEW, problems)
    matrix = load_yaml_subset(MATRIX, problems)
    run_test(test_review, __file__, review, problems)
    run_test(test_matrix, __file__, matrix, problems)
    run_test(test_gate_definition_change_requires_dispatcher_approval, __file__)
    run_test(test_issues_mode_reports_stale_paths, __file__, problems)
    if problems.items:
        for item in problems.items:
            print("FAIL", item)
        print(f"manifest tests: FAIL ({len(problems.items)} problems)")
        return 1
    counts = {status: 0 for status in sorted(STATUSES)}
    for row in matrix["rules"]:
        counts[row["status"]] += 1
    print(f"review manifest: {len(review['files'])} text paths, unclassified 0, ghosts 0")
    print("enforcement matrix: " + " ".join(f"{key}={counts[key]}" for key in sorted(counts)))
    print("manifest tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
