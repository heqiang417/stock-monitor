"""
Dashboard routes - 决策仪表盘API（三段式复盘+信号标准化+舆情+格式化）
"""
import logging
from flask import Blueprint, jsonify, request
from services.market_state import MarketStateAnalyzer
from services.signal_standardizer import SignalStandardizer
from services.dashboard_formatter import DashboardFormatter, Dashboard, DashboardItem
from services.news_sentiment import NewsSentimentService

logger = logging.getLogger(__name__)

DB_PATH = None
market_analyzer = None
signal_standardizer = None
news_service = None
formatter = None


def create_dashboard_routes(db_path: str):
    """Create dashboard blueprint."""
    global DB_PATH, market_analyzer, signal_standardizer, news_service, formatter

    DB_PATH = db_path
    market_analyzer = MarketStateAnalyzer(db_path)
    signal_standardizer = SignalStandardizer(db_path)
    news_service = NewsSentimentService()
    formatter = DashboardFormatter()

    bp = Blueprint('dashboard', __name__, url_prefix='/api/v1/dashboard')

    @bp.route('/state', methods=['GET'])
    def get_market_state():
        """获取市场状态"""
        date = request.args.get('date')
        state = market_analyzer.analyze(date)
        return jsonify({
            'regime': state.regime.value,
            'score': state.score,
            'position_hint': state.position_hint,
            'date': state.date,
            'signals': [{'name': s.name, 'value': s.value, 'detail': s.detail, 'score': s.score}
                        for s in state.signals]
        })

    @bp.route('/signal/<symbol>', methods=['GET'])
    def get_stock_signal(symbol):
        """获取单只股票信号"""
        regime = request.args.get('market_regime')
        price = request.args.get('price', type=float)
        sig = signal_standardizer.analyze_stock(symbol, price, regime)
        return jsonify(sig.to_dict())

    @bp.route('/signals', methods=['POST'])
    def get_batch_signals():
        """批量获取信号"""
        data = request.get_json()
        symbols = data.get('symbols', [])
        regime = data.get('market_regime')

        results = []
        for sym in symbols:
            sig = signal_standardizer.analyze_stock(sym, market_regime=regime)
            results.append(sig.to_dict())
        return jsonify(results)

    @bp.route('/news/<stock_name>', methods=['GET'])
    def get_stock_news(stock_name):
        """获取股票新闻"""
        code = request.args.get('code')
        result = news_service.should_skip_stock(stock_name, code)
        return jsonify(result)

    @bp.route('/market_sentiment', methods=['GET'])
    def get_market_sentiment():
        """获取市场整体舆情"""
        sentiment = news_service.get_market_sentiment()
        return jsonify(sentiment)

    @bp.route('/full', methods=['POST'])
    def get_full_dashboard():
        """
        获取完整决策仪表盘
        请求体: {"date": "2026-03-20", "stocks": [{"symbol": "sz002149", "name": "西部材料"}, ...]}
        """
        data = request.get_json()
        date = data.get('date')
        stocks = data.get('stocks', [])

        # 1. 市场状态
        state = market_analyzer.analyze(date)

        # 2. 逐只分析
        items = []
        for stock in stocks:
            sym = stock['symbol']
            name = stock.get('name', sym)

            # 信号
            sig = signal_standardizer.analyze_stock(sym, market_regime=state.regime.value)

            # 新闻（可选，慢）
            news_info = {'sentiment': None}
            if data.get('include_news'):
                news_info = news_service.should_skip_stock(name, sym)

            items.append(DashboardItem(
                symbol=sym,
                name=name,
                signal=sig.signal.value,
                trend=sig.trend.value,
                price=sig.buy_price or 0,
                buy_price=sig.buy_price,
                stop_loss=sig.stop_loss,
                target=sig.target_price,
                rsi=sig.rsi,
                reasons=sig.reasons or [],
                news_sentiment=news_info.get('news') and
                    next((n['sentiment'] for n in news_info['news'] if n.get('sentiment') != '中性'), None)
            ))

        # 3. 组装仪表盘
        dashboard = Dashboard(
            date=state.date,
            market_regime=state.regime.value,
            market_score=state.score,
            market_signals=[{'name': s.name, 'value': s.value, 'detail': s.detail}
                           for s in state.signals],
            items=items,
        )

        # 4. 返回文本 + 原始数据
        return jsonify({
            'text': formatter.format_text(dashboard),
            'data': {
                'date': dashboard.date,
                'market_regime': dashboard.market_regime,
                'market_score': dashboard.market_score,
                'market_signals': dashboard.market_signals,
                'items': [i.__dict__ for i in dashboard.items],
            }
        })

    @bp.route('/health', methods=['GET'])
    def health():
        return jsonify({'status': 'ok', 'modules': ['market_state', 'signal_standardizer', 'news_sentiment', 'dashboard_formatter']})

    return bp
