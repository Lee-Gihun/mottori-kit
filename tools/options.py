#!/usr/bin/env python3
"""The kit's optional parts in one table, read by setup; MANUAL.md section 1 describes each.

Usage:
  python3 tools/options.py                 every option with its state, what it needs and when it pays off,
                                           and two facts about this machine that are not switches
  python3 tools/options.py on NAME [key=value ...]
  python3 tools/options.py on meaning [key=value ...] yes
  python3 tools/options.py on loop [sources=all|SOURCE] yes
  python3 tools/options.py off NAME
  python3 tools/options.py setup           what setup.sh runs: one line saying how many are off

Nothing here switches an option on or off unless a person names it, with one exception: setup turns
the list by meaning on when an embedding server on this machine already answers with its model and
the owner has not said no (KIT-DR-094). Turning one on checks its need
first and changes nothing while a need is missing. It never starts a service or gives an approval
that belongs to the user. It downloads one thing, the model of the list by meaning, and only
after the owner's yes: asked once on a terminal, or the word yes added to the command. The loop's
send permission takes the same yes; on a terminal, a choice of sources other than the one described
is described in turn before its yes is taken. `off` also records the user's no, which the list then
shows.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import config as C  # noqa: E402
import hookdiag  # noqa: E402
import paths as P  # noqa: E402
import safeio  # noqa: E402
import loop_config  # noqa: E402
import loop_jobs  # noqa: E402
import loop_platform  # noqa: E402
import loop_runtimes  # noqa: E402
import loop_sending  # noqa: E402
import loop_sources  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
COME_BACK = (
    "To see this list again: python3 tools/options.py · to turn one on or off: python3 "
    "tools/options.py on|off NAME (MANUAL.md section 1)"
)
TURN = "To turn one on or off: python3 tools/options.py on|off NAME (MANUAL.md section 1)"
NOT_READ = (
    "{name}: its own tool does not read the settings just written as on, so they were put back "
    "and it stays off."
)
FIRST_FAILED = (
    "{name}: its first step failed ({command}, exit {code}), so the settings were put back and "
    "it stays off. Fix the cause, then run `python3 tools/options.py on {name}` again."
)
HEAD = (
    "Optional parts. Setup turns on the delivery check, and the list by meaning only when an embedding "
    "server on this machine already answers; the rest stays off until you turn it on:"
)
NOT_APPLIED = (
    "not applied: {pairs}. To change them, run `python3 tools/options.py off {name}`, then `on "
    "{name}` with the new values."
)
USAGE = (
    "usage: python3 tools/options.py [list] | on NAME [key=value ...] | off NAME | setup   "
    "(names: {names})"
)

ROOT = P.instance_root()
CONFIG = P.config_file(ROOT)

# The meaning list's settings, under instance. Whether they are on is read through the search's
# own reader (config.recall_meaning), so `on` notices settings written where the search does not look.
MEANING_KEY = "recall_meaning"
MEANING_DEFAULTS = {
    "endpoint": "http://127.0.0.1:11434/v1/embeddings",
    "model": "embeddinggemma",
    "query_prefix": "task: search result | query: ",
    "document_prefix": "title: none | text: ",
}
# The texts sent are the owner's own words, so only this machine may receive them.
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    C.validate(cfg)
    safeio.atomic_write(CONFIG, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def declined(cfg):
    value = cfg.get("options", {}).get("declined", []) if isinstance(cfg.get("options"), dict) else []
    return [x for x in value if isinstance(x, str)]


# --- meaning: a second search list by meaning, through a local embedding server ---

def _meaning_on():
    """On when the search's own reader (config.recall_meaning) finds endpoint and model in the
    configuration file, read again at each call."""
    C.reload()
    return C.recall_meaning() is not None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect could lead off this machine, so it fails the check instead


# A proxy from the environment would answer for a server that is not here and could carry the text
# off the machine, so the probe connects to the loopback address itself or not at all.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _embeds(endpoint, model):
    """True when the endpoint answers one embedding within two seconds."""
    body = json.dumps({"model": model, "input": ["ping"]}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
    try:
        with _LOCAL_OPENER.open(req, timeout=2) as r:
            return bool(json.load(r)["data"][0]["embedding"])
    except Exception:  # noqa: BLE001 - any failure means the need is not there yet
        return False


MEANING_NOT_LOCAL = (
    "refused: {endpoint} is not on this machine; the texts sent are your own words, so only "
    "127.0.0.1, localhost or ::1 is accepted"
)
MEANING_STEPS = (
    "No embedding server answered at {endpoint} with the model {model}. Start the server "
    "(`ollama serve`, or open the Ollama app), then run `python3 tools/options.py on meaning` "
    "again. For another model or address add model=NAME or endpoint=URL."
)
MEANING_NOT_INSTALLED = (
    "meaning stays off and nothing was changed: the local embedding server program, Ollama, is "
    "not installed. Install it with `{command}`, then run `python3 tools/options.py on meaning` "
    "again."
)
MEANING_PLAN = (
    "meaning needs the model {model} ({size}, from {source}). Turning it on downloads it with "
    "`{pull}`, writes its settings to {config} and builds the index of your messages; your "
    "words never leave this machine."
)
MEANING_ASK = "Download it and turn the list on? [y/N] "
MEANING_DECLINED = ("Nothing was downloaded. Your no is recorded, so setup will not turn the list on by itself; "
                    "`python3 tools/options.py on meaning` asks again.")
MEANING_NO_TERMINAL = (
    "Nothing was downloaded or changed: there is no terminal here to ask on. An assistant reading "
    "this asks the owner first, and only after the owner said yes runs `{command}`."
)
MEANING_PULL_FAILED = (
    "meaning stays off: `{pull}` exited {code}, so no settings were written. The server must be "
    "running for a download (`ollama serve`, or open the Ollama app)."
)
# The program that serves the default endpoint, the one command that installs it, and what the
# kit can say about a model before downloading it.
SERVER_PROGRAM = "ollama"
SERVER_INSTALL = ("brew install ollama" if sys.platform == "darwin"
                  else "curl -fsSL https://ollama.com/install.sh | sh")
MODELS = {"embeddinggemma": ("about 0.6 GB", "the Ollama library, "
                                             "https://ollama.com/library/embeddinggemma")}
# The one word that, added to `on meaning`, stands for the owner's yes to the download.
YES = "yes"


def _meaning_fetch(values, pairs, yes):
    """When no server answers with the model: say what turning it on downloads, take the
    owner's yes, and download the model through the server's own command.

    Returns an exit code when it stops here, or None after the download, when the need is
    checked again. Without the program it names the one command that installs it."""
    host = urllib.parse.urlsplit(values["endpoint"]).hostname or ""
    if host not in LOCAL_HOSTS:
        return None   # refused by the need check
    program = shutil.which(SERVER_PROGRAM)
    if not program:
        print(MEANING_NOT_INSTALLED.format(command=SERVER_INSTALL))
        return 1
    model = values["model"]
    size, source = MODELS.get(model, ("size not known to the kit", "the Ollama library"))
    pull = f"{SERVER_PROGRAM} pull {model}"
    print(MEANING_PLAN.format(model=model, size=size, source=source, pull=pull,
                              config=P.tracked_name(P.config_file)))
    if not yes and not sys.stdin.isatty():
        command = " ".join(["python3 tools/options.py on meaning", *pairs, YES])
        print(MEANING_NO_TERMINAL.format(command=command))
        return 1
    if not yes:
        try:
            answer = input(MEANING_ASK)
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", YES):
            # A no here is the owner's no: setup must not turn the list on later by itself.
            cfg = load_config()
            _set_declined(cfg, "meaning", True)
            save_config(cfg)
            print(MEANING_DECLINED)
            return 1
    sys.stdout.flush()   # through a pipe, the plan is read before what the download prints
    code = subprocess.run([program, "pull", model]).returncode
    if code:
        print(MEANING_PULL_FAILED.format(pull=pull, code=code))
        return 1
    return None


def _meaning_missing(values):
    host = urllib.parse.urlsplit(values["endpoint"]).hostname or ""
    if host not in LOCAL_HOSTS:
        return [MEANING_NOT_LOCAL.format(endpoint=values["endpoint"])]
    if not _embeds(values["endpoint"], values["model"]):
        return [MEANING_STEPS.format(endpoint=values["endpoint"], model=values["model"])]
    return []


# --- deliver: the turn-end check that records a document handed over unread ---

def _deliver_on():
    try:
        d = load_config().get("deliver", {})
    except (OSError, ValueError, AttributeError):
        return False  # before setup, or with a broken file, every option is off
    return isinstance(d, dict) and bool(d.get("block") or d.get("observe"))


_DELIVER_HOOK = re.compile(r'^\s*sh\s+("[^"]*|[^"\s]*)tools/hook\.sh"?\s+(deliver\.py\s+hook|event\s+Stop)\b')


def _stop_hook_runs_deliver():
    try:
        commands = [h["command"] for h in
                    hookdiag.declared("claude", hookdiag.read("claude", ROOT) or {}).get("Stop", [])]
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        return False
    # Either hook.sh runs the check itself or its dispatcher runs every Stop step; the command must
    # start by running hook.sh, since one that only mentions it, such as an echo, runs nothing.
    return any(isinstance(c, str) and _DELIVER_HOOK.search(c) for c in commands)


DELIVER_STEPS = (
    "The Stop hook in .claude/settings.json does not run the check. Add this entry to its Stop "
    "list, then run the command again: {\"hooks\": [{\"type\": \"command\", \"command\": \"sh "
    "\\\"$CLAUDE_PROJECT_DIR/tools/hook.sh\\\" deliver.py hook || true\"}]}"
)


def _deliver_missing(values):
    return [] if _stop_hook_runs_deliver() else [DELIVER_STEPS]


# --- two facts about this machine that the list also shows; neither is a switch of this kit ---

# Claude Code's settings files that may set cleanupPeriodDays, in the order it reads them.
RETENTION_FILES = (".claude/settings.local.json", ".claude/settings.json", "~/.claude/settings.json")
RETENTION_DEFAULT = 30   # Claude Code's days when no file sets cleanupPeriodDays


def retention(root):
    """Return (days, problem): how long Claude Code keeps transcripts in root, and None or why the
    days cannot be measured, with days then None.

    The first file that sets cleanupPeriodDays wins, as in Claude Code; with none it is
    RETENTION_DEFAULT. A file that cannot be read may set it, and a value that is not a number is
    not a day count, so either leaves the days unmeasured rather than reading a file Claude Code
    would not use."""
    for shown in RETENTION_FILES:
        path = os.path.expanduser(shown) if shown.startswith("~") else os.path.join(root, shown)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError) as error:
            return None, f"{shown} cannot be read ({error})"
        if isinstance(cfg, dict) and "cleanupPeriodDays" in cfg:
            days = cfg["cleanupPeriodDays"]
            # JSON true would pass an int check; it is not a day count.
            if isinstance(days, bool) or not isinstance(days, (int, float)):
                return None, f"cleanupPeriodDays in {shown} is not a number ({json.dumps(days)})"
            return days, None
    return RETENTION_DEFAULT, None


def _codex_fact():
    """Whether the codex program is on the PATH. Its login and its approval of this folder's hooks
    are steps only the user can take, and nothing here sees them."""
    if shutil.which("codex"):
        return ("Codex, a second model family: installed. Signing in (`codex login`) and approving this "
                "folder's hooks on its first launch are yours; prompts sent to it go to that vendor.")
    return ("Codex, a second model family: not installed. Workers and reviews can use it once you install "
            "it and sign in (`codex login`); prompts sent to it go to that vendor.")


def _history_fact():
    """How long Claude Code keeps transcripts here. The setting is the user's and applies to every folder."""
    days, problem = retention(ROOT)
    if days is None:
        return f"History: how long Claude Code keeps transcripts cannot be read here ({problem})."
    kept = f"History: Claude Code keeps terminal transcripts {days:g} days here"
    if days > RETENTION_DEFAULT:
        return kept + ", so recall can find words that old."
    return (kept + ', and recall finds nothing older. To keep more, add "cleanupPeriodDays": 365 (or any '
            "number of days) to ~/.claude/settings.json, which applies to every folder.")


