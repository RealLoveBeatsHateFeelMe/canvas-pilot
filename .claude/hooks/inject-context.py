"""SessionStart hook: inject Canvas Pilot project context into Claude's prompt.

stdout from a SessionStart hook is shown to Claude as additional context
(unlike most other events where stdout goes to debug log).

We inject:
1. A pointer to the project's CLAUDE.md / README.md
2. Today's pending list summary (or "no scan run today" if assignments.json missing)
3. A summary of past runs from runs/_processed.json if present
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import ROOT, today_dir, read_event, safe_main  # noqa: E402


@safe_main
def main():
    _ = read_event()

    lines = []
    lines.append("=" * 70)
    lines.append("CANVAS PILOT — Canvas assignment routing framework")
    lines.append("=" * 70)
    lines.append("")
    lines.append("You are running in a Canvas Pilot project. The framework scans")
    lines.append("Canvas for pending assignments and dispatches each to the user's")
    lines.append("course-specific skills (defined in .claude/skills/canvas-*/).")
    lines.append("")
    lines.append("ESSENTIAL CONTEXT:")
    lines.append("- Working directory: " + str(ROOT))
    lines.append("- Project doc: CLAUDE.md / README.md")
    lines.append("- Framework skills: .claude/skills/canvas-{scan,execute,skip}/SKILL.md")
    lines.append("- User-defined skills: .claude/skills/canvas-*/  (whatever the user adds)")
    lines.append("- Routing config: courses.yaml (course_id → skill mapping)")
    lines.append("- API client: src/canvas_client.py (READ-ONLY GETs only — no submit code)")
    lines.append("- Daily output: runs/<today>/")
    lines.append("- Cross-day dedup ledger: runs/_processed.json")
    lines.append("")

    today = today_dir()
    aj = today / "assignments.json"
    if aj.exists():
        try:
            items = json.loads(aj.read_text(encoding="utf-8"))
            lines.append(f"TODAY'S PENDING SCAN ({today.name}): {len(items)} items")
            for item in items[:30]:
                wd = today / f"{_slugify(item.get('course_name',''))}__{_slugify(item.get('name',''))}"
                rj = wd / "result.json"
                if rj.exists():
                    try:
                        r = json.loads(rj.read_text(encoding="utf-8"))
                        marker = f" [{r.get('status', '?')}]"
                    except Exception:
                        marker = " [result.json unreadable]"
                else:
                    marker = " [PENDING]"
                lines.append(
                    f"  - {item.get('skill','?'):18} | {item.get('course_name','?')[:24]:24} | "
                    f"{item.get('name','?')[:50]}{marker}"
                )
            if len(items) > 30:
                lines.append(f"  ... and {len(items) - 30} more")
        except Exception as e:
            lines.append(f"TODAY'S PENDING SCAN: failed to read assignments.json: {e}")
    else:
        lines.append("TODAY'S PENDING SCAN: not run yet today.")
        lines.append("First action should be: invoke canvas-scan skill (which produces plan.json).")

    lines.append("")

    pj = ROOT / "runs" / "_processed.json"
    if pj.exists():
        try:
            ledger = json.loads(pj.read_text(encoding="utf-8"))
            real = {k: v for k, v in ledger.items() if not k.startswith("_")}
            counts = {}
            for v in real.values():
                if isinstance(v, dict):
                    counts[v.get("status", "?")] = counts.get(v.get("status", "?"), 0) + 1
            lines.append(f"CROSS-DAY LEDGER ({len(real)} items): {counts}")
        except Exception as e:
            lines.append(f"CROSS-DAY LEDGER: unreadable: {e}")
    else:
        lines.append("CROSS-DAY LEDGER: empty (no prior runs)")

    lines.append("")
    lines.append("HOOK GUARDRAILS ACTIVE:")
    lines.append("- After every Write/Edit, hook validates result.json schema if path matches")
    lines.append("- On Stop, hook checks every assignment in assignments.json has a valid result.json")
    lines.append("  → if any are missing you will be required to continue and produce them.")
    lines.append("")
    lines.append("=" * 70)

    print("\n".join(lines))


def _slugify(s: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9_\- ]", "", s or "")
    return re.sub(r"\s+", "_", s).strip("_")[:60] or "untitled"


if __name__ == "__main__":
    main()
