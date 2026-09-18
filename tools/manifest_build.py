#!/usr/bin/env python3
"""Build the tracked-text review manifest without overwriting review decisions.

Path, owner, dependencies, and review timestamp are mechanical. ``kind`` and
``consumers`` are review decisions: a first run leaves them unclassified, and
later runs preserve the values already present in the manifest.

Untracked files under the kit's delivery prefixes are included while a worker
clone or fixture has not indexed them, so the same manifest is valid before
and after the patch is applied upstream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "system" / "review-manifest.yaml"
MANIFEST_REL = "system/review-manifest.yaml"
# Kit locations whose files count before Git indexes them. A worker clone carries its new files untracked
# (a non-resumable worker cannot add to the index) and the fresh-install fixture applies the dispatcher's patch
# the same way, so the manifest must be identical before and after `git add`. Until 2026-09-18 this was a
# hand-kept list of file names; two new files missed it and the fresh-install gate failed twenty minutes into a
# commit with a ghost-path message. A location rule has no list to forget. Worker artifacts (REPORT.md, .agents/)
# live outside these prefixes and stay out.
DELIVERY_PREFIXES = ("tools/", "system/", "templates/", ".github/workflows/", ".claude/commands/")
GATE_DEFINITION_PATHS = {
    ".github/workflows/gates.yml",
    "system/enforcement-matrix.yaml",
    "system/language-pending.txt",
    "system/review-manifest.yaml",
    "system/test-matrix.yaml",
    "tools/enforce.py",
    "tools/evidencecheck.py",
    "tools/gate.py",
    "tools/manifest_build.py",
    "tools/test_language.py",
}
# Tracked, append-only ledger. An untracked swarm-private path (the first draft) can never be seen by CI,
# so every gate-definition change would fail the remote gate (2026-09-18 port measurement).
APPROVAL_FILE = Path("system/gate-definition-approvals.md")
APPROVAL_RE = re.compile(
    r"^gate-definition-approval: decision:(?:KIT-)?DR-\d{3} "
    r"files=([^\s]+) sha256=([0-9a-f]{64})$"
)


def locale_paths() -> set[str]:
    """Return locale documents delivered before Git indexes a worker patch."""
    paths = {path.relative_to(ROOT).as_posix() for path in ROOT.glob("*.ko.md")}
    for base in (ROOT / "system", ROOT / "templates", ROOT / ".claude" / "commands"):
        if base.is_dir():
            paths.update(path.relative_to(ROOT).as_posix() for path in base.rglob("*.ko.md"))
    instance_locales = {
        "system/decisions.ko.md", "system/instance-rules.ko.md", "system/rituals.local.ko.md"
    }
    return {path for path in paths if path not in instance_locales and not path.startswith("system/debate/_")}


def git_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    paths = {raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw}
    # The output must manifest itself on the first build, before it exists.
    paths.add(MANIFEST_REL)
    paths.update(untracked_delivery_paths())
    paths.update(locale_paths())
    return paths


def untracked_delivery_paths(root: Path = ROOT) -> set[str]:
    """Untracked, not ignored files under DELIVERY_PREFIXES: what `git add -A` would add there."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=root, check=True, capture_output=True
    )
    names = (raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw)
    return {name for name in names if name.startswith(DELIVERY_PREFIXES)}


def is_text(path: Path) -> bool:
    data = path.read_bytes()
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def load_existing() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    try:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        row.get("path"): row
        for row in document.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }


def _approval_diff_args() -> tuple[Path, list[str]]:
    repo = Path(os.environ.get("MOTTORI_APPROVAL_REPO", ROOT)).resolve()
    mode = os.environ.get("MOTTORI_APPROVAL_MODE", "worktree")
    if mode == "staged":
        args = ["git", "diff", "--cached"]
    elif mode == "commit":
        base = os.environ.get("MOTTORI_APPROVAL_BASE", "")
        if not base:
            raise RuntimeError("MOTTORI_APPROVAL_BASE is required for commit approval comparison")
        args = ["git", "diff", base, "HEAD"]
    elif mode == "worktree":
        args = ["git", "diff", "HEAD"]
    else:
        raise RuntimeError(f"unknown approval comparison mode: {mode}")
    return repo, args


