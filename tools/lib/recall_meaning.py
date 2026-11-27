#!/usr/bin/env python3
"""The optional list of the owner's messages by meaning, from a local embeddings endpoint.

It is off unless the instance configuration names an embeddings endpoint on this machine and a
model (instance.recall_meaning); the texts sent are the owner's own words, so an endpoint on any
other host is refused. recall_store.py calls it: for one search, prepare() embeds the query and
brings the stored vectors up to date within a few seconds, and the Meaning it returns gives each
stored message its similarity to the query; `recall.py index` calls update_all() and state().
The vectors are a cache beside the store (recall-vectors.bin), safe to delete like the store.
"""
import array
import base64
import hashlib
import http.client
import json
import math
import operator
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import paths as P
import safeio

# Messages this module prints in more than one place, or too long to read inline.
RECALL_MEANING_BAD = (
    "List by meaning: off, because config.instance.recall_meaning needs endpoint and model as "
    "non-empty strings, and query_prefix and document_prefix, when given, as strings."
)
RECALL_MEANING_DOWN = (
    "The list by meaning is not available now: the embeddings endpoint {endpoint} gave no "
    "embeddings ({reason})."
)
RECALL_MEANING_NOT_LOCAL = (
    "List by meaning left out: {endpoint} is not on this machine (127.0.0.1, localhost or "
    "::1), and the owner's words are never sent elsewhere."
)
RECALL_MEANING_OFF = (
    "List by meaning: off (config.instance.recall_meaning names no endpoint and model)."
)
RECALL_MEANING_ON = (
    "List by meaning: on ({model}); {messages} messages in {pieces} pieces and {replies} short "
    "replies embedded, {waiting} waiting."
)
RECALL_MEANING_REBUILT = (
    "The model, its prefixes or its vector length changed, so the vectors of the list by "
    "meaning are being made again."
)

VECTORS = P.recall_vectors()
# Measured on the owner's history: the unit embedded hardly mattered, and most messages are one
# piece of this size. Pieces of PIECE characters start every PIECE_STEP characters.
PIECE, PIECE_STEP = 800, 640
# The texts sent are the owner's own words, so they never leave this machine.
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
# A query an endpoint does not answer in this time leaves the word lists alone; a model loaded
# after idle answers within it.
ANSWER_SECONDS = 2
# Pieces sent in one request, and the time one request may take outside a search.
EMBED_BATCH = 32
BATCH_SECONDS = 30
# The vectors file: one JSON line naming the settings the vectors were made under and their
# length, then one fixed-size record per piece: a kind, the KEY_BYTES of its message's key and
# the vector as signed bytes. A text's pieces follow each other and the last one has LAST_PIECE.
PIECE_KIND, LAST_PIECE, REPLY_KIND = b"t", b"T", b"r"
KEY_BYTES = 16
# Where the vectors were kept before, as JSON with base64 pieces; converted once.
VECTORS_JSON = P.recall_vectors_json()
_dot = getattr(math, "sumprod", None) or (lambda a, b: sum(map(operator.mul, a, b)))


class EmbedError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect could name another host; the endpoint must answer itself.
    def redirect_request(self, *args, **kwargs):
        return None


def settings():
    """The configured endpoint and model with their prefixes, or None when the list is off."""
    return C.recall_meaning()


def is_local(endpoint):
    try:
        parts = urllib.parse.urlsplit(endpoint)
        return parts.scheme in ("http", "https") and parts.hostname in LOCAL_HOSTS
    except ValueError:
        return False


