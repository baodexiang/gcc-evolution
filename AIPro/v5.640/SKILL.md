---
name: Aipro
use_deepseek_api: true
deepseek_model: deepseek-chat
description: AI PRO Trading System v5.640 - **核心职责**：更新主程序(.GCC/skill/SKILL.md)和云端程序(AI Pro/v5.640/SKILL.md)的md文件。**v5.640新功能**(缠论K线合并+三段判定早期趋势变化检测)。**7个外挂架构**(扫描引擎:P0-Tracking+剥头皮+SuperTrend；L1层:RobHoffman+双底双顶+飞云；L2层:MACD背离)。**L2评分体系**(5大类±22:形态±6+唐纳奇综合±8+量能±2+Wyckoff±2+每日偏向±2+Vegas隧道±2)。**信号来源分布**(外挂激活60%买卖+主程序协商40%买卖)。
version: 5.640
---

# AI PRO Trading System v5.640

## DeepSeek API处理

**本skill使用DeepSeek API进行文档分析和内容生成**

```
执行流程:
1. 读取代码变更 → 提取新功能/修复点
2. 构建DeepSeek prompt → 要求生成结构化文档
3. 调用DeepSeek API → 获取专业文档内容
4. 更新md文件 → .GCC/skill/SKILL.md + AI Pro/v5.640/SKILL.md
```

**DeepSeek生成要点**:
- 版本号和日期
- 功能描述（问题/解决方案）
- 检测命令和验证方法
- 版本历史记录

---

## 外挂总览 (GCC-0194重构)

| 层级 | 外挂 | 状态 | 数据周期 | 触发条件 | 冻结 |
|------|------|------|----------|----------|------|
| **P0** | P0-Open | ⏸️ 暂停 | 1h | UP→BUY, DOWN→SELL, SIDE→跳过 | 1-4h |
| **P0** | P0-Tracking | ✅ 运行 | 1h | 任何趋势下触发(v11.6) + 每日偏向 | 2-8h |
| **P0** | Chandelier+ZLSMA | ✅ 运行 | 5m | UP只买, DOWN只卖, SIDE依赖信号 + 每日偏向 | 2-8h |
| **L1** | SuperTrend v0.8.5 | ✅ 运行 | 1h | 方向+位置过滤(趋势解耦) | 门卫冻结 |
| **L1** | 飞云双突破 | ✅ 运行 | 1h | 趋势线+形态+放量(趋势解耦) | 门卫冻结 |
| **L1** | Rob Hoffman v2.0.1 | ✅ 运行 | 1h | IRB修正+动态ER阈值(恢复) | 门卫冻结 |
| **L2** | MACD背离 v1.0 | ✅ 运行 | 10m | 底/顶背离+GCC-0173双通道日志 | 无 |
| **独立** | Vision统一 v3.5 | ✅ 运行 | 4h(1h降频) | 8种Vision+21种Brooks形态统一GPT调用 | 每日1买1卖 |

### 信号发单管线 (三条平行线, GCC-0194重构)

```text
管线A: 外挂信号 (主力) [GCC-0171审计]
  外挂: SuperTrend / 飞云 / RobHoffman / 缠论买卖点 / 双底双顶
  → FilterChain Vision门控 (扫描引擎统一过滤, 主程序不再重复)
  → 移动止损/止盈也过滤(GCC-0194, 不再豁免)
  → 发单
  ※ L1/L2主信号为参考模式(不发单)
  ※ GCC-0194: N-Gate/HOLD_BAND/signal_gate已从主程序移除

管线B: Vision统一 (原BrooksVision+Vision合并) [GCC-0194重构]
  → 单次GPT调用: 8种Vision形态 + 21种Brooks形态 统一识别
  → 自带过滤 (EMA10+RSI+L2对比+每日限1买1卖)
  → 豁免 FilterChain (自己过滤自己=循环)
  → 发单
  ※ Vision+BrooksVision合并消除重复API调用

管线C: L2 MACD背离 (兜底震荡) [GCC-0173审计]
  → 10分钟周期底/顶背离检测
  → 独立触发, 绕过L2 Gate
  → 日志双通道: logger + log_to_server
  → 发单
  ※ 趋势行情有B覆盖, 震荡行情有C覆盖

设计理念: 趋势判断准确率~50%是市场本质, 不追求判更准,
而是用三线互补确保趋势/震荡都有独立信号源覆盖。
GCC-0194核心变更: L1趋势与外挂解耦, 外挂不依赖趋势方向判断。
```

---

## L2五大类评分 (v3.500)

| 类别 | 范围 | 说明 |
|------|------|------|
| 形态分 | ±6 | PA+2B+123 |
| 位置分 | ±4 | 通道位置 |
| 量能分 | ±2 | 成交量 |
| Wyckoff策略分 | ±2 | 阶段×形态 |
| 每日偏向分 | ±2 | 复盘设置的方向 |
| **总分** | **±16** | STRONG阈值±8 |

> v3.500移除唐纳奇通道分(±3)，与位置分重复计算pos_in_channel

---

## 版本更新

### GCC-0194 L1趋势与外挂解耦 + Vision统一 (2026-03-01)

**核心变更**: L1趋势判断不再影响外挂触发，外挂独立运行。

| 变更 | 旧 | 新 |
|------|-----|-----|
| x4大周期判定 | 5模块投票+缠论vs道氏竞争 | EMA(7/14/20)三线排列 |
| 共识度权重 | Vision35%+x4_30%+current20%+ST15% | 全部归零(外挂不需要趋势过滤) |
| Vision+BrooksVision | 两个独立GPT调用 | 单次GPT调用统一架构(v3.5) |
| 主程序过滤 | N-Gate/HOLD_BAND/signal_gate/FilterChain 4层 | 全部移除(扫描引擎统一) |
| FilterChain豁免 | 移动止损/止盈豁免 | 不再豁免, BrooksVision/VisionPattern/双底双顶豁免 |
| Rob Hoffman | 暂停(v21起) | v2.0.1恢复运行 |
| 仓位控制(v21.32) | BUY需current=UP, SELL需current=DOWN | 取消趋势限制, 仅保留EMA过滤 |

**GCC-0174 知识卡活化**:
- CardBridge: 查询+激活记录+蒸馏(confidence/quality自动更新)
- KNN闭环: 知识卡准确率→评分→回写卡片→JSONL日志
- 因果记忆检索: arXiv:2601.11958 Layer B概念

---

### v5.640 缠论K线合并+三段判定 (2026-02-08)

**背景**: 传统趋势判定需要等待当前周期K线收盘，无法提前捕捉趋势变化。

**解决方案**: 使用子周期K线(1H)提前判断当前周期(4H)的趋势变化

**核心模块**: `trend_8bar.py`

| 组件 | 功能 | 说明 |
|------|------|------|
| `merge(highs, lows)` | 缠论K线合并 | 处理包含关系，合并高低点 |
| `judge(highs, lows)` | 三段判定 | 4条件判断趋势: 底底高+顶顶高=上涨 |
| `TrendDetector` | 趋势检测器 | 用8根子K线(前两根当前周期)判定 |
| `_find_sub_timeframe()` | 子周期查找 | 自动选择最优子周期数据源 |

**三段判定逻辑**:
```
4个条件:
  底2>底1  底3>底2  顶2>顶1  顶3>顶2

判定:
  4/4满足 → 强趋势 (UP/DOWN)
  3/4满足 → 弱趋势 (WEAK_UP/WEAK_DOWN)
  其余    → 震荡 (SIDE)
```

**趋势状态定义**:
| 状态 | 值 | 方向 |
|------|------|------|
| UP | "up" | +1 |
| WEAK_UP | "weak_up" | +1 |
| SIDE | "side" | 0 |
| WEAK_DOWN | "weak_down" | -1 |
| DOWN | "down" | -1 |

**子周期配置** (`_find_sub_timeframe`):
```python
# 规则:
# 1. 理想子周期 = 当前周期 / 4 (4H→1H)
# 2. 窗口 = 12根子K线 = 3个当前周期K线
# 3. 保证三段判定有足够数据

# 示例:
# 4H周期 → 1H子周期, 12根1H
# 2H周期 → 30m子周期, 12根30m
```

**优势**:
| 对比项 | 传统方法 | 缠论三段判定 |
|--------|----------|--------------|
| 判定时机 | 等当前K线收盘 | 提前1-2根K线 |
| 数据源 | 当前周期 | 子周期合并 |
| 抗噪能力 | 一般 | 强(包含关系处理) |
| 趋势分级 | 仅方向 | 强/弱/震荡 |

