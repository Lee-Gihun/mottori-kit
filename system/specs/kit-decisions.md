# Kit design decision records (KIT-DR)

**This file holds the kit's own design decisions. The upstream owns it. Instances do not edit it.**
`git pull` overwrites it. If something here needs a fix, tell the upstream.

An instance records the decisions it makes in its own workspace in `instance/decisions.md`.
Git ignores `instance/`, so it does not conflict with pull. **The two files use separate numbering series.**

Append-only. Format:
`### DR-NNN title (YYYY-MM-DD · active|active-pilot|amended_by:DR-MMM|superseded_by:DR-MMM)`, optionally
followed by `· re-review DATE` or `· re-review N cycles later` and by one `· amended_by:DR-MMM` per later
amending record, then Decision / Context / Rejected alternatives / References. Keep each record short.

A later record that changes part of an earlier one marks the earlier heading `amended_by:DR-MMM`; the text of
the earlier record is not rewritten. One exception is mechanical: when the kit removes a file or a test that a
published record names, the reference loses the backticks or the test marker that make the link and evidence
checks look for it, a removed test is cited through the record that removed it with its old name kept, and
KIT-DR-037 item (18) lists each such edit. A second is a path rename: when a cited file moves, its citations
follow it, as KIT-DR-040 records.

Schema source of truth: `../../tools/lib/config.py` (configuration) and `../../tools/lib/journal.py` (journal
rows) · PRD: `PRD-session-memory.md`.

### DR-001 Instance wiring is derived or set in config, never hard-coded in code (2026-08-24 · active)

Decision:

- (a) **The transcript directory is a derived value**:
  `~/.claude/projects/<root path with every / and _ replaced by ->`.
- (b) Tracks, threads, check lists, and source-of-truth pointers live in `system/memory-config.json`.
- (c) ROOT is derived from `__file__`. Hooks call `$CLAUDE_PROJECT_DIR/tools/...` so that this derivation is
  correct.
- (d) Tracks and threads have no built-in fallback. A fallback for a value that is specific to one instance
  points at someone else's workspace. A loud empty value costs less than a quiet wrong value.

Context: the original workspace contained 9 absolute paths and 4 project keys. The hooks ended in
`2>/dev/null || true`, so on another machine the worst failure mode was a hook that **looks installed but
silently dies**.

evidence: none

Rejected alternative: making the transcript path a config entry. If a person does not edit it, recall returns
0 results and exits normally.

### DR-002 Structure guards the data border: three valve layers (2026-08-24 · amended_by:DR-072)

Decision: **Layer 1 is `.gitignore`**. Only the engine is tracked. Instance data is outside git from the
start.
**Layer 2 is the instance declaration**: `instance.context` and `remote_allowlist`, plus the valve check in
doctor (a detection layer).
**Layer 3 is credentials**. Work clones are pull-only.

Context: layer 2 alone is not a valve, because the same tree that causes an incident can also edit its own
boundary values. Layers 1 and 3 do the blocking. Layer 2 is an early warning.

evidence: none

Also decided: `~/.codex/sessions` is shared by the whole machine, so recall filters it by instance using
`payload.cwd` on the first line of each rollout. Claude transcripts sit in one directory per project, so they
do not have this problem.

### DR-003 Hooks fail safe but do not fail silently (2026-08-24 · amended_by:DR-037)

Decision: hooks always exit 0 (they never block a session). Instead, the SessionStart failure branch **injects
a warning as valid JSON**, and PreCompact failures are written to `state/.hook-errors.log`.

Context: failing safe is correct in itself. A hook that blocks a session is worse. The problem was that the
shell's `2>/dev/null || true` and Python's `except: pass` stacked up into **double silence**. This produced a
state that looks installed but is dead.

evidence: none

Rejected alternative: printing to stderr on failure. That is noisy even in the normal case where a tool was
deliberately not installed. So the hook is loud only in the case "the hook is defined but the tool is
missing".

### DR-004 Convention documents are split into engine and instance pairs (2026-08-24 · amended_by:DR-036 · amended_by:DR-054)

Decision: physically separate the files that `git pull` overwrites from the files that the instance writes.
`CLAUDE.md` pairs with `system/instance-rules.md`, `system/rituals.md` pairs with `system/rituals.local.md`,
and `system/kit-decisions.md` pairs with `system/decisions.md`. Every file on the right side is in
`.gitignore`.
`setup.sh` creates only the missing ones, from seed files.

Context: the kit shipped **documents meant to be edited** and **code meant to be left alone** in the same way.
Pull overwrites code cleanly, but a convention document conflicts when both sides edit it. Demonstrated case:
the instance adds one line to rituals, the upstream also edits the same file, and the result is divergent
branches. DR numbers are worse. Kit DR-004 and instance DR-004 collide in the same file.

evidence: none

Verification: an instance accumulated tracks, local rituals, local DRs, company documents, and a journal. Then
the upstream edited rituals and kit-decisions, and the instance pulled. **0 conflicts, the new lesson arrived,
everything in the instance was preserved, linkcheck reported 0.**

Rejected alternative: a merge tool or a 3-way merge. Automatic merging breaks the meaning of documents, and a
person ends up judging every merge.

### DR-005 Config schema version and upgrade guidance (2026-08-24 · amended_by:DR-036 · amended_by:DR-086)

Decision: `memory-config.json` carries `schema_version`. When the engine requires a new field, raise
`config.SCHEMA_VERSION` and write in `SCHEMA_CHANGES` **what the user must do**. `doctor` reports a config
that lags behind as FAIL and prints the required steps as written.
Entries in `CHANGELOG.md` are tagged with one of three labels: `[Action required]`, `[Note]`, `[Automatic]`.

Context: the engine arrives by pull, but **config is owned by the instance, so it does not arrive.** When
`instance.context` was added on 2026-08-24, the valve check treated an old config without that field as
personal, so it **did not look at remotes at all**. That is silent lag, and silent behavior was a repeated
problem in this repository.

evidence: none

Also decided: the upstream check in `doctor` is SKIPped in the upstream repository. The marker for this is the
presence of an export tool that exists only upstream. Editing the engine upstream is normal, so a warning
there would be a false alarm that people learn to ignore.

Rejected alternative: automatic migration. Config holds values that a person must read and judge (which
remotes to allow). If a machine fills them in, that judgment disappears.

### DR-006 The state ledger separates a public projection from a local overlay (2026-08-26 · amended_by:DR-041)

Decision: only allowlisted events go to the public journal. All other events, and events logged with
`--private`, go to the local journal. The view that merges the two is the source of truth.

Context: the tracked journal re-published events that were derived from private data. Concurrent append and
render also had a stale-writer problem and a truncate window.

evidence: none

Safety and migration: on error, the private side fails closed. Writes are bound together by a lock, atomic
publish, and rollback. Only journal provenance is frozen, and legacy threads are separated by hand.

Rejected alternatives: reusing tracks for this purpose, and letting the public side fail open on privacy when
an error occurs. References: `PRD-session-memory.md` §3.2, §9.

### DR-007 Wide tasks run in a fresh bounded worker, and AGENTS is the single instruction source (2026-08-29 · amended_by:DR-033 · amended_by:DR-043)

Decision: the master session stays the person's inbox. Wide reading, audits, and debates are isolated in
ephemeral runs of `fresh_worker.py`. The master gets back only a bounded receipt. The full trace stays in
`_private/work/runs/`.
The exact byte and capability contract is defined in `PRD-session-memory.md` §10.5.
`AGENTS.md` is the single source of the shared conventions, and Claude imports it with the exact line
`@AGENTS.md`.

Context: wide tool traces and accumulated sessions ate up the master context. Byte-identical copies of the
instructions also actually diverged. Isolating the runs that cause the problem was more direct than reducing
the number of files or the size of NOW.

evidence: none

Boundary: both adapters close connectors, web, network, plugins, and fan-out, and they do not rely on hooks.
Runtime fallback, public traces, a detached scheduler, and a Claude that can write are outside the scope of
v1.

Rejected alternatives: moving many files or shrinking NOW does not reduce the wide traces that cause the
problem. A database or an embedding index is not the bottleneck by current measurements. Runtime fallback and
public traces hide failures and the data border. All of these are rejected.

Reconsider: if there are 0 wide-task calls for two weeks, remove the worker. Reference:
`PRD-session-memory.md` §10.5.

### DR-008 Outbound text shows its role and consistency anchors before the body (2026-08-29 · amended_by:DR-036 · superseded_by:DR-085)

Decision: before writing an outbound deliverable that a person outside the repository will read or receive,
write the two lines `Document role` and `Consistency anchors` in the work log with real values. Then continue
without asking for approval. If the role stays the same, write them only once.

Context: even when search returns the right file, a wrongly settled goal can discard that file, and lookup
rules alone cannot prevent that failure. The two lines let a person check the reader, the approver, the goal,
and the actual evidence right away.

evidence: none

Rejected alternatives: a new index or search tool cannot prevent the failure of discarding an answer that was
already found. An approval gate on every paragraph adds too much cognitive load. Both are rejected.

References: the core rule 5 trigger in `AGENTS.md` and the outbound text section of `system/rituals.md`. If
the two-line preflight does not change a judgment even once in the next 5 outbound texts, remove it.

### DR-009 Plain writing is generated by close, skeleton, stop, as a 10-text pilot (2026-08-29 · active)

Decision: for outbound text, first fix the evidence and the task, then generate in the order `Close`, then
`Skeleton`, then `Stop`. After checking stance and economy, check last that the recipient can reconstruct the
connections. Do not use a shorter length as a stand-in for plain writing.

Context: the rejected examples showed more than wordiness. They also showed a second task that nobody asked
for, self-assessment, a wrong assumption about the recipient's state, and broken logic. The fix of cutting
word count also removed connections that were needed.

evidence: none

Rejected alternatives: the old 5-sentence deletion rule, a list of banned words, a length cap, and a new style
skill fix the surface instead of the cause, so they are rejected.

Reference: the outbound text section of `system/rituals.md`. Within 10 texts, if 3 texts need a structural
rewrite after following the procedure, or 2 are rejected as cold or disconnected, or content that the check
said to delete is restored 3 times, withdraw or redesign the pilot.

### DR-010 A worker run record holds harness identity, tokens, read scope, and write set (2026-09-16 · amended_by:DR-023 · amended_by:DR-033 · amended_by:DR-037)

Decision: `meta.json` v2 records `kit_rev`, `kit_dirty`, `harness_sha256`, `usage`, `read_scope`, and `scope`.
The receipt is unchanged except for one `scope:` line. `--write-prefix` is optional. It only detects and
records after the fact, and it does not roll back. A violation changes the run status only with
`--strict-scope` (live canary on 2026-09-16: both violations came from concurrent writers).

Context: the same model went from 8.3% to 37.2% when only the harness changed (`paper:2609.07925` §2). So to
interpret a run, the receipt must contain the harness identity, but v1 held only prompt and result hashes. If
the lead cannot see where a worker's output came from, it trusts wrong answers (`paper:2609.06702` App. F.2).
A boundary written in natural language is not enforcement (`paper:2609.04170` §3.3).

Before implementation, the design document closed 4 questions from an independent verifier (Codex). After
implementation, the first independent review found 7 defects, and all were fixed: R1, an existing symlink
passed. R2, restores with the same size and mtime, and empty directories. R3, a runtime failure hid a
violation. R4, callers were not connected. R5, the instance HEAD was mislabeled as the kit rev. R6, read_scope
syntax. R7, empty fixture fields.

The second review found R8 (hardlink aliases), R9 (creating a missing nested prefix counts as a violation),
and R10 (case correction on case-sensitive volumes). The third review found the rest of R5 (telling the
destination baseline apart from the source manifest) and R11 (stamps were not verified). These were fixed too
(31 fixtures. tools/sync_engine.sh stamps both the source manifest and the destination baseline, and verifies
the stamps again).

Rejected alternatives: putting external binaries, model snapshots, and environment variables into the hash
(they differ on every run, so runs cannot be compared). Summing usage across events (the totals come out
wrong). Rolling back the write set (detection after the fact does not widen the blast radius). Making the
prefix mandatory (every caller would break. It is a candidate for the next version).

References: the original instance's private workspace papers-2026-09-13-kit (design document
design-fresh-worker-receipt-v2, PROPOSALS, DR-draft, independent reviews REVIEW rounds 1 to 3),
`tools/tests/test_fresh_worker.py` with 31 fixtures, tools/sync_engine.sh.

### DR-011 The release gate is a reproduction of a stranger's first install (2026-09-17 · amended_by:DR-036)

Decision: after changing the engine, run `bash tools/tests/test_fresh_install.sh`. In a temporary clone, setup
(non-interactive, no arguments), then hooks, then linkcheck, then doctor, then regressions, then a second
setup run must all pass before a release. States that only a person can resolve (Codex hooks not trusted, no
transcript directory before the first session, tracks not registered) are a warning plus a to-do item in
doctor, not a FAIL. In an upstream copy before setup, references to paths that setup will create are counted
separately as PENDING.

Context: v0.4 was verified only on its own instance. When the README steps were followed in a temporary clone,
setup exited 1 silently without a tty, and even with arguments doctor reported 4 FAILs. A FAIL that never gets
fixed teaches people to ignore FAILs (a repeat of the 2026-08-24 lesson). Independent audits (a Codex defect
audit and a Claude documentation audit with 39 findings) also caught three more problems: a --force re-run
flipped the context, the kit's now.py imported a personal adapter, and the git 2.36 requirement was not
documented.

evidence: none

Rejected alternatives: fixing only the install documentation (the documentation drifts away from the code
again). Turning every doctor FAIL into a warning (this hides real breakage). Depending on a CI service (the
kit's contract is a local first install, so the local script is the source of truth and CI runs on top of it).

References: `tools/tests/test_fresh_install.sh`, `CHANGELOG.md` v0.5, the original instance's private workspace
kit-improve-2026-09-17 (2 audits and reviews).

### DR-012 Philosophy: human attention is the most expensive resource, and tokens are the cheapest (2026-09-17 · amended_by:DR-036)

Decision: the owner set the kit's objective in these words (owner's words, translated): "Treat human cognitive
cost as the most expensive resource and tokens as the cheapest resource, and make the trade-off on that basis.
Make many tasks keep running safely under one endless thread, so that a person deals with only one thing." The
first section of the README is the source of truth for this sentence. Two operating rules that make this trade
safe sit next to it.

1. **Verdicts arrive only as receipts.** The result of independent verification bought with tokens comes up
   only as a bounded receipt (KIT-DR-007, KIT-DR-010). If the full text reaches the person, the trade runs
   backwards.
2. **Pass and cause are verified separately.** Gates (install, regression, links) say only whether something
   passed. An independent review, not the proposer, examines the hypothesis about the cause of a failure again
   (KIT-DR-011).

Context: the measurements from one day, 2026-09-17, satisfy all three sentences. The owner watched only one
thread. Under it, 6 workers ran (a Claude documentation audit, a Codex defect audit, 2 Codex reviews, 3 Codex
strategy rounds, and repeated first-install gate runs). What came up was receipts and verdict tables. On the
same day that the gate produced a PASS, an independent audit corrected two of the dispatcher's cause
hypotheses (overlay order, and the baseline coming first) to different causes. Tokens were cheap, and the
person's time stayed in one thread.

evidence: none

