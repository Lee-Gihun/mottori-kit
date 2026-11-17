# mottori-kit architecture review

Review date: 2026-09-17
Scope: all 96 tracked files that `git ls-files` returned in the current integrated tree, plus the instance
paths that those files read or create.
Method: we compared the tracked file set, static path references, imports and subprocess calls, hook
registrations, and test registrations. The manifest path match is checked against the real
`git ls-files -z` output (`tools/test_manifests.py:47-70`, `tools/test_manifests.py:103-110`).

## 1. Conclusion

The state ledger, the gate, and the fresh worker are deep modules. A deep module hides a lot of work behind
a small interface. Behind the `now.py` CLI sit public/private routing, locking, atomic projection, and
rollback (`tools/now.py:445-598`). The gate (the edit and commit check) consumes only the stable issue
sets of several checkers (`tools/gate.py:119-188`). The worker runs in isolation, judges the write scope,
and then returns a receipt of at most 4,096 bytes
(`tools/fresh_worker.py:711-744`, `tools/fresh_worker.py:889-914`).

The integrated tree splits review and evidence into new modules. The review manifest regenerates the set
of tracked text files and keeps the human classification (`tools/manifest_build.py:32-111`). The matrix
check compares each rule origin with its fixture (`tools/test_manifests.py:139-201`). evidencecheck
checks marker syntax, local IDs, and required placement. It does not block external `paper:` and
`experiment:` markers. It leaves them as REVIEW instead (`tools/evidencecheck.py:74-90`,
`tools/evidencecheck.py:157-206`). paper-to-kit separates the proposal-only workflow from the runtime
adapters and checks that the adapters match the exact canonical bytes
(`system/skills/paper-to-kit.md:3-9`, `tools/test_skill_parity.py:62-96`).

Four structural risks remain.

1. The sync targets are declared twice: in the Python `SYNC_FILES` and in a shell copy list
   (`tools/fresh_worker.py:45`, `tools/sync_engine.sh:13-18`).
2. The doctor ledger check does not read the `rec.py check` exit code. It can read a crash or an output
   drift as 0 issues (`tools/doctor.py:650-659`).
3. The release runs all 19 Python suites. The doctor owns its own list of 15 suites. The two lists differ
   (`tools/doctor.py:583-622`, `tools/test_fresh_install.sh:91-95`).
4. The memory map now has a generation fixture, but the structure description itself is still a constant
   (`tools/build_memory_map.py:56-99`, `tools/test_coherence.py:73-92`).

There is one structural orphan: `tools/eval_recall.py`. Outside its own CLI, the README, the doctor, and
the regression suites do not call it (`tools/eval_recall.py:19-37`, `tools/doctor.py:583-622`). The
runtime convention files, `state/.gitkeep`, and `LICENSE` have no code callers. We do not count them as
orphans, because each has a consumer: the runtime, the repository shape, and legal metadata.

## 2. Module map

| module | narrow interface | hidden responsibility | main consumer | verification and remaining gaps |
|---|---|---|---|---|
| state ledger | `now.py log/render/check` | visibility routing, journal append, two NOW files, lock/rollback | hooks, gate, operator | A transaction fixture exists (`tools/test_state_runtime.py:533-1054`). |
| recall | `recall.py sessions/find` | Claude/Codex source discovery, cwd isolation, authored filter, ranking | AGENTS, slash command, doctor | Codex cwd and injection fixtures exist (`tools/test_recall.py:77-109`). The Claude parser and ranking ties have no separate fixture. |
| personal ledger | `rec.py new/find/check/audit` | fact schema, origin audit, hotset, snapshot | AGENTS, coherence, doctor | new-find-check-audit is verified (`tools/test_rec.py:27-46`). The snapshot ring and mid-run failure are not verified. |
| hooks | runtime JSON and installed pre-commit | SessionStart, PreCompact, gate lifecycle | Claude, Codex, Git | Runtime and installer fixtures are separate (`tools/test_hook_runtime.py:16-235`, `tools/test_install_hooks.py:39-99`). |
| gate | `baseline/status/check/precommit` | checker issue set, baseline, lock/token, extracted index | hooks, pre-commit | Checker crashes and the index tree are tested (`tools/test_install_checks.py:181-226`, `tools/test_hook_runtime.py:235-291`). |
| worker | `fresh_worker.py <runtime> <prompt>` | fresh runtime, run record, usage, write scope, receipt | operator, ask_codex | Worktree and scope fixtures exist (`tools/test_fresh_worker.py:454-717`). |
| receipts | `receipts.py list/show/cost` | aggregation of private run meta and bounded rendering | operator, doctor | list/show/cost/threshold fixtures exist (`tools/test_receipts.py:91-203`). |
| doctor | single PASS/FAIL/WARN/SKIP report | runtime, wiring, hooks, tools, valves, regressions | setup, operator | It registers 37 automatic checks and 4 manual ones (`tools/doctor.py:979-1027`). The ledger verdict can fail open. |
| setup/release | `setup.sh`, `test_fresh_install.sh` | instance seed, migration, hooks, doctor, full regressions, rerun | new instance operator | It runs the full regressions and a setup rerun (`tools/test_fresh_install.sh:91-104`). |
| review manifest | `manifest_build.py`, `test_manifests.py` | inventory of 96 text files, classification kept, rule/source coverage | reviewer, doctor | It checks missing/ghost files and matrix origins (`tools/test_manifests.py:73-110`, `tools/test_manifests.py:194-202`). |
| evidence contract | `evidencecheck.py --issues` | marker syntax, local resolver, required placement, REVIEW | gate, pre-commit, reviewer | It separates local missing items from external REVIEW items (`tools/test_evidencecheck.py:69-124`). |
| paper workflow | canonical workflow and generated adapters | cards, crosscheck, proposal-only boundary, human gate | Claude/Codex adapter | A schema cross fixture and exact-byte parity exist (`tools/test_skill_parity.py:32-96`). |

