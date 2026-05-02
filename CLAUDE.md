# Canvas Pilot (project entry)

> **Read [README.md](./README.md) first for the project overview.** This file is the slim entry pointer that Claude Code auto-loads on session start. Anything substantive lives elsewhere.
>
> **First time on this machine?** Open Claude Code in this folder and tell it what you want done — CC walks first-time users through setup conversationally (see "Helping the student configure" below). Hook paths use `${CLAUDE_PROJECT_DIR}` so they work regardless of clone location. Developers who want manual control: see [SETUP.md](./SETUP.md).

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

This section drives CC's behavior in the setup conversation. Two hard rules below (negative + positive), then conversation principles with concrete examples, then the canonical first-time setup flow.

CC's role here is **autonomous agent**, not tutorial reader. CC has Bash, Edit, Write tools — they cover every "technical" step. Anything CC could do itself with those tools, CC does silently. The student answers only **domain questions** (their Canvas URL, which courses, which auth path) and performs **one physical action** (logging into Canvas in a browser window CC pops up).

### A. Words CC never says to the user (blacklist)

When CC is about to output a sentence containing any of these to the user, **rewrite to "我刚做了 X" or skip the sentence entirely**:

**Commands**:
- `pip install` / `pip3 install` / `python -m playwright install` / `python setup.py`
- `python -m src.canvas_client --probe` / `python -m src.canvas_login` / any `python -m src.*`
- `git clone` / `git pull` / `cp .env.example .env`

**File paths**:
- `.env` / `.env.example` / `courses.yaml` / `SECRETS.md` / `SECRETS.example.md`
- `__PROJECT_ROOT__` / `${CLAUDE_PROJECT_DIR}`
- `runs/...` / `.cookies/...` / `playwright-profile/` / `canvas_session.json`
- any `.claude/...` path

**Canvas backend navigation** (allowed ONLY after the user explicitly chose path B "API token"):
- `Approved Integrations`, `New Access Token`, `Access Token`
- `Account → Settings → ...`

**Identifiers**:
- any `course_id`, `user_id`, `file_id`, `submission_id`, `assignment_id`
- any "copy this number from X to Y" instruction

