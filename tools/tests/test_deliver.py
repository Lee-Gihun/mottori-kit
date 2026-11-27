#!/usr/bin/env python3
"""Regression tests for the pre-delivery check: each signal fires on its case and stays quiet otherwise."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]

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
    # Each run creates many roots; remove them so they do not pile up on a small disk.
    atexit.register(shutil.rmtree, root, True)
    os.makedirs(os.path.join(root, "instance"))
    os.makedirs(os.path.join(root, "state"))
    return root


def run_hook(root, rows, message, active=False, config=BLOCK_UNOPENED):
    transcript = os.path.join(root, "transcript.jsonl")
    with open(transcript, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    if config is not None:
        with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"deliver": config}, f)
    payload = {"session_id": "s1", "transcript_path": transcript, "stop_hook_active": active,
               "last_assistant_message": message}
    env = dict(os.environ, MOTTORI_INSTANCE=root)
    # The Stop event's delivery step through the dispatcher, in a process that imports this root.
    code = ("import json, sys; sys.path[:0] = sys.argv[1:]; from testlib import hook_event; "
            "print(hook_event('Stop', json.load(sys.stdin), 'deliver'), end='')")
    result = subprocess.run([sys.executable, "-c", code, HERE, os.path.join(HERE, "tests")],
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
    rows[3] = use("Read", file_path="/y/report.md")
    code, out, _err = run_hook(instance(), rows, "I reread the report and sent it.")
    check("reading another folder's file of the same name is not a reread", out and "report.md" in out["reason"],
          repr(out))
    root = instance()
    full = os.path.join(root, "docs", "report.md")

    def reread(call):
        rows = [user("Write the report."), use("Write", file_path=full, content=BODY), tool_result(),
                call, tool_result(), use("SendUserFile", files=[full])]
        return run_hook(root, rows, "I reread the report and sent it.")[1]
    check("a shell command naming the full path is a reread", reread(use("Bash", command=f"cat {full}")) is None)
    check("the path relative to the instance root is a reread",
          reread(use("Bash", command="sed -n 1,80p ./docs/report.md")) is None
          and reread(use("Bash", command="head docs/report.md")) is None)
    check("a path that starts a line or follows a tab is a reread",
          reread(use("Bash", command=f"wc -l \\\n{full}")) is None
          and reread(use("Agent", prompt="Check these:\ndocs/report.md\n")) is None
          and reread(use("Bash", command=f"cat\t{full}")) is None)
    dotted = os.path.join(root, "docs", ".", "report.md")
    rows = [user("Write the report."), use("Write", file_path=dotted, content=BODY), tool_result(),
            use("Read", file_path=dotted), tool_result(), use("SendUserFile", files=[dotted])]
    check("a Read of the path as it was written is a reread",
          run_hook(root, rows, "I reread the report and sent it.")[1] is None)
    for name, call in (("the same file name under another folder", use("Bash", command="cat old/docs/report.md")),
                       ("the full path followed by .bak", use("Bash", command=f"cat {full}.bak")),
                       ("a later edit naming the path", use("Edit", file_path=full)),
                       ("a send naming the path", use("SendUserFile", files=[full]))):
        out = reread(call)
        check(f"{name} is not a reread", out and "report.md" in out["reason"], repr(out))
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
    check("the same call is not delivery when the tool is not a delivery tool", out is None, repr(out))


def test_default_only_records():
    # Published records cite this name as evidence, so it stays although the default now records nothing.
    root = instance()
    code, out, _err = run_hook(root, written_and_sent(), "I sent the report.", config=None)
    check("with no config nothing blocks or is recorded", code == 0 and out is None and not log_rows(root), repr(out))
    # Opening a FIFO with no writer hangs, so a hook that reads the transcript with no signal on times out.
    fifo = os.path.join(root, "unread.jsonl")
    os.mkfifo(fifo)
    payload = {"session_id": "s1", "transcript_path": fifo, "last_assistant_message": "I sent the report."}
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "hook"], input=json.dumps(payload),
                       capture_output=True, text=True, env=dict(os.environ, MOTTORI_INSTANCE=root), timeout=20)
        opened = False
    except subprocess.TimeoutExpired:
        opened = True
    check("with no signal on the hook returns before opening the transcript", not opened)
    root = instance()
    code, out, _err = run_hook(root, written_and_sent(), "I sent the report.", config={"observe": ["unopened"]})
    log = log_rows(root)
    check("an observed signal is recorded without blocking", out is None and len(log) == 1
          and log[0]["event"] == "observe" and log[0]["signals"] == ["unopened"], repr((out, log)))
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


def test_reason_is_english_after_a_korean_answer():
    code, out, _err = run_hook(instance(), written_and_sent(), "보고서를 보냈어.")
    check("the reason is English when the answer is Korean", out and "[pre-delivery check]" in out["reason"], repr(out))


def test_broken_input_never_blocks():
    root = instance()
    env = dict(os.environ, MOTTORI_INSTANCE=root)
    result = subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "hook"],
                            input="{not json", capture_output=True, text=True, env=env)
    check("malformed hook input exits zero without blocking", result.returncode == 0 and not result.stdout.strip())
    root = instance()
    env = dict(os.environ, MOTTORI_INSTANCE=root)
    payload = {"session_id": "s", "transcript_path": "/nonexistent/t.jsonl", "last_assistant_message": "All done."}
    # The Stop event's delivery step through the dispatcher, in a process that imports this root.
    code = ("import json, sys; sys.path[:0] = sys.argv[1:]; from testlib import hook_event; "
            "print(hook_event('Stop', json.load(sys.stdin), 'deliver'), end='')")
    result = subprocess.run([sys.executable, "-c", code, HERE, os.path.join(HERE, "tests")],
                            input=json.dumps(payload), capture_output=True, text=True, env=env)
    check("a missing transcript passes without a failure",
          result.returncode == 0 and not result.stdout.strip() and not result.stderr.strip(), result.stderr)
    root = instance()
    with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    code, out, err = run_hook(root, written_and_sent(), "I sent the report.", config=None)
    check("a broken config falls back to checking nothing, without a failure",
          code == 0 and out is None and not err.strip() and not log_rows(root), repr((out, err)))


def test_hook_failure_is_logged_once_under_the_settings_redirect():
    root = instance()
    log = os.path.join(root, "state", ".hook-errors.log")
    # Same stderr redirect tools/hook.sh gives a declared Stop hook.
    # A folder where the record log belongs makes the record write fail.
    os.makedirs(os.path.join(root, "state", ".deliver.jsonl"))
    code, out, err = run_hook(root, written_and_sent(), "I sent the report.")
    check("the failure is reported on stderr", code == 0 and out is None and "deliver hook failed" in err, err)
    env = dict(os.environ, MOTTORI_INSTANCE=root, PY=sys.executable, DELIVER=os.path.join(HERE, "deliver.py"),
               LOG=log)
    payload = {"transcript_path": os.path.join(root, "transcript.jsonl"), "last_assistant_message": "I sent the report."}
    subprocess.run('"$PY" "$DELIVER" hook 2>>"$LOG"', shell=True, input=json.dumps(payload),
                   capture_output=True, text=True, env=env)
    with open(log, encoding="utf-8") as f:
        lines = [line for line in f if line.strip()]
    check("a hook failure lands in the error log exactly once", len(lines) == 1, repr(lines))


def stats_text(root):
    env = dict(os.environ, MOTTORI_INSTANCE=root)
    return subprocess.run([sys.executable, os.path.join(HERE, "deliver.py"), "stats"],
                          capture_output=True, text=True, env=env).stdout


def test_stats_counts_blocks_and_changes():
    root = instance()
    run_hook(root, written_and_sent(), "I sent the report.")
    run_hook(root, written_and_sent(), "I sent the report.", active=True)
    out = stats_text(root)
    check("stats reports one block that did not change the answer",
          "blocked turns: 1" in out and "answer changed: 0" in out, out)


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
          "blocked turns: 1; seen again: 1; answer changed: 1" in out, out)
    check("the per-signal row agrees", "blocked 1 · seen again 1 · changed 1" in out, out)
    events = [r["event"] for r in log_rows(root)]
    check("re-entries of other turns write nothing", events == ["block", "after"], repr(events))
    # The same request typed again later in the session is a different turn. Block the first turn
    # without re-entering it, so only the turn key can keep the later turn from claiming the block.
    root = instance()
    run_hook(root, rows, "I sent the report.")
    again = rows + [use("Bash", command="true"), user("Write the report on why the deploy failed."),
                    use("Bash", command="true")]
    run_hook(root, again, "Unchanged answer.", active=True)
    events = [r["event"] for r in log_rows(root)]
    check("a repeated request text in a later turn is not the blocked turn", events == ["block"], repr(events))


def test_unchanged_reply_counts_as_unchanged():
    for reply in ("checked: unchanged", '"checked: unchanged."'):
        root = instance()
        rows = written_and_sent()
        run_hook(root, rows, "I sent the report.")
        run_hook(root, rows, reply, active=True)
        after = [r for r in log_rows(root) if r["event"] == "after"]
        check(f"the reply {reply!r} the block asks for counts as unchanged",
              len(after) == 1 and after[0]["changed"] is False, repr(after))
        out = stats_text(root)
        check(f"stats counts {reply!r} as no change", "answer changed: 0" in out, out)


def test_injected_user_rows_are_not_owner_requests():
    injected = (
        ("a task notification", user("<task-notification>bg done</task-notification>")),
        ("a system reminder", user("<system-reminder>Note the file changed.</system-reminder>")),
        ("a compaction summary", {"type": "user", "isCompactSummary": True, "message": {
            "role": "user", "content": "This session is being continued from a previous conversation."}}),
        ("a non-human origin", {"type": "user", "origin": {"kind": "task-notification"},
                                "message": {"role": "user", "content": "Background job finished."}}),
    )
    for label, row in injected:
        rows = written_and_sent() + [tool_result(), row]
        code, out, _err = run_hook(instance(), rows, "I sent report.md.")
        check(f"{label} after the write is not a new owner request",
              out and out.get("decision") == "block" and "why the deploy failed" in out["reason"], repr(out))
    rows = [user("Write the report on why the deploy failed."), user("<task-notification>bg done</task-notification>"),
            use("Write", file_path="/x/report.md", content=BODY), tool_result(),
            use("SendUserFile", files=["/x/report.md"])]
    code, out, _err = run_hook(instance(), rows, "I sent the report.")
    check("a block never quotes a task notice as the owner's request",
          out and "why the deploy failed" in out["reason"] and "task-notification" not in out["reason"], repr(out))
    rows = [user("Write the report on why the deploy failed."), {"type": "user", "origin": {"kind": "human"},
            "message": {"role": "user", "content": "Write the summary instead."}},
            use("Write", file_path="/x/report.md", content=BODY), tool_result(),
            use("SendUserFile", files=["/x/report.md"])]
    code, out, _err = run_hook(instance(), rows, "I sent the report.")
    check("a human-origin row is still the owner's request",
          out and "Write the summary instead" in out["reason"], repr(out))
    # The runtime stores many owner messages as a list whose first text block is injected.
    for label, extra in (("without an origin", {}), ("with a human origin", {"origin": {"kind": "human"}})):
        mixed = dict(user([{"type": "text", "text": "<system-reminder>context</system-reminder>"},
                           {"type": "text", "text": "Now write the summary instead."}]), **extra)
        rows = [user("Write the report on why the deploy failed."), use("Write", file_path="/x/old.md", content=BODY),
                tool_result(), use("SendUserFile", files=["/x/old.md"]), tool_result(), mixed,
                use("Write", file_path="/x/report.md", content=BODY), tool_result(),
                use("SendUserFile", files=["/x/report.md"])]
        code, out, _err = run_hook(instance(), rows, "I sent the report.")
        check(f"an owner message after an injected block is a new request ({label})",
              out and "Now write the summary instead" in out["reason"] and "system-reminder" not in out["reason"]
              and "why the deploy failed" not in out["reason"], repr(out))
        rows = rows[:6]
        code, out, _err = run_hook(instance(), rows, "It is at old.md.")
        check(f"a document from the previous turn does not block the new one ({label})", out is None, repr(out))
    rows = written_and_sent() + [tool_result(), dict(user("[Request interrupted by user]"), origin={"kind": "human"})]
    code, out, _err = run_hook(instance(), rows, "I sent report.md.")
    check("a human-origin row starts a new turn whatever its text", out is None, repr(out))
    # An owner-typed slash command arrives as a <command-name> row with no origin; it opens a turn.
    command = user("<command-name>/recall</command-name>\n<command-args>q</command-args>")
    rows = [user("Write the report on why the deploy failed."), use("Write", file_path="/x/old.md", content=BODY),
            tool_result(), command]
    code, out, _err = run_hook(instance(), rows, "It is at old.md.")
    check("a slash command row starts a new turn", out is None, repr(out))
    rows += [use("Write", file_path="/x/report.md", content=BODY), tool_result()]
    code, out, _err = run_hook(instance(), rows, "It is at report.md.")
    check("a block in a slash command turn quotes the command",
          out and "/recall" in out["reason"] and "why the deploy failed" not in out["reason"], repr(out))


def test_delivery_needs_the_whole_file_name():
    cases = (("/x/a.md", "See data.md for the numbers.", None),
             ("/x/report.md", "See old-report.md for last week.", None),
             ("/x/report.md", "report.md에 정리했어.", ["report.md"]),
             ("/x/report.md", "It is at /x/report.md now.", ["report.md"]),
             ("/x/report.md", "Sent `report.md`.", ["report.md"]),
             ("/x/notes.md", "See notes.md.bak and notes.md_old.", None))
    for path, message, expected in cases:
        rows = [user("Write it."), use("Write", file_path=path, content=BODY), tool_result()]
        code, out, _err = run_hook(instance(), rows, message)
        got = ["report.md"] if out and "report.md" in out["reason"] else None
        if expected is None:
            check(f"{message!r} does not deliver {os.path.basename(path)}", out is None, repr(out))
        else:
            check(f"{message!r} delivers {os.path.basename(path)}", got == expected, repr(out))
    rows = [user("Write it."), use("Write", file_path="/x/report.md", content=BODY), tool_result(),
            use("SendUserFile", files=["/x/old-report.md"])]
    code, out, _err = run_hook(instance(), rows, "Sent the old one.")
    check("sending another file whose name ends with the base name is not delivery", out is None, repr(out))


def test_malformed_log_line_is_skipped():
    root = instance()
    rows = written_and_sent()
    run_hook(root, rows, "I sent the report.")
    with open(os.path.join(root, "state", ".deliver.jsonl"), "a", encoding="utf-8") as f:
        f.write('{"broken\n')
    run_hook(root, rows, "I reread it and fixed the summary.", active=True)
    path = os.path.join(root, "state", ".deliver.jsonl")
    with open(path, encoding="utf-8") as f:
        events = []
        for line in f:
            try:
                events.append(json.loads(line)["event"])
            except ValueError:
                events.append("broken")
    check("a malformed log line does not stop the follow-up row", events == ["block", "broken", "after"],
          repr(events))
    check("stats still counts the block", "blocked turns: 1" in stats_text(root), stats_text(root))


def test_document_length_is_counted_in_characters_for_write_and_edit():
    import deliver
    folder = tempfile.mkdtemp(prefix="deliver-length-")
    atexit.register(shutil.rmtree, folder, True)
    for chars, expected in ((600, None), (1600, ["report.md"])):
        body = "가" * chars
        path = os.path.join(folder, "report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        results = []
        for tool in (("Write", {"file_path": path, "content": body}),
                     ("Edit", {"file_path": path, "old_string": "가", "new_string": "가"})):
            tools = [(tool[0], json.dumps(tool[1], ensure_ascii=False))]
            fired = deliver.evaluate("Sent report.md.", tools, {}, names=("unopened",))
            results.append(fired.get("unopened", {}).get("files"))
        check(f"a {chars}-character Korean document is judged the same by Write and Edit",
              results == [expected, expected], repr(results))


def main():
    for test in (test_quiet_turn_passes, test_unopened_document_blocks_once_and_quotes_request,
                 test_unopened_document_exceptions, test_configured_delivery_tools, test_default_only_records, test_reader_signal,
                 test_reason_is_english_after_a_korean_answer, test_broken_input_never_blocks,
                 test_hook_failure_is_logged_once_under_the_settings_redirect,
                 test_stats_counts_blocks_and_changes,
                 test_stats_links_a_reentry_only_to_its_own_blocked_turn,
                 test_unchanged_reply_counts_as_unchanged, test_injected_user_rows_are_not_owner_requests,
                 test_delivery_needs_the_whole_file_name, test_malformed_log_line_is_skipped,
                 test_document_length_is_counted_in_characters_for_write_and_edit):
        test()
    print(f"deliver: {'FAIL' if FAILED else 'PASS'} ({len(FAILED)} problems)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
