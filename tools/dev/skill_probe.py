#!/usr/bin/env python3
"""Measure whether Claude Code opens the thinking skills on tasks that should and should not open one.

Usage: python3 tools/dev/skill_probe.py <installation> <tasks.json> [--runs N] [--only ID,ID]
       [--out DIR] [--model NAME] [--budget-usd B] [yes]

Each run is a real Claude Code session on the owner's account, started in <installation> and sent
one task sentence; it is billed. So nothing starts without the owner's yes: asked once on a
terminal, or the word yes added to the command. The sessions write the installation's own state,
so the tree this tool sits in and a folder without instance/config.json are refused. Claude Code
also reads a CLAUDE.md in any folder above the one it starts in, so an installation below such a
folder is refused: its sessions would follow someone else's instructions as well.

Sessions run one at a time. Each event stream is saved as <out>/<id>-<run>.jsonl; the default
<out> is a new folder under the installation's private work area, because a stream lists the
account's tools and plugins. Claude Code itself leaves one empty folder for the installation
under ~/.claude/projects. The tool prints the model the sessions named, one line per task and
four totals, and writes the same as summary.json in <out>. It does not judge pass or fail. It
exits 1 when a run gave no result event (a failed session or a changed stream format), naming
each such run, and 2 on a usage error or a refusal.
"""

import argparse
import datetime
import json
import os
import shutil
import statistics
import subprocess
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P  # noqa: E402

ROOT = os.path.dirname(TOOLS)
# The variable that names the program to start; a test points it at a stand-in.
PROGRAM_ENV = "MOTTORI_SKILL_PROBE_CLAUDE_BIN"
PROGRAM_DEFAULT = "claude"
# The only variables a session inherits.
KEEP_ENV = ("HOME", "PATH", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "LC_ALL", "TERM")
SESSION_TIMEOUT = 900   # seconds; a session past it is stopped and counts as no result
BUDGET_DEFAULT = 2.0    # US dollars per session, passed as --max-budget-usd
YES = "yes"

PLAN = (
    "This starts {count} Claude Code session(s), one at a time, in {installation}. Each is a real "
    "session on your account and is billed; each may spend up to ${budget:g} (--max-budget-usd)."
)
ASK = "Start them? [y/N] "
NO_TERMINAL = (
    "Nothing was started: there is no terminal here to ask on. An assistant reading this asks the "
    "owner first, and only after the owner said yes runs `{command}`."
)
REFUSE_OWN_TREE = ("refused: {installation} is the tree this tool sits in; the sessions would write "
                   "its state. Name an installed copy.")
REFUSE_NOT_INSTALLED = ("refused: {installation} has no instance/config.json, so it is not an "
                        "installation; the sessions would write its state.")
REFUSE_RULES_ABOVE = ("refused: {found} is above {installation} and Claude Code would read it too, so "
                      "the sessions would not measure this installation alone. Put the installation "
                      "where no folder above it holds a CLAUDE.md.")
# The instruction files Claude Code reads in each folder above the one a session starts in.
RULES_ABOVE = ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md"))


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="tools/dev/skill_probe.py", description=__doc__.split("\n")[0])
    parser.add_argument("installation")
    parser.add_argument("tasks")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", default="")
    parser.add_argument("--out")
    parser.add_argument("--model")
    parser.add_argument("--budget-usd", type=float, default=BUDGET_DEFAULT)
    parser.add_argument("consent", nargs="?", choices=[YES])
    args = parser.parse_intermixed_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.budget_usd <= 0:
        parser.error("--budget-usd must be above 0")
    return args


def load_tasks(path, only):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tasks = data["tasks"]
    wanted = [i for i in only.split(",") if i]
    unknown = sorted(set(wanted) - {t["id"] for t in tasks})
    if unknown:
        raise SystemExit(f"no such task id: {', '.join(unknown)}")
    if wanted:
        tasks = [t for t in tasks if t["id"] in wanted]
    return list(data["thinking_skills"]), tasks


def rules_above(installation):
    """The first instruction file in a folder above the installation, or None."""
    folder = os.path.dirname(os.path.realpath(installation))
    while True:
        for name in RULES_ABOVE:
            if os.path.isfile(os.path.join(folder, name)):
                return os.path.join(folder, name)
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent


def refusal(installation):
    if os.path.realpath(installation) == os.path.realpath(ROOT):
        return REFUSE_OWN_TREE.format(installation=installation)
    if not os.path.isfile(P.config_file(installation)):
        return REFUSE_NOT_INSTALLED.format(installation=installation)
    found = rules_above(installation)
    if found:
        return REFUSE_RULES_ABOVE.format(found=found, installation=installation)
    return None


def consent(args, count):
    print(PLAN.format(count=count, installation=args.installation, budget=args.budget_usd))
    if args.consent == YES:
        return True
    if not sys.stdin.isatty():
        command = " ".join(["python3 tools/dev/skill_probe.py", *sys.argv[1:], YES])
        print(NO_TERMINAL.format(command=command))
        return False
    try:
        answer = input(ASK)
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", YES):
        print("Nothing was started.")
        return False
    return True


def session_env():
    return {name: os.environ[name] for name in KEEP_ENV if name in os.environ}


def session_command(program, task, args):
    command = [program, "-p", task, "--output-format", "stream-json", "--verbose",
               "--setting-sources", "project", "--permission-prompts", "none",
               "--no-session-persistence", "--max-budget-usd", f"{args.budget_usd:g}"]
    if args.model:
        command += ["--model", args.model]
    return command


