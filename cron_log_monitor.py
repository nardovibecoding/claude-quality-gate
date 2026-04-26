#!/usr/bin/env python3
# @bigd-hook-meta
# name: cron_log_monitor
# fires_on: SessionStart
# relevant_intents: [vps, pm]
# irrelevant_intents: [bigd, telegram, docx, x_tweet, git, code, memory, debug]
# cost_score: 2
# always_fire: false
"""SessionStart hook: check VPS cron job logs for recent errors."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vps_config import VPS_SSH


def ssh_cmd(cmd, timeout=10):
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", VPS_SSH, cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


def main():
    # Grep recent errors from all cron job logs
    ok, out = ssh_cmd(
        "grep -l 'ERROR\\|CRITICAL\\|Traceback\\|FAILED' /tmp/*.log 2>/dev/null | head -10"
    )

    if not ok or not out:
        print("{}")
        return

    error_files = out.strip().splitlines()

    # Get last error line from each file
    details = []
    for log_file in error_files[:5]:
        ok2, last_err = ssh_cmd(
            f"grep -E 'ERROR|CRITICAL|Traceback|FAILED' {log_file} | tail -1"
        )
        if ok2 and last_err:
            name = log_file.split("/")[-1]
            details.append(f"  - `{name}`: {last_err[:120]}")

    if details:
        msg = f"**VPS log errors found in {len(error_files)} file(s):**\n"
        msg += "\n".join(details)
        print(json.dumps({"systemMessage": msg}))
    else:
        print("{}")


if __name__ == "__main__":
    import io
    import os
    _raw = sys.stdin.read()
    try:
        _prompt = json.loads(_raw).get("prompt", "") if _raw else ""
    except Exception:
        _prompt = ""
    sys.path.insert(0, os.path.dirname(__file__))
    from _semantic_router import should_fire
    if not should_fire(__file__, _prompt):
        print("{}")
        sys.exit(0)
    sys.stdin = io.StringIO(_raw)
    main()
