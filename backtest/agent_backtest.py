#!/usr/bin/env python3
"""
Agent Backtest Loop - ReAct 架构（兼容不支持 tool_use 的模型）
=============================================================
核心：while True 循环 + 文本解析工具调用 + TodoWrite 任务规划

架构（Layer 1-3）：
- Layer 1: Agent Loop（累积 messages，模型输出 stop 则退出）
- Layer 2: 工具层（dispatch map，加工具不改循环）
- Layer 3: TodoWrite（同一时刻只能一个 in_progress，nag reminder 追责）

用法：
  python backtest/agent_backtest.py --rounds 20
"""

import argparse
import json
import numpy as np
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ===================== 配置 =====================
DB_PATH = os.getenv("STOCK_DB", "/home/heqiang/stock_data_ro.db")

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic/v1"

MODEL = "MiniMax-M2.7"
MAX_TOKENS = 2048

TOP_N = 200
TARGET_WIN_RATE = 55.0

PHASES = {
    "train": ("2021-01-01", "2024-06-30"),
    "val":   ("2024-07-01", "2025-07-01"),
    "test":  ("2025-07-02", "2026-03-24"),
}

# ===================== 数据库 =====================

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA cache_size=-65536")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ===================== 工具层（Layer 2）=====================

def _is_weak_market(conn: sqlite3.Connection, date: str = None) -> bool:
    """判断当天是否为弱市：全市场 >70% 个股收盘价 < MA20（chg_pct < 0 可作为简化判断）。"""
    try:
        cursor = conn.cursor()
        if date:
            # 指定日期
            row = cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN chg_pct > 0 THEN 1 ELSE 0 END) as up_count
                FROM kline_daily
                WHERE trade_date = ? AND volume > 0 AND chg_pct IS NOT NULL
            """, (date,)).fetchone()
        else:
            # 最近有数据的交易日
            row = cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN chg_pct > 0 THEN 1 ELSE 0 END) as up_count
                FROM kline_daily
                WHERE trade_date = (SELECT MAX(trade_date) FROM kline_daily)
                  AND volume > 0 AND chg_pct IS NOT NULL
            """).fetchone()
        if row and row[0] and row[0] > 0:
            up_ratio = row[1] / row[0]
            return up_ratio < 0.30  # 上涨股<30% → 弱市
        return False
    except Exception:
        return False


def scan_market(phase: str = "train", limit: int = TOP_N,
                top_n: int = None, weak_filter: bool = False) -> dict:
    """
    扫描市场候选股票。

    Args:
        phase: "train"|"val"|"test"
        limit: 成交量排序返回上限（兼容旧接口）
        top_n: 每次取成交量最大且满足基本面条件的 top N（默认同 limit）
        weak_filter: 是否开启弱市过滤；开启后仅在全市场上涨股<30%（弱市）时返回候选
    """
    conn = None
    effective_n = top_n if top_n is not None else limit
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        start, end = PHASES.get(phase, PHASES["train"])

        # 弱市过滤：取 phase 末段代表日判断
        if weak_filter:
            recent_date_row = cursor.execute("""
                SELECT MAX(trade_date) FROM kline_daily
                WHERE trade_date BETWEEN ? AND ?
            """, (start, end)).fetchone()
            if recent_date_row and recent_date_row[0]:
                if not _is_weak_market(conn, recent_date_row[0]):
                    return {"ok": True, "phase": phase, "count": 0,
                            "candidates": [], "weak_filtered": True,
                            "message": "非弱市日，已过滤"}

        rows = cursor.execute("""
            SELECT symbol, COUNT(*) as days, SUM(volume) as total_vol,
                   AVG(rsi14) as avg_rsi, MAX(rsi14) as max_rsi, MIN(rsi14) as min_rsi
            FROM kline_daily
            WHERE trade_date BETWEEN ? AND ?
              AND volume > 0 AND rsi14 IS NOT NULL
            GROUP BY symbol
            HAVING days > 100
            ORDER BY total_vol DESC
            LIMIT ?
        """, (start, end, effective_n)).fetchall()

        stocks = [{
            "symbol": r[0], "days": r[1],
            "total_vol": round(r[2], 2) if r[2] else 0,
            "avg_rsi": round(r[3], 1) if r[3] else 50,
            "max_rsi": round(r[4], 1) if r[4] else 50,
            "min_rsi": round(r[5], 1) if r[5] else 50,
        } for r in rows]
        return {"ok": True, "phase": phase, "count": len(stocks),
                "candidates": stocks, "top_n": effective_n,
                "weak_filter": weak_filter}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if conn:
            conn.close()



