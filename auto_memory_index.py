#!/usr/bin/env python3
# @bigd-hook-meta
# name: auto_memory_index
# fires_on: PostToolUse
# relevant_intents: [memory, meta]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, git, code, vps, sync, debug]
# cost_score: 1
# always_fire: false
"""PostToolUse hook: check if new memory file is in MEMORY.md index."""
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from hook_base import run_hook

MEMORY_DIR = Path.home() / ".claude/projects/-Users-bernard/memory"
INDEX = MEMORY_DIR / "MEMORY.md"


def check(tool_name, tool_input, input_data):
    if tool_name != "Write":
        return False
    file_path = tool_input.get("file_path", "")
    filename = Path(file_path).name
    return (
        "memory/" in file_path
        and file_path.endswith(".md")
        and "MEMORY.md" not in file_path
        and not filename.startswith("convo_")
    )


def action(tool_name, tool_input, input_data):
    file_path = tool_input.get("file_path", "")
    filename = Path(file_path).name
    if not INDEX.exists():
        return None
    index_content = INDEX.read_text()
    if filename in index_content:
        return None  # Already indexed
    return f"New memory file `{filename}` is NOT in MEMORY.md index. Add it."


if __name__ == "__main__":
    _raw = sys.stdin.read()
    try:
        _prompt = json.loads(_raw).get("prompt", "") if _raw else ""
    except Exception:
        _prompt = ""
    from _semantic_router import should_fire
    if not should_fire(__file__, _prompt):
        print("{}")
        sys.exit(0)
    sys.stdin = io.StringIO(_raw)
    run_hook(check, action, "auto_memory_index")
