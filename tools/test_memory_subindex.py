#!/usr/bin/env python3
"""Regression tests for one-level memory subindexes in now.py check."""
import contextlib
import io
import os
import sys
import tempfile
from testlib import run_test

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import now  # noqa: E402


def issues(files, index):
    tmp = tempfile.TemporaryDirectory()
    d = tmp.name
    for name, text in files.items():
        open(os.path.join(d, name), 'w', encoding='utf-8').write(text)
    open(os.path.join(d, 'MEMORY.md'), 'w', encoding='utf-8').write(index)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            now.check(memory_dir=d, root=d, issues=True)
        except SystemExit:
            pass
    result = out.getvalue()
    tmp.cleanup()
    return result


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
    tmp = tempfile.TemporaryDirectory()
    d = tmp.name
    open(os.path.join(d, 'MEMORY.md'), 'w', encoding='utf-8').write('- [T](bad-index.md)')
    open(os.path.join(d, 'bad-index.md'), 'wb').write(b'\xff\xfe\x00bad')
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            now.check(memory_dir=d, root=d, issues=True)
        except SystemExit:
            pass
    tmp.cleanup()
    assert 'subindex-unreadable:bad-index.md' in out.getvalue(), out.getvalue()


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    ok = 0
    for f in fns:
        try:
            run_test(f, __file__)
            ok += 1
            print('✓', f.__name__)
        except AssertionError as e:
            print('✗', f.__name__, str(e)[:300])
    print(f'memory subindex: {ok}/{len(fns)} passed')
    sys.exit(0 if ok == len(fns) else 1)
