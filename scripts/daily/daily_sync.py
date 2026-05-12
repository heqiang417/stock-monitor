#!/usr/bin/env python3
"""
每日数据同步脚本
每个交易日收盘后运行，同步所有数据到本地数据库

同步内容：
1. 日K线（多数据源自动切换：腾讯→akshare→efinance→baostock）
2. 技术指标（RSI、MA 重算）
3. 财务指标（检测新财报）
4. 周K线（增量）
5. 月K线（增量）
6. 估值数据（PE/PB/PS）

用法：
  python3 daily_sync.py          # 全量同步
  python3 daily_sync.py --kline   # 只同步日K线
  python3 daily_sync.py --fund    # 只同步财务指标
"""

import os
import sys
import json
import time
import random
import argparse
import threading
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import numpy as np

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from sync_health import write_sync_status

# 添加项目根目录到 Python 路径（稳健解析：scripts/daily -> 项目根）
_script_dir = os.path.dirname(os.path.abspath(__file__))
_candidate_roots = [
    os.path.dirname(os.path.dirname(_script_dir)),  # .../stock-monitor-app-py（标准）
    os.path.dirname(_script_dir),                   # .../scripts（兜底）
]

_project_root = None
for p in _candidate_roots:
    if os.path.isdir(os.path.join(p, 'data_provider')):
        _project_root = p
        break

if _project_root is None:
    # 最后兜底：保持旧行为，避免直接崩溃
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

env_file = os.path.join(_project_root, '.env')
if os.path.exists(env_file):
    try:
        with open(env_file, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except Exception:
        pass

sys.path.insert(0, _project_root)

# 兼容旧路径（仅作为fallback，优先使用当前项目路径）
_legacy_root = '/mnt/data/workspace/stock-monitor-app-py'
if os.path.exists(_legacy_root) and _legacy_root != _project_root:
    sys.path.append(_legacy_root)

from data_provider import DataFetcherManager
from data_provider.tencent_fetcher import TencentFetcher
from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.tushare_fetcher import TushareFetcher
from data_provider.baostock_fetcher import BaostockFetcher
from db import _is_postgres_target, _sqlite_placeholders_to_pyformat

# akshare 内部请求会被系统代理(clash)阻断，在 import 前清除代理环境变量
def _clear_proxy():
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        os.environ.pop(k, None)
    try:
        import requests
        requests.session().trust_env = False
    except Exception:
        pass

# 初始化多数据源管理器（腾讯最稳定，优先）
_manager = DataFetcherManager()
_manager.register(TencentFetcher(priority=0))
_manager.register(AkshareFetcher(priority=1))

# Tushare fallback（需要 TUSHARE_TOKEN 环境变量）
try:
    _tushare = TushareFetcher(priority=2)
    if _tushare.is_available():
        _manager.register(_tushare)
except Exception:
    pass

# Baostock fallback
try:
    _baostock = BaostockFetcher(priority=3)
    if _baostock.is_available():
        _manager.register(_baostock)
except Exception:
    pass

DB_TARGET = os.environ.get('POSTGRES_DSN') or os.environ.get('PG_DSN') or os.environ.get('DATABASE_URL') or os.environ.get('DB_DSN') or os.environ.get('STOCK_DB', os.path.join(_project_root, 'data', 'stock_data.db'))
DB_PATH = DB_TARGET
DB_IS_POSTGRES = _is_postgres_target(DB_TARGET)
LOG_DIR = os.environ.get('SYNC_LOG_DIR', os.path.join(_project_root, 'logs'))
INCR_DAYS = 15  # 增量更新天数
DB_TIMEOUT = int(os.environ.get('STOCK_DB_TIMEOUT', '60'))
DB_BUSY_TIMEOUT_MS = int(os.environ.get('STOCK_DB_BUSY_TIMEOUT_MS', '60000'))
REQUIRE_PG = os.environ.get('REQUIRE_PG', '1') == '1'

if REQUIRE_PG and not DB_IS_POSTGRES:
    raise RuntimeError(
        f"daily_sync.py requires PostgreSQL for production, but resolved DB_TARGET={DB_TARGET!r}. "
        f"Remove SQLite STOCK_DB override or set POSTGRES_DSN/PG_DSN/DATABASE_URL."
    )

os.makedirs(LOG_DIR, exist_ok=True)

today = datetime.now().strftime('%Y-%m-%d')
log_file = os.path.join(LOG_DIR, f'sync_{today}.log')


def _postgres_connect_kwargs(target: str) -> dict:
    parsed = urlparse(target)
    return {
        'host': parsed.hostname or '127.0.0.1',
        'port': parsed.port or 5432,
        'user': parsed.username,
        'password': parsed.password,
        'dbname': parsed.path.lstrip('/'),
        'connect_timeout': 10,
    }


def connect_db():
    if DB_IS_POSTGRES:
        import psycopg2
        conn = psycopg2.connect(**_postgres_connect_kwargs(DB_TARGET))
        conn.autocommit = False
        return conn

    from db import connect_db as _connect_db
    db_dir = os.path.dirname(DB_PATH) or '.'
    os.makedirs(db_dir, exist_ok=True)
    return _connect_db(DB_PATH)


def _q(sql: str) -> str:
    return _sqlite_placeholders_to_pyformat(sql) if DB_IS_POSTGRES else sql


def db_execute(conn, sql: str, params=()):
    cur = conn.cursor()
    cur.execute(_q(sql), params)
    return cur


def db_executemany(conn, sql: str, params_list):
    cur = conn.cursor()
    cur.executemany(_q(sql), params_list)
    return cur


def db_fetchall(conn, sql: str, params=()):
    return db_execute(conn, sql, params).fetchall()


def db_fetchone(conn, sql: str, params=()):
    return db_execute(conn, sql, params).fetchone()


def sql_insert(table: str, columns: list[str], conflict_cols: list[str] | None = None, update_cols: list[str] | None = None, ignore: bool = False) -> str:
    placeholders = ','.join(['?'] * len(columns))
    cols = ', '.join(columns)
    if ignore:
        if conflict_cols:
            return f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
        return f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})" if not DB_IS_POSTGRES else f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    if conflict_cols and update_cols:
        update_clause = ', '.join(f"{c}=EXCLUDED.{c}" for c in update_cols)
        return f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {update_clause}"

    return f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(log_file, 'a') as f:
        f.write(line + '\n')

# 记录已注册的数据源
log(f"已注册数据源: {[f.name for f in _manager.fetchers]}")
log(f"数据库目标: {DB_TARGET}")
if DB_IS_POSTGRES:
    log("数据库类型: PostgreSQL")
else:
    log(f"数据库目录存在: {os.path.isdir(os.path.dirname(DB_PATH) or '.')} | 文件存在: {os.path.exists(DB_PATH)} | timeout={DB_TIMEOUT}s | busy_timeout={DB_BUSY_TIMEOUT_MS}ms")

# ============================================================
# 1. 日K线增量更新（多数据源自动切换）
# ============================================================
def sync_daily_kline():
    log("=== 开始同步日K线（多数据源）===")
    conn = connect_db()
    symbols = [r[0] for r in db_fetchall(conn, 'SELECT DISTINCT symbol FROM kline_daily')]
    conn.close()

    beg_date = (datetime.now() - timedelta(days=INCR_DAYS)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    success = 0
    failed = 0

    def fetch_and_save(symbol):
        try:
            df = _manager.get_daily_data(symbol, beg_date, end_date)
            if df is None or df.empty:
                return 0

            conn2 = connect_db()
            count = 0
            for _, row in df.iterrows():
                try:
                    db_execute(conn2, sql_insert(
                        'kline_daily',
                        ['symbol', 'trade_date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'chg', 'chg_pct'],
                        conflict_cols=['symbol', 'trade_date'],
                        update_cols=['open', 'close', 'high', 'low', 'volume', 'amount', 'chg', 'chg_pct']
                    ),
                        (symbol, str(row['date']), float(row['open']), float(row['close']),
                         float(row['high']), float(row['low']), float(row['volume']),
                         float(row['amount']), float(row.get('chg', 0)),
                         float(row.get('chg_pct', 0))))
                    count += 1
                except:
                    pass
            conn2.commit()
            conn2.close()
            return count
        except:
            return 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_and_save, s): s for s in symbols}
        for f in as_completed(futures, timeout=600):
            try:
                result = f.result(timeout=15)
            except:
                result = 0
            if result > 0:
                success += 1
            else:
                failed += 1
            if (success + failed) % 500 == 0:
                log(f"  日K线进度: {success + failed}/{len(symbols)}")

    log(f"  日K线完成: 成功{success}, 失败{failed}")

