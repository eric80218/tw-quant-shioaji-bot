import os
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
        "is_live": is_live,
        "daily_order_count": risk_mgr.daily_state["order_count"],
        "max_daily_orders": risk_mgr.max_daily_orders,
        "nav": round(dynamic_nav, 0),
        "realized_pnl": round(risk_mgr.daily_state.get("realized_pnl", 0.0), 0),
        "available_cash": round(effective_cash, 0),
        "invested_cost": round(risk_mgr.daily_state.get("invested_cost", 0.0), 0),
        "single_slot_limit": risk_mgr.max_single_position,
        "max_slots": risk_mgr.max_slots,
        "positions": risk_mgr.daily_state.get("positions", {}),
        "latest_signal": last_signal
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

    # 執行「持倉 14D ATR 棘輪停損檢查 + 20強右側買點掃描」
    order_intent = strategy.evaluate_portfolio_and_scan(risk_mgr=risk_mgr, available_cash=effective_cash)

    if not order_intent:
        export_war_room_json(risk_mgr, actual_bank_balance, is_live_mode, "持倉棘輪安全 ‧ 無新增買賣訊號")
        broker.logout()
        return

    is_safe, fuse_message = risk_mgr.validate_order(order_intent, actual_bank_balance=actual_bank_balance)
    action_label = "買進" if order_intent["side"] == "BUY" else "賣出"

    if is_safe:
        if is_live_mode:
            broker.place_limit_order(
                symbol=order_intent["symbol"],
                action=order_intent["side"],
                price=order_intent["price"],
                quantity=order_intent["shares"]
            )
        risk_mgr.record_order_success(order_intent)
        signal_desc = f"{order_intent['symbol']} {action_label} {order_intent['shares']}股 ({order_intent.get('reason', '')})"
    else:
        signal_desc = f"攔截 {order_intent['symbol']} {action_label}: {fuse_message}"

    export_war_room_json(risk_mgr, actual_bank_balance, is_live_mode, signal_desc)
    notifier.send_execution_report(order_intent, is_safe, fuse_message, is_live_mode, risk_mgr, actual_bank_balance)
    broker.logout()


if __name__ == "__main__":
    run_trading_pipeline()
