---
name: jarvis
description: JARVIS个人AI助手 — Obsidian知识库语义搜索、决策日志记录/查询/复盘、KV记忆管理、索引更新
user_invocable: true
invoke_without_user_explicit_request: true
---

# JARVIS — 统一调用入口

根据 `$ARGUMENTS` 中的子命令，路由到对应Python脚本执行。所有脚本位于vault根目录下的 `.jarvis/` 目录。

**基础路径**: `/Users/wangruijun/Documents/Ruijun的知识库`

## 子命令路由

### search — 语义搜索知识库

在Obsidian vault的向量索引中语义搜索，也可搜索决策日志。

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/search.py "<查询词>" [--top_k 5] [--type "类型"] [--tag "标签"] [--format brief|detail] [--source vault|decisions|all]
```

- 默认 `--source vault` 搜索知识库
- `--source decisions` 搜索决策日志
- `--source all` 两者都搜

### log — 记录新决策

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py log --domain {work|investment} --title "决策标题" [--context "背景"] [--options "可选方案"] [--chosen "最终选择"] [--rationale "理由"] [--risk "风险"] [--tags "标签1,标签2"] [--confidence 1-5]
```

### list — 查询决策列表

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py list [--domain work|investment] [--status open|closed|abandoned] [--tag "标签"] [--days 30] [--limit 20]
```

### show — 查看决策详情+复盘历史

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py show --id <决策ID>
```

### review — 添加决策复盘

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py review --id <决策ID> --score 1-5 --result "实际结果" [--lesson "经验教训"] [--change "如果重来"]
```

### stats — 决策统计分析

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py stats [--domain work|investment]
```

返回：总数、状态分布、已复盘数、平均评分、校准偏差、热门标签、超期未关闭决策。

### memory — KV记忆管理

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py memory set <key> <value> [--category general|work|investment|preference]
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py memory get <key>
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py memory list [--category <分类>]
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py memory delete <key>
```

### index — 更新向量索引

```bash
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/indexer.py          # 增量更新
python3 /Users/wangruijun/Documents/Ruijun的知识库/.jarvis/indexer.py --force   # 全量重建
```

## 自主调用策略

当以下场景出现时，无需用户显式输入 `/jarvis`，应主动调用：

1. **用户问题模糊或跨域** → 执行 `search` 检索相关知识
2. **讨论决策点**（方案选择、投资操作、战略判断）→ 建议执行 `log` 记录
3. **引用历史决策** → 执行 `list` + `show` 获取上下文
4. **需要跨会话状态** → 执行 `memory get/set` 读写短期记忆
5. **用户提到更新/新笔记** → 建议执行 `index` 刷新索引

## 输出格式

所有命令输出为JSON，便于解析后以自然语言向用户呈现结果。搜索结果应摘要呈现关键信息，不要原样倾倒JSON。
