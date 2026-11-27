#!/usr/bin/env python3
"""Check relative file references in tracked Markdown.

Frozen and historical paths may be excluded through instance config. --all includes them. Inline Markdown links and code references are checked; fenced examples are not.
A Markdown link in a skill (system/skills/<name>/) that leaves the skill's folder is broken.

--session is the gate's session scope (the turn-end check, and an installed instance's commit
check): documents under the contributor folders are not read, and with --issues a
path-shaped code span that names a missing file is an advisory row (~ID), not a counted issue,
because prose may name a file that is still to be made.

--mine reads the owner's own folders instead: in a kit installation Git ignores them, so the
other runs do not read them (paths.owner_files). It records nothing.

Usage: python3 tools/linkcheck.py [--all] [--mine] [--issues] [--session] [--tree DIR] [--filelist FILE]"""
import collections, os, re, subprocess, sys, urllib.parse

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C
import paths as P
import runlog

# Said by a plain run in a kit installation, where Git lists none of the owner's own folders.
NOT_IN_THIS_RUN = (
    "[linkcheck] not in this run: {count} top-level names of your own, which Git ignores here. "
    "`python3 tools/linkcheck.py --mine` checks them; the turn-end check reads the Markdown a turn "
    "edits."
)

ROOT = P.instance_root()
# Contributor documents a running instance never reads; a check without --session still reads them.
CONTRIBUTOR_ONLY = ("system/dev/", "tools/dev/", "tools/tests/")

# Records of the past (the kit's and the instance's decision records) say what was true when each
# entry was written, so a file they name that has since moved or gone is not reported.
RECORDS = ("system/specs/kit-decisions.md", P.tracked_name(P.decisions))



def skill_folder(rel):
    """The skill folder (system/skills/<name>) a document lies in, or None. A link from a skill
    must stay inside its folder, because each runtime reads a copy of that folder alone."""
    parts = rel.split("/")
    prefix = P.tracked_name(P.skills).split("/")
    if len(parts) > len(prefix) + 1 and parts[:len(prefix)] == prefix:
        return "/".join(parts[:len(prefix) + 1])
    return None


# Configured frozen/historical prefixes may intentionally contain obsolete references.
def exclude_prefixes():
    """Frozen and archived areas whose old paths are not checked (checks.linkcheck_exclude_prefixes)."""
    return tuple(C.check_config("linkcheck_exclude_prefixes", []))

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# CommonMark angle-bracket destinations may contain spaces: [x](<a b/c.md#frag>).
LINK_ANGLE = re.compile(r"\[[^\]]*\]\(<([^>\n]+)>\)")
# An editor-style ":line" or ":line:col" suffix stays outside the captured path.
CODEREF = re.compile(r"`([A-Za-z0-9_\-./·]+\.(?:md|txt|tex|py|html|json|pdf|docx|sh))(?::\d+(?::\d+)?)?`")
# Code spans follow CommonMark within one line: a span opens on a backtick run that is not
# backslash-escaped and closes only on a run of the same length. Pairing single backticks would
# let a span such as ``a`b`` swallow a real link later on the line, and an escaped \` is literal
# text, so it must not open a span that hides a link a renderer draws.
_SPAN_OPENER = re.compile(r"\\.|`+")


def strip_inline_code(text):
    """Return text with inline code spans removed, line by line."""
    lines = []
    for line in text.split("\n"):
        kept, start, pos = [], 0, 0
        while True:
            m = _SPAN_OPENER.search(line, pos)
            if not m:
                break
            pos = m.end()
            if m.group().startswith("\\"):
                continue
            # Inside a span backslashes are literal, so the closing run is matched as is.
            close = re.compile(r"(?<!`)`{%d}(?!`)" % len(m.group())).search(line, pos)
            if close:
                kept.append(line[start:m.start()])
                start = pos = close.end()
        kept.append(line[start:])
        lines.append("".join(kept))
    return "\n".join(lines)


def tracked_md(filelist=None):
    """Return the Markdown to check: Git's list, with NUL delimiters and filesystem decoding, or
    an explicit file list, which is line-delimited and cannot represent newline-bearing names.
    """
    if filelist:
        return [l for l in open(filelist, encoding="utf-8").read().splitlines() if l.strip()]
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others",
                          "--exclude-standard", "*.md"], capture_output=True, check=True).stdout
    return [os.fsdecode(path) for path in out.split(b"\0") if path]

