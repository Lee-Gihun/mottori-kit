#!/usr/bin/env python3
"""Fixture tests for committed worker-batch coverage (experiment:X11)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
FRESH_WORKER = HERE / "fresh_worker.py"
WORKER_BATCH = HERE / "worker_batch.py"


def _script(path, body):
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _fixture():
    root = Path(tempfile.mkdtemp(prefix="worker-batch-"))
    (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    prompts = []
    for index in range(10):
        path = root / f"prompt-{index:02d}.md"
        path.write_text(f"do slot {index:02d}\n", encoding="utf-8")
        prompts.append(path)
    fake = root / "fake codex"
    _script(fake, """
import json, pathlib, sys
args = sys.argv[1:]
sys.stdin.read()
out = pathlib.Path(args[args.index("--output-last-message") + 1])
out.write_text("ok\\n", encoding="utf-8")
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}))
""")
    return root, prompts, fake


def _env(root, fake=None):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root))
    if fake is not None:
        env["MOTTORI_FRESH_WORKER_CODEX_BIN"] = str(fake)
    return env


def _create(root, prompts):
    manifest = root / "batch.json"
    slots = [f"slot-{index:02d}" for index in range(10)]
    result = subprocess.run(
        [sys.executable, str(WORKER_BATCH), "create", str(manifest),
         "--slots", ",".join(slots), "--prompts", *map(str, prompts)],
        cwd=root, env=_env(root), text=True, capture_output=True,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert [row["name"] for row in document["slots"]] == slots
    assert [row["prompt_sha256"] for row in document["slots"]] == [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in prompts
    ]
    return manifest, slots


def _run_slots(root, manifest, slots, prompts, fake):
    for slot, prompt in zip(slots, prompts):
        result = subprocess.run(
            [sys.executable, str(FRESH_WORKER), "--runtime", "codex",
             "--batch-manifest", str(manifest), "--slot", slot, str(prompt)],
            cwd=root, env=_env(root, fake), text=True, capture_output=True,
        )
        assert result.returncode == 0, (slot, result.stdout, result.stderr)
        run_rel = next(
            line.split(": ", 1)[1] for line in result.stdout.splitlines()
            if line.startswith("run: ")
        )
        meta = json.loads((root / run_rel / "meta.json").read_text(encoding="utf-8"))
        assert meta["schema_version"] == 2
        assert meta["batch"]["slot"] == slot
        assert meta["batch"]["manifest_sha256"] == hashlib.sha256(
            manifest.read_bytes()).hexdigest()
        assert meta["batch"]["prompt_sha256"] == hashlib.sha256(
            prompt.read_bytes()).hexdigest()


def _verify(root, manifest):
    return subprocess.run(
        [sys.executable, str(WORKER_BATCH), "verify", str(manifest),
         "--runs", str(root / "_private" / "work" / "runs")],
        cwd=root, env=_env(root), text=True, capture_output=True,
    )


def test_normal_ten_slot_batch_passes():
    root, prompts, fake = _fixture()
    try:
        manifest, slots = _create(root, prompts)
        _run_slots(root, manifest, slots, prompts, fake)
        result = _verify(root, manifest)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert result.stdout == "PASS\n"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_one_missing_terminal_is_inconclusive_and_listed():
    root, prompts, fake = _fixture()
    try:
        manifest, slots = _create(root, prompts)
        _run_slots(root, manifest, slots[:-1], prompts[:-1], fake)
        result = _verify(root, manifest)
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert result.stdout == "INCONCLUSIVE_COVERAGE\nmissing: slot-09\n"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_prompt_sha_mismatch_fails():
    root, prompts, fake = _fixture()
    try:
        manifest, slots = _create(root, prompts)
        _run_slots(root, manifest, slots, prompts, fake)
        metas = sorted((root / "_private" / "work" / "runs").glob("*/meta.json"))
        altered = json.loads(metas[4].read_text(encoding="utf-8"))
        altered["batch"]["prompt_sha256"] = "0" * 64
        metas[4].write_text(json.dumps(altered), encoding="utf-8")
        result = _verify(root, manifest)
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert result.stdout == "FAIL\n"
        assert "prompt SHA mismatch" in result.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_normal_ten_slot_batch_passes,
    test_one_missing_terminal_is_inconclusive_and_listed,
    test_prompt_sha_mismatch_fails,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
