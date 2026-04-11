#!/usr/bin/env python3
"""
行业情报扫描框架 (Industry Intelligence Scanner)
中集环科 ETO罐箱制造场景的外部环境监测工具

监测维度：
  1. 原料价格信号  — 铁矿石/焦炭/钢材上游成本趋势（akshare，可靠）
  2. 监管政策      — 危化品运输/压力容器/进出口新规（网页抓取，尽力而为）
  3. 行业动态      — 化工物流市场、竞争格局（网页抓取）
  4. 手工情报      — 展会/会议/竞品（人工录入）

运行方式：
  python3 intel_scanner.py              # 全量扫描并生成月度简报
  python3 intel_scanner.py --source macro   # 仅原料价格信号
  python3 intel_scanner.py --source policy  # 仅政策扫描
  python3 intel_scanner.py --list-sources   # 列出所有配置源

依赖：
  pip3 install requests beautifulsoup4 feedparser akshare pandas
"""

import sys
import os
import json
import time
import hashlib
import argparse
from datetime import datetime, timedelta
from typing import Optional
import ssl
import certifi

try:
    import requests
    from bs4 import BeautifulSoup
    import pandas as pd
    import akshare as ak
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip3 install requests beautifulsoup4 akshare pandas")
    sys.exit(1)

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

# ============================================================
# 配置区
# ============================================================

CONFIG = {
    "report_dir": "/Users/wangruijun/Documents/Ruijun的知识库/26年中集环科工作区/市场情报",
    # 缓存：避免重复抓取同一条目（存本地JSON）
    "cache_file": "/Users/wangruijun/Documents/Ruijun的知识库/26年中集环科工作区/数字化工具/.intel_cache.json",
    # 扫描最近N天的内容
    "lookback_days": 30,
    # 请求超时（秒）
    "request_timeout": 15,
    # 请求间隔（秒，避免被封）
    "request_delay": 2,
    # 代理（若需要，格式 'http://127.0.0.1:7890'）
    "proxy": None,
}

# ── 关键词权重配置 ──
# 命中核心词 → 高相关；命中背景词 → 中相关；0命中 → 低相关
KEYWORDS = {
    "core": [
        # 产品相关
        "罐箱", "罐车", "ISO罐", "液罐", "压力容器", "特种设备",
        "液化气", "危化品", "危险货物", "化工品运输",
        # 材料相关（可能影响供应链）
        "Q345R", "不锈钢", "压力钢板", "钢材",
        # 市场相关
        "化工物流", "液体危险货物", "多式联运", "罐式集装箱",
    ],
    "background": [
        # 监管框架
        "安全生产", "特种设备安全", "道路运输", "危货运输",
        "进出口管制", "检验检疫", "碳排放", "绿色制造",
        # 技术标准
        "国家标准", "行业标准", "GB/T", "TSG", "标准修订",
        # 宏观背景
        "制造业", "出口退税", "钢材关税", "双碳", "智能制造",
    ],
    "exclude": [
        # 过滤无关噪音
        "房地产", "股票", "基金", "医药", "教育",
    ],
}

