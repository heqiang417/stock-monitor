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

import os, sys, json, sqlite3, time, random, argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import warnings
warnings.filterwarnings("ignore")
import numpy as np

# === 配置 ===
DB_PATH = os.environ.get('STOCK_DB',
    '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db')
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
args = parser.parse_args()

INCR_DAYS = 60 if args.full else args.days
TODAY = datetime.now().strftime('%Y-%m-%d')
MIN_STOCKS = 4000
VALID_LOOKBACK_DAYS = 10
beg_date = (datetime.now() - timedelta(days=INCR_DAYS + 10)).strftime('%Y-%m-%d')
end_date = TODAY

# === 日志 ===
LOG_DIR = os.path.join(os.path.dirname(DB_PATH), '..', 'logs')
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
    try:
        r = session.get(
            'https://43.154.254.185/appstock/app/fqkline/get',
            verify=False,
            headers={'Host': 'web.ifzq.gtimg.cn'}, params={'param': f'{tsym},{period},{beg_date},{end_date},{INCR_DAYS+10},qfq'},
            timeout=15
        )
        d = r.json()
        data = d.get('data', {}).get(tsym, {})

        # 尝试多个可能的key
        days = data.get(period, []) or data.get(f'qfq{period}', [])

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
        return result
    except Exception as e:
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
    try:
        r = session.get(f'https://203.205.235.28/q={tsym}', headers={'Host': 'qt.gtimg.cn'}, verify=False, timeout=15)
        text = r.text.strip()
        # 解析: v_sz002149="51~名称~代码~现价~昨收~开盘~..."
        eq_pos = text.index('=')
        fields = text[eq_pos+2:-1].split('~')  # 去掉开头引号和结尾引号
        if len(fields) >= 47:
            return {
                'close': float(fields[3]) if fields[3] else None,
                'pe': float(fields[39]) if fields[39] else None,     # 动态市盈率
                'pb': float(fields[46]) if fields[46] else None,     # 市净率
                'volume': float(fields[6]) if fields[6] else 0,
                'amount': float(fields[37]) if fields[37] else 0,    # 成交额(万)
            }
    except Exception as e:
        pass
    return None


# ============================================================
# 数据库操作
# ============================================================

db_lock = threading.Lock()

def save_kline(symbol, klines, table='kline_daily'):
    if not klines:
        return 0
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('PRAGMA journal_mode=WAL')
        c = conn.cursor()
        count = 0
        for k in klines:
            try:
                c.execute(f'''INSERT INTO {table}
                    (symbol, trade_date, open, close, high, low, volume, amount, chg, chg_pct)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol, trade_date) DO UPDATE SET
                    open=excluded.open, close=excluded.close, high=excluded.high, low=excluded.low,
                    volume=excluded.volume, amount=excluded.amount, chg=excluded.chg, chg_pct=excluded.chg_pct''',
                    (symbol, k['trade_date'], k['open'], k['close'], k['high'], k['low'],
                     k['volume'], k['amount'], k['chg'], k['chg_pct']))
                count += 1
            except Exception as e:
                pass
        conn.commit()
        conn.close()
    return count

def save_valuation(symbol, quote):
    """保存估值数据（当日）"""
    if not quote or not quote.get('pe'):
        return 0
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute('''INSERT OR REPLACE INTO daily_valuation
                (symbol, trade_date, pe_ttm, pb, ps_ttm)
                VALUES (?,?,?,?,?)''',
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

    def process(sym):
        nonlocal completed, failed
        time.sleep(random.uniform(0.05, 0.15))
        klines = fetch_tencent_kline(sym, 'day')
        if klines:
            save_kline(sym, klines, 'kline_daily')
            completed += 1
        else:
            failed += 1
        if (completed + failed) % 1000 == 0:
            log(f'  日K线进度: {completed + failed}/{len(stock_list)}')

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(process, stock_list))

    log(f'  日K线完成: 成功 {completed}, 失败 {failed}')
    return completed, failed


# ============================================================
# 2. 指数日K线更新（腾讯）
# ============================================================

