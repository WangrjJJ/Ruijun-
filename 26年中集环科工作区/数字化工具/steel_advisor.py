#!/usr/bin/env python3
"""
钢材战略备货决策系统 (Steel Strategic Procurement Advisor)
中集环科 ETO制造场景下的钢材备货时机与数量决策支持工具

核心逻辑：
  价格分位数 × 订单管道 × 持仓成本 → 备货策略 + 建议量 + 净效益测算

运行方式：
  python3 steel_advisor.py              # 按CONFIG分析并生成报告
  python3 steel_advisor.py --no-report  # 仅终端输出，不写文件

依赖：
  pip3 install akshare pandas numpy scipy
"""

import sys
import os
import json
import argparse
from datetime import datetime, timedelta
from typing import Optional

try:
    import akshare as ak
    import pandas as pd
    import numpy as np
    from scipy import stats
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip3 install akshare pandas numpy scipy")
    sys.exit(1)

# ============================================================
# 配置区 — 每次分析前更新以下参数（约5分钟维护）
# ============================================================

CONFIG = {
    # 订单管道（各钢种，单位：吨）
    # 说明：signed=已签合同对应耗钢量，negotiating=在谈项目耗钢量（×win_rate算期望）
    "pipeline": {
        "Q345R": {
            "signed": 200,          # 已签订单耗钢（吨）→ 换算公式：合同额/均价/钢材占比
            "negotiating": 120,     # 在谈订单耗钢（吨）
            "win_rate": 0.45,       # 历史中标率（ETO业务参考值）
        },
        "304_316L": {
            "signed": 40,
            "negotiating": 30,
            "win_rate": 0.50,
        },
    },

    # 当前实物库存（吨）
    "inventory": {
        "Q345R": 60,
        "304_316L": 15,
    },

    # 月均耗量—正常满产状态（吨/月）
    "monthly_consumption": {
        "Q345R": 100,
        "304_316L": 20,
    },

    # 安全库存下限（吨）— 低于此值必须采购
    "safety_stock": {
        "Q345R": 40,
        "304_316L": 10,
    },

    # 持仓综合成本（元/吨/月）= 资金成本 + 仓储费 + 管理费
    # 资金成本参考：钢材价格 × 5.5%年化 / 12 ≈ Q345R约 180元，304约550元
    "holding_cost_per_ton_month": {
        "Q345R": 180,
        "304_316L": 550,
    },

    # 可用于备货的流动资金上限（万元）— 与财务协商的授权额度
    "available_capital_wan": 500,

    # 最大战略备货周期（月）— 超过此周期资金占用风险过高
    "max_strategic_months": 3,

    # 价格历史窗口（月）— 用于分位数基准
    "history_months": 24,

    # 报告输出目录（Obsidian vault路径）
    "report_dir": "/Users/wangruijun/Documents/Ruijun的知识库/26年中集环科工作区/市场情报",
}

# 期货品种映射（上期所主力合约代码）
FUTURES_MAP = {
    "Q345R": "HC0",    # 热轧卷板 → Q345R压力容器钢代理指标（相关系数>0.9）
    "304_316L": "SS0", # 不锈钢304 → 316L价格参考（价差相对稳定）
}

STEEL_NAMES = {
    "Q345R": "Q345R压力容器钢（HC热轧卷代理）",
    "304_316L": "304/316L不锈钢（SS不锈钢期货）",
}

# ============================================================
# 数据获取
# ============================================================

def fetch_price_history(symbol: str, months: int) -> pd.DataFrame:
    """
    从上期所（via akshare）获取主力合约历史价格
    返回：DataFrame（日期、收盘价）
    """
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=months * 32)

    df = ak.futures_main_sina(
        symbol=symbol,
        start_date=start_dt.strftime("%Y%m%d"),
        end_date=end_dt.strftime("%Y%m%d"),
    )
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").reset_index(drop=True)
    return df


# ============================================================
# 价格分析
# ============================================================

