"""Canvas LMS API client (read-only).

This client exposes GET endpoints only — listing courses, assignments,
files, modules, pages, folders, plus a generic `download_file`. The
framework's job is to scan and plan.

Two auth modes (controlled by `CANVAS_AUTH` env var, default `token`):

- `token`  — Bearer token from `CANVAS_TOKEN`. Use when your school lets
             you self-issue a personal access token.
- `cookie` — alternative for schools that disallow self-issued tokens.
             Reads `.cookies/canvas_session.json` written by `canvas_login`.
             First-time use (file missing) and 401 mid-session both auto-launch
             `python -m src.canvas_login --auto` as a subprocess — a Chromium
             window pops up, user logs in, window closes, request retries.
             User never needs to run `canvas_login` directly. Set
             `CANVAS_NO_AUTO_RELOGIN=1` to disable (then a missing/expired
             cookie raises `CanvasSessionExpired` like the old behavior).

Usage:
    python -m src.canvas_client --probe
    python -m src.canvas_client --courses
    python -m src.canvas_client --assignments <course_id>

Configuration: reads `CANVAS_AUTH` / `CANVAS_TOKEN` / `CANVAS_BASE` from
`.env` at the repo root. See `.env.example`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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
    """Cookie-mode session expired (401). Re-run `python -m src.canvas_login`."""


AUTH_MODE = os.environ.get("CANVAS_AUTH", "token").strip().lower()
TOKEN = os.environ.get("CANVAS_TOKEN", "")
BASE = os.environ.get("CANVAS_BASE", "https://canvas.instructure.com/api/v1").rstrip("/")

if AUTH_MODE not in ("token", "cookie"):
    raise RuntimeError(
        f"CANVAS_AUTH must be 'token' or 'cookie', got: {AUTH_MODE!r}"
    )

if AUTH_MODE == "token" and not TOKEN:
    raise RuntimeError(
        "CANVAS_TOKEN not set. Copy .env.example to .env and add your token, "
        "or set CANVAS_AUTH=cookie and run `python -m src.canvas_login`."
    )

_session = requests.Session()
# Set explicit headers. Canvas accepts the special string-id Accept value,
# which makes the API return assignment/course IDs as strings (avoiding
# JS-side precision loss with very large numeric IDs).
_session.headers.update({
    "User-Agent": "canvas-pilot/1.0",
    "Accept": "application/json+canvas-string-ids, application/json",
})

_COOKIE_PATH = ROOT / ".cookies" / "canvas_session.json"

if AUTH_MODE == "token":
    _session.headers["Authorization"] = f"Bearer {TOKEN}"
else:
    def _load_cookies_from_disk() -> bool:
        """Read .cookies/canvas_session.json into _session. Return False if missing."""
        if not _COOKIE_PATH.exists():
            return False
        cookie_data = json.loads(_COOKIE_PATH.read_text(encoding="utf-8"))
        _session.cookies.clear()
        _session.cookies.set(
            cookie_data["session_cookie_name"],
            cookie_data["session_cookie_value"],
            domain=cookie_data["domain"],
            path="/",
        )
        # Canvas CSRF token is session-scoped; same value works for every write
        # for the lifetime of the session. Setting it as a default header is harmless
        # on GETs (Canvas ignores it) and saves a per-request hook. The value stored
        # in canvas_session.json is already URL-unquoted by canvas_login.py — do not
        # unquote again here (would corrupt tokens that legitimately contain '%').
        _session.headers["X-CSRF-Token"] = cookie_data["csrf_token"]
        return True

    def _relogin_subprocess() -> bool:
        """Launch `python -m src.canvas_login --auto` and wait for it.
        Returns True iff it exited 0. CANVAS_NO_AUTO_RELOGIN=1 disables this."""
        if os.environ.get("CANVAS_NO_AUTO_RELOGIN") == "1":
            return False
        print(
            "[canvas_client] Canvas cookie missing or expired — "
            "opening browser to log in (Chromium window will pop up).",
            file=sys.stderr,
        )
        env = {**os.environ, "CANVAS_NO_AUTO_RELOGIN": "1"}
        rc = subprocess.run(
            [sys.executable, "-m", "src.canvas_login", "--auto"],
            cwd=str(ROOT),
            env=env,
        ).returncode
        if rc == 0:
            return True
        print(
            f"[canvas_client] canvas_login exited rc={rc}; auto-relogin failed.",
            file=sys.stderr,
        )
        return False

    # Wrap _session.request to retry once on 401 after re-login.
    # Both the first-time case (no cookie file) and the 24h-expiry case
    # land here: first-time has no Cookie header at all → Canvas 401s →
    # we relogin → retry succeeds. 24h-expiry has stale cookie → 401 →
    # relogin → retry. _retrying flag prevents recursion if relogin
    # itself somehow fails to fix the auth.
    _original_request = _session.request
    _retrying = {"in_progress": False}

    def _request_with_relogin(method, url, **kwargs):
        resp = _original_request(method, url, **kwargs)
        if (
            resp.status_code == 401
            and not _retrying["in_progress"]
            and os.environ.get("CANVAS_NO_AUTO_RELOGIN") != "1"
        ):
            _retrying["in_progress"] = True
            try:
                if _relogin_subprocess() and _load_cookies_from_disk():
                    resp = _original_request(method, url, **kwargs)
            finally:
                _retrying["in_progress"] = False
        if resp.status_code == 401:
            raise CanvasSessionExpired(
                "Canvas session expired (401). Auto-relogin disabled or failed. "
                "Run `python -m src.canvas_login` manually to debug."
            )
        return resp

    _session.request = _request_with_relogin

    # Initial cookie load — if no file exists, kick off first-time login now
    # so importing canvas_client is enough to "have a working session". If
    # subprocess says success but the cookie file still won't load, that's a
    # bug we'd rather surface here than discover via mysterious 401s later.
    if not _load_cookies_from_disk():
        if not (_relogin_subprocess() and _load_cookies_from_disk()):
            raise RuntimeError(
                f"CANVAS_AUTH=cookie but {_COOKIE_PATH} not found and "
                f"auto-relogin failed or disabled. "
                f"Run: python -m src.canvas_login"
            )


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
    r = _session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def paginate(path_or_url: str, **params) -> list[Any]:
    """GET with Link header pagination, returns flattened list."""
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
    out: list[Any] = []
    while url:
        r = _session.get(url, params=params if "?" not in url else None, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            out.extend(data)
        else:
            out.append(data)
        link = r.headers.get("Link", "")
        nxt = _parse_link_header(link).get("next")
        url = nxt
        params = {}
    return out


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
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = _session.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return dest


# ---------- File link extraction from assignment description ----------

FILE_LINK_RE = re.compile(r'/courses/(\d+)/files/(\d+)')


def extract_file_ids(html: str | None) -> list[str]:
    """Pull file_id values out of any /courses/<cid>/files/<fid> URLs in
    a chunk of HTML (e.g. an assignment.description body)."""
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