**关键文件**:
- `trend_8bar.py` - 缠论K线合并+三段判定模块
- `llm_server_v3640.py` - 主程序集成(第46行导入)

**验证命令**:
```bash
# 运行独立测试
python trend_8bar.py

# 检查导入
grep "trend_8bar" llm_server_v3640.py

# 预期输出:
# from trend_8bar import merge as chantheory_merge, judge as chantheory_judge, Trend as ChanTrend
```

---

### v5.540 趋势同步 + 智能选股 (2026-01-24)

**趋势转折同步** (sync_trend_to_scan_engine_v3540):
| 触发条件 | 行为 | 持久化 |
|----------|------|--------|
| L1 big_trend 变化 | HTTP通知扫描引擎 | global_trend_state.json |
| 程序启动 | L1刷新后同步趋势 | 自动加载 |
| 趋势→震荡 | 外挂切换策略 | 实时响应 |

**智能选股** (Paper Trading Enhanced):
| 功能 | 描述 |
|------|------|
| 🔍 搜索 | 按股票代码/名称实时过滤 |
| 📊 板块 | Tech/AI/Chips/EV/Finance/Mining/China |
| 🎯 快选 | 一键筛选板块股票 |

**L2评分体系更新** (5大类±22):
| 类别 | 范围 | 说明 |
|------|------|------|
| 形态分 | ±6 | PA+2B+123+K线 |
| 唐纳奇综合分 | ±8 | 位置±4+模式±3+验证±1 |
| 量能分 | ±2 | 成交量确认 |
| Wyckoff分 | ±2 | 阶段×形态 |
| 每日偏向 | ±2 | 当前周期趋势 |
| Vegas隧道 | ±2 | EMA 144/169位置 |
| **总分** | **±22** | **STRONG≥10/BUY≥6** |

---

### v3.499 每日偏向过滤 (2026-01-23)

**P0层过滤** (硬过滤):
| 每日偏向 | P0信号 | 执行 |
|----------|--------|------|
| UP | BUY | ✅ 执行 |
| UP | SELL | ❌ 拒绝 |
| DOWN | SELL | ✅ 执行 |
| DOWN | BUY | ❌ 拒绝 |
| SIDE | 任何 | ✅ 执行 |

**L2层评分** (软评分±2):
| 每日偏向 | 信号方向 | 评分调整 |
|----------|----------|----------|
| UP | BUY | +2 顺势 |
| UP | SELL | -2 逆势 |
| DOWN | SELL | +2 顺势 |
| DOWN | BUY | -2 逆势 |
| SIDE | 任何 | 0 无调整 |

**生效条件**: 仅当手动设置(from_file=true) + 日期=今天时生效，次日自动失效

### v3.498 HOLD时门卫开放 (2026-01-22)

| 大周期 | 小周期 | 门卫行为 |
|--------|--------|----------|
| HOLD | BUY/STRONG_BUY | 放行买入 (L1外挂决策) |
| HOLD | SELL/STRONG_SELL | 放行卖出 (L1外挂决策) |
| HOLD | 其他 | 等待 |

**设计理由**: L1外挂有自己的趋势过滤逻辑，震荡可能变趋势

### v3.497 美股成本价格高抛低吸 (2026-01-22)

| 当前价格 vs 成本 | 市场位置 | 评分调整 |
|------------------|----------|----------|
| 浮亏 | 低位 <30% | +1 加仓 |
| 浮亏 | 高位 >70% | -1 止损 |
| 浮盈 | 高位 >70% | -1 锁利 |

**函数**: `get_avg_cost_price()`, `get_cost_reduction_score_adj()`

---

## 核心职责

1. **主程序文档更新**: 更新 `.GCC/skill/SKILL.md` - 主程序功能说明
2. **云端程序文档更新**: 更新 `AI Pro/v5.465/SKILL.md` - 云端程序功能说明
3. **版本同步**: 确保主程序版本(v3.xxx)与云端版本(v5.xxx)文档同步

## Overview

An intelligent trading system combining AI prediction, human knowledge rules, and technical indicators through a **6-layer decision priority framework** with **three-party consensus voting**.

---

## v3.496 Core Features (美股盈亏动态策略调整)

### Background
1月美股累计亏损较大，需要根据每只股票的盈亏状态动态调整交易策略，对亏损股票加强高抛低吸。

### Problem
- 当前策略对所有股票一视同仁
- 亏损严重的股票仍可能在高位买入，加剧亏损
- 需要根据盈亏级别自动调整策略激进程度

### Solution: 盈亏级别动态策略

**新增函数**:
- `get_pnl_level(symbol)`: 计算盈亏级别 (normal/warning/severe)
- `get_max_position_units(symbol)`: 获取最大仓位单位

**策略分级**:

| 级别 | 亏损范围 | Wyckoff覆盖 | L2评分调整 | 仓位上限 |
|------|----------|-------------|-----------|----------|
| **normal** | <20% | 无覆盖 | 高位>70%额外-1分 | 2单位 |
| **warning** | 20-35% | 强制高抛低吸 | 无 | 2单位 |
| **severe** | >35% | 仅允许低位(<30%)买入 | 无 | 1单位 |

**Wyckoff阶段覆盖逻辑**:
```python
if pnl_level == "severe":
    # 只允许低位买入
    if pos_in_channel < 0.30:
        raw_phase = "ACCUMULATION"
    else:
        raw_phase = "DISTRIBUTION"  # 强制减仓

elif pnl_level == "warning":
    # 强制高抛低吸，忽略L1趋势
    if pos_in_channel < 0.30:
        raw_phase = "ACCUMULATION"
    elif pos_in_channel > 0.70:
        raw_phase = "DISTRIBUTION"
    else:
        raw_phase = "RANGING"
```

---

## v3.495 Core Features (MACD背离外挂)

### Background
基于知识卡片"93%胜率半木夏策略"，新增MACD背离策略外挂。

### Features
- MACD(13,34,9)背离检测（底背离/顶背离）
- 关键K线识别（MACD柱子颜色变化）
- ATR(13)止损 + 1:1.5盈亏比止盈
- L1趋势过滤（UP→只做底背离，DOWN→只做顶背离）
- ⭐绕过L2 Gate限制，不需要大周期STRONG信号

---

## v3.466 Core Features (TradingView信号数据增强)

### Background
原始TradingView Pine Script v2仅发送基础信号和120根K线数组，但由于Pine Script字符串变量限制(4096字符)，无法传输完整OHLCV数组。
系统已有Coinbase/yfinance预加载的历史OHLCV数据，因此改为传输丰富的实时技术指标。

### Problem
- Pine Script字符串变量限制4096字符，无法传输120根完整OHLCV
- 原v2只传输基础Donchian突破信号，缺少技术指标细节
- 主程序需要更多实时指标来增强决策质量

### Solution: Pine Script v3 信号数据增强

**文件**: `skill/AI_Donchian_LLM_Signal_v3.txt`

**传输字段汇总**:

| 类别 | 字段 | 说明 |
|------|------|------|
| **Donchian通道** | donchian_upper, donchian_lower, donchian_basis | 锁定的上一根K线通道值 |
| **位置指标** | pos_in_channel | 价格在通道中的位置(0-100%) |
| **OHLCV** | open, high, low, close, volume | 当前K线完整数据 |
| **RSI/ATR** | rsi14, atr14 | 相对强弱+真实波幅 |
| **EMA20** | ema20, ema_trend, price_above_ema | 均线值+趋势方向+价格位置 |
| **MACD** | macd_line, macd_signal, macd_hist, macd_trend | MACD(12,26,9)完整数据 |
| **MACD交叉** | macd_cross_over, macd_cross_under | 金叉/死叉信号 |
| **布林带** | bb_upper, bb_lower, bb_basis | 布林带(20,2σ)三轨 |
| **布林指标** | bb_width_pct, pos_in_bb, bb_squeeze | 宽度百分比+位置+挤压信号 |
| **成交量** | vol_ratio | 当前成交量/20日均量 |
| **突破信号** | signal, level | cross_over/cross_under + upper/basis/lower |
| **PA边界** | pa_buy_edge, pa_sell_edge | 价格行为买卖边界 |

### JSON数据示例

