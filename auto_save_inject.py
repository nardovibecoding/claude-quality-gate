#!/usr/bin/env python3
# @bigd-hook-meta
# name: auto_save_inject
# fires_on: PreToolUse
# always_fire: true
# cost_score: 1
"""PreToolUse hook: inject auto-save when marker file exists.

Reads /tmp/claude_auto_save_needed (written by context_50_check.py).
Injects systemMessage telling Claude to run /s (background Haiku agent).
Deletes marker after injection so it only fires once per threshold crossing.
"""
import json
from pathlib import Path

MARKER = Path("/tmp/claude_auto_save_needed")


def main():
    if not MARKER.exists():
        print("{}")
        return

    try:
        data = json.loads(MARKER.read_text())
        pct = data.get("pct", "?")
    except (json.JSONDecodeError, OSError):
        pct = "?"

    # Delete marker so we only inject once
    MARKER.unlink(missing_ok=True)

    print(json.dumps({
        "systemMessage": (
            f"CONTEXT AT {pct:.0f}%. Run /s NOW. "
            f"1. Set tab title (bash, foreground). "
            f"2. Spawn ONE background Agent (model=sonnet, run_in_background=true) to: "
            f"write tight convo summary to memory (max 150 words, 3-7 bullets: what changed, decisions, pending — skip narration; do NOT add to MEMORY.md index), file atoms to ~/NardoWorld/. "
            f"3. Print 'Saving... /clear' so user can /clear immediately. "
            f"4. Then answer the user's message normally. "
            f"Do not ask permission. Do this alongside your response."
        )
    }))


if __name__ == "__main__":
    main()
