#!/bin/bash
# JARVIS weekly vault index update
# Runs by crontab every Monday 7:17 AM

LOG="/Users/wangruijun/Documents/Ruijun的知识库/.jarvis/data/cron.log"
INDEXER="/Users/wangruijun/Documents/Ruijun的知识库/.jarvis/indexer.py"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
/usr/local/bin/python3 "$INDEXER" >> "$LOG" 2>&1
echo "" >> "$LOG"
