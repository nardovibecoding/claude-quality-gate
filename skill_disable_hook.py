#!/usr/bin/env python3
# @bigd-hook-meta
# name: skill_disable_hook
# fires_on: PostToolUse
# always_fire: true
# cost_score: 1
"""PostToolUse hook on Skill: disable skill after invocation (return to .disabled)."""
import json
import sys
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude/skills"
TRACKER = Path("/tmp/claude_skill_enabled.txt")


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    # Check if we enabled a skill in PreToolUse
    if not TRACKER.exists():
        print("{}")
        return

    skill_name = TRACKER.read_text().strip()
    TRACKER.unlink(missing_ok=True)

    if not skill_name:
        print("{}")
        return

    enabled = SKILLS_DIR / skill_name / "SKILL.md"
    disabled = SKILLS_DIR / skill_name / "SKILL.md.disabled"

    if enabled.exists() and not disabled.exists():
        enabled.rename(disabled)
        print(json.dumps({"systemMessage": f"Skill '{skill_name}' disabled after use."}))
    else:
        print("{}")


if __name__ == "__main__":
    main()
