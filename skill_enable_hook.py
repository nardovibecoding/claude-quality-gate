#!/usr/bin/env python3
# @bigd-hook-meta
# name: skill_enable_hook
# fires_on: PreToolUse
# always_fire: true
# cost_score: 1
"""PreToolUse hook on Skill: enable a disabled skill before invocation."""
import json
import sys
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude/skills"
CORE = {"s", "convos", "combo", "tab", "caveman", "librarian", "r1a", "recall"}


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    tool_input = data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    # Strip fully-qualified prefix (e.g., "ms-office-suite:pdf" → "pdf")
    if ":" in skill_name:
        skill_name = skill_name.split(":")[-1]

    if not skill_name or skill_name in CORE:
        print("{}")
        return

    disabled = SKILLS_DIR / skill_name / "SKILL.md.disabled"
    enabled = SKILLS_DIR / skill_name / "SKILL.md"

    if disabled.exists() and not enabled.exists():
        disabled.rename(enabled)
        # Track which skill we enabled so PostToolUse can disable it
        tracker = Path("/tmp/claude_skill_enabled.txt")
        tracker.write_text(skill_name)
        print(json.dumps({"systemMessage": f"Skill '{skill_name}' enabled on-demand."}))
    else:
        print("{}")


if __name__ == "__main__":
    main()
