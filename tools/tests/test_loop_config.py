#!/usr/bin/env python3
"""Test the reading of the loop's settings (the `loop` block of the instance configuration) in temporary
instance folders."""
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config as LC  # noqa: E402

# The tools this file exercises, for the kit's tool-coverage test (tools/tests/test_tool_coverage.py).
COVERED = (
    "tools/loop/lib/loop_config.py",
)

# The smallest configuration the instance reader accepts.
BASE = {"schema_version": 4, "instance": {"name": "t"},
        "egress": {"model_send": {"deny_prefixes": ["_private/"], "allow_prefixes": []}},
        "journal_visibility": {"public_tracks": ["system"], "legacy_public_tracks": [], "legacy_cutoff": None}}


class Instance:
    """A temporary instance root with instance/config.json holding config (None: no file)."""

    def __init__(self, config=BASE, raw=None):
        self.config, self.raw = config, raw

    def __enter__(self):
        self.root = tempfile.mkdtemp(prefix="loop-config-")
        os.makedirs(os.path.join(self.root, "instance"))
        if self.raw is not None or self.config is not None:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(self.raw if self.raw is not None else json.dumps(self.config))
        return self.root

    @property
    def path(self):
        return os.path.join(self.root, "instance", "config.json")

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)


def with_loop(block):
    return dict(BASE, loop=block)


def test_every_key_has_an_engine_default():
    for config in (None, BASE, with_loop({})):
        with Instance(config) as root:
            for key, (default, _, meaning) in LC.KEYS.items():
                assert LC.value(key, root) == default and meaning, key
            assert LC.problems(root) == [], LC.problems(root)
    assert LC.value("never", "/nonexistent-root") == ()
    assert LC.value("runtime_orders", "/nonexistent-root") == {"default": LC.DEFAULT_ORDER}


def test_configured_values_are_used():
    block = {"never": ["notes/", "LICENSE"], "clone_excluded": ["media/"], "job_prefix": "org.example",
             "runtime_orders": {"default": ["codex", "claude"], "judge": ["claude"]},
             "papers_contact": "t <t@example.invalid>", "token_ceiling": 200000, "_doc": "ignored"}
    with Instance(with_loop(block)) as root:
        assert LC.value("never", root) == ("notes/", "LICENSE")
        assert LC.value("clone_excluded", root) == ("media/",)
        assert LC.value("job_prefix", root) == "org.example"
        assert LC.value("runtime_orders", root) == {"default": ("codex", "claude"), "judge": ("claude",)}
        assert LC.value("papers_contact", root) == "t <t@example.invalid>"
        assert LC.value("token_ceiling", root) == 200000
        assert LC.problems(root) == []


def test_a_value_of_the_wrong_form_takes_the_default_and_is_said():
    block = {"never": ["../outside/", "/abs/"], "clone_excluded": "media/", "token_ceiling": "yes",
             "runtime_orders": {"nonstage": ["claude"]}, "papers_contact": "two\nlines"}
    with Instance(with_loop(block)) as root:
        for key, (default, _, _) in LC.KEYS.items():
            assert LC.value(key, root) == default, key
        said = LC.problems(root)
        # One line for each key, and for never one for each entry that is not one literal path.
        assert len(said) == len(block) + 1 and {line.split(":")[0] for line in said} == {f"loop.{k}" for k in block}, said
        assert 'loop.token_ceiling: cannot use "yes"' in said, said
    for bad in ({"token_ceiling": "true"}, {"token_ceiling": -1}, {"token_ceiling": True},
                {"nevr": []}, {"runtime_orders": {"judge": [["claude"]]}}):
        with Instance(with_loop(bad)) as root:
            assert LC.value("token_ceiling", root) is None and len(LC.problems(root)) == 1, bad
    for raw in ("not json", json.dumps(with_loop(["never"])), json.dumps(["a list"])):
        with Instance(raw=raw) as root:
            assert LC.value("token_ceiling", root) is None and LC.value("never", root) == ()
            assert len(LC.problems(root)) == 1, LC.problems(root)


def test_the_sources_schedule_and_health_keys():
    with Instance(with_loop({})) as root, Instance(with_loop({})) as twin:
        label = LC.job_label("papers", root)
        assert re.fullmatch(r"local\.t-[0-9a-f]{8}\.loop\.papers", label), label
        # Another folder with the same instance name gets its own label, so neither replaces the other's job.
        assert LC.job_label("papers", twin) != label, label
        assert LC.papers_user_agent(root) == "improvement-loop-papers"
        assert LC.value("schedule", root)["health"] == {"hour": 6, "minute": 0}
    block = {"job_prefix": "org.example", "papers_client": "reader", "papers_contact": "a@example.invalid",
             "papers_queries": ["abs:x"], "schedule": {"papers": {"weekday": 5, "hour": 4, "minute": 30}},
             "health_started_by": "my own daily job", "health_extra_checks": [["python3", "tools/x.py", "check"]]}
    with Instance(with_loop(block)) as root:
        assert LC.job_label("health", root) == "org.example.health"
        assert LC.papers_user_agent(root) == "reader (contact: a@example.invalid)"
        assert LC.value("papers_queries", root) == ("abs:x",)
        sched = LC.value("schedule", root)
        assert sched["papers"] == {"weekday": 5, "hour": 4, "minute": 30} and sched["health"] == LC.DEFAULT_SCHEDULE["health"]
        assert LC.value("health_extra_checks", root) == (("python3", "tools/x.py", "check"),)
        assert LC.problems(root) == [], LC.problems(root)
    bad = {"job_prefix": "has space", "schedule": {"health": {"weekday": 1, "hour": 6, "minute": 0}},
           "health_extra_checks": ["not a list"], "clone_excluded": ["../outside/"], "papers_queries": []}
    with Instance(with_loop(bad)) as root:
        assert re.fullmatch(r"local\.t-[0-9a-f]{8}\.loop\.papers", LC.job_label("papers", root))
        assert LC.value("schedule", root) == LC.DEFAULT_SCHEDULE
        assert len(LC.problems(root)) == len(bad), LC.problems(root)


def test_the_token_ceiling_says_what_it_counts():
    meaning = LC.KEYS["token_ceiling"][2]
    assert "the tokens the model programs report" in meaning, meaning
    assert "a run without a count does not move it" in meaning, meaning


def test_the_command_prints_every_key():
    r = subprocess.run([sys.executable, LC.__file__], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for key in LC.KEYS:
        assert f"loop.{key} = " in r.stdout, r.stdout


TESTS = [
    test_the_token_ceiling_says_what_it_counts,
    test_every_key_has_an_engine_default,
    test_configured_values_are_used,
    test_a_value_of_the_wrong_form_takes_the_default_and_is_said,
    test_the_sources_schedule_and_health_keys,
    test_the_command_prints_every_key,
]


def main():
    # A test function this list does not run would pass unseen, so it fails the file.
    unlisted = sorted(n for n, f in globals().items() if n.startswith("test_") and callable(f) and f not in TESTS)
    for name in unlisted:
        print(f"✗ {name}: not in TESTS")
    failed = []
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"loop_config: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed or unlisted else 0


if __name__ == "__main__":
    raise SystemExit(main())
