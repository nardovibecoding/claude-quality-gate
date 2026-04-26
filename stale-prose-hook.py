#!/usr/bin/env python3
# Copyright (c) 2026 Nardo. AGPL-3.0
"""PreToolUse hook: block git commit when staged diff symbols appear in
untouched prose (JSON _note, TODO/FIXME/HACK/XXX/NOTE comments,
@deprecated, .ship/*/goals/*.md verdicts) — write-side enforcement of
CLAUDE.md §Stale-prose vs live-source.

Hook protocol: read PreToolUse JSON from stdin, exit 0 to allow, exit 2
to block. stderr is surfaced to the model.

Skip marker: add [skip-stale-check=<reason>] to commit message subject.
Logs skips to ~/.claude/scripts/state/stale-prose-skips.jsonl.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
STATE_DIR = HOME / ".claude/scripts/state"
SKIPS_FILE = STATE_DIR / "stale-prose-skips.jsonl"

# ── Exclusion list (mirrors stale-prose-audit.py) ─────────────────────────
EXCLUDE_GLOBS = [
    "*/dist/*", "*/build/*", "*/node_modules/*", "*/.git/*", "*/.venv/*",
    "*/venv/*", "*/__pycache__/*", "*.pyc", "*.pyo", "*.lock", "*.log",
    ".env", ".env.*", "*.pem", "*.key",
    "*/.ship/*/experiments/*", "*/data/*", "*/cache/*", "*/.cache/*",
    "*/test-fixtures/*", "*/tests/snapshots/*",
]
EXCLUDE_DIRS = {
    "node_modules", ".git", "dist", "build", ".venv",
    "venv", "__pycache__", ".cache", "data", "cache",
}

# ── Pattern regexes (sourced from stale-prose-audit.py idioms) ────────────
NOTE_FIELD_RE = re.compile(r"^_[\w]*notes?$|^_note$", re.I)
DEPRECATED_RE = re.compile(r"@deprecated\b", re.I)
TODO_RE = re.compile(r"(?://|#)\s*(TODO|FIXME|HACK|XXX)\b", re.I)
NOTE_COMMENT_RE = re.compile(r"(?://|#)\s*NOTE\s*:", re.I)
VERDICT_RE = re.compile(r"^\s*\*\*(Verdict|Status|Result)\*\*", re.I)
# Symbol patterns from diff: PascalCase, camelCase (interior uppercase), snake_case (4+ chars)
SYMBOL_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9]{3,}"           # PascalCase: MyFunc, ThingX
    r"|[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]+"  # camelCase: thingXHandler, myFunc
    r"|[a-z_]+[a-z][_][a-z_]+)\b"        # snake_case: zebra_parser, my_func
)
# Skip marker in commit message
SKIP_RE = re.compile(r"\[skip-stale-check(?:=(?P<reason>[^\]]+))?\]", re.I)

SCAN_EXTS = {".json", ".ts", ".tsx", ".js", ".jsx", ".py", ".md"}


def is_excluded(path_str: str) -> bool:
    for g in EXCLUDE_GLOBS:
        if fnmatch.fnmatch(path_str, g):
            return True
    return False


def extract_symbols(diff_text: str) -> set[str]:
    """Extract changed symbol names from unified diff +/- lines."""
    symbols: set[str] = set()
    for line in diff_text.splitlines():
        if not line.startswith(("+", "-")):
            continue
        if line.startswith(("+++", "---")):
            continue
        found = SYMBOL_RE.findall(line[1:])
        for sym in found:
            if len(sym) >= 4:
                symbols.add(sym)
    return symbols


def get_staged_info(repo_root: str) -> tuple[list[str], str]:
    """Return (changed_files, diff_text). Both empty on error."""
    try:
        names_out = subprocess.run(
            ["git", "-C", repo_root, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=5
        )
        changed = [f.strip() for f in names_out.stdout.splitlines() if f.strip()]
        diff_out = subprocess.run(
            ["git", "-C", repo_root, "diff", "--cached"],
            capture_output=True, text=True, timeout=10
        )
        return changed, diff_out.stdout
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return [], ""


def find_git_root(cwd: str) -> str | None:
    """Walk up from cwd to find .git directory."""
    p = Path(cwd).resolve()
    for candidate in [p] + list(p.parents):
        if (candidate / ".git").exists():
            return str(candidate)
    return None


def iter_repo_files(repo_root: Path):
    """Yield Path objects for scannable files in repo."""
    for dp, dnames, fnames in os.walk(str(repo_root)):
        dnames[:] = [d for d in dnames if d not in EXCLUDE_DIRS]
        for fn in fnames:
            p = Path(dp) / fn
            if p.suffix in SCAN_EXTS and not is_excluded(str(p)):
                yield p


def scan_file_for_symbols(
    fpath: Path,
    symbols: set[str],
) -> list[dict]:
    """Return list of {lineno, line, pclass, symbol} matches."""
    hits: list[dict] = []
    try:
        raw = fpath.read_text(errors="ignore")
    except OSError:
        return hits

    lines = raw.splitlines()
    is_md = fpath.suffix == ".md"
    is_ship_verdict = (
        ".ship/" in str(fpath) and "/goals/" in str(fpath) and is_md
    )
    is_json = fpath.suffix == ".json"

    # JSON: scan _note / _*_note fields
    if is_json:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, dict):
            for k, v in _walk_json(data):
                if not isinstance(v, str):
                    continue
                if not NOTE_FIELD_RE.match(k):
                    continue
                # find which symbols appear in value
                for sym in symbols:
                    if sym in v:
                        # find line number
                        for lineno, L in enumerate(lines, 1):
                            if f'"{k}"' in L:
                                hits.append({
                                    "lineno": lineno,
                                    "line": L.rstrip()[:200],
                                    "pclass": "_note",
                                    "symbol": sym,
                                    "value_excerpt": v[:200],
                                })
                                break
        return hits

    # Code / Markdown: scan line by line
    fence_depth = 0
    for i, line in enumerate(lines, 1):
        if is_md:
            if line.lstrip().startswith("```"):
                fence_depth = 1 - fence_depth
            if fence_depth:
                continue

        pclass = None
        if DEPRECATED_RE.search(line):
            pclass = "deprecated"
        elif TODO_RE.search(line):
            pclass = "todo_fixme"
        elif NOTE_COMMENT_RE.search(line):
            pclass = "note_comment"
        elif is_ship_verdict and VERDICT_RE.match(line):
            pclass = "ship_verdict"

        if pclass is None:
            continue

        for sym in symbols:
            if sym in line:
                hits.append({
                    "lineno": i,
                    "line": line.rstrip()[:200],
                    "pclass": pclass,
                    "symbol": sym,
                    "value_excerpt": line.strip()[:200],
                })
                break  # one match per line is enough

    return hits


def _walk_json(obj, _depth=0):
    """Yield (key, value) pairs from nested dict. Depth-limited."""
    if _depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            if isinstance(v, (dict, list)):
                yield from _walk_json(v, _depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_json(item, _depth + 1)


def log_skip(command: str, reason: str, repo_root: str):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": "skip",
        "command": command[:200],
        "reason": reason,
        "repo": repo_root,
    }
    try:
        with SKIPS_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def main():
    t0 = time.time()
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Only intercept Bash tool calls
    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = (data.get("tool_input") or {}).get("command", "")
    if not command:
        sys.exit(0)

    # Only intercept git commit commands
    if not re.search(r"\bgit\s+commit\b", command):
        sys.exit(0)

    # Extract commit message from -m flag for skip-marker check
    msg_match = re.search(r'-m\s+["\']?([^"\'\\n]+)', command)
    commit_msg = msg_match.group(1) if msg_match else ""

    # Check skip marker
    skip_m = SKIP_RE.search(commit_msg) or SKIP_RE.search(command)
    if skip_m:
        reason = (skip_m.group("reason") or "").strip() or "no-reason"
        # Detect repo root from cwd
        cwd = os.getcwd()
        repo_root = find_git_root(cwd) or cwd
        log_skip(command, reason, repo_root)
        sys.exit(0)

    # Find repo root
    cwd = os.getcwd()
    repo_root = find_git_root(cwd)
    if not repo_root:
        sys.exit(0)  # not in a git repo — allow

    # Get staged changes
    changed_files_rel, diff_text = get_staged_info(repo_root)
    if not diff_text.strip():
        sys.exit(0)  # nothing staged

    # Build set of absolute changed paths for fast lookup
    changed_abs = {
        str((Path(repo_root) / f).resolve())
        for f in changed_files_rel
    }

    # Extract symbols from the diff
    symbols = extract_symbols(diff_text)
    if not symbols:
        sys.exit(0)  # no recognisable symbols changed

    # Perf guard: cap symbol set to avoid O(n*m) blow-up on giant diffs
    if len(symbols) > 200:
        # Keep longest (most specific) symbols
        symbols = set(sorted(symbols, key=len, reverse=True)[:200])

    # Scan repo for prose matches
    repo_path = Path(repo_root)
    matches: list[dict] = []

    for fpath in iter_repo_files(repo_path):
        # Skip files that ARE in the staged changeset
        if str(fpath.resolve()) in changed_abs:
            continue
        file_matches = scan_file_for_symbols(fpath, symbols)
        if file_matches:
            for m in file_matches:
                m["file"] = str(fpath)
            matches.extend(file_matches)
        # Perf: cap total matches reported
        if len(matches) >= 20:
            break

    elapsed = time.time() - t0

    if not matches:
        sys.exit(0)

    # Build block message
    lines = [
        "stale-prose-hook: BLOCKED — staged diff touches symbols referenced in",
        "prose files not included in this commit.",
        "",
        "These prose items may describe the old behavior and need updating:",
        "",
    ]
    for m in matches[:10]:
        lines.append(f"  {m['file']}:{m['lineno']}  [{m['pclass']}]  symbol={m['symbol']!r}")
        lines.append(f"  > {m['value_excerpt']}")
        lines.append("")

    lines.append("Options:")
    lines.append("  1. Update the prose in the same commit (add the prose file to your changes).")
    lines.append("  2. Add [skip-stale-check=<reason>] to your commit message subject to bypass.")
    lines.append("     This will be logged to ~/.claude/scripts/state/stale-prose-skips.jsonl.")
    lines.append("")
    lines.append(f"  (scan took {elapsed:.2f}s)")

    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