FACTS = {"codex": _codex_fact, "history": _history_fact}
FACTS_HEAD = "Also on this machine (facts, not switches of this kit):"
NOT_A_SWITCH = "{name} is not a switch of this kit, so nothing was changed. {fact}"


# --- loop: the weekly improvement loop, off until each of its steps is turned on ---

# What one cycle cost when it was run with real models (system/loop/README.md, section 7).
# An added source may say what one of its cycles costs (its COST, tools/loop/sources/README.md).
LOOP_COST = " ".join(
    ["Cost: a papers cycle run with real models took 52 to 75 minutes, 8 to 11 model runs and about 16 to 19 "
     "million tokens as the programs reported them, most of it cached input read again."]
    + [cost for _, cost in loop_sources.each("COST")]
    + ["loop.token_ceiling (off by default) stops a cycle at a limit."])
RUNTIME_NAMES = {"claude": "Claude Code", "codex": "Codex"}
# sources=all or sources=NAME on the command line; with more than one source the question offers each
# by its first letter, or by its number when two share one.
LOOP_SOURCES = {"all": loop_config.SOURCES, **{name: (name,) for name in loop_config.SOURCES}}
_KEYS = ([name[0] for name in loop_config.SOURCES]
         if len({name[0] for name in loop_config.SOURCES} | {"a", "n"}) == len(loop_config.SOURCES) + 2
         else [str(i) for i in range(1, len(loop_config.SOURCES) + 1)])
