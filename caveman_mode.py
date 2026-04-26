#!/usr/bin/env python3
# @bigd-hook-meta
# name: caveman_mode
# fires_on: UserPromptSubmit
# always_fire: true
# cost_score: 1
"""Hook: inject caveman mode reminder into every response context."""
import json
import sys

result = {
    "additionalContext": (
        "CAVEMAN MODE ACTIVE. "
        "Drop articles/filler/pleasantries. Fragments. Max compression. "
        "Smart terse, not broken English. Self-check: delete unnecessary words before responding."
    )
}
json.dump(result, sys.stdout)
