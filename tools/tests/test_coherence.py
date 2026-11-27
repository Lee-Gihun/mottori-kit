#!/usr/bin/env python3
"""coherence.py hub and status-date checks and memory-map generation regressions."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
COHERENCE = os.path.join(HERE, "coherence.py")
MEMORY_MAP = os.path.join(HERE, "dev", "build_memory_map.py")


def fixture(checks=None):
    root = tempfile.mkdtemp(prefix="coherence-fixture-")
    os.makedirs(os.path.join(root, "tools"))
    os.makedirs(os.path.join(root, "instance"))
    os.makedirs(os.path.join(root, "state"))
    # The kit stores config in templates/ and an installed instance stores it in system/.
    # This produces the same fixture in either tree.
    source = next(p for p in (os.path.join(ROOT, "templates", "config.json"),
                              os.path.join(ROOT, "instance", "config.json"))
                  if os.path.isfile(p))
    config = json.load(open(source, encoding="utf-8"))
    config["instance"] = {"name": "fixture"}
    config["tracks"] = []
    config["threads"] = []
    config["checks"] = checks or {"hubs": [], "status_docs": []}
    with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)
    return root


HANGUL = re.compile("[가-힣]")


def run(script, root, *args):
    environment = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_INTERNAL_RUN="1")
    return subprocess.run([sys.executable, script, *args], cwd=root, env=environment,
                          capture_output=True, text=True)


def test_memory_map_is_generated_from_fixture_root():
    root = fixture()
    try:
        result = run(MEMORY_MAP, root)
        output = os.path.join(root, "state", "memory-map.html")
        assert result.returncode == 0, result.stdout + result.stderr
        assert os.path.isfile(output)
        page = open(output, encoding="utf-8").read()
        assert "<title>Memory system map</title>" in page, page[:300]
        assert not HANGUL.search(page), HANGUL.search(page)
        assert "tools/dev/build_memory_map.py" in page
    finally:
        shutil.rmtree(root, ignore_errors=True)


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_status_doc_with_invalid_date_is_one_issue():
    root = fixture({"hubs": [], "status_docs": [["S.md", 4]]})
    try:
        write(root, "S.md", "# S\nStatus 2026-13-40\n")
        result = run(COHERENCE, root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "Traceback" not in result.stderr, result.stderr
        assert "S.md" in result.stdout, result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # A malformed checks row is one issue naming the key and the row, not a traceback.
    for checks, needle in (({"hubs": [], "status_docs": [["S.md", "14"]]}, "checks.status_docs row 1"),
                           ({"hubs": 123, "status_docs": []}, "checks.hubs must be a list"),
                           ({"hubs": [["docs"]], "status_docs": []}, "checks.hubs row 1"),
                           ({"hubs": [], "status_docs": [], "hub_ignore_ext": [".pyc", 5]},
                            "checks.hub_ignore_ext row 2")):
        root = fixture(checks)
        try:
            write(root, "S.md", "# S\nUpdated 2020-01-01\n")
            result = run(COHERENCE, root)
            assert result.returncode == 1 and "Traceback" not in result.stderr, result.stderr
            assert needle in result.stdout, (needle, result.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_stale_status_doc_is_reported():
    root = fixture({"hubs": [], "status_docs": [["S.md", 4], ["gone.md", 4]]})
    try:
        # A date far in the past stays stale whatever the real clock says.
        write(root, "S.md", "# S\nUpdated 2020-01-01\n")
        result = run(COHERENCE, root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "S.md: updated" in result.stdout and "header 2020-01-01" in result.stdout, result.stdout
        assert "gone.md: listed in checks.status_docs but missing" in result.stdout, result.stdout
        assert not HANGUL.search(result.stdout), result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hub_unlisted_file_not_hidden_by_longer_name():
    root = fixture({"hubs": [["hub", "INDEX.md"]], "status_docs": []})
    try:
        index = write(root, "hub/INDEX.md", "see data.md\n")
        os.utime(index, (1_000_000_000, 1_000_000_000))
        write(root, "hub/a.md", "a\n")
        write(root, "hub/new.md", "n\n")
        write(root, "hub/data.md", "d\n")
        result = run(COHERENCE, root)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "2 new file(s) not listed: a.md, new.md" in result.stdout, result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_instance_that_lists_nothing_is_told_nothing_was_checked():
    """An empty list checks nothing, and saying OK would read as a check that found nothing."""
    root = fixture({"hubs": [], "status_docs": []})
    try:
        result = run(COHERENCE, root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "nothing to check" in result.stdout and "OK" not in result.stdout, result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_run_log_records_pass_or_fail():
    root = fixture({"hubs": [], "status_docs": [["S.md", 4]]})
    try:
        environment = dict(os.environ, MOTTORI_INSTANCE=root)
        environment.pop("MOTTORI_INTERNAL_RUN", None)
        helped = subprocess.run([sys.executable, COHERENCE, "--help"], cwd=root, env=environment,
                                capture_output=True, text=True)
        assert helped.returncode == 0 and "Usage:" in helped.stdout, helped.stdout + helped.stderr
        assert not os.path.exists(os.path.join(root, "state", ".tool-runs.log"))
        # A listed status document that is missing is an issue, so the passing run needs a fresh one.
        import datetime
        write(root, "S.md", f"# S\nUpdated {datetime.date.today().isoformat()}\n")
        subprocess.run([sys.executable, COHERENCE], cwd=root, env=environment,
                       capture_output=True, text=True)
        write(root, "S.md", "# S\nUpdated 2020-01-01\n")
        subprocess.run([sys.executable, COHERENCE], cwd=root, env=environment,
                       capture_output=True, text=True)
        lines = [l.rstrip("\n").split("\t") for l in
                 open(os.path.join(root, "state", ".tool-runs.log"), encoding="utf-8")]
        assert [l[-1] for l in lines if l[1] == "coherence"] == ["ok", "ng"], lines
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_memory_map_is_generated_from_fixture_root,
    test_status_doc_with_invalid_date_is_one_issue,
    test_stale_status_doc_is_reported,
    test_hub_unlisted_file_not_hidden_by_longer_name,
    test_an_instance_that_lists_nothing_is_told_nothing_was_checked,
    test_run_log_records_pass_or_fail,
]


def main():
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"coherence: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
