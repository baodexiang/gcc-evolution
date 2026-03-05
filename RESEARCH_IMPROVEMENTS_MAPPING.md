# 论文驱动改善项全景图 — Paper IDs → Improvement IDs → Implementation Status

**生成时间**: 2026-02-14  
**数据源**: `state/improvements.json` (v4) + `.GCC/handoff.md` + `.GCC/skill/evolution-log.md` + `.GCC/research/reviews/`  
**目的**: 追踪所有论文驱动的改善项(RES-xxx)与系统改善项(SYS-xxx)的实现状态，识别重复与缺口

---

## 📊 Executive Summary

| 指标 | 数值 | 说明 |
|------|------|------|
| **总改善项数** | 51 | SYSTEM(31) + TOOL(11) + AUDIT(9) |
| **论文驱动项(RES)** | 8 | RES-001~008 |
| **已关闭** | 28 | CLOSED状态 |
| **进行中** | 20 | IN_PROGRESS状态 |
| **待验证** | 6 | TESTING状态 |
| **论文总数** | 4篇 | 2602.12030 + 2505.07078 + 2602.10798 + 2602.10785 |
| **已实现论文改善** | 6/8 | RES-001~006已编码, RES-007/008进行中 |
| **重复风险** | 中等 | SYS-020/RES-007/RES-008存在部分重叠 |

---

## 🔗 论文 → 改善项映射表

### 论文1: arXiv:2602.12030 (Time-Inhomogeneous Volatility Aversion)
**评分**: 4/5 | **目标模块**: 风控与节奏 | **发现日期**: 2026-02-12  
**论文链接**: https://arxiv.org/abs/2602.12030v1  
**精读报告**: `.GCC/research/reviews/2026-02-12_2602.12030v1.md`

#### 关联改善项
| 改善ID | 标题 | 状态 | 优先级 | 实现位置 | 验证状态 |
|--------|------|------|--------|---------|---------|
| **RES-007** | 趋势阶段风险预算 | IN_PROGRESS | P1 | `price_scan_engine_v21.py` L926-953 | Phase 1记录 |
| **RES-008** | 持仓时间衰减因子 | IN_PROGRESS | P1 | `price_scan_engine_v21.py` L6505-6538 | Phase 1记录 |
| **SYS-020** | 共识权重动态再平衡 | IN_PROGRESS | P1 | `llm_server_v3640.py` | Phase 1记录 |

#### 论文核心贡献
- **时间非齐次波动厌恶**: 不同持仓阶段(初期/中期/末期)设定不同风险容忍度
- **动态风险预算**: 初期降BUY门槛(-10%), 末期升门槛(+15%)
- **ATR制度倍数**: INITIAL=1.15(放宽), FINAL=0.85(收紧)

#### 实现细节
```
✅ RES-007 已编码:
  - estimate_trend_phase() 输出 phase + regime (bull/bear/sideways)
  - EMA动量确认 + market_regime标签
  - check_rhythm_quality() 读取trend_phase调整阈值
  
✅ RES-008 已编码:
  - _get_atr_threshold() 合并decay和atr_regime_mult
  - decay系数 0.7~1.0
  - atr_regime_mult: INITIAL=1.15, FINAL=0.85
  
⚠️ 待验证: 日志中是否观察到 `[v21.12] 阶段风险[观察]` 首次触发
```

---

### 论文2: arXiv:2505.07078 (FINSABER - LLM Financial Investing)
**评分**: 5/5 | **目标模块**: L1趋势判断 | **发现日期**: 2026-02-13  
**论文链接**: https://arxiv.org/abs/2505.07078  
**精读报告**: `.GCC/research/reviews/2026-02-13_oai_arXiv.org_2505.07078v5.md`

#### 关联改善项
| 改善ID | 标题 | 状态 | 优先级 | 实现位置 | 验证状态 |
|--------|------|------|--------|---------|---------|
| **RES-007** | 趋势阶段风险预算 | IN_PROGRESS | P1 | `price_scan_engine_v21.py` L953-1563 | Phase 1记录 |
| **SYS-020** | 共识权重动态再平衡 | IN_PROGRESS | P1 | `llm_server_v3640.py` | Phase 1记录 |

#### 论文核心贡献
- **市场制度感知**: LLM策略在牛市过度保守, 熊市过度激进
- **Regime自适应**: 牛市降BUY门槛(55%), 熊市升门槛(75%)
- **制度标签**: bull/bear/sideways三态判定

#### 实现细节
```
✅ RES-007 已编码 (v21.12增强):
  - estimate_trend_phase() 输出market_regime标签
  - check_rhythm_quality() 按regime调整阈值
  - scan_engine全局缓存market_regime
  
⚠️ SYS-020 部分覆盖:
  - REGIME_BASE_WEIGHTS已定义 (TRENDING/RANGING)
  - 但未与RES-007的market_regime标签同步
  - 需要determine_market_regime()向scan_engine暴露输出
  
⚠️ 待验证: 日志中是否观察到 `[v21.12] 阶段风险[观察]` 首次触发
```