def _compute_adx(highs, lows, closes, period: int = 14):
    """计算 ADX/+DI/-DI，返回 (adx_list, plus_di_list, minus_di_list)，与输入等长"""
    n = len(highs)
    if n < period + 1:
        return [None] * n, [None] * n, [None] * n

    tr_list = [None] * n
    plus_dm = [None] * n
    minus_dm = [None] * n
    hl_list  = [None] * n

    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list[i] = max(hl, hc, lc)
        hl_list[i] = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]
        plus_dm[i] = hl_list[i] if hl_list[i] > low_diff and hl_list[i] > 0 else 0
        minus_dm[i] = low_diff if low_diff > hl_list[i] and low_diff > 0 else 0

    # Wilder ATR
    atr = sum(tr_list[1:period + 1]) / period
    plus_di_sum = sum(plus_dm[1:period + 1])
    minus_di_sum = sum(minus_dm[1:period + 1])

    adx_list = [None] * n
    plus_di_list = [None] * n
    minus_di_list = [None] * n

    for i in range(period, n):
        atr = (atr * (period - 1) + tr_list[i]) / period
        plus_di_sum = (plus_di_sum * (period - 1) + plus_dm[i]) / period
        minus_di_sum = (minus_di_sum * (period - 1) + minus_dm[i]) / period
        pdi = plus_di_sum / atr * 100 if atr > 0 else 0
        mdi = minus_di_sum / atr * 100 if atr > 0 else 0
        dx = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
        plus_di_list[i] = pdi
        minus_di_list[i] = mdi
        adx_list[i] = dx

    return adx_list, plus_di_list, minus_di_list



