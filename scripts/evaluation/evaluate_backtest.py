#!/usr/bin/env python3
"""
策略回测评估（官方版）
与 daily_pick.py 完全对齐的回测逻辑：月度 PIT 选股 + 每日弱市检查 + 固定持有 + 持仓跳过

用法:
  python3 evaluate_backtest.py                    # 默认跑 V4 + BB 对比
  python3 evaluate_backtest.py --hold 7           # 指定持有天数
  python3 evaluate_backtest.py --rsi 18           # 指定 RSI 阈值
  python3 evaluate_backtest.py --no-bb            # 只跑 V4，不跑 BB
  python3 evaluate_backtest.py --output my_eval   # 自定义输出目录名

输出: data/results/eval_{output}/evaluate_result.json + .md
"""
import sqlite3, numpy as np, json, os, argparse, time
from datetime import datetime, timedelta

DB = '/mnt/data/workspace/stock-monitor-app-py/data/stock_data.db'
RESULTS_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'
TOP_N = 200
RF = 0.03
PIT_DELAY = 45

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-24'),
}

# === PIT 基本面评分（与 quick_explore.py 一致）===
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
        return {'trades':0,'pos_rate':0,'avg':0,'sharpe':0,'max_dd':0,'sortino':0,'win_rate':0,'plr':0}
    r = np.array(rets); n = len(r)
    pos = r[r > 0]; neg = r[r < 0]
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

def run_backtest(sym_data, sym_scores_pit, hold_days, rsi_thresh, weak_dates, compound_fn=None):
    """每日迭代：检查弱市→月度 PIT TOP200→RSI 阈值→复合信号→固定持有"""
    all_dates_sorted = sorted(set(d for sd in sym_data.values() for d in sd['dates']))

    # 月度 TOP200 缓存
    monthly_top = {}
    dt = datetime.strptime(all_dates_sorted[0], '%Y-%m-%d').replace(day=1)
    end_dt = datetime.strptime(all_dates_sorted[-1], '%Y-%m-%d')
    while dt <= end_dt:
        ms = dt.strftime('%Y-%m-%d')
        me_dt = dt + timedelta(days=32)
        scored = []
        for sym in sym_data:
            latest = 0
            for ad, sc in reversed(sym_scores_pit.get(sym, [])):
                if ad <= ms: latest = sc; break
            if latest > 0: scored.append((sym, latest))
        scored.sort(key=lambda x: -x[1])
        monthly_top[ms] = set(s[0] for s in scored[:TOP_N])
        dt = me_dt.replace(day=1)

    results = {}
    for phase, (ps, pe) in PHASES.items():
        all_rets = []
        date_to_idx = {d: i for i, d in enumerate(all_dates_sorted)}
        for d in all_dates_sorted:
            if d < ps or d > pe: continue
            if not weak_dates.get(d, False): continue
            idx = date_to_idx[d]
            if idx + 1 + hold_days >= len(all_dates_sorted): continue
            dt_d = datetime.strptime(d, '%Y-%m-%d')
            ms = dt_d.replace(day=1).strftime('%Y-%m-%d')
            top = monthly_top.get(ms, set())
            if not top: continue
            for sym in top:
                if sym not in sym_data: continue
                sd = sym_data[sym]
                if d not in sd['dates']: continue
                i = sd['dates'].index(d)
                if i + 1 + hold_days >= len(sd['dates']): continue
                if np.isnan(sd['rsi'][i]) or sd['rsi'][i] >= rsi_thresh or sd['rsi'][i] < 10: continue
                if compound_fn and not compound_fn(sd, i): continue
                bp = sd['open'][i + 1]
                sp = sd['close'][i + 1 + hold_days]
                if bp > 0 and not np.isnan(bp) and not np.isnan(sp):
                    all_rets.append((sp - bp) / bp * 100)
        results[phase] = calc_metrics(all_rets, hold_days)
    return results