LOOP_CHOICES = ({"y": loop_config.SOURCES} if len(loop_config.SOURCES) == 1 else
                {"a": loop_config.SOURCES, **{k: (name,) for k, name in zip(_KEYS, loop_config.SOURCES)}})
LOOP_ASK = (f"Allow {loop_config.SOURCES[0]} to send? [y/N] " if len(loop_config.SOURCES) == 1 else
            "Allow sending for [a]ll sources, "
            + ", ".join(f"[{k}] {name} only" for k, name in zip(_KEYS, loop_config.SOURCES)) + ", or [n]o? [n] ")
LOOP_NO_TERMINAL = (
    "Nothing was changed: there is no terminal here to ask on. An assistant reading this asks the "
    "owner first, and only after the owner said yes runs `python3 tools/options.py on loop "
    "sources={choice} yes`{others}."
)
LOOP_NO_RUNTIME = (
    "The loop needs Claude Code or Codex installed, and neither is: your yes can be saved now, but no cycle "
    "runs until you install one."
)
LOOP_SAME_FAMILY = (
    "Only {found} is installed, so the reviewer will be a fresh worker of the same family as the builder; "
    "each report names it."
)
LOOP_NEXT = (
    "Next: `python3 tools/loop/loops.py run <source>` runs one cycle now, `python3 tools/loop/loops.py "
    "start <source>` schedules it weekly with a daily health check, `python3 tools/loop/loops.py status` "
    "shows the state."
)