## 3. Coupling and authority


```text
event -> now.py -> memlib visibility -> public/private journal -> two NOW -> SessionStart
transcripts -> recall.py -> cwd/authored filters -> bounded slice
facts -> rec.py -> check/audit -> hotset/snapshots

edit -> gate -> linkcheck + now check + evidencecheck -> issue-set delta -> pass/block
prompt -> fresh_worker -> private run record -> receipts.py -> bounded receipt / doctor metric

git ls-files -> manifest_build -> review-manifest -> test_manifests
DR/CHANGELOG/matrix -> evidencecheck -> blocking issues + nonblocking REVIEW
paper list -> canonical workflow -> cards/crosscheck/proposals -> human judgment
```

Authority is split by the kind of claim.

| claim | source of truth | derived copy | evidence |
|---|---|---|---|
| current state | public NOW + local overlay | SessionStart context | `AGENTS.md:26-31`, `tools/now.py:648-696` |
| events | public/private monthly journal | NOW projection | `system/PRD-session-memory.md:85-99`, `tools/now.py:289-359` |
| personal facts | private fact files | hotset/snapshot | `tools/rec.py:23-33`, `tools/rec.py:99-130` |
| kit decisions | `system/kit-decisions.md` | README/CHANGELOG summary | `system/kit-decisions.md:1-11` |
| evidence marker syntax | `system/evidence-schema.md` | checker implementation and workflow markers | `system/evidence-schema.md:7-30`, `tools/evidencecheck.py:12-23` |
| review target set | text files from `git ls-files` | `system/review-manifest.yaml` | `tools/manifest_build.py:32-51`, `tools/test_manifests.py:47-70` |
| workflow meaning | `system/skills/paper-to-kit.md` | Claude/Codex adapter | `tools/skill_adapters.py:17-63` |
| worker run | private `meta.json` and stream/result | stdout receipt | `tools/fresh_worker.py:707-744` |

The public/private boundary has four layers: the default-deny Git allowlist (`.gitignore:16-57`), the
journal public-track allowlist (`tools/memlib.py:310-337`), the transcript cwd filter
(`tools/recall.py:62-101`), and the worker private run record (`tools/fresh_worker.py:197-205`). Run
outputs such as `REPORT.md` are not in the engine allowlist (`.gitignore:16-33`).

## 4. Full inventory of tracked files

The 96 rows below are exactly the same set as the current `git ls-files` output. The machine source of
truth for kind, owner, and consumer is `system/review-manifest.yaml`. The test compares missing and ghost
files in both directions (`tools/test_manifests.py:73-110`). Convention files with no direct path
reference also list their consumer.

