#!/usr/bin/env python3
"""Memory-map privacy, determinism and navigation contracts."""
import contextlib
import datetime as dt
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('map_builder', Path(__file__).resolve().parent.parent / 'dev' / 'build_memory_map.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import journal  # noqa: E402


@contextlib.contextmanager
def _instance(td):
    """Point the builder at td, with no search sources and an empty journal."""
    with patch.dict(os.environ, {'MOTTORI_INSTANCE': td}), \
            patch.object(B.C, 'episodic_sources', return_value=[]), \
            patch.object(journal, 'parse_journal', return_value=[]):
        yield


def test_public_generation_never_imports_private_loop_reader():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'tools' / 'loop').mkdir(parents=True)
        # The reader leaves a marker before raising, so a swallowed import error still shows.
        (root / 'tools/loop/papers_apply.py').write_text(
            "from pathlib import Path\n"
            "Path(__file__).with_name('READ-MARKER').touch()\n"
            "raise RuntimeError('MUST-NOT-READ-PRIVATE')\n")
        with _instance(td):
            data = B.observe()
            page = B.render(data, root / 'state/memory-map.html')
        # No local keys (cycles, local NOW, loop error) may reach the public data.
        assert set(data) == {'sources'}
        assert not (root / 'tools/READ-MARKER').exists()
        assert 'MUST-NOT-READ-PRIVATE' not in page
        assert '구현이 멈춘' not in page
        for anchor in ('status', 'flow', 'sources'):
            assert f'id="{anchor}"' in page and f'href="#{anchor}"' in page
        assert '<!doctype html>' in page and 'width=device-width' in page


def test_no_local_flag():
    """The private status view was removed; only the public design map is generated."""
    try:
        B.main(['--local'])
    except SystemExit as exc:
        assert exc.code == 2, exc.code
    else:
        raise AssertionError('--local was accepted')
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'tools' / 'loop').mkdir(parents=True)
        (root / 'tools/loop/papers_apply.py').write_text("raise RuntimeError('MUST-NOT-READ-PRIVATE')")
        with _instance(td):
            B.observe()


def test_public_map_is_deterministic():
    """A design page must not change just because time passed or NOW was touched."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'state').mkdir()
        now_file = root / 'state/NOW.md'
        now_file.write_text('now')
        output = root / 'state/memory-map.html'
        with _instance(td):
            first = B.render(B.observe(), output)
            old = (dt.datetime.now() - dt.timedelta(hours=50)).timestamp()
            os.utime(now_file, (old, old))
            with patch.object(journal, 'parse_journal', return_value=[{}, {}]):
                second = B.render(B.observe(), output)
        assert first == second


TESTS = [test_public_generation_never_imports_private_loop_reader,
         test_no_local_flag, test_public_map_is_deterministic]
if __name__ == '__main__':
    bad = []
    for test in TESTS:
        try:
            test()
            print('✓', test.__name__)
        except Exception as exc:
            print('✗', test.__name__, str(exc))
            bad.append(test.__name__)
    print(f'memory_map: {len(TESTS)-len(bad)}/{len(TESTS)} passed')
    raise SystemExit(bool(bad))
