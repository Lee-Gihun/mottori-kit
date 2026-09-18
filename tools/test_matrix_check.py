#!/usr/bin/env python3
"""Fail closed when the risk-based test matrix loses required coverage."""
import copy
import json
import os

from testlib import run_test


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATRIX = os.path.join(ROOT, "system", "test-matrix.yaml")
REVIEW = os.path.join(ROOT, "system", "review-manifest.yaml")
LAYERS = ("U", "S", "N", "M", "E2E")
RISKS = {"critical", "normal", "wrapper"}
REQUIRED = {"critical": set(LAYERS), "normal": {"U", "S", "N"}, "wrapper": {"S", "N"}}
CRITICAL_PROOFS = {
    "setup.sh": {
        "U": ("tools/test_setup_migration.py", "test_fresh_setup_creates_v4_config_and_now"),
        "S": ("tools/test_setup_migration.py", "test_v4_preserves_existing_visibility_cutover_semantics"),
        "N": ("tools/test_setup_migration.py", "test_structurally_invalid_config_aborts_without_overwrite"),
        "M": ("tools/test_mutation.py", "setup-constant"),
        "E2E": ("tools/test_fresh_install.sh", "setup.sh"),
    },
    "tools/memlib.py": {
        "U": ("tools/test_memlib_journal.py", "test_journal_body_exact_boundary"),
        "S": ("tools/test_state_runtime.py", "test_routing_and_public_immutability"),
        "N": ("tools/test_state_runtime.py", "test_structurally_invalid_config_fails_closed_without_import_crash"),
        "M": ("tools/test_mutation.py", "memlib-constant"),
        "E2E": ("tools/test_fresh_install.sh", "tools/memlib.py"),
    },
    "tools/now.py": {
        "U": ("tools/test_state_runtime.py", "test_routing_and_public_immutability"),
        "S": ("tools/test_state_runtime.py", "test_parallel_writers_exactly_once"),
        "N": ("tools/test_state_runtime.py", "test_identity_change_inside_atomic_publish_rolls_back_log_and_snapshot"),
        "M": ("tools/test_mutation.py", "now-return"),
        "E2E": ("tools/test_fresh_install.sh", "tools/now.py"),
    },
    "tools/gate.py": {
        "U": ("tools/test_hook_runtime.py", "test_gate_unit_rejects_current_only_checker_key"),
        "S": ("tools/test_hook_runtime.py", "test_precommit_now_check_reads_extracted_index_tree"),
        "N": ("tools/test_install_checks.py", "test_fresh_install_rejects_malformed_summaries"),
        "M": ("tools/test_mutation.py", "gate-return"),
        "E2E": ("tools/test_fresh_install.sh", "tools/gate.py"),
    },
    "tools/linkcheck.py": {
        "U": ("tools/test_install_checks.py", "test_linkcheck_exclude_config_applies_only_without_all"),
        "S": ("tools/test_install_checks.py", "test_linkcheck_extracted_tree_uses_only_ignored_root_fallback"),
        "N": ("tools/test_install_checks.py", "test_linkcheck_exit_codes_and_pending"),
        "M": ("tools/test_mutation.py", "linkcheck-compare"),
        "E2E": ("tools/test_fresh_install.sh", "tools/linkcheck.py"),
    },
    "tools/doctor.py": {
        "U": ("tools/test_install_checks.py", "test_doctor_remote_allowlist_is_host_and_path_bounded"),
        "S": ("tools/test_doctor_json.py", "test_precompact_simulation_passes_for_both_runtimes"),
        "N": ("tools/test_install_checks.py", "test_doctor_codex_armed_and_git_version"),
        "M": ("tools/test_mutation.py", "doctor-return"),
        "E2E": ("tools/test_fresh_install.sh", "tools/doctor.py"),
    },
    "tools/fresh_worker.py": {
        "U": ("tools/test_fresh_worker.py", "test_fresh_worker_receipt_limit_matches_contract_boundary"),
        "S": ("tools/test_fresh_worker.py", "test_strict_scope_detects_git_and_immediate_parent_writes"),
        "N": ("tools/test_fresh_worker.py", "test_prompt_boundaries_fail_closed"),
        "M": ("tools/test_mutation.py", "fresh-worker-constant"),
        "E2E": ("tools/test_fresh_install.sh", "tools/fresh_worker.py"),
    },
    "tools/install_hooks.sh": {
        "U": ("tools/test_install_hooks.py", "test_repair_then_check_installs_exact_executable"),
        "S": ("tools/test_install_hooks.py", "test_failed_repair_restores_current_hook_and_preserves_missing_hook"),
        "N": ("tools/test_install_hooks.py", "test_foreign_precommit_aborts_without_overwrite"),
        "M": ("tools/test_mutation.py", "install-hooks-return"),
        "E2E": ("tools/test_fresh_install.sh", "tools/install_hooks.sh"),
    },
}


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _expected_tools(review):
    expected = set()
    for row in review.get("files", []):
        path = row.get("path", "")
        name = os.path.basename(path)
        if row.get("kind") not in {"tool", "hook", "gate-definition"}:
            continue
        if path == "setup.sh" or (path.startswith("tools/") and not name.startswith("test_")
                                  and name.endswith((".py", ".sh", ".js"))):
            expected.add(path)
    return expected