# ============================================================
# 2. 技术指标重算
# ============================================================
def recalc_technical_indicators():
    log("=== 重算技术指标 ===")
    conn = connect_db()
    symbols = [r[0] for r in db_fetchall(conn, 'SELECT DISTINCT symbol FROM kline_daily')]
    updated = 0

    for i, symbol in enumerate(symbols):
        rows = db_fetchall(
            conn,
            'SELECT trade_date, close, high, low FROM kline_daily WHERE symbol=? ORDER BY trade_date',
            (symbol,)
        )

        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]

        updates = []
        for j, row in enumerate(rows):
            trade_date = row[0]
            ma5 = round(sum(closes[max(0, j-4):j+1]) / min(5, j+1), 2) if j >= 0 else None
            ma10 = round(sum(closes[max(0, j-9):j+1]) / min(10, j+1), 2) if j >= 1 else None
            ma20 = round(sum(closes[max(0, j-19):j+1]) / min(20, j+1), 2) if j >= 1 else None
            ma60 = round(sum(closes[max(0, j-59):j+1]) / min(60, j+1), 2) if j >= 1 else None

            rsi14 = None
            if j >= 14:
                gains, losses = [], []
                for k in range(j-13, j+1):
                    change = closes[k] - closes[k-1]
                    gains.append(max(change, 0))
                    losses.append(max(-change, 0))
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                if avg_loss == 0:
                    rsi14 = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi14 = round(100 - 100 / (1 + rs), 2)

            updates.append((ma5, ma10, ma20, ma60, rsi14, symbol, trade_date))

        if updates:
            db_executemany(
                conn,
                'UPDATE kline_daily SET ma5=?, ma10=?, ma20=?, ma60=?, rsi14=? WHERE symbol=? AND trade_date=?',
                updates
            )

        updated += 1
        if updated % 500 == 0:
            log(f"  技术指标进度: {updated}/{len(symbols)}")

    conn.commit()
    conn.close()
    log(f"  技术指标完成: 更新{updated}只股票")

# ============================================================
# 3. 财务指标增量更新
# ============================================================
def sync_financial_indicators():
    log("=== 同步财务指标（滚动500只）===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    all_symbols = [r[0] for r in db_fetchall(conn, 'SELECT DISTINCT symbol FROM kline_daily')]

    # 找出最久没更新的500只
    stale = db_fetchall(conn, '''
        SELECT k.symbol FROM kline_daily k
        LEFT JOIN (
            SELECT symbol, MAX(report_date) as latest FROM financial_indicators GROUP BY symbol
        ) f ON k.symbol = f.symbol
        GROUP BY k.symbol, f.latest
        ORDER BY COALESCE(f.latest, '2000-01-01') ASC
        LIMIT 500
    ''')
    symbols = [r[0] for r in stale]
    conn.close()

    log(f"  待更新: {len(symbols)}只（最久未更新优先）")
    success = 0
    failed = 0

    for i, symbol in enumerate(symbols):
        code = symbol[2:] if symbol.startswith(('sz', 'sh')) else symbol
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code, start_year=str(datetime.now().year - 1))
            if df is None or df.empty:
                failed += 1
                continue
            latest = df.iloc[0]
            conn2 = connect_db()
            db_execute(conn2, sql_insert(
                'financial_indicators',
                ['symbol', 'report_date', 'eps', 'roe', 'revenue_growth', 'profit_growth',
                 'gross_margin', 'net_margin', 'debt_ratio', 'current_ratio', 'total_assets'],
                conflict_cols=['symbol', 'report_date'],
                update_cols=['eps', 'roe', 'revenue_growth', 'profit_growth', 'gross_margin', 'net_margin', 'debt_ratio', 'current_ratio', 'total_assets']
            ),
                (symbol, str(latest.get('日期', '')),
                 float(latest.get('摊薄每股收益(元)', 0) or 0),
                 float(latest.get('净资产收益率(%)', 0) or 0),
                 float(latest.get('主营业务收入增长率(%)', 0) or 0),
                 float(latest.get('净利润增长率(%)', 0) or 0),
                 float(latest.get('销售毛利率(%)', 0) or 0),
                 float(latest.get('销售净利率(%)', 0) or 0),
                 float(latest.get('资产负债率(%)', 0) or 0),
                 float(latest.get('流动比率', 0) or 0), None))
            conn2.commit()
            conn2.close()
            success += 1
        except:
            failed += 1

        if (i + 1) % 100 == 0:
            log(f"  财务指标进度: {i+1}/{len(symbols)} 成功{success} 失败{failed}")
        time.sleep(0.3)

    log(f"  财务指标完成: 成功{success}, 失败{failed}")

# ============================================================
# 3b. 财务指标每日快照（forward fill）
# ============================================================
def build_financial_daily():
    """把每只股票最新的财务数据写入 financial_daily，保证每天有完整快照"""
    log("=== 构建财务每日快照 ===")
    today = datetime.now().strftime('%Y-%m-%d')
    conn = connect_db()

    # 建表
    db_execute(conn, '''CREATE TABLE IF NOT EXISTS financial_daily (
        symbol TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        eps REAL, roe REAL, revenue_growth REAL, profit_growth REAL,
        gross_margin REAL, net_margin REAL, debt_ratio REAL,
        current_ratio REAL, total_assets REAL,
        PRIMARY KEY (symbol, trade_date)
    )''')

    # 删除今天的旧快照（允许重跑）
    db_execute(conn, "DELETE FROM financial_daily WHERE trade_date=?", (today,))

    # 每只股票取最新一条财务数据，写入今天的快照
    db_execute(conn, f'''
        INSERT INTO financial_daily
            (symbol, trade_date, eps, roe, revenue_growth, profit_growth,
             gross_margin, net_margin, debt_ratio, current_ratio, total_assets)
        SELECT f.symbol, '{today}', f.eps, f.roe, f.revenue_growth, f.profit_growth,
               f.gross_margin, f.net_margin, f.debt_ratio, f.current_ratio, f.total_assets
        FROM financial_indicators f
        INNER JOIN (
            SELECT symbol, MAX(report_date) as max_date
            FROM financial_indicators GROUP BY symbol
        ) latest ON f.symbol = latest.symbol AND f.report_date = latest.max_date
        ON CONFLICT (symbol, trade_date) DO NOTHING
    ''')

    count = db_fetchone(conn, "SELECT COUNT(*) FROM financial_daily WHERE trade_date=?", (today,))[0]
    conn.commit()
    conn.close()
    log(f"  财务快照完成: {today} {count}只")

# ============================================================
# 4. 周K线增量更新
# ============================================================
def sync_weekly_kline():
    log("=== 同步周K线（多数据源自动切换）===")

    conn = connect_db()
    symbols = [r[0] for r in db_fetchall(conn, 'SELECT DISTINCT symbol FROM kline_daily')]

    start_date = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    success = 0

    for i, symbol in enumerate(symbols):
        try:
            df = _manager.get_period_data(symbol, start_date, end_date, period='weekly')
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    db_execute(conn, sql_insert(
                        'kline_weekly',
                        ['symbol', 'trade_week', 'open', 'close', 'high', 'low', 'volume', 'amount', 'chg', 'chg_pct'],
                        conflict_cols=['symbol', 'trade_week'],
                        ignore=True
                    ),
                        (symbol, str(row['date']), float(row['open']), float(row['close']),
                         float(row['high']), float(row['low']), float(row['volume']),
                         float(row['amount']), float(row.get('chg', 0)),
                         float(row.get('chg_pct', 0))))
                success += 1
        except:
            pass

        if (i+1) % 200 == 0:
            conn.commit()
            log(f"  周K线进度: {i+1}/{len(symbols)}")
        time.sleep(0.2)

    conn.commit()
    conn.close()
    log(f"  周K线完成: 更新{success}只")

# ============================================================
# 5. 月K线增量更新
# ============================================================
def sync_monthly_kline():
    log("=== 同步月K线（多数据源自动切换）===")

    conn = connect_db()
    symbols = [r[0] for r in db_fetchall(conn, 'SELECT DISTINCT symbol FROM kline_daily')]

    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    success = 0

    for i, symbol in enumerate(symbols):
        try:
            df = _manager.get_period_data(symbol, start_date, end_date, period='monthly')
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    db_execute(conn, sql_insert(
                        'kline_monthly',
                        ['symbol', 'trade_month', 'open', 'close', 'high', 'low', 'volume', 'amount', 'chg', 'chg_pct'],
                        conflict_cols=['symbol', 'trade_month'],
                        ignore=True
                    ),
                        (symbol, str(row['date']), float(row['open']), float(row['close']),
                         float(row['high']), float(row['low']), float(row['volume']),
                         float(row['amount']), float(row.get('chg', 0)),
                         float(row.get('chg_pct', 0))))
                success += 1
        except:
            pass

        if (i+1) % 200 == 0:
            conn.commit()
            log(f"  月K线进度: {i+1}/{len(symbols)}")
        time.sleep(0.2)

    conn.commit()
    conn.close()
    log(f"  月K线完成: 更新{success}只")

