# tools/loop/sources/

A source of the improvement loop that this installation adds. The kit ships none here: its one source, papers,
lives in `tools/loop/lib/loop_papers.py`. Each Python file here is one source, read by
[`tools/loop/lib/loop_sources.py`](../lib/loop_sources.py); the file's name is the source's name. A broken file
stops every loop command with its path, so a mistake here is never skipped quietly.

## What the module defines

Required:

| Name | What it is |
|---|---|
| `NAME` | The source's name, the same as the file's name, and not `papers`. |
| `BASE` | The folder of its cycle folders, relative to the instance root, under `_private/`. Workers send from here, `on loop` allows exactly this folder, and the applier judges only cycles in it. |
| `HOME` | The folder of its own files: `state.json` (with `last_cycle`, the date of the last cycle), `cycle.log` and the scheduler's log. |
| `PROGRAM` | The bash script that runs one cycle, relative to the instance root: `["/bin/bash", "tools/loop/notes_cycle.sh"]`. The loop adds `--force` when you run it by hand. |
| `SCHEDULE` | Its weekly time: `{"weekday": 0, "hour": 21, "minute": 0}`, weekday 0 being Sunday. `loop.schedule` can change it. |
| `CYCLE_NAME` | A regular expression for a cycle folder's name inside `BASE`, such as `r"\d{4}-\d{2}-\d{2}$"`. |
| `INPUT` | The document in a cycle folder that the judge reads, such as `REVIEW.md`. |
| `material(d)` | The judge prompt's line naming what to judge in cycle folder `d`. |

Optional:

| Name | What it is |
|---|---|
| `sends(root)` | The lines `on loop` prints for what a cycle of this source sends, and to whom. Write every kind of data it reads. |
| `unusable(cycle_dir)` | Why a cycle folder (an absolute path) is never judged, such as a failed collection, or `None`. |
| `watch(root, today, ls, heal_cmds)` | The health check's problems for this source, as `[(key, message)]`; `tools/loop/lib/loop_watch_checks.py` has `watched`, `age`, `apply_problem`, `ceiling_problem` and `apply_cmd` to build them. |
| `HEAL_GROUPS`, `HEAL_PREFIXES` | Which of its problem keys one repair run fixes together. |
| `status_note(root)` | One extra line for `loops.py status` while the source may send, or `None`. |
| `friction(root)` | Text the papers proposal worker reads while this source may send, such as where your recurring corrections are counted. `FRICTION_SENT` is then a pair of sentences for `on loop`: what that sends while this source is chosen, and what may still be read while it is not. |
| `KEYS` | Settings of its own in the `loop` block: `{key: (default, kind, meaning)}`, kind being `flag`, `paths`, `path`, `optional_path`, `line`, `texts` or `count`. |
| `STAGES` | Names of its model steps, so `loop.runtime_orders` can name them. |
| `LOOP_FILES` | Its own files, which a cycle may change only as the loop's own tools (`tools/loop/loop_policy.py`). |
| `COST` | One sentence `on loop` prints about what one of its cycles costs. |

The cycle program writes `state.json` in `HOME`, a folder per cycle in `BASE` with `INPUT` in it, and its report as
`REPORT.md` there. `tools/loop/lib/loop_beat.py` gives it the lock, the log, the workers and the state file that
papers uses; `tools/loop/papers_apply.py CYCLE --source NAME` judges and builds what it proposed.
