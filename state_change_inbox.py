#!/usr/bin/env python3
# @bigd-hook-meta
# name: state_change_inbox
# fires_on: PostToolUse
# always_fire: true
# cost_score: 1
"""PostToolUse hook: append state-impacting edits to persistent JSONL inbox.

Mirrors STATE_FILE_PATTERNS from state_change_detector.py exactly.
Dedupes on (file_path, minute-bucket) to prevent duplicate rows.
Silent: no stdout, never blocks tool call.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

INBOX = Path("/Users/bernard/NardoWorld/meta/state_change_inbox.jsonl")

# Mirror state_change_detector.py patterns EXACTLY
STATE_FILE_PATTERNS = [
    re.compile(r"\.env(\.|$)"),
    re.compile(r"(^|/)[^/]*config[^/]*\.(py|js|ts|json|yaml|yml|toml|ini)$", re.IGNORECASE),
    re.compile(r"(^|/)[^/]*settings[^/]*\.(py|js|ts|json|yaml|yml|toml|ini)$", re.IGNORECASE),
    re.compile(r"crontab"),
    re.compile(r"\.service$"),
    re.compile(r"\.timer$"),
    re.compile(r"/strategies?/[^/]+\.py$", re.IGNORECASE),
    re.compile(r"/strats?/[^/]+\.py$", re.IGNORECASE),
    re.compile(r"/hooks/[^/]+\.(py|sh)$", re.IGNORECASE),
]

EXCLUDE_PATTERNS = [
    re.compile(r"\.md$"),
    re.compile(r"/lessons/"),
    re.compile(r"/memory/convo_"),
    re.compile(r"/NardoWorld/"),
]


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name", "")
    if tool not in ("Edit", "Write", "NotebookEdit"):
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not file_path:
        return 0

    if any(p.search(file_path) for p in EXCLUDE_PATTERNS):
        return 0
    if not any(p.search(file_path) for p in STATE_FILE_PATTERNS):
        return 0

    now = time.time()
    # Minute bucket for dedup
    minute_bucket = int(now // 60)
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")

    # Load existing rows for dedup check
    existing_rows = []
    if INBOX.exists():
        try:
            for line in INBOX.read_text().splitlines():
                line = line.strip()
                if line:
                    try:
                        existing_rows.append(json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass

    # Dedup: same file_path within same minute
    for row in existing_rows:
        if row.get("file_path") == file_path:
            existing_ts = row.get("ts", 0)
            if int(existing_ts // 60) == minute_bucket:
                return 0

    new_row = {
        "ts": now,
        "file_path": file_path,
        "tool": tool,
        "session_id": session_id,
    }

    try:
        INBOX.parent.mkdir(parents=True, exist_ok=True)
        with INBOX.open("a") as fh:
            fh.write(json.dumps(new_row) + "\n")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
