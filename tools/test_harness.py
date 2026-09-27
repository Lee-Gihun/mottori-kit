#!/usr/bin/env python3
"""Harness wiring tests: the data border, adapter parity, and canary honesty.

The rule this file exists for: a generated injection file can carry the local private overlay,
so it must be outside Git or it must carry public state only.  Nothing here calls a model.
"""

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from testlib import run_test


ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "harness.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("harness", str(TOOL))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_runtime_declares_the_roles_it_cannot_take():
    """A new harness may cover one role, but it may not hide the five it drops."""
    harness = load_tool()
    for name, spec in harness.RUNTIMES.items():
        assert set(spec["roles"]) <= set(harness.ROLES), f"{name}: unknown role"
        assert spec["mode"] in ("checked-in", "generated"), f"{name}: unknown mode"
        assert spec["wiring"], f"{name}: no wiring path declared"
        if set(harness.ROLES) - set(spec["roles"]):
            assert spec["gap_note"].strip(), f"{name}: gaps without a note"


def test_command_adapter_embeds_the_canonical_body_verbatim():
    """The slash command has one source of truth; the adapter may only wrap it."""
    harness = load_tool()
    body = "# NOW\n\n본문 한 줄.\n"
    rendered = harness.render_command("now", body)
    assert rendered.startswith("---\ndescription: ")
    assert harness.GENERATED in rendered
    assert rendered.endswith(body), "canonical body must survive byte-exact"


def test_state_falls_back_to_public_when_the_path_is_not_outside_git():
    """fail-close: if we cannot prove the file is ignored, the private overlay is dropped."""
    harness = load_tool()
    seen = {}

    def fake_render(public_only=False):
        seen["public_only"] = public_only
        return "state\n"

    harness.render_state = fake_render
    harness.git_ignored = lambda _rel: False
    harness.opencode_artifacts(public_only=not harness.git_ignored(harness.OPENCODE_STATE))
    assert seen["public_only"] is True

    harness.git_ignored = lambda _rel: True
    harness.opencode_artifacts(public_only=not harness.git_ignored(harness.OPENCODE_STATE))
    assert seen["public_only"] is False


def test_ignore_line_is_written_once():
    harness = load_tool()
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / ".gitignore").write_text("_private/\n", encoding="utf-8")
        harness.ROOT = root
        harness.git_ignored = lambda _rel: False
        assert harness.ensure_ignore_line() is True
        first = (root / ".gitignore").read_text(encoding="utf-8")
        assert harness.ensure_ignore_line() is False, "second call must not append again"
        assert (root / ".gitignore").read_text(encoding="utf-8") == first
        assert first.count(harness.OPENCODE_GITIGNORE_LINE) == 1
        assert first.startswith("_private/\n"), "existing rules must survive"


def test_canary_prompt_never_carries_the_nonce():
    """The nonce must reach the model only through injection, never through the question.

    Otherwise a harness with no injection at all still passes by echoing the prompt.
    """
    source = TOOL.read_text(encoding="utf-8")
    prompt_start = source.index('"Print only the value')
    prompt = source[prompt_start:source.index('"]', prompt_start)]
    assert "nonce" not in prompt, "the prompt must not interpolate the nonce"
    assert "HOOK_CANARY" in prompt, "the prompt must point at the injected marker"
    assert "ABSENT" in prompt, "a missing marker must have a distinct answer"


class _Proc:
    def __init__(self, stdout):
        self.stdout = stdout


def _canary_sandbox(harness, root, answer):
    """Point canary_once at a temp instance with a fake model. Nothing is called for real.

    The fake state renderer embeds the nonce exactly as now.py does (from MOTTORI_HOOK_CANARY),
    and `answer(nonce, state_text)` plays the model, seeing the state file as it is on disk mid-run.
    """
    harness.ROOT = root
    harness.git_ignored = lambda _rel: True

    def fake_render(public_only=False):
        nonce = os.environ.get("MOTTORI_HOOK_CANARY")
        return "state\n" + (f"HOOK_CANARY:{nonce}\n" if nonce else "")

    def fake_run(cmd, **kw):
        nonce = os.environ.get("MOTTORI_HOOK_CANARY", "")
        return answer(nonce, (root / harness.OPENCODE_STATE).read_text(encoding="utf-8"))

    harness.render_state = fake_render
    harness._run = fake_run


