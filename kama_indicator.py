# ========================================================================
# KAMA Indicator Module v1.0
# ========================================================================
#
# 版本: 1.0
# 日期: 2026-01-31
#
# Kaufman自适应移动平均线 (KAMA) - 效率比(ER)计算
#
# 核心原理:
#   - 效率比 ER = 方向变化 / 总波动
#   - ER → 1: 趋势明显（价格朝一个方向走）
#   - ER → 0: 震荡市场（价格来回波动）
#
# 用途:
#   - 剥头皮外挂 (chandelier_zlsma_plugin.py) 的微观震荡过滤
#   - Rob Hoffman外挂 (rob_hoffman_plugin.py) 的纠缠检测
#
# ========================================================================

import numpy as np
from typing import Union


def calculate_efficiency_ratio(closes: Union[np.ndarray, list], period: int = 10) -> float:
    """
    计算效率比 ER (Efficiency Ratio)

    KAMA的核心指标，用于判断市场是趋势还是震荡。

    公式:
        ER = abs(close - close[n]) / sum(abs(close[i] - close[i-1]))

    解释:
        - 分子：N周期的净价格变化（方向性移动）
        - 分母：N周期内每根K线变化的绝对值之和（总波动）
        - 如果价格持续朝一个方向走，ER接近1
        - 如果价格来回震荡，ER接近0

    Args:
        closes: 收盘价序列 (numpy数组或列表)
        period: 计算周期 (默认10，KAMA标准参数)

    Returns:
        ER值 (0-1): 越接近1越是趋势，越接近0越是震荡

    Examples:
        >>> # 持续上涨 → ER接近1
        >>> trend = np.cumsum(np.ones(20))
        >>> calculate_efficiency_ratio(trend, 10)
        1.0

        >>> # 来回震荡 → ER接近0
        >>> ranging = np.array([100, 101, 99, 100, 102, 98, 100, 101, 99, 100, 100])
        >>> calculate_efficiency_ratio(ranging, 10)
        0.0
    """
    if isinstance(closes, list):
        closes = np.array(closes, dtype=float)

    n = len(closes)
    if n < period + 1:
        return 0.5  # 数据不足，返回中性值

    # 方向变化 = 最新价 - N周期前价
    # 注意: closes[-1] 是最新价, closes[-(period+1)] 是N+1根前的价格
    direction = abs(closes[-1] - closes[-(period + 1)])

    # 总波动 = 最近N+1根K线的逐根变化绝对值之和
    # np.diff 计算相邻元素差值，然后取绝对值求和
    recent_closes = closes[-(period + 1):]
    volatility = np.sum(np.abs(np.diff(recent_closes)))

    if volatility == 0:
        return 0.5  # 避免除零，返回中性值

    # ER = 方向变化 / 总波动，限制在[0, 1]范围内
    er = direction / volatility
    return min(er, 1.0)


def calculate_kama(closes: Union[np.ndarray, list], period: int = 10,
                   fast: int = 2, slow: int = 30) -> np.ndarray:
    """
    计算完整KAMA序列

    KAMA公式:
        SC = (ER × (fast_sc - slow_sc) + slow_sc)²
        KAMA = KAMA[i-1] + SC × (close - KAMA[i-1])

    其中:
        - fast_sc = 2/(fast+1), 默认 2/3 ≈ 0.667
        - slow_sc = 2/(slow+1), 默认 2/31 ≈ 0.0645

    特性:
        - 趋势明显时(ER→1): SC接近fast_sc²，KAMA快速跟随
        - 震荡市场时(ER→0): SC接近slow_sc²，KAMA几乎不动

    Args:
        closes: 收盘价序列
        period: ER计算周期 (默认10)
        fast: 快速EMA周期 (默认2)
        slow: 慢速EMA周期 (默认30)

    Returns:
        KAMA序列 (numpy数组)

    Note:
        对于震荡过滤用途，通常只需要 calculate_efficiency_ratio()，
        不需要计算完整KAMA序列。
    """
    if isinstance(closes, list):
        closes = np.array(closes, dtype=float)

    n = len(closes)
    kama = np.zeros(n)

    if n <= period:
        return kama

    # 初始值
    kama[period] = closes[period]

    # 平滑系数
    fast_sc = 2 / (fast + 1)
    slow_sc = 2 / (slow + 1)

    for i in range(period + 1, n):
        # 计算当前位置的ER
        er = calculate_efficiency_ratio(closes[:i + 1], period)

        # 计算平滑系数 SC
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

        # 计算KAMA
        kama[i] = kama[i - 1] + sc * (closes[i] - kama[i - 1])

    return kama


