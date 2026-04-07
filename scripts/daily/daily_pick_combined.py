#!/usr/bin/env python3
"""
每日选股 - 策略组合包
包含三个策略：
  1. Fstop3_pt5 v10：RSI<18 + BB触底 + 放量1.5x + 弱市50%
  2. BB1.00：RSI<20 + BB<=1.00 + 弱市70% + 7天持有
  3. BB1.02+KDJ Oversold：RSI<20 + BB<=1.02 + KDJ超卖 + 弱市70% + TOP500
用法: python3 daily_pick_combined.py [--date 2026-04-02] [--push]
"""
import sqlite3, json, subprocess, os, argparse, time, requests
from datetime import datetime, timedelta
from collections import defaultdict
import sys

# 动态加载策略一致性校验（推送前查评估结果）
def load_strategy_metrics():
    """返回策略key->显示字符串的字典，无评估文件时返回None走降级"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    checker_path = os.path.join(script_dir, 'check_strategy_consistency.py')
    cfg_dir = os.path.join(script_dir, '..', 'configs', 'strategy')
    results_dir = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'

    # 直接读取评估JSON（不依赖子进程）
    metrics = {}

    # Fstop3（强制对齐最新 eval 真源）
    r_file = os.path.join(results_dir, 'fstop3_v10_framework_eval.json')
    if os.path.exists(r_file):
        try:
            with open(r_file, 'r', encoding='utf-8') as f:
                r = json.load(f)
            rs = r.get('results', {})
            train_m = rs.get('train', {}).get('metrics', {})
            val_m = rs.get('val', {}).get('metrics', {})
            test_m = rs.get('test', {}).get('metrics', {})
            has_core = all(
                isinstance(m, dict) and ('positive_rate' in m) and ('sharpe' in m) and ('total_trades' in m)
                for m in [train_m, val_m, test_m]
            )
            if has_core:
                metrics['Fstop3_pt5_v10'] = (
                    f"三阶段胜率 {train_m.get('positive_rate',0):.1f}%/"
                    f"{val_m.get('positive_rate',0):.1f}%/"
                    f"{test_m.get('positive_rate',0):.1f}% | "
                    f"夏普 {train_m.get('sharpe',0):.2f}/"
                    f"{val_m.get('sharpe',0):.2f}/"
                    f"{test_m.get('sharpe',0):.2f} | "
                    f"笔数 {int(train_m.get('total_trades',0))}/"
                    f"{int(val_m.get('total_trades',0))}/"
                    f"{int(test_m.get('total_trades',0))}"
                )
            else:
                print("[Fstop3指标加载失败] eval 缺少核心字段，已降级⚠️", flush=True)
        except Exception as e:
            print(f"[Fstop3指标加载失败] {e}", flush=True)
            pass

    # BB1.00
    r_file = os.path.join(results_dir, 'bb100_full_28metrics.json')
    if os.path.exists(r_file):
        try:
            r = json.load(open(r_file))
            pp = r.get('per_phase', {})
            tr, va, te = pp.get('train', {}), pp.get('val', {}), pp.get('test', {})
            if te:
                n = te.get('total_trades', 0)
                metrics['BB1.00'] = (
                    f"三阶段胜率 {tr.get('positive_rate',0):.1f}%/{va.get('positive_rate',0):.1f}%/"
                    f"{te.get('positive_rate',0):.1f}% | "
                    f"夏普 {tr.get('sharpe',0):.2f}/{va.get('sharpe',0):.2f}/{te.get('sharpe',0):.2f}"
                    + (f" | 测试{n}笔" if n else "")
                )
        except Exception as e:
            print(f"[BB1.00指标加载失败] {e}", flush=True)
            pass

    # BB1.02+KDJ（从weak_filter_compare.json，取BB1.02_H7_TOP500_weakwidth70）
    r_file = os.path.join(results_dir, 'weak_filter_compare.json')
    if os.path.exists(r_file):
        try:
            r = json.load(open(r_file))
            entry = next((v for k, v in r.items()
                          if 'BB1.02_H7_TOP500' in k and 'weakwidth70' in k), None)
            if entry:
                pp = entry.get('results', {})
                tr, va, te = pp.get('train', {}).get('metrics', {}), \
                             pp.get('val', {}).get('metrics', {}), \
                             pp.get('test', {}).get('metrics', {})
                if te:
                    n = te.get('total_trades', 0)
                    metrics['BB1.02_KDJ'] = (
                        f"三阶段胜率 {tr.get('positive_rate',0):.1f}%/{va.get('positive_rate',0):.1f}%/"
                        f"{te.get('positive_rate',0):.1f}% | "
                        f"夏普 {tr.get('sharpe',0):.2f}/{va.get('sharpe',0):.2f}/{te.get('sharpe',0):.2f}"
                        + (f" | 测试{n}笔" if n else "")
                    )
        except Exception as e:
            print(f"[BB1.02_KDJ指标加载失败] {e}", flush=True)
            pass

    return metrics

def load_strategy_qualified():
    """按统一标准判断策略是否合格：三阶段正收益率>55% 且 测试笔数>=30"""
    results_dir = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'
    q = {}

    # Fstop3
    try:
        r = json.load(open(os.path.join(results_dir, 'fstop3_v10_framework_eval.json')))
        tr = r['results']['train']['metrics']; va = r['results']['val']['metrics']; te = r['results']['test']['metrics']
        q['Fstop3_pt5_v10'] = (tr.get('positive_rate', 0) > 55 and va.get('positive_rate', 0) > 55 and te.get('positive_rate', 0) > 55 and te.get('total_trades', 0) >= 30)
    except Exception:
        q['Fstop3_pt5_v10'] = False

    # BB1.00
    try:
        r = json.load(open(os.path.join(results_dir, 'bb100_full_28metrics.json')))
        pp = r.get('per_phase', {})
        tr, va, te = pp.get('train', {}), pp.get('val', {}), pp.get('test', {})
        q['BB1.00'] = (tr.get('positive_rate', 0) > 55 and va.get('positive_rate', 0) > 55 and te.get('positive_rate', 0) > 55 and te.get('total_trades', 0) >= 30)
    except Exception:
        q['BB1.00'] = False

    # BB1.02_KDJ
    try:
        r = json.load(open(os.path.join(results_dir, 'weak_filter_compare.json')))
        entry = next((v for k, v in r.items() if 'BB1.02_H7_TOP500' in k and 'weakwidth70' in k), None)
        pp = entry.get('results', {}) if entry else {}
        tr = pp.get('train', {}).get('metrics', {})
        va = pp.get('val', {}).get('metrics', {})
        te = pp.get('test', {}).get('metrics', {})
        q['BB1.02_KDJ'] = (tr.get('positive_rate', 0) > 55 and va.get('positive_rate', 0) > 55 and te.get('positive_rate', 0) > 55 and te.get('total_trades', 0) >= 30)
    except Exception:
        q['BB1.02_KDJ'] = False

    return q

STRATEGY_METRICS = load_strategy_metrics()
STRATEGY_QUALIFIED = load_strategy_qualified()
qualified_count = sum(1 for v in STRATEGY_QUALIFIED.values() if v)
print(f"[策略指标加载] 成功 {len(STRATEGY_METRICS)}个策略 | 合格 {qualified_count}个")

parser = argparse.ArgumentParser()
parser.add_argument('--date', default=None)
parser.add_argument('--push', action='store_true')
parser.add_argument('--also-group', action='store_true', help='同时推送到群')
parser.add_argument('--wait', action='store_true')
args = parser.parse_args()

DB_PATH = os.environ.get('STOCK_DB', '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db')
READY_FLAG = '/tmp/stock_data_ready.flag'
TODAY = datetime.now().strftime('%Y-%m-%d')
MIN_STOCKS = 4000
VALID_LOOKBACK_DAYS = 10
STRATEGY_VERSION = "combined-v1.1"

db = sqlite3.connect(DB_PATH)
db.execute('PRAGMA journal_mode=WAL')

def get_latest_valid_trade_date(db, min_stocks=MIN_STOCKS, lookback_days=VALID_LOOKBACK_DAYS):
    row = db.execute(
        f"""
        SELECT trade_date, COUNT(*) AS cnt
        FROM kline_daily
        WHERE trade_date >= date('{TODAY}', '-{lookback_days} day')
        GROUP BY trade_date
        HAVING cnt >= {min_stocks}
        ORDER BY trade_date DESC
        LIMIT 1
        """
    ).fetchone()
    return row[0] if row else None


# === 确定日期 ===
latest = args.date or TODAY
if args.wait and not args.date:
    waited = 0
    while waited < 180:
        ready_date = None
        try:
            with open(READY_FLAG) as f:
                ready_date = f.read().strip()
        except FileNotFoundError:
            pass

        if ready_date:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 数据就绪: {ready_date}")
            latest = ready_date
            break

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 等待数据... ({waited}s)")
        time.sleep(60)
        waited += 1
    else:
        # wait超时时，自动回退到最近有效交易日
        fallback = get_latest_valid_trade_date(db)
        if fallback:
            print(f"等待超时，回退到最近有效交易日: {fallback}")
            latest = fallback
        else:
            print("等待超时且无有效交易日，跳过")
            db.close()
            exit(1)

    db.close()
    db = sqlite3.connect(DB_PATH)
    db.execute('PRAGMA journal_mode=WAL')

# 若未指定日期且今天数据不足，自动回退到最近有效交易日
if not args.date:
    latest_total = db.execute("SELECT COUNT(*) FROM kline_daily WHERE trade_date=?", (latest,)).fetchone()[0]
    if latest_total < MIN_STOCKS:
        fallback = get_latest_valid_trade_date(db)
        if fallback and fallback != latest:
            print(f"当前日期数据不足({latest_total}只)，自动回退到: {fallback}")
            latest = fallback

# === 数据校验 ===
def get_latest_trade_date(db):
    row = db.execute("SELECT MAX(trade_date) FROM kline_daily").fetchone()
    return row[0] if row and row[0] else None

def get_trade_day_gap(db, from_date, to_date):
    if not from_date or not to_date:
        return None
    row = db.execute(
        """
        SELECT COUNT(DISTINCT trade_date)
        FROM kline_daily
        WHERE trade_date > ? AND trade_date <= ?
        """,
        (from_date, to_date)
    ).fetchone()
    return row[0] if row else None

def validate(db, date):
    errors = []
    total = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}'").fetchone()[0]
    if total < MIN_STOCKS:
        errors.append(f"K线不足: {total}只")
    has_rsi = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}' AND rsi14 IS NOT NULL").fetchone()[0]
    has_bb = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}' AND boll_lower IS NOT NULL").fetchone()[0]
    if has_rsi < total * 0.8:
        errors.append(f"RSI未计算: {has_rsi}/{total}")
    if has_bb < total * 0.8:
        errors.append(f"BB未计算: {has_bb}/{total}")
    return errors, {"total": total, "rsi": has_rsi, "bb": has_bb}

errors, stats = validate(db, latest)
if errors:
    print(f"数据校验失败: {errors}")
    db.close()
    exit(1)
print(f"数据校验通过 ({latest}): K线{stats['total']} RSI{stats['rsi']} BB{stats['bb']}")

latest_trade = get_latest_trade_date(db)
stale_trade_days = get_trade_day_gap(db, latest, latest_trade) if latest_trade else None
if stale_trade_days and stale_trade_days > 0:
    print(f"⚠️ 数据滞后: 目标日 {latest}，数据库最新交易日 {latest_trade}，差 {stale_trade_days} 个交易日")

# === 市场宽度 ===
m = db.execute(f"""
    SELECT COUNT(*) total,
        SUM(CASE WHEN ma20 IS NOT NULL THEN 1 ELSE 0 END) has_ma20,
        SUM(CASE WHEN ma20 IS NOT NULL AND close<ma20 THEN 1 ELSE 0 END) below
    FROM kline_daily WHERE trade_date='{latest}'
