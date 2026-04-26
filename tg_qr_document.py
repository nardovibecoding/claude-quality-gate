#!/usr/bin/env python3
# @bigd-hook-meta
# name: tg_qr_document
# fires_on: PreToolUse
# relevant_intents: [telegram]
# irrelevant_intents: [bigd, pm, docx, x_tweet, git, code, vps, sync, memory, debug]
# cost_score: 1
# always_fire: false
"""PreToolUse hook: warn to send QR codes as document not photo on Telegram."""
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

    # Check for TG reply tool with QR image
    if "telegram" not in tool_name and "reply" not in tool_name:
        print("{}")
        return

    files = tool_input.get("files", [])
    if not files:
        print("{}")
        return

    has_qr = any(
        re.search(r'qr|login|scan', str(f), re.IGNORECASE)
        for f in files
    )

    if has_qr:
        print(json.dumps({
            "systemMessage": (
                "⚠️ **QR code detected.** Send as document (not photo) on Telegram — "
                "photo compression can make QR codes unscannable."
            )
        }))
    else:
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
