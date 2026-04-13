#!/usr/bin/env python3
"""Block git commands that would embed PATs in remote URLs."""
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

tool = data.get("tool_name", "")
inp = data.get("tool_input", {})

if tool != "Bash":
    sys.exit(0)

cmd = inp.get("command", "")

# Hard block: prediction-markets + on-chain-bots are private — never push/expose to any remote
if re.search(r"git\s+(push|remote\s+set-url|remote\s+add|clone)", cmd):
    if "prediction-markets" in cmd or "prediction_markets" in cmd or "on-chain-bots" in cmd or "on_chain_bots" in cmd:
        print(json.dumps({
            "decision": "block",
            "reason": "prediction-markets / on-chain-bots are private. Never push to GitHub or any remote."
        }))
        sys.exit(0)

# Also block gh repo create/delete for private repos
if re.search(r"gh\s+repo\s+(create|delete)", cmd) and ("prediction" in cmd or "on-chain" in cmd):
    print(json.dumps({
        "decision": "block",
        "reason": "prediction-markets / on-chain-bots are private. No GitHub repo allowed."
    }))
    sys.exit(0)

# Only care about git remote set-url and git push with explicit URLs
if not re.search(r"git\s+(remote\s+set-url|push|clone)", cmd):
    sys.exit(0)

# Detect embedded credentials: https://user:TOKEN@host
pat_pattern = re.compile(r"https?://[^@\s]+:[^@\s]+@(github\.com|gitlab\.com|bitbucket\.org)", re.IGNORECASE)
match = pat_pattern.search(cmd)

if match:
    print(json.dumps({
        "decision": "block",
        "reason": (
            "PAT detected in git URL. Use a clean URL instead:\n"
            "  https://github.com/owner/repo.git\n"
            "Git will prompt for credentials separately, or use gh auth login."
        )
    }))
    sys.exit(0)

sys.exit(0)