| tracked file | kind / owner | consumer | current file evidence |
|---|---|---|---|
| `.claude/commands/dossier.md` | tool / kit | human, Claude | (`.claude/commands/dossier.md:1`) |
| `.claude/commands/garden.md` | tool / kit | human, Claude | (`.claude/commands/garden.md:1`) |
| `.claude/commands/now.md` | tool / kit | human, Claude | (`.claude/commands/now.md:1`) |
| `.claude/commands/paper-to-kit.md` | tool / kit | human, Claude | (`.claude/commands/paper-to-kit.md:1`) |
| `.claude/commands/recall.md` | tool / kit | human, Claude | (`.claude/commands/recall.md:1`) |
| `.claude/settings.json` | hook / kit | Claude, tool | (`.claude/settings.json:1`) |
| `.codex/hooks.json` | hook / kit | Codex, tool | (`.codex/hooks.json:1`) |
| `.gitignore` | rule / kit | human, Git/tool | (`.gitignore:1`) |
| `AGENTS.md` | rule / kit | human, Claude, Codex | (`AGENTS.md:1`) |
| `CHANGELOG.md` | evidence / kit | human, Claude, Codex | (`CHANGELOG.md:1`) |
| `CHECKLIST.md` | rule / kit | human, agents | (`CHECKLIST.md:1`) |
| `CLAUDE.md` | rule / kit | Claude | (`CLAUDE.md:1`) |
| `LICENSE` | evidence / kit | human/legal tool | (`LICENSE:1`) |
| `README.md` | evidence / kit | human, agents | (`README.md:1`) |
| `SETUP.md` | rule / kit | human, agents | (`SETUP.md:1`) |
| `setup.sh` | tool / kit | human, setup tests | (`setup.sh:1`) |
| `state/.gitkeep` | generated / kit | Git checkout | (`.gitignore:53-55`) |
| `system/PRD-info-architecture.md` | rule / kit | human, agents | (`system/PRD-info-architecture.md:1`) |
| `system/PRD-session-memory.md` | rule / kit | human, agents | (`system/PRD-session-memory.md:1`) |
| `system/WORKING-WITH-AI.md` | rule / kit | human, agents | (`system/WORKING-WITH-AI.md:1`) |
| `system/debate/README.md` | rule / kit | human, agents | (`system/debate/README.md:1`) |
| `system/deep-pass.md` | rule / kit | human, agents | (`system/deep-pass.md:1`) |
| `system/enforcement-matrix.md` | evidence / kit | human, agents, tool | (`system/enforcement-matrix.md:1`) |
| `system/enforcement-matrix.yaml` | generated / kit | human, agents, tool | (`system/enforcement-matrix.yaml:1`) |
| `system/evidence-schema.md` | rule / kit | human, agents, tool | (`system/evidence-schema.md:1`) |
| `system/kit-decisions.md` | rule / kit | human, agents | (`system/kit-decisions.md:1`) |
| `system/lenses/README.md` | rule / kit | human, agents | (`system/lenses/README.md:1`) |
| `system/lenses/ergodic.md` | rule / kit | human, agents | (`system/lenses/ergodic.md:1`) |
| `system/lenses/feedback-loop.md` | rule / kit | human, agents | (`system/lenses/feedback-loop.md:1`) |
| `system/lenses/fence.md` | rule / kit | human, agents | (`system/lenses/fence.md:1`) |
| `system/lenses/feynman.md` | rule / kit | human, agents | (`system/lenses/feynman.md:1`) |
| `system/lenses/incentive.md` | rule / kit | human, agents | (`system/lenses/incentive.md:1`) |
| `system/lenses/inversion.md` | rule / kit | human, agents | (`system/lenses/inversion.md:1`) |
| `system/lenses/isomorphism.md` | rule / kit | human, agents | (`system/lenses/isomorphism.md:1`) |
| `system/lenses/jensen.md` | rule / kit | human, agents | (`system/lenses/jensen.md:1`) |
| `system/lenses/ledger.md` | rule / kit | human, agents | (`system/lenses/ledger.md:1`) |
| `system/lenses/limits.md` | rule / kit | human, agents | (`system/lenses/limits.md:1`) |
| `system/lenses/marginal.md` | rule / kit | human, agents | (`system/lenses/marginal.md:1`) |
| `system/lenses/mirror.md` | rule / kit | human, agents | (`system/lenses/mirror.md:1`) |
| `system/lenses/silence.md` | rule / kit | human, agents | (`system/lenses/silence.md:1`) |
| `system/person-ledger.md` | rule / kit | human, agents | (`system/person-ledger.md:1`) |
| `system/review-manifest.yaml` | generated / kit | human, agents, tool | (`system/review-manifest.yaml:1`) |
| `system/reviews/architecture.md` | evidence / kit | human, agents | (`system/reviews/architecture.md:1`) |
| `system/rituals.md` | rule / kit | human, agents | (`system/rituals.md:1`) |
| `system/skills/paper-to-kit.md` | rule / kit | human, agents, tool | (`system/skills/paper-to-kit.md:1`) |
| `templates/decisions.md` | template / kit | setup, human | (`templates/decisions.md:1`) |
| `templates/instance-rules.md` | template / kit | setup, human | (`templates/instance-rules.md:1`) |
| `templates/memory-config.json` | template / kit | setup, memlib | (`templates/memory-config.json:1`) |
| `templates/rituals.local.md` | template / kit | setup, human | (`templates/rituals.local.md:1`) |
| `tools/ask_codex.sh` | tool / kit | human, Codex | (`tools/ask_codex.sh:1`) |
| `tools/build_memory_map.py` | tool / kit | human | (`tools/build_memory_map.py:1`) |
| codex_root_thread.py (later removed with `ask_codex.sh --resume-root`) | tool / kit | ask_codex | - |
| `tools/coherence.py` | tool / kit | doctor, human | (`tools/coherence.py:1`) |
| `tools/diarize.py` | tool / kit | transcribe, human | (`tools/diarize.py:1`) |
| `tools/doctor.py` | tool / kit | setup, human | (`tools/doctor.py:1`) |
| `tools/eval_recall.py` | tool / kit | manual CLI only | (`tools/eval_recall.py:1`) |
| `tools/evidencecheck.py` | tool / kit | gate, human | (`tools/evidencecheck.py:1`) |
| `tools/fresh_worker.py` | tool / kit | human, ask_codex | (`tools/fresh_worker.py:1`) |
| `tools/gate.py` | tool / kit | hooks, pre-commit | (`tools/gate.py:1`) |
| `tools/hook_canary.py` | tool / kit | doctor, human | (`tools/hook_canary.py:1`) |
| `tools/hookdiag.py` | tool / kit | doctor, canary | (`tools/hookdiag.py:1`) |
| `tools/i18n.py` | tool / kit | tools | (`tools/i18n.py:1`) |
| `tools/install_hooks.sh` | tool / kit | setup, human | (`tools/install_hooks.sh:1`) |
| `tools/linkcheck.py` | tool / kit | gate, doctor | (`tools/linkcheck.py:1`) |
| `tools/manifest_build.py` | tool / kit | reviewer | (`tools/manifest_build.py:1`) |
| `tools/memlib.py` | tool / kit | state/recall tools | (`tools/memlib.py:1`) |
| `tools/now.py` | tool / kit | hooks, human | (`tools/now.py:1`) |
| `tools/portrait.py` | tool / kit | doctor, human | (`tools/portrait.py:1`) |
| `tools/precommit-hook.sh` | hook / kit | Git | (`tools/precommit-hook.sh:1`) |
| `tools/rec.py` | tool / kit | human, coherence | (`tools/rec.py:1`) |
| `tools/recall.py` | tool / kit | human, agents | (`tools/recall.py:1`) |
| `tools/receipts.py` | tool / kit | human, doctor | (`tools/receipts.py:1`) |
| `tools/skill_adapters.py` | tool / kit | Claude/Codex packaging | (`tools/skill_adapters.py:1`) |
| `tools/sync_engine.sh` | tool / kit | human | (`tools/sync_engine.sh:1`) |
| `tools/test_coherence.py` | tool / kit | regression | (`tools/test_coherence.py:1`) |
| `tools/test_doctor_json.py` | tool / kit | regression | (`tools/test_doctor_json.py:1`) |
| `tools/test_evidencecheck.py` | tool / kit | regression | (`tools/test_evidencecheck.py:1`) |
| `tools/test_fresh_install.sh` | tool / kit | release gate | (`tools/test_fresh_install.sh:1`) |
| `tools/test_fresh_worker.py` | tool / kit | regression | (`tools/test_fresh_worker.py:1`) |
| `tools/test_hook_runtime.py` | tool / kit | regression | (`tools/test_hook_runtime.py:1`) |
| `tools/test_hookdiag.py` | tool / kit | regression | (`tools/test_hookdiag.py:1`) |
| `tools/test_i18n.py` | tool / kit | regression | (`tools/test_i18n.py:1`) |
| `tools/test_install_checks.py` | tool / kit | regression | (`tools/test_install_checks.py:1`) |
| `tools/test_install_hooks.py` | tool / kit | regression | (`tools/test_install_hooks.py:1`) |
| `tools/test_manifests.py` | tool / kit | regression | (`tools/test_manifests.py:1`) |
| `tools/test_memcheck.py` | tool / kit | regression | (`tools/test_memcheck.py:1`) |
| `tools/test_memlib_journal.py` | tool / kit | regression | (`tools/test_memlib_journal.py:1`) |
| `tools/test_portability.py` | tool / kit | regression | (`tools/test_portability.py:1`) |
| `tools/test_rec.py` | tool / kit | regression | (`tools/test_rec.py:1`) |
| `tools/test_recall.py` | tool / kit | regression | (`tools/test_recall.py:1`) |
| `tools/test_receipts.py` | tool / kit | regression | (`tools/test_receipts.py:1`) |
| `tools/test_setup_migration.py` | tool / kit | regression | (`tools/test_setup_migration.py:1`) |
| `tools/test_skill_parity.py` | tool / kit | regression | (`tools/test_skill_parity.py:1`) |
| `tools/test_state_runtime.py` | tool / kit | regression | (`tools/test_state_runtime.py:1`) |
| `tools/transcribe.py` | tool / kit | human | (`tools/transcribe.py:1`) |
| `tools/wf_gardener.js` | tool / kit | garden command | (`tools/wf_gardener.js:1`) |

