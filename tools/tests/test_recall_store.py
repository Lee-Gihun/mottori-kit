#!/usr/bin/env python3
"""recall_store.py and recall_meaning.py: the store of the owner's typed messages, the lists a
search prints, and the optional list by meaning."""
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler

import testlib


TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECALL = os.path.join(TOOLS, "recall.py")
SESSION = "0a1b2c3d-0000-4000-8000-000000000001"
HEAD = re.compile(r"^■ (\d{4}-\d\d-\d\d \d\d:\d\d) \[(\w+)\] ([0-9a-f]{8}:\d+)")


def fixture():
    base = tempfile.mkdtemp(prefix="recall-store-")
    root = os.path.join(base, "instance")
    home = os.path.join(base, "home")
    os.makedirs(os.path.join(root, "instance"))
    os.makedirs(os.path.join(home, ".codex", "sessions"))
    return base, root, home


def stamp(hour, minute, day=17):
    return datetime.datetime(2026, 9, day, hour, minute).astimezone().isoformat()


def user(root, ident, text, at, **extra):
    row = {"type": "user", "uuid": ident, "sessionId": SESSION, "timestamp": at, "cwd": root,
           "message": {"content": text}}
    row.update(extra)
    return row


def assistant(root, ident, text, at):
    return {"type": "assistant", "uuid": ident, "sessionId": SESSION, "timestamp": at,
            "cwd": root, "message": {"content": [{"type": "text", "text": text}]}}


def transcript(home, root, rows, name=SESSION):
    key = "".join(c if c.isascii() and (c.isalnum() or c == "-") else "-" for c in root)
    folder = os.path.join(home, ".claude", "projects", key)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def recall(root, home, *args, ok=True):
    result = subprocess.run([sys.executable, RECALL, *args], cwd=root, capture_output=True,
                            text=True, env=dict(os.environ, HOME=home, MOTTORI_INSTANCE=root))
    if ok:
        assert result.returncode == 0, result.stderr + result.stdout
    return result


def hits(output):
    return [line for line in output.splitlines() if HEAD.match(line)]


def private(root, name):
    return os.path.join(root, "_private", "state", name)


