# Changelog

## [Unreleased]

### Changed
- **refactor(brooks-vision)**: v2.6 取消L2拦截和形态方向覆盖，简化信号流程
  - L2信号: 移除反方向拦截逻辑，仅记录用于日报统计(AGREE/NEUTRAL)
  - 形态方向校正: 移除PATTERN_SIGNAL_MAP覆盖GPT direction的逻辑，信任GPT判断
  - scan_symbol流程从7步精简为6步

### Fixed
- **fix(scan-engine)**: v21.27 移动止损/止盈豁免P0冷却和日限次 — CRWV保命信号被误封
  - `_notify_main_server()` 新增 `_p0_safety_exempt` 标志
  - 移动止损/止盈跳过 P0 fail 冷却 (v21.2) 和 P0 日限次 (v21.19)
- **fix(scan-engine)**: v21.26 `_get_position_and_max` max_units=None 防护
- **fix(scan-engine)**: v21.25 Coinbase 4H 请求 cap 300根 — ZEC HTTP 400 修复
- **fix(scan-engine)**: v21.24 移动止损/止盈豁免 FilterChain Vision gate
- **fix(main-server)**: v3.678 KEY-003 数据源改 `live` — OpenBB 故障不再降级 template
- **fix(main-server)**: v3.677 移动止盈补豁免 FilterChain + SignalGate (3处)

### Added
- **feat(scan-engine)**: v21.20 分型过滤器 `check_fractal_filter()` — 三外挂共用
  - BUY 遇顶分型拦截 / SELL 遇底分型拦截
  - SuperTrend / N字 / 缠论BS position control 后统一调用
- **feat(scan-engine)**: v21.20 加密货币数据源切换 Coinbase 优先
  - `_coinbase_fetch_candles()` 轻量版，失败降级 yfinance

### Changed
- **chore**: 根目录清理 — 旧脚本/空文件/MSI副本/已废弃状态文件移至 `backup/`
  - 删除20个文件 (-12486行): `log_analyzer_v3-BaoPCS.py`, `vision_comparison.py`, `_analyze_flips.py`, `gcc_dashboard_v497.html`, `scan_macd_divergence_state.json` 等
  - 数字编号空文件 (`2`~`10`) 清理

### Added
- **feat(KEY-006)**: Brooks Vision v2.3 — Al Brooks 形态识别合并到视觉雷达
  - `brooks_vision.py` (新): GPT-5.2 看4H蜡烛图 + Brooks价格行为形态识别
  - RADAR_PROMPT v2.3: 14概率锚点(Rose三年322期) + 6环境矩阵 + 5步分析法
  - 知识卡×7: Brooks PA (Always-In/反转形态/应用层) + Rose PA (2022/2023/2024/统一规则库)
  - scan_engine: `from brooks_vision import radar_tick` 集成
  - 删除旧 Brooks 外挂3文件 (-1340行): `brooks_pa_plugin.py`, `key004_brooks_pa.py`, `test_key004_brooks_pa.py`

---

## [v3.665] — 2026-02-23

### Fixed
- **fix(AUD-052)**: ZECUSDC 跨K线来回翻转冷却门控
  - 根因：缠论准确率 45.8% → L1 UP↔DOWN 频繁翻转 → 累计 -6.49 USD
  - L1 刷新时检测 `current_trend` 翻转，记录 `_last_direction_flip_time`
  - `send_3commas_signal` 新增 AUD-052 冷却门控（止损/止盈豁免）
  - `.gcc/params/ZECUSDC.yaml` 写入 `direction_flip_cooldown_bars: 4`（=16h）
  - 日志标签：`[AUD-052][DIR_FLIP_COOL]`

### Added
- **feat(KEY-001)**: Vision Cache 观察接入 Phase1
  - Vision 读取后存 `VisionSnapshot`（pattern/bias/confidence）
  - 数据写入 `state/vision_cache/index.db`
  - 开关：`KEY001_VC_OBS_ENABLED = True`，日志：`[KEY001-VCACHE][OBS]`

- **feat(KEY-004)**: Plugin Cache 观察接入 Phase1（SuperTrend）
  - SuperTrend 执行后存 `FeatureVector`（signal/mode/regime）
  - 数据写入 `state/cache/key004_features.db`
  - 开关：`KEY004_PC_OBS_ENABLED = True`，日志：`[KEY004-PCACHE][OBS]`

---

## [v3.664] — 2026-02-23

