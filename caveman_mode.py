#!/usr/bin/env python3
"""Hook: inject caveman mode reminder into every response context."""
import json
import sys

result = {
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": (
            "CAVEMAN MODE ACTIVE. "
            "Drop articles/filler/pleasantries. Fragments. Max compression. "
            "Smart terse, not broken English. Self-check: delete unnecessary words before responding."
        )
    }
}
json.dump(result, sys.stdout)
