Korean: `README.ko.md`

# mottori-kit

An **agent workspace engine** that preserves state and depth across endless sessions.
Claude Code and Codex run under the same rules, and work continues across compaction.

`git clone` → `bash setup.sh` → `bash tools/install_hooks.sh --repair` → `bash tools/install_hooks.sh --check` → `python3 tools/doctor.py`.
These five commands finish within one minute. `tools/test_fresh_install.sh` measures this exact sequence in a
temporary clone and passes as of 2026-09-17. Declaring your boundaries in `system/instance-rules.md` and
completing the human checks in CHECKLIST take as long as you need.

**Quick start.** Requires Python 3.8+, git 2.5+, Bash 3.2+, and macOS or Linux. `claude`, `codex`, and
`node` are optional. If the shell came from another mottori workspace, first run `unset MOTTORI_INSTANCE` or set
it to the new clone's absolute path. Run `bash setup.sh --name <name> --context personal|work`. A `work` context makes `doctor`
reject pushes to remotes outside the allowlist. Then run `bash tools/install_hooks.sh --repair`, followed by
`bash tools/install_hooks.sh --check` and `python3 tools/doctor.py`. `FAIL` must be zero. `warn` is acceptable, and `--` means not applicable. Replace every
`CHANGEME` in `system/instance-rules.md`. Nothing under `state/` or `_private/` is ever committed, so back it up
yourself. To update, run `git pull`, check the hooks again, refresh the gate baseline, and rerun `doctor`. See
SETUP.md section 5a. Before the first Claude or Codex session, `python3 tools/recall.py sessions` should succeed
with no output.

---

## What it solves

Endless sessions fail in two different ways, with different causes.

**State loss.** An old snapshot poses as the source of truth. Measurement: a note dated 8/8 still posed as the
current state on 8/15, and a person had to correct it manually.
→ State lives on **disk**, not in the conversation. Declared public tracks go to `state/journal-*.md` and
`state/NOW.md`. Undeclared events and events logged with `--private` go to the local journal and overlay under
`_private/state/`. The SessionStart hook merges both NOW files and injects the result. A clone with no local data
reports that state as `unavailable`.

**Depth loss.** Compaction summarizes the *current task* to preserve continuity. It therefore flattens the
reasoning in other threads. When you return to a conclusion from several days ago, the discussion starts over at
a shallow level.
→ Give each thread one **dossier**. It has five fields: position, decisions plus reasons, rejected options plus
reasons, open questions, and next move. Read the dossier before returning to a thread. Append a five-line delta
before leaving it.

Some information was not lost. It was simply **not searched**. Full conversation transcripts remain under
`~/.claude/projects/`. In the original instance for this repository, one session occupied 523 MB. `recall.py`
searches them with grep.

## Layout

```text
tools/           Engine. The core four are memlib, now, recall, and rec
  memlib.py      Schema source of truth. All other tools import it
  now.py         Journal append, NOW rendering, drift checks, and hook entry point
  recall.py      Targeted transcript search across Claude JSONL and Codex rollouts
  rec.py         Personal fact ledger with atomic notes and an audit chain
  fresh_worker.py Isolates broad work in a fresh, ephemeral run and returns only a bounded receipt
  receipts.py    One-line worker-run ledger, detailed replay, and token-cost histogram
  ask_codex.sh   Codex entry point. Its default fresh path delegates to fresh_worker
  doctor.py      Installation verifier with 37 checks, 4 human checks, and `--json` output
  test_fresh_install.sh Reproduces a first install in a temporary clone
system/          Rules, two PRDs, rituals, 13 lenses, deep-pass, and WORKING-WITH-AI
  skills/        Runtime-neutral canonical workflows; tools/skill_adapters.py generates and checks adapters
.claude/         Five Claude hooks and five slash commands
.codex/          Two Codex hooks: SessionStart and PreCompact
templates/       Files each instance must complete
```

## Philosophy in one sentence

