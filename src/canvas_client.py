"""Canvas LMS API client (read-only).

This client exposes GET endpoints only — listing courses, assignments,
files, modules, pages, folders, plus a generic `download_file`. The
framework's job is to scan and plan; whatever happens after that is up
to the per-course skills you write.

Two auth modes (controlled by `CANVAS_AUTH` env var, default `token`):

- `token`  — Bearer token from `CANVAS_TOKEN`. Cheap, ~1 year lifetime.
             Use when your school lets you self-issue API tokens.
- `cookie` — for schools that disallow self-issued tokens. Goes through
             a headless Playwright Chromium with a persistent profile at
             `.cookies/playwright-profile/`. The browser owns the auth
             state — we never parse cookie names or schema. On 401, a
             headed browser pops up; user logs in once; the headless
             picks up where it left off. No JSON file, no cookie naming,
             no env override.

Both modes expose the same public API. Switch via `.env`; nothing else
changes.

Usage:
    python -m src.canvas_client --probe
    python -m src.canvas_client --courses
    python -m src.canvas_client --assignments <course_id>

Configuration: reads `CANVAS_AUTH` / `CANVAS_TOKEN` / `CANVAS_BASE` /
`CANVAS_WEB_BASE` from `.env` at the repo root. See `.env.example`.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

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


class CanvasSessionExpired(RuntimeError):
    """Cookie-mode session is expired and re-login failed or timed out."""


AUTH_MODE = os.environ.get("CANVAS_AUTH", "token").strip().lower()
TOKEN = os.environ.get("CANVAS_TOKEN", "")
BASE = os.environ.get("CANVAS_BASE", "https://canvas.instructure.com/api/v1").rstrip("/")


def _derive_web_base() -> str:
    """Web origin (no /api/v1). Used by cookie mode for the login URL."""
    explicit = os.environ.get("CANVAS_WEB_BASE", "").strip()
    if explicit:
        return explicit.rstrip("/")
    if BASE.endswith("/api/v1"):
        return BASE[: -len("/api/v1")]
    return BASE


WEB_BASE = _derive_web_base()


if AUTH_MODE not in ("token", "cookie"):
    raise RuntimeError(
        f"CANVAS_AUTH must be 'token' or 'cookie', got: {AUTH_MODE!r}"
    )

if AUTH_MODE == "token" and not TOKEN:
    raise RuntimeError(
        "CANVAS_TOKEN not set. Copy .env.example to .env and add your token, "
        "or set CANVAS_AUTH=cookie."
    )


# ---------- HTTP backends ----------
#
# Two interchangeable backends behind the same public methods. Token mode
# is plain requests.Session. Cookie mode delegates everything to a headless
# Playwright Chromium so we never touch cookies, names, or schema by hand.

class _RequestsBackend:
    """Token mode: requests.Session with Bearer + browser-like headers.
    Some institutional anti-cheat / analytics tooling flags non-browser
    API callers (default python-requests UA stands out); spoofing as
    Chrome with normal Accept headers neutralizes that signal at zero
    cost."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json+canvas-string-ids, application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        })
        self._session.headers["Authorization"] = f"Bearer {TOKEN}"

    def get(self, url: str, params: dict | None = None) -> Any:
        r = self._session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_with_headers(self, url: str, params: dict | None = None) -> tuple[Any, dict]:
        r = self._session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json(), dict(r.headers)

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = self._session.get(url, stream=True, timeout=120)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return dest

    def get_user_agent(self) -> str:
        return self._session.headers.get("User-Agent", "")


