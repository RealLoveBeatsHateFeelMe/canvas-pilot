# SETUP — first run on a fresh clone

Bootstrap walkthrough. ~5 min for token mode, ~10 min for cookie mode (first run; ~15 sec subsequent runs).

Assumptions: [Claude Code](https://claude.com/claude-code) installed, Python 3.11+. The hook scripts under `.claude/hooks/` use only stdlib + cross-platform path handling, so macOS / Linux / Windows all work.

---

## 1. Choose your auth mode (do this first)

In your Canvas instance:

1. Click your avatar (top-left) → **Settings**
2. Scroll to **Approved Integrations**
3. Look at the **+ New Access Token** button.

| What you see | What it means | Go to |
|---|---|---|
| Button is clickable, lets you generate a token | Your school allows self-issued tokens | **§2A — Token mode** |
| Button is missing, greyed out, errors with "permission denied", or generated tokens get auto-revoked | Your school disabled student-issued tokens (common at some private universities, K-12 districts, schools enforcing OAuth-only) | **§2B — Cookie mode** |

Both modes give you the same `canvas-scan` / `canvas-execute` framework. The trade-offs:

| | Token | Cookie |
|---|---|---|
| Setup time | 1 min | 5–10 min first run, ~15 sec/day after |
| Auth lifetime | ~1 year | ~24 h (re-login daily; ~15 sec with persistent profile) |
| Browser dependency | None | Headless Chromium (~150 MB, one-time install) |

---

## 2A. Token mode

Click **+ New Access Token**. Name it whatever (e.g. `canvas-pilot`). **Copy the token now — Canvas only shows it once.**

```bash
cp .env.example .env
```

Edit `.env`:

```
CANVAS_AUTH=token
CANVAS_TOKEN=<paste-here>
CANVAS_BASE=https://canvas.<your-school>.edu/api/v1
```

If your school uses a generic Canvas-cloud host, `CANVAS_BASE` looks like `https://<school>.instructure.com/api/v1` instead — check the URL bar when you're in Canvas.

Continue to §3.

---

## 2B. Cookie mode

Install Playwright + a Chromium binary (one-time, ~150 MB):

```bash
pip install playwright
python -m playwright install chromium
```

```bash
cp .env.example .env
```

Edit `.env`:

```
CANVAS_AUTH=cookie
CANVAS_BASE=https://canvas.<your-school>.edu/api/v1
CANVAS_WEB_BASE=https://canvas.<your-school>.edu
# CANVAS_TOKEN unused — leave blank or remove the line.
```

Capture your first cookie:

```bash
python -m src.canvas_login
```

A Chromium window opens at your school's Canvas login. **First run** (full SSO + 2FA expected):

1. Log in normally (school username, password)
2. Complete 2FA (Duo push / Microsoft Authenticator / etc.)
3. Wait until your Canvas Dashboard appears
4. Switch to the terminal and **press Enter** — that signals "I'm logged in, capture cookies now". The script then visits `/profile/settings` to refresh the CSRF token, reads the relevant cookies, writes them to `.cookies/canvas_session.json`, and saves the browser profile under `.cookies/playwright-profile/`.

> **Optional convenience**: if the 2FA page has a "Remember this device" / "Trust this browser" / "Don't ask again" checkbox, ticking it (before approving) lets subsequent runs skip 2FA for some window — typically 30 days. **It's optional, not required.** Without it, you just do full 2FA every time the Canvas cookie expires (~daily). Same functionality either way.

Both `.cookies/canvas_session.json` and `.cookies/playwright-profile/` are gitignored.

**Subsequent runs** (Canvas session cookie expires every ~24 h): same command, `python -m src.canvas_login`.

- If you ticked "Remember device" on first run: browser auto-redirects through SSO, no 2FA push, you press Enter. **~15 seconds.**
- If you didn't tick (or your school doesn't offer the option): full ceremony again — username, password, 2FA push, Approve, Enter. **~5 minutes.** Functionally identical, just slower.

