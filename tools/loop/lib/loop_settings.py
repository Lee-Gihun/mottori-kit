#!/usr/bin/env python3
"""Whether a cycle of the improvement loop may start: no problem in the loop's settings and the source's
allowance to send, with the lines that say why not.

A problem is an unknown key, a key written twice or an unusable value of the `loop` block
(tools/loop/lib/loop_config.py). While there is one, no cycle judges or builds. A root argument names
the instance root; without it, the tree this file lives in."""
import os
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
sys.path[:0] = [p for p in (os.path.join(TOOLS, "loop"), os.path.join(TOOLS, "loop", "lib")) if p not in sys.path]
import loop_config  # noqa: E402
import loop_sending  # noqa: E402
import paths as P  # noqa: E402

STATUS = "python3 tools/loop/loops.py status"
KEYS_COMMAND = "python3 tools/loop/lib/loop_config.py"


def problems(root=None):
    """Every problem of the loop's settings, one line each."""
    return loop_config.problems(root)


def _where():
    return f"{P.tracked_name(P.config_file)} ({loop_config.BLOCK})"


def stopped_line(found):
    """The one line a cycle or the applier prints when the settings stop it."""
    n = len(found)
    return (f"stopped: {n} problem{'' if n == 1 else 's'} in {_where()}; nothing judged or built. "
            f"See: {STATUS}")


def report_lines(found):
    """What status prints first while the settings stop the loop."""
    return (["config error: loop is stopped (no cycle will judge or build until fixed)", f"  {_where()}:"]
            + [f"  - {line}" for line in found]
            + [f"  Fix {P.tracked_name(P.config_file)}, then run `{STATUS}`. Valid settings: `{KEYS_COMMAND}`"])


def cycle_refusal(source, model_send, root=None):
    """The one line that ends a cycle of source before it sends anything or starts a worker, or None
    when it may run: a problem of the settings, or no allowance to send (tools/options.py on loop).
    model_send is the instance's egress.model_send, as tools/lib/config.py egress_model_send() returns it."""
    found = problems(root)
    if found:
        return stopped_line(found)
    if source not in loop_sending.allowed(model_send):
        return loop_sending.REFUSAL.format(source=source)
    return None
