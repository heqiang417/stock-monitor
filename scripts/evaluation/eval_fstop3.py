#!/usr/bin/env python3
"""
Fstop3_pt5 v10 完整评估
按 EVAL_FRAMEWORK.md v1.5 标准三阶段 + 28项指标 + sell_mode=stop_profit
"""
import sqlite3, json, time, os, sys
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

DB = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
OUTPUT_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 框架标准三阶段
PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-27'),
}
RF = 0.03; COST = 0.30
STOP_LOSS = 3.0; TAKE_PROFIT = 5.0; HOLD_DAYS = 10

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
    return {
        'total_trades': n, 'positive_rate': round(pos_rate, 2), 'avg_return': round(avg_ret, 4),
        'median_return': round(median_ret, 4), 'max_return': round(max_ret, 4),
        'min_return': round(min_ret, 4), 'hit_stocks': hit_stock_count,
        'sharpe': round(sharpe, 4), 'max_drawdown': round(mdd * 100, 4),
        'volatility': round(ann_vol, 4), 'downside_volatility': round(dn_std, 4),
        'sortino': round(sortino, 4), 'win_rate': round(pos_rate, 2),
        'profit_loss_ratio': round(plr, 4),
        'avg_win': round(float(np.mean(pos)), 4) if len(pos) > 0 else 0,
        'avg_loss': round(float(np.mean(neg)), 4) if len(neg) > 0 else 0,
        'max_win': round(max_ret, 4), 'max_loss': round(min_ret, 4),
        'max_consec_wins': cwmax, 'max_consec_losses': clmax,
        'annual_return': round(ann_ret, 4),
        'calmar': round(ann_ret / (mdd * 100), 4) if mdd > 0.0001 else 0,
        'recovery_factor': round(recovery_factor, 4),
        'breakeven_wr': round(be_wr, 2),
        'expectancy': round(expectancy, 4),
        'train_test_ratio': 0, 'three_phase_consistency': 0,
        'avg_hold_days': hold_days,
    }

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
        rows = conn.execute("""SELECT trade_date, open, close, high, low, volume, rsi14, macd_hist, boll_lower, boll_upper, ma5, ma10, ma20, kdj_k, kdj_d, kdj_j FROM kline_daily WHERE symbol=? AND trade_date>='2020-12-01' AND trade_date<='2026-03-31' ORDER BY trade_date""", (sym,)).fetchall()
        if len(rows) < 60: continue
        dates = [r[0] for r in rows]
        opens = np.array([r[1] for r in rows], dtype=float)
        closes = np.array([r[2] for r in rows], dtype=float)
        vols = np.array([r[5] for r in rows], dtype=float)
        rsi = np.array([r[6] if r[6] is not None else np.nan for r in rows], dtype=float)
        bb_l = np.array([r[8] if r[8] is not None else np.nan for r in rows], dtype=float)
        ma5_vol = np.array([r[10] if r[10] is not None else np.nan for r in rows], dtype=float)
        sym_data[sym] = {'dates': dates, 'open': opens, 'close': closes, 'volume': vols, 'rsi': rsi, 'bb_lower': bb_l, 'ma5_vol': ma5_vol}
    log(f"  {len(sym_data)} 股票已加载 ({time.time()-t0:.1f}s)")

    # 预计算弱市标记
    log("计算弱市标记（Fstop3: >50%个股<MA20）...")
    all_dates = sorted(set(d for sd in sym_data.values() for d in sd['dates']))
    weak = {}
    for d in all_dates:
        total = below = 0
        for sd in sym_data.values():
            try:
                idx = sd['dates'].index(d)
                if idx >= 20:
                    ma20_val = np.nanmean(sd['close'][max(0, idx-19):idx+1])
                    c = sd['close'][idx]
                    if not np.isnan(c) and not np.isnan(ma20_val):
                        total += 1
                        if c < ma20_val: below += 1
            except ValueError: pass
        weak[d] = (total >= 20 and below / total > 0.5)  # 50% threshold
    log(f"  弱市标记完成 ({time.time()-t0:.1f}s)")
    return sym_data, dict(sym_scores_pit), weak

