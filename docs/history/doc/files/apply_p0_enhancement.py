#!/usr/bin/env python3
"""
P0增强自动patch脚本

功能:
1. 自动在指定位置插入3个增强函数
2. 自动在N-Swing逻辑后插入集成代码
3. 创建备份文件
4. 验证插入是否成功

使用方法:
    python apply_p0_enhancement.py

版本: v1.0
日期: 2025-12-11
"""

import os
import re
from datetime import datetime


# ==================== 配置 ====================

TARGET_FILE = "llm_server_test1_9996.py"
BACKUP_SUFFIX = ".backup_p0"

# 3个增强函数的完整代码
ENHANCEMENT_FUNCTIONS = '''
def detect_volume_price_divergence(prices, volumes, window=5):
    """
    检测量价背离
    返回: "BEARISH_DIV" | "BULLISH_DIV" | "NONE"
    """
    if not prices or not volumes or len(prices) < window or len(volumes) < window:
        return "NONE"
    
    try:
        p = prices[-window:]
        v = volumes[-window:]
        
        price_change = (p[-1] - p[0]) / max(p[0], 1e-9)
        vol_avg = sum(v) / len(v)
        vol_change = (v[-1] - v[0]) / max(vol_avg, 1e-9)
        
        if price_change > 0.02 and vol_change < -0.2:
            return "BEARISH_DIV"
        elif price_change < -0.02 and vol_change > 0.2:
            return "BULLISH_DIV"
        
        return "NONE"
    
    except Exception as e:
        print(f"[WARN] detect_volume_price_divergence failed: {e}")
        return "NONE"


def compute_n_swing_time_weight(bars_needed):
    """
    根据触发阈值所需的时间计算权重
    返回: float (0.5 ~ 2.0)
    """
    if bars_needed <= 0:
        return 1.0
    
    if bars_needed <= 3:
        return 2.0
    elif bars_needed <= 5:
        return 1.5
    elif bars_needed <= 8:
        return 1.0
    else:
        return 0.5


def validate_n_swing_candle(highs, lows, opens, closes, anchor_price, is_bullish):
    """
    验证N-swing突破时的K线实体质量
    返回: (is_valid: bool, reason: str)
    """
    if not highs or not lows or not opens or not closes:
        return True, "NO_OHLC_DATA"
    
    if len(highs) != len(lows) or len(highs) != len(opens) or len(highs) != len(closes):
        return True, "ARRAY_LENGTH_MISMATCH"
    
    try:
        threshold_ratio = 1.03 if is_bullish else 0.97
        trigger_idx = None
        
        for i in range(len(highs)):
            if is_bullish:
                if highs[i] >= anchor_price * threshold_ratio:
                    trigger_idx = i
                    break
            else:
                if lows[i] <= anchor_price * threshold_ratio:
                    trigger_idx = i
                    break
        
        if trigger_idx is None:
            return True, "NO_TRIGGER_CANDLE"
        
        o = opens[trigger_idx]
        h = highs[trigger_idx]
        l = lows[trigger_idx]
        c = closes[trigger_idx]
        
        body = abs(c - o)
        total_range = h - l
        
        if total_range == 0:
            return False, "DOJI"
        
        body_ratio = body / total_range
        
        if body_ratio < 0.3:
            return False, "WEAK_BODY"
        
        if c > o:
            upper_shadow = h - c
            if upper_shadow > body * 2:
                return False, "LONG_UPPER_SHADOW"
        elif c < o:
            lower_shadow = c - l
            if lower_shadow > body * 2:
                return False, "LONG_LOWER_SHADOW"
        
        return True, "VALID"
    
    except Exception as e:
        print(f"[WARN] validate_n_swing_candle failed: {e}")
        return True, "EXCEPTION"

'''

# 集成代码
INTEGRATION_CODE = '''
# ========= P0增强1: 量价背离检测 =========
if n_score != 0:
    if n_score > 0 and last_up_end is not None:
        segment_closes = closes_nswing[last_up_end:]
        segment_vols = volumes[last_up_end:] if volumes and len(volumes) > last_up_end else None
        
        if segment_vols:
            divergence = detect_volume_price_divergence(segment_closes, segment_vols, window=5)
            
            if divergence == "BEARISH_DIV":
                print(f'[N-SWING] 检测到顶背离 (价涨量缩), 取消多头增强')
                n_score = 0
                n_bias = 'N_NONE'
    
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
    if n_score > 0 and last_up_end is not None:
        bars_needed = len(closes_nswing) - last_up_end
    elif n_score < 0 and last_down_end is not None:
        bars_needed = len(closes_nswing) - last_down_end
    else:
        bars_needed = 0
    
    if bars_needed > 0:
        time_weight = compute_n_swing_time_weight(bars_needed)
        n_score_original = n_score
        
        n_score_weighted = int(n_score * time_weight)
        
        if abs(n_score_weighted) >= 2:
            pass
        elif abs(n_score_weighted) >= 1:
            if n_score > 0:
                n_bias = 'N_BUY_WEAK'
                n_score = 1
            else:
                n_bias = 'N_SELL_WEAK'
                n_score = -1
        else:
            n_score = 0
            n_bias = 'N_NONE'
        
        if n_score_weighted != n_score_original:
            print(f'[N-SWING] 时间权重调整: bars={bars_needed}, weight={time_weight:.1f}, '
                  f'score: {n_score_original} -> {n_score_weighted}')

# ========= P0增强3: K线实体验证 =========
if n_score != 0:
    highs_data = data.get('highs', [])
    lows_data = data.get('lows', [])
    opens_data = data.get('opens', [])
    
    if highs_data and lows_data and opens_data:
        highs_reversed = list(reversed(highs_data))
        lows_reversed = list(reversed(lows_data))
        opens_reversed = list(reversed(opens_data))
        
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

'''


