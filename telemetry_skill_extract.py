#!/usr/bin/env python3
# @bigd-hook-meta
# name: telemetry_skill_extract
# fires_on: PostToolUse
# always_fire: true
# cost_score: 1
"""PostToolUse hook: detect skill invocations and append to skill_invocations.jsonl.

A "skill invocation" is detected when:
1. tool_name contains "skill" (case-insensitive), OR
2. The tool input contains a known skill trigger pattern (/s, /combo, /r1a, etc.)

Schema appended:
{
  "ts": 1776885000,
  "session_id": "abc...",
  "skill": "s",
  "trigger_source": "explicit_slash|keyword_match|tool_use|auto_route",
  "trigger_text_snippet": "/s ...",
  "tokens_in": null,
  "tokens_out": null,
  "success": true,
  "duration_ms": null
}

Silent on failure.
"""

import json
import os
import re
import sys
import time

SKILL_INVOCATIONS_PATH = os.path.expanduser("~/NardoWorld/meta/skill_invocations.jsonl")
SESSION_ID = os.environ.get("CLAUDE_SESSION_ID", f"pid_{os.getpid()}")

# Known always-on skills from CLAUDE.md
KNOWN_SKILLS = ["s", "combo", "r1a", "recall"]

# Slash-command pattern: /skillname at start of prompt or after whitespace
SLASH_RE = re.compile(r"(?:^|[\s])\/([a-zA-Z0-9_-]+)", re.MULTILINE)

# Explicit skill keywords that map to skills
KEYWORD_MAP = {
    "/s": "s",
    "/combo": "combo",
    "/r1a": "r1a",
    "/recall": "recall",
}


def _append_line(path: str, line: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _detect_skill(payload: dict):
    """Return (skill_name, trigger_source, snippet) or (None, None, None)."""
    tool_name = payload.get("tool_name", payload.get("tool", ""))

    # Check if the tool itself is a skill invocation
    if tool_name and "skill" in tool_name.lower():
        # Extract skill name from tool params
        tool_input = payload.get("tool_input", payload.get("input", {}))
        skill = tool_input.get("skill_name", tool_input.get("name", tool_name))
        return str(skill), "tool_use", str(tool_input)[:80]

    # Check tool input text for slash commands
    tool_input = payload.get("tool_input", payload.get("input", {}))
    input_text = ""
    if isinstance(tool_input, dict):
        input_text = tool_input.get("command", tool_input.get("prompt", tool_input.get("text", "")))
    elif isinstance(tool_input, str):
        input_text = tool_input

    if input_text:
        # Check explicit slash patterns
        for slash, skill in KEYWORD_MAP.items():
            if re.search(r"(?:^|[\s])" + re.escape(slash) + r"(?:[\s]|$)", input_text, re.IGNORECASE):
                return skill, "explicit_slash", input_text[:80]

        # Generic slash match for known skills
        for match in SLASH_RE.finditer(input_text):
            candidate = match.group(1).lower()
            if candidate in KNOWN_SKILLS:
                return candidate, "keyword_match", input_text[:80]

    return None, None, None


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    try:
        skill, trigger_source, snippet = _detect_skill(payload)
        if skill is None:
            # Not a skill invocation — exit fast
            print(json.dumps({}))
            return

        # Check for success from tool output
        tool_response = payload.get("tool_response", payload.get("output", {}))
        if isinstance(tool_response, dict):
            success = not tool_response.get("error") and not tool_response.get("is_error")
        elif isinstance(tool_response, str):
            success = True
        else:
            success = True

        row = {
            "ts": int(time.time()),
            "session_id": SESSION_ID,
            "skill": skill,
            "trigger_source": trigger_source,
            "trigger_text_snippet": snippet or "",
            "tokens_in": None,
            "tokens_out": None,
            "success": success,
            "duration_ms": None,
        }
        line = json.dumps(row, separators=(",", ":")) + "\n"
        _append_line(SKILL_INVOCATIONS_PATH, line)

    except Exception as e:
        print(f"[telemetry_skill_extract] error: {e}", file=sys.stderr)

    print(json.dumps({}))


if __name__ == "__main__":
    main()
