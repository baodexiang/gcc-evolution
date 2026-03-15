# AI Trading System B1通道交易规则完整审计报告
**日期: 2026-03-15 | 审计人: Claude Opus 4.6**

---

## 核心交易规则（审计标准）

1. 降低交易次数，宁可错过不乱进，只进趋势确认信号
2. 最大仓位5个
3. 趋势未完全确认：只建2个仓位
4. 回调不破趋势：加仓至5个
5. 回调出现：减仓至2个

---

## 执行摘要

| 规则 | 完成度 | 主要缺陷 | 优先级 |
|-----|--------|---------|--------|
| **规则1**: 降低交易次数 | ⭐⭐⭐⭐ (80%) | 无强制首次2单位 | P1 |
| **规则2**: 最大仓位5 | ⭐⭐⭐⭐⭐ (100%) | 无 | ✅ |
| **规则3**: 未确认建2 | ⭐⭐ (20%) | 无强制分层机制 | **P0** |
| **规则4**: 回调企稳加仓 | ⭐ (10%) | 完全缺失自动加仓 | **P0** |
| **规则5**: 回调进行减仓 | ⭐ (10%) | 完全缺失自动减仓 | **P0** |

---

## 第一部分: 信号/指标文件完整清单

### 1. 扫描引擎
| 属性 | 值 |
|------|-----|
| **文件路径** | `price_scan_engine_v21.py` (v21.22) |
| **功能** | P0-Tracking/P0-Open基础信号生成，15min外挂扫描调度 |
| **信号类型** | 趋势确认 + 过滤 |
| **预估频率** | 低频（每日配额制: BUY≤1次, SELL≤1次/品种） |
| **符合规则** | ✅规则1(配额制) ✅规则2(P2门控) ❌规则3-5(无分层加减仓) |

### 2. GCC-TM决策引擎
| 属性 | 值 |
|------|-----|
| **文件路径** | `gcc_trading_module.py` (v0.3) |
| **功能** | 树搜索+三视角验证，唯一下单决策源 |
| **信号类型** | 趋势确认 + 过滤 |
| **预估频率** | 中频（每30分钟一轮） |
| **符合规则** | ✅规则1(多层剪枝) ✅规则2(P2满仓禁BUY) ❌规则3(无首次建2) ❌规则4-5(无回调处理) |

### 3. Vision门控
| 属性 | 值 |
|------|-----|
| **文件路径** | `vision_analyzer.py` (v3.5) |
| **功能** | Claude/GPT-5.2图像识别，返回方向(UP/DOWN/SIDE) |
| **信号类型** | 过滤（门控，不推入信号池） |
| **预估频率** | 低频（每根4H K线一次） |
| **符合规则** | ✅规则1(仅门控不生成信号) |

### 4. N字门控
| 属性 | 值 |
|------|-----|
| **文件路径** | `n_structure.py` (v1.0) |
| **功能** | N字结构识别，5状态机(PERFECT_N/SHALLOW/DEEP_PULLBACK/SIDE/FAILED) |
| **信号类型** | 趋势确认 + 震荡 |
| **预估频率** | 低频（每品种每日≤1BUY+≤1SELL） |
| **符合规则** | ✅规则1(配额) ✅规则3部分(PERFECT_N=确认) |

### 5. Brooks Vision
| 属性 | 值 |
|------|-----|
| **文件路径** | `brooks_vision.py` |
| **功能** | Al Brooks价格行为分析，RADAR_PROMPT V2 |
| **信号类型** | 趋势确认 |
| **预估频率** | 低频（与Vision同步） |
| **符合规则** | ✅规则1 |

---

## 第二部分: _score_buy_candidate() / _score_sell_candidate() 调用链

