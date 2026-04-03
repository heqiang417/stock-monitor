#!/usr/bin/env python3
"""
daily_pick V4 完整28项指标评测
严格按项目文档要求：训练/验证/测试分别计算28项
PIT延迟按财报披露截止日：Q1=30天/半年报=62天/Q3=31天/年报=120天
测试集 2025-07-02 ~ 2025-12-31
"""
import sys, sqlite3, json, time, os
import numpy as np
from datetime import datetime, timedelta
from bisect import bisect_right

sys.path.insert(0, '/mnt/data/workspace/stock-monitor-app-py/backtest')
from quick_explore import DB, TOP_N, RF

COST = 0.30  # 0.15%单边 x2
HOLD = 10
RSI_THRESH = 20
OUTPUT_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results/eval_daily_pick_v4'

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-27'),
}

# 按财报类型设PIT延迟
def pit_delay_days(report_date_str):
    """根据报告期月份计算PIT延迟天数"""
    month = int(report_date_str[5:7])
    if month == 3:    return 30    # Q1: 03-31 → 04-30
    elif month == 6:  return 62    # H1: 06-30 → 08-31
    elif month == 9:  return 31    # Q3: 09-30 → 10-31
    elif month == 12: return 120   # 年报: 12-31 → 次年04-30
    else: return 45

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def calc_28_metrics(rets, hold_days, hit_stock_count):
    """按文档要求计算全部28项指标"""
    if not rets:
        return {k: 0 for k in [
            'total_trades','positive_rate','avg_return','median_return','max_return','min_return','hit_stocks',
            'sharpe','max_drawdown','volatility','downside_volatility','sortino',
            'win_rate','profit_loss_ratio','avg_win','avg_loss','max_win','max_loss','max_consec_win','max_consec_loss',
            'annual_return','calmar','recovery_factor','break_even_wr','expectancy',
            'train_test_ratio','three_phase_consistency','avg_hold_days'
        ]}
    r = np.array(rets)
    n = len(r)
    pos = r[r > 0]
    neg = r[r <= 0]

    pos_rate = len(pos) / n * 100
    avg_ret = float(np.mean(r))
    median_ret = float(np.median(r))
    max_ret = float(max(r))
    min_ret = float(min(r))

    # 年化
    ann_ret = avg_ret * 252 / hold_days
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_vol = std * np.sqrt(252 / hold_days)

    # 夏普 & 索提诺
    sharpe = (ann_ret - RF * 100) / ann_vol if ann_vol > 0 else 0
    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold_days)) if len(dn) > 1 else 0
    sortino = (ann_ret - RF * 100) / dn_std if dn_std > 0 else 0

    # 最大回撤（基于累计对数收益）
    cum = 0; peak = 0; mdd = 0
    for x in rets:
        cum += np.log(1 + x / 100)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)

    # 盈亏比
    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0

    # 连续盈亏
    cw = cl = cwmax = clmax = 0
    for x in rets:
        if x > 0: cw += 1; cl = 0; cwmax = max(cwmax, cw)
        else: cl += 1; cw = 0; clmax = max(clmax, cl)

    # 期望值
    if len(neg) > 0:
        expectancy = float(len(pos)/n * np.mean(pos) + len(neg)/n * np.mean(neg))
    else:
        expectancy = float(np.mean(r))

    return {
        'total_trades': n,
        'positive_rate': round(pos_rate, 2),
        'avg_return': round(avg_ret, 4),
        'median_return': round(median_ret, 4),
        'max_return': round(max_ret, 4),
        'min_return': round(min_ret, 4),
        'hit_stocks': hit_stock_count,
        'sharpe': round(sharpe, 4),
        'max_drawdown': round(mdd * 100, 2),
        'volatility': round(ann_vol, 4),
        'downside_volatility': round(dn_std, 4),
        'sortino': round(sortino, 4),
        'win_rate': round(pos_rate, 2),
        'profit_loss_ratio': round(plr, 4),
        'avg_win': round(float(np.mean(pos)), 4) if len(pos) > 0 else 0,
        'avg_loss': round(float(abs(np.mean(neg))), 4) if len(neg) > 0 else 0,
        'max_win': round(max_ret, 4),
        'max_loss': round(abs(min_ret), 4),
        'max_consec_win': cwmax,
        'max_consec_loss': clmax,
        'annual_return': round(ann_ret, 2),
        'calmar': round(ann_ret / (mdd * 100), 4) if mdd > 0 else 0,
        'recovery_factor': round(float(sum(rets)) / (mdd * 100), 4) if mdd > 0 else 0,
        'break_even_wr': round(1 / (1 + plr) * 100, 2) if plr > 0 else 0,
        'expectancy': round(expectancy, 4),
        'train_test_ratio': 0,  # 需要跨阶段计算
        'three_phase_consistency': 0,  # 需要跨阶段计算
        'avg_hold_days': hold_days
    }

