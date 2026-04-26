#!/usr/bin/env python3
# @bigd-hook-meta
# name: lineage_auto_register
# fires_on: PostToolUse
# relevant_intents: [pm, memory, meta]
# irrelevant_intents: [bigd, telegram, docx, x_tweet, git, code, vps, sync, debug]
# cost_score: 1
# always_fire: false
"""PostToolUse hook: auto-register data-producing files into data_lineage.json.

Triggers on Edit | Write | NotebookEdit.
Extension filter: .jsonl, .json, .parquet
Path filter: must be under a known data dir (~/NardoWorld/, ~/inbox/, ~/on-chain-bots/,
             or any path matching */data/* or */logs/*).
Excludes: node_modules, .git, __pycache__, .venv, data_lineage.json itself,
          consistency_registry.json, state_registry.json.

On match: appends stub entry to data_lineage.json collectors dict (keyed by path).
Silent on no-op; prints "[lineage] registered: <path>" only when a new entry is added.
Exit 0 always -- never blocks.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

LINEAGE_PATH = Path("/Users/bernard/NardoWorld/meta/data_lineage.json")

DATA_EXTENSIONS = {".jsonl", ".json", ".parquet"}

KNOWN_DATA_PREFIXES = [
    "/Users/bernard/NardoWorld/",
    "/Users/bernard/inbox/",
    "/Users/bernard/on-chain-bots/",
]

DATA_PATH_PATTERNS = ["/data/", "/logs/"]

EXCLUDE_SUBSTRINGS = [
    "node_modules/",
    "/.git/",
    "__pycache__/",
    "/.venv/",
    "/venv/",
]

EXCLUDE_EXACT = {
    str(LINEAGE_PATH),
    "/Users/bernard/NardoWorld/meta/consistency_registry.json",
    "/Users/bernard/NardoWorld/meta/state_registry.json",
}


def is_target(path: str) -> bool:
    # Extension check
    ext = os.path.splitext(path)[1].lower()
    if ext not in DATA_EXTENSIONS:
        return False
    # Exclude exact paths
    if path in EXCLUDE_EXACT:
        return False
    # Exclude path fragments
    for frag in EXCLUDE_SUBSTRINGS:
        if frag in path:
            return False
    # Path must match known prefix OR contain a data/logs segment
    under_known = any(path.startswith(pfx) for pfx in KNOWN_DATA_PREFIXES)
    under_data_pattern = any(pat in path for pat in DATA_PATH_PATTERNS)
    return under_known or under_data_pattern


def load_lineage():
    try:
        raw = LINEAGE_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, None
        if "collectors" not in data:
            data["collectors"] = {}
        if not isinstance(data["collectors"], dict):
            # File uses object structure; if it's somehow a list convert to dict
            data["collectors"] = {}
        return data, raw
    except Exception:
        return None, None


def write_lineage(data: dict) -> bool:
    try:
        new_text = json.dumps(data, indent=2, ensure_ascii=False)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=LINEAGE_PATH.parent, prefix=".lineage_tmp_"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(new_text)
                f.write("\n")
            os.replace(tmp_path, str(LINEAGE_PATH))
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return False
        return True
    except Exception:
        return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name", "")
    if tool not in ("Edit", "Write", "NotebookEdit"):
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or ""
    )
    if not file_path:
        return 0

    # Expand ~ if present
    file_path = str(Path(file_path).expanduser())

    if not is_target(file_path):
        return 0

    data, _ = load_lineage()
    if data is None:
        return 0

    collectors = data["collectors"]
    if file_path in collectors:
        # Already registered -- no-op
        return 0

    # Build stub entry
    stub = {
        "path": file_path,
        "host": "mac",
        "first_seen_ts": int(time.time()),
        "producer": "<unknown -- auto-registered>",
        "consumers": [],
        "note": "auto-registered by lineage_auto_register hook; manual review needed",
        "status": "AUTO_REGISTERED",
    }

    collectors[file_path] = stub

    if write_lineage(data):
        print(f"[lineage] registered: {file_path}", flush=True)

    return 0


if __name__ == "__main__":
    import io
    sys.path.insert(0, os.path.dirname(__file__))
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
    sys.exit(main())