def embed(config, texts, prefix, timeout):
    """Unit-length vectors for texts from an OpenAI-compatible embeddings route."""
    if not is_local(config["endpoint"]):
        raise EmbedError("not local")
    body = json.dumps({"model": config["model"], "input": [prefix + x for x in texts]})
    request = urllib.request.Request(config["endpoint"], data=body.encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    # No proxy: one named in the environment would carry the texts off this machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    answer = {}

    def call():
        try:
            with opener.open(request, timeout=timeout) as response:
                answer["body"] = response.read()
        except Exception as exc:   # raised below, in the caller
            answer["error"] = exc

    # The socket timeout bounds each read, not the request; a body sent slowly would outlast it.
    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(timeout)
    try:
        if worker.is_alive():
            raise TimeoutError
        if "error" in answer:
            raise answer["error"]
        rows = json.loads(answer["body"])["data"]
        rows = sorted(rows, key=lambda row: row.get("index", 0))
        vectors = [[float(x) for x in row["embedding"]] for row in rows]
    except urllib.error.HTTPError as exc:   # a redirect it did not follow lands here too
        raise EmbedError(f"HTTP {exc.code}") from exc
    except (OSError, ValueError, KeyError, TypeError, AttributeError,
            http.client.HTTPException) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):   # one class from 3.10 on
            raise EmbedError(f"no answer within {round(timeout, 1)} s") from exc
        raise EmbedError(type(reason).__name__) from exc
    if len(vectors) != len(texts) or not all(vectors) or len({len(v) for v in vectors}) != 1:
        raise EmbedError("shape")
    out = []
    for vector in vectors:
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        out.append([x / norm for x in vector])
    return out


def pack(vector):
    """A unit vector as signed 8-bit integers; it lost nothing measured."""
    return array.array("b", [max(-127, min(127, round(x * 127))) for x in vector]).tobytes()


def pieces(text):
    """The overlapping pieces a message is embedded as; a short message is one piece."""
    return [text[a:a + PIECE] for a in range(0, max(1, len(text) - (PIECE - PIECE_STEP)),
                                             PIECE_STEP)]


def _key(text):
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:KEY_BYTES]


def reply_text(record):
    """What a short reply is embedded as: the assistant's text before it, then the reply."""
    return record["tail"] + "\n" + record["text"].strip()


def _header(config):
    return {"model": config["model"], "query_prefix": config["query_prefix"],
            "document_prefix": config["document_prefix"], "piece": [PIECE, PIECE_STEP]}


def _empty(header, dims):
    """Vectors with no record, to be written whole: data holds the records in the file's format,
    texts maps a text's key to the offsets of its pieces' vectors in data, replies a reply's key to
    its one offset in a list; saved is how much of data the file holds, None for none of it."""
    return {"header": header, "dims": dims, "data": bytearray(), "texts": {}, "replies": {},
            "saved": None, "start": 0}


def load_vectors():
    """The vectors file read once into one buffer, or None when it is missing or its first line
    is not a header."""
    try:
        with open(VECTORS, "rb") as f:
            first = f.readline()
            meta = json.loads(first)
            data = bytearray(max(0, os.fstat(f.fileno()).st_size - len(first)))
            got = f.readinto(data)
    except (OSError, ValueError):
        return None
    dims = meta.get("dims") if isinstance(meta, dict) else 0
    if not (dims is None or (type(dims) is int and dims > 0)):
        return None
    del data[got:]
    vectors = dict(_empty(meta.get("header"), dims), data=data, start=len(first))
    _index_records(vectors)
    return vectors


def _index_records(vectors):
    """Fill texts and replies from data. Data is cut after its last whole text or reply, so the
    rest of a record cut off by a crash, or a text without its last piece, is written over."""
    data, dims = vectors["data"], vectors["dims"]
    size = 1 + KEY_BYTES + (dims or 0)
    at = end = 0
    pending, last = [], None
    while dims and at + size <= len(data):
        kind, key = bytes(data[at:at + 1]), bytes(data[at + 1:at + 1 + KEY_BYTES])
        if kind not in (PIECE_KIND, LAST_PIECE, REPLY_KIND) or (pending and key != last):
            break   # a damaged file: what follows is made again
        pending.append(at + 1 + KEY_BYTES)
        last, at = key, at + size
        if kind == PIECE_KIND:
            continue
        if kind == REPLY_KIND and len(pending) > 1:
            break
        vectors["texts" if kind == LAST_PIECE else "replies"][key.decode("ascii", "replace")] = \
            pending
        pending, end = [], at
    del data[end:]
    vectors["saved"] = end


