# Decision records (DR)

**This file contains decisions for this workspace only.** Design decisions for the kit itself are in
`system/specs/kit-decisions.md`, which is owned upstream and overwritten by `git pull`. Git ignores `instance/`, so a
pull never touches this file.

Append only. Format: `### DR-NNN Title (YYYY-MM-DD · active|superseded_by:DR-MMM)`, followed by decision,
context, rejected alternatives, and references. Keep each record short. A decision row in the journal points to
it with `→ dr:NNN`. To schedule a re-review, end the parenthesis with an optional ` · re-review YYYY-MM-DD`, as in
`### DR-001 Example (2026-01-05 · active · re-review 2026-02-01)`; `python3 tools/triggers.py scan` turns it
into a re-review trigger. Heading reader: `../tools/triggers.py`; PRD: `../system/specs/PRD-session-memory.md`.

*(Empty for now. Add the first decision here when it is made.)*
