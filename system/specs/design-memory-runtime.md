# Design: memory, execution, and improvement

Current design, 2026-10-08. This is a kit design document, authored in English. It connects requirements to
implementation and observations; it does not grant execution authority or certify an installed instance.

<a id="purpose"></a>
## What this structure should save

A person returning to a task should not have to explain prior decisions, reconstruct rejected alternatives,
or correct the same mistake again. The goal is lower effort to resume, judge, and act while completing the
work. Memory volume, rule counts, and automatic changes are intermediate observations.

Always injecting the full history raises context cost; keeping only the current request loses earlier
decisions. This design combines a small current-state view with source records and dossiers opened when
needed. It keeps essential boundaries always active and loads other rules conditionally. Compare those
choices on real resumed tasks instead of treating retrieval counts or a universal rule limit as proof.

Improvement also needs both judgment and execution evidence. A report alone does not establish a correction;
an adoption quota encourages unnecessary changes. Distinguish idea value from implementation defects, allow
bounded repair, and revisit the design when observed user burden increases.

This Markdown document, including its diagrams, is the primary explanation. Use [retrieval](#retrieval) to
follow a resumed task, [improvement](#improvement) to understand a blocked change, and
[verification](#verification) to distinguish requirements from observations. HTML is a supporting view.

<a id="ownership"></a>
## 1. Ownership and entry points

A product requirements document (PRD) defines what must hold. This design explains how and why. Decision
records preserve changes and rejected alternatives; code and actual runs provide implementation evidence.

```mermaid
flowchart TD
    info["Information PRD: authority and correction"] --> design["Design: structure and reasons"]
    session["Session PRD: continuity and improvement"] --> design
    decisions["Decision records: changes and alternatives"] --> design
    design --> code["Code, commands, and tests"]
    code --> evidence["Observed results and remaining unknowns"]
    evidence -->|"Compare with requirements"| design
```

| Concern | Source of truth | Consumer |
|---|---|---|
| Claim authority, correction, and data boundaries | [Information PRD](PRD-info-architecture.md) and instance rules | Records, documents, answers |
| Continuity and improvement requirements | [Session PRD](PRD-session-memory.md) | This design and instance observations |
| State/configuration schema and visibility | [config.py](../../tools/lib/config.py), [journal.py](../../tools/lib/journal.py) and instance configuration | NOW rendering and hook context |
| Fact schema and provenance | [facts.py](../../tools/facts.py) | Search, hotset, audit chain |
| Transcript scope and speaker roles | [recall.py](../../tools/recall.py) | Search slices and retrieval evaluation |
| Worker execution, receipt, and provenance | [fresh_worker.py](../../tools/fresh_worker.py), PRD section 10.5 | Private run record and bounded receipt |
| Optional improvement loop | Explicit instance delegation and adapter contract | Judging proposals, building and reviewing each change, saving its patch |
| Engine updates | Upstream export review, then `git pull` in the instance | Engine provenance, without instance data or authority |

Each module owns its schema. `config.py` is not the sole schema for every domain. A derived view reads those
sources instead of introducing another manually maintained registry. Requirements, code, and observations are
different forms of evidence.

The kit includes a manual gardener, described [below](#manual-garden). The improvement loop (`tools/loop/`, with
its health check and schedule) ships off and is described in [its own document](../loop/README.md); this document
does not turn it on. An instance that turns it on, or adds an adapter of its own, must document its actual run,
stop, status, schedule, authorization, and protected paths. An
upstream instance's delegation, cadence, switch, or successful run never transfers automatically.

<a id="state"></a>
## 2. Recording and restoring state

The journal records events. NOW is the derived current-state view. A dossier preserves a task's reasoning,
decisions, rejected options, open questions, and next move.

```mermaid
flowchart TD
    event["Decision, correction, or state change"] --> scope{"Safe to share?"}
    scope -->|"Yes"| public["Public journal"]
    scope -->|"No or uncertain"| private["Private journal"]
    public --> pnow["Public NOW"]
    private --> lnow["Local NOW"]
    pnow --> merged["Bounded merged context"]
    lnow --> merged
    merged --> session["Session start, resume, or compaction recovery"]
    session --> depth["Read relevant dossier and originals"]
```

Preserve these requirements:

- Events outside the public-track allowlist and events marked `--private` stay local. Missing, corrupt, or
  incompatible configuration fails closed to local storage, with a warning that does not disclose raw data.
  Callers must mark private-derived events private even when their track is public.
- A later allowlist expansion does not publish old events retroactively. Preserve the legacy cutoff and its
  public set. Removing previously tracked material is a separate operation.
- Local dossier names and paths stay in the private thread registry. Invalid local entries produce a degraded
  status without suppressing valid public state. Private writes must not alter public journal or NOW bytes.
- Serialize append, fsync, render, temporary-file fsync, and atomic replace under the repository lock. Readers
  see a complete old or new snapshot. Check the configuration inside the lock before each append and each
  render. A failed journal write is undone (truncated to its old size, or a new file removed). A page carries
  one `state-content-sha256` marker: the hash of its inputs (journal bytes, each canonical's update line, the
  policy, the dossier marks and the two engine source files) and of the page itself, so a hand edit or a page
  from an older engine reads as stale and is rendered again. Do not silently discard malformed events.
- Live and staged validation use content identity rather than mtime. Distinguish source freshness from generation
  time. Live calendar-date freshness and elapsed-time age answer different questions.
- Public NOW and SessionStart additional context are each at most **6,000 UTF-8 bytes**. Keep the public/local
  minimum allocations and truncation indication. Unavailable or broken local state must be visible while
  valid public context remains usable.

Code: [now.py](../../tools/now.py), [journal.py](../../tools/lib/journal.py),
[config.py](../../tools/lib/config.py). Regression entry points:
[test_state_runtime.py](../../tools/tests/test_state_runtime.py),
[test_memlib_journal.py](../../tools/tests/test_memlib_journal.py).
Existing tests do not prove current dispatcher delivery or useful recovery in a real task.

<a id="retrieval"></a>
## 3. Retrieval and current meaning

Start from the claim: facts use facts.py, exact past statements use recall, reasoning uses a dossier, and current
progress uses NOW plus execution evidence. Do not rank all files on one universal authority ladder.

```mermaid
flowchart TD
    request["Current request"] --> lookup["Retrieve relevant source and state"]
    records["Original statements, journals, and dossiers"] --> lookup
    lookup --> meaning["Recover attribution, current validity, and reasons"]
    meaning --> action["Use in the answer, judgment, or action"]
    action --> outcome["Observe task outcome and user effort"]
    outcome -->|"New decision or correction"| records
    lookup -->|"Missing, conflicting, or unreadable"| unknown["State the limit and continue useful work"]
```

Keep source runtime, project, timestamp, and speaker role. Tool output, injected context, copied child-agent
history, and compaction summaries are not original user statements. Distinguish no match, absent source,
parser failure, filtering, ranking, and expression mismatch. A known-item failure requires independent reason
to believe the source item exists.

The hotset and dossier point to evidence and current decisions; they do not replace originals. Preserve
capacity, demotion, and supersession rules. Adding a storage format requires migration and regression checks.
Evaluate preservation, known-item retrieval, expression variation, current meaning, and behavioral use
separately. Compare absent context, the current method, and a candidate on the same real task and reading
budget. More hits alone do not establish a better answer.

Code: [facts.py](../../tools/facts.py), [recall.py](../../tools/recall.py),
[eval_recall.py](../../tools/dev/eval_recall.py).
Regression entry points: [test_facts.py](../../tools/tests/test_facts.py),
[test_recall.py](../../tools/tests/test_recall.py).
An optional thread-reentry adapter is not required to read a registered dossier or verify that its reasoning
appears in the resumed task.

<a id="runtime"></a>
## 4. Runtime delivery and effect

A configured hook or successful direct command establishes command validity, not dispatcher delivery.
Use positive and disabled-negative canaries in the actual runtime to verify model-visible injection. A model
finding the same state through another tool does not prove hook delivery. Recheck applicability after a model,
binary, or launch configuration changes.

Recovery observers expose errors and preserve useful work. Boundaries for disclosure and unauthorized
mutation fail closed. Do not give all hooks one blanket exit policy. Trace the combination of exception
handling and shell fallbacks so failures do not disappear.

Inspect runtime support with [hookdiag.py](../../tools/lib/hookdiag.py) and verify actual delivery with
[hook_canary.py](../../tools/hook_canary.py). Direct sessions, wrapper sessions, and different runtimes may have
different support. Installation alone is not a positive canary.

The Claude canary requires empty tool and MCP inventories and zero model tool calls.
It permits only explicitly named runtime built-ins whose startup metadata identifies
both path and source as bundled. Configured, malformed, duplicate, or unknown plugins
fail the check. This distinguishes bundled runtime metadata from user plugin loading;
it does not claim the runtime contains no internal components.
Runtime-managed user configuration is outside the repository write-set check. An ephemeral CLI session may
still persist a project trust entry. When running disposable verification, record that side effect and remove
only its own temporary project entry afterward, preserving unrelated user settings. This is a verification
responsibility; the worker does not automatically edit user configuration.

<a id="worker"></a>
## 5. Fresh work and bounded return

The exact normative byte and capability contract remains in
[session PRD section 10.5](PRD-session-memory.md#105-fresh-bounded-worker-kit-dr-007). This design does not
relax it. The dispatcher provides an exact prompt snapshot and declared read/write scope. Complete evidence
stays in a private run record; the bounded receipt points back to it.

For work that requires source material, distinguish the list of required paths from the contents actually
delivered. Bind the effective input snapshot to each required material's content hash. If a runtime cannot
read a file, supply its required contents in the input. Missing, unreadable, or truncated required material
must not silently count as a complete review. Delivery evidence and evidence of using the material in a
judgment are separate. This is a requirement; installation-specific verification remains necessary.

Preserve meta v2 provenance: `kit_rev` is the git HEAD of the running copy and `kit_rev_source` names its
source. Missing usage is null. The READ_SCOPE and UNREAD lines of a result are self-report
that a person reads in result.txt; they are not copied into metadata. Report write-set prefixes, changes,
violations, and status. The write set is measured only in a worktree that only the worker writes: a diff of a
shared workspace with concurrent writers cannot identify the cause, so a shared-workspace run records
`unchecked (shared workspace)` and does not scan the tree. A violation is reported only and never changes run
status; post-hoc detection is not prevention.

Before deleting a worktree, preserve new or changed ignored outputs inside declared write prefixes.
Safe regular files go to the private run's `untracked/` directory and binary patch, with their
relative paths and SHA-256 values in worktree metadata. Read-material copies are excluded.
Hidden, credential-shaped, cache, linked, or otherwise unsafe ignored outputs are not exported.
An incomplete or failed capture returns exit 5 and preserves the worktree at `preserved_path`
for recovery. A termination signal during capture also leaves that worktree available, and
an interrupt while the runtime is still running captures the worker's output before the worktree is
removed; if that capture fails, the worktree and its path are kept. Read
`capture_status`, `capture_skipped`, and `capture_error` before retrying;
a successful model process is not sufficient evidence of durable output delivery.

For an adapter that applies emitted edits, accept only **complete EDIT blocks in the final response**. Never
silently collect or combine earlier assistant segments. A missing or incomplete final artifact is delivery
failure, even if the stream contains a draft. A remaining bounded repair attempt requests the complete final
result. Read-only Claude can emit a proposal; only an authorized dispatcher can apply it.

Provider credential environment variables are separated for each runtime; an explicitly saved Claude
token is used only by the Claude adapter.
`READ_SCOPE:` and `UNREAD:` are optional self-reports, not proof of filesystem confinement. Missing
declarations remain null. Material hashes and write-set checks answer different questions.

Code: [fresh_worker.py](../../tools/fresh_worker.py), [receipts.py](../../tools/receipts.py). Regression entry points:
[test_fresh_worker.py](../../tools/tests/test_fresh_worker.py), [test_receipts.py](../../tools/tests/test_receipts.py).

<a id="improvement"></a>
## 6. Optional improvement adapters

This section is a requirement for the improvement loop and for any adapter an instance adds. The loop ships off:
no source sends and nothing is scheduled until the owner turns each on. The loop stops at a reviewed patch: it
never writes into the owner's files, and the owner's agent applies a saved patch in a session. Installation or
PRD adoption never grants automatic mutation, commit, push, or external-send authority.

```mermaid
stateDiagram-v2
    state "Judge picks proposals" as Judge
    state "Refused" as Refused
    state "Fixed specification and first build" as Build
    state "Tests and independent review" as Verify
    state "One feedback repair" as Repair
    state "Abandoned" as Abandoned
    state "Pending: the next run continues it" as Pending
    state "Saved as a patch with its report" as Saved
    state "Evaluated in use or still unknown" as Observe
    [*] --> Judge
    Judge --> Refused: Value, scope, or evidence insufficient
    Judge --> Build: Proposal picked (now a change)
    Build --> Verify: Complete final artifact
    Build --> Repair: First build failed
    Verify --> Repair: Repairable first failure
    Verify --> Pending: No runtime could be called, or the token ceiling
    Verify --> Refused: Refused at a stage, with the reason
    Repair --> Verify: Check again
    Repair --> Abandoned: Build failed again
    Verify --> Abandoned: Second attempt fails
    Verify --> Saved: Exact patch passes
    Saved --> Observe: Applied by the owner's agent
```

Keep a refused proposal, a build defect, a pending change, an abandoned change,
a saved patch, and the observed effect separate. Zero adoption can be correct. It is different from every selected
implementation failing. Measure stages and causes; do not impose an adoption quota.

An implementation has at most **two attempts in total: one initial attempt and one feedback repair** under
the same specification and write-set. Persist attempt history and the abandoned state across restarts. Do not
increase the budget dynamically or reset it by renaming the same change. A changed goal or scope needs
separate judgment and retains the earlier failure evidence.

Bind every attempt to specification, input, starting commit, patch hash, validation, and review evidence.
Check the starting commit and the change in isolation; preserve existing failures and require no new failures.
Independent review must validate the exact patch, status, exit code, and contract. Never bypass hooks or
weaken review to obtain a pass.

Adapters must separately specify schedule and collection window, stop conditions, protected paths, rollback
unit, and follow-up observation. Read-only status and help commands must not heal, trigger work, notify, or
mutate records. The health check itself needs observable failure. Do not retry abandoned changes forever.

An applied change is not demonstrated user benefit. Tests, reviewer agreement, and commit existence do not
establish HELPED. Without real-task follow-up, effect remains UNKNOWN. Observe avoided errors, new friction,
regressions, undos, and user intervention before deciding to keep, change, or undo.

<a id="manual-garden"></a>
### Manual memory audit

The `/garden` command ([its steps](../skills/garden/SKILL.md)) is report-only. The session's own agent follows
its steps in any runtime and produces proposals with evidence and risk; it does not edit or commit. The
calling session handles subsequent judgment under the instance's valid authority.
The `/garden` command follows [the memory section of rituals](../rituals.md#memory): the session asks the owner
about the kinds that section names and executes the rest only within the scope the instance explicitly
delegated; without delegation it stops at proposals ([improvement contract](PRD-session-memory.md#improvement)).
The report goes to `_private/state/gardener-<date>.md`. It does not inherit an
optional automatic adapter's authority. Confirm runner availability in the actual installation.

<a id="map"></a>
## 7. Markdown design and a supporting status view

Keep design and decision context in this Markdown document and the PRDs. Put Mermaid diagrams beside the
explanation they support and link to stable requirement anchors. Understanding the system must not require
opening a separate HTML artifact. The generated HTML view is a design view for skimming the structure: it
carries no observation time or live counts, so rerunning it gives the same file unless the design changed. It
links back to these documents and source evidence.

Use the existing [build_memory_map.py](../../tools/dev/build_memory_map.py) generator. It takes no options and writes
only the public map; there is no local status view. Its output file is a generated artifact and need not exist
in a fresh clone.

```sh
python3 tools/dev/build_memory_map.py          # output: state/memory-map.html
```

The public map contains general structure only. Summaries drawn from private source material, cycle results,
or personal state do not go into it. A renderer producing a file does not authorize its disclosure.
Distinguish a hardcoded explanation from a measured result. Use PASS, FAIL, UNKNOWN, or STALE with time,
version, source, and scope; missing data or a parser failure is UNKNOWN.

The first screen should let a reader identify the next personal action, the blocked stage, and the evidence
being relied on within 60 seconds. Verify actual desktop and narrow-screen layout, links, and clipping. A
fixture that generates valid HTML is not that reader test.

<a id="verification"></a>
## 8. Verification without transferred claims

Requirements stay active when unimplemented or unmeasured. Do not lower them to match current code. The
following table maps checks; it is not a test report. No originating instance's result is adopted here.

| Requirement | Claim | Status | Source | Test or observation | Last check |
|---|---|---|---|---|---|
| `#state` | Privacy, atomicity, and bounded context | Instance verification required | now/journal | State and journal regressions; real runtime recovery | Not recorded here |
| `#retrieval` | Correct source and usable retrieval | Instance verification required | recall/facts | Known-item, paraphrase, time-conflict, and resumed-task cases | Not recorded here |
| `#runtime` | Dispatcher delivery | Instance verification required | hookdiag/hook_canary | Positive and disabled-negative runtime canaries | Not recorded here |
| `#worker` | Byte/capability contract and provenance | Instance verification required | fresh_worker/receipts | Worker and receipt regressions, boundary canary | Not recorded here |
| `#worker` | Required material, effective input snapshot, and content-hash binding | Instance verification required | Task input construction and fresh_worker | Missing, unreadable, truncated, and actually delivered material | Not recorded here |
| `#improvement` | Bounded repair and authorized application | Optional adapter, not included | Instance implementation | Repair-to-pass, reject/no-op, exhaustion, restart, stale-base cases | Not applicable until installed |
| `#map` | No private material in the public map, and readable delivery | Instance verification required | build_memory_map | Privacy fixtures and actual desktop/narrow-screen inspection | Not recorded here |
| PRD acceptance | Lower resume, judgment, and action cost | UNKNOWN without real-task evidence | User tasks and correction evidence | 20-question trial, 30-second provenance trace, recurrence and burden; [session PRD success criteria](PRD-session-memory.md#acceptance) | Not recorded here |

An instance can record a dated six-field snapshot in its existing local run or report; a new parallel status
registry is unnecessary. Keep retrieval, storage, injection, behavior, and effect observations independent.
Code regressions cannot close the PRDs' real-user requirements.

<a id="migration"></a>
## 9. Document and language compatibility

The two PRD paths remain entry points, and their English text is normative. Preserve fixed anchors and the exact
section 10.5 byte/capability link.

Use fixed anchors in live references. Interpret historical section numbers against the Git version that
recorded them; do not rewrite old decisions. Engine policy belongs in kit decisions, while instance authority
and operational observations belong to that instance. Generalization requires semantic review as well as
name and path filtering.

The two PRDs and this design are kit-owned contracts, excluded from automatic source-instance document
export (`NOT_SYNCED`). A change to a shared requirement needs review in both repositories; copying a source
instance's text does not transfer its authority, schedule, or observations. Keep the shared section 10.5 body
and compatibility anchors equivalent. Engine code can still follow reviewed selective export, with manual
gardener references mapped to this document's existing `#manual-garden` entry.
