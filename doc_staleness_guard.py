#!/usr/bin/env python3
"""PostToolUse Read hook: warn when a doc has referenced files newer than its verified_at.

Opt-in: docs must have frontmatter with `verified_at: YYYY-MM-DD` and `documents: [path, ...]`.

Fires only for Read tool on .md files. Injects warning into systemMessage if stale.
Never blocks — just informs.
"""
import json
import os
import re
import sys
from datetime import datetime, date
from pathlib import Path


def _expand(p: str) -> Path:
    """Expand ~ and environment variables."""
    return Path(os.path.expandvars(os.path.expanduser(p.strip())))


def _parse_frontmatter(text: str) -> dict | None:
    """Minimal YAML frontmatter parser — only handles fields we need."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    fm_text = text[4:end]
    out = {"verified_at": None, "documents": []}
    in_docs = False
    for line in fm_text.splitlines():
        stripped = line.rstrip()
        if in_docs:
            m = re.match(r"^  - (.+)$", stripped)
            if m:
                out["documents"].append(m.group(1).strip())
                continue
            in_docs = False
        if stripped.startswith("verified_at:"):
            val = stripped.split(":", 1)[1].strip().strip('"\'')
            out["verified_at"] = val
        elif stripped.rstrip() == "documents:":
            in_docs = True
    return out


def _check_staleness(doc_path: Path) -> str | None:
    """Return warning message if doc is stale, else None."""
    if not doc_path.exists() or doc_path.suffix != ".md":
        return None
    try:
        text = doc_path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    fm = _parse_frontmatter(text)
    if not fm or not fm["verified_at"] or not fm["documents"]:
        return None

    try:
        verified = datetime.strptime(fm["verified_at"], "%Y-%m-%d").date()
    except ValueError:
        return None

    verified_ts = datetime.combine(verified, datetime.min.time()).timestamp()
    stale = []
    for ref in fm["documents"]:
        ref_path = _expand(ref)
        if not ref_path.exists():
            continue
        try:
            mtime = ref_path.stat().st_mtime
        except OSError:
            continue
        if mtime > verified_ts:
            mod_date = date.fromtimestamp(mtime).isoformat()
            stale.append(f"{ref_path.name} (edited {mod_date})")

    if not stale:
        return None

    days = (date.today() - verified).days
    preview = ", ".join(stale[:4])
    more = f" (+{len(stale) - 4} more)" if len(stale) > 4 else ""
    return (
        f"⚠️ {doc_path.name} may be stale — verified {verified.isoformat()} ({days}d ago), "
        f"{len(stale)} referenced files edited since: {preview}{more}. "
        f"Refresh before trusting."
    )


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("{}")
        return

    if data.get("tool_name") != "Read":
        print("{}")
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith(".md"):
        print("{}")
        return

    warning = _check_staleness(Path(file_path))
    if warning:
        print(json.dumps({"systemMessage": warning}))
    else:
        print("{}")


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parent))
    from _safe_hook import safe_run
    safe_run(main, "doc_staleness_guard")
