#!/bin/bash
# Mac→VPS sync for repos without GitHub remotes + memory + wiki
# Called from: cron (every 5 min) or post-commit hook
# Only syncs if there are actual changes to push.
#
# What syncs:
#   1. prediction-markets (git bundle — no GitHub remote)
#   2. memory (~/.claude/projects/-Users-bernard/memory/)
#   3. NardoWorld wiki

set -euo pipefail

VPS="vps"
LOG="/tmp/vps_sync.log"
LOCK="/tmp/vps_sync.lock"
BUNDLE="/tmp/pm-sync-bundle.git"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

# Prevent concurrent runs
if [ -f "$LOCK" ]; then
  pid=$(cat "$LOCK" 2>/dev/null)
  if kill -0 "$pid" 2>/dev/null; then
    exit 0
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Quick connectivity check
if ! ssh -o ConnectTimeout=5 "$VPS" true 2>/dev/null; then
  log "VPS unreachable, skipping"
  exit 0
fi

# ─── 1. prediction-markets (git bundle) ──────────────────────────────
PM_DIR="$HOME/prediction-markets"
if [ -d "$PM_DIR/.git" ]; then
  LOCAL_HEAD=$(cd "$PM_DIR" && git rev-parse HEAD)
  REMOTE_HEAD=$(ssh "$VPS" 'cd ~/prediction-markets && git rev-parse HEAD 2>/dev/null' || echo "none")

  if [ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]; then
    log "PM: local=$LOCAL_HEAD VPS=$REMOTE_HEAD — syncing"

    if [ "$REMOTE_HEAD" = "none" ]; then
      # Full bundle
      (cd "$PM_DIR" && git bundle create "$BUNDLE" HEAD --all 2>/dev/null)
    else
      # Incremental bundle
      (cd "$PM_DIR" && git bundle create "$BUNDLE" "$REMOTE_HEAD..HEAD" 2>/dev/null)
    fi

    scp -q "$BUNDLE" "$VPS:/tmp/pm-sync-bundle.git"
    ssh "$VPS" 'cd ~/prediction-markets && \
      git fetch /tmp/pm-sync-bundle.git HEAD:incoming 2>/dev/null && \
      git stash -q 2>/dev/null; \
      git merge incoming --ff-only 2>/dev/null && \
      git branch -d incoming 2>/dev/null && \
      git stash pop -q 2>/dev/null; \
      rm -f /tmp/pm-sync-bundle.git' 2>/dev/null

    # Rebuild + restart scanner if TS/script files changed
    CHANGED=$(cd "$PM_DIR" && git diff --name-only "$REMOTE_HEAD..HEAD" -- '*.ts' '*.sh' 2>/dev/null | head -1)
    if [ -n "$CHANGED" ]; then
      log "PM: code changed, rebuilding + restarting scanner on VPS"
      ssh "$VPS" 'cd ~/prediction-markets && npm run build 2>/dev/null && \
        tmux kill-session -t scanner 2>/dev/null; sleep 1; \
        tmux new-session -d -s scanner "bash /home/bernard/prediction-markets/scripts/start-scanner.sh" && \
        echo "Scanner restarted with new code"' 2>/dev/null &
    fi

    log "PM: synced to $LOCAL_HEAD"
    rm -f "$BUNDLE"
  fi
fi

# ─── 2. Memory (git push/pull to self-hosted bare repo, migrated 2026-04-23) ───
MEMORY_DIR="$HOME/.claude/projects/-Users-bernard/memory"
if [ -d "$MEMORY_DIR/.git" ]; then
  # pull remote changes (VPS writes), then commit+push local
  (cd "$MEMORY_DIR" && \
    git pull --rebase origin main 2>/dev/null ; \
    git add -A && git commit -m "mac-periodic: $(date +%FT%T)" --allow-empty-message 2>/dev/null ; \
    git push origin main 2>/dev/null \
      || (git pull --rebase origin main 2>/dev/null && git push origin main 2>/dev/null)
  ) && log "Memory: git synced" || log "Memory: git sync failed (see /tmp/memory_auto_commit.log)"
fi

# ─── 3. NardoWorld wiki (git push/pull to self-hosted bare repo, migrated 2026-04-23) ───
WIKI_DIR="$HOME/NardoWorld"
if [ -d "$WIKI_DIR/.git" ]; then
  (cd "$WIKI_DIR" && \
    git pull --rebase origin main 2>/dev/null ; \
    git add -A && git commit -m "mac-periodic: $(date +%FT%T)" --allow-empty-message 2>/dev/null ; \
    git push origin main 2>/dev/null \
      || (git pull --rebase origin main 2>/dev/null && git push origin main 2>/dev/null)
  ) && log "Wiki: git synced" || log "Wiki: git sync failed"
fi

# ─── 4. Claude scripts (rsync) ───────────────────────────────────────
SCRIPTS_DIR="$HOME/.claude/scripts/"
if [ -d "$SCRIPTS_DIR" ]; then
  rsync -az --exclude='__pycache__' \
    "$SCRIPTS_DIR" \
    "$VPS:~/.claude/scripts/" \
    2>/dev/null && log "Scripts: synced" || log "Scripts: rsync failed"
fi

# ─── 5. Skills git pull with rebase fallback (fixes ff-only silent abort) ───
SKILLS_DIR="$HOME/.claude/skills"
if [ -d "$SKILLS_DIR/.git" ]; then
  git -C "$SKILLS_DIR" pull --rebase origin main 2>/dev/null \
    || git -C "$SKILLS_DIR" pull --no-rebase origin main 2>/dev/null \
    && log "Skills: pulled" \
    || log "Skills: pull failed — manual resolve needed"
fi

log "Sync complete"
