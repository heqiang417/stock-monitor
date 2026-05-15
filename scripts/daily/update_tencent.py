#!/usr/bin/env python3
"""
股票数据增量更新 - 腾讯财经为主数据源
腾讯能提供的用腾讯，腾讯没有的用其他源

同步内容：
1. 日K线（腾讯）+ 技术指标重算
2. 指数日K线（腾讯）+ 技术指标重算
3. 周K线（腾讯）
4. 月K线（腾讯）
5. 估值数据 PE/PB（腾讯实时 → 写入当日）
6. 财务指标（akshare fallback）

用法：
  python3 update_tencent.py              # 默认增量1天
  python3 update_tencent.py --days 5     # 增量5天
  python3 update_tencent.py --full       # 全量同步（周末用）
  python3 update_tencent.py --kline      # 只同步K线
  python3 update_tencent.py --fund       # 只同步财务指标
"""

import os, sys, json, time, random, argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import requests
import urllib3
from urllib.parse import urlparse
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from sync_health import (
    assess_trade_date_health,
    find_best_trade_date,
    write_sync_status,
)

# 让脚本可复用项目里的 PG/SQLite 兼容 DB 层
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

env_file = os.path.join(PROJECT_ROOT, '.env')
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

from db import _is_postgres_target, _sqlite_placeholders_to_pyformat
from data_provider.akshare_fetcher import AkshareFetcher

# === 配置 ===
DEFAULT_DB_PATH = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
DB_TARGET = os.environ.get('POSTGRES_DSN') or os.environ.get('PG_DSN') or os.environ.get('DATABASE_URL') or os.environ.get('DB_DSN') or os.environ.get('STOCK_DB') or DEFAULT_DB_PATH
DB_PATH = DB_TARGET
DB_IS_POSTGRES = _is_postgres_target(DB_TARGET)
REQUIRE_PG = os.environ.get('REQUIRE_PG', '1') == '1'
if REQUIRE_PG and not DB_IS_POSTGRES:
    raise RuntimeError(
        f"update_tencent.py requires PostgreSQL for production, but resolved DB_TARGET={DB_TARGET!r}. "
        f"Remove SQLite STOCK_DB override or set POSTGRES_DSN/PG_DSN/DATABASE_URL."
    )
STOCKS_FILE = os.environ.get('STOCKS_FILE',
    '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/stock_data_full.json')
READY_FLAG = '/tmp/stock_data_ready.flag'
INDEX_SYMBOLS = [
    'sh000001',  # 上证指数
    'sz399001',  # 深证成指
    'sz399006',  # 创业板指
    'sh000688',  # 科创50
    'sh000300',  # 沪深300
    'sh000905',  # 中证500
    'sh000852',  # 中证1000
]

# === 参数解析 ===
parser = argparse.ArgumentParser(description='腾讯股票数据更新')
parser.add_argument('--days', type=int, default=1, help='增量天数')
parser.add_argument('--full', action='store_true', help='全量同步')
parser.add_argument('--kline', action='store_true', help='只同步K线')
parser.add_argument('--fund', action='store_true', help='只同步财务指标')
parser.add_argument('--no-weekly', action='store_true', help='跳过周K线')
parser.add_argument('--no-monthly', action='store_true', help='跳过月K线')
parser.add_argument('--target-date', help='指定目标交易日（YYYY-MM-DD），用于补历史某一天的数据')
parser.add_argument('--light-target-date', action='store_true', help='指定目标日时启用轻量补数：跳过估值/周月K，只补该日K线+指标')
args = parser.parse_args()

INCR_DAYS = 60 if args.full else args.days
TODAY = args.target_date or datetime.now().strftime('%Y-%m-%d')
TARGET_DATE_MODE = bool(args.target_date)
LIGHT_TARGET_DATE_MODE = bool(args.light_target_date or args.target_date)
MIN_STOCKS = 4000
VALID_LOOKBACK_DAYS = 10
if TARGET_DATE_MODE:
    beg_date = (datetime.strptime(TODAY, '%Y-%m-%d') - timedelta(days=max(INCR_DAYS + 10, 35))).strftime('%Y-%m-%d')
else:
    beg_date = (datetime.now() - timedelta(days=INCR_DAYS + 10)).strftime('%Y-%m-%d')
