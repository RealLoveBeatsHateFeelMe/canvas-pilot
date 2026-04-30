---
name: canvas-bootstrap
description: Use this skill when the user wants to set up Canvas Pilot for the first time, add a new course to the routing table, or redesign an existing per-course skill. Trigger phrases include "设计 skill" / "改 skill" / "design a skill" / "modify skill" / "add a new course" / "set up canvas pilot". Also auto-invoked by canvas-scan when `routes:` in courses.yaml is empty. Surveys recurring assignment patterns per course (>=3 occurrences), collects student-chosen skill names, then writes SKILL.md skeletons + courses.yaml route entries.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Skill
---

# canvas-bootstrap

Helps the student stand up new per-course skills. Two ways to enter:

1. **Auto** — canvas-scan §0 detects `courses.yaml.routes` is empty/all-commented and dispatches this skill via the Skill tool.
2. **Manual** — student says "设计 skill" / "改 skill" / "design a skill" / "add a new course" / etc. The Claude orchestrator reads the trigger and invokes this skill.

Either way, this skill produces two artifacts per chosen course:

- `.claude/skills/canvas-<student-chosen-name>/SKILL.md` — a generated skeleton with frontmatter filled in, fingerprint summary inline, and 4 TODO sections the student must fill in by hand.
- An entry in `courses.yaml` under `routes:` mapping that course's `course_id` to `canvas-<name>`.

This skill **never writes any solving logic**. It writes routing/IO scaffolding — the student writes the actual playbook.

## Roles and limits

- This skill is a **framework-level** utility. It must contain **zero course-specific knowledge** (no institution names, course numbers, instructor identities). Stays clean for upstream public mirror.
- Skeletons it writes are also framework-level templates — only contain student-fillable TODOs and per-course fingerprint **measurements**, never **labels** ("major type", "this is a code course"). Facts only.
- After writing skeletons, this skill exits. The student fills the TODOs in their editor; new skills become discoverable on the next CC session.

## What you do

### 1. Build the fingerprint table

For every course in `courses.yaml.routes` (or every active course Canvas returns when routes is empty):

```python
import sys
sys.path.insert(0, ".")
from src import canvas_client as cv
from src.recurring_patterns import bucket_recurring, is_course_active

# routes empty → call cv.get('/courses', enrollment_state='active', include=['term'])
# routes non-empty → iterate routes (use cv.get_course for each to get term info)
raw_courses = cv.get('/courses', enrollment_state='active', include=['term'])

# Filter out (a) ended-term courses (with 7-day grace) and (b) empty courses
# These are noise the student doesn't want to make decisions about.
fingerprints = []
for c in raw_courses:
    if not is_course_active(c, grace_days=7):
        continue  # last quarter's course — student doesn't install skills on dead courses
    items = cv.list_assignments(c["id"])
    if len(items) == 0:
        continue  # empty course — nothing to fingerprint, nothing to automate
    patterns, sub_threshold = bucket_recurring(items, min_freq=3)
    fingerprints.append({
        "course_id": c["id"],
        "course_name": c["name"],
        "configured_skill": c.get("configured_skill"),  # set when iterating routes
        "patterns": patterns,
        "sub_threshold": sub_threshold,
        "total_assignments": len(items),
    })
```

Compute fingerprint for **all surviving courses**, including ones already configured — re-running bootstrap to refresh the view of an existing course is a legit use case.

**Why filter**:
- **Ended-term courses** (e.g. last quarter's course still showing in `enrollment_state=active` because grades aren't finalized) — student doesn't want to install a skill on something that won't have new assignments. The 7-day grace is for the edge case where finals just ended and a make-up assignment might still post.
- **Empty courses** (0 assignments) — nothing to fingerprint, nothing the student can decide about. If the course later gets assignments, the student re-runs bootstrap and it appears.

If after filtering **0 courses remain**, tell the student "no active courses with assignments yet — re-run after some weeks of work have posted" and exit.

### 2. Render the table to the student — main + folded layout

**Split fingerprints into two groups before rendering**:

- **main**: courses where `len(patterns) > 0` (have at least one recurring assignment shape at min_freq=3)
- **folded**: courses where `len(patterns) == 0` (only sub-threshold assignments — typically onboarding/training spaces, but could also be a real course in week 1-2 before patterns have accumulated)

