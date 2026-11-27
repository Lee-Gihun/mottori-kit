#!/usr/bin/env python3
"""One line about background work: what this session, and other sessions on this folder, left running.

A runtime that hands its turn-end hook the list of background tasks still running (Claude Code
does: shell commands, subagents, workflows) also tells a live session when one finishes. It does
not show how far a task has got without a tool call, which tasks a machine restart cut off, or
what another session on the same folder is running. This fills those three gaps and nothing else.

  python3 tools/tasks.py    print the line for this folder now

tools/dispatch.py calls save() at a turn end and show() at a session start and at each prompt.
The line names each task, how long it has run and when its output last moved; for a workflow,
the agents finished per phase. It never carries a task's output text, and nothing running prints
nothing. Every error and every unknown input ends in silence: a hook that fails would show the
user an error on each prompt.
"work_line": "off" in the instance config switches it off.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C  # noqa: E402
import hook_input  # noqa: E402
import paths as P  # noqa: E402
import safeio  # noqa: E402

# Messages this module prints in more than one place, or too long to read inline.
PHASES = (
    ", agents finished per phase: {counts} (asked how far it is, give these counts phase by "
    "phase)"
)
RUNNING = "[tasks] {who} has background work running: {tasks}{more}."
USAGE = (
    "usage: tasks.py    print what this session and other sessions on this folder left running"
)

# The root comes from this file's location only, so a session never reads another instance's tasks.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP_SECONDS = 14 * 86400   # A snapshot nobody rewrote for two weeks describes nothing that still runs.
QUIET_SECONDS = 30 * 60     # Another session's task with no sign of life for this long is not called running.
SHOWN = 4                   # Tasks listed per session; the rest are counted, so the line stays short.
MAX_BYTES = 600             # The whole text a prompt can gain from this module.
SEEN = ".seen.json"         # Per viewing session, what it was last shown; a dot keeps it out of the snapshot glob.
UNREADABLE = False          # What _read() gives for a snapshot that cannot be read now.
ENDED, UNKNOWN = None, 0    # What _progress() gives as a task's last sign of life when it has ended, or none is known.


def _off():
    return C.work_line_off(ROOT)


def _store():
    """Snapshots hold task descriptions, so they live inside the Git directory, which Git never
    tracks. Without one nothing is saved: a folder outside Git has no untracked place to use."""
    return P.work_snapshots(ROOT)


def _read(path):
    """The snapshot, None when it is damaged, UNREADABLE when it cannot be read now (kept: only its
    owner rewrites it, and a passing permission or I/O fault does not make it wrong)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return UNREADABLE
    except ValueError:
        return None
    # A snapshot of another version or a damaged one is dropped rather than silencing every line.
    ok = isinstance(data, dict) and isinstance(data.get("tasks"), list) and all(
        isinstance(t, dict) and all(isinstance(t.get(k), str) for k in ("id", "type", "what"))
        and isinstance(t.get("since"), (int, float)) for t in data["tasks"])
    return data if ok else None


def _write(path, data):
    safeio.atomic_write(path, json.dumps(data, ensure_ascii=False))


def _drop(path):
    try:   # Another session may have removed it first.
        os.remove(path)
    except OSError:
        pass


def _boot():
    """Time the machine started, or 0 when it cannot be read (then nothing is reported as cut)."""
    try:
        with open("/proc/uptime", encoding="ascii") as f:
            return time.time() - float(f.read().split()[0])
    except (OSError, ValueError):
        pass
    try:   # By its full path: a scheduled job's search path may lack the folder of the system's tools.
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"], capture_output=True, text=True,
                             timeout=2).stdout
        return float(re.search(r"sec = (\d+)", out).group(1))
    except Exception:  # noqa: BLE001 - no boot time only means no restart report
        return 0