end_date = TODAY

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


def get_conn():
    if DB_IS_POSTGRES:
        import psycopg2
        conn = psycopg2.connect(**_postgres_connect_kwargs(DB_TARGET))
        conn.autocommit = False
        return conn
    from db import connect_db
    return connect_db(DB_PATH)


def _q(sql: str) -> str:
    return _sqlite_placeholders_to_pyformat(sql) if DB_IS_POSTGRES else sql


def _exec(conn, sql: str, params=()):
    cur = conn.cursor()
    if params is None:
        cur.execute(_q(sql))
    else:
        cur.execute(_q(sql), params)
    return cur


def _execmany(conn, sql: str, params_list):
    cur = conn.cursor()
    cur.executemany(_q(sql), params_list)
    return cur


def _fetchall(cur):
    rows = cur.fetchall()
    return [tuple(r.values()) if isinstance(r, dict) else tuple(r) for r in rows]


def _fetchone(cur):
    row = cur.fetchone()
    if row is None:
        return None
    return tuple(row.values()) if isinstance(row, dict) else tuple(row)


def _table_exists(conn, name: str) -> bool:
    if DB_IS_POSTGRES:
        row = _fetchone(_exec(conn, "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s LIMIT 1", (name,)))
        return bool(row)
    row = _fetchone(_exec(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)))
    return bool(row)


def _upsert_kline_sql(table: str) -> str:
    return f'''INSERT INTO {table}
        (symbol, trade_date, open, close, high, low, volume, amount, chg, chg_pct)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(symbol, trade_date) DO UPDATE SET
        open=excluded.open, close=excluded.close, high=excluded.high, low=excluded.low,
        volume=excluded.volume, amount=excluded.amount, chg=excluded.chg, chg_pct=excluded.chg_pct'''


def get_runtime_python() -> str:
    """Prefer configured runtime python when the path exists; otherwise fall back safely."""
    candidates = [
        os.environ.get('RUNTIME_PYTHON'),
        os.path.join(PROJECT_ROOT, '.venv', 'bin', 'python'),
        sys.executable,
        '/usr/bin/python3',
    ]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        if os.access(candidate, os.X_OK):
            return candidate
    return sys.executable or 'python3'



# === 日志 ===
LOG_DIR = os.environ.get('SYNC_LOG_DIR', os.path.join(PROJECT_ROOT, 'logs'))
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f'tencent_sync_{TODAY}.log')

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(log_file, 'a') as f:
            f.write(line + '\n')
    except:
        pass

# === 加载股票列表 ===
with open(STOCKS_FILE) as f:
    _data = json.load(f)
stocks = _data.get('stocks', [])

stock_list = []
for s in stocks:
    sym = s.get('symbol', '')
    if not sym.startswith(('sz', 'sh')):
        sym = f'sh{sym}' if sym.startswith('6') else f'sz{sym}'
    stock_list.append(sym)

VALID_SYMBOL_PREFIXES = ('sz', 'sh')

def is_valid_symbol(symbol: str) -> bool:
    if not symbol or not symbol.startswith(VALID_SYMBOL_PREFIXES):
        return False
    code = symbol[2:]
    return code.isdigit() and len(code) == 6

FETCH_STATS = {
    'kline': {'network_error': 0, 'parse_error': 0, 'empty_payload': 0, 'success': 0},
    'quote': {'network_error': 0, 'parse_error': 0, 'empty_payload': 0, 'success': 0},
    'fallback': {'attempt': 0, 'success': 0, 'no_today': 0, 'error': 0},
}
FETCH_STATS_LOCK = threading.Lock()
_AKSHARE_FETCHER = None
_AKSHARE_LOCK = threading.Lock()


def _bump_fetch_stat(kind, key):
    with FETCH_STATS_LOCK:
        FETCH_STATS.setdefault(kind, {}).setdefault(key, 0)
        FETCH_STATS[kind][key] += 1

log(f'股票总数: {len(stock_list)}, 增量: {INCR_DAYS} 天, 模式: {"全量" if args.full else "增量"}')

# ============================================================
# 腾讯 API 函数
# ============================================================

def _get_session():
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": "", "https": ""}
    return s

