---
name: obsidian-sync
description: "Sync work updates, project progress, meeting notes, and business data into the correct Obsidian vault knowledge area. TRIGGER when: user mentions syncing to Obsidian, updating vault notes, recording progress, saving meeting notes, or when new work information (investment approvals, project milestones, KPI data, strategy updates) needs to be persisted to the knowledge base. Also trigger when user says '同步到Obsidian', '更新工作区', '记录到笔记', '同步进展', or any variant of saving work context to the vault."
---

# Obsidian Sync — 工作信息同步到知识库

将工作更新信息路由到 Obsidian Vault 的正确知识分区，保持知识库与实际工作进展同步。

## Vault 位置

`/c/Users/01455310/Documents/Obsidian Vault/`

## 路由规则

根据信息类型，定位到正确的目标笔记：

| 信息类型 | 目标路径 | 示例 |
|---------|---------|------|
| 战略/方针/KPI | `26年中集环科工作区/战略框架/` | 公司方针变更、考核指标调整 |
| 产能/工艺/质量/HSE | `26年中集环科工作区/重点行动计划/固本—制造与HSE.md` | 特罐搬迁、医疗基建、工艺标准化 |
| 数字化/IoT/ERP/QMS | `26年中集环科工作区/重点行动计划/培元—创新与数字化.md` | 系统上线、数字化项目进展 |
| 降本/采购优化 | `26年中集环科工作区/重点行动计划/减支—成本领先.md` | 采购策略、成本改善 |
| 渗透率/新市场/多元化 | `26年中集环科工作区/重点行动计划/增收—*.md` | 市场拓展、新业务 |
| 经营数据/财务 | `26年中集环科工作区/经营数据/` | 季度指标、预算执行 |
| 会议纪要 | `26年中集环科工作区/会议纪要/` | 新建笔记，按日期命名 |
| 采购模型/MILP | `运筹优化知识库/项目实战/` | 模型迭代、求解结果 |

## 执行流程

### 1. 识别信息来源

信息可能来自：
- 用户口述或上传的文件（PDF/Excel/PPT）
- 当前对话中完成的工作成果
- 用户指定的更新内容

### 2. 提炼关键信息

从源材料中提取结构化信息：
- 项目名称、责任人、时间节点
- 关键数据（金额、产能、KPI等）
- 决策结论和审批状态
- 里程碑和待办事项

### 3. 定位目标笔记

1. 读取 Vault 的 `CLAUDE.md` 路由表确定目标笔记
2. 用 `Read` 工具读取目标笔记当前内容
3. 确定插入/更新位置（找到对应 section）

### 4. 增量更新

遵循以下原则：
- **增量更新**：只修改变化部分，不重写整个文件
- **保持格式一致**：遵循目标笔记已有的 Markdown 格式和 Obsidian 语法
- **使用 Callout**：重要信息用 `> [!info]`、`> [!warning]` 等 Obsidian callout
- **表格化数据**：财务/指标数据用 Markdown 表格呈现
- **任务清单**：里程碑用 `- [ ]` / `- [x]` 跟踪
- **时间标记**：更新内容标注信息来源日期

### 5. 更新 Claude 工作区记忆

同步完成后，检查 `~/.claude/projects/C--Users-01455310/memory/` 下是否有对应的 project memory：
- 有 → 同步更新 memory 文件
- 无 → 按需创建新的 memory 文件并更新 MEMORY.md 索引

## Frontmatter 约定

新建笔记时必须包含 frontmatter：

```yaml
---
title: "笔记标题"
type: 会议纪要 | 经营数据 | 重点行动计划 | ...
tags:
  - 2026
  - 相关标签
status: 执行中 | 已完成 | 已更新
priority: P0 | P1 | P2
owner: 责任人
date: YYYY-MM-DD
---
```

## 会议纪要特殊处理

新建会议纪要时：
- 文件名格式：`会议主题 YYYY-MM-DD.md`
- frontmatter 额外字段：`host`（主持人）、`attendees`（参会人）
- 放在 `26年中集环科工作区/会议纪要/` 目录下

## 经营数据特殊处理

- 按季度组织（Q1/Q2/Q3/Q4）
- 不覆盖历史数据，新季度新建文件
- 放在 `26年中集环科工作区/经营数据/` 目录下

## 注意事项

- 更新前必须先 Read 目标文件，了解现有内容和格式
- 使用 `Edit` 工具精确修改，不要用 `Write` 覆盖整个文件
- 中文输出，保持与 Vault 现有风格一致
- 使用 Obsidian wikilink 语法 `[[笔记名]]` 做内部链接
- 完成后告知用户更新了哪个文件的哪个部分
