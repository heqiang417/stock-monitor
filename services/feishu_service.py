"""
飞书通知服务
发送飞书消息到指定用户/群组
"""
import logging
import requests
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class FeishuService:
    """飞书消息发送服务"""
    
    def __init__(self, app_id=None, app_secret=None, default_chat_id=None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.default_chat_id = default_chat_id
        self.access_token = None
        self.token_expires = 0
    
    def get_access_token(self):
        """获取飞书 access_token"""
        if self.access_token and datetime.now().timestamp() < self.token_expires:
            return self.access_token
        
        if not self.app_id or not self.app_secret:
            logger.warning("飞书 app_id/app_secret 未配置")
            return None
        
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10
            )
            data = resp.json()
            if data.get("code") == 0:
                self.access_token = data["tenant_access_token"]
                self.token_expires = datetime.now().timestamp() + data.get("expire", 7200) - 60
                return self.access_token
            else:
                logger.error(f"获取飞书 token 失败: {data}")
                return None
        except Exception as e:
            logger.error(f"飞书 token 请求异常: {e}")
            return None
    
    def send_message(self, receive_id_type="open_id", receive_id=None, msg_type="text", content=None):
        """发送飞书消息
        
        Args:
            receive_id_type: open_id/user_id/chat_id/email
            receive_id: 接收者ID
            msg_type: text/post/card 等
            content: 消息内容（JSON字符串或dict）
        """
        token = self.get_access_token()
        if not token:
            logger.warning("无法获取飞书 token，跳过发送")
            return {"success": False, "error": "no_token"}
        
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        
        try:
            resp = requests.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={
                    "receive_id": receive_id,
                    "msg_type": msg_type,
                    "content": content
                },
                timeout=10
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info(f"飞书消息发送成功: {receive_id}")
                return {"success": True, "message_id": data.get("data", {}).get("message_id")}
            else:
                logger.error(f"飞书消息发送失败: {data}")
                return {"success": False, "error": data.get("msg", "unknown")}
        except Exception as e:
            logger.error(f"飞书消息发送异常: {e}")
            return {"success": False, "error": str(e)}
    
    def send_alert(self, symbol, price, change_pct, strategy_name, level="info", receive_id=None):
        """发送股票告警消息
        
        Args:
            symbol: 股票代码
            price: 当前价格
            change_pct: 涨跌幅
            strategy_name: 策略名称
            level: 告警级别 info/warning/high
            receive_id: 接收者ID（可选，默认使用配置的ID）
        """
        if not receive_id:
            # 从配置读取默认接收者
            receive_id = getattr(self, 'default_receive_id', None)
            if not receive_id:
                logger.warning("未配置飞书接收者ID")
                return {"success": False, "error": "no_receive_id"}
        
        # 根据级别设置颜色
        color_map = {
            "info": "blue",
            "warning": "yellow", 
            "high": "red"
        }
        color = color_map.get(level, "blue")
        
        # 涨跌符号
        arrow = "📈" if change_pct >= 0 else "📉"
        sign = "+" if change_pct >= 0 else ""
        
        # 构建卡片消息
        card_content = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{arrow} 股票告警: {symbol}"},
                "template": color
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**策略**: {strategy_name}\n**价格**: ¥{price}\n**涨跌幅**: {sign}{change_pct}%\n**时间**: {datetime.now().strftime('%H:%M:%S')}"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看详情"},
                            "type": "primary",
                            "url": "http://localhost:3001/"
                        }
                    ]
                }
            ]
        }
        
        return self.send_message(
            receive_id_type="open_id",
            receive_id=receive_id,
            msg_type="interactive",
            content=card_content
        )
    
    def send_stock_alert(self, stock, price, chg_pct, strategy_name, trigger_condition, level="info"):
        """Send stock alert (alias for send_alert with stock-style params).
        
        Args:
            stock: Stock symbol
            price: Current price
            chg_pct: Change percentage
            strategy_name: Name of the triggered strategy
            trigger_condition: Description of the trigger condition
            level: Alert level (info/warning/high)
        """
        return self.send_alert(
            symbol=stock,
            price=price,
            change_pct=chg_pct,
            strategy_name=strategy_name,
            level=level,
            receive_id=getattr(self, 'default_chat_id', None)
        )
    
    def send_test_message(self, receive_id=None):
        """发送测试消息"""
        return self.send_alert(
            symbol="002149",
            price=48.96,
            change_pct=2.5,
            strategy_name="测试策略",
            level="info",
            receive_id=receive_id
        )
