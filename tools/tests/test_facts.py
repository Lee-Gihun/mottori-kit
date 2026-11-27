#!/usr/bin/env python3
"""facts.py CLI regressions using isolated temporary ledgers."""
import os
import re
import shutil
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fixture(*, facts=False):
    root = tempfile.mkdtemp(prefix="facts-fixture-")
    os.makedirs(os.path.join(root, "tools", "lib"))
    for name in ("facts.py", "lib/config.py", "lib/paths.py", "lib/safeio.py"):
        shutil.copy2(os.path.join(HERE, name), os.path.join(root, "tools", name))
    if facts:
        os.makedirs(os.path.join(root, "_private", "ledger", "facts"))
    return root


def run(root, *args, instance=None):
    env = dict(os.environ)
    env.pop("MOTTORI_INSTANCE", None)
    if instance:
        env["MOTTORI_INSTANCE"] = instance
    return subprocess.run([sys.executable, "tools/facts.py", *args], cwd=root, env=env,
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
    assert "WARNING" not in created.stdout and "TODO" not in created.stdout, created.stdout


def test_new_find_check_audit_chain():
    root = fixture()
    try:
        make_fact(root, "검증된 사실")

        found = run(root, "find", "검증된", "--speaker=소유")
        assert found.returncode == 0 and "fixture-fact" in found.stdout and "[find] 1 hit(s)" in found.stdout, found.stdout
        checked = run(root, "check")
        assert checked.returncode == 0 and "problems: 0" in checked.stdout
        audited = run(root, "audit", "fixture-fact")
        assert audited.returncode == 0
        assert "[✓] sources/origin.txt" in audited.stdout
        assert "origin gap: none" in audited.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_distinguishes_uncreated_ledger():
    root = fixture()
    try:
        # Nothing recorded yet is an answer to a search, with the command that records the first fact.
        result = run(root, "find", "anything")
        assert result.returncode == 0, result.stdout
        assert "no facts recorded yet" in result.stdout and "facts.py new" in result.stdout, result.stdout
        shown = run(root, "show", "no-such-id")
        assert shown.returncode == 1 and "no facts recorded yet" in shown.stdout, shown.stdout
        checked = run(root, "check")
        assert checked.returncode == 0, checked.stdout
        assert checked.stdout.strip().splitlines() == [
            "[check] no ledger yet: _private/ledger/facts (facts.py new creates it)"], checked.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_distinguishes_empty_ledger():
    root = fixture(facts=True)
    try:
        result = run(root, "find", "anything")
        assert result.returncode == 0
        assert "0 hits in the searched scope" in result.stdout and "0 record(s)" in result.stdout
        assert "no ledger" not in result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_zero_hits_reports_scope_and_suggests_rewording():
    root = fixture()
    try:
        make_fact(root, "배포는 금요일에 한다")
        result = run(root, "find", "deployment", "--tag=기억")
        assert result.returncode == 0, result.stdout + result.stderr
        for needle in ("0 hits in the searched scope", "1 record", "--tag=기억", "another form of the word"):
            assert needle in result.stdout, (needle, result.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hot_prints_hotset_content():
    root = fixture()
    try:
        make_fact(root, "핫셋에 보일 주장")
        result = run(root, "hot")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "핫셋에 보일 주장" in result.stdout and "fixture-fact" in result.stdout, result.stdout
        assert "[hot] 1 record(s) ->" in result.stdout, result.stdout
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
        two = os.path.join(root, "_private", "ledger", "facts", "fact-two.md")
        text = open(two, encoding="utf-8").read()
        open(two, "w", encoding="utf-8").write(text.replace("\nhot: false\n", "\nhot: true\n"))
        outputs = [run(root, *args) for args in (
            ("new", "Bad_ID"), ("new", "fact-one"), ("find", "claim"), ("find", "absent"),
            ("show", "nope"), ("audit", "fact-one"), ("check",), ("hot",), ("snapshot",))]
        text = "\n".join(r.stdout + r.stderr for r in outputs)
        assert "[check] problems: 2" in text and "status `superseded` requires" in text, text
        assert "fact-two: a superseded record must not be hot" in text, text
        assert "## C. Confirmed" in text and "origin gap: none" in text, text
        assert not re.search("[가-힣]", text), text
        scaffold = run(root, "new", "scaffold-one")
        assert scaffold.returncode == 0
        body = open(os.path.join(root, "_private", "ledger", "facts", "scaffold-one.md"),
                    encoding="utf-8").read()
        assert "status: TODO-status" in body and not re.search("[가-힣]", body), body
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_status_values_are_read_in_either_language():
    """A status is read the same whether the record was written in Korean or English."""
    root = fixture()
    try:
        _status_fact(root, "fact-ko", "결정됨")
        _status_fact(root, "fact-en", "decided")
        _status_fact(root, "old-ko", "대체됨")
        _status_fact(root, "old-en", "superseded")
        checked = run(root, "check")
        problems = [line for line in checked.stdout.splitlines() if line.startswith("PROBLEM")]
        # Each superseded record lacks its link; facts.py new wrote it out of the hotset in either language.
        assert len(problems) == 2, checked.stdout
        assert all("old-" in line for line in problems), problems
        assert sum("superseded_by" in line for line in problems) == 2, problems
        hot = run(root, "hot")
        section = hot.stdout.split("## A. Decided", 1)[1].split("## ", 1)[0]
        assert "fact-ko" in section and "fact-en" in section, hot.stdout
        assert hot.stdout.count("`fact-ko`") == 1 and hot.stdout.count("`fact-en`") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


FACTS_REL = os.path.join("_private", "ledger", "facts")


def _write_fact(root, name, text):
    os.makedirs(os.path.join(root, FACTS_REL), exist_ok=True)
    with open(os.path.join(root, FACTS_REL, name), "w", encoding="utf-8") as f:
        f.write(text)


def _raw_fact(rid, *, status="확정", claim="a claim", origin="sources/origin.txt", via=True,
              with_id=True, body=""):
    lines = ["---"]
    if with_id:
        lines.append(f"id: {rid}")
    lines += [f"claim: {claim}" if claim == "" else f'claim: "{claim}"',
              f"status: {status}", "hot: true", "domain: test", "tags: [fixture]",
              "speaker: owner", "date: 2026-09-17", "origin_kind: document",
              f'origin: "{origin}"' if origin == "" else f"origin: {origin}"]
    if via:
        lines += ["via:", f"  - {origin}"]
    lines += ["---", "", body, ""]
    return "\n".join(lines)


def _problems(result):
    return [line for line in result.stdout.splitlines() if line.startswith("PROBLEM")]


def test_check_rejects_scaffold_todos():
    root = fixture()
    try:
        make_fact(root)  # creates sources/origin.txt
        os.remove(os.path.join(root, FACTS_REL, "fixture-fact.md"))
        created = run(root, "new", "scaf", "--status=확정", "--origin=sources/origin.txt",
                      "--origin_kind=문서")
        assert created.returncode == 0 and "TODO" in created.stdout, created.stdout + created.stderr
        assert run(root, "new", "bare").returncode == 0
        checked = run(root, "check")
        assert checked.returncode == 1, checked.stdout
        problems = " ".join(_problems(checked))
        for field in ("claim", "speaker", "domain", "tags"):
            assert f"`{field}`" in problems, (field, checked.stdout)
        # A present field holding a scaffold value must not be reported as missing.
        assert "TODO" in problems and "missing" not in problems, problems
        # The placeholder line is the one report; no second line quotes the placeholder value.
        assert "TODO-" not in problems, problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_malformed_record_is_reported_not_crashed():
    root = fixture()
    try:
        make_fact(root)
        _write_fact(root, "no-id.md", _raw_fact("no-id", with_id=False))
        _write_fact(root, "blank-claim.md", _raw_fact("blank-claim", claim=""))
        listed = run(root, "new", "list-origin", "--claim=c", "--status=확정", "--speaker=s",
                     "--tags=t", "--origin=[src/a, src/b]", "--origin_kind=문서", "--domain=d")
        assert listed.returncode == 0 and "WARNING" in listed.stdout, listed.stdout
        _write_fact(root, "list-speaker.md",
                    _raw_fact("list-speaker").replace("speaker: owner", "speaker: [a, b]"))
        _write_fact(root, "list-status.md", _raw_fact("list-status", status="[확정, 추정]"))
        _write_fact(root, "list-id.md", _raw_fact("[x, y]"))
        _write_fact(root, "list-date.md",
                    _raw_fact("list-date").replace("date: 2026-09-17", "date: [2026-09-17, 2026-09-18]"))
        _write_fact(root, "no-hot.md", _raw_fact("no-hot").replace("hot: true\n", ""))
        _write_fact(root, "typo-hot.md", _raw_fact("typo-hot").replace("hot: true", "hot: ture"))
        _write_fact(root, "empty-hot.md", _raw_fact("empty-hot").replace("hot: true", "hot:"))
        _write_fact(root, "bad-date.md",
                    _raw_fact("bad-date").replace("date: 2026-09-17", "date: 2026-02-30"))
        _write_fact(root, "self-ref.md", _raw_fact("self-ref", status="대체됨").replace(
            "hot: true", "hot: true\nsuperseded_by: self-ref"))
        _write_fact(root, "list-domain.md", _raw_fact("list-domain").replace(
            "domain: test", "domain: [a, b]").replace("origin_kind: document", "origin_kind: [doc]"))
        _write_fact(root, "single-quoted.md", _raw_fact("single-quoted", status="'확정'").replace(
            "  - sources/origin.txt", "  - 'sources/origin.txt'"))
        checked = run(root, "check")
        assert checked.returncode == 1, checked.stdout + checked.stderr
        assert "Traceback" not in checked.stderr, checked.stderr
        problems = " ".join(_problems(checked))
        assert "`id`" in problems and "`claim`" in problems, checked.stdout
        assert "list-origin: `origin`" in problems and "list-speaker: `speaker`" in problems, problems
        assert "list-status: `status`" in problems and "list-date: `date`" in problems, problems
        assert "list-id.md: `id`" in problems, problems
        # Read as false before validation, either would silently leave the hotset.
        assert "no-hot: required field missing `hot`" in problems and "typo-hot: `hot`" in problems, problems
        assert [p for p in _problems(checked) if "empty-hot:" in p] == [
            "PROBLEM empty-hot: required field missing `hot`"], checked.stdout
        assert "bad-date: `date` must be a real" in problems, problems
        assert "self-ref: superseded_by points to the record itself" in problems, problems
        assert "self-ref: a superseded record must not be hot" in problems, problems
        assert "list-domain: `domain`" in problems and "list-domain: `origin_kind`" in problems, problems
        assert "single-quoted" not in problems, problems
        for args in (("find", "claim"), ("find", ""), ("hot",), ("audit", "blank-claim"),
                     ("find", "--since=2026-01-01")):
            result = run(root, *args)
            assert result.returncode == 0 and "Traceback" not in result.stderr, (args, result.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_reports_unparsable_record():
    root = fixture()
    try:
        make_fact(root)
        _write_fact(root, "plain.md", "no front matter here\n")
        with open(os.path.join(root, FACTS_REL, "latin1.md"), "wb") as f:
            f.write(b"---\nid: latin1\nclaim: caf\xe9\n---\n")
        checked = run(root, "check")
        assert checked.returncode == 1, checked.stdout
        assert "Traceback" not in checked.stderr, checked.stderr
        for name in ("plain.md", "latin1.md"):
            assert any(name in line for line in _problems(checked)), checked.stdout
        audited = run(root, "audit", "plain")
        assert audited.returncode == 1 and "Traceback" not in audited.stderr, audited.stderr
        assert "plain.md" in audited.stdout, audited.stdout
        shown = run(root, "show", "latin1")
        assert shown.returncode == 1 and "Traceback" not in shown.stderr, shown.stderr
        assert "latin1.md" in shown.stdout, shown.stdout
        hot = run(root, "hot")
        assert hot.returncode == 0 and "WARNING 2 fact file(s)" in hot.stdout, hot.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hot_shows_unknown_status_record():
    root = fixture()
    try:
        make_fact(root)
        _write_fact(root, "typo-status.md", _raw_fact("typo-status", status="confirmd"))
        hot = run(root, "hot")
        assert hot.returncode == 0, hot.stderr
        assert "`fixture-fact`" in hot.stdout and "`typo-status`" in hot.stdout, hot.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hot_shows_record_without_status_line():
    root = fixture()
    try:
        raw = _raw_fact("no-status").replace("status: 확정\n", "")
        assert "status:" not in raw
        _write_fact(root, "no-status.md", raw)
        hot = run(root, "hot")
        assert hot.returncode == 0, hot.stderr
        assert "`no-status`" in hot.stdout, hot.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_find_status_either_language():
    root = fixture()
    try:
        make_fact(root)  # stored in the Korean status form
        for value in ("confirmed", "확정"):
            found = run(root, "find", "--status=" + value)
            assert found.returncode == 0 and "fixture-fact" in found.stdout, (value, found.stdout)
        for bad in (["--stauts=x"], ["--status", "확정"]):
            typo = run(root, "find", *bad)
            assert typo.returncode == 1, (bad, typo.stdout)
            assert "usage" in typo.stdout, typo.stdout
        _write_fact(root, "list-speaker.md",
                    _raw_fact("list-speaker").replace("speaker: owner", "speaker: [team]"))
        found = run(root, "find", "--speaker=tea")
        assert "list-speaker" in found.stdout, found.stdout
        # YAML lets an inline list quote its items; the quotes are not part of the tag.
        _write_fact(root, "quoted-tag.md", _raw_fact("quoted-tag").replace("tags: [fixture]", "tags: ['quoted', \"pair\"]"))
        found = run(root, "find", "--tag=pair")
        assert "quoted-tag" in found.stdout, found.stdout
        _write_fact(root, "plain.md", "no front matter here\n")
        found = run(root, "find", "claim")
        assert "[find] WARNING 1 fact file(s)" in found.stdout, found.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_audit_empty_origin_is_missing():
    root = fixture()
    try:
        make_fact(root)
        _write_fact(root, "no-origin.md", _raw_fact("no-origin", origin="", via=False))
        audited = run(root, "audit", "no-origin")
        assert audited.returncode == 0, audited.stdout + audited.stderr
        chain = [line for line in audited.stdout.splitlines() if "origin" in line and "[" in line]
        assert chain and not any("[✓] " in line and "this record" not in line for line in chain), \
            audited.stdout
        assert "✗ missing" in audited.stdout, audited.stdout
        _write_fact(root, "no-kind.md", _raw_fact("no-kind").replace("origin_kind: document\n", ""))
        audited = run(root, "audit", "no-kind")
        assert "origin kind: ✗ missing" in audited.stdout, audited.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_flags_missing_origin_and_broken_link():
    root = fixture()
    try:
        make_fact(root)
        path = os.path.join(root, FACTS_REL, "fixture-fact.md")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\nSee [[missing-id]].\n")
        os.remove(os.path.join(root, "sources", "origin.txt"))
        checked = run(root, "check")
        assert checked.returncode == 1, checked.stdout
        problems = _problems(checked)
        assert sum("path missing" in p and "sources/origin.txt" in p for p in problems) == 1, problems
        assert any("[[missing-id]]" in p for p in problems), problems
        audited = run(root, "audit", "fixture-fact")
        assert "[✗ missing] sources/origin.txt" in audited.stdout, audited.stdout
        assert "origin gap: none" not in audited.stdout, audited.stdout
        # A directory is not evidence, and an existing derived step must not certify a lost origin.
        with open(os.path.join(root, "summary.md"), "w", encoding="utf-8") as f:
            f.write("summary\n")
        _write_fact(root, "dir-origin.md", _raw_fact("dir-origin", origin="."))
        _write_fact(root, "lost-origin.md", _raw_fact("lost-origin", origin="lost.md").replace(
            "  - lost.md", "  - summary.md"))
        problems = _problems(run(root, "check"))
        assert any("dir-origin" in p and "path missing" in p for p in problems), problems
        audited = run(root, "audit", "lost-origin")
        assert "[✗ missing] lost.md" in audited.stdout, audited.stdout
        assert "[✓] summary.md" in audited.stdout, audited.stdout
        assert "origin gap: none" not in audited.stdout, audited.stdout
        assert "[✓] ." not in run(root, "audit", "dir-origin").stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _snapshot_dirs(root):
    snaps = os.path.join(root, "_private", "ledger", ".snapshots")
    return sorted(d for d in os.listdir(snaps) if os.path.isdir(os.path.join(snaps, d)))


def test_snapshot_tracks_side_files():
    root = fixture()
    try:
        make_fact(root)
        first = run(root, "snapshot")
        assert first.returncode == 0 and len(_snapshot_dirs(root)) == 1, first.stdout + first.stderr
        same = run(root, "snapshot")
        assert "unchanged" in same.stdout and len(_snapshot_dirs(root)) == 1, same.stdout
        with open(os.path.join(root, "_private", "ledger", "README.md"), "w", encoding="utf-8") as f:
            f.write("ledger notes\n")
        second = run(root, "snapshot")
        assert second.returncode == 0 and len(_snapshot_dirs(root)) == 2, second.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # In process: an edit during the copy, then a same-second publish by another session.
    import contextlib, io
    sys.path.insert(0, HERE)
    import facts
    root = fixture()
    saved = facts.ROOT, facts.LEDGER, facts.FACTS
    try:
        make_fact(root, "Morning")
        facts.ROOT, facts.LEDGER = root, os.path.join(root, "_private", "ledger")
        facts.FACTS = os.path.join(facts.LEDGER, "facts")
        fact = os.path.join(facts.FACTS, "fixture-fact.md")
        before = open(fact, "rb").read()
        killed = os.path.join(facts.LEDGER, ".snapshots", ".stage-killed")
        os.makedirs(killed)
        os.utime(killed, (0, 0))   # a stage left by a run killed long ago is pruned with the ring
        copytree, rename = shutil.copytree, os.rename

        def edited_during_copy(src, dst, *args, **kwargs):
            # Evening exists only while the copy is made: only a hash of the copy names it right.
            open(fact, "wb").write(before.replace(b"Morning", b"Evening"))
            try:
                return copytree(src, dst, *args, **kwargs)
            finally:
                open(fact, "wb").write(before)

        def other_session_first(src, dst):
            copytree(src, dst)
            return rename(src, dst)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            shutil.copytree = edited_during_copy
            try:
                facts.cmd_snapshot()
            finally:
                shutil.copytree = copytree
            assert facts.cmd_snapshot() == 0
            open(fact, "ab").write(b"more\n")
            facts.os.rename = other_session_first
            try:
                assert facts.cmd_snapshot() == 0
            finally:
                facts.os.rename = rename
        # The restored Morning text is a new snapshot, not "unchanged", and the race did not crash.
        assert "unchanged" not in out.getvalue(), out.getvalue()
        assert len(_snapshot_dirs(root)) == 3, (_snapshot_dirs(root), out.getvalue())
        assert not [d for d in os.listdir(os.path.join(facts.LEDGER, ".snapshots")) if d.startswith(".")]
    finally:
        facts.ROOT, facts.LEDGER, facts.FACTS = saved
        shutil.rmtree(root, ignore_errors=True)


def test_hot_renders_when_snapshot_fails():
    root = fixture()
    snaps = os.path.join(root, "_private", "ledger", ".snapshots")
    try:
        make_fact(root, "스냅샷 실패에도 보일 주장")
        os.makedirs(snaps)
        os.chmod(snaps, 0o555)
        hot = run(root, "hot")
        assert hot.returncode == 0, hot.stdout + hot.stderr
        assert "Traceback" not in hot.stderr, hot.stderr
        hotset = os.path.join(root, "_private", "ledger", "hotset.md")
        assert "스냅샷 실패에도 보일 주장" in open(hotset, encoding="utf-8").read()
    finally:
        if os.path.isdir(snaps):
            os.chmod(snaps, 0o755)
        shutil.rmtree(root, ignore_errors=True)


def test_new_refuses_quote_in_claim():
    root = fixture()
    try:
        for value in ('--claim=he said "yes"', "--claim=line one\nline two",
                      "--claim=first\rsecond", "--claim=first\u2028second",
                      "--claim=trailing\n", "--claim=\n", "--claim=abc\r\n",
                      os.fsdecode(b"--claim=caf\x85")):
            result = run(root, "new", "q", value)
            assert result.returncode == 1, result.stdout
            assert "Traceback" not in result.stderr, result.stderr
            # The refusal message starts with the field; the usage line does not.
            assert result.stdout.startswith("[new] --claim"), result.stdout
            assert not os.path.exists(os.path.join(root, FACTS_REL, "q.md"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_new_rejects_unparsed_argument():
    root = fixture()
    try:
        for rid, extra in (("x", ["--claim", "text"]), ("x", ["--colour=red"]), ("x\n", [])):
            result = run(root, "new", rid, *extra)
            assert result.returncode == 1, (rid, extra, result.stdout)
            # A trailing newline in the id is refused by name rather than by the usage line.
            assert ("usage" if extra else "x") in result.stdout, result.stdout
            facts = os.path.join(root, FACTS_REL)
            assert not os.path.isdir(facts) or not os.listdir(facts), os.listdir(facts)
        os.makedirs(os.path.join(root, FACTS_REL))
        for cmd in ("show", "audit"):
            result = run(root, cmd)
            assert result.returncode == 1 and "usage" in result.stdout, (cmd, result.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_new_does_not_overwrite_a_concurrent_creation():
    """Another session creating the same id after the argument checks must not be overwritten."""
    import contextlib, io
    sys.path.insert(0, HERE)
    import facts
    root = fixture(facts=True)  # an existing directory keeps os.makedirs from recursing into the hook
    saved = facts.ROOT, facts.FACTS, facts.os.makedirs
    path = os.path.join(root, FACTS_REL, "same.md")

    def other_session_creates(*args, **kwargs):
        saved[2](*args, **kwargs)
        with open(path, "w", encoding="utf-8") as f:
            f.write("other session\n")

    facts.ROOT, facts.FACTS, facts.os.makedirs = root, os.path.join(root, FACTS_REL), other_session_creates
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = facts.cmd_new(["same", "--claim=this session"])
        assert rc == 1 and "same.md" in out.getvalue(), out.getvalue()
        assert open(path, encoding="utf-8").read() == "other session\n"
    finally:
        facts.ROOT, facts.FACTS, facts.os.makedirs = saved
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_check_rejects_scaffold_todos,
    test_malformed_record_is_reported_not_crashed,
    test_check_reports_unparsable_record,
    test_hot_shows_unknown_status_record,
    test_hot_shows_record_without_status_line,
    test_find_status_either_language,
    test_audit_empty_origin_is_missing,
    test_check_flags_missing_origin_and_broken_link,
    test_snapshot_tracks_side_files,
    test_hot_renders_when_snapshot_fails,
    test_new_refuses_quote_in_claim,
    test_new_rejects_unparsed_argument,
    test_new_does_not_overwrite_a_concurrent_creation,
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
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"facts: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
