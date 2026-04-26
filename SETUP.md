# SETUP — first run on a fresh clone

Bootstrap walkthrough. Six steps, ~10 minutes including filling in your courses.

Assumptions: you have [Claude Code](https://claude.com/claude-code) installed and Python 3.11+. The hook scripts under `.claude/hooks/` are written for Windows but use only stdlib + cross-platform path handling, so macOS/Linux should work too.

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

## 3. Configure `SECRETS.md`

```bash
cp SECRETS.example.md SECRETS.md
```

Open `SECRETS.md` and fill in at minimum:

- Your Canvas user_id (run `python -m src.canvas_client --probe` after step 4 to find it).
- A row in the **Active courses** table for each course you want the framework to scan. Each row needs `course_id`, name, and `skill` (the skill name from `.claude/skills/canvas-*/`).

The other sections (per-course details) can stay as templates until you actually need them — they're useful as a paste-target when you discover the real spec location for a course.

## 4. Rewrite hardcoded paths

The hook commands in `.claude/settings.json` need absolute paths to this clone's location. Run:

```bash
python setup.py
```

It auto-detects where you cloned the repo and replaces the `__PROJECT_ROOT__` placeholder. Idempotent — safe to re-run.

> Don't commit the resulting changes back to upstream — they're machine-local. `git diff .claude/settings.json` shows exactly what got rewritten if you want to verify.

## 5. Install Python deps

```bash
pip install requests pyyaml
```

That's it for the framework's own deps. If you write skills that need more (e.g. PyMuPDF for PDF work, requests-html for scraping), `pip install` them as needed.

## 6. Configure your courses

Edit `courses.yaml`. Each entry maps a course_id to a skill:

```yaml
routes:
  12345:
    name: "Course Short Label"
    skill: canvas-mycode
pending_window_days: 7
```

The skill names you reference here must correspond to skills under `.claude/skills/canvas-*/SKILL.md`. The framework ships with `canvas-scan`, `canvas-execute`, and `canvas-skip` (a generic "log to todo" fallback), but **no course-specific skills**. You write those yourself — see [README.md § How to write your own skill](./README.md#how-to-write-your-own-skill).

If you don't have any skills yet, route everything to `canvas-skip` for the first run. The framework will scan, list what's pending, and on approval log them to `runs/<today>/todo.md` so you can do them by hand. That's enough to verify the framework is working end-to-end before you commit to writing skills.

## Test

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

## Troubleshooting

**`setup.py` says "no placeholder" everywhere.** Either you already ran it, or your clone was rewritten by someone else on a different machine and they pushed the change. Check `git diff .claude/settings.json` — if the path inside isn't `__PROJECT_ROOT__` and isn't yours either, fix manually.

**Hooks don't fire.** Open `.claude/settings.json`, confirm every `command` field has your absolute path, and that the `.claude/hooks/*.py` files exist. Try `python .claude/hooks/inject-context.py` manually — if it crashes, fix the import / path issue before re-running CC.

**`CANVAS_TOKEN not set` from `canvas_client.py`.** `.env` not loaded. Make sure you copied `.env.example` to `.env` (not just edited the example) and that the token line is `CANVAS_TOKEN=...` with no quotes around the value.

**`raise_for_status()` 401 on probe.** Token is wrong or expired, or `CANVAS_BASE` doesn't match your school's host. Test with `curl -H "Authorization: Bearer $TOKEN" $CANVAS_BASE/users/self`.

**Stop hook keeps blocking session end.** It's enforcing the "every assignment has a result.json" gate. Either finish the dispatch (re-invoke `canvas-execute`), or write `result.json` files manually with `status: skipped, deferred_to_next_run: true, notes: "<reason>"` for the items you don't want to handle this run. As a last resort, delete `runs/<today>/.scan_in_progress` to disarm the gate (fine if you're cleaning up, bad if you have unfinished real work).

**Different OS.** The hook commands in `.claude/settings.json` use `python` (not `python3`). On macOS/Linux you may need to `ln -s $(which python3) /usr/local/bin/python` or hand-edit settings.json. The scripts themselves are platform-independent.
