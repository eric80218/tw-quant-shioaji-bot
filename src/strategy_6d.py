import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime


class Strategy6D:
    def __init__(self, watch_list=None):
        # 預設內建「台股高流動性核心 20 強」自動掃描池（免手動挑股，涵蓋科技、AI、重電、金融、傳產龍頭）
        self.watch_list = watch_list or [
            # AI 與半導體權值
            "2330.TW", "2454.TW", "2317.TW", "2382.TW", "3231.TW",
            "2357.TW", "2308.TW", "3711.TW", "2379.TW", "3034.TW",
            # 重電、航運與高動能波段
            "1519.TW", "1513.TW", "2603.TW", "2609.TW", "2368.TW",
            # 防禦價值與金控龍頭
            "1232.TW", "1216.TW", "2881.TW", "2882.TW", "2891.TW"
        ]
        self.max_single_amount = 15000.0   # 單倉最高 15,000 元
        self.min_single_amount = 3510.0    # 永豐金 2 折低消門檻
        self.atr_multiplier = 2.0          # 跌破最高價 - 2.0 倍 ATR 觸發賣出
        self.rotation_threshold = 7.5      # +7.5 分換股輪動門檻

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
        """
        步驟 1：先巡檢現有持倉，更新 14日 ATR 保本鎖利棘輪；若跌破棘輪線，立即優先產生 SELL 賣出單
        步驟 2：掃描 20 強清單尋找最強右側買點；若已滿 3 倉但新股分數領先最弱持倉 >= +7.5 分，觸發汰弱留強賣出單
        """
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

                # 更新持倉最高價與計算新棘輪停損價 (只升不降)
                highest_p = max(float(pos.get("highest_price", close_p)), close_p)
                raw_stop = round(highest_p - (self.atr_multiplier * atr), 1)

                # 保本加速鎖：當最高價已超過買進價 + 1.5 倍 ATR，停損線保底拉升至成本價 +0.5% (鎖住不敗)
                entry_p = float(pos["entry_price"])
                if highest_p >= entry_p + (1.5 * atr):
                    raw_stop = max(raw_stop, round(entry_p * 1.005, 1))

                new_ratchet_stop = max(float(pos.get("ratchet_stop", 0.0)), raw_stop)

                # 更新狀態機內的棘輪價格與現價評分
                current_score = round(rsi + ((close_p - ma5) / ma5 * 100), 2)
                pos["highest_price"] = round(highest_p, 1)
                pos["current_price"] = round(close_p, 1)
                pos["ratchet_stop"] = new_ratchet_stop
                pos["score"] = current_score

                if current_score < weakest_score:
                    weakest_score = current_score
                    weakest_symbol = sym

                # 檢查是否跌破 14D ATR 保本棘輪防線
                if close_p <= new_ratchet_stop:
                    print(f"-> 【觸發 ATR 棘輪停損/鎖利】{sym} 現價 {close_p} <= 棘輪線 {new_ratchet_stop}，準備賣出！")
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

        # === 第二階段：掃描台股 20 強清單尋找最佳右側買點 ===
        best_candidate = None
        highest_score = -999.0

        for symbol_raw in self.watch_list:
            pure_sym = symbol_raw.replace(".TW", "").replace(".TWO", "")
            if pure_sym in positions:
                continue  # 已持有的跳過

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

                # 6D 右側條件：站上 MA5 + 站上月線 MA20 (多頭排列) + RSI 向上勾頭
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
                print(f"-> 【觸發 +7.5分換股輪動】新股 {best_candidate['symbol']}({best_candidate['score']}分) 領先 {weakest_symbol}({weakest_score}分) 達 +{score_diff}分，先賣出弱勢股！")
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
                    "reason": f"換股輪動賣出：{best_candidate['symbol']} 分差 +{score_diff} 分"
                }
            return None

        # 情境 B：尚有空倉，計算 15,000 元以內的買進零股數
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
            "reason": f"右側突破 MA5+RSI勾頭 (初始棘輪停損 {best_candidate['ratchet_stop']}元)"
        }
