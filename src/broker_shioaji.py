import os
import time
import base64


class ShioajiBroker:
    def __init__(self, simulation=False):
        self.simulation = simulation
        self.api = None
        self.is_logged_in = False
        self.sim_verified_msg = ""

    def _prepare_ca_file(self, ca_base64: str) -> str:
        """將 GitHub Secrets 中的 Base64 字串還原為 /tmp/Sinopac.pfx 實體憑證檔"""
        ca_path = "/tmp/Sinopac.pfx"
        clean_b64 = ca_base64.strip().replace("\n", "").replace("\r", "").replace(" ", "")
        with open(ca_path, "wb") as f:
            f.write(base64.b64decode(clean_b64))
        return ca_path

    def run_official_sim_verification(self, api_key: str, secret_key: str, ca_base64: str = "", ca_passwd: str = "") -> str:
        """
        永豐金官方 API 模擬環境自動通關腳本 (相容最新版 Shioaji 1.x API)
        """
        print("-> 【永豐 API 模擬驗證】開始執行 Shioaji 官方模擬下單測試...")
        ca_status = "未提供憑證"
        if ca_base64:
            try:
                ca_path = self._prepare_ca_file(ca_base64)
                file_size = os.path.getsize(ca_path)
                ca_status = f"憑證解碼成功({file_size} bytes)"
            except Exception as ce:
                ca_status = f"憑證格式錯誤({ce})"

        try:
            import shioaji as sj
            sim_api = sj.Shioaji(simulation=True)
            accounts = sim_api.login(api_key=api_key, secret_key=secret_key)
            print(f"-> [Step 1/3] 模擬環境登入成功！帳戶列表: {accounts}")

            # 等待商品合約檔載入 (最多等待 15 秒)
            for _ in range(15):
                try:
                    if sim_api.Contracts.Stocks["2890"] is not None:
                        break
                except Exception:
                    pass
                time.sleep(1)

            contract = sim_api.Contracts.Stocks["2890"] or sim_api.Contracts.Stocks["2330"]
            print(f"-> [Step 2/3] 成功鎖定測試標的合約: {contract}")

            # 兼容 Shioaji 1.x 最新版 (StockOrderLot) 與舊版 (TFTStockOrderLot)
            lot_enum = getattr(sj.constant, "StockOrderLot", getattr(sj.constant, "TFTStockOrderLot", None))
            common_lot = getattr(lot_enum, "Common", "Common")

            # 送出永豐官方要求的模擬委託單 (買進 1 張 2890 @ 20.0 元)
            order = sim_api.Order(
                price=20.0,
                quantity=1,
                action=sj.constant.Action.Buy,
                price_type=sj.constant.StockPriceType.LMT,
                order_type=sj.constant.OrderType.ROD,
                order_lot=common_lot,
                account=sim_api.stock_account
            )
            trade = sim_api.place_order(contract, order)
            print(f"-> [Step 3/3] 模擬委託送出成功！Trade: {trade}")
            time.sleep(2)
            sim_api.logout()
            return f"✅ 永豐模擬測試單已成功送出 ({ca_status})"
        except Exception as e:
            print(f"-> [模擬驗證異常] {e}")
            return f"⚠️ 模擬測試回報: {e} ({ca_status})"

    def login(self) -> bool:
        api_key = os.environ.get("SHIOAJI_API_KEY", "").strip()
        secret_key = os.environ.get("SHIOAJI_SECRET_KEY", "").strip()
        ca_base64 = os.environ.get("SHIOAJI_CA_BASE64", "").strip()
        ca_passwd = os.environ.get("CA_PASSWORD", "").strip()

        if not api_key or not secret_key:
            print("-> 【Paper Trading 沙盒模式】未偵測到永豐金 API 金鑰，以模擬沙盒運行。")
            return False

        if self.simulation or not ca_base64 or not ca_passwd:
            self.sim_verified_msg = self.run_official_sim_verification(api_key, secret_key, ca_base64, ca_passwd)
            return False

        # 優先嘗試登入正式實盤 (simulation=False)
        try:
            import shioaji as sj
            self.api = sj.Shioaji(simulation=False)
            self.api.login(api_key=api_key, secret_key=secret_key)

            ca_path = self._prepare_ca_file(ca_base64)
            self.api.activate_ca(ca_path=ca_path, ca_passwd=ca_passwd)

            self.is_logged_in = True
            self.sim_verified_msg = "🟢 永豐實盤 API 與電子憑證已完美連線"
            print("-> 【Shioaji 實盤模式】永豐金 API 登入與 .pfx 憑證載入成功！")
            return True
        except Exception as e:
            print(f"-> 【實盤待開通】({e})，自動執行官方模擬環境下單測試...")
            self.sim_verified_msg = self.run_official_sim_verification(api_key, secret_key, ca_base64, ca_passwd)
            self.is_logged_in = False
            return False

    def get_actual_positions(self):
        if not self.is_logged_in or not self.api:
            return None
        try:
            positions = self.api.list_positions(self.api.stock_account)
            return {str(p.code): int(p.quantity) for p in positions}
        except Exception:
            return None

    def place_limit_order(self, symbol: str, action: str, price: float, quantity: int) -> bool:
        if not self.is_logged_in or not self.api:
            print(f"-> [模擬下單] {action} {symbol} {quantity}股 @ {price}元")
            return True
        try:
            import shioaji as sj
            contract = self.api.Contracts.Stocks[symbol]
            lot_enum = getattr(sj.constant, "StockOrderLot", getattr(sj.constant, "TFTStockOrderLot", None))
            intraday_odd = getattr(lot_enum, "IntradayOdd", "IntradayOdd")

            order = self.api.Order(
                price=price,
                quantity=quantity,
                action=sj.constant.Action.Buy if action == "BUY" else sj.constant.Action.Sell,
                price_type=sj.constant.StockPriceType.LMT,
                order_type=sj.constant.OrderType.ROD,
                order_lot=intraday_odd,
                account=self.api.stock_account
            )
            trade = self.api.place_order(contract, order)
            print(f"-> [實盤委託成功] {trade}")
            return True
        except Exception as e:
            print(f"-> [實盤委託失敗] {e}")
            return False

    def logout(self):
        if self.is_logged_in and self.api:
            try:
                self.api.logout()
            except Exception:
                pass
