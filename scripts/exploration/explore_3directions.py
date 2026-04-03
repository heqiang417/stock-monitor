#!/usr/bin/env python3
"""
三方向策略探索
方向1: 更严格大盘弱市过滤 (MA20下方比例 60%, 75%, 85%)
方向2: 资金流向/北向资金情绪过滤 (主力净流入>0, 北向净买入)
方向3: 动态仓位管理 (根据信号强度调整仓位)
"""
import sys, json, time, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from datetime import datetime, timedelta

# ============================================================
# Config
# ============================================================
DB = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
OUTPUT_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'
os.makedirs(OUTPUT_DIR, exist_ok=True)

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-27'),
}

# Baseline params
BASELINE = {
    'name': 'Fstop3_pt5',
    'rsi_thresh': 18,
    'use_bb': True,
    'vol_mult': 1.5,
    'weak_thresh': 0.5,
    'top_n': 300,
    'stop_loss': 3.0,
    'take_profit': 5.0,
    'max_hold_days': 10,
    'position_pct': 0.10,
    'use_capital_flow': False,
    'use_northbound': False,
    'market_rsi_thresh': None,
    'position_mode': 'fixed',  # fixed | adaptive
}
BASELINE_RESULTS = {
    'train': {'win_rate': 58.6, 'avg_return': None, 'trades': None, 'sharpe': 2.92},
    'val':   {'win_rate': 89.0, 'avg_return': None, 'trades': None, 'sharpe': 2.32},
    'test':  {'win_rate': 68.4, 'avg_return': None, 'trades': None, 'sharpe': 3.90},
}

# ============================================================
# PIT延迟
# ============================================================
def pit_delay_days(report_date):
    month = int(report_date[5:7])
    if month == 3: return 30
    elif month == 6: return 62
    elif month == 9: return 31
    elif month == 12: return 120
    return 45

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

