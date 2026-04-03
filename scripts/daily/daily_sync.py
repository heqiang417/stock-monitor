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
import sqlite3
import time
import random
import argparse
import threading
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_provider import DataFetcherManager
from data_provider.tencent_fetcher import TencentFetcher
from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.tushare_fetcher import TushareFetcher
from data_provider.baostock_fetcher import BaostockFetcher

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

DB_PATH = '/mnt/data/workspace/stock-monitor-app-py/data/stock_data.db'
LOG_DIR = '/mnt/data/workspace/stock-monitor-app-py/logs'
INCR_DAYS = 15  # 增量更新天数

os.makedirs(LOG_DIR, exist_ok=True)

today = datetime.now().strftime('%Y-%m-%d')
log_file = os.path.join(LOG_DIR, f'sync_{today}.log')

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(log_file, 'a') as f:
        f.write(line + '\n')

# 记录已注册的数据源
log(f"已注册数据源: {[f.name for f in _manager.fetchers]}")

# ============================================================
# 1. 日K线增量更新（多数据源自动切换）
# ============================================================
def sync_daily_kline():
    log("=== 开始同步日K线（多数据源）===")
    conn = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]
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

            conn2 = sqlite3.connect(DB_PATH)
            count = 0
            for _, row in df.iterrows():
                try:
                    conn2.execute('''INSERT OR REPLACE INTO kline_daily
                        (symbol, trade_date, open, close, high, low, volume, amount, chg, chg_pct)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
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
    conn = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]
    updated = 0

    for i, symbol in enumerate(symbols):
        rows = conn.execute(
            'SELECT rowid, close, high, low FROM kline_daily WHERE symbol=? ORDER BY trade_date',
            (symbol,)
        ).fetchall()

        if len(rows) < 20:
            continue

        closes = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]

        # 计算 MA
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
                'UPDATE kline_daily SET ma5=?, ma10=?, ma20=?, ma60=?, rsi14=? WHERE rowid=?',
                (ma5, ma10, ma20, ma60, rsi14, rowid)
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

    conn = sqlite3.connect(DB_PATH)
    all_symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]

    # 找出最久没更新的500只
    stale = conn.execute('''
        SELECT k.symbol FROM kline_daily k
        LEFT JOIN (
            SELECT symbol, MAX(report_date) as latest FROM financial_indicators GROUP BY symbol
        ) f ON k.symbol = f.symbol
        GROUP BY k.symbol
        ORDER BY COALESCE(f.latest, '2000-01-01') ASC
        LIMIT 500
    ''').fetchall()
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
            conn2 = sqlite3.connect(DB_PATH)
            conn2.execute('''INSERT OR REPLACE INTO financial_indicators
                (symbol, report_date, eps, roe, revenue_growth, profit_growth,
                 gross_margin, net_margin, debt_ratio, current_ratio, total_assets)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
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
    conn = sqlite3.connect(DB_PATH)

    # 建表
    conn.execute('''CREATE TABLE IF NOT EXISTS financial_daily (
        symbol TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        eps REAL, roe REAL, revenue_growth REAL, profit_growth REAL,
        gross_margin REAL, net_margin REAL, debt_ratio REAL,
        current_ratio REAL, total_assets REAL,
        PRIMARY KEY (symbol, trade_date)
    )''')

    # 删除今天的旧快照（允许重跑）
    conn.execute(f"DELETE FROM financial_daily WHERE trade_date='{today}'")

    # 每只股票取最新一条财务数据，写入今天的快照
    conn.execute(f'''
        INSERT OR IGNORE INTO financial_daily
            (symbol, trade_date, eps, roe, revenue_growth, profit_growth,
             gross_margin, net_margin, debt_ratio, current_ratio, total_assets)
        SELECT f.symbol, '{today}', f.eps, f.roe, f.revenue_growth, f.profit_growth,
               f.gross_margin, f.net_margin, f.debt_ratio, f.current_ratio, f.total_assets
        FROM financial_indicators f
        INNER JOIN (
            SELECT symbol, MAX(report_date) as max_date
            FROM financial_indicators GROUP BY symbol
        ) latest ON f.symbol = latest.symbol AND f.report_date = latest.max_date
    ''')

    count = conn.execute(f"SELECT COUNT(*) FROM financial_daily WHERE trade_date='{today}'").fetchone()[0]
    conn.commit()
    conn.close()
    log(f"  财务快照完成: {today} {count}只")

# ============================================================
# 4. 周K线增量更新
# ============================================================
def sync_weekly_kline():
    log("=== 同步周K线（多数据源自动切换）===")

    conn = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]

    start_date = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    success = 0

    for i, symbol in enumerate(symbols):
        try:
            df = _manager.get_period_data(symbol, start_date, end_date, period='weekly')
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    conn.execute('''INSERT OR IGNORE INTO kline_weekly
                        (symbol, trade_week, open, close, high, low, volume, amount, chg, chg_pct)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
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

    conn = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]

    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')
    success = 0

    for i, symbol in enumerate(symbols):
        try:
            df = _manager.get_period_data(symbol, start_date, end_date, period='monthly')
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    conn.execute('''INSERT OR IGNORE INTO kline_monthly
                        (symbol, trade_month, open, close, high, low, volume, amount, chg, chg_pct)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
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
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            count = 0
            for _, row in df.iterrows():
                code = str(row.get('代码', ''))
                if code.startswith('6'):
                    symbol = f'sh{code}'
                elif code.startswith(('0', '3')):
                    symbol = f'sz{code}'
                else:
                    continue

                pe = row.get('市盈率-动态')
                pb = row.get('市净率')
                ps = row.get('市销率')

                conn.execute('''INSERT OR REPLACE INTO daily_valuation
                    (symbol, trade_date, pe_ttm, pb, ps_ttm) VALUES (?,?,?,?,?)''',
                    (symbol, today, float(pe) if pe and pe != '-' else None,
                     float(pb) if pb and pb != '-' else None,
                     float(ps) if ps and ps != '-' else None))
                count += 1

            conn.commit()
            log(f"  估值数据完成: 更新{count}只")
    except Exception as e:
        log(f"  估值数据失败: {e}")
    finally:
        conn.close()

# ============================================================
# 7. 资金流向更新
# ============================================================
def sync_capital_flow():
    log("=== 同步资金流向 ===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]
    conn.close()

    today_str = datetime.now().strftime('%Y-%m-%d')
    success = 0
    db_lock = threading.Lock()

    def fetch_flow(symbol):
        code = symbol[2:]
        market = 'sh' if symbol.startswith('sh') else 'sz'
        try:
            df = ak.stock_individual_fund_flow(stock=code, market=market)
            if df is None or df.empty:
                return None
            latest = df.iloc[-1]
            return {
                'symbol': symbol,
                'trade_date': str(latest.get('日期', today_str)),
                # akshare 返回单位是元，转万元（与 download_capital_flow.py 保持一致）
                'main_net_inflow': float(latest.get('主力净流入-净额', 0) or 0) / 10000.0,
                'super_large_net_inflow': float(latest.get('超大单净流入-净额', 0) or 0) / 10000.0,
                'large_net_inflow': float(latest.get('大单净流入-净额', 0) or 0) / 10000.0,
                'medium_net_inflow': float(latest.get('中单净流入-净额', 0) or 0) / 10000.0,
                'small_net_inflow': float(latest.get('小单净流入-净额', 0) or 0) / 10000.0,
            }
        except:
            return None

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_flow, s): s for s in symbols}
        done = 0
        for f in as_completed(futures, timeout=600):
            try:
                data = f.result(timeout=10)
            except:
                data = None
            if data:
                with db_lock:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute('PRAGMA journal_mode=WAL')
                    conn.execute('''INSERT OR REPLACE INTO capital_flow
                        (symbol, trade_date, main_net_inflow, super_large_net_inflow,
                         large_net_inflow, medium_net_inflow, small_net_inflow)
                        VALUES (?,?,?,?,?,?,?)''',
                        (data['symbol'], data['trade_date'], data['main_net_inflow'],
                         data['super_large_net_inflow'], data['large_net_inflow'],
                         data['medium_net_inflow'], data['small_net_inflow']))
                    conn.commit()
                    conn.close()
                success += 1
            done += 1
            if done % 200 == 0:
                log(f"  资金流向进度: {done}/{len(symbols)}")

    log(f"  资金流向完成: 更新{success}只")

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

    conn = sqlite3.connect(DB_PATH)
    symbols = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]

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
                    conn.execute('''INSERT OR REPLACE INTO stock_industry
                        (symbol, industry, industry_code) VALUES (?,?,?)''',
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
                    conn.execute('''INSERT OR REPLACE INTO stock_industry
                        (symbol, industry) VALUES (?,?)''', (symbol, industry))
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

    conn = sqlite3.connect(DB_PATH)
    # 检查已有最新日期
    latest = conn.execute("SELECT MAX(date) FROM northbound_flow").fetchone()[0]
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
            conn2 = sqlite3.connect(DB_PATH)
            for _, row in df.iterrows():
                d = str(row.get('date', ''))
                if latest and d <= latest:
                    continue
                conn2.execute('''INSERT OR IGNORE INTO northbound_flow
                    (date, type, direction, net_buy, net_flow, index_chg) VALUES (?,?,?,?,?,?)''',
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

    conn = sqlite3.connect(DB_PATH)
    latest = conn.execute("SELECT MAX(date) FROM margin_data").fetchone()[0]
    conn.close()

    # 最近5个交易日的日期
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
    for date_str in sorted(dates_to_fetch):
        try:
            df = ak.stock_margin_detail_sse(date=date_str)
            if df is None or df.empty:
                log(f"  融资融券 {date_str} 无数据，跳过")
                continue
            # 汇总当日全市场数据
            margin_balance = 0
            margin_buy = 0
            short_sell = 0
            short_amount = 0
            short_volume = 0
            for _, row in df.iterrows():
                margin_balance += float(row.get('融资余额', 0) or 0)
                margin_buy += float(row.get('融资买入额', 0) or 0)
                short_sell += float(row.get('融券卖出量', 0) or 0)
                short_amount += float(row.get('融券卖出额', 0) or 0)
                short_volume += float(row.get('融券余量', 0) or 0)

            conn2 = sqlite3.connect(DB_PATH)
            conn2.execute('''INSERT OR IGNORE INTO margin_data
                (date, margin_balance, margin_buy, short_volume, short_amount,
                 short_sell, total_balance) VALUES (?,?,?,?,?,?,?)''',
                (date_str, margin_balance, margin_buy, short_volume,
                 short_amount, short_sell, margin_balance + short_amount))
            conn2.commit()
            conn2.close()
            count += 1
        except Exception as e:
            log(f"  融资融券 {date_str} 失败: {e}")
        time.sleep(1)

    log(f"  融资融券完成: 新增{count}天")

# ============================================================
# 11. 股东数据增量更新（抽样）
# ============================================================
def sync_shareholder_data():
    log("=== 同步股东数据（滚动500只）===")
    try:
        import akshare as ak
    except ImportError:
        log("  akshare 未安装，跳过")
        return

    conn = sqlite3.connect(DB_PATH)
    # 找出最久没更新的500只
    stale = conn.execute('''
        SELECT k.symbol FROM kline_daily k
        LEFT JOIN (
            SELECT symbol, MAX(created_at) as latest FROM shareholder_data GROUP BY symbol
        ) s ON k.symbol = s.symbol
        GROUP BY k.symbol
        ORDER BY COALESCE(s.latest, '2000-01-01') ASC
        LIMIT 500
    ''').fetchall()
    symbols = [r[0] for r in stale]
    conn.close()

    log(f"  待更新: {len(symbols)}只（最久未更新优先）")
    count = 0
    failed = 0

    for i, symbol in enumerate(symbols):
        code = symbol[2:] if symbol.startswith(('sz', 'sh')) else symbol
        try:
            df = ak.stock_circulate_stock_holder(symbol=code)
            if df is not None and not df.empty:
                conn2 = sqlite3.connect(DB_PATH)
                for _, row in df.iterrows():
                    rd = str(row.get('日期', ''))
                    name = str(row.get('股东名称', ''))
                    hold_num = float(row.get('持股数量', 0) or 0)
                    hold_ratio = float(row.get('持股比例', 0) or 0)
                    conn2.execute('''INSERT OR IGNORE INTO shareholder_data
                        (symbol, report_date, name, shareholder_count,
                         change_pct, avg_holdings) VALUES (?,?,?,?,?,?)''',
                        (symbol, rd, name, int(hold_num), hold_ratio, 0))
                    count += 1
                conn2.commit()
                conn2.close()
        except:
            failed += 1

        if (i + 1) % 100 == 0:
            log(f"  股东数据进度: {i+1}/{len(symbols)} 成功{count}条 失败{failed}只")
        time.sleep(0.3)

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

    conn = sqlite3.connect(DB_PATH)
    latest = conn.execute("SELECT MAX(date) FROM limit_up_down").fetchone()[0]
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
                conn2 = sqlite3.connect(DB_PATH)
                for _, row in df.iterrows():
                    code = str(row.get('代码', ''))
                    conn2.execute('''INSERT OR IGNORE INTO limit_up_down
                        (date, code, name, chg_pct, close, amount, mkt_cap,
                         turnover, seal_amount, first_seal_time, last_seal_time,
                         break_count, consecutive, industry, type)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
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
                conn2 = sqlite3.connect(DB_PATH)
                for _, row in df.iterrows():
                    code = str(row.get('代码', ''))
                    conn2.execute('''INSERT OR IGNORE INTO limit_up_down
                        (date, code, name, chg_pct, close, amount, mkt_cap,
                         turnover, type)
                        VALUES (?,?,?,?,?,?,?,?,?)''',
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

    conn = sqlite3.connect(DB_PATH)
    # 建表
    conn.execute('''CREATE TABLE IF NOT EXISTS news_daily (
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
    watchlist = conn.execute("SELECT symbol, name FROM watchlist").fetchall()
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

            conn2 = sqlite3.connect(DB_PATH)
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

    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS market_review (
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
            check_date = conn.execute(
                "SELECT trade_date FROM kline_daily WHERE trade_date < ? "
                "GROUP BY trade_date "
                "HAVING COUNT(*) > 4000 ORDER BY trade_date DESC LIMIT 1",
                (today_str,)
            ).fetchone()
            if check_date:
                review_date = check_date[0]
                stats = conn.execute(f'''
                    SELECT 
                        SUM(CASE WHEN CAST(chg_pct AS REAL) > 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) < 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) = 0 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) >= 9.9 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN CAST(chg_pct AS REAL) <= -9.9 THEN 1 ELSE 0 END)
                    FROM kline_daily WHERE trade_date = '{review_date}'
                ''').fetchone()
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
        conn.execute('''INSERT OR REPLACE INTO market_review
            (trade_date, index_data, up_count, down_count, flat_count,
             limit_up, limit_down, top_sectors, bottom_sectors)
            VALUES (?,?,?,?,?,?,?,?,?)''',
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

    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS chip_distribution (
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
    watchlist = conn.execute("SELECT symbol, name FROM watchlist").fetchall()
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

            conn2 = sqlite3.connect(DB_PATH)
            conn2.execute('''INSERT OR REPLACE INTO chip_distribution
                (symbol, trade_date, chip_data, avg_cost, profit_ratio,
                 concentration_90, concentration_70)
                VALUES (?,?,?,?,?,?,?)''',
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

    conn = sqlite3.connect(DB_PATH)
    total = 0

    for symbol, name in INDEX_SYMBOLS.items():
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                log(f"  {name}({symbol}): 无数据")
                continue

            latest = conn.execute(
                "SELECT MAX(trade_date) FROM kline_daily_index WHERE symbol=?",
                (symbol,)).fetchone()[0]

            count = 0
            for _, row in df.iterrows():
                trade_date = str(row['date'])[:10]
                if latest and trade_date <= latest:
                    continue

                close = float(row.get('close', 0) or 0)
                prev_close = None
                prev = conn.execute(
                    "SELECT close FROM kline_daily_index WHERE symbol=? AND trade_date<? ORDER BY trade_date DESC LIMIT 1",
                    (symbol, trade_date)).fetchone()
                if prev:
                    prev_close = prev[0]

                pct_change = ((close - prev_close) / prev_close * 100) if prev_close else 0

                conn.execute('''INSERT OR REPLACE INTO kline_daily_index
                    (symbol, trade_date, open, high, low, close, volume, amount, pct_change)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
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
        rows = conn.execute(
            "SELECT trade_date, close FROM kline_daily_index WHERE symbol=? ORDER BY trade_date",
            (symbol,)).fetchall()
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
                conn.execute(f"UPDATE kline_daily_index SET {set_clause} WHERE symbol=? AND trade_date=?", vals)
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

    conn = sqlite3.connect(DB_PATH)
    latest = conn.execute("SELECT MAX(trade_date) FROM lhb_detail").fetchone()[0]
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

        conn = sqlite3.connect(DB_PATH)
        for _, row in df.iterrows():
            trade_date = str(row.get('上榜日', ''))[:10]
            if latest and trade_date <= latest:
                continue
            try:
                conn.execute('''INSERT OR IGNORE INTO lhb_detail
                    (trade_date, code, name, reason, buy_amount, sell_amount,
                     net_amount, turnover, mkt_cap, chg_after_1d, chg_after_5d,
                     buy_seats, sell_seats, data_source)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
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

    conn = sqlite3.connect(DB_PATH)
    latest = conn.execute("SELECT MAX(trade_date) FROM block_trades").fetchone()[0]
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

        conn = sqlite3.connect(DB_PATH)
        for _, row in df.iterrows():
            trade_date = str(row.get('交易日期', ''))[:10]
            try:
                conn.execute('''INSERT OR IGNORE INTO block_trades
                    (trade_date, code, name, price, volume, amount, buyer, seller)
                    VALUES (?,?,?,?,?,?,?,?)''',
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
    parser.add_argument('--limit', action='store_true', help='只同步涨跌停')
    parser.add_argument('--news', action='store_true', help='只同步新闻')
    parser.add_argument('--review', action='store_true', help='只同步大盘复盘')
    parser.add_argument('--chip', action='store_true', help='只同步筹码分布')
    parser.add_argument('--index', action='store_true', help='只同步大盘指数K线')
    parser.add_argument('--lhb', action='store_true', help='只同步龙虎榜')
    parser.add_argument('--block', action='store_true', help='只同步大宗交易')
    parser.add_argument('--full', action='store_true', help='全量同步（包含周/月K线）')
    args = parser.parse_args()

    run_all = args.full
    # 只在没有指定任何单项参数时，才跑全部每日流程
    single_flags = [args.kline, args.fund, args.tech, args.weekly, args.monthly,
                    args.valuation, args.flow, args.industry, args.northbound,
                    args.margin, args.shareholder, args.limit,
                    args.news, args.review, args.chip,
                    args.index, args.lhb, args.block]
    run_daily = not any(single_flags) and not args.full

    log(f"{'='*50}")
    log(f"每日数据同步开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"{'='*50}")

    start_time = time.time()

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
        sync_capital_flow()
    if run_all or run_daily or args.industry:
        sync_industry()

    # 新增数据源（每日更新）
    if run_all or run_daily or args.northbound:
        sync_northbound_flow()
    if run_all or run_daily or args.margin:
        sync_margin_data()
    if run_all or run_daily or args.shareholder:
        sync_shareholder_data()
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
                args.index, args.lhb, args.block]):
        validate_and_report(elapsed)

# ============================================================
# 校验 & 飞书告警
# ============================================================
def validate_and_report(elapsed):
    """同步后校验数据完整性，异常发飞书告警"""
    log("=== 数据完整性校验 ===")
    conn = sqlite3.connect(DB_PATH)
    today = datetime.now().strftime('%Y-%m-%d')
    errors = []
    warnings = []
    stats = {}

    # 1. 日K线 — 最新日期
    latest_kline = conn.execute("SELECT MAX(trade_date) FROM kline_daily").fetchone()[0]
    kline_today = conn.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{latest_kline}'").fetchone()[0]
    total_stocks = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_daily").fetchone()[0]
    stats['kline'] = f"{latest_kline} {kline_today}/{total_stocks}只"

    if not latest_kline or latest_kline < (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'):
        errors.append(f"日K线严重滞后: 最新{latest_kline}")
    elif kline_today < 3000:
        warnings.append(f"日K线偏少: {latest_kline}只有{kline_today}只（期望≥4000）")

    # 2. 技术指标 — RSI/MA
    has_rsi = conn.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{latest_kline}' AND rsi14 IS NOT NULL").fetchone()[0]
    if has_rsi < kline_today * 0.7:
        warnings.append(f"RSI计算不全: {has_rsi}/{kline_today}只")

    # 3. 资金流向
    flow_latest = conn.execute("SELECT MAX(trade_date) FROM capital_flow").fetchone()[0]
    flow_count = conn.execute(f"SELECT COUNT(*) FROM capital_flow WHERE trade_date='{flow_latest}'").fetchone()[0] if flow_latest else 0
    stats['capital_flow'] = f"{flow_latest} {flow_count}只"

    # 4. 估值
    val_latest = conn.execute("SELECT MAX(trade_date) FROM daily_valuation").fetchone()[0]
    val_count = conn.execute(f"SELECT COUNT(*) FROM daily_valuation WHERE trade_date='{val_latest}'").fetchone()[0] if val_latest else 0
    stats['valuation'] = f"{val_latest} {val_count}只"

    # 5. 北向资金
    nb_latest = conn.execute("SELECT MAX(date) FROM northbound_flow").fetchone()[0]
    stats['northbound'] = nb_latest or "无数据"

    # 6. 融资融券
    margin_latest = conn.execute("SELECT MAX(date) FROM margin_data").fetchone()[0]
    stats['margin'] = margin_latest or "无数据"

    # 7. 涨跌停
    limit_latest = conn.execute("SELECT MAX(date) FROM limit_up_down").fetchone()[0]
    stats['limit_up_down'] = limit_latest or "无数据"

    # 8. 财务指标
    fund_count = conn.execute("SELECT COUNT(DISTINCT symbol) FROM financial_indicators WHERE roe IS NOT NULL").fetchone()[0]
    stats['financial'] = f"{fund_count}只"
    if fund_count < 3000:
        warnings.append(f"财务指标偏少: {fund_count}只")

    conn.close()

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