def get_kama_direction(kama: np.ndarray, lookback: int = 3) -> str:
    """
    判断KAMA方向

    Args:
        kama: KAMA序列
        lookback: 回看周期 (默认3)

    Returns:
        "UP" / "DOWN" / "SIDE"
    """
    if len(kama) < lookback + 1:
        return "SIDE"

    recent = kama[-lookback:]

    # 过滤零值
    recent = recent[recent != 0]
    if len(recent) < 2:
        return "SIDE"

    # 计算变化率
    change_pct = (recent[-1] - recent[0]) / recent[0] * 100 if recent[0] != 0 else 0

    if change_pct > 0.1:
        return "UP"
    elif change_pct < -0.1:
        return "DOWN"
    else:
        return "SIDE"


# ========================================================================
# 测试
# ========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("KAMA Indicator Module v1.0 - 单元测试")
    print("=" * 60)

    # 测试1: 持续上涨 → ER应该接近1
    print("\n测试1: 持续上涨")
    trend_up = np.cumsum(np.ones(20))  # [1, 2, 3, ..., 20]
    er_up = calculate_efficiency_ratio(trend_up, 10)
    print(f"  数据: 持续上涨 1→20")
    print(f"  ER = {er_up:.3f} (预期接近1.0)")
    assert er_up > 0.9, f"趋势上涨ER应该>0.9, 实际={er_up}"

    # 测试2: 持续下跌 → ER应该接近1
    print("\n测试2: 持续下跌")
    trend_down = np.cumsum(-np.ones(20))  # [-1, -2, -3, ..., -20]
    er_down = calculate_efficiency_ratio(trend_down, 10)
    print(f"  数据: 持续下跌")
    print(f"  ER = {er_down:.3f} (预期接近1.0)")
    assert er_down > 0.9, f"趋势下跌ER应该>0.9, 实际={er_down}"

    # 测试3: 来回震荡 → ER应该接近0
    print("\n测试3: 来回震荡")
    ranging = np.array([100, 101, 99, 100, 102, 98, 100, 101, 99, 100, 100.0])
    er_ranging = calculate_efficiency_ratio(ranging, 10)
    print(f"  数据: 100附近震荡")
    print(f"  ER = {er_ranging:.3f} (预期接近0)")
    assert er_ranging < 0.2, f"震荡市ER应该<0.2, 实际={er_ranging}"

    # 测试4: 完整KAMA计算
    print("\n测试4: KAMA序列计算")
    prices = np.array([100 + i * 0.5 + np.sin(i / 3) * 2 for i in range(50)])
    kama = calculate_kama(prices, period=10)
    print(f"  数据: 50根K线 (上升+噪音)")
    print(f"  KAMA最后5个值: {kama[-5:]}")

    direction = get_kama_direction(kama)
    print(f"  KAMA方向: {direction}")

    # 测试5: 数据不足
    print("\n测试5: 数据不足")
    short_data = np.array([100, 101, 102])
    er_short = calculate_efficiency_ratio(short_data, 10)
    print(f"  数据: 只有3根K线")
    print(f"  ER = {er_short:.3f} (预期0.5，中性值)")
    assert er_short == 0.5, f"数据不足时ER应该=0.5, 实际={er_short}"

    print("\n" + "=" * 60)
    print("所有测试通过!")
    print("=" * 60)
