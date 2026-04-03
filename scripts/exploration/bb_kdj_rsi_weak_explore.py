#!/usr/bin/env python3
"""
BB + KDJ + RSI + 弱市过滤 扩展探索
在 BB1.02 + KDJ Oversold + RSI<20 基础上测试：
  1. 有/无弱市过滤（个股MA20宽度 vs 指数MA20）
  2. 不同弱市阈值
  3. 更多TOP N规模
"""
import sqlite3, json, time, os
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

DB = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
OUTPUT_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'
os.makedirs(OUTPUT_DIR, exist_ok=True)

PHASES = {'train': ('2021-01-01', '2024-06-30'), 'val': ('2024-07-01', '2025-07-01'), 'test': ('2025-07-02', '2026-03-24')}
RF = 0.03; COST = 0.30

def pit_delay_days(s):
    m = int(s[5:7])
    return {3:30, 6:62, 9:31, 12:120}.get(m, 45)

def pit_effective_date(s):
    return (datetime.strptime(s, '%Y-%m-%d') + timedelta(days=pit_delay_days(s))).strftime('%Y-%m-%d')

def fund_score(roe, rev_g, profit_g, gross_margin, debt_ratio):
    roe = roe or 0; rev_g = rev_g or 0; profit_g = profit_g or 0
    gross_margin = gross_margin or 0
    debt_ratio = debt_ratio if debt_ratio is not None else 100
    s = min(max(roe, 0), 30)
    s += min(max(rev_g, 0) * 0.4, 20)
    s += min(max(profit_g, 0) * 0.4, 20)
    s += min(max(gross_margin, 0) * 0.3, 15)
    if debt_ratio < 30: s += 15
    elif debt_ratio < 50: s += 10
    elif debt_ratio < 70: s += 5
    return s

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def calc_28_metrics(rets, hold_days, hit_stock_count=0):
    if not rets:
        return {k: 0 for k in ['total_trades','positive_rate','avg_return','median_return','max_return','min_return','hit_stocks','sharpe','max_drawdown','volatility','downside_volatility','sortino','win_rate','profit_loss_ratio','avg_win','avg_loss','max_win','max_loss','max_consec_wins','max_consec_losses','annual_return','calmar','recovery_factor','breakeven_wr','expectancy','train_test_ratio','three_phase_consistency','avg_hold_days']}
    r = np.array(rets); n = len(r)
    pos = r[r > 0]; neg = r[r <= 0]
    pos_rate = len(pos) / n * 100
    avg_ret = float(np.mean(r)); median_ret = float(np.median(r))
    max_ret = float(max(r)); min_ret = float(min(r))
    ann_ret = avg_ret * 252 / hold_days
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_vol = std * np.sqrt(252 / hold_days)
    sharpe = (ann_ret - RF * 100) / ann_vol if ann_vol > 0 else 0
    cum = 0; peak = 0; mdd = 0
    for x in rets:
        cum += np.log(1 + x / 100); peak = max(peak, cum); mdd = max(mdd, peak - cum)
    dn = r[r < 0]; dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold_days)) if len(dn) > 1 else 0
    sortino = (ann_ret - RF * 100) / dn_std if dn_std > 0 else 0
    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0
    cw = cl = cwmax = clmax = 0
    for x in rets:
        if x > 0: cw += 1; cl = 0; cwmax = max(cwmax, cw)
        else: cl += 1; cw = 0; clmax = max(clmax, cl)
    expectancy = float(len(pos)/n * np.mean(pos) + len(neg)/n * np.mean(neg)) if len(neg) > 0 else avg_ret
    total_ret = sum(rets); recovery_factor = total_ret / abs(mdd * 100) if mdd > 0.0001 else 0
    be_wr = 1 / (1 + plr) * 100 if plr > 0 else 100
    return {'total_trades': n, 'positive_rate': round(pos_rate, 2), 'avg_return': round(avg_ret, 4), 'median_return': round(median_ret, 4), 'max_return': round(max_ret, 4), 'min_return': round(min_ret, 4), 'hit_stocks': hit_stock_count, 'sharpe': round(sharpe, 4), 'max_drawdown': round(mdd * 100, 4), 'volatility': round(ann_vol, 4), 'downside_volatility': round(dn_std, 4), 'sortino': round(sortino, 4), 'win_rate': round(pos_rate, 2), 'profit_loss_ratio': round(plr, 4), 'avg_win': round(float(np.mean(pos)), 4) if len(pos) > 0 else 0, 'avg_loss': round(float(np.mean(neg)), 4) if len(neg) > 0 else 0, 'max_win': round(max_ret, 4), 'max_loss': round(min_ret, 4), 'max_consec_wins': cwmax, 'max_consec_losses': clmax, 'annual_return': round(ann_ret, 4), 'calmar': round(ann_ret / (mdd * 100), 4) if mdd > 0.0001 else 0, 'recovery_factor': round(recovery_factor, 4), 'breakeven_wr': round(be_wr, 2), 'expectancy': round(expectancy, 4), 'train_test_ratio': 0, 'three_phase_consistency': 0, 'avg_hold_days': hold_days}