def fetch_tencent_kline(symbol, period='day'):
    """腾讯财经API获取K线（日/周/月）
    period: day / week / month
    支持普通股票(symbol=sz000001/sh600000)和指数(symbol=sh000001/sz399001)
    """
    if symbol.startswith('sz'):
        tsym = f'sz{symbol[2:]}'
    elif symbol.startswith('sh'):
        tsym = f'sh{symbol[2:]}'
    else:
        tsym = symbol

    session = _get_session()
    last_error_kind = 'network_error'
    for _ in range(2):
        try:
            r = session.get(
                'https://43.154.254.185/appstock/app/fqkline/get',
                verify=False,
                headers={'Host': 'web.ifzq.gtimg.cn'}, params={'param': f'{tsym},{period},{beg_date},{end_date},{INCR_DAYS+10},qfq'},
                timeout=15
            )
            d = r.json()
            data = d.get('data', {}).get(tsym, {})
            days = data.get(period, []) or data.get(f'qfq{period}', [])
            if not days:
                last_error_kind = 'empty_payload'
                time.sleep(0.2)
                continue

            result = []
            for row in days:
                if len(row) >= 6:
                    result.append({
                        'trade_date': row[0],
                        'open': float(row[1]),
                        'close': float(row[2]),
                        'high': float(row[3]),
                        'low': float(row[4]),
                        'volume': float(row[5]),
                        'amount': float(row[6]) if len(row) > 6 else 0,
                        'chg': float(row[7]) if len(row) > 7 else 0,
                        'chg_pct': float(row[8]) if len(row) > 8 else 0
                    })
            if result:
                _bump_fetch_stat('kline', 'success')
                return result
            last_error_kind = 'parse_error'
        except requests.RequestException:
            last_error_kind = 'network_error'
        except Exception:
            last_error_kind = 'parse_error'
        time.sleep(0.2)

    _bump_fetch_stat('kline', last_error_kind)
    return []

def fetch_tencent_quote(symbol):
    """腾讯实时行情（含PE/PB）"""
    if symbol.startswith('sz'):
        tsym = f'sz{symbol[2:]}'
    elif symbol.startswith('sh'):
        tsym = f'sh{symbol[2:]}'
    else:
        tsym = symbol

    session = _get_session()
    last_error_kind = 'network_error'
    for _ in range(2):
        try:
            r = session.get(f'https://203.205.235.28/q={tsym}', headers={'Host': 'qt.gtimg.cn'}, verify=False, timeout=15)
            text = r.text.strip()
            eq_pos = text.index('=')
            fields = text[eq_pos+2:-1].split('~')
            if len(fields) >= 47:
                _bump_fetch_stat('quote', 'success')
                return {
                    'close': float(fields[3]) if fields[3] else None,
                    'pe': float(fields[39]) if fields[39] else None,
                    'pb': float(fields[46]) if fields[46] else None,
                    'volume': float(fields[6]) if fields[6] else 0,
                    'amount': float(fields[37]) if fields[37] else 0,
                }
            last_error_kind = 'empty_payload'
        except requests.RequestException:
            last_error_kind = 'network_error'
        except Exception:
            last_error_kind = 'parse_error'
        time.sleep(0.2)
    _bump_fetch_stat('quote', last_error_kind)
    return None


def _get_akshare_fetcher():
    global _AKSHARE_FETCHER
    if _AKSHARE_FETCHER is None:
        with _AKSHARE_LOCK:
            if _AKSHARE_FETCHER is None:
                fetcher = AkshareFetcher(priority=1)
                _AKSHARE_FETCHER = fetcher if fetcher.is_available() else False
    return _AKSHARE_FETCHER if _AKSHARE_FETCHER is not False else None


def _normalize_fallback_df(df):
    if df is None or (hasattr(df, 'empty') and df.empty):
        return []
    result = []
    for _, row in df.iterrows():
        trade_date = str(row.get('date') or row.get('trade_date') or '')[:10]
        if not trade_date:
            continue
        try:
            result.append({
                'trade_date': trade_date,
                'open': float(row['open']),
                'close': float(row['close']),
                'high': float(row['high']),
                'low': float(row['low']),
                'volume': float(row.get('volume', 0) or 0),
                'amount': float(row.get('amount', 0) or 0),
                'chg': float(row.get('chg', 0) or 0),
                'chg_pct': float(row.get('chg_pct', 0) or 0),
            })
        except Exception:
            continue
    return result


