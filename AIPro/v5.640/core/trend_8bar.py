"""
当前周期趋势判定算法 (云端版)
================================
Synced from v3.640 main program

核心逻辑:
  当前周期 = 4H (可配置)
  子周期 = 1H (当前周期/4)

  每个当前周期K线 = 4根子周期K线
  前两根已完成的当前周期K线 = 8根子周期K线

  这8根子周期K线合并后做三段判定:
  → 底底高+顶顶高 = 趋势延续/上涨
  → 底底低+顶顶低 = 趋势反转/下跌
  → 否则 = 震荡

  不需要等第三根当前周期K线收线就能判断趋势是否改变

作者: D's Trading System
日期: 2025-02-07
版本: v5.640 Cloud
"""

import numpy as np
from typing import Tuple, List, Dict
from enum import Enum
from dataclasses import dataclass


# ============================================================
# 状态定义
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


@dataclass
class State:
    trend: Trend            # 当前趋势判定
    score: float            # 趋势分数 0-1
    prev_trend: Trend       # 上一次判定
    changed: bool           # 趋势是否刚发生变化
    merged_count: int       # 合并后K线数量 (从8根子K线合并)
    detail: Dict            # 判定细节


# ============================================================
# K线合并 (包含关系处理)
# ============================================================

def merge(highs, lows):
    """
    缠论K线合并 — 极简版

    只处理高低点，不需要开收盘价
    输入: 高点数组, 低点数组
    输出: 合并后的高点数组, 低点数组
    """
    if len(highs) == 0:
        return [], []

    m_h = [float(highs[0])]
    m_l = [float(lows[0])]
    direction = 0

    for i in range(1, len(highs)):
        h, l = float(highs[i]), float(lows[i])
        ph, pl = m_h[-1], m_l[-1]

        # 包含关系: 一根被另一根完全覆盖
        if (ph >= h and pl <= l) or (h >= ph and l <= pl):
            if direction >= 0:  # 上升合并: 取高
                m_h[-1] = max(ph, h)
                m_l[-1] = max(pl, l)
            else:               # 下降合并: 取低
                m_h[-1] = min(ph, h)
                m_l[-1] = min(pl, l)
        else:
            # 不包含, 更新方向
            if h > ph and l > pl:
                direction = 1
            elif h < ph and l < pl:
                direction = -1
            m_h.append(h)
            m_l.append(l)

    return m_h, m_l


# ============================================================
# 三段判定
# ============================================================

def judge(highs, lows) -> Tuple[Trend, float, Dict]:
    """
    三根合并K线判定趋势

    4个条件:
      底2>底1  底3>底2  顶2>顶1  顶3>顶2
      4/4 → 强趋势
      3/4 → 弱趋势
      其余 → 震荡
    """
    if len(highs) < 3:
        return Trend.SIDE, 0.0, {'reason': 'not_enough_bars'}

    h1, h2, h3 = highs[-3], highs[-2], highs[-1]
    l1, l2, l3 = lows[-3], lows[-2], lows[-1]

    up = [l2 > l1, l3 > l2, h2 > h1, h3 > h2]
    dn = [l2 < l1, l3 < l2, h2 < h1, h3 < h2]
    up_n = sum(up)
    dn_n = sum(dn)

    detail = {
        'highs': [h1, h2, h3],
        'lows': [l1, l2, l3],
        'up_conditions': up,
        'down_conditions': dn,
    }

    if up_n == 4: return Trend.UP, 1.0, detail
    if up_n == 3: return Trend.WEAK_UP, 0.75, detail
    if dn_n == 4: return Trend.DOWN, 1.0, detail
    if dn_n == 3: return Trend.WEAK_DOWN, 0.75, detail
    return Trend.SIDE, max(up_n, dn_n) / 4, detail


# ============================================================
# 核心: 用子周期K线判断当前周期趋势
# ============================================================

