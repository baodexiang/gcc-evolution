"""
baseline_gate.py — 基准K线 + 唐纳奇周期 仓位门控
====================================================
在 handle_p0_signal() 中买卖前检查:
  1) 先判断结构方向: buy基准/sell基准/反转/中性
  2) 再按结构规则过滤所有信号(BUY和SELL都受结构影响)
  3) 唐纳奇周期: 方向是否与周期趋势一致 (GCC-0200)

结构规则 (GCC-0200 S9):
  看多结构 (has_buy, !has_sell):
    BUY(顺结构) → pos 0~3 放开，检查 price > buy_baseline
    SELL(逆结构) → 限制 pos[3,4]，无价格检查
  看空结构 (has_sell, !has_buy):
    SELL(顺结构) → pos 5,4,3,2 放开，检查 price < sell_baseline
    BUY(逆结构) → 限制 pos[1,2]，无价格检查
  反转 (both):
    BUY → 限制 pos[1,2]，检查 price > buy_baseline
    SELL → 限制 pos[3,4]，检查 price < sell_baseline
  中性 (neither): 全部放行

Phase 1: ENABLED=False，仅日志观察，不实际拦截。
DC Phase 1: DC_ENABLED=False，仅日志模拟拦截，不实际拦截。
"""

import json
import os
import time

ENABLED = False     # Phase 1: 基准K线观察模式
DC_ENABLED = False  # Phase 1: 唐纳奇周期观察模式

STATE_FILE = os.path.join(os.path.dirname(__file__), "state", "baseline_state.json")

# 5分钟TTL缓存
_cache = {"data": {}, "ts": 0.0}
_CACHE_TTL = 300  # 5 min


def _load_state() -> dict:
    """读取baseline_state.json，带5分钟缓存"""
    now = time.time()
    if (now - _cache["ts"]) < _CACHE_TTL and _cache["data"]:
        return _cache["data"]
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                _cache["data"] = data
                _cache["ts"] = now
                return data
    except Exception:
        pass
    return {}


def _dc_check(state: dict, direction: str) -> str:
    """
    GCC-0200: 唐纳奇周期过滤检查。
    返回可解析的标签字符串:
      [DC_PASS]  — 方向与周期一致或震荡
      [DC_BLOCK:原因] — 方向与周期冲突(模拟拦截)
      [DC_NODATA] — 无周期数据
    """
    maturity = state.get("dc_maturity")
    trend = state.get("dc_cycle_trend")
    if maturity is None or trend is None:
        return "[DC_NODATA]"

    trend_label = {1: "上升", -1: "下降", 0: "震荡"}.get(trend, "?")
    info = f"{maturity}/{trend_label}"

    # BUY遇下降周期 → 模拟拦截
    if direction == "buy" and trend == -1:
        return f"[DC_BLOCK:BUY反向{info}]"
    # SELL遇上升周期 → 模拟拦截
    if direction == "sell" and trend == 1:
        return f"[DC_BLOCK:SELL反向{info}]"

    return f"[DC_PASS:{info}]"


def baseline_gate(current_price, direction, position_units, symbol) -> tuple:
    """
    返回 (pass: bool, reason: str)
    pass=True 表示通过(允许交易), pass=False 表示拦截

    核心逻辑: 先判断结构方向，再按结构规则过滤所有信号。
    任何BUY/SELL信号都先看基准是buy还是sell，然后遵守相应规则。

    Phase 1 (ENABLED=False): 不通过时也返回 True (不拦截)，仅日志
    Phase 2 (ENABLED=True):  不通过时返回 False (实际拦截)
    """
    state = _load_state().get(symbol, {})
    has_buy = state.get("buy_found") and state.get("buy_price") is not None
    has_sell = state.get("sell_found") and state.get("sell_price") is not None

    # ---- Step 1: 判断结构方向 ----
    if has_buy and not has_sell:
        structure = "bullish"   # 看多结构
    elif has_sell and not has_buy:
        structure = "bearish"   # 看空结构
    elif has_buy and has_sell:
        structure = "reversal"  # 反转(双基准)
    else:
        structure = "neutral"   # 中性(无基准)

    # ---- Step 2: 中性 → 全部放行 ----
    if structure == "neutral":
        return True, ""

    dc_tag = _dc_check(state, direction)

    # ---- Step 3: 按结构+信号方向过滤 ----
    if structure == "bullish":
        # 看多结构: BUY顺结构放开, SELL逆结构限制
        if direction == "buy":
            # 顺结构: pos 0~3 放开，检查 price > buy_baseline
            if position_units not in [0, 1, 2, 3]:
                return True, ""
            if current_price <= state["buy_price"]:
                msg = f"价格{current_price}<=基准Buy{state['buy_price']}(pos={position_units},看多顺结构) {dc_tag}"
                return (not ENABLED), msg
            return True, f"通过基准Buy:{current_price}>{state['buy_price']}(pos={position_units},看多顺结构) {dc_tag}"
        else:
            # SELL逆结构: 限制 pos[3,4]，无价格检查(无sell基准)
            if position_units not in [3, 4]:
                return True, ""
            msg = f"SELL逆结构限制(pos={position_units},看多结构,无sell基准) {dc_tag}"
            return (not ENABLED), msg

    elif structure == "bearish":
        # 看空结构: SELL顺结构放开, BUY逆结构限制
        if direction == "sell":
            # 顺结构: pos 5,4,3,2 放开，检查 price < sell_baseline
            if position_units not in [5, 4, 3, 2]:
                return True, ""
            if current_price >= state["sell_price"]:
                msg = f"价格{current_price}>=基准Sell{state['sell_price']}(pos={position_units},看空顺结构) {dc_tag}"
                return (not ENABLED), msg
            return True, f"通过基准Sell:{current_price}<{state['sell_price']}(pos={position_units},看空顺结构) {dc_tag}"
        else:
            # BUY逆结构: 限制 pos[1,2]，无价格检查(无buy基准)
            if position_units not in [1, 2]:
                return True, ""
            msg = f"BUY逆结构限制(pos={position_units},看空结构,无buy基准) {dc_tag}"
            return (not ENABLED), msg

    elif structure == "reversal":
        # 反转: 双方都限制+价格检查
        if direction == "buy":
            if position_units not in [1, 2]:
                return True, ""
            if current_price <= state["buy_price"]:
                msg = f"价格{current_price}<=基准Buy{state['buy_price']}(pos={position_units},反转限制) {dc_tag}"
                return (not ENABLED), msg
            return True, f"通过基准Buy:{current_price}>{state['buy_price']}(pos={position_units},反转限制) {dc_tag}"
        else:
            if position_units not in [3, 4]:
                return True, ""
            if current_price >= state["sell_price"]:
                msg = f"价格{current_price}>=基准Sell{state['sell_price']}(pos={position_units},反转限制) {dc_tag}"
                return (not ENABLED), msg
            return True, f"通过基准Sell:{current_price}<{state['sell_price']}(pos={position_units},反转限制) {dc_tag}"

    return True, ""
