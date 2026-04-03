#!/usr/bin/env python3
"""
Strategy Search V4+ with Dynamic PIT Delay
Searches for strategies with >55% positive rate across all 3 phases
and test Sharpe > 1.0
"""
import sqlite3, json, time, os
import numpy as np
from datetime import datetime, timedelta

DB = '/mnt/data/workspace/stock-monitor-app-py/data/stock_data.db'
TOP_N = 200
RF = 0.03
COST = 0.30  # 0.15%单边 x2

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-27'),
}

def pit_delay_days(report_date_str):
    month = int(report_date_str[5:7])
    if month == 3:    return 30
    elif month == 6:  return 62
    elif month == 9:  return 31
    elif month == 12: return 120
    else: return 45

def fund_score(roe, rg, pg, gm, dr):
    roe = roe or 0; rg = rg or 0; pg = pg or 0; gm = gm or 0
    dr = dr if dr is not None else 100
    s = min(max(roe, 0), 30) + min(max(rg, 0) * 0.4, 20)
    s += min(max(pg, 0) * 0.4, 20) + min(max(gm, 0) * 0.3, 15)
    if dr < 30: s += 15
    elif dr < 50: s += 10
    elif dr < 70: s += 5
    return s

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def calc_metrics(rets, hold):
    if not rets:
        return {'trades': 0, 'pos_rate': 0, 'avg': 0, 'sharpe': 0, 'max_dd': 0,
                'sortino': 0, 'plr': 0}
    r = np.array(rets)
    n = len(r)
    pos = r[r > 0]
    neg = r[r <= 0]
    pos_rate = len(pos) / n * 100
    avg = float(np.mean(r))
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_ret = avg * 252 / hold
    ann_vol = std * np.sqrt(252 / hold)
    sharpe = (ann_ret - RF * 100) / ann_vol if ann_vol > 0 else 0
    # max drawdown on log returns
    cum = 0; peak = 0; mdd = 0
    for x in rets:
        cum += np.log(1 + x / 100)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold)) if len(dn) > 1 else 0
    sortino = (ann_ret - RF * 100) / dn_std if dn_std > 0 else 0
    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0
    return {'trades': n, 'pos_rate': round(pos_rate, 1), 'avg': round(avg, 2),
            'sharpe': round(sharpe, 2), 'max_dd': round(mdd * 100, 2),
            'sortino': round(sortino, 2), 'plr': round(plr, 2)}

def run_backtest(sym_data, sym_scores, weak, hold_days, rsi_thresh, weak_thresh=0.7,
                 compound_fn=None, use_weak=True):
    results = {}
    for phase, (ps, pe) in PHASES.items():
        all_rets = []
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
                    if i + 1 + hold_days >= len(dates):
                        break

                    # Weak market filter
                    if use_weak and not weak.get(d, (0, 1))[1]:
                        i += 1; continue

                    # RSI filter
                    if np.isnan(rsi[i]) or rsi[i] >= rsi_thresh or rsi[i] < 10:
                        i += 1; continue

                    # Compound signal
                    if compound_fn and not compound_fn(sd, i):
                        i += 1; continue

                    bp = opens[i + 1]
                    sp = closes[i + 1 + hold_days]
                    if bp > 0 and not np.isnan(bp) and not np.isnan(sp):
                        ret = (sp - bp) / bp * 100 - COST
                        all_rets.append(ret)
                    i += hold_days + 1

            dt = me_dt.replace(day=1)

        results[phase] = calc_metrics(all_rets, hold_days)
    return results

# ===== LOAD DATA =====
t0 = time.time()
log("连接数据库...")
conn = sqlite3.connect(DB, timeout=120)

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
        SELECT trade_date, open, close, rsi14, boll_lower, ma20, volume, macd_hist
        FROM kline_daily WHERE symbol=? AND trade_date>='2020-12-01' AND trade_date<='2026-03-27'
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
    vol = np.array([r[6] if r[6] is not None else 0 for r in rows], dtype=float)
    macd_hist = np.array([r[7] if r[7] is not None else np.nan for r in rows], dtype=float)
    vol_ma5 = np.convolve(vol, np.ones(5)/5, mode='full')[:len(vol)]
    sym_data[sym] = {
        'dates': dates, 'open': opens, 'close': closes, 'rsi': rsi,
        'bb_lower': bb_lower, 'ma20': ma20, 'vol': vol, 'vol_ma5': vol_ma5,
        'macd_hist': macd_hist
    }
log(f"  K线: {len(sym_data)} 只 ({time.time()-t0:.1f}s)")

# Pre-compute weak market for multiple thresholds
log("计算弱市（多阈值）...")
all_dates = sorted(set(d for sd in sym_data.values() for d in sd['dates']))
weak_data = {}  # {date: (ratio, is_weak_70, is_weak_60, is_weak_80)}
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
    if total >= 20:
        ratio = below / total
        weak_data[d] = {
            'ratio': ratio,
            60: ratio > 0.6,
            70: ratio > 0.7,
            80: ratio > 0.8,
        }
