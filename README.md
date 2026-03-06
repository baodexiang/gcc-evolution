# AI Trading Bot

自动化多品种量化交易系统，基于 LLM + 技术指标 + 外挂策略三层架构。

## 版本

| 文件 | 版本 |
|------|------|
| `llm_server_v3640.py` | v3.677 |
| `price_scan_engine_v21.py` | v21.27 |
| `monitor_v3640.py` | v3.610 |
| `log_analyzer_v3.py` | v3.14 |
| `vision_analyzer.py` | v3.x (文件头版本历史到v3.1, 统一链路口径) |
| `brooks_vision.py` | v2.6 (KEY-006 Brooks Vision) |
| `n_structure.py` | v2.0 |
| `modules/vision_adaptive.py` | v1.3 (KEY-001 Phase B) |
| `modules/key002_regime.py` | v1.0 (KEY-002 Phase B) |
| `modules/es_risk_backtest.py` | v2.0 (KEY-005 Phase A) |

**Vision 修复补充（Unreleased）**：
- `vision_analyzer.py` 形态写入 `pattern_latest.json` 采用“按 symbol 合并更新”，避免单次写入覆盖其他品种结果
- 基准价回填统一使用 `analyze_patterns()` 内部 `bars` 数据按 `bars_ago` 定位，避免变量错用导致基准价写入异常

## 架构概述

```
K线数据
  │
  ▼
Vision Filter (vision_pre_filter.py)
  │  Anchor冲突检查 + GPT-5.2看图 + KNN历史相似
  ▼
L1 趋势判断 (llm_server_v3640.py)
  │  缠论K线合并 + x4大周期 + Vision覆盖
  ▼
L2 信号检测 (price_scan_engine_v21.py)
  │  空间确认 + STRONG_BUY/SELL拦截
  ▼
外挂层 (各plugin)
  │  N字门控 / 缠论BS / 双底双顶 / SuperTrend / Brooks Vision
  ▼
Position Control (v20.7)
  │  0~5档逐级升降 + 移动止盈止损
  ▼
KEY-001 动态门控 (modules/vision_adaptive.py)
  │  phase/action分桶阈值 + gate_score → PASS/HOLD/BLOCK
  ▼
KEY-002 Regime门控 (modules/key002_regime.py)
  │  5种Regime参数矩阵 + entry_threshold → 放行/拦截
  ▼
下单 (Coinbase API)
```

### 改善模块 (KEY系列)

| KEY | 模块 | 状态 | 作用 |
|-----|------|------|------|
| KEY-001 | `modules/vision_adaptive.py` | **Phase B 上线** | Vision动态门控，按Wyckoff阶段差异化阈值，降低误杀 |
| KEY-001 | `modules/key001_vision_cache.py` | Phase A 观察 | Vision快照缓存+多时间框架偏差跟踪，VisionCache + 校准层 |
| KEY-001 | `modules/key001_master_validation/` | **Phase1 观察接入** | 三大师验证层（Livermore/Druckenmiller/Connors），纯观察模式 |
| KEY-002 | `modules/key002_regime.py` | **Phase B 上线** | Regime自适应节奏，震荡期自动收紧cooldown/threshold/止损 |
| KEY-004 | `modules/key004_plugin_cache.py` | Phase A 观察 | 外挂执行缓存，FeatureVector+KlineSignature+MFE/MAE分析 |
| KEY-005 | `modules/es_risk_backtest.py` | Phase A 观察 | ES多分位风控校验，GREEN/YELLOW/RED三级联动 |
| KEY-006 | `brooks_vision.py` | **v2.6 上线** | Brooks Vision雷达：GPT-5.2看图+21种形态(MAP驱动方向)+EMA/RSI过滤 |

**拦截豁免**：移动止损、移动止盈信号绕过全路径门控（P0冷却/P0日限次/FilterChain/SignalGate/KEY-001/002，保命优先）

## 品种

**美股 (11个)**: TSLA, COIN, RDDT, NBIS, CRWV, RKLB, HIMS, OPEN, AMD, ONDS, PLTR

**加密货币**: BTCUSDC, ETHUSDC, SOLUSDC, ZECUSDC

## 常用命令

```bash
# 启动主服务
python llm_server_v3640.py

# 启动扫描引擎
python price_scan_engine_v21.py

# 启动监控面板
python monitor_v3640.py

# 每日日志分析
python log_analyzer_v3.py --daily

# 冻结美股卖出（低位保护）
python freeze_stock_sell.py

# 恢复外挂配额
python reset_quota_patch.py

# 热重载扫描引擎状态
curl -X POST http://127.0.0.1:6002/reload_state

# FilterChain 回测基准（KEY-006 净贡献分析）
python filter_chain_retrospective.py
python filter_chain_retrospective.py --symbol SOLUSDC
python filter_chain_retrospective.py --gate volume   # 只跑 Volume Gate
python filter_chain_retrospective.py --gate micro    # 只跑 Micro Gate
python filter_chain_retrospective.py --export csv

# P0 外挂参数分析（基于历史日志推导建议值）
python p0_plugin_analysis.py
```

## 关键配置

- 外挂启用/禁用: `config/plugins.yaml`
- 品种周期参数: `timeframe_params.py`
- 改善管理: `python manage_improvements.py list`

## KEY-001 大师验证层

- 路径: `modules/key001_master_validation/`
- 结构: `MasterValidationHub` + `Livermore/Druckenmiller/Connors` + `decision_policy` + `audit` + `evo`
- **状态: Phase1 观察模式已接入主程序**（`send_3commas_signal()` KEY-002 gate 之后）
- 开关: `MASTER_OBS_ENABLED = True`（纯观察，不拦截任何信号）
- 豁免: 移动止损/止盈信号跳过
- 审计日志: `state/audit/key001_master_validation.jsonl`
- 配置:
  - `modules/key001_master_validation/config/key001_master_policy.yaml`
  - `modules/key001_master_validation/config/key001_master_weights.yaml`
- 验证:
  - `pytest test_key001_master_validation.py`
  - `grep "[KEY001-MASTER][OBS]" logs/server.log | tail -20`

## 扫描引擎特性 (v21.20+)

- **分型过滤器** (`check_fractal_filter`): BUY遇顶分型拦截/SELL遇底分型拦截，三外挂共用
- **Coinbase数据源优先**: 加密货币先走Coinbase API，失败降级yfinance
- **P0安全豁免** (v21.27): 移动止损/止盈跳过P0冷却和日限次

## 数据流

- `market_regime` 字段包含 `position_pct`（唐纳奇通道位置百分比），供扫描引擎节奏评分使用
- 状态持久化: `state/` 目录
- 日志: `logs/` 目录

## 进化记录

见 `.GCC/skill/evolution-log.md`（每次代码修改自动追加）

## 架构详细说明

见 `ARCHITECTURE.md`
