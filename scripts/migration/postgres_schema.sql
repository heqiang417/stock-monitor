-- Auto-generated from SQLite schema
CREATE SCHEMA IF NOT EXISTS public;

DROP TABLE IF EXISTS public."alert_history" CASCADE;
CREATE TABLE public."alert_history" (
    "id" BIGINT,
    "timestamp" BIGINT NOT NULL,
    "stock" TEXT,
    "price" DOUBLE PRECISION,
    "chg_pct" DOUBLE PRECISION,
    "strategy_id" TEXT,
    "strategy_name" TEXT,
    "trigger_condition" TEXT,
    "message" TEXT,
    "level" TEXT DEFAULT 'info',
    "feishu_sent" BIGINT DEFAULT 0,
    "is_read" BIGINT DEFAULT 0,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."alerts" CASCADE;
CREATE TABLE public."alerts" (
    "id" BIGINT,
    "timestamp" BIGINT NOT NULL,
    "strategy_id" TEXT,
    "message" TEXT,
    "level" TEXT DEFAULT 'info',
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    "stock" TEXT DEFAULT '',
    "trigger_condition" TEXT DEFAULT '',
    "price" DOUBLE PRECISION,
    "is_read" BIGINT DEFAULT 0,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."block_trades" CASCADE;
CREATE TABLE public."block_trades" (
    "id" BIGINT,
    "trade_date" TEXT,
    "code" TEXT,
    "name" TEXT,
    "price" DOUBLE PRECISION,
    "volume" DOUBLE PRECISION,
    "amount" DOUBLE PRECISION,
    "buyer" TEXT,
    "seller" TEXT,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."capital_flow" CASCADE;
CREATE TABLE public."capital_flow" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "trade_date" TEXT NOT NULL,
    "main_net_inflow" DOUBLE PRECISION,
    "super_large_net_inflow" DOUBLE PRECISION,
    "large_net_inflow" DOUBLE PRECISION,
    "medium_net_inflow" DOUBLE PRECISION,
    "small_net_inflow" DOUBLE PRECISION,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    "data_source" TEXT DEFAULT 'api',
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."chip_distribution" CASCADE;
CREATE TABLE public."chip_distribution" (
    "symbol" TEXT NOT NULL,
    "trade_date" TEXT NOT NULL,
    "chip_data" TEXT,
    "avg_cost" DOUBLE PRECISION,
    "profit_ratio" DOUBLE PRECISION,
    "concentration_90" DOUBLE PRECISION,
    "concentration_70" DOUBLE PRECISION,
    PRIMARY KEY ("symbol", "trade_date")
);

DROP TABLE IF EXISTS public."daily_valuation" CASCADE;
CREATE TABLE public."daily_valuation" (
    "symbol" TEXT,
    "trade_date" TEXT,
    "pe_ttm" DOUBLE PRECISION,
    "pb" DOUBLE PRECISION,
    "ps_ttm" DOUBLE PRECISION,
    PRIMARY KEY ("symbol", "trade_date")
);

DROP TABLE IF EXISTS public."dividends" CASCADE;
CREATE TABLE public."dividends" (
    "id" BIGINT,
    "stock_code" TEXT NOT NULL,
    "stock_name" TEXT,
    "announce_date" TEXT,
    "div_type" TEXT,
    "bonus_ratio" DOUBLE PRECISION,
    "transfer_ratio" DOUBLE PRECISION,
    "cash_div" DOUBLE PRECISION,
    "record_date" TEXT,
    "ex_div_date" TEXT,
    "pay_date" TEXT,
    "shares_arrive_date" TEXT,
    "div_desc" TEXT,
    "report_period" TEXT,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."earnings_forecast" CASCADE;
CREATE TABLE public."earnings_forecast" (
    "code" TEXT,
    "name" TEXT,
    "report_date" TEXT,
    "forecast_type" TEXT,
    "forecast_content" TEXT,
    "profit_min" DOUBLE PRECISION,
    "profit_max" DOUBLE PRECISION,
    "forecast_change_min" DOUBLE PRECISION,
    "forecast_change_max" DOUBLE PRECISION,
    "reason" TEXT,
    "prev_year_value" DOUBLE PRECISION,
    "announce_date" TEXT,
    PRIMARY KEY ("code", "report_date", "forecast_type")
);

DROP TABLE IF EXISTS public."financial_daily" CASCADE;
CREATE TABLE public."financial_daily" (
    "symbol" TEXT NOT NULL,
    "trade_date" TEXT NOT NULL,
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
);

DROP TABLE IF EXISTS public."financial_indicators" CASCADE;
CREATE TABLE public."financial_indicators" (
    "symbol" TEXT,
    "report_date" TEXT,
    "eps" DOUBLE PRECISION,
    "roe" DOUBLE PRECISION,
    "revenue_growth" DOUBLE PRECISION,
    "profit_growth" DOUBLE PRECISION,
    "gross_margin" DOUBLE PRECISION,
    "net_margin" DOUBLE PRECISION,
    "debt_ratio" DOUBLE PRECISION,
    "current_ratio" DOUBLE PRECISION,
    "total_assets" DOUBLE PRECISION,
    PRIMARY KEY ("symbol", "report_date")
);

DROP TABLE IF EXISTS public."fund_flow" CASCADE;
CREATE TABLE public."fund_flow" (
    "symbol" TEXT NOT NULL,
    "date" TEXT NOT NULL,
    "close" DOUBLE PRECISION,
    "chg_pct" DOUBLE PRECISION,
    "main_net_inflow" DOUBLE PRECISION,
    "super_net_inflow" DOUBLE PRECISION,
    "big_net_inflow" DOUBLE PRECISION,
    "mid_net_inflow" DOUBLE PRECISION,
    "small_net_inflow" DOUBLE PRECISION,
    "main_pct" DOUBLE PRECISION,
    "super_pct" DOUBLE PRECISION,
    "big_pct" DOUBLE PRECISION,
    "mid_pct" DOUBLE PRECISION,
    "small_pct" DOUBLE PRECISION,
    PRIMARY KEY ("symbol", "date")
);

DROP TABLE IF EXISTS public."institutional_data" CASCADE;
CREATE TABLE public."institutional_data" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "name" TEXT,
    "latest_price" DOUBLE PRECISION,
    "change_pct" DOUBLE PRECISION,
    "institution_count" BIGINT,
    "reception_method" TEXT,
    "reception_personnel" TEXT,
    "reception_location" TEXT,
    "reception_date" TEXT,
    "announcement_date" TEXT,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."kline_daily" CASCADE;
CREATE TABLE public."kline_daily" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "trade_date" TEXT NOT NULL,
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
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
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
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."kline_daily_index" CASCADE;
CREATE TABLE public."kline_daily_index" (
    "symbol" TEXT,
    "trade_date" TEXT,
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
);

DROP TABLE IF EXISTS public."kline_monthly" CASCADE;
CREATE TABLE public."kline_monthly" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "trade_month" TEXT NOT NULL,
    "open" DOUBLE PRECISION NOT NULL,
    "close" DOUBLE PRECISION NOT NULL,
    "high" DOUBLE PRECISION NOT NULL,
    "low" DOUBLE PRECISION NOT NULL,
    "volume" DOUBLE PRECISION,
    "amount" DOUBLE PRECISION,
    "chg" DOUBLE PRECISION,
    "chg_pct" DOUBLE PRECISION,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."kline_weekly" CASCADE;
CREATE TABLE public."kline_weekly" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "trade_week" TEXT NOT NULL,
    "open" DOUBLE PRECISION NOT NULL,
    "close" DOUBLE PRECISION NOT NULL,
    "high" DOUBLE PRECISION NOT NULL,
    "low" DOUBLE PRECISION NOT NULL,
    "volume" DOUBLE PRECISION,
    "amount" DOUBLE PRECISION,
    "chg" DOUBLE PRECISION,
    "chg_pct" DOUBLE PRECISION,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."lhb_detail" CASCADE;
CREATE TABLE public."lhb_detail" (
    "id" BIGINT,
    "trade_date" TEXT,
    "code" TEXT,
    "name" TEXT,
    "reason" TEXT,
    "buy_amount" DOUBLE PRECISION,
    "sell_amount" DOUBLE PRECISION,
    "net_amount" DOUBLE PRECISION,
    "turnover" DOUBLE PRECISION,
    "mkt_cap" DOUBLE PRECISION,
    "chg_after_1d" DOUBLE PRECISION,
    "chg_after_5d" DOUBLE PRECISION,
    "buy_seats" TEXT,
    "sell_seats" TEXT,
    "data_source" TEXT,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."limit_up_down" CASCADE;
CREATE TABLE public."limit_up_down" (
    "date" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "name" TEXT,
    "chg_pct" DOUBLE PRECISION,
    "close" DOUBLE PRECISION,
    "amount" DOUBLE PRECISION,
    "mkt_cap" DOUBLE PRECISION,
    "turnover" DOUBLE PRECISION,
    "seal_amount" DOUBLE PRECISION,
    "first_seal_time" TEXT,
    "last_seal_time" TEXT,
    "break_count" BIGINT,
    "consecutive" BIGINT,
    "industry" TEXT,
    "type" TEXT,
    PRIMARY KEY ("date", "code", "type")
);

DROP TABLE IF EXISTS public."margin_data" CASCADE;
CREATE TABLE public."margin_data" (
    "date" TEXT NOT NULL,
    "margin_balance" DOUBLE PRECISION,
    "margin_buy" DOUBLE PRECISION,
    "short_volume" DOUBLE PRECISION,
    "short_amount" DOUBLE PRECISION,
    "short_sell" DOUBLE PRECISION,
    "total_balance" DOUBLE PRECISION,
    PRIMARY KEY ("date")
);

DROP TABLE IF EXISTS public."margin_szse" CASCADE;
CREATE TABLE public."margin_szse" (
    "date" TEXT,
    "margin_buy" DOUBLE PRECISION,
    "margin_balance" DOUBLE PRECISION,
    "short_sell" DOUBLE PRECISION,
    "short_volume" DOUBLE PRECISION,
    "short_balance" DOUBLE PRECISION,
    "total_balance" DOUBLE PRECISION,
    PRIMARY KEY ("date")
);

DROP TABLE IF EXISTS public."market_review" CASCADE;
CREATE TABLE public."market_review" (
    "trade_date" TEXT,
    "index_data" TEXT,
    "up_count" BIGINT,
    "down_count" BIGINT,
    "flat_count" BIGINT,
    "limit_up" BIGINT,
    "limit_down" BIGINT,
    "top_sectors" TEXT,
    "bottom_sectors" TEXT,
    PRIMARY KEY ("trade_date")
);

DROP TABLE IF EXISTS public."news_daily" CASCADE;
CREATE TABLE public."news_daily" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "title" TEXT,
    "url" TEXT,
    "snippet" TEXT,
    "publish_date" TEXT,
    "source" TEXT,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."northbound_flow" CASCADE;
CREATE TABLE public."northbound_flow" (
    "id" BIGINT,
    "date" TEXT,
    "type" TEXT,
    "direction" TEXT,
    "net_buy" DOUBLE PRECISION,
    "net_flow" DOUBLE PRECISION,
    "up_count" BIGINT,
    "down_count" BIGINT,
    "index_chg" DOUBLE PRECISION,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."northbound_holdings" CASCADE;
CREATE TABLE public."northbound_holdings" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "trade_date" TEXT NOT NULL,
    "hold_shares" DOUBLE PRECISION,
    "hold_pct" DOUBLE PRECISION,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."option_data" CASCADE;
CREATE TABLE public."option_data" (
    "date" TEXT,
    "code" TEXT,
    "name" TEXT,
    "close" DOUBLE PRECISION,
    "volume" DOUBLE PRECISION,
    "amount" DOUBLE PRECISION,
    "oi" DOUBLE PRECISION,
    "pcr" DOUBLE PRECISION,
    PRIMARY KEY ("date", "code")
);

DROP TABLE IF EXISTS public."share_lock" CASCADE;
CREATE TABLE public."share_lock" (
    "id" BIGINT,
    "stock_code" TEXT NOT NULL,
    "stock_name" TEXT,
    "unlock_date" TEXT NOT NULL,
    "share_type" TEXT,
    "unlock_shares" DOUBLE PRECISION,
    "actual_unlock_shares" DOUBLE PRECISION,
    "actual_unlock_value" DOUBLE PRECISION,
    "ratio" DOUBLE PRECISION,
    "prev_close" DOUBLE PRECISION,
    "prev20d_chg" DOUBLE PRECISION,
    "post20d_chg" DOUBLE PRECISION,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."share_unlock" CASCADE;
CREATE TABLE public."share_unlock" (
    "date" TEXT,
    "code" TEXT,
    "name" TEXT,
    "unlock_amount" DOUBLE PRECISION,
    "unlock_ratio" DOUBLE PRECISION,
    "price" DOUBLE PRECISION,
    "actual_unlock_amount" DOUBLE PRECISION,
    "actual_unlock_market_value" DOUBLE PRECISION,
    "pre_20d_change" DOUBLE PRECISION,
    "post_20d_change" DOUBLE PRECISION,
    PRIMARY KEY ("date", "code")
);

DROP TABLE IF EXISTS public."shareholder_change" CASCADE;
CREATE TABLE public."shareholder_change" (
    "code" TEXT,
    "name" TEXT,
    "change_date" TEXT,
    "shareholder_name" TEXT,
    "change_amount" DOUBLE PRECISION,
    "change_price" DOUBLE PRECISION,
    "remaining_shares" DOUBLE PRECISION,
    "change_period" TEXT,
    "change_method" TEXT,
    PRIMARY KEY ("code", "change_date", "shareholder_name", "change_amount")
);

DROP TABLE IF EXISTS public."shareholder_data" CASCADE;
CREATE TABLE public."shareholder_data" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "report_date" TEXT NOT NULL,
    "total_shareholders" BIGINT,
    "change_pct" DOUBLE PRECISION,
    "avg_holdings" DOUBLE PRECISION,
    "top10_pct" DOUBLE PRECISION,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    "shareholder_count" BIGINT,
    "avg_market_value" DOUBLE PRECISION,
    "total_market_value" DOUBLE PRECISION,
    "total_shares" DOUBLE PRECISION,
    "change_count" BIGINT,
    "price_change_pct" DOUBLE PRECISION,
    "share_change" DOUBLE PRECISION,
    "share_change_reason" TEXT,
    "announcement_date" TEXT,
    "name" TEXT,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."stock_history" CASCADE;
CREATE TABLE public."stock_history" (
    "id" BIGINT,
    "timestamp" BIGINT NOT NULL,
    "price" DOUBLE PRECISION NOT NULL,
    "open" DOUBLE PRECISION,
    "high" DOUBLE PRECISION,
    "low" DOUBLE PRECISION,
    "volume" BIGINT,
    "amount" DOUBLE PRECISION,
    "chg" DOUBLE PRECISION,
    "chg_pct" DOUBLE PRECISION,
    "bid1_price" DOUBLE PRECISION,
    "bid1_vol" BIGINT,
    "ask1_price" DOUBLE PRECISION,
    "ask1_vol" BIGINT,
    "created_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."stock_industry" CASCADE;
CREATE TABLE public."stock_industry" (
    "id" BIGINT,
    "symbol" TEXT NOT NULL,
    "industry" TEXT,
    "industry_code" TEXT,
    "updated_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."stock_margin_detail" CASCADE;
CREATE TABLE public."stock_margin_detail" (
    "trade_date" TEXT,
    "symbol" TEXT,
    "name" TEXT,
    "margin_balance" DOUBLE PRECISION,
    "margin_buy" DOUBLE PRECISION,
    "margin_repay" DOUBLE PRECISION,
    "short_volume" DOUBLE PRECISION,
    "short_sell" DOUBLE PRECISION,
    "short_repay" DOUBLE PRECISION,
    PRIMARY KEY ("trade_date", "symbol")
);

DROP TABLE IF EXISTS public."stock_repurchase" CASCADE;
CREATE TABLE public."stock_repurchase" (
    "code" TEXT,
    "name" TEXT,
    "announce_date" TEXT,
    "repurchase_amount" DOUBLE PRECISION,
    "repurchase_price_high" DOUBLE PRECISION,
    "repurchase_price_low" DOUBLE PRECISION,
    "repurchase_ratio" DOUBLE PRECISION,
    "status" TEXT,
    "latest_price" DOUBLE PRECISION,
    "planned_amount_min" DOUBLE PRECISION,
    "planned_amount_max" DOUBLE PRECISION,
    "actual_amount" DOUBLE PRECISION,
    "actual_price_low" DOUBLE PRECISION,
    "actual_price_high" DOUBLE PRECISION,
    PRIMARY KEY ("code", "announce_date")
);

DROP TABLE IF EXISTS public."strategies" CASCADE;
CREATE TABLE public."strategies" (
    "id" TEXT,
    "name" TEXT,
    "enabled" BIGINT,
    "logic" TEXT,
    "conditions" TEXT,
    "actions" TEXT,
    "last_triggered" TEXT,
    "trigger_count" BIGINT DEFAULT 0,
    PRIMARY KEY ("id")
);

DROP TABLE IF EXISTS public."trade_calendar" CASCADE;
CREATE TABLE public."trade_calendar" (
    "trade_date" TEXT,
    "is_trade_day" BIGINT DEFAULT 1,
    PRIMARY KEY ("trade_date")
);

DROP TABLE IF EXISTS public."watchlist" CASCADE;
CREATE TABLE public."watchlist" (
    "symbol" TEXT,
    "name" TEXT,
    "added_at" TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY ("symbol")
);

CREATE INDEX IF NOT EXISTS "idx_alert_history_level_read" ON public."alert_history" (level, is_read);
CREATE INDEX IF NOT EXISTS "idx_alert_history_stock_ts" ON public."alert_history" (stock, timestamp);
CREATE INDEX IF NOT EXISTS "idx_alerts_level_read" ON public."alerts" (level, is_read);
CREATE INDEX IF NOT EXISTS "idx_alerts_timestamp" ON public."alerts" (timestamp);
CREATE INDEX IF NOT EXISTS "idx_alerts_ts" ON public."alerts" (timestamp);
CREATE INDEX IF NOT EXISTS "idx_kline_daily_date" ON public."kline_daily" (trade_date);
CREATE INDEX IF NOT EXISTS "idx_kline_daily_date_symbol_vol" ON public."kline_daily" (trade_date, symbol, volume);
CREATE INDEX IF NOT EXISTS "idx_kline_daily_rsi" ON public."kline_daily" (rsi14);
CREATE INDEX IF NOT EXISTS "idx_kline_daily_sym_date" ON public."kline_daily" (symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS "idx_kline_daily_symbol" ON public."kline_daily" (symbol);
CREATE INDEX IF NOT EXISTS "idx_kline_daily_symbol_date" ON public."kline_daily" (symbol, trade_date);
CREATE INDEX IF NOT EXISTS "idx_kline_monthly_sym_date" ON public."kline_monthly" (symbol, trade_month DESC);
CREATE INDEX IF NOT EXISTS "idx_kline_monthly_symbol" ON public."kline_monthly" (symbol);
CREATE INDEX IF NOT EXISTS "idx_kline_weekly_sym_date" ON public."kline_weekly" (symbol, trade_week DESC);
CREATE INDEX IF NOT EXISTS "idx_kline_weekly_symbol" ON public."kline_weekly" (symbol);
CREATE INDEX IF NOT EXISTS "idx_stock_history_timestamp" ON public."stock_history" (timestamp);
CREATE INDEX IF NOT EXISTS "idx_stock_history_ts" ON public."stock_history" (timestamp);