def scope_hash(paths, root):
    """Hash file names and bytes into the identity of one link check.

    doctor computes the same identity to decide whether a recorded check covered the
    current files, so both call this one function and stay byte-identical.
    """
    import hashlib
    digest = hashlib.sha1()
    # Exclude generated projections from the certificate identity because render timestamps change.
    # The link checker still reads them; only the identity used to certify a completed check excludes them.
    generated = tuple(P.tracked_name(lambda r, s=scope: P.now_page(s, r))
                      for scope in ("public", "private"))
    for name in sorted(path for path in paths if path not in generated):
        digest.update(os.fsencode(name))
        try:
            digest.update(open(os.path.join(root, name), "rb").read())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()[:12]


def is_real_path(t):
    # Ignore section anchors, line anchors such as L12 or L3-L9, abbreviations, and separator
    # notation. A bare leading L is not enough: LICENSE.md is a real file name.
    if t.startswith("§") and "/" not in t: return False
    if re.fullmatch(r"L\d+(-L?\d+)?", t): return False
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
SETUP_CREATED = frozenset(P.tracked_name(path_of) for path_of in (
    P.config_file, P.rules, P.rituals, P.decisions, P.gate_baseline, P.projects_readme,
    lambda root: P.now_page("public", root), lambda root: P.now_page("private", root)))


# These ignored instance destinations are created on first use, independently of setup.
OPTIONAL_DESTINATIONS = frozenset((
    P.tracked_name(P.deep_pass_ledger), P.tracked_name(P.debate) + "/_p_review.md",
    "_private/transcribe-prompts.json", ".claude/settings.local.json",
))


def _optional_target(cands, tree):
    """Recognize only declared destinations that Git confirms are ignored and untracked."""
    for candidate in cands:
        rel = os.path.normpath(os.path.relpath(os.path.abspath(candidate), tree))
        if rel in OPTIONAL_DESTINATIONS and _is_ignored(rel):
            return True
    return False


def _setup_done():
    return os.path.exists(P.config_file(ROOT))


def _pending_target(cands, tree):
    """Return whether an unconfigured tree references a file created by setup."""
    if _setup_done():
        return False
    for c in cands:
        rel = os.path.normpath(os.path.relpath(os.path.abspath(c), tree))
        if rel in SETUP_CREATED:
            return True
    return False


# What one run found. broken and code_only hold (document, target); code_only are the broken ones
# named only in a code span. pending targets are files setup creates, optional ones ignored
# destinations created on first use.
Result = collections.namedtuple("Result", "broken checked pending optional code_only")


def check(tree=ROOT, filelist=None, include_all=False, session=False):
    """Check the references in one tree's Markdown. tree is read for file contents, while the
    instance's exclusions and ignored local targets come from ROOT; session leaves out the
    contributor folders."""
    tree = os.path.abspath(tree)
    broken, checked, pending, optional, code_only = [], 0, [], [], set()
    for rel in tracked_md(filelist):
        if not include_all and (rel in RECORDS or rel.startswith(exclude_prefixes())):
            continue
        if session and rel.startswith(CONTRIBUTOR_ONLY):
            continue
        fp = os.path.join(tree, rel)
        # Git still lists a tracked file deleted without staging; that deletion is not a defect.
        # A file named in an explicit file list must exist, so it is reported below.
        if not filelist and not os.path.lexists(fp):
            continue
        try:
            text = strip_fences(open(fp, encoding="utf-8").read())
        except (OSError, UnicodeDecodeError):
            # An unreadable file has unchecked links, so it must fail the run rather than vanish.
            broken.append((rel, "<unreadable>"))
            continue
        base = os.path.dirname(fp)
        links, coderefs = set(), set()
        # Bracket syntax inside inline code, such as `x[0](y)`, is code rather than a link.
        prose = strip_inline_code(text)
        found = [m.group(1) for m in LINK_ANGLE.finditer(prose)]
        found += [m.group(1) for m in LINK.finditer(prose) if not m.group(1).startswith("<")]
        for t in found:
            if t.startswith(("http://", "https://", "mailto:", "#")): continue
            t = t.split("#")[0]
            if t and is_real_path(t): links.add(t)
        for m in CODEREF.finditer(text):
            t = m.group(1)
            if "/" in t and is_real_path(t): coderefs.add(t)
        parents = os.path.dirname(rel).split("/") if os.path.dirname(rel) else []
        own_folder = skill_folder(rel)
        for t in links | coderefs:
            t2 = urllib.parse.unquote(t)
            checked += 1
            # A Markdown link must resolve exactly as a renderer resolves it, from its document.
            # Prose names repository paths, so a code reference also tries the root.
            is_link = t in links
            if is_link and own_folder:
                inside = os.path.join(tree, own_folder)
                if os.path.commonpath([os.path.normpath(os.path.join(base, t2)), inside]) != inside:
                    broken.append((rel, t))
                    continue
            near = [os.path.join(base, t2)] + ([] if is_link else [os.path.join(tree, t2)])
            # Accept entries inside the tree, including symlink entries.
            cands = list(near)
            if not is_link:
                # Prose often names a path relative to an enclosing project folder rather than
                # to the document.
                cands += [os.path.join(tree, *parents[:i], t2) for i in range(len(parents) - 1, 0, -1)]
            if any(os.path.exists(c) or os.path.lexists(c) for c in cands):
                continue
            if _pending_target(near, tree):
                pending.append((rel, t))
                continue
            # Fallback to the live root only for ignored local data; tracked targets must exist in the staged tree.
            if tree != os.path.abspath(ROOT):
                # Normalize so a ../ link from a folder that exists only in the staged tree still resolves.
                rc = [os.path.normpath(c) for c in [os.path.join(ROOT, os.path.dirname(rel), t2)] + ([] if is_link else [os.path.join(ROOT, t2)])]
                hit = next((c for c in rc if os.path.exists(c) or os.path.lexists(c)), None)
                if hit and _is_ignored(os.path.relpath(hit, ROOT)):
                    continue
            if _optional_target(near, tree):
                optional.append((rel, t))
                continue
            broken.append((rel, t))
            if not is_link:
                code_only.add((rel, t))
    return Result(broken, checked, pending, optional, code_only)


