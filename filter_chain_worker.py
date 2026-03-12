#!/usr/bin/env python3
"""
FilterChain Worker — 本地三道闸门预热脚本 (v1.2)
=================================================
在本地运行, 计算三道闸门过滤结果并写入 state/filter_chain_state.json.
远程服务器通过 OneDrive 同步读取该文件, 无需安装 OpenBB.

架构:
    闸门1 Vision: 读 state/vision/pattern_latest.json (服务器同步过来)
    闸门2 Volume: yfinance OHLCV (本地直接拉)
    闸门3 Micro:  .GCC/improvement/signal_gate.py (OpenBB Hurst计算)
        ↓
    写 state/filter_chain_state.json → OneDrive同步 → 服务器读取

运行方式:
    python filter_chain_worker.py          # 运行一次
    python filter_chain_worker.py --loop   # 每4小时循环

依赖:
    state/vision/pattern_latest.json  (Vision形态, 服务器生成, OneDrive同步)
    yfinance                           (本地直接拉取OHLCV)
    .GCC/improvement/signal_gate.py         (Hurst微观结构计算, 需要OpenBB)
    .GCC/improvement/files/filter_chain.py  (vision_gate, volume_filter函数)
"""

import json
import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone

# GCC-0049fix: improvement/ 已迁移到 .GCC/improvement/
# .GCC 不是合法Python包名, 用 sys.path + 模块别名解决
_gcc_imp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".GCC")
if _gcc_imp_path not in sys.path:
    sys.path.insert(0, _gcc_imp_path)

os.makedirs("logs", exist_ok=True)
_fc_log_handler = logging.FileHandler("logs/filter_chain_worker.log", encoding="utf-8")
_fc_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(), _fc_log_handler])
log = logging.getLogger("FCWorker")

# 品种映射: 主程序符号 → yfinance符号
CRYPTO_SYMBOLS = {
    "BTCUSDC": "BTC-USD",
    "ETHUSDC": "ETH-USD",
    "SOLUSDC": "SOL-USD",
    "ZECUSDC": "ZEC-USD",
}

STOCK_SYMBOLS = [
    "TSLA", "COIN", "RDDT", "NBIS", "CRWV",
    "RKLB", "HIMS", "OPEN", "AMD", "ONDS", "PLTR",
]

PATTERN_LATEST_FILE = os.path.join("state", "vision", "pattern_latest.json")
STATE_PATH = os.path.join("state", "filter_chain_state.json")
REFRESH_INTERVAL = 1 * 3600  # GCC-0194: 1小时, 对齐Vision 1H刷新

# 形态→信号方向映射 (GCC-0194: 扩展支持Brooks 21种形态)
PATTERN_SIGNAL_MAP = {
    # 原12种
    "DOUBLE_BOTTOM": "BUY",
    "HEAD_SHOULDERS_BOTTOM": "BUY",
    "REVERSAL_123_BUY": "BUY",
    "FALSE_BREAK_BUY": "BUY",
    "ASC_TRIANGLE": "BUY",
    "WEDGE_FALLING": "BUY",
    "DOUBLE_TOP": "SELL",
    "HEAD_SHOULDERS_TOP": "SELL",
    "REVERSAL_123_SELL": "SELL",
    "FALSE_BREAK_SELL": "SELL",
    "DESC_TRIANGLE": "SELL",
    "WEDGE_RISING": "SELL",
    # Brooks新增方向型
    "CUP_AND_HANDLE": "BUY",
    "ROUNDING_BOTTOM": "BUY",
    "BULL_FLAG": "BUY",
    "BEAR_FLAG": "SELL",
    "MTR_BUY": "BUY",
    "MTR_SELL": "SELL",
    "HEAD_SHOULDERS": "SELL",  # 无方向时默认SELL
    # 环境型 (方向中性, 由direction字段决定)
    "CLIMAX": "NEUTRAL",
    "TIGHT_CHANNEL": "NEUTRAL",
    "BROAD_CHANNEL": "NEUTRAL",
    "BREAKOUT": "NEUTRAL",
    "TRADING_RANGE": "NEUTRAL",
}

