# Evidence marker schema

Evidence markers are pointers that let a machine find the basis for a decision or change. The checker judges
only marker syntax and the existence of local targets. Independent review determines whether an external source
exists and whether the marker actually supports the claim.

## Allowed syntax

| Kind | Syntax | Examples |
|---|---|---|
| Paper | `paper:<arXiv id or DOI>` | `paper:2609.09134`, `paper:10.1000/example` |
| Experiment | `experiment:<id>` | `experiment:fresh-install-20260917` |
| Run | `run:<run id>` | `run:20260917T163052+0900-codex-f58c6c0b` |
| Decision | `decision:<DR-nnn or KIT-DR-nnn>` | `decision:DR-001`, `decision:KIT-DR-012` |
| Test | `test:<tools/test_x.py::name>` | `test:tools/test_evidencecheck.py::test_malformed_marker_fails` |

An arXiv ID may use modern `YYMM.number` or legacy `archive/YYMMNNN` syntax and may have a `vN` version suffix.
A DOI requires the `10.` prefix, a registrant number, and a suffix after `/`. Experiment IDs use ASCII letters,
digits, `.`, `_`, and `-`; run IDs also permit `+`. Inline code is recommended to keep punctuation and
boundaries unambiguous.

## Local existence checks

- `decision:KIT-DR-nnn` resolves to the `### DR-nnn` heading in `system/kit-decisions.md`.
- `decision:DR-nnn` resolves to the heading in `system/decisions.md` at the local root.
- `test:tools/test_x.py::name` requires both the file in the checked tree and the named Python function.
- `run:<run id>` requires `_private/work/runs/<run id>/` at the local root.
- `paper:` and `experiment:` may have sources outside this repository, so only syntax is checked. They are
  reported as `REVIEW external existence not checked`, which is not a blocking issue.

During pre-commit, the extracted index is the checked tree, while runs and instance decision records that live
outside Git are resolved from the current local root.

## Required locations

- Every DR in `system/kit-decisions.md` has at least one allowed marker in its Context section. An existing DR
  whose evidence pointer cannot be reconstructed keeps its body unchanged and uses a separate `evidence: none`
  marker.
- Every `[Action required]` and `[Know]` item in `CHANGELOG.md` has at least one allowed marker in its section.
  If there is no evidence, state exactly `evidence: none` instead of hiding that absence.
- Every `ENFORCED` row in `system/enforcement-matrix.md` has a `test:` marker on the same row.

`evidence: none` is an explicit exception only for the two required CHANGELOG tags and existing DR contexts. It
does not mean evidence exists, prove marker suitability, or exempt any other required location.

## Checker output contract

`python3 tools/evidencecheck.py` exits 1 when issues exist and 0 otherwise. `--issues` always exits 0 and uses
this format:

```text
<stable ID>\t<display text>
~review|<file>|<marker>\tREVIEW <display text>
#issues <N>
```

The trailer is always the last line. `~review|` rows do not count as issues. `tools/gate.py` and the pre-commit
hook consume only blocking issues, in the same way as other checkers.
