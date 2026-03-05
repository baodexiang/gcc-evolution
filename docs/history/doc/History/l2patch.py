#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
patch_tv_l2_10m_v2.py

作用：
- 在当前目录中查找 tv_l2_10m_server.py；
- 先自动备份一份（带时间戳文件名）；
- 然后把该文件替换成“只看 10m K 线 + 成交量、专门识别假突破/假跌破”的 2.0-pre 版本。
"""

import os
import shutil
import datetime

NEW_CODE = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tv_l2_10m_server.py
2.0-pre 小周期 L2（10m）接收与分析服务

设计原则：
- 只看 10m K 线 + 成交量，不再在小周期内自建 Donchian / 支撑阻力线；
- 不负责“判断有没有突破/跌破”，只负责：
    1）识别假突破 / 假跌破（fake_breakout / fake_breakdown）；
    2）在关键位置给出 micro_reversal_10m / exec_bias_10m，供主程序的 micro_timing_gate 决定“多等几根 K 线”或“避免追高杀低”；
- 由主程序的大周期 L1/L2 决定结构与 SR，小周期只做局部质量过滤。
"""

import json
import os
from typing import Any, Dict, List, Optional

try:
    from flask import Flask, request, jsonify
except Exception:  # Flask 不是必需依赖
    Flask = None
    request = None
    jsonify = None


STATE_PATH_DEFAULT = os.environ.get("L2_10M_STATE_PATH", "l2_10m_state.json")


# ----------------------------------------------------------------------
# 工具函数：均值 / 成交量状态 / 相对位置分区
# ----------------------------------------------------------------------
def _safe_mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _volume_state(vols: List[float]) -> str:
    """根据最近 5 根 vs 更早的成交量对比，给出简单 volume_state_10m

    逻辑：
    - 最近 5 根均量 >= 2 倍历史均量          → CLIMAX
    - 最近 5 根均量在 [1.2, 2) × 历史均量   → RISING
    - 最近 5 根均量 <= 0.5 × 历史均量       → FALLING
    - 否则                                 → NORMAL
    """
    vols = [float(v) for v in vols if v is not None]
    if len(vols) < 3:
        return "UNKNOWN"

    if len(vols) <= 5:
        recent_mean = _safe_mean(vols)
        base_mean = recent_mean
    else:
        recent = vols[-5:]
        history = vols[:-5]
        recent_mean = _safe_mean(recent)
        base_mean = _safe_mean(history) or recent_mean

    if base_mean <= 0:
        return "UNKNOWN"

    ratio = recent_mean / base_mean
    if ratio >= 2.0:
        return "CLIMAX"
    if ratio >= 1.2:
        return "RISING"
    if ratio <= 0.5:
        return "FALLING"
    return "NORMAL"


def _pos_zone_from_range(last_close: float, lows: List[float], highs: List[float]) -> Dict[str, Any]:
    """根据 10m 窗口内的高低点，计算相对位置 pos_ratio_10m 与 pos_zone_10m

    注意：
    - 这里只是一个“区间相对位置”的粗略标签，并不是 Donchian SR。
    """
    lows = [float(x) for x in lows if x is not None]
    highs = [float(x) for x in highs if x is not None]

    if not lows or not highs:
        return {"pos_ratio": 0.5, "pos_zone": "MID"}

    window_low = min(lows)
    window_high = max(highs)
    if window_high <= window_low:
        return {"pos_ratio": 0.5, "pos_zone": "MID"}

    last_close = float(last_close)
    pos_ratio = (last_close - window_low) / (window_high - window_low)
    pos_ratio = max(0.0, min(1.0, pos_ratio))

    if pos_ratio <= 0.10:
        zone = "EXTREME_LOW"
    elif pos_ratio <= 0.35:
        zone = "LOW"
    elif pos_ratio <= 0.65:
        zone = "MID"
    elif pos_ratio <= 0.90:
        zone = "HIGH"
    else:
        zone = "EXTREME_HIGH"

    return {"pos_ratio": pos_ratio, "pos_zone": zone}


