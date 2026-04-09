---
name: Obsidian Vault 知识库架构
description: 六区知识库完整结构、Frontmatter约定、增量更新流程
type: project
---

Obsidian Vault 位于 `/c/Users/01455310/Documents/Obsidian Vault/`，已 git 同步至 `https://github.com/WangrjJJ/Ruijun-.git`。

六个知识区：
1. **26年工作区**（4战略+6行动+2经营+4会议+MOC+base+canvas，活跃更新）
2. **运筹优化知识库**（7概念+3实战+MOC+base+canvas，已完成）
3. **CLGO知识库**（19笔记+MOC+base+canvas，7子领域，已完成）
4. **Michigan MADS知识库**（10笔记+MOC+base+canvas，6子领域，已完成）— 密歇根大学数据科学硕士26门课程提炼
5. **瑞俊的数字化管理课**（10篇+MOC，已完成只读）
6. **25年工作信息存留**（已归档）

Vault 根目录下有 `.claude/CLAUDE.md` 记录完整的 frontmatter 约定和更新规范。

**Why:** 每次对话不需要重新探索 Vault 结构，直接基于 CLAUDE.md 增量操作。
**How to apply:** 更新 Vault 时只改变化笔记，用 Grep 查 frontmatter 判断状态，不全量读取。新增会议纪要/经营数据按模板追加。