# ── 信息源配置 ──
# type: macro=akshare数据, html=HTML抓取, rss=RSS, manual=手工录入
SOURCES = {
    # ── 原料价格信号（akshare，可靠）──
    "macro_upstream": {
        "name": "上游原料价格信号（铁矿石/焦炭/废钢）",
        "category": "macro",
        "type": "macro",
        "enabled": True,
    },

    # ── 监管政策（HTML抓取，尽力而为）──
    "mem_safety": {
        "name": "应急管理部 — 工作动态",
        "category": "policy",
        "type": "html",
        "url": "https://www.mem.gov.cn/xw/yjglbgzdt/",
        "list_selector": "ul li",
        "title_selector": "a",
        "date_selector": None,
        "link_base": "https://www.mem.gov.cn",
        "encoding": "utf-8",
        "enabled": True,
    },
    "ccin_policy": {
        "name": "中国化工报 — 政策动态",
        "category": "policy",
        "type": "html",
        "url": "http://www.ccin.com.cn/detail/category/8",
        "list_selector": "ul li",
        "title_selector": "a",
        "date_selector": None,
        "link_base": "http://www.ccin.com.cn",
        "encoding": "utf-8",
        "enabled": True,
    },

    # ── 行业动态 ──
    "ccin_industry": {
        "name": "中国化工报 — 行业新闻",
        "category": "industry",
        "type": "html",
        "url": "http://www.ccin.com.cn/",
        "list_selector": "ul li",
        "title_selector": "a",
        "date_selector": None,
        "link_base": "http://www.ccin.com.cn",
        "encoding": "utf-8",
        "enabled": True,
    },

    # ── 专利（需登录，先禁用，可换 SooPAT 公开接口）──
    "cnipa_patent": {
        "name": "国家知识产权局 — 罐箱专利（待配置）",
        "category": "patent",
        "type": "html",
        "url": "https://pss-system.cponline.cnipa.gov.cn/",
        "list_selector": "div.result-item",
        "title_selector": "span.title",
        "date_selector": None,
        "link_base": "",
        "enabled": False,
        "note": "需登录，建议改用 SooPAT（www.soopat.com）手动检索后录入",
    },

    # ── 竞争对手A股/港股动态（akshare股价+新闻）──
    "competitor_singamas": {
        "name": "胜狮货柜（0716.HK）— 直接竞争对手监测",
        "category": "competitor",
        "type": "competitor_stock",
        "hk_symbol": "00716",          # 港股代码
        "name_zh": "胜狮货柜",
        "enabled": True,
    },

    # ── 主要客户动态（罐箱租赁商融资成本指标）──
    "customer_macro_signal": {
        "name": "罐箱主要客户宏观信号（美元利率+化工品价格）",
        "category": "customer",
        "type": "customer_macro",
        "enabled": True,
    },

    # ── 中集环科自身A股新闻（301559.SZ）──
    "self_news_301559": {
        "name": "中集环科 A股新闻（301559.SZ）",
        "category": "industry",
        "type": "self_stock_news",
        "a_symbol": "301559",
        "enabled": True,
    },

    # ── 手工录入（展会/竞品/会议）──
    "manual_events": {
        "name": "行业展会与会议（手工录入）",
        "category": "industry",
        "type": "manual",
        "items": [
            {
                "title": "中国国际危险品运输及储存技术展览会（CHDTS）",
                "date": "2026-06",
                "url": "",
                "note": "关注危化品运输设备最新需求，竞品动态",
                "relevance": "high",
            },
            {
                "title": "intermodal Asia 2026（上海，多式联运展）",
                "date": "2026-06",
                "url": "",
                "note": "ISO罐箱行业国际风向，欧洲客户需求变化",
                "relevance": "high",
            },
            {
                "title": "中国压力容器学术会议",
                "date": "2026-10",
                "url": "",
                "note": "新材料/新工艺，竞品技术动向",
                "relevance": "medium",
            },
        ],
        "enabled": True,
    },
}

# ============================================================
# 工具函数
# ============================================================