# ==================== 核心函数 ====================

def create_backup(filepath):
    """创建备份文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{filepath}{BACKUP_SUFFIX}_{timestamp}"
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ 备份已创建: {backup_path}")
    return backup_path


def find_insertion_points(content):
    """查找插入位置"""
    lines = content.split('\n')
    
    # 查找函数定义区域 (在compute_l2_local_exec_bias之前)
    func_insert_line = None
    for i, line in enumerate(lines):
        if 'def compute_l2_local_exec_bias' in line:
            func_insert_line = i
            break
    
    # 查找N-Swing逻辑插入点 (elif down_ratio <= 0.97: 之后)
    nswing_insert_line = None
    for i, line in enumerate(lines):
        if 'elif down_ratio <= 0.97:' in line:
            # 找到这行后，继续找到下一个非空行
            for j in range(i+1, len(lines)):
                if lines[j].strip() and not lines[j].strip().startswith('#'):
                    nswing_insert_line = j
                    break
            break
    
    return func_insert_line, nswing_insert_line


def apply_patch(filepath):
    """应用patch"""
    print("=" * 70)
    print("开始应用P0增强patch")
    print("=" * 70)
    
    # 1. 检查文件存在
    if not os.path.exists(filepath):
        print(f"❌ 错误: 文件不存在 - {filepath}")
        return False
    
    # 2. 创建备份
    backup_path = create_backup(filepath)
    
    # 3. 读取文件
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 4. 查找插入位置
    func_line, nswing_line = find_insertion_points(content)
    
    if func_line is None:
        print("❌ 错误: 无法找到函数插入位置 (compute_l2_local_exec_bias)")
        return False
    
    if nswing_line is None:
        print("❌ 错误: 无法找到N-Swing集成位置 (elif down_ratio <= 0.97:)")
        return False
    
    print(f"✅ 找到函数插入位置: 第{func_line}行")
    print(f"✅ 找到N-Swing集成位置: 第{nswing_line}行")
    
    # 5. 插入代码
    lines = content.split('\n')
    
    # 插入函数定义
    func_lines = ENHANCEMENT_FUNCTIONS.strip().split('\n')
    lines = lines[:func_line] + func_lines + [''] + lines[func_line:]
    
    # 重新计算nswing_line (因为前面插入了代码)
    nswing_line += len(func_lines) + 1
    
    # 插入集成代码
    integration_lines = INTEGRATION_CODE.strip().split('\n')
    lines = lines[:nswing_line] + [''] + integration_lines + [''] + lines[nswing_line:]
    
    # 6. 写回文件
    patched_content = '\n'.join(lines)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(patched_content)
    
    print(f"✅ P0增强已成功应用!")
    print(f"   - 新增3个函数 ({len(func_lines)}行)")
    print(f"   - 新增集成代码 ({len(integration_lines)}行)")
    print(f"   - 总计新增 {len(func_lines) + len(integration_lines)}行")
    
    # 7. 验证
    print("\n" + "=" * 70)
    print("验证patch结果")
    print("=" * 70)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        new_content = f.read()
    
    checks = [
        ("detect_volume_price_divergence" in new_content, "函数1: 量价背离检测"),
        ("compute_n_swing_time_weight" in new_content, "函数2: 时间权重"),
        ("validate_n_swing_candle" in new_content, "函数3: K线实体验证"),
        ("P0增强1: 量价背离检测" in new_content, "集成代码: 量价背离"),
        ("P0增强2: 时间权重" in new_content, "集成代码: 时间权重"),
        ("P0增强3: K线实体验证" in new_content, "集成代码: K线实体验证"),
    ]
    
    all_passed = True
    for passed, desc in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {desc}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n🎉 所有验证通过! P0增强已成功集成!")
        print(f"\n备份文件: {backup_path}")
        print(f"目标文件: {filepath}")
    else:
        print("\n⚠️  部分验证失败,请检查!")
        print(f"可从备份恢复: {backup_path}")
    
    print("=" * 70)
    
    return all_passed


# ==================== 主函数 ====================

def main():
    """主函数"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║              P0增强自动patch工具 v1.0                        ║
║                                                              ║
║  功能: 自动为N-Swing添加3项P0增强                            ║
║  1. 量价背离检测 - 防止假突破                                ║
║  2. 时间权重 - 区分快拉vs慢涨                                ║
║  3. K线实体验证 - 防止上影线欺骗                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # 检查目标文件
    if not os.path.exists(TARGET_FILE):
        print(f"❌ 错误: 找不到目标文件 - {TARGET_FILE}")
        print("请确保在正确的目录下运行此脚本")
        return
    
    # 应用patch
    success = apply_patch(TARGET_FILE)
    
    if success:
        print("\n📝 下一步:")
        print("1. 修改TradingView Pine脚本 (参考 TV_enhanced_v2.pine)")
        print("2. 部署新版Pine到TradingView")
        print("3. 重启Python服务")
        print("4. 观察日志输出,验证P0增强生效")
    else:
        print("\n⚠️  patch失败,请手动检查!")


if __name__ == "__main__":
    main()
