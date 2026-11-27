#!/usr/bin/env python3
"""Check the evidence markers of the kit's decision records, change log, rules table and model page.

A marker is well formed, and what it names exists in this tree: a decision record, a test
function, a run folder. A paper or experiment marker is checked for form only. Each decision
record's context, and each CHANGELOG item marked [Action required] or [Note], carries at least one
valid marker or `evidence: none`. The contract is system/dev/evidence-schema.md.

Usage: python3 tools/dev/evidencecheck.py [--tree DIR]
Prints one line per problem and exits 1 when there is one; prints nothing and exits 0 otherwise,
and also when the tree holds none of the checked files.
"""

import argparse
import ast
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths as P  # noqa: E402

ROOT = os.path.dirname(TOOLS)
TARGETS = ("system/specs/kit-decisions.md", "CHANGELOG.md", "system/dev/enforcement.md",
           "system/specs/model-assumptions.md")
MARKER_START = re.compile(r"(?<![A-Za-z0-9_-])(paper|experiment|run|decision|test):")
PAYLOAD = {
    "paper": re.compile(
        r"(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?"
        r"|10\.\d{4,9}/[-._;()/:A-Za-z0-9]+"
    ),
    "experiment": re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"),
    "run": re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}"),
    "decision": re.compile(r"(?:KIT-)?DR-\d{3}"),
    "test": re.compile(r"tools/tests/test_[A-Za-z0-9_]+\.py::[A-Za-z_][A-Za-z0-9_]*"),
}
EXEMPT = re.compile(r"(?<![A-Za-z0-9_-])evidence:\s*none\b")
# CHANGELOG headings whose item must carry a marker.
CHANGELOG_TAGS = ("[Action required]", "[Note]")
# Labels that end a decision record's context section.
SECTION_LABELS = (
    "Decision:", "Alternatives:", "Rejected alternatives:", "Verification:",
    "Safety and migration:", "Boundary:", "Reconsider:", "References:",
    "Side decisions:", "Candidate sentences:",
)


def markers(text):
    """Yield (namespace, payload, line) for each marker in source order."""
    for match in MARKER_START.finditer(text):
        # Without a payload right after the colon this is prose ("Verification test: run").
        token = re.match(r"[^\s`<>]+", text[match.end():])
        if not token:
            continue
        payload = token.group(0).rstrip(".,;!?")
        # A marker inside parentheses or a Markdown link carries the closing bracket; strip only
        # unbalanced ones so a DOI with balanced parentheses keeps its own.
        for opening, closing in (("(", ")"), ("[", "]")):
            while payload.endswith(closing) and payload.count(closing) > payload.count(opening):
                payload = payload[:-1].rstrip(".,;!?")
        yield match.group(1), payload, text.count("\n", 0, match.start()) + 1


def _decision_exists(marker, tree):
    rel = os.path.join("system", "specs", "kit-decisions.md") if marker.startswith("KIT-") \
        else P.tracked_name(P.decisions)
    try:
        text = open(os.path.join(tree, rel), encoding="utf-8").read()
    except OSError:
        return False
    return re.search(rf"^###\s+{re.escape(marker.replace('KIT-', '', 1))}\b", text, re.M) is not None


def _test_exists(marker, tree):
    rel, name = marker.split("::", 1)
    try:
        module = ast.parse(open(os.path.join(tree, rel), encoding="utf-8").read())
    except (OSError, SyntaxError, UnicodeError):
        return False
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
               for node in ast.walk(module))


def problem(namespace, payload, tree):
    """Return what is wrong with one marker, or None."""
    if not PAYLOAD[namespace].fullmatch(payload):
        return "malformed"
    exists = {"decision": _decision_exists, "test": _test_exists,
              "run": lambda run, root: os.path.isdir(os.path.join(P.runs(root), run))}.get(namespace)
    if exists and not exists(payload, tree):
        return "names nothing in this tree"
    return None


def _valid(text, tree):
    return any(problem(kind, payload, tree) is None for kind, payload, _ in markers(text))


def _sections(rel, text):
    """Yield (name, text) for each part of a file that must carry a marker."""
    if rel == "system/specs/kit-decisions.md":
        starts = list(re.finditer(r"^###\s+(DR-\d{3})\b", text, re.M))
        for index, start in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
            context, collecting = [], False
            for line in text[start.end():end].splitlines():
                if line.startswith(("Context:", "Reason:")):
                    collecting = True
                elif collecting and line.startswith(SECTION_LABELS):
                    break
                if collecting:
                    context.append(line)
            yield f"KIT-{start.group(1)} context", "\n".join(context)
    elif rel == "CHANGELOG.md":
        starts = list(re.finditer(r"^###\s+(.+)$", text, re.M))
        for index, start in enumerate(starts):
            heading = start.group(1).strip().replace("`", "")
            if not any(tag in heading for tag in CHANGELOG_TAGS):
                continue
            end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
            next_h2 = re.search(r"^##\s+", text[start.end():end], re.M)
            yield heading, text[start.end():start.end() + next_h2.start() if next_h2 else end]


def check(tree):
    """Return the problem lines of a tree, empty when there is none."""
    if not any(os.path.isfile(os.path.join(tree, rel)) for rel in TARGETS):
        return []
    found = []
    for rel in TARGETS:
        try:
            text = open(os.path.join(tree, rel), encoding="utf-8").read()
        except OSError:
            found.append(f"{rel}: missing")
            continue
        for namespace, payload, line in markers(text):
            wrong = problem(namespace, payload, tree)
            if wrong:
                found.append(f"{rel}:{line}: {namespace}:{payload} {wrong}")
        for name, section in _sections(rel, text):
            if not EXEMPT.search(section) and not _valid(section, tree):
                found.append(f"{rel}: {name} has no valid marker and no `evidence: none`")
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--tree", default=ROOT, help="the tree to check (default: this tool's own)")
    found = check(os.path.abspath(parser.parse_args(argv).tree))
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
