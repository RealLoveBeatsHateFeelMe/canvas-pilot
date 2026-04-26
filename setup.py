"""First-time setup: rewrite the __PROJECT_ROOT__ placeholder in
.claude/settings.json to point at this clone's actual location.

Why: Claude Code hooks need absolute paths in their `command` fields.
$CLAUDE_PROJECT_DIR can get mangled by Git Bash on Windows (msys2
rewrites `C:\\Users\\...` to `/c/Users/...` in some contexts), so the
safe pattern is to ship a template with a sentinel placeholder and
rewrite it once on clone.

Idempotent: re-running on the same machine is a no-op.

Usage:
    python setup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PLACEHOLDER = "__PROJECT_ROOT__"

TARGETS = [
    ".claude/settings.json",
]


def main() -> int:
    here = Path(__file__).resolve().parent
    new_path = str(here).replace("\\", "/")

    print(f"Configuring Canvas Pilot at:")
    print(f"  {new_path}")
    print()

    total = 0
    for rel in TARGETS:
        p = here / rel
        if not p.exists():
            print(f"  [skip] {rel} (not found)")
            continue
        text = p.read_text(encoding="utf-8")
        n = text.count(PLACEHOLDER)
        if n == 0:
            if new_path in text:
                print(f"  [ok ] {rel} (already configured)")
            else:
                print(f"  [ok ] {rel} (no placeholder)")
            continue
        new = text.replace(PLACEHOLDER, new_path)
        p.write_text(new, encoding="utf-8")
        total += n
        print(f"  [fix] {rel} ({n} replacement{'s' if n != 1 else ''})")

    print()
    print(f"Done. {total} replacement(s) total.")
    print()
    print("Next steps:")
    print("  1. cp .env.example .env       # then fill in CANVAS_TOKEN")
    print("  2. cp SECRETS.example.md SECRETS.md   # then fill in your courses")
    print("  3. pip install requests pyyaml")
    print("  4. Open this folder in Claude Code, say: scan canvas")
    print()
    print("Don't commit the modified .claude/settings.json back to origin —")
    print("it now contains your local path. .gitignore can be updated to")
    print("ignore it if you plan to track other settings/ changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