def _model_send(cfg):
    egress = cfg.get("egress") if isinstance(cfg.get("egress"), dict) else {}
    found = egress.get("model_send") if isinstance(egress.get("model_send"), dict) else {}
    return {"deny_prefixes": list(found.get("deny_prefixes", C.DEFAULT_EGRESS_MODEL_SEND["deny_prefixes"])),
            "allow_prefixes": list(found.get("allow_prefixes", []))}


def _loop_on():
    try:
        return bool(loop_sending.allowed(_model_send(load_config())))
    except (OSError, ValueError, AttributeError):
        return False


def _loop_label(cfg, state_word):
    """The loop's state in a few words: off, or which sources may send and what is scheduled."""
    if not loop_platform.supported():
        return f"off; {loop_platform.SHORT}"
    allowed = loop_sending.allowed(_model_send(cfg))
    if not allowed:
        return STATE_LABEL[state_word]
    on = [name for name, yes in loop_jobs.scheduled(ROOT).items() if yes and name in loop_config.SOURCES]
    return f"{', '.join(allowed)} may send; " + (f"{', '.join(on)} scheduled" if on else "nothing scheduled")


def _loop_statement(chosen):
    """Say what leaves the machine when a cycle of each chosen source runs, and what turning it on changes."""
    only = "" if len(chosen) == len(loop_config.SOURCES) else f" ({chosen[0]} only)"
    print(f"The improvement loop{only}. What leaves this machine when a cycle runs:")
    for line in loop_sending.statement(chosen, ROOT):
        print("  - " + line)
    print("  " + loop_sending.NOTHING_ELSE)
    print("  " + LOOP_COST)
    folders = " and ".join(f"{s} ({loop_sending.PREFIXES[s]})" for s in chosen)
    others = [s for s in loop_config.SOURCES if s not in chosen]
    print(f"Turning this on allows {folders} to send {'its cycle folder' if len(chosen) == 1 else 'their cycle folders'}"
          + (f"; {' and '.join(others)} may then not send" if others else "")
          + ". It schedules nothing.")


