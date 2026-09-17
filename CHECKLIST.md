Korean: `CHECKLIST.ko.md`

# CHECKLIST: Checks after installation

Use this list after `bash setup.sh` and `python3 tools/doctor.py` finish. Some machine checks overlap with doctor,
but **a person judges the result here**. Doctor measures whether hooks are declared, command-valid, and armed
through Codex trust. It cannot measure whether a hook fired and affected the model. Section C covers that gap.

- `[ ]` requires human judgment.
- `[machine]` can be checked with one command. Paste it and inspect the result.

---

## A. Policy: Check this before anything else

The remaining checks matter only after these pass.

- `[ ]` **May you clone a personal GitHub repository onto a company machine?** Check IT policy. If not, use a
  mirror on the company Git host or transfer an archive instead.
- `[ ]` **Are project hooks allowed?** State-injection hooks live in this repository's project-level
  `.claude/settings.json`. A Mac managed by MDM may block project hooks or require approval. If blocked, automatic
  state injection does not run. You can fall back to `python3 tools/now.py render` and manual reading, but that
  restores the discipline this kit is meant to remove. Open Claude Code at the repository root so
  `$CLAUDE_PROJECT_DIR` points to this directory.
- `[ ]` **May you use transcription and recording tools?** `tools/transcribe.py` and `tools/diarize.py` handle
  meeting audio. Recording consent and data-retention policies apply. **Do not run them before confirming
  policy.** If you will not use them, do not delete them. They are tracked engine files, and deletion will
  conflict with the next pull. Record the execution ban in `system/instance-rules.md`.
- `[ ]` **May company material be sent to external models?** Confirm the scope of approval for Claude and Codex.
  Do not put data outside that scope in this workspace.

## B. Valve: Does company material stay inside?

- `[machine]` Are there no remotes, or only allowed remotes?

  ```bash
  git remote -v          # setup.sh adds clone origin to the allowlist as the engine update path. Doctor catches others
  ```

- `[machine]` Is instance data really outside Git?

  ```bash
  git status --short     # state/ and _private/ must not appear
  git check-ignore -v state/NOW.md system/memory-config.json
  ```

- `[ ]` **If a remote exists, did you clone with pull-only credentials?** Allow engine updates but prevent pushes
  from this side. `.gitignore` protects data, and credentials protect code. These are two separate barriers.
- `[ ]` Did you complete the boundary declaration in `system/instance-rules.md`? Any remaining `CHANGEME` means
  it was not completed.

## C. Hooks: Doctor knows command effects but not actual runtime firing

Doctor verifies SessionStart command output and the journal effect of PreCompact in a temporary instance. It
cannot verify that the runtime dispatcher **actually fired** either command or that SessionStart output entered
the model context.

- `[ ]` **Check SessionStart injection.** Open a new session and ask exactly:

  > What does NOW currently say?

  If the model answers without reading a file, injection worked. If it reads the file, injection did not work.
- `[ ]` **Check actual PreCompact firing.** Doctor already verifies the command effect. After the next real
  compaction, run:

  ```bash
  tail -3 state/journal-$(date +%Y-%m).md   # A "compaction occurred" row must be present
  test ! -e state/.hook-errors.log && echo "no hook error log" || cat state/.hook-errors.log
  ```

- `[ ]` **Approve Codex hook trust.** Codex asks for trust the first time it sees hooks. If you do not approve,
  they silently do not run. Launch `codex` once and check whether the prompt appears.
- `[ ]` **Does Codex read AGENTS.md?** Send one task and inspect whether the response follows the seven core rules,
  including the outbound em-dash restriction and human-only send, commit, and push boundary.

## D. First use: Does it actually run?

- `[machine]` Record the first event, then regenerate NOW:

  ```bash
  python3 tools/now.py log "[system/state] installation verification"
  cat state/NOW.md
  ```

- `[machine]` Does recall search only this instance? Sessions from other instances must not appear.

  ```bash
  python3 tools/recall.py sessions
  ```
  Before the first Claude or Codex session, no output with exit code 0 is normal. After opening one session,
  verify that only the current instance path appears.

