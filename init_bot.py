import os

files_content = {
    "requirements.txt": """shioaji>=1.2.0
pandas>=2.0.0
requests>=2.31.0
yfinance>=0.2.40
""",
    
    "src/__init__.py": """# src 模組初始化
""",
    
    "src/risk_management.py": """import os
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
""",

    "src/broker_shioaji.py": """import os
import base64
import shioaji as sj

class ShioajiBroker:
    def __init__(self, simulation=False):
        self.api = sj.Shioaji(simulation=simulation)
        self.is_logged_in = False

    def restore_certificate(self):
        ca_base64 = os.getenv("SHIOAJI_CA_BASE64")
        if not ca_base64:
            raise ValueError("【錯誤】未找到 SHIOAJI_CA_BASE64 環境變數")
        ca_data = base64.b64decode(ca_base64)
        ca_path = "ca_cert.pfx"
        with open(ca_path, "wb") as f:
            f.write(ca_data)
        return ca_path

    def login(self):
        api_key = os.getenv("SHIOAJI_API_KEY")
        secret_key = os.getenv("SHIOAJI_SECRET_KEY")
        ca_password = os.getenv("CA_PASSWORD")

        if not api_key or not secret_key:
            print("【待機中】尚未設定永豐金 API Key，系統維持 AI 模擬沙盒模式。")
            return False

        try:
            self.api.login(api_key=api_key, secret_key=secret_key, fetch_contract=True)
            if ca_password:
                ca_path = self.restore_certificate()
                self.api.activate_ca(ca_path=ca_path, ca_passwd=ca_password, person_id=os.getenv("SHIOAJI_PERSON_ID", ""))
                if os.path.exists(ca_path):
                    os.remove(ca_path)
            self.is_logged_in = True
            print("【Shioaji】永豐金 API 登入與憑證授權成功！")
            return True
        except Exception as e:
            self.is_logged_in = False
            print(f"【Shioaji 登入異常】{str(e)}，自動降級為 AI 模擬模式。")
            return False

    def place_limit_order(self, symbol: str, action: str, price: float, quantity: int):
        if not self.is_logged_in:
            raise ConnectionError("【錯誤】API 尚未登入")
        contract = self.api.Contracts.Stocks[symbol]
        order_action = sj.constant.Action.Buy if action == "BUY" else sj.constant.Action.Sell
        order = self.api.Order(
            action=order_action, price=price, quantity=quantity,
            price_type=sj.constant.StockPriceType.LMT, order_type=sj.constant.OrderType.ROD,
            account=self.api.stock_account
        )
        return self.api.place_order(contract, order)

    def logout(self):
        if self.is_logged_in:
            self.api.logout()
""",

    "src/line_notifier.py": """import os
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
""",

    "src/strategy_6d.py": """import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

class Strategy6D:
    def __init__(self, watch_list=None):
        self.watch_list = watch_list or ["2330.TW", "2317.TW", "1232.TW", "2454.TW"]
        self.max_single_amount = 15000.0
        self.min_single_amount = 3510.0

    def calculate_indicators(self, df):
        df['MA5'] = df['Close'].rolling(window=5).mean()
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        df['ATR_14'] = np.max(pd.concat([high_low, high_close, low_close], axis=1), axis=1).rolling(window=14).mean()
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['RSI_14'] = 100 - (100 / (1 + (gain / loss)))
        return df

    def scan_best_signal(self, available_cash):
        for symbol_raw in self.watch_list:
            try:
                df = yf.Ticker(symbol_raw).history(period="3m")
                if df.empty or len(df) < 25: continue
                df = self.calculate_indicators(df)
                latest, prev = df.iloc[-1], df.iloc[-2]
                
                if (latest['Close'] > latest['MA5']) and (latest['RSI_14'] > prev['RSI_14']):
                    pure_symbol = symbol_raw.replace(".TW", "").replace(".TWO", "")
                    target_amount = min(self.max_single_amount, available_cash * 0.95)
                    if target_amount < self.min_single_amount: continue
                    shares = int(target_amount // latest['Close'])
                    if shares < 1: continue
                    
                    return {
                        "hash_id": f"{datetime.now().strftime('%Y%m%d')}_TW_{pure_symbol}_BUY_6D",
                        "symbol": pure_symbol, "side": "BUY", "order_type": "LIMIT",
                        "price": round(float(latest['Close']), 1), "shares": int(shares),
                        "strategy_score": round(float(latest['RSI_14']), 2), "atr": round(float(latest['ATR_14']), 2)
                    }
            except Exception:
                continue
        return None
""",

    "main.py": """import os
import json
from datetime import datetime
from src.risk_management import RiskManagement
from src.broker_shioaji import ShioajiBroker
from src.line_notifier import LineNotifier
from src.strategy_6d import Strategy6D

def export_war_room_json(risk_mgr, actual_bank_balance=300000.0, is_live=False, last_signal="無強勢訊號"):
    os.makedirs("docs", exist_ok=True)
    dynamic_nav = risk_mgr.max_capital_cap + risk_mgr.daily_state.get("realized_pnl", 0.0)
    effective_cash = risk_mgr.get_effective_Buying_power(actual_bank_balance)
    
    payload = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_live": is_live, "daily_order_count": risk_mgr.daily_state["order_count"],
        "max_daily_orders": risk_mgr.max_daily_orders, "nav": round(dynamic_nav, 0),
        "available_cash": round(effective_cash, 0), "invested_cost": round(risk_mgr.daily_state.get("invested_cost", 0.0), 0),
        "single_slot_limit": risk_mgr.max_single_position, "max_slots": 3, "latest_signal": last_signal
    }
    with open("docs/dashboard_data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def run_trading_pipeline():
    risk_mgr = RiskManagement()
    broker = ShioajiBroker(simulation=False)
    notifier = LineNotifier()
    strategy = Strategy6D()

    is_live_mode = broker.login()
    actual_bank_balance = 300000.0
    effective_cash = risk_mgr.get_effective_Buying_power(actual_bank_balance)
    
    order_intent = strategy.scan_best_signal(available_cash=effective_cash)
    if not order_intent:
        export_war_room_json(risk_mgr, actual_bank_balance, is_live_mode, "今日無符合條件標的")
        broker.logout()
        return

    is_safe, fuse_message = risk_mgr.validate_order(order_intent, actual_bank_balance=actual_bank_balance)
    if is_safe:
        if is_live_mode: broker.place_limit_order(order_intent["symbol"], order_intent["side"], order_intent["price"], order_intent["shares"])
        risk_mgr.record_order_success(order_intent)
        signal_desc = f"{order_intent['symbol']} 買進 {order_intent['shares']}股"
    else:
        signal_desc = f"攔截: {order_intent['symbol']}"

    export_war_room_json(risk_mgr, actual_bank_balance, is_live_mode, signal_desc)
    notifier.send_execution_report(order_intent, is_safe, fuse_message, is_live_mode, risk_mgr, actual_bank_balance)
    broker.logout()

if __name__ == "__main__":
    run_trading_pipeline()
""",

    "docs/index.html": """<!DOCTYPE html>
<html lang="zh-TW" class="dark">
<head>
  <meta charset="UTF-8">
  <title>6D Quant Auto-Trading War Room</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 p-6 max-w-5xl mx-auto font-sans">
  <header class="flex justify-between items-center border-b border-slate-800 pb-4 mb-6">
    <h1 class="text-2xl font-bold">⚡ 6D Quant Auto-Bot 戰情室</h1>
    <div id="last-updated" class="text-xs text-slate-400">載入中...</div>
  </header>
  <div class="grid grid-cols-3 gap-4 mb-6">
    <div class="bg-slate-900 p-4 rounded-xl border border-slate-800">
      <div class="text-xs text-slate-400">5萬池淨值 (NAV)</div>
      <div id="nav-val" class="text-xl font-bold mt-1">NT$ 50,000</div>
    </div>
    <div class="bg-slate-900 p-4 rounded-xl border border-slate-800">
      <div class="text-xs text-slate-400">剩餘可買現金</div>
      <div id="cash-val" class="text-xl font-bold text-sky-400 mt-1">NT$ 45,000</div>
    </div>
    <div class="bg-slate-900 p-4 rounded-xl border border-slate-800">
      <div class="text-xs text-slate-400">今日交易配額</div>
      <div id="quota-val" class="text-xl font-bold text-emerald-400 mt-1">0 / 3 筆</div>
    </div>
  </div>
  <script>
    fetch('./dashboard_data.json').then(r => r.json()).then(d => {
      document.getElementById('last-updated').innerText = '最後更新: ' + d.last_updated;
      document.getElementById('nav-val').innerText = 'NT$ ' + d.nav.toLocaleString();
      document.getElementById('cash-val').innerText = 'NT$ ' + d.available_cash.toLocaleString();
      document.getElementById('quota-val').innerText = d.daily_order_count + ' / ' + d.max_daily_orders + ' 筆';
    }).catch(e => console.log('等待首次資料生成'));
  </script>
</body>
</html>
""",

    ".github/workflows/quant_trading.yml": """name: TW 6D Quant Auto-Trading & WarRoom

on:
  schedule:
    - cron: '50 0 * * 1-5'
    - cron: '0 5 * * 1-5'
  workflow_dispatch:

jobs:
  run-bot:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
      - name: Install Dependencies
        run: pip install -r requirements.txt
      - name: Run Pipeline
        env:
          SHIOAJI_API_KEY: ${{ secrets.SHIOAJI_API_KEY }}
          SHIOAJI_SECRET_KEY: ${{ secrets.SHIOAJI_SECRET_KEY }}
          CA_PASSWORD: ${{ secrets.CA_PASSWORD }}
          SHIOAJI_CA_BASE64: ${{ secrets.SHIOAJI_CA_BASE64 }}
          LINE_CHANNEL_ACCESS_TOKEN: ${{ secrets.LINE_CHANNEL_ACCESS_TOKEN }}
        run: python main.py
      - name: Commit and Push
        run: |
          git config --local user.email "quant-bot@github.com"
          git config --local user.name "6D Quant Bot"
          git add data/ docs/
          git diff --quiet && git diff --staged --quiet || (git commit -m "chore: auto update war-room data" && git push)
"""
}

for filepath, content in files_content.items():
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[建立成功] {filepath}")

print("\\n🎉 所有 9 個專案檔案已全數自動生成完畢！")
