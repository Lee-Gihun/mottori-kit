#!/usr/bin/env python3
"""Memory-map observation, unavailable, privacy and navigation contracts."""
import datetime as dt
import importlib.util
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from testlib import run_test

spec = importlib.util.spec_from_file_location('map_builder', Path(__file__).with_name('build_memory_map.py'))
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


def test_age_keeps_whole_days_and_absence_is_not_zero():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'now.md'
        assert B.file_observation(path, dt.datetime.now(dt.timezone.utc))['status'] == 'UNAVAILABLE'
        path.write_text('now')
        now = dt.datetime.now(dt.timezone.utc)
        epoch = (now - dt.timedelta(hours=49)).timestamp()
        os.utime(path, (epoch, epoch))
        observed = B.file_observation(path, now)
        assert observed == {'status': 'STALE', 'age_hours': 49.0}, observed


def test_public_generation_never_imports_private_loop_reader():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'tools').mkdir()
        (root / 'tools/papers_apply.py').write_text("raise RuntimeError('MUST-NOT-READ-PRIVATE')")
        with patch.object(B.M, 'ROOT', td), patch.object(B.M, 'EPISODIC_SOURCES', []), patch.object(B.M, 'parse_journal', return_value=[]):
            data = B.observe(False)
            page = B.render(data, root / 'system/memory-map.html')
        assert data['cycles'] == [] and data['local_now'] is None
        assert 'MUST-NOT-READ-PRIVATE' not in page
        assert data['loop_status'] == 'UNAVAILABLE'
        assert '구현이 멈춘' not in page
        for anchor in ('status', 'flow', 'sources'):
            assert f'id="{anchor}"' in page and f'href="#{anchor}"' in page
        assert '<!doctype html>' in page and 'width=device-width' in page


def test_local_observation_failure_cannot_look_healthy():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'tools').mkdir()
        (root / 'tools/papers_apply.py').write_text("raise RuntimeError('private raw value')")
        with patch.object(B.M, 'ROOT', td), patch.object(B.M, 'EPISODIC_SOURCES', []), patch.object(B.M, 'parse_journal', return_value=[]):
            data = B.observe(True)
            page = B.render(data, root / '_private/work/system-overview/index.html')
        assert data['loop_status'] == 'UNAVAILABLE'
        assert '관측 실패' in data['loop_error']
        assert 'private raw value' not in page
        assert '현재 실행 결과를 아직 확인하지 못했어요' in page



def test_optional_adapter_owns_roots_and_missing_links_are_not_anchors():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'tools').mkdir()
        date = dt.datetime.now(dt.timezone.utc).date().isoformat()
        cycle = root / 'custom-reports' / date
        cycle.mkdir(parents=True)
        (cycle / 'APPLY.md').write_text('private body must not appear')
        (root / 'tools/papers_apply.py').write_text(
            'from pathlib import Path\n'
            'def cycle_sources(root):\n    return [("custom", Path(root)/"custom-reports", "")]\n'
            'def cycle_summary(path):\n    return {"selected": 1, "counts": {"applied": 1}}\n')
        with patch.object(B.M, 'ROOT', td), patch.object(B.M, 'EPISODIC_SOURCES', []), patch.object(B.M, 'parse_journal', return_value=[]):
            data = B.observe(True)
            output = root / '_private/work/system-overview/index.html'
            page = B.render(data, output)
        assert data['loop_status'] == 'AVAILABLE' and len(data['cycles']) == 1
        assert 'private body must not appear' not in page
        assert '2026-10-08-system-revisit.md' not in page
        assert 'href="../../../system/loops.md"' not in page
        assert '<html lang="ko">' in page  # The UI is explicitly pending translation.


def test_adapter_cannot_select_an_outside_root():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'tools').mkdir()
        (root / 'tools/papers_apply.py').write_text(
            'def cycle_sources(root):\n    return [("outside", "/", "")]\n'
            'def cycle_summary(path):\n    raise AssertionError("must not read")\n')
        with patch.object(B.M, 'ROOT', td), patch.object(B.M, 'EPISODIC_SOURCES', []), patch.object(B.M, 'parse_journal', return_value=[]):
            data = B.observe(True)
        assert data['loop_status'] == 'UNAVAILABLE' and data['cycles'] == []
        assert 'ValueError' in data['loop_error']


TESTS = [test_optional_adapter_owns_roots_and_missing_links_are_not_anchors,
         test_adapter_cannot_select_an_outside_root,test_age_keeps_whole_days_and_absence_is_not_zero,
         test_public_generation_never_imports_private_loop_reader,
         test_local_observation_failure_cannot_look_healthy]
if __name__ == '__main__':
    bad = []
    for test in TESTS:
        try:
            run_test(test, __file__)
            print('✓', test.__name__)
        except Exception as exc:
            print('✗', test.__name__, str(exc))
            bad.append(test.__name__)
    print(f'memory_map: {len(TESTS)-len(bad)}/{len(TESTS)} passed')
    raise SystemExit(bool(bad))
