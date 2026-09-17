#!/usr/bin/env python3
"""근거 표지의 문법, 로컬 대상, 필수 배치를 검사한다."""

import argparse
import ast
import os
import re
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ("system/kit-decisions.md", "CHANGELOG.md", "system/enforcement-matrix.md")
MARKER_START = re.compile(r"(?<![A-Za-z0-9_-])(paper|experiment|run|decision|test):")
PAYLOAD = {
    "paper": re.compile(
        r"(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?"
        r"|10\.\d{4,9}/[-._;()/:A-Za-z0-9]+"
    ),
    "experiment": re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"),
    "run": re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}"),
    "decision": re.compile(r"(?:KIT-)?DR-\d{3}"),
    "test": re.compile(r"tools/test_[A-Za-z0-9_]+\.py::[A-Za-z_][A-Za-z0-9_]*"),
}


def _args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", default=ROOT, help="검사할 트리 (기본: 도구가 속한 루트)")
    parser.add_argument("--local-root", help="run과 인스턴스 DR을 찾을 로컬 루트")
    parser.add_argument("--issues", action="store_true", help="게이트용 안정 이슈 집합")
    return parser.parse_args()


def _markers(text):
    """(namespace, payload, line) 표지를 원문 순서로 낸다."""
    for match in MARKER_START.finditer(text):
        end = match.end()
        token = re.match(r"[^\s`<>]+", text[end:])
        payload = token.group(0) if token else ""
        payload = payload.rstrip(".,;!?")
        line = text.count("\n", 0, match.start()) + 1
        yield match.group(1), payload, line


def _decision_exists(marker, tree, local_root):
    if marker.startswith("KIT-"):
        rel = os.path.join("system", "kit-decisions.md")
        decision = marker[len("KIT-"):]
        root = tree
    else:
        rel = os.path.join("system", "decisions.md")
        decision = marker
        root = local_root
    try:
        text = open(os.path.join(root, rel), encoding="utf-8").read()
    except OSError:
        return False
    return re.search(rf"^###\s+{re.escape(decision)}\b", text, re.M) is not None


def _test_exists(marker, tree):
    rel, name = marker.split("::", 1)
    try:
        source = open(os.path.join(tree, rel), encoding="utf-8").read()
        module = ast.parse(source)
    except (OSError, SyntaxError, UnicodeError):
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        for node in ast.walk(module)
    )


def _local_exists(namespace, payload, tree, local_root):
    """Return True/False for local IDs and None for external unresolved IDs."""
    if namespace == "decision":
        return _decision_exists(payload, tree, local_root)
    if namespace == "test":
        return _test_exists(payload, tree)
    if namespace == "run":
        return os.path.isdir(os.path.join(local_root, "_private", "work", "runs", payload))
    return None


def _has_valid_marker(text, tree, local_root, namespace=None):
    return any(
        (namespace is None or kind == namespace)
        and PAYLOAD[kind].fullmatch(payload)
        and _local_exists(kind, payload, tree, local_root) is not False
        for kind, payload, _ in _markers(text)
    )


