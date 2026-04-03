#!/usr/bin/env python3
"""
布林带中间参数探索：BB0.98 / 0.99 / 1.00
填补 BB0.96~1.02 之间的空白参数区间

参数：
  - RSI < 20（超卖，严格）
  - 弱市状态 = 70%
  - TOP300 基本面候选池
  - 持仓期：7天
  - KDJ：无 / 超卖（K<20 或 J<0）
  - 三阶段：训练/验证/测试

BB乘数变体（本次核心）：
  - 0.98：BB_lower × 0.98（价格接近下轨但未完全触及）
  - 0.99：BB_lower × 0.99（更宽松）
  - 1.00：BB_lower × 1.00（严格等于下轨）
"""
import sqlite3, json, time, os, sys
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import product

# ============================================================
# Config
# ============================================================
DB = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
OUTPUT_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'
os.makedirs(OUTPUT_DIR, exist_ok=True)

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-31'),
    'test':  ('2025-08-01', '2026-03-31'),
}

RF = 0.03
COST = 0.30

# ============================================================
# PIT 财报延迟
# ============================================================
def pit_delay_days(report_date_str):
    month = int(report_date_str[5:7])
    if month == 3:    return 30
    elif month == 6:  return 62
    elif month == 9:  return 31
    elif month == 12: return 120
    else: return 45

def pit_effective_date(report_date_str):
    return (datetime.strptime(report_date_str, '%Y-%m-%d') + timedelta(days=pit_delay_days(report_date_str))).strftime('%Y-%m-%d')

# ============================================================
# 基本面打分
# ============================================================
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

# ============================================================
# 28项指标计算
# ============================================================
def calc_28_metrics(rets, hold_days, hit_stock_count=0):
    if not rets:
        return {k: 0 for k in [
            'total_trades','positive_rate','avg_return','median_return',
            'max_return','min_return','hit_stocks',
            'sharpe','max_drawdown','volatility','downside_volatility','sortino',
            'win_rate','profit_loss_ratio','avg_win','avg_loss',
            'max_win','max_loss','max_consec_wins','max_consec_losses',
            'annual_return','calmar','recovery_factor','breakeven_wr','expectancy',
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

    ann_ret = avg_ret * 252 / hold_days
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_vol = std * np.sqrt(252 / hold_days)
    sharpe = (ann_ret - RF * 100) / ann_vol if ann_vol > 0 else 0

    cum = 0; peak = 0; mdd = 0
    for x in rets:
        cum += np.log(1 + x / 100)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)

    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold_days)) if len(dn) > 1 else 0
    sortino = (ann_ret - RF * 100) / dn_std if dn_std > 0 else 0
    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0

    cw = cl = cwmax = clmax = 0
    for x in rets:
        if x > 0: cw += 1; cl = 0; cwmax = max(cwmax, cw)
        else: cl += 1; cw = 0; clmax = max(clmax, cl)

    expectancy = float(len(pos)/n * np.mean(pos) + len(neg)/n * np.mean(neg)) if len(neg) > 0 else avg_ret
    total_ret = sum(rets)
    recovery_factor = total_ret / abs(mdd * 100) if mdd > 0.0001 else 0
    be_wr = 1 / (1 + plr) * 100 if plr > 0 else 100

    return {
        'total_trades': n,
        'positive_rate': round(pos_rate, 2),
        'avg_return': round(avg_ret, 4),
        'median_return': round(median_ret, 4),
        'max_return': round(max_ret, 4),
        'min_return': round(min_ret, 4),
        'hit_stocks': hit_stock_count,
        'sharpe': round(sharpe, 4),
        'max_drawdown': round(mdd * 100, 4),
        'volatility': round(ann_vol, 4),
        'downside_volatility': round(dn_std, 4),
        'sortino': round(sortino, 4),
        'win_rate': round(pos_rate, 2),
        'profit_loss_ratio': round(plr, 4),
        'avg_win': round(float(np.mean(pos)), 4) if len(pos) > 0 else 0,
        'avg_loss': round(float(np.mean(neg)), 4) if len(neg) > 0 else 0,
        'max_win': round(max_ret, 4),
        'max_loss': round(min_ret, 4),
        'max_consec_wins': cwmax,
        'max_consec_losses': clmax,
        'annual_return': round(ann_ret, 4),
        'calmar': round(ann_ret / (mdd * 100), 4) if mdd > 0.0001 else 0,
        'recovery_factor': round(recovery_factor, 4),
        'breakeven_wr': round(be_wr, 2),
        'expectancy': round(expectancy, 4),
        'train_test_ratio': 0,
        'three_phase_consistency': 0,
        'avg_hold_days': hold_days,
    }