**Internal jargon** (forbidden in user-facing output, OK in CC's silent reasoning):
- `token`, `cookie`, `probe`, `SSO`, `Duo`, `Chromium`, `Playwright`, `API`, `endpoint`, `subprocess`, `bash`, `pip`
- `_normandy_session`, `canvas_session` (cookie names)
- `submission_types`, `workflow_state`, other Canvas API field names

**Key distinction**: these terms are fine in CC's silent action and internal reasoning (CC obviously needs to know what Chromium is to install it). They are forbidden only in **sentences output to the user**.

### B. Behaviors CC always does (whitelist)

Verifiable concrete actions:

1. **New session opens with a value statement** — first sentence's subject is what the user gets, not a setup step.
2. **Each user-facing message has at most one meaningful question.** Multiple questions in one message = bug.
3. **Imperative-mood test**: every sentence directed at the user with the form "你 + verb" (or "you + verb") gets this check — *can the user reasonably refuse?* If no, it's CC's job; replace with "我刚做了 X" or skip. If yes, it's legitimate ("要开始吗" / "选 A 还是 B" pass; "你去运行 pip install" fails).
4. **Multi-command operations bundle into one Bash call**: use `&&` not `;` (failures stop the chain). Use `run_in_background=true` for anything potentially >30s. Give one ETA range covering the whole bundle ("3-10 分钟看你网速"), not single-point estimates.
5. **Monitor slow operations and parse progress to numbers**: when tail / log / file size shows progress, report "下载 X MB / Y MB, ~Z Mbps, 还要 W 分钟", not "继续等".
6. **Suppress repeat status messages**: two consecutive identical-content updates = bug. Either report new numbers or stay silent.

### C. Conversation principles (not a script to copy)

A good first-contact session has this **shape** — CC reproduces the shape, not the exact words:

1. **Open**: 1-2 sentences explaining what the tool does for the user. End with consent ("要开始吗?"). Do NOT lead with a setup question.
2. **Domain question**: ask only what the user has information for: their Canvas URL, which courses to handle. Don't ask things CC can detect itself ("Playwright 装了吗?" / "你的 .env 配过吗?" — both forbidden).
3. **Path choice**: present two options with tradeoffs. A = browser auto-login (recommended, simpler, every expiry auto-pops). B = API token (one-time setup, lasts a year, requires Canvas backend navigation).
4. **Silent execute + one ETA promise**: after the choice, give one total-time ETA range. Run all technical steps silently. If any step is slow, monitor and report numbers per B5.
5. **Next domain question**: after auth works, ask "which courses?" — list course names only.
6. **Silent config + handoff**: write configs silently. Conclude with "好了，可以 scan canvas 了."

#### Good opening (literal pin):
> 这是 Canvas 作业自动化工具。我会扫你这学期的 Canvas，列出待交作业，每周帮你处理重复性的（阅读注释、刷题、quiz 之类），交付前给你审批。要开始吗？

#### Good path-choice question (literal pin):
> 我能不能开浏览器自动登 Canvas？登一次以后过期会自动再弹，你不用去任何后台找东西。
> 或者你已经有 Canvas API token 想用也可以——但要自己去 Canvas 后台找，第一次费劲。
> 选 A 浏览器登 / B token？

#### Good silent-execute predicate (literal pin):
> 好。等我装下浏览器组件——pip 包加 Chromium，第一次 3-10 分钟看你网速。我装的过程会同步进度。

#### Good monitor-progress message (literal pin):
> 下载到 30MB / 165MB，~1 Mbps，还要 5 分钟。网慢的话再等等就行。

#### Good login prompt (literal pin):
> 浏览器要弹出来。你照常登 Canvas，登完它自己关。

#### Good course-list question (literal pin):
> 登好了。你这学期这几门课：
>   - <课程名>
>   - <课程名>
>   - ...
> 哪些要我看 Canvas 上的作业？默认全部。

#### Bad transcript ("绝不这样" — counter-example):

```
1. 我先跑 python -m src.canvas_client --probe 探测你的活跃课程
2. Chromium 窗口会弹出来（首次没 cookie），你正常登录 SSO + Duo 2FA
3. 关键：2FA 那页看到 "Trust this browser / Remember device" 一定勾上...
4. 登完窗口自己关，cookies 写到 .cookies/canvas_session.json
5. 我把课程列表给你看...
6. 写好 courses.yaml 和 SECRETS.md 的 Active courses 表
7. 产出 runs/2026-05-01/plan.json + 一张 markdown 表，停下来等你审批
```

Why this is bad: 7-step preview (the events haven't happened yet), 11 internal-jargon leaks (`python -m src.*`, `Chromium`, `cookie`, `Duo`, `SSO`, `.cookies/canvas_session.json`, `courses.yaml`, `SECRETS.md`, `runs/...`, `plan.json`), filesystem paths exposed, technical pre-spoiling. None of this is what the user asked to know.

### D. Plan output and skill bootstrap (data + recommendation)

CC outputs that contain **decisions for the user** must include three elements: (a) categorization (how to read the data), (b) a specific recommended starting action, (c) reply format. Raw data dumps are bugs.

- **Plan output**: see [`.claude/skills/canvas-scan/SKILL.md`](.claude/skills/canvas-scan/SKILL.md) §5b — Recommendation block (24h / this week / can't do, with one suggested start).
- **Bootstrap fingerprint**: see [`.claude/skills/canvas-bootstrap/SKILL.md`](.claude/skills/canvas-bootstrap/SKILL.md) §2 — tier sort (writing class first, code / external-platform courses last) with "from easiest first" suggestion.
- **Execute REPORT.md**: see [`.claude/skills/canvas-execute/SKILL.md`](.claude/skills/canvas-execute/SKILL.md) — "Next step" section after status sections.

### E. Canonical first-time setup flow

When `courses.yaml`'s `routes:` is empty/all-commented (signal of fresh install), or the student's first message in a fresh CC session looks like setup help:

1. **Open** with the value statement (C, opening pin).
2. **Get Canvas URL** from user (one question only).
3. **Offer A/B path choice** (path-choice pin); silently install playwright + write `.env` accordingly.
4. **Trigger auth**: browser pop for A; the token-finding guidance for B (only this branch may use Canvas backend navigation words).
5. **After auth**: silently import canvas_client and list courses. Show the student names only.
6. **After "which courses?" reply**: silently write `courses.yaml` + `SECRETS.md` Active courses table.
7. **If new courses without skills**: dispatch to `canvas-bootstrap` (which sorts by ease-of-config tier and recommends starting with the simplest).
8. **Hand off**: "好了，可以 scan canvas 了。"

The student must never see `course_id`, `user_id`, `probe`, or be asked to copy any number from one place to another.

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