def _loop_statement_again(chosen):
    """A choice other than the one just described: describe it and take a yes for it."""
    _loop_statement(chosen)
    try:
        return input("Allow this? [y/N] ").strip().lower() in ("y", YES)
    except EOFError:
        return False


def _loop_turn_on(pairs):
    """Say what leaves the machine, take the owner's yes and choice of sources, and allow only those to send."""
    if not loop_platform.supported():
        print(loop_platform.REFUSAL)
        return 1
    yes = YES in pairs
    rest = [pair for pair in pairs if pair != YES]
    chosen = LOOP_SOURCES["all"]
    for pair in rest:
        key, _, value = pair.partition("=")
        if key != "sources" or value not in LOOP_SOURCES:
            print(f"cannot use {pair}; this option takes " + ", ".join(f"sources={k}" for k in LOOP_SOURCES),
                  file=sys.stderr)
            return 2
        chosen = LOOP_SOURCES[value]
    _loop_statement(chosen)
    found = loop_runtimes.installed(ROOT)
    if len(found) < 2:
        print(LOOP_SAME_FAMILY.format(found=RUNTIME_NAMES.get(found[0], found[0])) if found else LOOP_NO_RUNTIME)
    if not yes:
        if not sys.stdin.isatty():
            choice = next(k for k, v in LOOP_SOURCES.items() if v == tuple(chosen))
            others = [k for k in LOOP_SOURCES if k != choice and LOOP_SOURCES[k] != tuple(chosen)]
            print(LOOP_NO_TERMINAL.format(choice=choice, others=" (or " + ", or ".join(f"sources={k}" for k in others)
                                          + ")" if choice == "all" and others else ""))
            return 1
        try:
            answer = input(LOOP_ASK).strip().lower()[:1]
        except EOFError:
            answer = ""
        if answer not in LOOP_CHOICES or (LOOP_CHOICES[answer] != tuple(chosen)
                                          and not _loop_statement_again(LOOP_CHOICES[answer])):
            print("Nothing was changed.")
            return 1
        chosen = LOOP_CHOICES[answer]
    cfg = load_config()
    cfg.setdefault("egress", {})["model_send"] = loop_sending.allow(_model_send(cfg), chosen)
    _set_declined(cfg, "loop", False)
    save_config(cfg)
    try:
        none = not any(loop_jobs.scheduled(ROOT).values())
    except (OSError, RuntimeError):
        none = False
    schedule = "Nothing is scheduled." if none else "This does not change the schedule."
    print(f"loop: {', '.join(chosen)} may send to a model runtime. {schedule}")
    print("  " + LOOP_NEXT)
    return 0