# ============================================================
# 加载数据
# ============================================================
def load_data():
    print("加载数据...")
    t0 = time.time()
    conn = sqlite3.connect(DB, timeout=120)

    # 基本面PIT评分
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
            pd = (datetime.strptime(rd, '%Y-%m-%d') + timedelta(days=pit_delay_days(rd))).strftime('%Y-%m-%d')
            sym_scores.setdefault(sym, []).append((pd, s))

    # K线数据
    sym_data = {}
    for sym in sym_scores:
        rows = conn.execute("""
            SELECT trade_date, open, close, high, low, rsi14,
                   boll_lower, boll_upper, ma5, ma10, ma20,
                   macd_hist, volume
            FROM kline_daily
            WHERE symbol=? AND trade_date>='2020-12-01'
            ORDER BY trade_date
        """, (sym,)).fetchall()
        if len(rows) < 60:
            continue
        dates = [r[0] for r in rows]
        sym_data[sym] = {
            'dates': dates,
            'open':      np.array([r[1] for r in rows], dtype=float),
            'close':     np.array([r[2] for r in rows], dtype=float),
            'high':      np.array([r[3] for r in rows], dtype=float),
            'low':       np.array([r[4] for r in rows], dtype=float),
            'rsi':       np.array([r[5] if r[5] is not None else np.nan for r in rows], dtype=float),
            'bb_lower':  np.array([r[6] if r[6] is not None else np.nan for r in rows], dtype=float),
            'bb_upper':  np.array([r[7] if r[7] is not None else np.nan for r in rows], dtype=float),
            'ma5':       np.array([r[8] if r[8] is not None else np.nan for r in rows], dtype=float),
            'ma10':      np.array([r[9] if r[9] is not None else np.nan for r in rows], dtype=float),
            'ma20':      np.array([r[10] if r[10] is not None else np.nan for r in rows], dtype=float),
            'macd_hist': np.array([r[11] if r[11] is not None else np.nan for r in rows], dtype=float),
            'volume':    np.array([r[12] if r[12] is not None else np.nan for r in rows], dtype=float),
        }

    # 资金流向数据
    capital_flow = {}
    cf_rows = conn.execute("""
        SELECT symbol, trade_date, main_net_inflow
        FROM capital_flow
        WHERE trade_date >= '2020-12-01'
    """).fetchall()
    for sym, td, mni in cf_rows:
        capital_flow.setdefault(sym, {})[td] = mni if mni is not None else 0.0

    # 北向资金流向
    north_flow = {}
    nf_rows = conn.execute("""
        SELECT date, net_buy
        FROM northbound_flow
        WHERE date >= '2020-12-01' AND direction='south'
    """).fetchall()
    for dt, nb in nf_rows:
        north_flow[dt] = nb if nb is not None else 0.0

    # 北向持股比例
    north_hold = {}
    nh_rows = conn.execute("""
        SELECT symbol, trade_date, hold_pct
        FROM northbound_holdings
        WHERE trade_date >= '2020-12-01'
    """).fetchall()
    for sym, td, hp in nh_rows:
        north_hold.setdefault(sym, {})[td] = hp if hp is not None else 0.0

    conn.close()

    all_dates = sorted(set(d for sd in sym_data.values() for d in sd['dates']))

    # 计算弱市 (不同阈值)
    def calc_weak_dates(thresh):
        weak = {}
        for d in all_dates:
            total = below = 0
            for sd in sym_data.values():
                try:
                    idx = sd['dates'].index(d)
                    ma = sd['ma20'][idx]; cl = sd['close'][idx]
                    if not np.isnan(ma) and not np.isnan(cl):
                        total += 1
                        if cl < ma: below += 1
                except ValueError: pass
            weak[d] = (total >= 20 and below / total > thresh)
        return weak

    # 计算大盘RSI (所有股票等权RSI均值)
    def calc_market_rsi_dates(thresh):
        """大盘RSI均值 < thresh 为弱市"""
        weak = {}
        for d in all_dates:
            rsi_vals = []
            for sd in sym_data.values():
                try:
                    idx = sd['dates'].index(d)
                    rsi = sd['rsi'][idx]
                    if not np.isnan(rsi) and rsi >= 10:
                        rsi_vals.append(rsi)
                except ValueError: pass
            if len(rsi_vals) >= 20:
                weak[d] = np.mean(rsi_vals) < thresh
            else:
                weak[d] = False
        return weak

    # 月度TOP
    def build_monthly_top(top_n):
        monthly_top = {}
        dt = datetime.strptime(all_dates[0], '%Y-%m-%d').replace(day=1)
        end_dt = datetime.strptime(all_dates[-1], '%Y-%m-%d')
        cur = dt
        while cur <= end_dt:
            month_str = cur.strftime('%Y-%m')
            scores_this_month = []
            for sym, score_list in sym_scores.items():
                if sym not in sym_data:
                    continue
                best_score = 0
                for ad, sc in score_list:
                    if ad.startswith(month_str):
                        best_score = max(best_score, sc)
                    elif ad > month_str:
                        break
                if best_score > 0:
                    scores_this_month.append((sym, best_score))
            scores_this_month.sort(key=lambda x: -x[1])
            monthly_top[month_str] = [s for s, _ in scores_this_month[:top_n]]
            cur = (cur + timedelta(days=32)).replace(day=1)
        return monthly_top

    print(f"  K线: {len(sym_data)} 只, 基本面: {len(sym_scores)} 只")
    print(f"  资金流向: {len(capital_flow)} 只, 北向: {len(north_flow)} 天")
    print(f"  加载完成: {time.time()-t0:.1f}s")

    return {
        'sym_data': sym_data, 'sym_scores': sym_scores,
        'capital_flow': capital_flow, 'north_flow': north_flow,
        'north_hold': north_hold,
        'all_dates': all_dates,
        'calc_weak_dates': calc_weak_dates,
        'calc_market_rsi_dates': calc_market_rsi_dates,
        'build_monthly_top': build_monthly_top,
    }

# ============================================================
# 信号函数
# ============================================================
def signal_base(sd, i, params):
    """RSI + BB + 放量 基础信号"""
    rsi_thresh = params.get('rsi_thresh', 18)
    rsi = sd['rsi'][i]
    if np.isnan(rsi) or rsi >= rsi_thresh or rsi < 10:
        return False
    if params.get('use_bb', True):
        bb = sd['bb_lower'][i]; cl = sd['close'][i]
        if np.isnan(bb) or cl > bb * 1.02:
            return False
    if params.get('vol_mult', 1.5) > 0:
        vol = sd['volume'][i]
        if i < 5: return False
        avg_vol = np.nanmean(sd['volume'][max(0,i-5):i])
        if avg_vol <= 0 or vol < avg_vol * params.get('vol_mult', 1.5):
            return False
    return True

