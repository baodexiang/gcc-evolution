"""
缠论买卖点外挂 v2.0
===================
周期自适应，不写死任何时间周期。
信号: BUY (一买/二买/三买) / SELL (一卖/二卖/三卖)

依赖: czsc_lite.py
"""

import logging
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("chan_bs_plugin")

try:
    from czsc_lite import CZSC, RawBar, Freq, ZS
    _czsc_available = True
except ImportError:
    _czsc_available = False
    logger.warning("czsc_lite.py未找到，缠论买卖点外挂禁用")


# ============================================================
# 周期映射
# ============================================================

FREQ_MAP = {
    "1m": Freq.F1, "5m": Freq.F5, "15m": Freq.F15, "30m": Freq.F30,
    "1H": Freq.F60, "4H": Freq.F240,
    "1D": Freq.D, "1W": Freq.W, "1M": Freq.M,
} if _czsc_available else {}

FREQ_ALIASES = {
    "60m": "1H", "1h": "1H", "4h": "4H", "240m": "4H",
    "D": "1D", "d": "1D", "daily": "1D",
    "W": "1W", "w": "1W", "weekly": "1W",
}


def _resolve_freq(freq_str: str) -> "Freq":
    freq_str = FREQ_ALIASES.get(freq_str.strip(), freq_str.strip())
    if freq_str in FREQ_MAP:
        return FREQ_MAP[freq_str]
    raise ValueError(f"未知周期: {freq_str}, 支持: {list(FREQ_MAP.keys())}")


# ============================================================
# 数据结构
# ============================================================

class BSPoint(Enum):
    BUY_1 = "一买"
    BUY_2 = "二买"
    BUY_3 = "三买"
    SELL_1 = "一卖"
    SELL_2 = "二卖"
    SELL_3 = "三卖"


@dataclass
class ChanSignal:
    type: BSPoint
    price: float
    zs_zg: float
    zs_zd: float
    strength: float
    dt: datetime
    reason: str
    stop_loss: float
    target: float


@dataclass
class ChanBSResult:
    signal: str = "NONE"
    bs_type: Optional[BSPoint] = None
    strength: float = 0.0
    price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    zs_zg: float = 0.0
    zs_zd: float = 0.0
    reason: str = ""
    bi_count: int = 0
    zs_count: int = 0
    freq: str = ""


# ============================================================
# 核心算法
# ============================================================

def find_zhongshu(bi_list) -> List[dict]:
    if not _czsc_available or len(bi_list) < 3:
        return []
    result = []
    i = 0
    while i <= len(bi_list) - 3:
        try:
            zs = ZS(bis=bi_list[i:i+3])
        except Exception:
            i += 1
            continue
        if not zs.is_valid:
            i += 1
            continue
        zs_bis = list(bi_list[i:i+3])
        j = i + 3
        while j < len(bi_list):
            bi = bi_list[j]
            if bi.low < zs.zg and bi.high > zs.zd:
                zs_bis.append(bi)
                j += 1
            else:
                break
        result.append({
            'zg': zs.zg, 'zd': zs.zd,
            'gg': zs.gg, 'dd': zs.dd,
            'sdt': zs.sdt,
            'edt': zs_bis[-1].edt if hasattr(zs_bis[-1], 'edt') else None,
            'bi_count': len(zs_bis),
        })
        i = j
    return result


def _bi_strength(bi) -> float:
    amplitude = abs(bi.high - bi.low)
    if hasattr(bi, 'raw_bars') and bi.raw_bars:
        n_bars = max(len(bi.raw_bars), 1)
        efficiency = amplitude / n_bars
        return amplitude * (1 + efficiency / max(amplitude, 0.001))
    return amplitude


def _check_divergence(bi_a, bi_b, direction: str = "down") -> Tuple[bool, float]:
    s_a = _bi_strength(bi_a)
    s_b = _bi_strength(bi_b)
    if s_a <= 0:
        return False, 0.0
    ratio = s_b / s_a
    if direction == "down":
        is_div = ratio < 0.8 and bi_b.low <= bi_a.low * 1.02
    else:
        is_div = ratio < 0.8 and bi_b.high >= bi_a.high * 0.98
    strength = min(1.0, max(0, (1.0 - ratio) / 0.5))
    return is_div, strength


def _is_down_bi(bi) -> bool:
    d = str(getattr(bi, 'direction', ''))
    return '下' in d or 'Down' in d


def _is_up_bi(bi) -> bool:
    d = str(getattr(bi, 'direction', ''))
    return '上' in d or 'Up' in d