def _loop_turn_off():
    """Unschedule the loop's jobs and take back every allowance to send."""
    stopped = loop_jobs.stop_all(ROOT)
    cfg = load_config()
    cfg.setdefault("egress", {})["model_send"] = loop_sending.disallow(_model_send(cfg))
    _set_declined(cfg, "loop", True)
    save_config(cfg)
    words = {loop_config.HEALTH: "health check"}
    failed = [f"{words.get(name, name)}: {err}" for name, err in stopped if err]
    jobs = ", ".join(words.get(name, name) for name, err in stopped if not err) or "nothing was scheduled"
    print(f"loop is off: unscheduled: {jobs}; no source may send. Setup will not offer it again.")
    for line in failed:
        print(f"  not unscheduled: {line}")
    return 1 if failed else 0


# Order is the order of setup's numbers and of the manual's list. is_on reads the option's state anew;
# missing(values) lists the user's steps its need still lacks, and an option without it needs only
# what is_on reads, so `on` shows its steps whenever it is off. settings: what `on` writes into the
# config, with values_at the two keys of the dict a command line may give text values; fetch: what
# `on` does, after the owner's yes, when the need is missing (see _meaning_fetch); off_settings:
# what `off` writes; first: the option's own first step after it is on; off_steps: the user's own
# steps when the tool has nothing it may change itself; label(cfg, state) shows a state in a few words
# instead of on or off; turn_on(pairs) and turn_off() replace the steps above for an option that does
# its own. title, short and later make the option's
# line; MANUAL.md section 1 has a paragraph for each name.
OPTIONS = [
    {"name": "meaning", "is_on": _meaning_on, "missing": _meaning_missing, "fetch": _meaning_fetch,
     "settings": {"instance": {MEANING_KEY: MEANING_DEFAULTS}}, "values_at": ("instance", MEANING_KEY),
     "off_settings": {"instance": {MEANING_KEY: None}},
     "first": ["tools/recall.py", "index"],
     "title": "Search by meaning",
     "short": (
         "finds your past messages by meaning, not only by their words · needs a local "
         "embedding server (Ollama with embeddinggemma, about 0.6 GB); nothing leaves this "
         "machine"
     ),
     "later": "once you have a few weeks of sessions to search"},
    {"name": "deliver", "is_on": _deliver_on, "missing": _deliver_missing,
     "settings": {"deliver": {"block": ["unopened"], "observe": []}},
     "off_settings": {"deliver": {"block": [], "observe": []}},
     "first": ["tools/deliver.py", "stats"],
     "title": "Delivery check",
     "short": (
         "stops a turn once when a long document written in it is handed over without being "
         "reread · Claude Code only; on after setup; nothing leaves this machine"
     ),
     "later": "from the first day"},
    {"name": "loop", "is_on": _loop_on, "label": _loop_label, "turn_on": _loop_turn_on, "turn_off": _loop_turn_off,
     "title": "Improvement loop",
     "short": (
         "weekly changes to this kit from new arXiv papers (papers) and from any source this installation "
         "added, each built in a temporary clone, tested in a sandbox and checked by a reviewer that did not "
         "build it · needs macOS and your yes; a second runtime is optional"
     ),
     "later": "after a few weeks, once the rest is part of your routine"},
]
STATE_LABEL = {"on": "on", "off": "off", "declined": "off, you said no"}
BY_NAME = {o["name"]: o for o in OPTIONS}


