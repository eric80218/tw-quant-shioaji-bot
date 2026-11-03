import os
import base64


class ShioajiBroker:
    def __init__(self, simulation=False):
        self.simulation = simulation
        self.api = None
        self.is_logged_in = False

    def login(self) -> bool:
        api_key = os.environ.get("SHIOAJI_API_KEY", "").strip()
        secret_key = os.environ.get("SHIOAJI_SECRET_KEY", "").strip()
        ca_base64 = os.environ.get("SHIOAJI_CA_BASE64", "").strip()
        ca_passwd = os.environ.get("CA_PASSWORD", "").strip()

        if not api_key or not secret_key:
            print("-> 【Paper Trading 沙盒模式】未偵測到永豐金 API 金鑰，以模擬沙盒運行。")
            return False

        try:
            import shioaji as sj
            self.api = sj.Shioaji(simulation=self.simulation)
            self.api.login(api_key=api_key, secret_key=secret_key)

            if ca_base64 and ca_passwd:
                ca_path = "/tmp/Sinopac.pfx"
                with open(ca_path, "wb") as f:
                    f.write(base64.b64decode(ca_base64))
                self.api.activate_ca(ca_path=ca_path, ca_passwd=ca_passwd, person_id="")

            self.is_logged_in = True
            print("-> 【Shioaji 實盤模式】永豐金 API 登入與憑證載入成功！")
            return True
        except Exception as e:
            print(f"-> 【自動降級沙盒】永豐金連線異常 ({e})，切換為 Paper Trading 模擬模式。")
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
            order = self.api.Order(
                price=price,
                quantity=quantity,
                action=sj.constant.Action.Buy if action == "BUY" else sj.constant.Action.Sell,
                price_type=sj.constant.StockPriceType.LMT,
                order_type=sj.constant.OrderType.ROD,
                order_lot=sj.constant.TFTStockOrderLot.IntradayOdd,
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
