import os
import json
from datetime import datetime, timedelta, timezone
from src.risk_management import RiskManagement
from src.broker_shioaji import ShioajiBroker
from src.line_notifier import LineNotifier
from src.strategy_6d import Strategy6D

TAIWAN_TZ = timezone(timedelta(hours=8))


def reconcile_with_broker(risk_mgr, broker, is_live_mode: bool):
    """
    每日實盤庫存自動對帳：若在實盤模式下，比對永豐金真實庫存與 state_machine.json
    自動清除昨日盤中零股未撮合成交的幽靈部位并釋放現金額度
    """
    if not is_live_mode:
        return
    actual_pos = broker.get_actual_positions()
    if actual_pos is None:
        return

    local_pos = risk_mgr.daily_state.get("positions", {})
    modified = False

    for sym in list(local_pos.keys()):
        if sym not in actual_pos:
            ghost = local_pos.pop(sym)
            ghost_cost = round(ghost["entry_price"] * ghost["shares"] * 1.001425, 0)
            risk_mgr.daily_state["invested_cost"] = max(0.0, risk_mgr.daily_state.get("invested_cost", 0.0) - ghost_cost)
            print(f"-> 【實盤自動對帳】發現 {sym} 昨日未成交，已自動剔除幽靈部位並釋放額度 NT$ {ghost_cost:,.0f}")
            modified = True
        elif actual_pos[sym] != local_pos[sym]["shares"]:
            local_pos[sym]["shares"] = actual_pos[sym]
            modified = True

    if modified:
        risk_mgr.save_state()


def export_war_room_json(risk_mgr, strategy, actual_bank_balance=300000.0, is_live=False, last_signal="無強勢訊號"):
    os.makedirs("docs", exist_ok=True)
    dynamic_nav = risk_mgr.max_capital_cap + risk_mgr.daily_state.get("realized_pnl", 0.0)
    effective_cash = risk_mgr.get_effective_Buying_power(actual_bank_balance)

    payload = {
        "last_updated": datetime.now(TAIWAN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "is_live": is_live,
        "market_regime": getattr(strategy, "market_regime", "BULL (正常)"),
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

    # 實盤模式下先執行永豐金庫存對帳
    reconcile_with_broker(risk_mgr, broker, is_live_mode)

    effective_cash = risk_mgr.get_effective_Buying_power(actual_bank_balance)
    order_intent = strategy.evaluate_portfolio_and_scan(risk_mgr=risk_mgr, available_cash=effective_cash)

    if not order_intent:
        export_war_room_json(risk_mgr, strategy, actual_bank_balance, is_live_mode, "持倉棘輪安全 ‧ 無新增買賣訊號")
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
        signal_desc = f"{order_intent['symbol']} {action_label} {order_intent['shares']}股 @ {order_intent['price']}元 ({order_intent.get('reason', '')})"
    else:
        signal_desc = f"攔截 {order_intent['symbol']} {action_label}: {fuse_message}"

    export_war_room_json(risk_mgr, strategy, actual_bank_balance, is_live_mode, signal_desc)
    notifier.send_execution_report(order_intent, is_safe, fuse_message, is_live_mode, risk_mgr, actual_bank_balance)
    broker.logout()


if __name__ == "__main__":
    run_trading_pipeline()