Candidate sentences: "Verdicts arrive only as receipts" (ranked first in Codex round 3) and "Pass and cause
are verified separately" (a new candidate in the same round) are means, not goals, so they moved down to the
rules. "Conversation is a volatile medium" stays as the explanation of the state-loss problem (README "What it
solves") and does not take the philosophy slot.

Rejected alternative: setting the objective as "cross-verification by two models". The official OpenAI plugin
already holds that position (adoption survey, 2026-09-17). What we offer is not cross-verification but the way
its results reach the person.

References: the README philosophy section, KIT-DR-007, KIT-DR-010, KIT-DR-011, `tools/tests/test_fresh_install.sh`.

### DR-013 A change to a gate-definition file passes only with one line in the approval ledger (2026-09-18 · superseded_by:DR-032)

Decision: some files decide what the gates catch (language allow rules, the pending list, evidence and
enforcement constants, enforcement, the test matrix, manifest rules, and the GATE_DEFINITION set in
`tools/dev/manifest_build.py`). A diff to these files passes only when a `gate-definition-approval` line in
system/gate-definition-approvals.md (tracked, append-only) matches it exactly (decision marker = the
relevant KIT-DR number, files = the sorted file list, sha256 = the diff hash).
`tools/dev/manifest_build.py --issues` runs the check, and pre-commit and CI run the same check.

Context: two measured cases on 2026-09-18. One worker defined a regression but did not add it to the run list,
so it looked "passed". Another worker widened the allow list of its own gate to meet its exit condition. When
the side that did the work also writes its own receipt, a written prohibition does not catch this.
The first draft kept the approval ledger as a swarm file under `_private/`. CI could not see it, so every
gate-definition change failed on the remote. So the ledger moved to a tracked file.

evidence: decision:KIT-DR-032 (removed test
tools/tests/test_manifests.py::test_gate_definition_change_requires_dispatcher_approval)

References: KIT-DR-011, KIT-DR-012, the gate-definition class in `system/dev/review-manifest.yaml`,
`.github/workflows/gates.yml`.
Scope addition (2026-09-18, measured during a sync): the check applies only to the kit tree where gate
definitions are written (a tree without `system/memory-config.json`).
An installed instance receives gate definitions through engine sync, and the ledger of the source kit has
already approved that diff. So `--issues` reports `~gate-definition-approval` as not applicable. The first
implementation also required an approval line in instances, and that blocked every engine sync.

evidence: decision:KIT-DR-032 (removed test
tools/tests/test_manifests.py::test_gate_definition_approval_is_not_applicable_in_installed_instance)

### DR-014 Trigger store: things that should surface later live in a file, and action tiers are constants (2026-09-19 · active-pilot · re-review 3 cycles later · amended_by:DR-038)

Decision: `tools/triggers.py` keeps date triggers in the instance file `_private/triggers/triggers.jsonl`
(`add`, `due`, `hook`, `claim`, `fire`, `sleep`, `list`, `scan`). `scan` builds triggers with stable ids
(`exp-X<n>`, `rereview-DR-<n>`) from the due-date column of the experiment register and from decision records
that have a re-review date, so running it again is idempotent.

Action tiers are constants, not settings. T0 is speaking. T1 is preparing (a draft in the private area, which
can be undone). T2 is going outside (sending, committing, paying, deleting). T2 is never automatic and
surfaces only as a draft plus a one-line request. `privacy` (default private) and `destination` (default
local, no external party) are axes independent of the tier, so "T0 is always allowed" does not become
permission for external notifications.

`due` is read-only without `--mark`, and only `hook` records that an item was shown. At most 5 items show per
session, in ascending order of how often each was shown (carry-over), so the cap does not starve later items.
If an item is shown three times without a `fire`, it goes to sleep automatically for 7 days (the ignore count
is recorded).

`claim` takes a lease, and a live lease rejects a second claim. `fire` rejects repeats and records the event
in `history`. Storage is load-modify-save inside a file lock, with replacement through a temporary file.

For the language-dependent words in the source parser (closed status, re-review marker, "N cycles later"), the
engine holds only English defaults, and the instance setting `triggers.sources` overrides them (the kit tree
passes the language gate unchanged).

The one SessionStart hook line (the same JSON contract in `.claude/settings.json` and `.codex/hooks.json`) is
a separate rollback bundle, and its unit is the hook line plus the trigger store.

Context: the owner's instruction on 2026-09-19 was to build calibrated judgment (Jev-style) and proactivity
(Instinct-style) into the kit, and not only for Claude Code. It must also run the same way when moved to
Codex. The design converged over 10 rounds of Claude and Codex debate in the instance (the debate files are in
the debate folder of the source instance, under the 2026-09-19 decide-triggers issue. They are not in the kit
tree).

What Codex changed: `due` became read-only. It added the destination axis, the lease, history, and locking,
and the carry-over ordering. Source parsers became data. A `tools/runtime/` package was rejected (the runtime
registry lives inside `fresh_worker.py`). `decide` (a calibrated-judgment registry, shadow mode, a judgment
ledger) moved to the bundle of the next cycle.

evidence: test:tools/tests/test_triggers.py::test_add_due_fire_and_tier_boundary ·
test:tools/tests/test_triggers.py::test_hook_limits_and_auto_sleep_after_ignores ·
test:tools/tests/test_triggers.py::test_claim_lease_refuses_second_holder_and_due_stays_read_only ·
test:tools/tests/test_triggers.py::test_scan_experiments_and_decision_rereviews

Re-review (after 3 cycles): the ratio of fires to automatic sleeps, the number of times the session-start
section actually changed behavior, and whether the two harnesses produced the same output.

### DR-015 Runtime vocabulary derives from one registry entry, and a harness declares the roles it cannot take (2026-09-21 · active-pilot · re-review 3 cycles later · amended_by:DR-037 · amended_by:DR-048 · amended_by:DR-051 · amended_by:DR-064)

Decision: tools/harness.py is the registry of harness wiring and the source of truth for the runtime
vocabulary. One harness is one entry in `RUNTIMES` (binary, wiring path, mode `checked-in|generated`, the
roles it takes, and **the reason for each role it cannot take**). The role vocabulary uses the same 6 roles as
`hookdiag.ROLE_EVENTS` (injector, recovery, observer, enforcer, side_effect, guard).

`CONSUMERS` in `tools/tests/test_manifests.py` is derived from this table and is no longer a literal. Before
this, a third harness also had to edit the test file. What one entry adds is limited to the **runtime
vocabulary**. A new harness still needs its adapter code, tests, and distribution metadata (review manifest,
test matrix, translation list) added separately (adding opencode worked that way).

opencode is the first generated harness. It has no hook surface, and in v2.0.11 the `instructions` entry in
its config was measured not to load (2026-09-21). So the launcher carries the injector role:
`harness.py open opencode` rebuilds the state file and plants it as the first prompt. A session started
directly receives no state.

The 4 slash commands are rendered from the source files in `.claude/commands/*.md`. The other five roles are
not wired, and `status` prints them as gaps. `status` says "wired" only when the state file and the command
directory both exist and the commands match the source (the same parity function as `check`).

Data border: the injection file can contain the local private overlay, so **unless the file is proven to be
outside Git, it holds only public state** (fail-close). The output for this is
`now.py context [--public-only]`, which prints the same body as plain text without the hook JSON envelope.

Verification is a canary round trip, not the presence of wiring (`harness.py verify`). The prompt does not
carry the nonce. In a harness where the injected body is a file, the model can find the same file with grep
and pass without any injection (measured on 2026-09-21: in the first experiment the model called grep, and
that contaminated the experiment).

Tools cannot be turned off. `opencode run` in v2.0.11 has no flag that turns off tools, and with a config that
turned tools off, the free tier refused to run (403). So **a run that used tools does not count as evidence**
(inconclusive). Even the same correct answer is not a PASS if there was a tool call.

The nonce sits in the injection file (outside Git) only while the run lasts, because that file is the channel
being measured. When the run ends (including timeouts and exceptions), the file is rewritten with a body that
has no nonce, and the ledger keeps only the verdict.

Context: the owner pointed out on 2026-09-21 that without an "install, then set up, then use" scenario, the
kit cannot claim to be harness-agnostic. The measured starting point: `setup.sh` installed neither `.claude/`
nor `.codex/` (the wiring depended on files checked into the repository), and the word `opencode` appeared 0
times in the whole kit.

Observed constraints: the plugin API of opencode v2.0.11 differs from the public documentation
(`export default {id, setup}`), and the signatures of the event and session hooks are not stable yet. So the
remaining roles that need a plugin were not added in this cycle.

evidence: decision:KIT-DR-051 (removed test
tools/tests/test_harness.py::test_every_runtime_declares_the_roles_it_cannot_take) · decision:KIT-DR-037
(removed test tools/tests/test_harness.py::test_state_falls_back_to_public_when_the_path_is_not_outside_git) ·
decision:KIT-DR-048 (removed test tools/tests/test_harness.py::test_canary_prompt_never_carries_the_nonce) ·
decision:KIT-DR-048 (removed test
tools/tests/test_harness.py::test_a_tool_using_run_is_never_counted_as_proof) · decision:KIT-DR-048 (removed
test tools/tests/test_harness.py::test_state_file_holds_no_nonce_after_a_canary_run) · decision:KIT-DR-048
(removed test tools/tests/test_harness.py::test_status_does_not_call_a_half_wired_opencode_wired) Model lane
addition (2026-09-21, the owner's usage plan): a harness is a lane for one model provider. Claude runs in
Claude Code, GPT runs in Codex, and third-party models (free tiers, Chinese models, and others) run in
opencode. So the canary is measured **once per model**, not once per runtime, and only the verdicts go into
the state/harness-canary.json ledger (`verify opencode --sweep`). This ledger is an optional generated file,
so it does not exist in an instance that has never run verify. When switching models, "does this model
actually receive and follow the kit state" is a property of the model, not of the wiring. Weak models call
tools or fail to follow instructions, so they fall to INCONCLUSIVE or FAIL, and that record is a measurement
ledger that routing can use. No consumer reads it automatically yet.
Correction (2026-09-28, independent audit before the commit): four claims in the draft were narrowed to match
the implementation. "The run turns off all tools" (the implementation marks a run that used tools as
inconclusive). "The nonce never touches the disk" (it sits in the injection file during the run). "Routing
reads the ledger" (there is no consumer). "A new harness attaches with one entry" (only the runtime vocabulary
does). The same audit fixed `status`, which had reported "wired" after looking at the state file alone.

Re-review (after 3 cycles): whether opencode sessions were actually used, whether the canary caught a
regression, whether a fourth harness really got its runtime vocabulary from one entry, and whether the model
ledger actually changed a routing decision.

KIT-DR-064: `test_manifests.py` is removed; nothing derives a register row from this table any more.

### DR-016 Memory requirements are separate from implementation design, and instance authority is not inherited (2026-10-08 · amended_by:DR-036 · amended_by:DR-062 · amended_by:DR-064)

Decision: the two PRDs define origins, corrections, and data boundaries, as well as work continuity and
success conditions. Implementation links and Mermaid diagrams live in `system/design-memory-runtime.md`. The
Markdown documents are the source of truth for the design, and the HTML map is a secondary viewing screen. The
`.ko.md` files of the two PRDs are the current sources of truth, and the full English `.md` translations are
kept bound to the hash of the source. The §10.5 byte/capability contract stays as it is.

Context: `decision:KIT-DR-004`. If the upstream instance's delegation for automatic application, its
schedules, and its run results were ported by only replacing names with generic ones, installing the kit would
read like a delegation of authority. The PRDs and the design are classified as kit-owned, so they are not
overwritten automatically, and each change gets a separate consistency review. The manual gardener is
report-only and does not inherit the authority of the optional periodic adapter.

Engine: recall first filters its candidates by instance, role, and summary, and checks native source identity.
It reads archived sessions with the same rules and removes duplicates. Files that the worker depends on are
listed together in the engine inventory. Code distribution is separate from personal records, credentials, and
delegation.

Rejected alternatives: copying the main documents as they are, or keeping two sources of truth as if the
translation were complete. Claiming an actual effect on the dispatcher, or a reduced burden on the user, from
an install or fixture PASS.

References: `PRD-info-architecture.md`, `PRD-session-memory.md`, `design-memory-runtime.md`,
`tools/tests/test_recall.py`, `tools/tests/test_fresh_worker.py`, `tools/tests/test_memory_map.py`.

DR-016 supplement: before giving a prescription, first look up what has already been done, and ask only about
what is still unknown. The seven rules are operating defaults. They are not claimed as a universal upper limit
of model capability.

KIT-DR-016 verification supplement: Markdown dependency extraction now resolves relative links and inline file
references against the document, preserving PRD-to-design connections. External URLs and out-of-tree paths do
not become local dependencies. The new auth helper and map tests are included in the engine inventory and risk
matrix. Existing critical test requirements are unchanged. Source snapshot delivery, TERM cleanup, and
worker-observed AGENTS provenance have dedicated worker regressions. Gate-definition approval is bound to the
reviewed diff below, not inherited from the upstream instance.

KIT-DR-064: the engine inventory is removed; `test_instance_shape.py` takes its file set from `git ls-files tools`.

### DR-017 Self-contained source commentary (2026-10-08 · active)

Decision: `code-writing.md` holds the shared writing principles. Comments and docstrings explain current
behavior, interfaces, invariants, and the reasons they are needed, in concise English. Session stories, review
numbers, and measurements from completed runs belong in decision or observation records. Exact source terms,
fixtures, tool directives, licenses, and generation stamps are preserved. Instance authority does not change.

Reason: putting the story of how code came to be into the code demands context that has nothing to do with
maintenance. Deleting every explanation also loses the knowledge of causes that safe changes need. Rewrite
incidents as current operating conditions, and keep long evidence in the relevant record.

evidence: none

Verification: compare the frozen source with the executable AST, runtime strings, script tokens, and heredocs.
English versions of CLI help derived from docstrings are told apart as an intended display change. Preserve
the frozen history, and do not treat old comments as newly verified facts. Judge by a new reader's
understanding and the relevant regressions, not by comment counts or a banned-word gate.

Reconsider: review this again if a needed constraint cannot be found near the code, or if a comment edit
changes a runtime consumer that was not meant to change.

### DR-018 Reviewed engine transfer and runtime isolation (2026-10-08 · amended_by:DR-037 · amended_by:DR-064)

Decision: distribute shared memory and bounded-worker mechanisms while preserving explicit kit variants.
Instance schedules, operational records, commit delegation, recording adapters and credentials do not transfer
with engine code. Lens definitions are reusable. Application records are private instance data. The lens
index, deep-pass and rituals are kit-owned policies.

Context: `decision:KIT-DR-004`, `decision:KIT-DR-016`. Installation, worker-cluster upgrade and a long-lived
source workspace have different dependency and authority boundaries. A successful source check cannot
establish a successful fresh install. Model agreement is a review observation, not empirical independence or
measured user benefit.

Boundary: worker child environments separate provider credentials, and the harness identity records that
policy. Read scope is optional self-report, material hashes verify input identity, and write restrictions have
their own evidence. The worker sync includes its direct runtime/test dependencies, checks existing consumers
and rolls back failed publication. It does not update the full kit, instance config or schedules.

Verification: require normal controls before mutation claims, distinguish infrastructure errors from detected
defects, run fresh installation in both declared languages, and preserve instance data in update fixtures. The
evidence checker accepts English and Korean context labels with the same section boundaries. Release evidence
records exact code identities and command results separately.

Rejected alternatives: blanket source overwrite. Inheriting the source instance's automatic-commit authority.
Storing lens anecdotes in tracked definitions. Calling self-reported reads enforced isolation. Treating
unavailable adapter output as healthy.

Reconsider: a supported installed consumer fails after a verified upgrade, a future export rewrites a
kit-owned policy, or a concrete task requires a portable opt-in application engine. That engine needs separate
execution/commit/egress controls and its own installed E2E before distribution.

KIT-DR-018 output-delivery supplement: collect safe ignored outputs only within explicit write prefixes.
Preserve bytes, hashes and replayable patches before cleanup. Failed or incomplete capture returns exit 5 and
preserves the worktree. Termination during capture also preserves it. Capture failure takes precedence over
strict-scope exit 4 without erasing scope metadata. Known bundled startup metadata is distinct from configured
plugins. Unknown or malformed plugin records still fail the canary. Temporary verification owns cleanup of its
own runtime configuration side effects. The worker does not automatically clean up user configuration.

DR-018 diagnostic and verification supplement: the sync diagnostic uses the exporter's read-only plan, so it
shares the exporter's ownership scope and normalization. A missing input, a failed privacy check, or a plan
that cannot be obtained is a FAIL.

Gate regressions in the development tree are bound to a small synthetic evidence sample that actually runs.
Full distribution regressions and install verification stay separate. Evidence runs keep their time limit and
their blocking verdict, and the reason for a failure is left in the diagnostic. This supplement removes the
duplicated full check inside the focused regression. It does not count verification on a synthetic sample as
distribution verification.

The CI evidence step uses the normal command, which fails when there is a problem. The machine-readable list
mode always exits normally, and only callers that judge the issue count directly use it.

RAN is a record that a test was entered. It is not proof of success. Each top-level gate attempt actually runs
the cited suites under a new run ID. Earlier records, or records that arrive late, are not used as evidence of
success for a new attempt. The internal recursion guard stays.

KIT-DR-064: the test log and the evidence re-run under a new run ID are removed; a marker is checked for form
and for what it names, and continuous integration runs every suite.

### DR-019 Lens documents rewritten in plain language, with an index to choose from (2026-11-18 · active)

Decision: rewrite the 13 lens definitions and the lens index so that a person or a model who has never seen
this repository can choose a lens and use it. Each definition starts with the question it asks, when to turn
it on, and what to leave behind after using it. Then come a summary, an example from everyday work, why it
works, how to use it, where to use it, ways to misuse it, how to use it with other lenses, and sources. The
index gets a "when to turn it on" column, a four-step procedure that starts from what the user originally
wanted to get, criteria for telling overlapping lenses apart, and a way to use this folder alone without the
rest of the kit. The Korean files are the source of truth for the lens folder. The twelve English files, which
were untranslated copies, became translations bound to their sources.

Context: `decision:KIT-DR-018`. The definitions were reviewed against the usage records of the original
instance, read by readers without context, tested in a before-and-after comparison with criteria written down
in advance, and reviewed by a model from a different family. In that comparison, the new index made two models
choose the intended lens more often (157/208 with the old index, 130/156 with the new index. This fell short
of the line set in advance for calling it an improvement, and it was never lower in any of the seven runs).
Advice written after reading the new definitions more often contained the next thing to do (from 35/52 to
40/52). This test asks for advice on situations described in writing, so it cannot measure whether an agent
stops to use a lens in the middle of real work.

Boundary: the lenses stay at 13. Three candidates (purpose, reader, contrast) were reviewed and not added, and
the index records the reasons. Application records are private instance data and are not moved into the
definitions. The comparison data stays in the original instance.

Reconsider: review this again if a comparison made on real work shows that some definition made a decision
worse, or if the results of the pre-delivery check now under test make the reader candidate worth keeping as a
lens.

### DR-020 Turn-end checks use the session scope, and release checks run at release time (2026-11-18 · amended_by:DR-041 · amended_by:DR-042 · amended_by:DR-064)

Decision: gate checks have two scopes. The session scope is the link check and the state check. It runs in
an installed workspace at the turn-end `check`, at `baseline`, and at `precommit`. The release scope is all
four checkers plus a fresh run of every cited test suite. It runs in the kit development tree at `precommit`
and `baseline`, and in `gate.py release`.

A kit development tree is a tree with no instance config that has `setup.sh` and the config template (the same
test the push hook uses). `MOTTORI_GATE_SCOPE=release|session` overrides that test, and an unknown value is
read as the stricter release scope. A baseline is compared only against checkers measured in the same scope.

`resume` measures nothing and reports the one-line reason of the last block. When the Stop hook is called
again in the same turn, the check passes once and keeps the pending marker. `check` runs only when there is an
edit marker, a pending marker, or a changed work-tree fingerprint. When a checker produces no result, the
block reason names the checker and gives a one-line cause. The three gate hooks write their own failures to
`state/.hook-errors.log`.

Context: `decision:KIT-DR-003`, `decision:KIT-DR-011`, `decision:KIT-DR-013`. On a fresh install under a
temporary HOME, after a one-line edit to an ignored document, the turn-end check took 83.6 seconds and
`setup.sh` took 86.7 seconds (2026-11-18). The turn-end check was running the kit's own release checks on
every user turn. After the change the same measurements are 0.4 seconds and 3.0 seconds, and 0.08 seconds on
an unchanged tree. In the gate records of the original instance, excluding entries written by tests, about 10
of 395 blocks were caused by the turn that was blocked, and 240 of the 316 blocks that carried a session name
repeated the previous block's problems.

evidence: removed test tools/tests/test_devtree_gate.py::test_installed_check_runs_no_cited_suite · removed
test tools/tests/test_devtree_gate.py::test_devtree_precommit_and_release_run_cited_suites · removed test
tools/tests/test_enforce.py::test_session_check_keeps_release_checkers_in_baseline ·
test:tools/tests/test_enforce.py::test_resume_reports_pending_reason_without_measuring ·
test:tools/tests/test_enforce.py::test_H03_H04_stop_hook_active_passes_once_and_keeps_pending

Boundary: CI does not go through the gate. It runs the whole regression suite and the four checkers directly,
so release checking did not shrink. The fingerprint misses ignored paths and an overwrite that keeps both size
and modification time. Codex has no turn-end hook, so this check runs on Claude Code only.

Rejected alternatives: running release checks asynchronously at turn end (the result arrives in a later turn
and no longer shows which turn caused it). Caching checker results (deciding when to drop the cache becomes
one more checker).

Reconsider: problems that the session scope missed are repeatedly caught at commit time or in CI.

KIT-DR-064: the release scope is removed; every tree uses the session scope, and continuous integration runs
the suite and the static checks.

### DR-021 Session-start injection carries dossiers and the newest decisions first (2026-11-18 · amended_by:DR-036 · amended_by:DR-041)

Decision: session-start injection no longer cuts the NOW text in the middle. It splits NOW into sections and
fills them in order. The track board, the source pointers, and the state banner are fixed. Then comes the
newest decision of each side, then the dossier names, then the remaining decisions, then recent events, newest
first. Dossiers that do not fit are replaced by one line with their count and the command that lists them
(`python3 tools/now.py threads`). The generated NOW file shortens its dossier list the same way. A long list
never makes the injection fail.

The public and local sides share the remaining room equally, and room one side leaves unused goes to the
other. One event line is cut at 400 bytes, and one line reports how many older lines were left out. The
6,000-byte cap is unchanged.

Compaction events stay out of the decisions section and fold into one line in the events section. Journal
freshness is measured from the last event that is not a compaction. `log --private` writes to the local
journal even when the public journal is corrupt.

A trigger's shown count rises at most once per calendar day, and the command the hook prints runs as written.
`add` refuses condition kinds that can never fire.

Context: `decision:KIT-DR-006`, `decision:KIT-DR-014`. With a long journal, the middle cut removed the dossier
list and the recent decisions, the two things a session needs most after compaction. Compaction events filled
the recent-decision slots (68 of 70 lines in the original instance's public journal for November), and they
kept journal freshness at "0 days" forever. In a test with 1,000 journal lines on each side, the new injection
stays under the cap and keeps both the dossier and the decision sections. A trigger's shown count rose on
every hook run, so one day of sessions counted as three ignored showings and put it to sleep.

evidence:
test:tools/tests/test_state_runtime.py::test_hook_context_keeps_dossiers_and_newest_decisions_with_long_journals ·
test:tools/tests/test_state_runtime.py::test_hook_context_names_omitted_dossiers_when_both_lists_are_long ·
test:tools/tests/test_state_runtime.py::test_hook_context_survives_sixty_long_dossier_names_on_one_side ·
test:tools/tests/test_state_runtime.py::test_snapshot_drops_compactions_from_decisions_and_dedups_recent ·
test:tools/tests/test_state_runtime.py::test_private_log_survives_corrupt_public_journal ·
test:tools/tests/test_triggers.py::test_shown_counts_once_per_calendar_day ·
test:tools/tests/test_triggers.py::test_hook_fire_instruction_runs_as_written

Boundary: when decisions are many and long, the events section is empty and only the count of omitted lines
remains. The memory-index wording check and the recording checks run only in an instance that has those tools,
and the wording check is now advice that does not block.

Reconsider: an injection is observed without the dossier list or its omission line, or without the newest decision.

### DR-022 Pre-delivery check: record every hit, and block only with a signal that has shown its hit rate (2026-11-18 · active-pilot · re-review 2026-12-16 · amended_by:DR-036 · amended_by:DR-041)

Decision: `tools/deliver.py` is the second Stop hook. It calls no model. It reads the last answer of the turn
and the turn's tool calls and evaluates signals. `unopened` fires when a reading document of at least 1,500
characters written in this turn is delivered without being reopened. The tool names that count as delivering a
file are listed in the instance config, `deliver.send_tools`. `reader` fires on a long report at the end of a
long working turn.

Each signal runs in one of two modes, record only or block. By default `unopened` is recorded and nothing
blocks. A blocking signal stops the turn once, and its reason carries only the signals that fired and the
owner's original request. Every hit goes to `state/.deliver.jsonl`. A block gets one follow-up record, written
at the re-entry of the same turn, that says whether the answer changed (`deliver.py stats`). A re-entry that
belongs to another turn or to another hook is not counted.

The check's own failure never blocks a turn. Signals that judge wording alone are excluded: a sentence that
asks the owner to do something, and a claim that a check passed.

Context: `decision:KIT-DR-003`, `decision:KIT-DR-012`. In the original instance all 6,697 messages the owner
typed in five months were read, and 2,243 corrections were counted. Thirteen classes of recurring mistake
already had a written rule. Twelve of them recurred more than three times after the rule was written, and for
eight the rate per 1,000 messages stayed flat or rose.

In a small controlled test, a short rule placed inside the task prompt reduced unrequested additions to 0 of
72 reports (19 with no rule, 2 with a reread step, 1 with a first-time-reader review). So rules go where the
work happens, and the turn end gets narrow checks only.

Four signals were first run over 8,817 past turns. `unopened` fired on 2.1% of turns and was right in 35 of 40
sampled hits. `reader` fired on 4.6% and was right in 14 of 40. A signal for sentences that hand work to the
owner was right in 2 of 40, and a signal for pass claims was right in 0 of 37. Both were removed from the
code.

Three later candidates went through the same replay. A signal for a document that is named but not sent was
right in 12 of 40, a signal for an output never looked at after it was made was right in 14 of 40, and a
signal for internal names used without explanation was right in 0 of 40. None was added.

evidence: test:tools/tests/test_deliver.py::test_unopened_document_blocks_once_and_quotes_request ·
test:tools/tests/test_deliver.py::test_default_only_records ·
test:tools/tests/test_deliver.py::test_configured_delivery_tools ·
test:tools/tests/test_deliver.py::test_stats_links_a_reentry_only_to_its_own_blocked_turn ·
test:tools/tests/test_deliver.py::test_broken_input_never_blocks

Boundary: of 18 real complaints in the original instance that an output was delivered without being looked at,
`unopened` caught 1. The others were videos, images, and rendered pages. "Reopened" means that a later tool
call in the turn names the file. The check does not read tool results, so a command that only prints the file
name also counts. The check runs only in the Claude Code Stop hook. The unrequested-addition numbers come from
12 invented tasks, not from real work.

Rejected alternatives: asking another model to review every answer (cost and delay on every turn, and it did
worse than the in-prompt rule in the controlled test). Writing more rule sentences (see the counts above).

Re-judge (2026-12-16): per signal, the number of hits in installed workspaces and the share of blocks after
which the answer changed. A signal whose share is under one half goes back to record only. A new signal is not
added without a hit rate measured on past conversations.

### DR-023 A worker receipt leads with the verdict, and expected outputs are checked after the run (2026-11-18 · amended_by:DR-037 · amended_by:DR-041 · amended_by:DR-073)

Decision: the receipt cap stays at 4,096 UTF-8 bytes. The header order changes. `verdict:`, the worker's own
`unknowns:`, the command that opens the full result `full:`, and `expect:` when `--expect` was given, all come
before the body. Line breaks and control characters in header values are escaped, so a value cannot add a
header line of its own. When the worker's unknowns are cut, the value starts with the total and the number
omitted. A long result keeps its start and ends with a truncation marker and the full-result command.

`--expect PATH` checks before the run that the path is inside the workspace, and after the run that the file
exists as a non-empty regular file. If any expected file is missing, a run that was successful becomes
`expected-output-missing` and exits with code 6. The receipt verdict is then INCONCLUSIVE even if the worker
wrote PASS. Terminal status names are defined in one place, tools/worker_batch.py.

A prompt that contains the text of a denied path is still refused, and the refusal now says to remove the path
and state the prohibition in words. The egress-log code that could never run, `--strict-egress`,
`ask_codex.sh --resume-root`, and the `codex_root_thread.py` helper are removed.

Context: `decision:KIT-DR-007`, `decision:KIT-DR-010`, `decision:KIT-DR-012`. KIT-DR-010 fixed the receipt as
unchanged apart from one `scope:` line. This record amends that sentence. A person who judges from the receipt
alone needs the verdict first, and a count of the unknowns even when their text is cut. A run in which the
worker wrote PASS and left no file could not be told apart from a good run by its receipt.

evidence:
test:tools/tests/test_fresh_worker.py::test_receipt_byte_cap_keeps_the_start_and_puts_verdict_unknowns_and_location_first ·
test:tools/tests/test_fresh_worker.py::test_receipt_header_values_cannot_forge_lines_and_count_cut_unknowns ·
test:tools/tests/test_fresh_worker.py::test_expect_missing_or_empty_output_downgrades_a_pass ·
test:tools/tests/test_fresh_worker.py::test_expect_outside_root_is_refused_before_a_run · decision:KIT-DR-073
(removed test
tools/tests/test_egress.py::test_prohibition_naming_a_private_path_is_refused_with_wording_advice) ·
test:tools/tests/test_receipts.py::test_status_vocabulary_is_shared_by_worker_and_ledger

Boundary: the denied-path check reads prompt text. It is not a sandbox on what the worker reads. `--expect`
checks that a non-empty file exists after the run. It does not check that the content is right or that this
run wrote it. A run without `--expect` behaves as before.

Reconsider: a judgment made from a receipt alone is overturned when the full result is opened.

### DR-024 Korean editions live under `ko/`, and an index knows the pairs (2026-11-18 · superseded_by:DR-062)

Decision: documents in the root tree are English. A Korean edition lives under `ko/` at the same relative path
with the same file name (what was `README.ko.md` is `ko/README.md`). The pair table `ko/INDEX.md` is generated
(`python3 tools/dev/i18n_stamp.py index`), and the check fails when the table and the files disagree. A link
inside a Korean document goes to the Korean edition when one exists. Which side of a pair is the source stays
as its stamp says. "English is the main edition" means that English sits in the root tree and is what agents
read automatically. Hangul is allowed in files under `ko/`, in Korean values of the string catalog, and in
test data about Korean input.

Context: `decision:KIT-DR-004`, `decision:KIT-DR-016`, `decision:KIT-DR-019`. Owner instruction, 2026-11-18:
make English the main edition, collect the Korean files in one place, and let an index file say which file
pairs with which. Forty-two pairs sat next to their English files, links from Korean lens documents led to the
English index, and Korean command files in the command folder were registered by the runtime as separate
commands.

evidence: decision:KIT-DR-062

Boundary: no runtime reads the Korean rule files automatically. That was also true before the move.
An installed workspace may keep old `*.ko.md` copies, because `git pull` does not remove ignored instance
files.

Reconsider: a third language arrives, or Korean users actually ask for Korean rules to be loaded automatically.

### DR-025 Measure the fixed context of every session, and cap the default recall output (2026-11-18 · active)

Decision: `python3 tools/context_budget.py` measures what enters every session, in bytes and approximate
tokens: instruction files (`CLAUDE.md`, the files it imports, and `AGENTS.md`), the session-start
state injection, the trigger hook output, hook output added to each prompt, and the runtime memory index. It
writes no file. `doctor` warns, and never fails, when an item is over the warning line in the config.

The default output of `recall.py find` shows the source and a short excerpt of each match and stays within
4,000 bytes, notices included. When it stops early it prints how many matches remain and names `--full`.
`--full` prints what the command printed before, and `--full` and `--around` are not capped.

A Claude session is searched only when the working folder it records is this workspace or a declared alias, so
another project is not searched even when both folders map to the same transcript folder name. With zero
matches, the command states the scope it searched.

Context: `decision:KIT-DR-002`, `decision:KIT-DR-012`. On a fresh install the fixed context is about 6.7 KB,
most of it the seven rules. In the original instance it was 39.7 KB, of which 29.1 KB was the memory index.
The rules document said that only seven rules are always active, while most of the always-loaded instructions
sat in an index nobody measured. Splitting that index into per-task sub-indexes reduced it to 6.6 KB. Recall
output for one common word was 17.8 KB and is 3.6 KB under the new default.

evidence: test:tools/tests/test_context_budget.py::test_defaults_do_not_warn_on_small_install ·
test:tools/tests/test_context_budget.py::test_stale_state_is_estimated_without_writing_any_file ·
test:tools/tests/test_recall.py::test_default_output_is_capped_and_says_how_to_see_more ·
test:tools/tests/test_recall.py::test_full_keeps_previous_output_shape ·
test:tools/tests/test_recall.py::test_missing_transcript_dir_never_borrows_another_project ·
test:tools/tests/test_recall.py::test_claude_records_from_another_folder_with_the_same_store_name_are_excluded ·
test:tools/tests/test_recall.py::test_default_output_stays_under_the_cap_with_a_long_query

Boundary: a transcript file that records no working folder at all is still searched, and the number of such
files is reported. What the runtime injects by itself (system prompt, tool definitions, skill list) and the
user's global settings are not measured. Token counts are estimates and were not compared with a real
tokenizer. The warning lines are starting values, not measurements.

Reconsider: a warning line fires all the time in real use, or never fires.

### DR-026 Tool output follows the instance language, and that language is saved in the config (2026-11-18 · superseded_by:DR-049)

Decision: tool output that a person or a model reads comes from the string catalog. That covers the generated
`state/NOW.md`, the session-start injection, log, refusal and error messages, and help text. The language is
chosen from `MOTTORI_LANG`, then `instance.lang` in the config, then the shell locale. `setup.sh` writes the
install language to `instance.lang`. Words that are written to files and read back by code (the compaction
marker in the journal, section headings of NOW, the retroactive-entry marker, status values in the ledger) are
written in the current language, and every reader accepts both languages. Korean output is byte-identical to
what it was before the move, except five fallback messages inside hook configuration files, which are now
English only. English strings use no em dash and no arrow.

Context: `decision:KIT-DR-024`. An English install still showed a Korean state view and Korean command output.
The language came only from an environment variable and the locale, so a workspace installed in Korean could
run in another language under a shell or a scheduler with an English locale. Once generated state files and
journal markers follow the language, that language has to be fixed per workspace. The output of 208 Korean
commands was captured before and after the move and compared byte for byte, and 56 round trips were checked in
which state written in one language is read in the other.

evidence: test:tools/tests/test_state_runtime.py::test_english_instance_writes_english_state_and_injection ·
test:tools/tests/test_state_runtime.py::test_state_tokens_are_read_in_both_languages · decision:KIT-DR-049
(removed test tools/tests/test_i18n.py::test_configured_language_beats_locale) ·
test:tools/tests/test_facts.py::test_status_values_are_read_in_either_language · removed test
tools/tests/test_evidencecheck.py::test_issue_ids_do_not_depend_on_language
Boundary: a workspace installed earlier has no `instance.lang` and keeps following the locale until one line
is added (see CHANGELOG). The recording and transcription tools, the memory-map tool, and the description
column of the enforcement matrix still contain Korean and are listed in `system/dev/language-pending.txt`.
Parser labels that read Korean documents or transcripts stay Korean.

Reconsider: an old journal or ledger is misread in a workspace that changed its language.

### DR-027 Leaving a session and closing a job have a procedure (2026-11-18 · amended_by:DR-031 · amended_by:DR-041)

Decision:

1. When work will continue in another session or runtime, the leaving session writes a handoff note to a file
   (the handoff section of `system/rituals.md`, `/handoff` on Claude Code). The note has five parts, and text
   that exists only in the conversation goes into the note as text, not as a description. One journal line
   makes the path of the note visible in the state the next session is given.
2. Each job folder has one page at its top. When the job ends, the page says "done" and lists what to keep and
   what may be deleted. Temporary copies are made in one place only, and whoever dispatched the work deletes
   them. Nothing that cannot be rebuilt is deleted automatically (`system/WORKING-WITH-AI.md`).
3. `doctor` measures free disk space, the size of `.git`, the size of stale scratch files, and the number of
   job folders without a guide page, and it only warns.
4. Triggers get `add --sticky`. A notice the owner must see does not fall asleep because of how often it was
   shown, and it comes first in the list.
5. The Codex hook canary runs with the user config loaded.

Context: `decision:KIT-DR-012`, `decision:KIT-DR-014`, `decision:KIT-DR-021`. All 53 sessions of the original
instance were read. Of the new sessions, 42% were opened beside a session that was still running, and two or
more sessions were used on 56 of 153 days. "One thread" is the aim, and the practice was several.

In 9 of the 19 sessions that continued earlier work, the owner pasted more than 800 characters, and in 8 of
those the pasted text was an answer from another session or runtime. Dossiers and state carry what was
decided. Text that lived only in a conversation had no way to travel.

In the same instance the disk reached 98% full, and 93 of 125 job folders had no file saying what the job was
or whether it was finished. Six notices for the owner fell asleep after being shown three times, and none was
handled.

The Codex canary reported a working hook as failed, because Codex records project trust in the user config and
the canary ignored that config. In the same call, the model received the value the hook injected when the user
config was loaded, and did not receive it when the config was ignored.

evidence: test:tools/tests/test_triggers.py::test_sticky_triggers_never_auto_sleep_and_lead_the_hook ·
test:tools/tests/test_hook_runtime.py::test_canary_children_pin_instance_and_block_ambient_tools ·
test:tools/tests/test_doctor_json.py::test_growth_lowered_lines_warn_each_item_and_never_fail ·
test:tools/tests/test_doctor_json.py::test_growth_check_writes_nothing

Boundary: the handoff is a procedure and a command document. The engine does not enforce it. Codex has no
slash commands, so the same procedure is requested in words. The growth check only warns and deletes nothing.
The canary switches off connectors and external features one by one, and it uses the rest of the user's
settings as they are.

Reconsider: long pastes continue in sessions that take over work even when a handoff note was written. The
growth check warns all the time, or never.

### DR-028 Recall reads compressed Codex sessions, with a metadata cache and a time limit (2026-11-18 · amended_by:DR-041)

Decision: `recall.py find` and `recall.py sessions` also read Codex sessions stored as `*.jsonl.zst`. A Codex
source whose pattern ends in `.jsonl` also matches the same pattern with `.zst`. Compressed files are streamed
through the `zstd` command on PATH, and nothing decompressed is written to disk. Without zstd, compressed
files are left out and one line gives their count.

The first-line metadata of each compressed session (working folder, session id, subagent flag, parent id,
history boundary, never message text) is cached in the file `.recall-codex-meta.json` under `_private/state/`.
An entry is keyed by real path and used only while the file's size and modification time match. The cache sits
in the private state folder because it names the working folder of every Codex session on the machine. It is
written atomically with ASCII escapes, and deleting it is safe.

A compressed file whose first line zstd did not deliver, or a zstd that is on PATH but cannot start, is not
cached: one line gives the count of such files, they are not searched, and the next run tries them again. A
first line that zstd delivered but that does not parse is cached like a plain file's, so it is not read on
every run.

The CLI `find` reads files newest first and opens no new file after 20 seconds, except that the newest file is
always read. When files were left, one line gives their count and names `--scan-all`, and room for that line
is kept inside the 4,000-byte default output. The zero-hit scope counts the files actually read, so subagent
sessions that are not searched are not counted.

A lone surrogate in a session id or a message is replaced before it is hashed or printed. The `find()`
function without a time limit and `iter_messages` without a deadline behave as before.

Context: `decision:KIT-DR-025`. On one machine 5,088 of 5,111 Codex session files were compressed, so recall
could not see almost all Codex history, the lookup that rule 3 names. Python reads zstd only from version 3.14
on. Reading the first line of 5,088 compressed sessions took 17.4 seconds one at a time and 7.6 seconds with 8
parallel readers, a cost every `find` and `sessions` would pay, because the same-instance filter needs each
session's working folder first. With the cache a default search took 5.5 to 7.4 seconds, and a first search
without it 14 to 20.4 seconds. A full search across all instances took 31.5 to 35 seconds, which is the reason
for the time limit. The cache was 1,459,231 bytes for 5,088 sessions.

evidence: test:tools/tests/test_recall.py::test_compressed_codex_sessions_are_found_with_the_instance_filter ·
test:tools/tests/test_recall.py::test_missing_zstd_skips_compressed_sessions_with_one_line ·
test:tools/tests/test_recall.py::test_metadata_cache_holds_no_text_and_follows_a_rewritten_file ·
test:tools/tests/test_recall.py::test_time_limit_reads_newest_first_and_says_what_was_left ·
test:tools/tests/test_recall.py::test_failed_zstd_read_is_reported_and_tried_again ·
test:tools/tests/test_recall.py::test_lone_surrogate_in_session_metadata_does_not_crash ·
test:tools/tests/test_recall.py::test_time_limit_counts_only_sessions_it_would_have_read ·
test:tools/tests/test_recall.py::test_real_zstd_reads_a_compressed_session ·
test:tools/tests/test_recall.py::test_unstartable_zstd_is_reported_even_across_all_instances ·
test:tools/tests/test_recall.py::test_zero_hit_scope_counts_only_sessions_read_without_a_time_limit ·
test:tools/tests/test_recall.py::test_compressed_file_with_an_unparseable_first_line_is_cached_not_reread ·
test:tools/tests/test_recall.py::test_hit_from_a_session_whose_id_holds_a_lone_surrogate_is_printed

Boundary: what is given up. A search under the limit can miss a best match that exists only in older files,
and says so. The limit is checked between files, so one large file or a stalled zstd can take a search past 20
seconds. The first metadata read covers every compressed session on the machine, not only this workspace's,
and counts against the limit. Without zstd the skipped count is for the whole machine. zstd failing after the
first line loses the rest of that file without a warning. When the same session exists as a live and an
archived copy, a hit can point at the newer copy. `tools/eval_recall.py` calls `find` without `--scan-all`, so
its measurement is also bounded. `sessions` has no time limit. Linux and Windows were not run.

Rejected alternatives: decompressing sessions into a disk cache (copies conversation text and is large). A
Python zstd package (the kit uses the standard library only). A limit that leaves files unread without saying
so.

Reconsider: default searches regularly stop at the time limit in real use, or the metadata cache itself slows every run.

### DR-029 The doctor coverage row warns about missing link-check coverage, and only the link row fails on broken links (2026-11-18 · amended_by:DR-041 · amended_by:DR-042)

Decision: the doctor row "gate · output check omitted" reports coverage only. It passes when a recorded
linkcheck pass matches the current Markdown bytes, or when the working-tree fingerprint the turn-end gate
stored after its last clean pass equals the current one. Otherwise it warns and names the time of the last
turn-end gate run, or says that none was recorded. The warning says that only Claude Code runs the turn-end
gate. The row no longer fails because new files exist. A broken link fails through the link check row in the
same doctor run. When `tools/gate.py` is missing, the row warns instead of crashing.

Context: `decision:KIT-DR-020`. The row failed whenever any file was added in the last commit or was untracked
and no manual linkcheck record matched the current bytes. Only a manual `python3 tools/linkcheck.py` writes
that record: the turn-end gate runs `linkcheck.py --issues` as an internal run, and doctor's own link
measurement writes nothing either. So after any Markdown edit the row failed even when the gate and the link
row had just measured zero broken links. In the test fixture the row listed
`docs/a.md, docs/b.md, .gitignore, docs/c.md` as new files while the link row measured 2 references and 0
broken.

On a fixture of 500 Markdown files and 5,000 references the row took 0.059 seconds before and 0.065 seconds
after (median of 5). An independent review measured 32 to 54 milliseconds more with a 100,000-line run log.
Session start and turn end are unchanged, because no hook calls doctor.

evidence: test:tools/tests/test_install_checks.py::test_doctor_unrecorded_clean_links_warn_and_show_turn_end_gate

Boundary: what is given up. A new file without a link-check record is no longer a failure by itself. This row
can pass while the link row fails on a broken link the gate already accepted in its baseline. The fingerprint
misses an overwrite that keeps both size and modification time. Doctor reads three private names of
`tools/gate.py`. The age of the last turn-end run is shown and not judged; the warning only says that an old
or missing run may mean the Stop hook is not firing, and the same warning appears with a working hook after a
shell edit made since the last run. In a workspace that runs only Codex, which has no turn-end hook, the row
warns until a manual link check is recorded.

Rejected alternatives: having the turn-end gate write the linkcheck record (a hash of every Markdown byte at
every turn end, and an exception to the internal-run rule). Measuring the links again inside this row (repeats
the link row).

Reconsider: the row warns on most doctor runs in a workspace whose Stop hook fires.

### DR-030 The link checker reads angle-bracket links, skips inline code, and keeps backticked paths checked (2026-11-18 · amended_by:DR-036 · amended_by:DR-037 · amended_by:DR-041)

Decision: a newer link checker variant in the original instance had five parsing changes without tests or a
record. Four are ported and one is dropped.

1. Kept: CommonMark angle-bracket destinations such as `[x](<a b/c.md#frag>)` are checked.
2. Kept, narrowed: inline code is removed before Markdown links are read. A code span follows CommonMark
   within one line: it opens on a backtick run that is not escaped with a backslash and closes only on a run
   of the same length.
3. Kept, moved: an editor-style `:line` or `:line:col` suffix is accepted on a backticked path only; a
   Markdown link with such a suffix stays strict, because a renderer would open the missing file. In the
   variant the suffix applied only to Markdown links.
4. Kept, narrowed: a backticked path is also resolved against each enclosing folder of its document, but not
   when the same path is a Markdown link in that document.
5. Dropped: reporting backticked paths whose first folder exists nowhere only as a count. The new suite is
   `tools/tests/test_linkcheck.py`, which doctor runs among the kit-only suites.

Context: `decision:KIT-DR-020`. Change (5) runs before the setup-pending and optional checks. On the kit's
documents it would have reclassified 43 of 113 pending and optional references (9 pending before setup, 34
optional) as not checked. After setup it would hide a missing required file under an absent folder, and it
hides any typo in a path's first folder. On the kit's documents before v0.11, the old and the new checker give
identical findings in both scopes: 780 references, 0 broken, 75 pending, 38 optional. Changes (1) to (4) are
exercised only by the constructed cases in the suite. The old checker passes 9 of the 13 assertions in the new
suite.

evidence: test:tools/tests/test_linkcheck.py::test_markdown_link_typo_is_reported ·
test:tools/tests/test_linkcheck.py::test_angle_bracket_destinations_with_spaces ·
test:tools/tests/test_linkcheck.py::test_inline_code_is_not_a_link ·
test:tools/tests/test_linkcheck.py::test_backticked_line_suffix ·
test:tools/tests/test_linkcheck.py::test_backticked_path_resolves_against_parent_folders ·
test:tools/tests/test_linkcheck.py::test_backticked_path_with_unknown_first_folder_is_broken

Boundary: what is no longer reported. Bracket syntax inside inline code, such as `x[0](y)`, is no longer read
as a link. A link after a stray single backtick that pairs with a later backtick on the same line is hidden; a
CommonMark renderer shows that text as code too, but the old checker reported the link. A wrong backticked
relative path passes when an enclosing folder happens to contain that path. A code span is not followed across
a line break. An instance that cites paths from other codebases in backticks sees them as broken and fences
those documents with `linkcheck_exclude_prefixes`. No Markdown renderer was run; the CommonMark statements
come from the specification.

Rejected alternatives: keeping (5) and printing each path without failing (it removes the gate for the typo
class it lets through). Pairing single backticks per line (a valid span such as ``` ``a`b`` ``` swallowed a
later link).

Reconsider: the original instance's documents show broken backticked paths that are not typos and cannot be
fenced by document prefix.

### DR-031 The explicit handoff step of KIT-DR-027 is withdrawn (2026-11-18 · active)

Decision: part (1) of KIT-DR-027 is withdrawn. The kit no longer has a step in which the leaving session
writes a handoff note. The `/handoff` command in both languages, the handoff section of `system/rituals.md`
and its index line, the sentence in rule 4 of `AGENTS.md`, its line in the reading list, and the command
description in tools/harness.py are removed. Parts (2) to (5) of KIT-DR-027 stay. The entry ritual now points
a session that takes over a long-running task to the page at the top of the task's folder, which KIT-DR-027
part (2) already requires.

Context: `decision:KIT-DR-027`. The owner decided that a step in which the leaving session writes a note is
not how he works. The procedure depends on the leaving session, and sessions often end at a usage limit
without a chance to write anything. In a check of nine past cases where context was pasted by hand into a
continued session, the pasted text was already in another session's transcript on disk in all nine, and eight
of the nine source sessions were still open.

Boundary: nothing in this commit replaces the step. Text that lived only in a conversation can be found by a
later session that searches the transcripts on disk with `python3 tools/recall.py find`. That search runs only
when a session is asked to run it, and it has limits: by default it reads only this instance's sessions, it
opens no new file after 20 seconds unless `--scan-all` is given, it skips Codex sessions stored compressed
when `zstd` is not installed, and it never searches Claude subagent transcripts. Notes an instance already
wrote under `_private/state/handoff/` stay where they are, and no tool reads them.

Rejected alternatives: keeping the command as an optional step (a documented step the owner does not take
leads a session to look for a note that is not there).

Reconsider: a case where text that had to travel to another session was in no transcript on disk.

### DR-032 Gate definitions are no longer approved through a ledger line (2026-11-18 · amended_by:DR-064)

Decision: KIT-DR-013 is superseded. The ledger system/gate-definition-approvals.md, its check in
`tools/dev/manifest_build.py`, the `MOTTORI_APPROVAL_*` variables passed by `tools/gate.py` and
`.github/workflows/gates.yml`, enforcement-matrix rule `w2-18-gate-definition-approval` and the matching row
of `system/dev/enforcement-matrix.md` are removed. GATE_DEFINITION_PATHS stays: those files always carry the
`gate-definition` kind in the review manifest, whatever a hand edit says. Review manifest rows keep only
`path`, `kind` and `consumers`, and `tools/dev/manifest_build.py` refuses to rewrite a manifest that is not
valid JSON.

Context: `decision:KIT-DR-013`. The approval line can be written by the same agent that made the change. The
failure message of `--issues` printed the exact `files=... sha256=...` text to copy, and the decision marker
was only checked for its shape. In a scratch repository a line with that copied text and the marker of a
nonexistent record DR-999 made the check pass, so the check verified that someone wrote a line, not who
approved the diff. It also cost a lot: the generated review manifest is itself a gate-definition file, so most
ordinary edits needed a fresh line (18 of the 21 lines include it), and the check had edge cases of its own
(the diff hash depended on git config, untracked files were unseen, staged mode read the working ledger, one
malformed line blocked every approval, a missing CI base ended in a traceback).

evidence: removed tests tools/tests/test_manifests.py::test_gate_definition_kind_is_fixed and
tools/tests/test_manifests.py::test_build_refuses_unparseable_manifest
Boundary: what is given up. Nothing now fails merely because a gate definition changed, so there is no
mandatory pause before such a change lands. The planned seal for enforcement-matrix rule
`w2-19-language-pending-seal` was this approval: a new line in `system/dev/language-pending.txt` still skips
the language check, and that hole now has no planned seal. What still protects gate definitions: the
regression list in `system/dev/test-matrix.yaml` and its check, the suites the commit gate and CI run, the
fixed `gate-definition` kind in the review manifest, and the dispatcher reading the diff before integrating
it.

Reconsider: a stronger check is wanted. It must rest on something the agent cannot write, for example CI
printing the gate-definition diff in its run summary or a protected branch, not on a file in the same tree.

KIT-DR-064: the test matrix and the review manifest are removed; the suite, continuous integration and the
reading of the diff remain, and the language check's open hole is now the `HANGUL_ALLOWED` list in
`tools/tests/test_language.py`.

### DR-033 Worker write scope is measured only in a worktree and only reported; strict scope, read-scope metadata and the wave receipt are removed (2026-11-18 · active)

Decision: this amends KIT-DR-010 and the worker contract of KIT-DR-007, following the engine exported from the
original instance. `tools/fresh_worker.py` no longer has `--strict-scope`. The write set is measured
only in a worktree that only the worker writes (`--worktree`); a run in the shared workspace records scope
`unchecked (shared workspace)` and does not scan the tree. A violation is recorded in `scope.status` and the
receipt, and never changes run status or the exit code. Metadata no longer records `harness_sha256` or
`read_scope`; the READ_SCOPE and UNREAD lines stay in result.txt as the worker's self-report.
`tools/receipts.py aggregate` (the wave receipt) is removed; `list` and `show` remain.
`tools/ask_codex.sh --resume` is removed, so every Codex call is a fresh worker run.

Context: `decision:KIT-DR-007`, `decision:KIT-DR-010`, `decision:KIT-DR-023`. A diff of a shared workspace
with concurrent writers cannot tell which writer made a change; the live canary recorded in KIT-DR-010 found
that both violations came from concurrent writers. Failing a run on such a diff blames the worker for another
writer. No kit tool other than the worker itself read the harness hash or the copied read scope.

evidence: test:tools/tests/test_fresh_worker.py::test_scope_violation_is_report_only_without_strict ·
test:tools/tests/test_fresh_worker.py::test_shared_workspace_scope_unchecked ·
test:tools/tests/test_fresh_worker.py::test_write_prefix_boundaries_fail_closed ·
test:tools/tests/test_tool_entrypoints.py::test_ask_codex_has_no_root_thread_lookup

Boundary: what is given up. No option makes a scope violation fail a run, so a script that relied on exit 4
sees success with `scope: scope_violation`. A shared-workspace run is not measured at all. A batch that
combined several runs into one receipt now reads each receipt with `receipts.py show`.

Rejected alternatives: keeping `--strict-scope` in the kit only (it would make `tools/fresh_worker.py` a kit
variant that each export from the original instance has to reconcile by hand).

Reconsider: a caller needs a run to fail on a scope violation in a worktree.

### DR-034 The gate baseline is a plain file; signing and adoption approval are removed; a session sharing a folder is not blocked for another session's block or for a link only another session is still editing (2026-11-19 · active)

Decision: `tools/gate.py baseline` saves the measured issue set as plain JSON, a mapping of checker name to
issue IDs. It first copies the old file to state/.gate-baseline.prev.json, so an unwanted adoption is undone
by copying that file back, and it prints what it adopted. It no longer refuses on a dirty tree.

The commands `approve-adoption`, `seal-baseline` and `selfcheck`, the signing key and approval file under
`.git`, the adoption history and the seal step of `install_hooks.sh --repair` are removed. A signed baseline
from an earlier version still loads; its signature fields are ignored and the next save writes the plain form.
New issues, a removed checker, and an absent or corrupt baseline still block.

Also decided on 2026-11-19, after an independent review: sessions that share one folder are told apart by the
hook payload's `session_id`, and the pending marker under `.git` holds one entry per session (its reason, its
issue IDs, and which other sessions were told). An issue held by another session's entry does not block a
session at turn end: IDs already in the baseline or held by another session's entry are not counted again, so
the session that blocked first holds a shared ID.

Only the blocked session clears its own entry, once the issue is gone, whoever fixed it; another session's
passing Stop never clears it, because an issue found only through the edited-file list cannot be measured
again from another session. Another session's next prompt gets one line, once per block, saying that
another session on this folder left a check failing, that it is not from this conversation and does not block
it, with the reason. A payload without a session ID, and a plain-text marker from an earlier version, judge
and clear everything as before.

While any block is pending, every Stop measures instead of taking the unchanged-tree shortcut. A block whose
only new issues are broken links in Markdown that Git does not track blocks once in the editing turn and is
released by the Stop that follows, so the next prompt does not repeat it unless that file was edited again
before that Stop.

The edit marker under `.git` likewise holds one entry per session: the files that session edited through an
edit tool and the time of its last edit. A broken link that the link check reports in a document listed in
another session's live entry, and not in this session's own, is left to that session: it does not block
this session's turn end, it is not saved to the baseline, and nothing is said about it.

An entry is live until that session's next turn end and for at most one hour after its last edit, so a session
that died in the middle of a turn does not keep its documents exempt: a live turn rarely goes an hour without
an edit, and an expired entry only restores the single-session rule.

Every other issue is judged as if the session were alone on the folder: every state-check issue whatever its
ID, and every issue in a file no session edited through an edit tool, such as one a shell command made. A
session that was blocked stays blocked at its later turn ends for what its own block holds.

Decided on 2026-11-20 by the main session: an earlier version of this rule also let an issue tied to no
session's edits pass while another session had edits pending and said the commit check would stop it; that was
too broad, because a state-check issue a session made through its own edit could never be tied to it and most
state-check issues are not measured at commit, so it was withdrawn.

The gate writes its marker files to a temporary file and renames it, so a prompt hook that reads without the
lock never sees half a marker.

Context: the signed baseline and the adoption approval came in with CHANGELOG v0.7 and v0.8 and never had a
kit record, so this record supersedes none. They did not stop what they were for: the baseline file is
untracked, so after it was deleted `gate.py baseline` adopted every new issue with no approval, and the agent
that must not adopt issues could run `approve-adoption` and read the key with the same rights. The one pending
record was overwritten by the newest block, so a session was stopped by another session's failure, and its own
passing Stop cleared the other session's reason. Decided during the v0.11 line-by-line review by the
maintainer's assistant; the maintainer delegated the reversible decisions of that review on 2026-11-18 and may
reverse any of them.

evidence: test:tools/tests/test_gate.py::test_a_session_is_judged_only_for_its_own_block ·
test:tools/tests/test_gate.py::test_baseline_adopts_new_issue_and_keeps_previous_file ·
test:tools/tests/test_gate.py::test_previously_sealed_baseline_still_reads ·
test:tools/tests/test_gate.py::test_reentrant_stop_passes_on_gate_failure ·
test:tools/tests/test_gate.py::test_unknown_subcommand_is_an_error ·
test:tools/tests/test_gate.py::test_markers_are_utf8_under_a_legacy_locale

Boundary: what is given up. A hand edit of the baseline that bypasses `gate.py` is not detected. Nothing stops
an agent from running `gate.py baseline` to accept its own new issues; that shows in the command's output and
in the previous copy. A gate fault on a re-entered Stop ends the turn instead of blocking it again. A
state-check issue or a shell-made issue that another session left unfinished can still block the session that
ends its turn first. An abandoned session's entry keeps every Stop measuring until that session's own Stop
runs or `gate.py baseline` removes the marker.

Rejected alternatives: keeping the seal with the clean-tree rule relaxed (it still does not stop deletion of
the file). Moving the approval out of the agent's reach (one machine has no second identity to hold it).
Keeping a block on an untracked Markdown file pending until its link is fixed (a link left broken on purpose
in a draft would then block every turn, and `gate.py baseline` cannot adopt an issue in an untracked file). A
state file per session (one marker with an entry per session needs no new file and keeps every reason).

Reconsider: an issue adopted by a worker without anyone noticing it in the baseline output or the previous copy.

### DR-035 The kit asks the owner only on four critical kinds, and a running loop acts only inside delegated scope (2026-11-19 · active)

Decision: a kit session or command asks the owner before acting only on the four critical kinds named in
`system/rituals.md#memory`: something leaves the machine, data that cannot be rebuilt is deleted, an
untouchable folder is touched, or money or a usage limit is spent. It also asks when personal facts conflict,
as that section says. It applies everything else with a way to undo it and reports afterward.

A running loop, including the follow-ups of `/garden`, acts only inside the scope the owner explicitly
delegated in the instance rules; without that delegation it stops at proposals, and installing the kit grants
no execution authority (`system/PRD-session-memory.md`).

Drafts from the same review that say otherwise are obsolete: `/garden` also asking on structure, policy and
personal facts, the kit keeping a separate list of its own, and a kit default that lands non-critical changes
without delegation.

Context: `decision:KIT-DR-012`, `decision:KIT-DR-016`. Drafts written during the review gave `/garden`,
`/now`, paper-to-kit and the session PRD different rules; this record states the one the merged documents
follow. Escalating small decisions spends the owner's attention, and execution authority is each instance's
own grant. Decided during the v0.11 line-by-line review by the maintainer's assistant; the maintainer
delegated the reversible decisions of that review on 2026-11-18 and may reverse any of them.

evidence: test:tools/tests/test_skill_parity.py::test_manual_commands_stop_only_on_critical_kinds ·
decision:KIT-DR-057 (removed test
tools/tests/test_tool_entrypoints.py::test_wf_gardener_owner_questions_only_critical_kinds)

Boundary: the four kinds are a list in documents, not a check; nothing measures whether a session asked. The
kit ships no loop that consumes `ready` proposals of paper-to-kit.

Reconsider: a change applied without asking turns out to be one of the four kinds, or causes a loss that
cannot be undone.

### DR-036 Corrections to earlier records where the text and the kit's behaviour differ (2026-11-19 · amended_by:DR-041 · amended_by:DR-062)

Decision: these sentences replace the ones named, and the earlier records are not rewritten.

1. KIT-DR-012: the aim "one endless thread" means one line of the owner's attention. Work may run in several
   sessions over the same workspace, and what carries it between them is files on disk (state, dossiers, the
   page at the top of a job folder, transcripts), not a note written by the session that leaves.
2. KIT-DR-008: the two lines `Document role` and `Consistency anchors` come first in the working message to
   the owner, never in the body that is sent. They are not written to a separate work log.
3. KIT-DR-005: the upstream check in `doctor` is skipped in the source workspace that exports the kit. The
   marker is the presence of tools/kit_sync.py, which the public kit repository does not contain, so the check
   runs in a clone of the public kit.
4. KIT-DR-022: each signal is off, record only, or block, and a signal the instance config does not list is
   off, so by default the check reads no transcript and records nothing. A document counts as reopened when a
   later tool call that is neither an edit nor a send carries its whole path anywhere in its input: the full
   path, or the path relative to the instance root (a leading ./ allowed), with no character that could
   continue a path directly before or after it. So a shell command such as cat counts, and a file of the same
   name in another folder does not, except for a document at the instance root, whose root-relative path is
   its file name. The check cannot know whether the output of that call was read, and it does not see a path
   the shell builds or escapes (a variable, a glob, a backslash before a space).
5. KIT-DR-004: since KIT-DR-007, the engine side of the first pair is `AGENTS.md`, which `CLAUDE.md` imports
   with one line. The instance side is still `system/instance-rules.md`.
6. KIT-DR-016: since KIT-DR-024 the Korean editions live under `ko/`, and each pair's source is the side its
   stamp names. The two PRDs keep Korean as the source, in `ko/system/PRD-session-memory.md` and
   `ko/system/PRD-info-architecture.md`; their English editions are bound to the hash of that source.
7. KIT-DR-011: `bash tools/tests/test_fresh_install.sh` runs setup (which installs the hooks), a hook check,
   linkcheck, doctor, a stub worker run and a setup rerun. It runs no regression suite; those run separately
   at the release boundary.
8. KIT-DR-030: `tools/tests/test_linkcheck.py` is an engine suite that instances receive, and doctor runs it
   among the shared regression suites, not among the kit-only ones.
9. KIT-DR-021: session-start injection no longer splits NOW into sections. One selection is made from the
   journals and the config, and both the NOW page and the injected body are rendered from it; the injected
   body leaves out a section with no rows, while the page keeps its placeholder. When even the smallest
   selection overflows the page cap, the page is cut and that cut page is injected as it stands.

   Each journal topic (the `topic` of a `[topic/type]` tag) with a decision or phase change dated within 14
   days of the newest one keeps its newest such row before the other decision places go to the newest rows,
   within the same caps; registered tracks get no special treatment, and when there are more such topics than
   places, the newest of those rows win. The 14 days keep a topic used once long ago from holding a place for
   ever. The first decision placed on each side is therefore the newest decision. Building the selection at
   session start reads both journals again: about 60 to 80 ms more with 3,000 rows on each side.

Context: `decision:KIT-DR-004`, `decision:KIT-DR-005`, `decision:KIT-DR-008`, `decision:KIT-DR-011`,
`decision:KIT-DR-012`, `decision:KIT-DR-016`, `decision:KIT-DR-021`, `decision:KIT-DR-022`,
`decision:KIT-DR-024`, `decision:KIT-DR-030`, `decision:KIT-DR-031`. Item (9) followed from the rework of the
state view, in which a busy topic evicted every decision of another topic and the injection parsed translated
page text back into rows. A line-by-line review of this file found the other eight places where a record says
something the kit does not do.

Item (4) also records a behaviour change made on 2026-11-19 after an independent review: the default went from
`unopened` recorded to no signal, because a check that only wrote a log nobody was told to read cost every
Stop a full transcript read, and a reread was matched by file name, so reading another folder's file of the
same name counted. KIT-DR-022's 2026-12-16 re-review therefore counts only instances that turned a signal on
in their config; a new instance with the default contributes no hits and is not read as a zero hit rate.

The outbound procedure in `system/rituals.md` already puts the two lines first in the working message.
`tools/deliver.py` defines the signals `unopened` and `reader` and turns on only the signals the instance
config lists. tools/kit_sync.py is absent from the public kit tree. KIT-DR-031 removed the step in which a
leaving session writes a note. KIT-DR-024 moved the Korean files under `ko/`. The header of
`tools/tests/test_fresh_install.sh` says the full suites run at the release boundary. The link checker and its
suite are the same file in the kit and in the workspace that exports it, so doctor lists the suite with the
shared ones. Decided during the v0.11 line-by-line review by the maintainer's assistant; the maintainer
delegated the reversible decisions of that review on 2026-11-18 and may reverse any of them.

Boundary: the mechanism by which a new session finds related work by itself is not designed yet. Until it
exists, text that lived only in another conversation is found only when a session is asked to search the
transcripts with `python3 tools/recall.py find`, within the limits KIT-DR-031 lists.

Rejected alternatives: editing the earlier records in place (the file is append-only, and a later reader could
no longer tell what was decided when).

Reconsider: another record is found whose text and the kit's behaviour differ.

### DR-037 v0.11 removals and simplifications without a record, corrections to KIT-DR-015, KIT-DR-018 and KIT-DR-023, and reference edits in published records (2026-11-19 · amended_by:DR-041 · amended_by:DR-048 · amended_by:DR-064)

Decision: these changes of v0.11 are recorded here; the earlier records are not rewritten, apart from the
reference edits item (18) lists.

1. Hook failures (KIT-DR-003): every SessionStart and PreCompact hook of both runtimes appends its stderr to
   `state/.hook-errors.log`, and the triggers hook writes a timestamped failure line instead of ending
   silently. The next session start shows one notice for the log lines not reported before (count, first time,
   last line) and records how far it has reported. `doctor` lists failures from the last 7 days and warns only
   on those the session start has not shown yet.
2. doctor, setup and language: doctor checks whether PreCompact fired by reading the compaction marker in the
   journals, and the manual PreCompact item is removed. The four boundary rows are named `boundary · ...`.
   Some catalog rows that nothing read are removed; others remain. Python 3.9 is the minimum. Templates ship
   no tracks and neutral transcription prompts.
3. Checks and CI: the enforcement matrix lists only rules that a check stands behind. The test-matrix check
   refuses a matrix that lowers a row the code lists as critical. CI runs every suite before it fails, runs
   the full mutation set, and uses a read-only token. The fresh-install script checks each claim it prints.
4. Engine sync (KIT-DR-010): `sync_engine.sh`, which copied the worker tools alone into another instance, is
   removed with its tests, because an instance upgrades with `git pull`. With it go the sync stamps in
   `tools/fresh_worker.py`, the `kit_sync` field of the run metadata, and the English copies of messages that
   `fresh_worker.py` and `tools/ask_codex.sh` kept for a tree without the catalog; both now print from the
   catalog only. Other commands that no kit caller used are removed in the same way: `tools/receipts.py cost`
   and the `list` options `--since`, `--runtime` and `--json`, `tools/build_memory_map.py --local`, and the
   `tools/enforce.py hook` subcommand; each now exits with a usage error.
5. Content: the architecture review and the content audit documents are deleted, as finished reports that
   looked current. Undefined labels are dropped from the PRD. Lens files point to the records section of the
   lens README. `tools/dev/i18n_stamp.py` keeps pairs only and no pending state. Closing a job asks the owner
   only before deleting data that cannot be rebuilt.
6. Recording: tools/diarize.py reads JSON segments only and writes a speaker file for any valid input, however
   small. tools/transcribe.py writes only the kept segments to its JSON and loses `--detect-language` and
   `--keep-wav`, which no kit caller used.
7. Workers (KIT-DR-023): a run whose status is not success gets the receipt verdict
   `INCONCLUSIVE (run status: ...)`, and the worker's own verdict appears on a `worker_verdict:` line.
   `--timeout SECONDS` stops the runtime and its process group and records status `timeout` with exit 7.

   `tools/worker_batch.py create` and `verify` and the `fresh_worker.py` options `--batch-manifest` and
   `--slot` are removed, because nothing called them; tools/worker_batch.py now only holds the status list,
   and each prompt runs as its own worker run.

   `tools/receipts.py` counts a run still marked `running` more than 6 hours after it started as failed,
   because a killed run never rewrites its `meta.json`; a live run given a `--timeout` above 6 hours therefore
   also shows as failed until it finishes.

   The Claude worker passes `--model` with `MOTTORI_FRESH_WORKER_CLAUDE_MODEL`, and without it the alias
   `opus`. The Codex worker passes a model option only when `MOTTORI_FRESH_WORKER_CODEX_MODEL` is set; it runs
   Codex with the user configuration ignored (`--ignore-user-config`), and without the variable its command
   carries no model option. Its reasoning effort is `MOTTORI_FRESH_WORKER_CODEX_EFFORT` (lower-case letters
   only), and without it, or with any other value, `high`.

   A result whose verdict is not a string is the invalid-contract result instead of a crash. A crash in result
   handling ends the run record as `interrupted` instead of leaving it `running`, and an isolated worktree is
   kept until its changes are captured. `tools/ask_codex.sh` works on its own checkout and no longer follows
   an inherited `MOTTORI_INSTANCE` that names another folder. A prompt path that is a FIFO is refused at once
   as not a regular file instead of blocking before the timeout applies.
8. KIT-DR-015: the sentence that `verify opencode --sweep` writes verdicts to state/harness-canary.json is no
   longer true; verify only prints them, and nothing reads that file.
9. KIT-DR-018: the supplement sentence about strict-scope exit 4 is no longer true, because KIT-DR-033 removed
   `--strict-scope`.
10. Ledgers: `rec.py check` names a field that still holds a `rec.py new` TODO placeholder instead of calling
    it missing, and reports a list in `status` or `date` as one problem; `check`, `hot` and `find` no longer
    crash on list values, and `find --since` keeps a record whose date is a list rather than hiding it.

    The separate English over-cap line of `rec.py hot` is removed, because the hotset text above it carries
    the same warning. `portrait.py candidates` without a person ledger prints the line `stale` prints.

    `rec.py check` reports a fact file without a `hot` line as a missing required field, and a `hot` value
    other than true or false in any case as a problem; before, both were read as false and kept the fact out
    of the hotset unnoticed. A scaffold placeholder is reported once.

    `rec.py new` refuses an ID that another session created at the same moment instead of overwriting that
    fact. `portrait.py stale` and `candidates` print in the install language.
11. Gate and hooks: when every new issue in a block is a link in edited Markdown that Git does not track, the
    block no longer offers `gate.py baseline`, which cannot accept such an issue; a block that also has an
    issue in a tracked file still offers it. The gate and the delivery check hook read hook input through one
    reader: input that is not a JSON object counts as empty and is no longer logged as a hook failure, and
    neither waits for input on a terminal or on an open stdin that stays silent.
12. doctor: a row is not applicable instead of a warning only where another row already warns about the same
    cause or the gap is outside this folder: `claude global time` when this folder's own settings inject the
    time, and the recall and PreCompact rows while no Claude Code transcript folder exists (the transcript
    path row still warns). So an instance used only through Codex sees no compaction warning until a Claude
    transcript folder exists.

    A settings file that is valid JSON of the wrong shape is reported as such on every row that reads it
    instead of as a crashed check. The PreCompact row passes only on a parsed compaction event in a journal,
    not on a row that quotes the marker.

    `tools/coherence.py` checks only hub indexes and status-document dates and loses `--quiet`; links and the
    fact ledger are left to `tools/linkcheck.py` and `python3 tools/rec.py check`, which doctor runs as their
    own rows, so doctor parses each result once. The worker receipt row shows the recent failure rate as
    information and warns only when receipts cannot be read, because a failed run is already visible in its
    receipt.

    Before setup the hook-command rows warn without running the hook, which used to leave lines in
    `state/.hook-errors.log`. When `core.hooksPath` is outside the repository, the pre-commit row says to set
    it back to `.git/hooks` and run `install_hooks.sh --repair`, and in a folder that is not the top of its
    own git repository it says to run `git init` first, where `--repair` would write into the enclosing
    repository.

    When the trigger store cannot be read, the context row says its total is partial. A store with unreadable
    lines is measured as the hook prints it, with their count and the refusal, instead of being left out as
    unmeasured. Without a config the schema row stays in the output as not applicable. The FAIL row of a
    drifted kit hook names `install_hooks.sh --repair`; a foreign hook's row names its two ways forward
    (amended by KIT-DR-039's 2026-11-20 amendment).
13. Config: `thresholds.track_stale_days` and `thresholds.context_state_max_bytes` are removed from the
    template, because nothing read them. An existing config that still has them loads without a warning, as
    any unknown key does. The template also leaves out the nine tuning values whose defaults live in the code
    (`now_tail_events`, `now_recent_decisions`, `journal_stale_days`, `memory_rot_days`, `now_max_bytes`,
    `now_hook_max_bytes`, `context_instructions_max_bytes`, `context_memory_index_max_bytes`,
    `context_fixed_max_bytes`); `thresholds` is empty and `_thresholds_note` names the files that hold
    the defaults, so a copy in each config cannot drift from the code.

    Setup no longer creates _private/transcribe-prompts.json, because transcription falls back to the generic
    prompt without it; an audio user who wants custom names creates it in the shape of
    templates/transcribe-prompts.json.
14. State check: `now.py check` no longer has the recording and drive inbox checks, which ran only with helper
    scripts the kit does not ship. When an instance has its own tools/now_instance.py, `now.py check` calls
    its `check(root, warn)`, and an error inside that module stops the check instead of being ignored.

    The message about inputs newer than the state page no longer counts journal lines, because entry times can
    be backdated; it gives the render time and the time the journal file was written. `now.py log` refuses
    text that holds a character `str.splitlines` treats as a line break (a CR, U+2028 and the like), because
    the reader would split the row.

    A public track row whose canonical resolves inside this tree's own `_private/` folder, through a symlink
    or a case variant of the folder name too, shows only its path, never its update line, and the public
    fingerprint does not hash that file either. A canonical counts as private when its path as written,
    normalized, begins with `_private` in any letter case, or when a folder above its resolved file is the
    same folder as `_private` (compared with `os.path.samefile`), so a `_private` folder that is itself a
    symlink to a place outside the tree, and a link target that spells the tree's path in another letter case,
    are covered too.

    The canonical-behind issue, on which the turn-end gate blocks, is raised only when the track's newest
    decision, state or correction event is newer than its canonical file; an idea or a lesson no longer raises
    it.

    Hook input is read with one deadline for the whole read. `state/.hook-errors.log` and the tool-run log
    keep their newer half once they pass 256 KiB; journals and records are never trimmed.
15. Push check: `tools/enforce.py prepush` leaves out only the commits the destination remote already has (its
    remote-tracking refs and the sha it advertises), not commits another remote has, so a push to a new remote
    inspects the whole outgoing history for `_private/` paths. A kit tree before setup skips the context and
    allowlist checks, which read the config it does not have yet, but its pushed commits are still checked for
    `_private/` paths; it no longer passes every push. Reason: a commit another remote held counted as already
    published, so a private file could leave through a new remote, and a tree before setup is where nothing
    else guards.
16. Hook install: `tools/install_hooks.sh` asks Git for the hook directory, so a `core.hooksPath` written with
    `~` is resolved as Git resolves it and refused when it is outside the repository, with the way back in the
    refusal; it used to install into a folder named `~` inside the workspace. `--repair` prunes only its own
    timestamped backups (`pre-commit.bak.<date>T<time>.<pid>`), so a backup a user named is kept.
17. Link check: an explicit Markdown link resolves only from its own document, the way a renderer opens it,
    also for setup-created, first-use and staged-tree targets; a backticked path still also tries the
    repository root and the enclosing folders. A nested link that matched only a root-level file used to pass
    while a reader's click opened nothing. A Markdown file that cannot be read or decoded fails the run as
    `<unreadable>` instead of being skipped with its links unchecked. A `--tree` run records no certificate in
    the tool-run log, because it did not read the live files.
18. Reference edits in published records: three records published in v0.10 name a file or a test that v0.11
    removed, so the link and evidence checks would fail on them. Only those references change, and the words
    around them stay. In KIT-DR-010 the two mentions of tools/sync_engine.sh (removed by item (4)) and in
    KIT-DR-013 the mention of system/gate-definition-approvals.md (removed by KIT-DR-032) lose their
    backticks. The two evidence lines of KIT-DR-013 cite `decision:KIT-DR-032` and keep the removed test names
    in parentheses. In KIT-DR-015 the removed test that held the old data border is cited the same way,
    through this record (item (19)). The heading of KIT-DR-022 writes its re-review date with `re-review`, the
    word the format line names, where it said `re-judge`.
19. KIT-DR-015, data border: opencode sends the injection file to a hosted model provider, so the file holds
    only public state unless `install`, `refresh` or `open` is given `--include-private` and the file is
    proven to be outside Git (fail-close); `verify` and its canary never include the overlay.

    The earlier border considered Git only, so a git-ignored state file carried the local overlay to the
    hosted provider through `open` and the canary, and a git-ignore line is not consent to send private state
    to a third party. The test that held the old border is replaced by
    `decision:KIT-DR-048 (removed test tools/tests/test_harness.py::test_no_private_overlay_reaches_opencode)`.

    The canary sends the same seed text that `open` passes as the first prompt, but through `opencode run`
    rather than the interactive `--prompt`, so a canary PASS still differs from the launcher path in that
    entry point.
20. Checklist: `CHECKLIST.md` no longer asks a user to run the disposable-clone gate drill or
    `tools/install_hooks.sh --check`, because setup installs and checks the hooks (KIT-DR-039), doctor reports
    them, and the test suites run each drill case; the drill moves to a closing section for contributors that
    names those tests. The audio item applies only to users who will transcribe meeting audio. It asks them to
    confirm the recording policy before the first run and no longer asks to record an execution ban in
    `system/instance-rules.md`.
21. Follow-ups found after the fourth review wave: `python3 tools/recall.py find` reads a transcript row whose
    session id is a number as that id written as text, as it did before the type checks, and ends with
    one line counting the rows it skipped because they are not a JSON object or carry a wrongly typed session
    id or timestamp; a row skipped for a wrongly typed nested field is not counted, because it cannot be told
    apart from a row that has no text. `rec.py check` reports an empty `hot` value once, as a missing field.

    doctor reports a hook command that is not a string as an unexpected settings shape on every hook row,
    where the failure-branch row crashed, the fixed session context measure counts it as a hook not measured,
    where it crashed, and its Korean Codex trust hint cites `ko/CHECKLIST.md`. `setup.sh` prints the hook
    paths `tools/install_hooks.sh` reports instead of looking up the hooks folder a second time, so the two
    cannot disagree.

Context: `decision:KIT-DR-003`, `decision:KIT-DR-010`, `decision:KIT-DR-013`, `decision:KIT-DR-015`,
`decision:KIT-DR-018`, `decision:KIT-DR-022`, `decision:KIT-DR-023`, `decision:KIT-DR-030`,
`decision:KIT-DR-033`. The v0.11 review made these changes in many small packages that each wrote a draft but
no record; each removes something nothing used, makes a check say what it measures, or makes a check catch
what it used to miss. Items (18) and (19) move into this record what earlier rounds of the review had written
into published records. Decided during the v0.11 line-by-line review by the maintainer's assistant; the
maintainer delegated the reversible decisions of that review on 2026-11-18 and may reverse any of them.

evidence: test:tools/tests/test_bypass_pins.py::test_h1_h01b_session_hooks_log_stderr ·
test:tools/tests/test_state_runtime.py::test_now_hook_context_reports_hook_errors ·
test:tools/tests/test_doctor_json.py::test_precompact_journal_marker_check · decision:KIT-DR-041 (was
test_tool_entrypoints.py::test_diarize_degenerate_inputs_still_write_output and
test_transcribe_filter.py::test_json_and_diarize_use_kept_segments) ·
test:tools/tests/test_fresh_worker.py::test_receipt_verdict_is_inconclusive_when_run_status_failed ·
test:tools/tests/test_fresh_worker.py::test_runtime_past_timeout_is_reaped_and_recorded · decision:KIT-DR-041
(was test_receipts.py::test_stale_running_counts_as_failure) · decision:KIT-DR-048 (removed test
tools/tests/test_harness.py::test_verify_writes_nothing_under_state) ·
test:tools/tests/test_facts.py::test_check_rejects_scaffold_todos ·
test:tools/tests/test_facts.py::test_malformed_record_is_reported_not_crashed ·
test:tools/tests/test_gate.py::test_edited_markdown_is_link_checked_in_the_turn_that_edited_it ·
test:tools/tests/test_deliver.py::test_broken_input_never_blocks ·
test:tools/tests/test_doctor_json.py::test_rows_say_what_is_true_for_this_folder ·
test:tools/tests/test_state_runtime.py::test_check_without_repair_never_writes_snapshots ·
test:tools/tests/test_enforce.py::test_prepush_refuses_pushed_private_commit ·
test:tools/tests/test_install_hooks.py::test_outside_repo_hookspath_is_refused ·
test:tools/tests/test_linkcheck.py::test_markdown_link_typo_is_reported ·
test:tools/tests/test_linkcheck.py::test_unreadable_markdown_is_reported ·
test:tools/tests/test_facts.py::test_new_does_not_overwrite_a_concurrent_creation ·
test:tools/tests/test_fresh_worker.py::test_result_handling_crash_before_capture_keeps_worktree_and_records_interrupted ·
decision:KIT-DR-048 (removed test tools/tests/test_harness.py::test_no_private_overlay_reaches_opencode) ·
test:tools/tests/test_recall.py::test_claude_text_and_legacy_content_blocks ·
test:tools/tests/test_install_checks.py::test_doctor_time_hook_matches_the_date_command ·
test:tools/tests/test_context_budget.py::test_hooks_that_are_not_measured_are_counted

Boundary: scripts that used a removed option or matched an old `doctor --json` name fail or miss rows until
they are changed (see CHANGELOG v0.11). A session can see a hook failure that was already fixed, once.

Reconsider: a removed option or document is asked for again by a real use.

KIT-DR-064: item (3)'s enforcement matrix and test-matrix check are replaced by `system/dev/enforcement.md`
and `tools/tests/test_tool_coverage.py`.

KIT-DR-065: the template has no `_thresholds_note` (item (13)); `MANUAL.md` section 2 names every `thresholds`
key with its default.

### DR-038 The trigger store follows its sources, retires ignored notices, and needs no claim before fire (2026-11-19 · amended_by:DR-041 · amended_by:DR-052)

Decision: this amends KIT-DR-014; its text is not rewritten.

1. Rows store no `privacy` and no `destination`. `add` accepts `--privacy` and `--destination` and ignores
   them. The tiers stay, and T2 is still never automatic.
2. `claim` is optional. `fire` works without a claim; it still refuses a live lease held by another holder and
   a repeated fire.
3. A plain row shown on three days without a fire sleeps for 7 days, as before; a row that has already slept
   twice (RETIRE_AFTER_SLEEPS) is retired instead of sleeping again, and `list --all` still shows it. A sticky
   row never sleeps or retires on its own.
4. `scan` reads the date from the heading segment that carries the re-review marker. It moves an open row it
   made to the date its source now gives, reopens a fired or retired row when the source gives a later date
   than the one it was closed on, and closes an `exp-` or `rereview-` row it made from a file that no longer
   lists it; such a row reopens when the source lists it again. Rows added by hand are never closed by `scan`.
   `add` with an existing id reopens a fired or retired row whose new date is later than its closing date.
5. A store line is unreadable when it is not a JSON object or when a field the commands display, sort or
   change is missing or of the wrong type: `id` and `what` as text, `when` as a trigger spec that parses, a
   known `tier`, `source` when set, the `shown` and `ignored` counters as integers, `history` as a list, and
   `created` and the other date fields as ISO dates.

   `hook`, `due` and `list` skip such a line and say how many they skipped; while one exists, `hook` and
   `due --mark` count nothing as shown, so nothing sleeps or retires on its own. `add`, `fire`, `claim`,
   `sleep` and `scan` refuse until the line is repaired or removed, and the refusal names the store file, the
   line numbers and the first problem, naming only the field and never quoting the stored value; while such a
   line exists the session-start hook shows that refusal in place of its fire and sleep hint, even when
   nothing is due.
6. Every message of `triggers.py` comes from the catalog in the install language; reminder text that `scan`
   already stored keeps its wording, and the `argparse` usage and error framing stays English.
7. `scan` refreshes the text, tier and source of an open, fired or retired row it made from the same file when
   that line changes; rows added by hand are untouched. The session-start hook shortens a reminder's text,
   source and lease holder past 200 characters each, never the id, and says that `list` shows the whole row.
   `hook`, `due` and `list` mark a row under a live lease by another named holder as being handled by that
   holder. `claim` requires `--holder`, because a lease under the shared default holder coordinates nothing;
   `fire` needs no holder.

Context: `decision:KIT-DR-014`. The scan read the re-review date from the last segment of the heading, so a
date in another segment never became a trigger, and a rescan did not follow a moved date or a closed source.
Ignored notices slept and woke without end. One damaged line made the whole session-start hook fail.

On one machine every session has the same default holder (user and host name), so the lease guarded nothing
and only made a plain `fire` fail. No kit tool delivers a trigger anywhere, so the privacy and destination
axes guarded nothing either.

A valid JSON row with a wrongly typed field made the session-start hook fail on every start and the writing
commands stop with a traceback, and a long stored text was injected whole at every session start. Decided
during the v0.11 line-by-line review by the maintainer's assistant; the maintainer delegated the reversible
decisions of that review on 2026-11-18 and may reverse any of them.

evidence: test:tools/tests/test_triggers.py::test_fire_without_claim ·
test:tools/tests/test_triggers.py::test_claim_lease_refuses_second_holder_and_due_stays_read_only ·
test:tools/tests/test_triggers.py::test_what_is_one_line ·
test:tools/tests/test_triggers.py::test_ignored_twice_retires ·
test:tools/tests/test_triggers.py::test_scan_follows_edited_source ·
test:tools/tests/test_triggers.py::test_source_closed_rows_return_when_listed_again ·
test:tools/tests/test_triggers.py::test_add_reopens_fired_fixed_id ·
test:tools/tests/test_triggers.py::test_scan_decision_marker_not_last ·
test:tools/tests/test_triggers.py::test_hook_survives_bad_rows

Boundary: what is given up. Nothing stops two sessions from acting on the same trigger at once; only one fire
is recorded, because `fire` runs under the store lock and refuses a row that is already fired. `add` no longer
refuses an outward destination, because none is stored. A notice ignored for about three weeks is retired and
shows only in `list --all`. A script that calls `claim` without `--holder` now stops with a usage error.

Reconsider: two sessions act on the same trigger, or a retired notice turns out to have been needed.

### DR-039 Setup installs the verification backstop hooks itself (2026-11-19 · amended_by:DR-041 · amended_by:DR-072 · amended_by:DR-074)

Decision: `setup.sh` installs the pre-commit and pre-push backstop on a first install and on every rerun, with
or without `--force`. It runs `tools/install_hooks.sh --check` first and leaves a current pair untouched,
because `--repair` always rewrites the files; otherwise it runs `--repair`, which keeps an older kit hook as
`.git/hooks/pre-*.bak.<timestamp>`, and prints the files it wrote.

A hook that is not the kit's is never overwritten and never skipped in silence: the installer still installs
the other hook, names the hook in the way with two ways forward (add the printed line that runs the kit's
check right after its first line, which the installer then reports as `chained` and never rewrites, or move it
aside and run `--repair`), and setup finishes the rest.

Any other installer failure (for example `core.hooksPath` outside the repository) prints
`backstop hooks not installed` with the installer's reason and the `--check` command, and setup finishes the
rest. When the folder is not the top of its own git repository, setup installs no hooks and says so in
one line, because the hooks would run on the commits of the enclosing project.

A refusal or a skip does not change setup's exit code. On a first install or a `--force` run that code comes
from the final doctor run and the baseline save, and doctor reports a missing or foreign hook as FAIL, reading
every line of `--check`; a plain rerun on an existing config installs the hooks, runs no doctor and exits 0.
The quick start in `README.md` is one command.

Context: `decision:KIT-DR-011`. `.git/hooks/` does not come with a clone, and the install steps asked for a
second command that a stranger could skip, so an install could look complete with no commit or push backstop.
An existing instance that never ran the installer gets the backstop by rerunning setup. Decided during the
v0.11 line-by-line review by the maintainer's assistant; the maintainer delegated the reversible decisions of
that review on 2026-11-18 and may reverse any of them.

Amended 2026-11-20 (eighth review wave): a foreign pre-push next to a missing pre-commit showed FAIL 0 because
doctor read only the first line and called a missing hook a warning, and `--repair` installed nothing while
any hook was foreign; the chain line and the per-hook repair date from this amendment.

evidence:
test:tools/tests/test_setup_migration.py::test_setup_leaves_foreign_and_enclosing_repository_hooks_alone ·
test:tools/tests/test_hook_runtime.py::test_installer_refuses_foreign_and_outside_hookspath

Boundary: in a kit folder inside another repository, doctor says to run `git init` in the folder before
`install_hooks.sh --repair`; run without `git init`, `--repair` writes the hooks into the enclosing
repository. Setup never edits a foreign hook itself: the person adds the line or moves the hook. The line
works only in a shell hook, and a pre-push that reads Git's standard input itself (`git lfs`) cannot share it.
A chained hook is recognised by that exact line, so a hook that skips it before reaching it passes as chained.

Reconsider: the hook install in setup breaks a hook workflow a user already had.

### DR-040 Tests, release tools and release records move to `tools/tests/`, `tools/dev/` and `system/dev/`, and one runner lists the suites (2026-11-19 · amended_by:DR-041 · amended_by:DR-064)

Decision: every regression test, `testlib.py` and the fresh-install shell test move from `tools/` to
`tools/tests/`. The release tools `evidencecheck.py`, `manifest_build.py`, `i18n_stamp.py` and
`skill_adapters.py` move to `tools/dev/`. The release records (the review manifest, the enforcement matrix in
YAML and Markdown, the test matrix, the evidence schema, the engine inventory and the language pending list)
move to `system/dev/`, and their Korean editions to `ko/system/dev/`.

Nothing a hook runs or a document tells a user to run for running an instance moves, so an installed instance
keeps working after `git pull` with no step. What moved serves changing the kit: the commands for running the
tests, among them the fresh-install test that `SETUP.md` names after an engine change, and the evidence schema
that a user writing an evidence marker reads.

`python3 tools/tests/run.py` is the one answer to which tests certify the tree: it runs every test file in its
folder one at a time from the root, each with an empty temporary HOME and stdin from /dev/null, prints
one line per file and exits 1 if any failed; file names select a subset, and `--full` adds the full mutation
run and the fresh-install test in English and Korean. The CI file calls it, and nothing else keeps a list of
suites: doctor's release mode runs it in place of its own list.

The body of `gate.py release` moves to `tools/dev/gate_release.py`, and `gate.py` imports it for every
release-scope measurement: `gate.py release`, and precommit, baseline and status in a kit development tree or
under `MOTTORI_GATE_SCOPE=release`. Apart from that import, no tool under `tools/` imports from `tools/tests/`
or `tools/dev/`, imports inside functions included, and no Claude or Codex hook command runs a file in them:
on 2026-11-20 every hook command of `.claude/settings.json` and `.codex/hooks.json`, replayed in a fresh
instance, opened no file in either folder.

The Git pre-commit of an installed instance uses the session scope; only in a kit development tree, before
setup, does it run the release scope, which runs the cited tests and the release checkers in tools/dev. The
three folders hold the kit's own tests, release tools and release records; they ship with every clone and the
documents cite files in them, so they are not meant to be removed.

Every test citation, in earlier records and changelog sections too, now names its file under `tools/tests/`,
and other pointers to the moved files follow them; this is a path rename of evidence pointers, not a change of
what any record says. A pointer to a file removed before this move keeps its old spelling.

Context: an independent review counted about 37,000 lines under `tools/`, of which about 20,000 were tests and
about 1,000 release tools, and about 3,000 lines of release records in `system/`, all in the same two folders
as what a running instance uses. A structure more complex than its use costs the reader's attention. Decided
during the v0.11 review by the maintainer's assistant; the maintainer delegated the reversible decisions of
that review and may reverse this one.

evidence: test:tools/tests/test_runner.py::test_one_line_per_file_and_failure_exits_nonzero · removed test
tools/tests/test_devtree_gate.py::test_devtree_precommit_and_release_run_cited_suites ·
test:tools/tests/test_tool_entrypoints.py::test_tools_import_nothing_from_tests_or_dev

Rejected alternatives: a separate runtime distribution that holds only what an instance runs (it would add a
build step and a second place to pull from, while the upgrade path is `git pull`).

Boundary: `gate.py` keeps the selection of suites from citations, the evidence re-run under a fresh run id,
the extracted-tree Git fixture, the parser of failed test names and their constants. In the kit
an installed instance's pre-commit uses the session scope, so these run only on the release path, but the
gate, evidence and enforcement tests patch them on the gate module, and moving them would mean rewriting those
tests. The release gate still runs only the cited suites, not the runner's whole list, because running all of
them would change what `gate.py release` and the pre-commit check in a kit development tree do.

`doctor.py` keeps its kit-shape markers, now naming `system/dev/`, and the skip of the regression row outside
release mode, which tests pin. The evidence schema is the reference for writing an evidence marker, so
`AGENTS.md` and the paper-to-kit skill now point into `system/dev/`. The engine inventory now names a moved
tool by its path under tools/, for example tests/run.py.

The runner runs the test files it finds, so a deleted test file makes the run one line shorter, not a failure;
`--full` likewise skips an extra entry whose file is absent, because the workspace tree has none of them.

Nothing counts the test files themselves: a deletion is caught only through the file's other ties, which are
the review manifest until it is regenerated, a citation as evidence and an entry in the test matrix (all three
fail `gate.py release`, the last because the test-matrix check is itself a cited suite), a path named in a
checked document (the link check), and an entry in the engine inventory (the installed-shape test). On
2026-11-20 every test file had at least one tie besides the manifest.

Reconsider: an instance needs a file under `tools/tests/`, `tools/dev/` or `system/dev/` to run, or a separate
list of suites comes back in another file.

KIT-DR-064: the release path this Boundary describes is removed with `tools/dev/gate_release.py`, the review
manifest, the test matrix, the engine inventory and `doctor --release`.

### DR-041 Seventh review wave: state, reminders, recall, install, hooks, gate, doctor and workers; the recording tools leave the kit; corrections to earlier records (2026-11-20 · amended_by:DR-042 · amended_by:DR-048 · amended_by:DR-064 · amended_by:DR-072)

Decision: the changes of the seventh review wave are recorded here, grouped by area; earlier records are not
rewritten, apart from the reference edits item (13) lists.

1. State: a journal correction competes for decision places like a decision or state row. Injected event rows
   go in whole; the 400-byte cut per row is gone. A track whose key is not in `public_tracks` shows its rows,
   board row and pointer on the local page only, and its canonical no longer changes the public fingerprint.

   When the public page cannot be rendered under the current policy, the public output says public state is
   unavailable and names the file and line; a malformed row is reported by path, line and the words
   malformed journal row, never by its text. A damaged tracked journal no longer hides the local view, and
   when the visibility policy is not ready the local page reads only the private journals. A generated local
   page whose inputs are gone is removed.

   Only a system state row in the compaction marker form counts as a compaction. A missing dossier file is
   marked in the injection and in `now.py threads`. Journal names may hold digits (q4); config track keys,
   `public_tracks` and `journal_types` are checked against the row pattern, and a name outside it gives a
   config warning instead of failing, because the previous release accepted it and failing froze the public
   state after an update; a schema 4 config without `public_tracks`, or with `legacy_public_tracks` null,
   fails validation naming the key.

   The canonical-stale check compares local dates. Undecodable bytes on the hook path are replaced instead of
   crashing. Each journal file is read and parsed once per process. In canary mode `now.py hook-context`
   prints only the nonce line, and an internal probe (`MOTTORI_INTERNAL_RUN=1`) neither advances nor trims the
   hook error log. Run-log trim and append share one lock of their own, so recording a run never waits on the
   state lock.
2. The state page transaction is plain: the config is checked inside the lock before each append and each
   render, a failed journal write is undone, and the page is written atomically. A page carries one
   `state-content-sha256` marker over its inputs and its own bytes, so a hand edit or a page from an older
   engine reads as stale; touching a file without changing it does not. The mid-render identity checks, the
   snapshot restore and the second marker are removed. A config change during a log now keeps the logged event
   with the existing warning that NOW was not refreshed.
3. Reminders: a 12/28 row first scanned in early January is last year's date. The session-start hook waits at
   most one second for the store lock and then prints one line saying the store is busy; other writers wait
   until the lock is free and say after three seconds what they are waiting for, and readers take no lock.
   When pinned rows would fill every hook place, the last place goes to the least-shown ordinary row. `scan`
   leaves alone a row of the same id that came from another file. A showing counts only on a date later than
   the last counted one. Bad patterns, dates, ranges and limits, `fire` on a retired row, and `sleep` under
   another holder's lease are refused with a message. `add --help` hides the ignored options. In canary mode
   the hook prints nothing.
4. Recall: a Codex session is scoped by the first line of the file when it is a session_meta row with an
   absolute working folder; other sessions are skipped and counted. `--order recent` and ties rank by parsed
   time. Under `--since` a row whose time does not parse is excluded and counted. `--order oldest` opens the
   oldest files first, and the 20-second limit starts after source selection. A lone surrogate in an id or
   time no longer crashes the duplicate filter. A Claude line without a session id inside an owned session is
   kept, and a leading Codex instructions block is stripped from the typed text. `tools/eval_recall.py` no
   longer depends on the hash seed.
5. Facts and ledgers: `rec.py` evidence paths must be files; `audit` shows the declared origin first; `check`
   reports a date that is not a real YYYY-MM-DD, a record pointing to itself, a superseded record that is
   still hot, and a list in `domain` or `origin_kind`; `check` without a ledger exits 0; snapshots are staged
   and hashed before they are published. `portrait.py` reads its start date only from a
   `last-reviewed: YYYY-MM-DD` line, includes that day, and asks for the line when it is missing.
   `coherence.py` reports a malformed checks row or a missing status document as one issue, and `--help` runs
   nothing.
6. Install and push: setup adds the clone origin to the remote allowlist only for a new work instance, without
   a password, query or fragment (an http(s) user name is dropped; an ssh account is kept), and `--force` adds
   no remote. A personal instance set up by an earlier version keeps the origin that version added.

   Setup stops before writing anything outside the top of its own git repository; a plain rerun after an
   interrupted first setup exits 1 and names the missing files; `--force` keeps an existing gate baseline and
   writes the config atomically.

   Instance files without a config count as a damaged instance, and commit and push are refused with recovery
   steps. The pre-push check judges what the receiver has only from the remote object id Git hands the hook.
   The hook installer never deletes a backup and names the resolved hooks folder in its `core.hooksPath`
   refusal.
7. Hooks: every declared hook runs through one launcher, `tools/hook.sh`. A missing or read-only `state/` no
   longer stops a hook, a failing tool adds one timestamped line to `state/.hook-errors.log` when that log can
   be written, and a hook never inherits another instance's `MOTTORI_INSTANCE`. The kit's settings no longer
   declare the delivery check's Stop hook; turning it on takes the hook entry in the docstring of
   `tools/deliver.py` and a signal in the config. doctor probes each SessionStart command with an event on
   stdin and a time limit. `hookdiag.py`, `hook_canary.py`, `harness.py` and `context_budget.py` report early
   exits, missing runtimes, empty settings files and undeclared injectors instead of crashing or counting
   them; the opencode canary writes no file.
8. Gate: every Stop measures; the unchanged-tree fingerprint shortcut and its file are gone. In
   an installed instance only explicit Markdown links can block a turn end: a path-shaped code span naming a
   missing file is advisory there and is not saved into the baseline, while release scope still blocks on it.
   The turn-end link check skips release-record folders in an installed instance, and a Stop in a kit
   development tree keeps the baseline's accepted findings in those folders. The edit hook writes only under
   the gate lock and logs a timestamped line when it cannot take it. The suite selection, the evidence re-run,
   the Git fixture and the per-run test log move to `tools/dev/gate_release.py`. Stop records the identity of
   the Markdown it checked (`linkcheck.scope_hash`) so doctor's coverage row can pass.
9. doctor: rows that cannot help are not listed or not applicable (node, Codex and Claude when absent, the
   transcript path before a Claude Code turn, the person ledger before it exists); on a fresh clone without
   node, codex or claude a work instance shows `checks 39 - ok 28 · FAIL 0 · warn 1 · not applicable 10` and a
   personal one `checks 39 - ok 27 · FAIL 0 · warn 1 · not applicable 11`, since a personal instance does not
   check the clone's remote.

   A broken config fails its row with the loader's reason. Arguments are parsed with exact names. Without Git
   there is one Git row. Hook failures already shown at session start are information. The coverage row never
   claims a pass while the link row fails, and the link row warns only when every broken reference is an
   advisory code span outside the release-record folders. Doctor reads tool exit codes and machine rows
   instead of localized sentences.
10. Workers: tools/worker_batch.py is removed; its status list lives in `tools/receipts.py`. Receipts count
    recorded statuses only and list runs still marked running apart, without guessing a failure from age;
    `show` withholds a verdict whose result file no longer matches its hash. A dirty-worktree patch is
    measured from the starting tree; an interrupted worktree run is captured before removal; stream errors
    reach the receipt with a login hint; the private-reference check normalizes paths and refuses a trailing
    parent step; `tools/ask_codex.sh` checks its arguments first.
11. Runner and release tools: `python3 tools/tests/run.py --help` prints usage, an empty test folder is an
    error, a missing `--full` entry fails instead of being skipped, and children run without
    `MOTTORI_INSTANCE`, `XDG_CONFIG_HOME`, `GIT_CONFIG_GLOBAL` and `CODEX_HOME`. Mutant runs write no release
    evidence. CI checks whitespace in the pushed commits. tools/build_memory_map.py moves to `tools/dev/`,
    because it generates a design page for contributors.
12. Surface: tools/transcribe.py, tools/diarize.py, their test, templates/transcribe-prompts.json leave the
    kit; an instance that has them keeps them as its own tools. The work-instance manual item about recording
    policy and its two catalog entries stay, and doctor lists the item only where tools/transcribe.py exists,
    so an instance that restores the tools gets the question back instead of a missing message.

    The starter config leaves out the transcript sources and the empty check inventories, which the code
    defaults to; setup still carries them over from an existing config.

    `AGENTS.md` loses what holds only for outbound writing (the preamble pointer, the punctuation rule and the
    measured test, now in `system/rituals.md#outbound`) and the evidence-schema pointer (the paper workflow
    names it); rule 4 gains the missing-dossier fallback and rule 7 the frozen-original rule; a missing
    `system/instance-rules.md` is recreated by `bash setup.sh --force`, which keeps the existing settings, not
    by the agent.

    README, SETUP and CHECKLIST teach the first day only, and the optional parts sit in one Optional section
    of SETUP. The gate drill moves to `system/dev/contributing.md`.
13. Corrections and reference edits. KIT-DR-006: rollback covers only a failed journal write. KIT-DR-020: the
    session scope no longer fingerprints the tree, and code spans are advisory there. KIT-DR-021: event lines
    are not cut at 400 bytes. KIT-DR-022: `tools/deliver.py` is no longer a declared Stop hook by default.
    KIT-DR-023: status names live in `tools/receipts.py`.

    KIT-DR-027 (4): pinned rows lead, but the last hook place goes to an ordinary row when they would fill it.
    KIT-DR-028: `find` reads newest first only in the default order, the time limit starts after source
    selection and does not count the metadata read, and `iter_messages` takes `scan_seconds` and
    `oldest_first` instead of a deadline; the file always read is the first in reading order.

    KIT-DR-029: the title's claim holds except for advisory code spans, the coverage row is skipped where it
    would pass while the link row fails, and the gate now records a document identity at Stop, which reverses
    the rejected alternative of having the turn-end gate hash the Markdown. KIT-DR-030: backticked paths keep
    blocking only at release scope.

    KIT-DR-036 (4): a file of the same name in another folder does not count as a reread, also for a document
    at the instance root; the sentence saying otherwise was wrong, because a match must not follow a path
    character.

    KIT-DR-037 (1): every hook writes through the launcher; (6): the recording tools are gone; (7): the 6-hour
    failure rule and `worker_batch.py` are gone; (12): the transcript path row is not applicable before a
    Claude Code turn; (15): see item (6); (16): no backup is pruned. Item (1) of KIT-DR-037 was already edited
    in place during this wave to describe the launcher; that edit is recorded here.

    KIT-DR-038 (2): `fire` also refuses a retired row; (4): reopening applies only to rows `scan` made from
    the same file. KIT-DR-039: setup stops outside the top of its own repository, a plain rerun of an
    incomplete install exits 1, and `install_hooks.sh --repair` refuses a nested kit instead of writing into
    the enclosing repository. KIT-DR-040 boundary: the suite selection and evidence re-run now live in
    `tools/dev/gate_release.py`, and `--full` fails on an absent entry.

    Reference edits: mentions of tools/worker_batch.py, tools/transcribe.py, tools/diarize.py and
    templates/transcribe-prompts.json in KIT-DR-023 and KIT-DR-037 lose their backticks; the removed tests of
    KIT-DR-037 are cited through this record with their old names; the status-vocabulary test of KIT-DR-023
    follows its move to `test_receipts.py`.

Context: two other model families reviewed a snapshot of the kit and the workspace it came from independently
and returned six reports with reproduced defects; each accepted item was reproduced before it was changed. The
changes remove what nothing used, make a check say what it measures, or make a tool refuse instead of
crashing. Decided by the maintainer's assistant under the maintainer's delegation of reversible decisions; the
maintainer may reverse any of them. The recording tools leave because their consent and retention questions
differ for every user and no other kit tool needs them.

evidence:
test:tools/tests/test_state_runtime.py::test_hook_context_keeps_dossiers_and_newest_decisions_with_long_journals ·
test:tools/tests/test_state_runtime.py::test_hook_context_keeps_long_event_lines_whole ·
test:tools/tests/test_state_runtime.py::test_track_row_shows_update_line_without_file_age_warning ·
test:tools/tests/test_state_runtime.py::test_hook_context_survives_corrupt_public_journal ·
test:tools/tests/test_state_runtime.py::test_private_log_survives_corrupt_public_journal ·
test:tools/tests/test_state_runtime.py::test_absent_overlay_stays_unavailable_and_is_not_created ·
test:tools/tests/test_state_runtime.py::test_now_hook_context_reports_hook_errors ·
test:tools/tests/test_state_runtime.py::test_touch_then_render_clears_stale_marker ·
test:tools/tests/test_state_runtime.py::test_page_from_an_older_engine_is_rendered_again ·
test:tools/tests/test_state_runtime.py::test_config_change_after_import_aborts_before_public_mutation ·
test:tools/tests/test_triggers.py::test_scan_md_dates_hold_across_new_year ·
test:tools/tests/test_triggers.py::test_shown_counts_once_per_calendar_day ·
test:tools/tests/test_triggers.py::test_sticky_triggers_never_auto_sleep_and_lead_the_hook ·
test:tools/tests/test_triggers.py::test_scan_follows_edited_source ·
test:tools/tests/test_triggers.py::test_invalid_inputs_exit_2 ·
test:tools/tests/test_recall.py::test_other_cwd_rollout_is_excluded_by_default ·
test:tools/tests/test_recall.py::test_since_uses_local_date ·
test:tools/tests/test_recall.py::test_time_limit_reads_newest_first_and_says_what_was_left ·
test:tools/tests/test_facts.py::test_check_flags_missing_origin_and_broken_link ·
test:tools/tests/test_facts.py::test_malformed_record_is_reported_not_crashed ·
test:tools/tests/test_facts.py::test_find_distinguishes_uncreated_ledger ·
test:tools/tests/test_tool_entrypoints.py::test_person_ledger_ignores_future_dates ·
test:tools/tests/test_coherence.py::test_status_doc_with_invalid_date_is_one_issue · decision:KIT-DR-072
(removed test tools/tests/test_setup_migration.py::test_origin_is_allowed_only_for_a_new_work_instance) ·
test:tools/tests/test_setup_migration.py::test_setup_leaves_foreign_and_enclosing_repository_hooks_alone ·
test:tools/tests/test_enforce.py::test_prepush_refuses_pushed_private_commit ·
test:tools/tests/test_install_hooks.py::test_repair_never_deletes_a_backup ·
test:tools/tests/test_bypass_pins.py::test_h1_h01_missing_gate_command_is_logged ·
test:tools/tests/test_install_checks.py::test_doctor_state_injection_failure_names_the_error ·
test:tools/tests/test_hookdiag.py::test_codex_hooks_list_reads_paired_and_noisy_output · decision:KIT-DR-048
(removed test tools/tests/test_harness.py::test_no_private_overlay_reaches_opencode) ·
test:tools/tests/test_context_budget.py::test_hooks_that_are_not_measured_are_counted ·
test:tools/tests/test_deliver.py::test_default_only_records ·
test:tools/tests/test_bypass_pins.py::test_h1_h06_delivery_check_needs_only_its_config ·
test:tools/tests/test_gate.py::test_every_stop_measures · removed test
tools/tests/test_gate.py::test_session_tighten_keeps_removed_checker ·
test:tools/tests/test_gate.py::test_staged_checks_use_the_staged_linkcheck_without_git_pinning ·
test:tools/tests/test_install_checks.py::test_doctor_unrecorded_clean_links_warn_and_show_turn_end_gate ·
test:tools/tests/test_doctor_json.py::test_command_line_is_parsed ·
test:tools/tests/test_doctor_json.py::test_missing_git_is_one_row ·
test:tools/tests/test_doctor_json.py::test_recorded_link_pass_yields_to_a_failed_link_row ·
test:tools/tests/test_install_checks.py::test_doctor_warns_on_recent_hook_errors ·
test:tools/tests/test_install_checks.py::test_doctor_manual_list_holds_only_what_a_person_can_check ·
test:tools/tests/test_receipts.py::test_running_is_counted_apart_not_as_failure ·
test:tools/tests/test_fresh_worker.py::test_read_material_case_variant_of_denied_prefix_is_refused ·
test:tools/tests/test_runner.py::test_full_entries_cannot_go_missing ·
test:tools/tests/test_tool_entrypoints.py::test_tools_import_nothing_from_tests_or_dev

Rejected alternatives: none of these was accepted: a 180-day window for last year's month and day in `scan`
(it would read 11/30 seen in May as last November); reading Codex session metadata past the first line (one
more compressed read per file); keeping the snapshot restore and mid-render identity checks of the state page
(an edit a few milliseconds into a render cannot be told from one just after it); a doctor row for delivery
signals set without the Stop hook (the template note gives both steps); no longer putting a shown reminder to
sleep; moving the release-tool messages out of the shared catalog (it would need a second catalog shape and
new language-test rules); keeping the prose-date guess of `portrait.py` as a fallback.

Boundary: what stays open. A trailing ellipsis after an allowed private folder escapes the parent-step
refusal. Every Stop rewrites the baseline file while it holds accepted release-record link findings.
Compressed Codex metadata cached by an earlier version can still give a session the wrong folder until the
cache entry is rewritten. Two different lone surrogates in message ids map to the same replacement and the
duplicate filter keeps one. A killed snapshot leaves a hidden staging folder until a snapshot published more
than a day later removes it. `now.py check --issues` does not report a local page whose inputs are gone. A
personal instance set up by an earlier version keeps its clone origin in the remote allowlist until the owner
edits it.

Reconsider: a user needs the recording tools from the kit, or a removed shortcut is measured as a cost a user notices.

KIT-DR-064: the release scope items (8) and (13) mention is removed; every tree uses the session scope.

### DR-042 One hook line per event; the kit's dispatcher decides what runs (2026-11-20 · amended_by:DR-045)

Decision: Claude Code's `.claude/settings.json` declares one fixed line per event the kit uses,
`sh "$CLAUDE_PROJECT_DIR/tools/hook.sh" event <Event> claude`, each with an explicit timeout: SessionStart,
UserPromptSubmit, PostToolUse (Write, Edit, NotebookEdit), Stop and PreCompact. `tools/hook.sh` starts
`tools/dispatch.py` once per event.

The runtime's adapter reads stdin once into one event record (session, working folder, event, prompt, edited
paths or unknown, the runtime's own hint that a turn-end check already stopped this turn, and its turn id),
and the kit's steps run on it in a fixed order, each in its own thread with a time budget and its failure
caught and logged: session start, the state view then due reminders; each prompt, the time then the last block
reason; an edit, the edit mark; turn end, the gate check then the delivery check; before compaction, the
compaction row. Context blocks are joined and block reasons are joined.

The launcher holds the dispatcher's output until it exits; when the dispatcher fails or passes the launcher's
limit, the partial output is dropped and the runtime's fallback goes out (at session start, the instruction to
read the state files by hand). `MOTTORI_DISABLE_HOOKS=1` gives the empty answer before Python starts, and
doctor's wiring row says so.

The tools keep their command lines; the steps call the same functions. This corrects KIT-DR-041 (7) and (13)
on one point: the delivery check is a step of the Stop event, so turning it on takes only a signal in the
config.

Codex and Antigravity: `.codex/hooks.json` declares the same five events with the same timeouts, each
`sh "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/tools/hook.sh" event <Event> codex`, PostToolUse
matching `^apply_patch$`, because Codex runs a hook in the session's folder, which may be below the root.

`.agents/hooks.json` declares one hook named `kit` with SessionStart (30), PreInvocation (15), PostToolUse
(15) and Stop (190), each `sh ../tools/hook.sh event <Event> agy`, because Antigravity runs a hook in the
`.agents` folder; the lifecycle events are flat lists and PostToolUse is a group matching both generations of
edit tools (`write_file`, `edit_file`, `write_to_file`, `replace_file_content`, `multi_replace_file_content`).

These command texts, their timeouts and their positions in the file are fixed: Codex stores each approval
against the hooks file's absolute path, the event, the group and handler position, the command text and the
timeout, so changing any of them makes every Codex user approve the hooks again. What runs changes only inside
the dispatcher.

The Codex adapter reads Claude Code's field names plus `turn_id` and takes edited paths from the patch headers
(`Add File`, `Update File`, `Delete File`, `Move to`) relative to `cwd`; a patch without them marks the turn
with paths unknown, so the turn-end check measures the whole tree. That misses two things: a Markdown file Git
ignores, whose links the check reads only when an edit names the file, and the file's tie to this session, so
a broken link in a document another session edited within the hour is left to that session. Its answer has
Claude Code's shape.

The Antigravity adapter takes `conversationId` as the session, treats only the first model call of a prompt
(`invocationNum` 0) as the per-prompt event, runs the turn-end steps only when `terminationReason` is
`NO_TOOL_CALL`, and reads `Path` or the older `TargetFile` of an edit tool; its answers are `injectSteps` with
a system message, `{"decision": "continue", "reason": ...}` for a block, and `{}` otherwise, also from the
launcher when switched off or failing. The delivery check stays a Claude Code step.

A finding blocks once per turn in every runtime: the dispatcher keeps its own stamp beside the gate's markers
in the checkout's Git folder (`mottori-dispatch-stamp`, so it is never an untracked file), keyed by runtime
and session, holding the turn key (the runtime's turn id, or the dispatcher's count of prompts where there is
none) and the findings still open in that turn: the gate's issue ids, read from the pending entry it has just
written, and a hash of any other block reason, so fixing one of the gate's issues does not make the others
new.

The same finding at a later turn end of the same turn does not block again and is named once at the next
prompt, unless the gate's own pending line already says it; a finding that is gone is dropped, so a Stop that
comes without the runtime's hint blocks it again if it comes back in that turn.

On Codex and Antigravity as captured, and on Claude Code as its hook reference describes, every Stop after a
kit block carries that hint (Claude Code's and Codex's `stop_hook_active`, Antigravity's `executionNum` above
0). With it the gate keeps whatever it finds pending without blocking, so a new or returning gate finding
later in a blocked turn is named at the next prompt and measured again at the next turn's first Stop, and the
delivery check does not judge that Stop at all; an entry unchanged for seven days is dropped, and the file is
written only when an entry changes.

When the stamp cannot be read or written, the runtime's own hint alone decides; Antigravity's
`continuationActive` stays false, so its hint is `executionNum` above 0, which the capture shows at every Stop
after a continuation.

doctor, tools/harness.py, `tools/hookdiag.py` and the context budget read all three files through
`hookdiag.declared`, `hookdiag.ROLE_EVENTS` maps the roles per runtime, and doctor has a wiring row for
Antigravity. `.gitignore` tracks `.agents/hooks.json` and, under `.agents/`, otherwise only the four skill
folders of the next paragraph. This also corrects KIT-DR-020 (Codex now has a turn-end hook) and KIT-DR-029
(the coverage warning no longer names Claude Code as the only runtime with the turn-end gate).

Antigravity state and commands: Antigravity starts no SessionStart for a continued conversation and sends no
event for a compaction; the capture's one sign of a compaction is a new `CHECKPOINT` row in the transcript. So
at the first model call of a prompt the dispatcher injects the state when this conversation has not received
the current one: the stamp keeps, per conversation, a hash of the state text it last gave and how far it has
read the transcript.

The state goes in when its text differs from that hash (another session or this one logged, or a day passed)
or when a `CHECKPOINT` row appeared since; a compaction is then recorded first (`tools/now.py precompact`'s
row, runtime agy), so the state given already holds it. No other Antigravity event writes that row; an
ordinary Stop records no compaction. The offset read is saved before that row is written, so a step that
overruns its budget records the compaction once and the next prompt gives the state.

A prompt whose state is unchanged gets none, a conversation the stamp never saw gets it at its first prompt,
and the state is given only after the stamp has recorded it, so a stamp that cannot be locked or replaced
gives none and cannot repeat the state at every prompt; a stamp that cannot be parsed starts again empty, so
each conversation gets the state once more.

The cost is one build of the state text per prompt and one more stamp write when something changed. The build
grows with the system state rows of the journal, such as compaction rows: each is compared with the compaction
marker in both languages, and each comparison looks up the configured language again.

On synthetic journals of 3,000 rows a build took about 35 ms when they were ordinary event rows and about 520
ms when they were system state rows, the same whether they sat in one month or eight; a build that overruns
the step's budget is abandoned and logged, and that prompt gets no state; the state is recorded as received
only while the step is still inside its budget, so a step that ends too late leaves it to the next prompt; a
session that logs often gets the state again after each such turn. The step has a one-second budget, and the
time step's budget is now one second, so a prompt's steps stay inside the launcher's ten seconds.

The kit's four commands reach Antigravity as skills: tools/harness.py writes `.agents/skills/<name>/SKILL.md`
for now, recall, dossier and garden from the same `.claude/commands/` file Claude Code loads, with a `name`
and `description` header and the argument placeholder replaced by a plain description of what the user gave;
the header follows the language of the body, so the tracked files do not change with a user's shell.
`harness.py install agy` writes them, `harness.py check` reports a stale one, and `.gitignore` tracks those
four folders and nothing else under `.agents/skills/`. The garden skill still names Claude Code's workflow
tool.

AGENTS.md rule 2 says what to do when no state block arrived (run `python3 tools/now.py context`, and tell the
owner once that hooks are not running and the step doctor names), and rule 5 says deliverables go into the
workspace, not a runtime's own artifact folder; the number of rules is unchanged.

Arming, the check by hand and the delivery check: doctor has one arming row per runtime that needs a one-time
step. `hooks · codex armed` asks Codex's hooks/list; `hooks · agy armed` reads Antigravity's `/hooks` listing
in print mode (`agy -p /hooks --output-format json`, no model turn) and the `trustedWorkspaces` key of
`~/.gemini/antigravity-cli/settings.json`, because print mode runs the hooks of a folder nobody trusted, so
the listing alone proves only that they are loaded. A trusted folder above the checkout counts, as the
binary's function names suggest; that is not measured.

Each row is a pass when every required role is listed and trusted, a warning that names the exact step
otherwise (Codex: start `codex` in the folder, trust it, then "Trust all" on the hooks review; Antigravity:
start `agy` in the folder and answer "Yes, I trust this folder"), and not applicable when the program is
absent. Claude Code needs no such step, so its wiring row stands for it.

Doctor keeps each verdict in the checkout's Git folder (`mottori-runtime-arming`); at session start one line
names the other installed runtimes doctor last found unarmed, read from that file with no probe, and a runtime
whose own session starts has its stale verdict dropped.

`python3 tools/gate.py manual-check` judges the tree as a turn-end check would, for a runtime whose turn-end
hook does not run: it prints the checks run and PASS (exit 0), BLOCK with the reason (1) or UNCHECKED with the
reason (2, a checker failed or the baseline is absent or broken). It reads the edit list but clears no edit
entry and no session's block and never tightens the baseline, so a file it reports is still judged at the next
turn end.

The delivery check stays a Claude Code step: the Codex transcript fixture has no tool call row, because the
captured session made none, so a reader that finds a reread cannot be written from it; Antigravity's is not
built.

Context: a vendor's hook file should only say that an event happened in that runtime, so a kit update never
changes a declared command; Codex skips a project hook until its exact command text is approved. Where the
build specification and the capture record (system/dev/runtime-capture.md) differ about what a runtime sends,
the capture wins; the only difference found was the names of Antigravity's edit tools, and the matcher holds
both.

Measured in one fresh instance with the previous settings beside the new, whose separate processes start in
parallel as Claude Code runs them, fifteen runs each with old and new taking turns, medians of six rounds:
session start took 120 to 123 ms against 108 to 127 for the two old lines, from 6 ms less to 13 ms more, and
12 or 13 ms more in three rounds, because the dispatcher imports the state and reminder steps in one process
(an independent rerun gave 0, 10 and 12 ms more); each prompt 118 to 120 against 119 to 124, an edit 133 to
138 against 135 to 138, turn end 386 to 393 against 385 to 394, before compaction 105 to 108 against 106
to 108. doctor in a fresh instance shows the same rows before and after.

With an owner's own SessionStart line before or after the event line, its wiring, command validity and
failure branch rows pass, because they test the line that names SessionStart and the runtime, wherever it
stands; an event line for another event or runtime does not satisfy the wiring row. The compaction simulation
likewise runs only the kit's PreCompact event line when an owner's own PreCompact line stands beside it, and
fails, saying none is the kit's, when there are several PreCompact lines and none is the kit's event line.
Decided by the maintainer's assistant under the maintainer's delegation of reversible decisions.

evidence: test:tools/tests/test_dispatch.py::test_claude_adapter_reads_each_event_shape ·
test:tools/tests/test_dispatch.py::test_a_partly_fixed_gate_block_does_not_block_again_in_its_turn ·
test:tools/tests/test_dispatch.py::test_answers_are_merged_in_order ·
test:tools/tests/test_dispatch.py::test_a_failing_or_slow_step_does_not_cost_the_state_block ·
test:tools/tests/test_dispatch.py::test_steps_get_one_parsed_payload ·
test:tools/tests/test_dispatch.py::test_launcher_answers_whole_or_falls_back ·
test:tools/tests/test_dispatch.py::test_launcher_drops_an_overrunning_dispatcher ·
test:tools/tests/test_dispatch.py::test_declared_lines_and_time_limits_agree ·
test:tools/tests/test_bypass_pins.py::test_h1_h05_sessionstart_failure_has_json_fallback ·
test:tools/tests/test_bypass_pins.py::test_h1_h06_delivery_check_needs_only_its_config ·
test:tools/tests/test_doctor_json.py::test_precompact_simulation_passes_for_both_runtimes ·
test:tools/tests/test_context_budget.py::test_hooks_that_are_not_measured_are_counted ·
test:tools/tests/test_hook_runtime.py::test_doctor_accepts_own_session_hook_beside_event_line ·
test:tools/tests/test_dispatch.py::test_codex_and_agy_fixtures_pass_through_both_adapters ·
test:tools/tests/test_dispatch.py::test_each_finding_blocks_once_per_turn ·
test:tools/tests/test_hookdiag.py::test_static_report_keys_each_kit_event ·
test:tools/tests/test_dispatch.py::test_state_reaches_each_runtime_and_agy_again_only_when_it_missed_it ·
decision:KIT-DR-063 (removed test
tools/tests/test_agy_skills.py::test_agy_skills_are_the_command_bodies_with_a_header) · decision:KIT-DR-063
(removed test tools/tests/test_skill_parity.py::test_committed_agy_skills_have_exact_parity) ·
test:tools/tests/test_dispatch.py::test_a_moved_ignored_document_with_a_broken_link_stops_its_turn_once_in_each_runtime ·
test:tools/tests/test_dispatch.py::test_doctor_names_each_runtime_armed_unapproved_or_absent_and_session_start_says_so_once

Rejected alternatives: a runtime's hint as the only guard (Antigravity's `continuationActive` is false at
every Stop, so a block would loop to the runtime's limit; the stamp still holds a finding to one block when a
hint is missing); a hash of the whole block reason as the finding (the gate names all its open issues in one
reason, so fixing one of them made the rest a new finding of the same turn); the gate's pending marker as the
stamp (the gate can pass while the delivery check blocks); a `|| printf` fallback in each declared line (the
line would change with its text, which asks Codex for approval again; the launcher holds the fallback); a
process per step inside the dispatcher (that start-up cost is what one process removes); reading the
launcher's limits from the settings file (the launcher runs before Python, and sh cannot read JSON); the state
at every Antigravity prompt (a message given stays in the conversation); Antigravity's resume notice in the
transcript as the sign of a continued conversation (a vendor's wording, seen in one capture).

Boundary: a deleted `tools/hook.sh` gives no fallback; the runtime shows the hook error. A step past its
budget is abandoned and ends when the dispatcher exits. The fallback text is English in every instance,
because the launcher cannot reach the catalog without Python.

When the user's own hooks already have a time hook (`~/.claude/settings.json` for Claude Code,
`~/.codex/hooks.json` for Codex), the time step adds none, so a prompt gets the time once.

The Stop steps run one after another, where Claude Code ran the two separate lines in parallel: with delivery
on, its transcript scan now adds to the gate's time instead of overlapping it. In an instance with delivery on
and a 25 MB transcript, the gate alone took about 390 ms and delivery about 200 ms; turn end gave medians of
504, 508 and 514 ms in three rounds against 517, 517 and 521 for the two parallel processes, and the added
cost grows with the transcript.

Each prompt and turn end also takes the stamp's lock and reads its small file; the gate finds the Git folder
of a plain checkout without starting git, so this costs medians of 0.04 ms for a Codex prompt or turn end
without a finding and 0.22 ms for an Antigravity prompt, whose count is written.

A Codex user who has not approved the changed lines gets no kit hook at all until then; doctor's
`hooks · codex armed` row says so and names the step.

Reconsider: a runtime is measured to take longer per event than the separate processes did, or a step needs a
process of its own, or a runtime changes the inputs the capture recorded.

### DR-043 One way to ask another model: a Gemini worker, per-runtime worker settings, a copy without the private area, and the network per call (2026-11-21 · amended_by:DR-073)

Decision: this amends the worker contract of KIT-DR-007. `tools/fresh_worker.py --runtime gemini` runs the
Antigravity CLI in print mode with the options the capture showed to answer (system/dev/runtime-capture.md):
`--output-format json`, `--sandbox`, `--mode accept-edits` (never the default automatic mode, never the flag
that skips permission checks), `--disable-slash-commands`, `--print-timeout` set to the run's timeout, and a
one-run `--settings` with `permissions.deny` for `write_file(*)` and `unsandboxed(*)`, so the worker is
read-only and prints its answer. A non-empty `denied_actions` or an empty `response` is a failed run (status
`failed`, exit 1) whose receipt names the reason, because agy exits 0 in both cases. The conversation id goes
into the run record.

Every worker's environment sets `MOTTORI_DISABLE_HOOKS=1` and drops the other vendors' variables
(`CLAUDE_`/`ANTHROPIC_`, `OPENAI_`/`CODEX_`, `GEMINI_`/`GOOGLE_`/`ANTIGRAVITY_`). One config key, `workers`,
holds optional entries per runtime: `model`, `effort`, `where` (`instance` or `copy`) and `web_in_instance`;
`tools/config.py` refuses any other key or value by name. Absent means the earlier behaviour for claude and
codex and a copy for gemini; the variables `MOTTORI_FRESH_WORKER_CLAUDE_MODEL`,
`MOTTORI_FRESH_WORKER_CODEX_MODEL` and `MOTTORI_FRESH_WORKER_CODEX_EFFORT` still override it, and only
`MOTTORI_FRESH_WORKER_GEMINI_BIN` is new, for the program's path.

A copy is a folder from the system's temporary place, refused if it lies inside the instance, holding the
tracked files and the untracked files Git does not ignore as they are on disk, so a draft written this turn is
seen; it has no `.git`, no symlink, no file reached through a symlinked folder and no path
the model-send policy denies, its files are APFS clones where the file system allows (a large instance costs
time, not disk), and it is deleted when the run ends. A copy keeps nothing, so a copy run refuses
`--write-prefix`, `--expect` and `--worktree`.

`--web` gives one call the network and its runtime's web search: Claude gets `WebSearch` and `WebFetch`,
approved by name; Codex gets `web_search="live"` and command network in the same workspace-write sandbox;
Gemini's rules drop the deny of `read_url(*)` and `execute_url(*)`. A `--web` run works in a copy, unless that
runtime's `where` is `instance` and `workers.<runtime>.web_in_instance` is true.

Codex's workspace-write sandbox reads the whole disk (measured with `codex sandbox`), so a copy does not keep
the private area from a Codex worker: `codex --web` is refused unless the owner set that switch, and the
refusal names claude or gemini with `--web` as the next step. A Codex worker in a copy passes
`--skip-git-repo-check`, since a copy has no `.git`.

A worker's environment has no `OLDPWD` or `CLAUDE_PROJECT_DIR`, and its `PWD` is its own folder. Without
`--web` every worker is offline as before, so a loop's workers stay offline whatever the config says. The
receipt names `where`, `network`, `model` and `effort`; Gemini's network without `--web` reads
`off (unverified: agy search)`. A Codex failure whose stderr says `401 Unauthorized` or `status 401` names
`codex login`.

`tools/ask.sh <runtime>[,<runtime>] <prompt-file>` asks one runtime, or two in parallel: each worker prints
its run id when the run record exists, and ask.sh prints both and logs them in `system/debate/_dispatch.log`
before it waits. `tools/ask_codex.sh` is a thin wrapper over it with the same options and variables. A refused
prompt names the rule and the next step, and so does `ask.sh --help`. The debate template gains two lines (the
caller answers a round's strongest objection before it closes; a guest's verdict is collected before it sees
another's) and the debate page a host procedure per runtime.

Context: the owner asked for the three runtimes to feel the same and for models to argue without him carrying
messages, with as little dependence on one vendor's features as possible. A copy holds no private file, which
a text check of the prompt cannot promise, and the earlier worktree mode lives inside the private area and
points back at the repository. A fixed offline cap meant a model asked to check a fact could not open the
documentation; the owner asked on 11/20 whether forcing that limit was the best the kit could do. Decided by
the maintainer's assistant under the maintainer's delegation of reversible decisions.

evidence:
test:tools/tests/test_fresh_worker.py::test_gemini_worker_reads_a_copy_without_the_private_area_and_fails_loudly_when_denied ·
test:tools/tests/test_fresh_worker.py::test_web_runs_in_a_copy_unless_the_owner_switch_says_instance_and_is_off_without_it ·
test:tools/tests/test_fresh_worker.py::test_ask_runs_two_runtimes_at_once_and_each_receipt_names_its_model ·
test:tools/tests/test_fresh_worker.py::test_codex_default_model ·
test:tools/tests/test_memlib_journal.py::config_cases

Rejected alternatives: the prompt on agy's stdin (it needs the stream format on both sides, whose result shape
the capture did not record); plan mode (not an answer mode: it writes a plan and asks for approval); a Gemini
worker in the instance by default (the URL rules are read from the binary, not measured, so the copy is the
floor); an archive of the last commit as the copy (it would hide a draft written this turn); a new variable
per setting (one config key replaces them; the old variables stay as overrides); a debate engine; a Codex
permissions profile that denies reads of the instance (`codex sandbox` 0.169.1 honoured a
`permissions.<name>.filesystem` deny, but it was not measured through `codex exec` and older builds may not
know the key).

Boundary: the names `read_url`, `execute_url` and `unsandboxed` come from the agy 1.5.13 binary's strings, not
from a run, and whether `read_url(*)` also stops the built-in web search is not measured, so the receipt says
unverified; whether Claude's Read tool or agy's tools can read outside the copy is not measured either; the
one-run `permissions` value may replace the user's saved rules for that run instead of adding to them
(top-level replacement was measured for the trusted folder list).

The prompt reaches agy in its argument list, so a prompt near the system's argument limit fails to start, with
the error in the receipt, and other local users can see it in the process list. agy keeps every worker run in
the user's Antigravity history. agy's usage object was not captured, so only its raw form is certain.

A copy walks every tracked and unignored file per run; on APFS each is a clone (3,000 files took 0.4 s in a
synthetic tree, so an instance of about 36,000 files is a few seconds), elsewhere a full data copy. The host
procedures say that Codex and Antigravity must run `ask.sh` outside their sandboxes; neither approval was
measured here.

Reconsider: a real run shows a Gemini worker answering with a write or a URL action allowed, or agy changes
its envelope or rule names, or copies grow slow enough to matter.

### DR-044 Notes between sessions, and recall over Antigravity transcripts (2026-11-21 · active)

Decision: `tools/notes.py` keeps short notes from one session to the others on the same checkout, in
`_private/notes/notes.jsonl` beside the reminder store, written under its lock and replaced whole.
`notes.py add TEXT [--for TOPIC]` stores a note of at most 240 bytes (or a path that says more) with its id,
time and writer; `notes.py done ID WHAT` marks it taken and says what was done.

The dispatcher's session-start and prompt steps show each session the notes it has not been shown, once: at
most five, 600 bytes together, after a heading that says a note is data with who wrote it and when,
never the owner's approval. Nothing is printed when there is nothing new. A note not taken expires after seven
days. An unreadable line in the store is skipped, counted beside the notes shown, and kept when the store is
rewritten.

The writer is named from the shell's variables only when one runtime's are present, because a runtime's shell
also inherits those of a runtime that started it; only Codex's `CODEX_THREAD_ID` was measured to equal the
session id its hooks receive, so only a Codex writer is not shown its own note.

A run asked for through `tools/ask.sh` leaves a finish note when it ends (`fresh_worker.py --finish-note`,
which ask.sh passes): it names the run, its status and the receipt command, and is shown once, to the next
session that prompts in this checkout, or, when the asking shell is a Codex session, only to that session.

A session relays the owner's words that belong to other work as a note, quoted exactly, marked as his and with
where the original is (`system/rituals.md#entry`). This does not restore the leaving-session note that
KIT-DR-031 withdrew: no note is written because a session ends.

`tools/recall.py` reads Antigravity CLI transcripts
(`~/.gemini/antigravity-cli/brain/<conversation>/.system_generated/logs/transcript.jsonl`, source `agy`): the
typed request without its wrapper, the model's answers, and its system rows and compaction checkpoints as
system and summary records. Their rows name no folder, so a transcript is scoped by the conversation index
beside `brain/` (`conversation_summaries.db`, column `workspace_uris`); a transcript the index does not place
is skipped and counted in the scope line and in a notice. doctor has a row that warns when Codex or
Antigravity is installed and recall's sources hold none of its transcripts.

The notes step has a one-second budget at session start and at a prompt; to keep each event's steps inside the
launcher's limit, the reminder step's budget goes from five seconds to four (its lock wait is one) and the
gate's resume step's from five to four (it only reads the gate's markers).

Context: the owner hops between sessions and runtimes on one folder and said the three runtimes should feel
the same. Words he gives one session about another session's work had no way to reach it, and a requested run
that ends after its session stopped waiting was found only by looking. recall read Claude Code and Codex only.
`decision:KIT-DR-031`.

evidence:
test:tools/tests/test_notes.py::test_a_note_shows_once_in_each_other_runtime_and_not_after_it_is_taken ·
test:tools/tests/test_notes.py::test_limits_unreadable_lines_and_expiry ·
test:tools/tests/test_fresh_worker.py::test_ask_runs_two_runtimes_at_once_and_each_receipt_names_its_model ·
test:tools/tests/test_recall.py::test_agy_transcripts_are_scoped_by_the_conversation_index ·
test:tools/tests/test_doctor_json.py::test_runtime_transcripts_row_says_so_for_an_installed_runtime_with_none

Rejected alternatives: a vendor's session messaging (each runtime has its own or none, and the kit stays apart
from them); a note at every session end (KIT-DR-031); scoping Antigravity transcripts by the hook's `cwd` (it
covers only conversations where the hooks ran); naming the writer from inherited variables.

Boundary: the index's table and id column were not read in the capture, so an index row is tied to a
conversation by any value equal to the conversation id; if Antigravity changes the index, every transcript is
counted as not placed and none is searched by default (`--all-instances` still reads them). The tests run the
captured transcript and hook inputs through stand-ins, not real sessions. A Claude Code or Antigravity writer
is shown its own note once. A finish note for a session that did wait is shown to the next session that
prompts, which may be another. Notes live in `_private`, so a worker running in a copy cannot read them.

Reconsider: Antigravity changes its index or transcript folders, or notes are written for routine handoffs
instead of the owner's words.

### DR-045 The agent sees what is running in the background, in one line (2026-11-20 · active)

Decision: `tools/work.py` adds three steps to the dispatcher of KIT-DR-042. At turn end, before the gate, it
saves the runtime's list of background tasks still running (shell commands, subagents, workflows) per session
in `.git/mottori-work/`, keeping when each task was first seen; a turn end with nothing running keeps only its
time, which bounds the window of a workflow launched later.

At session start, after the reminders, and at each prompt, after the last block reason, it adds one line per
session of this folder that has something running: each task, how long it has run, when its output last moved
and, for a workflow, the agents finished per phase, read from the journal of its run.

No task names its run, but the runtime keeps each launch's script beside the runs under the workflow's name,
so the run is the newest launch of that name after both the machine start and the last turn end that did not
list the task, and before the turn end that first saw it; when that window holds more than one launch of the
name, or that turn end first saw two tasks of the name, as when a later launch returned within the turn and
would be the newest, the task gets no counts. Only that journal is read, so the cost does not
grow with workflows that already returned, and a workflow between phases keeps its counts and its signs of
life.

At most four tasks per session are named and the rest counted; when the lines together pass 600 bytes, the
longest line names one task fewer at a time, down to its count alone, so every session keeps its line within
the 600 bytes; only the line that gives up a name is rendered again, so the cost grows with the tasks shown
and not with their square.

A shell task whose output ends with the runtime's exit marker, a workflow whose result file exists and a task
the runtime has just reported finished are not called running. Another session's task is shown only while its
output moved in the last 30 minutes. A snapshot older than the machine's start is reported once to its own
session and once to the others as cut off by a restart; a hand run of the command and a doctor probe show it
to no session, so they mark nothing as told and remove nothing.

Nothing running adds nothing. At a prompt the line is added only when what it says, durations aside, changed
since that session last saw it; session start always adds it, since a new context holds no earlier line. No
task's output text is ever added, and a subagent's output, which is a link to its conversation record, is only
timed, never opened. Any error or unknown input ends in silence, and a prompt or session start whose input
names no valid session adds nothing.

Only a runtime whose turn-end input carries the task list saves one (Claude Code today); a session of another
runtime still sees what other sessions run. `"work_line": "off"` in the config switches every step off; any
other value leaves them on.

Context: the owner starts long jobs behind a session, moves to other topics or to other sessions on the same
folder, and comes back asking how far a job is. Claude Code already gives its turn-end hook the running list
and wakes a live session when a task ends; it does not show progress without a tool call, what a restart cut
off, or what another session runs.

Real headless sessions (Claude Code 2.1.292, model opus, a fresh kit instance made by the quick start, each
run a short fresh session) compared three designs: off, a line when it changed, and a line at every prompt.
Five scenarios ran twice per design, 30 runs: a background shell job asked whether it is going well, a
two-phase workflow asked how far it is, an unrelated question right after a job started, five status questions
in about three minutes, and a second session on the same folder asked what is running.

Over the 16 status answers per design, the answers with no tool call were 0 with off, 4 with the on-change
line and 2 with the every-prompt line; mean tool calls 1.3, 1.0 and 1.1; mean output tokens 402, 309 and 275;
mean cache-read tokens 81,900, 71,900 and 75,900; seconds to the first text 8.2, 8.6 and 6.9. The difference
is the workflow question: with either line no tool call, about 3 s to the first text, 64 to 80 output tokens
and 36,500 to 43,100 cache-read tokens, against one tool call, 7.0 to 7.7 s, 448 to 552 output tokens and
86,300 cache-read tokens with off.

For the shell job the model read the output in every design to give the step, since the line carries no output
text; only at the first status question of each on-change run did it answer from the line, without the step.
The second session ran three or four commands in every design, although with the line it named the
other session as the one that started the job. Every answer was right, no design brought a job up in the
unrelated question, and twenty prompts with nothing running added 0 bytes in every design.

The on-change line is the default: it answers the workflow question without a tool call as the every-prompt
line does and adds the line only when it changed, so the every-prompt mode was removed. Two wordings of the
phase counts were tried on the workflow question with the on-change line, two runs each; both relayed the
counts, but the answers took 74 and 80 output tokens with the instruction to give the counts phase by phase
and 127 and 173 without it, so the instruction stays.

Measured through the launcher in a fresh instance holding 200 snapshots, each with a shell task whose output
just moved and a workflow whose journal has an agent still working, the line against off, each value the
median of three runs, two rounds, at a load average near 4 from other work on the machine: session start added
62 to 69 ms and each prompt 60 to 67 ms when each workflow pairs with one launch and its journal is read, and
48 ms and 41 to 44 ms when each session's window holds twenty launches of the name, so no journal is read. 200
snapshots that hold only a turn end with nothing running added 5 to 14 ms and no text.

Before the pairing by launch script the same setup gave 43 to 52 ms at session start and 42 to 48 ms at each
prompt, also with 3,000 empty folders under `~/.claude/projects`, turn end within noise (0 to 6 ms) and a peak
resident memory of 21.7 MB for the hook process; turn end and memory were not measured again. The module never
lists project folders, so their number does not change the cost. Decided by the maintainer's assistant under
the maintainer's delegation of reversible decisions.

evidence: test:tools/tests/test_tasks.py::test_line_names_each_task_its_age_and_phase_counts ·
test:tools/tests/test_tasks.py::test_restart_other_sessions_and_switch ·
test:tools/tests/test_tasks.py::test_errors_and_unknown_input_are_silent ·
test:tools/tests/test_dispatch.py::test_declared_lines_and_time_limits_agree ·
test:tools/tests/test_context_budget.py::test_hooks_that_are_not_measured_are_counted

Rejected alternatives: a hook on every tool call that records what was started (the turn-end input already
carries the list); reading a task's output to show its last step (the output text would reach the context); a
second setting for the mode.

Boundary: not measured are long sessions, a replay over the owner's recorded status questions (it needs his
conversation transcripts), Linux and Codex. To fit the launcher's limits beside the notes, arming and
Antigravity steps of the later runtime records, the step budgets of KIT-DR-042 changed: the reminder step has
2 s and gate resume 3 s, and the work steps 2 s at session start and turn end and 1 s at a prompt. A folder
outside Git saves nothing. `python3 tools/context_budget.py` does not run the work steps; it notes their limit
instead.

