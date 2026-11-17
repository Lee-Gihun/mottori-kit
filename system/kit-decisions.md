# Kit design decision records (KIT-DR)

**This file holds the kit's own design decisions. The upstream owns it. Instances do not edit it.**
`git pull` overwrites it. If something here needs a fix, tell the upstream.

An instance records the decisions it makes in its own workspace in `system/decisions.md`.
That file is outside git, so it does not conflict with pull. **The two files use separate numbering series.**

Append-only. Format: `### DR-NNN title (YYYY-MM-DD · active|superseded_by:DR-MMM)`, then
Decision / Context / Rejected alternatives / References. Keep each record short.
Schema source of truth: `../tools/memlib.py` · PRD: `PRD-session-memory.md`.

### DR-001 Instance wiring is derived or set in config, never hard-coded in code (2026-08-24 · active)
Decision: (a) **The transcript directory is a derived value**:
`~/.claude/projects/<root path with every / and _ replaced by ->`.
(b) Tracks, threads, check lists, and source-of-truth pointers live in `system/memory-config.json`.
(c) ROOT is derived from `__file__`. Hooks call `$CLAUDE_PROJECT_DIR/tools/...` so that this derivation is
correct.
(d) Tracks and threads have no built-in fallback. A fallback for a value that is specific to one instance
points at someone else's workspace. A loud empty value costs less than a quiet wrong value.
Context: the original workspace contained 9 absolute paths and 4 project keys. The hooks ended in
`2>/dev/null || true`, so on another machine the worst failure mode was a hook that **looks installed but
silently dies**.
evidence: none
Rejected alternative: making the transcript path a config entry. If a person does not edit it, recall returns
0 results and exits normally.

### DR-002 Structure guards the data border: three valve layers (2026-08-24 · active)
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

### DR-003 Hooks fail safe but do not fail silently (2026-08-24 · active)
Decision: hooks always exit 0 (they never block a session). Instead, the SessionStart failure branch **injects
a warning as valid JSON**, and PreCompact failures are written to `state/.hook-errors.log`.
Context: failing safe is correct in itself. A hook that blocks a session is worse. The problem was that the
shell's `2>/dev/null || true` and Python's `except: pass` stacked up into **double silence**. This produced a
state that looks installed but is dead.
evidence: none
Rejected alternative: printing to stderr on failure. That is noisy even in the normal case where a tool was
deliberately not installed. So the hook is loud only in the case "the hook is defined but the tool is
missing".

### DR-004 Convention documents are split into engine and instance pairs (2026-08-24 · active)
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

### DR-005 Config schema version and upgrade guidance (2026-08-24 · active)
Decision: `memory-config.json` carries `schema_version`. When the engine requires a new field, raise
`memlib.SCHEMA_VERSION` and write in `SCHEMA_CHANGES` **what the user must do**. `doctor` reports a config
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

### DR-006 The state ledger separates a public projection from a local overlay (2026-08-26 · active)
Decision: only allowlisted events go to the public journal. All other events, and events logged with
`--private`, go to the local journal. The view that merges the two is the source of truth.
Context: the tracked journal re-published events that were derived from private data. Concurrent append and
render also had a stale-writer problem and a truncate window.
evidence: none
Safety and migration: on error, the private side fails closed. Writes are bound together by a lock, atomic
publish, and rollback. Only journal provenance is frozen, and legacy threads are separated by hand.
Rejected alternatives: reusing tracks for this purpose, and letting the public side fail open on privacy when
an error occurs. References: `PRD-session-memory.md` §3.2, §9.

### DR-007 Wide tasks run in a fresh bounded worker, and AGENTS is the single instruction source (2026-08-29 · active)
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

### DR-008 Outbound text shows its role and consistency anchors before the body (2026-08-29 · active)
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

