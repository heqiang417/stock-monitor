#!/usr/bin/env python3
"""
Fstop3_pt5 v10 统一回测流水线（单次运行产出三件套）
1) backtest/trades_v10_Fstop3_pt5.json
2) data/results/fstop3_v10_framework_eval.json
3) docs/strategy/Fstop3_pt5_v10/backtest_report.md
"""
import json
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = PROJECT_ROOT / "data/stock_data.db"
OUTPUT_DIR = PROJECT_ROOT / "data/results"
TRADES_PATH = PROJECT_ROOT / "backtest/trades_v10_Fstop3_pt5.json"
EVAL_PATH = OUTPUT_DIR / "fstop3_v10_framework_eval.json"
REPORT_PATH = PROJECT_ROOT / "docs/strategy/Fstop3_pt5_v10/backtest_report.md"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

PHASES = {
    "train": ("2021-01-01", "2024-06-30"),
    "val": ("2024-07-01", "2025-07-01"),
    "test": ("2025-07-02", "2026-03-27"),
}

RF = 0.03
COST = 0.30
STOP_LOSS = 3.0
TAKE_PROFIT = 5.0
HOLD_DAYS = 10
TOP_N = 300


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def pit_delay_days(report_date: str) -> int:
    m = int(report_date[5:7])
    return {3: 30, 6: 62, 9: 31, 12: 120}.get(m, 45)


def pit_effective_date(report_date: str) -> str:
    return (datetime.strptime(report_date, "%Y-%m-%d") + timedelta(days=pit_delay_days(report_date))).strftime("%Y-%m-%d")


def fund_score(roe, rev_g, profit_g, gross_margin, debt_ratio) -> float:
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
    t0 = time.time()
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

        # 以收盘价滚动20天计算MA20（避免依赖外部已算字段）
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

    log(f"  {len(sym_data)} 股票已加载 ({time.time() - t0:.1f}s)")

    log("计算弱市标记（>50%个股<MA20）...")
    all_dates = sorted(set(d for sd in sym_data.values() for d in sd["dates"]))
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
        weak[d] = (total >= 20 and below / total > 0.5)

    log(f"  弱市标记完成 ({time.time() - t0:.1f}s)")
    return sym_data, dict(sym_scores_pit), weak


def month_iter(start_date: str, end_date: str):
    cur = datetime.strptime(start_date, "%Y-%m-%d").replace(day=1)
    phase_end = datetime.strptime(end_date, "%Y-%m-%d")
    while cur <= phase_end:
        next_month = (cur + timedelta(days=32)).replace(day=1)
        yield cur.strftime("%Y-%m-%d"), next_month.strftime("%Y-%m-%d")
        cur = next_month


