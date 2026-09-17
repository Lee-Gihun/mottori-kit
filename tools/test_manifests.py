#!/usr/bin/env python3
"""Structural and coverage checks for the review and enforcement manifests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "system" / "review-manifest.yaml"
MATRIX = ROOT / "system" / "enforcement-matrix.yaml"
DELIVERY_PATHS = {
    "system/enforcement-matrix.yaml",
    "system/review-manifest.yaml",
    "tools/manifest_build.py",
    "tools/test_manifests.py",
}
KINDS = {"rule", "evidence", "tool", "hook", "template", "generated"}
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


def main() -> int:
    problems = Problems()
    review = load_yaml_subset(REVIEW, problems)
    matrix = load_yaml_subset(MATRIX, problems)
    test_review(review, problems)
    test_matrix(matrix, problems)
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
