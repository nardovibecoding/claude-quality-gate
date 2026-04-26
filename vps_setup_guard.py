#!/usr/bin/env python3
# @bigd-hook-meta
# name: vps_setup_guard
# fires_on: PreToolUse
# relevant_intents: [vps, sync]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, git, code, memory, debug]
# cost_score: 1
# always_fire: false
# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""PreToolUse hook: warn when attempting complex inline SSH commands.

Detects ssh commands with heredocs, printf \\n chains, base64 blobs,
or long embedded strings — all of which break when piped through the
Claude Code terminal due to line wrapping.

Suggests using a committed script instead.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hook_base import run_hook

# Patterns that indicate a complex inline SSH command that will likely break
_HEREDOC = re.compile(r"ssh\b.*<<\s*['\"]?\w+['\"]?", re.DOTALL)
_PRINTF_NEWLINES = re.compile(r"ssh\b.*printf.*\\n.*\\n.*\\n", re.DOTALL)
_BASE64_BLOB = re.compile(r"ssh\b.*\|.*base64\s+-d", re.DOTALL)
_LONG_SSH = re.compile(r"ssh\b.{300,}", re.DOTALL)


def check(tool_name, tool_input, _input_data):
    if tool_name != "Bash":
        return False
    cmd = tool_input.get("command", "")
    return bool(
        _HEREDOC.search(cmd) or
        _PRINTF_NEWLINES.search(cmd) or
        _BASE64_BLOB.search(cmd) or
        _LONG_SSH.search(cmd)
    )


def action(_tool_name, tool_input, _input_data):
    cmd = tool_input.get("command", "")
    if _HEREDOC.search(cmd):
        reason = "heredoc over SSH"
    elif _BASE64_BLOB.search(cmd):
        reason = "base64 pipe over SSH"
    elif _PRINTF_NEWLINES.search(cmd):
        reason = "printf with embedded newlines over SSH"
    else:
        reason = "long inline SSH command"

    return (
        f"VPS SETUP GUARD: {reason} detected — terminal will wrap lines and break this.\n"
        f"Write a script to scripts/setup_X.sh, commit+push, then:\n"
        f"  ssh vps \"bash ~/telegram-claude-bot/scripts/setup_X.sh\""
    )


if __name__ == "__main__":
    import io
    import json
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
    run_hook(check, action, "vps_setup_guard")
