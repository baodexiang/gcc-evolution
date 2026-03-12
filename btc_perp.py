"""
BTC永续合约交易模块 (GCC-0256 S5)
版本: v1.0

策略:
  BUY信号 → 开多 (LONG) BTC-PERP-INTX, 5x杠杆
  SELL信号 → 开空 (SHORT) BTC-PERP-INTX, 5x杠杆

卖出规则 (自动平仓, 优先级从高到低):
  1. 止损: 亏损 ≥ 保证金30% ($300) — BTC反向6%, 及时止损
  2. 止盈: 盈利 ≥ 保证金50% ($500) — BTC同向10%
  3. 追踪止损: 盈利>$200后激活, 从最高盈利回撤40%平仓
  4. 超时强平: 持仓超72小时 — 限制funding rate累积
  5. 信号反转: Vision方向反转 → 先平仓(下轮再开)

资金控制:
  - 保证金严格 ≤ $1000
  - 杠杆 5x → 名义持仓 $5000
  - 同时最多1个持仓
  - 持仓状态持久化到 state/btc_perp_position.json

依赖:
  - coinbase_sync_v6.py (api_request, get_order, cancel_order)
"""

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("btc_perp")

_position_lock = threading.Lock()

# ── 配置 ─────────────────────────────────────────────────────────────────
BUDGET = 1000           # 保证金 (USDC)
LEVERAGE = 5            # 杠杆倍数 (Coinbase max 10x, 用户限制5x)
PRODUCT_ID = "BTC-PERP-INTX"
MARGIN_TYPE = "CROSS"

# 卖出策略参数
TAKE_PROFIT_PCT = 0.50  # 止盈: 保证金的50% ($500) — BTC涨/跌10%
STOP_LOSS_PCT = 0.30    # 止损: 保证金的30% ($300) — BTC反向6%，及时止损

# 追踪止损 (Trailing Stop)
TRAILING_ACTIVATE_PCT = 0.20  # 盈利达保证金20%($200)后激活追踪
TRAILING_PULLBACK_PCT = 0.40  # 从最高盈利回撤40%就平仓

# 最大持仓时间 (限制funding rate累积)
MAX_HOLD_HOURS = 72     # 最长持仓72小时，超时强平

# 持仓状态文件
STATE_FILE = Path(__file__).parent / "state" / "btc_perp_position.json"


# ── 持仓管理 ─────────────────────────────────────────────────────────────

def _load_position(include_pending: bool = False) -> Optional[dict]:
    """加载当前持仓 (线程安全)"""
    with _position_lock:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if data.get("status") == "open":
                    return data
                if include_pending and data.get("status") == "pending_close":
                    return data
            except Exception:
                pass
        return None


def _save_position(position: dict):
    """保存持仓状态 (线程安全)"""
    with _position_lock:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(position, indent=2, ensure_ascii=False), encoding="utf-8")


def _clear_position():
    """清除持仓 (平仓后, 线程安全)"""
    with _position_lock:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if data.get("status") in ("open", "pending_close"):
                    data["status"] = "closed"
                    data["closed_at"] = datetime.now().isoformat()
                    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass


def _mark_pending_close(close_order_id: str):
    """标记持仓为pending_close"""
    with _position_lock:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                data["status"] = "pending_close"
                data["close_order_id"] = close_order_id
                data["close_submitted_at"] = datetime.now().isoformat()
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass


def check_pending_close() -> Optional[str]:
    """检查pending_close订单是否已FILLED

    Returns:
        None = 无pending, "FILLED" = 已成交, "PENDING" = 等待中, "FAILED" = 失败需重试
    """
    with _position_lock:
        if not STATE_FILE.exists():
            return None
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None

    if data.get("status") != "pending_close":
        return None

    close_order_id = data.get("close_order_id", "")
    if not close_order_id:
        _clear_position()
        return "FILLED"

    try:
        from coinbase_sync_v6 import get_order
        order_data = get_order(close_order_id)
        if not order_data:
            return "PENDING"

        # Coinbase order status in nested structure
        order_info = order_data.get("order", order_data)
        status = order_info.get("status", "")

        if status in ("FILLED", "COMPLETED"):
            _clear_position()
            logger.info(f"[BTC_PERP] 平仓订单{close_order_id}已FILLED")
            return "FILLED"
        elif status in ("CANCELLED", "CANCELED", "REJECTED", "EXPIRED", "FAILED"):
            with _position_lock:
                data["status"] = "open"
                data.pop("close_order_id", None)
                data.pop("close_submitted_at", None)
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.warning(f"[BTC_PERP] 平仓订单{close_order_id}状态={status}，恢复open")
            return "FAILED"
        else:
            # 超过10分钟取消重试
            submitted = data.get("close_submitted_at", "")
            if submitted:
                elapsed = (datetime.now() - datetime.fromisoformat(submitted)).total_seconds()
                if elapsed > 600:
                    try:
                        from coinbase_sync_v6 import cancel_order
                        cancel_order(close_order_id)
                        logger.warning(f"[BTC_PERP] 平仓订单{close_order_id}超时10min，已取消")
                    except Exception:
                        pass
                    with _position_lock:
                        data["status"] = "open"
                        data.pop("close_order_id", None)
                        data.pop("close_submitted_at", None)
                        STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    return "FAILED"
            return "PENDING"
    except Exception as e:
        logger.error(f"[BTC_PERP] 查询平仓订单异常: {e}")
        return "PENDING"


