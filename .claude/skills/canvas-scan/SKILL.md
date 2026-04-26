---
name: canvas-scan
description: This skill should be used when scanning Canvas for pending assignments and producing an approval-gated plan. Invoked when the user says "scan canvas", "what's due", "/canvas-scan", or similar. Reads courses.yaml, queries Canvas for assignments due in the configured pending window, buckets them by urgency, renders a plan table, writes `runs/<today>/plan.json`, and STOPS. Does NOT dispatch sub-skills — that is `canvas-execute`'s job.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - WebFetch
  - TodoWrite
---

# canvas-scan (scan + plan)

Scanner + planner for Canvas Pilot. This skill produces a **plan for user review** and then stops. Dispatch is a separate skill, `canvas-execute`, that the user invokes *after* reviewing the plan.

## Why scan and execute are split

The split makes the approval gate an **architectural boundary**, not a prose instruction:

- `canvas-scan` (this file): scan → bucket → render plan → write `plan.json` → **END**.
- `canvas-execute`: reads `plan.json` → parses user's approval → dispatches approved → writes REPORT.md.

Because the two skills are invoked in two separate Skill tool calls, there is a hard boundary between "agent proposes" and "agent acts". The user must explicitly say "go" (or "approve all", "do 1, 3, 5", etc.) before any user-defined skill runs. The file on disk is the contract.

