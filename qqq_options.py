"""
TSLA期权直接买入模块 (GCC-0256 S5)
版本: v3.0

策略:
  BUY信号 → 买入ATM Call (无限上行空间)
  SELL信号 → 买入ATM Put (无限下行空间)

卖出规则 (自动平仓, 优先级从高到低):
  1. 时间止损: DTE ≤ 1天 → 到期前强制平仓
  2. 止损: 期权价值跌到成本50%以下 → 市价平仓
  3. 追踪止损: 盈利达成本25%后激活, 从最高回撤40%平仓 (让利润跑)
  4. 信号反转: Vision方向反转 → 先平旧仓(下轮再开)

资金控制:
  - 严格 ≤ $3000/笔，向下取整
  - 同时最多1个持仓 (避免资金分散)
  - 持仓状态持久化到 state/tsla_options_position.json

依赖:
  - schwab_data_provider.py
  - schwab-py SDK
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tsla_options")

# 线程锁: 防止后台线程和主线程同时操作持仓文件
_position_lock = threading.Lock()

# ── 配置 ─────────────────────────────────────────────────────────────────
BUDGET = 3000           # 每次交易预算 (USD)，严格不超
MIN_DTE = 7             # 最短到期天数
MAX_DTE = 14            # 最长到期天数
TARGET_DELTA = 0.50     # 目标delta (ATM)
MAX_CONTRACTS = 5       # 单次最大合约数，在BUDGET内买满
SYMBOL = "TSLA"         # 标的

# 卖出策略参数
STOP_LOSS_PCT = 0.25    # 止损: 亏损成本的25%平仓
EXIT_DTE = 1            # 时间止损: 到期前1天平仓

# 分阶段止盈 — 到10%利润先卖一半，剩余用6%移动止盈
TAKE_PROFIT_PCT = 0.10        # 第一阶段: 盈利达10%卖50%仓位
TAKE_PROFIT_CLOSE_RATIO = 0.5 # 卖出比例: 50%
TRAILING_ACTIVATE_PCT = 0.10  # 追踪止损激活门槛(剩余仓位)
TRAILING_PULLBACK_PCT = 0.06  # 从最高价值回撤6%就平仓(剩余仓位)

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
                logger.info(f"[TSLA_OPT] 平仓订单{close_order_id}已FILLED，持仓已清除")
                return "FILLED"
            elif status in ("CANCELED", "REJECTED", "EXPIRED"):
                # 平仓失败，恢复为open状态让auto_manage重试
                with _position_lock:
                    data["status"] = "open"
                    del data["close_order_id"]
                    del data["close_submitted_at"]
                    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.warning(f"[TSLA_OPT] 平仓订单{close_order_id}状态={status}，恢复为open重试")
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
                            logger.warning(f"[TSLA_OPT] 平仓订单{close_order_id}超时10min，已取消")
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
        logger.error(f"[TSLA_OPT] 查询平仓订单{close_order_id}异常: {e}")
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
    """获取TSLA期权链 (MIN_DTE ~ MAX_DTE, ATM附近)"""
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
        logger.error(f"[TSLA_OPT] get_option_chain失败: HTTP {resp.status_code}")
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


# ── 期权选择 ───────────────────────────────────────────────────────────

def select_option(direction: str, chain: dict = None) -> Optional[dict]:
    """
    选择ATM附近最优单腿期权，严格控制总成本 ≤ BUDGET
    BUY信号 → 买ATM Call  |  SELL信号 → 买ATM Put
    偏好: delta接近0.50 (ATM) > 低ask价 > 短DTE
    """
    if chain is None:
        chain = get_option_chain()

    if not chain or not chain.get("expirations"):
        logger.error("[TSLA_OPT] 无可用期权链")
        return None

    price = chain["underlying_price"]
    best = None
    best_score = -1

    for exp in chain["expirations"]:
        dte = exp["dte"]

        if direction == "BUY":
            # 买Call
            for strike, opt in exp["calls"].items():
                if abs(opt["delta"] - TARGET_DELTA) > 0.15:
                    continue
                if opt["ask"] <= 0:
                    continue

                cost_per = opt["ask"]  # 每张ask价 (乘100=实际成本)
                total_cost = cost_per * 100
                contracts = min(int(BUDGET / total_cost), MAX_CONTRACTS)
                if contracts < 1:
                    continue
                actual_cost = total_cost * contracts
                if actual_cost > BUDGET:
                    continue

                # 评分: ATM越近越好, 越便宜越好(能买更多张), DTE适中
                delta_score = 1 - abs(opt["delta"] - 0.50)
                price_score = 1 - min(cost_per / (price * 0.05), 1)  # 占标的5%以内
                dte_score = 1 / max(dte, 1)
                score = delta_score * 0.5 + price_score * 0.3 + dte_score * 0.2

                if score > best_score:
                    best_score = score
                    best = {
                        "type": "CALL",
                        "expiration": exp["date"],
                        "dte": dte,
                        "strike": strike,
                        "option_symbol": opt["symbol"],
                        "delta": round(opt["delta"], 3),
                        "ask": cost_per,
                        "bid": opt["bid"],
                        "cost_per_contract": cost_per,
                        "contracts": contracts,
                        "total_cost": round(actual_cost, 2),
                    }

        elif direction == "SELL":
            # 买Put
            for strike, opt in exp["puts"].items():
                if abs(abs(opt["delta"]) - TARGET_DELTA) > 0.15:
                    continue
                if opt["ask"] <= 0:
                    continue

                cost_per = opt["ask"]
                total_cost = cost_per * 100
                contracts = min(int(BUDGET / total_cost), MAX_CONTRACTS)
                if contracts < 1:
                    continue
                actual_cost = total_cost * contracts
                if actual_cost > BUDGET:
                    continue

                delta_score = 1 - abs(abs(opt["delta"]) - 0.50)
                price_score = 1 - min(cost_per / (price * 0.05), 1)
                dte_score = 1 / max(dte, 1)
                score = delta_score * 0.5 + price_score * 0.3 + dte_score * 0.2

                if score > best_score:
                    best_score = score
                    best = {
                        "type": "PUT",
                        "expiration": exp["date"],
                        "dte": dte,
                        "strike": strike,
                        "option_symbol": opt["symbol"],
                        "delta": round(opt["delta"], 3),
                        "ask": cost_per,
                        "bid": opt["bid"],
                        "cost_per_contract": cost_per,
                        "contracts": contracts,
                        "total_cost": round(actual_cost, 2),
                    }

    return best


# ── 下单 ─────────────────────────────────────────────────────────────────

def place_option(option: dict, dry_run: bool = True) -> dict:
    """下单买入单腿期权 (Call或Put)"""
    if not option:
        return {"success": False, "error": "无期权数据"}

    # 最后一道资金检查
    if option["total_cost"] > BUDGET:
        return {"success": False, "error": f"总成本${option['total_cost']}超过预算${BUDGET}"}

    # 账户资金检查 (dry_run跳过)
    if not dry_run:
        try:
            from schwab_data_provider import get_provider as _gp
            bal = _gp().get_account_balance()
            option_bp = bal.get("option_buying_power", 0)
            if option_bp < option["total_cost"]:
                # 资金不够买当前合约数，降级到实际能买的最大量
                affordable = int(option_bp / (option["cost_per_contract"] * 100))
                if affordable < 1:
                    msg = f"账户期权购买力${option_bp:.0f}不足以买1张(需${option['cost_per_contract'] * 100:.0f})，跳过"
                    logger.warning(f"[TSLA_OPT] {msg}")
                    return {"success": False, "error": msg}
                logger.warning(
                    f"[TSLA_OPT] 资金不足: 购买力${option_bp:.0f} < 计划${option['total_cost']:.0f}，"
                    f"降级 {option['contracts']}→{affordable}张"
                )
                option["contracts"] = affordable
                option["total_cost"] = round(option["cost_per_contract"] * 100 * affordable, 2)
            logger.info(f"[TSLA_OPT] 资金检查通过: option_buying_power=${option_bp:.0f}, 下单${option['total_cost']:.0f}")
        except Exception as _bal_e:
            logger.error(f"[TSLA_OPT] 资金检查异常: {_bal_e}")
            return {"success": False, "error": f"资金检查失败: {_bal_e}"}

    try:
        from schwab.orders.options import option_buy_to_open_limit

        client, account_hash = _get_schwab_client()
        opt_symbol = option["option_symbol"]
        contracts = option["contracts"]
        limit_price = str(option["cost_per_contract"])

        order_spec = option_buy_to_open_limit(
            opt_symbol, contracts, limit_price
        )
        label = f"Buy {option['type']} {option['strike']} x{contracts}"

        if dry_run:
            resp = client.preview_order(account_hash, order_spec)
            logger.info(f"[TSLA_OPT] PREVIEW {label} cost=${option['total_cost']:.0f} → HTTP {resp.status_code}")
            return {"success": resp.status_code == 200, "dry_run": True, "label": label,
                    "status_code": resp.status_code, "option": option}

        resp = client.place_order(account_hash, order_spec)
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else ""
            logger.info(f"[TSLA_OPT] PLACED {label} cost=${option['total_cost']:.0f} order_id={order_id}")

            # 保存持仓
            _save_position({
                "status": "open",
                "order_id": order_id,
                "option": option,
                "opened_at": datetime.now().isoformat(),
                "entry_cost": option["cost_per_contract"],
                "peak_value": option["cost_per_contract"],  # 追踪止损用
            })

            return {"success": True, "order_id": order_id, "label": label, "option": option}
        else:
            error_body = ""
            try:
                error_body = resp.json()
            except Exception:
                error_body = resp.text[:300]
            return {"success": False, "error": f"HTTP {resp.status_code}: {error_body}", "option": option}

    except Exception as e:
        logger.error(f"[TSLA_OPT] place_option异常: {e}")
        return {"success": False, "error": str(e)}


def close_option(option: dict, contracts: int = None, dry_run: bool = True,
                 market_order: bool = False) -> dict:
    """平仓: 卖出已持有的期权 (sell to close)

    Args:
        option: 持仓中的option字典
        contracts: 卖出张数 (默认=全部)
        market_order: True=市价平仓, False=限价(用bid价)
    """
    if not option:
        return {"success": False, "error": "无期权数据"}

    try:
        from schwab.orders.options import option_sell_to_close_limit, option_sell_to_close_market

        client, account_hash = _get_schwab_client()
        opt_symbol = option.get("option_symbol") or option.get("long_symbol", "")
        qty = contracts or option.get("contracts", 1)

        if market_order:
            order_spec = option_sell_to_close_market(opt_symbol, qty)
        else:
            # 用当前bid价作为限价
            bid = option.get("bid", option.get("cost_per_contract", 0.01))
            order_spec = option_sell_to_close_limit(opt_symbol, qty, str(bid))

        label = f"Close {option.get('type','?')} {option.get('strike', option.get('long_strike','?'))} x{qty}"

        if dry_run:
            resp = client.preview_order(account_hash, order_spec)
            return {"success": resp.status_code == 200, "dry_run": True, "label": label}

        resp = client.place_order(account_hash, order_spec)
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else ""
            _mark_pending_close(order_id)
            logger.info(f"[TSLA_OPT] CLOSE SUBMITTED {label} order_id={order_id}")
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

def get_option_current_value(option: dict) -> Optional[float]:
    """
    查询单腿期权当前bid价 (每张)
    """
    try:
        client, _ = _get_schwab_client()

        exp_date = datetime.strptime(option["expiration"], "%Y-%m-%d")
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
        opt_type = option.get("type", "")  # "CALL" or "PUT" (旧: BULL_CALL/BEAR_PUT)
        strike_val = option.get("strike") or option.get("long_strike")
        if strike_val is None:
            return None

        if opt_type in ("CALL", "BULL_CALL"):
            option_map = data.get("callExpDateMap", {})
        else:
            option_map = data.get("putExpDateMap", {})

        for exp_key in option_map:
            if not exp_key.startswith(option.get("expiration", "")):
                continue
            strikes = option_map[exp_key]
            # 尝试匹配strike key (兼容 "490.0" 和 "490")
            s_keys = [str(strike_val)]
            if strike_val == int(strike_val):
                s_keys.append(str(int(strike_val)))
            for s_key in s_keys:
                if s_key in strikes:
                    return strikes[s_key][0].get("bid", 0)

        return None
    except Exception as e:
        logger.error(f"[TSLA_OPT] 查询期权当前价值失败: {e}")
        return None


def check_exit_rules() -> Optional[dict]:
    """
    检查卖出规则 (优先级: TIME_EXIT > STOP_LOSS > TAKE_PROFIT_PARTIAL > TRAILING_STOP)

    分阶段止盈:
      1) 盈利达25% → 卖掉一部分(单数卖1张, 偶数卖一半)
      2) 剩余仓位 → 追踪止损(从峰值回撤15%平仓)

    Returns:
        None = 无持仓或不需要操作
        {"action": str, "reason": str, "current_value": float,
         "pnl": float, "option": dict, "contracts": int (部分平仓张数)}
    """
    position = _load_position()
    if not position:
        return None

    option = position.get("option") or position.get("spread") or {}
    if not option or "expiration" not in option:
        logger.warning("[TSLA_OPT] 持仓数据缺少option/expiration字段，跳过")
        return None
    entry_cost = position.get("entry_cost", option.get("cost_per_contract", 0))
    contracts = option.get("contracts", 0)

    # 1. 时间止损: DTE ≤ EXIT_DTE (最高优先级, 全部平仓)
    try:
        exp_date = datetime.strptime(option["expiration"], "%Y-%m-%d")
        days_left = (exp_date - datetime.now()).days
        if days_left <= EXIT_DTE:
            current_value = get_option_current_value(option)
            if current_value is None:
                current_value = 0.01
            pnl = (current_value - entry_cost) * 100 * contracts
            return {
                "action": "TIME_EXIT",
                "reason": f"到期前{days_left}天，强制全部平仓",
                "current_value": current_value,
                "pnl": round(pnl, 2),
                "option": option,
            }
    except Exception:
        pass

    # 2. 查询当前价值
    current_value = get_option_current_value(option)
    if current_value is None:
        logger.warning("[TSLA_OPT] 无法获取当前期权价值，跳过检查")
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

    # 3. 止损: 亏损 ≥ 成本的 STOP_LOSS_PCT (全部平仓)
    stop_loss_threshold = entry_cost * (1 - STOP_LOSS_PCT)
    if current_value <= stop_loss_threshold:
        return {
            "action": "STOP_LOSS",
            "reason": f"触发{STOP_LOSS_PCT*100:.0f}%止损 (当前${current_value:.2f} ≤ 阈值${stop_loss_threshold:.2f})",
            "current_value": current_value,
            "pnl": round(pnl_total, 2),
            "option": option,
        }

    # 4. 分阶段止盈: 盈利达25% → 卖一部分(奇数卖1张, 偶数卖一半)
    partial_tp_done = position.get("partial_tp_done", False)
    take_profit_threshold = entry_cost * (1 + TAKE_PROFIT_PCT)
    if not partial_tp_done and current_value >= take_profit_threshold and contracts >= 2:
        # 奇数(3,5): 卖1张; 偶数(2,4): 卖一半
        close_qty = 1 if contracts % 2 == 1 else contracts // 2
        close_pnl = pnl_per_contract * 100 * close_qty
        return {
            "action": "TAKE_PROFIT_PARTIAL",
            "reason": (f"盈利达{TAKE_PROFIT_PCT*100:.0f}% → 卖{close_qty}/{contracts}张锁利 "
                       f"(当前${current_value:.2f} ≥ 阈值${take_profit_threshold:.2f})"),
            "current_value": current_value,
            "pnl": round(close_pnl, 2),
            "option": option,
            "contracts": close_qty,
        }

    # 5. 追踪止损: 部分止盈完成后 或 盈利达25%后激活
    #    从峰值回撤15%平仓(剩余全部), 不要求current_value>entry_cost
    trailing_activate = entry_cost * (1 + TRAILING_ACTIVATE_PCT)
    if peak_value >= trailing_activate or partial_tp_done:
        pullback = peak_value - current_value
        if peak_value > 0 and pullback > 0:
            pullback_pct = pullback / peak_value  # 从peak回撤百分比(基于peak)
            if pullback_pct >= TRAILING_PULLBACK_PCT:
                return {
                    "action": "TRAILING_STOP",
                    "reason": (f"追踪止损: 最高${peak_value:.2f} → 当前${current_value:.2f} "
                               f"回撤{pullback_pct*100:.0f}% ≥ {TRAILING_PULLBACK_PCT*100:.0f}%"),
                    "current_value": current_value,
                    "pnl": round(pnl_total, 2),
                    "option": option,
                }

    return None


def auto_manage(dry_run: bool = True) -> Optional[dict]:
    """
    自动持仓管理: 检查卖出规则 → 执行平仓(支持部分平仓)

    Returns:
        None = 无操作
        {"action": str, "result": dict} = 已执行平仓
    """
    exit_signal = check_exit_rules()
    if not exit_signal:
        return None

    action = exit_signal["action"]
    option = exit_signal["option"]
    pnl = exit_signal.get("pnl", 0)
    close_qty = exit_signal.get("contracts")  # 部分平仓张数, None=全部

    logger.info(
        f"[TSLA_OPT] 卖出触发: {action} — {exit_signal['reason']} "
        f"PnL=${pnl:.0f} qty={close_qty or 'ALL'}"
    )

    result = close_option(option, contracts=close_qty, dry_run=dry_run, market_order=True)

    # 部分止盈成功 → 更新持仓张数 + 标记partial_tp_done + 恢复status=open
    # 注意: close_option会调_mark_pending_close设status=pending_close，
    #       部分平仓必须恢复为open，否则check_pending_close确认后会清掉剩余仓位
    if action == "TAKE_PROFIT_PARTIAL" and result.get("success") and not dry_run:
        with _position_lock:
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                opt_key = "option" if "option" in data else "spread"
                old_qty = data[opt_key].get("contracts", 0)
                data[opt_key]["contracts"] = old_qty - close_qty
                data["partial_tp_done"] = True
                data["status"] = "open"  # 恢复open，剩余仓位继续追踪
                # 重置peak_value为当前值，让追踪止损从此刻起算
                data["peak_value"] = round(exit_signal["current_value"], 2)
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info(f"[TSLA_OPT] 部分止盈完成: {old_qty}→{old_qty - close_qty}张, 追踪止损已激活")
            except Exception as _e:
                logger.error(f"[TSLA_OPT] 更新部分止盈状态失败: {_e}")

    return {
        "action": action,
        "reason": exit_signal["reason"],
        "pnl": pnl,
        "result": result,
    }


# ── 完整执行流 ───────────────────────────────────────────────────────────

def execute_signal(direction: str, dry_run: bool = True) -> dict:
    """
    完整执行: 检查持仓 → 反向则先平 → 选期权 → 下单

    Args:
        direction: "BUY" 或 "SELL"
        dry_run: True=干跑, False=实盘
    """
    logger.info(f"[TSLA_OPT] 收到{direction}信号, dry_run={dry_run}")

    # 0. 检查是否有pending_close (旧仓等确认中, 不开新仓)
    pending_pos = _load_position(include_pending=True)
    if pending_pos and pending_pos.get("status") == "pending_close":
        logger.info("[TSLA_OPT] 旧仓pending_close等确认中，跳过开仓")
        return {"success": True, "action": "WAIT_PENDING", "reason": "旧仓平仓等确认中"}

    # 1. 检查现有持仓
    position = _load_position()
    if position:
        opt_data = position.get("option") or position.get("spread")
        if not opt_data:
            logger.warning("[TSLA_OPT] 持仓数据异常(无option字段)，清除重来")
            _clear_position()
            position = None
    if position:
        existing_type = opt_data.get("type", "")
        # 同向: 已有持仓，不重复开 (兼容旧BULL_CALL/BEAR_PUT)
        if (direction == "BUY" and existing_type in ("CALL", "BULL_CALL")) or \
           (direction == "SELL" and existing_type in ("PUT", "BEAR_PUT")):
            logger.info(f"[TSLA_OPT] 已有同向持仓 {existing_type}，跳过")
            return {"success": True, "action": "HOLD", "reason": "已有同向持仓"}

        # 反向: 平旧仓, 不立即开新仓 (等pending_close确认后下轮再开)
        logger.info(f"[TSLA_OPT] 信号反转 {existing_type} → {direction}，平仓等确认")
        close_result = close_option(opt_data, dry_run=dry_run, market_order=True)
        if not close_result.get("success") and not dry_run:
            logger.error(f"[TSLA_OPT] 平仓失败: {close_result}")
            return {"success": False, "error": "旧仓平仓失败", "close_result": close_result}
        return {"success": True, "action": "REVERSAL_CLOSE", "reason": f"反转平仓 {existing_type}→{direction}，等确认后再开新仓"}

    # 2. 获取期权链
    chain = get_option_chain()
    if not chain:
        return {"success": False, "error": "获取期权链失败"}

    # 3. 选择最优期权
    option = select_option(direction, chain)
    if not option:
        return {"success": False, "error": f"无合适的{direction}期权"}

    # 4. 最终资金检查
    if option["total_cost"] > BUDGET:
        return {"success": False, "error": f"总成本${option['total_cost']:.0f}超预算${BUDGET}"}

    logger.info(
        f"[TSLA_OPT] 选中: {option['type']} {option['strike']} "
        f"DTE={option['dte']} x{option['contracts']} "
        f"cost=${option['total_cost']:.0f} delta={option['delta']}"
    )

    # 5. 下单
    order_result = place_option(option, dry_run=dry_run)

    return {"success": order_result.get("success", False), "option": option, "order": order_result}


# ── 向后兼容: llm_server导入用 ─────────────────────────────────────────
# llm_server_v3640.py 仍然 import 旧名称, 这里做别名映射
select_spread = select_option
place_spread = place_option
close_spread = close_option
get_spread_current_value = get_option_current_value


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    action = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if action == "scan":
        chain = get_option_chain()
        if chain:
            print(f"TSLA = ${chain['underlying_price']}")
            print(f"到期日: {len(chain['expirations'])}个")
            print(f"预算: ${BUDGET} | DTE: {MIN_DTE}-{MAX_DTE}天\n")

            for d in ["BUY", "SELL"]:
                opt = select_option(d, chain)
                if opt:
                    label = "Call (做多)" if d == "BUY" else "Put (做空)"
                    print(f"{'='*50}")
                    print(f"{label} ({d}信号)")
                    print(f"  到期: {opt['expiration']} (DTE={opt['dte']})")
                    print(f"  Strike: {opt['strike']}")
                    print(f"  Delta: {opt['delta']:.3f}")
                    print(f"  每张: ask=${opt['ask']*100:.0f}")
                    print(f"  合约: {opt['contracts']}张")
                    print(f"  总成本: ${opt['total_cost']:.0f}")
                    print(f"  最大亏损: ${opt['total_cost']:.0f} (权利金)")
                    print(f"  最大盈利: 无限")
                    print(f"  卖出规则: 止损{STOP_LOSS_PCT*100:.0f}% | 追踪{TRAILING_PULLBACK_PCT*100:.0f}%回撤 | DTE≤{EXIT_DTE}天")
                    print()

    elif action == "position":
        pos = _load_position()
        if pos:
            o = pos.get("option") or pos.get("spread") or {}
            print(f"持仓: {o.get('type','?')} {o.get('strike', o.get('long_strike','?'))}")
            print(f"到期: {o.get('expiration','?')} (DTE={o.get('dte','?')})")
            print(f"成本: ${o.get('total_cost',0):.0f} ({o.get('contracts',0)}张)")
            print(f"开仓: {pos.get('opened_at','?')}")
            cv = get_option_current_value(o)
            if cv is not None:
                entry = pos.get('entry_cost', o.get('cost_per_contract', 0))
                pnl = (cv - entry) * 100 * o.get('contracts', 0)
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
        print(f"⚠️  即将实盘买入 {direction} TSLA 期权 (预算${BUDGET})!")
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
            o = pos.get("option") or pos.get("spread") or {}
            print(f"⚠️  即将平仓 {o.get('type','?')} {o.get('strike', o.get('long_strike','?'))}!")
            confirm = input("确认? (yes/no): ")
            if confirm.lower() == "yes":
                result = close_option(o, dry_run=False, market_order=True)
                print(json.dumps(result, indent=2, default=str))

    else:
        print("用法: python qqq_options.py <command>")
        print("  scan       扫描当前最优期权")
        print("  buy/sell   干跑测试")
        print("  buy-live   实盘开仓 (需确认)")
        print("  sell-live  实盘开仓 (需确认)")
        print("  position   查看持仓")
        print("  check      检查卖出规则")
        print("  manage     自动管理 (干跑)")
        print("  close-live 手动平仓 (需确认)")
