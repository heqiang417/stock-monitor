#!/usr/bin/env python3
"""
探索方向9-13：不依赖弱市过滤的股票交易策略

D9: 纯 RSI 超卖
D10: 趋势回归（MA5>MA10>MA20 + RSI<25 超跌）
D11: 极度超卖（RSI<15/18 + 连续下跌N天）
D12: 缩量底部（VOL < MA20*0.3 + RSI<20 + BB下轨）
D13: 布林带下轨反弹（BB下轨 + RSI<25）

合格标准:
- train/val/test 正率均 > 55%
- 三阶段一致性 = 1
- test 夏普 > 1
- test 盈亏比 > 1.1
- test 回撤 < 50%
- test 交易数 >= 30
"""
import json
import os
import sqlite3
import time
import multiprocessing as mp
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import product

import numpy as np

PROJECT_ROOT = "/home/heqiang/.openclaw/workspace/stock-monitor-app-py"
DB = os.path.join(PROJECT_ROOT, "data/stock_data.db")
OUTPUT = os.path.join(PROJECT_ROOT, "data/results/explore_direction_9_13.json")
WORKERS = max(1, int(os.environ.get('D9_WORKERS', mp.cpu_count())))

PHASES = {
    "train": ("2021-01-01", "2024-06-30"),
    "val":   ("2024-07-01", "2025-07-01"),
    "test":  ("2025-07-02", "2026-03-27"),
}
RF = 0.03
COST = 0.30


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def pit_delay_days(report_date: str) -> int:
    m = int(report_date[5:7])
    return {3: 30, 6: 62, 9: 31, 12: 120}.get(m, 45)


def pit_effective_date(report_date: str) -> str:
    return (datetime.strptime(report_date, "%Y-%m-%d") + timedelta(days=pit_delay_days(report_date))).strftime("%Y-%m-%d")


def fund_score(roe, rev_g, profit_g, gross_margin, debt_ratio):
    roe = roe or 0
    rev_g = rev_g or 0
    profit_g = profit_g or 0
    gross_margin = gross_margin or 0
    debt_ratio = debt_ratio if debt_ratio is not None else 100
    s = min(max(roe, 0), 30)
    s += min(max(rev_g, 0) * 0.4, 20)
    s += min(max(profit_g, 0) * 0.4, 20)
    s += min(max(gross_margin, 0) * 0.3, 15)
    if debt_ratio < 30:
        s += 15
    elif debt_ratio < 50:
        s += 10
    elif debt_ratio < 70:
        s += 5
    return s


def calc_28_metrics(returns, hold_days, hit_stock_count=0):
    keys = [
        "total_trades", "positive_rate", "avg_return", "median_return", "max_return", "min_return", "hit_stocks",
        "sharpe", "max_drawdown", "volatility", "downside_volatility", "sortino",
        "win_rate", "profit_loss_ratio", "avg_win", "avg_loss", "max_win", "max_loss",
        "max_consec_wins", "max_consec_losses",
        "annual_return", "calmar", "recovery_factor", "breakeven_wr", "expectancy",
        "train_test_ratio", "three_phase_consistency", "avg_hold_days",
    ]
    if not returns:
        return {k: 0 for k in keys}

    r = np.array(returns, dtype=float)
    n = len(r)
    pos = r[r > 0]
    neg = r[r <= 0]
    pos_rate = len(pos) / n * 100

    avg_ret = float(np.mean(r))
    median_ret = float(np.median(r))
    max_ret = float(np.max(r))
    min_ret = float(np.min(r))

    ann_ret = avg_ret * 252 / hold_days
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_vol = std * np.sqrt(252 / hold_days) if std > 0 else 0
    sharpe = (ann_ret - RF * 100) / ann_vol if ann_vol > 0 else 0

    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold_days)) if len(dn) > 1 else 0
    sortino = (ann_ret - RF * 100) / dn_std if dn_std > 0 else 0

    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for x in returns:
        cum += np.log(1 + x / 100)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)

    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0

    cw = cl = cwmax = clmax = 0
    for x in returns:
        if x > 0:
            cw += 1; cl = 0; cwmax = max(cwmax, cw)
        else:
            cl += 1; cw = 0; clmax = max(clmax, cl)

    expectancy = float(len(pos) / n * np.mean(pos) + len(neg) / n * np.mean(neg)) if len(neg) > 0 else avg_ret
    total_ret = float(np.sum(r))
    recovery_factor = total_ret / abs(mdd * 100) if mdd > 0.0001 else 0
    breakeven = 1 / (1 + plr) * 100 if plr > 0 else 100

    return {
        "total_trades": n,
        "positive_rate": round(pos_rate, 2),
        "avg_return": round(avg_ret, 4),
        "median_return": round(median_ret, 4),
        "max_return": round(max_ret, 4),
        "min_return": round(min_ret, 4),
        "hit_stocks": hit_stock_count,
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd * 100, 4),
        "volatility": round(ann_vol, 4),
        "downside_volatility": round(dn_std, 4),
        "sortino": round(sortino, 4),
        "win_rate": round(pos_rate, 2),
        "profit_loss_ratio": round(plr, 4),
        "avg_win": round(float(np.mean(pos)), 4) if len(pos) > 0 else 0,
        "avg_loss": round(float(np.mean(neg)), 4) if len(neg) > 0 else 0,
        "max_win": round(max_ret, 4),
        "max_loss": round(min_ret, 4),
        "max_consec_wins": cwmax,
        "max_consec_losses": clmax,
        "annual_return": round(ann_ret, 4),
        "calmar": round(ann_ret / (mdd * 100), 4) if mdd > 0.0001 else 0,
        "recovery_factor": round(recovery_factor, 4),
        "breakeven_wr": round(breakeven, 2),
        "expectancy": round(expectancy, 4),
        "train_test_ratio": 0,
        "three_phase_consistency": 0,
        "avg_hold_days": hold_days,
    }