def backtest_signal(symbol: str, signal_type: str, params: dict,
                    phase: str = "train") -> dict:
    """对单只股票回测"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        start, end = PHASES.get(phase, PHASES["train"])
        rows = cursor.execute("""
            SELECT trade_date, open, high, low, close, volume,
                   rsi14, ma5, ma10, ma20,
                   macd_dif, macd_dea, macd_hist,
                   boll_lower, boll_upper, boll_mid,
                   kdj_k, kdj_d, kdj_j
            FROM kline_daily
            WHERE symbol = ? AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date ASC
        """, (symbol, start, end)).fetchall()

        if len(rows) < 30:
            return {"ok": False, "error": f"数据不足: {len(rows)}条"}

        dates    = [r[0] for r in rows]
        opens    = [r[1] for r in rows]
        highs    = [r[2] for r in rows]
        lows     = [r[3] for r in rows]
        closes   = [r[4] for r in rows]
        volumes  = [r[5] for r in rows]
        rsi14_l  = [r[6] for r in rows]
        ma5_l    = [r[7] for r in rows]
        ma10_l   = [r[8] for r in rows]
        ma20_l   = [r[9] for r in rows]
        macd_dif = [r[10] for r in rows]
        macd_dea = [r[11] for r in rows]
        macd_hst = [r[12] for r in rows]
        boll_low = [r[13] for r in rows]
        boll_up  = [r[14] for r in rows]
        boll_mid = [r[15] for r in rows]
        kdj_k    = [r[16] for r in rows]
        kdj_d    = [r[17] for r in rows]
        kdj_j    = [r[18] for r in rows]

        # 预计算 ADX
        adx_list, plus_di_list, minus_di_list = _compute_adx(highs, lows, closes)

        hold_days = params.get("hold_days", 7)
        signal_count = win_count = 0
        total_return = 0.0
        trades = []

        i = 0
        while i < len(rows) - hold_days:
            trigger = False
            if signal_type == "rsi":
                thresh = params.get("rsi_thresh", 20)
                if rsi14_l[i] is not None and rsi14_l[i] <= thresh:
                    trigger = True
            elif signal_type == "bb_break":
                thresh = params.get("bb_thresh", 1.0)
                if boll_low[i] is not None and closes[i] <= boll_low[i] * thresh:
                    trigger = True
            elif signal_type == "macd_goldCross":
                if macd_dif[i] is not None and macd_dea[i] is not None:
                    if i > 0 and macd_dif[i] > macd_dea[i] and macd_dif[i-1] <= macd_dea[i-1]:
                        trigger = True
            elif signal_type == "ma_cross":
                if ma5_l[i] is not None and ma10_l[i] is not None:
                    if i > 0 and ma5_l[i] > ma10_l[i] and ma5_l[i-1] <= ma10_l[i-1]:
                        trigger = True
            elif signal_type == "bollinger_bounce":
                if boll_low[i] is not None and closes[i] <= boll_low[i]:
                    trigger = True
            elif signal_type == "volume_breakout":
                vol_thresh = params.get("vol_thresh", 1.5)
                avg_v = sum(volumes[max(0,i-20):i]) / min(20, i+1) if i > 0 else volumes[0]
                if volumes[i] > avg_v * vol_thresh:
                    trigger = True

            # ===== KDJ 系列 =====
            elif signal_type == "kdj_goldCross":
                if kdj_k[i] is not None and kdj_d[i] is not None:
                    if i > 0 and kdj_k[i] > kdj_d[i] and kdj_k[i-1] <= kdj_d[i-1]:
                        trigger = True

            elif signal_type == "kdj_oversold":
                thresh = params.get("kdj_thresh", 20)
                if kdj_j[i] is not None and kdj_j[i] < thresh:
                    trigger = True

            # ===== MACD 增强 =====
            elif signal_type == "macd_hist_turn":
                if macd_hst[i] is not None:
                    if i > 0 and macd_hst[i] > 0 and macd_hst[i-1] <= 0:
                        trigger = True

            elif signal_type == "macd_divergence":
                if macd_hst[i] is not None and macd_dif[i] is not None:
                    if i > 5 and closes[i] < closes[i-3] and macd_dif[i] > macd_dif[i-3]:
                        trigger = True

            # ===== 成交量 =====
            elif signal_type == "volume_shrink":
                shrink = params.get("shrink_ratio", 0.3)
                if i >= 20:
                    avg_v = sum(volumes[i-20:i]) / 20
                    if volumes[i] < avg_v * shrink:
                        trigger = True

            elif signal_type == "volume_mean_reversion":
                if i >= 5:
                    short_avg = sum(volumes[i-5:i]) / 5
                    long_avg = sum(volumes[i-20:i]) / 20
                    if short_avg < long_avg * 0.5 and volumes[i] > volumes[i-1] * 1.2:
                        trigger = True

            # ===== 多周期共振 =====
            elif signal_type == "rsi_ma_combo":
                rsi_thresh = params.get("rsi_thresh", 20)
                if rsi14_l[i] is not None and rsi14_l[i] <= rsi_thresh:
                    if ma5_l[i] is not None and ma10_l[i] is not None and ma20_l[i] is not None:
                        if ma5_l[i] > ma10_l[i] > ma20_l[i]:
                            trigger = True

            elif signal_type == "kdj_macd_combo":
                if kdj_k[i] is not None and kdj_d[i] is not None and macd_dif[i] is not None and macd_dea[i] is not None:
                    kdj_cross = kdj_k[i] > kdj_d[i] and kdj_k[i-1] <= kdj_d[i-1] if i > 0 else False
                    macd_cross = macd_dif[i] > macd_dea[i] and macd_dif[i-1] <= macd_dea[i-1] if i > 0 else False
                    if kdj_cross and macd_cross:
                        trigger = True

            # ===== 趋势 =====
            elif signal_type == "adx_plusDI":
                thresh = params.get("adx_thresh", 20)
                if adx_list[i] is not None and adx_list[i] > thresh:
                    if plus_di_list[i] is not None and minus_di_list[i] is not None:
                        if plus_di_list[i] > minus_di_list[i]:
                            trigger = True

            # ===== 支撑压力 =====
            elif signal_type == "price_support":
                n = params.get("n_days", 5)
                if i >= n:
                    window_low = min(lows[i-n:i+1])
                    if lows[i] <= window_low:
                        trigger = True

            elif signal_type == "price_resistance":
                n = params.get("n_days", 5)
                if i >= n:
                    window_high = max(highs[i-n:i+1])
                    if highs[i] >= window_high:
                        trigger = True

            if trigger:
                signal_count += 1
                # T+1 开盘买入
                buy_idx = i + 1 if i + 1 < len(rows) else i
                ep = rows[buy_idx][1]  # open price
                ed = dates[buy_idx]

                # ---- 卖出逻辑（sell_mode）----
                sell_mode = params.get("sell_mode", "fixed_hold")

                if sell_mode == "stop_profit":
                    # T+2 起每日检查止损/止盈
                    stop_loss = params.get("stop_loss", 3.0)
                    take_profit = params.get("take_profit", 5.0)
                    exit_idx = None
                    for d in range(i + 2, min(i + hold_days + 1, len(rows))):
                        day_ret = (rows[d][4] - ep) / ep * 100  # close vs buy_price
                        if day_ret >= take_profit:
                            exit_idx = d
                            break
                        if day_ret <= -stop_loss:
                            exit_idx = d
                            break
                    if exit_idx is None:
                        exit_idx = min(i + hold_days, len(rows) - 1)
                else:
                    # fixed_hold: T+1+N 收盘卖出
                    exit_idx = min(i + hold_days, len(rows) - 1)

                xp = rows[exit_idx][4]  # close price at exit
                # 双边交易成本 0.30%（买入扣一次，卖出扣一次）
                ret = (xp - ep) / ep * 100 - 0.30
                total_return += ret
                if ret > 0:
                    win_count += 1
                trades.append({
                    "symbol": symbol, "entry_date": ed, "entry_price": round(ep, 2),
                    "exit_date": dates[exit_idx], "exit_price": round(xp, 2),
                    "return_pct": round(ret, 2), "signal": signal_type,
                    "sell_mode": sell_mode,
                })
                i += hold_days
            else:
                i += 1

        if signal_count == 0:
            return {"ok": False, "error": "无信号"}

        return {
            "ok": True, "symbol": symbol, "signal_type": signal_type,
            "params": params, "phase": phase,
            "signal_count": signal_count, "win_count": win_count,
            "win_rate": round(win_count / signal_count * 100, 1),
            "avg_return": round(total_return / signal_count, 2),
            "total_return": round(total_return, 2),
            "trades": trades,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if conn:
            conn.close()


def backtest_batch(symbols: list, signal_type: str, params: dict, phase: str = "train") -> dict:
    """
    对一批股票批量回测，聚合所有股票的收益列表。
    用于验证"选股策略"是否在多只股票上通用。

    返回：{
        ok, phase,
        total_signals, hit_stocks, win_rate, avg_return,
        trades: [{symbol, buy_date, sell_date, return_pct}, ...]
    }
    """
    all_trades = []
    hit = set()
    total_signals = 0
    total_wins = 0
    total_ret = 0.0
    errors = []

    for sym in symbols:
        r = backtest_signal(sym, signal_type, params, phase)
        if r.get('ok') and r.get('signal_count', 0) > 0:
            total_signals += r['signal_count']
            total_wins += r.get('win_count', 0)
            total_ret += r.get('total_return', 0)
            for t in r.get('trades', []):
                all_trades.append(t)
                hit.add(t['symbol'])
        elif not r.get('ok'):
            errors.append(f"{sym}: {r.get('error', 'unknown')}")

    if total_signals == 0:
        return {"ok": False, "phase": phase, "error": "无信号", "details": errors}

    return {
        "ok": True,
        "phase": phase,
        "total_signals": total_signals,
        "hit_stocks": len(hit),
        "win_rate": round(total_wins / total_signals * 100, 2),
        "avg_return": round(total_ret / total_signals, 4),
        "trades": all_trades,
        "errors": errors[:5],  # 只保留前5个错误
    }


def _calc_metrics(rets: list, hold_days: int) -> dict:
    """计算完整指标（与项目评估框架对齐）"""
    if not rets:
        return {
            'trades': 0, 'pos_rate': 0, 'avg': 0, 'sharpe': 0,
            'max_dd': 0, 'sortino': 0, 'win_rate': 0, 'plr': 0,
            'ann_ret': 0, 'vol': 0, 'sortino_ret': 0,
        }
    r = np.array(rets)
    n = len(r)
    pos = r[r > 0]
    neg = r[r < 0]
    pos_rate = len(pos) / n * 100
    avg = float(np.mean(r))
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_ret = avg * 252 / hold_days
    ann_vol = std * np.sqrt(252 / hold_days)
    rf = 3.0  # 无风险利率
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0
    # 最大回撤
    cum = np.cumprod(1 + r / 100)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak * 100
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0
    # Sortino
    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold_days)) if len(dn) > 1 else 0
    sortino = (ann_ret - rf) / dn_std if dn_std > 0 else 0
    # 盈亏比
    plr = float(np.mean(pos) / abs(np.mean(neg))) if len(pos) > 0 and len(neg) > 0 else 0
    return {
        'trades': n, 'pos_rate': round(pos_rate, 2), 'avg': round(avg, 4),
        'sharpe': round(sharpe, 4), 'max_dd': round(max_dd, 2), 'sortino': round(sortino, 4),
        'win_rate': round(pos_rate, 2), 'plr': round(plr, 4),
        'ann_ret': round(ann_ret, 2), 'vol': round(ann_vol, 4),
    }


def evaluate_result(candidate: dict = None, /, **kwargs) -> dict:
    """
    完整三阶段评估（对接 stock-strategy-evaluator skill 的 28 项指标框架）。

    支持两种调用格式：
      1. evaluate_result(candidate={...})           # 包装格式
      2. evaluate_result(symbol=..., signal_type=..., params={...}, train={...}, val={...}, test={...})  # 解包格式

    PIT 合规要求：
    - 策略所用数据必须在购买股票前已经公开（即 PIT 合规）
    - 若 candidate 中带 pit_compliant=True 字段则认可；
      若带 pit_compliant=False 或不带该字段，框架会在 TOOL_DOC 里注明
      "策略必须使用 PIT 合规数据"
    - 财报 PIT 延迟参考：一季报30天/半年报62天/三季报31天/年报120天
    """
    import subprocess

    # 支持解包格式：LLM 传 symbol/train/val/test 分别作为关键字参数
    if candidate is None:
        candidate = {
            "symbol": kwargs.get("symbol"),
            "signal_type": kwargs.get("signal_type"),
            "params": kwargs.get("params", {}),
            "pit_compliant": kwargs.get("pit_compliant", False),
            "train": kwargs.get("train"),
            "val": kwargs.get("val"),
            "test": kwargs.get("test"),
        }

    for phase in ('train', 'val', 'test'):
        r = candidate.get(phase, {})
        if r.get('ok') is False:
            return {"ok": False, "qualified": False, "reason": f"{phase}阶段回测失败: {r.get('error')}"}

    # 1. 构建 trades.json（供评估脚本使用）
    trades_data = {
        "name": f"{candidate.get('symbol', '')}_{candidate.get('signal_type', '')}",
        "config": candidate.get('params', {}),
    }
    for phase in ('train', 'val', 'test'):
        phase_trades = candidate.get(phase, {}).get('trades', [])
        trades_data[phase] = [
            {
                "symbol": t.get('symbol'),
                "buy_date": t.get('entry_date'),
                "sell_date": t.get('exit_date'),
                "return_pct": t.get('return_pct'),
            }
            for t in phase_trades
        ]

    # 2. 写临时 trades.json
    work_dir = Path(__file__).parent.parent
    trades_file = work_dir / ".tmp_trades.json"
    result_file = work_dir / "evaluate_result.json"
    with open(trades_file, "w") as f:
        json.dump(trades_data, f, ensure_ascii=False)

    # 3. 调用评估脚本
    eval_script = Path("/home/heqiang/.openclaw-bot1/workspace/skills/stock-strategy-evaluator/scripts/evaluate_strategy.py")
    if not eval_script.exists():
        # 回退：尝试相对路径
        eval_script = work_dir / "scripts" / "evaluate_strategy.py"

    try:
        cp = subprocess.run(
            ["python3", str(eval_script), str(trades_file),
             "--name", f"{candidate.get('symbol', '')}_{candidate.get('signal_type', '')}",
             "--stages", "train", "val", "test"],
            capture_output=True, text=True, timeout=120,
            cwd=str(work_dir)
        )
        eval_ok = cp.returncode == 0
    except Exception as e:
        eval_ok = False

    # 4. 读取 28 项指标结果
    per_stage = {}
    if result_file.exists():
        try:
            with open(result_file) as f:
                full_result = json.load(f)
            per_stage = full_result.get("per_stage", {})
        except Exception:
            pass

    # 5. 基于 28 项指标判断是否达标
    qualified = True
    reasons = []
    stage_summary = {}

    for phase in ('train', 'val', 'test'):
        metrics = per_stage.get(phase, {})
        signal_count = len(trades_data.get(phase, []))
        win_rate = metrics.get('win_rate', metrics.get('positive_rate', 0))
        avg_return = metrics.get('avg_return', 0)

        stage_summary[phase] = {
            **metrics,
            "phase": phase,
            "signal_count": signal_count,
        }

        if signal_count < 5:
            qualified = False
            reasons.append(f"{phase}信号太少({signal_count}笔)")
        if win_rate < TARGET_WIN_RATE:
            qualified = False
            reasons.append(f"{phase}胜率{win_rate:.1f}%<{TARGET_WIN_RATE}%")
        if avg_return <= 0:
            qualified = False
            reasons.append(f"{phase}均益{avg_return:.2f}%<=0")

    # 三阶段一致性
    wr_list = [stage_summary.get(p, {}).get('win_rate', 0) or stage_summary.get(p, {}).get('positive_rate', 0) for p in ('train', 'val', 'test')]
    wr_consistency = min(wr_list) / max(wr_list) * 100 if max(wr_list) > 0 else 0

    # train_test_ratio
    train_ret = stage_summary.get('train', {}).get('avg_return', 0)
    test_ret = stage_summary.get('test', {}).get('avg_return', 0)
    train_test_ratio = train_ret / test_ret if test_ret != 0 else 0

    # 汇总
    summary = {
        "ok": True,
        "qualified": qualified,
        "symbol": candidate.get("symbol"),
        "signal_type": candidate.get("signal_type"),
        "params": candidate.get("params"),
        "per_stage": {
            "train": stage_summary.get("train", {}),
            "val":   stage_summary.get("val", {}),
            "test":  stage_summary.get("test", {}),
        },
        "total_trades": sum(len(trades_data.get(p, [])) for p in ('train', 'val', 'test')),
        "wr_consistency": round(wr_consistency, 2),
        "train_test_ratio": round(train_test_ratio, 4),
        "reasons": reasons,
        "config": candidate.get('params', {}),
    }

    wr_train = stage_summary.get('train', {}).get('win_rate', stage_summary.get('train', {}).get('positive_rate', 0))
    wr_val   = stage_summary.get('val',   {}).get('win_rate', stage_summary.get('val',   {}).get('positive_rate', 0))
    wr_test  = stage_summary.get('test',  {}).get('win_rate', stage_summary.get('test',  {}).get('positive_rate', 0))

    if qualified:
        summary["reason"] = (
            f"✅ 三阶段全达标 | "
            f"训练胜率{wr_train:.1f}% 均益{stage_summary.get('train',{}).get('avg_return',0):.2f}% | "
            f"验证胜率{wr_val:.1f}% 均益{stage_summary.get('val',{}).get('avg_return',0):.2f}% | "
            f"测试胜率{wr_test:.1f}% 均益{stage_summary.get('test',{}).get('avg_return',0):.2f}% | "
            f"一致性{wr_consistency:.1f}%"
        )
        summary["push"] = True
    else:
        summary["reason"] = " | ".join(reasons)
        summary["push"] = False

    # 6. 写最终结果（供后续写入飞书文档）
    final_result_file = work_dir / "evaluate_result.json"
    with open(final_result_file, "w") as f:
        json.dump({
            "name": f"{candidate.get('symbol','')}_{candidate.get('signal_type','')}",
            "config": candidate.get('params', {}),
            "per_stage": per_stage,
            "qualified": qualified,
            "summary": summary,
        }, f, indent=2, ensure_ascii=False)

    # 清理临时文件
    if trades_file.exists():
        trades_file.unlink()

    return summary


def push_candidate(candidate: dict = None, /, **kwargs) -> dict:
    """推送达标策略。支持 evaluate_result 同款两种调用格式。"""
    if candidate is None:
        candidate = {
            "symbol": kwargs.get("symbol"),
            "signal_type": kwargs.get("signal_type"),
            "params": kwargs.get("params", {}),
            "train": kwargs.get("train"),
            "val": kwargs.get("val"),
            "test": kwargs.get("test"),
        }
    f = Path(__file__).parent.parent / "data" / "results" / "agent_candidates.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a") as fp:
        fp.write(json.dumps({**candidate, "found_at": datetime.now().isoformat()}, ensure_ascii=False) + "\n")
    return {"ok": True, "count": sum(1 for _ in open(f))}


# ===================== 工具调度表 =====================

def update_todo(todo: list) -> dict:
    """更新Todo列表"""
    return {"ok": True, "todo": todo}

TOOL_HANDLERS = {
    "scan_market":      lambda **kw: scan_market(**kw),
    "backtest_signal":  lambda **kw: backtest_signal(**kw),
    "backtest_batch":   lambda **kw: backtest_batch(**kw),
    "evaluate_result":  lambda **kw: evaluate_result(**kw),
    "push_candidate":   lambda **kw: push_candidate(**kw),
    "update_todo":      lambda **kw: update_todo(**kw),
}


def _auto_decode(obj):
    """自动将JSON字符串解析为dict/list"""
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            # 递归解析嵌套的JSON字符串（如 LLM double-encode 问题）
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return parsed
        except (json.JSONDecodeError, ValueError):
            return obj
    if isinstance(obj, dict):
        return {k: _auto_decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_auto_decode(v) for v in obj]
    return obj

def run_tool(name: str, arguments: dict) -> str:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"}, ensure_ascii=False)
    try:
        # 自动修复 LLM double-encode 问题
        fixed_args = _auto_decode(arguments)
        result = handler(**fixed_args)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ===================== TodoWrite 管理器（Layer 3）=====================

class TodoManager:
    def __init__(self):
        self.items = []
        self.rounds_since_update = 0

    def update(self, items: list):
        if sum(1 for it in items if it.get("status") == "in_progress") > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = items
        self.rounds_since_update = 0

    def tick(self):
        self.rounds_since_update += 1

    def should_nag(self) -> bool:
        return self.rounds_since_update >= 3

    def get_display(self) -> str:
        if not self.items:
            return "(no tasks)"
        return "\n".join(
            f"{ {'pending':'🔲','in_progress':'🔵','completed':'✅'}.get(it.get('status'),'⬜')} "
            f"[{it.get('status')}] {it.get('content','')}"
            for it in self.items
        )


# ===================== LLM 调用 =====================

def call_llm(messages: list, model: str = MODEL) -> dict:
    import urllib.request, urllib.error

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
    }

    req = urllib.request.Request(
        f"{MINIMAX_BASE_URL}/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "curl/7.81.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"error": str(e)}


# ===================== ReAct 文本解析 =====================

TOOL_CALL_RE = re.compile(
    r'<tool_call>\s*(\w+)\s*\(\s*(.*?)\s*\)\s*</tool_call>',
    re.DOTALL
)
STOP_RE = re.compile(r'<stop\s*/?>', re.IGNORECASE)

TOOL_DOC = """
你可用的工具（直接调用，不要在思考里描述）：