def analyze_price(df: pd.DataFrame, history_months: int) -> dict:
    """
    计算当前价格在历史区间的位置
    返回：分位数、趋势、支撑/压力位等
    """
    # 全量窗口用于分位数基准
    cutoff = datetime.now() - timedelta(days=history_months * 31)
    window = df[df["日期"] >= cutoff]["收盘价"]

    current = float(df["收盘价"].iloc[-1])
    percentile = float(stats.percentileofscore(window, current))

    # 30日趋势
    recent = df.tail(22)  # ≈30个交易日
    price_30d_ago = float(recent["收盘价"].iloc[0])
    trend_pct = (current / price_30d_ago - 1) * 100

    # 60日高低点（短期支撑/压力）
    recent_60 = df.tail(44)
    support = float(recent_60["收盘价"].min())
    resistance = float(recent_60["收盘价"].max())

    return {
        "current": current,
        "percentile_24m": round(percentile, 1),
        "min_24m": float(window.min()),
        "max_24m": float(window.max()),
        "mean_24m": float(window.mean()),
        "trend_pct_30d": round(trend_pct, 2),
        "trend_dir": "↑" if trend_pct > 0 else "↓",
        "support_60d": round(support, 0),
        "resistance_60d": round(resistance, 0),
    }


# ============================================================
# 策略决策
# ============================================================

def get_stance(percentile: float) -> tuple:
    """
    根据价格分位数输出采购策略
    返回：(代码, 中文策略, 说明)
    """
    if percentile < 20:
        return ("AGGRESSIVE", "积极建库", "历史低价区，超前2-3个月备货，锁定成本优势")
    elif percentile < 40:
        return ("MODERATE", "适量建库", "偏低价区，超前1-2个月备货")
    elif percentile < 60:
        return ("JIT", "按需采购", "中性区间，维持JIT，覆盖已签订单即可")
    elif percentile < 78:
        return ("MINIMIZE", "压缩采购", "偏高价区，仅覆盖必要需求，不做战略库存")
    else:
        return ("WAIT", "等待回调", "历史高价区，压至安全库存下限，等待回调")


def calculate_recommendation(steel_type: str, price_info: dict, stance_code: str) -> dict:
    """
    计算建议采购量和财务效益
    核心公式：建议量 = 基础需求量 + 战略附加量（受资金约束）
    """
    p = CONFIG["pipeline"][steel_type]
    inv = CONFIG["inventory"][steel_type]
    monthly = CONFIG["monthly_consumption"][steel_type]
    safety = CONFIG["safety_stock"][steel_type]
    holding = CONFIG["holding_cost_per_ton_month"][steel_type]
    max_months = CONFIG["max_strategic_months"]
    budget = CONFIG["available_capital_wan"] * 10000
    current_price = price_info["current"]

    # 预期需求（概率加权）
    expected_demand = p["signed"] + p["negotiating"] * p["win_rate"]

    # 基础采购量 = 补足安全库存 + 预期需求 - 当前库存
    base_qty = max(0.0, expected_demand + safety - inv)

    # 战略附加量（基于策略）
    if stance_code == "AGGRESSIVE":
        strategic_months = min(2.5, max_months)
        strategic_add = monthly * strategic_months
    elif stance_code == "MODERATE":
        strategic_months = min(1.5, max_months)
        strategic_add = monthly * strategic_months
    elif stance_code == "JIT":
        strategic_add = 0.0
    elif stance_code == "MINIMIZE":
        # 收紧基础量：只覆盖签单+安全库存
        base_qty = max(0.0, p["signed"] + safety - inv)
        strategic_add = 0.0
    else:  # WAIT
        base_qty = max(0.0, safety - inv)
        strategic_add = 0.0

    total_qty = base_qty + strategic_add

    # 资金约束修正
    max_by_budget = budget / current_price if current_price > 0 else 9999
    if total_qty > max_by_budget:
        total_qty = max_by_budget

    # ── 财务效益测算 ──
    # 与历史均价对比（若当前低于均价，买入有节省）
    saving_per_ton = price_info["mean_24m"] - current_price
    gross_saving = saving_per_ton * strategic_add  # 只算战略附加量的节省

    # 持仓成本（战略附加量平均持仓2个月）
    holding_total = strategic_add * holding * 2.0
    net_benefit = gross_saving - holding_total

    # 采购总预算
    budget_used = total_qty * current_price

    return {
        "expected_demand_ton": round(expected_demand, 1),
        "current_inventory_ton": inv,
        "base_qty_ton": round(base_qty, 1),
        "strategic_add_ton": round(strategic_add, 1),
        "recommended_qty_ton": round(total_qty, 1),
        "budget_used_wan": round(budget_used / 10000, 1),
        "budget_ok": budget_used <= budget,
        "gross_saving_wan": round(gross_saving / 10000, 1),
        "holding_cost_wan": round(holding_total / 10000, 1),
        "net_benefit_wan": round(net_benefit / 10000, 1),
        "roi_pct": round(net_benefit / holding_total * 100, 1) if holding_total > 0 else float("inf"),
    }