def load_data(conn):
    log("加载PIT基本面...")
    fund_rows = conn.execute(
        """
        SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio
        FROM financial_indicators
        WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL OR profit_growth IS NOT NULL
        ORDER BY symbol, report_date
        """
    ).fetchall()

    sym_scores_pit = defaultdict(list)
    for sym, rd, roe, rg, pg, gm, dr in fund_rows:
        s = fund_score(roe, rg, pg, gm, dr)
        if s > 0 and rd:
            sym_scores_pit[sym].append((pit_effective_date(rd), s))

    log(f"  {len(sym_scores_pit)} 股票有PIT分数")
    log("加载K线数据...")

    sym_data = {}
    for sym in sym_scores_pit.keys():
        rows = conn.execute(
            """
            SELECT trade_date, open, close, volume, rsi14, boll_lower
            FROM kline_daily
            WHERE symbol=? AND trade_date>='2020-12-01' AND trade_date<='2026-03-31'
            ORDER BY trade_date
            """,
            (sym,),
        ).fetchall()
        if len(rows) < 60:
            continue

        dates = [r[0] for r in rows]
        opens = np.array([r[1] for r in rows], dtype=float)
        closes = np.array([r[2] for r in rows], dtype=float)
        vols = np.array([r[3] for r in rows], dtype=float)
        rsi = np.array([r[4] if r[4] is not None else np.nan for r in rows], dtype=float)
        bb_l = np.array([r[5] if r[5] is not None else np.nan for r in rows], dtype=float)

        # MA20
        ma20 = np.full(len(closes), np.nan)
        for i in range(19, len(closes)):
            ma20[i] = np.nanmean(closes[i - 19 : i + 1])

        # MA10
        ma10 = np.full(len(closes), np.nan)
        for i in range(9, len(closes)):
            ma10[i] = np.nanmean(closes[i - 9 : i + 1])

        # MA5
        ma5 = np.full(len(closes), np.nan)
        for i in range(4, len(closes)):
            ma5[i] = np.nanmean(closes[i - 4 : i + 1])

        # VOL MA20
        vol_ma20 = np.full(len(vols), np.nan)
        for i in range(19, len(vols)):
            vol_ma20[i] = np.nanmean(vols[i - 19 : i + 1])

        sym_data[sym] = {
            "dates": dates,
            "open": opens,
            "close": closes,
            "volume": vols,
            "rsi": rsi,
            "bb_lower": bb_l,
            "ma20": ma20,
            "ma10": ma10,
            "ma5": ma5,
            "vol_ma20": vol_ma20,
        }

    log(f"  {len(sym_data)} 股票已加载")
    return sym_data, dict(sym_scores_pit)


def month_iter(start_date: str, end_date: str):
    cur = datetime.strptime(start_date, "%Y-%m-%d").replace(day=1)
    phase_end = datetime.strptime(end_date, "%Y-%m-%d")
    while cur <= phase_end:
        next_month = (cur + timedelta(days=32)).replace(day=1)
        yield cur.strftime("%Y-%m-%d"), next_month.strftime("%Y-%m-%d")
        cur = next_month