t0 = time.time()
log("加载数据...")
conn = sqlite3.connect(DB, timeout=120)

# 自定义加载，使用按财报类型的PIT延迟
from quick_explore import fund_score
log("加载PIT基本面（动态延迟）...")
fund_rows = conn.execute("""
    SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio
    FROM financial_indicators
    WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL OR profit_growth IS NOT NULL
    ORDER BY symbol, report_date
""").fetchall()

sym_scores = {}
for sym, rd, roe, rg, pg, gm, dr in fund_rows:
    s = fund_score(roe, rg, pg, gm, dr)
    if s > 0 and rd:
        pit_days = pit_delay_days(rd)
        pit_date = (datetime.strptime(rd, '%Y-%m-%d') + timedelta(days=pit_days)).strftime('%Y-%m-%d')
        if sym not in sym_scores:
            sym_scores[sym] = []
        sym_scores[sym].append((pit_date, s))
log(f"  PIT评分: {len(sym_scores)} 只")

log("加载K线数据...")
active = list(sym_scores.keys())
sym_data = {}
for sym in active:
    rows = conn.execute("""
        SELECT trade_date, open, close, rsi14, boll_lower, ma20
        FROM kline_daily WHERE symbol=? AND trade_date>='2020-12-01'
        ORDER BY trade_date
    """, (sym,)).fetchall()
    if len(rows) < 60:
        continue
    dates = [r[0] for r in rows]
    opens = np.array([r[1] for r in rows], dtype=float)
    closes = np.array([r[2] for r in rows], dtype=float)
    rsi = np.array([r[3] if r[3] is not None else np.nan for r in rows], dtype=float)
    bb_lower = np.array([r[4] if r[4] is not None else np.nan for r in rows], dtype=float)
    ma20 = np.array([r[5] if r[5] is not None else np.nan for r in rows], dtype=float)
    sym_data[sym] = {'dates': dates, 'open': opens, 'close': closes, 'rsi': rsi, 'bb_lower': bb_lower, 'ma20': ma20}
log(f"  K线: {len(sym_data)} 只")

log("计算弱市...")
all_dates = sorted(set(d for sd in sym_data.values() for d in sd['dates']))
weak = {}
for d in all_dates:
    total = below = 0
    for sd in sym_data.values():
        try:
            idx = sd['dates'].index(d)
            if idx >= 20:
                ma = np.nanmean(sd['close'][max(0, idx-19):idx+1])
                cl = sd['close'][idx]
                if not np.isnan(ma) and not np.isnan(cl):
                    total += 1
                    if cl < ma:
                        below += 1
        except ValueError:
            pass
    weak[d] = (total >= 20 and below / total > 0.7)
weak_count = sum(1 for v in weak.values() if v)
log(f"  弱市: {weak_count}/{len(all_dates)} 天 ({time.time()-t0:.1f}s)")

conn.close()
log(f"数据加载完成: {len(sym_data)} 只股票, {time.time()-t0:.1f}s")

# 回测
log("开始回测...")
results = {}
trades_all = {}
hit_stocks_all = {}

