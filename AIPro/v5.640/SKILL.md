---
name: L1 Solution
use_deepseek_api: true
deepseek_model: deepseek-chat
description: L1趋势/震荡判断准确性分析与系统自我进化工具。**v3.677+v21.27+Vision统一链路**。**Claude只写代码，其他用DeepSeek**。**GCC-0194**(Vision+BrooksVision合并单次GPT调用+x4改EMA三线排列+L1趋势与外挂解耦+共识度权重归零+主程序去重复过滤)。**v21.27**(含trailing状态恢复；当前口径：移动止损/止盈纳入FilterChain)。**v3.677**(GCC-0193三管线审计修复+移动止损/止盈豁免anchor拦截)。**KEY-007 KNN五层架构**(modules/knn/ v1.000)。**GCC-0174**(知识卡活化CardBridge+蒸馏+KNN闭环)。
---


## 当前运行实况 (2026-03-07)

- 主程序: llm_server_v3640.py = 3.677 + GCC-0197 log tag fix ([GCC-0197] 替换 [KEY-009][S4])
- 扫描引擎: price_scan_engine_v21.py = 21.27
- P0-Tracking: 默认关闭（P0_TRACKING_ENABLED=False）
- 移动止损/止盈: 运行中，且纳入 FilterChain 审核
- FilterChain豁免白名单: BrooksVision / VisionPattern / 双底双顶
- P0-CycleSwitch: 路由保留，_run_cycle_switch_analysis() 下单开关已关闭
- KEY-010 方向过滤: `AIPro/signal_direction_filter.py` 已接入 `/p0_signal` 前置记录与方向评估（S6/S7/S8/S9）
- KEY-010 运行模式: `OBSERVE_ONLY = True`（仅记录 would_block，不做真实拦截）
- KEY-009 Dashboard: `/key009` 与 `/key009/json` 输出 `review_status.signal_filter`（OBSERVE/ENFORCE/OFF）
- L2评分当前生效口径: 总分 `±16`（历史 `±22` 仅用于追溯，不作为当前实盘口径）
- 说明: 文档中的历史版本段落用于追溯，需以本节“当前运行实况”为准

## ⚠️ 工具分工原则

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude (写代码专用)                      │
├─────────────────────────────────────────────────────────────┤
│  ✅ 修改主程序代码 (llm_server_v3xxx.py)                     │
│  ✅ 修改扫描引擎 (price_scan_engine_v20.py)                  │
│  ✅ 修改Vision分析器 (vision_analyzer.py)                    │
│  ✅ 修改监控程序 (monitor_v3xxx.py)                          │
│  ✅ 其他Python代码修改/新增                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  DeepSeek API (分析/文档)                    │
├─────────────────────────────────────────────────────────────┤
│  ✅ /aipro solution - L1趋势分析                             │
│  ✅ /aipro check - L2信号检测(含BIAS25/Cycle Gate/唐安琪路由复查) │
│  ✅ /aipro vision - Vision覆盖效果分析                       │
│  ✅ /aipro update - 文档同步更新 + 发布前自检(Go/No-Go)      │
│  ✅ /aipro 30m 自动更新任务 (一键自检 + 快速状态 + 失败快查 + 调度快修 + 进程自愈重启) │
│  ✅ evolution-log.md 经验记录                                │
│  ✅ skill.md 文档更新                                        │
│  ✅ 各种分析报告生成                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## v20.7 Position Control 立体仓位控制 (2026-02-06)

### 核心原则
```
先查仓位数 → 再定买卖条件 (避免来回打脸)
v20.7: 严格逐级 + 移动止盈直通 + 中间档放宽 + 极端仓位放松 + 急跌保护 + 暴跌连卖
```

### BUY转换 (v21.32 取消趋势限制+仅EMA过滤)
| 转换 | v21.32条件 | 说明 |
|------|-----------|------|
| 0→1 | 前1根阳线(P0直通) | 无K线数据→拒绝 |
| 1→2 | >EMA5 + 前2根合并阳 + (突破实体高OR加分) | 突破改OR加分项 |
| 2→3 | >EMA10 + body合并阳 + (突破实体高OR加分) | 突破改OR加分项 |
| 3→4 | >EMA10 + body合并阳 + (突破实体高OR加分) | 突破改OR加分项 |
| 4→5 | price>EMA10 | v21.32取消current=UP趋势限制,仅EMA过滤 |

### SELL转换 (v21.32 取消趋势限制+仅EMA过滤+暴跌连卖)
| 仓位 | 卖点 | v21.32条件 | 目标 |
|------|------|-----------|------|
| 5 | 一卖 | 前1根阴 | →**4档(逐级)** |
| 4 | 二卖 | <EMA5 + 前2根合并阴 + (跌破实体低OR加分) | →**3档(逐级)** |
| 3 | 三卖 | <EMA10 + body合并阴 + (创新低OR加分) | →**2档(逐级)** |
| 2 | 四卖 | <EMA10 + body合并阴 + (创新低OR加分) | →**1档(逐级)** |
| 1 | 清仓 | price<EMA10 | →**0档** (v21.32取消current=DOWN趋势限制) |
| 急跌 | crash_mode | 当前K线跌≥5% → 跳过所有条件 | 逐级减1 + 允许同K线卖2次 |

