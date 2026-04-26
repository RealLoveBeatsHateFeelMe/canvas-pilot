---
name: canvas-skip
description: This skill should be used when an assignment was routed to a skill name that doesn't exist or is intentionally non-automated. Logs the assignment to the daily todo.md so the user can do it manually, and returns a `skipped` status to canvas-execute. Does no automation work.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
---

# canvas-skip (manual-todo fallback)

Generic fallback for assignments that the framework can't (or shouldn't) automate. Routes an item into `runs/<today>/todo.md` so the user has a clear list of "things I'll do by hand this run".

Useful when:

- The user marks a course as `skill: canvas-skip` in `courses.yaml` for assignments that depend on a non-Canvas platform (third-party homework site, in-class clicker, lab equipment, etc.).
- A user-defined skill is partial or buggy and the user wants to capture the assignment without auto-handling it.
- A specific assignment is routed via an `override` to skip while the bulk of the course is automated.

## What you do

1. Read the assignment item passed by canvas-execute (course_id, assignment_id, name, due_at, html_url, submission_types, description).

2. Append a section to `runs/<today>/todo.md` with:
   - Course name and assignment title
   - Due date (in user's local timezone for readability)
   - URL (`html_url`)
   - `submission_types`
   - First ~400 chars of `description` as an excerpt (so the user has a hint of what to do)

   Create the file if it doesn't exist; append (don't overwrite) if it does. Format:

   ```markdown
   ## <course_name> — <assignment_name>

   - Due: 2026-04-25 23:59 PT
   - URL: https://canvas.../assignments/...
   - Submission types: online_upload
   - Description excerpt: ...
   ```

3. Write `runs/<today>/<course_slug>__<assignment_slug>/result.json`:

   ```json
   {
     "status": "skipped",
     "notes": "logged to todo.md for manual handling"
   }
   ```

4. Return.

## What you MUST NOT do

- Do NOT mark anything as `draft_ready` — `skipped` is the honest status when the framework didn't produce work.
- Do NOT try to fetch content from external platforms. If the assignment depends on something outside Canvas, that's exactly why it's routed here.
- Do NOT call any submit endpoint. The public framework's API client is read-only.