The main group is the actionable surface. The folded group is hidden by default to keep the decision space small, but **every folded course is still numbered** so the student can install a skill on it directly without expanding (or expand with `展开 N` to see what assignments it actually has).

**Numbering is one continuous sequence**, but with two semantics:

- Numbers `1..N` (in main): each is a **pattern**. Pattern → course is many-to-one (one course can have multiple patterns).
- Numbers `N+1..N+K` (in folded): each is a **whole course** (no patterns to enumerate). The number = the entire course.

Build a lookup table as you assign numbers:

```python
lookup = {}  # number -> ("pattern", course_id, pattern) | ("course", course_id, fingerprint)
n = 1
for fp in main:
    for pat in fp["patterns"]:
        lookup[n] = ("pattern", fp["course_id"], pat); n += 1
for fp in folded:
    lookup[n] = ("course", fp["course_id"], fp); n += 1
```

If a course has `configured_skill` already set, mark its heading (`✓ canvas-pyhw`) and skip numbering its patterns/itself — it's already in routes, not eligible for re-naming this session.

**Chinese template** (when most recent user message contains Han characters):

```
{main course name}                         ← 已配 ✓ canvas-pyhw / 未配
  N  {norm_name}      [{submission_types}]   {count}x
  N  {norm_name}      [{submission_types}]   {count}x
  + M one-off / sub-threshold assignments     (omit line if M=0)

{next main course}
  ...

⊕ K 门课没有 recurring pattern (默认折叠):
   N  {course_name}                         ({total_assignments} 杂作业)
   N  {course_name}                         ({total_assignments} 杂)
   ↑ 想给某门起 skill？回 "N → name" 装；或 "展开 N" 看具体作业名

哪几门课要装 skill？回 `<numbers> → <name>`（前缀 canvas- 我加）。

例（基于上面的 fingerprint，**仅作示范怎么读表**，不是要你照抄）：
  <根据真实 fingerprint 生成 2-4 行 inline-analysis examples，见下方 "Example generation rules">
```

If `K == 0` (no folded courses), omit the `⊕` block entirely.
If `len(main) == 0` (every course is folded), still render the folded block — it's all the student has.

**English template** (default):

```
{main course name}                         ← already configured ✓ canvas-pyhw / unconfigured
  N  {norm_name}      [{submission_types}]   {count}x
  ...
  + M one-off / sub-threshold assignments

⊕ K courses have no recurring pattern (folded by default):
   N  {course_name}                         ({total_assignments} loose assignments)
   N  {course_name}                         ({total_assignments} loose)
   ↑ Install a skill on one? Reply "N → name". Or "expand N" to see assignment names.

Reply with `<numbers> → <name>` (I add the canvas- prefix).

Examples (generated from your fingerprint above — these show HOW to read
the table, not what to type):
  <2-4 inline-analysis example lines per the rules below>
```

Render columns with whitespace alignment, not pipe-tables — patterns are facts, not a data grid.

### 2c. Example generation rules

After the table, render **2-4 example mapping lines** based on the actual fingerprint data. Each example has the format:

```
  <numbers> → <made-up-name>    <一句话理由 / one-sentence rationale>
```

The rationale draws on **observable signals** in the fingerprint:

- `submission_types` — `online_upload` (might be PDF / scan / file), `online_quiz` (Canvas quiz), `online_text_entry` (typed answer), `external_tool` (LTI), `on_paper` (in-class)
- **Pattern name shape** — words like "Scan / HW / Quiz / Set / Problem / Project / Reading / Lab / Lecture / Discussion" suggest the work kind
- For folded courses — the count of loose assignments + the course name

**Soft framing required**:
- ✅ "看起来像扫描件" / "名字含 'Set/Project' 像代码" / "submission_type 是 quiz 显然是测验"
- ✅ "looks like scanned PDFs" / "names contain 'Set/Project' suggesting code" / "submission type is quiz so it's a quiz"
- ❌ "这是 PDF 课 / Code 课 / Quiz 课"
- ❌ "this is a PDF course / Code course / Quiz course"

The goal is **teach the student to read signals**, not pre-classify their course.

**Coverage**: pick 2-4 examples to show variety — at minimum one multi-pattern same-course, one single-pattern, and (if folded section exists) one folded-course mapping. Don't enumerate every number; show the format.

**If main is empty** (only folded courses), examples should all be folded-course mappings. **If folded is empty**, skip the folded-course example.

