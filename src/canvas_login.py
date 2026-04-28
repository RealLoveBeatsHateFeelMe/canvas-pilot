"""Playwright-based Canvas login — captures session cookie for `CANVAS_AUTH=cookie`.

Use this when your school disallows self-issued personal access tokens.

You normally don't run this directly. `canvas_client` calls it as a subprocess
the first time it sees a missing or expired cookie, so the daily user-facing
flow is just `scan canvas` — a Chromium window pops up, you log in, it closes.
This module is the underlying primitive; you can still run it manually for
debugging:

    python -m src.canvas_login            # auto mode (default)
    python -m src.canvas_login --manual   # legacy press-Enter flow

Auto mode (default):
  1. Reads CANVAS_WEB_BASE from .env (or derives from CANVAS_BASE).
  2. Opens a headed Chromium window using a PERSISTENT browser profile at
     `.cookies/playwright-profile/`. Persistence carries Duo / SSO IDP
     "remember this device" trust cookies between runs, so subsequent runs
     skip the 2FA push (until the 30-day Duo trust window expires).
  3. Polls the browser context every 1.5s for the `_normandy_session` cookie.
     As soon as it appears (= SSO completed, Canvas redirected to dashboard),
     visits `/profile/settings` to ensure `_csrf_token` is also set, then
     captures both cookies and closes the window.
  4. Hard cap: 5 minutes. If the user never completes login, returns exit
     code 3 so callers know it's a user-cancel, not a transient failure.

Manual mode (--manual):
  Same as auto except step 3 waits for `input()` instead of polling — used
  when an SSO chain doesn't actually set `_normandy_session` until after
  multiple post-login redirects, and the auto loop would close the window
  prematurely. Rare; reserved for debugging.

Exit codes:
  0  success — cookie file written
  1  environment / playwright not installed
  2  cookies missing after login completed (CSRF token never appeared)
  3  timeout — user did not finish login within 5 minutes (auto mode only)

The CSRF token is URL-unquoted ONCE here at capture time; canvas_client.py
does NOT re-unquote when it loads, so tokens that legitimately contain '%'
aren't corrupted.

If wedged: `rm -rf .cookies/playwright-profile/` and re-run.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent

AUTO_TIMEOUT_SEC = 300   # 5 min hard cap on user finishing SSO+2FA
POLL_INTERVAL_SEC = 1.5  # how often to check for session cookie


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _derive_web_base() -> str | None:
    """Prefer explicit CANVAS_WEB_BASE; else strip /api/v1 from CANVAS_BASE."""
    explicit = os.environ.get("CANVAS_WEB_BASE", "").strip()
    if explicit:
        return explicit.rstrip("/")
    api_base = os.environ.get("CANVAS_BASE", "").strip().rstrip("/")
    if not api_base:
        return None
    if api_base.endswith("/api/v1"):
        return api_base[: -len("/api/v1")]
    return api_base


def _wait_for_session_cookie(context, deadline: float) -> bool:
    """Poll context cookies until `_normandy_session` appears or deadline passes."""
    while time.monotonic() < deadline:
        cookies = context.cookies()
        if any(c["name"] == "_normandy_session" for c in cookies):
            return True
        time.sleep(POLL_INTERVAL_SEC)
    return False


def main() -> int:
    auto = "--manual" not in sys.argv[1:]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed.", file=sys.stderr)
        print(
            "Install:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    web_base = _derive_web_base()
    if not web_base:
        print(
            "ERROR: set CANVAS_WEB_BASE in .env "
            "(e.g. https://canvas.<your-school>.edu)\n"
            "       or CANVAS_BASE so we can derive it.",
            file=sys.stderr,
        )
        return 1

    profile_dir = ROOT / ".cookies" / "playwright-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"Opening browser to {web_base}/login")
    print(f"  Profile dir: {profile_dir}")
    print()
    if auto:
        print("Complete SSO + 2FA in the browser window.")
        print("This window will close automatically once login is detected")
        print(f"(timeout: {AUTO_TIMEOUT_SEC // 60} min).")
        print("  Tip: tick 'Remember this device' on the 2FA page if offered —")
        print("  next renewal then takes ~15s with no 2FA push.")
    else:
        print("In the browser window:")
        print("  1. Complete SSO / 2FA if prompted.")
        print("  2. Wait until your Canvas Dashboard appears.")
        print("  3. Switch back here and press Enter.")
    print()

    with sync_playwright() as p:
        # Persistent context: cookies + localStorage + IndexedDB + Duo trust
        # state survive between runs. New context returned directly (not a
        # Browser wrapper), so close() is on the context.
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(f"{web_base}/login")

        if auto:
            deadline = time.monotonic() + AUTO_TIMEOUT_SEC
            got_session = _wait_for_session_cookie(context, deadline)
            if not got_session:
                print(
                    f"ERROR: timeout — no Canvas session cookie after "
                    f"{AUTO_TIMEOUT_SEC} s. Login not completed.",
                    file=sys.stderr,
                )
                context.close()
                return 3
        else:
            try:
                input("Press Enter once you see the Canvas Dashboard... ")
            except (EOFError, KeyboardInterrupt):
                print("Aborted.", file=sys.stderr)
                context.close()
                return 1

        # Visit /profile/settings to ensure _csrf_token is set on the response.
        # Some SSO flows leave it unset on the dashboard. In auto mode this
        # also guards against the rare race where _normandy_session lands a
        # poll-tick before the CSRF cookie does.
        page.goto(f"{web_base}/profile/settings")
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass  # not fatal; cookies should still be present

        cookies = context.cookies()
        context.close()

    session_cookie = next(
        (c for c in cookies if c["name"] == "_normandy_session"), None
    )
    csrf_cookie = next(
        (c for c in cookies if c["name"] == "_csrf_token"), None
    )

    if not session_cookie:
        print(
            "ERROR: _normandy_session cookie not found — login likely incomplete.\n"
            "       Make sure you reached the Dashboard before the window closed.",
            file=sys.stderr,
        )
        return 2
    if not csrf_cookie:
        print(
            "ERROR: _csrf_token cookie not found.\n"
            "       Try `python -m src.canvas_login --manual` to debug.",
            file=sys.stderr,
        )
        return 2

    out = {
        "session_cookie_name": "_normandy_session",
        "session_cookie_value": session_cookie["value"],
        "csrf_token": unquote(csrf_cookie["value"]),
        "captured_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "domain": session_cookie["domain"],
    }

    cookie_path = ROOT / ".cookies" / "canvas_session.json"
    cookie_path.parent.mkdir(exist_ok=True)
    cookie_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print()
    print(f"OK Cookies captured. Wrote {cookie_path}")
    print(f"   domain={out['domain']}  csrf_token_len={len(out['csrf_token'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