for phase, (ps, pe) in PHASES.items():
    all_rets = []
    phase_trades = []
    stocks_hit = set()

    dt = datetime.strptime(ps, '%Y-%m-%d').replace(day=1)
    end_dt = datetime.strptime(pe, '%Y-%m-%d')

    while dt <= end_dt:
        ms = dt.strftime('%Y-%m-%d')
        me_dt = dt + timedelta(days=32)
        me = min(me_dt.replace(day=1).strftime('%Y-%m-%d'), pe)

        # Monthly TOP200 PIT
        scored = []
        for sym in sym_data:
            latest = 0
            for ad, sc in reversed(sym_scores.get(sym, [])):
                if ad <= ms:
                    latest = sc
                    break
            if latest > 0:
                scored.append((sym, latest))
        scored.sort(key=lambda x: -x[1])
        top = [s[0] for s in scored[:TOP_N]]

        for sym in top:
            if sym not in sym_data:
                continue
            sd = sym_data[sym]
            dates = sd['dates']
            opens = sd['open']
            closes = sd['close']
            rsi = sd['rsi']

            i = 0
            while i < len(dates):
                d = dates[i]
                if d < ms:
                    i += 1; continue
                if d >= me:
                    break
                if i + 1 + HOLD >= len(dates):
                    break
                if not weak.get(d, False):
                    i += 1; continue
                if np.isnan(rsi[i]) or rsi[i] >= RSI_THRESH or rsi[i] < 10:
                    i += 1; continue

                bp = opens[i + 1]
                sp = closes[i + 1 + HOLD]
                if bp > 0 and not np.isnan(bp) and not np.isnan(sp):
                    ret = (sp - bp) / bp * 100 - COST
                    all_rets.append(ret)
                    phase_trades.append({'symbol': sym, 'date': d, 'buy': round(bp, 2), 'sell': round(sp, 2), 'ret': round(ret, 4)})
                    stocks_hit.add(sym)
                i += HOLD + 1

        dt = me_dt.replace(day=1)

    m = calc_28_metrics(all_rets, HOLD, len(stocks_hit))
    results[phase] = m
    trades_all[phase] = phase_trades
    hit_stocks_all[phase] = list(stocks_hit)
    log(f"{phase}: {m['total_trades']}笔, 正率{m['positive_rate']}%, 夏普{m['sharpe']}, 索提诺{m['sortino']}")

# 跨阶段计算
train_ret = results['train']['avg_return']
test_ret = results['test']['avg_return']
results['train']['train_test_ratio'] = round(train_ret / test_ret, 4) if test_ret != 0 else 0
results['val']['train_test_ratio'] = 0
results['test']['train_test_ratio'] = round(train_ret / test_ret, 4) if test_ret != 0 else 0

# 三阶段一致性（方向是否一致）
directions = [1 if results[p]['avg_return'] > 0 else -1 for p in ['train', 'val', 'test']]
consistency = 1 if len(set(directions)) == 1 else 0
for p in ['train', 'val', 'test']:
    results[p]['three_phase_consistency'] = consistency

# 输出
output = {
    'name': 'daily_pick_v4_RSI20_弱市TOP200_hold10',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'phases': {p: PHASES[p] for p in PHASES},
    'config': {
        'hold_days': HOLD, 'rsi_threshold': f'<{RSI_THRESH} & >=10',
        'weak_market': '>70% stocks < MA20',
        'top_n': TOP_N, 'pit_delay': '45天',
        'cost': f'{COST}% total (0.15%单边x2)',
        'fund_score': 'quick_explore公式',
        'data_note': '测试集截至2025-12-31，全部基于2025-09-30三季报'
    },
    'per_phase': results
}

os.makedirs(OUTPUT_DIR, exist_ok=True)
with open(os.path.join(OUTPUT_DIR, 'evaluate_result.json'), 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
with open(os.path.join(OUTPUT_DIR, 'trades.json'), 'w') as f:
    json.dump(trades_all, f, indent=2, ensure_ascii=False)

print(f"\n完成! {time.time()-t0:.1f}s")
print(f"\n{'='*70}")
print("daily_pick V4 完整28项指标")
print(f"{'='*70}")

categories = {
    '基础指标': ['total_trades','positive_rate','avg_return','median_return','max_return','min_return','hit_stocks'],
    '风险指标': ['sharpe','max_drawdown','volatility','downside_volatility','sortino'],
    '交易质量': ['win_rate','profit_loss_ratio','avg_win','avg_loss','max_win','max_loss','max_consec_win','max_consec_loss'],
    '效率指标': ['annual_return','calmar','recovery_factor','break_even_wr','expectancy'],
    '稳定性': ['train_test_ratio','three_phase_consistency','avg_hold_days']
}

for cat, keys in categories.items():
    print(f"\n### {cat}")
    for k in keys:
        vals = {p: results[p][k] for p in ['train', 'val', 'test']}
        print(f"  {k}: train={vals['train']} | val={vals['val']} | test={vals['test']}")
