"""
缠论交易系统 v2.0
================================

周期自适应架构:
  - 不写死任何时间周期
  - 初始化时传入 base_freq (当前周期) 和 sub_ratio (子周期比)
  - 例: base_freq="4H", sub_ratio=4 → 用4根1H判断4H趋势, 在4H上做缠论
  - 例: base_freq="1D", sub_ratio=4 → 用4根4H判断日线趋势, 在日线上做缠论
  - 例: base_freq="1H", sub_ratio=4 → 用4根15m判断1H趋势, 在1H上做缠论

两层架构:
  1. N根子周期三段    → 当前周期趋势/震荡
  2. czsc缠论         → 当前周期一/二/三买卖点

扫描引擎:
  每根子周期收线 → 更新趋势状态
  每根当前周期收线 → 更新缠论买卖点
  有信号就激活，没有就跳过

安装:
  pip install czsc pandas numpy

作者: D's Trading System
日期: 2025-02-07
版本: v2.0 - 周期参数化 + 一买一卖
"""

import pandas as pd
import numpy as np
from czsc import CZSC, RawBar, Freq, ZS
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum


# ============================================================
# 周期映射
# ============================================================

FREQ_MAP = {
    "1m":   Freq.F1,
    "5m":   Freq.F5,
    "15m":  Freq.F15,
    "30m":  Freq.F30,
    "1H":   Freq.F60,
    "4H":   Freq.F240,
    "1D":   Freq.D,
    "1W":   Freq.W,
    "1M":   Freq.M,
}


def to_czsc_freq(freq_str: str) -> Freq:
    """字符串周期 → czsc Freq枚举"""
    freq_str = freq_str.strip()
    if freq_str in FREQ_MAP:
        return FREQ_MAP[freq_str]
    aliases = {
        "60m": Freq.F60, "60min": Freq.F60, "1h": Freq.F60,
        "240m": Freq.F240, "240min": Freq.F240, "4h": Freq.F240,
        "D": Freq.D, "d": Freq.D, "daily": Freq.D,
        "W": Freq.W, "w": Freq.W, "weekly": Freq.W,
    }
    if freq_str in aliases:
        return aliases[freq_str]
    raise ValueError(f"未知周期: {freq_str}, 支持: {list(FREQ_MAP.keys())}")


# ============================================================
# Part 1: 状态定义
# ============================================================

class Trend(Enum):
    UP = "up"
    WEAK_UP = "weak_up"
    SIDE = "side"
    WEAK_DOWN = "weak_down"
    DOWN = "down"

    @property
    def direction(self):
        if self in (Trend.UP, Trend.WEAK_UP): return 1
        if self in (Trend.DOWN, Trend.WEAK_DOWN): return -1
        return 0


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
class TradeSignal:
    """最终交易信号"""
    action: str              # BUY_CONFIRMED / SELL_CONFIRMED / BUY / SELL / WAIT
    direction: int           # 1=多, -1=空, 0=观望
    trend_state: Trend       # 子周期三段判定
    trend_score: float
    trend_changed: bool      # 趋势是否刚变化
    chan_signal: Optional[ChanSignal]  # 缠论买卖点（如有）
    entry_price: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    position_pct: int        # 仓位百分比
    reason: str
    base_freq: str = ""      # 当前周期
    timestamp: datetime = field(default_factory=datetime.now)


# ============================================================
# Part 2: K线合并 + 三段判定
# ============================================================

def merge(highs, lows):
    """缠论K线合并"""
    if len(highs) == 0:
        return [], []
    m_h, m_l = [float(highs[0])], [float(lows[0])]
    direction = 0
    for i in range(1, len(highs)):
        h, l = float(highs[i]), float(lows[i])
        ph, pl = m_h[-1], m_l[-1]
        if (ph >= h and pl <= l) or (h >= ph and l <= pl):
            if direction >= 0:
                m_h[-1] = max(ph, h)
                m_l[-1] = max(pl, l)
            else:
                m_h[-1] = min(ph, h)
                m_l[-1] = min(pl, l)
        else:
            if h > ph and l > pl: direction = 1
            elif h < ph and l < pl: direction = -1
            m_h.append(h)
            m_l.append(l)
    return m_h, m_l


def judge(highs, lows) -> Tuple[Trend, float]:
    """三根合并K线判定趋势"""
    if len(highs) < 3:
        return Trend.SIDE, 0.0
    h1, h2, h3 = highs[-3], highs[-2], highs[-1]
    l1, l2, l3 = lows[-3], lows[-2], lows[-1]
    up = sum([l2 > l1, l3 > l2, h2 > h1, h3 > h2])
    dn = sum([l2 < l1, l3 < l2, h2 < h1, h3 < h2])
    if up == 4: return Trend.UP, 1.0
    if up == 3: return Trend.WEAK_UP, 0.75
    if dn == 4: return Trend.DOWN, 1.0
    if dn == 3: return Trend.WEAK_DOWN, 0.75
    return Trend.SIDE, max(up, dn) / 4


