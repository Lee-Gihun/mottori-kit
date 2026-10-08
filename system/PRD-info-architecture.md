<!-- source: PRD-info-architecture.ko.md sha256:50bbd8c749cf8823dc235f0d6f9df6ba4053c5ffce3165acb019fafc96a341b6 source-of-truth: ko -->
# PRD — Information trust and correction

> **Status: current engine requirements, revised 2026-10-08.** Adopting a requirement is separate from completing its implementation and verification.
> The Korean `.ko.md` is the source of truth. This English `.md` is a translation bound to that source's content hash.
> Distinguish unmet requirements and the latest observations in `design-memory-runtime.md#verification`.
> Role: what to trust, how to handle conflicts and corrections, and how to judge success.
> Session behavior belongs in `PRD-session-memory.ko.md`; implementation and verification connections belong in `design-memory-runtime.md`.

<a id="purpose"></a>
## 1. Purpose and the cost of failure

The agent carries forward current intent and evidence to complete the work without making the user explain the past again or correct the same error repeatedly. Storage volume, search counts, and rule compliance are intermediate observations serving that purpose.

Failures to prevent include proposing an already settled choice without a reason, making a claim without reading available evidence, hardening inference into fact, and recording a correction without changing the next action. Accurate records can still fail during retrieval, interpretation, or synthesis. Verify actual responses and actions as well as the records.

The user does not take on routine information maintenance. The agent records, retrieves, and updates information, briefly surfacing only the unknowns that require the user's decision. Repeatedly asking for information already available also counts as a cost.

<a id="authority"></a>
## 2. Claim origin, current validity, and scope

Do not give one file type authority over every kind of claim.

| What needs to be known | Evidence to check first | What to check alongside it |
|---|---|---|
| Who said what | Original message, conversation log, or audio | Speaker, time, and the distinction between original, transcription, and summary |
| What was decided | Explicit user decision, confirmed decision record, and decision event | Whether the statement was exploratory and whether it was later changed or withdrawn |
| What is happening now | The current canonical record and execution evidence for that scope, plus merged NOW | Freshness of the actual source and availability of local state |
| Why a conclusion was reached | The thread's dossier and linked source material and judgments | Reasons for rejection, remaining unknowns, and conditions on the conclusion |
| Whether something ran or was verified | The result, log, or observation for that execution | Target version, method, observation time, and unobserved scope |

The user's statements are the origin for the user's decisions, preferences, plans, and corrections. Agent documents do not replace them. Being closest to the original strengthens attribution; it does not make an old statement override a newer decision.

Do not silently resolve conflicting records by replacing them with whichever file is newest. Link explicit changes and supersession where they resolve the conflict. Otherwise expose the conflict and the evidence needed to judge it. When the current user instruction is clear, do not request approval again for an already delegated decision.

<a id="record-lifecycle"></a>
## 3. Creating, correcting, superseding, and preserving records

Preserve originals while allowing interpretations to be corrected. Record what a correction supersedes. Do not erase a withdrawal in a way that lets the old, incorrect direction return. Existing frozen areas remain reference-only.

The fact ledger holds one claim per record. It needs content, source location, derivation path, speaker, date, topic, status, and supersession relationship. Mark any missing origin. Epistemic status, such as confirmed, reported, inferred, or unresolved, differs from decision validity, such as decided, superseded, or withdrawn. Keep that distinction even before changing the storage format.

Record corrections, new source facts, decisions, and state changes in the turn when they occur. Session end must not be the only recording point. This does not require rebuilding every stable document as atomic records. Choose what to extract actively according to its volatility and effect on future decisions.

`Decided` prevents repeated proposals without new evidence. A user request to reconsider, changed conditions, or contradictory evidence can justify a new judgment while preserving the earlier reasons. Reconsideration itself is not a violation.

<a id="retrieval"></a>
## 4. Retrieval and uncertainty

| Activity | Required behavior |
|---|---|
| General explanation or casual conversation | Do not automatically load unrelated personal records |
| A specific claim about a record | Check the origin or a record that supports the claim |
| An action or strategy proposal | Check current constraints and what has already been done or decided |
| Writing or updating a document | Check the evidence and its current meaning, and look for conflicts |

Do not ask again for facts explicit in the current conversation. Retrieve what the records can establish first. Ask the user only when a remaining unknown would change the result.

Search must support keywords, topics, status, people, and time ranges, with a full-text path that still works when tags are missing. The audit chain must connect a claim to its derivatives and original location. A small hotset signals the existence of important decisions, withdrawals, current facts, and unresolved matters; it does not replace the complete material. The hotset needs a capacity limit and demotion conditions.

