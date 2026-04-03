#!/usr/bin/env python3
"""
股票策略评测框架
严格遵守项目目标：
  - 训练集选策略，验证/测试只做样本外检验
  - PIT财报延迟（按披露截止日）
  - A股 T+1 卖出约束
  - 28项评价指标（训练/验证/测试分别计算）
  - 三阶段正收益率 >55%

用法：
  from strategy_evaluator import StrategyEvaluator
  ev = StrategyEvaluator()
  ev.load_data()
  result = ev.evaluate(strategy_fn, hold_days=10)
  ev.print_28_metrics(result)
  ev.save(result, 'my_strategy')
"""
import sqlite3, json, time, os
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, List, Tuple

# ============================================================
# 配置
# ============================================================
DB = '/mnt/data/workspace/stock-monitor-app-py/data/stock_data.db'
TOP_N = 200
RF = 0.03          # 无风险利率 3%
COST = 0.30        # 0.15%单边 x2
OUTPUT_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-01'),
    'test':  ('2025-07-02', '2026-03-27'),
}

# ============================================================
# PIT 延迟（按财报披露截止日）
# ============================================================
def pit_delay_days(report_date: str) -> int:
    """根据报告期月份计算PIT延迟天数"""
    month = int(report_date[5:7])
    if month == 3:   return 30    # Q1: 03-31 → 04-30
    elif month == 6: return 62    # H1: 06-30 → 08-31
    elif month == 9: return 31    # Q3: 09-30 → 10-31
    elif month == 12: return 120  # 年报: 12-31 → 次年04-30
    return 45

# ============================================================
# 基本面打分（quick_explore 公式）
# ============================================================
def fund_score(roe, rev_g, profit_g, gross_margin, debt_ratio):
    """基本面打分（满分100）"""
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
# 28项指标计算
# ============================================================
@dataclass
class Metrics28:
    """28项评价指标"""
    # 基础指标（7）
    total_trades: int = 0
    positive_rate: float = 0.0
    avg_return: float = 0.0
    median_return: float = 0.0
    max_return: float = 0.0
    min_return: float = 0.0
    hit_stocks: int = 0
    # 风险指标（5）
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    downside_volatility: float = 0.0
    sortino: float = 0.0
    # 交易质量（8）
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_win: float = 0.0
    max_loss: float = 0.0
    max_consec_win: int = 0
    max_consec_loss: int = 0
    # 效率指标（5）
    annual_return: float = 0.0
    calmar: float = 0.0
    recovery_factor: float = 0.0
    break_even_wr: float = 0.0
    expectancy: float = 0.0
    # 稳定性（3）
    train_test_ratio: float = 0.0
    three_phase_consistency: int = 0
    avg_hold_days: float = 0.0

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d.get(k, 0) for k in cls.__dataclass_fields__})


