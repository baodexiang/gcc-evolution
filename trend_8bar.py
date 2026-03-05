"""
当前周期趋势判定算法
================================

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
"""

import pandas as pd
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
# 核心: 用8根子周期K线判断当前周期趋势
# ============================================================

class TrendDetector:
    """
    当前周期趋势检测器

    用法:
        detector = TrendDetector(sub_ratio=4)

        # 每根子周期K线更新时调用
        state = detector.update(df_sub)

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

    def update(self, df_sub: pd.DataFrame) -> State:
        """
        每根子周期K线到来时调用

        参数:
            df_sub: 子周期K线数据 (至少需要 window 根)

        返回:
            State: 当前状态，包含趋势判定和是否发生变化
        """
        data = df_sub.tail(self.window)

        if len(data) < self.window:
            return State(
                trend=Trend.SIDE,
                score=0.0,
                prev_trend=self.prev_trend,
                changed=False,
                merged_count=0,
                detail={'reason': f'need {self.window} bars, got {len(data)}'},
            )

        # 合并
        m_h, m_l = merge(data['high'].values, data['low'].values)

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


# ============================================================
# 测试
# ============================================================

def run_test():
    np.random.seed(42)

    # 生成1H数据 (子周期)
    # 模拟: 上涨 → 转震荡 → 转下跌 → 再转上涨
    price = 100.0
    data = []
    phases = [
        ('up',   40, 0.3, 0.5),
        ('side', 20, 0.0, 0.8),
        ('down', 30, -0.35, 0.5),
        ('side', 15, 0.0, 0.6),
        ('up',   35, 0.3, 0.4),
    ]

    true_labels = []
    for phase, length, drift, vol in phases:
        for _ in range(length):
            o = price
            c = o + drift + np.random.randn() * vol
            h = max(o, c) + abs(np.random.randn()) * vol * 0.3
            l = min(o, c) - abs(np.random.randn()) * vol * 0.3
            data.append({'open': o, 'high': h, 'low': l, 'close': c})
            true_labels.append(phase)
            price = c

    df_1h = pd.DataFrame(data)

    print("=" * 60)
    print("  当前周期趋势判定 — 8根子K线算法测试")
    print("=" * 60)
    print(f"\n  当前周期: 4H")
    print(f"  子周期: 1H")
    print(f"  子K线数据: {len(df_1h)} 根")
    print(f"  判定窗口: 8根1H (= 前两根4H)")

    # 初始化检测器
    detector = TrendDetector(sub_ratio=4)

    # 逐根1H更新
    results = []
    for i in range(8, len(df_1h)):
        state = detector.update(df_1h.iloc[:i+1])
        x4_dir = 1 if i < 60 else (-1 if i < 100 else 1)  # 模拟x4方向
        decision = decide(state, x4_dir)

        results.append({
            'bar': i,
            'true': true_labels[i],
            'trend': state.trend.value,
            'score': state.score,
            'changed': state.changed,
            'action': decision['action'],
            'position': decision['position'],
            'merged': state.merged_count,
        })

        # 只打印趋势变化的时刻
        if state.changed:
            print(f"\n  Bar {i:>3} | {fmt(decision)}")

    results_df = pd.DataFrame(results)

    # 统计
    print(f"\n{'='*60}")
    print(f"  统计分析")
    print(f"{'='*60}")

    # 趋势变化次数
    changes = results_df[results_df['changed']].copy()
    print(f"\n  趋势变化次数: {len(changes)}")

    if len(changes) > 0:
        # 变化间隔
        intervals = changes['bar'].diff().dropna()
        print(f"  变化间隔: 平均 {intervals.mean():.1f} 根1H, "
              f"最短 {intervals.min():.0f}, 最长 {intervals.max():.0f}")
        print(f"  对应4H:   平均 {intervals.mean()/4:.1f} 根, "
              f"最短 {intervals.min()/4:.1f}, 最长 {intervals.max()/4:.1f}")

    # 各趋势占比
    print(f"\n  判定状态分布:")
    for trend, count in results_df['trend'].value_counts().items():
        pct = count / len(results_df) * 100
        print(f"    {trend:>10}: {count:>4} ({pct:.1f}%)")

    # 与真实标签对比
    print(f"\n  判定准确率:")
    direction_map = {'up': 1, 'weak_up': 1, 'down': -1, 'weak_down': -1, 'side': 0}
    true_map = {'up': 1, 'down': -1, 'side': 0}

    correct = 0
    total = 0
    for _, row in results_df.iterrows():
        pred_dir = direction_map.get(row['trend'], 0)
        true_dir = true_map.get(row['true'], 0)
        if pred_dir == true_dir:
            correct += 1
        total += 1

    print(f"    方向准确率: {correct}/{total} = {correct/total:.1%}")

    # 交易决策统计
    print(f"\n  交易决策分布:")
    for action, count in results_df['action'].value_counts().items():
        pct = count / len(results_df) * 100
        print(f"    {action:>10}: {count:>4} ({pct:.1f}%)")

    # 关键: 趋势变化的反应速度
    print(f"\n{'='*60}")
    print(f"  关键指标: 趋势变化反应速度")
    print(f"{'='*60}")

    # 找到真实标签切换点
    true_changes = []
    for i in range(1, len(true_labels)):
        if true_labels[i] != true_labels[i-1]:
            true_changes.append({'bar': i, 'from': true_labels[i-1], 'to': true_labels[i]})

    # 找到算法检测到变化的时间
    detected_changes = changes[['bar', 'trend']].to_dict('records')

    print(f"\n  真实切换 vs 算法检测:")
    for tc in true_changes:
        # 找最近的算法检测
        nearest = None
        for dc in detected_changes:
            if dc['bar'] >= tc['bar']:
                nearest = dc
                break

        if nearest:
            delay = nearest['bar'] - tc['bar']
            print(f"    真实: Bar {tc['bar']:>3} ({tc['from']}→{tc['to']}) | "
                  f"检测: Bar {nearest['bar']:>3} ({nearest['trend']}) | "
                  f"延迟: {delay}根1H = {delay/4:.1f}根4H")
        else:
            print(f"    真实: Bar {tc['bar']:>3} ({tc['from']}→{tc['to']}) | "
                  f"未检测到")

    print(f"""
{'='*60}
  结论
{'='*60}

  8根子周期K线(前两根当前周期) 合并后做三段判定:
  - 可以提前判断当前周期的趋势是否改变
  - 不需要等当前K线收线
  - 反应速度比等当前周期收线快 1-2 根当前周期K线

  配合x4拟合:
  - x4给大方向
  - 8根子K线给当前状态确认
  - 两层够了，不需要递归
{'='*60}""")

    return results_df


if __name__ == "__main__":
    results = run_test()