def test_a_tool_using_run_is_never_counted_as_proof():
    """The nonce sits in a file, so a model with grep could answer without any injection.

    opencode v2.0.11 `run` has no flag that turns tools off, so the canary cannot forbid them.
    It refuses to count them instead: the same correct answer is PASS without a tool call and
    INCONCLUSIVE with one.
    """
    harness = load_tool()
    stream = "\n".join([
        json.dumps({"type": "tool_use", "part": {"tool": "grep"}}),
        json.dumps({"type": "text", "part": {"text": "KIT-NONCE"}}),
    ])
    text, tools, errors = harness.read_stream(stream)
    assert "KIT-NONCE" in text and tools == ["grep"] and errors == []

    def answer_with(tool_events):
        def answer(nonce, _state):
            events = [{"type": "tool_use", "part": {"tool": t}} for t in tool_events]
            events.append({"type": "text", "part": {"text": nonce}})
            return _Proc("\n".join(json.dumps(e) for e in events))
        return answer

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        _canary_sandbox(harness, root, answer_with([]))
        assert harness.canary_once("opencode", "prov/m", 5)[0] == "pass", "control: a clean answer passes"
        _canary_sandbox(harness, root, answer_with(["grep"]))
        verdict, detail = harness.canary_once("opencode", "prov/m", 5)
    assert verdict == "inconclusive", "a correct answer after a tool call must not count as proof"
    assert "grep" in detail


def test_state_file_holds_no_nonce_after_a_canary_run():
    """The nonce is on disk in the injection file only while the run lasts.

    The file is the channel being measured, so it must carry the nonce during the run. Afterwards
    (answer, timeout, or crash) the finally branch rewrites it without the nonce, and the
    environment variable is gone too, so the next session or the next canary cannot find it.
    """
    harness = load_tool()
    seen = {}

    def answer(nonce, state):
        seen["during"] = nonce and nonce in state
        seen["nonce"] = nonce
        return _Proc(json.dumps({"type": "text", "part": {"text": nonce}}))

    def timeout(nonce, state):
        seen["timeout_nonce"] = nonce
        raise subprocess.TimeoutExpired(cmd="opencode", timeout=5)

    def crash(nonce, state):
        seen["crash_nonce"] = nonce
        raise OSError("binary vanished")

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        state_path = root / harness.OPENCODE_STATE

        _canary_sandbox(harness, root, answer)
        assert harness.canary_once("opencode", "prov/m", 5)[0] == "pass"
        assert seen["during"], "the run must actually see the nonce in the file (else this test proves nothing)"
        after = state_path.read_text(encoding="utf-8")
        assert seen["nonce"] not in after and "HOOK_CANARY" not in after

        _canary_sandbox(harness, root, timeout)
        assert harness.canary_once("opencode", "prov/m", 5)[0] == "timeout"
        assert seen["timeout_nonce"] not in state_path.read_text(encoding="utf-8")

        _canary_sandbox(harness, root, crash)
        try:
            harness.canary_once("opencode", "prov/m", 5)
        except OSError:
            pass
        else:
            raise AssertionError("the crash must propagate, not be read as a verdict")
        assert seen["crash_nonce"] not in state_path.read_text(encoding="utf-8")
    assert "MOTTORI_HOOK_CANARY" not in os.environ, "the nonce must not outlive the run in the environment"


def _status_output(harness):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert harness.cmd_status(None) == 0
    return out.getvalue()


def _opencode_line(output):
    return next(line for line in output.splitlines() if " opencode " in line)


