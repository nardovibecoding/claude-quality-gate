#!/usr/bin/env python3
# @bigd-hook-meta
# name: auto_vps_sync
# fires_on: PostToolUse
# relevant_intents: [vps, git, sync]
# irrelevant_intents: [bigd, pm, telegram, docx, x_tweet, memory, debug]
# cost_score: 3
# always_fire: false
"""PostToolUse hook: auto-sync VPS after git push."""
import io
import json
import re
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from hook_base import run_hook, ssh_cmd
from vps_config import VPS_REPO


def check(tool_name, tool_input, input_data):
    if tool_name != "Bash":
        return False
    cmd = tool_input.get("command", "")
    return bool(re.search(r"git\s+push", cmd))


def action(tool_name, tool_input, input_data):
    ok, out = ssh_cmd(f"cd {VPS_REPO} && git fetch origin && git reset --hard origin/main")
    msg = f"VPS auto-synced after git push." if ok else f"VPS sync FAILED: {out}"

    import subprocess
    from pathlib import Path
    scripts = Path.home() / "telegram-claude-bot" / "scripts"

    # Auto-sync public extracted repos (sec-ops-guard, quality-gate, etc.)
    sync_script = scripts / "sync_public_repos.py"
    if sync_script.exists():
        r = subprocess.run(
            ["python3", str(sync_script), "--sync"],
            capture_output=True, text=True, timeout=60)
        synced = r.stdout.count("COPIED")
        if synced:
            msg += f" Public repos: {synced} files synced."

    # Auto-sync template (sanitized full bot copy)
    template_script = scripts / "sync_template.py"
    if template_script.exists():
        r = subprocess.run(
            ["python3", str(template_script), "--sync"],
            capture_output=True, text=True, timeout=60)
        if "pushed" in r.stdout:
            msg += " Template synced."

    return msg


if __name__ == "__main__":
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
    run_hook(check, action, "auto_vps_sync")