Reconsider: a long-session or replay measurement, or a measured status question that the line did not answer.

KIT-DR-065: the work step at session start has 1 s, not 2 s; the `index` step of KIT-DR-055 runs before it and
has the other second (`tools/dispatch.py`).

### DR-046 Searching the owner's words: a derived store, a word list, a short-reply list, time limits, and an optional local list by meaning (2026-11-21 · amended_by:DR-055)

Decision: a search of the owner's words (`find --role user`, any time limit, or a list line's locator) answers
from a derived store of what he typed, the file `recall-store.json` under `_private/state/`, which a search
brings up to date for at most 3 seconds and `recall.py index` builds whole; other searches read the
transcripts as before.

1. The reader takes messages typed during a turn (queued commands of human origin) and leaves out rows another
   origin wrote.
2. The word list ranks his messages by BM25 over words and character pairs; scripts without reliable spaces
   give pairs, not words.
3. A reply of 45 characters or fewer is kept with the last 300 characters of the assistant's text before it
   and listed apart, because mixed into the main list such entries pushed his own statements out.
4. `--before`, `--near`, `--until` and a `--since` with a time list what he typed by time, nearest first.
5. Every search ends with a line saying what was searched, and a query of one or two words gets one line
   advising a full sentence.
6. The list by meaning is off unless `instance.recall_meaning` names an endpoint and a model. The endpoint
   must be on this machine (127.0.0.1, localhost or ::1), no proxy and no redirect are followed, and one
   protocol is spoken (an OpenAI-compatible embeddings route), with the standard library only.

   Messages are cut into pieces of 800 characters stepping 640, embedded with the document prefix, kept at
   unit length as signed 8-bit integers, and a message scores by its best piece; a short reply gets one more
   vector of the text before it and the reply, scored only for the short-reply list. A setting of the wrong
   shape turns off this list alone, and a search and `recall.py index` each say in one line what it needs; the
   rest of the configuration stays in force.

   A search prints 8 lines by meaning with their similarity, then 4 by words not already shown (half of
   `--max` when that is more); a message the word list would also show is marked `[both]`; short replies
   picked by meaning show their similarity too. When the endpoint does not answer within 2 seconds, or gives
   no embeddings for another reason (an HTTP error, or a redirect, which is not followed), one line says why
   and the word lists are printed alone. A search by time makes no embedding call. Settings changes rebuild
   the vectors and say so.

   After the query, which has 2 seconds of its own, a search embeds what is new for at most 3 more seconds: no
   request starts after that bound and none runs past it, whether the endpoint stalls or sends its answer
   slowly. `recall.py index` embeds the rest, waiting up to 30 seconds per request, can run from two processes
   at once (the second waits), and prints the state, which names an endpoint a search would refuse.