scan_market(phase: str, limit: int, top_n: int, weak_filter: bool) -> candidates[]
  - phase: "train"|"val"|"test"
  - limit: 成交量排序返回上限（兼容旧接口）
  - top_n: 每次取成交量最大且满足基本面条件的 top N
  - weak_filter: 是否开启弱市过滤（上涨股<30%）；开启后仅弱市日返回候选
  - 返回成交量最高的候选股票列表

backtest_signal(symbol: str, signal_type: str, params: dict, phase: str) -> result
  - signal_type: "rsi"|"bb_break"|"macd_goldCross"|"ma_cross"|"bollinger_bounce"|"volume_breakout"|"kdj_goldCross"|"kdj_oversold"|"macd_hist_turn"|"macd_divergence"|"volume_shrink"|"volume_mean_reversion"|"rsi_ma_combo"|"kdj_macd_combo"|"adx_plusDI"|"price_support"|"price_resistance"
  - params示例: {"rsi_thresh": 20, "hold_days": 7}
  - 卖出规则（sell_mode）：
      * sell_mode="fixed_hold"（默认）：T+1开盘买 → T+1+N收盘卖
      * sell_mode="stop_profit"：T+1开盘买 → T+2起每日检查止损/止盈，触发则卖，否则持有满N天
        - stop_loss（默认3.0）：日收益<=-stop_loss% 止损，当日收盘卖
        - take_profit（默认5.0）：日收益>=take_profit% 止盈，当日收盘卖
  - 交易成本：双边0.30%（买入扣一次，卖出扣一次）
  - 返回回测统计结果（含每笔交易的 return_pct，已扣成本）

