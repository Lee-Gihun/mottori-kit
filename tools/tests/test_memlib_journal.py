#!/usr/bin/env python3
"""Generated boundary tests for journal parsing and config validation."""
import contextlib
import copy
import dataclasses
import datetime
import os
import random
import tempfile
from unittest import mock

import sys
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config  # noqa: E402
import journal  # noqa: E402
import now  # noqa: E402
import runlog  # noqa: E402
import safeio  # noqa: E402


SEED = 0x6D656D
RNG = random.Random(SEED)
CUTOFF = datetime.datetime.fromisoformat("2026-02-01T00:00:00+09:00")


@dataclasses.dataclass(frozen=True)
class JournalCase:
    name: str
    files: dict
    strict_expect: str
    nonstrict_expect: str
    rows: tuple = ()
    visibility: str = None


@dataclasses.dataclass(frozen=True)
class ConfigCase:
    name: str
    data: dict
    expect: str


def event(ts, track="system", kind="state", body="ok", ending="\n"):
    return f"- {ts} [{track}/{kind}] {body}{ending}"


def jf(text, month="2026-01", physical="public"):
    return {f"{physical}/journal-{month}.md": text.encode("utf-8")}


def journal_cases():
    """Return deterministic generated cases with an explicit per-mode oracle."""
    cases = []
    valid_timestamps = (
        "2026-01-15T08:31:22+09:00",
        "2026-01-15T08:31:22+0900",
        "2026-01-15T08:31+09:00",
    )
    for i in range(20):
        ts = RNG.choice(valid_timestamps)
        body = f"valid-{i}-{RNG.randrange(1_000_000)}"
        cases.append(JournalCase(
            f"valid timestamp {i}", jf(event(ts, body=body)), "accept", "accept",
            ((body, "public"),)))

    for i in range(20):
        ts = f"2026-01-{RNG.randrange(1, 29):02d}T08:31:{RNG.randrange(60):02d}"
        cases.append(JournalCase(
            f"timezone missing {i}", jf(event(ts, body=f"naive-{i}")),
            "reject", "warning"))

    for i in range(20):
        body = f"zulu-{i}"
        cases.append(JournalCase(
            f"Z timezone outside journal grammar {i}",
            jf(event(f"2026-01-{i % 20 + 1:02d}T08:31:22Z", body=body)),
            "reject", "warning"))

    for i in range(20):
        body = f"bom-{i}"
        cases.append(JournalCase(
            f"utf8 BOM {i}", jf("\ufeff" + event("2026-01-15T08:31:22+09:00", body=body)),
            "reject", "warning"))

    for i in range(20):
        body = f"crlf-{i}"
        text = "# journal\r\n\r\n" + event(
            "2026-01-15T08:31:22+09:00", body=body, ending="\r\n")
        cases.append(JournalCase(
            f"CRLF {i}", jf(text), "accept", "accept", ((body, "public"),)))

    for i in range(20):
        body = f"unterminated-{i}"
        cases.append(JournalCase(
            f"missing final newline {i}",
            jf(event("2026-01-15T08:31:22+09:00", body=body, ending="")),
            "reject", "warning", ((body, "public"),)))

    for i in range(20):
        text = "" if i % 2 else "\n\n# comment\n\n"
        cases.append(JournalCase(
            f"empty blank comments {i}", jf(text), "accept", "accept"))

    for i in range(20):
        body = chr(ord("a") + i % 26) * (301 + RNG.randrange(40))
        cases.append(JournalCase(
            f"body over 300 {i}",
            jf(event("2026-01-15T08:31:22+09:00", body=body)),
            "reject", "warning"))

    for i in range(20):
        kind = f"unknown{RNG.randrange(1000)}"
        cases.append(JournalCase(
            f"unknown type {i}",
            jf(event("2026-01-15T08:31:22+09:00", kind=kind, body=f"type-{i}")),
            "reject", "warning"))

    for i in range(20):
        track = f"bad track {RNG.randrange(1000)}"
        cases.append(JournalCase(
            f"track whitespace {i}",
            jf(event("2026-01-15T08:31:22+09:00", track=track, body=f"space-{i}")),
            "reject", "warning"))

    for i in range(20):
        accepted = i % 2 == 0
        track = "공유" if accepted else RNG.choice(("共有", "研究", "공유🚦"))
        body = f"unicode-{i}"
        cases.append(JournalCase(
            f"unicode track {i}",
            jf(event("2026-02-15T08:31:22+09:00", track=track, body=body), "2026-02"),
            "accept" if accepted else "reject",
            "accept" if accepted else "warning",
            ((body, "public"),) if accepted else ()))

    for i in range(20):
        first, second = f"same-a-{i}", f"same-b-{i}"
        text = event("2026-01-15T08:31:22+09:00", body=first)
        text += event("2026-01-15T08:31:22+09:00", body=second)
        cases.append(JournalCase(
            f"stable equal timestamp {i}", jf(text), "accept", "accept",
            ((first, "public"), (second, "public"))))

    # Cross-file ordering, cutoff equality and one-second neighbors, and physical routing.
    cases.extend((
        JournalCase(
            "two month files sort chronologically",
            {
                "public/journal-2026-02.md": event(
                    "2026-02-01T00:00:01+09:00", body="feb").encode(),
                "public/journal-2026-01.md": event(
                    "2026-01-31T23:59:59+09:00", body="jan").encode(),
            }, "accept", "accept", (("jan", "public"), ("feb", "public"))),
        JournalCase(
            "mixed offset spellings keep equal instant source order",
            jf(
                event("2026-02-02T08:00:00+09:00", body="first-colon")
                + event("2026-02-02T08:00:00+0900", body="second-compact"),
                "2026-02"),
            "accept", "accept", (("first-colon", "public"), ("second-compact", "public"))),
        JournalCase(
            "aware datetimes sort by instant across month files",
            {
                "public/journal-2026-01.md": event(
                    "2026-01-31T23:30:00+08:00", body="later-instant").encode(),
                "public/journal-2026-02.md": event(
                    "2026-02-01T00:00:00+09:00", body="earlier-instant").encode(),
            }, "accept", "accept", (("earlier-instant", "public"), ("later-instant", "public"))),
        JournalCase(
            "legacy cutoff one second before",
            jf(event("2026-01-31T23:59:59+09:00", track="research", body="before")),
            "accept", "accept", (("before", "private"),)),
        JournalCase(
            "legacy cutoff exact second",
            jf(event("2026-02-01T00:00:00+09:00", track="research", body="exact"), "2026-02"),
            "accept", "accept", (("exact", "private"),)),
        JournalCase(
            "legacy cutoff one second after",
            jf(event("2026-02-01T00:00:01+09:00", track="research", body="after"), "2026-02"),
            "accept", "accept", (("after", "public"),)),
        JournalCase(
            "legacy public track at cutoff",
            jf(event("2026-02-01T00:00:00+09:00", track="system", body="legacy-public"), "2026-02"),
            "accept", "accept", (("legacy-public", "public"),)),
        JournalCase(
            "private physical journal stays private",
            jf(event("2026-02-02T00:00:00+09:00", track="system", body="forced-private"),
               "2026-02", "private"),
            "accept", "accept", (("forced-private", "private"),)),
        JournalCase(
            "public projection filter",
            jf(event("2026-02-02T00:00:00+09:00", track="research", body="public-only"),
               "2026-02"),
            "accept", "accept", (("public-only", "public"),), "public"),
        JournalCase(
            "private projection filter excludes public",
            jf(event("2026-02-02T00:00:00+09:00", track="research", body="excluded"),
               "2026-02"),
            "accept", "accept", (), "private"),
    ))
    return cases