def read_stream(path):
    """The skills a stream opened, in order, its result event and the model its first event names.

    The result and the model are None when the stream has none.
    """
    skills, result, model = [], None, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "result":
                result = event
            if event.get("type") == "system" and event.get("subtype") == "init" \
                    and isinstance(event.get("model"), str):
                model = event["model"]
            content = (event.get("message") or {}).get("content") if event.get("type") == "assistant" else None
            for block in content if isinstance(content, list) else ():
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
                    name = (block.get("input") or {}).get("skill")
                    if isinstance(name, str):
                        skills.append(name)
    return skills, result, model


def thinking(skills, names):
    """The opened skills that are thinking skills; a plugin's prefix (plugin:name) is ignored."""
    return [s for s in skills if s.rsplit(":", 1)[-1] in names]


def run_one(program, task, args, out, run):
    path = os.path.join(out, f"{task['id']}-{run}.jsonl")
    with open(path, "wb") as stream:
        try:
            subprocess.run(session_command(program, task["text"], args), cwd=args.installation,
                           env=session_env(), stdin=subprocess.DEVNULL, stdout=stream,
                           stderr=subprocess.DEVNULL, timeout=SESSION_TIMEOUT)
        except subprocess.TimeoutExpired:
            pass
    return path


def version(program):
    try:
        done = subprocess.run([program, "--version"], env=session_env(), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unknown ({exc.__class__.__name__})"
    return (done.stdout or done.stderr).strip() or f"unknown (exit {done.returncode})"


def summarize(names, tasks, runs, asked, program_version):
    """The summary of all runs. Its model is what the sessions named: a default changes over time,
    so the name asked for (or none) is given only when no session named one."""
    rows, lengths, cost, missing = [], [], 0.0, []
    named = sorted({run["model"] for task_runs in runs.values() for run in task_runs if run["model"]})
    model = ", ".join(named) or f"{asked or 'the default'} (no session named its model)"
    totals = {"open": [0, 0], "closed": [0, 0]}
    for task in tasks:
        opened_runs, opened = 0, []
        for run in runs[task["id"]]:
            if run["result"] is None:
                missing.append(run["stream"])
                continue
            totals[task["expect"]][1] += 1
            lengths.append(run["answer_chars"])
            cost += run["cost_usd"]
            hit = thinking(run["skills"], names)
            if hit:
                opened_runs += 1
                totals[task["expect"]][0] += 1
                opened += [s for s in hit if s not in opened]
        rows.append({"id": task["id"], "expect": task["expect"], "opened_runs": opened_runs,
                     "runs_with_result": sum(r["result"] is not None for r in runs[task["id"]]),
                     "runs": len(runs[task["id"]]), "opened": opened})
    return {"model": model, "version": program_version, "tasks": rows,
            "should_open": {"opened": totals["open"][0], "runs": totals["open"][1]},
            "should_stay_closed": {"opened": totals["closed"][0], "runs": totals["closed"][1]},
            "median_answer_chars": statistics.median(lengths) if lengths else None,
            "cost_usd": round(cost, 6), "no_result": missing,
            "runs": {tid: [{k: v for k, v in r.items() if k != "result"} for r in rs]
                     for tid, rs in runs.items()}}


def report(summary):
    print(f"model: {summary['model']}")
    print(f"version: {summary['version']}")
    for row in summary["tasks"]:
        which = ", ".join(row["opened"]) or "none"
        print(f"{row['id']}  should {'open' if row['expect'] == 'open' else 'stay closed'}  "
              f"opened in {row['opened_runs']} of {row['runs_with_result']} runs: {which}")
    o, c = summary["should_open"], summary["should_stay_closed"]
    print(f"a thinking skill opened in {o['opened']} of {o['runs']} runs of the tasks that should open one")
    print(f"a thinking skill opened in {c['opened']} of {c['runs']} runs of the tasks that should not")
    median = summary["median_answer_chars"]
    print(f"median answer length: {'none' if median is None else f'{median:g} characters'}")
    print(f"summed cost: ${summary['cost_usd']:.4f}")
    for stream in summary["no_result"]:
        print(f"no result: {stream}")


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    stop = refusal(args.installation)
    if stop:
        print(stop)
        return 2
    names, tasks = load_tasks(args.tasks, args.only)
    if not consent(args, len(tasks) * args.runs):
        return 0
    program = os.environ.get(PROGRAM_ENV) or PROGRAM_DEFAULT
    program = shutil.which(program) or program
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.out or os.path.join(P.private_area(args.installation), "work", "skill-probe", stamp)
    os.makedirs(out, exist_ok=True)
    runs = {}
    for task in tasks:
        runs[task["id"]] = []
        for run in range(1, args.runs + 1):
            path = run_one(program, task, args, out, run)
            skills, result, model = read_stream(path)
            answer = result.get("result") if result else None
            runs[task["id"]].append({
                "stream": os.path.relpath(path, args.installation), "skills": skills,
                "result": result, "model": model,
                "answer_chars": len(answer) if isinstance(answer, str) else 0,
                "cost_usd": float(result.get("total_cost_usd") or 0) if result else 0.0})
    summary = summarize(names, tasks, runs, args.model, version(program))
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    report(summary)
    print(f"streams and summary.json: {out}")
    return 1 if summary["no_result"] else 0


if __name__ == "__main__":
    sys.exit(main())