Context: before this, a search scanned every transcript on each call and matched the query as one literal
phrase. On the maintainer's own history (119 past statements, each with queries written beforehand in several
forms; a hit means the statement is among the lines shown, one query each), the literal phrase found 0 of 119
by a full question and 75 of 119 by a tidied quotation.

Measured with this code, the list by meaning on, 8 lines by meaning and 4 by words: full question 111, full
question with keywords 113, keywords 89, one distinctive word with the gist 114, tidied quotation 119, his own
way of referring back 86; the lines set before building were 100, 100, 85, 108, 115 and 85. The word list
alone (8 lines) found 75, 84, 55, 112, 119 and 71. Of 40 decisions given as a short reply, 28 were in one of
the lists (line 28).

Over 714 searches with the model loaded, a search took 1.03 seconds at the median and 1.33 at most (line 1.5);
the first search after the model had unloaded took 2.09 seconds (line 3). The first build took 273 seconds: 35
for the store, the rest to embed 10,135 pieces and 3,308 short replies; the tool's largest resident memory was
about 400 MB in that build and about 350 MB per search.

On 30 topics never discussed, the best similarity was 0.31 to 0.52 (median 0.38); for the full-question form
of the 119 statements it was 0.38 to 0.74 (median 0.52), so the two ranges overlap. Decided by the
maintainer's assistant on the maintainer's design brief of 2026-11-20; the maintainer may reverse it.

