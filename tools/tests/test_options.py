#!/usr/bin/env python3
"""The optional-parts table: nothing changes unless a person names an option, a missing need
changes nothing, a no is remembered, and the manual describes each option in the table's order.

Every case runs in a scratch copy of tools/ with its own config and HOME; the embedding need is a
stand-in that answers inside each program the test starts (testlib.http_stand_ins), so no address
is served and no real model or service is called.
"""
import contextlib
import http.server
import importlib.util
import json
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

import testlib
from testlib import skip_unless, terminal_opens


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.contextmanager
def instance():
    """Yield (root, env): a scratch instance whose recall.py is a stub that logs its arguments."""
    parent = tempfile.mkdtemp(prefix="options-")
    try:
        root = os.path.join(parent, "inst")
        shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(root, "tools"),
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))
        os.makedirs(os.path.join(root, "instance"))
        os.makedirs(os.path.join(root, ".claude"))
        # An installed instance has no templates/, so the starter config is written here.
        cfg = {"schema_version": 4, "instance": {"name": "fixture"},
               "journal_visibility": {"public_tracks": ["system"], "legacy_cutoff": None,
                                      "legacy_public_tracks": []},
               "deliver": {"block": [], "observe": [], "send_tools": ["FixtureTool"]}}
        write(root, "instance/config.json", json.dumps(cfg, indent=2) + "\n")
        write(root, "tools/recall.py",
              "import sys\nopen(sys.argv[0] + '.calls', 'a').write(' '.join(sys.argv[1:]) + '\\n')\n")
        home = os.path.join(parent, "home")
        os.makedirs(home)
        bindir = os.path.join(parent, "bin")
        os.makedirs(bindir)
        # No codex on this PATH, so its need is missing by construction.
        env = {"HOME": home, "PATH": bindir + os.pathsep + "/usr/bin:/bin",
               "MOTTORI_INSTANCE": root}
        # The programs started here reach the stand-ins through these two (testlib.http_stand_ins).
        env.update({k: os.environ[k] for k in ("PYTHONPATH", testlib.STAND_IN_ENV) if k in os.environ})
        yield root, env
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def write(root, rel, body):
    path = os.path.join(root, rel)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def read(root, rel):
    with open(os.path.join(root, rel), "rb") as f:
        return f.read()


def run(root, env, *args):
    return subprocess.run([sys.executable, os.path.join(root, "tools", "options.py"), *args],
                          cwd=root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)


def config(root):
    return json.loads(read(root, "instance/config.json"))