### 移动止盈/止损 (v20.7 直通+按仓位选阈值)
```
移动止盈/止损: 直通所有仓位(不经PC条件检查)
├── 首尾仓位(0↔1, 4↔5): 双阈值
│   ├── 第1次: ATR(14)动态阈值 (按资产类型+市场状态，8AM刷新)
│   └── 第2次: 固定阈值
├── 中间仓位(2/3/4): 固定阈值(美股3.0%, 加密3.5%, ZEC 4.0%)
└── 每天2次买+2次卖配额
```

### 急跌保护 (v20.5) + 暴跌连卖 (v20.7)
```
当前K线跌幅≥5%时，绕过三层限制:
├── check_position_control(): crash_mode跳过条件
├── check_plugin_daily_limit(): 绕过sell_used配额
├── check_first_position_bar_freeze(): 绕过K线内冻结
├── 移动止损: 绕过trailing_stop_count>=2限制
└── v20.7: 允许同K线卖出2次(crash_sell_this_cycle追踪)
```

### v21 L2空间位置确认 (新增)
```
check_l2_recommendation(): 5个外挂在x4过滤后插入L2空间确认
├── L2=STRONG_SELL → 阻止BUY
├── L2=STRONG_BUY → 阻止SELL
├── 普通BUY/SELL → 不阻止
└── 急跌SELL → 绕过

v3.620 5方校准 (HumanDualTrackCalibrator):
├── 追踪: rule, cnn, fused, vision, image_cnn 5方准确率
├── CNN覆盖: CNN准确率 > 融合准确率 → 跳过融合直接用CNN
├── Vision覆盖: Vision准确率 > L1 winner准确率 → Vision覆盖L1
├── 8AM邮件: 5方对比报告 (monitor发送)
└── 双底双顶: 取消x4和当前周期方向限制(形态反转不受趋势过滤)
```

### v20.7关键函数
- `check_new_high_breakout(bars, price)` - 突破5根实体高确认
- `check_new_low_breakdown(bars, price)` - 跌破5根实体低确认
- `check_position_control()` - 返回3元组 (allowed, reason, target_position)
- `check_l2_recommendation()` - L2空间确认(v21新增)
- `is_crash_bar()` - 急跌检测(跌幅≥CRASH_SELL_THRESHOLD_PCT)
- `_get_atr_threshold()` - ATR(14)动态阈值(24h缓存+8AM刷新)
- `_classify_asset_type()` - 自动分类资产(科技股/BTC/ETH/中型币/山寨币)
- `_check_trailing_stop()` - 移动止盈/止损(按仓位选阈值)

### 保留函数
- `merge_body_intersection_bars(bars)` - 按body交集合并K线段
- `check_body_merged_bullish/bearish(bars)` - body合并后阳/阴判断
- `check_merged_bars_bullish/bearish(bars, count)` - N根合并后阳/阴判断

---

## DeepSeek API处理 (分析/文档/skill更新)

**所有skill统一走 `/aipro` 子模式（solution/check/vision/update）并使用DeepSeek API处理**
**v57补充**：30m任务在“调度快修”后，需追加“进程自愈重启”（停旧进程 → 启动主进程 → 核验PID）确保修复即时生效。

```
DeepSeek负责:
├── 趋势分析和判断
├── L2信号检测报告
├── Vision覆盖效果分析
├── 文档同步更新 (skill.md)
├── 30m任务运维闭环 (自检/状态/失败快查/调度快修/进程自愈重启)
├── 开源发布自检清单执行 (Go/No-Go)
├── 经验记录 (evolution-log.md)
└── 改善建议生成

Claude负责:
└── 实际代码修改 (需要时由用户触发)
```

### /aipro 主程序最新框架同步 (2026-02-25)

| 文件 | 版本 | 说明 |
|------|------|------|
| `llm_server_v3640.py` | v3.677 | 主决策服务器 (GCC-0194: 去重复过滤, Vision+BV合并) |
| `price_scan_engine_v21.py` | v21.27 | 扫描主循环 + trailing状态恢复（部分外挂调用按当前配置注释/停用） |
| `vision_analyzer.py` | v3.x | Vision+BrooksVision统一链路 (文件头版本历史至v3.1) |
| `monitor_v3640.py` | v3.640(显示层) / 头注v3.610 | 实时仪表板（版本标识待统一） |
| `log_analyzer_v3.py` | v3.14 | KEY-009四管线日志审计 + CardBridge Phase门控检测 |
| `n_structure.py` | v2.0 | N字5状态门控 (已转外挂, 主程序仅观察) |
| `modules/knn/` | v1.000 | KEY-007 KNN五层架构 (L1模型+L2存储+L3进化+L4编排+L5对齐) |
| `gcc_evolution/card_bridge.py` | v1.1 | 知识卡活化 (CardBridge查询+蒸馏+因果记忆) |
| `macd_divergence_plugin.py` | v1.0 | MACD背离 (GCC-0173双通道日志) |
| `filter_chain_worker.py` | v1.2 | FilterChain BG线程 (唯一过滤入口) |