# ============================================================
# 数据加载
# ============================================================
def load_data(conn):
    t0 = time.time()
    log("加载PIT基本面...")
    fund_rows = conn.execute("""
        SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio
        FROM financial_indicators
        WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL OR profit_growth IS NOT NULL
        ORDER BY symbol, report_date
    """).fetchall()

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
        rows = conn.execute("""
            SELECT trade_date, open, close, high, low, volume,
                   rsi14, macd_hist, boll_lower, kdj_k, kdj_d, kdj_j
            FROM kline_daily
            WHERE symbol=? AND trade_date>='2020-12-01' AND trade_date<='2026-03-31'
            ORDER BY trade_date
        """, (sym,)).fetchall()
        if len(rows) < 60:
            continue
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

        vol_ma5 = np.convolve(vols, np.ones(5) / 5, mode='full')[:len(vols)]
        sym_data[sym] = {
            'dates': dates, 'open': opens, 'close': closes,
            'high': highs, 'low': lows, 'vol': vols, 'vol_ma5': vol_ma5,
            'rsi': rsi, 'macd_hist': macd_hist, 'bb_lower': bb_lower,
            'kdj_k': kdj_k, 'kdj_d': kdj_d, 'kdj_j': kdj_j,
        }
    log(f"  {len(sym_data)} 股票已加载 ({time.time()-t0:.1f}s)")

    # 预计算弱市标记
    log("计算弱市标记...")
    all_dates = sorted(set(d for sd in sym_data.values() for d in sd['dates']))
    weak = {}
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
                        if c < ma20:
                            below += 1
            except ValueError:
                pass
        weak[d] = (total >= 20 and below / total > 0.7)
    log(f"  弱市标记完成 ({time.time()-t0:.1f}s)")
    return sym_data, dict(sym_scores_pit), weak

# ============================================================
# 回测引擎
# ============================================================
def run_backtest(sym_data, sym_scores_pit, weak,
                 hold_days, top_n,
                 bb_mult,
                 kdj_filter,
                 weak_thresh=0.7):
    """
    返回 {phase: {metrics28, trades, hit_stocks}}
    """
    results = {}
    for phase, (ps, pe) in PHASES.items():
        all_rets = []
        hit_stocks_set = set()
        dt = datetime.strptime(ps, '%Y-%m-%d').replace(day=1)
        end_dt = datetime.strptime(pe, '%Y-%m-%d')

        while dt <= end_dt:
            ms = dt.strftime('%Y-%m-%d')
            me_dt = dt + timedelta(days=32)
            me = min(me_dt.replace(day=1).strftime('%Y-%m-%d'), pe)

            # 选股：本月TOP_N PIT分数
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
            top = [s[0] for s in scored[:top_n]]

            for sym in top:
                if sym not in sym_data:
                    continue
                sd = sym_data[sym]
                dates = sd['dates']
                closes = sd['close']
                rsi = sd['rsi']
                bb_l = sd['bb_lower']
                k_k = sd['kdj_k']
                k_j = sd['kdj_j']

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < ms:
                        i += 1; continue
                    if d >= me:
                        break
                    if i + 1 + hold_days >= len(dates):
                        break

                    # 弱市过滤
                    if not weak.get(d, False):
                        i += 1; continue

                    # RSI < 20 过滤
                    if np.isnan(rsi[i]) or rsi[i] >= 20:
                        i += 1; continue
                    # 排除 RSI 异常低值
                    if rsi[i] < 10:
                        i += 1; continue

                    # 布林带下轨过滤 (price <= BB_lower * bb_mult)
                    price = closes[i]
                    if not np.isnan(bb_l[i]) and bb_l[i] > 0:
                        if price > bb_l[i] * bb_mult:
                            i += 1; continue
                    else:
                        i += 1; continue

                    # KDJ 过滤
                    if kdj_filter == 'oversold':
                        if np.isnan(k_k[i]) or np.isnan(k_j[i]):
                            i += 1; continue
                        if not (k_k[i] < 20 or k_j[i] < 0):
                            i += 1; continue

                    # T+1 买入，持有hold_days后收盘卖出
                    bp = sd['open'][i + 1]
                    sp = sd['close'][i + 1 + hold_days]
                    if bp > 0 and not np.isnan(bp) and not np.isnan(sp):
                        ret = (sp - bp) / bp * 100 - COST
                        all_rets.append(ret)
                        hit_stocks_set.add(sym)
                    i += hold_days + 1

            dt = me_dt.replace(day=1)

        metrics = calc_28_metrics(all_rets, hold_days, len(hit_stocks_set))
        results[phase] = {
            'metrics': metrics,
            'trades': len(all_rets),
            'hit_stocks': len(hit_stocks_set),
        }

    # 计算三阶段一致性
    pos_rates = [results[p]['metrics']['positive_rate'] for p in ['train', 'val', 'test']]
    consistency = sum(1 for pr in pos_rates if pr >= 55) / 3 * 100
    for phase in results:
        results[phase]['metrics']['three_phase_consistency'] = round(consistency, 2)

    return results

