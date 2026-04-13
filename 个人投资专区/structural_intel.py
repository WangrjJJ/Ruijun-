#!/usr/bin/env python3
"""
BTC 结构性情报采集模块
=====================
采集价格之外的结构性供需数据：矿工经济、ETF资金流、Strategy持仓、OI、链上供应。
供 daily_brief.py 和 update_dashboard.py 调用。

数据源:
  - mempool.space (矿工, 免费无认证)
  - blockchain.info (链上, 免费无认证)
  - Binance futures (OI, 免费)
  - .etf_flows.json / .mstr_holdings.json (手动/缓存回退)
"""

import json
import os
import time
import ssl
import urllib.request
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ─── 常量 ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ETF_FILE = os.path.join(BASE_DIR, ".etf_flows.json")
MSTR_FILE = os.path.join(BASE_DIR, ".mstr_holdings.json")
CACHE_FILE = os.path.join(BASE_DIR, ".structural_cache.json")
CACHE_TTL = 300  # 5 min cache for API calls

MEMPOOL_BASE = "https://mempool.space/api"
BLOCKCHAIN_BASE = "https://blockchain.info"
BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"

TIMEOUT = 15  # seconds per request


# ─── 通用工具 ────────────────────────────────────────────────────────────

def _fetch_json(url, timeout=TIMEOUT):
    """GET JSON with SSL fallback, returns dict/list or None on failure."""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        # Retry without SSL verification (some China networks need this)
        try:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None


def _fetch_text(url, timeout=TIMEOUT):
    """GET raw text, returns str or None."""
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode().strip()
    except Exception:
        try:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode().strip()
        except Exception:
            return None


def _load_json_file(path):
    """Load a local JSON file, return dict or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json_file(path, data):
    """Save dict to local JSON file."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_mem_cache = {}
_cache_lock = threading.Lock()


def _cached_fetch(key, fetch_fn, ttl=CACHE_TTL):
    """Thread-safe in-memory cache. Falls back to fetch_fn on miss."""
    with _cache_lock:
        entry = _mem_cache.get(key)
        if entry and time.time() - entry.get("ts", 0) < ttl:
            return entry.get("data")
    # Release lock during slow fetch
    data = fetch_fn()
    if data is not None:
        with _cache_lock:
            _mem_cache[key] = {"ts": time.time(), "data": data}
    return data


# ─── 1. 矿工经济 (mempool.space) ────────────────────────────────────────

def fetch_miner_stats():
    """
    返回:
    {
        "hashrate_eh": float,          # EH/s
        "difficulty": float,           # 当前难度
        "diff_change_pct": float,      # 下次调整预期 %
        "diff_remaining_blocks": int,  # 距离调整剩余区块
        "diff_eta_date": str,          # 预计调整日期 YYYY-MM-DD
        "fee_economy": int,            # sat/vB economy fee
        "fee_fastest": int,            # sat/vB fastest fee
        "top_pools": [                 # Top 5 矿池
            {"name": str, "pct": float, "blocks": int},
        ],
        "source": "mempool.space"
    }
    """
    def _fetch():
        result = {"source": "mempool.space"}

        # Sequential fetch (outer fetch_all handles inter-source parallelism)
        hr_data = _fetch_json(f"{MEMPOOL_BASE}/v1/mining/hashrate/1m")
        diff_data = _fetch_json(f"{MEMPOOL_BASE}/v1/difficulty-adjustment")
        fee_data = _fetch_json(f"{MEMPOOL_BASE}/v1/fees/recommended")
        pool_data = _fetch_json(f"{MEMPOOL_BASE}/v1/mining/pools/1w")
        # Process results
        if hr_data:
            raw_hr = hr_data.get("currentHashrate", 0)
            result["hashrate_eh"] = round(raw_hr / 1e18, 1)
            result["difficulty"] = hr_data.get("currentDifficulty", 0)

        if diff_data:
            result["diff_change_pct"] = round(diff_data.get("difficultyChange", 0), 2)
            result["diff_remaining_blocks"] = diff_data.get("remainingBlocks", 0)
            eta_ms = diff_data.get("estimatedRetargetDate", 0)
            if eta_ms:
                result["diff_eta_date"] = datetime.fromtimestamp(eta_ms / 1000).strftime("%Y-%m-%d")

        if fee_data:
            result["fee_economy"] = fee_data.get("economyFee", 0)
            result["fee_fastest"] = fee_data.get("fastestFee", 0)

        if pool_data and "pools" in pool_data:
            pools = pool_data["pools"]
            total_blocks = sum(p.get("blockCount", 0) for p in pools)
            top5 = []
            for p in sorted(pools, key=lambda x: x.get("blockCount", 0), reverse=True)[:5]:
                bc = p.get("blockCount", 0)
                pct = round(bc / total_blocks * 100, 1) if total_blocks else 0
                top5.append({"name": p.get("name", "?"), "pct": pct, "blocks": bc})
            result["top_pools"] = top5

        return result if "hashrate_eh" in result else None

    return _cached_fetch("miner_stats", _fetch) or {}