**开源发布基线补充（v5.260）**:
- 冻结程序基线：`./.GCC/doc/gcc_v5260.zip`
- 需求文档（含验收矩阵+启动前自检）：`./.GCC/improvement/03022026/GCC 开源发布计划.docx`
- `/aipro update` 在开源发布语境下必须附带：基线差异摘要 + P0/P1自检通过率 + Go/No-Go 结论 + 验收矩阵覆盖结论
- 若用户要求“完整复查原始代码和结构”，`/aipro update`必须追加：冻结包结构核查 + 当前代码结构核查 + 差异清单 + 风险分级

**建议输出模板**:
- Baseline: `MATCH/MISMATCH` + 变更文件清单
- Matrix: `covered/partial/missing` 统计 + missing项
- Checklist: `P0 pass=x/y`, `P1 pass=x/y`
- Decision: `Go/No-Go`
- Next Actions: 3条（含owner）
- 机器可读JSON块：`baseline/matrix/checklist/decision/next_actions`
- 完整复查附加块：`frozen_structure/current_structure/diff/risk_levels`

```text
输入层
  TradingView -> /llm_decide(4H主路径), /tv_l2_10m(30m L2)
  yfinance/Coinbase -> price_scan_engine_v21.py 轮询
  vision_analyzer.py -> state/vision/pattern_latest.json

决策层
  llm_server_v3640.py (v3.677)
    - L1趋势 + x4 EMA(7/14/20)
    - L2 Macro评分 + 30m快速通道
    - KEY-001/002/003 + Breaker + Position门禁
  price_scan_engine_v21.py (v21.27)
    - 外挂扫描 + L2空间确认 + trailing状态恢复

过滤层
  filter_chain_worker.py (v1.2) -> state/filter_chain_state.json
    - Vision / Volume / Micro 三闸门
    - trailing stop/take + BrooksVision/VisionPattern/双底双顶豁免

执行层
  P0/插件信号 -> /p0_signal -> 3Commas / SignalStack
  BrooksVision v2.6: 读pattern_latest.json + EMA/RSI/L2本地验证

状态与审计层
  state/*.json + logs/*.log + log_analyzer_v3.py(v3.14)
  /key009 + dashboard + evolution-log
  review_status.signal_filter (KEY-010观察状态字段)
```

## KEY-010: Signal Direction Filter (观察模式)

```text
模块:
  AIPro/signal_direction_filter.py

核心常量:
  THRESHOLD=0.50
  MIN_SAMPLE=1
  WARNING_THRESHOLD=0.50
  RETENTION_DAYS=7
  WINDOW_4H=4
  OBSERVE_ONLY=True

接入点:
  llm_server_v3640.py -> /p0_signal -> handle_p0_signal()
    S6: record_signal() 记录有效信号
    S7: evaluate_direction() 计算4h/周方向占优
    S8: BUY路径调用 filter_signal() (观察模式)
    S9: SELL路径调用 filter_signal() (观察模式)

可观测性:
  /key009, /key009/json 注入 review_status.signal_filter
  key009_dashboard.html 显示 SignalFilter: OBSERVE/ENFORCE/OFF

行为口径:
  观察模式下, filter_signal() 永远返回 True
  仅记录 would_block 事件, 不阻断实际下单
```

