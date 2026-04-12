#!/usr/bin/env python3
"""
个人日报系统 v2 (Personal Daily Brief)
资产信号 × 公司雷达 × OPC/AI动态 → 终端 + 邮件推送

v2 优化：
  - P0: 每日数据持久化 + 趋势记忆句（连续N天...）
  - P0: HN查询词优化 + 36kr/GitHub Trending 新源
  - P1: BTC资金费率 + Dominance（领先指标）
  - P1: 双币行权概率自动估算（波动率模型）
  - P2: 跨信号关联（规则引擎 → 结论句）
  - P2: 胜狮 → BCTI化学品运价指数（行业真实需求信号）

运行: python3 daily_brief.py
凭证: ~/.daily_brief_secrets.json（chmod 600）
历史: 同目录 .daily_brief_history.json（自动维护90天）

依赖: pip3 install requests akshare pandas beautifulsoup4
"""

import sys
import io
import json
import math
import time
import smtplib
import contextlib
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.header import Header

try:
    import akshare as ak
except ImportError:
    print("[ERROR] 请运行: pip3 install akshare pandas requests beautifulsoup4")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ============================================================
# 配置区 — 双币/行动项手动维护
# ============================================================

DUAL_CURRENCY = [
    {
        "type":   "Buy Low",
        "strike": 69500,
        "amount": "$140,000 USDT",
        "expiry": "2026-04-22",
    },
    {
        "type":   "Sell High",
        "strike": 74000,
        "amount": "2.26 BTC",
        "expiry": "2026-04-22",
    },
]

ACTION_ITEMS = [
    "月度提现 $3,630 ≈ ¥25,000 待执行（Q1已过0提现）",
    "D池定投：工资日 ¥5,000-8,000 → USDT",
]

DAILY_QUESTIONS = [
    "如果明天有人付 ¥5,000 请你解决一个问题，会是什么问题？",
    "你的哪项能力，在 AI 加持下可以服务 10 个以上付费客户？",
    "本周接触的信息中，哪个让你感到「这个我能做更好」？",
    "OPC 最大的障碍：技术 / 销售 / 信心 / 时间，哪个排第一？",
    "如果做一个面向制造业的 AI 工具，最容易验证的第一个功能是什么？",
    "BTC 策略当前能支撑多少个月基本开销？这个数字让你感觉如何？",
    "下周可以做哪一个最小实验来测试 OPC 方向的可行性？",
]

# HN 查询词（v2 优化：更宽泛、更高命中率）
HN_QUERIES = {
    "AI工具·颠覆咨询/运营": [
        "AI agent workflow",
        "AI replacing consultants",
        "AI operations automation tool",
    ],
    "OPC·独立变现": [
        "one person SaaS",
        "solo founder B2B revenue",
        "Show HN AI tool",
    ],
}

# 36kr AI/创业关键词过滤
KR36_KEYWORDS = ["AI", "人工智能", "大模型", "Agent", "SaaS", "独立开发",
                 "创业", "一人公司", "咨询", "自动化", "出海"]

# ============================================================
# 路径
# ============================================================

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, ".daily_brief_history.json")
SECRETS_FILE = os.path.expanduser("~/.daily_brief_secrets.json")

# ============================================================
# 历史数据持久化 + 趋势检测
# ============================================================

def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(history: dict):
    # 保留最近90天
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    trimmed = {k: v for k, v in history.items() if k >= cutoff}
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def save_today(snapshot: dict):
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    history[today] = snapshot
    save_history(history)


def streak(history: dict, key: str, condition) -> int:
    """从昨天往回数，连续满足条件的天数"""
    today = datetime.now().strftime("%Y-%m-%d")
    dates = sorted([d for d in history if d < today], reverse=True)
    n = 0
    for d in dates:
        val = history[d].get(key)
        if val is not None and condition(val):
            n += 1
        else:
            break
    return n