def qualify(res):
    """判断是否满足合格标准"""
    t = res["train"]["metrics"]
    v = res["val"]["metrics"]
    te = res["test"]["metrics"]

    # 三阶段一致性
    pos_rates = [t["positive_rate"], v["positive_rate"], te["positive_rate"]]
    three_phase_consistency = 1 if all(pr > 55 for pr in pos_rates) else 0

    return (
        t["positive_rate"] > 55 and
        v["positive_rate"] > 55 and
        te["positive_rate"] > 55 and
        te["total_trades"] >= 30 and
        three_phase_consistency == 1 and
        te["sharpe"] > 1 and
        te["max_drawdown"] < 50 and
        te["profit_loss_ratio"] > 1.1
    ), three_phase_consistency


def run_backtest_d9(sym_data, sym_scores_pit, params):
    """
    D9: 纯 RSI 超卖
    信号：RSI < rsi_thresh 且 price <= boll_lower * bb_mult
    持有：hold_days
    止损止盈：SL3% TP5%
    top_n: 300/500/800
    """
    results = {}
    hold_days = params["max_hold_days"]
    top_n = params["top_n"]
    rsi_thresh = params["rsi_thresh"]
    bb_mult = params.get("bb_mult", 1.0)
    stop_loss = params.get("stop_loss", 3.0)
    take_profit = params.get("take_profit", 5.0)

    for phase, (phase_start, phase_end) in PHASES.items():
        returns = []
        actual_holds = []
        hit_stocks_set = set()

        for month_start, next_month_start in month_iter(phase_start, phase_end):
            # 月度选股：按基本面分排序
            scored = []
            for sym in sym_data:
                latest_score = 0
                for eff_date, score in reversed(sym_scores_pit.get(sym, [])):
                    if eff_date <= month_start:
                        latest_score = score
                        break
                if latest_score > 0:
                    scored.append((sym, latest_score))
            scored.sort(key=lambda x: -x[1])
            monthly_top = [s[0] for s in scored[:top_n]] if top_n > 0 else [s[0] for s in scored]

            for sym in monthly_top:
                sd = sym_data.get(sym)
                if sd is None:
                    continue

                dates = sd["dates"]
                closes = sd["close"]
                opens_arr = sd["open"]
                rsi = sd["rsi"]
                bb_l = sd["bb_lower"]

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < month_start:
                        i += 1
                        continue
                    if d >= next_month_start or d > phase_end:
                        break
                    if d < phase_start:
                        i += 1
                        continue
                    if i + 1 >= len(dates):
                        break

                    # D9 信号检查
                    if np.isnan(rsi[i]) or rsi[i] >= rsi_thresh or rsi[i] < 10:
                        i += 1
                        continue
                    price = closes[i]
                    if np.isnan(bb_l[i]) or bb_l[i] <= 0 or price > bb_l[i] * bb_mult:
                        i += 1
                        continue

                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price):
                        i += 1
                        continue

                    # 卖出逻辑
                    sell_idx = None
                    for h in range(1, hold_days + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates):
                            break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -stop_loss:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 - stop_loss / 100)
                            break
                        if pct_chg >= take_profit:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 + take_profit / 100)
                            break

                    if sell_idx is None:
                        sell_idx = min(buy_idx + hold_days, len(dates) - 1)
                        sell_price = closes[sell_idx]

                    if np.isnan(sell_price) or sell_price <= 0:
                        i += 1
                        continue

                    ret = (sell_price - buy_price) / buy_price * 100 - COST
                    returns.append(ret)
                    actual_holds.append(max(1, sell_idx - buy_idx))
                    hit_stocks_set.add(sym)
                    i += max(1, sell_idx - i)

        avg_hold = round(float(np.mean(actual_holds)), 2) if actual_holds else hold_days
        metrics = calc_28_metrics(returns, avg_hold, len(hit_stocks_set))
        results[phase] = {"metrics": metrics, "trades": len(returns), "hit_stocks": len(hit_stocks_set)}

    # 三阶段一致性
    pos_rates = [results[p]["metrics"]["positive_rate"] for p in ["train", "val", "test"]]
    consistency = 1 if all(pr > 55 for pr in pos_rates) else 0
    for phase in results:
        results[phase]["metrics"]["three_phase_consistency"] = consistency
    return results


