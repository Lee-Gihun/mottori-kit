# Evidence marker schema

A marker points from a decision or a change to what it rests on. `tools/dev/evidencecheck.py` checks the
markers in `system/specs/kit-decisions.md`, `CHANGELOG.md` and the rules table `system/dev/enforcement.md`:
each marker is well formed, and what it names exists in this tree. It does not ask whether a test ran;
continuous integration runs every suite. Whether a marker supports its claim is for a reviewer.

## Syntax

| Kind | Syntax | Exists when |
|---|---|---|
| Paper | `paper:<arXiv id or DOI>` | form only |
| Experiment | `experiment:<id>` | form only |
| Run | `run:<run id>` | the folder `_private/work/runs/<run id>/` exists |
| Decision | `decision:<DR-nnn or KIT-DR-nnn>` | `KIT-DR-nnn` has a `### DR-nnn` heading in `system/specs/kit-decisions.md`; `DR-nnn` has one in `instance/decisions.md` |
| Test | `test:<tools/tests/test_x.py::name>` | the file defines a function of that name |

An arXiv id is `YYMM.number` or `archive/YYMMNNN`, with an optional `vN`. A DOI is `10.`, a registrant
number, `/` and a suffix. Experiment ids use ASCII letters, digits, `.`, `_` and `-`; run ids also `+`.
Writing a marker in inline code keeps its end unambiguous.

## Required places

- The Context section of every decision record in `system/specs/kit-decisions.md`.
- Every `[Action required]` and `[Note]` item of `CHANGELOG.md`.

Each holds at least one valid marker, or exactly `evidence: none`, which states that there is none.

## Output

The checker prints one line per problem and exits 1, or prints nothing and exits 0. A tree with none of the
three files (an installed instance) passes.