class TrendDetector:
    """N根子周期K线判断当前周期趋势

    sub_ratio: 子周期与当前周期的比值
        4H用1H → sub_ratio=4
        1D用4H → sub_ratio=6
        1H用15m → sub_ratio=4
    window = sub_ratio * 2 根子周期K线用于判断
    """

    def __init__(self, sub_ratio: int = 4):
        self.sub_ratio = sub_ratio
        self.window = sub_ratio * 2
        self.prev_trend = Trend.SIDE

    def update(self, df_sub: pd.DataFrame) -> Tuple[Trend, float, bool]:
        data = df_sub.tail(self.window)
        if len(data) < self.window:
            return Trend.SIDE, 0.0, False
        m_h, m_l = merge(data['high'].values, data['low'].values)
        trend, score = judge(m_h, m_l)
        changed = (trend.direction != self.prev_trend.direction)
        self.prev_trend = trend
        return trend, score, changed


# ============================================================
# Part 3: 缠论核心
# ============================================================

def find_zhongshu(bi_list) -> List[dict]:
    if len(bi_list) < 3:
        return []
    result = []
    i = 0
    while i <= len(bi_list) - 3:
        try:
            zs = ZS(bis=bi_list[i:i+3])
        except:
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
    """计算一笔的力度 = 价格幅度 × 时间效率"""
    amplitude = abs(bi.high - bi.low)
    if hasattr(bi, 'raw_bars') and bi.raw_bars:
        n_bars = max(len(bi.raw_bars), 1)
        efficiency = amplitude / n_bars
        return amplitude * (1 + efficiency / max(amplitude, 0.001))
    return amplitude


