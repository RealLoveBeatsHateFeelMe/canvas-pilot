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
- Auth: `.env` selects between `CANVAS_AUTH=token` (Bearer) and `CANVAS_AUTH=cookie` (Playwright session). See [SETUP.md §1](./SETUP.md) for the decision tree.
- Configuration: `courses.yaml` (course_id → skill) and `SECRETS.md` (per-quarter identifiers). **CC populates these from probe — students don't type course IDs by hand.** See "Helping the student configure" below.
- Output: `runs/<today>/` — `plan.json`, `assignments.json`, per-assignment work dirs with `result.json`, final `REPORT.md`. Cross-day dedup ledger at `runs/_processed.json`.

---

## ⚠️ Helping the student configure (CC reads this — student doesn't)

The framework needs `courses.yaml` (course_id → skill routing) and `SECRETS.md` (per-quarter identifiers) filled in. **Don't ask the student to type course IDs.** Probe gives them for free.

**When the student first asks to scan**, OR `courses.yaml`'s `routes:` is empty/all-commented, do this **before** scanning:

1. Run `python -m src.canvas_client --probe`. Output is `<course_id> | <course_code> | <course_name>` per active course.
2. Show the student a brief list (use the human-readable course names, not raw IDs) and ask which to handle. Default: all of them.
3. For each chosen course, ask "what skill handles this?". For first-time setup, default to `canvas-skip` (the manual-todo fallback).
4. Write `courses.yaml`'s `routes:` section AND update `SECRETS.md`'s `Active courses` table from the probe output. You have all the data — name, course_code, id — already.
5. THEN proceed with `canvas-scan`.

The student should never see the words "course_id", "user_id", "probe", or be asked to copy a number from one place to another. Do it for them.

### Git hygiene the student doesn't need to think about

`.gitignore` already covers `.env`, `runs/`, `SECRETS.md`, `.cookies/`, `__pycache__/`. Trust it.

- **Never** use `git add -f`, `git add -A`, or `git add .` — they bypass or blanket-add. Use `git add <specific-paths>` only.
- **Never** edit `.gitignore` to remove a safety entry, even "just for testing".
- Before any commit, mentally check the staged file list contains only generic framework code. If unsure, run `git diff --cached` and verify silently.
- Don't tell the student to run `git status` / `git check-ignore` etc. Handle it. Mention sensitive files only if you would otherwise commit one.

---

## Critical do-nots

- Do NOT dispatch user-defined skills from `canvas-scan`. Scan produces a plan and stops; `canvas-execute` is what dispatches after the user approves. The two-skill split makes the approval gate a filesystem boundary instead of a prose instruction.
- Do NOT hardcode course IDs / file IDs / instructor info in any committed file. They go in `SECRETS.md` (gitignored).
- Do NOT leave the `.scan_in_progress` marker behind. If a run crashes, clean it up before stopping; the Stop hook will refuse to release until every assignment has a valid `result.json`.

## Pointers

- Per-user / per-quarter data: `SECRETS.md` (gitignored)
- Latest run report: `runs/<today>/REPORT.md`
- Framework skills: `.claude/skills/canvas-{scan,execute,skip}/SKILL.md`
- Framework auth: `src/canvas_client.py` (read-only API), `src/canvas_login.py` (Playwright cookie capture for `CANVAS_AUTH=cookie`)
- User-defined skills: `.claude/skills/canvas-*/` (whatever you add)

**Adding a new course mid-term?** Tell CC `design a skill` (or `设计 skill`) — this triggers `canvas-bootstrap`, which surveys recurring patterns in the new course and writes a SKILL.md skeleton + courses.yaml route entry. Same flow as the first-run setup, just on demand.