**信号发单管线 (三条平行线, GCC-0194重构)**:
```text
管线A: 外挂信号 (主力) [GCC-0171审计]
  外挂: SuperTrend / 飞云 / RobHoffman / 缠论买卖点 / 双底双顶
  → FilterChain Vision门控 (扫描引擎统一过滤, 主程序不再重复)
  → 移动止损/止盈也走FilterChain（不再豁免）
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

```text
关键口径:
1) GCC-0194: x4改EMA(7/14/20)三线排列, 取消5模块投票
2) GCC-0194: L1趋势与外挂完全解耦, 外挂不依赖趋势方向
3) GCC-0194: Vision+BrooksVision合并为单次GPT调用(vision_analyzer统一缓存链路)
4) GCC-0194: 共识度权重全部归零(外挂不需要任何趋势过滤)
5) GCC-0194: 主程序去掉N-Gate/HOLD_BAND/signal_gate/FilterChain重复过滤
6) v21.27口径: 仓位控制按现行EMA条件执行, trailing状态可持久化恢复
7) FilterChain: 扫描引擎为唯一过滤入口, 当前豁免仅BrooksVision/VisionPattern/双底双顶
8) KEY-007 KNN五层架构(modules/knn/ v1.000, 周级迭代)
9) GCC-0174: 知识卡活化CardBridge(查询+蒸馏+KNN闭环+因果记忆)
10) gcc-evo v5.250 流程: observe → analyze → suggest → gate → rollout → handoff
11) KEY-010: signal_direction_filter 已接入 /p0_signal, 当前为 OBSERVE_ONLY
12) KEY-009 Dashboard 已展示 SignalFilter 模式状态字段 review_status.signal_filter
```

**DeepSeek分析要点**:
- L1x4大周期趋势/震荡判断准确性
- L1当前周期趋势/震荡判断准确性
- 结合知识卡片(Wyckoff/ICT/Al Brooks)给出改善建议
- SuperTrend外挂触发准确性
- **v3.460 L2门卫机制验证**(大周期STRONG→小周期交易→冻结)
- **v3.465 P1改善项验证**(20EMA趋势过滤+Power Candle+量堆式拉升)
- **v3.470 后台OHLCV更新器验证**(多周期缓存维护+Coinbase API)
- **v3.472 回退模式API获取真实OHLCV**(fetch_ohlcv_from_api+避免high==low)
- **v3.472 TV数据优先级保护**(_last_tv_update_time+5分钟保护窗口)
- **v3.491 ADX阈值优化+价格强制判断+位置一致性**
- **v3.492 L2量价异常检测**(6种量价异常+形态量价背离)
- **v3.499 回滚v3.498 HOLD放行**(L1外挂用plugin_bypass_l2不走门卫，HOLD放行只影响L2小周期→回滚)
- **v3.499 唐纳奇通道策略强化**(L2位置确认反馈到L1+五大类评分±17)
- **v3.540 趋势转折同步到扫描引擎**(sync_trend_to_scan_engine_v3540+global_trend_state.json持久化+启动时L1刷新后同步)
- **v3.545 L1外挂移交扫描引擎**(RobHoffman+双底双顶+飞云移交扫描引擎v15；双底双顶改用current_trend；飞云新建独立外挂文件；MACD背离保持10分钟)
- **v3.550 鲁本威科夫知识应用**(L1增强:VPOC迁移验证+价值区域重叠检测；L2增强:假突破无法重入规则+累积分配量能特征；评分内部优化总分±22不变)
- **v3.551 美股L1当前趋势自适应修复**(自适应DOW回看窗口:美股16/8/25 vs 加密货币60/30/120；30分钟定时刷新用TV同周期4H K线；仅开盘时段刷新；加密货币不受影响)
- **v3.551 剥头皮外挂state.json读取bug修复**(扫描引擎`_get_current_trend_for_scalping()`查找`state["symbols"]`但品种在根级别+直接取`current_trend`但实际嵌套在`_last_final_decision.three_way_signals.market_regime`→永远返回SIDE→剥头皮从不激活；修复后使用与`_get_current_trend()`一致的深层路径)
- **v3.560 系统健壮性升级**(24项修复:P0×3原子写入+SELL状态+NY时区；P1×11 FIFO卖出+统一仓位+HTTP重试+日志轮转+剥头皮状态保护+4外挂save+冻结日期重置+趋势fallback；P2×10 SignalStack冷却+bare except+3commas重试+趋势缓存TTL+优雅关闭+safe_json_read)
- **v3.581 Vision架构统一+x4定义统一**(独立程序vision_analyzer.py成为唯一Vision来源；统一用big_trend消除trend_x4混淆；Vision覆盖当前周期regime或direction变化；P0-Tracking不受趋势限制)
- **v3.585 DeepSeek替代GPT-5.1**(L1分析改用DeepSeek,成本降低90%;仲裁保留)
- **v3.586 顺大逆小修复+AI UNKNOWN fallback**(get_scalp_daily_bias改用big_trend;AI判断UNKNOWN时从context.trend.x4提取;清理unused trend_x4参数;Monitor显示V:前缀)
- **v3.600 动态TV周期适配**(timeframe_params.py中央参数源;L1/L2/P0/Vision全动态;外挂固定4H;Vision v2.9 GPT-4o only移除Claude API)
- **v3.610 L2打分修正+L2空间确认+MACD修复**(L2阈值统一±8/±4;SR veto保护;exec_bias写入GTS;check_l2_recommendation()空间确认;MACD 30m预加载buffer120+放松参数)
- **v3.620 三方对比测试+5方校准+双底双顶取消x4**(5方dual_track:rule/cnn/fused/vision/image_cnn;CNN覆盖融合;Vision准确率覆盖L1;图像CNN ResNet18;双底双顶取消x4和当前周期方向限制;8AM 5方邮件报告)
- **v3.640 缠论替换道氏7层+x4双算法**(缠论K线合并+三段判定替换7层道氏管道;x4道氏vs缠论准确率竞争;Vision>90%覆盖缠论基线;7方校准器;14列面板L1用/x4用;趋势转折邮件改善;CJK对齐修复;PLTR启动刷新;plugin_profit_tracker恢复)
- **v21.32 仓位控制取消趋势限制**(GCC-0194: 4→5/1→0取消current=UP/DOWN限制,仅保留EMA过滤;Rob Hoffman v2.0.1恢复;FilterChain豁免调整:止损/止盈也过滤)
- **v21 扫描引擎+v20.7 PC极端放松**(暴跌同K线卖2次;按仓位选阈值;L2空间确认5外挂插入)

---

## ⭐⭐⭐ 严格检查: L1→L2趋势/震荡传递与策略执行

### 检查1: L1 x4大周期趋势/震荡判断准确性

**必须验证L1 x4大周期判断是否与K线图一致:**

| L1 x4判断 | K线图特征 | 正确标准 |
|-----------|-----------|----------|
| **UP趋势** | HH+HL(更高高点+更高低点) | ADX>阈值 + 道氏理论确认上升 |
| **DOWN趋势** | LH+LL(更低高点+更低低点) | ADX>阈值 + 道氏理论确认下降 |
| **SIDE震荡** | 高低点无规律/区间内 | ADX<阈值 + 价格在通道内 |

### 检查2: L1当前周期趋势/震荡判断准确性

**必须验证L1当前周期判断是否稳定且准确:**

| 检查项 | 合格标准 | 问题表现 |
|--------|----------|----------|
| 判断准确性 | 与实际K线走势一致 | 明显趋势判为SIDE |
| 判断稳定性 | 每10根K线≤1次切换 | 频繁在UP/DOWN/SIDE跳动 |
| 与x4一致性 | 当前周期≤大周期 | 大周期DOWN但当前判UP |

### 检查3: L1→L2大周期传递准确性

**必须验证L1判断是否正确传递到L2:**

```
L1层输出 (v3.586统一命名):
  ├─ big_trend: UP/DOWN/SIDE (x4大周期趋势，五模块综合判断)
  ├─ current_trend: UP/DOWN/SIDE (当前周期趋势，Human模块，可被Vision覆盖)
  ├─ regime_x4: TREND_UP/TREND_DOWN/RANGING (x4周期状态)
  └─ pos_in_channel: 0.0-1.0 (位置)
       ↓