def test_store_reads_only_what_was_added_and_follows_the_files():
    base, root, home = fixture()
    try:
        first = "STORE early message about the harbour"
        # The store notices a rewrite by the 256 bytes before where it stopped, so the reply after the
        # first message is longer than that: the edit below must fall outside that window whatever
        # the length of the temporary folder's path, which the records carry (short on Linux).
        path = transcript(home, root, [user(root, "u1", first, stamp(9, 0)),
                                       assistant(root, "a1", "noted " + "and more " * 40, stamp(9, 1))])
        out = recall(root, home, "find", "where is the harbour", "--role", "user").stdout
        assert len(hits(out)) == 1 and "harbour" in out, out
        assert "Searched: 1 messages the owner typed, 2026-09-17 to 2026-09-17 (claude)" in out, out
        assert os.path.isfile(private(root, "recall-store.json"))
        with open(private(root, "recall-queries.jsonl"), encoding="utf-8") as f:
            logged = [json.loads(line) for line in f]
        assert logged[-1]["query"] == "where is the harbour" and logged[-1]["shown"] == {
            "words": 1, "short": 0}, logged
        assert "harbour" not in json.dumps(logged[-1]["shown"]) + json.dumps(logged[-1]["options"])
        # The coverage line names when the store was last checked, not when it last grew.
        with open(private(root, "recall-store.json"), encoding="utf-8") as f:
            saved = json.load(f)
        saved["updated"] = "2026-01-01T00:00:00+00:00"
        with open(private(root, "recall-store.json"), "w", encoding="utf-8") as f:
            json.dump(saved, f)
        out = recall(root, home, "find", "where is the harbour", "--role", "user").stdout
        assert "2026-01-01 00:00" not in out and "store checked" in out, out
        # An earlier line changed in place is not read again; an added line is.
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("harbour", "lighter"))
        transcript(home, root, [user(root, "u2", "STORE later message about the lantern",
                                     stamp(9, 5))])
        out = recall(root, home, "find", "lantern or lighter", "--role", "user").stdout
        assert "lantern" in out and "lighter" not in out, out
        # A file that shrank is read again from the start.
        with open(path, encoding="utf-8") as f:
            rows = f.readlines()
        with open(path, "w", encoding="utf-8") as f:
            f.write(rows[0])
        out = recall(root, home, "find", "lantern or lighter", "--role", "user").stdout
        assert "lighter" in out and "lantern" not in out, out
        # A file rewritten in place to a larger size is read again too.
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(user(root, "u4", "STORE replaced lantern " + "pad " * 50,
                                    stamp(9, 6))) + "\n")
        out = recall(root, home, "find", "lantern or lighter", "--role", "user").stdout
        assert "replaced lantern" in out and "lighter" not in out, out
        # A deleted file takes its messages with it, and the coverage line says so.
        os.remove(path)
        out = recall(root, home, "find", "lighter", "--role", "user").stdout
        assert not hits(out) and "1 left with deleted transcripts" in out, out
        # The store is a cache: deleted, it is built again by the next search.
        transcript(home, root, [user(root, "u3", "STORE rebuilt message", stamp(9, 9))])
        os.remove(private(root, "recall-store.json"))
        out = recall(root, home, "find", "rebuilt", "--role", "user").stdout
        assert len(hits(out)) == 1, out
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_word_list_scores_words_and_character_pairs():
    base, root, home = fixture()
    try:
        transcript(home, root, [
            user(root, "k", "회상 도구는 문장으로 물어야 잘 찾는다", stamp(9, 0)),
            user(root, "j", "検索結果をまとめる", stamp(9, 1)),
            user(root, "w", "ＲＥＴＲＩＥＶＡＬ budget stays small", stamp(9, 2)),
            user(root, "b", "검색은 BM25로 한다", stamp(9, 3)),
            user(root, "x", "unrelated note on lunch", stamp(9, 4))])
        cases = (("왜 문장으로 물어야 하지", "회상 도구"), ("結果", "検索結果"),
                 ("retrieval", "ＲＥＴＲＩＥＶＡＬ"), ("구는문장", "회상 도구"),
                 # A term written against a particle is still the term.
                 ("bm25 쓰나", "BM25로"))
        for query, expected in cases:
            out = recall(root, home, "find", query, "--role", "user").stdout
            assert hits(out) and expected in hits(out)[0], (query, out)
        # The pair across a single space counts; the query matched with spaces ignored is
        # marked as exact and gains nothing over other lines.
        out = recall(root, home, "find", "물어야잘", "--role", "user").stdout
        assert "[exact]" in hits(out)[0], out
        assert "ask in a full sentence" in out, out
        out = recall(root, home, "find", "why does the retrieval budget stay small",
                     "--role", "user").stdout
        assert "ask in a full sentence" not in out and "budget" in hits(out)[0], out
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_short_replies_have_their_own_list_with_the_text_before_them():
    base, root, home = fixture()
    try:
        transcript(home, root, [
            user(root, "u1", "what should happen to the old archive?", stamp(9, 0)),
            assistant(root, "a1", "Shall I move the archive to cold storage and keep an index?",
                      stamp(9, 1)),
            user(root, "u2", "yes, do that", stamp(9, 2))])
        out = recall(root, home, "find", "move the archive to cold storage", "--role",
                     "user").stdout
        words, _, short = out.partition("Short replies")
        assert "yes, do that" not in words, out
        assert "cold storage" in short and short.count("yes, do that") == 1, out
        assert "read both" in out, out
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_only_the_asking_message_is_left_out_not_what_was_typed_a_moment_ago():
    """Words typed a minute ago, in another session or earlier in this one, are found. The one
    message left out is the newest of the session written last, which is the question."""
    base, root, home = fixture()
    try:
        def ago(seconds):
            return (datetime.datetime.now().astimezone() - datetime.timedelta(seconds=seconds)).isoformat()
        other = transcript(home, root, [user(root, "o1", "the party is at the MARIGOLD rooftop", ago(90))],
                           name="11111111-1111-4111-8111-111111111111")
        old = time.time() - 60
        os.utime(other, (old, old))
        transcript(home, root, [
            user(root, "e1", "earlier here: the MARIGOLD caterer is booked", ago(240)),
            user(root, "q1", "where is the MARIGOLD party?", ago(5))])
        out = recall(root, home, "find", "MARIGOLD", "--role", "user").stdout
        assert "MARIGOLD rooftop" in out and "MARIGOLD caterer" in out, out
        assert "where is the MARIGOLD party" not in out and "it is the turn that is asking" in out, out
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_lines_fit_the_budget_and_the_asking_turn_is_left_out():
    base, root, home = fixture()
    try:
        rows = [user(root, f"m{i}", f"PLENTY message {i} " + "padding words " * 40,
                     stamp(8, i)) for i in range(40)]
        now = datetime.datetime.now().astimezone().isoformat()
        rows.append(user(root, "now", "PLENTY asked right now", now))
        transcript(home, root, rows)
        out = recall(root, home, "find", "plenty message", "--role", "user", "--max",
                     "30").stdout
        assert len(hits(out)) == 30 and len(out.encode("utf-8")) <= 4000, (len(out), out)
        assert "10 more of 40 matching messages" in out, out
        assert "asked right now" not in out and "it is the turn that is asking" in out, out
        oldest = recall(root, home, "find", "plenty message", "--role", "user", "--order",
                        "oldest").stdout
        times = [HEAD.match(line).group(1) for line in hits(oldest)]
        assert times == sorted(times) and "time order" in oldest, oldest
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_time_limits_list_what_he_typed_nearest_first():
    base, root, home = fixture()
    try:
        transcript(home, root, [user(root, f"t{h}{m}", f"TIMED at {h}:{m:02d}", stamp(h, m))
                                for h, m in ((10, 0), (10, 20), (10, 40), (11, 30))]
                   + [user(root, "bad", "TIMED when unknown", "not a time")])
        out = recall(root, home, "find", "--before", "2026-09-17 10:45").stdout
        assert [line.split("· ")[-1] for line in hits(out)] == ["TIMED at 10:40",
                                                                 "TIMED at 10:20"], out
        out = recall(root, home, "find", "--near", "2026-09-17 11:00", "--minutes",
                     "40").stdout
        assert [line.split("· ")[-1] for line in hits(out)] == [
            "TIMED at 10:40", "TIMED at 11:30", "TIMED at 10:20"], out
        out = recall(root, home, "find", "timed", "--role", "user", "--since",
                     "2026-09-17 10:30", "--until", "2026-09-17 11:00").stdout
        assert [line.split("· ")[-1] for line in hits(out)] == ["TIMED at 10:40"], out
        assert "skipped as malformed" in out and "time does not parse): 1." in out, out
        # A long message sent again later in the same session is listed at its later time too.
        resent = "RESENT please rerun the export and check every file listed in the report"
        transcript(home, root, [user(root, "r1", resent, stamp(12, 0)),
                                user(root, "r2", resent, stamp(15, 0))])
        out = recall(root, home, "find", "--before", "2026-09-17 15:05").stdout
        assert [line.split("· ")[-1] for line in hits(out)] == [resent], out
        # A width without a window would be silently ignored, so it is refused.
        refused = recall(root, home, "find", "--minutes", "5", ok=False)
        assert refused.returncode == 2 and "--before or --near" in refused.stderr, refused
        # A --since with a time is honoured to the minute, so it searches the owner's words.
        out = recall(root, home, "find", "timed", "--since", "2026-09-17 10:30").stdout
        assert [line.split("· ")[-1] for line in hits(out)] == ["TIMED at 11:30",
                                                                 "TIMED at 10:40"], out
        refused = recall(root, home, "find", "timed", "--since", "2026-09-17 10:30", "--json",
                         ok=False)
        assert refused.returncode == 2 and "--since with a time" in refused.stderr, refused
        refused = recall(root, home, "find", "timed", "--before", "2026-09-17 10:45",
                         "--role", "assistant", ok=False)
        assert refused.returncode == 2 and "--before" in refused.stderr, refused.stderr
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_runtime_written_records_stay_out_of_the_owner_list():
    base, root, home = fixture()
    try:
        transcript(home, root, [
            user(root, "s", "RUNTIME summary of the earlier conversation", stamp(9, 0),
                 isCompactSummary=True),
            user(root, "h", "RUNTIME hook feedback", stamp(9, 1), isMeta=True),
            user(root, "n", "RUNTIME task finished", stamp(9, 2),
                 origin={"kind": "task-notification"}),
            user(root, "i", "[Request interrupted by user] RUNTIME", stamp(9, 3)),
            user(root, "o", "RUNTIME words the owner typed", stamp(9, 4))])
        out = recall(root, home, "find", "runtime", "--role", "user").stdout
        assert [line.split("· ")[-1] for line in hits(out)] == [
            "RUNTIME words the owner typed"], out
        old = recall(root, home, "find", "RUNTIME", "--include-system").stdout
        assert "summary of the earlier" in old and "hook feedback" in old, old
        assert "--include-system" in recall(root, home, "find", "--help").stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_a_locator_opens_the_message_with_its_neighbours():
    base, root, home = fixture()
    try:
        transcript(home, root, [
            user(root, "u1", "OPEN first question", stamp(9, 0)),
            assistant(root, "a1", "first answer", stamp(9, 1)),
            user(root, "u2", "OPEN the message to open " + "long " * 200, stamp(9, 2)),
            assistant(root, "a2", "second answer", stamp(9, 3))])
        out = recall(root, home, "find", "message to open", "--role", "user").stdout
        locator = HEAD.match(hits(out)[0]).group(3)
        opened = recall(root, home, "find", locator, "--around", "1").stdout
        assert "first answer" in opened and "second answer" in opened, opened
        assert "long " * 200 in opened, opened
        assert "OPEN first question" not in opened, opened
        # Time-ordered ids share their start across sessions begun in the same minute; ids
        # that still share their end open both messages instead of whichever comes first.
        for ident, word in (("0199a1b2-0000-7000-8000-00000000aaa1", "apples"),
                            ("0199a1b2-0000-7000-8000-00000000aaa2", "pears"),
                            ("0299a1b2-0000-7000-8000-00000000aaa2", "plums")):
            transcript(home, root, [dict(user(root, "v" + word, "LOCATE " + word, stamp(8, 0)),
                                         sessionId=ident)], name=ident)
        out = recall(root, home, "find", "locate apples pears plums", "--role", "user").stdout
        locators = {line.split("· ")[-1]: HEAD.match(line).group(3) for line in hits(out)}
        assert locators["LOCATE apples"] != locators["LOCATE pears"], out
        opened = recall(root, home, "find", locators["LOCATE apples"], "--around", "0").stdout
        assert "apples" in opened and "pears" not in opened, opened
        opened = recall(root, home, "find", locators["LOCATE pears"], "--around", "0").stdout
        assert "pears" in opened and "plums" in opened, opened
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_a_large_first_build_answers_the_old_way_and_index_builds_it():
    base, root, home = fixture()
    try:
        transcript(home, root, [user(root, "u1", "LARGE history message", stamp(9, 0)),
                                assistant(root, "a1", "LARGE assistant reply", stamp(9, 1)),
                                user(root, "u2", "LARGE later message", stamp(16, 0))])

        def first_search(*args):
            code = ("import sys; sys.path.insert(0, %r); import recall_store, recall; "
                    "recall_store.FIRST_BUILD_BYTES = 0; sys.argv = ['recall.py'] + %r; "
                    "sys.exit(recall.main())" % (os.path.join(TOOLS, "lib"), ["find", *args]))
            return subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True,
                                  text=True, env=dict(os.environ, HOME=home,
                                                      MOTTORI_INSTANCE=root))
        result = first_search("LARGE", "--role", "user")
        assert result.returncode == 0, result.stderr
        assert "recall.py index" in result.stdout and "■ 1 ·" in result.stdout, result.stdout
        assert "assistant reply" not in result.stdout, result.stdout
        # The transcript search has no window, so a search by time waits for the index.
        for args in (["--before", "2026-09-17 09:10"], ["LARGE", "--before", "2026-09-17 09:10"]):
            result = first_search(*args)
            assert result.returncode == 1 and "recall.py index" in result.stdout, result
            assert "■" not in result.stdout and "old way" not in result.stdout, result.stdout
        assert not os.path.exists(private(root, "recall-store.json"))
        assert "Indexed 2 owner messages" in recall(root, home, "index").stdout
        assert hits(recall(root, home, "find", "large", "--role", "user").stdout)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# A stand-in for a local embeddings route: a text's vector counts the words of a few topics it