log(f"  弱市: {len(weak_data)} 天 ({time.time()-t0:.1f}s)")

conn.close()
log(f"数据加载完成: {len(sym_data)} 只股票, {time.time()-t0:.1f}s")

# ===== STRATEGY SEARCH =====
all_results = []

def record(name, params, results):
    rec = {'name': name, 'params': params}
    for phase in ['train', 'val', 'test']:
        rec[phase] = results[phase]
    all_results.append(rec)
    t, v, te = results['train'], results['val'], results['test']
    log(f"  {name}: train={t['pos_rate']}%({t['trades']}) val={v['pos_rate']}%({v['trades']}) test={te['pos_rate']}%({te['trades']}) sharpe={te['sharpe']}")

# --- helper: wrap weak_data for run_backtest ---
def make_weak_lookup(thresh):
    """Return a dict compatible with run_backtest's weak.get(d, ...)"""
    return {d: (wd['ratio'], wd[thresh]) for d, wd in weak_data.items()}

# ===== Batch 1: RSI threshold x Hold days (with weak=70%) =====
log("\n" + "="*60)
log("BATCH 1: RSI threshold x Hold days (weak>70%)")
log("="*60)
weak70 = make_weak_lookup(70)
for rsi_t in [15, 18, 20, 25, 30]:
    for hold in [3, 5, 7, 10, 14]:
        name = f"RSI<{rsi_t}_hold{hold}d_weak70"
        params = {'rsi': f'<{rsi_t}', 'hold': hold, 'weak': '>70%', 'top': TOP_N, 'pit': 'dynamic'}
        res = run_backtest(sym_data, sym_scores, weak70, hold, rsi_t)
        record(name, params, res)

# ===== Batch 2: Weak market threshold optimization =====
log("\n" + "="*60)
log("BATCH 2: Weak market threshold (RSI<20, hold=7d)")
log("="*60)
for wthresh in [60, 70, 80]:
    wk = make_weak_lookup(wthresh)
    name = f"RSI20_hold7d_weak{wthresh}"
    params = {'rsi': '<20', 'hold': 7, 'weak': f'>{wthresh}%', 'top': TOP_N, 'pit': 'dynamic'}
    res = run_backtest(sym_data, sym_scores, wk, 7, 20)
    record(name, params, res)

# ===== Batch 3: Compound signals =====
log("\n" + "="*60)
log("BATCH 3: Compound signals (RSI<20, hold=7d, weak=70%)")
log("="*60)
compounds = {
    'bb_bottom': lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                and sd['close'][i] <= sd['bb_lower'][i] * 1.02),
    'vol_surge': lambda sd, i: sd['vol_ma5'][i] > 0 and sd['vol'][i] > sd['vol_ma5'][i] * 1.5,
    'macd_pos': lambda sd, i: not np.isnan(sd['macd_hist'][i]) and sd['macd_hist'][i] > 0,
    'macd_neg_small_rsi': lambda sd, i: (not np.isnan(sd['macd_hist'][i]) and sd['macd_hist'][i] < 0
                                         and not np.isnan(sd['rsi'][i]) and sd['rsi'][i] < 15),
    'bb_and_vol': lambda sd, i: (
        (not np.isnan(sd['bb_lower'][i]) and sd['close'][i] <= sd['bb_lower'][i] * 1.02) and
        (sd['vol_ma5'][i] > 0 and sd['vol'][i] > sd['vol_ma5'][i] * 1.3)
    ),
}
for cname, fn in compounds.items():
    for hold in [5, 7, 10]:
        name = f"RSI20_{cname}_hold{hold}d"
        params = {'rsi': '<20', 'hold': hold, 'compound': cname, 'weak': '>70%', 'top': TOP_N, 'pit': 'dynamic'}
        res = run_backtest(sym_data, sym_scores, weak70, hold, 20, compound_fn=fn)
        record(name, params, res)

# ===== Batch 4: No weak market filter =====
log("\n" + "="*60)
log("BATCH 4: No weak market filter (RSI<20, various holds)")
log("="*60)
for hold in [5, 7, 10]:
    name = f"RSI20_hold{hold}d_noweak"
    params = {'rsi': '<20', 'hold': hold, 'weak': 'none', 'top': TOP_N, 'pit': 'dynamic'}
    res = run_backtest(sym_data, sym_scores, {}, hold, 20, use_weak=False)
    record(name, params, res)