backtest_batch(symbols: list, signal_type: str, params: dict, phase: str) -> result
  - 对一批股票（symbols列表）批量回测，聚合所有收益
  - **这是验证"选股策略"的核心工具** — 先用 scan_market 扫出一批股票，再用此工具批量验证策略
  - 返回：{total_signals, hit_stocks, win_rate, avg_return, trades: [...]}
  - trades 列表可供 evaluate_result 计算28项指标

⚠️ PIT 合规：策略必须使用 PIT 合规数据，即选股所用数据必须在买入前已公开。
   财报PIT延迟参考：一季报30天/半年报62天/三季报31天/年报120天。

evaluate_result(candidate: dict) -> evaluation
  - 完整三阶段评估（接项目评估框架）
  - candidate格式: {"symbol":str,"signal_type":str,"params":dict,"pit_compliant":bool,"train":{result},"val":{result},"test":{result}}
  - 返回每阶段完整指标(sharpe/max_dd/sortino等)及三阶段一致性
  - qualified=True表示三阶段全部达标（胜率≥55%、均益>0、信号数≥5、一致性高）

push_candidate(candidate: dict)
  - 推送三阶段全达标的策略到候选池

停止探索：直接输出 <stop/>
"""


def parse_model_output(text: str) -> tuple[list[tuple], bool]:
    """
    解析模型输出中的工具调用和停止标记。
    返回 ([(name, args_str), ...], should_stop)
    """
    calls = []
    should_stop = bool(STOP_RE.search(text))
    for m in TOOL_CALL_RE.finditer(text):
        calls.append((m.group(1), m.group(2).strip()))
    return calls, should_stop



def parse_positional_args(args_str: str, tool_name: str) -> dict:
    """将位置参数列表转为字典。支持嵌套结构。"""
    def split_args(s):
        parts = []
        depth = 0
        current = ""
        for ch in s:
            if ch in "{[":
                depth += 1
                current += ch
            elif ch in "}]":
                depth -= 1
                current += ch
            elif ch == "," and depth == 0:
                parts.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            parts.append(current.strip())
        return parts

    def convert_value(v):
        v = v.strip()
        if not v or v in ('None', 'null'):
            return None
        if v in ('True', 'true'):
            return True
        if v in ('False', 'false'):
            return False
        if v.startswith('"') or v.startswith("'"):
            return v.strip('"\'')
        if v.startswith('{') or v.startswith('['):
            try:
                return json.loads(v)
            except Exception:
                return v
        try:
            return int(v)
        except Exception:
            try:
                return float(v)
            except Exception:
                return v

    parts = split_args(args_str)
    result = {}
    if tool_name == "scan_market":
        keys = ["phase", "limit"]
    elif tool_name == "backtest_signal":
        keys = ["symbol", "signal_type", "params", "phase"]
    elif tool_name in ("evaluate_result", "push_candidate"):
        keys = ["candidate"]
    elif tool_name == "backtest_batch":
        keys = ["symbols", "signal_type", "params", "phase"]
    else:
        return result
    for i, part in enumerate(parts):
        if i < len(keys):
            result[keys[i]] = convert_value(part)
    return result


def parse_args(args_str: str, tool_name: str = None) -> dict:
    args_str = args_str.strip()
    if not args_str:
        return {}
    # 修复 LLM double-encode 问题：去掉嵌套的 <tool_call>...</tool_call> 标签
    # 例: {"phase": "<tool_call>{"phase": "train"}</tool_call>"} -> {"phase": "..."}
    # 处理嵌套 tool_call 在 JSON 字符串值里的情况
    while True:
        stripped = re.sub(r'<tool_call>[^<]*</tool_call>', '', args_str)
        if stripped == args_str:
            break
        args_str = stripped
    # 处理 JSON 字符串值里包含 tool_call 的情况：{"key": "<tool_call>{...}</tool_call>"}
    # 提取内层 JSON 并替换
    def replace_tool_call_in_json(m):
        inner = m.group(1)  # <tool_call>{...}</tool_call>
        inner_json = re.search(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', inner, re.DOTALL)
        if inner_json:
            try:
                parsed = json.loads(inner_json.group(1))
                # 把 Python 对象转回 JSON 字符串（不带外层引号）
                return json.dumps(parsed, ensure_ascii=False)
            except Exception:
                pass
        return m.group(0)
    args_str = re.sub(r'"([^"]*)"', replace_tool_call_in_json, args_str)
    if args_str.startswith("{"):
        try:
            return json.loads(args_str)
        except Exception:
            pass
    if "=" in args_str:
        result = {}
        for part in args_str.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip(); v = v.strip()
                try:
                    result[k] = json.loads(v)
                except Exception:
                    if v.startswith('"') or v.startswith("'"):
                        result[k] = v.strip('"\'')
                    elif v in ("True", "true"):
                        result[k] = True
                    elif v in ("False", "false"):
                        result[k] = False
                    elif v in ("None", "null"):
                        result[k] = None
                    else:
                        try:
                            result[k] = int(v)
                        except Exception:
                            try:
                                result[k] = float(v)
                            except Exception:
                                result[k] = v
        return result
    if tool_name:
        return parse_positional_args(args_str, tool_name)
    return {}



# ===================== Agent Loop 主循环（Layer 1）=====================

SYSTEM_PROMPT = f"""你是一个股票策略探索 Agent，目标是找到三阶段（训练/验证/测试）都能盈利的策略。