# ----------------------------------------------------------------------
# 模式识别：假突破 / 假跌破（只用 10m K 线本身）
# ----------------------------------------------------------------------
def _detect_fake_break_pattern(closes: List[float], highs: List[float], lows: List[float]) -> str:
    """识别 10m 级别的假突破 / 假跌破 模式

    约定：
    - 输入已经按“时间从旧到新”排序；
    - 我们只看最近最后一根 K，结合之前窗口的极值来判断：
        * FAKE_BREAKOUT：高点明显刺破之前高点，但收盘重新回到之前区间；
        * FAKE_BREAKDOWN：低点明显跌破之前低点，但收盘重新回到之前区间；
    - 这里只是一个粗略的 pattern 标签，交给主程序决定如何使用。
    """
    n = min(len(closes), len(highs), len(lows))
    if n < 3:
        return "NONE"

    closes = [float(c) for c in closes[-n:]]
    highs = [float(h) for h in highs[-n:]]
    lows = [float(l) for l in lows[-n:]]

    prev_high = max(highs[:-1])
    prev_low = min(lows[:-1])
    last_close = closes[-1]
    last_high = highs[-1]
    last_low = lows[-1]
    prev_close = closes[-2]

    if prev_high <= prev_low:
        return "NONE"

    # 允许的“刺破/跌破”容差
    edge_eps = 0.001
    wick_eps = 0.002

    # FAKE_BREAKOUT：当前高点显著高于之前高点，但收盘收回 prev_high 附近或之下
    if last_high > prev_high * (1.0 + edge_eps) and last_close <= prev_high:
        body_top = max(last_close, prev_close)
        if last_high >= body_top * (1.0 + wick_eps):
            return "FAKE_BREAKOUT"

    # FAKE_BREAKDOWN：当前低点显著低于之前低点，但收盘收回 prev_low 附近或之上
    if last_low < prev_low * (1.0 - edge_eps) and last_close >= prev_low:
        body_bottom = min(last_close, prev_close)
        if last_low <= body_bottom * (1.0 - wick_eps):
            return "FAKE_BREAKDOWN"

    return "NONE"


# ----------------------------------------------------------------------
# 核心：单次快照分析
# ----------------------------------------------------------------------
def analyze_l2_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """根据 10m K 线快照，输出 L2 小周期总结信号

    约定：
    - TradingView 侧传入的 highs/lows/close_prices/volumes 通常是“最新在前”的数组，
      这里会统一翻转为“时间从旧到新”再做分析；
    - 突破/跌破的存在与否，由主程序的大周期 L1/L2 决定，本函数只做局部质量过滤。
    """
    symbol = str(payload.get("symbol", "UNKNOWN"))
    timeframe = str(payload.get("timeframe", "10"))
    last_close = float(payload.get("last_close") or payload.get("close") or 0.0)

    # 兼容不同字段名
    highs = payload.get("highs") or []
    lows = payload.get("lows") or []
    closes = payload.get("close_prices") or payload.get("closes") or []
    vols = payload.get("volumes") or payload.get("volume") or []

    # TradingView 一般是“最新在前”，翻转为“旧→新”
    if highs:
        highs = list(reversed(highs))
    if lows:
        lows = list(reversed(lows))
    if closes:
        closes = list(reversed(closes))
    if vols:
        vols = list(reversed(vols))

    vol_state = _volume_state(vols) if vols else "UNKNOWN"
    pos_info = _pos_zone_from_range(
        last_close, lows or [last_close], highs or [last_close]
    )
    pos_ratio = pos_info["pos_ratio"]
    pos_zone = pos_info["pos_zone"]

    # 只用 10m K 线本身做假突破 / 假跌破检测
    fake_break_tag = (
        _detect_fake_break_pattern(closes, highs, lows)
        if closes and highs and lows
        else "NONE"
    )

    # 仍然保留 TV 侧的 10m PA edge，作为辅助信息，不再在小周期内计算 Donchian SR
    signal = str(payload.get("signal", "none") or "none").lower()
    level = str(payload.get("level", "none") or "none").lower()
    pa_buy_edge = bool(payload.get("pa_buy_edge"))
    pa_sell_edge = bool(payload.get("pa_sell_edge"))

    micro_reversal = "NONE"
    exec_bias = "FORCE_HOLD"

    # ------------------------------------------------------------------
    # 规则 1：极端低位 + 假跌破 / 多头 PA edge → MICRO_BOTTOM
    # ------------------------------------------------------------------
    if pos_zone in {"EXTREME_LOW", "LOW"} and vol_state in {"RISING", "CLIMAX"}:
        if fake_break_tag == "FAKE_BREAKDOWN" or pa_buy_edge:
            micro_reversal = "MICRO_BOTTOM"
            exec_bias = "STRONG_BUY"

    # ------------------------------------------------------------------
    # 规则 2：极端高位 + 假突破 / 空头 PA edge → MICRO_TOP
    # ------------------------------------------------------------------
    if pos_zone in {"EXTREME_HIGH", "HIGH"} and vol_state in {"RISING", "CLIMAX"}:
        if fake_break_tag == "FAKE_BREAKOUT" or pa_sell_edge:
            micro_reversal = "MICRO_TOP"
            exec_bias = "STRONG_SELL"

    # ------------------------------------------------------------------
    # 规则 3：非极端位置，仅给弱 bias（BUY_OK / SELL_OK），否则 FORCE_HOLD
    # ------------------------------------------------------------------
    if micro_reversal == "NONE":
        if pa_buy_edge and pos_zone in {"EXTREME_LOW", "LOW"}:
            exec_bias = "BUY_OK"
        elif pa_sell_edge and pos_zone in {"EXTREME_HIGH", "HIGH"}:
            exec_bias = "SELL_OK"
        else:
            exec_bias = "FORCE_HOLD"

    result: Dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "last_close": last_close,
        "volume_state_10m": vol_state,
        "pos_zone_10m": pos_zone,
        "pos_ratio_10m": pos_ratio,
        "micro_reversal_10m": micro_reversal,
        "exec_bias_10m": exec_bias,
        "fake_break_tag": fake_break_tag,
    }

    # 保留原始信号的关键字段，方便主程序/日志调试
    result["raw_signal_10m"] = {
        "signal": signal,
        "level": level,
        "pa_buy_edge": pa_buy_edge,
        "pa_sell_edge": pa_sell_edge,
        "n_bars": len(closes),
    }

    return result