```json
{
  "symbol": "BTCUSDC",
  "timeframe": "240",
  "time_ms": 1737100800000,
  "signal": "cross_over",
  "level": "basis",
  "pa_buy_edge": true,
  "pa_sell_edge": false,
  "donchian_upper": 105000.0,
  "donchian_lower": 98000.0,
  "donchian_basis": 101500.0,
  "pos_in_channel": 65.5,
  "rsi14": 58.32,
  "atr14": 1250.5,
  "ema20": 101200.0,
  "ema_trend": "up",
  "price_above_ema": true,
  "macd_line": 850.5,
  "macd_signal": 720.3,
  "macd_hist": 130.2,
  "macd_trend": "bullish",
  "macd_cross_over": false,
  "macd_cross_under": false,
  "bb_upper": 103500.0,
  "bb_lower": 99000.0,
  "bb_basis": 101250.0,
  "bb_width_pct": 4.45,
  "pos_in_bb": 72.3,
  "bb_squeeze": false,
  "vol_ratio": 1.35,
  "open": 100500.0,
  "high": 102800.0,
  "low": 100200.0,
  "close": 102500.0,
  "volume": 15000000
}
```

### 技术指标计算逻辑

**1. EMA20趋势判断**:
```pine
emaSlope = ema20 - ema20[3]
emaTrend = emaSlope > 0 ? "up" : emaSlope < 0 ? "down" : "flat"
```

**2. 布林带挤压检测**:
```pine
bbWidthSma = ta.sma(bbWidth, 20)
bbSqueeze = bbWidth < bbWidthSma * 0.8  // 宽度<80%均值=挤压
```

**3. 位置计算**:
```pine
posInChannel = ((close - lowerPrev) / dcRange) * 100  // 0-100%
posInBB = ((close - bbLower) / bbWidth) * 100         // 0-100%
```

### Key Files
- `skill/AI_Donchian_LLM_Signal_v3.txt` - Pine Script v3源码
- `llm_server_v3466.py` - 主程序解析新字段

### Verification
```bash
# 检查TradingView推送的新字段
grep "macd_line\|bb_squeeze\|ema_trend" logs/server.log | tail -10

# 预期输出:
# [v3.466] BTCUSDC: TV信号 macd_trend=bullish, bb_squeeze=false, ema_trend=up
```

---

## v3.465 Core Features (P1改善项 - 云端增强)

### Background
云端v5.465版本新增L2信号质量增强功能，通过三个P1级别的改善项提升交易信号准确性。

### P1-1: 20 EMA趋势过滤器

**函数**: `analyze_ema20_trend(ohlcv_data, window=20)`

```python
# 趋势判断
价格 > 20 EMA + EMA斜率向上  → BULLISH
价格 < 20 EMA + EMA斜率向下  → BEARISH
其他情况                      → NEUTRAL

# 回调信号
价格接近EMA(±1%) + 趋势明确 → pullback_signal=True
```

**评分规则**:
| 条件 | 分数 |
|------|------|
| BULLISH + 回调信号 | +1.5 |
| BULLISH 无回调 | +0.5 |
| BEARISH + 回调信号 | -1.5 |
| BEARISH 无回调 | -0.5 |
| NEUTRAL | 0 |

### P1-2: Power Candle力量K线检测

**函数**: `detect_power_candle(ohlcv_data)`

```python
# 力量K线条件
Bullish Power: HIGH=CLOSE + 上影线<5% + 实体>=60%
Bearish Power: LOW=CLOSE + 下影线<5% + 实体>=60%

# 强度等级
实体60-70% = 1级
实体70-80% = 2级
实体80%+   = 3级
```

**评分规则**: ±0.5(1级) / ±1.0(2级) / ±1.5(3级)

### P1-3: 量堆式拉升检测

**函数**: `detect_volume_heap_rally(ohlcv_data, lookback=10)`

```python
# 量堆条件
连续3根以上K线 成交量 > 平均成交量×1.2

# 动能强度
3-4根  = MODERATE
5-6根  = STRONG
7根+   = VERY_STRONG

# 脉冲量警告
单根成交量 >= 平均×3 → pulse_volume_warning=True (可能陷阱)
```

**评分规则**: MODERATE(±0.5) / STRONG(±1.0) / VERY_STRONG(±1.5)

### Key Files
- `llm_server_v3465.py` - 主程序
- `monitor_v3465.py` - 监控程序 (P1告警显示)
- `AI Pro/v5.465/core/l2_analysis.py` - 云端L2分析模块

### Verification
```bash
# 检测P1改善项
grep "v5.465.*EMA20\|Power Candle\|Volume Heap" logs/server.log | tail -10

# 监控程序告警面板显示:
# - 📈 回调信号 bias=BULLISH/BEARISH
# - 💪 力量K线 BULLISH/BEARISH L2/L3
# - 📊 量堆拉升 STRONG/VERY_STRONG
# - ⚠️ 脉冲量警告 (可能陷阱)
```

---

## v3.460 Core Features (L2大小周期门卫机制)

### Background
当L2大周期出现STRONG_BUY/STRONG_SELL信号时，这是高置信度的交易方向信号。但直接在大周期收盘价进场可能不是最佳时机，需要在小周期找到精准进场点。

### Problem
- 大周期STRONG信号是高置信方向
- 直接进场时机可能不是最优
- 需要小周期确认后再进场

### Solution: L2门卫机制

**1. 大周期门卫** (`update_l2_big_cycle_decision`):
- 只有大周期=STRONG_BUY时，才允许小周期买入
- 只有大周期=STRONG_SELL时，才允许小周期卖出
- 每次大周期信号更新时重置小周期状态

**2. 小周期评分** (`compute_l2_small_cycle_decision`):
```python
# 简化版评分 (-5 ~ +5)
# K线形态分: -1 ~ +1 (大阳/锤子+1, 大阴/射击星-1)
# RSI位置分: -2 ~ +2 (超卖+2, 超买-2)
# 动量分: -2 ~ +2 (上涨放量+2, 下跌放量-2)

# 阈值
# score >= 3 → STRONG_BUY
# score >= 2 → BUY
# score <= -3 → STRONG_SELL
# score <= -2 → SELL
```

**3. 门卫检查** (`check_l2_gate`):
```
大周期STRONG_BUY + 小周期BUY/STRONG_BUY → 允许买入
大周期STRONG_SELL + 小周期SELL/STRONG_SELL → 允许卖出
其他情况 → 拒绝交易
```

**4. 冻结机制** (`mark_l2_small_cycle_traded`):
- 交易后立即冻结
- 直到下一个大周期信号才解冻
- 防止同一大周期内重复交易

### Key Files
- `llm_server_v3460.py` - 主程序 (L2门卫机制)
- `monitor_v3460.py` - 监控程序 (显示门卫状态)
- `l2_gate_state.json` - 门卫状态持久化

### Verification
```bash
# 查看L2门卫日志
grep "v3.460" logs/server.log | grep "L2 Gate" | tail -10

# 检查门卫状态文件
cat l2_gate_state.json

# 监控程序会在告警面板显示:
# - 🚪 允许买入/卖出 (门卫开放)
# - 🔒 已冻结 (等待下一大周期)
# - ⏳ 等待小周期 (大周期STRONG但小周期未满足)
```

---

## v3.455 Core Features (L2评分重构)

### Background
L2评分系统原始设计最大分数22分，STRONG阈值为±6分，这意味着仅需达到27%即可触发STRONG信号。
新增K线形态评分后，这个问题会更加严重。

### Problem
- 原始评分范围太大 (±22分)，导致STRONG阈值(±6)门槛过低
- 新增评分项时分数会持续膨胀
- STRONG_BUY/STRONG_SELL触发过于容易

### Solution: 评分压缩 + K线形态分

**1. 新增K线形态评分** (`compute_candle_shape_score`):
```python
def compute_candle_shape_score(bar: dict) -> tuple:
    """
    返回: (score, shape_name)
    +1.0: 大阳线(实体≥70%) / 锤子线
    +0.5: 普通阳线(30%<实体<70%)
     0.0: 十字星/纺锤(实体≤30%)
    -0.5: 普通阴线
    -1.0: 大阴线(实体≥70%) / 射击之星
    """
```

