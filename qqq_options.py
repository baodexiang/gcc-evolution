"""
QQQ期权垂直价差交易模块 (GCC-0256 S4)
版本: v2.0

策略:
  BUY信号 → Bull Call Spread (买低Call + 卖高Call)
  SELL信号 → Bear Put Spread (买高Put + 卖低Put)

卖出规则 (自动平仓, 优先级从高到低):
  1. 时间止损: DTE ≤ 1天 → 到期前强制平仓
  2. 止损: spread价值跌到成本50%以下 → 市价平仓
  3. 止盈: 盈利达最大盈利50% → 限价平仓
  4. 追踪止损: 盈利达最大盈利25%后激活, 从最高回撤40%平仓
  5. 信号反转: Vision方向反转 → 先平旧仓(下轮再开)

资金控制:
  - 严格 ≤ $1000/笔，向下取整
  - 同时最多1个持仓 (避免资金分散)
  - 持仓状态持久化到 state/qqq_options_position.json

依赖:
  - schwab_data_provider.py
  - schwab-py SDK
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("qqq_options")

# 线程锁: 防止后台线程和主线程同时操作持仓文件
_position_lock = threading.Lock()

# ── 配置 ─────────────────────────────────────────────────────────────────
BUDGET = 1000           # 每次交易预算 (USD)，严格不超
SPREAD_WIDTH = 5        # 价差宽度 ($5)
MIN_DTE = 7             # 最短到期天数
MAX_DTE = 14            # 最长到期天数
TARGET_DELTA = 0.50     # 目标delta (ATM)
MAX_CONTRACTS = 5       # 单次最大合约数
SYMBOL = "TSLA"         # 标的

# 卖出策略参数
TAKE_PROFIT_PCT = 0.50  # 止盈: 达到最大盈利的50%平仓
STOP_LOSS_PCT = 0.50    # 止损: 亏损成本的50%平仓
EXIT_DTE = 1            # 时间止损: 到期前1天平仓

# 追踪止损 (Trailing Stop)
TRAILING_ACTIVATE_PCT = 0.25  # 盈利达最大盈利25%后激活追踪
TRAILING_PULLBACK_PCT = 0.40  # 从最高价值回撤40%就平仓

# 持仓状态文件
STATE_FILE = Path(__file__).parent / "state" / "tsla_options_position.json"


# ── 持仓管理 ─────────────────────────────────────────────────────────────

def _load_position(include_pending: bool = False) -> Optional[dict]:
    """加载当前持仓 (线程安全)

    Args:
        include_pending: True=包含pending_close状态的仓, False=只返回open状态
    """
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
    """标记持仓为pending_close, 等确认FILLED后再清除"""
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
    """检查pending_close订单是否已FILLED, 返回状态

    Returns:
        None = 无pending, "FILLED" = 已成交已清除, "PENDING" = 还在等, "FAILED" = 失败需重试
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
        from schwab_data_provider import get_provider
        provider = get_provider()
        client = provider._get_client()
        account_hash = provider._get_account_hash()
        resp = client.get_order(int(close_order_id), account_hash)
        if resp.status_code == 200:
            order_data = resp.json()
            status = order_data.get("status", "")
            if status == "FILLED":
                _clear_position()
                logger.info(f"[QQQ_OPT] 平仓订单{close_order_id}已FILLED，持仓已清除")
                return "FILLED"
            elif status in ("CANCELED", "REJECTED", "EXPIRED"):
                # 平仓失败，恢复为open状态让auto_manage重试
                with _position_lock:
                    data["status"] = "open"
                    del data["close_order_id"]
                    del data["close_submitted_at"]
                    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.warning(f"[QQQ_OPT] 平仓订单{close_order_id}状态={status}，恢复为open重试")
                return "FAILED"
            else:
                # PENDING/WORKING/QUEUED等
                # 超过10分钟还没成交就取消重试
                submitted = data.get("close_submitted_at", "")
                if submitted:
                    elapsed = (datetime.now() - datetime.fromisoformat(submitted)).total_seconds()
                    if elapsed > 600:
                        try:
                            client.cancel_order(int(close_order_id), account_hash)
                            logger.warning(f"[QQQ_OPT] 平仓订单{close_order_id}超时10min，已取消")
                        except Exception:
                            pass
                        with _position_lock:
                            data["status"] = "open"
                            if "close_order_id" in data:
                                del data["close_order_id"]
                            if "close_submitted_at" in data:
                                del data["close_submitted_at"]
                            STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                        return "FAILED"
                return "PENDING"
    except Exception as e:
        logger.error(f"[QQQ_OPT] 查询平仓订单{close_order_id}异常: {e}")
        return "PENDING"


