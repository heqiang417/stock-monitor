"""
新闻搜索与舆情过滤模块
支持多数据源：东方财富API + Tavily + EastMoney Web
"""
import os
import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    url: str
    snippet: str
    published: str
    sentiment: str  # "利好"/"利空"/"中性"
    relevance: float  # 0-1 相关度


class NewsSentimentService:
    """新闻搜索与舆情分析（多数据源）"""

    POSITIVE_WORDS = ['利好', '增长', '突破', '业绩', '涨停', '创新高', '收购', '合作',
                       '订单', '回购', '增持', '分红', '扭亏', '高增长', '超预期',
                       '业绩大增', '利润增长', '营收增长', '签单', '中标', '扩产']
    NEGATIVE_WORDS = ['利空', '下跌', '亏损', '减持', '暴雷', '违规', '处罚', '诉讼',
                       '退市', '暴跌', '减产', '裁员', '暴降', '巨亏', '立案',
                       '留置', '调查', '罚款', '监管', '风险警示', '问询函', 'ST']

    def __init__(self, tavily_keys: List[str] = None, max_age_days: int = 3):
        self.max_age_days = max_age_days
        self._init_tavily(tavily_keys)

    def _init_tavily(self, tavily_keys=None):
        """初始化 Tavily"""
        if tavily_keys:
            self.tavily_keys = tavily_keys
        else:
            env_key = os.getenv('TAVILY_API_KEY', '')
            if env_key:
                self.tavily_keys = [k.strip() for k in env_key.split(',') if k.strip()]
            else:
                env_path = os.path.expanduser('~/.openclaw/.env')
                self.tavily_keys = []
                if os.path.exists(env_path):
                    with open(env_path) as f:
                        for line in f:
                            if line.startswith('TAVILY_API_KEY'):
                                val = line.split('=', 1)[1].strip().strip('"').strip("'")
                                self.tavily_keys = [k.strip() for k in val.split(',') if k.strip()]
                                break
        self._key_index = 0
        logger.info(f"Tavily keys: {len(self.tavily_keys)}")

    def _get_next_key(self):
        if not self.tavily_keys:
            return None
        key = self.tavily_keys[self._key_index % len(self.tavily_keys)]
        self._key_index += 1
        return key

    # ========== 数据源 1: 东方财富新闻 API ==========
    def _search_eastmoney(self, stock_code: str, max_results: int = 5) -> List[NewsItem]:
        """通过东方财富 API 获取个股新闻（最快最准）"""
        if not stock_code:
            return []

        # 标准化代码 (sh600519 → 600519, sz002149 → 002149)
        code = re.sub(r'^(sh|sz|bj)', '', stock_code)

        try:
            import requests
            url = f"https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                'cb': '',
                'param': json.dumps({
                    'uid': '',
                    'keyword': code,
                    'type': ['cmsArticleWebOld'],
                    'client': 'web',
                    'clientType': 'web',
                    'clientVersion': 'curr',
                    'param': {
                        'cmsArticleWebOld': {
                            'searchScope': 'default',
                            'sort': 'default',
                            'pageIndex': 1,
                            'pageSize': max_results,
                            'preTag': '',
                            'postTag': ''
                        }
                    }
                })
            }
            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://so.eastmoney.com/'}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            text = resp.text.strip()
            if text.startswith('('):
                text = text[1:-1]
            data = json.loads(text)

            news = []
            for item in data.get('result', {}).get('cmsArticleWebOld', []):
                title = re.sub(r'<[^>]+>', '', item.get('title', ''))
                content = re.sub(r'<[^>]+>', '', item.get('content', ''))[:200]
                url = item.get('url', '')
                date_str = item.get('showTime', item.get('date', ''))

                sentiment = self._judge_sentiment(title + ' ' + content)
                news.append(NewsItem(
                    title=title, url=url, snippet=content,
                    published=date_str, sentiment=sentiment, relevance=0.9
                ))
            return news
        except Exception as e:
            logger.debug(f"东方财富API失败: {e}")
            return []

    # ========== 数据源 2: Tavily ==========
    def _search_tavily(self, query: str, max_results: int = 5) -> List[NewsItem]:
        """Tavily 英文搜索"""
        try:
            from tavily import TavilyClient
        except ImportError:
            return []

        key = self._get_next_key()
        if not key:
            return []

        try:
            client = TavilyClient(api_key=key)
            response = client.search(
                query=query, max_results=max_results,
                search_depth="basic", include_answer=False, topic="news"
            )
            news = []
            cutoff = datetime.now() - timedelta(days=self.max_age_days)
            for r in response.get('results', []):
                published = r.get('published_date', '')
                if published:
                    try:
                        pub = datetime.fromisoformat(published.replace('Z', '+00:00'))
                        if pub < cutoff:
                            continue
                    except:
                        pass
                title = r.get('title', '')
                snippet = r.get('content', '')[:200]
                sentiment = self._judge_sentiment(title + ' ' + snippet)
                news.append(NewsItem(
                    title=title, url=r.get('url', ''), snippet=snippet,
                    published=published, sentiment=sentiment, relevance=0.7
                ))
            return news
        except Exception as e:
            logger.debug(f"Tavily搜索失败: {e}")
            return []

    # ========== 统一搜索接口 ==========
    def search_stock_news(self, stock_name: str, stock_code: str = None,
                          max_results: int = 5) -> List[NewsItem]:
        """
        搜索股票新闻（多源聚合）
        优先级: 东方财富 > Tavily
        """
        all_news = []

        # 1. 东方财富（中文，最准）
        if stock_code:
            em_news = self._search_eastmoney(stock_code, max_results)
            all_news.extend(em_news)
            logger.debug(f"东方财富: {len(em_news)} 条")

        # 2. Tavily（补充）
        if len(all_news) < max_results:
            query = f"{stock_name} {stock_code or ''} A股".strip()
            tv_news = self._search_tavily(query, max_results - len(all_news))
            all_news.extend(tv_news)
            logger.debug(f"Tavily: {len(tv_news)} 条")

        return all_news[:max_results]

    # ========== 情感判断 ==========
    def _judge_sentiment(self, text: str) -> str:
        pos = sum(1 for w in self.POSITIVE_WORDS if w in text)
        neg = sum(1 for w in self.NEGATIVE_WORDS if w in text)
        if pos > neg:
            return "利好"
        elif neg > pos:
            return "利空"
        return "中性"

    # ========== 业务接口 ==========
    def should_skip_stock(self, stock_name: str, stock_code: str = None) -> Dict:
        """判断是否应该跳过某只股票（利空过滤）"""
        news = self.search_stock_news(stock_name, stock_code, max_results=3)
        if not news:
            return {"skip": False, "reason": "无新闻", "news": []}
        neg_news = [n for n in news if n.sentiment == "利空"]
        if len(neg_news) >= 2:
            return {
                "skip": True,
                "reason": f"利空{len(neg_news)}条: {'; '.join(n.title[:30] for n in neg_news[:2])}",
                "news": [n.__dict__ for n in news]
            }
        return {"skip": False, "reason": "无明显利空", "news": [n.__dict__ for n in news]}

    def get_market_sentiment(self) -> Dict:
        """获取整体市场舆情"""
        # 用东方财富大盘新闻
        news = self._search_eastmoney('上证指数', 10)
        if not news:
            news = self._search_tavily("A股 大盘 行情分析", 10)
        if not news:
            return {"sentiment": "未知", "details": []}

        pos = sum(1 for n in news if n.sentiment == "利好")
        neg = sum(1 for n in news if n.sentiment == "利空")
        if pos > neg * 2:
            sentiment = "偏多"
        elif neg > pos * 2:
            sentiment = "偏空"
        else:
            sentiment = "中性"

        return {
            "sentiment": sentiment,
            "positive": pos, "negative": neg,
            "neutral": len(news) - pos - neg,
            "details": [{"title": n.title, "sentiment": n.sentiment} for n in news[:5]]
        }