class Embeddings(http.server.BaseHTTPRequestHandler):
    """Answers one vector for any input, like an OpenAI-style route, and records the path of every
    request in the file requests of its state folder."""
    def do_POST(self):
        with open(os.path.join(self.server.state, "requests"), "a", encoding="utf-8") as f:
            f.write(self.path + "\n")
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        out = json.dumps({"data": [{"embedding": [0.5, 0.5]} for _ in body["input"]]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def embedding_server():
    """Yield (url, requests): the stand-in's endpoint, and a function that lists the path of every
    request it was sent."""
    state = tempfile.mkdtemp(prefix="options-embed-")
    try:
        url = testlib.register_stand_in(__file__, "Embeddings", state)

        def requests():
            path = os.path.join(state, "requests")
            return read(state, "requests").decode().splitlines() if os.path.exists(path) else []
        yield url + "/v1/embeddings", requests
    finally:
        shutil.rmtree(state, ignore_errors=True)


def unserved_port():
    """A loopback port number no stand-in answers on: a connection there is refused."""
    return 47000


def test_a_missing_need_prints_the_steps_and_changes_nothing():
    with instance() as (root, env), embedding_server() as (proxy, proxied):
        before = read(root, "instance/config.json")
        # A proxy from the environment must not answer for a local server that is not there.
        env = dict(env, http_proxy=proxy.rsplit("/v1/", 1)[0])
        cases = [
            # Without the server program the one command that installs it is named: Homebrew on
            # macOS, Ollama's own script elsewhere.
            (["on", "meaning", f"endpoint=http://127.0.0.1:{unserved_port()}/v1/embeddings"],
             "install ollama" if sys.platform == "darwin" else "ollama.com/install.sh"),
            # A remote host is refused before any call: the texts would be the owner's own words.
            (["on", "meaning", "endpoint=http://example.invalid/v1/embeddings"], "refused"),
            (["on", "codex"], "codex login"),
            (["on", "history"], "cleanupPeriodDays"),
        ]
        for args, step in cases:
            r = run(root, env, *args)
            assert r.returncode == 1, (args, r.stdout, r.stderr)
            assert "nothing was changed" in r.stdout and step in r.stdout, (args, r.stdout)
            assert read(root, "instance/config.json") == before, args
        assert not os.path.exists(os.path.join(root, "tools", "recall.py.calls"))
        assert proxied() == [], proxied()
        # The Stop declaration either runs the check or runs one dispatcher; a command that only
        # mentions the file leaves the delivery check off, and the steps name the entry to add.
        for command in ("sh tools/hook.sh gate.py check || true", "echo deliver.py disabled",
                        "echo 'tools/hook.sh deliver.py hook'"):
            write(root, ".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": command}]}]}}))
            r = run(root, env, "on", "deliver")
            assert r.returncode == 1 and "deliver.py hook" in r.stdout, (command, r.stdout)
            assert read(root, "instance/config.json") == before
        r = run(root, env, "on", "meaning", "size=3")
        assert r.returncode == 2 and "size=3" in r.stderr, r.stderr
        assert read(root, "instance/config.json") == before


