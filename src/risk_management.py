import os
import json
from datetime import datetime, timedelta, timezone

TAIWAN_TZ = timezone(timedelta(hours=8))


class RiskManagement:
    def __init__(self, state_file="data/daily_state.json"):
        self.state_file = state_file
        self.max_capital_cap = 50000.0      # FUSE 2: 永豐波段池 5 萬本金硬頂
        self.cash_buffer_ratio = 0.90       # 保留 10% 現金緩衝墊 (實際最高動用 45,000)
        self.max_single_position = 15000.0  # 單倉最高上限 15,000 元
        self.min_order_amount = 3510.0      # 永豐金 2 折低消門檻
        self.max_daily_orders = 3           # FUSE 4: 單日最多交易 3 筆
        self.max_slots = 3                  # 最多持有 3 倉
        self.daily_state = self._load_state()

    def _load_state(self) -> dict:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        today_str = datetime.now(TAIWAN_TZ).strftime("%Y-%m-%d")
        default_state = {
            "date": today_str,
            "order_count": 0,
            "executed_hashes": [],
            "invested_cost": 0.0,
            "realized_pnl": 0.0,
            "positions": {}
        }
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("date") != today_str:
                    data["date"] = today_str
                    data["order_count"] = 0
                    data["executed_hashes"] = []
                data.setdefault("invested_cost", 0.0)
                data.setdefault("realized_pnl", 0.0)
                data.setdefault("positions", {})
                return data
            except Exception:
                return default_state
        return default_state

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.daily_state, f, ensure_ascii=False, indent=2)

    def get_effective_Buying_power(self, actual_bank_balance: float = 300000.0) -> float:
        dynamic_cap = self.max_capital_cap + float(self.daily_state.get("realized_pnl", 0.0))
        effective_pool = min(actual_bank_balance, dynamic_cap) * self.cash_buffer_ratio
        invested = float(self.daily_state.get("invested_cost", 0.0))
        return max(0.0, round(effective_pool - invested, 0))

    def validate_order(self, order_intent: dict, actual_bank_balance: float = 300000.0):
        hash_id = order_intent.get("hash_id", "")
        side = order_intent.get("side", "BUY")
        symbol = order_intent.get("symbol", "")
        price = float(order_intent.get("price", 0.0))
        shares = int(order_intent.get("shares", 0))
        amount = round(price * shares, 0)

        # FUSE 4: 冪等鎖與單日次數上限
        if hash_id in self.daily_state.get("executed_hashes", []):
            return False, f"FUSE 4 攔截：重覆訊號 ({hash_id})"

        if self.daily_state.get("order_count", 0) >= self.max_daily_orders:
            return False, f"FUSE 4 攔截：已達單日交易上限 ({self.max_daily_orders} 筆)"

        positions = self.daily_state.get("positions", {})
        today_str = datetime.now(TAIWAN_TZ).strftime("%Y-%m-%d")

        if side == "BUY":
            if len(positions) >= self.max_slots:
                return False, f"FUSE 5 攔截：已達目前允許持倉上限 ({self.max_slots} 倉)"
            if amount > self.max_single_position:
                return False, f"FUSE 2 攔截：單筆金額 {amount:.0f} 超過 1.5 萬硬頂"
            if amount < self.min_order_amount:
                return False, f"FUSE 2 攔截：單筆金額 {amount:.0f} 低於永豐低消門檻"
            avail = self.get_effective_Buying_power(actual_bank_balance)
            if amount > avail:
                return False, f"FUSE 2 攔截：可用額度不足 (需 {amount:.0f} / 剩 {avail:.0f})"
        elif side == "SELL":
            if symbol not in positions:
                return False, f"FUSE 1 攔截：帳本無 {symbol} 持倉，禁止賣出底倉"
            if positions[symbol].get("buy_date") == today_str:
                return False, f"FUSE 4 攔截：T+1 零股保護鎖，禁止當日沖銷 ({symbol})"

        return True, "PASS (通過 5 道防呆保險絲)"

    def record_order_success(self, order_intent: dict):
        hash_id = order_intent.get("hash_id", "")
        side = order_intent.get("side", "BUY")
        symbol = order_intent.get("symbol", "")
        price = float(order_intent.get("price", 0.0))
        shares = int(order_intent.get("shares", 0))
        today_str = datetime.now(TAIWAN_TZ).strftime("%Y-%m-%d")

        self.daily_state["order_count"] = self.daily_state.get("order_count", 0) + 1
        if hash_id:
            self.daily_state.setdefault("executed_hashes", []).append(hash_id)

        positions = self.daily_state.setdefault("positions", {})

        if side == "BUY":
            cost = round(price * shares * 1.001425, 0)
            self.daily_state["invested_cost"] = round(self.daily_state.get("invested_cost", 0.0) + cost, 0)
            positions[symbol] = {
                "shares": shares,
                "entry_price": price,
                "current_price": price,
                "highest_price": price,
                "ratchet_stop": order_intent.get("ratchet_stop", round(price * 0.93, 2)),
                "score": order_intent.get("strategy_score", 0.0),
                "buy_date": today_str
            }
        elif side == "SELL" and symbol in positions:
            pos = positions.pop(symbol)
            entry_cost = round(float(pos["entry_price"]) * int(pos["shares"]) * 1.001425, 0)
            net_proceeds = round(price * shares * (1 - 0.001425 - 0.003), 0)
            pnl = net_proceeds - entry_cost
            self.daily_state["invested_cost"] = max(0.0, round(self.daily_state.get("invested_cost", 0.0) - entry_cost, 0))
            self.daily_state["realized_pnl"] = round(self.daily_state.get("realized_pnl", 0.0) + pnl, 0)

        self.save_state()
