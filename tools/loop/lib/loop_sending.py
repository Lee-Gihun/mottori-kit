#!/usr/bin/env python3
"""Which of the loop's sources may send to a model runtime, and what each one sends.

A source may send when its cycle folder is in egress.model_send.allow_prefixes of the instance
configuration.
The functions take the model_send dict, as tools/lib/config.py egress_model_send() returns it, and
change only the loop's own prefixes. statement() says what leaves the machine for the sources chosen,
from the settings it depends on."""
import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402
import loop_sources  # noqa: E402
from loop_config import SOURCES  # noqa: E402
from loop_stores import PAPERS_BASE  # noqa: E402

# The folder each source's workers send from.
PREFIXES = {**{name: m.BASE + "/" for name, m in loop_sources.added().items()}, "papers": PAPERS_BASE + "/"}
NOTHING_ELSE = ("Nothing goes to the kit's authors. The model program runs under your account and can read any "
                "file your account can read, as in your own sessions.")
REFUSAL = "{source} is not allowed to send to a model runtime. To allow it: python3 tools/options.py on loop"


def allowed(model_send):
    """The sources whose cycle folder may be sent, in the order of SOURCES."""
    prefixes = model_send.get("allow_prefixes") or []
    return [s for s in SOURCES if PREFIXES[s] in prefixes]


def allow(model_send, sources):
    """model_send whose loop allowances are exactly the cycle folders of sources; others are kept."""
    allow_list = disallow(model_send)["allow_prefixes"]
    return dict(model_send, allow_prefixes=allow_list + [PREFIXES[s] for s in SOURCES if s in sources])


def disallow(model_send):
    """model_send without the loop's cycle folders in its allowances."""
    loop = set(PREFIXES.values())
    return dict(model_send, allow_prefixes=[p for p in model_send.get("allow_prefixes") or [] if p not in loop])


def statement(sources, root=None):
    """The lines that say what leaves this machine when a cycle of each of sources runs."""
    out = [line for name, sends in loop_sources.each("sends") if name in sources for line in sends(root)]
    if "papers" in sources:
        contact = loop_config.value("papers_contact", root)
        arxiv = (f"the search queries and the client name ({loop_config.value('papers_client', root)})"
                 + (f" and your contact address ({contact}) go to arXiv" if contact else
                    " go to arXiv (no contact address while loop.papers_contact is empty)"))
        # An added source may offer the papers proposal worker evidence of its own (its friction hook);
        # it says what that sends while it is chosen and what may still be read while it is not.
        offered = "".join(" " + (on if name in sources else off)
                          for name, (on, off) in loop_sources.each("FRICTION_SENT"))
        out.append(f"papers: {arxiv}, and the matching papers are downloaded; their text and files of this kit go "
                   "to the model runtime you use." + offered)
    return out