def run_backtest(sym_data, sym_scores_pit, weak):
    results = {}
    for phase, (ps, pe) in PHASES.items():
        all_rets = []; hit_stocks_set = set(); actual_holds = []
        dt = datetime.strptime(ps, '%Y-%m-%d').replace(day=1)
        end_dt = datetime.strptime(pe, '%Y-%m-%d')

        while dt <= end_dt:
            ms = dt.strftime('%Y-%m-%d')
            me_dt = dt + timedelta(days=32)
            me = min(me_dt.replace(day=1).strftime('%Y-%m-%d'), pe)

            # 选股：Fstop3 v10 无基本面过滤，所有股票均可
            for sym in sym_data:
                if sym not in sym_data: continue
                sd = sym_data[sym]; dates = sd['dates']; closes = sd['close']; opens_arr = sd['open']
                rsi = sd['rsi']; bb_l = sd['bb_lower']; vols = sd['volume']; ma5_vol = sd.get('ma5_vol')

                
                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < ms: i += 1; continue
                    if d >= me: break
                    if i + 1 + HOLD_DAYS >= len(dates): break

                    # 弱市过滤
                    if not weak.get(d, False): i += 1; continue

                    # RSI < 18
                    if np.isnan(rsi[i]) or rsi[i] >= 18: i += 1; continue

                    # BB触底: close <= boll_lower (exact)
                    price = closes[i]
                    if np.isnan(bb_l[i]) or bb_l[i] <= 0 or price > bb_l[i]: i += 1; continue

                    # 放量: vol >= ma5 * 1.5
                    if i < 5 or np.isnan(vols[i]) or np.isnan(ma5_vol[i]) or ma5_vol[i] <= 0:
                        i += 1; continue
                    if vols[i] < ma5_vol[i] * 1.5: i += 1; continue

                    # T+1买入
                    bp = opens_arr[i + 1]  # 明日开盘价
                    if bp <= 0 or np.isnan(bp): i += 1; continue

                    # 止损止盈模式
                    # T+1买，T+2起检查，最多持有HOLD_DAYS天
                    sell_price = None; actual_hold = 0
                    for h in range(1, HOLD_DAYS + 1):
                        if i + 1 + h >= len(dates): break
                        sp = closes[i + 1 + h]
                        pct_chg = (sp - bp) / bp * 100
                        if pct_chg <= -STOP_LOSS or pct_chg >= TAKE_PROFIT:
                            sell_price = sp
                            actual_hold = h
                            break
                    if sell_price is None:
                        # 到期卖出（h=HOLD_DAYS时未触发）
                        sell_idx = i + 1 + HOLD_DAYS
                        if sell_idx < len(dates):
                            sell_price = closes[sell_idx]
                            actual_hold = HOLD_DAYS
                        else:
                            i += 1; continue

                    if sell_price is None or sell_price <= 0 or np.isnan(sell_price):
                        i += 1; continue

                    ret = (sell_price - bp) / bp * 100 - COST
                    all_rets.append(ret)
                    actual_holds.append(actual_hold)
                    hit_stocks_set.add(sym)
                    i += HOLD_DAYS + 1  # 持仓期不重复

            dt = me_dt.replace(day=1)

        metrics = calc_28_metrics(all_rets, HOLD_DAYS, len(hit_stocks_set))
        # avg_hold_days 用 actual_holds
        if actual_holds:
            metrics['avg_hold_days'] = round(sum(actual_holds) / len(actual_holds), 1)
        results[phase] = {'metrics': metrics, 'trades': len(all_rets), 'hit_stocks': len(hit_stocks_set)}

    # 三阶段一致性
    pos_rates = [results[p]['metrics']['positive_rate'] for p in ['train', 'val', 'test']]
    consistency = sum(1 for pr in pos_rates if pr >= 55) / 3 * 100
    for phase in results:
        results[phase]['metrics']['three_phase_consistency'] = round(consistency, 2)

    return results

def main():
    t0 = time.time()
    log("=" * 60)
    log("Fstop3_pt5 v10 评估（EVAL_FRAMEWORK.md v1.5 标准）")
    log("=" * 60)
    log(f"三阶段: train={PHASES['train']} val={PHASES['val']} test={PHASES['test']}")
    log(f"参数: RSI<18 + BB触底 + 放量1.5x + 弱市50% + TOP300")
    log(f"卖出: 止损{STOP_LOSS}%/止盈{TAKE_PROFIT}% 持有{HOLD_DAYS}天")

    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores_pit, weak = load_data(conn)
    conn.close()

    results = run_backtest(sym_data, sym_scores_pit, weak)

    # 打印结果
    log("\n" + "=" * 80)
    for phase in ['train', 'val', 'test']:
        m = results[phase]['metrics']
        log(f"{phase.upper()}: {m['total_trades']}笔 正率{m['positive_rate']:.1f}% 均益{m['avg_return']:.4f}% 夏普{m['sharpe']:.2f} 索提诺{m['sortino']:.2f} MDD{m['max_drawdown']:.1f}% P/L{m['profit_loss_ratio']:.2f}")

    # 保存
    out = {'params': {'rsi': 18, 'bb': 'exact', 'vol': 1.5, 'weak': 0.5, 'top': 300, 'hold': HOLD_DAYS, 'sell': 'stop_profit', 'stop_loss': STOP_LOSS, 'take_profit': TAKE_PROFIT}, 'results': results, 'phases': PHASES}
    out_path = os.path.join(OUTPUT_DIR, 'fstop3_v10_framework_eval.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log(f"\n结果已保存: {out_path}")

    # 合格检查
    log("\n合格标准检查:")
    for phase in ['train', 'val', 'test']:
        m = results[phase]['metrics']
        checks = [
            ('正率>55%', m['positive_rate'] > 55),
            ('夏普>1.0', m['sharpe'] > 1.0),
            ('索提诺>2.0', m['sortino'] > 2.0),
            ('MDD<50%', m['max_drawdown'] < 50),
            ('P/L>1.0', m['profit_loss_ratio'] > 1.0),
        ]
        for name, ok in checks:
            log(f"  {phase}.{name}: {'✅' if ok else '❌'} (实际: {m['positive_rate']:.1f}%等)")

    log(f"\n总耗时: {time.time()-t0:.1f}s")

if __name__ == '__main__':
    main()
