"""Stop hook: the closeout gate.

When a Claude session wants to stop, this hook verifies that every assignment
in today's assignments.json has a corresponding result.json with a valid status.
If any are missing, exit 2 + stderr forces Claude to keep going.

To prevent infinite loops, we honor the `stop_hook_active` flag in the event.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import (  # noqa: E402
    block,
    passthrough,
    read_event,
    safe_main,
    today_dir,
    validate_result_schema,
)


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_\- ]", "", s or "")
    return re.sub(r"\s+", "_", s).strip("_")[:60] or "untitled"


@safe_main
def main():
    event = read_event()

    # Avoid infinite loops: if we already blocked once and Claude is back here,
    # let it stop. CC sets this flag when the previous Stop was blocked by a hook.
    if event.get("stop_hook_active"):
        passthrough("hook check-router-complete: stop_hook_active=true, releasing")

    today = today_dir()

    # Only gate sessions that explicitly opted into execute-mode by touching
    # the marker file. Bootstrap sessions, manual `claude` invocations, etc.
    # pass through silently. The canvas-execute skill creates this marker
    # when it starts and deletes it when it's done. canvas-scan never
    # creates this marker — scan produces plan.json and ends cleanly.
    marker = today / ".scan_in_progress"
    if not marker.exists():
        passthrough(
            "hook check-router-complete: no .scan_in_progress marker, "
            "this session is not in execute mode, releasing"
        )

    aj = today / "assignments.json"
    if not aj.exists():
        passthrough("hook check-router-complete: marker exists but no assignments.json, releasing")

    try:
        items = json.loads(aj.read_text(encoding="utf-8"))
    except Exception as e:
        passthrough(f"hook check-router-complete: assignments.json unreadable ({e}), passing")

    if not isinstance(items, list) or not items:
        passthrough("hook check-router-complete: assignments.json empty, nothing to verify")

    missing = []
    invalid = []

    for item in items:
        course_slug = slugify(item.get("course_name", ""))
        asg_slug = slugify(item.get("name", ""))
        wd = today / f"{course_slug}__{asg_slug}"
        rj = wd / "result.json"

        if not rj.exists():
            missing.append({
                "course_id": item.get("course_id"),
                "assignment_id": item.get("assignment_id"),
                "name": item.get("name"),
                "skill": item.get("skill"),
                "expected_path": str(rj.relative_to(today.parent.parent)),
            })
            continue

        try:
            content = rj.read_text(encoding="utf-8")
            ok, err = validate_result_schema(content, rj)
            if not ok:
                invalid.append({
                    "name": item.get("name"),
                    "path": str(rj.relative_to(today.parent.parent)),
                    "error": err,
                })
        except Exception as e:
            invalid.append({
                "name": item.get("name"),
                "path": str(rj.relative_to(today.parent.parent)),
                "error": f"could not read: {e}",
            })

    if not missing and not invalid:
        passthrough(f"hook check-router-complete: all {len(items)} assignments accounted for")

    msg_lines = ["hook check-router-complete: SESSION CANNOT STOP YET."]
    msg_lines.append("")

    if missing:
        msg_lines.append(f"{len(missing)} assignment(s) have no result.json:")
        for m in missing:
            msg_lines.append(
                f"  - {m['course_id']}:{m['assignment_id']} | "
                f"skill={m['skill']} | {m['name']}"
            )
            msg_lines.append(f"      expected at: {m['expected_path']}")
        msg_lines.append("")
        msg_lines.append(
            "→ For each missing assignment, you must EITHER invoke the "
            "appropriate user-defined skill (whatever the routing config "
            "says) OR write a result.json directly with status='skipped' "
            "and notes explaining why this assignment cannot be done now."
        )
        msg_lines.append("")

    if invalid:
        msg_lines.append(f"{len(invalid)} result.json file(s) are invalid:")
        for inv in invalid:
            msg_lines.append(f"  - {inv['name']}")
            msg_lines.append(f"      path: {inv['path']}")
            msg_lines.append(f"      → {inv['error']}")
        msg_lines.append("")
        msg_lines.append("→ Fix the schemas above before stopping.")

    msg_lines.append("")
    msg_lines.append("After fixing, you can attempt to stop again.")

    block("\n".join(msg_lines))


if __name__ == "__main__":
    main()