def _proof_error(tool, layer, test_path, root):
    expected_path, selector = CRITICAL_PROOFS[tool][layer]
    if test_path != expected_path:
        return f"{tool}:{layer}: proof path must be {expected_path}"
    text = open(os.path.join(root, test_path), encoding="utf-8", errors="replace").read()
    if layer in {"U", "S", "N"}:
        present = f"def {selector}(" in text
    elif layer == "M":
        present = f'Mutation("{selector}", "{tool}"' in text
    else:
        present = f"# CRITICAL_E2E {selector}" in text
    return None if present else f"{tool}:{layer}: proof selector absent: {selector}"


def validate(document, root=ROOT, review=None):
    errors = []
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    rows = document.get("tools")
    if not isinstance(rows, list):
        return errors + ["tools must be a list"]
    seen = set()
    for index, row in enumerate(rows):
        label = f"tools[{index}]"
        path, risk, layers = row.get("path"), row.get("risk"), row.get("layers")
        if not isinstance(path, str) or not path:
            errors.append(f"{label}.path missing")
            continue
        if path in seen:
            errors.append(f"duplicate path: {path}")
        seen.add(path)
        if not os.path.isfile(os.path.join(root, path)):
            errors.append(f"tool path missing: {path}")
        if risk not in RISKS:
            errors.append(f"{path}: invalid risk {risk!r}")
            continue
        if not isinstance(layers, dict) or set(layers) != set(LAYERS):
            errors.append(f"{path}: layers must be exactly {','.join(LAYERS)}")
            continue
        for layer in REQUIRED[risk]:
            if layers[layer] is None:
                errors.append(f"{path}: required layer {layer} is null")
        for layer, test_path in layers.items():
            if test_path is None:
                continue
            full = os.path.join(root, test_path)
            if not os.path.isfile(full):
                errors.append(f"{path}:{layer}: test path missing: {test_path}")
                continue
            text = open(full, encoding="utf-8", errors="replace").read()
            if path not in text and os.path.basename(path) not in text:
                errors.append(f"{path}:{layer}: name absent from {test_path}")
        if risk == "critical":
            if path not in CRITICAL_PROOFS:
                errors.append(f"{path}: critical proof map missing")
            else:
                for layer in LAYERS:
                    test_path = layers.get(layer)
                    if not isinstance(test_path, str) or not os.path.isfile(os.path.join(root, test_path)):
                        continue
                    proof_error = _proof_error(path, layer, test_path, root)
                    if proof_error:
                        errors.append(proof_error)
    review = review if review is not None else _load(REVIEW)
    expected = _expected_tools(review)
    if seen != expected:
        errors.append("matrix inventory mismatch: missing=" + repr(sorted(expected - seen))
                      + " extra=" + repr(sorted(seen - expected)))
    return errors


def _self_test(document, review):
    broken = copy.deepcopy(document)
    broken["tools"][0]["layers"]["M"] = None
    assert any("required layer M is null" in e for e in validate(broken, review=review))
    broken = copy.deepcopy(document)
    broken["tools"][0]["layers"]["U"] = "tools/no-such-test.py"
    assert any("test path missing" in e for e in validate(broken, review=review))
    broken = copy.deepcopy(document)
    broken["tools"][0]["layers"]["U"] = "tools/test_rec.py"
    assert any("proof path must" in e for e in validate(broken, review=review))


def main():
    try:
        document, review = _load(MATRIX), _load(REVIEW)
        errors = validate(document, review=review)
        _self_test(document, review)
    except Exception as exc:  # noqa: BLE001
        print(f"test matrix: FAIL parser/self-test: {type(exc).__name__}: {exc}")
        return 1
    if errors:
        for error in errors:
            print("FAIL " + error)
        print(f"test matrix: FAIL {len(errors)} issue(s)")
        return 1
    print(f"test matrix: PASS {len(document['tools'])} tools, required null 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_test(main, __file__))
