# -*- coding: utf-8 -*-
"""
BTC投资策略看板 - 数据更新脚本（Mac版）
每周一 12:00 自动运行，拉取实时数据、更新HTML看板、生成周报、微信推送
"""
import json
import os
import re
import ssl
import smtplib
import subprocess
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl._create_unverified_context()

# ========== 路径配置（Mac） ==========
VAULT_DIR = os.path.expanduser('~/Documents/Ruijun的知识库')
INVEST_DIR = os.path.join(VAULT_DIR, '个人投资专区')
HTML_PATH = os.path.join(INVEST_DIR, '策略看板.html')
ARCHIVE_DIR = os.path.join(INVEST_DIR, '周报归档')

# ========== 邮件通知配置（QQ邮箱） ==========
# 获取授权码：QQ邮箱 → 设置 → 账户 → POP3/IMAP/SMTP服务 → 开启 → 生成授权码
EMAIL_SENDER   = '121685816@qq.com'
EMAIL_AUTH_CODE = 'fbaxdebrknvobgeh'   # QQ邮箱SMTP授权码
EMAIL_RECEIVER = '121685816@qq.com'
EMAIL_ENABLED  = EMAIL_AUTH_CODE != 'xxxxxxxxxxxxxxxx'

# ========== WxPusher 微信推送配置 ==========
# 注册步骤：https://wxpusher.zjiecode.com
# 1. 扫码关注"WxPusher消息推送平台"公众号
# 2. 登录后台创建应用，获取 APP_TOKEN
# 3. 在"用户管理"页面获取你的 UID
WXPUSHER_APP_TOKEN = 'AT_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'  # ← 替换为你的 AppToken
WXPUSHER_UID = 'UID_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'       # ← 替换为你的 UID
WXPUSHER_ENABLED = WXPUSHER_APP_TOKEN != 'AT_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

# ========== 持仓配置（每次买卖BTC后手动更新） ==========
TOTAL_BTC = 2.83      # 当前实际BTC持仓
POOL_A_PCT = 0.35
POOL_B_PCT = 0.50
POOL_C_PCT = 0.15

# ========== 当周双币理财持仓（每周更新） ==========
# 每周一结算后更新以下参数，驱动自动分析
USDT_AVAILABLE   = 140000   # 当前可用USDT（用于Buy Low）
BTC_SELL_HIGH    = 2.26     # 当前用于Sell High的BTC数量
BUY_LOW_STRIKE   = 69500    # 当前Buy Low行权价（0=未设置）
SELL_HIGH_STRIKE = 74000    # 当前Sell High行权价（0=未设置）
EXPIRY_DATE      = '2026-04-18'  # 当前到期日
YTD_WITHDRAWN_CNY = 0       # 年度累计已提现人民币（元）

# ========== 策略参数 ==========
GRID_RANGE = 0.15         # 网格区间 ±15%
C_POOL_TRIGGER = 40000    # C池抄底触发价
D_POOL_TRIGGER_1 = 55000  # D池第一档触发价
D_POOL_TRIGGER_2 = 45000  # D池第二档触发价

# ========== 现金流 ==========
ANNUAL_TARGET_CNY = 300000


# ==================== 行权价计算 ====================

def get_strike_step(price):
    if price < 20000: return 500
    elif price < 50000: return 1000
    elif price < 100000: return 1000
    else: return 2000