# ============================================================
# 报告生成
# ============================================================

def build_price_bar(percentile: float, width: int = 30) -> str:
    """可视化价格分位数条"""
    filled = int(percentile / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {percentile:.0f}%"


def generate_report(results: dict) -> str:
    """生成Markdown格式报告"""
    now = datetime.now()
    week = now.isocalendar()[1]
    year = now.year

    lines = [
        "---",
        f'title: "钢材备货决策报告 {year}-W{week:02d}"',
        "type: 市场情报",
        f"date: {now.strftime('%Y-%m-%d')}",
        "tags:",
        "  - 钢材备货",
        "  - 采购决策",
        "  - 成本领先",
        "---",
        "",
        f"# 钢材战略备货决策报告 {year}-W{week:02d}",
        "",
        f"> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} | 数据来源：上期所（akshare）",
        "",
        "---",
        "",
        "## 价格分位数总览",
        "",
        "| 钢种 | 当前价格(元/吨) | 24月分位数 | 30日趋势 | 采购策略 |",
        "|------|----------------|------------|----------|----------|",
    ]

    for steel_type, res in results.items():
        pi = res["price_info"]
        stance = res["stance"]
        lines.append(
            f"| {STEEL_NAMES[steel_type]} | "
            f"¥{pi['current']:,.0f} | "
            f"{pi['percentile_24m']:.0f}% | "
            f"{pi['trend_dir']}{abs(pi['trend_pct_30d']):.1f}% | "
            f"**{stance[1]}** |"
        )

    lines += ["", "---", ""]

    for steel_type, res in results.items():
        pi = res["price_info"]
        stance = res["stance"]
        rec = res["recommendation"]

        lines += [
            f"## {STEEL_NAMES[steel_type]}",
            "",
            "### 价格位置分析",
            "",
            f"```",
            f"价格分位数：{build_price_bar(pi['percentile_24m'])}",
            f"",
            f"  当前价格：¥{pi['current']:,.0f}/吨",
            f"  24月最低：¥{pi['min_24m']:,.0f}/吨",
            f"  24月均值：¥{pi['mean_24m']:,.0f}/吨",
            f"  24月最高：¥{pi['max_24m']:,.0f}/吨",
            f"",
            f"  60日支撑：¥{pi['support_60d']:,.0f}  60日压力：¥{pi['resistance_60d']:,.0f}",
            f"  30日趋势：{pi['trend_dir']} {abs(pi['trend_pct_30d']):.1f}%",
            f"```",
            "",
            "### 决策结论",
            "",
            f"> **{stance[1]}** — {stance[2]}",
            "",
            "### 建议采购量测算",
            "",
            "| 维度 | 数值 |",
            "|------|------|",
            f"| 预期需求（签单+在谈×中标率） | {rec['expected_demand_ton']:.0f} 吨 |",
            f"| 当前库存 | {rec['current_inventory_ton']} 吨 |",
            f"| 基础采购量（补足安全库存+需求） | {rec['base_qty_ton']:.0f} 吨 |",
            f"| 战略附加量（价格窗口机会） | **{rec['strategic_add_ton']:.0f} 吨** |",
            f"| **建议总采购量** | **{rec['recommended_qty_ton']:.0f} 吨** |",
            f"| 预计采购金额 | ¥{rec['budget_used_wan']:.0f} 万元 {'✅' if rec['budget_ok'] else '⚠️ 超预算'} |",
            "",
            "### 财务效益测算",
            "",
            "| 项目 | 金额 | 说明 |",
            "|------|------|------|",
            f"| 相较均价节省（战略附加量） | ¥{rec['gross_saving_wan']:.1f} 万 | 当前价低于24月均价的成本差 |",
            f"| 持仓综合成本（持仓2月估算） | -¥{rec['holding_cost_wan']:.1f} 万 | 资金成本+仓储 |",
            f"| **净效益** | **{'¥' if rec['net_benefit_wan'] >= 0 else '-¥'}{abs(rec['net_benefit_wan']):.1f} 万** | {'正收益，建议执行' if rec['net_benefit_wan'] >= 0 else '负收益，不建议战略备货'} |",
            "",
            "---",
            "",
        ]

    # 操作清单
    lines += [
        "## 本周操作清单",
        "",
    ]
    for steel_type, res in results.items():
        stance_code = res["stance"][0]
        rec = res["recommendation"]
        name = STEEL_NAMES[steel_type].split("（")[0]
        if stance_code in ("AGGRESSIVE", "MODERATE"):
            lines.append(
                f"- [ ] **{name}**：建议采购 {rec['recommended_qty_ton']:.0f} 吨"
                f"（战略附加 {rec['strategic_add_ton']:.0f} 吨），"
                f"预算 ¥{rec['budget_used_wan']:.0f} 万，净效益 ¥{rec['net_benefit_wan']:.1f} 万"
            )
        elif stance_code == "JIT":
            lines.append(
                f"- [ ] **{name}**：按需采购 {rec['base_qty_ton']:.0f} 吨，覆盖已签订单，不做战略库存"
            )
        else:
            lines.append(
                f"- [ ] **{name}**：{res['stance'][1]}，最低采购 {rec['base_qty_ton']:.0f} 吨（安全库存兜底）"
            )

    lines += [
        "",
        "---",
        "",
        "## 模型说明",
        "",
        "**采购策略映射（价格24月分位数）：**",
        "- <20%：积极建库 — 超前2.5个月备货",
        "- 20-40%：适量建库 — 超前1.5个月备货",
        "- 40-60%：按需采购 — JIT，覆盖签单",
        "- 60-78%：压缩采购 — 仅签单+安全库存",
        "- >78%：等待回调 — 压至安全库存下限",
        "",
        "**净效益计算：**",
        "> 净效益 = (24月均价 - 当前价) × 战略附加量 - 持仓成本",
        "> 仅当净效益 > 0 时，战略备货在财务上可行",
        "",
        "**数据来源：** 上期所主力合约收盘价（HC=热轧卷板, SS=不锈钢304）",
        "**注意：** 期货价格为代理指标，Q345R现货价通常高于HC约3-5%，316L现货高于SS约8-12%",
        "",
        "← [[减支—成本领先]] | [[培元—创新与数字化]] | [[26年工作区 MOC]]",
    ]

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def main(write_report: bool = True):
    print("=" * 60)
    print("  钢材战略备货决策系统  |  中集环科")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    results = {}

    for steel_type, symbol in FUTURES_MAP.items():
        name = STEEL_NAMES[steel_type]
        print(f"\n[获取数据] {name} ({symbol})...")

        try:
            df = fetch_price_history(symbol, CONFIG["history_months"])
            price_info = analyze_price(df, CONFIG["history_months"])
            stance = get_stance(price_info["percentile_24m"])
            rec = calculate_recommendation(steel_type, price_info, stance[0])

            results[steel_type] = {
                "price_info": price_info,
                "stance": stance,
                "recommendation": rec,
            }

            print(f"  当前价格：¥{price_info['current']:,.0f}/吨")
            print(f"  24月分位：{price_info['percentile_24m']:.0f}%  "
                  f"30日趋势：{price_info['trend_dir']}{abs(price_info['trend_pct_30d']):.1f}%")
            print(f"  → 策略：【{stance[1]}】  建议采购：{rec['recommended_qty_ton']:.0f}吨  "
                  f"净效益：¥{rec['net_benefit_wan']:.1f}万")

        except Exception as e:
            print(f"  [ERROR] 获取 {symbol} 失败: {e}")
            continue

    if not results:
        print("\n[ERROR] 所有品种获取失败，请检查网络或akshare版本")
        return

    if write_report:
        report_content = generate_report(results)
        now = datetime.now()
        week = now.isocalendar()[1]
        filename = f"钢材备货决策_{now.year}-W{week:02d}.md"
        report_path = os.path.join(CONFIG["report_dir"], filename)

        os.makedirs(CONFIG["report_dir"], exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        print(f"\n[报告] 已保存至: {report_path}")
    else:
        print("\n[--no-report 模式，跳过文件写入]")

    print("\n完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="钢材战略备货决策系统")
    parser.add_argument("--no-report", action="store_true", help="不生成报告文件")
    args = parser.parse_args()
    main(write_report=not args.no_report)
