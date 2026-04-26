#!/usr/bin/env python3
"""
bot-liveness-guard.py — Block mtime-based bot-liveness inference.

Modes (dispatch via sys.argv[1]):
  pretool     — PreToolUse(Bash): block mtime-inference reads of bot data files
                unless 3-step systemd protocol was run within last 30min.
  posttool    — PostToolUse(Bash): mark protocol satisfied when systemctl/journalctl
                ran against a registered bot unit.
  userprompt  — UserPromptSubmit: emit reminder when prompt mentions liveness keyword
                AND a bot name.

Source / lesson: ~/NardoWorld/lessons/lesson_bot_liveness_misdiagnosis_20260426.md
Rule: ~/.claude/rules/pm-bot.md §Liveness verdict protocol
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- Bot registry ---------------------------------------------------------
BOTS = {
    'kalshi-bot': {'host': 'hel',    'host_alias': 'hel'},
    'pm-bot':     {'host': 'london', 'host_alias': 'london'},
}

LIVENESS_KEYWORDS = re.compile(
    r'\b(wedged|stuck|dead|alive|silent|frozen|hung|down|offline|crashed|broken|stale|not running|not firing|last scan|0 emits|wedge)\b',
    re.IGNORECASE,
)
BOT_NAME_PATTERN = re.compile(
    r'\b(kalshi[-_]?bot|pm[-_]?bot|polymarket|kalshi|hel\b|london\b|prediction[-_]?market)\b',
    re.IGNORECASE,
)

BOT_DATA_FILE_RE = re.compile(
    r'(signal-trace|trade-journal|signal_history|eval-history|portfolio\.json|kalshi_cancels|clob_cancels|mm-roundtrips|virtual-fills|brier_tracking|kmm-orders|signal_status|scanner\.log)',
    re.IGNORECASE,
)
MTIME_VERB_RE = re.compile(
    r'(\bls\s+-[a-zA-Z]*l|\bls\b|\bstat\s|\bfind\b.*-mmin|\bfind\b.*-mtime|\bhead\s+-1\b|\btail\s+-1\b|\bwc\s+-l\b)',
)

CACHE_DIR = Path.home() / '.cache' / 'claude-bot-liveness'
PROTOCOL_TTL = timedelta(minutes=30)

# Match systemctl is-active <unit> OR journalctl -u <unit> --since
SYSTEMCTL_RE = re.compile(r'systemctl\s+(?:is-active|status|show)\s+([\w.\-]+)')
JOURNALCTL_RE = re.compile(r'journalctl\s+(?:[^|;&]*\s)?-u\s+([\w.\-]+)\s+(?:[^|;&]*\s)?--since')


def _safe_load_input() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _unit_basename(unit: str) -> str:
    if unit.endswith('.service'):
        unit = unit[: -len('.service')]
    return unit


def _protocol_satisfied(unit_basename: str) -> bool:
    marker = CACHE_DIR / f'{unit_basename}-checked-at.iso'
    if not marker.exists():
        return False
    try:
        ts = marker.read_text().strip()
        # tolerate trailing newline; accept either Z suffix or +00:00
        ts_norm = ts.replace('Z', '+00:00')
        dt = datetime.fromisoformat(ts_norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt) < PROTOCOL_TTL
    except Exception:
        return False


def _mark_protocol(unit_basename: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        marker = CACHE_DIR / f'{unit_basename}-checked-at.iso'
        marker.write_text(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    except Exception as e:
        print(f'bot-liveness-guard: marker write failed: {e}', file=sys.stderr)


# ---- Mode handlers --------------------------------------------------------

def handle_pretool(payload: dict) -> int:
    cmd = (payload.get('tool_input') or {}).get('command') or ''
    if not cmd:
        return 0
    # Only intercept commands that mention a bot data file AND an mtime-inference verb.
    if not BOT_DATA_FILE_RE.search(cmd):
        return 0
    if not MTIME_VERB_RE.search(cmd):
        return 0
    # If protocol satisfied for either bot in last 30min, allow.
    for unit in BOTS.keys():
        if _protocol_satisfied(unit):
            return 0
    msg = (
        '\n'
        '⛔ bot-liveness-guard BLOCK\n'
        'You are about to read bot data file mtime/contents to infer liveness.\n'
        'Mtime can lie (file rotation, async writes). Run the 3-step protocol FIRST:\n'
        '  ssh <host_alias> \'systemctl is-active <unit>\'\n'
        '  ssh <host_alias> \'journalctl -u <unit> --since "5 min ago" --no-pager | tail -20\'\n'
        '  ssh <host_alias> \'systemctl show <unit> -p MainPID -p ActiveEnterTimestamp\'\n'
        'Bot registry: kalshi-bot @ hel | pm-bot @ london\n'
        'The companion populator hook will mark the protocol satisfied.\n'
        'Lesson: ~/NardoWorld/lessons/lesson_bot_liveness_misdiagnosis_20260426.md\n'
    )
    print(msg, file=sys.stderr)
    return 2


def handle_posttool(payload: dict) -> int:
    cmd = (payload.get('tool_input') or {}).get('command') or ''
    if not cmd:
        return 0
    units_seen = set()
    for m in SYSTEMCTL_RE.finditer(cmd):
        units_seen.add(_unit_basename(m.group(1)))
    for m in JOURNALCTL_RE.finditer(cmd):
        units_seen.add(_unit_basename(m.group(1)))
    for unit in units_seen:
        if unit in BOTS:
            _mark_protocol(unit)
    return 0


def handle_userprompt(payload: dict) -> int:
    prompt = payload.get('prompt') or ''
    if not prompt:
        return 0
    if not (LIVENESS_KEYWORDS.search(prompt) and BOT_NAME_PATTERN.search(prompt)):
        return 0
    reminder = (
        '[bot-liveness-guard reminder] Liveness verdict protocol — DO NOT infer from file mtime alone:\n'
        '  1. ssh <host> \'systemctl is-active <unit>\'\n'
        '  2. ssh <host> \'journalctl -u <unit> --since "5 min ago" --no-pager | tail -20\'\n'
        '  3. ssh <host> \'systemctl show <unit> -p MainPID -p ActiveEnterTimestamp\'\n'
        'Bot registry: kalshi-bot @ hel | pm-bot @ london\n'
        'Lesson: ~/NardoWorld/lessons/lesson_bot_liveness_misdiagnosis_20260426.md'
    )
    print(reminder)
    return 0


def main() -> int:
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ''
        payload = _safe_load_input()
        if mode == 'pretool':
            return handle_pretool(payload)
        if mode == 'posttool':
            return handle_posttool(payload)
        if mode == 'userprompt':
            return handle_userprompt(payload)
        # Unknown mode: silent no-op.
        return 0
    except Exception as e:
        # Never break tool-use because of this hook.
        try:
            print(f'bot-liveness-guard: uncaught error: {e}', file=sys.stderr)
        except Exception:
            pass
        return 0


if __name__ == '__main__':
    sys.exit(main())