# ----------------------------------------------------------------------
# 状态文件读写
# ----------------------------------------------------------------------
def _load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(path: str, state: Dict[str, Any]) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def update_state_file(payload: Dict[str, Any], state_path: Optional[str] = None) -> Dict[str, Any]:
    """更新 l2_10m_state.json 中某个 symbol 的快照，并返回最新结果"""
    if state_path is None:
        state_path = STATE_PATH_DEFAULT

    snapshot = analyze_l2_snapshot(payload)
    symbol = snapshot.get("symbol", "UNKNOWN")

    state = _load_state(state_path)
    snapshot["updated_at_ms"] = int(payload.get("time_ms") or 0)
    state[symbol] = snapshot
    _save_state(state_path, state)
    return snapshot


# ----------------------------------------------------------------------
# Flask 服务封装（保持与旧版本兼容）
# ----------------------------------------------------------------------
def create_app(state_path: Optional[str] = None):
    if Flask is None:
        raise RuntimeError("Flask 未安装，无法以服务模式运行 tv_l2_10m_server。")

    app = Flask(__name__)

    @app.route("/tv_l2_10m", methods=["POST"])
    def handle_tv_l2_10m():
        data = request.get_json(force=True, silent=True) or {}
        snapshot = update_state_file(data, state_path=state_path)
        return jsonify({"ok": True, "snapshot": snapshot})

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify(
            {
                "ok": True,
                "component": "tv_l2_10m_server",
                "version": "2.0-pre",
                "state_path": state_path or STATE_PATH_DEFAULT,
            }
        )

    return app


if __name__ == "__main__":
    # 作为独立服务运行：python tv_l2_10m_server.py
    if Flask is None:
        print(
            "Flask 未安装，本文件只能作为工具模块使用。\\n"
            "请先 `pip install flask` 后再以服务方式运行，"
            "或在主程序中直接导入 analyze_l2_snapshot / update_state_file。"
        )
    else:
        app = create_app()
        port = int(os.environ.get("L2_10M_PORT", "5000"))
        print(f"[tv_l2_10m_server] Listening on http://0.0.0.0:{port}/tv_l2_10m")
        app.run(host="0.0.0.0", port=port)
'''


def main():
    target = "tv_l2_10m_server.py"
    if not os.path.exists(target):
        print(f"[ERROR] 未找到 {target}，请确认补丁脚本与该文件在同一目录下。")
        return

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"tv_l2_10m_server_backup_{ts}.py"

    shutil.copy2(target, backup)
    print(f"[INFO] 已备份原文件到: {backup}")

    with open(target, "w", encoding="utf-8") as f:
        f.write(NEW_CODE)

    print(f"[OK] 已用新的 L2 小周期实现重写 {target}")
    print("     现在 tv_l2_10m_server.py 已是 2.0-pre 版本（只看 K 线 + 量能，检测假突破/假跌破）。")


if __name__ == "__main__":
    main()