L2层接收:
  ├─ big_trend: = L1的big_trend (顺大逆小用此值)
  ├─ wyckoff_phase: 由big_trend+pos计算
  └─ l2_strategy: 由wyckoff_phase决定
       ↓
扫描引擎:
  ├─ trend_x4: = big_trend (同步传递)
  └─ 顺大逆小: big_trend=UP→只做多, DOWN→只做空, SIDE→双向
```

### 检查4: L2策略执行（最重要）

**L2必须根据不同趋势/震荡执行不同策略:**

| L1 x4趋势 | Wyckoff阶段 | L2策略 | 交易方向 |
|-----------|-------------|--------|----------|
| **UP** | MARKUP | 顺大逆小：回调买 | 只做多 |
| **DOWN** | MARKDOWN | 顺大逆小：反弹卖 | 只做空 |
| **SIDE+低位** | ACCUMULATION | 高抛低吸：低买 | 底部买入 |
| **SIDE+高位** | DISTRIBUTION | 高抛低吸：高卖 | 顶部卖出 |
| **SIDE+中间** | RANGING | 不交易 | 观望 |

---

## 每日复盘节奏 (2次/天，每次12小时)

| 时间 | 覆盖范围 | 重点 |
|------|----------|------|
| **美东 9:00 AM** | 前12小时(21:00-09:00) | 加密货币夜盘+亚洲盘 |
| **美东 9:00 PM** | 前12小时(09:00-21:00) | 美股盘中+欧洲盘 |

**复盘流程**:
1. 运行 `/aipro check` → 检查L2信号准确性
2. 运行 `/aipro solution` → 分析L1→L2传递问题
3. 查阅知识卡片 → `skill/INDEX.md` 找解决方案
4. 设计改善方案
5. 更新 `evolution-log.md` → 记录经验

---

## 核心职责

1. **K线截图分析**: 查看 `regime-review/MMDDYYYY/` 目录下当日K线截图
2. **日志对比**: 结合交易日志分析L1判断是否准确
3. **准确性评估**:
   - L1x4 (大周期4倍) 趋势/震荡判断准确性
   - L1当前周期 趋势/震荡判断准确性
4. **知识卡片应用**: 读取 `cards/` 目录下的知识卡片，用于完善主程序
5. **自我进化**: 基于分析结果和知识卡片改善主程序代码
6. **经验积累**: 每次分析后更新 `evolution-log.md`

## 自我进化流程

```
┌─────────────────────────────────────────────────────────────────┐
│  1. 读取知识                                                     │
│     ├─ INDEX.md → 找到相关知识卡片                               │
│     ├─ cards/ → 读取具体知识内容                                 │
│     └─ evolution-log.md → 读取历史经验                          │
│                                                                 │
│  2. 分析准确性                                                   │
│     ├─ regime-review/MMDDYYYY/ → K线截图                        │
│     ├─ logs/ → 交易日志                                         │
│     └─ 对比L1x4/L1当前周期判断 vs 实际行情                       │
│                                                                 │
│  3. 改善主程序                                                   │
│     ├─ 发现问题 → 结合知识卡片找解决方案                         │
│     ├─ 修改代码 → llm_server_v3xxx.py                           │
│     └─ 验证效果 → 下次复盘检验                                   │
│                                                                 │
│  4. 记录经验                                                     │
│     └─ 更新 evolution-log.md                                    │
└─────────────────────────────────────────────────────────────────┘
```

## 工作流程

### 1. 读取历史经验
```
开始任务前：
1. 读取 skill/evolution-log.md（实战经验）
2. 读取 skill/INDEX.md（知识卡片索引）
3. 按需读取 skill/cards/ 中的具体卡片
```

### 2. 执行任务
```
结合历史经验 + 知识卡片 + 当前上下文完成任务
```

### 3. 记录新经验
```
任务完成后，将新发现追加到 skill/evolution-log.md
```

## 目录结构

```
skill/
├── SKILL.md                 ← 本文件（技能说明）
├── evolution-log.md         ← 动态经验（持续积累）
├── INDEX.md                 ← 知识卡片索引
├── regime-review/           ← 趋势复盘技能
│   ├── SKILL.md             ← 复盘技能说明
│   ├── MMDDYYYY/            ← 按日期存放截图
│   └── review/              ← 复盘报告输出
└── cards/                   ← 知识卡片（按来源分类）
    ├── Al Brooks 教程/
    ├── Wyckoff 方法/
    ├── ICT 系列/
    └── ...其他来源/