规则：
- 训练集选策略，验证/测试集只评估（不能调参）
- A股 T+1：T日信号，T+1开盘买，持有N天后收盘卖
- 目标：胜率≥55%，均益>0，信号数≥5

工作方式（ReAct）：
1. 你在思考中分析当前状态
2. 决定下一步后，用 <tool_call>tool_name(args)</tool_call> 格式调用工具
3. 工具结果会返回给你，继续分析
4. 当你认为探索足够时，输出 <stop/>

{TOOL_DOC}

重要：
- 先扫描训练集了解候选股票池
- 分析候选股的 RSI 区间/波动性，决定试哪只
- 信号类型和参数组合由你决定
- **选股策略正确流程**：
  1. scan_market 扫出候选股票列表
  2. **backtest_batch** 对整批股票批量回测（一次评估一篮子股票的同一策略）
  3. 用返回的 trades 列表供 evaluate_result 计算28项指标
  4. 三阶段都要用 backtest_batch 验证，不能只测单只股票
- 达标标准：胜率>55%、均益>0、三阶段一致性>60%
- evaluate_result 需要传入包含 train/val/test 三个阶段结果的完整 candidate 结构
"""


def run_agent_loop(rounds: int = 20, model: str = None) -> dict:
    todo_mgr = TodoManager()
    todo_mgr.update([
        {"content": "扫描市场候选股票池", "status": "in_progress"},
        {"content": "分析候选股，选择信号类型和参数", "status": "pending"},
        {"content": "三阶段回测，评估是否达标", "status": "pending"},
        {"content": "达标策略推送候选池", "status": "pending"},
    ])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"""开始策略探索。

