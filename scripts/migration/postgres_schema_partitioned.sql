-- PostgreSQL partitioned schema (monthly range partitions on date-like columns)
CREATE SCHEMA IF NOT EXISTS public;

CREATE TABLE IF NOT EXISTS public."daily_valuation" (
    "symbol" TEXT NOT NULL,
    "trade_date" DATE NOT NULL,
    "pe_ttm" DOUBLE PRECISION,
    "pb" DOUBLE PRECISION,
    "ps_ttm" DOUBLE PRECISION,
    PRIMARY KEY ("symbol", "trade_date")
) PARTITION BY RANGE ("trade_date");

CREATE TABLE IF NOT EXISTS public."financial_daily" (
    "symbol" TEXT NOT NULL,
    "trade_date" DATE NOT NULL,
    "eps" DOUBLE PRECISION,
    "roe" DOUBLE PRECISION,
    "revenue_growth" DOUBLE PRECISION,
    "profit_growth" DOUBLE PRECISION,
    "gross_margin" DOUBLE PRECISION,
    "net_margin" DOUBLE PRECISION,
    "debt_ratio" DOUBLE PRECISION,
    "current_ratio" DOUBLE PRECISION,
    "total_assets" DOUBLE PRECISION,
    PRIMARY KEY ("symbol", "trade_date")
) PARTITION BY RANGE ("trade_date");

CREATE TABLE IF NOT EXISTS public."kline_daily_index" (
    "symbol" TEXT NOT NULL,
    "trade_date" DATE NOT NULL,
    "open" DOUBLE PRECISION,
    "high" DOUBLE PRECISION,
    "low" DOUBLE PRECISION,
    "close" DOUBLE PRECISION,
    "volume" DOUBLE PRECISION,
    "amount" DOUBLE PRECISION,
    "pct_change" DOUBLE PRECISION,
    "ma5" DOUBLE PRECISION,
    "ma10" DOUBLE PRECISION,
    "ma20" DOUBLE PRECISION,
    "rsi14" DOUBLE PRECISION,
    PRIMARY KEY ("symbol", "trade_date")
) PARTITION BY RANGE ("trade_date");

CREATE TABLE IF NOT EXISTS public."margin_data" (
    "date" DATE NOT NULL,
    "margin_balance" DOUBLE PRECISION,
    "margin_buy" DOUBLE PRECISION,
    "short_volume" DOUBLE PRECISION,
    "short_amount" DOUBLE PRECISION,
    "short_sell" DOUBLE PRECISION,
    "total_balance" DOUBLE PRECISION,
    PRIMARY KEY ("date")
) PARTITION BY RANGE ("date");

CREATE TABLE IF NOT EXISTS public."kline_daily" (
    "id" BIGINT NOT NULL,
    "symbol" TEXT NOT NULL,
    "trade_date" DATE NOT NULL,
    "open" DOUBLE PRECISION NOT NULL,
    "close" DOUBLE PRECISION NOT NULL,
    "high" DOUBLE PRECISION NOT NULL,
    "low" DOUBLE PRECISION NOT NULL,
    "volume" DOUBLE PRECISION,
    "amount" DOUBLE PRECISION,
    "chg" DOUBLE PRECISION,
    "chg_pct" DOUBLE PRECISION,
    "ma5" DOUBLE PRECISION,
    "ma10" DOUBLE PRECISION,
    "ma20" DOUBLE PRECISION,
    "ma60" DOUBLE PRECISION,
    "rsi14" DOUBLE PRECISION,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "macd_dif" DOUBLE PRECISION,
    "macd_dea" DOUBLE PRECISION,
    "macd_hist" DOUBLE PRECISION,
    "boll_upper" DOUBLE PRECISION,
    "boll_mid" DOUBLE PRECISION,
    "boll_lower" DOUBLE PRECISION,
    "kdj_k" DOUBLE PRECISION,
    "kdj_d" DOUBLE PRECISION,
    "kdj_j" DOUBLE PRECISION,
    "adx" DOUBLE PRECISION,
    "plus_di" DOUBLE PRECISION,
    "minus_di" DOUBLE PRECISION,
    "atr" DOUBLE PRECISION,
    "atr14" DOUBLE PRECISION,
    "bb_width" DOUBLE PRECISION,
    "obv" DOUBLE PRECISION,
    "turnover_avg20" DOUBLE PRECISION,
    "turnover_spike" DOUBLE PRECISION,
    "rel_strength_5d" DOUBLE PRECISION,
    "rel_strength_10d" DOUBLE PRECISION,
    "rel_strength_20d" DOUBLE PRECISION,
    "volume_avg20" DOUBLE PRECISION,
    "volume_spike" DOUBLE PRECISION,
    "plus_di14" DOUBLE PRECISION,
    "minus_di14" DOUBLE PRECISION,
    "adx14" DOUBLE PRECISION,
    "main_inflow_strength" DOUBLE PRECISION,
    "main_inflow_3d_days" DOUBLE PRECISION,
    "north_hold_pct" DOUBLE PRECISION,
    "north_hold_change" DOUBLE PRECISION,
    "north_buy_streak" DOUBLE PRECISION,
    "pe_pct_252" DOUBLE PRECISION,
    "pb_pct_252" DOUBLE PRECISION,
    "drawdown_20d" DOUBLE PRECISION,
    "rebound_from_low_20d" DOUBLE PRECISION,
    "up_streak" DOUBLE PRECISION,
    "down_streak" DOUBLE PRECISION,
    PRIMARY KEY ("id", "trade_date")
) PARTITION BY RANGE ("trade_date");
CREATE INDEX IF NOT EXISTS idx_kline_daily_symbol_trade_date ON public."kline_daily" ("symbol", "trade_date");

CREATE TABLE IF NOT EXISTS public."capital_flow" (
    "id" BIGINT NOT NULL,
    "symbol" TEXT NOT NULL,
    "trade_date" DATE NOT NULL,
    "main_net_inflow" DOUBLE PRECISION,
    "super_large_net_inflow" DOUBLE PRECISION,
    "large_net_inflow" DOUBLE PRECISION,
    "medium_net_inflow" DOUBLE PRECISION,
    "small_net_inflow" DOUBLE PRECISION,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    "data_source" TEXT DEFAULT 'api',
    PRIMARY KEY ("id", "trade_date")
) PARTITION BY RANGE ("trade_date");
CREATE INDEX IF NOT EXISTS idx_capital_flow_symbol_trade_date ON public."capital_flow" ("symbol", "trade_date");

CREATE TABLE IF NOT EXISTS public."northbound_holdings" (
    "id" BIGINT NOT NULL,
    "symbol" TEXT NOT NULL,
    "trade_date" DATE NOT NULL,
    "hold_shares" DOUBLE PRECISION,
    "hold_pct" DOUBLE PRECISION,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id", "trade_date")
) PARTITION BY RANGE ("trade_date");
CREATE INDEX IF NOT EXISTS idx_northbound_holdings_symbol_trade_date ON public."northbound_holdings" ("symbol", "trade_date");

CREATE TABLE IF NOT EXISTS public."northbound_flow" (
    "id" BIGINT NOT NULL,
    "date" DATE NOT NULL,
    "type" TEXT,
    "direction" TEXT,
    "net_buy" DOUBLE PRECISION,
    "net_flow" DOUBLE PRECISION,
    "up_count" BIGINT,
    "down_count" BIGINT,
    "index_chg" DOUBLE PRECISION,
    PRIMARY KEY ("id", "date")
) PARTITION BY RANGE ("date");
CREATE INDEX IF NOT EXISTS idx_northbound_flow_date ON public."northbound_flow" ("date");
