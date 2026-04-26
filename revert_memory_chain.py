#!/usr/bin/env python3
# @bigd-hook-meta
# name: revert_memory_chain
# fires_on: PostToolUse
# relevant_intents: [git, memory]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, vps, sync, debug]
# cost_score: 1
# always_fire: false
"""PostToolUse hook: after git revert or 'remove:' commit, remind to update memory."""
import io
import json
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
    _raw = sys.stdin.read()
    try:
        _prompt = json.loads(_raw).get("prompt", "") if _raw else ""
    except Exception:
        _prompt = ""
    from _semantic_router import should_fire
    if not should_fire(__file__, _prompt):
        print("{}")
        sys.exit(0)
    sys.stdin = io.StringIO(_raw)
    run_hook(check, action, "revert_memory_chain")