def _check_divergence(bi_a, bi_b, direction: str = "down") -> Tuple[bool, float]:
    """检测两笔间背驰  ratio < 0.8 = 力度衰减 = 背驰"""
    s_a = _bi_strength(bi_a)
    s_b = _bi_strength(bi_b)
    if s_a <= 0:
        return False, 0.0
    ratio = s_b / s_a
    if direction == "down":
        is_div = ratio < 0.8 and bi_b.low <= bi_a.low * 1.02
        strength = min(1.0, max(0, (1.0 - ratio) / 0.5))
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
    """检测全部买卖点: 一买/一卖 + 二买/二卖 + 三买/三卖"""
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
                is_div, div_strength = _check_divergence(bi_a, bi_b, "down")
                if is_div and div_strength >= 0.2:
                    signals.append(ChanSignal(
                        type=BSPoint.BUY_1, price=bi_b.low,
                        zs_zg=last_zs['zg'], zs_zd=last_zs['zd'],
                        strength=min(div_strength * 1.2, 1.0),
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
                is_div, div_strength = _check_divergence(bi_a, bi_b, "up")
                if is_div and div_strength >= 0.2:
                    signals.append(ChanSignal(
                        type=BSPoint.SELL_1, price=bi_b.high,
                        zs_zg=last_zs['zg'], zs_zd=last_zs['zd'],
                        strength=min(div_strength * 1.2, 1.0),
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
# Part 4: 缠论外挂 (周期无关)
# ============================================================

class ChanPlugin:
    """缠论外挂 — 在指定周期上做笔/中枢/买卖点"""

    def __init__(self, symbol: str = "DEFAULT", freq: str = "4H"):
        self.symbol = symbol
        self.freq = freq
        self.czsc_freq = to_czsc_freq(freq)
        self.czsc = None
        self.signals: List[ChanSignal] = []
        self.zhongshu_list: List[dict] = []

    def update(self, df: pd.DataFrame):
        """传入当前周期的OHLCV数据，重新计算"""
        bars = []
        dt_col = 'dt' if 'dt' in df.columns else 'datetime'
        for _, row in df.iterrows():
            dt = row[dt_col] if dt_col in df.columns else datetime.now()
            if isinstance(dt, str): dt = pd.to_datetime(dt)
            bars.append(RawBar(
                symbol=self.symbol, dt=dt, freq=self.czsc_freq,
                open=float(row['open']), close=float(row['close']),
                high=float(row['high']), low=float(row['low']),
                vol=float(row.get('vol', row.get('volume', 0))),
                amount=float(row.get('amount', 0)),
            ))
        self.czsc = CZSC(bars)
        self._refresh()

    def update_bar(self, bar: dict):
        """增量更新一根K线"""
        raw = RawBar(
            symbol=self.symbol, dt=bar['dt'], freq=self.czsc_freq,
            open=bar['open'], close=bar['close'],
            high=bar['high'], low=bar['low'],
            vol=bar.get('vol', 0), amount=bar.get('amount', 0),
        )
        if self.czsc is None:
            self.czsc = CZSC([raw])
        else:
            self.czsc.update(raw)
        self._refresh()

    def get_buy_signals(self, min_strength=0.3) -> List[ChanSignal]:
        return [s for s in self.signals
                if s.type in (BSPoint.BUY_1, BSPoint.BUY_2, BSPoint.BUY_3)
                and s.strength >= min_strength]

    def get_sell_signals(self, min_strength=0.3) -> List[ChanSignal]:
        return [s for s in self.signals
                if s.type in (BSPoint.SELL_1, BSPoint.SELL_2, BSPoint.SELL_3)
                and s.strength >= min_strength]

    def _refresh(self):
        if self.czsc and len(self.czsc.bi_list) >= 3:
            self.zhongshu_list = find_zhongshu(self.czsc.bi_list)
            self.signals = detect_chan_signals(self.czsc.bi_list, self.zhongshu_list)
        else:
            self.zhongshu_list = []
            self.signals = []


# ============================================================
# Part 5: 扫描引擎 (周期无关)
# ============================================================

class Scanner:
    """
    扫描引擎 — 周期自适应

    用法:
        # 4H周期, 用1H做子周期 (sub_ratio=4)
        scanner = Scanner(symbol='SPY', base_freq='4H', sub_ratio=4)

        # 日线周期, 用4H做子周期 (sub_ratio=6)
        scanner = Scanner(symbol='SPY', base_freq='1D', sub_ratio=6)

        # 1H周期, 用15m做子周期 (sub_ratio=4)
        scanner = Scanner(symbol='SPY', base_freq='1H', sub_ratio=4)
    """

    def __init__(self, symbol: str = "DEFAULT",
                 base_freq: str = "4H", sub_ratio: int = 4):
        self.symbol = symbol
        self.base_freq = base_freq
        self.sub_ratio = sub_ratio
        self.trend_detector = TrendDetector(sub_ratio=sub_ratio)
        self.chan_plugin = ChanPlugin(symbol=symbol, freq=base_freq)

        self.trend = Trend.SIDE
        self.trend_score = 0.0
        self.trend_changed = False
        self.signal_history: List[dict] = []

    def on_sub_close(self, df_sub: pd.DataFrame):
        """每根子周期收线 — 更新趋势"""
        self.trend, self.trend_score, self.trend_changed = \
            self.trend_detector.update(df_sub)

    def on_base_close(self, df_base: pd.DataFrame):
        """每根当前周期收线 — 更新缠论"""
        self.chan_plugin.update(df_base)

    def on_bar(self, df_sub: pd.DataFrame, df_base: pd.DataFrame,
               is_base_close: bool = False) -> TradeSignal:
        """一站式调用 — 每根子周期收线时调用"""
        self.on_sub_close(df_sub)
        if is_base_close:
            self.on_base_close(df_base)

        signal = self.scan()

        self.signal_history.append({
            'timestamp': signal.timestamp,
            'action': signal.action,
            'trend': signal.trend_state.value,
            'chan': signal.chan_signal.type.value if signal.chan_signal else None,
            'position': signal.position_pct,
            'freq': self.base_freq,
        })
        return signal

    def scan(self) -> TradeSignal:
        """
        扫描信号 — 纯结构驱动

        一买/一卖: 纯背驰, 不依赖任何外部方向
        二买/三买/二卖/三卖: 结合趋势状态
        """
        td = self.trend.direction

        # === 一买/一卖: 纯缠论结构 ===
        bs1_signals = [s for s in self.chan_plugin.signals
                       if s.type in (BSPoint.BUY_1, BSPoint.SELL_1)
                       and s.strength >= 0.3]

        if bs1_signals:
            best = max(bs1_signals, key=lambda s: s.strength)
            is_buy = best.type == BSPoint.BUY_1

            if best.strength >= 0.7:
                action = "BUY_CONFIRMED" if is_buy else "SELL_CONFIRMED"
                position = 80
            elif best.strength >= 0.5:
                action = "BUY_CONFIRMED" if is_buy else "SELL_CONFIRMED"
                position = 60
            else:
                action = "BUY" if is_buy else "SELL"
                position = 40

            reason = f"缠论{best.type.value}: {best.reason}"
            return self._make_signal(action, 1 if is_buy else -1,
                                     best, position, reason)

        # === 二买/三买/二卖/三卖: 结合趋势 ===
        if td == 0:
            buys = [s for s in self.chan_plugin.get_buy_signals()
                    if s.type != BSPoint.BUY_1]
            sells = [s for s in self.chan_plugin.get_sell_signals()
                     if s.type != BSPoint.SELL_1]
            best_buy = max(buys, key=lambda s: s.strength) if buys else None
            best_sell = max(sells, key=lambda s: s.strength) if sells else None

            if best_buy and (not best_sell or best_buy.strength > best_sell.strength):
                reason = f"震荡+缠论{best_buy.type.value}: {best_buy.reason}"
                return self._make_signal("BUY", 1, best_buy, 50, reason)
            elif best_sell:
                reason = f"震荡+缠论{best_sell.type.value}: {best_sell.reason}"
                return self._make_signal("SELL", -1, best_sell, 50, reason)

            return self._make_signal("WAIT", 0, None, 0, "震荡+无缠论信号")

        # 有趋势方向
        base_action = "BUY" if td == 1 else "SELL"
        base_position = 100 if self.trend in (Trend.UP, Trend.DOWN) else 70

        chan_sig = None
        if td == 1:
            buys = [s for s in self.chan_plugin.get_buy_signals()
                    if s.type != BSPoint.BUY_1]
            if buys:
                chan_sig = max(buys, key=lambda s: s.strength)
        elif td == -1:
            sells = [s for s in self.chan_plugin.get_sell_signals()
                     if s.type != BSPoint.SELL_1]
            if sells:
                chan_sig = max(sells, key=lambda s: s.strength)

        if chan_sig:
            action = f"{base_action}_CONFIRMED"
            reason = f"{self.trend.value} + 缠论{chan_sig.type.value}: {chan_sig.reason}"
            return self._make_signal(action, td, chan_sig, base_position, reason)
        else:
            reason = f"{self.trend.value} → 等缠论买卖点"
            return self._make_signal(base_action, td, None, base_position, reason)

    def _make_signal(self, action, direction, chan_sig,
                     position, reason) -> TradeSignal:
        if self.trend_changed:
            reason = (f"⚡趋势变化({self.trend_detector.prev_trend.value}"
                      f"→{self.trend.value}) | {reason}")
        return TradeSignal(
            action=action,
            direction=direction,
            trend_state=self.trend,
            trend_score=self.trend_score,
            trend_changed=self.trend_changed,
            chan_signal=chan_sig,
            entry_price=chan_sig.price if chan_sig else None,
            stop_loss=chan_sig.stop_loss if chan_sig else None,
            target=chan_sig.target if chan_sig else None,
            position_pct=position,
            reason=reason,
            base_freq=self.base_freq,
        )


# ============================================================
# Part 6: 格式化输出
# ============================================================

def fmt(sig: TradeSignal) -> str:
    emoji = {
        'BUY_CONFIRMED': '✅🟢', 'SELL_CONFIRMED': '✅🔴',
        'BUY': '🟢', 'SELL': '🔴',
        'WAIT': '🟡', 'NO_TRADE': '⛔',
    }
    e = emoji.get(sig.action, '?')
    lines = [
        f"{'='*50}",
        f"  {e} {sig.action}  |  仓位 {sig.position_pct}%  |  周期 {sig.base_freq}",
        f"{'='*50}",
        f"  趋势:    {sig.trend_state.value} (score={sig.trend_score:.2f})"
        f"{'  ⚡变化!' if sig.trend_changed else ''}",
    ]
    if sig.chan_signal:
        cs = sig.chan_signal
        lines.append(f"  缠论:    {cs.type.value} (强度={cs.strength:.0%})")
        lines.append(f"  入场:    {cs.price:.2f}")
        lines.append(f"  止损:    {cs.stop_loss:.2f}")
        lines.append(f"  目标:    {cs.target:.2f}")
        lines.append(f"  中枢:    [{cs.zs_zd:.2f} ~ {cs.zs_zg:.2f}]")
    else:
        lines.append(f"  缠论:    暂无买卖点")
    lines.append(f"  说明:    {sig.reason}")
    lines.append(f"{'='*50}")
    return "\n".join(lines)


# ============================================================
# Part 7: 测试
# ============================================================

def run_test():
    print("=" * 50)
    print("  缠论交易系统 v2.0 — 周期自适应测试")
    print("=" * 50)

    np.random.seed(42)
    price = 500.0
    data_sub = []
    dt = datetime(2024, 1, 2, 9, 0)

    for drift, vol, n in [
        (0.8, 2.0, 40),
        (0.0, 3.0, 30),
        (-0.9, 2.0, 35),
        (0.0, 2.5, 20),
        (0.7, 1.8, 35),
    ]:
        for _ in range(n):
            o = price
            c = o + drift + np.random.randn() * vol
            h = max(o, c) + abs(np.random.randn()) * vol * 0.3
            l = min(o, c) - abs(np.random.randn()) * vol * 0.3
            data_sub.append({
                'dt': dt, 'open': o, 'high': h,
                'low': l, 'close': c, 'vol': 10000
            })
            price = c
            dt += timedelta(minutes=15)

    df_sub = pd.DataFrame(data_sub)

    sub_ratio = 4
    rows_base = []
    for i in range(0, len(df_sub) - (sub_ratio - 1), sub_ratio):
        chunk = df_sub.iloc[i:i+sub_ratio]
        rows_base.append({
            'dt': chunk.iloc[0]['dt'],
            'open': chunk.iloc[0]['open'],
            'high': chunk['high'].max(),
            'low': chunk['low'].min(),
            'close': chunk.iloc[-1]['close'],
            'vol': chunk['vol'].sum(),
        })
    df_base = pd.DataFrame(rows_base)

    base_freq = "1H"
    print(f"\n  当前周期: {base_freq}")
    print(f"  子周期比: {sub_ratio}")
    print(f"  子周期数据: {len(df_sub)} 根")
    print(f"  当前周期数据: {len(df_base)} 根")

    scanner = Scanner(symbol='SPY', base_freq=base_freq, sub_ratio=sub_ratio)

    print(f"\n  开始扫描...\n")
    signals_log = []
    prev_action = None
    window = sub_ratio * 2

    for i in range(window, len(df_sub)):
        is_base = (i % sub_ratio == sub_ratio - 1)
        n_base = (i + 1) // sub_ratio
        curr_base = df_base.iloc[:n_base] if n_base > 0 else df_base.iloc[:1]

        signal = scanner.on_bar(
            df_sub=df_sub.iloc[:i+1],
            df_base=curr_base,
            is_base_close=is_base,
        )
        signals_log.append(signal)

        should_print = (
            signal.trend_changed or
            'CONFIRMED' in signal.action or
            signal.action != prev_action
        )
        if should_print:
            e = {'BUY_CONFIRMED': '✅🟢', 'SELL_CONFIRMED': '✅🔴',
                 'BUY': '🟢', 'SELL': '🔴', 'WAIT': '🟡', 'NO_TRADE': '⛔'}
            chan_str = f"缠论:{signal.chan_signal.type.value}" if signal.chan_signal else ""
            print(f"  Bar {i:>3} | {e.get(signal.action, '?')} "
                  f"{signal.action:>16} | {signal.trend_state.value:>8} | "
                  f"{chan_str}")
        prev_action = signal.action

    print(f"\n{'='*50}")
    print(f"  统计 ({base_freq})")
    print(f"{'='*50}")

    actions = {}
    for s in signals_log:
        actions[s.action] = actions.get(s.action, 0) + 1
    total = len(signals_log)
    print(f"\n  总扫描次数: {total}")
    for a, c in sorted(actions.items(), key=lambda x: -x[1]):
        print(f"    {a:>18}: {c:>4} ({c/total:.1%})")

    confirmed = sum(1 for s in signals_log if 'CONFIRMED' in s.action)
    print(f"\n  缠论确认信号: {confirmed} 次")
    print(f"  趋势变化次数: {sum(1 for s in signals_log if s.trend_changed)}")
    print(f"\n  最新信号:")
    print(fmt(signals_log[-1]))

    print(f"""
{'='*50}
  接入你的系统
{'='*50}

  from chan_trading_system import Scanner, fmt

  # === 4H周期, 1H子周期 ===
  scanner = Scanner(symbol='SPY', base_freq='4H', sub_ratio=4)

  # === 日线, 4H子周期 ===
  scanner = Scanner(symbol='SPY', base_freq='1D', sub_ratio=6)

  # === 1H, 15m子周期 ===
  scanner = Scanner(symbol='SPY', base_freq='1H', sub_ratio=4)

  signal = scanner.on_bar(
      df_sub=df_sub,
      df_base=df_base,
      is_base_close=False,
  )

  if signal.action == 'BUY_CONFIRMED':
      buy(price=signal.entry_price,
          stop=signal.stop_loss,
          target=signal.target,
          size=signal.position_pct)
{'='*50}""")


if __name__ == "__main__":
    run_test()
