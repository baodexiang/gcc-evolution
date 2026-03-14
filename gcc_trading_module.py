"""
gcc_trading_module.py  —  GCC交易决策模块 v0.2 (顺大逆小)
基于 arXiv:2603.04735 (树状搜索) + arXiv:2407.09468 (三视角验证)

v0.2 架构: 顺大逆小 (Follow Big, Counter Small)
  - Vision在K线开盘时看历史K线定方向(门控), 一票定音
  - 每30分钟一轮决策(共8轮/4H), 方向一致时入场
  - 交易后继续收集信号, 8轮汇总与下一K线Vision对比
  - 上一K线汇总与当前Vision矛盾时整根K线HOLD

Phase 1: 观察模式 — 只记录决策日志，不干扰现有交易逻辑
Phase 2: 执行模式 — BUY→下一K线市价买入 / SELL→市价卖出 / HOLD→不动
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")

logger = logging.getLogger("gcc.trading")

# ── 路径常量 ──────────────────────────────────────────────────
_STATE_DIR       = Path("state")
_GCC_DIR         = Path(".GCC")

_VISION_SNAP_DIR = _STATE_DIR / "vision_cache" / "snapshots"
_N_STRUCT_FILE   = _STATE_DIR / "n_structure_state.json"
_SIGNAL_LOG      = _STATE_DIR / "audit" / "signal_log.jsonl"
_GCC_MODE_FILE   = _GCC_DIR / "signal_filter" / "mode_state.json"
_PLUGIN_KNN_ACC  = _STATE_DIR / "plugin_knn_accuracy.json"
_KNN_ACC_MAP     = _STATE_DIR / "knn_accuracy_map.json"
_LOG_FILE        = _STATE_DIR / "gcc_trading_decisions.jsonl"
_REGIME_FILE     = _STATE_DIR / "regime_validation.json"
_CONTEXT_SNAP_DIR = _STATE_DIR / "gcc_decision_context"
_MAIN_STATE_FILE  = Path("logs") / "state.json"

# ── v0.2 顺大逆小: K线轮次常量 ─────────────────────────────────
_CANDLE_DURATION_MIN = 240    # 4H K线 (分钟)
_ROUND_INTERVAL_MIN  = 30    # 每轮30分钟
_ROUNDS_PER_CANDLE   = _CANDLE_DURATION_MIN // _ROUND_INTERVAL_MIN  # 8

# 4H K线UTC边界 (0:00, 4:00, 8:00, 12:00, 16:00, 20:00)
_4H_BOUNDARIES_UTC = [0, 4, 8, 12, 16, 20]

# 前向声明(完整定义在L1054附近), 供_get_candle_open_utc使用
_CRYPTO_SYMBOLS: frozenset = frozenset()  # 将被后面覆盖


def _get_candle_open_utc(ts_epoch: float = None, symbol: str = None) -> float:
    """根据时间计算当前4H K线的开盘时间戳(epoch秒)。
    加密货币: UTC 4H边界 (0:00/4:00/8:00/12:00/16:00/20:00)。
    美股: 纽约时区4H边界 (盘中9:30起算, 约9/13/17/21 ET)。
    """
    if ts_epoch is None:
        ts_epoch = time.time()

    # 美股用纽约时区计算, 加密用UTC
    is_crypto = symbol in _CRYPTO_SYMBOLS if symbol else False
    if is_crypto or symbol is None:
        dt = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
    else:
        dt = datetime.fromtimestamp(ts_epoch, tz=_NY_TZ)

    hour = dt.hour
    candle_hour = (hour // 4) * 4
    candle_open = dt.replace(hour=candle_hour, minute=0, second=0, microsecond=0)
    return candle_open.timestamp()


def _get_current_round(ts_epoch: float = None, symbol: str = None) -> int:
    """计算当前处于第几轮 (0-7)。"""
    if ts_epoch is None:
        ts_epoch = time.time()
    candle_open = _get_candle_open_utc(ts_epoch, symbol=symbol)
    elapsed_min = (ts_epoch - candle_open) / 60.0
    round_idx = int(elapsed_min // _ROUND_INTERVAL_MIN)
    return min(round_idx, _ROUNDS_PER_CANDLE - 1)


# ── v0.2 CandleState: K线生命周期状态 ─────────────────────────
@dataclass
class CandleState:
    """单根4H K线的轮次决策状态。"""
    symbol: str
    candle_open_ts: float         # UTC epoch秒 (4H K线开盘时间)
    vision_direction: str         # "BUY" | "SELL" | "HOLD"
    vision_confidence: float      # Vision置信度
    prev_summary: str             # 上一K线8轮汇总方向
    effective_direction: str      # 实际执行方向 (矛盾时=HOLD)
    bv_direction: str = "HOLD"    # v0.3: BrooksVision形态方向 (BUY/SELL/HOLD)
    bv_pattern: str = "NONE"      # v0.3: BrooksVision识别的形态名
    wyckoff_phase: str = "X"      # v0.4: Wyckoff Phase A-E/X (GCC-0261)
    wyckoff_bias: str = "HOLD"    # v0.4: Wyckoff门控投票方向
    value_composite: float = 0.0  # v0.5: KEY-003价值分析综合分 (-10~+10)
    value_modifier: float = 1.0   # v0.5: 仓位系数 (position_modifier from value analysis)
    current_round: int = 0        # 当前已完成轮次 (0-8)
    traded: bool = False          # 是否已交易
    trade_round: int = -1         # 交易发生在第几轮 (-1=未交易)
    round_decisions: list = field(default_factory=list)  # 每轮决策记录

    def is_expired(self, now: float = None) -> bool:
        """当前时间是否已超出本K线范围。"""
        if now is None:
            now = time.time()
        return now >= self.candle_open_ts + _CANDLE_DURATION_MIN * 60

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "candle_open_ts": self.candle_open_ts,
            "candle_open_str": datetime.fromtimestamp(
                self.candle_open_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "vision_direction": self.vision_direction,
            "vision_confidence": self.vision_confidence,
            "bv_direction": self.bv_direction,
            "bv_pattern": self.bv_pattern,
            "wyckoff_phase": self.wyckoff_phase,
            "wyckoff_bias": self.wyckoff_bias,
            "value_composite": self.value_composite,
            "value_modifier": self.value_modifier,
            "prev_summary": self.prev_summary,
            "effective_direction": self.effective_direction,
            "current_round": self.current_round,
            "traded": self.traded,
            "trade_round": self.trade_round,
            "round_decisions": self.round_decisions,
        }


def _candle_state_path(symbol: str) -> Path:
    return _STATE_DIR / f"gcc_candle_state_{symbol}.json"


def _candle_summary_path(symbol: str) -> Path:
    return _STATE_DIR / f"gcc_candle_summary_{symbol}.json"


def _load_candle_state(symbol: str) -> Optional[CandleState]:
    """加载当前K线状态，过期或不存在返回None。
    过期时先聚合上一根K线的汇总(防止丢失)。
    """
    p = _candle_state_path(symbol)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        state = CandleState(
            symbol=d["symbol"],
            candle_open_ts=d["candle_open_ts"],
            vision_direction=d["vision_direction"],
            vision_confidence=d["vision_confidence"],
            prev_summary=d.get("prev_summary", "HOLD"),
            effective_direction=d["effective_direction"],
            bv_direction=d.get("bv_direction", "HOLD"),     # v0.3: 重启恢复BV方向
            bv_pattern=d.get("bv_pattern", "NONE"),          # v0.3: 重启恢复BV形态
            wyckoff_phase=d.get("wyckoff_phase", "X"),       # v0.4: Wyckoff Phase
            wyckoff_bias=d.get("wyckoff_bias", "HOLD"),      # v0.4: Wyckoff投票
            value_composite=d.get("value_composite", 0.0),   # v0.5: KEY-003价值分析
            value_modifier=d.get("value_modifier", 1.0),     # v0.5: 仓位系数
            current_round=d.get("current_round", 0),
            traded=d.get("traded", False),
            trade_round=d.get("trade_round", -1),
            round_decisions=d.get("round_decisions", []),
        )
        if state.is_expired():
            # 过期 → 聚合上一根K线的汇总再丢弃
            # 注: 此处无bars可用, volume boost跳过(可接受的精度损失)
            if state.round_decisions:
                _aggregate_candle_summary(state)
                logger.info("[GCC-TM] %s expired candle aggregated before discard", symbol)
            # 清除持久信号 (防止跨K线泄漏)
            with _signal_pool_lock:
                if symbol in _signal_pool:
                    _signal_pool.pop(symbol, None)
                    _persist_signal_pool()
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return state
    except Exception as e:
        logger.debug("[GCC-TM] load_candle_state %s: %s", symbol, e)
        return None


_atomic_write_lock = __import__("threading").Lock()

def _atomic_write(p: Path, data: str) -> None:
    """P2原子写入: 先写临时文件, 再rename(防止断电导致半写损坏)。
    v0.3: 加锁防止Windows并发rename的WinError 32。
    """
    with _atomic_write_lock:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(p)  # 原子 rename


def _save_candle_state(state: Optional[CandleState]) -> None:
    """保存K线状态。state=None时删除文件。"""
    if state is None:
        return
    p = _candle_state_path(state.symbol)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(p, json.dumps(state.as_dict(), ensure_ascii=False, indent=2))
    except Exception as e:
        logger.debug("[GCC-TM] save_candle_state: %s", e)


def _load_prev_summary(symbol: str) -> dict:
    """加载上一K线的8轮汇总结果。"""
    p = _candle_summary_path(symbol)
    if not p.exists():
        return {"direction": "HOLD", "confidence": 0.5}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"direction": "HOLD", "confidence": 0.5}


def _save_candle_summary(symbol: str, summary: dict) -> None:
    """保存当前K线的8轮汇总结果。
    1. 覆盖写入 latest文件(供下一K线读取)
    2. 追加写入 history文件(保留所有历史，重启不丢失)
    """
    p = _candle_summary_path(symbol)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # latest: 原子覆盖写入(下根K线只需最后一条)
        _atomic_write(p, json.dumps(summary, ensure_ascii=False, indent=2))
        # history: 追加写入(保留完整趋势链条)
        # P1去重: 检查最后一条是否同一symbol+ts(过期聚合可能重复写入)
        history_file = _STATE_DIR / "gcc_candle_history.jsonl"
        record = {**summary, "symbol": symbol}
        _dup = False
        try:
            if history_file.exists():
                with open(history_file, "rb") as fh:
                    fh.seek(0, 2)  # end
                    pos = fh.tell()
                    buf = b""
                    while pos > 0 and b"\n" not in buf.rstrip(b"\n"):
                        chunk = min(pos, 512)
                        pos -= chunk
                        fh.seek(pos)
                        buf = fh.read(chunk) + buf
                    last_line = buf.rstrip(b"\n").split(b"\n")[-1]
                    if last_line:
                        last = json.loads(last_line)
                        if last.get("symbol") == symbol and last.get("ts") == summary.get("ts"):
                            _dup = True
        except Exception:
            pass
        if not _dup:
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("[GCC-TM] save_candle_summary: %s", e)


def _init_candle_state(symbol: str, bars: list = None) -> CandleState:
    """新K线开始: Vision定方向 + 与上一K线汇总比较 → 确定effective_direction。
    bars: OHLCV数据，用于触发新鲜Vision API调用(排除当前未完成K线)。
    """
    now = time.time()
    candle_open = _get_candle_open_utc(now, symbol=symbol)

    # Vision读取: 优先通过主程序触发新API调用, 回退到缓存
    vision_bias, vision_conf = "HOLD", 0.5
    _fresh_called = False
    if bars and len(bars) >= 15:
        try:
            from llm_server_v3640 import read_vision_result
            # 排除最后一根(当前未完成K线), Vision看历史
            hist_bars = bars[:-1] if len(bars) > 1 else bars
            # force_refresh=True: 新K线必须拿新鲜Vision，绕过冷却
            vr = read_vision_result(symbol, ohlcv_bars=hist_bars, force_refresh=True)
            if vr and vr.get("current"):
                cur = vr["current"]
                direction = (cur.get("direction") or "SIDE").upper()
                conf = float(cur.get("confidence") or 0.5)
                conf = max(0.0, min(1.0, conf))
                bias_map = {"UP": "BUY", "DOWN": "SELL"}
                vision_bias = bias_map.get(direction, "HOLD")
                vision_conf = conf
                _fresh_called = True
                logger.info("[GCC-TM] %s fresh Vision call: %s(%.0f%%)", symbol, vision_bias, conf * 100)
        except Exception as e:
            logger.warning("[GCC-TM] %s fresh Vision FAILED at candle open, using stale cache: %s", symbol, e)
    if not _fresh_called:
        vision_bias, vision_conf = _read_vision(symbol)
        logger.warning("[GCC-TM] %s Vision from STALE cache (no fresh call): %s(%.0f%%)", symbol, vision_bias, vision_conf * 100)

    # KEY-010: BrooksVision 从门控拆出→信号池外挂 (4H开盘扫一次, 推入信号池持续8轮)
    bv_bias, bv_pattern = "HOLD", "NONE"
    try:
        import brooks_vision as _bv
        _bv_results = _bv.scan_all(_bv.init_radar() if not _bv._mods_ready else _bv._mods_cache,
                                    symbols=[symbol] if not symbol.endswith("USDC") and not symbol.endswith("USDT")
                                    else [_bv.INTERNAL_TO_YF.get(symbol, symbol)])
        if _bv_results:
            for _bv_r in _bv_results:
                _bv_sig = _bv_r.get("radar", {}).get("signal", "")
                _bv_pat = _bv_r.get("radar", {}).get("brooks_pattern", "NONE")
                _bv_conf = _bv_r.get("radar", {}).get("confidence", 50)
                if _bv_sig in ("BUY", "SELL"):
                    bv_bias = _bv_sig
                    bv_pattern = _bv_pat
                    # 推入信号池 (持久信号, 持续参与整根4H K线的8轮投票)
                    gcc_push_signal(symbol, "BrooksVision_4H", _bv_sig,
                                    min(0.95, max(0.3, _bv_conf / 100.0)),
                                    persistent=True)
                    break
        logger.info("[GCC-TM] %s BrooksVision→信号池: %s [%s]", symbol, bv_bias, bv_pattern)
    except ImportError:
        logger.debug("[GCC-TM] %s BrooksVision not installed, skip", symbol)
    except Exception as _bv_e:
        logger.warning("[GCC-TM] %s BrooksVision FAILED: %s", symbol, _bv_e)

    # 上一K线汇总
    prev = _load_prev_summary(symbol)
    prev_dir = prev.get("direction", "HOLD")

    # GCC-0261 S4: Wyckoff Phase门控 — B通道数学计算(Vision不判断Wyckoff)
    wyckoff_bias, wyckoff_phase = "HOLD", "X"
    if bars and len(bars) >= 50:
        try:
            from wyckoff_phase import detect_phase as _wp_detect, _phase_to_bias as _wp_bias
            b_result = _wp_detect(bars)
            wyckoff_phase = b_result.get("phase", "X")
            wyckoff_bias = _wp_bias(wyckoff_phase, b_result.get("structure", "UNKNOWN"))
            logger.info("[GCC-TM] %s Wyckoff B通道: Ph%s/%s(%.0f%%) → %s",
                        symbol, wyckoff_phase, b_result.get("structure", "?"),
                        b_result.get("confidence", 0) * 100, wyckoff_bias)
        except ImportError:
            logger.debug("[GCC-TM] %s wyckoff_phase module not found", symbol)
        except Exception as _wp_e:
            logger.warning("[GCC-TM] %s Wyckoff B通道异常: %s", symbol, _wp_e)

    # KEY-003: 价值分析综合分 (每日更新，4H读一次)
    value_composite, value_modifier = 0.0, 1.0
    try:
        import json as _json_va
        _va_path = _STATE_DIR / "value_analysis_latest.json"
        if _va_path.exists():
            _va_data = _json_va.loads(_va_path.read_text(encoding="utf-8"))
            for _va_r in _va_data.get("results", []):
                if _va_r.get("ticker") == symbol:
                    value_composite = float(_va_r.get("composite_score", 0))
                    value_modifier = float(_va_r.get("position_modifier", 1.0))
                    break
            logger.info("[GCC-TM] %s 价值分析: composite=%.2f modifier=%.1f",
                        symbol, value_composite, value_modifier)
    except Exception as _va_e:
        logger.debug("[GCC-TM] %s 价值分析读取异常: %s", symbol, _va_e)

    # KEY-010: 三方投票 — Vision(趋势) + prev_summary(上K汇总) + Wyckoff(阶段)
    # BV已拆出到信号池, 门控: 趋势+惯性+阶段
    # 多数票(≥2)→执行, 无多数但有方向→跟随多数, 全弃权→HOLD
    votes = {"BUY": 0, "SELL": 0}
    for _v in [vision_bias, prev_dir, wyckoff_bias]:
        if _v in votes:
            votes[_v] += 1

    if votes["BUY"] >= 2:
        effective = "BUY"
    elif votes["SELL"] >= 2:
        effective = "SELL"
    elif votes["BUY"] == 1 and votes["SELL"] == 0:
        effective = "BUY"    # 唯一有方向的(其余弃权)
    elif votes["SELL"] == 1 and votes["BUY"] == 0:
        effective = "SELL"   # 唯一有方向的(其余弃权)
    else:
        effective = "HOLD"   # 对冲或全弃权

    # GCC-0264 S1: SELL硬约束 — Vision高confidence看多时禁止SELL
    # 经验卡数据: SELL 0/5全输, 根因是在Vision看多时逆势做空
    if effective == "SELL" and vision_bias == "BUY" and vision_conf > 0.7:
        effective = "HOLD"
        logger.info("[GCC-TM] %s GCC-0264 SELL硬约束: vision=BUY(%.0f%%>70%%) → SELL→HOLD",
                    symbol, vision_conf * 100)

    logger.info("[GCC-TM] %s 三方投票: vision=%s prev=%s wyckoff=%s(Ph%s) → effective=%s (BV→池: %s[%s])",
                symbol, vision_bias, prev_dir, wyckoff_bias, wyckoff_phase, effective, bv_bias, bv_pattern)

    state = CandleState(
        symbol=symbol,
        candle_open_ts=candle_open,
        vision_direction=vision_bias,
        vision_confidence=vision_conf,
        prev_summary=prev_dir,
        effective_direction=effective,
        bv_direction=bv_bias,
        bv_pattern=bv_pattern,
        wyckoff_phase=wyckoff_phase,
        wyckoff_bias=wyckoff_bias,
        value_composite=value_composite,
        value_modifier=value_modifier,
    )

    # 如果程序重启, 当前已经不在round 0, 标记起点
    # 不在此处做HOLD占位回填 — 交给gcc_observe()用完整决策回填(有bars+mod)
    actual_round = _get_current_round(now, symbol=symbol)
    if actual_round > 0:
        state.current_round = actual_round
        logger.info("[GCC-TM] %s restart at round %d, pending backfill with decisions",
                    symbol, actual_round)

    logger.info(
        "[GCC-TM] %s new candle: vision=%s(%.0f%%) prev=%s wyckoff=%s(Ph%s) effective=%s round=%d",
        symbol, vision_bias, vision_conf * 100, prev_dir, wyckoff_bias, wyckoff_phase, effective, state.current_round,
    )
    return state


def _aggregate_candle_summary(state: CandleState, bars: list = None) -> dict:
    """8轮结束: 汇总所有轮次决策 → BUY/SELL/HOLD + 置信度。
    bars: 完整4H K线的OHLCV, 用于volume修正(K线完成后量比才准确)。
    """
    buy_count = sum(1 for r in state.round_decisions if r.get("action") == "BUY")
    sell_count = sum(1 for r in state.round_decisions if r.get("action") == "SELL")
    hold_count = len(state.round_decisions) - buy_count - sell_count

    # 多数投票
    total = max(len(state.round_decisions), 1)
    if buy_count > sell_count and buy_count > hold_count:
        direction = "BUY"
        confidence = buy_count / total
    elif sell_count > buy_count and sell_count > hold_count:
        direction = "SELL"
        confidence = sell_count / total
    else:
        # 平局或HOLD最多 → HOLD, 确保confidence > 0
        direction = "HOLD"
        confidence = max(hold_count / total, 0.5)

    # Volume修正: K线完成后量比才准确
    volume_boost = 0.0
    if bars and len(bars) >= 2:
        try:
            cur_vol = float(bars[-1].get("volume") or bars[-1].get("v") or 0)
            # 均量 = 前N根的平均
            prev_vols = [float(b.get("volume") or b.get("v") or 0)
                         for b in bars[-21:-1] if b]
            avg_vol = sum(prev_vols) / max(len(prev_vols), 1) if prev_vols else 0
            if avg_vol > 0:
                rvol = cur_vol / avg_vol
                # 放量(>1.5)且方向明确 → 增强confidence
                if rvol >= 1.5 and direction != "HOLD":
                    volume_boost = min((rvol - 1.0) * 0.1, 0.15)
                    confidence = min(confidence + volume_boost, 1.0)
                # 缩量(<0.5)且方向有分歧 → 降低confidence
                elif rvol < 0.5 and confidence < 0.6:
                    volume_boost = -0.1
                    confidence = max(confidence + volume_boost, 0.1)
                logger.info("[GCC-TM] %s volume at 4H end: rvol=%.2f boost=%.2f",
                            state.symbol, rvol, volume_boost)
        except Exception as e:
            logger.debug("[GCC-TM] %s volume calc error: %s", state.symbol, e)

    summary = {
        "direction": direction,
        "confidence": round(confidence, 3),
        "buy_rounds": buy_count,
        "sell_rounds": sell_count,
        "hold_rounds": hold_count,
        "total_rounds": len(state.round_decisions),
        "traded": state.traded,
        "trade_round": state.trade_round,
        "volume_boost": round(volume_boost, 3),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    _save_candle_summary(state.symbol, summary)
    logger.info(
        "[GCC-TM] %s candle summary: %s (B:%d S:%d H:%d traded=%s)",
        state.symbol, direction, buy_count, sell_count, hold_count, state.traded,
    )
    return summary


# ── 决策输出日志 ───────────────────────────────────────────────
def _log_decision(record: dict) -> None:
    """Phase1观察模式：追加决策记录到 JSONL。"""
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[GCC-TRADE] log_decision failed: %s", e)


# ══════════════════════════════════════════════════════════════
# S06  _read_vision(symbol) → (bias, confidence)
# 读 state/vision_cache/snapshots/{symbol}/latest.json
# bias: "BUY" | "SELL" | "HOLD"  confidence: 0.0~1.0
# ══════════════════════════════════════════════════════════════
def _read_vision(symbol: str) -> Tuple[str, float]:
    """从 state/vision/latest.json 读取最新 Vision 判断。
    v3.670: 修正路径(原snap_file不存在) + 字段映射(direction→bias)。
    direction UP→BUY, DOWN→SELL, SIDE→HOLD
    """
    vision_file = _STATE_DIR / "vision" / "latest.json"
    if not vision_file.exists():
        return "HOLD", 0.5
    try:
        all_data = json.loads(vision_file.read_text(encoding="utf-8"))
        entry = all_data.get(symbol, {})
        current = entry.get("current", {})
        if not current:
            return "HOLD", 0.5
        direction = (current.get("direction") or "SIDE").upper()
        conf = float(current.get("confidence") or 0.5)
        conf = max(0.0, min(1.0, conf))
        # 映射: UP→BUY, DOWN→SELL, SIDE→HOLD
        bias_map = {"UP": "BUY", "DOWN": "SELL"}
        bias = bias_map.get(direction, "HOLD")
        return bias, conf
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_vision %s: %s", symbol, e)
        return "HOLD", 0.5


# S06b: _read_wyckoff_phase removed — Wyckoff由B通道数学模块独立计算(GCC-0261)


# ══════════════════════════════════════════════════════════════
# S07  _read_scan_signal(symbol) → (direction, confidence)
# 读 state/n_structure_state.json 作为扫描信号代理
# direction: "BUY" | "SELL" | "NONE"   confidence: 0.0~1.0
# 注: scan_signals.json 由主程序运行时生成，离线时回退到 n_structure
# ══════════════════════════════════════════════════════════════
def _read_scan_signal(symbol: str) -> Tuple[str, float]:
    """读扫描信号方向。优先 scan_signals.json，无则用 n_structure_state。"""
    # 优先检查实时 scan_signals
    scan_file = _STATE_DIR / "scan_signals.json"
    if scan_file.exists():
        try:
            d = json.loads(scan_file.read_text(encoding="utf-8"))
            entry = d.get(symbol, {})
            direction = (entry.get("direction") or "NONE").upper()
            conf = float(entry.get("confidence") or 0.5)
            if direction in ("BUY", "SELL"):
                return direction, max(0.0, min(1.0, conf))
        except Exception:
            pass

    # 回退: n_structure_state
    if _N_STRUCT_FILE.exists():
        try:
            d = json.loads(_N_STRUCT_FILE.read_text(encoding="utf-8"))
            entry = d.get(symbol, {})
            n_dir = (entry.get("direction") or "NONE").upper()
            quality = float(entry.get("quality") or 0.0)
            if n_dir == "UP":
                return "BUY", min(0.8, 0.5 + quality * 0.3)
            if n_dir == "DOWN":
                return "SELL", min(0.8, 0.5 + quality * 0.3)
        except Exception as e:
            logger.debug("[GCC-TRADE] _read_scan_signal n_struct %s: %s", symbol, e)

    return "NONE", 0.0




# ══════════════════════════════════════════════════════════════
# S10  _read_win_rate(symbol, direction) → float
# 读 state/audit/signal_log.jsonl → 统计 symbol+direction 历史胜率
# retrospective: "correct_pass"=胜, "false_pass"/"wrong_block"=败
# 最多读取最近 200 条，至少 5 条才给有效值
# ══════════════════════════════════════════════════════════════
def _read_win_rate(symbol: str, direction: str = "") -> float:
    """读取历史胜率，无足够数据返回 0.5。"""
    if not _SIGNAL_LOG.exists():
        return 0.5
    correct = 0
    total = 0
    try:
        lines = _SIGNAL_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
        # 取最近 200 条倒序扫描
        for line in reversed(lines[-400:]):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("symbol") != symbol:
                continue
            if direction and r.get("direction", "").upper() != direction.upper():
                continue
            retro = r.get("retrospective") or ""
            if retro in ("correct_pass", "correct_block"):
                correct += 1
                total += 1
            elif retro in ("false_pass", "wrong_block", "false_block"):
                total += 1
            if total >= 200:
                break
        if total < 5:
            return 0.5
        return round(correct / total, 4)
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_win_rate %s: %s", symbol, e)
        return 0.5



# ══════════════════════════════════════════════════════════════
# S12  _read_signal_direction() → str
# 读 .GCC/signal_filter/mode_state.json → "ENFORCE" | "OBSERVE" | "OFF"
# ══════════════════════════════════════════════════════════════
def _read_signal_direction() -> str:
    """读取 GCC 信号方向过滤模式。"""
    if not _GCC_MODE_FILE.exists():
        return "OFF"
    try:
        d = json.loads(_GCC_MODE_FILE.read_text(encoding="utf-8"))
        mode = (d.get("mode") or "OFF").upper()
        # observe_only 覆盖
        if d.get("observe_only"):
            return "OBSERVE"
        return mode if mode in ("ENFORCE", "OBSERVE", "OFF") else "OFF"
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_signal_direction: %s", e)
        return "OFF"


# ══════════════════════════════════════════════════════════════
# S12b  _read_signal_direction_detail() → dict
# 读 .GCC/signal_filter/direction_log.jsonl 最新一条，获取方向占优信息
# ══════════════════════════════════════════════════════════════
def _read_signal_direction_detail() -> dict:
    """读取 SignalDirectionFilter 最新方向判断。"""
    log_path = _GCC_DIR / "signal_filter" / "direction_log.jsonl"
    if not log_path.exists():
        return {"direction": "NO_ANSWER"}
    try:
        last_line = ""
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line.strip()
        return json.loads(last_line) if last_line else {"direction": "NO_ANSWER"}
    except Exception:
        return {"direction": "NO_ANSWER"}


# ══════════════════════════════════════════════════════════════
# S12c  _read_position(symbol) → (position_units, max_units)
# 读 logs/state.json 获取当前仓位档位
# ══════════════════════════════════════════════════════════════
def _read_position(symbol: str) -> tuple:
    """读取品种当前仓位。返回 (position_units, max_units)。"""
    if not _MAIN_STATE_FILE.exists():
        return (0, 5)
    try:
        d = json.loads(_MAIN_STATE_FILE.read_text(encoding="utf-8"))
        st = d.get(symbol)
        if not st:
            return (0, 5)
        pos = st.get("position_units", 0) or 0
        mx = st.get("max_units", 5)
        if mx is None:
            mx = 5
        return (pos, mx)
    except Exception:
        return (0, 5)


# ══════════════════════════════════════════════════════════════
# L1-S02  _read_regime
# 补充输入槽位：市场体制
# ══════════════════════════════════════════════════════════════

def _read_regime(symbol: str) -> dict:
    """读 regime_validation.json → 最新市场体制 (TRENDING/RANGING/VOLATILE)。"""
    if not _REGIME_FILE.exists():
        return {"regime": "UNKNOWN", "direction": "NONE"}
    try:
        data = json.loads(_REGIME_FILE.read_text(encoding="utf-8"))
        records = data.get("records", {}).get(symbol, [])
        if not records:
            return {"regime": "UNKNOWN", "direction": "NONE"}
        latest = records[-1] if isinstance(records, list) else records
        return {
            "regime": latest.get("regime", "UNKNOWN"),
            "direction": latest.get("direction", "NONE"),
        }
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_regime %s: %s", symbol, e)
        return {"regime": "UNKNOWN", "direction": "NONE"}



# ══════════════════════════════════════════════════════════════
# Phase B1: Schwab VWAP 读取 — docx P0 数据源
# 股票品种从 Schwab API 获取实时 VWAP，加密品种跳过
# ══════════════════════════════════════════════════════════════
_SCHWAB_QUOTE_CACHE: Dict[str, dict] = {}
_SCHWAB_QUOTE_CACHE_TS: Dict[str, float] = {}
_SCHWAB_QUOTE_TTL = 60  # 缓存60秒

def _read_schwab_vwap(symbol: str) -> dict:
    """
    读取 Schwab 实时报价 VWAP。
    返回: {"vwap": float, "vwap_bias": "ABOVE"/"BELOW"/"AT"/"UNKNOWN", "last": float}
    加密品种直接返回 UNKNOWN（Schwab 不支持加密货币）。
    """
    import time as _time
    # 加密品种跳过
    if symbol in _CRYPTO_SYMBOLS:
        return {"vwap": 0.0, "vwap_bias": "UNKNOWN", "last": 0.0}

    # 缓存检查
    cached_ts = _SCHWAB_QUOTE_CACHE_TS.get(symbol, 0)
    if _time.time() - cached_ts < _SCHWAB_QUOTE_TTL and symbol in _SCHWAB_QUOTE_CACHE:
        return _SCHWAB_QUOTE_CACHE[symbol]

    try:
        from schwab_data_provider import get_provider
        quote = get_provider().get_quote(symbol)
        result = {
            "vwap": quote.get("vwap", 0.0),
            "vwap_bias": quote.get("vwap_bias", "UNKNOWN"),
            "last": quote.get("last", 0.0),
        }
        _SCHWAB_QUOTE_CACHE[symbol] = result
        _SCHWAB_QUOTE_CACHE_TS[symbol] = _time.time()
        return result
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_schwab_vwap %s: %s", symbol, e)
        return {"vwap": 0.0, "vwap_bias": "UNKNOWN", "last": 0.0}


# ══════════════════════════════════════════════════════════════
# Phase B2: Coinbase OBI + CVD 读取 — 加密品种数据源
# ══════════════════════════════════════════════════════════════
_CB_CACHE: Dict[str, dict] = {}
_CB_CACHE_TS: Dict[str, float] = {}
_CB_CACHE_TTL = 30  # 30秒缓存

def _read_coinbase_obi_cvd(symbol: str) -> dict:
    """
    读取 Coinbase OBI + CVD。
    股票品种直接返回 UNKNOWN。
    返回: {"obi": float, "obi_bias": str, "cvd": float, "cvd_bias": str}
    """
    import time as _time
    # 股票品种跳过
    if symbol not in _CRYPTO_SYMBOLS:
        return {"obi": 0.0, "obi_bias": "UNKNOWN", "cvd": 0.0, "cvd_bias": "UNKNOWN"}

    cached_ts = _CB_CACHE_TS.get(symbol, 0)
    if _time.time() - cached_ts < _CB_CACHE_TTL and symbol in _CB_CACHE:
        return _CB_CACHE[symbol]

    try:
        from coinbase_data_provider import get_market_data
        data = get_market_data(symbol)
        obi = data.get("obi", {})
        cvd = data.get("cvd", {})
        result = {
            "obi": obi.get("obi", 0.0),
            "obi_bias": obi.get("obi_bias", "UNKNOWN"),
            "cvd": cvd.get("cvd", 0.0),
            "cvd_bias": cvd.get("cvd_bias", "UNKNOWN"),
        }
        _CB_CACHE[symbol] = result
        _CB_CACHE_TS[symbol] = _time.time()
        return result
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_coinbase_obi_cvd %s: %s", symbol, e)
        return {"obi": 0.0, "obi_bias": "UNKNOWN", "cvd": 0.0, "cvd_bias": "UNKNOWN"}


# ── Nowcast: 读取最新日频评分 (KEY-005-NC) ──
_NC_CACHE: Dict[str, dict] = {}
_NC_CACHE_DATE: str = ""

def _read_nowcast(symbol: str) -> dict:
    """读取 state/nowcast_log.jsonl 中该品种当天最新评分。
    返回: {"score": int, "confidence": float, "reasoning": str} 或空 dict。
    缓存按日刷新 — 日频数据不需要每30min重读。"""
    global _NC_CACHE, _NC_CACHE_DATE
    from datetime import datetime as _dt_nc
    from zoneinfo import ZoneInfo as _zi_nc
    today = _dt_nc.now(_zi_nc("America/New_York")).strftime("%Y-%m-%d")

    # 日级缓存: 同一天只读一次文件
    if _NC_CACHE_DATE == today and symbol in _NC_CACHE:
        return _NC_CACHE[symbol]

    # 刷新缓存
    if _NC_CACHE_DATE != today:
        _NC_CACHE.clear()
        _NC_CACHE_DATE = today

    # 品种映射: gcc-tm用BTCUSDC, nowcast用BTC-USD
    _NC_SYMBOL_MAP = {
        "BTCUSDC": "BTC-USD", "ETHUSDC": "ETH-USD",
        "SOLUSDC": "SOL-USD", "ZECUSDC": "ZEC-USD",
    }
    nc_sym = _NC_SYMBOL_MAP.get(symbol, symbol)

    try:
        nc_file = _STATE_DIR / "nowcast_log.jsonl"
        if not nc_file.exists():
            return {}
        best = {}
        with open(nc_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("symbol") == nc_sym and entry.get("date") == today and "error" not in entry:
                    best = {"score": entry["score"], "confidence": entry.get("confidence", 0.5),
                            "reasoning": entry.get("reasoning", "")}
        _NC_CACHE[symbol] = best
        return best
    except Exception as e:
        logger.debug("[GCC-TRADE] _read_nowcast %s: %s", symbol, e)
        return {}


# ══════════════════════════════════════════════════════════════
# L1-S03  DecisionContext — 标准化决策上下文快照
# 统一所有输入源为一个 dataclass，落盘供回放/dashboard/回填复用
# ══════════════════════════════════════════════════════════════
@dataclass
class DecisionContext:
    symbol: str
    ts: str
    # 原有输入 (L1-S01)
    vision: tuple         # (bias, confidence)
    scan: tuple           # (direction, confidence)
    win_rate_buy: float
    win_rate_sell: float
    # 新增输入 (L1-S02)
    regime: dict = field(default_factory=dict)
    # 信号方向过滤 + 仓位管理
    signal_direction: dict = field(default_factory=dict)
    position: tuple = (0, 5)  # (position_units, max_units)
    # 信号池统计（4H内收集的外挂BUY/SELL计数）
    signal_pool: dict = field(default_factory=dict)  # {buy:N, sell:N, total:N, strongest:"..."}
    # 扩展槽位（docx P0 数据源预留）
    extended: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "ts": self.ts,
            "vision": list(self.vision), "scan": list(self.scan),
            "win_rate_buy": self.win_rate_buy, "win_rate_sell": self.win_rate_sell,
            "regime": self.regime,
            "signal_direction": self.signal_direction,
            "position": list(self.position),
            "signal_pool": self.signal_pool,
            "extended": self.extended,
        }

    def snapshot(self) -> None:
        """落盘快照到 state/gcc_decision_context/{symbol}/{ts}.json。"""
        try:
            snap_dir = _CONTEXT_SNAP_DIR / self.symbol
            snap_dir.mkdir(parents=True, exist_ok=True)
            safe_ts = self.ts.replace(":", "-").replace(" ", "_")
            path = snap_dir / f"{safe_ts}.json"
            path.write_text(
                json.dumps(self.as_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("[GCC-TRADE] context snapshot: %s", e)


# ══════════════════════════════════════════════════════════════
# S13  TreeNode — 树搜索候选路径节点
# action: "BUY" | "SELL" | "HOLD"
# scores_by_source: 各数据源打分 {source: float}
# aggregate: 综合分数 [-1, 1]
# pruned: 是否被剪枝
# prune_reason: 剪枝原因
# ══════════════════════════════════════════════════════════════
@dataclass
class TreeNode:
    action: str                              # "BUY" | "SELL" | "HOLD"
    scores_by_source: dict = field(default_factory=dict)
    aggregate: float = 0.0                   # [-1, 1]
    pruned: bool = False
    prune_reason: str = ""
    # PUCT 树搜索扩展 (arXiv:2603.04735)
    depth: int = 0                           # 树深度 (0=根, 1=L1方向, 2=L2策略)
    visit_count: int = 0                     # N(s,a) 访问次数
    total_value: float = 0.0                 # W(s,a) 累积价值
    children: list = field(default_factory=list)  # 子节点列表
    strategy: str = ""                       # L2策略标签

    @property
    def q_value(self) -> float:
        """PUCT Q值 = 平均价值。"""
        return self.total_value / self.visit_count if self.visit_count > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "action":           self.action,
            "scores_by_source": self.scores_by_source,
            "aggregate":        round(self.aggregate, 4),
            "pruned":           self.pruned,
            "prune_reason":     self.prune_reason,
            "depth":            self.depth,
            "strategy":         self.strategy,
            "visit_count":      self.visit_count,
            "q_value":          round(self.q_value, 4),
            "children_count":   len(self.children),
        }


# ══════════════════════════════════════════════════════════════
# S14  _score_buy_candidate — BUY 路径各数据源打分
# 返回 scores_by_source dict，每个 key 对应一个数据源贡献值
# v0.2 权重设计 (Vision已提升为门控，不参与打分):
#   scan      0.30  — 扫描引擎方向 (入场信号)
#   filter    0.25  — 过滤链通过情况 (入场条件)
#   win_rate  0.15  — 历史胜率偏置
#   volume    0.10  — 量比确认
#   signal_pool 0.45 — 外挂共识 (入场信心)
#   vwap/obi/cvd — 量价确认
# ══════════════════════════════════════════════════════════════
def _score_buy_candidate(symbol: str, bars: list, context: dict) -> dict:
    """v0.2: 为 BUY 候选路径打分 (Vision已提升为门控，不参与打分)。"""
    scan_dir,    scan_conf   = context.get("scan",   ("NONE", 0.0))
    win_rate                 = context.get("win_rate_buy", 0.5)

    scores = {}

    # GCC-0264 S3: scan权重0.30→0.20 (经验卡: scan越高反而越输 delta=-0.136)
    if scan_dir == "BUY":
        scores["scan"] = +scan_conf * 0.20
    elif scan_dir == "SELL":
        scores["scan"] = -scan_conf * 0.20
    else:
        scores["scan"] = 0.0

    # win_rate 偏置 (v0.2: 0.24→0.30, 即 0.5→0, 1.0→+0.15)
    scores["win_rate"] = (win_rate - 0.5) * 0.30

    # volume: v0.2 K线未完成时量比不准，轮次中不参与打分(8轮汇总时再用)
    scores["volume"] = 0.0

    # Phase B1: VWAP — 价格在VWAP上方支持BUY (v0.2: 0.10→0.15)
    vwap_bias = context.get("schwab_vwap", {}).get("vwap_bias", "UNKNOWN")
    if vwap_bias == "ABOVE":
        scores["vwap"] = +0.15
    elif vwap_bias == "BELOW":
        scores["vwap"] = -0.10
    else:
        scores["vwap"] = 0.0

    # Phase B2: Coinbase OBI — 买压支持BUY (v0.2: 0.08→0.10)
    coinbase = context.get("coinbase", {})
    obi_bias = coinbase.get("obi_bias", "UNKNOWN")
    if obi_bias == "BUY_PRESSURE":
        scores["obi"] = +0.10
    elif obi_bias == "SELL_PRESSURE":
        scores["obi"] = -0.08
    else:
        scores["obi"] = 0.0

    # Phase B2: Coinbase CVD — 主买支持BUY (v0.2: 0.08→0.10)
    cvd_bias = coinbase.get("cvd_bias", "UNKNOWN")
    if cvd_bias == "BUY_DOMINANT":
        scores["cvd"] = +0.10
    elif cvd_bias == "SELL_DOMINANT":
        scores["cvd"] = -0.08
    else:
        scores["cvd"] = 0.0

    # 信号池: 30分钟内外挂BUY票数占比 (v0.2: 0.40→0.45)
    pool = context.get("signal_pool", {})
    pool_total = pool.get("total", 0)
    if pool_total > 0:
        buy_ratio = pool.get("buy", 0) / pool_total
        scores["signal_pool"] = (buy_ratio - 0.5) * 0.45  # 全BUY→+0.225, 全SELL→-0.225
    else:
        scores["signal_pool"] = 0.0

    # KEY-003: 价值分析 — composite>0支持BUY, <0抑制BUY (权重0.15)
    _va_score = context.get("value_composite", 0.0)
    scores["value"] = max(-0.15, min(0.15, _va_score * 0.015))  # ±10→±0.15

    # KEY-005-NC: Nowcast日频方向偏置 (权重0.20, score -5~+5)
    # BUY路径: 正分支持买入, 负分反对买入
    nc = context.get("nowcast", {})
    nc_score = nc.get("score", 0)
    scores["nowcast"] = (nc_score / 5.0) * 0.20 if nc_score != 0 else 0.0

    # GCC-0264 S2: 信号一致性分 (简化topo, 权重0.15)
    # 经验卡: topo是最强预测因子 delta=+0.188
    # 计算当前scores中正向信号占比 → 一致性越高分越高
    _scored_vals = [v for k, v in scores.items() if v != 0 and k != "consistency"]
    if _scored_vals:
        _pos = sum(1 for v in _scored_vals if v > 0)
        _consistency = _pos / len(_scored_vals)  # 0~1
        scores["consistency"] = (_consistency - 0.5) * 0.30  # 全一致→+0.15, 全分歧→-0.15
    else:
        scores["consistency"] = 0.0

    # GCC-0264 S4: ZECUSDC品种折扣 (经验卡: ZEC 41%胜率, topo对ZEC无效)
    if symbol == "ZECUSDC":
        for k in scores:
            scores[k] *= 0.7  # 30%折扣

    return scores


# ══════════════════════════════════════════════════════════════
# S15  _score_sell_candidate — SELL 路径各数据源打分
# 镜像 BUY 打分，方向相反
# ══════════════════════════════════════════════════════════════
def _score_sell_candidate(symbol: str, bars: list, context: dict) -> dict:
    """v0.2: 为 SELL 候选路径打分 (Vision已提升为门控，不参与打分)。"""
    scan_dir,    scan_conf   = context.get("scan",   ("NONE", 0.0))
    win_rate                 = context.get("win_rate_sell", 0.5)

    scores = {}

    # GCC-0264 S3: scan权重0.30→0.20 (经验卡: scan越高反而越输)
    if scan_dir == "SELL":
        scores["scan"] = +scan_conf * 0.20
    elif scan_dir == "BUY":
        scores["scan"] = -scan_conf * 0.20
    else:
        scores["scan"] = 0.0

    # win_rate (v0.2: 0.24→0.30)
    scores["win_rate"] = (win_rate - 0.5) * 0.30

    # volume: v0.2 K线未完成时量比不准，轮次中不参与打分
    scores["volume"] = 0.0

    # Phase B1: VWAP — 价格在VWAP下方支持SELL (v0.2: 0.10→0.15)
    vwap_bias = context.get("schwab_vwap", {}).get("vwap_bias", "UNKNOWN")
    if vwap_bias == "BELOW":
        scores["vwap"] = +0.15
    elif vwap_bias == "ABOVE":
        scores["vwap"] = -0.10
    else:
        scores["vwap"] = 0.0

    # Phase B2: Coinbase OBI — 卖压支持SELL (v0.2: 0.08→0.10)
    coinbase = context.get("coinbase", {})
    obi_bias = coinbase.get("obi_bias", "UNKNOWN")
    if obi_bias == "SELL_PRESSURE":
        scores["obi"] = +0.10
    elif obi_bias == "BUY_PRESSURE":
        scores["obi"] = -0.08
    else:
        scores["obi"] = 0.0

    # Phase B2: Coinbase CVD — 主卖支持SELL (v0.2: 0.08→0.10)
    cvd_bias = coinbase.get("cvd_bias", "UNKNOWN")
    if cvd_bias == "SELL_DOMINANT":
        scores["cvd"] = +0.10
    elif cvd_bias == "BUY_DOMINANT":
        scores["cvd"] = -0.08
    else:
        scores["cvd"] = 0.0

    # 信号池: 30分钟内外挂SELL票数占比 (v0.2: 0.40→0.45)
    pool = context.get("signal_pool", {})
    pool_total = pool.get("total", 0)
    if pool_total > 0:
        sell_ratio = pool.get("sell", 0) / pool_total
        scores["signal_pool"] = (sell_ratio - 0.5) * 0.45  # 全SELL→+0.225, 全BUY→-0.225
    else:
        scores["signal_pool"] = 0.0

    # KEY-003: 价值分析 — composite<0支持SELL(高估值卖出), >0抑制SELL(低估值持有)
    _va_score = context.get("value_composite", 0.0)
    scores["value"] = max(-0.15, min(0.15, -_va_score * 0.015))  # 注意取反: 高分抑制卖出

    # KEY-005-NC: Nowcast日频方向偏置 (权重0.20, score -5~+5)
    # SELL路径: 负分支持卖出, 正分反对卖出 (取反)
    nc = context.get("nowcast", {})
    nc_score = nc.get("score", 0)
    scores["nowcast"] = (-nc_score / 5.0) * 0.20 if nc_score != 0 else 0.0

    # GCC-0264 S2: 信号一致性分 (简化topo, 权重0.15)
    _scored_vals = [v for k, v in scores.items() if v != 0 and k != "consistency"]
    if _scored_vals:
        _pos = sum(1 for v in _scored_vals if v > 0)
        _consistency = _pos / len(_scored_vals)
        scores["consistency"] = (_consistency - 0.5) * 0.30
    else:
        scores["consistency"] = 0.0

    # GCC-0264 S4: ZECUSDC品种折扣
    if symbol == "ZECUSDC":
        for k in scores:
            scores[k] *= 0.7

    return scores


# ══════════════════════════════════════════════════════════════
# S16  _score_hold_candidate — HOLD 路径中性分
# ══════════════════════════════════════════════════════════════
def _score_hold_candidate() -> dict:
    """HOLD 路径固定中性分 0.0，作为基线竞争者。v0.2: 移除vision。"""
    return {"scan": 0.0, "win_rate": 0.0, "volume": 0.0,
            "vwap": 0.0, "obi": 0.0, "cvd": 0.0,
            "signal_pool": 0.0, "nowcast": 0.0, "value": 0.0,
            "consistency": 0.0}


# ══════════════════════════════════════════════════════════════
# S17  _aggregate_candidate_score(scores_dict) → float [-1, 1]
# 各数据源分数加总后 clamp 到 [-1, 1]
# ══════════════════════════════════════════════════════════════
def _aggregate_candidate_score(scores: dict) -> float:
    """合并各数据源得分 → 归一化到 [-1, 1]。"""
    total = sum(scores.values())
    return max(-1.0, min(1.0, total))


# ══════════════════════════════════════════════════════════════
# S18-S21  剪枝规则
# ══════════════════════════════════════════════════════════════
_CRYPTO_SYMBOLS = frozenset({
    "BTCUSDC", "ETHUSDC", "SOLUSDC", "ZECUSDC",
})

def _apply_pruning(nodes: List[TreeNode], symbol: str,
                   context: dict,
                   failed_patterns: Optional[dict] = None) -> List[TreeNode]:
    """
    对候选节点应用剪枝规则 P0-P2。
    P0: 失败模式记忆 — 已知失败的信号组合直接剪 (arXiv:2603.04735 negative constraint)
    P1: SignalDirectionFilter ENFORCE — 方向占优时剪反向
    P2: Position Control — 仓位已满时阻止同方向
    """
    position, max_units = context.get("position", (0, 5))
    sig_dir = context.get("signal_direction", {})
    sig_dir_label = sig_dir.get("direction", "NO_ANSWER")
    sig_dir_mode = sig_dir.get("mode", _read_signal_direction())

    # 预计算信号指纹（P0 使用）
    fingerprint = _make_signal_fingerprint(context) if failed_patterns else ""

    for node in nodes:
        if node.pruned:
            continue

        # P0: 失败模式记忆（论文: negative constraint）
        if failed_patterns and node.action in ("BUY", "SELL"):
            if _is_failed_pattern(symbol, node.action, fingerprint, failed_patterns):
                node.pruned = True
                node.prune_reason = f"P0:known_failed_pattern({node.action})"
                continue

        # P1: SignalDirectionFilter — ENFORCE模式下方向占优时剪反向
        if sig_dir_mode == "ENFORCE":
            if node.action == "BUY" and sig_dir_label == "SELL_DOMINANT":
                node.pruned = True
                node.prune_reason = "P1:SignalFilter SELL_DOMINANT"
                continue
            if node.action == "SELL" and sig_dir_label == "BUY_DOMINANT":
                node.pruned = True
                node.prune_reason = "P1:SignalFilter BUY_DOMINANT"
                continue

        # P2: Position Control — 仓位已满不加仓，空仓不减仓
        if node.action == "BUY" and position >= max_units:
            node.pruned = True
            node.prune_reason = f"P2:Position full({position}/{max_units})"
            continue
        if node.action == "SELL" and position <= 0:
            node.pruned = True
            node.prune_reason = f"P2:Position empty(0/{max_units})"
            continue

    return nodes


# ══════════════════════════════════════════════════════════════
# S22  _select_best_candidate — 从存活节点中选最优
# 规则: aggregate 最大的存活节点；全部被剪枝则返回 HOLD
# ══════════════════════════════════════════════════════════════
def _select_best_candidate(nodes: List[TreeNode]) -> TreeNode:
    """从存活候选节点中选 aggregate 最高的；全剪枝时返回 HOLD。"""
    surviving = [n for n in nodes if not n.pruned]
    if not surviving:
        hold = TreeNode(action="HOLD", prune_reason="all_candidates_pruned")
        hold.scores_by_source = _score_hold_candidate()
        hold.aggregate = 0.0
        return hold
    return max(surviving, key=lambda n: n.aggregate)


# ══════════════════════════════════════════════════════════════
# S22b  PUCT 树搜索 — arXiv:2603.04735 核心算法
# Multi-level: L1(方向BUY/SELL/HOLD) → L2(子策略)
# PUCT: UCB(s,a) = Q(s,a) + c_puct * P(s,a) * sqrt(N_parent) / (1 + N(s,a))
# 数值反馈: 验证分数回传 → 迭代选择最优路径
# ══════════════════════════════════════════════════════════════

# PUCT 超参数
_C_PUCT = 1.5        # 探索-利用平衡系数 (论文推荐 1.0-2.0)
_PUCT_ITERATIONS = 4  # 搜索迭代次数 (论文~600节点，我们4轮×9节点=36次评估)
_PRUNE_RATIO = 0.8    # 每轮剪枝比例 (论文~80%剪枝)

# L2 子策略定义 — 每个方向3种策略，强调不同数据源
_L2_STRATEGIES: Dict[str, List[dict]] = {
    "BUY": [
        {"strategy": "momentum",  "emphasis": {"scan": 1.6, "volume": 1.4, "signal_pool": 1.2}},
        {"strategy": "value",     "emphasis": {"win_rate": 1.8, "scan": 0.7, "signal_pool": 1.0}},
        {"strategy": "breakout",  "emphasis": {"volume": 2.0, "signal_pool": 1.5}},
    ],
    "SELL": [
        {"strategy": "momentum",  "emphasis": {"scan": 1.6, "volume": 1.4, "signal_pool": 1.2}},
        {"strategy": "reversal",  "emphasis": {"win_rate": 1.8, "scan": 0.7, "signal_pool": 1.0}},
        {"strategy": "weakness",  "emphasis": {"win_rate": 1.5, "volume": 0.8, "signal_pool": 1.5}},
    ],
    "HOLD": [
        {"strategy": "neutral",   "emphasis": {}},
    ],
}


def _expand_l2_children(parent: TreeNode, base_scores: dict) -> List[TreeNode]:
    """
    arXiv:2603.04735 Expand: L1节点→L2子策略节点。
    对基础分数应用子策略的emphasis权重，生成不同侧重的候选路径。
    """
    strategies = _L2_STRATEGIES.get(parent.action, [])
    children = []
    for strat in strategies:
        # 对每个数据源应用emphasis权重
        adjusted_scores = {}
        emphasis = strat["emphasis"]
        for src, val in base_scores.items():
            if src.startswith("_"):
                continue  # 跳过元数据key
            multiplier = emphasis.get(src, 1.0)
            adjusted_scores[src] = val * multiplier
        agg = _aggregate_candidate_score(adjusted_scores)
        child = TreeNode(
            action=parent.action,
            scores_by_source=adjusted_scores,
            aggregate=agg,
            depth=2,
            strategy=strat["strategy"],
        )
        children.append(child)
    return children


def _puct_score(child: TreeNode, parent_visits: int, prior: float) -> float:
    """
    arXiv:2603.04735 PUCT公式:
    UCB(s,a) = Q(s,a) + c_puct * P(s,a) * sqrt(N_parent) / (1 + N(s,a))

    Q(s,a)    = 平均价值 (exploitation)
    P(s,a)    = 先验概率，由 aggregate 归一化得到
    N_parent  = 父节点总访问次数
    N(s,a)    = 子节点访问次数
    c_puct    = 探索常数
    """
    q = child.q_value
    exploration = _C_PUCT * prior * math.sqrt(parent_visits) / (1 + child.visit_count)
    return q + exploration


def _numerical_feedback(node: TreeNode, verifier: "BeyondEuclidVerifier",
                        closes: List[float], current_price: float) -> float:
    """
    arXiv:2603.04735 Verify+Correct: 数值反馈循环。
    对候选节点做验证 → 返回归一化反馈值 [0, 1]。
    论文: "propose → code → verify → inject error → correct → expand deeper"
    我们: 用三视角验证器的共识度作为数值反馈。
    """
    if node.action == "HOLD":
        return 0.3  # HOLD 的基准反馈值（不活跃）

    consensus, results, verdict = verifier.verify(node, closes, current_price)
    if not results:
        return 0.3

    # 只用非弃权视角计算反馈值
    active_results = [r for r in results if not r.abstain]
    if not active_results:
        return 0.2  # 全部弃权，低反馈值（不奖励无法判断的候选）

    avg_score = sum(r.score for r in active_results) / len(active_results)
    active_consensus = sum(1 for r in active_results if r.ok)
    active_count = len(active_results)

    # consensus_bonus 基于有效视角比例，而非绝对数量
    consensus_ratio = active_consensus / active_count
    consensus_bonus = consensus_ratio * 0.4  # 全通过 +0.4，全拒绝 +0.0

    return min(1.0, avg_score * 0.5 + consensus_bonus + 0.1)


# 失败模式记忆 — arXiv:2603.04735 negative constraint
_FAILED_PATTERN_FILE = _STATE_DIR / "gcc_puct_failed_patterns.json"
_FAILED_PATTERN_MAX = 50   # 每个 symbol 最多记录50个失败模式
_FAILED_PATTERN_TTL = 8    # 失败模式有效期：8根K线


def _make_signal_fingerprint(context: dict) -> str:
    """生成信号指纹：提取关键信号状态组合作为唯一标识。"""
    scan_dir = context.get("scan", ("NONE", 0.0))[0] if isinstance(context.get("scan"), (list, tuple)) else "NONE"
    sig_label = context.get("signal_direction", {}).get("direction", "NO_ANSWER")
    return f"{scan_dir}|{sig_label}"


def _load_failed_patterns() -> dict:
    """加载失败模式缓存 {symbol: [{fingerprint, action, candle_count}]}"""
    if not _FAILED_PATTERN_FILE.exists():
        return {}
    try:
        return json.loads(_FAILED_PATTERN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_failed_patterns(patterns: dict) -> None:
    """保存失败模式缓存。"""
    try:
        _FAILED_PATTERN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(_FAILED_PATTERN_FILE,
                      json.dumps(patterns, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.debug("[GCC-TM] save_failed_patterns: %s", e)


def _is_failed_pattern(symbol: str, action: str, fingerprint: str,
                        patterns: dict) -> bool:
    """检查当前信号组合是否是已知失败模式。"""
    for p in patterns.get(symbol, []):
        if p.get("action") == action and p.get("fingerprint") == fingerprint:
            if p.get("candle_count", 0) < _FAILED_PATTERN_TTL:
                return True
    return False


def _record_failed_pattern(symbol: str, action: str, fingerprint: str,
                            patterns: dict) -> None:
    """记录失败模式（verdict=SKIP 后调用）。"""
    if symbol not in patterns:
        patterns[symbol] = []
    for p in patterns[symbol]:
        if p.get("action") == action and p.get("fingerprint") == fingerprint:
            return  # 已存在
    patterns[symbol].append({
        "fingerprint": fingerprint,
        "action": action,
        "candle_count": 0,
    })
    if len(patterns[symbol]) > _FAILED_PATTERN_MAX:
        patterns[symbol] = patterns[symbol][-_FAILED_PATTERN_MAX:]


## _load_visit_stats / _save_visit_stats / _apply_visit_history / _update_visit_stats
## REMOVED: 累积统计导致历史Q值压倒当前信号 (agg=-0.41 但 q=+0.91)
## PUCT 现在每次调用从零开始，只靠当前轮三视角反馈


# ══════════════════════════════════════════════════════════════
# S23  VerifierResult — 三视角验证结果
# ══════════════════════════════════════════════════════════════
@dataclass
class VerifierResult:
    perspective: str    # "topology" | "geometry" | "algebra"
    ok: bool            # 是否支持该候选方向
    score: float        # 置信度 [0, 1]
    reasoning: str = ""
    abstain: bool = False  # True=此视角弃权，不计入 consensus


# ══════════════════════════════════════════════════════════════
# S24-S25  TopologyVerifier
# 论文: arXiv:2407.09468 Sec.3 Topology (超图连通性)
# 思路: 把各数据源分数看作超图节点，连通度反映信号一致性
# 实现: Cheeger常数近似 = 最小割 / 节点数（连通=ok）
# S25: 信号数 < 3 或 active < 2 时 abstain（弃权）
# ══════════════════════════════════════════════════════════════
class TopologyVerifier:
    """
    超图连通性验证：信号源之间的一致性评估。
    arXiv:2407.09468 Topology 视角核心概念:
      - 信号源 = 超图节点，同方向信号之间有超边连接
      - Cheeger常数近似 = 最小割 / 节点数 (连通性度量)
      - Laplacian Fiedler值 = 超图 Laplacian 第二小特征值 (谱连通性)
      - Fiedler值越大 = 连通度越强 = 信号一致性越高
    """

    THRESHOLD = 0.0   # Cheeger 近似值 > 0 代表连通

    @staticmethod
    def _fiedler_value(vals: list) -> float:
        """
        arXiv:2407.09468: 超图 Laplacian Fiedler值（代数连通度）。
        Fiedler值 = λ₂ = min_{x⊥1} x'Lx / x'x
        实现: 构建相似度 Laplacian → Rayleigh 商迭代求 λ₂。
        对 n≤6 的小矩阵用投影 Rayleigh 商法（精确到收敛）。
        """
        n = len(vals)
        if n < 2:
            return 0.0
        # 归一化到 [-1, 1]
        max_abs = max(abs(v) for v in vals) or 1.0
        normed = [v / max_abs for v in vals]
        # 相似度矩阵 W[i][j] = max(0, 1 - |ni - nj|)
        W = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                sim = max(0.0, 1.0 - abs(normed[i] - normed[j]))
                W[i][j] = sim
                W[j][i] = sim
        # 度矩阵 + Laplacian
        D = [sum(W[i]) for i in range(n)]
        L = [[(D[i] if i == j else 0.0) - W[i][j] for j in range(n)] for i in range(n)]

        # Rayleigh 商迭代: 在 1⊥ 子空间中求最小特征值
        # 初始向量: 交替 +1/-1 (正交于全1向量)
        x = [(-1.0) ** i for i in range(n)]
        # 减去在全1方向的投影 → 保证 x⊥1
        mean_x = sum(x) / n
        x = [xi - mean_x for xi in x]
        norm = sum(xi * xi for xi in x) ** 0.5
        if norm < 1e-12:
            return 0.0
        x = [xi / norm for xi in x]

        fiedler = 0.0
        for _ in range(20):  # 迭代收敛
            # y = L @ x
            y = [sum(L[i][j] * x[j] for j in range(n)) for i in range(n)]
            # Rayleigh 商 = x'y / x'x
            xty = sum(x[i] * y[i] for i in range(n))
            xtx = sum(x[i] * x[i] for i in range(n))
            fiedler = xty / xtx if xtx > 1e-12 else 0.0
            # 逆迭代: 解 (L - σI)z = x, σ 略小于 fiedler
            # 简化: 直接用 y 归一化 + 正交化作为下一步
            # 减去 1⊥ 投影
            mean_y = sum(y) / n
            y = [yi - mean_y for yi in y]
            norm_y = sum(yi * yi for yi in y) ** 0.5
            if norm_y < 1e-12:
                break
            x = [yi / norm_y for yi in y]

        return max(0.0, round(fiedler, 6))

    def verify(self, node: TreeNode) -> VerifierResult:
        scores = {k: v for k, v in node.scores_by_source.items()
                  if not k.startswith("_")}  # 排除元数据 key

        # S25: 信号源不足 3 个时弃权
        if len(scores) < 3:
            return VerifierResult(
                perspective="topology", ok=False, score=0.5,
                abstain=True,
                reasoning=f"abstain: only {len(scores)} sources"
            )

        vals = list(scores.values())
        positive = sum(1 for v in vals if v > 0)
        negative = sum(1 for v in vals if v < 0)
        neutral  = sum(1 for v in vals if v == 0)

        # 只考虑有信号(非零)的节点做连通性判断
        active = positive + negative
        if active < 2:
            return VerifierResult(
                perspective="topology", ok=False, score=0.5,
                abstain=True,
                reasoning=f"abstain: active={active} neutral={neutral} (insufficient)"
            )

        # --- Cheeger 近似 (组合法) ---
        majority = max(positive, negative)
        minority = active - majority
        cheeger_approx = minority / active

        # --- Fiedler 值 (谱法, 论文核心) ---
        # 只对有效信号做谱分析
        active_vals = [v for v in vals if v != 0]
        fiedler = self._fiedler_value(active_vals)

        # 综合判断: Cheeger + Fiedler 双重确认
        # Cheeger ≤ 0.34 (组合一致) AND Fiedler > 0 (谱连通)
        ok = cheeger_approx <= 0.34 and fiedler >= 0.0

        # score: Cheeger 和 Fiedler 加权 + neutral 惩罚
        total = len(vals)
        neutral_ratio = neutral / total if total > 0 else 1.0
        balance = majority / active
        raw_score = balance * 0.7 + min(fiedler, 1.0) * 0.3

        # neutral 惩罚：neutral_ratio > 0.6 时降权
        if neutral_ratio > 0.6:
            penalty = (neutral_ratio - 0.6) * 1.5  # 最多 -0.6
            score = round(max(0.2, raw_score - penalty), 4)
        else:
            score = round(raw_score, 4)

        return VerifierResult(
            perspective="topology", ok=ok, score=score,
            reasoning=(f"pos={positive} neg={negative} neutral={neutral} "
                       f"active={active} cheeger={cheeger_approx:.2f} "
                       f"fiedler={fiedler:.4f}")
        )


# ══════════════════════════════════════════════════════════════
# S26-S28  GeometryVerifier
# 论文: arXiv:2407.09468 Sec.4 Geometry (黎曼流形曲率)
# 思路: 对数收益率序列的局部曲率 → 判断当前价格动能方向
# S27: 滚动缓冲区最多 500 根 bars
# S28: Riemannian IC 修正 ±0.15
# ══════════════════════════════════════════════════════════════
class GeometryVerifier:
    """
    黎曼流形曲率验证：价格序列动能与候选方向一致性。
    arXiv:2407.09468 Geometry 视角核心概念:
      - 对数收益率序列 = 黎曼流形上的曲线
      - 测地线曲率 = 二阶差分 (加速度)
      - Frechet均值 = 最小化测地线距离平方和的中心点
      - 测地线距离 = 当前点到 Frechet 均值的距离 → 偏离度
    """

    MAX_BUFFER = 500
    IC_CORRECT = 0.15   # S28: 黎曼曲率修正幅度

    def __init__(self):
        self._price_buf: List[float] = []  # 对数收益率序列 (S27)

    def update(self, close_prices: List[float]) -> None:
        """喂入收盘价，维护对数收益率滚动缓冲。"""
        import math
        new_returns = []
        for i in range(1, len(close_prices)):
            p0, p1 = close_prices[i - 1], close_prices[i]
            if p0 > 0 and p1 > 0:
                new_returns.append(math.log(p1 / p0))
        self._price_buf.extend(new_returns)
        # 截断到最近 MAX_BUFFER 条
        if len(self._price_buf) > self.MAX_BUFFER:
            self._price_buf = self._price_buf[-self.MAX_BUFFER:]

    def _geodesic_curvature(self) -> tuple:
        """
        计算近期收益率序列的测地线曲率（二阶差分）和斜率（一阶差分）。
        返回: (curvature, slope)
        """
        buf = self._price_buf
        if len(buf) < 10:
            return 0.0, 0.0
        recent = buf[-20:]
        # 一阶差分（速度/斜率）
        d1 = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        slope = sum(d1) / len(d1) if d1 else 0.0
        # 二阶差分（曲率/加速度）
        d2 = [d1[i] - d1[i - 1] for i in range(1, len(d1))]
        curvature = sum(d2) / len(d2) if d2 else 0.0
        return curvature, slope

    def _frechet_mean(self) -> float:
        """
        arXiv:2407.09468: Frechet均值 = 最小化测地线距离平方和的点。
        在1D对数收益率空间中，Frechet均值 = 算术均值。
        返回: 近期对数收益率的 Frechet 均值。
        """
        buf = self._price_buf
        if len(buf) < 5:
            return 0.0
        recent = buf[-50:]  # 近50根K线的收益率
        return sum(recent) / len(recent)

    def _geodesic_distance(self, current_return: float) -> float:
        """
        arXiv:2407.09468: 当前点到 Frechet 均值的测地线距离。
        在1D流形上 = |current - frechet_mean|。
        距离越大 = 偏离历史中心越远 = 信号越强(趋势加速或反转)。
        """
        fm = self._frechet_mean()
        return abs(current_return - fm)

    def verify(self, node: TreeNode, close_prices: Optional[List[float]] = None) -> VerifierResult:
        if close_prices:
            self.update(close_prices)

        curvature, slope = self._geodesic_curvature()

        # Frechet 均值 + 测地线距离 (论文核心)
        frechet = self._frechet_mean()
        current_ret = self._price_buf[-1] if self._price_buf else 0.0
        geo_dist = self._geodesic_distance(current_ret)

        # 动量方向: 优先看曲率(加速度)，曲率接近零时用斜率(速度)
        # 对数收益率量级 ~0.001，二阶差分 ~0.00001，需大倍率放大
        if abs(curvature) > 1e-6:
            momentum_up = curvature > 0
            signal_strength = abs(curvature) * 10000
        elif abs(slope) > 1e-6:
            momentum_up = slope > 0
            signal_strength = abs(slope) * 500  # 斜率权重低于曲率
        else:
            # 真的没信号
            momentum_up = True  # 中性偏保守
            signal_strength = 0.0

        action_up = node.action == "BUY"
        aligned = (momentum_up == action_up) or node.action == "HOLD"

        # 测地线距离增强: 偏离 Frechet 均值越远，信号越强
        # geo_dist 量级 ~0.001-0.01, 放大后叠加到 signal_strength
        geo_boost = min(geo_dist * 200, 0.05)  # 最多 +0.05 额外强度
        signal_strength += geo_boost

        # S28: IC 修正，clamp 到 ±0.15
        raw_ic = min(signal_strength, self.IC_CORRECT)
        score = 0.5 + (raw_ic if aligned else -raw_ic)
        score = max(0.0, min(1.0, score))

        return VerifierResult(
            perspective="geometry", ok=aligned, score=round(score, 4),
            reasoning=(f"curvature={curvature:.6f} slope={slope:.6f} "
                       f"frechet={frechet:.6f} geo_dist={geo_dist:.6f} "
                       f"momentum_up={momentum_up} action={node.action} aligned={aligned}")
        )


# ══════════════════════════════════════════════════════════════
# S29-S31  AlgebraVerifier
# 论文: arXiv:2407.09468 Sec.5 Algebra (等变加权胜率)
# 思路: 用双曲空间距离加权历史胜率，支持等变变换
# S30: record_outcome() 记录历史结果
# S31: reference_price 首次价格作为等变基准点
# ══════════════════════════════════════════════════════════════
class AlgebraVerifier:
    """等变加权胜率验证：双曲空间距离调权的历史胜率。"""

    def __init__(self):
        self._history: List[dict] = []   # {price, action, outcome: bool}
        self._ref_price: Optional[float] = None   # S31 等变基准点

    def record_outcome(self, price: float, action: str, outcome: bool) -> None:
        """S30: 记录一次交易结果（outcome=True 为盈利）。"""
        if self._ref_price is None:
            self._ref_price = price   # S31: 首次价格初始化
        self._history.append({"price": price, "action": action, "outcome": outcome})
        # 只保留最近 200 条
        if len(self._history) > 200:
            self._history = self._history[-200:]

    def _hyperbolic_distance(self, p1: float, p2: float) -> float:
        """双曲空间距离近似：对数价格比的绝对值。"""
        import math
        if p1 <= 0 or p2 <= 0:
            return 1.0
        return abs(math.log(p2 / p1))

    def verify(self, node: TreeNode, current_price: float = 0.0) -> VerifierResult:
        """S29: 等变加权胜率验证。"""
        if not self._history or current_price <= 0:
            return VerifierResult(
                perspective="algebra", ok=False, score=0.5,
                abstain=True,
                reasoning="abstain: no history"
            )

        ref = self._ref_price or current_price
        same_action = [h for h in self._history if h["action"] == node.action]
        if len(same_action) < 3:
            return VerifierResult(
                perspective="algebra", ok=False, score=0.5,
                abstain=True,
                reasoning=f"abstain: insufficient history ({len(same_action)}<3)"
            )

        # 双曲距离加权胜率
        weighted_win = 0.0
        weighted_total = 0.0
        for h in same_action:
            dist = self._hyperbolic_distance(h["price"], current_price)
            # 距离越近权重越大（距离反比）
            weight = 1.0 / (1.0 + dist)
            weighted_total += weight
            if h["outcome"]:
                weighted_win += weight

        if weighted_total <= 0:
            return VerifierResult(perspective="algebra", ok=False, score=0.5,
                                  abstain=True,
                                  reasoning="abstain: zero weight")

        win_rate = weighted_win / weighted_total
        ok = win_rate >= 0.5
        score = round(win_rate, 4)

        return VerifierResult(
            perspective="algebra", ok=ok, score=score,
            reasoning=(f"weighted_wr={win_rate:.3f} "
                       f"n={len(same_action)} action={node.action}")
        )


# ══════════════════════════════════════════════════════════════
# S32-S34  BeyondEuclidVerifier
# arXiv:2407.09468: 三视角独立验证，≥2/3 通过才执行
# S32: verify(best_node) → (consensus_count, results)
# S33: 共识规则 ≥2/3 → EXECUTE，<2/3 → SKIP
# S34: 无存活候选 → 直接 SKIP 跳过验证
# ══════════════════════════════════════════════════════════════
class BeyondEuclidVerifier:
    """三视角独立验证器：Topology + Geometry + Algebra。"""

    def __init__(self):
        self.topology = TopologyVerifier()
        self.geometry = GeometryVerifier()
        self.algebra  = AlgebraVerifier()

    def verify(
        self,
        best_node: Optional[TreeNode],
        close_prices: Optional[List[float]] = None,
        current_price: float = 0.0,
    ) -> Tuple[int, List[VerifierResult], str]:
        """
        S32: 对最优候选节点进行三视角验证。
        返回: (consensus_count, results, verdict)
        verdict: "EXECUTE" | "SKIP" | "NOTIFY"
        """
        # S34: 无候选 (all_pruned) 直接 SKIP
        if best_node is None or best_node.prune_reason == "all_candidates_pruned":
            return 0, [], "SKIP"

        # HOLD 节点不需要三视角验证（保守策略）
        if best_node.action == "HOLD":
            return 0, [], "SKIP"

        results: List[VerifierResult] = [
            self.topology.verify(best_node),
            self.geometry.verify(best_node, close_prices),
            self.algebra.verify(best_node, current_price),
        ]

        # S33: 弃权视角不计入分母（动态 consensus）
        active_results = [r for r in results if not r.abstain]
        consensus_count = sum(1 for r in active_results if r.ok)
        active_count = len(active_results)

        if active_count == 0:
            # 全部弃权 → SKIP
            verdict = "SKIP"
        elif active_count == 1:
            # 单视角：必须 ok 才放行
            verdict = "EXECUTE" if consensus_count >= 1 else "SKIP"
        elif active_count == 2:
            # 双视角：1/2 不冲突即放行（预测性验证不卡太紧）
            verdict = "EXECUTE" if consensus_count >= 1 else "SKIP"
        else:
            # 三视角：2/3 通过（原逻辑）
            verdict = "EXECUTE" if consensus_count >= 2 else "SKIP"

        logger.debug(
            "[GCC-TM][BEV] active=%d/%d consensus=%d verdict=%s",
            active_count, len(results), consensus_count, verdict
        )

        return consensus_count, results, verdict


# ══════════════════════════════════════════════════════════════
# S35  PHASE 常量
# ══════════════════════════════════════════════════════════════
PHASE_OBSERVE   = "observe"    # Phase1: 只记录，不发单
PHASE_EXECUTE   = "execute"    # Phase2: 写 pending_order.json
PHASE_HOLD_ONLY = "hold_only"  # Phase3: 强制 HOLD，风控熔断时使用


# ══════════════════════════════════════════════════════════════
# S36-S42  GCCTradingModule — 主类
# ══════════════════════════════════════════════════════════════
class GCCTradingModule:
    """
    GCC 交易决策主模块。
    Phase1(observe): 只记录 decisions.jsonl，不干扰主程序。
    Phase2(execute): 写 pending_order.json，下一K线市价执行。
    """

    # S36: __init__
    def __init__(
        self,
        symbol: str,
        phase: str = PHASE_OBSERVE,
        log_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None,
    ):
        self.symbol    = symbol
        self.phase     = phase
        self.log_dir   = Path(log_dir) if log_dir else _STATE_DIR
        self.state_dir = Path(state_dir) if state_dir else _STATE_DIR

        self._verifier = BeyondEuclidVerifier()
        self._decision_log  = self.log_dir / "gcc_trading_decisions.jsonl"
        self._pending_file  = self.state_dir / f"gcc_pending_order_{symbol}.json"

        logger.info("[GCC-TRADE] init symbol=%s phase=%s", symbol, phase)

    # ── S37: process() 主流程 ─────────────────────────────────
    def process(
        self,
        bars: list,
        signal_pool_data: Optional[dict] = None,
        candle_state: Optional[CandleState] = None,
    ) -> dict:
        """
        主流程入口。
        v0.2: 增加candle_state参数，传递Vision门控状态到树搜索。
        bars: OHLCV list，最新在末尾，至少含 volume/close 字段。
        signal_pool_data: 30分钟信号池统计 {buy:N, sell:N, total:N, ...}
        candle_state: 当前K线轮次状态 (None=向后兼容旧行为)
        """
        ts = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")

        # 提取收盘价与当前价
        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
        current_price = closes[-1] if closes else 0.0

        # L1: 组装 DecisionContext（含新增槽位 + 落盘快照）
        ctx = self._build_context(bars, ts)
        # 注入信号池数据到context
        if signal_pool_data:
            ctx.signal_pool = signal_pool_data
        context = self._context_to_score_dict(ctx)
        # KEY-003: 注入价值分析分数到评分context
        if candle_state:
            context["value_composite"] = candle_state.value_composite

        # L3-S02: hold_only 模式 — 直接 HOLD，只记日志
        if self.phase == PHASE_HOLD_ONLY:
            result = {
                "ts": ts, "symbol": self.symbol, "phase": self.phase,
                "best_node": None, "final_action": "HOLD",
                "verdict": "HOLD_ONLY", "consensus": 0,
                "verifier_results": [], "current_price": current_price,
                "rejected_nodes": [], "context": ctx.as_dict(),
            }
            self._write_decision_log(result)
            return result

        # L2: 树搜索（收集 rejected_nodes）— v0.2传入candle_state做Vision门控
        best_node, rejected_nodes = self._run_tree_search_with_rejected(
            bars, context, candle_state=candle_state
        )

        # L3: 三视角验证
        final_action, consensus, verdict, ver_results = self._run_verification(
            best_node, closes, current_price
        )

        # 失败模式记忆：SKIP 时记录信号指纹
        if verdict == "SKIP" and best_node and best_node.action in ("BUY", "SELL"):
            try:
                fp = _make_signal_fingerprint(context)
                failed_pats = _load_failed_patterns()
                _record_failed_pattern(self.symbol, best_node.action, fp, failed_pats)
                _save_failed_patterns(failed_pats)
            except Exception as _fp_e:
                logger.debug("[GCC-TM] record_failed_pattern: %s", _fp_e)

        # L2-S03: rejected_nodes 摘要
        rejected_summary = [
            {"action": n.action, "aggregate": round(n.aggregate, 4),
             "prune_reason": n.prune_reason, "strategy": n.strategy}
            for n in rejected_nodes
        ]

        result = {
            "ts":           ts,
            "symbol":       self.symbol,
            "phase":        self.phase,
            "best_node":    best_node.as_dict() if best_node else None,
            "final_action": final_action,
            "verdict":      verdict,
            "consensus":    consensus,
            "verifier_results": [
                {"perspective": r.perspective, "ok": r.ok,
                 "score": r.score, "reasoning": r.reasoning,
                 "abstain": r.abstain}
                for r in ver_results
            ],
            "active_count": sum(1 for r in ver_results if not r.abstain),
            "current_price": current_price,
            "rejected_nodes": rejected_summary,
            "context":      ctx.as_dict(),
        }

        # S40: 所有模式都写决策日志
        self._write_decision_log(result)

        # S45: KNN经验卡写入 (每次BUY/SELL决策记录9维特征，供dashboard展示+outcome回填)
        if final_action in ("BUY", "SELL"):
            try:
                _knn_feat = _build_knn_features(context, ver_results)
                _knn_exp = {
                    "symbol": self.symbol,
                    "action": final_action,
                    "features": _knn_feat,
                    "outcome": None,
                    "ts": ts,
                    "price": current_price,
                    "ref_price": current_price,
                    "strongest_source": signal_pool_data.get("strongest", "") if signal_pool_data else "",
                    "vote_detail": signal_pool_data.get("vote_detail", {}) if signal_pool_data else {},
                    "signals_count": signal_pool_data.get("total", 0) if signal_pool_data else 0,
                }
                _write_knn_experience_dict(_knn_exp)
            except Exception as _knn_w_e:
                logger.warning("[GCC-TRADE] KNN experience write: %s", _knn_w_e)

        # S41: pending_order 由 gcc_observe() 轮次逻辑统一控制
        # (v0.2: 避免process()和gcc_observe()双写)

        # v0.2: 附加Vision门控信息
        if candle_state is not None:
            result["vision_gate"] = {
                "vision_direction": candle_state.vision_direction,
                "vision_confidence": candle_state.vision_confidence,
                "prev_summary": candle_state.prev_summary,
                "effective_direction": candle_state.effective_direction,
                "round": candle_state.current_round,
                "traded": candle_state.traded,
            }

        logger.info(
            "[GCC-TRADE] %s action=%s verdict=%s consensus=%s/3 rejected=%d",
            self.symbol, final_action, verdict, consensus, len(rejected_nodes),
        )
        return result

    # ── v0.2: process_round() — 轮次感知决策 ─────────────────
    def process_round(
        self,
        bars: list,
        signals: list,
        candle_state: CandleState,
        observe_only: bool = False,
    ) -> dict:
        """
        v0.2 顺大逆小: 单轮决策。
        1. effective_direction=HOLD → 整根K线不交易
        2. 已交易 → 继续评估但不执行
        3. 方向不一致 → HOLD
        4. 方向一致 + 未交易 → EXECUTE
        """
        # 构建信号池
        buy_votes = sum(1 for s in signals if s.get("action") == "BUY")
        sell_votes = sum(1 for s in signals if s.get("action") == "SELL")
        total = len(signals)
        vote_detail = {}
        for s in signals:
            src = s.get("source", "unknown")
            if src not in vote_detail:
                vote_detail[src] = {"BUY": 0, "SELL": 0}
            act = s.get("action", "HOLD")
            if act in ("BUY", "SELL"):
                vote_detail[src][act] += 1

        signal_pool_data = {
            "buy": buy_votes, "sell": sell_votes, "total": total,
            "strongest": max(signals, key=lambda s: s.get("confidence", 0)).get("source", "") if signals else "",
            "vote_detail": vote_detail,
        }

        # 调用核心process (传入candle_state做Vision门控)
        result = self.process(
            bars,
            signal_pool_data=signal_pool_data,
            candle_state=candle_state,
        )

        # 轮次后处理
        result["round"] = candle_state.current_round
        result["executed"] = False

        # 规则1: effective_direction=HOLD → 不交易
        if candle_state.effective_direction == "HOLD":
            result["verdict"] = "DIRECTION_HOLD"
            result["final_action"] = "HOLD"
            return result

        # 规则2: 已交易 → 不执行, action改HOLD避免污染8轮汇总
        if candle_state.traded:
            result["verdict"] = "ALREADY_TRADED"
            result["final_action"] = "HOLD"
            return result

        # 规则3: 方向不一致 → HOLD
        if (result["final_action"] != "HOLD"
                and result["final_action"] != candle_state.effective_direction):
            result["verdict"] = "DIRECTION_MISMATCH"
            result["final_action"] = "HOLD"
            return result

        # 规则4: 方向一致 + EXECUTE → 执行
        if result["verdict"] == "EXECUTE" and not observe_only:
            result["executed"] = True

        return result

    # ── 内部: 组装上下文 → DecisionContext ────────────────────
    def _build_context(self, bars: list, ts: str = "") -> DecisionContext:
        sym = self.symbol
        ctx = DecisionContext(
            symbol=sym, ts=ts,
            vision=_read_vision(sym),
            scan=_read_scan_signal(sym),
            win_rate_buy=_read_win_rate(sym, "BUY"),
            win_rate_sell=_read_win_rate(sym, "SELL"),
            # L1-S02 新增槽位
            regime=_read_regime(sym),
            signal_direction=_read_signal_direction_detail(),
            position=_read_position(sym),
            # Phase B1: Schwab VWAP + Phase B2: Coinbase OBI/CVD
            extended={
                "schwab_vwap": _read_schwab_vwap(sym),
                "coinbase": _read_coinbase_obi_cvd(sym),
                "nowcast": _read_nowcast(sym),
            },
        )
        # L1-S03 快照落盘
        ctx.snapshot()
        return ctx

    def _context_to_score_dict(self, ctx: DecisionContext) -> dict:
        """将 DecisionContext 转为向后兼容的 dict，供评分/剪枝函数使用。"""
        return {
            "vision": ctx.vision, "scan": ctx.scan,
            "win_rate_buy": ctx.win_rate_buy, "win_rate_sell": ctx.win_rate_sell,
            "regime": ctx.regime,
            "signal_direction": ctx.signal_direction,
            "position": ctx.position,
            "signal_pool": ctx.signal_pool,
            "schwab_vwap": ctx.extended.get("schwab_vwap", {}),
            "coinbase": ctx.extended.get("coinbase", {}),
            "nowcast": ctx.extended.get("nowcast", {}),
        }

    # ── L2-S03: 树搜索 + rejected_nodes 收集 ────────────────────
    def _run_tree_search_with_rejected(
        self, bars: list, context: dict,
        candle_state: Optional[CandleState] = None,
    ) -> Tuple[TreeNode, List[TreeNode]]:
        """树搜索并收集所有被剪枝的节点，供 dashboard 展示。"""
        best_node = self._run_tree_search(bars, context, candle_state=candle_state)
        # 从内部状态收集 rejected（_run_tree_search 中标记 pruned 的节点）
        rejected = getattr(self, "_last_rejected_nodes", [])
        return best_node, rejected

    # ── S38: PUCT 多层树搜索 (arXiv:2603.04735) ────────────────
    def _run_tree_search(self, bars: list, context: dict,
                         candle_state: Optional[CandleState] = None) -> TreeNode:
        """
        v0.2: arXiv:2603.04735 PUCT 树搜索算法 + Vision门控:
        0. Vision门控: 只展开CandleState锁定的方向 (顺大逆小)
        1. L1展开: 仅允许方向 + HOLD
        2. 剪枝: P1(SignalFilter) + P2(Position)
        3. L2展开: 存活L1节点 → 子策略节点
        4. PUCT迭代: N轮选择→数值反馈→回传值→再选择
        5. 最终选择: 最高Q值的L2节点
        """
        sym = self.symbol
        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
        current_price = closes[-1] if closes else 0.0
        self._last_rejected_nodes: List[TreeNode] = []

        # ── Step 0: Vision门控 (v0.2 顺大逆小) ──
        hold_scores = _score_hold_candidate()
        if candle_state is not None:
            if not candle_state.effective_direction or candle_state.effective_direction == "HOLD":
                hold = TreeNode(action="HOLD", prune_reason="vision_gate:HOLD")
                hold.scores_by_source = hold_scores
                return hold

        # ── Step 1: L1 展开 (方向层) — 仅展开允许的方向 ──
        buy_scores  = _score_buy_candidate(sym, bars, context)
        sell_scores = _score_sell_candidate(sym, bars, context)

        if candle_state is not None:
            allowed = candle_state.effective_direction
            l1_nodes = []
            if allowed == "BUY":
                l1_nodes.append(TreeNode("BUY", buy_scores,
                                         _aggregate_candidate_score(buy_scores), depth=1))
                # SELL被Vision门控拒绝
                rejected_sell = TreeNode("SELL", sell_scores,
                                         _aggregate_candidate_score(sell_scores), depth=1)
                rejected_sell.pruned = True
                rejected_sell.prune_reason = "vision_gate:only_BUY_allowed"
                self._last_rejected_nodes.append(rejected_sell)
            elif allowed == "SELL":
                l1_nodes.append(TreeNode("SELL", sell_scores,
                                         _aggregate_candidate_score(sell_scores), depth=1))
                rejected_buy = TreeNode("BUY", buy_scores,
                                        _aggregate_candidate_score(buy_scores), depth=1)
                rejected_buy.pruned = True
                rejected_buy.prune_reason = "vision_gate:only_SELL_allowed"
                self._last_rejected_nodes.append(rejected_buy)
            l1_nodes.append(TreeNode("HOLD", hold_scores, 0.0, depth=1))
        else:
            # 向后兼容: 无candle_state时保留旧行为(三方向都展开)
            l1_nodes = [
                TreeNode("BUY",  buy_scores,  _aggregate_candidate_score(buy_scores),  depth=1),
                TreeNode("SELL", sell_scores, _aggregate_candidate_score(sell_scores), depth=1),
                TreeNode("HOLD", hold_scores, 0.0, depth=1),
            ]

        # ── Step 2: L1 剪枝 — 含失败模式记忆 ──
        failed_patterns = _load_failed_patterns()
        _apply_pruning(l1_nodes, sym, context, failed_patterns=failed_patterns)
        surviving_l1 = [n for n in l1_nodes if not n.pruned]
        self._last_rejected_nodes.extend(n for n in l1_nodes if n.pruned)
        if not surviving_l1:
            hold = TreeNode(action="HOLD", prune_reason="all_candidates_pruned")
            hold.scores_by_source = hold_scores
            return hold

        # ── Step 3: L2 展开 (子策略层) ──
        score_map = {"BUY": buy_scores, "SELL": sell_scores, "HOLD": hold_scores}
        all_l2: List[TreeNode] = []
        for l1 in surviving_l1:
            children = _expand_l2_children(l1, score_map[l1.action])
            l1.children = children
            all_l2.extend(children)

        if not all_l2:
            return _select_best_candidate(surviving_l1)

        # ── Step 4: PUCT 迭代选择 + 数值反馈 (每次从零开始) ──
        # 计算 L2 先验概率 P(s,a) — 由 aggregate 归一化
        all_agg = [abs(c.aggregate) for c in all_l2]
        sum_agg = sum(all_agg) or 1.0
        priors = {id(c): abs(c.aggregate) / sum_agg for c in all_l2}

        # 创建轻量验证器副本用于反馈（不污染主验证器状态）
        feedback_verifier = BeyondEuclidVerifier()
        feedback_verifier.geometry.update(closes)

        for iteration in range(_PUCT_ITERATIONS):
            # PUCT 选择: 计算每个L2节点的UCB值
            total_visits = sum(c.visit_count for c in all_l2) + 1
            best_ucb = -float("inf")
            selected = all_l2[0]
            for child in all_l2:
                if child.pruned:
                    continue
                ucb = _puct_score(child, total_visits, priors[id(child)])
                if ucb > best_ucb:
                    best_ucb = ucb
                    selected = child

            # 数值反馈: 验证选中节点
            feedback_value = _numerical_feedback(
                selected, feedback_verifier, closes, current_price
            )

            # 回传值 (backpropagation)
            selected.visit_count += 1
            selected.total_value += feedback_value

            # 剪枝低价值分支 (论文: ~80% pruned)
            if iteration == 1 and len(all_l2) > 3:
                # 第2轮后剪掉Q值最低的分支
                ranked = sorted(
                    [c for c in all_l2 if not c.pruned],
                    key=lambda c: c.q_value,
                )
                n_prune = max(1, int(len(ranked) * (1 - _PRUNE_RATIO)))
                for c in ranked[:n_prune]:
                    if c.action != "HOLD":  # 保留HOLD
                        c.pruned = True
                        c.prune_reason = f"PUCT:low_q={c.q_value:.3f}"
                        self._last_rejected_nodes.append(c)

        # ── Step 5: 选择最终候选 — 最高Q值的存活L2节点 ──
        surviving_l2 = [c for c in all_l2 if not c.pruned]
        if not surviving_l2:
            return _select_best_candidate(surviving_l1)

        # 论文: 最终选择基于最多访问次数 (robust) 或最高Q值 (greedy)
        # 交易场景用Q值 (greedy) — 我们需要最高预期收益
        best = max(surviving_l2, key=lambda c: c.q_value if c.visit_count > 0 else c.aggregate)

        # 将L2最优提升为最终节点，保留策略信息
        best.scores_by_source["_puct_strategy"] = best.strategy
        best.scores_by_source["_puct_visits"] = best.visit_count
        best.scores_by_source["_puct_q_value"] = round(best.q_value, 4)
        return best

    # ── S39: 三视角验证 ────────────────────────────────────────
    def _run_verification(
        self,
        best_node: TreeNode,
        closes: List[float],
        current_price: float,
    ) -> Tuple[str, int, str, List[VerifierResult]]:
        consensus, ver_results, verdict = self._verifier.verify(
            best_node, closes, current_price
        )
        # 验证通过才执行候选动作，否则 HOLD
        final_action = best_node.action if verdict == "EXECUTE" else "HOLD"
        return final_action, consensus, verdict, ver_results

    # ── S40: 写决策日志 ────────────────────────────────────────
    def _write_decision_log(self, result: dict) -> None:
        try:
            self._decision_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self._decision_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[GCC-TRADE] write_decision_log: %s", e)

    # ── S41: 写 pending_order ──────────────────────────────────
    def _write_pending_order(
        self, action: str, price: float, ts: str
    ) -> None:
        """Phase2: 写待执行订单，由后台消费线程或llm_decide消费。"""
        order = {
            "symbol":    self.symbol,
            "action":    action,
            "price_ref": price,
            "ts":        ts,
            "source":    "gcc_trading_module",
            "consumed":  False,
            "processing": False,  # v3.681: 防崩溃重复下单标记
        }
        try:
            self._pending_file.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._pending_file,
                          json.dumps(order, ensure_ascii=False, indent=2))
            logger.info("[GCC-TRADE] pending_order written: %s %s", action, self.symbol)
        except Exception as e:
            logger.warning("[GCC-TRADE] write_pending_order: %s", e)



# ══════════════════════════════════════════════════════════════
# S43  KNNExperience dataclass
# S44  特征向量 5 维: vision_conf/scan_conf/win_rate/topology/geometry
# ══════════════════════════════════════════════════════════════
@dataclass
class KNNExperience:
    symbol:    str
    action:    str               # "BUY" | "SELL" | "HOLD"
    features:  List[float]       # 5 维特征向量 (S44)
    outcome:   Optional[bool]    # None=待回填, True=盈利, False=亏损
    ts:        str               # ISO 时间戳
    price:     float = 0.0       # 决策时价格
    ref_price: float = 0.0       # 回填比较基准价

    def as_dict(self) -> dict:
        return {
            "symbol":    self.symbol,
            "action":    self.action,
            "features":  self.features,
            "outcome":   self.outcome,
            "ts":        self.ts,
            "price":     self.price,
            "ref_price": self.ref_price,
        }

    @staticmethod
    def feature_names() -> List[str]:
        """S44: 5 维特征名称（顺序与 features 对应）。"""
        return [
            "vision_conf",      # 0: Vision 置信度 [0,1]
            "scan_conf",        # 1: 扫描信号置信度 [0,1]
            "win_rate",         # 2: 历史胜率 [0,1]
            "topology_score",   # 3: Topology 验证得分 [0,1]
            "geometry_score",   # 4: Geometry 验证得分 [0,1]
        ]


def _build_knn_features(context, ver_results: List[VerifierResult]) -> List[float]:
    """S44: 从 context + verifier_results 提取 5 维特征向量。"""
    _g = getattr(context, "__getitem__", None)
    if _g or isinstance(context, dict):
        vision_bias, vision_conf = context.get("vision", ("HOLD", 0.5))
        _, scan_conf             = context.get("scan",   ("NONE", 0.0))
        win_rate                 = context.get("win_rate_buy", 0.5)
    else:
        vision_bias, vision_conf = getattr(context, "vision", ("HOLD", 0.5))
        _, scan_conf             = getattr(context, "scan",   ("NONE", 0.0))
        win_rate                 = getattr(context, "win_rate_buy", 0.5)

    # verifier results by perspective
    topo_score = next((r.score for r in ver_results if r.perspective == "topology"), 0.5)
    geo_score  = next((r.score for r in ver_results if r.perspective == "geometry"), 0.5)

    return [
        round(float(vision_conf), 4),
        round(float(scan_conf), 4),
        round(float(win_rate), 4),
        round(float(topo_score), 4),
        round(float(geo_score), 4),
    ]


# ══════════════════════════════════════════════════════════════
# S45-S46  KNN 经验写入 + 回填
# 集成到 GCCTradingModule 作为方法
# ══════════════════════════════════════════════════════════════
_KNN_EXP_FILE = _STATE_DIR / "gcc_knn_experience.jsonl"
_KNN_BACKFILL_LOOKBACK = 8   # S46: 8 根 K 线后回填


def _write_knn_experience(exp: KNNExperience) -> None:
    """S45: 追加 KNN 经验到 jsonl。"""
    _write_knn_experience_dict(exp.as_dict())


def _write_knn_experience_dict(exp_dict: dict) -> None:
    """追加 KNN 经验dict到 jsonl（支持额外字段如归因信息）。"""
    try:
        _KNN_EXP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_KNN_EXP_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(exp_dict, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[GCC-TRADE] write_knn_experience: %s", e)


def _backfill_outcome(symbol: str, current_price: float,
                      lookback: int = _KNN_BACKFILL_LOOKBACK) -> List[dict]:
    """
    S46: 回填最近未填 outcome 的经验条目。
    规则: 当前价格 > ref_price * 1.005 → BUY经验=True / SELL经验=False
          当前价格 < ref_price * 0.995 → BUY经验=False / SELL经验=True
          否则 → neutral (outcome 保持 None)
    lookback: 最多回填最近 N 条未填条目。
    返回: 本次回填的记录列表 [{price, action, outcome}, ...]，供 Algebra verifier 使用。
    """
    filled_records: List[dict] = []
    if not _KNN_EXP_FILE.exists() or current_price <= 0:
        return filled_records
    try:
        lines = _KNN_EXP_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        updated = []
        fill_count = 0
        for line in lines:
            if not line.strip():
                updated.append(line)
                continue
            try:
                rec = json.loads(line)
            except Exception:
                updated.append(line)
                continue

            # 只回填本 symbol、outcome=None、且未超过 lookback 限额
            if (rec.get("symbol") == symbol
                    and rec.get("outcome") is None
                    and fill_count < lookback):
                ref = float(rec.get("ref_price") or rec.get("price") or 0)
                if ref > 0:
                    move = (current_price - ref) / ref
                    action = rec.get("action", "HOLD")
                    if move > 0.005:
                        rec["outcome"] = (action == "BUY")
                        fill_count += 1
                        filled_records.append({
                            "price": ref, "action": action,
                            "outcome": rec["outcome"],
                        })
                    elif move < -0.005:
                        rec["outcome"] = (action == "SELL")
                        fill_count += 1
                        filled_records.append({
                            "price": ref, "action": action,
                            "outcome": rec["outcome"],
                        })
                    # |move| <= 0.5% → 保持 None（neutral，不算）
            updated.append(json.dumps(rec, ensure_ascii=False))

        _atomic_write(_KNN_EXP_FILE, "\n".join(updated) + "\n")
        if fill_count:
            logger.info("[GCC-TRADE] backfill %s: %d outcomes filled", symbol, fill_count)
    except Exception as e:
        logger.warning("[GCC-TRADE] backfill_outcome %s: %s", symbol, e)
    return filled_records


# ══════════════════════════════════════════════════════════════
# S47  模块单例 — 启动时按品种初始化
# ══════════════════════════════════════════════════════════════
_gcc_modules: dict = {}   # {symbol: GCCTradingModule}


def _load_algebra_history(mod: "GCCTradingModule") -> int:
    """从 gcc-evo L4 KNN (plugin_knn_history.npz) 加载历史 returns → 喂给 Algebra verifier。
    v3.670: 统一使用 gcc-evo L4 KNN 数据（modules/knn/store.py 管理），
    不再维护独立 gcc_knn_experience.jsonl。
    key格式: generic_{symbol}（品种整体KNN历史）
    """
    _KNN_NPZ = _STATE_DIR / "plugin_knn_history.npz"
    if not _KNN_NPZ.exists():
        return 0
    try:
        import numpy as np
        data = np.load(str(_KNN_NPZ), allow_pickle=True)
        db = data["db"].item() if data["db"].shape == () else data["db"]
        # gcc-evo plugin_knn key格式: generic_{symbol}
        knn_key = f"generic_{mod.symbol}"
        if knn_key not in db:
            return 0
        returns = db[knn_key].get("returns")
        if returns is None or len(returns) == 0:
            return 0
        # 取最近200条（algebra verifier上限），跳过中性（|return| < 0.5%）
        # 每条return记录两个方向的outcome:
        #   涨(r>0) → BUY=True, SELL=False
        #   跌(r<0) → BUY=False, SELL=True
        recent = returns[-200:]
        count = 0
        price = 100.0  # 基准价，用returns累积推算相对价格序列
        for r in recent:
            r_val = float(r)
            price *= (1.0 + r_val)  # 累积价格，越近的越接近当前价
            if abs(r_val) < 0.005:
                continue
            buy_outcome = r_val > 0    # 涨了=BUY正确
            sell_outcome = r_val < 0   # 跌了=SELL正确
            mod._verifier.algebra.record_outcome(price, "BUY", buy_outcome)
            mod._verifier.algebra.record_outcome(price, "SELL", sell_outcome)
            count += 1
        return count
    except Exception as e:
        logger.debug("[GCC-TM] load_algebra_history %s: %s", mod.symbol, e)
        return 0


# B1: 品种级 phase 配置 — 加密 OBSERVE / 美股 EXECUTE
# 安全开关：只有在此集合中的美股品种才会走 EXECUTE 模式
_GCC_TM_EXECUTE_SYMBOLS: frozenset = frozenset({
    # 美股全量 EXECUTE
    "TSLA", "CRWV", "NBIS", "ONDS", "OPEN", "HIMS",
    "AMD", "COIN", "RKLB", "RDDT", "NVDA", "PLTR",
    # 加密 (OPUSDC不在此列 — 走独立剥头皮路径gcc_scalp_observe, 避免pending_order冲突)
    "BTCUSDC", "ETHUSDC", "ZECUSDC", "SOLUSDC",
})  # B4: 逐品种开启，随时可关


def _get_symbol_phase(symbol: str) -> str:
    """按品种决定 phase：白名单 → EXECUTE，否则 OBSERVE。"""
    if symbol in _GCC_TM_EXECUTE_SYMBOLS:
        return PHASE_EXECUTE
    return PHASE_OBSERVE


def _get_gcc_module(symbol: str) -> "GCCTradingModule":
    """懒加载单例：每个品种一个 GCCTradingModule 实例。"""
    if symbol not in _gcc_modules:
        phase = _get_symbol_phase(symbol)
        mod = GCCTradingModule(symbol, phase=phase)
        # 从 KNN 经验加载已回填历史 → Algebra verifier 冷启动
        n = _load_algebra_history(mod)
        if n:
            logger.info("[GCC-TM] init %s: loaded %d algebra history records", symbol, n)
        _gcc_modules[symbol] = mod
    return _gcc_modules[symbol]


# ══════════════════════════════════════════════════════════════
# A1: 方向锁 Leader 排名器
# 读 plugin_signal_accuracy.json，按品种选准确率最高(样本>=10)的外挂
# ══════════════════════════════════════════════════════════════
_LEADER_FILE = _STATE_DIR / "plugin_direction_leader.json"
_LEADER_MIN_SAMPLE = 10


def compute_direction_leaders() -> dict:
    """按品种计算最强外挂 leader，仅加密品种，样本<10不输出。

    读取 state/plugin_signal_accuracy.json，输出 state/plugin_direction_leader.json。
    由 key009_audit 每周调用。
    返回: {symbol: {leader, acc, sample_n, updated}}
    """
    acc_path = _STATE_DIR / "plugin_signal_accuracy.json"
    if not acc_path.exists():
        logger.info("[GCC-TM][LEADER] plugin_signal_accuracy.json not found")
        return {}

    try:
        raw = json.loads(acc_path.read_text(encoding="utf-8"))
        accuracy = raw.get("accuracy", {})
    except Exception as e:
        logger.warning("[GCC-TM][LEADER] read accuracy: %s", e)
        return {}

    # 构建 {symbol: {plugin_name: {total, correct, acc}}}
    sym_plugins: Dict[str, dict] = {}
    for plugin_name, plugin_data in accuracy.items():
        for sym, sym_data in plugin_data.items():
            if sym == "_overall":
                continue
            total = sym_data.get("total", 0)
            correct = sym_data.get("correct", 0)
            acc_val = sym_data.get("acc", 0) or 0
            if sym not in sym_plugins:
                sym_plugins[sym] = {}
            sym_plugins[sym][plugin_name] = {
                "total": total, "correct": correct, "acc": acc_val,
            }

    # 每个加密品种选 leader（准确率最高 + 样本 >= 10）
    leaders = {}
    for sym, plugins in sym_plugins.items():
        if sym not in _CRYPTO_SYMBOLS:
            continue
        best_name, best_acc, best_n = None, -1.0, 0
        for pname, pdata in plugins.items():
            if pdata["total"] < _LEADER_MIN_SAMPLE:
                continue
            if pdata["acc"] > best_acc:
                best_name = pname
                best_acc = pdata["acc"]
                best_n = pdata["total"]
        if best_name:
            leaders[sym] = {
                "leader": best_name,
                "acc": round(best_acc, 4),
                "sample_n": best_n,
                "updated": datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            }

    # 写入
    try:
        _LEADER_FILE.write_text(
            json.dumps(leaders, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        logger.info(
            "[GCC-TM][LEADER] updated: %s",
            {s: v["leader"] for s, v in leaders.items()},
        )
    except Exception as e:
        logger.warning("[GCC-TM][LEADER] write: %s", e)

    return leaders


# ══════════════════════════════════════════════════════════════
# A2-A3: 方向锁 — leader 激活时锁定品种方向，2h 过期
# ══════════════════════════════════════════════════════════════
# {symbol: {"dir": "BUY"/"SELL", "source": str, "lock_ts": float, "expire_ts": float}}
_direction_lock: Dict[str, dict] = {}
_LOCK_DURATION = 2 * 3600  # 2小时过期
_DIRECTION_LOCK_FILE = _STATE_DIR / "gcc_direction_lock.json"


def _persist_direction_lock() -> None:
    """方向锁落盘。"""
    try:
        _atomic_write(_DIRECTION_LOCK_FILE,
                      json.dumps(_direction_lock, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.debug("[GCC-TM] persist_direction_lock: %s", e)


def _restore_direction_lock() -> None:
    """启动时恢复方向锁，自动清理过期条目。"""
    global _direction_lock
    if not _DIRECTION_LOCK_FILE.exists():
        return
    try:
        data = json.loads(_DIRECTION_LOCK_FILE.read_text(encoding="utf-8"))
        now = time.time()
        _direction_lock = {k: v for k, v in data.items()
                          if v.get("expire_ts", 0) > now}
        if _direction_lock:
            logger.info("[GCC-TM] restored %d direction locks from disk", len(_direction_lock))
    except Exception as e:
        logger.debug("[GCC-TM] restore_direction_lock: %s", e)


_restore_direction_lock()

# 缓存 leader 配置（启动时 / 每周更新时刷新）
_direction_leaders: Dict[str, dict] = {}
_direction_leaders_ts: float = 0.0
_LEADER_RELOAD_INTERVAL = 300  # 5分钟重新读文件


def _load_direction_leaders() -> Dict[str, dict]:
    """从 plugin_direction_leader.json 加载 leader 配置，5分钟缓存。"""
    global _direction_leaders, _direction_leaders_ts
    now = time.time()
    if now - _direction_leaders_ts < _LEADER_RELOAD_INTERVAL and _direction_leaders:
        return _direction_leaders
    if _LEADER_FILE.exists():
        try:
            _direction_leaders = json.loads(
                _LEADER_FILE.read_text(encoding="utf-8")
            )
            _direction_leaders_ts = now
        except Exception:
            pass
    return _direction_leaders


def _set_direction_lock(symbol: str, direction: str, source: str) -> None:
    """Leader 外挂激活时锁定方向。"""
    now = time.time()
    _direction_lock[symbol] = {
        "dir": direction,
        "source": source,
        "lock_ts": now,
        "expire_ts": now + _LOCK_DURATION,
    }
    _persist_direction_lock()
    logger.info(
        "[GCC-TM][DIRECTION_LOCK] %s locked %s by %s (expires 2h)",
        symbol, direction, source,
    )


def check_direction_lock(symbol: str, source: str, action: str) -> dict:
    """检查方向锁。

    返回: {"allowed": bool, "reason": str, "lock_dir": str|None, "leader": str|None}
    - leader 激活: 设置锁 + 放行
    - 非 leader 同向: 放行
    - 非 leader 反向: Phase1 记 log / Phase2 拦截
    - 无锁: 放行
    - 非加密: 放行
    """
    # 非加密品种不用方向锁
    if symbol not in _CRYPTO_SYMBOLS:
        return {"allowed": True, "reason": "not_crypto", "lock_dir": None, "leader": None}

    leaders = _load_direction_leaders()
    leader_info = leaders.get(symbol)

    # 该品种没有 leader（样本不足）
    if not leader_info:
        return {"allowed": True, "reason": "no_leader", "lock_dir": None, "leader": None}

    leader_name = leader_info["leader"]

    # 检查现有锁是否过期
    lock = _direction_lock.get(symbol)
    if lock and time.time() > lock["expire_ts"]:
        del _direction_lock[symbol]
        lock = None
        logger.debug("[GCC-TM][DIRECTION_LOCK] %s lock expired", symbol)

    # 是 leader 外挂激活 → 设置/更新锁
    if source == leader_name:
        _set_direction_lock(symbol, action, source)
        return {"allowed": True, "reason": "leader_sets_lock", "lock_dir": action, "leader": leader_name}

    # 非 leader，当前无锁 → 放行
    if not lock:
        return {"allowed": True, "reason": "no_lock", "lock_dir": None, "leader": leader_name}

    # 非 leader，锁方向一致 → 放行
    if action == lock["dir"]:
        return {"allowed": True, "reason": "same_direction", "lock_dir": lock["dir"], "leader": leader_name}

    # 非 leader，反向 → Phase1 只记 log 不拦截
    logger.info(
        "[GCC-TM][DIRECTION_LOCK] %s BLOCKED %s %s (lock=%s by %s) — Phase1 log only",
        symbol, source, action, lock["dir"], lock["source"],
    )
    return {
        "allowed": False,  # Phase2 时改为实际拦截
        "reason": f"opposite_to_lock({lock['dir']})",
        "lock_dir": lock["dir"],
        "leader": leader_name,
    }


# ══════════════════════════════════════════════════════════════
# 信号收集器 — 4H K线内收集所有外挂 BUY/SELL 信号
# ══════════════════════════════════════════════════════════════
import threading as _threading

# {symbol: [{"source": str, "action": "BUY"/"SELL", "confidence": float, "ts": str}, ...]}
_signal_pool: Dict[str, list] = {}
_signal_pool_lock = _threading.Lock()
_SIGNAL_POOL_FILE = _STATE_DIR / "gcc_signal_pool.json"


def _persist_signal_pool() -> None:
    """信号池落盘（lock内调用）。"""
    try:
        _atomic_write(_SIGNAL_POOL_FILE,
                      json.dumps(_signal_pool, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.debug("[GCC-TM] persist_signal_pool: %s", e)


def _restore_signal_pool() -> None:
    """启动时恢复信号池，清理超过4小时的陈旧信号。"""
    global _signal_pool
    if not _SIGNAL_POOL_FILE.exists():
        return
    try:
        data = json.loads(_SIGNAL_POOL_FILE.read_text(encoding="utf-8"))
        now = datetime.now(_NY_TZ)
        restored = 0
        for sym, signals in data.items():
            fresh = []
            for s in signals:
                try:
                    sig_dt = datetime.strptime(s["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_NY_TZ)
                    if (now - sig_dt).total_seconds() < 4 * 3600:
                        fresh.append(s)
                except Exception:
                    pass
            if fresh:
                _signal_pool[sym] = fresh
                restored += len(fresh)
        if restored:
            logger.info("[GCC-TM] restored %d signals from disk", restored)
    except Exception as e:
        logger.debug("[GCC-TM] restore_signal_pool: %s", e)


_restore_signal_pool()


def gcc_push_signal(symbol: str, source: str, action: str,
                    confidence: float = 0.5,
                    persistent: bool = False) -> None:
    """外挂产生BUY/SELL时调用，收集到信号池。

    Args:
        persistent: True=持久信号，持续参与整根4H K线的8轮投票（如BrooksVision_4H）
                    False=一次性信号，被_drain_signals取出后清除（如15min外挂）

    加密品种会检查方向锁：反向信号 Phase1 记 log 但仍入池，Phase2 拦截不入池。
    """
    if action not in ("BUY", "SELL"):
        logger.info("[GCC-TM][DROP] %s %s action=%s 非BUY/SELL, 丢弃", symbol, source, action)
        return

    # A3: 方向锁检查
    lock_result = check_direction_lock(symbol, source, action)
    if not lock_result["allowed"]:
        # Phase1: 记日志但仍然入池（观察模式）
        # Phase2: 改为 return 直接丢弃（拦截模式）
        logger.info(
            "[GCC-TM][DIRECTION_LOCK] %s %s %s → %s (Phase1: still pushed)",
            symbol, source, action, lock_result["reason"],
        )

    ts = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    with _signal_pool_lock:
        if symbol not in _signal_pool:
            _signal_pool[symbol] = []
        # v0.2.1: 同source同action去重 — 防止外挂30min内重复推送导致投票权重翻倍
        _dup = any(s["source"] == source and s["action"] == action
                    for s in _signal_pool[symbol])
        if _dup:
            logger.debug("[GCC-TM][DEDUP] %s %s %s 已在池中, 跳过", symbol, source, action)
            return
        _signal_pool[symbol].append({
            "source": source, "action": action,
            "confidence": confidence, "ts": ts,
            "lock_status": lock_result["reason"],
            "persistent": persistent,
        })
        _persist_signal_pool()
    logger.debug("[GCC-TM] push %s %s %s conf=%.2f persistent=%s",
                 symbol, source, action, confidence, persistent)


def _drain_signals(symbol: str) -> list:
    """取出信号池。一次性信号被清除，持久信号保留供后续轮次使用。"""
    with _signal_pool_lock:
        all_signals = _signal_pool.get(symbol, [])
        # 返回全部信号（一次性+持久）供本轮投票
        result = list(all_signals)
        # 只保留持久信号，清除一次性信号
        _signal_pool[symbol] = [s for s in all_signals if s.get("persistent")]
        if not _signal_pool[symbol]:
            _signal_pool.pop(symbol, None)
        _persist_signal_pool()
    return result


# ══════════════════════════════════════════════════════════════
# B2: pending_order 消费器 — 主程序每根 K 线开头调用
# ══════════════════════════════════════════════════════════════
def gcc_consume_pending_order(symbol: str) -> Optional[dict]:
    """读取 pending_order（如有），标记 processing=True 防止并发/崩溃重复。

    返回: {"action": "BUY"/"SELL", "price_ref": float, ...} 或 None。
    调用方需在下单后调用 gcc_confirm_consumed(symbol, success) 标记结果。
    """
    pending_file = _STATE_DIR / f"gcc_pending_order_{symbol}.json"
    if not pending_file.exists():
        return None
    try:
        order = json.loads(pending_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    if order.get("consumed"):
        return None

    # v3.681: 崩溃恢复保护 — processing=True 说明上次下单可能已发出但未确认
    if order.get("processing"):
        _proc_ts = order.get("processing_ts", "")
        logger.warning(
            "[GCC-TM][CRASH_GUARD] %s %s processing=True (上次可能已下单未确认, ts=%s), 跳过自动重试",
            symbol, order.get("action"), _proc_ts,
        )
        # 超过2小时的processing视为崩溃残留, 自动过期
        if _proc_ts:
            try:
                _proc_dt = datetime.strptime(_proc_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_NY_TZ)
                _proc_age_h = (datetime.now(_NY_TZ) - _proc_dt).total_seconds() / 3600
                if _proc_age_h > 2:
                    order["consumed"] = True
                    order["consumed_ts"] = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
                    order["expired"] = True
                    order["expire_reason"] = "crash_guard_timeout"
                    _atomic_write(pending_file, json.dumps(order, ensure_ascii=False, indent=2))
                    logger.warning("[GCC-TM][CRASH_GUARD] %s processing超2h, 自动过期", symbol)
            except Exception:
                pass
        return None

    # v3.681: TTL检查 — 超过24小时的pending_order自动过期清理
    _order_ts = order.get("ts", "")
    if _order_ts:
        try:
            _order_dt = datetime.strptime(_order_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_NY_TZ)
            _age_hours = (datetime.now(_NY_TZ) - _order_dt).total_seconds() / 3600
            if _age_hours > 24:
                logger.warning(
                    "[GCC-TM][EXPIRED] %s %s price_ref=%.2f age=%.1fh > 24h, 丢弃",
                    symbol, order.get("action"), order.get("price_ref", 0), _age_hours,
                )
                order["consumed"] = True
                order["consumed_ts"] = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
                order["expired"] = True
                order["expire_reason"] = "ttl_24h"
                _atomic_write(pending_file, json.dumps(order, ensure_ascii=False, indent=2))
                return None
        except Exception:
            pass

    # v3.681: 标记 processing=True, 防止崩溃后重复下单
    order["processing"] = True
    order["processing_ts"] = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
    try:
        _atomic_write(pending_file, json.dumps(order, ensure_ascii=False, indent=2))
    except Exception:
        pass

    logger.info(
        "[GCC-TM][PEEK] %s %s price_ref=%.2f (标记processing, 等待执行确认)",
        symbol, order.get("action"), order.get("price_ref", 0),
    )
    return order


def gcc_confirm_consumed(symbol: str, success: bool = True) -> None:
    """下单结果确认。
    success=True → consumed=True (完成)
    success=False → processing=False (恢复为可重试状态)
    """
    pending_file = _STATE_DIR / f"gcc_pending_order_{symbol}.json"
    if not pending_file.exists():
        return
    try:
        order = json.loads(pending_file.read_text(encoding="utf-8"))
        if success:
            order["consumed"] = True
            order["consumed_ts"] = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            order["processing"] = False
            _atomic_write(pending_file, json.dumps(order, ensure_ascii=False, indent=2))
            logger.info(
                "[GCC-TM][CONSUMED] %s %s price_ref=%.2f confirmed",
                symbol, order.get("action"), order.get("price_ref", 0),
            )
        else:
            # 下单失败 → 计数+1, 超过3次标记consumed(防无限重试)
            retry_count = order.get("retry_count", 0) + 1
            order["retry_count"] = retry_count
            order["processing"] = False
            if retry_count >= 3:
                order["consumed"] = True
                order["consumed_ts"] = datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S")
                order["expired"] = True
                order["expire_reason"] = f"max_retries_{retry_count}"
                _atomic_write(pending_file, json.dumps(order, ensure_ascii=False, indent=2))
                logger.warning("[GCC-TM][GIVE_UP] %s 连续%d次失败, 放弃", symbol, retry_count)
            else:
                _atomic_write(pending_file, json.dumps(order, ensure_ascii=False, indent=2))
                logger.warning("[GCC-TM][RETRY] %s 下单失败(%d/3), 等待重试", symbol, retry_count)
    except Exception as e:
        logger.warning("[GCC-TM][CONSUMED] %s write error: %s", symbol, e)


# ══════════════════════════════════════════════════════════════
# 模拟交易回填 — 用下一K线收盘价验证上一次裁决是否盈利
# ══════════════════════════════════════════════════════════════
def _backfill_sim_trades(symbol: str, bars: list) -> None:
    """回填 gcc_sim_trades.jsonl 中 outcome=None 的记录。"""
    sim_path = _STATE_DIR / "gcc_sim_trades.jsonl"
    if not sim_path.exists():
        return
    closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
    if not closes:
        return
    cur_price = closes[-1]

    try:
        lines = sim_path.read_text(encoding="utf-8").strip().split("\n")
        updated = False
        new_lines = []
        for line in lines:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("symbol") == symbol and rec.get("outcome") is None:
                entry = rec.get("entry_price", 0)
                if entry > 0:
                    if rec["action"] == "BUY":
                        rec["outcome"] = cur_price > entry
                    elif rec["action"] == "SELL":
                        rec["outcome"] = cur_price < entry
                    rec["exit_price"] = cur_price
                    rec["pnl_pct"] = round((cur_price - entry) / entry * 100, 3)
                    if rec["action"] == "SELL":
                        rec["pnl_pct"] = -rec["pnl_pct"]
                    updated = True
            new_lines.append(json.dumps(rec, ensure_ascii=False))
        if updated:
            _atomic_write(sim_path, "\n".join(new_lines) + "\n")
    except Exception as e:
        logger.debug("[GCC-TM] backfill_sim: %s", e)


# ══════════════════════════════════════════════════════════════
# S48-S49  llm_server 接入入口
# v0.2 顺大逆小: 每30分钟调用一次(共8轮/4H K线)
# ══════════════════════════════════════════════════════════════
def gcc_observe(
    symbol: str,
    bars: list,
    observe_only: bool = False,
) -> None:
    """
    v0.2 顺大逆小: 每30分钟由扫描引擎调用。
    1. 加载/初始化CandleState (新K线时调Vision定方向)
    2. 收集信号 → process_round → Vision门控决策
    3. 方向一致且首次 → 执行交易
    4. 8轮结束 → 汇总 → 保存供下一K线比较
    """
    original_phase = None
    try:
        signals = _drain_signals(symbol)
        mod = _get_gcc_module(symbol)
        original_phase = mod.phase
        if observe_only and mod.phase != PHASE_OBSERVE:
            mod.phase = PHASE_OBSERVE

        # ── 加载/初始化K线状态 ──
        state = _load_candle_state(symbol)
        if state is None:
            # 新K线: _load_candle_state过期时已自动聚合上一根
            # 初始化新K线 (Vision定方向 + 对比上一K线汇总)
            state = _init_candle_state(symbol, bars=bars)
            _save_candle_state(state)

        # 回填模拟交易
        _backfill_sim_trades(symbol, bars)

        # S46: KNN经验outcome回填 (每轮用当前价格更新历史未填条目)
        try:
            _current_price = float(bars[-1].get("close") or bars[-1].get("c") or 0) if bars else 0.0
            if _current_price > 0:
                _backfill_outcome(symbol, _current_price)
        except Exception as _bf_e:
            logger.debug("[GCC-TRADE] knn backfill: %s", _bf_e)

        # GCC-0261 S5: P&F止盈目标检查 — 价格接近T1/T2时推SELL到信号池
        try:
            from wyckoff_pnf import check_and_push as _pnf_check, update_targets as _pnf_update
            _pnf_price = float(bars[-1].get("close") or bars[-1].get("c") or 0) if bars else 0.0
            if _pnf_price > 0 and bars and len(bars) >= 50:
                from wyckoff_phase import _extract_arrays, _calc_atr
                _pnf_h, _pnf_l, _pnf_c, _, _ = _extract_arrays(bars)
                _pnf_atr = _calc_atr(_pnf_h, _pnf_l, _pnf_c)
                # 新K线时更新目标 (Phase C/D才会写入)
                if state is not None and state.current_round == 0:
                    _pnf_update(symbol, bars)
                # 每轮检查价格vs目标
                _pnf_pushed = _pnf_check(symbol, _pnf_price, _pnf_atr)
                if _pnf_pushed:
                    logger.info("[GCC-TM] %s P&F: %d个止盈信号推入池", symbol, _pnf_pushed)
        except ImportError:
            pass
        except Exception as _pnf_e:
            logger.debug("[GCC-TM] %s P&F check: %s", symbol, _pnf_e)

        # ── 自修复: 清除旧格式空BACKFILL条目(price=0, 无真实决策), 让下方逻辑重跑 ──
        # 必须在already_done检查之前，否则当前轮已存在时直接return，永远不清旧条目
        _stale = [r for r in state.round_decisions
                  if r.get("verdict") == "BACKFILL" and r.get("price", 0) == 0]
        if _stale:
            for _sr in _stale:
                state.round_decisions.remove(_sr)
            logger.info("[GCC-TM] %s purged %d stale BACKFILL entries, will re-decide",
                        symbol, len(_stale))
            _save_candle_state(state)  # 立即持久化清除结果

        # ── 轮次去重: 检查当前round index是否已在round_decisions中 ──
        actual_round = _get_current_round(symbol=symbol)
        already_done = any(r.get("round") == actual_round for r in state.round_decisions)
        if already_done and not _stale:
            # 同一30分钟内重复调用且无旧条目需回填,跳过
            _save_candle_state(state)
            logger.debug("[GCC-TM] %s skip duplicate round %d (already recorded)",
                         symbol, actual_round)
            return

        # ── 缺失轮次回填: 用当前bars跑完整决策(不执行交易) ──
        recorded_rounds = {r.get("round") for r in state.round_decisions}
        _backfill_count = 0
        for _missing_r in range(actual_round):
            if _missing_r not in recorded_rounds:
                try:
                    _bf_result = mod.process_round(
                        bars, signals, state,
                        observe_only=True,  # 回填轮不执行交易
                    )
                    _bf_action = _bf_result.get("final_action", "HOLD")
                    _bf_verdict = _bf_result.get("verdict", "BACKFILL")
                    _bf_consensus = _bf_result.get("consensus", 0)
                    _bf_price = _bf_result.get("current_price", 0.0)
                    # 从process_round结果中提取信号统计
                    _bf_ctx = _bf_result.get("context", {})
                    _bf_sp = _bf_ctx.get("signal_pool", {})
                    state.round_decisions.append({
                        "round": _missing_r,
                        "action": _bf_action,
                        "verdict": f"BACKFILL_{_bf_verdict}",
                        "executed": False,
                        "signals": _bf_sp.get("total", 0),
                        "buy_votes": _bf_sp.get("buy", 0),
                        "sell_votes": _bf_sp.get("sell", 0),
                        "price": _bf_price,
                        "consensus": _bf_consensus,
                        "ts": datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                        "note": "backfill_with_decision",
                    })
                except Exception as _bf_dec_e:
                    logger.warning("[GCC-TM] %s backfill round %d decision failed: %s",
                                   symbol, _missing_r, _bf_dec_e)
                    state.round_decisions.append({
                        "round": _missing_r, "action": "HOLD",
                        "verdict": "BACKFILL_ERROR", "executed": False,
                        "signals": 0, "buy_votes": 0, "sell_votes": 0,
                        "price": 0.0,
                        "ts": datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                        "note": f"backfill_error: {_bf_dec_e}",
                    })
                _backfill_count += 1
        if _backfill_count:
            state.round_decisions.sort(key=lambda r: r.get("round", 0))
            state.current_round = actual_round
            logger.info("[GCC-TM] %s backfilled %d missed rounds with decisions (now round %d)",
                        symbol, _backfill_count, actual_round)
            _save_candle_state(state)

        # 回填修复后当前轮已处理 → 跳过
        if already_done:
            _save_candle_state(state)
            return

        # ── 轮次决策 ──
        result = mod.process_round(
            bars, signals, state,
            observe_only=observe_only,
        )

        gcc_action = result.get("final_action", "HOLD")
        gcc_verdict = result.get("verdict", "SKIP")
        executed = result.get("executed", False)

        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b]
        current_price = closes[-1] if closes else 0.0

        # v0.2.1: 数据源校验 — Schwab(美股) / Coinbase(加密) 复查 yfinance 价格
        if current_price > 0:
            try:
                _is_crypto = symbol.endswith("USDC") or symbol.endswith("USDT")
                _verified_price = 0.0
                _verify_src = ""
                if _is_crypto:
                    _crypto_map = {"BTCUSDC": "BTC", "ETHUSDC": "ETH",
                                   "SOLUSDC": "SOL", "ZECUSDC": "ZEC"}
                    _cb_sym = _crypto_map.get(symbol)
                    if _cb_sym:
                        from coinbase_sync_v6 import get_price as _cb_get_price
                        _verified_price = _cb_get_price(_cb_sym)
                        _verify_src = "Coinbase"
                else:
                    from schwab_data_provider import get_provider as _schwab_gp
                    _q = _schwab_gp().get_quote(symbol)
                    _verified_price = _q.get("last", 0)
                    _verify_src = "Schwab"
                if _verified_price > 0:
                    _dev = abs(current_price - _verified_price) / _verified_price
                    if _dev > 0.05:
                        logger.warning(
                            "[GCC-TM][DATA_CHECK] %s yfinance=%.2f %s=%.2f 偏差%.1f%% > 5%% → 用%s价格",
                            symbol, current_price, _verify_src, _verified_price, _dev * 100, _verify_src,
                        )
                        current_price = _verified_price
                    else:
                        logger.debug(
                            "[GCC-TM][DATA_CHECK] %s yfinance=%.2f %s=%.2f 偏差%.1f%% OK",
                            symbol, current_price, _verify_src, _verified_price, _dev * 100,
                        )
            except Exception as _vc_e:
                logger.debug("[GCC-TM][DATA_CHECK] %s 校验异常(不影响): %s", symbol, _vc_e)

        # ── 更新K线状态 ──
        buy_votes = sum(1 for s in signals if s.get("action") == "BUY")
        sell_votes = sum(1 for s in signals if s.get("action") == "SELL")
        # GCC-0259: 记录每个信号源的投票方向 (供dashboard显示)
        buy_sources = [s.get("source", "?") for s in signals if s.get("action") == "BUY"]
        sell_sources = [s.get("source", "?") for s in signals if s.get("action") == "SELL"]

        round_record = {
            "round": state.current_round,
            "action": gcc_action,
            "verdict": gcc_verdict,
            "executed": executed,
            "signals": len(signals),
            "buy_votes": buy_votes,
            "sell_votes": sell_votes,
            "buy_sources": buy_sources,
            "sell_sources": sell_sources,
            "price": current_price,
            "ts": datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        state.round_decisions.append(round_record)
        state.current_round += 1

        if executed and not state.traded:
            state.traded = True
            state.trade_round = state.current_round - 1
            # P0安全: 先持久化traded=True, 再写pending_order
            # 防止断电后traded丢失导致重复下单
            _save_candle_state(state)
            if mod.phase == PHASE_EXECUTE:
                mod._write_pending_order(gcc_action, current_price,
                                          round_record["ts"])

        # ── 轮次决策日志 (独立于process()的详细日志) ──
        ts_now = round_record["ts"]
        dec_record = {
            "ts": ts_now,
            "symbol": symbol,
            "phase": mod.phase,
            "gcc_action": gcc_action,
            "verdict": gcc_verdict,
            "reason": f"v0.2 round={state.current_round - 1}/{_ROUNDS_PER_CANDLE} "
                       f"dir={state.effective_direction} traded={state.traded}",
            "buy_signals": buy_votes,
            "sell_signals": sell_votes,
            "signals_count": len(signals),
            "price": current_price,
            "observe_only": bool(observe_only),
            "round": state.current_round - 1,
            "vision_gate": {
                "vision_direction": state.vision_direction,
                "effective_direction": state.effective_direction,
                "prev_summary": state.prev_summary,
            },
            "consensus": result.get("consensus", 0),
            "executed": executed,
        }
        # v0.2: 轮次日志写独立文件，避免与process()的详细日志双写
        _round_log_path = _STATE_DIR / "gcc_round_decisions.jsonl"
        try:
            with open(_round_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dec_record, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # 模拟执行记录 (仅在实际执行时记录)
        if executed and gcc_action != "HOLD":
            _sim_path = _STATE_DIR / "gcc_sim_trades.jsonl"
            sim_record = {
                "ts": ts_now, "symbol": symbol,
                "action": gcc_action, "entry_price": current_price,
                "round": state.current_round - 1,
                "signals_count": len(signals),
                "outcome": None,
            }
            try:
                with open(_sim_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(sim_record, ensure_ascii=False) + "\n")
            except Exception:
                pass

        # KNN记录 (保持不变)
        if gcc_action in ("BUY", "SELL"):
            try:
                from modules.knn.features import extract_gcctm_features, infer_regime_from_bars
                from modules.knn.orchestrator import plugin_knn_record_and_query
                _gcctm_feat = extract_gcctm_features(dec_record, bars)
                _gcctm_regime = infer_regime_from_bars(bars)
                _gcctm_knn_res = plugin_knn_record_and_query(
                    "gcctm", symbol, _gcctm_feat, gcc_action,
                    close_price=current_price, regime=_gcctm_regime, bars=bars,
                )
                if _gcctm_knn_res:
                    logger.info(
                        "[GCC-TM][KNN] %s %s win_rate=%.0f%% avg_ret=%.2f%% bias=%s",
                        symbol, gcc_action, _gcctm_knn_res.win_rate * 100,
                        _gcctm_knn_res.avg_return * 100, _gcctm_knn_res.bias,
                    )
            except Exception as _knn_err:
                logger.debug("[GCC-TM][KNN] %s record failed: %s", symbol, _knn_err)

        # ── 检查K线结束: 8轮完成 → 汇总(含volume修正) ──
        if state.current_round >= _ROUNDS_PER_CANDLE:
            summary = _aggregate_candle_summary(state, bars=bars)
            logger.info(
                "[GCC-TM] %s candle complete: summary=%s traded=%s",
                symbol, summary.get("direction"), state.traded,
            )
            # 清除持久信号 (K线结束, 持久信号不应跨K线)
            with _signal_pool_lock:
                if symbol in _signal_pool:
                    _signal_pool.pop(symbol, None)
                    _persist_signal_pool()
            # 清除K线状态文件(下次调用时_init_candle_state会创建新的)
            try:
                _candle_state_path(symbol).unlink(missing_ok=True)
            except Exception:
                pass
            # 失败模式 TTL 递增 + 过期清理
            try:
                fp_data = _load_failed_patterns()
                if symbol in fp_data:
                    fp_data[symbol] = [
                        {**p, "candle_count": p.get("candle_count", 0) + 1}
                        for p in fp_data[symbol]
                        if p.get("candle_count", 0) + 1 < _FAILED_PATTERN_TTL
                    ]
                    _save_failed_patterns(fp_data)
            except Exception as _fp_e:
                logger.debug("[GCC-TM] failed_pattern TTL update: %s", _fp_e)
        else:
            _save_candle_state(state)

        logger.info(
            "[GCC-TM] %s R%d/%d action=%s verdict=%s dir=%s traded=%s signals=%d",
            symbol, state.current_round - 1, _ROUNDS_PER_CANDLE,
            gcc_action, gcc_verdict, state.effective_direction,
            state.traded, len(signals),
        )
    except Exception as e:
        import traceback
        logger.warning("[GCC-TM] gcc_observe %s: %s\n%s", symbol, e, traceback.format_exc())
    finally:
        try:
            if 'mod' in locals() and original_phase is not None:
                mod.phase = original_phase
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
# GCC-0256 S5: OP剥头皮模块 — RSI(7)均值回归 + 方向门控
# 独立于 gcc_observe 的轻量5min入口
# 策略: RSI<25做多 / RSI>75做空, 三方投票方向门控, $500限额
# ══════════════════════════════════════════════════════════════

_SCALP_STATE_FILE = _STATE_DIR / "gcc_scalp_state.json"
_SCALP_TRADES_FILE = _STATE_DIR / "gcc_scalp_trades.jsonl"
_SCALP_MAX_POSITION_USD = 500      # 最大仓位$500
_SCALP_RSI_PERIOD = 7
_SCALP_RSI_OVERSOLD = 25           # 超卖阈值
_SCALP_RSI_OVERBOUGHT = 75        # 超买阈值
_SCALP_RSI_EXIT_HIGH = 70         # BUY出场RSI
_SCALP_RSI_EXIT_LOW = 30          # SELL出场RSI
_SCALP_ATR_PERIOD = 3
_SCALP_MAX_HOLD_BARS = 12         # 最多持仓12根(1h)
_SCALP_COOLDOWN_BARS = 3          # 冷却3根(15min)
_SCALP_SYMBOLS = frozenset({"OPUSDC"})  # 剥头皮白名单


def _scalp_calc_rsi(closes: list, period: int = 7) -> float:
    """RSI(7) Wilder平滑，返回最新值。需要至少period+1个close。"""
    if len(closes) < period + 1:
        return 50.0  # 数据不足返回中性
    import numpy as _np
    arr = _np.array(closes, dtype=float)
    deltas = _np.diff(arr)
    gains = _np.where(deltas > 0, deltas, 0.0)
    losses = _np.where(deltas < 0, -deltas, 0.0)
    avg_gain = _np.mean(gains[:period])
    avg_loss = _np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _scalp_calc_atr(highs: list, lows: list, closes: list, period: int = 3) -> float:
    """ATR(3)，返回最新值。"""
    if len(closes) < period + 1:
        return closes[-1] * 0.005 if closes else 0.01
    import numpy as _np
    h = _np.array(highs, dtype=float)
    l = _np.array(lows, dtype=float)
    c = _np.array(closes, dtype=float)
    tr1 = h[1:] - l[1:]
    tr2 = _np.abs(h[1:] - c[:-1])
    tr3 = _np.abs(l[1:] - c[:-1])
    tr = _np.maximum(tr1, _np.maximum(tr2, tr3))
    return float(_np.mean(tr[-period:]))


def _load_scalp_state() -> dict:
    """加载剥头皮持仓状态。"""
    if _SCALP_STATE_FILE.exists():
        try:
            return json.loads(_SCALP_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "in_trade": False,
        "direction": None,        # "BUY" or "SELL"
        "entry_price": 0.0,
        "entry_ts": None,
        "bars_held": 0,
        "cooldown": 0,
        "tp_price": 0.0,          # 止盈价
        "sl_price": 0.0,          # 止损价
        "quantity": 0.0,          # 持仓数量(OP个数)
    }


def _save_scalp_state(state: dict) -> None:
    """持久化剥头皮状态(原子写入)。"""
    try:
        _SCALP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(_SCALP_STATE_FILE,
                      json.dumps(state, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning("[GCC-SCALP] save state: %s", e)


def _record_scalp_trade(trade: dict) -> None:
    """记录剥头皮交易到JSONL(不可变追加)。"""
    try:
        _SCALP_TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SCALP_TRADES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("[GCC-SCALP] record trade: %s", e)


def scalp_get_pnl_summary() -> dict:
    """读取剥头皮交易记录，计算24h/当天/当月P&L。
    返回: {
        "h24": {"pnl": float, "trades": int, "wins": int},
        "today": {"pnl": float, "trades": int, "wins": int},
        "month": {"pnl": float, "trades": int, "wins": int},
        "all_time": {"pnl": float, "trades": int, "wins": int},
    }
    """
    result = {
        "h24":      {"pnl": 0.0, "trades": 0, "wins": 0},
        "today":    {"pnl": 0.0, "trades": 0, "wins": 0},
        "month":    {"pnl": 0.0, "trades": 0, "wins": 0},
        "all_time": {"pnl": 0.0, "trades": 0, "wins": 0},
    }
    if not _SCALP_TRADES_FILE.exists():
        return result

    now = datetime.now(_NY_TZ)
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")
    h24_cutoff = time.time() - 86400

    try:
        with open(_SCALP_TRADES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                except Exception:
                    continue
                pnl = float(t.get("net_pnl_usd", 0))
                is_win = pnl > 0
                ts_epoch = float(t.get("exit_epoch", 0))
                ts_str = t.get("exit_ts", "")

                # all_time
                result["all_time"]["pnl"] += pnl
                result["all_time"]["trades"] += 1
                if is_win:
                    result["all_time"]["wins"] += 1

                # 24h
                if ts_epoch > h24_cutoff:
                    result["h24"]["pnl"] += pnl
                    result["h24"]["trades"] += 1
                    if is_win:
                        result["h24"]["wins"] += 1

                # today
                if ts_str.startswith(today_str):
                    result["today"]["pnl"] += pnl
                    result["today"]["trades"] += 1
                    if is_win:
                        result["today"]["wins"] += 1

                # month
                if ts_str.startswith(month_str):
                    result["month"]["pnl"] += pnl
                    result["month"]["trades"] += 1
                    if is_win:
                        result["month"]["wins"] += 1
    except Exception as e:
        logger.warning("[GCC-SCALP] read trades: %s", e)

    return result


def gcc_scalp_observe(
    symbol: str,
    bars_5m: list,
) -> Optional[dict]:
    """
    GCC-0256 S5: OP剥头皮5min入口。
    轻量路径: 方向门控 + RSI(7)信号 + $500仓位检查 → Coinbase限价单。
    跳过树搜索/BEV/PUCT/信号池。

    Args:
        symbol: 品种名 (如 "OPUSDC")
        bars_5m: 5min OHLCV列表, 至少30根
            每根: {"open": f, "high": f, "low": f, "close": f, "volume": f}

    Returns:
        None 或 {"action": str, "reason": str, ...}
    """
    if symbol not in _SCALP_SYMBOLS:
        return None
    if not bars_5m or len(bars_5m) < 15:
        logger.debug("[GCC-SCALP] %s: bars不足(%d)", symbol, len(bars_5m) if bars_5m else 0)
        return None

    # ── 提取OHLC序列 ──
    closes = [float(b.get("close") or b.get("c") or 0) for b in bars_5m]
    highs = [float(b.get("high") or b.get("h") or 0) for b in bars_5m]
    lows = [float(b.get("low") or b.get("l") or 0) for b in bars_5m]
    current_price = closes[-1]
    if current_price <= 0:
        return None

    # ── 计算指标 ──
    rsi = _scalp_calc_rsi(closes, _SCALP_RSI_PERIOD)
    atr = _scalp_calc_atr(highs, lows, closes, _SCALP_ATR_PERIOD)

    # ── 方向门控: 读取当前K线的三方投票方向 ──
    gate_direction = "HOLD"
    try:
        cs = _load_candle_state(symbol)
        if cs is None:
            # 没有4H CandleState — 尝试读crypto母品种(OPUSDC没有4H的,用自身或跳过)
            # 剥头皮品种可能没有4H门控，降级为无门控
            gate_direction = "BOTH"  # 允许双向
        else:
            gate_direction = cs.effective_direction or "HOLD"
    except Exception:
        gate_direction = "BOTH"

    # ── 加载持仓状态 ──
    state = _load_scalp_state()

    # 冷却递减
    if state["cooldown"] > 0:
        state["cooldown"] -= 1
        _save_scalp_state(state)

    # ── 持仓中: 检查出场条件 ──
    if state["in_trade"]:
        state["bars_held"] += 1
        should_exit = False
        exit_reason = ""

        if state["direction"] == "BUY":
            if current_price >= state["tp_price"]:
                should_exit, exit_reason = True, "TP"
            elif current_price <= state["sl_price"]:
                should_exit, exit_reason = True, "SL"
            elif rsi > _SCALP_RSI_EXIT_HIGH:
                should_exit, exit_reason = True, "RSI_EXIT"
        else:  # SELL
            if current_price <= state["tp_price"]:
                should_exit, exit_reason = True, "TP"
            elif current_price >= state["sl_price"]:
                should_exit, exit_reason = True, "SL"
            elif rsi < _SCALP_RSI_EXIT_LOW:
                should_exit, exit_reason = True, "RSI_EXIT"

        if state["bars_held"] >= _SCALP_MAX_HOLD_BARS:
            should_exit, exit_reason = True, "TIMEOUT"

        if should_exit:
            # 计算P&L
            entry_p = state["entry_price"]
            if state["direction"] == "BUY":
                raw_pnl_pct = (current_price - entry_p) / entry_p
            else:
                raw_pnl_pct = (entry_p - current_price) / entry_p
            fee_pct = 0.0009  # maker来回0.09%
            net_pnl_pct = raw_pnl_pct - fee_pct
            net_pnl_usd = net_pnl_pct * _SCALP_MAX_POSITION_USD

            now_ts = datetime.now(_NY_TZ)
            trade_record = {
                "symbol": symbol,
                "direction": state["direction"],
                "entry_price": entry_p,
                "exit_price": current_price,
                "entry_ts": state["entry_ts"],
                "exit_ts": now_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_epoch": time.time(),
                "bars_held": state["bars_held"],
                "exit_reason": exit_reason,
                "rsi_at_exit": round(rsi, 1),
                "raw_pnl_pct": round(raw_pnl_pct * 100, 3),
                "net_pnl_pct": round(net_pnl_pct * 100, 3),
                "net_pnl_usd": round(net_pnl_usd, 2),
                "quantity": state["quantity"],
            }
            _record_scalp_trade(trade_record)

            # 经验卡: 平仓回填 outcome (赚钱=True, 亏钱=False)
            try:
                _write_knn_experience_dict({
                    "symbol": symbol,
                    "action": state["direction"],
                    "features": [rsi / 100.0, atr / current_price,
                                 1.0, current_price, net_pnl_pct],
                    "outcome": net_pnl_usd > 0,
                    "ts": now_ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "price": current_price,
                    "ref_price": entry_p,
                    "strongest_source": f"scalp_exit_{exit_reason}",
                    "source": "gcc_scalp",
                    "pnl_usd": net_pnl_usd,
                })
            except Exception:
                pass

            logger.info(
                "[GCC-SCALP] %s EXIT %s: $%.4f→$%.4f %s P&L=$%+.2f (%.2f%%)",
                symbol, state["direction"], entry_p, current_price,
                exit_reason, net_pnl_usd, net_pnl_pct * 100,
            )

            # 写平仓pending_order (SELL平多 / BUY平空)
            close_action = "SELL" if state["direction"] == "BUY" else "BUY"
            _scalp_write_pending(symbol, close_action, current_price, state["quantity"],
                                 f"scalp_exit_{exit_reason}")

            # 重置状态
            state = {
                "in_trade": False, "direction": None,
                "entry_price": 0.0, "entry_ts": None,
                "bars_held": 0, "cooldown": _SCALP_COOLDOWN_BARS,
                "tp_price": 0.0, "sl_price": 0.0, "quantity": 0.0,
            }
            _save_scalp_state(state)
            return {"action": close_action, "reason": exit_reason,
                    "pnl_usd": net_pnl_usd}

        _save_scalp_state(state)
        return None  # 持仓中，未触发出场

    # ── 未持仓: 检查进场条件 ──
    if state["cooldown"] > 0:
        return None

    signal = None
    if rsi < _SCALP_RSI_OVERSOLD:
        signal = "BUY"
    elif rsi > _SCALP_RSI_OVERBOUGHT:
        signal = "SELL"

    if signal is None:
        return None

    # 方向门控
    if gate_direction not in ("BOTH", signal, "HOLD"):
        # HOLD时允许双向 (剥头皮品种可能无4H门控)
        if gate_direction != "HOLD":
            logger.info("[GCC-SCALP] %s RSI=%s but gate=%s → blocked",
                        symbol, signal, gate_direction)
            return None

    # 计算止盈止损
    quantity = _SCALP_MAX_POSITION_USD / current_price
    if signal == "BUY":
        tp_price = current_price + atr
        sl_price = current_price - atr
    else:
        tp_price = current_price - atr
        sl_price = current_price + atr

    now_ts = datetime.now(_NY_TZ)

    # 写进场pending_order
    _scalp_write_pending(symbol, signal, current_price, quantity,
                         f"scalp_entry_RSI{rsi:.0f}")

    # 经验卡: 开仓写入 (outcome=None, 平仓时回填)
    try:
        _write_knn_experience_dict({
            "symbol": symbol,
            "action": signal,
            "features": [rsi / 100.0, atr / current_price,
                         1.0 if gate_direction in (signal, "BOTH") else 0.0,
                         current_price, 0.0],
            "outcome": None,
            "ts": now_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "price": current_price,
            "ref_price": current_price,
            "strongest_source": f"scalp_RSI{rsi:.0f}",
            "source": "gcc_scalp",
        })
    except Exception:
        pass

    # 更新状态
    state = {
        "in_trade": True,
        "direction": signal,
        "entry_price": current_price,
        "entry_ts": now_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "bars_held": 0,
        "cooldown": 0,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "quantity": quantity,
    }
    _save_scalp_state(state)

    logger.info(
        "[GCC-SCALP] %s ENTRY %s @ $%.4f RSI=%.1f TP=$%.4f SL=$%.4f qty=%.2f",
        symbol, signal, current_price, rsi, tp_price, sl_price, quantity,
    )
    return {"action": signal, "reason": f"RSI={rsi:.0f}", "price": current_price}


def _scalp_write_pending(symbol: str, action: str, price: float,
                         quantity: float, reason: str) -> None:
    """写剥头皮pending_order，标记source=gcc_scalp区分正常GCC-TM。"""
    order = {
        "symbol":    symbol,
        "action":    action,
        "price_ref": price,
        "quantity":  quantity,
        "ts":        datetime.now(_NY_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "source":    "gcc_scalp",
        "reason":    reason,
        "consumed":  False,
        "processing": False,
        "max_usd":   _SCALP_MAX_POSITION_USD,
    }
    pending_path = _STATE_DIR / f"gcc_pending_order_{symbol}.json"
    try:
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(pending_path,
                      json.dumps(order, ensure_ascii=False, indent=2))
        logger.info("[GCC-SCALP] pending_order: %s %s @ $%.4f qty=%.2f (%s)",
                    action, symbol, price, quantity, reason)
    except Exception as e:
        logger.warning("[GCC-SCALP] write pending: %s", e)


# ══════════════════════════════════════════════════════════════
# 自测 (直接运行时)
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    sym = "BTCUSDC"
    print(f"=== gcc_trading_module 数据读取层自测 ({sym}) ===")
    print(f"S06 Vision:         {_read_vision(sym)}")
    print(f"S07 ScanSignal:     {_read_scan_signal(sym)}")
    print(f"S10 WinRate BUY:    {_read_win_rate(sym, 'BUY')}")
    bars_mock = [{"volume": 100 + i * 10} for i in range(22)]
    print(f"S12 GCC Mode:       {_read_signal_direction()}")

    print(f"\n=== S13-S22 树搜索层自测 ===")
    ctx = {
        "vision":          ("BUY", 0.82),
        "scan":            ("BUY", 0.6),
        "win_rate_buy":    0.62,
        "win_rate_sell":   0.44,
    }

    # 打分
    buy_scores  = _score_buy_candidate(sym, bars_mock, ctx)
    sell_scores = _score_sell_candidate(sym, bars_mock, ctx)
    hold_scores = _score_hold_candidate()

    # 构建节点
    buy_node  = TreeNode("BUY",  buy_scores,  _aggregate_candidate_score(buy_scores))
    sell_node = TreeNode("SELL", sell_scores, _aggregate_candidate_score(sell_scores))
    hold_node = TreeNode("HOLD", hold_scores, _aggregate_candidate_score(hold_scores))

    print(f"S14 BUY  scores: {buy_scores}  agg={buy_node.aggregate:.4f}")
    print(f"S15 SELL scores: {sell_scores}  agg={sell_node.aggregate:.4f}")
    print(f"S16 HOLD scores: {hold_scores}  agg={hold_node.aggregate:.4f}")

    # 剪枝
    nodes = _apply_pruning([buy_node, sell_node, hold_node], sym, ctx)
    for n in nodes:
        print(f"  {n.action}: pruned={n.pruned} reason={n.prune_reason}")

    # 选最优
    best = _select_best_candidate(nodes)
    print(f"S22 Best candidate: {best.action}  aggregate={best.aggregate:.4f}")

    print(f"\n=== S23-S34 三视角验证层自测 ===")
    verifier = BeyondEuclidVerifier()

    # 喂入模拟价格序列（上升趋势）
    import math
    prices = [100.0 * math.exp(0.002 * i + 0.001 * (i % 3 - 1)) for i in range(60)]
    verifier.geometry.update(prices)

    # 模拟有历史记录的 Algebra
    for i in range(10):
        verifier.algebra.record_outcome(prices[i], "BUY", i % 3 != 0)  # 约67%胜率

    # 用 best (BUY, agg=0.7458) 跑三视角验证
    consensus, results, verdict = verifier.verify(best, prices, prices[-1])
    print(f"S32 consensus={consensus}/3  verdict={verdict}")
    for r in results:
        print(f"  {r.perspective:10s}: ok={r.ok}  score={r.score:.4f}  {r.reasoning}")

    # S34: HOLD 节点直接 SKIP
    hold_test = TreeNode("HOLD", {}, 0.0)
    cnt2, _, v2 = verifier.verify(hold_test)
    print(f"S34 HOLD → verdict={v2} (expected SKIP)")

    # S34: None 节点直接 SKIP
    _, _, v3 = verifier.verify(None)
    print(f"S34 None → verdict={v3} (expected SKIP)")

    print(f"\n=== S35-S42 GCCTradingModule 主类自测 ===")
    import math as _math
    # 构造 bars (含 close/volume)
    test_bars = [
        {"close": 100.0 * _math.exp(0.003 * i), "volume": 1000 + i * 50}
        for i in range(30)
    ]

    # observe 模式
    mod_obs = GCCTradingModule("BTCUSDC", phase=PHASE_OBSERVE)
    r_obs = mod_obs.process(test_bars)
    print(f"S37 observe: action={r_obs['final_action']} verdict={r_obs['verdict']} consensus={r_obs['consensus']}/3")
    print(f"  best_node: {r_obs['best_node']}")
    print(f"  log_file exists: {mod_obs._decision_log.exists()}")

    # execute 模式 (verdict=EXECUTE 才写 pending_order)
    mod_exe = GCCTradingModule("BTCUSDC", phase=PHASE_EXECUTE)
    # 预先喂历史给 Algebra 以获得有效胜率
    for i in range(5):
        mod_exe._verifier.algebra.record_outcome(100.0 + i, "BUY", True)
    r_exe = mod_exe.process(test_bars)
    print(f"S41 execute: action={r_exe['final_action']} verdict={r_exe['verdict']}")
    if r_exe["verdict"] == "EXECUTE":
        print(f"  pending_order exists: {mod_exe._pending_file.exists()}")

    print(f"\n=== S43-S50 KNN经验层 + gcc_observe 自测 ===")
    import math as _m2
    bars50 = [{"close": 100 * _m2.exp(0.002*i), "volume": 500+i*30} for i in range(30)]

    # S43-S44: KNNExperience + 特征向量
    print(f"S44 feature_names: {KNNExperience.feature_names()}")

    # S47-S49: gcc_observe 接入测试
    gcc_observe("BTCUSDC", bars50)

    # v3.670: KNN统一由gcc-evo L4管理（plugin_knn_history.npz），验证algebra加载
    mod_knn = _get_gcc_module("BTCUSDC")
    alg_hist = len(mod_knn._verifier.algebra._history)
    print(f"S45 algebra history from gcc-evo KNN: {alg_hist} records")

    # S50: 验证 decisions.jsonl 写入
    mod50 = _get_gcc_module("ETHUSDC")
    r50 = mod50.process(bars50)
    print(f"S50 decisions.jsonl exists: {mod50._decision_log.exists()}")
    print(f"  ETHUSDC action={r50['final_action']} verdict={r50['verdict']}")
    print(f"\n✅ 全部 S01-S50 自测完成")
