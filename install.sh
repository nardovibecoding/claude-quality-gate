#!/bin/bash
# install.sh — install simply-quality-gate hooks into ~/.claude/hooks/.
# Idempotent: re-running this is safe (overwrites existing files, preserves
# user-edited settings.json by merging hooks.json entries non-destructively).
# Platform: macOS + Linux (Claude Code required).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOKS_DST="${HOOKS_DST:-$HOME/.claude/hooks}"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

echo "==> simply-quality-gate install"
echo "    repo:        $REPO_DIR"
echo "    hooks dst:   $HOOKS_DST"
echo "    settings:    $SETTINGS"

# 0. Verify Claude Code is installed
if [ ! -d "$HOME/.claude" ]; then
    echo "    ✗ ~/.claude/ not found — Claude Code is required. Install from https://claude.com/claude-code" >&2
    exit 1
fi
mkdir -p "$HOOKS_DST"

# 1. Copy hook .py files (excluding tests, lib, README, NOTICE, LICENSE)
echo "==> copying hook files"
COPIED=0
for f in "$REPO_DIR"/*.py; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    # Skip tests + scaffolding files that are not hooks
    case "$base" in
        test_*|*_test.py|conftest.py) continue ;;
    esac
    cp "$f" "$HOOKS_DST/$base"
    COPIED=$((COPIED + 1))
done
# Copy hook_client.sh + lib/ if present
[ -f "$REPO_DIR/hook_client.sh" ] && cp "$REPO_DIR/hook_client.sh" "$HOOKS_DST/"
if [ -d "$REPO_DIR/lib" ]; then
    mkdir -p "$HOOKS_DST/lib"
    cp -R "$REPO_DIR/lib/." "$HOOKS_DST/lib/"
fi
echo "    ✓ copied $COPIED hooks"

# 2. Merge hooks.json into settings.json (idempotent)
if [ -f "$REPO_DIR/hooks.json" ]; then
    if [ ! -f "$SETTINGS" ]; then
        echo '{}' > "$SETTINGS"
    fi
    python3 - <<EOF
import json
from pathlib import Path
src_path = Path("$REPO_DIR/hooks.json")
dst_path = Path("$SETTINGS")
src = json.loads(src_path.read_text())
dst = json.loads(dst_path.read_text())
src_hooks = src.get("hooks", {})
dst_hooks = dst.setdefault("hooks", {})
added = 0
for event, entries in src_hooks.items():
    existing = {json.dumps(e, sort_keys=True) for e in dst_hooks.get(event, [])}
    bucket = dst_hooks.setdefault(event, [])
    for entry in entries:
        key = json.dumps(entry, sort_keys=True)
        if key not in existing:
            bucket.append(entry)
            existing.add(key)
            added += 1
dst_path.write_text(json.dumps(dst, indent=2))
print(f"    ✓ merged {added} new hook entries into {dst_path}")
EOF
fi

# 3. Next steps
cat <<EOF

==> install complete

Next steps:
  1. Restart Claude Code to load the new hooks.
  2. Inspect what fired:   cat $HOOKS_DST/.router_log.jsonl | tail
  3. Disable a hook:       mv $HOOKS_DST/<name>.py $HOOKS_DST/<name>.py.disabled
  4. Re-run installer:     bash $REPO_DIR/install.sh

To uninstall:
  rm $HOOKS_DST/<copied-files>.py
  Edit $SETTINGS and remove the merged entries from "hooks".
EOF