def snap_to_strike(price, direction='up'):
    step = get_strike_step(price)
    if direction == 'up':
        return int((price // step + 1) * step)
    else:
        return int((price // step) * step)

def find_sell_high_strikes(price):
    step = get_strike_step(price)
    a_target = price * 1.12
    a_strike = int(round(a_target / step) * step)
    while a_strike < price * 1.08: a_strike += step
    if a_strike > price * 1.18: a_strike -= step

    b_target = price * 1.18
    b_strike = int(round(b_target / step) * step)
    while b_strike <= a_strike: b_strike += step
    if b_strike > price * 1.25: b_strike -= step

    buy_low_target_raw = price * 0.88
    buy_low_target = int(round(buy_low_target_raw / step) * step)
    while buy_low_target > price * 0.92: buy_low_target -= step

    return a_strike, b_strike, buy_low_target


# ==================== 数据获取 ====================

def fetch_json(url, timeout=10):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (URLError, Exception) as e:
        print(f'  [WARN] 请求失败 {url}: {e}')
        return None

CACHE_PATH = os.path.join(INVEST_DIR, '.price_cache.json')

def save_cache(data):
    try:
        with open(CACHE_PATH, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

def load_cache():
    try:
        with open(CACHE_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return None

def get_btc_price():
    print('获取BTC价格...')
    data = fetch_json(
        'https://api.coingecko.com/api/v3/simple/price'
        '?ids=bitcoin,tether&vs_currencies=usd,cny'
        '&include_24hr_change=true&include_7d_change=true'
    )
    if data and 'bitcoin' in data:
        btc = data['bitcoin']
        usdt_cny = data.get('tether', {}).get('cny', 6.90)
        result = {
            'btc_price_usd': round(btc.get('usd', 0)),
            'btc_24h_change': round(btc.get('usd_24h_change', 0), 1),
            'btc_7d_change': round(btc.get('usd_7d_change', 0), 1),
            'usdt_cny_rate': round(usdt_cny, 2),
            'source': 'CoinGecko',
        }
        save_cache(result)
        return result

    print('  CoinGecko失败，尝试Binance...')
    data = fetch_json('https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT')
    if data:
        price = float(data.get('lastPrice', 0))
        change = float(data.get('priceChangePercent', 0))
        result = {
            'btc_price_usd': round(price),
            'btc_24h_change': round(change, 1),
            'btc_7d_change': 0,
            'usdt_cny_rate': 6.90,
            'source': 'Binance',
        }
        save_cache(result)
        return result

    print('  所有API失败，使用离线缓存...')
    cached = load_cache()
    if cached:
        cached['source'] = '离线缓存'
        return cached

    return {
        'btc_price_usd': 71500,
        'btc_24h_change': 0,
        'btc_7d_change': 0,
        'usdt_cny_rate': 6.90,
        'source': '兜底数据',
    }

def get_eth_data():
    """获取ETH价格、ETH/BTC比值及30/90日历史区间"""
    print('获取ETH数据...')
    result = {'eth_price_usd': 0, 'eth_btc': 0,
              'eth_30d_low': 0, 'eth_30d_high': 0,
              'eth_90d_low': 0, 'eth_90d_high': 0, 'eth_90d_pct': 50}

    # 当前价格
    data = fetch_json(
        'https://api.coingecko.com/api/v3/simple/price'
        '?ids=ethereum&vs_currencies=usd,btc&include_24hr_change=true'
    )
    if data and 'ethereum' in data:
        result['eth_price_usd'] = round(data['ethereum'].get('usd', 0))
        result['eth_btc'] = round(data['ethereum'].get('btc', 0), 5)
        result['eth_24h_change'] = round(data['ethereum'].get('usd_24h_change', 0), 1)

    # 90日历史（含30日）
    hist = fetch_json(
        'https://api.coingecko.com/api/v3/coins/ethereum/market_chart'
        '?vs_currency=btc&days=90&interval=daily'
    )
    if hist and 'prices' in hist:
        prices = [p[1] for p in hist['prices']]
        if len(prices) >= 30:
            result['eth_30d_low']  = round(min(prices[-30:]), 5)
            result['eth_30d_high'] = round(max(prices[-30:]), 5)
        result['eth_90d_low']  = round(min(prices), 5)
        result['eth_90d_high'] = round(max(prices), 5)
        rng = result['eth_90d_high'] - result['eth_90d_low']
        cur = result['eth_btc']
        result['eth_90d_pct'] = round((cur - result['eth_90d_low']) / rng * 100) if rng > 0 else 50
        # 30日振幅（%）
        result['eth_30d_range_pct'] = round(
            (result['eth_30d_high'] - result['eth_30d_low']) / result['eth_30d_low'] * 100, 1
        ) if result['eth_30d_low'] > 0 else 0

    return result


def get_fear_greed():
    print('获取恐贪指数...')
    data = fetch_json('https://api.alternative.me/fng/?limit=1')
    if data and 'data' in data and len(data['data']) > 0:
        fg = data['data'][0]
        val = int(fg.get('value', 50))
        label_map = {(0,25):'极度恐惧',(25,45):'恐惧',(45,55):'中性',(55,75):'贪婪',(75,101):'极度贪婪'}
        label = next((lbl for (lo,hi),lbl in label_map.items() if lo<=val<hi), '中性')
        return val, label
    return 50, '中性'


# ==================== 策略计算 ====================

def calc_strategy(price, usdt_cny):
    a_btc = round(TOTAL_BTC * POOL_A_PCT, 2)
    b_btc = round(TOTAL_BTC * POOL_B_PCT, 2)
    c_btc = round(TOTAL_BTC * POOL_C_PCT, 2)

    a_strike, b_strike, buy_low = find_sell_high_strikes(price)
    step = get_strike_step(price)
    grid_low = snap_to_strike(price * (1 - GRID_RANGE), 'down')
    grid_high = snap_to_strike(price * (1 + GRID_RANGE), 'up')

    monthly_usdt = round(ANNUAL_TARGET_CNY / 12 / usdt_cny)
    monthly_cny = round(ANNUAL_TARGET_CNY / 12)

    a_premium_pct = round((a_strike / price - 1) * 100, 1)
    b_premium_pct = round((b_strike / price - 1) * 100, 1)
    buy_low_disc_pct = round((1 - buy_low / price) * 100, 1)

    base_apy_a = round(max(8, min(30, 32 - a_premium_pct * 1.2)), 1)
    base_apy_b = round(max(6, min(25, 32 - b_premium_pct * 1.2)), 1)

    now = datetime.now()
    months_elapsed = now.month - 1

    risk_signals = [
        {
            'name': 'BTC价格',
            'condition': f'< ${C_POOL_TRIGGER:,}',
            'current': '危险' if price < C_POOL_TRIGGER else ('警告' if price < D_POOL_TRIGGER_1 else '正常'),
            'level': 'danger' if price < C_POOL_TRIGGER else ('warn' if price < D_POOL_TRIGGER_1 else 'ok'),
            'action': f'当前${price:,}，距首档触发线{round((price/D_POOL_TRIGGER_1-1)*100)}%'
        },
        {
            'name': '波动率IV',
            'condition': '> 60%',
            'current': '偏高' if price < 70000 else '正常',
            'level': 'warn' if price < 70000 else 'ok',
            'action': '利好卖期权，权利金收入增加' if price < 70000 else '权利金收入正常水平'
        },
    ]

    a_strike_alt = a_strike + step
    b_strike_alt = b_strike - step

    recs = [
        f'A池 Sell High：行权价 ${a_strike:,}(+{a_premium_pct}%) 或 ${a_strike_alt:,}, 周期14天, APY {base_apy_a}%',
        f'B池 Sell High：行权价 ${b_strike:,}(+{b_premium_pct}%) 或 ${b_strike_alt:,}, 周期30天, APY {base_apy_b}%',
        f'Buy Low参考：${buy_low:,}(-{buy_low_disc_pct}%)；网格区间 ${grid_low:,}-${grid_high:,}',
    ]
    if price < D_POOL_TRIGGER_1:
        recs.append(f'⚠️ D池触发警告：BTC跌破${D_POOL_TRIGGER_1:,}，考虑启动第一档抄底')
    if YTD_WITHDRAWN_CNY < monthly_cny * months_elapsed:
        lag = months_elapsed - round(YTD_WITHDRAWN_CNY / monthly_cny)
        recs.append(f'⚠️ 月度提现滞后{lag}个月！建议本周P2P出金${monthly_usdt:,} USDT(≈¥{monthly_cny:,})')
    else:
        recs.append(f'月度提现正常，下次{now.month+1}月初提取${monthly_usdt:,} USDT')

    return {
        'strike_step': step,
        'pools': {
            'A': {'name': 'A池-现金流', 'btc': a_btc, 'pct': round(POOL_A_PCT*100),
                  'strategy': 'Sell High', 'strike': a_strike, 'strike_alt': a_strike_alt,
                  'premium_pct': a_premium_pct, 'tenor': '14天', 'apy': base_apy_a,
                  'buy_low_target': buy_low, 'buy_low_disc_pct': buy_low_disc_pct, 'status': '运行中'},
            'B': {'name': 'B池-增币', 'btc': b_btc, 'pct': round(POOL_B_PCT*100),
                  'strategy': 'Sell High远期+网格', 'strike': b_strike, 'strike_alt': b_strike_alt,
                  'premium_pct': b_premium_pct, 'tenor': '30天', 'apy': base_apy_b,
                  'grid_low': grid_low, 'grid_high': grid_high, 'status': '运行中'},
            'C': {'name': 'C池-储备', 'btc': c_btc, 'pct': round(POOL_C_PCT*100),
                  'strategy': '冷存储', 'status': '安全锁定'},
        },
        'cashflow': {
            'annual_target_cny': ANNUAL_TARGET_CNY,
            'ytd_withdrawn_cny': YTD_WITHDRAWN_CNY,
            'monthly_target_usdt': monthly_usdt,
            'monthly_target_cny': monthly_cny,
            'months_elapsed': months_elapsed,
        },
        'recommendations': recs,
        'risk_signals': risk_signals,
    }


# ==================== 双币决策分析 ====================

def analyze_buy_low(btc_price, fg_val, eth_data):
    """分析 Buy Low 决策：基于当前BTC价格、恐贪指数、持仓参数"""
    if USDT_AVAILABLE <= 0 or BUY_LOW_STRIKE <= 0:
        return None

    discount_pct = round((1 - BUY_LOW_STRIKE / btc_price) * 100, 1)
    btc_if_exercised = round(USDT_AVAILABLE / BUY_LOW_STRIKE, 3)
    btc_at_market    = round(USDT_AVAILABLE / btc_price, 3)
    extra_btc        = round(btc_if_exercised - btc_at_market, 3)

    # 概率估算：基于折价幅度 vs 7天1-sigma（年化波动率40%估算）
    sigma_7d = btc_price * 0.40 * (7/365) ** 0.5
    z_score  = abs(btc_price - BUY_LOW_STRIKE) / sigma_7d
    # 粗略正态分布CDF近似
    import math
    prob_triggered = round(0.5 * math.erfc(z_score / 2 ** 0.5) * 100, 0)

    # 年化收益率估算（基于折价幅度和IV约40%）
    est_apy_low  = max(15, round(discount_pct * 6))
    est_apy_high = max(25, round(discount_pct * 9))

    # 综合建议
    if discount_pct >= 8:
        suggestion = '行权价偏保守，触达概率极低，建议上调至折价4-6%'
        action = 'adjust'
    elif discount_pct <= 2:
        suggestion = '行权价偏激进，被行权概率过高（>50%），请确认愿意接BTC'
        action = 'caution'
    else:
        suggestion = '执行。两种结果均为正期望：未触发赚权利金，触发折价买BTC'
        action = 'execute'

    return {
        'usdt': USDT_AVAILABLE,
        'strike': BUY_LOW_STRIKE,
        'discount_pct': discount_pct,
        'btc_if_exercised': btc_if_exercised,
        'btc_at_market': btc_at_market,
        'extra_btc': extra_btc,
        'prob_triggered': int(prob_triggered),
        'est_apy_low': est_apy_low,
        'est_apy_high': est_apy_high,
        'suggestion': suggestion,
        'action': action,
        'expiry': EXPIRY_DATE,
    }


def analyze_sell_high(btc_price, fg_val):
    """分析 Sell High 决策：基于当前BTC价格、恐贪指数、持仓参数"""
    if BTC_SELL_HIGH <= 0 or SELL_HIGH_STRIKE <= 0:
        return None

    premium_pct   = round((SELL_HIGH_STRIKE / btc_price - 1) * 100, 1)
    usd_if_exercised = round(BTC_SELL_HIGH * SELL_HIGH_STRIKE)
    usd_at_market    = round(BTC_SELL_HIGH * btc_price)
    price_gain       = usd_if_exercised - usd_at_market

    import math
    sigma_7d  = btc_price * 0.40 * (7/365) ** 0.5
    z_score   = abs(SELL_HIGH_STRIKE - btc_price) / sigma_7d
    prob_exercised = round(0.5 * math.erfc(z_score / 2 ** 0.5) * 100, 0)

    est_apy_low  = max(10, round(premium_pct * 4))
    est_apy_high = max(20, round(premium_pct * 7))

    # 推荐行权价（A池+15%，B池+19%）
    step = get_strike_step(btc_price)
    rec_a = snap_to_strike(btc_price * 1.15, 'up')
    rec_b = snap_to_strike(btc_price * 1.19, 'up')

    if premium_pct < 3:
        suggestion = f'行权价过近（+{premium_pct}%），被行权概率>{100-int(prob_exercised)}%，建议上调至 ${rec_a:,}(+15%) 或 ${rec_b:,}(+19%)'
        action = 'adjust'
    elif premium_pct > 25:
        suggestion = f'行权价偏远（+{premium_pct}%），被行权概率极低，权利金收入有限'
        action = 'caution'
    else:
        suggestion = f'参数合理，执行。建议备选：A池 ${rec_a:,}(+15%) / B池 ${rec_b:,}(+19%)'
        action = 'execute'

    return {
        'btc': BTC_SELL_HIGH,
        'strike': SELL_HIGH_STRIKE,
        'premium_pct': premium_pct,
        'usd_if_exercised': usd_if_exercised,
        'usd_at_market': usd_at_market,
        'price_gain': price_gain,
        'prob_exercised': int(prob_exercised),
        'est_apy_low': est_apy_low,
        'est_apy_high': est_apy_high,
        'rec_strike_a': rec_a,
        'rec_strike_b': rec_b,
        'suggestion': suggestion,
        'action': action,
        'expiry': EXPIRY_DATE,
    }


def analyze_eth_btc_grid(eth_data, btc_price):
    """分析 ETH/BTC 网格策略可行性"""
    cur = eth_data.get('eth_btc', 0)
    if cur == 0:
        return None

    low_90  = eth_data.get('eth_90d_low', 0)
    high_90 = eth_data.get('eth_90d_high', 0)
    pct_90  = eth_data.get('eth_90d_pct', 50)
    range_30 = eth_data.get('eth_30d_range_pct', 0)

    # 建议网格区间（历史低点留10%余量 ~ 历史高点）
    rec_low  = round(low_90 * 0.90, 4)
    rec_high = round(high_90 * 1.02, 4)

    # 可行性评分（100分）
    score = 50
    score_notes = []
    if range_30 >= 5:
        score += 20
        score_notes.append(f'30日振幅{range_30}%（>5%，利于网格）+20')
    elif range_30 >= 3:
        score += 5
        score_notes.append(f'30日振幅{range_30}%（中等）+5')
    else:
        score -= 15
        score_notes.append(f'30日振幅仅{range_30}%（<3%，波动率不足）-15')

    if pct_90 <= 30:
        score += 15
        score_notes.append(f'90日分位{pct_90}%（低位，入场性价比高）+15')
    elif pct_90 >= 70:
        score -= 10
        score_notes.append(f'90日分位{pct_90}%（偏高位，性价比低）-10')
    else:
        score_notes.append(f'90日分位{pct_90}%（中性）+0')

    if score >= 65:
        verdict = '建议开启'
        verdict_icon = '✅'
    elif score >= 50:
        verdict = '等待时机'
        verdict_icon = '⏳'
    else:
        verdict = '暂不开启'
        verdict_icon = '⏸'

    # 触发条件
    triggers = [
        f'30日振幅扩大至 >5%（当前{range_30}%）',
        f'ETH/BTC 跌至 {round(low_90*0.92, 4)} 以下（历史低点-8%，更好入场价）',
        'ETH 出现明确催化剂（主网升级/ETF资金净流入）',
    ]

    return {
        'cur': cur,
        'low_90': low_90,
        'high_90': high_90,
        'pct_90': pct_90,
        'range_30': range_30,
        'rec_low': rec_low,
        'rec_high': rec_high,
        'score': score,
        'score_notes': score_notes,
        'verdict': verdict,
        'verdict_icon': verdict_icon,
        'triggers': triggers,
    }


# ==================== HTML 更新 ====================

def load_history():
    try:
        with open(HTML_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        m = re.search(r'"weekly_history"\s*:\s*(\[.*?\])', content, re.DOTALL)
        if m:
            return json.loads(m.group(1))
    except Exception:
        pass
    return []

def update_html(data_json):
    if not os.path.exists(HTML_PATH):
        print(f'  [SKIP] HTML文件不存在: {HTML_PATH}')
        return
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    json_str = json.dumps(data_json, ensure_ascii=False, indent=2)
    pattern = r'(// ====== DATA BLOCK START ======\s*\nconst DATA = ).*?(;\s*\n// ====== DATA BLOCK END ======)'
    replacement = r'\g<1>' + json_str + r'\g<2>'
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'  HTML更新完成')


# ==================== 周报生成 ====================

def generate_weekly_report(data_json):
    now = datetime.now()
    week_num = now.isocalendar()[1]
    year = now.year
    week_str = f'{year}-W{week_num:02d}'
    date_str = now.strftime('%Y-%m-%d')
    filepath = os.path.join(ARCHIVE_DIR, f'{week_str}.md')

    d   = data_json
    bl  = d.get('buy_low')
    sh  = d.get('sell_high')
    eg  = d.get('eth_grid')
    eth = d.get('eth_data', {})

    total_usd = d['total_btc'] * d['btc_price_usd']
    total_cny = round(total_usd * d['usdt_cny_rate'])

    # ── 市场数据表 ──────────────────────────────────────
    eth_row = ''
    if eth.get('eth_price_usd'):
        eth_row = f"| ETH价格 | ${eth['eth_price_usd']:,} | 24h {eth.get('eth_24h_change', 0):+.1f}% |\n"
        eth_row += f"| ETH/BTC | {eth.get('eth_btc', 0):.5f} | 30d区间 {eth.get('eth_30d_low',0):.4f}–{eth.get('eth_30d_high',0):.4f} |\n"

    # ── Buy Low 段 ──────────────────────────────────────
    bl_section = ''
    if bl:
        action_icon = {'execute': '✅ 建议执行', 'adjust': '⚠️ 建议调整', 'caution': '⚠️ 注意风险'}.get(bl['action'], '')
        bl_section = f"""
## 本周双币决策

### A. Buy Low ${bl['strike']:,}（${bl['usdt']:,} USDT → 到期{bl['expiry']}）

**{action_icon}** — {bl['suggestion']}

| 指标 | 数值 |
|------|------|
| 当前BTC价格 | ${d['btc_price_usd']:,} |
| 行权价 | ${bl['strike']:,}（折价 {bl['discount_pct']}%） |
| 触达概率（7天）| ~{bl['prob_triggered']}% |
| 不触达 → 年化收益 | {bl['est_apy_low']}–{bl['est_apy_high']}%（USDT权利金） |
| 触达 → 获得BTC | {bl['btc_if_exercised']} BTC（vs 市价买 {bl['btc_at_market']} BTC，多得 {bl['extra_btc']} BTC） |

**逻辑**：两种结果均为正期望。未触达：权利金年化{bl['est_apy_low']}–{bl['est_apy_high']}%远超USDT灵活储蓄；触达：折价{bl['discount_pct']}%买入BTC，有助于回补偏高的USDT持仓比例。
"""

    # ── Sell High 段 ────────────────────────────────────
    sh_section = ''
    if sh:
        action_icon = {'execute': '✅ 建议执行', 'adjust': '⚠️ 建议调整', 'caution': '⚠️ 注意风险'}.get(sh['action'], '')
        sh_section = f"""
### B. Sell High ${sh['strike']:,}（{sh['btc']} BTC → 到期{sh['expiry']}）

**{action_icon}** — {sh['suggestion']}

| 指标 | 数值 |
|------|------|
| 当前BTC价格 | ${d['btc_price_usd']:,} |
| 行权价 | ${sh['strike']:,}（溢价 +{sh['premium_pct']}%） |
| 行权概率（7天）| ~{sh['prob_exercised']}% |
| 行权 → 所得USDT | ${sh['usd_if_exercised']:,}（vs 市价 ${sh['usd_at_market']:,}，多 ${sh['price_gain']:,}） |
| 不行权 → 年化收益 | {sh['est_apy_low']}–{sh['est_apy_high']}%（BTC权利金） |
| 策略标准行权价参考 | A池 ${sh['rec_strike_a']:,}(+15%) / B池 ${sh['rec_strike_b']:,}(+19%) |
"""

    # ── ETH/BTC 网格段 ───────────────────────────────────
    grid_section = ''
    if eg:
        triggers_md = '\n'.join(f'- {t}' for t in eg['triggers'])
        notes_md    = '\n'.join(f'  - {n}' for n in eg['score_notes'])
        grid_section = f"""
## ETH/BTC 网格策略（周度更新）

**{eg['verdict_icon']} {eg['verdict']}**（可行性评分 {eg['score']}/100）

| 指标 | 数值 |
|------|------|
| 当前 ETH/BTC | {eg['cur']:.5f} |
| 90日最低 / 最高 | {eg['low_90']:.4f} / {eg['high_90']:.4f} |
| 90日分位数 | {eg['pct_90']}% |
| 30日振幅 | {eg['range_30']}% |
| 建议网格区间 | {eg['rec_low']:.4f} – {eg['rec_high']:.4f} |

**评分明细**：
{notes_md}

**开启触发条件（满足任一）**：
{triggers_md}
"""

    # ── 操作清单 ──────────────────────────────────────────
    checklist = ''
    if bl:
        bl_action = f'Buy Low ${bl["strike"]:,}（${bl["usdt"]:,} USDT，到期{bl["expiry"]}）— {bl["suggestion"][:20]}...'
        checklist += f'- [ ] {bl_action}\n'
    if sh:
        sh_action = f'Sell High ${sh["strike"]:,}（{sh["btc"]} BTC，到期{sh["expiry"]}）— {sh["suggestion"][:20]}...'
        checklist += f'- [ ] {sh_action}\n'
    for rec in d.get('recommendations', []):
        checklist += f'- [ ] {rec}\n'

    # ── 风险信号 ──────────────────────────────────────────
    risk_md = ''
    for sig in d.get('risk_signals', []):
        icon = '✅' if sig['level'] == 'ok' else ('⚠️' if sig['level'] == 'warn' else '🔴')
        risk_md += f"- {icon} **{sig['name']}** {sig['condition']}: {sig['current']} — {sig['action']}\n"

    content = f"""---
title: "{week_str} 投资周报"
type: 投资周报
date: {date_str}
tags:
  - 周报
  - BTC
  - ETH
  - 双币理财
  - 网格
---

# {week_str} 投资周报

> 自动生成于 {d['update_time']} | 数据来源：CoinGecko、Binance、Alternative.me

## 市场数据

| 指标 | 数值 | 变化 |
|------|------|------|
| BTC价格 | ${d['btc_price_usd']:,} | 24h {d['btc_24h_change']:+.1f}% / 7d {d['btc_7d_change']:+.1f}% |
{eth_row}| 恐贪指数 | {d['fear_greed_index']} ({d['fear_greed_label']}) | — |
| USDT/CNY | ~{d['usdt_cny_rate']:.2f} | — |

## 当前持仓状态

| 项目 | 数值 | 备注 |
|------|------|------|
| BTC总持仓 | {d['total_btc']} BTC | — |
| 可用USDT | ${USDT_AVAILABLE:,} | 用于Buy Low |
| 总市值(USD) | ${round(total_usd):,} | — |
| 总市值(CNY) | ¥{total_cny:,} | — |
| C池储备 | {d['pools']['C']['btc']} BTC | 冷存储不动 |
| 年度已提现 | ¥{YTD_WITHDRAWN_CNY:,} | 目标¥{ANNUAL_TARGET_CNY:,} |
{bl_section}{sh_section}{grid_section}
## 三池策略参数

| 池子 | BTC | 建议行权价 | 预估APY |
|------|-----|-----------|---------|
| A池(现金流) | {d['pools']['A']['btc']} | ${d['pools']['A']['strike']:,} (+{d['pools']['A']['premium_pct']}%) | {d['pools']['A']['apy']}% |
| B池(增币) | {d['pools']['B']['btc']} | ${d['pools']['B']['strike']:,} (+{d['pools']['B']['premium_pct']}%) | {d['pools']['B']['apy']}% |
| C池(储备) | {d['pools']['C']['btc']} | 冷存储 | — |

## 本周操作清单

{checklist}
## 风险信号

{risk_md}
---

← [[策略看板]] | [[投资策略总览]] | [[个人投资专区 MOC]]
"""

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'  周报生成: {filepath}')
    return filepath


# ==================== 微信推送（WxPusher） ====================

def send_wxpusher(data_json):
    """通过 WxPusher 发送周报摘要到微信"""
    if not WXPUSHER_ENABLED:
        print('  [SKIP] WxPusher未配置，跳过微信推送')
        print('  配置方法：访问 https://wxpusher.zjiecode.com，获取 AppToken 和 UID 后填入脚本顶部')
        return False

    d = data_json
    now = datetime.now()
    week_num = now.isocalendar()[1]
    week_str = f'W{week_num:02d}'
    total_usd = d['total_btc'] * d['btc_price_usd']
    total_cny = round(total_usd * d['usdt_cny_rate'])

    # 恐贪指数 emoji
    fg = d['fear_greed_index']
    fg_emoji = '😱' if fg < 25 else ('😰' if fg < 45 else ('😐' if fg < 55 else ('😊' if fg < 75 else '🤑')))

    # 风险信号汇总
    risk_lines = []
    for sig in d['risk_signals']:
        icon = '✅' if sig['level'] == 'ok' else ('⚠️' if sig['level'] == 'warn' else '🔴')
        risk_lines.append(f"{icon} {sig['name']}: {sig['current']}")

    # 操作建议（取前3条）
    rec_lines = [f"• {r}" for r in d['recommendations'][:3]]

    summary = f"""📊 **BTC {week_str} 投资周报**
━━━━━━━━━━━━━━
💰 **市场数据**
BTC价格：${d['btc_price_usd']:,}（24h {d['btc_24h_change']:+.1f}% / 7d {d['btc_7d_change']:+.1f}%）
恐贪指数：{fg} {d['fear_greed_label']} {fg_emoji}
持仓市值：¥{total_cny:,}（${round(total_usd):,}）

🏊 **三池状态**
A池 {d['pools']['A']['btc']} BTC → 建议行权价 ${d['pools']['A']['strike']:,}(+{d['pools']['A']['premium_pct']}%)
B池 {d['pools']['B']['btc']} BTC → 建议行权价 ${d['pools']['B']['strike']:,}(+{d['pools']['B']['premium_pct']}%)
C池 {d['pools']['C']['btc']} BTC → 冷存储不动

📋 **本周操作**
{chr(10).join(rec_lines)}

🚦 **风险信号**
{chr(10).join(risk_lines)}

🕐 更新于 {d['update_time']}"""

    payload = json.dumps({
        'appToken': WXPUSHER_APP_TOKEN,
        'content': summary,
        'summary': f"BTC {week_str} | ${d['btc_price_usd']:,} | 恐贪{fg}",
        'contentType': 3,  # 3=Markdown
        'uids': [WXPUSHER_UID],
    }).encode('utf-8')

    req = Request(
        'https://wxpusher.zjiecode.com/api/send/message',
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('success'):
                print(f'  微信推送成功')
                return True
            else:
                print(f'  微信推送失败: {result.get("msg")}')
                return False
    except Exception as e:
        print(f'  微信推送异常: {e}')
        return False


# ==================== 邮件推送（QQ SMTP） ====================

def send_email(data_json):
    """发送 HTML 格式周报邮件到 QQ 邮箱"""
    if not EMAIL_ENABLED:
        print('  [SKIP] 邮件未配置，跳过发送')
        print('  配置方法：QQ邮箱 → 设置 → 账户 → 开启SMTP → 获取授权码 → 填入脚本顶部')
        return False

    d = data_json
    now = datetime.now()
    week_num = now.isocalendar()[1]
    week_str = f'W{week_num:02d}'
    total_usd = d['total_btc'] * d['btc_price_usd']
    total_cny = round(total_usd * d['usdt_cny_rate'])

    fg = d['fear_greed_index']
    fg_color = '#d32f2f' if fg < 25 else ('#f57c00' if fg < 45 else ('#757575' if fg < 55 else ('#388e3c' if fg < 75 else '#1b5e20')))
    fg_emoji = '😱' if fg < 25 else ('😰' if fg < 45 else ('😐' if fg < 55 else ('😊' if fg < 75 else '🤑')))

    change_24h_color = '#d32f2f' if d['btc_24h_change'] < 0 else '#388e3c'
    change_7d_color  = '#d32f2f' if d['btc_7d_change']  < 0 else '#388e3c'

    risk_rows = ''
    for sig in d['risk_signals']:
        icon  = '✅' if sig['level'] == 'ok' else ('⚠️' if sig['level'] == 'warn' else '🔴')
        color = '#388e3c' if sig['level'] == 'ok' else ('#f57c00' if sig['level'] == 'warn' else '#d32f2f')
        risk_rows += f"""
        <tr>
          <td style="padding:6px 12px;border-bottom:1px solid #f0f0f0;">{icon} <b>{sig['name']}</b></td>
          <td style="padding:6px 12px;border-bottom:1px solid #f0f0f0;color:{color};">{sig['current']}</td>
          <td style="padding:6px 12px;border-bottom:1px solid #f0f0f0;color:#555;">{sig['action']}</td>
        </tr>"""

    rec_items = ''.join(
        f'<li style="margin:6px 0;color:#333;">{r}</li>'
        for r in d['recommendations']
    )

    subject = f"📊 BTC {week_str} 周报 | ${d['btc_price_usd']:,} | 恐贪{fg} {fg_emoji}"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'-apple-system',Arial,sans-serif;">
<div style="max-width:640px;margin:24px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a237e,#283593);padding:28px 32px;color:#fff;">
    <div style="font-size:13px;opacity:0.8;margin-bottom:4px;">BTC 投资策略周报</div>
    <div style="font-size:26px;font-weight:700;letter-spacing:1px;">{now.strftime('%Y年%m月%d日')} · {week_str}</div>
    <div style="font-size:13px;opacity:0.7;margin-top:6px;">自动生成于 {d['update_time']}</div>
  </div>

  <!-- 市场核心数据 -->
  <div style="display:flex;padding:24px 32px 0;gap:16px;">
    <div style="flex:1;background:#f8f9ff;border-radius:10px;padding:16px 20px;text-align:center;">
      <div style="font-size:12px;color:#888;margin-bottom:6px;">BTC 价格</div>
      <div style="font-size:28px;font-weight:700;color:#1a237e;">${d['btc_price_usd']:,}</div>
      <div style="font-size:13px;margin-top:4px;">
        <span style="color:{change_24h_color};">24h {d['btc_24h_change']:+.1f}%</span>
        &nbsp;|&nbsp;
        <span style="color:{change_7d_color};">7d {d['btc_7d_change']:+.1f}%</span>
      </div>
    </div>
    <div style="flex:1;background:#f8f9ff;border-radius:10px;padding:16px 20px;text-align:center;">
      <div style="font-size:12px;color:#888;margin-bottom:6px;">恐贪指数 {fg_emoji}</div>
      <div style="font-size:28px;font-weight:700;color:{fg_color};">{fg}</div>
      <div style="font-size:13px;color:{fg_color};margin-top:4px;">{d['fear_greed_label']}</div>
    </div>
    <div style="flex:1;background:#f8f9ff;border-radius:10px;padding:16px 20px;text-align:center;">
      <div style="font-size:12px;color:#888;margin-bottom:6px;">持仓市值</div>
      <div style="font-size:22px;font-weight:700;color:#1a237e;">¥{total_cny:,}</div>
      <div style="font-size:13px;color:#555;margin-top:4px;">${round(total_usd):,} · {d['total_btc']} BTC</div>
    </div>
  </div>

  <!-- 三池状态 -->
  <div style="padding:24px 32px 0;">
    <div style="font-size:15px;font-weight:600;color:#1a237e;margin-bottom:12px;">🏊 三池状态</div>
    <table style="width:100%;border-collapse:collapse;font-size:14px;">
      <tr style="background:#e8eaf6;">
        <th style="padding:8px 12px;text-align:left;font-weight:600;">池子</th>
        <th style="padding:8px 12px;text-align:right;">BTC</th>
        <th style="padding:8px 12px;text-align:right;">建议行权价</th>
        <th style="padding:8px 12px;text-align:right;">APY</th>
      </tr>
      <tr>
        <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;">A池 · 现金流</td>
        <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #f0f0f0;">{d['pools']['A']['btc']}</td>
        <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #f0f0f0;">${d['pools']['A']['strike']:,} <span style="color:#888;font-size:12px;">(+{d['pools']['A']['premium_pct']}%)</span></td>
        <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #f0f0f0;color:#388e3c;">{d['pools']['A']['apy']}%</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;">B池 · 增币</td>
        <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #f0f0f0;">{d['pools']['B']['btc']}</td>
        <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #f0f0f0;">${d['pools']['B']['strike']:,} <span style="color:#888;font-size:12px;">(+{d['pools']['B']['premium_pct']}%)</span></td>
        <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #f0f0f0;color:#388e3c;">{d['pools']['B']['apy']}%</td>
      </tr>
      <tr>
        <td style="padding:8px 12px;">C池 · 储备</td>
        <td style="padding:8px 12px;text-align:right;">{d['pools']['C']['btc']}</td>
        <td style="padding:8px 12px;text-align:right;color:#888;">冷存储不动</td>
        <td style="padding:8px 12px;text-align:right;color:#888;">-</td>
      </tr>
    </table>
  </div>

  <!-- 本周操作建议 -->
  <div style="padding:24px 32px 0;">
    <div style="font-size:15px;font-weight:600;color:#1a237e;margin-bottom:10px;">📋 本周操作建议</div>
    <ul style="margin:0;padding-left:20px;line-height:1.8;">
      {rec_items}
    </ul>
  </div>

  <!-- 风险信号 -->
  <div style="padding:20px 32px 0;">
    <div style="font-size:15px;font-weight:600;color:#1a237e;margin-bottom:12px;">🚦 风险信号</div>
    <table style="width:100%;border-collapse:collapse;font-size:14px;">
      <tr style="background:#f5f5f5;">
        <th style="padding:8px 12px;text-align:left;">指标</th>
        <th style="padding:8px 12px;text-align:left;">状态</th>
        <th style="padding:8px 12px;text-align:left;">备注</th>
      </tr>
      {risk_rows}
    </table>
  </div>

  <!-- USDT/CNY -->
  <div style="padding:16px 32px 0;">
    <div style="background:#fffde7;border-radius:8px;padding:12px 16px;font-size:13px;color:#555;">
      💱 USDT/CNY 参考汇率：<b>{d['usdt_cny_rate']:.2f}</b> &nbsp;|&nbsp;
      年度目标提现：<b>¥{d['cashflow']['annual_target_cny']:,}</b> &nbsp;|&nbsp;
      已提现：<b>¥{d['cashflow']['ytd_withdrawn_cny']:,}</b>
    </div>
  </div>

  <!-- Footer -->
  <div style="padding:20px 32px 24px;text-align:center;color:#aaa;font-size:12px;">
    由 update_dashboard.py 自动生成 · 每周一 12:00 更新<br>
    数据来源：CoinGecko · Alternative.me
  </div>
</div>
</body></html>"""

    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From']    = EMAIL_SENDER
    msg['To']      = EMAIL_RECEIVER
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    try:
        with smtplib.SMTP_SSL('smtp.qq.com', 465, context=SSL_CONTEXT) as server:
            server.login(EMAIL_SENDER, EMAIL_AUTH_CODE)
            server.sendmail(EMAIL_SENDER, [EMAIL_RECEIVER], msg.as_string())
        print(f'  邮件发送成功 → {EMAIL_RECEIVER}')
        return True
    except smtplib.SMTPAuthenticationError:
        print('  邮件发送失败：授权码错误，请检查 EMAIL_AUTH_CODE')
        return False
    except Exception as e:
        print(f'  邮件发送异常: {e}')
        return False


# ==================== Git 推送 ====================

def git_push(files):
    try:
        os.chdir(VAULT_DIR)
        for f in files:
            rel = os.path.relpath(f, VAULT_DIR)
            subprocess.run(['git', 'add', rel], check=True, capture_output=True)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        subprocess.run(
            ['git', 'commit', '-m', f'vault backup: {now_str}'],
            check=True, capture_output=True
        )
        subprocess.run(['git', 'push'], check=True, capture_output=True)
        print('  Git推送完成')
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else ''
        if 'nothing to commit' in stderr:
            print('  Git：无变更，跳过提交')
        else:
            print(f'  Git操作失败: {stderr}')
    except Exception as e:
        print(f'  Git异常: {e}')


# ==================== 主流程 ====================

def main():
    print('=' * 50)
    print(f'BTC投资策略看板 - {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 50)

    # 1. 获取市场数据
    market = get_btc_price()
    fg_val, fg_label = get_fear_greed()
    eth_data = get_eth_data()
    source = market.pop('source', 'unknown')
    print(f'BTC: ${market["btc_price_usd"]:,} | ETH: ${eth_data.get("eth_price_usd",0):,} | ETH/BTC: {eth_data.get("eth_btc",0):.5f} | 恐贪: {fg_val}({fg_label}) | 来源: {source}')

    # 2. 计算策略
    strategy = calc_strategy(market['btc_price_usd'], market['usdt_cny_rate'])

    # 3. 加载历史
    history = load_history()

    # 4. 组装数据
    now = datetime.now()
    week_num = now.isocalendar()[1]
    # 双币决策分析
    buy_low_analysis   = analyze_buy_low(market['btc_price_usd'], fg_val, eth_data)
    sell_high_analysis = analyze_sell_high(market['btc_price_usd'], fg_val)
    eth_grid_analysis  = analyze_eth_btc_grid(eth_data, market['btc_price_usd'])

    data_json = {
        'update_time': now.strftime('%Y-%m-%d %H:%M'),
        'btc_price_usd': market['btc_price_usd'],
        'btc_24h_change': market['btc_24h_change'],
        'btc_7d_change': market['btc_7d_change'],
        'fear_greed_index': fg_val,
        'fear_greed_label': fg_label,
        'usdt_cny_rate': market['usdt_cny_rate'],
        'total_btc': TOTAL_BTC,
        'accumulated_btc': 0.00,
        'eth_data': eth_data,
        'buy_low': buy_low_analysis,
        'sell_high': sell_high_analysis,
        'eth_grid': eth_grid_analysis,
        **strategy,
    }

    week_str = f'W{week_num:02d}'
    if not any(h.get('week') == week_str for h in history):
        history.append({
            'week': week_str,
            'date': now.strftime('%Y-%m-%d'),
            'btc_price': market['btc_price_usd'],
            'total_btc': TOTAL_BTC,
            'ytd_withdrawn': YTD_WITHDRAWN_CNY,
            'action': '周度自动更新',
        })
    data_json['weekly_history'] = history[-52:]

    # 5. 更新HTML看板
    update_html(data_json)

    # 6. 生成周报
    report_path = generate_weekly_report(data_json)

    # 7. Git推送
    files = [report_path]
    if os.path.exists(HTML_PATH):
        files.append(HTML_PATH)
    git_push(files)

    # 8. 邮件推送
    print('发送邮件...')
    send_email(data_json)

    # 9. 微信推送
    print('发送微信推送...')
    send_wxpusher(data_json)

    print('\n✅ 更新完成!')
    print(f'  周报: {report_path}')


if __name__ == '__main__':
    main()