def get_session() -> requests.Session:
    """创建配置好的HTTP会话"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    if CONFIG.get("proxy"):
        s.proxies = {
            "http": CONFIG["proxy"],
            "https": CONFIG["proxy"],
        }
    s.verify = certifi.where()
    return s


def load_cache() -> dict:
    """加载已处理条目的缓存（用于去重）"""
    cache_path = CONFIG["cache_file"]
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    """保存缓存"""
    os.makedirs(os.path.dirname(CONFIG["cache_file"]), exist_ok=True)
    with open(CONFIG["cache_file"], "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def item_id(title: str, url: str) -> str:
    """生成条目唯一ID（用于去重）"""
    raw = f"{title}{url}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


# ============================================================
# 相关度评分
# ============================================================

def score_relevance(text: str) -> tuple:
    """
    对文本计算关键词相关度
    返回：(score, matched_keywords)
    score: 0-100
    """
    text_lower = text.lower()

    # 排除词（直接过滤）
    for excl in KEYWORDS["exclude"]:
        if excl in text:
            return 0, []

    core_hits = [kw for kw in KEYWORDS["core"] if kw in text]
    bg_hits = [kw for kw in KEYWORDS["background"] if kw in text]

    score = len(core_hits) * 30 + len(bg_hits) * 10
    score = min(score, 100)

    return score, core_hits + bg_hits


def classify_relevance(score: int) -> str:
    if score >= 60:
        return "HIGH"
    elif score >= 25:
        return "MEDIUM"
    elif score > 0:
        return "LOW"
    else:
        return "NONE"


# ============================================================
# 数据抓取
# ============================================================

# ============================================================
# 原料价格宏观信号（akshare，可靠性高）
# ============================================================

def fetch_macro_intel() -> dict:
    """
    从akshare获取钢铁上游原料价格信号
    用于判断钢材成本压力方向（提前1-2个月预判钢价走势）

    信号逻辑：
      铁矿石↑ + 焦炭↑ → 钢材成本压力上行 → 可能涨价 → 早买
      铁矿石↓ + 焦炭↓ → 成本回落 → 等待买入窗口
    """
    result = {
        "commodity_index": None,
        "futures": {},
        "signal": "",
        "signal_detail": [],
    }

    # 1. 大宗商品价格综合指数
    try:
        df = ak.macro_china_commodity_price_index()
        df["日期"] = pd.to_datetime(df["日期"])
        latest = df.iloc[-1]
        prev_5 = df.iloc[-6] if len(df) > 6 else df.iloc[0]

        idx_now = float(latest["最新值"])
        idx_5d = float(prev_5["最新值"])
        idx_trend = (idx_now / idx_5d - 1) * 100

        result["commodity_index"] = {
            "value": idx_now,
            "trend_5d_pct": round(idx_trend, 2),
            "yr_change_pct": float(latest["近1年涨跌幅"]) if latest["近1年涨跌幅"] else None,
            "date": str(latest["日期"])[:10],
        }
    except Exception as e:
        result["signal_detail"].append(f"大宗商品指数获取失败: {e}")

    # 2. 上游关键品种：铁矿石(I0)、焦炭(J0)、焦煤(JM0)
    upstream_symbols = {
        "I0": "铁矿石",
        "J0": "焦炭",
        "JM0": "焦煤",
        "RB0": "螺纹钢",
        "HC0": "热轧卷板",
    }

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=90)
    up_trends = []

    for symbol, name in upstream_symbols.items():
        try:
            df = ak.futures_main_sina(
                symbol=symbol,
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d"),
            )
            if df.empty:
                continue

            df["日期"] = pd.to_datetime(df["日期"])
            df = df.sort_values("日期")

            current = float(df["收盘价"].iloc[-1])
            price_30d = float(df["收盘价"].iloc[max(0, len(df)-22)])
            trend_30d = (current / price_30d - 1) * 100

            result["futures"][symbol] = {
                "name": name,
                "current": current,
                "trend_30d_pct": round(trend_30d, 2),
                "dir": "↑" if trend_30d > 0 else "↓",
            }

            if symbol in ("I0", "J0"):  # 只用铁矿+焦炭判断方向
                up_trends.append(trend_30d)

        except Exception as e:
            result["signal_detail"].append(f"{name}({symbol}) 获取失败: {e}")

    # 3. 生成综合信号
    if up_trends:
        avg_upstream = sum(up_trends) / len(up_trends)
        if avg_upstream > 3:
            result["signal"] = "⚠️ 上游成本压力上行"
            result["signal_detail"].append(
                f"铁矿石/焦炭30日均涨幅 +{avg_upstream:.1f}%，钢材成本存在上行压力，"
                f"建议提前锁定采购"
            )
        elif avg_upstream < -3:
            result["signal"] = "✅ 上游成本回落"
            result["signal_detail"].append(
                f"铁矿石/焦炭30日均跌幅 {avg_upstream:.1f}%，钢材成本存在回落空间，"
                f"可适当等待更低买点"
            )
        else:
            result["signal"] = "🔵 上游成本平稳"
            result["signal_detail"].append(
                f"铁矿石/焦炭30日均变动 {avg_upstream:.1f}%，成本端无明显趋势"
            )

    return result


def fetch_html_source(source_id: str, source: dict, session: requests.Session) -> list:
    """
    抓取HTML类型信息源（健壮版）
    采用分级回退策略：精确选择器 → 宽泛li/a → 纯链接扫描
    """
    items = []
    try:
        resp = session.get(source["url"], timeout=CONFIG["request_timeout"])
        # 编码：优先用配置指定，其次 apparent_encoding
        resp.encoding = source.get("encoding") or resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 策略1：用配置的CSS选择器
        list_items = soup.select(source["list_selector"]) if source.get("list_selector") else []

        # 策略2：选择器取不到，用宽泛回退（所有li）
        if not list_items:
            list_items = soup.find_all("li")

        candidate_links = []

        for li in list_items[:50]:
            a = li.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")

            # 过滤：太短/太长的文本通常是导航项
            if not (6 < len(title) < 80):
                continue

            if href and not href.startswith("http"):
                href = source.get("link_base", "") + href

            candidate_links.append((title, href))

        # 策略3：若li策略依然取不到，直接扫全页链接
        if not candidate_links:
            for a in soup.find_all("a", href=True)[:80]:
                title = a.get_text(strip=True)
                if 6 < len(title) < 80:
                    href = a.get("href", "")
                    if href and not href.startswith("http"):
                        href = source.get("link_base", "") + href
                    candidate_links.append((title, href))

        for title, href in candidate_links[:30]:
            score, keywords = score_relevance(title)
            relevance = classify_relevance(score)

            # 策略：跳过0分条目（减少噪音）
            if score == 0:
                continue

            items.append({
                "source_id": source_id,
                "source_name": source["name"],
                "category": source["category"],
                "title": title,
                "url": href,
                "date": "",
                "relevance": relevance,
                "score": score,
                "keywords": keywords,
            })

    except Exception as e:
        print(f"  [WARN] {source['name']} 抓取失败: {e}")

    return items


def fetch_rss_source(source_id: str, source: dict) -> list:
    """抓取RSS类型信息源"""
    if not HAS_FEEDPARSER:
        print(f"  [SKIP] {source['name']}：feedparser未安装，运行 pip3 install feedparser")
        return []

    items = []
    try:
        feed = feedparser.parse(source["url"])
        lookback = datetime.now() - timedelta(days=CONFIG["lookback_days"])

        for entry in feed.entries[:50]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            pub = entry.get("published", "")

            score, keywords = score_relevance(title + " " + entry.get("summary", ""))
            relevance = classify_relevance(score)

            items.append({
                "source_id": source_id,
                "source_name": source["name"],
                "category": source["category"],
                "title": title,
                "url": link,
                "date": pub[:10] if len(pub) >= 10 else pub,
                "relevance": relevance,
                "score": score,
                "keywords": keywords,
            })

    except Exception as e:
        print(f"  [WARN] {source['name']} RSS解析失败: {e}")

    return items


def fetch_manual_source(source_id: str, source: dict) -> list:
    """返回手工录入条目"""
    items = []
    for item in source.get("items", []):
        items.append({
            "source_id": source_id,
            "source_name": source["name"],
            "category": source["category"],
            "title": item["title"],
            "url": item.get("url", ""),
            "date": item.get("date", ""),
            "relevance": item.get("relevance", "medium").upper(),
            "score": 80 if item.get("relevance") == "high" else 40,
            "keywords": [],
            "note": item.get("note", ""),
        })
    return items


# ============================================================
# 报告生成
# ============================================================

# ============================================================
# 竞争对手与客户信号
# ============================================================

def fetch_competitor_stock(source_id: str, source: dict) -> list:
    """
    监测竞争对手港股股价动态
    胜狮货柜（0716.HK）是中集环科在罐箱业务的主要上市竞争对手
    股价走势可反映行业景气度和竞争格局变化
    """
    items = []
    try:
        symbol = source["hk_symbol"]
        name = source["name_zh"]

        df = ak.stock_hk_daily(symbol=symbol, adjust="")
        if df.empty:
            return []

        df = df.sort_values("date")
        # 只取近6个月
        cutoff = (datetime.now() - timedelta(days=180)).date()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[df["date"] >= cutoff].reset_index(drop=True)
        if df.empty:
            return []

        current = float(df["close"].iloc[-1])
        price_3m = float(df["close"].iloc[max(0, len(df)-63)])  # ≈3个月交易日
        price_6m = float(df["close"].iloc[0])
        trend_3m = (current / price_3m - 1) * 100
        trend_6m = (current / price_6m - 1) * 100

        direction_3m = "↑" if trend_3m > 0 else "↓"
        direction_6m = "↑" if trend_6m > 0 else "↓"

        # 研判信号
        if trend_3m < -15:
            signal = "⚠️ 竞品股价大幅下跌，行业景气度低迷"
            relevance = "HIGH"
        elif trend_3m > 15:
            signal = "📈 竞品股价大幅上涨，行业需求可能复苏"
            relevance = "HIGH"
        elif abs(trend_3m) > 8:
            signal = f"{'上涨' if trend_3m > 0 else '下跌'}明显，关注行业动向"
            relevance = "MEDIUM"
        else:
            signal = "股价相对平稳"
            relevance = "LOW"

        title = (
            f"【竞品】{name}（{symbol}）现价 HK${current:.2f} | "
            f"近3月 {direction_3m}{abs(trend_3m):.1f}% | 近6月 {direction_6m}{abs(trend_6m):.1f}%"
        )

        items.append({
            "source_id": source_id,
            "source_name": source["name"],
            "category": "competitor",
            "title": title,
            "url": f"https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym={symbol}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "relevance": relevance,
            "score": 60 if relevance == "HIGH" else (30 if relevance == "MEDIUM" else 5),
            "keywords": [name, "竞争对手", "罐箱"],
            "note": signal,
        })

        # 额外获取竞品新闻（若可能）
        try:
            profile = ak.stock_hk_company_profile_em(symbol=symbol)
            if not profile.empty:
                intro = str(profile.get("公司介绍", pd.Series()).iloc[0] if "公司介绍" in profile.columns else "")[:200]
                if intro:
                    items.append({
                        "source_id": source_id + "_profile",
                        "source_name": source["name"] + " 公司简介",
                        "category": "competitor",
                        "title": f"【竞品档案】{name}：{intro[:80]}...",
                        "url": "",
                        "date": "",
                        "relevance": "LOW",
                        "score": 5,
                        "keywords": [name],
                        "note": "",
                    })
        except Exception:
            pass

    except Exception as e:
        print(f"  [WARN] 竞品股价获取失败: {e}")

    return items


def fetch_customer_macro(source_id: str, source: dict) -> list:
    """
    罐箱主要客户（租赁商）的宏观信号
    核心逻辑：租赁商融资成本 = f(美元利率)
      美元利率↑ → 租赁商融资成本↑ → 新箱订购减少 → 中集环科订单下降
    数据代理：美国10年期国债收益率（US10Y）
    """
    items = []
    try:
        # 获取美联储基准利率（美联储利率决议报告）
        df = ak.macro_bank_usa_interest_rate()
        if df.empty:
            raise ValueError("数据为空")

        # 过滤非空今值记录，按日期排序
        df["日期"] = pd.to_datetime(df["日期"])
        df = df[df["今值"].notna()].sort_values("日期").tail(12)
        latest_rate = float(df["今值"].iloc[-1]) if not df.empty else None
        prev_rate = float(df["今值"].iloc[-6]) if len(df) >= 6 else None

        if latest_rate is not None:
            change = latest_rate - prev_rate if prev_rate else 0
            if latest_rate > 4.5:
                signal = f"⚠️ 美联储利率仍处高位（{latest_rate:.2f}%），租赁商融资成本压制罐箱需求"
                relevance = "HIGH"
            elif change < -0.5:
                signal = f"📉 美联储降息中（较6月前-{abs(change):.1f}%），租赁商融资成本改善，罐箱需求可能复苏"
                relevance = "HIGH"
            else:
                signal = f"美联储利率 {latest_rate:.2f}%，较前期变动 {change:+.2f}%"
                relevance = "MEDIUM"

            items.append({
                "source_id": source_id,
                "source_name": source["name"],
                "category": "customer",
                "title": f"【客户宏观】美联储利率 {latest_rate:.2f}% → {signal[:50]}",
                "url": "",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "relevance": relevance,
                "score": 60 if relevance == "HIGH" else 30,
                "keywords": ["美元利率", "租赁商", "罐箱需求"],
                "note": signal,
            })
    except Exception as e:
        print(f"  [WARN] 客户宏观信号获取失败: {e}")

    return items


def fetch_self_stock_news(source_id: str, source: dict) -> list:
    """获取中集环科A股新闻（301559.SZ）"""
    items = []
    try:
        df = ak.stock_news_em(symbol=source["a_symbol"])
        if df.empty:
            return []

        for _, row in df.head(10).iterrows():
            title = str(row.get("新闻标题", ""))
            content = str(row.get("新闻内容", ""))[:200]
            date_str = str(row.get("发布时间", ""))[:10]
            url = str(row.get("新闻链接", ""))

            if not title:
                continue

            score, keywords = score_relevance(title + " " + content)
            relevance = classify_relevance(score)

            items.append({
                "source_id": source_id,
                "source_name": source["name"],
                "category": "industry",
                "title": f"【公司动态】{title}",
                "url": url,
                "date": date_str,
                "relevance": relevance if score > 0 else "LOW",
                "score": max(score, 10),  # 公司自身新闻基础分10
                "keywords": keywords,
                "note": "",
            })
    except Exception as e:
        print(f"  [WARN] 自身股票新闻获取失败: {e}")

    return items


def generate_macro_section(macro: dict) -> list:
    """生成原料价格信号部分"""
    lines = [
        "## 上游原料价格信号",
        "",
        f"> **综合判断：{macro.get('signal', '数据获取中')}**",
        "",
    ]

    # 大宗商品指数
    ci = macro.get("commodity_index")
    if ci:
        trend_dir = "↑" if ci["trend_5d_pct"] > 0 else "↓"
        lines += [
            f"**大宗商品综合价格指数（{ci['date']}）：** {ci['value']:.0f}  "
            f"5日 {trend_dir}{abs(ci['trend_5d_pct']):.1f}%  "
            f"年同比 {ci['yr_change_pct']:+.1f}%" if ci.get("yr_change_pct") else f"5日 {trend_dir}{abs(ci['trend_5d_pct']):.1f}%",
            "",
        ]

    # 上游品种明细
    futures = macro.get("futures", {})
    if futures:
        lines += [
            "| 品种 | 当前价（元/吨） | 30日涨跌 | 对钢材成本影响 |",
            "|------|----------------|----------|----------------|",
        ]
        impact_map = {
            "I0": "直接（占钢材成本约40%）",
            "J0": "直接（占钢材成本约15%）",
            "JM0": "间接（焦炭原料）",
            "RB0": "终端参考",
            "HC0": "终端参考（Q345R代理）",
        }
        for sym, data in futures.items():
            trend_str = f"{data['dir']}{abs(data['trend_30d_pct']):.1f}%"
            impact = impact_map.get(sym, "—")
            lines.append(
                f"| {data['name']}（{sym}） | "
                f"¥{data['current']:,.0f} | "
                f"{trend_str} | "
                f"{impact} |"
            )
        lines.append("")

    # 信号解读
    for detail in macro.get("signal_detail", []):
        lines.append(f"> {detail}")
    lines.append("")

    return lines


def generate_report(all_items: list, macro: Optional[dict] = None,
                    source_filter: Optional[str] = None) -> str:
    """生成月度情报简报（Markdown格式）"""
    now = datetime.now()
    month_str = now.strftime("%Y-%m")

    # 按相关度分组
    high = [i for i in all_items if i["relevance"] == "HIGH"]
    medium = [i for i in all_items if i["relevance"] == "MEDIUM"]

    # 按来源分类
    policy_items = [i for i in all_items if i["category"] == "policy"]
    industry_items = [i for i in all_items if i["category"] == "industry"]
    patent_items = [i for i in all_items if i["category"] == "patent"]
    competitor_items = [i for i in all_items if i["category"] == "competitor"]
    customer_items = [i for i in all_items if i["category"] == "customer"]

    def render_items(items: list, max_items: int = 10) -> list:
        lines = []
        for item in sorted(items, key=lambda x: x["score"], reverse=True)[:max_items]:
            kw_str = "、".join(item["keywords"][:3]) if item["keywords"] else ""
            kw_tag = f"  `{kw_str}`" if kw_str else ""
            note = f"\n  > {item['note']}" if item.get("note") else ""
            date_str = f"（{item['date']}）" if item["date"] else ""
            link = f" [→ 原文]({item['url']})" if item["url"] else ""
            lines.append(f"- **{item['title']}**{date_str}{link}{kw_tag}{note}")
        return lines

    lines = [
        "---",
        f'title: "市场情报简报 {month_str}"',
        "type: 市场情报",
        f"date: {now.strftime('%Y-%m-%d')}",
        "tags:",
        "  - 市场情报",
        "  - 原料价格",
        "  - 政策监测",
        "  - 行业动态",
        "---",
        "",
        f"# 市场情报简报 {month_str}",
        "",
        f"> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} | "
        f"网页扫描：{len(all_items)} 条 | "
        f"高相关：{len(high)} | 中相关：{len(medium)}",
        "",
        "---",
        "",
    ]

    # 原料价格信号（放最前，是最可靠的部分）
    if macro:
        lines += generate_macro_section(macro)
        lines += ["---", ""]

    # 高相关条目汇总
    lines += ["## 网页扫描高相关条目", ""]
    if high:
        lines += render_items(high)
    else:
        lines.append("_本期无高相关条目（可能是选择器需调试，或本期确实无相关内容）_")

    lines += ["", "---", "", "## 监管政策动态", ""]

    high_policy = [i for i in policy_items if i["relevance"] in ("HIGH", "MEDIUM")]
    if high_policy:
        lines += render_items(high_policy, max_items=8)
    else:
        lines.append("_本期政策扫描无高/中相关条目_")

    lines += ["", "## 行业与市场动态", ""]

    high_industry = [i for i in industry_items if i["relevance"] in ("HIGH", "MEDIUM")]
    if high_industry:
        lines += render_items(high_industry, max_items=8)
    else:
        lines.append("_本期行业扫描无高/中相关条目_")

    # 竞争对手动态
    if competitor_items:
        lines += ["", "## 竞争对手动态", ""]
        for item in competitor_items:
            note = f"\n  > {item['note']}" if item.get("note") else ""
            date_str = f"（{item['date']}）" if item.get("date") else ""
            link = f" [→ HKEX]({item['url']})" if item.get("url") else ""
            lines.append(f"- **{item['title']}**{date_str}{link}{note}")
        lines.append("")

    # 主要客户宏观信号
    if customer_items:
        lines += ["## 主要客户宏观信号", ""]
        for item in customer_items:
            note = f"\n  > {item['note']}" if item.get("note") else ""
            date_str = f"（{item['date']}）" if item.get("date") else ""
            lines.append(f"- **{item['title']}**{date_str}{note}")
        lines.append("")

    if patent_items:
        lines += ["", "## 专利动态", ""]
        lines += render_items(patent_items, max_items=5)

    # 展会日历
    manual = [i for i in all_items if i["source_id"] == "manual_events"]
    if manual:
        lines += ["", "## 重要会议与展会", ""]
        lines += render_items(manual)

    lines += [
        "",
        "---",
        "",
        "## 情报源扫描状态",
        "",
        "| 来源 | 类别 | 本期条目 | 状态 |",
        "|------|------|----------|------|",
    ]

    source_stats: dict = {}
    for item in all_items:
        sid = item["source_id"]
        source_stats[sid] = source_stats.get(sid, 0) + 1

    for sid, src in SOURCES.items():
        count = source_stats.get(sid, 0)
        status = "✅" if count > 0 else ("⚠️ 0条（可能需要调试选择器）" if src["enabled"] else "⏸️ 已禁用")
        lines.append(f"| {src['name']} | {src['category']} | {count} | {status} |")

    lines += [
        "",
        "---",
        "",
        "## 使用说明",
        "",
        "**添加新情报源（SOURCES配置）：**",
        "```python",
        "'my_source': {",
        "    'name': '来源名称',",
        "    'category': 'policy/industry/patent',",
        "    'type': 'html/rss/manual',",
        "    'url': 'https://...',",
        "    'list_selector': 'ul li',    # CSS选择器",
        "    'title_selector': 'a',",
        "    'date_selector': 'span',",
        "    'enabled': True,",
        "}",
        "```",
        "",
        "**添加核心关键词（KEYWORDS配置）：**",
        "- core词命中 +30分，background词 +10分，达60分为高相关",
        "",
        "← [[培元—创新与数字化]] | [[26年工作区 MOC]]",
    ]

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def main(source_filter: Optional[str] = None, list_sources: bool = False):
    if list_sources:
        print("\n已配置的情报源：\n")
        for sid, src in SOURCES.items():
            status = "✅ 启用" if src["enabled"] else "⏸️ 禁用"
            print(f"  [{src['category']:8s}] {status}  {src['name']}")
            print(f"            ID: {sid}  Type: {src['type']}")
        return

    print("=" * 60)
    print("  行业情报扫描系统  |  中集环科")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    session = get_session()
    cache = load_cache()
    all_items = []
    macro_data = None

    for sid, source in SOURCES.items():
        if not source.get("enabled", True):
            continue
        if source_filter and source["category"] != source_filter:
            continue

        print(f"\n[扫描] {source['name']}...")

        if source["type"] == "macro":
            macro_data = fetch_macro_intel()
            sig = macro_data.get("signal", "获取中")
            futures_count = len(macro_data.get("futures", {}))
            print(f"  原料品种: {futures_count} 个 | 综合信号: {sig}")
            continue
        elif source["type"] == "html":
            items = fetch_html_source(sid, source, session)
            time.sleep(CONFIG["request_delay"])
        elif source["type"] == "rss":
            items = fetch_rss_source(sid, source)
        elif source["type"] == "manual":
            items = fetch_manual_source(sid, source)
        elif source["type"] == "competitor_stock":
            items = fetch_competitor_stock(sid, source)
        elif source["type"] == "customer_macro":
            items = fetch_customer_macro(sid, source)
        elif source["type"] == "self_stock_news":
            items = fetch_self_stock_news(sid, source)
        else:
            print(f"  [SKIP] 未知类型: {source['type']}")
            continue

        # 去重（基于缓存）
        new_items = []
        for item in items:
            iid = item_id(item["title"], item["url"])
            if iid not in cache:
                new_items.append(item)
                cache[iid] = datetime.now().isoformat()

        high_count = sum(1 for i in items if i["relevance"] in ("HIGH", "MEDIUM"))
        print(f"  获取 {len(items)} 条 | 新增 {len(new_items)} 条 | 相关(高+中) {high_count} 条")
        all_items.extend(items)

    save_cache(cache)

    # 生成报告
    report_content = generate_report(all_items, macro=macro_data, source_filter=source_filter)
    now = datetime.now()
    month_str = now.strftime("%Y-%m")
    suffix = f"_{source_filter}" if source_filter else ""
    filename = f"市场情报简报_{month_str}{suffix}.md"
    report_path = os.path.join(CONFIG["report_dir"], filename)

    os.makedirs(CONFIG["report_dir"], exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    high_all = sum(1 for i in all_items if i["relevance"] == "HIGH")
    med_all = sum(1 for i in all_items if i["relevance"] == "MEDIUM")
    print(f"\n[汇总] 网页扫描 {len(all_items)} 条 | 高相关 {high_all} | 中相关 {med_all}")
    print(f"[报告] 已保存至: {report_path}")
    print("\n完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行业情报扫描系统")
    parser.add_argument("--source", help="只扫描指定类别: policy/industry/patent")
    parser.add_argument("--list-sources", action="store_true", help="列出所有配置的信息源")
    args = parser.parse_args()
    main(source_filter=args.source, list_sources=args.list_sources)