def detect_chan_signals(bi_list, zhongshu_list) -> List[ChanSignal]:
    signals = []
    if not zhongshu_list or len(bi_list) < 5:
        return signals

    last_zs = zhongshu_list[-1]
    zs_range = last_zs['zg'] - last_zs['zd']
    zs_edt = last_zs['edt']
    zs_sdt = last_zs['sdt']

    before_bis = [bi for bi in bi_list
                  if hasattr(bi, 'edt') and zs_sdt and bi.edt <= zs_sdt]
    after_bis = [bi for bi in bi_list
                 if hasattr(bi, 'sdt') and zs_edt and bi.sdt >= zs_edt]
    if not after_bis:
        after_bis = bi_list[-3:]

    # === 一买: 底背驰 ===
    if before_bis and after_bis:
        down_before = [bi for bi in before_bis if _is_down_bi(bi)]
        down_after = [bi for bi in after_bis if _is_down_bi(bi)]
        if down_before and down_after:
            bi_a, bi_b = down_before[-1], down_after[-1]
            if bi_b.low < last_zs['zd']:
                is_div, div_s = _check_divergence(bi_a, bi_b, "down")
                if is_div and div_s >= 0.2:
                    signals.append(ChanSignal(
                        type=BSPoint.BUY_1, price=bi_b.low,
                        zs_zg=last_zs['zg'], zs_zd=last_zs['zd'],
                        strength=min(div_s * 1.2, 1.0),
                        dt=bi_b.edt if hasattr(bi_b, 'edt') else datetime.now(),
                        reason=f"底背驰 力度比={_bi_strength(bi_b)/_bi_strength(bi_a):.2f} "
                               f"低点{bi_b.low:.2f}<中枢下沿{last_zs['zd']:.2f}",
                        stop_loss=bi_b.low * 0.97,
                        target=last_zs['zg'],
                    ))

        # === 一卖: 顶背驰 ===
        up_before = [bi for bi in before_bis if _is_up_bi(bi)]
        up_after = [bi for bi in after_bis if _is_up_bi(bi)]
        if up_before and up_after:
            bi_a, bi_b = up_before[-1], up_after[-1]
            if bi_b.high > last_zs['zg']:
                is_div, div_s = _check_divergence(bi_a, bi_b, "up")
                if is_div and div_s >= 0.2:
                    signals.append(ChanSignal(
                        type=BSPoint.SELL_1, price=bi_b.high,
                        zs_zg=last_zs['zg'], zs_zd=last_zs['zd'],
                        strength=min(div_s * 1.2, 1.0),
                        dt=bi_b.edt if hasattr(bi_b, 'edt') else datetime.now(),
                        reason=f"顶背驰 力度比={_bi_strength(bi_b)/_bi_strength(bi_a):.2f} "
                               f"高点{bi_b.high:.2f}>中枢上沿{last_zs['zg']:.2f}",
                        stop_loss=bi_b.high * 1.03,
                        target=last_zs['zd'],
                    ))

    # === 二买/二卖 ===
    if len(after_bis) < 2:
        return signals

    for i in range(1, len(after_bis)):
        bi = after_bis[i]
        prev_bi = after_bis[i - 1]

        if _is_down_bi(bi) and _is_up_bi(prev_bi):
            if bi.low > last_zs['zd']:
                margin = (bi.low - last_zs['zd']) / zs_range if zs_range > 0 else 0.5
                signals.append(ChanSignal(
                    type=BSPoint.BUY_2, price=bi.low,
                    zs_zg=last_zs['zg'], zs_zd=last_zs['zd'],
                    strength=min(margin, 1.0),
                    dt=bi.edt if hasattr(bi, 'edt') else datetime.now(),
                    reason=f"回调{bi.low:.2f}>中枢下沿{last_zs['zd']:.2f}",
                    stop_loss=last_zs['zd'],
                    target=last_zs['gg'] + zs_range if zs_range > 0 else bi.low * 1.03,
                ))

        if _is_up_bi(bi) and _is_down_bi(prev_bi):
            if bi.high < last_zs['zg']:
                margin = (last_zs['zg'] - bi.high) / zs_range if zs_range > 0 else 0.5
                signals.append(ChanSignal(
                    type=BSPoint.SELL_2, price=bi.high,
                    zs_zg=last_zs['zg'], zs_zd=last_zs['zd'],
                    strength=min(margin, 1.0),
                    dt=bi.edt if hasattr(bi, 'edt') else datetime.now(),
                    reason=f"反弹{bi.high:.2f}<中枢上沿{last_zs['zg']:.2f}",
                    stop_loss=last_zs['zg'],
                    target=last_zs['dd'] - zs_range if zs_range > 0 else bi.high * 0.97,
                ))

    # === 三买/三卖 ===
    if len(zhongshu_list) >= 2:
        prev_zs = zhongshu_list[-2]
        if last_zs['zd'] > prev_zs['zg']:
            for bi in after_bis:
                if _is_down_bi(bi) and bi.low > prev_zs['zg']:
                    gap = last_zs['zd'] - prev_zs['zg']
                    signals.append(ChanSignal(
                        type=BSPoint.BUY_3, price=bi.low,
                        zs_zg=prev_zs['zg'], zs_zd=prev_zs['zd'],
                        strength=min(1.0, (bi.low - prev_zs['zg']) / max(gap, 0.01)),
                        dt=bi.edt if hasattr(bi, 'edt') else datetime.now(),
                        reason=f"回踩{bi.low:.2f}>前中枢上沿{prev_zs['zg']:.2f}",
                        stop_loss=prev_zs['zg'],
                        target=last_zs['gg'] + (last_zs['gg'] - last_zs['dd']),
                    ))
        if last_zs['zg'] < prev_zs['zd']:
            for bi in after_bis:
                if _is_up_bi(bi) and bi.high < prev_zs['zd']:
                    gap = prev_zs['zd'] - last_zs['zg']
                    signals.append(ChanSignal(
                        type=BSPoint.SELL_3, price=bi.high,
                        zs_zg=prev_zs['zg'], zs_zd=prev_zs['zd'],
                        strength=min(1.0, (prev_zs['zd'] - bi.high) / max(gap, 0.01)),
                        dt=bi.edt if hasattr(bi, 'edt') else datetime.now(),
                        reason=f"反抽{bi.high:.2f}<前中枢下沿{prev_zs['zd']:.2f}",
                        stop_loss=prev_zs['zd'],
                        target=last_zs['dd'] - (prev_zs['gg'] - prev_zs['dd']),
                    ))

    return signals