### Added
- **feat(KEY-001)**: Vision Cache 模块 `modules/key001_vision_cache.py`
  - `VisionSnapshot` 快照 + `VisionCalibration` 校准 + `EnhancedVisionResult` 增强结果
  - `VisionCache` 多时间框架偏差跟踪（1h/4h/1d/3d）
  - GateMode: observe / soft / full 三级门控
  - 独立可运行，支持 standalone 执行模式
  - 测试: `test_key001_vision_cache.py`

- **feat(KEY-004)**: Plugin Cache 模块 `modules/key004_plugin_cache.py`
  - `FeatureVector` + `KlineSignature` 特征向量缓存
  - `MFEMAEResult` 最大有利/不利价格分析
  - `CacheStorageBackend` SQLite 后端
  - `PluginAdapter` Protocol 接口
  - 测试: `test_key004_plugin_cache.py`

---

## [v3.663] — 2026-02-22

### Added
- **feat(KEY-001)**: 大师验证层 Phase1 观察接入 `llm_server_v3640.py`
  - `send_3commas_signal()` KEY-002 gate 后插入观察块（`MASTER_OBS_ENABLED=True`）
  - 三大师并行评估：Livermore（时机/入场质量）、Druckenmiller（宏观/可否决）、Connors（统计模式）
  - 输出 `[KEY001-MASTER][OBS]` 日志 + `state/audit/key001_master_validation.jsonl`
  - Phase1 不拦截任何信号，仅收集 CONFIRM/DOWNGRADE/UPGRADE 数据

### Tests
- **test(KEY-001)**: `test_key001_master_validation.py` 100轮回归测试完成
  - 覆盖边界用例：空 context、fail-open 异常、macro veto、UPGRADE 条件
  - 20/20 质检全通过

---

## [v3.662] — 2026-02-22

### Added
- **feat(P0)**: FilterChain 回测基准工具 `filter_chain_retrospective.py`
  - 用 1088 条真实交易历史，对 Volume + Micro 两道 Gate 回溯，计算净贡献基准
  - 支持 `--symbol` / `--gate` / `--export csv` / `--min-score` 参数
  - 输出到 `logs/retrospective/`（KEY-006 GCC-0040~0043）
- **feat(P0)**: P0 外挂参数分析工具 `p0_plugin_analysis.py`
  - 基于 `state/audit/signal_log.jsonl` 分析 N字结构分布、参数效果
  - 自动计算各外挂放行率、wave5_divergence 触发率、retrace_ratio 分布
  - AUD-052 根因分析支持

### Changed
- **feat(plugin)**: 外挂参数优化
  - `rob_hoffman_plugin.py`: 参数调整
  - `feiyun_plugin.py`: 参数调整
  - `macd_divergence_plugin.py`: 参数调整
- **feat(n_structure)**: `n_structure.py` N字结构微调

---

## [v3.661] — 2026-02-21

### Added
- **feat(key001)**: KEY-001 动态门控误杀控制 Phase B 上线
  - `modules/vision_adaptive.py` v1.2: 新增 `compute_key001_gate_score()` / `evaluate_key001_gate()` / `apply_key001_gate()`
  - `gate_score = signal_conf×0.35 + n_state×0.25 + trend×0.20 - risk×0.20`
  - phase/action 分桶阈值（ACCUM/DISTRIB/REDIST 差异化），软阻断 HOLD + 硬阻断 BLOCK
  - vision_result 为空时自动读取 `pattern_latest.json`
  - 审计日志：`state/audit/key001_gate_log.jsonl`
  - 移动止损/止盈豁免

- **feat(key002)**: KEY-002 Regime 自适应节奏止损 Phase B 上线
  - `modules/key002_regime.py` v1.0 (新建): 5种 Regime 检测 + 参数矩阵
  - SIDE_HIGH_VOL → cooldown=8h / threshold=0.70 / atr×1.28 / max_trades=1
  - EVENT_RISK → max_trades=0 全冻结
  - 审计日志：`state/audit/key002_regime_log.jsonl`
  - 移动止损/止盈豁免

- **feat(key005)**: KEY-005 ES 多分位风控校验 Phase A 观察
  - `modules/es_risk_backtest.py` v2.0: 双分位 VaR(97.5%)/VaR(99%)/ES(97.5%)
  - 多分位一致性检验 `mq_test_score`，GREEN/YELLOW/RED 三级
  - 下游联动 KEY-001/002 参数（Phase A 仅记录，未生效）
  - 状态文件：`state/risk_es_state_v2.json`

