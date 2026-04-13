#!/usr/bin/env python3
"""UserPromptSubmit hook: remind Claude to check memory for recall-type questions."""
import json
import re
import sys

RECALL_PATTERNS = re.compile(
    r"("
    r"are we using|do we (have|use)|did we|have we (tried|used|installed|set up)"
    r"|remember when|do you remember|check.*(memory|if we)"
    r"|already (have|using|installed|set up|tried)"
    r"|we using.+already|we have.+already"
    r"|using this already|have this already"
    r"|didn.t we|wasn.t that|weren.t we"
    r"|last time we|before we|previously"
    r")",
    re.IGNORECASE,
)


def main():
    try:
        hook_input = json.load(sys.stdin)
        prompt = hook_input.get("prompt", "")
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    if RECALL_PATTERNS.search(prompt):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "\u26a0\ufe0f RECALL QUESTION DETECTED. "
                    "Check ALL memory dirs BEFORE answering:\n"
                    "  1. Project: ~/.claude/projects/-Users-bernard-polymarket-bot/memory/\n"
                    "  2. Home: ~/.claude/projects/-Users-bernard/memory/\n"
                    "Do NOT say 'not using' or 'don't have' without checking memory first."
                )
            }
        }))
    else:
        print("{}")


if __name__ == "__main__":
    main()
