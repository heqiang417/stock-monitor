"""
决策仪表盘格式化模块（借鉴 daily_stock_analysis 的推送格式）
将分析结果格式化为清晰的决策仪表盘，支持飞书推送
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class DashboardItem:
    """仪表盘单条"""
    symbol: str
    name: str
    signal: str  # 强烈买入/买入/观望/卖出
    trend: str
    price: float
    buy_price: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    rsi: Optional[float]
    reasons: List[str]
    news_sentiment: Optional[str] = None  # 利好/利空/中性


@dataclass
class Dashboard:
    """完整仪表盘"""
    date: str
    market_regime: str  # 进攻/均衡/防守
    market_score: float
    market_signals: List[Dict]
    items: List[DashboardItem]
    news_summary: Optional[str] = None


class DashboardFormatter:
    """仪表盘格式化器"""

    def format_text(self, dashboard: Dashboard) -> str:
        """格式化为纯文本（适合飞书 webhook）"""
        lines = []

        # 头部
        regime_icon = {"进攻": "🟢", "均衡": "🟡", "防守": "🔴"}.get(dashboard.market_regime, "⚪")
        lines.append(f"{'='*40}")
        lines.append(f"📊 每日决策仪表盘 | {dashboard.date}")
        lines.append(f"{'='*40}")
        lines.append(f"")
        lines.append(f"{regime_icon} 市场状态：{dashboard.market_regime}（评分 {dashboard.market_score:+.2f}）")

        # 市场信号
        if dashboard.market_signals:
            lines.append(f"")
            lines.append(f"── 市场信号 ──")
            for s in dashboard.market_signals:
                icon = {"看多": "🟢", "中性": "⚪", "看空": "🔴"}.get(s.get('value', ''), "⚪")
                lines.append(f"  {icon} {s['name']}：{s['value']} — {s.get('detail', '')}")

        # 新闻摘要
        if dashboard.news_summary:
            lines.append(f"")
            lines.append(f"📰 新闻摘要：{dashboard.news_summary}")

        # 个股信号
        lines.append(f"")
        lines.append(f"{'='*40}")
        lines.append(f"📋 个股信号")
        lines.append(f"{'='*40}")

        if not dashboard.items:
            lines.append("  今日无信号")
        else:
            # 按信号分组
            groups = {"强烈买入": [], "买入": [], "观望": [], "卖出": [], "强烈卖出": []}
            for item in dashboard.items:
                groups.setdefault(item.signal, []).append(item)

            # 买入信号优先展示
            for sig in ["强烈买入", "买入"]:
                for item in groups.get(sig, []):
                    icon = "🟢🟢" if sig == "强烈买入" else "🟢"
                    lines.append(f"")
                    lines.append(f"{icon} {item.name}（{item.symbol}）→ {sig}")
                    lines.append(f"  趋势：{item.trend} | 当前价：{item.price:.2f}")

                    if item.buy_price:
                        parts = [f"买入 {item.buy_price:.2f}"]
                        if item.stop_loss:
                            parts.append(f"止损 {item.stop_loss:.2f}")
                        if item.target:
                            parts.append(f"目标 {item.target:.2f}")
                        lines.append(f"  📍 {' | '.join(parts)}")

                    if item.rsi:
                        lines.append(f"  RSI：{item.rsi:.1f}")

                    if item.news_sentiment:
                        news_icon = {"利好": "📈", "利空": "📉", "中性": "➖"}.get(item.news_sentiment, "")
                        lines.append(f"  舆情：{news_icon} {item.news_sentiment}")

                    for r in item.reasons[:3]:
                        lines.append(f"  • {r}")

            # 观望/卖出
            wait_sell = groups.get("观望", []) + groups.get("卖出", []) + groups.get("强烈卖出", [])
            if wait_sell:
                lines.append(f"")
                lines.append(f"── 观望/卖出 ──")
                for item in wait_sell:
                    icon = {"观望": "🟡", "卖出": "🔴", "强烈卖出": "🔴🔴"}.get(item.signal, "")
                    lines.append(f"  {icon} {item.name}（{item.symbol}）→ {item.signal} | {', '.join(item.reasons[:2])}")

        # 检查清单
        lines.append(f"")
        lines.append(f"{'='*40}")
        lines.append(f"✅ 操作检查清单")
        lines.append(f"{'='*40}")

        buy_items = [i for i in dashboard.items if i.signal in ("强烈买入", "买入")]
        if buy_items:
            lines.append(f"  □ 是否已完成仓位规划？（市场状态：{dashboard.market_regime}）")
            for item in buy_items:
                lines.append(f"  □ {item.name}：买入价 {item.buy_price:.2f}，止损 {item.stop_loss:.2f}")
            lines.append(f"  □ 单只仓位不超过总资金20%")
            lines.append(f"  □ 设置条件单（止盈止损）")
        else:
            lines.append(f"  □ 今日无买入信号，保持观望")
            lines.append(f"  □ 检查持仓是否有需要止损的")

        lines.append(f"")
        lines.append(f"⚠️ 仅供参考，不构成投资建议")

        return "\n".join(lines)

    def format_feishu_card(self, dashboard: Dashboard) -> Dict:
        """格式化为飞书交互卡片"""
        regime_color = {"进攻": "green", "均衡": "orange", "防守": "red"}.get(dashboard.market_regime, "grey")

        elements = []

        # 市场状态
        elements.append({
            "tag": "markdown",
            "content": f"**市场状态：{dashboard.market_regime}**（评分 {dashboard.market_score:+.2f}）"
        })

        # 市场信号
        if dashboard.market_signals:
            sig_text = ""
            for s in dashboard.market_signals:
                icon = {"看多": "🟢", "中性": "⚪", "看空": "🔴"}.get(s.get('value', ''), "⚪")
                sig_text += f"{icon} {s['name']}：{s.get('detail', '')}\n"
            elements.append({"tag": "markdown", "content": sig_text})

        elements.append({"tag": "hr"})

        # 个股
        buy_items = [i for i in dashboard.items if i.signal in ("强烈买入", "买入")]
        for item in buy_items:
            icon = "🟢🟢" if item.signal == "强烈买入" else "🟢"
            content = f"**{icon} {item.name}（{item.symbol}）→ {item.signal}**\n"
            content += f"趋势：{item.trend} | 当前价：{item.price:.2f}\n"
            if item.buy_price:
                content += f"📍 买入 {item.buy_price:.2f} | 止损 {item.stop_loss:.2f} | 目标 {item.target:.2f}\n"
            if item.rsi:
                content += f"RSI：{item.rsi:.1f}\n"
            for r in item.reasons[:2]:
                content += f"• {r}\n"
            elements.append({"tag": "markdown", "content": content})

        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": "⚠️ 仅供参考，不构成投资建议"})

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"📊 决策仪表盘 | {dashboard.date}"},
                    "template": regime_color,
                },
                "elements": elements
            }
        }
