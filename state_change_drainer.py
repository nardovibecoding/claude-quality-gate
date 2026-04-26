#!/usr/bin/env python3
# @bigd-hook-meta
# name: state_change_drainer
# fires_on: Stop
# always_fire: true
# cost_score: 2
"""Stop hook: drain state_change_inbox.jsonl and update LATEST STATE blocks.

Convention map (file_path → memory target):
  ~/.claude/hooks/<name>.py/.sh  → ~/NardoWorld/projects/claude-harness/hooks-<name>.md
  ~/prediction-markets/scripts/<name>.py → ~/NardoWorld/projects/prediction-markets/scripts-<name>.md
  ~/prediction-markets/config/<name>.json → ~/NardoWorld/projects/prediction-markets/config-<name>.md
  ~/prediction-markets/packages/bot/src/<...> → ~/NardoWorld/projects/prediction-markets/bot-<basename>.md
  other → ~/NardoWorld/meta/unmapped_state_changes.md (one-line append)

After drain: renames inbox to state_change_inbox.<date>.processed.jsonl
"""
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

INBOX = Path("/Users/bernard/NardoWorld/meta/state_change_inbox.jsonl")
HARNESS_DIR = Path("/Users/bernard/NardoWorld/projects/claude-harness")
PM_DIR = Path("/Users/bernard/NardoWorld/projects/prediction-markets")
UNMAPPED = Path("/Users/bernard/NardoWorld/meta/unmapped_state_changes.md")

# Frontmatter regex helpers
_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_STATE_BLOCK_RE = re.compile(r"(## LATEST STATE[^\n]*\n)(.*?)(?=\n## |\Z)", re.DOTALL)
_HISTORY_RE = re.compile(r"(## State history\n)(.*)", re.DOTALL)


def map_file_to_target(file_path: str) -> Path | None:
    """Return the memory target Path for a given file_path, or None for unmapped."""
    fp = file_path
    home = str(Path.home())

    # Normalize ~ expansion
    if fp.startswith("~"):
        fp = home + fp[1:]

    p = Path(fp)
    name = p.stem  # filename without extension

    # ~/.claude/hooks/<name>.py or .sh
    if re.search(r"/\.claude/hooks/[^/]+\.(py|sh)$", fp):
        HARNESS_DIR.mkdir(parents=True, exist_ok=True)
        return HARNESS_DIR / f"hooks-{name}.md"

    # ~/prediction-markets/scripts/<name>.py
    if re.search(r"/prediction-markets/scripts/[^/]+\.py$", fp):
        PM_DIR.mkdir(parents=True, exist_ok=True)
        return PM_DIR / f"scripts-{name}.md"

    # ~/prediction-markets/config/<name>.json (and other extensions)
    if re.search(r"/prediction-markets/config/[^/]+$", fp):
        PM_DIR.mkdir(parents=True, exist_ok=True)
        return PM_DIR / f"config-{name}.md"

    # ~/prediction-markets/packages/bot/src/...
    if re.search(r"/prediction-markets/packages/bot/src/", fp):
        PM_DIR.mkdir(parents=True, exist_ok=True)
        return PM_DIR / f"bot-{name}.md"

    return None  # unmapped


def get_git_hash(file_path: str) -> str:
    """Return short git hash for the file's last commit, or 'no-git'."""
    p = Path(file_path)
    repo_dir = p.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "-1", "--format=%h", str(file_path)],
            capture_output=True, text=True, timeout=5
        )
        h = result.stdout.strip()
        if h:
            return h
        # Try with file_path as relative to cwd
        result2 = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "-1", "--format=%h", p.name],
            capture_output=True, text=True, timeout=5
        )
        h2 = result2.stdout.strip()
        return h2 if h2 else "no-git"
    except Exception:
        return "no-git"


def ensure_target_exists(target: Path, source_path: str) -> None:
    """Create a minimal target file if it doesn't exist."""
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    name = target.stem
    content = f"""---
title: {name}
has_state: true
state_updated: {today}
---

## LATEST STATE ({today})
enabled: []
disabled: []
params: {{}}
verify: `echo "check {source_path}"`

## State history
"""
    target.write_text(content)


