# Checklist (human-only checks)

This list holds only policy decisions and live-session checks that `tools/doctor.py` cannot automate. On a
company machine, complete section A before running `git clone`; complete sections B through E right after
setup finishes, and section F during your first week.

## A. Company policy (check before cloning on a company machine)

- [ ] **May you clone an external repository onto this company machine?** Check IT policy. If not, use a mirror on
  the company Git host or transfer an archive instead.
- [ ] **Are project hooks allowed?** State injection runs from this repository's project-level hook settings
  (`.claude/settings.json`, `.codex/hooks.json`, `.agents/hooks.json`). A Mac managed by MDM may block project hooks
  or require approval. If they are blocked, state is not injected: you can fall back to
  `python3 tools/now.py context` and reading by hand, but that brings back the discipline this kit is meant to
  remove. Open Claude Code at the repository root so `$CLAUDE_PROJECT_DIR` points to this folder.
- [ ] **May company material be sent to external models?** Confirm the scope of approval for each runtime you use
  (Claude Code, Codex, Antigravity). Do not put data outside that scope in this workspace.
- [ ] **What may be pushed from this machine, and where?** The kit does not decide that. Its commit and push
  checks only keep `_private/`, `instance/` and `state/` out of a commit, and a private path out of a push;
  any other file you track here goes wherever your Git account may push. That is the company's policy and your
  account's permissions.

## B. Data boundary

- [ ] **If material that belongs to someone else comes into this folder, does `instance/rules.md` say where it
  lands and what must never leave?** Company material is the usual case. Until such material comes in, the file
  can stay as the template. No tool reads these declarations; they are for you and the agent.

## C. Live hooks (what doctor cannot verify)

Doctor runs the hook commands in a temporary installation and checks what they print and write. Its row
`hooks · PreCompact fired in a real session` passes once a journal holds a recorded compaction event, which
shows that the compaction step ran here but not which runtime started it; the row does not apply until the
first Claude Code session, and warns once the journal's first line is more than 14 days old with no compaction
on record. Doctor cannot see whether a runtime fired the session-start hook in a live session and whether its
output reached the model. These checks close that gap.

- [ ] **Does session start inject the state?** Open a new session and ask exactly:

  > Quote the newest line under "Recent decisions and phases" without opening any file.

  Compare the answer with the newest decision row in `state/journal-<month>.md`. If it matches and no file was read,
  injection works. If the model reads a file or quotes a different line, it does not.
- [ ] **Did you approve each runtime's trust prompt?** Codex's "Trust all" on the hooks review and Antigravity's
  folder trust ([SETUP.md step 3](../SETUP.md#3-run-doctor-and-arm-your-runtime)). Launch `codex` once and check
  whether the prompt appears.
- [ ] **Does Codex follow `AGENTS.md`?** Give it one real task and check that the answer follows the seven rules,
  including the boundary that a person sends, commits and pushes, and a report that answers in its first two
  sentences.

## D. First session sanity

- [ ] Does every folder in `system/skills/` appear as a skill and a slash command in Claude Code? In Antigravity,
  do the same skills appear from `.agents/skills/`?

## E. Backup and irreversible commands

Git ignores your data, and nothing backs it up: your files under `instance/`, the journals and pages under `state/`,
and the ledgers under `_private/` exist only on this machine.

- [ ] Is this workspace inside a backup location, such as Time Machine or a company backup?
- [ ] If not, have you arranged a separate backup?
- [ ] Should Git keep folders of your own here, for a private remote of yours? List them below the marker at the
      end of `.gitignore`, one `!/folder/` a line; everything else you add stays outside Git.
- [ ] **Will you never run `git clean -xdf` here?** It deletes every file Git does not track, and here that is
  everything of yours: your own notes and folders, and all of `instance/`, `state/` and `_private/`.

## F. Within the first week

- [ ] Register one real track under `tracks` in `instance/config.json`.
- [ ] When a topic lasts several days, give it one dossier under `threads`.
- [ ] After the first compaction, does the first answer still know the current state? If not, the hook is not
  running: go back to the first item of section C.