# ─── 2. 链上供应 (blockchain.info) ───────────────────────────────────────

def fetch_onchain_supply():
    """
    返回:
    {
        "total_btc": float,            # 已挖出BTC总量
        "tx_count_24h": int,           # 24h交易数
        "hash_rate_gh": float,         # 算力 GH/s (备用源)
        "source": "blockchain.info"
    }
    """
    def _fetch():
        result = {"source": "blockchain.info"}

        total_sat = _fetch_text(f"{BLOCKCHAIN_BASE}/q/totalbc")
        if total_sat:
            try:
                result["total_btc"] = round(int(total_sat) / 1e8, 2)
            except ValueError:
                pass

        tx_count = _fetch_text(f"{BLOCKCHAIN_BASE}/q/24hrtransactioncount")
        if tx_count:
            try:
                result["tx_count_24h"] = int(tx_count)
            except ValueError:
                pass

        hr = _fetch_text(f"{BLOCKCHAIN_BASE}/q/hashrate")
        if hr:
            try:
                result["hash_rate_gh"] = float(hr)
            except ValueError:
                pass

        return result if len(result) > 1 else None

    return _cached_fetch("onchain_supply", _fetch) or {}


# ─── 3. ETF 资金流 (手动JSON回退) ────────────────────────────────────────

def fetch_etf_flows():
    """
    优先读取本地 .etf_flows.json (用户手动更新或自动脚本写入)。
    返回:
    {
        "date": str,                   # 数据日期
        "daily_net_m": float,          # 日净流入 $M
        "ibit_net": float,             # IBIT净流入 $M
        "fbtc_net": float,             # FBTC净流入 $M
        "gbtc_net": float,             # GBTC净流入 $M
        "cumulative_btc": int,         # ETF累计持仓 BTC
        "7d_net_m": float,             # 7天累计 $M
        "stale": bool,                 # 数据是否过期(>1天)
        "source": "local_json"
    }
    """
    data = _load_json_file(ETF_FILE)
    if not data:
        return {}

    data["source"] = "local_json"
    # Check staleness
    try:
        data_date = datetime.strptime(data.get("date", ""), "%Y-%m-%d")
        data["stale"] = (datetime.now() - data_date).days > 1
    except Exception:
        data["stale"] = True

    return data


# ─── 4. Strategy/MSTR 持仓 (缓存JSON) ───────────────────────────────────

def fetch_mstr_holdings():
    """
    读取本地 .mstr_holdings.json (7天TTL, 用户手动更新)。
    返回:
    {
        "updated": str,                # 更新日期
        "total_btc": int,              # 总持仓
        "avg_cost": float,             # 均价
        "total_cost_usd": int,         # 总成本 USD
        "pct_supply": float,           # 占总供应 %
        "last_purchase_btc": int,      # 最近一次买入量
        "last_purchase_date": str,     # 最近一次买入日期
        "last_purchase_price": float,  # 最近一次买入均价
        "stale": bool,                 # 数据>7天
        "source": "local_json"
    }
    """
    data = _load_json_file(MSTR_FILE)
    if not data:
        return {}

    data["source"] = "local_json"
    try:
        updated = datetime.strptime(data.get("updated", ""), "%Y-%m-%d")
        data["stale"] = (datetime.now() - updated).days > 7
    except Exception:
        data["stale"] = True

    return data