<!-- language:evidence-ko -->
> "인간의 인지비용을 가장 비싼 자원으로, 토큰을 가장 낮은 비용 자원으로 두고 트레이드오프한다. 하나의 무한 스레드 아래에서 여러 작업이 굴러가도 견디게 해서 사람이 하나만 상대하게 한다." (Treat human cognitive cost as the most expensive resource and tokens as the cheapest, and make that tradeoff. Let multiple tasks run resiliently beneath one endless thread so the person deals with only one.)

**Human attention is the most expensive resource; tokens are the cheapest.** The kit makes that trade for you.
You face one endless thread. Many tasks run in parallel beneath it and survive interruptions. What comes back is
a receipt, not a transcript. (Owner decision, 2026-09-17, KIT-DR-012)

Two rules keep that trade safe. **Judge only from receipts.** The result of independent verification purchased
with tokens must return in one line, so a person does not need to read the transcript. **Verify passage and cause
separately.** A gate reports only whether the work passed. An independent review checks why it failed.
2026-09-17 measurement: on the day the installation gate produced PASS, an independent audit corrected two of
the dispatcher's causal hypotheses.

## Four design principles

**State lives on disk.** Everything that must persist becomes a file. Tools recalculate what remains from those
files. Without this, work cannot survive one session. With it, sessions can continue indefinitely.

**Generated views and ledgers are separate.** Do not edit `NOW.md`, `hotset.md`, or `memory-map.html` by hand.
Change the ledger, then regenerate the view. This prevents the picture and the implementation from diverging.

**Every rule has a Why.** Prefer measured incidents from this workspace, such as journal and run paths. Do not
copy whole rules from papers or other harnesses (`2609.09134`). A rule without a reason is a candidate for
deletion. Context files grow without limit because reasons decay before instructions do.

**There are seven always-on rules.** The number of instructions followed at once reaches a limit around k=5 to
6. Adding more makes each rule less reliable. Everything else goes into conditionally loaded documents.

## No data is included

This repository tracks only the engine. `.gitignore` blocks `state/`, `_private/`, and
`system/memory-config.json` from the beginning. This is structural, not a matter of discipline. Git cannot see
the files, so it cannot push them by accident.

This also means that **this repository does not back up instance data**. Arrange a separate backup.

## What is not included

- **Three recording watchers** (`watch_recordings`, `ingest_recording`, and `recording_watchd`). They are personal
  device adapters with account paths embedded in them. Only the transcription engine, `transcribe.py` and
  `diarize.py`, is included. On a work machine, meeting recording is a consent and retention-policy issue, not a
  feature issue. Do not run these tools before checking policy.
- **A checksum ledger for frozen areas.** This is instance-specific data. To use the pattern, run
  `shasum -a 256 <area>/** > integrity.sha256`, then verify it with `shasum -c`. Keep the ledger **outside** the
  frozen area.
- **Past decision records, debate rounds, and person ledgers.** These all belong to the history of the original
  instance.

## Start

Requirements: Python 3.8 or later, git 2.5 or later, Bash 3.2 or later, and macOS or Linux. `claude`, `codex`, and `node` are
optional.

```bash
git clone <this-repository> ~/work
cd ~/work
bash setup.sh --name work --context work     # With no arguments it prompts. Without a tty it uses defaults
bash tools/install_hooks.sh --repair         # Pre-commit backstop. .git/hooks is not cloned
bash tools/install_hooks.sh --check          # Verify both installed hooks match their templates
python3 tools/doctor.py                      # Complete when FAIL is 0. warn can be normal. -- means not applicable
```

Use `--context personal` on a personal machine. A `work` context makes `doctor` reject push-capable remotes that
are outside the allowlist. Replace every `CHANGEME` in `system/instance-rules.md`. Nothing under `state/` or
`_private/` is committed, so back it up yourself.

See `SETUP.md` for the full procedure. See `CHECKLIST.md` for human checks after installation. For updates,
see `SETUP.md` section 5a.

## Normative evidence

The installation commands and backup warning are grounded respectively in the unfamiliar-clone reproduction in
`tools/test_fresh_install.sh`, the default-deny list in `.gitignore`, and KIT-DR-002 and KIT-DR-011. The commands
preserve the reproduced installation order. The backup warning states the other side of the same structure:
blocking tracking also blocks backup. Fixed counts and timings are measurements at the cited test or inventory,
not permanent performance guarantees.