### Changed
- **llm_server_v3640.py** `send_3commas_signal()`:
  - Filter Chain 之后追加 KEY-001 + KEY-002 双重门控
  - 拦截链：Vision → Signal Gate → Filter Chain → **KEY-001** → **KEY-002** → 发单

---

## [v3.660] — 2026-02-21

### Fixed
- **fix(rhythm)**: 节奏评分永远50分 — `market_regime` 写入时补写 `position_pct` 字段
  - 问题: `_pos_in_channel_refresh` 已计算但未写入 `market_regime`，导致扫描引擎读到默认值 50.0，trade_history 全是 0.5，节奏评分永远 50/100
  - 修复: L3652-3653 写入 `position_pct = round(_pos_in_channel_refresh * 100, 1)`（条件: not None）
  - 文件: `llm_server_v3640.py`

### Changed
- **feat(signal_gate)**: KEY-006-T03 Signal Gate Phase2=True — 微观结构过滤真实拦截
  - 3处开关同步改 True: `SIGNAL_GATE_ENABLED` / `3C_ENABLED` / `LAST_ENABLED`
  - 已有 4h staleness guard fail-open 保证安全
  - 文件: `llm_server_v3640.py`

- **feat(plugin)**: PLUGIN_YAML_PHASE2=True — YAML `enabled: false` 外挂真实拦截
  - 一行改动将 disabled 外挂加入 `_gov_disabled`，主循环自动跳过
  - 影响: BTC/ETH/SOL/ZEC/NBIS/HIMS/RKLB 的 SuperTrend + HIMS/RKLB 的 trailing_profit
  - 文件: `llm_server_v3640.py`

### Fixed
- **fix(log_analyzer)**: 兼容 improvements.json v2.1 by-key 结构
  - 文件: `log_analyzer_v3.py`

- **perf(chart)**: ChartEngine 单例化 — vision_pre_filter 避免重复实例化
  - 模块级懒加载单例，热路径性能提升
  - 文件: `.GCC/scripts/vision_pre_filter.py`

---

## [v3.659] — 2026-02-20

### Fixed
- **fix(sys)**: SYS-020 — `calc_consensus_score()` 读 `regime`+`trend` 键修复（原 `market_regime` 键不存在）
- **fix(sys)**: SYS-022 — confidence 为 None 时默认 0.5，ema10 添加 None 保护
- **fix(sys)**: SYS-032 — `tracking_state` 初始化添加 `last_volume`/`avg_volume`

### Changed
- **feat(key001)**: Phase4 加密 N_GATE=BLOCK 真拦截，`_n_gate_active` 按 `{sym}_{BUY/SELL}` 缓存
- **feat(key002)**: Phase1 — `_key002_original_trend` 记录覆盖前后 DIFF/SAME → `state/key002_adaptive.json`
- **feat(low_acc_guard)**: 缠论准确率 <30%（样本 >=10）时 Phase1 记录，Phase2 降级 SIDE

---

## [v3.658] — 2026-02-19

### Fixed
- 25+ 处 `print` → `log_to_server` 修复（KEY-001/CIRCUIT_BREAKER/PORTFOLIO_BREAKER 等）

### Changed
- SYS-006 频率控制 Phase2 开启（enforce=True）
- SYS-017 组合熔断 Phase2 开启

---

## [v3.651] — 2026-02-18

### Fixed
- **fix(plugin)**: MACD 外挂执行路径修复 — v3.650 `else: send_ok=False` 误杀所有外挂信号
  - 修复: `elif plugin_bypass_l2` 分支在 else 前插入，交易记录块 de-indent 移出

---

## [v3.650] — 2026-02-17

### Changed
- L1 主循环 BUY/SELL 改为参考模式（不下单），P0/L2 STRONG/MACD 背离正常交易
- Vision 升级 GPT-5.2，覆盖阈值 >90% → >80%
- 移动止损低位割肉保护：唐纳奇 20 通道 pos<25% 且非急跌 → 阻止
- P0 发送失败 5 分钟冷却

---

## [v3.640] — 2026-02-10

### Changed
- 缠论替换道氏 7 层趋势判定
- x4 双算法：道氏摆点 vs 缠论竞争准确率
- 7 方校准器: rule/cnn/fused/vision/image_cnn/x4_dow/x4_chan
