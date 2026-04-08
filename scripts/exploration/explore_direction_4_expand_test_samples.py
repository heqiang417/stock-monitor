#!/usr/bin/env python3
"""
探索方向4：提升测试样本数的 Fstop3 扩容搜索
目标：围绕 Fstop3_pt5（固定止盈止损）做“放宽入场密度”搜索，优先找到 test>=30 且三阶段胜率>55 的候选。

核心思想：
1. 不再继续叠加更严格过滤（已证明显著压缩 test trades）
2. 从 Fstop3 的弱市+超卖反转框架出发，放宽以下参数：
   - RSI 阈值：18 -> 19/20
   - BB 容忍：1.00 -> 1.01/1.02
   - 成交量：1.5x -> 1.2x/1.3x/0(不要求)
   - TOP N：300 -> 500/800/0(全市场)
   - 弱市阈值：0.5 -> 0.4/0.3/关闭
   - 持有/止盈止损：保留 Fstop3 风格，但允许微调
"""
import json
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import product

import numpy as np

PROJECT_ROOT = "/home/heqiang/.openclaw/workspace/stock-monitor-app-py"
DB = os.path.join(PROJECT_ROOT, "data/stock_data.db")
OUTPUT = os.path.join(PROJECT_ROOT, "data/results/explore_direction_4_expand_test_samples.json")

PHASES = {
    "train": ("2021-01-01", "2024-06-30"),
    "val": ("2024-07-01", "2025-07-01"),
    "test": ("2025-07-02", "2026-03-27"),
}
RF = 0.03
COST = 0.30

BASELINE = {
    "name": "Fstop3_pt5",
    "rsi_thresh": 18,
    "bb_mult": 1.00,
    "vol_mult": 1.5,
    "weak_thresh": 0.5,
    "use_weak": True,
    "top_n": 300,
    "stop_loss": 3.0,
    "take_profit": 5.0,
    "max_hold_days": 10,
}


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
        "win_rate", "profit_loss_ratio", "avg_win", "avg_loss", "max_win", "max_loss", "max_consec_wins", "max_consec_losses",
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
            cw += 1
            cl = 0
            cwmax = max(cwmax, cw)
        else:
            cl += 1
            cw = 0
            clmax = max(clmax, cl)

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

        ma20 = np.full(len(closes), np.nan)
        for i in range(19, len(closes)):
            ma20[i] = np.nanmean(closes[i - 19 : i + 1])

        sym_data[sym] = {
            "dates": dates,
            "open": opens,
            "close": closes,
            "volume": vols,
            "rsi": rsi,
            "bb_lower": bb_l,
            "ma20": ma20,
        }

    log(f"  {len(sym_data)} 股票已加载")

    all_dates = sorted(set(d for sd in sym_data.values() for d in sd["dates"]))
    weak_maps = {}
    for thresh in [0.3, 0.4, 0.5]:
        weak = {}
        for d in all_dates:
            total = below = 0
            for sd in sym_data.values():
                try:
                    idx = sd["dates"].index(d)
                except ValueError:
                    continue
                c = sd["close"][idx]
                m20 = sd["ma20"][idx]
                if np.isnan(c) or np.isnan(m20):
                    continue
                total += 1
                if c < m20:
                    below += 1
            weak[d] = (total >= 20 and below / total > thresh)
        weak_maps[thresh] = weak
        log(f"  弱市阈值 {thresh:.1f} 已计算")

    return sym_data, dict(sym_scores_pit), weak_maps


def month_iter(start_date: str, end_date: str):
    cur = datetime.strptime(start_date, "%Y-%m-%d").replace(day=1)
    phase_end = datetime.strptime(end_date, "%Y-%m-%d")
    while cur <= phase_end:
        next_month = (cur + timedelta(days=32)).replace(day=1)
        yield cur.strftime("%Y-%m-%d"), next_month.strftime("%Y-%m-%d")
        cur = next_month


def run_backtest(sym_data, sym_scores_pit, weak_maps, params):
    results = {}
    use_weak = params["use_weak"]
    weak_thresh = params.get("weak_thresh", 0.5)
    weak = weak_maps.get(weak_thresh, {}) if use_weak else {}
    hold_days = params["max_hold_days"]
    top_n = params["top_n"]

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

                    if use_weak and not weak.get(d, False):
                        i += 1
                        continue
                    if np.isnan(rsi[i]) or rsi[i] >= params["rsi_thresh"] or rsi[i] < 10:
                        i += 1
                        continue

                    price = closes[i]
                    if np.isnan(bb_l[i]) or bb_l[i] <= 0 or price > bb_l[i] * params["bb_mult"]:
                        i += 1
                        continue

                    if params["vol_mult"] > 0:
                        if i < 5 or np.isnan(vols[i]):
                            i += 1
                            continue
                        vol_ma5 = np.nanmean(vols[i - 5 : i])
                        if np.isnan(vol_ma5) or vol_ma5 <= 0 or vols[i] < vol_ma5 * params["vol_mult"]:
                            i += 1
                            continue

                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price):
                        i += 1
                        continue

                    sell_idx = None
                    sell_price = None
                    for h in range(1, hold_days + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates):
                            break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -params["stop_loss"]:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 - params["stop_loss"] / 100)
                            break
                        if pct_chg >= params["take_profit"]:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 + params["take_profit"] / 100)
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
    consistency = sum(1 for pr in pos_rates if pr > 55) / 3 * 100
    for phase in results:
        results[phase]["metrics"]["three_phase_consistency"] = round(consistency, 2)
    return results