def fetch_fallback_today_kline(symbol):
    _bump_fetch_stat('fallback', 'attempt')
    fetcher = _get_akshare_fetcher()
    if not fetcher:
        _bump_fetch_stat('fallback', 'error')
        return []
    try:
        df = fetcher.get_daily_data(symbol, beg_date.replace('-', ''), end_date.replace('-', ''))
        rows = _normalize_fallback_df(df)
        rows = [r for r in rows if str(r.get('trade_date')) == TODAY]
        if rows:
            _bump_fetch_stat('fallback', 'success')
            return rows
        _bump_fetch_stat('fallback', 'no_today')
        return []
    except Exception as e:
        print(f"[fallback] {symbol} error: {e}", flush=True)
        _bump_fetch_stat('fallback', 'error')
        return []


# ============================================================
# 数据库操作
# ============================================================

db_lock = threading.Lock()

def save_kline(symbol, klines, table='kline_daily'):
    if not klines:
        return 0
    with db_lock:
        conn = get_conn()
        count = 0
        for k in klines:
            try:
                _exec(conn, _upsert_kline_sql(table),
                    (symbol, k['trade_date'], k['open'], k['close'], k['high'], k['low'],
                     k['volume'], k['amount'], k['chg'], k['chg_pct']))
                count += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
    return count


def save_valuation(symbol, quote):
    """保存估值数据（当日）"""
    if not quote or not quote.get('pe'):
        return 0
    with db_lock:
        conn = get_conn()
        try:
            _exec(conn, '''INSERT INTO daily_valuation
                (symbol, trade_date, pe_ttm, pb, ps_ttm)
                VALUES (?,?,?,?,?)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                pe_ttm=excluded.pe_ttm, pb=excluded.pb, ps_ttm=excluded.ps_ttm''',
                (symbol, TODAY, quote['pe'], quote['pb'], None))
            conn.commit()
            conn.close()
            return 1
        except Exception as e:
            log(f"  valuation写入错误 {symbol}: {e}")
            conn.close()
            return 0


# ============================================================
# 1. 日K线更新（腾讯）
# ============================================================

def sync_daily_kline():
    log("=== [腾讯] 同步日K线 ===")
    completed, failed = 0, 0
    stale = 0
    wrote_today = 0
    fallback_used = 0

    def process(sym):
        nonlocal completed, failed, stale, wrote_today, fallback_used
        if not is_valid_symbol(sym):
            stale += 1
            return
        time.sleep(random.uniform(0.05, 0.15))
        klines = fetch_tencent_kline(sym, 'day')
        has_today = any(str(k.get('trade_date')) == TODAY for k in klines) if klines else False

        if klines:
            inserted = save_kline(sym, klines, 'kline_daily')
            if has_today and inserted > 0:
                completed += 1
                wrote_today += 1
                if (completed + failed + stale) % 1000 == 0:
                    log(f'  日K线进度: {completed + failed + stale}/{len(stock_list)}')
                return

        fallback_rows = fetch_fallback_today_kline(sym)
        if fallback_rows:
            inserted_fb = save_kline(sym, fallback_rows, 'kline_daily')
            if inserted_fb > 0:
                completed += 1
                wrote_today += 1
                fallback_used += 1
            else:
                stale += 1 if klines else failed + 0
        else:
            if klines:
                stale += 1
            else:
                failed += 1

        if (completed + failed + stale) % 1000 == 0:
            log(f'  日K线进度: {completed + failed + stale}/{len(stock_list)}')

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(process, stock_list))

    log(f'  日K线完成: 今日成功 {completed}, 历史返回/未含今日 {stale}, 失败 {failed}, fallback补齐 {fallback_used}')
    return completed, failed, stale


# ============================================================
# 2. 指数日K线更新（腾讯）
# ============================================================

