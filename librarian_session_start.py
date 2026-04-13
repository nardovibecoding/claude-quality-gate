#!/usr/bin/env python3
"""SessionStart hook: check if there's unfiled scratch content from a previous session."""
import json
import sys
from pathlib import Path

SCRATCH = Path.home() / "NardoWorld/meta/scratch.md"


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    if not SCRATCH.exists():
        print("{}")
        return

    content = SCRATCH.read_text().strip()
    if not content:
        print("{}")
        return

    line_count = len(content.split("\n"))
    print(json.dumps({
        "systemMessage": (
            f"NardoWorld: unfiled scratch log from previous session "
            f"({line_count} lines at ~/NardoWorld/meta/scratch.md). "
            f"Review it and file anything important to NardoWorld, "
            f"then clear the file. Do this before starting new work."
        )
    }))


if __name__ == "__main__":
    main()