def load_data(conn):
    t0 = time.time()
    log("加载PIT基本面...")
    fund_rows = conn.execute("""SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio FROM financial_indicators WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL OR profit_growth IS NOT NULL ORDER BY symbol, report_date""").fetchall()
    sym_scores_pit = defaultdict(list)
    for sym, rd, roe, rg, pg, gm, dr in fund_rows:
        s = fund_score(roe, rg, pg, gm, dr)
        if s > 0:
            pit_date = pit_effective_date(rd)
            sym_scores_pit[sym].append((pit_date, s))
    log(f"  {len(sym_scores_pit)} 股票有PIT分数")

    log("加载K线数据...")
    active = list(sym_scores_pit.keys())
    sym_data = {}
    for sym in active:
        rows = conn.execute("""SELECT trade_date, open, close, high, low, volume, rsi14, macd_hist, boll_lower, kdj_k, kdj_d, kdj_j FROM kline_daily WHERE symbol=? AND trade_date>='2020-12-01' AND trade_date<='2026-03-31' ORDER BY trade_date""", (sym,)).fetchall()
        if len(rows) < 60: continue
        dates = [r[0] for r in rows]
        opens = np.array([r[1] for r in rows], dtype=float)
        closes = np.array([r[2] for r in rows], dtype=float)
        highs = np.array([r[3] for r in rows], dtype=float)
        lows = np.array([r[4] for r in rows], dtype=float)
        vols = np.array([r[5] for r in rows], dtype=float)
        rsi = np.array([r[6] if r[6] is not None else np.nan for r in rows], dtype=float)
        macd_hist = np.array([r[7] if r[7] is not None else np.nan for r in rows], dtype=float)
        bb_lower = np.array([r[8] if r[8] is not None else np.nan for r in rows], dtype=float)
        kdj_k = np.array([r[9] if r[9] is not None else np.nan for r in rows], dtype=float)
        kdj_d = np.array([r[10] if r[10] is not None else np.nan for r in rows], dtype=float)
        kdj_j = np.array([r[11] if r[11] is not None else np.nan for r in rows], dtype=float)
        sym_data[sym] = {'dates': dates, 'open': opens, 'close': closes, 'high': highs, 'low': lows, 'vol': vols, 'rsi': rsi, 'macd_hist': macd_hist, 'bb_lower': bb_lower, 'kdj_k': kdj_k, 'kdj_d': kdj_d, 'kdj_j': kdj_j}
    log(f"  {len(sym_data)} 股票已加载 ({time.time()-t0:.1f}s)")

    log("计算弱市标记（个股MA20宽度）...")
    all_dates = sorted(set(d for sd in sym_data.values() for d in sd['dates']))
    weak_width = {}
    for d in all_dates:
        total = below = 0
        for sd in sym_data.values():
            try:
                idx = sd['dates'].index(d)
                if idx >= 20:
                    ma20 = np.nanmean(sd['close'][max(0, idx-19):idx+1])
                    c = sd['close'][idx]
                    if not np.isnan(c) and not np.isnan(ma20):
                        total += 1
                        if c < ma20: below += 1
            except ValueError: pass
        weak_width[d] = (total >= 20 and below / total > 0.7)
    log(f"  个股MA20弱市标记完成 ({time.time()-t0:.1f}s)")

    # 加载沪深300指数计算MA20弱市
    log("计算指数MA20弱市标记（沪深300）...")
    idx_rows = conn.execute("""SELECT trade_date, close FROM kline_daily WHERE symbol='sh000300' ORDER BY trade_date""").fetchall()
    idx_dates = [r[0] for r in idx_rows]
    idx_closes = np.array([r[1] for r in idx_rows], dtype=float)
    weak_idx_ma20 = {}
    for i, d in enumerate(idx_dates):
        if i >= 20:
            ma20 = np.nanmean(idx_closes[i-19:i+1])
            c = idx_closes[i]
            if not np.isnan(c) and not np.isnan(ma20):
                weak_idx_ma20[d] = (c < ma20)
    log(f"  指数MA20弱市标记完成 ({time.time()-t0:.1f}s)")

    return sym_data, dict(sym_scores_pit), weak_width, weak_idx_ma20

