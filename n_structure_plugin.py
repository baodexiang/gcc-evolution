"""
n_structure_plugin.py — N字结构信号外挂 (v1.0)
================================================
职责: 读取 state/n_structure_state.json，检测状态转换，生成 BUY/SELL 信号。

信号规则（保守模式，DEEP_PULLBACK不生成信号）:
  PERFECT_N  + UP   → BUY  (完美N字上升, 第三笔顺势)
  PERFECT_N  + DOWN → SELL (完美N字下降, 第三笔顺势)
  UP_BREAK   + UP   → BUY  (突破前N字高点, 趋势加速)
  DOWN_BREAK + DOWN → SELL (跌破前N字低点, 趋势加速)
  其余状态(SIDE/PULLBACK/DEEP_PULLBACK) → 无信号

触发条件:
  1. 状态发生转换（state 或 direction 与上次不同）
  2. quality >= 0.5（低质量N字跳过）
  3. 每个品种每日 BUY/SELL 各最多1次（配额）
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

# ── 状态文件路径 ──────────────────────────────────────────────
N_STATE_FILE   = os.path.join("state", "n_structure_state.json")
N_PLUGIN_STATE = os.path.join("state", "n_plugin_state.json")   # 外挂自身状态（配额+转换记录）

# ── 信号触发状态表 ───────────────────────────────────────────
_SIGNAL_MAP: Dict[Tuple[str, str], str] = {
    ("PERFECT_N",  "UP"):   "BUY",
    ("PERFECT_N",  "DOWN"): "SELL",
    ("UP_BREAK",   "UP"):   "BUY",
    ("DOWN_BREAK", "DOWN"): "SELL",
}

# ── 质量门槛 ─────────────────────────────────────────────────
QUALITY_MIN = 0.5   # 低于此值跳过

# ── 读取缓存 ─────────────────────────────────────────────────
_ns_cache: Dict = {"data": None, "ts": 0.0}
_NS_CACHE_SEC = 60   # 1分钟缓存（N字状态变化慢）


def _load_n_state(symbol: str) -> Optional[dict]:
    """读取 n_structure_state.json，1分钟缓存"""
    now = time.time()
    if _ns_cache["data"] is not None and now - _ns_cache["ts"] < _NS_CACHE_SEC:
        data = _ns_cache["data"]
    else:
        if not os.path.exists(N_STATE_FILE):
            return None
        try:
            with open(N_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _ns_cache["data"] = data
            _ns_cache["ts"] = now
        except Exception:
            return None
    return data.get(symbol)


def _load_plugin_state() -> dict:
    """读取外挂自身状态（配额 + 上次触发状态）"""
    if not os.path.exists(N_PLUGIN_STATE):
        return {}
    try:
        with open(N_PLUGIN_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_plugin_state(state: dict):
    """保存外挂状态"""
    os.makedirs("state", exist_ok=True)
    try:
        with open(N_PLUGIN_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _is_new_day(last_date: str) -> bool:
    """判断是否是新的纽约时间交易日"""
    try:
        from datetime import timezone, timedelta
        ny_now = datetime.now(timezone(timedelta(hours=-5)))
        return ny_now.strftime("%Y-%m-%d") != last_date
    except Exception:
        return True


def check_signal(symbol: str) -> Tuple[Optional[str], str, float]:
    """
    检查当前N字状态，返回 (action, reason, quality)。
    action = "BUY" / "SELL" / None

    流程:
      1. 读当前状态
      2. 检查是否满足信号状态
      3. 检查状态转换（避免重复触发）
      4. 检查 quality >= 0.5
      5. 检查每日配额
    """
    ns = _load_n_state(symbol)
    if not ns:
        return None, "n_structure_state.json无数据", 0.0

    state     = ns.get("state", "SIDE")
    direction = ns.get("direction", "NONE")
    quality   = float(ns.get("quality", 0.0))

    # Step 1: 信号状态判断
    action = _SIGNAL_MAP.get((state, direction))
    if not action:
        return None, f"状态{state}/{direction}不生成信号", quality

    # Step 2: quality过滤
    if quality < QUALITY_MIN:
        return None, f"N字质量不足(quality={quality:.2f}<{QUALITY_MIN})", quality

    # Step 3: 状态转换检查
    plugin_state = _load_plugin_state()
    sym_state = plugin_state.get(symbol, {})
    prev_state     = sym_state.get("last_state", "")
    prev_direction = sym_state.get("last_direction", "")

    if state == prev_state and direction == prev_direction:
        return None, f"状态未转换({state}/{direction})，不重复触发", quality

    # Step 4: 每日配额检查 (NY时区=交易日)
    from datetime import timedelta
    _ny_tz = timezone(timedelta(hours=-5))
    today = datetime.now(_ny_tz).strftime("%Y-%m-%d")
    quota_date = sym_state.get("quota_date", "")
    if quota_date != today:
        # 新的一天，重置配额
        sym_state["buy_used"]   = False
        sym_state["sell_used"]  = False
        sym_state["quota_date"] = today

    if action == "BUY" and sym_state.get("buy_used"):
        return None, f"今日BUY配额已用(PERFECT_N/UP_BREAK)", quality
    if action == "SELL" and sym_state.get("sell_used"):
        return None, f"今日SELL配额已用(PERFECT_N/DOWN_BREAK)", quality

    # 全部通过 → 更新状态并返回信号
    sym_state["last_state"]     = state
    sym_state["last_direction"] = direction
    sym_state["last_ts"]        = datetime.now(timezone.utc).isoformat()
    if action == "BUY":
        sym_state["buy_used"] = True
    else:
        sym_state["sell_used"] = True

    plugin_state[symbol] = sym_state
    _save_plugin_state(plugin_state)

    retrace = ns.get("retrace_ratio", 0.0)
    ext_ok  = ns.get("extension_ok", True)
    reason  = (f"N字{state}/{direction} quality={quality:.2f} "
               f"retrace={retrace:.1%} ext={'OK' if ext_ok else 'WEAK'} "
               f"A={ns.get('A',0):.2f} B={ns.get('B',0):.2f} C={ns.get('C',0):.2f}")

    logger.info(f"[NStructPlugin] {symbol} {action} 信号触发: {reason}")
    return action, reason, quality


def reset_cache():
    """强制清除读取缓存（测试用）"""
    _ns_cache["data"] = None
    _ns_cache["ts"] = 0.0