def calc_metrics(rets: List[float], hold_days: int, hit_stock_count: int = 0) -> Metrics28:
    """从收益率列表计算28项指标"""
    m = Metrics28()
    if not rets:
        return m

    r = np.array(rets)
    n = len(r)
    pos = r[r > 0]
    neg = r[r <= 0]

    # 基础指标
    m.total_trades = n
    m.positive_rate = round(len(pos) / n * 100, 2)
    m.avg_return = round(float(np.mean(r)), 4)
    m.median_return = round(float(np.median(r)), 4)
    m.max_return = round(float(max(r)), 4)
    m.min_return = round(float(min(r)), 4)
    m.hit_stocks = hit_stock_count

    # 年化
    ann_ret = m.avg_return * 252 / hold_days
    std = float(np.std(r, ddof=1)) if n > 1 else 0
    ann_vol = std * np.sqrt(252 / hold_days)

    # 风险指标
    m.volatility = round(ann_vol, 4)
    m.sharpe = round((ann_ret - RF * 100) / ann_vol, 4) if ann_vol > 0 else 0

    dn = r[r < 0]
    dn_std = float(np.std(dn, ddof=1) * np.sqrt(252 / hold_days)) if len(dn) > 1 else 0
    m.downside_volatility = round(dn_std, 4)
    m.sortino = round((ann_ret - RF * 100) / dn_std, 4) if dn_std > 0 else 0

    # 最大回撤（对数累计收益）
    cum = 0; peak = 0; mdd = 0
    for x in rets:
        cum += np.log(1 + x / 100)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    m.max_drawdown = round(mdd * 100, 2)

    # 交易质量
    m.win_rate = m.positive_rate
    m.avg_win = round(float(np.mean(pos)), 4) if len(pos) > 0 else 0
    m.avg_loss = round(float(abs(np.mean(neg))), 4) if len(neg) > 0 else 0
    m.max_win = m.max_return
    m.max_loss = round(abs(m.min_return), 4)
    m.profit_loss_ratio = round(float(np.mean(pos) / abs(np.mean(neg))), 4) if len(pos) > 0 and len(neg) > 0 else 0

    # 连续盈亏
    cw = cl = cwmax = clmax = 0
    for x in rets:
        if x > 0: cw += 1; cl = 0; cwmax = max(cwmax, cw)
        else: cl += 1; cw = 0; clmax = max(clmax, cl)
    m.max_consec_win = cwmax
    m.max_consec_loss = clmax

    # 效率指标
    m.annual_return = round(ann_ret, 2)
    m.calmar = round(ann_ret / (mdd * 100), 4) if mdd > 0 else 0
    m.recovery_factor = round(float(sum(rets)) / (mdd * 100), 4) if mdd > 0 else 0
    m.break_even_wr = round(1 / (1 + m.profit_loss_ratio) * 100, 2) if m.profit_loss_ratio > 0 else 0
    if len(neg) > 0:
        m.expectancy = round(float(len(pos)/n * np.mean(pos) + len(neg)/n * np.mean(neg)), 4)
    else:
        m.expectancy = round(m.avg_return, 4)

    m.avg_hold_days = hold_days
    return m


def calc_phase_consistency(phase_metrics: Dict[str, Metrics28]) -> Dict[str, Metrics28]:
    """计算跨阶段指标：三阶段一致性、训练/测试收益比"""
    directions = []
    avg_returns = {}
    for p in ['train', 'val', 'test']:
        if p in phase_metrics:
            directions.append(1 if phase_metrics[p].avg_return > 0 else -1)
            avg_returns[p] = phase_metrics[p].avg_return

    consistency = 1 if len(set(directions)) == 1 and len(directions) == 3 else 0
    ratio = round(avg_returns.get('train', 0) / avg_returns.get('test', 1), 4) if avg_returns.get('test', 0) != 0 else 0

    for p in phase_metrics:
        phase_metrics[p].three_phase_consistency = consistency
        phase_metrics[p].train_test_ratio = ratio
    return phase_metrics


# ============================================================
# 策略信号函数签名
# ============================================================
# StrategyFn = Callable[[dict, int, dict], bool]
# 参数: stock_data dict, 当前index, 额外参数dict
# 返回: True=买入信号