# ── 价格与余额 ──────────────────────────────────────────────────────────

def get_btc_price() -> Optional[float]:
    """获取BTC永续合约当前价格"""
    try:
        from coinbase_sync_v6 import api_request
        data = api_request("GET", f"/api/v3/brokerage/products/{PRODUCT_ID}")
        if data:
            price = float(data.get("price", 0) or 0)
            if price > 0:
                return price
    except Exception as e:
        logger.error(f"[BTC_PERP] 获取价格失败: {e}")
    return None


def get_perp_balance() -> float:
    """获取永续合约可用保证金"""
    try:
        from coinbase_sync_v6 import api_request
        # 永续专用portfolio接口
        data = api_request("GET", "/api/v3/brokerage/intx/portfolio")
        if data:
            summary = data.get("portfolio_summary", data)
            available = float(summary.get("available_margin",
                            summary.get("total_balance", 0)) or 0)
            if available > 0:
                return available

        # 回退: 查USDC账户余额
        data = api_request("GET", "/api/v3/brokerage/accounts")
        if data and "accounts" in data:
            for acct in data["accounts"]:
                if acct.get("currency") == "USDC":
                    return float(acct.get("available_balance", {}).get("value", 0) or 0)
    except Exception as e:
        logger.error(f"[BTC_PERP] 获取余额失败: {e}")
    return 0


# ── 开仓 ─────────────────────────────────────────────────────────────────

def open_position(direction: str, dry_run: bool = True) -> dict:
    """开仓: BUY=做多, SELL=做空

    保证金$1000, 5x杠杆, 名义持仓$5000
    """
    price = get_btc_price()
    if not price or price <= 0:
        return {"success": False, "error": "无法获取BTC价格"}

    notional = BUDGET * LEVERAGE
    base_size = round(notional / price, 8)

    logger.info(
        f"[BTC_PERP] {direction} price=${price:.0f} margin=${BUDGET} "
        f"leverage={LEVERAGE}x notional=${notional:.0f} size={base_size:.8f}BTC"
    )

    if dry_run:
        return {"success": True, "dry_run": True, "direction": direction,
                "price": price, "size": base_size, "notional": notional}

    # 资金检查
    balance = get_perp_balance()
    if balance < BUDGET:
        msg = f"可用保证金${balance:.0f} < 需要${BUDGET}，跳过"
        logger.warning(f"[BTC_PERP] {msg}")
        return {"success": False, "error": msg}
    logger.info(f"[BTC_PERP] 资金检查通过: 可用${balance:.0f}")

    try:
        from coinbase_sync_v6 import api_request

        payload = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": PRODUCT_ID,
            "side": direction,
            "order_configuration": {
                "market_market_ioc": {
                    "base_size": str(base_size),
                }
            },
            "leverage": str(LEVERAGE),
            "margin_type": MARGIN_TYPE,
        }

        result = api_request("POST", "/api/v3/brokerage/orders", body=payload)
        if result:
            order_id = (result.get("order_id") or
                        result.get("success_response", {}).get("order_id", ""))
            logger.info(f"[BTC_PERP] PLACED {direction} size={base_size:.8f} order_id={order_id}")

            _save_position({
                "status": "open",
                "order_id": order_id,
                "direction": direction,
                "entry_price": price,
                "size": base_size,
                "margin": BUDGET,
                "leverage": LEVERAGE,
                "notional": notional,
                "peak_pnl": 0,
                "opened_at": datetime.now().isoformat(),
            })

            return {"success": True, "order_id": order_id, "direction": direction,
                    "price": price, "size": base_size}

        return {"success": False, "error": "API请求失败"}
    except Exception as e:
        logger.error(f"[BTC_PERP] 开仓异常: {e}")
        return {"success": False, "error": str(e)}


# ── 平仓 ─────────────────────────────────────────────────────────────────