def trend_vs_yesterday(history: dict, key: str, today_val) -> str:
    """对比昨天的值，返回变化描述"""
    today = datetime.now().strftime("%Y-%m-%d")
    dates = sorted([d for d in history if d < today], reverse=True)
    if not dates:
        return ""
    yest_val = history[dates[0]].get(key)
    if yest_val is None or today_val is None:
        return ""
    diff = today_val - yest_val
    if abs(diff) < 0.01:
        return ""
    arrow = "↑" if diff > 0 else "↓"
    return f"（较昨日 {arrow}{abs(diff):.1f}）"


# ============================================================
# 正态分布近似（避免scipy依赖）
# ============================================================

def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def trigger_probability(current: float, strike: float, days: int,
                        annual_vol_pct: float, is_buy_low: bool) -> float:
    """
    对数正态模型估算行权概率
    Buy Low: P(price < strike)
    Sell High: P(price > strike)
    """
    if days <= 0 or annual_vol_pct <= 0 or current <= 0:
        return 0.0
    sigma = annual_vol_pct / 100
    T = days / 365
    d = math.log(strike / current) / (sigma * math.sqrt(T))
    prob = norm_cdf(d) if is_buy_low else (1 - norm_cdf(d))
    return round(prob * 100, 1)


# ============================================================
# 数据获取
# ============================================================

def fetch_crypto() -> dict:
    """BTC/ETH 价格 + 恐贪 + 资金费率 + dominance + 波动率"""
    result = {}

    # 价格
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd",
                    "include_24hr_change": "true"},
            timeout=12,
        )
        data = r.json()
        result["btc"] = {"price": data["bitcoin"]["usd"],
                         "change_24h": data["bitcoin"]["usd_24h_change"]}
        result["eth"] = {"price": data["ethereum"]["usd"],
                         "change_24h": data["ethereum"]["usd_24h_change"]}
        result["eth_btc"] = result["eth"]["price"] / result["btc"]["price"]
    except Exception as e:
        result["crypto_err"] = str(e)

    # 恐贪指数
    try:
        r2 = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        fng = r2.json()["data"][0]
        result["fear_greed"] = {"value": int(fng["value"]),
                                "label": fng["value_classification"]}
    except Exception:
        result["fear_greed"] = None

    # Binance 资金费率
    try:
        r3 = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
                          params={"symbol": "BTCUSDT", "limit": "1"}, timeout=10)
        fr = r3.json()[0]
        result["funding_rate"] = float(fr["fundingRate"])
    except Exception:
        result["funding_rate"] = None

    # BTC Dominance（CoinGecko global）
    try:
        r4 = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        gd = r4.json()["data"]
        result["btc_dominance"] = round(gd["market_cap_percentage"]["btc"], 1)
    except Exception:
        result["btc_dominance"] = None

    # 7天年化波动率（用于双币概率估算）
    try:
        r5 = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": "14", "interval": "daily"},
            timeout=12,
        )
        prices = [p[1] for p in r5.json()["prices"]]
        returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
        vol_7d = (sum(r ** 2 for r in returns[-7:]) / 7) ** 0.5 * (365 ** 0.5) * 100
        result["vol_7d_ann"] = round(vol_7d, 1)
    except Exception:
        result["vol_7d_ann"] = None

    return result