def sync_index_daily_kline():
    log("=== [腾讯] 同步指数日K线 ===")
    completed, failed = 0, 0
    for sym in INDEX_SYMBOLS:
        klines = fetch_tencent_kline(sym, 'day')
        if not klines:
            failed += 1
            continue
        with db_lock:
            conn = get_conn()
            for k in klines:
                try:
                    _exec(conn, '''INSERT INTO kline_daily_index
                        (symbol, trade_date, open, high, low, close, volume, amount, pct_change)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(symbol, trade_date) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low,
                        close=excluded.close, volume=excluded.volume, amount=excluded.amount,
                        pct_change=excluded.pct_change''',
                        (sym, k['trade_date'], k['open'], k['high'], k['low'], k['close'],
                         k['volume'], k['amount'], k['chg_pct']))
                except Exception:
                    pass
            conn.commit()
            conn.close()
        completed += 1

    log(f'  指数日K线完成: 成功 {completed}, 失败 {failed}')
    recalc_index_technical_indicators()
    return completed, failed


def recalc_index_technical_indicators():
    log("=== 重算指数技术指标 (MA/RSI) ===")
    conn = get_conn()
    symbols = [r[0] for r in _fetchall(_exec(conn, 'SELECT DISTINCT symbol FROM kline_daily_index'))]

    for symbol in symbols:
        rows = _fetchall(_exec(conn,
            'SELECT trade_date, close FROM kline_daily_index WHERE symbol=? ORDER BY trade_date',
            (symbol,)
        ))
        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]
        updates = []
        for j, (trade_date, close) in enumerate(rows):
            ma5 = round(sum(closes[max(0, j-4):j+1]) / min(5, j+1), 2)
            ma10 = round(sum(closes[max(0, j-9):j+1]) / min(10, j+1), 2)
            ma20 = round(sum(closes[max(0, j-19):j+1]) / min(20, j+1), 2)

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
            updates.append((ma5, ma10, ma20, rsi14, symbol, trade_date))

        _execmany(conn,
            'UPDATE kline_daily_index SET ma5=?, ma10=?, ma20=?, rsi14=? WHERE symbol=? AND trade_date=?',
            updates
        )

    conn.commit()
    conn.close()
    log(f"  指数技术指标完成: {len(symbols)} 个指数")


# ============================================================
# 3. 周K线更新（腾讯）
# ============================================================

def sync_weekly_kline():
    log("=== [计算] 从日K聚合生成周K线 ===")
    weeks = 52 if args.full else 8
    result = os.system(
        f'python3 {os.path.dirname(os.path.abspath(__file__))}/calc_weekly_monthly.py --weekly-only --weeks {weeks}'
    )
    log(f"  周K线{'成功' if result == 0 else '失败'}")
    return (0, 0) if result != 0 else (1, 0)


# ============================================================
# 3. 月K线更新（从日K聚合）
# ============================================================

def sync_monthly_kline():
    log("=== [计算] 从日K聚合生成月K线 ===")
    months = 24 if args.full else 12
    result = os.system(
        f'python3 {os.path.dirname(os.path.abspath(__file__))}/calc_weekly_monthly.py --monthly-only --months {months}'
    )
    log(f"  月K线{'成功' if result == 0 else '失败'}")
    return (0, 0) if result != 0 else (1, 0)


# ============================================================
# 4. 技术指标重算（本地计算，不依赖外部API）
# ============================================================