```
gcc_observe(symbol, bars)
  → _init_candle_state()          # Stage 1: 4H三方投票锁方向
    → Vision + BrooksVision + prev_summary
    → effective_direction = BUY/SELL/HOLD
  → _scan_plugins_15m()           # Stage 2: 15min信号池
    → Hoffman_15m / ChanBS_15m / SuperTrend_15m
    → RSI_15m / EMA_Cross_15m / MACD_Hist_15m / BB_MeanRev_30m
    → gcc_push_signal() → 信号池
  → process_round()               # Stage 3: 树搜索
    → _drain_signals()            # 取出信号池
    → process()
      → _build_candidates()       # L1: BUY/SELL/HOLD三方向
      → _score_buy_candidate()    # ★ 评分核心
        → scan_score (扫描引擎信号)
        → win_rate_score (KNN历史胜率)
        → vwap_score (VWAP偏离)
        → signal_pool_score (外挂投票汇总)
        → value_score (KEY-003价值分析)
        → emphasis_weight (L2子策略权重)
        → aggregate = 加权总分
      → _score_sell_candidate()   # 镜像逻辑
      → _apply_pruning()          # 剪枝
        → P-1: 人类禁卖 (human_sell_block.json)
        → P0: 失败模式记忆 (KNN)
        → P1: 方向过滤 (SignalDirectionFilter)
        → P2: 仓位控制 (position >= max_units)
      → _run_puct_search()        # PUCT迭代(4轮×9节点)
      → _verify_triple()          # 三视角验证(Topology/Geometry/Algebra)
      → _select_best_candidate()  # 选aggregate最高节点
    → _write_pending_order()      # Stage 4: 写pending
  → llm_decide() B1块消费         # 执行
    → send_signalstack_order(source="gcc_tm")  # 美股
    → send_3commas_signal(source="gcc_tm")     # 加密
```

---

## 第三部分: 所有filter/gate/rule模块

### 门控层（按优先级从高到低）

| 优先级 | 模块 | 文件路径 | 功能 | 信号类型 | 频率 | 符合规则 |
|--------|------|---------|------|---------|------|---------|
| P-1 | 人类禁卖 | `state/human_sell_block.json` | 时间窗口内禁SELL指定品种 | 过滤 | 实时 | ✅规则1 |
| P0 | KNN失败模式 | `gcc_trading_module.py` | 历史失败信号指纹匹配→剪枝 | 过滤 | 每轮 | ✅规则1 |
| P1 | 方向过滤 | `price_scan_engine_v21.py` | ENFORCE模式禁反向信号 | 过滤 | 每轮 | ✅规则1 |
| P2 | 仓位控制 | `gcc_trading_module.py` | 满仓禁BUY/空仓禁SELL | 仓位管理 | 每轮 | ✅规则2 |
| — | KEY-001 Anchor | `llm_server_v3640.py` | 人类方向锚点冲突检查 | 过滤 | 每单 | ✅规则1 |
| — | KEY-001 动态 | `llm_server_v3640.py` | Vision缓存方向冲突 | 过滤 | 每单 | ✅规则1 |
| — | KEY-002 Regime | `llm_server_v3640.py` | 市场状态自适应阈值 | 过滤 | 每单 | 待评估 |
| — | AUD-052 翻转冷却 | `llm_server_v3640.py` | 方向翻转后30min冷却 | 过滤 | 每单 | ✅规则1 |
| — | MasterHub | `llm_server_v3640.py` | 多门控汇总(≥2 blocked→拦截) | 过滤 | 每单 | ✅规则1 |
| — | KEY-003 价值限买 | `llm_server_v3640.py` | 后5名max_units=4 | 仓位管理 | 每单 | ✅规则2 |
| — | GCC-TM独占 | `llm_server_v3640.py` | 非gcc_tm来源→[BLOCKED][非B1] | 过滤 | 每单 | ✅规则1 |
| — | 交易频率控制 | `modules/trade_frequency.py` | NORMAL: 7笔/日, 3笔/品种 | 过滤 | 每单 | ✅规则1 |
| — | 连续亏损熔断 | `llm_server_v3640.py` | 3连亏→限tier, 5连亏→停BUY | 过滤 | 每单 | ✅规则1 |

