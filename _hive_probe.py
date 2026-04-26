#!/usr/bin/env python3
# @bigd-hook-meta
# name: _hive_probe
# fires_on: PreToolUse
# always_fire: false
# cost_score: 0
"""Phase A probe: verify updatedInput.prompt mutation reaches sub-agent.

Prepends <<HIVE_PROBE_MARKER_v1>> to Agent tool_input.prompt.
Logs every invocation to /tmp/hive_probe.log.
TEMPORARY — replaced by hive_bootstrap.py after probe passes.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("/tmp/hive_probe.log")
MARKER = "<<HIVE_PROBE_MARKER_v1>>\n\n"


def _ts():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    if data.get("tool_name") != "Agent":
        print("{}")
        return

    tool_input = data.get("tool_input", {})
    original_prompt = tool_input.get("prompt", "")

    if not original_prompt:
        print("{}")
        return

    mutated_prompt = MARKER + original_prompt

    # Log before/after
    log_entry = (
        f"[{_ts()}] PROBE FIRED\n"
        f"  before: {repr(original_prompt[:100])}\n"
        f"  after:  {repr(mutated_prompt[:120])}\n"
    )
    try:
        with LOG_FILE.open("a") as f:
            f.write(log_entry)
    except OSError:
        pass

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {
                "prompt": mutated_prompt,
            }
        }
    }))


if __name__ == "__main__":
    main()
