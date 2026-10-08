#!/usr/bin/env python3
"""Test claude_auth.py with synthetic credentials; never log in or modify real tokens."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import claude_auth as A
from testlib import run_test


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
            p.unlink()
            assert A.env({'OTHER':'retained'}) == {'OTHER':'retained'}


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
    assert not A.judge(0,A.SENTINEL,'OAuth token has expired')[0]


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
    with patch.object(A.subprocess, 'run', side_effect=RuntimeError(sentinel)), \
            patch.object(A, 'env', return_value={}):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert A.check() == 1
        assert sentinel not in output.getvalue()


TESTS=[test_claude_environment_removes_foreign_provider_settings,test_auth_probe_is_isolated_and_never_echoes_runtime_output,test_auth_environment_precedence_and_private_file_mode,test_auth_help_and_invalid_command_never_probe_or_save,test_auth_probe_requires_real_sentinel_and_clean_status]
if __name__=='__main__':
    bad=[]
    for test in TESTS:
        try:
            run_test(test,__file__)
            print('✓',test.__name__)
        except Exception as exc:
            bad.append(test.__name__)
            print('✗',test.__name__,str(exc))
    print(f'claude_auth: {len(TESTS)-len(bad)}/{len(TESTS)} passed')
    raise SystemExit(bool(bad))
