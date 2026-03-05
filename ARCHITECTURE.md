# 交易系统架构说明

## 信号流程

```
K线数据
  │
  ▼
┌──────────────────────────────────────────┐
│ 过滤层 (Vision Filter)                    │
│ vision_pre_filter.py                     │
│                                          │
│  ┌─────────────────────────────────┐     │
│  │ 1. Anchor 方向冲突检查           │     │
│  │    anchor=SHORT + BUY → BLOCK   │     │
│  ├─────────────────────────────────┤     │
│  │ 2. Vision 看图（Claude/GPT-5.2）│     │
│  │    形态识别 + Wyckoff阶段        │     │
│  │    → visual_bias (BUY/SELL/HOLD)│     │
│  ├─────────────────────────────────┤     │
│  │ 3. KNN 历史相似度（本地计算）   │     │
│  │    当前K线 vs 历史库             │     │
│  │    → knn_bias                   │     │
│  ├─────────────────────────────────┤     │
│  │ 4. filter_gate: 只有完全相反才  │     │
│  │    拦截，HOLD全放行              │     │
│  └─────────────────────────────────┘     │
│  输出: PASS / BLOCK                      │
└──────────────────────┬───────────────────┘
                       │ PASS
                       ▼
┌──────────────────────────────────────────┐
│ 外挂层 (Plugins) — 并行运行               │
│                                          │
│  n_structure.py       N字门控外挂         │
│  chan_bs_plugin.py    缠论买卖点外挂      │
│  double_pattern_plugin.py  双底双顶形态   │
│  rob_hoffman_plugin.py     Rob Hoffman   │
│  compute_signal_plugin.py  计算信号外挂   │
│    └─ EMA交叉/RSI超卖/MACD零轴           │
│    └─ 纯数值，不依赖图像                 │
│                                          │
│  输出: PluginSignal (方向+entry+SL+TP)   │
└──────────────────────┬───────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────┐
│ 校准层 (Calibrator)                       │
│ HumanDualTrackCalibrator                 │
│                                          │
│  输入:                                   │
│    L1 规则信号                           │
│    CNN 图像识别                          │
│    Vision latest.json（方向/置信度）     │
│    ← vision_analyzer.py 每30min写入      │
│                                          │
│  输出: 最终方向（UP/DOWN/SIDE）          │
└──────────────────────┬───────────────────┘
                       │
                       ▼
                  发单执行
          send_signalstack_order()
          send_3commas_signal()


## 文件职责

| 文件 | 层 | 职责 |
|------|----|------|
| vision_pre_filter.py | 过滤层 | 每次发单前：形态+Wyckoff+KNN → PASS/BLOCK |
| vision_analyzer.py | 校准输入 | 后台daemon，每30min写 latest.json |
| compute_signal_plugin.py | 外挂层 | 纯数值：EMA/RSI/MACD → PluginSignal |
| n_structure.py | 外挂层 | N字结构门控 |
| chan_bs_plugin.py | 外挂层 | 缠论二三买卖点 |
| double_pattern_plugin.py | 外挂层 | 双底双顶（调Vision API判断形态） |
| .GCC/scripts/anchor_calibrate.py | 工具 | 每日8点：Vision看图 → 写 GCC anchor |
| .GCC/scripts/knn_history_builder.py | 工具 | 一次性构建KNN历史库 |

## Vision 的两种使用方式（职责不同）

```
方式A：Vision 作为「过滤器」
  vision_pre_filter.py
  → 调 Claude/GPT-5.2 看当前图
  → 输出 PASS/BLOCK（阻止错误位置的交易）

方式B：Vision 作为「校准输入」
  vision_analyzer.py (后台进程)
  → 每30分钟分析所有品种
  → 写 state/vision/latest.json
  → HumanDualTrackCalibrator 读取
  → 影响最终方向判断（不直接产生信号）
```

两者互不干扰：A 是实时过滤，B 是定期校准。

## Phase 状态

| 组件 | Phase | 说明 |
|------|-------|------|
| vision_pre_filter | Phase1 | `VISION_FILTER_PHASE2=False`，只记录不拦截 |
| compute_signal_plugin | Phase1 | 未接入主程序，独立测试中 |
| KNN历史库 | 未初始化 | 需运行 `knn_history_builder.py` |
| KEY-004外挂因子化 | Phase1 | `_PLUGIN_YAML_PHASE2=False` |
```