# ─── 5. 交易所流向代理 (Binance OI) ──────────────────────────────────────

def fetch_exchange_proxy():
    """
    用 Binance BTCUSDT 永续合约未平仓量作为市场杠杆代理。
    返回:
    {
        "oi_btc": float,               # OI (BTC)
        "oi_usd": float,               # OI (USD est.)
        "source": "binance_futures"
    }
    """
    def _fetch():
        data = _fetch_json(f"{BINANCE_FAPI}/openInterest?symbol=BTCUSDT")
        if data and "openInterest" in data:
            oi_btc = float(data["openInterest"])
            # Estimate USD value (need BTC price, use rough recent)
            price_data = _fetch_json(
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=bitcoin&vs_currencies=usd"
            )
            btc_price = 72000  # fallback
            if price_data and "bitcoin" in price_data:
                btc_price = price_data["bitcoin"].get("usd", 72000)
            return {
                "oi_btc": round(oi_btc, 2),
                "oi_usd": round(oi_btc * btc_price / 1e9, 2),  # in $B
                "source": "binance_futures",
            }
        return None

    return _cached_fetch("exchange_proxy", _fetch) or {}


# ─── 聚合 ────────────────────────────────────────────────────────────────

def fetch_all():
    """
    并行采集所有结构性数据，每个源独立失败。
    返回 dict with keys: miner, onchain, etf, mstr, oi
    """
    fetchers = {
        "miner": fetch_miner_stats,
        "onchain": fetch_onchain_supply,
        "etf": fetch_etf_flows,
        "mstr": fetch_mstr_holdings,
        "oi": fetch_exchange_proxy,
    }
    result = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fn): key for key, fn in fetchers.items()}
        for future in as_completed(futures, timeout=30):
            key = futures[future]
            try:
                result[key] = future.result()
            except Exception:
                result[key] = {}
    return result


# ─── 格式化输出 ──────────────────────────────────────────────────────────

def _fmt_num(n, unit="", decimals=0):
    """Format number with commas."""
    if n is None:
        return "N/A"
    if decimals == 0:
        return f"{int(n):,}{unit}"
    return f"{n:,.{decimals}f}{unit}"


def _stale_tag(data):
    return " ⚠️过期" if data.get("stale") else ""


