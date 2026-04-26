# SETUP — first run on a fresh clone

Bootstrap walkthrough. Five steps, ~5 minutes.

Assumptions: you have [Claude Code](https://claude.com/claude-code) installed and Python 3.11+. The hook scripts under `.claude/hooks/` use only stdlib + cross-platform path handling, so macOS/Linux work alongside Windows.

---

## 1. Get a Canvas API token

In your Canvas instance, click your avatar (top-left) → **Settings** → scroll to **Approved Integrations** → **+ New Access Token**. Name it whatever (e.g. `canvas-pilot`). Copy the token — you only see it once.

## 2. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in:

- `CANVAS_TOKEN` — your token from step 1
- `CANVAS_BASE` — your school's Canvas API base. Default is `https://canvas.instructure.com/api/v1`; change to `https://canvas.<school>.edu/api/v1` if your school self-hosts.

## 3. Install deps + rewrite paths

```bash
pip install requests pyyaml
python setup.py
```

`setup.py` auto-detects where you cloned the repo and replaces the `__PROJECT_ROOT__` placeholder in `.claude/settings.json` so hook commands work. Idempotent — safe to re-run.

> Don't commit the resulting `.claude/settings.json` back upstream — it now contains your local path. `git diff` shows exactly what got rewritten.

## 4. Probe Canvas, then configure `courses.yaml` + `SECRETS.md`

This is where you tell the framework which courses to scan. **Don't go look up course IDs by hand** — Canvas gives them to you for free:

```bash
python -m src.canvas_client --probe
```

Output looks like:

```
OK Canvas user: Your Name (id=12345678)
4 active courses:
  82062 | AC-ENG-20A | Academic English 20A
  81271 | ICS-33    | Programming in Python
  81489 | INTL-101  | Intro to Global Studies
  82257 | MATH-2B   | Calculus
```

That's everything you need. From this output:

- The `id=...` after your name is your Canvas `user_id` — paste it into `SECRETS.md` (after `cp SECRETS.example.md SECRETS.md`).
- The course list gives you all the IDs and short codes. Pick the courses you want the framework to scan and add them to `courses.yaml`:

  ```yaml
  routes:
    81271:
      name: "ICS 33"           # any short label you like
      skill: canvas-skip       # see note below
    81489:
      name: "INTL 101"
      skill: canvas-skip
  pending_window_days: 7
  ```

**About the `skill` field**: the framework ships with `canvas-scan`, `canvas-execute`, and `canvas-skip` — but **no course-specific skills**. For the first run, route every course to `canvas-skip` (the generic "log to todo.md" fallback). That's enough to verify the framework end-to-end. Then read [README.md § How to write your own skill](./README.md#how-to-write-your-own-skill) and replace `canvas-skip` with your own skill names as you author them.

> If you're letting Claude Code do this setup interactively, you can hand it your token + Canvas domain and it will run probe, present the course list, and ask you which to include before writing the files. Don't let it ask you for course IDs by hand — that's what probe is for.

## 5. Test

Open this folder in Claude Code (`claude` from the repo root). When the session starts, the SessionStart hook injects context so CC knows it's in a Canvas Pilot project. Then say:

```
scan canvas
```

CC invokes `canvas-scan`, hits Canvas with your token, and produces:

- `runs/<today>/assignments.json` — raw pending list
- `runs/<today>/plan.json` — bucketed plan
- A markdown table in the chat showing what's pending

**It stops there — nothing is dispatched.** Review the plan; reply with approval (e.g. `all`, `1, 3, 5`, `urgent only`, `skip`) to invoke `canvas-execute`, which routes each approved item to its skill.

If `scan canvas` doesn't trigger the skill: type `/canvas-scan` explicitly. If hooks aren't firing (no SessionStart context message at the top), re-check that `python setup.py` actually rewrote `.claude/settings.json` (look for any remaining `__PROJECT_ROOT__` strings).

---

## Alternative auth: Playwright cookie path

Use this if your school **disallows students from self-issuing personal access
tokens**. The repo can read Canvas via the same browser session you use
day-to-day, captured once via Playwright. The framework (`canvas-scan` /
`canvas-execute` / `canvas-skip`) works identically under both modes.

### One-time setup

```bash
pip install playwright
python -m playwright install chromium
```

### `.env` for cookie mode

```
CANVAS_AUTH=cookie
CANVAS_BASE=https://<your-school>.instructure.com/api/v1
CANVAS_WEB_BASE=https://<your-school>.instructure.com
# CANVAS_TOKEN not needed
```

### Capture cookies (run any time the session expires, ~1/day)

```bash
python -m src.canvas_login
```

A Chromium window opens at your school's Canvas login. **Complete SSO + 2FA
manually** (the script intentionally doesn't try to drive school-specific SSO
forms — they're all different). Once you see the Dashboard, return to the
terminal and press Enter. The script writes `.cookies/canvas_session.json`
(gitignored) containing the session cookie + a URL-unquoted CSRF token.

### Verify

```bash
CANVAS_AUTH=cookie python -m src.canvas_client --probe
```

Should print your name + course list, identical to token-mode output.

### When cookie expires

The client raises `CanvasSessionExpired` on the first 401 with a clear message
pointing back to `python -m src.canvas_login`. Re-run that command to refresh
the cookie and continue.

### Caveats for skills that submit

This framework's `canvas_client` is read-only — submission code lives in
whatever skills you author. If a skill of yours uses cookie auth to POST to
Canvas, remember:

- Cookie sessions expire (~1 day) — handle the `CanvasSessionExpired`
  exception (or its 401 root cause) and tell the user to re-login.
- Canvas POST endpoints generally require the `X-CSRF-Token` header. The
  client sets it as a default session header, so any `requests` call that
  reuses `_session` carries it automatically.
- For Canvas's 3-step file upload, do NOT send the session cookie to the
  S3-style upload URL in step 2 (use a fresh `requests.post` without the
  shared session for that one call).

---

## Troubleshooting

**`setup.py` says "no placeholder" everywhere.** Either you already ran it, or your clone was rewritten by someone else on a different machine and they pushed the change. Check `git diff .claude/settings.json` — if the path inside isn't `__PROJECT_ROOT__` and isn't yours either, fix manually.

**Hooks don't fire.** Open `.claude/settings.json`, confirm every `command` field has your absolute path, and that the `.claude/hooks/*.py` files exist. Try `python .claude/hooks/inject-context.py` manually — if it crashes, fix the import / path issue before re-running CC.

**`CANVAS_TOKEN not set` from `canvas_client.py`.** `.env` not loaded. Make sure you copied `.env.example` to `.env` (not just edited the example) and that the token line is `CANVAS_TOKEN=...` with no quotes around the value.

**`raise_for_status()` 401 on probe.** Token is wrong or expired, or `CANVAS_BASE` doesn't match your school's host. Test with `curl -H "Authorization: Bearer $TOKEN" $CANVAS_BASE/users/self`.

**Stop hook keeps blocking session end.** It's enforcing the "every assignment has a result.json" gate. Either finish the dispatch (re-invoke `canvas-execute`), or write `result.json` files manually with `status: skipped, deferred_to_next_run: true, notes: "<reason>"` for the items you don't want to handle this run. As a last resort, delete `runs/<today>/.scan_in_progress` to disarm the gate (fine if you're cleaning up, bad if you have unfinished real work).

**Different OS.** The hook commands in `.claude/settings.json` use `python` (not `python3`). On macOS/Linux you may need to `ln -s $(which python3) /usr/local/bin/python` or hand-edit settings.json. The scripts themselves are platform-independent.
