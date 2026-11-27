#!/usr/bin/env python3
"""Regression tests for the memory-index audit (memory_index.py), run through now.py check."""
import contextlib
import io
import os
import sys
import tempfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import now  # noqa: E402


def issues(files, index):
    with tempfile.TemporaryDirectory() as d:
        for name, text in files.items():
            open(os.path.join(d, name), 'w', encoding='utf-8').write(text)
        open(os.path.join(d, 'MEMORY.md'), 'w', encoding='utf-8').write(index)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                now.check(memory_dir=d, root=d, issues=True)
            except SystemExit:
                pass
    return out.getvalue()


def test_direct_index_ok():
    s = issues({'a.md': 'x'}, '- [A](a.md) — a')
    assert 'index-missing:a.md' not in s, s


def test_missing_flagged():
    s = issues({'a.md': 'x', 'b.md': 'y'}, '- [A](a.md) — a')
    assert 'index-missing:b.md' in s, s


def test_subindex_counts_one_hop():
    s = issues({'a.md': 'x', 'b.md': 'y', 'topic-index.md': '- [B](b.md)'}, '- [A](a.md)\n- [T](topic-index.md)')
    assert 'index-missing:b.md' not in s, s


def test_subindex_not_linked_does_not_count():
    s = issues({'b.md': 'y', 'topic-index.md': '- [B](b.md)'}, '- (nothing)')
    assert 'index-missing:b.md' in s and 'index-missing:topic-index.md' in s, s


def test_two_hops_do_not_count():
    s = issues({'c.md': 'z', 'deep-index.md': '- [C](c.md)', 'topic-index.md': '- [D](deep-index.md)'},
               '- [T](topic-index.md)')
    assert 'index-missing:c.md' in s, s


def test_non_index_file_links_do_not_count():
    s = issues({'a.md': '- [B](b.md)', 'b.md': 'y'}, '- [A](a.md)')
    assert 'index-missing:b.md' in s, s


def test_ghost_from_subindex_names_source():
    s = issues({'topic-index.md': '- [Z](zz.md)'}, '- [T](topic-index.md)')
    assert 'index-ghost:zz.md' in s and 'topic-index.md' in s, s


def test_unreadable_subindex_does_not_crash():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, 'MEMORY.md'), 'w', encoding='utf-8').write('- [T](bad-index.md)')
        open(os.path.join(d, 'bad-index.md'), 'wb').write(b'\xff\xfe\x00bad')
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                now.check(memory_dir=d, root=d, issues=True)
            except SystemExit:
                pass
    assert 'subindex-unreadable:bad-index.md' in out.getvalue(), out.getvalue()
    # A stray byte in the index or late in a project memory file does not crash the check.
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, 'MEMORY.md'), 'wb').write(b'- [P](p.md) \xff\n')
        open(os.path.join(d, 'p.md'), 'wb').write(b'type: project\n' + b'x' * 500 + b'\xff\n')
        os.utime(os.path.join(d, 'p.md'), (0, 0))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            now.check(memory_dir=d, root=d, issues=True)
        assert 'memory-rot:p.md' in out.getvalue(), out.getvalue()


def test_memory_index_accepts_mixed_case_and_anchor_links():
    s = issues({'Feedback_note.md': 'x', 'ok-note.md': 'y'},
               '- [F](Feedback_note.md)\n- [O](ok-note.md#sec)')
    assert 'index-missing:Feedback_note.md' not in s, s
    assert 'index-missing:ok-note.md' not in s and 'index-ghost' not in s, s
    s = issues({'a.md': 'x', 'topic-index.md': '- [A](a.md) · [up](MEMORY.md)'},
               '- [T](topic-index.md)')
    assert 'index-ghost' not in s and 'index-missing' not in s, s


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    ok = 0
    for f in fns:
        try:
            f()
            ok += 1
            print('✓', f.__name__)
        except AssertionError as e:
            print('✗', f.__name__, str(e)[:300])
    print(f'memory subindex: {ok}/{len(fns)} passed')
    sys.exit(0 if ok == len(fns) else 1)