**2. 评分权重压缩**:
| 评分项 | 原范围 | 新范围 |
|--------|--------|--------|
| Position | ±3 | ±2 |
| Pattern (PA/2B/123) | ±6+ | ±3 (封顶) |
| K线形态 (新增) | - | ±1 |
| Volume | ±2 | ±1 |
| Trend | ±3 | ±2 |
| Regime | ±3 | ±1 |
| Volume Penalty | ±3 | ±1 |
| Divergence | ±3 | ±1 |
| Extreme Volume | ±2 | ±1 |

**3. 最终范围**: -12 ~ +12
**4. STRONG阈值**: ≥6 / ≤-6 = 需要50%（原27%）

### Verification
```bash
# 检查邮件L2评分显示是否包含K线形态
# L2 结构分析 (v3.455) 区块应显示:
# - K线形态: STRONG_BULL/BULL/DOJI/BEAR/STRONG_BEAR
# - 得分: +1.0 / +0.5 / 0.0 / -0.5 / -1.0
```

---

## v5.455 Cloud Features (i18n Analysis Result Translation)

### Background
云端程序需要支持EN/ZH语言切换。用户选择EN时显示英文，选择ZH时显示中文。
之前把所有中文改成英文是错误的做法，应该根据语言设置动态切换。

### Problem
- 分析结果中的shape/state/warning/reason等字段需要根据语言切换
- Logger日志和用户可见输出需要分开处理
- Logger保持英文(开发调试)，用户可见数据根据语言切换

### Solution: i18n Translation Layer

**1. 新增翻译键值** (`web/i18n.py`):
```python
# K-line Shapes
"shape_HAMMER": "Hammer" / "锤子线"
"shape_SHOOTING_STAR": "Shooting Star" / "射击之星"
"shape_STRONG_BULL": "Strong Bull" / "大阳线"
"shape_STRONG_BEAR": "Strong Bear" / "大阴线"

# Form-Spirit States
"fs_FORM_SPIRIT_BALANCED": "Form-Spirit Balanced" / "形神兼备"
"fs_FORM_SCATTERED_SPIRIT_FOCUSED": "Form Scattered, Spirit Focused" / "形散神聚"

# MACD Divergence
"macd_bearish_div": "Bearish divergence" / "顶背驰"
"macd_bullish_div": "Bullish divergence" / "底背驰"

# Signal Reasons
"reason_uptrend_pullback_buy": "Uptrend pullback buy" / "上涨趋势回调买入"
"reason_ranging_high_sell": "Ranging high sell" / "震荡高位卖出"
```

**2. 翻译函数** (`translate_analysis_result`):
```python
def translate_analysis_result(result: Dict, lang: str = "en") -> Dict:
    """
    v5.455: Translate analysis result fields based on language setting.

    Translates:
    - L2 candle_shape, form_spirit state/warning, macd_divergence warning
    - L1 macd_divergence warning
    - Main reason field
    """
    if lang == "en":
        return result  # English is default, no translation

    # Translate L2/L1/reason fields for ZH...
```

**3. Routes Integration**:
```python
# /api/analyze endpoint
lang = get_lang()  # from cookie
translated_result = translate_analysis_result(result, lang)
return jsonify({"success": True, "result": translated_result})
```

### Data Flow

```
分析引擎(EN key) → translate_analysis_result(lang) → 前端显示
                              ↓
                   EN: "Uptrend pullback buy"
                   ZH: "上涨趋势回调买入"
```

### Key Files Modified
| File | Changes |
|------|---------|
| `web/i18n.py` | +150行翻译键值 + translate_analysis_result()函数 |
| `web/routes.py` | 导入翻译函数，/api/analyze返回前调用 |
| `web/__init__.py` | 导出translate_analysis_result |
| `core/*.py` | Logger消息改英文(开发日志) |
| `data/*.py` | Logger消息改英文(开发日志) |

### Verification
```bash
# Test EN mode
curl -b "lang=en" http://localhost:5000/api/analyze -d '{"symbol":"BTC"}'
# Expected: "reason": "Uptrend pullback buy"

# Test ZH mode
curl -b "lang=zh" http://localhost:5000/api/analyze -d '{"symbol":"BTC"}'
# Expected: "reason": "上涨趋势回调买入"
```

---

## v5.455 Cloud Features (L1/L2 Decision Display)

### Background
云端仪表盘L1 TREND和L2 SIGNAL区域需要更直观显示最终决定，让用户一眼看出L1和L2各自的判断结果。

### Problem
- L1区域只显示Direction/Strength，没有直观的最终决定(STRONG BUY/BUY/HOLD/SELL/STRONG SELL)
- L2区域Signal显示简单的BUY/SELL/HOLD，没有区分强度
- 用户需要额外思考才能得出L1/L2的综合判断

### Solution: L1/L2 Decision Calculation

**1. L1 Decision 计算** (`_calculate_l1_decision`):
```python
def _calculate_l1_decision(self, l1: Dict) -> str:
    """
    Logic:
    - UP + STRONG → STRONG BUY
    - UP + MODERATE → BUY
    - UP + WEAK → HOLD (weak trend, no action)
    - DOWN + STRONG → STRONG SELL
    - DOWN + MODERATE → SELL
    - DOWN + WEAK → HOLD
    - SIDE → HOLD
    """
```

**2. L2 Decision 计算** (`_calculate_l2_decision`):
```python
def _calculate_l2_decision(self, l2: Dict) -> str:
    """
    Logic (v5.455 score range: -12 ~ +12):
    - BUY + score >= 6 (50% threshold) → STRONG BUY
    - BUY → BUY
    - SELL + score <= -6 → STRONG SELL
    - SELL → SELL
    - HOLD → HOLD
    """
```

**3. 前端显示** (`dashboard.html`):
```javascript
// v5.455: Get CSS class for decision display
function getDecisionClass(decision) {
    if (!decision) return '';
    const d = decision.toUpperCase();
    if (d.includes('BUY')) return 'signal-buy';   // green
    if (d.includes('SELL')) return 'signal-sell'; // red
    return '';  // HOLD has no special color
}
```

### New Layout
```
L1 TREND                    L2 SIGNAL
─────────────────           ─────────────────
Decision   STRONG BUY       Decision   BUY
Direction  UP               Score      4.5
Strength   STRONG           RSI        35.2
ADX        28.5             Volume     1.8x
Dow Theory UP               Pattern    ...
```

### Key Files Modified
| File | Changes |
|------|---------|
| `core/signal_generator.py` | +`_calculate_l1_decision()` +`_calculate_l2_decision()` |
| `web/templates/dashboard.html` | L1/L2第一行显示Decision + `getDecisionClass()`函数 |
| `web/i18n.py` | 添加"decision"翻译键 (EN/ZH) |

### Verification
```bash
# 运行分析后检查返回数据
curl http://localhost:5000/api/analyze -d '{"symbol":"TSLA","type":"stock"}'
# Expected: result.l1.decision = "STRONG BUY" / "BUY" / "HOLD" / "SELL" / "STRONG SELL"
# Expected: result.l2.decision = "STRONG BUY" / "BUY" / "HOLD" / "SELL" / "STRONG SELL"
```

---

## v3.450 Core Features (P0-CycleSwitch)

### Background
当用户在TradingView调整交易周期(如从1h改为4h)时，系统需要等待下次大周期收盘才能得到新周期的分析结果。
这段时间内(可能长达4小时)用户没有交易建议。

### Problem
- 周期切换后，旧周期的K线缓存被清空
- 新周期缓存为空，触发预加载(Coinbase/yfinance)
- 但预加载完成后没有立即分析，需等待下次TradingView推送
- 用户在等待期间没有任何交易指导

### Solution: P0-CycleSwitch Plugin

```python
def _trigger_single_preload(symbol: str, timeframe: int):
    """v3.450: 单品种预加载 + P0-CycleSwitch完整分析"""
    def _preload_thread():
        # 1. 预加载OHLCV数据
        _preload_single_symbol(symbol, timeframe)

        # 2. v3.450 P0-CycleSwitch: 预加载完成后立即运行完整分析
        _run_cycle_switch_analysis(symbol, timeframe)

def _run_cycle_switch_analysis(symbol: str, timeframe: int):
    """
    v3.450 P0-CycleSwitch: 周期切换后立即运行完整三方协商分析

    流程:
    1. 获取预加载的OHLCV数据
    2. 计算Tech信号 (ADX/MACD/RSI)
    3. 计算Human信号 (趋势/位置)
    4. 调用DeepSeek趋势仲裁
    5. 输出BUY/HOLD/SELL
    6. 正常交易执行
    7. 正常邮件通知
    """
```

