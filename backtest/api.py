"""
回测API端点
提供回测、策略评估、风险分析的REST API
"""
from flask import Blueprint, request, jsonify
from backtest.engine import (
    BacktestEngine, ClassicStrategies, RiskMetrics, 
    generate_report, BacktestResult
)
import os
import json
import copy
import time
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('backtest', __name__)

# Use the project root data directory for the database
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_project_root, 'data', 'stock_data.db')
STRATEGIES_FILE = os.path.join(_project_root, 'strategies.json')
engine = BacktestEngine(DB_PATH)

# 策略映射
STRATEGY_MAP = {
    'ma_cross': ('MA均线交叉', ClassicStrategies.ma_cross),
    'rsi_mean_reversion': ('RSI均值回归', ClassicStrategies.rsi_mean_reversion),
    'macd_crossover': ('MACD交叉', ClassicStrategies.macd_crossover),
    'bollinger_bounce': ('布林带反弹', ClassicStrategies.bollinger_bounce),
    'volume_breakout': ('成交量突破', ClassicStrategies.volume_breakout),
    'dual_ma_trend': ('双均线趋势', ClassicStrategies.dual_ma_trend),
    'golden_cross': ('黄金交叉', ClassicStrategies.golden_cross),
}

# ==================== 策略模板库 ====================
STRATEGY_TEMPLATES = {
    "dual_ma_fast": {
        "id": "dual_ma_fast",
        "name": "双均线快线策略",
        "description": "经典双均线交叉：MA5/MA20，灵敏度高，适合短线交易",
        "category": "趋势跟踪",
        "icon": "📈",
        "strategy_id": "ma_cross",
        "default_params": {"fast": 5, "slow": 20},
        "conditions": [
            {"type": "ma_cross", "fast": 5, "slow": 20, "operator": "cross_up", "action": "BUY"},
            {"type": "ma_cross", "fast": 5, "slow": 20, "operator": "cross_down", "action": "SELL"}
        ],
        "risk_level": "中",
        "recommended_period": "1-3个月",
        "tags": ["均线", "短线", "经典"]
    },
    "dual_ma_slow": {
        "id": "dual_ma_slow",
        "name": "双均线慢线策略",
        "description": "双均线MA10/MA60，过滤噪音，适合中线趋势跟踪",
        "category": "趋势跟踪",
        "icon": "📊",
        "strategy_id": "dual_ma_trend",
        "default_params": {"short": 10, "long": 60},
        "conditions": [
            {"type": "ma_cross", "fast": 10, "slow": 60, "operator": "cross_up", "action": "BUY"},
            {"type": "ma_cross", "fast": 10, "slow": 60, "operator": "cross_down", "action": "SELL"}
        ],
        "risk_level": "中低",
        "recommended_period": "3-6个月",
        "tags": ["均线", "中线", "趋势"]
    },
    "golden_cross": {
        "id": "golden_cross",
        "name": "黄金交叉策略",
        "description": "MA50/MA200经典金叉，长期趋势确认信号",
        "category": "趋势跟踪",
        "icon": "✨",
        "strategy_id": "golden_cross",
        "default_params": {},
        "conditions": [
            {"type": "ma_cross", "fast": 50, "slow": 200, "operator": "cross_up", "action": "BUY"},
            {"type": "ma_cross", "fast": 50, "slow": 200, "operator": "cross_down", "action": "SELL"}
        ],
        "risk_level": "低",
        "recommended_period": "6-12个月",
        "tags": ["均线", "长线", "经典", "金叉"]
    },
    "rsi_oversold": {
        "id": "rsi_oversold",
        "name": "RSI超买超卖策略",
        "description": "RSI<30买入（超卖），RSI>70卖出（超买），经典均值回归",
        "category": "均值回归",
        "icon": "🔄",
        "strategy_id": "rsi_mean_reversion",
        "default_params": {"oversold": 30, "overbought": 70},
        "conditions": [
            {"type": "rsi", "threshold": 30, "operator": "<=", "action": "BUY"},
            {"type": "rsi", "threshold": 70, "operator": ">=", "action": "SELL"}
        ],
        "risk_level": "中",
        "recommended_period": "2-4周",
        "tags": ["RSI", "超买超卖", "反转"]
    },
    "rsi_aggressive": {
        "id": "rsi_aggressive",
        "name": "RSI激进策略",
        "description": "RSI<20买入，RSI>80卖出，捕捉极端反转机会",
        "category": "均值回归",
        "icon": "⚡",
        "strategy_id": "rsi_mean_reversion",
        "default_params": {"oversold": 20, "overbought": 80},
        "conditions": [
            {"type": "rsi", "threshold": 20, "operator": "<=", "action": "BUY"},
            {"type": "rsi", "threshold": 80, "operator": ">=", "action": "SELL"}
        ],
        "risk_level": "高",
        "recommended_period": "1-2周",
        "tags": ["RSI", "激进", "反转"]
    },
    "macd_signal": {
        "id": "macd_signal",
        "name": "MACD信号策略",
        "description": "MACD金叉买入、死叉卖出，趋势动量经典策略",
        "category": "动量",
        "icon": "📉",
        "strategy_id": "macd_crossover",
        "default_params": {},
        "conditions": [
            {"type": "macd", "operator": "cross_up", "action": "BUY"},
            {"type": "macd", "operator": "cross_down", "action": "SELL"}
        ],
        "risk_level": "中",
        "recommended_period": "1-3个月",
        "tags": ["MACD", "动量", "趋势"]
    },
    "macd_histogram": {
        "id": "macd_histogram",
        "name": "MACD柱状图策略",
        "description": "MACD柱状图由负转正买入，由正转负卖出",
        "category": "动量",
        "icon": "📊",
        "strategy_id": "macd_crossover",
        "default_params": {},
        "conditions": [
            {"type": "macd_histogram", "operator": "cross_zero_up", "action": "BUY"},
            {"type": "macd_histogram", "operator": "cross_zero_down", "action": "SELL"}
        ],
        "risk_level": "中",
        "recommended_period": "2-4周",
        "tags": ["MACD", "柱状图", "动量"]
    },
    "bollinger_breakout": {
        "id": "bollinger_breakout",
        "name": "布林带突破策略",
        "description": "价格触及下轨买入（反弹），触及上轨卖出（回归）",
        "category": "波动率",
        "icon": "🎯",
        "strategy_id": "bollinger_bounce",
        "default_params": {"period": 20, "std": 2.0},
        "conditions": [
            {"type": "bollinger", "operator": "touch_lower", "action": "BUY"},
            {"type": "bollinger", "operator": "touch_upper", "action": "SELL"}
        ],
        "risk_level": "中",
        "recommended_period": "2-6周",
        "tags": ["布林带", "波动率", "突破"]
    },
    "bollinger_squeeze": {
        "id": "bollinger_squeeze",
        "name": "布林带收窄策略",
        "description": "布林带收窄时预示大行情，配合成交量突破",
        "category": "波动率",
        "icon": "🎯",
        "strategy_id": "bollinger_bounce",
        "default_params": {"period": 20, "std": 1.5},
        "conditions": [
            {"type": "bollinger_width", "operator": "<", "threshold": 0.05, "action": "WATCH"},
            {"type": "volume_surge", "operator": ">=", "threshold": 2.0, "action": "BUY"}
        ],
        "risk_level": "高",
        "recommended_period": "1-2周",
        "tags": ["布林带", "收窄", "波动率"]
    },
    "volume_breakout_trend": {
        "id": "volume_breakout_trend",
        "name": "成交量突破趋势策略",
        "description": "放量突破时顺势跟随，成交量放大2倍以上确认",
        "category": "成交量",
        "icon": "📊",
        "strategy_id": "volume_breakout",
        "default_params": {"mult": 2.0},
        "conditions": [
            {"type": "volume_surge", "operator": ">=", "threshold": 2.0, "price_change": ">0", "action": "BUY"},
            {"type": "volume_surge", "operator": ">=", "threshold": 2.0, "price_change": "<0", "action": "SELL"}
        ],
        "risk_level": "中高",
        "recommended_period": "1-2周",
        "tags": ["成交量", "突破", "趋势"]
    },
    "triple_ema": {
        "id": "triple_ema",
        "name": "三重EMA策略",
        "description": "EMA8/EMA21/EMA55三线排列，确认趋势强度",
        "category": "趋势跟踪",
        "icon": "📈",
        "strategy_id": "ma_cross",
        "default_params": {"fast": 8, "slow": 21},
        "conditions": [
            {"type": "triple_ema", "ema_fast": 8, "ema_mid": 21, "ema_slow": 55, "operator": "aligned_up", "action": "BUY"},
            {"type": "triple_ema", "ema_fast": 8, "ema_mid": 21, "ema_slow": 55, "operator": "aligned_down", "action": "SELL"}
        ],
        "risk_level": "中",
        "recommended_period": "2-4周",
        "tags": ["EMA", "三线", "趋势"]
    },
    "momentum_breakout": {
        "id": "momentum_breakout",
        "name": "动量突破策略",
        "description": "价格突破N日新高买入，跌破N日新低卖出",
        "category": "动量",
        "icon": "🚀",
        "strategy_id": "volume_breakout",
        "default_params": {"mult": 1.5},
        "conditions": [
            {"type": "price_breakout", "period": 20, "operator": "new_high", "action": "BUY"},
            {"type": "price_breakout", "period": 20, "operator": "new_low", "action": "SELL"}
        ],
        "risk_level": "中高",
        "recommended_period": "1-4周",
        "tags": ["动量", "突破", "新高新低"]
    }
}