def sync_index_daily_kline():
    log("=== [腾讯] 同步指数日K线 ===")
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('''CREATE TABLE IF NOT EXISTS kline_daily_index (
            symbol TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            pct_change REAL,
            ma5 REAL,
            ma10 REAL,
            ma20 REAL,
            rsi14 REAL,
            PRIMARY KEY (symbol, trade_date)
        )''')
        conn.commit()
        conn.close()

    completed, failed = 0, 0
    for sym in INDEX_SYMBOLS:
        klines = fetch_tencent_kline(sym, 'day')
        if not klines:
            failed += 1
            continue
        with db_lock:
            conn = sqlite3.connect(DB_PATH)
            conn.execute('PRAGMA journal_mode=WAL')
            c = conn.cursor()
            for k in klines:
                try:
                    c.execute('''INSERT INTO kline_daily_index
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
    conn = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily_index').fetchall()]

    for symbol in symbols:
        rows = conn.execute(
            'SELECT rowid, close FROM kline_daily_index WHERE symbol=? ORDER BY trade_date',
            (symbol,)
        ).fetchall()
        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]
        updates = []
        for j, (rowid, close) in enumerate(rows):
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
            updates.append((ma5, ma10, ma20, rsi14, rowid))

        conn.executemany(
            'UPDATE kline_daily_index SET ma5=?, ma10=?, ma20=?, rsi14=? WHERE rowid=?',
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
    conn = sqlite3.connect(DB_PATH)

    # 增量模式：只处理目标日有K线的股票，并且只更新目标日这一行
    if target_date:
        symbols = [r[0] for r in conn.execute(
            'SELECT DISTINCT symbol FROM kline_daily WHERE trade_date=?',
            (target_date,)
        ).fetchall()]
        updated_rows = 0

        for i, symbol in enumerate(symbols, 1):
            rows = conn.execute(
                'SELECT rowid, trade_date, close FROM kline_daily WHERE symbol=? ORDER BY trade_date',
                (symbol,)
            ).fetchall()
            if len(rows) < 20:
                continue

            closes = [r[2] for r in rows]
            updates = []
            for j, (rowid, trade_date, close) in enumerate(rows):
                if trade_date != target_date:
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

                    updates.append((ma5, ma10, ma20, ma60, rsi14, ma20, rowid))

            if updates:
                conn.executemany(
                    'UPDATE kline_daily SET ma5=?, ma10=?, ma20=?, ma60=?, rsi14=?, boll_mid=? WHERE rowid=?',
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

    # 兼容原有全量模式
    symbols = [r[0] for r in conn.execute(
        'SELECT DISTINCT symbol FROM kline_daily').fetchall()]
    updated = 0

    for i, symbol in enumerate(symbols):
        rows = conn.execute(
            'SELECT rowid, close, high, low FROM kline_daily WHERE symbol=? ORDER BY trade_date',
            (symbol,)
        ).fetchall()

        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]

        for j, row in enumerate(rows):
            rowid = row[0]
            ma5 = round(sum(closes[max(0, j-4):j+1]) / min(5, j+1), 2) if j >= 0 else None
            ma10 = round(sum(closes[max(0, j-9):j+1]) / min(10, j+1), 2) if j >= 1 else None
            ma20 = round(sum(closes[max(0, j-19):j+1]) / min(20, j+1), 2) if j >= 1 else None
            ma60 = round(sum(closes[max(0, j-59):j+1]) / min(60, j+1), 2) if j >= 1 else None

            # RSI14
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

            conn.execute(
                'UPDATE kline_daily SET ma5=?, ma10=?, ma20=?, ma60=?, rsi14=?, boll_mid=? WHERE rowid=?',
                (ma5, ma10, ma20, ma60, rsi14, ma20, rowid)
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
    conn = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_valuation'"
    ).fetchall()]
    conn.close()
    if not tables:
        log("  daily_valuation 表不存在，跳过")
        return 0

    completed = 0
    batch_size = 50  # 腾讯支持批量查询

    for i in range(0, len(stock_list), batch_size):
        batch = stock_list[i:i+batch_size]
        # 构建批量查询
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
                            with db_lock:
                                _conn = sqlite3.connect(DB_PATH)
                                _conn.execute('''INSERT OR REPLACE INTO daily_valuation
                                    (symbol, trade_date, pe_ttm, pb, ps_ttm)
                                    VALUES (?,?,?,?,?)''',
                                    (sym, TODAY, pe, pb, None))
                                _conn.commit()
                                _conn.close()
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

    conn = sqlite3.connect(DB_PATH)
    # 检查是否有新的财报数据需要更新
    # 简化版：只更新最近有财报发布的股票
    symbols = [r[0] for r in conn.execute(
        'SELECT DISTINCT symbol FROM kline_daily ORDER BY symbol'
    ).fetchall()]
    conn.close()

    log(f"  待检查: {len(symbols)} 只（逐只检查是否有新财报）")
    # 这部分逻辑比较复杂，保留原有 daily_sync.py 的实现
    # 暂时标记为需要手动触发
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

        # 3. 技术指标重算（增量模式：只补今天；全量模式：全量重算）
        recalc_technical_indicators(TODAY if not args.full else None)

        # 4. 周K线（--no-weekly 时跳过，仅周日全量跑）
        if not args.no_weekly:
            sync_weekly_kline()

        # 5. 月K线（--no-monthly 时跳过，仅周日全量跑）
        if not args.no_monthly:
            sync_monthly_kline()

        # 6. 估值数据
        sync_valuation()

        # 7. 财务指标（仅全量或周末）
        if args.full:
            sync_financial_indicators()

        # 8. 增量算今天布林带（必须在 READY_FLAG 之前完成）
        _calc_today_bollinger()

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
def _calc_today_bollinger():
    """只计算今天有数据的股票的布林带（增量，速度快）"""
    import numpy as np
    log("=== [腾讯] 增量计算今日布林带 ===")
    conn = sqlite3.connect(DB_PATH)
    today = TODAY

    # 找出今天有数据的股票
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM kline_daily WHERE trade_date=?",
        (today,)
    ).fetchall()]

    if not symbols:
        conn.close()
        log("  今日无新数据，跳过")
        return

    # 确保列存在
    cols = [c[1] for c in conn.execute('PRAGMA table_info(kline_daily)').fetchall()]
    for col in ['boll_lower', 'boll_upper']:
        if col not in cols:
            conn.execute(f'ALTER TABLE kline_daily ADD COLUMN {col} REAL')

    updated = 0
    for sym in symbols:
        rows = conn.execute(
            'SELECT trade_date, close FROM kline_daily WHERE symbol=? ORDER BY trade_date DESC LIMIT 25',
            (sym,)
        ).fetchall()
        rows.reverse()
        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]
        dates = [r[0] for r in rows]

        updates = []
        for i in range(19, len(closes)):
            window = closes[i-19:i+1]
            ma20 = np.mean(window)
            std20 = np.std(window, ddof=1)
            upper = ma20 + 2 * std20
            lower = ma20 - 2 * std20
            updates.append((round(upper, 4), round(lower, 4), sym, dates[i]))

        if updates:
            conn.executemany(
                'UPDATE kline_daily SET boll_upper=?, boll_lower=? WHERE symbol=? AND trade_date=?',
                updates
            )
            updated += 1

    conn.commit()
    conn.close()
    log(f"  今日布林带完成: {updated} 只股票")


# ============================================================
# 同步后数据校验
# ============================================================
def get_latest_valid_trade_date(conn, min_stocks=MIN_STOCKS, lookback_days=VALID_LOOKBACK_DAYS):
    """返回最近一个“有效交易日”（K线>=min_stocks），找不到返回None"""
    row = conn.execute(
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


def post_sync_validate():
    """同步完成后校验数据完整性，发现异常立即告警。返回(True/False, valid_date)"""
    log("=== 同步后数据校验 ===")
    conn = sqlite3.connect(DB_PATH)
    target_date = get_latest_valid_trade_date(conn)

    if not target_date:
        conn.close()
        msg = f"最近{VALID_LOOKBACK_DAYS}天无有效交易日（K线<={MIN_STOCKS}）"
        log(f"  ❌ 校验失败: {msg}")
        with open('/tmp/stock_sync_alert.txt', 'w') as f:
            f.write(f"{TODAY} sync failed:\n{msg}\n")
        return False, None

    errors = []

    # 1. 目标日K线数量
    total = conn.execute(
        "SELECT COUNT(*) FROM kline_daily WHERE trade_date=?",
        (target_date,)
    ).fetchone()[0]
    if total < MIN_STOCKS:
        errors.append(f"K线数据不足: {target_date} {total}只（需≥{MIN_STOCKS}）")

    # 2. 技术指标覆盖率
    has_rsi = conn.execute(
        "SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND rsi14 IS NOT NULL",
        (target_date,)
    ).fetchone()[0]
    has_ma = conn.execute(
        "SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND ma20 IS NOT NULL",
        (target_date,)
    ).fetchone()[0]
    if total > 0 and has_rsi < total * 0.8:
        errors.append(f"RSI未覆盖: {target_date} {has_rsi}/{total}只")
    if total > 0 and has_ma < total * 0.8:
        errors.append(f"MA20未覆盖: {target_date} {has_ma}/{total}只")

    # 3. 上一有效交易日对比（检测数据量骤降）
    prev = conn.execute(
        """
        SELECT trade_date, COUNT(*) AS cnt
        FROM kline_daily
        WHERE trade_date < ?
        GROUP BY trade_date
        HAVING cnt >= ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (target_date, MIN_STOCKS)
    ).fetchone()
    if prev and total < prev[1] * 0.9:
        errors.append(f"数据量骤降: {target_date} {total}只 vs 上日{prev[0]} {prev[1]}只")

    conn.close()

    summary = f"目标日{target_date}: K线{total}只, RSI{has_rsi}只, MA20{has_ma}只"
    if errors:
        log(f"  ❌ 校验失败: {summary}")
        for e in errors:
            log(f"    • {e}")
        with open('/tmp/stock_sync_alert.txt', 'w') as f:
            f.write(f"{TODAY} sync failed:\n" + '\n'.join(errors))
        return False, target_date
    else:
        log(f"  ✅ 校验通过: {summary}")
        try:
            os.remove('/tmp/stock_sync_alert.txt')
        except:
            pass
        return True, target_date


if __name__ == '__main__':
    main()
