#!/usr/bin/env python3
import sqlite3, json, math
from datetime import datetime, timedelta
from collections import defaultdict

DB = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
OUT = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results/recheck_execution_alignment_2026-04-19.json'
PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-24'),
}
PIT_DELAY = 45
COST = 0.30


def fund_score(roe, rg, pg, gm, dr):
    roe = roe or 0; rg = rg or 0; pg = pg or 0; gm = gm or 0
    dr = dr if dr is not None else 100
    s = min(max(roe, 0), 30) + min(max(rg, 0) * 0.4, 20)
    s += min(max(pg, 0) * 0.4, 20) + min(max(gm, 0) * 0.3, 15)
    if dr < 30: s += 15
    elif dr < 50: s += 10
    elif dr < 70: s += 5
    return s


def calc_metrics(rets):
    if not rets:
        return {'trades': 0, 'positive_rate': 0, 'avg_return': 0}
    pos = sum(1 for x in rets if x > 0)
    return {
        'trades': len(rets),
        'positive_rate': round(pos / len(rets) * 100, 2),
        'avg_return': round(sum(rets) / len(rets), 4),
    }

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# PIT scores
fund_rows = conn.execute("""
    SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio
    FROM financial_indicators WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL
    ORDER BY symbol, report_date
""").fetchall()
sym_scores = defaultdict(list)
for r in fund_rows:
    s = fund_score(r['roe'], r['revenue_growth'], r['profit_growth'], r['gross_margin'], r['debt_ratio'])
    if s > 0:
        pit_date = (datetime.strptime(r['report_date'], '%Y-%m-%d') + timedelta(days=PIT_DELAY)).strftime('%Y-%m-%d')
        sym_scores[r['symbol']].append((pit_date, s))

# price data
rows = conn.execute("""
    SELECT symbol, trade_date, open, close, rsi14, boll_lower
    FROM kline_daily
    WHERE trade_date >= '2020-12-01' AND trade_date <= '2026-03-24'
      AND open IS NOT NULL AND close IS NOT NULL
    ORDER BY symbol, trade_date
""").fetchall()
by_sym = defaultdict(list)
for r in rows:
    by_sym[r['symbol']].append(dict(r))

all_dates = sorted({r['trade_date'] for r in rows})
# weak70 by close<ma20 breadth
close_map = defaultdict(dict)
for sym, items in by_sym.items():
    closes = [x['close'] for x in items]
    dates = [x['trade_date'] for x in items]
    for i, d in enumerate(dates):
        if i >= 19:
            ma20 = sum(closes[i-19:i+1]) / 20
            close_map[d][sym] = (closes[i], ma20)
weak70 = {}
for d, mp in close_map.items():
    total = len(mp)
    below = sum(1 for c, m in mp.values() if c < m)
    weak70[d] = (total > 0 and below / total >= 0.7)

# monthly top300
monthly_top300 = {}
cur = datetime.strptime(all_dates[0], '%Y-%m-%d').replace(day=1)
end = datetime.strptime(all_dates[-1], '%Y-%m-%d')
while cur <= end:
    ms = cur.strftime('%Y-%m-%d')
    scored = []
    for sym in by_sym.keys():
        latest = 0
        for ad, sc in reversed(sym_scores.get(sym, [])):
            if ad <= ms:
                latest = sc
                break
        if latest > 0:
            scored.append((sym, latest))
    scored.sort(key=lambda x: -x[1])
    monthly_top300[ms] = {s for s, _ in scored[:300]}
    nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    cur = nxt

results = {'BB1.00_doc_fixed_hold7_close_sell': {}, 'BB1.00_wrong_open_sell_interpretation_proxy': {}}

for phase, (ps, pe) in PHASES.items():
    rets_close = []
    rets_open_proxy = []
    for sym, items in by_sym.items():
        dates = [x['trade_date'] for x in items]
        for i, x in enumerate(items):
            d = x['trade_date']
            if d < ps or d > pe:
                continue
            if not weak70.get(d, False):
                continue
            ms = datetime.strptime(d, '%Y-%m-%d').replace(day=1).strftime('%Y-%m-%d')
            if sym not in monthly_top300.get(ms, set()):
                continue
            rsi = x['rsi14']; bb = x['boll_lower']; close = x['close']
            if rsi is None or bb is None:
                continue
            if not (10 <= rsi < 20 and close <= bb * 1.0):
                continue
            buy_i = i + 1
            sell_i = i + 1 + 7
            if sell_i >= len(items):
                continue
            buy_p = items[buy_i]['open']
            sell_close = items[sell_i]['close']
            if buy_p and sell_close:
                rets_close.append((sell_close - buy_p) / buy_p * 100 - COST)
            # open-sell proxy: use sell day open instead of close to approximate the wrong wording
            sell_open = items[sell_i]['open']
            if buy_p and sell_open:
                rets_open_proxy.append((sell_open - buy_p) / buy_p * 100 - COST)
    results['BB1.00_doc_fixed_hold7_close_sell'][phase] = calc_metrics(rets_close)
    results['BB1.00_wrong_open_sell_interpretation_proxy'][phase] = calc_metrics(rets_open_proxy)

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(json.dumps(results, ensure_ascii=False, indent=2))