def run_backtest(sym_data, sym_scores_pit, weak_width, weak_idx_ma20,
                 hold_days, top_n, bb_mult, kdj_filter, rsi_mode,
                 weak_type='width70'):  # 'none', 'width70', 'idx_ma20'
    results = {}
    for phase, (ps, pe) in PHASES.items():
        all_rets = []; hit_stocks_set = set()
        dt = datetime.strptime(ps, '%Y-%m-%d').replace(day=1)
        end_dt = datetime.strptime(pe, '%Y-%m-%d')

        while dt <= end_dt:
            ms = dt.strftime('%Y-%m-%d')
            me_dt = dt + timedelta(days=32)
            me = min(me_dt.replace(day=1).strftime('%Y-%m-%d'), pe)

            scored = []
            for sym in sym_data:
                latest = 0
                for ad, sc in reversed(sym_scores_pit.get(sym, [])):
                    if ad <= ms: latest = sc; break
                if latest > 0: scored.append((sym, latest))
            scored.sort(key=lambda x: -x[1]); top = [s[0] for s in scored[:top_n]]

            for sym in top:
                if sym not in sym_data: continue
                sd = sym_data[sym]; dates = sd['dates']; closes = sd['close']; opens = sd['open']
                rsi = sd['rsi']; bb_l = sd['bb_lower']
                k_k = sd['kdj_k']; k_d = sd['kdj_d']; k_j = sd['kdj_j']

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < ms: i += 1; continue
                    if d >= me: break
                    if i + 1 + hold_days >= len(dates): break

                    # 弱市过滤
                    if weak_type == 'width70' and not weak_width.get(d, False): i += 1; continue
                    if weak_type == 'idx_ma20' and not weak_idx_ma20.get(d, False): i += 1; continue

                    # RSI 过滤
                    if np.isnan(rsi[i]) or rsi[i] >= 20: i += 1; continue
                    if rsi_mode == 'strict' and rsi[i] < 10: i += 1; continue

                    # 布林带过滤
                    price = closes[i]
                    if not np.isnan(bb_l[i]) and bb_l[i] > 0:
                        if price > bb_l[i] * bb_mult: i += 1; continue
                    else: i += 1; continue

                    # KDJ 过滤
                    if kdj_filter and not np.isnan(k_k[i]) and not np.isnan(k_d[i]):
                        if kdj_filter in ('oversold', 'both'):
                            if not (k_k[i] < 20 or k_j[i] < 0): i += 1; continue
                        if kdj_filter in ('golden_cross', 'both'):
                            if i > 0 and not np.isnan(k_k[i-1]) and not np.isnan(k_d[i-1]):
                                crossed = k_k[i] > k_d[i] and k_k[i-1] <= k_d[i-1]
                                if not crossed: i += 1; continue
                            else: i += 1; continue

                    bp = opens[i + 1]; sp = closes[i + 1 + hold_days]
                    if bp > 0 and not np.isnan(bp) and not np.isnan(sp):
                        ret = (sp - bp) / bp * 100 - COST
                        all_rets.append(ret); hit_stocks_set.add(sym)
                    i += hold_days + 1

            dt = me_dt.replace(day=1)

        metrics = calc_28_metrics(all_rets, hold_days, len(hit_stocks_set))
        results[phase] = {'metrics': metrics, 'trades': len(all_rets), 'hit_stocks': len(hit_stocks_set)}

    pos_rates = [results[p]['metrics']['positive_rate'] for p in ['train', 'val', 'test']]
    consistency = sum(1 for pr in pos_rates if pr >= 55) / 3 * 100
    for phase in results:
        results[phase]['metrics']['three_phase_consistency'] = round(consistency, 2)
    return results

