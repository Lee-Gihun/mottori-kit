#!/usr/bin/env python3
"""Test claude_auth.py with synthetic credentials; never log in or modify real tokens."""
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import sys
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import claude_auth as A  # noqa: E402


def test_auth_environment_precedence_and_private_file_mode():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'token'
        p.write_text('synthetic-file-token')
        p.chmod(0o600)
        with patch.object(A, 'TOKEN_FILE', str(p)):
            assert A.env({A.ENV_KEY:'synthetic-env-token'})[A.ENV_KEY] == 'synthetic-env-token'
            assert A.env({})[A.ENV_KEY] == 'synthetic-file-token'
            p.chmod(0o644)
            assert A.ENV_KEY not in A.env({})
            p.chmod(0o640)  # Group-readable alone must also be refused.
            assert A.ENV_KEY not in A.env({})
            p.unlink()
            assert A.env({'OTHER':'retained'}) == {'OTHER':'retained'}


def test_unreadable_token_file_falls_back():
    import os
    if os.geteuid() == 0:
        return  # Root reads mode-000 files, so the failure cannot be produced.
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'token'
        p.write_text('synthetic-file-token')
        p.chmod(0o000)
        try:
            with patch.object(A, 'TOKEN_FILE', str(p)):
                assert A.ENV_KEY not in A.env({})
            p.chmod(0o600)
            p.write_bytes(b'\xff\xfe not utf-8')
            with patch.object(A, 'TOKEN_FILE', str(p)):
                assert A.ENV_KEY not in A.env({})
        finally:
            p.chmod(0o600)


def test_save_writes_private_file():
    import contextlib
    import io
    import os
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'token'
        p.write_text('old')
        p.chmod(0o644)
        seen = {}

        def spy_fdopen(fd, *args, **kwargs):
            seen['mode_before_write'] = os.fstat(fd).st_mode & 0o777
            return real_fdopen(fd, *args, **kwargs)
        real_fdopen = os.fdopen
        with patch.object(A, 'TOKEN_FILE', str(p)), \
                patch.object(A.getpass, 'getpass', return_value='synthetic-saved-token'), \
                patch.object(A.os, 'fdopen', side_effect=spy_fdopen), \
                patch.object(A, 'check', return_value=0), \
                contextlib.redirect_stdout(io.StringIO()):
            assert A.save() == 0
        assert seen['mode_before_write'] == 0o600, oct(seen['mode_before_write'])
        assert p.stat().st_mode & 0o777 == 0o600
        assert p.read_text() == 'synthetic-saved-token\n'
        q = Path(td) / 'sub' / 'token'
        with patch.object(A, 'TOKEN_FILE', str(q)), \
                patch.object(A.getpass, 'getpass', return_value=''), \
                patch.object(A, 'check', side_effect=AssertionError('probe')), \
                contextlib.redirect_stdout(io.StringIO()):
            assert A.save() == 1
        assert not q.exists()
        target = Path(td) / 'target'
        target.write_text('untouched')
        link = Path(td) / 'link'
        link.symlink_to(target)
        with patch.object(A, 'TOKEN_FILE', str(link)), \
                patch.object(A.getpass, 'getpass', return_value='synthetic-saved-token'), \
                patch.object(A, 'check', side_effect=AssertionError('probe')), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                A.save()
                raise AssertionError('save followed a symlink')
            except OSError:
                pass
        assert target.read_text() == 'untouched'
        # The probe after saving uses what the workers use: an environment token overrides
        # the saved file, so save names it and fails when that token does not work.
        used = {}

        def probe(*args, **kwargs):
            used['token'] = kwargs['env'].get(A.ENV_KEY)
            ok = used['token'] == 'synthetic-new-token'
            return A.subprocess.CompletedProcess(args, 0 if ok else 1, stdout=A.SENTINEL if ok else '',
                                                 stderr='' if ok else 'OAuth token has expired')
        for env_token, rc, named in (('synthetic-expired-env', 1, True), ('synthetic-new-token', 0, False)):
            with patch.object(A, 'TOKEN_FILE', str(p)), \
                    patch.dict(A.os.environ, {A.ENV_KEY: env_token}), \
                    patch.object(A.getpass, 'getpass', return_value='synthetic-new-token'), \
                    patch.object(A.subprocess, 'run', side_effect=probe), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                assert A.save() == rc, out.getvalue()
            assert used['token'] == env_token, used
            assert ('instead of the saved file' in out.getvalue()) is named, out.getvalue()


