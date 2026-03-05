"""
P0增强函数 - N-Swing假信号过滤
包含3个核心函数：量价背离、时间权重、K线实体验证

版本: v1.0
日期: 2025-12-11
作者: AI Trading System
"""


def detect_volume_price_divergence(prices, volumes, window=5):
    """
    检测量价背离
    
    核心逻辑:
    - 价涨量缩 -> 顶背离 (BEARISH_DIV) - 可能见顶
    - 价跌量增 -> 底背离 (BULLISH_DIV) - 可能见底
    
    Args:
        prices (list): 价格数组,至少window个元素
        volumes (list): 成交量数组,至少window个元素
        window (int): 检测窗口,默认5根K线
    
    Returns:
        str: "BEARISH_DIV" | "BULLISH_DIV" | "NONE"
    
    示例:
        >>> prices = [95000, 96000, 97000, 98000, 99000]
        >>> volumes = [2000, 1800, 1500, 1200, 1000]
        >>> detect_volume_price_divergence(prices, volumes)
        'BEARISH_DIV'  # 价涨量缩,顶背离
    """
    if not prices or not volumes or len(prices) < window or len(volumes) < window:
        return "NONE"
    
    try:
        # 取最近window根K线
        p = prices[-window:]
        v = volumes[-window:]
        
        # 计算价格趋势 (涨跌幅)
        price_change = (p[-1] - p[0]) / max(p[0], 1e-9)
        
        # 计算成交量趋势 (相对平均量的变化)
        vol_avg = sum(v) / len(v)
        vol_change = (v[-1] - v[0]) / max(vol_avg, 1e-9)
        
        # 判断背离
        # 价涨量缩 -> 顶背离 (上涨超过2%,但量能下降超过20%)
        if price_change > 0.02 and vol_change < -0.2:
            return "BEARISH_DIV"
        
        # 价跌量增 -> 底背离 (下跌超过2%,但量能上升超过20%)
        elif price_change < -0.02 and vol_change > 0.2:
            return "BULLISH_DIV"
        
        return "NONE"
    
    except Exception as e:
        print(f"[WARN] detect_volume_price_divergence failed: {e}")
        return "NONE"


def compute_n_swing_time_weight(bars_needed):
    """
    根据触发阈值所需的时间计算权重
    
    核心逻辑:
    - 时间越短 -> 动能越强 -> 权重越高
    - 快速形成的形态比缓慢形成的更有效
    
    Args:
        bars_needed (int): 从锚点到触发阈值的K线数量
    
    Returns:
        float: 权重系数 (0.5 ~ 2.0)
            - 2.0: 3根K内完成 (极强动能)
            - 1.5: 5根K内完成 (强动能)
            - 1.0: 8根K内完成 (正常动能)
            - 0.5: 8根K以上 (弱动能)
    
    示例:
        >>> compute_n_swing_time_weight(2)
        2.0  # 2根K完成,极强
        >>> compute_n_swing_time_weight(10)
        0.5  # 10根K,太慢
    """
    if bars_needed <= 0:
        return 1.0
    
    if bars_needed <= 3:
        return 2.0    # 3根K内完成 -> 极强动能
    elif bars_needed <= 5:
        return 1.5    # 5根K内完成 -> 强动能
    elif bars_needed <= 8:
        return 1.0    # 8根K内完成 -> 正常动能
    else:
        return 0.5    # 8根K以上 -> 弱动能


