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

# Messages this module prints in more than one place, or too long to read inline.
AUTH_ENV_OVERRIDES = (
    "{var} is set in this environment and workers use it instead of the saved file: unset it, "
    "or set it to the new token."
)
AUTH_FIX = (
    "Headless Claude authentication failed. Refresh using `claude setup-token`, then `python3 "
    "tools/claude_auth.py save`."
)

TOKEN_FILE = os.path.expanduser("~/.config/mottori/claude-oauth-token")
ENV_KEY = "CLAUDE_CODE_OAUTH_TOKEN"
SENTINEL = "MOTTORI_AUTH_OK"
# Each vendor's environment prefixes. fresh_worker.py gives a worker only its own vendor's
# variables; env() below removes the Codex ones from every headless Claude call.
VENDOR_ENV = {
    "claude": ("CLAUDE_", "ANTHROPIC_"),
    "codex": ("OPENAI_", "CODEX_"),
    "gemini": ("GEMINI_", "GOOGLE_", "ANTIGRAVITY_"),
}

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
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            tok = f.read().strip()
    except (OSError, UnicodeDecodeError):
        return None  # An unreadable file must not crash callers; fall back to the login.
    return tok or None


def without_vendors(base, vendors):
    """base without the environment variables of the named vendors (keys of VENDOR_ENV)."""
    prefixes = tuple(prefix for vendor in vendors for prefix in VENDOR_ENV[vendor])
    return {key: value for key, value in base.items() if not key.upper().startswith(prefixes)}


def env(base=None):
    """Build a Claude environment without OpenAI/Codex provider settings.

    An explicit Claude environment token takes precedence over the saved token.
    """
    e = without_vendors(os.environ if base is None else base, ("codex",))
    if not e.get(ENV_KEY):
        tok = _read_token()
        if tok:
            e[ENV_KEY] = tok
    return e


def is_auth_error(text):
    return bool(text) and bool(_AUTH_ERR.search(text))


def explain(text):
    """Append recovery instructions only when the output indicates an auth error.

    The engine does not call it; it is for an instance's own tools that call Claude directly and
    pass its error text on.
    """
    return (text or "") + ("\n" + AUTH_FIX if is_auth_error(text) else "")


def source():
    """Report the credential source, using the same precedence as env()."""
    if os.environ.get(ENV_KEY):
        return f"environment token ({ENV_KEY}, overrides file)"
    if _read_token():
        return "saved token file"
    return "interactive login (may expire)"


def judge(rc, stdout, stderr):
    """Require exit 0 and exactly one sentinel line. Return (ok, reason).

    A clean sentinel run passes first, so a warning that merely mentions token
    expiry cannot fail a probe that actually authenticated.
    """
    lines = [ln.strip().strip("`*. ") for ln in (stdout or "").splitlines() if ln.strip()]
    if rc == 0 and lines == [SENTINEL]:
        return True, "ok"
    out = ((stdout or "") + "\n" + (stderr or "")).strip()
    if is_auth_error(out):
        return False, AUTH_FIX
    if rc != 0:
        return False, f"Authentication probe exited with status {rc}."
    return False, "Authentication response did not match the expected sentinel."


def check():
    """Exit 0 on success, 1 for a login failure, 2 when the probe failed for another reason.

    The probe uses env(), the same credential the workers will use."""
    probe_env = env()
    where = source()
    try:
        r = subprocess.run(["claude", "-p", f"Reply with exactly this one token and nothing else: {SENTINEL}",
                            "--model", "claude-haiku-4-5-20251001",
                            "--no-session-persistence", "--safe-mode", "--strict-mcp-config",
                            "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
                            "--permission-mode", "dontAsk", "--tools", "", "--no-chrome"],
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=probe_env, timeout=120, cwd="/tmp")
    except Exception as ex:  # noqa: BLE001
        print(f"Authentication probe could not run ({type(ex).__name__}).")
        return 2
    ok, why = judge(r.returncode, r.stdout, r.stderr)
    if ok:
        print(f"OK ({where})")
        return 0
    print(f"{why}\n(Credential source: {where})")
    return 1 if why == AUTH_FIX else 2


def save():
    tok = getpass.getpass("Paste setup-token value (hidden input): ").strip()
    if not tok:
        print("Empty value. Nothing saved.")
        return 1
    os.makedirs(os.path.dirname(TOKEN_FILE), mode=0o700, exist_ok=True)
    # O_NOFOLLOW refuses a planted symlink; fchmod before writing so an existing
    # loose file never holds the secret with its old mode.
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        os.close(fd)
        raise
    with os.fdopen(fd, "w") as f:
        f.write(tok + "\n")
    print("Saved. Running one authentication probe.")
    # Workers prefer an environment token over the file, so saving alone does not repair them.
    if os.environ.get(ENV_KEY) not in (None, "", tok):
        print(AUTH_ENV_OVERRIDES.format(var=ENV_KEY))
    return check()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="check", choices=("check", "save"),
                    help="check: one real headless probe with the saved credential (the default); "
                         "save: save a token from hidden input, mode 600")
    args = ap.parse_args(argv)
    return {"check": check, "save": save}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