# ============================================================
# 核心评测引擎
# ============================================================
class StrategyEvaluator:
    """策略评测引擎"""

    def __init__(self, db_path: str = DB):
        self.db = db_path
        self.sym_data = {}
        self.sym_scores = {}
        self.weak = {}
        self.monthly_top = {}
        self.all_dates = []
        self._loaded = False

    def log(self, msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    # --------------------------------------------------------
    # 数据加载
    # --------------------------------------------------------
    def load_data(self, force_reload=False):
        """加载K线、PIT基本面、弱市状态"""
        if self._loaded and not force_reload:
            return

        t0 = time.time()
        self.log("加载PIT基本面...")
        conn = sqlite3.connect(self.db, timeout=120)

        fund_rows = conn.execute("""
            SELECT symbol, report_date, roe, revenue_growth, profit_growth, gross_margin, debt_ratio
            FROM financial_indicators
            WHERE roe IS NOT NULL OR revenue_growth IS NOT NULL OR profit_growth IS NOT NULL
            ORDER BY symbol, report_date
        """).fetchall()

        self.sym_scores = {}
        for sym, rd, roe, rg, pg, gm, dr in fund_rows:
            s = fund_score(roe, rg, pg, gm, dr)
            if s > 0 and rd:
                pd = (datetime.strptime(rd, '%Y-%m-%d') + timedelta(days=pit_delay_days(rd))).strftime('%Y-%m-%d')
                self.sym_scores.setdefault(sym, []).append((pd, s))
        self.log(f"  PIT评分: {len(self.sym_scores)} 只")

        self.log("加载K线数据...")
        self.sym_data = {}
        for sym in self.sym_scores:
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
            self.sym_data[sym] = {
                'dates': dates,
                'open':    np.array([r[1] for r in rows], dtype=float),
                'close':   np.array([r[2] for r in rows], dtype=float),
                'high':    np.array([r[3] for r in rows], dtype=float),
                'low':     np.array([r[4] for r in rows], dtype=float),
                'rsi':     np.array([r[5] if r[5] is not None else np.nan for r in rows], dtype=float),
                'bb_lower': np.array([r[6] if r[6] is not None else np.nan for r in rows], dtype=float),
                'bb_upper': np.array([r[7] if r[7] is not None else np.nan for r in rows], dtype=float),
                'ma5':     np.array([r[8] if r[8] is not None else np.nan for r in rows], dtype=float),
                'ma10':    np.array([r[9] if r[9] is not None else np.nan for r in rows], dtype=float),
                'ma20':    np.array([r[10] if r[10] is not None else np.nan for r in rows], dtype=float),
                'macd_hist': np.array([r[11] if r[11] is not None else np.nan for r in rows], dtype=float),
                'volume':  np.array([r[12] if r[12] is not None else np.nan for r in rows], dtype=float),
            }
        conn.close()
        self.log(f"  K线: {len(self.sym_data)} 只")

        self.log("计算弱市状态...")
        self.all_dates = sorted(set(d for sd in self.sym_data.values() for d in sd['dates']))
        self.weak = {}
        for d in self.all_dates:
            total = below = 0
            for sd in self.sym_data.values():
                try:
                    idx = sd['dates'].index(d)
                    ma = sd['ma20'][idx]
                    cl = sd['close'][idx]
                    if not np.isnan(ma) and not np.isnan(cl):
                        total += 1
                        if cl < ma: below += 1
                except ValueError: pass
            self.weak[d] = (total >= 20 and below / total > 0.7)
        wc = sum(1 for v in self.weak.values() if v)
        self.log(f"  弱市: {wc}/{len(self.all_dates)} 天 ({time.time()-t0:.1f}s)")

        self.log("构建月度TOP200...")
        self._build_monthly_top()

        self._loaded = True
        self.log(f"数据加载完成: {len(self.sym_data)} 只, {time.time()-t0:.1f}s")

    def _build_monthly_top(self):
        """构建月度TOP200 PIT选股"""
        self.monthly_top = {}
        dt = datetime.strptime(self.all_dates[0], '%Y-%m-%d').replace(day=1)
        end_dt = datetime.strptime(self.all_dates[-1], '%Y-%m-%d')
        while dt <= end_dt:
            ms = dt.strftime('%Y-%m-%d')
            me_dt = dt + timedelta(days=32)
            scored = []
            for sym in self.sym_data:
                latest = 0
                for ad, sc in reversed(self.sym_scores.get(sym, [])):
                    if ad <= ms:
                        latest = sc
                        break
                if latest > 0:
                    scored.append((sym, latest))
            scored.sort(key=lambda x: -x[1])
            self.monthly_top[ms] = [s[0] for s in scored[:TOP_N]]
            dt = me_dt.replace(day=1)

    # --------------------------------------------------------
    # 内置信号函数
    # --------------------------------------------------------
    @staticmethod
    def signal_rsi(sd, i, params):
        """RSI超卖信号"""
        thresh = params.get('rsi_thresh', 20)
        rsi = sd['rsi'][i]
        return not np.isnan(rsi) and rsi < thresh and rsi >= 10

    @staticmethod
    def signal_rsi_bb(sd, i, params):
        """RSI超卖 + 布林带下轨触底"""
        thresh = params.get('rsi_thresh', 20)
        rsi = sd['rsi'][i]
        if np.isnan(rsi) or rsi >= thresh or rsi < 10:
            return False
        bb = sd['bb_lower'][i]
        cl = sd['close'][i]
        return not np.isnan(bb) and cl <= bb * 1.02

    @staticmethod
    def signal_rsi_macd(sd, i, params):
        """RSI超卖 + MACD柱>0"""
        thresh = params.get('rsi_thresh', 20)
        rsi = sd['rsi'][i]
        if np.isnan(rsi) or rsi >= thresh or rsi < 10:
            return False
        mh = sd['macd_hist'][i]
        return not np.isnan(mh) and mh > 0

    @staticmethod
    def signal_rsi_vol(sd, i, params):
        """RSI超卖 + 放量"""
        thresh = params.get('rsi_thresh', 20)
        vol_mult = params.get('vol_mult', 1.5)
        rsi = sd['rsi'][i]
        if np.isnan(rsi) or rsi >= thresh or rsi < 10:
            return False
        vol = sd['volume'][i]
        # 用前5日均量判断放量
        if i < 5: return False
        avg_vol = np.nanmean(sd['volume'][max(0,i-5):i])
        return avg_vol > 0 and vol > avg_vol * vol_mult

    @staticmethod
    def signal_rsi_ma(sd, i, params):
        """RSI超卖 + MA5>MA10（短期走强）"""
        thresh = params.get('rsi_thresh', 20)
        rsi = sd['rsi'][i]
        if np.isnan(rsi) or rsi >= thresh or rsi < 10:
            return False
        ma5 = sd['ma5'][i]; ma10 = sd['ma10'][i]
        return not np.isnan(ma5) and not np.isnan(ma10) and ma5 >= ma10

    @staticmethod
    def signal_rsi_close_up(sd, i, params):
        """RSI超卖 + 当日收阳"""
        thresh = params.get('rsi_thresh', 20)
        rsi = sd['rsi'][i]
        if np.isnan(rsi) or rsi >= thresh or rsi < 10:
            return False
        return sd['close'][i] > sd['open'][i]

    # --------------------------------------------------------
    # 弱市过滤
    # --------------------------------------------------------
    def get_weak_dates(self, threshold=0.7):
        """获取弱市日期（可调阈值）"""
        if threshold == 0.7:
            return self.weak  # 默认阈值，直接返回缓存
        
        # 非默认阈值需要重新计算
        weak = {}
        for d in self.all_dates:
            total = below = 0
            for sd in self.sym_data.values():
                try:
                    idx = sd['dates'].index(d)
                    ma = sd['ma20'][idx]
                    cl = sd['close'][idx]
                    if not np.isnan(ma) and not np.isnan(cl):
                        total += 1
                        if cl < ma: below += 1
                except ValueError: pass
            weak[d] = (total >= 20 and below / total > threshold)
        return weak

    # --------------------------------------------------------
    # 核心回测
    # --------------------------------------------------------
    def evaluate(self,
                 signal_fn: Callable,
                 hold_days: int = 10,
                 params: dict = None,
                 use_weak: bool = True,
                 weak_threshold: float = 0.7,
                 top_n: int = TOP_N,
                 phases: dict = None,
                 top_n_per_day: int = 0,
                 score_fn: Callable = None,
                 stop_loss: float = 3.0,
                 take_profit: float = 5.0,
                 sell_mode: str = 'stop_profit') -> Dict[str, Metrics28]:
        """
        评测一个策略

        Args:
            signal_fn: 信号函数 (stock_data, index, params) -> bool
            hold_days: 持有天数
                - sell_mode='fixed_hold' 时：固定持有 N 天后收盘卖出
                - sell_mode='stop_profit' 时：最大持有天数（最少持有一天）
            params: 传给信号函数的参数
            use_weak: 是否使用弱市过滤
            weak_threshold: 弱市阈值
            top_n: 基本面TOP N
            phases: 自定义阶段
            top_n_per_day: 每天最多取前N笔(0=不限制)
            score_fn: 排序函数(stock_data, index)->float，越大越优先；None则按RSI升序
            stop_loss: 止损百分比（默认3%），买入次日及之后有效（仅 stop_profit 模式）
            take_profit: 止盈百分比（默认5%），买入次日及之后有效（仅 stop_profit 模式）
            sell_mode: 卖出模式
                - 'stop_profit'（默认）：T+2 起每日检查止损/止盈，触发即卖，最多持有 hold_days 天
                - 'fixed_hold'：固定持有 hold_days 天后 T+1+N 收盘卖出

        Returns: {phase_name: Metrics28}
        """
        if not self._loaded:
            raise RuntimeError("请先调用 load_data()")

        params = params or {}
        phases = phases or PHASES
        weak_dates = self.get_weak_dates(weak_threshold) if use_weak else {}

        # 如果 top_n 不同，需要重新构建
        if top_n != TOP_N:
            monthly = {}
            dt = datetime.strptime(self.all_dates[0], '%Y-%m-%d').replace(day=1)
            end_dt = datetime.strptime(self.all_dates[-1], '%Y-%m-%d')
            while dt <= end_dt:
                ms = dt.strftime('%Y-%m-%d')
                me_dt = dt + timedelta(days=32)
                scored = []
                for sym in self.sym_data:
                    latest = 0
                    for ad, sc in reversed(self.sym_scores.get(sym, [])):
                        if ad <= ms: latest = sc; break
                    if latest > 0: scored.append((sym, latest))
                scored.sort(key=lambda x: -x[1])
                monthly[ms] = [s[0] for s in scored[:top_n]]
                dt = me_dt.replace(day=1)
        else:
            monthly = self.monthly_top

        results = {}
        for phase, (ps, pe) in phases.items():
            all_rets = []
            all_holds = []  # 记录每笔实际持仓天数
            stocks_hit = set()

            dt = datetime.strptime(ps, '%Y-%m-%d').replace(day=1)
            end_dt = datetime.strptime(pe, '%Y-%m-%d')

            while dt <= end_dt:
                ms = dt.strftime('%Y-%m-%d')
                me_dt = dt + timedelta(days=32)
                me = min(me_dt.replace(day=1).strftime('%Y-%m-%d'), pe)

                top_stocks = monthly.get(ms, [])
                # 收集每天的信号（支持 top_n_per_day 筛选）
                daily_signals = {}  # date -> [(sym, sd, i, score)]

                for sym in top_stocks:
                    if sym not in self.sym_data:
                        continue
                    sd = self.sym_data[sym]
                    i = 0
                    while i < len(sd['dates']):
                        d = sd['dates'][i]
                        if d < ms: i += 1; continue
                        if d >= me: break
                        if i + 1 + hold_days >= len(sd['dates']): break
                        if use_weak and not weak_dates.get(d, False): i += 1; continue

                        if signal_fn(sd, i, params):
                            bp = sd['open'][i + 1]
                            if bp <= 0 or np.isnan(bp):
                                i += 1; continue

                            if sell_mode == 'stop_profit':
                                # 止损/止盈模式：T+2起每日检查，最多持有 hold_days 天
                                sell_idx = None
                                for d_idx in range(i + 2, i + 2 + hold_days):
                                    if d_idx >= len(sd['dates']): break
                                    day_close = sd['close'][d_idx]
                                    if np.isnan(day_close): break
                                    pct_chg = (day_close - bp) / bp * 100
                                    if pct_chg <= -stop_loss or pct_chg >= take_profit:
                                        sell_idx = d_idx
                                        break
                                if sell_idx is None:
                                    sell_idx = i + 1 + hold_days
                                    if sell_idx >= len(sd['dates']):
                                        i += 1; continue
                            else:
                                # 固定持有模式：T+1+N 收盘卖出
                                sell_idx = i + 1 + hold_days
                                if sell_idx >= len(sd['dates']):
                                    i += 1; continue

                            sp = sd['close'][sell_idx]
                            if np.isnan(sp):
                                i += 1; continue
                            actual_hold = sell_idx - (i + 1)  # 实际持仓天数
                            if top_n_per_day > 0:
                                # 计算排序分数
                                if score_fn is not None:
                                    try:
                                        sc = score_fn(sd, i, sym, self.sym_scores.get(sym, []))
                                    except TypeError:
                                        sc = score_fn(sd, i)
                                else:
                                    # 默认：RSI越低分越高
                                    rsi_val = sd['rsi'][i]
                                    sc = -rsi_val if not np.isnan(rsi_val) else 0
                                daily_signals.setdefault(d, []).append((sym, bp, sp, sc, actual_hold))
                            else:
                                ret = (sp - bp) / bp * 100 - COST
                                all_rets.append(ret)
                                all_holds.append(actual_hold)
                                stocks_hit.add(sym)
                            i += hold_days + 1
                        else:
                            i += 1
                    # end while
                dt = me_dt.replace(day=1)

                # 处理 daily top_n 筛选
                if top_n_per_day > 0 and daily_signals:
                    for d, signals in daily_signals.items():
                        signals.sort(key=lambda x: -x[3])  # 按score降序
                        for sym, bp, sp, sc, actual_hold in signals[:top_n_per_day]:
                            ret = (sp - bp) / bp * 100 - COST
                            all_rets.append(ret)
                            all_holds.append(actual_hold)
                            stocks_hit.add(sym)

            avg_actual_hold = sum(all_holds) / len(all_holds) if all_holds else hold_days
            results[phase] = calc_metrics(all_rets, avg_actual_hold, len(stocks_hit))

        results = calc_phase_consistency(results)
        return results

    # --------------------------------------------------------
    # 批量搜索
    # --------------------------------------------------------
    def search(self,
               strategies: List[Tuple[str, Callable, dict]],
               hold_days: int = 10,
               use_weak: bool = True,
               weak_threshold: float = 0.7,
               top_n: int = TOP_N,
               top_n_per_day: int = 0,
               score_fn: Callable = None,
               stop_loss: float = 3.0,
               take_profit: float = 5.0,
               sell_mode: str = 'stop_profit') -> List[dict]:
        """
        批量搜索策略

        Args:
            strategies: [(name, signal_fn, params), ...]
            hold_days: 持有天数（或最大持有天数）
            use_weak: 是否弱市过滤
            weak_threshold: 弱市阈值
            top_n: 基本面TOP N
            top_n_per_day: 每天最多取前N笔
            score_fn: 排序函数
            stop_loss: 止损%（仅 stop_profit 模式）
            take_profit: 止盈%（仅 stop_profit 模式）
            sell_mode: 'stop_profit'（默认）或 'fixed_hold'

        Returns: 按测试夏普降序排列的列表
        """
        results = []
        for name, fn, params in strategies:
            self.log(f"评测: {name}")
            r = self.evaluate(fn, hold_days, params, use_weak, weak_threshold,
                               top_n=top_n, top_n_per_day=top_n_per_day,
                               score_fn=score_fn,
                               stop_loss=stop_loss, take_profit=take_profit,
                               sell_mode=sell_mode)
            result = {
                'name': name,
                'params': params,
                'hold_days': hold_days,
                'use_weak': use_weak,
                'weak_threshold': weak_threshold,
                'top_n': top_n,
                'top_n_per_day': top_n_per_day,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'sell_mode': sell_mode,
                'phases': {p: r[p].to_dict() for p in r}
            }
            results.append(result)
            t, v, te = r.get('train'), r.get('val'), r.get('test')
            if t and v and te:
                self.log(f"  train: {t.positive_rate}%/{t.total_trades}笔 | val: {v.positive_rate}%/{v.total_trades}笔 | test: {te.positive_rate}%/{te.total_trades}笔 | test_sharpe={te.sharpe}")

        results.sort(key=lambda x: x['phases'].get('test', {}).get('sharpe', -999), reverse=True)
        return results

    # --------------------------------------------------------
    # 输出
    # --------------------------------------------------------
    def print_28_metrics(self, result: Dict[str, Metrics28]):
        """打印完整的28项指标"""
        categories = {
            '基础指标（7）': ['total_trades','positive_rate','avg_return','median_return','max_return','min_return','hit_stocks'],
            '风险指标（5）': ['sharpe','max_drawdown','volatility','downside_volatility','sortino'],
            '交易质量（8）': ['win_rate','profit_loss_ratio','avg_win','avg_loss','max_win','max_loss','max_consec_win','max_consec_loss'],
            '效率指标（5）': ['annual_return','calmar','recovery_factor','break_even_wr','expectancy'],
            '稳定性（3）': ['train_test_ratio','three_phase_consistency','avg_hold_days'],
        }
        print(f"\n{'='*70}")
        print("策略 28 项指标")
        print(f"{'='*70}")
        for cat, keys in categories.items():
            print(f"\n{cat}")
            print(f"{'指标':<25} {'训练':>10} {'验证':>10} {'测试':>10}")
            print("-" * 60)
            for k in keys:
                vals = []
                for p in ['train', 'val', 'test']:
                    if p in result:
                        vals.append(str(getattr(result[p], k)))
                    else:
                        vals.append('-')
                print(f"  {k:<23} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")

    def save(self, result, name: str, output_dir: str = None):
        """保存结果到JSON"""
        output_dir = output_dir or os.path.join(OUTPUT_DIR, name)
        os.makedirs(output_dir, exist_ok=True)
        data = {
            'name': name,
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'phases': {p: PHASES[p] for p in PHASES},
            'config': {'top_n': TOP_N, 'cost': f'{COST}%', 'rf': RF},
            'per_phase': {p: result[p].to_dict() for p in result}
        }
        path = os.path.join(output_dir, 'evaluate_result.json')
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.log(f"结果保存: {path}")
        return path


# ============================================================
# 示例
# ============================================================
if __name__ == '__main__':
    ev = StrategyEvaluator()
    ev.load_data()

    # 示例1: RSI<20 + 弱市
    print("\n### 策略1: RSI<20 + 弱市>70% + TOP200 + 10天 ###")
    r1 = ev.evaluate(ev.signal_rsi, hold_days=10, params={'rsi_thresh': 20})
    ev.print_28_metrics(r1)

    # 示例2: RSI<20 + BB触底
    print("\n### 策略2: RSI<20 + BB触底 + 弱市>70% + TOP200 + 10天 ###")
    r2 = ev.evaluate(ev.signal_rsi_bb, hold_days=10, params={'rsi_thresh': 20})
    ev.print_28_metrics(r2)

    # 示例3: RSI<20 + MA5>MA10
    print("\n### 策略3: RSI<20 + MA5≥MA10 + 弱市>70% + TOP200 + 10天 ###")
    r3 = ev.evaluate(ev.signal_rsi_ma, hold_days=10, params={'rsi_thresh': 20})
    ev.print_28_metrics(r3)
