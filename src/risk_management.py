import os
import json
from datetime import datetime

class RiskManagement:
    def __init__(self, state_file="data/state_machine.json"):
        self.state_file = state_file
        self.min_core_shares = {"2330": 0}
        self.max_daily_orders = 3
        self.max_capital_cap = 50000.0
        self.max_single_position = 15000.0
        self.load_state()

    def load_state(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") != today:
                        data["date"] = today
                        data["order_count"] = 0
                        data["executed_hashes"] = []
                    self.daily_state = data
                    self.save_state()
                    return
            except Exception:
                pass

        self.daily_state = {
            "date": today,
            "order_count": 0,
            "executed_hashes": [],
            "invested_cost": 0.0,
            "realized_pnl": 0.0,
            "nav": 50000.0,
            "available_cash": 45000.0
        }
        self.save_state()

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.daily_state, f, ensure_ascii=False, indent=2)

    def get_effective_Buying_power(self, actual_bank_balance: float) -> float:
        dynamic_cap = self.max_capital_cap + self.daily_state.get("realized_pnl", 0.0)
        remaining_quota = max(0.0, dynamic_cap - self.daily_state.get("invested_cost", 0.0))
        effective_cash = min(actual_bank_balance, remaining_quota) * 0.90
        return round(effective_cash, 0)

    def validate_order(self, order_intent, actual_bank_balance=300000.0):
        if self.daily_state["order_count"] >= self.max_daily_orders:
            return False, f"【熔斷】已達今日最大交易次數上限 ({self.max_daily_orders} 筆)"
        
        order_hash = order_intent.get("hash_id")
        if order_hash in self.daily_state["executed_hashes"]:
            return False, f"【熔斷】重複交易訊號 (Hash ID: {order_hash})"

        if order_intent.get("order_type") != "LIMIT":
            return False, "【熔斷】全面禁止市價單（Market Order）"

        if order_intent["side"] == "BUY":
            order_cost = order_intent["price"] * order_intent["shares"] * 1.001425
            effective_cash = self.get_effective_Buying_power(actual_bank_balance)

            if order_cost > self.max_single_position:
                return False, f"【熔斷】單筆買進超過單倉上限 ({self.max_single_position:.0f}元)"

            if order_cost > effective_cash:
                return False, f"【熔斷】超過 5 萬元量化池剩餘可用額度"

        return True, "【通過】5 道防呆保險絲與 5 萬元硬頂鎖檢核無誤"

    def record_order_success(self, order_intent):
        self.daily_state["order_count"] += 1
        self.daily_state["executed_hashes"].append(order_intent["hash_id"])
        order_amount = order_intent["price"] * order_intent["shares"]
        if order_intent["side"] == "BUY":
            self.daily_state["invested_cost"] += order_amount
        elif order_intent["side"] == "SELL":
            self.daily_state["invested_cost"] = max(0.0, self.daily_state["invested_cost"] - order_amount)
        self.save_state()