evidence:
test:tools/tests/test_recall.py::test_claude_meta_transport_is_not_owner_but_quoted_feedback_survives ·
test:tools/tests/test_recall_store.py::test_store_reads_only_what_was_added_and_follows_the_files ·
test:tools/tests/test_recall_store.py::test_word_list_scores_words_and_character_pairs ·
test:tools/tests/test_recall_store.py::test_short_replies_have_their_own_list_with_the_text_before_them ·
test:tools/tests/test_recall_store.py::test_time_limits_list_what_he_typed_nearest_first ·
test:tools/tests/test_recall_store.py::test_list_by_meaning_is_off_unless_set_and_never_leaves_the_machine ·
test:tools/tests/test_recall_store.py::test_list_by_meaning_is_built_added_to_and_rebuilt ·
test:tools/tests/test_recall_store.py::test_endpoint_down_leaves_the_word_lists_and_lines_fit ·
test:tools/tests/test_recall_store.py::test_eight_bit_vectors_order_pieces_as_the_float_vectors_do Rejected
alternatives, each with the number that decided it (counts of 119, question or keyword form unless named): one
fused ranking of both lists (86 against 93 for the list by meaning alone, three tries); scoring adjacent word
pairs or pairs across a space (77 against 76); merging several phrasings into one query (73 against 93); a
similarity cutoff that hides weak results (absent topics reached 0.46, and a line there would also have hidden
10 statements that were in the first 8); shorter vectors (256 dimensions found 78 against 93 at 768); a model
13 times larger (no better, 20 times slower to index); an exact-phrase pass pinned above better lines (the
literal phrase found 75 tidied quotations where the word list finds 119); a bundled model, a remote endpoint,
a new dependency or a background process (a stranger's install must not need them, and the owner's words never
leave the machine); an index of the assistant's text beyond the tail before a short reply (only his words are
evidence of what he said).

Boundary: the test queries were written by a model, most under a rule against his distinctive words; a single
designated statement counted as the answer though other messages may have been valid answers; topic sweeps
were judged only inside the two lists' own results; only Korean and mixed Korean-English messages were
measured, so the claim for English and other languages rests on the chosen model's public benchmark standing
and not on a measurement of ours.

Against the prototype, his own back-reference form found 86 against 94: of the 8 statements lost, 7 sat at
ranks 9 to 12 by meaning and 4 of those come back into the first 8 when only one runtime's transcripts are
searched, because the store also holds the other runtime's messages (about 44% more candidates); one had been
found by words only.

The vectors take about 13 MB for 9,000 messages, and the first build takes minutes. A low best similarity is
shown, not hidden; the reader must treat such a list as leads. A model that takes longer than 2 seconds to
load after idle leaves that one search with the word lists only, and says so; the idle time was measured on
one search only.

Reconsider: a real query log shows a form of question the lists still miss, or a model behind the same route
measures better on the same statements.

### DR-047 Saving a Claude credential probes what the workers will use (2026-11-20 · amended_by:DR-049)

Decision: `tools/claude_auth.py save` writes the file and then runs the same probe as `check`, over `env()`,
the credential the workers read. An environment `CLAUDE_CODE_OAUTH_TOKEN` keeps its precedence over the saved
file; when it is set to a value other than the one just saved, save prints one line naming it and saying to
unset it or set it to the new token, and save fails when that token does not work. The `check(token)` override
that probed the typed value is removed. The helper's printed lines and its prompt come from the catalog.

Context: the seventh wave made save probe the value just typed, so a user whose expired token sat in the
environment was told the save worked while the workers kept failing, and the only advice was to save again.
Decided by the maintainer's assistant under the maintainer's delegation.

evidence: test:tools/tests/test_claude_auth.py::test_save_writes_private_file

Rejected alternatives: letting the saved file override the environment token (an explicit environment setting
would silently stop working); printing the line when the environment token equals the saved value (nothing
overrides then).

Reconsider: the workers stop preferring the environment token.

### DR-048 The opencode adapter is withdrawn (2026-11-22 · amended_by:DR-051)

Decision: the opencode adapter that KIT-DR-015 added is removed: its `RUNTIMES` entry in tools/harness.py with
the generated state file and commands, the `refresh` and `verify` commands and their canary, the `opencode`
option of `tools/options.py`, and its catalog texts, tests and documentation. What KIT-DR-015 decided for the
registry stays: one entry per runtime, and a note for each role a runtime cannot take. KIT-DR-037 items (8)
and (19) and the opencode clause of KIT-DR-041 item (7) no longer apply. The evidence lines of KIT-DR-015,
KIT-DR-037 and KIT-DR-041 that named the tests removed here cite this record with the old test names.

Context: the adapter was never verified in a real session, and the re-review KIT-DR-015 asked for (whether
opencode sessions were used, whether the canary caught a regression) had nothing to read. A runtime nobody
runs is code and documentation every change of state rendering, commands and catalog must keep true. Decided
by the owner on 2026-11-22 with the main session.

evidence: decision:KIT-DR-051 (removed test
tools/tests/test_harness.py::test_cli_status_runs_without_an_instance_config)

Rejected alternatives: keeping the adapter marked unverified (it would still have to be kept true at every such change).

Reconsider: a fourth runtime is asked for by a real use, together with a session that shows the injected state arrived.

### DR-049 The kit speaks English only (2026-11-22 · amended_by:DR-062)

Decision: everything the kit itself says is English: tool output, check names, status words, hook messages and
the headings of the pages it renders. The language is never chosen from the locale or an environment variable.
Korean exists only as translated documents under `ko/`, including `ko/templates/`, the starter documents a
person fills in: `bash setup.sh --lang ko` copies those instead of `templates/` (the default is `en`), and
`instance.lang` records only which set setup copied. What the owner and the agent write (journal lines,
decision records, their own documents) stays in their language.

Removed: tools/i18n.py, the table of about 890 messages in English and Korean that 22 modules and three shell
scripts looked up by key; the language rule (`MOTTORI_LANG`, then `instance.lang`, then the locale) and its
copy in tools/memlib.py; the `say` helper of `setup.sh`, `tools/ask.sh`, `tools/ask_codex.sh` and
`tools/install_hooks.sh`. Each message is the English text the table held, written where it is printed.
`instance_root()` moved unchanged to `tools/paths.py`.

The Korean status words `now.py check` looked for in the memory index are the instance key
`checks.volatile_index_words`, empty by default. Words a parser must match in documents and transcripts people
wrote in Korean stay, and journals and snapshots written before are still read through the Korean forms
`tools/now.py` lists as legacy.

KIT-DR-026 is superseded, and the sentence of KIT-DR-047 that its texts come from the catalog no longer
applies. Published records that named tools/i18n.py or tools/tests/test_i18n.py lose the backticks, and their
evidence lines cite this record with the old test names.

Amended by KIT-DR-062: the kit has no Korean edition, so `ko/`, `ko/templates/`, `bash setup.sh --lang` and
`instance.lang` are gone, and starter documents come from `templates/` only.

Context: `decision:KIT-DR-026` made tool output follow a language saved per instance. Decided by the owner on
2026-11-22: the kit speaks English only.

### DR-050 The shared module memlib is cut into what it is (2026-11-22 · active)

Decision: tools/memlib.py is removed. In its place, each with one job: `tools/paths.py` says where every file
the tools read or write lives, as functions of the instance root; `tools/config.py` reads the instance
configuration and _private/state/threads.json once per process on first use, validates the configuration with
a table of rules, reads the optional blocks that turn off only their own feature (`deliver`,
`triggers.sources`, `instance.recall_meaning`, `work_line`), and migrates a configuration for setup
(`python3 tools/config.py migrate` and `get`); `tools/journal.py` reads, validates, routes and appends journal
rows and gives setup the existing rows (`python3 tools/journal.py rows` and `count`); `tools/safeio.py` holds
the one atomic write, the one lock and the file hash.

What belonged elsewhere went to its owner: remote matching and the list of files only a running instance
writes to `tools/enforce.py`; the reader of a hook's stdin to `tools/hook_input.py`, because gate, deliver and
now read it when run by hand and dispatch imports those three; the tool-run log and the hook-failure lines to
`tools/runlog.py`, because its writers (coherence, gate, linkcheck, doctor) import one another and doctor,
which reads the evidence, imports the others; the page tokens, the update-line labels and the byte clipping to
`tools/now.py`. Importing any of these modules reads no file.

Two values true only in the maintainer's workspace became keys with neutral defaults: `ledger.snapshot_extras`
(default `["README.md"]`) and `triggers.experiments` (default none). setup.sh keeps only shell steps.

The header of a new journal file names `journal_types` in `system/memory-config.json` instead of the removed
module, and doctor's row `wiring · memlib ROOT` is `wiring · instance root`. Records that cited
tools/memlib.py follow the file the cited part moved to, as KIT-DR-040 records for a path rename; the language
rule's copy that KIT-DR-049 names was removed with it, so that mention loses its backticks.

Context: memlib was imported by most tools and read the configuration and the private thread registry at
import, so rec.py, hookdiag.py and work.py kept copies of its helpers; store paths were spelled in eight
modules, the config path in four, and atomic writes were defined four times. Decided by the owner with the
main session on 2026-11-21 and 22: a module does one job, calls go one way, one fact lives in one place.

evidence: decision:KIT-DR-086 (removed test
tools/tests/test_setup_migration.py::test_v2_history_is_fail_closed_and_cannot_be_retro_promoted) ·
test:tools/tests/test_memlib_journal.py::test_journal_body_exact_boundary ·
test:tools/tests/test_memlib_journal.py::test_root_aliases_shape_fails_closed

Rejected alternatives: one module that loads on first use (it would still do five jobs); the hook reader in
dispatch.py and the run log in doctor.py (each would make two modules import each other).

Reconsider: a module of this cut needs a private name of another, or a store path is built outside tools/paths.py.

### DR-051 Hook steps, the gate, the hook check and the health check talk in data; tools/harness.py is gone (2026-11-22 · amended_by:DR-053 · amended_by:DR-064)

Decision: each step of `tools/dispatch.py` has a plain id (state, reminders, notes, arming, work, time,
resume, edited, gate, deliver, precompact, restate) and another tool finds a step only through
`dispatch.steps(event, runtime)`; the pretend command lines that served as labels, and the expressions in
`tools/context_budget.py` that recognised steps by them, are removed, so a declared line that is not the
launcher's event form is counted as an unmeasured hook. A step entry says whether it is skipped once
the answer goes to the launcher's fallback. The record that makes a block reason fire once per turn belongs to
the gate (`gate.block_once`, `gate.count_prompt`, `gate.update_turn_record`). The state step prints plain text
(`now.session_state`), and one function says whether a run is a probe (`hook_input.probe`).

`tools/dev/gate_release.py` no longer imports or is handed the gate: the gate passes it the environment and
the failure recorder, the release verdict is `gate.py release` itself, and the test log names and the test
marker live only in `tools/dev/evidencecheck.py`. `linkcheck.check()` takes its options as arguments and
returns its results.

`bash tools/install_hooks.sh --check` and `--repair` print one line per hook, a status word (current, chained,
foreign, missing, owned-drift), a tab, the path, and optionally a tab and text for a person; a hooksPath
outside the repository exits 3. A repair leaves a current hook untouched and keeps one dated backup of a
drifted one, which is also what a failed repair restores.

Old formats: the sealed baseline (schema 3) that installs of v0.10 wrote is still read and the `gate.py dirty`
command those sessions' hook lines call stays; schema 2 baselines, plain-text edit and pending markers, the
six older hook hashes and the `MOTTORI_LEGACY_HOOK_HASHES` variable are removed. A push refusal always starts
"push blocked:", and the push check uses the commit check's private-path rule.

each check of `tools/doctor.py` has an id; `CHECKS` holds (id, function, needs Git), one table gives the label
a person sees, `--json` prints the id, and a check that needs another's result asks for it by id. doctor reads
`install_hooks.sh --check` by the first two tab-separated fields of each line (status word, hook path) and the
cause of a refused model-send policy as a value from `tools/config.py`, never by a sentence.

`tools/hookdiag.py` is the one reader of the three runtimes' declaration files, and its reports are keyed on
the kit's event names in each runtime; the role names and the PreToolUse "guard", which no runtime of the kit
declares, are gone. tools/harness.py is removed: the wiring of each runtime is doctor's, the Antigravity
skills are generated and checked by `tools/agy_skills.py`, and `open`, which nothing called, is dropped.

An owner's own hook line beside the kit's line, on any event, fails no doctor row; only the kit's own lines
are judged for an absolute path. This amends KIT-DR-015 (the runtime vocabulary now comes from
`hookdiag.HOOK_FILES`) and KIT-DR-048; their evidence lines name the removed tests with this record.

Context: readers found tools deciding things by matching text other tools printed for a person (step labels,
the installer's lines), a store of the gate kept in the dispatcher, two modules calling each other's private
functions, and constants defined twice. They also found doctor matching other tools' printed sentences and its
own translated labels, a role vocabulary standing in for event names, and a registry whose status repeated
doctor's rows. Decided by the owner with the main session on 2026-11-21 and 22, step 5 of the clean-up.

evidence: test:tools/tests/test_dispatch.py::test_steps_are_found_by_plain_id ·
test:tools/tests/test_install_hooks.py::test_check_prints_one_status_line_per_hook ·
test:tools/tests/test_hook_runtime.py::test_owner_lines_beside_the_kit_lines_never_fail_doctor ·
test:tools/tests/test_install_checks.py::test_doctor_precommit_reads_the_check_status_words ·
test:tools/tests/test_doctor_json.py::test_json_schema_and_exit_status ·
test:tools/tests/test_hookdiag.py::test_static_report_keys_each_kit_event · decision:KIT-DR-063 (removed test
tools/tests/test_agy_skills.py::test_doctor_names_stale_skills_in_the_agy_wiring_row)

Rejected alternatives: keeping v0.10's plain-text markers readable (a v0.10 instance updates cleanly without
them: the next Stop measures and removes them); renaming the `gate.py dirty` command (a session started before
the pull still calls it); keeping role names beside the events (two names for one thing); judging an owner's
line for portability (it is the owner's, and SETUP invites it).

Reconsider: a tool needs a step, a hook status or a gate result in a form this record does not give, or a
runtime declares an event the kit needs under a name of its own that the kit's events cannot spell.

KIT-DR-064: `tools/dev/gate_release.py`, `gate.py release` and the test log are removed.

### DR-052 The options list reads an option the way its own tool does; a trigger row keeps only its dates (2026-11-22 · active)

Decision: `tools/options.py` judges whether meaning is on with `config.recall_meaning()`, the reader the
search itself uses, so the list shows on only what the search will use. After `on` writes the settings it
reads the option back that way. When it still reads as off, `on` puts the configuration back, says the
option's tool does not read the settings, and exits 1, as it already did when the first step fails. Empty text
values, such as the empty prefixes the search accepts, are written.

In the same step: `now.py check` judges a track document by the date on its update line, the line the page
shows, and no longer by file time; a document with no dated line counts as behind.

A trigger row stores its dates and no state: `state()` derives open, asleep, leased, fired or retired from
them, and an old row loses the field at its next save. `tools/triggers.py` no longer takes `--privacy` or
`--destination`, which it ignored (this amends KIT-DR-038 (1)), and accepts only the `date` kind of when, the
one kind it evaluates.

Setup's migration is `tools/config_migrate.py`; Git remote syntax and matching are `tools/remotes.py`. A
journal without a final newline is reported at its last line. The work line reads no boot time when no task is
running.

Context: a review found the list showing meaning as on while the search read the settings as off: the list
parsed the setting its own way, and `on` checked only the exit status of `recall.py index`, which exits 0 when
meaning is off. Readers found check() judging documents by file time while the page trusts the update line,
and trigger rows whose state repeated their dates. Decided by the owner with the main session on 2026-11-22,
step 6 of the clean-up.

evidence: test:tools/tests/test_options.py::test_on_puts_back_settings_the_search_does_not_read ·
test:tools/tests/test_options.py::test_the_list_shows_on_only_what_the_search_reads ·
test:tools/tests/test_options.py::test_on_takes_the_empty_prefixes_the_search_accepts ·
test:tools/tests/test_triggers.py::test_state_is_read_from_dates_not_stored ·
test:tools/tests/test_tasks.py::test_a_prompt_with_nothing_running_reads_no_boot_time

Rejected alternatives: removing the claim that `on` catches settings the search does not read, instead of
making it true (the list would still show on for a feature that does not work); keeping rows of an unevaluated
kind of when readable (nothing would ever fire them).

Reconsider: an option's own tool has no reader `tools/options.py` can call, or a second kind of when gets an evaluator.

### DR-053 Step 6b removes what readers found written twice or misplaced; four behaviours change (2026-11-22 · active)

Decision: this step changes what a user sees only in these. (B1) A note added with `once` by a writer whose
session is known is shown once to one other session; the writer's own entry in `seen` no longer counts as a
showing, so rows already stored get the fix too.

(B2) The receipts list shows the first line of a prompt whose body starts with "-" as written. The reader
already did: every contract block the engine wrote ends with a blank line. It keeps reading the block shape,
because the contract wording changed several times and older runs are read by that shape; a test pins today's
layout and the oldest.

(B3) `options.retention(root)` is the one reader of `cleanupPeriodDays`, for the options list and for doctor.
Doctor's rule stays: a settings file that may set the value but cannot be read, or sets a non-number, leaves
the days unmeasured, because Claude Code uses the first file that sets the key and skipping that file could
report a value Claude Code does not use.

(B4) Measuring the context writes no state: `hookdiag.unarmed_notice(root, runtime)` only reads, and the
session-start step calls `hookdiag.clear_stale_verdict(root, runtime)` for its own runtime before the notice.

The record of what a turn end already reported is `tools/turns.py`, and its marker file is
`mottori-turn-record`; this amends KIT-DR-051, which put that record in the gate. An instance updating from
the last release leaves the old `mottori-dispatch-stamp` file unused, and the one turn running during the
update may block once more on a finding it already blocked. The audit of an assistant's memory index is
`tools/memory_index.py`, which `now.py check` calls.

Smaller visible wording: a refused read material says "read material" where it said "prompt", the candidates
header of `tools/portrait.py` no longer carries the maintainer's own words, `tools/hook_canary.py`'s help
follows its docstring, and a Codex result that is not valid UTF-8 is kept as raw bytes on both paths.

Context: fresh readers of steps 5 and 6 found logic written twice (two canary readers, two retention readers,
four "inside the workspace" checks), code in the wrong module (the turn record in the gate, the memory-index
audit in now.py, trigger source patterns in config.py), results passed through globals, and sentences that
were false or too dense. Decided by the owner with the main session on 2026-11-22, step 6b of the clean-up.

evidence: test:tools/tests/test_notes.py::test_a_once_note_from_a_known_session_reaches_one_other_session ·
test:tools/tests/test_receipts.py::test_prompt_line_is_the_body_as_written ·
test:tools/tests/test_options.py::test_the_list_and_doctor_read_the_same_retention ·
test:tools/tests/test_context_budget.py::test_measuring_writes_no_arming_verdict ·
test:tools/tests/test_hookdiag.py::test_the_unarmed_notice_only_reads_and_a_starting_runtime_clears_its_own_verdict

Rejected alternatives: cutting the prompt body by rebuilding today's contract blocks (every older run would
show its header line); keeping the old marker name readable (a second reader for a record whose entries expire
after seven days); the options list's old rule of skipping an unreadable settings file (it can name a value
Claude Code does not use).

Reconsider: a run record needs the prompt body's position for a layout the shape reader cannot read, or
Claude Code changes which settings file wins.

### DR-054 What one installation owns lives in `instance/`: the boundary is a folder, not a list of names (2026-11-22 · active)

Decision: `system/` holds only the kit's documents, the same in every installation. `instance/` holds what one
installation owns: `instance/config.json` and its backups, `instance/rules.md`, `instance/rituals.md`,
`instance/decisions.md`, and the debate rounds and prompts in `instance/debate/`.

`templates/` holds the blank form of each, named like the file it becomes (`templates/config.json`,
`templates/rules.md`, `templates/rituals.md`, `templates/decisions.md`; each round is copied from
`templates/debate-round.md`), and `ko/templates/` mirrors it. Files tools generate live in `state/`:
`state/debate-dispatch.log`, state/memory-map.html and state/build-log.md. The deep-pass ledger stays private
in `_private/deep-pass/ledger.md`, created on first use from `templates/deep-pass-ledger.md`.

`.gitignore` does not restore `instance/`, so nothing there is offered for commit; it no longer names the
owner's files under `ko/system/`, and keeps one short block denying their old places under `system/`, because
an installation that has pulled the new engine and not yet moved has nothing else between those files and
`git add -A`. `tools/paths.py` defines each of these paths once.

An installation in the old layout is told so in one line at session start, by doctor and by every command that
needs the configuration, and `bash setup.sh --force` moves each file once, keeping its bytes and mode; a file
present at both places stops it. No file is left at an old place and no tool reads one. This amends KIT-DR-004
on where the instance side of each pair lives.

Frozen history, the change log sections of published versions and the bodies of records already written, keeps
the old names (unlike the renames KIT-DR-040 records, citations of these files are not rewritten), and the
link check does not report a file that the change log or the decision records name and that has since moved or
gone.

Context: `system/` held three kinds of file side by side: the kit's documents, the files one installation
owns, and generated files. `.gitignore` restored all of `system/` and denied the owner's files again by name,
in English and in Korean, so each new instance file needed new lines there, and a forgotten line would have
let the file into a commit. Decided by the owner with the main session on 2026-11-22, step 7 of the clean-up.

evidence: decision:KIT-DR-004 ·
test:tools/tests/test_setup_migration.py::test_old_layout_says_one_line_until_force_moves_each_file_once ·
test:tools/tests/test_setup_migration.py::test_old_layout_file_at_both_places_stops_the_move

Rejected alternatives: a file left at each old place pointing to the new one (two places for one fact); tools
reading the old place as a fallback (a second reader that never goes away); keeping the files under `system/`
with the deny list (each new file must join the list).

Reconsider: an installation needs a file of its own that the kit's repository must track.

### DR-055 The search reads only the owner's typed words, turns its list by meaning on with one yes, and catches up behind the session (2026-11-23 · active)

Decision:

1. A prompt the kit sent to a worker is not the owner's words in any runtime. Every worker prompt starts with
   the contract line `[fresh bounded worker contract]`, and the reader leaves out a message that starts with
   it, as it leaves out a receipt handed back, a message from another session and the dispatch prefix.
   Claude Code and Codex workers keep no transcript (`--no-session-persistence`, `--ephemeral`); an
   Antigravity worker keeps one, which only its folder kept out until now, and it leaked when the worker ran
   in the instance or in a worktree under it. The engine keeps only the openers the kit writes. An instance
   lists the openers of its own prompts as regular expressions in `instance.agent_openers`, matched at the
   start with case ignored; the template has an empty list and the update adds it.
2. `options.py on meaning`, when no server answers with the model, names the model, its size and its source;
   in a terminal it asks once, and on yes downloads the model with the server's own command (`ollama pull`),
   writes the settings and builds the index. Without a terminal it changes nothing and names the one word,
   `yes`, that added to the same command stands for the owner's yes; the assistant adds it only after he said
   yes. Without the server program it says so in one line with the command that installs it.
3. At session start, when the store or the vectors are behind, the step `index` starts one detached process
   that holds the catch-up lock until it ends, so a second session start starts none; with nothing behind it
   starts nothing. A search reads what the transcripts added for at most 3 seconds, so a message typed a
   minute ago is found, embeds missing vectors for at most 3 seconds only while no catch-up runs, never waits
   for one, and its closing line says how many messages the list by meaning holds. The work line names the
   catch-up while it runs and says its end once.
4. The vectors live in `recall-vectors.bin`: one header line, then fixed-size 8-bit records, read once into
   one buffer and appended to. An existing `recall-vectors.json` is converted once, with nothing embedded
   again.
5. `select_sources` returns a named result (rows, unverified, zst_skipped, malformed).

Context: the owner decided on 2026-11-21 and 22 that the search reads his typed words in all three runtimes
and nothing a worker was sent, that the list by meaning turns on with one yes, that the index is kept up to
date behind the session, and that one search by meaning, measured at about 349 MB on his records, was a
defect.

On a synthetic store of 10,000 pieces at 768 dimensions one search by meaning peaked at about 102 MB against
53 MB by words alone: the base64 vectors file was loaded twice per search, inside and outside the lock. After
the change the same search peaks at about 64 MB.

Its share above the search by words stays under pieces x (dimensions + 17) bytes, plus under 300 bytes per
stored message, plus 3 MB for the query's request and answer; it grows with the number of pieces times the
vector length and with the number of messages. Step 8 of the clean-up.