# ============================================================
# 外挂主类 (周期参数化)
# ============================================================

class ChanBSPlugin:
    """缠论买卖点外挂 — 周期由调用方指定"""

    VERSION = "2.0"

    def __init__(self, freq: str = "4H"):
        self.freq = freq
        self.czsc_freq = _resolve_freq(freq) if _czsc_available else None

    def process_for_scan(
        self,
        symbol: str,
        ohlcv_bars: List[Dict],
        current_trend: str = "SIDE",
        min_strength: float = 0.3,
    ) -> ChanBSResult:
        result = ChanBSResult(freq=self.freq)

        if not _czsc_available:
            result.reason = "czsc未安装"
            return result
        if not ohlcv_bars or len(ohlcv_bars) < 30:
            result.reason = f"K线不足: {len(ohlcv_bars) if ohlcv_bars else 0} < 30"
            return result

        bars = self._to_raw_bars(symbol, ohlcv_bars)
        if not bars:
            result.reason = "RawBar转换失败"
            return result

        try:
            czsc = CZSC(bars)
        except Exception as e:
            result.reason = f"CZSC初始化异常: {e}"
            return result

        if len(czsc.bi_list) < 5:
            result.reason = f"笔不足: {len(czsc.bi_list)} < 5"
            result.bi_count = len(czsc.bi_list)
            return result

        zhongshu_list = find_zhongshu(czsc.bi_list)
        result.bi_count = len(czsc.bi_list)
        result.zs_count = len(zhongshu_list)

        if not zhongshu_list:
            result.reason = "无中枢"
            return result

        signals = detect_chan_signals(czsc.bi_list, zhongshu_list)
        if not signals:
            result.reason = "无买卖点信号"
            return result

        # 一买一卖优先 (纯结构驱动，不看trend)
        bs1 = [s for s in signals
               if s.type in (BSPoint.BUY_1, BSPoint.SELL_1)
               and s.strength >= min_strength]
        if bs1:
            best = max(bs1, key=lambda s: s.strength)
            result.signal = "BUY" if best.type == BSPoint.BUY_1 else "SELL"
            result.bs_type = best.type
            result.strength = best.strength
            result.price = best.price
            result.stop_loss = best.stop_loss
            result.target = best.target
            result.zs_zg = best.zs_zg
            result.zs_zd = best.zs_zd
            result.reason = f"{best.type.value}: {best.reason}"
            return result

        # 二买三买/二卖三卖: 结合trend方向
        buy_signals = [s for s in signals
                       if s.type in (BSPoint.BUY_2, BSPoint.BUY_3)
                       and s.strength >= min_strength]
        sell_signals = [s for s in signals
                        if s.type in (BSPoint.SELL_2, BSPoint.SELL_3)
                        and s.strength >= min_strength]

        best = None
        if current_trend == "UP" and buy_signals:
            best = max(buy_signals, key=lambda s: s.strength)
            result.signal = "BUY"
        elif current_trend == "DOWN" and sell_signals:
            best = max(sell_signals, key=lambda s: s.strength)
            result.signal = "SELL"
        elif current_trend == "SIDE":
            best_buy = max(buy_signals, key=lambda s: s.strength) if buy_signals else None
            best_sell = max(sell_signals, key=lambda s: s.strength) if sell_signals else None
            if best_buy and best_sell:
                best = best_buy if best_buy.strength >= best_sell.strength else best_sell
            elif best_buy:
                best = best_buy
            elif best_sell:
                best = best_sell
            if best:
                result.signal = "BUY" if best.type in (BSPoint.BUY_2, BSPoint.BUY_3) else "SELL"

        if best:
            result.bs_type = best.type
            result.strength = best.strength
            result.price = best.price
            result.stop_loss = best.stop_loss
            result.target = best.target
            result.zs_zg = best.zs_zg
            result.zs_zd = best.zs_zd
            result.reason = f"{best.type.value}: {best.reason}"
        else:
            result.reason = f"有{len(signals)}个信号但方向不匹配(trend={current_trend})"

        return result

    def should_activate_for_scan(self, result: ChanBSResult, min_strength: float = 0.3) -> bool:
        return result.signal in ("BUY", "SELL") and result.strength >= min_strength

    def get_action_for_scan(self, result: ChanBSResult) -> str:
        return result.signal

    def _to_raw_bars(self, symbol: str, ohlcv_bars: List[Dict]) -> list:
        if not _czsc_available:
            return []
        bars = []
        for bar in ohlcv_bars:
            try:
                dt = bar.get("timestamp") or bar.get("time") or bar.get("dt") or bar.get("datetime")
                if dt is None:
                    dt = datetime.now()
                elif isinstance(dt, str):
                    try:
                        from pandas import to_datetime
                        dt = to_datetime(dt).to_pydatetime()
                    except Exception:
                        dt = datetime.now()
                elif hasattr(dt, 'to_pydatetime'):
                    dt = dt.to_pydatetime()
                if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)

                raw = RawBar(
                    symbol=symbol, dt=dt, freq=self.czsc_freq,
                    open=float(bar.get("open", 0)),
                    close=float(bar.get("close", 0)),
                    high=float(bar.get("high", 0)),
                    low=float(bar.get("low", 0)),
                    vol=float(bar.get("vol", bar.get("volume", 0))),
                    amount=float(bar.get("amount", 0)),
                )
                bars.append(raw)
            except Exception as e:
                logger.debug(f"RawBar转换跳过: {e}")
                continue
        return bars