class TrendDetector:
    """
    当前周期趋势检测器 (云端简化版)

    用法:
        detector = TrendDetector(sub_ratio=4)

        # 每次数据更新时调用
        state = detector.update(highs, lows)

        if state.changed:
            print(f"趋势变化! {state.prev_trend} → {state.trend}")

    原理:
        当前周期每根K线 = sub_ratio 根子周期K线
        取前两根已完成的当前周期K线 = 2 * sub_ratio 根子周期K线
        这些子周期K线合并后做三段判定
        → 判断当前周期的趋势是否改变
    """

    def __init__(self, sub_ratio: int = 4):
        """
        参数:
            sub_ratio: 当前周期/子周期比例
                       4H/1H = 4
                       1H/15min = 4
                       D/4H = 6
        """
        self.sub_ratio = sub_ratio
        self.window = sub_ratio * 2  # 8根子K线 = 前两根当前周期K线
        self.prev_trend = Trend.SIDE
        self.trend_count = 0         # 当前趋势持续次数

    def update(self, highs: List[float], lows: List[float]) -> State:
        """
        更新趋势判定 (云端版: 直接传高低点数组)

        参数:
            highs: 子周期高点数组 (至少需要 window 根)
            lows: 子周期低点数组

        返回:
            State: 当前状态，包含趋势判定和是否发生变化
        """
        # 取最后 window 根
        h_data = highs[-self.window:] if len(highs) >= self.window else highs
        l_data = lows[-self.window:] if len(lows) >= self.window else lows

        if len(h_data) < self.window:
            return State(
                trend=Trend.SIDE,
                score=0.0,
                prev_trend=self.prev_trend,
                changed=False,
                merged_count=0,
                detail={'reason': f'need {self.window} bars, got {len(h_data)}'},
            )

        # 合并
        m_h, m_l = merge(h_data, l_data)

        # 三段判定
        trend, score, detail = judge(m_h, m_l)

        # 变化检测
        changed = (trend.direction != self.prev_trend.direction)

        # 如果方向真的变了（不是side内部波动）
        if changed and trend.direction != 0:
            self.trend_count = 1
        elif trend.direction == self.prev_trend.direction and trend.direction != 0:
            self.trend_count += 1
        else:
            self.trend_count = 0

        state = State(
            trend=trend,
            score=score,
            prev_trend=self.prev_trend,
            changed=changed,
            merged_count=len(m_h),
            detail=detail,
        )

        self.prev_trend = trend
        return state


# ============================================================
# 与x4拟合结合的交易决策
# ============================================================

def decide(state: State, x4_direction: int) -> Dict:
    """
    最终交易决策

    参数:
        state: TrendDetector.update() 的输出
        x4_direction: x4拟合大方向 (1=涨, -1=跌, 0=平)

    返回:
        决策字典
    """
    td = state.trend.direction

    # 一致
    if x4_direction != 0 and td == x4_direction:
        if state.trend in (Trend.UP, Trend.DOWN):
            action = "BUY" if td == 1 else "SELL"
            position = 100
            reason = f"x4{'涨' if td==1 else '跌'} + 强{state.trend.value} → 满仓"
        else:
            action = "BUY" if td == 1 else "SELL"
            position = 70
            reason = f"x4{'涨' if td==1 else '跌'} + 弱{state.trend.value} → 7成仓"

    # x4有方向但当前震荡
    elif x4_direction != 0 and td == 0:
        action = "WAIT"
        position = 0
        reason = f"x4{'涨' if x4_direction==1 else '跌'} + 震荡 → 等确认"

    # 矛盾
    elif x4_direction != 0 and td == -x4_direction:
        action = "NO_TRADE"
        position = 0
        reason = f"x4{'涨' if x4_direction==1 else '跌'} + {state.trend.value} → 矛盾不做"

    # x4无方向
    else:
        action = "WAIT"
        position = 0
        reason = "x4无方向 → 等待"

    # 趋势刚变化时加警告
    if state.changed:
        reason = f"⚡趋势变化({state.prev_trend.value}→{state.trend.value}) | " + reason

    return {
        'action': action,
        'position': position,
        'reason': reason,
        'trend': state.trend.value,
        'score': state.score,
        'changed': state.changed,
        'x4': x4_direction,
    }


# ============================================================
# 格式化输出
# ============================================================

def fmt(decision: Dict) -> str:
    emoji = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡", "NO_TRADE": "⛔"}
    return (
        f"{emoji.get(decision['action'], '?')} {decision['action']} "
        f"{decision['position']}% | "
        f"{decision['trend']} (score={decision['score']:.2f}) | "
        f"{decision['reason']}"
    )