**When the remember-device window expires** (typically 30 days for Duo): full ceremony anyway. Re-tick if you want another 30 days of fast logins.

**If something gets wedged** (corrupt profile, mysterious login loop): `rm -rf .cookies/playwright-profile/`. One full SSO and you're back.

Continue to §3.

---

## 3. Let Claude Code populate your config

```bash
cp SECRETS.example.md SECRETS.md
```

That's the only manual step. **Don't look up your course IDs by hand** — Claude Code will fill in `courses.yaml` and the `Active courses` table in `SECRETS.md` for you on first scan (§6). It runs `python -m src.canvas_client --probe`, lists your courses by name, asks which to handle, and writes the entries.

If you want to do it manually anyway, the schema is documented in `SECRETS.example.md` and `courses.yaml`.

## 4. Rewrite hardcoded paths

```bash
python setup.py
```

`setup.py` rewrites the `__PROJECT_ROOT__` placeholder in `.claude/settings.json` so hook commands point at the right files for your local clone. Idempotent — safe to re-run.

> Don't commit the resulting changes — they're machine-local. `git diff` after `setup.py` shows exactly what got rewritten.

## 5. Install Python deps

```bash
pip install requests
```

That's the only hard dependency for the framework. Add others as your own skills need them (e.g. `pyyaml` for richer YAML manipulation, `pymupdf` if a skill parses PDFs). Cookie-mode users already installed `playwright` in §2B.

## 6. Test

In Claude Code (`claude` from the repo root):

```
scan canvas
```

If `courses.yaml` is still empty (first run), CC asks which courses to handle and writes the config for you — you don't type IDs. Then `canvas-scan` produces `runs/<today>/plan.json` plus a markdown table of pending work. **It stops there — nothing is dispatched until you approve.** Reply with (`all` / `1, 3, 5` / `urgent only` / `skip`) to trigger `canvas-execute`.

If `scan canvas` doesn't trigger the skill, type `/canvas-scan` explicitly. If hooks aren't firing (no SessionStart context message at the top), re-check that `python setup.py` actually rewrote `.claude/settings.json`.

---

## Troubleshooting

**`setup.py` says "no placeholder" everywhere.** Either you already ran it, or your clone was rewritten by someone else on a different machine and they pushed the change. Check `git diff .claude/settings.json` — if the path inside isn't `__PROJECT_ROOT__` and isn't yours either, fix manually.

**Hooks don't fire.** Open `.claude/settings.json`, confirm every `command` field has your absolute path, and that the `.claude/hooks/*.py` files exist. Try `python .claude/hooks/inject-context.py` manually — if it crashes, fix the import / path issue before re-running CC.

**`CANVAS_TOKEN not set`** in token mode. `.env` not loaded, or you set `CANVAS_AUTH=token` but didn't paste the token. Make sure you copied `.env.example` to `.env` (not just edited the example) and the token line has no quotes around the value.

**`CanvasSessionExpired`** from cookie mode. The Canvas session cookie expired (typically ~24 h). Re-run `python -m src.canvas_login`.

**Cookie capture fails (`_normandy_session cookie not found`).** Login probably didn't reach Dashboard before you hit Enter, or the SSO chain stalled. Check the browser — make sure you're at the actual Canvas Dashboard URL (e.g. `canvas.<your-school>.edu/?login_success=1`) before pressing Enter. If the SSO loop won't complete, delete `.cookies/playwright-profile/` and try again.

**`raise_for_status()` 401 on probe.** Token is wrong/expired (token mode), or the cookie file's session value got invalidated server-side (cookie mode). Token: regenerate in Approved Integrations. Cookie: re-run `canvas_login`.

**Different OS.** The hook commands in `.claude/settings.json` use `python` (not `python3`). On macOS/Linux you may need to symlink `python` → `python3` or hand-edit settings.json. The scripts themselves are platform-independent.