def _required_issues(rel, text, tree, local_root):
    issues = {}
    if rel == "system/kit-decisions.md":
        starts = list(re.finditer(r"^###\s+(DR-\d{3})\b", text, re.M))
        stop_labels = (
            "결정:", "기각 대안:", "부수 결정:", "검증:", "안전성·마이그레이션:",
            "경계:", "재검토:", "참조:", "후보였던 문장들:",
        )
        for idx, start in enumerate(starts):
            end = starts[idx + 1].start() if idx + 1 < len(starts) else len(text)
            lines = text[start.end():end].splitlines()
            context = []
            collecting = False
            for line in lines:
                if line.startswith("맥락:"):
                    collecting = True
                    context.append(line)
                    continue
                if collecting and line.startswith(stop_labels):
                    break
                if collecting:
                    context.append(line)
            context_text = "\n".join(context)
            explicit_none = re.search(
                r"(?<![A-Za-z0-9_-])evidence:\s*none\b", context_text
            ) is not None
            if not explicit_none and not _has_valid_marker(context_text, tree, local_root):
                decision = start.group(1)
                issue_id = f"required|kit-decisions|{decision}"
                issues[issue_id] = f"필수 근거 표지 없음 {rel} {decision} 맥락 절"

    elif rel == "CHANGELOG.md":
        starts = list(re.finditer(r"^###\s+(.+)$", text, re.M))
        for idx, start in enumerate(starts):
            heading = start.group(1).strip().replace("`", "")
            # v0.8 English canonical headings use [Required] / [Note]; the Korean pair keeps [해야 함] / [알아둘 것].
            if not any(tag in heading for tag in ("[해야 함]", "[알아둘 것]", "[Required]", "[Action required]", "[Note]")):
                continue
            end_candidates = [len(text)]
            next_h3 = starts[idx + 1].start() if idx + 1 < len(starts) else len(text)
            end_candidates.append(next_h3)
            next_h2 = re.search(r"^##\s+", text[start.end():], re.M)
            if next_h2:
                end_candidates.append(start.end() + next_h2.start())
            section = text[start.end():min(end_candidates)]
            exempt = re.search(r"(?<![A-Za-z0-9_-])evidence:\s*none\b", section) is not None
            if not exempt and not _has_valid_marker(section, tree, local_root):
                issue_id = f"required|CHANGELOG.md|{heading}"
                issues[issue_id] = f"필수 근거 표지 없음 CHANGELOG.md {heading}"

    elif rel == "system/enforcement-matrix.md":
        for line in text.splitlines():
            if "|" not in line:
                continue
            cells = [cell.strip().replace("`", "") for cell in line.strip().strip("|").split("|")]
            if "ENFORCED" not in cells:
                continue
            key = cells[0] if cells else "unknown"
            if not _has_valid_marker(line, tree, local_root, namespace="test"):
                issue_id = f"required|enforcement-matrix|{key}"
                issues[issue_id] = f"필수 test 표지 없음 {rel} ENFORCED 행 {key}"
    return issues


def applicable(tree):
    """대상 파일이 하나도 없는 트리(설치된 인스턴스 등)는 검사 대상이 아니다.
    하나라도 있으면 나머지 부재는 missing-file 이슈다 (킷 안에서의 삭제는 fail-close)."""
    return any(os.path.isfile(os.path.join(tree, rel)) for rel in TARGETS)


def check(tree, local_root=None):
    local_root = os.path.abspath(local_root or tree)
    issues = {}
    reviews = {}
    marker_count = 0
    if not applicable(tree):
        return [], [], 0
    for rel in TARGETS:
        path = os.path.join(tree, rel)
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            issue_id = f"missing-file|{rel}"
            issues[issue_id] = f"검사 대상 파일 없음 {rel}"
            continue
        for namespace, payload, line in _markers(text):
            marker_count += 1
            if not PAYLOAD[namespace].fullmatch(payload):
                marker = f"{namespace}:{payload}"
                issue_id = f"syntax|{rel}|{marker}"
                issues[issue_id] = f"표지 문법 위반 {rel}:{line} {marker}"
                continue
            marker = f"{namespace}:{payload}"
            exists = _local_exists(namespace, payload, tree, local_root)
            if exists is False:
                issue_id = f"missing-local|{rel}|{marker}"
                issues[issue_id] = f"로컬 ID 없음 {rel}:{line} {marker}"
            elif exists is None:
                review_id = f"~review|{rel}|{marker}"
                reviews[review_id] = f"REVIEW 외부 존재 미판정 {rel}:{line} {marker}"
        issues.update(_required_issues(rel, text, tree, local_root))
    return sorted(issues.items()), sorted(reviews.items()), marker_count


def main():
    args = _args()
    tree = os.path.abspath(args.tree)
    issues, reviews, marker_count = check(tree, args.local_root)
    if args.issues:
        for issue_id, display in issues:
            print(f"{issue_id}\t{display}")
        for review_id, display in reviews:
            print(f"{review_id}\t{display}")
        print(f"#issues {len(issues)}")
        return 0
    if not applicable(tree):
        print(f"[evidencecheck] not applicable: none of {', '.join(TARGETS)} in this tree")
    print(f"[evidencecheck] files={len(TARGETS)} markers={marker_count}")
    for _, display in reviews:
        print(display)
    for _, display in issues:
        print(f"ISSUE {display}")
    print(f"[evidencecheck] issues: {len(issues)}")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
