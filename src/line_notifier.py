import os
import requests
from datetime import datetime

class LineNotifier:
    def __init__(self):
        self.access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
        self.user_id = os.getenv("LINE_USER_ID", "").strip()
        self.bot_warroom_url = os.getenv("BOT_WARROOM_URL", "https://你的GitHub帳號.github.io/tw-quant-shioaji-bot/")
        self.main_warroom_url = os.getenv("MAIN_WARROOM_URL", "https://你的GitHub帳號.github.io/你的舊操盤室倉庫名稱/")

    def send_execution_report(self, order_intent, is_safe, fuse_message, is_live_mode, risk_mgr, actual_bank_balance=300000.0):
        if not self.access_token:
            return False
        
        dynamic_nav = risk_mgr.max_capital_cap + risk_mgr.daily_state.get("realized_pnl", 0.0)
        invested_cost = risk_mgr.daily_state.get("invested_cost", 0.0)
        effective_cash = risk_mgr.get_effective_Buying_power(actual_bank_balance)
        order_count = risk_mgr.daily_state.get("order_count", 0)
        
        mode_label = "🟢 Shioaji 實盤連線" if is_live_mode else "🟡 AI 模擬沙盒"
        status_color = "#10B981" if is_safe else "#EF4444"
        status_title = "✅ 5 道保險絲檢核通過" if is_safe else "🛡️ 保險絲攔截熔斷"

        flex_contents = {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#0B0F19", "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": "⚡ 6D 量化自動交易戰情推播", "color": "#38BDF8", "weight": "bold", "size": "xs"},
                    {"type": "text", "text": status_title, "color": status_color, "weight": "bold", "size": "lg", "margin": "sm"},
                    {"type": "text", "text": f"{mode_label}", "color": "#94A3B8", "size": "xxs", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "backgroundColor": "#111827", "paddingAll": "16px", "spacing": "md",
                "contents": [
                    {
                        "type": "box", "layout": "vertical", "backgroundColor": "#1F2937", "cornerRadius": "8px", "paddingAll": "12px",
                        "contents": [
                            {"type": "text", "text": f"標的：{order_intent.get('symbol')} ({order_intent.get('side')})", "color": "#F8FAFC", "weight": "bold", "size": "sm"},
                            {"type": "text", "text": f"規格：{order_intent.get('shares')} 股 @ NT$ {order_intent.get('price')}", "color": "#CBD5E1", "size": "xs"}
                        ]
                    },
                    {
                        "type": "box", "layout": "vertical", "spacing": "sm",
                        "contents": [
                            {"type": "text", "text": f"5萬池淨值: NT$ {dynamic_nav:,.0f}", "color": "#FFFFFF", "size": "xs"},
                            {"type": "text", "text": f"剩餘可買現金: NT$ {effective_cash:,.0f}", "color": "#38BDF8", "size": "sm", "weight": "bold"},
                            {"type": "text", "text": f"今日交易: {order_count} / 3 筆", "color": "#34D399", "size": "xs"}
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "backgroundColor": "#0B0F19", "spacing": "sm", "paddingAll": "12px",
                "contents": [
                    {"type": "button", "style": "primary", "color": "#0284C7", "height": "sm", "action": {"type": "uri", "label": "⚡ 開啟戰情室", "uri": self.bot_warroom_url}},
                    {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "uri", "label": "🧭 總操盤室", "uri": self.main_warroom_url}}
                ]
            }
        }
        
        url = "https://api.line.me/v2/bot/message/broadcast" if not self.user_id else "https://api.line.me/v2/bot/message/push"
        body = {"to": self.user_id, "messages": [{"type": "flex", "altText": f"6D量化戰情通知: {status_title}", "contents": flex_contents}]} if self.user_id else {"messages": [{"type": "flex", "altText": f"6D量化戰情通知", "contents": flex_contents}]}
        
        try:
            requests.post(url, headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.access_token}"}, json=body, timeout=10)
        except Exception:
            pass