def save(event):
    """Turn end: save the tasks still running, keeping the time each was first seen. With none
    running the file is still written: its time is where _launch() starts to look for the script
    of a workflow launched later. A runtime whose turn-end input carries no task list leaves the
    saved list alone."""
    try:
        store = _store()
        sid, tasks = event.session, (event.raw or {}).get("background_tasks")
        if (not store or _off() or not isinstance(sid, str) or not re.fullmatch(r"[\w-]+", sid)
                or not isinstance(tasks, list)):
            return 0
        path = os.path.join(store, sid + ".json")
        before = _read(path) or {}   # damaged or unreadable: no first-seen times to keep
        old = {t["id"]: t for t in before.get("tasks", [])}   # _read() checked every row.
        now = time.time()
        rows = []
        for task in tasks:
            if not isinstance(task, dict) or not isinstance(task.get("id"), str):
                continue
            what = ": ".join(str(task[k]) for k in ("name", "description") if task.get(k))
            rows.append({"id": task["id"], "type": re.sub(r"\W", "", str(task.get("type", "task")))[:12],
                         "what": re.sub(r"\s+", " ", what)[:80],
                         "since": old.get(task["id"], {}).get("since", now)})
            if rows[-1]["type"] == "workflow" and isinstance(task.get("name"), str):
                # Finds the run's script, launched after the last turn end that did not list it; see _launch().
                after = old[task["id"]].get("after", 0) if task["id"] in old else before.get("at", 0)
                rows[-1].update(name=task["name"][:200], after=after)
        transcript = str(event.raw.get("transcript_path") or "")
        scratch = str(event.raw.get("scratchpad_dir") or "")
        # Only folder names are kept: where task output files and workflow journals appear.
        _write(path, {"session": sid, "at": now, "tasks": rows,
                      "out": os.path.join(os.path.dirname(scratch), "tasks") if scratch else "",
                      "wf": os.path.join(transcript[:-6], "subagents", "workflows")
                      if transcript.endswith(".jsonl") else ""})
    except Exception:  # noqa: BLE001 - see the module docstring: silence on every error
        pass
    return 0


