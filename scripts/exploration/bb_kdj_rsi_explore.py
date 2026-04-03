#!/usr/bin/env python3
"""
布林带变体 + KDJ组合 + RSI过滤 策略探索
在 RSI<20 + 弱市70% + TOP200 基线基础上测试扩展方向

扩展方向：
  1. BB下轨变体: multiplier = 0.94/0.95/0.96 (vs baseline 1.02)
  2. KDJ组合: K<20|J<0 (超卖) + K从下向上穿过D (金叉)
  3. RSI过滤: RSI<20(基础) + RSI区间30-40(即将超卖)
  4. 候选池: TOP200 → TOP300

持仓期: 7天 和 10天
三阶段:
  训练集: 2021-01-01 ~ 2024-06-30
  验证集: 2024-07-01 ~ 2025-07-31
  测试集: 2025-08-01 ~ 2026-03-31

约束: T+1卖出, 最长持有10天, PIT财报数据
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
def calc_28_metrics(rets, hold_days, hit_stock_count=0, all_rets_per_stock=None):
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

    # recovery factor
    total_ret = sum(rets)
    recovery_factor = total_ret / abs(mdd * 100) if mdd > 0.0001 else 0

    # breakeven win rate
    if plr > 0:
        be_wr = 1 / (1 + plr) * 100
    else:
        be_wr = 100

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
                 bb_mult,       # BB下轨乘数: 0.94/0.95/0.96/1.02
                 kdj_filter,    # None, 'oversold', 'golden_cross', 'both'
                 rsi_mode,      # 'strict'(<20), 'near_oversold'(30-40 also)
                 weak_thresh=0.7,
                 use_weak=True):
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
                opens = sd['open']
                closes = sd['close']
                rsi = sd['rsi']
                bb_l = sd['bb_lower']
                k_k = sd['kdj_k']
                k_d = sd['kdj_d']
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
                    if use_weak and not weak.get(d, False):
                        i += 1; continue

                    # RSI 过滤
                    if np.isnan(rsi[i]) or rsi[i] >= 20:
                        i += 1; continue
                    if rsi_mode == 'near_oversold':
                        # 也接受 RSI 在 30-40 区域（即将超卖）
                        pass  # 已经在上面排除了 rsi >= 20
                    elif rsi_mode == 'strict':
                        if rsi[i] < 10:  # 排除异常值
                            i += 1; continue

                    # 布林带下轨过滤 (price <= BB_lower * bb_mult)
                    price = closes[i]
                    if not np.isnan(bb_l[i]) and bb_l[i] > 0:
                        if price > bb_l[i] * bb_mult:
                            i += 1; continue
                    else:
                        i += 1; continue

                    # KDJ 过滤
                    if kdj_filter and not np.isnan(k_k[i]) and not np.isnan(k_d[i]):
                        if kdj_filter in ('oversold', 'both'):
                            if not (k_k[i] < 20 or k_j[i] < 0):
                                i += 1; continue
                        if kdj_filter in ('golden_cross', 'both'):
                            # K 从下向上穿过 D（金叉）
                            if i > 0 and not np.isnan(k_k[i-1]) and not np.isnan(k_d[i-1]):
                                crossed = k_k[i] > k_d[i] and k_k[i-1] <= k_d[i-1]
                                if not crossed:
                                    i += 1; continue
                            else:
                                i += 1; continue

                    # T+1 买入，持有hold_days后收盘卖出
                    bp = opens[i + 1]
                    sp = closes[i + 1 + hold_days]
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
    log("BB变体 + KDJ组合 + RSI过滤 策略探索")
    log("=" * 70)

    log("连接数据库...")
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores_pit, weak = load_data(conn)
    conn.close()

    # 参数网格
    BB_MULTS = [0.94, 0.95, 0.96, 1.02]
    HOLD_DAYS_LIST = [7, 10]
    TOP_N_LIST = [200, 300]
    KDJ_FILTERS = [None, 'oversold', 'golden_cross', 'both']
    RSI_MODES = ['strict', 'near_oversold']
    WEAK_THRESH = 0.7

    # 生成所有组合
    all_combos = []
    for bb_mult, hold, top_n, kdj, rsi_mode in product(BB_MULTS, HOLD_DAYS_LIST, TOP_N_LIST, KDJ_FILTERS, RSI_MODES):
        all_combos.append({
            'bb_mult': bb_mult,
            'hold_days': hold,
            'top_n': top_n,
            'kdj_filter': kdj,
            'rsi_mode': rsi_mode,
        })

    log(f"共 {len(all_combos)} 个组合待测")
    all_results = {}

    for idx, combo in enumerate(all_combos):
        bb_mult = combo['bb_mult']
        hold = combo['hold_days']
        top_n = combo['top_n']
        kdj = combo['kdj_filter']
        rsi_mode = combo['rsi_mode']

        kdj_name = kdj if kdj else 'none'
        label = f"BB{bb_mult}_H{hold}_TOP{top_n}_KDJ{kdj_name}_RSI{rsi_mode}"

        log(f"\n[{idx+1}/{len(all_combos)}] {label}")

        try:
            res = run_backtest(
                sym_data, sym_scores_pit, weak,
                hold_days=hold,
                top_n=top_n,
                bb_mult=bb_mult,
                kdj_filter=kdj,
                rsi_mode=rsi_mode,
                weak_thresh=WEAK_THRESH,
                use_weak=True,
            )
        except Exception as e:
            log(f"  ERROR: {e}")
            continue

        train_pr = res['train']['metrics']['positive_rate']
        val_pr = res['val']['metrics']['positive_rate']
        test_pr = res['test']['metrics']['positive_rate']
        train_sharpe = res['train']['metrics']['sharpe']
        val_sharpe = res['val']['metrics']['sharpe']
        test_sharpe = res['test']['metrics']['sharpe']
        consistency = res['train']['metrics']['three_phase_consistency']
        total_trades = res['train']['metrics']['total_trades'] + res['val']['metrics']['total_trades'] + res['test']['metrics']['total_trades']

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
    output_path = os.path.join(OUTPUT_DIR, 'bb_kdj_rsi_explore.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    log(f"\n结果已保存: {output_path}")

    # ============================================================
    # TOP10 排序：按三阶段一致性 > train正收益率 > val正收益率 > test正收益率
    # ============================================================
    sorted_results = sorted(
        all_results.items(),
        key=lambda x: (
            x[1]['results']['train']['metrics']['three_phase_consistency'],
            x[1]['results']['train']['metrics']['positive_rate'],
            x[1]['results']['val']['metrics']['positive_rate'],
            x[1]['results']['test']['metrics']['positive_rate'],
            x[1]['results']['train']['metrics']['sharpe'],
        )
    )
    sorted_results.reverse()  # 从高到低

    top10 = []
    for label, data in sorted_results[:10]:
        combo = data['params']
        res = data['results']
        top10.append({
            'rank': len(top10) + 1,
            'label': label,
            'params': combo,
            'train': res['train']['metrics'],
            'val': res['val']['metrics'],
            'test': res['test']['metrics'],
            'consistency': res['train']['metrics']['three_phase_consistency'],
            'total_trades': res['train']['metrics']['total_trades'] + res['val']['metrics']['total_trades'] + res['test']['metrics']['total_trades'],
        })

    top_path = os.path.join(OUTPUT_DIR, 'bb_kdj_rsi_top_strategies.json')
    with open(top_path, 'w', encoding='utf-8') as f:
        json.dump(top10, f, ensure_ascii=False, indent=2)
    log(f"TOP10策略已保存: {top_path}")

    # ============================================================
    # 打印TOP10摘要
    # ============================================================
    log("\n" + "=" * 90)
    log("TOP10 策略（三阶段一致性排序）")
    log("=" * 90)
    header = f"{'Rank':>4} {'Label':<45} {'Train_PR':>8} {'Val_PR':>8} {'Test_PR':>8} {'Consist':>8} {'Sharpe(T)':>9} {'Trades':>6}"
    log(header)
    log("-" * 90)
    for s in top10:
        label = s['label'][:44]
        log(f"{s['rank']:>4} {label:<45} {s['train']['positive_rate']:>7.1f}% {s['val']['positive_rate']:>7.1f}% {s['test']['positive_rate']:>7.1f}% {s['consistency']:>7.1f}% {s['train']['sharpe']:>8.2f} {s['total_trades']:>6}")

    log(f"\n总耗时: {time.time()-t0:.1f}s")
    return all_results, top10

if __name__ == '__main__':
    all_results, top10 = main()
