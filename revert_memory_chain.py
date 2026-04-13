#!/usr/bin/env python3
"""PostToolUse hook: after git revert or 'remove:' commit, remind to update memory."""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from hook_base import run_hook


def check(tool_name, tool_input, input_data):
    if tool_name != "Bash":
        return False
    cmd = tool_input.get("command", "")
    return bool(re.search(
        r"git\s+revert|"
        r'git\s+commit.*["\'](remove|revert|undo|rollback)',
        cmd, re.IGNORECASE
    ))


def action(tool_name, tool_input, input_data):
    return (
        "📋 **Revert detected.** Update memory to mark this as tried+rejected:\n"
        "1. Find the relevant memory file\n"
        "2. Add: what was tried, why it was reverted, what to do instead\n"
        "3. This prevents re-proposing the same approach in future sessions"
    )


if __name__ == "__main__":
    run_hook(check, action, "revert_memory_chain")
