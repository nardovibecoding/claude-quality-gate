#!/usr/bin/env python3
# @bigd-hook-meta
# name: pre_edit_impact
# fires_on: PreToolUse
# relevant_intents: [code, meta, debug]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, vps, sync, memory]
# cost_score: 2
# always_fire: false
# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""PreToolUse hook: blast-radius analysis before editing source files.

Counts how many files import/require the target file and tiers the risk.
Inspired by GitNexus impact analysis.

Tiers:
  0:      silent
  1-3:    LOW  — brief mention
  4-9:    HIGH — warn, check callers first
  10+:    CRITICAL — list top callers, high blast radius
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hook_base import run_hook

_TARGET_SUFFIXES = {".py", ".js", ".ts", ".tsx"}
_SEARCH_DIRS = [
    str(Path.home() / "telegram-claude-bot"),
    str(Path.home() / "face-analysis-app"),
    str(Path.home() / "eval-loop"),
    str(Path.home() / ".claude" / "hooks"),
]


def _count_importers(file_path: str) -> tuple[int, list[str]]:
    """Count files that import/require the given file."""
    stem = Path(file_path).stem

    # Build search pattern: matches import/from/require with the module name
    pattern = f"(import|from|require).*{stem}"

    refs = []
    for d in _SEARCH_DIRS:
        if not Path(d).exists():
            continue
        try:
            result = subprocess.run(
                ["grep", "-rlE",
                 "--include=*.py", "--include=*.js",
                 "--include=*.ts", "--include=*.tsx",
                 pattern, d],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().splitlines():
                if line and line != file_path and "/__pycache__/" not in line:
                    refs.append(line)
        except (subprocess.TimeoutExpired, Exception):
            continue

    return len(refs), list(dict.fromkeys(refs))  # deduplicated


def check(tool_name, tool_input, _input_data):
    if tool_name not in ("Edit", "Write"):
        return False
    fp = tool_input.get("file_path", "")
    return Path(fp).suffix in _TARGET_SUFFIXES


def action(_tool_name, tool_input, _input_data):
    fp = tool_input.get("file_path", "")
    if not fp:
        return None

    count, refs = _count_importers(fp)
    fname = Path(fp).name

    if count == 0:
        return None

    if count <= 3:
        names = ", ".join(Path(r).name for r in refs[:3])
        return f"IMPACT LOW: `{fname}` imported by {count} file(s): {names}"

    if count <= 9:
        names = ", ".join(Path(r).name for r in refs[:5])
        return (
            f"IMPACT HIGH: `{fname}` imported by {count} files "
            f"({names}). Check callers before editing."
        )

    top = "\n".join(f"  - {Path(r).name}" for r in refs[:5])
    return (
        f"IMPACT CRITICAL: `{fname}` has {count} dependents — high blast radius.\n"
        f"Top callers:\n{top}\n"
        f"Verify callers still work after this change."
    )


if __name__ == "__main__":
    import io
    import json
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
    run_hook(check, action, "pre_edit_impact")