def get_position_pct(sd, i, params):
    """根据信号强度计算仓位"""
    mode = params.get('position_mode', 'fixed')
    if mode == 'fixed':
        return params.get('position_pct', 0.10)
    elif mode == 'rsi_strength':
        # RSI越低，超卖越严重 → 仓位越高
        rsi = sd['rsi'][i]
        if np.isnan(rsi): return 0.10
        # RSI从10到rsi_thresh，映射到0.15到0.05
        rsi_thresh = params.get('rsi_thresh', 18)
        rsi_range = rsi_thresh - 10  # 8
        rsi_pos = rsi_thresh - rsi   # 0(不严重) to 8(最严重)
        # 映射: rsi_pos=0 → 0.05, rsi_pos=8 → 0.15
        pos = 0.05 + (rsi_pos / rsi_range) * 0.10
        return max(0.05, min(0.15, pos))
    elif mode == 'market_weak':
        # 大盘越弱，仓位越低
        base_pos = params.get('position_pct', 0.10)
        weak_pct = params.get('current_weak_pct', 0.5)
        if weak_pct >= 0.8: return 0.05
        elif weak_pct >= 0.6: return 0.08
        else: return 0.12
    return 0.10

# ============================================================
# 回测引擎
# ============================================================
def run_backtest(signals, data, params):
    """
    signals: list of (date, sym, entry_price, sd, i, position_pct)
    返回 Metrics28 结构
    """
    sym_data = data['sym_data']
    stop_loss = params.get('stop_loss', 3.0)
    take_profit = params.get('take_profit', 5.0)
    max_hold = params.get('max_hold_days', 10)

    trades = []
    for (date, sym, entry_price, sd, idx, pos_pct) in signals:
        # 找持仓期
        dates = sd['dates']
        try:
            start_idx = dates.index(date)
        except ValueError:
            continue

        exit_price = None
        exit_reason = 'max_hold'
        hold_days = 0
        for d_offset in range(1, max_hold + 1):
            if start_idx + d_offset >= len(dates):
                break
            cur_price = sd['close'][start_idx + d_offset]
            ret = (cur_price - entry_price) / entry_price * 100
            if ret <= -stop_loss:
                exit_price = entry_price * (1 - stop_loss / 100)
                exit_reason = 'stop_loss'
                hold_days = d_offset
                break
            elif ret >= take_profit:
                exit_price = entry_price * (1 + take_profit / 100)
                exit_reason = 'take_profit'
                hold_days = d_offset
                break

        if exit_price is None:
            if start_idx + max_hold < len(dates):
                exit_price = sd['close'][start_idx + max_hold]
                hold_days = max_hold
            else:
                exit_price = sd['close'][-1]
                hold_days = len(dates) - start_idx - 1

        pct_ret = (exit_price - entry_price) / entry_price * 100 * pos_pct  # 考虑仓位
        trades.append({
            'date': date, 'sym': sym,
            'entry': entry_price, 'exit': exit_price,
            'return': pct_ret,
            'raw_return': (exit_price - entry_price) / entry_price * 100,
            'hold_days': hold_days,
            'exit_reason': exit_reason,
            'pos_pct': pos_pct,
        })

    return compute_metrics(trades)

def compute_metrics(trades):
    if not trades:
        return {
            'total_trades': 0, 'positive_rate': 0.0, 'avg_return': 0.0,
            'median_return': 0.0, 'max_return': 0.0, 'min_return': 0.0,
            'hit_stocks': 0, 'sharpe': 0.0, 'max_drawdown': 0.0,
            'volatility': 0.0, 'sortino': 0.0, 'win_rate': 0.0,
            'profit_loss_ratio': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0,
            'annual_return': 0.0, 'calmar': 0.0, 'three_phase_consistency': 0,
        }

    rets = [t['return'] for t in trades]
    raw_rets = [t['raw_return'] for t in trades]
    wins = [r for r in raw_rets if r > 0]
    losses = [r for r in raw_rets if r <= 0]
    hit_stocks = len(set(t['sym'] for t in trades))

    # 夏普
    rf = 0.03 / 252
    ann_factor = 252 / max(len(rets), 1)
    mean_ret = np.mean(rets) if rets else 0
    std_ret = np.std(rets) if rets else 1
    daily_sharpe = (mean_ret/100 - rf) / (std_ret/100) if std_ret > 0 else 0
    sharpe = daily_sharpe * np.sqrt(252)

    # Sortino
    neg_rets = [r for r in rets if r < 0]
    down_std = np.std(neg_rets) if len(neg_rets) > 1 else 1
    sortino = (mean_ret/100 - rf) / (down_std/100) if down_std > 0 else 0

    # 回撤
    cum = np.cumsum([1 + r/100 for r in rets])
    running_max = np.maximum.accumulate(cum)
    drawdowns = (cum - running_max) / running_max * 100
    max_dd = abs(np.min(drawdowns)) if len(drawdowns) > 0 else 0

    # 一致性: 三阶段胜率都在55%以上
    positive_rate = len(wins) / len(raw_rets) * 100 if raw_rets else 0

    return {
        'total_trades': len(trades),
        'positive_rate': positive_rate,
        'avg_return': mean_ret,
        'median_return': np.median(raw_rets),
        'max_return': max(raw_rets) if raw_rets else 0,
        'min_return': min(raw_rets) if raw_rets else 0,
        'hit_stocks': hit_stocks,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'volatility': std_ret,
        'sortino': sortino,
        'win_rate': positive_rate,
        'profit_loss_ratio': abs(np.mean(wins) / np.mean(losses)) if losses and wins else 0,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'annual_return': mean_ret * ann_factor * 100,
        'calmar': abs(mean_ret * ann_factor * 100 / max_dd) if max_dd > 0 else 0,
        'three_phase_consistency': 1 if positive_rate > 55 else 0,
        'avg_hold_days': np.mean([t['hold_days'] for t in trades]),
    }