## 5. Duplication, contradiction, and test gaps

| area | current fact | verdict |
|---|---|---|
| sync inventory | The source hash list and the real copy loop are separate (`tools/fresh_worker.py:45`, `tools/sync_engine.sh:13-18`). | It needs a single authority and a temp-instance rollback fixture. |
| doctor duplication | `c_tools_run` runs linkcheck/coherence, and the dedicated checks run them again (`tools/doctor.py:524-580`). | This is a candidate for merging the "can it run" check and the result verdict into one structured probe. |
| release suite list | The doctor lists 15 suites by hand. fresh-install runs all 19 through a glob (`tools/doctor.py:589-622`, `tools/test_fresh_install.sh:91-95`). | To stop the lists from drifting, the release needs one owner. |
| schema authority | memlib owns the shared state schema. rec, gardener, and the memory map define some paths and structures on their own (`tools/memlib.py:2-6`, `tools/rec.py:21-33`, `tools/wf_gardener.js:10-17`, `tools/build_memory_map.py:56-99`). | Either narrow the scope of "the only schema" to state/config, or share a real registry. |
| evidence resolver | The three local kinds are checked for existence. The two external kinds are REVIEW (`tools/evidencecheck.py:74-90`, `tools/evidencecheck.py:177-186`). | It does not report REVIEW as PASS, so it matches the current boundary. Whether the source fits the claim is still a human judgment. |
| personal ledger | A new/find/check/audit fixture now exists (`tools/test_rec.py:27-70`). | Dedicated fixtures for snapshot rotation, atomic failure, and malformed frontmatter are still missing. |
| recall | Fixtures for cwd isolation and the authored filter now exist (`tools/test_recall.py:77-109`). | Determinism tests for the Claude transcript parser and ranking ties are still missing. |
| memory map | A generation fixture now exists (`tools/test_coherence.py:73-92`). | No test checks that the hardcoded store/flow is derived from a real registry. |
| gardener | It depends on an external agent JSON schema (`tools/wf_gardener.js:51-101`). | It has no deterministic local fixture. |

The order of priority for deletion and merging is as follows. P0: make the sync inventory a single list,
and make the doctor ledger check fail closed. P1: remove the duplicate runs in the doctor, and merge the
release suite owner. P2: connect or delete `eval_recall.py`. `now.py`, `gate.py`, and `fresh_worker.py`
really hide complexity that the caller would otherwise need to know. They are not deletion candidates.

## 6. Comparison with the philosophy

The objective in the README is to treat human attention as expensive and tokens as cheap, and to send up
verified receipts instead of transcripts (`README.md:57-72`). The structure implements this with the
worker receipt (`tools/fresh_worker.py:711-744`), the state projection (`tools/now.py:550-700`), manifest
coverage (`tools/test_manifests.py:103-110`), and the checker issue set (`tools/gate.py:119-170`).

A short verdict that hides its cause or scope betrays this philosophy. Three places do this now: the
possible false PASS in the doctor ledger check, the double list in sync, and the different suite lists in
the doctor and the release. The goal of the next improvement is not to reduce the file count. The goal is
to gather each authority at one seam, and to accept as a receipt only a result that has passed through
that interface.
