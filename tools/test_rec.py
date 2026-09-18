#!/usr/bin/env python3
"""rec.py CLI regressions using isolated temporary ledgers."""
import os
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = os.path.dirname(os.path.abspath(__file__))


def fixture(*, facts=False):
    root = tempfile.mkdtemp(prefix="rec-fixture-")
    os.makedirs(os.path.join(root, "tools"))
    shutil.copy2(os.path.join(HERE, "rec.py"), os.path.join(root, "tools", "rec.py"))
    if facts:
        os.makedirs(os.path.join(root, "_private", "ledger", "facts"))
    return root


def run(root, *args):
    return subprocess.run([sys.executable, "tools/rec.py", *args], cwd=root,
                          capture_output=True, text=True)


def test_new_find_check_audit_chain():
    root = fixture()
    try:
        os.makedirs(os.path.join(root, "sources"))
        with open(os.path.join(root, "sources", "origin.txt"), "w", encoding="utf-8") as f:
            f.write("origin evidence\n")
        created = run(root, "new", "fixture-fact", "--claim=검증된 사실",
                      "--status=확정", "--speaker=소유자", "--tags=회귀,기억",
                      "--origin=sources/origin.txt", "--origin_kind=문서",
                      "--domain=테스트", "--date=2026-09-17")
        assert created.returncode == 0, created.stdout + created.stderr

        found = run(root, "find", "검증된", "--speaker=소유")
        assert found.returncode == 0 and "fixture-fact" in found.stdout
        checked = run(root, "check")
        assert checked.returncode == 0 and "문제: 0건" in checked.stdout
        audited = run(root, "audit", "fixture-fact")
        assert audited.returncode == 0
        assert "[✓] sources/origin.txt" in audited.stdout
        assert "원점 결손: 없음" in audited.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_distinguishes_uncreated_ledger():
    root = fixture()
    try:
        result = run(root, "find", "anything")
        assert result.returncode == 1
        assert "원장이 없다" in result.stdout
        assert "기록에 없다" not in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_distinguishes_empty_ledger():
    root = fixture(facts=True)
    try:
        result = run(root, "find", "anything")
        assert result.returncode == 0
        assert "기록에 없다" in result.stdout
        assert "원장이 없다" not in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_new_find_check_audit_chain,
    test_find_distinguishes_uncreated_ledger,
    test_find_distinguishes_empty_ledger,
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
    print(f"rec: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
