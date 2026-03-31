---
title: "混合整数线性规划 MILP"
type: 概念笔记
tags:
  - 采购优化
  - MILP
  - 运筹优化
  - 线性规划
aliases:
  - "MILP"
  - "Mixed Integer Linear Programming"
---

# 混合整数线性规划（MILP）

> [!abstract] 定义
> Mixed Integer Linear Programming：在==线性目标函数和线性约束==下，决策变量中**同时包含连续变量和整数（含0-1二元）变量**的优化问题。是采购优化项目的核心求解框架。

## 标准形式

$$
\min \quad c^T x + d^T y
$$
$$
\text{s.t.} \quad Ax + By \leq b, \quad x \geq 0, \quad y \in \mathbb{Z}^+
$$

- $x$：连续变量（如采购量、库存量）
- $y$：整数/二元变量（如是否下单 0/1）
- $c, d$：目标系数（单价、持有成本等）
- $A, B$：约束矩阵
- $b$：约束右端项（需求量、预算上限等）

## 为什么用 MILP 而不是普通 LP？

> [!question]- 为什么需要整数变量？
> 采购场景中存在**逻辑决策**：某个物料本期是否下单？这种"是/否"决策必须用 0-1 二元变量建模。例如：
> - $y_{m,t} = 1$ → 本期采购物料 $m$，则 $x_{m,t} \geq \text{MOQ}$
> - $y_{m,t} = 0$ → 本期不采购，则 $x_{m,t} = 0$
>
> 这就是经典的 **Big-M 约束**，LP 无法处理。

## 在项目中的应用

### 决策变量设计

| 变量 | 含义 | 类型 | 出现模型 |
|------|------|------|----------|
| `q[p,m,t]` | 产品 p 使用物料 m 在 t 期的生产量 | 连续 | MVP |
| `x[m,t]` | 物料 m 在 t 期的采购量 | 连续 | 全部 |
| `I[m,t]` | 物料 m 在 t 期末库存 | 连续 | 全部 |
| `y[m,t]` | 物料 m 在 t 期是否下单 | 二元(0/1) | 全部 |
| `prod[p,t]` | 成品 p 在 t 期的产量 | 连续 | 罐箱 |

### 求解器配置

```python
# common.py 中的求解器工厂
def create_solver(time_limit=600, threads=0, mip_gap=0.0001):
    solver = pulp.PULP_CBC_CMD(
        timeLimit=time_limit,   # 最大求解时间 10 分钟
        threads=threads,        # 0 = 自动检测 CPU 核数
        gapRel=mip_gap          # 0.01% MIP Gap 容忍度
    )
    return solver
```

> [!tip] MIP Gap
> `mip_gap=0.0001` 表示当目标值与理论最优的差距小于 0.01% 时即可停止。采购场景下这个精度完全足够——千万级总成本的 0.01% 仅 ¥1,278。

## 相关链接

- [[目标函数与约束条件]] — MILP 中目标和约束的具体设计
- [[Rayray课代表的数字化管理课(3) - 前言3 从数据科学角度看决策优化问题|理论：受约束的优化问题]] — 理论课中的约束优化概念
- [[采购优化 MOC|← 返回目录]]
