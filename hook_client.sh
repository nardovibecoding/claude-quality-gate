#!/bin/bash
# Fast hook client — sends event to daemon via unix socket.
# Usage: echo '{"tool_name":"Bash",...}' | hook_client.sh pre|post
# Falls back to dispatcher if daemon not running.

SOCK="/tmp/claude_hook_daemon.sock"
EVENT_TYPE="${1:-pre}"
HOOKS_DIR="${HOOKS_DIR:-$(dirname "$0")}"

input=$(cat)
[ -z "$input" ] && echo '{}' && exit 0

# Try daemon (inject _event key — no python3 needed)
if [ -S "$SOCK" ]; then
    payload="{\"_event\":\"${EVENT_TYPE}\",\"_data\":${input}}"
    result=$(printf '%s' "$payload" | nc -U "$SOCK" -w 2 2>/dev/null)
    if [ -n "$result" ]; then
        echo "$result"
        exit 0
    fi
fi

# Fallback to dispatcher
if [ "$EVENT_TYPE" = "pre" ]; then
    echo "$input" | python3 "${HOOKS_DIR}/dispatcher_pre.py"
else
    echo "$input" | python3 "${HOOKS_DIR}/dispatcher_post.py"
fi
