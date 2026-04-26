#!/usr/bin/env python3
# @bigd-hook-meta
# name: api_key_lookup
# fires_on: PreToolUse
# relevant_intents: [code, meta, debug]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, vps, sync, memory]
# cost_score: 1
# always_fire: false
"""PreToolUse hook: remind to check reference_api_keys_locations.md before searching for keys."""
import io
import json
import os
import re
import sys


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Check Bash grep/find for env vars or .env files
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if re.search(r'grep.*(_API_KEY|_TOKEN|_SECRET|\.env)|find.*\.env|cat.*\.env', cmd):
            print(json.dumps({
                "systemMessage": (
                    "📋 **Check `reference_api_keys_locations.md` first** — "
                    "it has all API keys, worker code, credentials, and where everything lives. "
                    "No need to grep."
                )
            }))
            return

    # Check Grep tool for env var patterns
    if tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        if re.search(r'_API_KEY|_TOKEN|_SECRET|\.env', pattern):
            print(json.dumps({
                "systemMessage": (
                    "📋 **Check `reference_api_keys_locations.md` first** — "
                    "it has all API keys and locations indexed."
                )
            }))
            return

    print("{}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
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
    main()
