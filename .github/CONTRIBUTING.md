# Contributing

This page is for people who change the kit. Installing and using the kit never needs it.

## Tests and records

`tools/tests/`, `tools/dev/` and `system/dev/` hold the kit's own tests, contributor tools and records. No Claude
or Codex hook command runs a file in them, and no tool under `tools/` imports from them. The three folders ship
with every clone and the documents cite files in them, so keep them.

Before a commit, run:

```bash
python3 tools/tests/run.py --full   # every test file, the full mutation set, the installed-shape test and the fresh-install test
python3 tools/linkcheck.py          # ends with "broken: 0"
python3 tools/dev/evidencecheck.py  # prints nothing when every evidence marker is well formed and names something here
```

A commit itself runs only the checks an installed instance runs (links and state), and only where the Git hooks
are installed: `bash setup.sh` installs them, and in a clone where setup has not run nothing checks a commit.
Continuous integration (`.github/workflows/gates.yml`) runs the same three commands and `git diff --check` on
Ubuntu and macOS, and only in a repository named `mottori-kit`. An evidence marker follows
`system/dev/evidence-schema.md`, and `system/dev/enforcement.md` says which rule is checked by what; a rule you
add gets a row there. A part you add gets a row in `system/specs/model-assumptions.md`. A file you add or remove
changes `system/dev/kit-files.txt`, the list of the kit's own files (rewrite it with
`git ls-files > system/dev/kit-files.txt`): the checks of the kit's own conventions read it, so an
installation's own files, in its owner's language, are never judged by them.

`bash tools/tests/test_fresh_install.sh` reproduces a setup without a terminal in a temporary clone: setup (which
installs the hooks), a hook check, the link check, doctor, a stub worker run and a setup rerun.
`tools/tests/test_portability.py` backs the support matrix in `SETUP.md` step 1, and
`test:tools/tests/test_devtree_gate.py::test_partial_install_without_config_fails_closed` pins the partial
installation rule in `MANUAL.md` section 4. `system/CHECKLIST.md` and KIT-DR-011 define where human checks
begin. Times and version numbers in the documents are measurements from the stated test environment, not
guarantees for every machine.

## Skills

Each skill, slash commands included, has one source folder in `system/skills/<name>/`. Claude Code reads a copy in
`.claude/skills/`, Codex and Antigravity one in `.agents/skills/`. After changing a skill, write the copies again:

```bash
python3 tools/skills.py write   # make every copy match its source
python3 tools/skills.py check   # name each copied file that is missing, extra or different (no model call)
```

## Measuring whether skills open

`tools/dev/skill_probe.py` sends the twenty tasks of `system/dev/skill-probe-tasks.json` to Claude Code and counts
in how many runs a thinking skill was opened: ten tasks should open one, ten should not. Run it after changing a
skill's name or description or the lines of `AGENTS.md` that point to a skill, and when the model changes. Run it in
a throwaway installation (a clone where `bash setup.sh` has run), never in the kit tree itself, and with no
`CLAUDE.md` in any folder above it, because Claude Code reads those too and the tool refuses such a place:

```bash
python3 tools/dev/skill_probe.py ../probe system/dev/skill-probe-tasks.json --runs 3
```

Three runs per task is the unit, because whether a skill opens moves from run to run: that is 60 real
Claude Code sessions on your account, one at a time, each billed and capped at $2 by default (`--budget-usd`).
It asks once before it starts any. It measures Claude Code only, and it measures whether a skill was opened,
not whether the answer was better. The streams and `summary.json` land in the installation's
`_private/work/skill-probe/`. Claude Code itself leaves one empty folder for the installation under
`~/.claude/projects`. Record the result as a new row in section 8 of `system/specs/model-assumptions.md`,
where the last result is.

## The gate failure drill

The test suites run these failure cases on every change, so a user does not need to: a broken link at commit
(`tools/tests/test_bypass_pins.py`), a missing baseline (`test_h1_g11_absent_baseline_blocks` there), a checker that
crashes (`test_gate_check_blocks_when_measure_raises` in `tools/tests/test_install_checks.py`) and a corrupt baseline
(`test_corrupt_baseline_block_names_path_and_command` in `tools/tests/test_gate.py`). To watch an installed copy do
the same by hand, run this in a disposable clone. In the original, a broken gate would leave the commit of case 1
in real history. Each case must block; one that passes means the gate does nothing.

```bash
T="$(mktemp -d)" && git clone -q . "$T/gatetest" && cd "$T/gatetest"
bash setup.sh --name gatetest >/dev/null
python3 tools/gate.py baseline

# 1) Does a broken reference block a commit?
#    The file is under system/ because the repository root is deny-by-default, so git add would fail there
printf '[missing](nope-zz.md)\n' > system/_gatetest.md
git add system/_gatetest.md && git commit -m "must be blocked"   # Failure is success. The clone is disposable if it passes
git reset -q HEAD system/_gatetest.md 2>/dev/null; rm -f system/_gatetest.md

# 2) If a checker crashes, does the gate block instead of reporting zero issues?
python3 tools/gate.py dirty
cp tools/linkcheck.py /tmp/lc.bak && printf 'def ((((\n' >> tools/linkcheck.py
echo '{}' | python3 tools/gate.py check     # Must block with "Checkers produced no result"
cp /tmp/lc.bak tools/linkcheck.py

# 3) Does the gate block both a missing and a corrupt baseline, without automatic adoption?
cp state/.gate-baseline.json /tmp/bl.bak
rm state/.gate-baseline.json
python3 tools/gate.py dirty && echo '{}' | python3 tools/gate.py check
cp /tmp/bl.bak state/.gate-baseline.json
printf '{ corrupt' > state/.gate-baseline.json
python3 tools/gate.py dirty && echo '{}' | python3 tools/gate.py check
cp /tmp/bl.bak state/.gate-baseline.json

cd - >/dev/null && rm -rf "$T"      # Clean up the disposable clone
```
