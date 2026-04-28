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
| Setup time | 1 min | 5–10 min first run, ~15 sec/day after — and the renewal is **automatic**, you never run a login command, the browser just pops up on its own when scan needs it |
| Auth lifetime | ~1 year | ~24 h, transparently renewed by `scan canvas` |
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

That's it for setup. **You don't run any login command.** The first time you say `scan canvas` (§6 below), `canvas_client` notices there's no cookie file yet, opens a Chromium window automatically, and waits for you to log in:

1. Log in normally in the browser (school username, password)
2. Complete 2FA (Duo push / Microsoft Authenticator / etc.)
3. Wait until your Canvas Dashboard appears

The window then closes itself, the cookies get written to `.cookies/canvas_session.json`, and `scan canvas` continues. **First run is ~5 minutes** (full SSO + 2FA). After that, the persistent browser profile under `.cookies/playwright-profile/` makes renewal ~15 seconds — every subsequent time the cookie expires (~24h), `scan canvas` pops the browser, you watch it auto-redirect through SSO, the window closes, scan continues.

> **Strongly recommended on first run**: when 2FA shows a "Remember this device" / "Trust this browser" / "Don't ask again" checkbox, **tick it before approving**. That lets subsequent renewals skip the 2FA push for the trust window (typically 30 days) — making them ~15s instead of ~5min. Without it, you re-do full 2FA every cookie expiry.

Both `.cookies/canvas_session.json` and `.cookies/playwright-profile/` are gitignored.

**When the remember-device window expires** (typically 30 days for Duo): the next renewal goes through full 2FA anyway. Re-tick if you want another 30 days of fast logins.

**If something gets wedged** (corrupt profile, mysterious login loop): `rm -rf .cookies/playwright-profile/`. The next `scan canvas` will trigger a fresh full SSO.

**Disabling auto-relogin** (debugging only): set `CANVAS_NO_AUTO_RELOGIN=1` in `.env`. With this on, a missing/expired cookie raises `CanvasSessionExpired` instead of opening the browser, and you can manually run `python -m src.canvas_login --manual` if you want the legacy press-Enter flow.

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

**`CanvasSessionExpired`** from cookie mode. Auto-relogin failed or is disabled. Either `CANVAS_NO_AUTO_RELOGIN=1` is set in `.env` (remove it), or the auto-relogin subprocess hit a 5-minute timeout because login wasn't completed in the browser. Re-run scan; if it persists, try `python -m src.canvas_login --manual` to debug interactively.

**Cookie capture fails (`_normandy_session cookie not found`).** The browser closed before SSO finished setting the session cookie. In auto mode the script polls every 1.5s and closes as soon as `_normandy_session` appears, so this almost always means the SSO chain stalled at an IDP page. Run `python -m src.canvas_login --manual` to drive it manually and watch where it hangs. If the profile is the problem, `rm -rf .cookies/playwright-profile/` and retry.

**`raise_for_status()` 401 on probe.** Token mode: token is wrong/expired — regenerate in Approved Integrations. Cookie mode: should not happen normally — `_request_with_relogin` retries 401 once after auto-relogin. If you still see this, auto-relogin is failing silently. Run `python -m src.canvas_login --manual` and check its exit code.

**Different OS.** The hook commands in `.claude/settings.json` use `python` (not `python3`). On macOS/Linux you may need to symlink `python` → `python3` or hand-edit settings.json. The scripts themselves are platform-independent.
