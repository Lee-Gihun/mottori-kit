#!/usr/bin/env python3
"""Use an explicitly saved credential for headless Claude calls.

Without a saved token, retain the runtime's existing authentication method.
Installing this module neither creates credentials nor expands permissions.
Token values stay outside the repository. The owner may explicitly configure:
    claude setup-token
    python3 tools/claude_auth.py save   # Hidden input, saved with mode 600.
    python3 tools/claude_auth.py check  # One real headless probe.
"""
import argparse
import getpass
import os
import re
import stat
import subprocess
import sys

TOKEN_FILE = os.path.expanduser("~/.config/mottori/claude-oauth-token")
ENV_KEY = "CLAUDE_CODE_OAUTH_TOKEN"
FIX = ("Headless Claude authentication failed. Refresh using `claude setup-token`, "
       "then `python3 tools/claude_auth.py save`.")

_AUTH_ERR = re.compile(
    r"Please run /login|OAuth token has expired|authentication_error|Invalid API key|"
    r"401 Unauthorized|Not logged in|invalid x-api-key|token.*(expired|revoked)", re.I)


def _read_token():
    try:
        st = os.stat(TOKEN_FILE)
    except OSError:
        return None
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return None  # Never use a token file readable by other users.
    tok = open(TOKEN_FILE, encoding="utf-8").read().strip()
    return tok or None


def env(base=None):
    """Build a Claude environment without OpenAI/Codex provider settings.

    An explicit Claude environment token takes precedence over the saved token.
    """
    e = {key: value for key, value in (os.environ if base is None else base).items()
         if not key.upper().startswith(("OPENAI_", "CODEX_"))}
    if not e.get(ENV_KEY):
        tok = _read_token()
        if tok:
            e[ENV_KEY] = tok
    return e


def is_auth_error(text):
    return bool(text) and bool(_AUTH_ERR.search(text))


def explain(text):
    """Append recovery instructions only when the output indicates an auth error."""
    return (text or "") + ("\n" + FIX if is_auth_error(text) else "")


SENTINEL = "MOTTORI_AUTH_OK"


def source():
    """Report the credential source, using the same precedence as env()."""
    if os.environ.get(ENV_KEY):
        return "environment token (CLAUDE_CODE_OAUTH_TOKEN, overrides file)"
    if _read_token():
        return "saved token file"
    return "interactive login (may expire)"


def judge(rc, stdout, stderr):
    """Require exit 0, no auth error, and exactly one sentinel line. Return (ok, reason)."""
    out = ((stdout or "") + "\n" + (stderr or "")).strip()
    if is_auth_error(out):
        return False, FIX
    if rc != 0:
        return False, f"Authentication probe exited with status {rc}."
    lines = [ln.strip().strip("`*. ") for ln in (stdout or "").splitlines() if ln.strip()]
    if lines != [SENTINEL]:
        return False, "Authentication response did not match the expected sentinel."
    return True, "ok"


def check():
    try:
        r = subprocess.run(["claude", "-p", f"Reply with exactly this one token and nothing else: {SENTINEL}",
                            "--model", "claude-haiku-4-5-20251001",
                            "--no-session-persistence", "--safe-mode", "--strict-mcp-config",
                            "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
                            "--permission-mode", "dontAsk", "--tools", "", "--no-chrome"],
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=env(), timeout=120, cwd="/tmp")
    except Exception as ex:  # noqa: BLE001
        print(f"Authentication probe could not run ({type(ex).__name__}).")
        return 1
    ok, why = judge(r.returncode, r.stdout, r.stderr)
    if ok:
        print(f"OK ({source()})")
        return 0
    print(f"{why}\n(Credential source: {source()})")
    return 1


def save():
    tok = getpass.getpass("Paste setup-token value (hidden input): ").strip()
    if not tok:
        print("Empty value. Nothing saved.")
        return 1
    os.makedirs(os.path.dirname(TOKEN_FILE), mode=0o700, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok + "\n")
    os.chmod(TOKEN_FILE, 0o600)
    print("Saved. Running one authentication probe.")
    return check()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="check", choices=("check", "save"))
    args = ap.parse_args(argv)
    return {"check": check, "save": save}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