# ============================================================
# 6. 估值数据更新
# ============================================================
def sync_valuation():
    log("=== 同步估值数据 ===")
    # 优先走腾讯实时估值兜底，避免 akshare/eastmoney push2 断连
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception as e:
        log(f"  requests 不可用，跳过: {e}")
        return

    conn = connect_db()
    symbols = [r[0] for r in db_fetchall(conn, 'SELECT DISTINCT symbol FROM kline_daily')]

    def _get_session():
        s = requests.Session()
        s.trust_env = False
        s.proxies = {"http": "", "https": ""}
        return s

    def _fetch_tencent_quote(symbol):
        session = _get_session()
        try:
            r = session.get(
                f'https://203.205.235.28/q={symbol}',
                headers={'Host': 'qt.gtimg.cn'},
                verify=False,
                timeout=15,
            )
            text = r.text.strip()
            eq_pos = text.index('=')
            fields = text[eq_pos + 2:-1].split('~')
            if len(fields) >= 47:
                return {
                    'pe': float(fields[39]) if fields[39] else None,
                    'pb': float(fields[46]) if fields[46] else None,
                }
        except Exception:
            return None
        return None

    count = 0
    failed = 0
    for i, symbol in enumerate(symbols):
        quote = _fetch_tencent_quote(symbol)
        if quote and (quote.get('pe') is not None or quote.get('pb') is not None):
            try:
                db_execute(conn, sql_insert(
                    'daily_valuation',
                    ['symbol', 'trade_date', 'pe_ttm', 'pb', 'ps_ttm'],
                    conflict_cols=['symbol', 'trade_date'],
                    update_cols=['pe_ttm', 'pb', 'ps_ttm']
                ),
                    (symbol, today, quote.get('pe'), quote.get('pb'), None))
                count += 1
            except Exception:
                failed += 1
        else:
            failed += 1
        if (i + 1) % 1000 == 0:
            log(f"  估值进度: {i+1}/{len(symbols)}")

    conn.commit()
    conn.close()
    log(f"  估值数据完成: 更新{count}只, 失败{failed}只")

# ============================================================
# 7. 资金流向更新（当前 eastmoney push2 不稳，先降级为跳过+明确日志）
# ============================================================
def sync_capital_flow():
    """资金流向当前数据源不稳定，先止血：不再长时间卡死或写入异常稀疏数据。"""
    log("=== 同步资金流向（降级保护）===")
    latest = None
    count = 0
    try:
        conn = connect_db()
        latest = db_fetchone(conn, "SELECT MAX(trade_date) FROM capital_flow")[0]
        if latest:
            count = db_fetchone(conn, "SELECT COUNT(*) FROM capital_flow WHERE trade_date=?", (latest,))[0]
        conn.close()
    except Exception:
        pass
    log("  ⚠️ 当前 eastmoney push2 链路不稳定，资金流同步暂时跳过，保留历史数据")
    log("  ⚠️ 待切换稳定替代数据源后再恢复日更")
    return {
        'status': 'degraded',
        'reason': 'eastmoney_push2_unstable',
        'latest_available_date': latest,
        'latest_count': count,
    }