@bp.route('/api/backtest/run', methods=['POST'])
def run_backtest():
    """运行回测"""
    try:
        data = request.json
        symbol = data.get('symbol', '002149')
        strategy_id = data.get('strategy', 'ma_cross')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        initial_capital = data.get('initial_capital', 100000)
        
        # 策略参数
        params = data.get('params', {})
        
        if strategy_id not in STRATEGY_MAP:
            return jsonify({"error": f"未知策略: {strategy_id}"}), 400
        
        strategy_name, strategy_func = STRATEGY_MAP[strategy_id]
        
        result = engine.run_backtest(
            symbol=symbol,
            strategy_func=strategy_func,
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            **params
        )
        
        # 生成报告
        report = generate_report(result)
        
        # Convert Signal enum values to strings for JSON serialization
        trades_json = []
        for t in result.trades[-20:]:
            t_copy = dict(t)
            trades_json.append(t_copy)
        
        equity_json = []
        for e in result.equity_curve[-100:]:
            e_copy = dict(e)
            equity_json.append(e_copy)
        
        return jsonify({
            "success": True,
            "result": {
                "strategy_name": result.strategy_name,
                "symbol": result.symbol,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "initial_capital": result.initial_capital,
                "final_capital": result.final_capital,
                "total_return": result.total_return,
                "total_return_pct": result.total_return_pct,
                "annual_return": result.annual_return,
                "max_drawdown": result.max_drawdown,
                "max_drawdown_pct": result.max_drawdown_pct,
                "sharpe_ratio": result.sharpe_ratio,
                "sortino_ratio": result.sortino_ratio,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "total_trades": result.total_trades,
                "winning_trades": result.winning_trades,
                "losing_trades": result.losing_trades,
                "avg_win": result.avg_win,
                "avg_loss": result.avg_loss,
                "largest_win": result.largest_win,
                "largest_loss": result.largest_loss,
                "avg_hold_days": result.avg_hold_days,
            },
            "trades": trades_json,
            "equity_curve": equity_json,
            "report": report
        })
        
    except Exception as e:
        logger.error(f"Backtest error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/api/backtest/strategies', methods=['GET'])
def list_strategies():
    """获取所有可用策略列表"""
    strategies = []
    for sid, (name, _) in STRATEGY_MAP.items():
        strategies.append({
            "id": sid,
            "name": name,
            "description": get_strategy_description(sid)
        })
    return jsonify({"strategies": strategies})


def get_strategy_description(strategy_id: str) -> str:
    """获取策略描述"""
    descriptions = {
        'ma_cross': '短期均线上穿长期均线买入，下穿卖出',
        'rsi_mean_reversion': 'RSI超卖买入，超买卖出',
        'macd_crossover': 'MACD金叉买入，死叉卖出',
        'bollinger_bounce': '价格触及布林带下轨买入，上轨卖出',
        'volume_breakout': '成交量突破放大时跟随趋势',
        'dual_ma_trend': '双均线趋势跟踪策略',
        'golden_cross': '长期均线金叉策略（经典）',
    }
    return descriptions.get(strategy_id, '')


@bp.route('/api/backtest/compare', methods=['POST'])
def compare_strategies():
    """对比多个策略"""
    try:
        data = request.json
        symbol = data.get('symbol', '002149')
        strategy_ids = data.get('strategies', ['ma_cross', 'rsi_mean_reversion'])
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        initial_capital = data.get('initial_capital', 100000)
        
        results = []
        for sid in strategy_ids:
            if sid not in STRATEGY_MAP:
                continue
            
            name, func = STRATEGY_MAP[sid]
            try:
                result = engine.run_backtest(
                    symbol=symbol,
                    strategy_func=func,
                    strategy_name=name,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=initial_capital
                )
                results.append({
                    "strategy_id": sid,
                    "strategy_name": name,
                    "total_return_pct": result.total_return_pct,
                    "annual_return": result.annual_return,
                    "max_drawdown_pct": result.max_drawdown_pct,
                    "sharpe_ratio": result.sharpe_ratio,
                    "win_rate": result.win_rate,
                    "total_trades": result.total_trades,
                })
            except Exception as e:
                results.append({
                    "strategy_id": sid,
                    "strategy_name": name,
                    "error": str(e)
                })
        
        # 排序：按Sharpe比率降序
        results.sort(key=lambda x: x.get('sharpe_ratio', -999), reverse=True)
        
        return jsonify({
            "symbol": symbol,
            "period": f"{start_date} 至 {end_date}",
            "results": results,
            "best_strategy": results[0] if results else None
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/api/backtest/risk', methods=['POST'])
def calculate_risk():
    """计算风险指标"""
    try:
        data = request.json
        symbol = data.get('symbol', '002149')
        
        # 获取历史数据
        kline_data = engine.get_kline_data(symbol)
        if not kline_data:
            return jsonify({"error": "无数据"}), 404
        
        # 计算日收益率
        returns = []
        for i in range(1, len(kline_data)):
            prev = kline_data[i-1]['close']
            curr = kline_data[i]['close']
            if prev > 0:
                returns.append((curr - prev) / prev)
        
        # 计算各项风险指标
        var_95 = RiskMetrics.calculate_var(returns, 0.95)
        var_99 = RiskMetrics.calculate_var(returns, 0.99)
        cvar_95 = RiskMetrics.calculate_cvar(returns, 0.95)
        volatility = RiskMetrics.calculate_volatility(returns)
        
        return jsonify({
            "symbol": symbol,
            "data_points": len(kline_data),
            "risk_metrics": {
                "var_95": var_95,
                "var_99": var_99,
                "cvar_95": cvar_95,
                "annualized_volatility": volatility,
                "daily_volatility": RiskMetrics.calculate_volatility(returns, annualize=False),
            },
            "statistics": {
                "mean_return": sum(returns) / len(returns) if returns else 0,
                "max_return": max(returns) if returns else 0,
                "min_return": min(returns) if returns else 0,
                "positive_days": sum(1 for r in returns if r > 0),
                "negative_days": sum(1 for r in returns if r < 0),
            }
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/api/backtest/scan_all', methods=['POST'])
def scan_all_strategies():
    """扫描所有股票对所有策略的回测结果"""
    try:
        data = request.json
        strategy_id = data.get('strategy', 'ma_cross')
        watchlist_only = data.get('watchlist_only', False)
        
        # 获取股票列表
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA synchronous=NORMAL')
        cursor = conn.cursor()
        
        if watchlist_only:
            cursor.execute("SELECT symbol, name FROM watchlist")
        else:
            # 获取有K线数据的股票
            cursor.execute("SELECT DISTINCT symbol FROM kline_daily")
        
        stocks = cursor.fetchall()
        conn.close()
        
        if strategy_id not in STRATEGY_MAP:
            return jsonify({"error": f"未知策略: {strategy_id}"}), 400
        
        strategy_name, strategy_func = STRATEGY_MAP[strategy_id]
        
        results = []
        for stock in stocks:
            symbol = stock[0]
            try:
                result = engine.run_backtest(
                    symbol=symbol,
                    strategy_func=strategy_func,
                    strategy_name=strategy_name,
                    initial_capital=100000
                )
                results.append({
                    "symbol": symbol,
                    "name": stock[1] if len(stock) > 1 else "",
                    "total_return_pct": round(result.total_return_pct, 2),
                    "sharpe_ratio": round(result.sharpe_ratio, 2),
                    "win_rate": round(result.win_rate, 1),
                    "total_trades": result.total_trades,
                    "max_drawdown_pct": round(result.max_drawdown_pct, 2),
                })
            except Exception:
                continue
        
        # 按收益排序
        results.sort(key=lambda x: x['total_return_pct'], reverse=True)
        
        return jsonify({
            "strategy": strategy_name,
            "total_scanned": len(stocks),
            "successful": len(results),
            "top_performers": results[:20],
            "worst_performers": results[-5:] if len(results) >= 5 else results
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/api/backtest/report/<symbol>/<strategy>', methods=['GET'])
def get_report(symbol, strategy):
    """获取格式化报告"""
    try:
        if strategy not in STRATEGY_MAP:
            return jsonify({"error": f"未知策略: {strategy}"}), 400
        
        strategy_name, strategy_func = STRATEGY_MAP[strategy]
        
        result = engine.run_backtest(
            symbol=symbol,
            strategy_func=strategy_func,
            initial_capital=100000
        )
        
        report = generate_report(result)
        
        return jsonify({
            "symbol": symbol,
            "strategy": strategy_name,
            "report": report
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ==================== 策略模板 API ====================

@bp.route('/api/backtest/templates', methods=['GET'])
def list_templates():
    """获取所有策略模板列表"""
    try:
        category = request.args.get('category')
        tags = request.args.getlist('tag')
        
        templates = []
        for tid, tpl in STRATEGY_TEMPLATES.items():
            # 按分类过滤
            if category and tpl.get('category') != category:
                continue
            # 按标签过滤
            if tags and not any(t in tpl.get('tags', []) for t in tags):
                continue
            
            templates.append({
                "id": tpl["id"],
                "name": tpl["name"],
                "description": tpl["description"],
                "category": tpl["category"],
                "icon": tpl.get("icon", "📊"),
                "strategy_id": tpl["strategy_id"],
                "risk_level": tpl.get("risk_level", "中"),
                "recommended_period": tpl.get("recommended_period", ""),
                "tags": tpl.get("tags", []),
                "default_params": tpl.get("default_params", {}),
                "conditions": tpl.get("conditions", []),
                "logic": tpl.get("logic", "AND")
            })
        
        # 按分类排序
        category_order = {"趋势跟踪": 1, "均值回归": 2, "动量": 3, "波动率": 4, "成交量": 5}
        templates.sort(key=lambda x: (category_order.get(x["category"], 99), x["name"]))
        
        return jsonify({
            "success": True,
            "total": len(templates),
            "categories": list(set(t["category"] for t in STRATEGY_TEMPLATES.values())),
            "templates": templates
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/api/backtest/template/<template_id>', methods=['GET'])
def get_template(template_id):
    """获取单个模板详情"""
    try:
        if template_id not in STRATEGY_TEMPLATES:
            return jsonify({"error": f"模板不存在: {template_id}"}), 404
        
        tpl = STRATEGY_TEMPLATES[template_id]
        return jsonify({
            "success": True,
            "template": tpl
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/api/backtest/apply_template', methods=['POST'])
def apply_template():
    """应用模板创建策略"""
    try:
        data = request.json
        template_id = data.get('template_id')
        custom_name = data.get('name')
        custom_params = data.get('params', {})
        enabled = data.get('enabled', True)
        
        if not template_id:
            return jsonify({"error": "缺少 template_id 参数"}), 400
        
        if template_id not in STRATEGY_TEMPLATES:
            return jsonify({"error": f"模板不存在: {template_id}"}), 404
        
        tpl = STRATEGY_TEMPLATES[template_id]
        
        # 合并默认参数和自定义参数
        params = {**tpl.get('default_params', {}), **custom_params}
        
        # 生成策略ID
        strategy_id = f"tpl_{template_id}_{int(time.time())}"
        
        # 构建策略对象
        new_strategy = {
            "id": strategy_id,
            "name": custom_name or tpl["name"],
            "enabled": enabled,
            "logic": "AND",
            "conditions": [],
            "actions": [
                {"type": "notify_feishu", "message": f"🔔 策略触发: {custom_name or tpl['name']}"},
                {"type": "alert_web", "level": "high"}
            ],
            "template_id": template_id,
            "template_name": tpl["name"],
            "params": params,
            "lastTriggered": None,
            "triggerCount": 0
        }
        
        # 将模板条件转换为监控条件格式
        for cond in tpl.get("conditions", []):
            if cond["type"] == "ma_cross":
                # 双均线条件 - 转换为价格条件
                new_strategy["conditions"].append({
                    "type": "ma_cross_signal",
                    "operator": cond.get("operator", "cross_up"),
                    "value": 1,
                    "fast": cond.get("fast", params.get("fast", 5)),
                    "slow": cond.get("slow", params.get("slow", 20))
                })
            elif cond["type"] == "rsi":
                new_strategy["conditions"].append({
                    "type": "rsi",
                    "operator": cond.get("operator", "<="),
                    "value": cond.get("threshold", 30)
                })
            elif cond["type"] == "macd":
                new_strategy["conditions"].append({
                    "type": "macd_signal",
                    "operator": cond.get("operator", "cross_up"),
                    "value": 1
                })
            elif cond["type"] == "bollinger":
                new_strategy["conditions"].append({
                    "type": "bollinger_touch",
                    "operator": cond.get("operator", "touch_lower"),
                    "period": params.get("period", 20),
                    "std": params.get("std", 2.0)
                })
            elif cond["type"] == "volume_surge":
                new_strategy["conditions"].append({
                    "type": "volume_surge",
                    "operator": cond.get("operator", ">="),
                    "value": cond.get("threshold", 2.0)
                })
            elif cond["type"] == "price_breakout":
                new_strategy["conditions"].append({
                    "type": "price",
                    "operator": cond.get("operator", "new_high"),
                    "value": cond.get("period", 20)
                })
            elif cond["type"] == "triple_ema":
                new_strategy["conditions"].append({
                    "type": "ema_align",
                    "operator": cond.get("operator", "aligned_up"),
                    "ema_fast": cond.get("ema_fast", 8),
                    "ema_mid": cond.get("ema_mid", 21),
                    "ema_slow": cond.get("ema_slow", 55)
                })
            elif cond["type"] == "macd_histogram":
                new_strategy["conditions"].append({
                    "type": "macd_histogram",
                    "operator": cond.get("operator", "cross_zero_up"),
                    "value": 0
                })
            elif cond["type"] == "bollinger_width":
                new_strategy["conditions"].append({
                    "type": "bollinger_width",
                    "operator": cond.get("operator", "<"),
                    "value": cond.get("threshold", 0.05)
                })
        
        # 读取现有策略并添加新策略
        try:
            with open(STRATEGIES_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {"strategies": [], "templates": [], "categories": [], "lastUpdated": ""}
        
        # Handle both list and dict formats
        if isinstance(existing, list):
            existing = {"strategies": existing, "templates": [], "categories": [], "lastUpdated": ""}
        if "strategies" not in existing:
            existing["strategies"] = []
        
        existing["strategies"].append(new_strategy)
        existing["lastUpdated"] = time.strftime("%Y-%m-%d")
        
        with open(STRATEGIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            "success": True,
            "message": f"已应用模板「{tpl['name']}」，创建策略「{new_strategy['name']}」",
            "strategy": new_strategy,
            "template": {
                "id": tpl["id"],
                "name": tpl["name"],
                "strategy_id": tpl["strategy_id"]
            }
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@bp.route('/api/backtest/template/preview', methods=['POST'])
def preview_template():
    """预览模板应用效果（不实际创建策略）"""
    try:
        data = request.json
        template_id = data.get('template_id')
        custom_params = data.get('params', {})
        
        if not template_id:
            return jsonify({"error": "缺少 template_id 参数"}), 400
        
        if template_id not in STRATEGY_TEMPLATES:
            return jsonify({"error": f"模板不存在: {template_id}"}), 404
        
        tpl = STRATEGY_TEMPLATES[template_id]
        params = {**tpl.get('default_params', {}), **custom_params}
        
        # 构建预览策略
        preview_strategy = {
            "template_id": template_id,
            "name": tpl["name"],
            "description": tpl["description"],
            "strategy_id": tpl["strategy_id"],
            "params": params,
            "conditions_count": len(tpl.get("conditions", [])),
            "risk_level": tpl.get("risk_level", "中"),
            "recommended_period": tpl.get("recommended_period", ""),
            "tags": tpl.get("tags", [])
        }
        
        return jsonify({
            "success": True,
            "preview": preview_strategy
        })
        
    except Exception as e:
        logger.error(f"Backtest API error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500