### Data Flow

```
TradingView推送(新周期) → 检测周期切换 → 预加载OHLCV
                                          ↓
                              P0-CycleSwitch触发
                                          ↓
                              Tech+Human+DeepSeek分析
                                          ↓
                              BUY/HOLD/SELL → 正常交易 → 邮件通知
```

### Key Changes

| Component | Before (v3.446) | After (v3.450) |
|-----------|-----------------|----------------|
| 周期切换处理 | 仅预加载数据 | 预加载 + 完整分析 |
| 分析触发 | 等待下次TV推送 | 预加载后立即分析 |
| 交易执行 | 需等待 | 立即执行(正常流程) |
| 邮件通知 | 无 | 立即发送([P0-CycleSwitch]标识) |

### Email Format

- **普通通知**: `[P0-CycleSwitch] BTCUSDC 240min → BUY`
- **执行成功**: `⚡ [P0-CycleSwitch] BTCUSDC 240min → BUY ✅`

### Verification

```bash
# Check P0-CycleSwitch trigger
grep "P0-CycleSwitch" logs/server.log | tail -10

# Expected output:
# [v3.450] BTCUSDC: 检测到周期切换 60min → 240min
# [v3.450] BTCUSDC: 预加载完成，触发P0-CycleSwitch分析...
# [P0-CycleSwitch] BTCUSDC: 开始完整三方协商分析 (周期=240min)
# [P0-CycleSwitch] BTCUSDC: Tech信号=BUY, 趋势=UP, ADX=28.5
# [P0-CycleSwitch] BTCUSDC: DeepSeek仲裁=UP, 置信度=75%
# [P0-CycleSwitch] BTCUSDC: ✅ 买入成功! 新仓位=3
# [P0-CycleSwitch] BTCUSDC: 邮件通知已发送
```

### Key Files
- `llm_server_v3450.py:2503-2521` - `_trigger_single_preload`函数修改
- `llm_server_v3450.py:2527-2765` - `_run_cycle_switch_analysis`新函数

---

## v3.446 Core Features (Complete OHLCV from TradingView)

### Background
TradingView Pine Script sends complete OHLCV arrays (highs[], lows[], opens[], close_prices[], volumes[]) with 120 bars each cycle.
However, main program only used close_prices[], initializing O=H=L=C=close (fake data).

This caused:
- Inaccurate Dow Theory Swing Point detection (needs real High/Low)
- ATR calculation errors
- Pattern recognition issues (double bottom, head-shoulders, etc.)

### Solution: Direct Use of TradingView Complete OHLCV

```python
# v3.446: Parse complete OHLCV arrays from TradingView
tv_highs = data.get("highs", [])
tv_lows = data.get("lows", [])
tv_opens = data.get("opens", [])
tv_volumes = data.get("volumes", [])

# Build complete bars with real O/H/L/C/V
if has_complete_ohlcv:
    for i in range(len(close_prices)):
        bar = {
            "open": float(tv_opens[i]),
            "high": float(tv_highs[i]),
            "low": float(tv_lows[i]),
            "close": float(close_prices[i]),
            "volume": float(tv_volumes[i]),
        }
        tv_complete_bars.append(bar)

    # Replace OHLCVWindow cache with complete data
    ohlcv_window.clear()
    for bar in reversed(tv_complete_bars):
        ohlcv_window.append(bar)
```

### Key Changes

| Component | Before (v3.445) | After (v3.446) |
|-----------|-----------------|----------------|
| OHLCV Source | close_prices only | Complete highs/lows/opens/closes/volumes |
| Initial Data | O=H=L=C=close (fake) | Real OHLCV from TV |
| Cache Update | Accumulate bar-by-bar | Replace with 120 complete bars |
| Cycle Switch | Wait for accumulation | Instant - TV provides all data |

### Data Flow

```
TradingView推送 (每个大周期收盘)
    ↓
JSON: {
    "highs": [120个最高价],
    "lows": [120个最低价],
    "opens": [120个开盘价],
    "close_prices": [120个收盘价],
    "volumes": [120个成交量]
}
    ↓
v3.446解析完整数组
    ↓
构建120根真实OHLCV bars
    ↓
替换OHLCVWindow缓存
    ↓
道氏理论/ATR/形态识别使用真实数据
```

### Verification

```bash
# Check complete OHLCV parsing
grep "v3.446.*完整OHLCV" logs/server.log | tail -5

# Expected output:
# [v3.446] BTCUSDC: TradingView推送完整OHLCV数据 (120根)
# [v3.446] BTCUSDC: 使用TV完整OHLCV更新缓存 (120根)
# [v3.446] BTCUSDC: 样本K线 - O:42150.00 H:42380.00 L:42050.00 C:42250.00

# Check fallback mode (if TV data incomplete)
grep "回退模式" logs/server.log | tail -5
```

### New Method: OHLCVWindow.clear()

```python
class OHLCVWindow:
    def clear(self):
        """v3.446: Clear window data for replacement"""
        self.bars = []
        self.tv_signals = []
```

---

## v3.445 Core Features (Per-Symbol Timeframe Configuration)

### Background
All symbols were preloaded with the same MAIN_TIMEFRAME (default 30min).
Actual trading cycles differ:
- ZEC: 1 hour
- BTC/ETH/SOL: 2 hours
- US Stocks: 4 hours

This caused mixed-period K-lines in OHLCVWindow, affecting indicator accuracy.

### SYMBOL_TIMEFRAMES Configuration
```python
# Per-symbol timeframe (minutes)
SYMBOL_TIMEFRAMES = {
    # Crypto
    "ZECUSDC": 60,    # 1 hour
    "BTCUSDC": 120,   # 2 hours
    "ETHUSDC": 120,   # 2 hours
    "SOLUSDC": 120,   # 2 hours
    # US Stocks (4 hours)
    "TSLA": 240,
    "COIN": 240,
    "RDDT": 240,
    # ... more symbols
}

def get_symbol_timeframe(symbol: str) -> int:
    """v3.445: Get trading cycle for symbol (minutes)"""
    return SYMBOL_TIMEFRAMES.get(symbol, 60)  # default 1h
```

### Data Source Updates

**Coinbase API (Crypto)**:
```python
# Supports 2h granularity
if timeframe <= 60:
    granularity = 3600   # 1h
elif timeframe <= 120:
    granularity = 7200   # 2h (NEW)
else:
    granularity = 21600  # 6h
```

**yfinance (US Stocks)**:
```python
# Supports 2h/4h intervals
if timeframe <= 60:
    interval = "1h"
elif timeframe <= 120:
    interval = "2h"   # NEW
else:
    interval = "4h"   # NEW for US stocks
```

### Key Files
- `llm_server_v3445.py` - Main program with SYMBOL_TIMEFRAMES
- `monitor_v3445.py` - Dashboard synced to v3.445
- `AI Pro/v5.445/` - Cloud version synced

### Verification
```bash
# Check per-symbol timeframe preload
grep "v3.445.*周期" logs/server.log | tail -10

# Expected output:
# [v3.445] ZECUSDC: 周期=60min, granularity=3600s
# [v3.445] BTCUSDC: 周期=120min, granularity=7200s
# [v3.445] TSLA: yfinance interval=4h, period=30d
```

---

## v3.360 Core Features

### 飞云双突破独立外挂

**Problem:** L2同时处理K线形态和双突破打分，职责混杂。

**Solution:** 将双突破从L2移至独立外挂，L2专注K线形态分析：

```
┌─────────────────────────────────────────────────────────────────┐
│  v3.360 双外挂架构 (P0-Tracking一直运行，外挂是额外增强)         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  P0-Tracking (基础扫描) ─────────────────────────────────→ 执行 │
│       │                                                         │
│       ├─→ L1外挂 (趋势跟随)                                     │
│       │     条件: consensus=AGREE + direction=UP/DOWN           │
│       │     触发: UP+BUY / DOWN+SELL                            │
│       │                                                         │
│       └─→ 飞云外挂 (趋势捕捉) ← v3.360新增                       │
│             条件: is_double=True + L1趋势方向一致                │
│             触发: UP+DOUBLE_BREAK_BUY / DOWN+DOUBLE_BREAK_SELL  │
│                                                                 │
│  两个外挂独立检查，可同时激活(信号共振)                          │
│  震荡行情: 外挂不激活，仅P0执行                                  │
└─────────────────────────────────────────────────────────────────┘
```

### L2专注K线形态

