#!/usr/bin/env python3
"""coherence.py linkcheck interpretation and memory-map generation regressions."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COHERENCE = os.path.join(HERE, "coherence.py")
MEMORY_MAP = os.path.join(HERE, "build_memory_map.py")


def fixture(linkcheck_body=""):
    root = tempfile.mkdtemp(prefix="coherence-fixture-")
    os.makedirs(os.path.join(root, "tools"))
    os.makedirs(os.path.join(root, "system"))
    os.makedirs(os.path.join(root, "state"))
    # The kit stores config in templates/ and an installed instance stores it in system/.
    # This produces the same fixture in either tree.
    source = next(p for p in (os.path.join(ROOT, "templates", "memory-config.json"),
                              os.path.join(ROOT, "system", "memory-config.json"))
                  if os.path.isfile(p))
    config = json.load(open(source, encoding="utf-8"))
    config["instance"] = {"name": "fixture", "context": "personal",
                          "remote_allowlist": []}
    config["tracks"] = []
    config["threads"] = []
    config["checks"] = {"hubs": [], "status_docs": []}
    with open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)
    if linkcheck_body:
        path = os.path.join(root, "tools", "linkcheck.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env python3\n" + linkcheck_body)
    return root


HANGUL = re.compile("[가-힣]")


def run(script, root, *args, lang="ko"):
    environment = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_INTERNAL_RUN="1", MOTTORI_LANG=lang)
    return subprocess.run([sys.executable, script, *args], cwd=root, env=environment,
                          capture_output=True, text=True)


def test_linkcheck_measurement_failure_is_not_broken_count():
    root = fixture("import sys\nprint('probe crashed', file=sys.stderr)\nraise SystemExit(2)\n")
    try:
        result = run(COHERENCE, root)
        assert result.returncode == 1
        assert "linkcheck 측정 실패" in result.stdout
        assert "깨진 링크 -1" not in result.stdout
        assert "[coherence] 총 1건" in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_broken_links_remain_a_measured_count():
    body = ("import sys\n"
            "print('BROKEN README.md -> absent-a.md')\n"
            "print('BROKEN README.md -> absent-b.md')\n"
            "print('linkcheck: refs=2 broken: 2')\n"
            "raise SystemExit(1)\n")
    root = fixture(body)
    try:
        result = run(COHERENCE, root)
        assert result.returncode == 1
        assert "링크 2" in result.stdout
        assert "linkcheck 측정 실패" not in result.stdout
        assert result.stdout.count("[링크] BROKEN") == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_memory_map_is_generated_from_fixture_root():
    root = fixture()
    try:
        result = run(MEMORY_MAP, root)
        output = os.path.join(root, "system", "memory-map.html")
        assert result.returncode == 0, result.stdout + result.stderr
        assert os.path.isfile(output)
        page = open(output, encoding="utf-8").read()
        assert "기억 시스템 지도" in page
        assert "public journal 사건" in page
        assert "tools/build_memory_map.py" in page
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_english_output_has_no_hangul():
    crashed = fixture("import sys\nprint('probe crashed', file=sys.stderr)\nraise SystemExit(2)\n")
    broken = fixture("print('BROKEN README.md -> absent-a.md')\n"
                     "print('linkcheck: refs=1 broken: 1')\nraise SystemExit(1)\n")
    try:
        failed = run(COHERENCE, crashed, lang="en")
        assert failed.returncode == 1
        assert "linkcheck measurement failed" in failed.stdout, failed.stdout
        assert "[coherence] total 1" in failed.stdout, failed.stdout
        assert not HANGUL.search(failed.stdout), failed.stdout
        counted = run(COHERENCE, broken, lang="en")
        assert "links 1" in counted.stdout and "[links] BROKEN" in counted.stdout, counted.stdout
        assert not HANGUL.search(counted.stdout), counted.stdout
        quiet = run(COHERENCE, broken, "--quiet", lang="en")
        assert quiet.stdout.startswith("[coherence] 1 issue(s): broken links 1"), quiet.stdout
        assert not HANGUL.search(quiet.stdout), quiet.stdout
    finally:
        shutil.rmtree(crashed, ignore_errors=True)
        shutil.rmtree(broken, ignore_errors=True)


def test_ledger_trailer_is_read_in_either_language():
    """A rec.py check trailer printed in one language is counted under the other."""
    clean = "print('linkcheck: refs=0 broken: 0')\n"
    for trailer, lang in (("[check] 문제: 3건", "en"), ("[check] problems: 3", "ko")):
        root = fixture(clean)
        try:
            os.makedirs(os.path.join(root, "_private", "ledger", "facts"))
            with open(os.path.join(root, "tools", "rec.py"), "w", encoding="utf-8") as f:
                f.write(f"print({trailer!r})\nraise SystemExit(1)\n")
            result = run(COHERENCE, root, "--quiet", lang=lang)
            assert result.returncode == 1, result.stdout + result.stderr
            expected = "원장 문제 3" if lang == "ko" else "ledger problems 3"
            assert expected in result.stdout, result.stdout
        finally:
            shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_linkcheck_measurement_failure_is_not_broken_count,
    test_broken_links_remain_a_measured_count,
    test_memory_map_is_generated_from_fixture_root,
    test_english_output_has_no_hangul,
    test_ledger_trailer_is_read_in_either_language,
]


def main():
    failed = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"coherence: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