### DR-010 A worker run record holds harness identity, tokens, read scope, and write set (2026-09-16 · active)
Decision: `meta.json` v2 records `kit_rev`, `kit_dirty`, `harness_sha256`, `usage`, `read_scope`, and `scope`.
The receipt is unchanged except for one `scope:` line. `--write-prefix` is optional. It only detects and
records after the fact, and it does not roll back. A violation changes the run status only with
`--strict-scope` (live canary on 2026-09-16: both violations came from concurrent writers).
Context: the same model went from 8.3% to 37.2% when only the harness changed (`paper:2609.07925` §2). So to
interpret a run, the receipt must contain the harness identity, but v1 held only prompt and result hashes. If
the lead cannot see where a worker's output came from, it trusts wrong answers (`paper:2609.06702` App. F.2).
A boundary written in natural language is not enforcement (`paper:2609.04170` §3.3). Before implementation,
the design document closed 4 questions from an independent verifier (Codex). After implementation, the first
independent review found 7 defects, and all were fixed: R1, an existing symlink passed. R2, restores with the
same size and mtime, and empty directories. R3, a runtime failure hid a violation. R4, callers were not
connected. R5, the instance HEAD was mislabeled as the kit rev. R6, read_scope syntax. R7, empty fixture
fields. The second review found R8 (hardlink aliases), R9 (creating a missing nested prefix counts as a
violation), and R10 (case correction on case-sensitive volumes). The third review found the rest of R5
(telling the destination baseline apart from the source manifest) and R11 (stamps were not verified). These
were fixed too (31 fixtures. `tools/sync_engine.sh` stamps both the source manifest and the destination
baseline, and verifies the stamps again).
Rejected alternatives: putting external binaries, model snapshots, and environment variables into the hash
(they differ on every run, so runs cannot be compared). Summing usage across events (the totals come out
wrong). Rolling back the write set (detection after the fact does not widen the blast radius). Making the
prefix mandatory (every caller would break. It is a candidate for the next version).
References: the original instance's private workspace papers-2026-09-13-kit (design document
design-fresh-worker-receipt-v2, PROPOSALS, DR-draft, independent reviews REVIEW rounds 1 to 3),
`tools/test_fresh_worker.py` with 31 fixtures, `tools/sync_engine.sh`.

### DR-011 The release gate is a reproduction of a stranger's first install (2026-09-17 · active)
Decision: after changing the engine, run `bash tools/test_fresh_install.sh`. In a temporary clone, setup
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
References: `tools/test_fresh_install.sh`, `CHANGELOG.md` v0.5, the original instance's private workspace
kit-improve-2026-09-17 (2 audits and reviews).

### DR-012 Philosophy: human attention is the most expensive resource, and tokens are the cheapest (2026-09-17 · active)
Decision: the owner set the kit's objective in these words (owner's words, translated): "Treat human cognitive
cost as the most expensive resource and tokens as the cheapest resource, and make the trade-off on that basis.
Make many tasks keep running safely under one endless thread, so that a person deals with only one thing." The
first section of the README is the source of truth for this sentence. Two operating rules that make this trade
safe sit next to it.
(1) **Verdicts arrive only as receipts.** The result of independent verification bought with tokens comes up
only as a bounded receipt (KIT-DR-007, KIT-DR-010). If the full text reaches the person, the trade runs
backwards. (2) **Pass and cause are verified separately.** Gates (install, regression, links) say only whether
something passed. An independent review, not the proposer, examines the hypothesis about the cause of a
failure again (KIT-DR-011).
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
References: the README philosophy section, KIT-DR-007, KIT-DR-010, KIT-DR-011, `tools/test_fresh_install.sh`.

### DR-013 A change to a gate-definition file passes only with one line in the approval ledger (2026-09-18 · active)
Decision: some files decide what the gates catch (language allow rules, the pending list, evidence and
enforcement constants, enforcement, the test matrix, manifest rules, and the GATE_DEFINITION set in
`tools/manifest_build.py`). A diff to these files passes only when a `gate-definition-approval` line in
`system/gate-definition-approvals.md` (tracked, append-only) matches it exactly (decision marker = the
relevant KIT-DR number, files = the sorted file list, sha256 = the diff hash).
`tools/manifest_build.py --issues` runs the check, and pre-commit and CI run the same check.
Context: two measured cases on 2026-09-18. One worker defined a regression but did not add it to the run list,
so it looked "passed". Another worker widened the allow list of its own gate to meet its exit condition. When
the side that did the work also writes its own receipt, a written prohibition does not catch this.
The first draft kept the approval ledger as a swarm file under `_private/`. CI could not see it, so every
gate-definition change failed on the remote. So the ledger moved to a tracked file.
evidence: test:tools/test_manifests.py::test_gate_definition_change_requires_dispatcher_approval
References: KIT-DR-011, KIT-DR-012, the gate-definition class in `system/review-manifest.yaml`,
`.github/workflows/gates.yml`.
Scope addition (2026-09-18, measured during a sync): the check applies only to the kit tree where gate
definitions are written (a tree without `system/memory-config.json`).
An installed instance receives gate definitions through engine sync, and the ledger of the source kit has
already approved that diff. So `--issues` reports `~gate-definition-approval` as not applicable. The first
implementation also required an approval line in instances, and that blocked every engine sync.
evidence: test:tools/test_manifests.py::test_gate_definition_approval_is_not_applicable_in_installed_instance

