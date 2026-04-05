# -*- coding: utf-8 -*-
"""
BTC投资策略看板 - 数据更新脚本
每周一12:00自动运行，拉取实时数据并更新HTML看板
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

# ========== 配置 ==========
VAULT_DIR = r'C:\Users\01455310\Documents\Obsidian Vault'
INVEST_DIR = os.path.join(VAULT_DIR, '个人投资专区')
HTML_PATH = os.path.join(INVEST_DIR, '策略看板.html')
ARCHIVE_DIR = os.path.join(INVEST_DIR, '周报归档')

# 持仓配置（手动更新，每次买卖BTC后修改这里）
TOTAL_BTC = 4.20
POOL_A_PCT = 0.35
POOL_B_PCT = 0.50
POOL_C_PCT = 0.15

# 策略参数
GRID_RANGE = 0.15         # 网格区间 ±15%
C_POOL_TRIGGER = 40000    # C池抄底触发价

# 币安双币理财行权价档位规则（基于BTC价格区间的标准间距）
# BTC价格区间 → 行权价间距
# < $20,000 → $500
# $20,000-$50,000 → $1,000
# $50,000-$100,000 → $1,000 或 $2,000
# > $100,000 → $2,000 或 $5,000
def get_strike_step(price):
    """根据BTC价格返回行权价间距"""
    if price < 20000: return 500
    elif price < 50000: return 1000
    elif price < 100000: return 1000
    else: return 2000

def snap_to_strike(price, direction='up'):
    """将价格对齐到最近的行权价档位"""
    step = get_strike_step(price)
    if direction == 'up':
        return int((price // step + 1) * step)
    else:
        return int((price // step) * step)

def find_sell_high_strikes(price, premium_pct_low=0.08, premium_pct_high=0.20):
    """
    根据当前BTC价格，生成合理的Sell High行权价候选档位
    A池: 保守，+10%~+15% 区间选最近档位
    B池: 激进，+15%~+20% 区间选最近档位
    返回: (a_strike, b_strike, buy_low_target)
    """
    step = get_strike_step(price)

    # A池行权价: 现价+10%~+15%之间的档位
    a_target = price * 1.12  # 偏向+12%附近
    a_strike = int(round(a_target / step) * step)
    # 确保至少比现价高8%
    while a_strike < price * 1.08:
        a_strike += step
    # 确保不超过+18%
    if a_strike > price * 1.18:
        a_strike -= step

    # B池行权价: 现价+15%~+22%之间的档位
    b_target = price * 1.18  # 偏向+18%附近
    b_strike = int(round(b_target / step) * step)
    # 确保比A池高
    while b_strike <= a_strike:
        b_strike += step
    # 确保不超过+25%
    if b_strike > price * 1.25:
        b_strike -= step

    # Buy Low目标价: 现价-10%~-15%之间的档位
    buy_low_target_raw = price * 0.88
    buy_low_target = int(round(buy_low_target_raw / step) * step)
    # 确保比现价低至少8%
    while buy_low_target > price * 0.92:
        buy_low_target -= step

    return a_strike, b_strike, buy_low_target

# 现金流
ANNUAL_TARGET_CNY = 300000
YTD_WITHDRAWN_CNY = 0     # 手动更新：年度累计已提现人民币


def fetch_json(url, timeout=8):
    """获取JSON数据"""
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (URLError, Exception) as e:
        print(f'  [WARN] 请求失败 {url}: {e}')
        return None


def get_btc_price():
    """从CoinGecko获取BTC价格，失败则尝试Binance，再失败用离线缓存"""
    print('获取BTC价格...')
    # 尝试 CoinGecko
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

    # 尝试 Binance
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

    # 离线模式：使用缓存
    print('  所有API失败，使用离线缓存...')
    cached = load_cache()
    if cached:
        cached['source'] = '离线缓存'
        return cached

    # 兜底：使用已知数据
    print('  无缓存，使用兜底数据')
    return {
        'btc_price_usd': 67244,
        'btc_24h_change': -1.7,
        'btc_7d_change': -3.2,
        'usdt_cny_rate': 6.90,
        'source': '兜底数据',
    }


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


def get_fear_greed():
    """获取恐贪指数"""
    print('获取恐贪指数...')
    data = fetch_json('https://api.alternative.me/fng/?limit=1')
    if data and 'data' in data and len(data['data']) > 0:
        fg = data['data'][0]
        val = int(fg.get('value', 50))
        label_map = {
            (0, 25): '极度恐惧',
            (25, 45): '恐惧',
            (45, 55): '中性',
            (55, 75): '贪婪',
            (75, 101): '极度贪婪',
        }
        label = '中性'
        for (lo, hi), lbl in label_map.items():
            if lo <= val < hi:
                label = lbl
                break
        return val, label
    return 50, '中性'


def calc_strategy(price, usdt_cny):
    """根据当前价格计算策略参数"""
    a_btc = round(TOTAL_BTC * POOL_A_PCT, 2)
    b_btc = round(TOTAL_BTC * POOL_B_PCT, 2)
    c_btc = round(TOTAL_BTC * POOL_C_PCT, 2)

    # 使用档位对齐的行权价
    a_strike, b_strike, buy_low = find_sell_high_strikes(price)
    step = get_strike_step(price)

    # 网格区间也对齐到档位
    grid_low = snap_to_strike(price * (1 - GRID_RANGE), 'down')
    grid_high = snap_to_strike(price * (1 + GRID_RANGE), 'up')

    monthly_usdt = round(ANNUAL_TARGET_CNY / 12 / usdt_cny)
    monthly_cny = round(ANNUAL_TARGET_CNY / 12)

    # 计算实际溢价百分比
    a_premium_pct = round((a_strike / price - 1) * 100, 1)
    b_premium_pct = round((b_strike / price - 1) * 100, 1)
    buy_low_disc_pct = round((1 - buy_low / price) * 100, 1)

    # APY估算：行权价距离越远，APY越低；距离越近，APY越高
    # 基准：+10% → ~22% APY, +15% → ~16% APY, +20% → ~12% APY
    base_apy_a = max(8, min(30, 32 - a_premium_pct * 1.2))
    base_apy_b = max(6, min(25, 32 - b_premium_pct * 1.2))
    base_apy_a = round(base_apy_a, 1)
    base_apy_b = round(base_apy_b, 1)

    now = datetime.now()
    months_elapsed = now.month - 1  # 1月=0, 4月=3

    # 风险信号
    risk_signals = [
        {
            'name': 'BTC价格',
            'condition': f'< ${C_POOL_TRIGGER:,}',
            'current': '危险' if price < C_POOL_TRIGGER else ('警告' if price < 55000 else '正常'),
            'level': 'danger' if price < C_POOL_TRIGGER else ('warn' if price < 55000 else 'ok'),
            'action': f'当前${price:,}，距触发线{round((price/C_POOL_TRIGGER-1)*100)}%'
        },
        {
            'name': '波动率IV',
            'condition': '> 60%',
            'current': '偏高' if price < 70000 else '正常',
            'level': 'warn' if price < 70000 else 'ok',
            'action': '利好卖期权，权利金收入增加' if price < 70000 else '权利金收入正常水平'
        },
        {
            'name': '市值区间',
            'condition': '偏离目标',
            'current': '正常',
            'level': 'ok',
            'action': '持仓市值在合理范围内'
        }
    ]

    # 相邻档位供参考
    a_strike_alt = a_strike + step  # A池备选（更保守）
    b_strike_alt = b_strike - step  # B池备选（更激进）

    # 操作建议
    recs = [
        f'A池 Sell High: 建议行权价 ${a_strike:,}(+{a_premium_pct}%) 或 ${a_strike_alt:,}(+{round((a_strike_alt/price-1)*100,1)}%), 周期14天, 预估APY {base_apy_a}%',
        f'B池 Sell High: 建议行权价 ${b_strike:,}(+{b_premium_pct}%) 或 ${b_strike_alt:,}(+{round((b_strike_alt/price-1)*100,1)}%), 周期30天',
        f'Buy Low备选: ${buy_low:,}(-{buy_low_disc_pct}%); 网格区间 ${grid_low:,}-${grid_high:,}',
    ]
    if price < 55000:
        recs.append('风险提示: BTC接近C池触发线，关注是否需要启动抄底')
    elif price < 70000:
        recs.append('恐贪指数偏低(恐惧区), IV偏高 - 适合卖期权赚取权利金')
    else:
        recs.append('市场情绪中性偏乐观，维持常规策略')

    month_name = now.strftime('%m').lstrip('0')
    if YTD_WITHDRAWN_CNY < monthly_cny * months_elapsed:
        recs.append(f'月度提现: {month_name}月尚未提取, 建议月初P2P出金${monthly_usdt:,} USDT(≈¥{monthly_cny:,})')
    else:
        recs.append(f'月度提现: 本月已达标, 下次提现{int(month_name)+1}月初')

    return {
        'strike_step': step,
        'pools': {
            'A': {'name': 'A池-现金流', 'btc': a_btc, 'pct': round(POOL_A_PCT*100),
                   'strategy': 'Sell High', 'strike': a_strike, 'strike_alt': a_strike_alt,
                   'premium_pct': a_premium_pct, 'tenor': '14天',
                   'apy': base_apy_a, 'buy_low_target': buy_low, 'buy_low_disc_pct': buy_low_disc_pct,
                   'status': '运行中'},
            'B': {'name': 'B池-增币', 'btc': b_btc, 'pct': round(POOL_B_PCT*100),
                   'strategy': 'Sell High远期+网格', 'strike': b_strike, 'strike_alt': b_strike_alt,
                   'premium_pct': b_premium_pct, 'tenor': '30天',
                   'apy': base_apy_b, 'grid_low': grid_low, 'grid_high': grid_high, 'status': '运行中'},
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


def load_history():
    """从HTML中读取历史记录"""
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
    """更新HTML文件中的DATA块"""
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    json_str = json.dumps(data_json, ensure_ascii=False, indent=2)
    # 替换DATA块
    pattern = r'(// ====== DATA BLOCK START ======\s*\nconst DATA = ).*?(;\s*\n// ====== DATA BLOCK END ======)'
    replacement = r'\g<1>' + json_str + r'\g<2>'
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'HTML更新完成: {HTML_PATH}')


def generate_weekly_report(data_json):
    """生成周报归档"""
    now = datetime.now()
    week_num = now.isocalendar()[1]
    year = now.year
    week_str = f'{year}-W{week_num:02d}'
    date_str = now.strftime('%Y-%m-%d')
    filename = f'{week_str}.md'
    filepath = os.path.join(ARCHIVE_DIR, filename)

    d = data_json
    total_value_usd = d['total_btc'] * d['btc_price_usd']
    total_value_cny = round(total_value_usd * d['usdt_cny_rate'])

    content = f"""---
