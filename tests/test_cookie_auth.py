"""Unit tests for CANVAS_AUTH=cookie path.

Covers:
  1. CSRF token is read AS-IS from the cookie file (canvas_login.py is the
     one responsible for URL-unquoting; canvas_client must NOT re-unquote
     or it would corrupt tokens that legitimately contain '%').
  2. CANVAS_AUTH=cookie with no .cookies/ directory raises a clear error
     pointing the user at canvas_login, instead of failing cryptically.

The auth selector runs at module import time, so each test runs canvas_client
in a subprocess with a controlled env + temp cookie file to avoid polluting the
parent test process (which already imported canvas_client in token mode).

Run: pytest tests/test_cookie_auth.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run_in_cookie_mode(tmp_path: Path, code: str, csrf_value: str = "abc/def==+xyz"):
    """Spawn a fresh python process with CANVAS_AUTH=cookie and a seeded cookie."""
    cookies_dir = tmp_path / ".cookies"
    cookies_dir.mkdir()
    (cookies_dir / "canvas_session.json").write_text(json.dumps({
        "session_cookie_name": "_normandy_session",
        "session_cookie_value": "fake-session-value",
        "csrf_token": csrf_value,
        "captured_at": "2026-04-25T18:00:00-07:00",
        "domain": "canvas.example.edu",
    }), encoding="utf-8")

    # canvas_client.py reads .cookies/ from ROOT (the repo root), so we have
    # to seed the real ROOT and clean up after.
    real_cookies_dir = ROOT / ".cookies"
    real_cookie_file = real_cookies_dir / "canvas_session.json"
    backup = None
    if real_cookie_file.exists():
        backup = real_cookie_file.read_bytes()
    real_cookies_dir.mkdir(exist_ok=True)
    real_cookie_file.write_bytes((cookies_dir / "canvas_session.json").read_bytes())

    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env={
                "CANVAS_AUTH": "cookie",
                "CANVAS_BASE": "https://canvas.example.edu/api/v1",
                "PATH": str(Path(sys.executable).parent),
                "SYSTEMROOT": "C:\\Windows",  # Windows env basics; harmless on POSIX
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        if backup is not None:
            real_cookie_file.write_bytes(backup)
        else:
            real_cookie_file.unlink(missing_ok=True)
            try:
                real_cookies_dir.rmdir()
            except OSError:
                pass

    return result


def test_csrf_token_passes_through_unquoted(tmp_path):
    """canvas_login.py is supposed to unquote BEFORE writing. canvas_client.py
    must pass the value through verbatim. If it re-unquoted, tokens that
    legitimately contain '%' would break."""
    code = textwrap.dedent("""
        from src import canvas_client
        v = canvas_client._session.headers.get("X-CSRF-Token", "")
        print("HEADER=" + repr(v))
        print("MODE=" + canvas_client.AUTH_MODE)
    """)
    r = _run_in_cookie_mode(tmp_path, code, csrf_value="abc/def==+xyz")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "MODE=cookie" in r.stdout
    assert "HEADER='abc/def==+xyz'" in r.stdout, r.stdout


def test_missing_cookie_file_raises_clear_error(tmp_path):
    """CANVAS_AUTH=cookie with no .cookies/ should raise a clear message
    pointing at canvas_login, not blow up cryptically."""
    real_cookies_dir = ROOT / ".cookies"
    real_cookie_file = real_cookies_dir / "canvas_session.json"
    backup = None
    if real_cookie_file.exists():
        backup = real_cookie_file.read_bytes()
        real_cookie_file.unlink()
    try:
        r = subprocess.run(
            [sys.executable, "-c", "from src import canvas_client"],
            cwd=str(ROOT),
            env={
                "CANVAS_AUTH": "cookie",
                "CANVAS_BASE": "https://canvas.example.edu/api/v1",
                "PATH": str(Path(sys.executable).parent),
                "SYSTEMROOT": "C:\\Windows",
            },
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        if backup is not None:
            real_cookies_dir.mkdir(exist_ok=True)
            real_cookie_file.write_bytes(backup)

    assert r.returncode != 0, "should have failed"
    combined = (r.stderr + r.stdout).lower()
    assert "canvas_login" in combined, f"error msg should mention canvas_login: {r.stderr}"
