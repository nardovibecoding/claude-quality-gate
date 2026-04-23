#!/usr/bin/env python3
"""Shared telemetry lib for hook self-fire logging.

Usage in any hook:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from telemetry import log_fire, log_fire_done

    t0 = log_fire(__file__)
    try:
        ... hook logic ...
    except Exception as e:
        log_fire_done(__file__, t0, errored=True)
        raise
    log_fire_done(__file__, t0, errored=False)

All writes are append-only + atomic (os.write on O_WRONLY|O_APPEND).
Failure is always silent (writes to stderr, never raises).
"""

import json
import os
import sys
import time

HOOK_FIRES_PATH = os.path.expanduser("~/NardoWorld/meta/hook_fires.jsonl")

# Session id from env or pid fallback
_SESSION_ID = os.environ.get("CLAUDE_SESSION_ID", f"pid_{os.getpid()}")


def _get_event_type():
    """Best-effort: detect hook event type from argv or env."""
    # Claude Code passes event type in env for some hooks
    return os.environ.get("CLAUDE_HOOK_EVENT", "unknown")


def log_fire(hook_path: str) -> float:
    """Call at hook entry. Returns t0 (float seconds) for duration calc."""
    return time.monotonic()


def log_fire_done(hook_path: str, t0: float, errored: bool = False,
                  output_size_bytes: int = 0) -> None:
    """Call at hook exit. Appends one row to hook_fires.jsonl. Silent on failure."""
    try:
        duration_ms = int((time.monotonic() - t0) * 1000)
        hook_name = os.path.basename(hook_path)
        event = _get_event_type()
        row = {
            "ts": int(time.time()),
            "session_id": _SESSION_ID,
            "hook": hook_name,
            "event": event,
            "matcher": "",
            "duration_ms": duration_ms,
            "output_size_bytes": output_size_bytes,
            "errored": errored,
        }
        line = json.dumps(row, separators=(",", ":")) + "\n"
        _append_line(HOOK_FIRES_PATH, line)
    except Exception as e:
        print(f"[telemetry] log_fire_done error: {e}", file=sys.stderr)


def _append_line(path: str, line: str) -> None:
    """Atomic append. Creates dirs if needed."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as e:
        print(f"[telemetry] _append_line error on {path}: {e}", file=sys.stderr)
