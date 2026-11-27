#!/usr/bin/env python3
"""The command line for searching past sessions: it checks the arguments and routes each search.

  recall.py find PATTERN [--source all|NAME[,NAME], see --help] [--role user|assistant]
      [--since YYYY-MM-DD] [--around N] [--max 8] [--thinking] [--full] [--scan-all]
  recall.py find LOCATOR [--around N]
  recall.py index
  recall.py sessions [--max 40 | --all]

A search of the owner's words (--role user, a time limit, or a locator) is answered by
recall_store.py from its store of what the owner typed; every other search is the literal search of
recall_literal.py over the transcripts. This module checks the arguments, sends each search to
one of the two, and lists the session files. The printed hits are for reading in the session;
quote an original message by its locator.
"""
import argparse
import datetime
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import recall_literal as L
import recall_store as S
import transcripts as T

# Messages this module prints in more than one place, or too long to read inline.
AROUND_NEGATIVE = "--around must be 0 or more"
BAD_TIME = (
    "{value!r} is not a date (YYYY-MM-DD) or a time (YYYY-MM-DD HH:MM, local unless it names a "
    "zone)"
)
EMPTY_PATTERN = (
    "PATTERN must not be empty; give words to search for, or a time limit of the owner's words"
)
HELP_ALL_INSTANCES = (
    "also search Codex sessions and Claude records written in other folders (default: this "
    "instance only; KIT-DR-025)"
)
HELP_AROUND = (
    "messages of context before and after each hit (default 0; {full} with --full or --json)"
)
HELP_BEFORE = (
    "the --minutes (default 30) before this time, the way back from a journal line; searches "
    "the owner's words"
)
HELP_FULL = (
    "print every selected hit with its neighbouring messages (default output is capped at "
    "{max_bytes} bytes)"
)
HELP_INCLUDE_AGENTS = (
    "also search Codex subagent rollouts and known agent dispatch messages (Claude subagent "
    "transcripts are not searched)"
)
HELP_INCLUDE_SYSTEM = (
    "also show system-injected records (plugin lists, full AGENTS text, command wrappers, and "
    "so on)"
)
HELP_INDEX = (
    "build the store of the owner's messages, or bring it up to date, with the vectors of the "
    "list by meaning when it is on; prints its state"
)
HELP_MINUTES = (
    "width of the --before or --near window in minutes (default 30); needs one of them"
)
HELP_ORDER = (
    "score=match quality (default) · recent=newest first · oldest=file order (previous "
    "behaviour)"
)
HELP_OWNER = (
    "Searching the owner's words (--role user, or any time limit) answers from a store of what "
    "they\ntyped: _private/state/recall-store.json, safe to delete (`recall.py index` builds it "
    "again).\nFrom a journal line: `find --before 'YYYY-MM-DD HH:MM'` lists what they typed in "
    "the 30 minutes\nbefore it. Otherwise ask in one full sentence and add any of their own "
    "words you remember; the\nword list ranks their messages by the words and character pairs "
    "they share with the query.\nShort replies (\"yes, do that\") are listed apart with the "
    "end of the assistant's text before\nthem: read both before saying they decided something.\n"
    "Each line carries a locator (8 characters:line); `find LOCATOR --around N` opens that "
    "message\nwith N messages on each side, read from its transcript. A long message is "
    "searched by its\nfirst 2,000 characters; its locator opens it in full.\nWith "
    "config.instance.recall_meaning naming a local embeddings endpoint and model, a search\n"
    "first lists their messages by meaning, each with its similarity, then 4 more by words "
    "(half\nof --max when that is more); a message both lists would show is marked [both], and "
    "short\nreplies picked by meaning show their similarity too. No result is hidden for a low "
    "similarity:\na list whose best similarity is low is a set of leads, not evidence, and "
    "nothing found\nmeans nothing in what the closing coverage line names. The vectors are "
    "kept in\n_private/state/recall-vectors.bin, safe to delete like the store.\nRecords the "
    "runtime wrote itself (summaries, hook and task notices, messages from other\nsessions) "
    "are left out; --include-system or --include-agents reads the transcripts with them.\nEach "
    "search of their words adds one line (time, query, options, lines shown; no hit text) to\n"
    "_private/state/recall-queries.jsonl, the material for measuring real queries; delete it "
    "freely."
)
HELP_SCAN_ALL = (
    "search every session file; by default files are read newest first (oldest first with "
    "--order oldest) and new files stop being opened after {seconds} seconds"
)
HELP_SINCE = (
    "from this date or time on (local time unless it names a zone); a time searches the "
    "owner's words"
)
MAX_TOO_SMALL = "--max must be 1 or more"
STORE_BUILD = (
    "The owner's messages are not indexed yet, and indexing takes longer than a search: run "
    "`python3 tools/recall.py index` once. This search reads the transcripts the old way."
)
STORE_BUILD_FIRST = (
    "The owner's messages are not indexed yet, and a search by time answers only from the "
    "index: run `python3 tools/recall.py index` once (it takes longer than a search), then "
    "search again."
)
STORE_ONLY = (
    "--until, --before, --near, --minutes and a --since with a time search the owner's words; "
    "they do not combine with --role assistant, --json, --include-system, --include-agents, "
    "--thinking, --all-instances, --scan-all or a --source without a runtime"
)