- `[machine]` Send a task to Codex, if the Codex CLI is installed:

  ```bash
  printf '%s\n' "Answer in one line: how many always-on core rules does this repository have?" \
    > system/debate/_p_canary.md
  bash tools/ask_codex.sh system/debate/_p_canary.md > /tmp/codex.log
  tail -15 /tmp/codex.log
  rm system/debate/_p_canary.md
  ```

  The output must show `FRESH_WORKER v1`, `capability: workspace-write`, and `status: success`. The receipt must
  be no more than 4,096 bytes, and it must not print the full transcript.
- `[ ]` Do the slash commands `/now`, `/recall`, `/dossier`, and `/garden` appear?
- `[machine]` **Does the verification gate actually block bad changes?** Check all three cases. If any case passes,
  the gate is equivalent to having no gate. **Run this in a disposable clone.** If you run it in the original and
  the gate is broken, the commit in test 1 remains in real history. 2026-09-17 independent audit P.

  ```bash
  T="$(mktemp -d)" && git clone -q . "$T/gatetest" && cd "$T/gatetest"
  bash setup.sh --name gatetest --context personal >/dev/null
  bash tools/install_hooks.sh --repair
  bash tools/install_hooks.sh --check
  python3 tools/gate.py baseline

  # 1) Does a broken reference block a commit?
  #    The file is under system/ because the repository root is deny-by-default, so git add would fail there
  printf '[missing](nope-zz.md)\n' > system/_gatetest.md
  git add system/_gatetest.md && git commit -m "must be blocked"   # Failure is success. The clone is disposable if it passes
  git reset -q HEAD system/_gatetest.md 2>/dev/null; rm -f system/_gatetest.md

  # 2) If a checker crashes, does the gate block instead of reporting zero issues?
  python3 tools/gate.py dirty
  cp tools/linkcheck.py /tmp/lc.bak && printf 'def ((((\n' >> tools/linkcheck.py
  echo '{}' | python3 tools/gate.py check     # Must block with "measurement unavailable"
  cp /tmp/lc.bak tools/linkcheck.py

  # 3) Does the gate block both a missing and a corrupt baseline, without automatic adoption?
  cp state/.gate-baseline.json /tmp/bl.bak
  rm state/.gate-baseline.json
  python3 tools/gate.py dirty && echo '{}' | python3 tools/gate.py check
  cp /tmp/bl.bak state/.gate-baseline.json
  printf '{ corrupt' > state/.gate-baseline.json
  python3 tools/gate.py dirty && echo '{}' | python3 tools/gate.py check
  cp /tmp/bl.bak state/.gate-baseline.json

  cd - >/dev/null && rm -rf "$T"      # Clean up the disposable clone
  ```

  **Know what the gate cannot see.** PostToolUse observes changes only from `Write`, `Edit`, and `NotebookEdit`.
  Bash edits, external writers, and Codex edits are caught only by pre-commit. If a turn ends through an
  interrupt, `gate.py resume` recovers it at the next prompt. `git commit --no-verify` bypasses every check.

## E. Backup: What this repository does not do

**If `.gitignore` blocks the data, the data is not backed up.** The journals and dossiers under `state/`, and the
ledgers under `_private/`, exist only on this machine.

- `[ ]` Is this workspace inside a company backup location, such as Time Machine or an MDM backup?
- `[ ]` If not, have you chosen a separate backup?
- `[ ]` **Do you understand the risk of `git clean -xdf`?** It deletes untracked files. That means it deletes all
  of `state/` and `_private/`. Never use it in this directory.

## F. Within the first week

- `[ ]` Register one track in `tracks` within `system/memory-config.json`.
- `[ ]` When a topic lasts several days, assign one dossier in `threads`.
- `[ ]` After the first compaction, does the first recovered response know the state? If not, the hook is not
  running. Return to the first item in section C.

## G. When you change the engine

If you fix this kit at work, there is **no** automatic path that sends the change to your personal machine. This
is intentional. An automatic path would require a machine to decide whether a change contains company IP. A
string check cannot prove that.

- `[ ]` For an ordinary bug, record only the symptom. Reproduce and fix it on the personal machine.
- `[ ]` If the change still must be uploaded, a person must read the diff and confirm that it contains no company
  identifiers, measurements, or code names. Then upload it using separate write credentials.

## Item evidence

This checklist retains only human authority, company policy, and recoverability that automatic checks cannot
observe. Each item's Why compares the boundary that `tools/doctor.py` cannot decide with the instance declaration
in `system/instance-rules.md`. Hook and command counts are point-in-time wiring checks, not policy themselves.
