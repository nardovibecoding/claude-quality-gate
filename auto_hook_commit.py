#!/usr/bin/env python3
# Copyright (c) 2026 Nardo (nardovibecoding). AGPL-3.0 — see LICENSE
"""PostToolUse hook: sync ~/.claude/ edits to telegram-claude-bot/ and commit.

Watches three source dirs:
  ~/.claude/hooks/*.py           → telegram-claude-bot/hooks/
  ~/.claude/claude-mcp-proxy/**  → telegram-claude-bot/claude-mcp-proxy/
  ~/.claude/claude-skill-loader/**→ telegram-claude-bot/claude-skill-loader/

Direction: Mac live → repo → git commit (reverse of auto_hook_deploy.py)
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

HOOKS_SRC = Path.home() / ".claude" / "hooks"
MCP_PROXY_SRC = Path.home() / ".claude" / "claude-mcp-proxy"
SKILL_LOADER_SRC = Path.home() / ".claude" / "claude-skill-loader"
BOT_REPO = Path.home() / "telegram-claude-bot"
HOOKS_DST = BOT_REPO / "hooks"
MCP_PROXY_DST = BOT_REPO / "claude-mcp-proxy"
SKILL_LOADER_DST = BOT_REPO / "claude-skill-loader"

# Mac-only hooks — do NOT commit to repo
MAC_ONLY_HOOKS = {
    "auto_pre_publish.py",
    "auto_skill_sync.py",
    "cookie_health.py",
    "auto_context_checkpoint.py",
    "temp_file_guard.py",
}

# Private files in mcp-proxy/skill-loader — do NOT commit to repo
MCP_PRIVATE = {"servers.json"}


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, **kwargs)


def _classify(file_path: str):
    """Return (src_root, dst_root, rel_path) or None if not watched."""
    p = Path(file_path)
    for src, dst in [
        (HOOKS_SRC, HOOKS_DST),
        (MCP_PROXY_SRC, MCP_PROXY_DST),
        (SKILL_LOADER_SRC, SKILL_LOADER_DST),
    ]:
        try:
            rel = p.relative_to(src)
            return src, dst, rel
        except ValueError:
            continue
    return None


def check(tool_name, tool_input, input_data):
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return False
    return _classify(tool_input.get("file_path", "")) is not None


def action(tool_name, tool_input, input_data):
    file_path = Path(tool_input.get("file_path", ""))
    classified = _classify(str(file_path))
    if not classified:
        return None
    src_root, dst_root, rel = classified

    # Apply exclusion filters
    if src_root == HOOKS_SRC:
        if file_path.name in MAC_ONLY_HOOKS:
            return None
        if not file_path.suffix == ".py":
            return None
        # Syntax check for Python hooks
        result = run(["python3", "-m", "py_compile", str(file_path)])
        if result.returncode != 0:
            return f"auto_hook_commit: syntax error in {file_path.name}, not committed"
    else:
        # mcp-proxy / skill-loader: skip private files and node_modules
        if file_path.name in MCP_PRIVATE:
            return None
        if "node_modules" in str(rel):
            return None

    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(file_path, dst)
    except Exception as e:
        return f"auto_hook_commit: copy failed: {e}"

    repo_rel = str(dst.relative_to(BOT_REPO))
    run(["git", "add", repo_rel], cwd=BOT_REPO)
    diff = run(["git", "diff", "--cached", "--name-only"], cwd=BOT_REPO)
    if not diff.stdout.strip():
        return None

    label = src_root.name  # "hooks", "claude-mcp-proxy", "claude-skill-loader"
    run(["git", "commit", "-m", f"{label}: update {file_path.name}"], cwd=BOT_REPO)
    msg = f"auto_hook_commit: {file_path.name} committed to telegram-claude-bot/{label}/"

    # For standalone repos: also push to their own GitHub remote
    if src_root in (MCP_PROXY_SRC, SKILL_LOADER_SRC):
        run(["git", "add", str(file_path)], cwd=src_root)
        diff2 = run(["git", "diff", "--cached", "--name-only"], cwd=src_root)
        if diff2.stdout.strip():
            run(["git", "commit", "-m", f"update {file_path.name}"], cwd=src_root)
        push = run(["git", "push", "origin", "main"], cwd=src_root)
        if push.returncode == 0:
            msg += f" + pushed to {src_root.name} GitHub."
        else:
            msg += f" WARNING: GitHub push failed for {src_root.name}."

    return msg


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    if not check(tool_name, tool_input, input_data):
        print("{}")
        return

    msg = action(tool_name, tool_input, input_data)
    if msg:
        print(json.dumps({"systemMessage": msg}))
    else:
        print("{}")


if __name__ == "__main__":
    main()