def _add(vectors, kind, key, vectors_of_pieces):
    """Append one text's pieces, or one reply, to data and index them."""
    data, offsets = vectors["data"], []
    for n, vector in enumerate(vectors_of_pieces):
        last = n == len(vectors_of_pieces) - 1
        data += (REPLY_KIND if kind == "replies" else LAST_PIECE if last else PIECE_KIND)
        data += key.encode("ascii")
        offsets.append(len(data))
        data += vector
    vectors[kind][key] = offsets


def _save_vectors(vectors):
    """Write what data holds that the file does not: the whole file when it holds none of it,
    else the records added since it was read, after its last whole text or reply."""
    if vectors["saved"] is None or not os.path.exists(VECTORS):
        head = json.dumps({"header": vectors["header"], "dims": vectors["dims"]},
                          separators=(",", ":")).encode("utf-8") + b"\n"
        safeio.atomic_write(VECTORS, head + vectors["data"])
        vectors.update(saved=len(vectors["data"]), start=len(head))
        return
    with open(VECTORS, "r+b") as f:
        f.truncate(vectors["start"] + vectors["saved"])
        f.seek(0, os.SEEK_END)
        f.write(vectors["data"][vectors["saved"]:])
    vectors["saved"] = len(vectors["data"])


def _keep_only(vectors, texts, replies):
    """Drop the vectors of texts and replies the store no longer holds; the file is then
    written whole."""
    if all(k in texts for k in vectors["texts"]) and all(k in replies for k in vectors["replies"]):
        return
    kept, dims = _empty(vectors["header"], vectors["dims"]), vectors["dims"]
    with memoryview(vectors["data"]) as view:
        for kind, wanted in (("texts", texts), ("replies", replies)):
            for key, offsets in vectors[kind].items():
                if key in wanted:
                    _add(kept, kind, key, [view[o:o + dims] for o in offsets])
    vectors.clear()
    vectors.update(kept)


