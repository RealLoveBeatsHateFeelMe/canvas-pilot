# Canvas Pilot (project entry)

> **Read [README.md](./README.md) first for the project overview.** This file is the slim entry pointer that Claude Code auto-loads on session start. Anything substantive lives elsewhere.
>
> **First time on this machine?** The hook commands in `.claude/settings.json` need to point at *this clone's* absolute path. Run `python setup.py` once — it rewrites the `__PROJECT_ROOT__` placeholder. Without that, hooks silently no-op (the system *looks* like it's working but safety checks aren't running). Full bootstrap: [SETUP.md](./SETUP.md).

This file is loaded automatically when CC starts a session in this directory. Keep it small. Per-user / per-quarter identifiers (course IDs, file IDs, instructor info) belong in **[SECRETS.md](./SECRETS.md)** which is gitignored — never hardcode them here or in any committed SKILL.md.

---

## ⚠️ THE CORE RULE: assignment.description is rarely the real spec

**Canvas's `assignment.name` and `assignment.description` are routing hints, not specs.** For most STEM courses they're empty strings. For most non-STEM courses they're a paragraph that doesn't tell you what to actually produce. The real spec usually lives somewhere else:

- An external instructor website linked from the course front page
- A reading PDF in a course Files folder
- A wiki page in modules
- A textbook chapter referenced obliquely
- An attached PDF on the assignment itself

**Before any user-defined skill processes an assignment, it should:**

1. Read `assignment.description` — but treat it as a hint, not the full spec.
2. Pull `cv.get_front_page(course_id)` to find external pointers.
3. Pull `cv.list_modules(course_id)` to find reading material / wiki pages.
4. Walk linked references (other Canvas pages, external URLs, attached files).

Where the real spec for each course lives belongs in `SECRETS.md`, indexed by course. Once you've discovered it, write it down — the next session shouldn't have to rediscover.

The framework's `canvas-scan` skill already encodes this rule in its long-form documentation. User-defined skills should follow the same discipline.

---

## Quick orientation

- This project routes recurring Canvas assignments to user-written skills. The framework ships scaffolding (scan + execute + skip) but no course-specific skills.
- Trigger: in a CC session from this directory, say `scan canvas` or `/canvas-scan`. CC invokes the scan skill, lists pending, stops. Reply with `all` / numbers / `skip` to dispatch. See `.claude/skills/canvas-scan/SKILL.md` and `canvas-execute/SKILL.md` for the full contract.
- Configuration: `courses.yaml` (course_id → skill). `.env` (`CANVAS_TOKEN` + `CANVAS_BASE`). `SECRETS.md` (per-quarter identifiers your skills reference).
- Output: `runs/<today>/` — `plan.json`, `assignments.json`, per-assignment work dirs with `result.json`, final `REPORT.md`. Cross-day dedup ledger at `runs/_processed.json`.

## Critical do-nots

- Do NOT submit anything to Canvas from the framework. The Canvas API client is read-only by design — there are no `submit_*` or `upload_*` helpers. If a user-defined skill wants to submit, that's its choice and its responsibility.
- Do NOT dispatch user-defined skills from `canvas-scan`. Scan produces a plan and stops; `canvas-execute` is what dispatches after the user approves. The two-skill split makes the approval gate a filesystem boundary instead of a prose instruction.
- Do NOT commit `.env`, `runs/`, `SECRETS.md`, or any draft to git. `.gitignore` enforces this — verify with `git status` before any commit.
- Do NOT hardcode course IDs / file IDs / instructor info in any committed file. They go in `SECRETS.md`.
- Do NOT leave the `.scan_in_progress` marker behind. If a run crashes, clean it up before stopping; the Stop hook will refuse to release until every assignment has a valid `result.json`.

## Pointers

- Per-user / per-quarter data: `SECRETS.md` (gitignored)
- Latest run report: `runs/<today>/REPORT.md`
- Framework skills: `.claude/skills/canvas-{scan,execute,skip}/SKILL.md`
- User-defined skills: `.claude/skills/canvas-*/` (whatever you add)