def format_section(struct_data, history=None):
    """
    生成终端/邮件渲染文本。
    struct_data: fetch_all() 的返回
    history: 历史dict用于趋势比较 (optional)
    """
    lines = []
    lines.append("")
    lines.append("⑤ 结构性情报")

    # ── Miner ──
    m = struct_data.get("miner", {})
    if m:
        hr = m.get("hashrate_eh", 0)
        # Trend vs yesterday
        hr_trend = ""
        if history:
            prev_hr = history.get("hashrate_eh")
            if prev_hr and prev_hr > 0:
                chg = (hr - prev_hr) / prev_hr * 100
                arrow = "↑" if chg > 0 else "↓" if chg < 0 else "→"
                hr_trend = f" ({arrow}{abs(chg):.1f}%)"

        diff_str = ""
        if "diff_change_pct" in m:
            dc = m["diff_change_pct"]
            sign = "+" if dc >= 0 else ""
            remaining = m.get("diff_remaining_blocks", "?")
            eta = m.get("diff_eta_date", "?")
            diff_str = f"  难度调整 {sign}{dc}% ({remaining}块后, {eta})"

        fee_str = ""
        if "fee_economy" in m:
            fee_str = f"  费率 {m['fee_economy']} sat/vB"

        pool_str = ""
        if "top_pools" in m:
            parts = [f"{p['name']} {p['pct']}%" for p in m["top_pools"][:3]]
            pool_str = f"  Top3: {' | '.join(parts)}"

        lines.append(f"  ⛏️  矿工  算力 {hr} EH/s{hr_trend}{diff_str}")
        if fee_str or pool_str:
            lines.append(f"           {fee_str}{pool_str}")

    # ── ETF ──
    e = struct_data.get("etf", {})
    if e and e.get("date"):
        stale = _stale_tag(e)
        daily = e.get("daily_net_m")
        daily_str = f"${daily:+.0f}M" if daily is not None else "N/A"

        # Sub-ETF breakdown
        parts = []
        if e.get("ibit_net") is not None:
            parts.append(f"IBIT {e['ibit_net']:+.0f}")
        if e.get("fbtc_net") is not None:
            parts.append(f"FBTC {e['fbtc_net']:+.0f}")
        if e.get("gbtc_net") is not None:
            parts.append(f"GBTC {e['gbtc_net']:+.0f}")
        breakdown = f" ({' | '.join(parts)})" if parts else ""

        cum_btc = _fmt_num(e.get("cumulative_btc"))
        week_net = e.get("7d_net_m")
        week_str = f"${week_net:+.0f}M" if week_net is not None else "N/A"

        lines.append(f"  📊 ETF   日净流 {daily_str}{breakdown}{stale}")
        lines.append(f"            7天累计 {week_str}  ETF总持仓 {cum_btc} BTC")

    # ── MSTR ──
    mstr = struct_data.get("mstr", {})
    if mstr and mstr.get("total_btc"):
        stale = _stale_tag(mstr)
        total = _fmt_num(mstr["total_btc"])
        cost_b = round(mstr.get("total_cost_usd", 0) / 1e9, 1)
        avg = _fmt_num(mstr.get("avg_cost"), "$", 0)
        pct = mstr.get("pct_supply", 0)

        lines.append(f"  🏦 MSTR  持仓 {total} BTC (${cost_b}B)  均价 {avg}  占供应 {pct}%{stale}")

        lp_btc = mstr.get("last_purchase_btc")
        lp_date = mstr.get("last_purchase_date", "")
        lp_price = mstr.get("last_purchase_price")
        if lp_btc:
            price_str = f" @ ${lp_price:,.0f}" if lp_price else ""
            lines.append(f"            最近买入 {_fmt_num(lp_btc)} BTC{price_str} ({lp_date})")

    # ── OI ──
    oi = struct_data.get("oi", {})
    if oi and oi.get("oi_btc"):
        oi_btc = _fmt_num(oi["oi_btc"], decimals=0)
        oi_usd = oi.get("oi_usd", 0)

        oi_trend = ""
        if history:
            prev_oi = history.get("oi_btc")
            if prev_oi and prev_oi > 0:
                chg = (oi["oi_btc"] - prev_oi) / prev_oi * 100
                arrow = "↑" if chg > 0 else "↓" if chg < 0 else "→"
                oi_trend = f" (较昨日 {arrow}{abs(chg):.1f}%)"

        lines.append(f"  📈 OI    未平仓 {oi_btc} BTC (${oi_usd}B){oi_trend}")

    # ── Onchain ──
    oc = struct_data.get("onchain", {})
    if oc and oc.get("total_btc"):
        total = _fmt_num(oc["total_btc"], " BTC", 2)
        tx = _fmt_num(oc.get("tx_count_24h"))
        lines.append(f"  🔗 链上  已挖出 {total}  24h交易 {tx}")

    if len(lines) <= 1:
        lines.append("  ⚠️  所有数据源不可用")

    return "\n".join(lines)


# ─── 交叉信号 ────────────────────────────────────────────────────────────

