#!/usr/bin/env python3
"""Stop hook: nudge Claude to file anything worth keeping to NardoWorld.

Fires after Claude's full response so it can capture atoms from the
complete exchange (user input + Claude's response), not just user input.

Tracks last_filed timestamp so /s synthesis knows what's already been filed.
"""
import json
import sys
import time
from pathlib import Path

LAST_FILED = Path.home() / "NardoWorld/meta/last_filed"


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    # Don't fire if stop was due to error
    stop_reason = hook_input.get("stop_reason", "")
    if stop_reason in ("error", "api_error"):
        print("{}")
        return

    # Update last_filed timestamp
    try:
        LAST_FILED.parent.mkdir(parents=True, exist_ok=True)
        LAST_FILED.write_text(str(int(time.time())))
    except OSError:
        pass

    # Per-turn filing removed — now handled by /s batch scan of transcript JSONL.
    # This hook only updates last_filed timestamp for /s to know what's fresh.
    print("{}")


if __name__ == "__main__":
    main()
