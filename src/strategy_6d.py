import math
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

TAIWAN_TZ = timezone(timedelta(hours=8))


class Strategy6D:
    def __init__(self, watch_list=None):
        self.fallback_list = [
            "2330.TW", "2454.TW", "2317.TW", "2382.TW", "3231.TW",
            "2357.TW", "2308.TW", "3711.TW", "2379.TW", "3034.TW",
            "1519.TW", "1513.TW", "2603.TW", "2609.TW", "2368.TW",
            "1232.TW", "1216.TW", "2881.TW", "2882.TW", "2891.TW"
        ]
        self.fallback_names = {
            "2330": "台積電", "2454": "聯發科", "2317": "鴻海", "2382": "廣達", "3231": "緯創",
            "2357": "華碩", "2308": "台達電", "3711": "日月光投控", "2379": "瑞昱", "3034": "聯詠",
            "1519": "華城", "1513": "中興電", "2603": "長榮", "2609": "陽明", "2368": "金像電",
            "1232": "統一", "1216": "統一企業", "2881": "富邦金", "2882": "國泰金", "2891": "中信金"
        }
        self.max_single_amount = 15000.0   # 單倉最高 15,000 元
        self.min_single_amount = 3510.0    # 永豐金 2 折低消門檻
        self.atr_multiplier = 2.0          # 跌破最高價 - 2.0 倍 ATR 觸發賣出
        self.rotation_threshold = 7.5      # +7.5 分換股輪動門檻
        self.market_regime = "BULL (大盤多頭 ‧ 開放 3 倉)"
        self.scan_details = []             # 儲存今日 20 強掃描結果供網頁顯示
        self.stock_names = {}              # 儲存中文名稱對應表
        self.watch_list = watch_list or self.fetch_dynamic_top20()

    @staticmethod
    def get_tick_size(price: float) -> float:
        """台股官方 6 級價格升降單位 (Tick Size)"""
        if price < 10:
            return 0.01
        elif price < 50:
            return 0.05
        elif price < 100:
            return 0.1
        elif price < 500:
            return 0.5
        elif price < 1000:
            return 1.0
        else:
            return 5.0

    def align_tw_tick(self, raw_price: float, side: str = "NONE", aggressive_ticks: int = 1) -> float:
        """將價格精準對齊台股 Tick 檔位，避免 Shioaji API 退單"""
        tick = self.get_tick_size(raw_price)
        if side == "BUY":
            adjusted = raw_price + (tick * aggressive_ticks)
            steps = math.floor(round(adjusted / tick, 6))
        elif side == "SELL":
            adjusted = max(tick, raw_price - (tick * aggressive_ticks))
            steps = math.ceil(round(adjusted / tick, 6))
        else:
            steps = round(raw_price / tick)
        return round(steps * tick, 2)

    def check_market_regime(self) -> int:
        """大盤系統性風險濾網：檢查 0050.TW 是否站上 20 日月線"""
        try:
            df = yf.Ticker("0050.TW").history(period="3mo")
            if df.empty or len(df) < 22:
                return 3
            df["MA20"] = df["Close"].rolling(window=20).mean()
            close_p = float(df.iloc[-1]["Close"])
            ma20 = float(df.iloc[-1]["MA20"])
            if close_p < ma20:
                self.market_regime = f"DEFENSIVE (0050跌破月線 {close_p:.1f}<{ma20:.1f} ‧ 限縮 1 倉)"
                return 1
            else:
                self.market_regime = f"BULL (0050站穩月線 {close_p:.1f}>={ma20:.1f} ‧ 開放 3 倉)"
                return 3
        except Exception:
            return 3

    def fetch_dynamic_top20(self) -> list:
        print("-> 【動態選股池】正在連線台灣證交所 (TWSE) 抓取最新全市場熱門 20 強與中文股名...")
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                self.stock_names = self.fallback_names
                return self.fallback_list

            data = res.json()
            candidates = []
            name_dict = {}
            for row in data:
                code = str(row.get("Code", "")).strip()
                name = str(row.get("Name", "")).strip()
                if len(code) != 4 or not code.isdigit() or code.startswith("00"):
                    continue
                name_dict[code] = name
                try:
                    close_p = float(str(row.get("ClosingPrice", "0")).replace(",", ""))
                    trade_val = float(str(row.get("TradeValue", "0")).replace(",", ""))
                except ValueError:
                    continue

                if 20.0 <= close_p <= 1500.0 and trade_val > 0:
                    candidates.append((code, trade_val))

            candidates.sort(key=lambda x: x[1], reverse=True)
            top20 = [f"{c[0]}.TW" for c in candidates[:20]]
            self.stock_names = name_dict
            if len(top20) >= 10:
                return top20
        except Exception as e:
            print(f"-> 動態抓取異常 ({e})，自動切換為備援 20 強名單。")

        self.stock_names = self.fallback_names
        return self.fallback_list

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()

        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        df['ATR_14'] = np.max(pd.concat([high_low, high_close, low_close], axis=1), axis=1).rolling(window=14).mean()

        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['RSI_14'] = 100 - (100 / (1 + (gain / loss)))
        return df

    def evaluate_portfolio_and_scan(self, risk_mgr, available_cash: float) -> dict:
        allowed_slots = self.check_market_regime()
        risk_mgr.max_slots = allowed_slots

        positions = risk_mgr.daily_state.get("positions", {})
        now_tw = datetime.now(TAIWAN_TZ)
        today_str = now_tw.strftime("%Y%m%d")
        current_hm = now_tw.hour * 100 + now_tw.minute
        self.scan_details = []

        # === 第一階段：現有持倉 14D ATR 保本棘輪巡檢 (全天候允許停損賣出) ===
        weakest_symbol = None
        weakest_score = 999.0
        atr_sell_order = None

        for sym, pos in list(positions.items()):
            try:
                df = yf.Ticker(f"{sym}.TW").history(period="3mo")
                if df.empty or len(df) < 20:
                    continue
                df = self.calculate_indicators(df)
                latest = df.iloc[-1]
                close_p = float(latest['Close'])
                atr = float(latest['ATR_14'])
                rsi = float(latest['RSI_14'])
                ma5 = float(latest['MA5'])

                highest_p = max(float(pos.get("highest_price", close_p)), close_p)
                raw_stop = self.align_tw_tick(highest_p - (self.atr_multiplier * atr), side="NONE")

                entry_p = float(pos["entry_price"])
                if highest_p >= entry_p + (1.5 * atr):
                    raw_stop = max(raw_stop, self.align_tw_tick(entry_p * 1.005, side="NONE"))

                new_ratchet_stop = max(float(pos.get("ratchet_stop", 0.0)), raw_stop)
                current_score = round(rsi + ((close_p - ma5) / ma5 * 100), 2)

                pos["highest_price"] = self.align_tw_tick(highest_p, side="NONE")
                pos["current_price"] = self.align_tw_tick(close_p, side="NONE")
                pos["ratchet_stop"] = new_ratchet_stop
                pos["score"] = current_score

                if current_score < weakest_score:
                    weakest_score = current_score
                    weakest_symbol = sym

                if close_p <= new_ratchet_stop and atr_sell_order is None:
                    sell_limit_price = self.align_tw_tick(close_p, side="SELL", aggressive_ticks=1)
                    atr_sell_order = {
                        "hash_id": f"{today_str}_TW_{sym}_SELL_ATR",
                        "symbol": sym,
                        "side": "SELL",
                        "order_type": "LIMIT",
                        "price": sell_limit_price,
                        "shares": int(pos["shares"]),
                        "strategy_score": current_score,
                        "atr": round(atr, 2),
                        "ratchet_stop": new_ratchet_stop,
                        "reason": f"盤中防崩盤：跌破 14D ATR 棘輪線 ({new_ratchet_stop}元)"
                    }
            except Exception as e:
                print(f"-> 巡檢持倉 {sym} 發生異常: {e}")

        risk_mgr.save_state()

        # === 第二階段：掃描動態 20 強清單並更新戰情室雷達（帶入中文股名） ===
        best_candidate = None
        highest_score = -999.0

        for symbol_raw in self.watch_list:
            pure_sym = symbol_raw.replace(".TW", "").replace(".TWO", "")
            stock_name = self.stock_names.get(pure_sym, pure_sym)

            if pure_sym in positions:
                p_info = positions[pure_sym]
                self.scan_details.append({
                    "symbol": pure_sym,
                    "name": stock_name,
                    "price": p_info.get("current_price", p_info.get("entry_price", 0)),
                    "score": p_info.get("score", 0),
                    "status": "HOLDING"
                })
                continue

            try:
                df = yf.Ticker(symbol_raw).history(period="3mo")
                if df.empty or len(df) < 25:
                    continue
                df = self.calculate_indicators(df)
                latest, prev = df.iloc[-1], df.iloc[-2]

                close_p = float(latest['Close'])
                ma5 = float(latest['MA5'])
                ma20 = float(latest['MA20'])
                rsi_today = float(latest['RSI_14'])
                rsi_yest = float(prev['RSI_14'])
                atr = float(latest['ATR_14'])

                score = round(rsi_today + ((close_p - ma5) / ma5 * 100), 1)
                is_pass = (close_p > ma5) and (close_p > ma20) and (rsi_today > rsi_yest)

                self.scan_details.append({
                    "symbol": pure_sym,
                    "name": stock_name,
                    "price": round(close_p, 1),
                    "score": score,
                    "status": "PASS" if is_pass else "WAIT"
                })

                if is_pass and score > highest_score:
                    highest_score = score
                    buy_limit_price = self.align_tw_tick(close_p, side="BUY", aggressive_ticks=1)
                    init_stop = self.align_tw_tick(close_p - (self.atr_multiplier * atr), side="NONE")
                    best_candidate = {
                        "symbol": pure_sym,
                        "price": buy_limit_price,
                        "atr": round(atr, 2),
                        "score": score,
                        "ratchet_stop": init_stop
                    }
            except Exception:
                continue

        self.scan_details.sort(key=lambda x: x.get("score", 0), reverse=True)

        if atr_sell_order:
            return atr_sell_order

        # 盤中防追高鎖：09:00 ~ 12:44 僅巡檢停損，不買進新股
        if 900 <= current_hm < 1245:
            return None

        if not best_candidate:
            return None

        if len(positions) >= allowed_slots and weakest_symbol:
            score_diff = round(best_candidate["score"] - weakest_score, 2)
            if score_diff >= self.rotation_threshold:
                weak_pos = positions[weakest_symbol]
                raw_sell_p = float(weak_pos.get("current_price", weak_pos["entry_price"]))
                sell_limit_price = self.align_tw_tick(raw_sell_p, side="SELL", aggressive_ticks=1)
                return {
                    "hash_id": f"{today_str}_TW_{weakest_symbol}_SELL_ROTATE",
                    "symbol": weakest_symbol,
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "price": sell_limit_price,
                    "shares": int(weak_pos["shares"]),
                    "strategy_score": weakest_score,
                    "atr": best_candidate["atr"],
                    "ratchet_stop": weak_pos["ratchet_stop"],
                    "reason": f"換股輪動：{best_candidate['symbol']} 領先 +{score_diff} 分"
                }
            return None

        target_amount = min(self.max_single_amount, available_cash * 0.95)
        if target_amount < self.min_single_amount:
            return None

        shares = int(target_amount // best_candidate["price"])
        if shares < 1:
            return None

        return {
            "hash_id": f"{today_str}_TW_{best_candidate['symbol']}_BUY_6D",
            "symbol": best_candidate["symbol"],
            "side": "BUY",
            "order_type": "LIMIT",
            "price": best_candidate["price"],
            "shares": shares,
            "strategy_score": best_candidate["score"],
            "atr": best_candidate["atr"],
            "ratchet_stop": best_candidate["ratchet_stop"],
            "reason": f"尾盤確認突破+Tick對齊 (棘輪停損 {best_candidate['ratchet_stop']}元)"
        }