# ── Schwab客户端 ─────────────────────────────────────────────────────────

def _get_schwab_client():
    """获取schwab client和account_hash"""
    from schwab_data_provider import get_provider
    provider = get_provider()
    client = provider._get_client()
    account_hash = provider._get_account_hash()
    return client, account_hash


# ── 期权链 ───────────────────────────────────────────────────────────────

def get_option_chain(client=None) -> dict:
    """获取QQQ期权链 (MIN_DTE ~ MAX_DTE, ATM附近)"""
    if client is None:
        client, _ = _get_schwab_client()

    from_date = datetime.now() + timedelta(days=MIN_DTE - 2)
    to_date = datetime.now() + timedelta(days=MAX_DTE + 2)

    resp = client.get_option_chain(
        SYMBOL,
        contract_type=client.Options.ContractType.ALL,
        strike_count=20,
        include_underlying_quote=True,
        from_date=from_date,
        to_date=to_date,
    )

    if resp.status_code != 200:
        logger.error(f"[QQQ_OPT] get_option_chain失败: HTTP {resp.status_code}")
        return {}

    data = resp.json()
    price = data.get("underlying", {}).get("last", 0)
    call_map = data.get("callExpDateMap", {})
    put_map = data.get("putExpDateMap", {})

    expirations = []
    for exp_key in sorted(call_map.keys()):
        parts = exp_key.split(":")
        exp_date = parts[0]
        dte = int(parts[1]) if len(parts) > 1 else 0
        if dte < MIN_DTE or dte > MAX_DTE:
            continue

        calls = {}
        for strike_str, opts in call_map[exp_key].items():
            opt = opts[0]
            calls[float(strike_str)] = {
                "symbol": opt.get("symbol", ""),
                "bid": opt.get("bid", 0),
                "ask": opt.get("ask", 0),
                "last": opt.get("last", 0),
                "delta": opt.get("delta", 0),
                "volume": opt.get("totalVolume", 0),
                "oi": opt.get("openInterest", 0),
            }

        puts = {}
        for strike_str, opts in put_map.get(exp_key, {}).items():
            opt = opts[0]
            puts[float(strike_str)] = {
                "symbol": opt.get("symbol", ""),
                "bid": opt.get("bid", 0),
                "ask": opt.get("ask", 0),
                "last": opt.get("last", 0),
                "delta": opt.get("delta", 0),
                "volume": opt.get("totalVolume", 0),
                "oi": opt.get("openInterest", 0),
            }

        expirations.append({"date": exp_date, "dte": dte, "calls": calls, "puts": puts})

    return {"underlying_price": price, "expirations": expirations}


# ── Spread选择 ───────────────────────────────────────────────────────────

