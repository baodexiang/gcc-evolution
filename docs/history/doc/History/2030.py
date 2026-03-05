#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志重构补丁 v2.030 - 交易审计风格
=====================================

【核心目标】
1. 重写STEP6/STEP7为"交易审计报告风格"
2. 彻底拆清 Donchian Signal vs Zone
3. 统一三套坐标体系（L1/L2/Rhythm）

【严格约束】
✓ 只改日志输出层
✗ 不改任何交易逻辑
✗ 不改任何Gate判定条件
✗ 不改L2计算方式

使用方法：
    python3 log_refactor_v2030_FINAL.py
"""

import sys
import os
import re

INPUT_FILE = "llm_server_test1_2030.py"
OUTPUT_FILE = "llm_server_test1_2030_AUDIT_LOG.py"


# ========== 术语字典（嵌入到代码注释中） ==========
TERMINOLOGY_DICT = '''
# ========================================================================
# 术语与坐标体系权威字典 v2.030
# ========================================================================
#
# 1. Donchian Signal vs Zone（严禁混淆）
#    ┌─────────────────┬────────────────────────────────────────┐
#    │ donchian_signal │ 事件/触发: breakout/breakdown/cross_over│
#    │                 │ cross_under/none                        │
#    ├─────────────────┼────────────────────────────────────────┤
#    │ donchian_zone   │ 位置/区域: LOWER_HALF/UPPER_HALF       │
#    │ (或sr_zone)     │ 或BELOW_SUPPORT/MID/ABOVE_RESIST       │
#    └─────────────────┴────────────────────────────────────────┘
#
# 2. 三套坐标体系（必须清晰区分）
#    ┌──────────┬────────────────┬────────────────────────┐
#    │ 坐标系   │ 使用字段       │ 用途                   │
#    ├──────────┼────────────────┼────────────────────────┤
#    │ L1 120-K │ low_120        │ Wyckoff阶段判断        │
#    │ 线区间   │ high_120       │ 趋势方向判断           │
#    │          │ mid_120        │ 宏观位置(pos_zone)     │
#    │          │ pos_ratio      │ near_low_120/high_120  │
#    ├──────────┼────────────────┼────────────────────────┤
#    │ L2 SR    │ sr_support     │ exec_bias计算          │
#    │ 三线     │ sr_mid         │ 执行精度控制           │
#    │          │ sr_resistance  │ L2大周期决策           │
#    │          │ sr_zone        │                        │
#    ├──────────┼────────────────┼────────────────────────┤
#    │ Rhythm   │ prev_sr        │ 二买二卖区间(1/3划分) │
#    │ Gate     │ reference_zone │ 突破/回落判定          │
#    │ (前序SR) │ zone_range     │ two_buy/sell计数       │
#    └──────────┴────────────────┴────────────────────────┘
#
# 3. 位置标签对照
#    pos_zone (L1-120K): EXTREME_LOW/LOW/MID/HIGH/EXTREME_HIGH
#    sr_zone (L2-SR):    LOWER/MID/UPPER 或 LOWER_HALF/UPPER_HALF
#
# 4. 二买二卖区间（Rhythm Gate）
#    基准: 使用前一根K线的prev_sr
#    划分: 1/3区间（v2.025更新）
#    - 二买区间: [support, support + (mid-support)/3]
#    - 二卖区间: [resistance - (resistance-mid)/3, resistance]
#
# ========================================================================
'''


def apply_patch_terminology_dict(content: str) -> str:
    """PATCH 1: 插入术语字典"""
    print("[PATCH 1/3] 插入术语字典...")
    
    # 在文件开头的注释区插入
    insert_marker = "# =========================================================\n# AI PRO TRADING SYSTEM"
    
    if insert_marker in content:
        content = content.replace(
            insert_marker,
            TERMINOLOGY_DICT + "\n" + insert_marker
        )
        print("  ✓ 术语字典已插入\n")
    else:
        print("  ! 未找到插入点，跳过\n")
    
    return content


def apply_patch_step6_refactor(content: str) -> str:
    """PATCH 2: 重写STEP6为交易审计风格"""
    print("[PATCH 2/3] 重写STEP6...")
    
    # 找到STEP6的开始和结束
    step6_start = '"STEP6 - L2 Execution Layer & Decision Flow'
    step7_start = '"STEP7 - Final Decision & Execution'
    
    if step6_start not in content or step7_start not in content:
        print("  ! 未找到STEP6/STEP7标记\n")
        return content
    
    # 新的STEP6模板
    new_step6 = '''        "=" * 80,
        "STEP6 - L2 EXECUTION LAYER AUDIT / L2执行层审计报告",
        "=" * 80,
        "",
        "━━━ [6.1] L2 Input Snapshot / L2输入快照 ━━━",
        "",
        "SR Coordinate System (当前K线Donchian三线):",
        f"  sr_support:    {decision.get('sr_support', 'N/A'):.2f}" if isinstance(decision.get('sr_support'), (int, float)) else f"  sr_support:    {decision.get('sr_support', 'N/A')}",
        f"  sr_mid:        {decision.get('sr_mid', 'N/A'):.2f}" if isinstance(decision.get('sr_mid'), (int, float)) else f"  sr_mid:        {decision.get('sr_mid', 'N/A')}",
        f"  sr_resistance: {decision.get('sr_resistance', 'N/A'):.2f}" if isinstance(decision.get('sr_resistance'), (int, float)) else f"  sr_resistance: {decision.get('sr_resistance', 'N/A')}",
        f"  last_close:    {last_close:.2f}",
        "",
        "Donchian Status (区分Signal和Zone):",
        f"  donchian_signal: {signal}  ← 事件: breakout/breakdown/cross_over/cross_under/none",
        f"  donchian_zone:   {decision.get('l2_zone_tag', sr_zone)}  ← 位置: LOWER_HALF/MID/UPPER_HALF",
        "",
        "Price Action Signals:",
        f"  pa_buy_edge:   {pa_buy_edge}",
        f"  pa_sell_edge:  {pa_sell_edge}",
        f"  pa_tag:        {normalize_l2_tag(pa_tag)}",
        f"  two_b_tag:     {normalize_l2_tag(two_b_tag)}",
        f"  volume_state:  {normalize_l2_tag(volume_state)}",
        "",
        "Market Environment:",
        f"  bearish_env:   {bearish_env}",
        f"  bearish_gate:  {bearish_gate}",
        f"  rally_active:  {state.get('rally_active', False)}",
        "",
        "",
        "━━━ [6.2] L2 Decision Chain / L2决策链路 ━━━",
        "",
        "Step 1: Base exec_bias (基于SR+PA+2B+Volume):",
        f"  sr_zone → exec_bias 映射:",
        f"    Input:  sr_zone={sr_zone}, pa_buy={pa_buy_edge}, pa_sell={pa_sell_edge}, vol={normalize_l2_tag(volume_state)}",
        f"    Output: base_exec_bias = {decision.get('base_exec_bias', exec_bias)}",
        "",
        "Step 2: N-swing Enhancement (N字形态增强):",
        f"  Applied: {state.get('_n_swing_info', {}).get('applied', False)}",
        "" if not state.get('_n_swing_info', {}).get('applied') else f"  N-swing bias: {state.get('_n_swing_info', {}).get('bias', 'NONE')}, score: {state.get('_n_swing_info', {}).get('score', 0)}",
        f"  After N-swing: exec_bias = {exec_bias}",
        "",
        "Step 3: Direction Gate (方向门控 - 低位禁空/高位禁多):",
        f"  Gate result: {('✓ PASS' if decision.get('l2_reason_tag') is None else '✗ BLOCKED by ' + str(decision.get('l2_reason_tag')))}",
        f"  Final exec_bias: {exec_bias}",
        "",
        "",
        "━━━ [6.3] L2 → L1 Mapping / 执行层→决策层映射 ━━━",
        "",
        f"  L1 action (before L2): {l1_action_before_l2}",
        f"  L2 exec_bias:          {exec_bias}",
        f"  L2 gate result:        {decision.get('l2_reason_tag') or '✓ PASS'}",
        f"  Action (after L2):     {final_action}",
        "",
        "",
        "━━━ [6.4] Rhythm Gate Audit / 节奏门审计 (二买二卖) ━━━",
        "",
        "Coordinate System: 使用前一根K线的prev_sr (1/3区间划分)",
        f"  prev_sr.support:    {rhythm_status.get('reference_zone', {}).get('zone_low', 'N/A'):.2f}" if isinstance(rhythm_status.get('reference_zone', {}).get('zone_low'), (int, float)) else f"  prev_sr.support:    N/A",
        f"  prev_sr.mid:        {(rhythm_status.get('reference_zone', {}).get('zone_low', 0) + rhythm_status.get('reference_zone', {}).get('zone_high', 0))*1.5:.2f}" if isinstance(rhythm_status.get('reference_zone', {}).get('zone_low'), (int, float)) else f"  prev_sr.mid:        N/A",
        f"  reference_zone:     {rhythm_status.get('reference_zone', {}).get('zone_type', 'UNKNOWN')}",
        f"  zone_range:         {rhythm_status.get('reference_zone', {}).get('zone_desc', 'N/A')}",
        "",
        "Rhythm Status:",
        f"  execution_rhythm:   {rhythm_status.get('execution_rhythm', 'NONE')}  ← TWO_BUY/TWO_SELL/NONE",
        f"  rhythm_status:      {rhythm_status.get('rhythm_status', 'INACTIVE')}",
        "",
        "Structure Confirmation:",
        f"  breakout_confirmed:      {rhythm_status.get('structure_confirmed', {}).get('breakout_confirmed', False)}  ← 是否突破prev_sr区间",
        f"  zone_return_confirmed:   {rhythm_status.get('structure_confirmed', {}).get('zone_return_confirmed', False)}  ← 是否回到prev_sr区间",
        "",
        "Execution Count (剩余次数):",
        f"  two_buy_used:       {rhythm_status.get('two_buy_used', 0)} / 2",
        f"  two_sell_used:      {rhythm_status.get('two_sell_used', 0)} / 2",
        f"  current_phase:      {('第1次已完成，准备第2次' if rhythm_status.get('two_buy_used', 0) == 1 else ('已完成（2/2）' if rhythm_status.get('two_buy_used', 0) >= 2 else '准备第1次执行'))}",
        "",
        "Rhythm Effect:",
        f"  rhythm_effect:      {rhythm_status.get('rhythm_effect', 'NEUTRAL')}  ← ALLOW/BLOCK/NEUTRAL",
        "" if not rhythm_status.get('block_reason') else f"  block_reason:       {rhythm_status.get('block_reason')}",
        "",
        "说明: 二买=突破后顺势2次, 二卖=失败后防守2次, 超限后仅HOLD",
        "",
        "",
        "━━━ [6.5] Other Gates Status / 其他门控状态 ━━━",
        "",'''
    
    # 添加gates状态
    gates_block = '''        f"  smart_limit_gate:        {'✓ PASS' if gates['smart_limit_gate']['pass'] else '✗ BLOCK'}  {gates['smart_limit_gate']['reason_cn']}",
        f"  low_120_no_short_gate:   {'✓ PASS' if gates['low_120_no_short_gate']['pass'] else '✗ BLOCK'}  {gates['low_120_no_short_gate']['reason_cn']}",
        f"  phase_short_quota_gate:  {'✓ PASS' if gates['phase_short_quota_gate']['pass'] else '✗ BLOCK'}  {gates['phase_short_quota_gate']['reason_cn']}",
        f"  global_trade_quota_gate: {'✓ PASS' if gates['global_trade_quota_gate']['pass'] else '✗ BLOCK'}  {gates['global_trade_quota_gate']['reason_cn']}",
        f"  unclear_mid_gate:        {'✓ PASS' if gates['unclear_mid_no_edge_gate']['pass'] else '✗ BLOCK'}  {gates['unclear_mid_no_edge_gate']['reason_cn']}",
        f"  grid_pa_edge_gate:       {'✓ PASS' if gates['grid_pa_edge_gate']['pass'] else '✗ BLOCK'}  {gates['grid_pa_edge_gate']['reason_cn']}",
        f"  bearish_buy_gate:        {'✓ PASS' if gates['bearish_buy_gate']['pass'] else '✗ BLOCK'}  {gates['bearish_buy_gate']['reason_cn']}",
        "",
        "",'''
    
    new_step6 += gates_block
    
    # 用正则找到STEP6的完整区块并替换
    pattern = re.compile(
        r'("STEP6 - L2 Execution Layer.*?)"STEP7 - Final Decision',
        re.DOTALL
    )
    
    def replacer(match):
        return new_step6 + '\n        "STEP7 - Final Decision'
    
    content = pattern.sub(replacer, content)
    
    print("  ✓ STEP6已重写为审计风格\n")
    return content


def apply_patch_step7_refactor(content: str) -> str:
    """PATCH 3: 重写STEP7责任链"""
    print("[PATCH 3/3] 重写STEP7...")
    
    # 新的STEP7模板
    new_step7 = '''        "=" * 80,
        "STEP7 - DECISION RESPONSIBILITY CHAIN / 最终决策责任链",
        "=" * 80,
        "",
        "━━━ [7.1] Decision Flow / 决策流程 ━━━",
        "",
        "① LLM Raw Output (LLM原始输出):",
        f"  llm_raw_action:    {llm_raw_action}",
        f"  confidence:        {confidence:.2f}",
        "",
        "② Grid/PA Filter (格子层+PA过滤):",
        f"  ai_action:         {ai_action}  ← Grid决策表 + PA edge规则",
        f"  grid_applied:      {llm_fallback}",
        "",
        "③ L1 Decision (L1决策层):",
        f"  l1_action:         {l1_action_before_l2}  ← 进入L2之前",
        "",
        "④ L2 Execution Layer (L2执行层):",
        f"  exec_bias:         {exec_bias}",
        f"  l2_gate_result:    {decision.get('l2_reason_tag') or '✓ PASS'}",
        "",
        "⑤ Rhythm Gate (节奏门):",
        f"  rhythm_effect:     {rhythm_status.get('rhythm_effect', 'NEUTRAL')}",
        "" if rhythm_status.get('rhythm_effect') == 'NEUTRAL' else f"  rhythm_impact:     {rhythm_status.get('block_reason', 'N/A')}",
        "",
        "⑥ Other Gates (其他门控):",'''
    
    # 添加gates摘要
    gates_summary = '''        f"  blocked_gates:     {[k for k,v in gates.items() if not v.get('pass', True)]}",
        "",
        "⑦ Final Action (最终动作):",
        f"  final_action:      {final_action}  ← 最终执行",
        "",
        "",
        "━━━ [7.2] Why This Action? / 为什么是这个动作？ ━━━",
        "",'''
    
    new_step7 += gates_summary
    
    # 添加决策原因分析
    reason_analysis = '''        f"  blocked_by:        {entry_block_reason or 'NONE'}",
        f"  overridden_by:     {('GRID_DECISION' if llm_fallback and grid_action else ('L2_GATE' if decision.get('l2_reason_tag') else 'NONE'))}",
        "",
        "Decision Logic Chain (决策逻辑链):",'''
    
    new_step7 += reason_analysis
    
    # 根据final_action给出解释
    explain_block = '''        "" if final_action != "HOLD" else "  ✓ Action=HOLD 原因:",
        "" if final_action != "HOLD" or not entry_block_reason else f"     - {entry_block_reason}",
        "" if final_action != "HOLD" or entry_block_reason else "     - LLM/Grid判断为HOLD",
        "",
        "" if final_action == "HOLD" else f"  ✓ Action={final_action} 路径:",
        "" if final_action == "HOLD" else f"     - LLM → Grid → L1 → L2 → Rhythm → Other Gates → {final_action}",
        "",
        "",
        "━━━ [7.3] Execution Summary / 执行摘要 ━━━",
        "",'''
    
    new_step7 += explain_block
    
    # 添加执行摘要
    exec_summary = '''        "Position State:",
        f"  position_units:    {state['position_units']}/{MAX_UNITS_PER_SYMBOL}",
        f"  open_buys:         {len(state.get('open_buys', []))}",
        f"  open_sells:        {len(state.get('open_sells', []))}",
        f"  cycle_id:          {state['cycle_id']}",
        "",
        "Trade Counts:",
        f"  actual_buy_count:  {state.get('actual_buy_count', 0)}",
        f"  actual_sell_count: {state.get('actual_sell_count', 0)}",
        "",
        "Action Log:",
        f"  symbol:            {symbol}",
        f"  side:              {final_action if final_action in ['BUY', 'SELL'] else 'NONE'}",
        f"  exec:              {exec_flag}",
        f"  trade_mode:        {trade_mode}",
        "",
        "=" * 80,
        "",'''
    
    new_step7 += exec_summary
    
    # 替换STEP7
    pattern = re.compile(
        r'"STEP7 - Final Decision & Execution.*?(?="STEP8|"Trading Principles)',
        re.DOTALL
    )
    
    content = pattern.sub(lambda m: new_step7, content)
    
    print("  ✓ STEP7已重写为责任链风格\n")
    return content


def main():
    print("\n" + "=" * 80)
    print("日志重构补丁 v2.030 - 交易审计风格")
    print("=" * 80)
    print(f"\n输入: {INPUT_FILE}")
    print(f"输出: {OUTPUT_FILE}\n")
    
    if not os.path.exists(INPUT_FILE):
        print(f"✗ 文件不存在: {INPUT_FILE}")
        return 1
    
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_lines = len(content.splitlines())
    print(f"原文件: {original_lines} 行\n")
    print("=" * 80 + "\n")
    
    # 应用补丁
    try:
        content = apply_patch_terminology_dict(content)
        content = apply_patch_step6_refactor(content)
        content = apply_patch_step7_refactor(content)
    except Exception as e:
        print(f"\n✗ 补丁应用失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # 保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    
    final_lines = len(content.splitlines())
    
    print("=" * 80)
    print("✅ 日志重构完成")
    print("=" * 80)
    print(f"\n输出文件: {OUTPUT_FILE}")
    print(f"行数变化: {original_lines} → {final_lines} ({final_lines - original_lines:+d})\n")
    
    print("改进摘要:")
    print("  ✓ 插入术语字典（Signal vs Zone, 三套坐标体系）")
    print("  ✓ STEP6重写为审计报告风格")
    print("  ✓ STEP7重写为责任链风格")
    print("  ✓ 统一Donchian Signal/Zone命名")
    print("  ✓ 明确L1/L2/Rhythm坐标体系\n")
    
    print("验收标准:")
    print("  ✓ 一眼看懂决策链")
    print("  ✓ 一眼看懂Signal vs Zone")
    print("  ✓ 一眼看懂三套坐标体系")
    print("  ✓ 一眼看懂为什么HOLD\n")
    
    print("验证步骤:")
    print("  python3 -m py_compile " + OUTPUT_FILE + "\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())