def generate_structural_insights(struct_data, crypto_data=None, history=None):
    """
    基于结构性数据生成交叉信号。
    struct_data: fetch_all() 返回
    crypto_data: daily_brief 的 crypto dict (含 fear_greed, funding_rate, btc price)
    history: 前一天 snapshot
    返回 list of str (insight lines)
    """
    insights = []
    etf = struct_data.get("etf", {})
    mstr = struct_data.get("mstr", {})
    miner = struct_data.get("miner", {})
    oi = struct_data.get("oi", {})
    fg = None
    fr = None
    btc_price = None

    if crypto_data:
        fg_data = crypto_data.get("fear_greed", {})
        fg = fg_data.get("value") if isinstance(fg_data, dict) else fg_data
        fr = crypto_data.get("funding_rate")
        btc_data = crypto_data.get("btc", {})
        btc_price = btc_data.get("price") if isinstance(btc_data, dict) else None

    # S1: ETF逆势吸筹
    if etf.get("7d_net_m") and fg is not None:
        if etf["7d_net_m"] > 500 and fg < 25:
            insights.append(
                "⚡ [S1] ETF 7天净流入 >${:.0f}M + 恐贪{} → "
                "机构逆势吸筹，散户恐慌，中期偏多信号".format(
                    etf["7d_net_m"], fg
                )
            )

    # S2: ETF持续流出
    if etf.get("daily_net_m") is not None and etf["daily_net_m"] < -200:
        insights.append(
            "⚡ [S2] ETF 日净流出 ${:.0f}M → "
            "关注是否连续赎回，若持续3天以上为短期卖压信号".format(
                etf["daily_net_m"]
            )
        )

    # S3: MSTR大额买入
    if mstr.get("last_purchase_btc") and mstr.get("last_purchase_date"):
        try:
            lp_date = datetime.strptime(mstr["last_purchase_date"], "%Y-%m-%d")
            if (datetime.now() - lp_date).days <= 7 and mstr["last_purchase_btc"] > 5000:
                insights.append(
                    "⚡ [S3] Strategy 本周买入 {} BTC → "
                    "最大结构性买盘活跃，短期价格支撑增强".format(
                        _fmt_num(mstr["last_purchase_btc"])
                    )
                )
        except Exception:
            pass

    # S4: 算力高+费率低 = 矿工利润承压
    if miner.get("hashrate_eh") and miner.get("fee_economy") is not None:
        if miner["fee_economy"] < 5:
            # Check if hashrate is near ATH (use >900 EH/s as proxy)
            if miner["hashrate_eh"] > 900:
                insights.append(
                    "⚡ [S4] 算力 {} EH/s (高位) + 费率仅 {} sat/vB → "
                    "矿工利润承压，链上活跃度偏低".format(
                        miner["hashrate_eh"], miner["fee_economy"]
                    )
                )

    # S5: OI上升+价格下跌+负资金费率 = 空头挤压机会
    if oi.get("oi_btc") and history and btc_price and fr is not None:
        prev_oi = history.get("oi_btc")
        prev_price = history.get("btc_price")
        if prev_oi and prev_price:
            oi_chg = (oi["oi_btc"] - prev_oi) / prev_oi * 100
            price_chg = (btc_price - prev_price) / prev_price * 100
            if oi_chg > 5 and price_chg < 0 and fr < 0:
                insights.append(
                    "⚡ [S5] OI↑{:.1f}% + 价格↓{:.1f}% + 资金费率{:.4f}% → "
                    "空头大量建仓，潜在空头挤压机会".format(
                        oi_chg, price_chg, fr * 100
                    )
                )

    # S6: 大幅难度调整
    if miner.get("diff_change_pct") is not None:
        dc = miner["diff_change_pct"]
        if dc > 5:
            insights.append(
                "⚡ [S6] 难度预计上调 {:.1f}% → "
                "高成本矿工面临出局压力，关注矿工抛售".format(dc)
            )
        elif dc < -5:
            insights.append(
                "⚡ [S6] 难度预计下调 {:.1f}% → "
                "算力出走，生产成本下降，矿工卖压缓解".format(dc)
            )

    # S7: MSTR均价高于当前价 = 浮亏
    if mstr.get("avg_cost") and btc_price:
        if btc_price < mstr["avg_cost"]:
            discount = (mstr["avg_cost"] - btc_price) / mstr["avg_cost"] * 100
            insights.append(
                "⚡ [S7] BTC ${:,.0f} < MSTR均价 ${:,.0f} (浮亏{:.1f}%) → "
                "ATM飞轮承压，关注MSTR NAV折价是否扩大".format(
                    btc_price, mstr["avg_cost"], discount
                )
            )

    return insights


# ─── snapshot 扩展字段 ────────────────────────────────────────────────────

