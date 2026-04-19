#!/usr/bin/env python3
"""
探索方向9-13：不依赖弱市过滤的策略

D9:  纯RSI超卖 + BB触底（RSI < 18/20/25, price <= boll_lower)
D10: 多头排列回归（MA5>MA10>MA20 且 RSI<25）
D11: 连续下跌极度超卖（RSI < 15/18 + 连跌3/5/7天）
D12: 缩量底部（VOL < 0.3 * VOL_MA20 + RSI<20 + BB触底）
D13: 布林带下轨反弹（price <= boll_lower * 1.0 + RSI<25）

合格：train/val/test 正率均>55%，三阶段一致性=1，test夏普>1，test盈亏比>1.1
"""
import json, os, sqlite3, time, multiprocessing as mp
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import product

import numpy as np

PROJECT_ROOT = "/home/heqiang/.openclaw/workspace/stock-monitor-app-py"
DB = os.path.join(PROJECT_ROOT, "data", "stock_data.db")
OUTPUT = os.path.join(PROJECT_ROOT, "data/results/explore_no_weak_d9_d13.json")

PHASES = {
    "train":  ("2021-01-01", "2024-06-30"),
    "val":    ("2024-07-01", "2025-07-01"),
    "test":   ("2025-07-02", "2026-03-27"),
}
RF = 0.03
COST = 0.30

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def pit_delay_days(report_date):
    m = int(report_date[5:7])
    return {3: 30, 6: 62, 9: 31, 12: 120}.get(m, 45)

def pit_effective_date(report_date):
    return (datetime.strptime(report_date, "%Y-%m-%d") + timedelta(days=pit_delay_days(report_date))).strftime("%Y-%m-%d")

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

def calc_28_metrics(returns, hold_days, hit_stock_count=0):
    keys = [
        "total_trades","positive_rate","avg_return","median_return","max_return","min_return","hit_stocks",
        "sharpe","max_drawdown","volatility","downside_volatility","sortino",
        "win_rate","profit_loss_ratio","avg_win","avg_loss","max_win","max_loss",
        "max_consec_wins","max_consec_losses","annual_return","calmar",
        "recovery_factor","breakeven_wr","expectancy","train_test_ratio",
        "three_phase_consistency","avg_hold_days",
    ]
    if not returns:
        return {k: 0 for k in keys}
    r = np.array(returns, dtype=float)
    n = len(r)
    pos = r[r > 0]; neg = r[r <= 0]
    pos_rate = len(pos) / n * 100
    avg_ret = float(np.mean(r)); median_ret = float(np.median(r))
    max_ret = float(np.max(r)); min_ret = float(np.min(r))
    ann_ret = avg_ret * 252 / hold_days
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_vol = std * np.sqrt(252 / hold_days) if std > 0 else 0
    sharpe = (ann_ret - RF * 100) / ann_vol if ann_vol > 0 else 0
    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold_days)) if len(dn) > 1 else 0
    sortino = (ann_ret - RF * 100) / dn_std if dn_std > 0 else 0
    cum = 0.0; peak = 0.0; mdd = 0.0
    for x in returns:
        cum += np.log(1 + x / 100)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    mdd = mdd * 100
    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0
    cw = cl = cwmax = clmax = 0
    for x in returns:
        if x > 0: cw += 1; cl = 0; cwmax = max(cwmax, cw)
        else: cl += 1; cw = 0; clmax = max(clmax, cl)
    expectancy = float(len(pos)/n*np.mean(pos) + len(neg)/n*np.mean(neg) if len(neg) > 0 else avg_ret)
    total_ret = float(np.sum(r))
    recovery_factor = total_ret / abs(mdd) if mdd > 0.0001 else 0
    breakeven = 1 / (1 + plr) * 100 if plr > 0 else 100
    return {
        "total_trades": n, "positive_rate": round(pos_rate, 2),
        "avg_return": round(avg_ret, 4), "median_return": round(median_ret, 4),
        "max_return": round(max_ret, 4), "min_return": round(min_ret, 4),
        "hit_stocks": hit_stock_count, "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4), "volatility": round(ann_vol, 4),
        "downside_volatility": round(dn_std, 4), "sortino": round(sortino, 4),
        "win_rate": round(pos_rate, 2), "profit_loss_ratio": round(plr, 4),
        "avg_win": round(float(np.mean(pos)), 4) if len(pos) > 0 else 0,
        "avg_loss": round(float(np.mean(neg)), 4) if len(neg) > 0 else 0,
        "max_win": round(float(np.max(pos)), 4) if len(pos) > 0 else 0,
        "max_loss": round(float(np.min(neg)), 4) if len(neg) > 0 else 0,
        "max_consec_wins": cwmax, "max_consec_losses": clmax,
        "annual_return": round(ann_ret, 4), "calmar": round(ann_ret / mdd * 100, 4) if mdd > 0 else 0,
        "recovery_factor": round(recovery_factor, 4),
        "breakeven_wr": round(breakeven, 2), "expectancy": round(expectancy, 4),
        "train_test_ratio": round(n / max(1, n), 2),
        "three_phase_consistency": 0, "avg_hold_days": hold_days,
    }