evidence: test:tools/tests/test_recall.py::test_claude_worker_prompt_is_not_the_owner ·
test:tools/tests/test_recall.py::test_codex_worker_prompt_is_not_the_owner ·
test:tools/tests/test_recall.py::test_agy_worker_prompt_is_not_the_owner ·
test:tools/tests/test_recall.py::test_configured_opener_keeps_a_worker_prompt_out ·
test:tools/tests/test_recall.py::test_agy_transcripts_are_scoped_by_the_conversation_index ·
test:tools/tests/test_options.py::test_the_model_is_downloaded_only_after_one_yes ·
test:tools/tests/test_recall_store.py::test_session_start_catches_up_behind_the_session ·
test:tools/tests/test_tasks.py::test_the_index_catching_up_is_quiet_and_a_failure_is_said_once ·
test:tools/tests/test_recall_store.py::test_a_search_by_meaning_holds_the_vectors_once

Rejected alternatives: keeping the owner's Korean openers in the engine (the engine holds nothing of one
owner); a literal list of openers (his two phrases would take eight entries); a search that waits for the
catch-up, or that drops its own short reading of new lines (a message typed after session start would not be
found until the next one); a catch-up that embeds while a search embeds too (the same texts sent twice);
keeping the JSON vectors file and loading it once (still base64 text per piece, parsed whole on each search).

Reconsider: a runtime keeps a transcript of a worker run whose prompt does not start with the contract line,
or a search of the owner's real history still peaks far above the measured bound.

KIT-DR-065: a message typed a minute ago is read into the store, but a search leaves out what was typed in the
last ten minutes (the turn that is asking) and says how many.

### DR-056 The folders under `tools/` and `system/` show who each file is for, and three commands get names that say what they are (2026-11-24 · amended_by:DR-064)

Decision:

1. At the top of `tools/` is what a person, an agent or a hook starts. A file that is only imported, or only
   started by another file of the kit, is in `tools/lib/`: config.py, config_migrate.py, hook_input.py,
   hookdiag.py, journal.py, memory_index.py, paths.py, precommit-hook.sh, recall_literal.py,
   recall_meaning.py, recall_store.py, remotes.py, runlog.py, safeio.py, transcripts.py, turns.py and
   worker_sandbox.py. What only a kit maintainer runs is in `tools/dev/`, which now also holds eval_recall.py.
   Tests stay in `tools/tests/`.

   Whatever the rule would say, `tools/hook.sh`, `tools/gate.py` and `tools/enforce.py` do not move: the
   runtime hook declarations call the first, and the Git hooks of every installation, and hooks an owner
   chained by hand, call the other two. `tools/dispatch.py` stays beside `hook.sh`, which starts it, and
   `tools/agy_skills.py` stays at the top because doctor imports it and a runtime tool imports nothing from
   `tools/dev/` (KIT-DR-040).
2. Every file that imports a kit module puts `tools/` and `tools/lib/` on `sys.path` itself, in two lines
   computed from its own location and written the same way at each folder depth:
   `TOOLS = os.path.dirname(os.path.abspath(__file__))` at the top of `tools/`, with one more
   `os.path.dirname(...)` for each folder below it, then
   `sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]`. A test reads every
   tool and fails when a file spells these lines another way. `gate.py` keeps the one more line that puts
   `tools/dev/` on the path for its release scope. A file that starts another tool builds that tool's path
   from the instance root as before, with the new folder in it.
3. Three commands are renamed: `tools/rec.py` is `tools/facts.py`, `tools/work.py` is `tools/tasks.py` and
   `tools/portrait.py` is `tools/person_ledger.py`. Their tests, the prefix each prints in front of its lines,
   the sentences that tell someone which command to run and the dispatcher step that runs the second (`tasks`)
   follow. Store paths, configuration keys, journal types, trigger ids and environment variables keep their
   names.
4. The specifications move to `system/specs/`: PRD-info-architecture.md, PRD-session-memory.md,
   design-memory-runtime.md and this file. The contributor page `system/dev/contributing.md` is
   `CONTRIBUTING.md` at the root. The Korean editions move the same way under `ko/`.
5. Records of the past keep the paths of their day. The change log and the entries already written in this
   file, in its Korean edition and in an instance's `instance/decisions.md` are not edited, and the link
   check does not read these files, so a file an entry names that has since moved is not reported. The one
   edit a past entry receives is the mechanical one the preamble of this file names: a test marker follows its
   renamed test. The markers that cited tools/tests/test_rec.py, tools/tests/test_work.py and
   test_portrait_ignores_future_dates cite `tools/tests/test_facts.py`, `tools/tests/test_tasks.py` and
   `test_person_ledger_ignores_future_dates`, so the release evidence check resolves every marker.
6. A group of tools that serves one job gets its own folder under the same rule: the improvement loop, which
   is not in the kit yet, sits in `tools/loop/`, with its modules in `tools/loop/lib/` and its paper stage in
   `tools/loop/papers/`.
7. An existing installation's Git hooks keep working after the pull, because the files they call did not move.
   A script of the owner's own that imports a kit module needs the two lines of (2). The hook template's
   self-check message names its new path, `tools/lib/precommit-hook.sh`; `tools/install_hooks.sh` counts a
   hook with the exact bytes of the previous template, which differed only in that path, as current, so no
   installation has to reinstall its hooks.

Context: an outside reader went through the kit twice and could not tell apart, in one flat list of 44 files
under `tools/`, the commands, the modules those commands import and the scripts only a maintainer runs. Three
command names did not say what the command is: rec.py sat between recall.py and receipts.py, "work" already
meant a company machine, the example folder and the workers, and the person ledger's own guide says a portrait
is not the goal. `system/` mixed the guides an agent reads with the design specifications and the contributor
page, and files had five ways of putting the kit's folders on `sys.path`. Decided by the owner with the main
session on 2026-11-21 and 22, step 9L of the clean-up.

evidence: test:tools/tests/test_tool_entrypoints.py::test_every_tool_puts_the_kit_folders_on_the_path_the_same_way

Rejected alternatives: moving `hook.sh`, `gate.py` and `enforce.py` with the rule (a runtime asks its user for
approval again when a hook line changes, and installed Git hooks would fail until reinstalled); a file left at
each old path that forwards to the new one (two places for one fact, and an old name that never goes away);
rewriting the paths in entries already written (an entry says what was true when it was written).

Reconsider: a hook declaration or an installed Git hook needs a file that has moved, or nothing any longer
starts a file at the top of `tools/`.

KIT-DR-064: `gate.py` no longer has a release scope and no longer puts `tools/dev/` on its path.

### DR-057 The improvement loop is an engine part, shipped off, with every value of one installation in its configuration (2026-11-24 · amended_by:DR-058 · amended_by:DR-061)

Decision:

1. The weekly improvement loop ships in the kit: `tools/loop/` with its modules in `tools/loop/lib/` and the
   papers source's scripts in `tools/loop/papers/`, the templates its model workers receive in
   `system/loop/prompts/`, its scheduler template in `system/loop/launchd/job.plist`, its document
   `system/loop/README.md` and its tests.
2. It is off, and four things are turned on one by one: `python3 tools/options.py on loop` says what each
   source sends and allows only the sources the owner chooses to send their cycle folder;
   `python3 tools/loop/loops.py run` or `start` runs or schedules a source, and starting one schedules the
   daily health check with it; `loop.landing` (off, worktree or commit) is set with
   `python3 tools/loop/loops.py landing`, which takes a yes for worktree and commit. Setup schedules nothing.
   A patch held because landing was off is never landed by a later run; its report names it for the owner to
   apply by hand.
3. The engine always refuses changes to the private area, `state/`, `.git/`, `instance/config.json` and the
   policy module, and the installation only adds to that list in `loop.never`. `templates/config.json` starts
   that list with the files that decide what the loop may do and that guard a commit (`tools/loop/`,
   `tools/gate.py`, `tools/enforce.py`, `tools/hook.sh`, `tools/dispatch.py`, `tools/install_hooks.sh`,
   `tools/lib/precommit-hook.sh`, `tools/options.py`, `.claude/`, `.codex/`, `.agents/`, `setup.sh`); the
   engine's own rule stays that at most one bundle per cycle may change only the loop's tools.
4. Nothing of one installation is in the loop's code: the runtime order of each stage, the folders left out of
   the isolated clone, the papers source's client name, contact and queries, the job label prefix and times,
   what else starts the health check, the last line of a commit landing's message, the correction groups and
   the garden's optional lens files are keys of the `loop` block, each with an engine default that
   `tools/loop/lib/loop_config.py` holds and prints. The garden reads the machine's local time.
5. macOS only for now: every macOS command sits in one module per kind
   (`tools/loop/lib/loop_macos_schedule.py`, `_alert.py`, `_process.py`, `_sandbox.py`) behind
   `tools/loop/lib/loop_platform.py`; elsewhere every command but `status` ends with one sentence, and a test
   that needs macOS goes through `testlib.macos_only`.
6. The health check the loop schedules probes no login and starts no model program; it looks at a source only
   once the source ran here or was scheduled more than eight days ago. Every landing, working-tree or commit,
   is listed in `_private/loops/LANDED.md` with its undo command. A candidate's commit check in the isolated
   clone runs in the scope the installation's own commit hook uses, though the clone lacks the instance
   configuration.
7. `/garden` is a prompt the session's own agent follows in any runtime, report-only; the JavaScript workflow
   script it ran, which worked only in one runtime's workflow feature, is removed, and the test that checked
   its prompt for KIT-DR-035 now checks the command's text.

Context: the loop ran only in its author's workspace and carried his folder names, runtime order, contact
address, schedule and time zone in its code. An outside reader was asked how a stranger should turn it on and
answered with three conscious steps (sending, scheduling, landing) plus the sending choice per source. Decided
by the owner with the main session on 2026-11-21 and 22, step 9d of the clean-up.

evidence: test:tools/tests/test_loop_way_in.py::test_on_loop_takes_a_yes_and_allows_only_the_chosen_source ·
test:tools/tests/test_loop_way_in.py::test_another_platform_refuses ·
test:tools/tests/test_loop_config.py::test_every_key_has_an_engine_default ·
test:tools/tests/test_papers_apply.py::test_a_reviewed_patch_is_saved_from_the_working_tree_and_nothing_is_written ·
test:tools/tests/test_papers_apply.py::test_refusals_name_the_path_and_each_branch_is_needed ·
test:tools/tests/test_tool_entrypoints.py::test_garden_command_carries_the_steps_and_stays_report_only ·
removed test
tools/tests/test_papers_apply.py::test_an_installations_clone_runs_the_commit_check_in_the_hooks_scope
Rejected alternatives: a `--query` option for the papers source (it has a default list on the kit's subject);
landing set by editing the JSON file by hand (a command checks the value and says what follows at the moment
of the choice); landing the patches held while landing was off once it is turned on (weeks of patches would
land together on a tree the owner has since edited); keeping the template's starting never list out of the
engine's fixed part (the owner's present behaviour lets the loop change its own tools, which a new
installation may later choose).

Reconsider: a second platform's modules exist, or an installation needs a value of its own that the `loop`
block cannot hold.

### DR-058 The loop holds against a hostile change: deny-by-default sandbox, read-only workers, landing names its paths (2026-11-24 · amended_by:DR-059 · amended_by:DR-061)

Decision: a builder's or a collector's output is treated as possibly hostile, not only mistaken.

1. Each sandbox start gets its rules as text on `sandbox-exec`'s command line, so nothing a test writes
   changes a later start.
2. The profile denies by default and allows what the sandboxed runs were measured to need, each allowance
   listed in `tools/loop/lib/loop_macos_sandbox.py` with what needs it: writes in the run's folder only; reads
   of that folder, the object store the clone shares, the toolchain and a short system list; one Mach service
   (`com.apple.bsd.dirhelper`); POSIX semaphores; no network of any kind and no pseudo-terminal. Launch
   services, job creation and Apple events have no harmless probe, so a test asserts the rule text.
3. No test serves on a network address: HTTP stand-ins answer inside the program that connects; a test that
   needs a terminal skips by name. The sandboxed base run of the suite has every test file at exit 0, and the
   runner and the loop's test summary count skipped tests apart from passes.
4. Every stage starts its model program read-only (`fresh_worker.py --read-only`; Codex with
   `--sandbox read-only`), and the loop writes each stage's one output file from the answer.
5. A bundle may not name a file whose name starts with `.git`; every file an edit wrote must be in the patch;
   no mode change. Paths, the never list and the policy file are compared in NFC case-folded form, and another
   spelling of a tracked path is refused at judgment.
6. At landing, under the lock, the settings, the policy and landing's paths are read again; a review counts
   only for its base and patch; a test gone on a moved base counts as lost.
7. Every key of the `loop` block is known or a problem (keys starting with `_` are notes), every value is
   type-checked, and while a problem exists no cycle judges, builds or lands; `status` and the health check
   say so.
8. A paper id is fetched only when the sweep listed it in arXiv form.
9. `on loop` prints only the chosen sources' statements, which say what really leaves (garden: every typed
   message, pasted text included; papers: queries, client name and an optional contact); choosing again
   replaces the earlier choice; each cycle checks its allowance and the settings before anything leaves; the
   person-ledger lane runs only with `loop.person_ledger_lane` (default false); papers names garden's reports
   only while garden may send.
10. Landing is `off`, or `worktree` or `commit` with `loop.landing_paths`, set together by `loops.py landing`;
    a reviewed change outside the paths, or one that changes the sandbox module, is held with its patch and
    `git apply` command and no later run lands it; `commit` is refused in a work instance.
    `templates/config.json` joins the engine's never list, and the template's `never` starts empty; this
    replaces the twelve starting entries of DR-057 (3). The health-check sentence of DR-057 (6) is narrowed:
    the check itself starts no model program, a repair reruns a cycle that does.

Context: after step 9d a reviewer of another model family read the kit's loop as a stranger's machine would
meet it and tried to break it; five of its findings were checked against the code by the main session and were
true (a rules file inside the writable folder, a Codex worker that could write the owner's checkout, an
allow-by-default profile, a misspelt `never` dropping every protection, a cached review reused after the
source changed). A reader-side review of the commands and texts gave the base wording of `on loop`, `landing`
and the settings errors. Decided by the owner with the main session, step 9h of the clean-up.

evidence: test:tools/tests/test_loop_isolation.py::test_a_start_cannot_change_the_rules_of_the_next_start ·
test:tools/tests/test_loop_isolation.py::test_the_rules_deny_by_default ·
test:tools/tests/test_loop_isolation.py::test_from_inside_only_the_run_folder_and_nothing_outside_the_sandbox ·
test:tools/tests/test_loop_isolation.py::test_no_test_file_serves_on_a_network_address ·
test:tools/tests/test_loop_read_only.py::test_every_stage_starts_every_runtime_read_only ·
test:tools/tests/test_loop_skips.py::test_the_runner_counts_skips_apart_and_names_the_reason_once ·
test:tools/tests/test_loop_guard.py::test_no_bundle_names_a_file_git_itself_reads ·
test:tools/tests/test_loop_guard.py::test_one_file_has_one_name ·
test:tools/tests/test_loop_settings.py::test_every_wrong_setting_is_a_listed_problem_and_none_raises ·
test:tools/tests/test_loop_consent.py::test_on_loop_says_what_the_chosen_sources_send ·
test:tools/tests/test_loop_consent.py::test_paper_ids_come_only_from_the_sweep

Rejected alternatives: allow-by-default with explicit denials (deny-by-default ran the whole sandboxed suite);
a starting `never` list of control files (imports and globbed tests make it open-ended); an `all` word for
landing (one word would open the loop's own code and the hooks); suggesting a path as a safe start (tools run,
rule files and documents are read by the agents, templates seed installations); a rule in the profile for this
machine's addresses or for terminals.

Not done here: pinning the judging set (step 9f), recovery after a kill during landing (step 9e), the words of
reports and the one-screen status (the voice step).

Reconsider: a test or a tool needs a resource the profile denies, a second platform's sandbox module exists,
or an owner asks for a landing form between a path list and off.

### DR-059 The loop recovers a landing that died, names each change's check, judges cost changes later, keeps a change to a file that runs as a patch, and reads less (2026-11-25 · amended_by:DR-060 · amended_by:DR-061)

Decision:

1. Before a patch is written into the owner's files, an intent file is written; at every start of a cycle and
   of the applier, under the global lock and before the tree is read, an intent without a ledger row (for
   commit landing, without its commit) is settled: files as before, the intent is dropped; files as the patch
   gives, the landing is undone with one ledger line and one report line `undone: unfinished landing`;
   anything else, or a failed undo, writes the stop flag `_private/loops/landing-stopped.json`, while which
   nothing lands and `status` and the health check name the change, its files and the intent file. Each start
   settles the flag again.

   `python3 tools/doctor.py --json --no-runtimes` runs once before and once after a landing; a check failing
   only after, or a doctor run that dies, undoes the landing at once. The hook canary is not run. The landed
   list says an undo rewinds files only.
2. What lands is exactly the saved patch: paths and modes come from the patch's bytes at every landing, both
   forms, and must equal the recorded ones; a rebase whose listing differs is broken.
3. A change to a file that runs or to one of the loop's prompts (`loop_policy.RUNS`: everything under
   `tools/`, `.githooks/`, `setup.sh`, `.claude/`, `.codex/`, `.agents/` and `system/loop/`) lands by itself
   only with the new setting `loop.self_landing` true (engine default false); the sandbox modules never do.
   The rule is by place because the loop's checks import or start files anywhere under `tools/`, a commit
   landing runs the hooks and a model run in the tree loads the hook settings; without the setting the loop
   lands documents and rule files only.

   A test run in a clone keeps every file of the clone, and the real-tree retest the tracked tests and the
   changed files, byte-equal from before the first test file to after the last, or the change is refused with
   the changed paths. A test file also cannot leave code for those after it: in a clone a file or link added
   under `tools/` ends the run, `__pycache__` folders are removed before each test file, and each test file
   gets a home folder of its own.
4. The judge gives each bundle one `check` beside the specification (the spec hash is unchanged): `test`,
   `cost` (`context-bytes`) or `unknown`. The loop computes the evidence from its own runs; a change whose
   evidence does not hold is refused before review and gets the second attempt, whose prompt carries the
   failing tests' clipped output; a patch adding no line or changing only `*.md` carries the builder's
   `Checked:` statement instead; an `act` bundle with an `unknown` check is refused at judgment. The evidence
   goes into the ledger row and `APPLY.md`.
5. The garden cycle, before its model stages, judges each landed row whose re-judgment date has come: a `cost`
   change is measured again on the working tree, in the sandbox with writes denied, and undone when worse, or
   equal with more lines added than removed outside `tools/tests/`; kept when equal otherwise; "helped" when
   smaller. Undo follows landing's rules read at that moment and needs the files exactly as landed. Every
   other change gets "not measured: judge it in use" once.
6. A papers cycle reads at most eight papers in full; a paper counts as read only when a card names it
   (`_private/papers/read.json`); card sections and proposal fields follow the check's three kinds. Every
   cycle counts its model runs and tokens in `tokens.json`; its report ends with one line, and `status` shows
   the last cycle's line; a run without a total is "without a count", never zero. The new setting
   `loop.token_ceiling` (engine default null) stops new model stages once reached; parallel stages already
   started may finish. A cycle stopped this way has the state `token-ceiling`, not failed: nothing resumes it,
   the applier skips it, and status and the health check each name it once.
7. Settings and consent: every path entry of the `loop` block and of `landing` is one literal path (no `*`,
   empty, `.` or `..` part, leading `/`, `\` or `:`); a key written twice and a runtime name the worker
   tool does not know are problems. The applier checks its source's allowance at every start, the backlog
   included. At a terminal, `on loop` shows the statement of the sources finally chosen before it takes the
   yes. A papers cycle removes an earlier selection and stops before the fetch when its selection fails. With
   the person-ledger lane off, the garden cycle removes earlier `mirror.md` copies.
8. The reviewer is handed the snapshot's untracked files, and its tree is compared with the snapshot commit
   after the run; a review counts only for that commit and the patch bytes; an untracked file that is empty or
   not text is named with its size instead of shown. A change moved onto a newer base has its evidence found
   again there, and one whose check no longer holds, or whose tests change the files that judge them, goes
   back to the judge. After a landing in the working tree, the run's later changes are built, tested and
   reviewed on the tree it left.
9. Smaller: a stage's output replaces a link instead of writing through it; the HTTP stand-ins give the test
   process its connection function back; the runner counts a failed file's skips; the retest no longer counts
   a skipped test as passed; the beat's unused `GARDEN_CYCLES` placeholder is gone.
10. Sentences that promised too much are narrowed in the document and the printed texts: what the real-tree
    retest may read, what `loop.clone_excluded` does not hide (Git's objects), what a review is compared with,
    that "no later run lands it" is about that patch, what papers reads while garden is off, the machine data
    garden sends, and that `git pull` and `git push` behave so on a branch with an upstream. DR-058 (6) and
    (10) are amended accordingly.

Context: a second reviewer of another model family read the hardened loop again and still failed it; the main
session checked seven new findings against the code and all were true (a rebase could land a file the moved
base ignores; a `never` entry `notes//` protected nothing; a terminal choice could widen after its statement;
the applier did not check its allowance; a failed selection still fetched; the review's tree was never
compared with the snapshot; a stage output wrote through a link). A read-only survey of the code found that
part of the planned work existed already (the landing intent, the repair attempt, the skip of carded papers),
so only what was missing was built.

evidence:
test:tools/tests/test_loop_checks.py::test_a_test_check_whose_test_did_not_fail_before_is_refused_before_review ·
test:tools/tests/test_loop_tokens.py::test_no_new_stage_starts_once_the_cycle_reaches_its_token_ceiling ·
test:tools/tests/test_loop_tokens.py::test_a_papers_cycle_reads_eight_papers_records_what_its_cards_name_and_ends_its_report_with_the_count ·
test:tools/tests/test_loop_settings.py::test_an_entry_that_is_not_one_literal_path_is_a_problem_that_names_it ·
test:tools/tests/test_loop_consent.py::test_the_applier_without_its_sources_allowance_ends_before_any_model_call ·
test:tools/tests/test_loop_checks.py::test_the_reviewer_reads_the_untracked_files_the_tests_ran_with

Rejected alternatives: running the doctor's hook canary around a landing (it starts model programs with hooks
on); a written list of the single files that judge a change, kept complete by a test that followed imports
(built first; it missed the tools the doctor starts after a landing, the shell hooks, an import inside a try
block and a new file named like a standard module, and each fix added a mechanism); a list of exceptions to
the rule; pinning those files to the base's bytes instead of holding them (the skipped tests still would not
run); statistics, spreads or any metric other than `context-bytes` for later judgment, and commands written by
a model; separate read and execute rights in the sandbox profile, narrower `sysctl-read`, a private object
store per clone and confining a model program's reads to prepared inputs (the document states what can be read
instead); deleting the person-ledger lane.

Not done here: the words the loop prints and the layout of its reports (the voice step).