# GCC-0199: BV形态黑名单 — 准确率<35%的形态在FilterChain也需拦截(同步brooks_vision.py)
BV_PATTERN_BLACKLIST = {"BEAR_FLAG"}


def _read_vision_result(symbol: str):
    """读取 pattern_latest.json 中指定品种的形态数据, 返回 (VisionResult, overall_structure, position)
    v1.1: 新增 overall_structure / position 字段透传
    GCC-0194: 新增 direction 字段, 环境型形态用direction推导bias"""
    from improvement.files.filter_chain import VisionResult
    try:
        if not os.path.exists(PATTERN_LATEST_FILE):
            return None, "UNKNOWN", "MID"
        with open(PATTERN_LATEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data.get(symbol)
        if not entry:
            return None, "UNKNOWN", "MID"
        pattern = entry.get("pattern", "NONE")
        confidence = entry.get("confidence") or 0.0
        bias = PATTERN_SIGNAL_MAP.get(pattern, "NEUTRAL")
        # GCC-0194: 环境型形态(NEUTRAL)用direction推导bias
        if bias == "NEUTRAL" or (pattern == "NONE" and entry.get("direction")):
            direction = str(entry.get("direction", "SIDE")).upper()
            if direction == "UP":
                bias = "BUY"
            elif direction == "DOWN":
                bias = "SELL"
            # SIDE保持NEUTRAL
        # GCC-0199: BV形态黑名单 → 强制NEUTRAL, 放在direction推导之后确保不被覆盖
        if pattern in BV_PATTERN_BLACKLIST:
            bias = "NEUTRAL"
        overall_structure = entry.get("overall_structure", "UNKNOWN")
        position = entry.get("position", "MID")
        vr = VisionResult(
            pattern=pattern,
            bias=bias,
            confidence=float(confidence),
            description=entry.get("reason", ""),
        )
        return vr, overall_structure, position
    except Exception as e:
        log.warning(f"  读取pattern_latest.json失败({symbol}): {e}")
        return None, "UNKNOWN", "MID"


def _fetch_ohlcv(yf_sym: str, period: str = "60d", interval: str = "1h"):
    """用yfinance拉取OHLCV, 返回 (closes, volumes)"""
    try:
        import yfinance as yf
        df = yf.download(yf_sym, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 20:
            return None, None
        # yfinance >= 0.2.31 returns MultiIndex columns; flatten
        if isinstance(df.columns, __import__('pandas').MultiIndex):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        closes = df["Close"].dropna().values.tolist()
        volumes = df["Volume"].dropna().values.tolist()
        n = min(len(closes), len(volumes))
        return closes[-n:], volumes[-n:]
    except Exception as e:
        log.warning(f"  yfinance拉取失败({yf_sym}): {e}")
        return None, None


def run_once():
    """计算所有品种的三道闸门结果并写入 JSON"""
    from improvement.files.filter_chain import vision_gate, volume_filter
    from improvement.signal_gate import SignalGate
    from filter_logger import write_filter_log as _wfl

    gate_equity = SignalGate(provider="yfinance", fallback="yfinance",
                             lookback_days=30, cache_ttl=REFRESH_INTERVAL, asset_type="equity")
    gate_crypto = SignalGate(provider="yfinance", fallback="yfinance",
                             lookback_days=30, cache_ttl=REFRESH_INTERVAL, asset_type="crypto")

    result = {}
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _process(main_sym, yf_sym, gate):
        """处理单个品种的三道闸门 (v1.1: 5步权重计算)"""
        result[main_sym] = {}
        vision, overall_structure, position = _read_vision_result(main_sym)
        closes, volumes = _fetch_ohlcv(yf_sym)

        for direction in ("BUY", "SELL"):
            try:
                # 闸门1: Vision
                v_decision, v_reason = vision_gate(vision, direction)

                # KEY-004: 因子观测台 record_signal — vision_gate (fail-silent)
                try:
                    from factor_db import record_signal as _rs_vg
                    _vg_sig = 0 if v_decision == "HOLD" else (1 if direction == "BUY" else -1)
                    _rs_vg(symbol=main_sym, factor_name="vision_gate",
                           signal=_vg_sig,
                           close_price=float(closes[-1]) if closes else None)
                except Exception:
                    pass

                # 闸门2: Volume
                vol_rvol, vol_pv, vol_obv = 0.0, 0.0, 0
                if closes and volumes and len(closes) >= 20:
                    vol = volume_filter(closes, volumes, direction)
                    vol_score = round(vol.score, 3)
                    vol_reason = vol.reason
                    vol_blocked = False  # v1.2: 观察模式，不拦截
                    vol_rvol = getattr(vol, "rvol", 0.0)
                    vol_pv   = getattr(vol, "pv_alignment", 0.0)
                    vol_obv  = getattr(vol, "obv_direction", 0)
                else:
                    vol_score = 1.0
                    vol_reason = "无量价数据,跳过Volume"
                    vol_blocked = False

                # 闸门3: Micro (Hurst微观结构) — 异常时fail-open
                try:
                    micro = gate.check(yf_sym, direction.lower())
                    micro_go = micro.go
                    # v1.2: 数据不可用时fail-open(不拦截)，避免误杀
                    if micro.reason and "数据不可用" in micro.reason:
                        micro_go = True
                        micro = type(micro)(True, micro.regime, micro.flow_direction,
                                            micro.alignment, micro.variance_ratio,
                                            micro.h0, "数据不可用→fail-open放行")
                except Exception as _micro_e:
                    log.warning(f"  {main_sym} {direction} micro异常: {_micro_e}")
                    from dataclasses import dataclass as _dc
                    @_dc
                    class _FallbackMicro:
                        go: bool = True
                        regime: str = "unknown"
                        flow_direction: str = "neutral"
                        alignment: str = "neutral"
                        variance_ratio: float = float('nan')
                        h0: float = float('nan')
                        reason: str = f"micro异常→fail-open: {_micro_e}"
                    micro = _FallbackMicro()
                    micro_go = True

                # 合并三门结果
                blocked_by = ""
                if v_decision == "HOLD":
                    blocked_by = "vision"
                elif vol_blocked:
                    blocked_by = "volume"
                # micro观察模式(v1.2): 不拦截, 仅记录到micro_go/micro_reason

                reason = (v_reason if blocked_by == "vision"
                          else vol_reason if blocked_by == "volume"
                          else micro.reason if blocked_by == "micro"
                          else "三道闸门全部通过")

                # v1.1: 5步权重计算
                weight = 1.0

                # Step 1: 历史结构位置权重
                if overall_structure != "UNKNOWN":
                    if position == "HIGH" and direction == "BUY":
                        weight *= 0.7   # 高位追多降权
                    elif position == "LOW" and direction == "SELL":
                        weight *= 0.7   # 低位追空降权
                    if overall_structure == "DISTRIBUTION" and direction == "BUY":
                        weight *= 0.7   # 派发区BUY降权
                    elif overall_structure == "ACCUMULATION" and direction == "SELL":
                        weight *= 0.7   # 积累区SELL降权

                # Step 2: 形态冲突直接清零
                if v_decision == "HOLD":
                    weight = 0.0

                # Step 3: Volume健康加成 — v3.670: 已取消(量经常出意外)
                # if not vol_blocked and vol_score >= 0.7:
                #     weight = round(weight * 1.1, 3)

                # Step 4: 计算 execution_size
                # v1.3: SKIP阈值从0.5降至0.35 — 防止双降权(0.7*0.7=0.49)误杀
                # VisionPattern 95触发0派发全因compound penalty低于0.5
                if v_decision == "HOLD" or weight == 0.0:
                    execution_size = "SKIP"
                elif weight >= 1.2:
                    execution_size = "FULL"
                elif weight >= 0.8:
                    execution_size = "STANDARD"
                elif weight >= 0.35:
                    execution_size = "REDUCED"
                else:
                    execution_size = "SKIP"

                # Step 5: SKIP → passed=False (Phase2: Vision权重门控真拦截)
                passed = (blocked_by == "")
                if execution_size == "SKIP":
                    passed = False
                    if not blocked_by:
                        blocked_by = "weight"

                result[main_sym][direction] = {
                    "passed": passed,
                    "blocked_by": blocked_by,
                    "vision": v_decision,
                    "vision_reason": v_reason,
                    "overall_structure": overall_structure,   # v1.1 新增
                    "position": position,                      # v1.1 新增
                    "final_weight": round(weight, 3),          # v1.1 新增
                    "execution_size": execution_size,           # v1.1 新增
                    "volume_score": vol_score,
                    "volume_reason": vol_reason,
                    "micro_go": micro.go,
                    "micro_regime": micro.regime,
                    "micro_reason": micro.reason,
                    "reason": reason,
                    "ts": ts_now,
                }
                log.info(f"  {main_sym} {direction}: passed={passed} blocked={blocked_by!r} "
                         f"struct={overall_structure}/{position} size={execution_size}(w={weight:.2f}) "
                         f"vision={v_decision} vol={vol_score:.0%} micro={micro.go}")

                # KEY-001 T07: FilterLog 审计落盘 (fail-silent)
                try:
                    _last_price = closes[-1] if closes else 0.0
                    _vr = getattr(micro, "variance_ratio", 0.0)
                    _wfl(
                        symbol=main_sym,
                        direction=direction,
                        passed=passed,
                        blocked_by=blocked_by,
                        reason=reason,
                        vision_result=vision,
                        vision_decision=v_decision,
                        vision_reason=v_reason,
                        vol_score=vol_score,
                        vol_reason=vol_reason,
                        vol_rvol=vol_rvol,
                        vol_pv_alignment=vol_pv,
                        vol_obv_direction=vol_obv,
                        micro_go=micro.go,
                        micro_regime=micro.regime,
                        micro_flow=getattr(micro, "flow_direction", ""),
                        micro_alignment=getattr(micro, "alignment", ""),
                        micro_vr=_vr if _vr == _vr else 0.0,
                        micro_h0=getattr(micro, "h0", 0.0),
                        micro_reason=micro.reason,
                        current_price=_last_price,
                    )
                except Exception:
                    pass

            except Exception as e:
                log.warning(f"  {main_sym} {direction} 失败: {e}")
                result[main_sym][direction] = {
                    "passed": None, "blocked_by": "error",
                    "reason": str(e), "ts": ts_now,
                }

    # 加密货币
    for main_sym, yf_sym in CRYPTO_SYMBOLS.items():
        log.info(f"Computing {main_sym} ({yf_sym}) crypto...")
        _process(main_sym, yf_sym, gate_crypto)

    # 美股
    for sym in STOCK_SYMBOLS:
        log.info(f"Computing {sym} stock...")
        _process(sym, sym, gate_equity)

    result["_meta"] = {
        "updated_at": ts_now,
        "version": "v1.2",
        "symbols": list(CRYPTO_SYMBOLS.keys()) + STOCK_SYMBOLS,
    }

    os.makedirs("state", exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    log.info(f"已写入 {STATE_PATH} ({len(result) - 1} 个品种)")

    # KNN历史库更新已移到主程序boot区(共享同一模块实例)


def main():
    ap = argparse.ArgumentParser(description="FilterChain Worker v1.0")
    ap.add_argument("--loop", action="store_true", help="每4小时循环运行")
    args = ap.parse_args()

    if args.loop:
        log.info(f"循环模式: 每 {REFRESH_INTERVAL // 3600} 小时刷新")
        while True:
            try:
                run_once()
            except Exception as e:
                log.error(f"run_once 失败: {e}", exc_info=True)
            log.info(f"下次刷新: {REFRESH_INTERVAL // 3600} 小时后")
            time.sleep(REFRESH_INTERVAL)
    else:
        run_once()


if __name__ == "__main__":
    main()