# ============================================================
# 主程序
# ============================================================
def main():
    t0 = time.time()
    log("=" * 70)
    log("BB0.98/0.99/1.00 布林带中间参数探索")
    log("=" * 70)

    log("连接数据库...")
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores_pit, weak = load_data(conn)
    conn.close()

    # 参数网格
    BB_MULTS = [0.98, 0.99, 1.00]
    HOLD_DAYS = 7
    TOP_N = 300
    KDJ_FILTERS = [None, 'oversold']

    all_combos = []
    for bb_mult, kdj in product(BB_MULTS, KDJ_FILTERS):
        all_combos.append({
            'bb_mult': bb_mult,
            'hold_days': HOLD_DAYS,
            'top_n': TOP_N,
            'kdj_filter': kdj,
            'rsi_mode': 'strict',
        })

    log(f"共 {len(all_combos)} 个组合待测")
    all_results = {}

    for idx, combo in enumerate(all_combos):
        bb_mult = combo['bb_mult']
        hold = combo['hold_days']
        top_n = combo['top_n']
        kdj = combo['kdj_filter']

        kdj_name = kdj if kdj else 'none'
        label = f"BB{bb_mult}_H{hold}_TOP{top_n}_KDJ{kdj_name}"

        log(f"\n[{idx+1}/{len(all_combos)}] {label}")

        try:
            res = run_backtest(
                sym_data, sym_scores_pit, weak,
                hold_days=hold,
                top_n=top_n,
                bb_mult=bb_mult,
                kdj_filter=kdj,
            )
        except Exception as e:
            log(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            continue

        train_pr = res['train']['metrics']['positive_rate']
        val_pr = res['val']['metrics']['positive_rate']
        test_pr = res['test']['metrics']['positive_rate']
        train_sharpe = res['train']['metrics']['sharpe']
        val_sharpe = res['val']['metrics']['sharpe']
        test_sharpe = res['test']['metrics']['sharpe']
        consistency = res['train']['metrics']['three_phase_consistency']
        total_trades = res['train']['trades'] + res['val']['trades'] + res['test']['trades']

        log(f"  train: PR={train_pr:.1f}% sharpe={train_sharpe:.2f} ({res['train']['trades']}笔)")
        log(f"  val:   PR={val_pr:.1f}% sharpe={val_sharpe:.2f} ({res['val']['trades']}笔)")
        log(f"  test:  PR={test_pr:.1f}% sharpe={test_sharpe:.2f} ({res['test']['trades']}笔)")
        log(f"  一致性={consistency:.1f}% 总交易={total_trades}")

        all_results[label] = {
            'params': combo,
            'results': res,
        }

    # ============================================================
    # 保存所有结果
    # ============================================================
    output_path = os.path.join(OUTPUT_DIR, 'bb098_099_100_explore.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    log(f"\n结果已保存: {output_path}")

    # ============================================================
    # 汇总摘要
    # ============================================================
    log("\n" + "=" * 70)
    log("汇总摘要")
    log("=" * 70)
    for label, data in sorted(all_results.items()):
        r = data['results']
        train_m = r['train']['metrics']
        val_m = r['val']['metrics']
        test_m = r['test']['metrics']
        log(f"\n{label}")
        log(f"  训练集: PR={train_m['positive_rate']:.1f}% Sharpe={train_m['sharpe']:.2f} Sortino={train_m['sortino']:.2f} 交易={r['train']['trades']}笔")
        log(f"  验证集: PR={val_m['positive_rate']:.1f}% Sharpe={val_m['sharpe']:.2f} Sortino={val_m['sortino']:.2f} 交易={r['val']['trades']}笔")
        log(f"  测试集: PR={test_m['positive_rate']:.1f}% Sharpe={test_m['sharpe']:.2f} Sortino={test_m['sortino']:.2f} 交易={r['test']['trades']}笔")
        log(f"  三阶段一致性: {train_m['three_phase_consistency']:.0f}% | "
            f"胜率={test_m['win_rate']:.1f}% | "
            f"期望收益={test_m['expectancy']:.2f}% | "
            f"卡玛={test_m['calmar']:.2f}")

    elapsed = time.time() - t0
    log(f"\n总耗时: {elapsed:.1f}s")

if __name__ == '__main__':
    main()