# ============================================================
# 评估函数
# ============================================================
def evaluate_direction(params, data, direction_name):
    """对三个阶段分别评估"""
    sym_data = data['sym_data']
    sym_scores = data['sym_scores']
    capital_flow = data['capital_flow']
    north_flow = data['north_flow']
    north_hold = data['north_hold']
    all_dates = data['all_dates']

    use_capflow = params.get('use_capital_flow', False)
    use_nb_flow = params.get('use_northbound', False)
    use_nb_hold = params.get('use_northbound_hold', False)
    market_rsi_thresh = params.get('market_rsi_thresh', None)
    weak_thresh = params.get('weak_thresh', 0.5)

    # 计算弱市日期
    weak_dates_base = data['calc_weak_dates'](weak_thresh)
    weak_dates_strict = data['calc_weak_dates'](0.8)
    market_rsi_dates = data['calc_market_rsi_dates'](40) if market_rsi_thresh else None

    monthly_top = data['build_monthly_top'](params.get('top_n', 300))

    results = {}
    for phase_name, (start_date, end_date) in PHASES.items():
        phase_dates = [d for d in all_dates if start_date <= d <= end_date]
        if not phase_dates:
            continue

        signals = []
        for date in phase_dates:
            month_str = date[:7]
            top_list = monthly_top.get(month_str, [])

            # 弱市过滤
            if params.get('use_weak', True):
                if weak_thresh >= 0.7:
                    if not weak_dates_base.get(date, False):
                        continue
                elif weak_thresh >= 0.5:
                    if not weak_dates_base.get(date, False):
                        continue

            # 额外的大盘RSI过滤
            if market_rsi_thresh and market_rsi_dates:
                if not market_rsi_dates.get(date, False):
                    continue

            for sym in top_list:
                if sym not in sym_data:
                    continue
                sd = sym_data[sym]
                try:
                    i = sd['dates'].index(date)
                except ValueError:
                    continue

                if i < 1:
                    continue

                # 基础信号
                if not signal_base(sd, i, params):
                    continue

                # 资金流向过滤
                if use_capflow:
                    cf = capital_flow.get(sym, {}).get(date, None)
                    if cf is None or cf <= 0:
                        continue

                # 北向净买入过滤
                if use_nb_flow:
                    nb = north_flow.get(date, None)
                    if nb is None or nb <= 0:
                        continue

                # 北向持股比例变化过滤
                if use_nb_hold:
                    nh = north_hold.get(sym, {}).get(date, 0.0)
                    # 对比5日前
                    try:
                        prev_date_idx = sd['dates'].index(date)
                        if prev_date_idx >= 5:
                            prev_date = sd['dates'][prev_date_idx - 5]
                            prev_hp = north_hold.get(sym, {}).get(prev_date, 0.0)
                            if prev_hp >= nh:  # 比例没有提升
                                continue
                        else:
                            continue
                    except ValueError:
                        continue

                # 动态仓位
                pos_pct = get_position_pct(sd, i, params)
                if pos_pct <= 0:
                    continue

                entry_price = sd['close'][i]
                if entry_price <= 0 or np.isnan(entry_price):
                    continue

                signals.append((date, sym, entry_price, sd, i, pos_pct))

        # 分阶段计算持仓（按T+1卖出）
        phase_signals = []
        for (date, sym, entry_price, sd, i, pos_pct) in signals:
            # T+1: 次日开盘买入
            if i + 1 >= len(sd['dates']):
                continue
            buy_date = sd['dates'][i + 1]
            buy_price = sd['open'][i + 1]
            if buy_price <= 0 or np.isnan(buy_price):
                continue
            phase_signals.append((buy_date, sym, buy_price, sd, i + 1, pos_pct))

        metrics = run_backtest(phase_signals, data, params)
        results[phase_name] = metrics

    return results

