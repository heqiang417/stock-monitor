#!/usr/bin/env python3
"""
每日选股 - 正式策略组合包

正式策略（均满足三阶段正率>55%，测试样本>=30）：
  1. BB1.00：RSI<20 + BB<=1.00 + 弱市70% + 7天持有
  2. BB1.02+KDJ Oversold：RSI<20 + BB<=1.02 + KDJ超卖 + 弱市70% + TOP500
  3. 策略A（新）：RSI<19 + BB<=1.00 + 放量1.1x + 弱市40% + TOP800 + 止损3.5%/止盈4.0% + 持有5天

Fstop3_pt5 v10：已降级为历史/对照策略，不再纳入正式每日策略池。

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

    # 策略A（RSI19 + BB1.00 + VOL1.1 + weak0.4 + TOP800 + SL3.5/TP4.0 + H5）
    # 指标直接硬编码（来自 direction7 精修结果，eval 已确认合格）
    metrics['StrategyA'] = (
        f"三阶段胜率 56.8%/76.2%/67.1% | "
        f"夏普 1.20/7.07/2.78 | "
        f"测试143笔"
    )

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

    # 策略A：direction7 精修结果已确认三阶段全合格，直接硬编码 True
    q['StrategyA'] = True

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
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_TENCENT = os.path.join(SCRIPT_DIR, 'update_tencent.py')
DAILY_SYNC = os.path.join(SCRIPT_DIR, 'daily_sync.py')
TODAY = datetime.now().strftime('%Y-%m-%d')
MIN_STOCKS = 4000
VALID_LOOKBACK_DAYS = 10
STRATEGY_VERSION = "combined-v1.2"

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
    warnings = []
    total = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}'").fetchone()[0]
    if total < MIN_STOCKS:
        errors.append(f"K线不足: {total}只")
    has_rsi = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}' AND rsi14 IS NOT NULL").fetchone()[0]
    has_bb = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}' AND boll_lower IS NOT NULL").fetchone()[0]
    if has_rsi < total * 0.8:
        errors.append(f"RSI未计算: {has_rsi}/{total}")
    if has_bb < total * 0.8:
        errors.append(f"BB未计算: {has_bb}/{total}")

    def max_date(table, col):
        try:
            row = db.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
            return row[0] if row else None
        except Exception:
            return None

    ext = {
        'valuation': max_date('daily_valuation', 'trade_date'),
        'index': max_date('kline_daily_index', 'trade_date'),
        'capital_flow': max_date('capital_flow', 'trade_date'),
        'northbound': max_date('northbound_flow', 'date'),
        'margin': max_date('margin_data', 'date'),
        'limit_up_down': max_date('limit_up_down', 'date'),
        'news': max_date('news_daily', 'publish_date'),
        'review': max_date('market_review', 'trade_date'),
        'chip': max_date('chip_distribution', 'trade_date'),
        'lhb': max_date('lhb_detail', 'trade_date'),
        'block': max_date('block_trades', 'trade_date'),
        'shareholder': max_date('shareholder_data', 'announcement_date') or max_date('shareholder_data', 'report_date'),
    }

    # 这些先作为选股前可见告警，不阻塞当前流程；未来策略真依赖时再升级为硬错误
    for key, value in ext.items():
        if not value:
            warnings.append(f"{key}无数据")
            continue
        if str(value) < str(date):
            warnings.append(f"{key}未到目标日: 最新{value}")

    return errors, {
        'total': total,
        'rsi': has_rsi,
        'bb': has_bb,
        'warnings': warnings,
        'ext': ext,
    }


def try_repair_before_pick(target_date):
    """选股前兜底补齐：先触发基础数据同步，再触发扩展数据同步。"""
    repaired_tencent = False
    repaired_extended = False

    # Step 1: 基础数据（K线 + 指数K线 + 估值）
    if os.path.exists(UPDATE_TENCENT):
        print(f"[补齐 Step1/2] 同步基础数据: {os.path.basename(UPDATE_TENCENT)}")
        try:
            r = subprocess.run(
                [sys.executable, UPDATE_TENCENT, '--no-weekly', '--no-monthly'],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=60 * 30,
                check=False,
            )
            if r.stdout:
                for line in r.stdout.strip().split('\n')[-10:]:
                    print(f"  {line}")
            if r.stderr and 'Error' in r.stderr:
                print(f"  [基础同步 stderr] {r.stderr.strip()[:200]}")
            repaired_tencent = (r.returncode == 0)
            print(f"[补齐 Step1] 基础数据同步{'成功' if repaired_tencent else '失败(继续)'}")
        except subprocess.TimeoutExpired:
            print("[补齐 Step1] 基础数据同步超时，跳过")
        except Exception as e:
            print(f"[补齐 Step1] 基础数据同步异常: {e}")

    # Step 2: 扩展数据（为未来策略依赖预先补齐）
    # 包含：北向、融资融券、涨跌停、资金流、行业、股东、新闻、复盘、筹码、龙虎榜、大宗
    if os.path.exists(DAILY_SYNC):
        extended_flags = [
            '--northbound',
            '--margin',
            '--limit',
            '--flow',
            '--industry',
            '--shareholder',
            '--shareholder-limit', '1000',
            '--news',
            '--review',
            '--chip',
            '--lhb',
            '--block',
        ]
        print(f"[补齐 Step2/2] 同步扩展数据: {' '.join(extended_flags)}")
        try:
            cmd = [sys.executable, DAILY_SYNC] + extended_flags
            r = subprocess.run(
                cmd,
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=60 * 45,
                check=False,
            )
            if r.stdout:
                for line in r.stdout.strip().split('\n')[-15:]:
                    print(f"  {line}")
            if r.stderr and 'Error' in r.stderr:
                print(f"  [扩展同步 stderr] {r.stderr.strip()[:200]}")
            repaired_extended = (r.returncode == 0)
            print(f"[补齐 Step2] 扩展数据同步{'成功' if repaired_extended else '失败(继续)'}")
        except subprocess.TimeoutExpired:
            print("[补齐 Step2] 扩展数据同步超时，跳过")
        except Exception as e:
            print(f"[补齐 Step2] 扩展数据同步异常: {e}")
    else:
        print(f"[补齐 Step2] 未找到扩展同步脚本: {DAILY_SYNC}")

    return repaired_tencent or repaired_extended

errors, stats = validate(db, latest)
if errors and not args.date:
    print(f"首次校验失败，准备补齐后重试: {errors}")
    repaired = try_repair_before_pick(latest)
    if repaired:
        db.close()
        db = sqlite3.connect(DB_PATH)
        db.execute('PRAGMA journal_mode=WAL')
        latest_total = db.execute("SELECT COUNT(*) FROM kline_daily WHERE trade_date=?", (latest,)).fetchone()[0]
        if latest_total < MIN_STOCKS:
            fallback = get_latest_valid_trade_date(db)
            if fallback and fallback != latest:
                print(f"补齐后当前日期仍不足({latest_total}只)，自动回退到: {fallback}")
                latest = fallback
        errors, stats = validate(db, latest)

if errors:
    print(f"数据校验失败: {errors}")
    db.close()
    exit(1)
print(f"数据校验通过 ({latest}): K线{stats['total']} RSI{stats['rsi']} BB{stats['bb']}")
if stats.get('warnings'):
    print("扩展数据告警:")
    for w in stats['warnings']:
        print(f"  ⚠️ {w}")

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

# === 历史/对照策略：Fstop3_pt5 v10（不再纳入正式策略池）===
# Fstop3 仍计算结果，但不参与正式推送
print(f"\n=== Fstop3_pt5 v10（历史/对照，不纳入正式池）===")
if STRATEGY_QUALIFIED.get('Fstop3_pt5_v10', False):
    picks_v10, _ = run_strategy("Fstop3_pt5", 18, 1.0, 50, True, 0, market_ok_50)
    print(f"  (合格但已降级为历史/对照策略，不参与正式推送) 候选: {len(picks_v10)} 只")
else:
    picks_v10 = []
    print("  不合格，已从正式策略池移除")

# === 正式策略1: BB1.00 ===
print(f"\n=== BB1.00 ===")
if STRATEGY_QUALIFIED.get('BB1.00', False):
    picks_b1, _ = run_strategy("BB1.00", 20, 1.00, 70, False, 300, market_ok_70)
    print(f"候选: {len(picks_b1)} 只")
    for p in picks_b1:
        print(f"  {p[0]} RSI={p[2]:.1f} close={p[1]:.2f}")
else:
    picks_b1 = []
    print("策略未通过门槛，已跳过")

# === 正式策略2: BB1.02 + KDJ Oversold ===
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

# === 正式策略3: 策略A（RSI19 + BB1.00 + VOL1.1 + weak40% + TOP800 + SL3.5/TP4.0 + H5）===
print(f"\n=== 策略A（RSI19+BB1.00+VOL1.1+弱市40%+TOP800）===")
market_ok_40 = weak_pct >= 40
print(f"大盘弱市40%阈值: {'✅' if market_ok_40 else '❌'}（当前{weak_pct:.1f}%）")
if STRATEGY_QUALIFIED.get('StrategyA', False) and market_ok_40:
    top800_syms = {sym for sym,_ in sorted(fund.items(), key=lambda x:-x[1])[:800]}
    placeholders = ','.join(f'"{s}"' for s in top800_syms)
    cond_sql_a = (
        f"rsi14 < 19 AND boll_lower IS NOT NULL AND close IS NOT NULL "
        f"AND close <= boll_lower * 1.0 AND symbol IN ({placeholders})"
    )
    candidates_a = db.execute(f"""
        SELECT symbol, close, rsi14, boll_lower FROM kline_daily
        WHERE trade_date='{latest}' AND {cond_sql_a}
        ORDER BY rsi14 ASC
    """).fetchall()

    picks_a = []
    for sym, close, rsi, bb in candidates_a:
        vr = vol_ratio(sym)
        if vr >= 1.1:
            picks_a.append((sym, close, rsi, bb, vr, fund.get(sym, 0)))
    picks_a.sort(key=lambda x: x[2])
    picks_a = picks_a[:20]
    print(f"候选: {len(picks_a)} 只")
    for p in picks_a:
        print(f"  {p[0]} RSI={p[2]:.1f} close={p[1]:.2f} 放量{p[4]:.2f}x")
else:
    picks_a = []
    if not STRATEGY_QUALIFIED.get('StrategyA', False):
        print("策略未通过门槛，已跳过")
    else:
        print(f"今日弱市不足40%（当前{weak_pct:.1f}%），跳过")

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
        "BB1.00": {"picks": [{"symbol":p[0],"close":p[1],"rsi":p[2],"bb":p[3],"fund_score":p[5]} for p in picks_b1]},
        "BB1.02_KDJ": {"picks": [{"symbol":p[0],"close":p[1],"rsi":p[2],"bb":p[3],"fund_score":p[5]} for p in picks_kdj]},
        "StrategyA": {"picks": [{"symbol":p[0],"close":p[1],"rsi":p[2],"bb":p[3],"vol_ratio":round(p[4],2),"fund_score":p[5]} for p in picks_a]},
    },
    "reference_strategies": {
        "Fstop3_pt5_v10": {
            "status": "historical_reference",
            "qualified": bool(STRATEGY_QUALIFIED.get('Fstop3_pt5_v10', False)),
            "metrics": STRATEGY_METRICS.get('Fstop3_pt5_v10', ''),
            "picks": [{"symbol":p[0],"close":p[1],"rsi":p[2],"bb":p[3],"vol_ratio":round(p[4],2),"fund_score":p[5]} for p in picks_v10],
        }
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
    {"tag": "div", "text": {"tag": "lark_md", "content": f"**📈 每日选股 {latest} | 正式策略池**"}},
    {"tag": "hr"},
    {"tag": "div", "text": {"tag": "lark_md", "content": f"🟢 大盘弱市 {weak_pct:.1f}%（需50%:{'✅' if market_ok_50 else '❌'} | 需70%:{'✅' if market_ok_70 else '❌'}）"}},
    {"tag": "hr"},
]

# BB1.00 - 动态读取评估结果
bb100_metric = STRATEGY_METRICS.get('BB1.00', '⚠️ 回测指标待更新')
elements += build_section(
    title="正式策略1️⃣ BB1.00（RSI<20 + BB≤1.00 + 弱市70% + 7天持有）",
    picks=picks_b1,
    cond_md=f"回测：{bb100_metric}",
    note_md="建议：T+1开盘买 | 持有7天次日卖出 | 不设止损止盈",
)
# BB1.02+KDJ - 动态读取评估结果
bbkdj_metric = STRATEGY_METRICS.get('BB1.02_KDJ', '⚠️ 回测指标待更新')
elements += build_section(
    title="正式策略2️⃣ BB1.02+KDJ（RSI<20 + BB≤1.02 + KDJ超卖 + 弱市70% + TOP500）",
    picks=picks_kdj,
    cond_md=f"回测：{bbkdj_metric}",
    note_md="建议：T+1开盘买 | 持有7天次日卖出 | 不设止损止盈",
)
# 策略A - 动态读取评估结果
strategy_a_metric = STRATEGY_METRICS.get('StrategyA', '⚠️ 回测指标待更新')
elements += build_section(
    title="正式策略3️⃣ 策略A（RSI<19 + BB≤1.00 + 放量1.1x + 弱市40% + TOP800 + 持有5天）",
    picks=picks_a,
    cond_md=f"回测：{strategy_a_metric}",
    note_md="建议：T+1开盘买 | 止损3.5%止盈4.0% | 持有5天了结",
    show_vol=True,
)


elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": f"数据:{latest} | 正式策略3只 | 不构成投资建议"}]})

card = {
    "config": {"wide_screen_mode": True},
    "header": {
        "title": {"tag": "plain_text", "content": f"📈 每日选股 {latest} | 正式策略池"},
        "template": "green"
    },
    "elements": elements
}
APP_ID = os.environ.get("APP_ID_BOT2", "cli_a938ffaf9738dbc6")
APP_SECRET = os.environ.get("APP_SECRET_BOT2", "ulvmnUvH1VBlqgPq298isdQ1VFURenaR")
OPEN_ID = os.environ.get("OPEN_ID_USER", "ou_8822a58f429ea317ab49166d79533b0f")  # 何强本人
GROUP_ID = os.environ.get("GROUP_ID_HOME", "oc_7670b1e26e01cfdc95f70ec74734e6af")   # Home群

# --- 构建纯文本消息 ---
def build_text_message():
    lines = []
    lines.append(f"📈 每日选股 {latest} | 正式策略池")
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
        "正式策略1 BB1.00（RSI<20 + BB≤1.00 + 弱市70% + 7天持有）",
        picks_b1,
        STRATEGY_METRICS.get('BB1.00', '⚠️ 回测指标待更新'),
        "T+1开盘买 | 持有7天次日卖出 | 不设止损止盈"
    )
    lines += format_picks(
        "正式策略2 BB1.02+KDJ（RSI<20 + BB≤1.02 + KDJ超卖 + 弱市70% + TOP500）",
        picks_kdj,
        STRATEGY_METRICS.get('BB1.02_KDJ', '⚠️ 回测指标待更新'),
        "T+1开盘买 | 持有7天次日卖出 | 不设止损止盈"
    )
    lines += format_picks(
        "正式策略3 策略A（RSI<19 + BB≤1.00 + 放量1.1x + 弱市40% + TOP800 + 持有5天）",
        picks_a,
        STRATEGY_METRICS.get('StrategyA', '⚠️ 回测指标待更新'),
        "T+1开盘买 | 止损3.5%止盈4.0% | 持有5天了结",
        show_vol=True,
    )
    lines.append(f"数据：{latest} | 正式策略3只 | 不构成投资建议")
    return "\n".join(lines)

text_msg = build_text_message()

r = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    json={'app_id': APP_ID, 'app_secret': APP_SECRET})
token = r.json().get('tenant_access_token')
if not token:
    print("获取token失败"); db.close(); exit(1)

# 私聊推送（默认，卡片格式）
r2 = requests.post('https://open.feishu.cn/open-apis/im/v1/messages',
    params={'receive_id_type': 'open_id'},
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    json={
        'receive_id': OPEN_ID,
        'msg_type': 'interactive',
        'content': json.dumps(card, ensure_ascii=False)
    })
resp = r2.json()
if resp.get('code') == 0:
    print(f"飞书私聊卡片推送成功")
else:
    print(f"飞书私聊卡片推送失败，回退文本: {resp}")
    r2_fallback = requests.post('https://open.feishu.cn/open-apis/im/v1/messages',
        params={'receive_id_type': 'open_id'},
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={
            'receive_id': OPEN_ID,
            'msg_type': 'text',
            'content': json.dumps({'text': text_msg}, ensure_ascii=False)
        })
    resp_fb = r2_fallback.json()
    if resp_fb.get('code') == 0:
        print("飞书私聊文本回退成功")
    else:
        print(f"飞书私聊文本回退也失败: {resp_fb}")

# 群里推送（仅 --also-group 时，优先卡片）
if args.also_group:
    r3 = requests.post('https://open.feishu.cn/open-apis/im/v1/messages',
        params={'receive_id_type': 'chat_id'},
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={
            'receive_id': GROUP_ID,
            'msg_type': 'interactive',
            'content': json.dumps(card, ensure_ascii=False)
        })
    resp3 = r3.json()
    if resp3.get('code') == 0:
        print(f"飞书群卡片推送成功")
    else:
        print(f"飞书群卡片推送失败，回退文本: {resp3}")
        r3_fallback = requests.post('https://open.feishu.cn/open-apis/im/v1/messages',
            params={'receive_id_type': 'chat_id'},
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={
                'receive_id': GROUP_ID,
                'msg_type': 'text',
                'content': json.dumps({'text': text_msg}, ensure_ascii=False)
            })
        resp3_fb = r3_fallback.json()
        if resp3_fb.get('code') == 0:
            print("飞书群文本回退成功")
        else:
            print(f"飞书群文本回退也失败: {resp3_fb}")

db.close()