---

## 第四部分: 仓位管理模块

| 模块 | 文件路径 | 功能 | 信号类型 | 频率 | 符合规则 |
|------|---------|------|---------|------|---------|
| position_units | `llm_server_v3640.py` | 0-5档仓位跟踪 | 仓位管理 | 实时 | ✅规则2 |
| max_units | `llm_server_v3640.py` | KEY-003动态(后5名=4,其他=5) | 仓位管理 | 每日 | ✅规则2 |
| P2剪枝 | `gcc_trading_module.py` L1457-1463 | 满仓禁BUY/空仓禁SELL | 仓位管理 | 每轮 | ✅规则2 |
| 移动止盈 | `price_scan_engine_v21.py` | ATR突破→加仓(3→4→5) | 仓位管理 | 低频 | ❌规则3(无首次2限制) |
| 移动止损 | `price_scan_engine_v21.py` | ATR跌破→减仓(5→4→3) | 仓位管理 | 低频 | ❌规则5(无减至2逻辑) |
| HOLD_BAND | `llm_server_v3640.py` L8092-8214 | 唐纳奇低位阻止割肉 | 仓位管理 | 5min | ❌规则5(阻止减仓而非减至2) |
| coinbase_sync | `coinbase_sync_v6.py` | 实盘仓位同步到state | 仓位管理 | 每单后 | ✅规则2 |
| 道氏回调检测 | `llm_server_v3640.py` L7405 | SHALLOW/NORMAL/DEEP分级 | 不明确 | 每轮 | ⚠️检测有但无执行 |

---

## 第五部分: 关键缺陷分析

### 缺陷1: 仓位单位与决策脱节 ❌
- TreeNode只有 `action="BUY"/"SELL"`，无 `target_position` 字段
- 每次BUY加1档(由移动止盈逐步加)，但无强制"首次建2"
- 首次BUY可能只建1个，也可能连续信号快速到5个

### 缺陷2: 回调检测存在但不执行 ❌
- 道氏回调深度检测 ✅ (SHALLOW/NORMAL/DEEP)
- HOLD_BAND企稳检测 ✅ (PULLBACK_STABILIZING)
- **但无自动加减仓指令生成** — 检测了不执行

### 缺陷3: HOLD_BAND过度保护 ❌
- pos<25%阻止SELL → 应该是减至2而非禁止SELL
- 当前是被动等待反弹，不是主动管理仓位

### 缺陷4: 配额制与仓位管理矛盾 ⚠️
- 频率模块计"笔数"，仓位模块计"档位"
- 7笔BUY × 每笔+1档 = 可能7档(超过max_units=5由P2兜底)
- 应改为"轮次制"：首次→2档，确认→5档，回调→2档

---

## 第六部分: P0修复建议

### 修复1: TreeNode添加target_position
```
文件: gcc_trading_module.py
改动: TreeNode新增target_position字段
逻辑:
  vision_confidence < 0.7 → target=2 (规则3)
  pullback_stabilizing    → target=5 (规则4)
  pullback_in_progress    → target=2 (规则5)
  正常趋势               → target=3 (中间阶段)
```

### 修复2: 回调自动加减仓信号
```
文件: price_scan_engine_v21.py 或 gcc_trading_module.py
新增: check_pullback_rebalance()
逻辑:
  PULLBACK_IN_PROGRESS + pos>2 → SELL至2 (规则5)
  PULLBACK_STABILIZING + pos<5 → BUY至5 (规则4)
  信号推入GCC-TM信号池由B1统一决策
```

### 修复3: HOLD_BAND改为主动减仓
```
文件: llm_server_v3640.py
改动: pos<25%时减至2(而非禁止SELL)
```

---

*审计深度: 12个核心模块, 7个外挂, 8个门控点*
*审计完成: 2026-03-15*
