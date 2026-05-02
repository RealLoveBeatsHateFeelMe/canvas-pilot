---
name: canvas-execute
description: This skill should be used when executing an already-scanned Canvas plan after the user has approved it. Invoked after `canvas-scan` wrote `runs/<today>/plan.json` and the user replied with approval like "approve all", "do 1, 3, 5", "urgent only", "defer N", "skip", "cancel". Parses the approval, updates plan.json with per-item decisions, dispatches approved items to the user-defined skills (whatever the user wrote under `.claude/skills/canvas-*/`), writes skipped+deferred result.json for non-approved items, then produces REPORT.md.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - WebFetch
  - Skill
  - TodoWrite
---

# canvas-execute (approval-gated dispatch)

Dispatcher for Canvas Pilot. This skill is the **execute** half of the scan/execute split — it runs only after `canvas-scan` has produced a plan and the user has explicitly approved some subset of it.

## The contract with canvas-scan

- `canvas-scan` wrote `runs/<today>/plan.json` with every pending item at `user_decision: null`.
- The user reviewed the plan (printed as a markdown table in the previous turn) and replied with an approval spec.
- Claude (the outer orchestrator) parsed the user's reply and invoked this skill with the approval interpretation as context.

**This skill's job**: apply the approval to plan.json, dispatch the approved items to the user's skills, record the non-approved ones as deferred, finalize.

**If `plan.json` doesn't exist or is >24h old → STOP and tell the user to run `/canvas-scan` first.** Do not invent a plan, do not dispatch anything, do not guess.

The framework's contract: dispatch, record `result.json`, finalize. Skills produce a draft and write `result.json` with `status: draft_ready` and a `draft_path`.

## What you do

### 0. Precondition check

```bash
TODAY=$(date +%Y-%m-%d)
test -f "runs/$TODAY/plan.json" || { echo "NO_PLAN"; exit 1; }
test -f "runs/$TODAY/assignments.json" || { echo "NO_ASSIGNMENTS"; exit 1; }
```

If either is missing: tell the user "No plan.json for today. Run `/canvas-scan` first to generate a plan, review it, then come back." Stop. Do NOT run scan inline — that defeats the approval gate.

Then check freshness:

```python
import json, datetime as dt
from pathlib import Path
plan = json.loads(Path(f"runs/{today}/plan.json").read_text(encoding="utf-8"))
expires = dt.datetime.fromisoformat(plan["expires_at"])
now = dt.datetime.now(expires.tzinfo)
if now > expires:
    # tell user: "Plan is stale (>24h). Re-run /canvas-scan before executing."
    pass
```

If expired: STOP. Tell user to rerun `/canvas-scan`.

### 1. Handle stale marker from a prior crashed session

Before activating your own marker, glob `runs/*/.scan_in_progress`. For each match whose date is **not today**:

- Read that day's `assignments.json`.
- For any assignment lacking a `result.json`, write `{status: "skipped", notes: "session crashed before this item was processed", deferred_to_next_run: true}`.
- Delete the orphan marker.

This keeps the Stop hook from being permanently wedged by a past crash.

### 2. Activate today's marker

```bash
mkdir -p "runs/$TODAY"
touch "runs/$TODAY/.scan_in_progress"
```

This arms the Stop hook (`check-router-complete.py`). Every assignment in `runs/$TODAY/assignments.json` must now have a matching `result.json` before this session can stop.

### 3. Parse user's approval + update plan.json

Read the user's approval spec — either passed in as context when Claude invoked this skill, or visible in the preceding turn.

Recognize these patterns:

| User says | Interpretation |
|---|---|
| `all` / `approve all` / `全部` / `全部批准` / `批准全部` | every item → `approve` |
| `urgent only` / `只做 urgent` / `只做紧急` | items with `bucket: urgent` → `approve`, rest → `defer` |
| `1, 3, 5` / `do 1 3 5` / `做 1 3 5` | listed indices → `approve`, rest → `defer` |
| `1-4` / `1 to 4` / `1 到 4` | index range → `approve`, rest → `defer` |
| `swap N to canvas-X` / `第 N 项用 canvas-X` | item N → `swap:canvas-X` (still approved, different skill) |
| `defer N` / `第 N 项 defer` / `skip N` | item N → `defer` |
| `cancel` / `取消` | every item → `defer` (nothing dispatched) |
| User picks some, silent on others (e.g. `1, 3` with 5 items total) | unmentioned indices → `defer` (safer than auto-executing) |

**Ambiguous or unparseable input → STOP and ask once.** Do not guess. Example ambiguous: "do the first few" (how many?). Answer: "Please clarify — items 1, 2, 3?" and wait.

Update plan.json atomically:

```python
import json, os
from pathlib import Path
plan_path = Path(f"runs/{today}/plan.json")
plan = json.loads(plan_path.read_text(encoding="utf-8"))
for item in plan["items"]:
    item["user_decision"] = determine_decision(item)  # "approve" | "defer" | "swap:canvas-X"
tmp = plan_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
os.replace(tmp, plan_path)
```