```

## 知识体系

### 静态知识（cards/）
- 来自视频、书籍的学习笔记
- 按原始来源分类
- 查询时先看 INDEX.md 找到对应卡片

### 动态经验（evolution-log.md）
- 实战中积累的经验
- 踩过的坑、验证过的模式
- 每次任务后更新

## 经验分类

### P0: 核心交易逻辑
- 市场状态检测（趋势 vs 盘整）
- 入场/出场决策框架
- 风险管理规则
- **L1 Supertrend 外挂验证**
- **v3.460 L2 门卫机制验证**
- **v3.465 P1 改善项验证**
- **v3.466 TradingView信号数据增强**
- **v3.470 后台OHLCV更新器**(多周期缓存维护)
- **v3.472 回退模式API获取真实OHLCV**(道氏理论支持)
- **v3.472 TV数据优先级保护**(5分钟保护窗口)

### P1: 系统架构
- 多模块协作模式
- API 集成（3Commas, SignalStack, Schwab）
- 线程安全和并发处理

### P2: 调试和监控
- 日志分析模式
- 异常处理最佳实践
- 性能优化技巧

### P3: 知识管理
- 知识卡片应用
- Wyckoff / ICT / Al Brooks 理论应用

---

## v3.586 变量命名规范验证

### 统一命名规范

| 变量 | 含义 | 来源函数 | 用途 |
|------|------|----------|------|
| `big_trend` | x4大周期趋势(UP/DOWN/SIDE) | `compute_ai_big_trend_v3300()` | 顺大逆小策略 |
| `current_trend` | 当前周期方向(UP/DOWN/SIDE) | `compute_human_phase_v3300()` | 外挂时机判断 |
| `regime_x4` | x4周期震荡/趋势状态 | AI模块 | 状态分类 |
| `current_regime` | 当前周期震荡/趋势状态 | AI模块 | 状态分类 |

### 验证检查点

```bash
# 检查顺大逆小是否使用big_trend
grep "get_scalp_daily_bias" logs/server.log | tail -5
# 应显示: [v3.586] 剥头皮每日偏向: ... [顺大逆小]

# 检查AI UNKNOWN fallback
grep "AI x4_regime fallback" logs/server.log | tail -5
# 应显示: [v3.586] AI x4_regime fallback: context.trend.x4=...

# 检查Vision覆盖显示
# Monitor界面应显示: V:UP / V:DOWN / V:SIDE (带V:前缀表示Vision覆盖)
```

### DeepSeek仲裁验证 (x4大周期)

```bash
# AI+Tech分歧时DeepSeek仲裁
grep "DEEPSEEK_ARBITER" logs/server.log | tail -5
# 应显示: consensus=DEEPSEEK_ARBITER, big_trend=...
```

### KAMA ER阈值8AM自动分析

```bash
# 每天纽约8AM运行ER阈值分析
grep "ER Analysis\|ER Analyzer" logs/monitor.log | tail -10
# 应显示阈值调整报告