def main(argv):
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0

    def option(name):
        return argv[argv.index(name) + 1] if name in argv[:-1] else None
    # --tree reads file contents from an extracted staged tree while retaining instance exclusions.
    tree = os.path.abspath(option("--tree") or ROOT)
    filelist = option("--filelist")
    include_all, session, mine = "--all" in argv, "--session" in argv, "--mine" in argv
    if mine:
        # The owner's Markdown written to a list, read through the same path as an explicit file list.
        import tempfile
        names = [rel for rel in P.owner_files(ROOT) if rel.lower().endswith(".md")]
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as listing:
            listing.write("".join(name + "\n" for name in names))
        try:
            found = check(tree, listing.name, include_all, session)
        finally:
            os.unlink(listing.name)
        filelist = listing.name
    else:
        found = check(tree, filelist, include_all, session)
    broken = found.broken

    if "--issues" in argv:
        # Emit stable source-and-target IDs so the gate detects replacement issues, not only count changes. The final trailer certifies measurement; findings still exit zero.
        advisory = found.code_only if session else set()
        for rel, target in sorted(broken):
            mark = "~" if (rel, target) in advisory else ""
            print(f"{mark}{rel} -> {target}\t" + f"broken reference {rel} -> {target}")
        print(f"#issues {len(broken) - len(advisory)}")
        return 0

    scope = ("your own folders" if mine else
             "ALL (including frozen)" if include_all else "live documents (frozen excluded)")
    print(f"[linkcheck] scope={scope}, refs={found.checked}")
    ignored = P.owner_names(ROOT) if tree == os.path.abspath(ROOT) and not filelist and not mine else []
    if ignored:
        print(NOT_IN_THIS_RUN.format(count=len(ignored)))
    for rel, target in sorted(broken):
        print(f"BROKEN {rel} -> {target}")
    for rel, target in sorted(found.pending):
        print(f"PENDING {rel} -> {target}  (created by setup.sh; upstream copy before setup)")
    # Files the kit creates on first use are the kit's business: listed only with --all.
    for rel, target in sorted(found.optional) if include_all else ():
        print(f"OPTIONAL {rel} -> {target}  (ignored instance destination; created on first use)")
    extra = f" · pending(before setup): {len(found.pending)}" if found.pending else ""
    if found.optional and include_all:
        print(f"[linkcheck] optional(first use): {len(found.optional)}")
    print(f"[linkcheck] broken: {len(broken)}" + extra)
    # Record the exact input-file bytes that this checker read. The identity hashes the live
    # files, so a run that read a staged tree or an explicit file list certifies nothing.
    if tree == os.path.abspath(ROOT) and not filelist:
        runlog.log_run("linkcheck", f"broken={len(broken)}", scope=scope_hash(tracked_md(), ROOT),
                  ok=(len(broken) == 0))
    # Normal mode fails on broken references; --issues mode reports measurement success separately.
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
