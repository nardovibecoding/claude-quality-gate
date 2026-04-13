#!/usr/bin/env python3
# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""Stop hook: append session edit summary to session_learnings.md.

Reads the edit log (written by auto_test_after_edit.py) and appends a dated
entry to ~/.claude/skills/session_learnings.md. Only fires if 3+ non-memory
files were edited. Silent — never blocks or interrupts.

Inspired by oh-my-claudecode learner pattern.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Skip during convos (auto-clear flow)
_tty = os.environ.get("CLAUDE_TTY_ID", "").strip()
if Path(f"/tmp/claude_ctx_exit_pending_{_tty}").exists() if _tty else Path("/tmp/claude_ctx_exit_pending").exists():
    print("{}")
    sys.exit(0)

_EDIT_LOG_DIR = Path("/tmp")
_LEARNINGS_FILE = Path.home() / ".claude" / "skills" / "session_learnings.md"
_SKIP = ["memory/", "MEMORY.md", "task_plan.md", "session_learnings.md",
         ".claude/plans/", "/tmp/"]


def _edit_log_path(session_id):
    if session_id:
        safe = session_id.replace("/", "_").replace("\\", "_")
        return _EDIT_LOG_DIR / f"claude_edits_{safe}.json"
    return _EDIT_LOG_DIR / "claude_edits_this_turn.json"


def _skip(file_path):
    return any(p in file_path for p in _SKIP)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    path = _edit_log_path(data.get("session_id"))
    try:
        if not path.exists():
            sys.exit(0)
        all_edits = json.loads(path.read_text())
    except Exception:
        sys.exit(0)

    # Deduplicate, drop memory/plan files
    seen: dict = {}
    for e in all_edits:
        f = e.get("file", "")
        if _skip(f):
            continue
        if f not in seen or e.get("ts", 0) > seen[f].get("ts", 0):
            seen[f] = e

    edits = list(seen.values())
    if len(edits) < 3:
        sys.exit(0)

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"\n## {today}"]
    for e in edits[:10]:
        fname = Path(e["file"]).name
        funcs = e.get("functions", [])
        if funcs:
            lines.append(f"- `{fname}`: {', '.join(funcs[:4])}")
        else:
            lines.append(f"- `{fname}`")

    _LEARNINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_LEARNINGS_FILE, "a") as f:
        f.write("\n".join(lines) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
