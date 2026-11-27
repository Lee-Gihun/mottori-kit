#!/usr/bin/env python3
"""Every tool file is named by a test file, and the critical tools keep their required proofs.

A tool file is a tracked .py, .sh or .js file under tools/ that is neither a test file (test_*) nor
test data (tools/tests/fixtures/). A test file names it when its text holds the tool's path or file
name, or one of its import lines names the tool's module. A file that reaches a tool only through
another module lists it in a COVERED tuple.

Each critical tool has five proofs, one per layer: U (unit), S (system) and N (negative) are test
functions of the given name, M is a Mutation("selector", "tool", ...) entry, E2E is a
"# CRITICAL_E2E selector" line in the given file.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
CRITICAL_PROOFS = {
    "setup.sh": {
        "U": ("tools/tests/test_setup_migration.py", "test_fresh_setup_creates_v4_config_and_now"),
        "S": ("tools/tests/test_setup_migration.py", "test_v4_preserves_existing_visibility_cutover_semantics"),
        "N": ("tools/tests/test_setup_migration.py", "test_structurally_invalid_config_aborts_without_overwrite"),
        "M": ("tools/tests/test_mutation.py", "setup-compare"),
        "E2E": ("tools/tests/test_fresh_install.sh", "setup.sh"),
    },
    "tools/lib/config.py": {
        "U": ("tools/tests/test_memlib_journal.py", "test_tilde_instance_reads_its_config"),
        "S": ("tools/tests/test_doctor_json.py", "test_manual_items_name_only_what_is_installed_and_a_broken_config_names_its_error"),
        "N": ("tools/tests/test_memlib_journal.py", "test_root_aliases_shape_fails_closed"),
        "M": ("tools/tests/test_mutation.py", "config-compare"),
        "E2E": ("tools/tests/test_instance_shape.py", "tools/lib/config.py"),
    },
    "tools/lib/journal.py": {
        "U": ("tools/tests/test_memlib_journal.py", "test_journal_body_exact_boundary"),
        "S": ("tools/tests/test_doctor_json.py", "test_precompact_simulation_passes_for_both_runtimes"),
        "N": ("tools/tests/test_memlib_journal.py", "test_parse_journal_reports_invalid_utf8"),
        "M": ("tools/tests/test_mutation.py", "journal-constant"),
        "E2E": ("tools/tests/test_instance_shape.py", "tools/lib/journal.py"),
    },
    "tools/now.py": {
        "U": ("tools/tests/test_state_runtime.py", "test_routing_and_public_immutability"),
        "S": ("tools/tests/test_state_runtime.py", "test_parallel_writers_exactly_once"),
        "N": ("tools/tests/test_state_runtime.py", "test_config_change_after_import_aborts_before_public_mutation"),
        "M": ("tools/tests/test_mutation.py", "now-return"),
        "E2E": ("tools/tests/test_fresh_install.sh", "tools/now.py"),
    },
    "tools/gate.py": {
        "U": ("tools/tests/test_hook_runtime.py", "test_gate_unit_rejects_current_only_checker_key"),
        "S": ("tools/tests/test_hook_runtime.py", "test_precommit_now_check_reads_extracted_index_tree"),
        "N": ("tools/tests/test_install_checks.py", "test_fresh_install_rejects_malformed_summaries"),
        "M": ("tools/tests/test_mutation.py", "gate-return"),
        "E2E": ("tools/tests/test_fresh_install.sh", "tools/gate.py"),
    },
    "tools/linkcheck.py": {
        "U": ("tools/tests/test_install_checks.py", "test_linkcheck_exclude_config_applies_only_without_all"),
        "S": ("tools/tests/test_install_checks.py", "test_linkcheck_extracted_tree_uses_only_ignored_root_fallback"),
        "N": ("tools/tests/test_install_checks.py", "test_linkcheck_exit_codes_and_pending"),
        "M": ("tools/tests/test_mutation.py", "linkcheck-compare"),
        "E2E": ("tools/tests/test_fresh_install.sh", "tools/linkcheck.py"),
    },
    "tools/doctor.py": {
        "U": ("tools/tests/test_install_checks.py", "test_doctor_does_not_fail_a_tracked_symlink_to_a_public_file"),
        "S": ("tools/tests/test_doctor_json.py", "test_precompact_simulation_passes_for_both_runtimes"),
        "N": ("tools/tests/test_install_checks.py", "test_doctor_codex_armed_and_git_version"),
        "M": ("tools/tests/test_mutation.py", "doctor-compare"),
        "E2E": ("tools/tests/test_fresh_install.sh", "tools/doctor.py"),
    },
    "tools/fresh_worker.py": {
        "U": ("tools/tests/test_fresh_worker.py", "test_fresh_worker_receipt_limit_matches_contract_boundary"),
        "S": ("tools/tests/test_fresh_worker.py", "test_scope_violation_detected_outside_prefix_and_symlink_escape"),
        "N": ("tools/tests/test_fresh_worker.py", "test_prompt_boundaries_fail_closed"),
        "M": ("tools/tests/test_mutation.py", "fresh-worker-constant"),
        "E2E": ("tools/tests/test_fresh_install.sh", "tools/fresh_worker.py"),
    },
    "tools/install_hooks.sh": {
        "U": ("tools/tests/test_install_hooks.py", "test_repair_then_check_installs_exact_executable"),
        "S": ("tools/tests/test_install_hooks.py", "test_failed_repair_restores_current_hook_and_preserves_missing_hook"),
        "N": ("tools/tests/test_install_hooks.py", "test_foreign_precommit_aborts_without_overwrite"),
        "M": ("tools/tests/test_mutation.py", "install-hooks-return"),
        "E2E": ("tools/tests/test_fresh_install.sh", "tools/install_hooks.sh"),
    },
}


IMPORT_LINE = re.compile(r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+)?import[ \t]+\(?([\w., \t]+)", re.M)


def tracked(root):
    """The tracked paths under tools/ of a Git tree."""
    listed = subprocess.run(["git", "ls-files", "-z", "tools"], cwd=root, capture_output=True,
                            text=True, check=True)
    return [path for path in listed.stdout.split("\0") if path]


def unnamed_tools(root, paths):
    """Return the tool files among paths that no test file among them names."""
    def is_test(path):
        return path.startswith("tools/tests/") and os.path.basename(path).startswith("test_")
    tools = [path for path in paths if path.endswith((".py", ".sh", ".js")) and not is_test(path)
             and not path.startswith("tools/tests/fixtures/")]
    texts, modules = [], set()
    for path in filter(is_test, paths):
        text = (Path(root) / path).read_text(encoding="utf-8", errors="replace")
        texts.append(text)
        for match in IMPORT_LINE.finditer(text):
            if match.group(1):
                modules.add(match.group(1).rsplit(".", 1)[-1])
            modules.update(name.split()[0] for name in match.group(2).split(",") if name.strip())
    named = []
    for tool in tools:
        name = os.path.basename(tool)
        if os.path.splitext(name)[0] in modules or any(tool in text or name in text for text in texts):
            named.append(tool)
    return sorted(set(tools) - set(named))


def proof_problems(root, proofs):
    """Return one line for each required proof that its file does not hold."""
    problems = []
    for tool, layers in proofs.items():
        for layer in ("U", "S", "N", "M", "E2E"):
            if layer not in layers:
                problems.append(f"{tool}:{layer}: no proof named")
                continue
            path, selector = layers[layer]
            try:
                text = (Path(root) / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                problems.append(f"{tool}:{layer}: {path} missing")
                continue
            needle = {"M": f'Mutation("{selector}", "{tool}"',
                      "E2E": f"# CRITICAL_E2E {selector}"}.get(layer, f"def {selector}(")
            if needle not in text:
                problems.append(f"{tool}:{layer}: {path} lacks {selector}")
    return problems


def test_every_tool_file_is_named_by_a_test_file():
    assert unnamed_tools(ROOT, tracked(ROOT)) == [], unnamed_tools(ROOT, tracked(ROOT))


def test_critical_tools_keep_their_proofs():
    assert proof_problems(ROOT, CRITICAL_PROOFS) == [], proof_problems(ROOT, CRITICAL_PROOFS)


def test_a_tool_file_no_test_names_fails():
    with tempfile.TemporaryDirectory(prefix="tool-coverage-") as tmp:
        files = {
            "tools/named.py": "", "tools/lib/imported.py": "", "tools/loop/lib/listed.py": "",
            "tools/lonely.sh": "", "tools/tests/fixtures/data.py": "", "tools/tests/testlib.py": "",
            "tools/tests/test_a.py": "import testlib\nfrom lib import imported\n# tools/named.py\n",
            "tools/tests/test_b.py": 'COVERED = (\n    "tools/loop/lib/listed.py",\n)\n',
        }
        for rel, text in files.items():
            (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / rel).write_text(text, encoding="utf-8")
        assert unnamed_tools(tmp, list(files)) == ["tools/lonely.sh"], unnamed_tools(tmp, list(files))


def test_a_critical_tool_that_loses_a_proof_fails():
    with tempfile.TemporaryDirectory(prefix="tool-coverage-") as tmp:
        tests = Path(tmp) / "tools" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_x.py").write_text("def test_unit():\n    pass\n"
                                         'MUTATIONS = [Mutation("x-return", "tools/x.py", "early-return")]\n'
                                         "# CRITICAL_E2E tools/x.py\n", encoding="utf-8")
        proofs = {"tools/x.py": {layer: ("tools/tests/test_x.py", "test_unit") for layer in ("U", "S", "N")}}
        proofs["tools/x.py"].update(M=("tools/tests/test_x.py", "x-return"),
                                    E2E=("tools/tests/test_x.py", "tools/x.py"))
        assert proof_problems(tmp, proofs) == []
        proofs["tools/x.py"]["N"] = ("tools/tests/test_x.py", "test_gone")
        proofs["tools/x.py"]["M"] = ("tools/tests/test_x.py", "x-compare")
        del proofs["tools/x.py"]["E2E"]
        assert proof_problems(tmp, proofs) == [
            "tools/x.py:N: tools/tests/test_x.py lacks test_gone",
            "tools/x.py:M: tools/tests/test_x.py lacks x-compare",
            "tools/x.py:E2E: no proof named"], proof_problems(tmp, proofs)


if __name__ == "__main__":
    for test in (test_every_tool_file_is_named_by_a_test_file, test_critical_tools_keep_their_proofs,
                 test_a_tool_file_no_test_names_fails, test_a_critical_tool_that_loses_a_proof_fails):
        test()
        print("PASS " + test.__name__)
