"""Playwright-based Canvas login — captures session cookie for `CANVAS_AUTH=cookie`.

Use this when your school disallows self-issued personal access tokens.
Run once initially and again whenever the cookie expires (typically 24h).

    python -m src.canvas_login

Flow (semi-manual on purpose — SSO selectors vary per school, so we don't try to
automate them):

  1. Reads CANVAS_WEB_BASE from .env (or derives from CANVAS_BASE).
  2. Opens a headed Chromium window using a PERSISTENT browser profile at
     `.cookies/playwright-profile/`. Persistence carries Duo / SSO IDP
     "remember this device" trust cookies between runs, so subsequent runs
     skip the 2FA push (until the 30-day Duo trust window expires).
  3. Waits for you to complete SSO + 2FA in the window manually.
  4. After you press Enter, captures `_normandy_session` and `_csrf_token`
     cookies, URL-unquotes the CSRF token (Canvas writes 422 if unquoted with %),
     and writes everything to .cookies/canvas_session.json.

The CSRF token is unquoted ONCE here at capture time; canvas_client.py does NOT
re-unquote when it loads, so tokens that legitimately contain '%' aren't corrupted.

First run: complete SSO + 2FA in the browser, press Enter. ~5 min.
Subsequent runs (when the Canvas session cookie expires, ~24h):
  - If the user ticked "Remember this device" on the first run's 2FA page
    (most providers offer this; not all schools enable it): ~15 seconds —
    browser auto-redirects through SSO, no 2FA push, press Enter.
  - Otherwise: full ceremony again (~5 min). Functionally identical, just
    slower. Cookie auth works fine without remember-me; it's just a
    convenience optimization.
If wedged: `rm -rf .cookies/playwright-profile/` and re-run.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent


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


def main() -> int:
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
    print("In the browser window:")
    print("  1. Complete SSO / 2FA if prompted.")
    print("     (Optional: if 2FA shows a 'Remember this device' / 'Trust")
    print("      browser' checkbox, ticking it lets subsequent runs skip 2FA")
    print("      until that window expires. Not required — daily 2FA also works.)")
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
        # Persistent context launches with a default page already attached.
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(f"{web_base}/login")

        try:
            input("Press Enter once you see the Canvas Dashboard... ")
        except (EOFError, KeyboardInterrupt):
            print("Aborted.", file=sys.stderr)
            context.close()
            return 1

        # Visit /profile/settings to ensure _csrf_token is set on the response.
        # Some SSO flows leave it unset on the dashboard.
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
            "       Make sure you reached the Dashboard before pressing Enter.",
            file=sys.stderr,
        )
        return 2
    if not csrf_cookie:
        print(
            "ERROR: _csrf_token cookie not found.\n"
            "       Try visiting /profile/settings manually before pressing Enter.",
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
    print()
    print("Verify with:")
    print("   CANVAS_AUTH=cookie python -m src.canvas_client --probe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
