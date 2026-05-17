# -*- coding: utf-8 -*-
from jqdata import *
import pandas as pd
import numpy as np

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('BB1.02_KDJ 策略回测启动')

    set_order_cost(
        OrderCost(
            close_tax=0.001,
            open_commission=0.0003,
            close_commission=0.0003,
            min_commission=5
        ),
        type='stock'
    )

    g.strategy_name = 'BB1.02_KDJ'
    g.rsi_threshold = 20
    g.bb_mult = 1.02
    g.weak_pct = 0.70
    g.top_n = 500
    g.hold_days = 7
    g.max_positions = 5

    g.buy_list = []
    g.hold_info = {}

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(before_close, time='before_close', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


def before_market_open(context):
    log.info('before_market_open: {}'.format(context.current_dt))
    g.buy_list = []

    if not is_weak_market(context):
        log.info('当前非弱市，不触发 {}'.format(g.strategy_name))
        return

    stock_pool = get_stock_pool(context)
    selected = []

    for stock in stock_pool:
        try:
            if check_buy_signal(context, stock):
                selected.append(stock)
        except Exception as e:
            log.info('检查 {} 失败: {}'.format(stock, e))

    g.buy_list = selected[:g.max_positions]
    log.info('买入列表: {}'.format(g.buy_list))


def market_open(context):
    buy_stocks(context)


def before_close(context):
    sell_stocks(context)


def after_market_close(context):
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录: {}'.format(_trade))
    log.info('一天结束')
    log.info('##############################################################')


def get_stock_pool(context):
    all_stocks = get_all_securities(types=['stock'], date=context.current_dt).index.tolist()
    current_data = get_current_data()

    candidates = []
    for s in all_stocks:
        try:
            if current_data[s].paused:
                continue
            if current_data[s].is_st:
                continue
            name = current_data[s].name
            if 'ST' in name or '*' in name:
                continue
            if (context.current_dt.date() - get_security_info(s).start_date).days < 60:
                continue
            candidates.append(s)
        except:
            continue

    q = query(
        valuation.code,
        valuation.circulating_market_cap
    ).filter(
        valuation.code.in_(candidates)
    ).order_by(
        valuation.circulating_market_cap.desc()
    ).limit(g.top_n)

    df = get_fundamentals(q)
    if df is None or len(df) == 0:
        return []

    return list(df['code'])


def is_weak_market(context):
    stocks = get_stock_pool(context)
    if len(stocks) == 0:
        return False

    stocks = stocks[:500]
    below_count = 0
    valid_count = 0

    for stock in stocks:
        try:
            df = get_bars(stock, count=25, unit='1d', fields=['close'], include_now=False)
            if df is None or len(df) < 20:
                continue

            closes = pd.Series(df['close'])
            ma20 = closes.iloc[-20:].mean()
            last_close = closes.iloc[-1]

            valid_count += 1
            if last_close < ma20:
                below_count += 1
        except:
            continue

    if valid_count < 50:
        return False

    ratio = below_count * 1.0 / valid_count
    log.info('弱市判断: {:.2%}'.format(ratio))
    return ratio > g.weak_pct


def check_buy_signal(context, stock):
    bars = get_bars(
        stock,
        count=40,
        unit='1d',
        fields=['high', 'low', 'close'],
        include_now=False
    )
    if bars is None or len(bars) < 25:
        return False

    highs = pd.Series(bars['high'])
    lows = pd.Series(bars['low'])
    closes = pd.Series(bars['close'])
    rsi = calc_rsi(closes, 14)
    if np.isnan(rsi) or rsi >= g.rsi_threshold or rsi < 10:
        return False

    _, _, bb_lower = calc_boll(closes, 20, 2)
    last_close = closes.iloc[-1]
    if np.isnan(bb_lower) or last_close > bb_lower * g.bb_mult:
        return False

    k_val, d_val, j_val = calc_kdj(highs, lows, closes, 9, 3, 3)
    cond_k = (not np.isnan(k_val)) and (k_val < 20)
    cond_j = (not np.isnan(j_val)) and (j_val < 0)

    return cond_k or cond_j


def buy_stocks(context):
    if len(g.buy_list) == 0:
        return

    current_positions = list(context.portfolio.positions.keys())
    available_slots = g.max_positions - len(current_positions)
    if available_slots <= 0:
        return

    to_buy = [s for s in g.buy_list if s not in current_positions][:available_slots]
    if len(to_buy) == 0:
        return

    cash = context.portfolio.available_cash
    if cash <= 0:
        return

    per_stock_cash = cash / len(to_buy)

    for stock in to_buy:
        order_value(stock, per_stock_cash)
        current = get_current_data()[stock]
        buy_price = current.day_open if current.day_open and current.day_open > 0 else current.last_price
        if buy_price is None or buy_price <= 0:
            pos = context.portfolio.positions.get(stock)
            buy_price = pos.avg_cost if pos is not None else 0
        g.hold_info[stock] = {
            'buy_date': context.current_dt.date(),
            'buy_price': buy_price
        }
        log.info('买入 {}'.format(stock))


def sell_stocks(context):
    positions = context.portfolio.positions

    for stock in list(positions.keys()):
        pos = positions[stock]
        if pos.closeable_amount <= 0:
            continue

        if stock not in g.hold_info:
            g.hold_info[stock] = {
                'buy_date': context.current_dt.date(),
                'buy_price': pos.avg_cost
            }

        held_days = (context.current_dt.date() - g.hold_info[stock]['buy_date']).days
        if held_days >= g.hold_days:
            log.info('卖出 {}，原因: 固定持有到期'.format(stock))
            order_target(stock, 0)
            if stock in g.hold_info:
                del g.hold_info[stock]


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    last_gain = avg_gain.iloc[-1]
    last_loss = avg_loss.iloc[-1]

    if np.isnan(last_gain) or np.isnan(last_loss):
        return np.nan
    if last_loss == 0:
        return 100.0

    rs = last_gain / last_loss
    return 100 - (100 / (1 + rs))


def calc_boll(series, period=20, num_std=2):
    if len(series) < period:
        return np.nan, np.nan, np.nan

    window = series.iloc[-period:]
    middle = window.mean()
    std = window.std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def calc_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    if len(closes) < n:
        return np.nan, np.nan, np.nan

    low_list = lows.rolling(n).min()
    high_list = highs.rolling(n).max()
    denom = (high_list - low_list).replace(0, np.nan)
    rsv = (closes - low_list) / denom * 100
    rsv = rsv.fillna(50)

    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k.iloc[-1], d.iloc[-1], j.iloc[-1]
