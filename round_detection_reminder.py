#!/usr/bin/env python3
# @bigd-hook-meta
# name: round_detection_reminder
# fires_on: UserPromptSubmit
# relevant_intents: [debug_round, debug]
# irrelevant_intents: []
# cost_score: 1
# always_fire: false
"""
round_detection_reminder.py -- UserPromptSubmit hook (additive).

Trigger: user mentions Nth-round debugging on the same bug, or cites a prior debug
conclusion ("already ruled out", "tried that", "round 3 proved").

Action: inject reminder to consult `.ship/<slug>/experiments/rounds.md` and re-run
the multi-round confound check before trusting any inherited conclusion.

Lesson source: pm-london wedge 2026-04-25 — 5 rounds of "flag = trigger" debugging
where each round inherited the previous round's premise without verifying isolation.
Premise turned out confounded by 52 LOC of main.ts shipped in same commit as flag flip.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _semantic_router import should_fire

TRIGGER_PATTERNS = [
    r"\bround\s*\d+\b",
    r"\b(?:already|previously)\s+(?:tried|ruled\s+out|tested|debugged|proved|disproved)\b",
    r"\btried\s+(?:that|already|before)\b",
    r"\b(?:we|i)\s+(?:already|previously)\s+(?:proved|showed|confirmed|disproved|tested)\b",
    r"\bN\s*>\s*1\s+rounds?\b",
    r"\b(?:fresh\s+eyes|deeper\s+audit|mystery)\b",
    r"\b(?:falsified|exonerated|ruled\s+out)\b",
    r"\b(?:we|i)\s+(?:tried|tested)\s+(?:[A-Za-z0-9_,\s]+,\s*){2,}",
]

REMINDER = """\
[round-detection reminder] Multi-round debug pattern detected.

Before trusting any inherited conclusion from prior rounds:
1. Locate the slug: which `.ship/<slug>/experiments/rounds.md`? If missing, the prior rounds were not logged with isolation discipline — treat every cited conclusion as `[unverified]`.
2. Run `git diff <prev-round-SHA>..<this-round-SHA> -- <relevant paths>`. If MORE than the claimed variable changed, the prior round was confounded. Conclusions built on that round do not count as evidence.
3. Phrases like "mystery", "fresh eyes", "needs deeper audit" inside prior docs = explicit admission the premise was unresolved. Treat the entire doc as inherited claims, not facts.
4. Apply the 3-question causal-claim gate before any "X caused Y", "Z is falsified", "ruled out W" verb in your reply: (a) what else changed? (b) single snapshot or N≥2? (c) any inherited premise unverified this session? If fuzzy, downgrade to "consistent with" / "suggestive signal".

Templates:
- `~/.claude/skills/ship/phases/common/rounds.md` — round entry format
- `~/.claude/skills/ship/phases/common/observations.md` — observation entry format

Rules:
- `~/.claude/CLAUDE.md` → Multi-round debug confound check + Causal-claim gate
- `~/.claude/rules/ship.md` → Debug-round isolation discipline + Observations log + Causal chain completeness
"""


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    prompt = (payload.get("prompt") or "").lower()
    if not any(re.search(p, prompt) for p in TRIGGER_PATTERNS):
        sys.exit(0)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": REMINDER,
        }
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    _raw_stdin = sys.stdin.read()
    try:
        _prompt = json.loads(_raw_stdin).get("prompt", "")
    except Exception:
        _prompt = ""
    sys.stdin = io.StringIO(_raw_stdin)
    if not should_fire(__file__, _prompt):
        print("{}")
        sys.exit(0)
    main()