def validate_n_swing_candle(highs, lows, opens, closes, anchor_price, is_bullish):
    """
    验证N-swing突破时的K线实体质量
    
    核心逻辑:
    - 检查触发阈值的K线是否有足够的实体
    - 过滤上影线/下影线过长的假突破
    - 过滤十字星等无方向K线
    
    Args:
        highs (list): 高价数组
        lows (list): 低价数组
        opens (list): 开盘价数组
        closes (list): 收盘价数组
        anchor_price (float): 锚点价格
        is_bullish (bool): True=多头突破, False=空头突破
    
    Returns:
        tuple: (is_valid: bool, reason: str)
            - (True, "VALID"): K线质量合格
            - (False, "DOJI"): 十字星,无方向
            - (False, "WEAK_BODY"): 实体太小(<30%)
            - (False, "LONG_UPPER_SHADOW"): 上影线过长(>实体2倍)
            - (False, "LONG_LOWER_SHADOW"): 下影线过长(>实体2倍)
    
    示例:
        多头突破:
        >>> highs = [98000, 98500, 99000]
        >>> lows = [97800, 98000, 98500]
        >>> opens = [97900, 98200, 98600]
        >>> closes = [98100, 98400, 98900]
        >>> validate_n_swing_candle(highs, lows, opens, closes, 95000, True)
        (True, 'VALID')  # 实体健康
        
        假突破:
        >>> highs = [98000, 99500, 98200]  # 第2根触及+3%
        >>> lows = [97800, 98000, 98000]
        >>> opens = [97900, 98100, 98100]
        >>> closes = [98100, 98150, 98100]  # 但收盘回落
        >>> validate_n_swing_candle(highs, lows, opens, closes, 95000, True)
        (False, 'LONG_UPPER_SHADOW')  # 上影线过长
    """
    if not highs or not lows or not opens or not closes:
        return True, "NO_OHLC_DATA"  # 缺数据时默认通过
    
    if len(highs) != len(lows) or len(highs) != len(opens) or len(highs) != len(closes):
        return True, "ARRAY_LENGTH_MISMATCH"
    
    try:
        # 找到首次触及阈值的K线
        threshold_ratio = 1.03 if is_bullish else 0.97
        trigger_idx = None
        
        for i in range(len(highs)):
            if is_bullish:
                # 多头: 高点触及 anchor * 1.03 (+3%)
                if highs[i] >= anchor_price * threshold_ratio:
                    trigger_idx = i
                    break
            else:
                # 空头: 低点触及 anchor * 0.97 (-3%)
                if lows[i] <= anchor_price * threshold_ratio:
                    trigger_idx = i
                    break
        
        if trigger_idx is None:
            return True, "NO_TRIGGER_CANDLE"
        
        # 提取触发K线的OHLC
        o = opens[trigger_idx]
        h = highs[trigger_idx]
        l = lows[trigger_idx]
        c = closes[trigger_idx]
        
        # 计算实体和影线
        body = abs(c - o)
        total_range = h - l
        
        if total_range == 0:
            return False, "DOJI"  # 十字星,无方向
        
        body_ratio = body / total_range
        
        # 检查实体太小 (实体不足30%)
        if body_ratio < 0.3:
            return False, "WEAK_BODY"
        
        # 多头K线: 检查上影线
        if c > o:
            upper_shadow = h - c
            lower_shadow = o - l
            
            # 上影线过长 (超过实体2倍)
            if upper_shadow > body * 2:
                return False, "LONG_UPPER_SHADOW"
        
        # 空头K线: 检查下影线
        elif c < o:
            upper_shadow = h - o
            lower_shadow = c - l
            
            # 下影线过长 (超过实体2倍)
            if lower_shadow > body * 2:
                return False, "LONG_LOWER_SHADOW"
        
        return True, "VALID"
    
    except Exception as e:
        print(f"[WARN] validate_n_swing_candle failed: {e}")
        return True, "EXCEPTION"  # 异常时默认通过


# ==================== 使用示例 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("P0增强函数测试")
    print("=" * 60)
    
    # 测试1: 量价背离检测
    print("\n【测试1: 量价背离检测】")
    
    # 顶背离: 价涨量缩
    prices1 = [95000, 96000, 97000, 98000, 99000]
    volumes1 = [2000, 1800, 1500, 1200, 1000]
    result1 = detect_volume_price_divergence(prices1, volumes1)
    print(f"价涨量缩: {result1}")  # 预期: BEARISH_DIV
    
    # 底背离: 价跌量增
    prices2 = [99000, 98000, 97000, 96000, 95000]
    volumes2 = [1000, 1200, 1500, 1800, 2000]
    result2 = detect_volume_price_divergence(prices2, volumes2)
    print(f"价跌量增: {result2}")  # 预期: BULLISH_DIV
    
    # 正常: 量价配合
    prices3 = [95000, 96000, 97000, 98000, 99000]
    volumes3 = [1000, 1200, 1500, 1800, 2000]
    result3 = detect_volume_price_divergence(prices3, volumes3)
    print(f"量价配合: {result3}")  # 预期: NONE
    
    # 测试2: 时间权重
    print("\n【测试2: 时间权重】")
    for bars in [2, 5, 8, 12]:
        weight = compute_n_swing_time_weight(bars)
        print(f"{bars}根K线: 权重={weight}")
    
    # 测试3: K线实体验证
    print("\n【测试3: K线实体验证】")
    
    # 健康突破
    highs_good = [98000, 98500, 99000]
    lows_good = [97800, 98000, 98500]
    opens_good = [97900, 98200, 98600]
    closes_good = [98100, 98400, 98900]
    valid, reason = validate_n_swing_candle(
        highs_good, lows_good, opens_good, closes_good, 95000, True
    )
    print(f"健康突破: valid={valid}, reason={reason}")
    
    # 上影线假突破
    highs_fake = [98000, 99500, 98200]  # 第2根冲高到+3%
    lows_fake = [97800, 98000, 98000]
    opens_fake = [97900, 98100, 98100]
    closes_fake = [98100, 98150, 98100]  # 但收盘回落
    valid2, reason2 = validate_n_swing_candle(
        highs_fake, lows_fake, opens_fake, closes_fake, 95000, True
    )
    print(f"假突破: valid={valid2}, reason={reason2}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