def select_spread(direction: str, chain: dict = None) -> Optional[dict]:
    """
    选择ATM附近最优spread，严格控制总成本 ≤ BUDGET
    偏好: delta接近0.50 (ATM) > 盈亏比 > 短DTE
    """
    if chain is None:
        chain = get_option_chain()

    if not chain or not chain.get("expirations"):
        logger.error("[QQQ_OPT] 无可用期权链")
        return None

    price = chain["underlying_price"]
    best = None
    best_score = -1

    for exp in chain["expirations"]:
        dte = exp["dte"]
        calls = exp["calls"]
        puts = exp["puts"]

        if direction == "BUY":
            for strike in sorted(calls.keys()):
                short_strike = strike + SPREAD_WIDTH
                if short_strike not in calls:
                    continue
                c_long = calls[strike]
                c_short = calls[short_strike]

                if abs(c_long["delta"] - TARGET_DELTA) > 0.12:
                    continue
                if c_long["ask"] <= 0 or c_short["bid"] <= 0:
                    continue

                cost = round(c_long["ask"] - c_short["bid"], 2)
                if cost <= 0:
                    continue

                max_profit = SPREAD_WIDTH - cost
                contracts = min(int(BUDGET / (cost * 100)), MAX_CONTRACTS)
                total_cost = cost * 100 * contracts
                if contracts < 1 or total_cost > BUDGET:
                    continue

                rr = max_profit / cost
                # 偏好ATM (delta权重高)
                score = (1 - abs(c_long["delta"] - 0.50)) * 0.5 + rr * 0.3 + (1 / max(dte, 1)) * 0.2

                if score > best_score:
                    best_score = score
                    best = {
                        "type": "BULL_CALL",
                        "expiration": exp["date"],
                        "dte": dte,
                        "long_strike": strike,
                        "short_strike": short_strike,
                        "long_symbol": c_long["symbol"],
                        "short_symbol": c_short["symbol"],
                        "long_delta": round(c_long["delta"], 3),
                        "short_delta": round(c_short["delta"], 3),
                        "cost_per_contract": cost,
                        "max_profit_per_contract": round(max_profit, 2),
                        "risk_reward": round(rr, 2),
                        "contracts": contracts,
                        "total_cost": round(total_cost, 2),
                        "total_max_profit": round(max_profit * 100 * contracts, 2),
                    }

        elif direction == "SELL":
            for strike in sorted(puts.keys(), reverse=True):
                short_strike = strike - SPREAD_WIDTH
                if short_strike not in puts:
                    continue
                p_long = puts[strike]
                p_short = puts[short_strike]

                if abs(abs(p_long["delta"]) - TARGET_DELTA) > 0.12:
                    continue
                if p_long["ask"] <= 0 or p_short["bid"] <= 0:
                    continue

                cost = round(p_long["ask"] - p_short["bid"], 2)
                if cost <= 0:
                    continue

                max_profit = SPREAD_WIDTH - cost
                contracts = min(int(BUDGET / (cost * 100)), MAX_CONTRACTS)
                total_cost = cost * 100 * contracts
                if contracts < 1 or total_cost > BUDGET:
                    continue

                rr = max_profit / cost
                score = (1 - abs(abs(p_long["delta"]) - 0.50)) * 0.5 + rr * 0.3 + (1 / max(dte, 1)) * 0.2

                if score > best_score:
                    best_score = score
                    best = {
                        "type": "BEAR_PUT",
                        "expiration": exp["date"],
                        "dte": dte,
                        "long_strike": strike,
                        "short_strike": short_strike,
                        "long_symbol": p_long["symbol"],
                        "short_symbol": p_short["symbol"],
                        "long_delta": round(p_long["delta"], 3),
                        "short_delta": round(p_short["delta"], 3),
                        "cost_per_contract": cost,
                        "max_profit_per_contract": round(max_profit, 2),
                        "risk_reward": round(rr, 2),
                        "contracts": contracts,
                        "total_cost": round(total_cost, 2),
                        "total_max_profit": round(max_profit * 100 * contracts, 2),
                    }

    return best


# ── 下单 ─────────────────────────────────────────────────────────────────