def recalc_technical_indicators(target_date=None):
    log("=== 重算技术指标 (MA/RSI) ===")
    conn = get_conn()

    # 增量模式：只处理目标日有K线的股票，并且只更新目标日这一行
    if target_date:
        symbols = [r[0] for r in _fetchall(_exec(conn,
            'SELECT DISTINCT symbol FROM kline_daily WHERE trade_date=?',
            (target_date,)
        ))]
        updated_rows = 0

        for i, symbol in enumerate(symbols, 1):
            rows = _fetchall(_exec(conn,
                'SELECT trade_date, close FROM kline_daily WHERE symbol=? ORDER BY trade_date',
                (symbol,)
            ))
            if len(rows) < 20:
                continue

            closes = [r[1] for r in rows]
            updates = []
            for j, (trade_date, close) in enumerate(rows):
                if str(trade_date) != str(target_date):
                    continue

                ma5 = round(sum(closes[max(0, j-4):j+1]) / min(5, j+1), 2)
                ma10 = round(sum(closes[max(0, j-9):j+1]) / min(10, j+1), 2)
                ma20 = round(sum(closes[max(0, j-19):j+1]) / min(20, j+1), 2)
                ma60 = round(sum(closes[max(0, j-59):j+1]) / min(60, j+1), 2)

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

                updates.append((ma5, ma10, ma20, ma60, rsi14, ma20, symbol, trade_date))

            if updates:
                _execmany(conn,
                    'UPDATE kline_daily SET ma5=?, ma10=?, ma20=?, ma60=?, rsi14=?, boll_mid=? WHERE symbol=? AND trade_date=?',
                    updates
                )
                updated_rows += len(updates)

            if i % 500 == 0:
                conn.commit()
                log(f"  技术指标进度: {i}/{len(symbols)}")

        conn.commit()
        conn.close()
        log(f"  技术指标完成: 目标日 {target_date} 更新 {updated_rows} 行")
        return

    symbols = [r[0] for r in _fetchall(_exec(conn,
        'SELECT DISTINCT symbol FROM kline_daily'
    ))]
    updated = 0

    for i, symbol in enumerate(symbols):
        rows = _fetchall(_exec(conn,
            'SELECT trade_date, close, high, low FROM kline_daily WHERE symbol=? ORDER BY trade_date',
            (symbol,)
        ))

        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]
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

            updates.append((ma5, ma10, ma20, ma60, rsi14, ma20, symbol, trade_date))

        if updates:
            _execmany(conn,
                'UPDATE kline_daily SET ma5=?, ma10=?, ma20=?, ma60=?, rsi14=?, boll_mid=? WHERE symbol=? AND trade_date=?',
                updates
            )

        updated += 1
        if updated % 1000 == 0:
            log(f"  技术指标进度: {updated}/{len(symbols)}")

    conn.commit()
    conn.close()
    log(f"  技术指标完成: 更新 {updated} 只股票")


# ============================================================
# 5. 估值数据 PE/PB（腾讯实时行情）
# ============================================================

def sync_valuation():
    log("=== [腾讯] 同步估值数据 PE/PB ===")
    conn = get_conn()
    tables = _table_exists(conn, 'daily_valuation')
    conn.close()
    if not tables:
        log("  daily_valuation 表不存在，跳过")
        return 0

    completed = 0
    batch_size = 50  # 腾讯支持批量查询

    for i in range(0, len(stock_list), batch_size):
        batch = [sym for sym in stock_list[i:i+batch_size] if is_valid_symbol(sym)]
        if not batch:
            continue
        query_str = ','.join(batch)
        session = _get_session()
        try:
            r = session.get(f'https://203.205.235.28/q={query_str}', headers={'Host': 'qt.gtimg.cn'}, verify=False, timeout=15)
            lines = r.text.strip().split('\n')
            for line in lines:
                if '=' not in line:
                    continue
                try:
                    eq_pos = line.index('=')
                    fields = line[eq_pos+2:-1].split('~')
                    if len(fields) >= 47 and fields[2]:
                        symbol = fields[2]
                        prefix = 'sh' if line.startswith('v_sh') else 'sz'
                        sym = f'{prefix}{symbol}'
                        pe = float(fields[39]) if fields[39] else None
                        pb = float(fields[46]) if fields[46] else None
                        if pe and pb:
                            save_valuation(sym, {'pe': pe, 'pb': pb})
                            completed += 1
                except:
                    pass
        except:
            pass

        if (i + batch_size) % 1000 == 0:
            log(f"  估值进度: {min(i+batch_size, len(stock_list))}/{len(stock_list)}")
        time.sleep(0.1)

    log(f"  估值完成: {completed} 只股票")
    return completed


# ============================================================
# 6. 财务指标（akshare fallback）
# ============================================================

def sync_financial_indicators():
    log("=== [akshare] 同步财务指标 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过财务指标")
        return

    conn = get_conn()
    symbols = [r[0] for r in _fetchall(_exec(conn,
        'SELECT DISTINCT symbol FROM kline_daily ORDER BY symbol'
    ))]
    conn.close()

    log(f"  待检查: {len(symbols)} 只（逐只检查是否有新财报）")
    log("  财务指标同步暂需手动运行 daily_sync.py --fund")


# ============================================================
# 主流程
# ============================================================

