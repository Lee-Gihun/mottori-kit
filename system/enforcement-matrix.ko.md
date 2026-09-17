# 근거 계약 집행 매트릭스

이 표는 근거 계약에서 코드가 판정하는 범위와 사람이 검토하는 범위를 분리한다.

| 계약 | 상태 | 집행 위치 | 검증 근거 |
|---|---|---|---|
| 허용 표지 문법 | ENFORCED | `tools/evidencecheck.py` | `test:tools/test_evidencecheck.py::test_malformed_marker_fails` |
| decision, test, run 로컬 존재 | ENFORCED | `tools/evidencecheck.py` | `test:tools/test_evidencecheck.py::test_missing_local_id_fails` |
| DR, CHANGELOG, 매트릭스 필수 위치 | ENFORCED | `tools/evidencecheck.py` | `test:tools/test_evidencecheck.py::test_required_locations_without_markers_fail` |
| gate와 pre-commit의 이슈 집합 소비 | ENFORCED | `tools/gate.py`, `tools/precommit-hook.sh` | `test:tools/test_evidencecheck.py::test_gate_consumes_evidencecheck_issues_end_to_end` |
| 표지가 해당 주장에 적합한가 | INDEPENDENT REVIEW | 코드 판정 밖 | 독립 검토자가 원문과 주장을 대조한다 |