def place_spread(spread: dict, dry_run: bool = True) -> dict:
    """下单垂直价差"""
    if not spread:
        return {"success": False, "error": "无spread数据"}

    # 最后一道资金检查
    if spread["total_cost"] > BUDGET:
        return {"success": False, "error": f"总成本${spread['total_cost']}超过预算${BUDGET}"}

    # 账户资金检查: 确认可用资金 ≥ $1000 (dry_run跳过)
    if not dry_run:
        try:
            from schwab_data_provider import get_provider as _gp
            bal = _gp().get_account_balance()
            option_bp = bal.get("option_buying_power", 0)
            if option_bp < BUDGET:
                msg = f"账户期权购买力${option_bp:.0f} < 预算${BUDGET}，跳过下单"
                logger.warning(f"[QQQ_OPT] {msg}")
                return {"success": False, "error": msg}
            logger.info(f"[QQQ_OPT] 资金检查通过: option_buying_power=${option_bp:.0f}")
        except Exception as _bal_e:
            logger.error(f"[QQQ_OPT] 资金检查异常: {_bal_e}")
            return {"success": False, "error": f"资金检查失败: {_bal_e}"}

    try:
        from schwab.orders.options import bull_call_vertical_open, bear_put_vertical_open

        client, account_hash = _get_schwab_client()
        spread_type = spread["type"]
        contracts = spread["contracts"]
        cost = spread["cost_per_contract"]

        if spread_type == "BULL_CALL":
            order_spec = bull_call_vertical_open(
                long_call_symbol=spread["long_symbol"],
                short_call_symbol=spread["short_symbol"],
                quantity=contracts, net_debit=str(cost),
            )
            label = f"Bull Call {spread['long_strike']}/{spread['short_strike']}"
        elif spread_type == "BEAR_PUT":
            order_spec = bear_put_vertical_open(
                long_put_symbol=spread["long_symbol"],
                short_put_symbol=spread["short_symbol"],
                quantity=contracts, net_debit=str(cost),
            )
            label = f"Bear Put {spread['long_strike']}/{spread['short_strike']}"
        else:
            return {"success": False, "error": f"未知spread类型: {spread_type}"}

        if dry_run:
            resp = client.preview_order(account_hash, order_spec)
            logger.info(f"[QQQ_OPT] PREVIEW {label} x{contracts} cost=${spread['total_cost']:.0f} → HTTP {resp.status_code}")
            return {"success": resp.status_code == 200, "dry_run": True, "label": label,
                    "status_code": resp.status_code, "spread": spread}

        resp = client.place_order(account_hash, order_spec)
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else ""
            logger.info(f"[QQQ_OPT] PLACED {label} x{contracts} cost=${spread['total_cost']:.0f} order_id={order_id}")

            # 保存持仓
            _save_position({
                "status": "open",
                "order_id": order_id,
                "spread": spread,
                "opened_at": datetime.now().isoformat(),
                "entry_cost": spread["total_cost"],
                "peak_value": spread["cost_per_contract"],  # 追踪止损用
            })

            return {"success": True, "order_id": order_id, "label": label, "spread": spread}
        else:
            error_body = ""
            try:
                error_body = resp.json()
            except Exception:
                error_body = resp.text[:300]
            return {"success": False, "error": f"HTTP {resp.status_code}: {error_body}", "spread": spread}

    except Exception as e:
        logger.error(f"[QQQ_OPT] place_spread异常: {e}")
        return {"success": False, "error": str(e)}