def _convert_json():
    """Write the vectors of the earlier JSON file (base64 pieces) into the vectors file once and
    remove it, so an update keeps the vectors without embedding anything again."""
    if os.path.exists(VECTORS) or not os.path.exists(VECTORS_JSON):
        return
    try:
        with open(VECTORS_JSON, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    if (isinstance(old, dict) and type(old.get("dims")) is int and isinstance(old.get("texts"), dict)
            and isinstance(old.get("replies"), dict)):
        vectors = _empty(old.get("header"), old["dims"])
        for kind in ("texts", "replies"):
            for key, packed in old[kind].items():
                try:
                    raw = [base64.b64decode(p, validate=True)
                           for p in (packed if kind == "texts" else [packed])]
                except (TypeError, ValueError):
                    continue   # made again by the next update
                if raw and len(key) == KEY_BYTES and all(len(r) == old["dims"] for r in raw):
                    _add(vectors, kind, key, raw)
        _save_vectors(vectors)
    os.remove(VECTORS_JSON)


def _texts_to_embed(records):
    """Texts and short-reply texts to embed, newest first, by key."""
    texts, replies = {}, {}
    for record in sorted(records, key=lambda r: -(r["epoch"] or 0)):
        texts.setdefault(_key(record["text"]), record["text"])
        if record["tail"]:
            joined = reply_text(record)
            replies.setdefault(_key(joined), joined)
    return texts, replies


def _jobs(vectors, texts, replies):
    """What is still to embed: (kind, key, pieces) for every text and reply without vectors."""
    return ([("texts", k, pieces(x)) for k, x in texts.items() if k not in vectors["texts"]]
            + [("replies", k, [x]) for k, x in replies.items() if k not in vectors["replies"]])


def _batch_end(jobs, at):
    """The end of the batch that starts at jobs[at]: up to EMBED_BATCH pieces, at least one job."""
    end, size = at, 0
    while end < len(jobs) and (end == at or size + len(jobs[end][2]) <= EMBED_BATCH):
        size += len(jobs[end][2])
        end += 1
    return end


def _current(vectors, head, dims):
    """vectors when they were made under head and, when dims is given, have that length."""
    return (vectors is not None and vectors["header"] == head
            and (dims is None or vectors["dims"] in (None, dims)))


def update_vectors(records, config, dims=None, seconds=None):
    """Embed the messages that have no vectors yet, newest first; returns (vectors, status).

    With `seconds` it stops starting new requests after that time and gives way to a process
    already updating, answering from the file as it is; without it, it waits for that process,
    embeds everything and leaves out vectors of messages the store no longer holds. Vectors made
    under other settings, or of another length than `dims`, are dropped and made again, and
    status says so."""
    status = {"rebuilt": False, "failed": False}
    texts, replies = _texts_to_embed(records)
    head = _header(config)
    try:
        with safeio.locked(VECTORS + ".lock", timeout=0 if seconds is not None else 600):
            _convert_json()
            vectors = load_vectors()
            if not _current(vectors, head, dims):
                status["rebuilt"] = vectors is not None
                vectors = _empty(head, dims)
            if seconds is None:
                _keep_only(vectors, texts, replies)
            if _embed_jobs(vectors, texts, replies, config, seconds, status) or (
                    vectors["saved"] is None):
                _save_vectors(vectors)
    except safeio.StateLockTimeout:
        vectors = load_vectors()
        if not _current(vectors, head, dims):
            vectors = _empty(head, dims)
    return vectors, status


def _embed_jobs(vectors, texts, replies, config, seconds, status):
    """Embed what vectors lacks, batch by batch, into vectors; returns whether any were made.

    Inside a search no request starts with less than half a second left, and none runs past the
    bound, so an endpoint that stalls or answers slowly holds a search no longer than it. Without
    a bound each batch is written as soon as it is made, so a search reads it at once."""
    jobs = _jobs(vectors, texts, replies)
    changed = False
    start = time.monotonic()
    at = 0
    while at < len(jobs) and not (seconds is not None
                                  and time.monotonic() - start > seconds - 0.5):
        end = _batch_end(jobs, at)
        batch = jobs[at:end]
        left = (BATCH_SECONDS if seconds is None
                else max(0.1, seconds - (time.monotonic() - start)))
        try:
            made = embed(config, [p for _kind, _k, parts in batch for p in parts],
                         config["document_prefix"], left)
        except EmbedError as exc:
            status["failed"] = str(exc)
            break
        if vectors["dims"] is None:
            vectors.update(dims=len(made[0]), saved=None)   # the first line names the length
        elif len(made[0]) != vectors["dims"]:
            # The model behind the endpoint changed under the same name.
            status["rebuilt"] = True
            vectors.update(_empty(vectors["header"], len(made[0])))
            jobs, at = _jobs(vectors, texts, replies), 0
            continue
        at = end
        for kind, key, parts in batch:
            _add(vectors, kind, key, [pack(made.pop(0)) for _ in parts])
        changed = True
        if seconds is None:
            _save_vectors(vectors)
    return changed


def similarity(vectors_of_pieces, query):
    """A message's similarity to the query: its best piece, as the dot product of unit vectors."""
    return max(_dot(memoryview(p).cast("b"), query) for p in vectors_of_pieces) / 127


def share(vectors, records):
    """(messages of records with vectors, short replies of records with vectors, short replies),
    counted by message as the coverage line counts; a text the owner typed twice is embedded once."""
    have = sum(1 for r in records if _key(r["text"]) in vectors["texts"])
    replies = [r for r in records if r["tail"]]
    replied = sum(1 for r in replies if _key(reply_text(r)) in vectors["replies"])
    return have, replied, len(replies)


class Meaning:
    """The query's vector and the stored vectors of one search."""

    def __init__(self, vectors, query):
        self.vectors, self.query = vectors, query

    def messages(self, records, pool):
        """{i: similarity} for the records[i] of pool that have vectors."""
        return self._best("texts", ((i, _key(records[i]["text"])) for i in pool))

    def replies(self, records, pool):
        """{i: similarity} for the short replies records[i] of pool that have vectors."""
        return self._best("replies", ((i, _key(reply_text(records[i]))) for i in pool))

    def _best(self, kind, keys):
        table, dims, out = self.vectors[kind], self.vectors["dims"], {}
        with memoryview(self.vectors["data"]) as view:
            for i, key in keys:
                offsets = table.get(key)
                if offsets:
                    out[i] = similarity([view[o:o + dims] for o in offsets], self.query)
        return out


def prepare(query, records, notes, seconds):
    """Ready the list by meaning for one search of `query` over the stored records.

    Embeds the query and spends up to `seconds` embedding records that have no vectors yet.
    Returns a Meaning, or None when the list is off, the endpoint is not local or does not
    answer; each reason is appended to notes as one line."""
    config = settings()
    if config is None:
        if C.instance().get("recall_meaning"):
            notes.append(RECALL_MEANING_BAD)
        return None
    if not is_local(config["endpoint"]):
        notes.append(RECALL_MEANING_NOT_LOCAL.format(endpoint=config["endpoint"]))
        return None
    try:
        query_vector = embed(config, [query], config["query_prefix"], ANSWER_SECONDS)[0]
    except EmbedError as exc:
        notes.append(RECALL_MEANING_DOWN.format(endpoint=config["endpoint"], reason=exc))
        return None
    vectors, status = update_vectors(records, config, len(query_vector), seconds)
    if status["rebuilt"]:
        notes.append(RECALL_MEANING_REBUILT)
    return Meaning(vectors, query_vector)


def update_all(records, say=print):
    """Embed every stored message without a time limit (`recall.py index` and the catch-up);
    returns the exit code, 1 when the endpoint is not local or does not answer. Gives say a line
    for each thing that changed or failed."""
    config = settings()
    if config is None:
        return 0
    if not is_local(config["endpoint"]):
        return 1   # state() says why
    _vectors, status = update_vectors(records, config, seconds=None)
    if status["rebuilt"]:
        say(RECALL_MEANING_REBUILT)
    if status["failed"]:
        say(RECALL_MEANING_DOWN.format(endpoint=config["endpoint"], reason=status["failed"]))
        return 1
    return 0


def _on_here():
    """The settings when the list is on and its endpoint is on this machine, else None."""
    config = settings()
    return config if config is not None and is_local(config["endpoint"]) else None


def behind(records):
    """Whether the list is on here and a stored message or short reply has no vector yet."""
    config = _on_here()
    if config is None:
        return False
    if os.path.exists(VECTORS_JSON):
        return True   # converted by the next update
    vectors = load_vectors()
    if not _current(vectors, _header(config), None):
        return bool(records)
    return bool(_jobs(vectors, *_texts_to_embed(records)))


def indexed(records):
    """[messages of records with vectors, messages] when the list is on here, else None."""
    if _on_here() is None:
        return None
    vectors = load_vectors()
    if not _current(vectors, _header(settings()), None):
        return [0, len(records)]
    return [share(vectors, records)[0], len(records)]


def state(records):
    """One line for `recall.py index`: off, or the model with how much of records is embedded."""
    config = settings()
    if config is None:
        return (RECALL_MEANING_BAD if C.instance().get("recall_meaning") else RECALL_MEANING_OFF)
    if not is_local(config["endpoint"]):
        return RECALL_MEANING_NOT_LOCAL.format(endpoint=config["endpoint"])
    vectors = load_vectors() or _empty(None, None)
    texts, _replies = _texts_to_embed(records)
    have, replied, replies = share(vectors, records)
    return RECALL_MEANING_ON.format(model=config["model"], messages=have, pieces=sum(len(vectors["texts"][k]) for k in texts if k in vectors["texts"]), replies=replied, waiting=len(records) - have + replies - replied)