# ============================================================
# KEY-004: symbol级 min_strength 参数化
# ============================================================

_min_strength_cache: Dict[str, float] = {}

# 默认值: 加密波动大→放宽, 股票→收紧
_DEFAULT_MIN_STRENGTH_CRYPTO = 0.25
_DEFAULT_MIN_STRENGTH_STOCK = 0.35


def _is_crypto(symbol: str) -> bool:
    return any(kw in symbol.upper() for kw in ("BTC", "ETH", "SOL", "ZEC", "USDC", "USDT"))


def get_symbol_min_strength(symbol: str) -> float:
    """从 .GCC/params/<SYMBOL>.yaml 读取 plugin.chan_bs.min_strength，带缓存。"""
    if symbol in _min_strength_cache:
        return _min_strength_cache[symbol]

    default = _DEFAULT_MIN_STRENGTH_CRYPTO if _is_crypto(symbol) else _DEFAULT_MIN_STRENGTH_STOCK
    try:
        import yaml
        yaml_path = os.path.join(".GCC", "params", f"{symbol}.yaml")
        if os.path.exists(yaml_path):
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            val = (data.get("plugin", {}) or {}).get("chan_bs", {}) or {}
            if "min_strength" in val:
                default = float(val["min_strength"])
    except Exception as e:
        logger.warning(f"[KEY004][CHANBS] {symbol} YAML读取min_strength异常: {e}")

    _min_strength_cache[symbol] = default
    return default


# ============================================================
# 单例 (按周期缓存)
# ============================================================

_plugin_instances: Dict[str, ChanBSPlugin] = {}
_plugin_lock = threading.Lock()


def get_chan_bs_plugin(freq: str = "4H") -> ChanBSPlugin:
    """获取缠论买卖点外挂 (按周期缓存)"""
    global _plugin_instances
    if freq not in _plugin_instances:
        with _plugin_lock:
            if freq not in _plugin_instances:
                _plugin_instances[freq] = ChanBSPlugin(freq=freq)
    return _plugin_instances[freq]
