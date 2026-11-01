import yfinance as yf
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