**Made-up names**: pick short, descriptive names matching the rationale (`engscan` / `pyhw` / `globalquiz` / `mytraining`). These are illustrative — the student picks their own.

### 3. Parse the student's reply

The student can reply with two kinds of input — handle them in order:

**3a. Expand command** (escape hatch for folded courses):

If the student's reply is `展开 N` / `expand N` / `unfold N` (single token + number, optionally with extra space), and `N` resolves to a folded course in the lookup table, **re-render the table** with that course moved into the main group. To enumerate its assignments as numbered items, re-bucket with `min_freq=1` so every distinct (norm_name, submission_types) gets a number — sub-threshold becomes "main" for this one course. Loop back to §2's render with the expanded layout (including the moved course's new pattern numbers). All other folded courses stay folded.

The student then either continues with `<numbers> → <name>` mapping (now able to reference the expanded patterns) or sends another `展开 M`. No limit on how many times they can expand.

**3b. Mapping lines** (`<numbers> → <name>`):

Apply these rules in order:

**Silent normalizations** (no commentary back to student):

- LHS separators: split on `[,，\s和、與与&+]` — Chinese commas, "和", "与", spaces, etc all valid.
- RHS skill name: strip a leading `canvas-` if the student typed it (we add the prefix back).
- Missing `→` arrow: if the line still parses (numbers followed by exactly one identifier-shaped token), accept it. If multiple non-numeric tokens, fall through to ambiguous handling.

**Resolve each number against the lookup table**:

- `("pattern", course_id, pattern)` — student picked one recurring pattern from a main course
- `("course", course_id, fingerprint)` — student picked a whole folded course

**Ambiguous → ask once**:

If after normalization a line has multiple non-numeric tokens or no clear separation between numbers and name, ask:
> "`<line>` — 你是说 `1,2 → pyhw` 吗？回 y / n / 重写"

Don't loop. Second failure on the same line → stop bootstrap, tell student to re-run with the strict format.

**Hard reject — cross-course bundling**:

If a single mapping references **two or more course_ids** (after lookup), print:

> "你这条混了不同课 — 一个 skill 只能配一门课。请分两条写。"

Show which numbers map to which course names. Re-prompt that line.

This applies to all combinations: pattern+pattern across courses, course+course, pattern+course. The rule is one mapping = one course_id. Folded course numbers are individually one course, so they're naturally per-course on their own — combining them with anything else from another course is the failure case.

**Soft suggest — partial pattern coverage within a main course**:

If the student maps some patterns in a main course but not all of them (e.g., course has patterns 1, 2, 3 — student maps only pattern 1 to a skill), tell the student:

> "{course} 你只配了 pattern 1 ({pattern_1_norm}) → canvas-pyhw。pattern 2 和 3 没配 — 这两类作业出现时会走 canvas-skip（落 todo.md 你手动处理）。这样行吗？还是再起一个 skill？回 y / 加 skill 名"

`y` / silence / similar → accept. Adding another mapping → fold it in. **Never auto-fan-out** (don't generate a second skill on the student's behalf).

This soft-suggest does **not** apply to folded courses — picking a folded course number means the whole course, no partial coverage to warn about.

### 4. For each accepted mapping, prepare skeleton + route entry

Build the skeleton string from the template in the appendix below. Substitute these placeholders from the fingerprint:

| placeholder | source |
|---|---|
| `{name}` | the student-chosen name (without `canvas-` prefix) |
| `{course_name}` | from the fingerprint |
| `{course_id}` | from the fingerprint |
| `{today}` | `date +%Y-%m-%d` |
| `{pattern_summary}` | `"<pat1>" and "<pat2>" and ...` (joined human-readable) — for the frontmatter `description` field. **For folded-course mappings** (no patterns), use `"all assignments in {course_name}"` instead. |
| `{pattern_block}` | indented bullet list of `count×  norm_name    [submission_types]` lines for THIS course's mapped patterns. **For folded-course mappings**, render `"  - (no recurring patterns at min_freq=3 yet — total {N} assignments seen, mostly one-offs at the time of bootstrap)"` instead. |
| `{empty_or_thin}` | `"empty for 100% of items in this course"` if that course has ≥80% of items with empty `description`, otherwise `"thin (only short blurbs in most items)"` |
| `{empty_desc_warning_if_applicable}` | only emit the "real spec lives elsewhere" callout when the empty-description ratio crosses 80%; otherwise emit empty string |

Skeleton must include:

- `<!-- UNFILLED_SKELETON v1 -->` HTML comment **as the very first line of body** (after frontmatter)
- A blockquote starting with `> **STOP if you are Claude reading this from canvas-execute dispatch.**` — explicitly tells dispatch to write `result.json status="error" deferred_to_next_run=true` and stop. This is the self-guard that prevents Claude from "guessing" the assignment when the student hasn't filled the body.

### 5. Write skeletons + commit routes (idempotent)

For each mapping in this run:

**5a. Check sentinel before overwriting** — if `.claude/skills/canvas-<name>/SKILL.md` already exists, read it. If the file contains `<!-- UNFILLED_SKELETON v1 -->`, the student hasn't started filling it — safe to overwrite. If the sentinel is **gone**, the student has edited the body. Stop and ask:

> "canvas-<name> 已存在且已被你编辑过。重新生成会覆盖你的填充。继续? [y/N/save-as canvas-<name>-v2]"

Default `N`. `save-as` → write to `canvas-<name>-v2/SKILL.md` instead and update the routes entry to point at `-v2`.

**5b. Write the skeleton file**: `mkdir .claude/skills/canvas-<name>/` then `Write` SKILL.md. Use `Write` tool (not `Edit` — it's a new file).

**5c. Add to in-memory routes update** — accumulate, don't write `courses.yaml` per skill:

```python
new_routes[course_id] = {
    "name": course_name,
    "skill": f"canvas-{name}",  # literal SKILL name, not symbolic
}
```

**5d. After the skill is written, ask if more**:

> "✓ canvas-<name> 已生成 (.claude/skills/canvas-<name>/SKILL.md)
> 还要再设计下一个吗？回 y / 跳过 / 完成"

`y` → re-render the table (with the just-configured course now marked `✓`) and loop back to step 3. `跳过` / `完成` / `done` / silence → exit the loop.

### 6. Atomic write courses.yaml + final summary

Read existing `courses.yaml`, merge `new_routes` into the `routes:` section (preserve any existing entries), atomic-write:

```python
import yaml
from pathlib import Path
import os

cfg_path = Path("courses.yaml")
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
# IMPORTANT: cfg.get("routes") can be None when routes: header exists but
# all entries are commented out (the upstream first-run state). setdefault
# does NOT overwrite an existing None, so we coerce explicitly.
if cfg.get("routes") is None:
    cfg["routes"] = {}
cfg["routes"].update(new_routes)  # course_id keys; later wins on collision
if cfg.get("pending_window_days") is None:
    cfg["pending_window_days"] = 7

tmp = cfg_path.with_suffix(".yaml.tmp")
tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
os.replace(tmp, cfg_path)
```

Print a final summary:

```
✓ courses.yaml: added 3 routes
✓ skeletons written:
    .claude/skills/canvas-pyhw/SKILL.md
    .claude/skills/canvas-globalquiz/SKILL.md
    .claude/skills/canvas-engscan/SKILL.md

Next:
  1. Open each SKILL.md and fill the 4 TODO sections (spec location,
     draft production, verification approach, result.json wiring).
  2. When you remove the <!-- UNFILLED_SKELETON v1 --> sentinel, this
     skill is "ready" — canvas-execute will dispatch into it.
  3. New skills usually become discoverable immediately (Claude Code
     hot-reloads SKILL.md). If `/canvas-scan` can't dispatch your new
     skill, restart CC and try again.
```

End your turn. Do NOT invoke canvas-scan or canvas-execute from here — those have their own triggers.

## What you MUST NOT do

- Do **not** write any course-specific knowledge into the skeleton (no institution names, course numbers, instructor identities). Skeletons are templates — fingerprint MEASUREMENTS are facts; everything else is the student's job.
- Do **not** label courses with a "major type" (code / quiz / document). Just list the patterns. Students decide what their course is.
- Do **not** recommend skill names. Students choose. The format is `<numbers> → <name>` — they supply the name.
- Do **not** write any TODO solving logic. The 4 TODO sections in the skeleton are intentionally open.
- Do **not** auto-fan-out one mapping into multiple skills. Per-course is per-course.
- Do **not** invoke `canvas-execute` or other sub-skills. This skill only writes files and config.

---

## Appendix: skeleton template (the literal string this skill writes)

This is the markdown the skill writes to `.claude/skills/canvas-{name}/SKILL.md` after substitution. Keep this section in lockstep with the parser in step 5a (the sentinel string `<!-- UNFILLED_SKELETON v1 -->` must match exactly).

````
---
name: canvas-{name}
description: Handles {pattern_summary} for {course_name} (course {course_id}).
  Invoked by canvas-execute. Produces draft and writes result.json with status:
  draft_ready.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - WebFetch
---

<!-- UNFILLED_SKELETON v1 — DO NOT REMOVE UNTIL YOU FILL THE 4 TODOs BELOW -->

> **STOP if you are Claude reading this from canvas-execute dispatch.**
> This skill is a generated skeleton; the student has not filled in the spec
> location or verification steps yet. Write `result.json` with:
> `{{"status": "error", "notes": "canvas-{name} skeleton unfilled — student must complete the 4 TODO sections in .claude/skills/canvas-{name}/SKILL.md before this assignment can be auto-handled", "deferred_to_next_run": true}}`
> and stop. Do NOT attempt to do the work from the TODO bullets alone.

# canvas-{name}

> Auto-generated skeleton {today}. Fill the 4 TODO sections below, then remove
> the `<!-- UNFILLED_SKELETON v1 -->` line above to mark this skill ready.

## This course at a glance (from fingerprint)

- Course: {course_name} (id `{course_id}`)
- Recurring patterns this skill handles:
{pattern_block}

{empty_desc_warning_if_applicable}

## What you do — fill these in

### 1. TODO: where does the real spec live?

The Canvas description is {empty_or_thin} for this course. Where do you go to
read what each assignment actually wants? (front_page link? a Files folder?
external instructor site? attached PDF? textbook chapter?) Document it here so
future-you doesn't re-discover it.

### 2. TODO: produce your draft

Write the deliverable into the work dir at:
`runs/<today>/<course_slug>__<assignment_slug>/`

Describe step by step what "produce a draft" means for this assignment kind —
what to fetch, what to compute, what file format to write.

### 3. TODO: how do you verify the draft is correct BEFORE submitting?

This is the section students skip and regret. Before claiming done:

- What numeric constraints does the spec impose? (page count, file count,
  function count, line/sentence/word limit, character limit, ...)
- How do you measure those properties on YOUR draft and produce a number?
- What's a sanity check that catches "the file is empty" / "wrong format" /
  "missing required section"?

Vibes are not verification. The check must produce a number you can look at,
not a feeling. Write it as a script and put output in `verification.log` next
to the draft.

### 4. Write result.json before returning

```json
{{"status": "draft_ready", "draft_path": "runs/<today>/<dir>/<file>", "notes": "..."}}
```

Valid `status` values: `draft_ready` / `submitted` / `skipped` / `error`.
The Stop hook (`check-router-complete.py`) blocks the session from ending
until this exists.
````

The triple-backtick block uses `````` (6 backticks) as the fence so the inner
``` ``` ``` of the JSON block doesn't break it. When emitting, also escape
literal `{` and `}` in the JSON example by doubling them (`{{` `}}`) so any
Python-style `.format()` substitution doesn't get confused — or, simpler, do
substitution with `str.replace()` for each placeholder rather than `.format()`.

## Configuration

- `courses.yaml` — read existing `routes:`; write back merged.
- `.env` — `CANVAS_TOKEN` / `CANVAS_BASE` (already required by canvas_client).
- `src/recurring_patterns.py` — `normalize()` and `bucket_recurring(items, min_freq=3)`.
- `src/canvas_client.py:list_assignments(course_id)` — pulls the assignment list.

## Failure modes

| Symptom | Cause | What to do |
|---|---|---|
| `canvas_client --probe` fails | bad token / network | Tell student, stop. Don't write anything. |
| Course returns 0 assignments | empty course this term | Render `(no assignments yet — skipped)` and skip. |
| All patterns sub-threshold (e.g. ≤2 occurrences each) | early in term | Render the sub-threshold tail count and tell student "early term — re-run bootstrap once a few weeks of work have posted". |
| Student input keeps failing parse after 1 retry | unclear input | Stop bootstrap politely, tell student to re-run with `<numbers> → <name>` format. Don't loop. |
| `.claude/skills/canvas-<name>/SKILL.md` exists, sentinel missing | student edited it | Ask before overwriting (default N), offer save-as `-v2`. |