def fetch_company_radar() -> dict:
    """中集环科(301559) + BCTI化学品运价 + 钢材上游"""
    result = {}

    # 中集环科 A 股
    try:
        df = ak.stock_zh_a_daily(symbol="sz301559", adjust="")
        if not df.empty:
            df = df.sort_values("date")
            row = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None
            close = float(row["close"])
            chg = ((close / float(prev["close"])) - 1) * 100 if prev is not None else None
            result["zjhk"] = {"price": close,
                              "change_pct": round(chg, 2) if chg is not None else None,
                              "date": str(row["date"])[:10]}
        else:
            result["zjhk"] = {"err": "empty"}
    except Exception as e:
        result["zjhk"] = {"err": str(e)}

    # BCTI 化学品油轮运价指数（替代胜狮，真正反映化学品运输需求）
    try:
        df_bcti = ak.macro_shipping_bcti()
        if not df_bcti.empty:
            df_bcti["日期"] = pd.to_datetime(df_bcti["日期"])
            df_bcti = df_bcti.sort_values("日期")
            latest = df_bcti.iloc[-1]
            result["bcti"] = {
                "value":     float(latest["最新值"]),
                "change_pct": float(latest["涨跌幅"]) if pd.notna(latest["涨跌幅"]) else None,
                "trend_3m":  float(latest["近3月涨跌幅"]) if pd.notna(latest["近3月涨跌幅"]) else None,
                "date":      str(latest["日期"])[:10],
            }
    except Exception as e:
        result["bcti"] = {"err": str(e)}

    # 钢材上游信号
    try:
        up_trends, steel_rows = [], []
        for sym, name in [("I0", "铁矿石"), ("J0", "焦炭"), ("HC0", "热轧卷")]:
            df_f = ak.futures_main_sina(
                symbol=sym,
                start_date=(datetime.now() - timedelta(days=45)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
            )
            if df_f.empty:
                continue
            df_f = df_f.sort_values("日期")
            cur = float(df_f["收盘价"].iloc[-1])
            p30 = float(df_f["收盘价"].iloc[max(0, len(df_f) - 22)])
            t30 = round((cur / p30 - 1) * 100, 1)
            steel_rows.append(f"{name} {t30:+.1f}%")
            if sym in ("I0", "J0"):
                up_trends.append(t30)

        avg = sum(up_trends) / len(up_trends) if up_trends else 0
        if avg > 3:
            sig = f"⚠️  上游成本压力上行（均+{avg:.1f}%）"
        elif avg < -3:
            sig = f"✅  上游成本回落（均{avg:.1f}%）"
        else:
            sig = f"🔵  成本端平稳（均{avg:.1f}%）"
        result["steel"] = {"signal": sig, "detail": "  ".join(steel_rows),
                           "avg_trend": round(avg, 1)}
    except Exception as e:
        result["steel"] = {"signal": f"获取失败: {e}", "detail": "", "avg_trend": 0}

    return result


def fetch_hn_intel() -> dict:
    """HN Algolia（v2: 更宽泛查询词，30天窗口）"""
    ts_cutoff = int((datetime.now() - timedelta(days=30)).timestamp())
    output = {}

    for category, queries in HN_QUERIES.items():
        seen, items = set(), []
        for q in queries:
            try:
                r = requests.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={"query": q, "tags": "story",
                            "numericFilters": f"created_at_i>{ts_cutoff}",
                            "hitsPerPage": 5},
                    timeout=10,
                )
                for h in r.json().get("hits", []):
                    title = h.get("title", "").strip()
                    if not title or title in seen or h.get("points", 0) < 2:
                        continue
                    seen.add(title)
                    hn_url = f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"
                    # v3: 提取摘要和评论数
                    raw_text = h.get("story_text") or ""
                    if raw_text and HAS_BS4:
                        raw_text = BeautifulSoup(raw_text, "html.parser").get_text(" ", strip=True)
                    summary = raw_text[:120].strip() if raw_text else ""
                    items.append({"title": title, "points": h.get("points", 0),
                                  "comments": h.get("num_comments", 0),
                                  "summary": summary,
                                  "url": h.get("url") or hn_url})
                time.sleep(0.3)
            except Exception:
                pass
        items.sort(key=lambda x: x["points"], reverse=True)
        output[category] = items[:4]

    return output


def fetch_36kr() -> list:
    """36kr RSS（BeautifulSoup XML解析，关键词过滤）"""
    if not HAS_BS4:
        return []
    items = []
    try:
        r = requests.get("https://36kr.com/feed",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "xml")
        for it in soup.find_all("item")[:30]:
            title = it.find("title")
            link = it.find("link")
            if not title:
                continue
            text = title.text.strip()
            if any(kw in text for kw in KR36_KEYWORDS):
                # v3: 从description提取摘要
                desc_tag = it.find("description")
                summary = ""
                if desc_tag and desc_tag.text.strip():
                    desc_soup = BeautifulSoup(desc_tag.text, "html.parser")
                    first_p = desc_soup.find("p")
                    summary = (first_p.get_text(strip=True) if first_p
                               else desc_soup.get_text(strip=True))[:120]
                items.append({
                    "title": text,
                    "summary": summary,
                    "url": link.text.strip() if link else "",
                })
    except Exception:
        pass
    return items[:4]