def _span(seconds):
    minutes = max(0, int(seconds // 60))
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def _launch(snapshot, task, boot):
    """The run folder name of a workflow task, or None when its run cannot be told.

    No task names its run, but the runtime keeps each launch's script beside the runs as
    <name>-<run folder>.js. The task's run is that of the one script of its name written after the
    machine started and the last turn end that did not list the task, and no later than the turn
    end that first saw it. There is no answer when:
    - the task has no name, or the snapshot no workflow folder;
    - that turn end first saw two tasks of the name: one may have returned within the turn, and
      the newest script may be its;
    - the window holds no script of the name, or more than one."""
    name, wf, after = task.get("name"), snapshot.get("wf") or "", task.get("after", 0)
    same = sum(t.get("name") == name and t["since"] == task["since"] for t in snapshot["tasks"]
               if t["type"] == "workflow")
    if not isinstance(name, str) or not name or not wf or same > 1:
        return None
    runs = []
    try:
        for entry in os.scandir(os.path.join(os.path.dirname(os.path.dirname(wf)), "workflows", "scripts")):
            run = entry.name[len(name) + 1:-3]
            if entry.name.startswith(name + "-") and entry.name.endswith(".js") and run.startswith("wf_") \
                    and max(boot, after) <= entry.stat().st_mtime <= task["since"] + 1:
                runs.append(run)
    except OSError:
        return None
    return runs[0] if len(runs) == 1 else None


def _phases(folder):
    """The agents finished per phase in a run's journal, as "phase done/started, ...", or "" when
    the journal cannot be read."""
    phases, done = {}, set()
    try:
        with open(os.path.join(folder, "journal.jsonl"), "rb") as f:
            for raw in f:   # Row order is start order, so phases come out in the order the script entered them.
                if raw.startswith(b'{"type":"started"'):
                    try:   # A row cut off mid-append costs only itself.
                        row = json.loads(raw)
                    except ValueError:
                        continue
                    phases.setdefault(re.sub(r"\s+", " ", str(row.get("phase") or "agents"))[:30],
                                      []).append(row.get("key"))
                elif raw.startswith(b'{"type":"result"'):   # A result row carries the agent's whole answer: read only its key.
                    key = re.match(rb'\{"type":"result","key":"([^"]+)"', raw[:300])
                    done.add(key.group(1).decode() if key else None)
    except OSError:
        return ""
    return ", ".join(f"{phase} {sum(k in done for k in keys)}/{len(keys)}" for phase, keys in phases.items())


def _progress(snapshot, task, boot):
    """(time of the last sign of life, UNKNOWN, or ENDED when the task has ended; per-phase counts or "")."""
    output = os.path.join(snapshot.get("out") or "", task["id"] + ".output")
    if task["type"] != "workflow":
        try:
            # A subagent's output is a link to its conversation record: its time is read, the file
            # is never opened. A shell task's output is a plain file the runtime ends with a marker.
            if task["type"] != "shell":
                return os.stat(output).st_mtime, ""
            with open(output, "rb") as f:
                f.seek(max(0, os.fstat(f.fileno()).st_size - 64))
                # A task a subagent started reports its end to that subagent, so this session's
                # saved list would keep calling it running without this check.
                if b"[exited with code" in f.read():
                    return ENDED, ""
                return os.fstat(f.fileno()).st_mtime, ""
        except OSError:
            return UNKNOWN, ""
    if os.path.exists(output) and os.path.getsize(output) > 0:   # Written once, when the workflow returns.
        return ENDED, ""
    run = _launch(snapshot, task, boot)
    if run is None:
        return UNKNOWN, ""
    folder = os.path.join(snapshot["wf"], run)
    # A run's folder holds one record per agent, which grow while the agents work.
    try:
        moved = max((e.stat().st_mtime for e in os.scandir(folder)), default=UNKNOWN)
    except OSError:
        moved = UNKNOWN
    return moved, _phases(folder)


def _current(path, now, keep):
    """The snapshot at path, or None when it cannot be read now, is damaged or nobody rewrote it for
    KEEP_SECONDS. A damaged or expired one is removed, unless this run shows its lines to nobody (keep)."""
    snapshot = _read(path)
    if snapshot is UNREADABLE:
        return None
    if snapshot is None or not isinstance(snapshot.get("at"), (int, float)) \
            or now - snapshot["at"] > KEEP_SECONDS:
        if not keep:
            _drop(path)
        return None
    return snapshot


def _cut(path, snapshot, own, boot, keep):
    """The notice that a machine restart cut off this snapshot's tasks, or None. Said once to the
    session that owned the tasks and once to the others; the owner rewrites its file at its next turn end."""
    flag = "told_owner" if own else "told_others"
    names = [t for t in snapshot["tasks"] if _progress(snapshot, t, boot)[0] is not ENDED]
    if not names or snapshot.get(flag):
        return None
    if not keep:
        snapshot[flag] = True
        _write(path, snapshot)
    when = time.strftime("%m-%d %H:%M", time.localtime(boot))
    who = "" if own else " (another session on this folder)"
    listed = "; ".join(f'"{t["what"]}" ({t["type"]})' for t in names)
    return ("cut", path, own), f"[tasks] Cut off by a machine restart at {when}{who}: {listed}. Not running now."


def _parts(snapshot, own, boot, now):
    """([(task id, counts)], [one text per task still running]) for one snapshot."""
    parts, keys = [], []
    for task in snapshot["tasks"]:
        moved, counts = _progress(snapshot, task, boot)
        if moved is ENDED:
            continue
        idle = now - (moved or snapshot["at"])   # with no sign of life known, from the turn end that saw it
        if not own and idle > QUIET_SECONDS:
            continue
        keys.append((task["id"], counts))
        age = _span(now - task["since"])
        part = f'"{task["what"]}" ({task["type"]}), started {age} ago, output last moved {_span(idle)} ago'
        parts.append(part + (PHASES.format(counts=counts) if counts else ""))
    return keys, parts


def _render(own, parts, shown):
    who = ("this session" if own else "another session on this folder")
    if not shown:
        return RUNNING.format(who=who, tasks=f"{len(parts)} task(s)", more="")
    more = f"; and {len(parts) - shown} more" if len(parts) > shown else ""
    return RUNNING.format(who=who, tasks="; ".join(parts[:shown]), more=more)


def _fit(out, runs):
    """Render the running-task lines into out, within MAX_BYTES with the cut notices.

    Fewer tasks named, rather than text cut off at the byte limit: the longest line that still
    names a task gives up one name at a time, down to its count alone, so every session keeps its
    place in the 600 bytes. Each run is [index in out, own, parts, names shown]."""
    def render(run):
        out[run[0]] = (out[run[0]][0], _render(*run[1:]))

    def size(text):
        return len(text.encode("utf-8"))
    for run in runs:
        render(run)
    while size("\n".join(text for _, text in out)) > MAX_BYTES:
        naming = [run for run in runs if run[3]]
        if not naming:
            break
        longest = max(naming, key=lambda run: size(out[run[0]][1]))
        longest[3] -= 1
        render(longest)
    return out


def _lines(sid, prompt):
    """Return [(what changed it, text)], one per session with something to say. Without a session
    id (a hand run) or in a probe nobody's context receives the lines, so nothing is marked
    as told and nothing is removed."""
    store = _store()
    if not store:
        return []
    keep = sid is None or hook_input.probe()
    finished = re.findall(r"<task-id>([^<]+)</task-id>", str(prompt or "")[:4000])
    now, boot, out, runs = time.time(), None, [], []
    for path in sorted(glob.glob(os.path.join(store, "*.json"))):
        snapshot = _current(path, now, keep)
        if snapshot is None:
            continue
        own = snapshot.get("session") == sid
        if own and finished and not keep:   # The runtime is telling the model this task ended; do not call it running.
            snapshot["tasks"] = [t for t in snapshot["tasks"] if t["id"] not in finished]
            _write(path, snapshot)
        if not snapshot["tasks"]:   # Says nothing either way, so the boot time is not read for it.
            continue
        boot = _boot() if boot is None else boot
        if boot > snapshot["at"]:
            cut = _cut(path, snapshot, own, boot, keep)
            if cut:
                out.append(cut)
            continue
        keys, parts = _parts(snapshot, own, boot, now)
        if parts:
            out.append((("run", path, own, tuple(keys)), None))
            runs.append([len(out) - 1, own, parts, min(SHOWN, len(parts))])
    index = _catch_up(keep)
    if index:
        out.append(index)
    return _fit(out, runs)


def _catch_up(keep):
    """The search index's catch-up behind the session (tools/lib/recall_store.py), or None. Its
    module is loaded only while it has something to say."""
    if not os.path.exists(P.recall_catch_up(ROOT)):
        return None
    import recall_store
    return recall_store.catch_up_notice(keep, ROOT)


def _text(lines):
    data = "\n".join(text for _, text in lines).encode("utf-8")
    if len(data) <= MAX_BYTES:
        return data.decode("utf-8")
    return data[:MAX_BYTES - 3].decode("utf-8", "ignore") + "..."


def _read_seen(path):
    try:
        with open(path, encoding="utf-8") as f:
            seen = json.load(f)
    except (OSError, ValueError):
        return {}
    return {s: v for s, v in seen.items() if isinstance(v, list) and len(v) == 2
            and isinstance(v[1], (int, float))} if isinstance(seen, dict) else {}


def show(event, start=False):
    """Session start and prompt: print the line. At a prompt it is printed only when what it says
    changed since this session last saw it (durations aside): the same line again tells the model
    nothing new and costs context at every prompt (the measurement is in KIT-DR-045)."""
    try:
        if _off():
            return 0
        sid = event.session if isinstance(event.session, str) and re.fullmatch(r"[\w-]+", event.session) else None
        store = _store()
        if sid is None or not store:   # Unknown input: no context to show it to, and tasks would be labelled as another's.
            return 0
        lines = _lines(sid, event.prompt)
        if not hook_input.probe():
            path = os.path.join(store, SEEN)
            seen = _read_seen(path)
            key, now = repr([k for k, _ in lines]), time.time()
            changed = seen.get(sid, [None])[0] != key
            if changed:
                seen = {s: v for s, v in seen.items() if now - v[1] < KEEP_SECONDS}
                seen[sid] = [key, now]
                _write(path, seen)
            # A session start begins a context that holds no earlier line, so it always prints.
            if not changed and not start:
                return 0
        if lines:
            print(_text(lines))
    except Exception:  # noqa: BLE001 - see the module docstring: silence on every error
        pass
    return 0


def main(argv):
    if argv[1:] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if argv[1:]:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        if not _off():
            lines = _lines(None, "")
            if lines:
                print(_text(lines))
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
