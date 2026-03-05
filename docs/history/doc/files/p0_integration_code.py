"""
P0增强集成代码
插入位置: llm_server_test1_9996.py 第2896行之后

版本: v1.0
日期: 2025-12-11

说明:
- 这段代码应插入到 N-Swing 判断逻辑之后、应用增强逻辑之前
- 即第2896行 (elif down_ratio <= 0.97:) 之后
- 第2897行 (# 应用 N-swing 增强) 之前
"""

# ===================================
# 从这里开始复制
# ===================================

# ========= P0增强1: 量价背离检测 =========
if n_score != 0:
    # 多头: 检查上涨段之后的量价背离
    if n_score > 0 and last_up_end is not None:
        segment_closes = closes_nswing[last_up_end:]
        segment_vols = volumes[last_up_end:] if volumes and len(volumes) > last_up_end else None
        
        if segment_vols:
            divergence = detect_volume_price_divergence(segment_closes, segment_vols, window=5)
            
            if divergence == "BEARISH_DIV":
                print(f'[N-SWING] 检测到顶背离 (价涨量缩), 取消多头增强')
                n_score = 0
                n_bias = 'N_NONE'
    
    # 空头: 检查下跌段之后的量价背离
    elif n_score < 0 and last_down_end is not None:
        segment_closes = closes_nswing[last_down_end:]
        segment_vols = volumes[last_down_end:] if volumes and len(volumes) > last_down_end else None
        
        if segment_vols:
            divergence = detect_volume_price_divergence(segment_closes, segment_vols, window=5)
            
            if divergence == "BULLISH_DIV":
                print(f'[N-SWING] 检测到底背离 (价跌量增), 取消空头增强')
                n_score = 0
                n_bias = 'N_NONE'

# ========= P0增强2: 时间权重 =========
if n_score != 0:
    # 计算从锚点到当前的K线数量
    if n_score > 0 and last_up_end is not None:
        bars_needed = len(closes_nswing) - last_up_end
    elif n_score < 0 and last_down_end is not None:
        bars_needed = len(closes_nswing) - last_down_end
    else:
        bars_needed = 0
    
    if bars_needed > 0:
        time_weight = compute_n_swing_time_weight(bars_needed)
        n_score_original = n_score
        
        # 应用时间权重
        n_score_weighted = int(n_score * time_weight)
        
        # 根据加权后的score调整bias
        if abs(n_score_weighted) >= 2:
            # 保持STRONG级别
            pass
        elif abs(n_score_weighted) >= 1:
            # 降级到WEAK
            if n_score > 0:
                n_bias = 'N_BUY_WEAK'
                n_score = 1
            else:
                n_bias = 'N_SELL_WEAK'
                n_score = -1
        else:
            # 权重太低,取消增强
            n_score = 0
            n_bias = 'N_NONE'
        
        if n_score_weighted != n_score_original:
            print(f'[N-SWING] 时间权重调整: bars={bars_needed}, weight={time_weight:.1f}, '
                  f'score: {n_score_original} -> {n_score_weighted}')

# ========= P0增强3: K线实体验证 =========
if n_score != 0:
    # 从data中提取highs, lows, opens (如果有)
    highs_data = data.get('highs', [])
    lows_data = data.get('lows', [])
    opens_data = data.get('opens', [])
    
    if highs_data and lows_data and opens_data:
        # 反转数组顺序 (TV传入的是i=0最新, 我们需要旧->新)
        highs_reversed = list(reversed(highs_data))
        lows_reversed = list(reversed(lows_data))
        opens_reversed = list(reversed(opens_data))
        
        # 多头验证
        if n_score > 0 and last_up_end is not None and up_after_low:
            segment_highs = highs_reversed[last_up_end:]
            segment_lows = lows_reversed[last_up_end:]
            segment_opens = opens_reversed[last_up_end:]
            segment_closes = closes_nswing[last_up_end:]
            
            is_valid, reason = validate_n_swing_candle(
                segment_highs,
                segment_lows,
                segment_opens,
                segment_closes,
                up_after_low,
                is_bullish=True
            )
            
            if not is_valid:
                print(f'[N-SWING] K线验证失败: {reason}, 取消多头增强')
                n_score = 0
                n_bias = 'N_NONE'
        
        # 空头验证
        elif n_score < 0 and last_down_end is not None and down_after_high:
            segment_highs = highs_reversed[last_down_end:]
            segment_lows = lows_reversed[last_down_end:]
            segment_opens = opens_reversed[last_down_end:]
            segment_closes = closes_nswing[last_down_end:]
            
            is_valid, reason = validate_n_swing_candle(
                segment_highs,
                segment_lows,
                segment_opens,
                segment_closes,
                down_after_high,
                is_bullish=False
            )
            
            if not is_valid:
                print(f'[N-SWING] K线验证失败: {reason}, 取消空头增强')
                n_score = 0
                n_bias = 'N_NONE'

# ===================================
# 复制到这里结束
# ===================================

"""
注意事项:
1. 确保在文件开头已导入3个增强函数
2. 确保data变量包含 highs, lows, opens 字段 (需要修改Pine脚本)
3. 如果暂时没有highs/lows/opens, 可以只启用前2项增强
"""