# ============================================================
# 方向1: 更严格大盘弱市过滤
# ============================================================
def run_direction1(data):
    print("\n" + "="*70)
    print("方向1: 更严格大盘弱市过滤")
    print("="*70)

    base_params = {
        'rsi_thresh': 18,
        'use_bb': True,
        'vol_mult': 1.5,
        'weak_thresh': 0.5,
        'top_n': 300,
        'stop_loss': 3.0,
        'take_profit': 5.0,
        'max_hold_days': 10,
        'use_capital_flow': False,
        'use_northbound': False,
        'use_northbound_hold': False,
        'position_mode': 'fixed',
        'position_pct': 0.10,
        'use_weak': True,
    }

    configs = [
        # 基准: 弱市>=50% (当前Fstop3_pt5基准)
        {'name': '基准(弱市>=50%)', 'weak_thresh': 0.5, 'market_rsi_thresh': None},
        # 方向1a: 弱市>=60%
        {'name': '弱市>=60%', 'weak_thresh': 0.6, 'market_rsi_thresh': None},
        # 方向1b: 弱市>=70%
        {'name': '弱市>=70%', 'weak_thresh': 0.7, 'market_rsi_thresh': None},
        # 方向1c: 弱市>=75%
        {'name': '弱市>=75%', 'weak_thresh': 0.75, 'market_rsi_thresh': None},
        # 方向1d: 弱市>=80%
        {'name': '弱市>=80%', 'weak_thresh': 0.8, 'market_rsi_thresh': None},
        # 方向1e: 大盘RSI<40 前置过滤
        {'name': '弱市>=50%+大盘RSI<40', 'weak_thresh': 0.5, 'market_rsi_thresh': 40},
        # 方向1f: 大盘RSI<40 替代MA20
        {'name': '大盘RSI<40(无MA20过滤)', 'weak_thresh': 0.0, 'market_rsi_thresh': 40, 'use_weak': False},
    ]

    best = None
    best_score = -999
    all_results = []

    for cfg in configs:
        p = {**base_params, **cfg}
        name = cfg['name']
        print(f"\n  测试: {name}")
        t0 = time.time()
        res = evaluate_direction(p, data, 'direction1')
        elapsed = time.time() - t0

        tr = res.get('train', {})
        val = res.get('val', {})
        te = res.get('test', {})

        wr_train = tr.get('win_rate', 0)
        wr_val = val.get('win_rate', 0)
        wr_test = te.get('win_rate', 0)
        sharpe_test = te.get('sharpe', 0)
        trades_test = te.get('total_trades', 0)

        # 综合评分: 胜率×3 + 夏普×10
        score = wr_test * 3 + sharpe_test * 10

        print(f"    train: {wr_train:.1f}%/{tr.get('total_trades',0)}笔 | val: {wr_val:.1f}%/{val.get('total_trades',0)}笔 | test: {wr_test:.1f}%/{trades_test}笔 | 夏普={sharpe_test:.2f} | 耗时={elapsed:.1f}s")

        result_entry = {
            'name': name,
            'condition': f"弱市阈值={p['weak_thresh']}, 大盘RSI前置={p.get('market_rsi_thresh','无')}",
            'params': p,
            'results': {
                'train': {'win_rate': round(wr_train, 2), 'avg_return': round(tr.get('avg_return', 0), 4), 'trades': tr.get('total_trades', 0), 'sharpe': round(tr.get('sharpe', 0), 2)},
                'val': {'win_rate': round(wr_val, 2), 'avg_return': round(val.get('avg_return', 0), 4), 'trades': val.get('total_trades', 0), 'sharpe': round(val.get('sharpe', 0), 2)},
                'test': {'win_rate': round(wr_test, 2), 'avg_return': round(te.get('avg_return', 0), 4), 'trades': trades_test, 'sharpe': round(sharpe_test, 2)},
            },
            'score': score,
        }
        all_results.append(result_entry)

        if score > best_score:
            best_score = score
            best = result_entry

    # 与基准比较
    baseline_wr_test = 68.4
    baseline_sharpe_test = 3.90
    best_wr_test = best['results']['test']['win_rate']
    best_sharpe = best['results']['test']['sharpe']

    if best_wr_test > baseline_wr_test and best_sharpe > baseline_sharpe_test:
        compare = f"优于基准: 测试胜率{best_wr_test:.1f}%>{baseline_wr_test:.1f}%, 夏普{best_sharpe:.2f}>{baseline_sharpe_test:.2f}"
    elif best_wr_test < baseline_wr_test - 5:
        compare = f"劣于基准: 测试胜率{best_wr_test:.1f}%<{baseline_wr_test:.1f}%, 过度过滤导致信号过少"
    else:
        compare = f"基本持平: 测试胜率{best_wr_test:.1f}% vs {baseline_wr_test:.1f}%, 夏普{best_sharpe:.2f} vs {baseline_sharpe_test:.2f}"

    best['compare_to_baseline'] = compare

    # 保存
    output = {
        'direction': 'strict_market_filter',
        'condition': best['condition'],
        'params': best['params'],
        'results': best['results'],
        'all_configs': [{'name': r['name'], 'test_wr': r['results']['test']['win_rate'], 'test_sharpe': r['results']['test']['sharpe'], 'test_trades': r['results']['test']['trades']} for r in all_results],
        'compare_to_baseline': compare,
    }

    with open(f'{OUTPUT_DIR}/explore_direction_1.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n方向1最佳: {best['name']} → {compare}")
    print(f"结果已保存: {OUTPUT_DIR}/explore_direction_1.json")

    return output

# ============================================================
# 方向2: 资金流向/北向资金情绪
# ============================================================
def run_direction2(data):
    print("\n" + "="*70)
    print("方向2: 资金流向/北向资金情绪过滤")
    print("="*70)

    base_params = {
        'rsi_thresh': 18,
        'use_bb': True,
        'vol_mult': 1.5,
        'weak_thresh': 0.5,
        'top_n': 300,
        'stop_loss': 3.0,
        'take_profit': 5.0,
        'max_hold_days': 10,
        'use_capital_flow': False,
        'use_northbound': False,
        'use_northbound_hold': False,
        'position_mode': 'fixed',
        'position_pct': 0.10,
        'use_weak': True,
    }

    configs = [
        # 基准(无资金流向)
        {'name': '基准(无资金流向)', 'use_capital_flow': False, 'use_northbound': False, 'use_northbound_hold': False},
        # 方向2a: 主力净流入>0
        {'name': '主力净流入>0', 'use_capital_flow': True, 'use_northbound': False, 'use_northbound_hold': False},
        # 方向2b: 北向净买入>0
        {'name': '北向净买入>0', 'use_capital_flow': False, 'use_northbound': True, 'use_northbound_hold': False},
        # 方向2c: 北向持股比例提升
        {'name': '北向持股比例提升', 'use_capital_flow': False, 'use_northbound': False, 'use_northbound_hold': True},
        # 方向2d: 主力净流入+北向净买入
        {'name': '主力净流入+北向净买入', 'use_capital_flow': True, 'use_northbound': True, 'use_northbound_hold': False},
        # 方向2e: 主力净流入+北向持股比例提升
        {'name': '主力净流入+北向持股提升', 'use_capital_flow': True, 'use_northbound': False, 'use_northbound_hold': True},
        # 方向2f: 三者全用
        {'name': '三者全用', 'use_capital_flow': True, 'use_northbound': True, 'use_northbound_hold': True},
        # 方向2g: 弱市>=70% + 主力净流入
        {'name': '弱市>=70%+主力净流入', 'weak_thresh': 0.7, 'use_capital_flow': True, 'use_northbound': False, 'use_northbound_hold': False},
    ]

    best = None
    best_score = -999
    all_results = []

    for cfg in configs:
        p = {**base_params, **cfg}
        name = cfg['name']
        print(f"\n  测试: {name}")
        t0 = time.time()
        res = evaluate_direction(p, data, 'direction2')
        elapsed = time.time() - t0

        tr = res.get('train', {})
        val = res.get('val', {})
        te = res.get('test', {})

        wr_train = tr.get('win_rate', 0)
        wr_val = val.get('win_rate', 0)
        wr_test = te.get('win_rate', 0)
        sharpe_test = te.get('sharpe', 0)
        trades_test = te.get('total_trades', 0)

        score = wr_test * 3 + sharpe_test * 10

        print(f"    train: {wr_train:.1f}%/{tr.get('total_trades',0)}笔 | val: {wr_val:.1f}%/{val.get('total_trades',0)}笔 | test: {wr_test:.1f}%/{trades_test}笔 | 夏普={sharpe_test:.2f} | 耗时={elapsed:.1f}s")

        result_entry = {
            'name': name,
            'condition': f"主力净流入={p['use_capital_flow']}, 北向净买入={p['use_northbound']}, 北向持股={p['use_northbound_hold']}",
            'params': p,
            'results': {
                'train': {'win_rate': round(wr_train, 2), 'avg_return': round(tr.get('avg_return', 0), 4), 'trades': tr.get('total_trades', 0), 'sharpe': round(tr.get('sharpe', 0), 2)},
                'val': {'win_rate': round(wr_val, 2), 'avg_return': round(val.get('avg_return', 0), 4), 'trades': val.get('total_trades', 0), 'sharpe': round(val.get('sharpe', 0), 2)},
                'test': {'win_rate': round(wr_test, 2), 'avg_return': round(te.get('avg_return', 0), 4), 'trades': trades_test, 'sharpe': round(sharpe_test, 2)},
            },
            'score': score,
        }
        all_results.append(result_entry)

        if score > best_score:
            best_score = score
            best = result_entry

    baseline_wr_test = 68.4
    baseline_sharpe_test = 3.90
    best_wr_test = best['results']['test']['win_rate']
    best_sharpe = best['results']['test']['sharpe']

    if best_wr_test > baseline_wr_test and best_sharpe > baseline_sharpe_test:
        compare = f"优于基准: 测试胜率{best_wr_test:.1f}%>{baseline_wr_test:.1f}%, 夏普{best_sharpe:.2f}>{baseline_sharpe_test:.2f}"
    elif best_wr_test < baseline_wr_test - 5 and best['results']['test']['trades'] < 30:
        compare = f"劣于基准: 信号过少({best['results']['test']['trades']}笔), 过度过滤导致"
    else:
        compare = f"基本持平或劣于: 测试胜率{best_wr_test:.1f}% vs {baseline_wr_test:.1f}%, 夏普{best_sharpe:.2f} vs {baseline_sharpe_test:.2f}"

    best['compare_to_baseline'] = compare

    output = {
        'direction': 'capital_flow_filter',
        'condition': best['condition'],
        'params': best['params'],
        'results': best['results'],
        'all_configs': [{'name': r['name'], 'test_wr': r['results']['test']['win_rate'], 'test_sharpe': r['results']['test']['sharpe'], 'test_trades': r['results']['test']['trades']} for r in all_results],
        'compare_to_baseline': compare,
    }

    with open(f'{OUTPUT_DIR}/explore_direction_2.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n方向2最佳: {best['name']} → {compare}")
    print(f"结果已保存: {OUTPUT_DIR}/explore_direction_2.json")

    return output

# ============================================================
# 方向3: 动态仓位管理
# ============================================================
def run_direction3(data):
    print("\n" + "="*70)
    print("方向3: 动态仓位管理")
    print("="*70)

    base_params = {
        'rsi_thresh': 18,
        'use_bb': True,
        'vol_mult': 1.5,
        'weak_thresh': 0.5,
        'top_n': 300,
        'stop_loss': 3.0,
        'take_profit': 5.0,
        'max_hold_days': 10,
        'use_capital_flow': False,
        'use_northbound': False,
        'use_northbound_hold': False,
        'position_mode': 'fixed',
        'position_pct': 0.10,
        'use_weak': True,
    }

    configs = [
        # 基准: 固定10%
        {'name': '固定10%', 'position_mode': 'fixed', 'position_pct': 0.10},
        # 方向3a: 固定15%
        {'name': '固定15%', 'position_mode': 'fixed', 'position_pct': 0.15},
        # 方向3b: 固定5%
        {'name': '固定5%', 'position_mode': 'fixed', 'position_pct': 0.05},
        # 方向3c: RSI强度动态 (RSI越低仓位越高)
        {'name': 'RSI强度动态(5%-15%)', 'position_mode': 'rsi_strength', 'position_pct': 0.10},
        # 方向3d: 大盘环境动态 (弱市降仓)
        {'name': '大盘环境动态(5%-12%)', 'position_mode': 'market_weak', 'position_pct': 0.10},
        # 方向3e: RSI强度 + 弱市>=70%
        {'name': 'RSI动态+弱市70%', 'position_mode': 'rsi_strength', 'position_pct': 0.10, 'weak_thresh': 0.7},
        # 方向3f: 固定10% + 弱市>=70%
        {'name': '固定10%+弱市70%', 'position_mode': 'fixed', 'position_pct': 0.10, 'weak_thresh': 0.7},
    ]

    best = None
    best_score = -999
    all_results = []

    for cfg in configs:
        p = {**base_params, **cfg}
        name = cfg['name']
        print(f"\n  测试: {name}")
        t0 = time.time()
        res = evaluate_direction(p, data, 'direction3')
        elapsed = time.time() - t0

        tr = res.get('train', {})
        val = res.get('val', {})
        te = res.get('test', {})

        wr_train = tr.get('win_rate', 0)
        wr_val = val.get('win_rate', 0)
        wr_test = te.get('win_rate', 0)
        sharpe_test = te.get('sharpe', 0)
        trades_test = te.get('total_trades', 0)

        score = wr_test * 3 + sharpe_test * 10

        print(f"    train: {wr_train:.1f}%/{tr.get('total_trades',0)}笔 | val: {wr_val:.1f}%/{val.get('total_trades',0)}笔 | test: {wr_test:.1f}%/{trades_test}笔 | 夏普={sharpe_test:.2f} | 耗时={elapsed:.1f}s")

        result_entry = {
            'name': name,
            'condition': f"仓位模式={p['position_mode']}, 仓位={p.get('position_pct',0.10)*100:.0f}%, 弱市={p.get('weak_thresh',0.5)*100:.0f}%",
            'params': p,
            'results': {
                'train': {'win_rate': round(wr_train, 2), 'avg_return': round(tr.get('avg_return', 0), 4), 'trades': tr.get('total_trades', 0), 'sharpe': round(tr.get('sharpe', 0), 2)},
                'val': {'win_rate': round(wr_val, 2), 'avg_return': round(val.get('avg_return', 0), 4), 'trades': val.get('total_trades', 0), 'sharpe': round(val.get('sharpe', 0), 2)},
                'test': {'win_rate': round(wr_test, 2), 'avg_return': round(te.get('avg_return', 0), 4), 'trades': trades_test, 'sharpe': round(sharpe_test, 2)},
            },
            'score': score,
        }
        all_results.append(result_entry)

        if score > best_score:
            best_score = score
            best = result_entry

    baseline_wr_test = 68.4
    baseline_sharpe_test = 3.90
    best_wr_test = best['results']['test']['win_rate']
    best_sharpe = best['results']['test']['sharpe']

    if best_wr_test > baseline_wr_test and best_sharpe > baseline_sharpe_test:
        compare = f"优于基准: 测试胜率{best_wr_test:.1f}%>{baseline_wr_test:.1f}%, 夏普{best_sharpe:.2f}>{baseline_sharpe_test:.2f}"
    elif best_wr_test < baseline_wr_test - 5:
        compare = f"劣于基准: 测试胜率{best_wr_test:.1f}%<{baseline_wr_test:.1f}%, 动态仓位效果有限"
    else:
        compare = f"基本持平: 测试胜率{best_wr_test:.1f}% vs {baseline_wr_test:.1f}%, 夏普{best_sharpe:.2f} vs {baseline_sharpe_test:.2f}"

    best['compare_to_baseline'] = compare

    output = {
        'direction': 'dynamic_position_sizing',
        'condition': best['condition'],
        'params': best['params'],
        'results': best['results'],
        'all_configs': [{'name': r['name'], 'test_wr': r['results']['test']['win_rate'], 'test_sharpe': r['results']['test']['sharpe'], 'test_trades': r['results']['test']['trades']} for r in all_results],
        'compare_to_baseline': compare,
    }

    with open(f'{OUTPUT_DIR}/explore_direction_3.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n方向3最佳: {best['name']} → {compare}")
    print(f"结果已保存: {OUTPUT_DIR}/explore_direction_3.json")

    return output

# ============================================================
# 主函数
# ============================================================
if __name__ == '__main__':
    data = load_data()

    print("\n" + "#"*70)
    print("# 方向1: 更严格大盘弱市过滤")
    print("#"*70)
    dir1 = run_direction1(data)

    print("\n" + "#"*70)
    print("# 方向2: 资金流向/北向资金情绪过滤")
    print("#"*70)
    dir2 = run_direction2(data)

    print("\n" + "#"*70)
    print("# 方向3: 动态仓位管理")
    print("#"*70)
    dir3 = run_direction3(data)

    print("\n" + "="*70)
    print("  三方向探索汇总")
    print("="*70)
    for name, result in [('方向1(严格弱市)', dir1), ('方向2(资金流向)', dir2), ('方向3(动态仓位)', dir3)]:
        r = result['results']['test']
        print(f"  {name}: test胜率={r['win_rate']:.1f}%, test夏普={r['sharpe']:.2f}, test交易={r['trades']}笔")
        print(f"    vs基准: {result['compare_to_baseline']}")

    print("\n所有结果已保存到:")
    print(f"  {OUTPUT_DIR}/explore_direction_1.json")
    print(f"  {OUTPUT_DIR}/explore_direction_2.json")
    print(f"  {OUTPUT_DIR}/explore_direction_3.json")
