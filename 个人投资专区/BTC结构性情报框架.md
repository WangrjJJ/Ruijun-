---
title: BTC结构性情报框架
type: 投资策略
date: 2026-04-13
status: 生效中
tags:
  - BTC
  - 结构性分析
  - 情报框架
  - 数据源
---

# BTC结构性情报框架

> [!abstract] 概述
> 价格走势之外的**结构性供需力量**监控框架。用于日报/周报的策略制订，辅助双币理财和仓位管理决策。

## 核心逻辑

```
价格 = f(结构性买盘, 结构性卖盘, 情绪, 流动性)
```

日报/周报只看价格和恐贪是不够的。真正驱动中长期走势的是**谁在买、谁在卖、供应在收缩还是扩张**。

## 六大结构性情报维度

### 1. ETF资金流（日频）

> [!tip] 为什么重要
> ETF是当前最大的边际买盘来源。日净流入/流出直接反映机构资金态度。

| 指标 | 含义 | 数据源 |
|------|------|--------|
| 日净流入/流出 ($M) | 当日ETF总买卖差 | [Farside Investors](https://farside.co.uk/btc/) |
| IBIT/FBTC/GBTC分项 | BlackRock/Fidelity/Grayscale各自流向 | [SoSoValue](https://sosovalue.com/assets/etf/us-btc-spot) |
| 7天/30天累计 | 趋势方向 | [CoinGlass ETF](https://www.coinglass.com/etf/bitcoin) |
| ETF累计持仓 (BTC) | 总锁定量 | [Bitbo ETF Tracker](https://bitbo.io/treasuries/us-etfs/) |

**信号规则**:
- ETF 7天累计 >$500M + 恐贪 <25 → 机构逆势吸筹 (中期看多)
- ETF 日净流出 >$200M 连续3天 → ETF赎回潮 (短期卖压)

**更新方式**: 手动更新 `.etf_flows.json`，每个交易日收盘后30秒

### 2. Strategy/MSTR持仓（周频）

> [!tip] 为什么重要
> Strategy是全球最大的BTC结构性买家，2026年YTD购入~90,000 BTC (其他所有上市公司合计仅~4,000)。其买入节奏直接影响市场支撑力。

| 指标 | 含义 | 数据源 |
|------|------|--------|
| 总持仓 (BTC) | 当前766,970 BTC (~3.6%供应) | [strategy.com/purchases](https://www.strategy.com/purchases) |
| 均价 | $75,644 — 高于/低于现价决定NAV溢/折价 | [BitcoinTreasuries](https://bitcointreasuries.net) |
| 最近买入 | 买入量+均价 → 判断飞轮是否活跃 | 8-K Filing (通常周一) |
| ATM发行状态 | $21B MSTR + $21B STRC 额度使用情况 | SEC Filings |

**信号规则**:
- 本周新增 >5,000 BTC → 飞轮活跃，短期价格支撑增强
- BTC现价 < MSTR均价 → NAV折价，ATM飞轮承压 (边际买盘减弱风险)

**更新方式**: 手动更新 `.mstr_holdings.json`，每周一查看8-K

### 3. 矿工经济（自动/日频）

> [!tip] 为什么重要
> 矿工是唯一的结构性卖家（需卖BTC覆盖电费）。算力、难度、费率决定矿工利润，利润承压时抛售增加。

| 指标 | 含义 | 数据源 |
|------|------|--------|
| 算力 (EH/s) | 网络安全+矿工投入 | [mempool.space](https://mempool.space) (自动) |
| 难度调整预期 (%) | 正=竞争加剧 负=矿工退出 | mempool.space (自动) |
| 链上费率 (sat/vB) | 链上活跃度代理 | mempool.space (自动) |
| Top矿池份额 | 算力集中度 | mempool.space (自动) |

**信号规则**:
- 算力新高 + 费率 <5 sat/vB → 矿工利润承压
- 难度调整 >+5% → 高成本矿工面临出局压力
- 难度调整 <-5% → 算力出走，生产成本下降，卖压缓解

### 4. 未平仓合约OI（自动/日频）

> [!tip] 为什么重要
> OI变化+价格方向+资金费率三维组合，可推断多空建仓/平仓行为。

| 组合 | 含义 |
|------|------|
| OI↑ + 价格↑ + FR>0 | 多头建仓 (趋势延续) |
| OI↑ + 价格↓ + FR<0 | 空头建仓 (潜在挤压机会) |
| OI↓ + 价格↓ | 多头平仓 (去杠杆) |
| OI↓ + 价格↑ | 空头平仓/挤压进行中 |

**数据源**: Binance futures API (自动采集)

### 5. 链上供应（自动/日频）

| 指标 | 含义 | 数据源 |
|------|------|--------|
| 已挖出BTC总量 | 供应上限参照 | [blockchain.info](https://blockchain.info) (自动) |
| 24h交易量 | 链上活跃度 | blockchain.info (自动) |

**进阶指标** (需Glassnode/CryptoQuant, 后续扩展):
- 交易所存量 (当前~2.71M BTC, 7年低点)
- LTH/STH供应比 (当前LTH持有75%供应)
- MVRV比率、供应盈利百分比

### 6. 宏观/立法信号（手动跟踪）

| 事件 | 状态 | 影响 |
|------|------|------|
| 美国战略BTC储备 | 已签行政令(2025.3)，未新购入 | 长期利多 |
| BITCOIN Act (S.954) | 国会审议中，提议购100万BTC | 若通过为超级利多 |
| 新罕布什尔州储备法 | 已通过，已购$100M ETF | 州级先例 |
| ECB反对纳入BTC | 明确表态不会持有 | 中性 |

## 数据采集架构

```
structural_intel.py
├── fetch_miner_stats()     ← mempool.space (自动, 日频)
├── fetch_onchain_supply()  ← blockchain.info (自动, 日频)
├── fetch_exchange_proxy()  ← Binance OI (自动, 日频)
├── fetch_etf_flows()       ← .etf_flows.json (手动, 日频)
├── fetch_mstr_holdings()   ← .mstr_holdings.json (手动, 周频)
└── fetch_all()             → 并行采集 → 日报⑤板块 + 周报
```

## 手动数据更新指南

### ETF资金流 (每个交易日)

1. 打开 [Farside Investors](https://farside.co.uk/btc/)
2. 记录当日 Total、IBIT、FBTC、GBTC 列
3. 更新 `个人投资专区/.etf_flows.json`:

```json
{
  "date": "2026-04-11",
  "daily_net_m": 240.5,
  "ibit_net": 180.2,
  "fbtc_net": 45.3,
  "gbtc_net": -12.0,
  "cumulative_btc": 721090,
  "7d_net_m": 850.0
}
```

### MSTR持仓 (每周一)

1. 打开 [strategy.com/purchases](https://www.strategy.com/purchases)
2. 查看最新8-K
3. 更新 `个人投资专区/.mstr_holdings.json`:

```json
{
  "updated": "2026-04-07",
  "total_btc": 766970,
  "avg_cost": 75644,
  "total_cost_usd": 58020000000,
  "pct_supply": 3.6,
  "last_purchase_btc": 4871,
  "last_purchase_date": "2026-04-05",
  "last_purchase_price": 67718
}
```

## 交叉信号总表

| ID | 条件 | 判断 |
|----|------|------|
| S1 | ETF 7天净流入 >$500M + 恐贪 <25 | 机构逆势吸筹 → 中期偏多 |
| S2 | ETF 日净流出 >$200M | 短期卖压信号 |
| S3 | MSTR 本周买入 >5,000 BTC | 最大买盘活跃 → 价格支撑 |
| S4 | 算力高位 + 费率 <5 sat/vB | 矿工利润承压 |
| S5 | OI↑>5% + 价格↓ + FR<0 | 空头挤压机会 |
| S6 | 难度调整 >+5% 或 <-5% | 矿工经济拐点 |
| S7 | BTC现价 < MSTR均价 | MSTR飞轮承压 |

## 当前结构性画像 (2026年4月)

> [!important] 多空力量对比
> **多方结构性力量**: ETF持续净流入($18.7B Q1)、交易所存量7年低点(5.88%)、鲸鱼30天吸筹270K BTC、LTH持有75%供应、恐贪连续极端恐惧(逆向指标)
>
> **空方结构性力量**: MSTR浮亏(均价$75.6K>现价$72K)、NAV折价压制ATM飞轮、Q1三连阴(2018年来首次)、矿工hashprice处2019低点
>
> **研判**: 典型蓄积阶段 — 强手吸收弱手筹码、情绪极度悲观但结构性供需收紧。关键支撑: $60-65K (实现价格+矿工盈亏平衡)。

## 相关链接

- [[投资策略总览]] — 三池策略+风控矩阵
- [[策略看板]] — 实时数据看板
- [[个人投资专区 MOC]] — 投资区入口

---
*框架建立于 2026-04-13，由 JARVIS 结构性情报模块支撑*
