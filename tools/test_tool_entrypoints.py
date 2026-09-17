#!/usr/bin/env python3
"""Subprocess smoke/negative pairs for thin or optional distribution entrypoints."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

# Matrix coverage names are intentionally literal for tools/test_matrix_check.py.
COVERED = (
    "tools/ask_codex.sh", "tools/codex_root_thread.py", "tools/diarize.py",
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


def test_codex_root_thread_handles_malformed_corpus():
    with tempfile.TemporaryDirectory(prefix="codex-root-thread-") as td:
        session = pathlib.Path(td, ".codex", "sessions", "bad.jsonl")
        session.parent.mkdir(parents=True)
        session.write_text("not json\n", encoding="utf-8")
        env = dict(os.environ, HOME=td, PYTHONDONTWRITEBYTECODE="1")
        result = run(PY, "tools/codex_root_thread.py", env=env)
        assert result.returncode == 0 and result.stdout == "\n"


def test_shell_wrappers_reject_missing_required_input():
    ask = run("bash", "tools/ask_codex.sh")
    assert ask.returncode != 0 and "프롬프트 파일 없음" in ask.stdout
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
    positive = run(node, "--check", "tools/wf_gardener.js")
    assert positive.returncode == 0, positive.stdout + positive.stderr
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write("let x = ;\n" +
                (ROOT / "tools" / "wf_gardener.js").read_text(encoding="utf-8"))
        bad = f.name
    try:
        negative = run(node, "--check", bad)
        assert negative.returncode != 0
    finally:
        os.unlink(bad)


TESTS = (
    test_stdlib_cli_help_and_negative_options,
    test_diarize_help_and_negative_option,
    test_diarize_help_works_without_audio_stack,
    test_portrait_normal_and_unknown_command,
    test_codex_root_thread_handles_malformed_corpus,
    test_shell_wrappers_reject_missing_required_input,
    test_wf_gardener_syntax_positive_and_negative,
)


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"tool entrypoints: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
