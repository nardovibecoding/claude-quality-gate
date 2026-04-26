#!/usr/bin/env python3
# @bigd-hook-meta
# name: task_auto_continue
# fires_on: TaskCompleted
# always_fire: true
# cost_score: 1
"""TaskCompleted hook: nudge Claude to continue with next unblocked task."""
import json
import sys

def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "TaskCompleted",
            "additionalContext": "Task completed. Check TaskList for unblocked tasks and start the next one immediately. Do NOT ask the user."
        }
    }))

if __name__ == "__main__":
    main()