| v3.350 | v3.360 |
|--------|--------|
| L2打分包含双突破 | 双突破移至飞云外挂 |
| K线+双突破混合 | **专注K线形态**(PA/2B/123/13买卖点) |

### state.json新增字段

```python
state[symbol]["feiyun_plugin_for_scan"] = {
    "signal": "DOUBLE_BREAK_BUY/SELL/NONE",  # 飞云双突破信号
    "is_double": True/False,                  # 是否双突破(趋势线+形态)
    "confidence": 0.0-1.0,                    # 信号置信度
    "trendline_break": {},                    # 趋势线突破详情
    "pattern_break": {},                      # 形态突破详情
    "volume_confirmed": True/False,           # 成交量确认
    "l1_direction": "UP/DOWN/SIDE",           # L1趋势方向
    "activate_feiyun_plugin": True/False,     # 是否激活飞云外挂
    "updated_at": "2026-01-10T..."            # 更新时间
}
```

### 双外挂激活条件矩阵

| L1趋势 | 飞云双突破 | L1外挂 | 飞云外挂 | 标签 |
|--------|-----------|--------|---------|------|
| UP(AGREE) | DOUBLE_BREAK_BUY | ✅ | ✅ | [L1+飞云激活] |
| UP(AGREE) | 无/其他 | ✅ | ❌ | [L1外挂激活] |
| DOWN(AGREE) | DOUBLE_BREAK_SELL | ✅ | ✅ | [L1+飞云激活] |
| DOWN(AGREE) | 无/其他 | ✅ | ❌ | [L1外挂激活] |
| SIDE | 任何 | ❌ | ❌ | [P0-Tracking] |

**v3.442核心变更**:
- SuperTrend外挂v0.8.4: **移除趋势限制**，趋势+震荡行情都能触发，仅保留位置过滤(>80%不买/<20%不卖)
- 飞云外挂: 仍需趋势行情+双突破+放量确认

### signal_data新增字段

```python
signal_data = {
    "signal": "BUY/SELL",
    "activate_l1_plugin": True/False,      # L1外挂激活标志
    "activate_feiyun_plugin": True/False,  # 飞云外挂激活标志 (v3.360新增)
    "l1_trend_direction": "BUY_ONLY/SELL_ONLY/None",
    "feiyun_signal": "DOUBLE_BREAK_BUY/SELL/None",  # v3.360新增
}
```

### Key Files Updated
- `llm_server_v3360.py` - 主程序，新增feiyun_plugin_for_scan写入，L2移除双突破
- `price_scan_engine_v11.py` - 扫描引擎v11.0，双外挂检查，函数重命名_should_activate_plugins
- `monitor_v3360.py` - 监控程序

**Verification:**
```bash
# Check 飞云外挂状态写入
grep "飞云外挂状态" logs/server.log | tail -5

# Check 飞云外挂激活
grep "飞云外挂激活" logs/scan_engine.log | tail -5

# Check L1+飞云双外挂激活
grep "L1外挂+飞云外挂" logs/scan_engine.log | tail -5

# Check P0-Tracking正常执行
grep "P0-Tracking" logs/scan_engine.log | tail -5
```

---

## v3.350 Core Features

### Human模块道氏理论增强

**Problem:** Human模块使用LLM主观判断(visual_slope)判断当前周期趋势，可能误判。

**Solution:** 使用道氏理论(Swing Point)客观判断当前周期趋势/震荡：

```
┌─────────────────────────────────────────────────────────────────┐
│  v3.350 Human模块道氏理论增强                                    │
├─────────────────────────────────────────────────────────────────┤
│  LLM主观判断:              道氏理论客观判断:                      │
│  visual_slope              compute_trend_dow_swing()            │
│  position_feel             从60根K线提取Swing Point              │
│  recent_impact             HH+HL=UP, LH+LL=DOWN, mixed=SIDE     │
├─────────────────────────────────────────────────────────────────┤
│  双重验证置信度提升:                                              │
│  道氏+LLM一致 → conf=0.85 (主趋势)                               │
│  道氏确认+企稳信号 → conf=0.80 (回调企稳)                         │
│  仅道氏确认 → conf=0.75                                          │
└─────────────────────────────────────────────────────────────────┘
```

**Human模块新增输出:**
```python
human_module = {
    "phase": "PULLBACK_STABILIZING",
    "confidence": 0.80,
    "reason": "大UP+道氏回调(LH+LL)+企稳信号 → 回调企稳",
    # v3.350新增
    "current_dow_regime": "TREND_DOWN",  # 道氏理论当前周期趋势
    "dow_trend": "down",                  # up/down/side
    "dow_pattern": "LH+LL",               # 道氏模式
}
```

### L1趋势条件激活扫描引擎

**Problem:** 扫描引擎P0-Tracking触发时不考虑L1趋势状态，震荡市被来回割。

**Solution:** P0-Tracking正常运行，触发时检查L1趋势状态(基于道氏理论)决定是否激活L1外挂：

```
扫描引擎一直运行
    ↓
P0-Tracking正常扫描 (持续工作)
    ↓
抓到触发点 (drawdown/rise超阈值)
    ↓
读取state.json的l1_trend_for_scan
    ↓
┌─────────────────────────────────────────────────────────────┐
│ UP趋势(consensus=AGREE) + BUY触发  → 激活L1外挂 + P0执行   │
│ DOWN趋势(consensus=AGREE) + SELL触发 → 激活L1外挂 + P0执行 │
│ 震荡/无趋势                         → 仅P0执行，不激活外挂  │
└─────────────────────────────────────────────────────────────┘
```

### state.json新增字段

```python
state[symbol]["l1_trend_for_scan"] = {
    "direction": "UP/DOWN/SIDE",         # 当前周期趋势方向(仅道氏理论)
    "trend_source": "DOW",               # 趋势来源(仅道氏理论，不回退LLM)
    "current_dow_regime": "TREND_UP/...",# 道氏理论判断(Swing Point)
    "dow_pattern": "HH+HL/LH+LL/mixed",  # 道氏模式
    "current_regime_llm": "TREND_UP/...",# LLM判断(仅对比用，不参与决策)
    "consensus": "AGREE/DISAGREE/...",   # AI+Tech一致性
    "l1_signal": "BUY/HOLD/SELL",        # L1最终信号
    "updated_at": "2026-01-10T..."       # 更新时间
}
```

**v3.350道氏理论增强**:
- `direction`仅使用道氏理论(Swing Point)判断，客观量化
- 道氏趋势UP: HH+HL (更高的高点+更高的低点)
- 道氏趋势DOWN: LH+LL (更低的高点+更低的低点)
- 道氏震荡: 方向不一致 (如HH+LL或LH+HL)
- **不回退LLM**: 道氏判断震荡就是震荡，不使用LLM主观判断覆盖

### signal_data新增字段

```python
signal_data = {
    "signal": "BUY/SELL",
    "activate_l1_plugin": True/False,  # L1外挂激活标志
    "l1_trend_direction": "BUY_ONLY/SELL_ONLY/None",
}
```

### Key Files (v3.350)
- `llm_server_v3350.py` - 主程序，L1计算后写入l1_trend_for_scan
- `price_scan_engine_v10.py` - 扫描引擎，读取L1趋势条件激活
- `monitor_v3350.py` - 监控程序

**Verification:**
```bash
# Check L1趋势状态写入
grep "L1趋势状态写入" logs/server.log | tail -5

# Check L1外挂激活
grep "L1外挂激活" logs/scan_engine.log | tail -5

# Check P0-Tracking正常执行
grep "P0-Tracking" logs/scan_engine.log | tail -5
```

---

## v3.340 Core Features

### L1-L2 Unified 5-Level Signal Format

| Layer | Old Format | New Format |
|-------|------------|------------|
| L1 | STRONG_BUY/WEAK_BUY/NEUTRAL/WEAK_SELL/STRONG_SELL | STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL |
| L2 | STRONG_BUY/BUY_OK/FORCE_HOLD/SELL_OK/STRONG_SELL | STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL |

### Monitor Panel Signal Abbreviations

| Signal | Abbrev | Color |
|--------|--------|-------|
| STRONG_BUY | 多 | Green |
| BUY | 买 | Green |
| HOLD | 平 | Yellow |
| SELL | 卖 | Red |
| STRONG_SELL | 空 | Red |

---

## v3.280 Core Features

### Swing Point道氏理论 - 摆动点识别