# Messages shown on each side of a hit under --full or --json, and of a message opened by its
# locator, when --around does not say.
FULL_AROUND_DEFAULT = 2
# A search over every stored session can take minutes once compressed Codex sessions are
# included (about 35 seconds for 5,000 sessions), so find reads the newest files first and stops
# opening new files after this many seconds; --scan-all lifts the limit. The output says how many
# files were left unread.
SCAN_SECONDS = 20


# ------------------------------------------------------------------ listing the sessions


def sessions(max_sessions=40):
    """List the session files this instance's searches read, newest first, with their sizes."""
    missing = T.missing_claude_store(None)
    if missing:
        print(T.NO_TRANSCRIPTS.format(path=missing))
    selection = T.select_sources(None)
    files = selection.rows
    files.sort(key=lambda row: T.mtime(row[2]), reverse=True)
    total = len(files)
    shown = files if max_sessions is None else files[:max_sessions]
    for sname, kind, fp, _checked in shown:
        try:
            sz = os.path.getsize(fp) / 1048576
        except OSError:
            continue  # Removed after it was listed.
        shown_name = T.agy_conversation(fp) if kind == "agy-jsonl" else os.path.basename(fp)
        print(f"[{sname:6s}] {shown_name[:52]:54s} {sz:8.1f} MB")
    if len(shown) < total:
        print(f"({len(shown)}/{total} shown, newest first · all: `recall.py sessions --all`)")
    if selection.unverified:
        print(T.UNVERIFIED_FILES.format(count=selection.unverified))
    if selection.zst_skipped:
        print(T.ZST_SKIPPED.format(count=selection.zst_skipped))
    if T.unreadable_count():
        print(T.ZST_UNREADABLE.format(count=T.unreadable_count()))
    if T.unscoped_count():
        print(T.AGY_UNSCOPED.format(count=T.unscoped_count()))
    return 0


# ------------------------------------------------------------------ the command line


def _parser(source_names):
    """The argument parser, with its find and sessions subparsers for the usage errors."""
    ap = argparse.ArgumentParser(add_help=True, description=(
        "Find what was said in past sessions on this folder, in the runtimes' own transcripts."))
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("find", epilog=HELP_OWNER, help="search past messages for words, a time or both",

                       formatter_class=argparse.RawDescriptionHelpFormatter)
    f.add_argument("pattern", nargs="?", default="")
    f.add_argument("--role", choices=["user", "assistant"])
    f.add_argument("--since", help=HELP_SINCE)
    f.add_argument("--until", help=(
        "up to this date (inclusive) or time; searches the owner's words"
    ))
    f.add_argument("--before", help=HELP_BEFORE)
    f.add_argument("--near", help=(
        "--minutes (default 30) on either side of this time; searches the owner's words"
    ))
    f.add_argument("--minutes", type=int, default=None, help=HELP_MINUTES)
    f.add_argument("--around", type=int, default=None,
                   help=HELP_AROUND.format(full=FULL_AROUND_DEFAULT))
    f.add_argument("--max", type=int, default=8, dest="max_hits")
    f.add_argument("--thinking", action="store_true")
    f.add_argument("--full", action="store_true",
                   help=HELP_FULL.format(max_bytes=L.COMPACT_MAX_BYTES))
    f.add_argument("--json", action="store_true", dest="json_output",
                   help="structured results including source location, native ID, and record ID")
    f.add_argument("--source", default=None,
                   help="all (default)|{names}; a comma-separated list is allowed".format(names="|".join(source_names)))
    f.add_argument("--include-agents", action="store_true",
                   help=HELP_INCLUDE_AGENTS)
    f.add_argument("--include-system", action="store_true",
                   help=HELP_INCLUDE_SYSTEM)
    f.add_argument("--order", choices=["score","recent","oldest"], default="score",
                   help=HELP_ORDER)
    f.add_argument("--all-instances", action="store_true",
                   help=HELP_ALL_INSTANCES)
    f.add_argument("--scan-all", action="store_true",
                   help=HELP_SCAN_ALL.format(seconds=SCAN_SECONDS))
    sub.add_parser("index", help=HELP_INDEX)
    s = sub.add_parser("sessions", help="list past sessions, newest first")
    s.add_argument("--max", type=int, default=40, dest="max_sessions")
    s.add_argument("--all", action="store_true")
    return ap, f, s


