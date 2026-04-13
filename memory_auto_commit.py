#!/usr/bin/env python3
# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Stop hook: rsync memory to VPS at session end."""
import json
import os
import subprocess
import sys
from pathlib import Path

# Skip during convos (auto-clear flow)
_tty = os.environ.get("CLAUDE_TTY_ID", "").strip()
if Path(f"/tmp/claude_ctx_exit_pending_{_tty}").exists() if _tty else Path("/tmp/claude_ctx_exit_pending").exists():
    print("{}")
    sys.exit(0)

MEMORY_SRC = Path.home() / ".claude" / "projects" / f"-Users-{Path.home().name}" / "memory"
VPS_TARGET = "bernard@157.180.28.14:~/claude-memory/"


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kwargs)


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    if not MEMORY_SRC.exists():
        print("{}")
        return

    # Skip if no memory files changed since last sync
    STAMP = Path("/tmp/memory_last_rsync.ts")
    last_sync = STAMP.stat().st_mtime if STAMP.exists() else 0
    newest = max((f.stat().st_mtime for f in MEMORY_SRC.rglob("*") if f.is_file()), default=0)
    if newest <= last_sync:
        print("{}")
        return

    result = run(["rsync", "-az", "--delete",
                  str(MEMORY_SRC) + "/",
                  VPS_TARGET])

    if result.returncode == 0:
        STAMP.touch()
        print(json.dumps({"systemMessage": "Memory rsynced to VPS."}))
    else:
        print("{}")


if __name__ == "__main__":
    main()