### 4. Dispatch approved items — one at a time, in order

For each item in plan.json where `user_decision == "approve"` or starts with `"swap:"`, process sequentially (plan.json items are already sorted earliest-due-first).

For each item:

1. Determine which skill to invoke:
   - `user_decision == "approve"` → `proposed_skill`
   - `user_decision == "swap:canvas-X"` → `canvas-X`

2. **TodoWrite**: add the assignment as a todo, mark `in_progress`.

3. **Invoke via the Skill tool**. Pass a brief context line:
   > "Work on `<assignment_name>` (course `<course_name>`). Work dir: `runs/<today>/<work_dir>`. See `assignments.json` and `plan.json` for full item details."

4. Sub-skill runs → writes its own `result.json` → returns.

5. Read the `result.json`. Mark todo `completed` (or keep `in_progress` with an error note if `status: error`).

6. Update `runs/_processed.json` ledger (atomic write):
   ```python
   ledger[f"{course_id}:{assignment_id}"] = {
       "status": sub_result["status"],
       "course_name": item["course_name"],
       "assignment_name": item["assignment_name"],
       "due_at": item["due_at"],
       "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
       "draft_path": sub_result.get("draft_path"),
       "notes": sub_result.get("notes"),
       "deferred_to_next_run": False,
   }
   ```

7. Continue to the next approved item.

Run items **sequentially** — Canvas reads can race, and sequential logs are easier to debug.

**If the Skill tool reports the target skill is not discoverable**, STOP and print a clear error ("skill `canvas-X` not found; check `.claude/skills/canvas-X/SKILL.md` exists"). Do NOT try to do the work inline.

### 5. Pause when the session is running tight

Claude judges its own context budget. If roughly less than ~15 turns of capacity remain AND there are still approved items left to dispatch, **break out of the loop** instead of trying to squeeze in another heavy item. Half-finished work is worse than deferred work.

To pause cleanly (the Stop hook requires every `assignments.json` item to have a `result.json`):

1. For each remaining undispatched approved item, write a placeholder `result.json`:
   ```json
   {
     "assignment_id": "...",
     "course_id": "...",
     "status": "skipped",
     "notes": "paused mid-run — awaiting user decision (continue or defer)",
     "deferred_to_next_run": true
   }
   ```
   Also update `_processed.json` with `deferred_to_next_run: true`.

2. **Print a clear status to the user**:

   ```
   Done so far:
   - #1 Assignment A — draft_ready (runs/.../a.json)
   - #2 Assignment B — draft_ready (runs/.../b.json)

   Not done yet (session running tight):
   - #3 Assignment C
   - #4 Assignment D

   Continue?
   - "continue" / "yes" → I'll keep going from #3
   - "defer" / "skip" / silence → remaining stay deferred, will resurface on next /canvas-scan
   ```

3. End your turn. Do NOT proceed to §6 finalize yet — wait for the user's reply.

4. On the user's next turn:
   - **continue** → go back to §4 and dispatch the next undispatched item. Each successful sub-skill completion **overwrites** the placeholder `result.json`. Repeat §5 pause-check as you go.
   - **defer / skip / silence / anything not a clear continue** → jump to §6 finalize. Placeholder `result.json` files stay as the final state.

### 6. Finalize

Reach this section via one of two paths:

- **Happy path**: §4 loop completed all approved items.
- **Defer path**: user replied "defer" / silence after §5's pause-and-ask.

Steps:

1. **Write deferred `result.json` for items not yet written**:
   - `user_decision == "defer"` (explicitly declined) — if their `result.json` doesn't already exist, write `{status: "skipped", notes: "user declined at plan review", deferred_to_next_run: true}`.
   - `user_decision == null` (user silent on this index at approval time) — same.
   - Placeholder-paused items from §5 are already written, skip.

2. **Update `runs/_processed.json` ledger** for every item processed this run.

3. **Write `runs/<today>/REPORT.md`** (see §7 for urgent banner + §8 for layout).

4. **Remove marker**: `rm "runs/$TODAY/.scan_in_progress"`. Pair with §2's `touch`. If you skip this step, the next session in this directory is gated.

### 7. Urgent banner at top of REPORT.md

Compute urgency for EVERY item in `assignments.json` (whether approved, deferred, or already done):

```python
import json, datetime as dt
from pathlib import Path
from src import canvas_client as cv

now = dt.datetime.now(dt.timezone.utc)
ledger = json.loads(Path("runs/_processed.json").read_text(encoding="utf-8"))
todays = json.loads(Path(f"runs/{today}/assignments.json").read_text(encoding="utf-8"))

urgent = []
for item in todays:
    key = f"{item['course_id']}:{item['assignment_id']}"
    led = ledger.get(key, {})

    try:
        sub = cv.get_submission(item["course_id"], item["assignment_id"])
        live_state = sub.get("workflow_state")
    except Exception:
        live_state = "?"

    if live_state in ("submitted", "graded"):
        continue

    due = dt.datetime.fromisoformat(item["due_at"].replace("Z", "+00:00"))
    hours_left = (due - now).total_seconds() / 3600
    if hours_left <= 24:
        urgent.append({
            "course": item["course_name"][:25],
            "name": item["name"][:50],
            "hours_left": round(hours_left, 1),
            "state": live_state if hours_left > 0 else "OVERDUE",
            "ledger_state": led.get("status"),
            "draft": led.get("draft_path"),
            "skill": item["skill"],
        })
```