""").fetchone()
total_mkt = m[1] or 1
weak_pct = (m[2] or 0) / total_mkt * 100
market_ok_50 = weak_pct >= 50
market_ok_70 = weak_pct >= 70
print(f"大盘弱市: {weak_pct:.1f}%个股在MA20下方（需50%:{market_ok_50} | 需70%:{market_ok_70}）")

# === 基本面打分 ===
fund_rows = db.execute("""
    SELECT f.symbol, f.roe, f.revenue_growth, f.profit_growth, f.gross_margin, f.debt_ratio
    FROM financial_indicators f
    INNER JOIN (SELECT symbol, MAX(report_date) d FROM financial_indicators GROUP BY symbol) t
    ON f.symbol=t.symbol AND f.report_date=t.d
""").fetchall()

def score_fund(r):
    roe=r[1] or 0; rev_g=r[2] or 0; profit_g=r[3] or 0
    gross=r[4] or 0; debt=r[5] if r[5] is not None else 100
    return round(
        min(max(roe/30*30,0),30) +
        min(max((rev_g+20)/60*20,0),20) +
        min(max((profit_g+20)/60*20,0),20) +
        min(max(gross/60*15,0),15) +
        min(max((100-debt)/100*15,0),15), 1)

fund = {r[0]: score_fund(r) for r in fund_rows}
top300 = {sym for sym,_ in sorted(fund.items(), key=lambda x:-x[1])[:300]}
print(f"基本面TOP300: {len(top300)} 只")

# === 共用成交量数据（30天窗口）===
cutoff = (datetime.strptime(latest, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
vol_rows = db.execute(f"""
    SELECT symbol, trade_date, volume FROM kline_daily
    WHERE trade_date='{latest}'
       OR (trade_date <= '{latest}' AND trade_date >= '{cutoff}')