def test_status_does_not_call_a_half_wired_opencode_wired():
    """The state file alone is not wiring: the slash commands must exist and match their source."""
    harness = load_tool()
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        commands = root / ".claude" / "commands"
        commands.mkdir(parents=True)
        for name in harness.COMMANDS:
            (commands / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
        harness.ROOT = root
        harness.git_ignored = lambda _rel: True
        harness.which = lambda _binary: "/usr/local/bin/fake"
        harness.render_state = lambda public_only=False: "state\n"

        (root / harness.OPENCODE_STATE).write_text("state\n", encoding="utf-8")
        output = _status_output(harness)
        line = _opencode_line(output)
        assert "배선됨" not in line and "반쪽 배선" in line, line
        assert f"MISSING {harness.OPENCODE_COMMAND_DIR}" in output

        for path, content in harness.opencode_command_artifacts():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        assert "배선됨" in _opencode_line(_status_output(harness))

        (commands / "now.md").write_text("# now, edited at the source\n", encoding="utf-8")
        output = _status_output(harness)
        assert "배선 낡음" in _opencode_line(output), "a stale adapter must not read as wired"
        assert "STALE   .opencode/command/now.md" in output
        check_out = io.StringIO()
        with contextlib.redirect_stdout(check_out):
            assert harness.cmd_check(None) == 1, "check and status must agree on the same parity"



def test_canary_ledger_never_stores_the_nonce():
    """The ledger is a verdict record. A nonce on disk would make the next run greppable."""
    harness = load_tool()
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "harness-canary.json"
        harness.persist_canary({"prov/model-a": ("pass", "도구 사용 0")}, path)
        harness.persist_canary({"prov/model-b": ("inconclusive", "도구 사용: grep")}, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert set(payload["models"]) == {"prov/model-a", "prov/model-b"}, "a second run must not erase the first"
    assert payload["models"]["prov/model-a"]["verdict"] == "pass"
    assert "KIT-" not in path.name and "KIT-" not in json.dumps(payload), "no nonce may reach the ledger"


def test_model_list_takes_only_provider_qualified_names():
    harness = load_tool()
    harness._run = lambda cmd, **kw: type("P", (), {"stdout": "opencode/muse-spark-1.3\nnoise line\n\nzhipu/glm-5\n"})()
    assert harness.available_models("opencode") == ["opencode/muse-spark-1.3", "zhipu/glm-5"]


def test_stream_reader_separates_text_tools_and_errors():
    harness = load_tool()
    stream = "\n".join([
        json.dumps({"type": "step_start", "part": {"text": "KIT-NOISE"}}),
        "not json",
        json.dumps({"type": "error", "error": {"message": "free tier"}}),
        json.dumps({"type": "text", "part": {"text": "KIT-ANSWER"}}),
    ])
    text, tools, errors = harness.read_stream(stream)
    assert "KIT-ANSWER" in text
    assert "KIT-NOISE" not in text, "non-text events must not be read as an answer"
    assert tools == [] and errors == ["free tier"]


def test_cli_status_runs_without_an_instance_config():
    """status is the first thing a new user runs; it must not need setup to have happened."""
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run([sys.executable, str(TOOL), "status"],
                              capture_output=True, text=True, cwd=tmp,
                              env={"PATH": "/usr/bin:/bin", "MOTTORI_INSTANCE": tmp,
                                   "PYTHONDONTWRITEBYTECODE": "1", "HOME": tmp})
        assert proc.returncode == 0, proc.stderr
        for name in ("claude", "codex", "opencode"):
            assert name in proc.stdout


TESTS = [
    test_every_runtime_declares_the_roles_it_cannot_take,
    test_command_adapter_embeds_the_canonical_body_verbatim,
    test_state_falls_back_to_public_when_the_path_is_not_outside_git,
    test_ignore_line_is_written_once,
    test_canary_prompt_never_carries_the_nonce,
    test_a_tool_using_run_is_never_counted_as_proof,
    test_state_file_holds_no_nonce_after_a_canary_run,
    test_status_does_not_call_a_half_wired_opencode_wired,
    test_canary_ledger_never_stores_the_nonce,
    test_model_list_takes_only_provider_qualified_names,
    test_stream_reader_separates_text_tools_and_errors,
    test_cli_status_runs_without_an_instance_config,
]


def main():
    passed = 0
    for test in TESTS:
        run_test(test, __file__)
        print(f"✓ {test.__name__}")
        passed += 1
    print(f"harness: {passed}/{len(TESTS)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
