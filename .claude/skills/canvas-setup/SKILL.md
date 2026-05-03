---
name: canvas-setup
description: Use this skill on a fresh Canvas Pilot install when the student has never configured the project before. Trigger phrases include "set me up", "set up canvas pilot", "install canvas pilot", "/canvas-setup", "first time", "i'm new". Also auto-invoked by `canvas-scan` §0 when `.env` is missing or `CANVAS_BASE` is empty. Walks the student through a deterministic N-step first-run flow — Canvas URL → auth path → silent install → silent config → browser login → course selection — then dispatches `canvas-bootstrap` to design per-course skills. The student answers ~3 domain questions and logs into Canvas once; everything else is silent CC action.
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Skill
---

# canvas-setup (first-run configurator)

This skill **replaces** the old "Helping the student configure" prose section in `CLAUDE.md`. The prose was a set of negative rules ("never say pip install") that CC had to apply on top of free-form judgment. This skill is the positive version: a fixed N-step script. Every step specifies (a) what CC does silently, (b) what CC says to the student, (c) what CC waits for. CC walks the script; CC does not improvise.

## Why this skill exists (read this before editing)

The friend test (2026-05-02) found 12 setup-related UX bugs, all rooted in the same behavior: CC was reading framework docs (`SETUP.md`, `.env.example` comments, error tables) and parroting them at the student as a tutorial. Friend was told to `pip install` herself, edit `.env` herself, navigate Canvas back-office to find an Access Token herself — even though CC has Bash/Edit/Write tools to do all of it. See `.claude/plans/public-setup-ux-bugs.md` for the full incident list.

The fix is **not** more prose rules in CLAUDE.md. The fix is making first-run a fixed sequence the SKILL.md mechanism enforces: CC dispatches this skill, walks the steps, returns. The student's only legitimate actions are answering domain questions (Canvas URL, which courses, A/B path) and logging into Canvas once in a popup browser. Every other "step" the friend ever did manually (cp .env.example .env, pip install, edit env vars, run setup.py, find Access Token) is now CC's silent work.

## Hard rules CC follows the entire way through this skill

**The student's only legitimate actions during this skill**:
1. Answering questions CC asks about their own situation (Canvas URL, which courses, A/B choice).
2. Logging into Canvas once in a browser window CC pops up.
3. (B path only) Pasting an API token they generated.

**Anything else is CC's job.** If CC catches itself about to write a sentence telling the student to "open .env", "run pip install", "go to Canvas → Account → Settings → Approved Integrations", "copy this command into your terminal", "edit courses.yaml" — that is the bug this skill exists to prevent. Stop, do it with `Bash`/`Edit`/`Write`, and tell the student "我刚做了 X" / "I just did X" instead.

**Internal vocabulary the student never sees**: `pip`, `playwright`, `chromium`, `cookie`, `token` (in path A), `probe`, `SSO`, `Duo`, `.env`, `courses.yaml`, `SECRETS.md`, `__PROJECT_ROOT__`, `${CLAUDE_PROJECT_DIR}`, `runs/...`, `.cookies/...`, any Canvas API field name, any course/user/file `_id`. These are fine in CC's internal reasoning; they are forbidden in user-facing output.

**One question per turn**: each user-facing message ends with at most one question. Multi-question turns are a bug.

**Slow operations get one ETA + parsed progress**: any Bash command that may take >30s runs with `run_in_background=true`, gets one upfront time estimate covering the whole bundle (e.g. "等我装下浏览器组件，3-10 分钟看你网速"), and gets monitored with progress reported as numbers ("下载到 30 MB / 165 MB, ~1 Mbps, 还要 5 分钟"). Never repeat-emit "继续等" with no new information.

**Multi-command operations bundle into one Bash call**: `pip install playwright && python -m playwright install chromium` runs as ONE command, not two separate "等一下" turns. Use `&&` so failures stop the chain.

---

## What you do

### Step 1 — Open with value, ask consent

CC's silent action: none yet.

