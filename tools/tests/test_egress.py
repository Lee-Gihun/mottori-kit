#!/usr/bin/env python3
"""Behavior tests for the model-send egress policy and what the fresh worker refuses under it."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent.parent
WORKER = HERE / "fresh_worker.py"


def _config(root, deny=("_private/",), allow=(), include_egress=True):
    data = {
        "schema_version": 4,
        "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                               "legacy_public_tracks": []},
    }
    if include_egress:
        data["egress"] = {
            "model_send": {
                "deny_prefixes": list(deny),
                "allow_prefixes": list(allow),
            }
        }
    (root / "instance").mkdir(parents=True, exist_ok=True)
    (root / "instance" / "config.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _script(path, body):
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run(root, prompt, binary):
    env = dict(
        os.environ,
        MOTTORI_INSTANCE=str(root),
        MOTTORI_FRESH_WORKER_CODEX_BIN=str(binary),
    )
    argv = [sys.executable, str(WORKER), "--runtime", "codex", str(prompt)]
    return subprocess.run(argv, cwd=root, env=env, text=True, capture_output=True)


def _run_dir(root, receipt):
    run_line = next(line for line in receipt.splitlines() if line.startswith("run: "))
    return root / run_line.split(": ", 1)[1]


def _read_config(root, expression):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root), PYTHONPATH=str(HERE / "lib"))
    result = subprocess.run(
        [sys.executable, "-c", f"import json, config as C; print(json.dumps({expression}))"],
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
        assert _read_config(root, "C.schema()") == 4
        assert _read_config(root, "C.egress_model_send()") == {
            "deny_prefixes": ["_private/"],
            "allow_prefixes": [],
        }
        assert _doctor_egress(root)[0] == "PASS"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_doctor_accepts_an_explicit_empty_deny_list():
    """An empty list is the owner's choice: a copy still leaves out _private/ (KIT-DR-083)."""
    root = Path(tempfile.mkdtemp(prefix="egress-doctor-"))
    try:
        _config(root, deny=())
        status, detail = _doctor_egress(root)
        assert status == "PASS" and "deny=0" in detail, (status, detail)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_parser_rejects_malformed_egress_prefixes():
    root = Path(tempfile.mkdtemp(prefix="egress-parser-"))
    try:
        _config(root, deny=("../outside/",))
        loaded, policy = _read_config(
            root, "[C.load_ok(), C.egress_model_send()]"
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
            loaded, policy = _read_config(root, "[C.load_ok(), C.egress_model_send()]")
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


def test_a_prompt_that_names_a_denied_path_is_run_because_its_words_are_not_judged():
    """A worker in the instance can open the denied paths, so refusing their names would stop
    nothing. A prohibition that spells the path is the plainest case."""
    root = Path(tempfile.mkdtemp(prefix="egress-words-"))
    try:
        _config(root, deny=("_private/", "people/alice/"))
        private = root / "_private" / "source" / "secret.txt"
        private.parent.mkdir(parents=True)
        private.write_text("private fixture\n", encoding="utf-8")
        marker = root / "runtime-started"
        fake = root / "fake codex"
        _script(fake, f"from pathlib import Path\nPath({str(marker)!r}).write_text('started')\n")
        for body in ("Read `_private/source/secret.txt`; the absolute spelling is " + str(private)
                     + "; see also people/alice/profile.md\n",
                     "Review tools/now.py. Do not open _private/ or anything under it.\n"):
            marker.unlink(missing_ok=True)
            prompt = root / "prompt.md"
            prompt.write_text(body, encoding="utf-8")
            result = _run(root, prompt, fake)
            assert marker.exists(), result.stdout + result.stderr
            assert result.returncode != 2 and "private path" not in result.stderr, result.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_prompt_file_under_a_denied_path_is_refused_for_a_copy_and_run_in_the_instance():
    root = Path(tempfile.mkdtemp(prefix="egress-prompt-file-"))
    try:
        _config(root)
        prompt = root / "_private" / "prompts" / "secret.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("No path reference in this body.\n", encoding="utf-8")
        marker = root / "runtime-started"
        fake = root / "fake codex"
        _script(fake, f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n")
        # In the instance the worker can open the file itself.
        result = _run(root, prompt, fake)
        assert marker.exists() and result.returncode != 2, result.stdout + result.stderr
        # A copy leaves the denied paths out, so it is not handed a file from one either.
        marker.unlink()
        shutil.rmtree(root / "_private" / "work")
        config = json.loads((root / "instance" / "config.json").read_text(encoding="utf-8"))
        config["workers"] = {"codex": {"where": "copy"}}
        (root / "instance" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        result = _run(root, prompt, fake)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "the prompt file is under a path the model-send policy denies (_private/prompts/secret.md)" \
            in result.stderr, result.stderr
        assert not marker.exists(), "the fake runtime must never receive argv or prompt bytes"
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
        result = _run(root, prompt, fake)
        assert result.returncode == 0, result.stderr
        # The run record carries no egress fields: the policy acts by where the worker runs.
        assert "egress" not in result.stdout
        run = _run_dir(root, result.stdout)
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        assert "egress" not in meta
        assert not (run / "egress.log").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_optional_config_uses_private_default_without_schema_bump,
    test_doctor_accepts_an_explicit_empty_deny_list,
    test_parser_rejects_malformed_egress_prefixes,
    test_N5_allow_prefix_must_be_strictly_below_every_overlapping_deny,
    test_N5_invalid_overlap_stops_fresh_worker_before_runtime,
    test_a_prompt_that_names_a_denied_path_is_run_because_its_words_are_not_judged,
    test_a_prompt_file_under_a_denied_path_is_refused_for_a_copy_and_run_in_the_instance,
    test_public_reference_is_negative_and_allow_prefix_overrides_deny,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