def run_backtest_d10(sym_data, sym_scores_pit, params):
    """
    D10: 趋势回归
    信号：MA5 > MA10 > MA20（多头排列），RSI < rsi_thresh（回调超卖）
    """
    results = {}
    hold_days = params["max_hold_days"]
    top_n = params["top_n"]
    rsi_thresh = params["rsi_thresh"]
    stop_loss = params.get("stop_loss", 3.0)
    take_profit = params.get("take_profit", 5.0)

    for phase, (phase_start, phase_end) in PHASES.items():
        returns = []
        actual_holds = []
        hit_stocks_set = set()

        for month_start, next_month_start in month_iter(phase_start, phase_end):
            scored = []
            for sym in sym_data:
                latest_score = 0
                for eff_date, score in reversed(sym_scores_pit.get(sym, [])):
                    if eff_date <= month_start:
                        latest_score = score
                        break
                if latest_score > 0:
                    scored.append((sym, latest_score))
            scored.sort(key=lambda x: -x[1])
            monthly_top = [s[0] for s in scored[:top_n]] if top_n > 0 else [s[0] for s in scored]

            for sym in monthly_top:
                sd = sym_data.get(sym)
                if sd is None:
                    continue

                dates = sd["dates"]
                closes = sd["close"]
                opens_arr = sd["open"]
                rsi = sd["rsi"]
                ma5 = sd["ma5"]
                ma10 = sd["ma10"]
                ma20 = sd["ma20"]

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < month_start:
                        i += 1
                        continue
                    if d >= next_month_start or d > phase_end:
                        break
                    if d < phase_start:
                        i += 1
                        continue
                    if i + 1 >= len(dates):
                        break

                    # D10 信号检查：MA5 > MA10 > MA20 多头排列
                    if np.isnan(ma5[i]) or np.isnan(ma10[i]) or np.isnan(ma20[i]):
                        i += 1
                        continue
                    if not (ma5[i] > ma10[i] > ma20[i]):
                        i += 1
                        continue
                    # RSI 超卖
                    if np.isnan(rsi[i]) or rsi[i] >= rsi_thresh or rsi[i] < 10:
                        i += 1
                        continue

                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price):
                        i += 1
                        continue

                    sell_idx = None
                    for h in range(1, hold_days + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates):
                            break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -stop_loss:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 - stop_loss / 100)
                            break
                        if pct_chg >= take_profit:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 + take_profit / 100)
                            break

                    if sell_idx is None:
                        sell_idx = min(buy_idx + hold_days, len(dates) - 1)
                        sell_price = closes[sell_idx]

                    if np.isnan(sell_price) or sell_price <= 0:
                        i += 1
                        continue

                    ret = (sell_price - buy_price) / buy_price * 100 - COST
                    returns.append(ret)
                    actual_holds.append(max(1, sell_idx - buy_idx))
                    hit_stocks_set.add(sym)
                    i += max(1, sell_idx - i)

        avg_hold = round(float(np.mean(actual_holds)), 2) if actual_holds else hold_days
        metrics = calc_28_metrics(returns, avg_hold, len(hit_stocks_set))
        results[phase] = {"metrics": metrics, "trades": len(returns), "hit_stocks": len(hit_stocks_set)}

    pos_rates = [results[p]["metrics"]["positive_rate"] for p in ["train", "val", "test"]]
    consistency = 1 if all(pr > 55 for pr in pos_rates) else 0
    for phase in results:
        results[phase]["metrics"]["three_phase_consistency"] = consistency
    return results


def run_backtest_d11(sym_data, sym_scores_pit, params):
    """
    D11: 极度超卖
    信号：RSI < rsi_thresh，且连续下跌N天
    """
    results = {}
    hold_days = params["max_hold_days"]
    top_n = params["top_n"]
    rsi_thresh = params["rsi_thresh"]
    down_days = params["down_days"]
    stop_loss = params.get("stop_loss", 3.0)
    take_profit = params.get("take_profit", 5.0)

    for phase, (phase_start, phase_end) in PHASES.items():
        returns = []
        actual_holds = []
        hit_stocks_set = set()

        for month_start, next_month_start in month_iter(phase_start, phase_end):
            scored = []
            for sym in sym_data:
                latest_score = 0
                for eff_date, score in reversed(sym_scores_pit.get(sym, [])):
                    if eff_date <= month_start:
                        latest_score = score
                        break
                if latest_score > 0:
                    scored.append((sym, latest_score))
            scored.sort(key=lambda x: -x[1])
            monthly_top = [s[0] for s in scored[:top_n]] if top_n > 0 else [s[0] for s in scored]

            for sym in monthly_top:
                sd = sym_data.get(sym)
                if sd is None:
                    continue

                dates = sd["dates"]
                closes = sd["close"]
                opens_arr = sd["open"]
                rsi = sd["rsi"]

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < month_start:
                        i += 1
                        continue
                    if d >= next_month_start or d > phase_end:
                        break
                    if d < phase_start:
                        i += 1
                        continue
                    if i + 1 >= len(dates):
                        break
                    if i < down_days:
                        i += 1
                        continue

                    # D11 信号检查
                    if np.isnan(rsi[i]) or rsi[i] >= rsi_thresh or rsi[i] < 5:
                        i += 1
                        continue

                    # 连续下跌 N 天
                    consec_down = 0
                    for k in range(i - 1, i - down_days - 1, -1):
                        if k < 0:
                            break
                        if closes[k] < closes[k + 1]:
                            consec_down += 1
                        else:
                            break

                    if consec_down < down_days:
                        i += 1
                        continue

                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price):
                        i += 1
                        continue

                    sell_idx = None
                    for h in range(1, hold_days + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates):
                            break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -stop_loss:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 - stop_loss / 100)
                            break
                        if pct_chg >= take_profit:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 + take_profit / 100)
                            break

                    if sell_idx is None:
                        sell_idx = min(buy_idx + hold_days, len(dates) - 1)
                        sell_price = closes[sell_idx]

                    if np.isnan(sell_price) or sell_price <= 0:
                        i += 1
                        continue

                    ret = (sell_price - buy_price) / buy_price * 100 - COST
                    returns.append(ret)
                    actual_holds.append(max(1, sell_idx - buy_idx))
                    hit_stocks_set.add(sym)
                    i += max(1, sell_idx - i)

        avg_hold = round(float(np.mean(actual_holds)), 2) if actual_holds else hold_days
        metrics = calc_28_metrics(returns, avg_hold, len(hit_stocks_set))
        results[phase] = {"metrics": metrics, "trades": len(returns), "hit_stocks": len(hit_stocks_set)}

    pos_rates = [results[p]["metrics"]["positive_rate"] for p in ["train", "val", "test"]]
    consistency = 1 if all(pr > 55 for pr in pos_rates) else 0
    for phase in results:
        results[phase]["metrics"]["three_phase_consistency"] = consistency
    return results


