import os
import requests


class LineNotifier:
    def __init__(self):
        self.token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
        self.user_id = os.environ.get("LINE_USER_ID", "").strip()

    def send_execution_report(self, order_intent: dict, is_safe: bool, fuse_msg: str, is_live: bool, risk_mgr, bank_balance: float):
        mode_str = "🟢 實盤委託" if is_live else "🟡 沙盒模擬"
        status_str = "✅ 執行成功" if is_safe else f"🛡️ 保險絲攔截 ({fuse_msg})"
        action_str = "買進" if order_intent.get("side") == "BUY" else "賣出"

        text = (
            f"【6D Quant 戰情回報】{mode_str}\n"
            f"標的：{order_intent.get('symbol')} ({action_str})\n"
            f"股數：{order_intent.get('shares')} 股 @ {order_intent.get('price')} 元\n"
            f"6D積分：{order_intent.get('strategy_score')} 分\n"
            f"棘輪停損：{order_intent.get('ratchet_stop')} 元\n"
            f"狀態：{status_str}\n"
            f"原因：{order_intent.get('reason', '')}"
        )
        print(text)

        if not self.token or not self.user_id:
            return

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}"
            }
            payload = {
                "to": self.user_id,
                "messages": [{"type": "text", "text": text}]
            }
            requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload, timeout=10)
        except Exception as e:
            print(f"-> LINE 推播異常: {e}")