# holds, so a synonym is close in meaning and far in words.
TOPICS = ({"archive", "storage", "vault", "cellar"}, {"lunch", "meal", "noodles", "food"},
          {"deploy", "release", "rollout", "ship"}, {"budget", "money", "cost", "price"})


class Embeddings(BaseHTTPRequestHandler):
    """The route a StandIn registers. It answers inside the program that connects (testlib's
    stand-ins), so its settings and the texts it was sent are files in its state folder."""
    def do_POST(self):
        with open(os.path.join(self.server.state, "settings.json"), encoding="utf-8") as f:
            o = json.load(f)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        line = (json.dumps([body["model"], body["input"]]) + "\n").encode("utf-8")
        fd = os.open(os.path.join(self.server.state, "inputs.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        if o["status"] != 200:   # an error, or a redirect to another host
            self.send_response(o["status"])
            self.send_header("Location", "http://192.0.2.1:9/v1/embeddings")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        time.sleep(o["delay"] if body["input"][0].startswith("Q: ") else o["document_delay"])
        data = [{"index": n, "embedding": StandIn.vector(text, body["model"])
                 if o["dims"] is None else StandIn.wide(text, o["dims"])}
                for n, text in enumerate(body["input"])]
        raw = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if o["trickle"] and not body["input"][0].startswith("Q: "):
            for byte in raw[:15]:   # a body begun slowly, each read inside a timeout
                self.wfile.write(bytes([byte]))
                self.wfile.flush()
                time.sleep(o["trickle"])
            raw = raw[15:]
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class StandIn:
    def __init__(self, delay=0.0, document_delay=None, status=200, trickle=0.0, dims=None):
        self.state = tempfile.mkdtemp(prefix="recall-stand-in-")
        with open(os.path.join(self.state, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"delay": delay, "status": status, "trickle": trickle, "dims": dims,
                       "document_delay": delay if document_delay is None else document_delay}, f)
        self.url = testlib.register_stand_in(__file__, "Embeddings", self.state) + "/v1/embeddings"

    @property
    def inputs(self):
        """(model, texts) of every request it was sent, in order."""
        path = os.path.join(self.state, "inputs.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [tuple(json.loads(line)) for line in f if line.endswith("\n")]

    @staticmethod
    def vector(text, model):
        words = re.findall(r"[a-z]+", text.lower())
        out = [float(sum(w in topic for w in words)) for topic in TOPICS] + [0.1]
        return out + [0.0] * 3 if model == "longer-model" else out

    @staticmethod
    def wide(text, dims):
        """A vector of dims values that only the text decides, for measuring at a real size."""
        seed = int.from_bytes(text.encode("utf-8")[-8:].rjust(8, b"\0"), "big")
        return [((seed * (i + 1) * 2654435761) % 2001 - 1000) / 1000 for i in range(dims)]

    def texts(self):
        return [x for _model, batch in self.inputs for x in batch]

    def close(self):
        shutil.rmtree(self.state, ignore_errors=True)


def configure(root, url, model="stand-in"):
    with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"instance": {"recall_meaning": {
            "endpoint": url, "model": model, "query_prefix": "Q: ",
            "document_prefix": "D: "}}}, f)


def test_list_by_meaning_is_off_unless_set_and_never_leaves_the_machine():
    base, root, home = fixture()
    server = StandIn()
    try:
        transcript(home, root, [user(root, "u1", "MEANING keep the old files in the cellar",
                                     stamp(9, 0))])
        out = recall(root, home, "find", "where do old files go", "--role", "user").stdout
        assert hits(out) and "List by meaning" not in out and not server.inputs, out
        assert "off (config.instance.recall_meaning names no endpoint" in recall(
            root, home, "index").stdout
        # A half setting turns off this list alone, and both commands say what it needs.
        with open(os.path.join(root, "instance", "config.json"), "w") as f:
            json.dump({"instance": {"recall_meaning": {"endpoint": server.url}}}, f)
        out = recall(root, home, "find", "where do old files go", "--role", "user").stdout
        assert hits(out) and not server.inputs, out
        assert "off, because config.instance.recall_meaning needs endpoint and model" in out
        assert "off, because config.instance.recall_meaning needs endpoint and model" in recall(
            root, home, "index").stdout
        for url in ("http://192.0.2.1:11434/v1/embeddings", "http://example.invalid/v1/embeddings",
                    "http://127.0.0.1.example.invalid/v1/embeddings"):
            configure(root, url)
            out = recall(root, home, "find", "where do old files go", "--role", "user").stdout
            assert "is not on this machine" in out and hits(out), (url, out)
            assert "with similarity" not in out, out
            index = recall(root, home, "index", ok=False)
            assert index.returncode == 1 and "is not on this machine" in index.stdout, index
            assert "List by meaning: on" not in index.stdout, index
        # A proxy named in the environment is not used for the local endpoint.
        configure(root, server.url)
        result = subprocess.run([sys.executable, RECALL, "find", "where do old files go",
                                 "--role", "user"], cwd=root, capture_output=True, text=True,
                                env=dict(os.environ, HOME=home, MOTTORI_INSTANCE=root,
                                         http_proxy="http://192.0.2.1:9",
                                         HTTP_PROXY="http://192.0.2.1:9", NO_PROXY=""))
        assert "with similarity" in result.stdout and server.inputs, result.stdout + result.stderr
    finally:
        server.close()
        shutil.rmtree(base, ignore_errors=True)


def test_list_by_meaning_is_built_added_to_and_rebuilt():
    base, root, home = fixture()
    server = StandIn()
    try:
        configure(root, server.url)
        long_text = "MEANING notes " + "plain words " * 80 + "and then the noodles at noon"
        transcript(home, root, [
            user(root, "u1", "MEANING put the backups in the vault", stamp(9, 0)),
            user(root, "u2", long_text, stamp(9, 1)),
            user(root, "u3", "MEANING the backups go to storage tonight", stamp(9, 2)),
            assistant(root, "a1", "Shall I ship the release on Friday?", stamp(9, 3)),
            user(root, "u4", "yes", stamp(9, 4)),
            user(root, "u5", "MEANING backups backups backups", stamp(9, 5))]
            + [user(root, f"f{i}", f"MEANING ship item {i}", stamp(8, i, day=16))
               for i in range(9)])
        out = recall(root, home, "find", "where is the archive kept", "--role", "user").stdout
        meaning, _, rest = out.partition("By words")
        words, _, short = rest.partition("Short replies")
        lines = hits(meaning)
        assert "by meaning, with similarity" in meaning and lines, out
        assert "vault" in lines[0] or "storage" in lines[0], out
        assert re.search(r"· \d\.\d\d · ", lines[0]), out
        # The text before a short reply is embedded with the reply and never ranks in the list
        # by meaning; documents carry the document prefix, the query the query prefix.
        assert all(x.startswith("D: ") for x in server.texts()[1:]), server.texts()
        assert server.texts()[0] == "Q: where is the archive kept", server.texts()
        assert any(x.startswith("D: Shall I ship") and x.endswith("\nyes")
                   for x in server.texts()), server.texts()
        assert "Shall I ship" not in meaning, out
        # The best piece of a long message is its score.
        out = recall(root, home, "find", "what did we have for lunch", "--role", "user").stdout
        assert "MEANING notes" in hits(out)[0], out
        # Found by both lists: marked once and not repeated in the word list.
        out = recall(root, home, "find", "backups in the vault", "--role", "user").stdout
        meaning, _, words = out.partition("By words")
        assert "[both]" in meaning and "vault" not in words, out
        # A decision by short reply is found through the text before it, in its own list.
        out = recall(root, home, "find", "should the release go out on friday", "--role",
                     "user").stdout
        assert "Short replies" in out and "→ yes" in out.partition("Short replies")[2], out
        assert re.search(r"· \d\.\d\d · Shall I ship", out.partition("Short replies")[2]), out
        # A record cut off at the end of the vectors file is made again, not a failed search;
        # bytes after the last whole record are ignored, and written over at the next save.
        path = private(root, "recall-vectors.bin")
        for cut, made in ((20, 1), (-5, 0)):   # into the last record (the reply), past the end
            with open(path, "rb") as f:
                raw = f.read()
            with open(path, "wb") as f:
                f.write(raw[:-cut] if cut > 0 else raw + b"T" * -cut)
            before = len(server.texts())
            assert hits(recall(root, home, "find", "backups in the vault", "--role", "user").stdout)
            assert len(server.texts()) - before == 1 + made, (cut, server.texts()[before:])
            assert os.path.getsize(path) == len(raw) + (5 if cut < 0 else 0), (cut, len(raw))
        # The vectors kept as JSON before are converted once, with nothing embedded again.
        with open(path, "rb") as f:
            first, data = f.readline(), f.read()
        meta = json.loads(first)
        size = 1 + 16 + meta["dims"]
        data = data[:len(data) // size * size]   # without the bytes added above
        old = {"header": meta["header"], "dims": meta["dims"], "texts": {}, "replies": {}}
        for at in range(0, len(data), size):
            kind, key = data[at:at + 1], data[at + 1:at + 17].decode()
            packed = base64.b64encode(data[at + 17:at + size]).decode()
            if kind == b"r":
                old["replies"][key] = packed
            else:
                old["texts"].setdefault(key, []).append(packed)
        os.remove(path)
        with open(private(root, "recall-vectors.json"), "w", encoding="utf-8") as f:
            json.dump(old, f)
        before = len(server.texts())
        out = recall(root, home, "find", "backups in the vault", "--role", "user").stdout
        assert "[both]" in out and server.texts()[before:] == ["Q: backups in the vault"], out
        assert not os.path.exists(private(root, "recall-vectors.json"))
        with open(path, "rb") as f:
            assert f.read() == first + data
        # An added message is embedded alone; a search by time makes no call at all.
        before = len(server.texts())
        transcript(home, root, [user(root, "u6", "MEANING the cost of the plan", stamp(9, 6))])
        recall(root, home, "find", "--before", "2026-09-17 09:30")
        assert len(server.texts()) == before, server.texts()[before:]
        out = recall(root, home, "find", "how much money does it take", "--role", "user").stdout
        assert server.texts()[before + 1:] == ["D: MEANING the cost of the plan"], server.texts()
        assert "cost of the plan" in hits(out)[0], out
        state = recall(root, home, "index").stdout
        assert "List by meaning: on (stand-in); 15 messages in 16 pieces and 1 short replies" in state, state
        # Another model, or a vector of another length, makes every vector again.
        before = len(server.texts())
        for model in ("other-model", "longer-model"):
            configure(root, server.url, model)
            out = recall(root, home, "find", "where is the archive kept", "--role", "user").stdout
            assert "being made again" in out and "with similarity" in out, out
            assert len(server.texts()) - before == 1 + 16 + 1, server.texts()[before:]
            before = len(server.texts())
        # Two index runs at once: the second waits for the first and has nothing left to embed.
        os.remove(private(root, "recall-vectors.bin"))
        env = dict(os.environ, HOME=home, MOTTORI_INSTANCE=root)
        runs = [subprocess.Popen([sys.executable, RECALL, "index"], cwd=root, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(2)]
        assert [run.wait(60) for run in runs] == [0, 0], [run.communicate() for run in runs]
        assert len(server.texts()) - before == 16 + 1, server.texts()[before:]
    finally:
        server.close()
        shutil.rmtree(base, ignore_errors=True)


def test_endpoint_down_leaves_the_word_lists_and_lines_fit():
    base, root, home = fixture()
    slow = StandIn(delay=3)
    stalled = StandIn(document_delay=12)
    trickled = StandIn(trickle=0.4)
    try:
        rows = [user(root, f"m{i}", f"PLENTY archive message {i} " + "padding words " * 40,
                     stamp(8, i)) for i in range(30)]
        transcript(home, root, rows)
        port = 47000   # no stand-in answers there, so the connection is refused
        for url in ("http://127.0.0.1:%d/v1/embeddings" % port, slow.url):
            configure(root, url)
            started = time.monotonic()
            out = recall(root, home, "find", "plenty archive message", "--role", "user").stdout
            assert time.monotonic() - started < 6, out
            reason = "no answer within 2 s" if url == slow.url else "ConnectionRefusedError"
            assert "gave no embeddings (%s)" % reason in out and len(hits(out)) == 8, out
            assert "with similarity" not in out, out
        for status in (307, 500):
            with StandInRunning(status=status) as server:
                configure(root, server.url)
                out = recall(root, home, "find", "plenty archive message", "--role", "user").stdout
                assert "gave no embeddings (HTTP %d)" % status in out, out
                assert len(hits(out)) == 8, out
        # Documents an endpoint stalls on, or sends slowly, hold a search only for its bound.
        for server in (stalled, trickled):
            configure(root, server.url)
            started = time.monotonic()
            out = recall(root, home, "find", "plenty archive message", "--role", "user").stdout
            assert time.monotonic() - started < 4.5 and "by meaning: 0 of 30." in out, out
        with StandInRunning() as server:
            configure(root, server.url)
            out = recall(root, home, "find", "plenty archive message", "--role", "user",
                         "--max", "20").stdout
            assert "with similarity" in out and len(hits(out)) == 30, out
            assert len(out.encode("utf-8")) <= 4000, (len(out.encode("utf-8")), out)
    finally:
        slow.close()
        stalled.close()
        trickled.close()
        shutil.rmtree(base, ignore_errors=True)


PEAK = """
import contextlib, io, runpy, sys, tracemalloc
tracemalloc.start()
sys.argv = sys.argv[1:]
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as stop:
    if stop.code not in (0, None):
        raise
print(tracemalloc.get_traced_memory()[1], file=sys.__stdout__)
"""


def peak_bytes(root, home, *args):
    """The most memory, in bytes, that a recall.py run had allocated at one time.

    The run is a child process that counts its own Python allocations. The count does not move
    with what else the machine is doing, which the process's resident size did.
    """
    result = subprocess.run([sys.executable, "-c", PEAK, RECALL, *args], cwd=root,
                            capture_output=True, text=True, check=True,
                            env=dict(os.environ, HOME=home, MOTTORI_INSTANCE=root))
    return int(result.stdout)


def test_a_search_by_meaning_holds_the_vectors_once():
    """On 10,000 stored pieces at embeddinggemma's 768 dimensions, a search by meaning takes no
    more memory than the same search by words plus what the vectors need: every piece's signed
    bytes with its kind and key (dims + 17 bytes), its message's place in the key table (under
    300 bytes a message) and 3 MB for the query's request and answer."""
    base, root, home = fixture()
    server = StandIn(dims=768)
    try:
        pieces = 10000
        words = ["harbour", "lantern", "archive", "storage", "vault", "boat", "winter", "key"]
        transcript(home, root, [user(root, f"u{i}", f"PEAK {i} " + " ".join(
            words[(i * 7 + j * 3) % len(words)] for j in range(60)),
            datetime.datetime(2026, 9, 1 + i // 1440 % 28, i // 60 % 24, i % 60).astimezone()
            .isoformat()) for i in range(pieces)])
        configure(root, server.url)
        assert "10000 messages in 10000 pieces" in recall(root, home, "index").stdout
        query = ("find", "where is the harbour in winter", "--role", "user")
        by_meaning = peak_bytes(root, home, *query)
        with open(os.path.join(root, "instance", "config.json"), "w", encoding="utf-8") as f:
            json.dump({}, f)
        by_words = peak_bytes(root, home, *query)
        bound = pieces * (768 + 17) + pieces * 300 + 3 * 2 ** 20
        assert by_meaning - by_words <= bound, (by_meaning, by_words, bound)
    finally:
        server.close()
        shutil.rmtree(base, ignore_errors=True)


START = """
import json, os, subprocess, sys
sys.path.insert(0, %r)
import dispatch, recall_store
started = []
class Counting(subprocess.Popen):
    def __init__(self, args, *rest, **options):
        started.append(args)
        super().__init__(args, *rest, **options)
subprocess.Popen = Counting
dispatch._index(None)
print(json.dumps([len(started), recall_store.catch_up_running()]))
""" % TOOLS


def session_start(root, home):
    """[processes the session start's index step started, whether a catch-up runs after it]."""
    env = dict(os.environ, HOME=home, MOTTORI_INSTANCE=root)
    env.pop("MOTTORI_INTERNAL_RUN", None)
    env.pop("MOTTORI_HOOK_CANARY", None)
    result = subprocess.run([sys.executable, "-c", START], cwd=root, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def in_store(root, code):
    """What code prints with recall_store imported in this instance."""
    result = subprocess.run([sys.executable, "-c", "import json, sys; sys.path.insert(0, %r); "
                             "import recall_store; print(json.dumps(%s))" % (os.path.join(TOOLS, "lib"), code)],
                            cwd=root, capture_output=True, text=True,
                            env=dict(os.environ, MOTTORI_INSTANCE=root))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_session_start_catches_up_behind_the_session():
    """Behind: one detached process, none while it runs, a search that does not wait for it and
    says how much is indexed, its end said once; nothing behind: a process that does nothing."""
    base, root, home = fixture()
    server = StandIn(document_delay=1.0)   # five batches of documents, a second each
    try:
        transcript(home, root, [user(root, f"c{i}", f"CATCH message {i} about the harbour",
                                     stamp(8, i % 60, day=10 + i // 60)) for i in range(150)])
        configure(root, server.url)
        assert session_start(root, home) == [1, True]
        assert session_start(root, home) == [0, True]
        out = recall(root, home, "find", "where is the harbour", "--role", "user").stdout
        assert in_store(root, "recall_store.catch_up_running()"), "the search waited for it"
        share = re.search(r"by meaning: (\d+) of 150, the rest being indexed behind the session",
                          out)
        assert share and int(share.group(1)) < 150, out
        # A catch-up that runs or ends well says nothing at session start.
        assert in_store(root, "recall_store.catch_up_notice(True)") is None
        deadline = time.monotonic() + 60
        while in_store(root, "recall_store.catch_up_running()") and time.monotonic() < deadline:
            time.sleep(0.2)
        assert in_store(root, "recall_store.catch_up_notice(False)") is None
        assert in_store(root, "recall_store.catch_up_notice(False)") is None
        # Every message was embedded once, by the catch-up alone.
        assert sum(1 for x in server.texts() if x.startswith("D: ")) == 150, server.texts()
        # Nothing behind: the process started finds nothing to do and leaves the record alone.
        record = os.path.join(root, "_private", "state", "recall-catch-up.json")
        before = open(record, encoding="utf-8").read()
        assert session_start(root, home)[0] == 1
        deadline = time.monotonic() + 30
        while in_store(root, "recall_store.catch_up_running()") and time.monotonic() < deadline:
            time.sleep(0.2)
        assert open(record, encoding="utf-8").read() == before
        assert sum(1 for x in server.texts() if x.startswith("D: ")) == 150, server.texts()
        out = recall(root, home, "find", "where is the harbour", "--role", "user").stdout
        assert "by meaning: 150 of 150." in out, out
    finally:
        server.close()
        shutil.rmtree(base, ignore_errors=True)


STARTS_ONLY = """
import json, subprocess, sys
sys.path.insert(0, %r)
import dispatch, recall_store
read, started = [], []
def reading(*args, **options):
    read.append(args)
    raise AssertionError("the session start read the session stores")
recall_store.T.select_sources = reading
class Started:
    def __init__(self, args, *rest, **options):
        started.append(args)
subprocess.Popen = Started
dispatch._index(None)
print(json.dumps([len(read), len(started), started[0][-2:-1] if started else None]))
""" % TOOLS


def test_the_index_step_only_starts_the_catch_up():
    """The session start's index step reads no session store: it starts the detached process,
    which decides whether anything is behind, and returns."""
    base, root, home = fixture()
    try:
        env = dict(os.environ, HOME=home, MOTTORI_INSTANCE=root)
        env.pop("MOTTORI_INTERNAL_RUN", None)
        env.pop("MOTTORI_HOOK_CANARY", None)
        result = subprocess.run([sys.executable, "-c", STARTS_ONLY], cwd=root, env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == [0, 1, [os.path.join(TOOLS, "lib")]], result.stdout
    finally:
        shutil.rmtree(base, ignore_errors=True)


class StandInRunning:
    def __init__(self, **options):
        self.options = options

    def __enter__(self):
        self.server = StandIn(**self.options)
        return self.server

    def __exit__(self, *exc):
        self.server.close()


def test_eight_bit_vectors_order_pieces_as_the_float_vectors_do():
    code = """
import json, math, random, sys
sys.path.insert(0, %r)
import recall_meaning as S
random.seed(7)
def unit(v):
    n = math.sqrt(sum(x * x for x in v)); return [x / n for x in v]
query = unit([random.gauss(0, 1) for _ in range(256)])
# Pieces at similarities 0.02 apart, from 0.95 down, in shuffled order.
pieces = []
for c in random.sample([0.95 - i * 0.02 for i in range(60)], 60):
    r = [random.gauss(0, 1) for _ in range(256)]
    d = sum(a * b for a, b in zip(r, query))
    r = unit([a - d * b for a, b in zip(r, query)])
    pieces.append(unit([c * a + math.sqrt(1 - c * c) * b for a, b in zip(query, r)]))
floats = sorted(range(60), key=lambda i: -sum(a * b for a, b in zip(pieces[i], query)))
packed = sorted(range(60), key=lambda i: -S.similarity([S.pack(pieces[i])], query))
best = S.similarity([S.pack(p) for p in pieces[:5]], query)
print(json.dumps([floats == packed, abs(best - max(
    sum(a * b for a, b in zip(p, query)) for p in pieces[:5])) < 0.02,
    [len(p) for p in S.pieces("x" * 1500)], len(S.pieces("short"))]))
""" % os.path.join(TOOLS, "lib")
    base, root, _home = fixture()
    try:
        result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True,
                                text=True, env=dict(os.environ, MOTTORI_INSTANCE=root))
        assert json.loads(result.stdout) == [True, True, [800, 800, 220], 1], result
    finally:
        shutil.rmtree(base, ignore_errors=True)


TESTS = [
    test_store_reads_only_what_was_added_and_follows_the_files,
    test_word_list_scores_words_and_character_pairs,
    test_short_replies_have_their_own_list_with_the_text_before_them,
    test_only_the_asking_message_is_left_out_not_what_was_typed_a_moment_ago,
    test_lines_fit_the_budget_and_the_asking_turn_is_left_out,
    test_time_limits_list_what_he_typed_nearest_first,
    test_runtime_written_records_stay_out_of_the_owner_list,
    test_a_locator_opens_the_message_with_its_neighbours,
    test_a_large_first_build_answers_the_old_way_and_index_builds_it,
    test_list_by_meaning_is_off_unless_set_and_never_leaves_the_machine,
    test_list_by_meaning_is_built_added_to_and_rebuilt,
    test_endpoint_down_leaves_the_word_lists_and_lines_fit,
    test_eight_bit_vectors_order_pieces_as_the_float_vectors_do,
    test_a_search_by_meaning_holds_the_vectors_once,
    test_session_start_catches_up_behind_the_session,
    test_the_index_step_only_starts_the_catch_up,
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
    print(f"recall_store: {len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