---

### 论文3: arXiv:2602.10798 (CEX/DEX Trading with Delays)
**评分**: 4/5 | **目标模块**: 风控与节奏 | **发现日期**: 2026-02-11  
**论文链接**: https://arxiv.org/abs/2602.10798v1  
**精读报告**: `.GCC/research/reviews/2026-02-11_2602.10798v1.md`

#### 关联改善项
| 改善ID | 标题 | 状态 | 优先级 | 实现位置 | 验证状态 |
|--------|------|------|--------|---------|---------|
| **RES-001** | 节奏阈值品种分化 | TESTING | P1 | `price_scan_engine_v21.py` L1374-1385 | 待日志验证 |

#### 论文核心贡献
- **执行延迟建模**: CEX/DEX之间的随机延迟差异
- **动态节奏阈值**: 加密75%/美股65% (执行延迟风险分化)
- **多信号异步执行**: 共识度投票考虑信号源延迟

#### 实现细节
```
✅ RES-001 已编码:
  - check_rhythm_quality() BUY阈值按品种分化
  - 加密货币: BUY>75%, SELL跌破+5%
  - 美股: BUY>65%, SELL跌破标准
  
⚠️ 待验证: 日志中是否观察到 `[v21.12] 节奏品种分化` 记录
```

---

### 论文4: arXiv:2602.10785 (Walk-Forward Optimization)
**评分**: 4/5 | **目标模块**: 校准器与EMA | **发现日期**: 2026-02-12  
**论文链接**: https://arxiv.org/abs/2602.10785v1  
**精读报告**: `.GCC/research/reviews/2026-02-11_2602.10785v1.md`

#### 关联改善项
| 改善ID | 标题 | 状态 | 优先级 | 实现位置 | 验证状态 |
|--------|------|------|--------|---------|---------|
| **RES-004** | 动态τ过滤 | TESTING | P2 | `llm_server_v3640.py` L5070 | 待日志验证 |
| **RES-006** | EMA窗口品种分化 | TESTING | P2 | `price_scan_engine_v21.py` L1534 | 待日志验证 |

#### 论文核心贡献
- **Walk-Forward优化**: 历史回测与前向验证的动态平衡
- **噪声样本过滤**: 排除涨跌<1%的样本(τ过滤)
- **品种自适应**: 加密EMA8/美股EMA5

#### 实现细节
```
✅ RES-004 已编码:
  - verify_pending() 新增最小运动过滤器 (τ=1%)
  - |change_pct|<1% 样本排除不参与统计
  
✅ RES-006 已编码:
  - check_ema5_momentum_filter() 新增symbol参数
  - 加密货币: EMA8
  - 美股: EMA5
  
⚠️ 待验证: 日志中是否观察到 `[v21.12] τ过滤` 和 `EMA分化` 记录
```

---

### 论文5: arXiv:2602.11020 (View-Aligned Robustness)
**评分**: 4/5 | **目标模块**: Vision与校准器 | **发现日期**: 2026-02-12  
**论文链接**: https://arxiv.org/abs/2602.11020v1  
**精读报告**: `.GCC/research/reviews/2026-02-11_2602.11020v1.md`

#### 关联改善项
| 改善ID | 标题 | 状态 | 优先级 | 实现位置 | 验证状态 |
|--------|------|------|--------|---------|---------|
| **RES-002** | Vision过度自信降权 | TESTING | P1 | `llm_server_v3640.py` L15379 | 待日志验证 |
| **RES-003** | 校准器晚期融合诊断 | TESTING | P2 | `llm_server_v3640.py` | 待日志验证 |

#### 论文核心贡献
- **多视角鲁棒性**: 单一视角(Vision)过度自信的风险
- **分歧度决策**: divergence>0.15时提高Vision覆盖阈值至90%
- **晚期融合**: 7方样本量加权平均 + 视角分歧度

#### 实现细节
```
✅ RES-002 已编码:
  - Vision conf>95% 且与big_trend冲突 → 降权×0.6
  - 降权后若<=80% → 放弃覆盖, 使用缠论基线
  
✅ RES-003 已编码:
  - get_weights() 新增late_fusion_score (7方加权)
  - view_divergence (准确率标准差)
  - 仅诊断数据, 不改变决策流
  
⚠️ 待验证: 日志中是否观察到 `Vision降权` 和 `分歧度` 记录
```

---

## 🎯 改善项实现状态矩阵

