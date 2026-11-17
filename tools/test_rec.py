#!/usr/bin/env python3
"""rec.py CLI regressions using isolated temporary ledgers."""
import os
import re
import shutil
import subprocess
import sys
import tempfile

from testlib import run_test


HERE = os.path.dirname(os.path.abspath(__file__))


def fixture(*, facts=False):
    root = tempfile.mkdtemp(prefix="rec-fixture-")
    os.makedirs(os.path.join(root, "tools"))
    for name in ("rec.py", "i18n.py"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    if facts:
        os.makedirs(os.path.join(root, "_private", "ledger", "facts"))
    return root


def run(root, *args, lang="ko", instance=None):
    env = dict(os.environ, MOTTORI_LANG=lang)
    env.pop("MOTTORI_INSTANCE", None)
    if instance:
        env["MOTTORI_INSTANCE"] = instance
    return subprocess.run([sys.executable, "tools/rec.py", *args], cwd=root, env=env,
                          capture_output=True, text=True)


def make_fact(root, claim="검증된 사실"):
    os.makedirs(os.path.join(root, "sources"), exist_ok=True)
    with open(os.path.join(root, "sources", "origin.txt"), "w", encoding="utf-8") as f:
        f.write("origin evidence\n")
    created = run(root, "new", "fixture-fact", "--claim=" + claim,
                  "--status=확정", "--speaker=소유자", "--tags=회귀,기억",
                  "--origin=sources/origin.txt", "--origin_kind=문서",
                  "--domain=테스트", "--date=2026-09-17")
    assert created.returncode == 0, created.stdout + created.stderr


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
        assert "찾은 범위에서 0건" in result.stdout and "레코드 0건" in result.stdout
        assert "기록에 없다" not in result.stdout
        assert "원장이 없다" not in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_zero_hits_reports_scope_and_suggests_rewording():
    root = fixture()
    try:
        make_fact(root, "배포는 금요일에 한다")
        for lang, needles in (("ko", ["찾은 범위에서 0건", "레코드 1건", "--tag=기억", "다른 언어"]),
                              ("en", ["0 hits in the searched scope", "1 record", "--tag=기억",
                                      "other language"])):
            result = run(root, "find", "deployment", "--tag=기억", lang=lang)
            assert result.returncode == 0, result.stdout + result.stderr
            for needle in needles:
                assert needle in result.stdout, (needle, result.stdout)
            assert "기록에 없다" not in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hot_prints_hotset_content():
    root = fixture()
    try:
        make_fact(root, "핫셋에 보일 주장")
        result = run(root, "hot")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "핫셋에 보일 주장" in result.stdout and "fixture-fact" in result.stdout, result.stdout
        hotset = os.path.join(root, "_private", "ledger", "hotset.md")
        assert open(hotset, encoding="utf-8").read().strip() in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ledger_follows_mottori_instance():
    engine, instance = fixture(), fixture()
    try:
        make_fact(instance, "인스턴스 쪽 사실")
        result = run(engine, "find", "인스턴스", instance=instance)
        assert result.returncode == 0 and "fixture-fact" in result.stdout, result.stdout
    finally:
        shutil.rmtree(engine, ignore_errors=True)
        shutil.rmtree(instance, ignore_errors=True)


def _status_fact(root, rid, status):
    os.makedirs(os.path.join(root, "sources"), exist_ok=True)
    with open(os.path.join(root, "sources", "origin.txt"), "w", encoding="utf-8") as f:
        f.write("origin evidence\n")
    created = run(root, "new", rid, "--claim=claim of " + rid, "--status=" + status,
                  "--speaker=owner", "--tags=fixture", "--origin=sources/origin.txt",
                  "--origin_kind=document", "--domain=test", "--date=2026-09-17")
    assert created.returncode == 0, created.stdout + created.stderr


def test_english_output_has_no_hangul():
    root = fixture()
    try:
        _status_fact(root, "fact-one", "confirmed")
        _status_fact(root, "fact-two", "superseded")
        outputs = [run(root, *args, lang="en") for args in (
            ("new", "Bad_ID"), ("new", "fact-one"), ("find", "claim"), ("find", "absent"),
            ("show", "nope"), ("audit", "fact-one"), ("check",), ("hot",), ("snapshot",))]
        text = "\n".join(r.stdout + r.stderr for r in outputs)
        assert "[check] problems: 1" in text and "status `superseded` requires" in text, text
        assert "## C. Confirmed" in text and "origin gap: none" in text, text
        assert not re.search("[가-힣]", text), text
        scaffold = run(root, "new", "scaffold-one", lang="en")
        assert scaffold.returncode == 0
        body = open(os.path.join(root, "_private", "ledger", "facts", "scaffold-one.md"),
                    encoding="utf-8").read()
        assert "status: TODO-status" in body and not re.search("[가-힣]", body), body
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_status_values_are_read_in_either_language():
    """A ledger written under one language keeps its meaning under the other."""
    root = fixture()
    try:
        _status_fact(root, "fact-ko", "결정됨")
        _status_fact(root, "fact-en", "decided")
        _status_fact(root, "old-ko", "대체됨")
        _status_fact(root, "old-en", "superseded")
        for lang in ("ko", "en"):
            checked = run(root, "check", lang=lang)
            problems = [line for line in checked.stdout.splitlines() if line.startswith("PROBLEM")]
            assert len(problems) == 2, checked.stdout
            assert all("old-" in line and "superseded_by" in line for line in problems), problems
            hot = run(root, "hot", lang=lang)
            heading = "## A. 결정됨" if lang == "ko" else "## A. Decided"
            section = hot.stdout.split(heading, 1)[1].split("## ", 1)[0]
            assert "fact-ko" in section and "fact-en" in section, hot.stdout
            assert hot.stdout.count("`fact-ko`") == 1 and hot.stdout.count("`fact-en`") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_english_output_has_no_hangul,
    test_status_values_are_read_in_either_language,
    test_new_find_check_audit_chain,
    test_find_distinguishes_uncreated_ledger,
    test_find_distinguishes_empty_ledger,
    test_find_zero_hits_reports_scope_and_suggests_rewording,
    test_hot_prints_hotset_content,
    test_ledger_follows_mottori_instance,
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
