#!/usr/bin/env python3
# @bigd-hook-meta
# name: inject_current_time
# fires_on: UserPromptSubmit
# always_fire: true
# cost_score: 1
"""UserPromptSubmit hook: inject current wall-clock time.

Prevents stale-timestamp bugs when a session pauses for hours
(e.g. overnight) — ensures every prompt receives fresh time context
instead of relying on stale `date` output from earlier tool calls.
"""
import datetime
import json
import sys


def main() -> None:
    # Consume stdin to be polite (hook protocol sends JSON input).
    try:
        sys.stdin.read()
    except Exception:
        pass

    now_local = datetime.datetime.now().astimezone()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    local_str = now_local.strftime("%a %Y-%m-%d %H:%M:%S %Z")
    utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    epoch = int(now_utc.timestamp())

    msg = f"[clock] {local_str} ({utc_str}, epoch {epoch})"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg,
        }
    }))


if __name__ == "__main__":
    main()