### TESTING组 (6项 — 待日志验证)
```
RES-001: 节奏品种分化 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.10798
  └─ 代码: price_scan_engine_v21.py L1374-1385
  └─ 验证: 搜日志 `[v21.12] 节奏品种分化` 或 `加密75%/美股65%`

RES-002: Vision过度自信降权 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.11020
  └─ 代码: llm_server_v3640.py L15379
  └─ 验证: 搜日志 `Vision降权` 或 `conf>95%`

RES-003: 校准器晚期融合 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.11020
  └─ 代码: llm_server_v3640.py (get_weights)
  └─ 验证: 搜日志 `late_fusion_score` 或 `view_divergence`

RES-004: 动态τ过滤 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.10785
  └─ 代码: llm_server_v3640.py L5070
  └─ 验证: 搜日志 `τ过滤` 或 `|change|<1%`

RES-005: 分歧度决策 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.11020
  └─ 代码: llm_server_v3640.py L15379
  └─ 验证: 搜日志 `divergence>0.15` 或 `Vision阈值90%`

RES-006: EMA品种分化 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.10785
  └─ 代码: price_scan_engine_v21.py L1534
  └─ 验证: 搜日志 `EMA分化` 或 `加密EMA8/美股EMA5`
```

### IN_PROGRESS组 (20项 — Phase 1观察中)
```
RES-007: 趋势阶段风险预算 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.12030 + arXiv:2505.07078
  └─ 代码: price_scan_engine_v21.py L926-953, L1562-1600
  └─ 验证: 搜日志 `[v21.12] 阶段风险[观察]` 首次触发

RES-008: 持仓时间衰减 ✅编码 ⏳验证
  └─ 论文: arXiv:2602.12030
  └─ 代码: price_scan_engine_v21.py L6505-6538
  └─ 验证: 搜日志 `[v21.12] 时间衰减` 或 `decay×atr_regime_mult`

SYS-011: 跨周期共识度评分 ✅编码 ⏳验证
  └─ 代码: price_scan_engine_v21.py + llm_server_v3640.py
  └─ 验证: 搜日志 `consensus_score` 或 `|score|<0.30`

SYS-015: Position Control SQS量价门槛 ✅编码 ⏳验证
  └─ 代码: modules/volume_analyzer.py + llm_server_v3640.py
  └─ 验证: 搜日志 `[SQS]` 或 `rel_vol×close_pos`

SYS-016: 外挂信号统一量价过滤(VF) ✅编码 ⏳验证
  └─ 代码: modules/volume_analyzer.py + llm_server_v3640.py
  └─ 验证: 搜日志 `[VF]` 或 `REJECT/DOWNGRADE/UPGRADE`

SYS-017: 连续亏损熔断 ✅编码 ⏳验证
  └─ 代码: llm_server_v3640.py
  └─ 验证: 搜日志 `3连亏限tier` 或 `5连亏停BUY`

SYS-018: StrategyEvaluator管道 ✅编码 ⏳验证
  └─ 代码: log_to_equity.py (新建)
  └─ 验证: 搜日志 `CAGR/Sharpe/MaxDD/PF/WinRate`

SYS-019: 组合相关性风控 ✅编码 ⏳验证
  └─ 代码: modules/correlation_monitor.py
  └─ 验证: 搜日志 `rho>0.7` 或 `限仓60%`

SYS-020: 共识权重动态再平衡 ✅编码 ⏳验证
  └─ 论文: arXiv:2505.07078 (FINSABER)
  └─ 代码: llm_server_v3640.py (REGIME_BASE_WEIGHTS)
  └─ 验证: 搜日志 `TRENDING→Tech45%` 或 `RANGING→Human40%`

SYS-021: 多源数据交叉验证 ✅编码 ⏳验证
  └─ 代码: llm_server_v3640.py (OHLCVWindow.check_staleness)
  └─ 验证: 搜日志 `staleness>300s` 或 `数据延迟告警`

SYS-022: Position Control置信度门控 ⏳编码
  └─ 代码: price_scan_engine_v21.py (check_position_control)
  └─ 验证: 搜日志 `confidence→Tier门槛`

SYS-023: Regime自适应数据窗口 ⏳编码
  └─ 代码: price_scan_engine_v21.py (get_recent_high_low)
  └─ 验证: 搜日志 `lookback: TRENDING→20`

SYS-024: 滑点与成交质量追踪 ⏳编码
  └─ 代码: llm_server_v3640.py (signal_price/fill_price)
  └─ 验证: 搜日志 `slippage>10bps` 或 `fill_time`

SYS-025: 趋势健康度(CVD+relVol) ✅编码 ⏳验证
  └─ 代码: models/volume_analyzer.py + price_scan_engine_v21.py L1350
  └─ 验证: 搜日志 `trend_health` 或 `CVD×relVol`

SYS-026: Donchian量价增强 ✅编码 ⏳验证
  └─ 代码: models/volume_analyzer.py + price_scan_engine_v21.py L1600
  └─ 验证: 搜日志 `donchian_score` 或 `
