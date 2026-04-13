#!/usr/bin/env python3
"""PostToolUse hook: auto-update 'updated:' timestamp on memory/wiki files."""
import datetime
import json
import re
import sys
from pathlib import Path

MEMORY_DIR = Path.home() / ".claude" / "projects" / f"-Users-{Path.home().name}" / "memory"
WIKI_DIR = Path.home() / "NardoWorld"
TODAY = datetime.date.today().isoformat()


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    tool = data.get("tool_name", "")
    if tool not in ("Edit", "Write"):
        print("{}")
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        print("{}")
        return

    p = Path(file_path)
    if not (str(p).startswith(str(MEMORY_DIR)) or str(p).startswith(str(WIKI_DIR))):
        print("{}")
        return

    if not p.exists() or p.suffix != ".md":
        print("{}")
        return

    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        print("{}")
        return

    # Must have frontmatter
    if not text.startswith("---"):
        print("{}")
        return

    end = text.find("\n---", 3)
    if end == -1:
        print("{}")
        return

    front = text[3:end]
    body = text[end:]

    # Update or add 'updated:'
    if re.search(r"^updated:", front, re.MULTILINE):
        front = re.sub(r"^updated:.*$", f"updated: {TODAY}", front, flags=re.MULTILINE)
    else:
        front = front.rstrip("\n") + f"\nupdated: {TODAY}\n"

    # Add 'created:' if missing
    if not re.search(r"^created:", front, re.MULTILINE):
        front = front.rstrip("\n") + f"\ncreated: {TODAY}\n"

    new_text = "---" + front + body
    if new_text != text:
        p.write_text(new_text, encoding="utf-8")

    print("{}")


if __name__ == "__main__":
    main()