CC says (literal pin, pick the language matching the student's first message):

> 这是 Canvas 作业自动化工具。我会扫你这学期的 Canvas，列出待交作业，每周帮你处理重复性的（阅读注释、刷题、quiz 之类），交付前给你审批。要开始吗？

> This is Canvas Pilot. I scan your Canvas, list what's pending, and each week help you draft the recurring stuff (reading annotations, quizzes, problem sets) — you review before anything gets submitted. Want to start?

CC waits for: any affirmative (yes/好/行/ok/嗯/start/开始). If the student says no or asks something else, answer their question and wait — do not advance to step 2.

### Step 2 — Get the Canvas URL

CC's silent action: none yet.

CC says:

> 你学校的 Canvas 网址是什么？比如 `canvas.uci.edu` 或 `rutgers.instructure.com` 这种。

> What's your school's Canvas URL? Something like `canvas.uci.edu` or `rutgers.instructure.com`.

CC waits for: a hostname or full URL. Accept any of:
- `canvas.uci.edu`
- `https://canvas.uci.edu`
- `https://canvas.uci.edu/`
- `https://canvas.uci.edu/courses`
- `canvas.uci.edu/login`

CC silently normalizes to the bare scheme+host:
```python
import re
raw = student_input.strip()
if not raw.startswith("http"):
    raw = "https://" + raw
host_only = re.match(r"(https?://[^/]+)", raw).group(1).rstrip("/")
# host_only = "https://canvas.uci.edu"
CANVAS_WEB_BASE = host_only
CANVAS_BASE = host_only + "/api/v1"
```

If the student gives something that doesn't match `https?://[a-z0-9.-]+` after normalization, ask once more: "我没认出来这是个 Canvas 网址 — 直接给我学校 Canvas 登录页那个地址就行。" Don't explain regex.

### Step 3 — Offer A/B path; default to A

CC says (literal pin):

> 两种登录方式选一种：
>
> **A. 浏览器登录**（推荐）
> 你像平时一样在弹出的 Canvas 页面登一次。session 偶尔过期了浏览器会再弹一下让你登几秒，你不需要手动找任何东西。所有学校都行。
>
> **B. API token**（一次设置，管一年）
> 你去 Canvas 后台找一个叫 "Access Token" 的东西，5 步导航。拿到后粘给我，我配好。一年内不用动。但**有些学校禁用了这个**——按钮可能找不到，遇到就只能选 A。
>
> 默认推荐 A。要 B 的话告诉我。

> Two ways to log in:
>
> **A. Browser login** (recommended)
> A Chromium pops up, you log in like normal. If the session ever expires the browser pops up again for ~10 seconds. Works at every school.
>
> **B. API token** (one-time, lasts a year)
> You navigate Canvas back-office to find "Access Token" (~5 clicks deep), paste it back. Then no more login for a year. **Some schools disable this** — button may not even appear; if so just go with A.
>
> Default A. Tell me if you want B.

CC waits for: explicit "A" / "B" / "browser" / "token" / silence. Silence ≥ "use A". If the student says anything ambiguous, repeat the choice once.

Set `auth_path = "A"` or `auth_path = "B"`.

### Step 4 — Install browser components (path A only) or skip (path B)

**If `auth_path == "A"`**:

First check whether playwright + chromium are already installed (single Python check, not a user-visible question):

```python
import subprocess, sys
result = subprocess.run(
    [sys.executable, "-c", "import playwright; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); p.chromium.launch(headless=True).close(); p.stop()"],
    capture_output=True, text=True, timeout=30
)
already_installed = result.returncode == 0
```

If `already_installed` → skip to Step 5 silently, say nothing.

If not installed → CC says (literal pin):

> 等我装下浏览器组件——3-10 分钟看你网速，第一次比较慢。我会同步进度。

> Installing the browser components — 3-10 minutes depending on your connection. I'll keep you posted.

CC then runs ONE bundled Bash command in background:

```bash
pip install playwright && python -m playwright install chromium 2>&1 | tee /tmp/canvas_setup_install.log
```

(Use `run_in_background=true`. On Windows replace `/tmp` with a project-relative tmp dir.)

CC monitors the log file every 30-60 seconds. Each time CC reports, it must extract **numbers** from the log:
- `playwright install chromium` prints `Downloading Chrome ... [progress bar] X% of YMb` — parse to "下载到 X MB / Y MB"
- divide bytes-downloaded by elapsed time → throughput in Mbps
- (Y - X) / throughput → ETA in minutes

CC says (literal pin format):

> 下载到 30 MB / 165 MB，~1 Mbps，还要 5 分钟。网慢的话再等等就行。

> 30 MB / 165 MB downloaded, ~1 Mbps, ~5 min left. Hang tight if your connection is slow.

**Suppression rule**: if CC's last status update was <2 minutes ago AND the new numbers haven't moved meaningfully (same X MB), CC stays silent. Repeat-emitting "继续等" / "still downloading" with no new info is a bug.

If install fails (non-zero exit, network error, disk full): CC reads the tail of the log, surfaces the actual error in plain language ("下载断了，看起来是网络问题——要不要再试一次？"), and waits for the student's call.

**If `auth_path == "B"`**: skip this step entirely. CC says nothing.

### Step 5 — Write `.env` silently

CC's silent action: write `.env` file. **Never** ask the student to do this.

```python
# Path A
env_content = (
    "CANVAS_AUTH=cookie\n"
    f"CANVAS_TOKEN=\n"
    f"CANVAS_BASE={CANVAS_BASE}\n"
    f"CANVAS_WEB_BASE={CANVAS_WEB_BASE}\n"
)

# Path B
env_content = (
    "CANVAS_AUTH=token\n"
    f"CANVAS_TOKEN={user_pasted_token}\n"
    f"CANVAS_BASE={CANVAS_BASE}\n"
    f"CANVAS_WEB_BASE={CANVAS_WEB_BASE}\n"
)
```

Use `Write` tool. Do not announce ".env written" or any filename to the student.

If a `.env` already exists (e.g. student is re-running setup): read it first; **preserve** any non-Canvas keys the student may have added; only overwrite the four `CANVAS_*` keys.

### Step 6 — Trigger login (path A) or get token (path B)

**Path A** — CC silently runs a probe that triggers the headed browser:

```bash
python -m src.canvas_client --probe
```

The probe will pop a Chromium login window (handled inside `canvas_client.py:_login_interactive`).

CC says (literal pin, **immediately before** running the probe so the student knows what's about to happen):

> 浏览器要弹出来。你照常登 Canvas，登完它自己关。

> Browser is about to pop up. Log in to Canvas like normal, it'll close itself when it's done.

CC waits for: probe to return successfully (Canvas accepted the session, cookies persisted to `.cookies/session.json`).

If probe fails because the student didn't complete login within 5 minutes: CC says "我没看到你登好——是浏览器没起来，还是中间卡住了？"  and waits.

If probe fails because `playwright` import broke (rare; install was supposed to handle this): CC silently reruns the install bundle once more, then retries the probe. Don't surface the install failure to the student unless it fails twice.

**Path B** — CC says (literal pin, only this branch may name Canvas back-office UI):

> 去 Canvas → 右上头像 → Account → Settings → 拉到底找 "Approved Integrations" → "+ New Access Token"。Purpose 随便填，Expires 留空。生成后会显示一个长字符串，**只显示一次**，复制粘给我。

> In Canvas: top-right avatar → Account → Settings → scroll to "Approved Integrations" → "+ New Access Token". Purpose: anything. Expires: leave blank. It'll show a long string **once** — copy it and paste it to me.

CC waits for: a string that looks like a Canvas token (long alphanumeric, usually 70+ chars, often contains `~`).

CC then writes `.env` with the token (Step 5 already happened with empty `CANVAS_TOKEN`; CC re-runs Step 5 with the actual value), and runs:

```bash
python -m src.canvas_client --probe
```

If probe returns 401: token is wrong. CC says "Canvas 不认这个 token——你确定复制完整了吗？再贴一次。" and waits. Do not assume the student needs to re-navigate.

### Step 7 — List active courses, ask which to handle

CC's silent action: list active courses via `canvas_client`:

**Empirical noise level**: Canvas's `enrollment_state='active'` returns ~70% noise — last term's not-yet-archived courses, school onboarding spaces ("Anteater Virtues", "First-Year Orientation Space"), year-long companion labs that are empty, AEPE/placement-exam shells. A naive list of all 10 active courses is bad UX: the student has to mentally filter through "is this onboarding garbage" 6 times to find the real ones.

Apply the same 2-layer filter `canvas-bootstrap` uses (`canvas-bootstrap` adds a 3rd layer based on assignment-pattern recurrence, which we can't do at setup time since we haven't bucketed yet):

```python
import sys
sys.path.insert(0, ".")
from src import canvas_client as cv
from src.recurring_patterns import is_course_active

raw_courses = cv.get('/courses', enrollment_state='active', include=['term'])

real = []
hidden = []
for c in raw_courses:
    # Layer 1: term ended >7 days ago → last term's leftover, hide
    if not is_course_active(c, grace_days=7):
        hidden.append((c, "ended"))
        continue
    # Layer 2: 0 assignments → onboarding space / empty companion lab, hide
    try:
        if not cv.list_assignments(c["id"]):
            hidden.append((c, "empty"))
            continue
    except Exception:
        hidden.append((c, "empty"))
        continue
    real.append(c)
```

CC presents `real` to the student by name. **Don't show `hidden` by default** — but tell the student the count so they know filtering happened (transparency: students should be able to override if a course got mis-filtered).

CC says (literal pin):

> 登好了。你这学期这几门课：
>
> - <课程名 1>
> - <课程名 2>
> - <课程名 3>
> - ...
>
> （另外还有 N 门看起来是空课 / 上学期残留 / 学校 onboarding——默认不看；要看告诉我）
>
> 哪些要我看 Canvas 上的作业？默认全部。

> Logged in. These are your courses this term:
>
> - <Course Name 1>
> - <Course Name 2>
> - <Course Name 3>
> - ...
>
> (Plus N others that look like empty / last-term / onboarding spaces — hidden by default; tell me if you want them in.)
>
> Which ones should I track? Default is all of these.

If `hidden` is empty (rare), drop the parenthetical line.

CC waits for: a selection. Accept "all" / "全部" / silence (= all of `real`) / a list of names ("just the first three" / "前两个和最后一个" / "skip the writing one") / "show me all" / "show me the hidden ones" (re-render with `hidden` expanded, each gets a number too). For ambiguous input ("the easy ones"), ask one clarifying question, don't guess.

CC silently maps the student's response to a list of `course_id` integers internally — never shown.

### Step 8 — Write `courses.yaml` silently

CC's silent action: use `Write` (or read-then-Edit if file exists) to create:

```yaml
# Generated by canvas-setup. Edit if needed.
pending_window_days: 7

routes:
  # course_id: skill-name
  # Skills will be filled in by canvas-bootstrap (next).
  <id_1>:
  <id_2>:
  <id_3>:
```

Each route's value is left blank — `canvas-bootstrap` (Step 9) will fill in skill names per course.

If `SECRETS.md` exists, CC also updates the "Active courses" table inside it (read first, replace just that section). If `SECRETS.md` doesn't exist, CC creates it from `SECRETS.example.md` (if that template exists; otherwise creates minimal).

CC says nothing about writing these files. The student does not need to know.

### Step 9 — Hand off to canvas-bootstrap

CC says (literal pin):

> 配好了。下面给每门课设计 skill——决定每门课怎么自动化。我从最简单的开始问你。

> All set. Now I'll help you design a skill for each course — how each course should be automated. I'll start with the simplest one.

CC then invokes `canvas-bootstrap` via the `Skill` tool, passing:

> "canvas-setup completed. Routes are written but skill-name values are blank. Run the fingerprint flow on each course in routes, ordered by ease-of-config tier, and write SKILL.md skeletons + fill in the route names."

`canvas-bootstrap` takes over from here. canvas-setup exits.

### Step 10 — End condition

When `canvas-bootstrap` returns, CC says (literal pin):

> 全部配完了。现在你可以说 "scan canvas" 让我看这周有什么要交。

> Setup complete. Say "scan canvas" whenever you want me to look at what's due.

This skill exits.

---

## Error / interruption recovery

**Student ctrl+C mid-setup, comes back later**: CC detects partial state on next session entry:
- `.env` doesn't exist → started with fresh first-run, restart at Step 1
- `.env` exists but `CANVAS_BASE` empty → restart at Step 2
- `.env` complete but no `.cookies/session.json` and `CANVAS_AUTH=cookie` → restart at Step 6 (re-trigger login)
- `.env` complete + cookies/token works but `courses.yaml.routes` empty → restart at Step 7

CC does not ask the student "where did we leave off". CC reads the filesystem state and resumes silently from the right step.

**Student wants to redo setup from scratch**: explicit trigger phrases like "redo setup" / "重新配", or `/canvas-setup` invoked manually. CC says "你想全部重来还是只改某一步（学校换了 / 课程列表 / 登录方式）？" and routes accordingly. **Never** silently overwrite working config.

**Student wants to uninstall**: out of scope for v1. If asked, CC explains what files are involved (`.env`, `.cookies/`, the playwright binaries) and lets the student decide what to delete.

---

## What this skill MUST NOT do

- Tell the student to run any shell command. CC has Bash; CC runs it.
- Tell the student to edit any file. CC has Edit/Write; CC writes it.
- Show the student a file path, command, environment variable name, or API field name.
- Ask the student a question whose answer CC could discover by running a check.
- Pre-announce a multi-step workflow ("first I'll do X, then Y, then Z..."). Steps happen silently when their time comes.
- Mix two questions into one turn. Single domain question per message.
- Repeat status messages with no new content.
- Skip the value-statement opening (Step 1) and jump to "what's your Canvas URL". The opening is mandatory.
