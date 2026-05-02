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

### 0. First-run check — unconfigured repo dispatches canvas-setup or canvas-bootstrap

Before doing anything else, check the repo's setup state. Two distinct unconfigured states:

```python
import os, yaml
from pathlib import Path

env_ok = False
env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "CANVAS_BASE" and v.strip():
            env_ok = True
            break

cfg = yaml.safe_load(Path("courses.yaml").read_text(encoding="utf-8")) if Path("courses.yaml").exists() else {}
routes = (cfg or {}).get("routes") or {}
routes_nonempty = bool(routes)
```

**If `env_ok` is False** → fresh install, never configured. Dispatch `canvas-setup` via the Skill tool with this context:

> ".env is missing or CANVAS_BASE is empty — fresh install, student has never configured the project. Run the full first-run flow."

Do NOT proceed to §1. Do NOT print a traceback if `.env` doesn't exist. canvas-setup will return when the student is fully configured (or stops mid-flow). On its return, scan exits — student can re-trigger `scan canvas` whenever they want.

**Else if `env_ok` but `routes_nonempty` is False** → Canvas connection is configured but no per-course skills. Dispatch `canvas-bootstrap`:

> "courses.yaml.routes is empty — Canvas connection works but student needs to design per-course skills. Run the fingerprint flow."

When bootstrap returns, **stop this scan**. Tell the student:

> "Routes installed. Open each new SKILL.md and fill the TODOs. Then run `scan canvas` again to produce a plan."

**Else** (`env_ok` and `routes_nonempty`): proceed to §1 normally.

The student should never see "course_id" / "user_id" or be asked to copy numbers — canvas-setup and canvas-bootstrap handle that.

### 1. Sanity check

```bash
python -m src.canvas_client --probe
```

If this fails, STOP and produce a **user-facing** message — not a traceback dump, not internal vocabulary. Match the failure mode below; **CC handles the recovery, the user only answers domain questions**:

| Symptom (CC-internal) | What CC says to the user (no jargon) |
|---|---|
| `401 Unauthorized` or `Invalid access token` | "Canvas isn't accepting our credentials. Want me to open the browser so you can log in again? (That's the simplest fix — takes ~15s if Canvas remembered your device.)" — then if user says yes, CC re-runs the login flow itself. |
| `CanvasSessionExpired` raised by canvas_client | Same as above — "Canvas session expired, want me to pop the browser?" CC handles re-login itself, user just logs in. |
| `FileNotFoundError: .env` or `CANVAS_TOKEN not set` | "Looks like setup never finished — let me walk you through it." Then CC drives the first-time configure flow from `CLAUDE.md` "Helping the student configure" itself. **Do not** tell the user to copy/edit `.env` by hand. |
| `ConnectionError` / `Timeout` / DNS failure | "Can't reach Canvas right now — looks like a network issue. Check your wifi / VPN, then say 'try again' when you're back online." |
| Anything else | "Hit something I didn't expect — let me show you what came back: `{short error}`. Want me to dig in, or skip scanning for now?" |

Do NOT write `plan.json` in any of these cases — there's nothing real to plan, a half-written plan would mislead. **STOP** after printing the user-facing message.

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

#### 5b'. Recommendation block (mandatory after the tables)

The two-table render answers "what's pending" + "what's urgent". It does NOT answer "what should I do first?". Without that answer, students stare at the table not knowing how to start. Add a Recommendation block immediately after Section 2.

The block has three parts, in order:

1. **"我做不了 / Can't do"**: a small bulleted subsection listing items the framework will skip (routes to `canvas-skip`, or items the current auth mode can't handle — e.g. `online_quiz` items under `CANVAS_AUTH=cookie`). Skip the subsection entirely if the list is empty.
2. **"建议 / Suggested"**: one sentence picking ONE item as the recommended starting point — usually the most urgent item that the framework CAN do. Frame as "try this one first, see how it goes". Reasoning is optional but helpful when the choice is non-obvious.
3. **Reply hint**: keep the existing one-line `all / 编号 / skip` prompt — it stays at the end.

**Chinese template (extended example)**:

```markdown
**三天内 due** — 无

**七天内 due**

| # | 课 | 作业 | due | 已交 |
|---|---|---|---|---|
| 1 | <课> | <quiz 类作业> | 周日 23:59 | 未交 |
| 2 | <课> | <写作 HW> | 周二 23:59 | 未交 |
| 3 | <课> | <代码作业> | 周一 08:00 | 未交 |

**我做不了**
- 1. <课> <quiz 作业> — quiz 类型，cookie 模式跑不了

建议：先批 3（最紧急），看看效果。觉得 OK 再批 2。

要做哪几项？全做回"全部"，挑几项回编号（例 "3,4"），不做回"跳过"。
```

**English template (extended example)**:

```markdown
**Due within 3 days** — none

**Due within 7 days**

| # | Course | Assignment | Due | Submitted |
|---|---|---|---|---|
| 1 | <course> | <quiz item> | Sun 23:59 | no |
| 2 | <course> | <writing HW> | Tue 23:59 | no |
| 3 | <course> | <code assignment> | Mon 08:00 | no |

**Can't do**
- 1. <course> <quiz item> — quiz type, can't run under cookie auth

Suggested: try 3 first (most urgent), then come back for 2 once you see how that goes.

Which ones? Reply `all` to do everything, numbers to pick (e.g. `3,4`), or `skip` to pass.
```

Drop the `**Can't do**` subsection if it would be empty. Drop the recommendation sentence if there are zero items the framework can do (rare). The reply hint always stays.

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
