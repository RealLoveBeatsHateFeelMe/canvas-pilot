# Canvas Pilot

Canvas Pilot turns the homework you do every week — readings, weekly quizzes, programming sets, lab reports — into something Claude Code can draft for you. You review before anything leaves your laptop. Runs inside [Claude Code](https://claude.com/claude-code).

```
[Canvas API]
     │
     ▼
canvas-scan ─────► plan.json ─────► (you review) ─────► canvas-execute
                                                              │
                                                              ▼
                                              Skill tool dispatch
                                                              │
                       ┌──────────────────────┬───────────────┴────────────────┐
                       ▼                      ▼                                ▼
               canvas-mycode/         canvas-myreading/             canvas-myquiz/
              (you write this)       (you write this)              (you write this)
```

## What this is

If you take the same kinds of assignments week after week — programming sets, reading annotations, weekly quizzes, lab reports — there's a fixed playbook each kind needs. **Canvas Pilot lets you encode that playbook once as a skill (`.claude/skills/canvas-myreading/SKILL.md`) and have it dispatched automatically whenever a matching assignment appears.**

The framework's job is the boring part:

- Scan Canvas for what's pending in the next N days.
- Group by urgency and show you a plan to approve.
- Once you approve, route each item to the right skill (per `courses.yaml`) and let it run.
- Track what got done across runs so the same assignment doesn't reappear.
- Stop and report cleanly so nothing gets half-done.

The interesting part — *how* a particular kind of assignment gets handled — is up to you. The repo ships **no course-specific skills**. You write your own.

## What this is NOT

- **Not an automated submitter — by design and by principle.** The Canvas API client ships read-only, and we don't accept PRs that add submission helpers. Auto-submitting AI-generated work to a graded LMS is academic-integrity territory we deliberately stay out of. Skills produce drafts; the student reviews and submits manually.
- **Not a "do my homework for me" tool.** It's a routing scaffold; the value is in the skills you write. You're responsible for whatever those skills do.
- **Not coupled to any LLM provider.** It runs inside Claude Code, and your skills can invoke whatever tools CC offers, but there's no API key for an LLM here — CC handles that.

## Quickstart

```bash
git clone https://github.com/<you>/canvas-pilot.git
cd canvas-pilot
python setup.py            # one-shot: configure local paths in settings.json
pip install requests       # cookie-mode users also: pip install playwright && python -m playwright install chromium
```

Configure auth — see [SETUP.md §1](./SETUP.md) for the **token vs cookie** decision (depends on whether your school lets students self-issue API tokens).

Open the folder in Claude Code (`claude` from the repo root), and say:

```
scan canvas
```

On first run, CC walks you through configuring `courses.yaml` and `SECRETS.md` itself — you don't type course IDs by hand. Then it lists pending assignments and stops. Reply with `all` / `1, 3` / `urgent only` / `skip` to control what gets dispatched.

**Adding a course mid-term?** Tell CC `design a skill` (or `设计 skill`) any time after first-run — it'll run the same fingerprint+naming flow on the new course and write a fresh SKILL.md skeleton + route entry.

## How to write your own skill

Pick one recurring assignment type — say, weekly reading annotations.

1. Add a course to `courses.yaml`:

   ```yaml
   routes:
     12345:
       name: "My Reading Course"
       skill: canvas-myreading
   pending_window_days: 7
   ```

2. Create the skill file at `.claude/skills/canvas-myreading/SKILL.md`:

   ```markdown
   ---
   name: canvas-myreading
   description: Handles weekly reading-annotation assignments for course 12345. Invoked by canvas-execute when an assignment routes to canvas-myreading. Knows to fetch the reading PDF from the Files folder, produce an annotated draft, and write result.json.
   allowed-tools:
     - Bash
     - Read
     - Write
     - Edit
     - WebFetch
   ---

   # canvas-myreading

   ## What you do

   1. Read the assignment item passed by canvas-execute.
   2. Pull the reading PDF from the course's Readings folder (file IDs in SECRETS.md).
   3. Produce an annotated PDF draft.
   4. Write result.json with status: draft_ready and draft_path pointing at the PDF.
   ```

3. Document the per-course identifiers (file IDs, voice rules, etc.) in `SECRETS.md` under a section for that course.

4. Run `scan canvas` — when an assignment in that course is pending, the framework will dispatch it to your skill.

The skill is a markdown instruction to Claude. Treat it like a small playbook: what to read, what to produce, what to write into `result.json`. Anything you can do with CC's tools, you can do here.

### result.json contract

Every skill must write `runs/<today>/<course_slug>__<assignment_slug>/result.json` before returning:

```json
{
  "status": "draft_ready",
  "draft_path": "runs/<today>/.../draft.pdf",
  "notes": "any free-form context the user should see in REPORT.md"
}
```

Valid `status` values: `draft_ready`, `submitted`, `skipped`, `error`. The Stop-hook gate (`check-router-complete.py`) blocks the session from ending until every assignment in the current run has a valid result.json — this is what keeps half-finished runs honest.

## Repo layout

```
.
├── .claude/
│   ├── hooks/                 # Hook scripts: SessionStart context, schema validation, Stop gate
│   ├── settings.json          # Hook registration (paths get rewritten by setup.py)
│   └── skills/
│       ├── canvas-scan/       # Framework: scan + plan + stop
│       ├── canvas-execute/    # Framework: parse approval + dispatch + finalize
│       └── canvas-skip/       # Framework: manual-todo fallback
├── src/
│   ├── canvas_client.py       # Read-only Canvas API helpers
│   ├── canvas_login.py        # Playwright cookie capture (CANVAS_AUTH=cookie)
│   └── report.py              # REPORT.md aggregator
├── runs/                      # Daily output (gitignored). plan.json, REPORT.md, drafts.
├── courses.yaml               # course_id → skill routing (CC populates from probe)
├── .env.example               # CANVAS_AUTH + CANVAS_BASE template
├── SECRETS.example.md         # Per-quarter identifier schema
├── SETUP.md                   # First-run walkthrough (decision tree at §1)
├── CLAUDE.md                  # Project entry that CC auto-loads
└── setup.py                   # One-shot path-rewriter
```

## License

[MIT](./LICENSE).