def fetch_github_trending() -> list:
    """GitHub Trending 日榜 — AI相关仓库"""
    if not HAS_BS4:
        return []
    items = []
    try:
        r = requests.get("https://github.com/trending?since=daily",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for art in soup.select("article.Box-row")[:15]:
            a = art.select_one("h2 a")
            if not a:
                continue
            name = a.text.strip().replace("\n", "/").replace(" ", "")
            desc_p = art.select_one("p")
            desc = desc_p.text.strip() if desc_p else ""
            combined = f"{name} {desc}".lower()
            if any(kw in combined for kw in ["ai", "agent", "llm", "gpt", "claude",
                                              "automation", "workflow", "saas"]):
                stars_span = art.select_one("span.d-inline-block.float-sm-right")
                stars = stars_span.text.strip() if stars_span else ""
                # v3: 保留完整描述 + 提取编程语言
                lang_span = art.select_one("span[itemprop='programmingLanguage']")
                lang = lang_span.text.strip() if lang_span else ""
                items.append({"name": name, "desc": desc, "stars": stars, "lang": lang})
    except Exception:
        pass
    return items[:3]


# ============================================================
# 跨信号关联引擎
# ============================================================

def generate_insights(crypto: dict, company: dict, history: dict) -> list:
    """根据多信号组合，生成结论性判断句"""
    insights = []

    fg = crypto.get("fear_greed", {})
    fg_val = fg.get("value", 50) if fg else 50
    fr = crypto.get("funding_rate")
    vol = crypto.get("vol_7d_ann")
    steel_avg = company.get("steel", {}).get("avg_trend", 0)
    zjhk_chg = company.get("zjhk", {}).get("change_pct")
    bcti = company.get("bcti", {})
    bcti_3m = bcti.get("trend_3m") if "err" not in bcti else None

    # 恐贪 + 资金费率 → 市场情绪
    if fg_val < 20 and fr is not None and fr < 0:
        insights.append(
            "⚡ 恐贪极低 + 资金费率为负 → 空头拥挤，恐慌可能过度，"
            "Buy Low 被行权概率低于模型估算"
        )
    elif fg_val < 20 and fr is not None and fr > 0.0005:
        insights.append(
            "⚡ 恐贪极低但资金费率转正 → 多头在抄底，价格可能企稳"
        )
    elif fg_val > 75 and fr is not None and fr > 0.0005:
        insights.append(
            "⚡ 恐贪高位 + 资金费率偏高 → 多头过热，Sell High 被行权概率上升"
        )

    # 钢材成本 + 公司股价
    if steel_avg < -3 and zjhk_chg is not None and zjhk_chg > 1:
        insights.append(
            "📊 钢材成本回落 + 环科股价上涨 → 成本利好可能已开始被市场定价"
        )
    elif steel_avg > 3 and zjhk_chg is not None and zjhk_chg < -1:
        insights.append(
            "📊 钢材成本上行 + 环科股价下跌 → 成本压力正在传导，关注备货时机"
        )

    # BCTI化学品运价 → 客户需求
    if bcti_3m is not None:
        if bcti_3m > 30:
            insights.append(
                f"🚢 化学品运价指数（BCTI）近3月暴涨 +{bcti_3m:.0f}% → "
                "化工物流需求旺盛，罐箱订单前景积极"
            )
        elif bcti_3m < -20:
            insights.append(
                f"🚢 化学品运价指数（BCTI）近3月跌 {bcti_3m:.0f}% → "
                "化工运输需求走弱，罐箱订单可能承压"
            )

    # 趋势记忆：恐贪连续极度恐惧
    fg_streak = streak(history, "fear_greed", lambda v: v < 20)
    if fg_streak >= 3:
        insights.append(
            f"📅 恐贪指数已连续 {fg_streak + 1} 天处于极度恐惧（含今日），"
            "历史上此模式平均持续 7-14 天后反转"
        )

    # 趋势记忆：资金费率连续为负
    fr_streak = streak(history, "funding_rate", lambda v: v < 0)
    if fr_streak >= 3:
        insights.append(
            f"📅 资金费率已连续 {fr_streak + 1} 天为负 → 空头持续支付费用，"
            "市场做空情绪浓厚但成本在累积"
        )

    return insights


# ============================================================
# 周度Obsidian归档
# ============================================================

WEEKLY_DIR = os.path.join(SCRIPT_DIR, "OPC周报")

# 洞察关键词库
INSIGHT_KEYWORDS = {
    "agent": "AI Agent",
    "workflow": "工作流自动化",
    "saas": "SaaS",
    "consulting": "咨询",
    "automation": "自动化",
    "coding": "AI编程",
    "llm": "大模型",
    "rag": "RAG",
    "mcp": "MCP协议",
    "one person": "一人公司",
    "solo": "独立开发",
}


def generate_weekly_digest():
    """从近7天历史中生成OPC情报周报，输出为Obsidian markdown"""
    history = load_history()
    now = datetime.now()
    iso_cal = now.isocalendar()
    week_label = f"{iso_cal[0]}-W{iso_cal[1]:02d}"

    # 取近7天数据
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_dates = sorted([d for d in history if d >= cutoff])
    if not week_dates:
        print(f"[周报] 近7天无历史数据，跳过")
        return None

    # 收集所有OPC条目
    all_items = []
    for d in week_dates:
        for item in history[d].get("opc_items", []):
            item["_date"] = d
            all_items.append(item)

    if not all_items:
        print(f"[周报] 近7天无OPC条目，跳过")
        return None

    total_scanned = len(all_items)

    # 按source分组，每组取top项（HN按points降序，其余按出现顺序）
    by_source = {}
    for it in all_items:
        by_source.setdefault(it["source"], []).append(it)

    selected = []
    for src, items in by_source.items():
        if src == "hn":
            items.sort(key=lambda x: x.get("points", 0), reverse=True)
        selected.extend(items[:4])
    selected = selected[:12]

    # 生成洞察
    insights = _generate_weekly_insights(all_items, by_source)

    # 构建markdown
    date_from = week_dates[0]
    date_to = week_dates[-1]
    prev_week = f"{iso_cal[0]}-W{iso_cal[1]-1:02d}" if iso_cal[1] > 1 else f"{iso_cal[0]-1}-W52"

    lines = [
        "---",
        f'title: "OPC情报周报 {week_label}"',
        "type: OPC周报",
        f"date: {now.strftime('%Y-%m-%d')}",
        "tags: [OPC, AI工具, 独立变现]",
        "---",
        "",
        f"# OPC情报周报 {week_label}",
        "",
        f"> {date_from} — {date_to} | 本周扫描 {total_scanned} 条 | 精选 {len(selected)} 条",
        "",
        "## 本周重点",
    ]

    # 按source分段输出
    source_labels = {
        "hn": "Hacker News",
        "36kr": "36kr · AI/创业",
        "github": "GitHub Trending · AI",
    }
    for src in ["hn", "36kr", "github"]:
        src_items = [it for it in selected if it["source"] == src]
        if not src_items:
            continue
        lines.append(f"\n### {source_labels.get(src, src)}")
        for it in src_items:
            if src == "hn":
                cmt = f" | {it.get('comments', 0)}评" if it.get("comments") else ""
                lines.append(f"- **{it['title']}** [{it.get('points', 0)}↑{cmt}]")
                if it.get("summary"):
                    lines.append(f"  {it['summary'][:120]}")
                if it.get("url"):
                    lines.append(f"  [链接]({it['url']})")
            elif src == "36kr":
                lines.append(f"- **{it['title']}**")
                if it.get("summary"):
                    lines.append(f"  {it['summary'][:120]}")
                if it.get("url"):
                    lines.append(f"  [链接]({it['url']})")
            elif src == "github":
                lang_str = f" | {it['lang']}" if it.get("lang") else ""
                stars_str = f" {it['stars']}" if it.get("stars") else ""
                lines.append(f"- **{it['title']}**{stars_str}{lang_str}")
                if it.get("summary"):
                    lines.append(f"  {it['summary'][:120]}")

    # 洞察部分
    if insights:
        lines.append("\n## 本周洞察")
        lines.append("\n> 基于本周信号的模式观察（规则引擎自动生成）")
        lines.append("")
        for ins in insights:
            lines.append(f"- {ins}")

    lines.append("")
    lines.append(f"---")
    lines.append(f"← [[{prev_week}]] | [[个人投资专区 MOC]]")
    lines.append("")

    # 写入文件
    os.makedirs(WEEKLY_DIR, exist_ok=True)
    filepath = os.path.join(WEEKLY_DIR, f"{week_label}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[周报] 已生成 → {filepath}")
    return filepath


def _generate_weekly_insights(all_items: list, by_source: dict) -> list:
    """简单规则引擎：关键词频率 + source分布 + 重复主题"""
    insights = []

    # 关键词频率统计
    kw_counts = {}
    for it in all_items:
        text = f"{it.get('title', '')} {it.get('summary', '')}".lower()
        for kw, label in INSIGHT_KEYWORDS.items():
            if kw in text:
                kw_counts[label] = kw_counts.get(label, 0) + 1

    if kw_counts:
        top_kws = sorted(kw_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        kw_str = "、".join(f"{k}({v}条)" for k, v in top_kws)
        insights.append(f"本周高热话题：{kw_str}")

    # source分布
    src_counts = {s: len(items) for s, items in by_source.items()}
    total = sum(src_counts.values())
    if total > 0:
        dist = "、".join(f"{s} {n}条({n*100//total}%)" for s, n in src_counts.items())
        insights.append(f"信息来源分布：{dist}")

    # 编程语言分布（GitHub）
    gh_items = by_source.get("github", [])
    if gh_items:
        langs = {}
        for it in gh_items:
            if it.get("lang"):
                langs[it["lang"]] = langs.get(it["lang"], 0) + 1
        if langs:
            lang_str = "、".join(f"{k}({v})" for k, v in
                                 sorted(langs.items(), key=lambda x: x[1], reverse=True))
            insights.append(f"GitHub语言分布：{lang_str}")

    return insights


# ============================================================
# 终端渲染
# ============================================================

def _chg(pct, decimals=2):
    if pct is None:
        return "—"
    arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
    return f"{arrow}{abs(pct):.{decimals}f}%"


def print_brief():
    now     = datetime.now()
    wd      = now.weekday()
    wnames  = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    history = load_history()
    snapshot = {}

    W = 64
    print()
    print("=" * W)
    print(f"  王瑞俊 · 每日简报 v2  {now.strftime('%Y-%m-%d')} {wnames[wd]}")
    print("=" * W)

    # ── ① 资产信号 ──────────────────────────────────────────
    print("\n① 资产信号")
    crypto = fetch_crypto()

    if "crypto_err" not in crypto:
        btc = crypto.get("btc", {})
        eth = crypto.get("eth", {})
        fg  = crypto.get("fear_greed")
        fr  = crypto.get("funding_rate")
        dom = crypto.get("btc_dominance")
        vol = crypto.get("vol_7d_ann")
        eth_btc = crypto.get("eth_btc", 0)

        # 恐贪中文标签
        fg_val = fg["value"] if fg else None
        if fg_val is not None:
            if fg_val <= 25:
                fg_label = "极度恐惧"
            elif fg_val <= 45:
                fg_label = "恐惧"
            elif fg_val <= 55:
                fg_label = "中性"
            elif fg_val <= 75:
                fg_label = "贪婪"
            else:
                fg_label = "极度贪婪"
        else:
            fg_label = "—"

        fg_trend = trend_vs_yesterday(history, "fear_greed", fg_val)

        print(f"  BTC  ${btc['price']:>9,.0f}  {_chg(btc['change_24h']):<10}"
              f"  恐贪 {fg_val}{fg_label}{fg_trend}")
        print(f"  ETH  ${eth['price']:>9,.0f}  {_chg(eth['change_24h']):<10}"
              f"  ETH/BTC {eth_btc:.5f}")

        # 新增指标行
        fr_str = f"{fr * 100:+.4f}%" if fr is not None else "—"
        fr_signal = ""
        if fr is not None:
            if fr < -0.0001:
                fr_signal = "（空头付费）"
            elif fr > 0.0005:
                fr_signal = "（多头过热）"
        dom_str = f"{dom:.1f}%" if dom is not None else "—"
        vol_str = f"{vol:.0f}%" if vol is not None else "—"
        print(f"  资金费率 {fr_str}{fr_signal}"
              f"  BTC占比 {dom_str}  7d波动率 {vol_str}")

        snapshot["btc_price"] = btc["price"]
        snapshot["fear_greed"] = fg_val
        snapshot["funding_rate"] = fr
        snapshot["btc_dominance"] = dom
        snapshot["vol_7d"] = vol
    else:
        print(f"  ⚠️  价格获取失败: {crypto['crypto_err']}")

    # 双币提醒 + 行权概率
    if DUAL_CURRENCY:
        btc_price = crypto.get("btc", {}).get("price", 0)
        vol_ann = crypto.get("vol_7d_ann", 40)
        print()
        for dc in DUAL_CURRENCY:
            expiry_dt = datetime.strptime(dc["expiry"], "%Y-%m-%d")
            days_left = (expiry_dt.date() - now.date()).days
            warn = "⚠️  " if days_left <= 3 else "📅  "

            prob_str = ""
            if btc_price > 0 and vol_ann and days_left > 0:
                is_bl = dc["type"].startswith("Buy")
                prob = trigger_probability(btc_price, dc["strike"],
                                           days_left, vol_ann, is_bl)
                prob_str = f"  行权概率 ≈{prob:.0f}%"

            print(f"  {warn}{dc['type']:<10} ${dc['strike']:,}  "
                  f"{dc['amount']:<16} {days_left}天后到期{prob_str}")

    # ── ② 公司雷达 ──────────────────────────────────────────
    print("\n② 公司雷达")
    company = fetch_company_radar()

    zjhk = company.get("zjhk", {})
    if "err" not in zjhk:
        chg = f"  {_chg(zjhk.get('change_pct'))}" if zjhk.get("change_pct") is not None else ""
        print(f"  中集环科 301559.SZ     ¥{zjhk['price']:.2f}{chg}  ({zjhk.get('date','')})")
        snapshot["zjhk_price"] = zjhk["price"]
        snapshot["zjhk_change"] = zjhk.get("change_pct")
    else:
        print(f"  中集环科 301559.SZ     获取失败")

    bcti = company.get("bcti", {})
    if "err" not in bcti:
        bcti_chg = _chg(bcti.get("change_pct"), 1)
        bcti_3m = _chg(bcti.get("trend_3m"), 0)
        print(f"  BCTI化学品运价         {bcti['value']:.0f}  日{bcti_chg}  近3月{bcti_3m}")
        snapshot["bcti"] = bcti["value"]
    else:
        print(f"  BCTI化学品运价         获取失败")

    steel = company.get("steel", {})
    print(f"  钢材上游信号           {steel.get('signal', '—')}")
    if steel.get("detail"):
        print(f"                         {steel['detail']}")
    snapshot["steel_avg_trend"] = steel.get("avg_trend", 0)

    # ── ⚡ 跨信号洞察 ───────────────────────────────────────
    insights = generate_insights(crypto, company, history)
    if insights:
        print("\n⚡ 信号关联")
        for ins in insights:
            print(f"  {ins}")

    # ── ③ OPC / AI 动态 ─────────────────────────────────────
    print("\n③ OPC机会 & AI动态")

    # HN
    print("\n  【Hacker News · 近30天】")
    hn = fetch_hn_intel()
    opc_items = []  # v3: 收集所有OPC条目
    for cat, items in hn.items():
        print(f"  ┌ {cat}")
        if items:
            for it in items:
                t = it["title"][:50] + "..." if len(it["title"]) > 50 else it["title"]
                cmt = f" | {it['comments']}评" if it.get("comments") else ""
                print(f"  │ · {t}  [{it['points']}↑{cmt}]")
                if it.get("summary"):
                    s = it["summary"][:60] + "..." if len(it["summary"]) > 60 else it["summary"]
                    print(f"  │   → {s}")
                opc_items.append({"source": "hn", "title": it["title"],
                                  "summary": it.get("summary", ""),
                                  "points": it["points"],
                                  "comments": it.get("comments", 0),
                                  "url": it.get("url", ""),
                                  "category": cat})
        else:
            print(f"  │ · 暂无高热度内容")

    # 36kr
    kr = fetch_36kr()
    if kr:
        print(f"\n  【36kr · AI/创业】")
        for it in kr:
            t = it["title"][:52] + "..." if len(it["title"]) > 52 else it["title"]
            print(f"  · {t}")
            if it.get("summary"):
                s = it["summary"][:60] + "..." if len(it["summary"]) > 60 else it["summary"]
                print(f"    → {s}")
            opc_items.append({"source": "36kr", "title": it["title"],
                              "summary": it.get("summary", ""),
                              "url": it.get("url", "")})

    # GitHub Trending
    gh = fetch_github_trending()
    if gh:
        print(f"\n  【GitHub Trending · AI】")
        for it in gh:
            lang_str = f" | {it['lang']}" if it.get("lang") else ""
            stars = f"  {it['stars']}" if it["stars"] else ""
            print(f"  · {it['name']}{stars}{lang_str}")
            if it.get("desc"):
                d = it["desc"][:60] + "..." if len(it["desc"]) > 60 else it["desc"]
                print(f"    → {d}")
            opc_items.append({"source": "github", "title": it["name"],
                              "summary": it.get("desc", ""),
                              "stars": it.get("stars", ""),
                              "lang": it.get("lang", "")})

    # 每日一问
    q = DAILY_QUESTIONS[wd]
    print(f"\n  💡 今日一问：\n     {q}")

    # ── ④ 行动项 ────────────────────────────────────────────
    if ACTION_ITEMS:
        print("\n④ 今日行动项")
        for item in ACTION_ITEMS:
            print(f"  ○ {item}")

    print()
    print("─" * W)
    print(f"  {now.strftime('%H:%M:%S')} | CoinGecko · Binance · akshare · HN · 36kr · GitHub")
    print("=" * W)
    print()

    # v3: OPC条目存入快照
    snapshot["opc_items"] = opc_items

    # 持久化今日快照
    save_today(snapshot)


# ============================================================
# 邮件推送
# ============================================================

def load_secrets() -> dict:
    if not os.path.exists(SECRETS_FILE):
        return {}
    with open(SECRETS_FILE, "r") as f:
        return json.load(f)


def send_email(content: str, subject: str):
    cfg = load_secrets()
    if not cfg:
        print("[WARN] 未找到凭证文件，跳过邮件")
        return

    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = cfg["smtp_user"]
    msg["To"] = cfg["mail_to"]

    try:
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], timeout=15) as smtp:
            smtp.login(cfg["smtp_user"], cfg["smtp_pass"])
            smtp.sendmail(cfg["smtp_user"], [cfg["mail_to"]], msg.as_string())
        print(f"[邮件] 已发送至 {cfg['mail_to']}")
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    now = datetime.now()
    wnames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    # --weekly: 手动生成周报
    if "--weekly" in sys.argv:
        path = generate_weekly_digest()
        if path:
            print(f"周报已生成: {path}")
        sys.exit(0)

    # 日报
    subject = f"每日简报 {now.strftime('%Y-%m-%d')} {wnames[now.weekday()]}"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_brief()
    content = buf.getvalue()

    # 周日自动附带周报
    weekly_path = None
    if now.weekday() == 6:  # 周日
        weekly_path = generate_weekly_digest()
        if weekly_path:
            subject += " [含周报]"

    sys.stdout.write(content)
    send_email(content, subject)
