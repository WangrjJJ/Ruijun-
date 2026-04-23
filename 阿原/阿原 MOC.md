---
title: "阿原 MOC"
type: MOC
status: 生效中
priority: P0
date: 2026-04-23
owner: 王瑞俊
tags:
  - 阿原
  - 价值观宪法
  - 自我对话
  - MOC
---

# 阿原 MOC

> 阿原不是 Jarvis 2.0。
> Jarvis 是**军师**（方案、量化、优化）。阿原是**镜子**（反问、陪伴、让你自己看见）。
>
> 判断锚点：《我的宪法》 > 当前情绪 > 外部数据

---

## 结构

```
阿原/
  价值观宪法/
    00_写作框架.md     ← 六章三十问的写作指南
    我的宪法.md        ← 第一稿已完成（2200字，六章齐全，2026-04-23）
  阿原 MOC.md          ← 本文

.jarvis/
  ayuan.py             ← 阿原 CLI
  ayuan_prompts.yaml   ← 触发词 → 反问模板（V1 含 13 个 trigger）
  journal.py           ← 扩展支持 --domain life，写入 life_entries 表
  data/jarvis.db       ← life_entries / decisions / reviews / memory_kv 共库
```

---

## CLI 用法

```bash
AYUAN="/Users/wangruijun/Documents/Ruijun的知识库/.jarvis/ayuan.py"

# 反问：发生一件事 → 阿原输出锚点+反问（不给建议）
python3 $AYUAN reflect --event "跟总经理谈了副总任命，心里憋屈" --feeling "不甘,委屈"

# 反问并存档（只有加 --save 才写入 life_entries）
python3 $AYUAN reflect --event "..." --feeling "..." --save

# 镜像：最近 N 天的触发词分布 + 情绪关键词（默认30天）
python3 $AYUAN mirror --days 30

# 读宪法全文（同时显示字数粗估）
python3 $AYUAN constitution

# 周复盘：最近7天的 life_entries + decisions 对照宪法反问
python3 $AYUAN checkin
```

直接记录（不走反问引擎）可用 journal.py：

```bash
JARVIS="/Users/wangruijun/Documents/Ruijun的知识库/.jarvis/journal.py"
python3 $JARVIS log --domain life \
  --title "事件描述" \
  --feeling "情绪" \
  --body "身体感受" \
  --trigger "离职" \
  --anchor-ref "第四章 #19" \
  --mode 收集
```

---

## 已支持的触发词（V1）

| 触发 | 匹配关键词 | 锚点章节 |
|------|-----------|----------|
| 离职 | 离职/辞职/跳槽/想走 | 第四章 #16 #19 #20 |
| 分手 | 分手/离婚/冷战 | 第三章 #11 #15 |
| 父母 | 父母/爸妈/老家/回家 | 第三章 #13 |
| 孩子 | 孩子/娃/育儿 | 第三章 #14 |
| 钱 | 钱不够/加薪/降薪/穷 | 第五章 #21 #22 #25 |
| 委屈 | 委屈/不甘/不被看见 | 第一章 #2 #4 |
| 迷茫 | 迷茫/失去方向/混乱 | 第二章 #6 #9 |
| 失控 | 崩溃/撑不住/太累 | 第五章 #23 #25 |
| 恐惧 | 怕/焦虑/害怕 | 第六章 #26 #27 |
| 成就 | 成就/晋升/搞定了 | 第四章 #18 #20 |
| 加班 | 加班/熬夜/出差 | 第五章 #23 #24 |
| 默认 | 未命中任何上述 | 全书 |

扩展方法：编辑 `.jarvis/ayuan_prompts.yaml`，加新 `trigger` 节点即可。

---

## 与 Jarvis 的边界（永远记住）

| 场景 | 走 Jarvis | 走阿原 |
|------|----------|-------|
| BTC 要不要加仓 | ✅ | ❌ |
| 副总任命心里憋屈 | ❌ | ✅ |
| QMS 选型评估 | ✅ | ❌ |
| 想离职 | ❌ | ✅ |
| 采购降本方案 | ✅ | ❌ |
| 最近老加班心累 | ❌ | ✅ |
| 跨界（投资选择触到了价值观）| 先 Jarvis 出方案，再阿原问"这事触及了宪法哪一条"| 

---

## 维护

- **宪法迭代**：每半年（生日 + 年中）重读一次，改动之处就是成长的证据。凝练页 `我的宪法.md#凝练：一页纸的我` 是阿原的"第一性原则"。
- **反问模板迭代**：新事件反复触发"默认"→ 说明需要新 trigger。加在 `ayuan_prompts.yaml`。
- **数据**：life_entries 与 decisions 同 DB（`.jarvis/data/jarvis.db`），后续可做交叉查询（决策是否对齐宪法锚点等）。

---

## 关联

- [[00_写作框架]] — 六章三十问
- [[我的宪法]] — 第一性原则
- [[个人投资专区 MOC]] — Jarvis 域
- [[26年工作区 MOC]] — Jarvis 域