**This skill MUST NOT:**
- Invoke any user-defined skill.
- Invoke `canvas-execute`.
- Write any `result.json`.
- Write `REPORT.md`.
- Create the `.scan_in_progress` marker (that's for execute).

## What you do

### 0. Pre-flight: handle empty courses.yaml (first-run config)

Before scanning, check `courses.yaml`. If its `routes:` section is empty or all-commented (i.e. fresh clone, never configured), this is a first-run setup. **Do NOT error out and do NOT scan with an empty route list.** Instead, follow the configuration flow described in [CLAUDE.md "Helping the student configure"](../../../CLAUDE.md):

1. Run `python -m src.canvas_client --probe` to list active courses.
2. Show the human-readable course names to the student, ask which to handle. Don't make them type or copy IDs.
3. For each chosen course, ask which skill handles it (default: `canvas-skip` for first-time setup).
4. Write `courses.yaml`'s `routes:` and update `SECRETS.md`'s `Active courses` table from the probe data.
5. Proceed with steps 1–6 below.

The student should never see "course_id" / "user_id" / "probe" or be asked to copy numbers.

### 1. Sanity check

```bash
python -m src.canvas_client --probe
```

If this fails:
- **Token mode**: token expired or network down. Tell the user the specific error and stop. Do not write `plan.json`.
- **Cookie mode**: a 401 raises `CanvasSessionExpired` with a clear message pointing back to `python -m src.canvas_login`. Surface that message to the user and stop.

### 2. Scan for pending assignments

For each `course_id` in `courses.yaml`'s `routes`, call `cv.list_assignments(course_id)` and keep items where:
- `submission.workflow_state` is NOT in `{submitted, graded}`, AND
- `due_at` is set, AND
- `due_at` is within `pending_window_days` (default 7) ahead, OR not more than 1h overdue

Write `runs/<today>/assignments.json` with the kept items. Each item: `course_id`, `course_name`, `skill` (looked up from `routes`), `assignment_id`, `name`, `due_at`, `html_url`, `submission_types`, `points_possible`.

If the list is empty, tell the user "no pending assignments in window", skip steps 3-6, and exit. No `plan.json` needed.

### 3. Filter what's already done

Two layers of dedup. Use both.

**Layer A — per-day work dirs.** For each item, check whether `runs/<today>/<course_slug>__<assignment_slug>/result.json` exists with `status` in `{draft_ready, submitted, skipped}`. If yes, skip.

**Layer B — cross-day ledger.** Read `runs/_processed.json` (a flat dict keyed by `<course_id>:<assignment_id>`). If the assignment is in there with a terminal status AND `completed_at` is more recent than `due_at - 24h`, skip.

**Exception — deferred items re-enter the plan.** If a ledger entry has `deferred_to_next_run: true`, re-include it. This is how the user's "defer N" / "skip" choices at plan-review time get another chance on the next scan.

### 4. Bucket by due_at

For each remaining item, compute `hours_left = (due_at_utc - now_utc).total_seconds() / 3600`.

Assign a bucket (first match wins):

| Bucket | Rule |
|---|---|
| OVERDUE | `hours_left <= 0` AND live Canvas `workflow_state` not in `{submitted, graded}` |
| URGENT  | `0 < hours_left <= 72` |
| SOON    | `72 < hours_left <= 168` (7 days) |
| LATER   | `hours_left > 168` |

Check live Canvas state via `cv.get_submission` only for OVERDUE candidates — for the others, ledger + assignments.json are enough.

### 5. Write plan.json + render plan table

#### 5a. plan.json

Write `runs/<today>/plan.json`:

```json
{
  "generated_at": "<ISO now>",
  "expires_at":   "<ISO now + 24h>",
  "items": [
    {
      "index": 1,
      "bucket": "urgent",
      "course_id": "12345",
      "course_name": "Course Short Label",
      "assignment_id": "67890",
      "assignment_name": "Assignment Title",
      "due_at": "2026-04-25T23:59:00Z",
      "hours_left": 53.2,
      "proposed_skill": "canvas-myskill",
      "user_decision": null
    }
  ]
}
```

- Sort by bucket priority (`overdue` → `urgent` → `soon` → `later`), then by `hours_left` ascending.
- `index` is 1-based and stable for this plan.json (users will refer to items by index: "do 1, 3, 5").
- `user_decision` starts as `null`. `canvas-execute` fills it in (`approve` / `defer` / `swap:<skill>`) during the approval parse step.
- Use atomic write (write to `.tmp`, then `os.replace`) to avoid leaving a half-written plan.

#### 5b. Plan table to user

This is the user-facing surface. Keep it terse — students reading their own plan don't need to see internals (plan.json path, the word `canvas-execute`, sub-skill names, expiry hints, bucket emojis).

Render two fixed sections — both always appear, even when empty:

- **Section 1 — Due within 3 days**: items with `hours_left <= 72`. OVERDUE items go at the top of this section with `overdue Xh` in the due column.
- **Section 2 — Due within 7 days**: items with `72 < hours_left <= 168`.

If a section has no items, render its heading with `— none` inline. Do NOT omit.

Columns (4, no truncation): `#`, Course, Assignment, Due.

- `#` — `index` from plan.json.
- Course — short label the student recognizes (the `name` in courses.yaml).
- Assignment — `assignment_name` verbatim.
- Due — local-time day-of-week + 24h time: `Mon 23:59`. Overdue: `overdue Xh` where X = `abs(hours_left)` rounded.

**Language selection**: sniff the most recent user message that triggered this scan. If it contains any Han character, use the Chinese template; otherwise English.

**English template**:

```markdown
**Due within 3 days** — none

**Due within 7 days**

| # | Course | Assignment | Due |
|---|---|---|---|
| 1 | <course label> | <assignment title> | Sun 23:59 |
| ... |

Which ones? Reply `all` to do everything, numbers to pick (e.g. `3,4`), or `skip` to pass.
```

**Chinese template**:

```markdown
**三天内 due** — 无

**七天内 due**

| # | 课 | 作业 | due |
|---|---|---|---|
| 1 | <课程简称> | <作业标题> | 周日 23:59 |
| ... |

要做哪几项？全做回"全部"，挑几项回编号（例 "3,4"），不做回"跳过"。
```

When a section has rows, drop the `— none` / `— 无` marker and render the heading + table. When empty, render only the heading with the inline marker (no empty table).

**Do NOT add to the user-facing render**:

- `plan.json` path or any other file path
- The word `canvas-execute` or any sub-skill name
- Expiry language ("valid for 24h")
- An exhaustive approval-format list beyond the one-sentence prompt
- `proposed_skill` column (it exists in plan.json for execute; users don't need it)
- Bucket emojis — section headings already carry urgency

### 6. End this turn

After printing the plan table, **STOP**. This skill is done. Do not:

- Invoke any Skill tool (no `canvas-execute`, no user-defined skill).
- Write `REPORT.md`.
- Loop back to "just execute the urgent ones since they're easy".

The user reviews the plan and replies in their next turn. Claude's next turn (based on their reply) will invoke `canvas-execute` with the approval interpretation.

## The "real source of truth" rule — most important section in this file

**Canvas's `assignment.name` and `assignment.description` are rarely the full spec.** The real spec usually lives somewhere else: an external instructor website linked from the course front page, a Files folder, a wiki page in modules, a textbook chapter referenced obliquely, an attached PDF.

**Always treat description as a routing hint, not the spec itself.** When a user-defined skill processes an assignment, it should:

1. Read `assignment.description` — but never assume it's the full spec.
2. Pull `cv.get_front_page(course_id)` and `cv.list_modules(course_id)` to find external pointers.
3. Pull `assignment.html_url` content if needed for in-page hints.
4. Walk linked references (other Canvas pages, external sites, attached files).

Where the real spec for each course lives is part of the user's `SECRETS.md` (per-quarter identifiers). The framework doesn't know — the user's skills do.

## Configuration

- `courses.yaml` — `course_id` → skill mapping. Edit when courses come and go.
- `.env` — `CANVAS_TOKEN`, `CANVAS_BASE`.
- `runs/<today>/assignments.json` — raw pending list (written by this skill).
- `runs/<today>/plan.json` — approval-gated plan (written by this skill).

## What you MUST NOT do

- Do NOT dispatch user-defined skills from this skill. That's `canvas-execute`'s job.
- Do NOT create the `.scan_in_progress` marker. Scan doesn't need it.
- Do NOT write `REPORT.md`. That happens in execute.
- Do NOT fabricate `due_at` or `workflow_state`. If Canvas API fails for an item, mark `hours_left: null` and `bucket: "unknown"` in plan.json and move on.
- Do NOT process assignments outside the configured window. `pending_window_days` in `courses.yaml` is the source of truth.
