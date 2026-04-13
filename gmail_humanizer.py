#!/usr/bin/env python3
"""PostToolUse hook: remind to run content-humanizer after creating content."""
import json
import sys


DOCX_TRIGGERS = (".docx",)

TOOL_TRIGGERS = {
    "mcp__claude_ai_Gmail__gmail_create_draft": "Gmail draft",
    "mcp__plugin_telegram_telegram__reply": "Telegram reply",
    "mcp__plugin_telegram_telegram__edit_message": "Telegram message",
}


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Check MCP tool triggers
    if tool_name in TOOL_TRIGGERS:
        label = TOOL_TRIGGERS[tool_name]
        print(json.dumps({
            "additionalContext": (
                f"📝 {label} created. Auto-humanize before sending: "
                "remove AI patterns (delve, crucial, leverage, robust, insofar as, furthermore). "
                "Short punchy sentences. Real voice. No em-dash overuse."
            )
        }))
        return

    # Check Write tool for .docx files
    if tool_name == "Write":
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        if any(file_path.endswith(ext) for ext in DOCX_TRIGGERS):
            print(json.dumps({
                "additionalContext": (
                    "📝 Docx written. Auto-humanize content: "
                    "remove AI patterns, vary sentence rhythm, keep technical precision. "
                    "Run /content-humanizer if not already done."
                )
            }))
            return

    print("{}")


if __name__ == "__main__":
    main()
