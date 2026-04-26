"""Shared utilities for Canvas Pilot hook scripts.

All hook scripts read a JSON event from stdin and exit with:
  0 = pass (Claude continues normally)
  2 = block (stderr is shown to Claude as feedback)

Anything else is treated as a non-blocking error by Claude Code.

CRITICAL SAFETY RULE: hook scripts MUST NEVER raise an unhandled exception
or exit with a non-zero non-2 code. If they do, CC may interpret it as a
block, feed the traceback back to Claude, and Claude will be stuck in a
runaway loop trying to fix something that's actually a hook bug. Wrap your
main() in @safe_main and you'll exit 0 (pass-through) on any internal error.
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import os
import sys
import traceback
from pathlib import Path

# Project root — hooks live in <root>/.claude/hooks/
ROOT = Path(__file__).resolve().parent.parent.parent


def read_event() -> dict:
    """Read the hook event JSON from stdin. Empty stdin → empty dict (so we
    can run scripts manually for testing without piping anything)."""
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"hook: stdin not valid JSON: {e}", file=sys.stderr)
        return {}


def block(message: str) -> None:
    """Exit 2 with a message to stderr — Claude sees this and must respond."""
    print(message, file=sys.stderr)
    sys.exit(2)


def passthrough(message: str | None = None) -> None:
    """Exit 0. Optional message goes to stdout (debug log only, Claude doesn't see it)."""
    if message:
        print(message)
    sys.exit(0)


def safe_main(fn):
    """Decorator: wrap a hook main() so that ANY internal error is caught
    and converted to a passthrough exit 0. This prevents runaway loops where
    a buggy hook script erroring out gets interpreted by CC as a block.

    The full traceback is written to a hook-errors.log file next to this
    module so we can debug after the fact without burning Claude tokens.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SystemExit:
            raise  # Let intentional sys.exit() through
        except BaseException as e:
            try:
                log = Path(__file__).resolve().parent / "hook-errors.log"
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"\n--- {dt.datetime.now().isoformat()} {fn.__name__} ---\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass
            # Always exit 0 to avoid blocking Claude
            print(f"hook safe_main: caught {type(e).__name__}, passing through", file=sys.stderr)
            sys.exit(0)
    return wrapper


def today_dir() -> Path:
    """The runs/<today>/ directory in the system's local timezone."""
    return ROOT / "runs" / dt.date.today().isoformat()


def project_root() -> Path:
    return ROOT


def is_path_under(p: Path, parent: Path) -> bool:
    try:
        p.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, FileNotFoundError):
        return False


def matches_result_json(file_path: str | None) -> bool:
    """Returns True if the given path looks like a `runs/.../result.json`,
    whether the path is relative or absolute."""
    if not file_path:
        return False
    p = Path(file_path).as_posix()
    if not p.endswith("/result.json"):
        return False
    return p.startswith("runs/") or "/runs/" in p


# ---- result.json schema ----

VALID_STATUSES = {"draft_ready", "submitted", "skipped", "error"}
REQUIRED_FIELDS = {"status"}


def validate_result_schema(content: str, file_path: Path | None = None) -> tuple[bool, str]:
    """Validate a result.json blob. Returns (ok, error_message)."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"result.json is not valid JSON: {e}"

    if not isinstance(data, dict):
        return False, f"result.json must be a JSON object, got {type(data).__name__}"

    missing = REQUIRED_FIELDS - data.keys()
    if missing:
        return False, f"result.json missing required fields: {sorted(missing)}"

    status = data.get("status")
    if status not in VALID_STATUSES:
        return False, (
            f"result.json status={status!r} is not one of "
            f"{sorted(VALID_STATUSES)}. Use 'draft_ready' for finished drafts, "
            f"'submitted' for items the user has confirmed they uploaded, "
            f"'skipped' for items intentionally not done, 'error' for failures."
        )

    if status == "draft_ready":
        draft_path = data.get("draft_path")
        if not draft_path:
            return False, (
                "result.json status='draft_ready' but no draft_path field. "
                "Add draft_path pointing to the file the user should review."
            )
        candidate = (ROOT / draft_path) if not Path(draft_path).is_absolute() else Path(draft_path)
        if not candidate.exists():
            return False, (
                f"result.json draft_path={draft_path!r} does not exist on disk. "
                f"Either create the file or change status away from 'draft_ready'."
            )

    if status == "submitted":
        if not data.get("draft_path") and not data.get("submitted_at"):
            return False, (
                "result.json status='submitted' should have either draft_path or "
                "submitted_at to provide an audit trail."
            )

    return True, ""
