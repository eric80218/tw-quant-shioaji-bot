import os
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
                self.api.activate_ca(
                    ca_path=ca_path,
                    ca_passwd=ca_password,
                    person_id=os.getenv("SHIOAJI_PERSON_ID", "")
                )
                if os.path.exists(ca_path):
                    os.remove(ca_path)
            self.is_logged_in = True
            print("【Shioaji】永豐金 API 登入與憑證授權成功！")
            return True
        except Exception as e:
            self.is_logged_in = False
            print(f"【Shioaji 登入異常】{str(e)}，自動降級為 AI 模擬模式。")
            return False

    def get_actual_positions(self) -> dict:
        """
        向永豐金查詢真實證券庫存 (用於每日啟動自動對帳，剔除昨日盤中零股未成交的幽靈部位)
        回傳格式: {"2330": 13, "2317": 60}
        """
        if not self.is_logged_in:
            return None
        try:
            positions = self.api.list_positions(self.api.stock_account)
            actual_dict = {}
            for p in positions:
                code = str(getattr(p, "code", "")).strip()
                qty = int(getattr(p, "quantity", 0))
                if code and qty > 0:
                    actual_dict[code] = qty
            return actual_dict
        except Exception as e:
            print(f"【對帳查詢略過】無法取得永豐實盤庫存 ({e})，維持本地帳本。")
            return None

    def place_limit_order(self, symbol: str, action: str, price: float, quantity: int):
        if not self.is_logged_in:
            raise ConnectionError("【錯誤】API 尚未登入")
        contract = self.api.Contracts.Stocks[symbol]
        order_action = sj.constant.Action.Buy if action == "BUY" else sj.constant.Action.Sell

        # 若數量小於 1000 股，自動指定為盤中零股 (IntradayOdd) 委託
        order_lot = (
            sj.constant.TFTStockOrderLot.IntradayOdd
            if quantity < 1000
            else sj.constant.TFTStockOrderLot.Common
        )

        order = self.api.Order(
            action=order_action,
            price=price,
            quantity=quantity,
            price_type=sj.constant.StockPriceType.LMT,
            order_type=sj.constant.OrderType.ROD,
            order_lot=order_lot,
            account=self.api.stock_account
        )
        return self.api.place_order(contract, order)

    def logout(self):
        if self.is_logged_in:
            self.api.logout()