当前 Todo：
{todo_mgr.get_display()}

数据库: {DB_PATH}
三阶段：
- 训练集: 2021-01-01 ~ 2024-06-30
- 验证集: 2024-07-01 ~ 2025-07-01
- 测试集: 2025-07-02 ~ 2026-03-24

请开始：先扫描训练集市场候选股票。
"""},
    ]

    candidates = []
    round_num = 0
    todo_updated_this_turn = False

    print(f"\n{'='*60}")
    print(f"🤖 Agent Backtest Loop | 模型: {model or MODEL} | 最多{rounds}轮")
    print(f"{'='*60}\n")

    while round_num < rounds:
        round_num += 1
        print(f"\n--- 第 {round_num}/{rounds} 轮 ---")

        # Nag reminder
        if todo_mgr.should_nag() and not todo_updated_this_turn:
            nag = {"role": "user", "content": "<reminder>请更新 Todo 状态。你在做什么？进展如何？</reminder>"}
            messages.append(nag)
            print("   🔔 [Nag] 连续未更新 Todo，已注入提醒")

        t0 = time.time()
        resp = call_llm(messages, model=model or MODEL)
        elapsed = time.time() - t0

        if "error" in resp:
            print(f"   ❌ LLM 错误: {resp['error']}")
            break

        # 提取文本内容
        content = resp.get("content", [])
        thinking = text = ""
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking":
                        thinking += block.get("text", "")
                    elif block.get("type") == "text":
                        text += block.get("text", "")
        full_text = thinking + text

        # 打印思考
        display_thought = (thinking or text)[:400].replace("\n", " ")
        print(f"   💭 {display_thought[:300]}...")

        # 解析工具调用
        tool_calls, should_stop = parse_model_output(full_text)
        todo_updated_this_turn = False

        if should_stop or not tool_calls:
            print(f"   ✅ 模型结束（{'<stop/>' if should_stop else '无工具调用'}）")
            break

        # 执行工具
        tool_results = []
        for name, args_str in tool_calls:
            args = parse_args(args_str, name)
            print(f"   🔧 {name}({json.dumps(args, ensure_ascii=False)[:80]})")
            result_str = run_tool(name, args)
            result_obj = json.loads(result_str)

            # 检查 update_todo
            if name == "update_todo":
                try:
                    todo_mgr.update(args.get("todo", []))
                    print(f"   📋 Todo: {todo_mgr.get_display()}")
                    todo_updated_this_turn = True
                except ValueError as ex:
                    print(f"   ⚠️  Todo无效: {ex}")
                    result_obj = {"ok": False, "error": str(ex)}

            # 检查 push_candidate
            if name == "push_candidate" and result_obj.get("ok"):
                cand = args.get("candidate", {})
                candidates.append(cand)
                print(f"   🎉 入池！累计 {len(candidates)} 个达标策略")

            print(f"   ← {result_str[:200]}")
            tool_results.append({"role": "user", "content": result_str})

        messages.append({"role": "assistant", "content": full_text})
        messages.extend(tool_results)

        if not todo_updated_this_turn:
            todo_mgr.tick()

        print(f"   ⏱️  {elapsed:.1f}秒 | 达标: {len(candidates)}个")

    print(f"\n{'='*60}")
    print(f"🏁 结束 | {round_num}轮 | 达标: {len(candidates)}个")
    print(f"{'='*60}\n")

    for i, c in enumerate(candidates, 1):
        print(f"  {i}. {c.get('symbol')} | {c.get('signal_type')} {c.get('params')}")
        for ph in ("train", "val", "test"):
            p = c.get(ph, {})
            print(f"     {ph}: 胜率{p.get('win_rate','?')}% 均益{p.get('avg_return','?')}%")

    return {"ok": True, "rounds": round_num, "candidates": candidates}


# ===================== 入口 =====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--model",  type=str,  default=None)
    args = parser.parse_args()

    t0 = time.time()
    result = run_agent_loop(rounds=args.rounds, model=args.model)
    print(f"\n总耗时: {time.time()-t0:.1f}秒")
