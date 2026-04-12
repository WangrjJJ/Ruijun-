#!/usr/bin/env python3
"""
个人日报系统 (Personal Daily Brief)
资产信号 × 公司雷达 × OPC/AI动态 → 终端 + 邮件推送

运行方式:
  python3 daily_brief.py

定时: LaunchAgent 每天 07:30 触发
邮件: 自动发送至 121685816@qq.com
凭证: ~/.daily_brief_secrets.json（chmod 600，不入git）

依赖:
  pip3 install requests akshare pandas
"""

import sys
import io
import json
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
    print("[ERROR] 请运行: pip3 install akshare pandas requests")
    sys.exit(1)

# ============================================================
# 配置区 — 双币到期日手动维护（每次滚动后更新）
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

# 今日行动项 — 手动维护，完成后删除，新增直接加
ACTION_ITEMS = [
    "月度提现 $3,630 ≈ ¥25,000 待执行（Q1已过0提现）",
    "D池定投：工资日 ¥5,000-8,000 → USDT",
]

# 每日思考题（按星期几轮换，0=周一）
DAILY_QUESTIONS = [
    "如果明天有人付 ¥5,000 请你解决一个问题，会是什么问题？",          # 周一
    "你的哪项能力，在 AI 加持下可以服务 10 个以上付费客户？",           # 周二
    "本周接触的信息中，哪个让你感到「这个我能做更好」？",                # 周三
    "OPC 最大的障碍：技术 / 销售 / 信心 / 时间，哪个排第一？",         # 周四
    "如果做一个面向制造业的 AI 工具，最容易验证的第一个功能是什么？",   # 周五
    "BTC 策略当前能支撑多少个月基本开销？这个数字让你感觉如何？",       # 周六
    "下周可以做哪一个最小实验来测试 OPC 方向的可行性？",                # 周日
]

# HN 搜索关键词（两类）
HN_QUERIES = {
    "AI工具·咨询/运营颠覆": [
        "AI consulting automation",
        "AI management strategy tool",
        "AI agent B2B workflow",
        "replacing management consultants AI",
    ],
    "OPC·独立变现线索": [
        "Show HN supply chain SaaS",
        "manufacturing analytics solo",
        "B2B automation indie founder",
        "industrial AI tool revenue",
    ],
}


# ============================================================
# 数据获取
# ============================================================

def fetch_crypto() -> dict:
    """BTC/ETH 价格 + 恐贪指数"""
    result = {}
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin,ethereum",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=12,
        )
        data = r.json()
        result["btc"] = {
            "price":     data["bitcoin"]["usd"],
            "change_24h": data["bitcoin"]["usd_24h_change"],
        }
        result["eth"] = {
            "price":     data["ethereum"]["usd"],
            "change_24h": data["ethereum"]["usd_24h_change"],
        }
        result["eth_btc"] = result["eth"]["price"] / result["btc"]["price"]
    except Exception as e:
        result["crypto_err"] = str(e)

    try:
        r2 = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        fng = r2.json()["data"][0]
        result["fear_greed"] = {
            "value": int(fng["value"]),
            "label": fng["value_classification"],
        }
    except Exception:
        result["fear_greed"] = None

    return result


