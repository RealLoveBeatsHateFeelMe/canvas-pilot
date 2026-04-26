# SECRETS.md — template for per-user / per-quarter identifiers

> Copy this to `SECRETS.md` and fill in the real values. `SECRETS.md` is
> gitignored. This template is committed to document the schema only.
>
> Each quarter, update `SECRETS.md` with the new course IDs, file IDs,
> instructor info, etc. Your skills should reference this file so that a
> new term doesn't require code changes — only a SECRETS.md update.

---

## Identity

| Field | Value |
|---|---|
| Real name | <your name> |
| School email | <you>@<school>.edu |
| Canvas user_id | <int — find via `python -m src.canvas_client --probe`> |

## Canvas

- Host: `<your school's Canvas host, e.g. canvas.<school>.edu>`
- API base: `https://<host>/api/v1`  (set in `.env` as `CANVAS_BASE`)

### Active courses (current term)

| course_id | name | instructor | skill |
|---|---|---|---|
| <id> | <full course name> | <instructor> | <skill name from .claude/skills/> |

### Skipped / archived courses

- <id> <reason>

## Per-course details

For each course your framework handles, document:

- Where the *real* spec lives (external instructor site, Files folder,
  module pages, attached PDFs, etc.) — your skills will use this.
- Specific identifiers your skill needs (file IDs for recurring readings,
  module IDs, page slugs, external URLs, etc.).
- Any course-specific rules your skill must follow (max page count, voice
  rules, formatting requirements, instructor preferences).
- The Canvas assignment_id table for assignments that recur with stable IDs.

Keep this file as the single source of "where is the data" — your skill
files (.claude/skills/canvas-*/SKILL.md) describe behavior categorically,
SECRETS.md holds the concrete IDs they reference.

## Time-sensitive

- Timezone, daylight-saving switch dates if relevant
- Current term name
- Any short-lived notes that should be cleared at term end

## Notes for skill authors

- Always read SECRETS.md before hardcoding identifiers in a SKILL.md.
- SECRETS.md is the "data" half; SKILL.md is the "logic" half.
- New skills get a section in SECRETS.md; new identifiers go there too.