**Problem:** v3.260道氏理论要求连续3次HH+HL才判断为UP，但实际趋势常常是"阳线-盘整-阳线"的波浪式，中间的盘整会打断判断，导致明显趋势被误判为SIDE。

**Solution:** 使用Swing Point（摆动点）识别法，先找出真正的波峰波谷，再比较高低关系：

```python
# 摆动点识别逻辑
def find_swing_points(highs, lows, n=2):
    """
    摆动高点(Swing High): 左右各n根的High都比它低
    摆动低点(Swing Low): 左右各n根的Low都比它高
    """

# 示例:
# 原始K线:  10 12 11 11 13 12 14 13 13 15
#               ↑        ↑        ↑
#            Swing    Swing    Swing
#             High     High     High
# 摆动高点序列: 12 → 13 → 14 → 15 = HH = UP趋势
# (中间的盘整K线被自动过滤)
```

**新增函数:**
| 函数 | 用途 |
|------|------|
| `find_swing_points()` | 识别摆动高点和摆动低点 |
| `compute_trend_dow_swing()` | 基于摆动点的道氏理论判断 |

**回退机制:** 数据不足(<10根K线)时自动回退到v3.260逐K线比较

**Verification:**
```bash
# Check Swing Point detection
grep "v3.280 DOW-Swing" logs/server.log | tail -10

# Expected output:
# [v3.280 DOW-Swing] SH=3, SL=2 | Highs: 95000.00→96000.00, Lows: 93000.00→94000.00 → up (HH+HL)
```

### 外挂v0.8.2 - 放宽触发条件

**Problem:** 外挂已缓存BUY1信号，但因Regime=RANGING被过滤（使用=NONE），导致信号被忽略。

**Solution:** 放宽触发条件，满足以下任一即可触发：

| # | 条件 | 说明 |
|---|------|------|
| 1 | Regime=TRENDING | 直接允许 |
| 2 | trend_state=STRONG_UP/DOWN | 直接允许 |
| 3 | L1有TRENDING投票 + 方向不冲突 | BUY1配UP/SIDE，SELL1配DOWN/SIDE |
| 4 | 位置极端 | BUY1: pos<35%, SELL1: pos>65% |

**修改文件:**
- `llm_server_v3280.py`: 添加L1 regime votes到market_data_for_plugin
- `supertrend_plugin_v08.py`: v0.8.2 `_apply_trend_filter()` 放宽逻辑

**Verification:**
```bash
# Check plugin trigger with relaxed conditions
grep "外挂触发\|L1有TRENDING投票\|低位触发\|高位触发" logs/server.log | tail -10

# Expected output:
# [SuperTrend] ZECUSDC: 外挂触发! BUY1 | L1有TRENDING投票(Human)+方向不冲突 | regime=RANGING...
```

---

## v3.271 Core Features

### Human Module Dow Theory Integration

**Problem:** Human module's `visual_slope` used independent `compute_visual_slope_v2900()`, not aligned with Dow Theory used elsewhere.

**Solution:** Pass `dow_trend_details` to Human module and use Dow Theory for trend judgment:

```python
# Data flow fixed:
llm_decide()
    ↓
compute_trend_dow() → trend_mid, trend_x4, trend_x8
    ↓
dow_trend_details = {
    "trend_mid": "up",      # NEW in v3.271
    "trend_x4": "up",
    "trend_x8": "side",
    "consensus": "up",      # 2/3 majority
}
    ↓
compute_human_signals_v2900(..., dow_trend_details)  # FIXED
    ↓
Dow Theory → visual_slope (STEEP_UP/UP/FLAT/DOWN/STEEP_DOWN)
```

**Conversion Logic:**
| Dow Theory | visual_slope |
|------------|--------------|
| mid=up, x4=up, x8=up | STEEP_UP (3-period consensus) |
| mid=up (others mixed) | UP |
| mid=down, x4=down, x8=down | STEEP_DOWN (3-period consensus) |
| mid=down (others mixed) | DOWN |
| mid=side | FLAT |

**Verification:**
```bash
# Check Dow→Human integration
grep "v3.270 DOW→Human" logs/server.log | tail -10

# Expected output:
# [v3.270 DOW→Human] 道氏理论趋势: mid=up, x4=up, x8=side → visual_slope=UP
```

---

## v3.260 Core Features

### DOW: Dow Theory Trend Detection

**Problem:** Slope + weighted_dr trend detection is slow to respond when market transitions from range to trend.

**Solution:** `compute_trend_dow()` - Dow Theory based algorithm:
- Uses only 4 bars (vs 120 for slope)
- Higher High + Higher Low (HH+HL) = UP trend
- Lower High + Lower Low (LH+LL) = DOWN trend
- Requires 3 consecutive confirmations

```python
def compute_trend_dow(highs, lows, n_bars=4):
    """
    - 3x HH+HL = UP (uptrend confirmed)
    - 3x LH+LL = DOWN (downtrend confirmed)
    - Otherwise = SIDE (ranging)
    """
```

**Improvement:**
| Metric | v3.250 (slope) | v3.260 (Dow) |
|--------|----------------|--------------|
| Bars needed | 120 | 4 |
| Trend detection | After 30-50% move | After 10-20% move |
| Range→Trend switch | Slow (avg drag) | Fast (4 bars) |

### Human Module Update

- Get highs/lows from `ohlcv_window.get_bars()`
- All timeframes (mid/x4/x8) use Dow Theory
- Fallback to v13 if insufficient data

### DeepSeek Module Update

- Dow Theory results added to arbitration prompt
- Dow Theory weight +40% in decision making
- **NEW: 道氏理论分歧触发仲裁** - 当道氏理论确认趋势(up/down)但有模块HOLD时，自动触发DeepSeek仲裁
- Example prompt section:
```
【v3.260 道氏理论判断 ⭐⭐⭐ 最重要】
- 当前周期: up (连续3次HH+HL)
- x4周期: up (连续3次HH+HL)
- x8周期: side (方向不一致)
- 综合判断: UP趋势共识
- 仲裁建议: 道氏理论确认上涨，BUY权重+40%，禁止SELL
```

### DeepSeek Arbitration Trigger Conditions

| # | Condition | Description |
|---|-----------|-------------|
| 1 | DIRECTION_CONFLICT | BUY vs SELL方向冲突 |
| 2 | CONFIDENCE_DIVERGENCE | 置信度分歧>0.4 |
| 3 | HIGH_CONF_HOLD_CONFLICT | 高置信度HOLD与其他方向冲突 |
| 4 | **DOW_TREND_DIVERGENCE** | 道氏理论确认趋势，但有模块HOLD (v3.260新增) |

---

## v3.250 Core Features

### Z1: ZEC-Specific L1 Algorithm

**Problem:** Standard L1 trend judgment (slope-based) doesn't work for high-volatility coins like ZEC.

**Solution:** `compute_trend_zec()` - ZEC-specific algorithm:
- 30-bar lookback (vs 120 for others)
- Price change percentage + momentum + position-in-range
- Thresholds: >5% = strong trend, 3-5% + momentum = trend

### P3: P0 Signal Deduplication

**Problem:** Duplicate P0 signals during US market open causing back-and-forth trading.

**Solution:** 60-second deduplication cache:
```python
_p0_signal_cache = {}  # {symbol_signal: timestamp}
_P0_DEDUP_SECONDS = 60
```

### L2-10m: US Stock Disable + Crypto 8h Freeze

**Problem:** US stock L2-10m (surge/crash triggers) causing over-trading.

**Solution:**
- Disable US stock L2-10m while keeping crypto
- Crypto L2-10m: 8-hour fixed freeze after trigger

---

## 核心检测目标 v3.260

### 目标1: L1大周期准确判断趋势vs震荡

**所有L1模块必须协同判断当前市场状态:**

| 模块 | 趋势判断依据 | 震荡判断依据 |
|------|-------------|-------------|
| **AI** | LLM分析多周期趋势一致性 | 多周期信号分歧 |
| **Human** | Swing Point道氏理论: 摆动点HH+HL | 摆动点方向不一致 |
| **Tech** | ADX>20 + DI方向明确 | ADX<20 + Chop>50 |
| **Grid** | PA形态确认趋势 | 无明确PA形态 |
| **DeepSeek** | 道氏理论+指标综合仲裁 | 仲裁建议观望 |