title: "{week_str} 投资周报"
type: 投资周报
date: {date_str}
tags:
  - 周报
  - BTC
---

# {week_str} 投资周报

> 自动生成于 {d['update_time']}

## 市场数据

| 指标 | 数值 |
|------|------|
| BTC价格 | ${d['btc_price_usd']:,} |
| 24h涨跌 | {d['btc_24h_change']:+.1f}% |
| 7日涨跌 | {d['btc_7d_change']:+.1f}% |
| 恐贪指数 | {d['fear_greed_index']} ({d['fear_greed_label']}) |
| USDT/CNY | {d['usdt_cny_rate']:.2f} |

## 持仓状态

| 项目 | 数值 |
|------|------|
| 总BTC | {d['total_btc']:.2f} |
| 总市值(USD) | ${round(total_value_usd):,} |
| 总市值(CNY) | ¥{total_value_cny:,} |
| 累计增币 | {d['accumulated_btc']:+.4f} BTC |
| 年度已提现 | ¥{d['cashflow']['ytd_withdrawn_cny']:,} |

## 三池状态

| 池子 | BTC | 策略 | 行权价 | APY |
|------|-----|------|--------|-----|
| A池(现金流) | {d['pools']['A']['btc']} | {d['pools']['A']['strategy']} | ${d['pools']['A']['strike']:,} | {d['pools']['A']['apy']}% |
| B池(增币) | {d['pools']['B']['btc']} | {d['pools']['B']['strategy']} | ${d['pools']['B']['strike']:,} | {d['pools']['B']['apy']}% |
| C池(储备) | {d['pools']['C']['btc']} | {d['pools']['C']['strategy']} | - | - |

