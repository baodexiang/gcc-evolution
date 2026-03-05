#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tv_l2_10m_server.py
1.995 小周期 L2 接收与分析服务

作用：
1. 接收 TradingView 10m 周期 Pine 脚本发来的 JSON 报警；
2. 解析 Donchian + PA edge + 120 根价格/成交量数据；
3. 生成简化后的 10m L2 总结信号（micro_reversal_10m / exec_bias_10m 等）；
4. 将每个 symbol 的最新 L2 状态持久化到 l2_10m_state.json，供主程序按需读取。

如果只想当作工具模块使用，可以：
    from tv_l2_10m_server import analyze_l2_snapshot, update_state_file
"""

import json
import os
import statistics
import time
from typing import Any, Dict, List

try:
    from flask import Flask, request, jsonify
except ImportError:  # 允许作为纯工具库使用
    Flask = None
    request = None
    jsonify = None

STATE_FILE_DEFAULT = "l2_10m_state.json"


# ==================== 工具函数：读写状态 ====================


def _load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ==================== 10m 数据分析核心 ====================


def _volume_state(vols: List[float]) -> str:
    """根据最近 5 根与之前的对比粗略判断量能状态。"""
    if not vols:
        return "UNKNOWN"
    # 使用最近 5 根 vs 其余作为基准
    recent = vols[-5:]
    base = vols[:-5] or vols
    mean_recent = statistics.fmean(recent)
    mean_base = statistics.fmean(base)
    if mean_base == 0:
        return "NORMAL"
    ratio = mean_recent / mean_base
    if ratio >= 2.0:
        return "CLIMAX"
    elif ratio >= 1.3:
        return "RISING"
    elif ratio <= 0.6:
        return "FALLING"
    else:
        return "NORMAL"


def _pos_zone_from_range(
    last_close: float, lows: List[float], highs: List[float]
) -> Dict[str, Any]:
    lo = min(lows)
    hi = max(highs)
    if hi <= lo:
        return {"pos_ratio": 0.5, "pos_zone": "MID"}
    pos_ratio = (last_close - lo) / (hi - lo)
    if pos_ratio <= 0.1:
        zone = "EXTREME_LOW"
    elif pos_ratio <= 0.35:
        zone = "LOW"
    elif pos_ratio <= 0.65:
        zone = "MID"
    elif pos_ratio <= 0.9:
        zone = "HIGH"
    else:
        zone = "EXTREME_HIGH"
    return {"pos_ratio": pos_ratio, "pos_zone": zone}

#2
def analyze_l2_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """将 TradingView 10m L2 JSON 解析为小周期总结信号。

    预期 payload 结构（由 Pine 脚本发送）大致为：

        {
          "role": "l2_10m",
          "symbol": "BTCUSDT.P",
          "timeframe": "10",
          "time_ms": 1700000000000,
          "signal": "cross_over" | "cross_under" | "none",
          "level": "upper" | "basis" | "lower" | "none",
          "pa_buy_edge": true/false,
          "pa_sell_edge": true/false,
          "highs": [...],
          "lows": [...],
          "close_prices": [...],
          "volumes": [...],
          "last_close": 43000.5
        }

    注意：Pine 数组里 index=0 是当前 K 线，我们这里统一翻转为
    旧 -> 新 方便后续分析。
    """
    role = payload.get("role") or "l2_10m"
    symbol = payload.get("symbol", "")
    timeframe = payload.get("timeframe", "")
    time_ms = int(payload.get("time_ms", int(time.time() * 1000)))
    last_close = float(payload.get("last_close", 0.0))

    highs = [float(x) for x in payload.get("highs", [])]
    lows = [float(x) for x in payload.get("lows", [])]
    closes = [float(x) for x in payload.get("close_prices", [])]
    vols = [float(x) for x in payload.get("volumes", [])]

    # Pine 中 push(close[i]) 时 i=0 是当前 K，这里翻转为旧 -> 新
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
    # === v1.995: 上一根 Donchian SR + 突破/跌破确认 ===
    prev_donchian_upper_10m = None
    prev_donchian_lower_10m = None
    prev_donchian_mid_10m = None
    try:
        if highs and lows and len(highs) >= 2 and len(lows) >= 2:
            _hi = max(highs[:-1])
            _lo = min(lows[:-1])
            if _hi >= _lo:
                prev_donchian_upper_10m = float(_hi)
                prev_donchian_lower_10m = float(_lo)
                prev_donchian_mid_10m = float((_hi + _lo) / 2.0)
    except Exception:
        pass

    confirm_tag = "NONE"
    try:
        _eps = 0.001
        if (
            prev_donchian_upper_10m is not None
            and last_close is not None
            and last_close > prev_donchian_upper_10m * (1.0 + _eps)
        ):
            # 上轨真突破：配合 cross_over / 买边 PA / 上轨 level 任意一项
            if (signal == "cross_over") or pa_buy_edge or (level == "upper"):
                confirm_tag = "TRUE_BREAKOUT"
        elif (
            prev_donchian_lower_10m is not None
            and last_close is not None
            and last_close < prev_donchian_lower_10m * (1.0 - _eps)
        ):
            # 下轨真跌破：配合 cross_under / 卖边 PA / 下轨 level 任意一项
            if (signal == "cross_under") or pa_sell_edge or (level == "lower"):
                confirm_tag = "TRUE_BREAKDOWN"
    except Exception:
        confirm_tag = "NONE"
    

    signal = payload.get("signal", "none")
    level = payload.get("level", "none")
    pa_buy_edge = bool(payload.get("pa_buy_edge", False))
    pa_sell_edge = bool(payload.get("pa_sell_edge", False))

    # ========= 简化版 micro bottom / top + 执行偏向 =========
    micro_reversal = "NONE"
    exec_bias = "FORCE_HOLD"

    # 下轨突破 + pa_buy_edge + 低位 + 放量 ≈ 小级别企稳/反转
    if (
        level == "lower"
        and signal == "cross_over"
        and pa_buy_edge
        and pos_zone in ("EXTREME_LOW", "LOW")
        and vol_state in ("RISING", "CLIMAX")
    ):
        micro_reversal = "MICRO_BOTTOM"
        exec_bias = "STRONG_BUY"

    # 上轨跌破 + pa_sell_edge + 高位 + 放量 ≈ 小级别见顶/转弱
    elif (
        level == "upper"
        and signal == "cross_under"
        and pa_sell_edge
        and pos_zone in ("EXTREME_HIGH", "HIGH")
        and vol_state in ("RISING", "CLIMAX")
    ):
        micro_reversal = "MICRO_TOP"
        exec_bias = "STRONG_SELL"

    else:
        # 二级：没有明显反转时，用位置 + PA 给偏向
        if pa_buy_edge and pos_zone in ("EXTREME_LOW", "LOW"):
            exec_bias = "BUY_OK"
        elif pa_sell_edge and pos_zone in ("EXTREME_HIGH", "HIGH"):
            exec_bias = "SELL_OK"
        else:
            exec_bias = "FORCE_HOLD"

    return {
        "role": role,
        "symbol": symbol,
        "timeframe": timeframe,
        "time_ms": time_ms,
        "last_close": last_close,
        "pos_ratio_10m": pos_ratio,
        "pos_zone_10m": pos_zone,
        "volume_state_10m": vol_state,
        "donchian_level_10m": level,
        "donchian_signal_10m": signal,
        "pa_buy_edge_10m": pa_buy_edge,
        "pa_sell_edge_10m": pa_sell_edge,
        "prev_donchian_upper_10m": prev_donchian_upper_10m,
        "prev_donchian_lower_10m": prev_donchian_lower_10m,
        "prev_donchian_mid_10m": prev_donchian_mid_10m,
        "confirm_tag": confirm_tag,
        "micro_reversal_10m": micro_reversal,
        "exec_bias_10m": exec_bias,
    }


def update_state_file(
    payload: Dict[str, Any], path: str = STATE_FILE_DEFAULT
) -> Dict[str, Any]:
    """分析一条 L2 报警并写入状态文件，返回总结结果。"""
    summary = analyze_l2_snapshot(payload)
    state = _load_state(path)
    sym = summary.get("symbol") or "UNKNOWN"
    state[sym] = summary
    _save_state(path, state)
    return summary

#3
# ==================== Flask 服务入口（可选） ====================


def _extract_payload_from_request(req) -> Dict[str, Any]:
    """从 TradingView 的 Webhook 请求中提取真正的 JSON payload。

    兼容两种常见用法：
      1）直接将 Pine 生成的 JSON 作为报警消息发送；
      2）外面再包一层 { "message": "<Pine JSON 字符串>" }。
    """
    try:
        raw = req.get_data(as_text=True) or ""
    except Exception:
        raw = ""

    raw = (raw or "").strip()
    if not raw:
        return {}

    # 先尝试直接解析
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            if "symbol" in data and "timeframe" in data:
                return data
            # 可能是 { "message": "...." }
            msg = data.get("message") or data.get("alert") or data.get("payload")
            if isinstance(msg, str):
                try:
                    return json.loads(msg)
                except json.JSONDecodeError:
                    pass
    except json.JSONDecodeError:
        pass

    # 再尝试 req.get_json()
    try:
        body = req.get_json(silent=True) or {}
        if isinstance(body, dict):
            if "symbol" in body and "timeframe" in body:
                return body
            msg = body.get("message") or body.get("alert") or body.get("payload")
            if isinstance(msg, str):
                try:
                    return json.loads(msg)
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass

    return {}


def create_app(state_file: str = STATE_FILE_DEFAULT):
    if Flask is None:
        raise RuntimeError(
            "Flask 未安装。请先 `pip install flask`，"
            "或仅导入本文件中的 analyze_l2_snapshot/update_state_file 函数使用。"
        )

    app = Flask(__name__)

    @app.route("/tv_l2_10m", methods=["POST"])
    def tv_l2_10m():
        payload = _extract_payload_from_request(request)
        if not payload:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "empty_or_invalid_payload",
                    }
                ),
                400,
            )
        summary = update_state_file(payload, path=state_file)
        return jsonify({"ok": True, "summary": summary})

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify({"ok": True, "service": "tv_l2_10m", "version": "1.995"})

    return app


if __name__ == "__main__":
    # 作为独立服务运行：python tv_l2_10m_server.py
    if Flask is None:
        print(
            "Flask 未安装，本文件只能作为工具模块使用。\n"
            "请先 `pip install flask` 后再以服务方式运行，"
            "或在主程序中直接导入 analyze_l2_snapshot/update_state_file。"
        )
    else:
        app = create_app()
        port = int(os.environ.get("L2_10M_PORT", "5000"))
        print(f"[tv_l2_10m_server] Listening on http://0.0.0.0:{port}/tv_l2_10m")
        app.run(host="0.0.0.0", port=port)