def main():
    t0 = time.time()
    log("连接数据库...")
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores_pit, weak_width, weak_idx_ma20 = load_data(conn)
    conn.close()

    # 要测试的参数组合
    # 基础: BB1.02 + KDJ Oversold + RSI<20 near_oversold + TOP300 + 7天
    # 变体: 有/无弱市(x3) x TOP N(x3) x 持有期(x2)
    combos = []
    for weak_type in ['none', 'width70', 'idx_ma20']:
        for top_n in [200, 300, 500]:
            for hold in [7, 10]:
                combos.append({
                    'bb_mult': 1.02,
                    'hold_days': hold,
                    'top_n': top_n,
                    'kdj_filter': 'oversold',
                    'rsi_mode': 'near_oversold',
                    'weak_type': weak_type,
                })

    log(f"共 {len(combos)} 个组合待测")
    all_results = {}

    for idx, combo in enumerate(combos):
        label = f"BB{combo['bb_mult']}_H{combo['hold_days']}_TOP{combo['top_n']}_KDJoversold_RSInear_weak{combo['weak_type']}"
        log(f"\n[{idx+1}/{len(combos)}] {label}")
        try:
            res = run_backtest(sym_data, sym_scores_pit, weak_width, weak_idx_ma20, **combo)
        except Exception as e:
            log(f"  ERROR: {e}"); continue

        for phase in ['train', 'val', 'test']:
            m = res[phase]['metrics']
            log(f"  {phase}: {m['total_trades']}笔/{m['positive_rate']:.1f}% S={m['sharpe']:.2f} Sortino={m['sortino']:.2f} 均益={m['avg_return']:.2f}% MDD={m['max_drawdown']:.1f}%")

        all_results[label] = {'params': combo, 'results': res}

    # 保存
    out_path = os.path.join(OUTPUT_DIR, 'weak_filter_compare.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    log(f"\n结果已保存: {out_path}")

    # 找三阶段全>55%且测试>=10笔的
    qualified = []
    for label, data in all_results.items():
        r = data['results']
        t, v, te = r['train']['metrics'], r['val']['metrics'], r['test']['metrics']
        if t['positive_rate'] > 55 and v['positive_rate'] > 55 and te['positive_rate'] > 55 and te['total_trades'] >= 10:
            qualified.append((te['total_trades'], te['positive_rate'], te['sharpe'], label, data))

    qualified.sort(key=lambda x: (-x[2], -x[0]))  # 按夏普排序
    log(f"\n=== 三阶段全>55%且测试>=10笔的策略共{len(qualified)}个 ===")
    for _, test_pr, test_s, label, data in qualified:
        t, v, te = data['results']['train']['metrics'], data['results']['val']['metrics'], data['results']['test']['metrics']
        log(f"{label}")
        log(f"  train: {t['total_trades']}笔/{t['positive_rate']:.1f}% S={t['sharpe']:.2f} 均益={t['avg_return']:.2f}%")
        log(f"  val:   {v['total_trades']}笔/{v['positive_rate']:.1f}% S={v['sharpe']:.2f} 均益={v['avg_return']:.2f}%")
        log(f"  test:  {te['total_trades']}笔/{te['positive_rate']:.1f}% S={te['sharpe']:.2f} 均益={te['avg_return']:.2f}%")
        log(f"  弱市类型: {data['params']['weak_type']}")

    log(f"\n总耗时: {time.time()-t0:.1f}s")

if __name__ == '__main__':
    main()
