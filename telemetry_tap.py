#!/usr/bin/env python3
"""Telemetry tap: registered on UserPromptSubmit, SessionStart, PreToolUse,
PostToolUse, Stop. Reads stdin event, appends 1 row to prompt_events.jsonl.

Design:
- Additive only: outputs {} (no context injection)
- Target <5ms, hard cap 20ms
- Privacy: prompt_snippet capped at 80 chars, never full prompt
- Silent on failure (stderr only)
"""

import json
import os
import sys
import time

PROMPT_EVENTS_PATH = os.path.expanduser("~/NardoWorld/meta/prompt_events.jsonl")
SESSION_ID = os.environ.get("CLAUDE_SESSION_ID", f"pid_{os.getpid()}")
HOOK_EVENT = os.environ.get("CLAUDE_HOOK_EVENT", "unknown")


def _append_line(path: str, line: str) -> None:
    """Atomic append via O_APPEND. Creates dir if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def main():
    t0 = time.monotonic()

    # Read stdin (required by hook protocol)
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    try:
        row = {
            "ts": int(time.time()),
            "session_id": SESSION_ID,
            "event": HOOK_EVENT,
        }

        # Extract prompt snippet for UserPromptSubmit events
        if HOOK_EVENT == "UserPromptSubmit":
            prompt = payload.get("prompt", "")
            row["prompt_snippet"] = prompt[:80]

        # Extract tool name for Pre/PostToolUse events
        if HOOK_EVENT in ("PreToolUse", "PostToolUse"):
            tool_name = payload.get("tool_name", payload.get("tool", ""))
            if not tool_name and isinstance(payload, dict):
                # Some versions nest under tool_use
                tool_name = payload.get("tool_use", {}).get("name", "")
            row["tool_name"] = tool_name

        duration_ms = int((time.monotonic() - t0) * 1000)
        row["tap_overhead_ms"] = duration_ms

        line = json.dumps(row, separators=(",", ":")) + "\n"
        _append_line(PROMPT_EVENTS_PATH, line)

    except Exception as e:
        print(f"[telemetry_tap] error: {e}", file=sys.stderr)

    # Always output empty dict — additive only
    print(json.dumps({}))


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parent))
    from _safe_hook import safe_run
    safe_run(main, "telemetry_tap")
