#!/usr/bin/env python3
# Copyright (c) 2026 Nardo. AGPL-3.0 — see LICENSE
"""PreToolUse hook: warn on scp/rsync of text files from remote without compression.

Catches the 2026-04-23 mistake: scp'ing a 289MB skip-log.jsonl from Hel at 25KB/s
(would have taken 3+ hours). Gzipped stream: 15MB -> 306KB in 89s (50x smaller).

Trigger: Bash command contains `scp HOST:PATH` or `rsync HOST:PATH` with a text-file
extension in PATH and no compression flag (scp -C, rsync -z, or `| gzip`/`gzip -c`).

See: memory/lesson_ssh_gzip_jsonl_20260423.md

Writes a warning (systemMessage); does NOT block. Human decides.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hook_base import run_hook

_TEXT_EXTS = (".jsonl", ".json", ".log", ".csv", ".tsv", ".txt", ".xml", ".md", ".yml", ".yaml", ".sql")

# Remote file refs: host:/path/file.ext  OR  host:~/path  OR  user@host:path
_REMOTE_FILE_RE = re.compile(
    r"(?:[A-Za-z0-9_.\-]+@)?[A-Za-z0-9_.\-]+:[~/][^\s'\"]+"
)


def _has_text_ext(token: str) -> bool:
    low = token.lower()
    return any(low.endswith(ext) for ext in _TEXT_EXTS)


def check(tool_name, tool_input, _input_data):
    if tool_name != "Bash":
        return False
    cmd = tool_input.get("command", "")
    if not cmd:
        return False
    # Fast reject: must mention scp or rsync
    if "scp " not in cmd and "rsync " not in cmd:
        return False
    # Must reference a remote file with a text extension
    for m in _REMOTE_FILE_RE.finditer(cmd):
        if _has_text_ext(m.group(0)):
            return True
    return False


def action(tool_name, tool_input, _input_data):
    cmd = tool_input.get("command", "")

    # Compression flags or piped gzip/zstd = already safe
    safe_markers = [
        " -C ", "-C ",          # scp -C compression
        " --compress",
        " gzip ", "| gzip",
        " zstd ", "| zstd",
        "gzip -c", "zstd -c",
        ".gz", ".zst",           # target is already compressed
    ]
    if any(mk in cmd for mk in safe_markers):
        return None
    # rsync combined short flags containing 'z' (e.g. -avz, -avzP, -avzh)
    if re.search(r"\brsync\s+-[a-zA-Z]*z[a-zA-Z]*\b", cmd):
        return None

    tool = "scp" if "scp " in cmd else "rsync"
    # Find the remote file(s) flagged
    remote_files = [m.group(0) for m in _REMOTE_FILE_RE.finditer(cmd) if _has_text_ext(m.group(0))]
    files_str = ", ".join(remote_files[:3])

    return (
        f"UNCOMPRESSED TEXT TRANSFER: `{tool}` is copying text file(s) from remote without compression.\n"
        f"  flagged: {files_str}\n"
        "Text files (.jsonl/.json/.log/.csv/.txt) compress ~10-50x with gzip. The 2026-04-23 incident:\n"
        "  raw scp from Hel = 25KB/s (289MB would take 3+ hours)\n"
        "  gzipped stream = 15MB -> 306KB in 89s (~50x smaller, ~10x faster)\n"
        "Preferred forms:\n"
        "  scp -C host:path/file.jsonl /local/   # scp with compression\n"
        "  rsync -avz host:path/file.jsonl /local/   # rsync -z\n"
        "  ssh host 'gzip -c path/file.jsonl' > /local/file.jsonl.gz   # streamed gzip (fastest)\n"
        "See: memory/lesson_ssh_gzip_jsonl_20260423.md"
    )


if __name__ == "__main__":
    run_hook(check, action, "ssh_uncompressed_textfile_guard")
