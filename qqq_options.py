"""
TSLA期权直接买入模块 (GCC-0256 S5)
版本: v3.0

策略:
  BUY信号 → 买入ATM Call (无限上行空间)
  SELL信号 → 买入ATM Put (无限下行空间)

买入规则 (分批建仓, 买大后买小):
  1. 第1批(大): 信号确认后市价买 contracts-1 张 (如3→先买2)
  2. 第2批(小): 1小时内期权价格从入场价跌5%以内时限价买1张, entry_cost加权平均
     买不到就放弃, 直接用第1批仓位等平仓

卖出规则 (分批平仓, 先卖小留大, 优先级从高到低):
  1. 时间止损: DTE ≤ 1天 → 到期前强制全部平仓
  2. 止损: 期权价值跌到成本25%以下 → 市价全部平仓
  3. 分阶段止盈: 盈利达12% → 限价卖1张锁利, 留大头博更多
  4. 追踪止损: 部分止盈后激活, 从最高回撤6%市价卖剩余
  5. 信号反转: Vision方向反转 → 先平旧仓(下轮再开)

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

# 分阶段止盈 — 到12%利润限价卖一半，剩余回撤6%市价卖
TAKE_PROFIT_PCT = 0.12        # 第一阶段: 盈利达12%限价卖50%仓位
TAKE_PROFIT_CLOSE_RATIO = 0.5 # 卖出比例: 50%
TRAILING_ACTIVATE_PCT = 0.12  # 追踪止损激活门槛(剩余仓位)
TRAILING_PULLBACK_PCT = 0.06  # 从最高价值回撤6%市价平仓(剩余仓位)

# 每日交易次数限制: 每个方向每天最多1次 (最多1次CALL + 1次PUT)
MAX_DAILY_PER_DIRECTION = 1

# 持仓状态文件
STATE_FILE = Path(__file__).parent / "state" / "tsla_options_position.json"
DAILY_TRADES_FILE = Path(__file__).parent / "state" / "tsla_options_daily.json"


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
    """清除持仓 (平仓后, 线程安全), 同时记录到交易历史"""
    with _position_lock:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if data.get("status") in ("open", "pending_close"):
                    data["status"] = "closed"
                    data["closed_at"] = datetime.now().isoformat()
                    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    # 记录到交易历史 (exit_action/exit_reason已在auto_manage中写入state)
                    _append_trade_history(data,
                                          data.get("exit_action", ""),
                                          data.get("exit_reason", ""))
            except Exception:
                pass


HISTORY_FILE = Path(__file__).parent / "state" / "tsla_options_history.json"


def _append_trade_history(pos_data: dict, exit_action: str = "", exit_reason: str = ""):
    """将完成的交易追加到历史记录"""
    opt = pos_data.get("option") or pos_data.get("spread") or {}
    entry_cost = pos_data.get("entry_cost", 0)
    opened_at = pos_data.get("opened_at", "")
    closed_at = pos_data.get("closed_at", "")
    contracts = opt.get("contracts", 0)
    partial_tp = pos_data.get("partial_tp_done", False)

    record = {
        "type": opt.get("type", ""),         # CALL / PUT
        "strike": opt.get("strike", 0),
        "expiration": opt.get("expiration", ""),
        "contracts": contracts,
        "entry_cost": entry_cost,
        "peak_value": pos_data.get("peak_value", 0),
        "opened_at": opened_at,
        "closed_at": closed_at,
        "exit_action": exit_action,           # TRAILING_STOP / STOP_LOSS / TIME_EXIT / REVERSAL
        "exit_reason": exit_reason,
        "partial_tp_done": partial_tp,
        "date": opened_at[:10] if opened_at else "",
    }

    try:
        history = []
        if HISTORY_FILE.exists():
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        history.append(record)
        # 保留最近90天
        if len(history) > 500:
            history = history[-500:]
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.error(f"[B2][TSLA-OPT] 写入交易历史失败: {e}")


def _get_daily_trades() -> dict:
    """获取今日已开仓记录 {direction: count}"""
    today = datetime.now().strftime("%Y-%m-%d")
    if DAILY_TRADES_FILE.exists():
        try:
            data = json.loads(DAILY_TRADES_FILE.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return data.get("trades", {})
        except Exception:
            pass
    return {}


def _record_daily_trade(direction: str):
    """记录一次开仓 (BUY=CALL, SELL=PUT)"""
    today = datetime.now().strftime("%Y-%m-%d")
    data = {"date": today, "trades": {}}
    if DAILY_TRADES_FILE.exists():
        try:
            data = json.loads(DAILY_TRADES_FILE.read_text(encoding="utf-8"))
            if data.get("date") != today:
                data = {"date": today, "trades": {}}
        except Exception:
            data = {"date": today, "trades": {}}
    trades = data.get("trades", {})
    trades[direction] = trades.get(direction, 0) + 1
    data["trades"] = trades
    DAILY_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAILY_TRADES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _can_trade_today(direction: str) -> bool:
    """检查该方向今天是否还能交易 (每方向每天最多1次)"""
    trades = _get_daily_trades()
    used = trades.get(direction, 0)
    return used < MAX_DAILY_PER_DIRECTION


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
                # 部分止盈确认: 更新合约数, 不清除持仓
                if data.get("pending_action") == "TAKE_PROFIT_PARTIAL":
                    _pq = data.get("pending_close_qty", 1)
                    _cv = data.get("pending_current_value", 0)
                    with _position_lock:
                        opt_key = "option" if "option" in data else "spread"
                        old_qty = data[opt_key].get("contracts", 0)
                        data[opt_key]["contracts"] = old_qty - _pq
                        data["partial_tp_done"] = True
                        data["status"] = "open"
                        data["peak_value"] = _cv  # 从此刻起算追踪止损
                        for _k in ("close_order_id", "close_submitted_at",
                                   "pending_action", "pending_close_qty", "pending_current_value"):
                            data.pop(_k, None)
                        STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                    logger.info(f"[B2][TSLA-OPT] 部分止盈确认: {old_qty}→{old_qty - _pq}张, 追踪止损已激活")
                    return "FILLED"
                # 全部平仓确认: 清除持仓
                _clear_position()
                logger.info(f"[B2][TSLA-OPT] 平仓订单{close_order_id}已FILLED，持仓已清除")
                return "FILLED"
            elif status in ("CANCELED", "REJECTED", "EXPIRED"):
                # 平仓失败，恢复为open状态让auto_manage重试
                with _position_lock:
                    data["status"] = "open"
                    del data["close_order_id"]
                    del data["close_submitted_at"]
                    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.warning(f"[B2][TSLA-OPT] 平仓订单{close_order_id}状态={status}，恢复为open重试")
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
                            logger.warning(f"[B2][TSLA-OPT] 平仓订单{close_order_id}超时10min，已取消")
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
        logger.error(f"[B2][TSLA-OPT] 查询平仓订单{close_order_id}异常: {e}")
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
        logger.error(f"[B2][TSLA-OPT] get_option_chain失败: HTTP {resp.status_code}")
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
        logger.error("[B2][TSLA-OPT] 无可用期权链")
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
                    logger.warning(f"[B2][TSLA-OPT] {msg}")
                    return {"success": False, "error": msg}
                logger.warning(
                    f"[B2][TSLA-OPT] 资金不足: 购买力${option_bp:.0f} < 计划${option['total_cost']:.0f}，"
                    f"降级 {option['contracts']}→{affordable}张"
                )
                option["contracts"] = affordable
                option["total_cost"] = round(option["cost_per_contract"] * 100 * affordable, 2)
            logger.info(f"[B2][TSLA-OPT] 资金检查通过: option_buying_power=${option_bp:.0f}, 下单${option['total_cost']:.0f}")
        except Exception as _bal_e:
            logger.error(f"[B2][TSLA-OPT] 资金检查异常: {_bal_e}")
            return {"success": False, "error": f"资金检查失败: {_bal_e}"}

    try:
        from schwab.orders.options import option_buy_to_open_limit, option_buy_to_open_market

        client, account_hash = _get_schwab_client()
        opt_symbol = option["option_symbol"]
        contracts = option["contracts"]

        # 分批建仓: 3张→先市价买2张, 留1张待跌5%内加仓
        batch1_qty = max(contracts - 1, 1) if contracts >= 2 else contracts
        addon_qty = contracts - batch1_qty  # 0 or 1

        # 第1批: 市价单 (快速入场)
        order_spec = option_buy_to_open_market(opt_symbol, batch1_qty)
        label = f"Buy {option['type']} {option['strike']} x{batch1_qty} MKT" + (f" (+{addon_qty}待跌加仓)" if addon_qty else "")

        if dry_run:
            resp = client.preview_order(account_hash, order_spec)
            logger.info(f"[B2][TSLA-OPT] PREVIEW {label} cost=${option['total_cost']:.0f} → HTTP {resp.status_code}")
            return {"success": resp.status_code == 200, "dry_run": True, "label": label,
                    "status_code": resp.status_code, "option": option}

        resp = client.place_order(account_hash, order_spec)
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else ""
            logger.info(f"[B2][TSLA-OPT] PLACED {label} cost=${option['total_cost']:.0f} order_id={order_id}")

            # 查询实际成交价 (Schwab常优化成交, ask $9.90 → fill $9.81)
            fill_price = option["cost_per_contract"]  # 默认用ask
            if order_id:
                import time as _t
                _t.sleep(2)  # 等待成交
                try:
                    _fill_resp = client.get_order(account_hash, int(order_id))
                    if _fill_resp.status_code == 200:
                        _fill_data = _fill_resp.json()
                        if _fill_data.get("status") == "FILLED":
                            _acts = _fill_data.get("orderActivityCollection", [])
                            for _act in _acts:
                                for _ex in _act.get("executionLegs", []):
                                    _fp = _ex.get("price")
                                    if _fp and _fp > 0:
                                        fill_price = _fp
                                        logger.info(f"[B2][TSLA-OPT] 实际成交价=${fill_price} (ask=${option['cost_per_contract']})")
                except Exception as _fe:
                    logger.warning(f"[B2][TSLA-OPT] 查询成交价失败, 用ask价: {_fe}")

            # 保存持仓 (用实际成交价, 非ask价)
            # 分批建仓: option.contracts=总目标, 实际先买batch1_qty张
            option_saved = dict(option)
            option_saved["contracts"] = batch1_qty  # 当前实际持有张数
            pos_data = {
                "status": "open",
                "order_id": order_id,
                "option": option_saved,
                "opened_at": datetime.now().isoformat(),
                "entry_cost": fill_price,
                "peak_value": fill_price,  # 追踪止损用
            }
            # 记录待加仓信息 (下次auto_manage检查时, 方向确认后买入)
            if addon_qty > 0:
                pos_data["addon_pending"] = {
                    "qty": addon_qty,
                    "option_symbol": opt_symbol,
                    "limit_price": option["cost_per_contract"],
                    "type": option["type"],
                    "strike": option["strike"],
                    "expiration": option["expiration"],
                }
                logger.info(f"[B2][TSLA-OPT] 分批建仓: 先买{batch1_qty}张, 待确认后加仓{addon_qty}张")
            _save_position(pos_data)

            return {"success": True, "order_id": order_id, "label": label, "option": option,
                    "fill_price": fill_price}
        else:
            error_body = ""
            try:
                error_body = resp.json()
            except Exception:
                error_body = resp.text[:300]
            return {"success": False, "error": f"HTTP {resp.status_code}: {error_body}", "option": option}

    except Exception as e:
        logger.error(f"[B2][TSLA-OPT] place_option异常: {e}")
        return {"success": False, "error": str(e)}


def close_option(option: dict, contracts: int = None, dry_run: bool = True,
                 market_order: bool = False, limit_price: float = None) -> dict:
    """平仓: 卖出已持有的期权 (sell to close)

    Args:
        option: 持仓中的option字典
        contracts: 卖出张数 (默认=全部)
        market_order: True=市价平仓, False=限价(用bid价)
        limit_price: 指定限价 (优先于bid, 仅market_order=False时生效)
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
            # 优先用指定限价, 否则用bid
            price = limit_price or option.get("bid", option.get("cost_per_contract", 0.01))
            order_spec = option_sell_to_close_limit(opt_symbol, qty, str(round(price, 2)))

        label = f"Close {option.get('type','?')} {option.get('strike', option.get('long_strike','?'))} x{qty}"

        if dry_run:
            resp = client.preview_order(account_hash, order_spec)
            return {"success": resp.status_code == 200, "dry_run": True, "label": label}

        resp = client.place_order(account_hash, order_spec)
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            order_id = location.split("/")[-1] if location else ""
            _mark_pending_close(order_id)
            logger.info(f"[B2][TSLA-OPT] CLOSE SUBMITTED {label} order_id={order_id}")
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
        logger.error(f"[B2][TSLA-OPT] 查询期权当前价值失败: {e}")
        return None


