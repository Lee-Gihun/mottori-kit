#!/usr/bin/env python3
# Matrix coverage: tools/memlib.py
"""Generated boundary tests for journal parsing and config validation."""
import copy
import dataclasses
import datetime
import os
import random
import tempfile

from testlib import run_test

import memlib as M


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
            "equal instant with compact offset stays stable",
            jf(event("2026-02-02T08:00:00+09:00", body="colon"), "2026-02"),
            "accept", "accept", (("colon", "public"),)),
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


def _write_case(root, files):
    for relative, payload in files.items():
        path = os.path.join(root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(payload)


def _run_journal_case(case):
    old = (M.STATE, M.PRIVATE_STATE, M.PUBLIC_JOURNAL_TRACKS,
           M.LEGACY_PUBLIC_TRACKS, M.LEGACY_CUTOFF)
    with tempfile.TemporaryDirectory() as td:
        M.STATE = os.path.join(td, "public")
        M.PRIVATE_STATE = os.path.join(td, "private")
        M.PUBLIC_JOURNAL_TRACKS = ("system", "research", "공유")
        M.LEGACY_PUBLIC_TRACKS = ("system",)
        M.LEGACY_CUTOFF = CUTOFF
        _write_case(td, case.files)
        try:
            errors = []
            rows = M.parse_journal(visibility=case.visibility, strict=False, errors=errors)
            actual_nonstrict = "warning" if errors else "accept"
            assert actual_nonstrict == case.nonstrict_expect, (
                case.name, "non-strict", actual_nonstrict, case.nonstrict_expect, errors)
            assert tuple((row["body"], row["visibility"]) for row in rows) == case.rows, (
                case.name, [(row["body"], row["visibility"]) for row in rows], case.rows)

            try:
                strict_rows = M.parse_journal(visibility=case.visibility, strict=True)
            except ValueError:
                actual_strict = "reject"
                strict_rows = None
            else:
                actual_strict = "accept"
            assert actual_strict == case.strict_expect, (
                case.name, "strict", actual_strict, case.strict_expect)
            if strict_rows is not None:
                assert tuple((row["body"], row["visibility"]) for row in strict_rows) == case.rows
        finally:
            (M.STATE, M.PRIVATE_STATE, M.PUBLIC_JOURNAL_TRACKS,
             M.LEGACY_PUBLIC_TRACKS, M.LEGACY_CUTOFF) = old


def test_journal_body_exact_boundary():
    """The documented limit is inclusive at 300 and rejects the first byte past it."""
    prefix = "- 2026-01-15T08:31:22+09:00 [system/state] "
    assert M.validate_line(prefix + ("x" * 300)) is None
    error = M.validate_line(prefix + ("x" * 301))
    assert error is not None and "300" in error


def valid_config():
    return {
        "schema_version": 4,
        "instance": {
            "name": "fixture",
            "context": "work",
            "remote_allowlist": ["github.com/example/repo", "git@gitlab.com:team/repo.git"],
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
    for i in range(12):
        cfg = valid_config()
        cfg["tracks"][0]["canonical"] = RNG.choice(absolute_paths + escaping_paths)
        cfg["case_nonce"] = RNG.randrange(1_000_000)
        cases.append(ConfigCase(f"unsafe canonical {i}", cfg, "reject"))

    malformed_remotes = (
        "", "   ", "not a host", "https://", "ssh://", "@", ":repo",
        "host name/repo", "https://bad host/repo", "github..com/repo", "[broken", "?query",
    )
    for i in range(16):
        cfg = valid_config()
        cfg["instance"]["remote_allowlist"] = [RNG.choice(malformed_remotes)]
        cfg["case_nonce"] = RNG.randrange(1_000_000)
        cases.append(ConfigCase(f"non-host remote allowlist {i}", cfg, "reject"))

    valid_remotes = (
        "github.com", "github.com/example/repo", "https://github.com/example/repo.git",
        "ssh://git@gitlab.com/team/repo", "git@github.com:example/repo.git",
        "/srv/git/repo", "~/git/repo", "../local/repo",
    )
    for i, remote in enumerate(valid_remotes):
        cfg = valid_config()
        cfg["instance"]["remote_allowlist"] = [remote]
        cases.append(ConfigCase(f"valid remote control {i}", cfg, "accept"))
    return cases


def _run_config_case(case):
    try:
        M._validate_config_shape(case.data)
    except ValueError:
        actual = "reject"
    else:
        actual = "accept"
    assert actual == case.expect, (case.name, actual, case.expect)


def _visibility_contract_on_fixture():
    """public/private 판정은 config allowlist에서 나온다. 설치 전 킷(system/memory-config.json 없음)에서
    돌려도 같은 계약을 재야 하므로 template(킷) 또는 현재 config(인스턴스)로 임시 인스턴스를 만들어 잰다."""
    import json
    import subprocess
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    source = next(p for p in (os.path.join(root, "templates", "memory-config.json"),
                              os.path.join(root, "system", "memory-config.json"))
                  if os.path.isfile(p))
    with tempfile.TemporaryDirectory(prefix="memlib-visibility-") as fixture:
        os.makedirs(os.path.join(fixture, "system"))
        os.makedirs(os.path.join(fixture, "state"))
        config = json.load(open(source, encoding="utf-8"))
        config.setdefault("journal_visibility", {})["public_tracks"] = ["system"]
        with open(os.path.join(fixture, "system", "memory-config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
        code = ("import memlib as M; print(M.journal_visibility('system'), "
                "M.journal_visibility('not-listed'), M.journal_visibility('system', force_private=True))")
        env = dict(os.environ, MOTTORI_INSTANCE=fixture)
        r = subprocess.run([sys.executable, "-c", code], cwd=here, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.split() == ["public", "private", "private"], r.stdout


def main():
    journals = journal_cases()
    configs = config_cases()
    assert len(journals) >= 200, len(journals)
    assert len([case for case in configs if case.expect == "reject"]) >= 30
    for case in journals:
        _run_journal_case(case)
    for case in configs:
        _run_config_case(case)
    run_test(test_journal_body_exact_boundary, __file__)
    _visibility_contract_on_fixture()
    print(f"PASS: journal {len(journals)} generated cases, config {len(configs)} cases, seed={SEED}")


if __name__ == "__main__":
    run_test(main, __file__)