# 检查状态文件
cat state/er_threshold_state.json
# 显示: chandelier_threshold, hoffman_threshold, last_analysis时间
```

**触发位置**: `monitor_v3585.py` L3584-3600

---

## L1 Supertrend 外挂验证

### 外挂激活条件

L1 Supertrend 外挂用于在特定条件下覆盖常规 L1 判断。验证时需检查：

```python
# 关键字段
SUPERTREND_ACTIVE = True/False      # 外挂是否激活
SUPERTREND_DIRECTION = UP/DOWN      # Supertrend 方向
L1_OVERRIDE = True/False            # 是否覆盖了 L1 判断
OVERRIDE_REASON = "supertrend"      # 覆盖原因
```

### 验证步骤

#### 1. 检查日志中的 Supertrend 状态
```bash
# 查看 Supertrend 外挂激活记录
tail -500 logs/SYMBOL | grep -E "(SUPERTREND|supertrend|ST_|外挂)"
```

#### 2. 验证激活条件是否满足
| 条件 | 说明 | 检查方法 |
|------|------|----------|
| Supertrend 翻转 | ST 从红变绿或绿变红 | 检查 ST_FLIP 字段 |
| 价格位置 | 价格相对 Supertrend 线位置 | 检查 PRICE_VS_ST |
| 趋势确认 | 与大周期趋势一致 | 检查 L1x4_TREND |
| 成交量确认 | 翻转时放量 | 检查 VOLUME_RATIO |

#### 3. 验证外挂是否有效激活
```markdown
## 有效激活条件
- [ ] Supertrend 发生翻转
- [ ] 翻转方向与 L1x4 大周期一致
- [ ] 价格站稳 Supertrend 线之上/下
- [ ] 成交量放大（可选）
- [ ] L1 被正确覆盖

## 无效激活情况
- ❌ 震荡市中频繁翻转（假信号）
- ❌ 翻转方向与大周期相反
- ❌ 价格立即回穿 Supertrend 线
```

#### 4. 复盘时验证
在 regime-review 复盘时，增加 Supertrend 外挂验证：

```markdown
| 标的 | ST翻转时间 | 翻转方向 | L1x4方向 | 外挂激活 | 后续走势 | 有效性 |
|------|-----------|----------|----------|----------|----------|--------|
| TSLA | 09:30 | UP | UP | ✅ | +2.5% | ✅ 有效 |
| AMD | 10:15 | DOWN | UP | ❌ | +1.2% | ✅ 正确未激活 |
| COIN | 11:00 | UP | DOWN | ❌ | -3.0% | ✅ 正确未激活 |
```

### 日志解析命令

```bash
# 查看 Supertrend 外挂激活历史
grep -E "SUPERTREND.*ACTIVE|ST_FLIP|L1_OVERRIDE" logs/SYMBOL | tail -50

# 统计激活次数
grep -c "SUPERTREND.*ACTIVE=True" logs/SYMBOL

# 查看激活时的上下文（前后5行）
grep -B5 -A5 "SUPERTREND.*ACTIVE=True" logs/SYMBOL
```

### 准确率计算

```markdown
## Supertrend 外挂准确率统计

| 指标 | 数值 |
|------|------|
| 总激活次数 | X |
| 有效激活（方向正确） | Y |
| 无效激活（假信号） | Z |
| 准确率 | Y/X = ?% |

## 改进建议
- 如果准确率 < 70%：考虑增加过滤条件
- 常见假信号场景：震荡市、与大周期相反
```

---

## 经验记录格式

```markdown
### [日期] [P0-P3] 标题