No search result means the item was not found within the searched scope. Distinguish that from an absent original, unavailable access, parser omission, and a query mismatch. If evidence is missing, stale, or conflicting, state what is unknown instead of filling it with inference presented as fact. Honest uncertainty is not a reason to stop other useful work.

<a id="boundaries"></a>
## 5. Data boundaries and delivery

Derived records, summaries, and visualizations inherit the source material's privacy, frozen-area, and external-transfer restrictions. Git tracking, permission to transmit to a model, and permission to send to another person are separate judgments. Writing content to a public path does not authorize publication.

Keep personal examples and original execution material private. Public documents contain general contracts and verification suitable for sharing. Export generalized engine contracts to the kit without transferring an instance's personal history or delegated authority. Specific frozen-area, send, and commit authority follows `AGENTS.md` and valid explicit delegation.

When the user must read a result or act on it, check delivery on the actual device and surface they use. Creating a file or writing a link alone does not establish readable delivery.

<a id="acceptance"></a>
## 6. Verify user outcomes

Retain the existing target of zero wrong answers across 20 questions, but **do not pass a system that says it does not know the answer to all 20 answerable questions.** In a fresh-session trial with the necessary source material available, report these separately:

1. Answerable questions: counts of evidence-backed correct answers, wrong answers, and unnecessary expressions of uncertainty.
2. Questions without source material or a current answer: counts of appropriate uncertainty and unsupported assertions.
3. Corrections, withdrawals, and temporal conflicts: whether an earlier claim was repeated and whether current validity was recovered.
4. Real work: whether the response incorporated previous conclusions and constraints to help the user's next judgment or action.

Retain the existing targets of no unwarranted repeated proposals, tracing an arbitrary claim to its origin within 30 seconds, a correction possible in one sentence, no recurrence of the same error, and conversation without perceptible delay. Measure them with the evaluation period, cases, denominator, and observer specified. User experience or satisfaction that the agent has not measured remains UNKNOWN.

Fewer corrections or no response may reflect fewer opportunities or less effort to observe, so report those conditions and do not count silence as success. Do not extend praise for one aspect into success for the whole task.

A functioning tool, retrieved evidence, delivery into the session, changed behavior, and an improved real outcome are different claims. Do not reuse a PASS at one stage as a PASS at a later stage.

Alongside a causal hypothesis, a correction record should identify where the failure actually occurred, who found it, and whether it recurred on the next execution. The existing I-1 through I-5 and A-1 through A-5 classifications may remain for historical comparison, but filling in a classification is not recovery. Do not introduce a separate user input form.

<a id="unmet"></a>
## 7. Unmet requirements and reconsideration

Verify the fresh-session 20-question trial, 30-second provenance audit, correction non-recurrence, and conversational delay on the current version of each instance. Automatic hotset loading, correction telemetry across all types, and enforced append-only recording also remain UNKNOWN without end-to-end evidence. Installation success or observations from another instance do not pass these checks. Keep unmet and unverified requirements, and use the verification process in `design-memory-runtime.md#verification`.

A new storage format, embeddings, graphs, or automatic rule promotion requires an actual failure and a comparative trial. More documents or more uses are not sufficient reasons to adopt them. Permit exhaustive reading when the task requires an exhaustive review, while distinguishing what was read from what was understood and verified.

## Revisions and historical references

Use this repository's Git history to recover earlier text and its section and line references. Record reasons for engine contract changes in `system/kit-decisions.md`, and instance decisions in that instance's `system/decisions.md`.

Old section 4.1 maps to [claim authority](#authority); 4.2 to [record lifecycle](#record-lifecycle); 4.3 and 10 to [verification](#acceptance); 4.4 to [uncertainty](#retrieval); 4.5 to [user effort](#purpose); 6.1 to [records](#record-lifecycle); 6.2 through 6.4 to [retrieval](#retrieval); 6.5 to [recording time](#record-lifecycle); 6.6 to [correction observations](#acceptance); 6.7 to the session PRD; and 6.8 through 6.9 to [reconsideration](#unmet). Update live consumers to these fixed anchors without rewriting historical decisions or debate records.

**This revision:** separates accuracy from uncertainty to close an acceptance loophole, permits reconsideration with new evidence, and clarifies "ask first" as "retrieve first, then ask only about remaining unknowns." Replacing this document alone changes no storage schema, authority, or frozen-area boundary.
