#!/usr/bin/env python3
"""UserPromptSubmit hook: surface pending tweet ideas, copy prompt to clipboard."""
import os
import json
import subprocess
import sys

PENDING_JSONL = os.path.expanduser("~/.tweet_ideas_pending.jsonl")
PENDING_JSON = os.path.expanduser("~/.tweet_ideas_pending.json")


def main():
    # Read user's prompt from stdin
    user_prompt = ""
    try:
        hook_input = json.load(sys.stdin)
        user_prompt = hook_input.get("prompt", "")
    except (json.JSONDecodeError, EOFError):
        pass

    all_items = []

    # JSONL format (accumulated)
    if os.path.exists(PENDING_JSONL):
        try:
            with open(PENDING_JSONL, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    all_items.extend(data.get("items", []))
            os.remove(PENDING_JSONL)
        except Exception:
            pass

    # Legacy single JSON format
    if os.path.exists(PENDING_JSON):
        try:
            with open(PENDING_JSON, "r") as f:
                data = json.load(f)
            all_items.extend(data.get("items", []))
            os.remove(PENDING_JSON)
        except Exception:
            pass

    if not all_items:
        print("{}")
        return

    lines = [f"📰 {len(all_items)} hot tweet idea(s):"]
    for item in all_items[:10]:
        title = item.get("title", "")
        url = item.get("url", "")
        source = item.get("source", "")
        if url:
            lines.append(f"  • {title} ({source})\n    {url}")
        else:
            lines.append(f"  • {title} ({source})")

    # Copy user's original prompt to clipboard so they can paste after
    if user_prompt:
        try:
            subprocess.run(["pbcopy"], input=user_prompt.encode(), check=True)
        except Exception:
            pass

    msg = "\n".join(lines)
    DUSTY_PINK = "\033[38;2;200;140;160m"
    RESET = "\033[0m"
    print(f"{DUSTY_PINK}{msg}{RESET}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