def test_with_the_need_in_place_on_writes_the_settings_and_runs_the_first_step():
    with instance() as (root, env), embedding_server() as (endpoint, _):
        # A first step that fails puts the settings back, so the list never shows a broken option on.
        stub = read(root, "tools/recall.py")
        before = read(root, "instance/config.json")
        write(root, "tools/recall.py", "raise SystemExit(2)\n")
        r = run(root, env, "on", "meaning", f"endpoint={endpoint}")
        assert r.returncode == 1 and read(root, "instance/config.json") == before, r.stdout
        assert "[off] Search by meaning" in run(root, env).stdout
        write(root, "tools/recall.py", stub.decode())
        r = run(root, env, "on", "meaning", f"endpoint={endpoint}")
        assert r.returncode == 0, r.stdout + r.stderr
        meaning = config(root)["instance"]["recall_meaning"]
        assert meaning["endpoint"] == endpoint and meaning["model"] == "embeddinggemma", meaning
        assert read(root, "tools/recall.py.calls").decode() == "index\n"
        # Settings given to an option that is already on are not applied silently.
        r = run(root, env, "on", "meaning", "model=other")
        assert r.returncode == 0 and "not applied: model=other" in r.stdout, r.stdout
        assert config(root)["instance"]["recall_meaning"]["model"] == "embeddinggemma"
        write(root, ".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "sh tools/hook.sh deliver.py hook || true"}]}]}}))
        r = run(root, env, "on", "deliver")
        assert r.returncode == 0, r.stdout + r.stderr
        assert config(root)["deliver"]["block"] == ["unopened"], config(root)["deliver"]
        assert config(root)["deliver"]["send_tools"] == ["FixtureTool"], "keys the option does not name stay"
        # A no is remembered: the option leaves the offer.
        r = run(root, env, "off", "meaning")
        assert r.returncode == 0, r.stdout + r.stderr
        cfg = config(root)
        assert "recall_meaning" not in cfg.get("instance", {}) and cfg["options"]["declined"] == ["meaning"], cfg
        listing = run(root, env).stdout
        assert "[off, you said no] Search by meaning" in listing, listing
        r = run(root, env, "off", "codex", "extra")
        assert r.returncode == 2 and "usage:" in r.stderr, r.stderr
        # Naming it again is a yes and lifts the no.
        r = run(root, env, "on", "meaning", f"endpoint={endpoint}")
        assert r.returncode == 0 and config(root)["options"]["declined"] == [], r.stdout


class Model(http.server.BaseHTTPRequestHandler):
    """Knows no model until the stand-in ollama in its state folder (a bin folder) has pulled one, as
    the real server answers before a download."""
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        out = json.dumps({"data": [{"embedding": [0.5, 0.5]} for _ in body["input"]]}).encode()
        self.send_response(200 if os.path.exists(os.path.join(self.server.state, "ollama.pulled")) else 404)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


def model_server(bindir):
    """The endpoint of a stand-in that knows no model until the stand-in ollama in bindir pulled one."""
    return testlib.register_stand_in(__file__, "Model", bindir) + "/v1/embeddings"


def stand_in_ollama(env):
    """An ollama on PATH that records its arguments and marks the model as pulled."""
    bindir = env["PATH"].split(os.pathsep)[0]
    path = os.path.join(bindir, "ollama")
    with open(path, "w", encoding="utf-8") as f:
        f.write('#!/bin/sh\necho "$@" >> "$0.calls"\ntouch "$0.pulled"\necho pulling\n')
    os.chmod(path, 0o755)
    return bindir


def on_terminal(root, env, answer, *args):
    """Run options.py with a terminal as its input, answering its one question with answer."""
    import pty
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen([sys.executable, os.path.join(root, "tools", "options.py"), *args],
                                cwd=root, env=env, stdin=slave, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        os.write(master, answer.encode() + b"\n")
        out, err = proc.communicate(timeout=30)
    finally:
        os.close(master)
        os.close(slave)
    return proc.returncode, out, err


def test_the_model_is_downloaded_only_after_one_yes():
    """Without a terminal: no word, the word, and not installed. Only the word changes anything; the
    answers at a terminal are the next test."""
    with instance() as (root, env):
        bindir = stand_in_ollama(env)
        calls, pulled = os.path.join(bindir, "ollama.calls"), os.path.join(bindir, "ollama.pulled")
        before = read(root, "instance/config.json")
        given = f"endpoint={model_server(bindir)}"
        # No terminal and no word: the plan and the word, nothing downloaded or written.
        r = run(root, env, "on", "meaning", given)
        assert r.returncode == 1 and not os.path.exists(calls), r.stdout + r.stderr
        assert read(root, "instance/config.json") == before
        assert "embeddinggemma (about 0.6 GB, from the Ollama library" in r.stdout, r.stdout
        assert ("only after the owner said yes runs `python3 tools/options.py on meaning "
                f"{given} yes`") in r.stdout, r.stdout
        # No terminal with the word.
        r = run(root, env, "on", "meaning", given, "yes")
        assert r.returncode == 0 and "meaning is on." in r.stdout, r.stdout + r.stderr
        # Read through a pipe, the plan still comes before what the download prints.
        assert r.stdout.index("embeddinggemma (about") < r.stdout.index("pulling"), r.stdout
        with open(calls, encoding="utf-8") as f:
            assert f.read() == "pull embeddinggemma\n"
        assert read(root, "tools/recall.py.calls").decode() == "index\n"
        # Not installed: one line with the command that installs it, nothing else.
        write(root, "instance/config.json", before.decode())
        os.remove(os.path.join(bindir, "ollama"))
        os.remove(pulled)
        r = run(root, env, "on", "meaning", given, "yes")
        assert r.returncode == 1 and r.stdout.count("\n") == 1, r.stdout
        assert "Ollama, is not installed. Install it with `" in r.stdout, r.stdout
        assert read(root, "instance/config.json") == before


@skip_unless(terminal_opens, "a pseudo-terminal, which the loop's sandbox does not give")
def test_at_a_terminal_only_a_yes_downloads_the_model():
    with instance() as (root, env):
        bindir = stand_in_ollama(env)
        calls = os.path.join(bindir, "ollama.calls")
        before = read(root, "instance/config.json")
        endpoint = model_server(bindir)
        given = f"endpoint={endpoint}"
        # A terminal and a no: nothing downloaded or turned on, and the no is kept, so setup does not
        # turn the list on later by itself (KIT-DR-094).
        code, out, _ = on_terminal(root, env, "n", "on", "meaning", given)
        assert code == 1 and "Download it and turn the list on?" in out and "Your no is recorded" in out, out
        assert not os.path.exists(calls) and "recall_meaning" not in config(root)["instance"]
        assert config(root)["options"]["declined"] == ["meaning"], config(root)
        assert before != read(root, "instance/config.json")
        # A terminal and a yes: downloaded once, written, the index started, the no forgotten.
        code, out, err = on_terminal(root, env, "y", "on", "meaning", given)
        assert code == 0 and "meaning is on." in out, out + err
        assert "meaning" not in config(root).get("options", {}).get("declined", []), config(root)
        assert read(root, "tools/recall.py.calls").decode() == "index\n"
        with open(calls, encoding="utf-8") as f:
            assert f.read() == "pull embeddinggemma\n"
        assert config(root)["instance"]["recall_meaning"]["endpoint"] == endpoint


def test_on_puts_back_settings_the_search_does_not_read():
    """`on` reads the option back through the search's own reader and restores the config when
    that reader does not see it on, whatever made the settings unreadable."""
    with instance() as (root, env), embedding_server() as (endpoint, _):
        before = read(root, "instance/config.json")
        # A key the search does not read: options.py writing the settings under another name.
        source = read(root, "tools/options.py").decode()
        write(root, "tools/options.py", source.replace('MEANING_KEY = "recall_meaning"',
                                                       'MEANING_KEY = "recall_meaning_v0"'))
        r = run(root, env, "on", "meaning", f"endpoint={endpoint}")
        assert r.returncode == 1 and "put back" in r.stdout, r.stdout + r.stderr
        assert read(root, "instance/config.json") == before
        assert "[off] Search by meaning" in run(root, env).stdout
        assert not os.path.exists(os.path.join(root, "tools", "recall.py.calls"))
        write(root, "tools/options.py", source)
        # An empty model is written, read back as off, and put back.
        r = run(root, env, "on", "meaning", f"endpoint={endpoint}", "model=")
        assert r.returncode == 1 and "put back" in r.stdout, r.stdout + r.stderr
        assert read(root, "instance/config.json") == before


def test_the_list_shows_on_only_what_the_search_reads():
    with instance() as (root, env):
        cfg = config(root)
        cfg["instance"]["recall_meaning"] = {"endpoint": "http://127.0.0.1:9/v1/embeddings",
                                             "model": "m", "query_prefix": 5}
        write(root, "instance/config.json", json.dumps(cfg))
        assert "[off] Search by meaning" in run(root, env).stdout


def test_on_takes_the_empty_prefixes_the_search_accepts():
    with instance() as (root, env), embedding_server() as (endpoint, _):
        r = run(root, env, "on", "meaning", f"endpoint={endpoint}", "query_prefix=", "document_prefix=")
        assert r.returncode == 0, r.stdout + r.stderr
        meaning = config(root)["instance"]["recall_meaning"]
        assert meaning["query_prefix"] == meaning["document_prefix"] == "", meaning
        assert "[on] Search by meaning" in run(root, env).stdout


def test_the_real_index_agrees_with_the_list():
    """With the search's own recall.py as the first step, the list and the index say the same."""
    with instance() as (root, env), embedding_server() as (endpoint, paths):
        shutil.copy(os.path.join(ROOT, "tools", "recall.py"), os.path.join(root, "tools", "recall.py"))
        r = run(root, env, "on", "meaning", f"endpoint={endpoint}")
        assert r.returncode == 0 and "List by meaning: on (embeddinggemma)" in r.stdout, r.stdout + r.stderr
        assert "[on] Search by meaning" in run(root, env).stdout
        index = subprocess.run([sys.executable, os.path.join(root, "tools", "recall.py"), "index"], cwd=root,
                               env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        assert index.returncode == 0 and "List by meaning: on (embeddinggemma)" in index.stdout, index


def test_the_list_and_doctor_read_the_same_retention():
    """A settings file that sets cleanupPeriodDays to something that is not a day count leaves the
    retention unmeasured for both, so the list cannot give a day count while doctor cannot say."""
    probe = "import sys; sys.path.insert(0, 'tools'); import doctor; print(doctor._transcript_retention())"
    with instance() as (root, env):
        os.makedirs(os.path.join(env["HOME"], ".claude"))
        write(env["HOME"], ".claude/settings.json", '{"cleanupPeriodDays": 365}')
        for local, on, said in (('{"cleanupPeriodDays": "90"}', False, "not a number"),
                                ("{", False, "cannot be read"),
                                ('{"cleanupPeriodDays": 90}', True, "kept 90 days"),
                                ('{"other": 1}', True, "kept 365 days")):
            write(root, ".claude/settings.local.json", local)
            listed = [x for x in run(root, env).stdout.splitlines() if x.strip().startswith("History:")]
            doctor = subprocess.run([sys.executable, "-c", probe], cwd=root, env=env,
                                    capture_output=True, text=True).stdout
            assert len(listed) == 1 and ("can find words that old" in listed[0]) == on, (local, listed)
            assert on or "cannot be read here" in listed[0], (local, listed)
            assert said in doctor, (local, doctor)


def load(env):
    """Import options.py bound to the scratch instance, as setup.sh's child process would be."""
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location(
            "options_under_test", os.path.join(env["MOTTORI_INSTANCE"], "tools", "options.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def test_setup_lists_once_and_changes_only_what_is_typed():
    with instance() as (root, env):
        before = read(root, "instance/config.json")
        # One line with the count and the way to the list, and nothing changes, at a terminal too.
        # The fixture holds an installation from before delivery was on by default, so all three are off.
        expected = "Three optional parts are off. Run python3 tools/options.py to view or enable them.\n"
        r = run(root, env, "setup")
        assert r.returncode == 0 and r.stdout == expected, r.stdout + r.stderr
        assert read(root, "instance/config.json") == before
        options = load(env)
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(sys.stdin, "isatty", lambda: True), \
                contextlib.redirect_stdout(out):
            assert options.cmd_setup() == 0
        assert out.getvalue() == expected, out.getvalue()
        assert read(root, "instance/config.json") == before
        # A part the owner said no to is still off, and the count says so.
        cfg = config(root)
        cfg["options"] = {"declined": ["meaning"]}
        write(root, "instance/config.json", json.dumps(cfg))
        r = run(root, env, "setup")
        assert r.stdout == expected, r.stdout
        assert "[off, you said no] Search by meaning" in run(root, env).stdout
        # Codex and the history are facts the list reports, with no state word and no number.
        listing = run(root, env).stdout
        assert "Codex, a second model family: not installed" in listing and "(codex)" not in listing, listing
        write(root, "../bin/codex", "#!/bin/sh\n")
        os.chmod(os.path.join(root, "../bin/codex"), 0o755)
        listing = run(root, env).stdout
        assert "Codex, a second model family: installed" in listing, listing
        # Naming one with on or off changes nothing and says it is not a switch.
        for word in ("on", "off"):
            for name in ("codex", "history"):
                r = run(root, env, word, name)
                assert r.returncode == 1 and f"{name} is not a switch of this kit" in r.stdout, r.stdout
        assert "declined" not in config(root).get("options", {}) or \
            not {"codex", "history"} & set(config(root)["options"]["declined"]), config(root)


def test_setup_turns_meaning_on_only_when_the_local_server_already_answers():
    """KIT-DR-094: setup turns the list by meaning on when it costs nothing, redraws the state page for
    the new configuration, and never after a no or with MOTTORI_NO_LOCAL_PROBE=1."""
    def setup(root, env, probe):
        options = load(env)
        out = io.StringIO()
        with mock.patch.dict(os.environ, dict(env, MOTTORI_NO_LOCAL_PROBE=probe)), \
                mock.patch.object(options, "_embeds", lambda e, m: True), contextlib.redirect_stdout(out):
            assert options.cmd_setup() == 0
        return out.getvalue()

    def current(root, env):
        code = "import sys; sys.path.insert(0, 'tools'); import now; print(now.snapshots_current())"
        return subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True,
                              text=True).stdout.strip()
    with instance() as (root, env):
        subprocess.run([sys.executable, "tools/now.py", "render"], cwd=root, env=env, capture_output=True)
        out = setup(root, env, "0")
        assert "Search by meaning is on" in out, out
        assert "recall_meaning" in config(root)["instance"], config(root)
        assert current(root, env) == "True"
    with instance() as (root, env):
        cfg = config(root)
        cfg["options"] = {"declined": ["meaning"]}
        write(root, "instance/config.json", json.dumps(cfg))
        before = read(root, "instance/config.json")
        assert "Search by meaning is on" not in setup(root, env, "0")
        assert read(root, "instance/config.json") == before
    with instance() as (root, env):
        before = read(root, "instance/config.json")
        assert "Search by meaning is on" not in setup(root, env, "1")
        assert read(root, "instance/config.json") == before


def test_manual_describes_every_option_in_order():
    # Only the kit ships the manual and setup; the workspace that exports it has neither.
    if not os.path.exists(os.path.join(ROOT, "setup.sh")):
        return
    # The manual words each part itself; only the names must match the options, in order.
    options = load({"MOTTORI_INSTANCE": ROOT})
    with open(os.path.join(ROOT, "MANUAL.md"), encoding="utf-8") as f:
        text = f.read()
    section = text.split("### The optional parts", 1)[1].split("\n### ", 1)[0]
    names = re.findall(r"^- \*\*([a-z]+): ", section, flags=re.M)
    assert names == [o["name"] for o in options.OPTIONS], names


def test_on_and_off_redraw_the_state_page():
    """A command that changed the configuration redraws the state page, so the next commit does not
    find the page older than the configuration."""
    with instance() as (root, env):
        def current():
            code = "import sys; sys.path.insert(0, 'tools'); import now; print(now.snapshots_current())"
            return subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True,
                                  text=True).stdout.strip()
        subprocess.run([sys.executable, "tools/now.py", "render"], cwd=root, env=env, capture_output=True)
        assert current() == "True"
        # A change written past options.py leaves the page behind the configuration.
        cfg = config(root)
        cfg["options"] = {"declined": []}
        write(root, "instance/config.json", json.dumps(cfg, indent=2) + "\n")
        assert current() == "False"
        r = run(root, env, "off", "deliver")
        assert r.returncode == 0 and "is off" in r.stdout, r.stdout + r.stderr
        assert current() == "True"
        r = run(root, env, "on", "deliver")
        assert r.returncode == 1 and current() == "True", r.stdout + r.stderr


TESTS = [
    test_a_missing_need_prints_the_steps_and_changes_nothing,
    test_with_the_need_in_place_on_writes_the_settings_and_runs_the_first_step,
    test_the_model_is_downloaded_only_after_one_yes,
    test_at_a_terminal_only_a_yes_downloads_the_model,
    test_on_puts_back_settings_the_search_does_not_read,
    test_the_list_shows_on_only_what_the_search_reads,
    test_on_takes_the_empty_prefixes_the_search_accepts,
    test_the_real_index_agrees_with_the_list,
    test_setup_lists_once_and_changes_only_what_is_typed,
    test_setup_turns_meaning_on_only_when_the_local_server_already_answers,
    test_manual_describes_every_option_in_order,
    test_the_list_and_doctor_read_the_same_retention,
    test_on_and_off_redraw_the_state_page,
]


def main():
    failed = []
    with testlib.http_stand_ins():
        for test in TESTS:
            try:
                test()
                print(f"✓ {test.__name__}")
            except Exception as exc:  # noqa: BLE001
                failed.append(test.__name__)
                print(f"✗ {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"options: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