**检测命令:**
```bash
# 检查v3.280 Swing Point道氏理论判断日志
grep "v3.280 DOW-Swing" logs/server.log | tail -20

# 检查trend_state分布
grep -oP 'trend_state["\': ]+[A-Z_]+' logs/server.log | sort | uniq -c

# 预期: STRONG_UP/UP/DOWN/STRONG_DOWN应与实际行情匹配
```

### 目标2: L2遵守L1原则执行操作

| L1判断 | L2执行模式 | 具体规则 |
|--------|-----------|----------|
| **趋势(UP/DOWN)** | 顺大逆小 | Rule D: 禁止逆势操作 |
| **震荡(SIDE)** | 高抛低吸 | Rule E: 冷却期 + 区间操作 |

**趋势模式 - 顺大逆小:**
- trend_state=STRONG_UP/UP → 禁止SELL，只允许BUY/HOLD
- trend_state=STRONG_DOWN/DOWN → 禁止BUY，只允许SELL/HOLD

**震荡模式 - 高抛低吸:**
- trend_state=SIDE → 3小时冷却期
- 高位(pos_ratio>70%) → 倾向SELL
- 低位(pos_ratio<30%) → 倾向BUY

**检测命令:**
```bash
# Rule D顺大逆小
grep "规则D激活" logs/server.log | wc -l
grep "一致性规则D介入" logs/server.log | wc -l

# Rule E震荡冷却
grep "规则E激活" logs/server.log | wc -l
```

---

## Version History

| Version | Date | Core Updates |
|---------|------|--------------|
| **v3.466** | 2026-01-17 | TradingView信号数据增强: Pine Script v3新增Donchian实际值+MACD(12,26,9)+布林带(20,2σ)+EMA20趋势+RSI14+ATR14+位置指标+成交量比率，解决4096字符限制 |
| **v3.465** | 2026-01-17 | P1改善项(云端增强): 20 EMA趋势过滤器(回调信号检测)+Power Candle力量K线检测(强度1-3级)+量堆式拉升检测(脉冲量警告)+监控告警面板P1显示 |
| **v3.460** | 2026-01-17 | L2大小周期门卫机制: 大周期STRONG→小周期交易一次→冻结→等待下一大周期信号 |
| **v3.455** | 2026-01-16 | L2评分重构: 解决分数膨胀问题(原27%→新50%触发STRONG)，新增K线形态分(大阳/锤子/十字/阴线)，权重压缩(-12~+12) |
| **v3.450** | 2026-01-16 | P0-CycleSwitch: 周期切换立即完整分析(Tech+Human+DeepSeek)，正常交易+邮件通知，不等待下次TradingView推送 |
| **v3.446** | 2026-01-16 | 直接使用TradingView完整OHLCV: 解析highs/lows/opens/volumes数组，构建120根真实K线，解决O=H=L=C假数据问题，道氏理论/ATR/形态识别更准确 |
| **v3.445** | 2026-01-16 | 品种独立周期配置: SYMBOL_TIMEFRAMES字典定义每个品种交易周期(ZEC=1h,BTC/ETH/SOL=2h,美股=4h)，OHLCV缓存按symbol+timeframe分离 |
| v3.442 | 2026-01-16 | 加密货币专用ADX阈值(20 vs 美股25) + SuperTrend v0.8.4移除趋势限制 |
| **v3.350** | 2026-01-10 | L1趋势条件激活扫描引擎: P0-Tracking正常运行，触发时检查L1趋势，趋势+方向匹配时激活L1外挂 |
| v3.340 | 2026-01-10 | L1-L2统一5档信号格式 + 监控面板信号缩写(多/买/平/卖/空) |
| **v3.280** | 2026-01-08 | Swing Point道氏理论 + 外挂v0.8.2放宽触发条件(L1有TRENDING投票或极端位置即可触发) |
| v3.271 | 2026-01-08 | Human module uses Dow Theory for visual_slope; dow_trend_details adds trend_mid/x4/x8/consensus fields |
| v3.260 | 2026-01-08 | DOW: Dow Theory trend detection (HH/HL); Human module uses ohlcv_window; DeepSeek Dow Theory weight +40% |
| v3.250 | 2026-01-08 | Z1: ZEC-specific L1 algorithm; P3: P0 signal deduplication; L2-10m US stock disable; T6: compute_trend_v13 dynamic thresholds |
| v3.245 | 2026-01-07 | P0-1: tech_indicators data source fix; P0-2: trend_mid data source fix |
| v3.241 | 2026-01-07 | P0/P1 Improvement Tracking for all 5 modules |
| v3.240 | 2026-01-07 | L1 Trend Fix: Weighted Direction Ratio |
| v3.231 | 2026-01-07 | Fix KeyError: plugin_signal (decision dict complete) |
| v3.230 | 2026-01-07 | Rule D Fix + Rule E: SIDE Market Cooldown |
| v3.220 | 2026-01-06 | Rule D: Big Trend Protection |
| v3.210 | 2026-01-06 | L1 Plugin Module Fix |
| v3.200 | 2026-01-06 | L2 10m Auxiliary Layer Refactor |
| v3.170 | 2026-01-06 | AI Dynamic Confidence Voting |
| v3.165 | 2026-01-05 | L2 Consistency Protection Rules |

## v3.240 Core Fix: Weighted Direction Ratio

### Problem
Trend judgment too conservative - actual 3-5% decline judged as SIDE.

### Root Cause
`_dir_ratio` only counts bar count, not move magnitude:
- 1 big red bar (-2%) + 5 small green bars (+0.1%×5) = dr=0.83 → Wrong UP

### Solution (Scheme B)
1. **`_weighted_dir_ratio()`**: Weight by move magnitude
2. **`compute_trend_v12()`**: Dual-condition judgment
   - Slope > 0.3%: Direct trend (no dr needed)
   - Slope 0.1-0.3%: Use weighted_dr for confirmation

### Effect
- BTC 94k→91k (-3%) → Correctly judged as DOWN (was SIDE)
- Trend capture rate +20-30%

## 1. Core Architecture: 6-Layer Decision Framework

| Layer | Name | Description |
|-------|------|-------------|
| **P0** | System Protection | Circuit breaker, freeze mechanism |
| **P1** | Risk Control | Stop-loss, position limits |
| **P2** | Strategy Signals | L1 Three-Party, L2 Macro |
| **P3** | Optimize Adjust | Position sizing |
| **P4** | Monitor Alert | Dashboard, Email alerts |
| **RT** | Real-time Triggers | 10m surge/crash detection |

## 2. Three-Party Consensus Voting

| Party | Weight | Source |
|-------|--------|--------|
| **AI** | 35% | LLM + Multi-timeframe |
| **Human** | 35% | Rules + Dow Theory + Wyckoff |
| **Tech** | 30% | XGBoost + Indicators |

## 3. Trading Channels

- **Crypto**: 3Commas API -> Coinbase/Binance
- **US Stocks**: SignalStack -> Charles Schwab

## 4. Core Modules

- Dow Theory Trend Detection (v3.260)
- CNN Market Regime Detection
- Wyckoff Structure Analysis
- Position Sync & Protection
- P0 Scan Engine v10.0

## 5. Key Protection Rules

### Rule D - 顺大逆小 (Follow Big Trend)

| Condition | Action |
|-----------|--------|
| trend_state in {STRONG_UP, UP} | Prohibit SELL |
| trend_state in {STRONG_DOWN, DOWN} | Prohibit BUY |

### Rule E - SIDE Market Cooldown

| Condition | Action |
|-----------|--------|
| trend_state = SIDE | 3-hour cooldown between trades |

## 6. Key Files

| File | Description |
|------|-------------|
| llm_server_v3465.py | Main server (v3.465) - P1改善项(EMA20/PowerCandle/量堆) |
| monitor_v3465.py | Dashboard (v3.465) - P1告警面板显示 |
| AI Pro/v5.465/core/l2_analysis.py | 云端L2分析模块 - P1改善项实现 |
| price_scan_engine_v10.py | P0 Engine v10.0 - L1外挂条件激活 |
| l2_gate_state.json | L2门卫状态持久化 (v3.460) |
| l1_rule_tracker.py | Rule tracker |

## Related Documentation

- [architecture.md](architecture.md) - Full system architecture
- [functions.md](functions.md) - Core function reference
- [training.md](training.md) - Model training guide
- [troubleshooting.md](troubleshooting.md) - Common issues
- [deepseek.md](deepseek.md) - DeepSeek integration guide