def run_backtest_d12(sym_data, sym_scores_pit, params):
    """
    D12: 缩量底部
    信号：VOL < vol_ma20 * vol_mult + RSI < rsi_thresh + 价格在BB下轨
    """
    results = {}
    hold_days = params["max_hold_days"]
    top_n = params["top_n"]
    rsi_thresh = params["rsi_thresh"]
    vol_mult = params.get("vol_mult", 0.3)
    bb_mult = params.get("bb_mult", 1.0)
    stop_loss = params.get("stop_loss", 3.0)
    take_profit = params.get("take_profit", 5.0)

    for phase, (phase_start, phase_end) in PHASES.items():
        returns = []
        actual_holds = []
        hit_stocks_set = set()

        for month_start, next_month_start in month_iter(phase_start, phase_end):
            scored = []
            for sym in sym_data:
                latest_score = 0
                for eff_date, score in reversed(sym_scores_pit.get(sym, [])):
                    if eff_date <= month_start:
                        latest_score = score
                        break
                if latest_score > 0:
                    scored.append((sym, latest_score))
            scored.sort(key=lambda x: -x[1])
            monthly_top = [s[0] for s in scored[:top_n]] if top_n > 0 else [s[0] for s in scored]

            for sym in monthly_top:
                sd = sym_data.get(sym)
                if sd is None:
                    continue

                dates = sd["dates"]
                closes = sd["close"]
                opens_arr = sd["open"]
                rsi = sd["rsi"]
                bb_l = sd["bb_lower"]
                vols = sd["volume"]
                vol_ma20 = sd["vol_ma20"]

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < month_start:
                        i += 1
                        continue
                    if d >= next_month_start or d > phase_end:
                        break
                    if d < phase_start:
                        i += 1
                        continue
                    if i + 1 >= len(dates):
                        break

                    # D12 信号检查
                    # RSI < rsi_thresh
                    if np.isnan(rsi[i]) or rsi[i] >= rsi_thresh or rsi[i] < 10:
                        i += 1
                        continue
                    # 价格在 BB 下轨
                    price = closes[i]
                    if np.isnan(bb_l[i]) or bb_l[i] <= 0 or price > bb_l[i] * bb_mult:
                        i += 1
                        continue
                    # 极度缩量
                    if np.isnan(vols[i]) or np.isnan(vol_ma20[i]) or vol_ma20[i] <= 0:
                        i += 1
                        continue
                    if vols[i] >= vol_ma20[i] * vol_mult:
                        i += 1
                        continue

                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price):
                        i += 1
                        continue

                    sell_idx = None
                    for h in range(1, hold_days + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates):
                            break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -stop_loss:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 - stop_loss / 100)
                            break
                        if pct_chg >= take_profit:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 + take_profit / 100)
                            break

                    if sell_idx is None:
                        sell_idx = min(buy_idx + hold_days, len(dates) - 1)
                        sell_price = closes[sell_idx]

                    if np.isnan(sell_price) or sell_price <= 0:
                        i += 1
                        continue

                    ret = (sell_price - buy_price) / buy_price * 100 - COST
                    returns.append(ret)
                    actual_holds.append(max(1, sell_idx - buy_idx))
                    hit_stocks_set.add(sym)
                    i += max(1, sell_idx - i)

        avg_hold = round(float(np.mean(actual_holds)), 2) if actual_holds else hold_days
        metrics = calc_28_metrics(returns, avg_hold, len(hit_stocks_set))
        results[phase] = {"metrics": metrics, "trades": len(returns), "hit_stocks": len(hit_stocks_set)}

    pos_rates = [results[p]["metrics"]["positive_rate"] for p in ["train", "val", "test"]]
    consistency = 1 if all(pr > 55 for pr in pos_rates) else 0
    for phase in results:
        results[phase]["metrics"]["three_phase_consistency"] = consistency
    return results