def check_exit_rules() -> Optional[dict]:
    """
    检查卖出规则 (优先级: TIME_EXIT > STOP_LOSS > TAKE_PROFIT_PARTIAL > TRAILING_STOP)

    分阶段止盈 (2张以上):
      1) 盈利达12% → 限价卖1张锁利(先卖小留大)
      2) 剩余仓位 → 追踪止损(从峰值回撤6%市价平仓)

    单张止盈 (1张):
      盈利达12% → 激活追踪止损, 从峰值回撤6%市价平仓

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
        logger.warning("[B2][TSLA-OPT] 持仓数据缺少option/expiration字段，跳过")
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
        logger.warning("[B2][TSLA-OPT] 无法获取当前期权价值，跳过检查")
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

    # 4. 分阶段止盈: 盈利达12% → 先卖小留大(卖1张锁利, 留大头博更多)
    partial_tp_done = position.get("partial_tp_done", False)
    take_profit_threshold = entry_cost * (1 + TAKE_PROFIT_PCT)
    if not partial_tp_done and current_value >= take_profit_threshold and contracts >= 2:
        # 先卖小留大: 3→卖1留2, 4→卖1留3, 5→卖1留4
        close_qty = 1
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

    # 5. 追踪止损: 部分止盈完成后 或 盈利达12%后激活
    #    从峰值回撤6%平仓(剩余全部)
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


def _check_addon_buy(dry_run: bool = True) -> Optional[dict]:
    """分批建仓第2批: 期权价格从入场价跌5%以内时加仓

    触发条件: entry_cost * 0.95 <= current_value < entry_cost (跌了但没跌太多)
    放弃条件: 价格涨超入场价(已确认方向, 不需要摊薄) 或 超30分钟
    """
    position = _load_position()
    if not position or not position.get("addon_pending"):
        return None

    addon = position["addon_pending"]
    option = position.get("option") or {}
    entry_cost = position.get("entry_cost", 0)

    # 超30分钟未触发 → 放弃加仓, 用现有仓位交易
    opened_at = position.get("opened_at", "")
    if opened_at:
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(opened_at)).total_seconds()
            if elapsed > 3600:  # 1小时
                with _position_lock:
                    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                    data.pop("addon_pending", None)
                    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info(f"[B2][TSLA-OPT] 加仓超时1h, 放弃, 用{option.get('contracts', 0)}张交易")
                return None
        except Exception:
            pass

    # 查当前价值
    current_value = get_option_current_value(option)
    if current_value is None:
        return None

    # 触发: 跌了但在5%以内 (低吸摊薄)
    dip_floor = entry_cost * 0.95
    if current_value >= entry_cost:
        # 价格没跌, 等
        return None
    if current_value < dip_floor:
        # 跌太多(>5%), 不加仓, 等止损
        logger.info(f"[B2][TSLA-OPT] 加仓跳过: 当前${current_value:.2f} < 5%底线${dip_floor:.2f}, 跌太多")
        return None

    # 在跌5%以内, 执行加仓
    addon_qty = addon["qty"]
    opt_symbol = addon["option_symbol"]
    limit_price = round(current_value, 2)  # 用当前bid价作限价

    logger.info(f"[B2][TSLA-OPT] 加仓触发: 当前${current_value:.2f} 跌至入场${entry_cost:.2f}的5%内, 买{addon_qty}张@${limit_price}")

    if dry_run:
        return {"action": "ADDON_BUY", "qty": addon_qty, "price": limit_price, "dry_run": True}

    try:
        from schwab.orders.options import option_buy_to_open_limit
        client, account_hash = _get_schwab_client()
        order_spec = option_buy_to_open_limit(opt_symbol, addon_qty, str(limit_price))
        resp = client.place_order(account_hash, order_spec)
        if resp.status_code == 201:
            location = resp.headers.get("Location", "")
            addon_order_id = location.split("/")[-1] if location else ""

            # 查询加仓成交价
            addon_fill = limit_price
            if addon_order_id:
                import time as _t
                _t.sleep(2)
                try:
                    _fr = client.get_order(account_hash, int(addon_order_id))
                    if _fr.status_code == 200:
                        _fd = _fr.json()
                        if _fd.get("status") == "FILLED":
                            for _a in _fd.get("orderActivityCollection", []):
                                for _e in _a.get("executionLegs", []):
                                    if _e.get("price", 0) > 0:
                                        addon_fill = _e["price"]
                except Exception:
                    pass

            # 更新持仓: 合约数增加, entry_cost加权平均
            with _position_lock:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                opt_key = "option" if "option" in data else "spread"
                old_qty = data[opt_key].get("contracts", 0)
                old_entry = data.get("entry_cost", 0)
                new_qty = old_qty + addon_qty
                # 加权平均成本
                new_entry = round((old_entry * old_qty + addon_fill * addon_qty) / new_qty, 4)
                data[opt_key]["contracts"] = new_qty
                data["entry_cost"] = new_entry
                data["peak_value"] = max(data.get("peak_value", 0), new_entry)
                data.pop("addon_pending", None)
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

            logger.info(
                f"[B2][TSLA-OPT] 加仓完成: {old_qty}→{new_qty}张, "
                f"成本${old_entry:.2f}→${new_entry:.2f}(加权), fill=${addon_fill}"
            )
            return {"action": "ADDON_BUY", "qty": addon_qty, "fill": addon_fill,
                    "new_total": new_qty, "new_entry": new_entry}
        else:
            logger.error(f"[B2][TSLA-OPT] 加仓下单失败: HTTP {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"[B2][TSLA-OPT] 加仓异常: {e}")
        return None


def sync_manual_close() -> bool:
    """GCC-0016 S0: 检测用户手工平仓 → 同步清除内部state
    查Schwab实际持仓, 如果内部state有仓但Schwab没有 → 清除state
    Returns: True=检测到手工平仓并清除, False=正常
    """
    pos = _load_position(include_pending=True)
    if not pos:
        return False
    opt = pos.get("option") or pos.get("spread")
    if not opt:
        return False
    try:
        from schwab.client import Client
        client, account_hash = _get_schwab_client()
        resp = client.get_accounts(fields=[Client.Account.Fields.POSITIONS])
        accounts = resp.json() if resp.status_code == 200 else []
        if not isinstance(accounts, list):
            accounts = [accounts]
        # 查是否还持有TSLA期权
        has_tsla_option = False
        for acct in accounts:
            sa = acct.get("securitiesAccount", acct)
            for p in sa.get("positions", []):
                inst = p.get("instrument", {})
                if inst.get("assetType") == "OPTION" and "TSLA" in inst.get("symbol", ""):
                    qty = p.get("longQuantity", 0)
                    if qty > 0:
                        has_tsla_option = True
                        break
        if not has_tsla_option:
            logger.warning(
                "[B2][TSLA-OPT] 手工平仓检测: 内部state有仓但Schwab无TSLA期权持仓 → 清除state"
            )
            _clear_position()
            return True
    except Exception as e:
        logger.debug(f"[B2][TSLA-OPT] sync_manual_close检查异常: {e}")
    return False


def auto_manage(dry_run: bool = True) -> Optional[dict]:
    """
    自动持仓管理: 加仓检查 → 卖出规则检查 → 执行平仓(支持部分平仓)

    Returns:
        None = 无操作
        {"action": str, "result": dict} = 已执行操作
    """
    # 分批建仓: 检查是否需要加仓 (优先于卖出检查)
    addon_result = _check_addon_buy(dry_run=dry_run)
    if addon_result:
        return {"action": "ADDON_BUY", "reason": "分批建仓第2批", "pnl": 0, "result": addon_result}

    exit_signal = check_exit_rules()
    if not exit_signal:
        return None

    action = exit_signal["action"]
    option = exit_signal["option"]
    pnl = exit_signal.get("pnl", 0)
    close_qty = exit_signal.get("contracts")  # 部分平仓张数, None=全部

    logger.info(
        f"[B2][TSLA-OPT] 卖出触发: {action} — {exit_signal['reason']} "
        f"PnL=${pnl:.0f} qty={close_qty or 'ALL'}"
    )

    # 第一次卖(TAKE_PROFIT_PARTIAL)用限价单(目标价=止盈阈值), 其他用市价
    if action == "TAKE_PROFIT_PARTIAL":
        _tp_limit = exit_signal.get("current_value", 0)  # 当前价>=阈值, 用当前价挂限价
        result = close_option(option, contracts=close_qty, dry_run=dry_run,
                              market_order=False, limit_price=_tp_limit)
    else:
        result = close_option(option, contracts=close_qty, dry_run=dry_run, market_order=True)

    # 记录exit信息到position state, 供_clear_position写入历史
    if result.get("success") and not dry_run:
        with _position_lock:
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                data["exit_action"] = action
                data["exit_reason"] = exit_signal["reason"]
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    # 部分止盈: 不立即更新合约数, 等check_pending_close确认FILLED后再更新
    # close_option已设status=pending_close, 这里只记录pending_action让确认逻辑知道是部分平仓
    if action == "TAKE_PROFIT_PARTIAL" and result.get("success") and not dry_run:
        with _position_lock:
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                data["pending_action"] = "TAKE_PROFIT_PARTIAL"
                data["pending_close_qty"] = close_qty
                data["pending_current_value"] = round(exit_signal["current_value"], 2)
                STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info(f"[B2][TSLA-OPT] 部分止盈限价单已提交, 等确认FILLED后更新合约数")
            except Exception as _e:
                logger.error(f"[B2][TSLA-OPT] 记录pending_action失败: {_e}")

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
    logger.info(f"[B2][TSLA-OPT] 收到{direction}信号, dry_run={dry_run}")

    # 0a. 每日交易次数限制: 每方向每天最多1次
    if not _can_trade_today(direction):
        logger.info(f"[B2][TSLA-OPT] {direction}方向今日已交易, 跳过 (每方向每天限1次)")
        return {"success": True, "action": "DAILY_LIMIT", "reason": f"{direction}方向今日已交易"}

    # 0b. 检查是否有pending_close (旧仓等确认中, 不开新仓)
    pending_pos = _load_position(include_pending=True)
    if pending_pos and pending_pos.get("status") == "pending_close":
        logger.info("[B2][TSLA-OPT] 旧仓pending_close等确认中，跳过开仓")
        return {"success": True, "action": "WAIT_PENDING", "reason": "旧仓平仓等确认中"}

    # 1. 检查现有持仓
    position = _load_position()
    if position:
        opt_data = position.get("option") or position.get("spread")
        if not opt_data:
            logger.warning("[B2][TSLA-OPT] 持仓数据异常(无option字段)，清除重来")
            _clear_position()
            position = None
    if position:
        existing_type = opt_data.get("type", "")
        # 同向: 已有持仓，不重复开 (兼容旧BULL_CALL/BEAR_PUT)
        if (direction == "BUY" and existing_type in ("CALL", "BULL_CALL")) or \
           (direction == "SELL" and existing_type in ("PUT", "BEAR_PUT")):
            logger.info(f"[B2][TSLA-OPT] 已有同向持仓 {existing_type}，跳过")
            return {"success": True, "action": "HOLD", "reason": "已有同向持仓"}

        # 反向: 平旧仓, 不立即开新仓 (等pending_close确认后下轮再开)
        logger.info(f"[B2][TSLA-OPT] 信号反转 {existing_type} → {direction}，平仓等确认")
        close_result = close_option(opt_data, dry_run=dry_run, market_order=True)
        if not close_result.get("success") and not dry_run:
            logger.error(f"[B2][TSLA-OPT] 平仓失败: {close_result}")
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
        f"[B2][TSLA-OPT] 选中: {option['type']} {option['strike']} "
        f"DTE={option['dte']} x{option['contracts']} "
        f"cost=${option['total_cost']:.0f} delta={option['delta']}"
    )

    # 5. 下单
    order_result = place_option(option, dry_run=dry_run)

    # 记录每日交易 (成功开仓后)
    if order_result.get("success") and not dry_run:
        _record_daily_trade(direction)

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
