# What Codex and Antigravity really send to hooks

Captured 2026-11-21 in two scratch Git repositories outside any instance, one real session at a time, with
the cheapest model each runtime offered. Every hook was a logger that appended its raw stdin, its process
working directory and its event name. The inputs are saved, with synthetic ids and paths, in
[tools/tests/fixtures/runtimes/](../../tools/tests/fixtures/runtimes/): one file per runtime and event, each
case named below, and one shortened transcript per runtime. Every local time in them is written as UTC, to agree
with the timestamps, and server response ids are synthetic too.
`test:tools/tests/test_runtime_fixtures.py::test_captured_inputs_carry_the_fields_adapters_read` pins the
fields the adapters and readers will use.

## Codex

Version: codex-cli 0.169.1 (the desktop app's build). The `codex` on the capture machine's PATH was 0.153.4
and was not used. Model `gpt-6-luna` at effort low, the smallest entry of `codex debug models --bundled`,
accepted on the first try.

Every run ignored the user's configuration (`--ignore-user-config`), set the sandbox to read-only or
workspace-write with the network off, and marked only the fixture folder trusted for that one run. The
hook-trust bypass was used on every run but one, and the fixture's hooks file held only the logger. These runs
did not pass the other options `tools/fresh_worker.py` passes. A recheck in a new scratch repository passed all
of them except `--disable hooks` (agents off, every other listed feature disabled): start, resume, edit and two
compaction runs gave hook inputs with the same fields for all six events, and the values the table relies on
(`source`, `stop_hook_active`, the patch headers, the compaction order) came out the same.

Runs:
- start: a saved session, started in the subfolder `sub`.
- resume: `exec resume` of that session with the same prompt text.
- edit: ephemeral, apply_patch calls and shell commands.
- compact: ephemeral, with a one-run compaction limit.
- notrust: ephemeral, without the hook-trust bypass.

| Question | Answer | Run, fixture case |
|---|---|---|
| Folder trust for one run | The dotted form `-c 'projects."<path>".trust_level="trusted"'` is ignored with an "unrecognized configuration setting" notice, and then project hooks do not load ("Untrusted project-local configuration is disabled"). The inline-table form `-c 'projects={"<path>"={trust_level="trusted"}}'` works. | start, first attempt and retry |
| Working directory of a hook | The session's folder, not the repository root: started in `sub`, `cwd` on stdin and the hook's process folder were both `sub`. A fixed command must find the root itself. | start, `SessionStart-startup` |
| SessionStart `source` | `startup`, `resume` (on `exec resume`), `compact` (after a compaction inside a turn). | `SessionStart-*` |
| The same prompt text twice | Two UserPromptSubmit inputs with the same `prompt` and different `turn_id`. The repeat came from `exec resume`, a second process on the same session; two prompts one after another inside one live session were not measured, because `exec` takes one prompt per process. | start and resume, `UserPromptSubmit-first`, `-repeat` |
| apply_patch input | `tool_name` is `apply_patch`, and `tool_input.command` is the whole patch text. Paths appear only in its headers (`*** Add File:`, `*** Update File:`, `*** Delete File:`, and `*** Move to:` after the old path), relative to `cwd`. `tool_response` is a string ending in a status line per file (`A`, `M`, `D`). A move reports only `M` with the new path. | edit, `PostToolUse-apply_patch-*` |
| A failed apply_patch call | No PostToolUse at all. Four calls failed verification, one of them an update of a missing file, and none reached the logger. A shell command arrives as `tool_name` `Bash` with `tool_input.command`. | edit, `PostToolUse-Bash` |
| `stop_hook_active` and `last_assistant_message` | False at the first Stop, which the logger blocked once. True at the Stop after that retry, with the same `turn_id`. False at the Stop of the next turn. `last_assistant_message` was a string each time. The block reason reaches the model as a user message wrapped in `<hook_prompt hook_run_id="stop:...">`. | start and resume, `Stop-before`, `-retry`, `-fresh-turn` |
| Compaction | `exec` has no `/compact`. A one-run `-c model_auto_compact_token_limit` forced an automatic one: 20000 did in the first capture, while in the recheck 20000 did not and 6000 did, so the limit that forces one depends on how long the session already is. The order was PreCompact (`trigger` `auto`, no `permission_mode`), then PostCompact, then SessionStart with `source` `compact`, all in the same turn. | compact, `PreCompact-auto`, `PostCompact-auto`, `SessionStart-compact` |
| Where injected context is cut | A SessionStart block of 1,503 lines (24,388 tokens) reached the model as its first and last 76 lines, about 10 KB together. The head and tail markers survived and the middle marker did not. Codex adds a header with the original token count, a "tokens truncated" line, and the temporary file that holds the full output. A state block must stay under about 10 KB; past that, the middle is not in the model's context, which holds the warning and the path instead. | start, codex `transcript.jsonl` |
| Hooks without the bypass | `exec` exited 0 and the model answered. Nothing about hooks was printed on stdout or stderr, and the logger ran 0 times. Codex's hooks/list for the folder listed no project hooks without folder trust; with the one-run trust it listed each with `trustStatus` `untrusted`. The listing comes from `codex app-server`, which takes no `--ignore-user-config`; the recheck read it with `CODEX_HOME` set to an empty folder, so only the project layer was seen. | notrust, recheck |
| Transcript and workspace | `~/.codex/sessions/YYYY/MM/DD/rollout-<local time>-<session id>.jsonl`, named in `transcript_path`. The first line is `session_meta`, whose `cwd` is the start folder (here the subfolder) and whose `git` holds commit and branch. Each turn's `turn_context` has its `cwd`. A resume appends to the same file. An ephemeral run has `transcript_path` null and leaves no file. | start, codex `transcript.jsonl` |
| A session variable for the model's shell | `CODEX_THREAD_ID` and `CODEX_SESSION_ID`, both equal to the hook input's `session_id`. Hook processes do not get them. | compact (printed values), edit (names) |

The user's own hooks file under the Codex home is read even with `--ignore-user-config`, and its one hook
ran beside the fixture's under the bypass.

## Antigravity CLI

Version: agy 1.5.13. Model `gemini-3.8-flash-low`. Every run passed `--sandbox`, an explicit `--mode`, the
model, `--print-timeout` and json or stream-json output, in a fixture under the home folder. Earlier
findings (hooks run in print mode, the hook folder is `.agents`, `continuationActive` stays false, the
`/hooks` listing) were not repeated.

Runs:
- edit1: `--mode accept-edits`.
- edit: `--mode auto`, which fell back to the default mode, with one Stop continuation.
- second: a second prompt with `--conversation`.
- compact: `/compact` as the prompt.
- after: one more prompt after that.
- plan: `--mode plan`.
- ro: a one-run read rule and write-deny rule.
- stdin, stream: a long prompt on stdin.
- config: `/config`, without and with `--settings`.

| Question | Answer | Run, fixture case |
|---|---|---|
| In-place edit | Tool `edit_file`, args `Path` (absolute), `Target`, `Replacement`. A PostToolUse input carries `error` (empty on success), `stepIdx` and `toolCall.id`, and no tool result. | edit, `PostToolUse-edit_file` |
| Modes | `--mode auto` printed "not available for this account; continuing in the default mode", and the default mode ran a sandboxed shell command without asking. In `accept-edits` the first shell command was refused. The run then ended with an empty response, `status` SUCCESS, exit 0, and `denied_actions` `[{"action":"command","display_name":"Bash"}]`. | edit, edit1 |
| `executionNum` | 0 at the first Stop and 1 at the Stop after the continuation, back to 0 on a second prompt. `invocationNum` kept counting after the continuation (3) and went back to 0 on a new prompt. | edit and second, `Stop-first`, `-continued`, `-second-prompt`, `PreInvocation-after-continue` |
| Compaction in print mode | `/compact` with `--conversation` works. The response was empty, stderr said "run ended with no output and no recorded error", the exit was 0, and Stop had `terminationReason` `TERMINAL_CUSTOM_HOOK`. The transcript was appended, not rewritten: same first line, 12 rows (5.8 KB) became 15 (10.2 KB), and the new rows were the prompt, a system message and one `CHECKPOINT` row ("Resuming from a compaction"). No SessionStart followed. The next prompt's PreInvocation had `invocationNum` 0 and `initialNumSteps` 16 (13 before), and no field marked the compaction. The one signal is the new CHECKPOINT row. | compact and after, `Stop-compact`, `PreInvocation-compact`, `-after-compact`, agy `transcript.jsonl` |
| One-run settings | `--settings` takes a JSON object. `/config` in print mode lists the merged settings with no model call. A top-level key replaces the saved value: a saved list of one trusted folder became exactly the list given. The key spelling is `"permissions": {"allow": [...], "deny": [...]}` with rules such as `read_file(<absolute folder>)` and `write_file(*)`, and `/config` showed them. Nothing was saved: the settings file kept its time and size. | config |
| Read-only run | `allow read_file(<fixture>)` with `deny write_file(*)`. The model answered the read and reported the write refused ("Matches user-configured deny rule"). No file was written, there was no `denied_actions` field, and the exit was 0. | ro |
| Plan mode | Not an answer mode. The prompt arrives as `/plan <text>`, the model writes a plan with `write_file` into the conversation's artifact folder, and the response asks for approval instead of answering. | plan, `PostToolUse-write_file` |
| A long prompt on stdin | `-p` needs an argument, and `-p -` takes the dash as the prompt. With `--input-format stream-json --output-format stream-json`, one line `{"event":"user","message":{"role":"user","content":"<text>"}}` delivered a 202,570-character prompt whole (the length of `lastUserInput` in the hook input). The output is NDJSON events: `init`, `step_update`, `result`. | stdin, stream |
| Transcript and workspace | `~/.gemini/antigravity-cli/brain/<conversation id>/.system_generated/logs/transcript_full.jsonl` (the hook's `transcriptPath`), with `transcript.jsonl` beside it holding the same rows. Rows carry `type`, `source`, `step_index`, `status`, `content` and `created_at`, and no folder. The workspace is in the conversation index (`conversation_summaries.db`, column `workspace_uris`, `["file://<workspace>"]`, read only for this capture's own conversations) and in the hook input's `cwd` and `workspacePaths`. | all runs |
| A session variable | Hook processes get `ANTIGRAVITY_CONVERSATION_ID`, equal to `conversationId`. The model's shell sees `ANTIGRAVITY_CONVERSATION_ID` and `ANTIGRAVITY_TRAJECTORY_ID` among other `ANTIGRAVITY_` names; only the names were read there. | second and later (hooks), edit (model shell) |

A model's shell also inherits the variables of the runtime that started the run: inside Antigravity it saw the
`CLAUDE_CODE_*` names of the Claude Code session that launched the capture. They do not identify the session
the shell belongs to, so a reader takes only the variables of its own runtime.

## What the kit declares from this

These are the fixed lines the kit declares (KIT-DR-042). Their command text, their timeout and their position in
the file may not change: Codex ties each approval to the hooks file's absolute path, the event, the group and
handler position, the command text and the timeout, so any change asks every Codex user for approval again.

| Runtime | File | Line | Events and timeouts (s) |
|---|---|---|---|
| Claude Code | `.claude/settings.json` | `sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" event <Event> claude` | SessionStart 30, UserPromptSubmit 15, PostToolUse 15 (`Write\|Edit\|NotebookEdit`), Stop 190, PreCompact 20 |
| Codex | `.codex/hooks.json` | `sh "$(git rev-parse --show-toplevel 2>/dev/null \|\| pwd)/tools/hook.sh" event <Event> codex` | the same five, PostToolUse matching `^apply_patch$` |
| Antigravity | `.agents/hooks.json`, hook name `kit` | `sh ../tools/hook.sh event <Event> agy` | SessionStart 30, PreInvocation 15, PostToolUse 15 (both generations of edit tool names), Stop 190 |

The adapters in `tools/dispatch.py` read the fields this record names, and
`test:tools/tests/test_dispatch.py::test_codex_and_agy_fixtures_pass_through_both_adapters` runs the fixtures
through them.

## Not measured, and why

- Codex: a manual `/compact` and its `trigger` value, and the "Hooks need review" screen and "Trust all".
  Both need the interactive client, which these runs may not use.
- Codex 0.153.4: not run.
- Codex: two prompts in a row inside one live session (see the same prompt text twice), and hooks/list with
  the user's layer loaded but the user's configuration ignored, which `app-server` does not offer.
- Antigravity: whether saved permission rules are merged with or replaced by a one-run `permissions` value.
  The capture machine has no saved rules, and writing them would change the user's configuration. Top-level
  replacement was shown with the trusted folder list.
- Antigravity: the interactive folder-trust prompt, which print mode skips.
- Antigravity: whether the model's shell variable equals the conversation id; only its name was read. A later
  run measured it (see [A fresh instance, measured](#a-fresh-instance-measured)).

## What the runs left in each runtime's history

Codex keeps three saved sessions in its sessions folder: the start session, which the resume continued, the
first attempt whose trust flag was ignored, and the recheck's start session, which its resume continued. The
ephemeral runs left none. Antigravity keeps every print-mode conversation in its brain folder and its index;
the `/config` listings made none. The full output of the cut block, which Codex writes to its temporary
folder, was removed after the capture. The ids are in the capture unit's report, not here.

## A fresh instance, measured

Measured 2026-11-21 in an instance made as in the README's Try it (`git clone`, then
`bash setup.sh --name work --context personal`, doctor FAIL 0), in a temporary folder under the home folder,
one real session at a time. Claude Code 2.1.292 ran with `haiku` over stream-json, with project settings only
(`--setting-sources project`) and `--include-hook-events`. Antigravity CLI 1.5.14 (the capture above ran 1.5.13;
agy updated its binary at setup time, before the first session) ran with
`gemini-3.8-flash-low`, `--sandbox`, `--mode auto` (which fell back to the default mode, as in the capture) and
json output, and continued a conversation with `--conversation`. The instance's `workers` key set `haiku` at
effort low for claude and `gemini-3.8-flash-low` for gemini. A shim placed first on PATH timed each
`tools/dispatch.py` run and kept its answer. A prompt replayed through `tools/hook.sh` without the shim took
0.05 s in all, so the launcher itself adds almost nothing.

| Cell | Claude Code | Antigravity CLI |
|---|---|---|
| State at start | Works. The SessionStart answer carried the state block, and the model quoted its first line. | Works. A new conversation's SessionStart carried it, and the model quoted its first line (two conversations). A continued conversation whose state had not changed got no second copy. |
| A Markdown file rewritten into a new folder with an edit tool, breaking a link | Works. The model wrote a new file under docs/sub with a link to b.md and removed the old file with `rm`. Stop blocked with `docs/sub/doc-claude.md -> b.md`, the model changed the link to point one folder up, and the next Stop passed. Claude Code showed its own notice "Stop hook error occurred" at the block. | Works. The model wrote a new file under docs/sub with the write tool, ran no shell command and left the original in place. Stop answered continue with `docs/sub/doc-agy3.md -> b.md`, the model removed the link markup, and the next Stop passed. In an earlier attempt `rm` of the old file failed inside the sandbox ("Operation not permitted"); the model asked to run it outside the sandbox and print mode refused. That turn ended on the refusal and no Stop hook ran. The edit stayed marked, so the block came at the end of the next prompt, and the Stop after the fix passed. |
| A prompt after another session wrote a note | Works. A note added from an Antigravity conversation was shown at the next Claude session's start. A second Claude session was shown it and the first session's note, once each. The finish note of `ask.sh gemini` was shown to the asking session at its next prompt. | Works. A continued conversation was shown the Claude session's note at its next prompt. A new conversation was shown, at its start, both notes and the finish note of a Claude worker that no session had seen. |
| `tools/ask.sh`, the host reads the receipt | Claude to Gemini works. `bash tools/ask.sh gemini docs/q.md` ran the worker in a copy, offline, with `gemini-3.8-flash-low`. The host ran `python3 tools/receipts.py show <id>` and quoted the answer and the `model` line. The verdict was INCONCLUSIVE because the worker left out the RESULT_JSON line. | Gemini to Claude works. `bash tools/ask.sh claude docs/q.md` failed inside the sandbox: the guest runtime could not start. The model asked to run it outside the sandbox, and print mode allowed that. The claude worker answered with `haiku` (verdict INCONCLUSIVE: an empty evidence list), and the host quoted the answer and the `model` line from the receipt. |
| Times the user acted | None. | None: this machine's trusted folders hold the home folder, so `hooks · agy armed` was ok right after setup. |
| Added wait, median | Per prompt 0.049 s (8 prompts). Per turn end 0.201 s (9). Start 0.055 s (2). Per edit 0.049 s (2). | First model call of a prompt 0.055 s (8), each later model call 0.037 s (14). Per turn end 0.221 s (9). Start 0.064 s (2). Per edit 0.049 s (4). |
| Checks missed | A move by a shell command (`mv`) in an ignored folder is not checked, by design (README step 4); see the rerun below. | The same `mv` move is not checked. One check moved to the next prompt (above). By design there is no delivery check and no compaction record. |

A first Claude Code attempt put the documents in a subfolder named `work/`, inside an instance folder also
named `work`, and the model looked for them at the root. The documents were moved to `docs/` and the turn was
run again in a new session. The `hooks · agy armed` row of doctor labelled the two roles Antigravity has no event
for "not listed by Codex"; the label now reads "not in the runtime's hook list".

A rerun the same day in a second fresh instance (agy 1.5.14 by `agy --version` at the run) moved a Markdown
file with a shell command in each runtime: `mkdir -p docs/sub && mv docs/doc-agy.md docs/sub/doc-agy.md` in
Antigravity, inside `--sandbox` and without asking to leave it, and the same `mv` for `doc-claude.md` through
Claude Code's Bash tool. Both commands exited 0 and moved the file, so a shell command inside Antigravity's
sandbox can change the folder. No PostToolUse ran, each Stop answered with nothing to report (`{}` in
Antigravity, empty in Claude Code), `python3 tools/gate.py manual-check` gave PASS, and
`python3 tools/linkcheck.py --filelist` on the moved files reported `docs/sub/doc-agy.md -> b.md` and
`docs/sub/doc-claude.md -> b.md` broken. This is the gap README step 4 names: a file written by a shell command is
not checked. An independent review saw the same in both runtimes; in its Antigravity run `ask.sh` inside the
sandbox still wrote its dispatch log and a run folder whose receipt says the runtime could not start
(`PermissionError: Operation not permitted`).

The model's shell variables, measured in a bare scratch repository: Antigravity's `ANTIGRAVITY_CONVERSATION_ID`
equals the print-mode `conversation_id`, and Claude Code's `CLAUDE_CODE_SESSION_ID` in the Bash tool equals the
session id.

Codex: 0.169.1 and 0.153.4 are installed. No real Codex session ran. On 2026-11-21 Codex sessions could not
start on the measuring account ("model is not supported when using Codex with a ChatGPT account"), so the
wave's session wrapper refused every Codex command (exit 69). Every Codex cell is not verified in a real Codex
session. The stand-in tests run the captured Codex inputs through the same cells:
`test:tools/tests/test_dispatch.py::test_codex_and_agy_fixtures_pass_through_both_adapters` (state at start),
`test:tools/tests/test_dispatch.py::test_a_moved_ignored_document_with_a_broken_link_stops_its_turn_once_in_each_runtime`
(the link turn),
`test:tools/tests/test_notes.py::test_a_note_shows_once_in_each_other_runtime_and_not_after_it_is_taken`
(notes) and
`test:tools/tests/test_fresh_worker.py::test_ask_runs_two_runtimes_at_once_and_each_receipt_names_its_model`
(asking). What the user sees, from the capture and Codex's documentation: without approval `codex exec` runs
no project hook and prints nothing about it; the terminal client shows "Hooks need review" with "Review
hooks", "Trust all and continue" and "Continue without trusting (hooks won't run)"; the desktop app has Review
hooks and Settings > Hooks. It is one act per checkout path, and again after any change to a declared line.
Doctor names the step until then.

Of the six directions of `tools/ask.sh`, Claude to Gemini and Gemini to Claude work. Claude to Codex, Codex
to Claude, Codex to Gemini and Gemini to Codex are not measured, for the reason above.

Not measured, and what the documentation says:
- Claude Code's interactive start in a new folder, which asks whether to trust the folder before project
  settings and their hooks apply. Headless runs do not ask.
- Antigravity's interactive trust prompt, "Do you trust the contents of this project?" with "Yes, I trust this
  folder". The answer is saved in `trustedWorkspaces`, and workspace hooks load after trust.
- What an interactive Antigravity session shows when the model asks to run a command outside the sandbox. The
  print-mode refusal reads "user denied permission to run command".

Left in history: Claude Code saved the two host sessions and the variable probe's session in two project
folders named after the scratch paths. Both folders were moved out and deleted. The guest Claude worker saves no
session. Antigravity keeps four conversations in its brain folder and index: two hosts, the guest worker's
conversation in a copy, and the variable probe. The rerun added one Claude Code project folder, moved out and
deleted, and one Antigravity conversation. Codex: none. The ids are in the measuring unit's report.