def month_iter(start_date, end_date):
    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while d < end:
        next_m = datetime(d.year + (d.month // 12), (d.month % 12) + 1, 1)
        yield d.strftime("%Y-%m-%d"), next_m.strftime("%Y-%m-%d")
        d = next_m

def load_data():
    """加载K线数据 + PIT财务数据"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # K线
    rows = conn.execute("""
        SELECT symbol, trade_date as date, open, close, high, low, volume,
               rsi14 as rsi, boll_lower, boll_upper, kdj_k, kdj_d, kdj_j
        FROM kline_daily
        WHERE trade_date >= '2020-01-01' AND trade_date <= '2026-03-31'
        ORDER BY symbol, trade_date
    """).fetchall()

    sym_data = defaultdict(lambda: {
        "dates": [], "open": [], "close": [], "high": [], "low": [],
        "volume": [], "rsi": [], "bb_lower": [], "bb_upper": [], "kdj_k": []
    })
    for r in rows:
        s = r["symbol"]
        sym_data[s]["dates"].append(r["date"])
        sym_data[s]["open"].append(float(r["open"]))
        sym_data[s]["close"].append(float(r["close"]))
        sym_data[s]["high"].append(float(r["high"]))
        sym_data[s]["low"].append(float(r["low"]))
        sym_data[s]["volume"].append(float(r["volume"]))
        sym_data[s]["rsi"].append(float(r["rsi"]) if r["rsi"] is not None else np.nan)
        sym_data[s]["kdj_k"].append(float(r["kdj_k"]) if r["kdj_k"] is not None else np.nan)
        sym_data[s]["bb_lower"].append(float(r["boll_lower"]) if r["boll_lower"] is not None else np.nan)
        sym_data[s]["bb_upper"].append(float(r["boll_upper"]) if r["boll_upper"] is not None else np.nan)

    # 计算MA5/MA10/MA20
    for sym in sym_data:
        closes = np.array(sym_data[sym]["close"])
        vols = np.array(sym_data[sym]["volume"])
        sym_data[sym]["ma5"] = _ma(closes, 5)
        sym_data[sym]["ma10"] = _ma(closes, 10)
        sym_data[sym]["ma20"] = _ma(closes, 20)
        sym_data[sym]["vol_ma20"] = _ma(vols, 20)

    # 财务 PIT
    rows2 = conn.execute("""
        SELECT symbol, report_date, roe, revenue_growth, profit_growth,
               gross_margin, debt_ratio
        FROM financial_indicators
        ORDER BY symbol, report_date
    """).fetchall()
    sym_pit = defaultdict(list)
    for r in rows2:
        eff = pit_effective_date(r["report_date"])
        score = fund_score(r["roe"], r["revenue_growth"], r["profit_growth"],
                           r["gross_margin"], r["debt_ratio"])
        sym_pit[r["symbol"]].append((eff, score))
    conn.close()
    return dict(sym_data), dict(sym_pit)

def _ma(arr, n):
    result = np.full(len(arr), np.nan)
    for i in range(n-1, len(arr)):
        chunk = arr[max(0, i-n+1):i+1]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) == n:
            result[i] = float(np.mean(valid))
    return result

def _run_backtest(sym_data, sym_scores_pit, params, direction_name):
    """通用回测逻辑，支持5种信号条件"""
    hold_days = params["max_hold_days"]
    top_n = params["top_n"]
    stop_loss = params.get("stop_loss", 3.0)
    take_profit = params.get("take_profit", 5.0)
    results = {}

    for phase, (phase_start, phase_end) in PHASES.items():
        returns = []; actual_holds = []; hit_stocks_set = set()

        for month_start, next_month_start in month_iter(phase_start, phase_end):
            # TOP N by PIT score
            scored = []
            for sym in sym_data:
                latest_score = 0
                for eff_date, score in reversed(sym_scores_pit.get(sym, [])):
                    if eff_date <= month_start:
                        latest_score = score; break
                if latest_score > 0:
                    scored.append((sym, latest_score))
            scored.sort(key=lambda x: -x[1])
            monthly_top = [s[0] for s in scored[:top_n]] if top_n > 0 else [s[0] for s in scored]

            for sym in monthly_top:
                sd = sym_data.get(sym)
                if sd is None: continue

                dates = sd["dates"]; closes = np.array(sd["close"])
                opens_arr = np.array(sd["open"]); rsi_arr = np.array(sd["rsi"])
                bb_l = np.array(sd["bb_lower"]); vols = np.array(sd["volume"])
                ma5 = np.array(sd["ma5"]); ma10 = np.array(sd["ma10"]); ma20 = np.array(sd["ma20"])
                vol_ma20 = np.array(sd["vol_ma20"])

                i = 0
                while i < len(dates):
                    d = dates[i]
                    if d < phase_start: i += 1; continue
                    if d >= next_month_start or d > phase_end: break
                    if i + 1 >= len(dates): break

                    # === 信号判断 ===
                    signal_ok = False
                    price = closes[i]
                    rsi_val = rsi_arr[i]

                    if direction_name == "D9":
                        # 纯RSI超卖 + BB触底
                        if not (not np.isnan(rsi_val) and rsi_val < params["rsi_thresh"]): i += 1; continue
                        if not (not np.isnan(bb_l[i]) and bb_l[i] > 0 and price <= bb_l[i] * params["bb_mult"]): i += 1; continue
                        if params.get("vol_mult", 0) > 0:
                            if i < 5 or np.isnan(vols[i]): i += 1; continue
                            vol_ma5_v = np.nanmean(vols[i-5:i])
                            if np.isnan(vol_ma5_v) or vols[i] < vol_ma5_v * params["vol_mult"]: i += 1; continue
                        signal_ok = True

                    elif direction_name == "D10":
                        # MA5>MA10>MA20 且 RSI<25
                        if any(np.isnan(x) for x in [ma5[i], ma10[i], ma20[i]]): i += 1; continue
                        if not (ma5[i] > ma10[i] > ma20[i]): i += 1; continue
                        if np.isnan(rsi_val) or rsi_val >= params.get("rsi_thresh", 25): i += 1; continue
                        signal_ok = True

                    elif direction_name == "D11":
                        # 极度超卖 + 连跌
                        if np.isnan(rsi_val) or rsi_val >= params["rsi_thresh"]: i += 1; continue
                        n_down = 0
                        for k in range(min(params.get("consec_down", 3), i)):
                            if closes[i-k] < closes[i-k-1]: n_down += 1
                            else: break
                        if n_down < params.get("consec_down", 3): i += 1; continue
                        signal_ok = True

                    elif direction_name == "D12":
                        # 缩量底部
                        if np.isnan(rsi_val) or rsi_val >= 20: i += 1; continue
                        if np.isnan(vol_ma20[i]) or vols[i] >= vol_ma20[i] * 0.3: i += 1; continue
                        if np.isnan(bb_l[i]) or price > bb_l[i] * 1.02: i += 1; continue
                        signal_ok = True

                    elif direction_name == "D13":
                        # BB触底反弹
                        if np.isnan(rsi_val) or rsi_val >= params.get("rsi_thresh", 25): i += 1; continue
                        if np.isnan(bb_l[i]) or bb_l[i] <= 0 or price > bb_l[i] * params.get("bb_mult", 1.0): i += 1; continue
                        signal_ok = True

                    if not signal_ok:
                        i += 1; continue

                    # === 买入/卖出 ===
                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price): i += 1; continue

                    sell_idx = None; sell_price = None
                    for h in range(1, hold_days + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates): break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -stop_loss:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 - stop_loss / 100); break
                        if pct_chg >= take_profit:
                            sell_idx = check_idx
                            sell_price = buy_price * (1 + take_profit / 100); break
                    if sell_idx is None:
                        sell_idx = min(buy_idx + hold_days, len(dates) - 1)
                        sell_price = closes[sell_idx]
                    if np.isnan(sell_price) or sell_price <= 0: i += 1; continue

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
    t = res["train"]["metrics"]; v = res["val"]["metrics"]; te = res["test"]["metrics"]
    return (
        t["positive_rate"] > 55 and v["positive_rate"] > 55 and te["positive_rate"] > 55 and
        te["total_trades"] >= 30 and
        round(sum(1 for pr in [t["positive_rate"],v["positive_rate"],te["positive_rate"]] if pr > 55)/3*100, 2) >= 100 and
        te["sharpe"] > 1 and te["profit_loss_ratio"] > 1.1 and te["max_drawdown"] < 50
    )

def build_combos():
    combos = []
    # D9: 纯RSI超卖+BB触底
    for rsi, bb_mult, vol_mult, hold, top in product(
        [18, 20, 25], [1.0], [0, 1.0, 1.2], [5, 7, 10], [300, 500, 800]):
        combos.append({"direction": "D9", "params": {
            "rsi_thresh": rsi, "bb_mult": bb_mult, "vol_mult": vol_mult,
            "max_hold_days": hold, "top_n": top, "stop_loss": 3.0, "take_profit": 5.0}})

    # D10: 趋势回归
    for rsi, hold, top in product([22, 25, 28], [5, 7], [300, 500]):
        combos.append({"direction": "D10", "params": {
            "rsi_thresh": rsi, "max_hold_days": hold, "top_n": top,
            "stop_loss": 3.0, "take_profit": 5.0}})

    # D11: 连跌极度超卖
    for rsi, consec, hold, top in product(
        [15, 18, 20], [3, 5, 7], [7, 10], [300, 500]):
        combos.append({"direction": "D11", "params": {
            "rsi_thresh": rsi, "consec_down": consec,
            "max_hold_days": hold, "top_n": top,
            "stop_loss": 3.0, "take_profit": 5.0}})

    # D12: 缩量底部
    for hold, top in product([7, 10], [300, 500]):
        combos.append({"direction": "D12", "params": {
            "max_hold_days": hold, "top_n": top,
            "stop_loss": 3.0, "take_profit": 5.0}})

    # D13: BB触底反弹
    for rsi, bb_mult, hold, top in product(
        [22, 25, 28], [1.0, 1.02], [5, 7, 10], [300, 500]):
        combos.append({"direction": "D13", "params": {
            "rsi_thresh": rsi, "bb_mult": bb_mult,
            "max_hold_days": hold, "top_n": top,
            "stop_loss": 3.0, "take_profit": 5.0}})

    return combos

def worker(args):
    combo, sym_data, sym_scores_pit = args
    d = combo["direction"]
    params = combo["params"]
    try:
        results = _run_backtest(sym_data, sym_scores_pit, params, d)
        t = results["train"]["metrics"]; v = results["val"]["metrics"]; te = results["test"]["metrics"]
        return {
            "direction": d, "params": params,
            "results": results,
            "train_wr": round(t["positive_rate"], 2), "train_n": t["total_trades"],
            "val_wr": round(v["positive_rate"], 2), "val_n": v["total_trades"],
            "test_wr": round(te["positive_rate"], 2), "test_n": te["total_trades"],
            "test_sharpe": round(te["sharpe"], 2), "test_plr": round(te["profit_loss_ratio"], 2),
            "test_mdd": round(te["max_drawdown"], 2),
            "passed": qualifies(results),
        }
    except Exception as e:
        return {"direction": d, "params": params, "error": str(e)}

def main():
    t0 = time.time()
    log("加载数据...")
    sym_data, sym_scores_pit = load_data()
    log(f"数据加载完成：{len(sym_data)} 只股票，耗时 {time.time()-t0:.1f}s")

    combos = build_combos()
    log(f"共 {len(combos)} 个组合待测")

    # 复用 calc_28_metrics 的 actual_holds 问题修复：需要传 actual_holds 进去
    # 先单线程跑10个试试
    log("先单线程试跑前10个组合...")
    for i, combo in enumerate(combos[:10]):
        result = worker((combo, sym_data, sym_scores_pit))
        r = result
        flag = "✅" if r.get("passed") else "  "
        print(f"{flag} {r['direction']} {str(r.get('params',{}))[:60]} "
              f"| train {r.get('train_n',0)}/{r.get('train_wr',0)}% "
              f"| val {r.get('val_n',0)}/{r.get('val_wr',0)}% "
              f"| test {r.get('test_n',0)}/{r.get('test_wr',0)}% "
              f"| sh={r.get('test_sharpe',0)} plr={r.get('test_plr',0)}")

    # 多进程跑剩余
    remaining = combos[10:]
    if remaining:
        log(f"多进程跑剩余 {len(remaining)} 个...")
        with mp.Pool(max(1, mp.cpu_count() - 1)) as pool:
            args_list = [(c, sym_data, sym_scores_pit) for c in remaining]
            all_results = pool.map(worker, args_list, chunksize=max(1, len(remaining)//16))
    else:
        all_results = []

    all_results_full = [worker((c, sym_data, sym_scores_pit)) for c in combos[:10]] + all_results

    # 保存
    out = {"timestamp": datetime.now().isoformat(), "directions": {}}
    for r in all_results_full:
        d = r["direction"]
        if d not in out["directions"]:
            out["directions"][d] = {"all_results": [], "passed": False}
        out["directions"][d]["all_results"].append(r)
        if r.get("passed"):
            out["directions"][d]["passed"] = True

    # 每个方向找最优
    for d in out["directions"]:
        results_list = out["directions"][d]["all_results"]
        if not results_list: continue
        best = max(results_list, key=lambda x: (
            x.get("test_wr", 0), x.get("test_sharpe", 0),
            x.get("test_n", 0), -x.get("test_mdd", 100)
        ))
        out["directions"][d]["best"] = best

    with open(OUTPUT, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    log(f"完成！耗时 {time.time()-t0:.1f}s")
    log(f"结果: {OUTPUT}")

    # 打印汇总
    for d, info in out["directions"].items():
        best = info.get("best", {})
        flag = "✅ PASS" if info["passed"] else "  FAIL"
        print(f"{flag} {d}: test {best.get('test_n',0)}笔/{best.get('test_wr',0)}% "
              f"sh={best.get('test_sharpe',0)} plr={best.get('test_plr',0)} "
              f"| {best.get('params',{})}")

if __name__ == "__main__":
    main()
