#!/usr/bin/env python3
"""
inbox_ack_consumer.py — Big SystemD Phase 6.4b

Reads ~/inbox/_approvals/*.json, validates each, logs to ~/.claude/logs/inbox_ack.log.
Run manually for now; future: cron pickup.

NO auto-actions fired in this phase. Consumer only validates + logs.

Usage:
  python3 ~/.claude/hooks/inbox_ack_consumer.py [--dry-run]
"""

import glob
import json
import os
import sys
from datetime import datetime, timezone

APPROVALS_DIR = os.path.expanduser("~/inbox/_approvals")
LOG_PATH = os.path.expanduser("~/.claude/logs/inbox_ack.log")
REQUIRED_FIELDS = ["brief_id", "code", "timestamp", "user_prompt_snippet"]

dry_run = "--dry-run" in sys.argv


def _log(msg):
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    if not dry_run:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")


def main():
    pattern = os.path.join(APPROVALS_DIR, "*.json")
    approval_files = sorted(glob.glob(pattern))

    if not approval_files:
        _log("inbox_ack_consumer: no approval files found")
        return

    ok = 0
    errors = 0

    for path in approval_files:
        filename = os.path.basename(path)
        # Skip lock file
        if filename.startswith("."):
            continue
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _log(f"PARSE_ERROR {filename}: {e}")
            errors += 1
            continue

        missing = [field for field in REQUIRED_FIELDS if field not in data]
        if missing:
            _log(f"SCHEMA_ERROR {filename}: missing fields {missing}")
            errors += 1
            continue

        _log(
            f"VALID brief_id={data['brief_id']} "
            f"code={data['code']} "
            f"ts={data['timestamp']} "
            f"prompt_snippet={data['user_prompt_snippet'][:60]!r}"
        )
        ok += 1

    _log(f"inbox_ack_consumer: done. valid={ok} errors={errors} total={ok+errors}")


if __name__ == "__main__":
    main()