def close_position(dry_run: bool = True) -> dict:
    """平仓: 反向市价单, 全部平掉"""
    position = _load_position()
    if not position:
        return {"success": False, "error": "无持仓"}

    direction = position["direction"]
    size = position["size"]
    close_side = "SELL" if direction == "BUY" else "BUY"

    logger.info(f"[BTC_PERP] 平仓 {close_side} size={size:.8f}")

    if dry_run:
        return {"success": True, "dry_run": True, "close_side": close_side, "size": size}

    try:
        from coinbase_sync_v6 import api_request

        payload = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": PRODUCT_ID,
            "side": close_side,
            "order_configuration": {
                "market_market_ioc": {
                    "base_size": str(size),
                }
            },
            "leverage": str(LEVERAGE),
            "margin_type": MARGIN_TYPE,
        }

        result = api_request("POST", "/api/v3/brokerage/orders", body=payload)
        if result:
            order_id = (result.get("order_id") or
                        result.get("success_response", {}).get("order_id", ""))
            _mark_pending_close(order_id)
            logger.info(f"[BTC_PERP] CLOSE SUBMITTED {close_side} size={size:.8f} order_id={order_id}")
            return {"success": True, "order_id": order_id}

        return {"success": False, "error": "API请求失败"}
    except Exception as e:
        logger.error(f"[BTC_PERP] 平仓异常: {e}")
        return {"success": False, "error": str(e)}


# ── 止盈止损 ─────────────────────────────────────────────────────────────

def check_exit_rules() -> Optional[dict]:
    """检查退出规则 (优先级: 止损 > 止盈 > 追踪止损 > 超时)

    同时更新peak_pnl用于追踪止损
    """
    position = _load_position()
    if not position:
        return None

    price = get_btc_price()
    if not price:
        logger.warning("[BTC_PERP] 无法获取价格，跳过检查")
        return None

    entry_price = position["entry_price"]
    size = position["size"]
    direction = position["direction"]
    margin = position["margin"]

    # 未实现盈亏
    if direction == "BUY":
        pnl = (price - entry_price) * size
    else:
        pnl = (entry_price - price) * size

    # 更新peak_pnl (追踪止损用)
    peak_pnl = position.get("peak_pnl", 0)
    if pnl > peak_pnl:
        peak_pnl = pnl
        with _position_lock:
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                data["peak_pnl"] = round(peak_pnl, 2)
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    # 1. 止损: 亏损 ≥ 保证金 × STOP_LOSS_PCT (最高优先级)
    sl_amount = margin * STOP_LOSS_PCT
    if pnl <= -sl_amount:
        return {
            "action": "STOP_LOSS",
            "reason": f"亏损${abs(pnl):.0f} ≥ 止损${sl_amount:.0f} (保证金{STOP_LOSS_PCT*100:.0f}%)",
            "pnl": round(pnl, 2),
            "current_price": price,
        }

    # 2. 止盈: 盈利 ≥ 保证金 × TAKE_PROFIT_PCT
    tp_amount = margin * TAKE_PROFIT_PCT
    if pnl >= tp_amount:
        return {
            "action": "TAKE_PROFIT",
            "reason": f"盈利${pnl:.0f} ≥ 止盈${tp_amount:.0f} (保证金{TAKE_PROFIT_PCT*100:.0f}%)",
            "pnl": round(pnl, 2),
            "current_price": price,
        }

    # 3. 追踪止损: 盈利曾达$200+, 从最高点回撤40%
    trailing_activate = margin * TRAILING_ACTIVATE_PCT
    if peak_pnl >= trailing_activate and pnl > 0:
        pullback = peak_pnl - pnl
        pullback_pct = pullback / peak_pnl if peak_pnl > 0 else 0
        if pullback_pct >= TRAILING_PULLBACK_PCT:
            return {
                "action": "TRAILING_STOP",
                "reason": (f"追踪止损: 最高盈利${peak_pnl:.0f} → 当前${pnl:.0f} "
                           f"回撤{pullback_pct*100:.0f}% ≥ {TRAILING_PULLBACK_PCT*100:.0f}%"),
                "pnl": round(pnl, 2),
                "current_price": price,
            }

    # 4. 超时强平: 持仓超MAX_HOLD_HOURS
    opened_at = position.get("opened_at", "")
    if opened_at:
        try:
            hold_hours = (datetime.now() - datetime.fromisoformat(opened_at)).total_seconds() / 3600
            if hold_hours >= MAX_HOLD_HOURS:
                return {
                    "action": "TIME_EXIT",
                    "reason": f"持仓{hold_hours:.0f}小时 ≥ 上限{MAX_HOLD_HOURS}小时 (限制funding累积)",
                    "pnl": round(pnl, 2),
                    "current_price": price,
                }
        except Exception:
            pass

    return None