# Case files name the folder of each journal: public is state/, private is _private/state/.
FOLDERS = {"public": "state", "private": os.path.join("_private", "state")}


@contextlib.contextmanager
def _instance(root, **policy):
    """Point every path at root and answer each named config reader with the given value."""
    saved = os.environ.get("MOTTORI_INSTANCE")
    os.environ["MOTTORI_INSTANCE"] = root
    try:
        with contextlib.ExitStack() as stack:
            for name, value in policy.items():
                stack.enter_context(mock.patch.object(config, name, lambda v=value: v))
            yield
    finally:
        if saved is None:
            os.environ.pop("MOTTORI_INSTANCE", None)
        else:
            os.environ["MOTTORI_INSTANCE"] = saved


def _write_case(root, files):
    for relative, payload in files.items():
        side, _, name = relative.partition("/")
        path = os.path.join(root, FOLDERS[side], name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(payload)


def _run_journal_case(case):
    with tempfile.TemporaryDirectory() as td, _instance(
            td, public_journal_tracks=("system", "research", "공유"),
            legacy_public_tracks=("system",), legacy_cutoff=CUTOFF):
        _write_case(td, case.files)
        errors = []
        rows = journal.parse_journal(visibility=case.visibility, strict=False, errors=errors)
        actual_nonstrict = "warning" if errors else "accept"
        assert actual_nonstrict == case.nonstrict_expect, (
            case.name, "non-strict", actual_nonstrict, case.nonstrict_expect, errors)
        assert tuple((row["body"], row["visibility"]) for row in rows) == case.rows, (
            case.name, [(row["body"], row["visibility"]) for row in rows], case.rows)

        try:
            strict_rows = journal.parse_journal(visibility=case.visibility, strict=True)
        except ValueError:
            actual_strict = "reject"
            strict_rows = None
        else:
            actual_strict = "accept"
        assert actual_strict == case.strict_expect, (
            case.name, "strict", actual_strict, case.strict_expect)
        if strict_rows is not None:
            assert tuple((row["body"], row["visibility"]) for row in strict_rows) == case.rows


def test_journal_body_exact_boundary():
    """The documented limit is inclusive at 300, and a body is one line by the reader's rule."""
    prefix = "- 2026-01-15T08:31:22+09:00 [system/state] "
    assert journal.validate_line(prefix + ("x" * 300)) is None
    error = journal.validate_line(prefix + ("x" * 301))
    assert error is not None and "300" in error
    # The reader splits at U+2028; a body holding one would be cut, so the writer refuses it.
    error = journal.validate_line(prefix + "Proceed only\u2028after approval")
    assert error is not None and "2028" in error, error
    # Digits are allowed in a track; a refusal names the part and the allowed characters.
    assert journal.validate_line("- 2026-01-15T08:31:22+09:00 [q4/decision] ship") is None
    error = journal.validate_line("- 2026-01-15T08:31:22+09:00 [Q4/decision] ship")
    assert "'Q4'" in error and "0-9" in error, error
    error = journal.validate_line("- 2026-01-15T08:31:22+09:00 [q4/Decision] ship")
    assert "'Decision'" in error and "decision" in error, error


def valid_config():
    return {
        "schema_version": 4,
        "instance": {
            "name": "fixture",
        },
        "tracks": [{"key": "work", "name": "Work", "canonical": "work/NOW.md"}],
        "journal_visibility": {
            "public_tracks": ["system"],
            "legacy_cutoff": None,
            "legacy_public_tracks": [],
        },
        "threads": [],
    }


def config_cases():
    """Generate more than 30 malformed configs plus valid boundary controls."""
    cases = []
    for i in range(8):
        cfg = valid_config()
        cfg["schema_version"] = bool(i % 2)
        cfg["case_nonce"] = RNG.randrange(1_000_000)
        cases.append(ConfigCase(f"bool schema_version {i}", cfg, "reject"))

    bad_track_dicts = ({}, {"key": "x"}, {"0": {}}, {"items": []})
    for i in range(8):
        cfg = valid_config()
        cfg["tracks"] = copy.deepcopy(RNG.choice(bad_track_dicts))
        cfg["case_nonce"] = RNG.randrange(1_000_000)
        cases.append(ConfigCase(f"tracks object {i}", cfg, "reject"))

    absolute_paths = (
        "/etc/passwd", "//server/share", os.path.join(os.sep, "tmp", "x"), "/var/db/config",
    )
    escaping_paths = ("../secret.md", "work/../secret.md", "a/b/../../secret", "..\\secret.md")
    # Every listed value is tested; a random draw left some never exercised.
    for i, path in enumerate(absolute_paths + escaping_paths):
        cfg = valid_config()
        cfg["tracks"][0]["canonical"] = path
        cfg["case_nonce"] = RNG.randrange(1_000_000)
        cases.append(ConfigCase(f"unsafe canonical {i}", cfg, "reject"))

    # Names the journal row pattern refuses only warn, because the previous release accepted them;
    # the keys schema 4 needs to route rows still fail.
    def named(label, change, expect):
        cfg = valid_config()
        change(cfg)
        cases.append(ConfigCase(label, cfg, expect))
    named("track key with a space", lambda c: c["tracks"][0].update(key="Bad Key"), "accept")
    named("upper-case public track", lambda c: c["journal_visibility"].update(public_tracks=["API"]), "accept")
    named("upper-case journal type", lambda c: c.update(journal_types=["decision", "Big"]), "accept")
    named("schema 4 without public_tracks", lambda c: c["journal_visibility"].pop("public_tracks"), "reject")
    # null is "no list": every track is ordinary. Anything else that is not a list is an error.
    named("null public_tracks", lambda c: c["journal_visibility"].update(public_tracks=None), "accept")
    named("public_tracks as one string", lambda c: c["journal_visibility"].update(public_tracks="system"), "reject")
    named("null legacy_public_tracks", lambda c: c["journal_visibility"].update(legacy_public_tracks=None), "reject")
    named("digit track key", lambda c: (c["tracks"][0].update(key="q4"),
                                        c["journal_visibility"].update(public_tracks=["v2"])), "accept")
    named("worker settings", lambda c: c.update(workers={
        "claude": {"model": "opus", "effort": "max"}, "codex": {"where": "copy"},
        "gemini": {"web_in_instance": True, "_note": "x"}, "_note": "x"}), "accept")
    for label, workers in (("worker list", []), ("unknown worker runtime", {"nosuch": {}}),
                           ("worker where elsewhere", {"codex": {"where": "home"}}),
                           ("worker switch as text", {"gemini": {"web_in_instance": "yes"}}),
                           ("worker effort with capitals", {"codex": {"effort": "High"}}),
                           ("unknown worker key", {"claude": {"modle": "opus"}})):
        named(label, lambda c, w=workers: c.update(workers=w), "reject")

    return cases


def _run_config_case(case):
    try:
        config.validate(case.data)
    except ValueError:
        actual = "reject"
    else:
        actual = "accept"
    assert actual == case.expect, (case.name, actual, case.expect)


def _visibility_contract_on_fixture():
    """Test visibility from the configured allowlist in a temporary instance.

    Use template configuration in the kit and current configuration in an installed instance."""
    import json
    import subprocess
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.dirname(here)
    source = next(p for p in (os.path.join(root, "templates", "config.json"),
                              os.path.join(root, "instance", "config.json"))
                  if os.path.isfile(p))
    with tempfile.TemporaryDirectory(prefix="journal-visibility-") as fixture:
        os.makedirs(os.path.join(fixture, "instance"))
        os.makedirs(os.path.join(fixture, "state"))
        config = json.load(open(source, encoding="utf-8"))
        config.setdefault("journal_visibility", {})["public_tracks"] = ["system"]
        with open(os.path.join(fixture, "instance", "config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
        code = ("import journal as J; print(J.journal_visibility('system'), "
                "J.journal_visibility('not-listed'), J.journal_visibility('system', force_private=True))")
        env = dict(os.environ, MOTTORI_INSTANCE=fixture)
        r = subprocess.run([sys.executable, "-c", code], cwd=os.path.join(here, "lib"), env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.split() == ["public", "private", "private"], r.stdout


def test_state_tokens_are_english_and_old_korean_forms_are_read():
    """Writers emit the English state tokens; readers also accept the Korean forms older files carry."""
    assert all(isinstance(text, str) and text and text.isascii() or name == "compaction_tail"
               for name, text in now.STATE_TOKENS.items()), now.STATE_TOKENS
    assert now.token("compaction") == "compaction occurred"
    old_korean = {
        "compaction": "컴팩션 발생",
        "compaction_tail": " — 이후 컨텍스트는 요약본",
        "generated_notice": "*생성 ",
    }
    assert now.LEGACY_TOKEN_FORMS == old_korean, now.LEGACY_TOKEN_FORMS
    for name, korean in old_korean.items():
        assert now.token_forms(name) == (now.STATE_TOKENS[name], korean), name
    assert journal.RETROACTIVE == "(retroactive)"
    assert now.UPDATED_LABELS["ko"] == ("마지막 갱신", "마지막 업데이트", "마지막 정비")
    for line in ("*마지막 갱신: 11/02 note*", "Last updated: 11/02 note", "마지막 정비：11/02 note"):
        assert now.UPDATED_RE.search(line).group(2).startswith("11/02"), line
    assert journal.LINE.match("- 2026-01-01T00:00:00+09:00 [잡/state] Korean track key")


def _fixture_config(cfg, code, env=None, private_threads=None, alone=False):
    """Import config in a temporary instance and return the JSON that code prints.

    alone=True copies config.py and the paths.py and safeio.py it imports, the way sync targets
    and hook fixtures do.
    """
    import json
    import shutil
    import subprocess
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory(prefix="config-fixture-") as root:
        os.makedirs(os.path.join(root, "instance"))
        os.makedirs(os.path.join(root, "tools", "lib"))
        with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        if private_threads is not None:
            os.makedirs(os.path.join(root, "_private", "state"))
            with open(os.path.join(root, "_private", "state", "threads.json"), "w",
                      encoding="utf-8") as f:
                json.dump(private_threads, f)
        for name in ("lib/config.py", "lib/paths.py", "lib/safeio.py"):
            shutil.copy(os.path.join(here, name), os.path.join(root, "tools", name))
        tools = os.path.join(root, "tools") if alone else here
        run_env = {k: v for k, v in os.environ.items()
                   if k != "PYTHONPATH"}
        run_env.update({"MOTTORI_INSTANCE": root, "HOME": root})
        run_env.update({k: v.replace("{ROOT}", root) for k, v in (env or {}).items()})
        prog = (f"import sys, json; sys.path.insert(0, {os.path.join(tools, 'lib')!r}); "
                f"sys.path.insert(0, {os.path.join(root, 'tools', 'lib')!r}); import config as C, paths as P; " + code)
        r = subprocess.run([sys.executable, "-I", "-c", prog], capture_output=True, text=True,
                           env=run_env, cwd=root)
        assert r.returncode == 0, r.stderr[-800:]
        return json.loads(r.stdout.strip().splitlines()[-1])


def test_root_aliases_shape_fails_closed():
    probe = "print(json.dumps([C.load_ok(), C.root_aliases()]))"
    for bad in ([1], "/old", [""]):
        ok, aliases = _fixture_config({"instance": {"root_aliases": bad}}, probe)
        assert ok is False and aliases == [], (bad, ok, aliases)
    # The optional list by meaning is checked where it is used; a slip there keeps the rest.
    for bad in ({"endpoint": "http://127.0.0.1:1/v1/embeddings"},
                {"endpoint": "x", "model": "m", "query_prefix": 1}, "http://127.0.0.1:1/x"):
        ok, aliases = _fixture_config({"instance": {"root_aliases": ["/old"],
                                                    "recall_meaning": bad}}, probe)
        assert ok is True and aliases == ["/old"], (bad, ok, aliases)
    meaning = {"endpoint": "http://127.0.0.1:1/v1/embeddings", "model": "m"}
    ok, read = _fixture_config({"instance": {"recall_meaning": meaning}},
                               "print(json.dumps([C.load_ok(), C.instance().get('recall_meaning')]))")
    assert ok is True and read == meaning, (ok, read)
    # A key an older setup wrote is ignored: the starter documents' language, the work or
    # personal context, the list of remotes.
    ok, aliases = _fixture_config({"instance": {"root_aliases": ["/old"], "lang": "ko",
                                                "context": "client", "remote_allowlist": "x"}}, probe)
    assert ok is True and aliases == ["/old"], (ok, aliases)


def test_an_empty_deny_list_loads():
    """An empty list is a choice, not a broken config: the copy still leaves out _private/."""
    ok, deny = _fixture_config(
        {"egress": {"model_send": {"deny_prefixes": []}}},
        "print(json.dumps([C.load_ok(), C.egress_model_send()['deny_prefixes']]))")
    assert ok is True and deny == [], (ok, deny)


def test_parse_journal_reports_invalid_utf8():
    with tempfile.TemporaryDirectory() as td, _instance(td):
        _write_case(td, {"public/journal-2026-01.md":
                         b"- 2026-01-15T08:31:22+09:00 [system/state] bad \xff byte\n"})
        errors = []
        rows = journal.parse_journal(errors=errors)
        assert rows == [] and len(errors) == 1 and "journal-2026-01.md" in errors[0], errors
        try:
            journal.parse_journal(strict=True)
        except ValueError as e:
            assert "journal-2026-01.md" in str(e), e
        else:
            raise AssertionError("strict parse accepted invalid UTF-8")
        # One session start parses and fingerprints each journal several times: an unchanged
        # file is opened once, and a write makes the next read see the new bytes.
        path = os.path.join(td, "state", "journal-2026-01.md")
        with open(path, "wb") as f:
            f.write(b"- 2026-01-15T08:31:22+09:00 [system/state] first\n")
        import builtins
        from unittest import mock
        with mock.patch("builtins.open", wraps=builtins.open) as opened:
            for _ in range(3):
                journal.parse_journal()
                journal.journal_bytes(path)
        assert opened.call_count == 1, opened.call_count
        with open(path, "ab") as f:
            f.write(b"- 2026-01-15T08:32:22+09:00 [system/state] second\n")
        assert [row["body"] for row in journal.parse_journal()] == ["first", "second"]


def test_clip_keeps_complete_tail_line():
    text = "HEAD\n" + "y" * 1000 + "\n" + "z" * 60 + "\n"
    marker = f"\n\n[… middle cut: original {len(text.encode('utf-8'))} bytes …]\n\n"
    # room 105 gives the head 44 bytes and the tail exactly 61, which starts on the 'z' line.
    budget = len(marker.encode("utf-8")) + 105
    out = now.clip_utf8(text, budget)
    assert len(out.encode("utf-8")) <= budget, len(out.encode("utf-8"))
    assert out.rstrip().endswith("z" * 60), out


def test_legacy_cutoff_accepts_z():
    ok, offset = _fixture_config(
        {"schema_version": 4, "journal_visibility": {
            "public_tracks": ["system"], "legacy_public_tracks": ["system"],
            "legacy_cutoff": "2026-08-27T00:00:00Z"}},
        "print(json.dumps([C.load_ok(), "
        "C.legacy_cutoff().utcoffset().total_seconds() if C.legacy_cutoff() else None]))")
    assert ok is True and offset == 0, (ok, offset)
    # Python 3.9 fromisoformat rejects each of these; the journal grammar or a transcript emits them.
    utc = datetime.timezone.utc
    for text, want in (
            ("2026-11-20T09:19:15.123456789Z", datetime.datetime(2026, 11, 20, 9, 19, 15, 123456, utc)),
            ("2026-11-20T09:19:15.5Z", datetime.datetime(2026, 11, 20, 9, 19, 15, 500000, utc)),
            ("2026-11-20T09:00:00+0900", datetime.datetime(2026, 11, 20, 0, 0, tzinfo=utc)),
            ("2026-11-20T09:00+09:00", datetime.datetime(2026, 11, 20, 0, 0, tzinfo=utc))):
        assert config.parse_timestamp(text) == want, (text, config.parse_timestamp(text))
    for text in ("2026-11-20T09:00:00", "2026-13-01T00:00:00Z", "2026-11-20T09:00:00.Z", "", None):
        assert config.parse_timestamp(text) is None, text


def test_tilde_instance_reads_its_config():
    # HOME is the fixture root, so ~ must resolve to it and its config must be the one read.
    same, ok, name = _fixture_config(
        {"instance": {"name": "tilde-fixture"}},
        "import os; print(json.dumps([P.instance_root() == os.environ['HOME'], C.load_ok(), "
        "C.instance().get('name')]))",
        env={"MOTTORI_INSTANCE": "~"}, alone=True)
    assert same is True and ok is True and name == "tilde-fixture", (same, ok, name)


def test_thread_dossier_must_be_relative():
    probe = "print(json.dumps([C.load_ok(), C.threads()]))"
    for bad in ("/etc/hosts", "../x", "a/../../x"):
        ok, _ = _fixture_config({"threads": [{"key": "t", "name": "T", "dossier": bad}]}, probe)
        assert ok is False, bad
    ok, threads = _fixture_config(
        {}, "print(json.dumps([C.private_threads_ok(), C.threads(), C.warnings()]))",
        private_threads=[{"key": "p", "name": "P", "dossier": "../outside.md"},
                         {"key": "q", "name": "Q", "dossier": "notes/q.md"}])[:2]
    assert ok is False and threads == [["q", "Q", "notes/q.md"]], (ok, threads)


def test_run_log_scope_roundtrip():
    saved = os.environ.pop("MOTTORI_INTERNAL_RUN", None)
    with tempfile.TemporaryDirectory() as td, _instance(td):
        os.makedirs(os.path.join(td, "state"))
        runs = os.path.join(td, "state", ".tool-runs.log")
        try:
            with open(runs, "w", encoding="utf-8") as f:
                f.write("old\trow\n" * (runlog.LOG_MAX_BYTES // 8 + 1))
            runlog.log_run("x", scope="abcdef1234567890", ok=True)
            with open(runs, "ab") as f:
                f.write(b"\xff\tx\tffffffffffff\t\tng\n")   # A stray byte must not crash readers.
            assert runlog.ran_at_head("x", "abcdef1234567890")
            assert runlog.last_run("x")[1] == "ffffffffffff"
            assert os.path.getsize(runs) <= runlog.LOG_MAX_BYTES   # The run log is bounded.
            # A render holding the state lock must not stall a Stop hook's run row or drop it.
            with journal.state_lock():
                runlog.log_run("under-state-lock", scope="c" * 12, ok=True)
            assert runlog.ran_at_head("under-state-lock", "c" * 12)
            # Another session appending during a trim waits for it, so the trim cannot replace
            # the file with a tail that misses the new line. Dropped bytes are raw bytes.
            import threading
            with open(runs, "wb") as f:
                f.write(b"\xff" * 100 + b"\n" + b"old\trow\n" * (runlog.LOG_MAX_BYTES // 8 + 1))
            real_write, other = safeio.atomic_write, []
            def trim_while_other_appends(path, data):
                if not other:
                    other.append(threading.Thread(
                        target=runlog.log_run, args=("writer-b", ""), kwargs={"scope": "b" * 12}))
                    other[0].start()
                    other[0].join(0.3)
                return real_write(path, data)
            safeio.atomic_write = trim_while_other_appends
            try:
                runlog.log_run("writer-a", scope="a" * 12)
            finally:
                safeio.atomic_write = real_write
            other[0].join()
            text = open(runs, encoding="utf-8").read()
            assert "writer-a" in text and "writer-b" in text, text[-200:]
            open(runs, "wb").write(b"\xff" * 600 + b"\n" + b"x" * 1000 + b"\n")
            assert runlog.trim_log(runs, 1200) == 1602 - os.path.getsize(runs)
        finally:
            if saved is not None:
                os.environ["MOTTORI_INTERNAL_RUN"] = saved


P057_TESTS = (test_root_aliases_shape_fails_closed, test_an_empty_deny_list_loads,
              test_parse_journal_reports_invalid_utf8, test_clip_keeps_complete_tail_line,
              test_legacy_cutoff_accepts_z, test_tilde_instance_reads_its_config,
              test_thread_dossier_must_be_relative, test_run_log_scope_roundtrip)


def test_new_private_files_are_owner_only():
    """A store the tools create in a private area must not be readable by other users of the
    machine; a public state file may be. An existing file keeps the mode it has."""
    old_mask = os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            private = os.path.join(tmp, "_private", "ledger", "hotset.md")
            public = os.path.join(tmp, "state", "NOW.md")
            marker = os.path.join(tmp, ".git", "mottori-work", "snapshot.json")
            for path in (private, public, marker):
                safeio.atomic_write(path, "x")
            mode = lambda path: os.stat(path).st_mode & 0o777
            assert mode(private) == 0o600 and mode(marker) == 0o600, (oct(mode(private)), oct(mode(marker)))
            assert mode(os.path.dirname(private)) == 0o700, oct(mode(os.path.dirname(private)))
            assert mode(public) == 0o644, oct(mode(public))
            os.chmod(public, 0o640)
            safeio.atomic_write(public, "y")
            assert mode(public) == 0o640, oct(mode(public))
            rows = os.path.join(tmp, "_private", "state", "journal-2026-11.md")
            with safeio.open_append(rows) as f:
                f.write("row\n")
            assert mode(rows) == 0o600, oct(mode(rows))
            with safeio.open_append(os.path.join(tmp, "state", "journal-2026-11.md")) as f:
                f.write("row\n")
            assert mode(os.path.join(tmp, "state", "journal-2026-11.md")) == 0o644
    finally:
        os.umask(old_mask)


def main():
    journals = journal_cases()
    configs = config_cases()
    assert len(journals) >= 200, len(journals)
    assert len([case for case in configs if case.expect == "reject"]) >= 30
    for case in journals:
        _run_journal_case(case)
    for case in configs:
        _run_config_case(case)
    test_journal_body_exact_boundary()
    test_state_tokens_are_english_and_old_korean_forms_are_read()
    test_new_private_files_are_owner_only()
    for test in P057_TESTS:
        test()
    _visibility_contract_on_fixture()
    print(f"PASS: journal {len(journals)} generated cases, config {len(configs)} cases, seed={SEED}")


if __name__ == "__main__":
    main()
