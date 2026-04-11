#!/usr/bin/env python3
"""
行业情报扫描框架 (Industry Intelligence Scanner)
中集环科 ETO罐箱制造场景的外部环境监测工具

监测维度：
  1. 监管政策  — 危化品运输/压力容器/进出口新规
  2. 行业动态  — 化工物流市场、竞争格局变化
  3. 专利扫描  — 国内同类产品专利申请动态
  4. 技术标准  — 国标/行标更新（GB/T、TSG等）

运行方式：
  python3 intel_scanner.py              # 全量扫描并生成月度简报
  python3 intel_scanner.py --source policy  # 仅扫描政策
  python3 intel_scanner.py --source patent  # 仅扫描专利
  python3 intel_scanner.py --list-sources   # 列出所有配置源

依赖：
  pip3 install requests beautifulsoup4 feedparser
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
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请运行: pip3 install requests beautifulsoup4")
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
# type: rss=RSS订阅, html=HTML抓取, manual=手工录入占位
SOURCES = {
    # ── 监管政策 ──
    "mot_news": {
        "name": "交通运输部 — 新闻动态",
        "category": "policy",
        "type": "html",
        "url": "https://www.mot.gov.cn/jiaotongyaowen/",
        "list_selector": "ul.list_con li",          # CSS选择器（找列表项）
        "title_selector": "a",
        "date_selector": "span",
        "link_base": "https://www.mot.gov.cn",
        "enabled": True,
    },
    "mem_safety": {
        "name": "应急管理部 — 法规标准",
        "category": "policy",
        "type": "html",
        "url": "https://www.mem.gov.cn/fw/flfgbz/",
        "list_selector": "ul.list_style li",
        "title_selector": "a",
        "date_selector": "span.date",
        "link_base": "https://www.mem.gov.cn",
        "enabled": True,
    },
    "gacc_news": {
        "name": "海关总署 — 公告通知",
        "category": "policy",
        "type": "html",
        "url": "http://www.customs.gov.cn/customs/302249/302266/index.html",
        "list_selector": "ul.list_con li",
        "title_selector": "a",
        "date_selector": "span",
        "link_base": "http://www.customs.gov.cn",
        "enabled": True,
    },
    "samr_std": {
        "name": "市场监管总局 — 特种设备标准",
        "category": "policy",
        "type": "html",
        "url": "https://www.samr.gov.cn/tzsbj/",
        "list_selector": "ul.list-style li",
        "title_selector": "a",
        "date_selector": None,
        "link_base": "https://www.samr.gov.cn",
        "enabled": True,
    },

    # ── 行业动态 (RSS) ──
    "chemnet_news": {
        "name": "中国化工网 — 行业动态",
        "category": "industry",
        "type": "rss",
        "url": "https://www.chemnet.com/rss/news.xml",
        "enabled": True,
    },
    "sinotrans_news": {
        "name": "中国国际货运代理协会动态",
        "category": "industry",
        "type": "rss",
        "url": "https://www.cifa.org.cn/rss.xml",
        "enabled": False,  # 待验证RSS地址
    },

    # ── 专利扫描 ──
    "cnipa_patent": {
        "name": "国家知识产权局 — 罐箱相关专利",
        "category": "patent",
        "type": "html",
        # 搜索罐式集装箱相关专利，可调整关键词
        "url": "https://pss-system.cponline.cnipa.gov.cn/searchResult/index?searchKey=罐式集装箱",
        "list_selector": "div.result-item",
        "title_selector": "span.title",
        "date_selector": "span.date",
        "link_base": "",
        "enabled": False,  # 知产局需要登录，先禁用
        "note": "需要登录后使用，或改用 SooPAT / patentics 等第三方"
    },

    # ── 手工录入占位（重要会议/展会）──
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
                "title": "intermodal Asia 2026",
                "date": "2026-06",
                "url": "",
                "note": "多式联运展，ISO罐箱行业风向",
                "relevance": "high",
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

def fetch_html_source(source_id: str, source: dict, session: requests.Session) -> list:
    """抓取HTML类型信息源"""
    items = []
    try:
        resp = session.get(source["url"], timeout=CONFIG["request_timeout"])
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        list_items = soup.select(source["list_selector"])
        for li in list_items[:30]:  # 最多取30条
            a = li.select_one(source["title_selector"])
            if not a:
                continue

            title = a.get_text(strip=True)
            href = a.get("href", "")
            if href and not href.startswith("http"):
                href = source.get("link_base", "") + href

            date_el = li.select_one(source["date_selector"]) if source.get("date_selector") else None
            pub_date = date_el.get_text(strip=True) if date_el else ""

            if not title:
                continue

            score, keywords = score_relevance(title)
            relevance = classify_relevance(score)

            items.append({
                "source_id": source_id,
                "source_name": source["name"],
                "category": source["category"],
                "title": title,
                "url": href,
                "date": pub_date,
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

def generate_report(all_items: list, source_filter: Optional[str] = None) -> str:
    """生成月度情报简报（Markdown格式）"""
    now = datetime.now()
    month_str = now.strftime("%Y-%m")

    # 按相关度分组
    high = [i for i in all_items if i["relevance"] == "HIGH"]
    medium = [i for i in all_items if i["relevance"] == "MEDIUM"]
    low = [i for i in all_items if i["relevance"] == "LOW"]

    # 按来源分类
    policy_items = [i for i in all_items if i["category"] == "policy"]
    industry_items = [i for i in all_items if i["category"] == "industry"]
    patent_items = [i for i in all_items if i["category"] == "patent"]

    def render_items(items: list, max_items: int = 10) -> list:
        lines = []
        for item in sorted(items, key=lambda x: x["score"], reverse=True)[:max_items]:
            kw_str = "、".join(item["keywords"][:3]) if item["keywords"] else ""
            kw_tag = f"  `{kw_str}`" if kw_str else ""
            note = f"  > {item['note']}" if item.get("note") else ""
            date_str = f"（{item['date']}）" if item["date"] else ""
            link = f"[→ 原文]({item['url']})" if item["url"] else ""
            lines.append(f"- **{item['title']}**{date_str} {link}{kw_tag}")
            if note:
                lines.append(note)
        return lines

    lines = [
        "---",
        f'title: "市场情报简报 {month_str}"',
        "type: 市场情报",
        f"date: {now.strftime('%Y-%m-%d')}",
        "tags:",
        "  - 市场情报",
        "  - 政策监测",
        "  - 行业动态",
        "---",
        "",
        f"# 市场情报简报 {month_str}",
        "",
        f"> 生成时间：{now.strftime('%Y-%m-%d %H:%M')} | "
        f"本次扫描：{len(all_items)} 条 | "
        f"高相关：{len(high)} 条 | 中相关：{len(medium)} 条",
        "",
        "---",
        "",
        "## 高相关条目（需关注）",
        "",
    ]

    if high:
        lines += render_items(high)
    else:
        lines.append("_本期无高相关条目_")

    lines += [
        "",
        "---",
        "",
        "## 监管政策动态",
        "",
    ]

    high_policy = [i for i in policy_items if i["relevance"] in ("HIGH", "MEDIUM")]
    if high_policy:
        lines += render_items(high_policy, max_items=8)
    else:
        lines.append("_本期政策动态无明显相关内容_")

    lines += [
        "",
        "## 行业与市场动态",
        "",
    ]

    high_industry = [i for i in industry_items if i["relevance"] in ("HIGH", "MEDIUM")]
    if high_industry:
        lines += render_items(high_industry, max_items=8)
    else:
        lines.append("_本期无明显相关行业动态_")

    if patent_items:
        lines += [
            "",
            "## 专利动态",
            "",
        ]
        lines += render_items(patent_items, max_items=5)

    # 展会日历
    manual = [i for i in all_items if i["source_id"] == "manual_events"]
    if manual:
        lines += [
            "",
            "## 重要会议与展会",
            "",
        ]
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

    for sid, source in SOURCES.items():
        if not source.get("enabled", True):
            continue
        if source_filter and source["category"] != source_filter:
            continue

        print(f"\n[扫描] {source['name']}...")

        if source["type"] == "html":
            items = fetch_html_source(sid, source, session)
            time.sleep(CONFIG["request_delay"])
        elif source["type"] == "rss":
            items = fetch_rss_source(sid, source)
        elif source["type"] == "manual":
            items = fetch_manual_source(sid, source)
        else:
            print(f"  [SKIP] 未知类型: {source['type']}")
            continue

        # 过滤已缓存（去重）
        new_items = []
        for item in items:
            iid = item_id(item["title"], item["url"])
            if iid not in cache:
                new_items.append(item)
                cache[iid] = now_str = datetime.now().isoformat()

        high_count = sum(1 for i in items if i["relevance"] in ("HIGH", "MEDIUM"))
        print(f"  获取 {len(items)} 条 | 新增 {len(new_items)} 条 | 相关(高+中) {high_count} 条")
        all_items.extend(items)

    save_cache(cache)

    # 生成报告
    report_content = generate_report(all_items, source_filter)
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
    print(f"\n[汇总] 共 {len(all_items)} 条 | 高相关 {high_all} | 中相关 {med_all}")
    print(f"[报告] 已保存至: {report_path}")
    print("\n完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行业情报扫描系统")
    parser.add_argument("--source", help="只扫描指定类别: policy/industry/patent")
    parser.add_argument("--list-sources", action="store_true", help="列出所有配置的信息源")
    args = parser.parse_args()
    main(source_filter=args.source, list_sources=args.list_sources)