def fetch_company_radar() -> dict:
    """中集环科(301559) + 胜狮景气度(00716) + 钢材上游信号"""
    result = {}

    # 中集环科 A 股（Sina Finance接口，绕过eastmoney代理问题）
    try:
        df = ak.stock_zh_a_daily(symbol="sz301559", adjust="")
        if not df.empty:
            df = df.sort_values("date")
            row = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None
            close = float(row["close"])
            change_pct = ((close / float(prev["close"])) - 1) * 100 if prev is not None else None
            result["zjhk"] = {
                "price":      close,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "date":       str(row["date"])[:10],
            }
        else:
            result["zjhk"] = {"err": "empty"}
    except Exception as e:
        result["zjhk"] = {"err": str(e), "show": True}

    # 胜狮（行业景气度指标，非主竞品）
    try:
        df_hk = ak.stock_hk_daily(symbol="00716", adjust="")
        if not df_hk.empty:
            df_hk["date"] = pd.to_datetime(df_hk["date"]).dt.date
            cutoff = (datetime.now() - timedelta(days=90)).date()
            df_hk = df_hk[df_hk["date"] >= cutoff].sort_values("date")
            cur   = float(df_hk["close"].iloc[-1])
            p3m   = float(df_hk["close"].iloc[0])
            result["singamas"] = {
                "price":    cur,
                "trend_3m": round((cur / p3m - 1) * 100, 1),
            }
    except Exception as e:
        result["singamas"] = {"err": str(e)}

    # 钢材上游信号（铁矿石 I0 + 焦炭 J0 驱动，HC0 终端参考）
    try:
        up_trends  = []
        steel_rows = []
        for sym, name in [("I0", "铁矿石"), ("J0", "焦炭"), ("HC0", "热轧卷")]:
            df_f = ak.futures_main_sina(
                symbol=sym,
                start_date=(datetime.now() - timedelta(days=45)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
            )
            if df_f.empty:
                continue
            df_f = df_f.sort_values("日期")
            cur  = float(df_f["收盘价"].iloc[-1])
            p30  = float(df_f["收盘价"].iloc[max(0, len(df_f) - 22)])
            t30  = round((cur / p30 - 1) * 100, 1)
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

        result["steel"] = {
            "signal": sig,
            "detail": "  ".join(steel_rows),
        }
    except Exception as e:
        result["steel"] = {"signal": f"获取失败: {e}", "detail": ""}

    return result


def fetch_hn_intel() -> dict:
    """HN Algolia：AI工具 + OPC变现线索（近7天，按相关性排序）"""
    ts_cutoff = int((datetime.now() - timedelta(days=30)).timestamp())
    output = {}

    for category, queries in HN_QUERIES.items():
        seen, items = set(), []
        for q in queries[:2]:          # 每类取前2条查询，控制耗时
            try:
                r = requests.get(
                    "https://hn.algolia.com/api/v1/search",   # 按相关性，而非纯时间
                    params={
                        "query": q,
                        "tags":  "story",
                        "numericFilters": f"created_at_i>{ts_cutoff}",
                        "hitsPerPage": 5,
                    },
                    timeout=10,
                )
                for h in r.json().get("hits", []):
                    title = h.get("title", "").strip()
                    if not title or title in seen:
                        continue
                    if h.get("points", 0) < 2:      # 降低门槛至2分
                        continue
                    seen.add(title)
                    hn_url = f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"
                    items.append({
                        "title":  title,
                        "points": h.get("points", 0),
                        "url":    h.get("url") or hn_url,
                    })
                time.sleep(0.3)
            except Exception:
                pass

        items.sort(key=lambda x: x["points"], reverse=True)
        output[category] = items[:3]

    return output


# ============================================================
# 终端渲染
# ============================================================

def _chg(pct, decimals=2):
    if pct is None:
        return "—"
    arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
    return f"{arrow}{abs(pct):.{decimals}f}%"


def print_brief():
    now = datetime.now()
    wd  = now.weekday()
    wnames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    W = 62
    print()
    print("=" * W)
    print(f"  王瑞俊 · 每日简报  {now.strftime('%Y-%m-%d')} {wnames[wd]}")
    print("=" * W)

    # ── ① 资产信号 ──────────────────────────────────────────
    print("\n① 资产信号")
    crypto = fetch_crypto()

    if "crypto_err" not in crypto:
        btc = crypto.get("btc", {})
        eth = crypto.get("eth", {})
        fg  = crypto.get("fear_greed")
        eth_btc = crypto.get("eth_btc", 0)

        fg_str = f"{fg['value']}（{fg['label']}）" if fg else "—"
        print(f"  BTC  ${btc.get('price', 0):>9,.0f}  {_chg(btc.get('change_24h')):<10}"
              f"  恐贪指数 {fg_str}")
        print(f"  ETH  ${eth.get('price', 0):>9,.0f}  {_chg(eth.get('change_24h')):<10}"
              f"  ETH/BTC  {eth_btc:.5f}")
    else:
        print(f"  ⚠️  价格获取失败: {crypto['crypto_err']}")

    if DUAL_CURRENCY:
        print()
        for dc in DUAL_CURRENCY:
            expiry_dt = datetime.strptime(dc["expiry"], "%Y-%m-%d")
            days_left = (expiry_dt.date() - now.date()).days
            warn = "⚠️  " if days_left <= 3 else "📅  "
            strike_str = f"${dc['strike']:,}"
            print(f"  {warn}{dc['type']:<10} {strike_str:<10}  "
                  f"{dc['amount']:<22} 到期 {dc['expiry']}（{days_left}天）")

    # ── ② 公司雷达 ──────────────────────────────────────────
    print("\n② 公司雷达")
    company = fetch_company_radar()

    zjhk = company.get("zjhk", {})
    if "err" not in zjhk:
        chg_str = f"  {_chg(zjhk.get('change_pct'))}" if zjhk.get("change_pct") is not None else ""
        date_str = f"（{zjhk['date']}）" if zjhk.get("date") else ""
        print(f"  中集环科 301559.SZ      ¥{zjhk.get('price', 0):.2f}{chg_str}  {date_str}")
    else:
        err_detail = f"  ({zjhk['err']})" if zjhk.get("show") else ""
        print(f"  中集环科 301559.SZ      获取失败{err_detail}")

    sg = company.get("singamas", {})
    if "err" not in sg:
        print(f"  胜狮（行业景气指标）    HK${sg.get('price', 0):.2f}"
              f"  近3月 {_chg(sg.get('trend_3m'), 1)}")
    else:
        print(f"  胜狮 00716.HK           获取失败")

    steel = company.get("steel", {})
    print(f"  钢材上游信号            {steel.get('signal', '—')}")
    if steel.get("detail"):
        print(f"                          {steel['detail']}")

    # ── ③ OPC / AI 动态 ─────────────────────────────────────
    print("\n③ OPC机会 & AI工具动态（HN 近30天·按相关性）")
    hn = fetch_hn_intel()

    for cat, items in hn.items():
        print(f"\n  【{cat}】")
        if items:
            for it in items:
                title = it["title"]
                if len(title) > 56:
                    title = title[:53] + "..."
                print(f"  · {title}  [{it['points']}↑]")
        else:
            print("  · 暂无高热度相关内容（36h内）")

    q = DAILY_QUESTIONS[wd]
    print(f"\n  💡 今日一问：\n     {q}")

    # ── ④ 行动项 ────────────────────────────────────────────
    if ACTION_ITEMS:
        print("\n④ 今日行动项")
        for item in ACTION_ITEMS:
            print(f"  ○ {item}")

    print()
    print("─" * W)
    print(f"  {now.strftime('%H:%M:%S')} | CoinGecko · akshare · HN Algolia")
    print("=" * W)
    print()


# ============================================================
# 邮件推送
# ============================================================

def load_secrets() -> dict:
    path = os.path.expanduser("~/.daily_brief_secrets.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def send_email(content: str, subject: str):
    """通过 QQ SMTP 发送纯文本邮件"""
    cfg = load_secrets()
    if not cfg:
        print("[WARN] 未找到 ~/.daily_brief_secrets.json，跳过邮件发送")
        return

    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"]    = cfg["smtp_user"]
    msg["To"]      = cfg["mail_to"]

    try:
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], timeout=15) as smtp:
            smtp.login(cfg["smtp_user"], cfg["smtp_pass"])
            smtp.sendmail(cfg["smtp_user"], [cfg["mail_to"]], msg.as_string())
        print(f"[邮件] 已发送至 {cfg['mail_to']}")
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")


if __name__ == "__main__":
    now = datetime.now()
    wnames = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    subject = (
        f"每日简报 {now.strftime('%Y-%m-%d')} {wnames[now.weekday()]}"
    )

    # 捕获终端输出，同时打印 + 发邮件
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_brief()
    content = buf.getvalue()

    sys.stdout.write(content)   # 打印到终端（LaunchAgent日志）
    send_email(content, subject)
