# Code and comments

Source files explain the current program. A reader should understand how to use
and safely change a module without knowing the sessions that produced it.

## What belongs next to code

- State the purpose, inputs, outputs, side effects, failure behavior, and necessary
  ordering constraints at the interface that owns them.
- Explain non-obvious mechanisms and tradeoffs. A reason must remain understandable
  without opening a decision record. Link deeper design when useful.
- Describe a regression by the behavior it protects, not the reviewer or review round.
- Remove comments that merely repeat clear code. Prefer clear names over an extra
  explanation of a vague name, but keep unrelated refactoring out of a comment edit.

Rewrite an incident as its current mechanism:

```python
# Hooks can export Git variables that select a different repository.
# Clear them before running Git in this worktree.
```

The incident's date, participants, run counts, and review narrative belong in a
decision or observation record. Preserve evidence with its original scope; an old
comment is not a newly verified fact. Historical documents can retain history.

A number, date, or version can be essential: a protocol limit, compatibility cutoff,
unit, or calibration condition may explain a current constraint. Keep the necessary
fact locally and put lengthy measurement history in its evidence document.

## Language and length

Write comments and docstrings in plain, concise English. Use complete explanations
where needed; there is no line-count quota. Avoid rhetorical questions, self-praise,
task status, and instructions addressed to the agent that wrote the file.

Keep exact non-English terms when translation would obscure a parser label, quoted
input, or regression case. Describe their role in English. Do not translate runtime
prompts, localized output, schema values, or fixture data as part of comment cleanup.
Human-facing CLI help derived from a docstring may change to English; retain its
commands, options, and meaning, and record that visible change.

## Text with a consumer

Preserve licenses, shebangs, encoding declarations, type annotations, linter and
formatter directives, generated fingerprints, and markers consumed by tools.
Comment syntax does not make these disposable prose.

Before editing a docstring, check whether help generation, a CLI decorator, doctest,
reflection, or a prompt builder consumes it. Before editing a shell heredoc, identify
whether it contains code or emitted text. Keep prompt bodies and exact test examples
unchanged unless their behavior is deliberately in scope.

Check source-reading tests and inventories too. A filename in a heading or a comment
inside a mutation fixture may be part of an existing test's input. Preserve that
connection or update the consumer explicitly without weakening the tested behavior.

## Review and verification

For a broad cleanup, preserve the starting files and record the reviewed scope.
Keep required facts locally, move history to the appropriate record, and preserve
frozen evidence. Snapshot storage must be outside exporter and indexer inputs.

Compare executable syntax and runtime literals separately from commentary. Python
AST equality with docstrings removed does not prove unchanged help or reflection.
Use language-aware checks for scripts, preserve consumed markers, and run relevant
existing checks. Treat any behavior change as a separate change with its own reason.

Judge the result by whether a fresh reader can explain the current behavior and its
constraints. Counts of comments, English words, or removed lines measure coverage,
not quality. Do not add a keyword or length gate to substitute for this judgment.
