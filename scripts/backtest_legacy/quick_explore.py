#!/usr/bin/env python3
"""
Quick strategy exploration - v2 (PIT-compliant)
遵守项目目标：
  - 训练集选策略，验证/测试只做样本外检验
  - 所用数据必须在购买前可用（PIT：财报延迟45天）
  - A股 T+1 卖出约束
  - 三阶段正收益率 >55%
"""
import sqlite3, numpy as np, time, json
from datetime import datetime, timedelta
from bisect import bisect_right

DB = '/mnt/data/workspace/stock-monitor-app-py/data/stock_data.db'
TOP_N = 200
RF = 0.03
PIT_DELAY_DAYS = 45  # 财报发布后45天才能用

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-24'),
}

def fund_score(roe, rg, pg, gm, dr):
    roe = roe or 0; rg = rg or 0; pg = pg or 0; gm = gm or 0
    dr = dr if dr is not None else 100
    s = min(max(roe, 0), 30) + min(max(rg, 0) * 0.4, 20)
    s += min(max(pg, 0) * 0.4, 20) + min(max(gm, 0) * 0.3, 15)
    if dr < 30: s += 15
    elif dr < 50: s += 10
    elif dr < 70: s += 5
    return s

def calc_metrics(rets, hold):
    if not rets:
        return {'trades': 0, 'pos_rate': 0, 'avg': 0, 'sharpe': 0, 'max_dd': 0,
                'sortino': 0, 'win_rate': 0, 'plr': 0}
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
    cum = np.cumprod(1 + r / 100)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak
    max_dd = float(np.max(dd) * 100) if len(dd) > 0 else 0
    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold)) if len(dn) > 1 else 0
    sortino = (ann_ret - RF * 100) / dn_std if dn_std > 0 else 0
    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0
    return {'trades': n, 'pos_rate': round(pos_rate, 1), 'avg': round(avg, 2),
            'sharpe': round(sharpe, 2), 'max_dd': round(max_dd, 2),
            'sortino': round(sortino, 2), 'win_rate': round(pos_rate, 1),
            'plr': round(plr, 2)}

def run_backtest(sym_data, sym_scores_pit, hold_days, rsi_thresh, compound_fn=None):
    """
    Run backtest with PIT-compliant fundamentals.
    Args:
        sym_data: {symbol: {dates, open, close, rsi, macd_hist, bb_lower, vol, vol_ma5}}
        sym_scores_pit: {symbol: [(date, score), ...]} sorted by date
        hold_days: holding period
        rsi_thresh: RSI threshold
        compound_fn: optional compound signal function
    Returns: {train/val/test: metrics}
    """
    results = {}
    for phase, (ps, pe) in PHASES.items():
        all_rets = []
        # Monthly iteration for PIT-correct stock selection
        dt = datetime.strptime(ps, '%Y-%m-%d').replace(day=1)
        end_dt = datetime.strptime(pe, '%Y-%m-%d')

        while dt <= end_dt:
            ms = dt.strftime('%Y-%m-%d')
            me_dt = dt + timedelta(days=32)
            me = min(me_dt.replace(day=1).strftime('%Y-%m-%d'), pe)

            # Get top stocks this month using PIT scores
            scored = []
            for sym in sym_data:
                latest = 0
                for ad, sc in reversed(sym_scores_pit.get(sym, [])):
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

                    # Check RSI
                    if np.isnan(rsi[i]) or rsi[i] >= rsi_thresh or rsi[i] < 10:
                        i += 1; continue
                    # Compound signal
                    if compound_fn and not compound_fn(sd, i):
                        i += 1; continue

                    # Buy T+1 open, sell after hold_days close
                    bp = opens[i + 1]
                    sp = closes[i + 1 + hold_days]
                    if bp > 0 and not np.isnan(bp) and not np.isnan(sp):
                        ret = (sp - bp) / bp * 100
                        all_rets.append(ret)
                    # Skip holding period (no re-buy)
                    i += hold_days + 1

            dt = me_dt.replace(day=1)

        results[phase] = calc_metrics(all_rets, hold_days)
    return results

