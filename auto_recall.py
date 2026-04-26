#!/usr/bin/env python3
# @bigd-hook-meta
# name: auto_recall
# fires_on: PreToolUse
# relevant_intents: [memory, meta]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, git, code, vps, sync, debug]
# cost_score: 2
# always_fire: false
"""PreToolUse hook: auto-enrich Grep/Glob on memory/ with BM25 search results."""
import io
import json
import os
import sys

def main():
    event = json.load(sys.stdin)
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    # Only trigger on Grep/Glob targeting memory
    if tool not in ("Grep", "Glob"):
        return

    path = tool_input.get("path", "")
    pattern = tool_input.get("pattern", "")

    if "memory" not in path and "memory" not in pattern:
        return

    # Extract search query from grep pattern or glob pattern
    query = tool_input.get("pattern", "")
    if not query:
        return

    # Clean regex artifacts for BM25 query
    import re
    query = re.sub(r'[\\.*+?^${}()|[\]]', ' ', query).strip()
    if len(query) < 3:
        return

    # Run BM25 search
    script = os.path.expanduser("~/.claude/scripts/memory_search.py")
    if not os.path.exists(script):
        return

    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, script, query, "--limit", "5", "--json"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return

        hits = json.loads(result.stdout)
        if not hits:
            return

        # Format compact results
        lines = ["RECALL (auto-BM25):"]
        for h in hits:
            lines.append(f"  [{h['score']:.2f}] {h['path']} — {h.get('description', '')[:60]}")

        print(json.dumps({
            "additionalContext": "\n".join(lines)
        }))
    except Exception:
        return

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
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
    main()