def main():
    start_time = time.time()
    log(f"开始腾讯数据同步 — {TODAY}")

    # 清除旧的就绪信号，防止 daily_pick 误读
    try:
        os.remove(READY_FLAG)
    except FileNotFoundError:
        pass

    only_fund = args.fund

    if only_fund:
        sync_financial_indicators()
    else:
        # 1. 日K线
        sync_daily_kline()

        # 2. 指数日K线 + 指标
        sync_index_daily_kline()

        # 3. 技术指标重算
        if args.full:
            recalc_technical_indicators(None)
        elif LIGHT_TARGET_DATE_MODE:
            recalc_technical_indicators(TODAY)
        else:
            # 增量模式：至少重算今天；若今天数据不足，再补算最近有效交易日
            recalc_targets = []
            conn = get_conn()
            try:
                today_total = _fetchone(_exec(conn,
                    'SELECT COUNT(*) FROM kline_daily WHERE trade_date=?',
                    (TODAY,)
                ))[0]
                if today_total > 0:
                    recalc_targets.append(TODAY)

                fallback_date = get_latest_valid_trade_date(conn)
                if fallback_date and fallback_date not in recalc_targets:
                    # 当今天数据不足或不存在时，补算最近有效交易日，避免 daily_pick 回退后 RSI/MA 为空
                    if today_total < MIN_STOCKS or fallback_date != TODAY:
                        recalc_targets.append(fallback_date)
            finally:
                conn.close()

            if not recalc_targets:
                recalc_targets = [TODAY]

            for target in recalc_targets:
                recalc_technical_indicators(target)

        # 4. 周K线（--no-weekly 时跳过，仅周日全量跑）
        if not args.no_weekly and not LIGHT_TARGET_DATE_MODE:
            sync_weekly_kline()

        # 5. 月K线（--no-monthly 时跳过，仅周日全量跑）
        if not args.no_monthly and not LIGHT_TARGET_DATE_MODE:
            sync_monthly_kline()

        # 6. 估值数据
        if not LIGHT_TARGET_DATE_MODE:
            sync_valuation()

        # 7. 财务指标（仅全量或周末）
        if args.full:
            sync_financial_indicators()

        # 8. 增量算目标日布林带（必须在 READY_FLAG 之前完成）
        _calc_today_bollinger(TODAY)

        # 最终校验（布林带算完后再决定是否发就绪信号）
        ok, valid_date = post_sync_validate()
        if ok:
            try:
                with open(READY_FLAG, 'w') as f:
                    # 写“最近有效交易日”，而不是强制TODAY
                    f.write(valid_date)
                log(f"  🏁 就绪信号已写入: {READY_FLAG} ({valid_date})")
            except Exception as e:
                log(f"  ⚠️ 写入就绪信号失败: {e}")
        else:
            log("  ⏸️ 本次同步未通过校验，不写就绪信号")

    elapsed = time.time() - start_time
    log(f"同步完成! 耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")




# ============================================================
# 今日布林带增量计算
# ============================================================
def _calc_today_bollinger(target_date=None):
    """只计算目标日有数据的股票的布林带（增量，速度快）"""
    import numpy as np
    target_date = target_date or TODAY
    log(f"=== [腾讯] 增量计算目标日布林带: {target_date} ===")
    conn = get_conn()

    symbols = [r[0] for r in _fetchall(_exec(conn,
        "SELECT DISTINCT symbol FROM kline_daily WHERE trade_date=?",
        (target_date,)
    ))]

    if not symbols:
        conn.close()
        log("  目标日无新数据，跳过")
        return

    updated = 0
    updated_rows = 0
    for sym in symbols:
        rows = _fetchall(_exec(conn,
            'SELECT trade_date, close FROM kline_daily WHERE symbol=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 25',
            (sym, target_date)
        ))
        rows.reverse()
        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]
        dates = [r[0] for r in rows]
        if str(dates[-1]) != str(target_date):
            continue

        window = closes[-20:]
        ma20 = float(np.mean(window))
        std20 = float(np.std(window, ddof=1))
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        _execmany(conn,
            'UPDATE kline_daily SET boll_upper=?, boll_lower=? WHERE symbol=? AND trade_date=?',
            [(float(round(upper, 4)), float(round(lower, 4)), sym, target_date)]
        )
        updated += 1
        updated_rows += 1

    conn.commit()
    conn.close()
    log(f"  目标日布林带完成: 股票 {updated} 只, 行 {updated_rows}")


