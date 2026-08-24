export const meta = {
  name: 'memory-gardener',
  description: 'Delegated second-pass over the memory system: detect rot, verify dossiers against transcripts, propose (never execute) fixes',
  phases: [{ title: 'Garden', detail: 'one auditor over state/, memory/, dossiers' }],
}

// PRD: system/PRD-session-memory.md §3.5. Report-only by contract: the gardener
// proposes, the session + Gihun adjudicate. This mirrors the radar's
// flag->adjudicate split, which kept 2 false alarms from becoming false fixes.
const ROOT = require('path').resolve(__dirname, '..')   // DR-023

const REPORT_SCHEMA = {
  type: 'object',
  required: ['report_path', 'findings', 'verified_claims', 'headline'],
  properties: {
    report_path: { type: 'string' },
    headline: { type: 'string', description: 'one sentence: the most important thing found' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['kind', 'evidence', 'proposal', 'risk'],
        properties: {
          kind: { type: 'string', description: 'rot|drift|duplicate|contradiction|unverified|hygiene' },
          evidence: { type: 'string' },
          proposal: { type: 'string' },
          risk: { type: 'string', description: 'what breaks if the proposal is wrong' },
        },
      },
    },
    verified_claims: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim', 'source_checked', 'verdict'],
        properties: {
          claim: { type: 'string' },
          source_checked: { type: 'string' },
          verdict: { type: 'string', description: 'confirmed|contradicted|unfindable' },
        },
      },
    },
  },
}

phase('Garden')
const result = await agent(`You are the memory gardener for the workspace at ${ROOT}.
Contract: you PROPOSE, you never edit. Every proposal needs evidence and a risk statement.
Full spec: ${ROOT}/system/PRD-session-memory.md §3.5.

DO, IN ORDER:

1. Run: python3 ${ROOT}/tools/now.py check
   Interpret each warning: real rot, false positive, or already-known. Do not repeat the raw
   output; judge it.

2. Read ${ROOT}/state/NOW.md and the current ${ROOT}/state/journal-*.md.
   Look for: state assertions in NOW that no journal event supports; journal events whose
   track 정본 was never updated; switch/decision lines with dangling refs (dr:NNN that does
   not exist in ${ROOT}/system/decisions.md).

3. Verify dossiers against the episodic record (THE core duty — a distillation that is not
   checked against raw is how memory rots politely):
   - Read ${ROOT}/research/soi-dossier.md and ${ROOT}/jobs/relocation-dossier.md.
   - Pick the 3 most load-bearing factual claims in EACH (dates, numbers, who-said-what).
   - For each claim run a targeted query:
       python3 ${ROOT}/tools/recall.py find "<keyword>" --max 2 --around 1
     and/or check the referenced repo file. Record verdict: confirmed / contradicted /
     unfindable. If contradicted, quote the transcript slice as evidence.

4. Memory hygiene: list files in ${MEMDIR}.
   Flag: type:project files that look like state snapshots (should be pointers),
   index lines in MEMORY.md that assert volatile facts, memories that duplicate what a
   repo file already owns. Propose supersede/archive moves — do not execute.

5. Compute today's date yourself (bash: date +%F) and write the report to
   ${ROOT}/state/gardener-<today>.md. NEVER overwrite an existing report from a previous
   day. Korean, with sections:
   ## 판정 요약 (3줄) / ## 검출 (kind별, 증거+제안+위험) / ## 서류철 검증 (표) /
   ## 판정 대기 목록 (구조·정책·개인 사실·불가침 관련만; 기계적·저위험 위생은 '자동 집행 권고'로 별도 분류).
   Keep it under 120 lines. Plain prose, no em-dashes.

Return the structured result.`, {
  label: 'gardener',
  schema: REPORT_SCHEMA,
})

return {
  headline: result?.headline,
  findings: (result?.findings || []).length,
  verified: (result?.verified_claims || []).map(v => `${v.verdict}: ${v.claim.slice(0, 60)}`),
  report: result?.report_path,
}