class _PlaywrightBackend:
    """Cookie mode: a headless Chromium with a persistent profile owns the
    auth state. We make Canvas API calls via `context.request`. On 401, we
    close the headless context, open a HEADED context against the same
    profile, wait for the user to log in (detected via /api/v1/users/self
    returning 200 from inside the page), then reopen headless and retry.

    No cookie names. No JSON schema. The browser handles everything a
    browser already handles.
    """

    PROFILE_DIR = ROOT / ".cookies" / "playwright-profile"
    LOGIN_TIMEOUT_SEC = 300  # 5 min for first-time SSO+2FA
    LOGIN_POLL_INTERVAL = 1.5

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "CANVAS_AUTH=cookie requires playwright. Install with:\n"
                "  pip install playwright\n"
                "  python -m playwright install chromium"
            ) from e
        self._sync_playwright = sync_playwright
        self._pw = sync_playwright().start()
        self._ctx = None
        self._auth_checked = False

    def _open_context(self, headless: bool):
        self.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        return self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.PROFILE_DIR),
            headless=headless,
        )

    def _ensure_session(self) -> None:
        if self._auth_checked and self._ctx is not None:
            return
        if self._ctx is None:
            self._ctx = self._open_context(headless=True)
        if not self._auth_works():
            self._ctx.close()
            self._ctx = None
            cookies = self._login_interactive()
            self._ctx = self._open_context(headless=True)
            if cookies:
                self._ctx.add_cookies(cookies)
        self._auth_checked = True

    def _auth_works(self) -> bool:
        try:
            r = self._ctx.request.get(f"{BASE}/users/self")
            return r.status == 200
        except Exception:
            return False

    def _login_interactive(self) -> list:
        """Open a headed Chromium and poll for Canvas auth via the
        BrowserContext's APIRequestContext (it shares cookies with all
        tabs in the context, so it works no matter which tab the SSO
        chain finally lands on — including the new tab a SAML auto-POST
        often pops). On success, capture cookies BEFORE closing —
        Chromium drops session-scoped cookies (no explicit expiry, e.g.
        Canvas's session cookie) when a context closes, so the next
        headless context needs them re-injected via add_cookies()."""
        print(
            "[canvas_client] Opening browser to log in to Canvas. "
            "A Chromium window will pop up.",
            file=sys.stderr,
        )
        ctx = self._open_context(headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{WEB_BASE}/login")
        deadline = time.monotonic() + self.LOGIN_TIMEOUT_SEC
        while time.monotonic() < deadline:
            try:
                r = ctx.request.get(f"{BASE}/users/self")
                if r.status == 200:
                    cookies = ctx.cookies()
                    ctx.close()
                    print("[canvas_client] Login detected.", file=sys.stderr)
                    return cookies
            except Exception:
                pass
            time.sleep(self.LOGIN_POLL_INTERVAL)
        ctx.close()
        raise CanvasSessionExpired(
            f"Login not completed within {self.LOGIN_TIMEOUT_SEC} seconds."
        )

    def _request(self, method: str, url: str, retried: bool = False, **kwargs):
        self._ensure_session()
        try:
            r = getattr(self._ctx.request, method)(url, **kwargs)
        except Exception as e:
            raise CanvasSessionExpired(f"playwright {method} error: {e}") from e
        if r.status == 401 and not retried:
            self._ctx.close()
            self._ctx = None
            self._auth_checked = False
            cookies = self._login_interactive()
            self._ctx = self._open_context(headless=True)
            if cookies:
                self._ctx.add_cookies(cookies)
            self._auth_checked = True
            return self._request(method, url, retried=True, **kwargs)
        if r.status == 401:
            raise CanvasSessionExpired(
                f"Got 401 on {method.upper()} {url} after re-login."
            )
        if r.status >= 400:
            raise requests.HTTPError(
                f"{method.upper()} {url} → HTTP {r.status}: {r.text()[:500]}"
            )
        return r

    def get(self, url: str, params: dict | None = None) -> Any:
        r = self._request("get", url, params=params or {})
        return r.json()

    def get_with_headers(self, url: str, params: dict | None = None) -> tuple[Any, dict]:
        r = self._request("get", url, params=params or {})
        return r.json(), dict(r.headers)

    def download(self, url: str, dest: Path) -> Path:
        r = self._request("get", url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.body())
        return dest

    def get_user_agent(self) -> str:
        try:
            self._ensure_session()
            page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            return page.evaluate("() => navigator.userAgent")
        except Exception:
            return "Mozilla/5.0 (Chromium via Playwright)"


_backend = _RequestsBackend() if AUTH_MODE == "token" else _PlaywrightBackend()


# ---------- Public HTTP primitives ----------

def _parse_link_header(header: str) -> dict[str, str]:
    out = {}
    for part in header.split(","):
        m = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def get(path_or_url: str, **params) -> Any:
    """GET single resource (no pagination)."""
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
    return _backend.get(url, params=params)


def paginate(path_or_url: str, **params) -> list[Any]:
    """GET with Link header pagination, returns flattened list."""
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
    out: list[Any] = []
    while url:
        data, headers = _backend.get_with_headers(
            url, params=params if "?" not in url else None
        )
        if isinstance(data, list):
            out.extend(data)
        else:
            out.append(data)
        link = headers.get("link") or headers.get("Link") or ""
        url = _parse_link_header(link).get("next")
        params = {}
    return out


def get_user_agent() -> str:
    """User-Agent currently being sent on Canvas API calls. Useful for
    skills that mirror the same UA in event payloads or logs. Stable
    across both auth modes."""
    return _backend.get_user_agent()


# ---------- High-level read helpers ----------

def get_self() -> dict:
    return get("/users/self")


def list_courses(enrollment_state: str = "active") -> list[dict]:
    """List enrolled courses. `enrollment_state` ∈ {active, completed,
    invited_or_pending, all}."""
    return paginate("/courses", enrollment_state=enrollment_state, per_page=50)


def list_assignments(course_id: str | int) -> list[dict]:
    return paginate(
        f"/courses/{course_id}/assignments",
        per_page=50,
        order_by="due_at",
        include=["submission"],
    )


def get_assignment(course_id: str | int, assignment_id: str | int) -> dict:
    return get(
        f"/courses/{course_id}/assignments/{assignment_id}",
        include=["submission"],
    )


def get_submission(course_id: str | int, assignment_id: str | int) -> dict:
    return get(
        f"/courses/{course_id}/assignments/{assignment_id}/submissions/self"
    )


def get_file(file_id: str | int) -> dict:
    return get(f"/files/{file_id}")


# ---------- Modules / Pages / Front page ----------
#
# These endpoints are how you find the "real" spec for an assignment when
# `assignment.description` is empty (which is common for STEM courses
# whose instructor maintains a separate website). Pull `front_page` and
# `modules` together and walk from there.

def get_front_page(course_id: str | int) -> dict:
    """Returns the course front page (the wiki page set as homepage).
    Often contains links to an external instructor site that has the
    real assignment specs."""
    return get(f"/courses/{course_id}/front_page")


def list_modules(course_id: str | int) -> list[dict]:
    return paginate(f"/courses/{course_id}/modules", per_page=50)


def list_module_items(course_id: str | int, module_id: str | int) -> list[dict]:
    return paginate(f"/courses/{course_id}/modules/{module_id}/items", per_page=50)


def get_page(course_id: str | int, page_url: str) -> dict:
    """Get a wiki page by its URL slug."""
    return get(f"/courses/{course_id}/pages/{page_url}")


def list_folders(course_id: str | int) -> list[dict]:
    return paginate(f"/courses/{course_id}/folders", per_page=50)


def list_files_in_folder(folder_id: str | int) -> list[dict]:
    return paginate(f"/folders/{folder_id}/files", per_page=50)


def download_file(url: str, dest: Path) -> Path:
    """Download a Canvas file (URL must include verifier or be authenticated)."""
    return _backend.download(url, dest)


# ---------- File link extraction ----------

FILE_LINK_RE = re.compile(r'/courses/(\d+)/files/(\d+)')


def extract_file_ids(html: str | None) -> list[str]:
    if not html:
        return []
    return list({m.group(2) for m in FILE_LINK_RE.finditer(html)})


# ---------- CLI ----------

def _main():
    args = sys.argv[1:]
    if not args or args[0] == "--probe":
        me = get_self()
        print(f"OK Canvas user: {me.get('name')} (id={me.get('id')})")
        courses = list_courses()
        print(f"{len(courses)} active courses:")
        for c in courses:
            print(f"  {c.get('id')} | {c.get('course_code')} | {c.get('name')}")
        return
    if args[0] == "--courses":
        print(json.dumps(list_courses(), indent=2))
        return
    if args[0] == "--assignments" and len(args) >= 2:
        cid = args[1]
        for a in list_assignments(cid):
            sub = a.get("submission") or {}
            print(f"  {a.get('id')} | due={a.get('due_at')} | submitted={sub.get('workflow_state')} | {a.get('name')}")
        return
    print(__doc__)


if __name__ == "__main__":
    _main()
