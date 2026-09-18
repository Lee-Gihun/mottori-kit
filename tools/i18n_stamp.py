#!/usr/bin/env python3
"""Bind each translated Markdown file to its source content hash."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PENDING_PATH = "system/language-pending.txt"
STAMP_RE = re.compile(
    r"<!-- source: (?P<source>[^ ]+) sha256:(?P<digest>[0-9a-f]{64}) "
    r"source-of-truth: (?P<direction>ko|en) -->"
)
KO_SOURCE_FILES = {
    "system/PRD-info-architecture.md",
    "system/PRD-session-memory.md",
    "system/WORKING-WITH-AI.md",
    "system/deep-pass.md",
    "system/person-ledger.md",
}
EXCLUDED_PREFIXES = (".git/", "_private/", "state/", "system/debate/_")
INSTANCE_FILES = {
    "system/decisions.md",
    "system/decisions.ko.md",
    "system/instance-rules.md",
    "system/instance-rules.ko.md",
    "system/rituals.local.md",
    "system/rituals.local.ko.md",
}
PAIR_INVENTORY = {
    ".claude/commands/dossier.md": "completed",
    ".claude/commands/garden.md": "completed",
    ".claude/commands/now.md": "completed",
    ".claude/commands/paper-to-kit.md": "completed",
    ".claude/commands/recall.md": "completed",
    "AGENTS.md": "completed",
    "CHANGELOG.md": "completed",
    "CHECKLIST.md": "completed",
    "README.md": "completed",
    "SETUP.md": "completed",
    "system/PRD-info-architecture.md": "pending",
    "system/PRD-session-memory.md": "pending",
    "system/WORKING-WITH-AI.md": "pending",
    "system/deep-pass.md": "pending",
    "system/enforcement-matrix.md": "completed",
    "system/evidence-schema.md": "completed",
    "system/kit-decisions.md": "pending",
    "system/lenses/README.md": "pending",
    "system/lenses/ergodic.md": "pending",
    "system/lenses/feedback-loop.md": "pending",
    "system/lenses/fence.md": "pending",
    "system/lenses/feynman.md": "completed",
    "system/lenses/incentive.md": "pending",
    "system/lenses/inversion.md": "pending",
    "system/lenses/isomorphism.md": "pending",
    "system/lenses/jensen.md": "pending",
    "system/lenses/ledger.md": "pending",
    "system/lenses/limits.md": "pending",
    "system/lenses/marginal.md": "pending",
    "system/lenses/mirror.md": "pending",
    "system/lenses/silence.md": "pending",
    "system/person-ledger.md": "pending",
    "system/reviews/architecture.md": "pending",
    "system/rituals.md": "pending",
    "system/skills/paper-to-kit.md": "completed",
    "templates/decisions.md": "completed",
    "templates/instance-rules.md": "completed",
    "templates/rituals.local.md": "completed",
}
REQUIRED_LOCALE_PAIRS = set(PAIR_INVENTORY)


@dataclass(frozen=True)
class Pair:
    canonical: Path
    locale: Path
    source: Path
    target: Path
    direction: str
    state: str


@dataclass(frozen=True)
class Stale:
    target: str
    source: str | None
    message: str


@dataclass(frozen=True)
class Report:
    pairs: tuple[Pair, ...]
    stale: tuple[Stale, ...]
    pending: tuple[str, ...]


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"path is outside root: {path}") from error


def normalized_bytes(path: Path) -> bytes:
    """Normalize line-ending representation without changing Markdown whitespace."""
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8")


def content_hash(path: Path) -> str:
    return hashlib.sha256(normalized_bytes(path)).hexdigest()


def pending_paths(root: Path) -> tuple[tuple[str, ...], list[Stale]]:
    path = root / PENDING_PATH
    if not path.is_file():
        return (), [Stale(PENDING_PATH, None, f"{PENDING_PATH}: pending-file missing")]
    entries: list[str] = []
    stale: list[Stale] = []
    seen: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry in seen:
            stale.append(
                Stale(entry, None, f"{PENDING_PATH}:{number}: duplicate pending entry: {entry}")
            )
            continue
        seen.add(entry)
        entries.append(entry)
    return tuple(entries), stale


def is_korean_source(canonical_rel: str) -> bool:
    return canonical_rel in KO_SOURCE_FILES or canonical_rel.startswith("system/lenses/")


def make_pair(canonical: Path, locale: Path, root: Path, state: str = "completed") -> Pair:
    canonical_rel = relative(canonical, root)
    if is_korean_source(canonical_rel):
        return Pair(canonical, locale, locale, canonical, "ko", state)
    return Pair(canonical, locale, canonical, locale, "en", state)


def discover_pairs(
    root: Path, pending: set[str], required_pairs: set[str], pair_states: dict[str, str]
) -> tuple[list[Pair], list[Stale]]:
    pairs: list[Pair] = []
    stale: list[Stale] = []
    locale_paths = {
        locale
        for locale in root.rglob("*.ko.md")
        if relative(locale, root) not in INSTANCE_FILES
        and not relative(locale, root).startswith(EXCLUDED_PREFIXES)
    }
    canonical_paths = {root / rel for rel in required_pairs}
    canonical_paths.update(
        locale.with_name(locale.name[: -len(".ko.md")] + ".md") for locale in locale_paths
    )
    for canonical in sorted(canonical_paths):
        locale = canonical.with_name(canonical.stem + ".ko.md")
        locale_rel = relative(locale, root)
        canonical_rel = relative(canonical, root)
        state = pair_states.get(canonical_rel, "completed")
        pair = make_pair(canonical, locale, root, state)
        listed_pending = canonical_rel in pending or locale_rel in pending
        if state not in {"completed", "pending"}:
            stale.append(
                Stale(
                    relative(pair.target, root),
                    relative(pair.source, root),
                    f"{canonical_rel}: invalid pair inventory state: {state}",
                )
            )
            continue
        if state == "pending":
            if not listed_pending:
                stale.append(
                    Stale(
                        relative(pair.target, root),
                        relative(pair.source, root),
                        f"{canonical_rel}: inventory state is pending but pending entry is missing",
                    )
                )
            continue
        if listed_pending:
            target_rel = relative(pair.target, root)
            stale.append(
                Stale(
                    target_rel,
                    relative(pair.source, root),
                    f"{target_rel}: completed pair cannot be pending without an explicit inventory transition",
                )
            )
            continue
        if not pair.source.is_file():
            target_rel = relative(pair.target, root)
            stale.append(
                Stale(
                    target_rel,
                    relative(pair.source, root),
                    f"{target_rel}: source file missing: {relative(pair.source, root)}",
                )
            )
            continue
        if not pair.target.is_file():
            stale.append(
                Stale(
                    relative(pair.target, root),
                    relative(pair.source, root),
                    f"{relative(pair.target, root)}: translated file missing",
                )
            )
            continue
        pairs.append(pair)
    return pairs, stale


def expected_stamp(pair: Pair) -> str:
    return (
        f"<!-- source: {pair.source.name} sha256:{content_hash(pair.source)} "
        f"source-of-truth: {pair.direction} -->"
    )


def pair_stale(pair: Pair, root: Path) -> Stale | None:
    target_rel = relative(pair.target, root)
    source_rel = relative(pair.source, root)
    lines = pair.target.read_text(encoding="utf-8").splitlines()
    stamp_lines = [line for line in lines if STAMP_RE.fullmatch(line)]
    if not lines or STAMP_RE.fullmatch(lines[0]) is None:
        return Stale(target_rel, source_rel, f"{target_rel}: missing translation stamp")
    if len(stamp_lines) != 1:
        return Stale(target_rel, source_rel, f"{target_rel}: multiple translation stamps")
    stamp = STAMP_RE.fullmatch(lines[0])
    assert stamp is not None
    if stamp.group("source") != pair.source.name:
        return Stale(
            target_rel,
            source_rel,
            f"{target_rel}: stamp source is {stamp.group('source')}; expected {pair.source.name}",
        )
    if stamp.group("direction") != pair.direction:
        return Stale(
            target_rel,
            source_rel,
            f"{target_rel}: source-of-truth is {stamp.group('direction')}; expected {pair.direction}",
        )
    if stamp.group("digest") != content_hash(pair.source):
        return Stale(target_rel, source_rel, f"{target_rel}: source hash changed ({source_rel})")
    return None


def check(
    root: Path = ROOT,
    required_pairs: set[str] | None = None,
    pair_states: dict[str, str] | None = None,
) -> Report:
    root = root.resolve()
    pending, stale = pending_paths(root)
    required = REQUIRED_LOCALE_PAIRS if required_pairs is None else required_pairs
    states = PAIR_INVENTORY if pair_states is None else pair_states
    pairs, pair_discovery_stale = discover_pairs(root, set(pending), required, states)
    stale.extend(pair_discovery_stale)
    stale.extend(item for pair in pairs if (item := pair_stale(pair, root)) is not None)
    return Report(tuple(pairs), tuple(stale), pending)


def atomic_write(path: Path, content: str) -> None:
    mode = path.stat().st_mode
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def bind(target: Path, root: Path = ROOT) -> Pair:
    root = root.resolve()
    target = target if target.is_absolute() else root / target
    target = target.resolve()
    target_rel = relative(target, root)
    if not target.is_file():
        raise ValueError(f"translated file does not exist: {target_rel}")
    if target.name.endswith(".ko.md"):
        canonical = target.with_name(target.name[: -len(".ko.md")] + ".md")
        locale = target
    elif target.name.endswith(".md"):
        canonical = target
        locale = target.with_name(target.stem + ".ko.md")
    else:
        raise ValueError("bind target must be X.md or X.ko.md")
    pair = make_pair(canonical, locale, root)
    pending, pending_stale = pending_paths(root)
    if pending_stale:
        raise ValueError(pending_stale[0].message)
    canonical_rel = relative(canonical, root)
    if PAIR_INVENTORY.get(canonical_rel) == "pending":
        raise ValueError(
            f"cannot bind pending pair before inventory transition: {canonical_rel}"
        )
    if relative(canonical, root) in set(pending) or target_rel in set(pending):
        raise ValueError(f"cannot bind pending file: {target_rel}")
    if target != pair.target.resolve():
        raise ValueError(
            f"bind expects translated side {relative(pair.target, root)} for source-of-truth {pair.direction}"
        )
    if not pair.source.is_file():
        raise ValueError(f"source file does not exist: {relative(pair.source, root)}")
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if lines and (STAMP_RE.fullmatch(lines[0].rstrip("\r\n")) or lines[0].startswith("<!-- source: ")):
        text = "".join(lines[1:])
    atomic_write(target, expected_stamp(pair) + "\n" + text)
    return pair


def print_report(report: Report, root: Path, include_bound: bool) -> None:
    stale_targets = {item.target for item in report.stale}
    if include_bound:
        for pair in report.pairs:
            target = relative(pair.target, root)
            status = "STALE" if target in stale_targets else "BOUND"
            print(
                f"{status} {target} <- {relative(pair.source, root)} "
                f"(source-of-truth: {pair.direction})"
            )
    pair_targets = {relative(pair.target, root) for pair in report.pairs}
    for item in report.stale:
        if not include_bound or item.target not in pair_targets:
            print(f"STALE {item.message}")
    for pending in report.pending:
        print(f"PENDING {pending}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="report stale and pending translations")
    bind_parser = subparsers.add_parser("bind", help="bind a completed translation to its source")
    bind_parser.add_argument("target", type=Path, help="translated X.md or X.ko.md")
    subparsers.add_parser("list", help="list locale pairs, directions, and state")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "bind":
        try:
            pair = bind(args.target, root)
        except (OSError, UnicodeError, ValueError) as error:
            print(f"ERROR {error}")
            return 2
        print(
            f"BOUND {relative(pair.target, root)} <- {relative(pair.source, root)} "
            f"(source-of-truth: {pair.direction})"
        )
        return 0
    report = check(root)
    print_report(report, root, include_bound=args.command == "list")
    status = "PASS" if not report.stale else "FAIL"
    print(f"i18n stamps: {status} (stale {len(report.stale)}; pending {len(report.pending)})")
    return 1 if args.command == "check" and report.stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
