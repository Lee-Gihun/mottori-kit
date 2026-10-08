Korean: `README.ko.md`

# Cross-runtime debate

Use another runtime to challenge a decision's assumptions and evidence. The owner should receive the
resolved recommendation or the concrete unresolved decision, rather than relay messages between tools.
A debate can improve a proposal; agreement does not independently validate it.

This README is shared engine policy. Prompts, case records, and run outputs belong to the instance.
The default ignore rules track this README and its translation, not the surrounding discussion files.
Ignoring a file prevents ordinary Git inclusion; it does not authorize sending its contents to a model.

## Prepare the exchange

1. State the decision, the strongest alternative, and what would change the recommendation.
2. Verify the actual available paths. Select the smallest set of current contracts and evidence needed to
   answer the question; do not attach an entire session, dossier collection, or personal corpus by default.
3. Check the instance data boundary before dispatch. A prompt, a path, and a tool read can each disclose
   information. Use only permitted material. Where necessary, pose a generic technical question without
   private source text, or mark the review unavailable.
4. Copy [the round template](../../templates/debate-round.md) to an ignored instance prompt such as
   `system/debate/_p_review.md`. The tracked template stays blank. Keep the discussion record in a protected
   instance location such as `_private/debate/` and retain references to the worker run records.
5. Define who owns each write. A review does not authorize editing code, policy, or source evidence.

The reusable template requires a strategic-assumption challenge, an actually worked perspective, evidence
for material findings, a response to the previous round, and an honest account of unread or unavailable
material. "No material change" and a rejected criticism are legitimate outcomes.

## Dispatch and runtime boundaries

The default is a fresh, ephemeral worker. Put the prompt in a file so shell metacharacters remain data.
From the instance root, choose the intended runtime:

```bash
python3 tools/fresh_worker.py --runtime claude system/debate/_p_review.md
python3 tools/fresh_worker.py --runtime codex system/debate/_p_review.md
```

The example path must be replaced with the prompt file actually prepared. Run the selected command, not
both merely to increase the number of reviewers. `bash tools/ask_codex.sh PROMPT_FILE` is the compatibility
entry for a fresh Codex call. An explicitly requested resume is a different operation; its failure must not
silently fall back to a fresh session.

The [worker contract](../PRD-session-memory.md#105-fresh-bounded-worker-kit-dr-007) owns exact capability,
receipt, and persistence requirements:

- Claude has read-only `Read`, `Glob`, and `Grep` tools. It can propose edits but cannot apply them or run
  shell checks. Do not assign it a required write or shell command and then infer completion from its answer.
- Codex has a workspace-write sandbox. Review-only instructions are task scope, not an operating-system
  guarantee of read-only access. Use the available scope checks and inspect actual effects.
- Workers do not inherit the caller's conversation or rely on hooks for current state. Name `AGENTS.md` and
  the required canonical sources explicitly. If NOW is relevant, specify both public and local surfaces
  subject to the data boundary; an inaccessible local overlay is unavailable, not absent.
- Both adapters disable connectors, web, command network access, plugins, and fan-out. These restrictions
  do not make otherwise prohibited model input permissible.
- The runner retains the prompt, event stream, final result, metadata, and content hashes under
  `_private/work/runs/`. The caller receives a bounded receipt. Read the result and relevant evidence before
  claiming what the reviewer saw, executed, or established.

Keep the execution handle until completion or a recorded interruption. The worker owns no scheduler and a
background process is not itself a notification mechanism. Use the calling runtime's supported wait or
completion mechanism, then inspect the output. Do not promise a later follow-up without a real scheduled path.

## Preserve the discussion

The caller appends each completed round to the instance discussion record or links its preserved result.
Do not edit another participant's original response. A summary must be labeled as a summary. Corrections
and counterarguments are new entries, with the actual runtime and model recorded when available.

For an execution or state claim, retain a checkable artifact, command result, or content hash with its scope.
A proposed check is not a performed check. A paper's claim, a local observation, and an impression have
separate evidential roles. State the limits of each instead of converting reviewer confidence into proof.

Before disputing a claim, quote the relevant permitted statement and answer it directly. Describe concrete
consequences and the smallest correction. A different model family can provide a different failure surface;
it does not guarantee independent evidence. Same-family review is not independent corroboration.

## End the exchange

A first response is advice, not a completed exchange. Address its strongest argument and obtain a response
to that challenge. Do not manufacture objections solely to produce another round.

- Continue when a material judgment changed and the next round has a concrete unresolved question or new evidence.
- Record convergence when the exchange leaves no decision-relevant disagreement to resolve.
- Stop when no new relevant evidence can be obtained; distinguish unresolved disagreement from convergence.
- If a limit or data boundary blocks review, record blocked or inconclusive, with the missing observation.

Round counts do not measure quality. Preserve rejected corrections as well as accepted ones. Where the
remaining difference requires the owner, present one prepared decision and what would change with the answer.

## Apply and observe

After convergence or the owner's decision, the authorized writer applies the agreed change. Existing
implementation budgets and protected areas still apply. Recheck the current base and final change, run
relevant validation, and record what was actually observed. Sending, committing, and pushing retain their
existing authorization requirements; a debate grants none.

Promote an adopted policy into the instance decision record or the kit decision record as appropriate.
Keep private cases and local pilot schedules out of shared engine documents. Record later execution or owner
feedback against the original decision. Passing checks and agreeing on a design are separate from observing
that it improves the work.
