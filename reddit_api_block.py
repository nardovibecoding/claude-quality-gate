#!/usr/bin/env python3
# @bigd-hook-meta
# name: reddit_api_block
# fires_on: PostToolUse
# relevant_intents: [code, debug]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, git, vps, sync, memory]
# cost_score: 1
# always_fire: false
"""PostToolUse hook: block Reddit OAuth API usage — Reddit API is dead, use scraping."""
import io
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from hook_base import run_hook


def check(tool_name, tool_input, input_data):
    if tool_name not in ("Edit", "Write"):
        return False
    content = tool_input.get("new_string", "") or tool_input.get("content", "")
    return bool(re.search(
        r"REDDIT_CLIENT_ID|REDDIT_CLIENT_SECRET|praw\.Reddit\(|"
        r"reddit_client_id|reddit_client_secret",
        content
    ))


def action(tool_name, tool_input, input_data):
    return (
        "⛔ **Reddit OAuth API is dead.** Do not use REDDIT_CLIENT_ID/SECRET or praw. "
        "Reddit revoked free API access. Use web scraping (fetch_watchdog probes) instead."
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
    run_hook(check, action, "reddit_api_block")