""").fetchall()

vol_cache = defaultdict(list)
for sym, td, vol in vol_rows:
    if td == latest:
        vol_cache[sym].insert(0, vol)  # 今天放最前
    elif len(vol_cache[sym]) < 4:
        vol_cache[sym].append(vol)

def vol_ratio(sym):
    vols = vol_cache.get(sym, [])
    if len(vols) < 2: return 0
    return vols[0] / (sum(vols)/len(vols)) if sum(vols)>0 else 0

def recalc_kdj_if_needed(db, date):
    """若当日KDJ全为空，则批量补算"""
    c = db.execute("SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND kdj_k IS NOT NULL", (date,)).fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM kline_daily WHERE trade_date=?", (date,)).fetchone()[0]
    if c >= total * 0.8:  # 已有80%以上，跳过
        return
    import statistics
    def calc_kdj(symbol, trade_date, n=9):
        rows = db.execute("""
            SELECT close, high, low FROM kline_daily 
            WHERE symbol=? AND trade_date<=?
            ORDER BY trade_date DESC LIMIT ?
        """, (symbol, trade_date, n+20)).fetchall()
        if len(rows) < n + 1:
            return None, None, None
        rsv_data = []
        for i in range(n):
            close = rows[n-1-i][0]
            high = max(rows[n-1-i-j][1] for j in range(n) if n-1-i-j >= 0)
            low = min(rows[n-1-i-j][2] for j in range(n) if n-1-i-j >= 0)
            rsv = 50 if high == low else (close - low) / (high - low) * 100
            rsv_data.append(rsv)
        k_prev, d_prev = 50.0, 50.0
        for rsv in rsv_data:
            k_prev = (2/3) * k_prev + (1/3) * rsv
            d_prev = (2/3) * d_prev + (1/3) * k_prev
        j = 3 * k_prev - 2 * d_prev
        return round(k_prev, 2), round(d_prev, 2), round(j, 2)
    missing = [r[0] for r in db.execute(
        "SELECT symbol FROM kline_daily WHERE trade_date=? AND kdj_k IS NULL", (date,)).fetchall()]
    updated = 0
    for sym in missing:
        k, d, j = calc_kdj(sym, date)
        if k is not None:
            db.execute("UPDATE kline_daily SET kdj_k=?, kdj_d=?, kdj_j=? WHERE symbol=? AND trade_date=?", 
                        (k, d, j, sym, date))
            updated += 1
    db.commit()
    print(f"  KDJ补算: {updated}/{len(missing)} 只")

# 先补算KDJ（如需要）
print("检查KDJ数据...")
recalc_kdj_if_needed(db, latest)

def run_strategy(name, rsi_thresh, bb_mult, weak_thresh, vol_required, topn, market_ok):
    """运行单个策略，返回候选列表"""
    cond_sql = f"rsi14 < {rsi_thresh} AND boll_lower IS NOT NULL AND close IS NOT NULL AND close <= boll_lower * {bb_mult}"
    if topn > 0:
        topn_syms = {sym for sym,_ in sorted(fund.items(), key=lambda x:-x[1])[:topn]}
        if topn_syms:
            placeholders = ','.join(f'"{s}"' for s in topn_syms)
            cond_sql += f" AND symbol IN ({placeholders})"

    candidates = db.execute(f"""
        SELECT symbol, close, rsi14, boll_lower FROM kline_daily
        WHERE trade_date='{latest}' AND {cond_sql}
        ORDER BY rsi14 ASC
    """).fetchall()

    if not candidates:
        return [], market_ok

    picks = []
    for sym, close, rsi, bb in candidates:
        if not market_ok:
            continue
        if vol_required:
            vr = vol_ratio(sym)
            if vr < 1.5:
                continue
            picks.append((sym, close, rsi, bb, vr, fund.get(sym, 0)))
        else:
            picks.append((sym, close, rsi, bb, 0, fund.get(sym, 0)))

    picks.sort(key=lambda x: x[2])
    return picks[:20], market_ok

# === 策略1: Fstop3_pt5 v10 ===
print(f"\n=== Fstop3_pt5 v10 ===")
if STRATEGY_QUALIFIED.get('Fstop3_pt5_v10', False):
    picks_v10, _ = run_strategy("Fstop3_pt5", 18, 1.0, 50, True, 0, market_ok_50)
    print(f"候选: {len(picks_v10)} 只")
    for p in picks_v10:
        print(f"  {p[0]} RSI={p[2]:.1f} close={p[1]:.2f} vol_ratio={p[4]:.2f}x")
else:
    picks_v10 = []
    print("策略未通过门槛，已跳过")

# === 策略2: BB1.00 ===
print(f"\n=== BB1.00 ===")
if STRATEGY_QUALIFIED.get('BB1.00', False):
    picks_b1, _ = run_strategy("BB1.00", 20, 1.00, 70, False, 300, market_ok_70)
    print(f"候选: {len(picks_b1)} 只")
    for p in picks_b1:
        print(f"  {p[0]} RSI={p[2]:.1f} close={p[1]:.2f}")
else:
    picks_b1 = []
    print("策略未通过门槛，已跳过")

# === 策略3: BB1.02 + KDJ Oversold ===
print(f"\n=== BB1.02+KDJ（TOP500 7天）===")
if STRATEGY_QUALIFIED.get('BB1.02_KDJ', False):
    # KDJ过滤：在SQL里直接用 (kdj_k < 20 OR kdj_j < 0)
    cond_sql_kdj = f"rsi14 < 20 AND boll_lower IS NOT NULL AND close IS NOT NULL AND close <= boll_lower * 1.02 AND (kdj_k < 20 OR kdj_j < 0)"
    top500_syms = {sym for sym,_ in sorted(fund.items(), key=lambda x:-x[1])[:500]}
    placeholders = ','.join(f'\"{s}\"' for s in top500_syms)
    cond_sql_kdj += f" AND symbol IN ({placeholders})"

    candidates_kdj = db.execute(f"""
        SELECT symbol, close, rsi14, boll_lower, kdj_k, kdj_j FROM kline_daily
        WHERE trade_date='{latest}' AND {cond_sql_kdj}
        ORDER BY rsi14 ASC
    """).fetchall()

    picks_kdj = []
    if market_ok_70:
        for sym, close, rsi, bb, k, j in candidates_kdj:
            picks_kdj.append((sym, close, rsi, bb, 0, fund.get(sym, 0)))
    picks_kdj.sort(key=lambda x: x[2])
    picks_kdj = picks_kdj[:20]
    print(f"候选: {len(picks_kdj)} 只")
    for p in picks_kdj:
        print(f"  {p[0]} RSI={p[2]:.1f} close={p[1]:.2f}")
else:
    picks_kdj = []
    print("策略未通过门槛，已跳过")

# === 历史记录 ===
HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'reports', 'daily_picks')
os.makedirs(HISTORY_DIR, exist_ok=True)
result_record = {
    "date": latest,
    "meta": {
        "strategy_version": STRATEGY_VERSION,
        "latest_trade_date": latest_trade,
        "stale_trade_days": stale_trade_days or 0
    },
    "strategies": {
        "Fstop3_pt5_v10": {"picks": [{"symbol":p[0],"close":p[1],"rsi":p[2],"bb":p[3],"vol_ratio":round(p[4],2),"fund_score":p[5]} for p in picks_v10]},
        "BB1.00": {"picks": [{"symbol":p[0],"close":p[1],"rsi":p[2],"bb":p[3],"fund_score":p[5]} for p in picks_b1]},
        "BB1.02_KDJ": {"picks": [{"symbol":p[0],"close":p[1],"rsi":p[2],"bb":p[3],"fund_score":p[5]} for p in picks_kdj]},
    },
    "market": {"weak_pct": round(weak_pct, 1), "market_ok_50": market_ok_50, "market_ok_70": market_ok_70}
}
history_file = os.path.join(HISTORY_DIR, f"{latest}.json")
with open(history_file, 'w', encoding='utf-8') as f:
    json.dump(result_record, f, ensure_ascii=False, indent=2)
print(f"\n历史记录已保存: {history_file}")

# === 推送飞书 ===
if not args.push:
    print("(--push 未指定，仅输出结果)")
    db.close()
    exit(0)

# 股票名称
stock_names = {}
try:
    import akshare as ak
    df = ak.stock_info_a_code_name()
    for _, row in df.iterrows():
        code = str(row['code'])
        sym = f'sh{code}' if code.startswith(('6','9')) else f'sz{code}'
        stock_names[sym] = row['name']
except:
    pass

def stock_name(sym):
    return stock_names.get(sym, sym)

def build_section(title, picks, cond_md, note_md, max_show=5, show_vol=False):
    """构建单个策略的卡片区域"""
    if picks:
        lines = []
        for p in picks[:max_show]:
            if show_vol and p[4] > 0:
                line = f"**{stock_name(p[0])}**({p[0][-6:]} 收{round(p[1],2)} RSI{round(p[2],1)} 放量{round(p[4],1)}x)"
            else:
                line = f"**{stock_name(p[0])}**({p[0][-6:]} 收{round(p[1],2)} RSI{round(p[2],1)})"
            lines.append(line)
        items_md = "\n".join(lines)
        count_md = f"共{len(picks)}只"
    else:
        items_md = "无候选"
        count_md = "0只"
    return [
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**{title}** {count_md}"}},
        {"tag": "div", "text": {"tag": "lark_md", "content": items_md}},
        {"tag": "div", "text": {"tag": "lark_md", "content": cond_md}},
        {"tag": "div", "text": {"tag": "lark_md", "content": note_md}},
        {"tag": "hr"},
    ]

elements = [
    {"tag": "div", "text": {"tag": "lark_md", "content": f"**📈 每日选股 {latest} | 三策略组合**"}},
    {"tag": "hr"},
    {"tag": "div", "text": {"tag": "lark_md", "content": f"🟢 大盘弱市 {weak_pct:.1f}%（需50%:{'✅' if market_ok_50 else '❌'} | 需70%:{'✅' if market_ok_70 else '❌'}）"}},
    {"tag": "hr"},
]

# Fstop3 v10 - 动态读取评估结果
fstop3_metric = STRATEGY_METRICS.get('Fstop3_pt5_v10', '⚠️ 回测指标待更新')
elements += build_section(
    title="策略1️⃣ Fstop3_pt5（RSI<18 + BB触底 + 放量1.5x + 弱市50%）",
    picks=picks_v10,
    cond_md=f"回测参考：{fstop3_metric}",
    note_md="建议：T+1开盘买 | 止损3%止盈5% | 持有个≤10天了结",
    show_vol=True,
)
# BB1.00 - 动态读取评估结果
bb100_metric = STRATEGY_METRICS.get('BB1.00', '⚠️ 回测指标待更新')
elements += build_section(
    title="策略2️⃣ BB1.00（RSI<20 + BB≤1.00 + 弱市70% + 7天持有）",
    picks=picks_b1,
    cond_md=f"回测：{bb100_metric}",
    note_md="建议：T+1开盘买 | 持有7天次日卖出 | 不设止损止盈",
)
# BB1.02+KDJ - 动态读取评估结果
bbkdj_metric = STRATEGY_METRICS.get('BB1.02_KDJ', '⚠️ 回测指标待更新')
elements += build_section(
    title="策略3️⃣ BB1.02+KDJ（RSI<20 + BB≤1.02 + KDJ超卖 + 弱市70% + TOP500）",
    picks=picks_kdj,
    cond_md=f"回测：{bbkdj_metric}",
    note_md="建议：T+1开盘买 | 持有7天次日卖出 | 不设止损止盈",
)


elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": f"数据:{latest} | 三策略组合 | 不构成投资建议"}]})

card = {"elements": elements}

APP_ID = os.environ.get("APP_ID_BOT2", "cli_a938ffaf9738dbc6")
APP_SECRET = os.environ.get("APP_SECRET_BOT2", "ulvmnUvH1VBlqgPq298isdQ1VFURenaR")
OPEN_ID = os.environ.get("OPEN_ID_USER", "ou_8822a58f429ea317ab49166d79533b0f")  # 何强本人
GROUP_ID = os.environ.get("GROUP_ID_HOME", "oc_7670b1e26e01cfdc95f70ec74734e6af")   # Home群

# --- 构建纯文本消息 ---
def build_text_message():
    lines = []
    lines.append(f"📈 每日选股 {latest} | 三策略组合")
    lines.append(f"策略版本：{STRATEGY_VERSION}")
    if stale_trade_days and stale_trade_days > 0:
        lines.append(f"⚠️ 数据滞后：最新交易日 {latest_trade}，当前使用 {latest}（滞后 {stale_trade_days} 个交易日）")
    lines.append(f"大盘弱市 {weak_pct:.1f}%（需50%:{'✅' if market_ok_50 else '❌'} | 需70%:{'✅' if market_ok_70 else '❌'}）")
    lines.append("")

    def format_picks(title, picks, cond, note, show_vol=False, max_show=5):
        out = []
        out.append(f"【{title}】共{len(picks)}只")
        if picks:
            for p in picks[:max_show]:
                vol_str = f" 放量{p[4]:.1f}x" if (show_vol and p[4] > 0) else ""
                out.append(f"  {stock_name(p[0])}({p[0][-6:]} 收{p[1]:.2f} RSI{p[2]:.1f}{vol_str})")
        else:
            out.append("  无候选")
        out.append(f"  回测：{cond}")
        out.append(f"  {note}")
        out.append("")
        return out

    lines += format_picks(
        "策略1 Fstop3_pt5（RSI<18 + BB触底 + 放量1.5x + 弱市50%）",
        picks_v10,
        STRATEGY_METRICS.get('Fstop3_pt5_v10', '⚠️ 回测指标待更新'),
        "T+1开盘买 | 止损3%止盈5% | 持有个≤10天了结",
        show_vol=True
    )
    lines += format_picks(
        "策略2 BB1.00（RSI<20 + BB≤1.00 + 弱市70% + 7天持有）",
        picks_b1,
        STRATEGY_METRICS.get('BB1.00', '⚠️ 回测指标待更新'),
        "T+1开盘买 | 持有7天次日卖出 | 不设止损止盈"
    )
    lines += format_picks(
        "策略3 BB1.02+KDJ（RSI<20 + BB≤1.02 + KDJ超卖 + 弱市70% + TOP500）",
        picks_kdj,
        STRATEGY_METRICS.get('BB1.02_KDJ', '⚠️ 回测指标待更新'),
        "T+1开盘买 | 持有7天次日卖出 | 不设止损止盈"
    )
    lines.append(f"数据：{latest} | 三策略组合 | 不构成投资建议")
    return "\n".join(lines)

text_msg = build_text_message()

r = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    json={'app_id': APP_ID, 'app_secret': APP_SECRET})
token = r.json().get('tenant_access_token')
if not token:
    print("获取token失败"); db.close(); exit(1)

# 私聊推送（默认，文本格式）
r2 = requests.post('https://open.feishu.cn/open-apis/im/v1/messages',
    params={'receive_id_type': 'open_id'},
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    json={
        'receive_id': OPEN_ID,
        'msg_type': 'text',
        'content': json.dumps({'text': text_msg})
    })
resp = r2.json()
if resp.get('code') == 0:
    print(f"飞书私聊推送成功")
else:
    print(f"飞书私聊推送失败: {resp}")

# 群里推送（仅 --also-group 时，文本格式）
if args.also_group:
    r3 = requests.post('https://open.feishu.cn/open-apis/im/v1/messages',
        params={'receive_id_type': 'chat_id'},
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={
            'receive_id': GROUP_ID,
            'msg_type': 'text',
            'content': json.dumps({'text': text_msg})
        })
    resp3 = r3.json()
    if resp3.get('code') == 0:
        print(f"飞书群推送成功")
    else:
        print(f"飞书群推送失败: {resp3}")

db.close()
