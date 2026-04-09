---
name: 采购优化MILP项目
description: 三模型采购优化项目(MVP/钢材/罐箱)的完整架构、文件清单和当前状态
type: project
---

## 项目概览
不锈钢板材/化工罐箱/MVP通用 三套采购决策优化模型，基于 MILP (PuLP+CBC)，Excel输入输出。

## 文件结构 (C:\Users\01455310\)

### 公共模块
- `common.py` — 三模型共用：颜色常量、样式函数、ResultWriter类、create_solver()多核求解器

### 模型1: MVP通用采购
- `generate_template.py` → `MVP_Optimization_Template.xlsx`
- `solve.py` — 2产品×2物料×12期，含物料替代+废料成本

### 模型2: 不锈钢板材 (最完善)
- `generate_steel_template.py` → `Steel_Procurement.xlsx`
- `solve_steel.py` — 12产品(6BU)×15板材×12期，裁剪损耗+聚合采购+敏感性分析
- `generate_report_ppt.py` → `Steel_Procurement_Report.pptx` (10页汇报PPT)

### 模型3: 化工罐箱
- `generate_tank_template.py` → `Tank_Procurement.xlsx`
- `solve_tank.py` — 4成品×15物料(6类)×52周，BOM消耗+季节性需求+安全库存

## 钢材模型关键特性
- **聚合采购**: 6个事业部12产品形成6个聚合组(A~F)，跨BU同规格需求聚合突破非标MOQ
- **敏感性分析**: 非标价格/MOQ/需求量三维，19个场景自动求解
- **最新结果**: 总成本¥12,778,965，综合损耗率6.79%，非标占比55.4%
- **PPT汇报**: 10页16:9宽屏，含封面/背景/模型/聚合/兼容/结果/计划/敏感性/结论

## 技术栈
- Python 3 + PuLP(CBC) + openpyxl + python-pptx
- 性能优化：预建索引字典(compat_by_prod等)、多核solver、MIP gap容差

**Why:** 用户是做采购优化决策支持的，需要完整的建模→求解→汇报工作流
**How to apply:** 后续可在此基础上扩展新场景/新约束/新报表