def qualifies(res):
    t = res["train"]["metrics"]
    v = res["val"]["metrics"]
    te = res["test"]["metrics"]
    return (
        t["positive_rate"] > 55 and v["positive_rate"] > 55 and te["positive_rate"] > 55 and
        t["total_trades"] >= 30 and v["total_trades"] >= 30 and te["total_trades"] >= 30
    )


def main():
    t0 = time.time()
    log("连接数据库...")
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores_pit, weak_maps = load_data(conn)
    conn.close()

    combos = []

    # A. Fstop3 邻域精细搜索：先从最有希望的放宽组合开始
    for rsi_thresh, bb_mult, vol_mult, weak_thresh, top_n, hold_days, stop_loss, take_profit in product(
        [18, 19, 20],
        [1.00, 1.01, 1.02],
        [1.5, 1.3, 1.2],
        [0.5, 0.4, 0.3],
        [300, 500, 800],
        [7, 10],
        [3.0],
        [5.0],
    ):
        combos.append({
            "family": "fstop3_expand",
            "rsi_thresh": rsi_thresh,
            "bb_mult": bb_mult,
            "vol_mult": vol_mult,
            "weak_thresh": weak_thresh,
            "use_weak": True,
            "top_n": top_n,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "max_hold_days": hold_days,
        })

    # B. 去掉弱市 or 放宽成交量，专门补 test 样本
    for rsi_thresh, bb_mult, vol_mult, top_n, hold_days, stop_loss, take_profit in product(
        [18, 19, 20],
        [1.00, 1.01, 1.02],
        [1.5, 1.2, 0.0],
        [300, 500, 800, 0],
        [7, 10],
        [3.0],
        [5.0],
    ):
        combos.append({
            "family": "no_weak_expand",
            "rsi_thresh": rsi_thresh,
            "bb_mult": bb_mult,
            "vol_mult": vol_mult,
            "weak_thresh": 0.5,
            "use_weak": False,
            "top_n": top_n,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "max_hold_days": hold_days,
        })

    # C. 向旧搜索高样本候选靠拢：RSI20 + vol/BB，高样本验证，叠回固定止盈止损
    seed_variants = [
        {"family": "seed_high_density", "rsi_thresh": 20, "bb_mult": 1.02, "vol_mult": 1.5, "use_weak": False, "weak_thresh": 0.5, "top_n": 500, "stop_loss": 3.0, "take_profit": 5.0, "max_hold_days": 10},
        {"family": "seed_high_density", "rsi_thresh": 20, "bb_mult": 1.00, "vol_mult": 1.5, "use_weak": False, "weak_thresh": 0.5, "top_n": 500, "stop_loss": 3.0, "take_profit": 5.0, "max_hold_days": 10},
        {"family": "seed_high_density", "rsi_thresh": 20, "bb_mult": 1.02, "vol_mult": 0.0,  "use_weak": True,  "weak_thresh": 0.5, "top_n": 300, "stop_loss": 3.0, "take_profit": 5.0, "max_hold_days": 7},
        {"family": "seed_high_density", "rsi_thresh": 20, "bb_mult": 1.02, "vol_mult": 1.2, "use_weak": True,  "weak_thresh": 0.4, "top_n": 500, "stop_loss": 3.0, "take_profit": 5.0, "max_hold_days": 7},
    ]
    combos.extend(seed_variants)

    log(f"共 {len(combos)} 个组合待测")
    all_results = []
    qualified = []

    for idx, params in enumerate(combos, 1):
        label = (
            f"{params['family']}_RSI{params['rsi_thresh']}_BB{params['bb_mult']:.2f}"
            f"_VOL{params['vol_mult']}_TOP{params['top_n'] if params['top_n']>0 else 'ALL'}"
            f"_{'weak'+str(params['weak_thresh']) if params['use_weak'] else 'noWeak'}"
            f"_SL{params['stop_loss']}_TP{params['take_profit']}_H{params['max_hold_days']}"
        )
        log(f"[{idx}/{len(combos)}] {label}")
        try:
            res = run_backtest(sym_data, sym_scores_pit, weak_maps, params)
        except Exception as e:
            log(f"  ERROR: {e}")
            continue

        row = {"name": label, "params": params, "results": res, "qualified": qualifies(res)}
        all_results.append(row)
        if row["qualified"]:
            qualified.append(row)

        te = res["test"]["metrics"]
        log(f"  test: {te['total_trades']}笔 / WR {te['positive_rate']:.2f}% / Sharpe {te['sharpe']:.2f} / Avg {te['avg_return']:.2f}%")

    def score(x):
        r = x["results"]
        t, v, te = r["train"]["metrics"], r["val"]["metrics"], r["test"]["metrics"]
        return (
            1 if x["qualified"] else 0,
            te["total_trades"],
            min(t["positive_rate"], v["positive_rate"], te["positive_rate"]),
            te["sharpe"],
        )

    all_results.sort(key=score, reverse=True)
    qualified.sort(key=score, reverse=True)

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "goal": "expand test sample count while preserving >55% win rate across train/val/test",
        "baseline": BASELINE,
        "qualified_count": len(qualified),
        "top10": all_results[:10],
        "qualified": qualified[:30],
        "all_results_count": len(all_results),
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log(f"结果已保存: {OUTPUT}")
    log(f"qualified: {len(qualified)}")
    for row in qualified[:10]:
        t = row["results"]["train"]["metrics"]
        v = row["results"]["val"]["metrics"]
        te = row["results"]["test"]["metrics"]
        log(f"✅ {row['name']}")
        log(f"   train {t['total_trades']} / {t['positive_rate']:.2f}% | val {v['total_trades']} / {v['positive_rate']:.2f}% | test {te['total_trades']} / {te['positive_rate']:.2f}% | test Sharpe {te['sharpe']:.2f}")

    log(f"总耗时: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
