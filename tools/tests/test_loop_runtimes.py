#!/usr/bin/env python3
"""Test the runtime order of the loop's stages and the reading of a run that could not be called."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config as LC  # noqa: E402
import loop_runtimes as LR  # noqa: E402

# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/lib/loop_runtimes.py",
)

TOOL = Path(LR.__file__)


def cli(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


class Instance:
    """A temporary instance root whose configuration holds the loop block given (None: no file)."""

    def __init__(self, block=None):
        self.block = block

    def __enter__(self):
        self.root = tempfile.mkdtemp(prefix="loop-runtimes-")
        os.makedirs(os.path.join(self.root, "instance"))
        if self.block is not None:
            Path(self.root, "instance", "config.json").write_text(json.dumps({"loop": self.block}))
        return self.root

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)


def runtimes(stage, built_by=None, root=None):
    return [(r["runtime"], r["own_family"]) for r in LR.order(stage, built_by, root)]


def test_every_stage_walks_one_order_unless_the_configuration_names_its_own():
    with Instance() as root:
        for stage in LC.STAGES:
            if stage != "review":
                assert runtimes(stage, root=root) == [(r, False) for r in LC.DEFAULT_ORDER], stage
    block = {"default": ["codex", "claude"], "digest": ["claude", "codex"], "card": ["gemini"]}
    with Instance({"runtime_orders": block}) as root:
        assert [r for r, _ in runtimes("judge", root=root)] == ["codex", "claude"]
        assert [r for r, _ in runtimes("digest", root=root)] == ["claude", "codex"]
        assert [r for r, _ in runtimes("card", root=root)] == ["gemini"]
        assert runtimes("triage", built_by="codex", root=root)[0] == ("codex", True)
    for bad in (("nope",), ("review",)):
        try:
            LR.order(*bad)
        except ValueError:
            continue
        raise AssertionError(f"order{bad} did not refuse")


def test_review_tries_the_other_families_first_and_the_builders_last():
    for block in (None, {"runtime_orders": {"review": ["codex", "claude"]}}):
        with Instance(block) as root:
            assert runtimes("review", built_by="claude", root=root) == [("codex", False), ("claude", True)]
            assert runtimes("review", built_by="codex", root=root) == [("claude", False), ("codex", True)]
    with Instance({"runtime_orders": {"review": ["claude", "gemini", "codex"]}}) as root:
        assert runtimes("review", built_by="claude", root=root) == [
            ("gemini", False), ("codex", False), ("claude", True)]
        assert runtimes("review", built_by="agy", root=root)[-1] == ("agy", True)
    r = cli("order", "review", "--built-by", "claude")
    assert r.returncode == 0 and [e["runtime"] for e in json.loads(r.stdout)][-1] == "claude", r
    assert [e["own_family"] for e in json.loads(r.stdout)].count(True) == 1, r
    assert cli("order", "review").returncode == 2


def test_unavailable_reads_only_the_recorded_reason():
    root = Path(tempfile.mkdtemp(prefix="loop-runtimes-"))
    try:
        run = root / "run"
        run.mkdir()
        assert LR.unavailable(str(run)) is None                 # no record: the walk ends
        r = cli("unavailable", str(run))
        assert r.returncode == 1 and json.loads(r.stdout) == {"unavailable": None}, r
        (run / "meta.json").write_text(json.dumps({"status": "failed", "unavailable": None}))
        assert LR.unavailable(str(run)) is None
        (run / "meta.json").write_text(json.dumps({"status": "failed", "unavailable": "model-not-available"}))
        r = cli("unavailable", str(run))
        assert r.returncode == 0 and json.loads(r.stdout) == {"unavailable": "model-not-available"}, r
        assert LR.unavailable({"unavailable": "not-installed"}) == "not-installed"
        (run / "meta.json").write_text("not json")
        assert LR.unavailable(str(run)) is None
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_installed_looks_for_the_program_the_worker_tool_starts():
    # The worker tool starts agy for gemini, so a machine with agy alone has gemini installed.
    folder = tempfile.mkdtemp(prefix="loop-runtimes-path-")
    try:
        Path(folder, "agy").write_text("#!/bin/sh\n")
        os.chmod(os.path.join(folder, "agy"), 0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith("MOTTORI_FRESH_WORKER_")}
        with Instance({"runtime_orders": {"default": ["gemini", "claude", "codex"]}}) as root, \
                mock.patch.dict(os.environ, dict(env, PATH=folder), clear=True):
            assert LR.installed(root) == ["gemini"], LR.installed(root)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


TESTS = [
    test_every_stage_walks_one_order_unless_the_configuration_names_its_own,
    test_review_tries_the_other_families_first_and_the_builders_last,
    test_unavailable_reads_only_the_recorded_reason,
    test_installed_looks_for_the_program_the_worker_tool_starts,
]


def main():
    # A test function this list does not run would pass unseen, so it fails the file.
    unlisted = sorted(n for n, f in globals().items() if n.startswith("test_") and callable(f) and f not in TESTS)
    for name in unlisted:
        print(f"✗ {name}: not in TESTS")
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"loop_runtimes: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
