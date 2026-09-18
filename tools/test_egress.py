#!/usr/bin/env python3
"""Behavior tests for model-send egress policy and fresh-worker auditing."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = Path(__file__).resolve().parent
WORKER = HERE / "fresh_worker.py"


def _config(root, deny=("_private/",), allow=(), include_egress=True):
    data = {
        "schema_version": 4,
        "journal_visibility": {"legacy_cutoff": None, "legacy_public_tracks": []},
    }
    if include_egress:
        data["egress"] = {
            "model_send": {
                "deny_prefixes": list(deny),
                "allow_prefixes": list(allow),
            }
        }
    (root / "system").mkdir(parents=True, exist_ok=True)
    (root / "system" / "memory-config.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _script(path, body):
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run(root, prompt, binary, strict=False):
    env = dict(
        os.environ,
        MOTTORI_INSTANCE=str(root),
        MOTTORI_FRESH_WORKER_CODEX_BIN=str(binary),
    )
    argv = [sys.executable, str(WORKER), "--runtime", "codex"]
    if strict:
        argv.append("--strict-egress")
    argv.append(str(prompt))
    return subprocess.run(argv, cwd=root, env=env, text=True, capture_output=True)


def _run_dir(root, receipt):
    run_line = next(line for line in receipt.splitlines() if line.startswith("run: "))
    return root / run_line.split(": ", 1)[1]


def _read_memlib(root, expression):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root), PYTHONPATH=str(HERE))
    result = subprocess.run(
        [sys.executable, "-c", f"import json, memlib as M; print(json.dumps({expression}))"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _doctor_egress(root):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root), PYTHONPATH=str(HERE))
    result = subprocess.run(
        [sys.executable, "-c", "import json, doctor; print(json.dumps(doctor.c_egress()))"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_optional_config_uses_private_default_without_schema_bump():
    root = Path(tempfile.mkdtemp(prefix="egress-default-"))
    try:
        _config(root, include_egress=False)
        assert _read_memlib(root, "M.CONFIG_SCHEMA") == 4
        assert _read_memlib(root, "M.EGRESS_MODEL_SEND") == {
            "deny_prefixes": ["_private/"],
            "allow_prefixes": [],
        }
        assert _doctor_egress(root)[0] == "PASS"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_fails_an_explicit_empty_deny_list():
    root = Path(tempfile.mkdtemp(prefix="egress-doctor-"))
    try:
        _config(root, deny=())
        status, detail = _doctor_egress(root)
        assert status == "FAIL"
        assert "deny_prefixes" in detail
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_parser_rejects_malformed_egress_prefixes():
    root = Path(tempfile.mkdtemp(prefix="egress-parser-"))
    try:
        _config(root, deny=("../outside/",))
        loaded, policy = _read_memlib(
            root, "[M.CONFIG_LOAD_OK, M.EGRESS_MODEL_SEND]"
        )
        assert loaded is False
        assert policy == {"deny_prefixes": ["_private/"], "allow_prefixes": []}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_N5_allow_prefix_must_be_strictly_below_every_overlapping_deny():
    cases = (
        (("_private/",), ("_private/",)),
        (("_private/share/secret/",), ("_private/share/",)),
        (("_private/",), ("public/",)),
        (("_private/", "_private/share/secret/"), ("_private/share/",)),
    )
    for deny, allow in cases:
        root = Path(tempfile.mkdtemp(prefix="egress-overlap-"))
        try:
            _config(root, deny=deny, allow=allow)
            loaded, policy = _read_memlib(root, "[M.CONFIG_LOAD_OK, M.EGRESS_MODEL_SEND]")
            assert loaded is False
            assert policy == {"deny_prefixes": ["_private/"], "allow_prefixes": []}
            status, detail = _doctor_egress(root)
            assert status == "FAIL" and "allow_prefixes" in detail
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_N5_invalid_overlap_stops_fresh_worker_before_runtime():
    root = Path(tempfile.mkdtemp(prefix="egress-overlap-worker-"))
    try:
        _config(root, deny=("_private/",), allow=("_private/",))
        prompt = root / "prompt.md"
        prompt.write_text("Public prompt.\n", encoding="utf-8")
        marker = root / "runtime-started"
        fake = root / "fake codex"
        _script(fake, f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n")
        result = _run(root, prompt, fake)
        assert result.returncode == 2
        assert "allow_prefixes" in result.stderr
        assert not marker.exists()
        assert not (root / "_private" / "work" / "runs").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_default_path_refuses_deny_ref_before_runtime_or_run_record():
    root = Path(tempfile.mkdtemp(prefix="egress-positive-"))
    try:
        _config(root, deny=("_private/", "people/alice/"))
        private = root / "_private" / "source" / "secret.txt"
        private.parent.mkdir(parents=True)
        private.write_text("private fixture\n", encoding="utf-8")
        prompt = root / "prompt.md"
        prompt.write_text(
            "Read `_private/source/secret.txt`; the absolute spelling is "
            + str(private)
            + "; do not send personal identifier path people/alice/profile.md\n",
            encoding="utf-8",
        )
        marker = root / "runtime-started"
        fake = root / "fake codex"
        _script(
            fake,
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('runtime received prompt')\n",
        )
        result = _run(root, prompt, fake)
        assert result.returncode == 2
        assert "model-send deny ref" in result.stderr
        assert "_private/source/secret.txt" in result.stderr
        assert "people/alice/profile.md" in result.stderr
        assert not marker.exists(), "the fake runtime must never receive argv or prompt bytes"
        assert not (root / "_private" / "work" / "runs").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_strict_egress_refuses_before_runtime_or_run_record():
    root = Path(tempfile.mkdtemp(prefix="egress-strict-"))
    try:
        _config(root)
        prompt = root / "_private" / "prompts" / "secret.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("No path reference in this body.\n", encoding="utf-8")
        marker = root / "runtime-started"
        fake = root / "fake codex"
        _script(fake, f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n")
        result = _run(root, prompt, fake)
        assert result.returncode == 2
        assert "model-send deny ref" in result.stderr and "_private/prompts/secret.md" in result.stderr
        assert not marker.exists()
        assert not (root / "_private" / "work" / "runs").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_public_reference_is_negative_and_allow_prefix_overrides_deny():
    root = Path(tempfile.mkdtemp(prefix="egress-negative-"))
    try:
        _config(root, allow=("_private/shareable/",))
        prompt = root / "prompt.md"
        prompt.write_text(
            "Read docs/public.md and _private/shareable/example.md\n", encoding="utf-8"
        )
        fake = root / "fake codex"
        _script(
            fake,
            """
import pathlib, sys
args = sys.argv[1:]
pathlib.Path(args[args.index("--output-last-message") + 1]).write_text("OK\\n")
print('{"type":"turn.completed"}')
""",
        )
        result = _run(root, prompt, fake, strict=True)
        assert result.returncode == 0, result.stderr
        assert "egress: 0 private refs" in result.stdout
        run = _run_dir(root, result.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert meta["egress"]["private_refs"] == []
        assert not (run / "egress.log").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_optional_config_uses_private_default_without_schema_bump,
    test_doctor_fails_an_explicit_empty_deny_list,
    test_parser_rejects_malformed_egress_prefixes,
    test_N5_allow_prefix_must_be_strictly_below_every_overlapping_deny,
    test_N5_invalid_overlap_stops_fresh_worker_before_runtime,
    test_default_path_refuses_deny_ref_before_runtime_or_run_record,
    test_strict_egress_refuses_before_runtime_or_run_record,
    test_public_reference_is_negative_and_allow_prefix_overrides_deny,
]


if __name__ == "__main__":
    for test in TESTS:
        run_test(test, __file__)
        print("PASS", test.__name__)