def auto_manage(dry_run: bool = True) -> Optional[dict]:
    """自动管理: 检查止盈止损 → 平仓"""
    exit_signal = check_exit_rules()
    if not exit_signal:
        return None

    action = exit_signal["action"]
    logger.info(
        f"[BTC_PERP] 触发{action}: {exit_signal['reason']} PnL=${exit_signal['pnl']:.0f}"
    )

    result = close_position(dry_run=dry_run)
    return {
        "action": action,
        "reason": exit_signal["reason"],
        "pnl": exit_signal["pnl"],
        "result": result,
    }


# ── 完整执行流 ───────────────────────────────────────────────────────────

def execute_signal(direction: str, dry_run: bool = True) -> dict:
    """完整执行: 检查持仓 → 反向则平 → 开仓"""
    logger.info(f"[BTC_PERP] 收到{direction}信号, dry_run={dry_run}")

    position = _load_position()
    if position:
        existing_dir = position["direction"]
        if direction == existing_dir:
            logger.info(f"[BTC_PERP] 已有同向持仓 {existing_dir}，跳过")
            return {"success": True, "action": "HOLD", "reason": "已有同向持仓"}

        # 反向: 只平仓, 不立即开新仓
        logger.info(f"[BTC_PERP] 信号反转 {existing_dir} → {direction}，平仓等确认")
        close_result = close_position(dry_run=dry_run)
        if not close_result.get("success") and not dry_run:
            return {"success": False, "error": "平仓失败", "close_result": close_result}
        return {"success": True, "action": "REVERSAL_CLOSE",
                "reason": f"反转平仓 {existing_dir}→{direction}，等确认后再开新仓"}

    return open_position(direction, dry_run=dry_run)


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "status":
        pos = _load_position()
        if pos:
            price = get_btc_price()
            entry = pos["entry_price"]
            d = pos["direction"]
            size = pos["size"]
            margin = pos["margin"]
            if price:
                pnl = (price - entry) * size if d == "BUY" else (entry - price) * size
                pnl_pct = pnl / margin * 100
                peak = pos.get("peak_pnl", 0)
                print(f"持仓: {d} {size:.8f} BTC @ ${entry:,.0f}")
                print(f"当前: ${price:,.0f} → PnL: ${pnl:,.0f} ({pnl_pct:+.1f}%保证金)")
                print(f"保证金: ${margin} x{pos['leverage']}")
                print(f"最高盈利: ${peak:,.0f}")
                opened = pos.get("opened_at", "")
                if opened:
                    hours = (datetime.now() - datetime.fromisoformat(opened)).total_seconds() / 3600
                    print(f"持仓时长: {hours:.1f}h / {MAX_HOLD_HOURS}h上限")
                print(f"退出规则: 止损{STOP_LOSS_PCT*100:.0f}% | 止盈{TAKE_PROFIT_PCT*100:.0f}% | "
                      f"追踪{TRAILING_PULLBACK_PCT*100:.0f}%回撤 | {MAX_HOLD_HOURS}h超时")
        else:
            print("无持仓")

    elif action == "price":
        p = get_btc_price()
        print(f"BTC = ${p:,.0f}" if p else "获取价格失败")

    elif action == "balance":
        b = get_perp_balance()
        print(f"可用保证金: ${b:,.0f}")

    elif action in ("buy", "sell"):
        d = "BUY" if action == "buy" else "SELL"
        result = execute_signal(d, dry_run=True)
        print(json.dumps(result, indent=2, default=str))

    elif action in ("buy-live", "sell-live"):
        d = "BUY" if "buy" in action else "SELL"
        print(f"⚠️  即将实盘 {d} BTC永续 (保证金${BUDGET}, {LEVERAGE}x杠杆)!")
        confirm = input("确认? (yes/no): ")
        if confirm.lower() == "yes":
            result = execute_signal(d, dry_run=False)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("已取消")

    elif action == "check":
        exit_signal = check_exit_rules()
        if exit_signal:
            print(f"触发: {exit_signal['action']}")
            print(f"原因: {exit_signal['reason']}")
            print(f"PnL: ${exit_signal['pnl']:.0f}")
        else:
            pos = _load_position()
            print("持仓正常" if pos else "无持仓")

    elif action == "close-live":
        pos = _load_position()
        if not pos:
            print("无持仓")
        else:
            print(f"⚠️  即将平仓 {pos['direction']}!")
            confirm = input("确认? (yes/no): ")
            if confirm.lower() == "yes":
                result = close_position(dry_run=False)
                print(json.dumps(result, indent=2, default=str))

    else:
        print("用法: python btc_perp.py <command>")
        print("  status     查看持仓")
        print("  price      BTC价格")
        print("  balance    可用保证金")
        print("  buy/sell   干跑测试")
        print("  buy-live   实盘开多 (需确认)")
        print("  sell-live  实盘开空 (需确认)")
        print("  check      检查止盈止损")
        print("  close-live 手动平仓 (需确认)")
