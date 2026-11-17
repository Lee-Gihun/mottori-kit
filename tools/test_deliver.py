#!/usr/bin/env python3
"""Regression tests for the pre-delivery check: each signal fires on its case and stays quiet otherwise."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from testlib import run_test  # noqa: E402

FAILED = []
BLOCK_UNOPENED = {"block": ["unopened"]}
BLOCK_ALL = {"block": ["unopened", "reader"]}
BODY = "x" * 2000


def check(name, condition, detail=""):
    print(("✓ " if condition else "✗ ") + name + ("" if condition else f"  {detail}"))
    if not condition:
        FAILED.append(name)


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def use(name, **data):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": name, "input": data}]}}


def instance():
    """Create a minimal instance root so state files land in a scratch directory."""
    root = tempfile.mkdtemp(prefix="deliver-test-")
    os.makedirs(os.path.join(root, "system"))
    os.makedirs(os.path.join(root, "state"))
    return root


def run_hook(root, rows, message, active=False, config=BLOCK_UNOPENED, lang="en"):
    transcript = os.path.join(root, "transcript.jsonl")
    with open(transcript, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    if config is not None:
        with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
            json.dump({"deliver": config}, f)
    payload = {"session_id": "s1", "transcript_path": transcript, "stop_hook_active": active,
               "last_assistant_message": message}
    env = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_LANG=lang)
    result = subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "hook"],
                            input=json.dumps(payload), capture_output=True, text=True, env=env)
    return result.returncode, (json.loads(result.stdout) if result.stdout.strip() else None), result.stderr


def log_rows(root):
    path = os.path.join(root, "state", ".deliver.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def written_and_sent(path="/x/report.md", body=BODY):
    return [user("Write the report on why the deploy failed."), use("Write", file_path=path, content=body),
            tool_result(), use("SendUserFile", files=[path])]


def test_quiet_turn_passes():
    root = instance()
    code, out, _err = run_hook(root, [user("Rename this function."), use("Edit", file_path="/x/a.py"),
                                      tool_result(), use("Bash", command="python3 a.py")],
                               "Renamed it and ran the script; the output is the same.")
    check("a short answer with no delivered document passes", code == 0 and out is None, repr(out))
    check("a passing turn writes no log", not log_rows(root))


def test_unopened_document_blocks_once_and_quotes_request():
    root = instance()
    rows = written_and_sent()
    code, out, _err = run_hook(root, rows, "I sent the report.")
    check("a document delivered without being reopened blocks", code == 0 and out and out.get("decision") == "block",
          repr(out))
    check("the reason names the file and quotes the owner's request",
          out and "report.md" in out["reason"] and "why the deploy failed" in out["reason"], repr(out))
    code, out, _err = run_hook(root, rows, "I reread the report, fixed the summary, and sent it again.", active=True)
    check("the second Stop call in the same turn passes", code == 0 and out is None, repr(out))
    log = log_rows(root)
    check("the log records the block and that the answer changed afterwards",
          [r["event"] for r in log] == ["block", "after"] and log[1]["changed"] is True, repr(log))


def test_unopened_document_exceptions():
    rows = [user("Write the report."), use("Write", file_path="/x/report.md", content=BODY), tool_result(),
            use("Read", file_path="/x/report.md"), tool_result(), use("SendUserFile", files=["/x/report.md"])]
    code, out, _err = run_hook(instance(), rows, "I reread the report and sent it.")
    check("a document reopened before delivery passes", out is None, repr(out))
    rows = [user("Leave a note."), use("Write", file_path="/x/note.md", content="short note"), tool_result()]
    code, out, _err = run_hook(instance(), rows, "Written to note.md.")
    check("a short document is not checked", out is None, repr(out))
    rows = [user("Fix it."), use("Write", file_path="/x/tool.py", content=BODY), tool_result()]
    code, out, _err = run_hook(instance(), rows, "Fixed tool.py.")
    check("a source file is not a reading document", out is None, repr(out))
    rows = [user("Draft it."), use("Write", file_path="/x/draft.md", content=BODY), tool_result()]
    code, out, _err = run_hook(instance(), rows, "The draft is saved; I will reread it next.")
    check("a document that is written but not delivered passes", out is None, repr(out))
    rows = [user("Write the report."), use("Write", file_path="/x/report.md", content=BODY), tool_result()]
    code, out, _err = run_hook(instance(), rows, "The report is in report.md.")
    check("naming the file in the answer counts as delivering it", out and "report.md" in out["reason"], repr(out))


def test_configured_delivery_tools():
    rows = [user("Write the report."), use("Write", file_path="/x/report.md", content=BODY), tool_result(),
            use("mcp__docs__update", ref={"id": "n1"}, payload="report.md")]
    config = {"block": ["unopened"], "send_tools": ["SendUserFile", "mcp__docs__*"]}
    code, out, _err = run_hook(instance(), rows, "I put it in the shared document.", config=config)
    check("a configured connector tool counts as delivery, so an unread document blocks",
          out and out.get("decision") == "block" and "report.md" in out["reason"], repr(out))
    code, out, _err = run_hook(instance(), rows, "I put it in the shared document.")
    check("the same call counts as reopening the file when the tool is not a delivery tool", out is None, repr(out))


def test_default_only_records():
    root = instance()
    code, out, _err = run_hook(root, written_and_sent(), "I sent the report.", config=None)
    check("with no config a fired signal does not block", code == 0 and out is None, repr(out))
    log = log_rows(root)
    check("the fired signal is recorded as observed",
          len(log) == 1 and log[0]["event"] == "observe" and log[0]["signals"] == ["unopened"], repr(log))
    root = instance()
    code, out, _err = run_hook(root, written_and_sent(), "I sent the report.",
                               config={"block": ["reader"], "observe": ["unopened"]})
    check("an observed signal never blocks even when another signal is set to block", out is None, repr(out))


def test_reader_signal():
    long_report = "The work is done and the result is as follows. " * 40
    rows = [user("Look into it.")] + [use("Bash", command=f"echo {i}") for i in range(9)]
    root = instance()
    code, out, _err = run_hook(root, rows, long_report, config=None)
    check("the long-report signal is neither blocked nor recorded unless configured",
          out is None and not log_rows(root), repr(out))
    code, out, _err = run_hook(instance(), rows, long_report, config=BLOCK_ALL)
    check("the long-report signal blocks when configured", out and "recipient" in out["reason"], repr(out))
    code, out, _err = run_hook(instance(), rows[:4], long_report, config=BLOCK_ALL)
    check("a long answer after little work passes", out is None, repr(out))
    code, out, _err = run_hook(instance(), rows, "Done. There are three results.", config=BLOCK_ALL)
    check("a short answer after long work passes", out is None, repr(out))
    fenced = "Summary first.\n```\n" + ("log line\n" * 400) + "```\nThat is all."
    code, out, _err = run_hook(instance(), rows, fenced, config=BLOCK_ALL)
    check("fenced output does not count toward the report length", out is None, repr(out))


def test_korean_reason():
    code, out, _err = run_hook(instance(), written_and_sent(), "보고서를 보냈어.", lang="ko")
    check("the reason follows the instance language", out and "내놓기 전 점검" in out["reason"], repr(out))


def test_broken_input_never_blocks():
    root = instance()
    env = dict(os.environ, MOTTORI_INSTANCE=root)
    result = subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "hook"],
                            input="{not json", capture_output=True, text=True, env=env)
    check("malformed hook input exits zero without blocking", result.returncode == 0 and not result.stdout.strip())
    check("the failure is reported on stderr and in the hook error log",
          "deliver hook failed" in result.stderr
          and os.path.exists(os.path.join(root, "state", ".hook-errors.log")), result.stderr)
    payload = {"session_id": "s", "transcript_path": "/nonexistent/t.jsonl", "last_assistant_message": "All done."}
    result = subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "hook"],
                            input=json.dumps(payload), capture_output=True, text=True, env=env)
    check("a missing transcript passes", result.returncode == 0 and not result.stdout.strip())
    with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    code, out, _err = run_hook(root, written_and_sent(), "I sent the report.", config=None)
    check("a broken config falls back to recording only", code == 0 and out is None, repr(out))


def test_stats_counts_blocks_and_changes():
    root = instance()
    run_hook(root, written_and_sent(), "I sent the report.")
    run_hook(root, written_and_sent(), "I sent the report.", active=True)
    env = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_LANG="en")
    result = subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "stats"],
                            capture_output=True, text=True, env=env)
    check("stats reports one block that did not change the answer",
          "blocked 1 turns" in result.stdout and "changed in 0" in result.stdout, result.stdout)


def stats_text(root):
    env = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_LANG="en")
    return subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "stats"],
                          capture_output=True, text=True, env=env).stdout


def test_stats_links_a_reentry_only_to_its_own_blocked_turn():
    root = instance()
    rows = written_and_sent()
    run_hook(root, rows, "I sent the report.")
    run_hook(root, rows, "I reread it and fixed the summary.", active=True)
    # The same turn coming back again after another Stop hook blocked it is not a second effect.
    run_hook(root, rows, "Another hook asked me to fix a link; fixed.", active=True)
    # A later request in the same session, re-entered after some other Stop hook blocked it.
    later = rows + [use("Bash", command="true"), user("Now explain the other issue.")]
    run_hook(root, later, "Unrelated answer.", active=True)
    out = stats_text(root)
    check("a block is followed up once, by its own turn only",
          "blocked 1 turns; 1 were seen again, and the answer changed in 1" in out, out)
    check("the per-signal row agrees", "blocked 1 · seen again 1 · changed 1" in out, out)
    events = [r["event"] for r in log_rows(root)]
    check("re-entries of other turns write nothing", events == ["block", "after"], repr(events))
    # The same request typed again later in the session is a different turn.
    again = later + [user("Write the report on why the deploy failed."),
                     use("Write", file_path="/x/report.md", content=BODY), tool_result(),
                     use("SendUserFile", files=["/x/report.md"])]
    run_hook(root, again, "Unchanged answer.", active=True)
    events = [r["event"] for r in log_rows(root)]
    check("a repeated request text in a later turn is not the blocked turn",
          events == ["block", "after"], repr(events))


def test_document_length_is_counted_in_characters_for_write_and_edit():
    import deliver
    folder = tempfile.mkdtemp(prefix="deliver-length-")
    for chars, expected in ((600, None), (1600, ["report.md"])):
        body = "가" * chars
        path = os.path.join(folder, "report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        results = []
        for tool in (("Write", {"file_path": path, "content": body}),
                     ("Edit", {"file_path": path, "old_string": "가", "new_string": "가"})):
            tools = [(tool[0], json.dumps(tool[1], ensure_ascii=False))]
            fired = deliver.evaluate("Sent report.md.", "", tools, {}, names=("unopened",))
            results.append(fired.get("unopened", {}).get("files"))
        check(f"a {chars}-character Korean document is judged the same by Write and Edit",
              results == [expected, expected], repr(results))


def main():
    for test in (test_quiet_turn_passes, test_unopened_document_blocks_once_and_quotes_request,
                 test_unopened_document_exceptions, test_configured_delivery_tools, test_default_only_records, test_reader_signal,
                 test_korean_reason, test_broken_input_never_blocks, test_stats_counts_blocks_and_changes,
                 test_stats_links_a_reentry_only_to_its_own_blocked_turn,
                 test_document_length_is_counted_in_characters_for_write_and_edit):
        run_test(test, __file__)
    print(f"deliver: {'FAIL' if FAILED else 'PASS'} ({len(FAILED)} problems)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