def run_backtest_d13(sym_data, sym_scores_pit, params):
    """
    D13: 布林带下轨反弹
    信号：price <= boll_lower * bb_mult，RSI < rsi_thresh
    """
    results = {}
    hold_days = params["max_hold_days"]
    top_n = params["top_n"]
    rsi_thresh = params["rsi_thresh"]
    bb_mult = params.get("bb_mult", 1.0)
    stop_loss = params.get("stop_loss", 3.0)
    take_profit = params.get("take_profit", 5.0)

    for phase, (phase_start, phase_end) in PHASES.items():
        returns = []
        actual_holds = []
        hit_stocks_set = set()

        for month_start, next_month_start in month_iter(phase_start, phase_end):
            scored = []
            for sym in sym_data:
                latest_score = 0
                for eff_date, score in reversed(sym_scores_pit.get(sym, [])):
                    if eff_date <= month_start:
                        latest_score = score
                        break
                if latest_score > 0:
                    scored.append((sym, latest_score))
            scored.sort(key=lambda x: -x[1])
            monthly_top = [s[0] for s in scored[:top_n]] if top_n > 0 else [s[0] for s in scored]

            for sym in monthly_top:
                sd = sym_data.get(sym)
                if sd is None:
                    continue

                dates = sd["dates"]
                closes = sd["close"]
                opens_arr = sd["open"]
                rsi = sd["rsi"]
                bb_l = sd["bb_lower"]

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < month_start:
                        i += 1
                        continue
                    if d >= next_month_start or d > phase_end:
                        break
                    if d < phase_start:
                        i += 1
                        continue
                    if i + 1 >= len(dates):
                        break

                    # D13 信号检查
                    if np.isnan(rsi[i]) or rsi[i] >= rsi_thresh or rsi[i] < 10:
                        i += 1
                        continue
                    price = closes[i]
                    if np.isnan(bb_l[i]) or bb_l[i] <= 0 or price > bb_l[i] * bb_mult:
                        i += 1
                        continue

                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price):
                        i += 1
                        continue

                    sell_idx = None
                    for h in range(1, hold_days + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates):
                            break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -stop_loss:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 - stop_loss / 100)
                            break
                        if pct_chg >= take_profit:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 + take_profit / 100)
                            break

                    if sell_idx is None:
                        sell_idx = min(buy_idx + hold_days, len(dates) - 1)
                        sell_price = closes[sell_idx]

                    if np.isnan(sell_price) or sell_price <= 0:
                        i += 1
                        continue

                    ret = (sell_price - buy_price) / buy_price * 100 - COST
                    returns.append(ret)
                    actual_holds.append(max(1, sell_idx - buy_idx))
                    hit_stocks_set.add(sym)
                    i += max(1, sell_idx - i)

        avg_hold = round(float(np.mean(actual_holds)), 2) if actual_holds else hold_days
        metrics = calc_28_metrics(returns, avg_hold, len(hit_stocks_set))
        results[phase] = {"metrics": metrics, "trades": len(returns), "hit_stocks": len(hit_stocks_set)}

    pos_rates = [results[p]["metrics"]["positive_rate"] for p in ["train", "val", "test"]]
    consistency = 1 if all(pr > 55 for pr in pos_rates) else 0
    for phase in results:
        results[phase]["metrics"]["three_phase_consistency"] = consistency
    return results