def _check_find(a, f, timed, source_names):
    """Stop with a usage error on a bad find argument; return the selected source names.

    An unknown source or an empty pattern would otherwise print a normal-looking answer for a
    search that was not the one asked for. None means every source."""
    if not a.pattern.strip() and not (timed or a.since and a.role == "user"):
        f.error(EMPTY_PATTERN)
    for value, end in ((a.since, False), (a.until, True), (a.before, False), (a.near, False)):
        if value is not None and S.parse_time(value, end) is None:
            f.error(BAD_TIME.format(value=value))
    if a.minutes is not None and a.minutes < 0:
        f.error("--minutes must be 0 or more")
    if a.minutes is not None and not (a.before or a.near):
        f.error("--minutes sets the width of a --before or --near window; give one of them")
    if a.max_hits < 1:
        f.error(MAX_TOO_SMALL)
    if a.around is not None and a.around < 0:
        f.error(AROUND_NEGATIVE)
    srcs = None if (a.source in (None, "all")) else set(a.source.split(","))
    if srcs is not None:
        unknown = sorted(srcs - set(source_names) - {"all"})
        if unknown:
            f.error("unknown --source name: {names}. Configured sources: all, {known}".format(names=", ".join(unknown), known=", ".join(source_names)))
        if "all" in srcs:
            srcs = None  # all already names every source, so "claude,all" means all.
    return srcs


def _has_clock(text):
    """True for a time of day, which only the store honours; the transcript search takes days."""
    try:
        datetime.date.fromisoformat(text.strip())
        return False
    except ValueError:
        return True


def _answers_from_store(a, srcs, timed):
    """True when the store of the owner's words answers this search instead of the transcripts.

    A search of the owner's words (--role user, or any time limit) goes to the store, unless it asks for
    what the store does not hold: other roles, runtime-written records, thinking, structured
    output, other instances, a full scan, or only sources that are not runtimes."""
    runtimes = {name for name, kind, _b, _p in C.episodic_sources() if kind != "text"}
    return (a.role == "user" or timed) and not (
        a.json_output or a.include_system or a.include_agents or a.thinking
        or a.all_instances or a.scan_all or a.role == "assistant"
        or (srcs is not None and not srcs & runtimes))


def _find_command(a, f, source_names):
    timed = (any(v is not None for v in (a.until, a.before, a.near, a.minutes))
             or bool(a.since and _has_clock(a.since)))
    srcs = _check_find(a, f, timed, source_names)
    owner = _answers_from_store(a, srcs, timed)
    if S.LOCATOR.match(a.pattern.strip()):
        return S.open_locator(a.pattern.strip(), FULL_AROUND_DEFAULT if a.around is None
                              else a.around)
    if timed and not owner:
        f.error(STORE_ONLY)
    if owner:
        answer = S.find(a, a.pattern.strip(), srcs, L.COMPACT_MAX_BYTES, FULL_AROUND_DEFAULT)
        if answer is not None:
            return answer
        # The transcript search has no time of day and no window, so only a search by
        # words can fall back to it, still limited to the owner's messages by --role user.
        if timed or not a.pattern.strip():
            print(STORE_BUILD_FIRST)
            return 1
        print(STORE_BUILD)
    since = (datetime.datetime.fromtimestamp(S.parse_time(a.since)).date().isoformat()
             if a.since else None)
    # --json and --full show neighbours by default; the compact form shows them only when
    # --around asks for them.
    around = a.around if a.around is not None else (
        FULL_AROUND_DEFAULT if (a.full or a.json_output) else 0)
    return L.find(a.pattern, a.role, since, around, a.max_hits, a.thinking, srcs,
                include_agents=a.include_agents, include_system=a.include_system,
                all_instances=a.all_instances, order=a.order, json_output=a.json_output,
                full=a.full, capped=a.around is None,
                scan_seconds=None if a.scan_all else SCAN_SECONDS)


def main():
    # Several registry rows can share a name (active and archived Codex sessions).
    source_names = list(dict.fromkeys(name for name, _k, _b, _p in C.episodic_sources()))
    ap, f, s = _parser(source_names)
    a = ap.parse_args()
    if a.cmd == "index":
        return S.build()
    if a.cmd == "find":
        return _find_command(a, f, source_names)
    if a.cmd == "sessions":
        if a.max_sessions < 1 and not a.all:
            s.error(MAX_TOO_SMALL)
        return sessions(None if a.all else a.max_sessions)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