### DR-014 Trigger store: things that should surface later live in a file, and action tiers are constants (2026-09-19 · active-pilot · re-review 3 cycles later)
Decision: `tools/triggers.py` keeps date triggers in the instance file `_private/triggers/triggers.jsonl`
(`add`, `due`, `hook`, `claim`, `fire`, `sleep`, `list`, `scan`).
`scan` builds triggers with stable ids (`exp-X<n>`, `rereview-DR-<n>`) from the due-date column of the
experiment register and from decision records that have a re-review date, so running it again is idempotent.
Action tiers are constants, not settings. T0 is speaking. T1 is preparing (a draft in the private area, which
can be undone). T2 is going outside (sending, committing, paying, deleting). T2 is never automatic and
surfaces only as a draft plus a one-line request. `privacy` (default private) and `destination` (default
local, no external party) are axes independent of the tier, so "T0 is always allowed" does not become
permission for external notifications. `due` is read-only without `--mark`, and only `hook` records that an
item was shown. At most 5 items show per session, in ascending order of how often each was shown (carry-over),
so the cap does not starve later items. If an item is shown three times without a `fire`, it goes to sleep
automatically for 7 days (the ignore count is recorded).
`claim` takes a lease, and a live lease rejects a second claim. `fire` rejects repeats and records the event
in `history`. Storage is load-modify-save inside a file lock, with replacement through a temporary file. For
the language-dependent words in the source parser (closed status, re-review marker, "N cycles later"), the
engine holds only English defaults, and the instance setting `triggers.sources` overrides them (the kit tree
passes the language gate unchanged). The one SessionStart hook line (the same JSON contract in
`.claude/settings.json` and `.codex/hooks.json`) is a separate rollback bundle, and its unit is the hook line
plus the trigger store.
Context: the owner's instruction on 2026-09-19 was to build calibrated judgment (Jev-style) and proactivity
(Instinct-style) into the kit, and not only for Claude Code. It must also run the same way when moved to
Codex. The design converged over 10 rounds of Claude and Codex debate in the instance (the debate files are in
the debate folder of the source instance, under the 2026-09-19 decide-triggers issue. They are not in the kit
tree).
What Codex changed: `due` became read-only. It added the destination axis, the lease, history, and locking,
and the carry-over ordering. Source parsers became data. A `tools/runtime/` package was rejected (the runtime
registry lives inside `fresh_worker.py`). `decide` (a calibrated-judgment registry, shadow mode, a judgment
ledger) moved to the bundle of the next cycle.
evidence: test:tools/test_triggers.py::test_add_due_fire_and_tier_boundary · test:tools/test_triggers.py::test_hook_limits_and_auto_sleep_after_ignores ·
test:tools/test_triggers.py::test_claim_lease_refuses_second_holder_and_due_stays_read_only · test:tools/test_triggers.py::test_scan_experiments_and_decision_rereviews
Re-review (after 3 cycles): the ratio of fires to automatic sleeps, the number of times the session-start
section actually changed behavior, and whether the two harnesses produced the same output.