# ============================================================
# 同步后数据校验
# ============================================================
def _health_exec_factory(conn):
    return lambda sql, params=None: conn.cursor().execute(sql, params) if False else _exec(conn, sql, params)


def get_latest_valid_trade_date(conn, min_stocks=MIN_STOCKS, lookback_days=VALID_LOOKBACK_DAYS):
    """返回最近一个“有效交易日”（共享逻辑）"""
    if DB_IS_POSTGRES:
        row = _fetchone(_exec(conn, '''
            SELECT trade_date, COUNT(*) AS cnt
            FROM kline_daily
            WHERE trade_date >= (%s::date - (%s * INTERVAL '1 day'))
            GROUP BY trade_date
            HAVING COUNT(*) >= %s
            ORDER BY trade_date DESC
            LIMIT 1
        ''', (TODAY, lookback_days, min_stocks)))
        return row[0] if row else None
    return find_best_trade_date(
        _health_exec_factory(conn),
        _fetchone,
        TODAY,
        DB_TARGET,
        min_stocks=min_stocks,
        lookback_days=lookback_days,
    )


def post_sync_validate():
    """同步完成后校验数据完整性，优先校验今天；发现异常立即告警。返回(True/False, valid_date)"""
    log("=== 同步后数据校验 ===")
    conn = get_conn()

    today_total = _fetchone(_exec(conn,
        "SELECT COUNT(*) FROM kline_daily WHERE trade_date=?",
        (TODAY,)
    ))[0]
    fallback_used = False
    if today_total >= MIN_STOCKS:
        target_date = TODAY
    else:
        target_date = get_latest_valid_trade_date(conn)
        fallback_used = bool(target_date and target_date != TODAY)
        log(f"  ⚠️ 今日 {TODAY} 仅 {today_total} 只，回退到最近有效交易日 {target_date} 做参考校验")

    if not target_date:
        conn.close()
        msg = f"最近{VALID_LOOKBACK_DAYS}天无有效交易日（K线<={MIN_STOCKS}）"
        log(f"  ❌ 校验失败: {msg}")
        write_sync_status({
            'pipeline_stage': 'base',
            'ready': False,
            'today': TODAY,
            'target_date': None,
            'today_kline_count': today_total,
            'fallback_used': False,
            'validation_errors': [msg],
            'validation_warnings': [],
        })
        with open('/tmp/stock_sync_alert.txt', 'w') as f:
            f.write(f"{TODAY} sync failed:\n{msg}\n")
        return False, None

    health = assess_trade_date_health(
        _health_exec_factory(conn),
        _fetchone,
        TODAY,
        target_date,
        min_stocks=MIN_STOCKS,
        db_target=DB_TARGET,
    )
    conn.close()

    summary = f"目标日{target_date}: K线{health['total']}只, RSI{health['rsi']}只, MA20{health['ma20']}只"
    log(f"  FetchStats kline={FETCH_STATS.get('kline')} quote={FETCH_STATS.get('quote')}")
    write_sync_status({
        'pipeline_stage': 'base',
        'ready': health['ok'],
        'today': TODAY,
        'target_date': target_date,
        'today_kline_count': today_total,
        'fallback_used': fallback_used,
        'validation_errors': health['errors'],
        'validation_warnings': health['warnings'],
        'health': {
            'total': health['total'],
            'rsi': health['rsi'],
            'ma20': health['ma20'],
            'bb': health['bb'],
            'valuation': health['valuation'],
            'sh_count': health['sh_count'],
            'sz_count': health['sz_count'],
        },
        'fetch_stats': FETCH_STATS,
    })
    if health['errors']:
        log(f"  ❌ 校验失败: {summary}")
        for e in health['errors']:
            log(f"    • {e}")
        for w in health['warnings']:
            log(f"    ⚠️ {w}")
        with open('/tmp/stock_sync_alert.txt', 'w') as f:
            f.write(f"{TODAY} sync failed:\n" + '\n'.join(health['errors']))
        return False, target_date
    else:
        log(f"  ✅ 校验通过: {summary}")
        for w in health['warnings']:
            log(f"    ⚠️ {w}")
        try:
            os.remove('/tmp/stock_sync_alert.txt')
        except:
            pass
        return True, target_date


if __name__ == '__main__':
    main()