def load_data():
    t0 = time.time()
    conn = sqlite3.connect(DB, timeout=120)

    print("Loading PIT fundamentals...", flush=True)
    fund_rows = conn.execute("""
        SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio
        FROM financial_indicators WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL
        ORDER BY symbol, report_date
    """).fetchall()
    sym_scores = {}
    for sym, rd, roe, rg, pg, gm, dr in fund_rows:
        s = fund_score(roe, rg, pg, gm, dr)
        if s > 0:
            pit_date = (datetime.strptime(rd, '%Y-%m-%d') + timedelta(days=PIT_DELAY)).strftime('%Y-%m-%d')
            if sym not in sym_scores: sym_scores[sym] = []
            sym_scores[sym].append((pit_date, s))
    print(f"  {len(sym_scores)} stocks with PIT scores", flush=True)

    print("Loading stock data...", flush=True)
    sym_data = {}
    for sym in sym_scores:
        rows = conn.execute("""
            SELECT trade_date, open, close, rsi14, boll_lower
            FROM kline_daily WHERE symbol=? AND trade_date>='2020-12-01' AND trade_date<='2026-03-24'
            ORDER BY trade_date
        """, (sym,)).fetchall()
        if len(rows) < 60: continue
        dates = [r[0] for r in rows]
        opens = np.array([r[1] for r in rows], dtype=float)
        closes = np.array([r[2] for r in rows], dtype=float)
        rsi = np.array([r[3] if r[3] is not None else np.nan for r in rows], dtype=float)
        bb_lower = np.array([r[4] if r[4] is not None else np.nan for r in rows], dtype=float)
        sym_data[sym] = {'dates': dates, 'open': opens, 'close': closes, 'rsi': rsi, 'bb_lower': bb_lower}
    print(f"  {len(sym_data)} stocks loaded", flush=True)

    print("Computing weak market...", flush=True)
    all_dates = set()
    for sd in sym_data.values(): all_dates.update(sd['dates'])
    weak = {}
    for d in sorted(all_dates):
        total = below = 0
        for sd in sym_data.values():
            try:
                idx = sd['dates'].index(d)
                if idx >= 20:
                    ma20 = np.nanmean(sd['close'][max(0,idx-19):idx+1])
                    if not np.isnan(sd['close'][idx]) and not np.isnan(ma20):
                        total += 1
                        if sd['close'][idx] < ma20: below += 1
            except ValueError: pass
        weak[d] = (total >= 20 and below / total > 0.7)
    print(f"  {len(weak)} dates ({time.time()-t0:.1f}s)", flush=True)
    conn.close()
    return sym_data, sym_scores, weak

def main():
    parser = argparse.ArgumentParser(description='策略回测评估')
    parser.add_argument('--hold', type=int, default=10, help='持有天数 (default: 10)')
    parser.add_argument('--rsi', type=int, default=20, help='RSI 阈值 (default: 20)')
    parser.add_argument('--no-bb', action='store_true', help='不跑 BB 对比')
    parser.add_argument('--output', type=str, default=None, help='输出目录名')
    args = parser.parse_args()

    output_name = args.output or f'eval_rsi{args.rsi}_hold{args.hold}'
    output_dir = os.path.join(RESULTS_DIR, output_name)
    os.makedirs(output_dir, exist_ok=True)

    sym_data, sym_scores, weak = load_data()

    strategies = {f'RSI<{args.rsi}+弱市70+TOP200+{args.hold}天': (args.rsi, None)}
    if not args.no_bb:
        strategies[f'RSI<{args.rsi}+BB触底+弱市70+TOP200+{args.hold}天'] = (
            args.rsi,
            lambda sd, i: (not np.isnan(sd['bb_lower'][i]) and sd['close'][i] <= sd['bb_lower'][i] * 1.02)
        )

    all_results = {}
    for name, (thresh, fn) in strategies.items():
        print(f"\nRunning: {name}", flush=True)
        res = run_backtest(sym_data, sym_scores, args.hold, thresh, weak, fn)
        all_results[name] = res
        for phase in ['train', 'val', 'test']:
            m = res[phase]
            print(f"  {phase}: {m['pos_rate']}% ({m['trades']}笔) sharpe={m['sharpe']} sortino={m['sortino']} max_dd={m['max_dd']}%", flush=True)

    # Save
    with open(os.path.join(output_dir, "evaluate_result.json"), "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    md = [f"# 策略回测评估\n\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    md += [f"## 参数\n- RSI 阈值: {args.rsi}\n- 持有天数: {args.hold}\n- PIT 延迟: {PIT_DELAY}天\n- TOP{TOP_N} 基本面筛选\n"]
    md += ["## 对比总览\n"]
    md += ["| 策略 | 阶段 | 笔数 | 正率 | 平均收益 | 夏普 | 索提诺 | 最大回撤 | 盈亏比 |"]
    md += ["|------|------|------|------|---------|------|--------|---------|--------|"]
    for name, res in all_results.items():
        for phase, label in [('train','训练'),('val','验证'),('test','测试')]:
            m = res[phase]
            md.append(f"| {name} | {label} | {m['trades']} | {m['pos_rate']}% | {m['avg']}% | {m['sharpe']} | {m['sortino']} | {m['max_dd']}% | {m['plr']} |")
    with open(os.path.join(output_dir, "evaluate_result.md"), "w") as f:
        f.write("\n".join(md))

    print(f"\nSaved to {output_dir}/")

if __name__ == '__main__':
    main()
