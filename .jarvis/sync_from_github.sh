#!/bin/bash
# JARVIS: Sync vault from GitHub and update vector index
# Runs daily at 7:03 and 22:03 via launchd

VAULT="/Users/wangruijun/Documents/Ruijun的知识库"
LOG="/Users/wangruijun/.jarvis/logs/sync.log"
INDEXER="$VAULT/.jarvis/indexer.py"
PYTHON="/usr/local/bin/python3"

# Fallback python path
if [ ! -x "$PYTHON" ]; then
    PYTHON="/usr/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(which python3 2>/dev/null)"
fi

mkdir -p "$(dirname "$LOG")"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') sync start ===" >> "$LOG"

cd "$VAULT" || { echo "ERROR: cannot cd to $VAULT" >> "$LOG"; exit 1; }

# Pull with autostash (git handles stash/unstash of tracked changes)
echo "  git pull --rebase --autostash..." >> "$LOG"
PULL_OUTPUT=$(git pull --rebase --autostash origin master 2>&1)
PULL_STATUS=$?
echo "$PULL_OUTPUT" >> "$LOG"

# Update index if new content was pulled
if echo "$PULL_OUTPUT" | grep -q "Already up to date"; then
    echo "  no changes, skipping index update" >> "$LOG"
elif [ $PULL_STATUS -eq 0 ]; then
    echo "  new changes pulled, updating index..." >> "$LOG"
    "$PYTHON" "$INDEXER" >> "$LOG" 2>&1
    echo "  index updated" >> "$LOG"
else
    echo "  ERROR: git pull failed (status=$PULL_STATUS), will retry next run" >> "$LOG"
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') sync done ===" >> "$LOG"
echo "" >> "$LOG"

# Keep log file under 1000 lines
tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