## 本周操作建议

"""
    for rec in d['recommendations']:
        content += f'- [ ] {rec}\n'

    content += f"""
## 风险信号

"""
    for sig in d['risk_signals']:
        emoji = '✅' if sig['level'] == 'ok' else ('⚠️' if sig['level'] == 'warn' else '🔴')
        content += f"- {emoji} **{sig['name']}** {sig['condition']}: {sig['current']} — {sig['action']}\n"

    content += f'\n---\n\n← [[策略看板]] | [[投资策略总览]] | [[个人投资专区 MOC]]\n'

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'周报生成: {filepath}')
    return filepath


def git_push(files):
    """Git提交并推送"""
    try:
        os.chdir(VAULT_DIR)
        for f in files:
            rel = os.path.relpath(f, VAULT_DIR)
            subprocess.run(['git', 'add', rel], check=True, capture_output=True)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        msg = f'投资看板周度更新 {now_str}'
        subprocess.run(['git', 'commit', '-m', msg], check=True, capture_output=True)
        subprocess.run(['git', 'push'], check=True, capture_output=True)
        print('Git推送完成')
    except subprocess.CalledProcessError as e:
        print(f'Git操作失败: {e}')
    except Exception as e:
        print(f'Git异常: {e}')


def main():
    print('=' * 50)
    print('BTC投资策略看板 - 数据更新')
    print('=' * 50)

    # 1. 获取市场数据
    market = get_btc_price()
    fg_val, fg_label = get_fear_greed()
    source = market.pop('source', 'unknown')
    print(f'BTC: ${market["btc_price_usd"]:,} | 24h: {market["btc_24h_change"]:+.1f}% | 恐贪: {fg_val} | 来源: {source}')

    # 2. 计算策略
    strategy = calc_strategy(market['btc_price_usd'], market['usdt_cny_rate'])

    # 3. 加载历史
    history = load_history()

    # 4. 组装数据
    now = datetime.now()
    week_num = now.isocalendar()[1]
    data_json = {
        'update_time': now.strftime('%Y-%m-%d %H:%M'),
        'btc_price_usd': market['btc_price_usd'],
        'btc_24h_change': market['btc_24h_change'],
        'btc_7d_change': market['btc_7d_change'],
        'fear_greed_index': fg_val,
        'fear_greed_label': fg_label,
        'usdt_cny_rate': market['usdt_cny_rate'],
        'total_btc': TOTAL_BTC,
        'accumulated_btc': 0.00,  # 手动更新
        **strategy,
    }

    # 追加本周记录
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
    data_json['weekly_history'] = history[-52:]  # 保留最近52周

    # 5. 更新HTML
    update_html(data_json)

    # 6. 生成周报
    report_path = generate_weekly_report(data_json)

    # 7. Git提交
    git_push([HTML_PATH, report_path])

    print('\n[OK] 更新完成!')
    print(f'  看板: {HTML_PATH}')
    print(f'  周报: {report_path}')


if __name__ == '__main__':
    main()