def to_snapshot_fields(struct_data):
    """
    从 fetch_all() 提取需要持久化到 history 的字段。
    返回 flat dict (所有值为 scalar 或 None)。
    """
    m = struct_data.get("miner", {})
    e = struct_data.get("etf", {})
    mstr = struct_data.get("mstr", {})
    oi = struct_data.get("oi", {})

    return {
        "hashrate_eh": m.get("hashrate_eh"),
        "difficulty_change": m.get("diff_change_pct"),
        "fee_rate": m.get("fee_economy"),
        "etf_daily_net_m": e.get("daily_net_m"),
        "etf_7d_net_m": e.get("7d_net_m"),
        "mstr_total_btc": mstr.get("total_btc"),
        "mstr_avg_cost": mstr.get("avg_cost"),
        "oi_btc": oi.get("oi_btc"),
    }


# ─── 周报格式化 ──────────────────────────────────────────────────────────

def format_weekly_section(struct_data, btc_price=None):
    """
    生成 Markdown 周报板块文本。
    """
    lines = []
    lines.append("## 结构性情报")
    lines.append("")

    # Miner
    m = struct_data.get("miner", {})
    if m:
        lines.append("### 矿工经济")
        hr = m.get("hashrate_eh", "N/A")
        lines.append(f"- 算力: {hr} EH/s")
        if "diff_change_pct" in m:
            dc = m["diff_change_pct"]
            sign = "+" if dc >= 0 else ""
            eta = m.get("diff_eta_date", "N/A")
            lines.append(f"- 下次难度调整: {sign}{dc}% (预计{eta})")
        if "fee_economy" in m:
            label = "极低" if m["fee_economy"] <= 2 else "偏低" if m["fee_economy"] <= 10 else "正常" if m["fee_economy"] <= 30 else "偏高"
            lines.append(f"- 平均费率: {m['fee_economy']} sat/vB ({label})")
        if "top_pools" in m:
            parts = [f"{p['name']} {p['pct']}%" for p in m["top_pools"][:3]]
            lines.append(f"- Top3矿池: {', '.join(parts)}")
        lines.append("")

    # ETF
    e = struct_data.get("etf", {})
    if e and e.get("date"):
        lines.append("### ETF资金流")
        stale = " (⚠️数据过期)" if e.get("stale") else ""
        daily = e.get("daily_net_m")
        if daily is not None:
            lines.append(f"- 最新日净流: ${daily:+.0f}M{stale}")
        week = e.get("7d_net_m")
        if week is not None:
            direction = "净流入" if week > 0 else "净流出"
            lines.append(f"- 7天累计: ${week:+.0f}M ({direction})")
        cum = e.get("cumulative_btc")
        if cum:
            lines.append(f"- ETF累计持仓: {cum:,} BTC")
        lines.append("")

    # MSTR
    mstr = struct_data.get("mstr", {})
    if mstr and mstr.get("total_btc"):
        lines.append("### Strategy (MSTR)")
        total = mstr["total_btc"]
        avg = mstr.get("avg_cost", 0)
        stale = " (⚠️数据过期)" if mstr.get("stale") else ""
        lines.append(f"- 持仓: {total:,} BTC | 均价 ${avg:,.0f}{stale}")
        lp = mstr.get("last_purchase_btc")
        lp_d = mstr.get("last_purchase_date", "")
        lp_p = mstr.get("last_purchase_price")
        if lp:
            p_str = f" @ ${lp_p:,.0f}" if lp_p else ""
            lines.append(f"- 最近买入: {lp:,} BTC{p_str} ({lp_d})")
        # NAV comparison
        if btc_price and avg:
            nav_pct = (btc_price - avg) / avg * 100
            label = "溢价" if nav_pct > 0 else "折价"
            lines.append(f"- 当前价 vs 均价: {label} {abs(nav_pct):.1f}%")
        lines.append("")

    return "\n".join(lines)


# ─── CLI 测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    print("正在采集结构性数据...")
    data = fetch_all()

    if "--json" in sys.argv:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(format_section(data))
        print()
        insights = generate_structural_insights(data)
        if insights:
            print("结构性交叉信号:")
            for i in insights:
                print(f"  {i}")
        else:
            print("(暂无触发的结构性信号)")