# ============================================================
# 8. 行业板块更新
# ============================================================
def sync_industry():
    log("=== 同步行业板块 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    symbols = [r[0] for r in db_fetchall(conn, 'SELECT DISTINCT symbol FROM kline_daily')]

    # 尝试批量获取
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            # 检查是否有成分股信息
            log(f"  获取到 {len(df)} 个行业板块")
            count = 0
            for _, row in df.iterrows():
                code = str(row.get('代码', ''))
                if code.startswith('6'):
                    symbol = f'sh{code}'
                elif code.startswith(('0', '3')):
                    symbol = f'sz{code}'
                else:
                    continue
                if symbol in symbols:
                    db_execute(conn, sql_insert(
                        'stock_industry',
                        ['symbol', 'industry', 'industry_code'],
                        conflict_cols=['symbol'],
                        update_cols=['industry', 'industry_code']
                    ),
                        (symbol, str(row.get('名称', '')), str(row.get('代码', ''))))
                    count += 1
            conn.commit()
            log(f"  行业板块批量完成: {count}只")
            conn.close()
            return
    except:
        pass

    # 逐只获取
    success = 0
    for i, symbol in enumerate(symbols):
        code = symbol[2:]
        try:
            df = ak.stock_individual_info_em(symbol=code)
            if df is not None and not df.empty:
                info = dict(zip(df['item'], df['value']))
                industry = info.get('行业', '')
                if industry:
                    db_execute(conn, sql_insert(
                        'stock_industry',
                        ['symbol', 'industry'],
                        conflict_cols=['symbol'],
                        update_cols=['industry']
                    ), (symbol, industry))
                    success += 1
        except:
            pass
        if (i+1) % 200 == 0:
            log(f"  行业板块进度: {i+1}/{len(symbols)}")
        time.sleep(0.3)

    conn.commit()
    conn.close()
    log(f"  行业板块完成: 更新{success}只")

# ============================================================
# 9. 北向资金增量更新
# ============================================================
def sync_northbound_flow():
    log("=== 同步北向资金 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    _clear_proxy()
    conn = connect_db()
    # 检查已有最新日期
    latest = db_fetchone(conn, "SELECT MAX(date) FROM northbound_flow")[0]
    if latest and not isinstance(latest, str):
        latest = str(latest)
    conn.close()

    count = 0
    for name in ['沪股通', '深股通']:
        try:
            df = ak.stock_hsgt_hist_em(symbol=name)
            if df is None or df.empty:
                continue
            df = df.rename(columns={
                '日期': 'date', '当日资金流入': 'net_buy',
                '当日余额': 'balance', '历史累计净买额': 'net_flow'
            })
            conn2 = connect_db()
            for _, row in df.iterrows():
                d = str(row.get('date', ''))
                if latest and d <= latest:
                    continue
                db_execute(conn2, sql_insert(
                    'northbound_flow',
                    ['date', 'type', 'direction', 'net_buy', 'net_flow', 'index_chg'],
                    conflict_cols=['date', 'type', 'direction'],
                    ignore=True
                ),
                    (d, name, '北向',
                     float(row.get('net_buy', 0) or 0),
                     float(row.get('net_flow', 0) or 0),
                     float(row.get('上证指数-涨跌幅', 0) or 0)))
                count += 1
            conn2.commit()
            conn2.close()
        except Exception as e:
            log(f"  北向资金 {name} 失败: {e}")

    log(f"  北向资金完成: 新增{count}条")

# ============================================================
# 10. 融资融券增量更新
# ============================================================
def sync_margin_data():
    log("=== 同步融资融券 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    _clear_proxy()
    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(date) FROM margin_data")[0]
    if latest and not isinstance(latest, str):
        latest = latest.strftime('%Y%m%d') if hasattr(latest, 'strftime') else str(latest).replace('-', '')
    conn.close()

    # 最近7个自然日内取交易日候选
    dates_to_fetch = []
    d = datetime.now()
    while len(dates_to_fetch) < 7:
        if d.weekday() < 5:
            dates_to_fetch.append(d.strftime('%Y%m%d'))
        d -= timedelta(days=1)

    if latest:
        dates_to_fetch = [dt for dt in dates_to_fetch if dt > latest]

    if not dates_to_fetch:
        log("  融资融券已是最新")
        return

    count = 0
    failed = 0
    for date_str in sorted(dates_to_fetch):
        success_for_day = False
        last_err = None

        for attempt in range(3):
            try:
                df = ak.stock_margin_detail_sse(date=date_str)
                # akshare 在无数据时返回 0行df但尝试设置13列名，报 ValueError
                # 将其视为"无数据"而非失败
                if df is None or df.empty:
                    log(f"  融资融券 {date_str} 无数据，跳过")
                    success_for_day = True
                    break

                # 兼容列名变化：只聚合实际存在的列
                def _sum_col(frame, names):
                    for name in names:
                        if name in frame.columns:
                            ser = frame[name]
                            return float(ser.fillna(0).sum())
                    return 0.0

                margin_balance = _sum_col(df, ['融资余额'])
                margin_buy = _sum_col(df, ['融资买入额'])
                short_sell = _sum_col(df, ['融券卖出量', '融券卖出'])
                short_amount = _sum_col(df, ['融券卖出额'])
                short_volume = _sum_col(df, ['融券余量'])

                conn2 = connect_db()
                db_execute(conn2, sql_insert(
                    'margin_data',
                    ['date', 'margin_balance', 'margin_buy', 'short_volume', 'short_amount', 'short_sell', 'total_balance'],
                    conflict_cols=['date'],
                    update_cols=['margin_balance', 'margin_buy', 'short_volume', 'short_amount', 'short_sell', 'total_balance']
                ),
                    (date_str, margin_balance, margin_buy, short_volume,
                     short_amount, short_sell, margin_balance + short_amount))
                conn2.commit()
                conn2.close()
                count += 1
                success_for_day = True
                break
            except ValueError as ve:
                # akshare 返回空df时设置列名失败，视为"无数据"而非失败
                if 'Length mismatch' in str(ve):
                    log(f"  融资融券 {date_str} 无数据（接口返回空），跳过")
                    success_for_day = True
                    break
                last_err = ve
                time.sleep(1 + attempt)
            except Exception as e:
                last_err = e
                time.sleep(1 + attempt)

        if not success_for_day:
            failed += 1
            log(f"  融资融券 {date_str} 失败: {last_err}")

    log(f"  融资融券完成: 新增{count}天, 失败{failed}天")

# ============================================================
# 11. 股东数据增量更新（抽样）
# ============================================================
def sync_shareholder_data(limit=500):
    log(f"=== 同步股东数据（滚动{limit}只）===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    # 找出最久没更新的 limit 只
    stale = db_fetchall(conn, f'''
        SELECT k.symbol FROM kline_daily k
        LEFT JOIN (
            SELECT symbol, MAX(created_at) as latest FROM shareholder_data GROUP BY symbol
        ) s ON k.symbol = s.symbol
        GROUP BY k.symbol, s.latest
        ORDER BY COALESCE(s.latest, '2000-01-01') ASC
        LIMIT {int(limit)}
    ''')
    symbols = [r[0] for r in stale]
    conn.close()

    log(f"  待更新: {len(symbols)}只（最久未更新优先）")
    count = 0
    failed = 0

    for i, symbol in enumerate(symbols):
        code = symbol[2:] if symbol.startswith(('sz', 'sh')) else symbol
        success = False
        for attempt in range(2):
            try:
                df = ak.stock_circulate_stock_holder(symbol=code)
                if df is not None and not df.empty:
                    conn2 = connect_db()
                    for _, row in df.iterrows():
                        rd = str(row.get('日期', ''))
                        name = str(row.get('股东名称', ''))
                        hold_num = float(row.get('持股数量', 0) or 0)
                        hold_ratio = float(row.get('持股比例', 0) or 0)
                        db_execute(conn2, sql_insert(
                            'shareholder_data',
                            ['symbol', 'report_date', 'name', 'shareholder_count', 'change_pct', 'avg_holdings'],
                            conflict_cols=['symbol', 'report_date', 'name'],
                            ignore=True
                        ),
                            (symbol, rd, name, int(hold_num), hold_ratio, 0))
                        count += 1
                    conn2.commit()
                    conn2.close()
                success = True
                break
            except Exception:
                time.sleep(0.5 + attempt)
        if not success:
            failed += 1

        if (i + 1) % 100 == 0:
            log(f"  股东数据进度: {i+1}/{len(symbols)} 成功{count}条 失败{failed}只")

    log(f"  股东数据完成: 新增{count}条, 失败{failed}只")

# ============================================================
# 12. 涨跌停数据增量更新
# ============================================================
def sync_limit_up_down():
    log("=== 同步涨跌停数据 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(date) FROM limit_up_down")[0]
    conn.close()

    # 最近5个交易日
    dates_to_fetch = []
    d = datetime.now()
    while len(dates_to_fetch) < 7:
        if d.weekday() < 5:
            dates_to_fetch.append(d.strftime('%Y%m%d'))
        d -= timedelta(days=1)

    if latest:
        dates_to_fetch = [dt for dt in dates_to_fetch if dt.replace('-','') > latest.replace('-','')]

    if not dates_to_fetch:
        log("  涨跌停已是最新")
        return

    count = 0
    for date_str in sorted(dates_to_fetch):
        # 涨停
        try:
            df = ak.stock_zt_pool_em(date=date_str)
            if df is not None and not df.empty:
                conn2 = connect_db()
                for _, row in df.iterrows():
                    code = str(row.get('代码', ''))
                    db_execute(conn2, sql_insert(
                        'limit_up_down',
                        ['date', 'code', 'name', 'chg_pct', 'close', 'amount', 'mkt_cap',
                         'turnover', 'seal_amount', 'first_seal_time', 'last_seal_time',
                         'break_count', 'consecutive', 'industry', 'type'],
                        conflict_cols=['date', 'code', 'type'],
                        ignore=True
                    ),
                        (date_str, code, str(row.get('名称', '')),
                         float(row.get('涨跌幅', 0) or 0),
                         float(row.get('最新价', 0) or 0),
                         float(row.get('成交额', 0) or 0),
                         float(row.get('总市值', 0) or 0),
                         float(row.get('换手率', 0) or 0),
                         float(row.get('封板资金', 0) or 0),
                         str(row.get('首次封板时间', '')),
                         str(row.get('最后封板时间', '')),
                         int(row.get('炸板次数', 0) or 0),
                         int(row.get('连板数', 1) or 1),
                         str(row.get('所属行业', '')), 'up'))
                    count += 1
                conn2.commit()
                conn2.close()
        except Exception as e:
            log(f"  涨停 {date_str} 失败: {e}")

        # 跌停
        try:
            df = ak.stock_zt_pool_dtgc_em(date=date_str)
            if df is not None and not df.empty:
                conn2 = connect_db()
                for _, row in df.iterrows():
                    code = str(row.get('代码', ''))
                    db_execute(conn2, sql_insert(
                        'limit_up_down',
                        ['date', 'code', 'name', 'chg_pct', 'close', 'amount', 'mkt_cap', 'turnover', 'type'],
                        conflict_cols=['date', 'code', 'type'],
                        ignore=True
                    ),
                        (date_str, code, str(row.get('名称', '')),
                         float(row.get('涨跌幅', 0) or 0),
                         float(row.get('最新价', 0) or 0),
                         float(row.get('成交额', 0) or 0),
                         float(row.get('总市值', 0) or 0),
                         float(row.get('换手率', 0) or 0), 'down'))
                    count += 1
                conn2.commit()
                conn2.close()
        except Exception as e:
            log(f"  跌停 {date_str} 失败: {e}")

        time.sleep(1)

    log(f"  涨跌停完成: 新增{count}条")

# ============================================================
# 13. 新闻搜索（Tavily API）
# ============================================================
def sync_news():
    """搜索关注列表股票的每日新闻"""
    log("=== 同步股票新闻 ===")

    # 读取 Tavily API key
    tavily_key = ""
    tavily_env = os.path.expanduser("~/.openclaw/.env")
    if os.path.exists(tavily_env):
        with open(tavily_env) as f:
            for line in f:
                if line.startswith("TAVILY_API_KEY="):
                    tavily_key = line.strip().split("=", 1)[1]
                    break
    if not tavily_key:
        log("  TAVILY_API_KEY 未设置，跳过")
        return

    conn = connect_db()
    # 建表
    db_execute(conn, '''CREATE TABLE IF NOT EXISTS news_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        title TEXT,
        url TEXT,
        snippet TEXT,
        publish_date TEXT,
        source TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )''')

    # 读取关注列表
    watchlist = db_fetchall(conn, "SELECT symbol, name FROM watchlist")
    conn.close()

    if not watchlist:
        log("  关注列表为空，跳过")
        return

    count = 0
    for symbol, name in watchlist:
        if not name or name == symbol:
            continue
        query = f"{name} 股票 新闻"
        try:
            import urllib.request, urllib.error
            body = json.dumps({
                "api_key": tavily_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": False,
                "include_raw_content": False,
                "days": 7,
                "search_lang": "zh",
            }).encode()
            req = urllib.request.Request("https://api.tavily.com/search",
                data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            results = data.get("results", [])
            if not results:
                continue

            conn2 = connect_db()
            for item in results:
                title = item.get("title", "")
                url = item.get("url", "")
                snippet = item.get("content", "")
                # 过滤掉纯英文结果
                has_chinese = any('\u4e00' <= c <= '\u9fff' for c in title + snippet)
                if not has_chinese:
                    continue
                # 尝试多个日期字段，依次降级
                import datetime
                _today = datetime.date.today().strftime("%Y-%m-%d")
                _raw_pub = (
                    item.get("published_date") or
                    item.get("crawl_date") or
                    item.get("pubDate") or
                    item.get("date") or
                    ""
                )
                # 提取 YYYY-MM-DD 格式
                import re
                _m = re.search(r"(\d{4}-\d{2}-\d{2})", str(_raw_pub))
                published = _m.group(1) if _m else _today
                source = item.get("url", "").split("/")[2] if item.get("url") else ""
                conn2.execute('''INSERT INTO news_daily
                    (symbol, title, url, snippet, publish_date, source)
                    VALUES (?,?,?,?,?,?)''',
                    (symbol, title, url, snippet, published, source))
                count += 1
            conn2.commit()
            conn2.close()
            log(f"  {name}: {len(results)} 条新闻")
        except Exception as e:
            log(f"  {name}: 新闻搜索异常: {e}")
        time.sleep(2)  # 避免频率限制

    log(f"  新闻搜索完成: {count} 条")

# ============================================================
# 14. 大盘复盘
# ============================================================
def sync_market_review():
    """获取每日大盘复盘数据"""
    log("=== 同步大盘复盘 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    db_execute(conn, '''CREATE TABLE IF NOT EXISTS market_review (
        trade_date TEXT PRIMARY KEY,
        index_data TEXT,
        up_count INTEGER,
        down_count INTEGER,
        flat_count INTEGER,
        limit_up INTEGER,
        limit_down INTEGER,
        top_sectors TEXT,
        bottom_sectors TEXT
    )''')

    today_str = datetime.now().strftime('%Y-%m-%d')
    review_date = today_str  # 实际有数据的日期

    try:
        # 1. 主要指数涨跌幅
        index_data = {}
        index_map = {'上证指数': 'sh000001', '深证成指': 'sz399001',
                     '创业板指': 'sz399006', '科创50': 'sh000688'}

        for idx_name, idx_code in index_map.items():
            try:
                prefix = idx_code[:2]
                code = idx_code[2:]
                df = ak.stock_zh_index_daily(symbol=idx_code)
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    close = float(latest.get('close', 0))
                    prev = float(df.iloc[-2].get('close', close)) if len(df) >= 2 else close
                    chg_pct = round((close - prev) / prev * 100, 2) if prev else 0
                    index_data[idx_name] = {'close': close, 'chg_pct': chg_pct}
            except Exception as e:
                log(f"  指数 {idx_name} 获取失败: {e}")

        # 2. 涨跌统计（从数据库计算，依赖日K线数据）
        try:
            # 用最近一个有足够数据的交易日（排除今天，今天16:05后才有数据）
            check_date = db_fetchone(
                conn,
                "SELECT trade_date FROM kline_daily WHERE trade_date < ? "
                "GROUP BY trade_date "
                "HAVING COUNT(*) > 4000 ORDER BY trade_date DESC LIMIT 1",
                (today_str,)
            )
            if check_date:
                review_date = check_date[0]
                stats = db_fetchone(conn, '''
                    SELECT 
                        SUM(CASE WHEN CAST(chg_pct AS REAL) > 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) < 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) = 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) >= 9.9 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) <= -9.9 THEN 1 ELSE 0 END)
                    FROM kline_daily WHERE trade_date = ?
                ''', (review_date,))
                up_count, down_count, flat_count, limit_up, limit_down = stats
                today_str = review_date
            else:
                up_count = down_count = flat_count = limit_up = limit_down = 0
        except Exception as e:
            log(f"  涨跌统计失败: {e}")
            up_count = down_count = flat_count = limit_up = limit_down = 0

        # 3. 板块表现
        top_sectors = []
        bottom_sectors = []
        try:
            df_board = ak.stock_board_industry_name_em()
            if df_board is not None and not df_board.empty:
                df_board_sorted = df_board.sort_values('涨跌幅', ascending=False)
                for _, row in df_board_sorted.head(5).iterrows():
                    top_sectors.append({'name': str(row.get('名称', '')),
                                        'chg_pct': float(row.get('涨跌幅', 0) or 0)})
                for _, row in df_board_sorted.tail(5).iterrows():
                    bottom_sectors.append({'name': str(row.get('名称', '')),
                                           'chg_pct': float(row.get('涨跌幅', 0) or 0)})
        except Exception as e:
            log(f"  板块数据失败: {e}")

        # 写入数据库
        db_execute(conn, sql_insert(
            'market_review',
            ['trade_date', 'index_data', 'up_count', 'down_count', 'flat_count',
             'limit_up', 'limit_down', 'top_sectors', 'bottom_sectors'],
            conflict_cols=['trade_date'],
            update_cols=['index_data', 'up_count', 'down_count', 'flat_count', 'limit_up', 'limit_down', 'top_sectors', 'bottom_sectors']
        ),
            (review_date, json.dumps(index_data, ensure_ascii=False),
             up_count, down_count, flat_count, limit_up, limit_down,
             json.dumps(top_sectors, ensure_ascii=False),
             json.dumps(bottom_sectors, ensure_ascii=False)))
        conn.commit()
        log(f"  大盘复盘完成: {review_date} 涨{up_count}/跌{down_count}/停{limit_up}+{limit_down}")

        # 发送飞书绿色卡片
        send_market_review_feishu(index_data, up_count, down_count, flat_count,
                                  limit_up, limit_down, top_sectors, bottom_sectors)

    except Exception as e:
        log(f"  大盘复盘失败: {e}")
    finally:
        conn.close()


def send_market_review_feishu(index_data, up_count, down_count, flat_count,
                               limit_up, limit_down, top_sectors, bottom_sectors):
    """发送大盘复盘飞书绿色卡片"""
    APP_ID = os.environ.get("APP_ID_BOT1", "cli_a926a8ecff789bd2")
    APP_SECRET = os.environ.get("APP_SECRET_BOT1", "tbVdK6gKIs6JicxjgmLkzfRJDjmHInyQ")
    OPEN_ID = os.environ.get("OPEN_ID_HEQIANG", "ou_7ae5f014203786f5051e13507b6675e0")

    today_str = datetime.now().strftime('%Y-%m-%d')

    # 指数行
    idx_lines = []
    for name, data in index_data.items():
        chg = data.get('chg_pct', 0)
        icon = "🔴" if chg > 0 else ("🟢" if chg < 0 else "⚪")
        idx_lines.append(f"{icon} {name}: {data.get('close', 0):.2f} ({chg:+.2f}%)")

    # 领涨板块
    sector_top = "\n".join([f"📈 {s['name']} {s['chg_pct']:+.2f}%" for s in top_sectors[:3]])
    sector_bot = "\n".join([f"📉 {s['name']} {s['chg_pct']:+.2f}%" for s in bottom_sectors[:3]])

    content = (
        f"**{today_str} 大盘复盘**\n\n"
        f"**主要指数:**\n" + "\n".join(idx_lines) + "\n\n"
        f"**涨跌统计:**\n"
        f"📈 上涨: {up_count}  📉 下跌: {down_count}  ⚪ 平盘: {flat_count}\n"
        f"🔴 涨停: {limit_up}  🟢 跌停: {limit_down}\n\n"
        f"**领涨板块:**\n{sector_top}\n\n"
        f"**领跌板块:**\n{sector_bot}"
    )

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 大盘复盘 {today_str}"},
            "template": "green"
        },
        "elements": [{"tag": "markdown", "content": content}]
    }

    try:
        r = subprocess.run(["curl", "-s", "-X", "POST",
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET})],
            capture_output=True, text=True, timeout=10)
        token = json.loads(r.stdout).get("tenant_access_token", "")

        if token:
            payload = json.dumps({"receive_id": OPEN_ID, "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False)}, ensure_ascii=False)
            subprocess.run(["curl", "-s", "-X", "POST",
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                "-H", f"Authorization: Bearer {token}",
                "-H", "Content-Type: application/json",
                "-d", payload],
                capture_output=True, text=True, timeout=10)
            log("  大盘复盘飞书卡片已发送")
        else:
            log("  飞书token获取失败")
    except Exception as e:
        log(f"  飞书卡片发送失败: {e}")

# ============================================================
# 15. 筹码分布数据
# ============================================================
def sync_chip_distribution():
    """获取关注列表股票的筹码分布数据"""
    log("=== 同步筹码分布 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    db_execute(conn, '''CREATE TABLE IF NOT EXISTS chip_distribution (
        symbol TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        chip_data TEXT,
        avg_cost REAL,
        profit_ratio REAL,
        concentration_90 REAL,
        concentration_70 REAL,
        PRIMARY KEY (symbol, trade_date)
    )''')

    # 读取关注列表
    watchlist = db_fetchall(conn, "SELECT symbol, name FROM watchlist")
    conn.close()

    if not watchlist:
        log("  关注列表为空，跳过")
        return

    today_str = datetime.now().strftime('%Y-%m-%d')
    count = 0
    failed = 0

    for symbol, name in watchlist:
        code = symbol[2:] if symbol.startswith(('sz', 'sh')) else symbol
        try:
            df = ak.stock_cyq_em(symbol=code)
            if df is None or df.empty:
                failed += 1
                continue

            chip_rows = []
            avg_cost = None
            profit_ratio = None
            conc_90 = None
            conc_70 = None

            # stock_cyq_em 返回筹码分布数据
            # 列名可能包含: 日期, 收盘价, 获利比例, 平均成本, 90集中度, 70集中度 等
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                chip_rows.append(row_dict)

            # 尝试从最后一行提取关键指标
            if chip_rows:
                last = chip_rows[-1]
                avg_cost = float(last.get('平均成本', last.get('avg_cost', 0)) or 0)
                profit_ratio = float(last.get('获利比例', last.get('profit_ratio', 0)) or 0)
                conc_90 = float(last.get('90集中度', last.get('concentration_90', 0)) or 0)
                conc_70 = float(last.get('70集中度', last.get('concentration_70', 0)) or 0)

            conn2 = connect_db()
            db_execute(conn2, sql_insert(
                'chip_distribution',
                ['symbol', 'trade_date', 'chip_data', 'avg_cost', 'profit_ratio', 'concentration_90', 'concentration_70'],
                conflict_cols=['symbol', 'trade_date'],
                update_cols=['chip_data', 'avg_cost', 'profit_ratio', 'concentration_90', 'concentration_70']
            ),
                (symbol, today_str, json.dumps(chip_rows, ensure_ascii=False, default=str),
                 avg_cost, profit_ratio, conc_90, conc_70))
            conn2.commit()
            conn2.close()
            count += 1
            log(f"  {name}({code}): 筹码数据已更新")
        except Exception as e:
            failed += 1
            log(f"  {name}({code}): 筹码数据失败: {e}")
        time.sleep(0.5)

    log(f"  筹码分布完成: 成功{count}, 失败{failed}")

# ============================================================
# 16. 大盘指数K线
# ============================================================
INDEX_SYMBOLS = {
    'sh000001': '上证指数',
    'sz399001': '深证成指',
    'sz399006': '创业板指',
    'sh000016': '上证50',
}

def sync_index_kline():
    """同步大盘指数日K线"""
    log("=== 同步大盘指数K线 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    total = 0

    for symbol, name in INDEX_SYMBOLS.items():
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                log(f"  {name}({symbol}): 无数据")
                continue

            latest = db_fetchone(
                conn,
                "SELECT MAX(trade_date) FROM kline_daily_index WHERE symbol=?",
                (symbol,)
            )[0]
            if latest and not isinstance(latest, str):
                latest = str(latest)

            count = 0
            for _, row in df.iterrows():
                trade_date = str(row['date'])[:10]
                if latest and trade_date <= latest:
                    continue

                close = float(row.get('close', 0) or 0)
                prev_close = None
                prev = db_fetchone(
                    conn,
                    "SELECT close FROM kline_daily_index WHERE symbol=? AND trade_date<? ORDER BY trade_date DESC LIMIT 1",
                    (symbol, trade_date)
                )
                if prev:
                    prev_close = prev[0]

                pct_change = ((close - prev_close) / prev_close * 100) if prev_close else 0

                db_execute(conn, sql_insert(
                    'kline_daily_index',
                    ['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_change'],
                    conflict_cols=['symbol', 'trade_date'],
                    update_cols=['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_change']
                ),
                    (symbol, trade_date,
                     float(row.get('open', 0) or 0),
                     float(row.get('high', 0) or 0),
                     float(row.get('low', 0) or 0),
                     close,
                     float(row.get('volume', 0) or 0),
                     0, pct_change))
                count += 1

            conn.commit()
            total += count
            if count > 0:
                log(f"  {name}({symbol}): +{count}条")
        except Exception as e:
            log(f"  {name}({symbol}): 失败 {e}")
        time.sleep(0.5)

    if total > 0:
        _calc_index_indicators(conn)
    conn.close()
    log(f"  指数K线完成: 共新增{total}条")

def _calc_index_indicators(conn):
    """计算大盘指数的MA5/MA10/MA20和RSI14"""
    for symbol in INDEX_SYMBOLS:
        rows = db_fetchall(
            conn,
            "SELECT trade_date, close FROM kline_daily_index WHERE symbol=? ORDER BY trade_date",
            (symbol,)
        )
        if len(rows) < 20:
            continue
        closes = [r[1] for r in rows]
        dates = [r[0] for r in rows]
        for i in range(len(rows)):
            updates = {}
            if i >= 4:
                updates['ma5'] = sum(closes[i-4:i+1]) / 5
            if i >= 9:
                updates['ma10'] = sum(closes[i-9:i+1]) / 10
            if i >= 19:
                updates['ma20'] = sum(closes[i-19:i+1]) / 20
            if i >= 14:
                gains, losses = [], []
                for j in range(i-13, i+1):
                    diff = closes[j] - closes[j-1]
                    gains.append(max(diff, 0))
                    losses.append(max(-diff, 0))
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                if avg_loss == 0:
                    updates['rsi14'] = 100
                else:
                    rs = avg_gain / avg_loss
                    updates['rsi14'] = 100 - (100 / (1 + rs))
            if updates:
                set_clause = ', '.join(f'{k}=?' for k in updates)
                vals = list(updates.values()) + [symbol, dates[i]]
                db_execute(conn, f"UPDATE kline_daily_index SET {set_clause} WHERE symbol=? AND trade_date=?", tuple(vals))
    conn.commit()
    log("  指数技术指标已更新")

# ============================================================
# 17. 龙虎榜
# ============================================================
def sync_lhb():
    """同步龙虎榜数据"""
    log("=== 同步龙虎榜 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(trade_date) FROM lhb_detail")[0]
    conn.close()

    dates_to_fetch = []
    d = datetime.now()
    while len(dates_to_fetch) < 10:
        if d.weekday() < 5:
            dates_to_fetch.append(d.strftime('%Y%m%d'))
        d -= timedelta(days=1)

    if latest:
        dates_to_fetch = [dt for dt in dates_to_fetch if dt > latest.replace('-', '')]

    if not dates_to_fetch:
        log("  龙虎榜已是最新")
        return

    start = min(dates_to_fetch)
    end = max(dates_to_fetch)
    count = 0

    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        if df is None or df.empty:
            log("  无龙虎榜数据")
            return

        conn = connect_db()
        for _, row in df.iterrows():
            trade_date = str(row.get('上榜日', ''))[:10]
            if latest and trade_date <= latest:
                continue
            try:
                db_execute(conn, sql_insert(
                    'lhb_detail',
                    ['trade_date', 'code', 'name', 'reason', 'buy_amount', 'sell_amount',
                     'net_amount', 'turnover', 'mkt_cap', 'chg_after_1d', 'chg_after_5d',
                     'buy_seats', 'sell_seats', 'data_source'],
                    conflict_cols=['trade_date', 'code', 'reason'],
                    ignore=True
                ),
                    (trade_date,
                     str(row.get('代码', '')),
                     str(row.get('名称', '')),
                     str(row.get('上榜原因', '')),
                     float(row.get('龙虎榜买入额', 0) or 0),
                     float(row.get('龙虎榜卖出额', 0) or 0),
                     float(row.get('龙虎榜净买额', 0) or 0),
                     float(row.get('成交额占总成交比', 0) or 0),
                     float(row.get('流通市值', 0) or 0),
                     float(row.get('上榜后1日', 0) or 0) if row.get('上榜后1日') else None,
                     float(row.get('上榜后5日', 0) or 0) if row.get('上榜后5日') else None,
                     str(row.get('解读', '')),
                     '',
                     'eastmoney'))
                count += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"  龙虎榜获取失败: {e}")
        return

    log(f"  龙虎榜完成: +{count}条")

# ============================================================
# 18. 大宗交易
# ============================================================
def sync_block_trades():
    """同步大宗交易数据"""
    log("=== 同步大宗交易 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(trade_date) FROM block_trades")[0]
    conn.close()

    if not latest:
        start = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    else:
        start = (datetime.strptime(latest, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y%m%d')

    end = datetime.now().strftime('%Y%m%d')
    if start > end:
        log("  大宗交易已是最新")
        return

    count = 0
    try:
        df = ak.stock_dzjy_mrtj(start_date=start, end_date=end)
        if df is None or df.empty:
            log("  无大宗交易数据")
            return

        conn = connect_db()
        for _, row in df.iterrows():
            trade_date = str(row.get('交易日期', ''))[:10]
            try:
                db_execute(conn, sql_insert(
                    'block_trades',
                    ['trade_date', 'code', 'name', 'price', 'volume', 'amount', 'buyer', 'seller'],
                    conflict_cols=['trade_date', 'code', 'price'],
                    ignore=True
                ),
                    (trade_date,
                     str(row.get('证券代码', '')),
                     str(row.get('证券简称', '')),
                     float(row.get('成交价', 0) or 0),
                     float(row.get('成交总量', 0) or 0),
                     float(row.get('成交总额', 0) or 0),
                     '', ''))
                count += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"  大宗交易获取失败: {e}")
        return

    log(f"  大宗交易完成: +{count}条")

# ============================================================
# 18. 北向持股增量更新
# ============================================================
def sync_northbound_holdings():
    """获取北向持股数据（按个股）"""
    log("=== 同步北向持股 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return
    _clear_proxy()

    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(trade_date) FROM northbound_holdings")[0]
    if latest and not isinstance(latest, str):
        latest = str(latest)
    # 获取有K线数据的股票列表
    symbols = [r[0] for r in db_fetchall(conn, "SELECT DISTINCT symbol FROM kline_daily ORDER BY symbol")]
    conn.close()

    count = 0
    failed = 0
    for i, sym in enumerate(symbols):
        code = sym[2:] if sym.startswith(('sz', 'sh')) else sym
        try:
            df = ak.stock_hsgt_individual_em(symbol=code)
            if df is None or df.empty:
                failed += 1
                continue
            conn2 = connect_db()
            for _, row in df.iterrows():
                d = str(row.get('持股日期', ''))
                if latest and d <= latest:
                    continue
                shares = float(row.get('持股数量', 0) or 0)
                pct = float(row.get('持股数量占A股百分比', 0) or 0)
                if shares <= 0:
                    continue
                db_execute(conn2, sql_insert(
                    'northbound_holdings',
                    ['symbol', 'trade_date', 'hold_shares', 'hold_pct'],
                    conflict_cols=['symbol', 'trade_date'],
                    update_cols=['hold_shares', 'hold_pct']
                ), (sym, d, shares, pct))
                count += 1
            conn2.commit()
            conn2.close()
        except Exception as e:
            failed += 1

        if (i + 1) % 100 == 0:
            log(f"  北向持股进度: {i+1}/{len(symbols)} 新增{count} 失败{failed}")

    log(f"  北向持股完成: 新增{count}条, 失败{failed}只")

# ============================================================
# 19. 融资融券明细增量更新
# ============================================================
def sync_stock_margin_detail():
    """获取融资融券明细数据（上交所+深交所）"""
    log("=== 同步融资融券明细 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return
    _clear_proxy()

    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(trade_date) FROM stock_margin_detail")[0]
    if latest and not isinstance(latest, str):
        latest = str(latest)
    conn.close()

    count = 0
    # 从最近的日期开始往回找，最多尝试10天
    from datetime import datetime, timedelta
    today = datetime.now()
    for delta in range(0, 10):
        d = (today - timedelta(days=delta)).strftime('%Y%m%d')
        if latest and d <= latest:
            break

        # 上交所
        try:
            df_sse = ak.stock_margin_detail_sse(date=d)
            if df_sse is not None and not df_sse.empty:
                conn2 = connect_db()
                for _, row in df_sse.iterrows():
                    code = str(row.get('标的证券代码', ''))
                    if not code:
                        continue
                    symbol = f"sh{code}"
                    db_execute(conn2, sql_insert(
                        'stock_margin_detail',
                        ['trade_date', 'symbol', 'name', 'margin_balance', 'margin_buy', 'margin_repay',
                         'short_volume', 'short_sell', 'short_repay'],
                        conflict_cols=['trade_date', 'symbol'],
                        update_cols=['margin_balance', 'margin_buy', 'margin_repay',
                                     'short_volume', 'short_sell', 'short_repay']
                    ), (
                        d, symbol, str(row.get('标的证券简称', '')),
                        float(row.get('融资余额', 0) or 0),
                        float(row.get('融资买入额', 0) or 0),
                        float(row.get('融资偿还额', 0) or 0),
                        float(row.get('融券余量', 0) or 0),
                        float(row.get('融券卖出量', 0) or 0),
                        float(row.get('融券偿还量', 0) or 0)
                    ))
                    count += 1
                conn2.commit()
                conn2.close()
        except Exception as e:
            log(f"  上交所融资融券 {d} 失败: {e}")

        # 深交所
        try:
            df_szse = ak.stock_margin_detail_szse(date=d)
            if df_szse is not None and not df_szse.empty:
                conn2 = connect_db()
                for _, row in df_szse.iterrows():
                    code = str(row.get('证券代码', ''))
                    if not code:
                        continue
                    symbol = f"sz{code}"
                    db_execute(conn2, sql_insert(
                        'stock_margin_detail',
                        ['trade_date', 'symbol', 'name', 'margin_balance', 'margin_buy', 'margin_repay',
                         'short_volume', 'short_sell', 'short_repay'],
                        conflict_cols=['trade_date', 'symbol'],
                        update_cols=['margin_balance', 'margin_buy', 'margin_repay',
                                     'short_volume', 'short_sell', 'short_repay']
                    ), (
                        d, symbol, str(row.get('证券简称', '')),
                        float(row.get('融资余额', 0) or 0),
                        float(row.get('融资买入额', 0) or 0),
                        0,  # 深交所无融资偿还额
                        float(row.get('融券余量', 0) or 0),
                        float(row.get('融券卖出量', 0) or 0),
                        0   # 深交所无融券偿还量
                    ))
                    count += 1
                conn2.commit()
                conn2.close()
        except Exception as e:
            log(f"  深交所融资融券 {d} 失败: {e}")

    log(f"  融资融券明细完成: 新增{count}条")

# ============================================================
# 20. 业绩预告增量更新
# ============================================================
def sync_earnings_forecast():
    """获取业绩预告数据"""
    log("=== 同步业绩预告 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return
    _clear_proxy()

    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(report_date) FROM earnings_forecast")[0]
    conn.close()

    count = 0
    # 获取最近几个季度的报告期
    now = datetime.now()
    quarters = []
    for year in range(now.year - 1, now.year + 1):
        for q_end in ['0331', '0630', '0930', '1231']:
            q = f"{year}{q_end}"
            if latest and q <= str(latest):
                continue
            quarters.append(q)

    for q in quarters:
        try:
            df = ak.stock_yjyg_em(date=q)
            if df is None or df.empty:
                continue
            conn2 = connect_db()
            for _, row in df.iterrows():
                code = str(row.get('股票代码', ''))
                if not code:
                    continue
                db_execute(conn2, sql_insert(
                    'earnings_forecast',
                    ['code', 'name', 'report_date', 'forecast_type', 'forecast_content',
                     'profit_min', 'profit_max', 'forecast_change_min', 'forecast_change_max',
                     'reason', 'prev_year_value', 'announce_date'],
                    conflict_cols=['code', 'report_date', 'forecast_type'],
                    update_cols=['name', 'forecast_content', 'profit_min', 'profit_max',
                                 'forecast_change_min', 'forecast_change_max', 'reason', 'prev_year_value', 'announce_date']
                ), (
                    code, str(row.get('股票简称', '')), q,
                    str(row.get('预告类型', '')),
                    str(row.get('业绩变动', '')),
                    float(row.get('预测数值', 0) or 0),
                    float(row.get('预测数值', 0) or 0),
                    float(row.get('业绩变动幅度', 0) or 0),
                    float(row.get('业绩变动幅度', 0) or 0),
                    str(row.get('业绩变动原因', '')),
                    float(row.get('上年同期值', 0) or 0),
                    str(row.get('公告日期', ''))
                ))
                count += 1
            conn2.commit()
            conn2.close()
            log(f"  业绩预告 {q}: +{len(df)}条")
        except Exception as e:
            log(f"  业绩预告 {q} 失败: {e}")

    log(f"  业绩预告完成: 新增{count}条")

# ============================================================
# 21. 分红送转增量更新
# ============================================================
def sync_dividends():
    """获取分红送转数据"""
    log("=== 同步分红送转 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return
    _clear_proxy()

    conn = connect_db()
    latest = db_fetchone(conn, "SELECT MAX(pay_date) FROM dividends WHERE pay_date IS NOT NULL AND pay_date != ''")[0]
    conn.close()

    count = 0
    now = datetime.now()
    for year in range(now.year - 2, now.year + 1):
        for q_end in ['0630', '1231']:
            q = f"{year}{q_end}"
            if latest and q <= str(latest):
                continue
            try:
                df = ak.stock_fhps_em(date=q)
                if df is None or df.empty:
                    continue
                conn2 = connect_db()
                for _, row in df.iterrows():
                    code = str(row.get('代码', ''))
                    if not code:
                        continue
                    db_execute(conn2, sql_insert(
                        'dividends',
                        ['stock_code', 'stock_name', 'announce_date', 'div_type',
                         'bonus_ratio', 'transfer_ratio', 'cash_div',
                         'record_date', 'ex_div_date', 'pay_date',
                         'shares_arrive_date', 'div_desc', 'report_period'],
                        conflict_cols=['stock_code', 'report_period'],
                        update_cols=['announce_date', 'div_type', 'bonus_ratio', 'transfer_ratio',
                                     'cash_div', 'record_date', 'ex_div_date', 'pay_date',
                                     'shares_arrive_date', 'div_desc']
                    ), (
                        code, str(row.get('名称', '')),
                        str(row.get('最新公告日期', '')),
                        '分红送转',
                        float(row.get('送转股份-送转总比例', 0) or 0),
                        float(row.get('送股比例', 0) or 0),
                        float(row.get('现金分红-现金分红比例', 0) or 0),
                        str(row.get('股权登记日', '')),
                        str(row.get('除权除息日', '')),
                        str(row.get('最新公告日期', '')),
                        str(row.get('红股上市日', '')),
                        str(row.get('方案进度', '')),
                        q
                    ))
                    count += 1
                conn2.commit()
                conn2.close()
                log(f"  分红送转 {q}: +{len(df)}条")
            except Exception as e:
                log(f"  分红送转 {q} 失败: {e}")

    log(f"  分红送转完成: 新增{count}条")

# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='每日数据同步')
    parser.add_argument('--kline', action='store_true', help='只同步日K线')
    parser.add_argument('--fund', action='store_true', help='只同步财务指标')
    parser.add_argument('--tech', action='store_true', help='只重算技术指标')
    parser.add_argument('--weekly', action='store_true', help='只同步周K线')
    parser.add_argument('--monthly', action='store_true', help='只同步月K线')
    parser.add_argument('--valuation', action='store_true', help='只同步估值')
    parser.add_argument('--flow', action='store_true', help='只同步资金流向')
    parser.add_argument('--industry', action='store_true', help='只同步行业板块')
    parser.add_argument('--northbound', action='store_true', help='只同步北向资金')
    parser.add_argument('--margin', action='store_true', help='只同步融资融券')
    parser.add_argument('--shareholder', action='store_true', help='只同步股东数据')
    parser.add_argument('--shareholder-limit', type=int, default=500, help='股东数据单次更新股票数，默认500')
    parser.add_argument('--limit', action='store_true', help='只同步涨跌停')
    parser.add_argument('--news', action='store_true', help='只同步新闻')
    parser.add_argument('--review', action='store_true', help='只同步大盘复盘')
    parser.add_argument('--chip', action='store_true', help='只同步筹码分布')
    parser.add_argument('--index', action='store_true', help='只同步大盘指数K线')
    parser.add_argument('--lhb', action='store_true', help='只同步龙虎榜')
    parser.add_argument('--block', action='store_true', help='只同步大宗交易')
    parser.add_argument('--northbound-holdings', action='store_true', help='只同步北向持股')
    parser.add_argument('--margin-detail', action='store_true', help='只同步融资融券明细')
    parser.add_argument('--earnings', action='store_true', help='只同步业绩预告')
    parser.add_argument('--dividends', action='store_true', help='只同步分红送转')
    parser.add_argument('--full', action='store_true', help='全量同步（包含周/月K线）')
    args = parser.parse_args()

    run_all = args.full
    # 只在没有指定任何单项参数时，才跑全部每日流程
    single_flags = [args.kline, args.fund, args.tech, args.weekly, args.monthly,
                    args.valuation, args.flow, args.industry, args.northbound,
                    args.margin, args.shareholder, args.limit,
                    args.news, args.review, args.chip,
                    args.index, args.lhb, args.block,
                    args.northbound_holdings, args.margin_detail, args.earnings, args.dividends]
    run_daily = not any(single_flags) and not args.full

    log(f"{'='*50}")
    log(f"每日数据同步开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"{'='*50}")

    start_time = time.time()
    capital_flow_status = None

    # 每日必跑（日K线 + 技术指标 + 估值 + 资金流向）
    if run_all or run_daily or args.kline:
        sync_daily_kline()
    if run_all or run_daily or args.tech:
        recalc_technical_indicators()
    if run_all or run_daily or args.valuation:
        sync_valuation()

    # 财务指标（滚动更新500只 + 每日快照）
    if run_all or run_daily or args.fund:
        sync_financial_indicators()
        build_financial_daily()

    # 资金流向 & 行业板块（每日更新）
    if run_all or run_daily or args.flow:
        capital_flow_status = sync_capital_flow()
    if run_all or run_daily or args.industry:
        sync_industry()

    # 新增数据源（每日更新）
    if run_all or run_daily or args.northbound:
        sync_northbound_flow()
    if run_all or run_daily or args.margin:
        sync_margin_data()
    if run_all or run_daily or args.shareholder:
        sync_shareholder_data(limit=args.shareholder_limit)
    if run_all or run_daily or args.limit:
        sync_limit_up_down()

    # 新增功能
    if run_all or run_daily or args.news:
        sync_news()
    if run_all or run_daily or args.review:
        sync_market_review()
    if run_all or run_daily or args.chip:
        sync_chip_distribution()

    # 新增数据源 v2
    if run_all or run_daily or args.index:
        sync_index_kline()
    if run_all or run_daily or args.lhb:
        sync_lhb()
    if run_all or run_daily or args.block:
        sync_block_trades()

    # 新增数据源 v3
    if run_all or run_daily or args.northbound_holdings:
        sync_northbound_holdings()
    if run_all or run_daily or args.margin_detail:
        sync_stock_margin_detail()
    if run_all or run_daily or args.earnings:
        sync_earnings_forecast()
    if run_all or run_daily or args.dividends:
        sync_dividends()

    # 周/月K线（仅周末或 --full 时跑，数据量大）
    if run_all or args.weekly:
        sync_weekly_kline()
    if run_all or args.monthly:
        sync_monthly_kline()

    elapsed = time.time() - start_time
    log(f"{'='*50}")
    log(f"同步完成! 耗时: {elapsed/60:.1f} 分钟")
    log(f"{'='*50}")

    # 校验 & 飞书告警
    if not any([args.kline, args.fund, args.tech, args.weekly, args.monthly,
                args.valuation, args.flow, args.industry, args.northbound,
                args.margin, args.shareholder, args.limit,
                args.news, args.review, args.chip,
                args.index, args.lhb, args.block,
                args.northbound_holdings, args.margin_detail, args.earnings, args.dividends]):
        validate_and_report(elapsed, capital_flow_status)

# ============================================================
# 校验 & 飞书告警
# ============================================================
def validate_and_report(elapsed, capital_flow_status=None):
    """同步后校验数据完整性，异常发飞书告警"""
    log("=== 数据完整性校验 ===")
    conn = connect_db()
    today = datetime.now().strftime('%Y-%m-%d')
    errors = []
    warnings = []
    stats = {}

    # 1. 日K线 — 最新日期
    latest_kline = db_fetchone(conn, "SELECT MAX(trade_date) FROM kline_daily")[0]
    kline_today = db_fetchone(conn, "SELECT COUNT(*) FROM kline_daily WHERE trade_date=?", (latest_kline,))[0]
    total_stocks = db_fetchone(conn, "SELECT COUNT(DISTINCT symbol) FROM kline_daily")[0]
    stats['kline'] = f"{latest_kline} {kline_today}/{total_stocks}只"

    if not latest_kline or latest_kline < (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'):
        errors.append(f"日K线严重滞后: 最新{latest_kline}")
    elif kline_today < 3000:
        warnings.append(f"日K线偏少: {latest_kline}只有{kline_today}只（期望≥4000）")

    # 2. 技术指标 — RSI/MA
    has_rsi = db_fetchone(conn, "SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND rsi14 IS NOT NULL", (latest_kline,))[0]
    if has_rsi < kline_today * 0.7:
        warnings.append(f"RSI计算不全: {has_rsi}/{kline_today}只")

    # 3. 资金流向
    flow_latest = db_fetchone(conn, "SELECT MAX(trade_date) FROM capital_flow")[0]
    flow_count = db_fetchone(conn, "SELECT COUNT(*) FROM capital_flow WHERE trade_date=?", (flow_latest,))[0] if flow_latest else 0
    stats['capital_flow'] = f"{flow_latest} {flow_count}只"
    if capital_flow_status and capital_flow_status.get('status') == 'degraded':
        warnings.append(
            f"资金流已降级: 最新{capital_flow_status.get('latest_available_date')} {capital_flow_status.get('latest_count', 0)}只, 原因={capital_flow_status.get('reason')}"
        )

    # 4. 估值
    val_latest = db_fetchone(conn, "SELECT MAX(trade_date) FROM daily_valuation")[0]
    val_count = db_fetchone(conn, "SELECT COUNT(*) FROM daily_valuation WHERE trade_date=?", (val_latest,))[0] if val_latest else 0
    stats['valuation'] = f"{val_latest} {val_count}只"

    # 5. 北向资金
    nb_latest = db_fetchone(conn, "SELECT MAX(date) FROM northbound_flow")[0]
    stats['northbound'] = nb_latest or "无数据"

    # 6. 融资融券
    margin_latest = db_fetchone(conn, "SELECT MAX(date) FROM margin_data")[0]
    stats['margin'] = margin_latest or "无数据"

    # 7. 涨跌停
    limit_latest = db_fetchone(conn, "SELECT MAX(date) FROM limit_up_down")[0]
    stats['limit_up_down'] = limit_latest or "无数据"

    # 8. 财务指标
    fund_count = db_fetchone(conn, "SELECT COUNT(DISTINCT symbol) FROM financial_indicators WHERE roe IS NOT NULL")[0]
    stats['financial'] = f"{fund_count}只"
    if fund_count < 3000:
        warnings.append(f"财务指标偏少: {fund_count}只")

    conn.close()

    write_sync_status({
        'pipeline_stage': 'extended',
        'ready': len(errors) == 0,
        'today': today,
        'target_date': latest_kline,
        'validation_errors': errors,
        'validation_warnings': warnings,
        'stats': stats,
        'capital_flow': capital_flow_status or {
            'status': 'unknown',
            'latest_available_date': flow_latest,
            'latest_count': flow_count,
        },
    })

    # 判断是否正常
    status = "❌ 异常" if errors else ("⚠️ 警告" if warnings else "✅ 正常")
    log(f"校验结果: {status}")
    for e in errors:
        log(f"  ❌ {e}")
    for w in warnings:
        log(f"  ⚠️ {w}")

    # 飞书告警
    if errors or warnings:
        send_feishu_alert(status, errors, warnings, stats, elapsed)
    else:
        log("  全部正常，不发告警")

def send_feishu_alert(status, errors, warnings, stats, elapsed):
    """发送飞书告警"""
    APP_ID = os.environ.get("APP_ID_BOT1", "cli_a926a8ecff789bd2")
    APP_SECRET = os.environ.get("APP_SECRET_BOT1", "tbVdK6gKIs6JicxjgmLkzfRJDjmHInyQ")
    OPEN_ID = os.environ.get("OPEN_ID_HEQIANG", "ou_7ae5f014203786f5051e13507b6675e0")

    lines = [f"**{status}** 耗时 {elapsed/60:.1f}分钟\n"]
    if errors:
        lines.append("**错误:**")
        for e in errors:
            lines.append(f"❌ {e}")
        lines.append("")
    if warnings:
        lines.append("**警告:**")
        for w in warnings:
            lines.append(f"⚠️ {w}")
        lines.append("")

    lines.append("**数据概览:**")
    for k, v in stats.items():
        lines.append(f"• {k}: {v}")

    content = "\n".join(lines)

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 数据同步报告 {status}"},
            "template": "red" if errors else ("orange" if warnings else "green")
        },
        "elements": [{"tag": "markdown", "content": content}]
    }

    try:
        r = subprocess.run(["curl", "-s", "-X", "POST",
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET})],
            capture_output=True, text=True, timeout=10)
        token = json.loads(r.stdout).get("tenant_access_token", "")

        if token:
            payload = json.dumps({"receive_id": OPEN_ID, "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False)}, ensure_ascii=False)
            r2 = subprocess.run(["curl", "-s", "-X", "POST",
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                "-H", f"Authorization: Bearer {token}",
                "-H", "Content-Type: application/json",
                "-d", payload],
                capture_output=True, text=True, timeout=10)
            log("  飞书告警已发送")
        else:
            log("  飞书token获取失败")
    except Exception as e:
        log(f"  飞书告警发送失败: {e}")

if __name__ == '__main__':
    main()