Format banner:

```markdown
# URGENT — N item(s) due within 24h, not submitted

- [canvas-myskill] Course Label | Assignment Title | due in 14h | state=unsubmitted | draft: runs/.../draft.pdf
- [canvas-myskill] Course Label | Other Assignment | OVERDUE 3h ago | ledger=draft_ready

Upload the draft, mark 'skip on purpose', or handle it. This banner reappears every run until resolved.

---
```

If no urgent items:

```markdown
# No urgent items in next 24h

---
```

The banner is ALWAYS the first block of REPORT.md. The user opens the file and sees status immediately.

### 8. REPORT.md body

After the urgent banner, group items by status:

```markdown
## Done (N)
- **Course Label** / Assignment Title  (due 2026-04-25T23:59:00Z)
  - draft: `runs/<today>/...`
  - notes: ...

## Skipped (N)
- ...

## Errors (N)
- **Course Label** / Assignment Title
  - skill: `canvas-<name>` → `.claude/skills/canvas-<name>/SKILL.md`
  - error notes: {result.json `notes` verbatim}
  - **Debug checklist** (open the SKILL.md and tick through):
    - [ ] `<!-- UNFILLED_SKELETON v1 -->` sentinel still present? Remove it after you fill the 4 TODOs.
    - [ ] Frontmatter `name:` matches the directory name (`canvas-<name>`)?
    - [ ] Frontmatter `allowed-tools:` includes everything the skill uses (Bash / Read / Write / Edit / WebFetch)?
    - [ ] §1 TODO answered (where does the real spec live)?
    - [ ] §2 TODO answered (how does this skill produce a draft)?
    - [ ] §3 TODO answered (how do you verify the draft before submitting)?
    - [ ] §4 result.json — does the skill actually write `runs/<today>/<dir>/result.json`?
    - [ ] If `notes` mentions a specific file path or API call: does that path exist? does the API call work standalone?
  - After fixing, re-run `/canvas-scan` — the assignment will reappear in the plan (deferred items re-enter on next scan).
```

If `Errors (N)` is empty, omit the heading entirely. The checklist exists because raw `error notes` is hostile to a first-time student — they get "X failed" without knowing whether the problem is their SKILL.md, the framework, or Canvas. The checklist gives them a 30-second sanity scan + a specific re-run command.

`src/report.py` has a `write_report` helper if you want to use it.

### 9. Next step

After the Done / Skipped / Errors sections, append a `## Next step` block with **one specific suggestion** based on what just happened. Don't dump data without telling the student what to do next.

Pick the suggestion based on actual run state (in priority order):

- **If `Errors (N) > 0`**: "Look at the first error — open `.claude/skills/canvas-<name>/SKILL.md` and check whether the §1–§4 TODOs are still unfilled. Then re-run `/canvas-scan` and that item reappears."
- **Else if `Skipped (N) > 0` for manual courses**: "These ones are manual — open them in Canvas yourself. The list is preserved at the top so you don't forget."
- **Else if `Done (N) > 0`**: "Drafts are at `runs/<today>/<dir>/` (each has a `result.json` pointing at the artifact). Review, then upload manually if the SKILL.md doesn't auto-submit."
- **Else (nothing approved)**: "Nothing dispatched this run. When you want to come back, say `scan canvas`."

Template (literal — don't add bullets if the data doesn't justify them):

```markdown
## Next step

<one sentence based on the rule above>
```

Keep it short. The point is the student lands on a clear action, not a wall of data.

### Crash-path fallback

If dispatch crashed mid-run (sub-skill threw, Canvas API died, etc.) and you're recovering in a follow-up turn before marker removal: make sure every item in assignments.json has a `result.json` (write `status: skipped, notes: "execute crashed at this item", deferred_to_next_run: true` for unfinished ones). Then the marker can be removed. Then report the crash to the user with specifics.

## What you MUST NOT do

- Do NOT dispatch an item whose `user_decision` isn't in `{approve, swap:*}`. "Not approved" means "not approved".
- Do NOT scan Canvas or regenerate plan.json from scratch. If plan.json is missing or stale, hand back to `/canvas-scan`.
- Do NOT try to rush the last approved item when context is tight. Pause (§5), report, ask. Half-finished work is worse than deferred work.
- Do NOT fabricate `draft_path` or `status` in the ledger. If a sub-skill returned `error`, record `error` — don't round up to `draft_ready`.
- Do NOT forget to remove the `.scan_in_progress` marker. A wedged Stop gate is the most common operator error.
