# Evidence-contract enforcement matrix

This table separates what code decides under the evidence contract from what a person reviews.

| Contract | Status | Enforcement point | Verification evidence |
|---|---|---|---|
| Allowed marker syntax | ENFORCED | `tools/evidencecheck.py` | `test:tools/test_evidencecheck.py::test_malformed_marker_fails` |
| Local existence of decisions, tests, and runs | ENFORCED | `tools/evidencecheck.py` | `test:tools/test_evidencecheck.py::test_missing_local_id_fails` |
| Required DR, CHANGELOG, and matrix locations | ENFORCED | `tools/evidencecheck.py` | `test:tools/test_evidencecheck.py::test_required_locations_without_markers_fail` |
| Gate and pre-commit consumption of issue sets | ENFORCED | `tools/gate.py`, `tools/precommit-hook.sh` | `test:tools/test_evidencecheck.py::test_gate_consumes_evidencecheck_issues_end_to_end` |
| Whether a marker supports its claim | INDEPENDENT REVIEW | Outside code judgment | An independent reviewer compares source and claim |