def run_backtest(sym_data, sym_scores_pit, weak):
    results = {}
    trades_output = {"train": [], "val": [], "test": []}

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
            monthly_top = [s[0] for s in scored[:TOP_N]]

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
                    if i + 1 + HOLD_DAYS >= len(dates):
                        break

                    if not weak.get(d, False):
                        i += 1
                        continue
                    if np.isnan(rsi[i]) or rsi[i] >= 18:
                        i += 1
                        continue

                    price = closes[i]
                    if np.isnan(bb_l[i]) or bb_l[i] <= 0 or price > bb_l[i]:
                        i += 1
                        continue

                    if i < 5 or np.isnan(vols[i]):
                        i += 1
                        continue
                    vol_ma5 = np.nanmean(vols[i - 5 : i])
                    if np.isnan(vol_ma5) or vol_ma5 <= 0 or vols[i] < vol_ma5 * 1.5:
                        i += 1
                        continue

                    buy_idx = i + 1
                    buy_price = opens_arr[buy_idx]
                    if buy_price <= 0 or np.isnan(buy_price):
                        i += 1
                        continue

                    sell_idx = None
                    for h in range(1, HOLD_DAYS + 1):
                        check_idx = buy_idx + h
                        if check_idx >= len(dates):
                            break
                        check_price = closes[check_idx]
                        pct_chg = (check_price - buy_price) / buy_price * 100
                        if pct_chg <= -STOP_LOSS or pct_chg >= TAKE_PROFIT:
                            sell_idx = check_idx
                            break

                    if sell_idx is None:
                        sell_idx = buy_idx + HOLD_DAYS
                        if sell_idx >= len(dates):
                            i += 1
                            continue

                    sell_price = closes[sell_idx]
                    if np.isnan(sell_price) or sell_price <= 0:
                        i += 1
                        continue

                    ret = (sell_price - buy_price) / buy_price * 100 - COST
                    returns.append(ret)
                    actual_holds.append(sell_idx - buy_idx)
                    hit_stocks_set.add(sym)
                    trades_output[phase].append(
                        {
                            "symbol": sym,
                            "buy_date": dates[buy_idx],
                            "sell_date": dates[sell_idx],
                            "return_pct": round(float(ret), 4),
                        }
                    )
                    i += HOLD_DAYS + 1

        metrics = calc_28_metrics(returns, HOLD_DAYS, len(hit_stocks_set))
        if actual_holds:
            metrics["avg_hold_days"] = round(sum(actual_holds) / len(actual_holds), 2)

        results[phase] = {
            "metrics": metrics,
            "trades": len(returns),
            "hit_stocks": len(hit_stocks_set),
        }

    # 跨阶段一致性：正率>=55 的阶段占比
    phase_order = ["train", "val", "test"]
    pos_rates = [results[p]["metrics"].get("positive_rate", 0) for p in phase_order]
    consistency = round(sum(1 for x in pos_rates if x >= 55) / len(phase_order) * 100, 2)

    test_avg = results["test"]["metrics"].get("avg_return", 0)
    train_avg = results["train"]["metrics"].get("avg_return", 0)
    train_test_ratio = round(train_avg / test_avg, 4) if test_avg else 0

    for p in phase_order:
        results[p]["metrics"]["three_phase_consistency"] = consistency
        results[p]["metrics"]["train_test_ratio"] = train_test_ratio

    return results, trades_output


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_report(eval_path: Path, report_path: Path):
    try:
        from generate_fstop3_report import generate_report_from_eval
    except Exception:
        generate_report_from_eval = None

    if generate_report_from_eval:
        generate_report_from_eval(str(eval_path), str(report_path))
        return

    # 兜底：最简报告
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    rs = payload.get("results", {})
    lines = [
        "# Fstop3_pt5 v10 回测报告",
        "",
        f"> 自动生成：{payload.get('generated_at', '')}",
        f"> 数据源：`{eval_path}`",
        "",
        "| 阶段 | 笔数 | 正率 | 夏普 |",
        "|---|---:|---:|---:|",
    ]
    for p in ["train", "val", "test"]:
        m = rs.get(p, {}).get("metrics", {})
        lines.append(f"| {p} | {m.get('total_trades',0)} | {m.get('positive_rate',0)}% | {m.get('sharpe',0)} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    t0 = time.time()
    log("=" * 70)
    log("Fstop3_pt5 v10 统一流水线：trades + eval + report")
    log("=" * 70)
    log(f"阶段: train={PHASES['train']} val={PHASES['val']} test={PHASES['test']}")
    log("参数: RSI<18 + BB触底 + 放量1.5x + 弱市50% + TOP300")
    log(f"卖出: stop_profit (止损{STOP_LOSS}% 止盈{TAKE_PROFIT}% 最长{HOLD_DAYS}天)")

    conn = sqlite3.connect(str(DB), timeout=120)
    sym_data, sym_scores_pit, weak = load_data(conn)
    conn.close()

    results, trades_output = run_backtest(sym_data, sym_scores_pit, weak)

    trades_payload = {
        "strategy": "Fstop3_pt5_v10",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "params": {
            "rsi": 18,
            "bb": "exact",
            "vol": 1.5,
            "weak": 0.5,
            "top": TOP_N,
            "hold": HOLD_DAYS,
            "sell": "stop_profit",
            "stop_loss": STOP_LOSS,
            "take_profit": TAKE_PROFIT,
            "cost": COST,
        },
        "phases": PHASES,
        "trades": trades_output,
    }

    eval_payload = {
        "strategy": "Fstop3_pt5_v10",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "params": trades_payload["params"],
        "phases": PHASES,
        "results": results,
        "source_trades": str(TRADES_PATH),
    }

    save_json(TRADES_PATH, trades_payload)
    save_json(EVAL_PATH, eval_payload)
    generate_report(EVAL_PATH, REPORT_PATH)

    log("\n回测摘要:")
    for phase in ["train", "val", "test"]:
        m = results[phase]["metrics"]
        log(
            f"{phase.upper()}: {m['total_trades']}笔 | 正率{m['positive_rate']:.2f}% | "
            f"夏普{m['sharpe']:.2f} | 均益{m['avg_return']:.4f}%"
        )

    log(f"\n已生成 trades: {TRADES_PATH}")
    log(f"已生成 eval:   {EVAL_PATH}")
    log(f"已生成 report: {REPORT_PATH}")
    log(f"总耗时: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
