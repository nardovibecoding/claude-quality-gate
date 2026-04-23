#!/usr/bin/env python3
"""
inbox_ack_consumer.py — Big SystemD Phase 8-3c

Reads ~/inbox/_approvals/*.json, validates each, logs to ~/.claude/logs/inbox_ack.log.
Then calls approval_executor.py to execute approved actions (P8-3c wire).

Usage:
  python3 ~/.claude/hooks/inbox_ack_consumer.py [--dry-run]
  python3 ~/.claude/hooks/inbox_ack_consumer.py --rollback <exec_id>
"""

import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

APPROVALS_DIR = os.path.expanduser("~/inbox/_approvals")
LOG_PATH = os.path.expanduser("~/.claude/logs/inbox_ack.log")
REQUIRED_FIELDS = ["brief_id", "code", "timestamp", "user_prompt_snippet"]
EXECUTOR_PATH = os.path.join(os.path.dirname(__file__), "approval_executor.py")

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
    # Pass --rollback through to executor
    if "--rollback" in sys.argv:
        idx = sys.argv.index("--rollback")
        if idx + 1 < len(sys.argv):
            exec_id = sys.argv[idx + 1]
            cmd = [sys.executable, EXECUTOR_PATH, "--rollback", exec_id]
            result = subprocess.run(cmd, capture_output=False)
            sys.exit(result.returncode)
        else:
            print("Usage: --rollback <exec_id>", file=sys.stderr)
            sys.exit(1)

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

    # P8-3c: call approval_executor for all validated approvals
    if ok > 0:
        _log("inbox_ack_consumer: handing off to approval_executor")
        cmd = [sys.executable, EXECUTOR_PATH]
        if dry_run:
            cmd.append("--dry-run")
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            _log(f"inbox_ack_consumer: approval_executor exited {result.returncode}")


if __name__ == "__main__":
    main()