def load_data(conn):
    """Load all data with PIT-compliant fundamentals"""
    t0 = time.time()

    # Load PIT fundamental scores (rolling, with 45-day delay)
    print("Loading PIT fundamentals...", flush=True)
    fund_rows = conn.execute("""
        SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio
        FROM financial_indicators
        WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL OR profit_growth IS NOT NULL
        ORDER BY symbol, report_date
    """).fetchall()

    sym_scores = {}
    for sym, rd, roe, rg, pg, gm, dr in fund_rows:
        s = fund_score(roe, rg, pg, gm, dr)
        if s > 0:
            # PIT delay: score available after report_date + 45 days
            pit_date = (datetime.strptime(rd, '%Y-%m-%d') + timedelta(days=PIT_DELAY_DAYS)).strftime('%Y-%m-%d')
            if sym not in sym_scores:
                sym_scores[sym] = []
            sym_scores[sym].append((pit_date, s))

    print(f"  {len(sym_scores)} stocks with PIT scores", flush=True)

    # Load stock data
    print("Loading stock data...", flush=True)
    active = list(sym_scores.keys())
    sym_data = {}
    for sym in active:
        rows = conn.execute("""
            SELECT trade_date, open, close, rsi14, macd_hist, boll_lower, volume
            FROM kline_daily WHERE symbol=? AND trade_date>='2020-12-01' AND trade_date<='2026-03-24'
            ORDER BY trade_date
        """, (sym,)).fetchall()
        if len(rows) < 60:
            continue
        dates = [r[0] for r in rows]
        opens = np.array([r[1] for r in rows], dtype=float)
        closes = np.array([r[2] for r in rows], dtype=float)
        rsi = np.array([r[3] if r[3] is not None else np.nan for r in rows], dtype=float)
        macd_hist = np.array([r[4] if r[4] is not None else np.nan for r in rows], dtype=float)
        bb_lower = np.array([r[5] if r[5] is not None else np.nan for r in rows], dtype=float)
        vol = np.array([r[6] if r[6] is not None else 0 for r in rows], dtype=float)
        vol_ma5 = np.convolve(vol, np.ones(5) / 5, mode='full')[:len(vol)]
        sym_data[sym] = {
            'dates': dates, 'open': opens, 'close': closes, 'rsi': rsi,
            'macd_hist': macd_hist, 'bb_lower': bb_lower, 'vol': vol, 'vol_ma5': vol_ma5
        }
    print(f"  {len(sym_data)} stocks loaded", flush=True)

    # Pre-compute weak market (% stocks below MA20)
    print("Computing weak market...", flush=True)
    all_dates = set()
    for sd in sym_data.values():
        all_dates.update(sd['dates'])
    weak = {}
    for d in sorted(all_dates):
        total = below = 0
        for sd in sym_data.values():
            try:
                idx = sd['dates'].index(d)
                if idx >= 20:
                    ma20 = np.nanmean(sd['close'][max(0, idx - 19):idx + 1])
                    if not np.isnan(sd['close'][idx]) and not np.isnan(ma20):
                        total += 1
                        if sd['close'][idx] < ma20:
                            below += 1
            except ValueError:
                pass
        weak[d] = (total >= 20 and below / total > 0.7)

    print(f"  {len(weak)} dates computed in {time.time() - t0:.1f}s", flush=True)
    return sym_data, sym_scores, weak

def main():
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores, weak = load_data(conn)
    conn.close()

    all_results = {}

    # === Exp 1: RSI thresholds (hold=7d, no compound) ===
    print("\n" + "=" * 60)
    print("EXP1: RSI Threshold (hold=7d)")
    print("=" * 60)
    for thresh in [15, 18, 20, 25, 30]:
        print(f"\n  RSI<{thresh}:", flush=True)
        res = run_backtest(sym_data, sym_scores, 7, thresh)
        all_results[f'rsi{thresh}_7d'] = res
        for phase in ['train', 'val', 'test']:
            m = res[phase]
            print(f"    {phase}: {m['pos_rate']}% ({m['trades']}笔) sharpe={m['sharpe']}", flush=True)

    # === Exp 2: Holding days (RSI<20) ===
    print("\n" + "=" * 60)
    print("EXP2: Holding Days (RSI<20)")
    print("=" * 60)
    for hold in [5, 7, 10, 14, 20]:
        print(f"\n  Hold={hold}d:", flush=True)
        res = run_backtest(sym_data, sym_scores, hold, 20)
        all_results[f'rsi20_{hold}d'] = res
        for phase in ['train', 'val', 'test']:
            m = res[phase]
            print(f"    {phase}: {m['pos_rate']}% ({m['trades']}笔) sharpe={m['sharpe']}", flush=True)

    # === Exp 3: Compound signals (RSI<20, hold=10d) ===
    print("\n" + "=" * 60)
    print("EXP3: Compound Signals (RSI<20, hold=10d)")
    print("=" * 60)
    compounds = {
        'rsi20_only': None,
        'rsi20_macd_pos': lambda sd, i: not np.isnan(sd['macd_hist'][i]) and sd['macd_hist'][i] > 0,
        'rsi20_bb_bottom': lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                           and sd['close'][i] <= sd['bb_lower'][i] * 1.02),
        'rsi20_vol_surge': lambda sd, i: sd['vol_ma5'][i] > 0 and sd['vol'][i] > sd['vol_ma5'][i] * 1.5,
    }
    for name, fn in compounds.items():
        print(f"\n  {name}:", flush=True)
        res = run_backtest(sym_data, sym_scores, 10, 20, fn)
        all_results[f'compound_{name}'] = res
        for phase in ['train', 'val', 'test']:
            m = res[phase]
            print(f"    {phase}: {m['pos_rate']}% ({m['trades']}笔) sharpe={m['sharpe']}", flush=True)

    # === Summary: filter by >55% all phases ===
    print("\n" + "=" * 60)
    print("SUMMARY: All 3 phases >55% positive rate")
    print("=" * 60)
    print(f"\n{'Strategy':<30} {'Train%':>7} {'Val%':>7} {'Test%':>7} {'Train#':>7} {'Val#':>7} {'Test#':>7}")
    print("-" * 72)
    for name, res in sorted(all_results.items()):
        t, v, te = res['train'], res['val'], res['test']
        if t['pos_rate'] > 55 and v['pos_rate'] > 55 and te['pos_rate'] > 55:
            print(f"{name:<30} {t['pos_rate']:>6.1f}% {v['pos_rate']:>6.1f}% {te['pos_rate']:>6.1f}% "
                  f"{t['trades']:>7} {v['trades']:>7} {te['trades']:>7}")

    # Save
    out = '/mnt/data/workspace/stock-monitor-app-py/results/new_strategies_v2.json'
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")

if __name__ == '__main__':
    main()
