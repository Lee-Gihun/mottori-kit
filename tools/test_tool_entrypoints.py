#!/usr/bin/env python3
"""Subprocess smoke/negative pairs for thin or optional distribution entrypoints."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

# Matrix coverage names are intentionally literal for tools/test_matrix_check.py.
COVERED = (
    "tools/ask_codex.sh", "tools/diarize.py",
    "tools/eval_recall.py", "tools/portrait.py", "tools/sync_engine.sh",
    "tools/transcribe.py", "tools/wf_gardener.js",
)


def run(*args, env=None):
    return subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)


def _python_help(path, env=None):
    positive = run(PY, path, "--help", env=env)
    assert positive.returncode == 0, positive.stdout + positive.stderr
    negative = run(PY, path, "--definitely-unknown-option", env=env)
    assert negative.returncode != 0, negative.stdout + negative.stderr


def test_stdlib_cli_help_and_negative_options():
    _python_help("tools/transcribe.py")
    _python_help("tools/eval_recall.py")


def test_diarize_help_and_negative_option():
    _python_help("tools/diarize.py")


def test_diarize_help_works_without_audio_stack():
    """`--help` must not need numpy/scipy/sklearn (CI has none). A fake `numpy` that raises on import
    simulates the missing stack deterministically; the run path must then fail with a clear message."""
    shadow = tempfile.mkdtemp(prefix="no-numpy-")
    try:
        os.makedirs(os.path.join(shadow, "numpy"))
        with open(os.path.join(shadow, "numpy", "__init__.py"), "w", encoding="utf-8") as f:
            f.write("raise ImportError('numpy blocked for the entrypoint test')\n")
        env = dict(os.environ, PYTHONPATH=shadow + os.pathsep + os.environ.get("PYTHONPATH", ""))
        _python_help("tools/diarize.py", env=env)
        blocked = run(PY, "tools/diarize.py", "missing.wav", "--segments", "missing.json", env=env)
        assert blocked.returncode != 0 and "numpy" in (blocked.stdout + blocked.stderr), blocked.stdout + blocked.stderr
    finally:
        shutil.rmtree(shadow, ignore_errors=True)


def test_portrait_normal_and_unknown_command():
    positive = run(PY, "tools/portrait.py", "stale", "--issues")
    assert positive.returncode == 0 and "#issues " in positive.stdout
    negative = run(PY, "tools/portrait.py", "not-a-command")
    assert negative.returncode == 2


def test_ask_codex_has_no_root_thread_lookup():
    """Resume needs an explicit thread id; nothing picks a thread from another project's history."""
    with tempfile.TemporaryDirectory(prefix="ask-codex-resume-") as td:
        prompt = pathlib.Path(td, "prompt.md")
        prompt.write_text("prompt\n", encoding="utf-8")
        marker = pathlib.Path(td, "codex-called")
        fake_bin = pathlib.Path(td, "bin")
        fake_bin.mkdir()
        fake = fake_bin / "codex"
        fake.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        fake.chmod(0o755)
        env = dict(os.environ, HOME=td, PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
        result = run("bash", "tools/ask_codex.sh", str(prompt), "--resume-root", env=env)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "--resume <SID>" in result.stdout and "--resume-root" not in result.stdout
        assert not marker.exists()
        assert not (ROOT / "tools" / "codex_root_thread.py").exists()


def test_ask_codex_logs_a_failed_fresh_run():
    """A failed fresh dispatch leaves FAILED in the log, so it is distinguishable from an interruption."""
    with tempfile.TemporaryDirectory(prefix="ask-codex-fail-") as td:
        root = pathlib.Path(td)
        (root / "tools").mkdir()
        (root / "system" / "debate").mkdir(parents=True)
        shutil.copy(ROOT / "tools" / "ask_codex.sh", root / "tools" / "ask_codex.sh")
        (root / "tools" / "fresh_worker.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
        (root / "p.md").write_text("prompt\n", encoding="utf-8")
        result = subprocess.run(["bash", "tools/ask_codex.sh", "p.md"], cwd=root,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 3, result.stdout + result.stderr
        log = (root / "system" / "debate" / "_dispatch.log").read_text(encoding="utf-8")
        assert "FAILED fresh (exit 3)" in log and "DONE fresh" not in log, log


def test_shell_wrappers_reject_missing_required_input():
    ask = run("bash", "tools/ask_codex.sh", env=dict(os.environ, MOTTORI_LANG="ko"))
    assert ask.returncode != 0 and "프롬프트 파일 없음" in ask.stdout
    ask = run("bash", "tools/ask_codex.sh", env=dict(os.environ, MOTTORI_LANG="en"))
    assert ask.returncode != 0 and "prompt file missing" in ask.stdout
    if not (ROOT / "tools" / "sync_engine.sh").is_file():
        print("- sync_engine wrapper: not applicable here (kit-side tool)")
        return
    sync = run("bash", "tools/sync_engine.sh")
    assert sync.returncode != 0 and "instance path" in sync.stderr


def test_wf_gardener_syntax_positive_and_negative():
    node = shutil.which("node")
    if node is None:
        source = (ROOT / "tools" / "wf_gardener.js").read_text(encoding="utf-8")
        assert "memory-gardener" in source and "REPORT_SCHEMA" in source
        return
    # The workflow runtime strips the meta export and runs the body inside an async function, so
    # top-level return and await are valid there. Check the syntax in that shape; a bare
    # `node --check` rejects the top-level return on newer Node versions.
    source = (ROOT / "tools" / "wf_gardener.js").read_text(encoding="utf-8")
    assert source.startswith("export const meta"), "workflow script must begin with the meta export"
    wrapped = "(async function () {\n" + source.replace("export const meta", "const meta", 1) + "\n})\n"
    paths = []
    try:
        for text in (wrapped, wrapped.replace("const meta", "let x = ;\nconst meta", 1)):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                f.write(text)
                paths.append(f.name)
        positive = run(node, "--check", paths[0])
        assert positive.returncode == 0, positive.stdout + positive.stderr
        negative = run(node, "--check", paths[1])
        assert negative.returncode != 0
    finally:
        for path in paths:
            os.unlink(path)


TESTS = (
    test_stdlib_cli_help_and_negative_options,
    test_diarize_help_and_negative_option,
    test_diarize_help_works_without_audio_stack,
    test_portrait_normal_and_unknown_command,
    test_ask_codex_has_no_root_thread_lookup,
    test_ask_codex_logs_a_failed_fresh_run,
    test_shell_wrappers_reject_missing_required_input,
    test_wf_gardener_syntax_positive_and_negative,
)


def main():
    failed = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"tool entrypoints: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
