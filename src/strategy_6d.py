import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime


class Strategy6D:
    def __init__(self, watch_list=None):
        # 備援核心 20 強名單 (當證交所 API 維護時自動啟用)
        self.fallback_list = [
            "2330.TW", "2454.TW", "2317.TW", "2382.TW", "3231.TW",
            "2357.TW", "2308.TW", "3711.TW", "2379.TW", "3034.TW",
            "1519.TW", "1513.TW", "2603.TW", "2609.TW", "2368.TW",
            "1232.TW", "1216.TW", "2881.TW", "2882.TW", "2891.TW"
        ]
        self.max_single_amount = 15000.0   # 單倉最高 15,000 元
        self.min_single_amount = 3510.0    # 永豐金 2 折低消門檻
        self.atr_multiplier = 2.0          # 跌破最高價 - 2.0 倍 ATR 觸發賣出
        self.rotation_threshold = 7.5      # +7.5 分換股輪動門檻
        # 啟動時自動抓取最新市場動態 20 強
        self.watch_list = watch_list or self.fetch_dynamic_top20()

    def fetch_dynamic_top20(self) -> list:
        """
        自動連線台灣證交所 (TWSE) 官方 OpenAPI，
        動態篩選出全市場「資金流入最大、成交值最高」的前 20 檔強勢普通股
        """
        print("-> 【動態選股池】正在連線台灣證交所 (TWSE) 抓取最新全市場熱門 20 強...")
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                print("-> 證交所 API 暫無回應，啟用備援核心 20 強名單。")
                return self.fallback_list

            data = res.json()
            candidates = []
            for row in data:
                code = str(row.get("Code", "")).strip()
                # 1. 僅保留 4 碼上市普通股 (排除權證、ETF 與特別股)
                if len(code) != 4 or not code.isdigit() or code.startswith("00"):
                    continue

                try:
                    close_p = float(str(row.get("ClosingPrice", "0")).replace(",", ""))
                    trade_val = float(str(row.get("TradeValue", "0")).replace(",", ""))
                except ValueError:
                    continue

                # 2. 過濾股價區間 (20元 ~ 1500元)，確保 1.5 萬預算能買進且非雞蛋水餃股
                if 20.0 <= close_p <= 1500.0 and trade_val > 0:
                    candidates.append((code, trade_val))

            # 3. 依當日成交金額 (TradeValue) 由大到小排序，取全市場資金最集中的前 20 名
            candidates.sort(key=lambda x: x[1], reverse=True)
            top20 = [f"{c[0]}.TW" for c in candidates[:20]]

            if len(top20) >= 10:
                print(f"-> 【動態 20 強更新成功】今日市場資金焦點: {[x.replace('.TW','') for x in top20[:8]]}...")
                return top20
        except Exception as e:
            print(f"-> 動態抓取異常 ({e})，自動切換為備援 20 強名單。")

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
        positions = risk_mgr.daily_state.get("positions", {})
        today_str = datetime.now().strftime("%Y%m%d")

        # === 第一階段：現有持倉 14D ATR 保本棘輪巡檢 ===
        weakest_symbol = None
        weakest_score = 999.0

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
                raw_stop = round(highest_p - (self.atr_multiplier * atr), 1)

                # 保本加速鎖：獲利超過 1.5 倍 ATR 時，停損線保底拉升至成本價 +0.5%
                entry_p = float(pos["entry_price"])
                if highest_p >= entry_p + (1.5 * atr):
                    raw_stop = max(raw_stop, round(entry_p * 1.005, 1))

                new_ratchet_stop = max(float(pos.get("ratchet_stop", 0.0)), raw_stop)
                current_score = round(rsi + ((close_p - ma5) / ma5 * 100), 2)

                pos["highest_price"] = round(highest_p, 1)
                pos["current_price"] = round(close_p, 1)
                pos["ratchet_stop"] = new_ratchet_stop
                pos["score"] = current_score

                if current_score < weakest_score:
                    weakest_score = current_score
                    weakest_symbol = sym

                if close_p <= new_ratchet_stop:
                    print(f"-> 【觸發 ATR 棘輪鎖利/停損】{sym} 現價 {close_p} <= 棘輪線 {new_ratchet_stop}，準備賣出！")
                    risk_mgr.save_state()
                    return {
                        "hash_id": f"{today_str}_TW_{sym}_SELL_ATR",
                        "symbol": sym,
                        "side": "SELL",
                        "order_type": "LIMIT",
                        "price": round(close_p, 1),
                        "shares": int(pos["shares"]),
                        "strategy_score": current_score,
                        "atr": round(atr, 2),
                        "ratchet_stop": new_ratchet_stop,
                        "reason": f"跌破 14D ATR 棘輪線 ({new_ratchet_stop}元)"
                    }
            except Exception as e:
                print(f"-> 巡檢持倉 {sym} 發生異常: {e}")

        risk_mgr.save_state()

        # === 第二階段：掃描動態 20 強清單尋找最佳右側買點 ===
        best_candidate = None
        highest_score = -999.0

        for symbol_raw in self.watch_list:
            pure_sym = symbol_raw.replace(".TW", "").replace(".TWO", "")
            if pure_sym in positions:
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

                if (close_p > ma5) and (close_p > ma20) and (rsi_today > rsi_yest):
                    score = round(rsi_today + ((close_p - ma5) / ma5 * 100), 2)
                    if score > highest_score:
                        highest_score = score
                        best_candidate = {
                            "symbol": pure_sym,
                            "price": round(close_p, 1),
                            "atr": round(atr, 2),
                            "score": score,
                            "ratchet_stop": round(close_p - (self.atr_multiplier * atr), 1)
                        }
            except Exception:
                continue

        if not best_candidate:
            return None

        # 情境 A：已滿 3 倉，檢查是否觸發「+7.5 分換股輪動門檻」
        if len(positions) >= risk_mgr.max_slots and weakest_symbol:
            score_diff = round(best_candidate["score"] - weakest_score, 2)
            if score_diff >= self.rotation_threshold:
                weak_pos = positions[weakest_symbol]
                return {
                    "hash_id": f"{today_str}_TW_{weakest_symbol}_SELL_ROTATE",
                    "symbol": weakest_symbol,
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "price": float(weak_pos.get("current_price", weak_pos["entry_price"])),
                    "shares": int(weak_pos["shares"]),
                    "strategy_score": weakest_score,
                    "atr": best_candidate["atr"],
                    "ratchet_stop": weak_pos["ratchet_stop"],
                    "reason": f"換股輪動：{best_candidate['symbol']} 領先 +{score_diff} 分"
                }
            return None

        # 情境 B：尚有空倉，換算 15,000 元以內的零股數
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
            "reason": f"右側突破 MA5+RSI勾頭 (棘輪停損 {best_candidate['ratchet_stop']}元)"
        }