# ===== Batch 5: Tighter RSI + compound =====
log("\n" + "="*60)
log("BATCH 5: Tight RSI<15 + compounds (hold=7d)")
log("="*60)
for cname, fn in {'bb_bottom': compounds['bb_bottom'], 'vol_surge': compounds['vol_surge']}.items():
    name = f"RSI15_{cname}_hold7d"
    params = {'rsi': '<15', 'hold': 7, 'compound': cname, 'weak': '>70%', 'top': TOP_N, 'pit': 'dynamic'}
    res = run_backtest(sym_data, sym_scores, weak70, 7, 15, compound_fn=fn)
    record(name, params, res)

# ===== Batch 6: Different TOP_N =====
log("\n" + "="*60)
log("BATCH 6: Different TOP_N (RSI<20, hold=7d, weak=70%)")
log("="*60)
# Temporarily override TOP_N
_orig_top = TOP_N
for topn in [100, 150, 200, 300]:
    TOP_N = topn
    name = f"RSI20_hold7d_TOP{topn}"
    params = {'rsi': '<20', 'hold': 7, 'weak': '>70%', 'top': topn, 'pit': 'dynamic'}
    res = run_backtest(sym_data, sym_scores, weak70, 7, 20)
    record(name, params, res)
TOP_N = _orig_top

# ===== Filter & Sort =====
log("\n" + "="*60)
log("RESULTS SUMMARY")
log("="*60)

qualifiers = []
for rec in all_results:
    t, v, te = rec['train'], rec['val'], rec['test']
    if (t['pos_rate'] > 55 and v['pos_rate'] > 55 and te['pos_rate'] > 55
        and te['sharpe'] > 1.0):
        qualifiers.append(rec)

qualifiers.sort(key=lambda x: -x['test']['sharpe'])

print(f"\n{'Strategy':<40} {'Train%':>7} {'Val%':>7} {'Test%':>7} {'T#':>6} {'V#':>6} {'Te#':>6} {'Sharpe':>7} {'Sortino':>8}")
print("-" * 100)
for q in qualifiers:
    t, v, te = q['train'], q['val'], q['test']
    print(f"{q['name']:<40} {t['pos_rate']:>6.1f}% {v['pos_rate']:>6.1f}% {te['pos_rate']:>6.1f}% "
          f"{t['trades']:>6} {v['trades']:>6} {te['trades']:>6} {te['sharpe']:>7.2f} {te['sortino']:>8.2f}")

# Also show near-missers (>55% all phases but sharpe 0.5-1.0)
near_miss = []
for rec in all_results:
    if rec in qualifiers:
        continue
    t, v, te = rec['train'], rec['val'], rec['test']
    if (t['pos_rate'] > 55 and v['pos_rate'] > 55 and te['pos_rate'] > 55
        and te['sharpe'] > 0.5):
        near_miss.append(rec)
near_miss.sort(key=lambda x: -x['test']['sharpe'])

if near_miss:
    print(f"\n--- Near-miss (all >55%, Sharpe 0.5-1.0) ---")
    print(f"{'Strategy':<40} {'Train%':>7} {'Val%':>7} {'Test%':>7} {'T#':>6} {'V#':>6} {'Te#':>6} {'Sharpe':>7}")
    print("-" * 90)
    for q in near_miss:
        t, v, te = q['train'], q['val'], q['test']
        print(f"{q['name']:<40} {t['pos_rate']:>6.1f}% {v['pos_rate']:>6.1f}% {te['pos_rate']:>6.1f}% "
              f"{t['trades']:>6} {v['trades']:>6} {te['trades']:>6} {te['sharpe']:>7.2f}")

# Top performers by training positive rate (regardless of test sharpe)
print(f"\n--- Top by Train positive rate (all 3 phases >50%) ---")
top_train = []
for rec in all_results:
    t, v, te = rec['train'], rec['val'], rec['test']
    if t['pos_rate'] > 50 and v['pos_rate'] > 50 and te['pos_rate'] > 50:
        top_train.append(rec)
top_train.sort(key=lambda x: -x['train']['pos_rate'])
print(f"{'Strategy':<40} {'Train%':>7} {'Val%':>7} {'Test%':>7} {'T#':>6} {'V#':>6} {'Te#':>6} {'Sharpe':>7}")
print("-" * 90)
for q in top_train[:15]:
    t, v, te = q['train'], q['val'], q['test']
    print(f"{q['name']:<40} {t['pos_rate']:>6.1f}% {v['pos_rate']:>6.1f}% {te['pos_rate']:>6.1f}% "
          f"{t['trades']:>6} {v['trades']:>6} {te['trades']:>6} {te['sharpe']:>7.2f}")

# Save results
out_dir = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, 'strategy_search_v4_pit.json')
output = {
    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
    'total_tested': len(all_results),
    'qualifiers': len(qualifiers),
    'all_results': all_results,
    'qualifiers_sorted': qualifiers,
}
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)
log(f"\n结果保存到 {out_path}")
log(f"总计测试 {len(all_results)} 个策略, 符合条件 {len(qualifiers)} 个")
log(f"完成! 总耗时 {time.time()-t0:.1f}s")