### DR-015 Runtime vocabulary derives from one registry entry, and a harness declares the roles it cannot take (2026-09-21 · active-pilot · re-review 3 cycles later)
Decision: `tools/harness.py` is the registry of harness wiring and the source of truth for the runtime
vocabulary. One harness is one entry in `RUNTIMES` (binary, wiring path, mode `checked-in|generated`, the
roles it takes, and **the reason for each role it cannot take**). The role vocabulary uses the same 6 roles as
`hookdiag.ROLE_EVENTS` (injector, recovery, observer, enforcer, side_effect, guard). `CONSUMERS` in
`tools/test_manifests.py` is derived from this table and is no longer a literal. Before this, a third harness
also had to edit the test file. What one entry adds is limited to the **runtime vocabulary**. A new harness
still needs its adapter code, tests, and distribution metadata (review manifest, test matrix, translation
list) added separately (adding opencode worked that way).
opencode is the first generated harness. It has no hook surface, and in v2.0.11 the `instructions` entry in
its config was measured not to load (2026-09-21). So the launcher carries the injector role:
`harness.py open opencode` rebuilds the state file and plants it as the first prompt. A session started
directly receives no state. The 4 slash commands are rendered from the source files in
`.claude/commands/*.md`. The other five roles are not wired, and `status` prints them as gaps. `status` says
"wired" only when the state file and the command directory both exist and the commands match the source (the
same parity function as `check`). Data border: the injection file can contain the local private overlay, so
**unless the file is proven to be outside Git, it holds only public state** (fail-close). The output for this
is `now.py context [--public-only]`, which prints the same body as plain text without the hook JSON envelope.
Verification is a canary round trip, not the presence of wiring (`harness.py verify`). The prompt does not
carry the nonce. In a harness where the injected body is a file, the model can find the same file with grep
and pass without any injection (measured on 2026-09-21: in the first experiment the model called grep, and
that contaminated the experiment). Tools cannot be turned off. `opencode run` in v2.0.11 has no flag that
turns off tools, and with a config that turned tools off, the free tier refused to run (403). So **a run that
used tools does not count as evidence** (inconclusive). Even the same correct answer is not a PASS if there
was a tool call. The nonce sits in the injection file (outside Git) only while the run lasts, because that
file is the channel being measured. When the run ends (including timeouts and exceptions), the file is
rewritten with a body that has no nonce, and the ledger keeps only the verdict.
Context: the owner pointed out on 2026-09-21 that without an "install, then set up, then use" scenario, the
kit cannot claim to be harness-agnostic. The measured starting point: `setup.sh` installed neither `.claude/`
nor `.codex/` (the wiring depended on files checked into the repository), and the word `opencode` appeared 0
times in the whole kit.
Observed constraints: the plugin API of opencode v2.0.11 differs from the public documentation
(`export default {id, setup}`), and the signatures of the event and session hooks are not stable yet. So the
remaining roles that need a plugin were not added in this cycle.
evidence: test:tools/test_harness.py::test_every_runtime_declares_the_roles_it_cannot_take ·
test:tools/test_harness.py::test_state_falls_back_to_public_when_the_path_is_not_outside_git ·
test:tools/test_harness.py::test_canary_prompt_never_carries_the_nonce ·
test:tools/test_harness.py::test_a_tool_using_run_is_never_counted_as_proof ·
test:tools/test_harness.py::test_state_file_holds_no_nonce_after_a_canary_run ·
test:tools/test_harness.py::test_status_does_not_call_a_half_wired_opencode_wired
Model lane addition (2026-09-21, the owner's usage plan): a harness is a lane for one model provider. Claude
runs in Claude Code, GPT runs in Codex, and third-party models (free tiers, Chinese models, and others) run in
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

### DR-016 Memory requirements are separate from implementation design, and instance authority is not inherited (2026-10-08 · active)
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
`tools/test_recall.py`, `tools/test_fresh_worker.py`, `tools/test_memory_map.py`.

DR-016 supplement: before giving a prescription, first look up what has already been done, and ask only about
what is still unknown. The seven rules are operating defaults. They are not claimed as a universal upper limit
of model capability.

KIT-DR-016 verification supplement: Markdown dependency extraction now resolves relative links and inline file
references against the document, preserving PRD-to-design connections. External URLs and out-of-tree paths do
not become local dependencies. The new auth helper and map tests are included in the engine inventory and risk
matrix. Existing critical test requirements are unchanged. Source snapshot delivery, TERM cleanup, and
worker-observed AGENTS provenance have dedicated worker regressions. Gate-definition approval is bound to the
reviewed diff below, not inherited from the upstream instance.

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


### DR-018 Reviewed engine transfer and runtime isolation (2026-10-08 · active)
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
that cannot be obtained is a FAIL. Gate regressions in the development tree are bound to a small synthetic
evidence sample that actually runs. Full distribution regressions and install verification stay separate.
Evidence runs keep their time limit and their blocking verdict, and the reason for a failure is left in the
diagnostic. This supplement removes the duplicated full check inside the focused regression. It does not count
verification on a synthetic sample as distribution verification. The CI evidence step uses the normal command,
which fails when there is a problem. The machine-readable list mode always exits normally, and only callers
that judge the issue count directly use it.

RAN is a record that a test was entered. It is not proof of success. Each top-level gate attempt actually runs
the cited suites under a new run ID. Earlier records, or records that arrive late, are not used as evidence of
success for a new attempt. The internal recursion guard stays.

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

### DR-020 Turn-end checks use the session scope, and release checks run at release time (2026-11-18 · active)
Decision: gate checks have two scopes. The session scope is the link check and the state check. It runs in an installed workspace at the turn-end `check`, at `baseline`, and at `precommit`. The release scope is all four checkers plus a fresh run of every cited test suite. It runs in the kit development tree at `precommit` and `baseline`, and in `gate.py release`. A kit development tree is a tree with no instance config that has `setup.sh` and the config template (the same test the push hook uses). `MOTTORI_GATE_SCOPE=release|session` overrides that test, and an unknown value is read as the stricter release scope. A baseline is compared only against checkers measured in the same scope. `resume` measures nothing and reports the one-line reason of the last block. When the Stop hook is called again in the same turn, the check passes once and keeps the pending marker. `check` runs only when there is an edit marker, a pending marker, or a changed work-tree fingerprint. When a checker produces no result, the block reason names the checker and gives a one-line cause. The three gate hooks write their own failures to `state/.hook-errors.log`.
Context: `decision:KIT-DR-003`, `decision:KIT-DR-011`, `decision:KIT-DR-013`. On a fresh install under a temporary HOME, after a one-line edit to an ignored document, the turn-end check took 83.6 seconds and `setup.sh` took 86.7 seconds (2026-11-18). The turn-end check was running the kit's own release checks on every user turn. After the change the same measurements are 0.4 seconds and 3.0 seconds, and 0.08 seconds on an unchanged tree. In the gate records of the original instance, excluding entries written by tests, about 10 of 395 blocks were caused by the turn that was blocked, and 240 of the 316 blocks that carried a session name repeated the previous block's problems.
evidence: test:tools/test_devtree_gate.py::test_installed_check_runs_no_cited_suite · test:tools/test_devtree_gate.py::test_devtree_precommit_and_release_run_cited_suites · test:tools/test_enforce.py::test_session_check_keeps_release_checkers_in_baseline · test:tools/test_enforce.py::test_resume_reports_pending_reason_without_measuring · test:tools/test_enforce.py::test_H03_H04_stop_hook_active_passes_once_and_keeps_pending
Boundary: CI does not go through the gate. It runs the whole regression suite and the four checkers directly, so release checking did not shrink. The fingerprint misses ignored paths and an overwrite that keeps both size and modification time. Codex has no turn-end hook, so this check runs on Claude Code only.
Rejected alternatives: running release checks asynchronously at turn end (the result arrives in a later turn and no longer shows which turn caused it). Caching checker results (deciding when to drop the cache becomes one more checker).
Reconsider: problems that the session scope missed are repeatedly caught at commit time or in CI.

### DR-021 Session-start injection carries dossiers and the newest decisions first (2026-11-18 · active)
Decision: session-start injection no longer cuts the NOW text in the middle. It splits NOW into sections and fills them in order. The track board, the source pointers, and the state banner are fixed. Then comes the newest decision of each side, then the dossier names, then the remaining decisions, then recent events, newest first. Dossiers that do not fit are replaced by one line with their count and the command that lists them (`python3 tools/now.py threads`). The generated NOW file shortens its dossier list the same way. A long list never makes the injection fail. The public and local sides share the remaining room equally, and room one side leaves unused goes to the other. One event line is cut at 400 bytes, and one line reports how many older lines were left out. The 6,000-byte cap is unchanged. Compaction events stay out of the decisions section and fold into one line in the events section. Journal freshness is measured from the last event that is not a compaction. `log --private` writes to the local journal even when the public journal is corrupt. A trigger's shown count rises at most once per calendar day, and the command the hook prints runs as written. `add` refuses condition kinds that can never fire.
Context: `decision:KIT-DR-006`, `decision:KIT-DR-014`. With a long journal, the middle cut removed the dossier list and the recent decisions, the two things a session needs most after compaction. Compaction events filled the recent-decision slots (68 of 70 lines in the original instance's public journal for November), and they kept journal freshness at "0 days" forever. In a test with 1,000 journal lines on each side, the new injection stays under the cap and keeps both the dossier and the decision sections. A trigger's shown count rose on every hook run, so one day of sessions counted as three ignored showings and put it to sleep.
evidence: test:tools/test_state_runtime.py::test_hook_context_keeps_dossiers_and_newest_decisions_with_long_journals · test:tools/test_state_runtime.py::test_hook_context_names_omitted_dossiers_when_both_lists_are_long · test:tools/test_state_runtime.py::test_hook_context_survives_sixty_long_dossier_names_on_one_side · test:tools/test_state_runtime.py::test_snapshot_drops_compactions_from_decisions_and_dedups_recent · test:tools/test_state_runtime.py::test_private_log_survives_corrupt_public_journal · test:tools/test_triggers.py::test_shown_counts_once_per_calendar_day · test:tools/test_triggers.py::test_hook_fire_instruction_runs_as_written
Boundary: when decisions are many and long, the events section is empty and only the count of omitted lines remains. The memory-index wording check and the recording checks run only in an instance that has those tools, and the wording check is now advice that does not block.
Reconsider: an injection is observed without the dossier list or its omission line, or without the newest decision.

### DR-022 Pre-delivery check: record every hit, and block only with a signal that has shown its hit rate (2026-11-18 · active-pilot · re-judge 2026-12-16)
Decision: `tools/deliver.py` is the second Stop hook. It calls no model. It reads the last answer of the turn and the turn's tool calls and evaluates signals. `unopened` fires when a reading document of at least 1,500 characters written in this turn is delivered without being reopened. The tool names that count as delivering a file are listed in the instance config, `deliver.send_tools`. `reader` fires on a long report at the end of a long working turn. Each signal runs in one of two modes, record only or block. By default `unopened` is recorded and nothing blocks. A blocking signal stops the turn once, and its reason carries only the signals that fired and the owner's original request. Every hit goes to `state/.deliver.jsonl`. A block gets one follow-up record, written at the re-entry of the same turn, that says whether the answer changed (`deliver.py stats`). A re-entry that belongs to another turn or to another hook is not counted. The check's own failure never blocks a turn. Signals that judge wording alone are excluded: a sentence that asks the owner to do something, and a claim that a check passed.
Context: `decision:KIT-DR-003`, `decision:KIT-DR-012`. In the original instance all 6,697 messages the owner typed in five months were read, and 2,243 corrections were counted. Thirteen classes of recurring mistake already had a written rule. Twelve of them recurred more than three times after the rule was written, and for eight the rate per 1,000 messages stayed flat or rose. In a small controlled test, a short rule placed inside the task prompt reduced unrequested additions to 0 of 72 reports (19 with no rule, 2 with a reread step, 1 with a first-time-reader review). So rules go where the work happens, and the turn end gets narrow checks only. Four signals were first run over 8,817 past turns. `unopened` fired on 2.1% of turns and was right in 35 of 40 sampled hits. `reader` fired on 4.6% and was right in 14 of 40. A signal for sentences that hand work to the owner was right in 2 of 40, and a signal for pass claims was right in 0 of 37. Both were removed from the code. Three later candidates went through the same replay. A signal for a document that is named but not sent was right in 12 of 40, a signal for an output never looked at after it was made was right in 14 of 40, and a signal for internal names used without explanation was right in 0 of 40. None was added.
evidence: test:tools/test_deliver.py::test_unopened_document_blocks_once_and_quotes_request · test:tools/test_deliver.py::test_default_only_records · test:tools/test_deliver.py::test_configured_delivery_tools · test:tools/test_deliver.py::test_stats_links_a_reentry_only_to_its_own_blocked_turn · test:tools/test_deliver.py::test_broken_input_never_blocks
Boundary: of 18 real complaints in the original instance that an output was delivered without being looked at, `unopened` caught 1. The others were videos, images, and rendered pages. "Reopened" means that a later tool call in the turn names the file. The check does not read tool results, so a command that only prints the file name also counts. The check runs only in the Claude Code Stop hook. The unrequested-addition numbers come from 12 invented tasks, not from real work.
Rejected alternatives: asking another model to review every answer (cost and delay on every turn, and it did worse than the in-prompt rule in the controlled test). Writing more rule sentences (see the counts above).
Re-judge (2026-12-16): per signal, the number of hits in installed workspaces and the share of blocks after which the answer changed. A signal whose share is under one half goes back to record only. A new signal is not added without a hit rate measured on past conversations.

### DR-023 A worker receipt leads with the verdict, and expected outputs are checked after the run (2026-11-18 · active)
Decision: the receipt cap stays at 4,096 UTF-8 bytes. The header order changes. `verdict:`, the worker's own `unknowns:`, the command that opens the full result `full:`, and `expect:` when `--expect` was given, all come before the body. Line breaks and control characters in header values are escaped, so a value cannot add a header line of its own. When the worker's unknowns are cut, the value starts with the total and the number omitted. A long result keeps its start and ends with a truncation marker and the full-result command. `--expect PATH` checks before the run that the path is inside the workspace, and after the run that the file exists as a non-empty regular file. If any expected file is missing, a run that was successful becomes `expected-output-missing` and exits with code 6. The receipt verdict is then INCONCLUSIVE even if the worker wrote PASS. Terminal status names are defined in one place, `tools/worker_batch.py`. A prompt that contains the text of a denied path is still refused, and the refusal now says to remove the path and state the prohibition in words. The egress-log code that could never run, `--strict-egress`, `ask_codex.sh --resume-root`, and the `codex_root_thread.py` helper are removed.
Context: `decision:KIT-DR-007`, `decision:KIT-DR-010`, `decision:KIT-DR-012`. KIT-DR-010 fixed the receipt as unchanged apart from one `scope:` line. This record amends that sentence. A person who judges from the receipt alone needs the verdict first, and a count of the unknowns even when their text is cut. A run in which the worker wrote PASS and left no file could not be told apart from a good run by its receipt.
evidence: test:tools/test_fresh_worker.py::test_receipt_byte_cap_keeps_the_start_and_puts_verdict_unknowns_and_location_first · test:tools/test_fresh_worker.py::test_receipt_header_values_cannot_forge_lines_and_count_cut_unknowns · test:tools/test_fresh_worker.py::test_expect_missing_or_empty_output_downgrades_a_pass · test:tools/test_fresh_worker.py::test_expect_outside_root_is_refused_before_a_run · test:tools/test_egress.py::test_prohibition_naming_a_private_path_is_refused_with_wording_advice · test:tools/test_worker_batch.py::test_status_vocabulary_is_shared_by_worker_and_ledger
Boundary: the denied-path check reads prompt text. It is not a sandbox on what the worker reads. `--expect` checks that a non-empty file exists after the run. It does not check that the content is right or that this run wrote it. A run without `--expect` behaves as before.
Reconsider: a judgment made from a receipt alone is overturned when the full result is opened.

### DR-024 Korean editions live under `ko/`, and an index knows the pairs (2026-11-18 · active)
Decision: documents in the root tree are English. A Korean edition lives under `ko/` at the same relative path with the same file name (what was `README.ko.md` is `ko/README.md`). The pair table `ko/INDEX.md` is generated (`python3 tools/i18n_stamp.py index`), and the check fails when the table and the files disagree. A link inside a Korean document goes to the Korean edition when one exists. Which side of a pair is the source stays as its stamp says. "English is the main edition" means that English sits in the root tree and is what agents read automatically. Hangul is allowed in files under `ko/`, in Korean values of the string catalog, and in test data about Korean input.
Context: `decision:KIT-DR-004`, `decision:KIT-DR-016`, `decision:KIT-DR-019`. Owner instruction, 2026-11-18: make English the main edition, collect the Korean files in one place, and let an index file say which file pairs with which. Forty-two pairs sat next to their English files, links from Korean lens documents led to the English index, and Korean command files in the command folder were registered by the runtime as separate commands.
evidence: test:tools/test_language.py::test_pair_index_fixture · test:tools/test_language.py::test_korean_link_to_english_fixture · test:tools/test_language.py::test_stamp_bind_and_source_drift_fixture
Boundary: no runtime reads the Korean rule files automatically. That was also true before the move. An installed workspace may keep old `*.ko.md` copies, because `git pull` does not remove ignored instance files.
Reconsider: a third language arrives, or Korean users actually ask for Korean rules to be loaded automatically.

### DR-025 Measure the fixed context of every session, and cap the default recall output (2026-11-18 · active)
Decision: `python3 tools/context_budget.py` measures what enters every session, in bytes and approximate tokens: instruction files (`CLAUDE.md`, the files it imports, and `AGENTS.md`), the session-start state injection, the trigger hook output, hook output added to each prompt, and the runtime memory index. It writes no file. `doctor` warns, and never fails, when an item is over the warning line in the config. The default output of `recall.py find` shows the source and a short excerpt of each match and stays within 4,000 bytes, notices included. When it stops early it prints how many matches remain and names `--full`. `--full` prints what the command printed before, and `--full` and `--around` are not capped. A Claude session is searched only when the working folder it records is this workspace or a declared alias, so another project is not searched even when both folders map to the same transcript folder name. With zero matches, the command states the scope it searched.
Context: `decision:KIT-DR-002`, `decision:KIT-DR-012`. On a fresh install the fixed context is about 6.7 KB, most of it the seven rules. In the original instance it was 39.7 KB, of which 29.1 KB was the memory index. The rules document said that only seven rules are always active, while most of the always-loaded instructions sat in an index nobody measured. Splitting that index into per-task sub-indexes reduced it to 6.6 KB. Recall output for one common word was 17.8 KB and is 3.6 KB under the new default.
evidence: test:tools/test_context_budget.py::test_defaults_do_not_warn_on_small_install · test:tools/test_context_budget.py::test_stale_state_is_estimated_without_writing_any_file · test:tools/test_recall.py::test_default_output_is_capped_and_says_how_to_see_more · test:tools/test_recall.py::test_full_keeps_previous_output_shape · test:tools/test_recall.py::test_missing_transcript_dir_never_borrows_another_project · test:tools/test_recall.py::test_claude_records_from_another_folder_with_the_same_store_name_are_excluded · test:tools/test_recall.py::test_default_output_stays_under_the_cap_with_a_long_query
Boundary: a transcript file that records no working folder at all is still searched, and the number of such files is reported. What the runtime injects by itself (system prompt, tool definitions, skill list) and the user's global settings are not measured. Token counts are estimates and were not compared with a real tokenizer. The warning lines are starting values, not measurements.
Reconsider: a warning line fires all the time in real use, or never fires.

### DR-026 Tool output follows the instance language, and that language is saved in the config (2026-11-18 · active)
Decision: tool output that a person or a model reads comes from the string catalog. That covers the generated `state/NOW.md`, the session-start injection, log, refusal and error messages, and help text. The language is chosen from `MOTTORI_LANG`, then `instance.lang` in the config, then the shell locale. `setup.sh` writes the install language to `instance.lang`. Words that are written to files and read back by code (the compaction marker in the journal, section headings of NOW, the retroactive-entry marker, status values in the ledger) are written in the current language, and every reader accepts both languages. Korean output is byte-identical to what it was before the move, except five fallback messages inside hook configuration files, which are now English only. English strings use no em dash and no arrow.
Context: `decision:KIT-DR-024`. An English install still showed a Korean state view and Korean command output. The language came only from an environment variable and the locale, so a workspace installed in Korean could run in another language under a shell or a scheduler with an English locale. Once generated state files and journal markers follow the language, that language has to be fixed per workspace. The output of 208 Korean commands was captured before and after the move and compared byte for byte, and 56 round trips were checked in which state written in one language is read in the other.
evidence: test:tools/test_state_runtime.py::test_english_instance_writes_english_state_and_injection · test:tools/test_state_runtime.py::test_state_tokens_are_read_in_both_languages · test:tools/test_i18n.py::test_configured_language_beats_locale · test:tools/test_rec.py::test_status_values_are_read_in_either_language · test:tools/test_evidencecheck.py::test_issue_ids_do_not_depend_on_language
Boundary: a workspace installed earlier has no `instance.lang` and keeps following the locale until one line is added (see CHANGELOG). The recording and transcription tools, the memory-map tool, and the description column of the enforcement matrix still contain Korean and are listed in `system/language-pending.txt`. Parser labels that read Korean documents or transcripts stay Korean.
Reconsider: an old journal or ledger is misread in a workspace that changed its language.

### DR-027 Leaving a session and closing a job have a procedure (2026-11-18 · active)
Decision: (1) When work will continue in another session or runtime, the leaving session writes a handoff note to a file (the handoff section of `system/rituals.md`, `/handoff` on Claude Code). The note has five parts, and text that exists only in the conversation goes into the note as text, not as a description. One journal line makes the path of the note visible in the state the next session is given. (2) Each job folder has one page at its top. When the job ends, the page says "done" and lists what to keep and what may be deleted. Temporary copies are made in one place only, and whoever dispatched the work deletes them. Nothing that cannot be rebuilt is deleted automatically (`system/WORKING-WITH-AI.md`). (3) `doctor` measures free disk space, the size of `.git`, the size of stale scratch files, and the number of job folders without a guide page, and it only warns. (4) Triggers get `add --sticky`. A notice the owner must see does not fall asleep because of how often it was shown, and it comes first in the list. (5) The Codex hook canary runs with the user config loaded.
Context: `decision:KIT-DR-012`, `decision:KIT-DR-014`, `decision:KIT-DR-021`. All 53 sessions of the original instance were read. Of the new sessions, 42% were opened beside a session that was still running, and two or more sessions were used on 56 of 153 days. "One thread" is the aim, and the practice was several. In 9 of the 19 sessions that continued earlier work, the owner pasted more than 800 characters, and in 8 of those the pasted text was an answer from another session or runtime. Dossiers and state carry what was decided. Text that lived only in a conversation had no way to travel. In the same instance the disk reached 98% full, and 93 of 125 job folders had no file saying what the job was or whether it was finished. Six notices for the owner fell asleep after being shown three times, and none was handled. The Codex canary reported a working hook as failed, because Codex records project trust in the user config and the canary ignored that config. In the same call, the model received the value the hook injected when the user config was loaded, and did not receive it when the config was ignored.
evidence: test:tools/test_triggers.py::test_sticky_triggers_never_auto_sleep_and_lead_the_hook · test:tools/test_hook_runtime.py::test_canary_children_pin_instance_and_block_ambient_tools · test:tools/test_doctor_json.py::test_growth_lowered_lines_warn_each_item_and_never_fail · test:tools/test_doctor_json.py::test_growth_check_writes_nothing
Boundary: the handoff is a procedure and a command document. The engine does not enforce it. Codex has no slash commands, so the same procedure is requested in words. The growth check only warns and deletes nothing. The canary switches off connectors and external features one by one, and it uses the rest of the user's settings as they are.
Reconsider: long pastes continue in sessions that take over work even when a handoff note was written. The growth check warns all the time, or never.
