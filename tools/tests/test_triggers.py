#!/usr/bin/env python3
"""Fixture tests for the trigger store CLI (tools/triggers.py)."""
import json
import os
import re
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent.parent
TRIGGERS = HERE / "triggers.py"


# The runs here stand for a real session; under a probe (a suite run by another check) the hook
# would print nothing.
os.environ.pop("MOTTORI_INTERNAL_RUN", None)
os.environ.pop("MOTTORI_HOOK_CANARY", None)


def _run(root, *args):
    env = dict(os.environ, MOTTORI_INSTANCE=str(root))
    return subprocess.run([sys.executable, str(TRIGGERS), *args], text=True,
                          capture_output=True, env=env)


def _fixture():
    root = Path(tempfile.mkdtemp(prefix="triggers-fixture-"))
    (root / "instance").mkdir()
    (root / "_private" / "work").mkdir(parents=True)
    return root


def _rows(root):
    path = root / "_private" / "triggers" / "triggers.jsonl"
    return {json.loads(l)["id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()}


def _state(row, day=None):
    """The state triggers.py reads from a stored row, on day (YYYY-MM-DD) or today."""
    sys.path.insert(0, str(TRIGGERS.parent))
    import datetime
    import triggers
    return triggers.state(row, datetime.date.fromisoformat(day) if day else None)


def _korean_config(root):
    """A config with Korean source patterns that also names the experiments table to scan."""
    (root / "instance" / "config.json").write_text(json.dumps({"triggers": {
        "experiments": "_private/work/experiments.md", "sources": {
        "experiments": {"closed_status": "완료|철회|종료"},
        "decisions": {"rereview_marker": "재판정", "cycles_later": "(\\d+)\\s*주기\\s*후"}}}},
        ensure_ascii=False), encoding="utf-8")


def test_add_due_fire_and_tier_boundary():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "date:2026-09-20", "--what", "send the minutes",
                 "--tier", "T2", "--source", "x.md:3", "--date", "2026-09-19")
        assert r.returncode == 0 and r.stdout.startswith("added tr-"), r
        tid = r.stdout.split()[1]
        r = _run(root, "add", "--when", "date:2026-09-20", "--what", "send the minutes",
                 "--tier", "T2", "--source", "x.md:3", "--date", "2026-09-19")
        assert r.stdout.startswith("exists"), "same when/what/source must be idempotent"
        r = _run(root, "due", "--date", "2026-09-19")
        assert r.stdout.strip() == "due 0", r.stdout
        r = _run(root, "due", "--date", "2026-09-21")
        assert "[T2 ask" in r.stdout and "draft only" in r.stdout and "due 1" in r.stdout, r.stdout
        r = _run(root, "claim", tid, "--holder", "owner")
        assert r.returncode == 0
        r = _run(root, "fire", tid, "--outcome", "sent by owner", "--date", "2026-09-21", "--holder", "owner")
        assert r.returncode == 0, r.stderr
        r = _run(root, "due", "--date", "2026-09-22")
        assert r.stdout.strip() == "due 0"
        store = root / "_private" / "triggers" / "triggers.jsonl"
        row = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
        assert row["fired"] == "2026-09-21" and row["outcome"] == "sent by owner"
        assert _state(row) == "fired"
        assert not {"tz", "privacy", "destination", "state"} & set(row), "unread fields are not stored"
        assert [e["event"] for e in row["history"]] == ["added", "claimed", "fired"]
        assert oct(store.stat().st_mode & 0o777) == "0o600"
        r = _run(root, "fire", tid, "--date", "2026-09-22")
        assert r.returncode == 2 and "already fired" in r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_read_only_commands_touch_nothing_on_a_fresh_root():
    root = _fixture()
    try:
        r = _run(root, "hook", "--date", "2026-09-19")
        assert r.returncode == 0 and r.stdout == ""
        r = _run(root, "due", "--date", "2026-09-19")
        assert r.stdout.strip() == "due 0"
        r = _run(root, "list")
        assert r.stdout.strip() == "total 0"
        assert not (root / "_private" / "triggers").exists(), "read-only commands must not create the store"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_invalid_inputs_exit_2():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "soon", "--what", "x")
        assert r.returncode == 2 and "when must be" in r.stderr
        r = _run(root, "add", "--when", "date:2026-13-01", "--what", "x")
        assert r.returncode == 2 and "YYYY-MM-DD" in r.stderr
        r = _run(root, "add", "--when", "event:", "--what", "x")
        assert r.returncode == 2
        r = _run(root, "fire", "tr-nope")
        assert r.returncode == 2 and "unknown trigger id" in r.stderr
        # Nothing reads a privacy or a destination, so add takes neither.
        for flag in ("--privacy", "--destination"):
            r = _run(root, "add", "--when", "date:2026-09-01", "--what", "x", flag, "private")
            assert r.returncode == 2 and "unrecognized arguments" in r.stderr, r
        assert not re.search("privacy|destination", _run(root, "add", "--help").stdout)
        r = _run(root, "add", "--when", "date:2026-13-01", "--what", "x")
        assert r.returncode == 2 and "date trigger needs YYYY-MM-DD" in r.stderr, r.stderr
        assert _run(root, "list").stdout.strip() == "total 0"
        # Dates and counts Python cannot hold are the tool's refusal, not a traceback.
        r = _run(root, "add", "--id", "v", "--when", "date:2026-09-01", "--what", "x", "--date", "2026-02-30")
        assert r.returncode == 2 and "--date needs a real date" in r.stderr, r
        assert _run(root, "add", "--id", "v", "--when", "date:2026-09-01", "--what", "x").returncode == 0
        r = _run(root, "sleep", "v", "--days", "99999999")
        assert r.returncode == 2 and "out of range" in r.stderr, r
        assert r.stderr == "triggers: a date or count is out of range\n", r
        r = _run(root, "due", "--limit", "-1")
        assert r.returncode == 2 and "--limit must be 0 or more" in r.stderr, r
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_limits_and_auto_sleep_after_ignores():
    root = _fixture()
    try:
        for i in range(7):
            r = _run(root, "add", "--when", "date:2026-09-01", "--what", f"item {i}", "--tier", "T0",
                     "--date", "2026-08-30")
            assert r.returncode == 0
        r = subprocess.run([sys.executable, str(TRIGGERS), "hook", "--date", "2026-09-19"], text=True,
                           capture_output=True, env=dict(os.environ, MOTTORI_INSTANCE=str(root),
                                                         MOTTORI_HOOK_CANARY="nonce"))
        assert r.returncode == 0 and r.stdout == "", "the hook canary run injects no reminders"
        r = _run(root, "hook", "--date", "2026-09-19")
        payload = json.loads(r.stdout)["hookSpecificOutput"]
        assert payload["hookEventName"] == "SessionStart"
        assert payload["additionalContext"].count("\n- [T0") == 5, payload["additionalContext"]
        seen = set(re.findall(r"item \d", payload["additionalContext"]))
        r = _run(root, "hook", "--date", "2026-09-19", "--format", "text")
        seen |= set(re.findall(r"item \d", r.stdout))
        assert len(seen) == 7, f"carry-over must show every due item within two sessions: {sorted(seen)}"
        # Showings count once per calendar day, so ignoring is measured across days.
        for day in range(20, 24):
            _run(root, "hook", "--date", f"2026-09-{day}")
            _run(root, "hook", "--date", f"2026-09-{day}")
        rows = [json.loads(l) for l in (root / "_private" / "triggers" / "triggers.jsonl")
                .read_text(encoding="utf-8").splitlines()]
        slept = [x for x in rows if x.get("slept_until")]
        assert slept and all(x["ignored"] == 1 and _state(x, "2026-09-23") == "asleep" for x in slept), rows
        assert all(e["event"] == "auto-sleep" for x in slept for e in x["history"][-1:])
        r = _run(root, "due", "--date", "2026-09-30")
        assert "due 5" in r.stdout, "auto sleep must expire after the sleep window"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_claim_lease_refuses_second_holder_and_due_stays_read_only():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "draft the minutes", "--date", "2026-08-30")
        tid = r.stdout.split()[1]
        r = _run(root, "claim", tid, "--minutes", "30", "--holder", "alice")
        assert r.returncode == 0 and r.stdout.startswith("leased ") and "by alice" in r.stdout, r
        r = _run(root, "claim", tid, "--minutes", "30", "--holder", "bob")
        assert r.returncode == 2 and "is leased by alice" in r.stderr
        r = _run(root, "claim", tid, "--minutes", "30", "--holder", "alice")
        assert r.returncode == 0, "the holder may renew its own lease"
        assert _run(root, "claim", tid).returncode == 2, "a lease under the shared default holder coordinates nothing"
        r = _run(root, "fire", tid, "--holder", "bob", "--date", "2026-09-19")
        assert r.returncode == 2 and "is leased by alice" in r.stderr
        r = _run(root, "sleep", tid, "--date", "2026-09-19")
        assert r.returncode == 2 and "is leased by alice" in r.stderr, "sleep must not hide a row a loop is handling"
        store = root / "_private" / "triggers" / "triggers.jsonl"
        before = store.read_bytes()
        r = _run(root, "due", "--date", "2026-09-19")
        assert "due 1" in r.stdout and "being handled by alice" in r.stdout, r.stdout
        assert store.read_bytes() == before, "due without --mark must never count as shown"
        for day in ("2026-09-17", "2026-09-18", "2026-09-19"):
            _run(root, "hook", "--date", day)      # shown reaches the ignore limit
        r = _run(root, "due", "--date", "2026-09-20")
        assert "due 0" in r.stdout, "a read-only due hides an about-to-sleep item"
        after = store.read_text(encoding="utf-8")
        assert json.loads(after.splitlines()[0])["slept_until"] is None, "read-only due must not write a sleep"
        r = _run(root, "fire", tid, "--holder", "alice", "--outcome", "done", "--date", "2026-09-19")
        assert r.returncode == 0, r.stderr
        r = _run(root, "claim", tid, "--holder", "alice")
        assert r.returncode == 2 and "already fired" in r.stderr
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "second item", "--date", "2026-08-30")
        r = _run(root, "hook", "--date", "2026-09-19", "--format", "text")
        assert r.stdout.startswith("[triggers due today]") and "second item" in r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scan_experiments_and_decision_rereviews():
    root = _fixture()
    try:
        (root / "_private" / "work" / "experiments.md").write_text(
            "# registry\n\n| ID | 실험 | 트리거 | 만기 | 재는 것 | 상태 | 판정 |\n|---|---|---|---|---|---|---|\n"
            "| X1 | pilot one | approval | 9/20 report | fill rate | 진행 중 | path |\n"
            "| X2 | no date | approval | after the next job | n | 트리거 대기 | path |\n"
            "| X3 | closed one | approval | 2026-09-10 | n | 완료 | path |\n"
            "| X4 | iso date | approval | 2026-10-04 | n | 적용 | path |\n", encoding="utf-8")
        (root / "instance" / "decisions.md").write_text(
            "### DR-901 first sample (2026-09-06 · active-pilot · 3주기 후 재판정)\n\n"
            "### DR-902 second sample (2026-09-07 · active-pilot · 9/20 재판정)\n\n"
            "### DR-903 third sample (2026-09-17 · active)\n", encoding="utf-8")
        _korean_config(root)
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 0, r.stderr
        assert "scan added 4 total 4" in r.stdout, r.stdout
        rows = _rows(root)
        assert rows["exp-X1"]["when"] == "date:2026-09-20" and rows["exp-X1"]["source"].endswith(":5")
        assert "exp-X2" not in rows and "exp-X3" not in rows
        assert rows["exp-X4"]["when"] == "date:2026-10-04"
        assert rows["rereview-DR-901"]["when"] == "date:2026-09-27", rows["rereview-DR-901"]
        assert rows["rereview-DR-902"]["when"] == "date:2026-09-20"
        assert "rereview-DR-903" not in rows
        r = _run(root, "scan", "--date", "2026-09-19")
        assert "scan added 0 total 4" in r.stdout, "scan must be idempotent"
        (root / "instance" / "config.json").write_text(json.dumps({"triggers": {"sources": {
            "decisions": {"cycles_later": "(unclosed"}}}}), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "not a valid regex" in r.stderr, r
        (root / "instance" / "config.json").write_text(json.dumps({"triggers": {"sources": {
            "decisions": {"cycles_later": "\\d+ cycles later"}}}}), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "needs a capture group" in r.stderr, r
        # A group that catches a word, or nothing, is the tool's refusal, not a traceback.
        for pattern in ("(\\w+)\\s*cycles?\\s*later", "(\\d+)? ?\\w* cycles? later"):
            (root / "instance" / "config.json").write_text(json.dumps({"triggers": {"sources": {
                "decisions": {"cycles_later": pattern}}}}), encoding="utf-8")
            with open(root / "instance" / "decisions.md", "a", encoding="utf-8") as f:
                f.write("### DR-909 worded count (2026-09-06 · re-review two cycles later)\n")
            r = _run(root, "scan", "--date", "2026-09-19")
            assert r.returncode == 2 and "not a number of cycles" in r.stderr, r
        (root / "instance" / "config.json").write_text(json.dumps({"triggers": {"sources": ["x"]}}), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "must be an object" in r.stderr, r
        (root / "instance" / "config.json").write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "top level must be an object" in r.stderr, r
        (root / "instance" / "config.json").write_text(json.dumps({"triggers": "x"}), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "triggers must be an object" in r.stderr, r
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_shown_counts_once_per_calendar_day():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "date:2026-11-18", "--what", "same day item", "--date", "2026-11-17")
        tid = r.stdout.split()[1]
        # Session start, resume, and compaction all run the hook; one day is one showing.
        for _ in range(6):
            r = _run(root, "hook", "--date", "2026-11-18", "--format", "text")
            assert "same day item" in r.stdout, r.stdout
        store = root / "_private" / "triggers" / "triggers.jsonl"
        row = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
        assert row["shown"] == 1 and _state(row, "2026-11-18") == "open", row
        for day in ("2026-11-19", "2026-11-20"):
            _run(root, "hook", "--date", day)
            _run(root, "hook", "--date", day)
        row = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
        assert row["shown"] == 3 and not row.get("slept_until"), row
        # A stuck holder of the store lock costs session start about a second and counts nothing.
        import fcntl
        with open(str(store) + ".lock", "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            before = store.read_bytes()
            r = subprocess.run([sys.executable, str(TRIGGERS), "hook", "--date", "2026-11-22", "--format", "text"],
                               text=True, capture_output=True, timeout=10,
                               env=dict(os.environ, MOTTORI_INSTANCE=str(root)))
            assert r.returncode == 0 and "run python3 tools/triggers.py due" in r.stdout, r
            assert "same day item" in _run(root, "list").stdout, "a reader takes no lock"
            assert store.read_bytes() == before
            # Any other writer waits for the lock instead of giving up, and says what it waits for.
            writer = subprocess.Popen([sys.executable, str(TRIGGERS), "add", "--when", "date:2027-01-01", "--what", "later"],
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      env=dict(os.environ, MOTTORI_INSTANCE=str(root)))
            assert "waiting for the trigger store" in writer.stderr.readline()
        out, _ = writer.communicate(timeout=10)
        assert writer.returncode == 0 and out.startswith("added "), out
        # A clock set back to a day already counted shows the row again without counting it.
        r = _run(root, "hook", "--date", "2026-11-19", "--format", "text")
        assert "same day item" in r.stdout, r.stdout
        row = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
        assert row["shown"] == 3 and row["last_shown"] == "2026-11-20" and _state(row, "2026-11-19") == "open", row
        r = _run(root, "hook", "--date", "2026-11-21", "--format", "text")
        assert r.stdout == "", "a fourth day without fire puts the trigger to sleep"
        row = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
        assert _state(row, "2026-11-21") == "asleep" and row["id"] == tid, row
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_fire_instruction_runs_as_written():
    root = _fixture()
    try:
        r = _run(root, "add", "--id", "t2", "--when", "date:2026-11-18", "--what", "x", "--date", "2026-11-17")
        assert r.returncode == 0, r.stderr
        r = _run(root, "hook", "--date", "2026-11-18", "--format", "text")
        line = [l for l in r.stdout.splitlines() if "fire" in l and "<id>" in l]
        assert len(line) == 1, r.stdout
        command = line[0].split("fire: ", 1)[1].split(" · sleep:")[0]
        command = command.replace("<id>", "t2").replace("'...'", "done")
        env = dict(os.environ, MOTTORI_INSTANCE=str(root))
        r = subprocess.run(command.replace("python3 tools/triggers.py",
                                           f"{shlex.quote(sys.executable)} {shlex.quote(str(TRIGGERS))}"),
                           shell=True, text=True, capture_output=True, env=env)
        assert r.returncode == 0 and "fired t2" in r.stdout, (command, r.stdout, r.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_add_refuses_when_kinds_that_never_fire():
    root = _fixture()
    try:
        for when in ("file_change:notes.md", "state:x", "event:deploy"):
            r = _run(root, "add", "--when", when, "--what", "x")
            assert r.returncode == 2 and "unknown when kind" in r.stderr, (when, r.stderr)
        assert not (root / "_private" / "triggers" / "triggers.jsonl").exists()
        # A stored row of such a kind (written by an older version) is an unreadable row: the hook
        # goes on and says so.
        store_dir = root / "_private" / "triggers"
        store_dir.mkdir(parents=True, exist_ok=True)
        (store_dir / "triggers.jsonl").write_text(json.dumps({
            "id": "old", "when": "event:x", "what": "legacy", "tier": "T0", "source": None,
            "state": "open", "created": "2026-09-01", "fired": None, "outcome": None, "shown": 0,
            "slept_until": None, "leased_until": None, "history": []}) + "\n", encoding="utf-8")
        r = _run(root, "hook", "--date", "2026-11-18", "--format", "text")
        assert r.returncode == 0 and "1 unreadable trigger row(s) skipped" in r.stdout, r
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_state_is_read_from_dates_not_stored():
    """A row's state follows its dates; a stored state field from an older version is ignored
    and dropped at the next save."""
    root = _fixture()
    try:
        store_dir = root / "_private" / "triggers"
        store_dir.mkdir(parents=True)
        (store_dir / "triggers.jsonl").write_text(json.dumps({
            "id": "old", "when": "date:2026-09-01", "what": "legacy", "tier": "T0", "source": None,
            "state": "asleep", "created": "2026-08-30", "fired": None, "outcome": None, "shown": 0,
            "slept_until": None, "leased_until": None, "history": []}) + "\n", encoding="utf-8")
        r = _run(root, "due", "--date", "2026-09-02")
        assert "legacy" in r.stdout and "due 1" in r.stdout, r.stdout
        assert _run(root, "sleep", "old", "--days", "3", "--date", "2026-09-02").returncode == 0
        row = _rows(root)["old"]
        assert "state" not in row and row["slept_until"] == "2026-09-05", row
        assert _state(row, "2026-09-04") == "asleep" and _state(row, "2026-09-05") == "open"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_sticky_triggers_never_auto_sleep_and_lead_the_hook():
    """An owner item stays in the five hook slots, first, until it is fired or slept by hand."""
    root = _fixture()
    try:
        for i in range(6):
            r = _run(root, "add", "--when", "date:2026-09-01", "--what", f"item {i}", "--tier", "T0",
                     "--date", "2026-08-30")
            assert r.returncode == 0
        r = _run(root, "add", "--when", "date:2026-09-05", "--what", "owner decision", "--tier", "T0",
                 "--date", "2026-08-30", "--sticky")
        assert r.returncode == 0 and r.stdout.startswith("added tr-"), r
        sticky_id = r.stdout.split()[1]
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "item 5", "--tier", "T0",
                 "--date", "2026-08-30", "--sticky")
        assert r.stdout.startswith("exists"), "an existing trigger is pinned, not duplicated"
        for day in range(19, 26):
            r = _run(root, "hook", "--date", f"2026-09-{day}", "--format", "text")
            lines = [l for l in r.stdout.splitlines() if l.startswith("- [T0")]
            assert 2 <= len(lines) <= 5, r.stdout   # plain rows drop out as they fall asleep
            # Sticky rows come first: the newest-dated owner item outranks older plain ones.
            assert {lines[0].split("] ", 1)[1].split(" (")[0],
                    lines[1].split("] ", 1)[1].split(" (")[0]} == {"owner decision", "item 5"}, lines
            assert all("; sticky)" in l for l in lines[:2]), lines
        rows = _rows(root)
        sticky_rows = [x for x in rows.values() if x.get("sticky")]
        assert len(sticky_rows) == 2 and all(not x.get("slept_until") for x in sticky_rows), sticky_rows
        assert any(_state(x, "2026-09-25") == "asleep" for x in rows.values() if not x.get("sticky")), \
            "plain triggers still fall asleep after three days of showings"
        r = _run(root, "sleep", sticky_id, "--date", "2026-09-25")
        assert r.returncode == 0
        r = _run(root, "due", "--date", "2026-09-26")
        assert "owner decision" not in r.stdout, "an explicit sleep still applies to a sticky trigger"
        # Pinned rows that fill every place would hide ordinary rows for good; the last place is theirs.
        for i in range(4):
            _run(root, "add", "--when", "date:2026-09-01", "--what", f"pin {i}", "--tier", "T0", "--sticky")
        _run(root, "add", "--when", "date:2026-09-26", "--what", "plain new", "--tier", "T0", "--date", "2026-09-26")
        lines = [l for l in _run(root, "hook", "--date", "2026-09-26", "--format", "text").stdout.splitlines()
                 if l.startswith("- [T0")]
        assert len(lines) == 5 and "plain new" in lines[4] and all("; sticky)" in l for l in lines[:4]), lines
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_decision_template_rereview_example_yields_one_trigger():
    """The re-review form documented in templates/decisions.md is the one scan reads with default patterns."""
    template_path = TRIGGERS.parent.parent / "templates" / "decisions.md"
    if not template_path.is_file():  # an installed instance ships no templates/
        return
    template = template_path.read_text(encoding="utf-8")
    example = re.search(r"`(### DR-\d+ [^`]*re-review[^`]*)`", template)
    assert example, "templates/decisions.md must document the re-review heading form"
    root = _fixture()
    try:
        (root / "instance" / "decisions.md").write_text(example[1] + "\n", encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-01-10")
        assert r.returncode == 0, r.stderr
        assert "scan added 1 total 1" in r.stdout, r.stdout
        row = json.loads((root / "_private" / "triggers" / "triggers.jsonl").read_text(encoding="utf-8"))
        assert row["id"] == "rereview-DR-001" and row["when"] == "date:2026-02-01", row
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scan_decision_marker_not_last():
    """The date sits in the segment that carries the marker, wherever that segment is."""
    root = _fixture()
    try:
        _korean_config(root)
        (root / "instance" / "decisions.md").write_text(
            "### DR-904 later segment (2026-10-01 · active · 2027-01-15 재판정 · 앞선 날짜분은 DR-907에서 판정)\n\n"
            "### DR-905 ratio elsewhere (2026-11-01 · 테스트 5/5 통과 · 2주기 후 재판정)\n\n"
            "### DR-906 no dot (2026-11-01 2주기 후 재판정)\n", encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-11-10")
        assert r.returncode == 0, r.stderr
        rows = _rows(root)
        assert rows["rereview-DR-904"]["when"] == "date:2027-01-15", rows.get("rereview-DR-904")
        assert rows["rereview-DR-905"]["when"] == "date:2026-11-15", rows["rereview-DR-905"]
        assert rows["rereview-DR-906"]["when"] == "date:2026-11-15", rows["rereview-DR-906"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scan_follows_edited_source():
    root = _fixture()
    try:
        _korean_config(root)
        reg = root / "_private" / "work" / "experiments.md"
        row = "| X1 | pilot | approval | {due} | n | {status} | path |\n"
        head = "| ID | a | b | c | d | e | f |\n|---|---|---|---|---|---|---|\n"
        reg.write_text(head + row.format(due="2026-09-20", status="진행 중"), encoding="utf-8")
        assert _run(root, "scan", "--date", "2026-09-19").returncode == 0
        # A duplicated id must not move the row back and forth: the first listing wins.
        reg.write_text(head + row.format(due="2026-10-30", status="진행 중")
                       + row.format(due="2026-11-15", status="진행 중"), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 0, r.stderr
        assert _rows(root)["exp-X1"]["when"] == "date:2026-10-30", _rows(root)["exp-X1"]
        assert "moved" not in _run(root, "scan", "--date", "2026-09-19").stdout
        # A row scan made follows its source line's text and position; a hand row with a listed id keeps its own.
        assert _run(root, "add", "--id", "exp-X2", "--source", "notes.md:1", "--when", "date:2026-12-31",
                    "--what", "hand row").returncode == 0
        reg.write_text(head + "\n" + row.format(due="2026-10-30", status="진행 중").replace("pilot", "renamed")
                       + row.format(due="2026-12-31", status="진행 중").replace("X1", "X2"), encoding="utf-8")
        assert _run(root, "scan", "--date", "2026-09-19").returncode == 0
        rows = _rows(root)
        assert "renamed" in rows["exp-X1"]["what"] and rows["exp-X1"]["source"].endswith(":4"), rows["exp-X1"]
        assert rows["exp-X2"]["what"] == "hand row" and rows["exp-X2"]["source"] == "notes.md:1", rows["exp-X2"]
        # Nor does a different date in the registry move it.
        reg.write_text(head + "\n" + row.format(due="2026-10-30", status="진행 중").replace("pilot", "renamed")
                       + row.format(due="2027-06-01", status="진행 중").replace("X1", "X2"), encoding="utf-8")
        assert "moved exp-X2" not in _run(root, "scan", "--date", "2026-09-19").stdout
        assert _rows(root)["exp-X2"]["when"] == "date:2026-12-31", _rows(root)["exp-X2"]
        # A hand-added row that shares the prefix is not scan's to close.
        assert _run(root, "add", "--id", "exp-X1-extra", "--source", "notes.md", "--when",
                    "date:2026-12-31", "--what", "hand row").returncode == 0
        (root / "instance" / "decisions.md").write_text("### DR-001 none (2026-01-01 · active)\n", encoding="utf-8")
        reg.write_text(head + row.format(due="2026-10-30", status="완료"), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-11-01")
        assert not _rows(root)["exp-X1-extra"]["fired"], _rows(root)["exp-X1-extra"]
        assert r.returncode == 0, r.stderr
        r = _run(root, "due", "--date", "2026-11-01")
        assert r.stdout.strip() == "due 0", r.stdout
        # A fired row whose source carries a later date opens again.
        reg.write_text(head + row.format(due="2026-12-01", status="진행 중"), encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-11-02")
        assert r.returncode == 0, r.stderr
        x1 = _rows(root)["exp-X1"]
        assert x1["when"] == "date:2026-12-01" and not x1["fired"], x1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_add_reopens_fired_fixed_id():
    root = _fixture()
    try:
        r = _run(root, "add", "--id", "loop-auth", "--when", "date:2026-01-01", "--what", "loop broke",
                 "--date", "2026-01-01")
        assert r.returncode == 0, r.stderr
        assert _run(root, "fire", "loop-auth", "--outcome", "fixed", "--date", "2026-01-01").returncode == 0
        r = _run(root, "add", "--id", "loop-auth", "--when", "date:2026-02-01", "--what", "loop broke",
                 "--date", "2026-02-01")
        assert r.returncode == 0 and r.stdout.startswith("reopened loop-auth"), r
        r = _run(root, "hook", "--date", "2026-02-02", "--format", "text")
        assert "loop broke" in r.stdout, r.stdout
        # An add with the date it already had (or an earlier one) leaves a fired row closed.
        assert _run(root, "fire", "loop-auth", "--date", "2026-02-02").returncode == 0
        r = _run(root, "add", "--id", "loop-auth", "--when", "date:2026-02-01", "--what", "loop broke")
        assert r.stdout.startswith("exists"), r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_scan_md_dates_hold_across_new_year():
    """Scanning on both sides of 31 Dec must not move or reopen a row by a year."""
    root = _fixture()
    try:
        _korean_config(root)
        (root / "_private" / "work" / "experiments.md").write_text(
            "| X1 | december pilot | approval | 12/20 report | n | 진행 중 | path |\n", encoding="utf-8")
        (root / "instance" / "decisions.md").write_text(
            "### DR-910 december review (2026-12-01 · 12/20 재판정)\n\n"
            "### DR-911 january review (2026-10-01 · 1/15 재판정)\n", encoding="utf-8")
        for day in ("2026-12-10", "2026-12-31", "2027-01-01", "2027-01-05"):
            r = _run(root, "scan", "--date", day)
            assert r.returncode == 0, r.stderr
            assert "moved" not in r.stdout, (day, r.stdout)
        rows = _rows(root)
        assert rows["exp-X1"]["when"] == "date:2026-12-20", rows["exp-X1"]
        assert rows["rereview-DR-910"]["when"] == "date:2026-12-20", rows["rereview-DR-910"]
        assert rows["rereview-DR-911"]["when"] == "date:2027-01-15", rows["rereview-DR-911"]
        # A December date written late and first read in January is overdue, not due next December.
        with open(root / "_private" / "work" / "experiments.md", "a", encoding="utf-8") as fh:
            fh.write("| X2 | late pilot | approval | 12/28 report | n | 진행 중 | path |\n")
        assert _run(root, "scan", "--date", "2027-01-05").returncode == 0
        assert _rows(root)["exp-X2"]["when"] == "date:2026-12-28", _rows(root)["exp-X2"]
        # A judged re-review stays judged when the next new year comes round.
        assert _run(root, "fire", "rereview-DR-911", "--outcome", "judged", "--date", "2027-01-16").returncode == 0
        for day in ("2027-12-31", "2028-01-02"):
            r = _run(root, "scan", "--date", day)
            assert r.returncode == 0 and "reopened" not in r.stdout, (day, r.stdout)
        assert _rows(root)["rereview-DR-911"]["fired"] == "2027-01-16", _rows(root)["rereview-DR-911"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_source_closed_rows_return_when_listed_again():
    """A missing config or an emptied registry closes rows; restoring the source brings them back.

    The table is named on the command line: without a config there is no default table."""
    root = _fixture()
    try:
        _korean_config(root)
        reg = root / "_private" / "work" / "experiments.md"
        text = "| X1 | pilot | approval | 2026-12-20 | n | 진행 중 | path |\n"
        reg.write_text(text, encoding="utf-8")
        (root / "instance" / "decisions.md").write_text(
            "### DR-910 review (2026-11-01 · 12/20 재판정)\n", encoding="utf-8")
        assert _run(root, "scan", "--experiments", str(reg), "--date", "2026-11-10").returncode == 0
        config = root / "instance" / "config.json"
        saved = config.read_text(encoding="utf-8")
        config.unlink()
        reg.write_text("", encoding="utf-8")
        assert _run(root, "scan", "--experiments", str(reg), "--date", "2026-11-11").returncode == 0
        rows = _rows(root)
        assert rows["exp-X1"]["outcome"] == rows["rereview-DR-910"]["outcome"] == "source closed", rows
        config.write_text(saved, encoding="utf-8")
        reg.write_text(text, encoding="utf-8")
        r = _run(root, "scan", "--experiments", str(reg), "--date", "2026-11-12")
        assert r.returncode == 0, r.stderr
        rows = _rows(root)
        for tid in ("exp-X1", "rereview-DR-910"):
            assert _state(rows[tid], "2026-11-12") == "open" and not rows[tid]["fired"], rows[tid]
            assert rows[tid]["when"] == "date:2026-12-20", rows[tid]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_md_dates_never_drift_a_year():
    """A late re-review stays after its decision; a stored M/D row keeps its year on later scans."""
    root = _fixture()
    try:
        _korean_config(root)
        reg = root / "_private" / "work" / "experiments.md"
        x1 = "| X1 | long pilot | t | 11/30 report | m | 진행 중 | p |\n"
        dr201 = "### DR-201 seven months on (2026-05-01 · active · 12/1 재판정)\n\n"
        reg.write_text(x1, encoding="utf-8")
        (root / "instance" / "decisions.md").write_text(dr201, encoding="utf-8")
        assert _run(root, "scan", "--date", "2026-05-02").returncode == 0
        rows = _rows(root)
        assert rows["rereview-DR-201"]["when"] == "date:2026-12-01", rows["rereview-DR-201"]
        assert rows["exp-X1"]["when"] == "date:2026-11-30", rows["exp-X1"]
        hook = _run(root, "hook", "--date", "2026-05-02", "--format", "text").stdout
        assert "DR-201" not in hook and "X1" not in hook, hook
        reg.write_text(x1 + "| X2 | jan pilot | t | 1/5 report | m | 진행 중 | p |\n", encoding="utf-8")
        (root / "instance" / "decisions.md").write_text(
            dr201 + "### DR-300 undated (active · 1/15 재판정)\n", encoding="utf-8")
        assert _run(root, "scan", "--date", "2026-12-28").returncode == 0
        for tid in ("exp-X2", "rereview-DR-300"):
            assert _run(root, "fire", tid, "--outcome", "done", "--date", "2027-01-16").returncode == 0
        # More than 180 days after the fire the scan date alone would put 1/5 and 1/15 in 2028.
        r = _run(root, "scan", "--date", "2027-08-01")
        assert r.returncode == 0 and "reopened" not in r.stdout and "moved" not in r.stdout, r.stdout
        rows = _rows(root)
        assert rows["exp-X2"]["when"] == "date:2027-01-05" and rows["exp-X2"]["fired"], rows["exp-X2"]
        assert rows["rereview-DR-300"]["when"] == "date:2027-01-15", rows["rereview-DR-300"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_survives_bad_rows():
    root = _fixture()
    try:
        store_dir = root / "_private" / "triggers"
        store_dir.mkdir(parents=True)
        good = {"id": "good", "when": "date:2026-09-01", "what": "good item", "tier": "T0", "source": None,
                "state": "open", "created": "2026-08-30", "fired": None, "outcome": None, "shown": 0,
                "slept_until": None, "leased_until": None, "history": []}
        bad_date = dict(good, id="bad-date", what="bad date", slept_until="2026-13-01")
        no_tier = {k: v for k, v in good.items() if k not in ("tier", "id")}   # add once stopped on the missing id
        # A counter of the wrong type once made the hook's sort raise on every session start.
        bad_count = dict(good, id="bad-count", what="bad count", shown="0")
        # Ready to retire: a retirement the hook cannot save must not be announced on every run.
        worn = dict(good, id="worn", what="worn item", shown=3, ignored=2, last_shown="2026-09-01")
        text = (json.dumps(good) + "\n" + json.dumps(worn) + "\n{bad\n" + json.dumps(bad_date) + "\n" + json.dumps(no_tier)
                + "\n" + json.dumps(dict(good, what=None)) + "\n" + json.dumps(bad_count) + "\n")
        (store_dir / "triggers.jsonl").write_bytes(text.encode("utf-8") + b"\xff\xfe bad\n")
        r = _run(root, "hook", "--date", "2026-09-19", "--format", "text")
        assert r.returncode == 0, r
        assert "good item" in r.stdout and "6 unreadable trigger row(s) skipped" in r.stdout, r.stdout
        assert "retired" not in r.stdout, r.stdout
        assert b"{bad" in (store_dir / "triggers.jsonl").read_bytes(), \
            "the hook must not rewrite a store it could not read in full"
        # The hook offers no command that refuses; the refusal says where the damage is and what helps.
        assert "fire: " not in r.stdout and "cannot read line(s) 3, 4, 5, 6, 7, 8 (line 3: " in r.stdout, r.stdout
        for args in (("fire", "good"), ("add", "--when", "date:2026-09-20", "--what", "x")):
            refused = _run(root, *args)
            assert refused.returncode == 2 and str(store_dir / "triggers.jsonl") in refused.stderr \
                and "line(s) 3, 4, 5, 6, 7, 8 (line 3: " in refused.stderr and "Repairing or removing" in refused.stderr, refused
        assert "(line 3: not a JSON object)" in refused.stderr, refused
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_fire_without_claim():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "x", "--date", "2026-08-30")
        tid = r.stdout.split()[1]
        r = _run(root, "fire", tid, "--outcome", "done", "--date", "2026-09-19")
        assert r.returncode == 0 and r.stdout.startswith("fired"), r
        r = _run(root, "fire", tid, "--outcome", "done", "--date", "2026-09-19")
        assert r.returncode == 2 and "already fired" in r.stderr, r
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "y", "--date", "2026-08-30")
        tid = r.stdout.split()[1]
        assert _run(root, "claim", tid, "--holder", "alice").returncode == 0
        r = _run(root, "fire", tid, "--holder", "bob", "--date", "2026-09-19")
        assert r.returncode == 2 and "is leased by alice" in r.stderr, r
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ignored_twice_retires():
    import datetime as dt
    root = _fixture()
    try:
        r = _run(root, "add", "--id", "plain", "--when", "date:2026-09-01", "--what", "plain item",
                 "--date", "2026-08-30")
        assert r.returncode == 0, r.stderr
        shown, retired_note = [], []
        day = dt.date(2026, 9, 19)
        while day <= dt.date(2026, 10, 25):
            r = _run(root, "hook", "--date", day.isoformat(), "--format", "text")
            assert r.returncode == 0, r.stderr
            if "plain item" in r.stdout:
                shown.append(day.isoformat())
            if "1 reminder(s) retired after being ignored" in r.stdout:
                retired_note.append(day.isoformat())
            day += dt.timedelta(days=1)
        # Three rounds of three showings, two week-long sleeps between them, then retirement.
        assert shown == ["2026-09-19", "2026-09-20", "2026-09-21", "2026-09-29", "2026-09-30",
                         "2026-10-01", "2026-10-09", "2026-10-10", "2026-10-11"], shown
        assert retired_note == ["2026-10-12"], retired_note
        row = _rows(root)["plain"]
        assert _state(row) == "retired" and row["fired"] is None, row
        listed = _run(root, "list").stdout
        assert "plain item" not in listed and "total 0 (1 fired or retired hidden" in listed, listed
        assert "plain item" in _run(root, "list", "--all").stdout
        for command in ("sleep", "fire"):
            r = _run(root, command, "plain", "--date", "2026-10-25")
            assert r.returncode == 2 and "was retired" in r.stderr, (command, r)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_what_is_one_line():
    root = _fixture()
    try:
        r = _run(root, "add", "--when", "date:2026-09-01", "--what", "a\nb", "--date", "2026-08-30")
        assert r.returncode == 0, r.stderr
        assert _run(root, "add", "--id", "long", "--when", "date:2026-09-01", "--what", "y" * 30000,
                    "--date", "2026-08-30").returncode == 0
        assert _run(root, "claim", "long", "--holder", "h" * 30000).returncode == 0
        r = _run(root, "hook", "--date", "2026-09-19", "--format", "text")
        long_line = next(l for l in r.stdout.splitlines() if "id long" in l)
        assert len(long_line) < 600 and "list shows the whole row" in long_line, long_line
        assert len([l for l in r.stdout.splitlines() if "a b" in l]) == 1, r.stdout
        assert not any(l.strip() == "b" for l in r.stdout.splitlines()), r.stdout
        # The refusal for an unreadable row names the field; quoting a 30,000-character date would be injected whole.
        store = root / "_private" / "triggers" / "triggers.jsonl"
        good = store.read_text(encoding="utf-8")
        row = dict(next(iter(_rows(root).values())), id="b")
        store.write_text(good + json.dumps(dict(row, when="date:" + "9" * 30000)) + "\n", encoding="utf-8")
        r = _run(root, "hook", "--date", "2026-09-19", "--format", "text")
        assert len(r.stdout) < 2000 and "field when" in r.stdout, len(r.stdout)
        # scan splits a stored source, so a source that is not text is refused, not a traceback.
        store.write_text(good + json.dumps(dict(row, source=5)) + "\n", encoding="utf-8")
        r = _run(root, "scan", "--date", "2026-09-19")
        assert r.returncode == 2 and "field source" in r.stderr, r
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_sleep_refuses_fired():
    root = _fixture()
    try:
        r = _run(root, "add", "--id", "s", "--when", "date:2026-09-01", "--what", "x", "--date", "2026-08-30")
        assert _run(root, "fire", "s", "--date", "2026-09-19").returncode == 0
        r = _run(root, "sleep", "s", "--date", "2026-09-19")
        assert r.returncode == 2 and "already fired" in r.stderr, r
        assert _state(_rows(root)["s"]) == "fired"
    finally:
        shutil.rmtree(root, ignore_errors=True)


TESTS = [
    test_scan_decision_marker_not_last,
    test_scan_follows_edited_source,
    test_add_reopens_fired_fixed_id,
    test_scan_md_dates_hold_across_new_year,
    test_source_closed_rows_return_when_listed_again,
    test_md_dates_never_drift_a_year,
    test_hook_survives_bad_rows,
    test_fire_without_claim,
    test_ignored_twice_retires,
    test_what_is_one_line,
    test_sleep_refuses_fired,
    test_add_due_fire_and_tier_boundary,
    test_read_only_commands_touch_nothing_on_a_fresh_root,
    test_invalid_inputs_exit_2,
    test_hook_limits_and_auto_sleep_after_ignores,
    test_claim_lease_refuses_second_holder_and_due_stays_read_only,
    test_scan_experiments_and_decision_rereviews,
    test_decision_template_rereview_example_yields_one_trigger,
    test_shown_counts_once_per_calendar_day,
    test_hook_fire_instruction_runs_as_written,
    test_add_refuses_when_kinds_that_never_fire,
    test_state_is_read_from_dates_not_stored,
    test_sticky_triggers_never_auto_sleep_and_lead_the_hook,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
