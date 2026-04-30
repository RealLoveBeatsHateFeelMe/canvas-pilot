"""SessionStart hook: warn if `python setup.py` was never run.

Detects that `.claude/settings.json` still contains the `__PROJECT_ROOT__`
literal placeholder — meaning the user fork-cloned the repo and started a CC
session before running `python setup.py`. In that state, EVERY hook command
is broken (path doesn't resolve), so all safety checks silently no-op.

This hook MUST itself be invokable WITHOUT setup.py having run, so its
command in `.claude/settings.json` is a relative path (working directory is
the project root at SessionStart time) — not the `__PROJECT_ROOT__/...`
template the other hooks use.

Output goes to stdout: SessionStart hook stdout is shown to Claude as
additional context (unlike most other events where stdout is debug-only).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import ROOT, read_event, safe_main  # noqa: E402


@safe_main
def main():
    # Windows console defaults to gbk and chokes on emoji/中文; force utf-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    _ = read_event()  # drain stdin so the pipe doesn't break

    settings_path = ROOT / ".claude" / "settings.json"
    if not settings_path.exists():
        return  # no settings.json — nothing to check

    text = settings_path.read_text(encoding="utf-8")
    if "__PROJECT_ROOT__" not in text:
        return  # setup.py has been run; placeholder is gone; we're good

    # Placeholder still present → setup.py never ran → every hook command
    # in this repo references a non-existent path, so all safety checks are
    # silently no-op'ing right now. Tell Claude immediately.
    print("\n".join([
        "",
        "=" * 70,
        "⚠️  SETUP NOT COMPLETE — `python setup.py` was never run",
        "=" * 70,
        "",
        ".claude/settings.json still contains the `__PROJECT_ROOT__` placeholder.",
        "Every hook command in this project references a path that doesn't",
        "resolve, so ALL safety checks are silently no-op'ing right now:",
        "",
        "  - result.json schema validation: NOT RUNNING",
        "  - Stop-gate router-complete check: NOT RUNNING",
        "  - presubmit audit (where present): NOT RUNNING",
        "",
        "**Surface this to the user immediately**: ask them to run",
        "`python setup.py` once at the repo root. It rewrites the placeholder",
        "to this machine's actual path (takes <1 second). Then this warning",
        "won't reappear next session.",
        "",
        "Until they do, treat any hook 'pass' as untrustworthy — the hooks",
        "aren't actually running.",
        "=" * 70,
        "",
    ]))


if __name__ == "__main__":
    main()