def make_name(direction, params):
    if direction == "D9":
        return (f"D9_RSI{params['rsi_thresh']}_BB{params.get('bb_mult',1.0):.2f}_"
                f"H{params['max_hold_days']}_TOP{params['top_n']}_SL{params.get('stop_loss',3.0)}_TP{params.get('take_profit',5.0)}")
    elif direction == "D10":
        return (f"D10_RSI{params['rsi_thresh']}_H{params['max_hold_days']}_TOP{params['top_n']}_"
                f"SL{params.get('stop_loss',3.0)}_TP{params.get('take_profit',5.0)}")
    elif direction == "D11":
        return (f"D11_RSI{params['rsi_thresh']}_down{params['down_days']}d_H{params['max_hold_days']}_TOP{params['top_n']}_"
                f"SL{params.get('stop_loss',3.0)}_TP{params.get('take_profit',5.0)}")
    elif direction == "D12":
        return (f"D12_RSI{params['rsi_thresh']}_VOL{params.get('vol_mult',0.3)}x_BB{params.get('bb_mult',1.0)}_"
                f"H{params['max_hold_days']}_TOP{params['top_n']}_SL{params.get('stop_loss',3.0)}_TP{params.get('take_profit',5.0)}")
    elif direction == "D13":
        return (f"D13_RSI{params['rsi_thresh']}_BB{params.get('bb_mult',1.0)}_"
                f"H{params['max_hold_days']}_TOP{params['top_n']}_SL{params.get('stop_loss',3.0)}_TP{params.get('take_profit',5.0)}")


def run_single_combo(args):
    direction, params = args
    try:
        if direction == "D9":
            res = run_backtest_d9(sym_data_global, sym_scores_pit_global, params)
        elif direction == "D10":
            res = run_backtest_d10(sym_data_global, sym_scores_pit_global, params)
        elif direction == "D11":
            res = run_backtest_d11(sym_data_global, sym_scores_pit_global, params)
        elif direction == "D12":
            res = run_backtest_d12(sym_data_global, sym_scores_pit_global, params)
        elif direction == "D13":
            res = run_backtest_d13(sym_data_global, sym_scores_pit_global, params)
        else:
            return None

        is_passed, consistency = qualify(res)
        name = make_name(direction, params)

        t = res["train"]["metrics"]
        v = res["val"]["metrics"]
        te = res["test"]["metrics"]

        return {
            "direction": direction,
            "name": name,
            "params": params,
            "results": res,
            "passed": is_passed,
            "three_phase_consistency": consistency,
            "train": {"wr": t["positive_rate"], "trades": t["total_trades"], "sharpe": t["sharpe"], "mdd": t["max_drawdown"], "plr": t["profit_loss_ratio"]},
            "val": {"wr": v["positive_rate"], "trades": v["total_trades"], "sharpe": v["sharpe"], "mdd": v["max_drawdown"], "plr": v["profit_loss_ratio"]},
            "test": {"wr": te["positive_rate"], "trades": te["total_trades"], "sharpe": te["sharpe"], "mdd": te["max_drawdown"], "plr": te["profit_loss_ratio"]},
        }
    except Exception as e:
        return {"direction": direction, "params": params, "error": str(e)}


# 全局数据（用于多进程）
sym_data_global = None
sym_scores_pit_global = None


def build_combos():
    all_combos = []

    # === D9: 纯 RSI 超卖 ===
    for rsi_thresh, bb_mult, hold_days, top_n in product(
        [18, 20, 25],
        [1.00, 1.01],
        [5, 7, 10],
        [300, 500, 800],
    ):
        all_combos.append(("D9", {
            "rsi_thresh": rsi_thresh,
            "bb_mult": bb_mult,
            "max_hold_days": hold_days,
            "top_n": top_n,
            "stop_loss": 3.0,
            "take_profit": 5.0,
        }))

    # === D10: 趋势回归（MA5>MA10>MA20 + RSI回调）===
    for rsi_thresh, hold_days, top_n in product(
        [20, 22, 25],
        [5, 7],
        [300, 500],
    ):
        all_combos.append(("D10", {
            "rsi_thresh": rsi_thresh,
            "max_hold_days": hold_days,
            "top_n": top_n,
            "stop_loss": 3.0,
            "take_profit": 5.0,
        }))

    # === D11: 极度超卖 ===
    for rsi_thresh, down_days, hold_days, top_n in product(
        [15, 18],
        [3, 5, 7],
        [7, 10],
        [300, 500],
    ):
        all_combos.append(("D11", {
            "rsi_thresh": rsi_thresh,
            "down_days": down_days,
            "max_hold_days": hold_days,
            "top_n": top_n,
            "stop_loss": 3.0,
            "take_profit": 5.0,
        }))

    # === D12: 缩量底部 ===
    for rsi_thresh, vol_mult, bb_mult, hold_days, top_n in product(
        [18, 20],
        [0.25, 0.30, 0.35],
        [1.00, 1.01],
        [7, 10],
        [300, 500],
    ):
        all_combos.append(("D12", {
            "rsi_thresh": rsi_thresh,
            "vol_mult": vol_mult,
            "bb_mult": bb_mult,
            "max_hold_days": hold_days,
            "top_n": top_n,
            "stop_loss": 3.0,
            "take_profit": 5.0,
        }))

    # === D13: 布林带下轨反弹 ===
    for rsi_thresh, bb_mult, hold_days, top_n in product(
        [20, 22, 25],
        [1.00, 1.01],
        [5, 7, 10],
        [300, 500],
    ):
        all_combos.append(("D13", {
            "rsi_thresh": rsi_thresh,
            "bb_mult": bb_mult,
            "max_hold_days": hold_days,
            "top_n": top_n,
            "stop_loss": 3.0,
            "take_profit": 5.0,
        }))

    return all_combos


