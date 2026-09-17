#!/usr/bin/env python3
"""Build the tracked-text review manifest without overwriting review decisions.

Path, owner, dependencies, and review timestamp are mechanical. ``kind`` and
``consumers`` are review decisions: a first run leaves them unclassified, and
later runs preserve the values already present in the manifest.

The delivery paths are included while they are untracked in a worker clone so
the same manifest is valid before and after the patch is applied upstream.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "system" / "review-manifest.yaml"
MANIFEST_REL = "system/review-manifest.yaml"
DELIVERY_PATHS = {
    "REPORT.md",
    "system/enforcement-matrix.yaml",
    "system/language-pending.txt",
    "system/reviews/content-audit.tsv",
    "system/review-manifest.yaml",
    "system/test-matrix.yaml",
    "tools/context_budget.py",
    "tools/enforce.py",
    "tools/manifest_build.py",
    "tools/test_bypass_pins.py",
    "tools/test_context_budget.py",
    "tools/test_egress.py",
    "tools/test_enforce.py",
    "tools/test_language.py",
    "tools/test_manifests.py",
    "tools/test_matrix_check.py",
    "tools/test_mutation.py",
    "tools/test_tool_entrypoints.py",
    "tools/test_worker_batch.py",
    "tools/worker_batch.py",
}


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
    paths.update(
        path for path in DELIVERY_PATHS
        if path == MANIFEST_REL or (ROOT / path).is_file()
    )
    paths.update(locale_paths())
    return paths


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
        if path.endswith(".ko.md"):
            canonical = existing.get(path[:-len(".ko.md")] + ".md", {})
            default_kind = canonical.get("kind", "evidence")
            default_consumers = canonical.get("consumers", ["human"])
        elif path == "tools/test_language.py":
            default_kind, default_consumers = "tool", ["tool"]
        elif path == "system/language-pending.txt":
            default_kind, default_consumers = "evidence", ["human", "tool"]
        elif path == "REPORT.md":
            default_kind, default_consumers = "evidence", ["human"]
        else:
            default_kind, default_consumers = None, []
        rows.append(
            {
                "path": path,
                "kind": old.get("kind", default_kind),
                "owner": "kit",
                "consumers": old.get("consumers", default_consumers),
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if regeneration changes the file")
    args = parser.parse_args()
    wanted = render(build())
    current = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else ""
    if args.check:
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
