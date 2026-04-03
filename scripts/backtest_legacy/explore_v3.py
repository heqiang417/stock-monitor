#!/usr/bin/env python3
"""
Strategy exploration v3 - 熊市胜率突破专项
目标: 训练期(熊市)胜率 >55%

三阶段:
  - 训练: 2021-01-01 ~ 2024-06-30 (熊市)
  - 验证: 2024-07-01 ~ 2025-07-01 (牛市)
  - 测试: 2025-07-02 ~ 2026-03-24 (震荡)

合格标准:
  - 三阶段正率全部 >55%
  - 三阶段夏普全部 >1.0
  - 测试笔数 ≥10
"""
import sqlite3, numpy as np, time, json
from datetime import datetime, timedelta

DB = '/mnt/data/workspace/stock-monitor-app-py/data/stock_data.db'
RF = 0.03
PIT_DELAY_DAYS = 45

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
        return {'trades': 0, 'pos_rate': 0, 'avg': 0, 'sharpe': 0,
                'max_dd': 0, 'sortino': 0, 'win_rate': 0, 'plr': 0}
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

def load_data(conn):
    """Load all data with PIT-compliant fundamentals"""
    t0 = time.time()

    # Load PIT fundamental scores
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
            SELECT trade_date, open, close, rsi14, macd_hist, macd_dif, macd_dea,
                   boll_lower, volume, ma20
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
        macd_dif = np.array([r[5] if r[5] is not None else np.nan for r in rows], dtype=float)
        macd_dea = np.array([r[6] if r[6] is not None else np.nan for r in rows], dtype=float)
        bb_lower = np.array([r[7] if r[7] is not None else np.nan for r in rows], dtype=float)
        vol = np.array([r[8] if r[8] is not None else 0 for r in rows], dtype=float)
        ma20_arr = np.array([r[9] if r[9] is not None else np.nan for r in rows], dtype=float)
        vol_ma5 = np.convolve(vol, np.ones(5) / 5, mode='full')[:len(vol)]
        sym_data[sym] = {
            'dates': dates, 'open': opens, 'close': closes, 'rsi': rsi,
            'macd_hist': macd_hist, 'macd_dif': macd_dif, 'macd_dea': macd_dea,
            'bb_lower': bb_lower, 'vol': vol, 'vol_ma5': vol_ma5, 'ma20': ma20_arr
        }
    print(f"  {len(sym_data)} stocks loaded", flush=True)

    # Pre-compute weak market percentage
    print("Computing weak market...", flush=True)
    all_dates = set()
    for sd in sym_data.values():
        all_dates.update(sd['dates'])
    weak_pct = {}
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
        weak_pct[d] = below / total if total >= 20 else 0

    print(f"  {len(weak_pct)} dates computed in {time.time() - t0:.1f}s", flush=True)
    return sym_data, sym_scores, weak_pct

def macd_divergence(sd, i, lookback=20):
    """Check if MACD shows positive divergence: price making new low but DIF not making new low"""
    if i < lookback:
        return False
    price_now = sd['close'][i]
    dif_now = sd['macd_dif'][i]
    if np.isnan(price_now) or np.isnan(dif_now):
        return False
    # Current price should be near local minimum (within 5% of min in lookback window)
    window_prices = sd['close'][i-lookback:i+1]
    window_dif = sd['macd_dif'][i-lookback:i+1]
    min_price = np.nanmin(window_prices)
    if price_now > min_price * 1.05:
        return False
    # Find DIF at price minimum
    min_price_indices = np.where(window_prices <= min_price * 1.01)[0]
    if len(min_price_indices) == 0:
        return False
    dif_at_min = np.nanmin(window_dif[min_price_indices])
    # Positive divergence: DIF is higher now than at price low
    return dif_now > dif_at_min

def run_backtest(sym_data, sym_scores, weak_pct, hold_days, rsi_thresh,
                 weak_thresh=None, compound_fn=None, top_n=200):
    """
    Run backtest with PIT-compliant fundamentals.
    weak_thresh: if set, only trade when weak_pct[d] > weak_thresh
    """
    results = {}
    for phase, (ps, pe) in PHASES.items():
        all_rets = []
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
                for ad, sc in reversed(sym_scores.get(sym, [])):
                    if ad <= ms:
                        latest = sc
                        break
                if latest > 0:
                    scored.append((sym, latest))
            scored.sort(key=lambda x: -x[1])
            top = [s[0] for s in scored[:top_n]]

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
                    if weak_thresh is not None:
                        pct = weak_pct.get(d, 0)
                        if pct <= weak_thresh:
                            i += 1; continue

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
                    # Skip holding period
                    i += hold_days + 1

            dt = me_dt.replace(day=1)

        results[phase] = calc_metrics(all_rets, hold_days)

    return results

def check_qualified(res):
    t, v, te = res['train'], res['val'], res['test']
    return (t['pos_rate'] > 55 and v['pos_rate'] > 55 and te['pos_rate'] > 55
            and t['sharpe'] > 1.0 and v['sharpe'] > 1.0 and te['sharpe'] > 1.0
            and te['trades'] >= 10)

