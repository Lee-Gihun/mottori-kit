#!/usr/bin/env python3
"""Check relative file references in tracked Markdown.

Frozen and historical paths may be excluded through instance config. --all includes them. Inline Markdown links and code references are checked; fenced examples are not.

Usage: python3 tools/linkcheck.py [--all]"""
import os, re, subprocess, sys, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memlib as M
from i18n import t

ROOT = M.ROOT
INCLUDE_ALL = "--all" in sys.argv

# --tree reads file contents from an extracted staged tree while retaining instance exclusions.
def _opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv[:-1] else default

TREE = os.path.abspath(_opt("--tree", ROOT))
FILELIST = _opt("--filelist")          # An explicit file list replaces Git discovery.

# Configured frozen/historical prefixes may intentionally contain obsolete references.
EXCLUDE_PREFIXES = tuple(M.check_config("linkcheck_exclude_prefixes", []))

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODEREF = re.compile(r"`([A-Za-z0-9_\-./·]+\.(?:md|txt|tex|py|html|json|pdf|docx|sh))`")

def tracked_md():
    """Preserve Git filenames with NUL delimiters and filesystem decoding.

    Explicit --filelist remains line-delimited and cannot represent newline-bearing names.
    """
    if FILELIST:
        return [l for l in open(FILELIST, encoding="utf-8").read().splitlines() if l.strip()]
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others",
                          "--exclude-standard", "*.md"], capture_output=True, check=True).stdout
    return [os.fsdecode(path) for path in out.split(b"\0") if path]

def is_real_path(t):
    # Ignore section anchors, line suffixes, abbreviations, and separator notation.
    if t.startswith(("§", "L")) and not "/" in t: return False
    if "..." in t or "·" in t: return False
    return True

def strip_fences(text):
    """Remove fenced examples, including indented fences inside lists. Example commands and deliberately invalid paths are not document references."""
    return re.sub(r"^[ \t]*```.*?^[ \t]*```", "", text, flags=re.S | re.M)


_IGN_CACHE = {}

def _is_ignored(rel):
    """Cache whether Git proves that this path is ignored."""
    if rel not in _IGN_CACHE:
        r = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", "--", rel],
                           capture_output=True)
        _IGN_CACHE[rel] = (r.returncode == 0)
    return _IGN_CACHE[rel]


# Setup-created instance files may be absent only before setup. Once configured, missing files are broken references.
SETUP_CREATED = frozenset((
    "system/memory-config.json", "system/instance-rules.md", "system/rituals.local.md",
    "system/decisions.md", "state/NOW.md", "_private/state/NOW.md", "state/.gate-baseline.json",
    "_private/transcribe-prompts.json",
))


# These ignored instance destinations are created on first use, independently of setup.
OPTIONAL_DESTINATIONS = frozenset((
    "_private/deep-pass/ledger.md", "system/debate/_p_review.md",
))


def _optional_target(base, t2):
    """Recognize only declared destinations that Git confirms are ignored and untracked."""
    for candidate in (os.path.join(base, t2), os.path.join(TREE, t2)):
        rel = os.path.normpath(os.path.relpath(os.path.abspath(candidate), TREE))
        if rel in OPTIONAL_DESTINATIONS and _is_ignored(rel):
            return True
    return False


def _setup_done():
    return os.path.exists(os.path.join(ROOT, "system", "memory-config.json"))


def _pending_target(base, t2):
    """Return whether an unconfigured tree references a file created by setup."""
    if _setup_done():
        return False
    for c in (os.path.join(base, t2), os.path.join(TREE, t2)):
        rel = os.path.normpath(os.path.relpath(os.path.abspath(c), TREE))
        if rel in SETUP_CREATED:
            return True
    return False


def check():
    broken, checked = [], 0
    check.pending = []
    check.optional = []
    for rel in tracked_md():
        if not INCLUDE_ALL and rel.startswith(EXCLUDE_PREFIXES):
            continue
        fp = os.path.join(TREE, rel)
        try:
            text = strip_fences(open(fp, encoding="utf-8").read())
        except Exception:
            continue
        base = os.path.dirname(fp)
        targets = set()
        for m in LINK.finditer(text):
            t = m.group(1)
            if t.startswith(("http://", "https://", "mailto:", "#")): continue
            t = t.split("#")[0]
            if t and is_real_path(t): targets.add(t)
        for m in CODEREF.finditer(text):
            t = m.group(1)
            if "/" in t and is_real_path(t): targets.add(t)
        for t in targets:
            t2 = urllib.parse.unquote(t)
            checked += 1
            # Accept entries inside TREE, including symlink entries.
            cands = [os.path.join(base, t2), os.path.join(TREE, t2)]
            if any(os.path.exists(c) or os.path.lexists(c) for c in cands):
                continue
            if _pending_target(base, t2):
                check.pending.append((rel, t))
                continue
            # Fallback to the live root only for ignored local data; tracked targets must exist in the staged tree.
            if TREE != ROOT:
                rc = [os.path.join(ROOT, os.path.dirname(rel), t2), os.path.join(ROOT, t2)]
                hit = next((c for c in rc if os.path.exists(c) or os.path.lexists(c)), None)
                if hit and _is_ignored(os.path.relpath(hit, ROOT)):
                    continue
            if _optional_target(base, t2):
                check.optional.append((rel, t))
                continue
            broken.append((rel, t))
    return broken, checked

if __name__ == "__main__":
    broken, checked = check()

    if "--issues" in sys.argv:
        # Emit stable source-and-target IDs so the gate detects replacement issues, not only count changes. The final trailer certifies measurement; findings still exit zero.
        for rel, target in sorted(broken):
            print(f"{rel} -> {target}\t" + t("linkcheck.issue", rel=rel, target=target))
        print(f"#issues {len(broken)}")
        sys.exit(0)

    scope = t("linkcheck.scope_all") if INCLUDE_ALL else t("linkcheck.scope_live")
    print(t("linkcheck.scope", scope=scope, count=checked))
    for rel, target in sorted(broken):
        print(t("linkcheck.broken", rel=rel, target=target))
    pending = getattr(check, "pending", [])
    for rel, target in sorted(pending):
        print(t("linkcheck.pending", rel=rel, target=target))
    optional = getattr(check, "optional", [])
    for rel, target in sorted(optional):
        print(t("linkcheck.optional", rel=rel, target=target))
    extra = t("linkcheck.pending_count", count=len(pending)) if pending else ""
    if optional:
        print(t("linkcheck.optional_count", count=len(optional)))
    print(t("linkcheck.summary", count=len(broken)) + extra)
    # Record the exact input-file bytes that this checker read.
    import hashlib as _h
    _d = _h.sha1()
    # Exclude generated projections from the certificate identity because render timestamps change.
    # The link checker still reads them; only the identity used to certify a completed check excludes them.
    _GEN = ("state/NOW.md", "_private/state/NOW.md")
    for _f in sorted(x for x in tracked_md() if x not in _GEN):
        _d.update(os.fsencode(_f))
        try:
            _d.update(open(os.path.join(ROOT, _f), "rb").read())
        except OSError:
            _d.update(b"<missing>")
    M.log_run("linkcheck", f"broken={len(broken)}", scope=_d.hexdigest()[:12],
              ok=(len(broken) == 0))
    # Normal mode fails on broken references; --issues mode reports measurement success separately.
    sys.exit(1 if broken else 0)
