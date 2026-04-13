#!/bin/bash
# JARVIS: Sync vault from GitHub and update vector index
# Runs daily at 7:03 and 22:03 via launchd

VAULT="/Users/wangruijun/Documents/Ruijun的知识库"
LOG="$VAULT/.jarvis/data/sync.log"
INDEXER="$VAULT/.jarvis/indexer.py"
PYTHON="/usr/local/bin/python3"

# Fallback python path
if [ ! -x "$PYTHON" ]; then
    PYTHON="/usr/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(which python3 2>/dev/null)"
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') sync start ===" >> "$LOG"

cd "$VAULT" || { echo "ERROR: cannot cd to $VAULT" >> "$LOG"; exit 1; }

# Only stash tracked file modifications (not untracked files like logs/scripts)
TRACKED_DIRTY=$(git diff --name-only 2>/dev/null)
STAGED_DIRTY=$(git diff --cached --name-only 2>/dev/null)
if [ -n "$TRACKED_DIRTY" ] || [ -n "$STAGED_DIRTY" ]; then
    echo "  stashing tracked changes..." >> "$LOG"
    git stash push --no-include-untracked -m "jarvis-sync-autostash" >> "$LOG" 2>&1
    STASHED=1
else
    STASHED=0
fi

# Pull with rebase to keep history clean
echo "  git pull --rebase origin master..." >> "$LOG"
PULL_OUTPUT=$(git pull --rebase origin master 2>&1)
PULL_STATUS=$?
echo "$PULL_OUTPUT" >> "$LOG"

# Restore stashed changes
if [ "$STASHED" -eq 1 ]; then
    echo "  restoring stashed changes..." >> "$LOG"
    git stash pop >> "$LOG" 2>&1
fi

# Check if new files were pulled
if echo "$PULL_OUTPUT" | grep -q "Already up to date"; then
    echo "  no changes, skipping index update" >> "$LOG"
else
    if [ $PULL_STATUS -eq 0 ]; then
        echo "  new changes pulled, updating index..." >> "$LOG"
        "$PYTHON" "$INDEXER" >> "$LOG" 2>&1
        echo "  index updated" >> "$LOG"
    else
        echo "  ERROR: git pull failed (status=$PULL_STATUS), will retry next run" >> "$LOG"
    fi
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') sync done ===" >> "$LOG"
echo "" >> "$LOG"