def close_spread(spread: dict, credit: float = None, dry_run: bool = True,
                  market_order: bool = False) -> dict:
    """平仓垂直价差

    Args:
        market_order: True=市价平仓(止损/时间止损用), False=限价平仓(止盈用)
    """
    if not spread:
        return {"success": False, "error": "无spread数据"}

    try:
        from schwab.orders.options import bull_call_vertical_close, bear_put_vertical_close

        client, account_hash = _get_schwab_client()
        spread_type = spread["type"]
        contracts = spread["contracts"]

        if market_order:
            # 市价平仓: credit设为0.01确保立刻成交 (接受最差价格)
            net_credit = "0.01"
        else:
            net_credit = str(credit) if credit else str(spread["cost_per_contract"])

        if spread_type == "BULL_CALL":
            order_spec = bull_call_vertical_close(
                long_call_symbol=spread["long_symbol"],
                short_call_symbol=spread["short_symbol"],
                quantity=contracts, net_credit=net_credit,
            )
            label = f"Close Bull Call {spread['long_strike']}/{spread['short_strike']}"
        elif spread_type == "BEAR_PUT":
            order_spec = bear_put_vertical_close(
                long_put_symbol=spread["long_symbol"],
                short_put_symbol=spread["short_symbol"],
                quantity=contracts, net_credit=net_credit,
            )
            label = f"Close Bear Put {spread['long_strike']}/{spread['short_strike']}"
        else:
            return {"success": False, "error": f"未知类型: {spread_type}"}

        if dry_run:
            resp = client.preview_order(account_hash, order_spec)
            return {"success": resp.status_code == 200, "dry_run": True, "label": label}

        resp = client.place_order(account_hash, order_spec)
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else ""
            # 标记为pending_close, 不立刻清除 — 等确认FILLED后再清
            _mark_pending_close(order_id)
            logger.info(f"[QQQ_OPT] CLOSE SUBMITTED {label} credit=${float(net_credit)*100*contracts:.0f} order_id={order_id}")
            return {"success": True, "order_id": order_id, "label": label}
        else:
            error_body = ""
            try:
                error_body = resp.json()
            except Exception:
                error_body = resp.text[:300]
            return {"success": False, "error": f"HTTP {resp.status_code}: {error_body}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 卖出策略: 持仓监控 ──────────────────────────────────────────────────

def get_spread_current_value(spread: dict) -> Optional[float]:
    """
    查询spread当前市值 (每张)
    Bull Call: long_call_bid - short_call_ask
    Bear Put:  long_put_bid - short_put_ask
    """
    try:
        client, _ = _get_schwab_client()

        # 重新查期权链获取实时报价
        exp_date = datetime.strptime(spread["expiration"], "%Y-%m-%d")
        resp = client.get_option_chain(
            SYMBOL,
            contract_type=client.Options.ContractType.ALL,
            strike_count=20,
            include_underlying_quote=True,
            from_date=exp_date - timedelta(days=1),
            to_date=exp_date + timedelta(days=1),
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        call_map = data.get("callExpDateMap", {})
        put_map = data.get("putExpDateMap", {})

        def _try_strike_key(strike_val, option_map):
            """尝试匹配strike key (兼容 "490.0" 和 "490")"""
            s = str(strike_val)
            if s in option_map:
                return s
            if strike_val == int(strike_val):
                s2 = str(int(strike_val))
                if s2 in option_map:
                    return s2
            return None

        if spread["type"] == "BULL_CALL":
            for exp_key in call_map:
                if not exp_key.startswith(spread["expiration"]):
                    continue
                calls = call_map[exp_key]
                long_s = _try_strike_key(spread["long_strike"], calls)
                short_s = _try_strike_key(spread["short_strike"], calls)
                if long_s and short_s:
                    long_bid = calls[long_s][0].get("bid", 0)
                    short_ask = calls[short_s][0].get("ask", 0)
                    return round(long_bid - short_ask, 2)

        elif spread["type"] == "BEAR_PUT":
            for exp_key in put_map:
                if not exp_key.startswith(spread["expiration"]):
                    continue
                puts = put_map[exp_key]
                long_s = _try_strike_key(spread["long_strike"], puts)
                short_s = _try_strike_key(spread["short_strike"], puts)
                if long_s and short_s:
                    long_bid = puts[long_s][0].get("bid", 0)
                    short_ask = puts[short_s][0].get("ask", 0)
                    return round(long_bid - short_ask, 2)

        return None
    except Exception as e:
        logger.error(f"[QQQ_OPT] 查询spread当前价值失败: {e}")
        return None


def check_exit_rules() -> Optional[dict]:
    """
    检查卖出规则 (优先级: TIME_EXIT > STOP_LOSS > TAKE_PROFIT > TRAILING_STOP)

    同时更新peak_value用于追踪止损

    Returns:
        None = 无持仓或不需要操作
        {"action": str, "reason": str, "current_value": float,
         "credit": float, "pnl": float, "spread": dict}
    """
    position = _load_position()
    if not position:
        return None

    spread = position.get("spread", {})
    entry_cost = spread.get("cost_per_contract", 0)
    max_profit = spread.get("max_profit_per_contract", 0)
    contracts = spread.get("contracts", 0)

    # 1. 时间止损: DTE ≤ EXIT_DTE (最高优先级)
    try:
        exp_date = datetime.strptime(spread["expiration"], "%Y-%m-%d")
        days_left = (exp_date - datetime.now()).days
        if days_left <= EXIT_DTE:
            current_value = get_spread_current_value(spread)
            credit = max(current_value, 0.01) if current_value and current_value > 0 else 0.01
            pnl = (credit - entry_cost) * 100 * contracts
            return {
                "action": "TIME_EXIT",
                "reason": f"到期前{days_left}天，强制平仓",
                "current_value": current_value,
                "credit": credit,
                "pnl": round(pnl, 2),
                "spread": spread,
            }
    except Exception:
        pass

    # 2. 查询当前价值
    current_value = get_spread_current_value(spread)
    if current_value is None:
        logger.warning("[QQQ_OPT] 无法获取当前spread价值，跳过检查")
        return None

    pnl_per_contract = current_value - entry_cost
    pnl_total = pnl_per_contract * 100 * contracts

    # 更新peak_value (追踪止损用)
    peak_value = position.get("peak_value", entry_cost)
    if current_value > peak_value:
        peak_value = current_value
        with _position_lock:
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                data["peak_value"] = round(peak_value, 2)
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    # 3. 止损: 亏损 ≥ 成本的 STOP_LOSS_PCT
    stop_loss_threshold = entry_cost * (1 - STOP_LOSS_PCT)
    if current_value <= stop_loss_threshold:
        credit = max(current_value, 0.01)
        return {
            "action": "STOP_LOSS",
            "reason": f"触发{STOP_LOSS_PCT*100:.0f}%止损 (当前${current_value:.2f} ≤ 阈值${stop_loss_threshold:.2f})",
            "current_value": current_value,
            "credit": credit,
            "pnl": round(pnl_total, 2),
            "spread": spread,
        }

    # 4. 止盈: 盈利 ≥ 最大盈利的 TAKE_PROFIT_PCT
    take_profit_threshold = entry_cost + max_profit * TAKE_PROFIT_PCT
    if current_value >= take_profit_threshold:
        return {
            "action": "TAKE_PROFIT",
            "reason": f"达到{TAKE_PROFIT_PCT*100:.0f}%止盈线 (当前${current_value:.2f} ≥ 目标${take_profit_threshold:.2f})",
            "current_value": current_value,
            "credit": current_value,
            "pnl": round(pnl_total, 2),
            "spread": spread,
        }

    # 5. 追踪止损: 价值曾涨过激活线, 从最高回撤TRAILING_PULLBACK_PCT
    trailing_activate = entry_cost + max_profit * TRAILING_ACTIVATE_PCT
    if peak_value >= trailing_activate and current_value > entry_cost:
        pullback = peak_value - current_value
        pullback_pct = pullback / (peak_value - entry_cost) if peak_value > entry_cost else 0
        if pullback_pct >= TRAILING_PULLBACK_PCT:
            return {
                "action": "TRAILING_STOP",
                "reason": (f"追踪止损: 最高${peak_value:.2f} → 当前${current_value:.2f} "
                           f"回撤{pullback_pct*100:.0f}% ≥ {TRAILING_PULLBACK_PCT*100:.0f}%"),
                "current_value": current_value,
                "credit": current_value,
                "pnl": round(pnl_total, 2),
                "spread": spread,
            }

    return None


def auto_manage(dry_run: bool = True) -> Optional[dict]:
    """
    自动持仓管理: 检查卖出规则 → 执行平仓

    适合定时调用 (如每5分钟)

    Returns:
        None = 无操作
        {"action": str, "result": dict} = 已执行平仓
    """
    exit_signal = check_exit_rules()
    if not exit_signal:
        return None

    action = exit_signal["action"]
    spread = exit_signal["spread"]
    credit = exit_signal.get("credit", 0.01)
    pnl = exit_signal.get("pnl", 0)

    # 止损/时间止损/追踪止损用市价单(必须成交), 止盈用限价单(锁定利润)
    use_market = action in ("STOP_LOSS", "TIME_EXIT", "TRAILING_STOP")

    logger.info(
        f"[QQQ_OPT] 卖出触发: {action} — {exit_signal['reason']} "
        f"PnL=${pnl:.0f} market_order={use_market}"
    )

    result = close_spread(spread, credit=credit, dry_run=dry_run, market_order=use_market)

    return {
        "action": action,
        "reason": exit_signal["reason"],
        "pnl": pnl,
        "result": result,
    }


# ── 完整执行流 ───────────────────────────────────────────────────────────

def execute_signal(direction: str, dry_run: bool = True) -> dict:
    """
    完整执行: 检查持仓 → 反向则先平 → 选spread → 下单

    Args:
        direction: "BUY" 或 "SELL"
        dry_run: True=干跑, False=实盘
    """
    logger.info(f"[QQQ_OPT] 收到{direction}信号, dry_run={dry_run}")

    # 资金检查统一在 place_spread() 内完成，此处不重复

    # 1. 检查现有持仓
    position = _load_position()
    if position:
        existing_type = position["spread"]["type"]
        # 同向: 已有持仓，不重复开
        if (direction == "BUY" and existing_type == "BULL_CALL") or \
           (direction == "SELL" and existing_type == "BEAR_PUT"):
            logger.info(f"[QQQ_OPT] 已有同向持仓 {existing_type}，跳过")
            return {"success": True, "action": "HOLD", "reason": "已有同向持仓"}

        # 反向: 平旧仓, 不立即开新仓 (等pending_close确认后下轮再开)
        logger.info(f"[QQQ_OPT] 信号反转 {existing_type} → {direction}，平仓等确认")
        old_spread = position["spread"]
        close_result = close_spread(old_spread, dry_run=dry_run, market_order=True)
        if not close_result.get("success") and not dry_run:
            logger.error(f"[QQQ_OPT] 平仓失败: {close_result}")
            return {"success": False, "error": "旧仓平仓失败", "close_result": close_result}
        # 旧仓进入pending_close，新仓等下轮开
        return {"success": True, "action": "REVERSAL_CLOSE", "reason": f"反转平仓 {existing_type}→{direction}，等确认后再开新仓"}

    # 2. 获取期权链
    chain = get_option_chain()
    if not chain:
        return {"success": False, "error": "获取期权链失败"}

    # 3. 选择最优spread
    spread = select_spread(direction, chain)
    if not spread:
        return {"success": False, "error": f"无合适的{direction} spread"}

    # 4. 最终资金检查
    if spread["total_cost"] > BUDGET:
        return {"success": False, "error": f"总成本${spread['total_cost']:.0f}超预算${BUDGET}"}

    logger.info(
        f"[QQQ_OPT] 选中: {spread['type']} {spread['long_strike']}/{spread['short_strike']} "
        f"DTE={spread['dte']} x{spread['contracts']} "
        f"cost=${spread['total_cost']:.0f} max_profit=${spread['total_max_profit']:.0f} "
        f"RR={spread['risk_reward']}:1"
    )

    # 5. 下单
    order_result = place_spread(spread, dry_run=dry_run)

    return {"success": order_result.get("success", False), "spread": spread, "order": order_result}


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    action = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if action == "scan":
        chain = get_option_chain()
        if chain:
            print(f"QQQ = ${chain['underlying_price']}")
            print(f"到期日: {len(chain['expirations'])}个")
            print(f"预算: ${BUDGET} | 价差: ${SPREAD_WIDTH} | DTE: {MIN_DTE}-{MAX_DTE}天\n")

            for d in ["BUY", "SELL"]:
                spread = select_spread(d, chain)
                if spread:
                    label = "Bull Call Spread" if d == "BUY" else "Bear Put Spread"
                    print(f"{'='*50}")
                    print(f"{label} ({d}信号)")
                    print(f"  到期: {spread['expiration']} (DTE={spread['dte']})")
                    print(f"  Strike: {spread['long_strike']}/{spread['short_strike']}")
                    print(f"  Delta: {spread['long_delta']:.3f}/{spread['short_delta']:.3f}")
                    print(f"  每张: 成本${spread['cost_per_contract']*100:.0f} / 最大盈利${spread['max_profit_per_contract']*100:.0f}")
                    print(f"  盈亏比: {spread['risk_reward']}:1")
                    print(f"  合约: {spread['contracts']}张")
                    print(f"  总计: 成本${spread['total_cost']:.0f} / 最大盈利${spread['total_max_profit']:.0f}")
                    print(f"  卖出规则: 止盈{TAKE_PROFIT_PCT*100:.0f}% | 止损{STOP_LOSS_PCT*100:.0f}% | DTE≤{EXIT_DTE}天")
                    print()

    elif action == "position":
        pos = _load_position()
        if pos:
            s = pos["spread"]
            print(f"持仓: {s['type']} {s['long_strike']}/{s['short_strike']}")
            print(f"到期: {s['expiration']} (DTE={s['dte']})")
            print(f"成本: ${s['total_cost']:.0f} ({s['contracts']}张)")
            print(f"开仓: {pos.get('opened_at','?')}")
            cv = get_spread_current_value(s)
            if cv is not None:
                pnl = (cv - s['cost_per_contract']) * 100 * s['contracts']
                print(f"当前价值: ${cv:.2f}/张 → PnL: ${pnl:.0f}")
        else:
            print("无持仓")

    elif action == "check":
        exit_signal = check_exit_rules()
        if exit_signal:
            print(f"触发: {exit_signal['action']}")
            print(f"原因: {exit_signal['reason']}")
            print(f"PnL: ${exit_signal['pnl']:.0f}")
        else:
            pos = _load_position()
            if pos:
                print("持仓正常，未触发卖出规则")
            else:
                print("无持仓")

    elif action == "manage":
        result = auto_manage(dry_run=True)
        if result:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("无需操作")

    elif action in ("buy", "sell"):
        direction = "BUY" if action == "buy" else "SELL"
        result = execute_signal(direction, dry_run=True)
        print(json.dumps(result, indent=2, default=str))

    elif action in ("buy-live", "sell-live"):
        direction = "BUY" if "buy" in action else "SELL"
        print(f"⚠️  即将实盘下单 {direction} QQQ spread (预算${BUDGET})!")
        confirm = input("确认? (yes/no): ")
        if confirm.lower() == "yes":
            result = execute_signal(direction, dry_run=False)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("已取消")

    elif action == "close-live":
        pos = _load_position()
        if not pos:
            print("无持仓可平")
        else:
            print(f"⚠️  即将平仓 {pos['spread']['type']}!")
            confirm = input("确认? (yes/no): ")
            if confirm.lower() == "yes":
                result = close_spread(pos["spread"], dry_run=False, market_order=True)
                print(json.dumps(result, indent=2, default=str))

    else:
        print("用法: python qqq_options.py <command>")
        print("  scan       扫描当前最优spread")
        print("  buy/sell   干跑测试")
        print("  buy-live   实盘开仓 (需确认)")
        print("  sell-live  实盘开仓 (需确认)")
        print("  position   查看持仓")
        print("  check      检查卖出规则")
        print("  manage     自动管理 (干跑)")
        print("  close-live 手动平仓 (需确认)")