def main():
    global sym_data_global, sym_scores_pit_global

    t0 = time.time()
    log(f"连接数据库...")
    conn = sqlite3.connect(DB, timeout=120)
    sym_data_global, sym_scores_pit_global = load_data(conn)
    conn.close()

    combos = build_combos()
    total = len(combos)
    log(f"D9-D13 不依赖弱市策略探索：共 {total} 个组合 | workers={WORKERS}")

    passed_all = []
    best_per_dir = {}

    if WORKERS > 1:
        with mp.Pool(WORKERS) as pool:
            results_iter = pool.imap_unordered(run_single_combo, combos, chunksize=8)
            for idx, result in enumerate(results_iter, 1):
                if result is None:
                    continue
                d = result.get("direction", "?")
                if "error" in result:
                    log(f"  ERROR {d}: {result['error']}")
                    continue

                passed_str = "✅" if result["passed"] else "❌"
                te = result["test"]
                tr = result["train"]
                log(f"[{idx}/{total}] {result['name']} | {passed_str} "
                    f"train {tr['trades']}/{tr['wr']:.1f}% | "
                    f"test {te['trades']}/{te['wr']:.1f}% | "
                    f"Sharpe {te['sharpe']:.2f} | PLR {te['plr']:.2f}")

                if result["passed"]:
                    passed_all.append(result)

                # 记录最佳（按 test sharpe 排序）
                if d not in best_per_dir or te["sharpe"] > best_per_dir[d]["test"]["sharpe"]:
                    best_per_dir[d] = result
    else:
        for idx, combo in enumerate(combos, 1):
            result = run_single_combo(combo)
            if result is None:
                continue
            d = result.get("direction", "?")
            if "error" in result:
                log(f"  ERROR {d}: {result['error']}")
                continue

            passed_str = "✅" if result["passed"] else "❌"
            te = result["test"]
            tr = result["train"]
            log(f"[{idx}/{total}] {result['name']} | {passed_str} "
                f"train {tr['trades']}/{tr['wr']:.1f}% | "
                f"test {te['trades']}/{te['wr']:.1f}% | "
                f"Sharpe {te['sharpe']:.2f} | PLR {te['plr']:.2f}")

            if result["passed"]:
                passed_all.append(result)
            if d not in best_per_dir or te["sharpe"] > best_per_dir[d]["test"]["sharpe"]:
                best_per_dir[d] = result

    # 汇总
    log(f"\n{'='*70}")
    log(f"汇总：D9-D13 不依赖弱市策略")
    log(f"{'='*70}")

    directions = ["D9", "D10", "D11", "D12", "D13"]
    final_output = {"directions": {}}

    for d in directions:
        if d in best_per_dir:
            r = best_per_dir[d]
            final_output["directions"][d] = {
                "passed": r["passed"],
                "best_combo": {
                    "name": r["name"],
                    "params": r["params"],
                    "train": r["train"],
                    "val": r["val"],
                    "test": r["test"],
                },
                "all_results": [x for x in passed_all if x["direction"] == d]
            }
            te = r["test"]
            tr = r["train"]
            vl = r["val"]
            flag = "✅" if r["passed"] else "❌"
            log(f"  {d} {flag}")
            log(f"     最佳: {r['name']}")
            log(f"     train: {tr['trades']}笔 / {tr['wr']:.1f}% / Sharpe {tr['sharpe']:.2f} / PLR {tr['plr']:.2f}")
            log(f"     val:   {vl['trades']}笔 / {vl['wr']:.1f}% / Sharpe {vl['sharpe']:.2f} / PLR {vl['plr']:.2f}")
            log(f"     test:  {te['trades']}笔 / {te['wr']:.1f}% / Sharpe {te['sharpe']:.2f} / PLR {te['plr']:.2f}")
        else:
            final_output["directions"][d] = {
                "passed": False,
                "best_combo": None,
                "all_results": [],
            }
            log(f"  {d}: 无有效结果")

    log(f"\n合格策略总数: {len(passed_all)}")
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    log(f"结果已保存: {OUTPUT}")
    log(f"总耗时: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)
    main()