def test_auth_help_and_invalid_command_never_probe_or_save():
    with patch.object(A, 'check', side_effect=AssertionError('probe')), patch.object(A, 'save', side_effect=AssertionError('save')):
        for args, expected in ((['--help'],0),(['bogus'],2)):
            try:
                A.main(args)
                raise AssertionError('parse should exit')
            except SystemExit as exc:
                assert exc.code == expected


def test_auth_probe_requires_real_sentinel_and_clean_status():
    assert A.judge(0,A.SENTINEL,'')[0]
    assert not A.judge(1,A.SENTINEL,'')[0]
    assert not A.judge(0,'not the requested response','')[0]
    # A clean sentinel run passes even when a warning mentions token expiry.
    assert A.judge(0,A.SENTINEL,'warning: your token will be expired soon')[0]
    assert not A.judge(1,A.SENTINEL,'OAuth token has expired')[0]
    assert not A.judge(0,'',  'OAuth token has expired')[0]


def test_check_separates_login_failure_from_other_probe_failure():
    import contextlib
    import io
    import subprocess
    from types import SimpleNamespace
    with patch.object(A, 'env', return_value={}), patch.object(A, 'source', return_value='synthetic'):
        with patch.object(A.subprocess, 'run', side_effect=subprocess.TimeoutExpired('claude', 120)), \
                contextlib.redirect_stdout(io.StringIO()):
            assert A.check() == 2
        for rc, out, err in ((0, 'wrong', ''), (3, '', 'some crash')):
            with patch.object(A.subprocess, 'run', return_value=SimpleNamespace(returncode=rc, stdout=out, stderr=err)), \
                    contextlib.redirect_stdout(io.StringIO()):
                assert A.check() == 2, (rc, out, err)
        with patch.object(A.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='OAuth token has expired')), \
                contextlib.redirect_stdout(io.StringIO()):
            assert A.check() == 1


def test_claude_environment_removes_foreign_provider_settings():
    base = {'CLAUDE_CODE_OAUTH_TOKEN': 'synthetic-claude', 'ANTHROPIC_API_KEY': 'synthetic-anthropic',
            'OPENAI_API_KEY': 'synthetic-openai', 'CODEX_API_KEY': 'synthetic-codex',
            'CODEX_HOME': '/synthetic/codex', 'PATH': '/synthetic/bin'}
    result = A.env(base)
    assert result == {key: value for key, value in base.items()
                      if not key.startswith(('OPENAI_', 'CODEX_'))}
    assert 'OPENAI_API_KEY' in base


def test_auth_probe_is_isolated_and_never_echoes_runtime_output():
    import contextlib
    import io
    from types import SimpleNamespace
    sentinel = 'synthetic-sensitive-error-value'
    for rc, out, err in ((1, sentinel, ''), (0, sentinel, ''), (0, '', 'authentication_error ' + sentinel)):
        ok, reason = A.judge(rc, out, err)
        assert not ok and sentinel not in reason
    with patch.object(A, 'env', return_value={'HOME': '/synthetic/home'}), \
            patch.object(A.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=A.SENTINEL, stderr='')) as run, \
            patch.object(A, 'source', return_value='synthetic auth source'):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert A.check() == 0
        command = run.call_args[0][0]
        assert '--safe-mode' in command and '--strict-mcp-config' in command
        assert command[command.index('--mcp-config') + 1] == '{"mcpServers":{}}'
        assert command[command.index('--tools') + 1] == ''
        assert '--disable-slash-commands' in command and '--no-chrome' in command
        assert '--no-session-persistence' in command
        assert command[command.index('--permission-mode') + 1] == 'dontAsk'
        kwargs = run.call_args[1]
        assert kwargs['stdin'] is A.subprocess.DEVNULL and kwargs['timeout'] == 120
    with patch.object(A.subprocess, 'run', side_effect=RuntimeError(sentinel)), \
            patch.object(A, 'env', return_value={}):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert A.check() != 0
        assert sentinel not in output.getvalue()


TESTS=[test_unreadable_token_file_falls_back,test_save_writes_private_file,test_check_separates_login_failure_from_other_probe_failure,test_claude_environment_removes_foreign_provider_settings,test_auth_probe_is_isolated_and_never_echoes_runtime_output,test_auth_environment_precedence_and_private_file_mode,test_auth_help_and_invalid_command_never_probe_or_save,test_auth_probe_requires_real_sentinel_and_clean_status]
if __name__=='__main__':
    bad=[]
    for test in TESTS:
        try:
            test()
            print('✓',test.__name__)
        except Exception as exc:
            bad.append(test.__name__)
            print('✗',test.__name__,str(exc))
    print(f'claude_auth: {len(TESTS)-len(bad)}/{len(TESTS)} passed')
    raise SystemExit(bool(bad))
