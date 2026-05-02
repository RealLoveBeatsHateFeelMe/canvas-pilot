# Canvas Pilot (project entry)

> **Read [README.md](./README.md) first for the project overview.** This file is the slim entry pointer that Claude Code auto-loads on session start. Anything substantive lives elsewhere.
>
> **First time on this machine?** Open Claude Code in this folder and tell it what you want done — CC walks first-time users through setup via the `canvas-setup` skill. Hook paths use `${CLAUDE_PROJECT_DIR}` so they work regardless of clone location. Developers who want manual control: see [SETUP.md](./SETUP.md).

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
- Configuration: `courses.yaml` (course_id → skill) and `SECRETS.md` (per-quarter identifiers). **CC populates these from probe — students don't type course IDs by hand.** First-run flow lives in [.claude/skills/canvas-setup/SKILL.md](./.claude/skills/canvas-setup/SKILL.md).
- Output: `runs/<today>/` — `plan.json`, `assignments.json`, per-assignment work dirs with `result.json`, final `REPORT.md`. Cross-day dedup ledger at `runs/_processed.json`.

---

## First-run setup is a skill, not a prose script

If the student arrives unconfigured (no `.env`, or `courses.yaml.routes` empty), **dispatch the `canvas-setup` skill** via the Skill tool. Do not improvise a setup conversation; do not read `SETUP.md` to them; do not ask them to edit files or run commands.

`canvas-setup` is a deterministic N-step script: open with value → get Canvas URL → offer A/B path (default A browser-login) → silently install browser components → silently write config → trigger one browser login → silently list active courses → ask which to track → silently write routes → hand off to `canvas-bootstrap` for per-course skill design. The student answers ~3 domain questions and logs into Canvas once; everything else is CC's silent action with `Bash` / `Edit` / `Write`.

`canvas-scan` §0 also dispatches `canvas-setup` automatically when it detects unconfigured state, so a student can also just say "scan canvas" on a fresh clone and land in the right flow.

If you find yourself writing a setup conversation outside the skill — telling the student to "open .env", "go to Canvas → Account → Settings", "run pip install", "copy this command into your terminal" — stop. That is the failure mode the skill exists to prevent. Read `.claude/skills/canvas-setup/SKILL.md` and follow it.

<!-- The legacy A-E blacklist/whitelist/dialog-pinning ruleset that used to live here is now the contract enforced by canvas-setup SKILL.md. Decision points (plan output, bootstrap fingerprint, execute report) are owned by their respective SKILL.md files: canvas-scan §5b, canvas-bootstrap §2b, canvas-execute §9. -->

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
