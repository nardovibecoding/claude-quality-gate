#!/usr/bin/env python3
# @bigd-hook-meta
# name: memory_inject_reset
# fires_on: SessionStart
# always_fire: true
# cost_score: 1
"""SessionStart hook: reset memory inject state so fresh injection happens."""
import os
from pathlib import Path

MARKER_DIR = Path("/tmp/claude_memory_inject")


def main():
    tty = os.environ.get("CLAUDE_TTY_ID", "default")
    for suffix in [".json", "_topic.json"]:
        f = MARKER_DIR / f"{tty}{suffix}"
        f.unlink(missing_ok=True)
    print("{}")


if __name__ == "__main__":
    main()
