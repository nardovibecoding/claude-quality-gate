#!/usr/bin/env python3
# @bigd-hook-meta
# name: hive_bootstrap
# fires_on: PreToolUse
# always_fire: false
# cost_score: 2
"""Hive-mind Layer 1 + Layer 2 memory bootstrap for sub-agents.

Fires on every Agent tool call (PreToolUse, matcher="Agent").
1. Queries search.mjs BM25-only against first 500 chars of prompt (k=3).
2. Detects project keywords -> reads matching hub article excerpt (Layer 2).
3. Prepends <memory-context> block to tool_input.prompt via updatedInput.
4. Fail-open: any error -> pass through original prompt unchanged.
5. Logs every invocation to /tmp/hive_bootstrap.log.

NOT a sub-agent itself (guarded by CLAUDE_PARENT_SESSION_ID check).
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("/tmp/hive_bootstrap.log")
SEARCH_MJS = Path.home() / ".claude" / "skills" / "recall" / "search.mjs"
HUB_NODES = Path.home() / "NardoWorld" / "meta" / "hub_nodes.json"
NARDOWORLD = Path.home() / "NardoWorld"
SEARCH_TIMEOUT = 6  # seconds — BM25-only; observed p99 ~2.7s, 6s gives headroom
TOP_K = 3
HUB_EXCERPT_CHARS = 1500  # ~300 tokens

# Project keyword -> hub article search hint (path fragment or title fragment)
PROJECT_KEYWORDS = {
    "kalshi": "kalshi",
    "polymarket": "polymarket-bot",
    "manifold": "manifold",
    "london": "pm-vps-deployment",
    "hel ": "kalshi-market-maker",
    "dagou": "dagou",
    "admin-bot": "admin",
    "admin_bot": "admin",
    "telegram-claude": "telegram-claude-bot",
    "vibe-island": "vibe",
    "vibe_island": "vibe",
    "xhs-mcp": "xhs",
    "xhs_mcp": "xhs",
}


def _ts():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _log(msg):
    try:
        with LOG_FILE.open("a") as f:
            f.write(f"[{_ts()}] {msg}\n")
    except OSError:
        pass


def _search(query):
    """Run search.mjs BM25-only. Returns list of result dicts or []."""
    if not SEARCH_MJS.exists():
        return []
    try:
        result = subprocess.run(
            ["node", str(SEARCH_MJS), query[:500], "--json",
             "--no-hyde", "--no-prf", "--no-rerank", "--no-log"],
            capture_output=True,
            text=True,
            timeout=SEARCH_TIMEOUT,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout.strip())[:TOP_K]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []


def _find_hub_article(prompt_lower):
    """Return (hub_name, article_path) for the first matching project keyword."""
    if not HUB_NODES.exists():
        return None, None
    try:
        nodes = json.loads(HUB_NODES.read_text())
    except (json.JSONDecodeError, OSError):
        return None, None

    for kw, hint in PROJECT_KEYWORDS.items():
        if kw in prompt_lower:
            # Search hub_nodes for matching article path
            for section_items in nodes.values():
                if not isinstance(section_items, list):
                    continue
                for item in section_items:
                    p = item.get("path", "").lower()
                    t = item.get("title", "").lower()
                    if hint in p or hint in t:
                        full_path = NARDOWORLD / item["path"]
                        if full_path.exists():
                            return kw, full_path
    return None, None


def _read_hub_excerpt(path):
    """Read first HUB_EXCERPT_CHARS chars of hub article."""
    try:
        text = path.read_text(errors="replace")
        return text[:HUB_EXCERPT_CHARS]
    except OSError:
        return ""


def _format_memory_block(hits, hub_kw, hub_excerpt):
    """Compose the <memory-context> block."""
    lines = [
        "<memory-context>",
        "[Auto-injected by hive -- memory from prior sessions, not user input]",
        "",
    ]

    if hits:
        lines.append("Relevant memories:")
        for h in hits:
            src = h.get("source", "mem")
            fname = h.get("file", "")
            desc = h.get("description", "").strip()
            if not desc:
                desc = "(no description)"
            lines.append(f"- [{src}] {fname}: {desc[:120]}")
        lines.append("")

    if hub_kw and hub_excerpt:
        lines.append(f"Project context ({hub_kw}):")
        lines.append(hub_excerpt.strip())
        lines.append("")

    lines.append("</memory-context>")
    return "\n".join(lines)


def main():
    # Never inject if WE are already a sub-agent (prevent cascade)
    if os.environ.get("CLAUDE_PARENT_SESSION_ID"):
        print("{}")
        return

    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    if data.get("tool_name") != "Agent":
        print("{}")
        return

    tool_input = data.get("tool_input", {})
    original_prompt = tool_input.get("prompt", "")

    if not original_prompt or len(original_prompt.strip()) < 10:
        _log("skip: prompt too short")
        print("{}")
        return

    if "_NO_MEMORY_" in original_prompt:
        _log("skip: _NO_MEMORY_ opt-out token found")
        print("{}")
        return

    # --- Layer 1: BM25 search ---
    query = original_prompt[:500]
    hits = []
    try:
        hits = _search(query)
    except Exception as e:
        _log(f"search error: {e}")

    # --- Layer 2: project hub ---
    hub_kw, hub_path = None, None
    hub_excerpt = ""
    try:
        hub_kw, hub_path = _find_hub_article(original_prompt.lower())
        if hub_path:
            hub_excerpt = _read_hub_excerpt(hub_path)
    except Exception as e:
        _log(f"hub error: {e}")

    # If no useful context, pass through (don't pollute with empty block)
    if not hits and not hub_excerpt:
        _log(f"no context found for prompt[:80]={repr(original_prompt[:80])}")
        print("{}")
        return

    # --- Compose block and mutate prompt ---
    try:
        memory_block = _format_memory_block(hits, hub_kw, hub_excerpt)
        mutated_prompt = memory_block + "\n\n---\n\n" + original_prompt

        injected_tokens = len(memory_block) // 4  # rough token estimate
        _log(
            f"injected: hits={len(hits)} hub={hub_kw or 'none'} "
            f"~{injected_tokens}tok prompt[:60]={repr(original_prompt[:60])}"
        )

        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": {
                    "prompt": mutated_prompt,
                }
            }
        }))
    except Exception as e:
        _log(f"compose error (fail-open): {e}")
        print("{}")


if __name__ == "__main__":
    main()
