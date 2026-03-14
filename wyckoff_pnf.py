"""
wyckoff_pnf.py  —  P&F水平计数止盈目标 + 信号池推送
GCC-0261 S5: 基于Wyckoff因果定律计算T1/T2止盈价位

原理:
  吸筹/派发区间的水平宽度(列数) × Box Size × 反转格数 = 预期行情幅度
  T1(保守) = 区间边界 + 宽度 × 0.6   (60%计数)
  T2(完整) = 区间边界 + 宽度 × 1.0   (100%计数)

接入方式:
  gcc_observe() 每30min调用 check_and_push()
  → 价格接近T1/T2时推SELL信号到信号池
  → 现有SELL流程自然执行减仓
"""

import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("gcc_tm")

_STATE_DIR = Path("state")
_PNF_STATE_FILE = _STATE_DIR / "wyckoff_pnf_targets.json"

# ─── 参数 ───
T1_RATIO = 0.6           # T1 = 区间宽度 × 60% (保守目标)
T2_RATIO = 1.0           # T2 = 区间宽度 × 100% (完整目标)
T1_PROXIMITY_ATR = 0.5   # 价格距T1 < 0.5 ATR时触发
T2_PROXIMITY_ATR = 0.5   # 价格距T2 < 0.5 ATR时触发
T1_CONFIDENCE = 0.65     # T1触发时推送的信号置信度
T2_CONFIDENCE = 0.80     # T2触发时推送的信号置信度
TARGET_COOLDOWN = 1800   # 同一目标推送冷却 (秒, 30min)
MIN_RANGE_ATR = 1.5      # 区间宽度 < 1.5 ATR 不计算目标


def calc_targets(support: float, resistance: float, atr: float,
                 structure: str) -> Optional[Dict]:
    """计算P&F止盈目标。

    Args:
        support: 区间支撑位
        resistance: 区间阻力位
        atr: 当前ATR
        structure: "ACCUMULATION" | "DISTRIBUTION"

    Returns:
        {"t1": float, "t2": float, "direction": "UP"|"DOWN",
         "support": float, "resistance": float} 或 None
    """
    width = resistance - support
    if width < atr * MIN_RANGE_ATR or atr <= 0:
        return None

    if structure in ("ACCUMULATION", "MARKUP"):
        # 向上突破: 目标在阻力上方
        t1 = resistance + width * T1_RATIO
        t2 = resistance + width * T2_RATIO
        return {"t1": round(t1, 4), "t2": round(t2, 4), "direction": "UP",
                "support": support, "resistance": resistance, "width": width}
    elif structure in ("DISTRIBUTION", "MARKDOWN"):
        # 向下突破: 目标在支撑下方
        t1 = support - width * T1_RATIO
        t2 = support - width * T2_RATIO
        return {"t1": round(t1, 4), "t2": round(t2, 4), "direction": "DOWN",
                "support": support, "resistance": resistance, "width": width}
    return None


def _load_targets() -> Dict:
    """加载持久化的目标状态。"""
    if _PNF_STATE_FILE.exists():
        try:
            return json.loads(_PNF_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_targets(data: Dict) -> None:
    """持久化目标状态。"""
    try:
        _PNF_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PNF_STATE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("[PNF] save targets: %s", e)


def update_targets(symbol: str, bars: List[dict]) -> Optional[Dict]:
    """检测区间并更新P&F目标。在Wyckoff Phase C/D时调用。

    复用 wyckoff_phase.py 的区间检测逻辑。
    """
    try:
        from wyckoff_phase import _extract_arrays, _calc_atr, _detect_range, detect_phase
    except ImportError:
        return None

    if not bars or len(bars) < 30:
        return None

    result = detect_phase(bars)
    phase = result.get("phase", "X")
    structure = result.get("structure", "UNKNOWN")

    # 只在Phase C/D时计算目标 (有明确区间+方向)
    if phase not in ("C", "D"):
        return None

    details = result.get("details", {})
    tr = details.get("range") or details.get("spring", {}).get("range")
    if not tr:
        return None

    highs, lows, closes, _, _ = _extract_arrays(bars)
    atr = _calc_atr(highs, lows, closes)

    targets = calc_targets(tr["support"], tr["resistance"], atr, structure)
    if not targets:
        return None

    # 持久化
    all_targets = _load_targets()
    all_targets[symbol] = {
        **targets,
        "phase": phase,
        "structure": structure,
        "atr": round(atr, 4),
        "created_ts": time.time(),
        "t1_pushed_ts": 0,
        "t2_pushed_ts": 0,
    }
    _save_targets(all_targets)
    logger.info("[PNF] %s 目标更新: T1=%.2f T2=%.2f dir=%s (Ph%s %s, range=%.2f-%.2f)",
                symbol, targets["t1"], targets["t2"], targets["direction"],
                phase, structure, tr["support"], tr["resistance"])
    return targets


def check_and_push(symbol: str, current_price: float, atr: float) -> int:
    """检查当前价格是否接近T1/T2目标，接近则推SELL信号到信号池。

    Args:
        symbol: 品种
        current_price: 当前价格
        atr: 当前ATR

    Returns:
        推送的信号数 (0, 1, or 2)
    """
    if current_price <= 0 or atr <= 0:
        return 0

    all_targets = _load_targets()
    entry = all_targets.get(symbol)
    if not entry:
        return 0

    t1 = entry.get("t1", 0)
    t2 = entry.get("t2", 0)
    direction = entry.get("direction", "UP")
    now = time.time()
    pushed = 0

    try:
        from gcc_trading_module import gcc_push_signal
    except ImportError:
        return 0

    # 方向判断: UP时到T1/T2推SELL(减仓), DOWN时到T1/T2推BUY(平空/减空)
    if direction == "UP":
        push_action = "SELL"
        t1_near = current_price >= t1 - atr * T1_PROXIMITY_ATR
        t2_near = current_price >= t2 - atr * T2_PROXIMITY_ATR
    else:
        push_action = "BUY"
        t1_near = current_price <= t1 + atr * T1_PROXIMITY_ATR
        t2_near = current_price <= t2 + atr * T2_PROXIMITY_ATR

    # T2优先 (更强信号)
    if t2_near and (now - entry.get("t2_pushed_ts", 0)) > TARGET_COOLDOWN:
        gcc_push_signal(symbol, "PnF_T2", push_action, T2_CONFIDENCE)
        entry["t2_pushed_ts"] = now
        pushed += 1
        logger.info("[PNF] %s T2目标(%.2f)触发 → %s (price=%.2f, conf=%.2f)",
                    symbol, t2, push_action, current_price, T2_CONFIDENCE)

    if t1_near and (now - entry.get("t1_pushed_ts", 0)) > TARGET_COOLDOWN:
        gcc_push_signal(symbol, "PnF_T1", push_action, T1_CONFIDENCE)
        entry["t1_pushed_ts"] = now
        pushed += 1
        logger.info("[PNF] %s T1目标(%.2f)触发 → %s (price=%.2f, conf=%.2f)",
                    symbol, t1, push_action, current_price, T1_CONFIDENCE)

    if pushed > 0:
        all_targets[symbol] = entry
        _save_targets(all_targets)

    return pushed