def state(option, cfg):
    if option["is_on"]():
        return "on"
    return "declined" if option["name"] in declined(cfg) else "off"


def state_text(option, cfg):
    s = state(option, cfg)
    if option.get("label"):
        return option["label"](cfg, s)
    return STATE_LABEL[s]


def line(option, cfg, number=None):
    name = option["name"]
    head = f"{number}. " if number else "   "
    return (f"  {head}[{state_text(option, cfg)}] {option['title']} ({name}): {option['short']}. "
            f"Pays off: {option['later']}.")


def _merge(cfg, settings):
    for key, value in settings.items():
        if value is None:
            cfg.pop(key, None)
        elif isinstance(value, dict) and isinstance(cfg.get(key), dict):
            # Keys the option does not name, such as deliver.send_tools, stay as the instance set them.
            _merge(cfg[key], value)
        else:
            cfg[key] = json.loads(json.dumps(value))


def _set_declined(cfg, name, value):
    opts = cfg.get("options") if isinstance(cfg.get("options"), dict) else {}
    names = [x for x in declined(cfg) if x != name] + ([name] if value else [])
    opts["declined"] = names
    cfg["options"] = opts


def turn_on(name, pairs=()):
    option = BY_NAME[name]
    if option.get("turn_on"):
        return option["turn_on"](list(pairs))
    cfg = load_config()
    yes = bool(option.get("fetch")) and YES in pairs
    pairs = [pair for pair in pairs if not (yes and pair == YES)]
    if option["is_on"]():
        print(f"{name} is already {state_text(option, cfg)}.")
        if pairs:
            print("  " + NOT_APPLIED.format(pairs=" ".join(pairs), name=name))
        return 0
    settings = json.loads(json.dumps(option.get("settings", {})))
    at = option.get("values_at")
    values = settings[at[0]][at[1]] if at else {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        # Only the text settings take a value from the command line; lists stay as the option sets them.
        # An empty value is written; if it turns the option off, the check after writing puts it back.
        if not sep or not isinstance(values.get(key), str):
            keys = ", ".join(k for k, v in values.items() if isinstance(v, str)) or "-"
            print(f"cannot use {pair}; this option takes a value for: {keys}", file=sys.stderr)
            return 2
        values[key] = value
    missing = option["missing"](values)
    if missing and option.get("fetch"):
        stopped = option["fetch"](values, pairs, yes)
        if stopped is not None:
            return stopped
        missing = option["missing"](values)
    if missing:
        print(f"{name} stays off and nothing was changed. What it still needs:")
        for step in missing:
            print("  " + step)
        return 1
    with open(CONFIG, encoding="utf-8") as f:
        before = f.read()
    _merge(cfg, settings)
    _set_declined(cfg, name, False)
    save_config(cfg)
    if not option["is_on"]():
        safeio.atomic_write(CONFIG, before)
        print(NOT_READ.format(name=name))
        return 1
    if option.get("first"):
        cmd = [sys.executable] + [os.path.join(ROOT, option["first"][0])] + option["first"][1:]
        sys.stdout.flush()
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc:
            # Put the settings back: the list shows on only an option whose first step ran.
            safeio.atomic_write(CONFIG, before)
            print(FIRST_FAILED.format(command="python3 " + " ".join(option["first"]), code=rc, name=name))
            return 1
    print(f"{name} is on.")
    return 0


def turn_off(name):
    option = BY_NAME[name]
    if option.get("turn_off"):
        return option["turn_off"]()
    cfg = load_config()
    _merge(cfg, option.get("off_settings", {}))
    _set_declined(cfg, name, True)
    save_config(cfg)
    print(f"{name} is off; the list shows that you said no.")
    return 0


def show(cfg, numbered=()):
    print(HEAD)
    for o in OPTIONS:
        number = numbered.index(o) + 1 if o in numbered else None
        print(line(o, cfg, number))
    print(FACTS_HEAD)
    for fact in FACTS.values():
        print("     " + fact())


COUNT_WORDS = ("No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")
OFF_LINE = "{count} optional {parts} off. Run python3 tools/options.py to view or enable them."


MEANING_SETUP_ON = (
    "Search by meaning is on: the embedding server on this machine answered with {model}. Nothing was "
    "downloaded and nothing leaves this machine; the first index is built in the background at the next "
    "session start. `python3 tools/options.py off meaning` turns it off."
)
# Setting this to 1 keeps setup from asking a local server anything; the test runner sets it.
NO_PROBE_ENV = "MOTTORI_NO_LOCAL_PROBE"


def _meaning_at_setup(cfg):
    """Turn the list by meaning on when it costs nothing: the local server already answers with the
    model and the owner has not said no before (KIT-DR-094). MOTTORI_NO_LOCAL_PROBE=1 keeps setup from
    asking the server at all. Returns the config, changed or not."""
    option = BY_NAME["meaning"]
    if os.environ.get(NO_PROBE_ENV) == "1" or option["is_on"]() or "meaning" in declined(cfg):
        return cfg
    settings = json.loads(json.dumps(option.get("settings", {})))
    at = option.get("values_at")
    values = settings[at[0]][at[1]] if at else {}
    if option["missing"](values):
        return cfg
    with open(CONFIG, encoding="utf-8") as f:
        before = f.read()
    _merge(cfg, settings)
    save_config(cfg)
    if option["is_on"]():
        print(MEANING_SETUP_ON.format(model=values.get("model", "the model")))
        redraw_state_page()
    else:
        safeio.atomic_write(CONFIG, before)
    return load_config()


def cmd_setup():
    """Say in one line how many options are off and how to see them. Setup asks nothing: an agent
    runs it. The one option it turns on by itself is the list by meaning, and only when its local
    server already answers with the model and the owner has not declined it (KIT-DR-094)."""
    cfg = _meaning_at_setup(load_config())
    off = [o for o in OPTIONS if state(o, cfg) != "on"]
    if off:
        count = COUNT_WORDS[len(off)] if len(off) < len(COUNT_WORDS) else str(len(off))
        print(OFF_LINE.format(count=count, parts="part is" if len(off) == 1 else "parts are"))
    return 0


def _config_bytes():
    try:
        with open(CONFIG, "rb") as f:
            return f.read()
    except OSError:
        return None


def redraw_state_page():
    """Render the state page again after the configuration changed, so the next commit does not
    find it older than the configuration it was drawn from."""
    sys.stdout.flush()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "now.py"), "render"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode:
        last = (r.stderr.strip().splitlines() or [f"exit {r.returncode}"])[-1]
        print(f"The state page was not redrawn ({last}); run python3 tools/now.py render.")


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if not argv or argv[0] == "list":
        try:
            cfg = load_config()
        except (OSError, ValueError):
            cfg = {}  # before setup every option is simply off
        show(cfg)
        print(TURN)
        return 0
    if not os.path.isfile(CONFIG):
        print(C.legacy_layout() or f"no {P.tracked_name(P.config_file)} yet; run bash setup.sh first",
              file=sys.stderr)
        return 1
    if argv[0] == "setup":
        return cmd_setup()
    if argv[0] in ("on", "off") and len(argv) == 2 and argv[1] in FACTS:
        print(NOT_A_SWITCH.format(name=argv[1], fact=FACTS[argv[1]]()))
        return 1
    if argv[0] in ("on", "off") and len(argv) >= 2 and argv[1] in BY_NAME and (argv[0] == "on" or len(argv) == 2):
        before = _config_bytes()
        code = turn_on(argv[1], argv[2:]) if argv[0] == "on" else turn_off(argv[1])
        if _config_bytes() != before:
            redraw_state_page()
        return code
    print(USAGE.format(names=", ".join(BY_NAME)), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