def changed_gate_definitions(root: Path = ROOT) -> list[str]:
    repo, args = _approval_diff_args()
    command = [*args, "--name-only", "--", *sorted(GATE_DEFINITION_PATHS)]
    result = subprocess.run(command, cwd=repo, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("cannot measure gate-definition diff: " + result.stderr.strip())
    return sorted({line for line in result.stdout.splitlines() if line in GATE_DEFINITION_PATHS})


def gate_definition_diff_sha(paths: list[str], root: Path = ROOT) -> str:
    repo, args = _approval_diff_args()
    result = subprocess.run(
        [*args, "--binary", "--", *paths],
        cwd=repo, check=True, capture_output=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _approval_lines(path: Path) -> tuple[list[str], list[str]]:
    if not path.is_file():
        return [], []
    valid, malformed = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("gate-definition-approval:"):
            continue
        if APPROVAL_RE.fullmatch(line):
            valid.append(line)
        else:
            malformed.append(f"{path}: invalid gate-definition approval syntax: {line}")
    return valid, malformed


def _approval_repo() -> Path:
    return Path(os.environ.get("MOTTORI_APPROVAL_REPO", ROOT)).resolve()


def installed_instance(root: Path) -> bool:
    """An installed instance carries ``system/memory-config.json``; the kit tree and worker clones do not."""
    return (root / "system" / "memory-config.json").is_file()


# KIT-DR-013 scope: the approval ledger governs the kit tree, where gate definitions are authored. An installed
# instance receives them through engine sync, and the origin kit's ledger already approved that diff, so the
# check is reported as not applicable there instead of blocking every engine sync (2026-09-18 port measurement).
NOT_APPLICABLE_INSTANCE = (
    "~gate-definition-approval\tnot applicable: installed instance "
    "(gate definitions arrive through engine sync; the origin kit's ledger approved that diff)"
)


def gate_definition_approval_issues(root: Path = ROOT) -> list[str]:
    if installed_instance(_approval_repo()):
        return []
    changed = changed_gate_definitions(root)
    if not changed:
        return []
    candidates: list[str] = []
    problems: list[str] = []
    approval_root, _args = _approval_diff_args()
    valid, malformed = _approval_lines(approval_root / APPROVAL_FILE)
    candidates.extend(valid)
    problems.extend(malformed)
    expected_sha = gate_definition_diff_sha(changed, root)
    expected_files = ",".join(changed)
    if problems:
        return problems
    for line in candidates:
        match = APPROVAL_RE.fullmatch(line)
        if match and match.group(1) == expected_files and match.group(2) == expected_sha:
            return []
    return [
        "gate-definition diff lacks matching dispatcher approval: "
        f"files={expected_files} sha256={expected_sha}"
    ]


def dependencies(path: str, candidates: set[str]) -> list[str]:
    if path == MANIFEST_REL:
        # The inventory is generated from the whole corpus. This also keeps a
        # first build stable when the output file does not exist yet.
        return sorted(candidates - {path})
    text = (ROOT / path).read_text(encoding="utf-8")
    found = set()
    for candidate in candidates:
        if candidate == path or not candidate:
            continue
        # References are intentionally lexical. This catches path literals in
        # docs, shell, JSON, and Python without pretending to resolve imports.
        if re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(candidate) + r"(?![A-Za-z0-9_.-])", text):
            found.add(candidate)
    return sorted(found)


def build() -> dict:
    paths = {
        path for path in git_paths()
        if path == MANIFEST_REL or ((ROOT / path).is_file() and is_text(ROOT / path))
    }
    existing = load_existing()
    rows = []
    for path in sorted(paths):
        old = existing.get(path, {})
        if path in GATE_DEFINITION_PATHS:
            default_kind, default_consumers = "gate-definition", ["human", "tool"]
        elif path.endswith(".ko.md"):
            canonical = existing.get(path[:-len(".ko.md")] + ".md", {})
            default_kind = canonical.get("kind", "evidence")
            default_consumers = canonical.get("consumers", ["human"])
        elif path in {
            "tools/i18n_stamp.py", "tools/test_devtree_gate.py",
            "tools/test_language.py", "tools/test_instance_shape.py", "tools/testlib.py",
        }:
            default_kind, default_consumers = "tool", ["tool"]
        elif path.startswith(".github/workflows/"):
            default_kind, default_consumers = "hook", ["tool"]
        elif path == "system/engine-inventory.txt":
            default_kind, default_consumers = "rule", ["human", "tool"]
        elif path == "system/language-pending.txt":
            default_kind, default_consumers = "evidence", ["human", "tool"]
        elif path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml")):
            # remote gate definitions: run by CI, read by nobody else
            default_kind, default_consumers = "tool", ["tool"]
        elif path.startswith("tools/test_") and path.endswith(".py"):
            # Regression suites are mechanical: read by people, run by the gates. Classifying them by hand
            # on every new suite was the recurring manual step behind stale-manifest blocks (2026-09-18).
            default_kind, default_consumers = "tool", ["human", "tool"]
        elif path.startswith("templates/"):
            # Instance-owned seeds copied by setup.sh: the same classification the existing template rows carry.
            default_kind, default_consumers = "template", ["human", "claude", "codex", "tool"]
        else:
            default_kind, default_consumers = None, []
        rows.append(
            {
                "path": path,
                # Path-specific defaults added later fill old unclassified rows. Gate definitions
                # always use the protected classification.
                "kind": default_kind if path in GATE_DEFINITION_PATHS else old.get("kind") or default_kind,
                "owner": "kit",
                "consumers": old.get("consumers") or default_consumers,
                "depends_on": dependencies(path, paths),
                "reviewed_at": None,
            }
        )
    return {
        "schema_version": 1,
        "generated_by": "tools/manifest_build.py",
        "files": rows,
    }


def render(document: dict) -> str:
    # JSON is a strict YAML 1.2 subset and keeps validation dependency-free.
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def issues_mode() -> int:
    """Gate checker (tools/gate.py CHECKS). A tree without the manifest (an installed instance) is not
    applicable; a stale manifest is a gated issue per path so a commit cannot land with a generated file
    behind the index (2026-09-18: the CI workflow was committed while missing from the manifest)."""
    if not MANIFEST.exists():
        print("~manifest-absent\tnot applicable: no system/review-manifest.yaml in this tree")
        if installed_instance(_approval_repo()):
            print(NOT_APPLICABLE_INSTANCE)
        try:
            approval_issues = gate_definition_approval_issues()
        except RuntimeError as error:
            approval_issues = [str(error)]
        for index, text in enumerate(approval_issues):
            print(f"gate-definition-approval|{index}\t{text}")
        print(f"#issues {len(approval_issues)}")
        return 0
    document = build()
    wanted = render(document)
    current = MANIFEST.read_text(encoding="utf-8")
    ids = []
    existing = load_existing()
    wanted_paths = {row["path"] for row in document["files"]}
    for path in sorted(wanted_paths - set(existing)):
        ids.append((f"manifest-missing|{path}", f"tracked text path not in manifest: {path}"))
    for path in sorted(set(existing) - wanted_paths):
        ids.append((f"manifest-ghost|{path}", f"manifest lists a path that is not tracked: {path}"))
    for row in document["files"]:
        if row.get("kind") is None or not row.get("consumers"):
            ids.append((f"manifest-unclassified|{row['path']}", f"kind/consumers unclassified: {row['path']}"))
    if current != wanted and not ids:
        ids.append(("manifest-stale|system/review-manifest.yaml", "manifest content differs from regeneration"))
    if installed_instance(_approval_repo()):
        print(NOT_APPLICABLE_INSTANCE)
    try:
        approval_issues = gate_definition_approval_issues()
    except RuntimeError as error:
        approval_issues = [str(error)]
    for index, text in enumerate(approval_issues):
        ids.append((f"gate-definition-approval|{index}", text))
    for issue_id, text in ids:
        print(f"{issue_id}\t{text}")
    print(f"#issues {len(ids)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if regeneration changes the file")
    parser.add_argument("--issues", action="store_true",
                        help="gate protocol: one `id<TAB>text` line per problem, then `#issues N`; exit 0")
    args = parser.parse_args()
    if args.issues:
        return issues_mode()
    wanted = render(build())
    current = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else ""
    if args.check:
        approval_issues = gate_definition_approval_issues()
        if approval_issues:
            for issue in approval_issues:
                print(issue, file=sys.stderr)
            return 1
        if current != wanted:
            print("review manifest is stale; run python3 tools/manifest_build.py", file=sys.stderr)
            return 1
        print("review manifest: current")
        return 0
    if current != wanted:
        MANIFEST.write_text(wanted, encoding="utf-8")
        print(f"wrote {MANIFEST.relative_to(ROOT)}")
    else:
        print(f"unchanged {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
