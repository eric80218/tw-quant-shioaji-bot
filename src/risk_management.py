import os
import json
from datetime import datetime, timedelta, timezone
​class RiskManagement:
def init(self, state_file="data/state_machine.json"):
self.state_file = state_file
self.min_core_shares = {"2330": 0}
self.max_daily_orders = 3
self.max_capital_cap = 50000.0
self.max_single_position = 15000.0
self.max_slots = 3
self.load_state()
​def get_taiwan_today(self):
"""取得台灣當下的日期字串"""
tw_tz = timezone(timedelta(hours=8))
return datetime.now(tw_tz).strftime("%Y-%m-%d")
​def load_state(self):
today = self.get_taiwan_today()
if os.path.exists(self.state_file):
try:
with open(self.state_file, "r", encoding="utf-8") as f:
data = json.load(f)
if data.get("date") != today:
data["date"] = today
data["order_count"] = 0
data["executed_hashes"] = []
if "positions" not in data:
data["positions"] = {}
self.daily_state = data
self.save_state()
return
except Exception:
pass
​self.daily_state = {
"date": today,
"order_count": 0,
"executed_hashes": [],
"invested_cost": 0.0,
"realized_pnl": 0.0,
"nav": 50000.0,
"available_cash": 45000.0,
"positions": {}
}
self.save_state()
​def save_state(self):
os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
with open(self.state_file, "w", encoding="utf-8") as f:
json.dump(self.daily_state, f, ensure_ascii=False, indent=2)
​def get_effective_Buying_power(self, actual_bank_balance: float) -> float:
dynamic_cap = self.max_capital_cap + self.daily_state.get("realized_pnl", 0.0)
remaining_quota = max(0.0, dynamic_cap - self.daily_state.get("invested_cost", 0.0))
effective_cash = min(actual_bank_balance, remaining_quota) * 0.90
return round(effective_cash, 0)
​def validate_order(self, order_intent, actual_bank_balance=300000.0):
if self.daily_state["order_count"] >= self.max_daily_orders:
return False, f"【熔斷】已達今日最大交易次數上限 ({self.max_daily_orders} 筆)"
​order_hash = order_intent.get("hash_id")
if order_hash in self.daily_state["executed_hashes"]:
return False, f"【熔斷】重複交易訊號 (Hash ID: {order_hash})"
​if order_intent.get("order_type") != "LIMIT":
return False, "【熔斷】全面禁止市價單（Market Order）"
​symbol = order_intent["symbol"]
positions = self.daily_state.get("positions", {})
​if order_intent["side"] == "BUY":
if symbol in positions:
return False, f"【熔斷】已持有 {symbol}，不重複加碼同一倉"
if len(positions) >= self.max_slots:
return False, f"【熔斷】已滿 {self.max_slots} 倉上限"
​order_cost = order_intent["price"] * order_intent["shares"] * 1.001425
effective_cash = self.get_effective_Buying_power(actual_bank_balance)
​if order_cost > self.max_single_position:
return False, f"【熔斷】單筆買進超過單倉上限 ({self.max_single_position:.0f}元)"
if order_cost > effective_cash:
return False, f"【熔斷】超過 5 萬元量化池剩餘可用額度"
​elif order_intent["side"] == "SELL":
if symbol not in positions:
return False, f"【熔斷】帳本無 {symbol} 持倉"
today = self.get_taiwan_today()
if positions[symbol].get("buy_date") == today:
return False, f"【熔斷】台股盤中零股不可當沖 ({symbol} 為今日買進，T+1 始可賣出)"
​return True, f"【通過】5 道防呆保險絲檢核無誤"
​def record_order_success(self, order_intent):
self.daily_state["order_count"] += 1
self.daily_state["executed_hashes"].append(order_intent["hash_id"])
symbol = order_intent["symbol"]
price = order_intent["price"]
shares = order_intent["shares"]
positions = self.daily_state.setdefault("positions", {})
​if order_intent["side"] == "BUY":
cost = round(price * shares * 1.001425, 0)
self.daily_state["invested_cost"] += cost
positions[symbol] = {
"shares": shares,
"entry_price": price,
"highest_price": price,
"ratchet_stop": order_intent.get("ratchet_stop", round(price * 0.94, 1)),
"score": order_intent.get("strategy_score", 60.0),
"buy_date": self.get_taiwan_today()
}
elif order_intent["side"] == "SELL" and symbol in positions:
pos = positions.pop(symbol)
entry_cost = round(pos["entry_price"] * pos["shares"] * 1.001425, 0)
net_proceeds = round(price * shares * (1 - 0.001425 - 0.003), 0)
pnl = net_proceeds - entry_cost
self.daily_state["invested_cost"] = max(0.0, self.daily_state["invested_cost"] - entry_cost)
self.daily_state["realized_pnl"] = round(self.daily_state.get("realized_pnl", 0.0) + pnl, 0)
self.daily_state["nav"] = round(self.max_capital_cap + self.daily_state["realized_pnl"], 0)
​self.save_state()