def print_result(label, res):
    t, v, te = res['train'], res['val'], res['test']
    qual = check_qualified(res)
    marker = " ★" if qual else ""
    sharpe_str = f"sharpe={t['sharpe']}/{v['sharpe']}/{te['sharpe']}"
    print(f"  {label}: train={t['pos_rate']}%({t['trades']}笔) val={v['pos_rate']}%({v['trades']}笔) "
          f"test={te['pos_rate']}%({te['trades']}笔) {sharpe_str}{marker}")

def main():
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores, weak_pct = load_data(conn)
    conn.close()

    all_results = {}
    qualified = []

    # Helper to run experiment
    def exp(name, label, hold_days, rsi_thresh, weak_thresh=None,
            compound_fn=None, top_n=200):
        res = run_backtest(sym_data, sym_scores, weak_pct, hold_days, rsi_thresh,
                           weak_thresh=weak_thresh, compound_fn=compound_fn, top_n=top_n)
        all_results[name] = res
        print_result(label, res)
        if check_qualified(res):
            qualified.append((name, res, label))
        return res

    # ========== Exp A: TOP N expansion ==========
    print("\n" + "=" * 70)
    print("EXP A: TOP N Expansion (RSI<20, hold=7d, BB触底1.02)")
    print("=" * 70)
    for top_n in [200, 300, 500, 1000]:
        for hold in [5, 7]:
            compound = lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                       and sd['close'][i] <= sd['bb_lower'][i] * 1.02)
            label = f"TOP{top_n}_hold{hold}d_BB"
            name = f"top{top_n}_hold{hold}d_bb"
            exp(name, label, hold, 20, compound_fn=compound, top_n=top_n)

    # ========== Exp B: Weak market thresholds ==========
    print("\n" + "=" * 70)
    print("EXP B: Weak Market Thresholds (TOP500, RSI<20, hold=7d, BB触底)")
    print("=" * 70)
    for wm_thresh in [0.65, 0.70, 0.75, 0.80]:
        compound = lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                   and sd['close'][i] <= sd['bb_lower'][i] * 1.02)
        label = f"WM>{int(wm_thresh*100)}%_TOP500_hold7d_BB"
        name = f"wm{int(wm_thresh*100)}_top500_hold7d_bb"
        exp(name, label, 7, 20, weak_thresh=wm_thresh, compound_fn=compound, top_n=500)

    # ========== Exp C: Compound signal refinements ==========
    print("\n" + "=" * 70)
    print("EXP C: Compound Signal Refinements (TOP500, RSI<20, hold=7d)")
    print("=" * 70)

    # C1: BB触底 + 放量2x
    compound_c1 = lambda sd, i: (
        (not np.isnan(sd['bb_lower'][i]) and sd['close'][i] <= sd['bb_lower'][i] * 1.02) and
        (sd['vol_ma5'][i] > 0 and sd['vol'][i] > sd['vol_ma5'][i] * 2.0)
    )
    exp('c1_bb_vol2x', "BB_touch+VOL2x", 7, 20, compound_fn=compound_c1, top_n=500)

    # C2: BB触底 + 放量1.5x
    compound_c2 = lambda sd, i: (
        (not np.isnan(sd['bb_lower'][i]) and sd['close'][i] <= sd['bb_lower'][i] * 1.02) and
        (sd['vol_ma5'][i] > 0 and sd['vol'][i] > sd['vol_ma5'][i] * 1.5)
    )
    exp('c2_bb_vol1.5x', "BB_touch+VOL1.5x", 7, 20, compound_fn=compound_c2, top_n=500)

    # C3: 严格BB触底 (close < bb_lower, not <=)
    compound_c3 = lambda sd, i: (
        not np.isnan(sd['bb_lower'][i]) and sd['close'][i] < sd['bb_lower'][i]
    )
    exp('c3_bb_strict', "BB_strict_touch", 7, 20, compound_fn=compound_c3, top_n=500)

    # C4: RSI<15 / RSI<18 with TOP500
    for rsi_t in [15, 18]:
        compound = lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                   and sd['close'][i] <= sd['bb_lower'][i] * 1.02)
        label = f"RSI<{rsi_t}_BB_TOP500_hold7d"
        name = f'c4_rsi{rsi_t}_bb_top500_hold7d'
        exp(name, label, 7, rsi_t, compound_fn=compound, top_n=500)

    # ========== Exp D: MACD 底背离 ==========
    print("\n" + "=" * 70)
    print("EXP D: MACD Positive Divergence (TOP500, hold=7d)")
    print("=" * 70)
    for rsi_t in [20, 25, 30]:
        label = f"MACD_div_RSI<{rsi_t}_TOP500"
        name = f'macd_div_rsi{rsi_t}_top500'
        exp(name, label, 7, rsi_t, compound_fn=macd_divergence, top_n=500)

    # MACD底背离 + BB触底
    for rsi_t in [20, 25]:
        def compound_d(sd, i):
            return (macd_divergence(sd, i) and
                    not np.isnan(sd['bb_lower'][i]) and
                    sd['close'][i] <= sd['bb_lower'][i] * 1.02)
        label = f"MACD_div+BB_RSI<{rsi_t}_TOP500"
        name = f'macd_div_bb_rsi{rsi_t}_top500'
        exp(name, label, 7, rsi_t, compound_fn=compound_d, top_n=500)

    # ========== Exp E: RSI threshold fine-tuning ==========
    print("\n" + "=" * 70)
    print("EXP E: RSI Fine-tuning (TOP500, hold=7d, BB触底)")
    print("=" * 70)
    for rsi_t in [16, 17, 18, 19, 20, 22]:
        compound = lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                   and sd['close'][i] <= sd['bb_lower'][i] * 1.02)
        label = f"RSI<{rsi_t}_BB_TOP500_hold7d"
        name = f'e_rsi{rsi_t}_bb_top500_hold7d'
        exp(name, label, 7, rsi_t, compound_fn=compound, top_n=500)

    # ========== Exp F: hold5 vs hold7 more granular ==========
    print("\n" + "=" * 70)
    print("EXP F: Hold5 vs Hold7 with TOP300/500 (RSI<20, BB触底)")
    print("=" * 70)
    for top_n in [300, 500]:
        for hold in [5, 6, 7, 8]:
            compound = lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                       and sd['close'][i] <= sd['bb_lower'][i] * 1.02)
            label = f"TOP{top_n}_hold{hold}d"
            name = f"f_top{top_n}_hold{hold}d"
            exp(name, label, hold, 20, compound_fn=compound, top_n=top_n)

    # ========== Exp G: TOP500 + BB触底 + 弱市分级 + RSI微调 ==========
    print("\n" + "=" * 70)
    print("EXP G: TOP500 + BB触底 + 弱市70%+ RSI微调")
    print("=" * 70)
    for rsi_t in [18, 20, 22]:
        compound = lambda sd, i: (not np.isnan(sd['bb_lower'][i])
                                   and sd['close'][i] <= sd['bb_lower'][i] * 1.02)
        label = f"WM70%_RSI<{rsi_t}_TOP500_hold7d"
        name = f'g_wm70_rsi{rsi_t}_top500_hold7d'
        exp(name, label, 7, rsi_t, weak_thresh=0.70, compound_fn=compound, top_n=500)

    # ========== Summary ==========
    print("\n" + "=" * 70)
    print(f"QUALIFIED: {len(qualified)} strategies")
    print("=" * 70)
    if qualified:
        print(f"\n{'Strategy':<35} {'Train%':>7} {'Val%':>7} {'Test%':>7} "
              f"{'TrainS':>7} {'ValS':>7} {'TestS':>7} {'#Test':>6}")
        print("-" * 85)
        for name, res, label in sorted(qualified, key=lambda x: -x[1]['test']['pos_rate']):
            t, v, te = res['train'], res['val'], res['test']
            print(f"{label:<35} {t['pos_rate']:>6.1f}% {v['pos_rate']:>6.1f}% {te['pos_rate']:>6.1f}% "
                  f"{t['sharpe']:>7.2f} {v['sharpe']:>7.2f} {te['sharpe']:>7.2f} {te['trades']:>6}")
    else:
        print("  No strategies passed all criteria.")

    # All with train>55%
    print("\n" + "=" * 70)
    print("ALL RESULTS (train positive rate >55%)")
    print("=" * 70)
    print(f"\n{'Strategy':<35} {'Train%':>7} {'Val%':>7} {'Test%':>7} "
          f"{'TrainS':>7} {'ValS':>7} {'TestS':>7} {'#Test':>6}")
    print("-" * 85)
    for name, res in sorted(all_results.items(),
                            key=lambda x: -(x[1]['train']['pos_rate'])):
        t, v, te = res['train'], res['val'], res['test']
        if t['pos_rate'] > 55:
            marker = "★" if check_qualified(res) else ""
            print(f"{name:<35} {t['pos_rate']:>6.1f}% {v['pos_rate']:>6.1f}% {te['pos_rate']:>6.1f}% "
                  f"{t['sharpe']:>7.2f} {v['sharpe']:>7.2f} {te['sharpe']:>7.2f} {te['trades']:>6} {marker}")

    # Save
    import os
    os.makedirs('/mnt/data/workspace/stock-monitor-app-py/data/results', exist_ok=True)
    out = '/mnt/data/workspace/stock-monitor-app-py/data/results/strategy_exploration_v3.json'
    with open(out, 'w') as f:
        json.dump({k: {phase: dict(v) for phase, v in res.items()}
                   for k, res in all_results.items()}, f, indent=2, default=str)
    print(f"\nResults saved to {out}")

if __name__ == '__main__':
    main()