- **场景**: 什么情况
- **问题**: 遇到什么
- **解决方案**: 如何解决
- **代码片段**: (可选)
- **教训**: 一句话总结
```

## 使用示例

**用户**: 帮我分析这个是不是 Wyckoff Spring

**Claude 执行流程**:
1. 读取 `skill/INDEX.md` 找到 Wyckoff 相关卡片
2. 读取 `skill/cards/Wyckoff 方法/Spring.md`
3. 结合知识分析用户问题
4. 如有新发现，追加到 `skill/evolution-log.md`

---

**用户**: 验证 TSLA 的 Supertrend 外挂是否有效激活

**Claude 执行流程**:
1. 读取 `logs/TSLA` 最近记录
2. 检查 Supertrend 翻转时间和方向
3. 对比 L1x4 大周期趋势
4. 验证外挂激活条件是否满足
5. 对比截图验证实际走势
6. 计算准确率，给出改进建议

---

**用户**: 验证 L2 信号的 P1 改善项是否正确应用

**Claude 执行流程**:
1. 读取 `logs/server.log` 查找 `v5.465` 相关记录
2. 检查 20 EMA 趋势过滤器是否正确计算
3. 验证 Power Candle 检测是否识别力量K线
4. 确认量堆式拉升检测是否正确计算
5. 统计各改善项对信号质量的提升效果

---

**用户**: 验证 BTCUSDC 的 L2 门卫机制是否正常工作

**Claude 执行流程**:
1. 读取 `logs/server.log` 查找 `v3.460.*L2 Gate` 记录
2. 检查大周期信号是否正确更新门卫状态
3. 验证小周期交易是否在允许条件下执行
4. 确认交易后是否正确进入冻结状态
5. 检查仓位管理是否与大周期一致（满仓不买/空仓不卖）
6. 检查 `l2_gate_state.json` 持久化状态
7. 统计门卫机制准确率，给出改进建议

---

## v3.465 P1 改善项验证

### P1-1: 20 EMA 趋势过滤器

```
价格 > 20 EMA + EMA斜率向上  → BULLISH
价格 < 20 EMA + EMA斜率向下  → BEARISH
回调信号: 价格接近EMA(±1%) + 趋势明确 → pullback_signal=True
```

### P1-2: Power Candle 力量K线检测

```
Bullish Power: HIGH=CLOSE + 上影线<5% + 实体>=60%
Bearish Power: LOW=CLOSE + 下影线<5% + 实体>=60%
强度等级: 实体60-70%=1级 | 70-80%=2级 | 80%+=3级
```

### P1-3: 量堆式拉升检测

```
量堆条件: 连续3根以上K线 成交量 > 平均成交量×1.2
动能强度: 3-4根=MODERATE | 5-6根=STRONG | 7根+=VERY_STRONG
脉冲量警告: 单根成交量 >= 平均×3 → pulse_volume_warning=True
```

---

## v3.460 L2 门卫机制验证 (v3.499更新)

```
大周期 STRONG_BUY  → 小周期 BUY/STRONG_BUY  → 允许买入一次
大周期 STRONG_SELL → 小周期 SELL/STRONG_SELL → 允许卖出一次
大周期 BUY/SELL    → 小周期同向信号 → 允许交易一次
大周期 HOLD        → 门卫关闭 → L2小周期不允许交易 (v3.499修复)
交易后 → 冻结状态 → 等待下一个大周期方向变化才解冻 (v3.499修复)
```

**v3.499架构说明**:
- **L2小周期**(10分钟webhook): 必须经过check_l2_gate()门卫
- **L1外挂**(SuperTrend/Rob Hoffman): 使用plugin_bypass_l2，不走门卫

---

## v3.466 TradingView信号数据增强

### 背景
Pine Script v3 增强了TradingView向主程序传输的信号数据，解决了4096字符限制问题。

### 传输字段

| 类别 | 字段 | 说明 |
|------|------|------|
| **Donchian通道** | donchian_upper/lower/basis | 锁定的上一根K线通道值 |
| **位置指标** | pos_in_channel, pos_in_bb | 价格在通道/布林带中位置(0-100%) |
| **OHLCV** | open, high, low, close, volume | 当前K线完整数据 |
| **RSI/ATR** | rsi14, atr14 | 相对强弱+真实波幅 |
| **EMA20** | ema20, ema_trend, price_above_ema | 均线+趋势(up/down/flat)+价格位置 |
| **MACD** | macd_line/signal/hist/trend | MACD(12,26,9)完整数据 |
| **MACD交叉** | macd_cross_over/under | 金叉/死叉信号 |
| **布林带** | bb_upper/lower/basis | 布林带(20,2σ)三轨 |
| **布林指标** | bb_width_pct, bb_squeeze | 宽度百分比+挤压信号 |
| **成交量** | vol_ratio | 当前成交量/20日均量 |
| **突破信号** | signal, level | cross_over/under + upper/basis/lower |
| **PA边界** | pa_buy_edge, pa_sell_edge | 价格行为买卖边界 |

### 文件
- `skill/AI_Donchian_LLM_Signal_v3.txt` - Pine Script v3源码

### 验证
```bash
grep "macd_line\|bb_squeeze\|ema_trend" logs/server.log | tail -10
```

---

## 版本更新代码复查 (superpowers集成)

> 详细流程见 `.GCC/skill/version-review.md`

### 触发方式

- 用户输入 `/review` 或 "复查主程序"
- 每次版本更新后自动提示

### 复查流程

```
1. 读取 evolution-log.md 最新更新记录
2. 定位 llm_server_v3xxx.py 主程序文件
3. 按P0→P2优先级验证核心模块:
   - P0: L2 Gate时序、Wyckoff稳定性、五大类评分、门卫机制、唐纳奇反馈
   - P1: 线程安全、状态持久化、异常处理
   - P2: 日志记录、版本标记
4. 生成复查报告
5. 记录到 evolution-log.md
```

### v3.488+ 必查清单

| 检查项 | 代码位置 | 验证要点 |
|--------|----------|----------|
| L2 Gate时序 | line 38462-38470 | 在10m修正之后调用 |
| Wyckoff缓存 | line 2990-2994 | 全局缓存+线程锁 |
| 阶段确认 | line 34698-34740 | 连续2根K线确认 |
| 五大类评分 | line 17167-17450 | 形态±6+位置±4+量能±2+Wyckoff±2+每日偏向±2 (v3.500移除唐纳奇±3) |
| 门卫机制 | line 7490-7627 | STRONG信号触发小周期 |

### 与superpowers技能集成

本复查流程基于 `superpowers:requesting-code-review` 设计:

1. **定位变更**: 读取evolution-log确定变更点
2. **代码审查**: 使用grep/read验证实现
3. **生成报告**: 按模板输出复查结果
4. **记录经验**: 更新evolution-log.md

