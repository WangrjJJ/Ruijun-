#!/bin/bash
# Claude Code 记忆同步脚本
# 用法: bash sync_memory.sh        （从 .claude → Vault，然后 push）
#       bash sync_memory.sh restore （从 Vault → .claude，新设备恢复用）

MEMORY_SRC="/c/Users/01455310/.claude/projects/C--Users-01455310/memory"
VAULT_DST="/c/Users/01455310/Documents/Obsidian Vault/Claude记忆同步"
VAULT_ROOT="/c/Users/01455310/Documents/Obsidian Vault"

if [ "$1" = "restore" ]; then
    echo "=== 恢复模式：Vault → .claude ==="
    mkdir -p "$MEMORY_SRC"
    cp "$VAULT_DST"/*.md "$MEMORY_SRC/"
    echo "✓ 已恢复 $(ls "$VAULT_DST"/*.md | wc -l) 个记忆文件到 .claude"
    exit 0
fi

echo "=== 同步模式：.claude → Vault → GitHub ==="

# Step 1: 复制最新记忆文件（排除脚本自身）
cp "$MEMORY_SRC"/*.md "$VAULT_DST/"
echo "✓ 已复制 $(ls "$MEMORY_SRC"/*.md | wc -l) 个记忆文件"

# Step 2: Git commit & push
cd "$VAULT_ROOT"
git add "Claude记忆同步/"
CHANGES=$(git diff --cached --stat)
if [ -z "$CHANGES" ]; then
    echo "✓ 无变更，跳过提交"
else
    git commit -m "sync: Claude记忆同步 $(date +%Y-%m-%d)"
    git push
    echo "✓ 已推送到 GitHub"
fi