Reconsider: a second metric becomes deterministic and cheap to measure, the sandbox lets nested sandboxes run
(then the loop's own tests run there and `self_landing` can be reconsidered), or a landing form commits
through a hook that starts model programs.

### DR-060 What a person reads says one thing, once, in one vocabulary; a cycle leaves one report (2026-11-25 · amended_by:DR-061)

Decision: this step changes words and layout, not what the kit decides.

1. One vocabulary holds for command output, reports, alerts, journal lines, `--help` and documents: one word
   per thing (cycle, source, proposal, change, patch file, saved, refused, abandoned, pending, starting
   commit, cycle output folder, temporary clone, temporary sandbox folder, your kit folder, step, send
   permission, runtime, worker, builder and reviewer, judge, the never list, the allowed area, kit files,
   health check, paper summary), and the words it replaces are not shown.

   The word in a record is the word in a sentence: a change's outcome is `saved`, `refused`, `abandoned` or
   `pending`, its reason a sentence in its own field; a cycle's state is `pending`, `done`, `failed` or
   `token-ceiling`.

   Nothing was published, so no stored data is migrated: a cycle folder from before this record reads as
   closed and is left as it is. Setting keys, command names and arguments, keys of records, names in code and
   the judge's answer format keep their spelling.
2. A cycle leaves one report, `REPORT.md` in its cycle output folder, drawn from data and redrawn when a step
   ends; it starts with what to do now: saved changes with their blocks, then pending ones, then refused and
   abandoned ones in one line each. `APPLY.md` and the papers copy `LATEST.md` are no longer written; where a
   prompt named a cycle's `APPLY.md` it names that cycle's report, and a folder from before this step that has
   an `APPLY.md` and no outcome record reads as closed and is left as it is.
3. When nothing is wrong the kit says nothing, and it says the same thing once: `tools/doctor.py` prints only
   what needs attention and `--all` prints every row, the health check prints nothing when there is no problem
   and a program reads its exit status or a record, and an alert is raised when a problem is first seen and
   when it is cleared.
4. Three behaviours change, each small: `python3 tools/options.py on NAME` and `off NAME` redraw the state
   page at their end; `doctor.py` gains `--all`; some messages are no longer printed when nothing is wrong.
5. The documents: `README.md` for a visitor, `SETUP.md` as the agent's day-one playbook, `CHECKLIST.md` with
   only what a person must check, and a new `MANUAL.md` for every day after the first, each fact in one of
   them; the loop's document answers eight questions in order and keeps every limit, guarantee and statement
   of what leaves the machine its earlier text held, each once. Every command a document or a printed line
   tells someone to run answers `--help` and `-h` with exit 0 and writes nothing.

Context: after the loop was hardened (KIT-DR-058, KIT-DR-059) a reader of another model family read the kit
seven times as a newcomer: the owner on day one, the agent that runs setup, and the owner the morning after a
cycle. The findings were the same each round: rows nobody needs when nothing is wrong, a loop report that
hides what to do now under codes, hashes and a wide table, one thing under three names, and one fact in three
documents. The texts were set by the main session's rulings on those reviews; where a target sentence was
false for the code, the code was kept and the sentence changed. Decided by the owner with the main session,
step 9v of the clean-up.

evidence: decision:KIT-DR-049 · decision:KIT-DR-059

Rejected alternatives: a framework or catalogue for messages (one table maps stored values to the words shown,
and the rest are plain strings); migrating stored records (nothing was published); renaming setting keys,
commands, record keys or the judge's answer format in the same step; keeping `APPLY.md` beside `REPORT.md`.

Not done here: the Korean editions and their stamps (a separate run); new behaviour of the loop.

Reconsider: a reader still meets one thing under two names, a report's first screen does not say what to do
now, or a stored word and the word shown for it differ.

### DR-061 The loop ends at a reviewed patch; the owner's agent applies it (2026-11-25 · active)

Decision:

1. The improvement loop collects, judges, builds a change in a temporary clone of the working tree (the
   commit, tracked changes and untracked files Git does not ignore), tests it in the sandbox, has the exact
   patch reviewed, and saves the patch with the cycle's report. Nothing under `tools/loop/` writes a tracked
   file of the installation, runs `git apply` or makes a commit there. The owner's agent applies a saved patch
   in a session by the procedure in `system/loop/README.md` section 4, and a commit is the owner's.
2. Superseded in the earlier records: the `landing` command and the settings `landing`, `landing_paths`,
   `self_landing` and `commit_trailer` (KIT-DR-057 (2), KIT-DR-059 (3)); landing's paths and the checks at
   landing (KIT-DR-058); the landing intent, the stop flag, the health-check runs around a landing, the later
   measurement of a cost change and its date, the retest on the owner's tree, the pinning of files during a
   test run and the rebase of a held change (KIT-DR-059 (1), (2) and the later judgment); the words `landed`,
   `blocked` and `undone` (KIT-DR-060, corrected in place). A configuration that still names one of the four
   settings is told so by the existing unknown-setting problem.
3. A change ends `saved`, `refused` (with the stage and the reason), `abandoned` (both build attempts failed)
   or `pending` (with why and what continues it: no runtime could be called, or the token ceiling); a cycle is
   `pending`, `done`, `failed` or `token-ceiling`. A cycle run again does not build a change it finished.
4. When a cycle saves a change it writes one private journal line naming the count and the report, so the next
   session's state view shows it; nothing is written when nothing was saved.
5. Nine defects found by the reviews are fixed with a test each: a file the owner staged broke the review, the
   runtime check looked for the wrong program, `context_bytes` counted a failed run, the review prompt lacked
   the check and the evidence, consent was read only at the start of a papers cycle, the person-ledger delta
   was copied into the report, a failed `git ls-files` let a misspelt path through, "Nothing is scheduled."
   was printed without reading the schedule, and the token ceiling's text did not say what it counts.

Context: three reviews by other model families found most of their defects in the machinery for landing a
change unattended. The owner decided on 2026-11-25 that the loop does not write into the owner's files, and
set the standard: code and text are plain, a published kit must not fail in ordinary use or leak and must say
what it does not do, a judgment an agent can make from a short written procedure need not be code, and the
loop assumes the model that builds a change can be wrong, not hostile. Decided by the owner with the main
session, step 9p of the clean-up.

evidence:
test:tools/tests/test_papers_apply.py::test_a_reviewed_patch_is_saved_from_the_working_tree_and_nothing_is_written ·
test:tools/tests/test_papers_apply.py::test_a_cycle_without_a_saved_change_journals_nothing ·
test:tools/tests/test_papers_apply.py::test_r7_outcome_record_broken_or_missing_is_not_done ·
test:tools/tests/test_loop_checks.py::test_a_new_file_the_owner_staged_is_not_handed_to_the_reviewer_twice

Rejected alternatives: repairing the landing machinery (its recovery, health checks, undo and holds were where
the reviews kept finding defects); a command that applies a patch at a terminal (the procedure is short and an
agent follows it); hardening against a builder that sets out to fool its own tests (the document says the
loop does not stop it, and the diff is read and the tests run before applying).

Reconsider: owners apply saved patches unchanged for weeks and ask for less reading, or the sandbox can run
the kit's own tests in full.

### DR-062 The kit is published in English only (2026-11-26 · amended_by:DR-064)

Decision: the kit has no Korean edition and no tooling for one. Removed: the 45 files under `ko/` (translated
documents, starter templates and the pair table `ko/INDEX.md`); `tools/dev/i18n_stamp.py`; the pair, stamp and
pair-index checks of `tools/tests/test_language.py`; the stamp comment and the line naming the Korean edition
at the top of 27 English documents; `--lang` of `setup.sh` and the configuration key `instance.lang`.

Starter documents come from `templates/` only, and `--lang` is now an unknown argument, refused with the usage
line. A configuration that still carries `instance.lang` loads as before, because unknown keys are accepted,
and `bash setup.sh --force` drops the key without reporting it as a reset.

The check that the kit's own text is English stays in `tools/tests/test_language.py`; the files allowed to
hold Hangul (engine source that reads Korean words in data people wrote, and the enforcement matrix whose
Korean text is not translated yet) moved from `system/dev/language-pending.txt` into the test as
`HANGUL_ALLOWED`, and an entry with no Hangul still fails.

The two PRDs are English and normative. The lens files and the person ledger in the kit are kit-owned, since
the source workspace keeps its own in Korean. Superseded: KIT-DR-024. Amended: KIT-DR-049, whose sentence on
Korean documents under `ko/` no longer holds, and KIT-DR-016 with KIT-DR-036 (6): the two PRDs have no Korean
source, and their English text is the requirement.

Enforcement-matrix rule `w2-19-locale-pair-stamp` is removed with its pin test; `w2-19-language-pending-seal`
keeps its id and now names the list in the test. Earlier CHANGELOG entries whose evidence cited a removed test
cite this record or KIT-DR-024 instead.

Context: `decision:KIT-DR-024`, `decision:KIT-DR-049`. Proposed by the owner on 2026-11-25. The main session
agreed: one edition is kept true instead of two, and a stale translation was the kit's only failing test. The
owner's own workspace stays in Korean.

evidence: test:tools/tests/test_language.py::test_allowed_files_fixture ·
test:tools/tests/test_setup_migration.py::test_a_starter_language_key_is_read_and_dropped_on_force ·
test:tools/tests/test_memlib_journal.py::test_root_aliases_shape_fails_closed

Rejected alternatives: keeping the Korean edition with its stamps (every English change needed a Korean one,
and stale editions were the kit's only failing test); keeping `--lang` as a no-op (an option that does nothing
is something extra); keeping `language-pending.txt` as a separate file (only the test reads it).

Reconsider: readers of the published kit ask for another language, with someone to keep that edition true.

KIT-DR-064: the enforcement matrix is replaced by the English table `system/dev/enforcement.md`, and rule
`w2-19-language-pending-seal` by `w2-19-language-allowlist`.

### DR-063 Skills have one source and one exporter; slash commands are skills; the lens skill offers and does not require (2026-11-26 · active)

Decision:

1. A skill's source is the folder `system/skills/<name>/`, a `SKILL.md` whose front matter has exactly `name`
   (the folder's name) and `description` (a JSON string of at most 1024 characters), and any files beside it.
   `python3 tools/skills.py write` copies every file of every source folder byte for byte to
   `.claude/skills/<name>/` and `.agents/skills/<name>/` and removes a file there that the source no longer
   has; `check` names each copied file that is missing, extra or different and exits 1, and otherwise prints
   nothing. The copies carry no banner. A folder there with no source of the same name is
   the owner's own skill and is left alone. doctor's row `tools · skills` calls the same function and names
   the command that fixes a difference.
2. Slash commands are skills: the five files of `.claude/commands/` became `now`, `recall`, `dossier`,
   `garden` and `paper-to-kit` in `system/skills/`, and where a body took `$ARGUMENTS` it says that the input
   is what the user wrote with the command. The lenses, the deep pass, the writing guide and the guide to
   large jobs became the skills `lenses`, `deep-pass`, `plain-writing` and `large-jobs`.
   `tools/agy_skills.py`, which turned commands into Antigravity skills, and `tools/dev/skill_adapters.py`,
   which turned `system/skills/paper-to-kit.md` into a command, are removed.
3. A link inside a skill folder points inside that folder; another skill is named in words and a kit file
   outside as a path in code font. `tools/linkcheck.py` reports a link from a skill to a file outside its
   folder as broken, because each runtime reads a copy of the folder alone.
4. The lens skill's body tells the agent to work the problem its own way first and offers one or two of
   thirteen questions before a design or decision is committed, saying in one line what a question changed and
   nothing when it changed nothing. `AGENTS.md` points to each thinking skill by name and says when it is for.
   Each thinking skill's `SKILL.md` is a short body; the full text sits beside it (`steps.md` for the deep
   pass, `frame.md` for large jobs, `guide.md` for plain writing and for the lenses, with the thirteen lens
   pages).
5. `.gitignore` restores only `.claude/settings.json` and the kit's skill folders under `.claude/` and
   `.agents/skills/`.

Context: the three runtimes, Claude Code, Codex and Antigravity, read the same open skill format, and in
Claude Code a skill is also the slash command of its name. Before this record the kit had two generators for
two of its skill kinds, and the thinking documents were reached only through a line in `AGENTS.md`.

Measured by the main session on one model: with the lens skill and the line in `AGENTS.md`, the skill was
opened in 24 of 30 runs where it should have been (ten task sentences, three runs each) and in 0 of 20 where
it should not; across the four installations tried it was never opened where it should not be (0 of 70).
Answers of that installation were preferred to those of an installation with no lenses in 16 of 30 blind pairs
against 9, with 5 undecided, at the same length (ratio 0.98). After the body was revised for cold readers, the
skill was opened in 8 of 10 runs where it should have been.

The owner set two conditions: a lens helps a person's insight and must not bind the model, and it should come
up without being asked for. Decided by the owner with the main session, step 9s of the clean-up.

evidence: test:tools/tests/test_skills.py::test_write_copies_every_file_and_check_names_each_difference ·
test:tools/tests/test_skills.py::test_every_skill_has_the_two_front_matter_fields ·
test:tools/tests/test_skills.py::test_this_trees_copies_match_their_sources ·
test:tools/tests/test_skills.py::test_doctor_row_names_each_difference_and_the_fix ·
test:tools/tests/test_linkcheck.py::test_a_skill_links_only_inside_its_own_folder ·
test:tools/tests/test_skill_parity.py::test_canonical_contract_is_machine_visible

Boundary: the measurements are from one model, on task sentences the main session wrote, and the last check,
after the revision, was not judged blind; they show the skill is found and does not make answers worse there,
not that it helps every model or task. Whether Codex and Antigravity open the skills unasked was not measured.
`check` compares bytes only and does not validate front matter; the suite does. Hidden files in a source
folder are not copied.

Rejected alternatives: keeping a generator per kind (two tools for one job); a banner in each copy (a copy
that differs from its source by a header cannot be checked by bytes).

Reconsider: a runtime stops reading one of the two folders, or the lens skill is opened where it should not be
in real use.

KIT-DR-065: these measurements ran in installations inside the maintainer's own workspace, whose instruction
file each session also read; they are not of the kit alone. Outside it the probe counted 10 of 30 and 0 of 30
(section 8 of `system/specs/model-assumptions.md`).

### DR-064 The builder's side keeps two things: a decision's pointer to its basis and an honest rules table; the release gate is the suite and continuous integration (2026-11-26 · active)

Decision:

1. Removed: the review manifest `system/dev/review-manifest.yaml` and its builder
   `tools/dev/manifest_build.py`; the enforcement matrix in YAML and Markdown; the engine inventory
   `system/dev/engine-inventory.txt` with its hash pin; the test matrix `system/dev/test-matrix.yaml` with
   `tools/tests/test_matrix_check.py`; `tools/tests/test_manifests.py`; the release tool
   `tools/dev/gate_release.py`; and the test log (`MOTTORI_TEST_LOG`, `MOTTORI_TEST_RUN_ID`, its writer in
   `tools/tests/testlib.py` and its reader in the evidence checker).
2. `tools/gate.py` has one scope: a commit in a kit clone before setup runs the checks an installed instance
   runs. The release branch of `measure`, `gate.py release`, the role scope that existed for it and
   `doctor --release` are gone. A baseline saved before this record that names the removed checkers does not
   block a commit or a turn end; their entries are dropped.
3. Kept: the evidence markers, checked by `tools/dev/evidencecheck.py` for form and for what they name in the
   tree (a decision record, a test function, a run folder), not for whether a test ran, as
   `system/dev/evidence-schema.md` says; and one English rules table, `system/dev/enforcement.md`, with one
   row per rule, its test, and one of four statuses, whose cited functions a test checks. Five rules of the
   old matrix were dropped because what they described no longer exists: the review-manifest coverage,
   integrity and doctor regression rules, and the two CHANGELOG v0.2 rows, whose checks are other rows.
4. What the lists guarded is derived: `tools/tests/test_instance_shape.py` takes its file set from
   `git ls-files tools`, and `tools/tests/test_tool_coverage.py` fails when a tool file is named by no test
   file or a critical tool loses a required proof. The runner fails a file in which a `def test_` function
   never ran, which closes the gap the test log closed.
5. The release gate is `python3 tools/tests/run.py --full` and continuous integration, which runs the suite,
   the link check, the evidence check and `git diff --check`, only in a repository named `mottori-kit`.
6. `CHANGELOG.md` holds one entry for this release; earlier entries are in Git, and the code that parsed them
   (the Korean tags, the Hangul allowance for the file) is gone. Each test file leaves nothing in the
   temporary folder.

Context: `decision:KIT-DR-020`, `decision:KIT-DR-040`. A survey of the builder's side counted about 5,300
lines of lists and checks that nothing an installed user runs reads, and a release mode inside
`tools/gate.py`, a tool every user runs. The owner's standard: each element answers what the person using the
kit gains, an adopted change names what it rests on, and what must be guaranteed is guaranteed in code.
Decided by the main session on that standard; the owner reads it before the release.

evidence: test:tools/tests/test_gate.py::test_older_baseline_naming_retired_checkers_does_not_block_a_commit ·
test:tools/tests/test_enforce.py::test_check_drops_retired_checkers_from_an_older_baseline ·
test:tools/tests/test_runner.py::test_a_test_function_its_file_never_runs_fails_the_file ·
test:tools/tests/test_evidencecheck.py::test_a_marker_naming_a_missing_test_fails ·
test:tools/tests/test_rules_table.py::test_a_row_citing_a_missing_function_fails ·
test:tools/tests/test_tool_coverage.py::test_a_tool_file_no_test_names_fails ·
test:tools/tests/test_tool_coverage.py::test_a_critical_tool_that_loses_a_proof_fails ·
test:tools/tests/test_install_checks.py::test_ci_runs_only_in_the_kit_repository

Boundary: a kit commit no longer runs any test; a contributor runs the suite, and continuous integration
catches a commit made without it. A marker can name a test that exists and still not support its claim; that
stays a reviewer's question. Naming a tool in a test file counts as coverage whether or not the test exercises
it.

Rejected alternatives: keeping the release scope for kit commits (every commit re-ran 48 suites, and it lived
in a tool every user runs); keeping the test log with a shorter window (the runner check closes the same gap
without a file); keeping the 82 normal rows of the test matrix (they repeated what `git ls-files` and the test
files already say).

Reconsider: a broken kit change reaches the published branch because no test ran before the commit, or the
rules table drifts from the code without a test noticing.

### DR-065 Each part says whom it is for, and what a model-side part assumes is measured again when the model changes (2026-11-26 · active)

Decision:

1. `system/specs/model-assumptions.md` sorts every part a user or their agent meets (the seven rules of
   `AGENTS.md`, each hook step of `tools/dispatch.py` and the Git hooks, the commands, the nine skills, the
   optional parts of `tools/options.py`, the stages of the loop) into one of four sections: for the person,
   making up for a model, making up for a runtime, or both. A row gives its basis as measured, outside or
   argued, with its evidence markers, and a part on the model's or the runtime's side says what it assumes and
   how to try without it today. Where the sorting is unclear the part goes to the fourth section and its row
   says what is unclear.
2. The same page lists the caps on what the model is shown that a reading of the code found (bytes,
   characters, lines or items that a hook, a tool or a prompt lets through), each with its value, where it is
   set, its reason or "no recorded reason; a starting value", and how to change it; it lists the places where
   the kit still prescribes a method, with the reason on record; and it says what to measure when a new model
   arrives and keeps the measurements so far.
3. `tools/dev/skill_probe.py` repeats the measurement of KIT-DR-063 on the tasks of
   `system/dev/skill-probe-tasks.json`: real Claude Code sessions, started only after the owner's yes, in a
   throwaway installation that no other instruction file sits above.
4. `tools/dev/evidencecheck.py` reads the page's markers, and `tools/tests/test_model_assumptions.py` fails
   when a hook step (Antigravity's own included), an optional part or a skill has no place in it.
5. `MANUAL.md` section 2 names every setting the code reads, with its default. No hook, check, cap or default
   changes value.

Context: `decision:KIT-DR-012`, `decision:KIT-DR-063`. The owner holds two principles for this kit. The first
is in the README: a person's attention is the scarce thing, tokens are cheap. The second, in his words
(translated): "as the model's intelligence rises we do not want the harness to be what limits the model; we
want collaboration centred on the person." Of the thinking lenses he said that they "help a person's insight
and must not become what limits the model". A survey of the kit found that nothing tied a part to a model
change: 47 decision records carry a `Reconsider:` line and none names a model becoming more capable; many caps
on what the model is shown had no stated reason, and a user could read about most of them nowhere. Decided by
the main session on the owner's stated principle; the owner reads it before the release.

evidence: test:tools/tests/test_model_assumptions.py::test_the_page_names_every_step_option_and_skill ·
test:tools/tests/test_model_assumptions.py::test_a_page_lacking_one_span_fails ·
test:tools/tests/test_evidencecheck.py::test_the_model_page_is_read_as_a_fourth_target ·
test:tools/tests/test_skill_probe.py::test_starts_nothing_without_yes ·
test:tools/tests/test_skill_probe.py::test_a_stream_without_result_is_named_and_fails

Boundary: one model has been measured, on task sentences the main session wrote (KIT-DR-063). Those sessions
ran in installations placed inside the maintainer's own workspace, and Claude Code reads a `CLAUDE.md` in any
folder above the one it starts in: asked which instruction files it had, a session there named the workspace's
file beside the installation's two, and a session in an installation outside it named the two alone. So the
figures of KIT-DR-063 are not of the kit alone, and the probe refuses an installation below such a file.

Repeated with the probe in an installation outside it on 2026-11-26 (claude-opus-5-5, Claude Code 2.1.292,
twenty tasks with three runs each): a thinking skill opened in 10 of 30 runs where one should and in 0 of 30
where none should, against 24 of 30 before. The kit alone opens them less often than KIT-DR-063 reports.

The same day the page's own step, trying without a part, was run on the lens skill: three blind judges
preferred answers with the skill opened in 52%, 58% and 56% of the decided pairs over an installation without
it, under the 60% set beforehand, so the wording that offers the skill and does not require it stays as it is.

The probe measures whether a skill is opened, not whether the answer was better, and Claude Code only. Most
rows of the page are argued, not measured: the page says what each part assumes, not that the assumption still
holds. The tests check that each part is named, not that its row stays true.

Rejected alternatives: a line on each of the 64 earlier records (the reader who needs this asks "a new model
is out, what do I measure again?", and one fact lives in one place); a reminder that fires when a new model id
is seen (a user cannot act on it and the maintainer does not need it); raising the state cap without repeating
the capture of where a runtime cuts an injected block.

Reconsider: a part of section 2 or 3 is tried without on a new model and its failure does not come back, or
the probe's counts move away from the newest row of section 8 of the page.

### DR-066 A lens is for the person: an agent that uses one shows the owner the question (2026-11-26 · active)

Decision: step 3 of the lens skill changes. Before, an agent said in one line what a lens had changed and said
nothing when it had changed nothing. Now it ends with one line that names the lens, puts its question in the
terms of the case, and says what changed or that the answer held. The skill's opening says the questions are
for a person first. Whether to use a lens stays the model's call: the description that opens the skill and the
line in `AGENTS.md` do not change.

Context: `decision:KIT-DR-063`, `decision:KIT-DR-065`. A blind comparison on one model found no difference
between answers written with the lens skill opened and answers of an installation without it (KIT-DR-065,
section 8 of `system/specs/model-assumptions.md`). The owner's reading of that result, in his words
(translated): the effect on the AI's answer may be slight, but the effect of a person's thinking being steered
by seeing the lens is large. In the 26 answers of that comparison written with the skill opened, 3 named the
lens to the reader, all on the task that asks for one: the old wording kept a lens out of the person's sight.

Measured after the change with the probe (claude-opus-5-5, Claude Code 2.1.292, twenty tasks with three runs
each, an installation with no other instruction file above it): a thinking skill opened in 15 of 30 runs where
one should and in 0 of 30 where none should, and in all 9 runs where the lens skill opened the answer ended
with the lens and its question. Decided by the main session on the owner's statement of the same day; the
owner reads it before the release.

evidence: none

Boundary: whether a person who sees the question decides better was not measured and cannot be by model
judges. One model, tasks answered in one turn. The line is one more line in a reply, on the roughly one in
three design or decision questions where the skill opens.

Rejected alternatives: telling the model to open the skill more often (a method prescribed to the model,
against KIT-DR-065, and the blind comparison gave no reason for it); showing the line only when the answer
changed (the question is what the person thinks with, whether or not it moved the agent's answer).

Reconsider: owners find the line noise in real use, or a later model shows the question unasked.

### DR-067 The front page starts from the owner's two sentences, and every folder has a page (2026-11-26 · active)

Decision:

1. `README.md` opens with one line that says what the kit is and what it does with the first of the two
   sentences (it spends tokens to save the person's attention), then four things a reader has lived through,
   then one paragraph on why the kit is built from files and checks (twelve of thirteen written rules did not
   hold in the original workspace), then how to try it: install the workspace, or copy the lens folder alone.
   Lenses, deep pass, plain writing and large jobs get a section of the same weight as keeping the thread. The
   second sentence (the harness must not hold the model back) has its own section with the measurement that
   went against the kit's favourite part. Reference material (what the parts cost, how each runtime was
   tested, the optional parts, the folder map) lives in `MANUAL.md`, and the README keeps one line for each.
2. Each folder a visitor opens has a README: `tools/`, `tools/lib/`, `tools/loop/`, `tools/tests/`, `system/`,
   `system/skills/`, `system/specs/`, `templates/`. A README says what the files cannot say one by one: how
   they fit and where to start.
3. Every tool file is named in a README of its own folder, the folder above it or `tools/`, and a line that
   names a file that is gone fails the same test.
4. The hero image is one exchange: a decision that crosses two compactions, and a lens question shown to the
   person.

Context: `decision:KIT-DR-012`. The owner said what the front page must do (translated): a first-time visitor
must understand it at once; a statistic that opens the page does not land and does not say what it has to do
with the philosophy; lenses and plain writing were what he had found most useful and were all but absent from
the first page; no claim of being first and no comparison with other tools; a README for each module matters.
He left the choices to the main session on 2026-11-26.

Before this record the README opened with the compaction sentence, which read as a memory tool, and three
folders had a README. Revised the same day, before anything was published: three cold readers each named what
was missing, every item was added, and the page went from 183 lines to 297.

The owner then said (translated) that a README filled with wordy and contrived writing will not do, that it
must be plain, full of substance, easy to read and able to hook a reader, and that adding this and that at
length is not good writing. The page was cut to 136 lines.

Two cold readers of the cut page each named the twelve-of-thirteen sentence as the one they would repeat, so
one sentence of it sits under the opening, tied to the design it led to; the message and correction totals
left the page. Both readers also marked the lines that read as a slogan or a staged moral, and those were
removed, in the pictures too. The owner had the line on what the name means removed.

He then said (translated) that the rules count is a surface experience and the page should carry the message
beneath it. The paragraph now opens with that message (what has to happen every time cannot rest on anyone
remembering it, the person or the agent) and keeps the count as its evidence, and the section on a better
model opens with the owner's two sentences taken together: models keep getting better and a person's
attention does not.

evidence: test:tools/tests/test_tool_entrypoints.py::test_readme_lists_every_tool ·
test:tools/tests/test_options.py::test_manual_describes_every_option_in_order

Boundary: the clone command gives the kit's public address, by the owner's word on 2026-11-26; no other kit
file names an account. The repository's description, topics and social image are set by hand on the day of
publication.

Rejected alternatives: opening with the correction counts (the owner had said on 2026-11-25 that they do not
land and do not show their link to the philosophy); adding everything a cold reader says is missing (a reader
names gaps, not what to cut); opening with a scene and no statement of what the kit is (a visitor who came
from a link decides in seconds); one generated list of every file with its docstring (the
docstring is already that fact's home); a README in every folder including those with one or two files.

Reconsider: first-time readers still read the kit as a memory tool, or a folder README falls behind its folder
in a way the test does not see.

### DR-068 One open question below the lens table asks what the table missed (2026-11-26 · active)

Decision: the lens skill keeps thirteen rows and gains one open question below them, for when no row fits or
the rows used agreed too easily: if the table missed one thing about this case, who would see it at once, and
what would they check first? The person is picked by role, not by name, and what is borrowed is how they work,
not how they talk. A question from outside the table is shown to the owner like a listed one, as "Lens
(outside the table)". Step 1 of the skill points to it.

Context: `decision:KIT-DR-066`. The owner asked (translated) whether a lens is needed for not getting trapped
in the lenses, such as: if there is one thing these lenses failed to point out, who is the best adviser, and
what would they say? Two records of the original workspace bear on it. When half of the owner's messages were
read for the lens review, about 23% of the corrections matched one of the thirteen lenses and 38% were a
question that is not among them. And of three earlier trials of answering as a named person, the one that
worked had borrowed that person's working method; the two that borrowed a voice produced well-written
paragraphs the owner rated lowest. So the question asks what the adviser would check, not what they would say.

evidence: none

Boundary: nobody has measured whether an agent uses the question or whether its answer helps a person. It
replaces the sentence that only allowed a made-up viewpoint.

Rejected alternatives: a fourteenth row with its own page (a row needs a situation a person can match, and
this one's situation is that no row matched); asking what the adviser would say (the trials above); naming a
real person (it invites invented quotations).

Reconsider: answers that show the line read as a persona speaking, or the line appears on quick questions.

### DR-069 Existing material comes in whole and as it is: its old broken links stop no turn (2026-11-26 · active)

Decision:

1. `tools/adopt.py FOLDER` adopts a folder of the owner's material that already sits inside the workspace. It
   moves, renames and edits nothing. It records the link issues the folder's Markdown has at that moment in
   `state/.gate-adopted.json`, and the turn-end check does not count a recorded issue against a turn that
   edits the file.
2. A second run drops the issues that were fixed and records none that appeared since the first; `--again` is
   the explicit way to accept the folder as it is now.
3. The same run names instruction files and Git repositories inside the folder and writes one inventory page
   under the private state folder, so an agent proposes tracks from one page.
4. `SETUP.md` tells the setup agent to bring existing material in whole and to reorganize, rename and fix
   nothing on the first day.
5. A block for a file in a folder nobody adopted names the command; a block inside an adopted folder does not,
   because there the link is new.

Context: `decision:KIT-DR-034`. The owner said (translated) that moving a folder full of his own material into
the kit had cost many permission approvals, which a company does not let an agent skip, first-time work on
consistency, friction and tokens, and asked for a way to make it easy. In a fresh installation the cause was
reproduced. Bringing a folder in costs nothing: Git ignores it and every check passes. But each time an edit
tool changed an old document, the turn-end check stopped the turn once for a link that document already had
broken, because for a file Git does not track the check has no earlier state to compare with. An instruction
file inside the folder was reported by nothing.

evidence: test:tools/tests/test_adopt.py::test_an_adopted_link_is_not_this_turns_issue_and_a_new_one_is ·
test:tools/tests/test_adopt.py::test_second_run_drops_fixed_links_and_does_not_accept_new_ones ·
test:tools/tests/test_adopt.py::test_adopting_records_the_broken_links_and_changes_nothing_in_the_folder ·
test:tools/tests/test_adopt.py::test_the_turn_end_check_reads_the_same_issue_ids

Boundary: the record names a link by its file's path, so a renamed or moved file loses its record. Nobody has
run it on a large real folder. It does not reduce the approvals a runtime asks for the kit's own commands;
whether the kit ships an allow list for them is the owner's decision and is not taken here.

Rejected alternatives: a migration tool that moves files into a layout (the kit needs no layout of the owner's
folders, and moving is what broke links and asked for approvals); letting `gate.py baseline` accept untracked
files (it would have to read every document Git ignores on each run); remembering a file's links when it is
first edited (the edit hook runs after the edit, so the earlier state is gone); accepting new issues on every
run (a turn could then silence its own breakage).

Reconsider: owners report blocks for links they did not break in adopted folders, or adoption is used to pass
a turn's own breakage.

### DR-070 A start with one question and one command, and no command allowed in advance (2026-11-26 · amended_by:DR-072 · amended_by:DR-081)

Decision:

1. `setup.sh` checks Python and Git itself and notes a rules file in a folder above, so the setup agent runs
   one command; `SETUP.md` opens with that short path and makes the first-day items wait for the owner.
2. Before setup the turn-end check does not judge a turn: a folder with no config and no state has no baseline
   by construction. A set-up instance whose baseline is missing still blocks.
3. Doctor does not warn about what a new folder cannot have yet: no track is a note on a passing row; a
   runtime's missing transcripts, an empty transcript folder and zero readable sessions are not applicable
   until a turn end is on record; a missing compaction event warns only after the journal's first row is
   fourteen days old; the one-time approval of Codex or Antigravity is a later step, with no line at session
   start, until that runtime has a session in this folder.
4. Setup ends with what to do next, and names `instance/rules.md` and `CHECKLIST.md` as requirements only on a
   work installation.
5. `.claude/settings.json` allows no command in advance. It asks, in every permission mode, for an edit to the
   kit's code and hook lines, to the rules every session loads, to `instance/config.json` and
   `instance/rules.md`, and to the files that hold what the turn-end check has accepted.
6. The owner's own notes and documents are not imports: `AGENTS.md` and the boundary ritual send them to
   `adopt.py`, and the three boundary principles stay for material from the other side of the boundary.

Context: `decision:KIT-DR-069`. The owner said (translated) that the experience has to be seamless at the
start and in daily use, and asked for it to be thought through from the seat of the people who use the kit. So
the README's own path was walked in live Claude Code 2.1.292 sessions with default permissions, in fresh
clones, and what a person would have had to approve was counted as the tool calls refused for lack of
permission.

Before: the setup sentence ended with setup not run and three calls refused (the agent's own version checks,
chained in one command, and a look for a rules file above); before setup the turn-end check stopped the turn
for a missing baseline; a finished setup showed five warnings on a machine with Codex and
Antigravity installed and two chores; asked to take in a folder of old notes, the agent followed the boundary
ritual, left the folder and asked the owner to fill in the rules file first.

A first version of this decision also shipped a list of 31 kit commands allowed in advance, and with it the
setup sentence, a decision told in passing and the folder of notes all ran with no call refused.

An adversarial round by a model of another vendor rejected that list. Its strongest point: a rule names a
script by a relative path, so after a `cd` into a subfolder the same rule runs a same-named file there, and a
workspace that adopts folders it did not write is where such a file can be. It also showed, command by
command, where an allowed call could accept findings, change the installation's context or print files from
outside the workspace. The list was removed, and the edits it named as most worth protecting were added to the
rules that ask.

evidence: test:tools/tests/test_permissions.py::test_no_command_is_allowed_in_advance ·
test:tools/tests/test_permissions.py::test_an_edit_to_what_the_checks_rest_on_always_asks ·
test:tools/tests/test_bypass_pins.py::test_h1_g11_absent_baseline_blocks ·
test:tools/tests/test_doctor_json.py::test_precompact_journal_marker_check ·
test:tools/tests/test_doctor_json.py::test_runtime_transcripts_row_says_so_for_an_installed_runtime_with_none

Boundary: the walks were sessions without a terminal; an interactive session was not run, and Codex and
Antigravity were not walked. Without an allow list a person approves the setup command once, and each kit
command the first time the agent runs it. The rules that ask cover the edit tools, not a shell command that
writes the same file; such a command is not allowed either, so it prompts as any command does. The fourteen
days have no recorded reason.

Rejected alternatives: shipping the allow list (above); writing it into the local settings on a yes at setup
(the same relative paths); keeping the day-one warnings and telling the setup agent to explain them (an
instruction where the output itself can be right).

Reconsider: a way is found to bind an allowed command to this checkout and to its exact arguments, for example
a hook that checks the working folder before a command runs, and it survives an adversarial round; or new
installations still end with warnings that are true of every new folder.

### DR-071 `_private/` is a place the owner knows about; the agent suggests it, and nothing goes there by guess (2026-11-26 · amended_by:DR-078 · amended_by:DR-081)

Decision:

1. The kit says what `_private/` is for where a new user looks: setup's closing lines, README and MANUAL. It
   is the place for what must stay on this machine. Git never takes it and the agent does not quote it in what
   it writes for other people. It is not hidden from the agent, nor from a worker that runs in this folder.
2. Rule 2 no longer tells the agent to log `--private` "when unsure". When something looks like company
   material or another person's details, the agent suggests once that it go under `_private/`, and uses
   `log --private` when the owner has said so.
3. A new installation keeps no list of public tracks: `journal_visibility.public_tracks` is `null`, and every
   journal line is ordinary unless it is logged with `--private`. An installation that already holds a list
   keeps it, and a rerun of setup keeps whichever it finds.
4. No mechanism is added that locks a worker out of `_private/` by file rules or by permission per vendor.

Context: `decision:KIT-DR-006`, `decision:KIT-DR-002`. The owner's words (translated): "It is enough that
there is a space called `_private`, that the user is made aware of what it is for, and that the harness
suggests putting something there when needed." And before that: "Who decides what is private, when and how?
Most of it is not private. A person using AI has already sent it all, and a company can see it all."

Measured in the installation the kit grew from: in one month 714 journal lines had gone to the private side and
224 to the ordinary one; 12 of the 714 were someone else's material, and the agent had sent 262 lines of a track
that was on the public list there on its own judgement. Measured in a fresh install: the README's first example
printed `recorded in private overlay (track "launch" is not in public_tracks)`, and Git ignores `state/` as it
ignores `_private/`, so a line left the machine by the same routes on either side.

evidence: test:tools/tests/test_setup_migration.py::test_fresh_setup_creates_v4_config_and_now ·
test:tools/tests/test_memlib_journal.py::config_cases

Boundary: the suggestion is a rule the agent must remember, and no check enforces it. A configuration that
cannot be read still sends lines under `_private/` until it is repaired. A line logged without `--private`
that the owner later wants kept local has to be moved by hand. The words "public" and "private overlay" still
appear in the tools' own names and in the injected view.

Rejected alternatives: keeping "when unsure, private" (it sent most lines there and buried the few that
mattered); a list of private tracks (not asked for: the owner's unit is the single item, which `--private`
covers); file rules that close `_private/` to workers, and a permission per model vendor (the owner called the
level above enough).

Reconsider: state is committed or synced to a place other people read; the agent's suggestions turn out to be
noise, or miss company material.

### DR-072 The kit does not tell work and personal folders apart, and does not decide where a folder may push (2026-11-26 · active)

Decision:

1. `instance.context` and `instance.remote_allowlist` are gone from the config, the template and every check.
   A config that still holds them loads as before, and `bash setup.sh --force` drops the two keys and says so.
2. No check refuses a commit or a push because of the kind of folder or the remote it goes to. The commit and
   push checks keep the one rule that is the kit's own: a path under `_private/`, `instance/` or `state/` that
   Git did not already hold is refused from a commit, a pushed commit that holds a private path is refused,
   and a tree with instance files and no config pushes nothing until it is whole.
3. `setup.sh` asks nothing, because an agent runs it: the instance's name is the folder's name unless `--name`
   gives another, and `--context` is accepted and answered with one line saying it is no longer used.
4. Removed with them: `enforce.py ready` and `doctor.py --ready`; doctor's remote row (`boundary_remotes`);
   the rule that in a work folder refused every tracked symlink and every tracked change; the section "Remote
   policy" of `templates/rules.md`; the checklist item on pull-only credentials; and tools/lib/remotes.py.
   Doctor's row on what Git ignores now also fails when anything under `_private/` is tracked.

Context: `decision:KIT-DR-002`, `decision:KIT-DR-039`, `decision:KIT-DR-041`, `decision:KIT-DR-070`,
`decision:KIT-DR-071`. The owner's words (translated): "Is it right to tell company use and personal use apart
at all? And setup is run by an agent anyway." Of keeping the lock as a switch a person turns on: "Is even that
needed?" And: "It is not for an open-source harness to manage permission for pushing company material to Git,
is it?" Before this record a setup run without a terminal and without `--context` took `work`, and that folder
then refused every commit and every push. KIT-DR-002 itself called the allowlist an early warning, since the
same tree could edit its own list.

evidence:
test:tools/tests/test_setup_migration.py::test_setup_asks_nothing_and_writes_one_kind_of_installation ·
test:tools/tests/test_setup_migration.py::test_an_earlier_configs_context_and_remote_list_are_dropped_and_said_so ·
test:tools/tests/test_enforce.py::test_S2_G1_a_forced_state_file_is_blocked_and_an_ordinary_file_is_not ·
test:tools/tests/test_enforce.py::test_prepush_refuses_a_damaged_instance_and_a_private_path_and_allows_a_kit_tree

Boundary: on a company machine nothing in the kit now stands between an ordinary tracked file and a push to
any remote; that is the company's policy and the permissions of the Git account. A folder that was set up as
`work` loses its refusal at the next update without being asked, and the migration says so in one line. The
path check reads paths, not contents: company material written into a tracked file is not seen.

Rejected alternatives: keeping the lock as an option a person turns on (the owner asked whether even that is
needed, and nobody has asked for one); keeping the allowlist for the folders that were personal (the same
permission management under another name); asking the question at setup and only recording the answer (a
question whose answer changes nothing).

Reconsider: a user asks for a lock on a folder and Git's own permissions cannot give it.

Amends: KIT-DR-002 (its layers 2 and 3 are no longer the kit's; layer 1 stays), KIT-DR-039 and KIT-DR-041 (6)
(setup adds no remote to any list), KIT-DR-070 (1) (the start has no question).

### DR-073 A prompt's words are not judged: the worker tool and the loop stop reading prompts for path names (2026-11-26 · active)

Decision: a boundary is drawn by which file goes where and by the folder a process runs in, not by words found
in a text.

1. `tools/fresh_worker.py` no longer reads a prompt for the names of denied paths. A worker in the instance
   can open what the session can. A copy leaves out every path `egress.model_send` denies, and a prompt file
   or read material under such a path is refused for a worker in a copy or a worktree.
2. The improvement loop no longer masks private paths in its prompts or checks that a prompt names none
   (`redact`, `assert_prompt_clean`).
3. Nothing is added that closes paths to a worker by file rules.

Context: `decision:KIT-DR-043`, `decision:KIT-DR-071`. The owner's words (translated): this is not the way,
with forbidden words; isolate what each file is allowed, and do not block by hard rules on words, here or
anywhere else. The text check refused a prompt that said not to open the private folder, because the sentence
spelled its path, and it stopped nothing: a worker in the instance could open the folder whatever its prompt
said. Measured on macOS with a dummy private file and the worker's own flags, from another folder: Claude Code
2.1.292 and Antigravity 1.5.17 refused to read, search or follow a link to the file; Codex 0.153.4 read it
under its default sandbox.

evidence:
test:tools/tests/test_egress.py::test_a_prompt_that_names_a_denied_path_is_run_because_its_words_are_not_judged ·
test:tools/tests/test_egress.py::test_a_prompt_file_under_a_denied_path_is_refused_for_a_copy_and_run_in_the_instance ·
test:tools/tests/test_fresh_worker.py::test_a_prompt_may_name_a_private_path_and_only_its_file_is_judged_by_where_the_worker_runs

Boundary: a Codex worker can read the rest of the disk, from a copy or a worktree too, so a copy does not keep
it out of `_private/`; `codex --web` stays refused outside the instance for that reason. What a prompt quotes
is its writer's choice, and nothing checks it. A loop prompt may now carry a private path that a test printed.

Rejected alternatives: keeping the text check as a second layer (the owner rejected the kind of rule, and it
refused honest prompts); Codex permission profiles that close the denied paths, with a trial command before
each run (built in a practice tree and measured to work on Codex 0.153.4 and 0.169.1 on macOS; a review by
another model family found four gaps, and the owner then said that knowing what `_private/` is for is enough,
KIT-DR-071 (4)).

Reconsider: a runtime can be confined to its folder for reading by a setting that is not a beta, or a user
asks for a worker that cannot open `_private/`.

Amends: KIT-DR-023 and KIT-DR-043 (the refusal of a prompt whose text names a private path), and the sentence
on it in the worker section of `system/specs/PRD-session-memory.md`.

### DR-074 Another tool's pre-push hook stops no commit (2026-11-26 · active)

Decision:

1. The kit's pre-commit hook still checks the installed pair first, and stops the commit when one of the kit's
   own hooks is missing or differs from the template. When the only finding is another tool's hook, the commit
   goes on to the gate.
2. Doctor's Git hook row warns, where it failed, when the kit's pre-commit is in place and the pre-push is
   another tool's: it says that pushes are not checked here and keeps the hook's two ways forward. Another
   tool's pre-commit hook is still a failure, because then the kit checks no commit.
3. The list of earlier template hashes that counted as current is removed from `tools/install_hooks.sh`: no
   released version installed a hook with those bytes.

Context: `decision:KIT-DR-039`, `decision:KIT-DR-072`. Git LFS installs a pre-push hook. With one in place
every commit was refused until the owner edited that hook or moved it away, though nothing was wrong with the
commit, and setup ended as incomplete. An audit of a fresh install found it. Decided by the maintainer's
assistant, who had told the owner it would be decided this way; the owner may reverse it.

evidence:
test:tools/tests/test_install_hooks.py::test_another_tools_push_hook_stops_no_commit_and_a_missing_one_does ·
test:tools/tests/test_install_checks.py::test_doctor_precommit_reads_the_check_status_words

Boundary: with another tool's pre-push hook in place, a commit made with `--no-verify` that holds a
private path is pushed unchecked until the owner adds the kit's line to that hook. A hook installed by the
last release has other bytes than this template, so `bash setup.sh --force` rewrites it after the update, as
the change log asks.

Rejected alternatives: keeping the refusal with a clearer message (the cost stays with a person who did
nothing wrong); a line printed at every commit (attention spent on each commit for a fact doctor already
states).

Reconsider: a private path is found pushed from a folder where another tool's pre-push hook was in place.

### DR-075 The options list holds only switches; Codex and the transcript retention are facts it reports (2026-11-26 · active)

Decision: `tools/options.py` lists three optional parts, each a switch the kit can turn: `meaning`, `deliver`
and `loop`. Below them it prints two facts about the machine: whether the `codex` program is installed, and
how many days Claude Code keeps transcripts in this folder. `on` and `off` with `codex` or `history` change
nothing and say that the name is not a switch. Setup's count of parts that are off, the README, the manual and
the change log all say three.

Context: `decision:KIT-DR-052`, `decision:KIT-DR-057`. An audit of a fresh install found the list's first
line, "each stays off until you turn it on", printed above two entries that were on: they read the machine,
and nothing the kit did turned them on or off. `off codex` only recorded a no. The count of parts that were
off differed by machine and by document (three on setup's last line, five in the README and the manual).
Decided by the maintainer's assistant; the owner may reverse it.

evidence: test:tools/tests/test_options.py::test_setup_lists_once_and_changes_only_what_is_typed ·
test:tools/tests/test_options.py::test_the_list_and_doctor_read_the_same_retention ·
test:tools/tests/test_options.py::test_manual_describes_every_option_in_order

Boundary: a configuration that recorded a no to `codex` or `history` keeps that entry under
`options.declined`; nothing reads it.

Rejected alternatives: keeping five entries and rewording the first line (two would still take `on` and `off`
and do nothing); dropping the two lines (how long transcripts are kept decides what recall can find, and a
person does not see it anywhere else).

Reconsider: the kit gains a real switch for either, for example a per-folder retention setting it may write.

### DR-076 A worker's copy holds the owner's own folders, and a link run says what it did not read (2026-11-26 · active)

Decision:

1. `tools/lib/paths.py` has one answer to which top-level names are the owner's in a kit installation: a name
   that the ignore file's deny-all rule (`/*`) is what ignores, that neither the kit nor its state owns, and
   that does not start with a dot (`owner_names`, `owner_files`). Where the ignore file has no such rule,
   Git's own list already holds the owner's files and the answer is empty.
2. A worker's copy holds those files beside what Git lists. Symbolic links, version-control and package
   folders, the kit's state and every path the model-send policy denies stay out, as before.
3. A plain `python3 tools/linkcheck.py` run and doctor's link row say when the owner's own folders were not
   read. The turn-end check keeps its scope: the files Git lists and the Markdown a turn edited.

Context: `decision:KIT-DR-043`, `decision:KIT-DR-069`. The kit's ignore file denies every top-level name and
restores only the engine, so in an installation Git lists none of the owner's documents. Three places took
Git's list for "the documents". An audit of a fresh install found them: a Gemini worker, which runs in a copy
by default, was handed a folder with the kit and none of the owner's files; a link run by hand and doctor's
link row reported no broken reference without having read a note of the owner's. The kit grew in a workspace
whose documents Git tracks, where the three were right.

Measured at the receiving end with a real Gemini worker (Antigravity CLI) in two fresh installations, each
holding a note `notes/plan.md` with a codeword: asked for the codeword, the installation with this change
returned it; the one without ended as a failed run after 108 seconds, because the worker did not find the file
and tried a shell command that its rules refuse.

evidence:
test:tools/tests/test_fresh_worker.py::test_a_copy_in_a_kit_installation_holds_the_owners_own_folders ·
test:tools/tests/test_linkcheck.py::test_a_plain_run_says_when_the_owners_own_folders_were_not_read ·
test:tools/tests/test_install_checks.py::test_doctor_link_row_says_when_the_owners_folders_were_not_read

Boundary: the copy takes every file of the owner's folders, whatever its size or kind; on a volume without
file clones a large folder costs time and disk for the length of the run. A link run by hand still does not
read the owner's folders: `python3 tools/adopt.py FOLDER --dry` counts one folder's broken links. A nested
ignore file inside an owner's folder is not honoured.

Rejected alternatives: widening the link run and the turn-end check to every file of the owner's (a link the
turn did not break would stop the turn, which KIT-DR-069 ruled out); walking the whole folder wherever the kit
runs (in a workspace with its own ignore file this would bring in what the owner ignored on purpose); a cap on
the copy's size (no measurement to set it by).

Reconsider: a copy of a large folder is slow enough to notice, or a person asks for a link run over their own folders.

### DR-077 A search of the owner's words leaves out only the message that is asking (2026-11-26 · active)

Decision: `tools/lib/recall_store.py` leaves out one message, the newest of the session whose transcript was
written last, when it was typed in the last ten minutes. Before, it left out every message typed in the last
ten minutes and called them all the turn that is asking.

Context: `decision:KIT-DR-065`. Found by walking the front page's promises in a fresh installation with real
Claude Code sessions. The owner typed a sentence in one session; a minute later a new session was asked to
quote it. The agent ran the search, the search returned nothing, and the agent told the owner that the only
message it could find was the one just sent. With this change the same walk ended with the sentence quoted
word for word.

evidence:
test:tools/tests/test_recall_store.py::test_only_the_asking_message_is_left_out_not_what_was_typed_a_moment_ago ·
test:tools/tests/test_recall_store.py::test_lines_fit_the_budget_and_the_asking_turn_is_left_out

Boundary: a search from a session that keeps no transcript, such as a worker, leaves out the newest recent
message of another session instead. When a turn has run for more than ten minutes, its own question is no
longer left out and can match itself.

Rejected alternatives: a shorter window (any window hides what was typed inside it); leaving out nothing (the
question matches itself and takes the first line).

Reconsider: a runtime gives a command the id of the session that started it, which would name the asking
message exactly.

### DR-078 The agent suggests `_private/` for what only looks confidential, and uses it when the owner calls the material confidential (2026-11-26 · active)

Decision: rule 2 has three cases.

1. The owner has said so, or has called the material confidential: the agent logs it with `--private` and says
   in one line that it did.
2. Something only looks that way, such as another person's private matter: the agent logs it the ordinary way
   and suggests once that it go under `_private/`.
3. An ordinary work note that names a plan or a colleague: no suggestion.

Context: `decision:KIT-DR-071`, which told the agent to suggest once for "company material or another person's
details". Walked in a fresh installation with real Claude Code sessions: under that wording the suggestion
came with three of three logged notes, among them a note that named a colleague and a launch date, so in a
workspace used for work it would come with almost every line. The owner had asked for a suggestion "when
needed".

Measured after the change, each in a new session: three ordinary notes, no suggestion; salary bands the owner
did not call confidential, logged the ordinary way with one suggestion; supplier terms the owner said were
under an NDA, logged with `--private` and one line saying so, twice of two.

Case (1) is the maintainer's assistant reading "the owner decides" to include the owner's own statement that
the material is confidential; the owner may reverse it.

evidence: none

Boundary: nothing enforces the three cases; they are what a model did in nine sessions with one model. A line
logged the ordinary way that the owner later wants kept local is moved by hand.

Rejected alternatives: asking before every private line, also when the owner has just called the material
confidential (a question whose answer the owner already gave); keeping the earlier examples (measured above).

Reconsider: the suggestion comes back as noise, or material the owner called confidential is logged the ordinary way.

### DR-079 The rules say how to write a line and when to read which file, so an agent logs a decision in one command (2026-11-26 · active)

Decision:

1. Rule 2 names the types a line usually takes (`decision`, `state`, `correction`, `lesson`) and says the
   track is any short name.
2. `python3 tools/now.py log --help` answers with the types and tracks of the workspace and writes nothing; so
   does `log` with no line.
3. The line above the rules says when `instance/rules.md` is read: before the owner's files are changed or
   moved or outside material comes in, not before every answer.
4. The list of when to read which document no longer sends an agent to `system/rituals.md#entry` at every
   session start, only when it takes over a long task, after a compaction, or on coming back to a topic.

Context: `decision:KIT-DR-006`. Found by walking the front page's promises in fresh installations with real
sessions. Told one decision, Claude Code made one to three tool calls to log it, often a chain of commands
that read the rules file and the config first; Antigravity read eight files, the tool's own source among them,
and asked `log --help`, which refused the words as a malformed line. With a person present each command is an
approval, and a chain is a new approval every time.

Measured after the change, each in a new session: Claude Code logged three different decisions with one plain
command each; Antigravity made two calls before the line, where it had made eight, and its input went from
about 26,000 tokens to about 14,000. An earlier wording that named `log --help` in the rule made Claude Code
call it first every time, so the rule names the types instead.

evidence: test:tools/tests/test_install_checks.py::test_log_help_answers_with_the_types_and_tracks_of_this_workspace

Boundary: four sessions with two models; nothing enforces what a model reads first. The always-loaded rules
grew by about 400 bytes in this and the last two records, to about 2,500 tokens for a new session. A workspace
that adds types of its own in its config still has them only in `log --help` and in the refusal.

Rejected alternatives: putting the tracks and types into the state given at session start (a cost in every
session for a doubt that comes only when a line is written); leaving the model to find out (measured above).

Reconsider: a model logs without these sentences, measured the same way.

### DR-080 A tool says when it had nothing to read, and three rules nobody read are removed or made conditional (2026-11-26 · active)

Decision:

1. `python3 tools/now.py threads` says that the private thread list is unavailable when
   `_private/state/threads.json` cannot be read, and exits 1; it used to say that no threads were registered.
2. `python3 tools/facts.py find` and `hot` without a ledger say that no facts are recorded yet, name the
   command that records the first, and exit 0.
3. `python3 tools/coherence.py` and doctor's coherence row say that nothing is listed to check when
   `checks.hubs` and `checks.status_docs` are empty; they used to report OK.
4. The line of `system/rituals.md` that asked for one sentence after a compaction, naming the procedure and
   the step, is removed.
5. The six writing steps of `system/rituals.md#outbound` are removed; the section keeps the two lines before
   the body and points to the `plain-writing` skill, which holds the one procedure.
6. A deep-pass record is written only where the owner keeps a ledger; an agent does not start one.
7. `tools/ask_codex.sh` loses `--fresh`, which did nothing.

Context: `decision:KIT-DR-064`, `decision:KIT-DR-009`, `decision:KIT-DR-063`. Each came from the audit of a
fresh install by independent agents. A registry that cannot be read was reported as empty, against rule 2's
own words. Rule 3 sends an agent to `facts.py find`, which ended in an error in every new installation. The
coherence check passed while checking nothing. The line after compaction rested on one paper's report and
nothing read or counted it. The outbound procedure existed twice with different wording, and a walked session
opened both. The deep-pass ledger had one reader, the improvement loop's garden source, which is off. Decided
by the maintainer's assistant; the owner may reverse any of them.

evidence:
test:tools/tests/test_install_checks.py::test_an_unreadable_private_thread_list_is_said_to_be_unavailable ·
test:tools/tests/test_facts.py::test_find_distinguishes_uncreated_ledger ·
test:tools/tests/test_coherence.py::test_an_instance_that_lists_nothing_is_told_nothing_was_checked

Boundary: whether an agent still loses its place in a procedure after a compaction has not been measured here,
with or without the removed line. An owner who wants every deep pass recorded starts the ledger once by
copying the template.

Rejected alternatives: creating an empty fact ledger at setup (an empty folder for a feature most owners never
use); keeping the outbound steps in both places and keeping them in step by a test (two texts to read where
one does).

Reconsider: a measurement shows agents losing their place after compaction in this kit; owners ask for the
deep-pass record by default.

### DR-081 What a second audit of a fresh install found, fixed (2026-11-26 · amended_by:DR-082)

Decision: from seven independent auditors of the changed kit and the builder's own reproduction.

1. The commit check judges the state page only where Git tracks it; in a kit installation it no longer asks to
   stage a page Git ignores.
2. A worker's copy keeps an owner's folder that holds one tracked file (`git check-ignore --no-index`).
3. A push refused for a private path names the step that works: drop the file from the commit that added it,
   since a later deleting commit is still sent.
4. Setup asks nothing on a terminal either: the options step prints one line, and the count of parts that are
   off includes those the owner said no to.
5. A config left out and written again from the template keeps earlier decisions in view: with no list of
   public tracks nothing is frozen private; and the two cutover keys take their defaults when left out.
6. An update drops `public_tracks: ["system"]`, the exact list the released v0.10 template shipped, and says
   so.
7. `--help` on the loop's four entry points prints usage; on the cycle scripts it used to start a cycle.
8. The view at session start counts the lines past its row limits; the folded compaction row no longer tells a
   new session that its context is a summary.
9. A Claude or Gemini worker refuses a write scope or an expected output.
10. Worker runs are counted under their own runtime.
11. Doctor does not warn about a runtime that has no transcripts; it was almost always simply unused.
12. `gate.py manual-check` leaves out the stale-page finding a turn end renders away.
13. A track's canonical file behind its newest decision is a reminder that never stops a turn.
14. `linkcheck.py --mine` reads the owner's own folders, and a plain run no longer lists the kit's first-use
    files.
15. Setup copies no file for the loop; the loop reads the template's correction groups until the owner keeps
    their own.
16. Turning the loop on states what a measured cycle cost, and the loop page says to commit an applied patch
    so that `git pull` merges it.
17. The `recall` skill and the garden's lookup search the owner's own words with a full question. Sentences
    made true: the push check refuses a private path only; three optional parts; `_private/` keeps things out
    of Git and out of what is written for others, while the agent still reads it; the doctor rows for Codex
    and Antigravity arming and for compaction; the rules table rows on the gate lock and the commit check; the
    coaching count; the README's lines on the seven rules, the loop and recall.

Context: `decision:KIT-DR-064`, `decision:KIT-DR-071`, `decision:KIT-DR-076`, `decision:KIT-DR-079`. The
audit's ledger is outside the kit. Five of the defects were introduced by the same day's changes (the push
sentence, the copy of a partly tracked folder, a rules-table row, the count of optional parts, the compaction
line still named on the assumptions page); each was a sentence or an edge case that the builder's tests did
not reach. Of four defects the builder held back to test the auditors, two were found. Decided by the
maintainer's assistant; the owner may reverse any of them.

evidence: test:tools/tests/test_install_checks.py::test_a_commit_does_not_judge_a_state_page_git_ignores ·
test:tools/tests/test_fresh_worker.py::test_a_copy_in_a_kit_installation_holds_the_owners_own_folders ·
test:tools/tests/test_enforce.py::test_prepush_refuses_pushed_private_commit ·
test:tools/tests/test_options.py::test_setup_lists_once_and_changes_only_what_is_typed · decision:KIT-DR-082
(removed test tools/tests/test_setup_migration.py::test_configless_recovery_keeps_earlier_decisions_in_view) ·
decision:KIT-DR-082 (removed test
tools/tests/test_setup_migration.py::test_the_released_default_track_list_is_dropped_on_update_and_said_so) ·
test:tools/tests/test_tool_entrypoints.py::test_the_loops_entry_points_answer_help_and_start_nothing ·
test:tools/tests/test_install_checks.py::test_lines_past_the_row_limits_are_counted_in_the_view ·
test:tools/tests/test_fresh_worker.py::test_a_worker_that_cannot_write_refuses_a_write_scope_before_anything_runs ·
decision:KIT-DR-088 (test moved out of the kit with the session-reading source:
tools/tests/test_garden_lanes.py::test_worker_runs_are_counted_under_the_runtime_their_folder_names) ·
test:tools/tests/test_doctor_json.py::test_runtime_transcripts_row_says_so_for_an_installed_runtime_with_none ·
test:tools/tests/test_linkcheck.py::test_a_plain_run_says_when_the_owners_own_folders_were_not_read

Boundary: an installation whose owner chose exactly `["system"]` as its list loses it at the update and is
told so. A store of Codex or Antigravity transcripts that moved is no longer a warning. Left to the owner:
whether the loop's garden source ships, whether commands are allowed in advance, whether the turn-end check
stops on a missed reread or a frozen path, the two-line outbound preflight, the split of the journal into two
files in a kit installation, and the migration code for configs older than v0.10.

Reconsider: a reported defect comes back in the next audit.

### DR-082 A cross-check by another model family: two of the fixes are taken back or tightened, and four limits are stated (2026-11-26 · active)

Decision:

1. Taken back from KIT-DR-081 (5) and (6): an update keeps whatever list of public tracks the installation
   holds, `["system"]` included, and a config written again without an old one freezes the journal rows
   already there as private, as before. The combined view at session start shows them either way. Only the two
   cutover keys keep their defaults when left out.
2. Tightened from KIT-DR-081 (12): `gate.py manual-check` leaves out the stale-page finding only when the
   config loads; otherwise it answers UNCHECKED, since the turn end could not render the page either.
3. Tightened from KIT-DR-081 (13): doctor shows the reminder that a track's summary is behind its decisions as
   a warning, so the reminder reaches the owner.
4. An adopted link that a measured turn sees repaired loses its excuse, so breaking it again is that turn's
   issue.

Context: `decision:KIT-DR-081`, `decision:KIT-DR-071`. The cross-check (gpt-6.2-astra, effort max) ran each
case in temporary copies and answered FAIL: an owner who chose `["system"]` would have had it widened at the
update, against KIT-DR-071 (3), and the test had been rewritten to the new behaviour; the manual check printed
PASS where the turn end blocked; the reminder reached no one; a repaired-then-broken adopted link stayed
silent.

evidence: test:tools/tests/test_setup_migration.py::test_a_saved_track_list_is_kept_on_update ·
test:tools/tests/test_setup_migration.py::test_configless_recovery_freezes_history_private ·
test:tools/tests/test_install_checks.py::test_doctor_shows_the_track_summary_reminder_the_check_gives ·
test:tools/tests/test_adopt.py::test_a_repaired_adopted_link_loses_its_excuse

Boundary, stated and not fixed: a search of the owner's words takes the session written last for the asking
one, so with two sessions writing at once it can leave out the wrong message; two messages that share their
first 2,000 characters are kept as one, so a correction at the end of a long message can be missed; the link
check reads inline links and code spans, not reference-style links or headings; a store entry whose transcript
is gone (a workspace restored on another machine) is dropped. The walks that measured the front page's
promises gave the session its approvals in advance and placed the dossier for it; whether a newcomer, unaided,
spends less attention over a week is not measured.

Reconsider: a runtime passes the asking session's id to the commands it runs; a store keeps a hash of the whole message.

### DR-083 The owner's choices on ten open questions, first part: send list, memory index, approvals, a preview (2026-11-26 · active)

Decision: the owner took the recommendations of a one-page list of ten open questions (in his words,
translated: "do as recommended", 2026-11-26 23:26). This record holds the small ones.

1. `egress.model_send.deny_prefixes` may be empty; it is the paths a worker's copy leaves out beyond
   `_private/` and the kit's state, and the loop's send switch.
2. Findings about Claude Code's memory index are reminders that never stop a turn.
3. No command is allowed in advance; SETUP says that the first days ask once per kit command.
4. The README says the kit is a preview that no newcomer has used alone for a week. The other choices have
   their own records: the reread check on, a check on frozen paths, the outbound two lines out of the kit, the
   pre-v0.10 migration removed, and the loop's garden source left out of the first release.

Context: `decision:KIT-DR-043`, `decision:KIT-DR-053`, `decision:KIT-DR-070`, `decision:KIT-DR-082`. The two
audits and the cross-check found that an empty deny list failed the whole config while a copy already left out
`_private/` by the kit's own list, and that the memory index stopped turns over a folder
outside the workspace. The owner kept the journal split as it is and no command allowed in advance.

evidence: test:tools/tests/test_memlib_journal.py::test_an_empty_deny_list_loads ·
test:tools/tests/test_egress.py::test_doctor_accepts_an_explicit_empty_deny_list ·
test:tools/tests/test_memory_subindex.py::test_missing_flagged

Boundary: an owner who relied on the memory index stopping a turn now sees a reminder in `now.py check` instead.

Reconsider: a copy is found holding a path the owner meant to keep from workers.

### DR-084 The reread check is on in a new installation (2026-11-26 · active)

Decision: `templates/config.json` sets `"deliver": {"block": ["unopened"]}`, so a turn in Claude Code that
hands over a long document it wrote without reopening it stops once. `on deliver` writes the same;
`off deliver` turns it off. An installation that already has its own delivery setting keeps it at an update.
The options list now says that this part is on after setup.

Context: `decision:KIT-DR-022`, `decision:KIT-DR-036`, `decision:KIT-DR-083`. The owner took the
recommendation to turn it on (2026-11-26 23:26). Rule 5 asks the agent to reread what it wrote; the README
says that what must happen every time is done by a check, not a rule to remember; the check existed and
measured right in 35 of 40 sampled hits, yet shipped off (KIT-DR-036 (4), decided by the maintainer's
assistant).

evidence:
test:tools/tests/test_setup_migration.py::test_setup_asks_nothing_and_writes_one_kind_of_installation ·
test:tools/tests/test_options.py::test_with_the_need_in_place_on_writes_the_settings_and_runs_the_first_step

Boundary: Claude Code only; Codex and Antigravity have no such step. By the sample about one stop in eight is
needless. Installations from before keep their setting until the owner runs `on deliver`.

Reconsider: needless stops are reported often enough to cost more attention than the rereads save.

### DR-085 The two lines before outbound text leave the kit (2026-11-26 · active)

Decision: the kit no longer asks an agent to write "Document role" and "Consistency anchors" before the body
of outbound text. `system/rituals.md#outbound` says what counts as outbound and points to the `plain-writing`
skill, which holds the one procedure; step 0 of the skill's guide is removed. Supersedes KIT-DR-008. An
installation that wants the two lines writes them in `instance/rituals.md`.

Context: `decision:KIT-DR-008`, `decision:KIT-DR-009`, `decision:KIT-DR-083`. The owner took the
recommendation to take them out of the kit (2026-11-26 23:26). KIT-DR-008 recorded no evidence and set a test
(remove the lines if they change no judgment in the next five outbound texts) whose result was never recorded.
In a walk with a real session the agent printed the two lines, with coined labels, at the top of its answer to
the owner, which rule 5 asks it not to do. The owner's own workspace keeps them as its own rule.

evidence: none

Boundary: whether outbound drafts get worse without the lines is not measured.

Reconsider: drafts are sent back for a wrong reader or goal that the two lines would have named.

### DR-086 Setup no longer moves a config from before v0.10 (2026-11-26 · active)

Decision: a config of schema 1, 2 or 3 is refused with one line that says to move it aside and run setup
again, which writes a new config and leaves the journal and documents as they are. The branches that froze old
journal rows by schema and refused old `threads[]` are removed, and so are their tests; doctor's row on an old
schema names the same step.

Context: `decision:KIT-DR-005`, `decision:KIT-DR-083`. The owner took the recommendation to remove it
(2026-11-26 23:26). v0.10, the first release, already wrote schema 4; schema 2 lived in the source repository
for three days in August and schema 3 never reached a template. No installation that holds one is recorded.
The code was smaller than the one-page list said: about 15 lines of the migration module, five tests and
doctor's step text.

evidence:
test:tools/tests/test_setup_migration.py::test_a_config_from_before_v0_10_is_refused_with_the_way_forward ·
test:tools/tests/test_setup_migration.py::test_configless_recovery_freezes_history_private

Boundary: an owner who still has such a config writes its tracks and threads into the new one by hand. The
next time the schema goes past 4, what the owner must do goes in `config.schema_gap()` and the move goes in
`tools/lib/config_migrate.py`, as DR-005 says; the table `SCHEMA_CHANGES` that held it is gone.

Reconsider: someone reports an installation from before v0.10.

### DR-087 The turn-end check stops a turn that edited a frozen path (2026-11-26 · active)

Decision: `instance/config.json` has a list `frozen` of paths relative to the folder, empty by default. When
an edit tool of any of the three runtimes changed a listed path, or a file under a listed folder, the turn-end
check of the session that made the edit stops once and says to put it back unless the owner asked for it.
`instance/rules.md` section 1 keeps the reasons and points to the list.

Context: rule 1 of `AGENTS.md` said nothing checked it by machine, and the frozen areas it protects (evidence,
source material) may be impossible to recover. The edit list the link check already keeps names each edited
file per session, so the check costs one comparison. The owner took the recommendation to build it (2026-11-26
23:26).

evidence: test:tools/tests/test_gate.py::test_a_turn_that_edited_a_frozen_path_stops_once

Rejected alternatives: reading the paths from the prose of `instance/rules.md` (a bullet's wording would
decide what is frozen); refusing the edit before it happens (only Claude Code can refuse a tool call, so the
three runtimes would differ); also comparing the folder with Git at every turn end (a change the owner made by
hand would stop every agent's turn).

Boundary: the edit has already happened when the turn stops; a shell command that changes a frozen path is not
seen, and neither is a path left out of the list.

Reconsider: an agent changes a frozen path with a shell command in a recorded session, or every runtime can
refuse a tool call by path.

### DR-088 The first release ships the loop with papers only; a source that reads the owner's sessions is added by the installation (2026-11-27 · active)

Decision: the loop's session-reading source (its weekly review of the owner's messages, its counting lanes,
its two prompts, its correction groups and its health check) leaves the kit. What the rest of the loop asked
of it became one seam, `tools/loop/lib/loop_sources.py`: an installation adds a source as one module in
`tools/loop/sources/`, and the sending statement, the options, the schedule, the status, the applier, the
judge, the health check and the never list reach it only there. The kit's code names no source but papers. The
manual `/garden` audit is a different thing and stays.

Context: `decision:KIT-DR-057`, `decision:KIT-DR-061`. That source had never run with real models, and it was
bound to one owner's files (a lens ledger table, a deep-pass ledger, rules made from night-time messages): in
a new folder it would send a model counts of nothing. The owner took the recommendation to leave it out of the
first release and keep it in their own workspace (2026-11-26 23:26). Keeping it there without a copy of each
shared loop file is what the seam is for. The one-page list made it sound small: it changed seventeen loop
modules, the options tool, seven documents and thirteen test files, and with the source's own files and tests
gone 2,367 lines left the kit and 622 came in.

evidence: test:tools/tests/test_loop_sources.py::test_an_added_source_is_known_listed_judged_and_watched ·
test:tools/tests/test_loop_sources.py::test_a_broken_source_module_stops_the_loop_with_its_path

Rejected alternatives: leaving the code in the kit unoffered (a reader of the kit would find a source nothing
turns on, and its tests would keep running in the kit); copying the shared loop files into the owner's
workspace with the source in them (every later change to the loop would have to be merged by hand there).

Boundary: an added source is the installation's code: the kit's tests do not run it, and a kit update can
change the seam under it; the seam's page says what it may define.

Reconsider: the session-reading source runs with real models in more than one folder, or a second installation
adds a source.

### DR-089 Waiting work stops a turn once; an installation can keep its own record of verdicts (2026-11-27 · active)

Decision:

1. `checks.waiting` in `instance/config.json` lists prefixes of the state-check issues an installation's own
   `tools/now_instance.py` reports for work that waits outside any turn. When every new issue of a turn end is
   such an item, the set stops that turn once with the counts per prefix; the same set or a part of it never
   stops a turn again, and each prompt says the items are waiting instead of saying a turn failed. A new item
   makes a new set. A failed checker, a baseline that is not ok and any other new issue still stop the turn as
   before.
2. The turn-end check hands each verdict (pass, block, waiting, repeat, warn) to `record()` in the
   installation's own `tools/gate_instance.py`, when there is one.
3. The plain-writing skill also follows an `outbound` section of `instance/rituals.md`.
4. An installation lists the tools it adds in a `README.local.md` beside a README under `tools/`; the test
   that every tool is listed reads both, so the kit's own pages stay the kit's.
5. `system/dev/kit-files.txt` lists the kit's own files; the language check reads only those, so an
   installation's own documents and tools in its owner's language are not judged, and in the kit's tree a test
   keeps the list equal to what Git tracks.
6. The tests that build a copy of the tree (the fresh install, the English setup and the hook tests' instance)
   copy only the listed files, so in an installation they neither copy its documents and data nor fail on
   their links into its private area (`tools/tests/testlib.py` `copy_kit`, `kit_repo`).
7. The mutation test and the setup-migration test copy only the listed files too: in the source workspace each
   copy of the whole tree took about 9 GB and filled the disk.
8. The test that the kit speaks English measures the live doctor and link check only in the kit's own tree; an
   installation's output names its own files in its owner's language, so there only the setup fixture built
   from the kit's files is measured.

Context: the source workspace kept a copy of the turn-end check with all three for its recording pipeline, its
research log of verdicts and its own lines before outbound text; moving that workspace onto the kit as an
ordinary installation (2026-11-27, the owner: "move into the new kit") needs places for them that are not
copies of engine files. `decision:KIT-DR-064`, `decision:KIT-DR-085`.

evidence: test:tools/tests/test_gate.py::test_waiting_items_stop_a_turn_once_and_then_only_wait ·
test:tools/tests/test_language.py::test_the_kit_file_list_names_every_tracked_file

Rejected alternatives: the installation's checks reporting waiting items as notes that never stop a turn (the
one stop is what makes an agent run the pipeline); a hard-coded list of prefixes (the kit ships no pipeline).

Boundary: what counts as waiting is the installation's word; a prefix that also matches a real failure would
let that failure stop only once.

Reconsider: an installation reports waiting items that an agent never acts on after the one stop.

### DR-090 An installation keeps folders of its own in Git below a marker in .gitignore (2026-11-27 · active)

Decision: `.gitignore` ends with a marker line, `# --- this installation's own lines ---`. An installation
writes below it the folders of its own that Git should keep (`!/notes/`) and further ignore lines; a
`git pull` merges the kit's lines above it and keeps these. Doctor's row on engine changes counts only a
change to a file the kit ships (`system/dev/kit-files.txt`), and a change to `.gitignore` only above the
marker. `CHECKLIST.md` and `MANUAL.md` (Where things are) say how.

Context: `decision:KIT-DR-002` made the ignore file deny everything and restore the engine, so nothing an
owner writes reaches a remote by accident. The source workspace keeps its documents in a private repository,
its only backup; moving it onto the kit (KIT-DR-089) would have left every new document outside Git, and
doctor would have called each edit of a tracked document an engine change.

evidence: test:tools/tests/test_install_checks.py::test_doctor_counts_only_the_kit_files_as_engine_changes

Rejected alternatives: restoring folders through `.git/info/exclude` (Git ranks the root `.gitignore` above
it, so a folder `/*` denies cannot be restored there); a folder `.gitignore` inside each folder (Git never
enters a folder the root denies).

Boundary: what an owner restores is theirs to keep private; the push check still refuses `_private/`,
`instance/` and `state/`.

Reconsider: owners keep their documents in a repository of their own beside the workspace instead.

### DR-091 The full installed-shape run takes only the kit's own tests (2026-11-27 · active)

Decision: `tools/tests/test_instance_shape.py --full` copies every tracked file under `tools/` into its
synthetic instance, as before, but runs only the test files listed in `system/dev/kit-files.txt`. A test an
installation added is left out of that run; the installation runs it in its own tree with the rest of the
suite. A tree without the list runs every test file.

Context: in the source workspace, moved onto the kit as an installation (KIT-DR-089), the full run also ran
that workspace's own instance test, which checks its real archive ledger and its own trigger patterns; the
synthetic instance has neither, so the run failed on two checks while the same file passed 83 of 83 in the
workspace itself. `decision:KIT-DR-089`.

evidence: test:tools/tests/test_install_checks.py::test_the_full_shape_run_takes_only_the_kit_tests_in_an_installation

Rejected alternatives: giving the synthetic instance copies of an installation's data (the point of the
fixture is that it holds none); asking each installation to mark its own tests (the kit file list already says
which files are the kit's).

Boundary: an installation's own tests are not run inside the synthetic instance, so a kit change that breaks
only them shows in the installation's own suite, not in the shape run.

Reconsider: an installation's own test needs the installed shape to catch something its own tree cannot.

### DR-092 The kit's Markdown wraps its prose near 110 characters, and a test keeps every line within 120 (2026-11-27 · active)

Decision: a line of prose in a Markdown file the kit ships is at most 120 characters, and is wrapped near
110. `tools/tests/test_markdown_lines.py` fails on a longer one in any file `system/dev/kit-files.txt` lists.
Not prose, and so never measured: a heading (a decision record's heading carries its status on one line), a
table row, an HTML line, fenced code, the front matter of a skill and a line with no space outside inline code
within the limit (a long URL, evidence marker or code span).

The kit's existing Markdown was laid out to match, without changing a word. A labelled part of a decision
record is its own paragraph, and the label stays at the start of its line, where the evidence check reads it.
A part whose sentences start with (1), (2) or (a), (b) is a list: numbers as a numbered list, letters as
bullets that keep the letter. A long paragraph is split where one idea ends. A script compared the words of
each record before and after, and the evidence check's view of every record's context is unchanged; the text
of earlier records is not rewritten.

The four prompt templates of the loop are short sections, such as what to read, what to write and the rules,
with every placeholder and instruction kept. The tables of `system/specs/model-assumptions.md` whose cells held
paragraphs (sections 2, 3, 4 and 8) are one list entry per row. A new record and a new page follow the same
layout.

Context: the owner opened `system/loop/prompts/propose.md` to review it and found six lines, one of them
1,641 characters, which a reader cannot follow and a diff shows only as one changed line. Nothing measured
line length, and newer records and the prompts were written as one line per part. Before this record, 601
lines of prose in 62 of the kit's 117 Markdown files ran past 120 characters: 406 in this file, whose longest
line was 5,779 characters, 39 in `PRD-session-memory.md` and 30 in `PRD-info-architecture.md`.

evidence: test:tools/tests/test_markdown_lines.py::test_kit_markdown_keeps_prose_lines_within_the_limit ·
test:tools/tests/test_markdown_lines.py::test_a_long_prose_line_fails_and_the_lines_that_cannot_wrap_pass

Rejected alternatives: a Markdown formatter (the kit needs only Python and Git, and a formatter rewrites the
tables and lists that tests read); one limit for every line, tables and headings included (a table row and a
heading cannot be wrapped); turning every table into a list (`tools/tests/test_rules_table.py` reads
`system/dev/enforcement.md` row by row, and `tools/tests/test_setup_migration.py` reads a row of the
configuration table in `MANUAL.md`).

Boundary: the test measures line length only. Whether a paragraph holds one idea is for review, and a table
row is not measured, so a table whose cells grow into paragraphs passes. Text a tool prints and a prompt built
in Python (`tools/loop/lib/loop_prompts.py`) are not Markdown files and are not measured.

Reconsider: a parser needs a line of prose whole that the test would make someone wrap, or the renderer the
owner reads the kit in shows wrapped source worse than long lines.

### DR-093 The owner's work lives in projects/, one folder per project (2026-11-27 · active)

Decision: setup creates `projects/` with its guide, `projects/README.md`. Every folder there is a project, named
after the folder, for documents, scripts and small code alike. A block at the top of its `README.md` can add a
`name`, an `area`, a `status` (`active`, `paused`, `planned` or `closed`), a `canonical` file to open first,
`outside` (folders that stay where they are) and `private` (its parts under `_private/`); every line is
optional, and the folders and their blocks are the only place projects are described:

1. the map between the one marker pair in `projects/README.md` is redrawn with the public state page, and by
   `python3 tools/projects.py draw`, which also adds the pair to a guide that has none; a file not written yet
   is named in the map, not linked;
2. the public state view names the open project folders by status in one line, counts the closed ones, and gives
   one line per open project with outside folders, within 800 bytes of its own, because it shares the
   session-start cap with the newest decisions;
3. doctor's projects row warns about what a block names but cannot find (the canonical file, an outside folder,
   a private part), a field it does not know, a block with no closing line, and markers it cannot draw between.
   Nothing about a project fails doctor.

A folder with its own repository, a scheduled job or another program writing to it, its own virtual
environment, or its own agent instructions stays where it is and is named under `outside`. The kit writes no
runtime permission for it; the manual names the flag and the setting. When a project ends, only its status
changes. The kit tracks nothing under `projects/`; the default deny keeps it out of Git until the owner
restores it below the marker (KIT-DR-090).

Context: moving the source workspace onto the kit left its owner's material in about thirty folders at the root
beside the kit's own, with one project's documents, code and private part often in three places, and some of it in
folders its owner's agents had put under `_private/` by caution. The owner asked whether moving everything under
one folder was coherent at all, whether a user should not be able to keep existing folders and only map them, and
said a game has code, not documents. The kit had only "whatever you create at the root", track canonicals and
dossiers that had to be inside the workspace (a `~` path read as a folder named `~`), and no record of a folder
added with `--add-dir`. `decision:KIT-DR-069` had rejected a layout of the owner's folders; this record keeps the
owner's folders free inside a project and only names the one place projects live.
`decision:KIT-DR-090` had named the condition this meets.

evidence: test:tools/tests/test_projects.py::test_every_folder_is_a_project_and_nothing_fails ·
test:tools/tests/test_projects.py::test_the_map_is_drawn_between_one_marker_pair_and_nowhere_else ·
test:tools/tests/test_projects.py::test_the_session_start_section_has_a_byte_cap ·
test:tools/tests/test_projects.py::test_setup_gives_a_new_instance_the_projects_guide

Rejected alternatives: areas as the first level of folders (a project can belong to two areas, and changing an
area would move every path in it; the area is a column of the map instead); a list of projects in
`instance/config.json` (a second list beside the folders drifts from them within weeks); moving every outside
folder in (a scheduled job or a repository's history would break); symbolic links as the map (copies for
workers skip them, and a link is invisible to the state view).

Boundary: tracks and threads in `instance/config.json` stay as they were, so the status board is still a list
the owner chooses; a project shows there only when it is also a track. Outside folders are not link-checked,
not frozen and not backed up by the kit, and a session opened inside one gets no state from this workspace.

Reconsider: the board's tracks and the projects drift apart in a real installation, so that tracks should be
read from the projects too, or owners keep most of their work outside and `projects/` holds only pointers.

Changed in review before it was published (2026-11-27). A fresh-installation check and a reviewer from another
model family found that following the guide broke the kit's own promises, so the first version was changed
before release: (1) bringing a folder of notes into `projects/` as the guide says made doctor fail, and the only
fix was to edit the folder the rules say to leave alone, so a folder with no block is now a project and nothing
about a project fails doctor; (2) a planned project's first file not written yet failed setup with "do not trust
the hooks", which is now a warning; (3) the `dossier` and `journal` fields were read by nothing else, and
dossiers already live in `threads`, so both were removed; (4) a capitalized key or an unindented list item was
dropped without a word, so keys are read in any case, list items at any indent, and an unknown field is named;
(5) the map went stale with nothing redrawing it, and a lone marker let a second draw erase the owner's text, so
the map is redrawn with the state page and only between exactly one marker pair; (6) closed projects and long
outside lists could push the newest decisions out of the session-start view, so closed projects are counted, not
listed, and the section has a byte cap; (7) a warning about an active project untouched for 60 days measured
only the local folder, so it fired while work went on in an outside folder, and no person had asked for it, so
it was removed. The map's display words (`projects.map_words`) are there for an installation that writes its map
in another language, as the source workspace does.

A second fresh-installation check and a second pass by the other reviewer, run on the changed version, found
what the first round had left: doctor's link row still failed for a brought-in folder's old broken links once
Git kept `projects/`, so it now reads the same record of them as the turn-end check; adopt's refusal sent a
folder to the workspace root, so it names `projects/`; front matter of another kind (a site generator's `title`
and `tags`) in a brought-in README raised warnings that only an edit could clear, so a block with a field unlike
any of the kit's is left unread, and only a near miss such as `statuss` is named; a canonical written from the
workspace was doubled, so both forms are read; a folder name with spaces broke its map link, so links are
encoded; a renamed project left the map stale until the next logged line, so the map is one of the state page's
inputs; a redraw opened the guide for writing before it had the new text, so it is written whole or not at all;
and a long first line broke the session-start cap, so that line is cut too. A folder under `projects/` that is a
link to a folder elsewhere is named instead of counted.

Boundary added in review: the map names every project with its outside and private paths, and
`projects/README.md` goes into a worker's copy like any other file, so a project left out of worker copies by
`egress.model_send.deny_prefixes` still shows its row there unless the guide is left out too.

### DR-094 Setup turns on search by meaning when it costs nothing (2026-11-27 · active)

Decision: setup turns the list by meaning on when an embedding server on this machine already answers with its
model and the owner has not declined it before: nothing is downloaded and nothing leaves the machine. It writes
the settings, draws the state page again for the new configuration and says so in one line; the first index is
built by the catch-up at the next session start. When the server or the model is missing, setup changes nothing,
as before. `MOTTORI_NO_LOCAL_PROBE=1` keeps setup from asking the server; the test runner sets it, so a server
on a developer's machine changes no test. While the list is off and the owner has not said no, a search says so
with the command that turns it on: the word search in its notices, a search of the store on its closing line. A
no to the download question of `on meaning` is recorded like `off meaning`, so setup never turns the list on
after it.

Context: the source workspace ran its first sessions after the move with the list off although the model was
installed and serving, and nothing said it was off; its owner asked why it was not running and whether new
users would start the same way. `decision:KIT-DR-055` asked for one yes because turning it on downloads
0.6 GB; with the model already present there is nothing to say yes to.

evidence: test:tools/tests/test_options.py::test_setup_turns_meaning_on_only_when_the_local_server_already_answers

Rejected alternatives: downloading the model at setup (`decision:KIT-DR-055`); asking at setup (setup asks
nothing, an agent runs it); leaving it off with a line in the options list (the source workspace showed the line
is not read).

Boundary: the answer is checked with the same two-second probe as `on meaning`, through the loopback address
only. A machine where another program answers on that address with the same model name is taken at its word.

Reconsider: an owner finds the list on without having known it existed, or the first index slows the first
session enough to be noticed.

Changed in review before it was published (2026-11-27): a reviewer from another model family found that
answering no to the download question left no record, so a later setup turned the list on after that no, and
that the word search, the route a new installation takes first, never printed the off line.

### DR-095 Doctor warns about a path in the configuration that names nothing (2026-11-27 · active)

Decision: doctor's config-paths row warns when a path inside the workspace in `instance/config.json` names
nothing on disk: `frozen`, `loop.never`, `loop.clone_excluded`, track canonicals and secondary documents, thread
dossiers, `personal_pointer`, `checks.status_docs` and `checks.hubs` (the folder and its index), and a
link-check exclusion that matches nothing. With no such path the row does not apply.

Context: when the source workspace reorganized its folders, about forty such paths still named the old places.
Each one would have stopped protecting or pointing (the turn-end freeze, the loop's never-list, the sandbox
exclusion) without a word.

evidence: test:tools/tests/test_projects.py::test_doctor_warns_about_a_config_path_that_names_nothing

Rejected alternatives: a failure (the first version failed: a path can also name a folder not made yet, which
the turn-end check still covers once it exists, and a failure tells the owner not to trust the hooks, which is
not true here); rewriting the paths automatically (only the owner knows where a moved folder went).

Boundary: paths outside the workspace are not checked here; a project's outside folders are the projects row's.

Reconsider: an installation keeps a path that names nothing on purpose, such as a folder created later.

Changed in review before it was published (2026-11-27): a reviewer from another model family found that a frozen
folder not made yet still protected on its first edit, so the failure was wrong; that `deliver.outbound_folders`
was checked although no tool reads it, so it was dropped; and that a hub's index file was not checked. A
fresh-installation check found that an empty list passed as a check that had found nothing and that
`personal_pointer` was missing.
The second pass added the worker copies' exclusions (`egress.model_send.deny_prefixes`), since a moved folder
kept out of worker copies lets the files at its new place go to workers, and a link-check exclusion written with
a leading `./`, which matches nothing.

### DR-096 The root holds only what a runtime, GitHub or a first-time reader needs (2026-11-27 · active)

Decision: the checklist of what only a person can check is `system/CHECKLIST.md`, and the contributing guide is
`.github/CONTRIBUTING.md`, where GitHub still shows it. The root keeps `README.md`, `AGENTS.md`, `CLAUDE.md`,
`LICENSE`, `SETUP.md`, `MANUAL.md`, `CHANGELOG.md` and `setup.sh`, beside `system/`, `tools/` and `templates/`.

Context: a new user's root held sixteen entries before they wrote anything, none of them theirs. `SETUP.md`
stays because the first instruction is to read it, `CHANGELOG.md` because a pull sends owners there, and
`MANUAL.md` because the README and the doctor name it.

evidence: test:tools/tests/test_projects.py::test_the_root_holds_only_what_a_runtime_github_or_a_first_reader_needs

Rejected alternatives: moving every document into a folder (agents and people look for the setup page at the
root, and renamed files break outside links); grouping `instance/`, `state/` and `_private/` under one folder
(hooks, tools and months of journals use these names, for three fewer entries).

Boundary: an installation's root also holds `instance/`, `state/`, `_private/` and `projects/`.

Reconsider: GitHub or the runtimes start reading these pages from another place.