def update_latest_state(target: Path, source_path: str, delta_line: str) -> None:
    """Insert delta_line at top of LATEST STATE block; move previous head to State history."""
    text = target.read_text()
    today = datetime.date.today().isoformat()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # Update frontmatter state_updated
    if _FM_RE.search(text):
        text = re.sub(r"state_updated:.*", f"state_updated: {today}", text)
    else:
        # No frontmatter, prepend minimal
        text = f"---\nhas_state: true\nstate_updated: {today}\n---\n\n" + text

    # Update date in ## LATEST STATE header
    text = re.sub(
        r"(## LATEST STATE)\s*\([^)]*\)",
        rf"\1 ({today})",
        text
    )

    # Locate the LATEST STATE block
    m = _STATE_BLOCK_RE.search(text)
    if m:
        header = m.group(1)
        body = m.group(2).rstrip()

        # Extract first content line (current head) for archiving
        lines = body.splitlines()
        # Filter to actual content lines (non-empty, not sub-headers)
        content_lines = [l for l in lines if l.strip() and not l.startswith("##")]
        old_head = content_lines[0] if content_lines else ""

        # Prepend delta line into block
        new_body = delta_line + "\n" + body
        text = text[:m.start()] + header + new_body + text[m.end():]

        # Archive old head into State history if it has substance
        if old_head and not old_head.startswith("-"):
            archive_entry = f"\n### {now_str}\n- {old_head}\n"
        elif old_head:
            archive_entry = f"\n### {now_str}\n{old_head}\n"
        else:
            archive_entry = ""

        if archive_entry:
            hm = _HISTORY_RE.search(text)
            if hm:
                # Insert after ## State history header
                insert_pos = hm.start(2)
                text = text[:insert_pos] + archive_entry + text[insert_pos:]
            else:
                # Append State history section
                text = text.rstrip() + f"\n\n## State history\n{archive_entry}"

        # Enforce 10-entry cap on State history
        text = cap_state_history(text)
    else:
        # No LATEST STATE block exists, append one
        text = text.rstrip() + f"\n\n## LATEST STATE ({today})\n{delta_line}\n\n## State history\n"

    target.write_text(text)


def cap_state_history(text: str, max_entries: int = 10) -> str:
    """Keep only the last max_entries in State history (drop oldest)."""
    hm = _HISTORY_RE.search(text)
    if not hm:
        return text
    history_start = hm.start(2)
    history_body = hm.group(2)

    # Split on ### entries
    entries = re.split(r"(?=### )", history_body)
    entries = [e for e in entries if e.strip()]

    if len(entries) <= max_entries:
        return text

    # Keep only last max_entries
    trimmed = entries[-max_entries:]
    new_history = "".join(trimmed)
    text = text[:history_start] + new_history
    return text


def append_unmapped(file_path: str, delta_line: str) -> None:
    """Append one line to unmapped_state_changes.md."""
    UNMAPPED.parent.mkdir(parents=True, exist_ok=True)
    if not UNMAPPED.exists():
        UNMAPPED.write_text("# Unmapped state changes\n\nFiles edited but not mapped to a memory target.\n\n")
    with UNMAPPED.open("a") as fh:
        fh.write(f"- {delta_line} — `{file_path}`\n")


def main():
    if not INBOX.exists():
        return 0

    try:
        raw = INBOX.read_text().strip()
    except Exception:
        return 0

    if not raw:
        return 0

    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue

    if not rows:
        return 0

    # Collect unique file_paths
    seen = {}
    for row in rows:
        fp = row.get("file_path", "")
        if fp and fp not in seen:
            seen[fp] = row

    for file_path, row in seen.items():
        tool = row.get("tool", "Edit")
        git_hash = get_git_hash(file_path)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        delta_line = f"- {now_str} — {tool} (commit {git_hash})"

        target = map_file_to_target(file_path)

        if target is None:
            append_unmapped(file_path, delta_line)
        else:
            try:
                ensure_target_exists(target, file_path)
                update_latest_state(target, file_path, delta_line)
            except Exception as e:
                # Fallback: append to unmapped so nothing is silently lost
                append_unmapped(file_path, f"{delta_line} [drainer-error: {e}]")

    # Rename inbox to processed
    today = datetime.date.today().isoformat()
    processed_path = INBOX.parent / f"state_change_inbox.{today}.processed.jsonl"
    # If file already exists (multiple sessions same day), append
    if processed_path.exists():
        with processed_path.open("a") as fh:
            fh.write(raw + "\n")
        INBOX.unlink()
    else:
        INBOX.rename(processed_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
